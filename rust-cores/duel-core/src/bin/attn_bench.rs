//! Micro-profile: how expensive is ONE attention forward vs the rest of a sim? The no-alloc rewrite
//! barely moved end-to-end sims/s, so this splits the leaf cost — pure forward time (this bench) vs
//! the 12-step rollout + tree ops (inferred). Tells us whether SIMD on the matmuls is worth it, or
//! whether the rollout is the real bottleneck.
//!
//!   cargo run --release --features bridge --bin attn_bench

use duel_core::attn::AttnNet;
use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::engine::{State, EMPTY, N_CELLS};
use duel_core::feats::features_tokens;
use duel_core::rng::Rng;
use std::time::Instant;

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

fn main() {
    let net = AttnNet::from_json_str(ATTN_NET_JSON).expect("load net");
    // A handful of real states (varied masks: some seats hold <3 reserves) so the bench isn't a
    // single cache-hot input.
    let mut rng = Rng::new(12345);
    let mut inputs = Vec::new();
    for _ in 0..64 {
        let st = new_game(&mut rng);
        inputs.push(features_tokens(&st, 0));
    }

    // warm up
    let mut acc = 0.0f64;
    for (t, m, s) in &inputs {
        acc += net.value(t, m, s);
    }

    let iters: u64 = 300_000;
    let start = Instant::now();
    let mut idx = 0usize;
    for _ in 0..iters {
        let (t, m, s) = &inputs[idx % inputs.len()];
        acc += net.value(t, m, s);
        idx += 1;
    }
    let el = start.elapsed();
    let ns = el.as_nanos() as f64 / iters as f64;
    println!(
        "{} forwards in {:.2?}  =>  {:.0} ns/forward  |  {:.0} forwards/s/core  (acc {:.3})",
        iters,
        el,
        ns,
        1e9 / ns,
        acc
    );
    println!("For reference, the full attn leaf runs ~670 sims/s/core (each sim = 1 forward + a 12-step rollout + tree ops).");
}
