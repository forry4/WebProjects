//! Attention forward for the P4b campaign — a runtime-parameterized adaptation
//! of spender-core's PROVEN attn.rs (18x24 -> D64 -> 2x[4-head MHA + FFN128] ->
//! pool + state-embed -> trunk -> heads), so one implementation serves both the
//! throughput gate (random weights, shape sweep) and the eventual real net
//! (weights loaded from the torch twin once the schema is locked). Runtime dims
//! cost nothing here: the matmuls dominate and their loop bounds are dynamic
//! either way. Computed in f32 (matches an f32-trained torch net).
use crate::rng::Rng;

#[derive(Clone, Copy)]
pub struct AttnCfg {
    pub t: usize,      // token count
    pub f: usize,      // feats per token
    pub d: usize,      // embed dim
    pub heads: usize,  // attention heads (d % heads == 0)
    pub ff: usize,     // FFN hidden
    pub layers: usize, // MHA+FFN blocks
    pub state: usize,  // flat state-vector feats
    pub trunk: usize,  // post-pool trunk width
    pub nact: usize,   // global policy logits
}

pub struct AttnNet {
    pub cfg: AttnCfg,
    emb_w: Vec<f32>, emb_b: Vec<f32>,
    wq: Vec<Vec<f32>>, wk: Vec<Vec<f32>>, wv: Vec<Vec<f32>>, wo: Vec<Vec<f32>>,
    f1w: Vec<Vec<f32>>, f1b: Vec<Vec<f32>>, f2w: Vec<Vec<f32>>, f2b: Vec<Vec<f32>>,
    sw: Vec<f32>, sb: Vec<f32>, tw: Vec<f32>, tb: Vec<f32>,
    vw: Vec<f32>, vb: Vec<f32>, pw: Vec<f32>, pb: Vec<f32>,
    ptok_w: Vec<f32>, ptok_b: Vec<f32>,
}

#[inline]
fn linear(x: &[f32], w: &[f32], b: &[f32], k: usize, m: usize, y: &mut [f32]) {
    // chunked multi-accumulator dot (valuenet's round-1 kernel) — the naive
    // single-accumulator loop is a serial FP chain LLVM cannot vectorize and
    // measured 3-4x slower on this exact forward.
    for mi in 0..m {
        let base = if b.is_empty() { 0.0 } else { b[mi] };
        y[mi] = base + crate::valuenet::dot(&w[mi * k..(mi + 1) * k], &x[..k]);
    }
}

#[inline]
fn layernorm(x: &mut [f32]) {
    let n = x.len() as f32;
    let mean = x.iter().sum::<f32>() / n;
    let var = x.iter().map(|&v| (v - mean) * (v - mean)).sum::<f32>() / n;
    let inv = 1.0 / (var + 1e-5).sqrt();
    for v in x.iter_mut() {
        *v = (*v - mean) * inv;
    }
}

impl AttnNet {
    /// Random-weight net for throughput probes (weights small enough that the
    /// masked softmax stays well-conditioned).
    pub fn random(cfg: AttnCfg, seed: u64) -> AttnNet {
        assert_eq!(cfg.d % cfg.heads, 0);
        let mut rng = Rng::new(seed);
        let mut w = |n: usize| -> Vec<f32> {
            (0..n).map(|_| ((rng.next_u64() % 2000) as f32 / 1000.0 - 1.0) * 0.08).collect()
        };
        let per_layer = |w: &mut dyn FnMut(usize) -> Vec<f32>, n: usize, l: usize| {
            (0..l).map(|_| w(n)).collect::<Vec<_>>()
        };
        let (d, f, ff, l) = (cfg.d, cfg.f, cfg.ff, cfg.layers);
        AttnNet {
            cfg,
            emb_w: w(d * f), emb_b: w(d),
            wq: per_layer(&mut w, d * d, l), wk: per_layer(&mut w, d * d, l),
            wv: per_layer(&mut w, d * d, l), wo: per_layer(&mut w, d * d, l),
            f1w: per_layer(&mut w, ff * d, l), f1b: per_layer(&mut w, ff, l),
            f2w: per_layer(&mut w, d * ff, l), f2b: per_layer(&mut w, d, l),
            sw: w(d * cfg.state), sb: w(d),
            tw: w(cfg.trunk * 2 * d), tb: w(cfg.trunk),
            vw: w(cfg.trunk), vb: w(1),
            pw: w(N_GLOBAL * cfg.trunk), pb: w(N_GLOBAL),
            ptok_w: w(2 * d), ptok_b: w(2),
        }
    }

    /// (tanh value, nact global logits). `tokens` = t*f, `mask` = t, `state` = state.
    /// Includes a per-token 2-logit head so the probe carries the full serving cost.
    pub fn forward(&self, tokens: &[f32], mask: &[f32], state: &[f32]) -> (f32, Vec<f32>) {
        let c = self.cfg;
        let (t_n, d, hd) = (c.t, c.d, c.d / c.heads);
        let nob: Vec<f32> = vec![];
        let mut x = vec![0f32; t_n * d];
        for t in 0..t_n {
            linear(&tokens[t * c.f..(t + 1) * c.f], &self.emb_w, &self.emb_b, c.f, d,
                   &mut x[t * d..(t + 1) * d]);
        }
        let scale = 1.0 / (hd as f32).sqrt();
        let (mut q, mut k, mut v) = (vec![0f32; t_n * d], vec![0f32; t_n * d], vec![0f32; t_n * d]);
        let mut ctx = vec![0f32; t_n * d];
        let mut sc = vec![0f32; t_n];
        for l in 0..c.layers {
            for t in 0..t_n {
                linear(&x[t * d..(t + 1) * d], &self.wq[l], &nob, d, d, &mut q[t * d..(t + 1) * d]);
                linear(&x[t * d..(t + 1) * d], &self.wk[l], &nob, d, d, &mut k[t * d..(t + 1) * d]);
                linear(&x[t * d..(t + 1) * d], &self.wv[l], &nob, d, d, &mut v[t * d..(t + 1) * d]);
            }
            for h in 0..c.heads {
                let off = h * hd;
                for i in 0..t_n {
                    let mut mx = f32::NEG_INFINITY;
                    for j in 0..t_n {
                        if mask[j] < 0.5 {
                            sc[j] = f32::NEG_INFINITY;
                            continue;
                        }
                        let mut s = 0.0;
                        for dd in 0..hd {
                            s += q[i * d + off + dd] * k[j * d + off + dd];
                        }
                        s *= scale;
                        sc[j] = s;
                        if s > mx {
                            mx = s;
                        }
                    }
                    let mut den = 0.0;
                    for j in 0..t_n {
                        if mask[j] >= 0.5 {
                            sc[j] = (sc[j] - mx).exp();
                            den += sc[j];
                        }
                    }
                    for dd in 0..hd {
                        let mut acc = 0.0;
                        for j in 0..t_n {
                            if mask[j] >= 0.5 {
                                acc += sc[j] * v[j * d + off + dd];
                            }
                        }
                        ctx[i * d + off + dd] = acc / den;
                    }
                }
            }
            for t in 0..t_n {
                let mut o = vec![0f32; d];
                linear(&ctx[t * d..(t + 1) * d], &self.wo[l], &nob, d, d, &mut o);
                for dd in 0..d {
                    x[t * d + dd] += o[dd];
                }
                layernorm(&mut x[t * d..(t + 1) * d]);
            }
            for t in 0..t_n {
                let mut h1 = vec![0f32; c.ff];
                linear(&x[t * d..(t + 1) * d], &self.f1w[l], &self.f1b[l], d, c.ff, &mut h1);
                for vv in h1.iter_mut() {
                    if *vv < 0.0 {
                        *vv = 0.0;
                    }
                }
                let mut h2 = vec![0f32; d];
                linear(&h1, &self.f2w[l], &self.f2b[l], c.ff, d, &mut h2);
                for dd in 0..d {
                    x[t * d + dd] += h2[dd];
                }
                layernorm(&mut x[t * d..(t + 1) * d]);
            }
        }
        let mut pool = vec![0f32; d];
        let mut cnt = 0.0;
        for t in 0..t_n {
            if mask[t] >= 0.5 {
                cnt += 1.0;
                for dd in 0..d {
                    pool[dd] += x[t * d + dd];
                }
            }
        }
        if cnt > 0.0 {
            for dd in 0..d {
                pool[dd] /= cnt;
            }
        }
        let mut se = vec![0f32; d];
        linear(state, &self.sw, &self.sb, c.state, d, &mut se);
        let mut cat = vec![0f32; 2 * d];
        cat[..d].copy_from_slice(&pool);
        cat[d..].copy_from_slice(&se);
        let mut ht = vec![0f32; c.trunk];
        linear(&cat, &self.tw, &self.tb, 2 * d, c.trunk, &mut ht);
        for vv in ht.iter_mut() {
            if *vv < 0.0 {
                *vv = 0.0;
            }
        }
        let mut val = [0f32; 1];
        linear(&ht, &self.vw, &self.vb, c.trunk, 1, &mut val);
        // Policy: 80 GLOBAL logits from the trunk scattered to their action ids,
        // + token-TIED logits from each mappable token's own embedding (the
        // Spender trick — a take/buy/discard/place is scored by the tile it
        // touches). Masked-token tied actions stay at NEG (they are illegal
        // whenever the token is empty, so the prior never reads them).
        let mut gl = vec![0f32; N_GLOBAL];
        linear(&ht, &self.pw, &self.pb, c.trunk, N_GLOBAL, &mut gl);
        let mut pol = vec![NEG; c.nact];
        for (gi, ai) in global_action_ids().enumerate() {
            pol[ai] = gl[gi];
        }
        let mut ptok = [0f32; 2];
        for t in 0..TIED_TOKENS.min(t_n) {
            if mask[t] < 0.5 {
                continue;
            }
            linear(&x[t * d..(t + 1) * d], &self.ptok_w, &self.ptok_b, d, 2, &mut ptok);
            let (a0, a1) = tied_actions(t);
            pol[a0] = ptok[0];
            if let Some(a1) = a1 {
                pol[a1] = ptok[1];
            }
        }
        (val[0].tanh(), pol)
    }
}

pub const NEG: f32 = -1e9;
/// Tokens 0..19 carry tied actions (12 depot + 4 black + 3 my-storage).
pub const TIED_TOKENS: usize = 19;
pub const N_TIED: usize = 22; // 12 take + 4 buy + 3 discard + 3 place
pub const N_GLOBAL: usize = crate::engine::N_ACTIONS - N_TIED; // 80

/// Token index -> (tied action, optional second tied action). Mirrors the
/// tokfeats token layout; MUST match attn_net.py's scatter exactly.
#[inline]
pub fn tied_actions(t: usize) -> (usize, Option<usize>) {
    use crate::engine::{A_BUY_BLACK0, A_DISCARD0, A_PLACE_SLOT0, A_TAKE_HEX0};
    match t {
        0..=11 => (A_TAKE_HEX0 + t, None),
        12..=15 => (A_BUY_BLACK0 + (t - 12), None),
        16..=18 => (A_DISCARD0 + (t - 16), Some(A_PLACE_SLOT0 + (t - 16))),
        _ => unreachable!("token {t} has no tied action"),
    }
}

/// The 80 action ids served by the global head, ascending (all ids minus the
/// 22 token-tied ones).
pub fn global_action_ids() -> impl Iterator<Item = usize> {
    (0..crate::engine::N_ACTIONS).filter(|&a| {
        use crate::engine::{A_BUY_BLACK0, A_DISCARD0, A_PLACE_SLOT0, A_TAKE_HEX0};
        !(A_TAKE_HEX0..A_TAKE_HEX0 + 12).contains(&a)
            && !(A_BUY_BLACK0..A_BUY_BLACK0 + 4).contains(&a)
            && !(A_DISCARD0..A_DISCARD0 + 3).contains(&a)
            && !(A_PLACE_SLOT0..A_PLACE_SLOT0 + 3).contains(&a)
    })
}

/// The production CoC attention config (the P4b throughput-gate winner).
pub fn coc_cfg() -> AttnCfg {
    AttnCfg {
        t: crate::tokfeats::TOK_N,
        f: crate::tokfeats::TOK_F,
        d: 48,
        heads: 4,
        ff: 96,
        layers: 2,
        state: crate::tokfeats::TOK_STATE,
        trunk: 128,
        nact: crate::engine::N_ACTIONS,
    }
}

impl crate::valuenet::PvEval for AttnNet {
    fn forward_raw(&self, raw: &[f32]) -> (f32, Vec<f32>) {
        let c = self.cfg;
        debug_assert_eq!(raw.len(), c.t * c.f + c.t + c.state);
        let (tokens, rest) = raw.split_at(c.t * c.f);
        let (mask, state) = rest.split_at(c.t);
        self.forward(tokens, mask, state)
    }
    fn forward_value_raw(&self, raw: &[f32]) -> f32 {
        self.forward_raw(raw).0
    }
    fn forward_batch(&self, raws: &[&[f32]], _need_policy: &[bool]) -> Vec<(f32, Vec<f32>)> {
        // no batched kernel: the wasm A/B showed batching doesn't pay off-GPU,
        // and attention training/self-play run on the torch sidecar anyway
        raws.iter().map(|r| self.forward_raw(r)).collect()
    }
    fn encode_state(&self, s: &crate::engine::State, seat: usize) -> Vec<f32> {
        crate::tokfeats::encode_row(s, seat)
    }
}

#[cfg(feature = "bridge")]
#[derive(serde::Deserialize)]
struct AttnJson {
    t: usize, f: usize, d: usize, heads: usize, ff: usize, layers: usize,
    state: usize, trunk: usize,
    emb_w: Vec<f32>, emb_b: Vec<f32>,
    wq: Vec<Vec<f32>>, wk: Vec<Vec<f32>>, wv: Vec<Vec<f32>>, wo: Vec<Vec<f32>>,
    f1w: Vec<Vec<f32>>, f1b: Vec<Vec<f32>>, f2w: Vec<Vec<f32>>, f2b: Vec<Vec<f32>>,
    sw: Vec<f32>, sb: Vec<f32>, tw: Vec<f32>, tb: Vec<f32>,
    vw: Vec<f32>, vb: Vec<f32>, pw: Vec<f32>, pb: Vec<f32>,
    ptok_w: Vec<f32>, ptok_b: Vec<f32>,
}

#[cfg(feature = "bridge")]
impl AttnNet {
    pub fn from_json_str(js: &str) -> AttnNet {
        let j: AttnJson = serde_json::from_str(js).expect("parse attn json");
        let cfg = AttnCfg {
            t: j.t, f: j.f, d: j.d, heads: j.heads, ff: j.ff, layers: j.layers,
            state: j.state, trunk: j.trunk, nact: crate::engine::N_ACTIONS,
        };
        assert_eq!(j.pw.len(), N_GLOBAL * j.trunk, "global head shape");
        assert_eq!(j.ptok_w.len(), 2 * j.d, "token head shape");
        AttnNet {
            cfg,
            emb_w: j.emb_w, emb_b: j.emb_b, wq: j.wq, wk: j.wk, wv: j.wv, wo: j.wo,
            f1w: j.f1w, f1b: j.f1b, f2w: j.f2w, f2b: j.f2b,
            sw: j.sw, sb: j.sb, tw: j.tw, tb: j.tb, vw: j.vw, vb: j.vb,
            pw: j.pw, pb: j.pb, ptok_w: j.ptok_w, ptok_b: j.ptok_b,
        }
    }
    pub fn from_json(path: &str) -> AttnNet {
        Self::from_json_str(&std::fs::read_to_string(path).expect("read attn json"))
    }
}
