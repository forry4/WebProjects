// Variant-S search worker (ROOT-PARALLEL) + the OFFLINE game driver's engine endpoint. Loaded as a
// MODULE worker; the wasm-pack (--target web) glue + .wasm sit beside this file. One of N identical
// workers — the main thread fans a seeded search to each, SUMS their root visit vectors, argmaxes, and
// asks one worker to convert the winner to a move. The offline driver additionally uses worker[0] for
// stateless engine calls (create/legal/apply/render) — sub-millisecond, no search.
//
// Protocol (main -> worker):
//   { id, kind:"search",  state, seat, budget, seed }  -> { id, visits:[70 ints] }  (variant S: v_state leaf)
//   { id, kind:"searchN", state, seat, budget, seed }  -> { id, visits:[70 ints] }  (variant N: learned leaf)
//   { id, kind:"searchPV",state, seat, budget, seed }  -> { id, visits:[70 ints] }  (variant PV: learned value+policy)
//   { id, kind:"refine",  state, seat, action, seed }  -> { id, move }   (endgame solver #1; dict-move JSON)
//   { id, kind:"convert", state, action }              -> { id, move }   (compact dict-move JSON)
//   ── offline driver (engine calls; every payload/return is a JSON STRING) ──
//   { id, kind:"newGame",    seed, winPoints }               -> { id, state }  (compact-state JSON)
//   { id, kind:"legalMoves", state }                         -> { id, moves }  ([{action,move}] JSON)
//   { id, kind:"apply",      state, action }                 -> { id, state }  (post-move compact JSON)
//   { id, kind:"gameDict",   state, pid0, pid1, viewer }     -> { id, game }   (render game-dict JSON)
// Lifecycle: { ready:true } once init succeeds, or { ready:false, error } if the wasm won't load
//   (the main thread then drops this worker; if none are ready it never announces client_ai_ready and
//   the server computes the move).
//
// NAMESPACE import + per-call feature detection, NOT named imports: the glue and this worker deploy
// together, but a browser can serve a CACHED old glue beside a new worker (same filenames, ~10-min
// Pages TTL) — a named import of a not-yet-exported fn would throw at module load and kill the whole
// worker, including the search kinds that old glue supports fine. Missing fn -> a per-call error the
// caller can surface ("update the app"), never a dead pool.

import init, * as core from "./spender_core.js";

let readyResolve;
const readyP = new Promise((res) => (readyResolve = res));

init()
  .then(() => { readyResolve(true); self.postMessage({ ready: true }); })
  .catch((err) => { readyResolve(false); self.postMessage({ ready: false, error: String(err) }); });

// Engine-call results are `{"error":...}` JSON on bad input; surface those as protocol-level
// errors so the driver has ONE failure path (worker error) instead of parsing every payload.
const engineResult = (key, json) => {
  if (typeof json === "string" && json.startsWith('{"error"')) {
    return { error: JSON.parse(json).error };
  }
  return { [key]: json };
};

self.onmessage = async (e) => {
  const msg = e.data || {};
  if (!msg.kind) return;
  const ok = await readyP;
  if (!ok) { self.postMessage({ id: msg.id, error: "wasm not loaded" }); return; }
  try {
    if (msg.kind === "search" || msg.kind === "searchN" || msg.kind === "searchPV") {
      const seed = BigInt(msg.seed >>> 0);
      const maxSims = (msg.maxSims >>> 0) || 0; // 0 = no cap
      const fn = msg.kind === "searchPV" ? core.search_visits_pv_timed  // PV = learned value+policy
               : msg.kind === "searchN" ? core.search_visits_n_timed    // N  = learned value leaf
               : core.search_visits_timed;                              // S  = v_state leaf
      const visits = fn(String(msg.state), msg.seat >>> 0, Number(msg.budget), maxSims, seed);
      self.postMessage({ id: msg.id, visits: Array.from(visits) });
    } else if (msg.kind === "refine") {
      const seed = BigInt(msg.seed >>> 0);
      const move = core.endgame_refine_move(String(msg.state), msg.seat >>> 0, msg.action >>> 0, seed);
      self.postMessage({ id: msg.id, move });
    } else if (msg.kind === "convert") {
      const move = core.action_to_move_for(String(msg.state), msg.action >>> 0);
      self.postMessage({ id: msg.id, move });
    } else if (msg.kind === "newGame") {
      if (typeof core.new_game_json !== "function") throw new Error("stale wasm: no offline engine");
      const state = core.new_game_json(BigInt(msg.seed >>> 0), msg.winPoints | 0);
      self.postMessage({ id: msg.id, state });
    } else if (msg.kind === "legalMoves") {
      if (typeof core.legal_moves_json !== "function") throw new Error("stale wasm: no offline engine");
      self.postMessage({ id: msg.id, ...engineResult("moves", core.legal_moves_json(String(msg.state))) });
    } else if (msg.kind === "apply") {
      if (typeof core.apply_action_json !== "function") throw new Error("stale wasm: no offline engine");
      self.postMessage({ id: msg.id, ...engineResult("state", core.apply_action_json(String(msg.state), msg.action >>> 0)) });
    } else if (msg.kind === "gameDict") {
      if (typeof core.game_dict_json !== "function") throw new Error("stale wasm: no offline engine");
      self.postMessage({ id: msg.id, ...engineResult("game",
        core.game_dict_json(String(msg.state), String(msg.pid0), String(msg.pid1), msg.viewer | 0)) });
    }
  } catch (err) {
    self.postMessage({ id: msg.id, error: String(err) });
  }
};
