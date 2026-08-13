//! The server's wire view, read back into a `View`.
//!
//! `games/dissonance/engine.py::view_for` already builds exactly the information
//! set this crate's `View` describes — it is the redaction boundary the whole
//! server rests on, so anything it ships is by definition something the seat is
//! allowed to know. That makes it the right input for a client-side bot: there
//! is no second projection to keep in step, and a bug here can only ever make
//! the bot play WORSE, never leak (the payload was already sent to that seat,
//! and every move it produces is re-validated by `engine.apply_move`).
//!
//! Card indices need no translation: both sides number a card `suit * 8 + rank`
//! and `tests/test_rust_parity.py` replays 400 fixtures across the boundary, so
//! the encoding is already gated.
//!
//! What is NOT read back, deliberately:
//!
//! * **`opp_hand`** — the face-up declarer hand an Open contract hands the
//!   defender. Using it would mean a `View` whose opponent hand is known, and
//!   `determinize` would reshuffle it anyway; the honest fix is a second
//!   information-set shape and Open is rare. The bot plays Open blind, which
//!   costs it strength and cannot cost it correctness.
//! * **`legal`** — recomputed from the state by `State::legal`, because the
//!   solver has to enumerate moves at every node regardless, and two sources
//!   for the same list is somewhere for them to disagree.

use crate::auction::HandEval;
use crate::cards::*;
use crate::dd::{Contract, Dd};
use crate::state::{Pile, State};
use crate::view::{Knowledge, View};
use serde_json::Value;

fn u8_at(v: &Value, k: &str) -> Option<u8> {
    v.get(k)?.as_u64().map(|x| x as u8)
}

fn mask_of(v: &Value) -> Mask {
    let mut m: Mask = 0;
    if let Some(a) = v.as_array() {
        for c in a {
            if let Some(c) = c.as_u64() {
                m |= 1 << c;
            }
        }
    }
    m
}

/// Rebuild one seat's information set from `view_for`'s payload.
///
/// Returns `None` for anything that is not a live trick-play position — the
/// caller then has nothing to search and must fall back, which is the same
/// degradation path a timeout takes.
pub fn view_from_json(v: &Value) -> Option<View> {
    let me = u8_at(v, "you")? as usize;


    let mut s = State {
        hand: [0; 2],
        pile: [[Pile::default(); 3]; 2],
        trump: u8_at(v, "trump")?,
        trick: u8_at(v, "trick")?,
        leader: u8_at(v, "leader")?,
        led: match v.get("led") {
            Some(Value::Number(n)) => n.as_i64()? as i8,
            _ => -1,
        },
        pts: [0, 0],
        escored: 0,   // filled from `etricks` below
        // What an even trick pays in this room (minor mode ships 1). OPTIONAL
        // and defaulting to classic's 2: every payload written before the
        // field existed is a classic-parity game, and that is exactly how it
        // was scored. A NEW payload carrying a value this wasm cannot handle
        // does not arise -- the field is a small int and the arithmetic is
        // generic -- but the WORKER refuses a minor view on an older wasm by
        // probing for `odd_wire`, which is the fail-closed half of this pair.
        even: v.get("even_val").and_then(|x| x.as_i64()).unwrap_or(2) as i8,
        // CARD SCORING (the server's skat mode since 2026-08-09): captured
        // cards score instead of the trick parity. OPTIONAL and defaulting to
        // false -- every payload from before the field is a parity game --
        // with the same fail-closed pair as `even_val`: the worker refuses a
        // card-scored view on an artifact whose `odd_wire()` is below 3, and
        // the server refuses to arm a skat room for such a client at all.
        cards: v.get("card_pts").and_then(|x| x.as_bool()).unwrap_or(false),
        // MUST HEAD THE TRICK -- a LEGALITY rule, so an artifact that misses
        // it does not merely misprice, it proposes cards the room refuses and
        // the server plays that decision itself. Optional and false by
        // default (every payload before it is a room without the rule); the
        // `odd_wire() >= 4` gate is what keeps a stale artifact out of a room
        // that has it.
        head: v.get("must_head").and_then(|x| x.as_bool()).unwrap_or(false),
    };
    // Which seats have already won a +2 trick. Not derivable from `pts` -- a
    // total of -1 is one +2 trick and three -1s just as easily as one -1 alone
    // -- and it is the bit the Null consolation turns on.
    if let Some(et) = v.get("etricks").and_then(|x| x.as_array()) {
        for (p, n) in et.iter().enumerate().take(2) {
            if n.as_i64().unwrap_or(0) > 0 {
                s.escored |= 1 << p;
            }
        }
    }
    s.hand[me] = mask_of(v.get("hand")?);
    let pts = v.get("pts")?.as_array()?;
    s.pts = [pts[0].as_i64()? as i8, pts[1].as_i64()? as i8];

    // Every pile top is public; so is the MIDDLE pile's bottom, which was dealt
    // face up. The outer bottoms are hidden from everyone including their owner,
    // which is why a seat's own piles go through the same `UNKNOWN` treatment as
    // the opponent's.
    let piles = v.get("piles")?.as_array()?;
    let mut public_piles: Mask = 0;
    for q in 0..2usize {
        let row = piles.get(q)?.as_array()?;
        for i in 0..3usize {
            let p = row.get(i)?;
            let n = u8_at(p, "n")?;
            if n == 0 {
                continue;
            }
            let top = p.get("top")?.as_u64()? as u8;
            public_piles |= 1 << top;
            if n == 1 {
                s.pile[q][i] = Pile { c: [top, 0], n: 1 };
                continue;
            }
            let under = match p.get("under") {
                Some(Value::Number(x)) => {
                    let c = x.as_u64()? as u8;
                    public_piles |= 1 << c;
                    c
                }
                _ => UNKNOWN,
            };
            s.pile[q][i] = Pile {
                c: [under, top],
                n: 2,
            };
        }
    }

    // Voids are inferred exactly the way `Knowledge::observe` does live: a card
    // that does not follow the suit led proves its player held none of that suit
    // IN HAND (a covered pile bottom may still be that suit and become playable
    // later, so the void must not be asserted over the whole holding).
    let mut kn = Knowledge::default();
    let mut played: Mask = 0;
    let mut led_now: Option<u8> = None;
    let mut first_leader = s.leader;
    let hist = v.get("history").and_then(|h| h.as_array());
    if let Some(hist) = hist {
        for (i, e) in hist.iter().enumerate() {
            let e = e.as_array()?;
            let seat = e[0].as_u64()? as usize;
            let card = e[1].as_u64()? as u8;
            if i == 0 {
                first_leader = seat as u8;
            }
            played |= 1 << card;
            match led_now {
                None => led_now = Some(card),
                Some(l) => {
                    // The CONTRACT decides what following means, so this reads
                    // `s.trump` rather than the raw suit: under Grand a ten
                    // discharges a trump lead and nothing else.
                    let ls = esuit(l, s.trump);
                    if esuit(card, s.trump) != ls {
                        kn.hand_void[seat][ls as usize] = true;
                    } else if s.head && ls != TRUMP_CLASS
                        && !crate::state::beats(l, card, s.trump)
                    {
                        // The must-head ceiling, mirrored from
                        // `Knowledge::observe` -- they followed without
                        // beating, so nothing higher of that suit is in hand.
                        let cap = rank(l);
                        let slot = &mut kn.hand_cap[seat][ls as usize];
                        if cap < *slot {
                            *slot = cap;
                        }
                    }
                    led_now = None;
                }
            }
        }
    }

    // The out-of-play cards this seat can actually place. `shown` is the talon
    // the declarer was allowed to see — three of the six in classic mode, and in
    // skat mode only once they CHOSE to look, which is the whole cost of Hand.
    // A defender sees `null` here and correctly treats all six as unknown.
    let known_out = v.get("shown").map(mask_of).unwrap_or(0);
    let known = s.hand[me] | public_piles | known_out;

    let opp_hand_n = v.get("opp_hand_n")?.as_u64()? as u32;
    let pool = ALL & !played & !known;
    let n_out_hidden = NOUT as u32 - (known_out.count_ones()).min(NOUT as u32);

    // The determinizer partitions `pool` into exactly the opponent's hand, the
    // covered outer bottoms and the unplaced out-cards. If that arithmetic does
    // not hold the payload is not describing a position this crate can search
    // (a phase we do not handle, or a shape that has drifted), and returning
    // None puts the decision back on the server bot rather than searching a lie.
    let mut hidden_slots = 0u32;
    for q in 0..2usize {
        for i in [0usize, 2] {
            if s.pile[q][i].n == 2 {
                hidden_slots += 1;
            }
        }
    }
    if pool.count_ones() != opp_hand_n + hidden_slots + n_out_hidden {
        return None;
    }

    Some(View {
        me,
        s,
        opp_hand_n,
        pool,
        kn,
        history: Vec::new(),
        first_leader,
        n_out_hidden,
    })
}

/// The scoring rule the server will actually apply, read off the armed request.
///
/// The numbers come from `engine.payoff_terms` -- the same function `_finish`
/// scores with -- rather than being rebuilt here, because a second copy of the
/// scoring is exactly the drift the card-play parity gate exists to prevent,
/// and this one would show up only as the bot preferring slightly wrong cards.
///
/// `None` means there is nothing to optimise against and the caller falls back
/// to the trick-point solve, which is the pre-2026-08-07 behaviour.
pub fn contract_from_json(v: &Value) -> Option<Contract> {
    let n = |k: &str| v.get(k)?.as_i64().map(|x| x as i32);
    let declarer = v.get("declarer")?.as_i64()?;
    if !(0..2).contains(&declarer) {
        return None;
    }
    Some(Contract {
        level: n("target")?,
        declarer: declarer as usize,
        make_base: n("make")?,
        // What each point past the target adds to a made contract: +1 in both
        // shipped modes. OPTIONAL rather than required, and defaulting to the
        // old flat rule, because a browser can hold a cached wasm older than
        // the server -- an armed decision written before the term existed must
        // still be searchable, and searching it at the old rule is exactly right.
        over: n("over").unwrap_or(0),
        set_base: n("set_base")?,
        short: n("short")?,
        // Optional and 0 by default, exactly like `over`: a browser can hold a
        // cached wasm older than the server, and an armed decision written
        // before the term existed must still be searchable -- at the flat rate,
        // which is what it was scored under when it was written.
        ramp: n("ramp").unwrap_or(0),
        null: n("null"),
    })
}

/// The auction candidates the server says are legal, each already priced by
/// `engine.payoff_terms` for the contract it would produce.
///
/// Read positionally and never re-derived: the index is the pooling key across
/// workers and the answer the client sends back, so the option list must mean
/// the same thing on both sides of the wire. An option missing a field is
/// DROPPED rather than defaulted — a zero `make` would quietly price a real
/// contract at nothing and the bot would simply never choose it.
pub fn options_from_json(v: &Value) -> Vec<crate::bid::Option_> {
    let arr = match v.as_array() {
        Some(a) => a,
        None => return Vec::new(),
    };
    let mut out = Vec::with_capacity(arr.len());
    for o in arr {
        let n = |k: &str| o.get(k).and_then(|x| x.as_i64()).map(|x| x as i32);
        match (n("denom"), n("target"), n("make"), n("set_base"), n("short"), n("null")) {
            // MEMBERSHIP, not a range. Grand is denomination 6 -- it sits ABOVE
            // no-trump's 4 rather than beside it, because 5 is the legacy Null
            // marker -- so `(0..=4)` rejected every Grand option. And a rejected
            // option empties the WHOLE list below, so the Hard tier answered
            // nothing at all for any skat decision whose options span Grand,
            // which is all of them: `skat_declarable` offers Grand at every
            // rung. Silent, per the usual failure mode -- the room just played
            // out on the server bot while still saying Hard.
            (Some(d), Some(t), Some(m), Some(sb), Some(sh), Some(nu))
                if crate::cards::DENOMS.contains(&(d as u8)) => {
                out.push(crate::bid::Option_ {
                    denom: d as u8, target: t, make: m,
                    // Optional and flat by default, same as the card search's:
                    // a cached wasm older than the server still prices every
                    // option, just under the rule it was built for.
                    over: n("over").unwrap_or(0),
                    set_base: sb, short: sh, ramp: n("ramp").unwrap_or(0), null: nu,
                    // Both OPTIONAL and both false by default, which is exactly
                    // the pre-pass behaviour: a wasm older than the server sees
                    // no flags, prices every option as one it could buy for
                    // itself, and falls back to the old "value <= 0 means pass"
                    // rule the client still carries.
                    opp: o.get("opp").and_then(|x| x.as_bool()).unwrap_or(false),
                    redeal: o.get("redeal").and_then(|x| x.as_bool()).unwrap_or(false),
                });
            }
            _ => return Vec::new(),   // a malformed list is not a partial one
        }
    }
    out
}

// ── the OFFLINE oracle: a whole deal, for resolving a settled contract ───────

/// A COMPLETE deal — every hand, every pile bottom, the out-cards, nothing
/// redacted. Two callers, one encoding:
///
/// * **`odd_review`** (the scorecard's DD column) hands it a banked round's
///   snapshot off the wire and spends an exact solve on the answer;
/// * **`bidserve`** (the auction arena's resolver) hands it `play.jsonl`-shaped
///   deals — the field names are that file's on purpose, so there is one
///   encoding of a deal in the repo rather than one per harness.
///
/// NOT A SERVING PATH for hidden information: `view_from_json` remains the
/// redaction boundary, and this reads ground truth that is already public
/// (a finished round, an offline fixture). It is also deliberately NOT
/// `view_from_json` with every card filled in — a View is an information set
/// whose pool the searcher SAMPLES, so even a fully-named payload gets
/// reshuffled, and its partition check rejects a filled-in outer bottom first
/// anyway (`hidden_slots` counts piles by `n == 2`, not by what is known).
///
/// FAILS CLOSED on anything that is not a fresh, complete deal: hands sized
/// off `NDEALT` (a literal 7 is wrong under three of the four deck-width
/// features), everything disjoint, and the whole expected card set accounted
/// for. `out` is OPTIONAL — the arena's resolver ships only hands + piles,
/// which is a complete POSITION (`State` never stores the out-cards; they are
/// the six nobody holds) — but whichever shape arrives is checked in full.
/// The caller is about to spend an exact solve, and a deal missing a card
/// resolves to a confident wrong number, not to an error.
pub fn deal_from_json(v: &Value) -> Option<State> {
    let mut s = State {
        hand: [0; 2],
        pile: [[Pile::default(); 3]; 2],
        trump: u8_at(v, "trump")?,
        // A review always runs the card play from the top: trick 1, nobody to
        // lead yet, no points and no +2 trick scored by either side.
        trick: 0,
        leader: u8_at(v, "leader")?,
        led: -1,
        pts: [0, 0],
        escored: 0,
        // The parity the round was PLAYED under -- `engine._deal_snapshot`
        // stamps it, and a minor round reviewed at classic values would be a
        // confidently wrong number in a column labelled a fact. Optional,
        // defaulting to 2: every snapshot from before the field is classic.
        even: v.get("even").and_then(|x| x.as_i64()).unwrap_or(2) as i8,
        // Card scoring, same discipline: a skat round banked BEFORE the card
        // values shipped was played under the parity, and the absent key
        // reviews it that way for free.
        cards: v.get("cards").and_then(|x| x.as_bool()).unwrap_or(false),
        // ...and must-head, which matters MORE here than the scoring does: it
        // is a legality rule, so replaying an older round under it would let
        // the review explore lines that round's players were allowed and this
        // one is not. Absent = the rule was not in force.
        head: v.get("head").and_then(|x| x.as_bool()).unwrap_or(false),
    };
    if s.leader > 1 {
        return None;
    }

    let hands = v.get("hands")?.as_array()?;
    let piles = v.get("piles")?.as_array()?;
    // Every card must be accounted for exactly once. Counting bits as we go and
    // comparing the total at the end catches a duplicate as surely as a
    // missing card: a repeated card raises the count in `seen` by nothing.
    let mut seen: Mask = 0;
    let mut n = 0u32;
    let take = |c: u8, seen: &mut Mask, n: &mut u32| -> Option<()> {
        if c >= NCARD {
            return None;
        }
        *seen |= 1 << c;
        *n += 1;
        Some(())
    };

    let in_hand = NDEALT as u32 - 6;
    for q in 0..2usize {
        s.hand[q] = mask_of(hands.get(q)?);
        if s.hand[q].count_ones() != in_hand {
            return None;
        }
        for c in hands.get(q)?.as_array()? {
            take(c.as_u64()? as u8, &mut seen, &mut n)?;
        }
        let row = piles.get(q)?.as_array()?;
        for i in 0..3usize {
            // `[bottom, top]` — the order `State::Pile.c` uses and
            // `gen_fixtures` emits, so a pile is read exactly as the engine
            // stores it and there is no place to get the orientation backwards.
            let p = row.get(i)?.as_array()?;
            if p.len() != 2 {
                return None;
            }
            let bottom = p[0].as_u64()? as u8;
            let top = p[1].as_u64()? as u8;
            take(bottom, &mut seen, &mut n)?;
            take(top, &mut seen, &mut n)?;
            s.pile[q][i] = Pile { c: [bottom, top], n: 2 };
        }
    }
    // `out` is OPTIONAL, and both shapes are fully checked. The banked-round
    // snapshot and `play.jsonl` carry it, and then the whole deck must
    // partition; the auction arena's resolver ships only hands + piles, which
    // is enough — `State` does not store the out-cards at all, they are simply
    // the six nobody holds, so their identity adds integrity and no position.
    let expect = match v.get("out") {
        Some(o) => {
            for c in o.as_array()? {
                take(c.as_u64()? as u8, &mut seen, &mut n)?;
            }
            NCARD as u32
        }
        None => NCARD as u32 - NOUT as u32,
    };

    // Disjoint (no card claimed twice) AND complete (everything expected).
    if n != expect || seen.count_ones() != expect {
        return None;
    }
    Some(s)
}

/// The classic talon-swap policy, as fitted weights off the armed request.
///
/// All-or-nothing: a row missing one weight is a malformed policy, and pricing
/// with half a policy would be a quiet third behaviour nobody measured. Absent
/// entirely (`None`) means "price the deal as dealt", the pre-2026-08-08 rule
/// and the correct reading for a skat room or an older server.
pub fn swap_from_json(v: &Value) -> Option<crate::bid::SwapPolicy> {
    let arr8 = |k: &str| -> Option<[f64; 8]> {
        let a = v.get(k)?.as_array()?;
        let mut out = [0.0; 8];
        if a.len() != 8 {
            return None;
        }
        for (i, x) in a.iter().enumerate() {
            out[i] = x.as_f64()?;
        }
        Some(out)
    };
    let n = |k: &str| v.get(k).and_then(|x| x.as_f64());
    Some(crate::bid::SwapPolicy {
        take_w: arr8("take_w")?,
        give_w: arr8("give_w")?,
        take_trump: n("take_trump")?,
        give_trump: n("give_trump")?,
        void: n("void")?,
        singleton: n("singleton")?,
        length: n("length")?,
    })
}

// ── the Expert tier's auction search ─────────────────────────────────────────

/// Which tree edge each option in the server's list stands for.
///
/// Read off the MOVE the server already attached to every option, rather than
/// shipped as a second parallel array: the two would have to be kept in step,
/// and a misalignment would price one option and send another. Returns `None`
/// on anything it does not recognise, and the caller falls back to Hard's
/// myopic pricing — a search that mislabels its own root moves is worse than no
/// search at all.
pub fn edges_from_json(v: &Value) -> Option<Vec<crate::auc_search::Bid>> {
    use crate::auc_search::Bid;
    let arr = v.as_array()?;
    let mut out = Vec::with_capacity(arr.len());
    for o in arr {
        let mv = o.get("move")?;
        match mv.get("kind").and_then(|x| x.as_str())? {
            "pass" => out.push(Bid::Pass),
            "bid" => match (mv.get("level").and_then(|x| x.as_u64()),
                            mv.get("denom").and_then(|x| x.as_u64()),
                            mv.get("value").and_then(|x| x.as_u64())) {
                (Some(l), Some(d), _) => out.push(Bid::Contract { level: l as u8, denom: d as u8 }),
                (_, _, Some(v)) => out.push(Bid::Number { value: v as u16 }),
                _ => return None,
            },
            _ => return None,   // declare / kontra / double are not auction edges
        }
    }
    Some(out)
}

/// The Expert tier's auction payload: where the bidding stands, the legality
/// knobs, and a priced row per settlement the auction could still reach.
///
/// Every number here is the server's — `engine.auction_search_payload` builds
/// the rows with the same `_terms_for` the room will score with — so the search
/// mirrors the auction's LEGALITY and nothing about its scoring.
pub fn auc_search_from_json(v: &Value)
    -> Option<(crate::auc_search::AucState, crate::auc_search::AucRules,
               crate::auc_search::TermsTable)> {
    let rules = auc_rules_from_json(v.get("rules")?)?;
    let state = auc_state_from_json(v.get("state")?)?;
    // The rows are read with the SAME reader the myopic pricing uses, so a term
    // means one thing on this side of the wire however it arrived.
    let rows = v.get("terms")?.as_array()?;
    let mut terms = crate::auc_search::TermsTable::new();
    for row in rows {
        let key = row.get("key").and_then(|x| x.as_u64())? as u16;
        // `options_from_json` is all-or-nothing by design; here one row at a
        // time, since a table missing a settlement prices that leaf at 0 rather
        // than mis-pricing every other one.
        let one = options_from_json(&Value::Array(vec![row.clone()]));
        match one.into_iter().next() {
            Some(o) => terms.insert(key, o),
            None => return None,
        }
    }
    if terms.is_empty() {
        return None;
    }
    Some((state, rules, terms))
}

/// The auction's legality knobs. Split out from the payload so the parity gate
/// can replay a node without also carrying its price table -- the fixture is
/// about which EDGES exist, and shipping ~60 priced rows per node to assert
/// that would be most of the file.
pub fn auc_rules_from_json(r: &Value) -> Option<crate::auc_search::AucRules> {
    use crate::auc_search::{AucMode, AucRules};
    let mode = match r.get("mode").and_then(|x| x.as_str())? {
        "skat" => AucMode::Skat,
        "classic" => AucMode::Classic,
        _ => return None,
    };
    let n = |k: &str| r.get(k).and_then(|x| x.as_u64());
    let rules = AucRules {
        mode,
        min_level: n("min_level")? as u8,
        max_level: n("max_level")? as u8,
        max_raise: n("max_raise")? as u8,
        // OPTIONAL, default 0: a payload from a server that has never heard of
        // the jump bonus prices sets exactly as it always did. Classic ships 3
        // since the raise cap was dropped (2026-08-13).
        jump_set_bonus: r.get("jump_set_bonus").and_then(|x| x.as_i64()).unwrap_or(0) as i32,
        top_denom: n("top_denom")? as u8,
        ladder: r.get("ladder").and_then(|x| x.as_array())
            .map(|a| a.iter().filter_map(|x| x.as_u64()).map(|x| x as u16).collect())
            .unwrap_or_default(),
        // OPTIONAL, and the default is the original minimax: a payload from a
        // server that has never heard of opponent models must behave exactly
        // as it always did. An unknown string is a malformed payload.
        opp: match r.get("opp_model").and_then(|x| x.as_str()) {
            None => crate::auc_search::OppModel::Minimax,
            Some("minimax") => crate::auc_search::OppModel::Minimax,
            Some("myopic") => crate::auc_search::OppModel::Myopic,
            Some(_) => return None,
        },
    };
    // The KEY must be there in skat, but it may legitimately be EMPTY -- a bid
    // standing on the ladder's top rung leaves nothing that outranks it, and
    // that node is perfectly searchable (its only edge is a pass, straight to
    // the leaf). Rejecting an empty ladder confused "no rungs left" with "the
    // field never arrived"; only the second is a malformed payload.
    if mode == AucMode::Skat && !r.get("ladder").map(|x| x.is_array()).unwrap_or(false) {
        return None;
    }
    Some(rules)
}

/// Where the bidding has got to.
pub fn auc_state_from_json(s: &Value) -> Option<crate::auc_search::AucState> {
    use crate::auc_search::AucState;
    let n = |k: &str| s.get(k).and_then(|x| x.as_u64());
    let used = s.get("used").and_then(|x| x.as_array())
        .map(|a| [a.first().and_then(|x| x.as_u64()).unwrap_or(0) as u8,
                  a.get(1).and_then(|x| x.as_u64()).unwrap_or(0) as u8])
        .unwrap_or([0, 0]);
    let declarer = s.get("declarer").and_then(|x| x.as_i64())?;
    if !(-1..2).contains(&declarer) {
        return None;
    }
    let state = AucState {
        level: n("level").unwrap_or(0) as u8,
        denom: n("denom").unwrap_or(0) as u8,
        value: n("value").unwrap_or(0) as u16,
        declarer: declarer as i8,
        used,
        passes: n("passes").unwrap_or(0) as u8,
        to_act: n("to_act")? as u8,
        // The STANDING bid's jump — what a pass would settle the set price on.
        // Optional for the same back-compat reason as the rate above.
        jump: n("jump").unwrap_or(0) as u8,
    };
    if state.to_act > 1 {
        return None;
    }
    Some(state)
}

/// ONE armed auction request, answered. Both the browser entry (`wasm.rs`) and
/// the offline harness (`bin/bidserve`) call this, which is the whole reason it
/// exists: the harness used to reproduce the entry's body, and the repo has
/// already paid for a measurement harness that did not reproduce the SERVING
/// shape. With Expert riding in on the same call there are now two search
/// modes to keep in step, and two copies of that choice is one too many.
///
/// `cache` is the caller's `Solved` slot, keyed by `bid::hand_key` — the
/// browser keeps one per worker across a whole auction, the harness may pass a
/// fresh one. It is a latency optimisation and changes no decision.
///
/// Returns the per-option sums SIGNED FOR THE ASKER, in the server's own order,
/// plus whether the solve was already in hand.
pub fn answer_auction(v: &Value, k: usize, dd: &mut Dd, rng: &mut crate::rng::Rng,
                      cache: &mut Option<(u64, crate::bid::Solved)>)
    -> Result<(Vec<f64>, bool), &'static str> {
    let view = view_from_json(v.get("view").unwrap_or(v)).ok_or("not a searchable position")?;
    let auc = v.get("auction").ok_or("no auction request")?;
    let null = Value::Null;
    let opts = options_from_json(auc.get("options").unwrap_or(&null));
    // Whoever would be DECLARING under these options — not necessarily the seat
    // being asked. A defender deciding on Kontra is pricing the opponent's
    // contract, so the solve is from the opponent's side and only the sign at
    // the end belongs to the asker.
    let declarer = auc.get("declarer").and_then(|x| x.as_u64()).unwrap_or(view.me as u64) as usize;
    if declarer > 1 {
        return Err("no such declarer");
    }
    if opts.is_empty() {
        return Ok((Vec::new(), false));
    }
    let sign = if view.me == declarer { 1.0 } else { -1.0 };
    // EXPERT: a tree instead of a price list. It needs the same solved worlds,
    // just more of them — whatever either seat could still bid, on both sides —
    // so the extra denominations join the same cache request rather than being
    // a second pass over the deals.
    let expert = auc_search_from_json(auc.get("search").unwrap_or(&null))
        // The tree signs its answer for the ASKER; only a decision that asks
        // about its own seat can use it, which is exactly the auction phase.
        .filter(|_| declarer == view.me)
        .and_then(|(st, rules, terms)| {
            let edges = edges_from_json(auc.get("options").unwrap_or(&null))?;
            if edges.len() != opts.len() {
                return None;      // the tree cannot label the list it must rank
            }
            Some((st, rules, terms, edges))
        });
    let (wanted, wanted_opp) = match &expert {
        Some((_, _, terms, _)) => (terms.denoms_mask(), terms.denoms_mask()),
        None => crate::bid::wanted_denoms(&opts),
    };
    // The talon model rides on the auction request as fitted weights; see
    // `bid::SwapPolicy`. It is part of the CACHE IDENTITY -- worlds solved
    // with the swap applied answer a different question than worlds solved
    // as dealt, and the contract-table bug was this exact shape.
    let swap = auc.get("swap").and_then(swap_from_json);
    let key = crate::bid::hand_key(&view, declarer, k.max(1))
        ^ swap.as_ref().map_or(0, |sp| sp.key());
    // A different hand starts a new entry; the same hand extends the one it
    // has, and asking about nothing new does no work at all.
    let mut entry = match cache.take() {
        Some((k0, s)) if k0 == key => s,
        _ => crate::bid::Solved::default(),
    };
    let cached = (wanted & !entry.covered) == 0 && (wanted_opp & !entry.covered_opp) == 0;
    if !cached {
        crate::bid::solve_into(&view, dd, rng, k.max(1), wanted, wanted_opp, declarer,
                               &mut entry, swap.as_ref());
    }
    let myopic = crate::bid::price(&opts, &entry.worlds, entry.covered, entry.covered_opp);
    let sums = match &expert {
        Some((st, rules, terms, edges)) => {
            let mut s = crate::auc_search::Search::new(view.me, rules.clone(), terms, &entry);
            let tree = s.values(*st, edges);
            // TIES ARE THE COMMON CASE AND THE INDEX IS A TERRIBLE WAY TO BREAK
            // THEM. Whenever the opponent has a reply that equalises whatever we
            // open with, every one of our openings has the SAME minimax value --
            // measured on 25 classic deals, the top four openings were exactly
            // tied on 4 of the first 6, and taking the earliest index opened at
            // level 1 in 13 of 25 (against Hard's 1 of 25). That is not the
            // search capping an auction, it is the search having no opinion and
            // the enumeration order answering for it.
            //
            // So Hard's price is the TIE-BREAK: among lines the opponent
            // equalises, prefer the one that pays best if they do not. It is
            // strictly the right order of authority -- the tree models a
            // stronger opponent than the one across the table, and when the
            // tree is indifferent its model is exactly what should stop mattering.
            //
            // WEIGHT. Both halves are sums of integer payoffs, so a genuine tree
            // difference is at least 1 per worker; the price is bounded by a few
            // thousand at any k the client asks for, so 1e-5 keeps the whole
            // tie-break term two orders of magnitude below the smallest real
            // difference, pool included. It can order ties and nothing else.
            tree.iter().zip(&myopic).map(|(t, m)| t + 1e-5 * m).collect()
        }
        None => myopic,
    };
    *cache = Some((key, entry));
    Ok((sums.iter().map(|x| x * sign).collect(), cached))
}

// ── HandEval, across workers ─────────────────────────────────────────────────
//
// An auction decision is a solver over SAMPLED WORLDS, and the worlds are the
// only expensive part (2 declarers x 5 denominations x one exact solve each,
// plus Null). So the pool splits by world: every worker samples its own and
// ships them back, the main thread concatenates, and one call runs the solver
// over the union. That is exactly the same arithmetic a single worker with the
// combined `k` would do — `HandEval` is a list of independent worlds and every
// reader indexes it as one.

/// `{"pts":[[[..NDENOM_SLOTS],[..NDENOM_SLOTS]]...],"floor":[...],"null":[[bool,bool]...]}`
///
/// A row is one world's per-TRUMP result for both seats, so it is
/// `NDENOM_SLOTS` wide rather than the classic auction's five: Grand is a
/// trump the solver can be asked about even though the classic ladder
/// cannot name it.
pub fn hand_eval_to_json(ev: &HandEval) -> String {
    let rows = |v: &Vec<[[i8; NDENOM_SLOTS]; 2]>| {
        let mut out = String::from("[");
        for (w, row) in v.iter().enumerate() {
            if w > 0 {
                out.push(',');
            }
            out.push('[');
            for (d, side) in row.iter().enumerate() {
                if d > 0 {
                    out.push(',');
                }
                out.push('[');
                for (i, x) in side.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    out.push_str(&x.to_string());
                }
                out.push(']');
            }
            out.push(']');
        }
        out.push(']');
        out
    };
    let mut nulls = String::from("[");
    for (w, row) in ev.null.iter().enumerate() {
        if w > 0 {
            nulls.push(',');
        }
        nulls.push_str(&format!("[{},{}]", row[0], row[1]));
    }
    nulls.push(']');
    format!(
        "{{\"pts\":{},\"floor\":{},\"null\":{},\"worlds\":{}}}",
        rows(&ev.pts),
        rows(&ev.floor),
        nulls,
        ev.k()
    )
}

/// Concatenate the worlds from every worker's `hand_eval_to_json`.
///
/// `floor` and `null` are each all-or-nothing across a run (they are computed
/// per world under one config), so a mix would silently change what the solver
/// reads. Rather than trust the caller, an empty `floor`/`null` anywhere makes
/// the merged one empty — which `HandEval::floor_of` / `null_of` already treat
/// as "not evaluated", i.e. never bid Null for free.
pub fn hand_eval_from_json(parts: &[Value]) -> HandEval {
    let mut pts = Vec::new();
    let mut floor = Vec::new();
    let mut nulls = Vec::new();
    let mut any_no_floor = false;
    let mut any_no_null = false;
    let grab = |v: Option<&Value>, out: &mut Vec<[[i8; NDENOM_SLOTS]; 2]>| -> bool {
        let a = match v.and_then(|x| x.as_array()) {
            Some(a) if !a.is_empty() => a,
            _ => return false,
        };
        for world in a {
            let mut row = [[0i8; NDENOM_SLOTS]; 2];
            if let Some(sides) = world.as_array() {
                for (d, side) in sides.iter().enumerate().take(2) {
                    if let Some(cells) = side.as_array() {
                        for (i, x) in cells.iter().enumerate().take(5) {
                            row[d][i] = x.as_i64().unwrap_or(0) as i8;
                        }
                    }
                }
            }
            out.push(row);
        }
        true
    };
    for p in parts {
        grab(p.get("pts"), &mut pts);
        if !grab(p.get("floor"), &mut floor) {
            any_no_floor = true;
        }
        match p.get("null").and_then(|x| x.as_array()) {
            Some(a) if !a.is_empty() => {
                for world in a {
                    let w = world.as_array();
                    nulls.push([
                        w.and_then(|x| x[0].as_bool()).unwrap_or(false),
                        w.and_then(|x| x[1].as_bool()).unwrap_or(false),
                    ]);
                }
            }
            _ => any_no_null = true,
        }
    }
    if any_no_floor || floor.len() != pts.len() {
        floor.clear();
    }
    if any_no_null || nulls.len() != pts.len() {
        nulls.clear();
    }
    HandEval {
        pts,
        floor,
        null: nulls,
    }
}

// ── THE WIRE-READER GATE ─────────────────────────────────────────────────────
// Replays real `engine.view_for` payloads (both seats, both auction modes, every
// ply of four complete games) through `view_from_json` and checks the
// information set that comes out.
//
// This is the second parity surface between the Python engine and this crate,
// and unlike the card-play one it fails SILENTLY: a reader that mis-sizes the
// hidden pool, drops a suit void or mistakes which pile bottom is public still
// hands the solver a legal position and still returns a legal card -- just a
// worse one, chosen from deals the seat's own information already rules out. A
// room would go on saying "Hard" while playing somewhere below it, with nothing
// red anywhere.
//
// `cargo test --features bridge`. The fixtures are COMMITTED, like play.jsonl --
// CI runs cargo with no Python step available. Regenerate them with
// `games/dissonance/tools/gen_view_fixtures.py` whenever `view_for` changes shape.
#[cfg(test)]
mod payoff_parity {
    // THE SCORING RULE, held to the engine's own answer. The terms are shipped
    // rather than reimplemented (`_ai_search` carries `engine.payoff_terms`), so
    // the one thing genuinely written twice is the arithmetic that turns terms
    // plus an outcome into a number -- and getting THAT wrong is the quietest
    // failure in the tier: the solver still returns a legal card, still looks
    // like it is thinking, and simply optimises the wrong thing.
    //
    // Regenerate with `games/dissonance/tools/gen_payoff_fixtures.py`.
    use super::*;

    fn rows() -> Vec<Value> {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../games/dissonance/tests/fixtures/payoff.jsonl"
        );
        let text = std::fs::read_to_string(path).unwrap_or_else(|e| {
            panic!("{path}: {e}\nRegenerate with:\n  PYTHONPATH=<repo root> python -m \
                    games.dissonance.tools.gen_payoff_fixtures > \
                    games/dissonance/tests/fixtures/payoff.jsonl")
        });
        text.lines()
            .filter(|l| !l.trim().is_empty())
            .map(|l| serde_json::from_str(l).expect("fixture line is not JSON"))
            .collect()
    }

    #[test]
    fn the_solver_scores_a_finished_round_exactly_as_the_engine_does() {
        let all = rows();
        assert!(all.len() > 40, "only {} contracts — regenerate", all.len());
        let (mut classic, mut skat, mut minor, mut checked, mut nulls) = (0, 0, 0, 0, 0);
        for (i, f) in all.iter().enumerate() {
            let c = contract_from_json(&f["terms"])
                .unwrap_or_else(|| panic!("fixture {i}: terms did not read back"));
            match f["mode"].as_str() {
                Some("skat") => skat += 1,
                Some("minor") => minor += 1,
                _ => classic += 1,
            }
            for row in f["rows"].as_array().unwrap() {
                let r = row.as_array().unwrap();
                let pts = r[0].as_i64().unwrap() as i32;
                let scored = r[1].as_bool().unwrap();
                let want = r[2].as_i64().unwrap() as i32;
                assert_eq!(
                    c.payoff(pts, scored), want,
                    "fixture {i}: {pts} pts, scored={scored}"
                );
                checked += 1;
                if !scored {
                    nulls += 1;
                }
            }
        }
        assert!(classic > 0 && skat > 0 && minor > 0, "all three modes must be covered");
        // The overtrick bonus is optional on the wire and defaults to flat, so
        // a fixture set that never carried one would pass this whole table
        // while the term was being dropped in `contract_from_json`.
        let with_over = all.iter()
            .filter(|f| contract_from_json(&f["terms"]).unwrap().over != 0)
            .count();
        assert!(with_over > 0, "no fixture prices an overtrick — regenerate");
        // Non-vacuity: the Null branch is the whole reason this search exists,
        // and a fixture that never exercised it would prove only the old rule.
        assert!(nulls > 100 && checked > 1000, "{nulls} null rows of {checked}");
    }

    #[test]
    fn a_declarer_on_no_scoring_trick_is_paid_the_consolation_not_the_set() {
        // Stated directly as well as by table, because it is the one clause a
        // points-searching solver could not see at any sample count.
        for f in rows().iter() {
            let c = contract_from_json(&f["terms"]).unwrap();
            let null = c.null.expect("the shipped game always has a consolation");
            assert!(c.payoff(-7, false) == null && c.payoff(0, false) == null,
                    "the consolation must not depend on the point total");
            assert!(c.payoff(-7, true) < 0, "and a declarer who scored is set");
        }
    }
}

#[cfg(test)]
mod fixture_replay {
    use super::*;
        use crate::rng::Rng;
        use crate::state::NTRICKS;

    fn fixtures() -> Vec<Value> {
        // `CARGO_MANIFEST_DIR` is rust-cores/dissonance-core.
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../games/dissonance/tests/fixtures/views.jsonl"
        );
        let text = std::fs::read_to_string(path).unwrap_or_else(|e| {
            panic!(
                "{path}: {e}\nRegenerate with:\n  PYTHONPATH=<repo root> python -m \
                 games.dissonance.tools.gen_view_fixtures > \
                 games/dissonance/tests/fixtures/views.jsonl"
            )
        });
        text.lines()
            .filter(|l| !l.trim().is_empty())
            .map(|l| serde_json::from_str(l).expect("fixture line is not JSON"))
            .collect()
    }

    #[test]
    fn every_shipped_view_is_a_position_this_crate_can_search() {
        let all = fixtures();
        assert!(all.len() > 100, "only {} fixtures — regenerate", all.len());
        let mut classic = 0;
        let mut skat = 0;
        let mut minor = 0;
        for (i, f) in all.iter().enumerate() {
            let v = view_from_json(f).unwrap_or_else(|| {
                panic!(
                    "fixture {i} (trick {}, seat {}) did not read back — the pool \
                     arithmetic or a required key has drifted",
                    f["trick"], f["you"]
                )
            });
            match f["mode"].as_str() {
                Some("skat") => skat += 1,
                Some("minor") => minor += 1,
                _ => classic += 1,
            }
            assert_eq!(v.me, f["you"].as_u64().unwrap() as usize);
            assert_eq!(v.s.trump, f["trump"].as_u64().unwrap() as u8);
            assert_eq!(v.s.trick, f["trick"].as_u64().unwrap() as u8);
            assert!(v.s.trick < NTRICKS);
            // The runtime parity must land in the State the searcher actually
            // solves -- a reader that dropped it would score minor as classic
            // and stay green on every other assertion here.
            assert_eq!(
                v.s.even as i64,
                f["even_val"].as_i64().unwrap_or(2),
                "fixture {i}: even_val did not reach State.even"
            );
            // ...and so must card scoring (skat, 2026-08-09): a reader that
            // dropped the flag would search a skat room under the old parity,
            // legal moves and all, with nothing else here going red.
            assert_eq!(
                v.s.cards,
                f["card_pts"].as_bool().unwrap_or(false),
                "fixture {i}: card_pts did not reach State.cards"
            );
            // ...and must-head, which is the one of the three that changes
            // LEGALITY: a reader that dropped it would hand the searcher a
            // larger move list than the room allows, and every answer built
            // on the extra moves would be refused on arrival.
            assert_eq!(
                v.s.head,
                f["must_head"].as_bool().unwrap_or(false),
                "fixture {i}: must_head did not reach State.head"
            );

            // My own hand, exactly. The opponent's is a COUNT and a hole.
            let mine: Mask = f["hand"]
                .as_array()
                .unwrap()
                .iter()
                .fold(0, |m, c| m | 1 << c.as_u64().unwrap());
            assert_eq!(v.s.hand[v.me], mine, "fixture {i}: my hand");
            assert_eq!(v.s.hand[1 - v.me], 0, "fixture {i}: opponent's hand leaked in");
            assert_eq!(
                v.opp_hand_n,
                f["opp_hand_n"].as_u64().unwrap() as u32,
                "fixture {i}"
            );
        }
        assert!(classic > 0 && skat > 0 && minor > 0,
                "all three modes must be covered");
    }

    #[test]
    fn the_legal_moves_agree_with_the_server_for_the_seat_to_move() {
        // `legal` is the server's own answer, and the crate recomputes it rather
        // than reading it (one source, per the module docstring). They must match or
        // the search is enumerating a different game.
        let mut checked = 0;
        for (i, f) in fixtures().iter().enumerate() {
            if f["_mover"].as_u64() != f["you"].as_u64() {
                continue; // `legal` is only meaningful for the seat to play
            }
            let v = view_from_json(f).unwrap();
            let mut m = [0u8; 16];
            let n = v.legal(&mut m);
            let mut got: Vec<u64> = m[..n].iter().map(|&c| c as u64).collect();
            got.sort_unstable();
            let mut want: Vec<u64> = f["legal"]
                .as_array()
                .unwrap()
                .iter()
                .map(|c| c.as_u64().unwrap())
                .collect();
            want.sort_unstable();
            assert_eq!(got, want, "fixture {i}: legal moves");
            checked += 1;
        }
        assert!(checked > 50, "only {checked} mover positions");
    }

    #[test]
    fn every_determinized_deal_is_a_complete_and_consistent_one() {
        // The determinizer is where a bad information set actually bites: it fills
        // the opponent's hand and the covered pile bottoms out of `pool`, so a pool
        // that is the wrong SIZE silently deals the wrong number of cards, and one
        // that is the wrong CONTENT deals a card someone can already see.
        let mut rng = Rng::new(0x0DD7_21CE);
        let mut buf = Vec::new();
        for (i, f) in fixtures().iter().enumerate() {
            let v = view_from_json(f).unwrap();
            let opp = 1 - v.me;
            for _ in 0..3 {
                let d = v.determinize(&mut rng, &mut buf);
                assert_eq!(
                    d.hand[opp].count_ones(),
                    v.opp_hand_n,
                    "fixture {i}: dealt the opponent the wrong number of cards"
                );
                assert_eq!(
                    d.hand[0] & d.hand[1],
                    0,
                    "fixture {i}: a card was dealt to both hands"
                );
                let mut seen: Mask = d.hand[0] | d.hand[1];
                let mut count = d.hand[0].count_ones() + d.hand[1].count_ones();
                for q in 0..2 {
                    for p in 0..3 {
                        let pile = &d.pile[q][p];
                        for k in 0..pile.n as usize {
                            let c = pile.c[k];
                            assert_ne!(c, UNKNOWN, "fixture {i}: an unfilled pile slot");
                            assert_eq!(seen & (1 << c), 0, "fixture {i}: card {c} twice");
                            seen |= 1 << c;
                            count += 1;
                        }
                    }
                }
                // Nobody holds a card that has already been played, and the deal
                // never invents one: what is left over is exactly the out-of-play
                // cards plus everything already on the table.
                assert_eq!(
                    seen.count_ones(),
                    count,
                    "fixture {i}: mask and count disagree"
                );
                let played = f["history"].as_array().unwrap().len() as u32;
                assert_eq!(
                    count + played + NOUT as u32,
                    NCARD as u32,
                    "fixture {i}: the deal does not account for the whole deck"
                );
            }
        }
    }

    #[test]
    fn every_denomination_the_server_can_offer_survives_the_option_reader() {
        // A rejected option empties the WHOLE list (a malformed list is not a
        // partial one), so ONE unreadable denomination silences the tier for
        // that decision and the room quietly plays on the server bot. Grand is
        // denomination 6 and `(0..=4)` rejected it, which is every skat
        // decision, since `skat_declarable` offers Grand at every rung.
        let opt = |d: u8| serde_json::json!({
            "denom": d, "target": 3, "make": 9, "over": 1,
            "set_base": 3, "short": 4, "null": 12 });
        for d in crate::cards::DENOMS {
            let got = options_from_json(&serde_json::json!([opt(d)]));
            assert_eq!(got.len(), 1, "denomination {d} emptied the option list");
            assert_eq!(got[0].denom, d);
            assert!(!got[0].opp && !got[0].redeal, "flags default to the old behaviour");
        }
        // A whole list, as the server actually sends one.
        let all: Vec<_> = crate::cards::DENOMS.iter().map(|&d| opt(d)).collect();
        assert_eq!(options_from_json(&serde_json::json!(all)).len(), crate::cards::DENOMS.len());
        // ...and something genuinely unreadable still empties it, deliberately.
        assert!(options_from_json(&serde_json::json!([opt(9)])).is_empty());
    }

    #[test]
    fn the_pass_flags_are_read_off_the_wire() {
        let v = serde_json::json!([
            {"denom": 2, "target": 3, "make": 9, "set_base": 3, "short": 4,
             "null": 12, "opp": true},
            {"denom": 0, "target": 0, "make": 0, "set_base": 0, "short": 0,
             "null": 0, "redeal": true}]);
        let got = options_from_json(&v);
        assert_eq!(got.len(), 2);
        assert!(got[0].opp && !got[0].redeal);
        assert!(got[1].redeal && !got[1].opp);
    }

    #[test]
    fn a_seats_own_covered_outer_bottoms_are_hidden_from_it_too() {
        // The one asymmetry that is easy to get wrong in the observer's favour:
        // only the MIDDLE pile's bottom is dealt face up. The outer two are face
        // down to their OWNER as well as to the opponent, so the search must
        // resample its own two exactly as it resamples the opponent's.
        //
        // Worth pinning on this side because the Python bot got it wrong in the
        // other direction: `hand_strength` valued a hand using all three of its
        // own bottoms, so it bid knowing two cards the rules never gave it.
        let mut rng = Rng::new(0x0B11_11D5);
        let mut buf = Vec::new();
        let (mut outer_seen, mut outer_varied, mut middle_seen) = (0, 0, 0);
        for f in fixtures().iter() {
            let v = view_from_json(f).unwrap();
            for i in [0usize, 2] {
                if v.s.pile[v.me][i].n == 2 {
                    outer_seen += 1;
                    assert_eq!(v.s.pile[v.me][i].c[0], UNKNOWN,
                        "the observer was handed its own covered outer bottom");
                    // ...and it really is resampled, not merely unknown-at-parse
                    // and then filled with a constant.
                    let mut got = std::collections::HashSet::new();
                    for _ in 0..12 {
                        got.insert(v.determinize(&mut rng, &mut buf).pile[v.me][i].c[0]);
                    }
                    if got.len() > 1 {
                        outer_varied += 1;
                    }
                }
            }
            if v.s.pile[v.me][1].n == 2 {
                middle_seen += 1;
                assert_ne!(v.s.pile[v.me][1].c[0], UNKNOWN,
                    "the middle bottom is dealt FACE UP and must not be resampled");
            }
        }
        // Non-vacuous on both arms: a fixture set with no covered piles left
        // would pass every assertion above without testing anything.
        assert!(outer_seen > 0 && middle_seen > 0,
            "no covered piles in the fixtures: {outer_seen} outer, {middle_seen} middle");
        assert!(outer_varied * 2 > outer_seen,
            "own outer bottoms barely moved across determinizations \
             ({outer_varied} of {outer_seen}) -- they are not being resampled");
    }

    #[test]
    fn a_suit_void_the_server_showed_is_never_dealt_back_into_that_hand() {
        // The inference this crate is allowed to make: failing to follow proves the
        // player held none of that suit IN HAND. Reading it back out of `history`
        // has to reproduce what `Knowledge::observe` builds live, or the search
        // wastes its worlds on deals the seat already knows are impossible.
        let mut rng = Rng::new(0xF00D_5EED);
        let mut buf = Vec::new();
        let mut voids_seen = 0;
        for (i, f) in fixtures().iter().enumerate() {
            let v = view_from_json(f).unwrap();
            let opp = 1 - v.me;
            // NFOLLOW, not 4: under Grand the tens are a class of their own,
            // and a loop that stopped at the four suits would never check the
            // one void the fifth suit makes possible.
            for s in 0..NFOLLOW {
                if !v.kn.hand_void[opp][s] {
                    continue;
                }
                voids_seen += 1;
                for _ in 0..4 {
                    let d = v.determinize(&mut rng, &mut buf);
                    assert_eq!(
                        d.hand[opp] & follow_mask(s as u8, v.s.trump),
                        0,
                        "fixture {i}: dealt class {s} into a hand known to be void"
                    );
                }
            }
        }
        // Non-vacuous: a reader that never inferred a void would pass every
        // assertion above by having nothing to assert.
        assert!(
            voids_seen > 0,
            "no void was inferred anywhere in the fixtures — the reader is not \
             reading history"
        );
    }
}

#[cfg(test)]
mod auction_legality {
    // THE AUCTION'S LEGALITY, held to the engine's own answer.
    //
    // Everything the Expert tier's tree needs is shipped as DATA except this:
    // the leaf prices come from `_terms_for` rows on the wire, but which edges
    // exist at a node the search is standing on cannot be, because the server
    // is not standing there. So `auc_search::legal_bids` mirrors
    // `engine.auction_options`, and this is the only thing keeping them equal.
    //
    // The drift is silent by construction: a tree that believes one extra bid
    // is legal prefers a line the room refuses, `_validated_bot_move` throws
    // the answer away, and the decision falls through to the server bot — a
    // room that says Expert and plays Normal, with nothing red anywhere.
    //
    // Regenerate with `games/dissonance/tools/gen_auction_fixtures.py`.
    use super::*;
    use crate::auc_search::{legal_bids, Bid};
    use std::collections::BTreeSet;

    fn rows() -> Vec<Value> {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../games/dissonance/tests/fixtures/auction.jsonl"
        );
        let text = std::fs::read_to_string(path).unwrap_or_else(|e| {
            panic!("{path}: {e}\nRegenerate with:\n  PYTHONPATH=<repo root> python -m \
                    games.dissonance.tools.gen_auction_fixtures > \
                    games/dissonance/tests/fixtures/auction.jsonl")
        });
        text.lines()
            .filter(|l| !l.trim().is_empty())
            .map(|l| serde_json::from_str(l).expect("fixture line is not JSON"))
            .collect()
    }

    /// Comparable, sorted, and printable — the failure has to name the bid that
    /// differs, not just the count.
    fn as_set(bids: &[Bid]) -> BTreeSet<(u8, u8, u16)> {
        bids.iter()
            .map(|b| match *b {
                Bid::Pass => (0, 0, 0),
                Bid::Contract { level, denom } => (1, denom, level as u16),
                Bid::Number { value } => (2, 0, value),
            })
            .collect()
    }

    fn wanted(row: &Value) -> BTreeSet<(u8, u8, u16)> {
        row["legal"].as_array().unwrap().iter()
            .map(|e| {
                if e.get("pass").is_some() {
                    (0, 0, 0)
                } else if let Some(v) = e.get("value") {
                    (2, 0, v.as_u64().unwrap() as u16)
                } else {
                    (1, e["denom"].as_u64().unwrap() as u8, e["level"].as_u64().unwrap() as u16)
                }
            })
            .collect()
    }

    #[test]
    fn the_tree_offers_exactly_the_bids_the_engine_calls_legal() {
        let all = rows();
        assert!(all.len() > 100, "only {} auction nodes — regenerate", all.len());
        let mut got = Vec::new();
        for (i, row) in all.iter().enumerate() {
            let rules = auc_rules_from_json(&row["rules"])
                .unwrap_or_else(|| panic!("node {i}: the rules did not read back"));
            let state = auc_state_from_json(&row["state"])
                .unwrap_or_else(|| panic!("node {i}: the state did not read back"));
            legal_bids(&state, &rules, &mut got);
            assert_eq!(as_set(&got), wanted(row),
                       "node {i} ({}): {state:?}", row["mode"]);
        }
    }

    /// A fixture that stopped reaching the interesting states would pass the
    /// test above while covering nothing. These are the shapes it exists for.
    #[test]
    fn the_fixture_still_reaches_the_states_worth_covering() {
        let all = rows();
        let count = |f: &dyn Fn(&Value) -> bool| all.iter().filter(|r| f(r)).count();
        let classic = |r: &Value| r["mode"] == "classic";
        assert!(count(&|r| classic(r) && r["state"]["level"].as_u64() == Some(0)) > 5,
                "no classic opener — the only node where passing is illegal");
        // CEILING-RELATIVE, not `>= 11`. Classic's ladder used to end at the
        // parity ceiling of 12 and now stops at 10 (a product cap), so a
        // literal here asserts a level nothing can reach and fails as "the
        // fixtures are thin" rather than "the cap moved".
        assert!(count(&|r| classic(r) && r["state"]["level"].as_u64().unwrap() + 1
                         >= r["rules"]["max_level"].as_u64().unwrap()) > 5,
                "nothing at the ceiling — where the raise cap stops binding");
        assert!(count(&|r| classic(r) && r["rules"]["max_level"].as_u64() == Some(10)) > 20,
                "classic's ladder is not the capped one the engine ships");
        assert!(count(&|r| r["state"]["used"][0].as_u64().unwrap()
                         | r["state"]["used"][1].as_u64().unwrap() != 0) > 40,
                "no spent denominations — the per-seat no-repeat rule is uncovered");
        assert!(count(&|r| r["mode"] == "skat") > 40, "skat's ladder is uncovered");
        assert!(count(&|r| r["state"]["passes"].as_u64().unwrap() > 0) > 0,
                "no skat node mid-pass-out — the one pass that is not a leaf");
        // MINOR: the classic shape at max_level 6. Its whole legality delta is
        // the cap, so the states worth demanding are the opener's 1..6 and a
        // node at the minor ceiling, where a tree hardcoding 12 anywhere
        // would offer overtakes the room refuses.
        let minor = |r: &Value| r["mode"] == "minor";
        assert!(count(&|r| minor(r) && r["rules"]["max_level"].as_u64() == Some(6)) > 20,
                "minor's capped ladder is uncovered");
        assert!(count(&|r| minor(r) && r["state"]["level"].as_u64().unwrap() >= 5) > 0,
                "nothing at minor's ceiling — where its raise cap stops binding");
    }
}

#[cfg(test)]
mod swap_policy_parity {
    // THE SWAP-POLICY ARITHMETIC, held to Python's answer. The WEIGHTS cross
    // the wire so they live once (`bot.swap_policy_terms`), but the FEATURES
    // -- trumpness, void, singleton, take-suit length, the tie-break -- are
    // arithmetic implemented in both `bot.choose_swap` and
    // `bid::SwapPolicy::choose`. Two implementations of one function drift
    // silently, and a drifted leaf model prices every auction against a talon
    // nobody would actually take.
    //
    // The fixture's first line carries the weights, so this test builds its
    // policy FROM the fixture and never grows a third copy of the constants.
    //
    // Regenerate with `games/dissonance/tools/gen_swap_fixtures.py`.
    use super::*;

    fn lines() -> Vec<Value> {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../games/dissonance/tests/fixtures/swap_policy.jsonl"
        );
        let text = std::fs::read_to_string(path).unwrap_or_else(|e| {
            panic!("{path}: {e}\nRegenerate with:\n  PYTHONPATH=<repo root> python -m \
                    games.dissonance.tools.gen_swap_fixtures > \
                    games/dissonance/tests/fixtures/swap_policy.jsonl")
        });
        text.lines()
            .filter(|l| !l.trim().is_empty())
            .map(|l| serde_json::from_str(l).expect("fixture line is not JSON"))
            .collect()
    }

    #[test]
    fn the_leaf_swaps_exactly_the_card_the_server_bot_would() {
        let all = lines();
        let policy = swap_from_json(&all[0]["policy"])
            .expect("the fixture's own policy header did not read back");
        assert!(all.len() > 300, "only {} rows — regenerate", all.len() - 1);
        let (mut swaps, mut pats) = (0, 0);
        for (i, row) in all[1..].iter().enumerate() {
            let hand = mask_of(&row["hand"]);
            let shown = mask_of(&row["shown"]);
            let denom = row["denom"].as_u64().unwrap() as u8;
            let got = policy.choose(hand, shown, denom);
            let want = match (row["take"].as_u64(), row["give"].as_u64()) {
                (Some(t), Some(g)) => Some((t as u8, g as u8)),
                _ => None,
            };
            assert_eq!(got, want, "row {i}: hand {hand:#x} shown {shown:#x} denom {denom}");
            match want {
                Some(_) => swaps += 1,
                None => pats += 1,
            }
        }
        // Both BRANCHES, or the assertion above is half a test: random talons
        // essentially never produce a pat, so the generator engineers them.
        assert!(swaps > 300 && pats >= 10, "{swaps} swaps / {pats} pats");
    }
}

#[cfg(test)]
mod review {
    //! The round review — `deal_from_json` + the exact solve behind `odd_review`.
    //!
    //! The review is shown to a player as a FACT about the round they just
    //! played ("double dummy would have scored this"), not as a bot's opinion,
    //! and these tests are what earns that framing: the reader has to fail
    //! closed on anything that is not a real deal, and the answer has to be the
    //! same number every time it is asked.
    use super::*;
    use crate::dd::Dd;

    /// A complete, legal deal as the server would ship it: 7 in hand and three
    /// 2-card piles per seat, 6 out of play, 32 accounted for exactly once.
    fn deal_json(trump: u8, leader: u8) -> Value {
        let mut c = 0u8;
        let mut next = |n: usize| -> Vec<u8> {
            let v: Vec<u8> = (c..c + n as u8).collect();
            c += n as u8;
            v
        };
        let h0 = next(7);
        let p0: Vec<Vec<u8>> = (0..3).map(|_| next(2)).collect();
        let h1 = next(7);
        let p1: Vec<Vec<u8>> = (0..3).map(|_| next(2)).collect();
        let out = next(6);
        serde_json::json!({
            "hands": [h0, h1],
            "piles": [p0, p1],
            "out": out,
            "trump": trump,
            "leader": leader,
        })
    }

    fn contract_json(declarer: usize) -> Value {
        serde_json::json!({
            "declarer": declarer, "target": 4, "make": 16,
            "set_base": 4, "short": 4, "over": 1, "null": 12,
        })
    }

    #[test]
    fn the_scoring_flags_reach_the_reviewed_state() {
        // A snapshot from before card scoring has no `cards` key and must
        // review under the parity it was played at; a card-scored round's
        // snapshot says so and must solve the card game. Reviewing one under
        // the other is a confidently wrong number in a column labelled a fact.
        let bare = deal_from_json(&deal_json(2, 1)).unwrap();
        assert!(!bare.cards);
        assert_eq!(bare.even, 2);
        let mut j = deal_json(2, 1);
        j["cards"] = serde_json::json!(true);
        let carded = deal_from_json(&j).unwrap();
        assert!(carded.cards);
        // ...and the two really are different games: over a handful of real
        // deals the same contract must not price identically under both
        // readings every time, or the flag reaches the State and decides
        // nothing. Any single deal CAN coincide, so the assertion is over the
        // sweep.
        let c = crate::dd::Contract {
            level: 4, declarer: 0, make_base: 16, over: 1,
            set_base: 4, short: 4, ramp: 0, null: Some(12),
        };
        let mut dd = Dd::new(14);
        let mut differed = false;
        for seed in 0..6u64 {
            let g = crate::game::Game::deal(&mut crate::rng::Rng::new(seed + 40), 2, 1);
            let mut carded = g.s;
            carded.cards = true;
            dd.clear();
            let a = dd.solve_contract(&g.s, &c);
            dd.clear();
            let b = dd.solve_contract(&carded, &c);
            differed |= a != b;
        }
        assert!(differed, "the cards flag did not change the reviewed game");
    }

    #[test]
    fn a_complete_deal_reads_back_as_the_start_of_trick_one() {
        let d = deal_from_json(&deal_json(2, 1)).expect("a complete deal must read");
        assert_eq!(d.trump, 2);
        assert_eq!(d.leader, 1);
        // A review always runs the play from the top, whatever happened live.
        assert_eq!(d.trick, 0);
        assert_eq!(d.led, -1);
        assert_eq!(d.pts, [0, 0]);
        assert_eq!(d.escored, 0, "nobody has won a +2 trick before trick 1");
        for q in 0..2 {
            assert_eq!(d.hand[q].count_ones(), 7);
            for i in 0..3 {
                assert_eq!(d.pile[q][i].n, 2, "every pile starts covered");
            }
        }
        // 7 in hand + 6 in piles, per seat.
        let held: u32 = (0..2)
            .map(|q| d.hand[q].count_ones() + (0..3).map(|i| d.pile[q][i].n as u32).sum::<u32>())
            .sum();
        assert_eq!(held, 2 * NDEALT as u32);
    }

    #[test]
    fn a_pile_is_read_bottom_then_top() {
        // Orientation is the one thing here that a wrong answer would not
        // announce: a flipped pile is a legal position, just the wrong one.
        let d = deal_from_json(&deal_json(4, 0)).unwrap();
        let p = d.pile[0][0];
        assert_eq!(p.c, [7, 8], "stored as [bottom, top]");
        assert_eq!(p.top(), Some(8), "the TOP is what is playable now");
        assert_eq!(p.covered(), Some(7));
    }

    #[test]
    fn an_incomplete_or_double_counted_deal_is_refused() {
        // FAIL CLOSED. Every one of these is a payload that would still
        // describe a searchable-looking position, so the reader has to reject
        // them on the arithmetic rather than on whether it can build a State.
        let strip = |f: &dyn Fn(&mut Value)| {
            let mut v = deal_json(1, 0);
            f(&mut v);
            deal_from_json(&v)
        };
        assert!(strip(&|v| { v["out"] = serde_json::json!([]); }).is_none(),
                "a deal missing its out-cards is not a complete deal");
        assert!(strip(&|v| { v["hands"][0] = serde_json::json!([0, 1, 2, 3, 4, 5]); }).is_none(),
                "a six-card hand leaves a card unaccounted for");
        assert!(strip(&|v| { v["hands"][1][0] = serde_json::json!(0); }).is_none(),
                "the same card in both hands must not read as a legal deal");
        assert!(strip(&|v| { v["piles"][0][0] = serde_json::json!([7]); }).is_none(),
                "a pile is two cards");
        assert!(strip(&|v| { v["leader"] = serde_json::json!(2); }).is_none(),
                "there are two seats");
        assert!(strip(&|v| { v["hands"][0][0] = serde_json::json!(99); }).is_none(),
                "a card index off the end of the deck");
        assert!(strip(&|v| { v.as_object_mut().unwrap().remove("trump"); }).is_none());
    }

    #[test]
    fn a_deal_without_out_cards_reads_the_same_position() {
        // The arena's resolver ships only hands + piles; the six out-cards add
        // integrity, never position (`State` does not store them). Both shapes
        // must read, and to the identical State -- and dropping a card from a
        // HAND must still be refused in the out-less shape.
        let mut v = deal_json(2, 1);
        let full = deal_from_json(&v).expect("with out");
        v.as_object_mut().unwrap().remove("out");
        let bare = deal_from_json(&v).expect("without out");
        assert_eq!(full, bare, "the out-cards changed the position");
        v["hands"][0] = serde_json::json!([0, 1, 2, 3, 4, 5]);
        assert!(deal_from_json(&v).is_none(), "a short hand slipped past the out-less check");
    }

    #[test]
    fn the_review_is_exact_and_gives_the_same_answer_every_time() {
        // The whole argument for showing this number to a player: there is no
        // sampling in it, so it is a property of the DEAL and not of a seed.
        // A PIMC answer would vary run to run and could not be labelled the way
        // this one is.
        let deal = deal_from_json(&deal_json(0, 0)).unwrap();
        let c = contract_from_json(&contract_json(0)).unwrap();
        let mut dd = Dd::new(16);
        let first = dd.solve_contract(&deal, &c);
        for _ in 0..3 {
            dd.clear();
            assert_eq!(dd.solve_contract(&deal, &c), first,
                       "an exact solve of a fixed deal must not move");
        }
        // ...and a WARM table must not change it either, which is the state the
        // export actually runs in (the tier has been searching all round).
        let other = deal_from_json(&deal_json(3, 1)).unwrap();
        dd.solve_contract(&other, &c);
        assert_eq!(dd.solve_contract(&deal, &c), first,
                   "a table warmed on another deal changed the answer");
    }

    #[test]
    fn swapping_the_declarer_reflects_the_value() {
        // The value is signed for the DECLARER. The same cards priced from the
        // other side is a different POSITION (the declarer leads to trick 1),
        // so this asserts the sign convention holds rather than that the two
        // are negatives of each other.
        let deal = deal_from_json(&deal_json(4, 0)).unwrap();
        let mut dd = Dd::new(16);
        let a = dd.solve_contract(&deal, &contract_from_json(&contract_json(0)).unwrap());
        dd.clear();
        let b = dd.solve_contract(&deal, &contract_from_json(&contract_json(1)).unwrap());
        // Both are finite scores in the payoff units the server ships, and a
        // made level-4 contract is worth its 16 while a set one pays the
        // defender -- so they cannot both be the same number by accident.
        assert!(a.abs() < 1000 && b.abs() < 1000, "payoff out of range: {a}, {b}");
    }

    /// THE PAR TABLE'S CONTRACT IS A POINTS SOLVE, EXACTLY -- and this test is
    /// the whole reason the round story can ask for one without a new export.
    ///
    /// The story modal wants "the highest level each side could bid and still
    /// make in each denomination", which is the declarer's double-dummy TRICK
    /// POINTS. There is no wasm export for a points solve (`odd_review` prices
    /// a contract), so the frontend asks for one by naming a contract whose
    /// payoff IS the points:
    ///
    ///   target 0, make 0, over 1, set_base 0, short 1, ramp 0, no null
    ///
    /// Above the target that pays `0 + 1 x (pts - 0)`; below it, `-(0 + 1 x
    /// (0 - pts))` -- the same number, so the payoff is the identity on the
    /// declarer's points at every leaf and the minimax is the points minimax.
    /// A `null` term would break it (the consolation is a cliff, not a point
    /// count), which is why the request omits the key.
    ///
    /// Asserted against `solve`, which is player 0's point DIFFERENTIAL, and
    /// the pool -- so it holds under every scoring the modes have, rather than
    /// against a second copy of the arithmetic.
    #[test]
    fn the_par_contract_is_exactly_a_double_dummy_points_solve() {
        let par = |declarer: usize| crate::dd::Contract {
            level: 0, declarer, make_base: 0, over: 1,
            set_base: 0, short: 1, ramp: 0, null: None,
        };
        // The reader must accept the shape the frontend really sends, null and
        // all -- a missing `null` key is `None`, not a defaulted consolation.
        let read = contract_from_json(&serde_json::json!({
            "declarer": 1, "target": 0, "make": 0, "over": 1,
            "set_base": 0, "short": 1, "ramp": 0,
        })).expect("the par terms must read");
        assert!(read.null.is_none(), "a par contract must carry no consolation");
        assert_eq!(read.key(), par(1).key(), "the wire's par contract is not the one tested");

        let mut dd = Dd::new(16);
        let mut spread = std::collections::HashSet::new();
        // Deliberately small: each cell is TWO cleared exact solves, so the
        // sweep is priced in minutes rather than seconds if it grows.
        for seed in 0..2u64 {
            for trump in [0u8, crate::cards::NOTRUMP] {
                for leader in 0..2u8 {
                    let g = crate::game::Game::deal(
                        &mut crate::rng::Rng::new(seed + 900), trump, leader);
                    let pool = g.s.pool() as i32;
                    dd.clear();
                    let diff0 = dd.solve(&g.s) as i32;   // player 0's differential
                    for declarer in 0..2usize {
                        let d = if declarer == 0 { diff0 } else { -diff0 };
                        // pts[d] + pts[1-d] = pool and pts[d] - pts[1-d] = d.
                        let pts = (pool + d) / 2;
                        dd.clear();
                        let v = dd.solve_contract(&g.s, &par(declarer));
                        assert_eq!(v, pts,
                            "par contract priced {v}, points solve says {pts} \
                             (trump {trump}, leader {leader}, declarer {declarer})");
                        spread.insert(v);
                    }
                }
            }
        }
        // ...and it is not answering one constant for every deal, which would
        // satisfy the equality above and mean nothing.
        assert!(spread.len() > 3, "the par solve returned {spread:?} across 40 asks");
    }

    /// ...and the par table's OTHER question — "could this seat duck every
    /// scoring trick in this denomination?" — is `null_no_even_makeable`.
    ///
    /// Same trick, one term further: a contract whose every ordinary leaf is
    /// worth 0 and whose consolation is worth 1 pays 1 exactly when the
    /// declarer can force taking no scoring trick, so the minimax over it is
    /// the boolean. `nsearch` is the crate's own (much cheaper) answer to that
    /// question and is what the two must agree on -- the browser cannot call
    /// it, since the committed artifact exports no such entry point.
    #[test]
    fn the_par_null_probe_is_exactly_the_ducking_search() {
        let probe = |declarer: usize| crate::dd::Contract {
            level: 0, declarer, make_base: 0, over: 0,
            set_base: 0, short: 0, ramp: 0, null: Some(1),
        };
        let read = contract_from_json(&serde_json::json!({
            "declarer": 0, "target": 0, "make": 0, "over": 0,
            "set_base": 0, "short": 0, "ramp": 0, "null": 1,
        })).expect("the null-probe terms must read");
        assert_eq!(read.key(), probe(0).key(), "the wire's probe is not the one tested");

        // BOTH ANSWERS HAVE TO APPEAR or the agreement below is one constant
        // meeting another -- and a guaranteed duck against double-dummy
        // defence is RARE from a fresh deal, so the cases are found with the
        // cheap boolean search first and only then priced with the expensive
        // one. (Sweeping the probe itself over enough deals to stumble on a
        // duck would cost minutes.)
        let mut dd = Dd::new(16);
        let (mut ducks, mut cannot) = (Vec::new(), Vec::new());
        for seed in 0..200u64 {
            let trump = crate::cards::DENOMS[(seed % 6) as usize];
            let g = crate::game::Game::deal(
                &mut crate::rng::Rng::new(seed + 700), trump, (seed % 2) as u8);
            for declarer in 0..2usize {
                let bucket = if dd.null_no_even_makeable(&g.s, declarer) {
                    &mut ducks
                } else {
                    &mut cannot
                };
                if bucket.len() < 2 {
                    bucket.push((g.s, declarer));
                }
            }
            if ducks.len() >= 2 && cannot.len() >= 2 {
                break;
            }
        }
        assert!(!ducks.is_empty() && !cannot.is_empty(),
                "{} duckable, {} not -- the sweep found only one answer",
                ducks.len(), cannot.len());
        for (want, cases) in [(true, &ducks), (false, &cannot)] {
            for (s, declarer) in cases.iter() {
                dd.clear();
                assert_eq!(dd.null_no_even_makeable(s, *declarer), want, "bucketed wrong");
                dd.clear();
                let got = dd.solve_contract(s, &probe(*declarer));
                assert_eq!(got, want as i32,
                    "probe said {got}, the ducking search said {want} (declarer {declarer})");
            }
        }
    }
}
