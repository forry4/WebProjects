//! ship_timing_arena — the user's surgical tempo tactic: "hold ships until the
//! LAST round of a phase to lock next-phase first-player" (advance after the
//! opponent's last chance to re-pass). Placing a ship advances the track by 1
//! (the only track-advance in the game), so this forces the biased champion to
//! NOT place ships in rounds 1-4 (hold them in storage) and let round 5 be when
//! they land — vs the normal champion, paired-CRN. If the timing HELPS (>0.50),
//! the champion mis-times ship placement (user right, a real tempo lever). If
//! <=0.50, its natural timing was already right.
//!
//!   ship_timing_arena <model.json> <pairs> <sims> <seed0>

use coc_core::engine::{self, State, A_PLACE_SLOT0, PLAYING};
use coc_core::netio;
use coc_core::tiles::T_SHIP;
use coc_core::valuenet::PvEval;
use coc_core::vsearch;

/// If `hold` and it's not the last round, refuse to PLACE a ship from storage
/// (pick the best NON-ship-placement instead); else normal most-visited pick.
fn timed_pick(net: &dyn PvEval, s: &State, sims: u32, seed: u64, hold: bool) -> usize {
    let legal = engine::legal_actions(s);
    if legal.len() == 1 {
        return legal[0];
    }
    let (visits, _) = vsearch::root_readout_pv(net, s, sims, vsearch::C_PUCT, seed);
    let seat = s.actor() as usize;
    if hold && s.round < 5 {
        let ship_place = |a: usize| -> bool {
            (A_PLACE_SLOT0..A_PLACE_SLOT0 + 3).contains(&a)
                && s.players[seat].storage.get(a - A_PLACE_SLOT0).copied() == Some(T_SHIP)
        };
        // only intervene if we actually hold a ship AND a ship-placement is on offer
        if s.players[seat].storage.iter().any(|&c| c == T_SHIP)
            && legal.iter().any(|&a| ship_place(a))
        {
            if let Some(&a) = legal.iter().filter(|&&a| !ship_place(a)).max_by_key(|&&a| visits[a]) {
                return a;
            }
        }
    }
    *legal.iter().max_by_key(|&&a| visits[a]).expect("nonempty")
}

/// (biased_won, margin, biased_ship_advances_in_round5, biased_ship_advances_total)
fn play(net: &dyn PvEval, biased_seat: usize, deck_seed: u64, sims: u32) -> (bool, i32, u32, u32) {
    let pair = (deck_seed % 81) as u8;
    let mut s = State::new_game([pair / 9, pair % 9], deck_seed);
    let mut adv_r5 = 0u32;
    let mut adv_tot = 0u32;
    let mut guard = 0u32;
    while !s.is_over() && guard < 4000 {
        guard += 1;
        let legal = engine::legal_actions(&s);
        if legal.len() == 1 {
            engine::apply(&mut s, legal[0]);
            continue;
        }
        let seat = s.actor() as usize;
        let sd = deck_seed ^ (guard as u64).wrapping_mul(0x9E37_79B9);
        let before = s.track_pos[biased_seat];
        let round = s.round;
        let playing = s.mode == PLAYING;
        let a = timed_pick(net, &s, sims, sd, seat == biased_seat);
        engine::apply(&mut s, a);
        if playing && s.track_pos[biased_seat] > before {
            adv_tot += 1;
            if round == 5 {
                adv_r5 += 1;
            }
        }
    }
    let margin = s.players[biased_seat].vp as i32 - s.players[1 - biased_seat].vp as i32;
    (s.winner == biased_seat as i8, margin, adv_r5, adv_tot)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 5 {
        eprintln!("usage: ship_timing_arena <model.json> <pairs> <sims> <seed0>");
        std::process::exit(2);
    }
    let net = netio::pv_from_json(&std::fs::read_to_string(&args[1]).expect("model"));
    let pairs: u64 = args[2].parse().unwrap();
    let sims: u32 = args[3].parse().unwrap();
    let seed0: u64 = args[4].parse().unwrap();

    let mut wins = 0u64;
    let mut games = 0u64;
    let mut margin_sum = 0i64;
    let mut r5 = 0u64;
    let mut tot = 0u64;

    for p in 0..pairs {
        let deck = seed0.wrapping_add(p.wrapping_mul(0x1_0001));
        for &bseat in &[0usize, 1usize] {
            let (won, margin, a5, at) = play(&net, bseat, deck, sims);
            if won {
                wins += 1;
            }
            margin_sum += margin as i64;
            r5 += a5 as u64;
            tot += at as u64;
            games += 1;
        }
    }
    let wr = wins as f64 / games as f64;
    let se = (wr * (1.0 - wr) / games as f64).sqrt();
    println!("=== ship_timing_arena: HOLD-SHIPS-TILL-ROUND-5 vs NORMAL champion ({} games @ {} sims, CRN) ===", games, sims);
    println!("timed win rate: {:.4} +-{:.3}  (avg margin {:+.1})", wr, 1.96 * se, margin_sum as f64 / games as f64);
    println!("biased ship-advances in round 5: {}/{} ({:.3}) -- mechanism check (should be HIGH vs the natural rate)", r5, tot, r5 as f64 / tot.max(1) as f64);
    println!(">0.50 => last-round ship timing HELPS (champion mis-times ships, user right); <=0.50 => natural timing was correct");
}
