//! The lossless State ⇄ JSON "Dump" shape — the compact-state JSON every wasm entry point
//! consumes (`_compact_state_dict` in main.py emits it; `tests/common/mod.rs` mirrors it for
//! fixtures). Serialize support exists for the OFFLINE driver: the browser holds this JSON as
//! the authoritative saved game and round-trips it through the stateless wasm calls
//! (`new_game_json` → `apply_action_json` → …), so the writer must be the exact inverse of
//! the reader. Field-for-field with `engine::State` — a new State field must be added here
//! (and to tests/common) or offline saves silently drop it.

use crate::engine::State;
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize)]
pub struct Dump {
    pub bank: [i32; 6],
    pub tokens: [[i32; 6]; 2],
    pub bonuses: [[i32; 5]; 2],
    pub points: [i32; 2],
    pub purchased_n: [i32; 2],
    pub purchased: [Vec<i32>; 2],
    pub reserved: [Vec<i32>; 2],
    pub reserved_blind: [Vec<bool>; 2],
    pub nobles_won: [Vec<i32>; 2],
    pub board: [i32; 12],
    pub decks: [Vec<i32>; 3],
    pub nobles: [i32; 3],
    pub turn: usize,
    pub phase: u8,
    pub pending_nobles: Vec<usize>,
    pub final_trigger: i32,
    pub winner: i32,
    pub ply: i32,
    pub win_points: i32,
}

impl Dump {
    pub fn into_state(self) -> State {
        State {
            bank: self.bank, tokens: self.tokens, bonuses: self.bonuses, points: self.points,
            purchased_n: self.purchased_n, purchased: self.purchased, reserved: self.reserved,
            reserved_blind: self.reserved_blind, nobles_won: self.nobles_won, board: self.board,
            decks: self.decks, nobles: self.nobles, turn: self.turn, phase: self.phase,
            pending_nobles: self.pending_nobles, final_trigger: self.final_trigger,
            winner: self.winner, ply: self.ply, win_points: self.win_points,
        }
    }

    pub fn from_state(s: &State) -> Dump {
        Dump {
            bank: s.bank, tokens: s.tokens, bonuses: s.bonuses, points: s.points,
            purchased_n: s.purchased_n, purchased: s.purchased.clone(), reserved: s.reserved.clone(),
            reserved_blind: s.reserved_blind.clone(), nobles_won: s.nobles_won.clone(),
            board: s.board, decks: s.decks.clone(), nobles: s.nobles, turn: s.turn, phase: s.phase,
            pending_nobles: s.pending_nobles.clone(), final_trigger: s.final_trigger,
            winner: s.winner, ply: s.ply, win_points: s.win_points,
        }
    }
}

/// Parse a compact-state JSON into a State. `None` on any parse failure.
pub fn state_from_json(state_json: &str) -> Option<State> {
    serde_json::from_str::<Dump>(state_json).ok().map(Dump::into_state)
}

/// Serialize a State to compact-state JSON (the exact shape `state_from_json` reads).
pub fn state_to_json(s: &State) -> String {
    serde_json::to_string(&Dump::from_state(s)).expect("Dump serializes")
}
