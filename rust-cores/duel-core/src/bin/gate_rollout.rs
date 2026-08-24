//! Rollout-length gate for the attention netval leaf. Both sides use the SAME net + SAME sims; they
//! differ ONLY in `rollout_steps`. The shipped leaf plays a 12-step rollout before evaluating the
//! net, and the microbench shows that rollout is ~70% of a sim — so if a 0-step (direct) or short
//! rollout is as good an EVALUATOR, dropping it is a ~3x sims/s win (and, per Spender's
//! static-beats-rollout finding for Splendor-like games, maybe a stronger leaf outright).
//!
//! Equal-SIMS isolates eval quality: `>0.5` for the shorter side = it is a BETTER evaluator per sim;
//! `~0.5` = the rollout adds nothing, so at EQUAL TIME the ~3x-faster short leaf wins in a landslide.
//! CRN seat-swapped, greedy, mirror sanity (12 vs 12 must read 0.5000).
//!
//!   cargo run --release --features bridge --bin gate_rollout -- --sims 2000 --games 80

use duel_core::attn::AttnNet;
use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::engine::{Move, State, EMPTY, N_CELLS};
use duel_core::mcts::{choose_move_with_leaf, Leaf, Opts, RngShuffler};
use duel_core::rng::Rng;

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

fn agent_move(st: &State, mover: usize, net: &AttnNet, sims: u64, steps: usize, dseed: u64) -> Option<Move> {
    let opts = Opts {
        max_iters: Some(sims),
        time_limit: Some(f64::INFINITY),
        temperature: None, // greedy
        rollout_steps: Some(steps),
        ..Default::default()
    };
    let mut rng = Rng::new(dseed ^ 0x4D43_5453);
    choose_move_with_leaf(st, mover, "hard", &opts, Leaf::AttnVal(net), &mut rng)
}

/// Agent A (seat `a_seat`) uses `roll_a` rollout steps; B uses `roll_b`. Same `net`, same `sims`.
fn play(gseed: u64, a_seat: usize, net: &AttnNet, sims: u64, roll_a: usize, roll_b: usize, cap: usize) -> f64 {
    let mut setup = Rng::new(mix(gseed, 0x5E7));
    let mut st = new_game(&mut setup);
    let mut game_rng = Rng::new(mix(gseed, 0x6A3E));
    let mut ply = 0usize;
    while !st.is_over() && ply < cap {
        let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
        let steps = if mover == a_seat { roll_a } else { roll_b };
        let dseed = mix(mix(gseed, mover as u64), ply as u64);
        let mv = match agent_move(&st, mover, net, sims, steps, dseed) {
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

fn run_match(net: &AttnNet, sims: u64, roll_a: usize, roll_b: usize, games: u64, seed0: u64, cap: usize) -> (f64, u64) {
    use std::sync::atomic::{AtomicU64, Ordering};
    let nthreads = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4);
    let next = AtomicU64::new(0);
    let total = std::sync::Mutex::new(0.0f64);
    std::thread::scope(|sc| {
        for _ in 0..nthreads {
            sc.spawn(|| {
                let mut local = 0.0f64;
                loop {
                    let g = next.fetch_add(1, Ordering::Relaxed);
                    if g >= games {
                        break;
                    }
                    local += play(seed0 + g, 0, net, sims, roll_a, roll_b, cap);
                    local += play(seed0 + g, 1, net, sims, roll_a, roll_b, cap);
                }
                *total.lock().unwrap() += local;
            });
        }
    });
    let t = *total.lock().unwrap();
    (t / (games * 2) as f64, games * 2)
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
    let mut games: u64 = 80;
    let mut sims: u64 = 2000;
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
            "--sims" => sims = next().parse().unwrap(),
            "--seed" => seed0 = next().parse().unwrap(),
            other => panic!("unknown arg: {}", other),
        }
        i += 1;
    }
    let net = AttnNet::from_json_str(ATTN_NET_JSON).expect("load attn_value_net.json");

    let (m, mn) = run_match(&net, sims, 12, 12, 8, seed0, cap);
    println!("[mirror] roll 12 vs 12 @ {sims} : {m:.4} (n={mn}) — must be 0.5000");
    println!("ROLLOUT GATE @ {sims} sims (side A = short rollout; >0.5 = short is a BETTER per-sim evaluator):");
    for roll_a in [2usize, 3] {
        let (r, n) = run_match(&net, sims, roll_a, 12, games, seed0, cap);
        let (lo, hi) = wilson(r, n);
        println!("  roll={roll_a:>2} vs roll=12 : {r:.4} [{lo:.3}, {hi:.3}] (n={n})");
    }
}
