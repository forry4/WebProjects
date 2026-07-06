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

/// Heuristic scaffold leaf: (softmax-of-priority priors, tanh heuristic margin).
pub fn heur_eval(s: &State, actor: usize, legal: &[usize]) -> (Vec<f64>, f64) {
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
    (p, heuristic::eval_reward(s, actor))
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
