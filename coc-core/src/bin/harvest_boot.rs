//! Bootstrap harvest: scaffold (heuristic rollout-leaf PUCT) self-play, recording
//! per searched decision: mover features + root visit distribution + searched root
//! value, then per-game outcome labels. The distill warm-start trains on this.
//!
//!   cargo run --release --bin harvest_boot -- <out_prefix> <games> <sims> <temp_micro> <seed0> <threads>
//!   e.g. harvest_boot C:/Users/Forrest/coc_run/boot 6000 1500 20 0 10
//!
//! Writes <out_prefix>.t<k>.csv per thread. Columns (no header):
//!   game_id, f0..f933, label (1/0 mover won), margin (mover score diff),
//!   value (searched root value, mover perspective), policy ("a:n a:n ..." sparse)
//! Forced (single-legal) decisions are applied without search and NOT recorded.
//! Board pairs cycle uniformly over the 81 combinations; openings are
//! visit-temperature-sampled for the first <temp_micro> searched decisions.

use std::fs::File;
use std::io::{BufWriter, Write};

use coc_core::engine::{self, State};
use coc_core::feats;
use coc_core::rng::Rng;
use coc_core::vsearch;

struct Row {
    actor: usize,
    feats: Vec<f32>,
    policy: String,
    value: f64,
}

fn run_thread(out: &str, t: usize, games: u64, sims: u32, temp_micro: usize, seed0: u64) {
    let path = format!("{out}.t{t}.csv");
    let mut w = BufWriter::new(File::create(&path).expect("create out"));
    let mut rng = Rng::new(seed0 ^ 0xB007_0000 ^ (t as u64) << 32);
    for g in 0..games {
        let seed = seed0 + (t as u64) * games + g;
        let pair = (seed % 81) as u8;
        let mut s = State::new_game([pair / 9, pair % 9], seed);
        let mut rows: Vec<Row> = Vec::with_capacity(200);
        let mut searched = 0usize;
        while !s.is_over() {
            let legal = engine::legal_actions(&s);
            if legal.len() == 1 {
                engine::apply(&mut s, legal[0]);
                continue;
            }
            let actor = s.actor() as usize;
            let (visits, value) =
                vsearch::root_readout_heur(&s, sims, vsearch::C_PUCT, seed.wrapping_mul(977) + searched as u64);
            let mut policy = String::new();
            for &a in &legal {
                if visits[a] > 0 {
                    if !policy.is_empty() {
                        policy.push(' ');
                    }
                    policy.push_str(&format!("{}:{}", a, visits[a]));
                }
            }
            let a = if searched < temp_micro {
                // temperature 1: sample proportional to visits
                let total: i64 = legal.iter().map(|&a| visits[a] as i64).sum();
                let mut pick = (rng.next_u64() % total.max(1) as u64) as i64;
                let mut chosen = legal[0];
                for &la in &legal {
                    pick -= visits[la] as i64;
                    if pick < 0 {
                        chosen = la;
                        break;
                    }
                }
                chosen
            } else {
                *legal.iter().max_by_key(|&&a| visits[a]).unwrap()
            };
            rows.push(Row { actor, feats: feats::features(&s, actor), policy, value });
            engine::apply(&mut s, a);
            searched += 1;
        }
        let scores = s.final_scores();
        for r in &rows {
            let label = if s.winner as usize == r.actor { 1 } else { 0 };
            let margin = scores[r.actor] - scores[1 - r.actor];
            let mut line = String::with_capacity(feats::N_FEATS * 8 + 64);
            line.push_str(&format!("{}", seed));
            for &f in &r.feats {
                line.push_str(&format!(",{}", trim_f(f)));
            }
            line.push_str(&format!(",{label},{margin},{:.4},{}", r.value, r.policy));
            writeln!(w, "{line}").expect("write row");
        }
        if (g + 1) % 100 == 0 {
            eprintln!("[t{t}] {}/{games} games", g + 1);
        }
    }
    w.flush().expect("flush");
    eprintln!("[t{t}] done -> {path}");
}

/// Compact float formatting (5 significant digits, strips zero noise).
fn trim_f(f: f32) -> String {
    if f == 0.0 {
        return "0".to_string();
    }
    if f == 1.0 {
        return "1".to_string();
    }
    format!("{:.5}", f)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 7 {
        eprintln!("usage: harvest_boot <out_prefix> <games> <sims> <temp_micro> <seed0> <threads>");
        std::process::exit(2);
    }
    let out = args[1].clone();
    let games: u64 = args[2].parse().unwrap();
    let sims: u32 = args[3].parse().unwrap();
    let temp_micro: usize = args[4].parse().unwrap();
    let seed0: u64 = args[5].parse().unwrap();
    let threads: usize = args[6].parse().unwrap();
    let per = games / threads as u64;
    std::thread::scope(|scope| {
        for t in 0..threads {
            let out = out.clone();
            scope.spawn(move || run_thread(&out, t, per, sims, temp_micro, seed0));
        }
    });
    eprintln!("harvest complete: {} games total", per * threads as u64);
}
