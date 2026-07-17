//! Determinized MCTS — a port of the search half of `games/spender_duel/ai.py`.
//!
//! The Python is AUTHORITATIVE: where the two disagree, this file is wrong. What "agree"
//! means here is narrower than for the engine, and deliberately so (see
//! `tools/gen_ai_fixtures.py`): the two searches draw from different RNGs, so their
//! simulations diverge by construction. Three things are therefore pinned exactly, and
//! they are the three that decide what bot this is:
//!
//!   * the LEAF (`value`) — what the search is optimising. Gated to 1e-12.
//!   * the BRANCHES (`legal`, `rollout_top_tier`) — which moves exist, and in what ORDER
//!     (the rollout samples by INDEX, so order is play-affecting, not cosmetic).
//!   * the RULES (`engine`) — already state-exact over 520 games / 54,271 moves.
//!
//! DELIBERATE DIVERGENCES FROM THE PYTHON (both unobservable through the gate, both here
//! because the alternative would be to fake a Mersenne Twister for no gain):
//!
//!   1. ONE rng stream, not two. Python's `_determinize` serialises its rng state into the
//!      sim (`_save_rng`), so a `replenish` inside a rollout draws from a FORK of the
//!      search's stream while `rng.choice` keeps drawing from the original. That fork is
//!      incidental — a side effect of the engine persisting `rng_state` for save/reload —
//!      not a design choice, so this passes one rng to both via `RngShuffler`.
//!   2. The canonicalising sort in `determinize` orders the bag by TOKEN CODE where Python
//!      sorts token NAME strings (alphabetical: black, blue, gold, ...). The sort exists to
//!      kill the true hidden order — any total order does that, and a shuffle immediately
//!      follows either way. Card pools DO sort identically (`d{lvl}_{idx:02}` is
//!      zero-padded, so within a level string order == index order).

use crate::cards::{LEVEL_OF, PEARL};
use crate::clock::{Clock, Deadline};
use crate::engine::{is_gem_or_pearl, opponent, Move, ReserveSrc, Shuffler, State, EMPTY, N_CELLS};
use crate::rng::Rng;
use crate::value::value;
use crate::valuenet::{QuantValueNet, ValueNet};

pub const C_PUCT: f64 = 1.5;
pub const MAX_TREE_DEPTH: usize = 14; // in-tree plies before truncating to a rollout
pub const ROLLOUT_STEPS: usize = 12; // engine moves played out before the heuristic leaf

/// Search budgets. "hard" = big budget, greedy. "normal" = small budget + TEMPERATURE
/// sampling, so it makes human-scale blunders.
///
/// `turn_budget` caps the WHOLE turn, `time_limit` any ONE decision. Both matter: a turn
/// can be several decisions (optional privilege -> mandatory -> ability pendings), so a
/// per-decision cap alone would let one turn think 3x its budget.
///
/// The Python's budgets are sized for a Render free tier that gets ~5 sims per root move;
/// this port exists precisely so those numbers buy ~1000x more. They are reproduced
/// unchanged because the tiers must stay comparable — retune them from measurements, not
/// from the port.
#[derive(Clone, Copy, Debug)]
pub struct Difficulty {
    pub turn_budget: f64,
    pub time_limit: f64,
    pub max_iters: u64,
    pub temperature: f64,
    pub rollout_steps: usize,
}

pub const NORMAL: Difficulty = Difficulty {
    turn_budget: 1.6,
    time_limit: 0.8,
    max_iters: 1200,
    temperature: 0.08,
    rollout_steps: 12,
};
pub const HARD: Difficulty = Difficulty {
    turn_budget: 5.0,
    time_limit: 2.5,
    max_iters: 5000,
    temperature: 0.0,
    rollout_steps: 12,
};
pub const DEFAULT_DIFFICULTY: &str = "hard";

/// Unknown names fall back to `hard`, mirroring `DIFFICULTY.get(d, DIFFICULTY[DEFAULT])`.
pub fn difficulty(name: &str) -> Difficulty {
    match name {
        "normal" => NORMAL,
        _ => HARD,
    }
}

/// Per-decision overrides. Python sets these as keyword args (and `take_dominance` via a
/// module global) so an arena can vary ONE side; here they are plain parameters, which
/// gets the same isolation without the global.
#[derive(Clone, Copy, Debug, Default)]
pub struct Opts {
    pub time_limit: Option<f64>,
    pub max_iters: Option<u64>,
    pub temperature: Option<f64>,
    pub rollout_steps: Option<usize>,
    pub take_dominance: Option<bool>,
}

/// Which evaluator the search truncates to at a leaf.
///
/// `Heuristic` is the deployed bot: a short rollout then `value::value` (the existing
/// behaviour — do NOT change it, the parity gates depend on it). `Net` is Phase 2: a DIRECT
/// 0-step learned value at the leaf (no rollout), which is how an outcome-trained net is
/// meant to be used. Copy so `leaf_eval` can read it out without fighting the `&mut self`
/// the rollout needs. The two are threaded via the `*_with_leaf` entry points below; the
/// plain `choose_move`/`root_search` keep their signatures and default to `Heuristic`, so
/// every existing caller (move server, harvest, wasm, play_turn_plan) is untouched.
#[derive(Clone, Copy)]
pub enum Leaf<'a> {
    Heuristic,
    Net(&'a ValueNet),
    // The int8-trunk net (opt-in `:net8` arm). Same leaf semantics as `Net`; only the forward
    // arithmetic differs (quantized), gated by the strength A/B vs `Net`, not float parity.
    Net8(&'a QuantValueNet),
}

/// Feeds the engine's bag shuffle from the search's rng (Python does this by persisting
/// `rng_state` into the sim; see the divergence note at the top of this file).
pub struct RngShuffler<'a> {
    pub rng: &'a mut Rng,
}

impl Shuffler for RngShuffler<'_> {
    fn shuffle(&mut self, bag: &mut Vec<u8>) {
        self.rng.shuffle(bag);
    }
}

// ── Search-legality pruning ──────────────────────────────────────────────────
/// Does this take hand the OPPONENT a Privilege? (3 of a colour, or 2+ pearls)
///
/// Fast-pathed and called per-take inside `legal`, which runs at every node: a 1-cell take
/// can be neither, and that's most of the enumeration.
fn take_gifts_privilege(board: &[i8; N_CELLS], cells: &[usize]) -> bool {
    if cells.len() < 2 {
        return false;
    }
    if cells.len() == 3 && board[cells[0]] == board[cells[1]] && board[cells[1]] == board[cells[2]] {
        return true;
    }
    cells.iter().filter(|&&i| board[i] == PEARL as i8).count() >= 2
}

#[inline]
fn pair(a: usize, b: usize) -> (usize, usize) {
    if a < b {
        (a, b)
    } else {
        (b, a)
    }
}

/// Lookup sets for the dominated-take prune (see `legal`). Shared by `legal` and the
/// rollout's lazy tier generator so the two can never disagree on what's pruned.
///
/// Cells are 0..24, so Python's sets of cells / sorted pairs are bitmasks here: `covered`
/// is one 25-bit mask and each pair table is a mask per row. Same membership semantics,
/// no allocation and no hashing — this runs at every node AND every rollout step.
#[derive(Default)]
struct DomSets {
    covered: u32,
    dom_pairs: [u32; N_CELLS],
    dom_pairs_gift: [u32; N_CELLS],
}

fn take_dominance_sets(board: &[i8; N_CELLS], moves: &[Move]) -> DomSets {
    let mut d = DomSets::default();
    for m in moves {
        let cells = match m {
            Move::Take { cells } => cells,
            _ => continue,
        };
        if cells.len() == 1 {
            continue; // a 1-take can neither gift nor dominate
        }
        let gift = take_gifts_privilege(board, cells);
        if !gift {
            for &c in cells {
                d.covered |= 1 << c;
            }
        }
        if cells.len() == 3 {
            let (a, b, c) = (cells[0], cells[1], cells[2]);
            let tgt = if gift { &mut d.dom_pairs_gift } else { &mut d.dom_pairs };
            for (x, y) in [pair(a, b), pair(b, c), pair(a, c)] {
                tgt[x] |= 1 << y;
            }
        }
    }
    d
}

fn keep_take(board: &[i8; N_CELLS], cells: &[usize], d: &DomSets) -> bool {
    if cells.len() == 1 {
        return d.covered & (1 << cells[0]) == 0;
    }
    if cells.len() == 2 {
        let (a, b) = pair(cells[0], cells[1]);
        if d.dom_pairs[a] & (1 << b) != 0 {
            return false;
        }
        if d.dom_pairs_gift[a] & (1 << b) != 0 && take_gifts_privilege(board, cells) {
            return false;
        }
    }
    true
}

/// `legal_moves` minus redundant/dominated branches, to spend sims where they matter.
/// Never returns empty when `legal_moves` is non-empty (the CoC lesson: a prune that can
/// strand the search makes it play worse, not better).
///
/// Three prunes:
///   * `skip_pending` — skipping an ability is never better than using it (take_same/steal
///     are free gains; a royal is free points). Discard has no skip.
///   * duplicate reserve `gold_cell`s — WHICH gold you take is very nearly irrelevant:
///     gold tokens are fungible, and vacating a cell can never open a line (the empty cell
///     still breaks contiguity exactly as the gold did). So 3 gold cells x 15 sources = 45
///     branches collapse to 15. The one residual effect is spiral REFILL order on a later
///     replenish — a deliberate, tiny approximation.
///   * takes that are a strict SUBSET of another legal take — taking {white} when
///     {white, pearl} is on offer is free value left on the board. A real BLUNDER FIX, not
///     just a speed prune: one extra token is worth ~0.018 to `value`, at or below rollout
///     noise, so the search genuinely could not tell the two apart and left the free token
///     behind in 32/60 positions. With the prune: 0/60. Dominance is EXACT, not heuristic —
///     a superset take grants strictly more tokens at no per-token cost, and the 10-cap
///     can't punish it (discard the extra straight back). The one real cost is handing the
///     opponent a Privilege (3-of-a-colour or 2+ pearls), so a superset that NEWLY triggers
///     that does not dominate — which is why "just always take the most" would be a rules
///     bug.
pub fn legal(st: &State, pid: usize, take_dominance: bool) -> Vec<Move> {
    let moves = st.legal_moves(pid);
    if moves.len() <= 1 {
        return moves;
    }
    let board = &st.board;

    // Takes are only ever 1-3 cells, so dominance resolves with two lookup tables instead
    // of an O(takes^2) subset scan:
    //   * a 1-take never gifts, so it is dominated iff its cell sits in ANY non-gifting
    //     take of size >= 2  -> `covered`.
    //   * a 2-take is dominated iff some 3-take contains it that doesn't newly gift.
    //   * a 3-take is maximal: nothing can dominate it.
    let d = if take_dominance { take_dominance_sets(board, &moves) } else { DomSets::default() };

    let mut pruned: Vec<Move> = Vec::with_capacity(moves.len());
    // <= 15 distinct reserve sources (3 levels x (12 slots + 3 decks)), so a linear scan
    // beats hashing.
    let mut seen_reserve: Vec<(u8, usize, i32)> = Vec::new();
    for m in &moves {
        match m {
            Move::SkipPending => continue,
            Move::Reserve { src, .. } => {
                let key = match *src {
                    ReserveSrc::Pyramid { level, slot } => (0u8, level, slot as i32),
                    ReserveSrc::Deck { level } => (1u8, level, -1),
                };
                if seen_reserve.contains(&key) {
                    continue;
                }
                seen_reserve.push(key);
            }
            Move::Take { cells } => {
                if !keep_take(board, cells, &d) {
                    continue;
                }
            }
            _ => {}
        }
        pruned.push(m.clone());
    }
    if pruned.is_empty() {
        moves
    } else {
        pruned
    }
}

// ── Rollout ──────────────────────────────────────────────────────────────────
// Priority: buy 0 > take 1 > reserve 2 > replenish 3 > use_privilege 4. Encoded as the
// tier ORDER of `rollout_top_tier` rather than a lookup, exactly as the Python does.

/// The rollout's chosen tier, built WITHOUT enumerating the tiers it will discard.
///
/// The policy only ever plays the best-priority tier, so `legal()` -> min tier -> filter
/// was ~61% wasted work — and it runs 12x per sim, the single hottest path in the search.
///
/// BYTE-IDENTICAL to that code, and the reason is delicate enough to spell out:
/// `rollout_move` picks with `rng.below(len(top))`, indexing by POSITION, so the same move
/// comes back iff this rebuilds each tier in exactly `legal_moves`' order. Hence the
/// engine's `mandatory_moves` is split into per-tier helpers (takes -> reserves -> buys)
/// and the tiers below are tried in priority order, each applying the same prunes `legal`
/// would have. Changing either order silently changes play.
pub fn rollout_top_tier(st: &State, pid: usize, take_dominance: bool) -> Vec<Move> {
    let p = &st.players[pid];

    let buys = st.buy_moves(pid); // tier 0
    if !buys.is_empty() {
        return buys;
    }

    let takes = st.line_moves(); // tier 1
    if !takes.is_empty() {
        if take_dominance {
            let d = take_dominance_sets(&st.board, &takes);
            let kept: Vec<Move> = takes
                .iter()
                .filter(|m| match m {
                    Move::Take { cells } => keep_take(&st.board, cells, &d),
                    _ => true,
                })
                .cloned()
                .collect();
            if !kept.is_empty() {
                return kept;
            }
        }
        return takes;
    }

    let mut reserves: Vec<Move> = Vec::new(); // tier 2
    let mut seen: Vec<(u8, usize, i32)> = Vec::new();
    for m in st.reserve_moves(pid) {
        let key = match m {
            Move::Reserve { src: ReserveSrc::Pyramid { level, slot }, .. } => (0u8, level, slot as i32),
            Move::Reserve { src: ReserveSrc::Deck { level }, .. } => (1u8, level, -1),
            _ => unreachable!("reserve_moves emits only reserves"),
        };
        if !seen.contains(&key) {
            seen.push(key);
            reserves.push(m);
        }
    }
    if !reserves.is_empty() {
        return reserves;
    }

    // tier 3
    if !st.bag.is_empty() && !st.replenished && st.board.iter().any(|&t| t == EMPTY) {
        return vec![Move::Replenish];
    }

    // tier 4
    if p.privileges > 0 && !st.replenished {
        let privs: Vec<Move> = (0..N_CELLS)
            .filter(|&i| is_gem_or_pearl(st.board[i]))
            .map(|i| Move::UsePrivilege { cell: i })
            .collect();
        if !privs.is_empty() {
            return privs;
        }
    }

    vec![Move::Pass] // legal_moves' defensive fallback (unreachable)
}

// ── MCTS ─────────────────────────────────────────────────────────────────────
pub struct Node {
    pub actor: usize,
    pub moves: Vec<Move>,
    pub children: Vec<Option<Box<Node>>>,
    pub n: Vec<i32>,
    pub w: Vec<f64>,
}

impl Node {
    pub fn new(actor: usize, moves: Vec<Move>) -> Node {
        let k = moves.len();
        Node { actor, moves, children: (0..k).map(|_| None).collect(), n: vec![0; k], w: vec![0.0; k] }
    }
}

/// UCT selection: `U = C_PUCT*sqrt(N)/(1+n)`, with NO 1/branches prior scaling.
///
/// The missing prior looks like a bug. It isn't, and the reason is MEASURED, not argued
/// (CRN-paired, equal sims, mirror verified at exactly 0.5000):
///
///     prior@c100    vs no-prior@c1.5  ->  0.5000   (100/76 ~= 1.3 ~= 1.5: identical)
///     no-prior@c0.4 vs no-prior@c1.5  ->  0.5000   (broad plateau)
///     prior@c1.5    vs no-prior@c1.5  ->  0.2500   (effective c ~= 0.02: far too low)
///
/// So a FLAT prior is mathematically just a constant rescale of C_PUCT — it carries no
/// information. What matters is the exploration LEVEL, and there is a wide plateau
/// (~0.4-1.5) with a cliff below it: at c~=0.02 the search commits to whatever the first
/// couple of rollouts liked, and this leaf is NOISY (rollout ~+-0.3), so it commits to
/// noise. Broad sampling + picking the best MEAN (the value tie-break in `choose_move`) is
/// the better estimator here.
///
/// Selection and the final pick are a PAIR: near-uniform visits are only sound because the
/// pick breaks visit ties by value. Don't change one without re-measuring the other. A
/// LEARNED prior would be different — it carries real information — so revisit this if a
/// policy net ever lands.
fn select(node: &Node, total: i32) -> usize {
    let mut best = -1e18f64;
    let mut best_i = 0usize;
    let sqrt_t = (total.max(1) as f64).sqrt();
    for i in 0..node.moves.len() {
        let n = node.n[i];
        let q = if n != 0 { node.w[i] / n as f64 } else { 0.0 }; // FPU: unvisited looks neutral
        let u = C_PUCT * sqrt_t / (1 + n) as f64;
        let s = q + u;
        if s > best {
            best = s;
            best_i = i;
        }
    }
    best_i
}

/// Resample everything `pid` cannot legitimately see, drawing from `rng`.
///
/// Hidden: the bag's CONTENTS (its count is public), each deck's ORDER, and the opponent's
/// BLIND reserved cards. We pool the decks with the opponent's blind reserves, canonicalize
/// (sort) the pool, shuffle it, then re-deal — so two positions differing only in hidden
/// order give the SAME search distribution. Public and therefore untouched: the board,
/// pyramid, privileges, tokens, purchased cards, royals, and face-up (pyramid-sourced)
/// reserves.
///
/// `pub(crate)` so `endgame` can determinize ONCE and then run an exact minimax over the
/// resulting FIXED world (with an identity shuffler); the MCTS reaches it via
/// `Search::determinize`. Extracted verbatim from that method — behaviour is unchanged, so
/// the parity gates are unaffected.
pub(crate) fn determinize_state(st: &State, pid: usize, rng: &mut Rng) -> State {
    let mut g = st.clone();
    let opp = opponent(pid);
    let blind: Vec<usize> = g.players[opp].reserved_from_deck.clone();

    // Resample PER LEVEL: a blind reserve's level is PUBLIC (the opponent saw which deck it
    // came off), so only its identity within that level is unknown. Pool each level's unseen
    // cards = that deck + the opponent's blind reserves of that level.
    let mut unseen: [Vec<usize>; 3] = [Vec::new(), Vec::new(), Vec::new()];
    for lvl in 0..3 {
        unseen[lvl].extend_from_slice(&g.decks[lvl]);
    }
    for &cid in &blind {
        unseen[LEVEL_OF[cid] as usize - 1].push(cid);
    }
    for pool in unseen.iter_mut() {
        pool.sort_unstable(); // canonicalize: kill the true order
        rng.shuffle(pool);
    }

    // Re-deal the opponent's blind reserves (same level, new identity), keeping their
    // face-up reserves — those are public — then refill each deck from the remainder.
    if !blind.is_empty() {
        let redealt: Vec<usize> = blind
            .iter()
            .map(|&cid| {
                unseen[LEVEL_OF[cid] as usize - 1]
                    .pop()
                    .expect("a blind reserve is always in its own level's pool")
            })
            .collect();
        let op = &mut g.players[opp];
        let mut kept: Vec<usize> =
            op.reserved.iter().copied().filter(|c| !blind.contains(c)).collect();
        kept.extend_from_slice(&redealt);
        op.reserved = kept;
        op.reserved_from_deck = redealt;
    }
    for lvl in 0..3 {
        let n = g.decks[lvl].len(); // sizes are public
        g.decks[lvl] = unseen[lvl][..n].to_vec();
    }

    g.bag.sort_unstable(); // canonicalize; fill_board shuffles
    rng.shuffle(&mut g.bag);
    g
}

struct Search<'r, 'n> {
    rng: &'r mut Rng,
    take_dominance: bool,
    steps: usize,
    leaf: Leaf<'n>,
}

impl Search<'_, '_> {
    /// The leaf truncation value from ROOT_PID's perspective. `Heuristic` runs the rollout
    /// (byte-identical to the deployed bot); `Net` returns a 0-step learned value — except at
    /// a terminal, which is a FACT, not a prediction, so it is scored ±1 exactly (the net's
    /// features assume a live position and must never be handed a finished game).
    fn leaf_eval(&mut self, st: &mut State, root_pid: usize) -> f64 {
        match self.leaf {
            Leaf::Heuristic => self.rollout(st, root_pid),
            Leaf::Net(net) => {
                if st.is_over() {
                    return if st.winner == root_pid as i32 { 1.0 } else { -1.0 };
                }
                net.eval(st, root_pid)
            }
            Leaf::Net8(net) => {
                // Terminal is a FACT, not a prediction — score ±1 exactly (the net's features
                // assume a live position), identical to the `Net` arm above.
                if st.is_over() {
                    return if st.winner == root_pid as i32 { 1.0 } else { -1.0 };
                }
                net.eval(st, root_pid)
            }
        }
    }

    /// Resample everything `pid` cannot legitimately see. Thin delegate to the free
    /// `determinize_state` (the endgame minimax reuses the SAME logic — one source of truth,
    /// so the two searches can never drift on what "hidden" means).
    fn determinize(&mut self, st: &State, pid: usize) -> State {
        determinize_state(st, pid, self.rng)
    }

    fn rollout_move(&mut self, st: &State, pid: usize) -> Option<Move> {
        if st.is_over() {
            return None;
        }
        if st.pending_pid != -1 {
            // Pendings are already tiny (<=7 resolvers) and are chosen uniformly, not by
            // tier — enumerate them normally.
            if st.pending_pid != pid as i32 {
                return None;
            }
            let moves = legal(st, pid, self.take_dominance);
            if moves.is_empty() {
                return None;
            }
            let i = self.rng.below(moves.len());
            return Some(moves[i].clone());
        }
        if pid != st.turn {
            return None;
        }
        let top = rollout_top_tier(st, pid, self.take_dominance);
        let i = self.rng.below(top.len()); // never empty: the tier chain ends in [pass]
        Some(top[i].clone())
    }

    /// Play a short, cheap continuation then evaluate (steps=0 -> a static leaf).
    ///
    /// Whether the rollout earns its ~40x cost per sim is game-specific and MEASURED, not
    /// assumed: Spender's static value-leaf beats its rollout, while Castles of Crimson
    /// needs the rollout (its payoffs are delayed, so a 0-step leaf undervalues in-flight
    /// turns). See `ai_selfplay.probe`.
    fn rollout(&mut self, st: &mut State, pid: usize) -> f64 {
        for _ in 0..self.steps {
            if st.is_over() {
                break;
            }
            let actor = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
            let mv = match self.rollout_move(st, actor) {
                Some(m) => m,
                None => break,
            };
            let mut sh = RngShuffler { rng: &mut *self.rng };
            if st.apply_move(actor, &mv, &mut sh).is_err() {
                break;
            }
        }
        value(st, pid)
    }

    /// One simulation. Returns the value from ROOT_PID's perspective.
    ///
    /// Turns don't strictly alternate (AGAIN chains, pendings), so each edge is credited
    /// by the ACTING player's identity, not by parity.
    fn simulate(&mut self, st: &mut State, node: &mut Node, root_pid: usize, depth: usize) -> f64 {
        if st.is_over() || depth >= MAX_TREE_DEPTH {
            return self.leaf_eval(st, root_pid);
        }
        let total: i32 = node.n.iter().sum();
        let i = select(node, total);
        let mv = node.moves[i].clone();
        let ok = {
            let mut sh = RngShuffler { rng: &mut *self.rng };
            st.apply_move(node.actor, &mv, &mut sh).is_ok()
        };
        if !ok {
            return value(st, root_pid);
        }
        if node.children[i].is_none() {
            let v = if st.is_over() {
                value(st, root_pid)
            } else {
                let actor = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
                let moves = legal(st, actor, self.take_dominance);
                node.children[i] = Some(Box::new(Node::new(actor, moves)));
                self.leaf_eval(st, root_pid)
            };
            node.n[i] += 1;
            node.w[i] += v;
            return v;
        }
        let v = {
            let child = node.children[i].as_mut().unwrap();
            self.simulate(st, child, root_pid, depth + 1)
        };
        node.n[i] += 1;
        node.w[i] += v;
        v
    }
}

/// The root move list for a decision — the INDEX SPACE every root statistic is reported
/// in.
///
/// Exposed because root-parallel serving pools statistics BY INDEX across workers that
/// each ran their own search: they agree only because this is a pure function of the
/// state, and every worker ingests the identical projection. Any consumer of
/// `root_search`'s arrays MUST index them with this exact list (in particular it is the
/// PRUNED search-legality list, not `engine::legal_moves` — see `legal`).
pub fn root_moves(st: &State, pid: usize, take_dominance: bool) -> Vec<Move> {
    legal(st, pid, take_dominance)
}

/// The root's raw statistics, before any pick is applied.
pub struct RootStats {
    pub moves: Vec<Move>,
    /// Visit count per root move.
    pub n: Vec<i32>,
    /// SUMMED value per root move (`w[i]/n[i]` is the mean Q). Summed rather than
    /// averaged so N independent searches pool by plain addition: `n` and `w` are both
    /// additive, hence so is the pooled mean.
    pub w: Vec<f64>,
}

/// Run the determinized MCTS for `pid`'s current decision and return the root statistics.
///
/// Split out of `choose_move` so client-side serving can fan this to N workers and pick
/// on the POOLED counts — the pick is a pure function of `(n, w)`, so pooling then
/// picking is exactly what one search of the combined sim count would do.
///
/// `opts.take_dominance = Some(false)` disables the dominated-take prune for THIS decision
/// — the A/B hook for `ai_selfplay`'s "hard+nodom" spec. Per-call rather than global, so an
/// arena can vary ONE side (the same reason `rollout_steps` is a parameter).
///
/// A single legal move is returned UNSEARCHED (`n = [0]`), mirroring `choose_move`'s
/// original short-circuit: there is nothing to decide, and the picks below both resolve
/// an all-zero root to index 0.
pub fn root_search(st: &State, pid: usize, diff: &str, opts: &Opts, rng: &mut Rng) -> Option<RootStats> {
    root_search_with_leaf(st, pid, diff, opts, Leaf::Heuristic, rng)
}

/// `root_search` with an explicit leaf evaluator. The Phase-2 entry point: pass
/// `Leaf::Net(&net)` to search with the learned value at the truncation. `Leaf::Heuristic`
/// reproduces `root_search` exactly (that is what `root_search` calls).
pub fn root_search_with_leaf(
    st: &State,
    pid: usize,
    diff: &str,
    opts: &Opts,
    leaf: Leaf,
    rng: &mut Rng,
) -> Option<RootStats> {
    let take_dominance = opts.take_dominance.unwrap_or(true);
    let cfg = difficulty(diff);
    let time_limit = opts.time_limit.unwrap_or(cfg.time_limit);
    let max_iters = opts.max_iters.unwrap_or(cfg.max_iters);
    let steps = opts.rollout_steps.unwrap_or(cfg.rollout_steps);

    let moves = root_moves(st, pid, take_dominance);
    if moves.is_empty() {
        return None;
    }
    if moves.len() == 1 {
        return Some(RootStats { moves, n: vec![0], w: vec![0.0] });
    }

    let mut root = Node::new(pid, moves);
    let deadline = Deadline::new(time_limit);
    let mut s = Search { rng, take_dominance, steps, leaf };
    let mut iters: u64 = 0;
    while iters < max_iters && !deadline.expired() {
        iters += 1;
        let mut sim = s.determinize(st, pid);
        s.simulate(&mut sim, &mut root, pid, 0);
    }
    Some(RootStats { moves: root.moves, n: root.n, w: root.w })
}

/// Apply the tier's pick rule to root statistics. Pure in `(n, w)` — which is what lets
/// serving pool several searches and call this once on the sum.
pub fn pick(stats: &RootStats, temperature: f64, rng: &mut Rng) -> usize {
    if temperature > 0.0 {
        if let Some(i) = pick_temperature(stats, temperature, rng) {
            return i;
        }
    }
    pick_greedy(stats)
}

/// Pick a move for `pid`'s current decision via determinized MCTS (heuristic leaf).
pub fn choose_move(
    st: &State,
    pid: usize,
    diff: &str,
    opts: &Opts,
    rng: &mut Rng,
) -> Option<Move> {
    choose_move_with_leaf(st, pid, diff, opts, Leaf::Heuristic, rng)
}

/// `choose_move` with an explicit leaf evaluator — the Phase-2 net-leaf entry point. Pure
/// delegation to `root_search_with_leaf` + `pick`, so `Leaf::Heuristic` == `choose_move`.
pub fn choose_move_with_leaf(
    st: &State,
    pid: usize,
    diff: &str,
    opts: &Opts,
    leaf: Leaf,
    rng: &mut Rng,
) -> Option<Move> {
    let temperature = opts.temperature.unwrap_or(difficulty(diff).temperature);
    let stats = root_search_with_leaf(st, pid, diff, opts, leaf, rng)?;
    let i = pick(&stats, temperature, rng);
    Some(stats.moves[i].clone())
}

/// Sample by VALUE (softmax over mean Q), NOT by visit count.
///
/// The usual AlphaZero trick — sample proportional to visits — is WRONG for this search and
/// was measured so: selection is deliberately exploration-heavy, so visits come out
/// near-uniform across all ~76 branches (quality lives in Q, not in the visit
/// distribution). Temperature-on-visits therefore collapses to a uniform random move, and
/// the "normal" tier LOST to the trivial random-legal bot 0.20. Softmax over Q gives a real
/// "understands but errs" opponent instead.
///
/// `None` when nothing was visited at all (the caller falls back to the greedy pick) —
/// which is also how an unsearched single-move root resolves without drawing from the rng.
fn pick_temperature(root: &RootStats, temperature: f64, rng: &mut Rng) -> Option<usize> {
    let scored: Vec<(usize, f64)> = (0..root.moves.len())
        .filter(|&i| root.n[i] != 0)
        .map(|i| (i, root.w[i] / root.n[i] as f64))
        .collect();
    if scored.is_empty() {
        return None;
    }
    let top = scored.iter().map(|&(_, q)| q).fold(f64::NEG_INFINITY, f64::max);
    let weights: Vec<f64> = scored.iter().map(|&(_, q)| ((q - top) / temperature).exp()).collect();
    Some(scored[rng.weighted(&weights)].0)
}

/// Visit count first, mean value as the TIE-BREAK.
///
/// The tie-break is load-bearing when sims are thin relative to the branching factor:
/// without it `max` returns the FIRST index, which is whatever legal_moves enumerates first
/// (a token take) — a badly under-sampled search then "always takes tokens", never buys, and
/// the game literally never ends (Duel has no turn limit). That is the deployed regime, not
/// a corner case: the Python bot gets ~5 sims per root move on Render.
///
/// `webapp/public/wasm/duel-worker.js` does NOT reimplement this — the main thread pools
/// the workers' `(n, w)` and hands them back to `duel_pick_move`, so this stays the only
/// copy of the rule.
fn pick_greedy(root: &RootStats) -> usize {
    let key = |i: usize| -> (i32, f64) {
        (root.n[i], if root.n[i] != 0 { root.w[i] / root.n[i] as f64 } else { -2.0 })
    };
    let mut best_i = 0usize;
    let mut best = key(0);
    for i in 1..root.moves.len() {
        let k = key(i);
        // Strict `>` on the (n, q) tuple: Python's `max` keeps the FIRST maximum.
        if k.0 > best.0 || (k.0 == best.0 && k.1 > best.1) {
            best = k;
            best_i = i;
        }
    }
    best_i
}

/// Plan `pid`'s whole turn on a CLONE and return the move sequence.
///
/// The server applies these back one at a time (re-validating each), so the heavy search
/// runs off the event loop. Stops when the turn passes to the opponent — an AGAIN chain
/// keeps the same `turn`, so the guard is the ACTOR, not the turn field.
///
/// The turn's total think time is capped by `turn_budget`: each decision gets at most the
/// tier's per-decision `time_limit` AND whatever budget remains, so a multi-decision turn
/// can't multiply the wait. Once the budget is spent the rest of the turn still resolves (a
/// small floor per decision) rather than bailing to a half-planned turn.
pub fn play_turn_plan(
    st: &State,
    pid: usize,
    diff: &str,
    turn_budget: Option<f64>,
    rng: &mut Rng,
    max_moves: usize,
) -> Vec<Move> {
    let cfg = difficulty(diff);
    let turn_budget = turn_budget.unwrap_or(cfg.turn_budget);
    let mut sim = st.clone();
    let mut seq: Vec<Move> = Vec::new();
    let start = Clock::start();
    for _ in 0..max_moves {
        if sim.is_over() {
            break;
        }
        let actor = if sim.pending_pid != -1 { sim.pending_pid as usize } else { sim.turn };
        if actor != pid {
            break;
        }
        let left = turn_budget - start.elapsed_secs();
        let budget = cfg.time_limit.min(left).max(0.05); // floor: always decide, never stall
        let opts = Opts { time_limit: Some(budget), ..Default::default() };
        let mv = match choose_move(&sim, pid, diff, &opts, rng) {
            Some(m) => m,
            None => break,
        };
        let mut sh = RngShuffler { rng: &mut *rng };
        if sim.apply_move(pid, &mv, &mut sh).is_err() {
            break;
        }
        seq.push(mv);
    }
    seq
}

#[cfg(test)]
mod tests {
    use super::*;

    fn board_state(board: [i8; N_CELLS]) -> State {
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

    /// The exception that makes the dominance prune a prune and not a rules bug: a
    /// superset take that NEWLY gifts the opponent a privilege does not dominate its
    /// subset, so the subset must survive.
    #[test]
    fn a_gifting_superset_does_not_dominate_its_subset() {
        let mut board = [EMPTY; N_CELLS];
        // Three whites in a row: the 3-take gifts (3 of a colour), the 2-takes do not.
        board[0] = 0;
        board[1] = 0;
        board[2] = 0;
        let st = board_state(board);
        let takes = st.line_moves();
        let d = take_dominance_sets(&st.board, &takes);
        assert!(keep_take(&st.board, &[0, 1], &d), "a non-gifting 2-take must survive a gifting 3-take");
        assert!(!keep_take(&st.board, &[0], &d), "but the 1-take is still covered by that 2-take");
        assert!(keep_take(&st.board, &[0, 1, 2], &d), "a 3-take is always maximal");
    }

    /// ...and when the subset gifts too, the superset's gift is not a NEW cost, so the
    /// subset IS dominated.
    #[test]
    fn a_gifting_superset_dominates_an_already_gifting_subset() {
        let mut board = [EMPTY; N_CELLS];
        board[0] = PEARL as i8;
        board[1] = PEARL as i8;
        board[2] = 0; // white
        let st = board_state(board);
        let takes = st.line_moves();
        let d = take_dominance_sets(&st.board, &takes);
        // {0,1} is 2 pearls -> gifts; {0,1,2} is 2 pearls + white -> also gifts.
        assert!(take_gifts_privilege(&st.board, &[0, 1]));
        assert!(take_gifts_privilege(&st.board, &[0, 1, 2]));
        assert!(!keep_take(&st.board, &[0, 1], &d), "no new cost => dominated");
    }

    /// The prune must never strand the search: `legal` non-empty whenever `legal_moves` is.
    #[test]
    fn legal_never_empties_a_non_empty_move_list() {
        let mut board = [EMPTY; N_CELLS];
        for i in 0..N_CELLS {
            board[i] = (i % 5) as i8;
        }
        let st = board_state(board);
        assert!(!st.legal_moves(0).is_empty());
        assert!(!legal(&st, 0, true).is_empty());
        assert!(!legal(&st, 0, false).is_empty());
    }

    /// Determinization is the hidden-info boundary: the search must not be able to read
    /// the true deck order. Two states differing ONLY in that order must determinize
    /// identically under the same rng.
    #[test]
    fn determinize_is_blind_to_the_true_deck_order() {
        let mut a = board_state([EMPTY; N_CELLS]);
        a.decks[0] = vec![0, 1, 2, 3, 4];
        let mut b = a.clone();
        b.decks[0] = vec![4, 2, 0, 3, 1]; // same multiset, different order
        let da = {
            let mut rng = Rng::new(7);
            Search { rng: &mut rng, take_dominance: true, steps: 12, leaf: Leaf::Heuristic }.determinize(&a, 0)
        };
        let db = {
            let mut rng = Rng::new(7);
            Search { rng: &mut rng, take_dominance: true, steps: 12, leaf: Leaf::Heuristic }.determinize(&b, 0)
        };
        assert_eq!(da.decks[0], db.decks[0], "the sort must erase the true order");
    }

    /// A blind reserve is resampled WITHIN ITS LEVEL (which deck it came off is public),
    /// and the pool it is drawn from is that level's deck plus itself.
    #[test]
    fn blind_reserves_resample_within_their_level() {
        let mut st = board_state([EMPTY; N_CELLS]);
        st.decks[2] = vec![54, 55, 56];
        st.players[1].reserved = vec![10, 60]; // 10 = face-up L1, 60 = blind L3
        st.players[1].reserved_from_deck = vec![60];
        let mut rng = Rng::new(3);
        let d = Search { rng: &mut rng, take_dominance: true, steps: 12, leaf: Leaf::Heuristic }.determinize(&st, 0);
        assert_eq!(d.players[1].reserved_from_deck.len(), 1);
        let got = d.players[1].reserved_from_deck[0];
        assert!([54, 55, 56, 60].contains(&got), "redealt from the L3 pool, got {}", got);
        assert!(d.players[1].reserved.contains(&10), "the face-up reserve is public and kept");
        assert_eq!(d.decks[2].len(), 3, "deck sizes are public");
    }

    fn moves_for(k: usize) -> Vec<Move> {
        (0..k).map(|i| Move::Take { cells: vec![i] }).collect()
    }

    fn node_with(n: Vec<i32>, w: Vec<f64>) -> Node {
        let mut node = Node::new(0, moves_for(n.len()));
        node.n = n;
        node.w = w;
        node
    }

    /// The picks read only `(moves, n, w)` — which is exactly what lets root-parallel
    /// serving pool several searches and pick once on the sum.
    fn stats_with(n: Vec<i32>, w: Vec<f64>) -> RootStats {
        RootStats { moves: moves_for(n.len()), n, w }
    }

    /// THE load-bearing tie-break (ai.py: without it the bot "always takes tokens, never
    /// buys, and the game literally never ends"). `ai_parity` cannot see this — the RNG
    /// makes the tree unreproducible across languages — so it is pinned here instead.
    #[test]
    fn greedy_pick_breaks_visit_ties_by_mean_value() {
        // All tied at 1 visit; index 2 is the best move. A plain `max(n)` returns index 0.
        let root = stats_with(vec![1, 1, 1, 1], vec![-0.5, 0.0, 0.9, 0.2]);
        assert_eq!(pick_greedy(&root), 2, "a visit tie must resolve by value, not by index");
    }

    /// ...but visits still come FIRST: the tie-break is a tie-break, not a re-ranking.
    #[test]
    fn greedy_pick_prefers_visits_over_value() {
        let root = stats_with(vec![5, 1], vec![0.5, 0.9]); // q = 0.1 vs 0.9
        assert_eq!(pick_greedy(&root), 0, "more visits wins even with a worse mean");
    }

    /// An unvisited move scores -2.0, below any real q in [-1, 1], so it can never win a
    /// tie-break — and must not divide by zero.
    #[test]
    fn greedy_pick_never_prefers_an_unvisited_move() {
        let root = stats_with(vec![0, 0], vec![0.0, 0.0]);
        assert_eq!(pick_greedy(&root), 0, "all-unvisited falls back to the first index");
        let root = stats_with(vec![0, 1], vec![0.0, -1.0]);
        assert_eq!(pick_greedy(&root), 1, "even a losing visited move beats an unvisited one");
    }

    /// The "normal" tier samples a softmax over mean Q, NOT over visit counts — sampling
    /// by visits was measured to LOSE to the trivial random bot (0.200), because this
    /// search's visits are near-uniform by design so visit-temperature ~= uniform random.
    /// The node below makes the two disagree: move 0 is the most-VISITED, move 1 the best
    /// by Q. Sampling Q must pick move 1 essentially always (weight ratio ~2.5e-8).
    #[test]
    fn temperature_samples_value_not_visit_count() {
        let root = stats_with(vec![50, 1], vec![-25.0, 0.9]); // q = -0.5 vs 0.9
        let mut rng = Rng::new(42);
        for _ in 0..200 {
            let i = pick_temperature(&root, 0.08, &mut rng).expect("something was visited");
            assert_eq!(i, 1, "temperature must follow Q, not the visit count");
        }
    }

    /// `select` deliberately has NO 1/branches prior scaling — measured, not argued
    /// (prior@c1.5 vs no-prior@c1.5 scored 0.2500: effective c ~= 0.02, which commits to
    /// the noise of the first couple of rollouts). This pins the consequence: with one
    /// move looking perfect after 4 visits, exploration must STILL win. Divide `u` by the
    /// branch count and this flips to 0 — which is exactly the rejected config.
    #[test]
    fn select_explores_rather_than_committing_to_an_early_winner() {
        let mut n = vec![0; 10];
        let mut w = vec![0.0; 10];
        n[0] = 4;
        w[0] = 4.0; // q = 1.0, a perfect score so far
        let node = node_with(n, w);
        assert_eq!(select(&node, 4), 1, "an unvisited move must out-score a 4-visit q=1.0 move");
    }

    /// The whole point of the port: the search must actually terminate and return a legal
    /// move. (Strength is measured by the arena, not here.)
    #[test]
    fn choose_move_returns_a_legal_move() {
        let mut board = [EMPTY; N_CELLS];
        for i in 0..N_CELLS {
            board[i] = (i % 5) as i8;
        }
        let mut st = board_state(board);
        st.decks = [(0..30).collect(), (30..54).collect(), (54..67).collect()];
        st.pyramid = [vec![0, 1, 2, 3, 4], vec![30, 31, 32, 33], vec![54, 55, 56]];
        let mut rng = Rng::new(1);
        let opts = Opts { max_iters: Some(200), time_limit: Some(f64::INFINITY), ..Default::default() };
        let mv = choose_move(&st, 0, "hard", &opts, &mut rng).expect("a move");
        assert!(st.legal_moves(0).contains(&mv));
    }
}
