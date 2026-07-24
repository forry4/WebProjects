//! The canonical FIXED action index — a policy net's output space (Phase 3 of the AZ campaign).
//!
//! WHAT THIS IS FOR: making "Hard" stronger. A learned VALUE leaf failed (it degrades with
//! search depth — see `feats.rs`/`valuenet.rs`). The winning design is a learned POLICY PRIOR
//! that biases the determinized PUCT while KEEPING the heuristic value leaf. A policy net emits
//! a FIXED-LENGTH vector, so every move must map to a stable index and back. This file is that
//! bijection; `bin/harvest_pv.rs` dumps (features, policy target, outcome) rows against it.
//!
//! THE LAYOUT IS FROZEN. A trained policy net's weights are tied to these exact index ranges —
//! reordering or resizing ANY block invalidates the net (a full retrain, not a patch). So the
//! block bases below are pinned by `const _: () = assert!(...)` and by `layout_is_frozen`.
//!
//! ── N_ACTIONS = 320 ─────────────────────────────────────────────────────────────────────
//!   take          [0   .. 145)  145  every straight line of 1-3 collinear contiguous cells on
//!                                     the 5x5 board — a FIXED GEOMETRIC set (25 singles + 72
//!                                     adjacent pairs + 48 triples). Indexed by the SORTED cell
//!                                     set via the pre-enumerated `TAKE_LINES` table.
//!   buy           [145 .. 235)  90   (slot, as_color). 15 slots [pyramid L1 0..4, L2 0..3,
//!                                     L3 0..2 = 12, then reserve 0..2 = 3] x 6 as_color buckets
//!                                     [none=-1 -> 0, colour 0..4 -> 1..5]. index = slot*6+bucket.
//!   reserve       [235 .. 250)  15   SOURCE only (gold_cell is fungible -> collapsed): pyramid
//!                                     12 slots + deck 3 levels. Same 12-slot ordering as buy.
//!   use_privilege [250 .. 275)  25   board cell 0..24.
//!   take_same     [275 .. 300)  25   board cell 0..24 (the take_same pending resolver).
//!   discard       [300 .. 307)  7    token colour 0..6 (INCLUDING gold=6).
//!   steal         [307 .. 313)  6    token 0..5 (gem 0..4 or pearl 5 — never gold).
//!   choose_royal  [313 .. 317)  4    royal id 0..3.
//!   replenish     [317]         1
//!   skip_pending  [318]         1
//!   pass          [319]         1
//!
//! ME/OPP-FREE: unlike `feats.rs`, action indices are seat-independent — a cell, a slot, a
//! colour mean the same thing to either player. The reserve/buy "slot -> card" lookups ARE
//! state-dependent (the pyramid/reserve contents), so `index_to_move` takes `&State`, and the
//! acting player is derived the same way the engine + `mcts` do (`acting_pid`: the pending
//! decider if one is open, else the turn player).
//!
//! COLLAPSED gold_cell (the one non-injectivity, by design): several legal `Reserve` moves that
//! differ ONLY in which gold token they take map to the SAME index — exactly as `mcts::legal`
//! already dedups them (gold is fungible; vacating a cell never opens a line). So the map is a
//! bijection over `mcts::root_moves` (the real policy index space), and total-and-legal over the
//! raw `engine::legal_moves`, comparing reserves by SOURCE. `round_trip_bijection` gates both.

use std::sync::OnceLock;

use crate::cards::{GOLD, N_ROYALS, PYRAMID_SIZES};
use crate::engine::{BuySrc, Move, ReserveSrc, State, N_CELLS};

// ── Block sizes ──────────────────────────────────────────────────────────────
pub const N_TAKE: usize = 145;
pub const N_BUY: usize = 90;
pub const N_RESERVE: usize = 15;
pub const N_PRIVILEGE: usize = 25;
pub const N_TAKE_SAME: usize = 25;
pub const N_DISCARD: usize = 7;
pub const N_STEAL: usize = 6;
pub const N_CHOOSE_ROYAL: usize = 4;

/// Face-up pyramid slots (5 + 4 + 3 = 12). The first 12 buy/reserve slots; reserve slots follow.
pub const PYR_SLOTS: usize = PYRAMID_SIZES[0] + PYRAMID_SIZES[1] + PYRAMID_SIZES[2];

// ── Block bases (FROZEN — see the const asserts below) ────────────────────────
pub const TAKE_BASE: usize = 0;
pub const BUY_BASE: usize = TAKE_BASE + N_TAKE; // 145
pub const RESERVE_BASE: usize = BUY_BASE + N_BUY; // 235
pub const PRIV_BASE: usize = RESERVE_BASE + N_RESERVE; // 250
pub const TAKE_SAME_BASE: usize = PRIV_BASE + N_PRIVILEGE; // 275
pub const DISCARD_BASE: usize = TAKE_SAME_BASE + N_TAKE_SAME; // 300
pub const STEAL_BASE: usize = DISCARD_BASE + N_DISCARD; // 307
pub const ROYAL_BASE: usize = STEAL_BASE + N_STEAL; // 313
pub const REPLENISH_IDX: usize = ROYAL_BASE + N_CHOOSE_ROYAL; // 317
pub const SKIP_PENDING_IDX: usize = REPLENISH_IDX + 1; // 318
pub const PASS_IDX: usize = REPLENISH_IDX + 2; // 319

/// The frozen output width of a policy net over Spender Duel.
pub const N_ACTIONS: usize = 320;

// Compile-time tripwires: a stray edit to any block size must fail the BUILD, never silently
// ship a policy net indexed against a shifted layout.
const _: () = assert!(BUY_BASE == 145);
const _: () = assert!(RESERVE_BASE == 235);
const _: () = assert!(PRIV_BASE == 250);
const _: () = assert!(TAKE_SAME_BASE == 275);
const _: () = assert!(DISCARD_BASE == 300);
const _: () = assert!(STEAL_BASE == 307);
const _: () = assert!(ROYAL_BASE == 313);
const _: () = assert!(REPLENISH_IDX == 317);
const _: () = assert!(PASS_IDX + 1 == N_ACTIONS);
const _: () = assert!(PYR_SLOTS == 12);
const _: () = assert!(N_CHOOSE_ROYAL == N_ROYALS);

// ── The take-line table (the fixed 5x5 geometry) ──────────────────────────────
/// Scan directions E, S, SE, SW — the "positive" half, identical to `engine::UNIT_DIRS`. Each
/// line is generated ONCE from its lowest-index cell (E/S/SE) or top-right cell (SW), which is
/// also its sorted-first cell, so the enumeration exactly matches `engine::line_moves`' set.
const DIRS: [(i32, i32); 4] = [(0, 1), (1, 0), (1, 1), (1, -1)];

/// Bitmask of a cell set (cells are 0..24, so each fits in one u32 bit). A set's mask is its
/// canonical key — order-free, so `move_to_index` need not pre-sort a `Take`'s cells.
#[inline]
fn mask(cells: &[usize]) -> u32 {
    cells.iter().fold(0u32, |m, &c| m | (1u32 << c))
}

/// Build the 145 canonical take-lines: 25 singles, then 72 adjacent pairs, then 48 triples —
/// three contiguous blocks, each cell set stored SORTED ascending. FROZEN order.
fn build_take_lines() -> Vec<Vec<usize>> {
    let mut lines: Vec<Vec<usize>> = Vec::with_capacity(N_TAKE);
    for i in 0..N_CELLS {
        lines.push(vec![i]);
    }
    for i in 0..N_CELLS {
        let (r, c) = ((i / 5) as i32, (i % 5) as i32);
        for (dr, dc) in DIRS {
            let (r2, c2) = (r + dr, c + dc);
            if (0..5).contains(&r2) && (0..5).contains(&c2) {
                let mut cells = vec![i, (r2 * 5 + c2) as usize];
                cells.sort_unstable();
                lines.push(cells);
            }
        }
    }
    for i in 0..N_CELLS {
        let (r, c) = ((i / 5) as i32, (i % 5) as i32);
        for (dr, dc) in DIRS {
            let (r3, c3) = (r + 2 * dr, c + 2 * dc);
            // r3,c3 in-bounds implies the midpoint r2,c2 is too (it lies between i and r3,c3).
            if (0..5).contains(&r3) && (0..5).contains(&c3) {
                let (r2, c2) = (r + dr, c + dc);
                let mut cells = vec![i, (r2 * 5 + c2) as usize, (r3 * 5 + c3) as usize];
                cells.sort_unstable();
                lines.push(cells);
            }
        }
    }
    debug_assert_eq!(lines.len(), N_TAKE, "take-line count drifted from N_TAKE");
    lines
}

/// The canonical take table (index -> sorted cell set), built once.
fn take_lines() -> &'static Vec<Vec<usize>> {
    static T: OnceLock<Vec<Vec<usize>>> = OnceLock::new();
    T.get_or_init(build_take_lines)
}

/// Reverse index: (cell-set mask -> take index), sorted by mask for a binary search. Masks are
/// unique (distinct cell sets), so the search is exact.
fn take_rev() -> &'static Vec<(u32, usize)> {
    static R: OnceLock<Vec<(u32, usize)>> = OnceLock::new();
    R.get_or_init(|| {
        let mut v: Vec<(u32, usize)> =
            take_lines().iter().enumerate().map(|(i, l)| (mask(l), i)).collect();
        v.sort_unstable_by_key(|&(m, _)| m);
        v
    })
}

/// The take-block index of a straight-line take, by its (order-free) cell set. `None` if the
/// cells are not one of the 145 canonical lines (never happens for a legal `Take`).
fn take_index(cells: &[usize]) -> Option<usize> {
    let m = mask(cells);
    let r = take_rev();
    r.binary_search_by_key(&m, |&(mm, _)| mm).ok().map(|pos| r[pos].1)
}

// ── Slot helpers (shared by buy + reserve) ────────────────────────────────────
/// First flat pyramid-slot index of a level: L1->0, L2->5, L3->9 (cumulative PYRAMID_SIZES).
#[inline]
fn pyr_slot_base(level: usize) -> usize {
    PYRAMID_SIZES[..level].iter().sum()
}

/// Invert a 0..12 flat pyramid slot to (level, slot-within-level).
#[inline]
fn pyr_level_slot(slot: usize) -> (usize, usize) {
    if slot < PYRAMID_SIZES[0] {
        (0, slot)
    } else if slot < PYRAMID_SIZES[0] + PYRAMID_SIZES[1] {
        (1, slot - PYRAMID_SIZES[0])
    } else {
        (2, slot - PYRAMID_SIZES[0] - PYRAMID_SIZES[1])
    }
}

/// as_color -> its buy bucket: none(-1) -> 0, colour c -> c+1.
#[inline]
fn as_color_bucket(as_color: i8) -> usize {
    if as_color < 0 {
        0
    } else {
        as_color as usize + 1
    }
}

/// The acting player — the pending decider if one is open, else the turn player. Same rule the
/// engine + `mcts` use to enumerate a decision's moves, so `index_to_move` reads the right
/// reserve list / turn context.
#[inline]
fn acting_pid(st: &State) -> usize {
    if st.pending_pid != -1 {
        st.pending_pid as usize
    } else {
        st.turn
    }
}

/// Locate a card in the face-up pyramid: (level, slot-within-level). Re-implements the private
/// `State::find_pyramid` (an accessor there would be additive churn for one caller).
fn find_pyramid_slot(st: &State, cid: usize) -> Option<(usize, usize)> {
    for lvl in 0..3 {
        for (slot, &c) in st.pyramid[lvl].iter().enumerate() {
            if c == cid as i32 {
                return Some((lvl, slot));
            }
        }
    }
    None
}

/// The lowest-index board cell holding a gold token, or `None` if the board has no gold (then
/// no `Reserve` is legal). `index_to_move` picks this as the fungible gold-cell.
fn first_gold_cell(st: &State) -> Option<usize> {
    (0..N_CELLS).find(|&i| st.board[i] == GOLD as i8)
}

// ── The bijection ──────────────────────────────────────────────────────────────
/// Total over every legal move: maps a `Move` to its fixed action index in `[0, N_ACTIONS)`.
///
/// State-dependent for `Buy` (a card's slot is found in the pyramid / the actor's reserve). The
/// `.expect`s fire only on a move that is not legal for the acting player — every caller feeds a
/// move drawn from `legal_moves`/`root_moves`, so a failure here is a bug, not bad input (the
/// repo convention, e.g. `encmove::decode_move`).
pub fn move_to_index(st: &State, mv: &Move) -> usize {
    match mv {
        Move::Take { cells } => {
            TAKE_BASE + take_index(cells).expect("take cells are not a canonical line")
        }
        Move::Buy { card, from, as_color } => {
            let slot = match from {
                BuySrc::Pyramid => {
                    let (lvl, s) =
                        find_pyramid_slot(st, *card).expect("buy(pyramid) card is not in the pyramid");
                    pyr_slot_base(lvl) + s
                }
                BuySrc::Reserve => {
                    let pid = acting_pid(st);
                    let pos = st.players[pid]
                        .reserved
                        .iter()
                        .position(|&c| c == *card)
                        .expect("buy(reserve) card is not in the actor's reserve");
                    PYR_SLOTS + pos
                }
            };
            BUY_BASE + slot * 6 + as_color_bucket(*as_color)
        }
        Move::Reserve { src, .. } => {
            let slot = match src {
                ReserveSrc::Pyramid { level, slot } => pyr_slot_base(*level) + *slot,
                ReserveSrc::Deck { level } => PYR_SLOTS + *level,
            };
            RESERVE_BASE + slot
        }
        Move::UsePrivilege { cell } => PRIV_BASE + *cell,
        Move::TakeSame { cell } => TAKE_SAME_BASE + *cell,
        Move::Discard { color } => DISCARD_BASE + *color,
        Move::Steal { color } => STEAL_BASE + *color,
        Move::ChooseRoyal { royal } => ROYAL_BASE + *royal,
        Move::Replenish => REPLENISH_IDX,
        Move::SkipPending => SKIP_PENDING_IDX,
        Move::Pass => PASS_IDX,
    }
}

/// Reconstruct the `Move` an action index denotes in state `st`.
///
/// Returns `None` when no legal move fits the index — an out-of-range index, an empty/exhausted
/// pyramid or reserve slot, an empty deck, or a reserve with no gold on the board. `Reserve`'s
/// fungible gold cell is filled with the lowest-index gold token (so a round-trip of a legal
/// reserve is equal to the original SOURCE, up to which gold it takes). The acting player (for
/// reserve-buy and turn context) is `acting_pid(st)`, matching `move_to_index`.
pub fn index_to_move(st: &State, idx: usize) -> Option<Move> {
    if idx >= N_ACTIONS {
        return None;
    }
    // take [0..145)
    if idx < BUY_BASE {
        return Some(Move::Take { cells: take_lines()[idx].clone() });
    }
    // buy [145..235)
    if idx < RESERVE_BASE {
        let rel = idx - BUY_BASE;
        let slot = rel / 6;
        let bucket = rel % 6;
        let as_color = if bucket == 0 { -1 } else { (bucket - 1) as i8 };
        if slot < PYR_SLOTS {
            let (lvl, s) = pyr_level_slot(slot);
            let c = *st.pyramid[lvl].get(s)?;
            if c < 0 {
                return None; // empty/exhausted pyramid slot
            }
            return Some(Move::Buy { card: c as usize, from: BuySrc::Pyramid, as_color });
        }
        let pid = acting_pid(st);
        let c = *st.players[pid].reserved.get(slot - PYR_SLOTS)?;
        return Some(Move::Buy { card: c, from: BuySrc::Reserve, as_color });
    }
    // reserve [235..250)
    if idx < PRIV_BASE {
        let gold = first_gold_cell(st)?; // no gold on the board => no reserve is legal
        let rel = idx - RESERVE_BASE;
        if rel < PYR_SLOTS {
            let (lvl, s) = pyr_level_slot(rel);
            let c = *st.pyramid[lvl].get(s)?;
            if c < 0 {
                return None; // can't reserve an empty slot
            }
            return Some(Move::Reserve { gold_cell: gold, src: ReserveSrc::Pyramid { level: lvl, slot: s } });
        }
        let lvl = rel - PYR_SLOTS;
        if st.decks.get(lvl).map_or(true, |d| d.is_empty()) {
            return None; // that deck is empty
        }
        return Some(Move::Reserve { gold_cell: gold, src: ReserveSrc::Deck { level: lvl } });
    }
    // use_privilege [250..275)
    if idx < TAKE_SAME_BASE {
        return Some(Move::UsePrivilege { cell: idx - PRIV_BASE });
    }
    // take_same [275..300)
    if idx < DISCARD_BASE {
        return Some(Move::TakeSame { cell: idx - TAKE_SAME_BASE });
    }
    // discard [300..307)
    if idx < STEAL_BASE {
        return Some(Move::Discard { color: idx - DISCARD_BASE });
    }
    // steal [307..313)
    if idx < ROYAL_BASE {
        return Some(Move::Steal { color: idx - STEAL_BASE });
    }
    // choose_royal [313..317)
    if idx < REPLENISH_IDX {
        return Some(Move::ChooseRoyal { royal: idx - ROYAL_BASE });
    }
    match idx {
        REPLENISH_IDX => Some(Move::Replenish),
        SKIP_PENDING_IDX => Some(Move::SkipPending),
        PASS_IDX => Some(Move::Pass),
        _ => None, // unreachable given the range guard, but keep the match total
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cards::{SPIRAL_ORDER, TOKEN_BAG};
    use crate::engine::{Pending, State, EMPTY, N_CELLS, PK_CHOOSE_ROYAL, PK_DISCARD, PK_STEAL, PK_TAKE_SAME};
    use crate::mcts::{root_moves, RngShuffler};
    use crate::rng::Rng;
    use std::collections::HashSet;

    /// Deal a fresh game — a structural copy of `bin/harvest_value::new_game` (it needs no
    /// bit-parity with Python; the parity gate owns the rules that play it out).
    fn new_game(rng: &mut Rng) -> State {
        let mut decks: [Vec<usize>; 3] = [(0..30).collect(), (30..54).collect(), (54..67).collect()];
        let sizes = [5usize, 4, 3];
        let mut pyramid: [Vec<i32>; 3] = [Vec::new(), Vec::new(), Vec::new()];
        for lvl in 0..3 {
            rng.shuffle(&mut decks[lvl]);
            for _ in 0..sizes[lvl] {
                pyramid[lvl].push(decks[lvl].pop().unwrap() as i32);
            }
        }
        let mut bag: Vec<u8> = TOKEN_BAG.to_vec();
        rng.shuffle(&mut bag);
        let mut board = [EMPTY; N_CELLS];
        for &c in SPIRAL_ORDER.iter() {
            if bag.is_empty() {
                break;
            }
            if board[c] == EMPTY {
                board[c] = bag.pop().unwrap() as i8;
            }
        }
        State::from_setup(board, bag, decks, pyramid, 2, vec![0, 1, 2, 3], [0, 1])
    }

    /// Two moves are "the same" for the round-trip if equal, treating a `Reserve`'s gold cell
    /// as fungible (it is deliberately collapsed in the index).
    fn eq_mod_gold(a: &Move, b: &Move) -> bool {
        match (a, b) {
            (Move::Reserve { src: sa, .. }, Move::Reserve { src: sb, .. }) => sa == sb,
            _ => a == b,
        }
    }

    /// THE table check: the 145 canonical take-lines are EXACTLY the straight lines
    /// `engine::line_moves` enumerates on a fully-occupied board — same geometry, no drift.
    #[test]
    fn take_lines_match_the_engine_geometry() {
        let lines = take_lines();
        assert_eq!(lines.len(), 145, "expected 145 canonical take-lines");
        // Counts by length: 25 singles / 72 pairs / 48 triples.
        let (mut s, mut p, mut t) = (0, 0, 0);
        for l in lines {
            match l.len() {
                1 => s += 1,
                2 => p += 1,
                3 => t += 1,
                _ => panic!("a take-line must be 1-3 cells"),
            }
            assert!(l.windows(2).all(|w| w[0] < w[1]), "cells must be stored sorted");
            assert!(l.iter().all(|&c| c < 25), "cell out of range");
        }
        assert_eq!((s, p, t), (25, 72, 48), "block sizes drifted");

        // All masks distinct (no aliased lines).
        let masks: HashSet<u32> = lines.iter().map(|l| mask(l)).collect();
        assert_eq!(masks.len(), lines.len(), "two lines share a cell set");

        // A full-gem board (colours 0..4, no gold) makes every geometric line legal, so
        // line_moves emits exactly the canonical set.
        let mut board = [EMPTY; N_CELLS];
        for i in 0..N_CELLS {
            board[i] = (i % 5) as i8;
        }
        let st = State::from_setup(
            board,
            Vec::new(),
            [Vec::new(), Vec::new(), Vec::new()],
            [vec![-1; 5], vec![-1; 4], vec![-1; 3]],
            0,
            vec![],
            [0, 0],
        );
        let engine: HashSet<Vec<usize>> = st
            .line_moves()
            .into_iter()
            .map(|m| match m {
                Move::Take { mut cells } => {
                    cells.sort_unstable();
                    cells
                }
                _ => unreachable!("line_moves emits only takes"),
            })
            .collect();
        let table: HashSet<Vec<usize>> = lines.iter().cloned().collect();
        assert_eq!(engine, table, "the take table != engine::line_moves geometry");
    }

    /// The bijection contract: over MANY self-play states, every legal move round-trips
    /// (index in range, reconstructs to a legal move equal-except-gold), and the policy index
    /// space (`root_moves`) is injective.
    #[test]
    fn round_trip_bijection() {
        let mut seen_types = [0usize; 11]; // coverage tally, by move discriminant below
        let mut states = 0usize;
        let mut moves_checked = 0usize;

        for game in 0..80u64 {
            let mut rng = Rng::new(0x51ED_u64.wrapping_mul(game + 1));
            let mut st = new_game(&mut rng);
            let mut ply = 0;
            while !st.is_over() && ply < 400 {
                let actor = acting_pid(&st);
                let legal = st.legal_moves(actor);
                if legal.is_empty() {
                    break;
                }
                states += 1;

                // (1) every legal move round-trips.
                for mv in &legal {
                    let idx = move_to_index(&st, mv);
                    assert!(idx < N_ACTIONS, "index {} out of range for {:?}", idx, mv);
                    seen_types[type_ix(mv)] += 1;
                    let back = index_to_move(&st, idx)
                        .unwrap_or_else(|| panic!("index_to_move({}) None for legal {:?}", idx, mv));
                    assert!(
                        st.legal_moves(actor).contains(&back),
                        "reconstructed {:?} (idx {}) is not legal (from {:?})",
                        back, idx, mv
                    );
                    assert!(
                        eq_mod_gold(mv, &back),
                        "round-trip changed the move: {:?} -> idx {} -> {:?}",
                        mv, idx, back
                    );
                    moves_checked += 1;
                }

                // (2) the policy index space is injective (reserves already deduped by source).
                let rm = root_moves(&st, actor, true);
                let idxs: Vec<usize> = rm.iter().map(|m| move_to_index(&st, m)).collect();
                let uniq: HashSet<usize> = idxs.iter().copied().collect();
                assert_eq!(uniq.len(), idxs.len(), "two root moves share an action index at state {:?}", rm);

                // advance with a pseudo-random legal move.
                let choice = legal[(rng.below(legal.len())) % legal.len()].clone();
                let mut sh = RngShuffler { rng: &mut rng };
                if st.apply_move(actor, &choice, &mut sh).is_err() {
                    break;
                }
                ply += 1;
            }
        }

        assert!(states > 500, "too few states exercised: {}", states);
        assert!(moves_checked > 5000, "too few moves exercised: {}", moves_checked);
        // The common mandatory move types MUST be covered by random self-play.
        for &t in &[0usize /*take*/, 1 /*buy*/, 2 /*reserve*/] {
            assert!(seen_types[t] > 0, "self-play never exercised move type {}", t);
        }
        eprintln!(
            "round_trip_bijection: {} games, {} states, {} legal moves checked; coverage {:?}",
            80, states, moves_checked, seen_types
        );
    }

    /// A discriminant index for coverage tallying (kept in sync with `move_to_index`).
    fn type_ix(m: &Move) -> usize {
        match m {
            Move::Take { .. } => 0,
            Move::Buy { .. } => 1,
            Move::Reserve { .. } => 2,
            Move::UsePrivilege { .. } => 3,
            Move::TakeSame { .. } => 4,
            Move::Steal { .. } => 5,
            Move::ChooseRoyal { .. } => 6,
            Move::Discard { .. } => 7,
            Move::Replenish => 8,
            Move::SkipPending => 9,
            Move::Pass => 10,
        }
    }

    /// The pending resolvers are rare in random play, so pin them with constructed states —
    /// every kind must round-trip, INCLUDING `skip_pending` where it is offered.
    #[test]
    fn pending_resolvers_round_trip() {
        let base = || {
            State::from_setup(
                [EMPTY; N_CELLS],
                Vec::new(),
                [Vec::new(), Vec::new(), Vec::new()],
                [vec![-1; 5], vec![-1; 4], vec![-1; 3]],
                0,
                vec![0, 1, 2, 3],
                [0, 0],
            )
        };
        let check = |st: &State| {
            let actor = acting_pid(st);
            let legal = st.legal_moves(actor);
            assert!(!legal.is_empty(), "constructed pending has no legal move");
            for mv in &legal {
                let idx = move_to_index(st, mv);
                let back = index_to_move(st, idx).expect("pending move must reconstruct");
                assert!(eq_mod_gold(mv, &back), "pending round-trip changed {:?} -> {:?}", mv, back);
                assert!(st.legal_moves(actor).contains(&back), "pending reconstruction illegal: {:?}", back);
            }
        };

        // take_same: two white tokens on the board.
        let mut st = base();
        st.board[0] = 0;
        st.board[1] = 0;
        st.pending_pid = 0;
        st.pending_kind = PK_TAKE_SAME;
        st.pending = Pending { color: 0, cells: vec![0, 1], ..Default::default() };
        check(&st);

        // steal: opponent holds a white and a pearl.
        let mut st = base();
        st.players[1].tokens[0] = 1;
        st.players[1].tokens[5] = 1;
        st.pending_pid = 0;
        st.pending_kind = PK_STEAL;
        st.pending = Pending { colors: vec![0, 5], ..Default::default() };
        check(&st);

        // choose_royal: two royals on offer.
        let mut st = base();
        st.royals_available = vec![0, 2];
        st.pending_pid = 0;
        st.pending_kind = PK_CHOOSE_ROYAL;
        st.pending = Pending { royals: vec![0, 2], ..Default::default() };
        check(&st);

        // discard: holding three different tokens (no skip is offered here).
        let mut st = base();
        st.players[0].tokens = [2, 0, 1, 0, 0, 1, 0];
        st.pending_pid = 0;
        st.pending_kind = PK_DISCARD;
        st.pending = Pending { excess: 4, ..Default::default() };
        check(&st);
    }

    /// Every action index reconstructs into its OWN block (or `None`) — the inverse map never
    /// crosses a block boundary. Confirms the range guards line up with `move_to_index`.
    #[test]
    fn indices_stay_in_their_block() {
        // A dense state so most slots reconstruct to Some (empties are still fine as None).
        let mut rng = Rng::new(123);
        let st = new_game(&mut rng);
        for idx in 0..N_ACTIONS {
            if let Some(mv) = index_to_move(&st, idx) {
                // The reconstructed move must index back to the SAME index (modulo the reserve
                // gold collapse, which does not change the index).
                assert_eq!(move_to_index(&st, &mv), idx, "index {} -> {:?} -> {}", idx, mv, move_to_index(&st, &mv));
            }
        }
        assert!(index_to_move(&st, N_ACTIONS).is_none(), "out-of-range index must be None");
    }

    /// The layout the const-asserts freeze, restated as a runtime gate the reviewer can read.
    #[test]
    fn layout_is_frozen() {
        assert_eq!(
            (
                TAKE_BASE, BUY_BASE, RESERVE_BASE, PRIV_BASE, TAKE_SAME_BASE, DISCARD_BASE, STEAL_BASE,
                ROYAL_BASE, REPLENISH_IDX, SKIP_PENDING_IDX, PASS_IDX, N_ACTIONS
            ),
            (0, 145, 235, 250, 275, 300, 307, 313, 317, 318, 319, 320)
        );
    }
}
