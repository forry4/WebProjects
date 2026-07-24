//! Where does the net-leaf time actually go? — the profile that decides whether int8+SIMD
//! is the right lever for closing the 6.9x wall-clock handicap the gate measured.
//!
//! The subtlety: the encoder's Group F feeds the heuristic's OWN output (`value`,
//! `standing`) as features, so every net eval already pays for a heuristic eval PLUS the
//! rest of the encoder PLUS the MLP. int8+SIMD only speeds the MLP matmuls — if the encoder
//! dominates, no amount of matmul tuning closes the gap, and the lever is a cheaper encoder
//! instead. So measure the split before optimizing (the repo lesson: perf intuitions get
//! refuted by measurement).
//!
//! Components timed on realistic mid-game states:
//!   * value::value   — the heuristic leaf (the baseline the net must beat on quality/speed)
//!   * features       — the full 275-d encoder (INCLUDES a value() call via Group F)
//!   * forward        — the MLP given precomputed features (what int8+SIMD would speed)
//!   * eval           — features + forward (the whole net leaf)
//!
//! Run: cargo run --release --features bridge --bin bench_leaf

use std::time::Instant;

use duel_core::engine::State;
use duel_core::feats::{features, N_FEATS};
use duel_core::mcts::{choose_move, Opts, RngShuffler};
use duel_core::rng::Rng;
use duel_core::valuenet::{QuantValueNet, ValueNet};
use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::value;

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

/// Collect realistic mid-game states by playing light self-play games and snapshotting.
fn gather_states(n: usize) -> Vec<(State, usize)> {
    let mut out = Vec::with_capacity(n);
    let mut rng = Rng::new(20260716);
    let mut g = 0u64;
    while out.len() < n {
        let mut st = new_game(&mut rng);
        let mut ply = 0;
        while !st.is_over() && ply < 120 && out.len() < n {
            let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
            if ply >= 4 {
                out.push((st.clone(), mover)); // skip the near-identical openings
            }
            let opts = Opts {
                max_iters: Some(40),
                time_limit: Some(f64::INFINITY),
                temperature: if ply < 10 { Some(0.6) } else { None },
                ..Default::default()
            };
            let mv = match choose_move(&st, mover, "hard", &opts, &mut rng) {
                Some(m) => m,
                None => break,
            };
            let mut sh = RngShuffler { rng: &mut rng };
            if st.apply_move(mover, &mv, &mut sh).is_err() {
                break;
            }
            ply += 1;
        }
        g += 1;
        if g > 100_000 {
            break;
        }
    }
    out
}

fn main() {
    let net = ValueNet::from_json_str(include_str!("../value_net.json")).expect("load net");
    let net8 = QuantValueNet::from_f32(&net); // int8 trunk of the same net (opt-in :net8 leaf)
    let states = gather_states(2000);
    let feats: Vec<Vec<f32>> = states.iter().map(|(s, seat)| features(s, *seat)).collect();
    assert_eq!(feats[0].len(), N_FEATS);
    println!("profiling {} realistic states, N_FEATS={}\n", states.len(), N_FEATS);

    // Enough repetitions that each component runs for a stable interval. black_box via a
    // running xor/sum sink so the optimizer can't elide the work.
    let reps = 400usize;

    let t = Instant::now();
    let mut sink = 0.0f64;
    for _ in 0..reps {
        for (s, seat) in &states {
            sink += value::value(s, *seat);
        }
    }
    let heur_ns = t.elapsed().as_nanos() as f64 / (reps * states.len()) as f64;

    let t = Instant::now();
    let mut fsink = 0.0f32;
    for _ in 0..reps {
        for (s, seat) in &states {
            let f = features(s, *seat);
            fsink += f[0] + f[N_FEATS - 1];
        }
    }
    let feats_ns = t.elapsed().as_nanos() as f64 / (reps * states.len()) as f64;

    // The MLP forward, three ways on the SAME precomputed features:
    //   * forward_serial  — the OLD serial single-accumulator + per-call `vec!` baseline
    //   * forward          — the NEW chunked-`dot` + thread-local-scratch f32 path
    //   * net8.forward     — the int8-quantized-trunk path (VNNI here / i32x4_dot on wasm)
    let t = Instant::now();
    for _ in 0..reps {
        for f in &feats {
            sink += net.forward_serial(f);
        }
    }
    let fwd_serial_ns = t.elapsed().as_nanos() as f64 / (reps * states.len()) as f64;

    let t = Instant::now();
    for _ in 0..reps {
        for f in &feats {
            sink += net.forward(f);
        }
    }
    let fwd_ns = t.elapsed().as_nanos() as f64 / (reps * states.len()) as f64;

    let t = Instant::now();
    for _ in 0..reps {
        for f in &feats {
            sink += net8.forward(f);
        }
    }
    let fwd_i8_ns = t.elapsed().as_nanos() as f64 / (reps * states.len()) as f64;

    // Isolate the per-call allocation cost the no-alloc rewrite removes, to attribute the
    // serial->chunked win between SIMD and de-alloc: `forward_serial` did 4 `vec![]` per call
    // (z-score 275 + layer outputs 256/256/1). Timing just those allocations (black_box'd so
    // they can't be elided) estimates the de-alloc share; the remainder is the SIMD `dot`.
    let t = Instant::now();
    let mut asink = 0usize;
    for _ in 0..reps {
        for _ in &feats {
            let z = std::hint::black_box(vec![0.0f32; 275]);
            let a = std::hint::black_box(vec![0.0f32; 256]);
            let b = std::hint::black_box(vec![0.0f32; 256]);
            let c = std::hint::black_box(vec![0.0f32; 1]);
            asink += z.len() + a.len() + b.len() + c.len();
        }
    }
    std::hint::black_box(asink); // anti-DCE: keep the allocations from being optimized away
    let alloc_ns = t.elapsed().as_nanos() as f64 / (reps * states.len()) as f64;

    let t = Instant::now();
    for _ in 0..reps {
        for (s, seat) in &states {
            sink += net.eval(s, *seat);
        }
    }
    let eval_ns = t.elapsed().as_nanos() as f64 / (reps * states.len()) as f64;

    // Implied single-thread throughput (forward-only), so the matvec win reads directly.
    let sps = |ns: f64| 1e9 / ns;
    println!("  {:<26} {:>8.1} ns/call", "value::value (heuristic)", heur_ns);
    println!("  {:<26} {:>8.1} ns/call   (incl. a value() via Group F)", "features (encoder)", feats_ns);
    println!();
    println!("  -- MLP forward (the matvec int8+SIMD speeds) --");
    println!("  {:<26} {:>8.1} ns/call   {:>9.0}/s   (OLD: serial + per-call vec!)", "forward_serial (f32)", fwd_serial_ns, sps(fwd_serial_ns));
    println!("  {:<26} {:>8.1} ns/call   {:>9.0}/s   (NEW: chunked dot + no-alloc)", "forward (f32)", fwd_ns, sps(fwd_ns));
    println!("  {:<26} {:>8.1} ns/call   {:>9.0}/s   (int8 trunk; VNNI here / i32x4_dot on wasm)", "forward (int8)", fwd_i8_ns, sps(fwd_i8_ns));
    println!("    f32 speedup (serial -> chunked+no-alloc) = {:.2}x", fwd_serial_ns / fwd_ns);
    println!("    int8 vs chunked-f32                       = {:.2}x", fwd_ns / fwd_i8_ns);
    // Attribution: of the (serial - chunked) ns saved, ~alloc_ns is the 4 vec![] removed;
    // the rest is the SIMD dot. On this net the matvec dominates, so SIMD is the big lever.
    let saved = fwd_serial_ns - fwd_ns;
    println!(
        "    of the {:.0} ns saved: ~{:.0} ns de-alloc ({:.0}%), ~{:.0} ns SIMD dot ({:.0}%)",
        saved, alloc_ns, 100.0 * alloc_ns / saved, saved - alloc_ns, 100.0 * (saved - alloc_ns) / saved
    );
    println!();
    println!("  {:<26} {:>8.1} ns/call", "eval (features+forward)", eval_ns);
    println!("  net eval / heuristic         = {:.1}x", eval_ns / heur_ns);
    println!("  MLP forward share of eval    = {:.0}%", 100.0 * fwd_ns / eval_ns);
    println!("  encoder share of eval        = {:.0}%", 100.0 * feats_ns / eval_ns);
    // If the MLP were free, eval -> ~features; that caps the achievable eval speedup.
    println!("  max eval speedup if MLP free = {:.2}x  (eval/features)", eval_ns / feats_ns);
    // The leaf comparison is vs the heuristic leaf, which ALSO rolls out ~12 steps in Hard;
    // this ratio is just the static-eval part. The gate's 6.9x is the whole per-sim cost.
    println!("\n  (sink {:.3} {:.3} — anti-DCE)", sink, fsink);
}
