//! P4b throughput gate, native side: attention forward evals/s/core across
//! candidate CoC token shapes (random weights — cost depends only on shape).
//! Calibration row: Spender's shipped 18x24/D64 arch (measured 2,041 evals/s
//! on this box's older code — a sanity anchor for the harness).
//!
//!   bench_attn            (runs the shape sweep)
use coc_core::attn::{AttnCfg, AttnNet};
use coc_core::rng::Rng;

fn bench(cfg: AttnCfg) {
    let net = AttnNet::random(cfg, 0xA77);
    let mut rng = Rng::new(0xBEEF);
    let mut r = |n: usize| -> Vec<f32> {
        (0..n).map(|_| (rng.next_u64() % 2000) as f32 / 1000.0 - 1.0).collect()
    };
    let tokens = r(cfg.t * cfg.f);
    let mut mask = vec![1.0f32; cfg.t];
    // realistic masking: ~15% of slots empty
    for i in 0..cfg.t {
        if i % 7 == 6 {
            mask[i] = 0.0;
        }
    }
    let state = r(cfg.state);
    // warm
    let mut acc = 0f32;
    for _ in 0..50 {
        acc += net.forward(&tokens, &mask, &state).0;
    }
    let iters = 2000;
    let t0 = std::time::Instant::now();
    for _ in 0..iters {
        acc += net.forward(&tokens, &mask, &state).0;
    }
    let dt = t0.elapsed().as_secs_f64();
    println!(
        "T={:2} F={:2} D={:2} L={} FF={:3}: {:7.1} us/eval  {:6.0} evals/s/core  [acc {:.3}]",
        cfg.t, cfg.f, cfg.d, cfg.layers, cfg.ff,
        dt / iters as f64 * 1e6,
        iters as f64 / dt,
        acc
    );
}

fn main() {
    let base = AttnCfg { t: 18, f: 24, d: 64, heads: 4, ff: 128, layers: 2, state: 60, trunk: 128, nact: 102 };
    // calibration (Spender's shipped shape)
    bench(base);
    for (t, f, d, ff) in [
        (32usize, 28usize, 48usize, 96usize),
        (32, 28, 64, 128),
        (44, 28, 48, 96),
        (44, 28, 64, 128),
        (56, 28, 64, 128),
        (44, 28, 32, 64),
    ] {
        bench(AttnCfg { t, f, d, heads: 4, ff, layers: 2, state: 80, trunk: 128, nact: 102 });
    }
}
