//! m6_arena — is monastery-6 UNDER-valued? (user: "M6 is the best tile, should
//! be bought 100%"; the audit shows the champion buys it ~65% of available
//! games.) DECISIVE test, no retrain: a copy of the champion FORCED to acquire
//! M6 whenever it can, vs the normal champion, paired-CRN. If forcing M6 makes
//! it STRONGER, the net under-values M6 (user right, a fixable calibration
//! blind spot). If weaker/equal, the champion's selectivity was correct.
//!
//!   m6_arena <model.json> <pairs> <sims> <seed0>

use coc_core::engine::{self, State};
use coc_core::mcts::Search;
use coc_core::netio;
use coc_core::rng::Rng;
use coc_core::valuenet::PvEval;
use coc_core::vsearch;

const M6_BIT: u32 = 5; // monastery effect_id 6 -> mon_mask bit 5
const M6_CODE: u16 = 27; // monastery effect_id 6 -> tile code (T_MONASTERY0=22 + 6 - 1)

/// Most-visited pick with the PV leaf VALUE-BIASED by `w6` toward owning M6
/// (w6=0 => normal champion). The bias reshapes the whole search — take, place
/// AND keep M6 — so a high w6 drives ownership toward ~100%, isolating "does
/// valuing M6 more help." Symmetric (also penalizes the OPPONENT owning it).
fn biased_pick(net: &dyn PvEval, s: &State, sims: u32, seed: u64, w6: f64) -> usize {
    let legal = engine::legal_actions(s);
    if legal.len() == 1 {
        return legal[0];
    }
    if w6 == 0.0 {
        let (visits, _) = vsearch::root_readout_pv(net, s, sims, vsearch::C_PUCT, seed);
        return *legal.iter().max_by_key(|&&a| visits[a]).expect("nonempty");
    }
    let mut search = Search::new(s.clone(), vsearch::C_PUCT);
    let mut rng = Rng::new(seed ^ 0x9E77);
    // reward HAVING M6 (owned OR in storage) — storage is ~1-2 plies from the
    // acquisition decision, so the reward is within the search horizon and
    // actually pulls the search toward TAKING M6 (rewarding only the placed
    // end-state was too far ahead to propagate).
    let has_m6 = |pl: &coc_core::engine::PlayerState| -> bool {
        (pl.mon_mask >> M6_BIT) & 1 == 1 || pl.storage.iter().any(|&c| c == M6_CODE)
    };
    let eval = |st: &State, actor: usize, lg: &[usize], _r: &mut Rng| {
        let (p, v) = vsearch::pv_eval(net, st, actor, lg);
        // PHASE-SCALED: M6 is a compounding ability, worth ~(phases left) — so
        // reward owning it EARLY, near-nothing LATE. phase 0=A -> 1.0, 4=E -> 0.2.
        let pl = (5.0 - st.phase as f64) / 5.0;
        let own = has_m6(&st.players[actor]);
        let opp = has_m6(&st.players[1 - actor]);
        let vv = (v + if own { w6 * pl } else { 0.0 } - if opp { w6 * pl } else { 0.0 })
            .clamp(-1.0, 1.0);
        (p, vv)
    };
    for _ in 0..sims {
        search.sim(&mut rng, &eval);
    }
    let visits = search.root_visits();
    *legal.iter().max_by_key(|&&a| visits[a]).expect("nonempty")
}

/// Play one game; forced_seat plays forced_choose, the other plays normal.
/// Returns (forced_won, margin_for_forced, forced_owns_m6).
fn play(net: &dyn PvEval, forced_seat: usize, deck_seed: u64, sims: u32, w6: f64) -> (bool, i32, bool) {
    let pair = (deck_seed % 81) as u8;
    let mut s = State::new_game([pair / 9, pair % 9], deck_seed);
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
        let bias = if seat == forced_seat { w6 } else { 0.0 };
        let a = biased_pick(net, &s, sims, sd, bias);
        engine::apply(&mut s, a);
    }
    let fs = forced_seat;
    let os = 1 - forced_seat;
    let margin = s.players[fs].vp as i32 - s.players[os].vp as i32;
    let won = s.winner == fs as i8;
    let owns = (s.players[fs].mon_mask >> M6_BIT) & 1 == 1;
    (won, margin, owns)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 6 {
        eprintln!("usage: m6_arena <model.json> <pairs> <sims> <seed0> <w6-bias>");
        std::process::exit(2);
    }
    let net = netio::pv_from_json(&std::fs::read_to_string(&args[1]).expect("model"));
    let pairs: u64 = args[2].parse().unwrap();
    let sims: u32 = args[3].parse().unwrap();
    let seed0: u64 = args[4].parse().unwrap();
    let w6: f64 = args[5].parse().unwrap();

    let mut forced_wins = 0u64;
    let mut games = 0u64;
    let mut margin_sum = 0i64;
    let mut forced_m6 = 0u64;

    for p in 0..pairs {
        let deck = seed0.wrapping_add(p.wrapping_mul(0x1_0001));
        // CRN pair: forced=seat0, then forced=seat1, same deck
        for &fseat in &[0usize, 1usize] {
            let (won, margin, owns) = play(&net, fseat, deck, sims, w6);
            if won {
                forced_wins += 1;
            }
            margin_sum += margin as i64;
            if owns {
                forced_m6 += 1;
            }
            games += 1;
        }
    }
    let wr = forced_wins as f64 / games as f64;
    let se = (wr * (1.0 - wr) / games as f64).sqrt();
    println!("=== m6_arena: M6-BIASED (w6={}) champion vs NORMAL champion ({} games @ {} sims, CRN) ===", w6, games, sims);
    println!("biased-M6 win rate: {:.4} +-{:.3}  (avg margin {:+.1})", wr, 1.96 * se, margin_sum as f64 / games as f64);
    println!("biased side ended owning M6: {}/{} ({:.3})", forced_m6, games, forced_m6 as f64 / games as f64);
    println!(">0.50 => valuing M6 more HELPS (net under-values M6, user right); <=0.50 => the champion's 65% was correct");
}
