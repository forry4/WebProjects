//! A cheap, differentiable-ish model of "what would a sensible player do here".
//!
//! Used for two things: the `greedy` bot's move choice, and — the reason it
//! exists as its own module — scoring how PLAUSIBLE an opponent's actual past
//! plays were under a hypothesised deal. Scores are kept in a small range
//! (roughly 0..4) so a softmax temperature is a meaningful knob rather than a
//! magic constant.

use crate::cards::*;
use crate::state::*;

/// Higher is more attractive for the player to move.
///
/// CARD SCORING (skat mode, 2026-08-09) has its own branch, mirrored by
/// `bot.policy_score` in Python: following, the trick's value IS the two
/// cards, so the score is the exact one-trick delta (bank the sum if winning,
/// hand it over if ducking) with a small tie-break toward the lower rank;
/// leading, lead low and keep the +2 cards back. Same rough 0..4 range as the
/// parity branch so the softmax temperature means the same thing.
#[inline]
pub fn policy_score(s: &State, c: u8) -> f32 {
    let r = rank(c) as f32 / 6.0;
    if s.cards {
        if s.led >= 0 {
            let tv = (card_points(s.led as u8) + card_points(c)) as f32;
            let w = beats(s.led as u8, c, s.trump);
            return 2.0 + 0.5 * (if w { tv } else { -tv }) - 0.05 * r;
        }
        let trumpish = if esuit(c, s.trump) == trump_class(s.trump) {
            1.0
        } else {
            0.0
        };
        return 1.0 + (1.0 - r) - 0.4 * card_points(c).max(0) as f32 - trumpish;
    }
    let want_win = trick_value(s.trick) > 0;
    if s.led >= 0 {
        let w = beats(s.led as u8, c, s.trump);
        match (want_win, w) {
            // Take the +2 trick, but with the cheapest card that does it.
            (true, true) => 3.0 - r,
            // Can't win it: throw something small.
            (true, false) => 1.0 - r,
            // Duck the -1 trick, and unload a big card while doing it.
            (false, false) => 3.0 + r,
            // Forced to win it: pay as little as possible.
            (false, true) => 0.6 - r,
        }
    } else {
        let trumpish = if esuit(c, s.trump) == trump_class(s.trump) {
            1.0
        } else {
            0.0
        };
        if want_win {
            1.0 + r + trumpish
        } else {
            // Lead low: under mandatory follow-suit this is how the -1 gets
            // forced onto the opponent.
            1.0 + (1.0 - r) - trumpish
        }
    }
}

/// Softmax over the legal moves. `temp` -> 0 is argmax, `temp` -> infinity is
/// uniform (which makes uniform determinization a special case of inference).
pub fn policy_probs(s: &State, cands: &[u8], temp: f32, out: &mut [f32]) {
    let mut best = f32::MIN;
    for (i, &c) in cands.iter().enumerate() {
        let v = policy_score(s, c) / temp.max(1e-6);
        out[i] = v;
        if v > best {
            best = v;
        }
    }
    let mut sum = 0.0;
    for i in 0..cands.len() {
        out[i] = (out[i] - best).exp();
        sum += out[i];
    }
    for i in 0..cands.len() {
        out[i] /= sum;
    }
}

pub fn policy_best(s: &State, cands: &[u8]) -> u8 {
    let mut best = cands[0];
    let mut bs = f32::MIN;
    for &c in cands {
        let v = policy_score(s, c);
        if v > bs {
            bs = v;
            best = c;
        }
    }
    best
}

/// Sample a move from the softmax. Used for imperfect-information playouts,
/// where a deterministic policy would give every playout the same answer and
/// so measure nothing.
pub fn policy_sample(s: &State, cands: &[u8], temp: f32, rng: &mut crate::rng::Rng) -> u8 {
    let mut p = [0f32; 16];
    policy_probs(s, cands, temp, &mut p);
    let u = (rng.next_u64() >> 40) as f32 / (1u64 << 24) as f32;
    let mut acc = 0.0;
    for (i, &c) in cands.iter().enumerate() {
        acc += p[i];
        if u < acc {
            return c;
        }
    }
    cands[cands.len() - 1]
}
