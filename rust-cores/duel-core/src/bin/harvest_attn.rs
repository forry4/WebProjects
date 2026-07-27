//! Self-play harvest for the ATTENTION value net (native-only, `--features bridge`). Emits the TOKEN
//! encoding (`feats::features_tokens`) per decision:
//!   `game_id, seat, <TOK_N*TOK_F tokens>, <TOK_N mask>, <TOK_STATE state>, hval, rootval, outcome`.
//! `hval` = the heuristic `value` (corr-with-outcome sanity + a training baseline). Label = the
//! game's eventual result from that row's mover seat (+1/-1).
//!
//! ITERATION: games are played by the SHIPPED ATTENTION NET itself (leaf = AttnVal, embedded
//! `attn_value_net.json`) at a 2-step rollout — gate-verified equal to the 12-step but ~3x faster,
//! and ~5x stronger than the old 400-sim heuristic harvest. This closes the train/inference
//! distribution gap: the net now learns from positions arising from its OWN strong play.
//! Single-threaded on purpose — run one process per core as parallel shards (distinct --seed/--out).
//!
//!   cargo run --release --features bridge --bin harvest_attn -- --games 834 --sims 2000 --seed 0 --out C:/Users/Forrest/duel_run/v3/shard_0.csv

use std::io::{BufWriter, Write};

use duel_core::attn::AttnNet;
use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::clock::Clock;
use duel_core::engine::{State, EMPTY, N_CELLS};
use duel_core::feats::{features_tokens, TOK_F, TOK_N, TOK_STATE};
use duel_core::mcts::{choose_move_and_rootval_with_leaf, Leaf, Opts, RngShuffler};
use duel_core::rng::Rng;
use duel_core::value::value;

static ATTN_NET_JSON: &str = include_str!("../attn_value_net.json");

fn new_game(rng: &mut Rng) -> State {
    let mut decks: [Vec<usize>; 3] = [(0..30).collect(), (30..54).collect(), (54..67).collect()];
    let pyramid_sizes = [5usize, 4, 3];
    let mut pyramid: [Vec<i32>; 3] = [Vec::new(), Vec::new(), Vec::new()];
    for lvl in 0..3 {
        rng.shuffle(&mut decks[lvl]);
        for _ in 0..pyramid_sizes[lvl] {
            pyramid[lvl].push(decks[lvl].pop().unwrap() as i32);
        }
    }
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
    State::from_setup(board, bag, decks, pyramid, 2, vec![0, 1, 2, 3], [0, 1])
}

struct Row {
    game_id: u64,
    seat: usize,
    tokens: Vec<f64>,
    mask: Vec<f64>,
    state: Vec<f64>,
    hval: f64,
    rootval: f64,
    outcome: f32,
}

fn play_game(game_id: u64, sims: u64, temp_plies: usize, temp: f64, seed: u64, cap: usize, a_seat: usize, leaf_a: Leaf, leaf_b: Leaf) -> Vec<Row> {
    let mut rng = Rng::new(seed);
    let mut st = new_game(&mut rng);
    let mut pending: Vec<(usize, Vec<f64>, Vec<f64>, Vec<f64>, f64, f64)> = Vec::new();
    let mut ply = 0usize;
    loop {
        if st.is_over() {
            break;
        }
        if ply >= cap {
            return Vec::new();
        }
        let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
        let (t, m, s) = features_tokens(&st, mover);
        let hval = value(&st, mover);
        let temperature = if ply < temp_plies { Some(temp) } else { None };
        let opts = Opts { max_iters: Some(sims), time_limit: Some(f64::INFINITY), temperature, rollout_steps: Some(2), coherent: true, prior_c: Some(1.0), ..Default::default() };
        let leaf = if mover == a_seat { leaf_a } else { leaf_b };
        // Search THIS position: pick the move AND capture the root value (Σw/Σn) for value-bootstrap.
        let (mv, rootval) = match choose_move_and_rootval_with_leaf(&st, mover, "hard", &opts, leaf, &mut rng) {
            Some(x) => x,
            None => break,
        };
        pending.push((mover, t, m, s, hval, rootval));
        let mut sh = RngShuffler { rng: &mut rng };
        if st.apply_move(mover, &mv, &mut sh).is_err() {
            break;
        }
        ply += 1;
    }
    if !st.is_over() {
        return Vec::new();
    }
    let winner = st.winner;
    pending
        .into_iter()
        .map(|(seat, tokens, mask, state, hval, rootval)| Row {
            game_id,
            seat,
            tokens,
            mask,
            state,
            hval,
            rootval,
            outcome: if winner == seat as i32 { 1.0 } else { -1.0 },
        })
        .collect()
}

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    let mut games: u64 = 3000;
    let mut sims: u64 = 400;
    let mut temp_plies: usize = 12;
    let mut temp: f64 = 0.5;
    let mut seed: u64 = 0;
    let mut out = "attn_harvest.csv".to_string();
    let mut leaf_kind = "attnval".to_string();
    let mut leaf_b_kind = String::new(); // empty -> same as --leaf (self-play)
    let mut attn_file: Option<String> = None; // a net loaded from disk, for the "attnfile" leaf kind
    let mut attn_file_b: Option<String> = None; // a SECOND loaded net, for the "attnfile2" leaf kind
    let cap: usize = 600;
    let mut i = 1;
    while i < argv.len() {
        let k = argv[i].clone();
        let mut next = || {
            i += 1;
            argv.get(i).cloned().unwrap_or_else(|| panic!("missing value for {}", k))
        };
        match k.as_str() {
            "--games" => games = next().parse().unwrap(),
            "--sims" => sims = next().parse().unwrap(),
            "--temp-plies" => temp_plies = next().parse().unwrap(),
            "--temp" => temp = next().parse().unwrap(),
            "--seed" => seed = next().parse().unwrap(),
            "--out" => out = next(),
            "--leaf" => leaf_kind = next(),
            "--leaf-b" => leaf_b_kind = next(),
            "--attn-file" => attn_file = Some(next()),
            "--attn-file-b" => attn_file_b = Some(next()),
            other => panic!("unknown arg: {}", other),
        }
        i += 1;
    }

    let net = AttnNet::from_json_str(ATTN_NET_JSON).expect("load embedded attn_value_net.json");
    let net2 = attn_file.as_ref().map(|p| {
        AttnNet::from_json_str(&std::fs::read_to_string(p).expect("read --attn-file")).expect("parse --attn-file")
    });
    let net3 = attn_file_b.as_ref().map(|p| {
        AttnNet::from_json_str(&std::fs::read_to_string(p).expect("read --attn-file-b")).expect("parse --attn-file-b")
    });
    // Per-seat leaves — self-play when --leaf-b is unset, else a MATCHUP (e.g. v2 vs a loaded developer
    // net: `--leaf attnval --leaf-b attnfile --attn-file dev_net.json`). Seats swap by game parity for
    // first-player balance; every position (both seats) is recorded, labeled by its mover's outcome.
    let mk_leaf = |kind: &str| -> Leaf {
        match kind {
            "attnval" => Leaf::AttnVal(&net),
            "attnfile" => Leaf::AttnVal(net2.as_ref().expect("--attn-file required for attnfile")),
            "attnfile2" => Leaf::AttnVal(net3.as_ref().expect("--attn-file-b required for attnfile2")),
            "heurdev" => Leaf::HeuristicW(&duel_core::value::DEV_WEIGHTS),
            "heur" => Leaf::Heuristic,
            o => panic!("leaf must be attnval|attnfile|attnfile2|heurdev|heur, got {o}"),
        }
    };
    let leaf_a = mk_leaf(&leaf_kind);
    let leaf_b = mk_leaf(if leaf_b_kind.is_empty() { &leaf_kind } else { &leaf_b_kind });

    let file = std::fs::File::create(&out).expect("create out");
    let mut w = BufWriter::new(file);
    write!(w, "game_id,seat").unwrap();
    for i in 0..TOK_N * TOK_F {
        write!(w, ",tok{i}").unwrap();
    }
    for i in 0..TOK_N {
        write!(w, ",mask{i}").unwrap();
    }
    for i in 0..TOK_STATE {
        write!(w, ",st{i}").unwrap();
    }
    writeln!(w, ",hval,rootval,outcome").unwrap();

    let (mut n, mut sx, mut sy, mut sxx, mut syy, mut sxy) = (0f64, 0f64, 0f64, 0f64, 0f64, 0f64);
    let (mut sr, mut srr, mut sry) = (0f64, 0f64, 0f64); // corr(rootval,outcome) accumulators
    let mut rows = 0u64;
    let mut terminated = 0u64;
    let clock = Clock::start();
    let mut line = String::with_capacity(4096);
    for g in 0..games {
        let gseed = seed ^ (g.wrapping_mul(0x9E37_79B9_7F4A_7C15));
        let rs = play_game(g, sims, temp_plies, temp, gseed, cap, (g % 2) as usize, leaf_a, leaf_b);
        if rs.is_empty() {
            continue;
        }
        terminated += 1;
        for r in &rs {
            let (x, y, rv) = (r.hval, r.outcome as f64, r.rootval);
            n += 1.0; sx += x; sy += y; sxx += x * x; syy += y * y; sxy += x * y;
            sr += rv; srr += rv * rv; sry += rv * y;
            line.clear();
            use std::fmt::Write as _;
            let _ = write!(line, "{},{}", r.game_id, r.seat);
            for &v in &r.tokens { let _ = write!(line, ",{v}"); }
            for &v in &r.mask { let _ = write!(line, ",{v}"); }
            for &v in &r.state { let _ = write!(line, ",{v}"); }
            let _ = write!(line, ",{},{},{}", r.hval, r.rootval, r.outcome);
            writeln!(w, "{line}").unwrap();
            rows += 1;
        }
    }
    w.flush().unwrap();
    let corr = {
        let cov = n * sxy - sx * sy;
        let vx = n * sxx - sx * sx;
        let vy = n * syy - sy * sy;
        let d = (vx * vy).sqrt();
        if d == 0.0 { 0.0 } else { cov / d }
    };
    let corr_rv = {
        let cov = n * sry - sr * sy;
        let vx = n * srr - sr * sr;
        let vy = n * syy - sy * sy;
        let d = (vx * vy).sqrt();
        if d == 0.0 { 0.0 } else { cov / d }
    };
    eprintln!("── attn harvest ── out {out}  games(term) {terminated}/{games}  rows {rows}  {:.1}s", clock.elapsed_secs());
    eprintln!("cols: 2 + {}(tok) + {}(mask) + {}(state) + 3  |  SANITY corr(hval,outcome)={:.4} corr(rootval,outcome)={:.4} (both >0; rootval≥hval expected)", TOK_N * TOK_F, TOK_N, TOK_STATE, corr, corr_rv);
}
