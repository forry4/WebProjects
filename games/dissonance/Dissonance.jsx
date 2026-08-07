import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbySectionHd, LobbyEmpty, TurnBadge, LobbyLoading,
  LobbyTabs, GameMenu, gameMenuCss, readLobbyCache, writeLobbyCache,
  createModalCss, CreateModal, CmRow, CmSeg, LobbyCreateRow, lobbyCreateRowCss,
  RulesModal, rulesModalCss,
  useProgressiveList, notWaiting, LobbyAction, useLastDifficulty,
} from "../../shared/lobby.jsx";
import DissonanceRules from "./rules.jsx";
import { parsePath, buildPath, pushPath, subscribe } from "../../shared/router.js";

// CSS lives in the sibling .css file, imported ?inline as a STRING and injected
// by this component's own <style> while mounted. Never a JS template literal —
// one stray backtick there reparses the rest of the file and blanks the page.
import _cssText from "./Dissonance.css?inline";

const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const OT_WS = WS_RAW.replace(/\/ws$/, "/dissonance/ws");
const OT_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/dissonance");

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
// Null is a CONSOLATION, not a contract: take no +2 trick as declarer and you
// score this instead of being set, whatever you actually declared. There is no
// denomination and no level to render -- `NULL_DENOM` survives only so a game
// SAVED while Null was still biddable still reads back.
const NULL_DENOM = 5;
const NULL_MAKE = 12;

// How long a completed trick stays face up before it moves to the Last trick
// panel. Long enough to read two cards, short enough not to stall the bot,
// whose own floor is 450ms — so its next lead lands while this is still up and
// simply waits its turn.
const TRICK_HOLD_MS = 700;

const BOT_TIERS = [
  { id: "easy", name: "Easy", desc: "Plays legally, blunders often" },
  { id: "normal", name: "Normal", desc: "Knows which tricks it wants" },
  { id: "hard", name: "Hard", desc: "Solves the hand exactly, in your browser" },
];
const BOT_TIER_IDS = BOT_TIERS.map((t) => t.id);   // what a remembered tier is validated against

// The Hard tier's card play is searched HERE, on the player's CPU. It is an
// exact double-dummy solve per sampled deal — ~70ms for one deal at trick 1 —
// which is unthinkable on Render's free tier and unremarkable on a laptop.
// Every failure path (no Worker, no wasm, a search error, a slow phone) is a
// no-op that leaves the server's heuristic bot to play the move.
const CLIENT_AI_TIERS = ["hard"];
//: A flat floor per move, so the bot's pace does not advertise how fast the
//  player's machine is — and so it never lands inside the completed-trick beat.
const CLIENT_AI_MIN_MS = 600;

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

// There is deliberately no `dim` prop: every face-up card renders identically,
// playable or not. See the note in the stylesheet.
function Card({ c, onClick, sel, small, ghost }) {
  if (ghost) return <div className={`dis-card ghost${small ? " sm" : ""}`}>?</div>;
  if (c === null || c === undefined) return <div className="dis-card back" />;
  const cls = `dis-card ${isRed(c) ? "red" : "black"}${onClick ? " play" : ""}`
    + `${sel ? " sel" : ""}${small ? " sm" : ""}`;
  return (
    <div className={cls} onClick={onClick} title={cardName(c)}>
      {/* The index sits in the TOP-RIGHT corner, which is what lets a pile
          reveal its buried card by offsetting it up and to the right — the
          corner alone identifies the card, so the hint labels underneath the
          piles ("1 hidden", "over 7♥") are no longer needed. */}
      <span className="dis-ix">
        <span className="dis-r">{RANKS[rankOf(c)]}</span>
        <span className="dis-s">{SUIT_GLYPH[suitOf(c)]}</span>
      </span>
    </div>
  );
}

function Pile({ pile, onPlay }) {
  if (!pile || pile.n === 0) {
    return (
      <div className="dis-pile">
        <div className="dis-pilewrap"><div className="dis-card ghost">–</div></div>
      </div>
    );
  }
  const twoLeft = pile.n === 2;
  const under = pile.under;
  const knownUnder = under !== null && under !== undefined;
  return (
    <div className="dis-pile">
      <div className="dis-pilewrap">
        {/* The buried card, offset up and right so its top-right index clears
            the card covering it. That IS the label: a face shows which card is
            coming (the middle pile, dealt face up), a back shows only that
            something is there — which is exactly what the outer piles hide,
            from their owner too. A one-card pile has nothing behind it. */}
        {twoLeft && (
          <div className="dis-buried" title={knownUnder ? cardName(under) : "face down"}>
            <Card c={knownUnder ? under : null} />
          </div>
        )}
        <Card c={pile.top} onClick={onPlay} />
      </div>
    </div>
  );
}

/** The contract, in the MIDDLE column so it survives a phone.
 *  The side panel already carries the full breakdown, but `.dis-side` is
 *  display:none under 760px — so on a phone the one thing the whole round is
 *  about was invisible from the moment the auction ended. */
function ContractChip({ game, nameOf, sharpBonus }) {
  const a = game.auction || {};
  if (!a.level) return null;
  const ct = game.contract || {};
  const red = a.denom === 1 || a.denom === 2;
  const doubling = ct.re ? 4 : ct.kontra ? 2 : 1;
  const parts = multParts(ct);
  return (
    <div className="dis-chip">
      <span className={`dis-chip-den${red ? " red" : ""}`}>
        {a.level}{DENOM_LABEL[a.denom]}
      </span>
      <span className="dis-chip-who">
        {nameOf(a.declarer)} must score{" "}
        {a.level + (ct.sharp ? sharpBonus : 0)}
      </span>
      {(parts.length > 0 || doubling > 1) && (
        <span className="dis-chip-mult">
          {parts.join(" + ")}{parts.length && doubling > 1 ? " · " : ""}
          {doubling > 1 ? (ct.re ? "Kontra + Re" : "Kontra") : ""}
          {ct.value ? ` · ${ct.value * (ct.mult || 1) * doubling}` : ""}
        </span>
      )}
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
      <div className="dis-maths">
        {ct.value}{ct.mult > 1 ? ` × ${ct.mult}` : ""}{doubling > 1 ? ` × ${doubling}` : ""}
        {" = "}<b>{stake}</b>{why ? ` — ${why}` : ""}
      </div>
    );
  }
  return (
    <>
      <div className="dis-scorerow"><span>At stake</span><b>{stake}</b></div>
      {why && <div className="muted" style={{ fontSize: "0.72rem" }}>{why}</div>}
      <div className="muted" style={{ fontSize: "0.72rem" }}>
        Made, it goes to {nameOf(game.auction.declarer)}; missed, to{" "}
        {nameOf(1 - game.auction.declarer)} plus 4 a point short.
      </div>
    </>
  );
}

/** What `value` would COMMIT you to in each denomination — the lowest level
 *  whose base x level reaches it, which is the number of trick points you would
 *  then have to score.
 *
 *  Every denomination, not only the ones that hit the number exactly. The
 *  decision at the ladder is "if I win here, what am I promising?", and for four
 *  of the five that answer is a level whose value OVERSHOOTS the bid — showing
 *  only the exact hits answered it for one denomination and left the rest blank.
 *  It also makes the cheap end legible: a bid of 2 requires level 1 in
 *  everything, i.e. it commits you to nothing at all. */
function levelsFor(value, bases, maxLevel) {
  if (!value || !bases?.length || !maxLevel) return [];
  return bases
    .map((base, denom) => ({ denom, level: Math.max(1, Math.ceil(value / base)) }))
    .filter((x) => x.level <= maxLevel);
}

/** What a number commits its winner to, per denomination. Rendered for the
 *  STANDING bid as well as your own selection: while the opponent holds it, the
 *  question you are answering is what THEIR number would cost you to take over,
 *  and that was only ever shown for a value you had already picked. */
function NeedsRow({ value, prefix, bases, maxLevel }) {
  if (!value || !bases?.length) return null;
  return (
    <div className="dis-clears">
      <span className="muted">{prefix}</span>
      {levelsFor(value, bases, maxLevel).map((x) => (
        <span key={x.denom} className={`dis-clear${x.denom === 1 || x.denom === 2 ? " red" : ""}`}>
          {x.level}{DENOM_LABEL[x.denom]}
        </span>
      ))}
    </div>
  );
}

/** Which auction a room runs. Classic is the default, so only skat is marked. */
function ModeBadge({ mode }) {
  if (mode !== "skat") return null;
  return <span className="dis-modebadge">{MODE_LABEL.skat}</span>;
}

function ContractLine({ game }) {
  const a = game.auction || {};
  // Skat mode: until the declaration lands, all there is to show is the number.
  if (game.mode === "skat" && !a.level) {
    return a.value
      ? <span className="dis-contract"><b>{a.value}</b></span>
      : <span className="muted">no bid yet</span>;
  }
  if (!a.level) return <span className="muted">no contract yet</span>;
  const red = a.denom === 1 || a.denom === 2;
  return (
    <span className="dis-contract">
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

export default function Dissonance({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");     // lobby | waiting | game
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [openGames, setOpenGames] = useState(() => readLobbyCache("dissonance", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("dissonance", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("dissonance", myId, "history", []));
  const [historyShown, historyMore] = useProgressiveList(history);
  // A room still waiting for an opponent belongs in Open, not in progress.
  const activeMine = notWaiting(myGames);
  const [lobbyTab, setLobbyTab] = useState("open");
  const [loadingGames, setLoadingGames] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [toast, setToast] = useState("");
  const [showRules, setShowRules] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  const [bidLevel, setBidLevel] = useState(null);
  const [bidDenom, setBidDenom] = useState(null);
  const [newMode, setNewMode] = useState("classic");
  // Create-modal selections. Deferred until "Create Game" rather than firing on
  // the option click — the shape every other game's modal uses.
  const [createOpp, setCreateOpp] = useState("ai");
  // Difficulty defaults to the tier this player last actually played, Normal
  // until they have one.
  const [createDiff, setCreateDiff, rememberDiff] =
    useLastDifficulty("dissonance", myId, BOT_TIER_IDS, "normal");
  // Skat mode's half-built moves: the number, then the declaration.
  const [bidValue, setBidValue] = useState(null);
  const [declDenom, setDeclDenom] = useState(null);
  const [declLevel, setDeclLevel] = useState(null);
  const [declSharp, setDeclSharp] = useState(false);
  const [declOpen, setDeclOpen] = useState(false);

  // Client-side search: the worker pool, whether it came up, and the two
  // idempotence keys (armed once per room+socket, dispatched once per decision).
  const wasmPoolRef = useRef(null);
  const [wasmReady, setWasmReady] = useState(false);
  const clientAiArmedRef = useRef(null);
  const aiDispatchRef = useRef(null);
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
  // Did the declarer actually SEE the talon? Classic always shows it to them;
  // skat only if they looked, and declining to look is what Hand means. The
  // round-end reveal must not say "was shown" about a Hand game.
  const sawTalon = !isSkat || !!game?.looked;

  const onMessage = useCallback((msg) => {
    if (msg.type === "error") { setToast(msg.message || "error"); setConnecting(false); return; }
    if (msg.room) {
      setRoomData(msg.room);
      setConnecting(false);
      const tok = msg.room.reconnect_tokens?.[myId];
      if (tok) { try { localStorage.setItem(`dissonance_token_${msg.room.room_id}_${myId}`, tok); } catch {} }
      if (msg.room.room_id) {
        setRoomId(msg.room.room_id);
        pushPath(buildPath("dissonance", msg.room.room_id));
      }
      setScreen(msg.room.game ? "game" : "waiting");
    }
  }, [myId]);

  const { connected, connect, send, disconnect, socketReady } = useSocket(onMessage);

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${OT_HTTP}/games`).then((r) => r.json())
      .then((d) => { const g = d.games || []; setOpenGames(g); writeLobbyCache("dissonance", myId, "open", g); })
      .catch(() => {}).finally(() => setLoadingGames(false));
    if (authUser?.session_token) {
      const headers = { Authorization: `Bearer ${authUser.session_token}` };
      fetch(`${OT_HTTP}/games/mine`, { headers }).then((r) => r.json())
        .then((d) => { const g = d.games || []; setMyGames(g); writeLobbyCache("dissonance", myId, "mine", g); }).catch(() => {});
      fetch(`${OT_HTTP}/games/history`, { headers }).then((r) => r.json())
        .then((d) => { const g = d.games || []; setHistory(g); writeLobbyCache("dissonance", myId, "history", g); }).catch(() => {});
    } else {
      setMyGames([]); setHistory([]);
      writeLobbyCache("dissonance", myId, "mine", []); writeLobbyCache("dissonance", myId, "history", []);
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

  // ── client-side (WASM) bot search ──────────────────────────────────────────
  // World-parallel: every worker searches the SAME decision from its own seed,
  // sampling its own deals, and returns per-move value SUMS. We add them by move
  // index — the index space is `State::legal`, a pure function of the position,
  // so index i is the same card everywhere — and hand the totals back to the
  // wasm to pick. The pick rule is NOT reimplemented here (see the worker).
  useEffect(() => {
    if (!roomData?.vs_ai || !CLIENT_AI_TIERS.includes(roomData?.ai_difficulty)
      || wasmPoolRef.current || typeof Worker === "undefined") return;
    const url = `${import.meta.env.BASE_URL}wasm/dissonance-worker.js`;
    // NEVER TAKE EVERY CORE. The solver is CPU-bound and a pool that pegs all of
    // them starves the browser's main/compositor/raster threads, so the board
    // stutters while the bot thinks. Only bites at <=4 cores; the cap dominates
    // above that. Two other games shipped without this rule for months.
    const cores = Math.max(1, Math.min((navigator.hardwareConcurrency || 4) - 1, 4));
    const makeWorker = () => {
      let w;
      try { w = new Worker(url, { type: "module" }); } catch { return null; }
      const pending = new Map();
      let resolveReady, nextId = 1;
      const ready = new Promise((res) => (resolveReady = res));
      w.onmessage = (e) => {
        const d = e.data || {};
        if (d.ready !== undefined) { resolveReady(!!d.ready); return; }
        if (d.id != null && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
      };
      w.onerror = () => resolveReady(false);
      return {
        ready,
        request(payload) {
          const id = nextId++;
          return new Promise((res) => { pending.set(id, res); w.postMessage({ ...payload, id }); });
        },
        terminate() { try { w.terminate(); } catch {} },
      };
    };
    const pool = Array.from({ length: cores }, makeWorker).filter(Boolean);
    wasmPoolRef.current = pool;
    Promise.all(pool.map((wk) => wk.ready)).then((flags) => {
      const live = pool.filter((_, i) => flags[i]);
      if (live.length > 0) {
        wasmPoolRef.current = live;
        setWasmReady(true);
      } else {
        console.warn("[dissonance client-AI] no WASM workers loaded -> server bot");
      }
    });
    return () => { pool.forEach((wk) => wk.terminate()); wasmPoolRef.current = null; setWasmReady(false); };
  }, [roomData?.vs_ai, roomData?.ai_difficulty]);

  // The server disarms the client when its socket drops, so a reconnect MUST
  // re-announce or the room quietly serves the server bot for the rest of it.
  useEffect(() => { if (!connected) clientAiArmedRef.current = null; }, [connected]);
  useEffect(() => {
    if (wasmReady && connected && roomData?.room_id
      && clientAiArmedRef.current !== roomData.room_id) {
      clientAiArmedRef.current = roomData.room_id;
      send({ action: "client_ai_ready" });
    }
  }, [wasmReady, connected, roomData?.room_id, send]);

  // One armed decision at a time; the server re-ships it on every broadcast, so
  // this must be idempotent. Keyed by ROOM as well as decision number: the
  // counter restarts at 1 in a new room, so a bare number could collide with the
  // last one we answered and silently skip the bot's first card.
  useEffect(() => {
    const as = roomData?.ai_search;
    const pool = wasmPoolRef.current;
    if (!as || !wasmReady || !pool || pool.length === 0) return;
    const key = `${roomData.room_id}:${as.decision}`;
    if (aiDispatchRef.current === key) return;
    aiDispatchRef.current = key;
    // The seat's view AND the scoring rule it is playing for. The search
    // optimises the payoff the server will actually apply, not the trick points
    // that only measure it — which is what lets it duck for the Null
    // consolation, and lets a defender play to force one +2 trick on a declarer
    // who is ducking. The terms come straight from `engine.payoff_terms`.
    const view = JSON.stringify({ view: as.view, payoff: as.payoff });
    const t0 = performance.now();
    // The server's cap counts WORLDS in total, and worlds are summed across the
    // pool, so split it rather than handing every worker the whole budget.
    const perWorker = Math.max(1, Math.ceil((as.max_worlds || 8) / pool.length));
    (async () => {
      try {
        const parts = await Promise.all(pool.map((wk, i) => wk.request({
          kind: "search", view, budget: as.budget_ms, maxWorlds: perWorker,
          seed: ((as.decision * 2654435761) ^ (i * 40503 + 1)) >>> 0,
        }).catch(() => null)));
        const good = parts.filter((p) => p && p.moves && p.sum);
        if (!good.length) return;              // every worker failed -> server bot
        const k = good[0].moves.length;
        const sum = new Array(k).fill(0);
        let worlds = 0;
        for (const p of good) {
          // Same view in => same legal list, so a length mismatch means a stale
          // worker. Pooling it would add up DIFFERENT cards' values.
          if (p.sum.length !== k || p.moves.length !== k) continue;
          for (let a = 0; a < k; a++) sum[a] += p.sum[a];
          worlds += p.worlds;
        }
        const res = await pool[0].request({ kind: "pick", moves: good[0].moves, sum });
        const card = res?.card;
        if (typeof card !== "number" || card < 0) return;
        // Every failure above is a silent return that hands the decision back to
        // the server, so the ONE thing that says the client tier is actually
        // running is this line.
        console.info(`[dissonance client-AI] ${good.length} workers, ${worlds} worlds `
          + `in ${Math.round(performance.now() - t0)}ms -> card ${card}`);
        // A flat floor per move: a fast machine waits, a slow one does not, so
        // the bot's pace never leaks the device. A submit that lands after the
        // decision was superseded is harmless — the server drops it as stale.
        const wait = CLIENT_AI_MIN_MS - (performance.now() - t0);
        if (wait > 0) await new Promise((r) => setTimeout(r, wait));
        send({ action: "ai_move", decision: as.decision, card, worlds });
      } catch {}
    })();
  }, [roomData, wasmReady, send]);
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2600); return () => clearTimeout(t); } }, [toast]);
  // A fresh contract clears any half-built bid. In skat mode the standing bid
  // is `value`, not `level` — `level` stays 0 until the declaration.
  useEffect(() => {
    setBidLevel(null); setBidDenom(null); setBidValue(null);
  }, [game?.auction?.level, game?.auction?.value, game?.auction?.to_act,
      game?.redeals]);
  // The completed trick stays on the table for a beat. The server clears `led`
  // the instant the second card lands, so without this the trick you just lost
  // (or won) vanishes mid-blink and the only record is the side panel — you
  // never actually SEE the two cards together.
  //
  // `over` is in here with `play` ON PURPOSE: the thirteenth trick and the +2
  // that breaks a Null both END the game in the same message that completes the
  // trick, so a hold that stops at `play` skips the one trick a player most
  // wants to see and swaps straight to the result panel. Measured: every other
  // trick held 655–700ms and the last one held 0.
  const [heldTrick, setHeldTrick] = useState(null);
  const holdTimer = useRef(null);
  const wasPlaying = useRef(false);
  useEffect(() => {
    const playing = game?.phase === "play";
    // Only a game that ENDED under us gets the over-hold. Opening a finished
    // room from the lobby would otherwise replay its last trick at you before
    // showing the result, and a forfeit has no trick to hold at all.
    const ending = game?.phase === "over" && wasPlaying.current;
    wasPlaying.current = playing;
    if (!playing && !ending) { setHeldTrick(null); return; }
    const done = lastTrick(game);
    if (!done) { setHeldTrick(null); return; }
    setHeldTrick(done);
    holdTimer.current = setTimeout(() => setHeldTrick(null), TRICK_HOLD_MS);
    return () => clearTimeout(holdTimer.current);
  }, [game?.trick, game?.phase]);
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
    if (vsAi) rememberDiff(difficulty);   // this game's tier is the next modal's default
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
    try { tok = localStorage.getItem(`dissonance_token_${rid}_${myId}`); } catch {}
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
    pushPath(buildPath("dissonance", null));
  };

  // ── URL deep entry + back/forward (this component owns /dissonance/<ROOM>) ──
  useEffect(() => {
    if (didInitRef.current) return;
    didInitRef.current = true;
    const r = parsePath();
    if (r.game === "dissonance" && r.room) resumeGame(r.room);
  }, []); // eslint-disable-line
  popHandlerRef.current = (r) => {
    if (r.game !== "dissonance") return;
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
    try { tok = localStorage.getItem(`dissonance_token_${roomId}_${myId}`); } catch {}
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
      return <div className="dis"><style>{styles}</style><LobbyLoading label="Connecting…" /></div>;
    }
    const openCol = (
      <div className="lby-col-open">
        <LobbySectionHd title="Open games" note={openGames.length ? `${openGames.length} waiting` : null} />
        <div className="lby-list">
          {openGames.length === 0 && <LobbyEmpty>No open games. Create one!</LobbyEmpty>}
          {openGames.map((g) => (
            <div key={g.id} className="lby-card">
              <div className="lby-card-info">
                <div className="lby-card-title">
                  {g.host_name || "Player"}<ModeBadge mode={g.mode} />
                </div>
                <div className="lby-card-meta">{g.id} · {timeAgo(g.created_at)}</div>
              </div>
              <div className="lby-card-actions">
                {g.host_id === myId
                  ? <LobbyAction kind="danger" onClick={() => cancelGame(g.id)}>Cancel</LobbyAction>
                  : <LobbyAction onClick={() => joinGame(g.id)}>Join</LobbyAction>}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
    const activeCol = (
      <div className="lby-col-active">
        <LobbySectionHd title="Your games" />
        <div className="lby-list">
          {activeMine.length === 0 && <LobbyEmpty>Nothing in progress.</LobbyEmpty>}
          {activeMine.map((g) => (
            <div key={g.id} className="lby-card">
              <div className="lby-card-info">
                <div className="lby-card-title">
                  {(g.you_are_p1 ? g.player2_name : g.player1_name) || "Waiting…"}
                  <ModeBadge mode={g.mode} />
                  {g.your_turn && <TurnBadge mine>Your turn</TurnBadge>}
                </div>
                <div className="lby-card-meta">{g.id} · {timeAgo(g.updated_at)}</div>
              </div>
              <div className="lby-card-actions">
                <LobbyAction onClick={() => resumeGame(g.id)}>Resume</LobbyAction>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
    const histCol = (
      <div className="lby-col-history">
        <LobbySectionHd title="History" />
        <div className="lby-list" ref={historyMore}>
          {history.length === 0 && <LobbyEmpty>No finished games yet.</LobbyEmpty>}
          {historyShown.map((g) => (
            <div key={g.id} className="lby-card lby-card-hist">
              <div className="lby-card-info">
                <div className="lby-card-title">
                  <span className={`hist-result ${g.you_won ? "won" : "lost"}`}>
                    {g.you_won ? "Won" : "Lost"}
                  </span>
                  <span className="hist-scores"> vs {g.opp_name}{" "}
                    <span className="hist-score-num">{g.your_score}–{g.opp_score}</span>
                  </span>
                  <ModeBadge mode={g.mode} />
                </div>
                <div className="lby-card-meta">
                  {g.contract ? `${g.contract.you_declared ? "declared" : "defended"} `
                    + `${g.contract.level}${DENOM_LABEL[g.contract.denom] || ""}`
                    + (g.mode === "skat" && g.contract.value
                      ? ` for ${g.contract.value}${g.contract.mult > 1 ? `×${g.contract.mult}` : ""}` : "")
                    + `${g.contract.made ? " (made)" : " (set)"} · ` : ""}
                  {timeAgo(g.updated_at)}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
    return (
      <div className="dis">
        <style>{styles}</style>
        <LobbyHeader onBack={onExit} title="Dissonance" user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : null} />
        <LobbyCreateRow
          onCreate={() => setShowCreate(true)}
          onJoin={(code) => joinGame(code.toUpperCase())}
          onRefresh={fetchGames}
          onRules={() => setShowRules(true)}
          refreshing={loadingGames}
        />
        {/* `key`, not `id` — LobbyTabs reads `t.key`, and the grid's `tab-<key>`
            class is what the CSS hides the other columns off. With `id` the bar
            rendered but every click set the tab to undefined, and `data-tab`
            matched no rule, so the phone lobby showed all three sections at once
            and the bar did nothing at all. */}
        <LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[
          { key: "open", label: "Open", count: openGames.length || null },
          { key: "active", label: "Active", count: activeMine.length || null },
          { key: "history", label: "History", count: history.length || null },
        ]} />
        <div className={`lby-cols tab-${lobbyTab}`}>
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
              <span className="cm-hint">Dissonance is head-to-head — one friend joins from the lobby.</span>
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
      <div className="dis">
        <style>{styles}</style>
        <LobbyHeader title="Dissonance" menu={<OddMenu onLeave={leaveToLobby}
          onRules={() => setShowRules(true)} />}
          user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : null} />
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
  const ct = game.contract || {};
  const prev = lastTrick(game);
  const bidLevels = [...new Set(bids.map((b) => b[0]))].sort((a, b) => a - b);
  const denomOkAt = (l, d) => bids.some((b) => b[0] === l && b[1] === d);
  const bidReady = bidLevel !== null && bidDenom !== null && denomOkAt(bidLevel, bidDenom);
  const legal = new Set(game.legal || []);
  const res = game.result;
  // A round that stopped early banked the SCORE but not the final tally: the
  // contract was already safe, and the tricks nobody played would still have
  // moved the trick points. Printing the running total as if it were the final
  // one reads as a miscount, so say what is actually true — at least this many.
  const scored = (n) => (res?.ended_early ? `at least ${n}` : `${n}`);
  // THE BEAT BLOCKS PLAY, and that is what makes it a beat rather than a race.
  // The hold is 700ms and a trick takes ~600ms at full tilt, so a player who
  // answers before it expires was leading the NEXT trick behind a screen still
  // showing the last one: their card sat invisible, the opponent's reply landed
  // inside the same window, and the two finished tricks ran together with a
  // single 18ms frame between them (measured). Nothing is swallowed — a card
  // with no click handler also loses its `.play` affordance, so during the hold
  // the hand plainly is not offering itself.
  const canPlay = myTurn && !heldTrick;

  const trickCards = (() => {
    // A just-finished trick outranks the next lead: both cards stay up until
    // the hold expires, so the trick is always seen complete — including the
    // one that ends the game, which is why this is checked before the phase.
    if (heldTrick) {
      return heldTrick.plays.map((p) => ({ seat: p[0], c: p[1], won: p[0] === heldTrick.winner }));
    }
    if (game.phase !== "play") return [];
    if (game.led === null || game.led === undefined) return [];
    return [{ seat: game.leader, c: game.led }];
  })();

  return (
    <div className="dis">
      <style>{styles}</style>
      <LobbyHeader title="Dissonance" menu={<OddMenu onLeave={leaveToLobby}
        onRules={() => setShowRules(true)}
        onAbandon={game.phase !== "over" ? () => setConfirmAbandon(true) : null} />}
        user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : null} />
      {reconnecting && <div className="banner">Reconnecting…</div>}

      <div className="dis-main">
        <div className={`dis-table ph-${game.phase}`}>
          {/* opponent */}
          <div className="dis-seat">
            <div className="dis-seatname">
              <b>{nameOf(oppSeat)}</b>
              <span>{game.pts[oppSeat] >= 0 ? "+" : ""}{game.pts[oppSeat]} pts</span>
            </div>
            <div className="dis-hand">
              {/* Open: the declarer bought a multiplier by playing face up, so
                  their real cards are on the table from trick 1. */}
              {game.opp_hand
                ? game.opp_hand.map((c) => <Card key={c} c={c} />)
                : Array.from({ length: game.opp_hand_n }, (_, i) => <Card key={i} c={null} />)}
            </div>
            {game.opp_hand && (
              <div className="muted" style={{ fontSize: "0.72rem" }}>Open — played face up</div>
            )}
            <div className="dis-piles">
              {game.piles[oppSeat].map((p, i) => <Pile key={i} pile={p} />)}
            </div>
          </div>

          {/* middle */}
          {game.phase === "auction" && isSkat ? (
            <div className="dis-auction">
              <div className="muted">Auction · a number, not a game</div>
              <ContractLine game={game} />
              {game.auction.value > 0 && (<>
                <div className="muted">{nameOf(declSeat)} holds it at {game.auction.value}</div>
                <NeedsRow value={game.auction.value} bases={skatBases}
                  maxLevel={catalog?.max_level}
                  prefix={`${game.auction.value} would need`} />
              </>)}
              {game.redeals > 0 && (
                <div className="muted" style={{ fontSize: "0.78rem" }}>
                  Hand thrown in{game.redeals > 1 ? ` ${game.redeals} times` : ""} — redealt.
                </div>
              )}
              {myTurn ? (
                <>
                  <div className="dis-valgrid">
                    {(opt.values || []).map((v) => (
                      <button key={v} className={bidValue === v ? "on" : ""}
                        onClick={() => setBidValue(bidValue === v ? null : v)}>{v}</button>
                    ))}
                  </div>
                  {bidValue !== null && bidValue !== game.auction.value && (
                    <NeedsRow value={bidValue} bases={skatBases}
                      maxLevel={catalog?.max_level}
                      prefix={`yours would need`} />
                  )}
                  <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                    <button className="btn" disabled={bidValue === null} onClick={doValueBid}>
                      Bid {bidValue ?? ""}
                    </button>
                    <button className="btn btn-ghost" onClick={doPass}>Pass</button>
                  </div>
                  <div className="muted dis-hint">
                    {game.auction.value === 0
                      ? "Pass and your opponent takes the talon and the lead — at their own price. Both of you passing throws the hand in."
                      : "Push them one rung past their hand, or let them have it."}
                  </div>
                </>
              ) : <div className="muted">Waiting for {nameOf(game.auction.to_act)}…</div>}
              <div className="dis-bidlog">
                {(game.auction.log || []).map((e, i) => (
                  <div key={i}>
                    <span>{nameOf(e.seat)}</span>
                    <span>{e.pass ? "pass" : e.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : game.phase === "auction" ? (
            <div className="dis-auction">
              <div className="muted">Auction</div>
              <ContractLine game={game} />
              {game.auction.level > 0 && (
                <div className="muted">
                  {nameOf(game.auction.declarer)} to score at least {game.auction.level}
                </div>
              )}
              {myTurn ? (
                <>
                  <div className="dis-bidgrid">
                    {bidLevels.map((l) => (
                      <button key={l} className={bidLevel === l ? "on" : ""}
                        onClick={() => {
                          setBidLevel(l);
                          // Keep the denom only if it stays legal at this level.
                          if (bidDenom !== null && !denomOkAt(l, bidDenom)) setBidDenom(null);
                        }}>{l}</button>
                    ))}
                  </div>
                  <div className="dis-denoms">
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
                    {opt.may_pass && <button className="btn btn-ghost" onClick={doPass}>Pass</button>}
                  </div>
                  {!opt.may_pass && <div className="muted" style={{ fontSize: "0.8rem" }}>
                    The opener must bid.
                  </div>}
                </>
              ) : <div className="muted">Waiting for {nameOf(game.auction.to_act)}…</div>}
              <div className="dis-bidlog">
                {(game.auction.log || []).map((e, i) => (
                  <div key={i}>
                    <span>{nameOf(e.seat)}</span>
                    <span>{e.pass ? "pass" : `${e.level}${DENOM_LABEL[e.denom]}`}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : game.phase === "swap" ? (
            <div className="dis-auction">
              <div className="muted">The talon</div>
              <ContractLine game={game} />
              {game.swap ? (
                <>
                  <div className="muted" style={{ fontSize: "0.85rem" }}>
                    You won the auction. Three of the six talon cards — take
                    one into hand and discard, or stand pat.
                  </div>
                  <div className="dis-hand" style={{ justifyContent: "center" }}>
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
                  talon cards…
                </div>
              )}
            </div>
          ) : game.phase === "talon" ? (
            <div className="dis-auction">
              <div className="muted">The talon · {game.auction.value} to beat</div>
              <ContractLine game={game} />
              {game.talon ? (
                !game.talon.looked ? (
                  <>
                    <div className="muted dis-hint">
                      You bought the declaration at <b>{game.auction.value}</b>. Look at
                      three of the six talon cards and you may take one into
                      hand — or decline to look at all and play <b>Hand</b>, worth
                      +1 to your multiplier.
                    </div>
                    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                      <button className="btn" onClick={() => doMove({ kind: "look" })}>
                        Look at the talon
                      </button>
                      <button className="btn btn-ghost dis-annbtn"
                        onClick={() => doMove({ kind: "hand" })}>
                        Play Hand (×2)
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="muted dis-hint">
                      Take one into hand and discard, or stand pat. Either way you
                      have looked, so Hand is gone.
                    </div>
                    <div className="dis-hand" style={{ justifyContent: "center" }}>
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
            <div className="dis-auction">
              <div className="muted">Declare · your bid was {game.auction.value}</div>
              {game.declare ? (() => {
                const d = game.declare;
                const row = d.denoms.find((x) => x.denom === declDenom);
                const value = row ? row.base * (declLevel || 0) : 0;
                const mult = 1 + (d.hand ? 1 : 0) + (declSharp ? 1 : 0) + (declOpen ? 1 : 0);
                // The same conditions apply_declare enforces, so the button is
                // never live on a declaration the server will refuse.
                const ok = !!row && declLevel >= row.min_level
                  && declLevel <= d.max_level && (!declOpen || declSharp);
                return (
                  <>
                    <div className="dis-denoms">
                      {d.denoms.map((x) => (
                        <button key={x.denom}
                          className={`${declDenom === x.denom ? "on " : ""}${x.denom === 1 || x.denom === 2 ? "red" : ""}`}
                          title={`${DENOM_NAME[x.denom]} — base ${x.base}, so at least level ${x.min_level}`}
                          // Switching denomination resets the announcements: the
                          // level moves with it, and a stale Open without its
                          // Sharp is a combination the server refuses.
                          onClick={() => {
                            setDeclDenom(x.denom); setDeclLevel(x.min_level);
                            setDeclSharp(false); setDeclOpen(false);
                          }}>
                          {DENOM_LABEL[x.denom]}<small>×{x.base}</small>
                        </button>
                      ))}
                    </div>
                    {row && (
                      <>
                        <div className="muted" style={{ fontSize: "0.8rem" }}>
                          At least level {row.min_level} to reach {d.bid}. Higher is
                          voluntary — it pays more and promises more.
                        </div>
                        <div className="dis-bidgrid">
                          {Array.from({ length: d.max_level - row.min_level + 1 },
                            (_, i) => row.min_level + i).map((l) => (
                              <button key={l} className={declLevel === l ? "on" : ""}
                                title={`${row.base} × ${l} = ${row.base * l}`}
                                onClick={() => setDeclLevel(l)}>{l}</button>
                            ))}
                        </div>
                      </>
                    )}
                    <div className="dis-anns">
                      {d.hand && <span className="dis-ann on" title="You never looked at the talon">Hand</span>}
                      <button className={`dis-ann${declSharp ? " on" : ""}`}
                        title={`Promise ${d.sharp_bonus} more than your level`}
                        onClick={() => {
                          const next = !declSharp;
                          setDeclSharp(next);
                          if (!next) setDeclOpen(false);   // Open rides on Sharp
                        }}>Sharp +{d.sharp_bonus}</button>
                      <button className={`dis-ann${declOpen ? " on" : ""}`}
                        disabled={!declSharp}
                        title="Sharp, with your hand face up from trick 1"
                        onClick={() => setDeclOpen(!declOpen)}>Open</button>
                    </div>
                    <div className="dis-maths">
                      {`${row?.base} × ${declLevel} = ${value}`}
                      {mult > 1 ? ` × ${mult} (${multParts({ ...d, sharp: declSharp, open: declOpen }).join(" + ")})` : ""}
                      {" = "}<b>{value * mult}</b>
                      {` · you must score ${declLevel + (declSharp ? d.sharp_bonus : 0)}`}
                    </div>
                    <button className="btn" disabled={!ok}
                      onClick={() => doDeclare(declDenom, declLevel, declSharp, declOpen)}>
                      Declare
                    </button>
                  </>
                );
              })() : (
                <div className="muted">{nameOf(declSeat)} is naming the game…</div>
              )}
            </div>
          ) : game.phase === "kontra" || game.phase === "re" ? (
            <div className="dis-auction">
              <div className="muted">{game.phase === "re" ? "Re?" : "Kontra?"}</div>
              <ContractLine game={game} />
              <SkatStake game={game} nameOf={nameOf} />
              {myKontra ? (
                <>
                  <div className="muted dis-hint">
                    You know the game at last. <b>Kontra</b> doubles it whichever
                    way it falls.
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <button className="btn dis-kontrabtn"
                      onClick={() => doMove({ kind: "kontra", on: true })}>Kontra ×2</button>
                    <button className="btn btn-ghost"
                      onClick={() => doMove({ kind: "kontra", on: false })}>Let it stand</button>
                  </div>
                </>
              ) : myRe ? (
                <>
                  <div className="muted dis-hint">
                    {nameOf(1 - declSeat)} doubled you. <b>Re</b> doubles it again.
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <button className="btn dis-kontrabtn"
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
          ) : (game.phase === "over" && !heldTrick) ? (
            <div className="dis-result">
              <div className={`dis-big ${res.made ? "made" : "set"}`}>
                {res.abandoned_by !== null && res.abandoned_by !== undefined
                  ? "Game abandoned"
                  : res.denom === NULL_DENOM
                    ? (res.made ? "Null made" : "Null broken")
                    : res.null ? "Null!"
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
                    {" "}for the standing {res.level}{DENOM_LABEL[res.denom]} contract.
                  </> : "."}
                </div>
              ) : res.mode === "skat" ? <>
                <div className="muted">
                  {`${nameOf(res.declarer)} bought it at ${res.bid}, declared `}
                  {`${res.level}${DENOM_LABEL[res.denom]}`}
                  {multParts(res).length ? ` ${multParts(res).join(" + ")}` : ""}
                  {res.kontra ? (res.re ? " · Kontra + Re" : " · Kontra") : ""}
                  {` and scored ${scored(res.declarer_pts)} of the ${res.target} promised`}
                  {res.null ? ` — taking no scoring trick at all` : ""}
                </div>
                {/* THE WHOLE CHAIN, from the denomination's base price. Skat's
                    value is base × level and that first step used to be
                    invisible, so a made contract printed a bare number where
                    classic prints "3 × 3 = 9". */}
                <div className="dis-maths">
                  {res.null ? `flat ${res.null_value} to ${nameOf(res.declarer)}` : <>
                    {`${res.base} (${DENOM_LABEL[res.denom]}) × ${res.level} = ${res.value}`}
                    {res.mult > 1 ? ` × ${res.mult}` : ""}
                    {res.doubling > 1 ? ` × ${res.doubling}` : ""}
                    {res.mult > 1 || res.doubling > 1 ? ` = ${res.stake}` : ""}
                    {res.made
                      ? ` to ${nameOf(res.declarer)}`
                      : ` + 4 × ${res.short} = ${res.scores[1 - res.declarer]} to ${nameOf(1 - res.declarer)}`}
                  </>}
                </div>
              </> : <>
                <div className="muted">
                  {`${nameOf(res.declarer)} bid ${res.level}${DENOM_LABEL[res.denom]} and scored ${scored(res.declarer_pts)}`}
                  {res.null ? ` — taking no scoring trick at all` : ""}
                </div>
                <div className="dis-maths">
                  {res.null
                    ? `flat ${res.null_value} to ${nameOf(res.declarer)}`
                    : res.made
                      ? `${res.level} × ${res.level} = ${res.scores[res.declarer]} to ${nameOf(res.declarer)}`
                      : `${res.level - 1} + 4 × ${res.short} = ${res.scores[1 - res.declarer]} to ${nameOf(1 - res.declarer)}`}
                </div>
              </>}
              {res.null && (
                <div className="muted" style={{ fontSize: "0.8rem" }}>
                  Null: a declarer who wins no +2 trick all round scores it
                  instead of being set, whatever they declared.
                </div>
              )}
              <div className="dis-scorerow" style={{ gap: "1.5rem", fontSize: "1.1rem" }}>
                <span>{nameOf(mySeat)} <b>{res.scores[mySeat]}</b></span>
                <span>{nameOf(oppSeat)} <b>{res.scores[oppSeat]}</b></span>
              </div>
              {/* THE TALON — the six nobody was dealt, revealed. Every card you
                  could not account for all round was either in their hand or in
                  here, so this is the answer sheet — as cards, because a run of
                  text codes is not something you can read a hand off.

                  "The talon" is the whole six-card stock, and the line beneath
                  says which three of it the declarer was actually shown. Note
                  the swap means this is the talon as it ENDED: the card the
                  declarer took is in their hand, and their discard is here in
                  its place. */}
              {game.out && (
                <div className="dis-reveal">
                  <div className="muted">The talon</div>
                  <div className="dis-outrow">
                    {game.out.map((c) => <Card key={c} c={c} small />)}
                  </div>
                  {/* WHAT THE DECLARER ACTUALLY SAW AND DID — and no more than
                      that. This line used to read `shown` straight off the
                      state, which the engine rewrote on a swap, so it named the
                      discarded card as one they had been shown; and it said
                      "was shown" even for a Hand game, where the declarer never
                      looked at the talon at all. Both are the same mistake:
                      describing the talon from the final position instead of
                      from what happened. */}
                  {game.shown && (sawTalon ? (
                    <div className="muted" style={{ fontSize: "0.72rem" }}>
                      {nameOf(res.declarer)} was shown {game.shown.map(cardName).join(" ")}
                      {game.swap_take != null && game.swap_give != null
                        ? `, and swapped ${cardName(game.swap_take)} with ${cardName(game.swap_give)}`
                        : game.swapped
                          // A save written before the engine recorded which
                          // cards moved. Say that one did, not which.
                          ? ", and swapped one of them"
                          : ", and stood pat"}
                    </div>
                  ) : (
                    <div className="muted" style={{ fontSize: "0.72rem" }}>
                      {nameOf(res.declarer)} played a Hand — never looked at these
                    </div>
                  ))}
                </div>
              )}
              <button className="btn" onClick={leaveToLobby}>Back to lobby</button>
            </div>
          ) : (
            <>
              <div className="dis-trick">
                {trickCards.length === 0
                  ? <div className="muted">{myTurn ? "Your lead" : "Waiting…"}</div>
                  : trickCards.map((t, i) => (
                    <div key={i} className={`dis-tp${t.won ? " won" : ""}`}>
                      <Card c={t.c} />
                      <div className="muted" style={{ fontSize: "0.72rem" }}>{nameOf(t.seat)}</div>
                    </div>
                  ))}
                {/* While a finished trick is held, this line is ABOUT that
                    trick — the server's counter has already moved on, so
                    reading it here labelled the two cards you are looking at
                    with the next trick's number and the next trick's value. */}
                <div className="dis-trickinfo">
                  Trick {heldTrick ? heldTrick.number : game.trick + 1} of 13 ·{" "}
                  <span className={`dis-val ${(heldTrick ? heldTrick.value : game.trick_value) > 0 ? "good" : "bad"}`}>
                    {(heldTrick ? heldTrick.value : game.trick_value) > 0 ? "+2" : "−1"}
                  </span>
                </div>
              </div>
              <ContractChip game={game} nameOf={nameOf}
                sharpBonus={catalog?.sharp_bonus ?? 2} />
              <div className="dis-turnbar">
                {game.phase === "over" ? <span className="muted">Last trick</span>
                  : heldTrick ? <span className="muted">{nameOf(heldTrick.winner)} takes it</span>
                    : myTurn ? <span className="dis-yourturn">Your turn</span>
                      : <span className="muted">{nameOf(game.to_play)} is thinking…</span>}
              </div>
            </>
          )}

          {/* you */}
          <div className="dis-seat">
            <div className="dis-piles">
              {game.piles[mySeat].map((p, i) => (
                <Pile key={i} pile={p}
                  onPlay={canPlay && legal.has(p?.top) ? () => doPlay(p.top) : null} />
              ))}
            </div>
            <div className="dis-hand">
              {(game.hand || []).map((c) => (
                <Card key={c} c={c}
                  sel={(game.phase === "swap" || game.phase === "talon") && swapGive === c}
                  onClick={
                    (game.phase === "swap" ? game.swap : game.phase === "talon" ? game.talon : null)
                      && swapTake !== null
                      ? () => setSwapGive(swapGive === c ? null : c)
                      : canPlay && legal.has(c) ? () => doPlay(c) : null
                  } />
              ))}
            </div>
            <div className="dis-seatname">
              <b>{nameOf(mySeat)}</b>
              <span>{game.pts[mySeat] >= 0 ? "+" : ""}{game.pts[mySeat]} pts</span>
            </div>
          </div>
        </div>

        {/* side panel */}
        <div className="dis-side">
          <div className="dis-panel dis-p-contract">
            <h4>Contract</h4>
            {isSkat && <>
              <div className="dis-scorerow">
                <span>{declSeat >= 0 ? `${nameOf(declSeat)} bought it at` : "Standing bid"}</span>
                <b>{game.auction.value || "—"}</b>
              </div>
              {game.auction.level > 0 && <>
                <div className="dis-scorerow">
                  <span>Declared</span>
                  <b>{game.auction.level}{DENOM_LABEL[game.auction.denom]}</b>
                </div>
                <div className="dis-scorerow">
                  <span>Must score</span>
                  <b>{game.auction.level + (ct.sharp ? (catalog?.sharp_bonus ?? 2) : 0)}</b>
                </div>
                <SkatStake game={game} nameOf={nameOf} rows />
              </>}
            </>}
            {isSkat ? null : game.auction.level
              ? <>
                <div className="dis-scorerow">
                  <span>{nameOf(game.auction.declarer)} needs</span>
                  <b>{game.auction.level}</b>
                </div>
                <div className="dis-scorerow">
                  <span>Trump</span><b>{DENOM_NAME[game.auction.denom]}</b>
                </div>
                <div className="dis-scorerow">
                  <span>Makes it for</span><b>{game.auction.level * game.auction.level}</b>
                </div>
              </>
              : <div className="muted">Being decided…</div>}
            {/* Live under every contract, so it belongs on the panel rather than
                in the contract line: the declarer always has this out. */}
            {game.auction.level > 0 && (
              <div className="dis-scorerow">
                <span>Or Null (no +2 trick)</span>
                <b>{isSkat ? (catalog?.skat_null_value ?? "") : (catalog?.null_make ?? NULL_MAKE)}</b>
              </div>
            )}
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
            <div className="dis-panel dis-p-last">
              <h4>Last trick</h4>
              <div className="dis-lasttrick">
                {prev.plays.map((p, i) => (
                  <div key={i} className={`dis-lt-play${p[0] === prev.winner ? " won" : ""}`}>
                    <Card c={p[1]} small />
                    <div className="muted">{nameOf(p[0])}</div>
                  </div>
                ))}
                <div className="dis-lt-note">
                  <div>#{prev.number}</div>
                  <div className={`dis-val ${prev.value > 0 ? "good" : "bad"}`}>
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
              the moment the swap resolves threw that away.

              It shows WHAT YOU WERE SHOWN, which after a swap is no longer what
              is out — the card you took is in your hand and your discard is out
              in its place. That is the more useful of the two: you can see your
              own hand, and this is the only record of the third card you turned
              down. */}
          {game.shown && game.phase !== "over" && (
            <div className="dis-panel dis-p-talon">
              <h4>The talon · you saw these</h4>
              <div className="dis-outrow">
                {game.shown.map((c) => <Card key={c} c={c} small />)}
              </div>
              {game.swapped && (
                <div className="muted" style={{ fontSize: "0.7rem", marginTop: "0.3rem" }}>
                  One of these is now in your hand.
                </div>
              )}
            </div>
          )}
          <div className="dis-panel dis-p-points">
            <h4>Points</h4>
            <div className="dis-scorerow"><span>{nameOf(mySeat)}</span><b>{game.pts[mySeat]}</b></div>
            <div className="dis-scorerow"><span>{nameOf(oppSeat)}</span><b>{game.pts[oppSeat]}</b></div>
            <div className="muted" style={{ fontSize: "0.72rem", marginTop: "0.3rem" }}>
              Always adds up to +5.
            </div>
          </div>
        </div>
      </div>

      {showRules && <OddRulesModal onClose={() => setShowRules(false)} />}
      {confirmAbandon && (
        <CreateModal title="Abandon game?" onClose={() => setConfirmAbandon(false)}>
          <span className="cm-hint">
            You forfeit the round and your opponent is paid what the contract is
            currently worth. This cannot be undone.
          </span>
          <div className="cm-footer">
            <button type="button" className="btn btn-ghost"
              onClick={() => setConfirmAbandon(false)}>Keep playing</button>
            <button type="button" className="cm-create"
              onClick={() => { send({ action: "abandon" }); setConfirmAbandon(false); }}>
              Abandon
            </button>
          </div>
        </CreateModal>
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

/** The in-game ☰. Every game uses this shape rather than a row of buttons in
 *  the header — Dissonance was the last one still showing Back + Rules. */
function OddMenu({ onLeave, onRules, onAbandon }) {
  return (
    <GameMenu items={[
      { label: "Return to menu", icon: "\u2190", onClick: onLeave },
      { label: "View rules", icon: "\ud83d\udcd6", onClick: onRules },
      // Only for a live game you are still in.
      onAbandon && { label: "Abandon game", icon: "\u2691", danger: true, onClick: onAbandon },
    ]} />
  );
}

function OddRulesModal({ onClose }) {
  return (
    <RulesModal title="How to play — Dissonance" onClose={onClose}>
      <DissonanceRules />
    </RulesModal>
  );
}
