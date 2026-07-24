//! NATIVE CRN strength gate for the GEOMETRY-aware leaf (`value_geom`) vs the deployed board-blind
//! `value`. Both sides are the SAME hard MCTS at the same sim budget; they differ ONLY in the leaf
//! truncation eval (`Leaf::HeuristicGeom` vs `Leaf::Heuristic`). Fast, all-Rust.
//!
//!   * GATE (geom vs plain, CRN seat-swapped): >0.5 = the geometry term is a real strength gain.
//!   * MIRROR SANITY (plain-vs-plain AND geom-vs-geom, seat-swapped, greedy): must read EXACTLY
//!     0.5000 — identical configs, so each seat-swapped pair sums to 1.
//!   * `--geom-line W` sweeps the line-term multiplier at runtime (no rebuild).
//!
//!     cargo run --release --features bridge --bin gate_geom -- --games 300 --sims 1000 --geom-line 0.4

use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::engine::{Move, State, EMPTY, N_CELLS};
use duel_core::mcts::{choose_move_with_leaf, Leaf, Opts, RngShuffler};
use duel_core::rng::Rng;
use duel_core::value::{set_geom_line, set_geom_mode};

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

#[inline]
fn mix(a: u64, b: u64) -> u64 {
    let mut x = a ^ b.wrapping_mul(0x9E37_79B9_7F4A_7C15);
    x ^= x >> 30;
    x = x.wrapping_mul(0xBF58_476D_1CE4_E5B9);
    x ^= x >> 27;
    x = x.wrapping_mul(0x94D0_49BB_1331_11EB);
    x ^= x >> 31;
    x
}

#[derive(Clone, Copy)]
struct Cfg {
    geom: bool,
}

fn agent_move(st: &State, mover: usize, cfg: Cfg, sims: u64, dseed: u64) -> Option<Move> {
    let leaf = if cfg.geom { Leaf::HeuristicGeom } else { Leaf::Heuristic };
    let opts = Opts {
        max_iters: Some(sims),
        time_limit: Some(f64::INFINITY),
        temperature: None, // hard = greedy
        ..Default::default()
    };
    let mut rng = Rng::new(dseed ^ 0x4D43_5453);
    choose_move_with_leaf(st, mover, "hard", &opts, leaf, &mut rng)
}

fn play(gseed: u64, a_seat: usize, a: Cfg, b: Cfg, sims: u64, cap: usize) -> f64 {
    let mut setup = Rng::new(mix(gseed, 0x5E7));
    let mut st = new_game(&mut setup);
    let mut game_rng = Rng::new(mix(gseed, 0x6A3E));
    let mut ply = 0usize;
    while !st.is_over() && ply < cap {
        let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
        let cfg = if mover == a_seat { a } else { b };
        let dseed = mix(mix(gseed, mover as u64), ply as u64);
        let mv = match agent_move(&st, mover, cfg, sims, dseed) {
            Some(m) => m,
            None => break,
        };
        let mut sh = RngShuffler { rng: &mut game_rng };
        if st.apply_move(mover, &mv, &mut sh).is_err() {
            break;
        }
        ply += 1;
    }
    if !st.is_over() || st.winner < 0 {
        return 0.5;
    }
    if st.winner as usize == a_seat {
        1.0
    } else {
        0.0
    }
}

fn run_match(a: Cfg, b: Cfg, games: u64, seed0: u64, sims: u64, cap: usize) -> (f64, u64) {
    let mut total = 0.0f64;
    let mut n = 0u64;
    for i in 0..games {
        for a_seat in 0..2 {
            total += play(seed0 + i, a_seat, a, b, sims, cap);
            n += 1;
        }
    }
    (total / n as f64, n)
}

fn wilson(p_hat: f64, n: u64) -> (f64, f64) {
    if n == 0 {
        return (0.0, 1.0);
    }
    let z = 1.96f64;
    let n = n as f64;
    let denom = 1.0 + z * z / n;
    let center = p_hat + z * z / (2.0 * n);
    let margin = z * ((p_hat * (1.0 - p_hat) + z * z / (4.0 * n)) / n).sqrt();
    ((center - margin) / denom, (center + margin) / denom)
}

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    let mut games: u64 = 300;
    let mut mirror_games: u64 = 20;
    let mut sims: u64 = 1000;
    let mut geom_line: f64 = 0.05;
    let mut geom_mode: u8 = 1;
    let mut seed0: u64 = 70_000;
    let cap: usize = 400;
    let mut i = 1;
    while i < argv.len() {
        let k = argv[i].clone();
        let mut next = || {
            i += 1;
            argv.get(i).cloned().unwrap_or_else(|| panic!("missing value for {}", k))
        };
        match k.as_str() {
            "--games" => games = next().parse().unwrap(),
            "--mirror-games" => mirror_games = next().parse().unwrap(),
            "--sims" => sims = next().parse().unwrap(),
            "--geom-line" => geom_line = next().parse().unwrap(),
            "--geom-mode" => geom_mode = next().parse().unwrap(),
            "--seed" => seed0 = next().parse().unwrap(),
            other => panic!("unknown arg: {}", other),
        }
        i += 1;
    }
    set_geom_line(geom_line);
    set_geom_mode(geom_mode);
    println!("[config] geom-mode {geom_mode}, geom-line {geom_line}, sims {sims}");
    let plain = Cfg { geom: false };
    let geom = Cfg { geom: true };

    println!("== MIRROR SANITY (seat-swapped, greedy — must read EXACTLY 0.5000) ==");
    let (pm, pn) = run_match(plain, plain, mirror_games, seed0, sims, cap);
    println!("  plain vs plain @ {sims} sims : {pm:.4}  (n={pn})");
    let (gm2, gn2) = run_match(geom, geom, mirror_games, seed0, sims, cap);
    println!("  geom  vs geom  @ {sims} sims : {gm2:.4}  (n={gn2})");

    println!("\n== THE GATE (geom vs plain, {sims} sims, geom-line {geom_line}) ==");
    let (gm, gn) = run_match(geom, plain, games, seed0, sims, cap);
    let (lo, hi) = wilson(gm, gn);
    println!("  geom vs plain : {gm:.4}  [{lo:.3}, {hi:.3}]  (n={gn})");

    println!("\n== VERDICT ==");
    println!("  geom-line {geom_line}, sims {sims}: GEOM {gm:.4} [{lo:.3}, {hi:.3}]");
    println!("  (>0.5 with the interval clear of 0.5 = the geometry-aware leaf is a real gain)");
}
