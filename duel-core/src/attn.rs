//! Card-set ATTENTION value net for Duel (value-only v1). Attention over the pyramid + own-reserved
//! card tokens plus a geometry/deck-aware global state. Ported from `spender-core::attn` with the
//! POLICY HEAD DROPPED. Parity-locked to the PyTorch twin (`tools/attn_net.py`) via `bin/attn_parity`
//! to 1e-6 — it must PLAY (this forward) what it TRAINS (torch), so nothing is gated until parity holds.
//!
//! embed(TOK_F->D) -> L x [4-head masked self-attn + FFN(D->FF->D), residual + no-affine LayerNorm]
//!   -> masked mean-pool over present tokens ++ state-embed(TOK_STATE->D) -> trunk(2D->H)+ReLU
//!   -> value head(H->1) -> tanh. Computed in f32 to match the f32-trained net.

use crate::engine::State;
use crate::feats::{features_tokens, TOK_F, TOK_N, TOK_STATE};

const D: usize = 64;
const HEADS: usize = 4;
const HD: usize = D / HEADS;
const FF: usize = 128;
const L: usize = 2;
const H: usize = 128;

pub struct AttnNet {
    pub emb_w: Vec<f32>,
    pub emb_b: Vec<f32>,
    pub wq: Vec<Vec<f32>>,
    pub wk: Vec<Vec<f32>>,
    pub wv: Vec<Vec<f32>>,
    pub wo: Vec<Vec<f32>>,
    pub f1w: Vec<Vec<f32>>,
    pub f1b: Vec<Vec<f32>>,
    pub f2w: Vec<Vec<f32>>,
    pub f2b: Vec<Vec<f32>>,
    pub sw: Vec<f32>,
    pub sb: Vec<f32>,
    pub tw: Vec<f32>,
    pub tb: Vec<f32>,
    pub vw: Vec<f32>,
    pub vb: Vec<f32>,
}

#[inline]
fn linear(x: &[f32], w: &[f32], b: &[f32], k: usize, m: usize, y: &mut [f32]) {
    for mi in 0..m {
        let mut s = if b.is_empty() { 0.0 } else { b[mi] };
        let row = mi * k;
        for ki in 0..k {
            s += x[ki] * w[row + ki];
        }
        y[mi] = s;
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
    /// value in [-1, 1]. `tokens` = TOK_N*TOK_F f64, `mask` = TOK_N, `state` = TOK_STATE.
    pub fn value(&self, tokens: &[f64], mask: &[f64], state: &[f64]) -> f64 {
        let tok: Vec<f32> = tokens.iter().map(|&x| x as f32).collect();
        let msk: Vec<f32> = mask.iter().map(|&x| x as f32).collect();
        let st: Vec<f32> = state.iter().map(|&x| x as f32).collect();
        let nob: Vec<f32> = vec![];

        // token embed
        let mut x = vec![0f32; TOK_N * D];
        for t in 0..TOK_N {
            let mut e = vec![0f32; D];
            linear(&tok[t * TOK_F..t * TOK_F + TOK_F], &self.emb_w, &self.emb_b, TOK_F, D, &mut e);
            x[t * D..t * D + D].copy_from_slice(&e);
        }

        let scale = 1.0 / (HD as f32).sqrt();
        for l in 0..L {
            let (mut q, mut k, mut v) =
                (vec![0f32; TOK_N * D], vec![0f32; TOK_N * D], vec![0f32; TOK_N * D]);
            for t in 0..TOK_N {
                linear(&x[t * D..t * D + D], &self.wq[l], &nob, D, D, &mut q[t * D..t * D + D]);
                linear(&x[t * D..t * D + D], &self.wk[l], &nob, D, D, &mut k[t * D..t * D + D]);
                linear(&x[t * D..t * D + D], &self.wv[l], &nob, D, D, &mut v[t * D..t * D + D]);
            }
            let mut ctx = vec![0f32; TOK_N * D];
            for h in 0..HEADS {
                let off = h * HD;
                for i in 0..TOK_N {
                    let mut sc = vec![f32::NEG_INFINITY; TOK_N];
                    let mut mx = f32::NEG_INFINITY;
                    for j in 0..TOK_N {
                        if msk[j] < 0.5 {
                            continue;
                        }
                        let mut s = 0.0;
                        for d in 0..HD {
                            s += q[i * D + off + d] * k[j * D + off + d];
                        }
                        s *= scale;
                        sc[j] = s;
                        if s > mx {
                            mx = s;
                        }
                    }
                    let mut den = 0.0;
                    for j in 0..TOK_N {
                        if msk[j] >= 0.5 {
                            sc[j] = (sc[j] - mx).exp();
                            den += sc[j];
                        }
                    }
                    for d in 0..HD {
                        let mut acc = 0.0;
                        for j in 0..TOK_N {
                            if msk[j] >= 0.5 {
                                acc += sc[j] * v[j * D + off + d];
                            }
                        }
                        ctx[i * D + off + d] = acc / den;
                    }
                }
            }
            for t in 0..TOK_N {
                let mut o = vec![0f32; D];
                linear(&ctx[t * D..t * D + D], &self.wo[l], &nob, D, D, &mut o);
                for d in 0..D {
                    x[t * D + d] += o[d];
                }
                layernorm(&mut x[t * D..t * D + D]);
            }
            for t in 0..TOK_N {
                let mut h1 = vec![0f32; FF];
                linear(&x[t * D..t * D + D], &self.f1w[l], &self.f1b[l], D, FF, &mut h1);
                for vv in h1.iter_mut() {
                    if *vv < 0.0 {
                        *vv = 0.0;
                    }
                }
                let mut h2 = vec![0f32; D];
                linear(&h1, &self.f2w[l], &self.f2b[l], FF, D, &mut h2);
                for d in 0..D {
                    x[t * D + d] += h2[d];
                }
                layernorm(&mut x[t * D..t * D + D]);
            }
        }

        // masked mean-pool ++ state embed -> trunk -> value
        let mut pool = vec![0f32; D];
        let mut cnt = 0.0;
        for t in 0..TOK_N {
            if msk[t] >= 0.5 {
                cnt += 1.0;
                for d in 0..D {
                    pool[d] += x[t * D + d];
                }
            }
        }
        if cnt > 0.0 {
            for d in 0..D {
                pool[d] /= cnt;
            }
        }
        let mut se = vec![0f32; D];
        linear(&st, &self.sw, &self.sb, TOK_STATE, D, &mut se);
        let mut cat = vec![0f32; 2 * D];
        cat[..D].copy_from_slice(&pool);
        cat[D..].copy_from_slice(&se);
        let mut ht = vec![0f32; H];
        linear(&cat, &self.tw, &self.tb, 2 * D, H, &mut ht);
        for vv in ht.iter_mut() {
            if *vv < 0.0 {
                *vv = 0.0;
            }
        }
        let mut val = vec![0f32; 1];
        linear(&ht, &self.vw, &self.vb, H, 1, &mut val);
        val[0].tanh() as f64
    }

    /// Leaf value from `seat`'s perspective — tokenizes then forwards.
    pub fn eval(&self, st: &State, seat: usize) -> f64 {
        let (t, m, s) = features_tokens(st, seat);
        self.value(&t, &m, &s)
    }
}

#[cfg(any(feature = "bridge", target_arch = "wasm32"))]
#[derive(serde::Deserialize)]
struct AttnJson {
    emb_w: Vec<f32>,
    emb_b: Vec<f32>,
    wq: Vec<Vec<f32>>,
    wk: Vec<Vec<f32>>,
    wv: Vec<Vec<f32>>,
    wo: Vec<Vec<f32>>,
    f1w: Vec<Vec<f32>>,
    f1b: Vec<Vec<f32>>,
    f2w: Vec<Vec<f32>>,
    f2b: Vec<Vec<f32>>,
    sw: Vec<f32>,
    sb: Vec<f32>,
    tw: Vec<f32>,
    tb: Vec<f32>,
    vw: Vec<f32>,
    vb: Vec<f32>,
}

#[cfg(any(feature = "bridge", target_arch = "wasm32"))]
impl AttnNet {
    pub fn from_json_str(s: &str) -> Result<Self, String> {
        let j: AttnJson = serde_json::from_str(s).map_err(|e| e.to_string())?;
        Ok(AttnNet {
            emb_w: j.emb_w, emb_b: j.emb_b, wq: j.wq, wk: j.wk, wv: j.wv, wo: j.wo,
            f1w: j.f1w, f1b: j.f1b, f2w: j.f2w, f2b: j.f2b,
            sw: j.sw, sb: j.sb, tw: j.tw, tb: j.tb, vw: j.vw, vb: j.vb,
        })
    }
}
