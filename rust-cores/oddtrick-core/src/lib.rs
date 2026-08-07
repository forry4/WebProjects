//! Card-play core for the parity trick-taking game.
//!
//! 28-card deck, 13 cards each (7 in hand + three 2-card piles), 13 tricks.
//! Even-numbered tricks score +2, odd-numbered tricks -1, so the round is
//! constant-sum at +5 and "run your winners" is a losing plan by construction.
//!
//! Layers: `state` is the rules, `dd` solves a known deal exactly, `view` is
//! the information set plus its determinizer, `bots` are the players.

pub mod auction;
pub mod bots;
pub mod cards;
pub mod dd;
pub mod game;
pub mod infer;
pub mod policy;
pub mod rng;
pub mod skat;
pub mod state;
pub mod view;

pub use cards::*;
pub use dd::Dd;
pub use game::{play_round, Bot, Game};
pub use rng::Rng;
pub use state::{beats, trick_value, Pile, State, NTRICKS, POOL};
pub use view::{Knowledge, View};
