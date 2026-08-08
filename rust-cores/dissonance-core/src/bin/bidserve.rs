//! Drive the SHIPPED auction search from outside the browser.
//!
//! The Hard tier's auction is `bid.rs` reached through `wasm.rs`, and `wasm` is
//! `#[cfg(target_arch = "wasm32")]` — so until now the only way to run it was in
//! a browser, and its strength was measured nowhere. `bin/bidlab` measures
//! `auction.rs`, which is the design campaign's own solver and a DIFFERENT
//! implementation; it answers "should a solver bid this way", not "what does the
//! shipped bot do".
//!
//! This is a line protocol so the SERVER can drive it: the option list, the
//! prices and the moves all come from `engine.auction_payoff_options`, exactly
//! as they do in a real room, and nothing about what a bid IS lives here.
//!
//!   stdin :  one armed request per line, `{"view":..., "auction":{...}}`
//!   stdout:  `{"sums":[...]}` per line, in the option list's own order
//!
//! Reproduces `odd_pick_bid`'s body rather than calling it (it is behind the
//! wasm cfg). The LAST_BID cache is deliberately absent: it is a latency
//! optimisation and changes no decision.
use dissonance::bid;
use dissonance::dd::Dd;
use dissonance::rng::Rng;
use dissonance::wire::{options_from_json, view_from_json};
use std::io::{self, BufRead, Write};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let k: usize = args.first().and_then(|s| s.parse().ok()).unwrap_or(3);
    let bits: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(18);
    let mut dd = Dd::new(bits);
    let stdin = io::stdin();
    let mut out = io::stdout();
    let mut seed: u64 = 0x5EED_1234;
    for line in stdin.lock().lines() {
        let line = match line { Ok(l) => l, Err(_) => break };
        if line.trim().is_empty() { continue }
        let v: serde_json::Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => { writeln!(out, "{{\"error\":\"{e}\"}}").unwrap(); continue }
        };
        let view = match v.get("view").and_then(|x| view_from_json(x)) {
            Some(x) => x,
            None => { writeln!(out, "{{\"error\":\"unsearchable\"}}").unwrap(); continue }
        };
        let auc = v.get("auction").cloned().unwrap_or(serde_json::Value::Null);
        let opts = options_from_json(auc.get("options").unwrap_or(&serde_json::Value::Null));
        if opts.is_empty() {
            writeln!(out, "{{\"sums\":[]}}").unwrap();
            out.flush().unwrap();
            continue;
        }
        // Whoever would be DECLARING under these options -- not always the seat
        // asked. A defender weighing Kontra prices the OPPONENT's contract.
        let declarer = auc.get("declarer").and_then(|x| x.as_u64())
            .unwrap_or(view.me as u64) as usize;
        let sign = if view.me == declarer { 1.0 } else { -1.0 };
        seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        let mut rng = Rng::new(seed);
        let (wanted, wanted_opp) = bid::wanted_denoms(&opts);
        let mut cache = bid::Solved::default();
        bid::solve_into(&view, &mut dd, &mut rng, k, wanted, wanted_opp, declarer, &mut cache);
        let sums = bid::price(&opts, &cache.worlds, cache.covered, cache.covered_opp);
        let body: Vec<String> = sums.iter().map(|x| (x * sign).to_string()).collect();
        writeln!(out, "{{\"sums\":[{}]}}", body.join(",")).unwrap();
        out.flush().unwrap();
    }
}
