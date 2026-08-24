//! WASM entry points (Phase 2). Compiled only for `wasm32` (gated in lib.rs), so native builds and
//! `cargo test` never pull wasm-bindgen.
//!
//! `bench_move` builds the SAME deterministic mid-game position as the native `bench` bin and runs the
//! variant-S search for `sims` simulations, returning the chosen action index. JS times the call with
//! `performance.now()` → sims/second, compared to the native baseline + Render's logged ~380–870/move.
//!
//! `choose_action_for` is the real serving entry: it takes a compact-state JSON dump (the same shape the
//! cross-impl bridge uses) and returns the chosen action index. The action→move-dict bridge (actions.py)
//! is still unported; the browser glue will map the index for now or we port it in Phase 3.

use crate::dump::Dump;
use crate::engine::State;
use crate::rng::Rng;
use crate::vsearch;
use serde::Deserialize;
use wasm_bindgen::prelude::*;

/// Benchmark: run the search on a deterministic mid-game position; return the chosen action (JS times it).
#[wasm_bindgen]
pub fn bench_move(setup_seed: u64, setup_moves: u32, sims: usize, search_seed: u64) -> i32 {
    let pos = vsearch::demo_position(setup_seed, setup_moves);
    let mut rng = Rng::new(search_seed);
    vsearch::choose_action(&pos, pos.turn, sims, &mut rng) as i32
}

// The Dump struct (compact-state JSON shape) lives in `crate::dump` — shared with the offline
// driver exports below, which also need the Serialize direction.

/// Serving entry: search the given compact-state JSON for `seat` and return the chosen move as a
/// compact dict-move JSON string (the exact shape main.py's move handler accepts). `{"error":...}`
/// on a parse failure (the caller falls back to the server AI).
#[wasm_bindgen]
pub fn choose_move(state_json: &str, seat: usize, sims: usize, seed: u64) -> String {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return "{\"error\":\"parse\"}".to_string(),
    };
    let s = dump.into_state();
    let mut rng = Rng::new(seed);
    let a = vsearch::choose_action(&s, seat, sims, &mut rng);
    crate::actions::action_to_move_json(&s, a)
}

/// Time-budgeted serving entry: keep running simulations until `budget_ms` wall-clock has elapsed,
/// then pick the move. This makes the AI "think" for the full budget (far more sims than a fixed
/// count) instead of finishing in ~0.2s. `Date.now()` (valid in workers) is checked every 64 sims so
/// the JS-boundary overhead stays negligible.
#[wasm_bindgen]
pub fn choose_move_timed(state_json: &str, seat: usize, budget_ms: f64, seed: u64) -> String {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return "{\"error\":\"parse\"}".to_string(),
    };
    let s = dump.into_state();
    let mut rng = Rng::new(seed);
    let start = js_sys::Date::now();
    let a = vsearch::choose_action_until(&s, seat, &mut rng, |n| {
        n % 64 != 0 || (js_sys::Date::now() - start) < budget_ms
    });
    crate::actions::action_to_move_json(&s, a)
}

/// ROOT-PARALLEL piece: run a determinized search bounded by `budget_ms` OR `max_sims` (whichever
/// comes first) and return the ROOT VISIT COUNTS (length N_ACTIONS=70). Each worker calls this with a
/// distinct seed; the main thread SUMS the vectors across workers and argmaxes — standard root
/// parallelization (no shared memory). The `max_sims` cap bounds the per-worker tree size (≈ one node
/// per sim) so a fast device can't build a multi-hundred-MB tree (and finishes snappily). `max_sims=0`
/// = no cap. Empty vec on a parse error (the caller drops that worker's contribution).
#[wasm_bindgen]
pub fn search_visits_timed(state_json: &str, seat: usize, budget_ms: f64, max_sims: usize, seed: u64) -> Vec<i32> {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return Vec::new(),
    };
    let s = dump.into_state();
    let mut rng = Rng::new(seed);
    let start = js_sys::Date::now();
    let cap = if max_sims == 0 { usize::MAX } else { max_sims };
    vsearch::root_visits_until(&s, seat, &mut rng, |n| {
        n < cap && (n % 64 != 0 || (js_sys::Date::now() - start) < budget_ms)
    })
}

// ─── Variant N: learned value leaf (embedded weights) ─────────────────────────
// All four nets are embedded as BINCODE of their models.rs serde structs, not JSON
// text (~3x smaller wasm, bit-identical weights — the .json stays committed as the
// training-side source; regen via `gen_net_bins`, pinned by the models.rs test).
use crate::models::{from_bin, AttnModel, NModel, PVModel};

/// N's value net, embedded at build time (the verified learned leaf).
static N_MODEL_BIN: &[u8] = include_bytes!("n_model.bin");

fn build_n_net() -> crate::valuenet::StandardizedMlp {
    let m: NModel = from_bin(N_MODEL_BIN, "n_model");
    crate::valuenet::StandardizedMlp::new(
        crate::valuenet::Mlp::from_parts(m.dims, m.w, m.b),
        m.mu,
        m.sd,
    )
}

/// Variant N root-parallel search: identical to `search_visits_timed` but uses the LEARNED value as
/// the MCTS leaf (+ the H3 prior). The net is parsed once per call (once per move per worker —
/// negligible vs the thousands of sims it then runs). Same SUM-then-argmax aggregation as S.
#[wasm_bindgen]
pub fn search_visits_n_timed(state_json: &str, seat: usize, budget_ms: f64, max_sims: usize, seed: u64) -> Vec<i32> {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return Vec::new(),
    };
    let s = dump.into_state();
    let net = build_n_net();
    let leaf = |st: &State, sd: usize| -> f64 {
        let raw: Vec<f32> = crate::feats::features(st, sd).iter().map(|&x| x as f32).collect();
        net.forward_raw(&raw) as f64
    };
    let mut rng = Rng::new(seed);
    let start = js_sys::Date::now();
    let cap = if max_sims == 0 { usize::MAX } else { max_sims };
    vsearch::root_visits_until_leaf(
        &s,
        seat,
        &mut rng,
        |n| n < cap && (n % 64 != 0 || (js_sys::Date::now() - start) < budget_ms),
        &leaf,
    )
}

#[derive(serde::Serialize)]
struct NFull {
    visits: Vec<i32>,
    value: f64,
    q: Vec<Option<f64>>,
}

/// Variant N search returning visits + the searched POSITION VALUE + per-edge Q — for the WWSD
/// overlay's eval display (the visits-only `search_visits_n_timed` is enough to PICK a move but
/// carries no eval). JSON: `{"visits":[..70..],"value":<f64 in [-1,1], side-to-move>,"q":[..70..]}`
/// where `q[a]` is null for an unvisited action. `{"error":...}` on a parse failure. Single-threaded
/// (no worker aggregation): the friend's CPU runs the whole budget on the userscript's main thread.
#[wasm_bindgen]
pub fn search_n_full_timed(state_json: &str, seat: usize, budget_ms: f64, max_sims: usize, seed: u64) -> String {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return "{\"error\":\"parse\"}".to_string(),
    };
    let s = dump.into_state();
    let net = build_n_net();
    let leaf = |st: &State, sd: usize| -> f64 {
        let raw: Vec<f32> = crate::feats::features(st, sd).iter().map(|&x| x as f32).collect();
        net.forward_raw(&raw) as f64
    };
    let mut rng = Rng::new(seed);
    let start = js_sys::Date::now();
    let cap = if max_sims == 0 { usize::MAX } else { max_sims };
    let (n, w) = vsearch::root_nw_until_leaf(
        &s,
        seat,
        &mut rng,
        |i| i < cap && (i % 64 != 0 || (js_sys::Date::now() - start) < budget_ms),
        &leaf,
    );
    let tot: i32 = n.iter().sum();
    let value = if tot > 0 { w.iter().sum::<f64>() / tot as f64 } else { 0.0 };
    let q: Vec<Option<f64>> = (0..n.len())
        .map(|a| if n[a] > 0 { Some(w[a] / n[a] as f64) } else { None })
        .collect();
    serde_json::to_string(&NFull { visits: n, value, q })
        .unwrap_or_else(|_| "{\"error\":\"ser\"}".to_string())
}

// ─── Variant PV: AlphaZero policy+value net (embedded weights) ─────────────────
/// The Plan-A AZ champion served as N: `net_night_14` (178-feat, via `feats::features_ext`) — a
/// higher-sims (512) self-play continuation that beats the prior champion net_ext_19 ~0.55-0.58
/// (depth-robust, 256-3200 sims) and S 0.827 @400. PURE net swap (encoder unchanged from net_ext_19).
/// Rollback = revert this commit's pv_model.json (restores net_ext_19); net_pv_4 + the 125-feat
/// `features_az` path also remain in the tree.
static PV_MODEL_BIN: &[u8] = include_bytes!("pv_model.bin");

fn build_pv_net() -> crate::valuenet::PolicyValueNet {
    let m: PVModel = from_bin(PV_MODEL_BIN, "pv_model");
    crate::valuenet::PolicyValueNet::from_parts(
        m.mu, m.sd, m.tdims, m.tw, m.tb, m.vw, m.vb, m.pw, m.pb, m.n_act,
    )
}

/// LONG-MODE (21-point) specialization: `net_ext21_13` (178-feat, SAME `features_ext` encoder as the
/// 15-point net). Trained by 21-point self-play warm-started from net_night_14; beats net_night_14 AT
/// 21 points 0.6325 on fresh decks (600g), holds 0.58-0.65 across the 256-2048 sims-ladder. Served only
/// when `win_points == 21` (see the branch in the PV search fns); 15-point games are byte-identical to
/// before. Rollback = revert this commit (drops pv_model_21.json + the branch -> net_night_14 for all).
static PV_MODEL_BIN_21: &[u8] = include_bytes!("pv_model_21.bin");

fn build_pv_net_21() -> crate::valuenet::PolicyValueNet {
    let m: PVModel = from_bin(PV_MODEL_BIN_21, "pv_model_21");
    crate::valuenet::PolicyValueNet::from_parts(
        m.mu, m.sd, m.tdims, m.tw, m.tb, m.vw, m.vb, m.pw, m.pb, m.n_act,
    )
}

// ─── Variant N (Classic/15-pt): card-set ATTENTION net (net_attn_3), embedded ───
// Beats net_night_14 ~0.567 on fresh decks at depth (512/1024 sims). Per-card tokens (features_tokens)
// + attention leaf VALUE + per-token POLICY prior. 21-pt stays on net_ext21_13 (MLP). Rollback =
// revert this commit (drops attn_model.json + the 15-pt branch -> net_night_14 for Classic).
static ATTN_MODEL_BIN: &[u8] = include_bytes!("attn_model.bin");
fn build_attn_net() -> crate::attn::AttnNet {
    let m: AttnModel = from_bin(ATTN_MODEL_BIN, "attn_model");
    crate::attn::AttnNet {
        emb_w: m.emb_w, emb_b: m.emb_b, wq: m.wq, wk: m.wk, wv: m.wv, wo: m.wo,
        f1w: m.f1w, f1b: m.f1b, f2w: m.f2w, f2b: m.f2b,
        sw: m.sw, sb: m.sb, tw: m.tw, tb: m.tb, vw: m.vw, vb: m.vb,
        pg_w: m.pg_w, pg_b: m.pg_b, ptok_w: m.ptok_w, ptok_b: m.ptok_b,
    }
}

// Per-worker parsed-net cache. A Web Worker persists across every move it serves, but the serving fns
// rebuilt the net (parse ~2 MB of embedded JSON into nested Vec<f32>) on EVERY call. Parse once, lazily,
// on first use and reuse for the worker's life — the weights are immutable, so this is byte-identical to
// rebuilding. It also removes parse time from the timed budget: `start` is captured before the build, so
// on slow devices the re-parse was subtracted from the 4.5 s search window every move. thread_local is
// the right scope here (one wasm instance per worker; single-threaded).
thread_local! {
    static ATTN_NET: crate::attn::AttnNet = build_attn_net();
    static PV_NET_21: crate::valuenet::PolicyValueNet = build_pv_net_21();
}

/// Variant PV root-parallel search: like `search_visits_n_timed`, but the net supplies BOTH the MCTS
/// leaf VALUE and the POLICY PRIOR (`root_visits_until_pv`) over the 178-feat `features_ext` encoder —
/// the learned AlphaZero policy+value head. Same SUM-then-argmax root-parallel aggregation as S/N.
#[wasm_bindgen]
pub fn search_visits_pv_timed(state_json: &str, seat: usize, budget_ms: f64, max_sims: usize, seed: u64) -> Vec<i32> {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return Vec::new(),
    };
    let s = dump.into_state();
    let mut rng = Rng::new(seed);
    let start = js_sys::Date::now();
    let cap = if max_sims == 0 { usize::MAX } else { max_sims };
    if s.win_points == 21 {
        // Long mode: net_ext21_13 (MLP, features_ext) — unchanged.
        PV_NET_21.with(|net| {
            let pv = |st: &State, sd: usize| -> (f64, Vec<f64>) {
                let raw: Vec<f32> = crate::feats::features_ext(st, sd).iter().map(|&x| x as f32).collect();
                let (v, logits) = net.forward_raw(&raw);
                (v as f64, logits.iter().map(|&x| x as f64).collect())
            };
            vsearch::root_visits_until_pv(&s, seat, &mut rng,
                |n| n < cap && (n % 64 != 0 || (js_sys::Date::now() - start) < budget_ms), &pv)
        })
    } else {
        // Classic (15): card-set ATTENTION net (net_attn_3) — features_tokens leaf value + per-token policy.
        ATTN_NET.with(|net| {
            let pv = |st: &State, sd: usize| -> (f64, Vec<f64>) {
                let (t, msk, st2) = crate::feats::features_tokens(st, sd);
                net.forward(&t, &msk, &st2)
            };
            vsearch::root_visits_until_pv(&s, seat, &mut rng,
                |n| n < cap && (n % 64 != 0 || (js_sys::Date::now() - start) < budget_ms), &pv)
        })
    }
}

/// Variant PV search returning visits + the searched POSITION VALUE + per-edge Q — the PV analog of
/// `search_n_full_timed`, for the WWSD browser overlay's eval display (the visits-only
/// `search_visits_pv_timed` is enough to PICK a move but carries no eval). Same `{"visits","value",
/// "q"}` JSON shape as N. The net supplies both the leaf value and the policy prior.
#[wasm_bindgen]
pub fn search_pv_full_timed(state_json: &str, seat: usize, budget_ms: f64, max_sims: usize, seed: u64) -> String {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return "{\"error\":\"parse\"}".to_string(),
    };
    let s = dump.into_state();
    let mut rng = Rng::new(seed);
    let start = js_sys::Date::now();
    let cap = if max_sims == 0 { usize::MAX } else { max_sims };
    let (n, w) = if s.win_points == 21 {
        // Long mode: net_ext21_13 (MLP, features_ext) — unchanged.
        PV_NET_21.with(|net| {
            let pv = |st: &State, sd: usize| -> (f64, Vec<f64>) {
                let raw: Vec<f32> = crate::feats::features_ext(st, sd).iter().map(|&x| x as f32).collect();
                let (v, logits) = net.forward_raw(&raw);
                (v as f64, logits.iter().map(|&x| x as f64).collect())
            };
            vsearch::root_nw_until_pv(&s, seat, &mut rng,
                |i| i < cap && (i % 64 != 0 || (js_sys::Date::now() - start) < budget_ms), &pv)
        })
    } else {
        // Classic (15): card-set ATTENTION net (net_attn_3) — features_tokens leaf value + per-token policy.
        ATTN_NET.with(|net| {
            let pv = |st: &State, sd: usize| -> (f64, Vec<f64>) {
                let (t, msk, st2) = crate::feats::features_tokens(st, sd);
                net.forward(&t, &msk, &st2)
            };
            vsearch::root_nw_until_pv(&s, seat, &mut rng,
                |i| i < cap && (i % 64 != 0 || (js_sys::Date::now() - start) < budget_ms), &pv)
        })
    };
    let tot: i32 = n.iter().sum();
    let value = if tot > 0 { w.iter().sum::<f64>() / tot as f64 } else { 0.0 };
    let q: Vec<Option<f64>> = (0..n.len())
        .map(|a| if n[a] > 0 { Some(w[a] / n[a] as f64) } else { None })
        .collect();
    serde_json::to_string(&NFull { visits: n, value, q })
        .unwrap_or_else(|_| "{\"error\":\"ser\"}".to_string())
}

/// ENDGAME REFINEMENT (#1): given the aggregate PUCT action (argmax of the summed worker visits), run
/// the exact endgame solver on the TRUE state and return the (possibly overridden) move as dict-move
/// JSON. Runs ONCE per decision on the main thread (via one worker), after visit aggregation — cheap,
/// and a no-op outside endgame positions (returns the PUCT move's dict-move unchanged). `{"error":...}`
/// on a parse failure (caller falls back to the unrefined move / server AI).
#[wasm_bindgen]
pub fn endgame_refine_move(state_json: &str, seat: usize, puct_action: usize, seed: u64) -> String {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return "{\"error\":\"parse\"}".to_string(),
    };
    let s = dump.into_state();
    let mut rng = Rng::new(seed);
    let a = crate::endgame::refine(&s, seat, puct_action, &mut rng);
    crate::actions::action_to_move_json(&s, a)
}

/// Convert the aggregate-winning action index to a dict-move JSON for the given state (the main thread
/// resolves it once, after summing visits across the worker pool). `{"error":...}` on a parse failure.
#[wasm_bindgen]
pub fn action_to_move_for(state_json: &str, action: usize) -> String {
    let dump: Dump = match serde_json::from_str(state_json) {
        Ok(d) => d,
        Err(_) => return "{\"error\":\"parse\"}".to_string(),
    };
    let s = dump.into_state();
    crate::actions::action_to_move_json(&s, action)
}

// ─── Offline-driver exports (stateless engine calls for local vs-AI play) ─────
// The browser is the authority in an offline game: it holds the compact-state JSON, and every
// driver step is a pure JSON→JSON call — create, list legal moves, apply, render. All errors are
// `{"error":...}` strings (the driver surfaces them; nothing panics across the boundary).

/// Deal a fresh 2-player game and return its compact-state JSON (the offline save format).
#[wasm_bindgen]
pub fn new_game_json(seed: u64, win_points: i32) -> String {
    crate::dump::state_to_json(&crate::engine::new_game(seed, win_points))
}

/// Legal moves for the state's side-to-move: `[{"action":<idx>,"move":<dict-move>}, ...]`.
/// The driver matches the HUMAN's UI move dict against `move` (movesEqual) to find the action
/// index, and validates AI submissions the same way the server does (membership).
#[wasm_bindgen]
pub fn legal_moves_json(state_json: &str) -> String {
    let s = match crate::dump::state_from_json(state_json) {
        Some(s) => s,
        None => return "{\"error\":\"parse\"}".to_string(),
    };
    let parts: Vec<String> = crate::engine::legal_actions(&s)
        .into_iter()
        .map(|a| format!("{{\"action\":{},\"move\":{}}}", a, crate::actions::action_to_move_json(&s, a)))
        .collect();
    format!("[{}]", parts.join(","))
}

/// Apply `action` and return the resulting compact-state JSON. Rejects an action not in
/// `legal_actions` with `{"error":"illegal"}` — the driver must never corrupt a save with an
/// out-of-phase apply (engine::apply assumes legality).
#[wasm_bindgen]
pub fn apply_action_json(state_json: &str, action: usize) -> String {
    let mut s = match crate::dump::state_from_json(state_json) {
        Some(s) => s,
        None => return "{\"error\":\"parse\"}".to_string(),
    };
    if !crate::engine::legal_actions(&s).contains(&action) {
        return "{\"error\":\"illegal\"}".to_string();
    }
    crate::engine::apply(&mut s, action);
    crate::dump::state_to_json(&s)
}

/// Render the state as the incumbent game-dict JSON for `Spender.jsx`. `viewer` (0/1) hides the
/// OTHER seat's blind reserves while the game runs — pass the human's seat so the AI's deck-top
/// reserves stay secret, exactly as the server redacts them. -1 = full view.
#[wasm_bindgen]
pub fn game_dict_json(state_json: &str, pid0: &str, pid1: &str, viewer: i32) -> String {
    let s = match crate::dump::state_from_json(state_json) {
        Some(s) => s,
        None => return "{\"error\":\"parse\"}".to_string(),
    };
    crate::gamedict::to_game_dict_json(&s, pid0, pid1, viewer)
}
