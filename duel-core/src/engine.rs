//! Spender Duel rules engine — a faithful Rust port of `games/spender_duel/engine.py`.
//!
//! The Python is AUTHORITATIVE and live in production: where the two disagree, this file
//! is wrong by definition. Parity is gated by `src/bin/parity.rs`, which replays Python-
//! recorded games and compares a total projection of the state after EVERY move.
//!
//! Encoding (see `cards.rs`): white=0 blue=1 green=2 red=3 black=4, pearl=5, gold=6.
//! Card index = deck order (L1 0..29, L2 30..53, L3 54..66); -1 = empty cell/slot.
//! Levels are 0-BASED here (0..2) where the Python uses the strings "1".."3".
//!
//! DELIBERATE OMISSIONS (not rules, and not in the parity projection):
//!   * the move log — no rule reads it; it exists for the server's replay/review.
//!   * `turn_undo`/`_snapshot_turn` — reachable only via the `undo_turn` move, which
//!     `legal_moves` never emits; search sets `_skip_undo` and pays nothing for it.
//!   * `player_view` — a serving-side redaction, not a rule.
//!
//! RANDOMNESS: the Python's only rng use inside a move is the bag shuffle in
//! `_fill_board`. That is abstracted behind `Shuffler` so parity can SCRIPT it with the
//! exact post-shuffle order Python got, and a later MCTS can plug in a real rng.

use crate::cards::{
    ABILITY, AB_AGAIN, AB_NONE, AB_PRIVILEGE, AB_STEAL, AB_TAKE_SAME, BONUS, BONUS_COUNT,
    BONUS_WILD, COST, CROWNS, GOLD, LEVEL_OFF, LEVEL_OF, MAX_RESERVED, MAX_TOKENS, N_CARDS,
    N_COLORS, N_TOKENS, PEARL, PTS, ROYAL_ABILITY, ROYAL_PTS, SPIRAL_ORDER, WIN_COLOR_POINTS,
    WIN_CROWNS, WIN_POINTS,
};

// ─── Phases / pending kinds ──────────────────────────────────────────────────
pub const PLAYING: u8 = 0;
pub const OVER: u8 = 1;

/// Pending-kind codes. These MUST match `gen_engine_fixtures.KIND_IX` — the projection
/// prints them raw.
pub const PK_NONE: u8 = 0;
pub const PK_TAKE_SAME: u8 = 1;
pub const PK_STEAL: u8 = 2;
pub const PK_CHOOSE_ROYAL: u8 = 3;
pub const PK_DISCARD: u8 = 4;

/// Win-condition codes (projected as the Python's strings).
pub const WC_NONE: u8 = 0;
pub const WC_POINTS: u8 = 1;
pub const WC_CROWNS: u8 = 2;
pub const WC_COLOR: u8 = 3;

pub const EMPTY: i8 = -1;
pub const N_CELLS: usize = 25;
pub const CROWN_THRESHOLDS: [i32; 2] = [3, 6];

/// Scan directions for `_line_moves`: E, S, SE, SW. Only the "positive" half is scanned
/// because each line is generated from its lexicographically-first cell.
const UNIT_DIRS: [(i32, i32); 4] = [(0, 1), (1, 0), (1, 1), (1, -1)];

// ─── Moves ───────────────────────────────────────────────────────────────────
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ReserveSrc {
    Pyramid { level: usize, slot: usize },
    Deck { level: usize },
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum BuySrc {
    Pyramid,
    Reserve,
}

#[derive(Clone, PartialEq, Eq, Debug)]
pub enum Move {
    // optional actions (the turn continues afterwards)
    UsePrivilege { cell: usize },
    Replenish,
    // mandatory actions
    Take { cells: Vec<usize> },
    Reserve { gold_cell: usize, src: ReserveSrc },
    /// `as_color` is -1 except on a wild card, where it names the group it joins.
    Buy { card: usize, from: BuySrc, as_color: i8 },
    Pass,
    // pending resolvers
    TakeSame { cell: usize },
    Steal { color: usize },
    ChooseRoyal { royal: usize },
    Discard { color: usize },
    SkipPending,
}

// ─── Bag shuffling (the engine's only in-move randomness) ────────────────────
/// Mirrors the `rng` argument of Python's `_fill_board`: the ONLY thing it does with the
/// rng is shuffle the bag in place, so that is the whole seam.
pub trait Shuffler {
    fn shuffle(&mut self, bag: &mut Vec<u8>);
}

/// Replays the exact post-shuffle bag orders Python produced (the coc-core `dice_script`
/// trick): parity compares RULES, and never has to reimplement Mersenne Twister.
pub struct ScriptedFills {
    pub queue: std::collections::VecDeque<Vec<u8>>,
}

impl ScriptedFills {
    pub fn new(fills: Vec<Vec<u8>>) -> Self {
        Self { queue: fills.into_iter().collect() }
    }
    pub fn is_empty(&self) -> bool {
        self.queue.is_empty()
    }
}

impl Shuffler for ScriptedFills {
    fn shuffle(&mut self, bag: &mut Vec<u8>) {
        let next = self.queue.pop_front().expect("fill script exhausted: Rust shuffled more often than Python did");
        debug_assert_eq!(next.len(), bag.len(), "scripted fill has a different bag size");
        *bag = next;
    }
}

/// A `Shuffler` that refuses to run — for call sites that must provably never fill
/// (asserts the no-fill assumption instead of silently inventing an order).
pub struct NoShuffle;
impl Shuffler for NoShuffle {
    fn shuffle(&mut self, _bag: &mut Vec<u8>) {
        panic!("bag shuffle attempted with NoShuffle");
    }
}

// ─── State ───────────────────────────────────────────────────────────────────
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub enum Via {
    #[default]
    None,
    Card(usize),
    Royal(usize),
}

/// The pending sub-decision's context. Only the fields its kind uses are meaningful.
#[derive(Clone, PartialEq, Eq, Debug, Default)]
pub struct Pending {
    /// take_same: the token to duplicate.
    pub color: i32,
    /// take_same: board cells holding it (the emptied CELL changes line geometry, so
    /// which one you take is a real choice).
    pub cells: Vec<usize>,
    /// steal: TOKEN indices (a steal may target a pearl, not just a gem).
    pub colors: Vec<usize>,
    /// choose_royal: the royals still on offer.
    pub royals: Vec<usize>,
    /// discard: how many over the cap. Informational — `_after_action` recomputes it.
    pub excess: i32,
    pub via: Via,
}

#[derive(Clone, PartialEq, Eq, Debug, Default)]
pub struct Player {
    pub tokens: [i32; N_TOKENS],
    pub privileges: i32,
    pub reserved: Vec<usize>,
    /// Which reserves were BLIND deck draws. The log deliberately omits the card id for
    /// those, so this is the only record — and the AI needs it to determinize the
    /// opponent's hand rather than reading the true cards.
    pub reserved_from_deck: Vec<usize>,
    /// (card, as_color) — as_color is -1 unless the card is wild.
    pub purchased: Vec<(usize, i8)>,
    pub royals: Vec<usize>,
    pub royals_claimed: i32,
}

#[derive(Clone, PartialEq, Eq, Debug)]
pub struct State {
    pub phase: u8,
    pub winner: i32,
    pub win_condition: u8,
    pub win_color: i32,
    pub turn: usize,
    pub turn_number: i32,
    pub replenished: bool,
    pub again: bool,
    pub board: [i8; N_CELLS],
    pub bag: Vec<u8>,
    pub privileges_board: i32,
    pub decks: [Vec<usize>; 3],
    /// -1 = an exhausted slot (its deck ran out).
    pub pyramid: [Vec<i32>; 3],
    pub royals_available: Vec<usize>,
    pub players: [Player; 2],
    pub pending_pid: i32,
    pub pending_kind: u8,
    pub pending: Pending,
}

#[inline]
pub(crate) fn is_gem_or_pearl(tok: i8) -> bool {
    tok != EMPTY && tok != GOLD as i8
}

#[inline]
pub(crate) fn opponent(pid: usize) -> usize {
    1 - pid
}

/// Card index -> the Python's `d{level}_{idx:02d}` id. Needed because the parity
/// projection prints the pending's `via` as that literal string.
pub fn card_id_str(ci: usize) -> String {
    let lvl = LEVEL_OF[ci] as usize;
    format!("d{}_{:02}", lvl, ci - LEVEL_OFF[lvl - 1])
}

pub fn royal_id_str(ri: usize) -> String {
    format!("r{}", ri)
}

// ─── Derived player quantities ───────────────────────────────────────────────
/// Effective bonus per colour; a wild counts in the group it was attached to, and a
/// bonus-less card counts nowhere (Python's `if col in b` guard).
pub fn bonuses_of(p: &Player) -> [i32; N_COLORS] {
    let mut b = [0i32; N_COLORS];
    for &(cid, as_color) in &p.purchased {
        let bon = BONUS[cid];
        let col = if bon == BONUS_WILD { as_color } else { bon };
        if (0..N_COLORS as i8).contains(&col) {
            b[col as usize] += BONUS_COUNT[cid];
        }
    }
    b
}

pub fn crowns_of(p: &Player) -> i32 {
    p.purchased.iter().map(|&(c, _)| CROWNS[c]).sum()
}

pub fn points_of(p: &Player) -> i32 {
    let cards: i32 = p.purchased.iter().map(|&(c, _)| PTS[c]).sum();
    let royals: i32 = p.royals.iter().map(|&r| ROYAL_PTS[r]).sum();
    cards + royals
}

/// Card points per bonus-colour group (victory condition 3). Wilds count in their
/// attached group; bonus-less cards and royals count in no group.
pub fn color_points_of(p: &Player) -> [i32; N_COLORS] {
    let mut cp = [0i32; N_COLORS];
    for &(cid, as_color) in &p.purchased {
        let bon = BONUS[cid];
        let col = if bon == BONUS_WILD { as_color } else { bon };
        if (0..N_COLORS as i8).contains(&col) {
            cp[col as usize] += PTS[cid];
        }
    }
    cp
}

fn royal_entitlement(p: &Player) -> i32 {
    let crowns = crowns_of(p);
    CROWN_THRESHOLDS.iter().filter(|&&t| crowns >= t).count() as i32
}

// ─── Payment ─────────────────────────────────────────────────────────────────
/// Same answer as Python's `can_afford`: colours get their bonus deducted (floor 0 is
/// implicit in the `need > 0` guard), pearls never do, and gold covers the shortfall.
pub fn can_afford(card: usize, tokens: &[i32; N_TOKENS], bonuses: &[i32; N_COLORS]) -> bool {
    let mut gold = 0;
    for col in 0..=PEARL {
        let n = COST[card][col];
        // Python iterates the card's cost DICT, which has no zero entries — so skipping
        // zeros here visits exactly the same colours in the same order.
        if n == 0 {
            continue;
        }
        let need = if col < N_COLORS { n - bonuses[col] } else { n };
        if need > 0 {
            let short = need - tokens[col];
            if short > 0 {
                gold += short;
            }
        }
    }
    gold <= tokens[GOLD]
}

/// Auto-payment: colour/pearl tokens first, gold covers any shortfall.
///
/// The ORDER of the returned pairs is load-bearing: spent tokens are appended to the bag
/// in exactly this sequence, and the bag's ORDER is part of the state (it decides what a
/// later replenish deals). Python builds `spend` by iterating the cost dict — verified to
/// be in ascending colour order for all 67 cards — then appends gold last.
pub fn calc_spend(
    card: usize,
    tokens: &[i32; N_TOKENS],
    bonuses: &[i32; N_COLORS],
) -> Vec<(usize, i32)> {
    let mut spend: Vec<(usize, i32)> = Vec::new();
    let mut gold = 0;
    for col in 0..=PEARL {
        let n = COST[card][col];
        if n == 0 {
            continue;
        }
        let need = if col < N_COLORS { (n - bonuses[col]).max(0) } else { n };
        if need <= 0 {
            continue; // `effective_cost` only keeps colours with a positive need
        }
        let have = tokens[col].min(need);
        if have > 0 {
            spend.push((col, have));
        }
        gold += need - have;
    }
    if gold > 0 {
        spend.push((GOLD, gold));
    }
    spend
}

impl State {
    // ─── Construction ────────────────────────────────────────────────────────
    /// Build from an explicit post-deal setup (the fixture's `setup`), i.e. everything
    /// `new_game` produces after the initial fill and the setup privilege grant.
    pub fn from_setup(
        board: [i8; N_CELLS],
        bag: Vec<u8>,
        decks: [Vec<usize>; 3],
        pyramid: [Vec<i32>; 3],
        privileges_board: i32,
        royals_available: Vec<usize>,
        privs: [i32; 2],
    ) -> State {
        let mut players: [Player; 2] = Default::default();
        players[0].privileges = privs[0];
        players[1].privileges = privs[1];
        State {
            phase: PLAYING,
            winner: -1,
            win_condition: WC_NONE,
            win_color: -1,
            turn: 0,
            turn_number: 1,
            replenished: false,
            again: false,
            board,
            bag,
            privileges_board,
            decks,
            pyramid,
            royals_available,
            players,
            pending_pid: -1,
            pending_kind: PK_NONE,
            pending: Pending::default(),
        }
    }

    pub fn is_over(&self) -> bool {
        self.phase == OVER
    }

    // ─── Privileges (closed loop of 3: board pool <-> players) ───────────────
    /// Scarcity rule: take from the board pool, else from the opponent, else no-op
    /// (`to_pid` already holds all 3). Returns whether one actually moved.
    fn grant_privilege(&mut self, to_pid: usize) -> bool {
        if self.privileges_board > 0 {
            self.privileges_board -= 1;
            self.players[to_pid].privileges += 1;
            return true;
        }
        let opp = opponent(to_pid);
        if self.players[opp].privileges > 0 {
            self.players[opp].privileges -= 1;
            self.players[to_pid].privileges += 1;
            return true;
        }
        false
    }

    // ─── Board ───────────────────────────────────────────────────────────────
    /// Shuffle the bag and fill empty cells in spiral order until the bag (or the
    /// empties) run out. The bag is popped from the END, matching Python's `.pop()`.
    fn fill_board<S: Shuffler>(&mut self, sh: &mut S) -> i32 {
        sh.shuffle(&mut self.bag);
        let mut placed = 0;
        for &idx in SPIRAL_ORDER.iter() {
            if self.bag.is_empty() {
                break;
            }
            if self.board[idx] == EMPTY {
                self.board[idx] = self.bag.pop().unwrap() as i8;
                placed += 1;
            }
        }
        placed
    }

    /// 1-3 distinct cells, all holding gems/pearls, forming a contiguous straight line in
    /// any of the 8 directions. Gaps and gold break a line by OCCUPANCY: a skipped cell
    /// makes the step vector longer than 1, which the `max(|dr|,|dc|) != 1` test rejects.
    fn valid_line(&self, cells: &[usize]) -> bool {
        if cells.is_empty() || cells.len() > 3 {
            return false;
        }
        for (i, &a) in cells.iter().enumerate() {
            if cells[..i].contains(&a) {
                return false; // distinct cells
            }
            if a >= N_CELLS || !is_gem_or_pearl(self.board[a]) {
                return false;
            }
        }
        if cells.len() == 1 {
            return true;
        }
        let mut pts: Vec<(i32, i32)> = cells.iter().map(|&i| ((i / 5) as i32, (i % 5) as i32)).collect();
        pts.sort();
        let d = (pts[1].0 - pts[0].0, pts[1].1 - pts[0].1);
        if d.0.abs().max(d.1.abs()) != 1 {
            return false;
        }
        if cells.len() == 3 {
            let d2 = (pts[2].0 - pts[1].0, pts[2].1 - pts[1].1);
            if d2 != d {
                return false;
            }
        }
        true
    }

    // ─── Pending machinery ───────────────────────────────────────────────────
    fn set_pending(&mut self, pid: usize, kind: u8, ctx: Pending) {
        self.pending_pid = pid as i32;
        self.pending_kind = kind;
        self.pending = ctx;
    }

    fn clear_pending(&mut self) {
        self.pending_pid = -1;
        self.pending_kind = PK_NONE;
        self.pending = Pending::default();
    }

    // ─── Ability resolution ──────────────────────────────────────────────────
    /// `color` = the card's EFFECTIVE bonus colour (for take_same), or -1 for a royal.
    /// May set a pending choice; the caller continues via `after_action`.
    fn resolve_ability(&mut self, pid: usize, ability: u8, color: i8, via: Via) {
        match ability {
            AB_NONE => {}
            AB_AGAIN => self.again = true,
            AB_PRIVILEGE => {
                self.grant_privilege(pid);
            }
            AB_TAKE_SAME => {
                // Royals never carry take_same, so `color` is always a real colour here.
                debug_assert!(color >= 0, "take_same with no colour");
                let cells: Vec<usize> =
                    (0..N_CELLS).filter(|&i| self.board[i] == color).collect();
                if cells.is_empty() {
                    return; // no matching token on the board: ignore
                }
                if cells.len() == 1 {
                    self.board[cells[0]] = EMPTY;
                    self.players[pid].tokens[color as usize] += 1;
                } else {
                    self.set_pending(
                        pid,
                        PK_TAKE_SAME,
                        Pending { color: color as i32, cells, via, ..Default::default() },
                    );
                }
            }
            AB_STEAL => {
                let opp = opponent(pid);
                let colors: Vec<usize> =
                    (0..N_TOKENS).filter(|&t| t != GOLD && self.players[opp].tokens[t] > 0).collect();
                if colors.is_empty() {
                    return; // opponent has no stealable token: ignore
                }
                if colors.len() == 1 {
                    let c = colors[0];
                    self.players[opp].tokens[c] -= 1;
                    self.players[pid].tokens[c] += 1;
                } else {
                    self.set_pending(pid, PK_STEAL, Pending { colors, via, ..Default::default() });
                }
            }
            _ => unreachable!("unknown ability {}", ability),
        }
    }

    // ─── Turn pipeline ───────────────────────────────────────────────────────
    /// Ability pendings -> royal choices -> discard-to-10 -> finish turn. Runs after the
    /// mandatory move and after every pending resolver.
    fn after_action(&mut self, pid: usize) {
        if self.pending_pid != -1 {
            return;
        }
        let p = &self.players[pid];
        if p.royals_claimed < royal_entitlement(p) && !self.royals_available.is_empty() {
            let royals = self.royals_available.clone();
            self.set_pending(pid, PK_CHOOSE_ROYAL, Pending { royals, ..Default::default() });
            return;
        }
        let total: i32 = p.tokens.iter().sum(); // gold counts toward the cap
        if total > MAX_TOKENS {
            self.set_pending(
                pid,
                PK_DISCARD,
                Pending { excess: total - MAX_TOKENS, ..Default::default() },
            );
            return;
        }
        self.finish_turn(pid);
    }

    fn check_victory(&mut self, pid: usize) -> bool {
        let p = &self.players[pid];
        if points_of(p) >= WIN_POINTS {
            self.win_condition = WC_POINTS;
        } else if crowns_of(p) >= WIN_CROWNS {
            self.win_condition = WC_CROWNS;
        } else {
            let cp = color_points_of(p);
            // Python's `max(cp, key=...)` returns the FIRST maximum in colour order, so a
            // tie resolves to the lowest colour index — `>` (not `>=`) preserves that.
            let mut best = 0usize;
            for c in 1..N_COLORS {
                if cp[c] > cp[best] {
                    best = c;
                }
            }
            if cp[best] >= WIN_COLOR_POINTS {
                self.win_condition = WC_COLOR;
                self.win_color = best as i32;
            } else {
                return false;
            }
        }
        self.phase = OVER;
        self.winner = pid as i32;
        self.again = false;
        true
    }

    fn finish_turn(&mut self, pid: usize) {
        if self.check_victory(pid) {
            return; // victory pre-empts AGAIN
        }
        self.replenished = false;
        self.turn_number += 1;
        if self.again {
            self.again = false; // an AGAIN turn is its own turn: the seat does not pass
        } else {
            self.turn = opponent(pid);
        }
    }

    // ─── Optional-action handlers (the turn continues afterwards) ────────────
    fn h_use_privilege(&mut self, pid: usize, cell: usize) -> Result<(), &'static str> {
        if self.players[pid].privileges < 1 {
            return Err("no privilege to use");
        }
        if self.replenished {
            return Err("privileges must be used before replenishing");
        }
        if cell >= N_CELLS || !is_gem_or_pearl(self.board[cell]) {
            return Err("pick a gem or pearl token on the board");
        }
        let color = self.board[cell] as usize;
        self.board[cell] = EMPTY;
        self.players[pid].tokens[color] += 1;
        self.players[pid].privileges -= 1;
        self.privileges_board += 1;
        Ok(())
    }

    fn h_replenish<S: Shuffler>(&mut self, pid: usize, sh: &mut S) -> Result<(), &'static str> {
        if self.bag.is_empty() {
            return Err("the bag is empty");
        }
        if self.board.iter().all(|&t| t != EMPTY) {
            return Err("the board is full");
        }
        if self.replenished {
            return Err("already replenished this turn");
        }
        self.fill_board(sh);
        self.replenished = true;
        self.grant_privilege(opponent(pid));
        Ok(())
    }

    // ─── Mandatory-action handlers (each ends by driving after_action) ───────
    fn h_take(&mut self, pid: usize, cells: &[usize]) -> Result<(), &'static str> {
        if !self.valid_line(cells) {
            return Err("tokens must form an unbroken straight line of 1-3 gems/pearls");
        }
        let mut taken: Vec<i8> = Vec::with_capacity(cells.len());
        for &i in cells {
            taken.push(self.board[i]);
            self.board[i] = EMPTY;
        }
        for &t in &taken {
            self.players[pid].tokens[t as usize] += 1;
        }
        // The two privilege triggers: 3 of one colour, or 2+ pearls.
        let three_same = taken.len() == 3 && taken.iter().all(|&t| t == taken[0]);
        let two_pearls = taken.iter().filter(|&&t| t == PEARL as i8).count() >= 2;
        if three_same || two_pearls {
            self.grant_privilege(opponent(pid));
        }
        self.after_action(pid);
        Ok(())
    }

    fn h_reserve(&mut self, pid: usize, gold_cell: usize, src: ReserveSrc) -> Result<(), &'static str> {
        if self.players[pid].reserved.len() >= MAX_RESERVED {
            return Err("you already have 3 reserved cards");
        }
        if gold_cell >= N_CELLS || self.board[gold_cell] != GOLD as i8 {
            return Err("pick a gold token on the board");
        }
        match src {
            ReserveSrc::Pyramid { level, slot } => {
                if level >= 3 {
                    return Err("bad reserve source");
                }
                if slot >= self.pyramid[level].len() || self.pyramid[level][slot] < 0 {
                    return Err("no card in that pyramid slot");
                }
                let cid = self.pyramid[level][slot] as usize;
                // Refill the vacated slot from the deck (empty deck leaves it exhausted).
                self.pyramid[level][slot] = match self.decks[level].pop() {
                    Some(c) => c as i32,
                    None => -1,
                };
                self.players[pid].reserved.push(cid);
            }
            ReserveSrc::Deck { level } => {
                if level >= 3 {
                    return Err("bad reserve source");
                }
                let cid = match self.decks[level].pop() {
                    Some(c) => c,
                    None => return Err("that deck is empty"),
                };
                self.players[pid].reserved.push(cid);
                self.players[pid].reserved_from_deck.push(cid);
            }
        }
        self.board[gold_cell] = EMPTY;
        self.players[pid].tokens[GOLD] += 1;
        self.after_action(pid);
        Ok(())
    }

    fn find_pyramid(&self, cid: usize) -> Option<(usize, usize)> {
        for lvl in 0..3 {
            for (slot, &c) in self.pyramid[lvl].iter().enumerate() {
                if c == cid as i32 {
                    return Some((lvl, slot));
                }
            }
        }
        None
    }

    fn h_buy(&mut self, pid: usize, cid: usize, from: BuySrc, as_color: i8) -> Result<(), &'static str> {
        if cid >= N_CARDS {
            return Err("unknown card");
        }
        let mut pyr: Option<(usize, usize)> = None;
        match from {
            BuySrc::Pyramid => {
                pyr = self.find_pyramid(cid);
                if pyr.is_none() {
                    return Err("that card is not in the pyramid");
                }
            }
            BuySrc::Reserve => {
                if !self.players[pid].reserved.contains(&cid) {
                    return Err("that card is not in your reserve");
                }
            }
        }
        let bonuses = bonuses_of(&self.players[pid]);
        if BONUS[cid] == BONUS_WILD {
            // A wild joins one of YOUR existing bonus groups — so it needs one to exist.
            if bonuses.iter().all(|&n| n == 0) {
                return Err("you need a bonus card to purchase a wild card");
            }
            if as_color < 0 || bonuses[as_color as usize] == 0 {
                return Err("pick one of your bonus colors for the wild card");
            }
        } else if as_color != -1 {
            return Err("as_color only applies to wild cards");
        }
        if !can_afford(cid, &self.players[pid].tokens, &bonuses) {
            return Err("you can't afford that card");
        }
        for (col, n) in calc_spend(cid, &self.players[pid].tokens, &bonuses) {
            self.players[pid].tokens[col] -= n;
            // Spent tokens return to the BAG (there is no bank) — a later replenish
            // reshuffles them straight back into play.
            for _ in 0..n {
                self.bag.push(col as u8);
            }
        }
        match from {
            BuySrc::Pyramid => {
                let (lvl, slot) = pyr.unwrap();
                self.pyramid[lvl][slot] = match self.decks[lvl].pop() {
                    Some(c) => c as i32,
                    None => -1,
                };
            }
            BuySrc::Reserve => {
                let p = &mut self.players[pid];
                let i = p.reserved.iter().position(|&c| c == cid).unwrap();
                p.reserved.remove(i);
                if let Some(j) = p.reserved_from_deck.iter().position(|&c| c == cid) {
                    p.reserved_from_deck.remove(j);
                }
            }
        }
        self.players[pid].purchased.push((cid, as_color));
        let eff_color = if BONUS[cid] == BONUS_WILD { as_color } else { BONUS[cid] };
        self.resolve_ability(pid, ABILITY[cid], eff_color, Via::Card(cid));
        self.after_action(pid);
        Ok(())
    }

    fn h_pass(&mut self, pid: usize) -> Result<(), &'static str> {
        // Defensive liveness fallback only — unreachable per the no-deadlock argument
        // (see legal_moves) — but the engine must never strand a player.
        if self.legal_moves(pid) != vec![Move::Pass] {
            return Err("you have a legal action");
        }
        self.after_action(pid);
        Ok(())
    }

    // ─── Pending resolvers ───────────────────────────────────────────────────
    fn r_take_same(&mut self, pid: usize, cell: usize) -> Result<(), &'static str> {
        let color = self.pending.color;
        if !self.pending.cells.contains(&cell) || self.board[cell] as i32 != color {
            return Err("pick one of the matching tokens");
        }
        self.board[cell] = EMPTY;
        self.players[pid].tokens[color as usize] += 1;
        self.clear_pending();
        self.after_action(pid);
        Ok(())
    }

    fn r_steal(&mut self, pid: usize, color: usize) -> Result<(), &'static str> {
        let opp = opponent(pid);
        if !self.pending.colors.contains(&color) || color == GOLD || self.players[opp].tokens[color] < 1 {
            return Err("pick a gem or pearl your opponent holds");
        }
        self.players[opp].tokens[color] -= 1;
        self.players[pid].tokens[color] += 1;
        self.clear_pending();
        self.after_action(pid);
        Ok(())
    }

    fn r_choose_royal(&mut self, pid: usize, rid: usize) -> Result<(), &'static str> {
        let i = match self.royals_available.iter().position(|&r| r == rid) {
            Some(i) => i,
            None => return Err("that royal card is not available"),
        };
        self.royals_available.remove(i);
        self.players[pid].royals.push(rid);
        self.players[pid].royals_claimed += 1;
        // Cleared BEFORE the ability resolves, so the royal's own ability is free to open
        // a NEW pending (steal/take_same) of its own.
        self.clear_pending();
        self.resolve_ability(pid, ROYAL_ABILITY[rid], -1, Via::Royal(rid));
        self.after_action(pid);
        Ok(())
    }

    fn r_discard(&mut self, pid: usize, color: usize) -> Result<(), &'static str> {
        if color >= N_TOKENS || self.players[pid].tokens[color] < 1 {
            return Err("pick a token you hold");
        }
        self.players[pid].tokens[color] -= 1;
        self.bag.push(color as u8);
        self.clear_pending();
        self.after_action(pid); // re-arms the discard pending while still over 10
        Ok(())
    }

    fn r_skip_pending(&mut self, pid: usize) -> Result<(), &'static str> {
        if self.pending_kind == PK_CHOOSE_ROYAL {
            // Forfeit: count the entitlement as consumed so the check can't loop.
            self.players[pid].royals_claimed += 1;
        }
        self.clear_pending();
        self.after_action(pid);
        Ok(())
    }

    // ─── Move enumeration ────────────────────────────────────────────────────
    fn pending_legal_moves(&self, pid: usize) -> Vec<Move> {
        let mut moves = Vec::new();
        match self.pending_kind {
            PK_TAKE_SAME => {
                for &i in &self.pending.cells {
                    if self.board[i] as i32 == self.pending.color {
                        moves.push(Move::TakeSame { cell: i });
                    }
                }
            }
            PK_STEAL => {
                let opp = &self.players[opponent(pid)];
                for &c in &self.pending.colors {
                    if opp.tokens[c] > 0 {
                        moves.push(Move::Steal { color: c });
                    }
                }
            }
            PK_CHOOSE_ROYAL => {
                for &rid in &self.royals_available {
                    moves.push(Move::ChooseRoyal { royal: rid });
                }
            }
            PK_DISCARD => {
                for t in 0..N_TOKENS {
                    if self.players[pid].tokens[t] > 0 {
                        moves.push(Move::Discard { color: t });
                    }
                }
                return moves; // no skip: discarding to 10 is mandatory
            }
            _ => {}
        }
        moves.push(Move::SkipPending);
        moves
    }

    /// Every straight line of 1-3 gems/pearls. Each line is emitted from its
    /// lowest-index cell scanning E/S/SE/SW, so no line is generated twice.
    ///
    /// `pub(crate)` for the rollout's lazy tier generator (`mcts::rollout_top_tier`),
    /// which rebuilds ONE tier of `mandatory_moves` and depends on getting it in exactly
    /// this order — see that function.
    pub(crate) fn line_moves(&self) -> Vec<Move> {
        let mut moves = Vec::new();
        for i in 0..N_CELLS {
            if !is_gem_or_pearl(self.board[i]) {
                continue;
            }
            moves.push(Move::Take { cells: vec![i] });
            let (r, c) = ((i / 5) as i32, (i % 5) as i32);
            for (dr, dc) in UNIT_DIRS {
                let (r2, c2) = (r + dr, c + dc);
                if !(0..5).contains(&r2) || !(0..5).contains(&c2) {
                    continue;
                }
                let j = (r2 * 5 + c2) as usize;
                if !is_gem_or_pearl(self.board[j]) {
                    continue;
                }
                moves.push(Move::Take { cells: vec![i, j] });
                let (r3, c3) = (r2 + dr, c2 + dc);
                if (0..5).contains(&r3) && (0..5).contains(&c3) {
                    let k = (r3 * 5 + c3) as usize;
                    if is_gem_or_pearl(self.board[k]) {
                        moves.push(Move::Take { cells: vec![i, j, k] });
                    }
                }
            }
        }
        moves
    }

    pub(crate) fn reserve_moves(&self, pid: usize) -> Vec<Move> {
        let mut moves = Vec::new();
        if self.players[pid].reserved.len() < MAX_RESERVED {
            let gold_cells: Vec<usize> =
                (0..N_CELLS).filter(|&i| self.board[i] == GOLD as i8).collect();
            for g in gold_cells {
                for lvl in 0..3 {
                    for slot in 0..self.pyramid[lvl].len() {
                        if self.pyramid[lvl][slot] >= 0 {
                            moves.push(Move::Reserve {
                                gold_cell: g,
                                src: ReserveSrc::Pyramid { level: lvl, slot },
                            });
                        }
                    }
                    if !self.decks[lvl].is_empty() {
                        moves.push(Move::Reserve {
                            gold_cell: g,
                            src: ReserveSrc::Deck { level: lvl },
                        });
                    }
                }
            }
        }
        moves
    }

    pub(crate) fn buy_moves(&self, pid: usize) -> Vec<Move> {
        let p = &self.players[pid];
        let bonuses = bonuses_of(p);
        let eligible_wild: Vec<i8> =
            (0..N_COLORS).filter(|&c| bonuses[c] > 0).map(|c| c as i8).collect();
        let mut sources: Vec<(BuySrc, usize)> = Vec::new();
        for lvl in 0..3 {
            for &c in &self.pyramid[lvl] {
                if c >= 0 {
                    sources.push((BuySrc::Pyramid, c as usize));
                }
            }
        }
        for &cid in &p.reserved {
            sources.push((BuySrc::Reserve, cid));
        }
        let mut moves = Vec::new();
        for (frm, cid) in sources {
            if !can_afford(cid, &p.tokens, &bonuses) {
                continue;
            }
            if BONUS[cid] == BONUS_WILD {
                for &col in &eligible_wild {
                    moves.push(Move::Buy { card: cid, from: frm, as_color: col });
                }
            } else {
                moves.push(Move::Buy { card: cid, from: frm, as_color: -1 });
            }
        }
        moves
    }

    /// Takes, then reserves, then buys — the ORDER is load-bearing (the Python rollout
    /// reproduces one tier of this list and relies on the concatenation order).
    fn mandatory_moves(&self, pid: usize) -> Vec<Move> {
        let mut m = self.line_moves();
        m.extend(self.reserve_moves(pid));
        m.extend(self.buy_moves(pid));
        m
    }

    pub fn legal_moves(&self, pid: usize) -> Vec<Move> {
        if self.is_over() {
            return Vec::new();
        }
        if self.pending_pid != -1 {
            if pid as i32 != self.pending_pid {
                return Vec::new();
            }
            return self.pending_legal_moves(pid);
        }
        if pid != self.turn {
            return Vec::new();
        }
        let mut moves: Vec<Move> = Vec::new();
        // Optional actions come first, in strict rulebook order: privileges, then
        // replenish (which locks both out for the rest of the turn).
        if self.players[pid].privileges > 0 && !self.replenished {
            for i in 0..N_CELLS {
                if is_gem_or_pearl(self.board[i]) {
                    moves.push(Move::UsePrivilege { cell: i });
                }
            }
        }
        if !self.bag.is_empty() && !self.replenished && self.board.iter().any(|&t| t == EMPTY) {
            moves.push(Move::Replenish);
        }
        moves.extend(self.mandatory_moves(pid));
        if moves.is_empty() {
            // Unreachable per the no-deadlock argument (<=20 tokens held, <=3 gold of 25
            // => an empty bag implies a takeable gem/pearl) — defensive only.
            return vec![Move::Pass];
        }
        moves
    }

    // ─── Public API ──────────────────────────────────────────────────────────
    pub fn apply_move<S: Shuffler>(
        &mut self,
        pid: usize,
        mv: &Move,
        sh: &mut S,
    ) -> Result<(), &'static str> {
        if self.is_over() {
            return Err("game is over");
        }
        if self.pending_pid != -1 {
            if pid as i32 != self.pending_pid {
                return Err("not your decision");
            }
            // A resolver move must match the pending kind; discard has no skip because it
            // strictly reduces the hand, so it always terminates.
            let allowed = match (self.pending_kind, mv) {
                (PK_TAKE_SAME, Move::TakeSame { .. }) => true,
                (PK_STEAL, Move::Steal { .. }) => true,
                (PK_CHOOSE_ROYAL, Move::ChooseRoyal { .. }) => true,
                (PK_DISCARD, Move::Discard { .. }) => true,
                (PK_TAKE_SAME | PK_STEAL | PK_CHOOSE_ROYAL, Move::SkipPending) => true,
                _ => false,
            };
            if !allowed {
                return Err("must resolve the pending decision first");
            }
            return match *mv {
                Move::TakeSame { cell } => self.r_take_same(pid, cell),
                Move::Steal { color } => self.r_steal(pid, color),
                Move::ChooseRoyal { royal } => self.r_choose_royal(pid, royal),
                Move::Discard { color } => self.r_discard(pid, color),
                Move::SkipPending => self.r_skip_pending(pid),
                _ => unreachable!(),
            };
        }
        if pid != self.turn {
            return Err("not your turn");
        }
        match mv {
            Move::UsePrivilege { cell } => self.h_use_privilege(pid, *cell),
            Move::Replenish => self.h_replenish(pid, sh),
            Move::Take { cells } => self.h_take(pid, cells),
            Move::Reserve { gold_cell, src } => self.h_reserve(pid, *gold_cell, *src),
            Move::Buy { card, from, as_color } => self.h_buy(pid, *card, *from, *as_color),
            Move::Pass => self.h_pass(pid),
            // Resolver types are only legal against a matching pending.
            _ => Err("unknown move"),
        }
    }

    // ─── Projection (the parity contract) ────────────────────────────────────
    /// Canonical TOTAL projection — must be byte-identical to `gen_engine_fixtures.proj`.
    /// Includes the hidden piles (bag/deck order) on purpose: a port that gets the
    /// visible board right while drifting on deck order is still wrong, just later.
    pub fn proj(&self) -> String {
        fn join<T: std::fmt::Display>(xs: impl Iterator<Item = T>) -> String {
            xs.map(|x| x.to_string()).collect::<Vec<_>>().join(",")
        }
        let mut parts: Vec<String> = Vec::new();
        parts.push(format!("ph={}", if self.phase == PLAYING { 0 } else { 1 }));
        parts.push(format!("wn={}", self.winner));
        parts.push(format!(
            "wc={}",
            match self.win_condition {
                WC_POINTS => "points",
                WC_CROWNS => "crowns",
                WC_COLOR => "color",
                _ => "-",
            }
        ));
        parts.push(format!("wcol={}", self.win_color));
        parts.push(format!("turn={}", self.turn));
        parts.push(format!("tn={}", self.turn_number));
        parts.push(format!("rep={}", self.replenished as i32));
        parts.push(format!("agn={}", self.again as i32));
        parts.push(format!("pb={}", self.privileges_board));
        parts.push(format!("board={}", join(self.board.iter())));
        parts.push(format!("bag={}", join(self.bag.iter())));
        parts.push(format!("roy={}", join(self.royals_available.iter())));
        for lvl in 0..3 {
            parts.push(format!("d{}={}", lvl + 1, join(self.decks[lvl].iter())));
            parts.push(format!("p{}={}", lvl + 1, join(self.pyramid[lvl].iter())));
        }
        for seat in 0..2 {
            let p = &self.players[seat];
            parts.push(format!("t{}={}", seat, join(p.tokens.iter())));
            parts.push(format!("v{}={}", seat, p.privileges));
            parts.push(format!("r{}={}", seat, join(p.reserved.iter())));
            parts.push(format!("rd{}={}", seat, join(p.reserved_from_deck.iter())));
            parts.push(format!(
                "b{}={}",
                seat,
                p.purchased
                    .iter()
                    .map(|&(c, a)| format!("{}:{}", c, a))
                    .collect::<Vec<_>>()
                    .join(",")
            ));
            parts.push(format!("y{}={}", seat, join(p.royals.iter())));
            parts.push(format!("yc{}={}", seat, p.royals_claimed));
        }
        parts.push(format!("pp={}", self.pending_pid));
        parts.push(format!("pk={}", self.pending_kind));
        let has_ctx = self.pending_pid != -1;
        parts.push(format!(
            "pcol={}",
            if has_ctx { join(self.pending.colors.iter()) } else { String::new() }
        ));
        parts.push(format!(
            "proy={}",
            if has_ctx { join(self.pending.royals.iter()) } else { String::new() }
        ));
        // The Python's ctx never carries a `bonus` key, so this field is always -1. Kept
        // because the projection string must match byte-for-byte.
        parts.push("pbon=-1".to_string());
        parts.push(format!(
            "pvia={}",
            match self.pending.via {
                Via::Card(c) if has_ctx => card_id_str(c),
                Via::Royal(r) if has_ctx => royal_id_str(r),
                _ => "-".to_string(),
            }
        ));
        parts.join("|")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A bare state whose board is all gems (colour = index % 5), for geometry tests.
    fn gem_board_state() -> State {
        let mut board = [EMPTY; N_CELLS];
        for i in 0..N_CELLS {
            board[i] = (i % 5) as i8;
        }
        State::from_setup(
            board,
            Vec::new(),
            [Vec::new(), Vec::new(), Vec::new()],
            [vec![-1; 5], vec![-1; 4], vec![-1; 3]],
            0,
            vec![],
            [0, 0],
        )
    }

    /// `valid_line`'s REJECT branches are invisible to the parity corpus (which only ever
    /// replays moves Python already ruled legal) — but the server hands `apply_move`
    /// untrusted client moves, so they are the real validation boundary.
    #[test]
    fn valid_line_accepts_every_direction_and_length() {
        let s = gem_board_state();
        assert!(s.valid_line(&[0]));
        assert!(s.valid_line(&[0, 1]), "E pair");
        assert!(s.valid_line(&[0, 1, 2]), "E triple");
        assert!(s.valid_line(&[0, 5, 10]), "S triple");
        assert!(s.valid_line(&[0, 6, 12]), "SE triple");
        assert!(s.valid_line(&[2, 6, 10]), "SW triple");
        assert!(s.valid_line(&[2, 1, 0]), "order of the cells must not matter");
    }

    #[test]
    fn valid_line_rejects_non_lines() {
        let s = gem_board_state();
        assert!(!s.valid_line(&[]), "empty");
        assert!(!s.valid_line(&[0, 1, 2, 3]), "too long");
        assert!(!s.valid_line(&[0, 0]), "duplicate cells");
        assert!(!s.valid_line(&[25]), "out of range");
        assert!(!s.valid_line(&[0, 2]), "gap: a skipped cell makes the step vector 2");
        assert!(!s.valid_line(&[0, 1, 3]), "3rd cell breaks contiguity");
        assert!(!s.valid_line(&[0, 7]), "knight-ish jump");
        // Row wrap is NOT adjacency: cell 4 is (0,4) and cell 5 is (1,0).
        assert!(!s.valid_line(&[4, 5]), "row wrap must not count as a line");
    }

    #[test]
    fn valid_line_rejects_gold_and_empty_cells() {
        let mut s = gem_board_state();
        s.board[1] = GOLD as i8;
        s.board[2] = EMPTY;
        assert!(!s.valid_line(&[1]), "gold is not takeable by a line");
        assert!(!s.valid_line(&[0, 1]), "gold breaks the line by occupancy");
        assert!(!s.valid_line(&[2]), "empty cell");
    }

    /// The colour win must fire below the 20-point threshold — otherwise the points
    /// check (which runs first) would mask it and the branch would be dead.
    /// d3_00 + d3_01 + d2_00 + d1_04 = 10 white points, 10 total, 3 crowns.
    #[test]
    fn color_victory_fires_below_the_points_threshold() {
        let mut s = gem_board_state();
        s.players[0].purchased = vec![(54, -1), (55, -1), (30, -1), (4, -1)];
        assert!(points_of(&s.players[0]) < WIN_POINTS, "must not win on points");
        assert!(crowns_of(&s.players[0]) < WIN_CROWNS, "must not win on crowns");
        assert!(s.check_victory(0));
        assert_eq!(s.win_condition, WC_COLOR);
        assert_eq!(s.win_color, 0, "white");
        assert_eq!(s.winner, 0);
        assert!(s.is_over());
    }

    /// A wild counts in the group it was attached to — for BOTH the bonus and the
    /// colour-points victory group — while a bonus-less card counts in neither.
    #[test]
    fn wild_counts_in_its_attached_group() {
        let mut s = gem_board_state();
        s.players[0].purchased = vec![(25, 1), (29, -1)]; // d1_25 wild(1pt), d1_29 bonus-less(3pt)
        assert_eq!(bonuses_of(&s.players[0])[1], 1, "wild joins blue");
        assert_eq!(color_points_of(&s.players[0])[1], 1, "wild's point lands in blue");
        assert_eq!(color_points_of(&s.players[0]).iter().sum::<i32>(), 1, "bonus-less card joins no group");
        assert_eq!(points_of(&s.players[0]), 4, "but it still scores");
    }
}
