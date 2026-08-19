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
    // An optional third argument OFFSETS the seed stream. Two processes fed
    // identical request lines otherwise sample IDENTICAL worlds -- which turns
    // any attempt to emulate the browser's worker pool (four workers, each
    // sampling its own worlds, sums added) into four copies of one worker.
    let mut seed: u64 = 0x5EED_1234 ^ args.get(2)
        .and_then(|s| s.parse::<u64>().ok()).unwrap_or(0);
    let mut cache = dissonance::bid::SolvedCache::default();
    for line in stdin.lock().lines() {
        let line = match line { Ok(l) => l, Err(_) => break };
        if line.trim().is_empty() { continue }
        let v: serde_json::Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => { writeln!(out, "{{\"error\":\"{e}\"}}").unwrap(); continue }
        };
        // THE CARD SEARCH, for the per-decision regret harness. It calls
        // `wire::answer_card` -- the same body `odd_pick_card` does -- so the
        // thing being measured is the thing that is served.
        if let Some(req) = v.get("pick") {
            let view = req.get("view").and_then(dissonance::wire::view_from_json);
            match view {
                Some(view) => {
                    let c = req.get("payoff").and_then(contract_from_json);
                    let prior = c.and_then(|c| req.get("bid_prior")
                        .and_then(|p| dissonance::wire::bid_prior_from_json(p, c.declarer)));
                    let kk = req.get("k").and_then(|x| x.as_u64()).unwrap_or(8) as usize;
                    seed = seed.wrapping_mul(6364136223846793005)
                               .wrapping_add(1442695040888963407);
                    let mut r = Rng::new(seed);
                    let (moves, sums, _) = dissonance::wire::answer_card(
                        &view, c, prior.as_ref(), kk, &mut dd, &mut r);
                    let m: Vec<String> = moves.iter().map(|x| x.to_string()).collect();
                    let s: Vec<String> = sums.iter().map(|x| x.to_string()).collect();
                    writeln!(out, "{{\"moves\":[{}],\"sum\":[{}]}}",
                             m.join(","), s.join(",")).unwrap();
                }
                None => { writeln!(out, "{{\"error\":\"unsearchable view\"}}").unwrap(); }
            }
            out.flush().unwrap();
            continue;
        }
        // THE ORACLE: every legal move's EXACT value on the real deal. This is
        // what a cheater would know, and the yardstick a decision's regret is
        // measured against -- one solve, no sampling, same answer every time.
        if let Some(req) = v.get("rootvals") {
            let deal = deal_from_json(req);
            let c = req.get("terms").and_then(contract_from_json);
            match (deal, c) {
                (Some(mut s), Some(c)) => {
                    // Replay the plays already made, so the oracle is asked
                    // about the position the bot was actually facing.
                    if let Some(hist) = req.get("played").and_then(|x| x.as_array()) {
                        for card in hist.iter().filter_map(|x| x.as_u64()) {
                            s.play(card as u8);
                        }
                    }
                    let mut moves = [0u8; 16];
                    let n = s.legal(&mut moves);
                    let mut vals = [0i32; 16];
                    dd.solve_root_contract(&s, &moves[..n], &c, &mut vals);
                    let m: Vec<String> = moves[..n].iter().map(|x| x.to_string()).collect();
                    let vs: Vec<String> = vals[..n].iter().map(|x| x.to_string()).collect();
                    writeln!(out, "{{\"moves\":[{}],\"vals\":[{}],\"to_play\":{}}}",
                             m.join(","), vs.join(","), s.to_play()).unwrap();
                }
                _ => { writeln!(out, "{{\"error\":\"unresolvable oracle deal\"}}").unwrap(); }
            }
            out.flush().unwrap();
            continue;
        }
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
