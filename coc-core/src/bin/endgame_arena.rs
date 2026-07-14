//! endgame_arena — IDEA #1: exact-endgame evaluation. The serving netval leaf
//! plays the endgame out with the OLD HEURISTIC rollout (ai.py) then takes the
//! exact terminal reward — i.e. "exact under HEURISTIC play", and the heuristic
//! is weaker than the net. In the last phase (E) the game is short, so we can
//! afford to roll out with the NET's own greedy policy to terminal instead — a
//! strictly stronger endgame estimate, exactly where 1-2 VP decides the game.
//! Endgame-leaf champion vs normal-netval champion, paired-CRN. >0.50 => the
//! heuristic-rollout endgame value was a real weakness (a serving lever, no
//! retrain). <=0.50 => the endgame was already fine.
//!
//!   endgame_arena <model.json> <pairs> <sims> <seed0> [phase_from]
//!   phase_from (default 4=E): use the net-greedy endgame leaf when s.phase >= this.

use coc_core::engine::{self, State, OVER};
use coc_core::heuristic;
use coc_core::mcts::Search;
use coc_core::netio;
use coc_core::rng::Rng;
use coc_core::valuenet::PvEval;
use coc_core::vsearch;

/// Net-greedy playout to terminal (exact final reward under net-argmax play).
fn net_greedy_terminal(net: &dyn PvEval, s: &State, actor: usize) -> f64 {
    let mut r = s.clone();
    let mut guard = 0u32;
    while r.mode != OVER && guard < 400 {
        guard += 1;
        let l = engine::legal_actions(&r);
        let a = if l.len() == 1 {
            l[0]
        } else {
            let ra = r.actor() as usize;
            let (p, _) = vsearch::pv_eval(net, &r, ra, &l);
            *l.iter().max_by(|&&x, &&y| p[x].partial_cmp(&p[y]).unwrap()).expect("nonempty")
        };
        engine::apply(&mut r, a);
    }
    heuristic::terminal_reward(&r, actor)
}

fn pick(net: &dyn PvEval, s: &State, sims: u32, seed: u64, endgame: bool, phase_from: u8) -> usize {
    let legal = engine::legal_actions(s);
    if legal.len() == 1 {
        return legal[0];
    }
    let mut search = Search::new(s.clone(), vsearch::NETVAL_C_PUCT);
    let mut rng = Rng::new(seed ^ 0x9E77);
    let eval = |st: &State, actor: usize, lg: &[usize], r: &mut Rng| {
        if endgame && st.phase >= phase_from {
            let (p, _) = vsearch::pv_eval(net, st, actor, lg);
            (p, net_greedy_terminal(net, st, actor))
        } else {
            vsearch::hybrid_netval_eval_steps(net, st, actor, lg, r, vsearch::NETVAL_ROLLOUT_STEPS)
        }
    };
    for _ in 0..sims {
        search.sim(&mut rng, &eval);
    }
    let v = search.root_visits();
    *legal.iter().max_by_key(|&&a| v[a]).expect("nonempty")
}

fn play(net: &dyn PvEval, eg_seat: usize, deck: u64, sims: u32, phase_from: u8) -> (bool, i32) {
    let pair = (deck % 81) as u8;
    let mut s = State::new_game([pair / 9, pair % 9], deck);
    let mut guard = 0u32;
    while !s.is_over() && guard < 4000 {
        guard += 1;
        let legal = engine::legal_actions(&s);
        if legal.len() == 1 {
            engine::apply(&mut s, legal[0]);
            continue;
        }
        let seat = s.actor() as usize;
        let sd = deck ^ (guard as u64).wrapping_mul(0x9E37_79B9);
        let a = pick(net, &s, sims, sd, seat == eg_seat, phase_from);
        engine::apply(&mut s, a);
    }
    (s.winner == eg_seat as i8, s.players[eg_seat].vp as i32 - s.players[1 - eg_seat].vp as i32)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 5 {
        eprintln!("usage: endgame_arena <model.json> <pairs> <sims> <seed0> [phase_from=4]");
        std::process::exit(2);
    }
    let net = netio::pv_from_json(&std::fs::read_to_string(&args[1]).expect("model"));
    let pairs: u64 = args[2].parse().unwrap();
    let sims: u32 = args[3].parse().unwrap();
    let seed0: u64 = args[4].parse().unwrap();
    let phase_from: u8 = args.get(5).and_then(|s| s.parse().ok()).unwrap_or(4);

    let mut wins = 0u64;
    let mut games = 0u64;
    let mut margin = 0i64;
    for p in 0..pairs {
        let deck = seed0.wrapping_add(p.wrapping_mul(0x1_0001));
        for &eg in &[0usize, 1usize] {
            let (won, m) = play(&net, eg, deck, sims, phase_from);
            if won {
                wins += 1;
            }
            margin += m as i64;
            games += 1;
        }
    }
    let wr = wins as f64 / games as f64;
    let se = (wr * (1.0 - wr) / games as f64).sqrt();
    println!("=== endgame_arena: NET-GREEDY-endgame (phase>={}) vs NORMAL-netval champion ({} games @ {} sims, CRN) ===", phase_from, games, sims);
    println!("endgame-leaf win rate: {:.4} +-{:.3}  (avg margin {:+.1})", wr, 1.96 * se, margin as f64 / games as f64);
    println!(">0.50 => net-greedy endgame beats heuristic-rollout endgame (a serving lever, no retrain); <=0.50 => endgame already fine");
}
