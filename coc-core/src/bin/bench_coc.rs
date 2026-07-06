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

use coc_core::engine::State;
use coc_core::tiles;
use coc_core::valuenet::PolicyValueNet;

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
}
