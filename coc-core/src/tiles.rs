//! Static tile data for the compact engine — the int-code mirror of
//! games/castles_of_crimson/tiles.py (the 164-tile base-game supply, scoring tables,
//! depot plan). String tile ids ("h37") exist only Python-side; here a tile IS its
//! u16 code, and containers address tiles by slot.
//!
//! Tile codes (0 = empty / no tile):
//!   1            starting castle (pre-placed; never scores; not in supply)
//!   2            castle
//!   3            mine
//!   4            ship
//!   5..=13       livestock: 5 + animal*3 + (count-2)   (animal: 0=cow 1=sheep 2=pig; count 2..4)
//!   14..=21      building:  14 + building_type          (BUILDING_TYPES order)
//!   22..=47      monastery: 22 + (effect_id - 1)        (effect ids 1..26)

use crate::boards_gen::N_COLORS;

pub const T_EMPTY: u16 = 0;
pub const T_START_CASTLE: u16 = 1;
pub const T_CASTLE: u16 = 2;
pub const T_MINE: u16 = 3;
pub const T_SHIP: u16 = 4;
pub const T_LIVESTOCK0: u16 = 5; // ..=13
pub const T_BUILDING0: u16 = 14; // ..=21
pub const T_MONASTERY0: u16 = 22; // ..=47
pub const N_TILE_CODES: usize = 48;

/// Tile type, with discriminants equal to the COLOR index of the space it goes on
/// (board.py COLORS order: burgundy, blue, gray, green, beige, yellow).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
#[repr(u8)]
pub enum TileType {
    Castle = 0,    // burgundy
    Ship = 1,      // blue
    Mine = 2,      // gray
    Livestock = 3, // green
    Building = 4,  // beige
    Monastery = 5, // yellow
}

#[inline]
pub fn type_of(code: u16) -> TileType {
    match code {
        T_START_CASTLE | T_CASTLE => TileType::Castle,
        T_MINE => TileType::Mine,
        T_SHIP => TileType::Ship,
        5..=13 => TileType::Livestock,
        14..=21 => TileType::Building,
        22..=47 => TileType::Monastery,
        _ => panic!("type_of on empty/invalid tile code {code}"),
    }
}

/// The space color this tile places on (= TileType discriminant).
#[inline]
pub fn color_of(code: u16) -> u8 {
    type_of(code) as u8
}

/// Building type index (BUILDING_TYPES order) for a building tile.
#[inline]
pub fn building_type(code: u16) -> u8 {
    debug_assert!((T_BUILDING0..=21).contains(&code));
    (code - T_BUILDING0) as u8
}

/// (animal 0..2, count 2..4) for a livestock tile.
#[inline]
pub fn livestock_of(code: u16) -> (u8, u8) {
    debug_assert!((T_LIVESTOCK0..=13).contains(&code));
    let k = code - T_LIVESTOCK0;
    ((k / 3) as u8, (k % 3 + 2) as u8)
}

/// Monastery effect id (1..26) for a monastery tile.
#[inline]
pub fn monastery_effect(code: u16) -> u8 {
    debug_assert!((T_MONASTERY0..=47).contains(&code));
    (code - T_MONASTERY0 + 1) as u8
}

// ── Building types (tiles.py BUILDING_TYPES order) ──────────────────────────
pub const B_MARKET: u8 = 0;
pub const B_CARPENTER: u8 = 1;
pub const B_CHURCH: u8 = 2;
pub const B_WAREHOUSE: u8 = 3;
pub const B_BOARDING: u8 = 4;
pub const B_BANK: u8 = 5;
pub const B_TOWNHALL: u8 = 6;
pub const B_WATCHTOWER: u8 = 7;
pub const N_BUILDINGS: usize = 8;

// ── Goods (6 colors, index = die value - 1; tiles.py GOODS_COLORS order) ────
pub const N_GOODS: usize = N_COLORS; // amber rose jade cobalt plum rust

// ── Scoring tables ──────────────────────────────────────────────────────────
pub const N_PHASES: usize = 5; // A..E
pub const AREA_SCORE: [i16; 8] = [1, 3, 6, 10, 15, 21, 28, 36];
pub const PHASE_BONUS: [i16; N_PHASES] = [10, 8, 6, 4, 2];
pub const SELL_SILVER: i16 = 1;

#[inline]
pub fn sell_vp_per_tile(num_players: usize) -> i16 {
    num_players as i16
}
#[inline]
pub fn bonus_first(num_players: usize) -> i16 {
    num_players as i16 + 3
}
#[inline]
pub fn bonus_second(num_players: usize) -> i16 {
    num_players as i16
}

// ── Depot fill (2-player board) ─────────────────────────────────────────────
/// Fixed hex TYPES per numbered depot, refilled each phase (tiles.py DEPOT_PLAN).
pub const DEPOT_PLAN: [[TileType; 2]; 6] = [
    [TileType::Ship, TileType::Building],      // depot 1
    [TileType::Castle, TileType::Monastery],   // depot 2
    [TileType::Livestock, TileType::Building], // depot 3
    [TileType::Ship, TileType::Building],      // depot 4
    [TileType::Mine, TileType::Monastery],     // depot 5
    [TileType::Livestock, TileType::Building], // depot 6
];
pub const BLACK_FILL_2P: usize = 4;
pub const GOODS_PER_PHASE: usize = 5;
pub const START_SILVER: i16 = 1;
pub const START_GOODS: usize = 3;

// ── Supply construction (content mirrors tiles.build_supply; order is later
//    shuffled by the engine RNG, so only the multiset must match) ─────────────
pub const SUPPLY_LEN: usize = 124;
pub const BLACK_SUPPLY_LEN: usize = 40;
pub const GOODS_POOL_LEN: usize = 42; // 7 per color

/// (non_black[124], black[40]) tile codes, same construction order as tiles.py.
pub fn build_supply() -> ([u16; SUPPLY_LEN], [u16; BLACK_SUPPLY_LEN]) {
    let mut non_black = [0u16; SUPPLY_LEN];
    let mut black = [0u16; BLACK_SUPPLY_LEN];
    let (mut ni, mut bi) = (0, 0);

    // Buildings: 5 beige each (40), 2 black each (16).
    for bt in 0..N_BUILDINGS as u16 {
        for _ in 0..5 {
            non_black[ni] = T_BUILDING0 + bt;
            ni += 1;
        }
        for _ in 0..2 {
            black[bi] = T_BUILDING0 + bt;
            bi += 1;
        }
    }
    // Livestock: 20 green (9 kinds x2 + cow2 + sheep3), 8 black (first 8 kinds).
    let kind = |animal: u16, count: u16| T_LIVESTOCK0 + animal * 3 + (count - 2);
    for rep in 0..2 {
        let _ = rep;
        for a in 0..3 {
            for c in 2..=4 {
                non_black[ni] = kind(a, c);
                ni += 1;
            }
        }
    }
    non_black[ni] = kind(0, 2); // cow 2
    ni += 1;
    non_black[ni] = kind(1, 3); // sheep 3
    ni += 1;
    for k in 0..8u16 {
        black[bi] = T_LIVESTOCK0 + k;
        bi += 1;
    }
    // Mines: 10 gray, 2 black.
    for _ in 0..10 {
        non_black[ni] = T_MINE;
        ni += 1;
    }
    for _ in 0..2 {
        black[bi] = T_MINE;
        bi += 1;
    }
    // Ships: 20 blue, 6 black.
    for _ in 0..20 {
        non_black[ni] = T_SHIP;
        ni += 1;
    }
    for _ in 0..6 {
        black[bi] = T_SHIP;
        bi += 1;
    }
    // Castles: 14 burgundy, 2 black.
    for _ in 0..14 {
        non_black[ni] = T_CASTLE;
        ni += 1;
    }
    for _ in 0..2 {
        black[bi] = T_CASTLE;
        bi += 1;
    }
    // Monasteries: effect ids 1..20 yellow, 21..26 black.
    for eid in 1..=26u16 {
        let code = T_MONASTERY0 + eid - 1;
        if eid >= 21 {
            black[bi] = code;
            bi += 1;
        } else {
            non_black[ni] = code;
            ni += 1;
        }
    }
    assert_eq!(ni, SUPPLY_LEN);
    assert_eq!(bi, BLACK_SUPPLY_LEN);
    (non_black, black)
}

/// 42 goods (7 per color), colors 0..5.
pub fn build_goods_pool() -> [u8; GOODS_POOL_LEN] {
    let mut pool = [0u8; GOODS_POOL_LEN];
    for c in 0..6 {
        for k in 0..7 {
            pool[c * 7 + k] = c as u8;
        }
    }
    pool
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn supply_composition_is_164() {
        let (nb, b) = build_supply();
        assert_eq!(nb.len() + b.len(), 164);
        // every code valid + counts per type
        let mut counts = [0usize; N_TILE_CODES];
        for &t in nb.iter().chain(b.iter()) {
            assert!(t >= T_CASTLE && t < N_TILE_CODES as u16);
            counts[t as usize] += 1;
        }
        assert_eq!(counts[T_CASTLE as usize], 16);
        assert_eq!(counts[T_MINE as usize], 12);
        assert_eq!(counts[T_SHIP as usize], 26);
        let livestock: usize = (5..=13).map(|c| counts[c]).sum();
        assert_eq!(livestock, 28);
        let buildings: usize = (14..=21).map(|c| counts[c]).sum();
        assert_eq!(buildings, 56);
        for bt in 14..=21 {
            assert_eq!(counts[bt], 7); // 5 colored + 2 black
        }
        for eid in 22..=47 {
            assert_eq!(counts[eid], 1); // each monastery unique
        }
    }
}
