//! Position EVAL server (bridge feature): reads JSON requests on stdin, answers with the
//! netval search's root VALUE for a position, from the actor's perspective.
//!
//! Request:  {"proj": <compact.project(game)>, "sims": 4000, "seed": 123}
//! Response: {"value": -0.13, "actor": 1, "sims": 4000}
//!
//! Exists for the expert-gap measurement (cob_eval_gap.py). Why a VALUE server and not the
//! move server: to ask "was the pro's move better than ours?" you must APPLY each candidate
//! and RE-SEARCH the child. You cannot read the answer off one root search's edge-Q -- PUCT
//! starves the runner-up (a handful of shallow pessimistic sims), so edge-Q overstates the
//! gap, and worse with more sims. Visit counts pick the best move fine; they cannot measure
//! HOW MUCH better it is. (Same lesson the Spender puzzle pipeline learned the hard way.)
//!
//! Usage: eval_server_coc <model.json> [steps] [cpuct]
//! Defaults 30/1.0 = the SERVING netval config (vsearch::NETVAL_ROLLOUT_STEPS / NETVAL_C_PUCT).

use std::io::{self, BufRead, Write};

use coc_core::engine::State;
use coc_core::mcts::Search;
use coc_core::pxio::from_proj;
use coc_core::rng::Rng;
use coc_core::valuenet::PolicyValueNet;
use coc_core::vsearch;
use serde_json::Value;

/// Root value under the netval leaf, from the ROOT ACTOR's perspective, in [-1, 1].
fn root_value_netval(net: &PolicyValueNet, s: &State, sims: u32, seed: u64,
                     steps: usize, cpuct: f64) -> f64 {
    let mut search = Search::new(s.clone(), cpuct);
    let mut rng = Rng::new(seed ^ 0x9E77);
    let eval = |st: &State, actor: usize, lg: &[usize], r: &mut Rng| {
        vsearch::hybrid_netval_eval_steps(net, st, actor, lg, r, steps)
    };
    for _ in 0..sims {
        search.sim(&mut rng, &eval);
    }
    let n: i64 = search.root_visits().iter().map(|&x| x as i64).sum();
    let w: f64 = search.root_wins().iter().sum();
    if n > 0 { w / n as f64 } else { 0.0 }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let path = args.get(1).expect("usage: eval_server_coc <model.json> [steps] [cpuct]");
    let net = coc_core::netio::pv_from_json(&std::fs::read_to_string(path).expect("model"));
    let steps: usize = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(30);
    let cpuct: f64 = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(1.0);

    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut out = stdout.lock();
    for line in stdin.lock().lines() {
        let line = line.expect("stdin");
        if line.trim().is_empty() {
            continue;
        }
        let req: Value = serde_json::from_str(&line).expect("request json");
        let sims = req["sims"].as_u64().unwrap_or(4000) as u32;
        let seed = req["seed"].as_u64().unwrap_or(1);
        let s = from_proj(&req["proj"]);
        let actor = s.actor();
        let v = if s.is_over() {
            // Terminal: exact margin-based value, same convention as the search.
            let m = s.players[actor as usize].vp as f64 - s.players[1 - actor as usize].vp as f64;
            (m / 12.0).tanh()
        } else {
            root_value_netval(&net, &s, sims, seed, steps, cpuct)
        };
        writeln!(out, r#"{{"value":{:.6},"actor":{},"sims":{}}}"#, v, actor, sims)
            .expect("stdout");
        out.flush().expect("flush");
    }
}
