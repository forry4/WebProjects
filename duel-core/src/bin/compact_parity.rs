//! Compact-projection parity gate (native-only; `--features bridge`).
//!
//! The question this answers is the one serving hangs on: the browser never sees the
//! real game — it searches `compact.py::project`'s output, which deliberately drops the
//! deck order and the opponent's blind-reserve identities. So: **is the projection
//! lossless for everything the search reads?**
//!
//! Method: Python projects a real position and records what IT computes on the TRUE game
//! (`engine.legal_moves` and `ai._value`, both seats, at every position of every game);
//! we ingest the projection and must reproduce both — the move list EXACTLY, order
//! included (the rollout samples it by index, so order is play-affecting), and the leaf
//! to 1e-12 (the search optimises it; a leaf that differs at all is a different bot).
//!
//! The other half of the contract — that the projection carries no SECRET — is not
//! checkable here (we can only see what was shipped) and is gated on the Python side by
//! `games/spender_duel/tests/test_compact.py`.
//!
//!     python duel-core/tools/gen_compact_fixtures.py --games 120
//!     cargo run --release --features bridge --bin compact_parity

use std::io::{BufRead, BufReader};

use duel_core::compact::from_proj;
use duel_core::encmove::enc_move;
use duel_core::value::value;
use serde_json::Value;

const TOL: f64 = 1e-12;

fn main() {
    let path = std::env::args().nth(1).unwrap_or_else(|| {
        concat!(env!("CARGO_MANIFEST_DIR"), "/fixtures/compact_fixtures.jsonl").to_string()
    });
    let f = std::fs::File::open(&path).unwrap_or_else(|e| {
        panic!("open {}: {} — run tools/gen_compact_fixtures.py first", path, e)
    });

    let (mut n_pos, mut n_legal, mut n_blind, mut n_pend) = (0u64, 0u64, 0u64, 0u64);
    let mut worst = 0.0f64;
    for (ln, line) in BufReader::new(f).lines().enumerate() {
        let line = line.expect("read fixture");
        if line.trim().is_empty() {
            continue;
        }
        let rec: Value = serde_json::from_str(&line).expect("parse fixture");
        let proj = &rec["proj"];
        let seat = rec["seat"].as_u64().unwrap() as usize;

        let (st, got_seat) = from_proj(proj)
            .unwrap_or_else(|| panic!("line {}: projection rejected by from_proj", ln + 1));
        assert_eq!(got_seat, seat, "line {}: seat mismatch", ln + 1);

        // Move list: exact, INCLUDING order.
        let want: Vec<String> =
            rec["legal"].as_array().unwrap().iter().map(|m| m.to_string()).collect();
        let got: Vec<String> =
            st.legal_moves(seat).iter().map(|m| enc_move(m).to_string()).collect();
        assert_eq!(
            got.len(),
            want.len(),
            "line {}: legal_moves length {} != Python's {}\n  rust: {:?}\n  py:   {:?}",
            ln + 1, got.len(), want.len(), got, want
        );
        for (i, (g, w)) in got.iter().zip(&want).enumerate() {
            // Compare as parsed JSON: key ORDER inside a move object is an artifact of
            // each side's serializer, not part of the encoding.
            let (gv, wv): (Value, Value) = (serde_json::from_str(g).unwrap(), serde_json::from_str(w).unwrap());
            assert_eq!(gv, wv, "line {}: legal move {} differs\n  rust: {}\n  py:   {}", ln + 1, i, g, w);
        }
        n_legal += got.len() as u64;

        // Leaf value for the projected seat.
        let want_v: f64 = rec["val"].as_str().unwrap().parse().expect("parse val");
        let got_v = value(&st, seat);
        let d = (got_v - want_v).abs();
        assert!(d <= TOL, "line {}: value {} != Python's {} (d={:.3e})", ln + 1, got_v, want_v, d);
        worst = worst.max(d);

        if proj["players"]
            .as_array()
            .unwrap()
            .iter()
            .any(|p| p["reserved_blind"].as_array().unwrap().iter().any(|x| x.as_u64().unwrap() > 0))
        {
            n_blind += 1;
        }
        if proj["pending_kind"].as_u64().unwrap() != 0 {
            n_pend += 1;
        }
        n_pos += 1;
    }

    // A corpus that never exercises the redaction would pass while proving nothing about
    // it — the generator refuses to write one, and we refuse to accept one.
    assert!(n_blind > 0, "no fixture has an opponent blind reserve: the redaction is untested");
    assert!(n_pend > 0, "no fixture has a pending sub-decision");
    println!(
        "compact parity OK: {} projections, {} legal moves, worst value delta {:.3e}",
        n_pos, n_legal, worst
    );
    println!("  with an opponent blind reserve : {}", n_blind);
    println!("  with a pending sub-decision    : {}", n_pend);
}
