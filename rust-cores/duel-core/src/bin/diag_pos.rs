//! One-off diagnostic: run the AttnVal (netval) search on a single compact projection and
//! dump per-move visits / mean-Q, to see what the deployed client net actually decides.
//!   cargo run --release --features bridge --bin diag_pos -- <proj.json> <net.json> [sims] [seed]
use duel_core::attn::AttnNet;
use duel_core::compact::from_proj;
use duel_core::encmove::enc_move;
use duel_core::mcts::{root_search_with_leaf, Leaf, Opts};
use duel_core::rng::Rng;
use serde_json::Value;

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let proj_path = &a[1];
    let net_path = &a[2];
    let sims: u64 = a.get(3).and_then(|s| s.parse().ok()).unwrap_or(4000);
    let seed: u64 = a.get(4).and_then(|s| s.parse().ok()).unwrap_or(1);
    let dev_tilt: f64 = a.get(5).and_then(|s| s.parse().ok()).unwrap_or(0.0);
    let leaf_blend: f64 = a.get(6).and_then(|s| s.parse().ok()).unwrap_or(0.0);
    let roll: Option<usize> = a.get(7).and_then(|s| s.parse().ok());

    let proj: Value = serde_json::from_str(&std::fs::read_to_string(proj_path).unwrap()).unwrap();
    let (st, seat) = from_proj(&proj).expect("from_proj rejected projection");
    let net = AttnNet::from_json_str(&std::fs::read_to_string(net_path).unwrap()).expect("net parse");

    let opts = Opts { max_iters: Some(sims), time_limit: Some(f64::INFINITY), dev_tilt, leaf_blend, rollout_steps: roll, ..Default::default() };
    let mut rng = Rng::new(seed);
    let stats = root_search_with_leaf(&st, seat, "hard", &opts, Leaf::AttnVal(&net), &mut rng)
        .expect("no stats");
    let total: i64 = stats.n.iter().map(|&x| x as i64).sum();
    let mut idx: Vec<usize> = (0..stats.moves.len()).collect();
    idx.sort_by(|&x, &y| stats.n[y].cmp(&stats.n[x]));
    println!("seat={} sims={} seed={} total_visits={} nmoves={}", seat, sims, seed, total, stats.moves.len());
    for &i in idx.iter().take(16) {
        let q = if stats.n[i] > 0 { stats.w[i] / stats.n[i] as f64 } else { 0.0 };
        let m = serde_json::to_string(&enc_move(&stats.moves[i])).unwrap();
        println!("  v={:6} Q={:+.4}  {}", stats.n[i], q, m);
    }
    println!("GREEDY PICK (top visits): {}", serde_json::to_string(&enc_move(&stats.moves[idx[0]])).unwrap());
}
