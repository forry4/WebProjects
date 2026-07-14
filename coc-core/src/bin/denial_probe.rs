//! denial_probe — does the champion value REGRET-denial?
//!
//! Denial value (user's model) = the opponent's REGRET: how much their
//! best-response degrades when you take the tile, NOT the tile's value to you.
//! It's highest when the opponent is dice-constrained (e.g. rolled 5,5 and
//! depot 5 is their only productive 5-use). CoC makes this a PERFECT-INFO
//! tactic: `_begin_round` rolls everyone's dice at once, so at the start
//! player's turn the opponent's whole roll is visible.
//!
//! Method (bot-vs-bot, no human data): play champion self-play. At each
//! START-PLAYER turn-start (round_order[0], all dice unused), for every depot
//! the opponent could use (they hold a matching die), measure
//!     regret(tile) = opp_turn_value(tile present) - opp_turn_value(tile denied)
//! via two shallow searches of the opponent's turn (END_TURN hands them the
//! board with their known dice; toggling the tile isolates its denial value —
//! the start player's own gain is excluded on purpose). Then let the champion
//! play its real turn and record whether it TOOK the highest-regret tile.
//! Output: champion take-rate bucketed by regret. A low take-rate on
//! high-regret tiles = the confirmed blind spot (and the metric for a
//! regret-denial league opponent).
//!
//!   denial_probe <model.json> <games> <play_sims> <regret_sims> <seed0>

use coc_core::engine::{self, Micro, Pending, State, A_END_TURN};
use coc_core::netio;
use coc_core::vsearch;

/// Opponent's searched turn value from THEIR perspective (root actor = opponent
/// after the start player's END_TURN). Higher = better for the opponent.
fn opp_value(net: &dyn coc_core::valuenet::PvEval, s: &State, sims: u32, seed: u64) -> f64 {
    let (_, v) = vsearch::root_readout_pv(net, s, sims, vsearch::C_PUCT, seed);
    v
}

fn count_code(depot: &[u16; 2], code: u16) -> usize {
    depot.iter().filter(|&&t| t == code).count()
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 6 {
        eprintln!("usage: denial_probe <model.json> <games> <play_sims> <regret_sims> <seed0>");
        std::process::exit(2);
    }
    let model = std::fs::read_to_string(&args[1]).expect("model json");
    let net = netio::pv_from_json(&model);
    let games: u64 = args[2].parse().unwrap();
    let play_sims: u32 = args[3].parse().unwrap();
    let regret_sims: u32 = args[4].parse().unwrap();
    let seed0: u64 = args[5].parse().unwrap();

    // regret buckets: [0,.05) [.05,.1) [.1,.2) [.2,.4) [.4,inf)  -> (opportunities, taken)
    let edges = [0.05_f64, 0.10, 0.20, 0.40];
    let mut opps = [0u64; 5];
    let mut taken = [0u64; 5];
    let bucket = |r: f64| -> usize { edges.iter().position(|&e| r < e).unwrap_or(4) };

    // pending probe carried across the start player's (multi-move) turn
    struct Probe {
        start_seat: u8,
        depot: usize,
        code: u16,
        precount: usize,
        regret: f64,
    }

    for g in 0..games {
        let pair = (g % 81) as u8;
        let mut s = State::new_game([pair / 9, pair % 9], seed0.wrapping_add(g.wrapping_mul(0x9E37_79B9)));
        let mut probe: Option<Probe> = None;
        let mut guard = 0u32;
        while !s.is_over() && guard < 4000 {
            guard += 1;
            let legal = engine::legal_actions(&s);
            if legal.len() == 1 {
                engine::apply(&mut s, legal[0]);
                continue;
            }
            let actor = s.actor() as usize;

            // finalize a pending probe the instant the start player's turn ends
            if let Some(p) = &probe {
                if actor as u8 != p.start_seat {
                    let now = count_code(&s.depot_hex[p.depot], p.code);
                    let b = bucket(p.regret);
                    opps[b] += 1;
                    if now < p.precount {
                        taken[b] += 1;
                    }
                    probe = None;
                }
            }

            // arm a probe at the START player's clean turn-start
            let turn_start = matches!(s.micro, Micro::None)
                && s.pending == Pending::None
                && actor as u8 == s.round_order[0]
                && s.dice[actor].iter().all(|d| !d.used && !d.adjusted);
            if probe.is_none() && turn_start && engine::legal_actions_full(&s).contains(&A_END_TURN) {
                let opp = 1 - actor;
                let opp_dice: Vec<u8> = s.dice[opp]
                    .iter()
                    .filter(|d| !d.used)
                    .map(|d| d.value)
                    .collect();
                // opp-to-move base: start player ends without acting
                let mut base = s.clone();
                engine::apply(&mut base, A_END_TURN);
                if base.actor() as usize == opp && !base.is_over() {
                    let va = opp_value(&net, &base, regret_sims, seed0 ^ 0xA1);
                    let mut best_regret = 0.0_f64;
                    let mut best: Option<(usize, u16)> = None;
                    for d in 0..6usize {
                        if !opp_dice.contains(&((d as u8) + 1)) {
                            continue; // opponent can't use this depot
                        }
                        // each distinct tile in the depot
                        for slot in 0..2usize {
                            let code = base.depot_hex[d][slot];
                            if code == 0 {
                                continue;
                            }
                            let mut b2 = base.clone();
                            // deny: remove this tile, keeping the depot COMPACT
                            // (zeros only at the end — the engine invariant; a
                            // hole like [0, X] breaks arr_len/arr_remove).
                            if slot == 0 {
                                b2.depot_hex[d] = [b2.depot_hex[d][1], 0];
                            } else {
                                b2.depot_hex[d][1] = 0;
                            }
                            let vb = opp_value(&net, &b2, regret_sims, seed0 ^ 0xB2 ^ ((d as u64) << 8) ^ slot as u64);
                            let regret = va - vb; // opp perspective; >0 = tile helps opp
                            if regret > best_regret {
                                best_regret = regret;
                                best = Some((d, code));
                            }
                        }
                    }
                    if let Some((d, code)) = best {
                        probe = Some(Probe {
                            start_seat: actor as u8,
                            depot: d,
                            code,
                            precount: count_code(&s.depot_hex[d], code),
                            regret: best_regret,
                        });
                    }
                }
            }

            // champion's real move
            let a = vsearch::choose_action_pv(&net, &s, play_sims, seed0 ^ (guard as u64));
            engine::apply(&mut s, a);
        }
    }

    println!("=== denial_probe: champion regret-denial take-rate ===");
    println!("regret bucket        opportunities   taken   take-rate");
    let labels = ["[0,.05)", "[.05,.1)", "[.1,.2)", "[.2,.4)", "[.4,+)"];
    for i in 0..5 {
        let rate = if opps[i] > 0 { taken[i] as f64 / opps[i] as f64 } else { 0.0 };
        println!("{:<16} {:>12}   {:>6}   {:.3}", labels[i], opps[i], taken[i], rate);
    }
    let hi_o: u64 = opps[3] + opps[4];
    let hi_t: u64 = taken[3] + taken[4];
    println!(
        "HIGH-REGRET (>=.2): {} opportunities, take-rate {:.3}  <- the blind-spot signal",
        hi_o,
        if hi_o > 0 { hi_t as f64 / hi_o as f64 } else { 0.0 }
    );
}
