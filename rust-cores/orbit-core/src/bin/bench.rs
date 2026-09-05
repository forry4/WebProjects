//! Native random-play throughput probe, not a strength benchmark.
use orbit_core::{Chance, State};
use std::{hint::black_box, time::Instant};

fn main() {
    let games: u64 = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "1000".into())
        .parse()
        .expect("games");
    let start = Instant::now();
    let mut decisions = 0;
    let mut max_moves = 0;
    let mut turns = 0;
    let mut capped = 0;
    for seed in 0..games {
        let sides = std::array::from_fn(|i| 1 + ((seed >> i) & 1) as i32);
        let (mut g, mut chance) = State::new(seed, sides);
        let mut chooser = Chance::seeded(seed + 8001);
        for step in 0..2000 {
            let Some(pid) = g.actor() else {
                break;
            };
            let moves = g.legal_moves(pid);
            assert!(!moves.is_empty());
            max_moves = max_moves.max(moves.len());
            g.apply(pid, &moves[chooser.index(moves.len())], &mut chance)
                .unwrap();
            decisions += 1;
            black_box(g.clone());
            if step == 1999 && g.phase != "over" {
                capped += 1;
            }
        }
        g.validate().unwrap();
        turns += g.turn_number as u64;
    }
    let elapsed = start.elapsed().as_secs_f64();
    println!(
        "{}",
        serde_json::json!({"games":games,"decisions":decisions,"seconds":elapsed,
        "decisions_per_second":decisions as f64/elapsed,"turns":turns,"max_legal_moves":max_moves,
        "censored_games":capped,"includes_clone_per_decision":true})
    );
}
