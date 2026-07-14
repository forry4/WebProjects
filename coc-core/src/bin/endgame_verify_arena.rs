//! endgame_verify_arena — IDEA #1b: BOUNDED root-verification of the endgame,
//! the cheap variant of endgame_arena that dodges the leaf-speed trap.
//!
//! endgame_arena swapped the leaf to a net-greedy-to-terminal rollout at EVERY
//! node in phase E. That's ~15-30 extra net forwards PER SIM, so its +4pp
//! equal-sims edge WASHED at equal wall-clock (0.417 @300ms) — the sim loss ate
//! the accuracy gain. This variant runs the NORMAL cheap netval search, then
//! (only in the endgame, only on the top-M most-visited moves) does K
//! determinized net-greedy playouts to terminal and re-ranks by that exact
//! signal. Cost = M*K*~15 forwards PER DECISION (~a few hundred) vs the search's
//! own ~20-40k net forwards — a ~1-2% constant, NOT a per-sim multiplier. So a
//! gain here transfers to equal-time (unlike endgame_arena). Paired-CRN vs the
//! normal champion. >0.50 => the search's visit-ranking mis-picks close endgames
//! that an O(1) exact re-rank fixes (a serving lever, no retrain).
//!
//!   endgame_verify_arena <model.json> <pairs> <sims|Nms> <seed0> [phase_from=4] [topm=3] [k=8]

use coc_core::engine::{self, State, OVER};
use coc_core::heuristic;
use coc_core::mcts::{self, Search};
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

fn pick(
    net: &dyn PvEval,
    s: &State,
    sims: u32,
    budget_ms: u64,
    seed: u64,
    verify: bool,
    phase_from: u8,
    topm: usize,
    k: usize,
) -> usize {
    let legal = engine::legal_actions(s);
    if legal.len() == 1 {
        return legal[0];
    }
    let mut search = Search::new(s.clone(), vsearch::NETVAL_C_PUCT);
    let mut rng = Rng::new(seed ^ 0x9E77);
    let eval = |st: &State, actor: usize, lg: &[usize], r: &mut Rng| {
        vsearch::hybrid_netval_eval_steps(net, st, actor, lg, r, vsearch::NETVAL_ROLLOUT_STEPS)
    };
    if budget_ms > 0 {
        let deadline = std::time::Instant::now() + std::time::Duration::from_millis(budget_ms);
        while std::time::Instant::now() < deadline {
            for _ in 0..16 {
                search.sim(&mut rng, &eval);
            }
        }
    } else {
        for _ in 0..sims {
            search.sim(&mut rng, &eval);
        }
    }
    let v = search.root_visits();
    let most_visited = *legal.iter().max_by_key(|&&a| v[a]).expect("nonempty");
    if !verify || s.phase < phase_from {
        return most_visited;
    }
    // Bounded exact re-rank: top-M visited candidates, K determinized net-greedy
    // playouts each, pick the best mean terminal reward for the actor.
    let actor = s.actor() as usize;
    let mut cand: Vec<usize> = legal.iter().copied().filter(|&a| v[a] > 0).collect();
    cand.sort_by_key(|&a| std::cmp::Reverse(v[a]));
    cand.truncate(topm.max(1));
    if cand.len() < 2 {
        return most_visited;
    }
    let mut vrng = Rng::new(seed ^ 0xC0C_E6);
    let mut best = cand[0];
    let mut best_val = f64::NEG_INFINITY;
    for &a in &cand {
        let mut child = s.clone();
        engine::apply(&mut child, a);
        let mut sum = 0.0;
        for _ in 0..k.max(1) {
            let d = mcts::determinize(&child, &mut vrng);
            sum += net_greedy_terminal(net, &d, actor);
        }
        let mv = sum / k.max(1) as f64;
        if mv > best_val {
            best_val = mv;
            best = a;
        }
    }
    best
}

fn play(
    net: &dyn PvEval,
    v_seat: usize,
    deck: u64,
    sims: u32,
    budget_ms: u64,
    phase_from: u8,
    topm: usize,
    k: usize,
) -> (bool, i32) {
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
        let a = pick(net, &s, sims, budget_ms, sd, seat == v_seat, phase_from, topm, k);
        engine::apply(&mut s, a);
    }
    (s.winner == v_seat as i8, s.players[v_seat].vp as i32 - s.players[1 - v_seat].vp as i32)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 5 {
        eprintln!("usage: endgame_verify_arena <model.json> <pairs> <sims|Nms> <seed0> [phase_from=4] [topm=3] [k=8]");
        std::process::exit(2);
    }
    let net = netio::pv_from_json(&std::fs::read_to_string(&args[1]).expect("model"));
    let pairs: u64 = args[2].parse().unwrap();
    let (sims, budget_ms) = if let Some(t) = args[3].strip_suffix("ms") {
        (0u32, t.parse::<u64>().unwrap())
    } else {
        (args[3].parse::<u32>().unwrap(), 0u64)
    };
    let seed0: u64 = args[4].parse().unwrap();
    let phase_from: u8 = args.get(5).and_then(|s| s.parse().ok()).unwrap_or(4);
    let topm: usize = args.get(6).and_then(|s| s.parse().ok()).unwrap_or(3);
    let k: usize = args.get(7).and_then(|s| s.parse().ok()).unwrap_or(8);

    let mut wins = 0u64;
    let mut games = 0u64;
    let mut margin = 0i64;
    for p in 0..pairs {
        let deck = seed0.wrapping_add(p.wrapping_mul(0x1_0001));
        for &vs in &[0usize, 1usize] {
            let (won, m) = play(&net, vs, deck, sims, budget_ms, phase_from, topm, k);
            if won {
                wins += 1;
            }
            margin += m as i64;
            games += 1;
        }
    }
    let wr = wins as f64 / games as f64;
    let se = (wr * (1.0 - wr) / games as f64).sqrt();
    let budget = if budget_ms > 0 { format!("{}ms EQUAL-TIME", budget_ms) } else { format!("{} sims", sims) };
    println!(
        "=== endgame_verify_arena: ROOT-VERIFY-endgame (phase>={}, top{} x k{}) vs NORMAL champion ({} games @ {}, CRN) ===",
        phase_from, topm, k, games, budget
    );
    println!("verify win rate: {:.4} +-{:.3}  (avg margin {:+.1})", wr, 1.96 * se, margin as f64 / games as f64);
    println!(">0.50 => O(1) endgame re-rank fixes mis-picks (serving lever, transfers to equal-time); <=0.50 => visit-ranking already right");
}
