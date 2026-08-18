//! CLASSIC DISSONANCE, WHOLE — the phase machine `games/dissonance/engine.py`
//! runs, ported so a browser can referee its own round with nothing answering.
//!
//! This is the piece the other three offline games already had and this crate
//! deliberately did not: `state.rs` models CARD PLAY, because card play is all
//! the solver ever needed. Everything before trick 1 — the auction, the talon
//! swap, the Double — and the per-seat redaction afterwards lived only in
//! Python, which is fine for a server-refereed room and useless on a plane.
//!
//! ## WHAT IT DOES NOT DO, and that is the important half
//!
//! **It never scores a round.** When the thirteenth trick lands it sets
//! `phase: "over"` and leaves `result: null`; the offline driver prices the
//! round with `games/dissonance/pricing.js` and writes the row back. That is
//! not laziness, it is the `payoff_terms` discipline one rung further out:
//! `pricing.js` is ALREADY the client's one mirror of `_terms_for`/`payoff`,
//! gated against Python by `tests/test_bid_worth.py`. Composing the same
//! formula here would be a THIRD copy of the price list, in the language
//! furthest from the tests, and a wrong number there pays out silently — the
//! worst place to be wrong and the least likely to be noticed. So the rules
//! live here and the prices stay there, each with one owner.
//!
//! **It is CLASSIC ONLY, and says so loudly rather than guessing.** Minor is
//! this machine at a different trick value and would be nearly free; skat is a
//! second auction, a talon that can be declined, a declaration, announcements
//! and Kontra/Re; dummy is three seats, which this crate cannot represent at
//! all (`State.hand` is `[Mask; 2]` — the same reason `client_searchable`
//! already refuses it online). Any other mode is rejected at the door.
//!
//! ## THE SHAPE ON THE WIRE IS THE GAME DICT ITSELF
//!
//! It works on `serde_json::Value` rather than a struct, and that is chosen
//! rather than lazy. The frontend renders `engine.view_for`'s output and the
//! save IS `engine.py`'s game dict, so the JSON shape is the contract — a
//! struct with derived serde would put a second spelling of thirty keys
//! between the port and the thing it has to match, and every mismatch would
//! surface as a board that renders slightly wrong rather than as a type error.
//! Against a `Value` the port reads next to the Python it mirrors, which is
//! what the parity fixtures compare it against. Nothing here is on a hot path:
//! it runs once per move, not once per node.
//!
//! Card COMPARISON is not re-implemented — `state::beats` and `cards::esuit`
//! are the same functions the solver uses, so "what beats what" keeps the one
//! owner it has always had, Grand included.

use crate::cards::{esuit, NOTRUMP};
use crate::rng::Rng;
use crate::state::beats;
use serde_json::{json, Map, Value};

/// The base deck: 32 cards, ids 0..31, `suit * 8 + rank`.
const NCARD: usize = 32;
const IN_HAND: usize = 7;
const NPILES: usize = 3;
const N_OUT: usize = 6;
const N_SHOWN: usize = 3;
const NTRICKS: i64 = 13;
/// `PARITY_MAX_LEVEL` — the product cap on the ladder, not an arithmetic one.
const MAX_LEVEL: i64 = 10;
const MIN_LEVEL: i64 = 1;
/// `NULL_DENOM`, unreachable from the auction since Null became a consolation.
/// Kept because a save written while it was a bid still starts play at no trump.
const NULL_DENOM: i64 = 5;
const VERSION: i64 = 2;
const MATCH_TARGET: i64 = 200;
const EVEN_VALUE: i64 = 2;

type R<T> = Result<T, String>;

fn err<T>(m: &str) -> R<T> {
    Err(m.to_string())
}

// ─── little accessors, so the port reads like the Python it mirrors ─────────

fn geti(g: &Value, k: &str) -> i64 {
    g.get(k).and_then(|v| v.as_i64()).unwrap_or(0)
}
fn getb(g: &Value, k: &str) -> bool {
    g.get(k).and_then(|v| v.as_bool()).unwrap_or(false)
}
fn arr(g: &Value, k: &str) -> Vec<Value> {
    g.get(k).and_then(|v| v.as_array()).cloned().unwrap_or_default()
}
fn ints(v: &Value) -> Vec<i64> {
    v.as_array()
        .map(|a| a.iter().filter_map(|x| x.as_i64()).collect())
        .unwrap_or_default()
}
/// The seat's hand, sorted — hands are kept sorted in the dict, exactly as
/// `engine.py` keeps them, because the board renders them in that order.
fn hand(g: &Value, seat: usize) -> Vec<i64> {
    ints(&g["hands"][seat])
}
fn set_hand(g: &mut Value, seat: usize, mut h: Vec<i64>) {
    h.sort_unstable();
    g["hands"][seat] = json!(h);
}
fn auc(g: &Value) -> &Value {
    &g["auction"]
}
fn auci(g: &Value, k: &str) -> i64 {
    geti(auc(g), k)
}
fn phase(g: &Value) -> String {
    g.get("phase").and_then(|v| v.as_str()).unwrap_or("").to_string()
}

/// Every card the seat could reach, ignoring follow-suit: the hand plus each
/// pile's exposed top. Sorted, like `engine.playable`.
fn playable(g: &Value, seat: usize) -> Vec<i64> {
    let mut out = hand(g, seat);
    out.extend(pile_tops(g, seat));
    out.sort_unstable();
    out
}

fn pile_tops(g: &Value, seat: usize) -> Vec<i64> {
    let mut out = Vec::new();
    if let Some(ps) = g["piles"][seat].as_array() {
        for p in ps {
            let c = ints(p);
            if let Some(&t) = c.last() {
                out.push(t);
            }
        }
    }
    out
}

/// The POSITION whose card comes next. Two-seat: the leader until a card is
/// down, then the other seat. (`to_play` and `playing_seat` are the same
/// number in every two-seat mode — the distinction exists for the dummy.)
fn to_play(g: &Value) -> usize {
    let leader = geti(g, "leader") as usize;
    if g.get("led").map_or(true, |v| v.is_null()) {
        leader
    } else {
        1 - leader
    }
}

// ─── the deal ───────────────────────────────────────────────────────────────

/// Deal a classic round. `match_` carries a running match in; omit it for the
/// first round of a new one.
///
/// The shuffle is this crate's own `Rng` and deliberately does NOT reproduce
/// Python's — the parity gate replays PYTHON-dealt games through this module,
/// so what has to agree is the rules, never the permutation. Tying the two
/// shuffles together would be a second thing to keep in step for no gain.
pub fn new_game(seats: [String; 2], seed: u64, opener: usize, match_: Option<Value>) -> Value {
    let mut rng = Rng::new(seed);
    let mut deck: Vec<i64> = (0..NCARD as i64).collect();
    rng.shuffle(&mut deck);

    let mut hands: Vec<Value> = Vec::new();
    let mut piles: Vec<Value> = Vec::new();
    let mut k = 0usize;
    for _ in 0..2 {
        let mut h: Vec<i64> = deck[k..k + IN_HAND].to_vec();
        h.sort_unstable();
        hands.push(json!(h));
        k += IN_HAND;
        // Each pile is [bottom, top]; only the last element is playable.
        let seat_piles: Vec<Value> = (0..NPILES)
            .map(|i| json!([deck[k + 2 * i], deck[k + 2 * i + 1]]))
            .collect();
        piles.push(json!(seat_piles));
        k += 2 * NPILES;
    }
    let out: Vec<i64> = deck[k..k + N_OUT].to_vec();
    let shown: Vec<i64> = out[..N_SHOWN].to_vec();

    let m = match_.unwrap_or_else(|| {
        json!({
            "target": MATCH_TARGET,
            "scores": [0, 0],
            "round": 1,
            "over": false,
            "first_opener": opener,
        })
    });

    json!({
        "v": VERSION,
        "mode": "classic",
        "seats": [seats[0], seats[1]],
        "phase": "auction",
        "hands": hands,
        "piles": piles,
        "out": out,
        "shown": shown,
        "shown_at_deal": shown,
        "swapped": Value::Null,
        "swap_take": Value::Null,
        "swap_give": Value::Null,
        "opener": opener,
        "auction": {
            "level": 0,
            "denom": -1,
            "declarer": -1,
            "used": [0, 0],
            "last": [-1, -1],
            "to_act": opener,
            "log": [],
            "value": 0,
            "passes": 0,
        },
        "trump": NOTRUMP as i64,
        "trick": 0,
        "leader": opener,
        "led": Value::Null,
        "plays": [],
        "pts": [0, 0],
        "etricks": [0, 0],
        "history": [],
        "played": [],
        "result": Value::Null,
        "doubled": false,
        "match": m,
    })
}

/// Who opens round `m["round"]` — DERIVED from the round number and who opened
/// round 1, never flipped from the last deal. (Classic cannot pass a hand out,
/// so nothing here can fall out of phase today; it is derived anyway because
/// that is what the server does and the two must agree across a save.)
pub fn opener_for_round(m: &Value) -> usize {
    let first = m.get("first_opener").and_then(|v| v.as_i64()).unwrap_or(0);
    let round = m.get("round").and_then(|v| v.as_i64()).unwrap_or(1);
    ((first + round - 1).rem_euclid(2)) as usize
}

// ─── the auction ────────────────────────────────────────────────────────────

/// Every `[level, denom]` this seat may legally name, as an explicit list.
///
/// NOT a levels x denominations cross-product, and the Python says why: under
/// ranked denominations the legal set at the standing level depends on which
/// denomination stands, so a client rebuilding it from two axes gets it wrong.
pub fn auction_bids(g: &Value) -> Vec<[i64; 2]> {
    let mut bids = Vec::new();
    if phase(g) != "auction" {
        return bids;
    }
    let me = auci(g, "to_act") as usize;
    let level = auci(g, "level");
    let denom = auci(g, "denom");
    let used = ints(&auc(g)["used"]);
    // DENOM_RULE is "used" in every shipped mode: the per-player forever-ban.
    let free: Vec<i64> = (0..=(NOTRUMP as i64))
        .filter(|d| (used.get(me).copied().unwrap_or(0) >> d) & 1 == 0)
        .collect();
    if level == 0 {
        // The opener must bid — classic's `OPENER_MAY_PASS` is false.
        for d in &free {
            for lvl in MIN_LEVEL..=MAX_LEVEL {
                bids.push([lvl, *d]);
            }
        }
        return bids;
    }
    // An overtake stands at the SAME level in a higher-ranked denomination, or
    // raises by ANY amount up to the ceiling — classic dropped the raise cap
    // and prices big leaps with the jump bonus instead.
    for d in &free {
        for lvl in level..=MAX_LEVEL {
            if lvl == level && *d <= denom {
                continue; // same level: only a higher-ranked denomination outranks
            }
            bids.push([lvl, *d]);
        }
    }
    bids
}

/// May the seat to act pass? The classic opener may not.
pub fn may_pass(g: &Value) -> bool {
    phase(g) == "auction" && auci(g, "level") != 0
}

fn apply_bid(g: &mut Value, seat: usize, level: i64, denom: i64) -> R<()> {
    if phase(g) != "auction" {
        return err("not bidding");
    }
    if seat as i64 != auci(g, "to_act") {
        return err("not your turn");
    }
    if !auction_bids(g).iter().any(|b| b[0] == level && b[1] == denom) {
        return err("that bid does not outrank the standing contract");
    }
    // How far this bid RAISED the standing level — and THE OPENING BID COUNTS,
    // as a raise over level 0. Real game state, not derived at settle time,
    // because the settled contract's set price reads the FINAL bid's jump.
    let jump = level - auci(g, "level");
    let a = g.get_mut("auction").unwrap();
    a["jump"] = json!(jump);
    a["level"] = json!(level);
    a["denom"] = json!(denom);
    a["declarer"] = json!(seat);
    let used = a["used"][seat].as_i64().unwrap_or(0) | (1 << denom);
    a["used"][seat] = json!(used);
    a["last"][seat] = json!(denom);
    a["to_act"] = json!(1 - seat);
    a["log"].as_array_mut().unwrap().push(json!({
        "seat": seat, "level": level, "denom": denom
    }));
    Ok(())
}

fn apply_pass(g: &mut Value, seat: usize) -> R<()> {
    if phase(g) != "auction" {
        return err("not bidding");
    }
    if seat as i64 != auci(g, "to_act") {
        return err("not your turn");
    }
    if auci(g, "level") == 0 {
        return err("the opener must bid");
    }
    g["auction"]["log"]
        .as_array_mut()
        .unwrap()
        .push(json!({"seat": seat, "pass": true}));
    // The declarer now sees `shown` and decides on the swap before play.
    g["phase"] = json!("swap");
    Ok(())
}

// ─── the talon swap ─────────────────────────────────────────────────────────

fn apply_swap(g: &mut Value, seat: usize, take: Option<i64>, give: Option<i64>) -> R<()> {
    if phase(g) != "swap" {
        return err("not the swap phase");
    }
    let decl = auci(g, "declarer") as usize;
    if seat != decl {
        return err("only the declarer swaps");
    }
    match take {
        None => {
            g["swapped"] = json!(false);
        }
        Some(t) => {
            let give = match give {
                Some(x) => x,
                None => return err("you must discard a card"),
            };
            let shown = ints(&g["shown"]);
            if !shown.contains(&t) {
                return err("that card was not shown");
            }
            let mut h = hand(g, decl);
            if !h.contains(&give) {
                return err("you may only swap a card from your hand");
            }
            h.retain(|&c| c != give);
            h.push(t);
            set_hand(g, decl, h);
            // `shown` MUST follow `out` — it is "the out-of-play cards this
            // seat can place", not a record of what was shown. The searcher
            // does exact card-count arithmetic on it; the historical record is
            // `shown_at_deal`, which the round-end reveal reads instead.
            let mut out = ints(&g["out"]);
            if let Some(i) = out.iter().position(|&c| c == t) {
                out[i] = give;
            }
            g["out"] = json!(out);
            let mut sh = shown;
            if let Some(i) = sh.iter().position(|&c| c == t) {
                sh[i] = give;
            }
            g["shown"] = json!(sh);
            g["swap_take"] = json!(t);
            g["swap_give"] = json!(give);
            g["swapped"] = json!(true);
        }
    }
    // Classic offers the defender the Double here: the contract is settled and
    // the swap is done, so both seats know everything they will know before
    // trick 1.
    g["phase"] = json!("double");
    Ok(())
}

// ─── the Double ─────────────────────────────────────────────────────────────

fn apply_double(g: &mut Value, seat: usize, on: bool) -> R<()> {
    if phase(g) != "double" {
        return err("not the Double phase");
    }
    if seat as i64 == auci(g, "declarer") {
        return err("only the defender may Double");
    }
    g["doubled"] = json!(on);
    start_play(g);
    Ok(())
}

fn start_play(g: &mut Value) {
    let denom = auci(g, "denom");
    g["phase"] = json!("play");
    // `NULL_DENOM` is unreachable from the auction now; the branch survives so
    // a game SAVED before Null stopped being a bid still starts at no trump.
    g["trump"] = json!(if denom == NULL_DENOM { NOTRUMP as i64 } else { denom });
    g["trick"] = json!(0);
    g["led"] = Value::Null;
    g["plays"] = json!([]);
    // THE DECLARER LEADS to trick 1 — measured at +0.93 points, so it is a
    // real part of what the contract is worth.
    g["leader"] = json!(auci(g, "declarer"));
    g["deal"] = deal_snapshot(g);
}

/// The position at the top of trick 1, kept so the round can be REVIEWED.
///
/// `terms` is deliberately absent: this module does not price (see the module
/// note), so the driver fills it from `pricing.js` when it sees a fresh deal.
/// Everything else is here, and it must be SNAPSHOTTED rather than
/// reconstructed — by round end `history` says which card each seat played but
/// never WHERE FROM, so the hand/pile split that defines the position is gone.
fn deal_snapshot(g: &Value) -> Value {
    json!({
        "hands": [hand(g, 0), hand(g, 1)],
        "piles": g["piles"].clone(),
        "out": g["out"].clone(),
        "trump": geti(g, "trump"),
        "leader": geti(g, "leader"),
        "even": EVEN_VALUE,
        "cards": false,
        "head": false,
    })
}

// ─── card play ──────────────────────────────────────────────────────────────

/// The cards `seat` may play right now. Empty unless it is their turn, which
/// is what makes it safe for the view to ship unconditionally.
pub fn legal_moves(g: &Value, seat: usize) -> Vec<i64> {
    if phase(g) != "play" || seat != to_play(g) {
        return Vec::new();
    }
    let cands = playable(g, seat);
    let led = g.get("led").and_then(|v| v.as_i64());
    if let Some(led) = led {
        let trump = geti(g, "trump") as u8;
        let ls = esuit(led as u8, trump);
        let follow: Vec<i64> = cands
            .iter()
            .copied()
            .filter(|&c| esuit(c as u8, trump) == ls)
            .collect();
        // Follow-suit is MANDATORY and a pile's exposed top counts as a card
        // you hold, so the piles can constrain you. (`MUST_HEAD` is off in
        // every shipped mode, so there is no heading filter here — see
        // engine.py if it is ever turned on.)
        if !follow.is_empty() {
            return follow;
        }
    }
    cands
}

/// Take `c` out of the seat's holdings; returns the source (0 = hand,
/// 1..3 = the pile it came off), which is what `history` records.
fn remove_card(g: &mut Value, seat: usize, c: i64) -> R<i64> {
    let mut h = hand(g, seat);
    if let Some(i) = h.iter().position(|&x| x == c) {
        h.remove(i);
        set_hand(g, seat, h);
        return Ok(0);
    }
    let n = g["piles"][seat].as_array().map_or(0, |a| a.len());
    for i in 0..n {
        let p = ints(&g["piles"][seat][i]);
        if p.last() == Some(&c) {
            let mut p2 = p;
            p2.pop();
            g["piles"][seat][i] = json!(p2);
            return Ok(i as i64 + 1);
        }
    }
    err("card not held")
}

fn apply_play(g: &mut Value, seat: usize, c: i64) -> R<()> {
    if !legal_moves(g, seat).contains(&c) {
        return err("illegal card");
    }
    let pos = to_play(g);
    let source = remove_card(g, pos, c)?;
    g["history"]
        .as_array_mut()
        .unwrap()
        .push(json!([pos, c, source]));
    g["played"].as_array_mut().unwrap().push(json!(c));
    g["plays"].as_array_mut().unwrap().push(json!([pos, c]));
    if g["led"].is_null() {
        g["led"] = json!(c);
    }
    let plays: Vec<Vec<i64>> = arr(g, "plays").iter().map(ints).collect();
    if plays.len() < 2 {
        return Ok(());
    }

    // The winner, folded over the trick. `beats` asks "does this card beat
    // that one", so carrying the best card forward is exactly right.
    let trump = geti(g, "trump") as u8;
    let (mut win_pos, mut win_card) = (plays[0][0], plays[0][1]);
    for p in &plays[1..] {
        if beats(win_card as u8, p[1] as u8, trump) {
            win_pos = p[0];
            win_card = p[1];
        }
    }
    let trick = geti(g, "trick");
    // Trick 0 is the FIRST trick and scores -1: the parity is on the ONE-BASED
    // trick number, so an even trick is an odd index. Same arithmetic as
    // `engine.trick_value`, which takes the zero-based index too.
    let v = if trick % 2 == 1 { EVEN_VALUE } else { -1 };
    let winner = win_pos as usize;
    let mut pts = ints(&g["pts"]);
    pts[winner] += v;
    g["pts"] = json!(pts);
    if v > 0 {
        let mut et = ints(&g["etricks"]);
        et[winner] += 1;
        g["etricks"] = json!(et);
    }
    g["trick"] = json!(trick + 1);
    g["leader"] = json!(win_pos);
    g["led"] = Value::Null;
    g["plays"] = json!([]);
    if trick + 1 >= NTRICKS {
        // THE ROUND IS OVER AND THIS MODULE DOES NOT SCORE IT. `result` stays
        // null; the driver prices the row with pricing.js and banks it. See
        // the module note for why the price list is not duplicated here.
        g["phase"] = json!("over");
    }
    Ok(())
}

// ─── the move boundary ──────────────────────────────────────────────────────

/// Apply one move for `pid`, exactly as `engine.apply_move` would.
///
/// Every move is validated against the same legality the room enforces, so a
/// tampered save or a bot answering out of turn is refused rather than
/// applied — the offline driver is the referee and has to behave like one.
pub fn apply_move(g: &mut Value, pid: &str, mv: &Value, seed: u64) -> R<()> {
    if g.get("mode").and_then(|v| v.as_str()) != Some("classic") {
        return err("this engine plays classic rounds only");
    }
    let seats: Vec<String> = arr(g, "seats")
        .iter()
        .map(|s| s.as_str().unwrap_or("").to_string())
        .collect();
    let seat = match seats.iter().position(|s| s == pid) {
        Some(i) => i,
        None => return err("not a seat in this game"),
    };
    // `kind`, the key `engine.apply_move` reads -- the frontend already
    // speaks it, so an offline room takes the same move objects a live one
    // does and nothing in the JSX has to know which referee it is talking to.
    let kind = mv.get("kind").and_then(|v| v.as_str()).unwrap_or("");
    match kind {
        "bid" => {
            let level = mv.get("level").and_then(|v| v.as_i64()).unwrap_or(0);
            let denom = mv.get("denom").and_then(|v| v.as_i64()).unwrap_or(-1);
            apply_bid(g, seat, level, denom)
        }
        "pass" => apply_pass(g, seat),
        "swap" => {
            let take = mv.get("take").and_then(|v| v.as_i64());
            let give = mv.get("give").and_then(|v| v.as_i64());
            apply_swap(g, seat, take, give)
        }
        "double" => {
            let on = mv.get("on").and_then(|v| v.as_bool()).unwrap_or(false);
            apply_double(g, seat, on)
        }
        "play" => {
            let c = match mv.get("card").and_then(|v| v.as_i64()) {
                Some(c) => c,
                None => return err("no card"),
            };
            apply_play(g, seat, c)
        }
        "next_round" => {
            let round_no = mv.get("round").and_then(|v| v.as_i64());
            next_round(g, seat, round_no, seed)
        }
        _ => err("unknown move"),
    }
}

/// Deal the next round of a match that is not decided yet, in place.
///
/// EITHER seat may call it, which is why it carries `round` — the round the
/// caller was LOOKING at when they asked. A stale token no-ops rather than
/// dealing a third round over the top of the second. Offline that is not
/// theoretical: the bot loop and a human click can both arrive at it.
///
/// THE MATCH MUST ALREADY BE BANKED. This module does not score, so the driver
/// has added the finished round's payoff to `match.scores` and set
/// `match.over` before calling — the check below reads what it wrote.
fn next_round(g: &mut Value, seat: usize, round_no: Option<i64>, seed: u64) -> R<()> {
    if seat > 1 {
        return err("not a player in this game");
    }
    let m = match g.get("match").cloned() {
        Some(v) if v.is_object() => v,
        _ => return err("this game is a single round"),
    };
    let round = m.get("round").and_then(|v| v.as_i64()).unwrap_or(1);
    if let Some(r) = round_no {
        if r != round {
            return Ok(()); // already dealt, or a click from long ago
        }
    }
    if phase(g) != "over" {
        return err("the round is still being played");
    }
    if m.get("over").and_then(|v| v.as_bool()).unwrap_or(false) {
        return err("the match is over");
    }
    let mut nxt = m;
    nxt["round"] = json!(round + 1);
    let seats: Vec<String> = arr(g, "seats")
        .iter()
        .map(|s| s.as_str().unwrap_or("").to_string())
        .collect();
    // The SEED comes in with the call rather than being brewed here: the
    // caller owns randomness end to end, which is the same reason
    // `engine.apply_pass` takes an `rng` server-side, and it is what lets a
    // test replay a deal exactly.
    let opener = opener_for_round(&nxt);
    let fresh = new_game([seats[0].clone(), seats[1].clone()], seed, opener, Some(nxt));
    *g = fresh;
    Ok(())
}

/// The seat whose turn it is, or None between rounds and at the end.
pub fn turn_seat(g: &Value) -> Option<usize> {
    match phase(g).as_str() {
        "auction" => Some(auci(g, "to_act") as usize),
        "swap" => Some(auci(g, "declarer") as usize),
        "double" => Some(1 - auci(g, "declarer") as usize),
        "play" => Some(to_play(g)),
        _ => None,
    }
}

// ─── the per-seat view ──────────────────────────────────────────────────────

fn pile_view(g: &Value, owner: usize) -> Value {
    let mut out = Vec::new();
    if let Some(ps) = g["piles"][owner].as_array() {
        for (i, p) in ps.iter().enumerate() {
            let c = ints(p);
            if c.is_empty() {
                out.push(json!({"n": 0, "top": Value::Null, "under": Value::Null}));
                continue;
            }
            let top = *c.last().unwrap();
            // Only the MIDDLE pile's bottom is dealt face up. The outer two are
            // hidden from EVERYONE, the owner included, until the top above
            // them is played.
            let under = if c.len() == 2 && i == 1 {
                json!(c[0])
            } else {
                Value::Null
            };
            out.push(json!({"n": c.len(), "top": top, "under": under}));
        }
    }
    json!(out)
}

/// The round as one seat may see it — the same payload `engine.view_for`
/// builds, because that is what the board renders.
///
/// OFFLINE THE REDACTION IS NOT A SECURITY BOUNDARY and pretending otherwise
/// would be dishonest: the browser holds the whole deal, so a determined
/// player can read the bot's hand out of devtools — exactly as the online Hard
/// tier already documents, since it ships the bot's view to the human's own
/// machine to be searched there. What it IS is the rendering contract: the
/// board draws precisely what this hands it, so a leak here is a leak on
/// screen, which is the thing that would actually spoil a game.
pub fn view_for(g: &Value, seat: usize) -> Value {
    let opp = 1 - seat;
    let over = phase(g) == "over";
    let decl = auci(g, "declarer");
    let ph = phase(g);
    // The shown out-cards belong to the DECLARER's knowledge from the moment
    // the auction settles. "double" is in here with swap and play: by then the
    // declarer has already been shown the talon, and dropping it for one phase
    // would take back information they legitimately hold.
    let sees_shown = over
        || (decl == seat as i64 && (ph == "swap" || ph == "double" || ph == "play"));

    let mut v = Map::new();
    v.insert("mode".into(), json!("classic"));
    v.insert("phase".into(), json!(ph));
    v.insert("seats".into(), g["seats"].clone());
    v.insert("you".into(), json!(seat));
    v.insert("hand".into(), json!(hand(g, seat)));
    v.insert("opp_hand_n".into(), json!(hand(g, opp).len()));
    v.insert("piles".into(), json!([pile_view(g, 0), pile_view(g, 1)]));
    v.insert("dummy".into(), Value::Null);
    v.insert("dummy_seat".into(), Value::Null);
    v.insert(
        "auction".into(),
        json!({
            "level": auci(g, "level"),
            "denom": auci(g, "denom"),
            "declarer": decl,
            "to_act": auci(g, "to_act"),
            "used": auc(g)["used"].clone(),
            "log": auc(g)["log"].clone(),
            "value": auci(g, "value"),
            "jump": auci(g, "jump"),
        }),
    );
    v.insert("contract".into(), Value::Null);
    v.insert("doubled".into(), json!(getb(g, "doubled")));
    v.insert("looked".into(), Value::Null);
    v.insert("redeals".into(), json!(0));
    v.insert("match".into(), g.get("match").cloned().unwrap_or(Value::Null));
    v.insert("opp_hand".into(), Value::Null);
    v.insert("trump".into(), json!(geti(g, "trump")));
    v.insert("trick".into(), json!(geti(g, "trick")));
    v.insert(
        "trick_value".into(),
        json!(if ph == "play" {
            if geti(g, "trick") % 2 == 1 { EVEN_VALUE } else { -1 }
        } else {
            0
        }),
    );
    v.insert("even_val".into(), json!(EVEN_VALUE));
    v.insert("card_pts".into(), json!(false));
    v.insert("card_values".into(), Value::Null);
    v.insert("must_head".into(), json!(false));
    v.insert("must_head_now".into(), json!(false));
    v.insert("leader".into(), json!(geti(g, "leader")));
    v.insert("led".into(), g.get("led").cloned().unwrap_or(Value::Null));
    v.insert("pts".into(), g["pts"].clone());
    v.insert("etricks".into(), g["etricks"].clone());
    v.insert("history".into(), g["history"].clone());
    v.insert("result".into(), g.get("result").cloned().unwrap_or(Value::Null));
    v.insert(
        "out".into(),
        if over { g["out"].clone() } else { Value::Null },
    );
    v.insert(
        "shown".into(),
        if sees_shown { g["shown"].clone() } else { Value::Null },
    );
    v.insert(
        "shown_at_deal".into(),
        if sees_shown {
            g.get("shown_at_deal").cloned().unwrap_or(g["shown"].clone())
        } else {
            Value::Null
        },
    );
    v.insert("swapped".into(), g.get("swapped").cloned().unwrap_or(Value::Null));
    v.insert(
        "swap_take".into(),
        if over { g.get("swap_take").cloned().unwrap_or(Value::Null) } else { Value::Null },
    );
    v.insert(
        "swap_give".into(),
        if over { g.get("swap_give").cloned().unwrap_or(Value::Null) } else { Value::Null },
    );
    let playing = ph == "play";
    v.insert(
        "to_play".into(),
        if playing { json!(to_play(g)) } else { Value::Null },
    );
    v.insert(
        "turn_seat".into(),
        if playing { json!(to_play(g)) } else { Value::Null },
    );
    v.insert("plays".into(), g["plays"].clone());
    v.insert("tricks".into(), json!(NTRICKS));
    v.insert(
        "legal".into(),
        if playing { json!(legal_moves(g, seat)) } else { json!([]) },
    );
    v.insert(
        "options".into(),
        if ph == "auction" {
            let bids: Vec<Value> = auction_bids(g).iter().map(|b| json!([b[0], b[1]])).collect();
            json!({"bids": bids, "may_pass": may_pass(g)})
        } else {
            Value::Null
        },
    );
    v.insert(
        "swap".into(),
        if ph == "swap" && decl == seat as i64 {
            json!({"shown": g["shown"].clone(), "hand": hand(g, seat)})
        } else {
            Value::Null
        },
    );
    v.insert("talon".into(), Value::Null);
    v.insert("declare".into(), Value::Null);
    Value::Object(v)
}
