//! Card-set ATTENTION value net for Duel (value-only v1). Attention over the pyramid + own-reserved
//! card tokens plus a geometry/deck-aware global state. Ported from `spender-core::attn` with the
//! POLICY HEAD DROPPED. Parity-locked to the PyTorch twin (`tools/attn_net.py`) via `bin/attn_parity`
//! to 1e-6 — it must PLAY (this forward) what it TRAINS (torch), so nothing is gated until parity holds.
//!
//! embed(TOK_F->D) -> L x [4-head masked self-attn + FFN(D->FF->D), residual + no-affine LayerNorm]
//!   -> masked mean-pool over present tokens ++ state-embed(TOK_STATE->D) -> trunk(2D->H)+ReLU
//!   -> value head(H->1) -> tanh. Computed in f32 to match the f32-trained net.
//!
//! PERF: the forward is called once per MCTS sim (millions/search), on a tiny net (15 tokens), so
//! per-call heap allocation — not arithmetic — dominated. All scratch buffers now live in a
//! thread-local, reused across calls; the math is byte-identical (same ops, same order), verified by
//! `bin/attn_parity`. Buffers are fully overwritten each call except `pool` (accumulates from 0, so
//! it is cleared) and `sc` (masked-out lanes are never read, so a stale value can't leak in).

use crate::engine::State;
use crate::feats::{features_tokens, TOK_F, TOK_N, TOK_STATE};
use std::cell::RefCell;

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
        let wrow = &w[mi * k..mi * k + k];
        // 8 independent lanes break the f32 reduction dependency, so LLVM can emit SIMD + FMA for
        // the dot product (wasm128 is 4-wide f32, so this maps to two vector accumulators). This
        // REASSOCIATES the sum vs a strict left-to-right add, shifting the f32 result by ~1e-6 —
        // well within the `bin/attn_parity` tolerance; the argmax move is unchanged.
        let mut acc = [0f32; 8];
        let mut xc = x.chunks_exact(8);
        let mut wc = wrow.chunks_exact(8);
        for (xs, ws) in xc.by_ref().zip(wc.by_ref()) {
            for l in 0..8 {
                acc[l] += xs[l] * ws[l];
            }
        }
        let mut s = if b.is_empty() { 0.0 } else { b[mi] };
        for a in acc {
            s += a;
        }
        for (xr, wr) in xc.remainder().iter().zip(wc.remainder()) {
            s += xr * wr;
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

// Reused forward workspace (see the PERF note above). One per thread; in wasm each worker is its
// own thread, so there is no sharing/contention. Sizes are compile-time constants.
struct Scratch {
    tok: Vec<f32>,
    msk: Vec<f32>,
    st: Vec<f32>,
    x: Vec<f32>,
    q: Vec<f32>,
    k: Vec<f32>,
    v: Vec<f32>,
    ctx: Vec<f32>,
    sc: Vec<f32>,
    o: Vec<f32>,
    h1: Vec<f32>,
    h2: Vec<f32>,
    pool: Vec<f32>,
    se: Vec<f32>,
    cat: Vec<f32>,
    ht: Vec<f32>,
}
impl Scratch {
    fn new() -> Self {
        Scratch {
            tok: vec![0.0; TOK_N * TOK_F],
            msk: vec![0.0; TOK_N],
            st: vec![0.0; TOK_STATE],
            x: vec![0.0; TOK_N * D],
            q: vec![0.0; TOK_N * D],
            k: vec![0.0; TOK_N * D],
            v: vec![0.0; TOK_N * D],
            ctx: vec![0.0; TOK_N * D],
            sc: vec![0.0; TOK_N],
            o: vec![0.0; D],
            h1: vec![0.0; FF],
            h2: vec![0.0; D],
            pool: vec![0.0; D],
            se: vec![0.0; D],
            cat: vec![0.0; 2 * D],
            ht: vec![0.0; H],
        }
    }
}
thread_local! {
    static SCRATCH: RefCell<Scratch> = RefCell::new(Scratch::new());
}

impl AttnNet {
    /// value in [-1, 1]. `tokens` = TOK_N*TOK_F f64, `mask` = TOK_N, `state` = TOK_STATE.
    pub fn value(&self, tokens: &[f64], mask: &[f64], state: &[f64]) -> f64 {
        SCRATCH.with(|cell| {
            let s = &mut *cell.borrow_mut();
            let nob: &[f32] = &[];

            for (d, &sv) in s.tok.iter_mut().zip(tokens.iter()) {
                *d = sv as f32;
            }
            for (d, &sv) in s.msk.iter_mut().zip(mask.iter()) {
                *d = sv as f32;
            }
            for (d, &sv) in s.st.iter_mut().zip(state.iter()) {
                *d = sv as f32;
            }

            // token embed (written straight into x)
            for t in 0..TOK_N {
                linear(&s.tok[t * TOK_F..t * TOK_F + TOK_F], &self.emb_w, &self.emb_b, TOK_F, D, &mut s.x[t * D..t * D + D]);
            }

            let scale = 1.0 / (HD as f32).sqrt();
            for l in 0..L {
                for t in 0..TOK_N {
                    linear(&s.x[t * D..t * D + D], &self.wq[l], nob, D, D, &mut s.q[t * D..t * D + D]);
                    linear(&s.x[t * D..t * D + D], &self.wk[l], nob, D, D, &mut s.k[t * D..t * D + D]);
                    linear(&s.x[t * D..t * D + D], &self.wv[l], nob, D, D, &mut s.v[t * D..t * D + D]);
                }
                for h in 0..HEADS {
                    let off = h * HD;
                    for i in 0..TOK_N {
                        let mut mx = f32::NEG_INFINITY;
                        for j in 0..TOK_N {
                            if s.msk[j] < 0.5 {
                                continue;
                            }
                            let mut sv = 0.0;
                            for d in 0..HD {
                                sv += s.q[i * D + off + d] * s.k[j * D + off + d];
                            }
                            sv *= scale;
                            s.sc[j] = sv;
                            if sv > mx {
                                mx = sv;
                            }
                        }
                        let mut den = 0.0;
                        for j in 0..TOK_N {
                            if s.msk[j] >= 0.5 {
                                s.sc[j] = (s.sc[j] - mx).exp();
                                den += s.sc[j];
                            }
                        }
                        for d in 0..HD {
                            let mut acc = 0.0;
                            for j in 0..TOK_N {
                                if s.msk[j] >= 0.5 {
                                    acc += s.sc[j] * s.v[j * D + off + d];
                                }
                            }
                            s.ctx[i * D + off + d] = acc / den;
                        }
                    }
                }
                for t in 0..TOK_N {
                    linear(&s.ctx[t * D..t * D + D], &self.wo[l], nob, D, D, &mut s.o[..]);
                    for d in 0..D {
                        s.x[t * D + d] += s.o[d];
                    }
                    layernorm(&mut s.x[t * D..t * D + D]);
                }
                for t in 0..TOK_N {
                    linear(&s.x[t * D..t * D + D], &self.f1w[l], &self.f1b[l], D, FF, &mut s.h1[..]);
                    for vv in s.h1.iter_mut() {
                        if *vv < 0.0 {
                            *vv = 0.0;
                        }
                    }
                    linear(&s.h1[..], &self.f2w[l], &self.f2b[l], FF, D, &mut s.h2[..]);
                    for d in 0..D {
                        s.x[t * D + d] += s.h2[d];
                    }
                    layernorm(&mut s.x[t * D..t * D + D]);
                }
            }

            // masked mean-pool ++ state embed -> trunk -> value
            s.pool.fill(0.0);
            let mut cnt = 0.0;
            for t in 0..TOK_N {
                if s.msk[t] >= 0.5 {
                    cnt += 1.0;
                    for d in 0..D {
                        s.pool[d] += s.x[t * D + d];
                    }
                }
            }
            if cnt > 0.0 {
                for d in 0..D {
                    s.pool[d] /= cnt;
                }
            }
            linear(&s.st[..], &self.sw, &self.sb, TOK_STATE, D, &mut s.se[..]);
            s.cat[..D].copy_from_slice(&s.pool);
            s.cat[D..].copy_from_slice(&s.se);
            linear(&s.cat[..], &self.tw, &self.tb, 2 * D, H, &mut s.ht[..]);
            for vv in s.ht.iter_mut() {
                if *vv < 0.0 {
                    *vv = 0.0;
                }
            }
            let mut val = [0f32; 1];
            linear(&s.ht[..], &self.vw, &self.vb, H, 1, &mut val);
            val[0].tanh() as f64
        })
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
