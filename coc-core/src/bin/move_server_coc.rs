//! Cross-impl move server (bridge feature): reads JSON requests on stdin, answers
//! with ONE compact engine move per line. Used by games/castles_of_crimson/az/
//! rust_arena.py to play the Rust scaffold against the Python ai.py bot on the
//! authoritative engine.
//!
//! Request:  {"proj": <compact.project(game)>, "sims": 2000, "seed": 123}
//! Response: {"move": <compact move>, "actions": k}
//!
//! The search decides one micro-action at a time (fresh search per micro decision,
//! seed-offset) until the chain reaches an engine-move boundary, then composes the
//! chain via actions::chain_to_compact.

use std::io::{self, BufRead, Write};

use coc_core::actions::chain_to_compact;
use coc_core::engine::{self, Micro};
use coc_core::pxio::from_proj;
use coc_core::vsearch;
use serde_json::Value;

fn main() {
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
            let a = vsearch::choose_action_heur(&s, sims, seed.wrapping_add(chain.len() as u64));
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
