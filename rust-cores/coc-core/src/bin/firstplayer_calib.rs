//! firstplayer_calib — is the champion's VALUE HEAD mis-calibrated for the FIRST
//! player at the START of a new phase? (user's persistent claim: the AI
//! undervalues being first-player early into a new phase, when you get first
//! pick of the freshly-refilled depots + black depot.)
//!
//! NON-forcing test (unlike the biased arenas): play champion self-play, and at
//! each PHASE-START turn (round 1, clean turn-start, actor = round_order[0] = the
//! first player) record the search ROOT VALUE (what the net THINKS the first
//! player's position is worth) and the eventual outcome. Then compare, per phase,
//!   predicted P(first player wins) = (value+1)/2   vs   actual first-player win rate.
//! If ACTUAL >> PREDICTED at phase start (while a MID-phase control is calibrated),
//! the net under-prices first-player-at-phase-start — exactly the user's claim,
//! and immune to the reverse-causation that inflated the raw 0.63 correlation.
//!
//!   firstplayer_calib <model.json> <games> <sims> <threads> <seed0>

use coc_core::engine::{self, Micro, Pending, State};
use coc_core::netio;
use coc_core::valuenet::PvEval;
use coc_core::vsearch;
use std::sync::atomic::{AtomicU64, Ordering};

#[derive(Default, Clone)]
struct Acc {
    // per phase 0..4: (count, sum predicted P(win), sum actual win) for phase-start first player
    n: [u64; 5],
    pred: [f64; 5],
    act: [f64; 5],
    // mid-phase (round 3) first-player control
    mid_n: u64,
    mid_pred: f64,
    mid_act: f64,
}

fn run(net: &dyn PvEval, sims: u32, seed0: u64, queue: &AtomicU64, total: u64) -> Acc {
    let mut a = Acc::default();
    loop {
        let g = queue.fetch_add(1, Ordering::Relaxed);
        if g >= total {
            break;
        }
        let seed = seed0.wrapping_add(g.wrapping_mul(0x9E37_79B9));
        let pair = (g % 81) as u8;
        let mut s = State::new_game([pair / 9, pair % 9], seed);
        // records: (phase, first_player_seat, value) for phase starts; (seat,value) for mid
        let mut recs: Vec<(usize, usize, f64)> = Vec::new();
        let mut mid: Vec<(usize, f64)> = Vec::new();
        let mut prev_phase = 255usize;
        let mut mid_phase_seen = 255usize;
        let mut guard = 0u32;
        while !s.is_over() && guard < 4000 {
            guard += 1;
            let legal = engine::legal_actions(&s);
            if legal.len() == 1 {
                engine::apply(&mut s, legal[0]);
                continue;
            }
            let actor = s.actor() as usize;
            let sd = seed ^ (guard as u64).wrapping_mul(0x9E37_79B9);
            let clean = matches!(s.micro, Micro::None) && s.pending == Pending::None;
            let is_phase_start = clean
                && s.round == 1
                && s.phase as usize != prev_phase
                && actor == s.round_order[0] as usize;
            let is_mid = clean
                && s.round == 3
                && s.phase as usize != mid_phase_seen
                && actor == s.round_order[0] as usize;
            // the play search doubles as the recorded value (root value = net's belief)
            let (visits, value) = vsearch::root_readout_pv(net, &s, sims, vsearch::C_PUCT, sd);
            if is_phase_start && s.phase >= 1 {
                // skip phase A (symmetric opening); value is first player's perspective
                recs.push((s.phase as usize, actor, value));
                prev_phase = s.phase as usize;
            }
            if is_mid && s.phase >= 1 {
                mid.push((actor, value));
                mid_phase_seen = s.phase as usize;
            }
            let mv = *legal.iter().max_by_key(|&&x| visits[x]).unwrap();
            engine::apply(&mut s, mv);
        }
        let winner = s.winner;
        for (ph, seat, v) in recs {
            a.n[ph] += 1;
            a.pred[ph] += (v + 1.0) / 2.0;
            a.act[ph] += (winner == seat as i8) as u64 as f64;
        }
        for (seat, v) in mid {
            a.mid_n += 1;
            a.mid_pred += (v + 1.0) / 2.0;
            a.mid_act += (winner == seat as i8) as u64 as f64;
        }
    }
    a
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 6 {
        eprintln!("usage: firstplayer_calib <model.json> <games> <sims> <threads> <seed0>");
        std::process::exit(2);
    }
    let net = netio::pv_from_json(&std::fs::read_to_string(&args[1]).expect("model"));
    let games: u64 = args[2].parse().unwrap();
    let sims: u32 = args[3].parse().unwrap();
    let threads: usize = args[4].parse().unwrap();
    let seed0: u64 = args[5].parse().unwrap();
    let queue = AtomicU64::new(0);
    let accs: Vec<Acc> = std::thread::scope(|sc| {
        let hs: Vec<_> = (0..threads)
            .map(|_| {
                let netref: &dyn PvEval = &net;
                let qref = &queue;
                sc.spawn(move || run(netref, sims, seed0, qref, games))
            })
            .collect();
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });
    let mut a = Acc::default();
    for x in &accs {
        for p in 0..5 {
            a.n[p] += x.n[p];
            a.pred[p] += x.pred[p];
            a.act[p] += x.act[p];
        }
        a.mid_n += x.mid_n;
        a.mid_pred += x.mid_pred;
        a.mid_act += x.mid_act;
    }
    println!("=== firstplayer_calib: value-head calibration for the phase-start FIRST player ===");
    println!("({games} games @ {sims} sims; phases B-E; predicted=(V+1)/2 vs actual first-player win rate)");
    println!("phase      n      predicted   actual    delta(act-pred)");
    let labels = ["A", "B", "C", "D", "E"];
    let mut tot_n = 0u64;
    let mut tot_p = 0.0;
    let mut tot_a = 0.0;
    for p in 1..5 {
        if a.n[p] == 0 {
            continue;
        }
        let pr = a.pred[p] / a.n[p] as f64;
        let ac = a.act[p] / a.n[p] as f64;
        let se = (ac * (1.0 - ac) / a.n[p] as f64).sqrt();
        println!(
            "  {}     {:>6}      {:.4}     {:.4}     {:+.4} +-{:.4}",
            labels[p], a.n[p], pr, ac, ac - pr, 1.96 * se
        );
        tot_n += a.n[p];
        tot_p += a.pred[p];
        tot_a += a.act[p];
    }
    let pr = tot_p / tot_n as f64;
    let ac = tot_a / tot_n as f64;
    let se = (ac * (1.0 - ac) / tot_n as f64).sqrt();
    println!(
        "  B-E   {:>6}      {:.4}     {:.4}     {:+.4} +-{:.4}   <- phase-start first-player calibration",
        tot_n, pr, ac, ac - pr, 1.96 * se
    );
    let mpr = a.mid_pred / a.mid_n.max(1) as f64;
    let mac = a.mid_act / a.mid_n.max(1) as f64;
    let mse = (mac * (1.0 - mac) / a.mid_n.max(1) as f64).sqrt();
    println!(
        "  MID   {:>6}      {:.4}     {:.4}     {:+.4} +-{:.4}   <- round-3 first-player CONTROL",
        a.mid_n, mpr, mac, mac - mpr, 1.96 * mse
    );
    println!("\ndelta >> 0 at phase-start (but ~0 for MID control) => net UNDER-values first-player-at-phase-start (user right).");
    println!("delta ~ 0 => value head is calibrated; the first-player advantage is already correctly priced.");
}
