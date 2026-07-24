//! storage_arena — does the champion OVER-HOLD storage into phase ends? (CoB
//! strategy literature: "never carry tiles between phases"; unplaced tiles at a
//! phase boundary are wasted actions. The heuristic baseline's W_STORAGE term is
//! POSITIVE — it rewards holding storage — a candidate mispricing the net
//! inherits via Group E.)
//!
//! DECISIVE test, no retrain: a copy of the champion whose leaf value is
//! PENALIZED for holding storage in the last rounds of a phase (round 4-5, when
//! carryover risk is real), vs the normal champion, paired-CRN. If penalizing
//! end-phase storage makes it STRONGER (>0.50), the champion over-holds (a
//! fixable mispricing). If <=0.50, its storage timing was already correct.
//!
//!   storage_arena <model.json> <pairs> <sims> <seed0> <w-penalty>

use coc_core::engine::{self, State};
use coc_core::mcts::Search;
use coc_core::netio;
use coc_core::rng::Rng;
use coc_core::valuenet::PvEval;
use coc_core::vsearch;

/// Most-visited pick; the PV leaf value is PENALIZED by `w` for holding storage
/// in rounds 4-5 (w=0 => normal champion). Symmetric (rewards the OPPONENT
/// holding end-phase storage), so it isolates "should end-phase storage be
/// valued less" without a first-player artifact.
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
    // end-phase weight: round 5 = full, round 4 = half, earlier = none (holding
    // storage mid-phase is fine — you're about to place it).
    let end_factor = |round: u8| -> f64 {
        match round {
            5 => 1.0,
            4 => 0.5,
            _ => 0.0,
        }
    };
    let eval = |st: &State, actor: usize, lg: &[usize], _r: &mut Rng| {
        let (p, v) = vsearch::pv_eval(net, st, actor, lg);
        let ef = end_factor(st.round);
        let my_pen = st.players[actor].storage_len() as f64 / 3.0 * ef;
        let opp_pen = st.players[1 - actor].storage_len() as f64 / 3.0 * ef;
        let vv = (v - w * my_pen + w * opp_pen).clamp(-1.0, 1.0);
        (p, vv)
    };
    for _ in 0..sims {
        search.sim(&mut rng, &eval);
    }
    let visits = search.root_visits();
    *legal.iter().max_by_key(|&&a| visits[a]).expect("nonempty")
}

/// Returns (biased_won, margin, biased_end_phase_storage_tiles).
fn play(net: &dyn PvEval, biased_seat: usize, deck_seed: u64, sims: u32, w: f64) -> (bool, i32, u32) {
    let pair = (deck_seed % 81) as u8;
    let mut s = State::new_game([pair / 9, pair % 9], deck_seed);
    let mut end_store = 0u32;
    let mut guard = 0u32;
    while !s.is_over() && guard < 4000 {
        guard += 1;
        // count biased side's storage held at the moment round 5 turns end
        let legal = engine::legal_actions(&s);
        if legal.len() == 1 {
            engine::apply(&mut s, legal[0]);
            continue;
        }
        let seat = s.actor() as usize;
        let sd = deck_seed ^ (guard as u64).wrapping_mul(0x9E37_79B9);
        let bias = if seat == biased_seat { w } else { 0.0 };
        // sample end-phase storage: on the biased side's round-5 turn-start
        if seat == biased_seat && s.round == 5 {
            end_store += s.players[biased_seat].storage_len() as u32;
        }
        let a = biased_pick(net, &s, sims, sd, bias);
        engine::apply(&mut s, a);
    }
    let margin = s.players[biased_seat].vp as i32 - s.players[1 - biased_seat].vp as i32;
    (s.winner == biased_seat as i8, margin, end_store)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 6 {
        eprintln!("usage: storage_arena <model.json> <pairs> <sims> <seed0> <w-penalty>");
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
    let mut store_sum = 0u64;
    for p in 0..pairs {
        let deck = seed0.wrapping_add(p.wrapping_mul(0x1_0001));
        for &bseat in &[0usize, 1usize] {
            let (won, margin, es) = play(&net, bseat, deck, sims, w);
            if won {
                wins += 1;
            }
            margin_sum += margin as i64;
            store_sum += es as u64;
            games += 1;
        }
    }
    let wr = wins as f64 / games as f64;
    let se = (wr * (1.0 - wr) / games as f64).sqrt();
    println!("=== storage_arena: END-PHASE-STORAGE-PENALIZED (w={}) vs NORMAL champion ({} games @ {} sims, CRN) ===", w, games, sims);
    println!("penalized win rate: {:.4} +-{:.3}  (avg margin {:+.1})", wr, 1.96 * se, margin_sum as f64 / games as f64);
    println!("biased side round-5 storage tiles summed: {} ({:.3}/game) -- mechanism check (should DROP vs w=0)", store_sum, store_sum as f64 / games as f64);
    println!(">0.50 => penalizing end-phase storage HELPS (champion over-holds, lit right); <=0.50 => storage timing already correct");
}
