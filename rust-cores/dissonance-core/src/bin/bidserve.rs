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
//! It also answers a second, OFFLINE-ONLY request: `{"resolve": {...}}` takes a
//! whole deal plus the settled contract's `payoff_terms` and returns what that
//! contract is worth under exact double-dummy play.
//!
//!   stdin :  `{"resolve":{"hands":[[..],[..]],"piles":[...],"trump":d,
//!                         "leader":s,"terms":{...}}}`
//!   stdout:  `{"payoff":i,"pts":i,"duck":bool}`
//!
//! WHY IT LIVES HERE RATHER THAN IN THE ARENA. Resolving a round by PLAYING it
//! with the greedy policy scores both arms' auctions against a policy neither
//! tier would use, and adds the card play's variance on top of the bidding's --
//! and the bidding's is what the arena is trying to see. `bin/bidlab` has
//! resolved by exact solve since the design campaign for exactly that reason.
//! Reusing this process means the arena needs no second binary and no second
//! copy of the deal encoding.
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
use dissonance::state::POOL;
use dissonance::wire::{answer_auction, contract_from_json, deal_from_json};
use std::io::{self, BufRead, Write};

/// Resolve one settled contract on the REAL deal, exactly.
///
/// Returns three things, and the second and third are what make this more than
/// a scorer:
///
/// * `payoff` — the exact declarer-minus-defender value under contract-optimal
///   play. This is the answer, and it is what an auction arena should score a
///   round with: it has no card-play noise in it at all.
/// * `pts` — the declarer's total under POINTS-optimal play. A separate solve,
///   reported apart because it is NOT the total they finish on while playing
///   for the contract, and because a lower-variance yardstick is worth having
///   beside a noisy payoff.
/// * `duck` — can the declarer guarantee taking no +2 trick, i.e. is the Null
///   consolation available.
///
/// THE LAST TWO ARE THE SERVED TIER'S OWN LEAF. `bid::Option_::payoff(pts,
/// duck)` is exactly `max(contract_from_points, null_if_duckable)` — so a
/// caller that has all three can compare the served leaf against the exact
/// value on every single round, for the price of two cheap extra solves. That
/// comparison is the whole "is the points proxy good enough" question, and it
/// costs nothing to ask once the harness is resolving this way anyway.
fn resolve(dd: &mut Dd, req: &serde_json::Value) -> Option<(i32, i32, bool)> {
    let s = deal_from_json(req)?;
    let c = contract_from_json(req.get("terms")?)?;
    let payoff = dd.solve_contract(&s, &c);
    let diff = dd.solve(&s) as i32;
    let p0 = (POOL as i32 + diff) / 2;
    let pts = if c.declarer == 0 { p0 } else { POOL as i32 - p0 };
    let duck = dd.null_no_even_makeable(&s, c.declarer);
    Some((payoff, pts, duck))
}

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
        if let Some(req) = v.get("resolve") {
            match resolve(&mut dd, req) {
                Some((payoff, pts, duck)) => {
                    writeln!(out, "{{\"payoff\":{payoff},\"pts\":{pts},\"duck\":{duck}}}")
                        .unwrap();
                }
                // Loud, not silent: a deal that does not read back is a harness
                // bug, and a resolver that quietly returned 0 would look like a
                // legitimate result on every round.
                None => { writeln!(out, "{{\"error\":\"unresolvable deal\"}}").unwrap(); }
            }
            out.flush().unwrap();
            continue;
        }
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
