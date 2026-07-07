//! Batched NETVAL search driver — the sims/s lever for the offline tooling.
//!
//! A single netval sim is ~97% net forward, and a lone forward is MEMORY-bound
//! (streams the full 2.5MB of weights; 10 threads together sit at the shared-L3
//! ceiling). The fix that keeps search semantics EXACTLY intact: each
//! harvest/gate thread drives K independent games in lockstep, advancing every
//! game's search by ONE simulation per round, and evaluates the K leaves in one
//! `forward_batch` pass (row-reuse tiling: each weight row is read once and
//! applied to all K activations) — weight traffic per eval drops ~K-fold, no
//! virtual loss, no cross-thread sync.
//!
//! BIT-IDENTITY: a `SearchTask` owns its rng (seeded exactly like the
//! sequential path), each task's sims run in the same order with the same rng
//! consumption (determinize, then the rollout draws), `forward_batch` rows are
//! bit-identical to `forward_raw`/`forward_value_raw`, and priors go through
//! the shared `vsearch::priors_from_logits`. So a batched gate reproduces the
//! sequential gate's games EXACTLY (validated by gate_coc `batch=1` vs `batch=K`
//! producing identical win/margin lines).

use crate::engine::{self, State, OVER};
use crate::feats;
use crate::heuristic;
use crate::mcts::{Descent, LeafCtx, Search};
use crate::rng::Rng;
use crate::valuenet::PolicyValueNet;
use crate::vsearch;

/// One in-flight netval search (one game's current decision).
pub struct SearchTask {
    pub search: Search,
    rng: Rng,
    done: u32,
    sims: u32,
    rollout_steps: usize,
}

impl SearchTask {
    /// Mirrors the sequential setup exactly: `Search::new(root, c_puct)` +
    /// `Rng::new(seed ^ 0x9E77)`.
    pub fn new(root: State, c_puct: f64, seed: u64, sims: u32, rollout_steps: usize) -> Self {
        SearchTask {
            search: Search::new(root, c_puct),
            rng: Rng::new(seed ^ 0x9E77),
            done: 0,
            sims,
            rollout_steps,
        }
    }

    pub fn finished(&self) -> bool {
        self.done >= self.sims
    }

    /// Searched root value = sum W / sum N from the root actor's perspective
    /// (the harvest readout).
    pub fn root_value(&self) -> f64 {
        let n: i64 = self.search.root_visits().iter().map(|&x| x as i64).sum();
        let w: f64 = self.search.root_wins().iter().sum();
        if n > 0 {
            w / n as f64
        } else {
            0.0
        }
    }
}

/// A leaf awaiting its batched eval.
struct Pending {
    task_i: usize,
    leaf: LeafCtx,
    legal: Vec<usize>,
    actor: usize,
    /// row index of the prior features in the batch
    prior_row: usize,
    /// row index of the truncation-value features, or the exact terminal value
    value: Result<usize, f64>,
}

/// Advance every UNFINISHED task by exactly one simulation, evaluating all
/// their leaves in one batched net pass. Tasks sharing this call must share
/// `net` (the gate driver groups tasks per player before calling).
pub fn step_netval(net: &PolicyValueNet, tasks: &mut [&mut SearchTask]) {
    let mut rows: Vec<Vec<f32>> = Vec::with_capacity(tasks.len() * 2);
    let mut need_policy: Vec<bool> = Vec::with_capacity(tasks.len() * 2);
    let mut pendings: Vec<Pending> = Vec::with_capacity(tasks.len());
    for (i, task) in tasks.iter_mut().enumerate() {
        if task.finished() {
            continue;
        }
        match task.search.descend(&mut task.rng) {
            Descent::Done => {
                task.done += 1; // terminal descent: backed up internally
            }
            Descent::Leaf(leaf) => {
                let legal = engine::legal_actions(&leaf.state);
                let actor = leaf.state.actor() as usize;
                let prior_row = rows.len();
                rows.push(feats::features(&leaf.state, actor));
                need_policy.push(true);
                // the rollout consumes the task rng in the same order the
                // sequential hybrid_netval_eval_steps would (after descend)
                let mut r = leaf.state.clone();
                let mut steps = 0;
                while r.mode != OVER && steps < task.rollout_steps {
                    vsearch::priority_rollout_step(&mut r, &mut task.rng);
                    steps += 1;
                }
                let value = if r.mode == OVER {
                    Err(heuristic::terminal_reward(&r, actor))
                } else {
                    let row = rows.len();
                    rows.push(feats::features(&r, actor));
                    need_policy.push(false);
                    Ok(row)
                };
                pendings.push(Pending { task_i: i, leaf, legal, actor, prior_row, value });
            }
        }
    }
    if pendings.is_empty() {
        return;
    }
    let refs: Vec<&[f32]> = rows.iter().map(|r| r.as_slice()).collect();
    let out = net.forward_batch(&refs, &need_policy);
    for p in pendings {
        let probs = vsearch::priors_from_logits(&out[p.prior_row].1, &p.legal);
        let value = match p.value {
            Ok(row) => out[row].0 as f64,
            Err(v) => v,
        };
        debug_assert_eq!(p.actor, p.leaf.state.actor() as usize);
        let task = &mut tasks[p.task_i];
        task.search.complete(p.leaf, &probs, value);
        task.done += 1;
    }
}
