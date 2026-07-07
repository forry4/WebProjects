//! P0 throughput probes (plan gate): State clone cost + PolicyValueNet forward at
//! candidate feature dims. Run BEFORE committing the feature-vector size.
//!
//!   cargo run --release --bin bench_coc
//!
//! Gates (from the plan): MLP >= 1.5k evals/s/core at the chosen dims; clone must be
//! trivially cheap (it's ~one memcpy of ~1KB). apply+legal >= 100k micro-moves/s is
//! measured at the end of P1 once the engine exists.

use std::hint::black_box;
use std::time::Instant;

use coc_core::engine::{self, State};
use coc_core::rng::Rng;
use coc_core::tiles;
use coc_core::valuenet::PolicyValueNet;
use coc_core::{feats, heuristic, vsearch};

const N_ACTIONS: usize = 102;

fn midgame_state() -> State {
    // A plausible mid-game state: supply partially drawn, boards partially filled,
    // storage/goods/depots populated. Contents only matter for realistic memcpy size
    // (which is fixed anyway) — this is a clone-cost probe, not a rules probe.
    let mut s = State::shell([0, 3]);
    let (nb, b) = tiles::build_supply();
    s.supply[..nb.len()].copy_from_slice(&nb);
    s.supply_len = 90; // ~34 drawn
    s.black_supply[..b.len()].copy_from_slice(&b);
    s.black_supply_len = 28;
    s.goods_supply = tiles::build_goods_pool();
    s.goods_supply_len = 20;
    s.goods_queue[..3].copy_from_slice(&[1, 4, 2]);
    s.goods_queue_len = 3;
    for d in 0..6 {
        s.depot_hex[d] = [nb[d * 3], nb[d * 3 + 1]];
        s.depot_goods[d][d] = 2;
    }
    s.black_depot = [b[0], b[1], b[2], 0];
    for seat in 0..2 {
        let p = &mut s.players[seat];
        for i in 0..14 {
            p.duchy[i * 2 + seat] = nb[40 + i];
            p.filled |= 1 << (i * 2 + seat);
        }
        p.castle_sid = 18;
        p.storage = [nb[70 + seat], nb[80 + seat], 0];
        p.goods[1] = 3;
        p.goods[4] = 1;
        p.workers = 3;
        p.silver = 5;
        p.vp = 37;
        p.mines = 2;
        p.mon_mask = 0b101;
    }
    s.mode = coc_core::engine::PLAYING;
    s.phase = 2;
    s.round = 3;
    s.rng = 0xC0C0_1234_5678_9ABC;
    s
}

fn bench_clone(s: &State) {
    let n = 2_000_000u64;
    let t0 = Instant::now();
    let mut acc = 0u64;
    for i in 0..n {
        let c = black_box(s.clone());
        acc = acc.wrapping_add(c.players[0].vp as u64 + i);
    }
    let dt = t0.elapsed().as_secs_f64();
    println!(
        "clone: {:.1}M clones/s  ({:.0} ns/clone, state ~{}B inline)  [acc {}]",
        n as f64 / dt / 1e6,
        dt / n as f64 * 1e9,
        std::mem::size_of::<State>(),
        acc % 10
    );
}

fn bench_pv(in_dim: usize, trunk: &[usize]) {
    let net = PolicyValueNet::random(in_dim, trunk, N_ACTIONS, 42);
    // varying inputs so nothing folds
    let mut inputs = Vec::new();
    for k in 0..64 {
        let v: Vec<f32> = (0..in_dim).map(|i| ((i * 31 + k * 17) % 97) as f32 / 97.0).collect();
        inputs.push(v);
    }
    let n = 20_000usize;
    let t0 = Instant::now();
    let mut acc = 0.0f32;
    for i in 0..n {
        let (v, pol) = net.forward_raw(black_box(&inputs[i % 64]));
        acc += v + pol[i % N_ACTIONS];
    }
    let dt = t0.elapsed().as_secs_f64();
    println!(
        "pv {}->{:?}->(1+{}): {:.0} evals/s/core  ({:.1} us/eval)  [acc {:.3}]",
        in_dim,
        trunk,
        N_ACTIONS,
        n as f64 / dt,
        dt / n as f64 * 1e6,
        acc
    );
}

fn bench_playout() {
    // Random full games through legal_actions_full + apply — the P1 gate is
    // >= 100k micro-moves/s (this measures the full legal-enumeration cost too,
    // which dominates; apply alone is far cheaper).
    use coc_core::engine::{apply, legal_actions_full, State};
    use coc_core::rng::Rng;
    let mut rng = Rng::new(0xBEEF);
    let n_games = 2_000u64;
    let mut moves = 0u64;
    let t0 = Instant::now();
    for g in 0..n_games {
        let mut s = State::new_game([(g % 9) as u8, ((g / 9) % 9) as u8], g);
        while !s.is_over() {
            let acts = legal_actions_full(&s);
            let a = acts[rng.below(acts.len())];
            apply(&mut s, a);
            moves += 1;
        }
    }
    let dt = t0.elapsed().as_secs_f64();
    println!(
        "playout: {:.0} games/s, {:.2}M micro-moves/s ({:.0} micro-moves/game, legal+apply)",
        n_games as f64 / dt,
        moves as f64 / dt / 1e6,
        moves as f64 / n_games as f64
    );
}

/// Realistic mid-game PLAYING states via random playout (snapshots every ~40
/// micro-moves) — the netval-leaf breakdown benches run over these, not the
/// synthetic clone-probe state.
fn playout_states(n: usize) -> Vec<State> {
    let mut rng = Rng::new(0xFEED);
    let mut out = Vec::with_capacity(n);
    let mut g = 0u64;
    while out.len() < n {
        let mut s = State::new_game([(g % 9) as u8, ((g / 9) % 9) as u8], 1000 + g);
        let mut moves = 0u64;
        while !s.is_over() && out.len() < n {
            let acts = engine::legal_actions_full(&s);
            let a = acts[rng.below(acts.len())];
            engine::apply(&mut s, a);
            moves += 1;
            if moves % 40 == 0 && s.mode == engine::PLAYING {
                out.push(s.clone());
            }
        }
        g += 1;
    }
    out
}

/// The netval-leaf cost breakdown: encoder / heuristic eval / net forward /
/// full leaf / full search sims/s. This is where self-play + serving time goes.
fn bench_leaf_breakdown() {
    let states = playout_states(64);
    let net = PolicyValueNet::random(feats::N_FEATS, &[512, 256], N_ACTIONS, 7);

    let n = 20_000usize;
    let t0 = Instant::now();
    let mut acc = 0.0f32;
    for i in 0..n {
        let s = &states[i % states.len()];
        let f = feats::features(black_box(s), s.actor() as usize);
        acc += f[i % feats::N_FEATS];
    }
    let dt = t0.elapsed().as_secs_f64();
    println!("features(): {:.1} us/call ({:.0}/s/core)  [acc {:.3}]", dt / n as f64 * 1e6, n as f64 / dt, acc);

    let t0 = Instant::now();
    let mut acc = 0.0f64;
    for i in 0..n {
        let s = &states[i % states.len()];
        acc += heuristic::eval_reward(black_box(s), s.actor() as usize);
    }
    let dt = t0.elapsed().as_secs_f64();
    println!("heur eval_reward: {:.1} us/call  [acc {:.3}]", dt / n as f64 * 1e6, acc);

    // forward on precomputed features (isolates the net matvec)
    let fs: Vec<Vec<f32>> = states.iter().map(|s| feats::features(s, s.actor() as usize)).collect();
    let n = 20_000usize;
    let t0 = Instant::now();
    let mut acc = 0.0f32;
    for i in 0..n {
        let (v, pol) = net.forward_raw(black_box(&fs[i % fs.len()]));
        acc += v + pol[i % N_ACTIONS];
    }
    let dt = t0.elapsed().as_secs_f64();
    println!("forward_raw (934->[512,256]): {:.1} us/call ({:.0}/s/core)  [acc {:.3}]", dt / n as f64 * 1e6, n as f64 / dt, acc);

    let n = 5_000usize;
    let mut rng = Rng::new(0xABCD);
    let t0 = Instant::now();
    let mut acc = 0.0f64;
    for i in 0..n {
        let s = &states[i % states.len()];
        let legal = engine::legal_actions(s);
        let (p, v) = vsearch::hybrid_netval_eval(&net, black_box(s), s.actor() as usize, &legal, &mut rng);
        acc += v + p[legal[0]];
    }
    let dt = t0.elapsed().as_secs_f64();
    println!("netval leaf (2 fwd + rollout): {:.1} us/call ({:.0}/s/core)  [acc {:.3}]", dt / n as f64 * 1e6, n as f64 / dt, acc);

    // batched forward: per-eval cost at K=8/16/32 (the batch.rs operating points)
    for k in [8usize, 16, 32] {
        let refs: Vec<&[f32]> = (0..k).map(|i| fs[i % fs.len()].as_slice()).collect();
        let need: Vec<bool> = (0..k).map(|i| i % 2 == 0).collect();
        let n = 40_000usize / k;
        let t0 = Instant::now();
        let mut acc = 0.0f32;
        for _ in 0..n {
            let out = net.forward_batch(black_box(&refs), &need);
            acc += out[0].0 + out[0].1[7];
        }
        let dt = t0.elapsed().as_secs_f64();
        println!(
            "forward_batch K={k}: {:.1} us/eval ({:.0} evals/s/core)  [acc {:.3}]",
            dt / (n * k) as f64 * 1e6,
            (n * k) as f64 / dt,
            acc
        );
    }

    // full search: sims/s at the self-play operating point
    for (label, state) in [("mid", &states[20]), ("late", &states[60])] {
        let sims = 2_000u32;
        let mut search = coc_core::mcts::Search::new(state.clone(), vsearch::C_PUCT);
        let mut rng = Rng::new(0x5EED);
        let eval = |st: &State, actor: usize, lg: &[usize], r: &mut Rng| {
            vsearch::hybrid_netval_eval(&net, st, actor, lg, r)
        };
        let t0 = Instant::now();
        for _ in 0..sims {
            search.sim(&mut rng, &eval);
        }
        let dt = t0.elapsed().as_secs_f64();
        println!("netval SEARCH ({label}): {:.0} sims/s/core", sims as f64 / dt);
    }
}

fn main() {
    let s = midgame_state();
    bench_clone(&s);
    bench_playout();
    for (in_dim, trunk) in [
        (700usize, vec![384usize, 256]),
        (800, vec![512, 256]),
        (900, vec![512, 256]),
        (900, vec![768, 384]),
    ] {
        bench_pv(in_dim, &trunk);
    }
    bench_leaf_breakdown();
}
