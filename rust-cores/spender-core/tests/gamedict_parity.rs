//! Render-dict parity: the Rust `gamedict::to_game_dict` must reproduce the Python reference —
//! `serving.engine.to_game_dict` (full view) AND `main._redact_blind_reserves` of it (seat-0
//! view) — as equal JSON VALUES at every sampled position. The JSX renders whatever this emits,
//! so a drifted key here is a wrong board on screen in offline play.
//!
//! Fixtures: `tools/gen_gamedict_fixtures.py` (run it before this test).
//! Build: needs the `bridge` feature (serde in the native lib): `cargo test --features bridge`.

mod common;

use common::Dump;
use serde::Deserialize;
use serde_json::Value;
use spender_core::gamedict;

#[derive(Deserialize)]
struct Position {
    dump: Dump,
    full: Value,
    red0: Value,
}

#[test]
fn gamedict_matches_python() {
    let path = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/gamedict_fixtures.json");
    let raw = std::fs::read_to_string(path)
        .unwrap_or_else(|e| panic!("read {path}: {e}\nRun: python spender-core/tools/gen_gamedict_fixtures.py"));
    let positions: Vec<Position> = serde_json::from_str(&raw).expect("parse fixtures");
    assert!(!positions.is_empty(), "no fixtures");

    let mut n_pending = 0usize;
    for (pi, pos) in positions.iter().enumerate() {
        let s = pos.dump.to_state();
        if s.phase == spender_core::engine::DISCARD || s.phase == spender_core::engine::NOBLE {
            n_pending += 1;
        }
        let full: Value = serde_json::from_str(&gamedict::to_game_dict_json(&s, "p0", "p1", -1))
            .expect("rust full parses");
        assert_eq!(full, pos.full, "full-view game dict mismatch at position {pi}");
        let red0: Value = serde_json::from_str(&gamedict::to_game_dict_json(&s, "p0", "p1", 0))
            .expect("rust red0 parses");
        assert_eq!(red0, pos.red0, "seat-0 redacted game dict mismatch at position {pi}");
    }
    // The fixture generator asserts it sampled pending-phase positions; re-assert here so a
    // hand-trimmed fixture can't quietly stop covering pending_* (the drift-prone keys).
    assert!(n_pending > 0, "no pending-phase positions in fixtures");
    eprintln!("gamedict parity OK: {} positions ({n_pending} pending-phase)", positions.len());
}
