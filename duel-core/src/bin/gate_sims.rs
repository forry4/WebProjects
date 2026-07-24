//! Sims-saturation ladder for the SHIPPED ATTENTION-NET leaf (Duel Hard). Both agents use the
//! same attention value-net leaf (`attn_value_net.json`); they differ ONLY in sim budget. CRN
//! seat-swapped, greedy. A "doubling ladder" (net@N vs net@2N) answers "where does more search
//! stop paying off": `>0.5` for the high-sims side = doubling still helps there; `~0.5` = the net
//! is saturated by the lower budget.
//!
//! The old "~6k" figure was measured on the HEURISTIC leaf — a better evaluator can move the knee,
//! so this re-measures it on the net we actually ship.
//!
//!   cargo run --release --features bridge --bin gate_sims -- --ladder --games 240
//!   cargo run --release --features bridge --bin gate_sims -- --sims-a 4000 --sims-b 2000 --games 300

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

fn agent_move(st: &State, mover: usize, net: &AttnNet, sims: u64, dseed: u64) -> Option<Move> {
    let opts = Opts {
        max_iters: Some(sims),
        time_limit: Some(f64::INFINITY),
        temperature: None, // greedy
        ..Default::default()
    };
    let mut rng = Rng::new(dseed ^ 0x4D43_5453);
    choose_move_with_leaf(st, mover, "hard", &opts, Leaf::AttnVal(net), &mut rng)
}

/// Agent A (in seat `a_seat`) uses `sims_a`; agent B uses `sims_b`. Both use `net`. Returns A's score.
fn play(gseed: u64, a_seat: usize, net: &AttnNet, sims_a: u64, sims_b: u64, cap: usize) -> f64 {
    let mut setup = Rng::new(mix(gseed, 0x5E7));
    let mut st = new_game(&mut setup);
    let mut game_rng = Rng::new(mix(gseed, 0x6A3E));
    let mut ply = 0usize;
    while !st.is_over() && ply < cap {
        let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
        let sims = if mover == a_seat { sims_a } else { sims_b };
        let dseed = mix(mix(gseed, mover as u64), ply as u64);
        let mv = match agent_move(&st, mover, net, sims, dseed) {
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

/// Multi-threaded: games are independent + deterministic, so a shared work counter reproduces the
/// sequential result while saturating every core (the attention leaf is heavy).
fn run_match(net: &AttnNet, sims_a: u64, sims_b: u64, games: u64, seed0: u64, cap: usize) -> (f64, u64) {
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
                    local += play(seed0 + g, 0, net, sims_a, sims_b, cap);
                    local += play(seed0 + g, 1, net, sims_a, sims_b, cap);
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
    let mut games: u64 = 300;
    let mut sims_a: u64 = 2000;
    let mut sims_b: u64 = 1000;
    let mut seed0: u64 = 70_000;
    let mut ladder = false;
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
            "--sims-a" => sims_a = next().parse().unwrap(),
            "--sims-b" => sims_b = next().parse().unwrap(),
            "--seed" => seed0 = next().parse().unwrap(),
            "--ladder" => ladder = true,
            other => panic!("unknown arg: {}", other),
        }
        i += 1;
    }
    let attn = AttnNet::from_json_str(ATTN_NET_JSON).expect("load attn_value_net.json");

    // Mirror sanity: equal sims must read 0.5000 (identical bots, seat-swapped).
    let (m, mn) = run_match(&attn, 1000, 1000, 8, seed0, cap);
    println!("[mirror] attn 1000 vs 1000 : {m:.4} (n={mn}) — must be 0.5000");

    if ladder {
        // Doubling ladder: net@2N vs net@N. Games taper as sims grow to bound wall-clock; the
        // knee is where the high side falls to ~0.5. Prints incrementally.
        // Netval-leaf self-play is ~100x slower/sim than the heuristic, so n tapers as sims grow
        // to keep the whole ladder ~3h. Low rungs (where the knee is likely) get the most games.
        // If 8k-vs-4k is still clearly >0.5, follow up with a 16k-vs-8k rung.
        let rungs: [(u64, u64, u64); 4] = [
            (1000, 500, games),
            (2000, 1000, games * 4 / 5),
            (4000, 2000, games * 3 / 5),
            (8000, 4000, games / 3),
        ];
        println!("LADDER (attn net; high vs half-sims; >0.5 = doubling still helps):");
        for (a, b, g) in rungs {
            let (r, n) = run_match(&attn, a, b, g, seed0, cap);
            let (lo, hi) = wilson(r, n);
            println!("  {a:>6} vs {b:>5} : {r:.4} [{lo:.3}, {hi:.3}] (n={n})");
        }
    } else {
        let (r, n) = run_match(&attn, sims_a, sims_b, games, seed0, cap);
        let (lo, hi) = wilson(r, n);
        println!("SIMS GATE: attn {sims_a} vs {sims_b} : {r:.4} [{lo:.3}, {hi:.3}] (n={n})");
        println!("  (>0.5 = more sims still helps here; ~0.5 = saturated by {sims_b})");
    }
}
