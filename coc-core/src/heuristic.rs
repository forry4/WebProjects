//! Scaffold heuristic — the exact port of ai.py `_value` (WEIGHTS ai.py:51-58) +
//! the tanh reward squash. This is the P2 search leaf (bootstrap teacher + gate
//! yardstick), NOT shippable. Scalar parity vs Python is locked by the
//! value-parity fixture test (<=1e-9; float-op order differs only in the region
//! summation order, which costs ~1e-13 at these magnitudes).

use crate::boards_gen::{COLOR_MASK, N_REGIONS, REGION_MASK, REGION_SIZE};
use crate::engine::{State, NUM_PLAYERS};
use crate::tiles::{bonus_first, bonus_second, AREA_SCORE, PHASE_BONUS};

// ai.py WEIGHTS
pub const W_MINE_FUTURE: f64 = 0.9;
pub const W_AREA_PROX: f64 = 1.0;
pub const W_COLOR_PROX: f64 = 1.0;
pub const W_STORAGE: f64 = 0.35;
pub const W_MON_CONT: f64 = 0.45;
pub const W_EMPTY_PEN: f64 = 0.14;
pub const SQUASH: f64 = 12.0;

/// ai.py `_value`: realized score-if-ended-now + weighted unbanked potential.
pub fn value(s: &State, seat: usize) -> f64 {
    let p = &s.players[seat];
    let b = s.boards[seat] as usize;

    let base = p.vp
        + p.goods.iter().map(|&c| c as i16).sum::<i16>()
        + p.silver
        + p.workers / 2
        + s.endgame_monastery_vp(seat);

    let remaining = (5 - s.phase) as f64; // phase-ends still ahead (incl. current)
    let mut val = base as f64;

    val += p.mines as f64 * remaining * W_MINE_FUTURE;

    // area-completion proximity for partially-filled regions
    let pbonus = PHASE_BONUS[s.phase as usize] as f64;
    for r in 0..N_REGIONS[b] as usize {
        let size = REGION_SIZE[b][r] as usize;
        let filled = (p.filled & REGION_MASK[b][r]).count_ones() as usize;
        if 0 < filled && filled < size {
            let frac = filled as f64 / size as f64;
            val += (AREA_SCORE[size - 1] as f64 + pbonus) * frac * frac * W_AREA_PROX;
        }
    }

    // color-bonus proximity (bval = next claimable bonus value for this color)
    for color in 0..6 {
        let cmask = COLOR_MASK[b][color];
        let total = cmask.count_ones() as usize;
        if total == 0 {
            continue;
        }
        let filled = (p.filled & cmask).count_ones() as usize;
        if 0 < filled && filled < total {
            let bval = match s.bonus_left[color] {
                2 => bonus_first(NUM_PLAYERS) as f64,
                1 => bonus_second(NUM_PLAYERS) as f64,
                _ => 0.0,
            };
            let frac = filled as f64 / total as f64;
            val += bval * frac * frac * W_COLOR_PROX;
        }
    }

    val += p.storage_len() as f64 * W_STORAGE;
    // continuous monastery effects = ids 1..=14 (low 14 bits of mon_mask)
    val += (p.mon_mask & 0x3FFF).count_ones() as f64 * remaining * W_MON_CONT;
    val -= (37 - p.filled.count_ones()) as f64 * W_EMPTY_PEN;
    val
}

#[inline]
pub fn squash(x: f64) -> f64 {
    (x / SQUASH).tanh()
}

/// tanh score-margin from `seat`'s perspective at a TERMINAL state.
pub fn terminal_reward(s: &State, seat: usize) -> f64 {
    let scores = s.final_scores();
    squash((scores[seat] - scores[1 - seat]) as f64)
}

/// tanh heuristic-value margin from `seat`'s perspective (non-terminal leaf).
pub fn eval_reward(s: &State, seat: usize) -> f64 {
    squash(value(s, seat) - value(s, 1 - seat))
}
