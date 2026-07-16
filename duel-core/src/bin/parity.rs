//! Differential parity gate: replay Python-recorded games through the Rust engine and
//! require a byte-identical projection after EVERY move.
//!
//! WHY AFTER EVERY MOVE: comparing only final states lets two bugs cancel. The fixture
//! records the projection per move precisely so the FIRST divergence is the one reported.
//!
//! The fixtures (`fixtures/engine_fixtures.jsonl`, one game per line) are produced by
//! `tools/gen_engine_fixtures.py` against the authoritative Python engine. If Rust
//! disagrees, the Rust is wrong — never "fix" the fixture.
//!
//!     cargo run --release --features bridge --bin parity

use std::collections::VecDeque;
use std::fs::File;
use std::io::{BufRead, BufReader};

use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::engine::{BuySrc, Move, ReserveSrc, ScriptedFills, State, EMPTY, N_CELLS};
use serde::Deserialize;

// ─── Fixture schema (mirrors gen_engine_fixtures.py) ─────────────────────────
#[derive(Deserialize)]
struct Setup {
    board: Vec<i8>,
    bag: Vec<u8>,
    decks: std::collections::HashMap<String, Vec<usize>>,
    pyramid: std::collections::HashMap<String, Vec<i32>>,
    privileges_board: i32,
    royals: Vec<usize>,
    privs: Vec<i32>,
}

/// The index-encoded move (`enc_move`): a flat object whose fields depend on `t`.
#[derive(Deserialize)]
struct EncMove {
    t: String,
    #[serde(default)]
    cells: Option<Vec<usize>>,
    #[serde(default)]
    cell: Option<usize>,
    #[serde(default)]
    kind: Option<u8>,
    #[serde(default)]
    level: Option<usize>,
    #[serde(default)]
    slot: Option<i32>,
    #[serde(default)]
    card: Option<usize>,
    #[serde(default, rename = "from")]
    from: Option<u8>,
    #[serde(default)]
    as_color: Option<i8>,
    #[serde(default)]
    color: Option<usize>,
    #[serde(default)]
    royal: Option<usize>,
}

#[derive(Deserialize)]
struct FxMove {
    actor: usize,
    mv: EncMove,
    fills: Vec<Vec<u8>>,
    proj: String,
}

#[derive(Deserialize)]
struct Fixture {
    seed: i64,
    setup: Setup,
    setup_fills: Vec<Vec<u8>>,
    proj0: String,
    moves: Vec<FxMove>,
    #[allow(dead_code)]
    over: bool,
}

// ─── Decoding ────────────────────────────────────────────────────────────────
fn decode_move(e: &EncMove) -> Move {
    // Levels are 1-based in the fixture (as in the Python) and 0-based in the Rust engine.
    match e.t.as_str() {
        "take" => Move::Take { cells: e.cells.clone().expect("take without cells") },
        "use_privilege" => Move::UsePrivilege { cell: e.cell.expect("use_privilege without cell") },
        "replenish" => Move::Replenish,
        "reserve" => {
            let level = e.level.expect("reserve without level") - 1;
            let src = match e.kind.expect("reserve without kind") {
                0 => ReserveSrc::Pyramid { level, slot: e.slot.expect("pyramid reserve without slot") as usize },
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
        other => panic!("unknown fixture move type: {}", other),
    }
}

fn build_state(s: &Setup) -> State {
    let mut board = [EMPTY; N_CELLS];
    for (i, &t) in s.board.iter().enumerate() {
        board[i] = t;
    }
    let decks = [s.decks["1"].clone(), s.decks["2"].clone(), s.decks["3"].clone()];
    let pyramid = [s.pyramid["1"].clone(), s.pyramid["2"].clone(), s.pyramid["3"].clone()];
    State::from_setup(
        board,
        s.bag.clone(),
        decks,
        pyramid,
        s.privileges_board,
        s.royals.clone(),
        [s.privs[0], s.privs[1]],
    )
}

// ─── Reporting ───────────────────────────────────────────────────────────────
/// Field-by-field diff of the `|`-joined projection — the thing that makes a mismatch
/// debuggable instead of a wall of numbers.
fn report_diff(expect: &str, got: &str) {
    let e: Vec<&str> = expect.split('|').collect();
    let g: Vec<&str> = got.split('|').collect();
    if e.len() != g.len() {
        println!("    projection arity differs: expected {} fields, got {}", e.len(), g.len());
    }
    for i in 0..e.len().max(g.len()) {
        let ef = e.get(i).copied().unwrap_or("<missing>");
        let gf = g.get(i).copied().unwrap_or("<missing>");
        if ef != gf {
            println!("    FIELD {}:", i);
            println!("      expected: {}", ef);
            println!("      got:      {}", gf);
        }
    }
}

fn describe(e: &EncMove) -> String {
    format!(
        "{}{}{}{}{}{}{}{}{}",
        e.t,
        e.cells.as_ref().map(|c| format!(" cells={:?}", c)).unwrap_or_default(),
        e.cell.map(|c| format!(" cell={}", c)).unwrap_or_default(),
        e.kind.map(|k| format!(" kind={}", k)).unwrap_or_default(),
        e.level.map(|l| format!(" level={}", l)).unwrap_or_default(),
        e.slot.map(|s| format!(" slot={}", s)).unwrap_or_default(),
        e.card.map(|c| format!(" card={}", c)).unwrap_or_default(),
        e.from.map(|f| format!(" from={}", f)).unwrap_or_default(),
        e.color
            .map(|c| format!(" color={}", c))
            .or(e.royal.map(|r| format!(" royal={}", r)))
            .unwrap_or_default(),
    )
}

/// Independently re-derive the initial deal from its recorded shuffle: start from the
/// full bag on an empty board, apply Python's post-shuffle order, fill in spiral order.
/// Validates `_fill_board` + SPIRAL_ORDER against 520 deals that `setup` alone would
/// have let us skip (the setup gives the filled board outright).
fn check_setup_fill(fx: &Fixture) -> Result<(), String> {
    if fx.setup_fills.len() != 1 {
        return Err(format!("expected exactly 1 setup fill, got {}", fx.setup_fills.len()));
    }
    let mut bag: VecDeque<u8> = TOKEN_BAG.iter().copied().collect();
    if bag.len() != fx.setup_fills[0].len() {
        return Err("setup fill script size != TOKEN_BAG".into());
    }
    let mut board = [EMPTY; N_CELLS];
    let mut script: Vec<u8> = fx.setup_fills[0].clone();
    bag.clear();
    for &idx in SPIRAL_ORDER.iter() {
        if script.is_empty() {
            break;
        }
        if board[idx] == EMPTY {
            board[idx] = script.pop().unwrap() as i8;
        }
    }
    for i in 0..N_CELLS {
        if board[i] != fx.setup.board[i] {
            return Err(format!(
                "initial fill: cell {} = {}, setup says {}",
                i, board[i], fx.setup.board[i]
            ));
        }
    }
    if !script.is_empty() || !fx.setup.bag.is_empty() {
        return Err("initial fill did not exhaust the bag".into());
    }
    Ok(())
}

fn main() {
    // Defaults to the in-crate fixtures; `DUEL_FIXTURES` overrides for an out-of-tree run.
    let path = std::env::var("DUEL_FIXTURES")
        .unwrap_or_else(|_| concat!(env!("CARGO_MANIFEST_DIR"), "/fixtures/engine_fixtures.jsonl").to_string());
    let file = match File::open(&path) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("cannot open {}: {}", path, e);
            eprintln!("regenerate with: PYTHONPATH=. python duel-core/tools/gen_engine_fixtures.py --games 400 --loaded 120");
            std::process::exit(2);
        }
    };

    let (mut games, mut n_moves, mut mismatches, mut illegal) = (0usize, 0usize, 0usize, 0usize);

    for line in BufReader::new(file).lines() {
        let line = line.expect("read error");
        if line.trim().is_empty() {
            continue;
        }
        let fx: Fixture = serde_json::from_str(&line).expect("bad fixture line");
        games += 1;

        if let Err(e) = check_setup_fill(&fx) {
            println!("game seed={}: SETUP FILL MISMATCH: {}", fx.seed, e);
            mismatches += 1;
        }

        let mut st = build_state(&fx.setup);
        let got0 = st.proj();
        if got0 != fx.proj0 {
            println!("game seed={}: SETUP MISMATCH (before any move)", fx.seed);
            report_diff(&fx.proj0, &got0);
            mismatches += 1;
            continue; // every later move would cascade off a wrong start
        }

        for (mi, fm) in fx.moves.iter().enumerate() {
            let mv = decode_move(&fm.mv);

            // Every fixture move was chosen from Python's `legal_moves`, so ours must
            // offer it too — this checks move ENUMERATION, which the projection alone
            // (state after an externally-supplied move) would never exercise.
            if !st.legal_moves(fm.actor).contains(&mv) {
                println!(
                    "game seed={} move {}: ILLEGAL — Rust's legal_moves omits {} (actor {})",
                    fx.seed,
                    mi,
                    describe(&fm.mv),
                    fm.actor
                );
                illegal += 1;
            }

            let mut sh = ScriptedFills::new(fm.fills.clone());
            match st.apply_move(fm.actor, &mv, &mut sh) {
                Ok(()) => {}
                Err(e) => {
                    println!(
                        "game seed={} move {}: REJECTED {} (actor {}): {}",
                        fx.seed,
                        mi,
                        describe(&fm.mv),
                        fm.actor,
                        e
                    );
                    mismatches += 1;
                    break;
                }
            }
            if !sh.is_empty() {
                println!(
                    "game seed={} move {}: {} unused scripted fill(s) — Rust shuffled less often than Python",
                    fx.seed, mi, sh.queue.len()
                );
                mismatches += 1;
            }
            n_moves += 1;

            let got = st.proj();
            if got != fm.proj {
                println!(
                    "game seed={} move {}: MISMATCH after {} (actor {})",
                    fx.seed,
                    mi,
                    describe(&fm.mv),
                    fm.actor
                );
                report_diff(&fm.proj, &got);
                mismatches += 1;
                break; // the state has diverged: everything after is noise
            }
        }

        if games % 100 == 0 {
            println!("  ... {} games, {} moves, {} mismatches", games, n_moves, mismatches);
        }
    }

    println!("\n=== parity: {} games, {} moves, {} mismatches, {} illegal ===", games, n_moves, mismatches, illegal);
    if mismatches > 0 || illegal > 0 {
        println!("FAIL — the Python engine is authoritative; the Rust is wrong.");
        std::process::exit(1);
    }
    println!("PASS — Rust reproduces games/spender_duel/engine.py state-exactly.");
}
