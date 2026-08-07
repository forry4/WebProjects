//! Compose a completed micro-action chain into ONE compact engine move (the JSON
//! shape bridge.py::compact_to_move consumes). The chain must start at an
//! engine-move boundary of `s0` (Micro::None) and end back at one — exactly what
//! the per-decision search loop produces. The inverse (`compact_to_actions`) lives
//! below (bridge/wasm-gated — it takes serde JSON); tests/engine_parity.rs keeps its
//! own copy for fixture replay.

use crate::engine::{
    Pending, State, A_ADJUST0, A_BUY_BLACK0, A_DISCARD0, A_END_TURN, A_GOODS0, A_M6,
    A_PLACE_SLOT0, A_SELL, A_SHIP_DEPOT0, A_SKIP, A_SPACE0, A_SPEND_DIE0, A_TAKE_HEX0, A_WH0,
    A_WORKERS, A_XVALUE0, SETUP,
};

fn menu_sub_json(rest: &[usize]) -> String {
    match rest[0] {
        A_WORKERS => r#"{"t":"workers"}"#.to_string(),
        A_SELL => r#"{"t":"sell"}"#.to_string(),
        a if (A_TAKE_HEX0..A_TAKE_HEX0 + 12).contains(&a) => {
            let k = a - A_TAKE_HEX0;
            format!(r#"{{"t":"take_hex","depot":{},"slot":{}}}"#, k / 2, k % 2)
        }
        a if (A_PLACE_SLOT0..A_PLACE_SLOT0 + 3).contains(&a) => {
            let slot = a - A_PLACE_SLOT0;
            let space = rest[1] - A_SPACE0;
            format!(r#"{{"t":"place","slot":{slot},"space":{space}}}"#)
        }
        a => panic!("bad menu sub action {a}"),
    }
}

pub fn chain_to_compact(s0: &State, chain: &[usize]) -> String {
    let a0 = chain[0];
    if s0.mode == SETUP {
        return format!(r#"{{"t":"castle","space":{}}}"#, a0 - A_SPACE0);
    }
    if a0 == A_SKIP {
        return r#"{"t":"skip"}"#.to_string();
    }
    match s0.pending {
        Pending::ShipChoose => format!(r#"{{"t":"ship","depot":{}}}"#, a0 - A_SHIP_DEPOT0),
        Pending::ShipAdj { .. } => {
            format!(r#"{{"t":"ship_adj","depot":{}}}"#, a0 - A_SHIP_DEPOT0)
        }
        Pending::GoodsPick { .. } => format!(r#"{{"t":"pick","color":{}}}"#, a0 - A_GOODS0),
        Pending::BuildingTake { .. } => {
            let k = a0 - A_TAKE_HEX0;
            format!(r#"{{"t":"btake","depot":{},"slot":{}}}"#, k / 2, k % 2)
        }
        Pending::Warehouse => format!(r#"{{"t":"wh","color":{}}}"#, a0 - A_WH0),
        Pending::Townhall => {
            let slot = a0 - A_PLACE_SLOT0;
            let space = chain[1] - A_SPACE0;
            format!(r#"{{"t":"townhall","slot":{slot},"space":{space}}}"#)
        }
        Pending::ExtraAction => {
            let value = a0 - A_XVALUE0 + 1;
            format!(r#"{{"t":"extra","value":{},"sub":{}}}"#, value, menu_sub_json(&chain[1..]))
        }
        Pending::None => match a0 {
            A_END_TURN => r#"{"t":"end"}"#.to_string(),
            A_M6 => r#"{"t":"m6"}"#.to_string(), // atomic: spend 1 silver -> 2 workers
            a if (A_ADJUST0..A_ADJUST0 + 12).contains(&a) => {
                let k = a - A_ADJUST0;
                format!(r#"{{"t":"adjust","die":{},"to":{}}}"#, k / 6, k % 6 + 1)
            }
            a if (A_BUY_BLACK0..A_BUY_BLACK0 + 4).contains(&a) => {
                format!(r#"{{"t":"black","slot":{}}}"#, a - A_BUY_BLACK0)
            }
            a if (A_DISCARD0..A_DISCARD0 + 3).contains(&a) => {
                format!(r#"{{"t":"discard","slot":{}}}"#, a - A_DISCARD0)
            }
            a if (A_SPEND_DIE0..A_SPEND_DIE0 + 2).contains(&a) => {
                let die = a - A_SPEND_DIE0;
                match chain[1] {
                    A_WORKERS => format!(r#"{{"t":"workers","die":{die}}}"#),
                    A_SELL => format!(r#"{{"t":"sell","die":{die}}}"#),
                    b if (A_TAKE_HEX0..A_TAKE_HEX0 + 12).contains(&b) => {
                        let k = b - A_TAKE_HEX0;
                        format!(
                            r#"{{"t":"take_hex","die":{},"depot":{},"slot":{}}}"#,
                            die,
                            k / 2,
                            k % 2
                        )
                    }
                    b if (A_PLACE_SLOT0..A_PLACE_SLOT0 + 3).contains(&b) => {
                        let slot = b - A_PLACE_SLOT0;
                        let space = chain[2] - A_SPACE0;
                        format!(
                            r#"{{"t":"place","die":{die},"slot":{slot},"space":{space}}}"#
                        )
                    }
                    b => panic!("bad die-menu action {b}"),
                }
            }
            a => panic!("bad main action {a}"),
        },
    }
}

/// Compact move dict → micro-action chain (the exact inverse of `chain_to_compact`;
/// mirrors the fixture-replay copy in tests/engine_parity.rs). NON-PANICKING on
/// malformed input — returns an empty chain, which the offline apply path rejects
/// (a bad move from a client must surface as an error, never a wasm abort). Every
/// produced action is still validated against `legal_actions_full` before applying.
#[cfg(any(feature = "bridge", target_arch = "wasm32"))]
pub fn compact_to_actions(c: &serde_json::Value) -> Vec<usize> {
    use crate::engine::A_TAKE_HEX0 as TH;
    let Some(t) = c["t"].as_str() else { return vec![] };
    let g = |k: &str| c[k].as_i64().unwrap_or(-1) as isize;
    let ok = |v: Vec<isize>| -> Vec<usize> {
        if v.iter().any(|&x| x < 0) { vec![] } else { v.into_iter().map(|x| x as usize).collect() }
    };
    match t {
        "end" => vec![A_END_TURN],
        "skip" => vec![A_SKIP],
        "take_hex" => ok(vec![A_SPEND_DIE0 as isize + g("die"), TH as isize + g("depot") * 2 + g("slot")]),
        "place" => ok(vec![A_SPEND_DIE0 as isize + g("die"), A_PLACE_SLOT0 as isize + g("slot"),
                           A_SPACE0 as isize + g("space")]),
        "sell" => ok(vec![A_SPEND_DIE0 as isize + g("die"), A_SELL as isize]),
        "workers" => ok(vec![A_SPEND_DIE0 as isize + g("die"), A_WORKERS as isize]),
        "adjust" => ok(vec![A_ADJUST0 as isize + g("die") * 6 + (g("to") - 1)]),
        "black" => ok(vec![A_BUY_BLACK0 as isize + g("slot")]),
        "discard" => ok(vec![A_DISCARD0 as isize + g("slot")]),
        "m6" => vec![A_M6],
        "btake" => ok(vec![TH as isize + g("depot") * 2 + g("slot")]),
        "castle" => ok(vec![A_SPACE0 as isize + g("space")]),
        "ship" | "ship_adj" => ok(vec![A_SHIP_DEPOT0 as isize + g("depot")]),
        "pick" => ok(vec![A_GOODS0 as isize + g("color")]),
        "wh" => ok(vec![A_WH0 as isize + g("color")]),
        "townhall" => ok(vec![A_PLACE_SLOT0 as isize + g("slot"), A_SPACE0 as isize + g("space")]),
        "extra" => {
            let mut out = vec![A_XVALUE0 as isize + g("value") - 1];
            let sub = &c["sub"];
            let gs = |k: &str| sub[k].as_i64().unwrap_or(-1) as isize;
            match sub["t"].as_str() {
                Some("workers") => out.push(A_WORKERS as isize),
                Some("sell") => out.push(A_SELL as isize),
                Some("take_hex") => out.push(TH as isize + gs("depot") * 2 + gs("slot")),
                Some("place") => {
                    out.push(A_PLACE_SLOT0 as isize + gs("slot"));
                    out.push(A_SPACE0 as isize + gs("space"));
                }
                _ => return vec![],
            }
            ok(out)
        }
        _ => vec![],
    }
}
