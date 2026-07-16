//! Spender Duel search core — a Rust port of `games/spender_duel`'s engine + MCTS,
//! built to run the bot's search CLIENT-SIDE via WASM instead of server-side Python.
//!
//! WHY THIS EXISTS (the measured case):
//!   Sims are the strength currency, and the deployed bot is starved of them. It runs
//!   on Render's free tier (~0.1 CPU, ~11x slower than a dev box), so at the `hard`
//!   tier's 2.5s/decision it gets ~410 sims across ~76 root moves — about 5 sims per
//!   move, barely above random. No amount of Python tuning fixes that: it is a
//!   PLATFORM ceiling, not a code one.
//!   Running the same search in the player's browser removes all three limits at once
//!   (their real CPU, Rust instead of Python, root-parallel across cores). The repo has
//!   done this twice: spender-core (variant S/N) and coc-core (Expert) measure ~55-68k
//!   sims/s in-browser against Render's ~85-200.
//!
//! THE RULE FOR THIS CRATE: it must play EXACTLY like the Python it replaces. Strength
//! comes from more sims, never from a different bot. `games/spender_duel/engine.py`
//! stays authoritative for the rules; `cards.rs` is generated from `cards.py`; and the
//! `parity` bin gates every change by stepping both implementations through the same
//! games and comparing state after EVERY move. If the two ever disagree, the Rust is
//! wrong by definition.

pub mod cards;
