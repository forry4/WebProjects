//! Opponent-aware world sampling — a particle filter over deals.
//!
//! Plain PIMC samples uniformly among worlds consistent with the *cards*, which
//! throws away the strongest evidence available: the opponent's own choices.
//! This module reconstructs the whole round under a hypothesised deal, replays
//! it, and scores how plausible the opponent's actual plays were.
//!
//! The economics are what make this worth doing. Sampling and scoring a world
//! costs microseconds; solving one costs ~20 ms. So we can afford to propose a
//! thousand worlds, weight them, and then spend the SAME solve budget on a
//! resampled handful. That is the direct consequence of the measurement that
//! determinizations saturate at 8: the lever is which worlds we solve, not how
//! many.
//!
//! Note what `temp -> infinity` does and does not do. It flattens the policy,
//! but it does NOT reduce to uniform sampling: the likelihood still contains
//! -sum(ln n_legal) over the opponent's past decisions, so a world in which
//! they were FORCED explains their play better than one in which they chose
//! from five options. That is the principle of restricted choice, and it comes
//! out of the replay for free. Plain PIMC is `particles == 0`, not `temp =
//! inf` — which means the A/B ladder can separate restricted choice (temp inf)
//! from policy-shape inference (finite temp).

use crate::policy::policy_probs;
use crate::rng::Rng;
use crate::state::*;
use crate::view::View;

/// Rebuild the deal as it stood before trick 1, given a hypothesis about the
/// hidden cards now. Every play is public along with the pile it came from, so
/// this is exact rather than a guess.
pub fn rewind_for_test(v: &View, now: &State) -> State {
    rewind(v, now)
}

fn rewind(v: &View, now: &State) -> State {
    let mut hand = now.hand;
    let mut pile = now.pile;
    for &(mover, card, source) in v.history.iter().rev() {
        let m = mover as usize;
        if source == 0 {
            hand[m] |= 1 << card;
        } else {
            let p = &mut pile[m][(source - 1) as usize];
            p.c[p.n as usize] = card;
            p.n += 1;
        }
    }
    State {
        hand,
        pile,
        trump: now.trump,
        trick: 0,
        leader: v.first_leader,
        led: -1,
        pts: [0, 0],
        // The rewind replays from the DEAL, so it re-derives this on the way.
        escored: 0,
        // The scoring travels with the position -- a replay accumulates points.
        even: now.even,
        cards: now.cards,
    }
}

/// Rewind to the deal, then replay the whole round under this hypothesis.
/// Returns the position it lands on (which must equal `world`) and the
/// log-likelihood of the opponent's observed choices. `None` means the world
/// is impossible — the opponent could not legally have played what they did.
pub fn replay(v: &View, world: &State, temp: f32) -> Option<(State, f32)> {
    let opp = 1 - v.me;
    let mut st = rewind(v, world);
    let mut logw = 0f32;
    let mut cands = [0u8; 16];
    let mut probs = [0f32; 16];
    for &(mover, card, _) in v.history.iter() {
        let n = st.legal(&mut cands);
        let idx = cands[..n].iter().position(|&c| c == card)?;
        if mover as usize == opp {
            policy_probs(&st, &cands[..n], temp, &mut probs);
            logw += probs[idx].max(1e-9).ln();
        }
        st.play(card);
    }
    Some((st, logw))
}

/// Log-likelihood of the opponent's observed play under this hypothesis.
pub fn log_likelihood(v: &View, world: &State, temp: f32) -> Option<f32> {
    replay(v, world, temp).map(|(_, l)| l)
}

/// Propose `particles` worlds, weight them by opponent consistency, and
/// resample `k` to be solved. Falls back to uniform if nothing is plausible.
pub fn sample_worlds(
    v: &View,
    rng: &mut Rng,
    particles: usize,
    temp: f32,
    k: usize,
    buf: &mut Vec<u8>,
    out: &mut Vec<State>,
) {
    out.clear();
    if particles == 0 || v.history.is_empty() {
        for _ in 0..k {
            out.push(v.determinize(rng, buf));
        }
        return;
    }

    let mut worlds: Vec<State> = Vec::with_capacity(particles);
    let mut logw: Vec<f32> = Vec::with_capacity(particles);
    let mut best = f32::NEG_INFINITY;
    for _ in 0..particles {
        let w = v.determinize(rng, buf);
        if let Some(l) = log_likelihood(v, &w, temp) {
            if l > best {
                best = l;
            }
            worlds.push(w);
            logw.push(l);
        }
    }
    if worlds.is_empty() {
        for _ in 0..k {
            out.push(v.determinize(rng, buf));
        }
        return;
    }

    let mut wt: Vec<f32> = logw.iter().map(|&l| (l - best).exp()).collect();
    let total: f32 = wt.iter().sum();
    if !(total > 0.0) {
        for i in 0..k {
            out.push(worlds[i % worlds.len()]);
        }
        return;
    }
    // Systematic resampling: lower variance than independent draws, and it
    // guarantees any world holding more than 1/k of the mass is picked.
    let step = total / k as f32;
    let jitter = (rng.next_u64() >> 40) as f32 / (1u64 << 24) as f32 * step;
    let mut acc = wt[0];
    let mut j = 0usize;
    for i in 0..k {
        let target = jitter + i as f32 * step;
        while acc < target && j + 1 < wt.len() {
            j += 1;
            acc += wt[j];
        }
        out.push(worlds[j]);
    }
    wt.clear();
}
