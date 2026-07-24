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
// Lifecycle: { ready:true } once the wasm loads, or { ready:false, error } if it won't
//   (the main thread drops this worker; if none are ready it never announces
//   client_ai_ready and the SERVER computes the bot's move — the pre-existing path).

import init, { duel_search, duel_search_expert, duel_pick_move } from "./duel_core.js";

let readyResolve;
const readyP = new Promise((res) => (readyResolve = res));

init()
  .then(() => { readyResolve(true); self.postMessage({ ready: true }); })
  .catch((err) => { readyResolve(false); self.postMessage({ ready: false, error: String(err) }); });

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
    }
  } catch (err) {
    self.postMessage({ id: msg.id, error: String(err) });
  }
};
