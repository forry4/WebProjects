//! Differential parity gate for the AI layer: the heuristic leaf (`value`) and the pruned
//! move lists (`legal` / `rollout_top_tier`).
//!
//! WHY THIS IS A SEPARATE GATE FROM `parity`: the Rust MCTS can never be byte-identical to
//! the Python one — different RNGs, so the simulations diverge by construction. That leaves
//! exactly two things to pin down, and they are the two that MATTER:
//!
//!   * the LEAF: if Rust judges a position even slightly differently, its search is
//!     optimising a different game. Gated to 1e-12, from BOTH seats (a sign/perspective
//!     slip is a classic port bug and is invisible if you only check the mover).
//!   * the BRANCHES: if Rust considers a different set of moves — or the same set in a
//!     different ORDER — it is a different bot. Order is load-bearing: the rollout picks
//!     by INDEX.
//!
//! The fixtures (`fixtures/ai_fixtures.jsonl`) come from `tools/gen_ai_fixtures.py` against
//! the authoritative Python. If Rust disagrees, the Rust is wrong — never "fix" the fixture.
//!
//!     cargo run --release --features bridge --bin ai_parity

use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader};

use duel_core::engine::{BuySrc, Move, ReserveSrc, ScriptedFills, State, EMPTY, N_CELLS};
use duel_core::mcts::{legal, rollout_top_tier};
use duel_core::value::{value, WEIGHTS};
use serde::Deserialize;

/// Absolute tolerance on the leaf. Python writes floats with `repr()`, which round-trips
/// exactly through Rust's f64 parser, so this compares actual bits — not a printed
/// approximation. 1e-12 leaves room only for a final-ULP difference in libm's `tanh`/`pow`
/// (~1e-16 here); anything structural is orders of magnitude bigger and fails.
const VAL_TOL: f64 = 1e-12;

/// Cap on DETAILED mismatch prints. Everything is still counted — the summary is the
/// verdict; this just keeps a broken port from printing a hundred thousand lines.
const MAX_REPORTS: usize = 20;

// ─── Fixture schema (mirrors gen_ai_fixtures.py) ─────────────────────────────
#[derive(Deserialize)]
struct Header {
    weights: HashMap<String, f64>,
}

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
    /// The leaf from BOTH seats, as `repr()` strings.
    val: Vec<String>,
    /// The next decision's actor + move lists. Absent once the game is over; `top` is also
    /// absent while a pending is open (the rollout enumerates those normally, not by tier).
    #[serde(default)]
    seat: Option<usize>,
    #[serde(default)]
    legal: Option<Vec<EncMove>>,
    #[serde(default)]
    top: Option<Vec<EncMove>>,
}

#[derive(Deserialize)]
struct Fixture {
    seed: i64,
    setup: Setup,
    #[allow(dead_code)]
    setup_fills: Vec<Vec<u8>>,
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

fn describe_mv(m: &Move) -> String {
    match m {
        Move::Take { cells } => format!("take{:?}", cells),
        Move::UsePrivilege { cell } => format!("use_privilege({})", cell),
        Move::Replenish => "replenish".into(),
        Move::Reserve { gold_cell, src } => match src {
            ReserveSrc::Pyramid { level, slot } => format!("reserve(g{} pyr L{} s{})", gold_cell, level + 1, slot),
            ReserveSrc::Deck { level } => format!("reserve(g{} deck L{})", gold_cell, level + 1),
        },
        Move::Buy { card, from, as_color } => format!(
            "buy({} {} as{})",
            card,
            if *from == BuySrc::Pyramid { "pyr" } else { "res" },
            as_color
        ),
        Move::Pass => "pass".into(),
        Move::TakeSame { cell } => format!("take_same({})", cell),
        Move::Steal { color } => format!("steal({})", color),
        Move::ChooseRoyal { royal } => format!("choose_royal({})", royal),
        Move::Discard { color } => format!("discard({})", color),
        Move::SkipPending => "skip_pending".into(),
    }
}

/// Element-by-element diff of a move list — order is part of the contract, so report the
/// first position that differs rather than just "the sets differ".
fn report_moves(label: &str, want: &[Move], got: &[Move]) {
    println!("    {}: expected {} move(s), got {}", label, want.len(), got.len());
    for i in 0..want.len().max(got.len()) {
        let w = want.get(i).map(describe_mv).unwrap_or_else(|| "<missing>".into());
        let g = got.get(i).map(describe_mv).unwrap_or_else(|| "<missing>".into());
        if w != g {
            println!("      [{}] expected {:<28} got {}", i, w, g);
        }
    }
}

/// The Rust duplicates Python's WEIGHTS by necessity. This is the tripwire: a re-tuned
/// Python weight must fail LOUDLY here (with the value gate telling the same story), never
/// quietly ship a Rust bot playing to stale numbers. Unknown keys fail too — a NEW Python
/// weight the port doesn't implement is exactly as wrong as a changed one.
fn check_weights(h: &HashMap<String, f64>) -> Vec<String> {
    let w = &WEIGHTS;
    let expect: [(&str, f64); 12] = [
        ("progress", w.progress),
        ("progress_exp", w.progress_exp),
        ("points", w.points),
        ("crowns", w.crowns),
        ("color", w.color),
        ("bonus", w.bonus),
        ("bonus_spread", w.bonus_spread),
        ("token", w.token),
        ("gold", w.gold),
        ("privilege", w.privilege),
        ("reserved", w.reserved),
        ("scale", w.scale),
    ];
    let mut errs = Vec::new();
    for (k, v) in expect {
        match h.get(k) {
            Some(&got) if got == v => {}
            Some(&got) => errs.push(format!("{}: Python has {}, Rust has {}", k, got, v)),
            None => errs.push(format!("{}: missing from the fixture header", k)),
        }
    }
    for k in h.keys() {
        if !expect.iter().any(|(n, _)| n == k) {
            errs.push(format!("{}: Python has a weight the Rust port does not implement", k));
        }
    }
    errs
}

fn main() {
    let path = std::env::var("DUEL_AI_FIXTURES")
        .unwrap_or_else(|_| concat!(env!("CARGO_MANIFEST_DIR"), "/fixtures/ai_fixtures.jsonl").to_string());
    let file = match File::open(&path) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("cannot open {}: {}", path, e);
            eprintln!("regenerate with: PYTHONPATH=. python duel-core/tools/gen_ai_fixtures.py --games 60 --loaded 20");
            std::process::exit(2);
        }
    };

    let mut lines = BufReader::new(file).lines();

    // ── Header: the weights the fixtures were generated with ──
    let head_line = lines.next().expect("empty fixture file").expect("read error");
    let head: Header = serde_json::from_str(&head_line).expect("bad fixture header line");
    let weight_errs = check_weights(&head.weights);
    if !weight_errs.is_empty() {
        println!("WEIGHTS MISMATCH (fixture header vs duel_core::value::WEIGHTS):");
        for e in &weight_errs {
            println!("    {}", e);
        }
    }

    let (mut games, mut positions, mut mismatches) = (0usize, 0usize, 0usize);
    let (mut val_n, mut legal_n, mut top_n) = (0usize, 0usize, 0usize);
    let (mut val_bad, mut legal_bad, mut top_bad, mut proj_bad) = (0usize, 0usize, 0usize, 0usize);
    let mut max_err = 0.0f64;
    let mut reports = 0usize;

    for line in lines {
        let line = line.expect("read error");
        if line.trim().is_empty() {
            continue;
        }
        let fx: Fixture = serde_json::from_str(&line).expect("bad fixture line");
        games += 1;

        let mut st = build_state(&fx.setup);

        for (mi, fm) in fx.moves.iter().enumerate() {
            let mv = decode_move(&fm.mv);
            let mut sh = ScriptedFills::new(fm.fills.clone());
            if let Err(e) = st.apply_move(fm.actor, &mv, &mut sh) {
                println!(
                    "game seed={} move {}: REJECTED {} (actor {}): {}",
                    fx.seed, mi, describe(&fm.mv), fm.actor, e
                );
                mismatches += 1;
                break;
            }
            positions += 1;

            // (1) The engine gate, re-run: cheap insurance that the AI checks below are
            // being asked about the RIGHT position. A value that matches on a state that
            // has already drifted would be a false pass.
            let got_proj = st.proj();
            if got_proj != fm.proj {
                proj_bad += 1;
                mismatches += 1;
                if reports < MAX_REPORTS {
                    reports += 1;
                    println!(
                        "game seed={} move {}: STATE MISMATCH after {} — the replay has drifted; \
                         run `parity` first (the engine gate is the one that owns this).",
                        fx.seed, mi, describe(&fm.mv)
                    );
                }
                break; // the state has diverged: every later check is noise
            }

            // (2) The leaf, from both seats.
            for seat in 0..2 {
                let want: f64 = fm.val[seat].parse().expect("bad val float");
                let got = value(&st, seat);
                val_n += 1;
                let err = (got - want).abs();
                if err > max_err {
                    max_err = err;
                }
                if !(err <= VAL_TOL) {
                    val_bad += 1;
                    mismatches += 1;
                    if reports < MAX_REPORTS {
                        reports += 1;
                        println!(
                            "game seed={} move {}: VALUE MISMATCH seat {} after {}",
                            fx.seed, mi, seat, describe(&fm.mv)
                        );
                        println!("      expected: {}", want);
                        println!("      got:      {}", got);
                        println!("      abs err:  {:e}", err);
                    }
                }
            }

            // (3) + (4) The branches: same moves, SAME ORDER.
            if let Some(seat) = fm.seat {
                if let Some(want_enc) = &fm.legal {
                    let want: Vec<Move> = want_enc.iter().map(decode_move).collect();
                    let got = legal(&st, seat, true);
                    legal_n += want.len();
                    if got != want {
                        legal_bad += 1;
                        mismatches += 1;
                        if reports < MAX_REPORTS {
                            reports += 1;
                            println!(
                                "game seed={} move {}: _legal MISMATCH for seat {} (position after {})",
                                fx.seed, mi, seat, describe(&fm.mv)
                            );
                            report_moves("_legal", &want, &got);
                        }
                    }
                }
                if let Some(want_enc) = &fm.top {
                    let want: Vec<Move> = want_enc.iter().map(decode_move).collect();
                    let got = rollout_top_tier(&st, seat, true);
                    top_n += want.len();
                    if got != want {
                        top_bad += 1;
                        mismatches += 1;
                        if reports < MAX_REPORTS {
                            reports += 1;
                            println!(
                                "game seed={} move {}: _rollout_top_tier MISMATCH for seat {} (position after {})",
                                fx.seed, mi, seat, describe(&fm.mv)
                            );
                            report_moves("_rollout_top_tier", &want, &got);
                        }
                    }
                }
            }
        }

        if games % 20 == 0 {
            println!("  ... {} games, {} positions, {} mismatches", games, positions, mismatches);
        }
    }

    if reports >= MAX_REPORTS {
        println!("\n(detailed reports capped at {}; all mismatches are still counted below)", MAX_REPORTS);
    }
    println!("\n=== ai_parity ===");
    println!("  games            : {}", games);
    println!("  positions        : {}", positions);
    println!("  value samples    : {}  ({} bad, tol {:e})", val_n, val_bad, VAL_TOL);
    println!("  _legal moves     : {}  ({} position(s) bad)", legal_n, legal_bad);
    println!("  top-tier moves   : {}  ({} position(s) bad)", top_n, top_bad);
    println!("  state projections: {} bad", proj_bad);
    println!("  max value error  : {:e}", max_err);
    println!("  mismatches       : {}", mismatches);

    if !weight_errs.is_empty() {
        println!("\nFAIL — the Rust WEIGHTS are not the weights these fixtures were generated with.");
        std::process::exit(1);
    }
    if mismatches > 0 {
        println!("\nFAIL — the Python AI is authoritative; the Rust is wrong.");
        std::process::exit(1);
    }
    if val_n == 0 || legal_n == 0 || top_n == 0 {
        // A gate that checks nothing passes trivially — that is a failure, not a pass.
        println!("\nFAIL — the corpus exercised nothing (values/legal/top all empty).");
        std::process::exit(1);
    }
    println!("\nPASS — Rust reproduces games/spender_duel/ai.py's leaf and branches exactly.");
}
