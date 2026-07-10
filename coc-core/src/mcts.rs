//! Determinized PUCT (ISMCTS) — the spender-core mcts.rs pattern with the CoC
//! State/N_ACTIONS/determinize swapped in.
//!
//! Value convention: leaf value in [-1, 1] from the perspective of the player to
//! act at the leaf (`State::actor` — NOT `turn`, so pending sub-decisions credit
//! the right seat); backups credit each edge by the acting player's identity
//! (CoC turns are long same-player micro/pending chains, never strictly
//! alternating). Terminals back up the tanh score margin from seat 0's view.
//!
//! Determinization mirrors ai.py `_determinize`: canonicalize (sort) then
//! reshuffle the three UNDRAWN piles and reseed the dice stream, per simulation.
//! Depots, duchies, storage, current dice, and the goods QUEUE stay true
//! (they're public).

use crate::engine::{self, State, N_ACTIONS, OVER};
use crate::heuristic;
use crate::rng::Rng;
use std::collections::HashMap;

const EPS_PRIOR: f64 = 1e-3;

struct Node {
    to_play: i8,
    expanded: bool,
    p: [f64; N_ACTIONS],
    n: [i32; N_ACTIONS],
    w: [f64; N_ACTIONS],
    children: HashMap<usize, usize>,
}

impl Node {
    fn new(to_play: i8) -> Self {
        Node {
            to_play,
            expanded: false,
            p: [0.0; N_ACTIONS],
            n: [0; N_ACTIONS],
            w: [0.0; N_ACTIONS],
            children: HashMap::new(),
        }
    }
}

/// Clone `s` and resample the hidden information: sort (canonicalize — duplicate
/// codes are interchangeable, so sorting fully erases the true order) + shuffle
/// each undrawn pile, and reseed the future-dice stream.
pub fn determinize(s: &State, rng: &mut Rng) -> State {
    let mut d = s.clone();
    let n = d.supply_len as usize;
    d.supply[..n].sort_unstable();
    rng.shuffle(&mut d.supply[..n]);
    let n = d.black_supply_len as usize;
    d.black_supply[..n].sort_unstable();
    rng.shuffle(&mut d.black_supply[..n]);
    let n = d.goods_supply_len as usize;
    d.goods_supply[..n].sort_unstable();
    rng.shuffle(&mut d.goods_supply[..n]);
    d.rng = rng.next_u64();
    d
}

/// An in-flight simulation paused at its unexpanded leaf (the batching seam).
pub struct LeafCtx {
    idx: usize,
    path: Vec<(usize, usize)>,
    pub state: State,
}

/// Outcome of `Search::descend`.
pub enum Descent {
    /// Terminal reached during descent; already backed up — the sim is done.
    Done,
    /// Unexpanded leaf reached; evaluate it and call `complete`.
    Leaf(LeafCtx),
}

pub struct Search {
    root_state: State,
    c_puct: f64,
    nodes: Vec<Node>,
}

impl Search {
    pub fn new(root: State, c_puct: f64) -> Self {
        let actor = root.actor();
        Search { root_state: root, c_puct, nodes: vec![Node::new(actor)] }
    }

    fn select(&self, idx: usize, acts: &[usize]) -> usize {
        let node = &self.nodes[idx];
        let mut total = 0i32;
        for &a in acts {
            total += node.n[a];
        }
        let sqrt_total = ((total + 1) as f64).sqrt();
        let mut best_a = acts[0];
        let mut best_u = f64::NEG_INFINITY;
        for &a in acts {
            let n = node.n[a];
            let q = if n > 0 { node.w[a] / (n as f64) } else { 0.0 };
            let p = if node.p[a] > 0.0 { node.p[a] } else { EPS_PRIOR };
            let u = q + self.c_puct * p * sqrt_total / (1.0 + n as f64);
            if u > best_u {
                best_u = u;
                best_a = a;
            }
        }
        best_a
    }

    fn backup(&mut self, path: &[(usize, usize)], value: f64, ref_player: i8) {
        for &(ni, a) in path {
            let v = if self.nodes[ni].to_play == ref_player { value } else { -value };
            self.nodes[ni].n[a] += 1;
            self.nodes[ni].w[a] += v;
        }
    }

    /// One simulation. `eval(leaf_state, actor, legal, rng) -> (priors[N_ACTIONS],
    /// value)`; value from `actor`'s perspective (the rng lets the leaf run a
    /// rollout). Terminals back up tanh-margin internally. Composed from
    /// `descend` + `complete` so the batched drivers share this exact code path.
    pub fn sim<F>(&mut self, rng: &mut Rng, eval: &F)
    where
        F: Fn(&State, usize, &[usize], &mut Rng) -> (Vec<f64>, f64),
    {
        if let Descent::Leaf(leaf) = self.descend(rng) {
            let legal = engine::legal_actions(&leaf.state);
            let actor = leaf.state.actor() as usize;
            let (probs, value) = eval(&leaf.state, actor, &legal, rng);
            self.complete(leaf, &probs, value);
        }
    }

    /// First half of one simulation: determinize + tree descent. Either the
    /// descent hit a terminal (backed up internally — the sim is DONE) or it
    /// reached an unexpanded leaf whose eval the caller must supply via
    /// `complete` (this is the batching seam: collect K leaves, evaluate them
    /// in one net pass, then complete each).
    pub fn descend(&mut self, rng: &mut Rng) -> Descent {
        let mut s = determinize(&self.root_state, rng);
        let mut idx = 0usize;
        let mut path: Vec<(usize, usize)> = Vec::new();
        loop {
            if !self.nodes[idx].expanded {
                break;
            }
            let acts = engine::legal_actions(&s);
            let a = self.select(idx, &acts);
            path.push((idx, a));
            engine::apply(&mut s, a);
            if s.mode == OVER {
                let v0 = heuristic::terminal_reward(&s, 0);
                self.backup(&path, v0, 0);
                return Descent::Done;
            }
            idx = match self.nodes[idx].children.get(&a) {
                Some(&c) => c,
                None => {
                    let c = self.nodes.len();
                    self.nodes.push(Node::new(s.actor()));
                    self.nodes[idx].children.insert(a, c);
                    c
                }
            };
        }
        Descent::Leaf(LeafCtx { idx, path, state: s })
    }

    /// Second half: expand the leaf with `probs` (len N_ACTIONS) and back up
    /// `value` (from the leaf actor's perspective).
    pub fn complete(&mut self, leaf: LeafCtx, probs: &[f64], value: f64) {
        let actor = leaf.state.actor();
        self.nodes[leaf.idx].expanded = true;
        self.nodes[leaf.idx].p.copy_from_slice(probs);
        self.backup(&leaf.path, value, actor);
    }

    pub fn root_visits(&self) -> &[i32] {
        &self.nodes[0].n
    }

    pub fn root_wins(&self) -> &[f64] {
        &self.nodes[0].w
    }

    /// Per-decision TREE REUSE: adopt the expanded child under `action` as the
    /// new root (within one engine move the shipped state is fixed and the
    /// prefix grows by the chosen action, so that child IS the next
    /// micro-decision's root — its stats are valid ISMCTS averages for it).
    /// Returns false when the child was never expanded (build a fresh Search).
    /// The old root + sibling subtrees stay orphaned in the arena (bounded: a
    /// few reroots per engine move, then the whole tree is dropped).
    /// Caller MUST follow with `set_root_state` before the next sim.
    pub fn advance_root_child(&mut self, action: usize) -> bool {
        let Some(&child) = self.nodes[0].children.get(&action) else {
            return false;
        };
        if !self.nodes[child].expanded {
            return false;
        }
        self.nodes.swap(0, child);
        true
    }

    /// Replace the root state after `advance_root_child` steps (the caller
    /// recomputes it from the shipped state + full prefix — within-move micro
    /// actions are deterministic, so replay and stepping agree).
    pub fn set_root_state(&mut self, s: State) {
        self.root_state = s;
    }
}
