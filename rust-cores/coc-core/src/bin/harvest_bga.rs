//! Turn replayed BGA expert games into training rows (bridge feature).
//!
//! Reads JSONL on stdin, one per EXPERT DECISION:
//!   {"proj": <compact.project(game)>, "move": <compact move>, "label": 0|1, "margin": N, "gid": K}
//! Writes train_pv-format CSV to argv[1]:
//!   gid, feats(N_FEATS), label, margin, root_value, policy      (no aux -> train with --aux-dim 0)
//!
//! WHY A DFS (`chain_for`): CoC's policy space is MICRO-decomposed (102 actions: spend die ->
//! menu -> place-slot -> space), so one expert ENGINE move is a CHAIN of micro-actions and each
//! micro-decision needs its own row + one-hot target. Only chain_to_compact exists (chain ->
//! move); the inverse doesn't, so we search the short legal chains for the one that composes to
//! the recorded move. Compare PARSED json, not strings -- key order isn't guaranteed.
//!
//! ROOT_VALUE: harvest_boot stores the search's root value there and train_pv blends it at
//! BETA=0.3. An expert game has no search value, and filling it with OUR net's eval would train
//! the value head toward our own opinion -- precisely the signal we don't want. So we store the
//! OUTCOME (2*label-1); the blend then stays outcome-dominated and adds no self-referential term.
//!
//! Only decisions with >1 legal action are recorded (a forced action teaches nothing).

use std::io::{self, BufRead, Write};

use coc_core::actions::chain_to_compact;
use coc_core::engine::{self, Micro, State};
use coc_core::feats;
use coc_core::pxio::from_proj;
use serde_json::Value;

const MAX_CHAIN: usize = 8;

/// Micro-action chain from `s0` that composes to `target`, or None.
fn chain_for(s0: &State, target: &Value) -> Option<Vec<usize>> {
    fn go(s0: &State, s: &State, chain: &mut Vec<usize>, target: &Value) -> Option<Vec<usize>> {
        if !chain.is_empty() && s.micro == Micro::None {
            let got: Value = serde_json::from_str(&chain_to_compact(s0, chain)).ok()?;
            return if &got == target { Some(chain.clone()) } else { None };
        }
        if chain.len() >= MAX_CHAIN || s.is_over() {
            return None;
        }
        for a in engine::legal_actions(s) {
            let mut s2 = s.clone();
            engine::apply(&mut s2, a);
            chain.push(a);
            if let Some(found) = go(s0, &s2, chain, target) {
                return Some(found);
            }
            chain.pop();
        }
        None
    }
    go(s0, s0, &mut Vec::new(), target)
}

fn trim_f(f: f32) -> String {
    if f == 0.0 { "0".into() } else { format!("{:.4}", f) }
}

fn main() {
    let out_path = std::env::args().nth(1).expect("usage: harvest_bga <out.csv>");
    let mut w = std::io::BufWriter::new(std::fs::File::create(&out_path).expect("create"));

    let (mut rows, mut miss, mut lines) = (0usize, 0usize, 0usize);
    for line in io::stdin().lock().lines() {
        let line = line.expect("stdin");
        if line.trim().is_empty() {
            continue;
        }
        lines += 1;
        let req: Value = serde_json::from_str(&line).expect("request json");
        let s0 = from_proj(&req["proj"]);
        let label = req["label"].as_i64().unwrap_or(0);
        let margin = req["margin"].as_i64().unwrap_or(0);
        let gid = req["gid"].as_i64().unwrap_or(0);
        let rootv = 2.0 * label as f64 - 1.0;   // outcome, NOT our eval (see header)

        let chain = match chain_for(&s0, &req["move"]) {
            Some(c) => c,
            None => { miss += 1; continue; }
        };

        // One row per micro-DECISION along the expert's chain.
        let mut s = s0.clone();
        for &a in &chain {
            let legal = engine::legal_actions(&s);
            if legal.len() > 1 {
                let actor = s.actor() as usize;
                let f = feats::features(&s, actor);
                let mut l = String::with_capacity(f.len() * 8 + 64);
                l.push_str(&format!("{}", gid));
                for &x in &f {
                    l.push(',');
                    l.push_str(&trim_f(x));
                }
                l.push_str(&format!(",{},{},{:.4},{}:1", label, margin, rootv, a));
                writeln!(w, "{}", l).expect("write");
                rows += 1;
            }
            engine::apply(&mut s, a);
        }
    }
    w.flush().expect("flush");
    eprintln!("harvest_bga: {lines} decisions in -> {rows} rows out ({miss} chains not found)");
}
