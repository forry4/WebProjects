//! Heuristic leaf — a port of `_standing` / `_value` / `WEIGHTS` from
//! `games/spender_duel/ai.py`.
//!
//! This is the half of the AI that MUST be exact. The search's job is to optimise
//! whatever this function says is good, so a leaf that judges a position even slightly
//! differently is a different bot no matter how many sims it runs. `bin/ai_parity.rs`
//! pins it to 1e-12 against Python-recorded positions, from BOTH seats.
//!
//! The float expressions below are written in the Python's exact association order
//! (`a*x + b*y + c*z` groups left-to-right, and each `s +=` is its own rounding step).
//! That is what lets the gate run at 1e-12 instead of a hand-waved epsilon.

use crate::cards::{GOLD, WIN_COLOR_POINTS, WIN_CROWNS, WIN_POINTS};
use crate::engine::{bonuses_of, color_points_of, crowns_of, opponent, points_of, State};

/// Tuned by `ai_selfplay.arena` (hard-vs-normal / hard-vs-random). The three win
/// conditions make "progress toward the NEAREST win" the dominant term; it is convex so
/// that closing out a win outweighs broad, unfocused accumulation.
///
/// These are duplicated from Python by necessity, so `ai_parity` asserts them against the
/// fixture header: a re-tuned Python weight must fail loudly, not silently ship a Rust bot
/// that plays to stale numbers.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Weights {
    pub progress: f64,
    pub progress_exp: f64,
    pub points: f64,
    pub crowns: f64,
    pub color: f64,
    pub bonus: f64,
    pub bonus_spread: f64,
    pub token: f64,
    pub gold: f64,
    pub privilege: f64,
    pub reserved: f64,
    pub scale: f64,
}

pub const WEIGHTS: Weights = Weights {
    progress: 26.0,     // max(pts/20, crowns/10, best_color/10), convex
    progress_exp: 2.0,
    points: 1.00,       // realized prestige (also the 20-pt condition's currency)
    crowns: 1.35,       // crowns are scarce (28 in the whole deck) and gate royals
    color: 0.55,        // points concentrated in one color (the 10-in-a-color win)
    bonus: 0.85,        // permanent discounts — the engine
    bonus_spread: 0.20, // having SOME of many colors (keeps future cards reachable)
    token: 0.16,        // raw tokens in hand
    gold: 0.30,         // gold is wild — worth more than a plain gem
    // A privilege converts 1:1 into a gem/pearl of your choice, so it is worth ABOUT a
    // token — and must be worth slightly LESS, or hoarding always out-scores using and the
    // bot never spends one (measured: at 0.55 vs token 0.16 it sat on two all game).
    privilege: 0.13,
    reserved: 0.25,     // optionality (+ denial of a card the opponent wanted)
    scale: 9.0,         // tanh squash of the standing DIFFERENCE
};

/// One seat's positional worth. Scored identically for both players and subtracted in
/// `value`, so blocking/denial emerges from the search itself.
pub fn standing(st: &State, pid: usize, w: &Weights) -> f64 {
    let p = &st.players[pid];
    let pts = points_of(p);
    let crowns = crowns_of(p);
    let cp = color_points_of(p);
    let best_color = *cp.iter().max().unwrap();

    // Progress toward whichever win condition is closest, convex: 90% of the way to a win
    // is worth far more than twice 45%.
    let prog = (pts as f64 / WIN_POINTS as f64)
        .max(crowns as f64 / WIN_CROWNS as f64)
        .max(best_color as f64 / WIN_COLOR_POINTS as f64);
    let mut s = w.progress * prog.powf(w.progress_exp);
    s += w.points * pts as f64 + w.crowns * crowns as f64 + w.color * best_color as f64;

    let bon = bonuses_of(p);
    s += w.bonus * bon.iter().sum::<i32>() as f64;
    s += w.bonus_spread * bon.iter().filter(|&&n| n > 0).count() as f64;

    let toks = &p.tokens;
    let gold = toks[GOLD];
    s += w.token * (toks.iter().sum::<i32>() - gold) as f64 + w.gold * gold as f64;
    s += w.privilege * p.privileges as f64 + w.reserved * p.reserved.len() as f64;
    s
}

/// Leaf value in [-1, 1] from pid's perspective.
pub fn value_w(st: &State, pid: usize, w: &Weights) -> f64 {
    if st.is_over() {
        return if st.winner == pid as i32 { 1.0 } else { -1.0 };
    }
    let opp = opponent(pid);
    let diff = standing(st, pid, w) - standing(st, opp, w);
    (diff / w.scale).tanh()
}

#[inline]
pub fn value(st: &State, pid: usize) -> f64 {
    value_w(st, pid, &WEIGHTS)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::{EMPTY, N_CELLS};

    fn blank() -> State {
        State::from_setup(
            [EMPTY; N_CELLS],
            Vec::new(),
            [Vec::new(), Vec::new(), Vec::new()],
            [vec![-1; 5], vec![-1; 4], vec![-1; 3]],
            0,
            vec![],
            [0, 0],
        )
    }

    /// The one property the fixtures cannot check: they only ever record LIVE positions
    /// (the generator skips `legal`/`top` when over, but still records `val`), and a
    /// terminal's ±1 must not run through tanh.
    #[test]
    fn terminal_value_is_exactly_plus_minus_one() {
        let mut s = blank();
        s.phase = crate::engine::OVER;
        s.winner = 0;
        assert_eq!(value(&s, 0), 1.0);
        assert_eq!(value(&s, 1), -1.0);
    }

    /// A mirrored position must be worth exactly 0 to both seats — the sign/perspective
    /// check that a subtract-the-opponent leaf either passes trivially or fails loudly.
    #[test]
    fn symmetric_position_is_zero_from_both_seats() {
        let mut s = blank();
        for seat in 0..2 {
            s.players[seat].purchased = vec![(0, -1), (30, -1)];
            s.players[seat].tokens = [1, 2, 0, 0, 1, 0, 1];
            s.players[seat].privileges = 1;
        }
        assert_eq!(value(&s, 0), 0.0);
        assert_eq!(value(&s, 1), 0.0);
    }

    /// `value` must be antisymmetric: what is good for me is exactly as bad for you.
    #[test]
    fn value_is_antisymmetric() {
        let mut s = blank();
        s.players[0].purchased = vec![(54, -1), (30, -1)]; // 3pt + 2pt, crowns
        s.players[1].tokens = [1, 1, 1, 0, 0, 1, 2];
        assert!(value(&s, 0) > 0.0, "the seat with the cards should be ahead");
        assert_eq!(value(&s, 0), -value(&s, 1));
    }
}
