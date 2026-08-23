import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import ragtagCssText from "./RagTag.css?inline";
import RagTagRules from "./rules.jsx";
import {
  lobbyCss, LobbyHeader, LobbySectionHd, TurnBadge, LobbyLoading, LobbyEmpty,
  LobbyAction, LobbyTabs, notWaiting, GameMenu, gameMenuCss,
  createModalCss, CreateModal, CmRow, CmSeg, LobbyCreateRow, lobbyCreateRowCss,
  RulesModal, rulesModalCss, useProgressiveList,
  readLobbyCache, writeLobbyCache,
} from "../../shared/lobby.jsx";
import { buildPath, pushPath, replacePath, subscribe } from "../../shared/router.js";

/* Rag Tag — a two-player auto battler.
 *
 * The one thing that shapes this whole file: the game is SIMULTANEOUS. There is
 * no "your turn". Both players submit secretly and the round resolves when both
 * are in, so every prompt here is "you owe a submission" and every wait is
 * "waiting for them", never "waiting for the board".
 *
 * The FIGHT! step is resolved server-side in one go and arrives as `beats` — one
 * entry per turn with both revealed cards and every delta. This component plays
 * them back with a dwell so the fight reads as a fight rather than a diff. The
 * beats live in GAME STATE, so a reconnect mid-animation re-ships them.
 */

const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const WS_BASE = WS_RAW.replace(/\/ws$/, "");
const RT_WS = `${WS_BASE}/ragtag/ws`;
const RT_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/ragtag");

const ragtagStyles =
  lobbyCss + gameMenuCss + createModalCss + lobbyCreateRowCss + rulesModalCss + ragtagCssText;

//: How long one turn of the fight sits on screen before the next flips.
const BEAT_MS = 900;

function timeAgo(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function useSocket(onMessage) {
  const wsRef = useRef(null);
  const [connected, setConnected] = useState(false);
  const onMsg = useRef(onMessage);
  onMsg.current = onMessage;
  const connect = useCallback((url, firstMsg) => {
    try { wsRef.current?.close(); } catch {}
    const ws = new WebSocket(url);
    wsRef.current = ws;
    ws.onopen = () => { setConnected(true); if (firstMsg) ws.send(JSON.stringify(firstMsg)); };
    ws.onclose = () => setConnected(false);
    ws.onmessage = (e) => { try { onMsg.current(JSON.parse(e.data)); } catch {} };
  }, []);
  const send = useCallback((obj) => { try { wsRef.current?.send(JSON.stringify(obj)); } catch {} }, []);
  const disconnect = useCallback(() => {
    try { wsRef.current?.close(); } catch {}
    wsRef.current = null; setConnected(false);
  }, []);
  return { connected, connect, send, disconnect };
}

/* ── Rendering the mechanics ──────────────────────────────────────────────
 * Cards arrive from /catalog as op lists rather than printed text, because the
 * generated data is mechanics only — no publisher wording, no art. So the UI
 * says what a card DOES in its own vocabulary. That is also why the same op list
 * can drive the board, the log and the tooltip without three transcriptions.
 */

const TARGET_WORD = {
  self: "you", partner: "your partner", opp: "the opponent",
  opp_partner: "their partner", both_opps: "both opponents",
  all_others: "everyone else", all: "everyone",
};

function valueWord(n) {
  if (typeof n === "number") return String(n);
  if (!n) return "?";
  if (n.kind === "power") return "your Power";
  if (n.kind === "attacking_opponents_power") return "the blocked Power";
  if (n.kind === "spirits") return n.times > 1 ? `${n.times} per Spirit` : "1 per Spirit";
  return "?";
}

function opWords(op) {
  if (!op) return "";
  switch (op.op) {
    case "attack": {
      const who = op.target && op.target !== "opp" ? ` ${TARGET_WORD[op.target]}` : "";
      const by = op.by === "partner" ? " (partner)" : "";
      return `Attack${who}${by}`;
    }
    case "block": return "Block";
    case "damage": return `${valueWord(op.n)} damage to ${TARGET_WORD[op.target || "opp"]}`;
    case "heal": return `Heal ${valueWord(op.n)} — ${TARGET_WORD[op.target || "self"]}`;
    case "power": {
      const n = valueWord(op.n);
      const sign = typeof op.n === "number" && op.n < 0 ? "" : "+";
      return `${sign}${n} Power — ${TARGET_WORD[op.target || "self"]}`;
    }
    case "transfer_power": return `Move ${valueWord(op.n)} Power to ${TARGET_WORD[op.to]}`;
    case "cancel": return "Cancel their card";
    case "track": return `+${valueWord(op.n)} ${op.track.replace(/_/g, " ")}`;
    case "ignite": return "Set them Aflame";
    case "plant_scheme": return "Plant a Scheme";
    case "unleash_scheme": return "Unleash a Scheme";
    case "give_token": return `Pass the ${op.token} token`;
    case "take_token": return `Take the ${op.token} token`;
    case "flip_card": return "Turn this card over";
    case "spirit": return "+1 Spirit";
    case "if": return `If ${condWords(op.cond)}: ${op.then.map(opWords).join(", ")}`
      + (op.else ? ` — else ${op.else.map(opWords).join(", ")}` : "");
    case "fx": return "Special";
    default: return op.op;
  }
}

function condWords(cond) {
  if (!cond) return "?";
  switch (cond.kind) {
    case "power_at_least": return `you have ${cond.n}+ Power`;
    case "hp_equals": return `you are on ${cond.n} HP`;
    case "no_opponent_attacked": return "neither opponent attacks";
    case "self_attacked": return "you are attacked";
    case "own_attack_blocked": return "your attack is blocked";
    case "opponent_played_starting_card": return "they played their Starting Card";
    case "serpent": return `the ${cond.face} serpent shows`;
    case "face": return cond.face === "bodvar" ? "still human" : "transformed";
    case "ships": return `${cond.min}–${cond.max} Ships`;
    case "has_token": return `you hold the ${cond.token}`;
    case "token_on": return `${TARGET_WORD[cond.who]} holds the ${cond.token}`;
    default: return cond.kind;
  }
}

function cardText(card) {
  if (!card) return "";
  const main = (card.ops || []).map(opWords).filter(Boolean);
  const bonus = [];
  for (const op of card.ops || []) {
    if (op.success) bonus.push(`Success: ${op.success.map(opWords).join(", ")}`);
  }
  return [...main, ...bonus].join(" · ");
}

/* ── Board pieces ─────────────────────────────────────────────────────── */

function FighterCard({ fid, state, board, active, struck }) {
  if (!state || !board) return <div className="rt-fighter" />;
  const track = trackFor(state, board);
  const hpNow = spaceValue(track, state.hp);
  const hpMax = Math.max(0, ...track.filter((s) => s.kind === "hp").map((s) => s.hp));
  const ko = track.length && state.hp != null && track[state.hp]?.kind === "ko";
  const chips = [];
  for (const [name, n] of Object.entries(state.tokens || {})) {
    if (name === "serpent_face") {
      chips.push(<span className="rt-chip" key={name}>{n ? "black" : "white"} serpent</span>);
      continue;
    }
    if (n > 0) chips.push(<span className="rt-chip" key={name}><b>{n}</b> {name}</span>);
  }
  if (state.planted > 0) chips.push(<span className="rt-chip" key="planted"><b>{state.planted}</b> planted</span>);
  for (const [name, n] of Object.entries(state.tracks || {})) {
    chips.push(
      <span className="rt-chip" key={`t-${name}`}>
        {name.replace(/_/g, " ")} <b>{name === "divine_voice" ? (n < 0 ? "halo" : n + 1) : n}</b>
      </span>);
  }
  return (
    <div className={`rt-fighter${active ? " rt-active" : ""}${ko ? " rt-ko" : ""}${struck ? " rt-struck" : ""}`}>
      <div className="rt-fname">
        {board.name}
        {state.face === "berserker_bear" && <span className="rt-tag">BEAR</span>}
        {state.character && <span className="rt-tag">{state.character}</span>}
      </div>
      <div className="rt-stats">
        <span className="rt-hp">{ko ? "KO" : hpNow}<small>/{hpMax}</small></span>
        <span className="rt-pw">{state.power}<small> pw</small></span>
      </div>
      <div className="rt-bar">
        <span style={{ width: `${hpMax ? Math.max(0, Math.min(100, (hpNow / hpMax) * 100)) : 0}%` }} />
      </div>
      {chips.length > 0 && <div className="rt-chips">{chips}</div>}
    </div>
  );
}

function trackFor(state, board) {
  if (state.face === "berserker_bear" && board.back) return board.back.hp_track || [];
  if (board.characters) {
    const ch = board.characters.find((c) => c.id === state.character);
    return ch ? ch.hp_track : [];
  }
  return board.hp_track || [];
}

function spaceValue(track, idx) {
  if (!track || idx == null || !track[idx]) return 0;
  return track[idx].kind === "hp" ? track[idx].hp : 0;
}

function TeamSide({ label, mine, team, fighters, catalog, activeSlot, struckSlots }) {
  return (
    <div className={`rt-side${mine ? " rt-mine" : ""}`}>
      <div className="rt-side-hd">
        <span className="rt-side-name">{label}</span>
        <span>{mine ? "your team" : "their team"}</span>
      </div>
      <div className="rt-fighters">
        {(team || []).map((fid, slot) => (
          <FighterCard
            key={`${fid}-${slot}`}
            fid={fid}
            state={fighters?.[slot]}
            board={catalog?.fighters?.[fid]}
            active={activeSlot === slot}
            struck={struckSlots?.has(slot)}
          />
        ))}
      </div>
    </div>
  );
}

function eventWords(ev, catalog, teams) {
  const name = (seat, slot) => catalog?.fighters?.[teams?.[seat]?.[slot]]?.name || "?";
  switch (ev.kind) {
    case "hp": {
      const down = ev.to < ev.from;
      return <span className={down ? "rt-ev-hit" : "rt-ev-heal"}>
        {name(ev.seat, ev.slot)} {down ? "▼" : "▲"}
      </span>;
    }
    case "power":
      return <span className="rt-ev-pw">{name(ev.seat, ev.slot)} power {ev.from}→{ev.to}</span>;
    case "ko": return <span className="rt-ev-hit">{name(ev.seat, ev.slot)} is KO'd</span>;
    case "transform": return <span>{name(ev.seat, ev.slot)} becomes the Bear</span>;
    case "spirit": return <span>{ev.character} becomes a Spirit</span>;
    case "poison": return <span className="rt-ev-hit">poison ({ev.damage})</span>;
    case "execution": return <span className="rt-ev-hit">execution ({ev.damage})</span>;
    case "scheme_reveal": return <span>Intrigue: {String(ev.effect).replace(/_/g, " ")}</span>;
    case "token": return <span>{ev.token} token</span>;
    case "track": return <span>{String(ev.track).replace(/_/g, " ")} {ev.from}→{ev.to}</span>;
    case "revive": return <span className="rt-ev-heal">back from the dead</span>;
    case "removed": return <span>a card leaves the game</span>;
    case "instant_bonus": return <span>Instant Bonus</span>;
    default: return null;
  }
}

/* ── The component ───────────────────────────────────────────────────────── */

export default function RagTag({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");
  const [connecting, setConnecting] = useState(false);
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [toast, setToast] = useState("");
  const [openGames, setOpenGames] = useState(() => readLobbyCache("ragtag", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("ragtag", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("ragtag", myId, "history", []));
  const [loadingGames, setLoadingGames] = useState(false);
  const [lobbyTab, setLobbyTab] = useState("open");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [createOpp, setCreateOpp] = useState("ai");

  // Local build-step selection, before it is submitted.
  const [buildPick, setBuildPick] = useState(null);
  const [buildPos, setBuildPos] = useState(null);
  // Playback cursor through this round's beats.
  const [beatIdx, setBeatIdx] = useState(0);
  const [skipBeats, setSkipBeats] = useState(false);

  const [historyShown, historyMore] = useProgressiveList(history);
  const urlAttemptRef = useRef(null);

  const game = roomData?.game;
  const names = roomData?.players || {};
  const mySeat = game?.seats?.indexOf(myId) ?? -1;
  const theirSeat = mySeat >= 0 ? 1 - mySeat : -1;
  const over = !!game && game.winner !== null && game.winner !== undefined;

  /* ── socket ── */
  const handleMessage = useCallback((msg) => {
    setConnecting(false);
    if (msg.type === "error") {
      const ua = urlAttemptRef.current;
      if (ua) {
        urlAttemptRef.current = null;
        try {
          if (localStorage.getItem("ragtag_roomId") === ua.rid) localStorage.removeItem("ragtag_roomId");
          localStorage.removeItem(`ragtag_token_${ua.rid}_${myId}`);
        } catch {}
        setRoomId(""); setRoomData(null); setScreen("lobby");
        replacePath(buildPath("ragtag"));
      }
      setToast(msg.message || "error");
      return;
    }
    const room = msg.room;
    if (!room) return;
    const rid = room.room_id || roomId;
    const tok = room.reconnect_tokens?.[myId];
    if (tok) {
      try {
        localStorage.setItem(`ragtag_token_${rid}_${myId}`, tok);
        localStorage.setItem("ragtag_roomId", rid);
      } catch {}
    }
    setRoomData(room);
    const inGame = room.status === "playing" || room.status === "over";
    if (msg.type === "created" || msg.type === "joined") {
      if (rid) pushPath(buildPath("ragtag", rid));
      urlAttemptRef.current = null;
      setRoomId(rid);
      setScreen(inGame ? "game" : "waiting");
    } else if (inGame && screen !== "game") {
      setScreen("game");
    }
  }, [myId, roomId, screen]);

  const { connected, connect, send, disconnect } = useSocket(handleMessage);

  /* Static card + board tables, once. Cached so a reconnect renders instantly. */
  useEffect(() => {
    try {
      const cached = localStorage.getItem("ragtag_catalog");
      if (cached) setCatalog(JSON.parse(cached));
    } catch {}
    fetch(`${RT_HTTP}/catalog`).then((r) => r.json()).then((d) => {
      if (d.roster) {
        setCatalog(d);
        try { localStorage.setItem("ragtag_catalog", JSON.stringify(d)); } catch {}
      }
    }).catch(() => {});
  }, []);

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${RT_HTTP}/games`).then((r) => r.json()).then((d) => {
      const g = d.games || []; setOpenGames(g); writeLobbyCache("ragtag", myId, "open", g);
    }).catch(() => {}).finally(() => setLoadingGames(false));
    if (authUser?.session_token) {
      const headers = { Authorization: `Bearer ${authUser.session_token}` };
      fetch(`${RT_HTTP}/games/mine`, { headers }).then((r) => r.json()).then((d) => {
        const g = d.games || []; setMyGames(g); writeLobbyCache("ragtag", myId, "mine", g);
      }).catch(() => {});
      fetch(`${RT_HTTP}/games/history`, { headers }).then((r) => r.json()).then((d) => {
        const g = d.games || []; setHistory(g); writeLobbyCache("ragtag", myId, "history", g);
      }).catch(() => {});
    } else {
      setMyGames([]); setHistory([]);
      writeLobbyCache("ragtag", myId, "mine", []);
      writeLobbyCache("ragtag", myId, "history", []);
    }
  }, [authUser, myId]);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);
  useEffect(() => () => disconnect(), []); // eslint-disable-line
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(""), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  const newRoomId = () => Math.random().toString(36).slice(2, 7).toUpperCase();

  const createGame = useCallback((vsAi) => {
    const rid = newRoomId();
    setConnecting(true); setRoomId(rid); setShowCreateModal(false);
    connect(`${RT_WS}/${rid}/${myId}`, {
      action: "create", name: authUser?.name || "Player", vs_ai: vsAi,
    });
  }, [connect, myId, authUser]);

  const joinGame = useCallback((rid) => {
    if (!rid) return;
    const code = String(rid).trim().toUpperCase();
    setConnecting(true); setRoomId(code);
    connect(`${RT_WS}/${code}/${myId}`, {
      action: "join", name: authUser?.name || "Player",
      session_token: authUser?.session_token || null,
    });
  }, [connect, myId, authUser]);

  const resumeGame = useCallback((rid) => {
    let tok = null;
    try { tok = localStorage.getItem(`ragtag_token_${rid}_${myId}`); } catch {}
    setConnecting(true); setRoomId(rid);
    connect(`${RT_WS}/${rid}/${myId}`, tok
      ? { action: "reconnect", token: tok }
      : { action: "join", name: authUser?.name || "Player",
          session_token: authUser?.session_token || null });
  }, [connect, myId, authUser]);

  const cancelGame = useCallback((gid) => {
    if (!authUser?.session_token) return;
    fetch(`${RT_HTTP}/games/${gid}`, {
      method: "DELETE", headers: { Authorization: `Bearer ${authUser.session_token}` },
    }).then(() => fetchGames()).catch(() => {});
  }, [authUser, fetchGames]);

  const leaveToLobby = useCallback(() => {
    disconnect(); setRoomId(""); setRoomData(null); setScreen("lobby");
    replacePath(buildPath("ragtag"));
  }, [disconnect]);

  /* ── URL deep entry + Back/Forward ── */
  useEffect(() => {
    const path = window.location.pathname;
    const m = /\/ragtag\/([A-Za-z0-9_-]{1,24})\/?$/.exec(path);
    if (m) { urlAttemptRef.current = { rid: m[1].toUpperCase() }; resumeGame(m[1].toUpperCase()); }
  }, []); // eslint-disable-line

  useEffect(() => subscribe((r) => {
    if (r.game !== "ragtag") return;
    if (r.room) { urlAttemptRef.current = { rid: r.room }; resumeGame(r.room); }
    else { disconnect(); setRoomId(""); setRoomData(null); setScreen("lobby"); }
  }), [resumeGame, disconnect]);

  /* ── Beat playback ──
   * `beats` is replaced wholesale each round, so the cursor resets when the
   * round does. Skip jumps to the end rather than cancelling: the final state is
   * already applied server-side, the animation is only catching the eye up.
   */
  const beats = game?.beats || [];
  useEffect(() => { setBeatIdx(0); setSkipBeats(false); }, [game?.round]);
  useEffect(() => {
    if (skipBeats) { setBeatIdx(beats.length); return undefined; }
    if (beatIdx >= beats.length) return undefined;
    const t = setTimeout(() => setBeatIdx((i) => i + 1), BEAT_MS);
    return () => clearTimeout(t);
  }, [beatIdx, beats.length, skipBeats]);

  const shownBeat = beats[Math.min(beatIdx, beats.length - 1)] || null;
  const animating = beatIdx < beats.length;

  const struckSlots = useMemo(() => {
    const out = { 0: new Set(), 1: new Set() };
    for (const ev of shownBeat?.events || []) {
      if (ev.kind === "hp" && ev.to < ev.from) out[ev.seat].add(ev.slot);
    }
    return out;
  }, [shownBeat]);

  /* ── Moves ── */
  const sendMove = useCallback((move) => send({ action: "move", move }), [send]);

  // WHAT DO I OWE? The server answers this (`you_owe`), because a simultaneous
  // game has no "your turn" to read off the phase and a client that re-derives it
  // shows the wrong prompt the moment the two disagree.
  const owes = useMemo(() => {
    if (!game || over || mySeat < 0 || !game.you_owe) return null;
    if (game.pending_is_yours) return "pending";
    return game.phase;                 // draft | order | build
  }, [game, over, mySeat]);

  useEffect(() => { setBuildPick(null); setBuildPos(null); }, [game?.round, game?.phase]);

  /* ── Screens ── */
  if (connecting && screen === "lobby") {
    return (
      <div className="app ragtag">
        <style>{ragtagStyles}</style>
        <LobbyLoading label="Connecting…" />
      </div>
    );
  }

  if (screen === "lobby") {
    const activeMine = notWaiting(myGames);
    return (
      <div className="app ragtag">
        <style>{ragtagStyles}</style>
        <LobbyHeader
          onBack={onExit}
          title="Rag Tag"
          user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : null}
        />
        <LobbyCreateRow
          onCreate={() => setShowCreateModal(true)}
          onJoin={(code) => joinGame(code)}
          onRefresh={fetchGames}
          onRules={() => setShowRules(true)}
          refreshing={loadingGames} />

        {showCreateModal && (
          <CreateModal title="New Fight" onClose={() => setShowCreateModal(false)}>
            <CmRow label="Opponent">
              <CmSeg value={createOpp} onChange={setCreateOpp} options={[
                { value: "friend", label: "VS Friend", title: "One friend joins from the lobby or your room code" },
                { value: "ai", label: "VS Bot", title: "Starts instantly against the bot" },
              ]} />
            </CmRow>
            <span className="cm-hint">
              Rag Tag is head-to-head. The bot picks at random for now — it is here so
              the game can be played, not to give you a hard time.
            </span>
            <div className="cm-footer">
              <span className="cm-summary">
                Creating: <b>{createOpp === "ai" ? "vs Bot" : "vs Friend"}</b>
              </span>
              <button type="button" className="cm-create" onClick={() => createGame(createOpp === "ai")}>
                Create Game
              </button>
            </div>
          </CreateModal>
        )}

        <LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[
          { key: "open", label: "Open", count: openGames.length || null },
          { key: "active", label: "Active", count: activeMine.length || null },
          { key: "history", label: "History", count: history.length || null },
        ]} />

        <div className={`rt-lobby-cols lby-cols tab-${lobbyTab}`}>
          <div className="lby-col-open">
            <LobbySectionHd title="Open Games" />
            {openGames.length === 0 && <LobbyEmpty>No open games. Create one!</LobbyEmpty>}
            <div className="lby-list">
              {openGames.map((g) => (
                <div className="lby-card" key={g.id}>
                  <div className="lby-card-info">
                    <div className="lby-card-title">{g.host_name || "Player"}'s fight</div>
                    <div className="lby-card-meta">{g.id} · {timeAgo(g.created_at)}</div>
                  </div>
                  <div className="lby-card-actions">
                    {g.host_id === myId ? (
                      <>
                        <LobbyAction onClick={() => resumeGame(g.id)}>Return</LobbyAction>
                        <LobbyAction kind="secondary" onClick={() => cancelGame(g.id)}>Cancel</LobbyAction>
                      </>
                    ) : <LobbyAction onClick={() => joinGame(g.id)}>Join</LobbyAction>}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="lby-col-active">
            <LobbySectionHd title="Active Games" />
            {activeMine.length === 0 && <LobbyEmpty>No fights in progress.</LobbyEmpty>}
            <div className="lby-list">
              {activeMine.map((g) => (
                <div className="lby-card" key={g.id}>
                  <div className="lby-card-info">
                    <div className="lby-card-title">{g.player1_name || "?"} vs {g.player2_name || "?"}</div>
                    <div className="lby-card-meta">
                      {g.round ? `round ${g.round} · ` : ""}{timeAgo(g.updated_at)}
                    </div>
                  </div>
                  <div className="lby-card-actions">
                    {g.your_turn ? <TurnBadge mine>You're up</TurnBadge> : <TurnBadge>Waiting</TurnBadge>}
                    <LobbyAction onClick={() => resumeGame(g.id)}>Resume</LobbyAction>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="lby-col-history">
            <LobbySectionHd title="History" />
            {history.length === 0 && (
              <LobbyEmpty>{authUser ? "No finished fights yet." : "Log in to keep game history."}</LobbyEmpty>
            )}
            <div className="lby-list">
              {historyShown.map((g) => (
                <div className="lby-card lby-card-hist" key={g.id}>
                  <div className="lby-card-info">
                    <div className="lby-card-title">
                      <span className={`hist-result ${g.outcome === "won" ? "won" : "lost"}`}>
                        {g.outcome === "won" ? "Won" : g.outcome === "draw" ? "Draw" : "Lost"}
                      </span>
                      <span className="hist-scores"> vs {g.you_are_p1 ? g.player2_name : g.player1_name}</span>
                    </div>
                    <div className="lby-card-meta">
                      {(g.your_team || []).map((f) => catalog?.fighters?.[f]?.name || f).join(" + ")}
                      {" · "}{timeAgo(g.updated_at)}
                    </div>
                  </div>
                </div>
              ))}
              {historyMore}
            </div>
          </div>
        </div>
        {toast && <div className="rt-toast">{toast}</div>}
        {showRules && (
          <RulesModal title="How to play — Rag Tag" onClose={() => setShowRules(false)}>
            <RagTagRules />
          </RulesModal>
        )}
      </div>
    );
  }

  if (screen === "waiting") {
    const isHost = roomData?.host === myId;
    return (
      <div className="app ragtag">
        <style>{ragtagStyles}</style>
        <div className="rt-wrap rt-waiting">
          <h1>Rag Tag</h1>
          <p>Room code</p>
          <div className="rt-code">{roomId}</div>
          <p style={{ marginTop: "1rem" }}>
            {Object.keys(names).length < 2 ? "Waiting for an opponent…" : "Ready."}
          </p>
          {isHost && Object.keys(names).length >= 2 && (
            <button className="rt-go" onClick={() => send({ action: "start" })}>Start the fight</button>
          )}
          <div style={{ marginTop: "1.2rem" }}>
            <LobbyAction kind="secondary" onClick={leaveToLobby}>Back to lobby</LobbyAction>
          </div>
        </div>
        {toast && <div className="rt-toast">{toast}</div>}
      </div>
    );
  }

  /* ── The board ── */
  const teams = game?.teams || [[], []];
  const myTeam = mySeat >= 0 ? teams[mySeat] : [];
  const theirTeam = theirSeat >= 0 ? teams[theirSeat] : [];
  const cards = catalog?.cards || {};
  const instances = game?.instances || [];
  const cardOf = (inst) => (inst == null ? null : cards[String(instances[inst]?.cid)]);

  return (
    <div className="app ragtag">
      <style>{ragtagStyles}</style>
      <LobbyHeader
        title="Rag Tag"
        menu={<GameMenu items={[
          { label: "Return to lobby", onClick: leaveToLobby },
          { label: "How to play (rules)", onClick: () => setShowRules(true) },
          {
            label: "Abandon fight", danger: true,
            onClick: () => { if (!over) send({ action: "abandon" }); },
          },
        ]} />}
      />
      <div className="rt-wrap">
        {!connected && <div className="rt-waitline">Reconnecting…</div>}

        <div className="rt-teams">
          <TeamSide
            label={names[game?.seats?.[theirSeat]] || "Opponent"}
            team={theirTeam}
            fighters={game?.fighters?.[theirSeat]}
            catalog={catalog}
            activeSlot={shownBeat?.active?.[theirSeat]}
            struckSlots={struckSlots[theirSeat]}
          />
          <TeamSide
            label={names[myId] || "You"} mine
            team={myTeam}
            fighters={game?.fighters?.[mySeat]}
            catalog={catalog}
            activeSlot={shownBeat?.active?.[mySeat]}
            struckSlots={struckSlots[mySeat]}
          />
        </div>

        {game?.phase === "fight" || beats.length > 0 ? (
          <div className="rt-ring">
            <div className="rt-ring-hd">
              <span>Round {game?.round} · turn {shownBeat?.turn ?? "—"}</span>
              {animating && (
                <button className="rt-slot" onClick={() => setSkipBeats(true)}>Skip ▸▸</button>
              )}
            </div>
            {shownBeat ? (
              <>
                <div className="rt-beat">
                  <div className="rt-card rt-played" key={`t-${shownBeat.turn}`}>
                    <div className="rt-card-name">{cardOf(shownBeat.insts?.[theirSeat])?.name || "—"}</div>
                    <div className="rt-card-by">
                      {catalog?.fighters?.[cardOf(shownBeat.insts?.[theirSeat])?.fighter]?.name || ""}
                    </div>
                    <div className="rt-card-ops">{cardText(cardOf(shownBeat.insts?.[theirSeat]))}</div>
                  </div>
                  <div className="rt-vs">VS</div>
                  <div className="rt-card rt-played" key={`m-${shownBeat.turn}`}>
                    <div className="rt-card-name">{cardOf(shownBeat.insts?.[mySeat])?.name || "—"}</div>
                    <div className="rt-card-by">
                      {catalog?.fighters?.[cardOf(shownBeat.insts?.[mySeat])?.fighter]?.name || ""}
                    </div>
                    <div className="rt-card-ops">{cardText(cardOf(shownBeat.insts?.[mySeat]))}</div>
                  </div>
                </div>
                <div className="rt-events">
                  {(shownBeat.events || []).map((ev, i) => {
                    const node = eventWords(ev, catalog, teams);
                    return node ? <span key={i}>{node}</span> : null;
                  })}
                </div>
              </>
            ) : <div className="rt-events">The ring is quiet.</div>}
          </div>
        ) : null}

        {/* ── Prompts. Every one of them is "you owe a submission". ── */}
        {!over && owes === "pending" && game?.pending && (
          <div className="rt-prompt">
            <h3>Choose your next Character</h3>
            <p>Their marker goes on the top space of their track, and its icon applies at once.</p>
            <div className="rt-picks">
              {game.pending.options.map((c) => (
                <button className="rt-pick" key={c}
                  onClick={() => sendMove({ kind: "character", character: c })}>
                  <div className="rt-pick-name">{c}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {!over && owes === "draft" && (
          <div className="rt-prompt">
            <h3>Pick a Fighter {game.draft_round === 2 ? "(second)" : "(first)"}</h3>
            <p>
              {game.draft_round === 2
                ? "These are the ones your opponent passed on."
                : "Pick one, then pass the rest across."}
            </p>
            <div className="rt-picks">
              {(game.draft_hand || []).map((fid) => {
                const b = catalog?.fighters?.[fid];
                return (
                  <button className="rt-pick" key={fid}
                    onClick={() => sendMove({ kind: "draft", fighter: fid })}>
                    <div className="rt-pick-name">{b?.name || fid}</div>
                    <div className="rt-pick-sub">
                      {b ? `${b.base_power} power · ${(b.tags || []).join(", ")}` : ""}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {!over && owes === "order" && (
          <div className="rt-prompt">
            <h3>Who leads?</h3>
            <p>Their Starting Card goes on top of your two-card Fight Deck.</p>
            <div className="rt-picks">
              {myTeam.map((fid, slot) => (
                <button className="rt-pick" key={fid}
                  onClick={() => sendMove({ kind: "order", slot })}>
                  <div className="rt-pick-name">{catalog?.fighters?.[fid]?.name || fid}</div>
                  <div className="rt-pick-sub">leads the round</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {!over && owes === "build" && (
          <div className="rt-prompt">
            <h3>Build your deck</h3>
            <p>Keep one of these three and slide it in anywhere. The other two go to the bottom.</p>
            <div className="rt-picks">
              {(game.build_offer || []).map((inst) => {
                const c = cardOf(inst);
                return (
                  <button key={inst}
                    className={`rt-pick${buildPick === inst ? " rt-sel" : ""}`}
                    onClick={() => { setBuildPick(inst); setBuildPos(null); }}>
                    <div className="rt-pick-name">{c?.name || "?"}</div>
                    <div className="rt-pick-sub">
                      {catalog?.fighters?.[c?.fighter]?.name}{c?.instant_bonus ? " · instant bonus" : ""}
                    </div>
                    <div className="rt-pick-sub">{cardText(c)}</div>
                  </button>
                );
              })}
            </div>
            {buildPick != null && (
              <>
                <p style={{ marginTop: "0.6rem" }}>Where does it go? Top is played first.</p>
                <div className="rt-slots">
                  {(game.fight_deck || []).map((inst, i) => (
                    <span key={`s${i}`} style={{ display: "contents" }}>
                      <button className={`rt-slot${buildPos === i ? " rt-sel" : ""}`}
                        onClick={() => setBuildPos(i)}>▾</button>
                      <span className="rt-deckcard">{cardOf(inst)?.name || "?"}</span>
                    </span>
                  ))}
                  <button
                    className={`rt-slot${buildPos === (game.fight_deck || []).length ? " rt-sel" : ""}`}
                    onClick={() => setBuildPos((game.fight_deck || []).length)}>▾</button>
                </div>
              </>
            )}
            <button className="rt-go" disabled={buildPick == null || buildPos == null}
              onClick={() => sendMove({ kind: "build", inst: buildPick, pos: buildPos })}>
              Lock it in
            </button>
          </div>
        )}

        {!over && owes === null && (
          <div className="rt-waitline">
            {game?.phase === "build" ? "Waiting for your opponent to build…"
              : game?.phase === "draft" ? "Waiting for their pick…"
              : game?.phase === "order" ? "Waiting for them to choose who leads…"
              : animating ? "Fighting…" : "Waiting…"}
          </div>
        )}

        {over && (
          <div className="rt-over">
            <h2>
              {game.winner === "draw" ? "Draw"
                : game.winner === mySeat ? "You win" : "You lose"}
            </h2>
            <p>{game.log?.[game.log.length - 1] || ""} · {game.round} rounds</p>
            <div style={{ marginTop: "0.8rem" }}>
              <LobbyAction onClick={leaveToLobby}>Back to lobby</LobbyAction>
            </div>
          </div>
        )}

        {game?.log?.length > 0 && (
          <div className="rt-log">
            {game.log.slice(-12).map((line, i) => <div key={i}>{line}</div>)}
          </div>
        )}
      </div>
      {toast && <div className="rt-toast">{toast}</div>}
      {showRules && (
        <RulesModal title="How to play — Rag Tag" onClose={() => setShowRules(false)}>
          <RagTagRules />
        </RulesModal>
      )}
    </div>
  );
}
