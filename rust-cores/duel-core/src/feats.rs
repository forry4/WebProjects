//! Feature encoder for the Spender Duel learned value net (Phase 1 of the AZ campaign).
//!
//! WHAT THIS IS FOR: the deployed "Hard" bot searches with a HAND-TUNED heuristic leaf
//! (`value::value`), and its strength saturates by ~700 sims — it is at the ceiling of that
//! heuristic, not sims-limited. The lever is therefore a better EVALUATOR: an outcome-
//! trained value net used as the MCTS leaf. This file turns a `State` into the fixed vector
//! that net reads; `bin/harvest_value.rs` dumps (features, outcome) self-play rows for it.
//!
//! THIS ENCODER IS THE ONE SOURCE OF TRUTH — there is NO Python twin, and training reads the
//! harvested CSV by column. So two rules bind, hard:
//!   1. FROZEN LAYOUT. Every group below has a fixed index range (documented per-group). An
//!      input-dim change — even reordering — invalidates every trained weight, so it means a
//!      full retrain from scratch, not a patch. `feature_names()` names each column IN ORDER
//!      so the CSV header is self-documenting and cannot silently drift from the values.
//!   2. me/opp SYMMETRY. Everything is encoded from `seat`'s perspective ("me" = seat, "opp"
//!      = the other seat). The net is thus perspective-invariant: the same weights judge
//!      either player, and self-play labels (±1 from the mover's seat) line up with it.
//!
//! THE HEURISTIC-BASELINE TRICK (group F): the hand-tuned `standing`/`value` already encode a
//! decent positional read. Feeding them as INPUTS means the net starts life no worse than the
//! heuristic and only has to learn the RESIDUAL — the long-horizon signal the static leaf
//! misses. (Same trick spender-core/coc-core used to break their heuristic ceilings.)
//!
//! Normalizations are chosen so a typical value lands in ~[0, 1] (counts divided by their
//! game maximum) or ~[-1, 1] (the leaf). They are NOT hard bounds: the pre-tanh standing
//! DIFFERENCE (F) is deliberately unsquashed and can reach several units in a lopsided
//! endgame — that is the raw logit the net may reshape, so it is left as-is.

use crate::cards::{
    BONUS, BONUS_COUNT, COST, CROWNS, GOLD, LEVEL_OF, MAX_RESERVED, N_COLORS, N_ROYALS, N_TOKENS,
    PEARL, PTS, PYRAMID_SIZES,
};
use crate::engine::{
    bonuses_of, can_afford, color_points_of, crowns_of, points_of, State, EMPTY, N_CELLS,
};
use crate::value::{standing, value, WEIGHTS};

/// The per-card feature block (groups D and E), documented once at `push_card`.
pub const CARD_BLOCK: usize = 13;

/// Total face-up pyramid slots (5 + 4 + 3 = 12) — group D encodes one card block per slot.
pub const PYRAMID_SLOTS_TOTAL: usize = PYRAMID_SIZES[0] + PYRAMID_SIZES[1] + PYRAMID_SIZES[2];

/// The frozen feature-vector length. Groups:
///   A. global meta ............ [0  .. 17)   (17)
///   B. per-seat me then opp ... [17 .. 67)   (25 each = 50)
///   C. board .................. [67 .. 76)   (9)
///   D. pyramid 12 slots ....... [76 .. 232)  (12 x CARD_BLOCK = 156)
///   E. my 3 reserved slots .... [232 .. 271) (3  x CARD_BLOCK = 39)
///   F. heuristic baselines .... [271 .. 275) (4)
/// The card-block groups derive from PYRAMID_SLOTS_TOTAL (=12) and MAX_RESERVED (=3), so this
/// stays correct if the deck constants ever move (they won't — the parity gate pins them).
pub const N_FEATS: usize =
    17 + 50 + 9 + (PYRAMID_SLOTS_TOTAL * CARD_BLOCK) + (MAX_RESERVED * CARD_BLOCK) + 4;

/// Effective cost of card `ci` for a holder with `bon` bonuses: colour needs after the
/// bonus discount (floored at 0), plus pearls RAW (pearls are never discounted — mirrors
/// `engine::can_afford`). Gold is NOT modelled here (that is the separate `_afford` flag);
/// this is the "how far off am I" magnitude the net can weigh against tokens in hand.
#[inline]
fn eff_cost(ci: usize, bon: &[i32; N_COLORS]) -> i32 {
    let mut s = 0;
    for c in 0..N_COLORS {
        s += (COST[ci][c] - bon[c]).max(0);
    }
    s + COST[ci][PEARL]
}

/// One card's CARD_BLOCK (13) features — used for every pyramid slot (D) and every reserved
/// slot (E). `card < 0` is an empty/exhausted slot and encodes as all zeros (so "no card" is
/// distinguishable from "a 0-point card": the `present` flag is the discriminator).
///
///   0      present (1 if a card occupies the slot)
///   1      points / 6
///   2      crowns / 3
///   3..10  bonus one-hot(7): none, white, blue, green, red, black, wild  (index BONUS+1)
///   10     my effective-cost sum / 15   (colour needs after MY bonuses + pearls)
///   11     my affordable (1 if I can buy it now, gold included)
///   12     opp effective-cost sum / 15  (same, from the OPPONENT's bonuses — contention)
#[inline]
fn push_card(
    out: &mut Vec<f32>,
    card: i32,
    me_bon: &[i32; N_COLORS],
    opp_bon: &[i32; N_COLORS],
    me_tok: &[i32; N_TOKENS],
) {
    if card < 0 {
        out.extend(std::iter::repeat(0.0).take(CARD_BLOCK));
        return;
    }
    let ci = card as usize;
    out.push(1.0);
    out.push(PTS[ci] as f32 / 6.0);
    out.push(CROWNS[ci] as f32 / 3.0);
    // BONUS is -1 (none) .. 5 (wild); +1 maps it into the 0..6 one-hot slots.
    let bidx = (BONUS[ci] + 1) as usize;
    for k in 0..7 {
        out.push(if k == bidx { 1.0 } else { 0.0 });
    }
    out.push(eff_cost(ci, me_bon) as f32 / 15.0);
    out.push(if can_afford(ci, me_tok, me_bon) { 1.0 } else { 0.0 });
    out.push(eff_cost(ci, opp_bon) as f32 / 15.0);
}

// ═══ Card-set ATTENTION tokenizer (v1, value-only). Spec: scratchpad/duel_attn_design.md ═══
// The flat `features` above encodes the pyramid as 12 INDEPENDENT blocks; attention over these tokens
// lets a card's value depend on the others (the cross-card interaction that broke Spender's plateau).

pub const TOK_N: usize = PYRAMID_SLOTS_TOTAL + MAX_RESERVED; // 12 pyramid + 3 own-reserved = 15
pub const TOK_F: usize = 20; // per-card token features (see push_card_token)
pub const TOK_STATE: usize = 46; // global state vector (asserted below)

/// One card token — TOK_F features. `card<0` -> all zeros (masked out). Extends the proven per-card
/// block with the 3 "win-condition proximity after buying this card" deltas (points/crowns/color).
#[allow(clippy::too_many_arguments)]
fn push_card_token(
    out: &mut Vec<f64>,
    card: i32,
    reserved: bool,
    me_bon: &[i32; N_COLORS],
    opp_bon: &[i32; N_COLORS],
    me_tok: &[i32; N_TOKENS],
    me_points: i32,
    me_crowns: i32,
    me_cp: &[i32; N_COLORS],
) {
    if card < 0 {
        out.extend(std::iter::repeat(0.0).take(TOK_F));
        return;
    }
    let ci = card as usize;
    let pts = PTS[ci];
    let cr = CROWNS[ci];
    out.push(1.0); // 0 present
    out.push(pts as f64 / 6.0); // 1
    out.push(cr as f64 / 3.0); // 2
    let bidx = (BONUS[ci] + 1) as usize; // 3..9 bonus one-hot(7): none,white,blue,green,red,black,wild
    for k in 0..7 {
        out.push(if k == bidx { 1.0 } else { 0.0 });
    }
    out.push(BONUS_COUNT[ci] as f64 / 3.0); // 10
    out.push(LEVEL_OF[ci] as f64 / 3.0); // 11
    out.push(eff_cost(ci, me_bon) as f64 / 15.0); // 12 my colour-need after bonuses + pearls
    out.push(if can_afford(ci, me_tok, me_bon) { 1.0 } else { 0.0 }); // 13
    // 14 gold_needed proxy: colour+pearl shortfall vs tokens in hand (gold would cover the rest)
    let mut shortfall = 0i32;
    for c in 0..N_COLORS {
        shortfall += ((COST[ci][c] - me_bon[c]).max(0) - me_tok[c]).max(0);
    }
    shortfall += (COST[ci][PEARL] - me_tok[PEARL]).max(0);
    out.push(shortfall as f64 / 6.0); // 14
    out.push(eff_cost(ci, opp_bon) as f64 / 15.0); // 15 contention (opponent's need)
    out.push(if reserved { 1.0 } else { 0.0 }); // 16
    out.push(((me_points + pts) as f64 / 20.0).min(1.0)); // 17 points-win proximity after buy
    out.push(((me_crowns + cr) as f64 / 10.0).min(1.0)); // 18 crowns-win proximity after buy
    let cw = if BONUS[ci] >= 0 && (BONUS[ci] as usize) < N_COLORS {
        (me_cp[BONUS[ci] as usize] + pts) as f64 / 10.0
    } else {
        me_cp.iter().max().copied().unwrap_or(0) as f64 / 10.0
    };
    out.push(cw.min(1.0)); // 19 color-win proximity after buy
}

/// Longest contiguous takeable line (1-3) currently on the gem board — a cheap geometry signal for
/// the state vector (the eval that's otherwise board-blind).
fn best_line_len(st: &State) -> i32 {
    let board = &st.board;
    let takeable = |i: usize| board[i] >= 0 && (board[i] as usize) <= PEARL;
    const DIRS: [(i32, i32); 4] = [(0, 1), (1, 0), (1, 1), (1, -1)];
    let mut best = 0;
    for i in 0..N_CELLS {
        if !takeable(i) {
            continue;
        }
        best = best.max(1);
        let (r, c) = ((i / 5) as i32, (i % 5) as i32);
        for (dr, dc) in DIRS {
            let (r2, c2) = (r + dr, c + dc);
            if !(0..5).contains(&r2) || !(0..5).contains(&c2) {
                continue;
            }
            let j = (r2 * 5 + c2) as usize;
            if !takeable(j) {
                continue;
            }
            best = best.max(2);
            let (r3, c3) = (r2 + dr, c2 + dc);
            if (0..5).contains(&r3) && (0..5).contains(&c3) && takeable((r3 * 5 + c3) as usize) {
                best = best.max(3);
            }
        }
    }
    best
}

/// Tokenized encoding for the attention net: (tokens[TOK_N*TOK_F], mask[TOK_N], state[TOK_STATE]),
/// all f64, from `seat`'s perspective. Pure function of the state (root-parallel serving relies on it).
pub fn features_tokens(st: &State, seat: usize) -> (Vec<f64>, Vec<f64>, Vec<f64>) {
    let opp = 1 - seat;
    let me = &st.players[seat];
    let me_bon = bonuses_of(me);
    let opp_bon = bonuses_of(&st.players[opp]);
    let me_pts = points_of(me);
    let me_cr = crowns_of(me);
    let me_cp = color_points_of(me);

    // ── tokens + mask: 12 pyramid slots then 3 own-reserved ──
    let mut tokens: Vec<f64> = Vec::with_capacity(TOK_N * TOK_F);
    let mut mask: Vec<f64> = Vec::with_capacity(TOK_N);
    for lvl in 0..3 {
        for slot in 0..PYRAMID_SIZES[lvl] {
            let card = st.pyramid[lvl].get(slot).copied().unwrap_or(EMPTY as i32);
            mask.push(if card >= 0 { 1.0 } else { 0.0 });
            push_card_token(&mut tokens, card, false, &me_bon, &opp_bon, &me.tokens, me_pts, me_cr, &me_cp);
        }
    }
    for slot in 0..MAX_RESERVED {
        let card = me.reserved.get(slot).map(|&c| c as i32).unwrap_or(EMPTY as i32);
        mask.push(if card >= 0 { 1.0 } else { 0.0 });
        push_card_token(&mut tokens, card, true, &me_bon, &opp_bon, &me.tokens, me_pts, me_cr, &me_cp);
    }

    // ── state ──
    let mut s: Vec<f64> = Vec::with_capacity(TOK_STATE);
    for &pid in &[seat, opp] {
        let p = &st.players[pid];
        let bon = if pid == seat { &me_bon } else { &opp_bon };
        let cp = color_points_of(p);
        let pts = points_of(p);
        let cr = crowns_of(p);
        let best_c = *cp.iter().max().unwrap();
        let prog = (pts as f64 / 20.0).max(cr as f64 / 10.0).max(best_c as f64 / 10.0);
        s.push(pts as f64 / 20.0);
        s.push(cr as f64 / 10.0);
        s.push(best_c as f64 / 10.0);
        s.push(prog);
        s.push(p.privileges as f64 / 3.0);
        s.push(p.reserved.len() as f64 / 3.0);
        s.push(p.tokens.iter().sum::<i32>() as f64 / 10.0);
        s.push(p.tokens[GOLD] as f64 / 3.0);
        s.push(bon.iter().sum::<i32>() as f64 / 15.0);
    }
    for &pid in &[seat, opp] {
        let bon = if pid == seat { &me_bon } else { &opp_bon };
        for c in 0..N_COLORS {
            s.push(bon[c] as f64 / 5.0);
        }
    }
    let mut counts = [0i32; N_TOKENS];
    for &t in &st.board {
        if t != EMPTY {
            counts[t as usize] += 1;
        }
    }
    for c in 0..N_COLORS {
        s.push(counts[c] as f64 / 4.0);
    }
    s.push(counts[PEARL] as f64 / 2.0);
    s.push(counts[GOLD] as f64 / 3.0);
    s.push(best_line_len(st) as f64 / 3.0);
    // pyramid colour-demand (what the available cards need beyond my bonuses) — observable deck proxy
    let mut demand = [0i32; N_COLORS];
    for lvl in 0..3 {
        for slot in 0..PYRAMID_SIZES[lvl] {
            if let Some(&card) = st.pyramid[lvl].get(slot) {
                if card >= 0 {
                    for c in 0..N_COLORS {
                        demand[c] += (COST[card as usize][c] - me_bon[c]).max(0);
                    }
                }
            }
        }
    }
    for c in 0..N_COLORS {
        s.push(demand[c] as f64 / 20.0);
    }
    s.push(st.turn_number as f64 / 50.0);
    s.push(st.bag.len() as f64 / 25.0);
    s.push(st.again as i32 as f64);
    s.push(st.replenished as i32 as f64);
    s.push(st.privileges_board as f64 / 3.0);

    debug_assert_eq!(mask.len(), TOK_N);
    debug_assert_eq!(tokens.len(), TOK_N * TOK_F);
    debug_assert_eq!(s.len(), TOK_STATE, "TOK_STATE drift");
    (tokens, mask, s)
}

/// Encode `st` from `seat`'s perspective into the frozen N_FEATS vector. Pure function of
/// the state (root-parallel serving relies on this — see `mcts::root_moves`).
pub fn features(st: &State, seat: usize) -> Vec<f32> {
    let opp = 1 - seat;
    let me = &st.players[seat];
    let me_bon = bonuses_of(me);
    let opp_bon = bonuses_of(&st.players[opp]);

    let mut f: Vec<f32> = Vec::with_capacity(N_FEATS);

    // ── A. Global meta [0..17) ──────────────────────────────────────────────
    f.push(st.turn_number as f32 / 50.0);
    f.push(st.bag.len() as f32 / 25.0);
    f.push(st.decks[0].len() as f32 / 30.0);
    f.push(st.decks[1].len() as f32 / 24.0);
    f.push(st.decks[2].len() as f32 / 13.0);
    f.push(st.replenished as i32 as f32);
    f.push(st.again as i32 as f32);
    f.push(st.privileges_board as f32 / 3.0);
    for r in 0..N_ROYALS {
        f.push(if st.royals_available.contains(&r) { 1.0 } else { 0.0 });
    }
    // pending_kind one-hot(5): none / take_same / steal / choose_royal / discard (PK_* = 0..4)
    for k in 0..5u8 {
        f.push(if st.pending_kind == k { 1.0 } else { 0.0 });
    }

    // ── B. Per-seat, me then opp [17..67) — 25 features each ─────────────────
    for &pid in &[seat, opp] {
        let p = &st.players[pid];
        let bon = if pid == seat { &me_bon } else { &opp_bon };
        let cp = color_points_of(p);
        f.push(points_of(p) as f32 / 20.0);
        f.push(crowns_of(p) as f32 / 10.0);
        for c in 0..N_COLORS {
            f.push(cp[c] as f32 / 10.0);
        }
        f.push(*cp.iter().max().unwrap() as f32 / 10.0);
        for c in 0..N_COLORS {
            f.push(bon[c] as f32 / 5.0);
        }
        f.push(bon.iter().sum::<i32>() as f32 / 15.0);
        for c in 0..N_COLORS {
            f.push(p.tokens[c] as f32 / 5.0);
        }
        f.push(p.tokens[PEARL] as f32 / 2.0);
        f.push(p.tokens[GOLD] as f32 / 3.0);
        f.push(p.tokens.iter().sum::<i32>() as f32 / 10.0);
        f.push(p.privileges as f32 / 3.0);
        f.push(p.reserved.len() as f32 / 3.0);
        f.push(p.royals.len() as f32 / 2.0);
    }

    // ── C. Board [67..76) ────────────────────────────────────────────────────
    let mut counts = [0i32; N_TOKENS];
    let mut empty = 0i32;
    for &t in &st.board {
        if t == EMPTY {
            empty += 1;
        } else {
            counts[t as usize] += 1;
        }
    }
    // Per-type count / its bag maximum (gems 4, pearls 2, gold 3), so each lands in ~[0,1].
    for c in 0..N_COLORS {
        f.push(counts[c] as f32 / 4.0);
    }
    f.push(counts[PEARL] as f32 / 2.0);
    f.push(counts[GOLD] as f32 / 3.0);
    f.push(empty as f32 / 25.0);
    f.push(counts[GOLD] as f32 / 3.0); // num_gold_cells (== gold count; kept per the layout spec)

    // ── D. Pyramid — 12 face-up slots (L1 0..4, L2 0..3, L3 0..2) [76..232) ──
    for lvl in 0..3 {
        for slot in 0..PYRAMID_SIZES[lvl] {
            let card = st.pyramid[lvl].get(slot).copied().unwrap_or(EMPTY as i32);
            push_card(&mut f, card, &me_bon, &opp_bon, &me.tokens);
        }
    }

    // ── E. My reserved — 3 slots [232..271) (opp reserves are hidden; only counted in B) ──
    for slot in 0..MAX_RESERVED {
        let card = me.reserved.get(slot).map(|&c| c as i32).unwrap_or(EMPTY as i32);
        push_card(&mut f, card, &me_bon, &opp_bon, &me.tokens);
    }

    // ── F. Heuristic baselines [271..275) — the residual-learning trick ──────
    let s_me = standing(st, seat, &WEIGHTS);
    let s_opp = standing(st, opp, &WEIGHTS);
    f.push((s_me / 50.0) as f32);
    f.push((s_opp / 50.0) as f32);
    // The raw pre-tanh logit `value` squashes — left UNSQUASHED so the net can reshape it.
    f.push(((s_me - s_opp) / WEIGHTS.scale) as f32);
    // The deployed leaf itself, in [-1, 1]. MUST be the LAST column: the harvest reports its
    // correlation with the outcome label as the encoder/labeling wiring check.
    f.push(value(st, seat) as f32);

    debug_assert_eq!(f.len(), N_FEATS, "feature vector length drifted from N_FEATS");
    f
}

/// Column names in the SAME order as `features`, so the CSV header documents the layout and
/// cannot drift from the values (a length-mismatch test gates the two together).
pub fn feature_names() -> Vec<String> {
    let mut n: Vec<String> = Vec::with_capacity(N_FEATS);
    let card_block = |out: &mut Vec<String>, prefix: &str| {
        out.push(format!("{prefix}_present"));
        out.push(format!("{prefix}_points"));
        out.push(format!("{prefix}_crowns"));
        for b in ["none", "w", "b", "g", "r", "k", "wild"] {
            out.push(format!("{prefix}_bonus_{b}"));
        }
        out.push(format!("{prefix}_my_effcost"));
        out.push(format!("{prefix}_my_afford"));
        out.push(format!("{prefix}_opp_effcost"));
    };

    // A
    n.push("A_turn_number".into());
    n.push("A_bag_count".into());
    n.push("A_deck1".into());
    n.push("A_deck2".into());
    n.push("A_deck3".into());
    n.push("A_replenished".into());
    n.push("A_again".into());
    n.push("A_privileges_board".into());
    for r in 0..N_ROYALS {
        n.push(format!("A_royal{r}_avail"));
    }
    for k in ["none", "take_same", "steal", "choose_royal", "discard"] {
        n.push(format!("A_pending_{k}"));
    }
    // B
    for who in ["me", "opp"] {
        n.push(format!("B_{who}_points"));
        n.push(format!("B_{who}_crowns"));
        for c in 0..N_COLORS {
            n.push(format!("B_{who}_colorpts{c}"));
        }
        n.push(format!("B_{who}_best_color"));
        for c in 0..N_COLORS {
            n.push(format!("B_{who}_bonus{c}"));
        }
        n.push(format!("B_{who}_total_bonuses"));
        for c in 0..N_COLORS {
            n.push(format!("B_{who}_tok{c}"));
        }
        n.push(format!("B_{who}_pearl"));
        n.push(format!("B_{who}_gold"));
        n.push(format!("B_{who}_total_tokens"));
        n.push(format!("B_{who}_privileges"));
        n.push(format!("B_{who}_reserved"));
        n.push(format!("B_{who}_royals"));
    }
    // C
    for c in 0..N_COLORS {
        n.push(format!("C_board_tok{c}"));
    }
    n.push("C_board_pearl".into());
    n.push("C_board_gold".into());
    n.push("C_board_empty".into());
    n.push("C_board_gold_cells".into());
    // D
    for lvl in 0..3 {
        for slot in 0..PYRAMID_SIZES[lvl] {
            card_block(&mut n, &format!("D_L{}s{}", lvl + 1, slot));
        }
    }
    // E
    for slot in 0..MAX_RESERVED {
        card_block(&mut n, &format!("E_res{slot}"));
    }
    // F
    n.push("F_standing_me".into());
    n.push("F_standing_opp".into());
    n.push("F_standing_diff".into());
    n.push("F_value".into());

    debug_assert_eq!(n.len(), N_FEATS, "feature_names length drifted from N_FEATS");
    n
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cards::{N_CARDS, TOKEN_BAG};
    use crate::engine::{State, EMPTY, N_CELLS};
    use crate::rng::Rng;

    /// A well-formed, MODERATE mid-game state: valid card indices everywhere and small,
    /// balanced holdings (L1-only purchases, few tokens) so every feature — including the
    /// unsquashed standing-difference (F) — stays in the sane range the range test asserts.
    /// It need not be reachable; `features` never applies a move, it only reads the state.
    fn rand_state(rng: &mut Rng) -> (State, usize) {
        let ranges = [(0usize, 30usize), (30, 54), (54, 67)];
        let sizes = [5usize, 4, 3];

        // Deal the board from a shuffled real 25-token bag so per-type counts respect their
        // maxima (gems 4, pearls 2, gold 3) — the same multiset the normalizations assume.
        let mut supply: Vec<u8> = TOKEN_BAG.to_vec();
        rng.shuffle(&mut supply);
        let mut board = [EMPTY; N_CELLS];
        for cell in board.iter_mut() {
            if !supply.is_empty() && rng.below(6) != 0 {
                *cell = supply.pop().unwrap() as i8; // ~5/6 of cells occupied, rest empty
            }
        }
        let mut pyramid: [Vec<i32>; 3] = [Vec::new(), Vec::new(), Vec::new()];
        for lvl in 0..3 {
            for _ in 0..sizes[lvl] {
                let (lo, hi) = ranges[lvl];
                pyramid[lvl].push(if rng.below(5) == 0 { -1 } else { (lo + rng.below(hi - lo)) as i32 });
            }
        }
        let mut decks: [Vec<usize>; 3] = [Vec::new(), Vec::new(), Vec::new()];
        for lvl in 0..3 {
            let (lo, hi) = ranges[lvl];
            for _ in 0..rng.below(hi - lo) {
                decks[lvl].push(lo + rng.below(hi - lo));
            }
        }
        let royals: Vec<usize> = (0..N_ROYALS).filter(|_| rng.below(2) == 0).collect();
        let mut st = State::from_setup(
            board,
            Vec::new(),
            decks,
            pyramid,
            rng.below(4) as i32,
            royals,
            [rng.below(3) as i32, rng.below(3) as i32],
        );
        for pid in 0..2 {
            for _ in 0..rng.below(4) {
                st.players[pid].purchased.push((rng.below(30), -1)); // L1 only: PTS <= 1
            }
            for c in 0..N_TOKENS {
                st.players[pid].tokens[c] = rng.below(3) as i32;
            }
            for _ in 0..rng.below(MAX_RESERVED + 1) {
                st.players[pid].reserved.push(rng.below(N_CARDS));
            }
            st.players[pid].privileges = rng.below(3) as i32;
            for _ in 0..rng.below(3) {
                st.players[pid].royals.push(rng.below(N_ROYALS));
            }
        }
        (st, rng.below(2))
    }

    #[test]
    fn length_matches_n_feats() {
        // Both the values and the names must be exactly N_FEATS, over many states.
        assert_eq!(feature_names().len(), N_FEATS);
        let mut rng = Rng::new(12345);
        for _ in 0..300 {
            let (st, seat) = rand_state(&mut rng);
            assert_eq!(features(&st, seat).len(), N_FEATS);
        }
    }

    #[test]
    fn features_are_finite_and_in_range() {
        let mut rng = Rng::new(999);
        for _ in 0..500 {
            let (st, seat) = rand_state(&mut rng);
            for (i, &x) in features(&st, seat).iter().enumerate() {
                assert!(x.is_finite(), "feature {} ({}) is non-finite: {}", i, feature_names()[i], x);
                assert!(x.abs() <= 3.0, "feature {} ({}) out of range: {}", i, feature_names()[i], x);
            }
        }
    }

    /// The heuristic-baseline trick must be wired exactly: the last column IS the deployed
    /// leaf, so training/eval can read it (and the harvest correlates it with the outcome).
    #[test]
    fn last_feature_is_the_value_baseline() {
        let mut rng = Rng::new(7);
        for _ in 0..300 {
            let (st, seat) = rand_state(&mut rng);
            let f = features(&st, seat);
            assert_eq!(f[N_FEATS - 1], value(&st, seat) as f32, "F_value must equal value(st, seat)");
        }
    }

    /// No accidental constant: two materially different states must differ somewhere.
    #[test]
    fn different_states_differ() {
        let mut rng = Rng::new(2024);
        let (a, sa) = rand_state(&mut rng);
        // Force a clearly different position rather than trusting the RNG to diverge.
        let mut b = a.clone();
        b.players[sa].purchased.push((29, -1)); // a 3-point L1 card
        b.players[sa].tokens[0] += 2;
        b.turn_number += 5;
        assert_ne!(features(&a, sa), features(&b, sa));
    }

    /// The names are the CSV header, so a duplicate would silently alias two columns.
    #[test]
    fn feature_names_are_unique() {
        let names = feature_names();
        let mut sorted = names.clone();
        sorted.sort();
        sorted.dedup();
        assert_eq!(sorted.len(), names.len(), "duplicate feature name in the header");
    }
}
