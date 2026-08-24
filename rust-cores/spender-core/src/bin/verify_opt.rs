//! Zero-risk optimization harness: measures shared mcts/determinize hot-loop throughput AND emits a
//! deterministic fingerprint of the full root-visit vectors, so an allocation-only change can be proven
//! byte-identical (fingerprint unchanged) while faster (sims/s up). Uses the variant-S (v_state) leaf via
//! `root_visits_until` — the leaf is irrelevant here; the point is to exercise `Search::sim`/`determinize`
//! (shared with the attention PV path) with a cheap leaf so per-sim overhead is maximally visible.
//!
//! Usage: cargo run --release --bin verify_opt [sims] [seeds] [reps]

use spender_core::engine;
use spender_core::rng::Rng;
use spender_core::vsearch;
use std::time::Instant;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let sims: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(2000);
    let seeds: u64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(24);
    let reps: usize = args.get(3).and_then(|s| s.parse().ok()).unwrap_or(3);

    // A few structurally-different mid-game positions.
    let positions: Vec<engine::State> = [16u32, 24, 32, 40]
        .iter()
        .map(|&m| vsearch::demo_position(777, m))
        .collect();

    // warmup
    {
        let mut wrng = Rng::new(1);
        let _ = vsearch::root_visits_until(&positions[0], positions[0].turn, &mut wrng, |n| n < 200);
    }

    let mut fp: u64 = 0xcbf29ce484222325; // FNV-ish accumulator, order-sensitive
    let mut total_sims: u64 = 0;
    let t = Instant::now();
    for _rep in 0..reps {
        for (pi, pos) in positions.iter().enumerate() {
            for sd in 0..seeds {
                let mut rng = Rng::new(0x51ED_0000 ^ (sd.wrapping_mul(2654435761)) ^ (pi as u64));
                let visits = vsearch::root_visits_until(pos, pos.turn, &mut rng, |n| n < sims);
                let mut run: u64 = 0;
                for (a, &v) in visits.iter().enumerate() {
                    run = run
                        .wrapping_add((a as u64 + 1).wrapping_mul(v as u64))
                        .rotate_left(1);
                    total_sims += v as u64;
                }
                fp = fp.wrapping_mul(1_000_003).wrapping_add(run);
            }
        }
    }
    let el = t.elapsed().as_secs_f64();
    println!(
        "verify_opt: sims/call={sims} positions={} seeds={seeds} reps={reps}",
        positions.len()
    );
    println!("FINGERPRINT: {fp:016x}");
    println!(
        "THROUGHPUT: {total_sims} sims in {el:.3}s = {:.0} sims/s",
        total_sims as f64 / el
    );
}
