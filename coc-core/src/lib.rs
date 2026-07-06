//! Castles of Crimson search core. Module layout mirrors spender-core:
//! generated static tables (boards_gen) + tile data (tiles) + compact engine (engine) +
//! fixed action space (actions) + heuristic scaffold (heuristic) + PUCT (mcts) +
//! search drivers (vsearch) + nets (valuenet/attn) + wasm entries (wasm).

pub mod boards_gen;
pub mod rng;
pub mod tiles;
pub mod valuenet;

pub mod actions;
pub mod engine;
pub mod heuristic;
pub mod mcts;
pub mod proj;
pub mod pxio;
pub mod vsearch;

#[cfg(target_arch = "wasm32")]
pub mod wasm;
