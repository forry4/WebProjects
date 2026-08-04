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

use crate::attn::AttnNet;
use crate::compact::from_proj;
use crate::encmove::enc_move;
use crate::mcts::{pick, root_moves, root_search_with_leaf, Leaf, Opts, RootStats};
use crate::rng::Rng;

// The deployed Hard leaf: the card-set ATTENTION value net (rollout + attention value = "attnval").
// It beat the heuristic leaf at equal sims across the ladder (700:0.58 / 2000:0.62 / 4000:0.59, edge
// GROWS with depth) where the heuristic saturates by ~6k — so at prod's ~60k sims it is the stronger
// bot. Embedded (~1.9MB JSON) + parsed once per worker (thread_local). Rollout unchanged.
static ATTN_JSON: &str = include_str!("attn_value_net.json");
thread_local! {
    static ATTN_NET: AttnNet = AttnNet::from_json_str(ATTN_JSON).expect("embedded attn_value_net.json");
}

// The EXPERT leaf: champion-1 — the deployed v2 (Hard) further retrained to DEFEND patient development
// (the human-exploited blind spot), via a league dev-defense pass. Beats Hard's v2 0.559/0.570/0.583
// at 700/2k/4k sims (edge GROWS with search, so stronger still at prod's ~60k). Same arch/serving
// path as Hard — only the weights differ; selected by `duel_search_expert`.
static EXPERT_JSON: &str = include_str!("attn_expert_net.json");
thread_local! {
    static EXPERT_NET: AttnNet = AttnNet::from_json_str(EXPERT_JSON).expect("embedded attn_expert_net.json");
}

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
        // COHERENT single-world search (determinize once + chance held fixed). Beats the old per-sim
        // PIMC ~0.585 (n=400, mirror 0.5000). Per-worker one world -> the root-pool over N workers is an
        // N-world coherent ensemble (hedges strategy fusion). c_puct 1.0 = the winning plateau (0.3-1.0).
        coherent: true,
        prior_c: Some(1.0),
        ..Default::default()
    };
    let mut rng = Rng::new(seed.max(0.0) as u64);
    ATTN_NET.with(|attn| {
        match root_search_with_leaf(&st, seat, TIER, &opts, Leaf::AttnVal(attn), &mut rng) {
            Some(s) => serde_json::json!({ "visits": s.n, "wins": s.w }).to_string(),
            None => err("no decision"),
        }
    })
}

/// `duel_search` for the EXPERT tier — the identical search (same `TIER` config, leaf, prune, rollout,
/// greedy pick) but with the stronger `EXPERT_NET` (champion-1) as the value leaf. A separate entry
/// (not a tier param) so the existing Hard worker call is byte-unchanged; the worker picks this when
/// the room difficulty is "expert". `duel_pick_move` is net-independent (pooled-stats pick) → shared.
#[wasm_bindgen]
pub fn duel_search_expert(state_json: &str, budget_ms: f64, max_sims: u32, seed: f64) -> String {
    let (st, seat) = match parse_state(state_json) {
        Some(x) => x,
        None => return err("bad state"),
    };
    let opts = Opts {
        time_limit: Some((budget_ms / 1000.0).max(0.0)),
        max_iters: Some(if max_sims == 0 { u64::MAX } else { max_sims as u64 }),
        // COHERENT single-world search (determinize once + chance held fixed). Beats the old per-sim
        // PIMC ~0.585 (n=400, mirror 0.5000). Per-worker one world -> the root-pool over N workers is an
        // N-world coherent ensemble (hedges strategy fusion). c_puct 1.0 = the winning plateau (0.3-1.0).
        coherent: true,
        prior_c: Some(1.0),
        // MINIMAX selection: sign Q by node actor. The historical max-max (maximizing the ROOT's value
        // even at OPPONENT nodes = a cooperating-opponent model) measured 0.62 @cpuct1.0 / 0.67 @cpuct0.3
        // WORSE than this, control 0.5000 exact (2026-07-26). Expert only — Hard stays byte-unchanged.
        minimax: true,
        // AZ POLICY PRIOR at the measured optimum T*=2.0 (temp ladder: 0.5 sharp -> 0.446 HURTS,
        // 1.0 -> 0.524, 2.0 soft -> 0.5887 [.554,.622] = GO-strong; guide, don't dominate). Requires a
        // policy head — EXPERT_NET carries one, so this entry point ONLY. Edge decays with per-world
        // depth (0.535 @4000 sims), so re-verify if the sims/worker budget moves a lot.
        net_policy_temp: Some(2.0),
        // OPPONENT MODEL: c_puct at OPPONENT nodes only. Low = hard minimax (commit to the single
        // best reply); high = visits stay spread so what propagates up approximates an average over
        // replies (expectimax). The full ladder, champion-net self-A/B, control 0.5000 exact:
        //   3.0 = 0.4875 | 1.0 (was shipped) | 0.3 = 0.5400 | 0.1 = 0.5970 | 0.03 = 0.5913
        //   0.0 = 0.4412 COLLAPSE
        // An interior optimum with a plateau at 0.03-0.1. The collapse at 0.0 is the instructive
        // end: signed Q flips sign with who is ahead, so when the ROOT IS LOSING a visited reply
        // carries positive Q and beats an unvisited move's neutral-0 FPU — with no U term there is
        // nothing left to reconsider, and the node locks onto whichever reply it explored first.
        // Some exploration at opponent nodes is load-bearing, not slack.
        // The edge GROWS with depth (0.5970 @1500/world K=1 -> 0.6233 @pool4x1200 ->
        // 0.6900 [0.643, 0.733] @pool4x5000 = PRODUCTION shape, n=400, mirror 0.5000). Measured at
        // FPU neutral-0, which E3 confirmed as best (0.2 = 0.4938, 0.5 = 0.5200, both wash) — if FPU
        // ever changes, this whole ladder must be re-read, since the two knobs interact.
        opp_c: Some(0.1),
        ..Default::default()
    };
    let mut rng = Rng::new(seed.max(0.0) as u64);
    EXPERT_NET.with(|attn| {
        match root_search_with_leaf(&st, seat, TIER, &opts, Leaf::AttnVal(attn), &mut rng) {
            Some(s) => serde_json::json!({ "visits": s.n, "wins": s.w }).to_string(),
            None => err("no decision"),
        }
    })
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

// ─── Offline-driver exports (stateless save-envelope calls for local vs-AI) ──
// The browser is the authority in an offline game: it holds the SAVE envelope
// (dump.rs — full-fidelity State: ordered bag/decks, blind-reserve identities,
// the `revealed` undo gate) and every step is a pure JSON→JSON call. Search
// stays on the REDACTED projection from `duel_offline_proj`, so the AI cannot
// read the hidden order the client physically holds — the exact projection the
// server ships online, consumed by the same `duel_search*` entries above.
// All errors are `{"error":...}`.

/// Deal a fresh 2-player game and return its save-envelope JSON. Mirrors
/// `engine.new_game`: per-level deck shuffles + pyramid deal, 25-token bag drawn
/// onto the spiral, all 4 royals out, seat 1's setup privilege.
#[wasm_bindgen]
pub fn duel_new_game_json(seed: u64) -> String {
    crate::dump::state_to_json(&crate::engine::State::new_game(seed))
}

/// Legal moves for the acting seat as engine dicts: `{"actor": seat|-1, "moves":[...]}`
/// — drives the offline bot loop's forced-move fast path and the human-move matcher.
#[wasm_bindgen]
pub fn duel_legal_json(save_json: &str) -> String {
    match crate::gamedict::legal_json(save_json) {
        Ok(v) => v.to_string(),
        Err(e) => serde_json::json!({ "error": e }).to_string(),
    }
}

/// Apply one move (engine-style `{"type":...}` OR encmove `{"t":...}` — what
/// `duel_pick_move` emits) for `seat`. Validates by `legal_moves` membership.
/// `shuffle_seed` feeds the (at most one) replenish bag-reshuffle. Returns
/// `{"save": <envelope>, "events": [...]}` — events oldest→newest for the driver
/// to APPEND (Duel's log appends; the JSX reverses for display).
#[wasm_bindgen]
pub fn duel_apply_json(
    save_json: &str,
    move_json: &str,
    seat: usize,
    pid0: &str,
    pid1: &str,
    shuffle_seed: u64,
) -> String {
    match crate::gamedict::apply_save(save_json, move_json, seat, pid0, pid1, shuffle_seed) {
        Ok((save, events)) => {
            // `save` is already a JSON document; splice it in raw.
            format!(r#"{{"save":{},"events":{}}}"#, save, serde_json::Value::Array(events))
        }
        Err(e) => serde_json::json!({ "error": e }).to_string(),
    }
}

/// Render the save as `viewer`'s wire dict — `engine.player_view`'s exact shape
/// and redaction (bag→count, decks→counts, the other seat's blind reserves as
/// `{"level", "facedown": true}` until the game is over).
#[wasm_bindgen]
pub fn duel_player_view_json(
    save_json: &str,
    pid0: &str,
    pid1: &str,
    name0: &str,
    name1: &str,
    viewer: i32,
) -> String {
    let Some(s) = crate::dump::state_from_json(save_json) else {
        return r#"{"error":"bad save"}"#.to_string();
    };
    crate::gamedict::to_player_view(&s, [pid0, pid1], [name0, name1], viewer).to_string()
}

/// The REDACTED search projection for `ai_search.state` — `compact.project`'s
/// shape for `seat` (bag sorted, unseen pools sorted, blind reserves as counts).
#[wasm_bindgen]
pub fn duel_offline_proj(save_json: &str, seat: usize) -> String {
    let Some(s) = crate::dump::state_from_json(save_json) else {
        return r#"{"error":"bad save"}"#.to_string();
    };
    if seat > 1 {
        return r#"{"error":"bad seat"}"#.to_string();
    }
    crate::gamedict::to_proj(&s, seat).to_string()
}

// ─── Value-net forward micro-bench (Node/browser; not a serving entry) ───────────
// The one number the int8 rewrite is really FOR: wasm has no f32 FMA but HAS an integer dot
// (`i32x4_dot_i16x8`), so int8 is the path that changes the BROWSER forward economics. These
// two entries time the f32 vs int8 forward IN THE WASM VM so the deployment-relevant ratio can
// be read from Node — on a RANDOM-weight net (forward speed is weight-independent, so no need
// to embed the 3MB trained JSON in the serving wasm). Build with `+simd128` (per the wasm-pack
// invocation) to exercise `qdot`'s i32x4_dot arm; without it int8 falls to the scalar loop.
//
// The input is perturbed each iteration so the (pure) forward can't be hoisted out of the loop
// (which would collapse the bench to one call). Returns `{"ms":...,"checksum":...,"sps":...}`.

fn bench_raw() -> Vec<f32> {
    let mut rng = Rng::new(0xD0E1);
    (0..275).map(|_| (rng.next_f64() as f32 - 0.5) * 2.0).collect()
}

/// Time `iters` f32 forwards (chunked `dot`, no-alloc) on a random net; report ms + sims/s.
#[wasm_bindgen]
pub fn duel_bench_forward_f32(iters: u32, seed: f64) -> String {
    let net = crate::valuenet::ValueNet::random(seed.max(0.0) as u64);
    let mut raw = bench_raw();
    let rn = raw.len();
    let t0 = js_sys::Date::now();
    let mut sink = 0.0f64;
    for k in 0..iters as usize {
        raw[k % rn] += 1e-6; // defeat loop-invariant hoisting
        sink += net.forward(&raw);
    }
    let ms = js_sys::Date::now() - t0;
    let sps = if ms > 0.0 { iters as f64 / (ms / 1000.0) } else { f64::INFINITY };
    format!("{{\"ms\":{},\"checksum\":{},\"sps\":{}}}", ms, sink, sps)
}

/// Time `iters` int8 forwards (quantized trunk, `qdot` i32x4_dot arm) on a random net.
#[wasm_bindgen]
pub fn duel_bench_forward_i8(iters: u32, seed: f64) -> String {
    let net = crate::valuenet::ValueNet::random(seed.max(0.0) as u64);
    let q = crate::valuenet::QuantValueNet::from_f32(&net);
    let mut raw = bench_raw();
    let rn = raw.len();
    let t0 = js_sys::Date::now();
    let mut sink = 0.0f64;
    for k in 0..iters as usize {
        raw[k % rn] += 1e-6;
        sink += q.forward(&raw);
    }
    let ms = js_sys::Date::now() - t0;
    let sps = if ms > 0.0 { iters as f64 / (ms / 1000.0) } else { f64::INFINITY };
    format!("{{\"ms\":{},\"checksum\":{},\"sps\":{}}}", ms, sink, sps)
}
