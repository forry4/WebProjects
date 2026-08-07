// Spender Duel hard-tier search worker (ROOT-PARALLEL). Loaded as a MODULE worker; the
// wasm-pack (--target web) glue + .wasm sit beside this file. One of N identical workers
// — the main thread fans an independently-seeded search of the SAME decision to each,
// SUMS their root statistics, and asks one worker to pick from the pooled totals.
//
// WHY THE POOL SUMS STATS AND DOESN'T VOTE ON MOVES: `visits` and `wins` are both indexed
// by the root move list, which is a pure function of the state (duel-core mcts::root_moves),
// so every worker's index i means the same move. Both are additive, so summing them and
// picking once is exactly what a single search of the combined sim count would do.
//
// The pick itself is NOT reimplemented here: `duel_pick_move` runs duel-core's own
// pick_greedy on the pooled arrays. Its (visits, then mean-value) tie-break is
// load-bearing — a JS copy that drifted would silently pick the first index, which in
// Duel means "always take tokens, never buy, game never ends".
//
// Protocol (main -> worker):
//   { id, kind:"search", state, budget, maxSims, seed } -> { id, visits:[...], wins:[...] }
//   { id, kind:"pick",   state, visits, wins }          -> { id, move }  (enc_move JSON string)
//   ── offline driver (engine calls on the SAVE envelope; JSON strings in/out) ──
//   { id, kind:"newGame",    seed }                                       -> { id, save }
//   { id, kind:"legal",      save }                                       -> { id, legal }  ({actor,moves} JSON)
//   { id, kind:"apply",      save, move, seat, pid0, pid1, shuffleSeed }  -> { id, save, events }
//   { id, kind:"playerView", save, pid0, pid1, name0, name1, viewer }     -> { id, view }   (player_view JSON)
//   { id, kind:"proj",       save, seat }                                 -> { id, proj }   (redacted ai_search.state)
// Lifecycle: { ready:true } once the wasm loads, or { ready:false, error } if it won't
//   (the main thread drops this worker; if none are ready it never announces
//   client_ai_ready and the SERVER computes the bot's move — the pre-existing path).

// Namespace import so a cached OLD glue (without the offline exports) still loads —
// newer entries are feature-detected at call time instead of breaking the import.
import init, * as duel from "./duel_core.js";
const { duel_search, duel_search_expert, duel_pick_move } = duel;

let readyResolve;
const readyP = new Promise((res) => (readyResolve = res));

init()
  .then(() => { readyResolve(true); self.postMessage({ ready: true }); })
  .catch((err) => { readyResolve(false); self.postMessage({ ready: false, error: String(err) }); });

// Engine-call results are `{"error":...}` JSON on bad input; surface those as
// protocol-level errors so the driver has ONE failure path.
const engineResult = (key, json) => {
  if (typeof json === "string" && json.startsWith('{"error"')) {
    return { error: JSON.parse(json).error };
  }
  return { [key]: json };
};
const need = (fn) => {
  if (typeof fn !== "function") throw new Error("stale wasm: no offline engine");
  return fn;
};

self.onmessage = async (e) => {
  const msg = e.data || {};
  if (!msg.kind) return;
  const ok = await readyP;
  if (!ok) { self.postMessage({ id: msg.id, error: "wasm not loaded" }); return; }
  try {
    if (msg.kind === "search") {
      const search = msg.expert ? duel_search_expert : duel_search;
      const r = JSON.parse(search(
        String(msg.state), Number(msg.budget), (msg.maxSims >>> 0) || 0, Number(msg.seed >>> 0)));
      if (r.error) { self.postMessage({ id: msg.id, error: r.error }); return; }
      self.postMessage({ id: msg.id, visits: r.visits, wins: r.wins });
    } else if (msg.kind === "pick") {
      const move = duel_pick_move(
        String(msg.state), JSON.stringify(msg.visits), JSON.stringify(msg.wins));
      self.postMessage({ id: msg.id, move });
    } else if (msg.kind === "newGame") {
      const save = need(duel.duel_new_game_json)(BigInt(msg.seed >>> 0));
      self.postMessage({ id: msg.id, ...engineResult("save", save) });
    } else if (msg.kind === "legal") {
      self.postMessage({ id: msg.id, ...engineResult("legal", need(duel.duel_legal_json)(String(msg.save))) });
    } else if (msg.kind === "apply") {
      const out = need(duel.duel_apply_json)(
        String(msg.save), String(msg.move), msg.seat >>> 0,
        String(msg.pid0), String(msg.pid1), BigInt(msg.shuffleSeed >>> 0));
      if (out.startsWith('{"error"')) {
        self.postMessage({ id: msg.id, error: JSON.parse(out).error });
      } else {
        const parsed = JSON.parse(out);
        self.postMessage({ id: msg.id, save: JSON.stringify(parsed.save), events: parsed.events });
      }
    } else if (msg.kind === "playerView") {
      self.postMessage({ id: msg.id, ...engineResult("view",
        need(duel.duel_player_view_json)(String(msg.save), String(msg.pid0), String(msg.pid1),
          String(msg.name0), String(msg.name1), msg.viewer | 0)) });
    } else if (msg.kind === "proj") {
      self.postMessage({ id: msg.id, ...engineResult("proj",
        need(duel.duel_offline_proj)(String(msg.save), msg.seat >>> 0)) });
    }
  } catch (err) {
    self.postMessage({ id: msg.id, error: String(err) });
  }
};
