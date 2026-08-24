//! THE DRIFT GATE for the offline referee.
//!
//! `src/classic.rs` is a second implementation of the shipped classic phase
//! machine, and two implementations of one rule set drift silently — this
//! crate already learned that about card play, which is why
//! `tests/test_rust_parity.py` exists. This is the same method one phase
//! earlier: replay real rounds recorded from `games/dissonance/engine.py` and
//! demand the same per-seat view after every single move.
//!
//! What a failure here means, in order of likelihood: the auction's legality,
//! a phase transition, the redaction, or the trick fold. What it does NOT
//! cover is SCORING, because `classic.rs` deliberately does none — the offline
//! driver prices the round with `pricing.js`, which `test_bid_worth.py` gates
//! against `engine.payoff`.
//!
//! Run: `cargo test --release --features bridge --test classic`
//! Regenerate: `PYTHONPATH=. python -m games.dissonance.tools.gen_classic_fixtures 120
//!              > games/dissonance/tests/fixtures/classic.jsonl`

#![cfg(feature = "bridge")]

use dissonance::classic;
use serde_json::Value;

const FIXTURES: &str = "../../games/dissonance/tests/fixtures/classic.jsonl";

/// The keys the Python generator strips before hashing — `result` and `match`
/// are the driver's to fill, not this module's.
fn strip(mut v: Value) -> Value {
    if let Some(o) = v.as_object_mut() {
        o.remove("result");
        o.remove("match");
    }
    v
}

/// FNV-1a/64 over the view's canonical JSON. `serde_json::Value` holds its
/// objects in a BTreeMap, so `to_string` emits sorted keys with no spaces —
/// the same bytes `json.dumps(sort_keys=True, separators=(",", ":"))` makes.
fn fnv1a(v: &Value) -> u64 {
    let s = serde_json::to_string(v).expect("view serialises");
    let mut h: u64 = 0xCBF2_9CE4_8422_2325;
    for b in s.as_bytes() {
        h ^= *b as u64;
        h = h.wrapping_mul(0x0000_0100_0000_01B3);
    }
    h
}

fn load() -> Vec<Value> {
    let raw = std::fs::read_to_string(FIXTURES).unwrap_or_else(|e| {
        panic!(
            "{FIXTURES}: {e}\n\
             Regenerate with:\n  PYTHONPATH=. python -m \
             games.dissonance.tools.gen_classic_fixtures 120 > {FIXTURES}"
        )
    });
    raw.lines()
        .filter(|l| !l.trim().is_empty())
        .map(|l| serde_json::from_str(l).expect("a fixture line is JSON"))
        .collect()
}

#[test]
fn the_offline_referee_agrees_with_the_server_after_every_move() {
    let rounds = load();
    assert!(rounds.len() >= 20, "thin corpus: {} rounds", rounds.len());
    let mut moves = 0usize;
    let mut full = 0usize;

    for (ri, round) in rounds.iter().enumerate() {
        let mut g = round["g"].clone();
        let steps = round["steps"].as_array().expect("steps");
        for (si, step) in steps.iter().enumerate() {
            let pid = step["pid"].as_str().expect("pid");
            // The seed only matters for `next_round`, which a single-round
            // fixture never reaches; 0 keeps the replay deterministic.
            classic::apply_move(&mut g, pid, &step["move"], 0).unwrap_or_else(|e| {
                panic!("round {ri} step {si} {:?}: the offline engine refused a move the server applied: {e}", step["move"])
            });
            let got: Vec<Value> = (0..2).map(|s| strip(classic::view_for(&g, s))).collect();

            // The full views, where they were recorded (first and last step).
            // Checked BEFORE the digest so a canonicalisation difference reads
            // as the field that differs rather than as an opaque hash miss.
            if let Some(want) = step.get("views").and_then(|v| v.as_array()) {
                full += 1;
                for seat in 0..2 {
                    if want[seat] != got[seat] {
                        let mut diff = Vec::new();
                        for (k, wv) in want[seat].as_object().unwrap() {
                            let gv = got[seat].get(k);
                            if Some(wv) != gv {
                                diff.push(format!("  {k}:\n    server {wv}\n    offline {}",
                                    gv.map(|v| v.to_string()).unwrap_or_else(|| "<missing>".into())));
                            }
                        }
                        for k in got[seat].as_object().unwrap().keys() {
                            if want[seat].get(k).is_none() {
                                diff.push(format!("  {k}: offline invented this key"));
                            }
                        }
                        panic!(
                            "round {ri} step {si} seat {seat}: the view diverged\n{}",
                            diff.join("\n")
                        );
                    }
                }
            }

            let want_h = step["h"].as_array().expect("digests");
            for seat in 0..2 {
                assert_eq!(
                    fnv1a(&got[seat]),
                    want_h[seat].as_u64().expect("a digest"),
                    "round {ri} step {si} seat {seat}: the view diverged after {:?}. \
                     Replay this round in Python and diff the two views — the \
                     generator's `_views_at` does exactly that.",
                    step["move"]
                );
            }
            moves += 1;
        }
        assert_eq!(
            g["phase"].as_str(),
            Some("over"),
            "round {ri}: the offline engine did not finish the round"
        );
    }
    // NON-VACUITY. A replay that applied nothing would pass every assertion
    // above; these are the counts that say it really ran.
    assert!(moves > 3000, "only {moves} moves replayed");
    assert_eq!(full, rounds.len() * 2, "the full-view control did not run");
    eprintln!("classic parity: {} rounds, {moves} moves", rounds.len());
}

/// The engine is CLASSIC ONLY and must say so rather than mis-refereeing a
/// mode it does not implement — a wrong referee is worse than an absent one.
#[test]
fn any_other_mode_is_refused_at_the_door() {
    let rounds = load();
    for mode in ["skat", "minor", "dummy"] {
        let mut g = rounds[0]["g"].clone();
        g["mode"] = Value::String(mode.into());
        let mv = rounds[0]["steps"][0]["move"].clone();
        let pid = rounds[0]["steps"][0]["pid"].as_str().unwrap();
        assert!(
            classic::apply_move(&mut g, pid, &mv, 0).is_err(),
            "{mode} was accepted by an engine that only plays classic"
        );
    }
}
