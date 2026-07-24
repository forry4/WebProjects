//! WASM serving entries (P5). One ENGINE MOVE per client work-unit via a PREFIX
//! protocol (keeps root-parallelism across micro-decisions): the server ships the
//! compact projection (compact.py::project shape, supply pools pre-sorted) at each
//! of the AI's engine-move boundaries; each worker searches the current micro
//! decision from `state + prefix`, the main thread SUMS root visits across the
//! pool, argmaxes, appends to the prefix, and at the boundary (Micro::None)
//! converts the chain to the compact dict-move JSON bridge.py resolves.
//!
//! The model is NOT embedded (improves on the spender pattern): the worker fetches
//! the compact binary blob (tools/pv_json_to_bin.py, ~2.6MB vs 14MB JSON) once and
//! passes it to `coc_init_model` — a model swap is a file replace, no wasm rebuild.

use std::cell::RefCell;

use wasm_bindgen::prelude::*;

use crate::actions::chain_to_compact;
use crate::engine::{self, Micro, State};
use crate::mcts::Search;
use crate::netio;
use crate::pxio::from_proj;
use crate::rng::Rng;
use crate::valuenet::{PolicyValueNet, QuantPolicyValueNet};
use crate::vsearch;

thread_local! {
    static MODEL: RefCell<Option<PolicyValueNet>> = const { RefCell::new(None) };
    // int8 twin, quantized from the f32 net at load. v128 has no f32 FMA (the
    // f32 forward is compute-bound) but DOES have integer dot — int8 is the one
    // kernel change that speeds the wasm forward. Same quantization that gated
    // STRENGTH-NEUTRAL natively (fresh-seed 0.5000), and the integer math is
    // exact/deterministic, so that result transfers. "netval" serves int8;
    // "netvalf32" keeps the f32 path (A/B + rollback).
    static QMODEL: RefCell<Option<QuantPolicyValueNet>> = const { RefCell::new(None) };
    // Per-decision TREE REUSE + chunked continuation: the last search survives the
    // call, keyed by (state hash, mode, prefix). Same state + LONGER prefix →
    // re-root through the applied actions (~1.3x: micro-decision N inherits the
    // subtree micro-decision N-1 already built under the chosen action). Same
    // state + SAME prefix → CONTINUE the same tree (the JSX searches in time
    // slices and stops early once the summed visit lead is uncatchable — the
    // adaptive budget). One tree per worker, replaced per call — memory bounded.
    static TREE: RefCell<Option<TreeCache>> = const { RefCell::new(None) };
}

struct TreeCache {
    key: u64,
    mode: String,
    prefix: Vec<usize>,
    search: Search,
}

fn fnv1a(s: &str) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in s.as_bytes() {
        h ^= *b as u64;
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    h
}

/// Load the PV model from the compact binary blob. Call once per worker before any
/// pv/hybrid search. Returns false on a malformed blob (caller drops the worker).
#[wasm_bindgen]
pub fn coc_init_model(bytes: &[u8]) -> bool {
    match netio::pv_from_bin(bytes) {
        Some(net) => {
            QMODEL.with(|q| *q.borrow_mut() = Some(QuantPolicyValueNet::from_f32(&net)));
            MODEL.with(|m| *m.borrow_mut() = Some(net));
            true
        }
        None => false,
    }
}

/// Parse the projection + prefix and roll the state forward. The prefix must be
/// the micro-actions already chosen this engine move (possibly empty).
fn state_after(state_json: &str, prefix_json: &str) -> Option<(State, Vec<usize>)> {
    let proj: serde_json::Value = serde_json::from_str(state_json).ok()?;
    let prefix: Vec<usize> = serde_json::from_str(prefix_json).ok()?;
    let mut s = from_proj(&proj);
    for &a in &prefix {
        if s.is_over() || !engine::legal_actions(&s).contains(&a) {
            return None;
        }
        engine::apply(&mut s, a);
    }
    Some((s, prefix))
}

/// Position probe after applying `prefix`:
/// `{"over":0|1,"boundary":0|1,"actor":i,"forced":a|-1,"legal":n}`.
/// `boundary` = the prefix forms a complete engine move (Micro back to None);
/// `forced` = the single legal action when there is exactly one (skip the search).
/// `{"error":...}` on parse/illegal-prefix (caller falls back to the server AI).
#[wasm_bindgen]
pub fn coc_step_info(state_json: &str, prefix_json: &str) -> String {
    let Some((s, prefix)) = state_after(state_json, prefix_json) else {
        return r#"{"error":"bad state/prefix"}"#.to_string();
    };
    let over = s.is_over();
    let boundary = !prefix.is_empty() && s.micro == Micro::None;
    let (forced, n_legal) = if over {
        (-1i64, 0usize)
    } else {
        let legal = engine::legal_actions(&s);
        (if legal.len() == 1 { legal[0] as i64 } else { -1 }, legal.len())
    };
    format!(
        r#"{{"over":{},"boundary":{},"actor":{},"forced":{},"legal":{}}}"#,
        over as u8,
        boundary as u8,
        s.actor(),
        forced,
        n_legal
    )
}

/// ROOT-PARALLEL piece: one determinized search of the current micro decision,
/// bounded by `budget_ms` wall-clock OR `max_sims` (0 = uncapped), returning the
/// root visit vector (length N_ACTIONS). `mode`: "hybrid" (net prior +
/// rollout-heuristic value — the P4 self-play config), "pv" (pure net leaf), or
/// "heur" (scaffold, no model needed). Panics trap to a JS error the worker
/// reports; the server watchdog then computes the move — same failure envelope
/// as the spender workers.
#[wasm_bindgen]
pub fn coc_search_timed(
    state_json: &str,
    prefix_json: &str,
    mode: &str,
    budget_ms: f64,
    max_sims: u32,
    seed: u64,
) -> Vec<i32> {
    let Some((s, prefix)) = state_after(state_json, prefix_json) else {
        return Vec::new();
    };
    let mut visits = vec![0i32; engine::N_ACTIONS];
    if s.is_over() {
        return Vec::new();
    }
    let legal = engine::legal_actions(&s);
    if legal.len() == 1 {
        visits[legal[0]] = 1;
        return visits;
    }
    // netval (int8 or f32) serves with its tuned exploration constant.
    let c_puct = if mode.starts_with("netval") { vsearch::NETVAL_C_PUCT } else { vsearch::C_PUCT };
    // Tree reuse: adopt the cached search when it belongs to this decision chain
    // (same shipped state + mode, cached prefix is a prefix of ours — equal =
    // chunked continuation, shorter = re-root through the applied actions).
    let key = fnv1a(state_json);
    let cached: Option<Search> = TREE.with(|t| {
        let c = t.borrow_mut().take()?;
        if c.key != key
            || c.mode != mode
            || c.prefix.len() > prefix.len()
            || prefix[..c.prefix.len()] != c.prefix[..]
        {
            return None;
        }
        let mut se = c.search;
        for &a in &prefix[c.prefix.len()..] {
            if !se.advance_root_child(a) {
                return None;
            }
        }
        se.set_root_state(s.clone());
        Some(se)
    });
    let mut search = cached.unwrap_or_else(|| Search::new(s, c_puct));
    let mut rng = Rng::new(seed ^ 0x9E77);
    let start = js_sys::Date::now();
    let budget_left = |n: u32| {
        (max_sims == 0 || n < max_sims)
            && (n % 64 != 0 || n == 0 || js_sys::Date::now() - start < budget_ms)
    };
    let mut n: u32 = 0;
    match mode {
        "heur" => {
            while budget_left(n) {
                search.sim(&mut rng, &vsearch::heur_eval);
                n += 1;
            }
        }
        "pv" => MODEL.with(|m| {
            let mb = m.borrow();
            let net = mb.as_ref().expect("coc_init_model not called");
            let eval = |st: &State, actor: usize, lg: &[usize], _r: &mut Rng| {
                vsearch::pv_eval(net, st, actor, lg)
            };
            while budget_left(n) {
                search.sim(&mut rng, &eval);
                n += 1;
            }
        }),
        "netval" => QMODEL.with(|m| {
            // net prior + NETVAL_ROLLOUT_STEPS rollout + net VALUE at the truncation
            // (with NETVAL_C_PUCT, set above). Beats the heuristic-truncation hybrid
            // ~0.58-0.61, and the tuned config (30 steps + c_puct 1.0) adds another
            // ~0.62-0.64 over netval@20@1.5 — both gains GROW with depth so they
            // transfer to serving's ~20k sims. The campaign's gain over the bootstrap.
            // Serves the INT8 twin (simd128 integer dot — see QMODEL note);
            // "netvalf32" below is the f32 escape hatch.
            let mb = m.borrow();
            let net = mb.as_ref().expect("coc_init_model not called");
            let eval = |st: &State, actor: usize, lg: &[usize], r: &mut Rng| {
                vsearch::hybrid_netval_eval_steps(net, st, actor, lg, r, vsearch::NETVAL_ROLLOUT_STEPS)
            };
            while budget_left(n) {
                search.sim(&mut rng, &eval);
                n += 1;
            }
        }),
        "netvalf32" => MODEL.with(|m| {
            let mb = m.borrow();
            let net = mb.as_ref().expect("coc_init_model not called");
            let eval = |st: &State, actor: usize, lg: &[usize], r: &mut Rng| {
                vsearch::hybrid_netval_eval_steps(net, st, actor, lg, r, vsearch::NETVAL_ROLLOUT_STEPS)
            };
            while budget_left(n) {
                search.sim(&mut rng, &eval);
                n += 1;
            }
        }),
        _ => MODEL.with(|m| {
            // "hybrid" (default): net prior + rollout-heuristic value
            let mb = m.borrow();
            let net = mb.as_ref().expect("coc_init_model not called");
            let eval = |st: &State, actor: usize, lg: &[usize], r: &mut Rng| {
                vsearch::hybrid_eval(net, st, actor, lg, r)
            };
            while budget_left(n) {
                search.sim(&mut rng, &eval);
                n += 1;
            }
        }),
    }
    visits.copy_from_slice(search.root_visits());
    TREE.with(|t| {
        *t.borrow_mut() = Some(TreeCache { key, mode: mode.to_string(), prefix, search });
    });
    visits
}

/// Multi-tree variant of `coc_search_timed` (NETVAL): `ntrees` root-parallel
/// searches in LOCKSTEP, leaf evals batched through one `forward_batch` pass.
/// **MEASURED NEGATIVE IN WASM — do not route serving here (2026-07-09 Node
/// A/B: 874 vs 2,852 sims/s single-tree, flat across K=8/16).** The batched
/// kernel is a memory-BANDWIDTH optimization built on register blocking; the
/// native forward is load-bound with 16 wide registers, but v128 is 4-lane,
/// FMA-less and COMPUTE-bound, and the 4-input block spills — so batching
/// only adds overhead. Kept as tooling for a future relaxed-SIMD attempt
/// (i8 dot products would change the arithmetic economics). Correctness is
/// fine (visits sum to the same argmax as single-tree). Non-netval modes and
/// `ntrees<=1` fall back to the single-tree path.
#[wasm_bindgen]
pub fn coc_search_timed_multi(
    state_json: &str,
    prefix_json: &str,
    mode: &str,
    budget_ms: f64,
    max_sims: u32,
    seed: u64,
    ntrees: u32,
) -> Vec<i32> {
    if mode != "netval" || ntrees <= 1 {
        return coc_search_timed(state_json, prefix_json, mode, budget_ms, max_sims, seed);
    }
    let Some((s, _)) = state_after(state_json, prefix_json) else {
        return Vec::new();
    };
    if s.is_over() {
        return Vec::new();
    }
    let mut visits = vec![0i32; engine::N_ACTIONS];
    let legal = engine::legal_actions(&s);
    if legal.len() == 1 {
        visits[legal[0]] = 1;
        return visits;
    }
    let k = ntrees as usize;
    let per_tree_cap = if max_sims == 0 { u32::MAX } else { (max_sims / ntrees).max(1) };
    MODEL.with(|m| {
        let mb = m.borrow();
        let net = mb.as_ref().expect("coc_init_model not called");
        let mut tasks: Vec<crate::batch::SearchTask> = (0..k)
            .map(|i| {
                crate::batch::SearchTask::new(
                    s.clone(),
                    vsearch::NETVAL_C_PUCT,
                    seed.wrapping_add(0x9E37_79B9_7F4A_7C15u64.wrapping_mul(i as u64)),
                    per_tree_cap,
                    vsearch::NETVAL_ROLLOUT_STEPS,
                )
            })
            .collect();
        let start = js_sys::Date::now();
        let mut rounds: u32 = 0;
        loop {
            let mut live: Vec<&mut crate::batch::SearchTask> =
                tasks.iter_mut().filter(|t| !t.finished()).collect();
            if live.is_empty() {
                break;
            }
            crate::batch::step_netval(net, &mut live);
            rounds += 1;
            // one round = one sim per live tree; clock cadence ~= the single-tree n%64
            if rounds % 8 == 0 && js_sys::Date::now() - start >= budget_ms {
                break;
            }
        }
        for t in &tasks {
            for (v, rv) in visits.iter_mut().zip(t.search.root_visits()) {
                *v += rv;
            }
        }
    });
    visits
}

/// P4b throughput probe: attention forward evals/s at an arbitrary shape with
/// random weights (cost depends only on shape). Bench tooling — never called by
/// the serving path.
#[wasm_bindgen]
pub fn coc_attn_bench(t: u32, f: u32, d: u32, ff: u32, iters: u32) -> f64 {
    let cfg = crate::attn::AttnCfg {
        t: t as usize,
        f: f as usize,
        d: d as usize,
        heads: 4,
        ff: ff as usize,
        layers: 2,
        state: 80,
        trunk: 128,
        nact: engine::N_ACTIONS,
    };
    let net = crate::attn::AttnNet::random(cfg, 0xA77);
    let mut rng = Rng::new(0xBEEF);
    let mut r = |n: usize| -> Vec<f32> {
        (0..n).map(|_| (rng.next_u64() % 2000) as f32 / 1000.0 - 1.0).collect()
    };
    let tokens = r(cfg.t * cfg.f);
    let mut mask = vec![1.0f32; cfg.t];
    for i in 0..cfg.t {
        if i % 7 == 6 {
            mask[i] = 0.0;
        }
    }
    let state = r(cfg.state);
    let mut acc = 0f32;
    for _ in 0..30 {
        acc += net.forward(&tokens, &mask, &state).0;
    }
    let t0 = js_sys::Date::now();
    for _ in 0..iters {
        acc += net.forward(&tokens, &mask, &state).0;
    }
    let dt = (js_sys::Date::now() - t0) / 1000.0;
    if acc.is_nan() {
        return -1.0;
    }
    iters as f64 / dt
}

/// Compose a boundary-complete prefix into the compact dict-move JSON
/// (bridge.py::compact_to_move shape — the exact payload for the `ai_move` WS
/// action). `{"error":...}` if the prefix doesn't parse / isn't a full move.
#[wasm_bindgen]
pub fn coc_chain_move(state_json: &str, prefix_json: &str) -> String {
    let proj: serde_json::Value = match serde_json::from_str(state_json) {
        Ok(p) => p,
        Err(_) => return r#"{"error":"bad state"}"#.to_string(),
    };
    let prefix: Vec<usize> = match serde_json::from_str(prefix_json) {
        Ok(p) => p,
        Err(_) => return r#"{"error":"bad prefix"}"#.to_string(),
    };
    if prefix.is_empty() {
        return r#"{"error":"empty prefix"}"#.to_string();
    }
    let s0 = from_proj(&proj);
    let mut s = s0.clone();
    for &a in &prefix {
        if s.is_over() || !engine::legal_actions(&s).contains(&a) {
            return r#"{"error":"illegal prefix"}"#.to_string();
        }
        engine::apply(&mut s, a);
    }
    if s.micro != Micro::None {
        return r#"{"error":"prefix not at boundary"}"#.to_string();
    }
    chain_to_compact(&s0, &prefix)
}
