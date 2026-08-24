//! Learned value net as the MCTS leaf (Phase 2 of the Duel AZ campaign).
//!
//! WHAT THIS IS FOR: the deployed "Hard" bot searches with the HAND-TUNED heuristic leaf
//! (`value::value`), and its strength saturates by ~700 sims — the leaf is the ceiling, not
//! the sim count. Phase 1 harvested (features, outcome) self-play rows and trained an
//! outcome value net (`tools/train_value.py` → `value_net.json`). This module runs that net
//! as a DIRECT 0-step MCTS leaf: at a truncation it returns `net.eval(leaf, root_pid)` — the
//! net's P(win)-ish estimate in [-1, 1] — instead of the rollout+heuristic. The net is
//! meant to price the long horizon the static leaf misses; whether it actually beats the
//! heuristic AT EQUAL WALL-CLOCK is the empirical question the gate answers.
//!
//! THE PARITY CONTRACT: the forward pass here MUST reproduce the trained net bit-closely, or
//! any gate run through it measures a DIFFERENT net than was trained. `forward` is the exact
//! math `train_value.py` documents — `z = (x - mu)/sd`, then `relu(W0 z + b0)`,
//! `relu(W1 h1 + b1)`, `tanh(W2 h2 + b2)`, `w` row-major `[out][in]` — and the parity test
//! at the bottom asserts it matches the 32 stored `(x -> v)` samples within 1e-4.
//!
//! f32 THROUGHOUT (match the trainer's dtype; inference does not need f64 and this runs
//! per-sim, so speed matters). The two performance levers, both ported faithfully from
//! `coc-core/src/valuenet.rs` (the same net-leaf served in CoC's Expert bot):
//!   1. A CHUNKED 8-lane `dot` kernel. The naive single-accumulator inner loop is a serial
//!      FP dependency chain LLVM will NOT auto-vectorize (float reassociation is forbidden),
//!      so it ran the matvec at ~1% of the core's FMA throughput (the documented spender/coc
//!      trap). Eight independent lanes let LLVM emit SIMD FMAs.
//!   2. ZERO per-call heap allocation. The old `forward` did ~4 `vec![]` per call (z-score +
//!      each layer output); those are now thread-local ping-pong scratch buffers, so the
//!      per-sim hot path allocates nothing after warmup. Thread-local (not a `RefCell` field)
//!      keeps `ValueNet` `&self`/`Sync`, so a future root-parallel native search stays sound.
//! `forward_serial` preserves the original serial+alloc path so the bench can quantify the
//! win; the 1e-4 parity tolerance absorbs the chunked accumulation-order change.
//!
//! And an OPT-IN int8 net (`QuantValueNet`) — the two trunk layers (~96% of the MACs)
//! quantized to int8, heads + z-score kept f32 — ported from coc-core's `QuantPolicyValueNet`.
//! Its win is wasm: v128 lacks f32 FMA but HAS an integer dot (`i32x4_dot_i16x8`), so int8 is
//! the one path that changes the browser forward economics. int8 accumulation is EXACT, so
//! the VNNI / wasm-simd / scalar arms produce identical i32 — but int8 != f32, so it is gated
//! by STRENGTH vs the f32 leaf, not float parity (the `:net8` A/B), never the default.

use crate::engine::State;
use crate::feats::features;
use std::cell::RefCell;

/// Chunked 8-lane dot product. See the module doc (lever 1). The 8-lane chunk + lane-sum +
/// scalar tail is the CANONICAL accumulation order the parity tolerance is set against;
/// ported verbatim from `coc-core/src/valuenet.rs::dot`. Matvec speed is load/L3-bound, so
/// a single 8-lane chain measures the same as wider multi-chain variants.
#[inline]
fn dot(a: &[f32], b: &[f32]) -> f32 {
    const L: usize = 8;
    let mut acc = [0.0f32; L];
    let mut ca = a.chunks_exact(L);
    let mut cb = b.chunks_exact(L);
    for (xa, xb) in (&mut ca).zip(&mut cb) {
        for l in 0..L {
            acc[l] += xa[l] * xb[l];
        }
    }
    let mut s = 0.0f32;
    for l in 0..L {
        s += acc[l];
    }
    for (xa, xb) in ca.remainder().iter().zip(cb.remainder()) {
        s += xa * xb;
    }
    s
}

/// One dense layer: weights flattened row-major `[out][in]`, bias `[out]`.
struct Layer {
    w: Vec<f32>, // out_dim * in_dim, row `o` at [o*in_dim .. (o+1)*in_dim]
    b: Vec<f32>,
    in_dim: usize,
    out_dim: usize,
}

thread_local! {
    // Ping-pong scratch for `ValueNet::forward`, so the per-sim hot path allocates NOTHING
    // (the naive forward did ~4 `vec![]` per call). Two buffers sized to the widest layer;
    // the z-score result and each layer output alternate between them. Thread-local so the
    // net stays `&self`/`Sync` (root-parallel-safe) with no interior mutability on the net.
    static SCRATCH: RefCell<(Vec<f32>, Vec<f32>)> = const { RefCell::new((Vec::new(), Vec::new())) };
}

/// A trained MLP value net over the frozen `feats::features` vector: z-score standardize,
/// then `[N_FEATS -> h -> h -> 1]` with ReLU hidden units and a tanh output. Outcome-trained,
/// so `eval` returns a win-probability-shaped value in [-1, 1] from `seat`'s perspective.
pub struct ValueNet {
    mu: Vec<f32>,
    sd: Vec<f32>,
    layers: Vec<Layer>,
    scratch_width: usize, // max(in_dim, all out_dims) — the ping-pong buffer size
}

impl ValueNet {
    /// The net's input dimension (== `feats::N_FEATS`). Exposed so a loader can reject a net
    /// whose encoder drifted from the one this crate compiles against.
    pub fn in_dim(&self) -> usize {
        self.mu.len()
    }

    /// The raw forward pass, factored out of `eval` so the parity test can drive it with the
    /// stored raw feature vectors (`eval` builds those from a `State`; the samples ARE those
    /// vectors). Standardize with the trained mu/sd, then the MLP.
    ///
    /// Chunked `dot` + thread-local ping-pong scratch (see the module doc): SIMD-friendly and
    /// allocation-free on the hot path. The tanh is applied in f32 then widened — `train_value.py`
    /// does `float(net(...))`, i.e. an f32 tanh cast to Python's f64.
    pub fn forward(&self, raw: &[f32]) -> f64 {
        debug_assert_eq!(raw.len(), self.mu.len(), "feature length != net input dim");

        SCRATCH.with(|cell| {
            let mut guard = cell.borrow_mut();
            let (cur, next) = &mut *guard;
            let w = self.scratch_width;
            if cur.len() < w {
                cur.resize(w, 0.0);
            }
            if next.len() < w {
                next.resize(w, 0.0);
            }

            // z-score into cur[..n]. `sd` is already clamped (the trainer sets sd<1e-6 to 1.0
            // BEFORE export); the `!= 0.0` guard is belt-and-suspenders against a div by zero.
            let n = self.mu.len();
            for i in 0..n {
                let s = if self.sd[i] != 0.0 { self.sd[i] } else { 1.0 };
                cur[i] = (raw[i] - self.mu[i]) / s;
            }

            let nl = self.layers.len();
            for (li, layer) in self.layers.iter().enumerate() {
                let (id, od) = (layer.in_dim, layer.out_dim);
                let src = &cur[..id];
                for o in 0..od {
                    let row = &layer.w[o * id..o * id + id];
                    next[o] = layer.b[o] + dot(row, src);
                }
                // ReLU on hidden layers only; the output layer gets tanh below.
                if li + 1 < nl {
                    for x in next[..od].iter_mut() {
                        if *x < 0.0 {
                            *x = 0.0;
                        }
                    }
                }
                std::mem::swap(cur, next);
            }
            // After the final swap the output sits in `cur` (last layer out_dim == 1).
            cur[0].tanh() as f64
        })
    }

    /// The ORIGINAL serial single-accumulator + per-call-`vec!` forward, preserved so
    /// `bench_leaf` can quantify what the chunked-`dot` + no-alloc rewrite buys. NOT used in
    /// serving; behaviourally identical to `forward` up to accumulation order (both under 1e-4
    /// of the trained net). Do not "clean up" — its whole purpose is to be the slow baseline.
    pub fn forward_serial(&self, raw: &[f32]) -> f64 {
        debug_assert_eq!(raw.len(), self.mu.len(), "feature length != net input dim");
        let mut cur: Vec<f32> = (0..self.mu.len())
            .map(|i| {
                let s = if self.sd[i] != 0.0 { self.sd[i] } else { 1.0 };
                (raw[i] - self.mu[i]) / s
            })
            .collect();
        let n = self.layers.len();
        for (li, layer) in self.layers.iter().enumerate() {
            let mut next = vec![0.0f32; layer.out_dim];
            for o in 0..layer.out_dim {
                let row = &layer.w[o * layer.in_dim..o * layer.in_dim + layer.in_dim];
                let mut acc = layer.b[o];
                for i in 0..layer.in_dim {
                    acc += row[i] * cur[i];
                }
                next[o] = acc;
            }
            if li + 1 < n {
                for x in next.iter_mut() {
                    if *x < 0.0 {
                        *x = 0.0;
                    }
                }
            }
            cur = next;
        }
        cur[0].tanh() as f64
    }

    /// The MCTS leaf value: encode `st` from `seat`'s perspective and run the net. A pure
    /// function of the state (like `value::value`), so root-parallel serving stays sound.
    #[inline]
    pub fn eval(&self, st: &State, seat: usize) -> f64 {
        self.forward(&features(st, seat))
    }

    /// Random-weight net at the deployed dims (275->256->256->1) — for THROUGHPUT probes only
    /// (forward-pass speed is weight-independent, the spender/coc precedent). Used by the wasm
    /// micro-bench to time f32 vs int8 forwards WITHOUT embedding the 3MB trained JSON in the
    /// serving wasm. mu=0/sd=1 (a no-op z-score), which is fine for a speed probe.
    pub fn random(seed: u64) -> ValueNet {
        let dims = [275usize, 256, 256, 1];
        let mut rng = crate::rng::Rng::new(seed);
        let nextf = |rng: &mut crate::rng::Rng| {
            // uniform-ish in [-0.1, 0.1] from the splitmix stream (small so int8 quant is sane)
            ((rng.next_u64() >> 11) as f32 / (1u64 << 53) as f32 * 2.0 - 1.0) * 0.1
        };
        let mut layers = Vec::new();
        for l in 0..dims.len() - 1 {
            let (in_dim, out_dim) = (dims[l], dims[l + 1]);
            let w = (0..in_dim * out_dim).map(|_| nextf(&mut rng)).collect();
            let b = (0..out_dim).map(|_| nextf(&mut rng)).collect();
            layers.push(Layer { w, b, in_dim, out_dim });
        }
        let scratch_width = dims.iter().copied().max().unwrap_or(0);
        ValueNet { mu: vec![0.0; dims[0]], sd: vec![1.0; dims[0]], layers, scratch_width }
    }

    /// Parse `value_net.json` (the `train_value.py` export). serde-gated: native builds only
    /// pull it in for the bridge (the gate's move server), and the wasm build will embed the
    /// blob — neither the struct nor `forward`/`eval` need serde, so they stay always-on.
    #[cfg(any(feature = "bridge", target_arch = "wasm32"))]
    pub fn from_json_str(s: &str) -> Result<ValueNet, String> {
        use serde::Deserialize;

        #[derive(Deserialize)]
        struct RawLayer {
            w: Vec<Vec<f32>>, // [out][in]
            b: Vec<f32>,
        }
        #[derive(Deserialize)]
        struct Raw {
            mu: Vec<f32>,
            sd: Vec<f32>,
            layers: Vec<RawLayer>,
        }

        let raw: Raw = serde_json::from_str(s).map_err(|e| e.to_string())?;
        if raw.mu.len() != raw.sd.len() {
            return Err(format!("mu len {} != sd len {}", raw.mu.len(), raw.sd.len()));
        }
        // The input dim is checked against N_FEATS by the caller if it cares; here we only
        // need mu/sd to match the first layer's input.
        let mut layers = Vec::with_capacity(raw.layers.len());
        for (li, l) in raw.layers.into_iter().enumerate() {
            let out_dim = l.w.len();
            if out_dim == 0 {
                return Err(format!("layer {} has no rows", li));
            }
            let in_dim = l.w[0].len();
            if l.b.len() != out_dim {
                return Err(format!("layer {}: bias len {} != out_dim {}", li, l.b.len(), out_dim));
            }
            let mut flat = Vec::with_capacity(out_dim * in_dim);
            for (r, row) in l.w.iter().enumerate() {
                if row.len() != in_dim {
                    return Err(format!("layer {} row {}: width {} != {}", li, r, row.len(), in_dim));
                }
                flat.extend_from_slice(row);
            }
            layers.push(Layer { w: flat, b: l.b, in_dim, out_dim });
        }
        // Chain check: first layer's input must be mu/sd length, and each layer feeds the next.
        if let Some(first) = layers.first() {
            if first.in_dim != raw.mu.len() {
                return Err(format!("layer 0 in_dim {} != mu len {}", first.in_dim, raw.mu.len()));
            }
        }
        for w in layers.windows(2) {
            if w[0].out_dim != w[1].in_dim {
                return Err(format!("layer chain break: {} -> {}", w[0].out_dim, w[1].in_dim));
            }
        }
        let scratch_width = raw
            .mu
            .len()
            .max(layers.iter().map(|l| l.out_dim).max().unwrap_or(0));
        Ok(ValueNet { mu: raw.mu, sd: raw.sd, layers, scratch_width })
    }
}

// ─── int8 quantized value net (opt-in; the wasm-deployment win) ───────────────
// Trunk layers (275->256, 256->256; ~96% of the MACs) quantized to int8 at LOAD from the f32
// net (no new file format): per-output-row symmetric weight scales, DYNAMIC per-vector
// activation quantization (scale = amax/127, zero-point 128 -> u8 for vpdpbusd's u8 x i8 form,
// with the precomputed 128*rowsum correction). The value head (256->1) + z-score stay f32.
// Integer accumulation is EXACT, so the VNNI / wasm-simd128 / scalar `qdot` arms produce
// IDENTICAL i32 (deterministic across machines) — but int8 != f32, so this is an OPT-IN net
// (`:net8`) gated by STRENGTH vs the f32 net leaf, not float parity. Ported faithfully from
// `coc-core/src/valuenet.rs`'s `QuantPolicyValueNet` block.

/// u8 x i8 dot with i32 accumulation — AVX-512 VNNI (`vpdpbusd`) when compiled for it
/// (target-cpu=native on the Zen 4 dev box HAS avx512vnni), exact-same-result scalar loop
/// otherwise (CI / non-VNNI x86). `qdot_scalar` below is the always-present portable form the
/// determinism gate compares against.
#[cfg(all(target_arch = "x86_64", target_feature = "avx512vnni"))]
#[inline]
fn qdot(w: &[i8], x: &[u8]) -> i32 {
    use std::arch::x86_64::*;
    unsafe {
        let n = w.len();
        let chunks = n / 64;
        let mut acc = _mm512_setzero_si512();
        for c in 0..chunks {
            let xv = _mm512_loadu_si512(x.as_ptr().add(c * 64) as *const _);
            let wv = _mm512_loadu_si512(w.as_ptr().add(c * 64) as *const _);
            acc = _mm512_dpbusd_epi32(acc, xv, wv);
        }
        let mut s = _mm512_reduce_add_epi32(acc);
        for i in chunks * 64..n {
            s += (x[i] as i32) * (w[i] as i32);
        }
        s
    }
}

/// wasm-simd128 arm: widen u8/i8 to i16x8 halves and use `i32x4_dot_i16x8` (v128 DOES have an
/// integer dot even though it lacks f32 FMA — this is what makes int8 the one path that
/// changes the wasm forward economics). Products are i32 pairwise (255*127 per element,
/// n~275 accumulation — no overflow), so the result is the EXACT same integer as the scalar
/// loop. Ported from coc-core.
#[cfg(all(target_arch = "wasm32", target_feature = "simd128"))]
#[inline]
fn qdot(w: &[i8], x: &[u8]) -> i32 {
    use core::arch::wasm32::*;
    let n = w.len();
    let chunks = n / 16;
    let mut acc = i32x4_splat(0);
    for c in 0..chunks {
        let (xv, wv) = unsafe {
            (
                v128_load(x.as_ptr().add(c * 16) as *const v128),
                v128_load(w.as_ptr().add(c * 16) as *const v128),
            )
        };
        let xl = u16x8_extend_low_u8x16(xv); // u8 (<=255) fits positive i16
        let xh = u16x8_extend_high_u8x16(xv);
        let wl = i16x8_extend_low_i8x16(wv);
        let wh = i16x8_extend_high_i8x16(wv);
        acc = i32x4_add(acc, i32x4_dot_i16x8(xl, wl));
        acc = i32x4_add(acc, i32x4_dot_i16x8(xh, wh));
    }
    let mut s = i32x4_extract_lane::<0>(acc)
        + i32x4_extract_lane::<1>(acc)
        + i32x4_extract_lane::<2>(acc)
        + i32x4_extract_lane::<3>(acc);
    for i in chunks * 16..n {
        s += (x[i] as i32) * (w[i] as i32);
    }
    s
}

#[cfg(not(any(
    all(target_arch = "x86_64", target_feature = "avx512vnni"),
    all(target_arch = "wasm32", target_feature = "simd128")
)))]
#[inline]
fn qdot(w: &[i8], x: &[u8]) -> i32 {
    qdot_scalar(w, x)
}

/// The portable scalar u8 x i8 dot. Always compiled so the determinism gate can force it and
/// assert the SIMD `qdot` arm produces the identical i32 (integer accumulation is exact and
/// order-independent, so this is a real cross-arm check, not a tautology).
#[inline]
fn qdot_scalar(w: &[i8], x: &[u8]) -> i32 {
    let mut s = 0i32;
    for (wi, xi) in w.iter().zip(x.iter()) {
        s += (*xi as i32) * (*wi as i32);
    }
    s
}

/// Quantize one activation vector into `out`: symmetric i8 (amax/127) shifted to u8 with
/// zero-point 128. Returns the scale. Reuses `out`'s allocation (clear + extend), so the hot
/// path allocates only on the first, widest call. Float math, identical on every arm.
#[inline]
fn quantize_act(x: &[f32], out: &mut Vec<u8>) -> f32 {
    let mut amax = 0.0f32;
    for &v in x {
        amax = amax.max(v.abs());
    }
    let s = if amax > 0.0 { amax / 127.0 } else { 1.0 };
    let inv = 1.0 / s;
    out.clear();
    out.extend(x.iter().map(|&v| {
        let q = (v * inv).round().clamp(-127.0, 127.0) as i32;
        (q + 128) as u8
    }));
    s
}

thread_local! {
    // f32 ping-pong (cur/next) + a reusable u8 activation-quant buffer for `QuantValueNet`.
    static QSCRATCH: RefCell<(Vec<f32>, Vec<f32>, Vec<u8>)> =
        const { RefCell::new((Vec::new(), Vec::new(), Vec::new())) };
}

/// int8-trunk value net. Same interface as `ValueNet` (`from_f32`/`forward`/`eval`), OPT-IN.
pub struct QuantValueNet {
    mu: Vec<f32>,
    inv_sd: Vec<f32>,   // 1/sd precomputed (sd==0 -> 1.0); a mul beats a div per feature
    tin: Vec<usize>,    // per trunk layer: in_dim
    tout: Vec<usize>,   // per trunk layer: out_dim
    qw: Vec<Vec<i8>>,   // per trunk layer: row-major int8 weights
    qs: Vec<Vec<f32>>,  // per trunk layer: per-row weight scale
    qrs: Vec<Vec<i32>>, // per trunk layer: per-row weight sum (zero-point correction)
    tb: Vec<Vec<f32>>,  // per trunk layer: f32 biases
    hw: Vec<f32>,       // f32 value head, row-major (out_dim x in_dim); out_dim == 1
    hb: Vec<f32>,
    h_in: usize,
    scratch_width: usize,
}

impl QuantValueNet {
    /// Quantize an f32 `ValueNet`'s trunk (every layer but the last) to int8; keep the value
    /// head + z-score in f32. Per-output-row symmetric weight scales + per-row weight sums
    /// (for the u8 zero-point-128 correction). Mirrors `QuantPolicyValueNet::from_f32`.
    pub fn from_f32(net: &ValueNet) -> QuantValueNet {
        let nl = net.layers.len();
        assert!(nl >= 2, "need at least a trunk layer + a head layer to quantize");
        let inv_sd = net.sd.iter().map(|&s| if s != 0.0 { 1.0 / s } else { 1.0 }).collect();

        let (mut qw, mut qs, mut qrs, mut tb, mut tin, mut tout) =
            (Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new(), Vec::new());
        for layer in &net.layers[..nl - 1] {
            let (id, od) = (layer.in_dim, layer.out_dim);
            let mut lw = vec![0i8; id * od];
            let mut ls = vec![1.0f32; od];
            let mut lrs = vec![0i32; od];
            for o in 0..od {
                let row = &layer.w[o * id..o * id + id];
                let mut amax = 0.0f32;
                for &v in row {
                    amax = amax.max(v.abs());
                }
                let s = if amax > 0.0 { amax / 127.0 } else { 1.0 };
                let inv = 1.0 / s;
                let mut rs = 0i32;
                for (j, &v) in row.iter().enumerate() {
                    let q = (v * inv).round().clamp(-127.0, 127.0) as i32;
                    lw[o * id + j] = q as i8;
                    rs += q;
                }
                ls[o] = s;
                lrs[o] = rs;
            }
            qw.push(lw);
            qs.push(ls);
            qrs.push(lrs);
            tb.push(layer.b.clone());
            tin.push(id);
            tout.push(od);
        }

        let head = &net.layers[nl - 1];
        QuantValueNet {
            mu: net.mu.clone(),
            inv_sd,
            tin,
            tout,
            qw,
            qs,
            qrs,
            tb,
            hw: head.w.clone(),
            hb: head.b.clone(),
            h_in: head.in_dim,
            scratch_width: net.scratch_width,
        }
    }

    /// The int8 forward: standardize f32, per trunk layer (quantize acts -> int8 matvec via
    /// `qd` -> dequant + bias + ReLU in f32), then the f32 value head + tanh. Allocation-free
    /// on the hot path (thread-local scratch). `qd` is the SIMD `qdot` for `forward`, the
    /// portable `qdot_scalar` for `forward_ref` — same integer result, so the two agree bit
    /// for bit (the determinism gate).
    #[inline]
    fn forward_with(&self, raw: &[f32], qd: fn(&[i8], &[u8]) -> i32) -> f64 {
        QSCRATCH.with(|cell| {
            let mut guard = cell.borrow_mut();
            let (cur, next, xq) = &mut *guard;
            let w = self.scratch_width;
            if cur.len() < w {
                cur.resize(w, 0.0);
            }
            if next.len() < w {
                next.resize(w, 0.0);
            }

            let n = self.mu.len();
            for i in 0..n {
                cur[i] = (raw[i] - self.mu[i]) * self.inv_sd[i];
            }

            for l in 0..self.qw.len() {
                let (id, od) = (self.tin[l], self.tout[l]);
                let sx = quantize_act(&cur[..id], xq);
                let wl = &self.qw[l];
                let (ls, lrs, lb) = (&self.qs[l], &self.qrs[l], &self.tb[l]);
                for o in 0..od {
                    let acc = qd(&wl[o * id..o * id + id], &xq[..id]);
                    // Undo the u8 zero-point (x' = x_i8 + 128): sum(w*(x+128)) = sum(w*x) +
                    // 128*sum(w), so subtract 128*rowsum to recover the true int32 dot.
                    let corrected = acc - 128 * lrs[o];
                    let y = corrected as f32 * (sx * ls[o]) + lb[o];
                    next[o] = if y > 0.0 { y } else { 0.0 };
                }
                std::mem::swap(cur, next);
            }

            // f32 value head (single row) + tanh.
            let hd = self.h_in;
            (self.hb[0] + dot(&self.hw[..hd], &cur[..hd])).tanh() as f64
        })
    }

    /// int8 forward through the SIMD `qdot` (VNNI on x86 / i32x4_dot on wasm / scalar else).
    pub fn forward(&self, raw: &[f32]) -> f64 {
        self.forward_with(raw, qdot)
    }

    /// int8 forward forced through the portable scalar `qdot_scalar` — the reference the
    /// determinism gate compares `forward` against (must be bit-identical: integer-exact).
    pub fn forward_ref(&self, raw: &[f32]) -> f64 {
        self.forward_with(raw, qdot_scalar)
    }

    /// The MCTS leaf value (int8): encode `st` from `seat` and run the quantized forward.
    #[inline]
    pub fn eval(&self, st: &State, seat: usize) -> f64 {
        self.forward(&features(st, seat))
    }
}

// The parity gate lives with the net so it can never drift from `forward`. Bridge-gated so a
// plain `cargo test` (no serde-backed JSON loader) still compiles; the required gate runs
// `cargo test --release --features bridge valuenet`, which turns this on.
#[cfg(all(test, feature = "bridge"))]
mod tests {
    use super::*;
    use serde::Deserialize;

    // Embed the exact deployed net at compile time — cwd-independent, and guaranteed to be
    // the same bytes the crate would serve.
    const JSON: &str = include_str!("value_net.json");

    #[derive(Deserialize)]
    struct Sample {
        x: Vec<f32>, // raw (pre-zscore) features
        v: f64,      // the trained net's output for x (f32 tanh widened to f64)
    }
    #[derive(Deserialize)]
    struct Blob {
        samples: Vec<Sample>,
    }

    /// THE CONTRACT: the Rust forward pass must reproduce the trained net on all 32 stored
    /// samples within 1e-4. If this fails, every gate number is meaningless (a different net
    /// is being searched than was trained).
    #[test]
    fn valuenet_matches_trained_samples_within_1e4() {
        let net = ValueNet::from_json_str(JSON).expect("load value_net.json");
        let blob: Blob = serde_json::from_str(JSON).expect("parse samples");
        assert!(!blob.samples.is_empty(), "no parity samples in value_net.json");

        let mut max_err = 0.0f64;
        for s in &blob.samples {
            let got = net.forward(&s.x);
            max_err = max_err.max((got - s.v).abs());
        }
        // Printed so the gate report can quote the real number (run with --nocapture).
        eprintln!(
            "valuenet parity (chunked forward): max abs error = {:.3e} over {} samples",
            max_err,
            blob.samples.len()
        );
        assert!(max_err < 1e-4, "max abs parity error {:.3e} exceeds 1e-4", max_err);
    }

    /// The chunked `forward` and the preserved serial `forward_serial` must agree within 1e-4
    /// (accumulation order is the only difference), so the bench compares two nets that are
    /// the same up to that tolerance.
    #[test]
    fn valuenet_chunked_matches_serial() {
        let net = ValueNet::from_json_str(JSON).expect("load value_net.json");
        let blob: Blob = serde_json::from_str(JSON).expect("parse samples");
        let mut max_err = 0.0f64;
        for s in &blob.samples {
            max_err = max_err.max((net.forward(&s.x) - net.forward_serial(&s.x)).abs());
        }
        eprintln!("chunked vs serial: max abs diff = {:.3e}", max_err);
        assert!(max_err < 1e-4, "chunked vs serial diff {:.3e} exceeds 1e-4", max_err);
    }

    /// int8 DETERMINISM/EXACTNESS: the SIMD `qdot` path (`forward`) and the portable scalar
    /// path (`forward_ref`) must produce BIT-IDENTICAL outputs — integer accumulation is
    /// exact, so the VNNI/wasm/scalar arms are the same i32, and the f32 dequant is identical
    /// arithmetic. Also reports the int8-vs-f32 value MAE (expected ~1e-3..5e-3; int8 != f32
    /// is fine — the int8 net is gated by strength, not float parity).
    #[test]
    fn quant_int8_matches_scalar_and_reports_f32_mae() {
        let net = ValueNet::from_json_str(JSON).expect("load value_net.json");
        let q = QuantValueNet::from_f32(&net);
        let blob: Blob = serde_json::from_str(JSON).expect("parse samples");

        let mut simd_vs_scalar = 0.0f64;
        let mut mae = 0.0f64;
        let mut worst = 0.0f64;
        for s in &blob.samples {
            let a = q.forward(&s.x);
            let b = q.forward_ref(&s.x);
            simd_vs_scalar = simd_vs_scalar.max((a - b).abs());
            let d = (a - net.forward(&s.x)).abs();
            mae += d;
            worst = worst.max(d);
        }
        mae /= blob.samples.len() as f64;
        eprintln!(
            "int8 forward: SIMD-vs-scalar max diff = {:.3e} (must be 0); int8-vs-f32 MAE = {:.3e}, worst = {:.3e}",
            simd_vs_scalar, mae, worst
        );
        assert_eq!(simd_vs_scalar, 0.0, "int8 SIMD path diverged from the scalar reference");
    }
}
