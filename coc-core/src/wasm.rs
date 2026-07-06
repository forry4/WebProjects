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
use crate::valuenet::PolicyValueNet;
use crate::vsearch;

thread_local! {
    static MODEL: RefCell<Option<PolicyValueNet>> = const { RefCell::new(None) };
}

/// Load the PV model from the compact binary blob. Call once per worker before any
/// pv/hybrid search. Returns false on a malformed blob (caller drops the worker).
#[wasm_bindgen]
pub fn coc_init_model(bytes: &[u8]) -> bool {
    match netio::pv_from_bin(bytes) {
        Some(net) => {
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
    let Some((s, _)) = state_after(state_json, prefix_json) else {
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
    let mut search = Search::new(s, vsearch::C_PUCT);
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
    visits
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
