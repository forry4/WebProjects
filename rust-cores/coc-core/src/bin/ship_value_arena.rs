//! Does valuing SHIPS + CASTLES more help vs the champion?
//! The net-vs-top-humans analysis found the pros grab ships (+28) and castles
//! (+12) far more than our net. Play the champion with its leaf value biased
//! toward owning MORE ships+castles than the opponent, vs the NORMAL champion,
//! paired-CRN (same decks, seat-swapped). >0.50 => the champion under-values
//! ships/castles (the human edge is forceable); <=0.50 => already priced right
//! for bot-vs-bot (the "strong search already prices the tactic" pattern).
//!
//! Usage: ship_value_arena <model.json> <pairs> <sims> <seed0> <w-bias>
use coc_core::engine::{self, State};
use coc_core::mcts::Search;
use coc_core::netio;
use coc_core::rng::Rng;
use coc_core::tiles::{T_CASTLE, T_SHIP};
use coc_core::valuenet::PvEval;
use coc_core::vsearch;

/// Count of placed ships + (acquired) castles in a seat's duchy.
fn ship_castle(st: &State, seat: usize) -> i32 {
    st.players[seat]
        .duchy
        .iter()
        .filter(|&&c| c == T_SHIP || c == T_CASTLE)
        .count() as i32
}

/// w=0 => normal champion; w>0 => leaf value += w * (my - opp ships+castles)/8.
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
        let adv = (ship_castle(st, actor) - ship_castle(st, 1 - actor)) as f64 / 8.0;
        (p, (v + w * adv).clamp(-1.0, 1.0))
    };
    for _ in 0..sims {
        search.sim(&mut rng, &eval);
    }
    let visits = search.root_visits();
    *legal.iter().max_by_key(|&&a| visits[a]).expect("nonempty")
}

/// Returns (biased_won, margin, biased_ships+castles).
fn play(net: &dyn PvEval, biased_seat: usize, deck_seed: u64, sims: u32, w: f64) -> (bool, i32, i32) {
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
        let bias = if seat == biased_seat { w } else { 0.0 };
        let a = biased_pick(net, &s, sims, sd, bias);
        engine::apply(&mut s, a);
    }
    let margin = s.players[biased_seat].vp as i32 - s.players[1 - biased_seat].vp as i32;
    (s.winner == biased_seat as i8, margin, ship_castle(&s, biased_seat))
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 6 {
        eprintln!("usage: ship_value_arena <model.json> <pairs> <sims> <seed0> <w-bias>");
        std::process::exit(2);
    }
    let net = netio::pv_from_json(&std::fs::read_to_string(&args[1]).expect("model"));
    let pairs: u64 = args[2].parse().unwrap();
    let sims: u32 = args[3].parse().unwrap();
    let seed0: u64 = args[4].parse().unwrap();
    let w: f64 = args[5].parse().unwrap();

    let (mut wins, mut games, mut margin_sum, mut sc_sum) = (0u64, 0u64, 0i64, 0i64);
    for p in 0..pairs {
        let deck = seed0.wrapping_add(p.wrapping_mul(0x1_0001));
        for &bseat in &[0usize, 1usize] {
            let (won, margin, sc) = play(&net, bseat, deck, sims, w);
            if won {
                wins += 1;
            }
            margin_sum += margin as i64;
            sc_sum += sc as i64;
            games += 1;
        }
    }
    let wr = wins as f64 / games as f64;
    let se = (wr * (1.0 - wr) / games as f64).sqrt();
    println!("=== ship_value_arena: ship+castle-BIASED (w={}) vs NORMAL champion ({} games @ {} sims, CRN) ===", w, games, sims);
    println!("biased win rate: {:.4} +-{:.3}  (avg margin {:+.1})", wr, 1.96 * se, margin_sum as f64 / games as f64);
    println!("biased side avg ships+castles/game: {:.2}", sc_sum as f64 / games as f64);
    println!(">0.50 => valuing ships+castles HELPS (champion under-values them); <=0.50 => already priced right");
}
