//! Where do the SERVING sims go? — throughput decomposition of the shipped Expert config.
//!
//! Prompted by a live observation (2026-07-27): the browser pools only ~7k sims in its 3.5s
//! budget (~500 sims/s/core at the 4-worker cap), well under the ~1420 sims/s/core benched
//! before the policy head existed. Two costs were added/never-measured at serving:
//!   * the AZ POLICY PRIOR — `node_priors` runs a policy forward pass at EVERY node expansion,
//!   * the 12-step leaf ROLLOUT — tuned in the per-sim era (harvest already runs 2).
//! Both are strength levers, so the question is not "make it fast" but "which cost buys the
//! least strength per sim it destroys". Measure the split before optimizing (the repo lesson:
//! perf intuitions get refuted by measurement).
//!
//! Reports sims/s for the shipped config and for each cost removed, single-threaded (one
//! worker's-eye view — the browser runs one of these per core).
//!
//! Run: cargo run --release --features bridge --bin bench_serving [sims_per_position]

use std::time::Instant;

use duel_core::attn::AttnNet;
use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::engine::State;
use duel_core::mcts::{root_search_with_leaf, Leaf, Opts, RngShuffler};
use duel_core::rng::Rng;

const N_CELLS: usize = 25;
const EMPTY: i8 = -1;

fn new_game(rng: &mut Rng) -> State {
    let mut decks: [Vec<usize>; 3] = [(0..30).collect(), (30..54).collect(), (54..67).collect()];
    let sizes = [5usize, 4, 3];
    let mut pyramid: [Vec<i32>; 3] = [Vec::new(), Vec::new(), Vec::new()];
    for lvl in 0..3 {
        rng.shuffle(&mut decks[lvl]);
        for _ in 0..sizes[lvl] {
            pyramid[lvl].push(decks[lvl].pop().unwrap() as i32);
        }
    }
    let mut bag: Vec<u8> = TOKEN_BAG.to_vec();
    rng.shuffle(&mut bag);
    let mut board = [EMPTY; N_CELLS];
    for &c in SPIRAL_ORDER.iter() {
        if let Some(t) = bag.pop() {
            board[c as usize] = t as i8;
        }
    }
    State::from_setup(board, bag, decks, pyramid, 2, vec![0, 1, 2, 3], [0, 1])
}

/// Play `plies` random-ish moves so the bench runs on realistic MID-GAME states (an opening
/// position has a smaller tree and a cheaper encoder than what serving actually faces).
fn advance(st: &mut State, rng: &mut Rng, plies: usize) {
    let opts = Opts { max_iters: Some(60), time_limit: Some(f64::INFINITY), ..Default::default() };
    for _ in 0..plies {
        if st.is_over() {
            break;
        }
        let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
        let mv = match duel_core::mcts::choose_move(st, mover, "hard", &opts, rng) {
            Some(m) => m,
            None => break,
        };
        let mut sh = RngShuffler { rng };
        if st.apply_move(mover, &mv, &mut sh).is_err() {
            break;
        }
    }
}

fn bench(label: &str, states: &[State], sims: u64, net: &AttnNet, opts_of: impl Fn() -> Opts) -> f64 {
    let mut rng = Rng::new(0xBEEF);
    let t0 = Instant::now();
    let mut total = 0u64;
    for st in states {
        let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
        let opts = opts_of();
        if let Some(s) = root_search_with_leaf(st, mover, "hard", &opts, Leaf::AttnVal(net), &mut rng) {
            total += s.n.iter().map(|&x| x as u64).sum::<u64>();
        }
    }
    let secs = t0.elapsed().as_secs_f64();
    let rate = total as f64 / secs;
    println!("  {label:<44} {rate:>8.0} sims/s   ({total} sims / {secs:.2}s)");
    let _ = sims;
    rate
}

fn main() {
    let sims: u64 = std::env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(1500);
    let net_path = concat!(env!("CARGO_MANIFEST_DIR"), "/src/attn_expert_net.json");
    let net = AttnNet::from_json_str(&std::fs::read_to_string(net_path).expect("read expert net"))
        .expect("parse expert net");

    // 12 realistic mid-game positions (varied depth so the mix isn't one game phase).
    let mut states = Vec::new();
    for g in 0..12u64 {
        let mut rng = Rng::new(0xA11CE ^ g.wrapping_mul(0x9E3779B9));
        let mut st = new_game(&mut rng);
        advance(&mut st, &mut rng, 8 + (g as usize % 3) * 8);
        if !st.is_over() {
            states.push(st);
        }
    }
    println!("bench_serving: {} positions x {} sims, single-threaded (one worker's view)", states.len(), sims);
    println!("NOTE: run on an IDLE box — a busy machine deflates every row (ratios survive, absolutes don't).\n");

    let base = |mm: bool, prior: Option<f64>, roll: Option<usize>| {
        move || Opts {
            max_iters: Some(sims),
            time_limit: Some(f64::INFINITY),
            coherent: true,
            prior_c: Some(1.0),
            minimax: mm,
            net_policy_temp: prior,
            rollout_steps: roll,
            ..Default::default()
        }
    };

    println!("SHIPPED config and each cost removed:");
    let shipped = bench("shipped (minimax + prior@2.0 + rollout 12)", &states, sims, &net, base(true, Some(2.0), None));
    let no_prior = bench("  - prior            (minimax, rollout 12)", &states, sims, &net, base(true, None, None));
    let roll2 = bench("  - rollout->2       (minimax + prior)", &states, sims, &net, base(true, Some(2.0), Some(2)));
    let roll0 = bench("  - rollout->0       (minimax + prior)", &states, sims, &net, base(true, Some(2.0), Some(0)));
    let neither = bench("  - both             (minimax, rollout 2)", &states, sims, &net, base(true, None, Some(2)));
    let no_mm = bench("  - minimax          (prior, rollout 12)", &states, sims, &net, base(false, Some(2.0), None));

    println!("\nCOST SHARE (x = throughput multiplier vs shipped):");
    for (label, rate) in [
        ("drop prior", no_prior), ("rollout 12->2", roll2), ("rollout 12->0", roll0),
        ("drop prior + rollout 2", neither), ("drop minimax", no_mm),
    ] {
        println!("  {label:<26} {:.2}x   ({:+.0} sims/s)", rate / shipped, rate - shipped);
    }
    println!("\nEach row is a SPEED number only — pair it with the matching strength gate\n\
              (hp_sweep E4 for rollout, G2/G6 for the prior) before changing what serves.");
}
