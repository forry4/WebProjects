//! Cross-impl bridge for the strength arena (native-only; `--features bridge`).
//!
//! The RNG stream is the one thing `ai_parity` deliberately leaves free (the two searches
//! cannot draw the same numbers), so its effect is measured STATISTICALLY instead: pit
//! Rust-vs-Python at equal sims over CRN-paired games and require ~0.5. This is the server
//! side of that harness — the spender-core `move_server` precedent.
//!
//! One JSON request per stdin line:
//!   {"setup": {...}, "setup_fills": [...], "moves": [{"mv":…,"actor":n,"fills":[…]}, …],
//!    "seat": n, "sims": n, "seed": n,
//!    // optional: "difficulty" ("hard"|"normal"), "time_limit" (s), "temperature",
//!    //           "rollout_steps", "take_dominance" (false = the "hard+nodom" A/B arm)
//!   }
//! One response per line: {"mv": {…}} in `gen_engine_fixtures.enc_move`'s encoding, or
//! {"mv": null} when the seat has no decision, or {"error": "…"}.
//!
//! Replaying a move list (rather than shipping a state dump) reuses the fixture encoding
//! the parity gates already prove correct — the position the Rust searches is then, by
//! construction, the position Python is sitting on.

use std::collections::HashMap;
use std::io::{self, BufRead, Write};

use duel_core::encmove::{decode_move, enc_move, EncMove};
use duel_core::engine::{ScriptedFills, State, EMPTY, N_CELLS};
use duel_core::mcts::{choose_move, Opts};
use duel_core::rng::Rng;
use serde::Deserialize;
use serde_json::json;

#[derive(Deserialize)]
struct Setup {
    board: Vec<i8>,
    bag: Vec<u8>,
    decks: HashMap<String, Vec<usize>>,
    pyramid: HashMap<String, Vec<i32>>,
    privileges_board: i32,
    royals: Vec<usize>,
    privs: Vec<i32>,
}

#[derive(Deserialize)]
struct ReqMove {
    actor: usize,
    mv: EncMove,
    #[serde(default)]
    fills: Vec<Vec<u8>>,
}

#[derive(Deserialize)]
struct Req {
    setup: Setup,
    #[serde(default)]
    #[allow(dead_code)]
    setup_fills: Vec<Vec<u8>>,
    #[serde(default)]
    moves: Vec<ReqMove>,
    seat: usize,
    #[serde(default)]
    sims: Option<u64>,
    #[serde(default)]
    seed: u64,
    #[serde(default)]
    difficulty: Option<String>,
    #[serde(default)]
    time_limit: Option<f64>,
    #[serde(default)]
    temperature: Option<f64>,
    #[serde(default)]
    rollout_steps: Option<usize>,
    #[serde(default)]
    take_dominance: Option<bool>,
}

fn build_state(s: &Setup) -> State {
    let mut board = [EMPTY; N_CELLS];
    for (i, &t) in s.board.iter().enumerate() {
        board[i] = t;
    }
    State::from_setup(
        board,
        s.bag.clone(),
        [s.decks["1"].clone(), s.decks["2"].clone(), s.decks["3"].clone()],
        [s.pyramid["1"].clone(), s.pyramid["2"].clone(), s.pyramid["3"].clone()],
        s.privileges_board,
        s.royals.clone(),
        [s.privs[0], s.privs[1]],
    )
}

fn handle(req: &Req) -> Result<serde_json::Value, String> {
    let mut st = build_state(&req.setup);
    for (i, rm) in req.moves.iter().enumerate() {
        let mv = decode_move(&rm.mv);
        let mut sh = ScriptedFills::new(rm.fills.clone());
        st.apply_move(rm.actor, &mv, &mut sh)
            .map_err(|e| format!("replay move {} ({}) rejected: {}", i, rm.mv.t, e))?;
    }
    let diff = req.difficulty.clone().unwrap_or_else(|| "hard".to_string());
    let opts = Opts {
        // `sims` is the arena's currency: bound the search by ITERATIONS and let the clock
        // run free, so a busy box can't silently make one side weaker.
        max_iters: req.sims,
        time_limit: Some(req.time_limit.unwrap_or(f64::INFINITY)),
        temperature: req.temperature,
        rollout_steps: req.rollout_steps,
        take_dominance: req.take_dominance,
    };
    let mut rng = Rng::new(req.seed);
    Ok(match choose_move(&st, req.seat, &diff, &opts, &mut rng) {
        Some(mv) => json!({ "mv": enc_move(&mv) }),
        None => json!({ "mv": serde_json::Value::Null }),
    })
}

fn main() {
    let stdin = io::stdin();
    let mut out = io::stdout();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };
        if line.trim().is_empty() {
            continue;
        }
        let resp = match serde_json::from_str::<Req>(&line) {
            Ok(req) => match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| handle(&req))) {
                Ok(Ok(v)) => v,
                Ok(Err(e)) => json!({ "error": e }),
                Err(_) => json!({ "error": "panic while searching" }),
            },
            Err(e) => json!({ "error": format!("bad request: {}", e) }),
        };
        // Flush per line: the Python side is blocked reading this response.
        let _ = writeln!(out, "{}", resp);
        let _ = out.flush();
    }
}
