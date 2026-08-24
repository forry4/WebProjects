//! WASM serving entry — the Hard tier's card play, run in the player's browser.
//!
//! WHY CLIENT-SIDE. The search is an EXACT double-dummy solve per sampled world,
//! and `bin/bench` times one full 13-trick solve at ~74ms on a dev box. Render's
//! free tier is ~0.1 CPU; a server that spent even one world per decision would
//! stall the room, and the shared uvicorn process has four other games on it.
//! The player's own machine has cores nobody else is queueing for, so the same
//! bot — same rules, same solver, same aggregation — simply gets to sample more
//! worlds. Nothing about the STRENGTH KNOB changes shape: PIMC's quality is the
//! world count, and that is the only thing this moves.
//!
//! THE PROTOCOL, and the property that makes pooling sound. The server ships the
//! bot's own `engine.view_for` payload per decision; every worker ingests that
//! same payload, samples its OWN worlds from an independent seed, and returns
//! the per-move value SUM plus how many worlds it summed. The main thread adds
//! the vectors and takes the argmax. Pooling is by root-move INDEX, which is
//! sound because the index space is `State::legal` — a pure function of the
//! position, so every worker and the pick call enumerate the same list in the
//! same order. Sums are additive across disjoint world samples, so the pooled
//! answer is exactly what one worker with the combined `k` would compute.
//!
//! Nothing here is trusted: the card comes back over the same WebSocket a human
//! plays on and `engine.apply_move` validates it against `legal_moves` before it
//! touches the room. A tampered client can only weaken its own opponent.
//!
//! Only the Hard tier is served this way. Easy and Normal are the server's
//! one-trick-deep policy and are deliberately weak; handing them a solver would
//! silently collapse the ladder, which is a strength change, not a serving one.

use wasm_bindgen::prelude::*;

use std::cell::RefCell;

use crate::dd::Dd;
use crate::rng::Rng;
use crate::state::POOL;
use crate::view::View;
use crate::wire::{answer_auction, contract_from_json, deal_from_json, view_from_json};

/// Transposition table size, per worker. 2^18 entries is ~4MB for the plain
/// table plus ~2MB for the contract one — times a pool of at most four workers.
/// `bin/bench` runs 2^20 on a desktop, but a phone is the binding constraint
/// here and the table only has to survive ONE solve to pay for itself.
const TT_BITS: u32 = 18;

thread_local! {
    /// One solver per worker, reused across calls. The table stays warm between
    /// the worlds of a decision, which is most of what it is for.
    static DD: RefCell<Dd> = RefCell::new(Dd::new(TT_BITS));
    /// The last auction solve, keyed on the cards it was about.
    ///
    /// AN AUCTION ASKS THE SAME QUESTION SEVERAL TIMES. A classic auction runs
    /// five or six rounds and a skat ladder more, and the hand does not change
    /// while it does — only the option list does, and pricing options against
    /// solved deals is arithmetic. Without this every round paid the full solve
    /// again, which is where a bid's 7.5-9.2s went. The key is what the seat
    /// HOLDS, so the talon swap invalidates it by construction.
    ///
    /// The entry also remembers WHICH denominations it has solved, and grows.
    /// The set the options span shrinks down a classic auction (5, 5, 4, 4, 3,
    /// 3, 2 — a seat cannot re-bid a denomination it has named), so an entry
    /// identified by that set missed on every round and re-solved denominations
    /// it already held. Every round after the first is now arithmetic.
    // ONE SLOT IS RIGHT HERE and the type still allows more: a worker answers
    // for one seat, so the second slot would never be read. The harnesses that
    // drive BOTH seats through one process take the default 4 — see
    // `bid::SolvedCache`.
    static LAST_BID: RefCell<crate::bid::SolvedCache> =
        RefCell::new(crate::bid::SolvedCache::with_capacity(1));
}

fn err(msg: &str) -> String {
    format!("{{\"error\":\"{}\"}}", msg)
}

/// The armed request: the seat's view, and the scoring rule it is playing for.
/// The payoff half is optional so a caller that has not got it still gets a
/// search -- just one optimising the yardstick instead of the score.
fn parse(view_json: &str)
    -> Option<(View, Option<crate::dd::Contract>, Option<crate::bid::BidPrior>)> {
    let v: serde_json::Value = serde_json::from_str(view_json).ok()?;
    let view = view_from_json(v.get("view").unwrap_or(&v))?;
    let contract = v.get("payoff").and_then(contract_from_json);
    // THE AUCTION AS EVIDENCE, for the card play too. It needs a declarer to be
    // about, which is exactly what a settled contract carries -- so no contract
    // means no prior, and the search samples uniformly as it always did.
    let prior = contract.and_then(|c| {
        v.get("bid_prior").and_then(|p| crate::wire::bid_prior_from_json(p, c.declarer))
    });
    Some((view, contract, prior))
}

/// Solve `k` sampled worlds and return the per-move value sums.
///
/// `view_json` is the armed request: `{"view": ..., "payoff": ...}`. A bare
/// view is accepted too and searched on trick POINTS, which is what this did
/// before the payoff terms existed.
///
/// `{"moves":[card...],"sum":[f64...],"worlds":k}` — `moves` is `State::legal`
/// in its own order and `sum[i]` is the total, over the sampled worlds, of the
/// exact double-dummy value of playing `moves[i]`, signed so that HIGHER is
/// better for the seat to move. Both arrays are additive across workers.
///
/// A position with one legal card returns it with a zero sum and no search: the
/// answer cannot depend on it, and a full solve to learn that is the single
/// most wasteful thing this could do (mandatory follow-suit makes it common).
#[wasm_bindgen]
pub fn odd_pick_card(view_json: &str, k: usize, seed: f64) -> String {
    let (v, contract, prior) = match parse(view_json) {
        Some(x) => x,
        None => return err("not a searchable position"),
    };
    // THE SEARCH ITSELF IS `wire::answer_card`, which `bin/priorlab` also
    // calls. This entry is the wasm boundary and the JSON shape, nothing more —
    // a harness that reproduced the body instead of calling it is a mistake
    // this crate has already made once, with `odd_pick_bid`.
    let mut rng = Rng::new(seed.to_bits() ^ 0x9E37_79B9_7F4A_7C15);
    let (moves, sums, worlds) = DD.with(|dd| {
        let mut dd = dd.borrow_mut();
        crate::wire::answer_card(&v, contract, prior.as_ref(), k, &mut dd, &mut rng)
    });
    if moves.is_empty() {
        return err("no legal move");
    }
    let j = |xs: &[String]| format!("[{}]", xs.join(","));
    let m: Vec<String> = moves.iter().map(|x| x.to_string()).collect();
    let s: Vec<String> = sums.iter().map(|x| x.to_string()).collect();
    format!("{{\"moves\":{},\"sum\":{},\"worlds\":{}}}", j(&m), j(&s), worlds)
}

/// Price every auction option the server offered, over `k` sampled deals.
///
/// `{"sums":[f64...],"worlds":k}`, indexed by the SERVER'S option list — which
/// is the pooling key across workers and the answer the client sends back, so
/// nothing here re-derives it. Signed for the seat being asked, so higher is
/// better for them whether they are the one declaring (a bid, a declaration) or
/// the one deciding whether to double it (Kontra).
///
/// An empty option list is not an error: it is a seat whose only legal action
/// is to pass, and the caller reads that off the same emptiness.
///
/// THE EXPERT TIER RIDES IN ON THE SAME CALL. When the request carries an
/// `auction.search` block, each option is valued by MINIMAX over the auction
/// tree (`auc_search`) instead of by "what does this contract pay me". The
/// protocol does not move at all — same indices, same summing across the pool,
/// same move handed back — so only what the numbers MEAN changes, and a wasm
/// older than the server (or a malformed block) simply prices the Hard way.
#[wasm_bindgen]
pub fn odd_pick_bid(request_json: &str, k: usize, seed: f64) -> String {
    let v: serde_json::Value = match serde_json::from_str(request_json) {
        Ok(v) => v,
        Err(_) => return err("bad request"),
    };
    let mut rng = Rng::new(seed.to_bits() ^ 0x2545_F491_4F6C_DD1D);
    let out = DD.with(|dd| {
        let mut dd = dd.borrow_mut();
        LAST_BID.with(|slot| answer_auction(&v, k, &mut dd, &mut rng, &mut slot.borrow_mut()))
    });
    let (sums, cached) = match out {
        Ok(x) => x,
        Err(e) => return err(e),
    };
    let body = sums.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(",");
    format!("{{\"sums\":[{}],\"worlds\":{},\"cached\":{}}}",
            body, if sums.is_empty() { 0 } else { k.max(1) }, cached)
}

/// THE ROUND REVIEW: what the card play was worth to a perfect declarer.
///
/// `{"deal": {...}, "payoff": {...}}` -> `{"value": i32}`, the exact
/// double-dummy payoff of the round from the START of trick 1, signed for the
/// DECLARER — the same convention `solve_root_contract` uses, and the same one
/// `payoff` itself is written in.
///
/// WHY THIS IS NOT `odd_pick_card` WITH A FULLY-SPECIFIED VIEW. That is the
/// obvious implementation and it cannot work: a view carries a POOL of cards
/// the seat cannot place and the searcher samples worlds from it, so even a
/// payload naming every card gets reshuffled — and the wire's partition check
/// rejects the payload first anyway (see `deal_from_json`). A review has no
/// uncertainty left in it by construction: the round is over and every card has
/// been revealed, so this solves the ONE true deal exactly rather than
/// averaging over sampled ones. It is the cheapest search this crate does for
/// the same reason — one solve, no determinization, no pooling.
///
/// So there is nothing to aggregate and no seed: two callers handed the same
/// deal get the same number, which is what makes it safe to show a player as a
/// fact about their round rather than as a bot's opinion.
#[wasm_bindgen]
pub fn odd_review(request_json: &str) -> String {
    let v: serde_json::Value = match serde_json::from_str(request_json) {
        Ok(v) => v,
        Err(_) => return err("bad request"),
    };
    let deal = match v.get("deal").and_then(deal_from_json) {
        Some(d) => d,
        None => return err("not a complete deal"),
    };
    let contract = match v.get("payoff").and_then(contract_from_json) {
        Some(c) => c,
        None => return err("no contract to price"),
    };
    if contract.declarer > 1 {
        return err("no such declarer");
    }
    let value = DD.with(|dd| {
        let mut dd = dd.borrow_mut();
        // The review is a one-off against a table warmed by whatever the tier
        // was last asked. Those entries are keyed on positions from a DIFFERENT
        // deal, so they are not wrong -- a TT hit is keyed on the position --
        // but they are dead weight competing for slots with this solve. Clear
        // once, up front, rather than fight them for the whole search.
        dd.clear();
        dd.solve_contract(&deal, &contract)
    });
    format!("{{\"value\":{}}}", value)
}

/// The card the pooled sums choose: highest total, ties to the earliest legal
/// move.
///
/// It lives here rather than in the worker's JavaScript so that the tie-break is
/// stated in one place — `PimcBot::pick` keeps the first of equal-valued moves
/// for exactly the same reason a strict `>` does, and a pooled search that broke
/// ties differently would not be the same bot.
#[wasm_bindgen]
pub fn odd_best_card(pooled_json: &str) -> i32 {
    let v: serde_json::Value = match serde_json::from_str(pooled_json) {
        Ok(v) => v,
        Err(_) => return -1,
    };
    let (moves, sums) = match (
        v.get("moves").and_then(|x| x.as_array()),
        v.get("sum").and_then(|x| x.as_array()),
    ) {
        (Some(m), Some(s)) if !m.is_empty() && m.len() == s.len() => (m, s),
        _ => return -1,
    };
    let mut best = 0usize;
    for i in 1..moves.len() {
        if sums[i].as_f64().unwrap_or(f64::MIN) > sums[best].as_f64().unwrap_or(f64::MIN) {
            best = i;
        }
    }
    moves[best].as_i64().unwrap_or(-1) as i32
}

/// The constant-sum pool, so the client can label a value without hardcoding a
/// rule the `odd-positive` feature is allowed to change.
///
/// The CLASSIC pool -- minor mode's is -1, and a client that needs a per-mode
/// pool reads it from the server's `/catalog` (`pools`), which is authoritative
/// the way this constant cannot be.
#[wasm_bindgen]
pub fn odd_pool() -> i32 {
    POOL as i32
}

/// The wire vintage this artifact speaks. 2 = understands `even_val` /
/// `even` (minor mode's runtime trick value, 2026-08-09); 3 = understands
/// `card_pts` / `cards` (skat mode's card scoring, same day); 4 = understands
/// `must_head` / `head` (skat's must-head-the-trick rule, 2026-08-10).
///
/// RUNG 4 IS A LEGALITY RUNG, and that is a harder failure than 2 and 3 were.
/// An artifact that misses a SCORING field returns legal-but-misvalued moves;
/// one that misses this returns moves the room simply refuses, which
/// `_validated_bot_move` drops on the floor -- so the tier answers nothing and
/// the room plays the server bot at full speed while still saying Hard.
///
/// THE WORKER PROBES THIS EXPORT before searching a minor or card-scored
/// payload: an older wasm would silently read the view WITHOUT the field and
/// return legal-but-wrong-game moves with nothing red anywhere -- the exact
/// failure shape the `shown` rewrite already paid for. The probe (absence of
/// the export, or a value below what the payload needs) turns "stale artifact
/// in that room" into the ordinary per-decision fallback to the server bot.
#[wasm_bindgen]
pub fn odd_wire() -> i32 {
    4
}

// ─── THE OFFLINE REFEREE ────────────────────────────────────────────────────
//
// Three exports the search does not use at all: they run a whole CLASSIC round
// in the browser with nothing answering (`games/dissonance/offline.js`). The
// game dict crosses as JSON in both directions and IS `engine.py`'s dict, so a
// saved offline game and a saved online one are the same object — see
// `classic.rs` for why the shape is the contract and why this side never
// scores.
//
// They are ADDITIVE, so an older page loading a newer artifact is unaffected
// and a newer page against an older artifact fails at `undefined is not a
// function` rather than silently: the driver probes for `odd_new_round` before
// offering to deal, which is the same fail-closed shape `odd_wire` gives the
// search path.

/// Deal a classic round. `match_json` carries a running match in (`"null"` for
/// a fresh one); the seed is the caller's, so a test can replay a deal exactly.
#[wasm_bindgen]
pub fn odd_new_round(seats_json: &str, seed: f64, opener: u32, match_json: &str) -> String {
    let seats: Vec<String> = match serde_json::from_str(seats_json) {
        Ok(s) => s,
        Err(e) => return format!(r#"{{"error":"seats: {e}"}}"#),
    };
    if seats.len() != 2 {
        return r#"{"error":"a classic round seats exactly two"}"#.to_string();
    }
    let m: Option<serde_json::Value> = match serde_json::from_str(match_json) {
        Ok(serde_json::Value::Null) | Err(_) => None,
        Ok(v) => Some(v),
    };
    let g = crate::classic::new_game(
        [seats[0].clone(), seats[1].clone()],
        seed as u64,
        (opener % 2) as usize,
        m,
    );
    serde_json::to_string(&g).unwrap_or_else(|e| format!(r#"{{"error":"{e}"}}"#))
}

/// Apply one move. Returns `{"g": <the new game dict>}` or `{"error": "..."}`.
///
/// AN ERROR IS A NORMAL ANSWER, not a crash: the driver is the referee, so an
/// illegal move from a tampered save or a bot answering out of turn has to be
/// REFUSED and reported rather than applied. Same discipline as
/// `_validated_bot_move` server-side.
#[wasm_bindgen]
pub fn odd_apply(game_json: &str, pid: &str, move_json: &str, seed: f64) -> String {
    let mut g: serde_json::Value = match serde_json::from_str(game_json) {
        Ok(v) => v,
        Err(e) => return format!(r#"{{"error":"game: {e}"}}"#),
    };
    let mv: serde_json::Value = match serde_json::from_str(move_json) {
        Ok(v) => v,
        Err(e) => return format!(r#"{{"error":"move: {e}"}}"#),
    };
    match crate::classic::apply_move(&mut g, pid, &mv, seed as u64) {
        Ok(()) => serde_json::json!({ "g": g }).to_string(),
        Err(e) => serde_json::json!({ "error": e }).to_string(),
    }
}

/// The round as one seat may see it — the payload `Dissonance.jsx` renders.
#[wasm_bindgen]
pub fn odd_view(game_json: &str, seat: u32) -> String {
    let g: serde_json::Value = match serde_json::from_str(game_json) {
        Ok(v) => v,
        Err(e) => return format!(r#"{{"error":"game: {e}"}}"#),
    };
    let v = crate::classic::view_for(&g, (seat % 2) as usize);
    serde_json::to_string(&v).unwrap_or_else(|e| format!(r#"{{"error":"{e}"}}"#))
}
