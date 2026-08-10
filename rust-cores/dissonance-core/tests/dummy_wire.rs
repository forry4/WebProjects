//! The dummy reader against the Python engine's own views.
//!
//! `dummy.rs` re-states the rules instead of sharing `state.rs`, so nothing
//! structural keeps the two in step. This is what does. It replays every ply of
//! real rounds (`tools/gen_dummy_fixtures.py`) and demands the reader agree
//! with the engine about what it can see, what is legal, and whose turn it is.
//!
//! Every failure mode here is SILENT in production: a reader that refuses
//! everything degrades to the server bot at full speed under a Hard label, and
//! one that mis-sizes the hidden pool answers with a card computed from a lie.
//! Neither shows up as an error anywhere, which is why the assertions below are
//! about agreement rather than about not crashing.
//!
//!     cargo test --release --features bridge --test dummy_wire

use dissonance::dummy::*;
use serde_json::Value;

fn rows() -> Vec<Value> {
    let path = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../games/dissonance/tests/fixtures/dummy_views.jsonl"
    );
    let text = std::fs::read_to_string(path).unwrap_or_else(|e| {
        panic!(
            "missing {path}: {e}\nregenerate with\n  PYTHONPATH=. python -m \
             games.dissonance.tools.gen_dummy_fixtures"
        )
    });
    text.lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| serde_json::from_str(l).expect("bad fixture line"))
        .collect()
}

fn u8s(v: &Value) -> Vec<u8> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|x| x.as_u64().unwrap() as u8)
        .collect()
}

#[test]
fn every_ply_of_a_real_round_is_readable() {
    // A reader that fails closed on everything is "safe" and useless -- it
    // degrades every decision to the server bot while the label still says
    // Hard, which is precisely the outage shape this file exists to prevent.
    let rows = rows();
    assert!(rows.len() > 300, "fixture file looks truncated");
    let mut read = 0;
    for r in &rows {
        let view = serde_json::to_string(&r["view"]).unwrap();
        assert!(
            dview_from_json(&view).is_some(),
            "ply {} of the fixtures could not be read",
            read
        );
        read += 1;
    }
    assert_eq!(read, rows.len());
}

#[test]
fn the_reader_sees_exactly_what_the_engine_gave_that_seat() {
    for r in rows() {
        let view = serde_json::to_string(&r["view"]).unwrap();
        let dv = dview_from_json(&view).unwrap();
        let truth = &r["truth"];
        let me = dv.me as usize;
        let hands = truth["hands"].as_array().unwrap();

        // Its own hand, exactly -- no more and no less.
        let mut mine = dv.my_hand.clone();
        mine.sort();
        assert_eq!(mine, u8s(&hands[me]), "own hand");

        // The dummy's hand, exactly: it is face up from the deal, which is the
        // mode's premise and the reason a dummy world resamples so little.
        let mut d = dv.dummy_hand.clone();
        d.sort();
        assert_eq!(d, u8s(&hands[2]), "the dummy is public");

        // ...and the OPPONENT's hand only as a COUNT. A reader that could name
        // it would be reading a leak, so this is a redaction test too.
        assert_eq!(dv.opp_hand_n, hands[1 - me].as_array().unwrap().len());
        for c in u8s(&hands[1 - me]) {
            assert!(
                dv.unseen() & (1 << c) != 0,
                "card {c} of the opponent's hand was visible to the reader"
            );
        }
    }
}

#[test]
fn a_seats_own_covered_outer_bottoms_are_hidden_from_it_too() {
    // The asymmetry that is easy to get wrong: only the MIDDLE pile's bottom is
    // dealt face up, so a seat cannot name its own outer bottoms either. A
    // reader that assumed otherwise would search worlds the player cannot know.
    let mut checked = 0;
    for r in rows() {
        let view = serde_json::to_string(&r["view"]).unwrap();
        let dv = dview_from_json(&view).unwrap();
        let piles = r["truth"]["piles"].as_array().unwrap();
        for q in 0..3usize {
            for i in 0..3usize {
                let p = u8s(&piles[q][i]);
                if p.len() == 2 && i != 1 {
                    // covered, outer: the bottom must be unplaced for everyone
                    assert!(
                        dv.unseen() & (1 << p[0]) != 0,
                        "seat {} pile {} bottom {} was visible",
                        q,
                        i,
                        p[0]
                    );
                    checked += 1;
                }
            }
        }
    }
    assert!(checked > 100, "the hidden-bottom case was barely reached");
}

#[test]
fn the_determinized_world_is_a_legal_deal_and_agrees_on_whose_turn_it_is() {
    for (n, r) in rows().iter().enumerate() {
        let view = serde_json::to_string(&r["view"]).unwrap();
        let dv = dview_from_json(&view).unwrap();
        let st = dv
            .determinize(0x5eed ^ n as u64)
            .unwrap_or_else(|| panic!("ply {n} determinized to nothing"));

        // Every card exactly once: the three holdings plus what is out.
        let mut count = [0u8; 40];
        for q in 0..3 {
            let mut m = st.hand[q];
            while m != 0 {
                count[m.trailing_zeros() as usize] += 1;
                m &= m - 1;
            }
            for i in 0..3 {
                for k in 0..st.pile[q][i].n as usize {
                    count[st.pile[q][i].c[k] as usize] += 1;
                }
            }
        }
        assert!(count.iter().all(|&c| c <= 1), "ply {n}: a card was dealt twice");

        // POSITION and SEAT, the mode's central trap: the engine's `to_play` is
        // a position (which may be the dummy) while the acting PLAYER is the
        // side commanding it. Both must match, or the searcher answers for the
        // wrong hand and the room refuses every card it sends.
        let want_pos = r["truth"]["to_play"].as_u64().unwrap() as u8;
        let want_seat = r["truth"]["turn_seat"].as_u64().unwrap() as u8;
        assert_eq!(st.to_play(), want_pos, "ply {n}: position on turn");
        assert_eq!(st.side_of(st.to_play()), want_seat, "ply {n}: acting player");
        assert_eq!(st.side_of(st.to_play()), dv.me, "the armed seat is the actor");
    }
}

#[test]
fn the_legal_set_matches_the_engine_exactly() {
    // The one that decides whether a searching tier works at all. If the two
    // implementations disagree about legality, the browser answers with cards
    // the room refuses, `_validated_bot_move` drops them, and the room plays
    // the server bot at full speed while still saying Hard.
    for (n, r) in rows().iter().enumerate() {
        let view = serde_json::to_string(&r["view"]).unwrap();
        let dv = dview_from_json(&view).unwrap();
        let st = dv.determinize(0xd00d ^ n as u64).unwrap();
        let mut buf = [0u8; 16];
        let k = st.legal(&mut buf);
        let mut got: Vec<u8> = buf[..k].to_vec();
        got.sort();
        let want = u8s(&r["truth"]["legal"]);
        assert_eq!(got, want, "ply {n}: legal set");
    }
}

#[test]
fn a_search_answers_every_position_with_a_card_the_engine_calls_legal() {
    // End to end, at the shipped settings: what the browser would actually
    // send back, checked against what the room would actually accept.
    for (n, r) in rows().iter().enumerate().filter(|(i, _)| i % 7 == 0) {
        let view = serde_json::to_string(&r["view"]).unwrap();
        let dv = dview_from_json(&view).unwrap();
        let vals = pimc(&dv, 2, 2, Leaf::Material, 0xabc ^ n as u64)
            .unwrap_or_else(|| panic!("ply {n}: no world was searchable"));
        let card = best_card(&vals, dv.me).unwrap();
        let want = u8s(&r["truth"]["legal"]);
        assert!(
            want.contains(&card),
            "ply {n}: answered {card}, which the engine would refuse"
        );
        // The value vector is indexed by ascending card order and must be a
        // pure function of the position -- the browser pools it across workers
        // by summing index-wise, so a different order in one worker is a
        // silently different bot.
        let order: Vec<u8> = vals.iter().map(|x| x.0).collect();
        let mut sorted = order.clone();
        sorted.sort();
        assert_eq!(order, sorted, "ply {n}: legal order is not stable");
        assert_eq!(order, want, "ply {n}: pooled indices must be the legal set");
    }
}

#[test]
fn a_view_this_reader_cannot_honour_is_refused_rather_than_guessed() {
    // Fail-closed, checked by BREAKING real payloads. Each of these is a shape
    // the reader must not try to search: a different mode, a Grand contract it
    // has no rule for, and a card count that cannot partition.
    let r = &rows()[40];
    let base = r["view"].clone();

    let mut wrong_mode = base.clone();
    wrong_mode["mode"] = Value::from("skat");
    assert!(dview_from_json(&wrong_mode.to_string()).is_none());

    let mut grand = base.clone();
    grand["trump"] = Value::from(6);
    assert!(
        dview_from_json(&grand.to_string()).is_none(),
        "Grand has no rule here and must not be guessed at"
    );

    let mut miscount = base.clone();
    miscount["opp_hand_n"] = Value::from(99);
    assert!(dview_from_json(&miscount.to_string()).is_none());

    let mut leaked = base.clone();
    // A dummy that led is impossible; the reader must not build a state from it.
    leaked["leader"] = Value::from(2);
    assert!(dview_from_json(&leaked.to_string()).is_none());

    // ...and the unbroken original still reads, so the assertions above are
    // about the damage and not about the fixture.
    assert!(dview_from_json(&base.to_string()).is_some());
}

#[test]
fn the_wrapped_payload_the_browser_actually_sends_is_read_too() {
    // The worker sends `{view, payoff, auction}`, not a bare view. Reading only
    // the bare shape made every real decision return "not a searchable dummy
    // position" while all 468 fixture rows passed -- and the room simply played
    // the server bot at full speed under a Hard label, which is the exact
    // silent degradation this file exists to catch. It took a browser gate to
    // find, so it gets a test at this level too.
    let r = &rows()[60];
    let bare = serde_json::to_string(&r["view"]).unwrap();
    let wrapped = serde_json::json!({
        "view": r["view"].clone(),
        "payoff": {"make": 9, "set_base": 3},
    })
    .to_string();
    let a = dview_from_json(&bare).expect("bare view");
    let b = dview_from_json(&wrapped).expect("the shape the worker sends");
    assert_eq!(a.my_hand, b.my_hand);
    assert_eq!(a.dummy_hand, b.dummy_hand);
    assert_eq!(a.unseen(), b.unseen());
    assert_eq!(a.me, b.me);
}
