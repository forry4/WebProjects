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

use duel_core::clock::Clock;
use duel_core::encmove::{decode_move, enc_move, EncMove};
use duel_core::endgame;
use duel_core::engine::{ScriptedFills, State, EMPTY, N_CELLS};
use duel_core::mcts::{difficulty, pick, root_search_with_leaf, Leaf, Opts};
use duel_core::rng::Rng;
use duel_core::valuenet::{QuantValueNet, ValueNet};
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
    // Phase-2 net-leaf hooks (additive; absent => the original heuristic/sims behaviour).
    // `leaf: "net"` = the f32 learned value leaf, `leaf: "net8"` = the int8-quantized leaf
    // (the strength-neutrality A/B arm); anything else (or absent) is the heuristic.
    #[serde(default)]
    leaf: Option<String>,
    // A per-decision WALL-CLOCK budget in ms. When set it OVERRIDES `sims`: iterations run
    // uncapped and the clock bounds the search — the equal-time gate arm, where the slower
    // net leaf honestly gets fewer sims. Absent => bound by `sims`, clock free.
    #[serde(default)]
    budget_ms: Option<f64>,
    // Endgame-search hooks (additive; absent => the original pure-MCTS behaviour, so
    // rust_arena / gate_netleaf are untouched). `endgame:true` runs the EXACT `endgame` minimax
    // when `in_endgame` fires and it is CONCLUSIVE, else falls back to the MCTS with the
    // remaining wall-clock budget (the honest equal-time comparison — the exact search is paid
    // for). The `eg_*` knobs override the defaults in `endgame.rs`.
    #[serde(default)]
    endgame: Option<bool>,
    #[serde(default)]
    eg_depth: Option<usize>,
    #[serde(default)]
    eg_node_cap: Option<u64>,
    #[serde(default)]
    eg_dets: Option<usize>,
    #[serde(default)]
    eg_thresh: Option<f64>,
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

/// The pure-MCTS decision — the original `handle` body, factored out so the endgame path can
/// reuse it as its fallback with a REDUCED budget. `budget_ms_override` bounds the search by
/// wall-clock (Some) or leaves it sims-bounded (None); everything else reads off `req`.
fn run_mcts(
    st: &State,
    req: &Req,
    net: &ValueNet,
    net8: &QuantValueNet,
    budget_ms_override: Option<f64>,
) -> serde_json::Value {
    let diff = req.difficulty.clone().unwrap_or_else(|| "hard".to_string());
    let opts = if let Some(ms) = budget_ms_override {
        // Equal-time arm: uncapped iters, wall-clock bound (the honest comparison — the net
        // leaf is slower, so it simply completes fewer sims in the same ms).
        Opts {
            max_iters: Some(u64::MAX),
            time_limit: Some(ms / 1000.0),
            temperature: req.temperature,
            rollout_steps: req.rollout_steps,
            take_dominance: req.take_dominance,
        }
    } else {
        // Sims arm (the existing arena currency): bound by ITERATIONS, clock free, so a busy
        // box can't silently make one side weaker.
        Opts {
            max_iters: req.sims,
            time_limit: Some(req.time_limit.unwrap_or(f64::INFINITY)),
            temperature: req.temperature,
            rollout_steps: req.rollout_steps,
            take_dominance: req.take_dominance,
        }
    };
    let leaf = match req.leaf.as_deref() {
        Some("net") => Leaf::Net(net),
        Some("net8") => Leaf::Net8(net8),
        _ => Leaf::Heuristic,
    };

    let mut rng = Rng::new(req.seed);
    // `root_search_with_leaf` + `pick` reproduces `choose_move_with_leaf` EXACTLY (that is
    // all `choose_move` is), but exposes the sim count + search time so the gate can measure
    // each leaf's sims/s and quantify the equal-time handicap. The Clock wraps ONLY the search.
    let clock = Clock::start();
    let stats = root_search_with_leaf(st, req.seat, &diff, &opts, leaf, &mut rng);
    let elapsed_ms = clock.elapsed_secs() * 1000.0;
    match stats {
        Some(s) => {
            let temp = req.temperature.unwrap_or(difficulty(&diff).temperature);
            let i = pick(&s, temp, &mut rng);
            let sims: i64 = s.n.iter().map(|&x| x as i64).sum();
            json!({ "mv": enc_move(&s.moves[i]), "sims": sims, "elapsed_ms": elapsed_ms })
        }
        None => json!({ "mv": serde_json::Value::Null, "sims": 0, "elapsed_ms": elapsed_ms }),
    }
}

fn handle(req: &Req, net: &ValueNet, net8: &QuantValueNet) -> Result<serde_json::Value, String> {
    let mut st = build_state(&req.setup);
    for (i, rm) in req.moves.iter().enumerate() {
        let mv = decode_move(&rm.mv);
        let mut sh = ScriptedFills::new(rm.fills.clone());
        st.apply_move(rm.actor, &mv, &mut sh)
            .map_err(|e| format!("replay move {} ({}) rejected: {}", i, rm.mv.t, e))?;
    }

    // Endgame-augmented decision (opt-in). When it does not apply — not requested, not an
    // endgame, or inconclusive — it falls back to the pure MCTS, so the default path is
    // byte-for-byte the old behaviour.
    if req.endgame == Some(true) {
        let thresh = req.eg_thresh.unwrap_or(endgame::DEFAULT_THRESH);
        if endgame::in_endgame(&st, thresh) {
            let depth = req.eg_depth.unwrap_or(endgame::DEFAULT_DEPTH);
            let node_cap = req.eg_node_cap.unwrap_or(endgame::DEFAULT_NODE_CAP);
            let dets = req.eg_dets.unwrap_or(endgame::DEFAULT_DETS);
            // The exact search is bounded by the SAME wall-clock budget the plain bot gets, so
            // it is honestly paid for (equal-time). Absent a budget (the sims-mode diagnostic)
            // it runs to its node cap. `endgame_decide` = the fast root-alpha-beta serving path.
            let time_limit_s = req.budget_ms.map(|ms| ms / 1000.0);
            let clock = Clock::start();
            let res = endgame::endgame_decide(&st, req.seat, depth, node_cap, dets, req.seed, time_limit_s);
            let eg_ms = clock.elapsed_secs() * 1000.0;
            if let Some(d) = res {
                return Ok(json!({
                    "mv": enc_move(&d.best),
                    "sims": 0,
                    "elapsed_ms": eg_ms,
                    "endgame_triggered": true,
                    "endgame_conclusive": true,
                    "proven_win": d.proven_win,
                    "eg_nodes": d.nodes,
                    "eg_dets": d.dets_completed,
                }));
            }
            // Inconclusive: spend the REMAINING budget on the MCTS (never negative — floor a
            // small slice so a slow endgame probe still yields a move).
            let remaining = req.budget_ms.map(|b| (b - eg_ms).max(20.0));
            let mut v = run_mcts(&st, req, net, net8, remaining);
            if let Some(obj) = v.as_object_mut() {
                obj.insert("endgame_triggered".into(), json!(true));
                obj.insert("endgame_conclusive".into(), json!(false));
                obj.insert("eg_ms".into(), json!(eg_ms));
            }
            return Ok(v);
        }
    }

    let mut v = run_mcts(&st, req, net, net8, req.budget_ms);
    if let Some(obj) = v.as_object_mut() {
        obj.insert("endgame_triggered".into(), json!(false));
        obj.insert("endgame_conclusive".into(), json!(false));
    }
    Ok(v)
}

fn main() {
    // Load the value net ONCE at startup (embedded, so no cwd/path dependency). The heuristic
    // arena tools (rust_arena.py / sims_ladder.py) never send `leaf:"net"`, so they eat only
    // this one-time parse and are otherwise unaffected.
    let net = ValueNet::from_json_str(include_str!("../value_net.json"))
        .expect("load embedded value_net.json");
    // The int8-quantized trunk of the SAME net (opt-in `leaf:"net8"`). Built once from the f32
    // net at load — no separate file. The heuristic arena tools never send `leaf`, so this
    // one-time quantization is otherwise invisible to them.
    let net8 = QuantValueNet::from_f32(&net);
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
            Ok(req) => match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| handle(&req, &net, &net8))) {
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
