//! Search drivers. P2 scaffold: determinized PUCT + the ai.py heuristic value as
//! a STATIC leaf (no rollout — the documented Spender lesson: value-leaf beats
//! rollout) + a move-type-priority softmax prior. The PV-net driver lands in P3.

use crate::engine::{
    self, State, A_ADJUST0, A_BUY_BLACK0, A_DISCARD0, A_END_TURN, A_GOODS0, A_M6,
    A_PLACE_SLOT0, A_SELL, A_SHIP_DEPOT0, A_SKIP, A_SPACE0, A_SPEND_DIE0, A_TAKE_HEX0, A_WH0,
    A_WORKERS, A_XVALUE0, N_ACTIONS,
};
use crate::heuristic;
use crate::mcts::Search;
use crate::rng::Rng;

pub const C_PUCT: f64 = 1.5;

/// Serving config for the netval leaf, tuned by the offline sweep (fresh-seed
/// confirmed, and it GROWS with sims so it transfers to serving's ~20k): a longer
/// rollout truncation (more delayed-payoff resolution before the net value reads)
/// + lower exploration (commit faster). The combo beats netval@20@1.5 ~0.62-0.64
/// across 200-1024 sims. Scaffold/hybrid/pv keep C_PUCT + ROLLOUT_MICRO_STEPS.
pub const NETVAL_ROLLOUT_STEPS: usize = 30;
pub const NETVAL_C_PUCT: f64 = 1.0;

/// Rough action-type priority (the ai.py `_ROLLOUT_PRIORITY` shape, adapted to
/// micro actions). Only a PRIOR — PUCT corrects it.
fn action_priority(a: usize) -> f64 {
    match a {
        _ if a >= A_SPACE0 => 5.0,
        _ if (A_PLACE_SLOT0..A_PLACE_SLOT0 + 3).contains(&a) => 5.0,
        _ if (A_XVALUE0..A_XVALUE0 + 6).contains(&a) => 4.0,
        _ if (A_SHIP_DEPOT0..A_SHIP_DEPOT0 + 6).contains(&a) => 4.0,
        _ if (A_TAKE_HEX0..A_TAKE_HEX0 + 12).contains(&a) => 3.0,
        A_SELL => 3.0,
        _ if (A_GOODS0..A_GOODS0 + 6).contains(&a) => 3.0,
        _ if (A_WH0..A_WH0 + 6).contains(&a) => 3.0,
        _ if (A_SPEND_DIE0..A_SPEND_DIE0 + 2).contains(&a) => 3.5, // gateway to hex/place/sell
        _ if (A_BUY_BLACK0..A_BUY_BLACK0 + 4).contains(&a) => 2.0,
        A_M6 => 2.0,
        _ if (A_ADJUST0..A_ADJUST0 + 12).contains(&a) => 1.0,
        A_WORKERS => 1.0,
        _ if (A_DISCARD0..A_DISCARD0 + 3).contains(&a) => 0.0,
        A_SKIP | A_END_TURN => 0.0,
        _ => 1.0,
    }
}

/// Rollout depth in MICRO actions (~= ai.py's 8 ENGINE moves at ~2.5 micro/move).
/// The rollout-then-eval leaf matters: CoC's `_value` was tuned as a PAIR with the
/// Python bot's rollout (a stored tile at 0.35 credit is really "about to be placed
/// for a region score"), so a purely static leaf systematically undervalues
/// in-flight turns — measured 0.235 vs hard static, vs the rollout leaf's pass.
pub const ROLLOUT_MICRO_STEPS: usize = 20;

fn priority_rollout_step(s: &mut State, rng: &mut Rng) {
    let acts = engine::legal_actions(s);
    let mut mx = f64::NEG_INFINITY;
    for &a in &acts {
        let v = action_priority(a);
        if v > mx {
            mx = v;
        }
    }
    let top: Vec<usize> = acts.into_iter().filter(|&a| action_priority(a) == mx).collect();
    let a = top[rng.below(top.len())];
    engine::apply(s, a);
}

/// Heuristic scaffold leaf: (softmax-of-priority priors, tanh heuristic margin
/// after a short priority rollout — mirrors ai.py `_rollout` + `_eval_reward`).
pub fn heur_eval(s: &State, actor: usize, legal: &[usize], rng: &mut Rng) -> (Vec<f64>, f64) {
    let mut p = vec![0.0f64; N_ACTIONS];
    let mut mx = f64::NEG_INFINITY;
    for &a in legal {
        let v = action_priority(a);
        if v > mx {
            mx = v;
        }
        p[a] = v;
    }
    let mut sum = 0.0;
    for &a in legal {
        let e = (p[a] - mx).exp();
        p[a] = e;
        sum += e;
    }
    for &a in legal {
        p[a] /= sum;
    }
    let mut r = s.clone();
    let mut steps = 0;
    while r.mode != crate::engine::OVER && steps < ROLLOUT_MICRO_STEPS {
        priority_rollout_step(&mut r, rng);
        steps += 1;
    }
    let v = if r.mode == crate::engine::OVER {
        heuristic::terminal_reward(&r, actor)
    } else {
        heuristic::eval_reward(&r, actor)
    };
    (p, v)
}

/// Run `sims` simulations from `s` and return the root visit counts.
pub fn root_visits_heur(s: &State, sims: u32, c_puct: f64, seed: u64) -> Vec<i32> {
    let mut search = Search::new(s.clone(), c_puct);
    let mut rng = Rng::new(seed ^ 0x5EA2C4);
    for _ in 0..sims {
        search.sim(&mut rng, &heur_eval);
    }
    search.root_visits().to_vec()
}

/// Scaffold search returning (visits, searched root value from the root actor's
/// perspective = sum W / sum N) — the harvest readout.
pub fn root_readout_heur(s: &State, sims: u32, c_puct: f64, seed: u64) -> (Vec<i32>, f64) {
    let mut search = Search::new(s.clone(), c_puct);
    let mut rng = Rng::new(seed ^ 0x5EA2C4);
    for _ in 0..sims {
        search.sim(&mut rng, &heur_eval);
    }
    let n: i64 = search.root_visits().iter().map(|&x| x as i64).sum();
    let w: f64 = search.root_wins().iter().sum();
    (search.root_visits().to_vec(), if n > 0 { w / n as f64 } else { 0.0 })
}

/// Net leaf: (legal-masked softmax of the policy logits, value head) — both from
/// the leaf actor's perspective (features are mover-relative).
pub fn pv_eval(
    net: &crate::valuenet::PolicyValueNet,
    s: &State,
    actor: usize,
    legal: &[usize],
) -> (Vec<f64>, f64) {
    let f = crate::feats::features(s, actor);
    let (v, logits) = net.forward_raw(&f);
    let mut p = vec![0.0f64; N_ACTIONS];
    let mut mx = f32::NEG_INFINITY;
    for &a in legal {
        if logits[a] > mx {
            mx = logits[a];
        }
    }
    let mut sum = 0.0f64;
    for &a in legal {
        let e = ((logits[a] - mx) as f64).exp();
        p[a] = e;
        sum += e;
    }
    for &a in legal {
        p[a] /= sum;
    }
    (p, v as f64)
}

/// Hybrid leaf: NET policy prior + ROLLOUT-heuristic value (isolates prior quality;
/// also the S-style config — strong hand value + learned prior).
pub fn hybrid_eval(
    net: &crate::valuenet::PolicyValueNet,
    s: &State,
    actor: usize,
    legal: &[usize],
    rng: &mut Rng,
) -> (Vec<f64>, f64) {
    let (p, _) = pv_eval(net, s, actor, legal);
    let (_, v) = heur_eval(s, actor, legal, rng);
    (p, v)
}

/// Experiment (b) leaf: NET policy prior + 20-step priority rollout + the NET
/// VALUE HEAD at the truncation (instead of heuristic::eval_reward). The static
/// value leaf loses in CoC because a 0-step eval can't see the delayed payoffs
/// (income/region/endgame); this plays them PART-way out (20 micro-steps) then
/// applies the LEARNED long-horizon eval — the one untested lever after the pure
/// value-leaf path closed. Terminal positions still use the exact terminal reward.
pub fn hybrid_netval_eval(
    net: &crate::valuenet::PolicyValueNet,
    s: &State,
    actor: usize,
    legal: &[usize],
    rng: &mut Rng,
) -> (Vec<f64>, f64) {
    hybrid_netval_eval_steps(net, s, actor, legal, rng, ROLLOUT_MICRO_STEPS)
}

/// netval leaf with a configurable rollout truncation length (for the sweep — 20
/// was inherited from the hybrid scaffold, never tuned for the net-value leaf).
pub fn hybrid_netval_eval_steps(
    net: &crate::valuenet::PolicyValueNet,
    s: &State,
    actor: usize,
    legal: &[usize],
    rng: &mut Rng,
    max_steps: usize,
) -> (Vec<f64>, f64) {
    let (p, _) = pv_eval(net, s, actor, legal);
    let mut r = s.clone();
    let mut steps = 0;
    while r.mode != crate::engine::OVER && steps < max_steps {
        priority_rollout_step(&mut r, rng);
        steps += 1;
    }
    let v = if r.mode == crate::engine::OVER {
        heuristic::terminal_reward(&r, actor)
    } else {
        net.forward_raw(&crate::feats::features(&r, actor)).0 as f64
    };
    (p, v)
}

/// PV-net search: visits + root value (root actor's perspective).
pub fn root_readout_pv(
    net: &crate::valuenet::PolicyValueNet,
    s: &State,
    sims: u32,
    c_puct: f64,
    seed: u64,
) -> (Vec<i32>, f64) {
    let mut search = Search::new(s.clone(), c_puct);
    let mut rng = Rng::new(seed ^ 0x9E77);
    let eval = |st: &State, actor: usize, legal: &[usize], _rng: &mut Rng| {
        pv_eval(net, st, actor, legal)
    };
    for _ in 0..sims {
        search.sim(&mut rng, &eval);
    }
    let n: i64 = search.root_visits().iter().map(|&x| x as i64).sum();
    let w: f64 = search.root_wins().iter().sum();
    (search.root_visits().to_vec(), if n > 0 { w / n as f64 } else { 0.0 })
}

/// Pick the most-visited legal root action with the PV net leaf.
pub fn choose_action_pv(
    net: &crate::valuenet::PolicyValueNet,
    s: &State,
    sims: u32,
    seed: u64,
) -> usize {
    let legal = engine::legal_actions(s);
    if legal.len() == 1 {
        return legal[0];
    }
    let (visits, _) = root_readout_pv(net, s, sims, C_PUCT, seed);
    *legal.iter().max_by_key(|&&a| visits[a]).expect("nonempty legal")
}

/// Net-argmax policy (0 sims — the distill sanity probe).
pub fn choose_action_pv_argmax(
    net: &crate::valuenet::PolicyValueNet,
    s: &State,
    _seed: u64,
) -> usize {
    let legal = engine::legal_actions(s);
    if legal.len() == 1 {
        return legal[0];
    }
    let (p, _) = pv_eval(net, s, s.actor() as usize, &legal);
    *legal
        .iter()
        .max_by(|&&a, &&b| p[a].partial_cmp(&p[b]).unwrap())
        .expect("nonempty legal")
}

/// Pick the most-visited legal root action.
pub fn choose_action_heur(s: &State, sims: u32, seed: u64) -> usize {
    let legal = engine::legal_actions(s);
    if legal.len() == 1 {
        return legal[0];
    }
    let visits = root_visits_heur(s, sims, C_PUCT, seed);
    *legal
        .iter()
        .max_by_key(|&&a| visits[a])
        .expect("nonempty legal")
}
