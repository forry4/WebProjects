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

/// Chunked multi-accumulator dot product. The single-accumulator form is a serial
/// FP dependency chain the compiler may NOT vectorize (float reassociation is
/// forbidden), which ran the matvec at ~1% of the core's FMA throughput — 32
/// independent lanes let LLVM emit SIMD FMAs (AVX2/AVX-512 with target-cpu=native,
/// simd128 on wasm). Summation order differs from the scalar form by ~1e-6 relative
/// — net_export_check's 1e-4 parity bar still holds (re-verified after this change).
#[inline]
fn dot(a: &[f32], b: &[f32]) -> f32 {
    const L: usize = 8;
    let mut acc = [[0.0f32; L]; 4];
    let mut ca = a.chunks_exact(4 * L);
    let mut cb = b.chunks_exact(4 * L);
    for (xa, xb) in (&mut ca).zip(&mut cb) {
        for k in 0..4 {
            for l in 0..L {
                acc[k][l] += xa[k * L + l] * xb[k * L + l];
            }
        }
    }
    let mut s = 0.0f32;
    for k in 0..4 {
        for l in 0..L {
            s += acc[k][l];
        }
    }
    for (xa, xb) in ca.remainder().iter().zip(cb.remainder()) {
        s += xa * xb;
    }
    s
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
        PolicyValueNet { mu, inv_sd, tdims, tw, tb, vw, vb, pw, pb, n_act }
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
