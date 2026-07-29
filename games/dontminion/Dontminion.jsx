import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbySectionHd, TurnBadge, GameMenu, gameMenuCss,
  readLobbyCache, writeLobbyCache, createModalCss, CreateModal, CmRow, CmSeg,
  LobbyCreateRow, lobbyCreateRowCss,
} from "../../shared/lobby.jsx";
// Only the shared CARD FRAME (sizing vars + .card chrome). Dontminion's card face
// is its own markup — no gems here, but the frame keeps all five games' cards the
// same physical object on screen.
import { splendorCardCss } from "../../shared/splendor.jsx";
import { parsePath, buildPath, pushPath, replacePath, subscribe } from "../../shared/router.js";

// CSS lives in the sibling .css file, imported `?inline` (a string injected by this
// component's own <style> tag) — NEVER a JS template literal (the documented
// stray-backtick blank-page footgun).
import _cssText from "./Dontminion.css?inline";

// ─── Config ────────────────────────────────────────────────────────────────
const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const DM_WS = WS_RAW.replace(/\/ws$/, "/dontminion/ws");
const DM_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/dontminion");

const BOT_TIERS = [
  { id: "easy", name: "Easy", desc: "Plays random legal moves" },
  { id: "normal", name: "Normal", desc: "Plays random legal moves (for now)" },
  { id: "hard", name: "Hard", desc: "Plays random legal moves (for now)" },
];
const EXPANSIONS = [
  { id: "base", name: "Base Set" },
  { id: "intrigue", name: "Intrigue" },
];
const BASIC_ROW = ["Copper", "Silver", "Gold", "Estate", "Duchy", "Province", "Curse"];

function uid() { return Math.random().toString(36).slice(2, 10); }
function roomCode() { return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join(""); }
function timeAgo(ts) {
  if (!ts) return "";
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// Card-face tinting by primary type (dual types show a split banner).
const TYPE_LABEL = {
  action: "Action", treasure: "Treasure", victory: "Victory", curse: "Curse",
  attack: "Attack", reaction: "Reaction",
};
const typeBanner = (types) => (types || []).map((t) => TYPE_LABEL[t] || t).join(" – ");
const faceClass = (types) => {
  if (!types) return "";
  if (types.includes("curse")) return "dm-f-curse";
  if (types.includes("treasure")) return "dm-f-treasure";
  if (types.includes("victory")) return "dm-f-victory";
  return "dm-f-action";
};

function DmCardFace({ name, card, count, onClick, selected, disabled, highlight, small, badge }) {
  const types = card?.types || [];
  const cls = ["card", "dm-card", faceClass(types),
    small ? "dm-card-small" : "",
    selected ? "dm-sel" : "", highlight ? "dm-hl" : "",
    disabled ? "dm-dis" : "", onClick && !disabled ? "dm-clickable" : ""].filter(Boolean).join(" ");
  return (
    <div className={cls} onClick={disabled ? undefined : onClick} title={card ? `${name} (${card.cost}) — ${card.text}` : name}>
      {types.includes("attack") && <span className="dm-edge dm-edge-atk" />}
      {types.includes("reaction") && <span className="dm-edge dm-edge-rx" />}
      <div className="dm-card-name">{name}</div>
      {!small && <div className="dm-card-text">{card?.text || ""}</div>}
      <div className="dm-card-bottom">
        <span className="dm-cost">{card ? card.cost : ""}</span>
        <span className="dm-type">{typeBanner(types)}</span>
      </div>
      {count != null && <span className="dm-pile-count">{count}</span>}
      {badge != null && <span className="dm-card-badge">{badge}</span>}
    </div>
  );
}

// ─── Log formatting ─────────────────────────────────────────────────────────
function fmtLog(e, names) {
  const who = e.pid ? (names[e.pid] || e.pid) : "";
  switch (e.event) {
    case "turn_start": return `— ${who}'s turn (${e.turn}) —`;
    case "phase": return `${who} moves to the buy phase`;
    case "play": return `${who} plays ${e.card}`;
    case "buy": return `${who} buys ${e.card}`;
    case "gain": return e.dest && e.dest !== "discard"
      ? `${who} gains ${e.card} (to ${e.dest})` : `${who} gains ${e.card}`;
    case "gain_from_trash": return `${who} gains ${e.card} from the trash`;
    case "trash": return `${who} trashes ${(e.cards || []).join(", ")}`;
    case "supply_trash": return `${who} trashes ${e.card} from the Supply`;
    case "discard": return e.cards ? `${who} discards ${e.cards.join(", ")}`
      : `${who} discards ${e.n} card${e.n === 1 ? "" : "s"}`;
    case "draw": return `${who} draws ${e.n} card${e.n === 1 ? "" : "s"}`;
    case "shuffle": return `${who} shuffles their deck`;
    case "reveal": return `${who} reveals ${(e.cards || []).join(", ")}`;
    case "topdeck": return e.card ? `${who} puts ${e.card} onto their deck`
      : `${who} puts a card onto their deck`;
    case "deck_insert": return `${who} slips a card into their deck`;
    case "secret_passage": return `${who} places it ${e.position === 0 ? "on top" : e.position >= (e.depth - 1) ? "on the bottom" : `${e.position} deep`}`;
    case "named": return `${who} names ${e.card}`;
    case "pass": return `${who} passes ${e.card} to ${names[e.to] || e.to}`;
    case "pass_public": return `${who} passes a card to ${names[e.to] || e.to}`;
    case "abandon": return `${who} abandoned the game`;
    case "game_over": return `Game over — ${(e.winners || []).map((w) => names[w] || w).join(" & ")} win${(e.winners || []).length > 1 ? "" : "s"}!`;
    default: return null;
  }
}

// ─── Socket hook ─────────────────────────────────────────────────────────────
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
  const disconnect = useCallback(() => { try { wsRef.current?.close(); } catch {} wsRef.current = null; setConnected(false); }, []);
  const socketReady = useCallback(() => wsRef.current?.readyState, []);
  return { connected, connect, send, disconnect, socketReady };
}

// ─── Styles (no backticks anywhere in the css string) ───────────────────────
const dmStyles = baseCss + lobbyCss + splendorCardCss + _cssText
  + gameMenuCss + createModalCss + lobbyCreateRowCss;

// ─── Main component ─────────────────────────────────────────────────────────
export default function Dontminion({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");     // lobby | waiting | game
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [catalog, setCatalog] = useState(null);      // {cards, kingdom, expansions}
  const [openGames, setOpenGames] = useState(() => readLobbyCache("dontminion", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("dontminion", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("dontminion", myId, "history", []));
  const [loadingGames, setLoadingGames] = useState(false);
  const [toast, setToast] = useState("");
  const [reconnecting, setReconnecting] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createOpp, setCreateOpp] = useState("ai");
  const [createDiff, setCreateDiff] = useState("normal");
  const [createBots, setCreateBots] = useState(1);
  const [createPlayers, setCreatePlayers] = useState(4);
  const [createExps, setCreateExps] = useState(["base", "intrigue"]);
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  const [gameOverDismissed, setGameOverDismissed] = useState(false);
  const [showTrash, setShowTrash] = useState(false);
  // decision-prompt interaction state (generic across all frame kinds)
  const [pickIdx, setPickIdx] = useState([]);        // choose_cards: selected INDICES (dups!)
  const [pickOpts, setPickOpts] = useState([]);      // choose_option pick>1: selected ids
  const [orderIdx, setOrderIdx] = useState([]);      // order_cards: click sequence of indices

  // ── URL routing refs (segment 2 = room id; the shell owns "/dontminion") ──
  const screenRef = useRef(screen);
  screenRef.current = screen;
  const roomIdRef = useRef(roomId);
  roomIdRef.current = roomId;
  const urlAttemptRef = useRef(null);
  const didInitRef = useRef(false);
  const popHandlerRef = useRef(() => {});
  const reconnTimer = useRef(null);
  const reconnTries = useRef(0);

  const playerName = authUser?.name || "Player";

  // ── derived (keep ABOVE all effects — TDZ rule) ──
  const game = roomData?.game;
  const names = roomData?.players || {};
  const cards = catalog?.cards || {};
  const seats = game?.seats || {};
  const mySeat = seats[myId];
  const over = !!game?.over;
  const pv = game?.pending_view || null;
  const iAmActor = !!pv && !over && game?.pending_pid === myId && !!pv.constraint;
  const waitingOn = pv && !iAmActor ? pv.waiting_on : null;
  const myTurn = !!game && !over
    && (game.pending_pid ? game.pending_pid === myId : game.turn === myId);
  const botActing = !!game && !over && (roomData?.ai_players || []).includes(game.pending_pid || game.turn);
  const bridges = game?.turn_ctx?.bridges || 0;
  const effCost = (name) => Math.max(0, (cards[name]?.cost ?? 0) - bridges);
  const inBuy = !!game && game.phase === "buy" && game.turn === myId && !game.pending_pid && !over;
  const inAction = !!game && game.phase === "action" && game.turn === myId && !game.pending_pid && !over;
  const bought = !!game?.turn_ctx?.bought;
  const handTreasures = (mySeat?.hand || []).some((c) => cards[c]?.types?.includes("treasure"));
  const constraint = iAmActor ? pv.constraint : null;
  const kingdomPiles = game?.kingdom || [];
  const seatOrder = game?.players || Object.keys(names);
  const oppOrder = seatOrder.filter((p) => p !== myId);

  // ── socket plumbing ──
  const handleMessage = useCallback((msg) => {
    if (msg.type === "error") {
      const ua = urlAttemptRef.current;
      if (ua) {
        if (msg.message === "invalid token" && !ua.retried) {
          ua.retried = true;
          try { localStorage.removeItem(`dm_token_${ua.rid}_${myId}`); } catch {}
          resumeGame(ua.rid);
          return;
        }
        urlAttemptRef.current = null;
        try {
          if (localStorage.getItem("dm_roomId") === ua.rid) localStorage.removeItem("dm_roomId");
          localStorage.removeItem(`dm_token_${ua.rid}_${myId}`);
        } catch {}
        setRoomId(""); setRoomData(null); setScreen("lobby");
        replacePath(buildPath("dontminion"));
      }
      setToast(msg.message || "error"); return;
    }
    const room = msg.room;
    if (!room) return;
    const rid = room.room_id || roomId;
    const tok = room.reconnect_tokens?.[myId];
    if (tok) {
      try {
        localStorage.setItem(`dm_token_${rid}_${myId}`, tok);
        localStorage.setItem("dm_roomId", rid);
      } catch {}
    }
    setRoomData(room);
    const inGame = room.status === "playing" || room.status === "over";
    if (msg.type === "created" || msg.type === "joined" || msg.type === "reconnected") {
      if (rid) pushPath(buildPath("dontminion", rid));
      urlAttemptRef.current = null;
      setScreen(inGame ? "game" : "waiting");
    } else if (msg.type === "room_update" && inGame && screenRef.current !== "game") {
      setScreen("game");
    }
  }, [myId, roomId]); // eslint-disable-line react-hooks/exhaustive-deps

  const { connected, connect, send, disconnect, socketReady } = useSocket(handleMessage);

  useEffect(() => {
    fetch(`${DM_HTTP}/catalog`).then((r) => r.json()).then((d) => { if (d.ok) setCatalog(d); }).catch(() => {});
  }, []);

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${DM_HTTP}/games`).then((r) => r.json()).then((d) => { const g = d.games || []; setOpenGames(g); writeLobbyCache("dontminion", myId, "open", g); })
      .catch(() => {}).finally(() => setLoadingGames(false));
    if (authUser?.session_token) {
      const headers = { Authorization: `Bearer ${authUser.session_token}` };
      fetch(`${DM_HTTP}/games/mine`, { headers }).then((r) => r.json()).then((d) => { const g = d.games || []; setMyGames(g); writeLobbyCache("dontminion", myId, "mine", g); }).catch(() => {});
      fetch(`${DM_HTTP}/games/history`, { headers }).then((r) => r.json()).then((d) => { const g = d.games || []; setHistory(g); writeLobbyCache("dontminion", myId, "history", g); }).catch(() => {});
    } else { setMyGames([]); setHistory([]); writeLobbyCache("dontminion", myId, "mine", []); writeLobbyCache("dontminion", myId, "history", []); }
  }, [authUser, myId]);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);
  useEffect(() => { return () => disconnect(); }, []); // eslint-disable-line

  // ── URL deep entry + popstate ──
  const urlResume = (rid) => {
    urlAttemptRef.current = { rid, retried: false };
    resumeGame(rid);
  };
  useEffect(() => {
    if (didInitRef.current) return;
    didInitRef.current = true;
    const r = parsePath();
    if (r.game === "dontminion" && r.room) urlResume(r.room);
  }, []); // eslint-disable-line
  popHandlerRef.current = (r) => {
    if (r.game !== "dontminion") return;
    if (r.room && r.room !== roomIdRef.current) {
      urlResume(r.room);
    } else if (!r.room && (roomIdRef.current || urlAttemptRef.current)) {
      urlAttemptRef.current = null;
      leaveToLobby();
    }
  };
  useEffect(() => subscribe((r) => popHandlerRef.current(r)), []); // eslint-disable-line

  // ── auto-reconnect while in a live game (re-kicks the bot scheduler server-side) ──
  const inLiveGame = !!roomId && (screen === "game" || screen === "waiting") && roomData?.status !== "over";
  const attemptReconnect = useCallback(() => {
    if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; }
    const rs = socketReady();
    if (rs === 0 || rs === 1) { reconnTimer.current = setTimeout(attemptReconnect, 3000); return; }
    let tok = null;
    try { tok = localStorage.getItem(`dm_token_${roomId}_${myId}`); } catch {}
    if (tok) { setReconnecting(true); connect(`${DM_WS}/${roomId}/${myId}`, { action: "reconnect", token: tok }); }
    reconnTries.current += 1;
    reconnTimer.current = setTimeout(attemptReconnect, Math.min(2000 * reconnTries.current, 8000));
  }, [roomId, myId, connect, socketReady]);

  useEffect(() => {
    const clear = () => { if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; } };
    if (connected || !inLiveGame) {
      clear(); reconnTries.current = 0;
      if (connected) setReconnecting(false);
      return;
    }
    if (!reconnTimer.current) attemptReconnect();
    return clear;
  }, [connected, inLiveGame, attemptReconnect]);

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState !== "visible" || connected || !inLiveGame) return;
      reconnTries.current = 0;
      attemptReconnect();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [connected, inLiveGame, attemptReconnect]);

  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2600); return () => clearTimeout(t); } }, [toast]);

  // clear decision-prompt state whenever the decision context changes
  useEffect(() => {
    setPickIdx([]); setPickOpts([]); setOrderIdx([]);
  }, [game?.turn, game?.turn_number, game?.pending_kind, game?.pending_pid, (game?.log || []).length]);
  useEffect(() => { setGameOverDismissed(false); }, [roomId]);

  // ── actions ──
  const mv = (move) => send({ action: "move", move });

  const createGame = () => {
    const rid = roomCode();
    setRoomId(rid);
    setRoomData(null);
    setShowCreateModal(false);
    const msg = {
      action: "create", name: playerName, expansions: createExps,
      vs_ai: createOpp === "ai",
    };
    if (createOpp === "ai") {
      msg.num_bots = createBots;
      msg.ai_difficulty = createDiff;
    } else {
      msg.max_players = createPlayers;
    }
    connect(`${DM_WS}/${rid}/${myId}`, msg);
  };
  const joinGame = (rid) => {
    rid = (rid || "").toUpperCase().trim();
    if (!rid) return;
    setRoomId(rid);
    connect(`${DM_WS}/${rid}/${myId}`, { action: "join", name: playerName, session_token: authUser?.session_token });
  };
  const resumeGame = (rid) => {
    let tok = null;
    try { tok = localStorage.getItem(`dm_token_${rid}_${myId}`); } catch {}
    setRoomId(rid);
    connect(`${DM_WS}/${rid}/${myId}`, tok ? { action: "reconnect", token: tok } : { action: "join", name: playerName, session_token: authUser?.session_token });
  };
  const cancelGame = (rid) => {
    const headers = { "Content-Type": "application/json" };
    if (authUser?.session_token) headers.Authorization = `Bearer ${authUser.session_token}`;
    fetch(`${DM_HTTP}/games/${rid}/cancel?player_id=${encodeURIComponent(myId)}`, { method: "POST", headers })
      .then((r) => r.json()).then((d) => {
        if (!d.ok) { setToast(d.message || "Could not cancel"); return; }
        try {
          if (localStorage.getItem("dm_roomId") === rid) localStorage.removeItem("dm_roomId");
          localStorage.removeItem(`dm_token_${rid}_${myId}`);
        } catch {}
        fetchGames();
      }).catch(() => setToast("Could not cancel"));
  };
  const leaveToLobby = () => {
    disconnect();
    pushPath(buildPath("dontminion"));
    setScreen("lobby");
    setRoomData(null);
    setRoomId("");
  };
  const abandonGame = () => { send({ action: "abandon" }); setConfirmAbandon(false); };

  const handClick = (card) => {
    if (iAmActor) return;                       // prompts own the clicks
    const t = cards[card]?.types || [];
    if (inAction && t.includes("action") && game.actions > 0) mv({ type: "play_action", card });
    else if (inBuy && t.includes("treasure") && !bought) mv({ type: "play_treasure", card });
  };
  const pileClick = (pile) => {
    if (iAmActor && constraint?.piles) {
      if (constraint.piles.includes(pile)) mv({ type: "decision", pile });
      return;
    }
    if (inBuy && game.buys > 0 && (game.supply[pile] || 0) > 0 && effCost(pile) <= game.coins) {
      mv({ type: "buy", card: pile });
    }
  };

  // ── render helpers ──
  const kindOfPrompt = iAmActor ? pv.kind : null;

  const renderPrompt = () => {
    if (!game || over) return null;
    if (waitingOn) {
      return (
        <div className="dm-waitbar">
          Waiting for <b>{names[waitingOn] || waitingOn}</b>
          {pv?.card && pv.card !== "__attack" ? <> — {pv.card}</> : null}
          {botActing ? <span className="dm-dots">…</span> : null}
        </div>
      );
    }
    if (!iAmActor) return null;
    const c = constraint;
    const promptCard = pv.card === "__attack" ? "Attack" : pv.card;
    if (kindOfPrompt === "choose_cards") {
      const need = pickIdx.length;
      const ok = need >= c.min && need <= c.max;
      const label = c.min === c.max ? `${c.purpose} ${c.min}` : c.min === 0 ? `${c.purpose} up to ${c.max}` : `${c.purpose} ${c.min}–${c.max}`;
      return (
        <div className="dm-prompt">
          <div className="dm-prompt-hd">{promptCard}: {label} {need ? `(${need} picked)` : ""}</div>
          <div className="dm-prompt-cards">
            {c.cards.map((n, i) => (
              <DmCardFace key={i} name={n} card={cards[n]} small
                selected={pickIdx.includes(i)}
                onClick={() => setPickIdx((s) => s.includes(i) ? s.filter((x) => x !== i) : (s.length < c.max ? [...s, i] : s))} />
            ))}
          </div>
          <div className="dm-prompt-actions">
            <button className="btn btn-gold" disabled={!ok}
              onClick={() => { mv({ type: "decision", cards: pickIdx.map((i) => c.cards[i]) }); }}>
              Confirm{c.purpose === "pass" ? " (kept secret)" : ""}
            </button>
            {c.min === 0 && <button className="btn btn-outline" onClick={() => mv({ type: "decision", cards: [] })}>None</button>}
          </div>
        </div>
      );
    }
    if (kindOfPrompt === "choose_option") {
      const pick = c.pick || 1;
      if (pick === 1) {
        return (
          <div className="dm-prompt">
            <div className="dm-prompt-hd">{promptCard}</div>
            <div className="dm-prompt-actions">
              {c.options.map((o) => (
                <button key={o.id} className="btn btn-gold" onClick={() => mv({ type: "decision", ids: [o.id] })}>{o.label}</button>
              ))}
            </div>
          </div>
        );
      }
      return (
        <div className="dm-prompt">
          <div className="dm-prompt-hd">{promptCard}: choose {pick} (different)</div>
          <div className="dm-prompt-actions">
            {c.options.map((o) => (
              <button key={o.id}
                className={"btn " + (pickOpts.includes(o.id) ? "btn-gold" : "btn-outline")}
                onClick={() => setPickOpts((s) => s.includes(o.id) ? s.filter((x) => x !== o.id) : (s.length < pick ? [...s, o.id] : s))}>
                {o.label}
              </button>
            ))}
            <button className="btn btn-gold" disabled={pickOpts.length !== pick}
              onClick={() => mv({ type: "decision", ids: pickOpts })}>Confirm</button>
          </div>
        </div>
      );
    }
    if (kindOfPrompt === "choose_pile") {
      return (
        <div className="dm-prompt">
          <div className="dm-prompt-hd">{promptCard}: pick a highlighted Supply pile</div>
        </div>
      );
    }
    if (kindOfPrompt === "order_cards") {
      const remaining = c.cards.map((n, i) => i).filter((i) => !orderIdx.includes(i));
      return (
        <div className="dm-prompt">
          <div className="dm-prompt-hd">{promptCard}: click cards in order (first = top of deck)</div>
          <div className="dm-prompt-cards">
            {c.cards.map((n, i) => (
              <DmCardFace key={i} name={n} card={cards[n]} small
                selected={orderIdx.includes(i)}
                badge={orderIdx.includes(i) ? orderIdx.indexOf(i) + 1 : null}
                onClick={() => setOrderIdx((s) => s.includes(i) ? s : [...s, i])} />
            ))}
          </div>
          <div className="dm-prompt-actions">
            <button className="btn btn-gold" disabled={remaining.length > 0}
              onClick={() => mv({ type: "decision", order: orderIdx.map((i) => c.cards[i]) })}>Confirm order</button>
            <button className="btn btn-outline" onClick={() => setOrderIdx([])}>Reset</button>
          </div>
        </div>
      );
    }
    if (kindOfPrompt === "place_in_deck") {
      return (
        <div className="dm-prompt">
          <div className="dm-prompt-hd">Secret Passage: where in your deck? ({c.card})</div>
          <div className="dm-prompt-actions dm-slots">
            {Array.from({ length: c.deck_len + 1 }, (_, p) => (
              <button key={p} className="btn btn-outline"
                onClick={() => mv({ type: "decision", position: p })}>
                {p === 0 ? "Top" : p === c.deck_len ? "Bottom" : p}
              </button>
            ))}
          </div>
        </div>
      );
    }
    if (kindOfPrompt === "name_card") {
      return (
        <div className="dm-prompt">
          <div className="dm-prompt-hd">{promptCard}: name a card</div>
          <div className="dm-prompt-actions dm-names">
            {c.cards.map((n) => (
              <button key={n} className="btn btn-outline" onClick={() => mv({ type: "decision", card: n })}>{n}</button>
            ))}
          </div>
        </div>
      );
    }
    return null;
  };

  const renderPile = (name) => {
    const cardData = cards[name];
    const count = game.supply[name] ?? 0;
    const promptPiles = iAmActor && constraint?.piles ? constraint.piles : null;
    const highlight = promptPiles ? promptPiles.includes(name)
      : (inBuy && game.buys > 0 && count > 0 && effCost(name) <= game.coins);
    const disabled = promptPiles ? !promptPiles.includes(name) : count === 0;
    return (
      <div key={name} className="dm-pile-slot">
        <DmCardFace name={name} card={cardData} small count={count}
          highlight={highlight} disabled={disabled && !highlight}
          onClick={() => pileClick(name)} />
        {bridges > 0 && cardData && effCost(name) !== cardData.cost
          && <span className="dm-disc">now {effCost(name)}</span>}
      </div>
    );
  };

  const renderSeatStrip = (pid) => {
    const s = seats[pid] || {};
    const isBot = (roomData?.ai_players || []).includes(pid);
    const acting = !over && (game.pending_pid || game.turn) === pid;
    return (
      <div key={pid} className={"dm-opp" + (acting ? " dm-opp-acting" : "")}>
        <div className="dm-opp-name">
          {names[pid] || pid}{isBot ? " 🤖" : ""}
          {acting && <TurnBadge mine={false}>{game.pending_pid === pid ? "deciding" : "their turn"}</TurnBadge>}
        </div>
        <div className="dm-opp-stats">
          <span title="cards in hand">✋ {s.hand_count ?? "?"}</span>
          <span title="cards in deck">🂠 {s.deck_count ?? "?"}</span>
          <span title="victory points">🛡 {game.vp?.[pid] ?? 0}</span>
          <span title="turns taken">⏱ {s.turns_taken ?? 0}</span>
        </div>
        <div className="dm-opp-discard">
          discard: {s.discard_view?.top
            ? <b title={cards[s.discard_view.top]?.text}>{s.discard_view.top}</b> : "—"} ({s.discard_view?.count ?? 0})
        </div>
      </div>
    );
  };

  const renderGameOver = () => {
    if (!over || gameOverDismissed) return null;
    const scores = game.scores || {};
    const ranked = [...seatOrder].sort((a, b) => (scores[b]?.vp ?? 0) - (scores[a]?.vp ?? 0));
    const winners = game.winners || [];
    return (
      <div className="dm-backdrop">
        <div className="dm-modal">
          <h2>{winners.includes(myId) ? "Victory!" : "Game over"}</h2>
          <p className="dm-winline">
            {winners.length > 1 ? "Shared victory: " : "Winner: "}
            {winners.map((w) => names[w] || w).join(" & ")}
          </p>
          <table className="dm-scores">
            <thead><tr><th></th><th>VP</th><th>Turns</th></tr></thead>
            <tbody>
              {ranked.map((p) => (
                <tr key={p} className={winners.includes(p) ? "dm-win" : ""}>
                  <td>{names[p] || p}{p === myId ? " (you)" : ""}</td>
                  <td>{scores[p]?.vp ?? "?"}</td>
                  <td>{scores[p]?.turns ?? "?"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="dm-prompt-actions">
            <button className="btn btn-gold" onClick={leaveToLobby}>Back to lobby</button>
            <button className="btn btn-outline" onClick={() => setGameOverDismissed(true)}>View board</button>
          </div>
        </div>
      </div>
    );
  };

  const renderRules = () => (
    <CreateModal title="How to play" onClose={() => setShowRules(false)}>
      <div className="dm-rules">
        <p>Build the best deck. Each turn: play one Action (A), then buy a card (B), then everything you played and held is discarded and you draw 5 (C).</p>
        <p><b>Action phase</b> — play Action cards from your hand (you start with 1 Action; cards can grant more).</p>
        <p><b>Buy phase</b> — play Treasures for coins, then buy cards from the Supply into your discard pile. No Treasures after you buy.</p>
        <p>The game ends when the Province pile — or any three piles — empty. Most victory points in your whole deck wins.</p>
        <p>Attack cards hit the other players; a Moat (revealed from hand) blocks an attack against you.</p>
      </div>
    </CreateModal>
  );

  // ─── screens ───────────────────────────────────────────────────────────────
  if (screen === "lobby") {
    return (
      <div className="app dm" style={{ "--lby-accent": "#b08d57" }}>
        <style>{dmStyles}</style>
        <LobbyHeader onBack={onExit} title="Dontminion" onRules={() => setShowRules(true)} user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : "Guest"} />
        <LobbyCreateRow onCreate={() => setShowCreateModal(true)} onJoin={joinGame}
          onRefresh={fetchGames} refreshing={loadingGames} />
        {showCreateModal && (
          <CreateModal title="New Game" onClose={() => setShowCreateModal(false)}>
            <CmRow label="Opponent">
              <CmSeg options={[{ value: "ai", label: "vs AI" }, { value: "friend", label: "vs Friends" }]}
                value={createOpp} onChange={setCreateOpp} />
            </CmRow>
            {createOpp === "ai" ? (
              <>
                <CmRow label="Bots">
                  <CmSeg options={[1, 2, 3].map((n) => ({ value: n, label: String(n) }))}
                    value={createBots} onChange={setCreateBots} />
                </CmRow>
                <CmRow label="Difficulty">
                  <CmSeg options={BOT_TIERS.map((t) => ({ value: t.id, label: t.name, title: t.desc }))}
                    value={createDiff} onChange={setCreateDiff} />
                </CmRow>
              </>
            ) : (
              <CmRow label="Players">
                <CmSeg options={[2, 3, 4].map((n) => ({ value: n, label: String(n) }))}
                  value={createPlayers} onChange={setCreatePlayers} />
              </CmRow>
            )}
            <CmRow label="Expansions">
              <div className="dm-checks">
                {EXPANSIONS.map((ex) => {
                  const on = createExps.includes(ex.id);
                  return (
                    <button key={ex.id} type="button"
                      className={"dm-check" + (on ? " dm-check-on" : "")}
                      onClick={() => setCreateExps((s) => on
                        ? (s.length > 1 ? s.filter((x) => x !== ex.id) : s)   // at least one stays on
                        : [...s, ex.id])}>
                      {on ? "☑" : "☐"} {ex.name}
                    </button>
                  );
                })}
              </div>
            </CmRow>
            <div className="cm-hint">10 kingdom piles are dealt at random from the enabled expansions.</div>
            <div className="cm-footer">
              <span className="cm-summary">
                {createOpp === "ai" ? `You + ${createBots} bot${createBots > 1 ? "s" : ""} (${createDiff})` : `Up to ${createPlayers} players`}
                {" · "}{createExps.map((e) => EXPANSIONS.find((x) => x.id === e)?.name).join(" + ")}
              </span>
              <button className="btn btn-gold cm-create" onClick={createGame}>Create</button>
            </div>
          </CreateModal>
        )}
        {showRules && renderRules()}
        <div className="dm-lobby-cols">
          <div>
            <LobbySectionHd title="Open Games" note="join a table" />
            {openGames.length === 0 && <div className="lby-empty">No open games — create one!</div>}
            {openGames.map((g) => (
              <div key={g.id} className="lby-card">
                <div className="lby-card-info">
                  <div className="lby-card-title">{g.host_name || "?"}'s table</div>
                  <div className="lby-card-meta">
                    {g.player_count}/{g.max_players} players · {(g.expansions || []).join(" + ")} · {timeAgo(g.created_at)}
                  </div>
                </div>
                <div className="lby-card-actions">
                  {g.host_id === myId
                    ? <>
                        <button className="btn btn-gold" onClick={() => resumeGame(g.id)}>Return</button>
                        <button className="btn btn-outline" onClick={() => cancelGame(g.id)}>Cancel</button>
                      </>
                    : <button className="btn btn-gold" onClick={() => joinGame(g.id)}>Join</button>}
                </div>
              </div>
            ))}
          </div>
          <div>
            <LobbySectionHd title="My Games" note={authUser?.session_token ? "in progress" : "sign in to track games"} />
            {myGames.map((g) => (
              <div key={g.id} className="lby-card">
                <div className="lby-card-info">
                  <div className="lby-card-title">vs {(g.opponents || []).join(", ") || "…"}</div>
                  <div className="lby-card-meta">
                    {g.your_turn ? <TurnBadge mine>your turn</TurnBadge> : g.status}
                    {" · "}{timeAgo(g.updated_at)}
                  </div>
                </div>
                <div className="lby-card-actions">
                  <button className="btn btn-gold" onClick={() => resumeGame(g.id)}>Resume</button>
                </div>
              </div>
            ))}
            {myGames.length === 0 && <div className="lby-empty">Nothing in progress.</div>}
          </div>
          <div>
            <LobbySectionHd title="History" note="finished games" />
            {history.map((g) => (
              <div key={g.id} className="lby-card">
                <div className="lby-card-info">
                  <div className="lby-card-title">
                    <span className={"hist-result " + (g.you_won ? "won" : "lost")}>{g.you_won ? "Won" : "Lost"}</span>
                    {" "}vs {(g.opponents || []).join(", ")}
                  </div>
                  <div className="lby-card-meta">
                    {g.your_vp != null ? `${g.your_vp} VP` : ""} · {timeAgo(g.updated_at)}
                  </div>
                </div>
              </div>
            ))}
            {history.length === 0 && <div className="lby-empty">No finished games yet.</div>}
          </div>
        </div>
        {toast && <div className="dm-toast">{toast}</div>}
      </div>
    );
  }

  if (screen === "waiting") {
    const count = Object.keys(names).length;
    const cap = roomData?.max_players || 4;
    const isHost = roomData?.host === myId;
    return (
      <div className="app dm" style={{ "--lby-accent": "#b08d57" }}>
        <style>{dmStyles}</style>
        <LobbyHeader onBack={leaveToLobby} backLabel="← Leave" title="Dontminion" user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : "Guest"} />
        <div className="dm-wait">
          <h2>Room {roomId}</h2>
          <p className="dm-wait-note">Share this code — friends join with it from the lobby.</p>
          <p className="dm-wait-note">{(roomData?.expansions || []).map((e) => EXPANSIONS.find((x) => x.id === e)?.name || e).join(" + ")}</p>
          <div className="dm-wait-players">
            Players ({count}/{cap})
            <ul>
              {Object.entries(names).map(([p, n]) => (
                <li key={p}>{n}{p === roomData?.host ? " ♛" : ""}{p === myId ? " (you)" : ""}</li>
              ))}
            </ul>
          </div>
          {isHost
            ? <button className="btn btn-gold btn-full" disabled={count < 2}
                onClick={() => send({ action: "start" })}>
                {count < 2 ? "Waiting for players…" : `Deal & Start (${count} players)`}
              </button>
            : <div className="lby-loading"><span className="lby-spinner" /> Waiting for the host to start…</div>}
        </div>
        {toast && <div className="dm-toast">{toast}</div>}
      </div>
    );
  }

  if (!game) {
    return (
      <div className="app dm" style={{ "--lby-accent": "#b08d57" }}>
        <style>{dmStyles}</style>
        <div className="lby-loading dm-center"><span className="lby-spinner" /> Loading game…</div>
      </div>
    );
  }

  // ── game screen ──
  return (
    <div className="app dm dm-gamescreen" style={{ "--lby-accent": "#b08d57" }}>
      <style>{dmStyles}</style>
      <div className="dm-top">
        <GameMenu items={[
          { label: "Back to lobby", onClick: leaveToLobby },
          !over && { label: "Abandon game", onClick: () => setConfirmAbandon(true), danger: true },
          { label: "Rules", onClick: () => setShowRules(true) },
        ].filter(Boolean)} label="Menu" />
        <div className="dm-hud">
          <span className={"dm-phase" + (myTurn ? " dm-phase-mine" : "")}>
            {over ? "game over" : myTurn ? (game.pending_pid ? "your decision" : `your ${game.phase} phase`) : `${names[game.turn] || game.turn}'s turn`}
          </span>
          <span title="Actions">A {game.actions}</span>
          <span title="Buys">B {game.buys}</span>
          <span title="Coins">$ {game.coins}</span>
          {bridges > 0 && <span title="Bridge discount">−{bridges} cost</span>}
          <span title="Your victory points">🛡 {game.vp?.[myId] ?? 0}</span>
        </div>
        {reconnecting && !connected && <span className="dm-reconn">reconnecting…</span>}
      </div>

      <div className="dm-main">
        <div className="dm-side">
          {oppOrder.map(renderSeatStrip)}
          <div className="dm-trash" onClick={() => setShowTrash((s) => !s)}>
            Trash ({(game.trash || []).length}) {showTrash ? "▾" : "▸"}
            {showTrash && (
              <div className="dm-trash-list">
                {(game.trash || []).length ? game.trash.join(", ") : "empty"}
              </div>
            )}
          </div>
          <div className="dm-log">
            {(game.log || []).slice(-60).map((e) => {
              const line = fmtLog(e, names);
              return line ? <div key={e.n} className="dm-log-line">{line}</div> : null;
            })}
          </div>
        </div>

        <div className="dm-center-col">
          {renderPrompt()}
          <div className="dm-supply">
            <div className="dm-supply-row dm-basics">{BASIC_ROW.map(renderPile)}</div>
            <div className="dm-supply-row dm-kingdom">{kingdomPiles.map(renderPile)}</div>
          </div>
          <div className="dm-me">
            <div className="dm-inplay">
              {(mySeat?.in_play || []).map((c, i) => (
                <DmCardFace key={i} name={c} card={cards[c]} small />
              ))}
              {(mySeat?.in_play || []).length === 0 && <span className="dm-zone-hint">in play</span>}
            </div>
            <div className="dm-handrow">
              <div className="dm-mystats">
                <span title="deck">🂠 {mySeat?.deck_count ?? 0}</span>
                <span title="discard">{mySeat?.discard_view?.top || "—"} ({mySeat?.discard_view?.count ?? 0})</span>
              </div>
              <div className="dm-hand">
                {(mySeat?.hand || []).map((c, i) => {
                  const t = cards[c]?.types || [];
                  const playable = !iAmActor && ((inAction && t.includes("action") && game.actions > 0)
                    || (inBuy && t.includes("treasure") && !bought));
                  return <DmCardFace key={i} name={c} card={cards[c]}
                    highlight={playable} disabled={!playable && !over}
                    onClick={playable ? () => handClick(c) : undefined} />;
                })}
                {(mySeat?.hand || []).length === 0 && <span className="dm-zone-hint">hand empty</span>}
              </div>
              <div className="dm-turnbtns">
                {inBuy && handTreasures && !bought && (
                  <button className="btn btn-gold" onClick={() => mv({ type: "play_all_treasures" })}>Play all treasures</button>
                )}
                {(inAction || inBuy) && (
                  <button className="btn btn-outline" onClick={() => mv({ type: "end_phase" })}>
                    {inAction ? "To buy phase →" : "End turn"}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {confirmAbandon && (
        <div className="dm-backdrop" onClick={() => setConfirmAbandon(false)}>
          <div className="dm-modal" onClick={(e) => e.stopPropagation()}>
            <h2>Abandon this game?</h2>
            <p>The other players win.</p>
            <div className="dm-prompt-actions">
              <button className="btn btn-danger" onClick={abandonGame}>Abandon</button>
              <button className="btn btn-outline" onClick={() => setConfirmAbandon(false)}>Keep playing</button>
            </div>
          </div>
        </div>
      )}
      {showRules && renderRules()}
      {renderGameOver()}
      {toast && <div className="dm-toast">{toast}</div>}
    </div>
  );
}
