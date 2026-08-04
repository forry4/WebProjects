//! Offline-surface parity gate: replay Python-recorded games and require the three
//! offline writers to match the Python they mirror —
//!
//!   * `gamedict::to_player_view`  vs `engine.player_view`   (render redaction),
//!   * `gamedict::to_proj`         vs `compact.project`      (search redaction),
//!   * `gamedict::synth_events`    vs the log delta each `apply_move` appended.
//!
//! The RULES are gated by `parity` (state-exact per move); this bin assumes them and
//! checks the serving surface around them. Events are compared on EVERY move — a
//! diff-based synthesizer drifts exactly on the rare compound moves (auto-resolved
//! abilities, extra turns, winning buys). Views/projections are compared wherever the
//! generator sampled them (every pending + every k-th move + start/over).
//!
//! Fixtures are gitignored — a missing file means REGENERATE, not a parity break:
//!     PYTHONPATH=. python rust-cores/duel-core/tools/gen_gamedict_fixtures.py
//!     cargo run --release --features bridge --bin gamedict_parity

use std::fs::File;
use std::io::{BufRead, BufReader};

use duel_core::engine::{ScriptedFills, State, EMPTY, N_CELLS};
use duel_core::gamedict::{parse_encmove, synth_events, to_player_view, to_proj};
use serde_json::Value;

const PIDS: [&str; 2] = ["p0", "p1"];

fn build_state(setup: &Value) -> State {
    let mut board = [EMPTY; N_CELLS];
    for (i, c) in setup["board"].as_array().unwrap().iter().enumerate() {
        board[i] = c.as_i64().unwrap() as i8;
    }
    let deck = |l: &str| -> Vec<usize> {
        setup["decks"][l].as_array().unwrap().iter().map(|x| x.as_u64().unwrap() as usize).collect()
    };
    let pyr = |l: &str| -> Vec<i32> {
        setup["pyramid"][l].as_array().unwrap().iter().map(|x| x.as_i64().unwrap() as i32).collect()
    };
    State::from_setup(
        board,
        setup["bag"].as_array().unwrap().iter().map(|x| x.as_u64().unwrap() as u8).collect(),
        [deck("1"), deck("2"), deck("3")],
        [pyr("1"), pyr("2"), pyr("3")],
        setup["privileges_board"].as_i64().unwrap() as i32,
        setup["royals"].as_array().unwrap().iter().map(|x| x.as_u64().unwrap() as usize).collect(),
        [
            setup["privs"][0].as_i64().unwrap() as i32,
            setup["privs"][1].as_i64().unwrap() as i32,
        ],
    )
}

/// Compare as parsed Values (key order irrelevant); on mismatch, name the keys that
/// differ so the failure is debuggable without diffing two multi-KB JSON walls.
fn diff_value(label: &str, want: &Value, got: &Value) -> bool {
    if want == got {
        return true;
    }
    println!("    {} MISMATCH:", label);
    match (want, got) {
        (Value::Object(w), Value::Object(g)) => {
            for k in w.keys().chain(g.keys().filter(|k| !w.contains_key(*k))) {
                let (wv, gv) = (w.get(k), g.get(k));
                if wv != gv {
                    println!("      .{}:\n        py:   {}\n        rust: {}",
                        k,
                        wv.map(|v| v.to_string()).unwrap_or("<missing>".into()),
                        gv.map(|v| v.to_string()).unwrap_or("<missing>".into()));
                }
            }
        }
        _ => println!("      py:   {}\n      rust: {}", want, got),
    }
    false
}

/// The sampled views/projs block: views = [p0, p1, spectator], projs = [seat0, seat1].
fn check_views(rec: &Value, st: &State, wher: &str) -> usize {
    let mut bad = 0;
    if let Some(views) = rec.get("views").and_then(|v| v.as_array()) {
        for (i, viewer) in [0i32, 1, -1].iter().enumerate() {
            let got = to_player_view(st, PIDS, PIDS, *viewer);
            if !diff_value(&format!("{} player_view(viewer={})", wher, viewer), &views[i], &got) {
                bad += 1;
            }
        }
        let projs = rec["projs"].as_array().unwrap();
        for seat in 0..2usize {
            let got = to_proj(st, seat);
            if !diff_value(&format!("{} project(seat={})", wher, seat), &projs[seat], &got) {
                bad += 1;
            }
        }
    }
    bad
}

fn main() {
    let path = std::env::var("DUEL_GAMEDICT_FIXTURES").unwrap_or_else(|_| {
        concat!(env!("CARGO_MANIFEST_DIR"), "/fixtures/gamedict_fixtures.jsonl").to_string()
    });
    let file = match File::open(&path) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("cannot open {}: {}", path, e);
            eprintln!("fixtures are gitignored — regenerate with:");
            eprintln!("  PYTHONPATH=. python rust-cores/duel-core/tools/gen_gamedict_fixtures.py");
            std::process::exit(2);
        }
    };

    let (mut games, mut n_moves, mut n_view_checks, mut bad) = (0usize, 0usize, 0usize, 0usize);

    for line in BufReader::new(file).lines() {
        let line = line.expect("read error");
        if line.trim().is_empty() {
            continue;
        }
        let fx: Value = serde_json::from_str(&line).expect("bad fixture line");
        games += 1;
        let seed = fx["seed"].as_i64().unwrap();

        let mut st = build_state(&fx["setup"]);
        let b0 = check_views(&fx["views0"], &st, &format!("game seed={} setup", seed));
        if b0 > 0 {
            bad += b0;
            continue; // a wrong start cascades into every later sample
        }
        n_view_checks += 1;

        for (mi, fm) in fx["moves"].as_array().unwrap().iter().enumerate() {
            let actor = fm["actor"].as_u64().unwrap() as usize;
            let mv = parse_encmove(&fm["mv"]).unwrap_or_else(|| {
                panic!("game seed={} move {}: unparseable fixture move {}", seed, mi, fm["mv"])
            });
            let before = st.clone();
            let fills: Vec<Vec<u8>> = fm["fills"]
                .as_array()
                .unwrap()
                .iter()
                .map(|f| f.as_array().unwrap().iter().map(|x| x.as_u64().unwrap() as u8).collect())
                .collect();
            let mut sh = ScriptedFills::new(fills);
            if let Err(e) = st.apply_move(actor, &mv, &mut sh) {
                println!("game seed={} move {}: REJECTED {}: {}", seed, mi, fm["mv"], e);
                bad += 1;
                break;
            }
            n_moves += 1;

            let got_events = Value::Array(synth_events(&before, &st, actor, &mv, PIDS));
            if !diff_value(
                &format!("game seed={} move {} ({}) events", seed, mi, fm["mv"]["t"]),
                &fm["events"],
                &got_events,
            ) {
                bad += 1;
            }

            let b = check_views(fm, &st, &format!("game seed={} move {}", seed, mi));
            if fm.get("views").is_some() {
                n_view_checks += 1;
            }
            if b > 0 {
                bad += b;
                break; // state is fine (parity gates it) but the writers diverged: report once per game
            }
        }
    }

    println!(
        "\n=== gamedict parity: {} games, {} moves (events all checked), {} sampled view positions, {} mismatches ===",
        games, n_moves, n_view_checks, bad
    );
    if bad > 0 {
        println!("FAIL — engine.player_view / compact.project / the engine log are authoritative.");
        std::process::exit(1);
    }
    println!("PASS — the offline serving surface matches the Python it mirrors.");
}
