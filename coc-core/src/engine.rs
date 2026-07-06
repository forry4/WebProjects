//! Compact Castles of Crimson simulator — the int-state port of
//! games/castles_of_crimson/engine.py (2-player). Rule parity is proven by
//! tests/engine_parity.rs (fixture replay against the authoritative Python engine);
//! see coc-core/tools/gen_engine_fixtures.py.
//!
//! Deliberate omissions vs the Python engine (search/training don't need them):
//! undo snapshots (`turn_undo`/`undo_turn`), the move log (`moves` — display-only;
//! VP is banked incrementally), `vp_breakdown`, and the legacy always-0
//! `ship_advance_pending`.
//!
//! Design: the whole State is fixed-capacity inline storage (no heap except the
//! parity-test-only `dice_script`, empty in production) — clone ≈ one memcpy.
//! Containers with Python-list semantics (storage, depot hexes, black depot,
//! supplies, goods queue) are compacted arrays: live items first, `T_EMPTY`/len
//! padding after; removal shifts left, exactly like `list.pop(i)`.

use crate::boards_gen::{MAX_REGIONS, N_SPACES};
use crate::rng::Rng;
use crate::tiles::{BLACK_SUPPLY_LEN, GOODS_POOL_LEN, N_BUILDINGS, N_GOODS, SUPPLY_LEN};

// ── mode / phase / winner ────────────────────────────────────────────────────
pub const SETUP: u8 = 0;
pub const PLAYING: u8 = 1;
pub const OVER: u8 = 2;

/// `winner`: WIN_NONE while running; WIN_DRAW on a full tie (engine.py returns the
/// tied pid list; the compact engine only needs "draw"); else the winning seat.
pub const WIN_NONE: i8 = -2;
pub const WIN_DRAW: i8 = -1;

pub const NUM_TRACK_SPACES: u8 = 7;
pub const NO_SPACE: u8 = 255; // castle_sid before setup placement

// ── dice ─────────────────────────────────────────────────────────────────────
/// One of a player's two round dice. `orig` is the rolled value — die-adjust cost is
/// the NET distance from `orig` (moving back toward the roll refunds workers), so it
/// must survive adjustments. `adjusted` marks a die the search shouldn't re-adjust.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Die {
    pub value: u8,
    pub orig: u8,
    pub used: bool,
    pub adjusted: bool,
}

// ── pending sub-decisions (engine.py pending_kind, ctx inlined) ──────────────
/// Engine-level pending sub-decision (survives across engine moves; server-enforced
/// in the Python engine). `pending_pid` on State says who must resolve it.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Pending {
    None,
    /// Castle placed: one extra action with a die value of the player's choice.
    ExtraAction,
    /// Ship placed: choose a numbered depot to take ALL goods from.
    ShipChoose,
    /// Monastery-5 after a ship take: optionally also take goods from a depot
    /// adjacent to `from` (the depot chosen in ShipChoose).
    ShipAdj { from: u8 },
    /// Taking goods offered more NEW colors than free slots: pick which color to
    /// keep. `colors` = bitmask of still-offered colors; `depot` = source depot;
    /// `m5_from` = pending monastery-5 continuation depot (-1 = none).
    GoodsPick { depot: u8, colors: u8, m5_from: i8 },
    /// market/carpenter/church placed: take a matching hex from any depot.
    /// `types` = bitmask of allowed TileType discriminants.
    BuildingTake { types: u8 },
    /// Warehouse placed: immediately sell one held goods color.
    Warehouse,
    /// Townhall placed: place an additional hex from storage (die number ignored).
    Townhall,
}

// ── micro decision state (the action-space decomposition; NOT in engine.py) ──
/// Sub-state of the fixed action space's micro-decomposition ("spend die → menu →
/// place → space"). Always `None` at engine-move boundaries — the parity fixtures
/// assert that invariant. `die == -1` means the ExtraAction pseudo-die.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Micro {
    None,
    /// A die (or the extra-action value) is committed; choose what to do with it.
    DieMenu { die: i8, value: u8 },
    /// A storage slot is committed; choose the target space.
    PlaceWhere { die: i8, value: u8, slot: u8, ignore_number: bool },
    /// Monastery-6: choose a building tile from a depot (workers already checked).
    M6,
}

// ── per-player state ──────────────────────────────────────────────────────────
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PlayerState {
    /// Tile code per canonical space (0 = empty).
    pub duchy: [u16; N_SPACES],
    /// Bitmask of filled spaces (mirror of duchy != 0; kept for cheap region math).
    pub filled: u64,
    /// Canonical index of the starting-castle space (NO_SPACE until setup).
    pub castle_sid: u8,
    /// Storage (≤3), compacted, Python-list order — slot addressing is load-bearing.
    pub storage: [u16; 3],
    /// Held goods count per color. At most 3 DISTINCT colors non-zero (engine rule).
    pub goods: [u8; N_GOODS],
    /// Sold goods count per color (endgame monasteries 15/25).
    pub sold: [u8; N_GOODS],
    pub workers: i16,
    pub silver: i16,
    /// Realized VP, banked incrementally (final_scores does NOT need the move log).
    pub vp: i16,
    /// Count of claimed color-bonus tiles (their VP is already in `vp`; m26 needs the count).
    pub bonus_claimed: u8,
    pub mines: u8,
    /// Placed buildings per type (endgame monasteries 16..23).
    pub buildings: [u8; N_BUILDINGS],
    /// Bitmask of distinct livestock ANIMALS placed (m24: 0=cow 1=sheep 2=pig).
    pub livestock_mask: u8,
    /// Bitmask of active monastery effects (bit eid-1 for effect ids 1..26) — the
    /// ONE dispatch site replacing engine.py's scattered `in monastery_effects` checks.
    pub mon_mask: u32,
    /// Per-region bitmask of placed building TYPES (one-per-town rule; m1 lifts it).
    pub town_bldg: [u8; MAX_REGIONS],
}

impl PlayerState {
    pub fn empty() -> Self {
        PlayerState {
            duchy: [0; N_SPACES],
            filled: 0,
            castle_sid: NO_SPACE,
            storage: [0; 3],
            goods: [0; N_GOODS],
            sold: [0; N_GOODS],
            workers: 0,
            silver: 0,
            vp: 0,
            bonus_claimed: 0,
            mines: 0,
            buildings: [0; N_BUILDINGS],
            livestock_mask: 0,
            mon_mask: 0,
            town_bldg: [0; MAX_REGIONS],
        }
    }

    #[inline]
    pub fn storage_len(&self) -> usize {
        self.storage.iter().take_while(|&&t| t != 0).count()
    }

    #[inline]
    pub fn has_effect(&self, eid: u8) -> bool {
        self.mon_mask >> (eid - 1) & 1 == 1
    }
}

// ── whole game state ──────────────────────────────────────────────────────────
#[derive(Clone, PartialEq, Debug)]
pub struct State {
    /// Board index (0..8) per seat.
    pub boards: [u8; 2],
    /// 0..4 = phase A..E.
    pub phase: u8,
    /// 1..5 within the phase.
    pub round: u8,
    /// SETUP / PLAYING / OVER.
    pub mode: u8,
    pub winner: i8,

    // turn-order track (7 spaces; 2p: positions + who's on top when stacked)
    pub track_pos: [u8; 2],
    /// Seat on TOP when both share a track space (top acts first), else -1.
    pub track_top: i8,
    pub round_order: [u8; 2],
    pub start_player: u8,
    /// Seat whose main turn it is (pending decisions override via pending_pid).
    pub turn: i8,

    pub white_die: u8,
    pub dice: [[Die; 2]; 2],
    pub black_used: bool,
    pub m6_used: bool,

    // shared market
    /// Hex tiles per numbered depot (≤2, compacted, engine list order).
    pub depot_hex: [[u16; 2]; 6],
    /// Goods count per color per numbered depot (order within a depot is irrelevant).
    pub depot_goods: [[u8; N_GOODS]; 6],
    /// Central black depot (≤4, compacted).
    pub black_depot: [u16; 4],

    // draw piles — ORDERED (hidden info is exactly these orders + future dice).
    // engine.py `_draw` pops from the END; `_draw_type` scans from index 0.
    pub supply: [u16; SUPPLY_LEN],
    pub supply_len: u8,
    pub black_supply: [u16; BLACK_SUPPLY_LEN],
    pub black_supply_len: u8,
    pub goods_supply: [u8; GOODS_POOL_LEN],
    pub goods_supply_len: u8,
    /// This phase's per-round goods (≤5, popped from the FRONT each round).
    pub goods_queue: [u8; 5],
    pub goods_queue_len: u8,

    /// Remaining color-completion bonus tiles per color (2 → first+second, 1, 0).
    pub bonus_left: [u8; N_GOODS],

    pub players: [PlayerState; 2],

    /// Seat that must resolve `pending` (-1 = none).
    pub pending_pid: i8,
    pub pending: Pending,
    pub micro: Micro,

    /// splitmix64 stream for future dice (determinize reseeds this).
    pub rng: u64,
    /// Parity-test dice injection: when non-empty, dice/white-die rolls pop from the
    /// FRONT of this script instead of the rng. Always empty in production/search.
    pub dice_script: Vec<u8>,
}

impl State {
    /// An all-empty shell (benches / builders fill it in; new_game arrives with the
    /// full engine port).
    pub fn shell(boards: [u8; 2]) -> Self {
        State {
            boards,
            phase: 0,
            round: 1,
            mode: SETUP,
            winner: WIN_NONE,
            track_pos: [0; 2],
            track_top: -1,
            round_order: [0, 1],
            start_player: 0,
            turn: 0,
            white_die: 0,
            dice: [[Die::default(); 2]; 2],
            black_used: false,
            m6_used: false,
            depot_hex: [[0; 2]; 6],
            depot_goods: [[0; N_GOODS]; 6],
            black_depot: [0; 4],
            supply: [0; SUPPLY_LEN],
            supply_len: 0,
            black_supply: [0; BLACK_SUPPLY_LEN],
            black_supply_len: 0,
            goods_supply: [0; GOODS_POOL_LEN],
            goods_supply_len: 0,
            goods_queue: [0; 5],
            goods_queue_len: 0,
            bonus_left: [2; N_GOODS],
            players: [PlayerState::empty(), PlayerState::empty()],
            pending_pid: -1,
            pending: Pending::None,
            micro: Micro::None,
            rng: 0,
            dice_script: Vec::new(),
        }
    }

    /// Roll 1..6 — from the parity dice script when present, else the rng stream.
    #[inline]
    pub fn roll_d6(&mut self) -> u8 {
        if !self.dice_script.is_empty() {
            return self.dice_script.remove(0);
        }
        let mut r = Rng::new(self.rng);
        let v = (r.below(6) + 1) as u8;
        self.rng = r.state();
        v
    }

    /// Seat that must act right now (pending resolver if set, else the turn seat).
    #[inline]
    pub fn actor(&self) -> i8 {
        if self.pending_pid >= 0 {
            self.pending_pid
        } else {
            self.turn
        }
    }
}
