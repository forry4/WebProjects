//! Self-play harvest for the ATTENTION value net WITH AUXILIARY TARGETS (native-only, `--features
//! bridge`). Identical to `harvest_attn` but appends four GAME-FINAL aux targets per row, from that
//! row's mover seat: `card_margin, crown_margin, win_cond, game_len`. The aux heads are TRAINING-ONLY
//! (they regularize the shared trunk so the value head better "understands" development — the
//! diagnosed under-development blind spot); only the value path is exported, so `attn.rs`/serving are
//! unchanged. Row schema:
//!   `game_id, seat, <TOK_N*TOK_F tokens>, <TOK_N mask>, <TOK_STATE state>, hval, outcome,
//!    card_margin, crown_margin, win_cond, game_len`
//! Plays with the SHIPPED attention net (leaf = AttnVal, 2-step rollout). Single-threaded — run one
//! process per core as parallel shards. Per the low-scan methodology, harvest at LOWER sims for speed.
//!
//!   cargo run --release --features bridge --bin harvest_aux -- --games 1000 --sims 700 --seed 0 --out C:/Users/Forrest/duel_run/aux/shard_0.csv

use std::io::{BufWriter, Write};

use duel_core::attn::AttnNet;
use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::clock::Clock;
use duel_core::engine::{crowns_of, State, EMPTY, N_CELLS};
use duel_core::feats::{features_tokens, TOK_F, TOK_N, TOK_STATE};
use duel_core::mcts::{choose_move_with_leaf, Leaf, Opts, RngShuffler};
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
    outcome: f32,
    // Game-final aux targets, from `seat`'s perspective (RAW; the trainer normalizes).
    card_margin: f64,  // my purchased cards − opp's
    crown_margin: f64, // my crowns − opp's
    win_cond: f64,     // 1=points, 2=crowns, 3=color (engine encoding)
    game_len: f64,     // final turn number
}

fn play_game(game_id: u64, sims: u64, temp_plies: usize, temp: f64, seed: u64, cap: usize, net: &AttnNet) -> Vec<Row> {
    let mut rng = Rng::new(seed);
    let mut st = new_game(&mut rng);
    let mut pending: Vec<(usize, Vec<f64>, Vec<f64>, Vec<f64>, f64)> = Vec::new();
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
        pending.push((mover, t, m, s, value(&st, mover)));
        let temperature = if ply < temp_plies { Some(temp) } else { None };
        let opts = Opts { max_iters: Some(sims), time_limit: Some(f64::INFINITY), temperature, rollout_steps: Some(2), ..Default::default() };
        let mv = match choose_move_with_leaf(&st, mover, "hard", &opts, Leaf::AttnVal(net), &mut rng) {
            Some(m) => m,
            None => break,
        };
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
    // Game-final aux quantities (computed once; per-row values take the seat's perspective).
    let cards = [st.players[0].purchased.len() as i32, st.players[1].purchased.len() as i32];
    let crowns = [crowns_of(&st.players[0]), crowns_of(&st.players[1])];
    let win_cond = st.win_condition as f64;
    let game_len = st.turn_number as f64;
    pending
        .into_iter()
        .map(|(seat, tokens, mask, state, hval)| Row {
            game_id,
            seat,
            tokens,
            mask,
            state,
            hval,
            outcome: if winner == seat as i32 { 1.0 } else { -1.0 },
            card_margin: (cards[seat] - cards[1 - seat]) as f64,
            crown_margin: (crowns[seat] - crowns[1 - seat]) as f64,
            win_cond,
            game_len,
        })
        .collect()
}

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    let mut games: u64 = 1000;
    let mut sims: u64 = 700;
    let mut temp_plies: usize = 12;
    let mut temp: f64 = 0.5;
    let mut seed: u64 = 0;
    let mut out = "aux_harvest.csv".to_string();
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
            other => panic!("unknown arg: {}", other),
        }
        i += 1;
    }

    let net = AttnNet::from_json_str(ATTN_NET_JSON).expect("load embedded attn_value_net.json");

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
    writeln!(w, ",hval,outcome,card_margin,crown_margin,win_cond,game_len").unwrap();

    let mut rows = 0u64;
    let mut terminated = 0u64;
    let clock = Clock::start();
    let mut line = String::with_capacity(4096);
    for g in 0..games {
        let gseed = seed ^ (g.wrapping_mul(0x9E37_79B9_7F4A_7C15));
        let rs = play_game(g, sims, temp_plies, temp, gseed, cap, &net);
        if rs.is_empty() {
            continue;
        }
        terminated += 1;
        for r in &rs {
            line.clear();
            use std::fmt::Write as _;
            let _ = write!(line, "{},{}", r.game_id, r.seat);
            for &v in &r.tokens { let _ = write!(line, ",{v}"); }
            for &v in &r.mask { let _ = write!(line, ",{v}"); }
            for &v in &r.state { let _ = write!(line, ",{v}"); }
            let _ = write!(line, ",{},{},{},{},{},{}", r.hval, r.outcome, r.card_margin, r.crown_margin, r.win_cond, r.game_len);
            writeln!(w, "{line}").unwrap();
            rows += 1;
        }
    }
    w.flush().unwrap();
    eprintln!("── aux harvest ── out {out}  games(term) {terminated}/{games}  rows {rows}  {:.1}s", clock.elapsed_secs());
    eprintln!("cols: 2 + {}(tok) + {}(mask) + {}(state) + hval,outcome + 4 aux (card_margin,crown_margin,win_cond,game_len)", TOK_N * TOK_F, TOK_N, TOK_STATE);
}
