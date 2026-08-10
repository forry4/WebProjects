//! What does a dummy-mode decision COST? The budget is the same one every
//! other mode's Hard tier lives inside: ~70ms a world at trick 1, four workers,
//! a 12s watchdog. Reports per-decision cost at trick 1 (the widest position of
//! the round) and averaged over a whole round.
//!
//!     cargo run --release --bin dbench

use dissonance::dummy::*;
use std::time::Instant;

fn main() {
    println!("{:>6} {:>8} {:>12} {:>10} {:>12}", "depth", "leaf", "nodes/dec", "ms/dec", "ms/round");
    for leaf in [Leaf::Material, Leaf::Playout] {
        for depth in 1..=4u8 {
            let mut nodes = 0u64;
            let mut decisions = 0u64;
            let mut first_ms = 0.0f64;
            let t0 = Instant::now();
            for seed in 1..4u64 {
                let mut g = deal(seed);
                let mut first = true;
                while !g.done() {
                    // Only the positions a real bot is asked about: the two
                    // its side commands. The defender's answer is a decision
                    // too, so every ply of the round counts.
                    let t = Instant::now();
                    let mut s = Search::new(leaf);
                    let r = s.root(&g, depth);
                    nodes += s.nodes;
                    decisions += 1;
                    if first {
                        first_ms += t.elapsed().as_secs_f64() * 1000.0;
                        first = false;
                    }
                    let best = r
                        .iter()
                        .max_by_key(|x| x.1 as i32)
                        .map(|x| x.0)
                        .unwrap();
                    g.play(best);
                }
            }
            let ms = t0.elapsed().as_secs_f64() * 1000.0;
            println!(
                "{:>6} {:>8} {:>12} {:>10.2} {:>12.0}",
                depth,
                if leaf == Leaf::Material { "material" } else { "playout" },
                nodes / decisions,
                ms / decisions as f64,
                ms / 3.0
            );
            if ms / decisions as f64 > 400.0 {
                println!("        (trick-1 decision alone: {:.0}ms)", first_ms / 3.0);
                break;
            }
        }
    }
}
