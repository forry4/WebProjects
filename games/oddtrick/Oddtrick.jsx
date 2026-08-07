import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbySectionHd, LobbyEmpty, TurnBadge, LobbyLoading,
  LobbyTabs, GameMenu, gameMenuCss, readLobbyCache, writeLobbyCache,
  createModalCss, CreateModal, CmRow, CmSeg, LobbyCreateRow, lobbyCreateRowCss,
  RulesModal, rulesModalCss,
  useProgressiveList,
} from "../../shared/lobby.jsx";
import OddtrickRules from "./rules.jsx";
import { parsePath, buildPath, pushPath, subscribe } from "../../shared/router.js";

// CSS lives in the sibling .css file, imported ?inline as a STRING and injected
// by this component's own <style> while mounted. Never a JS template literal —
// one stray backtick there reparses the rest of the file and blanks the page.
import _cssText from "./Oddtrick.css?inline";

const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const OT_WS = WS_RAW.replace(/\/ws$/, "/oddtrick/ws");
const OT_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/oddtrick");

const styles = baseCss + lobbyCss + gameMenuCss + createModalCss + lobbyCreateRowCss
  + rulesModalCss + _cssText;

const SUIT_GLYPH = ["♣", "♦", "♥", "♠"];   // c d h s
// 32-card deck: 7 low, ace high, eight ranks per suit.
const RANKS = ["7", "8", "9", "10", "J", "Q", "K", "A"];
// Denominations are RANKED left to right: a same-level overtake must name one
// further right. Null is the top rung and exists only at level 6.
const DENOM_LABEL = ["♣", "♦", "♥", "♠", "NT", "Null"];
const DENOM_NAME = ["Clubs", "Diamonds", "Hearts", "Spades", "No-trump", "Null — win no +2 trick"];
const NOTRUMP = 4;
const NULL_DENOM = 5;
const NULL_LEVEL = 6;
const NULL_MAKE = 12;
const NULL_SET = 10;

const BOT_TIERS = [
  { id: "easy", name: "Easy", desc: "Plays legally, blunders often" },
  { id: "normal", name: "Normal", desc: "Knows which tricks it wants" },
];

// Two auctions over the same card play, picked per room. Skat mode bids a bare
// NUMBER and only names the game after winning — so the ladder cannot be read
// backwards into a denomination. Every number on it (the values list, each
// declaration's base and minimum level) arrives from the server in
// `game.options` / `game.declare`; nothing about the price table is hardcoded
// here, so the two can never disagree about what a bid costs.
const MODES = [
  { id: "classic", label: "Classic", title: "Bid a level and a denomination — the shipped auction" },
  { id: "skat", label: "Skat", title: "Bid a number, then declare the game that satisfies it" },
];
const MODE_LABEL = { classic: "Classic", skat: "Skat" };

/** The announcement stack, spelled out for the result and side panels. */
function multParts(ct) {
  const parts = [];
  if (ct?.hand) parts.push("Hand");
  if (ct?.sharp) parts.push("Sharp");
  if (ct?.open) parts.push("Open");
  return parts;
}

const suitOf = (c) => Math.floor(c / 8);
const rankOf = (c) => c % 8;
const isRed = (c) => suitOf(c) === 1 || suitOf(c) === 2;
const cardName = (c) => RANKS[rankOf(c)] + SUIT_GLYPH[suitOf(c)];
// Trick NUMBER t (1-based): even ones pay +2, odd ones cost 1.
const trickValue = (t0) => (t0 % 2 === 1 ? 2 : -1);

/** Does `follow` beat `led`? A mirror of `engine.beats` — kept in step with it
 *  by hand, like `trickValue` above. Only used to mark who TOOK the previous
 *  trick, so a drift here mislabels a badge and cannot affect play: every move
 *  is validated server-side and the points come off the wire. */
const beats = (led, follow, trump) => {
  const ls = suitOf(led), fs = suitOf(follow);
  if (fs === ls) return rankOf(follow) > rankOf(led);
  if (trump < NOTRUMP) return fs === trump && ls !== trump;
  return false;
};

/** The two cards of the last COMPLETED trick, with who played each and who took
 *  it. `history` is [seat, card, source] in play order, two entries per trick,
 *  so a trailing odd entry is the card currently face up on the table. */
function lastTrick(game) {
  const h = game.history || [];
  const done = Math.floor(h.length / 2);
  if (done === 0) return null;
  const [a, b] = [h[2 * (done - 1)], h[2 * done - 1]];
  const winner = beats(a[1], b[1], game.trump) ? b[0] : a[0];
  // Trick index `done - 1` is 0-based, matching `trickValue`.
  return { plays: [a, b], winner, value: trickValue(done - 1), number: done };
}

function uid() { return Math.random().toString(36).slice(2, 10); }
function roomCode() {
  return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join("");
}
function timeAgo(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// ─── pieces ─────────────────────────────────────────────────────────────────

function Card({ c, onClick, dim, sel, small, ghost }) {
  if (ghost) return <div className={`odd-card ghost${small ? " sm" : ""}`}>?</div>;
  if (c === null || c === undefined) return <div className="odd-card back" />;
  const cls = `odd-card ${isRed(c) ? "red" : "black"}${onClick ? " play" : ""}`
    + `${dim ? " dim" : ""}${sel ? " sel" : ""}${small ? " sm" : ""}`;
  return (
    <div className={cls} onClick={onClick} title={cardName(c)}>
      <span className="odd-r">{RANKS[rankOf(c)]}</span>
      <span className="odd-s">{SUIT_GLYPH[suitOf(c)]}</span>
    </div>
  );
}

function Pile({ pile, onPlay, playable }) {
  if (!pile || pile.n === 0) {
    return (
      <div className="odd-pile">
        <div className="odd-pilewrap"><div className="odd-card ghost">–</div></div>
        <div className="odd-under">empty</div>
      </div>
    );
  }
  const twoLeft = pile.n === 2;
  return (
    <div className="odd-pile">
      <div className={`odd-pilewrap${twoLeft ? " two" : ""}`}>
        <Card c={pile.top} onClick={onPlay} dim={onPlay ? false : !playable} />
      </div>
      <div className={`odd-under${pile.under !== null && pile.under !== undefined ? " known" : ""}`}>
        {!twoLeft ? "last" : pile.under !== null && pile.under !== undefined
          ? `over ${cardName(pile.under)}` : "1 hidden"}
      </div>
    </div>
  );
}

/** The parity strip: every trick, what it pays, and who took it. */
function TrickStrip({ game }) {
  const hist = game.history || [];
  // Two plays make a trick; walk the history to find each trick's winner.
  const winners = [];
  for (let t = 0; t * 2 + 1 < hist.length; t++) winners.push(null);
  return (
    <div className="odd-trickstrip">
      {Array.from({ length: 13 }, (_, t) => {
        const v = trickValue(t);
        const done = t < game.trick;
        const cls = `odd-tick ${v > 0 ? "good" : "bad"}${t === game.trick && game.phase === "play" ? " now" : ""}`;
        return <div key={t} className={cls} style={{ opacity: done ? 0.45 : 1 }}>{v > 0 ? "+2" : "−1"}</div>;
      })}
    </div>
  );
}

/** What the declared skat game is worth right now, and why.
 *  `rows` renders it as side-panel score rows; otherwise as one inline line. */
function SkatStake({ game, nameOf, rows }) {
  const ct = game.contract || {};
  if (!ct.value) return null;
  const doubling = ct.re ? 4 : ct.kontra ? 2 : 1;
  const stake = ct.value * ct.mult * doubling;
  const parts = multParts(ct);
  const why = [
    parts.length ? `×${ct.mult} ${parts.join(" + ")}` : null,
    ct.re ? "×4 Kontra + Re" : ct.kontra ? "×2 Kontra" : null,
  ].filter(Boolean).join(" · ");
  if (!rows) {
    return (
      <div className="odd-maths">
        {ct.value}{ct.mult > 1 ? ` × ${ct.mult}` : ""}{doubling > 1 ? ` × ${doubling}` : ""}
        {" = "}<b>{stake}</b>{why ? ` — ${why}` : ""}
      </div>
    );
  }
  return (
    <>
      <div className="odd-scorerow"><span>At stake</span><b>{stake}</b></div>
      {why && <div className="muted" style={{ fontSize: "0.72rem" }}>{why}</div>}
      <div className="muted" style={{ fontSize: "0.72rem" }}>
        Made, it goes to {nameOf(game.auction.declarer)}; missed, to{" "}
        {nameOf(1 - game.auction.declarer)} plus 4 a point short.
      </div>
    </>
  );
}

/** Every declaration that clears `value`, cheapest level first.
 *  This is the mode's whole point made visible: 12 is ♦6 and ♥4 and ♠3 and NT2,
 *  so naming 12 says nothing about which game is coming. */
function clearedBy(value, bases, maxLevel) {
  if (!value || !bases?.length || !maxLevel) return [];
  return bases.map((base, denom) => ({
    denom, level: Math.max(1, Math.ceil(value / base)),
  })).filter((x) => x.level <= maxLevel && x.level * bases[x.denom] === value);
}

/** Which auction a room runs. Classic is the default, so only skat is marked. */
function ModeBadge({ mode }) {
  if (mode !== "skat") return null;
  return <span className="odd-modebadge">{MODE_LABEL.skat}</span>;
}

function ContractLine({ game }) {
  const a = game.auction || {};
  // Skat mode: until the declaration lands, all there is to show is the number.
  if (game.mode === "skat" && !a.level) {
    return a.value
      ? <span className="odd-contract"><b>{a.value}</b></span>
      : <span className="muted">no bid yet</span>;
  }
  if (!a.level) return <span className="muted">no contract yet</span>;
  if (a.denom === NULL_DENOM) {
    return <span className="odd-contract"><b>Null</b></span>;
  }
  const red = a.denom === 1 || a.denom === 2;
  return (
    <span className="odd-contract">
      <b>{a.level}</b>
      <span style={{ color: red ? "#ff8a9c" : undefined }}>{DENOM_LABEL[a.denom]}</span>
    </span>
  );
}

// ─── socket ─────────────────────────────────────────────────────────────────

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
  const send = useCallback((o) => { try { wsRef.current?.send(JSON.stringify(o)); } catch {} }, []);
  const disconnect = useCallback(() => {
    try { wsRef.current?.close(); } catch {}
    wsRef.current = null; setConnected(false);
  }, []);
  const socketReady = useCallback(() => wsRef.current?.readyState, []);
  return { connected, connect, send, disconnect, socketReady };
}

// ─── main ───────────────────────────────────────────────────────────────────

export default function Oddtrick({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");     // lobby | waiting | game
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [openGames, setOpenGames] = useState(() => readLobbyCache("oddtrick", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("oddtrick", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("oddtrick", myId, "history", []));
  const [historyShown, historyMore] = useProgressiveList(history);
  const [lobbyTab, setLobbyTab] = useState("open");
  const [loadingGames, setLoadingGames] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [toast, setToast] = useState("");
  const [showRules, setShowRules] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [bidLevel, setBidLevel] = useState(null);
  const [bidDenom, setBidDenom] = useState(null);
  const [newMode, setNewMode] = useState("classic");
  // Create-modal selections. Deferred until "Create Game" rather than firing on
  // the option click — the shape every other game's modal uses.
  const [createOpp, setCreateOpp] = useState("ai");
  const [createDiff, setCreateDiff] = useState("normal");
  // Skat mode's half-built moves: the number, then the declaration.
  const [bidValue, setBidValue] = useState(null);
  const [declDenom, setDeclDenom] = useState(null);
  const [declLevel, setDeclLevel] = useState(null);
  const [declSharp, setDeclSharp] = useState(false);
  const [declOpen, setDeclOpen] = useState(false);

  const reconnTimer = useRef(null);
  const reconnTries = useRef(0);
  const roomIdRef = useRef("");
  const popHandlerRef = useRef(() => {});
  const didInitRef = useRef(false);
  roomIdRef.current = roomId;

  const game = roomData?.game || null;
  const players = roomData?.players || {};
  const seats = game?.seats || [];
  const mySeat = game ? game.you : null;
  const myTurn = !!game && game.phase !== "over"
    && (game.phase === "auction" ? game.auction.to_act === mySeat : game.to_play === mySeat);
  const isSkat = game?.mode === "skat";
  const declSeat = game?.auction?.declarer;
  const iDeclare = game != null && mySeat != null && declSeat === mySeat;
  // Skat's post-auction prompts each belong to exactly one seat; the server
  // only ships `talon` / `declare` to that seat, and Kontra/Re go by phase.
  const myKontra = isSkat && game?.phase === "kontra" && !iDeclare;
  const myRe = isSkat && game?.phase === "re" && iDeclare;

  const onMessage = useCallback((msg) => {
    if (msg.type === "error") { setToast(msg.message || "error"); setConnecting(false); return; }
    if (msg.room) {
      setRoomData(msg.room);
      setConnecting(false);
      const tok = msg.room.reconnect_tokens?.[myId];
      if (tok) { try { localStorage.setItem(`oddtrick_token_${msg.room.room_id}_${myId}`, tok); } catch {} }
      if (msg.room.room_id) {
        setRoomId(msg.room.room_id);
        pushPath(buildPath("oddtrick", msg.room.room_id));
      }
      setScreen(msg.room.game ? "game" : "waiting");
    }
  }, [myId]);

  const { connected, connect, send, disconnect, socketReady } = useSocket(onMessage);

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${OT_HTTP}/games`).then((r) => r.json())
      .then((d) => { const g = d.games || []; setOpenGames(g); writeLobbyCache("oddtrick", myId, "open", g); })
      .catch(() => {}).finally(() => setLoadingGames(false));
    if (authUser?.session_token) {
      const headers = { Authorization: `Bearer ${authUser.session_token}` };
      fetch(`${OT_HTTP}/games/mine`, { headers }).then((r) => r.json())
        .then((d) => { const g = d.games || []; setMyGames(g); writeLobbyCache("oddtrick", myId, "mine", g); }).catch(() => {});
      fetch(`${OT_HTTP}/games/history`, { headers }).then((r) => r.json())
        .then((d) => { const g = d.games || []; setHistory(g); writeLobbyCache("oddtrick", myId, "history", g); }).catch(() => {});
    } else {
      setMyGames([]); setHistory([]);
      writeLobbyCache("oddtrick", myId, "mine", []); writeLobbyCache("oddtrick", myId, "history", []);
    }
  }, [authUser, myId]);

  // The skat price table is the server's, never a copy: /catalog hands over the
  // per-denomination bases so the "what clears this number" hint below is the
  // same arithmetic the engine validates with.
  const [catalog, setCatalog] = useState(null);
  useEffect(() => {
    fetch(`${OT_HTTP}/catalog`).then((r) => r.json()).then(setCatalog).catch(() => {});
  }, []);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);
  useEffect(() => () => disconnect(), []); // eslint-disable-line
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2600); return () => clearTimeout(t); } }, [toast]);
  // A fresh contract clears any half-built bid. In skat mode the standing bid
  // is `value`, not `level` — `level` stays 0 until the declaration.
  useEffect(() => {
    setBidLevel(null); setBidDenom(null); setBidValue(null);
  }, [game?.auction?.level, game?.auction?.value, game?.auction?.to_act,
      game?.redeals]);
  // Swap-phase selection (declarer only).
  const [swapTake, setSwapTake] = useState(null);
  const [swapGive, setSwapGive] = useState(null);
  useEffect(() => { setSwapTake(null); setSwapGive(null); }, [game?.phase]);
  // Entering the declaration: start on the cheapest denomination the bid allows.
  useEffect(() => {
    const opts = game?.declare?.denoms;
    if (!opts?.length) return;
    const best = opts.reduce((a, b) => (b.min_level < a.min_level ? b : a));
    setDeclDenom(best.denom); setDeclLevel(best.min_level);
    setDeclSharp(false); setDeclOpen(false);
  }, [game?.phase, game?.declare?.bid]);

  const createGame = (vsAi, difficulty) => {
    const rid = roomCode();
    setConnecting(true); setShowCreate(false);
    connect(`${OT_WS}/${rid}/${myId}`, {
      action: "create", name: authUser?.name || "Player",
      vs_ai: vsAi, ai_difficulty: difficulty, mode: newMode,
    });
  };
  const joinGame = (rid) => {
    setConnecting(true);
    connect(`${OT_WS}/${rid}/${myId}`, {
      action: "join", name: authUser?.name || "Player",
      session_token: authUser?.session_token || null,
    });
  };
  const resumeGame = (rid) => {
    setConnecting(true);
    let tok = null;
    try { tok = localStorage.getItem(`oddtrick_token_${rid}_${myId}`); } catch {}
    if (tok) connect(`${OT_WS}/${rid}/${myId}`, { action: "reconnect", token: tok });
    else if (authUser?.session_token) {
      connect(`${OT_WS}/${rid}/${myId}`, { action: "auth_reconnect", session_token: authUser.session_token });
    } else joinGame(rid);
  };
  const cancelGame = (rid) => {
    if (!authUser?.session_token) return;
    fetch(`${OT_HTTP}/games/${rid}`, {
      method: "DELETE", headers: { Authorization: `Bearer ${authUser.session_token}` },
    }).then(() => fetchGames()).catch(() => {});
  };
  const leaveToLobby = () => {
    disconnect(); setRoomId(""); setRoomData(null); setScreen("lobby");
    pushPath(buildPath("oddtrick", null));
  };

  // ── URL deep entry + back/forward (this component owns /oddtrick/<ROOM>) ──
  useEffect(() => {
    if (didInitRef.current) return;
    didInitRef.current = true;
    const r = parsePath();
    if (r.game === "oddtrick" && r.room) resumeGame(r.room);
  }, []); // eslint-disable-line
  popHandlerRef.current = (r) => {
    if (r.game !== "oddtrick") return;
    if (r.room && r.room !== roomIdRef.current) resumeGame(r.room);
    else if (!r.room && roomIdRef.current) leaveToLobby();
  };
  useEffect(() => subscribe((r) => popHandlerRef.current(r)), []); // eslint-disable-line

  // Auto-reconnect while in a live game. Load-bearing for vs-bot: the server
  // re-drives the bot's turn on reconnect, which is what unsticks a game whose
  // scheduler died with the socket.
  const inLiveGame = !!roomId && (screen === "game" || screen === "waiting")
    && roomData?.status !== "over";
  const attemptReconnect = useCallback(() => {
    if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; }
    const rs = socketReady();
    if (rs === 0 || rs === 1) { reconnTimer.current = setTimeout(attemptReconnect, 3000); return; }
    let tok = null;
    try { tok = localStorage.getItem(`oddtrick_token_${roomId}_${myId}`); } catch {}
    if (tok) { setReconnecting(true); connect(`${OT_WS}/${roomId}/${myId}`, { action: "reconnect", token: tok }); }
    reconnTries.current += 1;
    reconnTimer.current = setTimeout(attemptReconnect, Math.min(2000 * reconnTries.current, 8000));
  }, [roomId, myId, connect, socketReady]);
  useEffect(() => {
    const clear = () => { if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; } };
    if (connected || !inLiveGame) {
      clear(); reconnTries.current = 0;
      if (connected) setReconnecting(false);
      return clear;
    }
    if (!reconnTimer.current) attemptReconnect();
    return clear;
  }, [connected, inLiveGame, attemptReconnect]);

  const doBid = () => {
    if (bidLevel === null || bidDenom === null) return;
    send({ action: "move", move: { kind: "bid", level: bidLevel, denom: bidDenom } });
  };
  const doPass = () => send({ action: "move", move: { kind: "pass" } });
  const doPlay = (card) => send({ action: "move", move: { kind: "play", card } });
  const doSwap = (take, give) => send({ action: "move", move: { kind: "swap", take, give } });
  const doMove = (move) => send({ action: "move", move });
  const doValueBid = () => {
    if (bidValue === null) return;
    doMove({ kind: "bid", value: bidValue });
  };
  const doDeclare = (denom, level, sharp, open) =>
    doMove({ kind: "declare", denom, level, sharp, open });

  // ── lobby ────────────────────────────────────────────────────────────────
  if (screen === "lobby") {
    if (connecting) {
      return <div className="odd"><style>{styles}</style><LobbyLoading label="Connecting…" /></div>;
    }
    const openCol = (
      <div className="lby-col">
        <LobbySectionHd title="Open games" note={openGames.length ? `${openGames.length} waiting` : null} />
        <div className="lby-list">
          {openGames.length === 0 && <LobbyEmpty>No open games. Create one!</LobbyEmpty>}
          {openGames.map((g) => (
            <div key={g.id} className="lby-card">
              <div className="lby-cardmain">
                <div className="lby-cardtitle">
                  {g.host_name || "Player"}<ModeBadge mode={g.mode} />
                </div>
                <div className="lby-cardsub">{g.id} · {timeAgo(g.created_at)}</div>
              </div>
              {g.host_id === myId
                ? <button className="btn btn-ghost" onClick={() => cancelGame(g.id)}>Cancel</button>
                : <button className="btn" onClick={() => joinGame(g.id)}>Join</button>}
            </div>
          ))}
        </div>
      </div>
    );
    const activeCol = (
      <div className="lby-col">
        <LobbySectionHd title="Your games" />
        <div className="lby-list">
          {myGames.length === 0 && <LobbyEmpty>Nothing in progress.</LobbyEmpty>}
          {myGames.map((g) => (
            <div key={g.id} className="lby-card">
              <div className="lby-cardmain">
                <div className="lby-cardtitle">
                  {(g.you_are_p1 ? g.player2_name : g.player1_name) || "Waiting…"}
                  <ModeBadge mode={g.mode} />
                  {g.your_turn && <TurnBadge mine>Your turn</TurnBadge>}
                </div>
                <div className="lby-cardsub">{g.id} · {timeAgo(g.updated_at)}</div>
              </div>
              <button className="btn" onClick={() => resumeGame(g.id)}>Resume</button>
            </div>
          ))}
        </div>
      </div>
    );
    const histCol = (
      <div className="lby-col lby-history">
        <LobbySectionHd title="History" />
        <div className="lby-list" ref={historyMore}>
          {history.length === 0 && <LobbyEmpty>No finished games yet.</LobbyEmpty>}
          {historyShown.map((g) => (
            <div key={g.id} className="lby-card">
              <div className="lby-cardmain">
                <div className="lby-cardtitle">
                  {g.you_won ? "Won" : "Lost"} vs {g.opp_name}
                  <ModeBadge mode={g.mode} />
                </div>
                <div className="lby-cardsub">
                  {g.your_score}–{g.opp_score}
                  {g.contract ? ` · ${g.contract.you_declared ? "declared" : "defended"} `
                    + (g.contract.denom === NULL_DENOM ? "Null"
                      : `${g.contract.level}${DENOM_LABEL[g.contract.denom] || ""}`)
                    + (g.mode === "skat" && g.contract.value
                      ? ` for ${g.contract.value}${g.contract.mult > 1 ? `×${g.contract.mult}` : ""}` : "")
                    + `${g.contract.made ? " (made)" : " (set)"}` : ""}
                  {" · "}{timeAgo(g.updated_at)}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
    return (
      <div className="odd">
        <style>{styles}</style>
        <LobbyHeader onBack={onExit} title="Oddtrick" user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : null} />
        <LobbyCreateRow
          onCreate={() => setShowCreate(true)}
          onJoin={(code) => joinGame(code.toUpperCase())}
          onRefresh={fetchGames}
          onRules={() => setShowRules(true)}
          refreshing={loadingGames}
        />
        <LobbyTabs
          tabs={[{ id: "open", label: "Open" }, { id: "active", label: "Yours" }, { id: "history", label: "History" }]}
          value={lobbyTab} onChange={setLobbyTab}
        />
        <div className="lby-cols" data-tab={lobbyTab}>
          {openCol}{activeCol}{histCol}
        </div>
        {showCreate && (
          <CreateModal title="New Game" onClose={() => setShowCreate(false)}>
            <CmRow label="Opponent">
              <CmSeg value={createOpp} onChange={setCreateOpp} options={[
                { value: "friend", label: "VS Friend", title: "Head-to-head — one friend joins from the lobby (or your room code)" },
                { value: "ai", label: "VS AI", title: "Starts instantly against the bot" },
              ]} />
            </CmRow>
            {createOpp === "ai" ? (
              <CmRow label="AI Difficulty">
                <CmSeg value={createDiff} onChange={setCreateDiff}
                  options={BOT_TIERS.map((t) => ({ value: t.id, label: t.name, title: t.desc }))} />
              </CmRow>
            ) : (
              <span className="cm-hint">Oddtrick is head-to-head — one friend joins from the lobby.</span>
            )}
            <CmRow label="Auction">
              <CmSeg value={newMode} onChange={setNewMode}
                options={MODES.map((m) => ({ value: m.id, label: m.label, title: m.title }))} />
              <span className="cm-hint">
                {newMode === "skat"
                  ? "Bid a number; name the game only after you win it. Then Hand, Sharp, Open — and their Kontra."
                  : "Bid a level and a denomination, ranked ♣ < ♦ < ♥ < ♠ < NT < Null."}
              </span>
            </CmRow>
            <div className="cm-footer">
              <span className="cm-summary">
                Creating: <b>{createOpp === "ai"
                  ? `${BOT_TIERS.find((t) => t.id === createDiff)?.name || createDiff} bot`
                  : "vs Friend"}</b>
                {", "}<b>{MODE_LABEL[newMode]}</b> auction
              </span>
              <button type="button" className="cm-create"
                onClick={() => createGame(createOpp === "ai", createDiff)}>
                Create Game
              </button>
            </div>
          </CreateModal>
        )}
        {showRules && <OddRulesModal onClose={() => setShowRules(false)} />}
        {toast && <div className="toast">{toast}</div>}
      </div>
    );
  }

  // ── waiting room ─────────────────────────────────────────────────────────
  if (screen === "waiting" || !game) {
    const isHost = roomData?.host === myId;
    const n = Object.keys(players).length;
    return (
      <div className="odd">
        <style>{styles}</style>
        <LobbyHeader onBack={leaveToLobby} title="Oddtrick" onRules={() => setShowRules(true)} user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : null} />
        <div className="panel" style={{ maxWidth: 480, margin: "2rem auto", textAlign: "center" }}>
          <h3>Room {roomId}</h3>
          <p className="muted">Share this code, or the link in your address bar.</p>
          <div style={{ margin: "1rem 0" }}>
            {Object.values(players).map((nm, i) => <div key={i}>{nm}</div>)}
          </div>
          {isHost && n >= 2 && <button className="btn" onClick={() => send({ action: "start" })}>Start</button>}
          {n < 2 && <div className="muted">Waiting for an opponent…</div>}
        </div>
        {showRules && <OddRulesModal onClose={() => setShowRules(false)} />}
        {toast && <div className="toast">{toast}</div>}
      </div>
    );
  }

  // ── game ─────────────────────────────────────────────────────────────────
  const oppSeat = 1 - mySeat;
  const nameOf = (seat) => players[seats[seat]] || (seat === mySeat ? "You" : "Opponent");
  const opt = game.options || { bids: [], may_pass: false };
  const bids = opt.bids || [];
  // Skat's price table, straight off /catalog — absent until it lands, which
  // only costs the "what clears this number" hint.
  const skatBases = catalog?.skat_bases || [];
  const skatNull = catalog?.skat_null_value ?? null;
  const ct = game.contract || {};
  const prev = lastTrick(game);
  const bidLevels = [...new Set(bids.filter((b) => b[1] !== NULL_DENOM).map((b) => b[0]))].sort((a, b) => a - b);
  const canNull = bids.some((b) => b[1] === NULL_DENOM);
  const denomOkAt = (l, d) => bids.some((b) => b[0] === l && b[1] === d);
  const bidReady = bidLevel !== null && bidDenom !== null && denomOkAt(bidLevel, bidDenom);
  const legal = new Set(game.legal || []);
  const res = game.result;

  const trickCards = (() => {
    // The led card, plus this seat's answer if it has been played.
    if (game.phase !== "play" || game.led === null || game.led === undefined) return [];
    return [{ seat: game.leader, c: game.led }];
  })();

  return (
    <div className="odd">
      <style>{styles}</style>
      <LobbyHeader onBack={leaveToLobby} title="Oddtrick" onRules={() => setShowRules(true)} user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : null} />
      {reconnecting && <div className="banner">Reconnecting…</div>}

      <div className="odd-main">
        <div className="odd-table">
          {/* opponent */}
          <div className="odd-seat">
            <div className="odd-seatname">
              <b>{nameOf(oppSeat)}</b>
              <span>{game.pts[oppSeat] >= 0 ? "+" : ""}{game.pts[oppSeat]} pts</span>
            </div>
            <div className="odd-hand">
              {/* Open: the declarer bought a multiplier by playing face up, so
                  their real cards are on the table from trick 1. */}
              {game.opp_hand
                ? game.opp_hand.map((c) => <Card key={c} c={c} />)
                : Array.from({ length: game.opp_hand_n }, (_, i) => <Card key={i} c={null} />)}
            </div>
            {game.opp_hand && (
              <div className="muted" style={{ fontSize: "0.72rem" }}>Open — played face up</div>
            )}
            <div className="odd-piles">
              {game.piles[oppSeat].map((p, i) => <Pile key={i} pile={p} playable={false} />)}
            </div>
          </div>

          {/* middle */}
          {game.phase === "auction" && isSkat ? (
            <div className="odd-auction">
              <div className="muted">Auction · a number, not a game</div>
              <ContractLine game={game} />
              {game.auction.value > 0 && (
                <div className="muted">{nameOf(declSeat)} holds it at {game.auction.value}</div>
              )}
              {game.redeals > 0 && (
                <div className="muted" style={{ fontSize: "0.78rem" }}>
                  Hand thrown in{game.redeals > 1 ? ` ${game.redeals} times` : ""} — redealt.
                </div>
              )}
              {myTurn ? (
                <>
                  <div className="odd-valgrid">
                    {(opt.values || []).map((v) => (
                      <button key={v} className={bidValue === v ? "on" : ""}
                        onClick={() => setBidValue(bidValue === v ? null : v)}>{v}</button>
                    ))}
                  </div>
                  {bidValue !== null && skatBases.length > 0 && (
                    <div className="odd-clears">
                      <span className="muted">{bidValue} is</span>
                      {clearedBy(bidValue, skatBases, catalog?.max_level).map((x) => (
                        <span key={x.denom} className={`odd-clear${x.denom === 1 || x.denom === 2 ? " red" : ""}`}>
                          {x.level}{DENOM_LABEL[x.denom]}
                        </span>
                      ))}
                      {bidValue === skatNull && <span className="odd-clear null">Null</span>}
                      <span className="muted">— and they can't tell which.</span>
                    </div>
                  )}
                  <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                    <button className="btn" disabled={bidValue === null} onClick={doValueBid}>
                      Bid {bidValue ?? ""}
                    </button>
                    <button className="btn btn-ghost" onClick={doPass}>Pass</button>
                  </div>
                  <div className="muted odd-hint">
                    {game.auction.value === 0
                      ? "Pass and your opponent takes the talon and the lead — at their own price. Both of you passing throws the hand in."
                      : "Push them one rung past their hand, or let them have it."}
                  </div>
                </>
              ) : <div className="muted">Waiting for {nameOf(game.auction.to_act)}…</div>}
              <div className="odd-bidlog">
                {(game.auction.log || []).map((e, i) => (
                  <div key={i}>
                    <span>{nameOf(e.seat)}</span>
                    <span>{e.pass ? "pass" : e.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : game.phase === "auction" ? (
            <div className="odd-auction">
              <div className="muted">Auction</div>
              <ContractLine game={game} />
              {game.auction.level > 0 && (
                <div className="muted">
                  {nameOf(game.auction.declarer)} to score at least {game.auction.level}
                </div>
              )}
              {myTurn ? (
                <>
                  <div className="odd-bidgrid">
                    {bidLevels.map((l) => (
                      <button key={l} className={bidLevel === l ? "on" : ""}
                        onClick={() => {
                          setBidLevel(l);
                          // Keep the denom only if it stays legal at this level.
                          if (bidDenom !== null && !denomOkAt(l, bidDenom)) setBidDenom(null);
                        }}>{l}</button>
                    ))}
                  </div>
                  <div className="odd-denoms">
                    {[0, 1, 2, 3, 4].map((d) => {
                      const ok = bidLevel !== null && denomOkAt(bidLevel, d);
                      return (
                        <button key={d}
                          className={`${bidDenom === d ? "on " : ""}${d === 1 || d === 2 ? "red" : ""}`}
                          disabled={!ok}
                          title={ok ? DENOM_NAME[d]
                            : bidLevel === null ? "pick a level first"
                              : "not available at that level"}
                          onClick={() => setBidDenom(d)}>{DENOM_LABEL[d]}</button>
                      );
                    })}
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                    <button className="btn" disabled={!bidReady} onClick={doBid}>
                      Bid {bidLevel ?? ""}{bidDenom !== null ? DENOM_LABEL[bidDenom] : ""}
                    </button>
                    {canNull && (
                      <button className="btn btn-ghost odd-nullbid"
                        title={`Win no +2 trick all round. Pays ${NULL_MAKE}; broken it pays them ${NULL_SET}. Bids as a ${NULL_LEVEL}.`}
                        onClick={() => send({ action: "move", move: { kind: "bid", level: NULL_LEVEL, denom: NULL_DENOM } })}>
                        Null
                      </button>
                    )}
                    {opt.may_pass && <button className="btn btn-ghost" onClick={doPass}>Pass</button>}
                  </div>
                  {!opt.may_pass && <div className="muted" style={{ fontSize: "0.8rem" }}>
                    The opener must bid.
                  </div>}
                </>
              ) : <div className="muted">Waiting for {nameOf(game.auction.to_act)}…</div>}
              <div className="odd-bidlog">
                {(game.auction.log || []).map((e, i) => (
                  <div key={i}>
                    <span>{nameOf(e.seat)}</span>
                    <span>{e.pass ? "pass"
                      : e.denom === NULL_DENOM ? "Null"
                        : `${e.level}${DENOM_LABEL[e.denom]}`}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : game.phase === "swap" ? (
            <div className="odd-auction">
              <div className="muted">The talon</div>
              <ContractLine game={game} />
              {game.swap ? (
                <>
                  <div className="muted" style={{ fontSize: "0.85rem" }}>
                    You won the auction. Three of the six set-aside cards — take
                    one into hand and discard, or stand pat.
                  </div>
                  <div className="odd-hand" style={{ justifyContent: "center" }}>
                    {game.swap.shown.map((c) => (
                      <Card key={c} c={c} sel={swapTake === c}
                        onClick={() => setSwapTake(swapTake === c ? null : c)} />
                    ))}
                  </div>
                  {swapTake !== null && (
                    <div className="muted" style={{ fontSize: "0.8rem" }}>
                      …and discard which card from your hand?
                    </div>
                  )}
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <button className="btn" disabled={swapTake === null || swapGive === null}
                      onClick={() => doSwap(swapTake, swapGive)}>
                      Swap {swapTake !== null ? cardName(swapTake) : ""}{swapGive !== null ? ` for ${cardName(swapGive)}` : ""}
                    </button>
                    <button className="btn btn-ghost" onClick={() => doSwap(null, null)}>
                      Stand pat
                    </button>
                  </div>
                </>
              ) : (
                <div className="muted">
                  {nameOf(game.auction.declarer)} is looking at three of the
                  set-aside cards…
                </div>
              )}
            </div>
          ) : game.phase === "talon" ? (
            <div className="odd-auction">
              <div className="muted">The talon · {game.auction.value} to beat</div>
              <ContractLine game={game} />
              {game.talon ? (
                !game.talon.looked ? (
                  <>
                    <div className="muted odd-hint">
                      You bought the declaration at <b>{game.auction.value}</b>. Look at
                      three of the six set-aside cards and you may take one into
                      hand — or decline to look at all and play <b>Hand</b>, worth
                      +1 to your multiplier.
                    </div>
                    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                      <button className="btn" onClick={() => doMove({ kind: "look" })}>
                        Look at the talon
                      </button>
                      <button className="btn btn-ghost odd-annbtn"
                        onClick={() => doMove({ kind: "hand" })}>
                        Play Hand (×2)
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="muted odd-hint">
                      Take one into hand and discard, or stand pat. Either way you
                      have looked, so Hand is gone.
                    </div>
                    <div className="odd-hand" style={{ justifyContent: "center" }}>
                      {game.talon.shown.map((c) => (
                        <Card key={c} c={c} sel={swapTake === c}
                          onClick={() => setSwapTake(swapTake === c ? null : c)} />
                      ))}
                    </div>
                    {swapTake !== null && (
                      <div className="muted" style={{ fontSize: "0.8rem" }}>
                        …and discard which card from your hand?
                      </div>
                    )}
                    <div style={{ display: "flex", gap: "0.5rem" }}>
                      <button className="btn" disabled={swapTake === null || swapGive === null}
                        onClick={() => doSwap(swapTake, swapGive)}>
                        Swap{swapTake !== null ? ` ${cardName(swapTake)}` : ""}
                        {swapGive !== null ? ` for ${cardName(swapGive)}` : ""}
                      </button>
                      <button className="btn btn-ghost" onClick={() => doSwap(null, null)}>
                        Stand pat
                      </button>
                    </div>
                  </>
                )
              ) : (
                <div className="muted">
                  {nameOf(declSeat)} won the auction at {game.auction.value} and is
                  deciding about the talon…
                </div>
              )}
            </div>
          ) : game.phase === "declare" ? (
            <div className="odd-auction">
              <div className="muted">Declare · your bid was {game.auction.value}</div>
              {game.declare ? (() => {
                const d = game.declare;
                const isNull = declDenom === NULL_DENOM;
                const row = d.denoms.find((x) => x.denom === declDenom);
                const value = isNull ? d.null_value : (row ? row.base * (declLevel || 0) : 0);
                const mult = 1 + (d.hand ? 1 : 0) + (declSharp ? 1 : 0) + (declOpen ? 1 : 0);
                // The same conditions apply_declare enforces, so the button is
                // never live on a declaration the server will refuse.
                const ok = (isNull ? d.null_ok && !declSharp
                  : !!row && declLevel >= row.min_level && declLevel <= d.max_level
                    && (!declOpen || declSharp));
                return (
                  <>
                    <div className="odd-denoms">
                      {d.denoms.map((x) => (
                        <button key={x.denom}
                          className={`${declDenom === x.denom ? "on " : ""}${x.denom === 1 || x.denom === 2 ? "red" : ""}`}
                          title={`${DENOM_NAME[x.denom]} — base ${x.base}, so at least level ${x.min_level}`}
                          // Announcements are legal in different combinations per
                          // denomination (Null takes no Sharp; every other game
                          // needs Sharp under Open), so switching denomination
                          // resets them rather than carrying a combination the
                          // server would refuse — and would leave unclearable,
                          // since the Open toggle disables itself without Sharp.
                          onClick={() => {
                            setDeclDenom(x.denom); setDeclLevel(x.min_level);
                            setDeclSharp(false); setDeclOpen(false);
                          }}>
                          {DENOM_LABEL[x.denom]}<small>×{x.base}</small>
                        </button>
                      ))}
                      {d.null_ok && (
                        <button className={`odd-nullbid${isNull ? " on" : ""}`}
                          title={`Win no +2 trick. Flat ${d.null_value}.`}
                          onClick={() => {
                            setDeclDenom(NULL_DENOM);
                            setDeclSharp(false); setDeclOpen(false);
                          }}>
                          Null
                        </button>
                      )}
                    </div>
                    {!isNull && row && (
                      <>
                        <div className="muted" style={{ fontSize: "0.8rem" }}>
                          At least level {row.min_level} to reach {d.bid}. Higher is
                          voluntary — it pays more and promises more.
                        </div>
                        <div className="odd-bidgrid">
                          {Array.from({ length: d.max_level - row.min_level + 1 },
                            (_, i) => row.min_level + i).map((l) => (
                              <button key={l} className={declLevel === l ? "on" : ""}
                                title={`${row.base} × ${l} = ${row.base * l}`}
                                onClick={() => setDeclLevel(l)}>{l}</button>
                            ))}
                        </div>
                      </>
                    )}
                    <div className="odd-anns">
                      {d.hand && <span className="odd-ann on" title="You never looked at the talon">Hand</span>}
                      {!isNull && (
                        <button className={`odd-ann${declSharp ? " on" : ""}`}
                          title={`Promise ${d.sharp_bonus} more than your level`}
                          onClick={() => {
                            const next = !declSharp;
                            setDeclSharp(next);
                            if (!next) setDeclOpen(false);   // Open rides on Sharp
                          }}>Sharp +{d.sharp_bonus}</button>
                      )}
                      <button className={`odd-ann${declOpen ? " on" : ""}`}
                        disabled={!isNull && !declSharp}
                        title={isNull ? "Play with your hand face up"
                          : "Sharp, with your hand face up from trick 1"}
                        onClick={() => setDeclOpen(!declOpen)}>Open</button>
                    </div>
                    <div className="odd-maths">
                      {isNull ? `Null, flat ${d.null_value}` : `${row?.base} × ${declLevel} = ${value}`}
                      {mult > 1 ? ` × ${mult} (${multParts({ ...d, sharp: declSharp, open: declOpen }).join(" + ")})` : ""}
                      {" = "}<b>{value * mult}</b>
                      {isNull ? " · win no +2 trick"
                        : ` · you must score ${declLevel + (declSharp ? d.sharp_bonus : 0)}`}
                    </div>
                    <button className="btn" disabled={!ok}
                      onClick={() => doDeclare(declDenom, isNull ? 0 : declLevel,
                        declSharp, declOpen)}>
                      Declare
                    </button>
                  </>
                );
              })() : (
                <div className="muted">{nameOf(declSeat)} is naming the game…</div>
              )}
            </div>
          ) : game.phase === "kontra" || game.phase === "re" ? (
            <div className="odd-auction">
              <div className="muted">{game.phase === "re" ? "Re?" : "Kontra?"}</div>
              <ContractLine game={game} />
              <SkatStake game={game} nameOf={nameOf} />
              {myKontra ? (
                <>
                  <div className="muted odd-hint">
                    You know the game at last. <b>Kontra</b> doubles it whichever
                    way it falls.
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <button className="btn odd-kontrabtn"
                      onClick={() => doMove({ kind: "kontra", on: true })}>Kontra ×2</button>
                    <button className="btn btn-ghost"
                      onClick={() => doMove({ kind: "kontra", on: false })}>Let it stand</button>
                  </div>
                </>
              ) : myRe ? (
                <>
                  <div className="muted odd-hint">
                    {nameOf(1 - declSeat)} doubled you. <b>Re</b> doubles it again.
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <button className="btn odd-kontrabtn"
                      onClick={() => doMove({ kind: "re", on: true })}>Re ×4</button>
                    <button className="btn btn-ghost"
                      onClick={() => doMove({ kind: "re", on: false })}>Accept</button>
                  </div>
                </>
              ) : (
                <div className="muted">
                  Waiting for {nameOf(game.phase === "re" ? declSeat : 1 - declSeat)}…
                </div>
              )}
            </div>
          ) : game.phase === "over" ? (
            <div className="odd-result">
              <div className={`odd-big ${res.made ? "made" : "set"}`}>
                {res.abandoned_by !== null && res.abandoned_by !== undefined
                  ? "Game abandoned"
                  : res.denom === NULL_DENOM
                    ? (res.made ? "Null made" : "Null broken")
                    : (res.made ? "Contract made" : "Contract set")}
              </div>
              {/* A forfeit has no contract to narrate — in skat mode the auction
                  may not even have produced a declarer, so every arithmetic line
                  below is skipped rather than printed against missing keys. */}
              {res.abandoned_by !== null && res.abandoned_by !== undefined ? (
                <div className="muted">
                  {nameOf(res.abandoned_by)} left the game, so{" "}
                  {nameOf(1 - res.abandoned_by)} takes{" "}
                  {res.scores[1 - res.abandoned_by]}
                  {res.level ? <>
                    {" "}for the standing {res.denom === NULL_DENOM ? "Null"
                      : `${res.level}${DENOM_LABEL[res.denom]}`} contract.
                  </> : "."}
                </div>
              ) : res.mode === "skat" ? <>
                <div className="muted">
                  {`${nameOf(res.declarer)} bought it at ${res.bid}, declared `}
                  {res.denom === NULL_DENOM ? "Null" : `${res.level}${DENOM_LABEL[res.denom]}`}
                  {multParts(res).length ? ` ${multParts(res).join(" + ")}` : ""}
                  {res.kontra ? (res.re ? " · Kontra + Re" : " · Kontra") : ""}
                  {res.denom === NULL_DENOM
                    ? ` and won ${res.declarer_etricks} scoring trick${res.declarer_etricks === 1 ? "" : "s"}`
                    : ` and scored ${res.declarer_pts} of the ${res.target} promised`}
                </div>
                <div className="odd-maths">
                  {`${res.value}`}
                  {res.mult > 1 ? ` × ${res.mult}` : ""}
                  {res.doubling > 1 ? ` × ${res.doubling}` : ""}
                  {res.mult > 1 || res.doubling > 1 ? ` = ${res.stake}` : ""}
                  {res.made
                    ? ` to ${nameOf(res.declarer)}`
                    : ` + 4 × ${res.short} = ${res.scores[1 - res.declarer]} to ${nameOf(1 - res.declarer)}`}
                </div>
              </> : <>
                <div className="muted">
                  {res.denom === NULL_DENOM
                    ? `${nameOf(res.declarer)} bid Null and won ${res.declarer_etricks} scoring trick${res.declarer_etricks === 1 ? "" : "s"}`
                    : `${nameOf(res.declarer)} bid ${res.level}${DENOM_LABEL[res.denom]} and scored ${res.declarer_pts}`}
                </div>
                <div className="odd-maths">
                  {res.denom === NULL_DENOM
                    ? (res.made
                      ? `flat ${NULL_MAKE} to ${nameOf(res.declarer)}`
                      : `flat ${NULL_SET} to ${nameOf(1 - res.declarer)}`)
                    : res.made
                      ? `${res.level} × ${res.level} = ${res.scores[res.declarer]} to ${nameOf(res.declarer)}`
                      : `${res.level - 1} + 4 × ${res.short} = ${res.scores[1 - res.declarer]} to ${nameOf(1 - res.declarer)}`}
                </div>
              </>}
              <div className="odd-scorerow" style={{ gap: "1.5rem", fontSize: "1.1rem" }}>
                <span>{nameOf(mySeat)} <b>{res.scores[mySeat]}</b></span>
                <span>{nameOf(oppSeat)} <b>{res.scores[oppSeat]}</b></span>
              </div>
              {/* The six nobody was dealt, revealed. Every card you could not
                  account for all round was either in their hand or in here, so
                  this is the answer sheet — as cards, because a run of text
                  codes is not something you can read a hand off. */}
              {game.out && (
                <div className="odd-reveal">
                  <div className="muted">Out of play all round</div>
                  <div className="odd-outrow">
                    {game.out.map((c) => <Card key={c} c={c} small />)}
                  </div>
                  {game.shown && (
                    <div className="muted" style={{ fontSize: "0.72rem" }}>
                      {nameOf(res.declarer)} was shown {game.shown.map(cardName).join(" ")}
                    </div>
                  )}
                </div>
              )}
              <button className="btn" onClick={leaveToLobby}>Back to lobby</button>
            </div>
          ) : (
            <>
              <div className="odd-trick">
                {trickCards.length === 0
                  ? <div className="muted">{myTurn ? "Your lead" : "Waiting…"}</div>
                  : trickCards.map((t, i) => (
                    <div key={i} style={{ textAlign: "center" }}>
                      <Card c={t.c} />
                      <div className="muted" style={{ fontSize: "0.72rem" }}>{nameOf(t.seat)}</div>
                    </div>
                  ))}
                <div className="odd-trickinfo">
                  Trick {game.trick + 1} of 13 ·{" "}
                  <span className={`odd-val ${game.trick_value > 0 ? "good" : "bad"}`}>
                    {game.trick_value > 0 ? "+2" : "−1"}
                  </span>
                </div>
              </div>
              <TrickStrip game={game} />
              <div className="odd-turnbar">
                {myTurn ? <span className="odd-yourturn">Your turn</span>
                  : <span className="muted">{nameOf(game.to_play)} is thinking…</span>}
              </div>
            </>
          )}

          {/* you */}
          <div className="odd-seat">
            <div className="odd-piles">
              {game.piles[mySeat].map((p, i) => (
                <Pile key={i} pile={p}
                  playable={legal.has(p?.top)}
                  onPlay={myTurn && legal.has(p?.top) ? () => doPlay(p.top) : null} />
              ))}
            </div>
            <div className="odd-hand">
              {(game.hand || []).map((c) => (
                <Card key={c} c={c}
                  sel={(game.phase === "swap" || game.phase === "talon") && swapGive === c}
                  dim={game.phase === "play" && myTurn && !legal.has(c)}
                  onClick={
                    (game.phase === "swap" ? game.swap : game.phase === "talon" ? game.talon : null)
                      && swapTake !== null
                      ? () => setSwapGive(swapGive === c ? null : c)
                      : myTurn && legal.has(c) ? () => doPlay(c) : null
                  } />
              ))}
            </div>
            <div className="odd-seatname">
              <b>{nameOf(mySeat)}</b>
              <span>{game.pts[mySeat] >= 0 ? "+" : ""}{game.pts[mySeat]} pts</span>
            </div>
          </div>
        </div>

        {/* side panel */}
        <div className="odd-side">
          <div className="odd-panel">
            <h4>Contract</h4>
            {isSkat && <>
              <div className="odd-scorerow">
                <span>{declSeat >= 0 ? `${nameOf(declSeat)} bought it at` : "Standing bid"}</span>
                <b>{game.auction.value || "—"}</b>
              </div>
              {game.auction.level > 0 && <>
                <div className="odd-scorerow">
                  <span>Declared</span>
                  <b>{game.auction.denom === NULL_DENOM ? "Null"
                    : `${game.auction.level}${DENOM_LABEL[game.auction.denom]}`}</b>
                </div>
                <div className="odd-scorerow">
                  <span>{game.auction.denom === NULL_DENOM ? "Must win" : "Must score"}</span>
                  <b>{game.auction.denom === NULL_DENOM ? "no +2 trick"
                    : game.auction.level + (ct.sharp ? (catalog?.sharp_bonus ?? 3) : 0)}</b>
                </div>
                <SkatStake game={game} nameOf={nameOf} rows />
              </>}
            </>}
            {isSkat ? null : game.auction.level
              ? game.auction.denom === NULL_DENOM ? <>
                <div className="odd-scorerow">
                  <span>{nameOf(game.auction.declarer)} must win</span>
                  <b>no +2 trick</b>
                </div>
                <div className="odd-scorerow">
                  <span>Trump</span><b>none</b>
                </div>
                <div className="odd-scorerow">
                  <span>Makes it for</span><b>{NULL_MAKE}</b>
                </div>
                <div className="odd-scorerow">
                  <span>Broken pays them</span><b>{NULL_SET}</b>
                </div>
              </> : <>
                <div className="odd-scorerow">
                  <span>{nameOf(game.auction.declarer)} needs</span>
                  <b>{game.auction.level}</b>
                </div>
                <div className="odd-scorerow">
                  <span>Trump</span><b>{DENOM_NAME[game.auction.denom]}</b>
                </div>
                <div className="odd-scorerow">
                  <span>Makes it for</span><b>{game.auction.level * game.auction.level}</b>
                </div>
              </>
              : <div className="muted">Being decided…</div>}
            {game.swapped !== null && game.swapped !== undefined && (
              <div className="muted" style={{ fontSize: "0.72rem", marginTop: "0.3rem" }}>
                {game.swapped
                  ? `${nameOf(declSeat)} exchanged a card with the talon.`
                  : isSkat && ct.hand
                    // Hand and stood-pat both leave `swapped` false, and they are
                    // very different reads — one never saw the cards at all.
                    ? `${nameOf(declSeat)} never looked at the talon.`
                    : `${nameOf(declSeat)} stood pat.`}
              </div>
            )}
          </div>
          {/* The trick just gone. It leaves the table the instant the next lead
              arrives, and "what did they just play" is the question the log
              answers worst — it is a flat list of cards with no trick breaks. */}
          {prev && (
            <div className="odd-panel">
              <h4>Last trick</h4>
              <div className="odd-lasttrick">
                {prev.plays.map((p, i) => (
                  <div key={i} className={`odd-lt-play${p[0] === prev.winner ? " won" : ""}`}>
                    <Card c={p[1]} small />
                    <div className="muted">{nameOf(p[0])}</div>
                  </div>
                ))}
                <div className="odd-lt-note">
                  <div>#{prev.number}</div>
                  <div className={`odd-val ${prev.value > 0 ? "good" : "bad"}`}>
                    {prev.value > 0 ? "+2" : "−1"}
                  </div>
                  <div className="muted">{nameOf(prev.winner)} took it</div>
                </div>
              </div>
            </div>
          )}
          {/* The talon, for the seat that bought the right to see it. It stays
              on screen for the rest of the round: three cards you know are out
              of play is a real holding to count from, and losing sight of them
              the moment the swap resolves threw that away. After a swap this
              tracks what is ACTUALLY out — your discard sits where the card you
              took used to be. */}
          {game.shown && game.phase !== "over" && (
            <div className="odd-panel">
              <h4>Set aside · you saw these</h4>
              <div className="odd-outrow">
                {game.shown.map((c) => <Card key={c} c={c} small />)}
              </div>
              {game.swapped && (
                <div className="muted" style={{ fontSize: "0.7rem", marginTop: "0.3rem" }}>
                  Includes the card you discarded.
                </div>
              )}
            </div>
          )}
          <div className="odd-panel">
            <h4>Points</h4>
            <div className="odd-scorerow"><span>{nameOf(mySeat)}</span><b>{game.pts[mySeat]}</b></div>
            <div className="odd-scorerow"><span>{nameOf(oppSeat)}</span><b>{game.pts[oppSeat]}</b></div>
            <div className="muted" style={{ fontSize: "0.72rem", marginTop: "0.3rem" }}>
              Always adds up to +5.
            </div>
          </div>
          <div className="odd-panel">
            <h4>Tricks played</h4>
            <div className="odd-log">
              {(game.history || []).length === 0 && <div>Nothing yet.</div>}
              {(game.history || []).slice().reverse().slice(0, 26).map((h, i) => (
                <div key={i}><span>{nameOf(h[0])}</span><span>{cardName(h[1])}</span></div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {showRules && <OddRulesModal onClose={() => setShowRules(false)} />}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

function OddRulesModal({ onClose }) {
  return (
    <RulesModal title="How to play — Oddtrick" onClose={onClose}>
      <OddtrickRules />
    </RulesModal>
  );
}
