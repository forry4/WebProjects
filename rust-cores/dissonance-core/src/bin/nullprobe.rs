//! Base rate for the NULL contract: how often can a player, playing perfectly
//! against a defence trying to force a trick on them, take no trick at all?
//!
//! This has to be known BEFORE Null is priced or measured in the auction. If
//! the answer is a couple of percent it is a dead rung whatever it pays; if it
//! is nearly half it will eat the game. Either way, an auction experiment that
//! never bids Null tells you nothing until you know which of those you are
//! looking at.
//!
//! Reported separately by who leads, because leading is a real handicap here:
//! the lead is the one card you are never allowed to duck with.
//!
//!   nullprobe [--deals N] [--threads T]

use dissonance::auction::NULL_DENOM;
use dissonance::cards::NOTRUMP;
use dissonance::dd::Dd;
use dissonance::game::Game;
use dissonance::rng::Rng;
use dissonance::state::State;

fn flag(a: &[String], n: &str) -> Option<String> {
    a.iter().position(|x| x == n).and_then(|i| a.get(i + 1)).cloned()
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let deals: usize = flag(&args, "--deals").and_then(|s| s.parse().ok()).unwrap_or(400);
    let threads: usize = flag(&args, "--threads")
        .and_then(|s| s.parse().ok())
        .unwrap_or(
            std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4)
                .saturating_sub(1).max(1),
        );
    assert_eq!(NULL_DENOM, 5, "bidding token, not a suit index");

    let per = deals.div_ceil(threads);
    // [lead convention][fewest tricks the declarer can be held to]
    let res: Vec<([[u64; 14]; 2], [u64; 2], [u64; 2], u64)> = std::thread::scope(|sc| {
        let mut hs = Vec::new();
        for t in 0..threads {
            hs.push(sc.spawn(move || {
                let mut dd = Dd::new(20);
                let mut hist = [[0u64; 14]; 2];
                let mut noeven = [0u64; 2];
                // Per-DEAL rather than per-hand: was the bid available to
                // ANYONE at this table? That is the rate that decides how
                // often the rung actually appears in play, and it is not
                // 2x the per-hand rate -- someone must win every even trick,
                // so the two players' chances are anti-correlated, not
                // independent.
                let mut either = [0u64; 2];
                let mut deals_seen = 0u64;
                for i in 0..per {
                    let idx = t * per + i;
                    if idx >= deals {
                        break;
                    }
                    let g = Game::deal(&mut Rng::new(idx as u64 + 1), NOTRUMP, 0);
                    deals_seen += 1;
                    let mut any = [false; 2];
                    for declarer in 0..2usize {
                        for (slot, dl) in [(0usize, true), (1usize, false)] {
                            let s = State {
                                trump: NOTRUMP,
                                trick: 0,
                                led: -1,
                                leader: if dl { declarer as u8 } else { 1 - declarer as u8 },
                                pts: [0, 0],
                                ..g.s
                            };
                            let m = dd.min_even_tricks(&s, declarer).clamp(0, 13) as usize;
                            hist[slot][m] += 1;
                            if dd.null_no_even_makeable(&s, declarer) {
                                noeven[slot] += 1;
                                any[slot] = true;
                            }
                        }
                    }
                    for slot in 0..2 {
                        if any[slot] {
                            either[slot] += 1;
                        }
                    }
                }
                (hist, noeven, either, deals_seen)
            }));
        }
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });

    let mut hist = [[0u64; 14]; 2];
    let mut noeven = [0u64; 2];
    let mut either = [0u64; 2];
    let mut ndeals = 0u64;
    for r in res {
        ndeals += r.3;
        for s in 0..2 {
            noeven[s] += r.1[s];
            either[s] += r.2[s];
            for k in 0..14 {
                hist[s][k] += r.0[s][k];
            }
        }
    }
    let n = (deals * 2) as f64; // two candidate declarers per deal
    println!("deals                 {}", deals);
    println!("hands                 {} (2 per deal)", n as u64);
    println!("\n== NULL variants ==");
    for (slot, label) in [(0usize, "declarer leads"), (1usize, "defender leads")] {
        println!(
            "  no EVEN trick, {:<15}  per hand {:>4}/{:.0} = {:4.1}%   |  per deal, EITHER player {:>4}/{} = {:4.1}%",
            label,
            noeven[slot],
            n,
            100.0 * noeven[slot] as f64 / n,
            either[slot],
            ndeals,
            100.0 * either[slot] as f64 / ndeals as f64
        );
    }
    for (slot, label) in [(0usize, "declarer leads"), (1usize, "defender leads")] {
        println!("\n-- fewest tricks the declarer can be held to, {} --", label);
        let mut cum = 0u64;
        for k in 0..14 {
            if hist[slot][k] == 0 {
                continue;
            }
            cum += hist[slot][k];
            let bar: String = std::iter::repeat('#')
                .take((50.0 * hist[slot][k] as f64 / n).round() as usize)
                .collect();
            // The cumulative column is the one that matters: a contract
            // "take at most K" is available to exactly that fraction of hands.
            println!(
                "  <= {:>2} even   {:>5} ({:5.1}%)   cumulative {:5.1}%  {}",
                k,
                hist[slot][k],
                100.0 * hist[slot][k] as f64 / n,
                100.0 * cum as f64 / n,
                bar
            );
        }
    }
}
