//! Paired-CRN gate: player A vs player B over seat-swapped pairs, all in Rust.
//!
//!   gate_coc <A> <B> <pairs> <sims_a> <sims_b> <seed0> <threads>
//!   player spec: SCAFFOLD | path/to/model.json | path/to/model.json:argmax
//!
//! CRN is EXACT in CoC: the dice stream advances 5 rolls/round regardless of play
//! and the supply is drawn deterministically, so the same seed gives both seat
//! orders identical decks AND dice. Search seeds derive from (game seed, step)
//! only, so A-vs-A is a deterministic mirror = exactly 0.5000 (the sanity control).

use coc_core::engine::{self, State};
use coc_core::netio::pv_from_json;
use coc_core::valuenet::PolicyValueNet;
use coc_core::vsearch;
use std::sync::atomic::{AtomicU64, Ordering};

enum Player {
    Scaffold,
    Net(PolicyValueNet),
    NetArgmax(PolicyValueNet),
}

impl Player {
    fn parse(spec: &str) -> Player {
        if spec == "SCAFFOLD" {
            return Player::Scaffold;
        }
        if let Some(path) = spec.strip_suffix(":argmax") {
            return Player::NetArgmax(pv_from_json(
                &std::fs::read_to_string(path).expect("model"),
            ));
        }
        Player::Net(pv_from_json(&std::fs::read_to_string(spec).expect("model")))
    }

    fn choose(&self, s: &State, sims: u32, seed: u64) -> usize {
        match self {
            Player::Scaffold => vsearch::choose_action_heur(s, sims, seed),
            Player::Net(net) => vsearch::choose_action_pv(net, s, sims, seed),
            Player::NetArgmax(net) => vsearch::choose_action_pv_argmax(net, s, seed),
        }
    }
}

fn play(a: &Player, b: &Player, seed: u64, a_seat: usize, sims_a: u32, sims_b: u32) -> (f64, i32) {
    let pair = (seed % 81) as u8;
    let mut s = State::new_game([pair / 9, pair % 9], seed);
    let mut step = 0u64;
    while !s.is_over() {
        let actor = s.actor() as usize;
        let sseed = seed.wrapping_mul(7919).wrapping_add(step);
        let act = if actor == a_seat {
            a.choose(&s, sims_a, sseed)
        } else {
            b.choose(&s, sims_b, sseed)
        };
        engine::apply(&mut s, act);
        step += 1;
    }
    let scores = s.final_scores();
    let margin = (scores[a_seat] - scores[1 - a_seat]) as i32;
    let win = if s.winner as usize == a_seat { 1.0 } else { 0.0 };
    (win, margin)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 8 {
        eprintln!("usage: gate_coc <A> <B> <pairs> <sims_a> <sims_b> <seed0> <threads>");
        std::process::exit(2);
    }
    let (spec_a, spec_b) = (args[1].clone(), args[2].clone());
    let pairs: u64 = args[3].parse().unwrap();
    let sims_a: u32 = args[4].parse().unwrap();
    let sims_b: u32 = args[5].parse().unwrap();
    let seed0: u64 = args[6].parse().unwrap();
    let threads: usize = args[7].parse().unwrap();

    let wins_milli = AtomicU64::new(0); // wins * 1000 to stay integer
    let margin_sum = AtomicU64::new(0); // offset +10000 per game
    let done = AtomicU64::new(0);
    std::thread::scope(|scope| {
        for t in 0..threads {
            let (spec_a, spec_b) = (spec_a.clone(), spec_b.clone());
            let (wins, margins, done) = (&wins_milli, &margin_sum, &done);
            scope.spawn(move || {
                let a = Player::parse(&spec_a);
                let b = Player::parse(&spec_b);
                let mut g = t as u64;
                while g < pairs {
                    let seed = seed0 + g;
                    for a_seat in 0..2 {
                        let (w, m) = play(&a, &b, seed, a_seat, sims_a, sims_b);
                        wins.fetch_add((w * 1000.0) as u64, Ordering::Relaxed);
                        margins.fetch_add((m + 10000) as u64, Ordering::Relaxed);
                    }
                    let d = done.fetch_add(1, Ordering::Relaxed) + 1;
                    if d % 25 == 0 {
                        eprintln!("{d}/{pairs} pairs...");
                    }
                    g += threads as u64;
                }
            });
        }
    });
    let n = (pairs * 2) as f64;
    let wr = wins_milli.load(Ordering::Relaxed) as f64 / 1000.0 / n;
    let avg_margin = margin_sum.load(Ordering::Relaxed) as f64 / n - 10000.0;
    let se = (wr * (1.0 - wr) / n).sqrt();
    println!(
        "gate: A={spec_a} (sims {sims_a}) vs B={spec_b} (sims {sims_b}): {wr:.4} +-{:.3} (n={}), avg margin {avg_margin:+.1}",
        1.96 * se,
        n as u64
    );
}
