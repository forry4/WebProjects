//! Full-fidelity State ⇄ JSON — the OFFLINE save format (IndexedDB), and nothing else.
//!
//! Deliberately NOT the compact projection: `compact.py::project` is a pure function
//! of PUBLIC information (bag sorted, decks as sorted pools, blind reserves as counts)
//! because the search must not read secrets. An offline save is the opposite contract —
//! the browser IS the authority, so it round-trips the TRUE state exactly: ordered bag,
//! ordered decks, blind reserve identities, and the `revealed` undo gate.
//! Field-for-field with `engine::State`; a new State field must be added here or
//! offline saves silently drop it.

use crate::engine::{Pending, Player, State, Via};
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize)]
pub struct PlayerDump {
    pub tokens: [i32; 7],
    pub privileges: i32,
    pub reserved: Vec<usize>,
    pub reserved_from_deck: Vec<usize>,
    pub purchased: Vec<(usize, i8)>,
    pub royals: Vec<usize>,
    pub royals_claimed: i32,
}

#[derive(Serialize, Deserialize)]
pub struct Dump {
    pub phase: u8,
    pub winner: i32,
    pub win_condition: u8,
    pub win_color: i32,
    pub turn: usize,
    pub turn_number: i32,
    pub replenished: bool,
    #[serde(default)]
    pub revealed: bool,
    pub again: bool,
    pub board: Vec<i8>, // 25
    pub bag: Vec<u8>,
    pub privileges_board: i32,
    pub decks: [Vec<usize>; 3],
    pub pyramid: [Vec<i32>; 3],
    pub royals_available: Vec<usize>,
    pub players: Vec<PlayerDump>, // 2
    pub pending_pid: i32,
    pub pending_kind: u8,
    pub pending_color: i32,
    pub pending_cells: Vec<usize>,
    pub pending_colors: Vec<usize>,
    pub pending_royals: Vec<usize>,
    pub pending_excess: i32,
    /// 0 None | 1 Card(v) | 2 Royal(v)
    pub pending_via_tag: u8,
    pub pending_via_val: usize,
}

impl Dump {
    pub fn from_state(s: &State) -> Dump {
        let (via_tag, via_val) = match s.pending.via {
            Via::None => (0, 0),
            Via::Card(c) => (1, c),
            Via::Royal(r) => (2, r),
        };
        Dump {
            phase: s.phase,
            winner: s.winner,
            win_condition: s.win_condition,
            win_color: s.win_color,
            turn: s.turn,
            turn_number: s.turn_number,
            replenished: s.replenished,
            revealed: s.revealed,
            again: s.again,
            board: s.board.to_vec(),
            bag: s.bag.clone(),
            privileges_board: s.privileges_board,
            decks: s.decks.clone(),
            pyramid: s.pyramid.clone(),
            royals_available: s.royals_available.clone(),
            players: s
                .players
                .iter()
                .map(|p| PlayerDump {
                    tokens: p.tokens,
                    privileges: p.privileges,
                    reserved: p.reserved.clone(),
                    reserved_from_deck: p.reserved_from_deck.clone(),
                    purchased: p.purchased.clone(),
                    royals: p.royals.clone(),
                    royals_claimed: p.royals_claimed,
                })
                .collect(),
            pending_pid: s.pending_pid,
            pending_kind: s.pending_kind,
            pending_color: s.pending.color,
            pending_cells: s.pending.cells.clone(),
            pending_colors: s.pending.colors.clone(),
            pending_royals: s.pending.royals.clone(),
            pending_excess: s.pending.excess,
            pending_via_tag: via_tag,
            pending_via_val: via_val,
        }
    }

    pub fn into_state(self) -> State {
        let mut board = [crate::engine::EMPTY; 25];
        for (i, &c) in self.board.iter().take(25).enumerate() {
            board[i] = c;
        }
        let mut players: [Player; 2] = Default::default();
        for (seat, pd) in self.players.into_iter().enumerate().take(2) {
            players[seat] = Player {
                tokens: pd.tokens,
                privileges: pd.privileges,
                reserved: pd.reserved,
                reserved_from_deck: pd.reserved_from_deck,
                purchased: pd.purchased,
                royals: pd.royals,
                royals_claimed: pd.royals_claimed,
            };
        }
        State {
            phase: self.phase,
            winner: self.winner,
            win_condition: self.win_condition,
            win_color: self.win_color,
            turn: self.turn,
            turn_number: self.turn_number,
            replenished: self.replenished,
            revealed: self.revealed,
            again: self.again,
            board,
            bag: self.bag,
            privileges_board: self.privileges_board,
            decks: self.decks,
            pyramid: self.pyramid,
            royals_available: self.royals_available,
            players,
            pending_pid: self.pending_pid,
            pending_kind: self.pending_kind,
            pending: Pending {
                color: self.pending_color,
                cells: self.pending_cells,
                colors: self.pending_colors,
                royals: self.pending_royals,
                excess: self.pending_excess,
                via: match self.pending_via_tag {
                    1 => Via::Card(self.pending_via_val),
                    2 => Via::Royal(self.pending_via_val),
                    _ => Via::None,
                },
            },
        }
    }
}

pub fn state_from_json(json: &str) -> Option<State> {
    serde_json::from_str::<Dump>(json).ok().map(Dump::into_state)
}

pub fn state_to_json(s: &State) -> String {
    serde_json::to_string(&Dump::from_state(s)).expect("Dump serializes")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::Shuffler;

    struct RngSh<'a>(&'a mut crate::rng::Rng);
    impl<'a> Shuffler for RngSh<'a> {
        fn shuffle(&mut self, bag: &mut Vec<u8>) {
            self.0.shuffle(bag);
        }
    }

    /// The save format's one job: byte-exact round-trips of REAL mid-game states —
    /// including hidden order (bag/decks) and the fields the parity projection
    /// deliberately omits (`revealed`, pending `via`), which `State::proj` alone
    /// would not catch.
    #[test]
    fn dump_round_trips_real_midgame_states() {
        for seed in 0..10u64 {
            let mut s = State::new_game(seed);
            let mut rng = crate::rng::Rng::new(seed + 31);
            for _ in 0..120 {
                if s.is_over() {
                    break;
                }
                let actor = if s.pending_pid >= 0 { s.pending_pid as usize } else { s.turn };
                let legal = s.legal_moves(actor);
                let mv = legal[(rng.next_f64() * legal.len() as f64) as usize % legal.len()].clone();
                s.apply_move(actor, &mv, &mut RngSh(&mut rng)).unwrap();
                let back = state_from_json(&state_to_json(&s)).expect("round-trip parses");
                assert_eq!(back.proj(), s.proj(), "projection drift (seed {seed})");
                assert_eq!(back.revealed, s.revealed, "revealed flag must survive the save");
                assert_eq!(back.pending.via, s.pending.via, "pending via must survive the save");
                assert_eq!(back.bag, s.bag, "ordered bag must survive the save");
                assert_eq!(back.decks, s.decks, "ordered decks must survive the save");
                assert_eq!(
                    [&back.players[0].reserved_from_deck, &back.players[1].reserved_from_deck],
                    [&s.players[0].reserved_from_deck, &s.players[1].reserved_from_deck],
                    "blind-reserve identities must survive the save"
                );
            }
        }
    }
}
