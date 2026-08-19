//! What an AUCTION costs the Hard tier, in search nodes.
//!
//! Nodes, not milliseconds: this box swings ~2.5x on identical work, which is
//! enough to invent a win that is not there (it invented a 14% one once). The
//! node count is exact and the two are proportional.
//!
//! The sequence measured is the real one. A classic seat cannot re-bid a
//! denomination it has already named, so the denominations its options span
//! shrink as the auction runs — 5, then 4, then 3, then 2 on its four turns.
use dissonance::bid::{price, solve_into, Option_, Solved};
use dissonance::dd::Dd;
use dissonance::game::Game;
use dissonance::rng::Rng;
use dissonance::view::View;

/// The denominations a classic seat's options span on each of its own turns.
const AUCTION: [u8; 4] = [0b11111, 0b01111, 0b00111, 0b00011];

fn main() {
    let deals: usize = std::env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(12);
    let k = 3usize;

    let opts: Vec<Option_> = (0..5)
        // The shipped level-3 classic terms, from the crate's one copy: this
        // line carried `make: 19, over: 0, set_base: 13` -- the pre-2026-08-16
        // price list -- while claiming to bench the shipped bidder.
        .map(|d| Option_ { denom: d, target: 3, make: 3 * 3 + 4, over: 1, set_base: 2 * 3 + 2, short: 5, ramp: 0, null: 20,
                  opp: false, redeal: false })
        .collect();

    // Identified by the set asked for (shipped) vs. by the HAND, with the set
    // asked for a query against it.
    for &(subset, label) in &[(false, "cache keyed on the set asked for (was)"),
                              (true, "cache keyed on the HAND (now)")] {
        let mut nodes = [0u64; AUCTION.len()];
        for seed in 0..deals as u64 {
            let g = Game::deal(&mut Rng::new(seed), 0, 0);
            let v = View::of(&g, 0);
            let mut dd = Dd::new(18);
            let mut rng = Rng::new(99);
            let mut cache = Solved::default();
            for (turn, &wanted) in AUCTION.iter().enumerate() {
                if !subset {
                    // A different key is a different entry: nothing is reused.
                    cache = Solved::default();
                    rng = Rng::new(99);
                }
                let n0 = dd.nodes;
                solve_into(&v, &mut dd, &mut rng, k, wanted, 0, 0, &mut cache, None, false);
                let _ = price(&opts, &cache.worlds, cache.covered, cache.covered_opp, false);
                nodes[turn] += dd.nodes - n0;
            }
        }
        let n = deals as f64;
        let total: f64 = nodes.iter().sum::<u64>() as f64 / n;
        println!("\n{label}");
        println!("  per turn: {}", nodes.iter()
            .map(|x| format!("{:.0}k", *x as f64 / n / 1e3)).collect::<Vec<_>>().join("  "));
        println!("  whole auction: {:.0}k nodes", total / 1e3);
    }
}
