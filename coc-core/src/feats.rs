//! Feature encoder for the CoC policy+value net — ONE source of truth shared by
//! the harvest bins and serving (training reads the CSV columns; there is no
//! Python encoder twin to drift).
//!
//! N_FEATS = 934, mover ("me" = seat) perspective. FROZEN LAYOUT — an input-dim
//! change invalidates all trained weights (full restart). Groups, in order:
//!   A  meta                (16)  phase/round one-hots, rounds-left, phase bonus,
//!                                start-player, track, next-round initiative
//!   B  bonus_left values    (6)  next claimable color-bonus value per color
//!   C  pending/micro       (21)  pending one-hot(8), micro one-hot(4), committed
//!                                die value one-hot(6), extra/townhall flags, slot
//!   D  per-seat resources (146)  73 x {me, opp}: vp/silver/workers/goods/sold/
//!                                storage/mines/buildings/livestock/mon_mask/
//!                                endgame-vp/dice(16)/score-if-now
//!   E  heuristic baselines  (4)  ai._value(me), (opp), tanh margin, score margin
//!                                (the "v_state baseline feature" trick)
//!   F  my board            (518) 37 x 14 per-space block (color/number/filled/
//!                                region fracs+potential/adjacency/storage-color/
//!                                die-number match) — feeds the 37-way SPACE head
//!   G  opp board summary    (14) per-color fill + best-region fracs, completes,
//!                                empties (denial-aware race read)
//!   H  depots              (161) 6 x 22 (2 hex slots x [type+subtype], goods
//!                                counts, me/opp can-take flags) + black 29
//!   I  storage              (48) my 3 x 9 (type/subtype/placeability), opp 3 x 7

use crate::boards_gen::{
    COLOR_MASK, NEIGHBOR_MASK, N_REGIONS, N_SPACES, REGION_MASK, REGION_OF, REGION_SIZE,
    SPACE_COLOR, SPACE_NUMBER,
};
use crate::engine::{Micro, Pending, State, DIE_EXTRA, DIE_TOWNHALL};
use crate::heuristic;
use crate::tiles::{
    self, building_type, color_of, livestock_of, monastery_effect, type_of, TileType, AREA_SCORE,
    PHASE_BONUS,
};

pub const N_FEATS: usize = 936; // was 934 (3 animals); +2 for the 4th animal's mask bit (me+opp)

/// Encoder version. A net declares its encoder by its INPUT DIM (936 -> V1,
/// N_FEATS_V2 -> V2 — inferred at model load), so v1 and v2 nets can face each
/// other in the same gate and the serving wasm picks the right encoder from
/// whatever model blob it fetched.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Enc {
    V1,
    V2,
    /// P4b attention rows (tokfeats.rs): 32x28 tokens + mask + state = 1024.
    Tokens,
}

impl Enc {
    pub fn from_in_dim(d: usize) -> Enc {
        match d {
            N_FEATS => Enc::V1,
            N_FEATS_V2 => Enc::V2,
            crate::tokfeats::N_FEATS_TOK => Enc::Tokens,
            _ => panic!("unknown encoder input dim {d}"),
        }
    }
    pub fn n_feats(self) -> usize {
        match self {
            Enc::V1 => N_FEATS,
            Enc::V2 => N_FEATS_V2,
            Enc::Tokens => crate::tokfeats::N_FEATS_TOK,
        }
    }
}

/// Encode `s` for `seat` under the given encoder version.
pub fn encode(enc: Enc, s: &State, seat: usize) -> Vec<f32> {
    match enc {
        Enc::V1 => features(s, seat),
        Enc::V2 => features_v2(s, seat),
        Enc::Tokens => crate::tokfeats::encode_row(s, seat),
    }
}

#[inline]
pub(crate) fn tile_sub(code: u16) -> f32 {
    if code == 0 {
        return 0.0;
    }
    match type_of(code) {
        TileType::Building => building_type(code) as f32 / 8.0,
        TileType::Livestock => livestock_of(code).1 as f32 / 4.0,
        TileType::Monastery => monastery_effect(code) as f32 / 26.0,
        _ => 0.0,
    }
}

#[inline]
fn push_tile(out: &mut Vec<f32>, code: u16) {
    let mut onehot = [0.0f32; 6];
    if code != 0 {
        onehot[type_of(code) as usize] = 1.0;
    }
    out.extend_from_slice(&onehot);
    out.push(tile_sub(code));
}

/// Depots (0-based mask) a seat could take a hex from with die value `v`
/// (monastery-12 widens to the wrapping neighbors) — feature-side mirror of
/// engine's allowed-values rule.
fn depot_mask_for(s: &State, seat: usize, v: u8) -> u8 {
    let m12 = s.players[seat].has_effect(12);
    let mut m = 1u8 << (v - 1);
    if m12 {
        m |= 1 << (v % 6);
        m |= 1 << ((v + 4) % 6);
    }
    m
}

pub fn features(s: &State, seat: usize) -> Vec<f32> {
    let opp = 1 - seat;
    let me = &s.players[seat];
    let op = &s.players[opp];
    let b = s.boards[seat] as usize;
    let ob = s.boards[opp] as usize;
    let mut out: Vec<f32> = Vec::with_capacity(N_FEATS);

    // ── A: meta (16) ──
    for p in 0..5 {
        out.push((s.phase as usize == p) as u8 as f32);
    }
    for r in 1..=5 {
        out.push((s.round as usize == r) as u8 as f32);
    }
    out.push(((4 - s.phase as i32) * 5 + (5 - s.round as i32)) as f32 / 25.0);
    out.push(PHASE_BONUS[s.phase as usize] as f32 / 10.0);
    out.push((s.start_player as usize == seat) as u8 as f32);
    out.push(s.track_pos[seat] as f32 / 6.0);
    out.push(s.track_pos[opp] as f32 / 6.0);
    out.push((s.track_order()[0] as usize == seat) as u8 as f32);

    // ── B: next claimable bonus value per color (6) ──
    for c in 0..6 {
        out.push(match s.bonus_left[c] {
            2 => 1.0,
            1 => 0.4,
            _ => 0.0,
        });
    }

    // ── C: pending/micro context (21) ──
    let ptag = match s.pending {
        Pending::None => 0,
        Pending::ExtraAction => 1,
        Pending::ShipChoose => 2,
        Pending::ShipAdj { .. } => 3,
        Pending::GoodsPick { .. } => 4,
        Pending::BuildingTake { .. } => 5,
        Pending::Warehouse => 6,
        Pending::Townhall => 7,
    };
    for t in 0..8 {
        out.push((ptag == t) as u8 as f32);
    }
    let (mtag, mdie, mval, mslot) = match s.micro {
        Micro::None => (0, 0i8, 0u8, 0u8),
        Micro::DieMenu { die, value } => (1, die, value, 0),
        Micro::PlaceWhere { die, value, slot } => (2, die, value, slot),
        Micro::M6 => (3, 0, 0, 0),
    };
    for t in 0..4 {
        out.push((mtag == t) as u8 as f32);
    }
    for v in 1..=6u8 {
        out.push((mval == v) as u8 as f32);
    }
    out.push((mdie == DIE_EXTRA) as u8 as f32);
    out.push((mdie == DIE_TOWNHALL) as u8 as f32);
    out.push(mslot as f32 / 3.0);

    // ── D: per-seat resources (73 x 2) ──
    let scores = s.final_scores();
    for pseat in [seat, opp] {
        let p = &s.players[pseat];
        let sc = scores[pseat];
        out.push((p.vp as f32 / 100.0).tanh());
        out.push((p.silver as f32 / 10.0).tanh());
        out.push((p.workers as f32 / 10.0).tanh());
        for c in 0..6 {
            out.push((p.goods[c] as f32 / 3.0).tanh());
        }
        out.push(p.distinct_goods() as f32 / 3.0);
        for c in 0..6 {
            out.push((p.sold[c] as f32 / 7.0).tanh());
        }
        out.push(p.storage_len() as f32 / 3.0);
        out.push(p.mines as f32 / 12.0);
        for bt in 0..8 {
            out.push(p.buildings[bt] as f32 / 7.0);
        }
        for a in 0..crate::tiles::N_ANIMALS {
            out.push((p.livestock_mask >> a & 1) as f32);
        }
        for e in 0..26 {
            out.push((p.mon_mask >> e & 1) as f32);
        }
        out.push((s.endgame_monastery_vp(pseat) as f32 / 20.0).tanh());
        for die in 0..2 {
            let d = s.dice[pseat][die];
            for v in 1..=6u8 {
                out.push((d.value == v && !d.used) as u8 as f32);
            }
            out.push(d.used as u8 as f32);
            out.push(d.adjusted as u8 as f32);
        }
        out.push((sc as f32 / 100.0).tanh());
    }

    // ── E: heuristic baselines (4) ──
    let vme = heuristic::value(s, seat);
    let vop = heuristic::value(s, opp);
    out.push(((vme / 100.0) as f32).tanh());
    out.push(((vop / 100.0) as f32).tanh());
    out.push(((vme - vop) / heuristic::SQUASH).tanh() as f32);
    out.push(((scores[seat] - scores[opp]) as f32 / 24.0).tanh());

    // ── F: my board per-space block (37 x 14) ──
    let my_unused: Vec<u8> = (0..2)
        .filter(|&i| !s.dice[seat][i].used)
        .map(|i| s.dice[seat][i].value)
        .collect();
    let storage_colors: u8 = (0..me.storage_len())
        .map(|i| 1u8 << color_of(me.storage[i]))
        .fold(0, |a, x| a | x);
    for sid in 0..N_SPACES {
        let color = SPACE_COLOR[b][sid];
        for c in 0..6 {
            out.push((color == c) as u8 as f32);
        }
        out.push(SPACE_NUMBER[b][sid] as f32 / 6.0);
        let filled = me.filled >> sid & 1 == 1;
        out.push(filled as u8 as f32);
        let r = REGION_OF[b][sid] as usize;
        let size = REGION_SIZE[b][r] as u32;
        let rfill = (me.filled & REGION_MASK[b][r]).count_ones();
        out.push(rfill as f32 / size as f32);
        out.push((size - rfill) as f32 / 8.0);
        out.push(if rfill < size {
            (AREA_SCORE[size as usize - 1] + PHASE_BONUS[s.phase as usize]) as f32 / 46.0
        } else {
            0.0
        });
        out.push((me.filled & NEIGHBOR_MASK[sid] != 0) as u8 as f32);
        out.push((!filled && storage_colors >> color & 1 == 1) as u8 as f32);
        out.push(
            my_unused.iter().any(|&v| v == SPACE_NUMBER[b][sid]) as u8 as f32,
        );
    }

    // ── G: opp board summary (14) ──
    for c in 0..6 {
        let cm = COLOR_MASK[ob][c];
        out.push((op.filled & cm).count_ones() as f32 / cm.count_ones() as f32);
    }
    for c in 0..6 {
        let mut best = 0.0f32;
        for r in 0..N_REGIONS[ob] as usize {
            if crate::boards_gen::REGION_COLOR[ob][r] as usize != c {
                continue;
            }
            let size = REGION_SIZE[ob][r] as u32;
            let f = (op.filled & REGION_MASK[ob][r]).count_ones();
            if f < size {
                let frac = f as f32 / size as f32;
                if frac > best {
                    best = frac;
                }
            }
        }
        out.push(best);
    }
    let mut completes = 0;
    for r in 0..N_REGIONS[ob] as usize {
        let m = REGION_MASK[ob][r];
        if op.filled & m == m {
            completes += 1;
        }
    }
    out.push(completes as f32 / 10.0);
    out.push((N_SPACES as u32 - op.filled.count_ones()) as f32 / 37.0);

    // ── H: depots (6 x 22 + 29) ──
    let opp_unused: Vec<u8> = (0..2)
        .filter(|&i| !s.dice[opp][i].used)
        .map(|i| s.dice[opp][i].value)
        .collect();
    let my_take_mask: u8 = my_unused.iter().fold(0, |a, &v| a | depot_mask_for(s, seat, v));
    let opp_take_mask: u8 = opp_unused.iter().fold(0, |a, &v| a | depot_mask_for(s, opp, v));
    for d in 0..6 {
        push_tile(&mut out, s.depot_hex[d][0]);
        push_tile(&mut out, s.depot_hex[d][1]);
        for c in 0..6 {
            out.push((s.depot_goods[d][c] as f32 / 3.0).tanh());
        }
        out.push((my_take_mask >> d & 1) as f32);
        out.push((opp_take_mask >> d & 1) as f32);
    }
    for slot in 0..4 {
        push_tile(&mut out, s.black_depot[slot]);
    }
    out.push(
        (!s.black_used && me.silver >= 2 && me.free_storage() && s.black_depot[0] != 0) as u8
            as f32,
    );

    // ── I: storage (my 3 x 9, opp 3 x 7) ──
    for slot in 0..3 {
        let code = me.storage[slot];
        push_tile(&mut out, code);
        if code == 0 {
            out.push(0.0);
            out.push(0.0);
        } else {
            let color = color_of(code);
            let mut any = 0u32;
            let mut now = 0u32;
            for sid in 0..N_SPACES {
                if me.filled >> sid & 1 == 1 || SPACE_COLOR[b][sid] != color {
                    continue;
                }
                if me.filled & NEIGHBOR_MASK[sid] == 0 {
                    continue;
                }
                any += 1;
                if my_unused.iter().any(|&v| v == SPACE_NUMBER[b][sid]) {
                    now += 1;
                }
            }
            out.push(any as f32 / 10.0);
            out.push(now as f32 / 10.0);
        }
    }
    for slot in 0..3 {
        push_tile(&mut out, op.storage[slot]);
    }

    debug_assert_eq!(out.len(), N_FEATS);
    out
}

// ─── Encoder v2: v1 + Group J (feature round 2) ──────────────────────────────
// The v1 encoder gives offered tiles only a type one-hot + ONE subtype scalar
// (effect_id/26 for monasteries), and NO time interaction — but a tile's worth
// is clock-coupled: continuous monasteries/mines compound over the phases LEFT
// (better early), endgame scorers pay by their CURRENT multiplier count plus
// accumulation headroom. Group J hands the net those two curves precomputed
// (the Spender per-card take_value lesson: explicit interactions >> making an
// MLP learn identity-decode x clock internally), plus 26-way monastery-effect
// availability unions (the subtype scalar can't be sliced into 26 categories).
//
// FROZEN LAYOUT v2 = the FULL v1 block (934, unchanged) + Group J (144):
//   J1 (12) my time-value per numbered-depot hex slot (d0s0,d0s1,..,d5s1)
//   J2  (4) my time-value per black-depot slot
//   J3  (3) my time-value per own-storage slot
//   J4 (16) OPP time-value per depot+black slot (denial read)
//   J5 (38) is-continuous-mon / is-endgame-mon per the 19 offer slots
//   J6 (19) my endgame multiplier count per slot (/8, 0 unless endgame mon)
//   J7 (26) takeable monastery-effect union (depots + black)
//   J8 (26) my-storage monastery-effect union

pub const N_FEATS_V2: usize = N_FEATS + 144;

/// Time-coupled acquisition value of `code` for `seat`, in rough VP-equivalents
/// (silver ~ 1 VP per final_scores; worker ~ 0.5). Deliberately encodes ONLY
/// the clock-coupled income/effect stream — placement/region VP is already
/// richly covered by the per-space board block. Ships/livestock/buildings/
/// castles have ~time-flat worth (their type one-hots suffice) -> 0 here.
pub(crate) fn tile_time_value(s: &State, seat: usize, code: u16) -> f32 {
    if code == 0 {
        return 0.0;
    }
    let p = &s.players[seat];
    let phases_left = (5 - s.phase) as f32; // phase-ends still ahead (incl. current)
    let v = match type_of(code) {
        TileType::Mine => {
            // 1 silver/phase, +0.5 worker-value/phase if monastery 2 is held
            let per_phase = 1.0 + if p.has_effect(2) { 0.5 } else { 0.0 };
            per_phase * phases_left
        }
        TileType::Monastery => {
            let e = monastery_effect(code);
            match e {
                // continuous: hand per-phase yield estimate x phases left
                1 => 0.3 * phases_left,                          // multi-building towns
                2 => 0.5 * (p.mines as f32 + 0.5) * phases_left, // worker per mine
                3 => 0.6 * phases_left,                          // +1 silver per sell
                4 => 0.3 * phases_left,                          // worker per sell
                5 => 0.6 * phases_left,                          // ship: adjacent depot goods
                6 => 0.5 * phases_left,                          // building->storage option
                7 => 0.5 * phases_left,                          // +1 VP per scoring livestock
                8 => 0.4 * phases_left,                          // adjust 2 per worker
                9..=11 => 0.4 * phases_left,                     // free die shift (place)
                12 => 0.5 * phases_left,                         // free die shift (take)
                13 => 0.7 * phases_left,                         // +1 silver on take-workers
                14 => 0.7 * phases_left,                         // take-workers gives 4
                // endgame: exact current multiplier + accumulation headroom
                15 => {
                    let kinds = p.sold.iter().filter(|&&c| c > 0).count() as f32;
                    2.0 * kinds + 2.0 * phases_left * 0.4
                }
                16..=23 => {
                    const EFF_BT: [u8; 8] = [
                        tiles::B_MARKET,
                        tiles::B_WATCHTOWER,
                        tiles::B_CARPENTER,
                        tiles::B_CHURCH,
                        tiles::B_WAREHOUSE,
                        tiles::B_BOARDING,
                        tiles::B_BANK,
                        tiles::B_TOWNHALL,
                    ];
                    let bt = EFF_BT[(e - 16) as usize] as usize;
                    4.0 * p.buildings[bt] as f32 + 4.0 * phases_left * 0.3
                }
                24 => {
                    4.0 * p.livestock_mask.count_ones() as f32 + 4.0 * phases_left * 0.3
                }
                25 => {
                    let sold: u32 = p.sold.iter().map(|&c| c as u32).sum();
                    sold as f32 + phases_left * 0.8
                }
                26 => 3.0 * p.bonus_claimed as f32 + 3.0 * phases_left * 0.3,
                _ => 0.0,
            }
        }
        _ => 0.0,
    };
    (v / 8.0).tanh()
}

/// My endgame-multiplier count for an offered endgame monastery (0 otherwise).
pub(crate) fn endgame_mult(s: &State, seat: usize, code: u16) -> f32 {
    if code == 0 || type_of(code) != TileType::Monastery {
        return 0.0;
    }
    let p = &s.players[seat];
    let e = monastery_effect(code);
    let n = match e {
        15 => p.sold.iter().filter(|&&c| c > 0).count() as u32,
        16..=23 => {
            const EFF_BT: [u8; 8] = [
                tiles::B_MARKET,
                tiles::B_WATCHTOWER,
                tiles::B_CARPENTER,
                tiles::B_CHURCH,
                tiles::B_WAREHOUSE,
                tiles::B_BOARDING,
                tiles::B_BANK,
                tiles::B_TOWNHALL,
            ];
            p.buildings[EFF_BT[(e - 16) as usize] as usize] as u32
        }
        24 => p.livestock_mask.count_ones(),
        25 => p.sold.iter().map(|&c| c as u32).sum(),
        26 => p.bonus_claimed as u32,
        _ => return 0.0,
    };
    (n as f32 / 8.0).min(1.0)
}

/// v2 = the full v1 vector (byte-identical prefix) + Group J appended.
pub fn features_v2(s: &State, seat: usize) -> Vec<f32> {
    let mut out = features(s, seat);
    out.reserve(N_FEATS_V2 - N_FEATS);
    let opp = 1 - seat;
    // the 19 offer slots in a fixed order: 12 numbered-depot hexes, 4 black, 3 storage
    let mut slots: [u16; 19] = [0; 19];
    for d in 0..6 {
        slots[d * 2] = s.depot_hex[d][0];
        slots[d * 2 + 1] = s.depot_hex[d][1];
    }
    for k in 0..4 {
        slots[12 + k] = s.black_depot[k];
    }
    for k in 0..3 {
        slots[16 + k] = s.players[seat].storage[k];
    }
    // J1-J3: my time-values (12 + 4 + 3)
    for &c in &slots {
        out.push(tile_time_value(s, seat, c));
    }
    // J4: opp time-values for the CONTESTED slots (depots + black)
    for &c in &slots[..16] {
        out.push(tile_time_value(s, opp, c));
    }
    // J5: continuous/endgame monastery flags per slot
    for &c in &slots {
        let (cont, end) = if c != 0 && type_of(c) == TileType::Monastery {
            let e = monastery_effect(c);
            ((e <= 14) as u8 as f32, (e >= 15) as u8 as f32)
        } else {
            (0.0, 0.0)
        };
        out.push(cont);
        out.push(end);
    }
    // J6: my endgame multiplier count per slot
    for &c in &slots {
        out.push(endgame_mult(s, seat, c));
    }
    // J7: takeable monastery-effect union (depots + black)
    let mut take_union = [0.0f32; 26];
    for &c in &slots[..16] {
        if c != 0 && type_of(c) == TileType::Monastery {
            take_union[(monastery_effect(c) - 1) as usize] = 1.0;
        }
    }
    out.extend_from_slice(&take_union);
    // J8: my storage monastery-effect union
    let mut sto_union = [0.0f32; 26];
    for &c in &slots[16..] {
        if c != 0 && type_of(c) == TileType::Monastery {
            sto_union[(monastery_effect(c) - 1) as usize] = 1.0;
        }
    }
    out.extend_from_slice(&sto_union);

    debug_assert_eq!(out.len(), N_FEATS_V2);
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::{apply, legal_actions, State};
    use crate::rng::Rng;

    #[test]
    fn feature_len_and_bounds_hold_over_playouts() {
        let mut rng = Rng::new(7);
        for seed in 0..10u64 {
            let mut s = State::new_game([(seed % 9) as u8, ((seed * 5) % 9) as u8], seed);
            while !s.is_over() {
                for seat in 0..2 {
                    let f = features(&s, seat);
                    assert_eq!(f.len(), N_FEATS);
                    for (i, &x) in f.iter().enumerate() {
                        assert!(
                            x.is_finite() && (-1.5..=1.5).contains(&x),
                            "feature {i} out of range: {x} (seed {seed})"
                        );
                    }
                }
                let acts = legal_actions(&s);
                let a = acts[rng.below(acts.len())];
                apply(&mut s, a);
            }
        }
    }

    #[test]
    fn v2_extends_v1_with_bounded_group_j() {
        let mut rng = Rng::new(11);
        for seed in 20..28u64 {
            let mut s = State::new_game([(seed % 9) as u8, ((seed * 7) % 9) as u8], seed);
            while !s.is_over() {
                for seat in 0..2 {
                    let f1 = features(&s, seat);
                    let f2 = features_v2(&s, seat);
                    assert_eq!(f2.len(), N_FEATS_V2);
                    // v1 must be a byte-identical prefix of v2 (frozen layout)
                    assert_eq!(&f2[..N_FEATS], &f1[..]);
                    for (i, &x) in f2[N_FEATS..].iter().enumerate() {
                        assert!(
                            x.is_finite() && (-1.5..=1.5).contains(&x),
                            "group-J feature {i} out of range: {x} (seed {seed})"
                        );
                    }
                }
                let acts = legal_actions(&s);
                let a = acts[rng.below(acts.len())];
                apply(&mut s, a);
            }
        }
    }
}
