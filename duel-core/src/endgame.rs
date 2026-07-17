//! EXACT depth-limited minimax for the ENDGAME — the pivotal-decision perfecter.
//!
//! WHY THIS EXISTS (the measured case): `mcts` is a SAMPLED search with a heuristic leaf,
//! and its strength saturates ~700 sims (measured) — the leaf, not the sim count, is the
//! ceiling. Because it is sampled, near the end of a game it can MISS a forced win, or fail
//! to block a forced loss, among many near-tie moves. An exact actor-aware alpha-beta over
//! the ENGINE (the real rules) plays those pivotal decisions perfectly. (Spender shipped
//! exactly this as its #1 improvement.)
//!
//! HOW IT STAYS SOUND:
//!   * DETERMINIZE FIRST, then treat hidden info as KNOWN. `mcts::determinize_state`
//!     resamples the opponent's blind reserves + bag + deck order (the ONLY hidden info);
//!     the minimax then applies moves with an IDENTITY shuffler, so no fresh randomness
//!     enters — the whole search is deterministic and self-consistent within one
//!     determinization. Aggregating over M determinizations averages out the sampled hidden
//!     info (a move that wins across ALL M is a forced win under the uncertainty).
//!   * TERMINAL = EXACT ±1 (a FACT read from `winner`), never the heuristic. Only the DEPTH
//!     horizon falls back to `value` (the same leaf the MCTS truncates to).
//!   * ACTOR-AWARE min/max (NOT negate-every-ply): turns don't alternate here — AGAIN chains,
//!     pending sub-decisions and multi-action turns mean the same actor can move several
//!     times in a row — so each node is MAX iff its actor == root_pid, else MIN. The same
//!     actor simply keeps maximizing across an extended turn.
//!
//! APPROXIMATIONS (documented, never hidden):
//!   * The move set is `mcts::legal` (the deployed search's PRUNED set: dominated takes,
//!     duplicate reserve gold-cells and skip-pending removed), NOT raw `engine::legal_moves`.
//!     This keeps branching tractable AND makes the exact search CONSISTENT with the bot it
//!     augments. A buy that wins is never pruned, so forced wins are still found; the
//!     diagnostic + gate measure whether the prune ever costs a real line.
//!   * A per-determinization NODE CAP (plus an optional wall-clock deadline) bounds cost; a
//!     determinization that blows the cap is DISCARDED (inconclusive) and the caller falls
//!     back to the MCTS. The search never hangs.

use crate::cards::{BONUS, BONUS_WILD, CROWNS, PTS, WIN_COLOR_POINTS, WIN_CROWNS, WIN_POINTS};
use crate::clock::Clock;
use crate::engine::{color_points_of, crowns_of, points_of, Move, Shuffler, State};
use crate::mcts::{determinize_state, legal};
use crate::rng::Rng;
use crate::value::value;

/// Default endgame-search budget, sized from measured node counts on real endgame positions
/// (see `bin/endgame_diag.rs`). Depth is in MOVES (a turn is several consecutive same-actor
/// moves), so it is deep enough to see a couple of full turns each side.
pub const DEFAULT_DEPTH: usize = 14;
/// Nodes PER determinization; a det that trips this is inconclusive and discarded.
pub const DEFAULT_NODE_CAP: u64 = 250_000;
pub const DEFAULT_DETS: usize = 6;
/// `in_endgame` fires at this win-closeness: within ~6 points / 3 crowns / 3 color-points of
/// a win, i.e. plausibly one or two turns from the end.
pub const DEFAULT_THRESH: f64 = 0.7;

/// No-op shuffler: the determinization already fixed the bag/deck order, so a replenish
/// inside the minimax must pop from that KNOWN order rather than reshuffle. (Contrast
/// `engine::NoShuffle`, which PANICS to assert "this call site never fills" — here fills are
/// expected, and simply deterministic.)
pub struct IdentityShuffle;
impl Shuffler for IdentityShuffle {
    fn shuffle(&mut self, _bag: &mut Vec<u8>) {}
}

/// Closeness of the LEADING seat to any win, in [0, 1]: max over both players of
/// max(points/20, crowns/10, best_color/10).
pub fn win_closeness(st: &State) -> f64 {
    let mut best = 0.0f64;
    for pid in 0..2 {
        let p = &st.players[pid];
        let pts = points_of(p) as f64 / WIN_POINTS as f64;
        let cr = crowns_of(p) as f64 / WIN_CROWNS as f64;
        let col = *color_points_of(p).iter().max().unwrap() as f64 / WIN_COLOR_POINTS as f64;
        best = best.max(pts).max(cr).max(col);
    }
    best
}

/// True when a win is plausibly within a couple of turns (so the exact search is worth it).
pub fn in_endgame(st: &State, thresh: f64) -> bool {
    !st.is_over() && win_closeness(st) >= thresh
}

#[inline]
fn actor_of(st: &State) -> usize {
    if st.pending_pid != -1 {
        st.pending_pid as usize
    } else {
        st.turn
    }
}

/// A cheap STATIC "how much does this move advance ACTOR toward a win" score, higher = try
/// first. Ordering only affects alpha-beta SPEED, never the exact value, so an approximate
/// key is fine — win-progressing moves first make forced wins (and the opponent's forced
/// wins, at a MIN node) surface early and prune hard.
fn order_key(st: &State, actor: usize, mv: &Move) -> i64 {
    match mv {
        Move::Buy { card, .. } => {
            let p = &st.players[actor];
            let pts = points_of(p);
            let cr = crowns_of(p);
            let cp = color_points_of(p);
            let card_pts = PTS[*card];
            let card_cr = CROWNS[*card];
            let mut key: i64 = 1_000_000; // buys before everything else
            if pts + card_pts >= WIN_POINTS {
                key += 10_000_000; // an immediate points win
            }
            if cr + card_cr >= WIN_CROWNS {
                key += 10_000_000; // an immediate crowns win
            }
            let bon = BONUS[*card];
            if bon >= 0 && bon != BONUS_WILD && cp[bon as usize] + card_pts >= WIN_COLOR_POINTS {
                key += 10_000_000; // an immediate color win
            }
            key + (card_pts as i64) * 1000 + (card_cr as i64) * 500
        }
        // A royal is free points and can win; resolve pending gains before ordinary takes.
        Move::ChooseRoyal { .. } => 900_000,
        Move::Steal { .. } | Move::TakeSame { .. } => 800_000,
        Move::Take { cells } => 1000 + cells.len() as i64 * 10,
        Move::Reserve { .. } => 500,
        Move::Replenish | Move::UsePrivilege { .. } => 100,
        Move::Discard { .. } => 50,
        Move::Pass | Move::SkipPending => 0,
    }
}

/// One determinization's exact-minimax machinery. `root_pid`-perspective throughout.
struct Minimax {
    root_pid: usize,
    max_depth: usize,
    node_cap: u64,
    nodes: u64,
    aborted: bool,
}

impl Minimax {
    fn ordered_moves(&self, st: &State, actor: usize) -> Vec<Move> {
        let mut moves = legal(st, actor, true);
        moves.sort_by_key(|m| std::cmp::Reverse(order_key(st, actor, m)));
        moves
    }

    /// The minimax value from root_pid's perspective, in [-1, 1]. `alpha`/`beta` are
    /// root-perspective bounds. `depth` counts moves already applied from the determinized
    /// root. Sets `self.aborted` (and returns a junk 0.0) once the node cap trips — every
    /// caller checks `aborted` immediately after, so the junk is never used.
    fn search(&mut self, st: &State, depth: usize, mut alpha: f64, mut beta: f64) -> f64 {
        self.nodes += 1;
        if self.nodes > self.node_cap {
            self.aborted = true;
            return 0.0;
        }
        if st.is_over() {
            // A FACT, not a prediction — exact terminal value.
            return if st.winner == self.root_pid as i32 { 1.0 } else { -1.0 };
        }
        if depth >= self.max_depth {
            return value(st, self.root_pid); // heuristic horizon (the MCTS's own leaf)
        }
        let actor = actor_of(st);
        let moves = self.ordered_moves(st, actor);
        let maximizing = actor == self.root_pid;
        if maximizing {
            let mut best = f64::NEG_INFINITY;
            for m in &moves {
                let mut child = st.clone();
                let mut sh = IdentityShuffle;
                if child.apply_move(actor, m, &mut sh).is_err() {
                    continue; // legal() only emits legal moves; guard defensively
                }
                let v = self.search(&child, depth + 1, alpha, beta);
                if self.aborted {
                    return 0.0;
                }
                if v > best {
                    best = v;
                }
                if best > alpha {
                    alpha = best;
                }
                if alpha >= beta {
                    break; // beta cut
                }
            }
            if best == f64::NEG_INFINITY {
                return value(st, self.root_pid); // no applicable move (defensive)
            }
            best
        } else {
            let mut best = f64::INFINITY;
            for m in &moves {
                let mut child = st.clone();
                let mut sh = IdentityShuffle;
                if child.apply_move(actor, m, &mut sh).is_err() {
                    continue;
                }
                let v = self.search(&child, depth + 1, alpha, beta);
                if self.aborted {
                    return 0.0;
                }
                if v < best {
                    best = v;
                }
                if best < beta {
                    beta = best;
                }
                if beta <= alpha {
                    break; // alpha cut
                }
            }
            if best == f64::INFINITY {
                return value(st, self.root_pid);
            }
            best
        }
    }
}

/// The full per-root-move result, exposed so a diagnostic can compare the MCTS's pick against
/// every move's exact value.
pub struct EndgameResult {
    /// The root move list — the SAME index space `mcts::root_moves` uses (both call `legal`).
    pub moves: Vec<Move>,
    /// Mean minimax value per root move over the COMPLETED determinizations (root_pid's
    /// perspective, [-1, 1]).
    pub values: Vec<f64>,
    pub best_idx: usize,
    /// The best move is a PROVEN forced win: exact value == +1 (a reached terminal, backed up
    /// through the min/max) in EVERY completed determinization.
    pub proven_win: bool,
    /// How many of `n_dets` determinizations completed (didn't trip the cap / deadline).
    pub dets_completed: usize,
    /// Total nodes expanded across all completed + aborted determinizations (tractability).
    pub nodes: u64,
}

/// Evaluate EVERY root move by exact minimax, aggregated over `n_dets` determinizations.
///
/// `None` when there is nothing to decide (`root_pid` has <=1 legal move, or it is not
/// `root_pid`'s decision) or when EVERY determinization was inconclusive.
///
/// `node_cap` bounds EACH determinization (one that trips it is discarded whole);
/// `time_limit_s` (None = unbounded) bounds the WHOLE call. Each root move is searched with a
/// FRESH full alpha-beta window so it gets its EXACT value (no root-level pruning — we need
/// every move's value to aggregate and to answer "did the MCTS pick a winning move?").
pub fn endgame_evaluate(
    st: &State,
    root_pid: usize,
    max_depth: usize,
    node_cap: u64,
    n_dets: usize,
    seed: u64,
    time_limit_s: Option<f64>,
) -> Option<EndgameResult> {
    if st.is_over() || actor_of(st) != root_pid {
        return None; // not this seat's decision
    }
    let moves = legal(st, root_pid, true);
    if moves.len() <= 1 {
        return None; // no real decision — let the caller play the forced move
    }

    let clock = Clock::start();
    let expired = |c: &Clock| time_limit_s.is_some_and(|l| c.elapsed_secs() >= l);

    let mut rng = Rng::new(seed);
    let k = moves.len();
    let mut sums = vec![0.0f64; k];
    let mut all_win = vec![true; k]; // per-move "== +1 in every completed det" tracker
    let mut completed = 0usize;
    let mut total_nodes = 0u64;

    for _ in 0..n_dets {
        if expired(&clock) {
            break;
        }
        let det = determinize_state(st, root_pid, &mut rng);
        // One node budget for the WHOLE determinization (all root moves share it).
        let mut mm = Minimax { root_pid, max_depth, node_cap, nodes: 0, aborted: false };
        let mut det_vals = vec![0.0f64; k];
        let mut det_ok = true;
        for (i, m) in moves.iter().enumerate() {
            let mut child = det.clone();
            let mut sh = IdentityShuffle;
            if child.apply_move(root_pid, m, &mut sh).is_err() {
                det_vals[i] = -1.0; // can't happen (from legal); treat as worst
                continue;
            }
            // Continue the minimax from depth 1 — the root move is the first ply.
            let v = mm.search(&child, 1, f64::NEG_INFINITY, f64::INFINITY);
            if mm.aborted || expired(&clock) {
                det_ok = false;
                break;
            }
            det_vals[i] = v;
        }
        total_nodes += mm.nodes;
        if !det_ok {
            continue; // discard this determinization entirely (inconclusive)
        }
        completed += 1;
        for i in 0..k {
            sums[i] += det_vals[i];
            if det_vals[i] < 1.0 - 1e-9 {
                all_win[i] = false;
            }
        }
    }

    if completed == 0 {
        return None; // every determinization blew the cap / deadline
    }
    let values: Vec<f64> = sums.iter().map(|&s| s / completed as f64).collect();
    // Pick the max mean value; ties resolve to the lower index (deterministic).
    let mut best_idx = 0usize;
    for i in 1..k {
        if values[i] > values[best_idx] {
            best_idx = i;
        }
    }
    let proven_win = all_win[best_idx];
    Some(EndgameResult { moves, values, best_idx, proven_win, dets_completed: completed, nodes: total_nodes })
}

/// Convenience wrapper: the best move + its aggregated value + whether it is a PROVEN forced
/// win. `None` when the endgame search does not apply (see `endgame_evaluate`), so the caller
/// falls back to the MCTS.
pub fn endgame_search(
    st: &State,
    root_pid: usize,
    max_depth: usize,
    node_cap: u64,
    n_dets: usize,
    seed: u64,
) -> Option<(Move, f64, bool)> {
    let r = endgame_evaluate(st, root_pid, max_depth, node_cap, n_dets, seed, None)?;
    Some((r.moves[r.best_idx].clone(), r.values[r.best_idx], r.proven_win))
}

/// The FAST serving decision (root-level alpha-beta per determinization).
pub struct EndgameDecision {
    pub best: Move,
    /// Mean value of the best move over the determinizations it was chosen in.
    pub value: f64,
    /// The best move is an exact win (+1) in EVERY completed determinization.
    pub proven_win: bool,
    pub dets_completed: usize,
    pub nodes: u64,
}

/// FAST endgame decision: root-level alpha-beta on each determinization instead of the
/// per-move full-window search of `endgame_evaluate`.
///
/// WHY THIS IS THE SERVING PATH (and resolves more positions): the root moves are tried in
/// WIN-FIRST order, so a forced win is found EARLY — its `alpha = +1` then makes every
/// remaining root move cheap (each opponent reply immediately beta-cuts below +1). So a
/// forced-win position resolves even when a NON-winning sibling would need a deep subtree —
/// exactly the case `endgame_evaluate` (which searches every sibling to a full window) marks
/// inconclusive. For a position with NO forced win it still must prove the best line, so it
/// can still hit the node cap and fall back — which is correct (no win to capture there).
///
/// Aggregation across `n_dets`: the best move is the one chosen best in the most
/// determinizations (tie-break: summed value); `proven_win` iff that move is an exact win in
/// EVERY completed determinization. `None` if every determinization tripped the cap/deadline.
pub fn endgame_decide(
    st: &State,
    root_pid: usize,
    max_depth: usize,
    node_cap: u64,
    n_dets: usize,
    seed: u64,
    time_limit_s: Option<f64>,
) -> Option<EndgameDecision> {
    if st.is_over() || actor_of(st) != root_pid {
        return None;
    }
    let moves = legal(st, root_pid, true);
    if moves.len() <= 1 {
        return None;
    }
    // Win-first order over the root moves, computed ONCE (the root move list + its static keys
    // are identical across determinizations — determinize only touches HIDDEN info, never
    // root_pid's own legal moves).
    let mut order: Vec<usize> = (0..moves.len()).collect();
    order.sort_by_key(|&i| std::cmp::Reverse(order_key(st, root_pid, &moves[i])));

    let clock = Clock::start();
    let expired = |c: &Clock| time_limit_s.is_some_and(|l| c.elapsed_secs() >= l);
    let mut rng = Rng::new(seed);
    let k = moves.len();
    let mut chosen = vec![0usize; k];
    let mut valsum = vec![0.0f64; k];
    let mut winsum = vec![0usize; k];
    let mut completed = 0usize;
    let mut total_nodes = 0u64;

    for _ in 0..n_dets {
        if expired(&clock) {
            break;
        }
        let det = determinize_state(st, root_pid, &mut rng);
        let mut mm = Minimax { root_pid, max_depth, node_cap, nodes: 0, aborted: false };
        let mut alpha = f64::NEG_INFINITY;
        let mut best_val = f64::NEG_INFINITY;
        let mut best_i = order[0];
        let mut aborted = false;
        for &i in &order {
            let mut child = det.clone();
            let mut sh = IdentityShuffle;
            if child.apply_move(root_pid, &moves[i], &mut sh).is_err() {
                continue;
            }
            // Root MAX node: no parent beta bound, but a rising alpha (from the win found early)
            // makes the remaining siblings' opponent replies beta-cut immediately.
            let v = mm.search(&child, 1, alpha, f64::INFINITY);
            if mm.aborted {
                aborted = true;
                break;
            }
            if v > best_val {
                best_val = v;
                best_i = i;
            }
            if best_val > alpha {
                alpha = best_val;
            }
        }
        total_nodes += mm.nodes;
        if aborted {
            continue;
        }
        completed += 1;
        chosen[best_i] += 1;
        valsum[best_i] += best_val;
        if best_val >= 1.0 - 1e-9 {
            winsum[best_i] += 1;
        }
    }

    if completed == 0 {
        return None;
    }
    let mut bi = 0usize;
    for i in 1..k {
        if (chosen[i], valsum[i]) > (chosen[bi], valsum[bi]) {
            bi = i;
        }
    }
    let value = if chosen[bi] > 0 { valsum[bi] / chosen[bi] as f64 } else { -1.0 };
    let proven_win = winsum[bi] == completed;
    Some(EndgameDecision { best: moves[bi].clone(), value, proven_win, dets_completed: completed, nodes: total_nodes })
}

/// The exact aggregated value of ONE specific root move over `n_dets` determinizations (mean,
/// root_pid's perspective), searched with a full window. Used by the diagnostic to ask "is the
/// move the MCTS chose actually winning / non-losing?" — over the SAME determinization sequence
/// `endgame_decide` uses (same seed). `None` if the move is illegal or every det tripped the cap.
pub fn endgame_move_value(
    st: &State,
    root_pid: usize,
    mv: &Move,
    max_depth: usize,
    node_cap: u64,
    n_dets: usize,
    seed: u64,
) -> Option<f64> {
    if st.is_over() || actor_of(st) != root_pid {
        return None;
    }
    let mut rng = Rng::new(seed);
    let mut sum = 0.0f64;
    let mut completed = 0usize;
    for _ in 0..n_dets {
        let det = determinize_state(st, root_pid, &mut rng);
        let mut child = det.clone();
        let mut sh = IdentityShuffle;
        if child.apply_move(root_pid, mv, &mut sh).is_err() {
            return None; // not a legal root move here
        }
        let mut mm = Minimax { root_pid, max_depth, node_cap, nodes: 0, aborted: false };
        let v = mm.search(&child, 1, f64::NEG_INFINITY, f64::INFINITY);
        if mm.aborted {
            continue;
        }
        sum += v;
        completed += 1;
    }
    if completed == 0 {
        None
    } else {
        Some(sum / completed as f64)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::{EMPTY, N_CELLS};

    // Card 29 (d1_29): 3 points, 0 crowns, bonus-less, cost = 4 red + 1 pearl.
    // Card 21 (d1_21): 0 points, 1 crown, bonus red, cost = 3 white.
    // Both are on the pyramid in these fixtures; realistic token stocks avoid the >10 discard
    // cascade (which would balloon the tree without changing the point of the test).
    const RED: usize = 3;
    const PEARL_T: usize = 5;
    const WHITE: usize = 0;

    fn state(board: [i8; N_CELLS], pyramid: [Vec<i32>; 3], decks: [Vec<usize>; 3]) -> State {
        State::from_setup(board, Vec::new(), decks, pyramid, 0, vec![], [0, 0])
    }

    fn empty_board() -> [i8; N_CELLS] {
        [EMPTY; N_CELLS]
    }

    fn tokens(white: i32, red: i32, pearl: i32) -> [i32; 7] {
        let mut t = [0; 7];
        t[WHITE] = white;
        t[RED] = red;
        t[PEARL_T] = pearl;
        t
    }

    /// A constructed position with a 1-move win => `endgame_search` returns it, PROVEN, +1.
    ///
    /// Seat 0 has 18 points and, from the pyramid, can buy card 29 (+3 => 21 >= 20, an
    /// immediate points win) OR the harmless card 21 (0 pts). The winning buy must be chosen
    /// and scored EXACTLY +1 (a terminal fact, not the heuristic).
    #[test]
    fn finds_the_one_move_win() {
        let mut st = state(
            empty_board(),
            [vec![29, 21, -1, -1, -1], vec![-1; 4], vec![-1; 3]],
            [vec![], vec![], vec![]],
        );
        st.players[0].purchased = vec![(29, -1); 6]; // 18 points
        assert_eq!(points_of(&st.players[0]), 18);
        st.players[0].tokens = tokens(3, 4, 1); // affords 29 (4R+1P) AND 21 (3W)
        st.turn = 0;
        let (mv, val, proven) = endgame_search(&st, 0, 6, 500_000, 1, 7).expect("a move");
        assert!(proven, "the 1-move win must be proven");
        assert!((val - 1.0).abs() < 1e-9, "the win value must be exactly +1, got {}", val);
        assert!(matches!(mv, Move::Buy { card: 29, .. }), "must play the winning buy, got {:?}", mv);
    }

    /// The opponent wins next turn unless blocked => the search picks the BLOCK.
    ///
    /// It is seat 0's turn. Seat 1 has 18 points and, on their turn, would buy card 29 (the
    /// only affordable pyramid card) to reach 21 and win. Seat 0 has two options: buy card 29
    /// (DENYING it — it leaves the pyramid) or buy the harmless card 21 (leaving card 29 for
    /// seat 1). Board is empty and there is no gold, so those buys are the only moves. The
    /// exact search must choose the denial; the non-denial line is a forced loss (-1).
    #[test]
    fn blocks_the_opponents_forced_win() {
        let mut st = state(
            empty_board(),
            [vec![29, 21, -1, -1, -1], vec![-1; 4], vec![-1; 3]],
            [vec![], vec![], vec![]],
        );
        st.players[1].purchased = vec![(29, -1); 6]; // seat 1: 18 points, one buy from 21
        st.players[0].tokens = tokens(3, 4, 1); // seat 0 can afford BOTH 29 and 21
        st.players[1].tokens = tokens(0, 4, 1); // seat 1 can afford 29
        st.turn = 0;
        let r = endgame_evaluate(&st, 0, 6, 1_000_000, 1, 3, None).expect("a decision");
        match &r.moves[r.best_idx] {
            Move::Buy { card, .. } => assert_eq!(*card, 29, "must deny the winning card by buying it"),
            other => panic!("expected the denial buy, got {:?}", other),
        }
        assert!(r.values[r.best_idx] > -1.0 + 1e-9, "the block is not a forced loss");
        assert!(r.values.iter().any(|&v| v < -1.0 + 1e-9), "the non-blocking line must lose (-1)");
    }

    /// A determinized minimax on a near-terminal FORCED LOSS returns exactly -1.
    ///
    /// Seat 0 is to move with no points and no way to deny: seat 1 has 18 points and card 29
    /// on the pyramid (which seat 1 can afford, seat 0 cannot). Seat 0 has two harmless takes
    /// (two isolated board tokens); either way seat 1 buys card 29 next turn and wins. Every
    /// line is a terminal loss, so the exact value is -1 (and NOT a proven win).
    #[test]
    fn near_terminal_forced_loss_is_exactly_minus_one() {
        let mut board = empty_board();
        board[0] = WHITE as i8; // two isolated takeable tokens (no line between 0 and 4)
        board[4] = 1; // blue
        let mut st = state(
            board,
            [vec![29, -1, -1, -1, -1], vec![-1; 4], vec![-1; 3]],
            [vec![], vec![], vec![]],
        );
        st.players[1].purchased = vec![(29, -1); 6]; // seat 1: 18 points
        st.players[0].tokens = tokens(0, 0, 0); // seat 0 can afford nothing (can only take)
        st.players[1].tokens = tokens(0, 4, 1); // seat 1 can afford card 29
        st.turn = 0;
        let r = endgame_evaluate(&st, 0, 6, 1_000_000, 1, 11, None).expect("a decision");
        assert!(!r.proven_win, "a forced loss is not a proven win");
        for &v in &r.values {
            assert!((v + 1.0).abs() < 1e-9, "every line is a forced loss (-1), got {}", v);
        }
    }

    /// The fast serving path (`endgame_decide`, root alpha-beta) finds the same 1-move win.
    #[test]
    fn decide_finds_the_one_move_win() {
        let mut st = state(
            empty_board(),
            [vec![29, 21, -1, -1, -1], vec![-1; 4], vec![-1; 3]],
            [vec![], vec![], vec![]],
        );
        st.players[0].purchased = vec![(29, -1); 6]; // 18 points
        st.players[0].tokens = tokens(3, 4, 1);
        st.turn = 0;
        let d = endgame_decide(&st, 0, 6, 500_000, 1, 7, None).expect("a decision");
        assert!(d.proven_win, "the 1-move win must be proven");
        assert!((d.value - 1.0).abs() < 1e-9);
        assert!(matches!(d.best, Move::Buy { card: 29, .. }), "must play the win, got {:?}", d.best);
    }

    /// The fast serving path also picks the BLOCK (root alpha-beta maximizes, so it avoids the
    /// -1 line automatically).
    #[test]
    fn decide_blocks_the_opponents_forced_win() {
        let mut st = state(
            empty_board(),
            [vec![29, 21, -1, -1, -1], vec![-1; 4], vec![-1; 3]],
            [vec![], vec![], vec![]],
        );
        st.players[1].purchased = vec![(29, -1); 6];
        st.players[0].tokens = tokens(3, 4, 1);
        st.players[1].tokens = tokens(0, 4, 1);
        st.turn = 0;
        let d = endgame_decide(&st, 0, 6, 1_000_000, 1, 3, None).expect("a decision");
        assert!(matches!(d.best, Move::Buy { card: 29, .. }), "must deny the win, got {:?}", d.best);
        assert!(d.value > -1.0 + 1e-9, "the block is not a forced loss");
        assert!(!d.proven_win, "denying is not itself a forced win");
    }

    /// `endgame_move_value` distinguishes the BLOCK (value > -1) from the non-blocking line
    /// that hands the opponent the win (value == -1). Uses the block position so the two moves
    /// genuinely differ (unlike a passive-opponent position, where every line eventually wins).
    #[test]
    fn move_value_scores_a_block_above_a_forced_loss() {
        let mut st = state(
            empty_board(),
            [vec![29, 21, -1, -1, -1], vec![-1; 4], vec![-1; 3]],
            [vec![], vec![], vec![]],
        );
        st.players[1].purchased = vec![(29, -1); 6]; // seat 1 threatens to win with card 29
        st.players[0].tokens = tokens(3, 4, 1);
        st.players[1].tokens = tokens(0, 4, 1);
        st.turn = 0;
        let block = Move::Buy { card: 29, from: crate::engine::BuySrc::Pyramid, as_color: -1 };
        let lose = Move::Buy { card: 21, from: crate::engine::BuySrc::Pyramid, as_color: -1 };
        let vb = endgame_move_value(&st, 0, &block, 6, 1_000_000, 1, 5).expect("block value");
        let vl = endgame_move_value(&st, 0, &lose, 6, 1_000_000, 1, 5).expect("losing value");
        assert!(vb > -1.0 + 1e-9, "denying the win is not a forced loss, got {}", vb);
        assert!((vl + 1.0).abs() < 1e-9, "leaving card 29 hands seat 1 the win (-1), got {}", vl);
    }

    /// `in_endgame` fires exactly at the closeness threshold and is symmetric across seats.
    #[test]
    fn in_endgame_threshold() {
        let mut st = state(empty_board(), [vec![-1; 5], vec![-1; 4], vec![-1; 3]], [vec![], vec![], vec![]]);
        assert!(!in_endgame(&st, 0.7), "a fresh position is not an endgame");
        // Seat 1 (NOT the mover) drives the closeness — symmetry across seats.
        st.players[1].purchased = vec![(29, -1); 4]; // 12 points -> 0.60, below
        assert!(!in_endgame(&st, 0.7));
        st.players[1].purchased = vec![(29, -1); 5]; // 15 points -> 0.75, above
        assert!(in_endgame(&st, 0.7));
    }
}
