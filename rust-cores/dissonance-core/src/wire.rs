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
use crate::dd::Contract;
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
            (Some(d), Some(t), Some(m), Some(sb), Some(sh), Some(nu)) if (0..=4).contains(&d) => {
                out.push(crate::bid::Option_ {
                    denom: d as u8, target: t, make: m,
                    // Optional and flat by default, same as the card search's:
                    // a cached wasm older than the server still prices every
                    // option, just under the rule it was built for.
                    over: n("over").unwrap_or(0),
                    set_base: sb, short: sh, null: nu,
                });
            }
            _ => return Vec::new(),   // a malformed list is not a partial one
        }
    }
    out
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
