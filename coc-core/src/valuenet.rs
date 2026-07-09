//! Value-net inference primitives (Phase 0 of the value-first ladder) — pure-Rust forward passes used
//! to (a) MEASURE Rust-CPU inference throughput vs net size (gates the affordable net for self-play),
//! and later (b) run the trained value as the MCTS leaf during Rust self-play. f32 (inference doesn't
//! need f64), naive cache-friendly matmuls (no BLAS dep). Weights are random here — forward-pass SPEED
//! is weight-independent, so this measures the real serving cost.
//!
//! Two candidate architectures: a flat MLP (baseline) and a single-block self-attention over entity
//! tokens (the relational arch the plan favors). Phase 0 reports evals/s for each so we pick the size.

use crate::rng::Rng;

#[inline]
fn relu_inplace(v: &mut [f32]) {
    for x in v.iter_mut() {
        if *x < 0.0 {
            *x = 0.0;
        }
    }
}

/// Chunked 8-lane dot product. The naive single-accumulator form is a serial FP
/// dependency chain the compiler may NOT vectorize (float reassociation is
/// forbidden), which ran the matvec at ~1% of the core's FMA throughput; 8
/// independent lanes let LLVM emit SIMD FMAs (AVX2/AVX-512 with
/// target-cpu=native, simd128 on wasm). The 8-lane chunk + lane-sum + scalar
/// tail is the CANONICAL accumulation order — `dot4` (the batched kernel) uses
/// the exact same order per pair, which is what makes batched search runs
/// bit-identical to sequential ones. Matvec speed is load/L3-bound, so a single
/// 8-lane chain measures the same as wider multi-chain variants.
#[inline]
pub(crate) fn dot(a: &[f32], b: &[f32]) -> f32 {
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

/// Register-blocked 4-input dot: one weight-row sweep dotted against FOUR
/// activation vectors at once. The row chunk is loaded once per 4 FMAs and the
/// four 8-lane accumulators live in registers, so a batched layer streams the
/// weights K/4 times instead of K times while the x-block (4 x ~4KB) stays
/// L1-resident — this is what turns `forward_batch` from a wash into a real
/// win (the first row-reuse tiling just traded L3 weight traffic for L2
/// activation traffic). Each output's accumulation order is IDENTICAL to
/// `dot`, preserving batched==sequential bit-identity.
#[inline]
fn dot4(row: &[f32], xs: [&[f32]; 4]) -> [f32; 4] {
    const L: usize = 8;
    let n = row.len();
    let chunks = n / L;
    let mut acc = [[0.0f32; L]; 4];
    for c in 0..chunks {
        let r = &row[c * L..c * L + L];
        for (k, x) in xs.iter().enumerate() {
            let xc = &x[c * L..c * L + L];
            for l in 0..L {
                acc[k][l] += r[l] * xc[l];
            }
        }
    }
    let mut out = [0.0f32; 4];
    for k in 0..4 {
        let mut s = 0.0f32;
        for l in 0..L {
            s += acc[k][l];
        }
        for i in chunks * L..n {
            s += row[i] * xs[k][i];
        }
        out[k] = s;
    }
    out
}

/// y[out] = W[out x in] @ x[in] + b[out]  (row-major W).
fn linear(w: &[f32], b: &[f32], x: &[f32], out_dim: usize, in_dim: usize, y: &mut [f32]) {
    for o in 0..out_dim {
        let row = &w[o * in_dim..o * in_dim + in_dim];
        y[o] = b[o] + dot(row, x);
    }
}

fn rand_vec(rng: &mut Rng, n: usize, scale: f32) -> Vec<f32> {
    (0..n)
        .map(|_| {
            // uniform-ish in [-scale, scale] from the splitmix stream
            let u = (rng.next_u64() >> 11) as f32 / (1u64 << 53) as f32;
            (u * 2.0 - 1.0) * scale
        })
        .collect()
}

// ─── MLP ───────────────────────────────────────────────────────────────────
pub struct Mlp {
    dims: Vec<usize>,          // [in, h1, h2, ..., 1]
    w: Vec<Vec<f32>>,          // per layer, row-major (out x in)
    b: Vec<Vec<f32>>,
}

impl Mlp {
    pub fn random(dims: &[usize], seed: u64) -> Self {
        let mut rng = Rng::new(seed);
        let mut w = Vec::new();
        let mut b = Vec::new();
        for l in 0..dims.len() - 1 {
            let (i, o) = (dims[l], dims[l + 1]);
            let scale = (2.0 / i as f32).sqrt();
            w.push(rand_vec(&mut rng, i * o, scale));
            b.push(vec![0.0; o]);
        }
        Mlp { dims: dims.to_vec(), w, b }
    }

    /// Build from trained parameters: `dims` = [in, h1, ..., 1]; `w[l]` row-major (out x in); `b[l]`.
    pub fn from_parts(dims: Vec<usize>, w: Vec<Vec<f32>>, b: Vec<Vec<f32>>) -> Self {
        assert_eq!(w.len(), dims.len() - 1);
        assert_eq!(b.len(), dims.len() - 1);
        Mlp { dims, w, b }
    }

    pub fn weights(&self) -> &[Vec<f32>] {
        &self.w
    }
    pub fn biases(&self) -> &[Vec<f32>] {
        &self.b
    }

    /// Forward one input → scalar value in [-1,1] (tanh on the last unit). ReLU on hidden layers.
    pub fn forward(&self, x: &[f32]) -> f32 {
        let mut cur = x.to_vec();
        let n = self.w.len();
        for l in 0..n {
            let (i, o) = (self.dims[l], self.dims[l + 1]);
            let mut next = vec![0.0f32; o];
            linear(&self.w[l], &self.b[l], &cur, o, i, &mut next);
            if l + 1 < n {
                relu_inplace(&mut next);
            }
            cur = next;
        }
        cur[0].tanh()
    }
}

/// MLP + input standardization (z-score with trained mu/sd) — the served value leaf. `forward_raw`
/// takes the RAW `feats::features` vector (f32), standardizes, and returns the value in [-1,1].
pub struct StandardizedMlp {
    mlp: Mlp,
    mu: Vec<f32>,
    sd: Vec<f32>,
}

impl StandardizedMlp {
    pub fn new(mlp: Mlp, mu: Vec<f32>, sd: Vec<f32>) -> Self {
        StandardizedMlp { mlp, mu, sd }
    }
    pub fn in_dim(&self) -> usize {
        self.mu.len()
    }
    #[inline]
    pub fn forward_raw(&self, raw: &[f32]) -> f32 {
        let n = self.mu.len();
        let mut z = vec![0.0f32; n];
        for i in 0..n {
            let s = if self.sd[i] != 0.0 { self.sd[i] } else { 1.0 };
            z[i] = (raw[i] - self.mu[i]) / s;
        }
        self.mlp.forward(&z)
    }
}

// ─── Policy + Value net (AZ retrain, Plan A) ─────────────────────────────────
// Shared trunk (Linear+ReLU layers) -> a value head (->1, tanh) and a policy head (->n_act logits).
// `forward_raw` takes the RAW `feats::features` vector, standardizes (z-score), and returns
// (value in [-1,1], policy logits over the action space). The Python trainer exports this JSON layout.
pub struct PolicyValueNet {
    enc: crate::feats::Enc, // encoder version, inferred from in_dim at load
    mu: Vec<f32>,
    inv_sd: Vec<f32>, // 1/sd precomputed at load (sd==0 -> 1.0); a mul beats 934 divs/forward
    tdims: Vec<usize>, // trunk dims: [in, h1, ..., H]
    tw: Vec<Vec<f32>>, // trunk weights per layer (row-major out x in)
    tb: Vec<Vec<f32>>,
    vw: Vec<f32>, // value head  H x 1 (row-major: 1 x H)
    vb: Vec<f32>,
    pw: Vec<f32>, // policy head n_act x H
    pb: Vec<f32>,
    n_act: usize,
}

impl PolicyValueNet {
    #[allow(clippy::too_many_arguments)]
    pub fn from_parts(
        mu: Vec<f32>, sd: Vec<f32>, tdims: Vec<usize>, tw: Vec<Vec<f32>>, tb: Vec<Vec<f32>>,
        vw: Vec<f32>, vb: Vec<f32>, pw: Vec<f32>, pb: Vec<f32>, n_act: usize,
    ) -> Self {
        assert_eq!(tw.len(), tdims.len() - 1);
        assert_eq!(tb.len(), tdims.len() - 1);
        let inv_sd = sd.iter().map(|&s| if s != 0.0 { 1.0 / s } else { 1.0 }).collect();
        let enc = crate::feats::Enc::from_in_dim(mu.len());
        PolicyValueNet { enc, mu, inv_sd, tdims, tw, tb, vw, vb, pw, pb, n_act }
    }
    pub fn in_dim(&self) -> usize {
        self.mu.len()
    }
    pub fn n_act(&self) -> usize {
        self.n_act
    }

    /// Random-weight net at the given dims — throughput probes only (forward-pass speed is
    /// weight-independent, so this measures the real serving/self-play cost of a candidate size).
    pub fn random(in_dim: usize, trunk: &[usize], n_act: usize, seed: u64) -> Self {
        let mut rng = Rng::new(seed);
        let mut tdims = vec![in_dim];
        tdims.extend_from_slice(trunk);
        let mut tw = Vec::new();
        let mut tb = Vec::new();
        for l in 0..tdims.len() - 1 {
            let (i, o) = (tdims[l], tdims[l + 1]);
            let scale = (2.0 / i as f32).sqrt();
            tw.push(rand_vec(&mut rng, i * o, scale));
            tb.push(vec![0.0; o]);
        }
        let hd = *tdims.last().unwrap();
        let s = (1.0 / hd as f32).sqrt();
        PolicyValueNet {
            enc: crate::feats::Enc::from_in_dim(in_dim),
            mu: vec![0.0; in_dim],
            inv_sd: vec![1.0; in_dim],
            tdims,
            tw,
            tb,
            vw: rand_vec(&mut rng, hd, s),
            vb: vec![0.0; 1],
            pw: rand_vec(&mut rng, hd * n_act, s),
            pb: vec![0.0; n_act],
            n_act,
        }
    }

    /// Standardize + trunk layers -> the shared hidden vector both heads read.
    fn trunk(&self, raw: &[f32]) -> Vec<f32> {
        let n = self.mu.len();
        let mut cur = vec![0.0f32; n];
        for i in 0..n {
            cur[i] = (raw[i] - self.mu[i]) * self.inv_sd[i];
        }
        for l in 0..self.tw.len() {
            let (i, o) = (self.tdims[l], self.tdims[l + 1]);
            let mut next = vec![0.0f32; o];
            linear(&self.tw[l], &self.tb[l], &cur, o, i, &mut next);
            relu_inplace(&mut next);
            cur = next;
        }
        cur
    }

    /// (value in [-1,1], policy logits[n_act]) from the raw feature vector.
    pub fn forward_raw(&self, raw: &[f32]) -> (f32, Vec<f32>) {
        let cur = self.trunk(raw);
        let hd = *self.tdims.last().unwrap();
        let mut vo = [0.0f32; 1];
        linear(&self.vw, &self.vb, &cur, 1, hd, &mut vo);
        let mut po = vec![0.0f32; self.n_act];
        linear(&self.pw, &self.pb, &cur, self.n_act, hd, &mut po);
        (vo[0].tanh(), po)
    }

    /// Value head only — skips the n_act x H policy matvec. The netval leaf's
    /// truncation eval needs only the value, so this shaves the policy head's
    /// share off the second forward of every sim.
    pub fn forward_value_raw(&self, raw: &[f32]) -> f32 {
        let cur = self.trunk(raw);
        let hd = *self.tdims.last().unwrap();
        let mut vo = [0.0f32; 1];
        linear(&self.vw, &self.vb, &cur, 1, hd, &mut vo);
        vo[0].tanh()
    }

    /// Batched forward: K inputs through the net with ROW-REUSE tiling — each
    /// weight row is loaded from L3 once and dotted against all K activations
    /// (which sit in L1/L2), so weight traffic per eval drops ~K-fold. The
    /// single-input forward was MEMORY-bound (2.5MB of weights streamed per
    /// call across 10 threads ≈ the shared-L3 ceiling); batching makes it
    /// compute-bound. Each output is BIT-IDENTICAL to forward_raw /
    /// forward_value_raw on the same input (same per-row `dot`, same order).
    /// `need_policy[k]` false skips the policy head for that row (returns an
    /// empty Vec) — the netval truncation rows only need the value.
    pub fn forward_batch(&self, raws: &[&[f32]], need_policy: &[bool]) -> Vec<(f32, Vec<f32>)> {
        let k = raws.len();
        assert_eq!(need_policy.len(), k);
        if k == 0 {
            return Vec::new();
        }
        // standardize all inputs
        let n = self.mu.len();
        let mut acts: Vec<Vec<f32>> = raws
            .iter()
            .map(|raw| {
                let mut z = vec![0.0f32; n];
                for i in 0..n {
                    z[i] = (raw[i] - self.mu[i]) * self.inv_sd[i];
                }
                z
            })
            .collect();
        // trunk layers: input-blocks of 4 through the register-blocked kernel
        // (weights stream once per block; the x-block stays L1-resident),
        // remaining 1-3 inputs through the plain dot (same accumulation order).
        for l in 0..self.tw.len() {
            let (i, o) = (self.tdims[l], self.tdims[l + 1]);
            let w = &self.tw[l];
            let b = &self.tb[l];
            let mut next: Vec<Vec<f32>> = vec![vec![0.0f32; o]; k];
            let mut kk = 0usize;
            while kk + 4 <= k {
                for oi in 0..o {
                    let row = &w[oi * i..oi * i + i];
                    let d = dot4(row, [&acts[kk], &acts[kk + 1], &acts[kk + 2], &acts[kk + 3]]);
                    for j in 0..4 {
                        next[kk + j][oi] = b[oi] + d[j];
                    }
                }
                kk += 4;
            }
            while kk < k {
                for oi in 0..o {
                    let row = &w[oi * i..oi * i + i];
                    next[kk][oi] = b[oi] + dot(row, &acts[kk]);
                }
                kk += 1;
            }
            for nx in next.iter_mut() {
                relu_inplace(nx);
            }
            acts = next;
        }
        let hd = *self.tdims.last().unwrap();
        // value head for every row (1 x H — trivial)
        let mut out: Vec<(f32, Vec<f32>)> = acts
            .iter()
            .map(|act| ((self.vb[0] + dot(&self.vw[..hd], act)).tanh(), Vec::new()))
            .collect();
        // policy head over the rows that need it, same 4-input blocking
        let wants: Vec<usize> = (0..k).filter(|&kk| need_policy[kk]).collect();
        for &kk in &wants {
            out[kk].1 = vec![0.0f32; self.n_act];
        }
        let mut wi = 0usize;
        while wi + 4 <= wants.len() {
            let (k0, k1, k2, k3) = (wants[wi], wants[wi + 1], wants[wi + 2], wants[wi + 3]);
            for a in 0..self.n_act {
                let row = &self.pw[a * hd..a * hd + hd];
                let d = dot4(row, [&acts[k0], &acts[k1], &acts[k2], &acts[k3]]);
                out[k0].1[a] = self.pb[a] + d[0];
                out[k1].1[a] = self.pb[a] + d[1];
                out[k2].1[a] = self.pb[a] + d[2];
                out[k3].1[a] = self.pb[a] + d[3];
            }
            wi += 4;
        }
        while wi < wants.len() {
            let kk = wants[wi];
            for a in 0..self.n_act {
                let row = &self.pw[a * hd..a * hd + hd];
                out[kk].1[a] = self.pb[a] + dot(row, &acts[kk]);
            }
            wi += 1;
        }
        out
    }
}

/// The one abstraction the search/leaf/batch drivers need from a policy+value
/// net — implemented by the f32 `PolicyValueNet` (delegating to its inherent
/// methods) and the int8 `QuantPolicyValueNet`, so `:netval8` players run
/// through the exact same search code as f32 ones. `encode_state` is the
/// ENCODER seam: a net carries its own feature version (inferred from its
/// input dim at load), so v1 and v2 nets face each other in one gate and the
/// wasm serves whichever model blob it fetched with the right encoder.
pub trait PvEval: Sync {
    fn forward_raw(&self, raw: &[f32]) -> (f32, Vec<f32>);
    fn forward_value_raw(&self, raw: &[f32]) -> f32;
    fn forward_batch(&self, raws: &[&[f32]], need_policy: &[bool]) -> Vec<(f32, Vec<f32>)>;
    fn encode_state(&self, s: &crate::engine::State, seat: usize) -> Vec<f32>;
}

impl PvEval for PolicyValueNet {
    fn forward_raw(&self, raw: &[f32]) -> (f32, Vec<f32>) {
        PolicyValueNet::forward_raw(self, raw)
    }
    fn forward_value_raw(&self, raw: &[f32]) -> f32 {
        PolicyValueNet::forward_value_raw(self, raw)
    }
    fn forward_batch(&self, raws: &[&[f32]], need_policy: &[bool]) -> Vec<(f32, Vec<f32>)> {
        PolicyValueNet::forward_batch(self, raws, need_policy)
    }
    fn encode_state(&self, s: &crate::engine::State, seat: usize) -> Vec<f32> {
        crate::feats::encode(self.enc, s, seat)
    }
}

// ─── int8 + VNNI quantized PV net ────────────────────────────────────────────
// Trunk layers (96% of the MACs) quantized to int8 at LOAD from the f32 net (no
// new file format): per-output-row symmetric weight scales, DYNAMIC per-vector
// activation quantization (scale = amax/127, zero-point 128 -> u8 for
// vpdpbusd's u8 x i8 form, with the precomputed 128*rowsum correction). Heads
// + z-scoring stay f32. Integer accumulation is EXACT, so the VNNI and scalar
// fallback paths produce identical outputs (deterministic across machines) —
// but int8 != f32, so this is an OPT-IN net (:netval8 / netval8 mode) gated by
// STRENGTH vs the f32 netval, not by float parity.

/// u8 x i8 dot with i32 accumulation — AVX-512 VNNI (`vpdpbusd`) when compiled
/// for it (target-cpu=native on the Zen 4 box), exact-same-result scalar loop
/// otherwise (wasm/CI).
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

#[cfg(not(all(target_arch = "x86_64", target_feature = "avx512vnni")))]
#[inline]
fn qdot(w: &[i8], x: &[u8]) -> i32 {
    let mut s = 0i32;
    for (wi, xi) in w.iter().zip(x.iter()) {
        s += (*xi as i32) * (*wi as i32);
    }
    s
}

/// Quantize one activation vector: symmetric i8 (amax/127) shifted to u8 with
/// zero-point 128. Returns (quantized, scale).
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

pub struct QuantPolicyValueNet {
    enc: crate::feats::Enc,
    mu: Vec<f32>,
    inv_sd: Vec<f32>,
    tdims: Vec<usize>,
    qw: Vec<Vec<i8>>,   // per trunk layer: row-major int8 weights
    qs: Vec<Vec<f32>>,  // per layer: per-row weight scale
    qrs: Vec<Vec<i32>>, // per layer: per-row weight sum (zero-point correction)
    tb: Vec<Vec<f32>>,  // f32 biases
    vw: Vec<f32>,
    vb: Vec<f32>,
    pw: Vec<f32>,
    pb: Vec<f32>,
    n_act: usize,
}

impl QuantPolicyValueNet {
    pub fn from_f32(net: &PolicyValueNet) -> Self {
        let mut qw = Vec::new();
        let mut qs = Vec::new();
        let mut qrs = Vec::new();
        for l in 0..net.tw.len() {
            let (i, o) = (net.tdims[l], net.tdims[l + 1]);
            let w = &net.tw[l];
            let mut lw = vec![0i8; i * o];
            let mut ls = vec![1.0f32; o];
            let mut lrs = vec![0i32; o];
            for oi in 0..o {
                let row = &w[oi * i..oi * i + i];
                let mut amax = 0.0f32;
                for &v in row {
                    amax = amax.max(v.abs());
                }
                let s = if amax > 0.0 { amax / 127.0 } else { 1.0 };
                let inv = 1.0 / s;
                let mut rs = 0i32;
                for (j, &v) in row.iter().enumerate() {
                    let q = (v * inv).round().clamp(-127.0, 127.0) as i32;
                    lw[oi * i + j] = q as i8;
                    rs += q;
                }
                ls[oi] = s;
                lrs[oi] = rs;
            }
            qw.push(lw);
            qs.push(ls);
            qrs.push(lrs);
        }
        QuantPolicyValueNet {
            enc: net.enc,
            mu: net.mu.clone(),
            inv_sd: net.inv_sd.clone(),
            tdims: net.tdims.clone(),
            qw,
            qs,
            qrs,
            tb: net.tb.clone(),
            vw: net.vw.clone(),
            vb: net.vb.clone(),
            pw: net.pw.clone(),
            pb: net.pb.clone(),
            n_act: net.n_act,
        }
    }

    /// Quantized trunk: standardize f32 -> per layer (quantize acts -> int8
    /// matvec -> dequant + bias + ReLU in f32).
    fn trunk_q(&self, raw: &[f32]) -> Vec<f32> {
        let n = self.mu.len();
        let mut cur = vec![0.0f32; n];
        for i in 0..n {
            cur[i] = (raw[i] - self.mu[i]) * self.inv_sd[i];
        }
        let mut xq: Vec<u8> = Vec::new();
        for l in 0..self.qw.len() {
            let (i, o) = (self.tdims[l], self.tdims[l + 1]);
            let sx = quantize_act(&cur, &mut xq);
            let mut next = vec![0.0f32; o];
            let w = &self.qw[l];
            for oi in 0..o {
                let acc = qdot(&w[oi * i..oi * i + i], &xq);
                let corrected = acc - 128 * self.qrs[l][oi];
                let y = corrected as f32 * (sx * self.qs[l][oi]) + self.tb[l][oi];
                next[oi] = if y > 0.0 { y } else { 0.0 };
            }
            cur = next;
        }
        cur
    }
}

impl PvEval for QuantPolicyValueNet {
    fn forward_raw(&self, raw: &[f32]) -> (f32, Vec<f32>) {
        let cur = self.trunk_q(raw);
        let hd = *self.tdims.last().unwrap();
        let v = (self.vb[0] + dot(&self.vw[..hd], &cur)).tanh();
        let mut po = vec![0.0f32; self.n_act];
        linear(&self.pw, &self.pb, &cur, self.n_act, hd, &mut po);
        (v, po)
    }
    fn forward_value_raw(&self, raw: &[f32]) -> f32 {
        let cur = self.trunk_q(raw);
        let hd = *self.tdims.last().unwrap();
        (self.vb[0] + dot(&self.vw[..hd], &cur)).tanh()
    }
    /// Per-input loop: with int8 the whole model is ~640KB (L2-resident), so
    /// the memory-traffic case for cross-input blocking largely evaporates.
    fn forward_batch(&self, raws: &[&[f32]], need_policy: &[bool]) -> Vec<(f32, Vec<f32>)> {
        raws.iter()
            .zip(need_policy)
            .map(|(raw, &np)| {
                if np {
                    self.forward_raw(raw)
                } else {
                    (self.forward_value_raw(raw), Vec::new())
                }
            })
            .collect()
    }
    fn encode_state(&self, s: &crate::engine::State, seat: usize) -> Vec<f32> {
        crate::feats::encode(self.enc, s, seat)
    }
}

// ─── Single-block self-attention over entity tokens ──────────────────────────
// tokens: T x d → linear Q,K,V (d x d) → softmax(QKᵀ/√d) V → residual+meanpool → MLP head → scalar.
pub struct AttnNet {
    t: usize,
    d: usize,
    wq: Vec<f32>, wk: Vec<f32>, wv: Vec<f32>, // each d x d row-major
    head: Mlp,                                 // d → hh → 1
}

impl AttnNet {
    pub fn random(t: usize, d: usize, head_hidden: usize, seed: u64) -> Self {
        let mut rng = Rng::new(seed);
        let s = (1.0 / d as f32).sqrt();
        AttnNet {
            t, d,
            wq: rand_vec(&mut rng, d * d, s),
            wk: rand_vec(&mut rng, d * d, s),
            wv: rand_vec(&mut rng, d * d, s),
            head: Mlp::random(&[d, head_hidden, 1], seed ^ 0x9e3779b9),
        }
    }

    /// tokens: flat T*d (row-major, one row per entity token). Returns scalar value.
    pub fn forward(&self, tokens: &[f32]) -> f32 {
        let (t, d) = (self.t, self.d);
        // project Q,K,V : (T x d)
        let mut q = vec![0.0f32; t * d];
        let mut k = vec![0.0f32; t * d];
        let mut v = vec![0.0f32; t * d];
        for r in 0..t {
            let row = &tokens[r * d..r * d + d];
            linear(&self.wq, &vec![0.0; d], row, d, d, &mut q[r * d..r * d + d]);
            linear(&self.wk, &vec![0.0; d], row, d, d, &mut k[r * d..r * d + d]);
            linear(&self.wv, &vec![0.0; d], row, d, d, &mut v[r * d..r * d + d]);
        }
        let scale = 1.0 / (d as f32).sqrt();
        // attention output, mean-pooled over tokens → context (d)
        let mut ctx = vec![0.0f32; d];
        for i in 0..t {
            // scores over j, softmax
            let mut scores = vec![0.0f32; t];
            let mut mx = f32::NEG_INFINITY;
            for j in 0..t {
                let mut dot = 0.0f32;
                for c in 0..d {
                    dot += q[i * d + c] * k[j * d + c];
                }
                scores[j] = dot * scale;
                if scores[j] > mx {
                    mx = scores[j];
                }
            }
            let mut sum = 0.0f32;
            for j in 0..t {
                scores[j] = (scores[j] - mx).exp();
                sum += scores[j];
            }
            // weighted V, accumulate into ctx (we mean-pool the per-token attn outputs)
            for j in 0..t {
                let wgt = scores[j] / sum;
                for c in 0..d {
                    ctx[c] += wgt * v[j * d + c];
                }
            }
        }
        for c in 0..d {
            ctx[c] /= t as f32;
        }
        self.head.forward(&ctx)
    }
}
