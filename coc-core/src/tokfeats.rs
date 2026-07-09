//! P4b TOKEN encoder — the attention net's input. THIS FILE IS THE SCHEMA SPEC:
//! 32 tokens x 28 feats + 32 mask + 96 state = 1024 flat f32 (the row format for
//! harvests, the PvEval seam, and the torch twin — all three read this layout).
//! FROZEN once the first distill harvest lands; slots marked reserved may gain
//! meanings later (same dim = same pipeline, only a retrain).
//!
//! Tokens (index -> thing):
//!    0..12  depot-hex offers: token 2*d + slot for depot d in 0..6
//!   12..16  black-depot offers
//!   16..19  my storage slots
//!   19..22  opponent storage slots
//!   22..27  my board's top-5 regions (by value-at-stake, deterministic rule below)
//!   27..32  opponent's top-5 regions
//! Mask = 1 when the slot holds a live tile / an existing region, else 0 (empty
//! offers, empty storage slots, and missing region ranks are masked out).
//!
//! Policy-head alignment (the token-tied payoff): depot tokens 0..12 are 1:1 with
//! A_TAKE_HEX0..+12, black tokens with A_BUY_BLACK0..+4, my storage tokens with
//! A_DISCARD0..+3 AND A_PLACE_SLOT0..+3 (2 logits/token); SPACE + globals stay on
//! the pooled trunk.
use crate::boards_gen::{COLOR_MASK, NEIGHBOR_MASK, N_SPACES, REGION_MASK, REGION_SIZE, SPACE_COLOR, SPACE_NUMBER};
use crate::engine::{Micro, Pending, State};
use crate::feats::{endgame_mult, tile_sub, tile_time_value};
use crate::tiles::{color_of, AREA_SCORE, N_GOODS, PHASE_BONUS};

pub const TOK_N: usize = 32;
pub const TOK_F: usize = 28;
pub const TOK_STATE: usize = 96;
pub const N_FEATS_TOK: usize = TOK_N * TOK_F + TOK_N + TOK_STATE; // 1024

// token feature slots (tile tokens; regions repurpose 11+ — kind flags disambiguate)
const K_DEPOT: usize = 0;
const K_BLACK: usize = 1;
const K_STORAGE: usize = 2;
const K_REGION: usize = 3;
const K_OWNER: usize = 4; // storage/region: 1 = opponent's
const K_COLOR0: usize = 5; // ..=10 color onehot
const K_SUB: usize = 11; // tile subtype (feats::tile_sub convention)
const K_TTV_ME: usize = 12; // tile_time_value for seat | region value-at-stake /46
const K_TTV_OPP: usize = 13; // tile_time_value for opp | region filled frac
const K_EMPTY_ME: usize = 14; // my empty spaces of this color /8 | region size /8
const K_EMPTY_OPP: usize = 15; // opp empty of color /8 | region remaining /8
const K_SURPLUS: usize = 16; // dead-if-held/taken flag | region phase bonus /10
const K_EGM_ME: usize = 17; // endgame mult (me) /8 | region area score /36
const K_EGM_OPP: usize = 18; // endgame mult (opp) /8 | region reachable frac
const K_DEPOT_NO: usize = 19; // (d+1)/6 for depot tokens
const K_GOODS_AT: usize = 20; // goods sitting on this depot /5
const K_PHASES_LEFT: usize = 21; // (5 - phase - 1 + eps) /5, all kinds
const K_PLACE_ME: usize = 22; // placeable somewhere on my board NOW (any die) | region die-needs 22..=27
const K_PLACE_OPP: usize = 23; // same for opp

pub fn encode_row(s: &State, seat: usize) -> Vec<f32> {
    let mut out = vec![0f32; N_FEATS_TOK];
    let (tok, rest) = out.split_at_mut(TOK_N * TOK_F);
    let (mask, st) = rest.split_at_mut(TOK_N);
    let opp = 1 - seat;
    let phases_left = (4 - s.phase as usize) as f32; // phases AFTER this one

    let mut tile_token = |tok: &mut [f32], ti: usize, code: u16, kind: usize, owner: usize,
                          depot_no: f32, goods_at: f32| {
        let f = &mut tok[ti * TOK_F..(ti + 1) * TOK_F];
        f[kind] = 1.0;
        f[K_OWNER] = owner as f32;
        f[K_COLOR0 + color_of(code) as usize] = 1.0;
        f[K_SUB] = tile_sub(code);
        f[K_TTV_ME] = tile_time_value(s, seat, code);
        f[K_TTV_OPP] = tile_time_value(s, opp, code);
        let c = color_of(code) as usize;
        let (bm, bo) = (s.boards[seat] as usize, s.boards[opp] as usize);
        let em = (COLOR_MASK[bm][c] & !s.players[seat].filled).count_ones();
        let eo = (COLOR_MASK[bo][c] & !s.players[opp].filled).count_ones();
        f[K_EMPTY_ME] = em as f32 / 8.0;
        f[K_EMPTY_OPP] = eo as f32 / 8.0;
        // dead-if-held/taken: holder's (or would-be holder = me, for offers)
        // stored count of this color vs their remaining empties of it
        let holder = if kind == K_STORAGE { owner } else { seat };
        let stored = s.players[holder].storage.iter()
            .filter(|&&t| t != 0 && color_of(t) as usize == c).count() as u32
            + if kind != K_STORAGE { 1 } else { 0 };
        let hempty = if holder == seat { em } else { eo };
        f[K_SURPLUS] = (stored > hempty) as u32 as f32;
        f[K_EGM_ME] = endgame_mult(s, seat, code) / 8.0;
        f[K_EGM_OPP] = endgame_mult(s, opp, code) / 8.0;
        f[K_DEPOT_NO] = depot_no;
        f[K_GOODS_AT] = goods_at;
        f[K_PHASES_LEFT] = phases_left / 5.0;
        f[K_PLACE_ME] = (s.legal_space_mask(seat, code, 0, true) != 0) as u32 as f32;
        f[K_PLACE_OPP] = (s.legal_space_mask(opp, code, 0, true) != 0) as u32 as f32;
    };

    // 0..12 depot-hex offers
    for d in 0..6 {
        let goods_at: u8 = s.depot_goods[d].iter().sum();
        for slot in 0..2 {
            let code = s.depot_hex[d][slot];
            let ti = 2 * d + slot;
            if code != 0 {
                mask[ti] = 1.0;
                tile_token(tok, ti, code, K_DEPOT, 0, (d + 1) as f32 / 6.0, goods_at as f32 / 5.0);
            }
        }
    }
    // 12..16 black depot
    for slot in 0..4 {
        let code = s.black_depot[slot];
        if code != 0 {
            mask[12 + slot] = 1.0;
            tile_token(tok, 12 + slot, code, K_BLACK, 0, 0.0, 0.0);
        }
    }
    // 16..22 storage (mine then opp)
    for (who, base) in [(seat, 16usize), (opp, 19usize)] {
        for slot in 0..3 {
            let code = s.players[who].storage[slot];
            if code != 0 {
                mask[base + slot] = 1.0;
                tile_token(tok, base + slot, code, K_STORAGE, (who != seat) as usize, 0.0, 0.0);
            }
        }
    }
    // 22..32 region tokens: top-5 per player by value-at-stake (incomplete regions
    // first, scored AREA+PHASE_BONUS, deterministic tie-break by region id)
    for (who, base) in [(seat, 22usize), (opp, 27usize)] {
        let b = s.boards[who] as usize;
        let filled = s.players[who].filled;
        let mut regs: Vec<(f32, usize)> = (0..REGION_SIZE[b].len())
            .filter(|&r| REGION_SIZE[b][r] > 0)
            .map(|r| {
                let size = REGION_SIZE[b][r] as usize;
                let done = (REGION_MASK[b][r] & filled).count_ones() as usize == size;
                let stake = if done {
                    0.0
                } else {
                    (AREA_SCORE[size - 1] + PHASE_BONUS[s.phase as usize]) as f32
                };
                (stake, r)
            })
            .collect();
        regs.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap().then(a.1.cmp(&b.1)));
        for (rank, &(stake, r)) in regs.iter().take(5).enumerate() {
            let ti = base + rank;
            mask[ti] = 1.0;
            let f = &mut tok[ti * TOK_F..(ti + 1) * TOK_F];
            let rmask = REGION_MASK[b][r];
            let size = REGION_SIZE[b][r] as usize;
            let done_cells = (rmask & filled).count_ones() as usize;
            let sid0 = rmask.trailing_zeros() as usize;
            f[K_REGION] = 1.0;
            f[K_OWNER] = (who != seat) as usize as f32;
            f[K_COLOR0 + SPACE_COLOR[b][sid0] as usize] = 1.0;
            f[K_TTV_ME] = stake / 46.0;
            f[K_TTV_OPP] = done_cells as f32 / size as f32;
            f[K_EMPTY_ME] = size as f32 / 8.0;
            f[K_EMPTY_OPP] = (size - done_cells) as f32 / 8.0;
            f[K_SURPLUS] = PHASE_BONUS[s.phase as usize] as f32 / 10.0;
            f[K_EGM_ME] = AREA_SCORE[size - 1] as f32 / 36.0;
            let mut reach = 0u32;
            for sid in 0..N_SPACES {
                if rmask >> sid & 1 == 1 && filled >> sid & 1 == 0
                    && NEIGHBOR_MASK[sid] & filled != 0 {
                    reach += 1;
                }
            }
            f[K_EGM_OPP] = if size > done_cells {
                reach as f32 / (size - done_cells) as f32
            } else {
                0.0
            };
            f[K_PHASES_LEFT] = phases_left / 5.0;
            // 22..=27: per-die-number empty-cell counts /8
            for sid in 0..N_SPACES {
                if rmask >> sid & 1 == 1 && filled >> sid & 1 == 0 {
                    f[K_PLACE_ME + (SPACE_NUMBER[b][sid] as usize - 1)] += 1.0 / 8.0;
                }
            }
        }
    }

    // ── state vector (96) ──
    let mut i = 0usize;
    let mut push = |st: &mut [f32], i: &mut usize, v: f32| {
        st[*i] = v;
        *i += 1;
    };
    for who in [seat, opp] {
        for die in 0..2 {
            let d = s.dice[who][die];
            push(st, &mut i, d.value as f32 / 6.0);
            push(st, &mut i, d.orig as f32 / 6.0);
            push(st, &mut i, d.used as u32 as f32);
            push(st, &mut i, d.adjusted as u32 as f32);
        }
    }
    push(st, &mut i, s.white_die as f32 / 6.0);
    push(st, &mut i, s.track_pos[seat] as f32 / 6.0);
    push(st, &mut i, s.track_pos[opp] as f32 / 6.0);
    push(st, &mut i, (s.track_top == seat as i8) as u32 as f32);
    for who in [seat, opp] {
        let p = &s.players[who];
        push(st, &mut i, (p.workers as f32 / 20.0).min(1.5));
        push(st, &mut i, (p.silver as f32 / 20.0).min(1.5));
        push(st, &mut i, p.vp as f32 / 100.0);
        push(st, &mut i, p.mines as f32 / 5.0);
    }
    for who in [seat, opp] {
        for c in 0..N_GOODS {
            push(st, &mut i, s.players[who].goods[c] as f32 / 4.0);
        }
    }
    for who in [seat, opp] {
        let sold: u32 = s.players[who].sold.iter().map(|&x| x as u32).sum();
        push(st, &mut i, sold as f32 / 12.0);
        push(st, &mut i, (3 - s.players[who].storage_len()) as f32 / 3.0);
    }
    for ph in 0..5 {
        push(st, &mut i, (s.phase as usize == ph) as u32 as f32);
    }
    for rd in 1..=5 {
        push(st, &mut i, (s.round as usize == rd) as u32 as f32);
    }
    push(st, &mut i, (s.start_player as usize == seat) as u32 as f32);
    push(st, &mut i, (s.actor() as usize == seat) as u32 as f32);
    for c in 0..N_GOODS {
        push(st, &mut i, s.bonus_left[c] as f32 / 2.0);
    }
    for who in [seat, opp] {
        let p = &s.players[who];
        let cont = (1..=14).filter(|&e| p.has_effect(e)).count();
        let endg = (15..=26).filter(|&e| p.has_effect(e)).count();
        push(st, &mut i, cont as f32 / 5.0);
        push(st, &mut i, endg as f32 / 5.0);
        push(st, &mut i, p.has_effect(2) as u32 as f32);
        push(st, &mut i, p.has_effect(6) as u32 as f32);
        push(st, &mut i, p.has_effect(8) as u32 as f32);
        push(st, &mut i, p.has_effect(14) as u32 as f32);
    }
    push(st, &mut i, s.black_used as u32 as f32);
    push(st, &mut i, s.m6_used as u32 as f32);
    let pk = match s.pending {
        Pending::None => 0,
        Pending::ExtraAction => 1,
        Pending::ShipChoose => 2,
        Pending::ShipAdj { .. } => 3,
        Pending::GoodsPick { .. } => 4,
        Pending::BuildingTake { .. } => 5,
        Pending::Warehouse => 6,
        Pending::Townhall => 7,
    };
    for k in 0..8 {
        push(st, &mut i, (pk == k) as u32 as f32);
    }
    let (mk, mval) = match s.micro {
        Micro::None => (0, 0.0),
        Micro::DieMenu { value, .. } => (1, value as f32 / 6.0),
        Micro::PlaceWhere { value, .. } => (2, value as f32 / 6.0),
        Micro::M6 => (3, 0.0),
    };
    for k in 0..4 {
        push(st, &mut i, (mk == k) as u32 as f32);
    }
    push(st, &mut i, mval);
    for who in [seat, opp] {
        let p = &s.players[who];
        push(st, &mut i, p.buildings.iter().map(|&x| x as u32).sum::<u32>() as f32 / 8.0);
        push(st, &mut i, p.livestock_mask.count_ones() as f32 / 9.0);
    }
    push(st, &mut i, s.goods_queue_len as f32 / 5.0);
    push(st, &mut i, s.supply_len as f32 / 124.0);
    debug_assert!(i <= TOK_STATE, "state vector overflow: {i}");
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::{self, State};
    use crate::rng::Rng;

    /// Layout invariants across random real games: exact dim, masks only where
    /// content exists, every value bounded, deterministic re-encode.
    #[test]
    fn token_rows_are_sane() {
        for seed in 0..12u64 {
            let mut s = State::new_game([(seed % 9) as u8, ((seed / 3) % 9) as u8], seed);
            let mut rng = Rng::new(seed ^ 0x70CF);
            let mut steps = 0;
            while !s.is_over() {
                if steps % 17 == 0 {
                    for seat in 0..2 {
                        let row = encode_row(&s, seat);
                        assert_eq!(row.len(), N_FEATS_TOK);
                        let mask = &row[TOK_N * TOK_F..TOK_N * TOK_F + TOK_N];
                        for (ti, &m) in mask.iter().enumerate() {
                            assert!(m == 0.0 || m == 1.0);
                            let tokf = &row[ti * TOK_F..(ti + 1) * TOK_F];
                            if m == 0.0 {
                                assert!(tokf.iter().all(|&v| v == 0.0), "masked token {ti} nonzero");
                            } else {
                                assert!(tokf.iter().any(|&v| v != 0.0), "live token {ti} all-zero");
                            }
                        }
                        for &v in &row {
                            assert!((-1.5..=2.0).contains(&v) && v.is_finite(), "unbounded {v}");
                        }
                        assert_eq!(row, encode_row(&s, seat), "non-deterministic");
                    }
                }
                let acts = engine::legal_actions_full(&s);
                engine::apply(&mut s, acts[rng.below(acts.len())]);
                steps += 1;
            }
        }
    }

    /// The Enc seam routes 1024 -> Tokens and the fresh-game shape is sensible:
    /// 12 depot offers live after replenish, storage empty, 10 region tokens.
    #[test]
    fn enc_seam_and_fresh_game_shape() {
        assert_eq!(crate::feats::Enc::from_in_dim(N_FEATS_TOK), crate::feats::Enc::Tokens);
        let mut s = State::new_game([0, 1], 5);
        let mut rng = Rng::new(9);
        while s.mode == engine::SETUP {
            let acts = engine::legal_actions_full(&s);
            engine::apply(&mut s, acts[rng.below(acts.len())]);
        }
        let row = crate::feats::encode(crate::feats::Enc::Tokens, &s, 0);
        let mask = &row[TOK_N * TOK_F..TOK_N * TOK_F + TOK_N];
        let depot_live: f32 = mask[..12].iter().sum();
        assert_eq!(depot_live, 12.0, "all 12 depot offers live at phase start");
        assert_eq!(mask[16..22].iter().sum::<f32>(), 0.0, "storage starts empty");
        assert_eq!(mask[22..32].iter().sum::<f32>(), 10.0, "5+5 region tokens");
    }
}
