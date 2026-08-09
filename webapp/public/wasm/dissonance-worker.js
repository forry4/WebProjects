// Dissonance hard-tier search worker (WORLD-PARALLEL). Loaded as a MODULE worker;
// the wasm-pack (--target web) glue + .wasm sit beside this file. One of N
// identical workers — the main thread fans the SAME decision to each with an
// independent seed, every worker samples its OWN worlds, and their per-move
// value sums are added.
//
// WHY SUMMING WORKS. The search is PIMC: sample a deal consistent with what the
// seat knows, solve it exactly, and total the value of each root move. The
// arrays are indexed by `State::legal`, a pure function of the position, so
// index i means the same card in every worker and in the pick. Sums over
// DISJOINT world samples add, so the pooled totals are exactly what one worker
// with the combined world count would have computed.
//
// The pick is NOT reimplemented here: `odd_best_card` runs the core's own rule
// (highest total, ties to the earliest legal move), which is `PimcBot::pick`'s.
// A JS copy that drifted would be a different bot with the same name.
//
// EACH WORKER SPENDS ITS OWN BUDGET, one world at a time, and stops on whichever
// of `budget`/`maxWorlds` comes first. A world costs ~70ms at trick 1 and
// effectively nothing by trick 7 (measured), so a fixed count would either stall
// the opening or waste the endgame; the cap is what actually binds, because
// sampling saturates around 8 worlds per seat.
//
// Protocol (main -> worker):
//   { id, kind:"search", view, budget, maxWorlds, seed }
//     -> { id, moves:[...], sum:[...], worlds:n }
//   { id, kind:"pick", moves, sum } -> { id, card }
//   { id, kind:"review", req } -> { id, value } | { id, error }
//     One EXACT solve of a finished round's deal (`odd_review`) -- no seed and
//     no pooling, because a review has no uncertainty to sample: the round is
//     over and every card is known. Same answer every time, which is what lets
//     the modal label it as a fact about the round rather than a bot's opinion.
// Lifecycle: { ready:true } once the wasm loads, or { ready:false, error } if it
//   won't (the main thread drops this worker; with none ready it never announces
//   client_ai_ready and the SERVER plays the bot — the pre-existing path).

// NAMESPACE import, not named: a NEW worker beside an OLD cached glue must
// degrade per-feature, and a named import of a symbol the old module lacks is
// a SyntaxError that kills the whole worker -- classic rooms included.
import * as wasm from "./dissonance.js";

const { default: init, odd_pick_card, odd_best_card, odd_pick_bid, odd_review } = wasm;

// Does this artifact speak wire 2 (minor mode's `even_val`)? Probed off the
// EXPORT TABLE, because that is the one thing an old artifact cannot fake: a
// wasm without the field's reader would silently search a minor room under
// classic trick values -- legal moves, wrong game, nothing red anywhere. The
// probe turns that into the ordinary per-decision server-bot fallback.
const WIRE = typeof wasm.odd_wire === "function" ? 2 : 1;

// The parity a request needs: 2 unless it explicitly carries a minor value.
function neededEven(req) {
  const v = req && (req.view || req.deal || req);
  const e = v && (v.even_val ?? v.even);
  return typeof e === "number" ? e : 2;
}

let readyResolve;
const readyP = new Promise((res) => (readyResolve = res));

init()
  .then(() => { readyResolve(true); self.postMessage({ ready: true, wire: WIRE }); })
  .catch((err) => { readyResolve(false); self.postMessage({ ready: false, error: String(err) }); });

self.onmessage = async (e) => {
  const msg = e.data || {};
  if (!msg.kind) return;
  const ok = await readyP;
  if (!ok) { self.postMessage({ id: msg.id, error: "wasm not loaded" }); return; }
  try {
    // Refuse to search a parity this artifact does not read, in EVERY kind:
    // the error goes back to the main thread, which drops the answer and the
    // server bot plays that one decision -- the same path a timeout takes.
    if (WIRE < 2 && (msg.kind === "search" || msg.kind === "bid" || msg.kind === "review")) {
      let req = null;
      try { req = JSON.parse(String(msg.view ?? msg.req)); } catch { /* let the wasm report it */ }
      if (req && neededEven(req) !== 2) {
        self.postMessage({ id: msg.id, error: "artifact predates minor parity" });
        return;
      }
    }
    if (msg.kind === "search") {
      const view = String(msg.view);
      const budget = Number(msg.budget) || 2000;
      const cap = (msg.maxWorlds >>> 0) || 8;
      const t0 = Date.now();
      let sum = null, moves = null, worlds = 0, seed = Number(msg.seed) || 1;
      do {
        const r = JSON.parse(odd_pick_card(view, 1, seed++));
        if (r.error) { self.postMessage({ id: msg.id, error: r.error }); return; }
        if (!sum) { moves = r.moves; sum = r.sum.slice(); }
        else for (let i = 0; i < sum.length; i++) sum[i] += r.sum[i];
        // A forced move reports zero worlds and returns immediately — searching
        // it further cannot change the answer.
        if (r.worlds === 0) { worlds = 0; break; }
        worlds += r.worlds;
      } while (worlds < cap && Date.now() - t0 < budget);
      self.postMessage({ id: msg.id, moves, sum, worlds });
    } else if (msg.kind === "bid") {
      // An auction decision. One call per world budget rather than the card
      // search's chunked loop: a world here is five full solves, so the
      // granularity that keeps the endgame responsive would only add overhead.
      const cap = (msg.maxWorlds >>> 0) || 2;
      const r = JSON.parse(odd_pick_bid(String(msg.view), cap, Number(msg.seed) || 1));
      if (r.error) { self.postMessage({ id: msg.id, error: r.error }); return; }
      self.postMessage({ id: msg.id, sums: r.sums, worlds: r.worlds });
    } else if (msg.kind === "review") {
      const r = JSON.parse(odd_review(String(msg.req)));
      if (r.error) { self.postMessage({ id: msg.id, error: r.error }); return; }
      self.postMessage({ id: msg.id, value: r.value });
    } else if (msg.kind === "pick") {
      const card = odd_best_card(JSON.stringify({ moves: msg.moves, sum: msg.sum }));
      self.postMessage({ id: msg.id, card });
    }
  } catch (err) {
    self.postMessage({ id: msg.id, error: String(err) });
  }
};
