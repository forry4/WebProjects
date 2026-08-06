import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbySectionHd, LobbyEmpty, TurnBadge, LobbyLoading,
  LobbyTabs, GameMenu, gameMenuCss, readLobbyCache, writeLobbyCache,
  createModalCss, CreateModal, CmRow, CmSeg, LobbyCreateRow, lobbyCreateRowCss,
  useProgressiveList,
} from "../../shared/lobby.jsx";
import { parsePath, buildPath, pushPath, subscribe } from "../../shared/router.js";

// CSS lives in the sibling .css file, imported ?inline as a STRING and injected
// by this component's own <style> while mounted. Never a JS template literal —
// one stray backtick there reparses the rest of the file and blanks the page.
import _cssText from "./Oddtrick.css?inline";

const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const OT_WS = WS_RAW.replace(/\/ws$/, "/oddtrick/ws");
const OT_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/oddtrick");

const styles = baseCss + lobbyCss + gameMenuCss + createModalCss + lobbyCreateRowCss + _cssText;

const SUIT_GLYPH = ["♣", "♦", "♥", "♠"];   // c d h s
const RANKS = ["8", "9", "10", "J", "Q", "K", "A"];
const DENOM_LABEL = ["♣", "♦", "♥", "♠", "NT"];
const DENOM_NAME = ["Clubs", "Diamonds", "Hearts", "Spades", "No-trump"];
const NOTRUMP = 4;

const BOT_TIERS = [
  { id: "easy", name: "Easy", desc: "Plays legally, blunders often" },
  { id: "normal", name: "Normal", desc: "Knows which tricks it wants" },
];

const suitOf = (c) => Math.floor(c / 7);
const rankOf = (c) => c % 7;
const isRed = (c) => suitOf(c) === 1 || suitOf(c) === 2;
const cardName = (c) => RANKS[rankOf(c)] + SUIT_GLYPH[suitOf(c)];
// Trick NUMBER t (1-based): even ones pay +2, odd ones cost 1.
const trickValue = (t0) => (t0 % 2 === 1 ? 2 : -1);

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
    + `${dim ? " dim" : ""}${sel ? " sel" : ""}`;
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

function ContractLine({ game }) {
  const a = game.auction || {};
  if (!a.level) return <span className="muted">no contract yet</span>;
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

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);
  useEffect(() => () => disconnect(), []); // eslint-disable-line
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2600); return () => clearTimeout(t); } }, [toast]);
  // A fresh contract clears any half-built bid.
  useEffect(() => { setBidLevel(null); setBidDenom(null); }, [game?.auction?.level, game?.auction?.to_act]);

  const createGame = (vsAi, difficulty) => {
    const rid = roomCode();
    setConnecting(true); setShowCreate(false);
    connect(`${OT_WS}/${rid}/${myId}`, {
      action: "create", name: authUser?.name || "Player",
      vs_ai: vsAi, ai_difficulty: difficulty,
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
                <div className="lby-cardtitle">{g.host_name || "Player"}</div>
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
                </div>
                <div className="lby-cardsub">
                  {g.your_score}–{g.opp_score}
                  {g.contract ? ` · ${g.contract.you_declared ? "declared" : "defended"} `
                    + `${g.contract.level}${DENOM_LABEL[g.contract.denom] || ""}`
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
        <LobbyHeader onBack={onExit} title="Oddtrick" onRules={() => setShowRules(true)} user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : null} />
        <LobbyCreateRow
          onCreate={() => setShowCreate(true)}
          onJoin={(code) => joinGame(code.toUpperCase())}
          onRefresh={fetchGames}
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
          <CreateModal title="New game" onClose={() => setShowCreate(false)}>
            <CmRow label="Opponent">
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                <button className="btn" onClick={() => createGame(false, "normal")}>A friend</button>
                {BOT_TIERS.map((t) => (
                  <button key={t.id} className="btn btn-ghost" title={t.desc}
                    onClick={() => createGame(true, t.id)}>Bot · {t.name}</button>
                ))}
              </div>
            </CmRow>
          </CreateModal>
        )}
        {showRules && <RulesModal onClose={() => setShowRules(false)} />}
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
        {showRules && <RulesModal onClose={() => setShowRules(false)} />}
        {toast && <div className="toast">{toast}</div>}
      </div>
    );
  }

  // ── game ─────────────────────────────────────────────────────────────────
  const oppSeat = 1 - mySeat;
  const nameOf = (seat) => players[seats[seat]] || (seat === mySeat ? "You" : "Opponent");
  const opt = game.options || { levels: [], denoms: [], may_pass: false };
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
              {Array.from({ length: game.opp_hand_n }, (_, i) => <Card key={i} c={null} />)}
            </div>
            <div className="odd-piles">
              {game.piles[oppSeat].map((p, i) => <Pile key={i} pile={p} playable={false} />)}
            </div>
          </div>

          {/* middle */}
          {game.phase === "auction" ? (
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
                    {opt.levels.map((l) => (
                      <button key={l} className={bidLevel === l ? "on" : ""}
                        onClick={() => setBidLevel(l)}>{l}</button>
                    ))}
                  </div>
                  <div className="odd-denoms">
                    {[0, 1, 2, 3, 4].map((d) => (
                      <button key={d}
                        className={`${bidDenom === d ? "on " : ""}${d === 1 || d === 2 ? "red" : ""}`}
                        disabled={!opt.denoms.includes(d)}
                        title={opt.denoms.includes(d) ? DENOM_NAME[d] : "already named by you"}
                        onClick={() => setBidDenom(d)}>{DENOM_LABEL[d]}</button>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <button className="btn" disabled={bidLevel === null || bidDenom === null}
                      onClick={doBid}>
                      Bid {bidLevel ?? ""}{bidDenom !== null ? DENOM_LABEL[bidDenom] : ""}
                    </button>
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
                    <span>{e.pass ? "pass" : `${e.level}${DENOM_LABEL[e.denom]}`}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : game.phase === "over" ? (
            <div className="odd-result">
              <div className={`odd-big ${res.made ? "made" : "set"}`}>
                {res.made ? "Contract made" : "Contract set"}
              </div>
              <div className="muted">
                {nameOf(res.declarer)} bid {res.level}{DENOM_LABEL[res.denom]} and scored {res.declarer_pts}
              </div>
              <div className="odd-maths">
                {res.made
                  ? `${res.level} × ${res.level} = ${res.scores[res.declarer]} to ${nameOf(res.declarer)}`
                  : `${res.level - 1} + 4 × ${res.short} = ${res.scores[1 - res.declarer]} to ${nameOf(1 - res.declarer)}`}
              </div>
              <div className="odd-scorerow" style={{ gap: "1.5rem", fontSize: "1.1rem" }}>
                <span>{nameOf(mySeat)} <b>{res.scores[mySeat]}</b></span>
                <span>{nameOf(oppSeat)} <b>{res.scores[oppSeat]}</b></span>
              </div>
              {game.out && <div className="muted" style={{ fontSize: "0.8rem" }}>
                Out of play: {game.out.map(cardName).join(" ")}
              </div>}
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
                  dim={game.phase === "play" && myTurn && !legal.has(c)}
                  onClick={myTurn && legal.has(c) ? () => doPlay(c) : null} />
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
            {game.auction.level
              ? <>
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
          </div>
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

      {showRules && <RulesModal onClose={() => setShowRules(false)} />}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

function RulesModal({ onClose }) {
  return (
    <CreateModal title="How Oddtrick works" onClose={onClose}>
      <div className="odd-rules">
        <p>
          A trick-taking game where taking tricks is <b>not simply good</b>.
          Even-numbered tricks pay <b>+2</b>; odd-numbered ones cost <b>1</b>.
          Six good and seven bad, so both scores always total +5 — sweeping all
          thirteen tricks scores 5, while taking exactly the six even ones
          scores 12. The game is about <i>which</i> tricks you win.
        </p>
        <h4>Your cards</h4>
        <p>
          Thirteen each: seven in hand, plus three piles of two. Only a pile's
          top card is playable; the one underneath becomes playable — and
          visible to both of you — once the top is gone. The middle pile's
          bottom card is face-up from the start; the outer two are hidden from
          everyone, <i>including you</i>. Two cards are set aside unseen.
        </p>
        <h4>The auction</h4>
        <p>
          The opener names a number and a suit (or no-trump), promising to
          finish with <b>at least</b> that many points. You may pass, or
          overtake by raising the number by <b>one or two</b> and naming a
          denomination you have not used yet. Whoever holds the last bid
          declares — and <b>leads to trick one</b>.
        </p>
        <h4>Playing</h4>
        <p>
          Follow suit if you can — and a pile's exposed top card counts as a
          card you hold. Otherwise play anything, including trump. Highest
          trump wins, else the highest card of the suit led. The winner leads
          next.
        </p>
        <h4>Scoring</h4>
        <p>
          Make the contract and you score <code>N × N</code>. Fall short and
          your <i>opponent</i> scores <code>(N − 1) + 4</code> per point you
          missed by.
        </p>
        <h4>The thing to notice</h4>
        <p>
          You need high cards to win the +2 tricks, but you also need <b>low</b>
          {" "}ones: leading your smallest card into an odd trick forces your
          opponent to win it and eat the penalty. A hand of pure aces is bad.
        </p>
      </div>
    </CreateModal>
  );
}
