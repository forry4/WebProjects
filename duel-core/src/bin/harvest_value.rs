//! Self-play harvest for the learned value net (Phase 1; native-only, `--features bridge`).
//!
//! Plays full games with the current HARD bot and dumps one CSV row per DECISION POINT:
//! `game_id, seat, <N_FEATS features>, outcome`. The label is the game's eventual result
//! from THAT row's mover seat (+1 win / -1 loss), so an outcome-trained net can learn the
//! long-horizon value the static leaf (`value.rs`) misses. Phase 2 trains on this; the
//! encoder (`feats.rs`) is the one source of truth and this writes its column names verbatim.
//!
//! WHY THE KNOBS MATTER:
//!   * `--sims` (default 400) — near the measured heuristic plateau, so the games are as
//!     well-played as the bot gets. Iteration-bounded (clock free), so a busy box can't
//!     silently weaken play and skew the labels.
//!   * `--temp-plies`/`--temp` — WITHOUT opening temperature every game is nearly identical
//!     (greedy self-play is deterministic given the deal) and the data is worthless. The
//!     first `temp-plies` decisions sample softmax-over-Q; the rest are greedy.
//!   * game seed = `--seed` XOR-mixed with the game index, so a run is fully reproducible and
//!     two games never share a stream.
//!
//! SANITY CHECK (printed): the Pearson correlation between the heuristic-baseline feature
//! (`F_value`, the last column) and the outcome label MUST be clearly positive — that is the
//! end-to-end proof the encoder AND the labeling are wired right (the heuristic predicts the
//! winner). A ~0 or negative number means something is broken, and the run says so loudly.
//!
//!     cargo run --release --features bridge --bin harvest_value -- \
//!         --games 200 --sims 400 --out /tmp/duel_harvest.csv

use std::io::{BufWriter, Write};

use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::clock::Clock;
use duel_core::engine::{State, EMPTY, N_CELLS};
use duel_core::feats::{feature_names, features, N_FEATS};
use duel_core::mcts::{choose_move, Opts, RngShuffler};
use duel_core::rng::Rng;

/// Deal a fresh game with `rng` — a faithful structural copy of `engine.py::new_game`
/// (shuffle each level's deck, deal the pyramid off the top, spiral-fill the board from the
/// 25-token bag, grant the second player the setup privilege). It does NOT need bit-parity
/// with Python's shuffle: self-play only needs a legal, seed-varied opening, and the parity
/// gate already pins the RULES that play it out.
fn new_game(rng: &mut Rng) -> State {
    // Level card-id ranges: L1 0..29, L2 30..53, L3 54..66.
    let mut decks: [Vec<usize>; 3] = [(0..30).collect(), (30..54).collect(), (54..67).collect()];
    let pyramid_sizes = [5usize, 4, 3];
    let mut pyramid: [Vec<i32>; 3] = [Vec::new(), Vec::new(), Vec::new()];
    for lvl in 0..3 {
        rng.shuffle(&mut decks[lvl]);
        for _ in 0..pyramid_sizes[lvl] {
            // Pop off the END, as the engine draws — order is randomized anyway.
            pyramid[lvl].push(decks[lvl].pop().unwrap() as i32);
        }
    }

    // Initial board fill: shuffle the 25-token bag and lay it down the spiral. 25 tokens fill
    // all 25 cells exactly, leaving the bag empty (as at a real game start).
    let mut bag: Vec<u8> = TOKEN_BAG.to_vec();
    rng.shuffle(&mut bag);
    let mut board = [EMPTY; N_CELLS];
    for &idx in SPIRAL_ORDER.iter() {
        if bag.is_empty() {
            break;
        }
        if board[idx] == EMPTY {
            board[idx] = bag.pop().unwrap() as i8;
        }
    }

    // Setup rule: the opponent of the first player starts with 1 privilege, drawn from the
    // 3-token board pool (so the pool is left at 2). Seat 0 moves first (from_setup sets turn=0).
    State::from_setup(board, bag, decks, pyramid, 2, vec![0, 1, 2, 3], [0, 1])
}

/// One harvested row: features + the seat that was about to move + the game's outcome for it.
struct Row {
    game_id: u64,
    seat: usize,
    feats: Vec<f32>,
    outcome: f32,
}

/// Play one game to a terminal, recording every decision. Returns the labeled rows, or an
/// empty vec if the game failed to terminate (pathological — discarded, never mislabeled).
fn play_game(game_id: u64, sims: u64, temp_plies: usize, temp: f64, seed: u64, cap: usize) -> Vec<Row> {
    let mut rng = Rng::new(seed);
    let mut st = new_game(&mut rng);
    let mut pending_rows: Vec<(usize, Vec<f32>)> = Vec::new();
    let mut ply = 0usize;

    loop {
        if st.is_over() {
            break;
        }
        if ply >= cap {
            return Vec::new(); // never terminated: discard rather than label a truncation as a result
        }
        // The mover is the pending decider if one is open, else the turn player.
        let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
        pending_rows.push((mover, features(&st, mover)));

        // Opening diversity: sample the first `temp-plies` decisions, then play greedy.
        let temperature = if ply < temp_plies { Some(temp) } else { None };
        let opts = Opts {
            max_iters: Some(sims),
            time_limit: Some(f64::INFINITY), // iteration-bounded: reproducible, load-independent
            temperature,
            ..Default::default()
        };
        let mv = match choose_move(&st, mover, "hard", &opts, &mut rng) {
            Some(m) => m,
            None => break, // no legal move — should be unreachable (Pass fallback)
        };
        let mut sh = RngShuffler { rng: &mut rng };
        if st.apply_move(mover, &mv, &mut sh).is_err() {
            break;
        }
        ply += 1;
    }

    if !st.is_over() {
        return Vec::new(); // ended without a winner (broke out early) — discard
    }
    let winner = st.winner;
    pending_rows
        .into_iter()
        .map(|(seat, feats)| Row {
            game_id,
            seat,
            feats,
            outcome: if winner == seat as i32 { 1.0 } else { -1.0 },
        })
        .collect()
}

/// Running accumulators for the Pearson correlation between the value-baseline column and
/// the outcome, plus a global feature min/max/mean (a cheap encoder-health readout).
#[derive(Default)]
struct Stats {
    n: f64,
    sx: f64,
    sy: f64,
    sxx: f64,
    syy: f64,
    sxy: f64,
    fmin: f64,
    fmax: f64,
    fsum: f64,
    fcount: f64,
}

impl Stats {
    fn new() -> Self {
        Stats { fmin: f64::INFINITY, fmax: f64::NEG_INFINITY, ..Default::default() }
    }
    fn add_row(&mut self, feats: &[f32], outcome: f32) {
        let x = feats[N_FEATS - 1] as f64; // F_value baseline
        let y = outcome as f64;
        self.n += 1.0;
        self.sx += x;
        self.sy += y;
        self.sxx += x * x;
        self.syy += y * y;
        self.sxy += x * y;
        for &v in feats {
            let v = v as f64;
            if v < self.fmin {
                self.fmin = v;
            }
            if v > self.fmax {
                self.fmax = v;
            }
            self.fsum += v;
            self.fcount += 1.0;
        }
    }
    fn correlation(&self) -> f64 {
        let cov = self.n * self.sxy - self.sx * self.sy;
        let vx = self.n * self.sxx - self.sx * self.sx;
        let vy = self.n * self.syy - self.sy * self.sy;
        let denom = (vx * vy).sqrt();
        if denom == 0.0 {
            0.0
        } else {
            cov / denom
        }
    }
}

struct Args {
    games: u64,
    sims: u64,
    temp_plies: usize,
    temp: f64,
    seed: u64,
    out: String,
    cap: usize,
}

fn parse_args() -> Args {
    let mut a = Args {
        games: 200,
        sims: 400,
        temp_plies: 12,
        temp: 0.5,
        seed: 0,
        out: "duel_harvest.csv".to_string(),
        cap: 600, // hard ceiling on decisions/game; a well-played Duel game ends far sooner
    };
    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        let key = argv[i].as_str();
        let mut next = || {
            i += 1;
            argv.get(i).cloned().unwrap_or_else(|| panic!("missing value for {}", key))
        };
        match key {
            "--games" => a.games = next().parse().expect("--games N"),
            "--sims" => a.sims = next().parse().expect("--sims S"),
            "--temp-plies" => a.temp_plies = next().parse().expect("--temp-plies P"),
            "--temp" => a.temp = next().parse().expect("--temp T"),
            "--seed" => a.seed = next().parse().expect("--seed K"),
            "--out" => a.out = next(),
            "--cap" => a.cap = next().parse().expect("--cap N"),
            other => panic!("unknown arg: {}", other),
        }
        i += 1;
    }
    a
}

fn main() {
    let args = parse_args();
    let names = feature_names();
    assert_eq!(names.len(), N_FEATS, "feature_names / N_FEATS mismatch");

    let file = std::fs::File::create(&args.out).expect("create --out file");
    let mut w = BufWriter::new(file);
    // Header: the encoder owns the column names, so training reads the layout straight off it.
    write!(w, "game_id,seat").unwrap();
    for name in &names {
        write!(w, ",{}", name).unwrap();
    }
    writeln!(w, ",outcome").unwrap();

    let mut stats = Stats::new();
    let mut total_rows: u64 = 0;
    let mut terminated_games: u64 = 0;
    let mut discarded_games: u64 = 0;
    let clock = Clock::start();

    // Reuse one line buffer to keep the hot loop allocation-light.
    let mut line = String::with_capacity(16 + N_FEATS * 10);

    for g in 0..args.games {
        // Mix the base seed with the game index so every game has an independent, reproducible
        // stream (splitmix constant; the first shuffle mixes it thoroughly regardless).
        let gseed = args.seed ^ (g.wrapping_mul(0x9E37_79B9_7F4A_7C15));
        let rows = play_game(g, args.sims, args.temp_plies, args.temp, gseed, args.cap);
        if rows.is_empty() {
            discarded_games += 1;
            continue;
        }
        terminated_games += 1;
        for row in &rows {
            stats.add_row(&row.feats, row.outcome);
            line.clear();
            use std::fmt::Write as _;
            let _ = write!(line, "{},{}", row.game_id, row.seat);
            for &v in &row.feats {
                let _ = write!(line, ",{}", v);
            }
            let _ = write!(line, ",{}", row.outcome);
            writeln!(w, "{}", line).unwrap();
            total_rows += 1;
        }
        w.flush().unwrap(); // flush per game (the spec's requirement)
    }
    w.flush().unwrap();

    let elapsed = clock.elapsed_secs().max(1e-9);
    let corr = stats.correlation();
    let fmean = if stats.fcount > 0.0 { stats.fsum / stats.fcount } else { 0.0 };

    eprintln!("── harvest complete ──");
    eprintln!("out                : {}", args.out);
    eprintln!("N_FEATS            : {}", N_FEATS);
    eprintln!("games (played)     : {}", args.games);
    eprintln!("games (terminated) : {}", terminated_games);
    eprintln!("games (discarded)  : {}", discarded_games);
    eprintln!("rows               : {}", total_rows);
    eprintln!("elapsed            : {:.2}s", elapsed);
    eprintln!("throughput         : {:.2} games/s, {:.0} rows/s", args.games as f64 / elapsed, total_rows as f64 / elapsed);
    eprintln!("feature min/max/mean: {:.4} / {:.4} / {:.4}", stats.fmin, stats.fmax, fmean);
    eprintln!("SANITY  corr(F_value, outcome) = {:.4}   (MUST be clearly positive)", corr);
    if corr <= 0.05 {
        eprintln!("!! WARNING: heuristic/outcome correlation is not clearly positive — the encoder");
        eprintln!("!! or the labeling is likely MISWIRED. Do not train on this data.");
    } else {
        eprintln!("OK: the heuristic baseline predicts the winner — encoder + labeling look sound.");
    }
}
