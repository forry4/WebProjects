//! Where does a SIM actually go? — component decomposition of the search's inner loop.
//!
//! `bench_serving` answers "what do the optional costs cost" (prior 1.05x, rollout 1.02x — both
//! nearly free). It does NOT say where the other ~95% goes, so optimising from it would be
//! guesswork. This bench times the primitives the loop calls per node/leaf, so a speedup can be
//! aimed at the thing that actually dominates.
//!
//! WHY SPEED IS A STRENGTH LEVER HERE, not housekeeping: the 2026-07-31 depth gate measured
//! netB2 @5000 vs @1200 = 0.5967 over 2.06 doublings => ~+0.047 win rate PER DOUBLING of sims.
//! Serving is wall-clock bound (3.5s), so a 2x throughput win is worth about as much as the
//! opp_c ship — and unlike a training change it cannot fail to transfer.
//!
//! Components, each timed in isolation on real mid-game positions:
//!   clone        `State::clone` — the coherent loop clones the determinized world PER SIM
//!   legal        `legal_moves` — allocates a Vec<Move> at every node expansion
//!   feats        `features_tokens` — allocates 3 Vec<f64> per leaf evaluation
//!   value        the attention forward with features ALREADY built (SCRATCH, no alloc)
//!   feats+value  what a leaf evaluation really costs end to end
//!
//! Run: cargo run --release --features bridge --bin bench_hotpath [iters]

use std::time::Instant;

use duel_core::attn::AttnNet;
use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::engine::{State, EMPTY, N_CELLS};
use duel_core::feats::features_tokens;
use duel_core::mcts::{choose_move_with_leaf, Leaf, Opts};
use duel_core::rng::Rng;

static NET_JSON: &str = include_str!("../attn_expert_net.json");

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

/// A handful of real mid-game positions (played out with a cheap search, like bench_serving).
fn positions(net: &AttnNet, n: usize) -> Vec<State> {
    let mut out = Vec::new();
    let mut rng = Rng::new(7);
    for g in 0..n {
        let mut st = new_game(&mut Rng::new(1000 + g as u64));
        let opts = Opts { max_iters: Some(120), time_limit: Some(f64::INFINITY), coherent: true, ..Default::default() };
        for _ in 0..14 {
            if st.is_over() {
                break;
            }
            let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
            match choose_move_with_leaf(&st, mover, "hard", &opts, Leaf::AttnVal(net), &mut rng) {
                Some(mv) => {
                    let mut sh = duel_core::mcts::RngShuffler { rng: &mut rng };
                    if st.apply_move(mover, &mv, &mut sh).is_err() {
                        break;
                    }
                }
                None => break,
            }
        }
        if !st.is_over() {
            out.push(st);
        }
    }
    out
}

fn main() {
    let iters: usize = std::env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(200_000);
    let net = AttnNet::from_json_str(NET_JSON).expect("net");
    let pos = positions(&net, 12);
    println!("bench_hotpath: {} positions, {} iters each component", pos.len(), iters);
    println!("NOTE: idle box only. These are PER-CALL costs; multiply by calls-per-sim to rank them.\n");

    let mover = |st: &State| if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };

    // clone
    let t = Instant::now();
    let mut sink = 0usize;
    for i in 0..iters {
        let c = pos[i % pos.len()].clone();
        sink += c.board.len();
    }
    let clone_ns = t.elapsed().as_nanos() as f64 / iters as f64;

    // legal_moves
    let t = Instant::now();
    for i in 0..iters {
        let st = &pos[i % pos.len()];
        sink += st.legal_moves(mover(st)).len();
    }
    let legal_ns = t.elapsed().as_nanos() as f64 / iters as f64;

    // features_tokens
    let t = Instant::now();
    for i in 0..iters {
        let st = &pos[i % pos.len()];
        let (tk, m, s) = features_tokens(st, mover(st));
        sink += tk.len() + m.len() + s.len();
    }
    let feats_ns = t.elapsed().as_nanos() as f64 / iters as f64;

    // value with features prebuilt
    let pre: Vec<(Vec<f64>, Vec<f64>, Vec<f64>)> = pos.iter().map(|st| features_tokens(st, mover(st))).collect();
    let t = Instant::now();
    let mut acc = 0.0;
    for i in 0..iters {
        let (tk, m, s) = &pre[i % pre.len()];
        acc += net.value(tk, m, s);
    }
    let value_ns = t.elapsed().as_nanos() as f64 / iters as f64;

    // full leaf eval
    let t = Instant::now();
    for i in 0..iters {
        let st = &pos[i % pos.len()];
        acc += net.eval(st, mover(st));
    }
    let leaf_ns = t.elapsed().as_nanos() as f64 / iters as f64;

    println!("  clone        {clone_ns:8.0} ns/call   (coherent loop clones the world once PER SIM)");
    println!("  legal        {legal_ns:8.0} ns/call   (allocates Vec<Move> at every node expansion)");
    println!("  feats        {feats_ns:8.0} ns/call   (allocates 3 Vec<f64> per leaf eval)");
    println!("  value        {value_ns:8.0} ns/call   (attention forward, features prebuilt)");
    println!("  feats+value  {leaf_ns:8.0} ns/call   (`eval` = what a leaf really costs)");
    println!();
    let share = 100.0 * feats_ns / leaf_ns.max(1.0);
    println!("  featurization is {share:.0}% of a leaf evaluation");
    println!("  a sim costs ~1 clone + ~depth legal + 1 leaf; at ~4800 sims/s that is ~{:.0} us/sim",
             1e6 / 4800.0);
    paired_kernel_ab();
    println!("\n(sink {sink}, acc {acc:.3})");
}

/// The 8-lane dot the real kernel uses (copied, so this bench needs no production API changes).
#[inline(always)]
fn dot8(x: &[f32], w: &[f32]) -> f32 {
    let mut acc = [0f32; 8];
    let mut xc = x.chunks_exact(8);
    let mut wc = w.chunks_exact(8);
    for (xs, ws) in xc.by_ref().zip(wc.by_ref()) {
        for l in 0..8 {
            acc[l] += xs[l] * ws[l];
        }
    }
    let mut s = 0.0;
    for a in acc {
        s += a;
    }
    for (xr, wr) in xc.remainder().iter().zip(wc.remainder()) {
        s += xr * wr;
    }
    s
}

/// PER-TOKEN shape — what `attn.rs::trunk_into` does today: one matvec per token, so the whole
/// weight matrix is walked N times.
fn lin_per_token(x: &[f32], w: &[f32], k: usize, m: usize, n: usize, y: &mut [f32]) {
    for t in 0..n {
        for mi in 0..m {
            y[t * m + mi] = dot8(&x[t * k..t * k + k], &w[mi * k..mi * k + k]);
        }
    }
}

/// BATCHED shape — loops swapped so each weight row is loaded once and reused across all N tokens.
fn lin_batched(x: &[f32], w: &[f32], k: usize, m: usize, n: usize, y: &mut [f32]) {
    for mi in 0..m {
        let wrow = &w[mi * k..mi * k + k];
        for t in 0..n {
            y[t * m + mi] = dot8(&x[t * k..t * k + k], wrow);
        }
    }
}

/// Paired, interleaved A/B of the two call shapes.
///
/// WHY PAIRED: cross-run variance on this box is ~20% (the same binary read 175 / 175 / 194 us for
/// the forward), so comparing a number from one build against a number from another build is
/// meaningless — a real 1.2x win and pure noise look identical. Timing both shapes in ONE process,
/// alternating which goes first, removes machine state from the comparison. Same discipline as the
/// play-gates' common-random-numbers.
///
/// Shapes are the real ones from `trunk_into`: QKV/Wo are [15 x 64] x [64 x 64], the FFN up-
/// projection is [15 x 64] x [64 x 128].
fn paired_kernel_ab() {
    for (k, m, label) in [(64usize, 64usize, "QKV/Wo  [15x64]x[64x64] "), (64, 128, "FFN up  [15x64]x[64x128]")] {
        let n = 15usize;
        let w: Vec<f32> = (0..m * k).map(|i| ((i % 17) as f32 - 8.0) * 0.01).collect();
        let x: Vec<f32> = (0..n * k).map(|i| ((i % 13) as f32 - 6.0) * 0.01).collect();
        let (mut y1, mut y2) = (vec![0f32; n * m], vec![0f32; n * m]);
        let (rounds, inner) = (24usize, 20_000usize);
        let (mut per_token, mut batched) = (0f64, 0f64);
        for r in 0..rounds {
            if r % 2 == 0 {
                let t = Instant::now();
                for _ in 0..inner { lin_per_token(&x, &w, k, m, n, &mut y1); }
                per_token += t.elapsed().as_secs_f64();
                let t = Instant::now();
                for _ in 0..inner { lin_batched(&x, &w, k, m, n, &mut y2); }
                batched += t.elapsed().as_secs_f64();
            } else {
                let t = Instant::now();
                for _ in 0..inner { lin_batched(&x, &w, k, m, n, &mut y2); }
                batched += t.elapsed().as_secs_f64();
                let t = Instant::now();
                for _ in 0..inner { lin_per_token(&x, &w, k, m, n, &mut y1); }
                per_token += t.elapsed().as_secs_f64();
            }
        }
        let diff: f32 = y1.iter().zip(y2.iter()).map(|(a, b)| (a - b).abs()).fold(0.0, f32::max);
        println!("PAIRED {label}: per-token {per_token:6.3}s | batched {batched:6.3}s | {:.2}x  (max|diff| {diff:.1e})",
                 per_token / batched);
    }
    println!("  >1.00x means batching wins. The two write IDENTICAL values (same dot, swapped loops).");
    paired_accum_ab();
}

/// 2 independent 8-wide accumulators (16 floats per step).
#[inline(always)]
fn dot8x2(x: &[f32], w: &[f32]) -> f32 {
    let (mut a, mut b) = ([0f32; 8], [0f32; 8]);
    let mut xc = x.chunks_exact(16);
    let mut wc = w.chunks_exact(16);
    for (xs, ws) in xc.by_ref().zip(wc.by_ref()) {
        for l in 0..8 {
            a[l] += xs[l] * ws[l];
            b[l] += xs[l + 8] * ws[l + 8];
        }
    }
    let mut s = 0.0;
    for l in 0..8 {
        s += a[l] + b[l];
    }
    for (xr, wr) in xc.remainder().iter().zip(wc.remainder()) {
        s += xr * wr;
    }
    s
}

/// 4 independent 8-wide accumulators (32 floats per step).
#[inline(always)]
fn dot8x4(x: &[f32], w: &[f32]) -> f32 {
    let (mut a, mut b, mut c, mut d) = ([0f32; 8], [0f32; 8], [0f32; 8], [0f32; 8]);
    let mut xc = x.chunks_exact(32);
    let mut wc = w.chunks_exact(32);
    for (xs, ws) in xc.by_ref().zip(wc.by_ref()) {
        for l in 0..8 {
            a[l] += xs[l] * ws[l];
            b[l] += xs[l + 8] * ws[l + 8];
            c[l] += xs[l + 16] * ws[l + 16];
            d[l] += xs[l + 24] * ws[l + 24];
        }
    }
    let mut s = 0.0;
    for l in 0..8 {
        s += a[l] + b[l] + c[l] + d[l];
    }
    for (xr, wr) in xc.remainder().iter().zip(wc.remainder()) {
        s += xr * wr;
    }
    s
}

/// Paired A/B of accumulator DEPTH — the real suspect behind the forward's ~14 GFLOP/s.
///
/// `dot8`'s comment claims its "8 independent lanes break the f32 reduction dependency", but those
/// 8 lanes are ONE AVX2 vector, so the vector FMAs still form a single serial chain: k=64 gives 8
/// dependent FMAs at ~4 cycles latency = ~32 cycles for 64 MACs = ~2 MACs/cycle, which is about
/// what the forward measures. Independent accumulators let several FMAs be in flight at once.
///
/// Reassociation note: x2 / x4 sum in a different order than x8, so results shift by ~1e-7 — the
/// same class of change `bin/attn_parity` already tolerates (and which `dot8` itself introduced).
#[inline(always)]
fn bb(v: &[f32]) -> &[f32] {
    std::hint::black_box(v)
}

fn paired_accum_ab() {
    let k = 64usize;
    let w: Vec<f32> = (0..k).map(|i| ((i % 17) as f32 - 8.0) * 0.01).collect();
    let x: Vec<f32> = (0..k).map(|i| ((i % 13) as f32 - 6.0) * 0.01).collect();
    let (rounds, inner) = (24usize, 400_000usize);
    let (mut t1, mut t2, mut t4) = (0f64, 0f64, 0f64);
    let (mut s1, mut s2, mut s4) = (0f32, 0f32, 0f32);
    for r in 0..rounds {
        // rotate which variant runs first so warm-up/thermal drift cannot favour one
        let order = [r % 3, (r + 1) % 3, (r + 2) % 3];
        for o in order {
            let t = Instant::now();
            match o {
                // black_box on BOTH operands: without it LLVM hoists the whole dot out of the
                // loop (both inputs are loop-invariant) and the bench reads ~0.6 ns/call, which is
                // how the first version of this measurement lied.
                0 => { for _ in 0..inner { s1 += dot8(bb(&x), bb(&w)); } t1 += t.elapsed().as_secs_f64(); }
                1 => { for _ in 0..inner { s2 += dot8x2(bb(&x), bb(&w)); } t2 += t.elapsed().as_secs_f64(); }
                _ => { for _ in 0..inner { s4 += dot8x4(bb(&x), bb(&w)); } t4 += t.elapsed().as_secs_f64(); }
            }
        }
    }
    println!("PAIRED ACCUMULATOR DEPTH (k=64 dot, {rounds} rotated rounds x {inner}):");
    println!("  dot8   (1 acc vector)  {t1:6.3}s   1.00x   [baseline, what attn.rs ships]");
    println!("  dot8x2 (2 acc vectors) {t2:6.3}s   {:.2}x", t1 / t2);
    println!("  dot8x4 (4 acc vectors) {t4:6.3}s   {:.2}x", t1 / t4);
    println!("  sums {s1:.3} / {s2:.3} / {s4:.3}  (differ in the last bits only — reassociation)");
}
