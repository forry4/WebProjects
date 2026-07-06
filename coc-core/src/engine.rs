//! Compact Castles of Crimson simulator — the int-state port of
//! games/castles_of_crimson/engine.py (2-player). Rule parity is proven by
//! tests/engine_parity.rs (fixture replay against the authoritative Python engine);
//! see coc-core/tools/gen_engine_fixtures.py.
//!
//! Deliberate omissions vs the Python engine (search/training don't need them):
//! undo snapshots (`turn_undo`/`undo_turn`), the move log (`moves` — display-only;
//! VP is banked incrementally), `vp_breakdown`, `turn_number`/`round_in_game`, and
//! the legacy always-0 `ship_advance_pending`.
//!
//! ## Action space (N_ACTIONS = 102) — micro-decomposition
//! One engine.py move = a short chain of micro-actions ("spend die → menu →
//! place-slot → space"). `Micro` tracks the chain position; it is ALWAYS `Micro::None`
//! at engine-move boundaries. The same heads are shared by normal die actions, the
//! castle `extra_action` (via XVALUE), `building_take`/monastery-6 (via TAKE_HEX),
//! and `townhall` (via PLACE_SLOT with the number check off).
//!
//! ## Parity-critical details mirrored from engine.py
//! - `legal` adjust affordability uses cost from the CURRENT value (conservative),
//!   while apply charges the NET distance from `orig` (refunds) — both mirrored.
//! - ship_choose offers ALL 6 depots (even empty); taking from an empty depot
//!   resolves to nothing.
//! - Pendings are cleared BEFORE their sub-action runs, so a chained pending set by
//!   the sub-action (e.g. extra-action places a ship) survives.
//! - Dice are rolled in SEAT order (not round order): p0d0 p0d1 p1d0 p1d1 white.
//! - `_draw` pops from the END of a pile; `_draw_type` scans from index 0.
//! - Depot replenish DISCARDS leftover hexes; goods on depots persist.
//!
//! Design: the whole State is fixed-capacity inline storage (no heap except the
//! parity-test-only `dice_script`, empty in production) — clone ≈ one memcpy.
//! Containers with Python-list semantics (storage, depot hexes, black depot,
//! supplies, goods queue) are compacted arrays: live items first, removal shifts
//! left, exactly like `list.pop(i)`.

use crate::boards_gen::{
    COLOR_MASK, MAX_REGIONS, NEIGHBOR_MASK, N_SPACES, REGION_MASK, REGION_OF, REGION_SIZE,
    SPACE_COLOR, SPACE_NUMBER,
};
use crate::rng::Rng;
use crate::tiles::{
    self, building_type, color_of, livestock_of, monastery_effect, type_of, TileType,
    AREA_SCORE, BLACK_FILL_2P, BLACK_SUPPLY_LEN, DEPOT_PLAN, GOODS_PER_PHASE, GOODS_POOL_LEN,
    N_BUILDINGS, N_GOODS, PHASE_BONUS, SELL_SILVER, START_GOODS, START_SILVER, SUPPLY_LEN,
    T_START_CASTLE,
};

pub const NUM_PLAYERS: usize = 2;

// ── mode / phase / winner ────────────────────────────────────────────────────
pub const SETUP: u8 = 0;
pub const PLAYING: u8 = 1;
pub const OVER: u8 = 2;

/// `winner`: WIN_NONE while running; WIN_DRAW kept for shape-compat (unreachable in
/// 2p — the track tiebreak always resolves); else the winning seat.
pub const WIN_NONE: i8 = -2;
pub const WIN_DRAW: i8 = -1;

pub const NUM_TRACK_SPACES: u8 = 7;
pub const NO_SPACE: u8 = 255;

// ── fixed action space ───────────────────────────────────────────────────────
pub const A_END_TURN: usize = 0;
pub const A_SPEND_DIE0: usize = 1; // +die (0..1)
pub const A_ADJUST0: usize = 3; // +die*6 + (to-1)  → 3..=14
pub const A_BUY_BLACK0: usize = 15; // +slot (0..3)
pub const A_DISCARD0: usize = 19; // +slot (0..2)
pub const A_M6: usize = 22;
pub const A_SKIP: usize = 23;
pub const A_XVALUE0: usize = 24; // +(v-1) → 24..=29
pub const A_SHIP_DEPOT0: usize = 30; // +(d-1) → 30..=35
pub const A_GOODS0: usize = 36; // +color → 36..=41
pub const A_WH0: usize = 42; // +color → 42..=47
pub const A_TAKE_HEX0: usize = 48; // +(depot-1)*2 + slot → 48..=59
pub const A_SELL: usize = 60;
pub const A_WORKERS: usize = 61;
pub const A_PLACE_SLOT0: usize = 62; // +slot (0..2)
pub const A_SPACE0: usize = 65; // +space (0..36)
pub const N_ACTIONS: usize = 102;

// pseudo-die markers inside Micro (die field)
pub const DIE_EXTRA: i8 = -1; // castle extra action (value chosen via XVALUE)
pub const DIE_TOWNHALL: i8 = -2; // townhall placement (no die, number ignored)

// ── dice ─────────────────────────────────────────────────────────────────────
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Die {
    pub value: u8,
    pub orig: u8,
    pub used: bool,
    pub adjusted: bool,
}

// ── pending sub-decisions (engine.py pending_kind, ctx inlined) ──────────────
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Pending {
    None,
    ExtraAction,
    ShipChoose,
    /// `cands` = bitmask (0-based depots) captured at offer time — engine.py stores
    /// the candidate list in ctx (the source depot is NOT recoverable from it).
    ShipAdj { cands: u8 },
    /// `colors` = bitmask of still-offered NEW colors; `m5_from` = -1 or the depot
    /// whose monastery-5 adjacent offer fires when the pick phase ends.
    GoodsPick { depot: u8, colors: u8, m5_from: i8 },
    /// `types` = bitmask of allowed TileType discriminants.
    BuildingTake { types: u8 },
    Warehouse,
    Townhall,
}

// ── micro decision state (the action-space decomposition; NOT in engine.py) ──
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Micro {
    None,
    /// A die (or pseudo-die) value is committed; choose what to do with it.
    DieMenu { die: i8, value: u8 },
    /// A storage slot is committed; choose the target space.
    PlaceWhere { die: i8, value: u8, slot: u8 },
    /// Monastery-6: choose a building tile from a depot.
    M6,
}

// ── per-player state ──────────────────────────────────────────────────────────
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PlayerState {
    pub duchy: [u16; N_SPACES],
    pub filled: u64,
    pub castle_sid: u8,
    pub storage: [u16; 3],
    pub goods: [u8; N_GOODS],
    pub sold: [u8; N_GOODS],
    pub workers: i16,
    pub silver: i16,
    pub vp: i16,
    pub bonus_claimed: u8,
    pub mines: u8,
    pub buildings: [u8; N_BUILDINGS],
    pub livestock_mask: u8,
    pub mon_mask: u32,
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
    pub fn free_storage(&self) -> bool {
        self.storage[2] == 0
    }
    #[inline]
    pub fn distinct_goods(&self) -> usize {
        self.goods.iter().filter(|&&c| c > 0).count()
    }
    #[inline]
    pub fn has_effect(&self, eid: u8) -> bool {
        self.mon_mask >> (eid - 1) & 1 == 1
    }
}

// ── whole game state ──────────────────────────────────────────────────────────
#[derive(Clone, PartialEq, Debug)]
pub struct State {
    pub boards: [u8; 2],
    pub phase: u8, // 0..4 = A..E
    pub round: u8, // 1..5
    pub mode: u8,  // SETUP / PLAYING / OVER
    pub winner: i8,

    pub track_pos: [u8; 2],
    /// Seat on TOP when both share a track space (top acts first), else -1.
    pub track_top: i8,
    pub round_order: [u8; 2],
    pub start_player: u8,
    pub turn: i8,

    pub white_die: u8,
    pub dice: [[Die; 2]; 2],
    pub black_used: bool,
    pub m6_used: bool,

    pub depot_hex: [[u16; 2]; 6],
    pub depot_goods: [[u8; N_GOODS]; 6],
    pub black_depot: [u16; 4],

    pub supply: [u16; SUPPLY_LEN],
    pub supply_len: u8,
    pub black_supply: [u16; BLACK_SUPPLY_LEN],
    pub black_supply_len: u8,
    pub goods_supply: [u8; GOODS_POOL_LEN],
    pub goods_supply_len: u8,
    pub goods_queue: [u8; GOODS_PER_PHASE],
    pub goods_queue_len: u8,

    pub bonus_left: [u8; N_GOODS],

    pub players: [PlayerState; 2],

    pub pending_pid: i8,
    pub pending: Pending,
    pub micro: Micro,

    pub rng: u64,
    /// Parity-test dice injection (front-popped); always empty in production/search.
    pub dice_script: Vec<u8>,
}

// ── compacted-array helpers (Python-list semantics) ───────────────────────────
#[inline]
fn arr_len(a: &[u16]) -> usize {
    a.iter().take_while(|&&t| t != 0).count()
}

#[inline]
fn arr_push(a: &mut [u16], code: u16) {
    let n = arr_len(a);
    debug_assert!(n < a.len());
    a[n] = code;
}

/// Remove index i, shifting left (list.pop(i)).
#[inline]
fn arr_remove(a: &mut [u16], i: usize) -> u16 {
    let n = arr_len(a);
    debug_assert!(i < n);
    let out = a[i];
    for k in i..n - 1 {
        a[k] = a[k + 1];
    }
    a[n - 1] = 0;
    out
}

impl State {
    pub fn shell(boards: [u8; 2]) -> Self {
        State {
            boards,
            phase: 0,
            round: 1,
            mode: SETUP,
            winner: WIN_NONE,
            track_pos: [0; 2],
            track_top: 0, // both stacked on space 0, start player (seat 0) on top
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
            goods_queue: [0; GOODS_PER_PHASE],
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

    /// Fresh game (self-play/serving path; parity fixtures build State from a
    /// projection instead). Mirrors engine.new_game for 2 players.
    pub fn new_game(boards: [u8; 2], seed: u64) -> Self {
        let mut s = State::shell(boards);
        let mut rng = Rng::new(seed ^ 0x5EED_C0C0_0000_0001);

        let (nb, bl) = tiles::build_supply();
        let mut supply = nb.to_vec();
        let mut black = bl.to_vec();
        let mut goods = tiles::build_goods_pool().to_vec();
        rng.shuffle(&mut supply);
        rng.shuffle(&mut black);
        rng.shuffle(&mut goods);
        s.supply[..supply.len()].copy_from_slice(&supply);
        s.supply_len = supply.len() as u8;
        s.black_supply[..black.len()].copy_from_slice(&black);
        s.black_supply_len = black.len() as u8;
        s.goods_supply[..goods.len()].copy_from_slice(&goods);
        s.goods_supply_len = goods.len() as u8;

        // Starting resources: workers seat-dependent (start player 1, next 2);
        // 1 silver + 3 goods each (drawn from the END of the pool).
        for seat in 0..2 {
            s.players[seat].workers = seat as i16 + 1;
            s.players[seat].silver = START_SILVER;
            for _ in 0..START_GOODS {
                let c = s.goods_draw();
                s.players[seat].goods[c as usize] += 1;
            }
        }
        s.rng = rng.state();
        s.replenish_depots();
        s.refill_goods_queue();
        s
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

    #[inline]
    pub fn actor(&self) -> i8 {
        if self.pending_pid >= 0 {
            self.pending_pid
        } else {
            self.turn
        }
    }

    #[inline]
    pub fn is_over(&self) -> bool {
        self.mode == OVER
    }

    // ── draw piles ────────────────────────────────────────────────────────────
    // NB: the main supply is only ever drawn BY TYPE (_draw_type); end-pop (_draw)
    // applies to the black/goods piles only — same as engine.py.

    /// Pop the FIRST tile of the given type (scan from index 0 — _draw_type).
    fn supply_pop_type(&mut self, ttype: TileType) -> Option<u16> {
        let n = self.supply_len as usize;
        for i in 0..n {
            if type_of(self.supply[i]) == ttype {
                let out = self.supply[i];
                for k in i..n - 1 {
                    self.supply[k] = self.supply[k + 1];
                }
                self.supply[n - 1] = 0;
                self.supply_len -= 1;
                return Some(out);
            }
        }
        None
    }

    #[inline]
    fn black_pop(&mut self) -> Option<u16> {
        if self.black_supply_len == 0 {
            return None;
        }
        self.black_supply_len -= 1;
        Some(self.black_supply[self.black_supply_len as usize])
    }

    #[inline]
    fn goods_draw(&mut self) -> u8 {
        debug_assert!(self.goods_supply_len > 0);
        self.goods_supply_len -= 1;
        self.goods_supply[self.goods_supply_len as usize]
    }

    // ── phase-start dealing ───────────────────────────────────────────────────
    /// Discard leftover hexes and refill each depot per DEPOT_PLAN; refill the
    /// black depot (leftovers discarded). Goods on depots persist.
    pub fn replenish_depots(&mut self) {
        for d in 0..6 {
            let mut hexes = [0u16; 2];
            let mut n = 0;
            for &ttype in &DEPOT_PLAN[d] {
                if let Some(t) = self.supply_pop_type(ttype) {
                    hexes[n] = t;
                    n += 1;
                }
            }
            self.depot_hex[d] = hexes;
        }
        let mut bd = [0u16; 4];
        for slot in bd.iter_mut().take(BLACK_FILL_2P) {
            match self.black_pop() {
                Some(t) => *slot = t,
                None => break,
            }
        }
        self.black_depot = bd;
    }

    pub fn refill_goods_queue(&mut self) {
        let mut q = [0u8; GOODS_PER_PHASE];
        let mut n = 0;
        for slot in q.iter_mut().take(GOODS_PER_PHASE) {
            if self.goods_supply_len == 0 {
                break;
            }
            *slot = self.goods_draw();
            n += 1;
        }
        self.goods_queue = q;
        self.goods_queue_len = n;
    }

    // ── track ─────────────────────────────────────────────────────────────────
    fn advance_track(&mut self, seat: usize, n: u8) {
        if n == 0 {
            return;
        }
        let dest = (self.track_pos[seat] + n).min(NUM_TRACK_SPACES - 1);
        self.track_pos[seat] = dest;
        // The mover lands on TOP of the destination stack.
        self.track_top = if self.track_pos[0] == self.track_pos[1] {
            seat as i8
        } else {
            -1
        };
    }

    /// Turn order, front-to-back: furthest-forward first; on a shared space the
    /// TOP of the stack acts first.
    pub fn track_order(&self) -> [u8; 2] {
        if self.track_pos[0] == self.track_pos[1] {
            let top = self.track_top.max(0) as u8;
            [top, 1 - top]
        } else if self.track_pos[0] > self.track_pos[1] {
            [0, 1]
        } else {
            [1, 0]
        }
    }

    // ── round / phase lifecycle ───────────────────────────────────────────────
    fn begin_round(&mut self) {
        self.round_order = self.track_order();
        self.start_player = self.round_order[0];
        // Dice roll in SEAT order (engine.py iterates game["order"]).
        for seat in 0..2 {
            let a = self.roll_d6();
            let b = self.roll_d6();
            self.dice[seat] = [
                Die { value: a, orig: a, used: false, adjusted: false },
                Die { value: b, orig: b, used: false, adjusted: false },
            ];
        }
        self.white_die = self.roll_d6();
        // Start player places one goods tile on the depot matching the white die.
        if self.goods_queue_len > 0 {
            let c = self.goods_queue[0];
            for k in 0..(self.goods_queue_len as usize - 1) {
                self.goods_queue[k] = self.goods_queue[k + 1];
            }
            self.goods_queue_len -= 1;
            self.goods_queue[self.goods_queue_len as usize] = 0;
            self.depot_goods[self.white_die as usize - 1][c as usize] += 1;
        }
        self.turn = self.start_player as i8;
        self.black_used = false;
        self.m6_used = false;
    }

    fn advance_turn(&mut self) {
        let idx = if self.round_order[0] as i8 == self.turn { 0 } else { 1 };
        if idx + 1 < NUM_PLAYERS {
            self.turn = self.round_order[idx + 1] as i8;
            self.black_used = false;
            self.m6_used = false;
        } else {
            self.advance_round();
        }
    }

    fn advance_round(&mut self) {
        if self.round < 5 {
            self.round += 1;
            self.begin_round();
        } else {
            self.advance_phase();
        }
    }

    fn end_of_phase(&mut self) {
        for seat in 0..2 {
            let mines = self.players[seat].mines as i16;
            if mines > 0 {
                self.players[seat].silver += mines;
                if self.players[seat].has_effect(2) {
                    self.players[seat].workers += mines;
                }
            }
        }
    }

    fn advance_phase(&mut self) {
        self.end_of_phase();
        if (self.phase as usize) + 1 < tiles::N_PHASES {
            self.phase += 1;
            self.round = 1;
            self.replenish_depots();
            self.refill_goods_queue();
            self.begin_round();
        } else {
            self.mode = OVER;
            self.turn = -1;
            self.winner = self.compute_winner();
        }
    }

    // ── scoring ───────────────────────────────────────────────────────────────
    pub fn endgame_monastery_vp(&self, seat: usize) -> i16 {
        let p = &self.players[seat];
        let mut total = 0i16;
        if p.has_effect(15) {
            total += 2 * p.sold.iter().filter(|&&c| c > 0).count() as i16;
        }
        // effects 16..=23 map to building types (MONASTERY_BUILDING_SCORING):
        // 16=market 17=watchtower 18=carpenter 19=church 20=warehouse 21=boarding
        // 22=bank 23=townhall
        const EFF_BT: [(u8, usize); 8] = [
            (16, tiles::B_MARKET as usize),
            (17, tiles::B_WATCHTOWER as usize),
            (18, tiles::B_CARPENTER as usize),
            (19, tiles::B_CHURCH as usize),
            (20, tiles::B_WAREHOUSE as usize),
            (21, tiles::B_BOARDING as usize),
            (22, tiles::B_BANK as usize),
            (23, tiles::B_TOWNHALL as usize),
        ];
        for &(eid, bt) in &EFF_BT {
            if p.has_effect(eid) {
                total += 4 * p.buildings[bt] as i16;
            }
        }
        if p.has_effect(24) {
            total += 4 * (p.livestock_mask.count_ones() as i16);
        }
        if p.has_effect(25) {
            total += p.sold.iter().map(|&c| c as i16).sum::<i16>();
        }
        if p.has_effect(26) {
            total += 3 * p.bonus_claimed as i16;
        }
        total
    }

    pub fn final_scores(&self) -> [i16; 2] {
        let mut out = [0i16; 2];
        for seat in 0..2 {
            let p = &self.players[seat];
            out[seat] = p.vp
                + p.goods.iter().map(|&c| c as i16).sum::<i16>()
                + p.silver
                + p.workers / 2
                + self.endgame_monastery_vp(seat);
        }
        out
    }

    fn compute_winner(&self) -> i8 {
        let scores = self.final_scores();
        if scores[0] != scores[1] {
            return if scores[0] > scores[1] { 0 } else { 1 };
        }
        let empties =
            |seat: usize| N_SPACES as u32 - self.players[seat].filled.count_ones();
        if empties(0) != empties(1) {
            return if empties(0) < empties(1) { 0 } else { 1 };
        }
        // Farthest BACK on the track wins = last in track order.
        self.track_order()[1] as i8
    }

    fn score_area_and_bonus(&mut self, seat: usize, sid: usize) {
        let b = self.boards[seat] as usize;
        let filled = self.players[seat].filled;
        let region = REGION_OF[b][sid] as usize;
        let rmask = REGION_MASK[b][region];
        if filled & rmask == rmask {
            let size = REGION_SIZE[b][region] as usize;
            let vp = AREA_SCORE[size - 1] + PHASE_BONUS[self.phase as usize];
            self.players[seat].vp += vp;
        }
        let color = SPACE_COLOR[b][sid] as usize;
        let cmask = COLOR_MASK[b][color];
        if filled & cmask == cmask && self.bonus_left[color] > 0 {
            let val = if self.bonus_left[color] == 2 {
                tiles::bonus_first(NUM_PLAYERS)
            } else {
                tiles::bonus_second(NUM_PLAYERS)
            };
            self.bonus_left[color] -= 1;
            self.players[seat].bonus_claimed += 1;
            self.players[seat].vp += val;
        }
    }

    fn score_livestock(&mut self, seat: usize, sid: usize, code: u16) {
        let (animal, _count) = livestock_of(code);
        let b = self.boards[seat] as usize;
        let rmask = REGION_MASK[b][REGION_OF[b][sid] as usize];
        let mut total = 0i16;
        let mut same_n = 0i16;
        let mut m = rmask;
        while m != 0 {
            let s = m.trailing_zeros() as usize;
            m &= m - 1;
            let t = self.players[seat].duchy[s];
            if (T_LIVESTOCK_LO..=T_LIVESTOCK_HI).contains(&t) {
                let (a, c) = livestock_of(t);
                if a == animal {
                    total += c as i16;
                    same_n += 1;
                }
            }
        }
        let mut gain = total;
        if self.players[seat].has_effect(7) {
            gain += same_n;
        }
        self.players[seat].vp += gain;
        self.players[seat].livestock_mask |= 1 << animal;
    }

    // ── goods movement ────────────────────────────────────────────────────────
    /// Take every goods tile of the mask's colors from `depot` (0-based). A color
    /// already held always stacks; a new color needs a free slot (<=3 distinct).
    fn take_goods_colors(&mut self, seat: usize, depot: usize, colors: u8) {
        for c in 0..N_GOODS {
            if colors >> c & 1 == 0 || self.depot_goods[depot][c] == 0 {
                continue;
            }
            let held = self.players[seat].goods[c] > 0;
            if held || self.players[seat].distinct_goods() < 3 {
                self.players[seat].goods[c] += self.depot_goods[depot][c];
                self.depot_goods[depot][c] = 0;
            }
        }
    }

    /// Take goods from `depot` (0-based). Already-held colors stack; new colors fill
    /// free slots. Returns Some(new-colors mask) when the player must pick (more new
    /// colors than free slots), else None (everything storable was taken).
    fn take_goods_from_depot(&mut self, seat: usize, depot: usize) -> Option<u8> {
        // 1. always take colors already held
        for c in 0..N_GOODS {
            if self.players[seat].goods[c] > 0 && self.depot_goods[depot][c] > 0 {
                self.players[seat].goods[c] += self.depot_goods[depot][c];
                self.depot_goods[depot][c] = 0;
            }
        }
        // 2. distinct NEW colors still in the depot
        let mut new_mask = 0u8;
        for c in 0..N_GOODS {
            if self.depot_goods[depot][c] > 0 && self.players[seat].goods[c] == 0 {
                new_mask |= 1 << c;
            }
        }
        let free = 3usize.saturating_sub(self.players[seat].distinct_goods());
        if free == 0 || new_mask == 0 {
            return None;
        }
        if new_mask.count_ones() as usize <= free {
            self.take_goods_colors(seat, depot, new_mask);
            return None;
        }
        Some(new_mask)
    }

    /// Monastery 5: after taking from `from` (0-based), optionally take from an
    /// adjacent depot that holds goods.
    fn m5_adjacent_mask(&self, from: usize) -> u8 {
        let mut mask = 0u8;
        for d in [from.wrapping_sub(1), from + 1] {
            if d < 6 && self.depot_goods[d].iter().any(|&c| c > 0) {
                mask |= 1 << d;
            }
        }
        mask
    }

    fn offer_m5_adjacent(&mut self, seat: usize, from: usize) {
        if self.players[seat].has_effect(5) {
            let cands = self.m5_adjacent_mask(from);
            if cands != 0 {
                self.pending_pid = seat as i8;
                self.pending = Pending::ShipAdj { cands };
            }
        }
    }

    // ── placement effects ─────────────────────────────────────────────────────
    fn building_take_pending(&mut self, seat: usize, types: u8) {
        if !self.players[seat].free_storage() {
            return;
        }
        let any = self.depot_hex.iter().flatten().any(|&t| t != 0 && types >> (type_of(t) as u8) & 1 == 1);
        if any {
            self.pending_pid = seat as i8;
            self.pending = Pending::BuildingTake { types };
        }
    }

    fn place_building_effect(&mut self, seat: usize, sid: usize, code: u16) {
        let bt = building_type(code);
        let b = self.boards[seat] as usize;
        let region = REGION_OF[b][sid] as usize;
        self.players[seat].buildings[bt as usize] += 1;
        self.players[seat].town_bldg[region] |= 1 << bt;
        match bt {
            tiles::B_BOARDING => self.players[seat].workers += 4,
            tiles::B_BANK => self.players[seat].silver += 2,
            tiles::B_WATCHTOWER => self.players[seat].vp += 4,
            tiles::B_MARKET => self.building_take_pending(
                seat,
                (1 << TileType::Ship as u8) | (1 << TileType::Livestock as u8),
            ),
            tiles::B_CARPENTER => {
                self.building_take_pending(seat, 1 << TileType::Building as u8)
            }
            tiles::B_CHURCH => self.building_take_pending(
                seat,
                (1 << TileType::Mine as u8)
                    | (1 << TileType::Monastery as u8)
                    | (1 << TileType::Castle as u8),
            ),
            tiles::B_WAREHOUSE => {
                if self.players[seat].distinct_goods() > 0 {
                    self.pending_pid = seat as i8;
                    self.pending = Pending::Warehouse;
                }
            }
            tiles::B_TOWNHALL => {
                if self.players[seat].storage_len() > 0 {
                    self.pending_pid = seat as i8;
                    self.pending = Pending::Townhall;
                }
            }
            _ => {}
        }
    }

    fn place_ship_effect(&mut self, seat: usize) {
        self.advance_track(seat, 1);
        let total: u32 = self
            .depot_goods
            .iter()
            .map(|d| d.iter().map(|&c| c as u32).sum::<u32>())
            .sum();
        if total > 0 {
            self.pending_pid = seat as i8;
            self.pending = Pending::ShipChoose;
        }
    }

    fn on_tile_placed(&mut self, seat: usize, sid: usize, code: u16) {
        let t = type_of(code);
        if t == TileType::Mine {
            self.players[seat].mines += 1;
        }
        // Region/color completion scores BEFORE the tile's own ability.
        self.score_area_and_bonus(seat, sid);
        match t {
            TileType::Livestock => self.score_livestock(seat, sid, code),
            TileType::Building => self.place_building_effect(seat, sid, code),
            TileType::Ship => self.place_ship_effect(seat),
            TileType::Castle => {
                self.pending_pid = seat as i8;
                self.pending = Pending::ExtraAction;
            }
            TileType::Monastery => {
                let eid = monastery_effect(code);
                self.players[seat].mon_mask |= 1 << (eid - 1);
            }
            TileType::Mine => {}
        }
    }

    // ── action cores (shared by die-menu and pending paths) ───────────────────
    fn sell_color(&mut self, seat: usize, color: usize) {
        let p = &mut self.players[seat];
        p.silver += if p.has_effect(3) { 2 } else { SELL_SILVER };
        let count = p.goods[color];
        p.vp += tiles::sell_vp_per_tile(NUM_PLAYERS) * count as i16;
        if p.has_effect(4) {
            p.workers += 1;
        }
        p.goods[color] = 0;
        p.sold[color] += count;
    }

    fn do_take_workers(&mut self, seat: usize) {
        let p = &mut self.players[seat];
        p.workers += if p.has_effect(14) { 4 } else { 2 };
        if p.has_effect(13) {
            p.silver += 1;
        }
    }

    /// Place storage[slot] on `sid` (legality pre-checked) + all placement effects.
    fn do_place_tile(&mut self, seat: usize, slot: usize, sid: usize) {
        let code = arr_remove(&mut self.players[seat].storage, slot);
        self.players[seat].duchy[sid] = code;
        self.players[seat].filled |= 1 << sid;
        self.on_tile_placed(seat, sid, code);
    }

    // ── small rule helpers ────────────────────────────────────────────────────
    #[inline]
    fn adjust_cost(&self, seat: usize, frm: u8, to: u8) -> i16 {
        let a = (to as i16 - frm as i16).rem_euclid(6);
        let b = (frm as i16 - to as i16).rem_euclid(6);
        let steps = a.min(b);
        let per = if self.players[seat].has_effect(8) { 2 } else { 1 };
        (steps + per - 1) / per
    }

    /// Bitmask over die values 1..6 (bit v-1): v alone, or v±1 wrapping on a free shift.
    #[inline]
    fn allowed_mask(v: u8, free_shift: bool) -> u8 {
        if !free_shift {
            return 1 << (v - 1);
        }
        let up = v % 6 + 1;
        let down = (v + 4) % 6 + 1; // (v-2) mod 6 + 1
        (1 << (v - 1)) | (1 << (up - 1)) | (1 << (down - 1))
    }

    #[inline]
    fn free_shift_for_tile(&self, seat: usize, t: TileType) -> bool {
        let p = &self.players[seat];
        match t {
            TileType::Building => p.has_effect(9),
            TileType::Ship | TileType::Livestock => p.has_effect(10),
            TileType::Castle | TileType::Mine | TileType::Monastery => p.has_effect(11),
        }
    }

    #[inline]
    fn has_placed_neighbor(&self, seat: usize, sid: usize) -> bool {
        self.players[seat].filled & NEIGHBOR_MASK[sid] != 0
    }

    #[inline]
    fn building_town_ok(&self, seat: usize, code: u16, sid: usize) -> bool {
        if type_of(code) != TileType::Building || self.players[seat].has_effect(1) {
            return true;
        }
        let b = self.boards[seat] as usize;
        let region = REGION_OF[b][sid] as usize;
        self.players[seat].town_bldg[region] >> building_type(code) & 1 == 0
    }

    /// Bitmask of legal target spaces for placing `code` with `number_mask` allowed
    /// die numbers (or any number when `ignore_number`).
    fn legal_space_mask(&self, seat: usize, code: u16, number_mask: u8, ignore_number: bool) -> u64 {
        let b = self.boards[seat] as usize;
        let color = color_of(code);
        let p = &self.players[seat];
        let mut out = 0u64;
        for sid in 0..N_SPACES {
            if p.filled >> sid & 1 == 1 {
                continue;
            }
            if SPACE_COLOR[b][sid] != color {
                continue;
            }
            if !ignore_number && number_mask >> (SPACE_NUMBER[b][sid] - 1) & 1 == 0 {
                continue;
            }
            if !self.has_placed_neighbor(seat, sid) {
                continue;
            }
            if !self.building_town_ok(seat, code, sid) {
                continue;
            }
            out |= 1 << sid;
        }
        out
    }

    /// The A_SPACE legality mask for a committed PlaceWhere micro state.
    fn place_where_mask(&self, seat: usize, die: i8, value: u8, slot: usize) -> u64 {
        let code = self.players[seat].storage[slot];
        debug_assert!(code != 0);
        if die == DIE_TOWNHALL {
            self.legal_space_mask(seat, code, 0, true)
        } else {
            let nm = Self::allowed_mask(value, self.free_shift_for_tile(seat, type_of(code)));
            self.legal_space_mask(seat, code, nm, false)
        }
    }

    /// Depots (0-based mask) this seat may take a hex from with die value `v`.
    #[inline]
    fn take_hex_depot_mask(&self, seat: usize, v: u8) -> u8 {
        Self::allowed_mask(v, self.players[seat].has_effect(12))
    }

    /// Whether die `die`'s menu holds a REAL action (sell / take-hex / place) —
    /// the flat-move notion behind ai.py `_legal`'s "productive" test.
    fn die_menu_has_real_action(&self, seat: usize, die: usize) -> bool {
        let v = self.dice[seat][die].value;
        if self.players[seat].goods[v as usize - 1] > 0 {
            return true;
        }
        if self.players[seat].free_storage() {
            let dmask = self.take_hex_depot_mask(seat, v);
            for d in 0..6 {
                if dmask >> d & 1 == 1 && self.depot_hex[d][0] != 0 {
                    return true;
                }
            }
        }
        for slot in 0..self.players[seat].storage_len() {
            if self.place_where_mask(seat, die as i8, v, slot) != 0 {
                return true;
            }
        }
        false
    }

    /// Any flat "productive" move at the main level (not workers/adjust/end/skip):
    /// a real die-menu action, a black buy, or a monastery-6 take.
    fn main_productive(&self, seat: usize) -> bool {
        let p = &self.players[seat];
        for die in 0..2 {
            if !self.dice[seat][die].used && self.die_menu_has_real_action(seat, die) {
                return true;
            }
        }
        if !self.black_used && p.silver >= 2 && p.free_storage() && self.black_depot[0] != 0 {
            return true;
        }
        if p.has_effect(6) && !self.m6_used && p.workers >= 2 && p.free_storage() {
            let any = self
                .depot_hex
                .iter()
                .flatten()
                .any(|&t| t != 0 && type_of(t) == TileType::Building);
            if any {
                return true;
            }
        }
        false
    }
}

const T_LIVESTOCK_LO: u16 = tiles::T_LIVESTOCK0;
const T_LIVESTOCK_HI: u16 = tiles::T_LIVESTOCK0 + 8;

// ── legal actions ─────────────────────────────────────────────────────────────
/// Exactly mirrors engine.py `legal_moves` (through the micro-decomposition) — the
/// parity-test surface. Search uses `legal_actions` (pruned) instead.
pub fn legal_actions_full(s: &State) -> Vec<usize> {
    let mut out = Vec::new();
    if s.is_over() {
        return out;
    }
    let seat = s.actor() as usize;

    if s.mode == SETUP {
        let b = s.boards[seat] as usize;
        for sid in 0..N_SPACES {
            if SPACE_COLOR[b][sid] == TileType::Castle as u8
                && s.players[seat].filled >> sid & 1 == 0
            {
                out.push(A_SPACE0 + sid);
            }
        }
        return out;
    }

    match s.micro {
        Micro::DieMenu { die, value } => {
            // Same items as engine.py's per-die enumeration / _legal_extra_actions:
            // take_workers (always), sell (if held), take_hex (storage room), place.
            out.push(A_WORKERS);
            if s.players[seat].goods[value as usize - 1] > 0 {
                out.push(A_SELL);
            }
            if s.players[seat].free_storage() {
                let dmask = s.take_hex_depot_mask(seat, value);
                for d in 0..6 {
                    if dmask >> d & 1 == 0 {
                        continue;
                    }
                    for slot in 0..2 {
                        if s.depot_hex[d][slot] != 0 {
                            out.push(A_TAKE_HEX0 + d * 2 + slot);
                        }
                    }
                }
            }
            for slot in 0..s.players[seat].storage_len() {
                if s.place_where_mask(seat, die, value, slot) != 0 {
                    out.push(A_PLACE_SLOT0 + slot);
                }
            }
        }
        Micro::PlaceWhere { die, value, slot } => {
            let mut m = s.place_where_mask(seat, die, value, slot as usize);
            while m != 0 {
                let sid = m.trailing_zeros() as usize;
                m &= m - 1;
                out.push(A_SPACE0 + sid);
            }
        }
        Micro::M6 => {
            for d in 0..6 {
                for slot in 0..2 {
                    let t = s.depot_hex[d][slot];
                    if t != 0 && type_of(t) == TileType::Building {
                        out.push(A_TAKE_HEX0 + d * 2 + slot);
                    }
                }
            }
        }
        Micro::None => match s.pending {
            Pending::ExtraAction => {
                // take_workers is always a legal sub, so every value is offerable.
                for v in 0..6 {
                    out.push(A_XVALUE0 + v);
                }
                out.push(A_SKIP);
            }
            Pending::ShipChoose => {
                // Engine offers ALL 6 depots, even empty ones.
                for d in 0..6 {
                    out.push(A_SHIP_DEPOT0 + d);
                }
                out.push(A_SKIP);
            }
            Pending::ShipAdj { cands } => {
                for d in 0..6 {
                    if cands >> d & 1 == 1 {
                        out.push(A_SHIP_DEPOT0 + d);
                    }
                }
                out.push(A_SKIP);
            }
            Pending::GoodsPick { colors, .. } => {
                for c in 0..N_GOODS {
                    if colors >> c & 1 == 1
                        && (s.players[seat].goods[c] > 0 || s.players[seat].distinct_goods() < 3)
                    {
                        out.push(A_GOODS0 + c);
                    }
                }
                out.push(A_SKIP);
            }
            Pending::BuildingTake { types } => {
                for d in 0..6 {
                    for slot in 0..2 {
                        let t = s.depot_hex[d][slot];
                        if t != 0 && types >> (type_of(t) as u8) & 1 == 1 {
                            out.push(A_TAKE_HEX0 + d * 2 + slot);
                        }
                    }
                }
                out.push(A_SKIP);
            }
            Pending::Warehouse => {
                for c in 0..N_GOODS {
                    if s.players[seat].goods[c] > 0 {
                        out.push(A_WH0 + c);
                    }
                }
                out.push(A_SKIP);
            }
            Pending::Townhall => {
                for slot in 0..s.players[seat].storage_len() {
                    if s.place_where_mask(seat, DIE_TOWNHALL, 0, slot) != 0 {
                        out.push(A_PLACE_SLOT0 + slot);
                    }
                }
                out.push(A_SKIP);
            }
            Pending::None => {
                let p = &s.players[seat];
                out.push(A_END_TURN);
                for die in 0..2 {
                    let d = s.dice[seat][die];
                    if d.used {
                        continue;
                    }
                    out.push(A_SPEND_DIE0 + die); // take_workers is always available
                    for to in 1..=6u8 {
                        if to == d.value {
                            continue;
                        }
                        // Engine legal_moves affordability: cost from the CURRENT
                        // value (conservative; apply charges net-from-orig).
                        if s.adjust_cost(seat, d.value, to) <= p.workers {
                            out.push(A_ADJUST0 + die * 6 + (to as usize - 1));
                        }
                    }
                }
                if !s.black_used && p.silver >= 2 && p.free_storage() {
                    for slot in 0..4 {
                        if s.black_depot[slot] != 0 {
                            out.push(A_BUY_BLACK0 + slot);
                        }
                    }
                }
                if !p.free_storage() {
                    for slot in 0..3 {
                        out.push(A_DISCARD0 + slot);
                    }
                }
                if p.has_effect(6) && !s.m6_used && p.workers >= 2 && p.free_storage() {
                    let any = s
                        .depot_hex
                        .iter()
                        .flatten()
                        .any(|&t| t != 0 && type_of(t) == TileType::Building);
                    if any {
                        out.push(A_M6);
                    }
                }
            }
        },
    }
    out
}

/// Search-facing legal actions — the ai.py `_legal` pruning in micro space
/// (strictly-dominated moves only; never empties a decision):
/// - never discard a stored tile;
/// - never re-adjust an already-adjusted die;
/// - with an adjusted die, drop its wasteful take_workers while a REAL action
///   remains anywhere (in micro space: drop A_WORKERS inside its menu, and drop
///   its SPEND_DIE entirely when workers was the menu's only content);
/// - with an unused die, never voluntarily end the turn.
pub fn legal_actions(s: &State) -> Vec<usize> {
    let mut out = legal_actions_full(s);
    if s.is_over() || s.mode == SETUP {
        return out;
    }
    let seat = s.actor() as usize;
    match s.micro {
        Micro::DieMenu { die, .. } if die >= 0 => {
            if s.dice[seat][die as usize].adjusted && out.len() > 1 && s.main_productive(seat) {
                out.retain(|&a| a != A_WORKERS);
            }
            out
        }
        Micro::None if s.pending == Pending::None => {
            out.retain(|&a| !(A_DISCARD0..A_DISCARD0 + 3).contains(&a));
            for die in 0..2 {
                if s.dice[seat][die].adjusted {
                    let lo = A_ADJUST0 + die * 6;
                    out.retain(|&a| !(lo..lo + 6).contains(&a));
                }
            }
            let productive = s.main_productive(seat);
            for die in 0..2 {
                let d = s.dice[seat][die];
                if !d.used
                    && d.adjusted
                    && productive
                    && !s.die_menu_has_real_action(seat, die)
                {
                    out.retain(|&a| a != A_SPEND_DIE0 + die);
                }
            }
            if s.dice[seat].iter().any(|d| !d.used) && out.len() > 1 {
                out.retain(|&a| a != A_END_TURN);
            }
            out
        }
        _ => out,
    }
}

// ── apply ─────────────────────────────────────────────────────────────────────
/// Apply a legal action (legality is the caller's contract — search only applies
/// actions from `legal_actions*`; the parity test asserts membership first).
pub fn apply(s: &mut State, a: usize) {
    let seat = s.actor() as usize;

    // Setup: place the starting castle.
    if s.mode == SETUP {
        debug_assert!((A_SPACE0..A_SPACE0 + N_SPACES).contains(&a));
        let sid = a - A_SPACE0;
        s.players[seat].duchy[sid] = T_START_CASTLE;
        s.players[seat].filled |= 1 << sid;
        s.players[seat].castle_sid = sid as u8;
        // Next player (seat order) who hasn't placed, else the game begins.
        let remaining = (0..2).find(|&x| s.players[x].castle_sid == NO_SPACE);
        match remaining {
            Some(x) => s.turn = x as i8,
            None => {
                s.mode = PLAYING;
                s.begin_round();
            }
        }
        return;
    }

    match s.micro {
        Micro::DieMenu { die, value } => {
            // A committed die/pseudo-die value; run the chosen core.
            match a {
                A_WORKERS => {
                    finish_menu_commit(s, seat, die);
                    s.do_take_workers(seat);
                    s.micro = Micro::None;
                }
                A_SELL => {
                    finish_menu_commit(s, seat, die);
                    s.sell_color(seat, value as usize - 1);
                    s.micro = Micro::None;
                }
                _ if (A_TAKE_HEX0..A_TAKE_HEX0 + 12).contains(&a) => {
                    let k = a - A_TAKE_HEX0;
                    let (d, slot) = (k / 2, k % 2);
                    finish_menu_commit(s, seat, die);
                    let code = arr_remove(&mut s.depot_hex[d], slot);
                    arr_push(&mut s.players[seat].storage, code);
                    s.micro = Micro::None;
                }
                _ if (A_PLACE_SLOT0..A_PLACE_SLOT0 + 3).contains(&a) => {
                    s.micro = Micro::PlaceWhere { die, value, slot: (a - A_PLACE_SLOT0) as u8 };
                }
                _ => unreachable!("illegal DieMenu action {a}"),
            }
        }
        Micro::PlaceWhere { die, value: _, slot } => {
            debug_assert!((A_SPACE0..A_SPACE0 + N_SPACES).contains(&a));
            let sid = a - A_SPACE0;
            // Clear the pending BEFORE the placement so a chained pending set by the
            // placed tile (ship/castle/building) survives — engine.py order.
            finish_menu_commit(s, seat, die);
            s.micro = Micro::None;
            s.do_place_tile(seat, slot as usize, sid);
        }
        Micro::M6 => {
            let k = a - A_TAKE_HEX0;
            let (d, slot) = (k / 2, k % 2);
            let code = arr_remove(&mut s.depot_hex[d], slot);
            arr_push(&mut s.players[seat].storage, code);
            s.players[seat].workers -= 2;
            s.m6_used = true;
            s.micro = Micro::None;
        }
        Micro::None => match s.pending {
            Pending::ExtraAction => match a {
                A_SKIP => clear_pending(s),
                _ if (A_XVALUE0..A_XVALUE0 + 6).contains(&a) => {
                    s.micro = Micro::DieMenu { die: DIE_EXTRA, value: (a - A_XVALUE0 + 1) as u8 };
                }
                _ => unreachable!("illegal ExtraAction action {a}"),
            },
            Pending::ShipChoose => match a {
                A_SKIP => clear_pending(s),
                _ => {
                    let d = a - A_SHIP_DEPOT0;
                    clear_pending(s);
                    let pick = s.take_goods_from_depot(seat, d);
                    let m5_from = if s.players[seat].has_effect(5) { d as i8 } else { -1 };
                    match pick {
                        Some(colors) => {
                            s.pending_pid = seat as i8;
                            s.pending =
                                Pending::GoodsPick { depot: d as u8, colors, m5_from };
                        }
                        None => {
                            if m5_from >= 0 {
                                s.offer_m5_adjacent(seat, d);
                            }
                        }
                    }
                }
            },
            Pending::ShipAdj { .. } => match a {
                A_SKIP => clear_pending(s),
                _ => {
                    let d = a - A_SHIP_DEPOT0;
                    clear_pending(s);
                    if let Some(colors) = s.take_goods_from_depot(seat, d) {
                        s.pending_pid = seat as i8;
                        s.pending =
                            Pending::GoodsPick { depot: d as u8, colors, m5_from: -1 };
                    }
                }
            },
            Pending::GoodsPick { depot, colors, m5_from } => match a {
                A_SKIP => {
                    // Skipping forgoes remaining colors; the m5 offer still applies.
                    clear_pending(s);
                    if m5_from >= 0 {
                        s.offer_m5_adjacent(seat, m5_from as usize);
                    }
                }
                _ => {
                    let c = a - A_GOODS0;
                    s.take_goods_colors(seat, depot as usize, 1 << c);
                    let rest = colors & !(1 << c as u8);
                    if s.players[seat].distinct_goods() >= 3 || rest == 0 {
                        clear_pending(s);
                        if m5_from >= 0 {
                            s.offer_m5_adjacent(seat, m5_from as usize);
                        }
                    } else {
                        s.pending = Pending::GoodsPick { depot, colors: rest, m5_from };
                    }
                }
            },
            Pending::BuildingTake { .. } => match a {
                A_SKIP => clear_pending(s),
                _ => {
                    let k = a - A_TAKE_HEX0;
                    let (d, slot) = (k / 2, k % 2);
                    let code = arr_remove(&mut s.depot_hex[d], slot);
                    arr_push(&mut s.players[seat].storage, code);
                    clear_pending(s);
                }
            },
            Pending::Warehouse => match a {
                A_SKIP => clear_pending(s),
                _ => {
                    let c = a - A_WH0;
                    s.sell_color(seat, c);
                    clear_pending(s);
                }
            },
            Pending::Townhall => match a {
                A_SKIP => clear_pending(s),
                _ => {
                    let slot = (a - A_PLACE_SLOT0) as u8;
                    s.micro = Micro::PlaceWhere { die: DIE_TOWNHALL, value: 0, slot };
                }
            },
            Pending::None => match a {
                A_END_TURN => s.advance_turn(),
                _ if (A_SPEND_DIE0..A_SPEND_DIE0 + 2).contains(&a) => {
                    let die = a - A_SPEND_DIE0;
                    s.micro = Micro::DieMenu { die: die as i8, value: s.dice[seat][die].value };
                }
                _ if (A_ADJUST0..A_ADJUST0 + 12).contains(&a) => {
                    let k = a - A_ADJUST0;
                    let (die, to) = (k / 6, (k % 6 + 1) as u8);
                    let d = s.dice[seat][die];
                    // NET cost from the originally-rolled value (refunds possible).
                    let delta = s.adjust_cost(seat, d.orig, to)
                        - s.adjust_cost(seat, d.orig, d.value);
                    s.players[seat].workers -= delta;
                    s.dice[seat][die].value = to;
                    s.dice[seat][die].adjusted = true;
                }
                _ if (A_BUY_BLACK0..A_BUY_BLACK0 + 4).contains(&a) => {
                    let slot = a - A_BUY_BLACK0;
                    s.players[seat].silver -= 2;
                    let code = arr_remove(&mut s.black_depot, slot);
                    arr_push(&mut s.players[seat].storage, code);
                    s.black_used = true;
                }
                _ if (A_DISCARD0..A_DISCARD0 + 3).contains(&a) => {
                    let slot = a - A_DISCARD0;
                    arr_remove(&mut s.players[seat].storage, slot);
                }
                A_M6 => s.micro = Micro::M6,
                _ => unreachable!("illegal main action {a}"),
            },
        },
    }
}

/// Completing a die-menu commit: a real die is marked used; the extra-action
/// pseudo-die clears its pending (BEFORE the core runs — engine.py order); the
/// townhall pseudo-die clears its pending likewise.
fn finish_menu_commit(s: &mut State, seat: usize, die: i8) {
    match die {
        DIE_EXTRA | DIE_TOWNHALL => clear_pending(s),
        _ => s.dice[seat][die as usize].used = true,
    }
}

#[inline]
fn clear_pending(s: &mut State) {
    s.pending_pid = -1;
    s.pending = Pending::None;
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::rng::Rng;

    /// Random playout smoke: every game completes, all listed actions apply, the
    /// mode/score invariants hold. (True rule parity is the Python differential.)
    #[test]
    fn random_playouts_complete() {
        for seed in 0..40u64 {
            let mut s = State::new_game([(seed % 9) as u8, ((seed / 9) % 9) as u8], seed);
            let mut rng = Rng::new(seed ^ 0xABCD);
            let mut steps = 0usize;
            while !s.is_over() {
                let acts = legal_actions_full(&s);
                assert!(!acts.is_empty(), "no legal actions (seed {seed}, step {steps})");
                let a = acts[rng.below(acts.len())];
                apply(&mut s, a);
                steps += 1;
                assert!(steps < 3000, "runaway game (seed {seed})");
            }
            assert!(s.winner == 0 || s.winner == 1);
            let scores = s.final_scores();
            assert!(scores[0] >= 0 && scores[1] >= 0);
            assert_eq!(s.micro, Micro::None);
            assert_eq!(s.pending, Pending::None);
        }
    }

    /// Fixed game length: exactly 5 phases x 5 rounds x 2 turns of end_turn-driven
    /// play (counting A_END_TURN applications).
    #[test]
    fn game_is_50_turns() {
        let mut s = State::new_game([0, 1], 7);
        let mut rng = Rng::new(99);
        let mut end_turns = 0;
        while !s.is_over() {
            let acts = legal_actions_full(&s);
            // bias to ending turns quickly but exercise menus occasionally
            let a = if acts.contains(&A_END_TURN) && rng.below(3) > 0 {
                A_END_TURN
            } else {
                acts[rng.below(acts.len())]
            };
            if a == A_END_TURN {
                end_turns += 1;
            }
            apply(&mut s, a);
        }
        assert_eq!(end_turns, 50);
    }
}
