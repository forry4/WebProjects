//! firstplayer_arena — does WEIGHTING first-player (turn-track position) more
//! heavily make the champion STRONGER? (user question B; the audit already
//! showed first-in-more-phases wins ~0.63, dose-dependent.) A copy of the
//! champion with its leaf value biased toward a turn-track LEAD (higher
//! track_pos => first player), vs the normal champion, paired-CRN. If biasing
//! toward first-player HELPS (>0.50), the champion under-weights tempo/first-
//! player (user right, a real lever). If <=0.50, it already weights it correctly.
//!
//!   firstplayer_arena <model.json> <pairs> <sims> <seed0> <w-bias>

use coc_core::engine::{self, State, NUM_TRACK_SPACES, PLAYING};
use coc_core::mcts::Search;
use coc_core::netio;
use coc_core::rng::Rng;
use coc_core::valuenet::PvEval;
use coc_core::vsearch;

/// Value-biased pick: reward the actor for a turn-track LEAD (secures first
/// player). w=0 => normal champion.
fn biased_pick(net: &dyn PvEval, s: &State, sims: u32, seed: u64, w: f64) -> usize {
    let legal = engine::legal_actions(s);
    if legal.len() == 1 {
        return legal[0];
    }
    if w == 0.0 {
        let (visits, _) = vsearch::root_readout_pv(net, s, sims, vsearch::C_PUCT, seed);
        return *legal.iter().max_by_key(|&&a| visits[a]).expect("nonempty");
    }
    let mut search = Search::new(s.clone(), vsearch::C_PUCT);
    let mut rng = Rng::new(seed ^ 0x9E77);
    let eval = |st: &State, actor: usize, lg: &[usize], _r: &mut Rng| {
        let (p, v) = vsearch::pv_eval(net, st, actor, lg);
        // signed track lead in [-1,1]: ahead => first player next phase
        let lead = (st.track_pos[actor] as f64 - st.track_pos[1 - actor] as f64)
            / NUM_TRACK_SPACES as f64;
        let vv = (v + w * lead).clamp(-1.0, 1.0);
        (p, vv)
    };
    for _ in 0..sims {
        search.sim(&mut rng, &eval);
    }
    let visits = search.root_visits();
    *legal.iter().max_by_key(|&&a| visits[a]).expect("nonempty")
}

/// Returns (biased_won, margin, biased_first_player_phases).
fn play(net: &dyn PvEval, biased_seat: usize, deck_seed: u64, sims: u32, w: f64) -> (bool, i32, u32) {
    let pair = (deck_seed % 81) as u8;
    let mut s = State::new_game([pair / 9, pair % 9], deck_seed);
    let mut fp_biased = 0u32;
    let mut prev_phase = 255u8;
    let mut guard = 0u32;
    while !s.is_over() && guard < 4000 {
        guard += 1;
        if s.mode == PLAYING && s.phase != prev_phase {
            if s.round_order[0] as usize == biased_seat {
                fp_biased += 1;
            }
            prev_phase = s.phase;
        }
        let legal = engine::legal_actions(&s);
        if legal.len() == 1 {
            engine::apply(&mut s, legal[0]);
            continue;
        }
        let seat = s.actor() as usize;
        let sd = deck_seed ^ (guard as u64).wrapping_mul(0x9E37_79B9);
        let bias = if seat == biased_seat { w } else { 0.0 };
        let a = biased_pick(net, &s, sims, sd, bias);
        engine::apply(&mut s, a);
    }
    let margin = s.players[biased_seat].vp as i32 - s.players[1 - biased_seat].vp as i32;
    (s.winner == biased_seat as i8, margin, fp_biased)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 6 {
        eprintln!("usage: firstplayer_arena <model.json> <pairs> <sims> <seed0> <w-bias>");
        std::process::exit(2);
    }
    let net = netio::pv_from_json(&std::fs::read_to_string(&args[1]).expect("model"));
    let pairs: u64 = args[2].parse().unwrap();
    let sims: u32 = args[3].parse().unwrap();
    let seed0: u64 = args[4].parse().unwrap();
    let w: f64 = args[5].parse().unwrap();

    let mut wins = 0u64;
    let mut games = 0u64;
    let mut margin_sum = 0i64;
    let mut fp_sum = 0u64;

    for p in 0..pairs {
        let deck = seed0.wrapping_add(p.wrapping_mul(0x1_0001));
        for &bseat in &[0usize, 1usize] {
            let (won, margin, fp) = play(&net, bseat, deck, sims, w);
            if won {
                wins += 1;
            }
            margin_sum += margin as i64;
            fp_sum += fp as u64;
            games += 1;
        }
    }
    let wr = wins as f64 / games as f64;
    let se = (wr * (1.0 - wr) / games as f64).sqrt();
    println!("=== firstplayer_arena: track-lead-BIASED (w={}) vs NORMAL champion ({} games @ {} sims, CRN) ===", w, games, sims);
    println!("biased win rate: {:.4} +-{:.3}  (avg margin {:+.1})", wr, 1.96 * se, margin_sum as f64 / games as f64);
    println!("biased side avg first-player phases/game: {:.2} (of ~5; >2.5 => the bias secured more first-player)", fp_sum as f64 / games as f64);
    println!(">0.50 => weighting first-player HELPS (champion under-weights it, user right); <=0.50 => already correct");
}
