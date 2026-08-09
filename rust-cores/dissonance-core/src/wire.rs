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

/// A complete deal — every hand and every pile, nothing redacted.
///
/// NOT A SERVING PATH. `view_from_json` is the redaction boundary and stays the
/// only thing the browser is ever handed; this reads GROUND TRUTH and exists so
/// an offline harness can resolve a settled contract by an exact double-dummy
/// solve of the real cards instead of by playing them with a heuristic. That is
/// `bin/bidlab`'s own method, and it is what takes card-play noise out of an
/// auction measurement entirely: a difference between two bidding strategies
/// becomes a difference in BIDDING, full stop.
///
/// The field names are `play.jsonl`'s, deliberately — `bin/gen_fixtures` already
/// writes exactly this shape, so there is one encoding of a deal in the repo
/// rather than one per harness.
pub fn deal_from_json(v: &Value) -> Option<State> {
    let hands = v.get("hands")?.as_array()?;
    let piles = v.get("piles")?.as_array()?;
    let mut s = State {
        hand: [0; 2],
        pile: [[Pile::default(); 3]; 2],
        trump: u8_at(v, "trump")?,
        trick: 0,
        leader: u8_at(v, "leader")?,
        led: -1,
        pts: [0, 0],
        escored: 0,
    };
    for p in 0..2usize {
        s.hand[p] = mask_of(hands.get(p)?);
        let row = piles.get(p)?.as_array()?;
        for i in 0..3usize {
            let pl = row.get(i)?.as_array()?;
            // [bottom, top], the layout `Pile::c` uses and `gen_fixtures` emits.
            s.pile[p][i] = Pile {
                c: [pl.first()?.as_u64()? as u8, pl.get(1)?.as_u64()? as u8],
                n: 2,
            };
        }
    }
    // Fail closed on anything that is not a fresh, complete deal: the caller is
    // about to spend an exact solve on it, and a deal missing a card resolves
    // to a confident wrong number rather than to an error.
    // DERIVED, not a literal 7: a seat is dealt `NDEALT` cards of which six sit
    // in its three two-card piles, and a hardcoded hand size is wrong under
    // three of the four deck-width features.
    let in_hand = NDEALT as u32 - 6;
    if s.hand[0].count_ones() != in_hand || s.hand[1].count_ones() != in_hand {
        return None;
    }
    if s.hand[0] & s.hand[1] != 0 {
        return None;
    }
    Some(s)
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
    let key = crate::bid::hand_key(&view, declarer, k.max(1));
    // A different hand starts a new entry; the same hand extends the one it
    // has, and asking about nothing new does no work at all.
    let mut entry = match cache.take() {
        Some((k0, s)) if k0 == key => s,
        _ => crate::bid::Solved::default(),
    };
    let cached = (wanted & !entry.covered) == 0 && (wanted_opp & !entry.covered_opp) == 0;
    if !cached {
        crate::bid::solve_into(&view, dd, rng, k.max(1), wanted, wanted_opp, declarer, &mut entry);
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
        let (mut classic, mut skat, mut checked, mut nulls) = (0, 0, 0, 0);
        for (i, f) in all.iter().enumerate() {
            let c = contract_from_json(&f["terms"])
                .unwrap_or_else(|| panic!("fixture {i}: terms did not read back"));
            match f["mode"].as_str() {
                Some("skat") => skat += 1,
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
        assert!(classic > 0 && skat > 0, "both modes must be covered");
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
                _ => classic += 1,
            }
            assert_eq!(v.me, f["you"].as_u64().unwrap() as usize);
            assert_eq!(v.s.trump, f["trump"].as_u64().unwrap() as u8);
            assert_eq!(v.s.trick, f["trick"].as_u64().unwrap() as u8);
            assert!(v.s.trick < NTRICKS);

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
        assert!(classic > 0 && skat > 0, "both auction modes must be covered");
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
        assert!(count(&|r| classic(r) && r["state"]["level"].as_u64().unwrap() >= 11) > 5,
                "nothing at the ceiling — where the raise cap stops binding");
        assert!(count(&|r| r["state"]["used"][0].as_u64().unwrap()
                         | r["state"]["used"][1].as_u64().unwrap() != 0) > 40,
                "no spent denominations — the per-seat no-repeat rule is uncovered");
        assert!(count(&|r| r["mode"] == "skat") > 40, "skat's ladder is uncovered");
        assert!(count(&|r| r["state"]["passes"].as_u64().unwrap() > 0) > 0,
                "no skat node mid-pass-out — the one pass that is not a leaf");
    }
}
