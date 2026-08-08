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
//! It calls the SAME `wire::answer_auction` the browser entry does — it used to
//! reproduce `odd_pick_bid`'s body, and with Expert riding in on the same
//! request there are now two search modes that would have to be kept in step in
//! two places. A harness that does not reproduce the serving shape is a lesson
//! this repo has already paid for once.
//!
//! The `Solved` cache is carried across lines, exactly as a worker carries it
//! across an auction: it is a latency optimisation keyed on the cards and
//! changes no decision.
use dissonance::dd::Dd;
use dissonance::rng::Rng;
use dissonance::wire::answer_auction;
use std::io::{self, BufRead, Write};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let k: usize = args.first().and_then(|s| s.parse().ok()).unwrap_or(3);
    let bits: u32 = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(18);
    let mut dd = Dd::new(bits);
    let stdin = io::stdin();
    let mut out = io::stdout();
    let mut seed: u64 = 0x5EED_1234;
    let mut cache: Option<(u64, dissonance::bid::Solved)> = None;
    for line in stdin.lock().lines() {
        let line = match line { Ok(l) => l, Err(_) => break };
        if line.trim().is_empty() { continue }
        let v: serde_json::Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => { writeln!(out, "{{\"error\":\"{e}\"}}").unwrap(); continue }
        };
        seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        let mut rng = Rng::new(seed);
        match answer_auction(&v, k, &mut dd, &mut rng, &mut cache) {
            Ok((sums, _)) => {
                let body: Vec<String> = sums.iter().map(|x| x.to_string()).collect();
                writeln!(out, "{{\"sums\":[{}]}}", body.join(",")).unwrap();
            }
            Err(e) => { writeln!(out, "{{\"error\":\"{e}\"}}").unwrap(); }
        }
        out.flush().unwrap();
    }
}
