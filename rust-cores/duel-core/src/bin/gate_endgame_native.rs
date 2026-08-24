//! NATIVE strength gate for the exact-endgame augmentation (the Python `gate_endgame.py` is too
//! slow for statistics — subprocess + full-game replay per decision). Fast, all-Rust, so hundreds
//! of games run in a couple of minutes.
//!
//! MODEL: both sides run the SAME hard MCTS at a FIXED sim budget that is well past the measured
//! ~700-sim saturation knee (so the plain side's sims are already maxed out). The AUGMENTED side,
//! when a position is `in_endgame` and `endgame_decide` is CONCLUSIVE, plays the exact minimax
//! move instead of the sampled pick. This is the ADDITIVE endgame refine we'd ship to WASM
//! (mirroring what Spender ships): the MCTS keeps its full budget, and the exact search only
//! overrides pivotal endgame decisions.
//!
//!   * GATE (aug vs plain, CRN seat-swapped): >0.5 = exact endgame play is a real strength gain.
//!   * MIRROR SANITY (plain-vs-plain AND aug-vs-aug, seat-swapped, greedy): must read EXACTLY
//!     0.5000 — identical configs make each seat-swapped pair sum to 1, so anything off 0.5 means
//!     the harness is biased and every other number is meaningless.
//!   * TRIGGER STATS: how often the endgame fired / was conclusive / proved a forced win.
//!
//!     cargo run --release --features bridge --bin gate_endgame_native -- --games 200 --sims 2000

use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::endgame::{endgame_decide, in_endgame};
use duel_core::engine::{Move, State, EMPTY, N_CELLS};
use duel_core::mcts::{choose_move, Opts, RngShuffler};
use duel_core::rng::Rng;

/// Fresh game — structural copy of `endgame_diag::new_game` (which mirrors engine.py::new_game).
fn new_game(rng: &mut Rng) -> State {
    let mut decks: [Vec<usize>; 3] = [(0..30).collect(), (30..54).collect(), (54..67).collect()];
    let pyramid_sizes = [5usize, 4, 3];
    let mut pyramid: [Vec<i32>; 3] = [Vec::new(), Vec::new(), Vec::new()];
    for lvl in 0..3 {
        rng.shuffle(&mut decks[lvl]);
        for _ in 0..pyramid_sizes[lvl] {
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

#[inline]
fn mix(a: u64, b: u64) -> u64 {
    let mut x = a ^ b.wrapping_mul(0x9E37_79B9_7F4A_7C15);
    x ^= x >> 30;
    x = x.wrapping_mul(0xBF58_476D_1CE4_E5B9);
    x ^= x >> 27;
    x = x.wrapping_mul(0x94D0_49BB_1331_11EB);
    x ^= x >> 31;
    x
}

#[derive(Clone, Copy)]
struct Cfg {
    eg: bool,
}

struct Params {
    sims: u64,
    depth: usize,
    node_cap: u64,
    dets: usize,
    thresh: f64,
    cap: usize,
}

#[derive(Default)]
struct Stats {
    decisions: u64,
    triggered: u64,
    conclusive: u64,
    proven: u64,
}

/// One agent's move. `track` accumulates endgame telemetry (only for the augmented side). The
/// decision seed is a pure function of (gseed, seat, ply) — NOT of which agent sits there — so an
/// identical-config seat-swap is byte-symmetric (the mirror reads exactly 0.5000).
fn agent_move(
    st: &State,
    mover: usize,
    cfg: Cfg,
    p: &Params,
    dseed: u64,
    stats: &mut Stats,
    track: bool,
) -> Option<Move> {
    if track {
        stats.decisions += 1;
    }
    if cfg.eg && in_endgame(st, p.thresh) {
        if track {
            stats.triggered += 1;
        }
        if let Some(d) = endgame_decide(st, mover, p.depth, p.node_cap, p.dets, dseed, None) {
            if track {
                stats.conclusive += 1;
                if d.proven_win {
                    stats.proven += 1;
                }
            }
            return Some(d.best);
        }
    }
    let opts = Opts {
        max_iters: Some(p.sims),
        time_limit: Some(f64::INFINITY),
        temperature: None, // hard = greedy (deterministic)
        ..Default::default()
    };
    let mut rng = Rng::new(dseed ^ 0x4D43_5453);
    choose_move(st, mover, "hard", &opts, &mut rng)
}

/// Play one game; agent A occupies seat `a_seat`. Returns A's score (1 / 0.5 / 0).
fn play(gseed: u64, a_seat: usize, a: Cfg, b: Cfg, p: &Params, stats: &mut Stats) -> f64 {
    let mut setup = Rng::new(mix(gseed, 0x5E7));
    let mut st = new_game(&mut setup);
    // Replenishment/blind-draw rng: seeded by the DECK only (not the seat) + advanced through the
    // game, so the seat-swapped pair draws the same hidden cards → mirror symmetry.
    let mut game_rng = Rng::new(mix(gseed, 0x6A3E));
    let mut ply = 0usize;
    while !st.is_over() && ply < p.cap {
        let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
        let cfg = if mover == a_seat { a } else { b };
        let dseed = mix(mix(gseed, mover as u64), ply as u64);
        let mv = match agent_move(&st, mover, cfg, p, dseed, stats, cfg.eg) {
            Some(m) => m,
            None => break,
        };
        let mut sh = RngShuffler { rng: &mut game_rng };
        if st.apply_move(mover, &mv, &mut sh).is_err() {
            break;
        }
        ply += 1;
    }
    if !st.is_over() || st.winner < 0 {
        return 0.5;
    }
    if st.winner as usize == a_seat {
        1.0
    } else {
        0.0
    }
}

/// A CRN match: each deck seed played BOTH seat orders. Returns (A win-rate, n_games).
fn run_match(a: Cfg, b: Cfg, games: u64, seed0: u64, p: &Params, stats: &mut Stats) -> (f64, u64) {
    let mut total = 0.0f64;
    let mut n = 0u64;
    for i in 0..games {
        for a_seat in 0..2 {
            total += play(seed0 + i, a_seat, a, b, p, stats);
            n += 1;
        }
    }
    (total / n as f64, n)
}

/// Wilson 95% score interval.
fn wilson(p_hat: f64, n: u64) -> (f64, f64) {
    if n == 0 {
        return (0.0, 1.0);
    }
    let z = 1.96f64;
    let n = n as f64;
    let denom = 1.0 + z * z / n;
    let center = p_hat + z * z / (2.0 * n);
    let margin = z * ((p_hat * (1.0 - p_hat) + z * z / (4.0 * n)) / n).sqrt();
    ((center - margin) / denom, (center + margin) / denom)
}

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    let mut games: u64 = 200;
    let mut mirror_games: u64 = 20;
    let mut sims: u64 = 2000;
    let mut depth: usize = 14;
    let mut node_cap: u64 = 250_000;
    let mut dets: usize = 6;
    let mut thresh: f64 = 0.7;
    let mut seed0: u64 = 70_000;
    let mut i = 1;
    while i < argv.len() {
        let k = argv[i].clone();
        let mut next = || {
            i += 1;
            argv.get(i).cloned().unwrap_or_else(|| panic!("missing value for {}", k))
        };
        match k.as_str() {
            "--games" => games = next().parse().unwrap(),
            "--mirror-games" => mirror_games = next().parse().unwrap(),
            "--sims" => sims = next().parse().unwrap(),
            "--depth" => depth = next().parse().unwrap(),
            "--node-cap" => node_cap = next().parse().unwrap(),
            "--dets" => dets = next().parse().unwrap(),
            "--thresh" => thresh = next().parse().unwrap(),
            "--seed" => seed0 = next().parse().unwrap(),
            other => panic!("unknown arg: {}", other),
        }
        i += 1;
    }
    let p = Params { sims, depth, node_cap, dets, thresh, cap: 400 };
    let plain = Cfg { eg: false };
    let aug = Cfg { eg: true };

    println!("== MIRROR SANITY (seat-swapped, greedy — must read EXACTLY 0.5000) ==");
    let mut junk = Stats::default();
    let (pm, pn) = run_match(plain, plain, mirror_games, seed0, &p, &mut junk);
    println!("  plain vs plain @ {sims} sims : {pm:.4}  (n={pn})");
    let mut junk2 = Stats::default();
    let (am, an) = run_match(aug, aug, mirror_games, seed0, &p, &mut junk2);
    println!("  aug   vs aug   @ {sims} sims : {am:.4}  (n={an})");

    println!("\n== THE GATE (aug vs plain, {sims} sims/decision, additive endgame refine) ==");
    let mut stats = Stats::default();
    let (gm, gn) = run_match(aug, plain, games, seed0, &p, &mut stats);
    let (lo, hi) = wilson(gm, gn);
    println!("  augmented vs plain : {gm:.4}  [{lo:.3}, {hi:.3}]  (n={gn})");

    println!("\n== ENDGAME TRIGGER STATS (augmented side) ==");
    let d = stats.decisions.max(1);
    let tr = stats.triggered.max(1);
    println!("  decisions            : {}", stats.decisions);
    println!("  in_endgame triggered : {} ({:.1}% of decisions)", stats.triggered, 100.0 * stats.triggered as f64 / d as f64);
    println!("  conclusive           : {} ({:.1}% of triggered)", stats.conclusive, 100.0 * stats.conclusive as f64 / tr as f64);
    println!("  proven forced wins   : {}", stats.proven);

    println!("\n== VERDICT ==");
    println!("  config: depth {depth}, node_cap {node_cap}, dets {dets}, thresh {thresh}, sims {sims}");
    println!("  GATE (aug vs plain): {gm:.4} [{lo:.3}, {hi:.3}]");
    println!("  (>0.5 with the interval clear of 0.5 = exact endgame is a real, significant gain)");
}
