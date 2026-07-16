//! WASM serving entries — the bot's search, run in the player's browser.
//!
//! WHY: on Render's free tier (~0.1 CPU) the Python bot gets ~410 sims across ~76 root
//! moves at its 2.5s/decision budget — about 5 sims per move, barely above random. The
//! player's own CPU, running Rust, across several cores, is ~3 orders of magnitude more.
//! Same bot, same leaf, same rules: only the sim count changes.
//!
//! THE PROTOCOL, and the one property that makes it work. The server ships the bot's
//! compact projection (`compact.py::project`) per DECISION; every worker ingests that
//! same projection, runs an independently-seeded search, and returns the ROOT
//! STATISTICS — not a move. The main thread SUMS them and asks `duel_pick_move` for the
//! answer. Pooling is by root-move INDEX, which is sound because the index space
//! (`mcts::root_moves`) is a pure function of the state: same projection in, same list
//! out, in every worker and in the pick call. `n` and `w` are both additive, so the
//! pooled mean `sum(w)/sum(n)` is exactly what one search of the combined sim count
//! computes — and `pick_greedy`'s (visits, mean-value) rule then applies unchanged.
//!
//! The move comes back in `encmove`'s encoding, which is `gen_engine_fixtures.enc_move`
//! — the same shape the parity gates already prove, and which the server decodes and
//! re-validates against `engine.legal_moves` before applying. Nothing here is trusted.
//!
//! Only the "hard" tier is served this way. "normal" deliberately plays weak (temperature
//! sampling, small budget) and its strength is CALIBRATED against the other tiers, so
//! handing it 1000x the sims would silently break the measured ladder — a strength
//! change, which this is not.

use wasm_bindgen::prelude::*;

use crate::compact::from_proj;
use crate::encmove::enc_move;
use crate::mcts::{pick, root_moves, root_search, Opts, RootStats};
use crate::rng::Rng;

/// The tier this serves. `duel_search` takes its budget from the caller instead of the
/// tier's `max_iters`/`time_limit`, which were sized for a starved Python server — but
/// everything else about the bot (leaf, prune, rollout depth, greedy pick) is the tier's.
const TIER: &str = "hard";

fn err(msg: &str) -> String {
    format!("{{\"error\":\"{}\"}}", msg)
}

fn parse_state(state_json: &str) -> Option<(crate::engine::State, usize)> {
    from_proj(&serde_json::from_str::<serde_json::Value>(state_json).ok()?)
}

/// Search ONE decision from the projected state and return the root statistics:
/// `{"visits":[i32...], "wins":[f64...]}`, indexed by `mcts::root_moves`.
///
/// Bounded by whichever of `budget_ms` / `max_sims` comes first. `max_sims` is not
/// optional in practice: a node is allocated per simulation and Duel's root nodes are
/// wide (~76 moves), so an unbounded fast device would grow the tree until the tab dies.
/// `seed` is f64 (JS numbers are exact to 2^53 — far past any seed we pass) to keep
/// BigInt out of the worker.
#[wasm_bindgen]
pub fn duel_search(state_json: &str, budget_ms: f64, max_sims: u32, seed: f64) -> String {
    let (st, seat) = match parse_state(state_json) {
        Some(x) => x,
        None => return err("bad state"),
    };
    let opts = Opts {
        time_limit: Some((budget_ms / 1000.0).max(0.0)),
        max_iters: Some(if max_sims == 0 { u64::MAX } else { max_sims as u64 }),
        ..Default::default()
    };
    let mut rng = Rng::new(seed.max(0.0) as u64);
    match root_search(&st, seat, TIER, &opts, &mut rng) {
        Some(s) => serde_json::json!({ "visits": s.n, "wins": s.w }).to_string(),
        None => err("no decision"),
    }
}

/// Apply the tier's pick rule to POOLED root statistics and return the winning move in
/// `encmove` (== `gen_engine_fixtures.enc_move`) encoding.
///
/// Separate from `duel_search` so `mcts::pick_greedy`'s (visits, mean-value) tie-break
/// stays in ONE place: only the main thread holds the pooled arrays, and reimplementing
/// the rule in JS to pick there would be a second copy of a load-bearing decision. The
/// tie-break is not a nicety — without it a thin search returns the FIRST index (a token
/// take), never buys, and the game never ends.
///
/// `visits_json`/`wins_json` must be indexed by `root_moves(state)`; a length mismatch is
/// rejected rather than silently picking the wrong move.
#[wasm_bindgen]
pub fn duel_pick_move(state_json: &str, visits_json: &str, wins_json: &str) -> String {
    let (st, seat) = match parse_state(state_json) {
        Some(x) => x,
        None => return err("bad state"),
    };
    let n: Vec<i32> = match serde_json::from_str(visits_json) {
        Ok(v) => v,
        Err(_) => return err("bad visits"),
    };
    let w: Vec<f64> = match serde_json::from_str(wins_json) {
        Ok(v) => v,
        Err(_) => return err("bad wins"),
    };
    let moves = root_moves(&st, seat, true);
    if moves.is_empty() {
        return err("no decision");
    }
    if moves.len() != n.len() || moves.len() != w.len() {
        return err("stats/move-list length mismatch");
    }
    let stats = RootStats { moves, n, w };
    // Greedy: the client path serves "hard" only, whose temperature is 0. Passing a
    // temperature here would need an rng and would make the pick non-reproducible from
    // the pooled stats alone.
    let mut rng = Rng::new(0);
    let i = pick(&stats, 0.0, &mut rng);
    enc_move(&stats.moves[i]).to_string()
}
