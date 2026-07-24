//! Ingestion of `games/spender_duel/compact.py`'s projection into a `State`.
//!
//! `compact.py` is AUTHORITATIVE for the shape and for what may be shipped at all (read
//! its module docstring before touching this file — it is the hidden-information
//! contract, not just a serializer). This side only reconstitutes it.
//!
//! THE ONE JUDGEMENT CALL, and why it is safe. The projection deliberately does NOT
//! carry deck order or the opponent's blind-reserve identities, so this function has to
//! invent them: it deals the opponent's blind reserves off the END of each level's
//! sorted unseen pool and takes the deck off the FRONT. Those identities are FICTION,
//! and they are meant to be — `mcts::Search::determinize` re-pools exactly these two
//! groups, canonicalizes, shuffles and re-deals them at the top of EVERY simulation, so
//! nothing the search reports can depend on them. What must be exact, and is, are the
//! things determinize preserves and the root reads before it runs:
//!
//!   * each deck's LENGTH (gates `reserve` from that deck in the root's `legal_moves`),
//!   * the pooled multiset per level (what determinize re-deals from),
//!   * `reserved.len()` for both seats (the leaf's `w.reserved` term),
//!   * the SEAT's OWN reserved ids and their ORDER (`buy_moves` enumerates them in
//!     order, and the rollout samples that list by index).
//!
//! Determinism matters for a second reason: root-parallel serving fans the SAME
//! projection to N workers and pools their root statistics BY INDEX, so every worker
//! must derive the same root move list. That holds because this function is a pure
//! function of the projection and `mcts::legal` is a pure function of the state.

use serde_json::Value;

use crate::cards::{LEVEL_OF, N_COLORS, N_ROYALS, N_TOKENS};
use crate::engine::{
    Pending, Player, State, Via, EMPTY, N_CELLS, OVER, PK_NONE, PLAYING,
};

fn i64_at(v: &Value, k: &str) -> Option<i64> {
    v.get(k)?.as_i64()
}

fn usize_vec(v: &Value, k: &str) -> Option<Vec<usize>> {
    Some(v.get(k)?.as_array()?.iter().filter_map(|x| x.as_u64()).map(|x| x as usize).collect())
}

fn i64_vec(v: &Value, k: &str) -> Option<Vec<i64>> {
    Some(v.get(k)?.as_array()?.iter().filter_map(|x| x.as_i64()).collect())
}

fn player_from(v: &Value) -> Option<Player> {
    let toks = i64_vec(v, "tokens")?;
    if toks.len() != N_TOKENS {
        return None;
    }
    let mut tokens = [0i32; N_TOKENS];
    for (i, t) in toks.iter().enumerate() {
        tokens[i] = *t as i32;
    }
    let purchased = v
        .get("purchased")?
        .as_array()?
        .iter()
        .filter_map(|e| {
            let a = e.as_array()?;
            Some((a.first()?.as_u64()? as usize, a.get(1)?.as_i64()? as i8))
        })
        .collect();
    Some(Player {
        tokens,
        privileges: i64_at(v, "privileges")? as i32,
        reserved: usize_vec(v, "reserved")?,
        reserved_from_deck: usize_vec(v, "reserved_from_deck")?,
        purchased,
        royals: usize_vec(v, "royals")?,
        royals_claimed: i64_at(v, "royals_claimed")? as i32,
    })
}

/// Parse a projection into `(state, seat)` — `seat` being whose view/decision it is.
///
/// Returns `None` on any malformed field rather than panicking: this parses data that
/// crossed the network, and in the browser a panic aborts the worker.
pub fn from_proj(v: &Value) -> Option<(State, usize)> {
    let seat = i64_at(v, "seat")? as usize;
    if seat > 1 {
        return None;
    }

    let cells = i64_vec(v, "board")?;
    if cells.len() != N_CELLS {
        return None;
    }
    let mut board = [EMPTY; N_CELLS];
    for (i, c) in cells.iter().enumerate() {
        // A board cell is EMPTY or a token index: `_do_take` does `tokens[board[cell]]`,
        // so anything else panics rather than merely playing badly.
        if *c < EMPTY as i64 || *c >= N_TOKENS as i64 {
            return None;
        }
        board[i] = *c as i8;
    }

    let deck_lens = usize_vec(v, "deck_lens")?;
    let unseen_v = v.get("unseen")?.as_array()?;
    if deck_lens.len() != 3 || unseen_v.len() != 3 {
        return None;
    }

    let pj = v.get("players")?.as_array()?;
    if pj.len() != 2 {
        return None;
    }
    let mut players: [Player; 2] = [player_from(&pj[0])?, player_from(&pj[1])?];

    // Rebuild the hidden piles from the per-level pools (see the header: these
    // identities are fiction, and determinize replaces them every simulation).
    let mut decks: [Vec<usize>; 3] = [Vec::new(), Vec::new(), Vec::new()];
    for lvl in 0..3 {
        let mut pool: Vec<usize> =
            unseen_v[lvl].as_array()?.iter().filter_map(|x| x.as_u64()).map(|x| x as usize).collect();
        for (s, p) in players.iter_mut().enumerate() {
            // Only the OPPONENT's blind reserves are counted-not-named; the seat's own
            // arrive as real ids in `reserved`/`reserved_from_deck` and are NOT in the pool.
            let n = pj[s].get("reserved_blind")?.as_array()?.get(lvl)?.as_u64()? as usize;
            for _ in 0..n {
                let cid = pool.pop()?;             // off the END; the deck takes the front
                p.reserved.push(cid);              // after the face-ups — `determinize`'s own order
                p.reserved_from_deck.push(cid);
            }
        }
        if pool.len() < deck_lens[lvl] {
            return None;                            // pool smaller than the deck it must supply
        }
        pool.truncate(deck_lens[lvl]);
        decks[lvl] = pool;
    }
    // Every id must name a real card, or LEVEL_OF/COST indexes out of bounds deep in the
    // search. Check once, here, at the trust boundary.
    let known = |c: &usize| *c < LEVEL_OF.len();
    if !decks.iter().flatten().all(known)
        || !players.iter().all(|p| {
            p.reserved.iter().all(known)
                && p.purchased.iter().all(|(c, _)| known(c))
                && p.royals.iter().all(|r| *r < N_ROYALS)
        })
    {
        return None;
    }

    let mut pyramid: [Vec<i32>; 3] = [Vec::new(), Vec::new(), Vec::new()];
    let pyr = v.get("pyramid")?.as_array()?;
    if pyr.len() != 3 {
        return None;
    }
    for lvl in 0..3 {
        pyramid[lvl] = pyr[lvl].as_array()?.iter().filter_map(|x| x.as_i64()).map(|x| x as i32).collect();
        if pyramid[lvl].iter().any(|&c| c >= LEVEL_OF.len() as i32) {
            return None;
        }
    }

    // The pending's cells/colors are indexed DIRECTLY (`board[i]`, `tokens[c]`) by the
    // resolvers, so an out-of-range one panics mid-search rather than playing a bad move.
    let pd = v.get("pending")?;
    let pending = Pending {
        color: i64_at(pd, "color")? as i32,
        cells: usize_vec(pd, "cells")?,
        colors: usize_vec(pd, "colors")?,
        royals: usize_vec(pd, "royals")?,
        excess: i64_at(pd, "excess")? as i32,
        // Log-only in the Python (`engine._log`'s `via=`); no rule reads it, so the
        // projection does not carry it and the search never misses it.
        via: Via::None,
    };
    if pending.cells.iter().any(|&c| c >= N_CELLS)
        || pending.colors.iter().any(|&c| c >= N_TOKENS)
        || pending.royals.iter().any(|&r| r >= N_ROYALS)
        || pending.color >= N_TOKENS as i32
    {
        return None;
    }

    let bag: Vec<u8> = i64_vec(v, "bag")?
        .iter()
        .map(|&t| if (0..N_TOKENS as i64).contains(&t) { Some(t as u8) } else { None })
        .collect::<Option<Vec<u8>>>()?;   // a bag token is dealt onto the board -> same index
    let royals_available = usize_vec(v, "royals")?;
    if royals_available.iter().any(|&r| r >= N_ROYALS) {
        return None;                      // `_claim_royal` indexes ROYAL_PTS/ROYAL_ABILITY
    }
    let win_color = i64_at(v, "win_color")? as i32;
    if win_color >= N_COLORS as i32 {
        return None;
    }
    let st = State {
        phase: if i64_at(v, "phase")? == 0 { PLAYING } else { OVER },
        winner: i64_at(v, "winner")? as i32,
        win_condition: i64_at(v, "win_condition")? as u8,
        win_color,
        turn: i64_at(v, "turn")?.clamp(0, 1) as usize,
        turn_number: i64_at(v, "turn_number")? as i32,
        replenished: i64_at(v, "replenished")? != 0,
        again: i64_at(v, "again")? != 0,
        board,
        bag,
        privileges_board: i64_at(v, "privileges_board")? as i32,
        decks,
        pyramid,
        royals_available,
        players,
        pending_pid: i64_at(v, "pending_pid")? as i32,
        pending_kind: i64_at(v, "pending_kind")? as u8,
        pending,
    };
    if st.pending_kind == PK_NONE && st.pending_pid != -1 {
        return None;                                // a pending with no kind would deadlock the search
    }
    Some((st, seat))
}
