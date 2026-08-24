//! Cross-impl move server (bridge feature): reads JSON requests on stdin, answers
//! with ONE compact engine move per line. Used by games/castles_of_crimson/az/
//! rust_arena.py to play the Rust scaffold against the Python ai.py bot on the
//! authoritative engine.
//!
//! Request:  {"proj": <compact.project(game)>, "sims": 2000, "seed": 123}
//! Response: {"move": <compact move>, "actions": k}
//!
//! With an argv model (`move_server_coc <model.json> [steps] [cpuct]`) decisions
//! use the NETVAL search (net prior + priority rollout + net value at truncation;
//! defaults 20/1.5 = the harvest/loop config) instead of the heuristic scaffold —
//! used to play the champion through the Python engine so its games carry full
//! move logs (the staging diagnostic).
//!
//! The search decides one micro-action at a time (fresh search per micro decision,
//! seed-offset) until the chain reaches an engine-move boundary, then composes the
//! chain via actions::chain_to_compact.

use std::io::{self, BufRead, Write};

use coc_core::actions::chain_to_compact;
use coc_core::engine::{self, Micro, State};
use coc_core::pxio::from_proj;
use coc_core::valuenet::PolicyValueNet;
use coc_core::vsearch;
use serde_json::Value;

fn choose_netval(net: &PolicyValueNet, s: &State, sims: u32, seed: u64,
                 steps: usize, cpuct: f64) -> usize {
    let legal = engine::legal_actions(s);
    if legal.len() == 1 {
        return legal[0];
    }
    let mut search = coc_core::mcts::Search::new(s.clone(), cpuct);
    let mut rng = coc_core::rng::Rng::new(seed ^ 0x9E77);
    let eval = |st: &State, actor: usize, lg: &[usize], r: &mut coc_core::rng::Rng| {
        vsearch::hybrid_netval_eval_steps(net, st, actor, lg, r, steps)
    };
    for _ in 0..sims {
        search.sim(&mut rng, &eval);
    }
    let visits = search.root_visits();
    *legal.iter().max_by_key(|&&a| visits[a]).unwrap()
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let net = args.get(1).map(|p| {
        coc_core::netio::pv_from_json(&std::fs::read_to_string(p).expect("model"))
    });
    let steps: usize = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(20);
    let cpuct: f64 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(1.5);
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = line.expect("stdin");
        if line.trim().is_empty() {
            continue;
        }
        let req: Value = serde_json::from_str(&line).expect("request json");
        let sims = req["sims"].as_u64().unwrap_or(2000) as u32;
        let seed = req["seed"].as_u64().unwrap_or(1);
        let s0 = from_proj(&req["proj"]);
        let mut s = s0.clone();
        let mut chain: Vec<usize> = Vec::new();
        loop {
            let sd = seed.wrapping_add(chain.len() as u64);
            let a = match &net {
                Some(n) => choose_netval(n, &s, sims, sd, steps, cpuct),
                None => vsearch::choose_action_heur(&s, sims, sd),
            };
            chain.push(a);
            engine::apply(&mut s, a);
            if s.micro == Micro::None {
                break;
            }
        }
        let mv = chain_to_compact(&s0, &chain);
        writeln!(out, r#"{{"move":{},"actions":{}}}"#, mv, chain.len()).expect("stdout");
        out.flush().expect("flush");
    }
}
