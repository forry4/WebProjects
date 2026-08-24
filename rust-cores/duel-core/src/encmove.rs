//! The index-encoded move wire format — `gen_engine_fixtures.enc_move` and its inverse.
//!
//! ONE copy, shared by every cross-language surface: the arena bridge (`move_server`),
//! the compact-parity gate, and the WASM entries whose answer the Python server feeds
//! straight back into `engine.apply_move`. A second copy of this mapping is a silent
//! bug factory — a `slot`/`level` off-by-one here reads as a legal-but-different move
//! on the far side, not as a parse error.
//!
//! `enc_move` is the exact inverse of `gen_engine_fixtures.enc_move`, so anything this
//! emits round-trips through the Python harness unchanged.

use serde::Deserialize;
use serde_json::json;

use crate::engine::{BuySrc, Move, ReserveSrc};

#[derive(Deserialize)]
pub struct EncMove {
    pub t: String,
    #[serde(default)]
    pub cells: Option<Vec<usize>>,
    #[serde(default)]
    pub cell: Option<usize>,
    #[serde(default)]
    pub kind: Option<u8>,
    #[serde(default)]
    pub level: Option<usize>,
    #[serde(default)]
    pub slot: Option<i32>,
    #[serde(default)]
    pub card: Option<usize>,
    #[serde(default, rename = "from")]
    pub from: Option<u8>,
    #[serde(default)]
    pub as_color: Option<i8>,
    #[serde(default)]
    pub color: Option<usize>,
    #[serde(default)]
    pub royal: Option<usize>,
}

/// Panics on a malformed encoding — every caller feeds it either a Python-generated
/// fixture or its own `enc_move` output, so a failure here is a bug, not bad input.
pub fn decode_move(e: &EncMove) -> Move {
    match e.t.as_str() {
        "take" => Move::Take { cells: e.cells.clone().expect("take without cells") },
        "use_privilege" => Move::UsePrivilege { cell: e.cell.expect("use_privilege without cell") },
        "replenish" => Move::Replenish,
        "reserve" => {
            let level = e.level.expect("reserve without level") - 1;
            let src = match e.kind.expect("reserve without kind") {
                0 => ReserveSrc::Pyramid {
                    level,
                    slot: e.slot.expect("pyramid reserve without slot") as usize,
                },
                _ => ReserveSrc::Deck { level },
            };
            Move::Reserve { gold_cell: e.cell.expect("reserve without gold cell"), src }
        }
        "buy" => Move::Buy {
            card: e.card.expect("buy without card"),
            from: if e.from.expect("buy without source") == 0 { BuySrc::Pyramid } else { BuySrc::Reserve },
            as_color: e.as_color.unwrap_or(-1),
        },
        "pass" => Move::Pass,
        "take_same" => Move::TakeSame { cell: e.cell.expect("take_same without cell") },
        "steal" => Move::Steal { color: e.color.expect("steal without color") },
        "choose_royal" => Move::ChooseRoyal { royal: e.royal.expect("choose_royal without royal") },
        "discard" => Move::Discard { color: e.color.expect("discard without color") },
        "skip_pending" => Move::SkipPending,
        other => panic!("unknown move type: {}", other),
    }
}

/// The inverse of `gen_engine_fixtures.enc_move`, so the Python side can feed our answer
/// straight into its own engine.
pub fn enc_move(mv: &Move) -> serde_json::Value {
    match mv {
        Move::Take { cells } => json!({"t": "take", "cells": cells}),
        Move::UsePrivilege { cell } => json!({"t": "use_privilege", "cell": cell}),
        Move::Replenish => json!({"t": "replenish"}),
        Move::Reserve { gold_cell, src } => match src {
            // `slot` is -1 for a deck source, matching Python's `src.get("slot", -1)`.
            ReserveSrc::Pyramid { level, slot } => {
                json!({"t": "reserve", "cell": gold_cell, "kind": 0, "level": level + 1, "slot": slot})
            }
            ReserveSrc::Deck { level } => {
                json!({"t": "reserve", "cell": gold_cell, "kind": 1, "level": level + 1, "slot": -1})
            }
        },
        Move::Buy { card, from, as_color } => json!({
            "t": "buy", "card": card,
            "from": if *from == BuySrc::Pyramid { 0 } else { 1 },
            "as_color": as_color,
        }),
        Move::Pass => json!({"t": "pass"}),
        Move::TakeSame { cell } => json!({"t": "take_same", "cell": cell}),
        Move::Steal { color } => json!({"t": "steal", "color": color}),
        Move::ChooseRoyal { royal } => json!({"t": "choose_royal", "royal": royal}),
        Move::Discard { color } => json!({"t": "discard", "color": color}),
        Move::SkipPending => json!({"t": "skip_pending"}),
    }
}
