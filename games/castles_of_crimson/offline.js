/* Offline vs-AI game driver for Castles of Crimson — the client-side stand-in for
 * main.py's room server + `_client_bot_turn` loop.
 *
 * The browser is authoritative: the saved game is the SAVE ENVELOPE (full-fidelity
 * State incl. ordered pools + rng, plus the tile-id ledger — coc-core/src/gamedict.rs),
 * and every step is a stateless JSON→JSON call into the engine compiled into
 * coc_core_bg.wasm. Search input is the REDACTED projection (`proj` kind), so the AI
 * cannot read the hidden pools or the dice rng the client physically holds — the same
 * strength profile as online.
 *
 * What main.py does that this mirrors:
 *  - the per-decision bot loop (`_client_bot_turn`): while the bot acts, fetch legal
 *    ENGINE moves; a single legal move applies directly (no search); otherwise arm
 *    `ai_search` {decision seq, proj, netval, 1500ms, 20k sims} and wait for the
 *    component's existing search loop to sink the move back here. Paced ~1s between
 *    applies so the bot doesn't teleport.
 *  - move validation: every applied move (human or AI) runs through the wasm apply,
 *    which converts + validates against legal_actions_full — never applied raw.
 *  - the move log: the record keeps a newest-first `moves` list (cap 2000) built from
 *    the wasm's per-apply event records, stamped with the turn counter.
 *  - undo_turn: a whole-envelope snapshot at the start of each HUMAN turn, restored on
 *    `{"type":"undo_turn"}` (the engine-side turn_undo is server bookkeeping; offline
 *    the snapshot is driver-side, the Spender-offline pattern).
 *
 * The engine runs in its own lazy module worker (`?engine=1` — no model fetch, so
 * engine calls work offline even when no model bin is cached; search pool workers
 * load their model as always).
 */

import { dbPut, dbGet, dbDelete, requestPersistentStorage } from "../../shared/offline-db.js";

export const COC_OFFLINE_AI_PID = "bot";
const LOG_CAP = 2000;
const BOT_PAUSE_MS = 900;

export const COC_BOARD_NAMES = {
  "1": "Starter", "2": "Big City", "3": "Ring of Knowledge", "4": "Twin Cities",
  "5": "One Two Three", "6": "Big River", "7": "Central City", "8": "Outer Cities",
  "9": "Two Cities",
};

const newLocalId = () =>
  "LOCAL" + Array.from({ length: 6 }, () => "ABCDEFGHJKMNPQRSTUVWXYZ23456789"[Math.floor(Math.random() * 31)]).join("");

// ─── The lazy engine worker (model-free) ───────────────────────────────────
let _engine = null;

function makeEngineWorker() {
  const url = `${import.meta.env.BASE_URL}wasm/coc-worker.js?engine=1`;
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
export const cocPids = (rec, myId) =>
  rec.mySeat === 0 ? [myId, COC_OFFLINE_AI_PID] : [COC_OFFLINE_AI_PID, myId];

async function save(rec) {
  rec.updated = Date.now();
  await dbPut(rec);
  return rec;
}

// ─── Public driver API ─────────────────────────────────────────────────────

export async function createOfflineCocGame({ myBoard, oppBoard, tier }) {
  const seed = (Math.random() * 0x100000000) >>> 0;
  const mySeat = Math.random() < 0.5 ? 0 : 1;
  const b = (id) => Math.max(0, Math.min(8, (parseInt(id, 10) || 1) - 1));
  const boards = mySeat === 0 ? [b(myBoard), b(oppBoard)] : [b(oppBoard), b(myBoard)];
  const { save: env } = await engine({ kind: "newGame", board0: boards[0], board1: boards[1], seed });
  const rec = {
    id: newLocalId(),
    game: "coc",
    dump: env,
    mySeat,
    tier,                        // "hard" | "expert"
    seed,
    moves: [],
    status: "playing",
    undo: null,
    decisionSeq: 0,
    turnNumber: 0,
    created: Date.now(),
    updated: Date.now(),
  };
  await save(rec);
  requestPersistentStorage();
  return rec;
}

export const loadOfflineCocGame = (id) => dbGet(id);
export const deleteOfflineCocGame = (id) => dbDelete(id);

async function currentActor(rec) {
  const { legal } = await engine({ kind: "legal", save: rec.dump });
  return JSON.parse(legal);
}

/* Synthesized roomData — the offline analog of CoC's mk_room_state. The component's
 * pool-creation effect keys on vs_ai + ai_difficulty; its search loop keys on
 * ai_search.decision. `ai_search` is armed by the BOT LOOP (below), not here. */
export async function cocOfflineRoomData(rec, myId, myName) {
  const pids = cocPids(rec, myId);
  const names = pids.map((p) => (p === COC_OFFLINE_AI_PID ? "Bot" : myName || "You"));
  const { dict } = await engine({
    kind: "gameDict", save: rec.dump, pid0: pids[0], pid1: pids[1], name0: names[0], name1: names[1],
  });
  const parsed = JSON.parse(dict);
  const game = { ...parsed.game, moves: rec.moves };
  return {
    room_id: rec.id,
    players: { [myId]: myName || "You", [COC_OFFLINE_AI_PID]: "Bot" },
    host: myId,
    status: rec.status,
    vs_ai: true,
    ai_player: COC_OFFLINE_AI_PID,
    ai_difficulty: rec.tier,
    max_players: 2,
    boards: {},
    same_board: false,
    final_scores: parsed.final_scores,
    vp_breakdown: {},            // replays the server log — unavailable offline
    offline: true,
    game,
  };
}

/* Apply one move (engine-style dict from the JSX, or a compact dict from the search
 * loop). Returns {ok, rec} / {ok:false, err}. Handles undo_turn and the log. */
export async function applyOfflineCocMove(rec, move, myId, { isAi = false } = {}) {
  if (rec.status === "over") return { ok: false, err: "game is over" };

  if (move?.type === "undo_turn") {
    if (!rec.undo) return { ok: false, err: "nothing to undo" };
    rec.dump = rec.undo.dump;
    rec.moves = rec.undo.moves;
    rec.decisionSeq = rec.undo.decisionSeq ?? rec.decisionSeq;
    // undo stays armed (Python re-snapshots immediately: multiple undos of the same
    // turn are idempotent restores of the turn-start position)
    return { ok: true, rec: await save(rec) };
  }

  const pids = cocPids(rec, myId);
  const seat = isAi ? aiSeatOf(rec) : rec.mySeat;
  const res = await engine({
    kind: "apply", save: rec.dump, move: JSON.stringify(move), seat,
    pid0: pids[0], pid1: pids[1],
  });
  rec.dump = res.save;

  // Prepend events newest-first with the turn stamp (t), engine-log style.
  const stamped = (res.events || []).map((e) => ({ t: rec.turnNumber, ...e }));
  rec.moves = [...stamped.reverse(), ...rec.moves].slice(0, LOG_CAP);
  if (move?.type === "end_turn" || move?.t === "end") rec.turnNumber += 1;

  const { actor } = await currentActor(rec);
  if (actor < 0) rec.status = "over";

  // Undo snapshot: armed at the START of the human's turn (the first moment they
  // become the actor), kept across their own mid-turn moves so undo always rewinds
  // to the turn start, and dropped once the turn passes on — Python only allows
  // undo on your own turn.
  if (rec.status !== "over" && actor === rec.mySeat) {
    const stillMyTurn = !isAi && rec.undo != null;
    if (!stillMyTurn) {
      rec.undo = { dump: rec.dump, moves: [...rec.moves], decisionSeq: rec.decisionSeq };
    }
  } else {
    rec.undo = null;
  }

  return { ok: true, rec: await save(rec) };
}

/* Arm the human's undo snapshot on (re)entry when it's already their turn — the
 * apply-path arming above only fires on transitions. */
export async function armCocUndoIfMyTurn(rec) {
  if (rec.status === "over" || rec.undo != null) return rec;
  const { actor } = await currentActor(rec);
  if (actor === rec.mySeat) {
    rec.undo = { dump: rec.dump, moves: [...rec.moves], decisionSeq: rec.decisionSeq };
    await save(rec);
  }
  return rec;
}

/* The per-decision bot loop — the offline `_client_bot_turn`. Drives the bot while it
 * is the actor: forced (single-legal) moves apply directly with a pacing pause;
 * otherwise arms ai_search and returns (the component's search loop sinks the chosen
 * compact move back through `applyOfflineCocMove` and calls this again).
 *
 * `publish(rec, aiSearch|null)` re-renders; `isCurrent()` lets the caller cancel the
 * loop when the screen/game changes mid-pause. */
export async function runCocBotLoop(rec, myId, publish, isCurrent) {
  const MODEL = { hard: "coc_pv_model_hard.bin", expert: "coc_pv_model.bin" };
  for (let step = 0; step < 60; step++) {
    if (!isCurrent() || rec.status === "over") return;
    const { actor, moves } = await currentActor(rec);
    if (actor !== aiSeatOf(rec)) return;      // human's turn (or over) — loop done
    if (!moves.length) return;
    if (moves.length === 1) {
      await new Promise((r) => setTimeout(r, BOT_PAUSE_MS));
      if (!isCurrent()) return;
      const res = await applyOfflineCocMove(rec, moves[0], myId, { isAi: true });
      if (!res.ok) { console.debug("[coc offline-AI] forced apply failed:", res.err); return; }
      rec = res.rec;
      await publish(rec, null);
      continue;
    }
    // Real decision → arm the search (the component's existing loop takes over).
    rec.decisionSeq += 1;
    await save(rec);
    const { proj } = await engine({ kind: "proj", save: rec.dump });
    await publish(rec, {
      decision: rec.decisionSeq,
      seat: aiSeatOf(rec),
      mode: "netval",
      model: MODEL[rec.tier] || MODEL.expert,
      budget_ms: 1500,
      max_sims: 20000,
      state: JSON.parse(proj),
    });
    return;
  }
}
