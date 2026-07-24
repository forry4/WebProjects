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

use crate::cards::{COST, GOLD, N_COLORS, PEARL, WIN_COLOR_POINTS, WIN_CROWNS, WIN_POINTS};
use crate::engine::{bonuses_of, color_points_of, crowns_of, opponent, points_of, State, N_CELLS};
use std::sync::atomic::{AtomicU64, AtomicU8, Ordering};

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

// ─── Geometry-aware eval (experimental; the deployed `value` is board-BLIND) ──────────
//
// The heuristic above never reads `st.board`, so it cannot tell a takeable 3-in-a-line of
// gems a player needs from three scattered tokens — it is blind to gem-acquisition prospects
// and board control. `value_geom` adds ONE term: each seat's best available line-take, weighted
// by how useful those tokens are to THAT seat (pearls are scarce; a colored gem is worth more if
// the seat already has a bonus in that color — synergy). Scored per-seat and SUBTRACTED, exactly
// like `standing`, so "the board currently favors my needs over my opponent's" (and its denial
// mirror) falls out of the search for free. This is NEW information the flat eval lacks, not a
// re-weighting of existing terms (which is measured-saturated).

const UNIT_DIRS: [(i32, i32); 4] = [(0, 1), (1, 0), (1, 1), (1, -1)]; // E, S, SE, SW (== engine)

pub struct GeomWeights {
    pub pearl: f64,
    pub gem_base: f64,
    pub gem_synergy: f64,
}
pub const GEOM: GeomWeights = GeomWeights { pearl: 1.0, gem_base: 0.5, gem_synergy: 0.4 };

// Mode-2 (demand-weighted) scaling: a token's util is boosted by the fraction of face-up pyramid
// cards that still need that color/pearl beyond the seat's permanent bonuses.
const GEM_DEMAND_K: f64 = 1.0;
const PEARL_DEMAND_K: f64 = 1.0;

// Overall line-term multiplier + formulation MODE, both tunable at runtime so the gate can sweep
// them without a rebuild. Serving uses the defaults (0.05 = the confirmed peak weight; mode 1).
const DEFAULT_GEOM_LINE: f64 = 0.05;
static GEOM_LINE_BITS: AtomicU64 = AtomicU64::new(u64::MAX); // u64::MAX = unset -> default
static GEOM_MODE: AtomicU8 = AtomicU8::new(1);
pub fn set_geom_line(w: f64) {
    GEOM_LINE_BITS.store(w.to_bits(), Ordering::Relaxed);
}
pub fn set_geom_mode(m: u8) {
    GEOM_MODE.store(m, Ordering::Relaxed);
}
#[inline]
fn geom_line() -> f64 {
    let b = GEOM_LINE_BITS.load(Ordering::Relaxed);
    if b == u64::MAX {
        DEFAULT_GEOM_LINE
    } else {
        f64::from_bits(b)
    }
}

/// Per-token-type utility for `pid` under the active mode: index 0-4 = colors, 5 = pearl, 6 = gold
/// (always 0 — gold is not line-takeable). Precomputed once per (state, seat) so the line scan is a
/// pure lookup.
fn token_utils(st: &State, pid: usize, g: &GeomWeights) -> [f64; 7] {
    let bon = bonuses_of(&st.players[pid]);
    let mut u = [0.0f64; 7];
    match GEOM_MODE.load(Ordering::Relaxed) {
        2 => {
            // Demand-weighted: boost a color/pearl by how many face-up cards still need it (beyond
            // this seat's permanent bonuses) — the "real needs" signal vs mode-1's synergy proxy.
            let mut demand = [0i32; 7];
            let mut ncards = 0i32;
            for lvl in 0..3 {
                for &cid in &st.pyramid[lvl] {
                    if cid < 0 {
                        continue;
                    }
                    ncards += 1;
                    let cost = &COST[cid as usize];
                    for c in 0..N_COLORS {
                        if cost[c] > bon[c] {
                            demand[c] += 1;
                        }
                    }
                    if cost[PEARL] > 0 {
                        demand[PEARL] += 1;
                    }
                }
            }
            let nc = ncards.max(1) as f64;
            for c in 0..N_COLORS {
                u[c] = g.gem_base * (1.0 + GEM_DEMAND_K * demand[c] as f64 / nc);
            }
            u[PEARL] = g.pearl * (1.0 + PEARL_DEMAND_K * demand[PEARL] as f64 / nc);
        }
        _ => {
            // Mode 1 (default): synergy — a colored gem is worth more if the seat already builds it.
            for c in 0..N_COLORS {
                u[c] = g.gem_base + if bon[c] > 0 { g.gem_synergy } else { 0.0 };
            }
            u[PEARL] = g.pearl;
        }
    }
    u
}

/// The single best available line-take value for `pid` over the shared board — the max over
/// every straight line of 1-3 contiguous gems/pearls (the same geometry `engine::line_moves`
/// enumerates), allocation-free.
fn best_line_util(st: &State, pid: usize, g: &GeomWeights) -> f64 {
    let board = &st.board;
    let util = token_utils(st, pid, g);
    let takeable = |i: usize| board[i] >= 0 && (board[i] as usize) <= PEARL; // gems 0-4 + pearl 5
    let u = |i: usize| util[board[i] as usize];
    let mut best = 0.0f64;
    for i in 0..N_CELLS {
        if !takeable(i) {
            continue;
        }
        let ui = u(i);
        if ui > best {
            best = ui;
        }
        let (r, c) = ((i / 5) as i32, (i % 5) as i32);
        for (dr, dc) in UNIT_DIRS {
            let (r2, c2) = (r + dr, c + dc);
            if !(0..5).contains(&r2) || !(0..5).contains(&c2) {
                continue;
            }
            let j = (r2 * 5 + c2) as usize;
            if !takeable(j) {
                continue;
            }
            let uij = ui + u(j);
            if uij > best {
                best = uij;
            }
            let (r3, c3) = (r2 + dr, c2 + dc);
            if (0..5).contains(&r3) && (0..5).contains(&c3) {
                let k = (r3 * 5 + c3) as usize;
                if takeable(k) {
                    let uijk = uij + u(k);
                    if uijk > best {
                        best = uijk;
                    }
                }
            }
        }
    }
    best
}

/// Geometry-aware leaf value in [-1, 1] from `pid`'s perspective: the standing difference plus
/// the best-line-take differential, squashed by the same `scale`.
pub fn value_geom(st: &State, pid: usize) -> f64 {
    if st.is_over() {
        return if st.winner == pid as i32 { 1.0 } else { -1.0 };
    }
    let opp = opponent(pid);
    let base = standing(st, pid, &WEIGHTS) - standing(st, opp, &WEIGHTS);
    let geom = geom_line() * (best_line_util(st, pid, &GEOM) - best_line_util(st, opp, &GEOM));
    ((base + geom) / WEIGHTS.scale).tanh()
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
