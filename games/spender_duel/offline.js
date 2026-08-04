/* Offline vs-AI game driver for Spender Duel — the client-side stand-in for
 * main.py's room server + client-AI decision loop.
 *
 * The browser is authoritative: the saved game is the SAVE ENVELOPE (full-fidelity
 * State incl. ordered bag/decks, blind-reserve identities and the `revealed` undo gate
 * — duel-core/src/dump.rs), and every step is a stateless JSON→JSON call into the
 * engine compiled into duel_core_bg.wasm. Search input is the REDACTED projection
 * (`proj` kind, seat-scoped), so the AI cannot read the deck order or the human's
 * blind reserves the client physically holds — the same strength profile as online.
 *
 * What main.py does that this mirrors:
 *  - per-decision bot loop: while the bot is the actor, fetch legal moves; a single
 *    legal move applies directly (no search); otherwise arm `ai_search`
 *    {decision seq, proj, 3500ms, 20k sims} and let the component's existing pool
 *    effect search it and sink the picked ENCMOVE back here. Paced ~1s between
 *    forced applies so the bot doesn't teleport.
 *  - move validation: every applied move (human engine-dict or AI encmove) goes
 *    through the wasm apply, which validates by legal_moves membership.
 *  - the move log: Duel's log strictly APPENDS (the JSX reverses for display); the
 *    wasm apply returns the exact records engine.py would have written (t/pid/type,
 *    parity-gated), so the driver just appends them.
 *  - undo_turn: a whole-envelope snapshot re-armed at each turn START (keyed on
 *    turn_number — an AGAIN extra turn is its own undoable turn, like Python's
 *    _snapshot_turn), REFUSED once the save's `revealed` flag is set (hidden
 *    information came up this turn — the blind-reserve/replenish exploit gate,
 *    exactly the online rule).
 *
 * The engine runs in its own lazy module worker (same duel-worker.js the search pool
 * uses; the driver instance only ever issues engine calls).
 */

import { dbPut, dbGet, dbDelete, requestPersistentStorage } from "../../shared/offline-db.js";

export const DUEL_OFFLINE_AI_PID = "bot";
const LOG_CAP = 2000;
const BOT_PAUSE_MS = 900;

const newLocalId = () =>
  "LOCAL" + Array.from({ length: 6 }, () => "ABCDEFGHJKMNPQRSTUVWXYZ23456789"[Math.floor(Math.random() * 31)]).join("");

// ─── The lazy engine worker ────────────────────────────────────────────────
let _engine = null;

function makeEngineWorker() {
  const url = `${import.meta.env.BASE_URL}wasm/duel-worker.js`;
  const w = new Worker(url, { type: "module" });
  const pending = new Map();
  let nextId = 1, readyRes;
  const ready = new Promise((r) => (readyRes = r));
  w.onmessage = (e) => {
    const d = e.data || {};
    if (d.ready !== undefined) { readyRes(!!d.ready); return; }
    const p = pending.get(d.id);
    if (p) { pending.delete(d.id); p(d); }
  };
  w.onerror = () => readyRes(false);
  return {
    async request(payload) {
      if (!(await ready)) throw new Error("the game engine failed to load — go online once to download it");
      const id = nextId++;
      const res = await new Promise((r) => { pending.set(id, r); w.postMessage({ ...payload, id }); });
      if (res.error) throw new Error(res.error);
      return res;
    },
  };
}

function engine(payload) {
  if (!_engine) _engine = makeEngineWorker();
  return _engine.request(payload);
}

// ─── Record helpers ────────────────────────────────────────────────────────

const aiSeatOf = (rec) => 1 - rec.mySeat;
export const duelPids = (rec, myId) =>
  rec.mySeat === 0 ? [myId, DUEL_OFFLINE_AI_PID] : [DUEL_OFFLINE_AI_PID, myId];

// The save envelope is plain JSON — actor/phase/turn_number/revealed are readable
// without a worker round-trip.
const envOf = (rec) => JSON.parse(rec.dump);
const actorOf = (env) => (env.phase !== 0 ? -1 : env.pending_pid >= 0 ? env.pending_pid : env.turn);

async function save(rec) {
  rec.updated = Date.now();
  await dbPut(rec);
  return rec;
}

// ─── Public driver API ─────────────────────────────────────────────────────

export async function createOfflineDuelGame({ tier }) {
  const seed = (Math.random() * 0x100000000) >>> 0;
  const mySeat = Math.random() < 0.5 ? 0 : 1;
  const { save: env } = await engine({ kind: "newGame", seed });
  const rec = {
    id: newLocalId(),
    game: "duel",
    dump: env,
    mySeat,
    tier,                        // "hard" | "expert"
    seed,
    moves: [],                   // appended engine-log records (JSX reverses for display)
    status: "playing",
    undo: null,
    decisionSeq: 0,
    created: Date.now(),
    updated: Date.now(),
  };
  armUndoIfMyTurn(rec);
  await save(rec);
  requestPersistentStorage();
  return rec;
}

export const loadOfflineDuelGame = (id) => dbGet(id);
export const deleteOfflineDuelGame = (id) => dbDelete(id);

/* Synthesized roomData — the offline analog of Duel's per-recipient broadcast_state.
 * The view is the HUMAN's `player_view` (the AI's view exists only inside the redacted
 * projection the search gets). The component's pool effect keys on vs_ai +
 * ai_difficulty; its search loop keys on ai_search.decision — armed by the bot loop. */
export async function duelOfflineRoomData(rec, myId, myName) {
  const pids = duelPids(rec, myId);
  const names = pids.map((p) => (p === DUEL_OFFLINE_AI_PID ? "Bot" : myName || "You"));
  const { view } = await engine({
    kind: "playerView", save: rec.dump,
    pid0: pids[0], pid1: pids[1], name0: names[0], name1: names[1], viewer: rec.mySeat,
  });
  const game = { ...JSON.parse(view), log: rec.moves };
  return {
    room_id: rec.id,
    players: { [myId]: myName || "You", [DUEL_OFFLINE_AI_PID]: "Bot" },
    host: myId,
    status: rec.status,
    vs_ai: true,
    ai_player: DUEL_OFFLINE_AI_PID,
    ai_difficulty: rec.tier,
    max_players: 2,
    offline: true,
    game,
  };
}

/* Re-arm the turn-start snapshot whenever a NEW turn begins with the human as actor
 * (turn_number keys it: Python's _snapshot_turn re-arms per finish_turn, so an AGAIN
 * extra turn is its own undoable turn). Mutates rec; caller persists. */
function armUndoIfMyTurn(rec) {
  const env = envOf(rec);
  if (env.phase !== 0) { rec.undo = null; return; }
  if (actorOf(env) !== rec.mySeat) return;
  if (rec.undo && rec.undo.tn === env.turn_number) return;   // same turn — keep turn start
  rec.undo = { dump: rec.dump, moves: [...rec.moves], decisionSeq: rec.decisionSeq, tn: env.turn_number };
}

/* Apply one move (engine-style {"type":...} dict from the JSX, or the search loop's
 * {"t":...} encmove). Returns {ok, rec} / {ok:false, err}. Handles undo_turn + log. */
export async function applyOfflineDuelMove(rec, move, myId, { isAi = false } = {}) {
  if (rec.status === "over") return { ok: false, err: "game is over" };

  if (move?.type === "undo_turn") {
    if (!rec.undo) return { ok: false, err: "nothing to undo" };
    // The online gate, verbatim: once hidden information surfaced this turn (a card
    // flipped face up, tokens drawn from the bag), the turn cannot be unseen.
    if (envOf(rec).revealed) return { ok: false, err: "can't undo after a card or token was revealed" };
    rec.dump = rec.undo.dump;
    rec.moves = rec.undo.moves;
    rec.decisionSeq = rec.undo.decisionSeq ?? rec.decisionSeq;
    // undo stays armed — repeated undos idempotently restore the turn start
    return { ok: true, rec: await save(rec) };
  }

  const pids = duelPids(rec, myId);
  const seat = isAi ? aiSeatOf(rec) : rec.mySeat;
  const res = await engine({
    kind: "apply", save: rec.dump, move: JSON.stringify(move), seat,
    pid0: pids[0], pid1: pids[1], shuffleSeed: (Math.random() * 0x100000000) >>> 0,
  });
  rec.dump = res.save;
  // Events come back oldest→newest with t/pid already stamped (parity-gated against
  // engine.py's own log) — append, cap from the FRONT (oldest evicted).
  rec.moves = [...rec.moves, ...(res.events || [])].slice(-LOG_CAP);

  if (envOf(rec).phase !== 0) {
    rec.status = "over";
    rec.undo = null;
  } else {
    armUndoIfMyTurn(rec);
  }
  return { ok: true, rec: await save(rec) };
}

/* Arm the human's undo snapshot on (re)entry — resume lands mid-turn where the
 * apply-path arming never ran (e.g. the app was killed right after the bot moved). */
export async function armDuelUndoIfMyTurn(rec) {
  const before = rec.undo?.tn;
  armUndoIfMyTurn(rec);
  if (rec.undo?.tn !== before) await save(rec);
  return rec;
}

/* The per-decision bot loop — the offline analog of the server arming `ai_search` on
 * each bot decision. Forced (single-legal) moves apply directly with a pacing pause;
 * a real decision arms ai_search and returns (the component's pool effect searches it
 * and sinks the picked encmove back through `applyOfflineDuelMove`, then calls this
 * again). `publish(rec, aiSearch|null)` re-renders; `isCurrent()` cancels the loop
 * when the screen/game changes mid-pause. */
export async function runDuelBotLoop(rec, myId, publish, isCurrent) {
  for (let step = 0; step < 60; step++) {
    if (!isCurrent() || rec.status === "over") return;
    const aiSeat = aiSeatOf(rec);
    if (actorOf(envOf(rec)) !== aiSeat) return;   // human's turn (or over) — loop done
    const { legal } = await engine({ kind: "legal", save: rec.dump });
    const { actor, moves } = JSON.parse(legal);
    if (actor !== aiSeat || !moves.length) return;
    if (moves.length === 1) {
      await new Promise((r) => setTimeout(r, BOT_PAUSE_MS));
      if (!isCurrent()) return;
      const res = await applyOfflineDuelMove(rec, moves[0], myId, { isAi: true });
      if (!res.ok) { console.debug("[duel offline-AI] forced apply failed:", res.err); return; }
      rec = res.rec;
      await publish(rec, null);
      continue;
    }
    // Real decision → arm the search (the component's existing pool effect takes over).
    rec.decisionSeq += 1;
    await save(rec);
    const { proj } = await engine({ kind: "proj", save: rec.dump, seat: aiSeat });
    await publish(rec, {
      decision: rec.decisionSeq,
      seat: aiSeat,
      budget_ms: 3500,
      max_sims: 20000,
      state: JSON.parse(proj),
    });
    return;
  }
}
