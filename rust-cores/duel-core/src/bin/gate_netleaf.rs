//! Net-leaf vs heuristic-leaf at EQUAL SIMS (or per-side sims), up a sims ladder. Tests whether a
//! LEARNED evaluator beats the hand heuristic when speed is held constant — and, via per-side levers,
//! any search-config A/B (coherent vs per-sim, guided vs unguided, budget asymmetries).
//!
//!   >0.5 at a sim level = side A is better there. CRN seat-swapped, greedy.
//!
//!   cargo run --release --features bridge --bin gate_netleaf -- --leaf net --sims 2000 --games 200
//!
//! Side-B levers (--coherent-b/--cpuct-b/--net-policy-temp-b/--sims-b) exist so BOTH sides can run
//! the serving-real coherent config (a gate between nets must not hand side A a search advantage),
//! and for equal-BUDGET framings (guided@2k vs unguided@8k).

use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::engine::{Move, State, EMPTY, N_CELLS};
use duel_core::mcts::{choose_move_with_leaf, greedy_net_move, Leaf, Opts, RngShuffler};
use duel_core::rng::Rng;
use duel_core::attn::AttnNet;
use duel_core::valuenet::{QuantValueNet, ValueNet};

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

/// One side's full search configuration. Both sides get one, so any lever can be A/B'd symmetrically.
#[derive(Clone, Copy)]
struct SideCfg<'a> {
    leaf: Leaf<'a>,
    sims: u64,
    prior: Option<(f64, f64)>,    // 1-ply heuristic prior (temp, c_puct)
    greedy: bool,                 // 1-ply greedy net, NO search
    dev_tilt: f64,
    net_policy_temp: Option<f64>, // learned policy prior serving temperature
    no_determinize: bool,         // perfect-info cheat
    root_dets: Option<usize>,     // K fixed worlds (legacy probe)
    coherent: bool,               // determinize once + chance frozen (the serving search)
    cpuct: Option<f64>,           // exploration override (applied unconditionally via Opts::prior_c)
    minimax: bool,                // sign Q by node actor in select (vs the deployed max-max)
    fpu: Option<f64>,             // first-play urgency reduction (unvisited q = parent q - r)
    max_depth: Option<usize>,     // in-tree depth cap override (None = MAX_TREE_DEPTH 14)
    rollout: Option<usize>,       // rollout-steps override (None = difficulty default 12)
}

impl<'a> SideCfg<'a> {
    fn plain(leaf: Leaf<'a>, sims: u64) -> Self {
        SideCfg {
            leaf,
            sims,
            prior: None,
            greedy: false,
            dev_tilt: 0.0,
            net_policy_temp: None,
            no_determinize: false,
            root_dets: None,
            coherent: false,
            cpuct: None,
            minimax: false,
            fpu: None,
            max_depth: None,
            rollout: None,
        }
    }
}

fn agent_move(st: &State, mover: usize, cfg: &SideCfg, dseed: u64) -> Option<Move> {
    if cfg.greedy {
        if let Leaf::AttnVal(net) = cfg.leaf {
            return greedy_net_move(st, mover, net); // 1-ply greedy net, NO search
        }
    }
    let (prior_temp, prior_c_from_prior) = match cfg.prior {
        Some((t, c)) => (Some(t), Some(c)),
        None => (None, None),
    };
    let opts = Opts {
        max_iters: Some(cfg.sims),
        time_limit: Some(f64::INFINITY),
        temperature: None,
        prior_temp,
        prior_c: cfg.cpuct.or(prior_c_from_prior), // explicit c_puct override wins (applied unconditionally)
        dev_tilt: cfg.dev_tilt,
        net_policy_temp: cfg.net_policy_temp,
        no_determinize: cfg.no_determinize,
        root_dets: cfg.root_dets,
        coherent: cfg.coherent,
        minimax: cfg.minimax,
        fpu: cfg.fpu,
        max_depth: cfg.max_depth,
        rollout_steps: cfg.rollout,
        ..Default::default()
    };
    let mut rng = Rng::new(dseed ^ 0x4D43_5453);
    choose_move_with_leaf(st, mover, "hard", &opts, cfg.leaf, &mut rng)
}

/// Agent A (seat `a_seat`) plays cfg_a; B plays cfg_b. Returns A's score.
fn play(gseed: u64, a_seat: usize, cfg_a: &SideCfg, cfg_b: &SideCfg, cap: usize) -> f64 {
    let mut setup = Rng::new(mix(gseed, 0x5E7));
    let mut st = new_game(&mut setup);
    let mut game_rng = Rng::new(mix(gseed, 0x6A3E));
    let mut ply = 0usize;
    while !st.is_over() && ply < cap {
        let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
        let cfg = if mover == a_seat { cfg_a } else { cfg_b };
        let dseed = mix(mix(gseed, mover as u64), ply as u64);
        let mv = match agent_move(&st, mover, cfg, dseed) {
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

fn run_match(cfg_a: &SideCfg, cfg_b: &SideCfg, games: u64, seed0: u64, cap: usize) -> (f64, u64) {
    // Multi-threaded: games are independent + deterministic, so a shared work counter gives the SAME
    // result as the sequential loop while saturating every core (the attention leaf is heavy).
    use std::sync::atomic::{AtomicU64, Ordering};
    let nthreads = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4);
    let next = AtomicU64::new(0);
    let total = std::sync::Mutex::new(0.0f64);
    std::thread::scope(|sc| {
        for _ in 0..nthreads {
            sc.spawn(|| {
                let mut local = 0.0f64;
                loop {
                    let g = next.fetch_add(1, Ordering::Relaxed);
                    if g >= games {
                        break;
                    }
                    local += play(seed0 + g, 0, cfg_a, cfg_b, cap);
                    local += play(seed0 + g, 1, cfg_a, cfg_b, cap);
                }
                *total.lock().unwrap() += local;
            });
        }
    });
    let t = *total.lock().unwrap();
    (t / (games * 2) as f64, games * 2)
}

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

static VALUE_NET_JSON: &str = include_str!("../value_net.json");
static ATTN_NET_JSON: &str = include_str!("../attn_value_net.json");

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    let mut games: u64 = 200;
    let mut sims: u64 = 2000;
    let mut sims_b: Option<u64> = None; // side-B sims override (equal-BUDGET framings)
    let mut leaf_kind = "net".to_string();
    let mut leaf_b_kind = "heur".to_string();
    let mut attn_file: Option<String> = None;
    let mut attn_file_b: Option<String> = None;
    let mut prior_temp: Option<f64> = None;
    let mut prior_c: Option<f64> = None;
    let mut greedy_net: bool = false;
    let mut dev_tilt: f64 = 0.0;
    let mut net_policy_temp: Option<f64> = None; // side-A learned policy prior temp
    let mut net_policy_temp_b: Option<f64> = None; // side-B learned policy prior temp
    let mut no_determinize: bool = false;
    let mut root_dets: Option<usize> = None;
    let mut coherent: bool = false; // side-A coherent search
    let mut coherent_b: bool = false; // side-B coherent search
    let mut cpuct: Option<f64> = None; // side-A c_puct override
    let mut cpuct_b: Option<f64> = None; // side-B c_puct override
    let mut root_dets_b: Option<usize> = None; // side-B world count (with --coherent-b: the K-ensemble)
    let mut minimax: bool = false; // side-A actor-signed selection
    let mut minimax_b: bool = false;
    let mut fpu: Option<f64> = None; // side-A FPU reduction
    let mut fpu_b: Option<f64> = None;
    let mut max_depth: Option<usize> = None; // side-A in-tree depth cap
    let mut max_depth_b: Option<usize> = None;
    let mut rollout: Option<usize> = None; // side-A rollout-steps override
    let mut rollout_b: Option<usize> = None;
    let mut seed0: u64 = 70_000;
    let cap: usize = 400;
    let mut i = 1;
    while i < argv.len() {
        let k = argv[i].clone();
        let mut next = || {
            i += 1;
            argv.get(i).cloned().unwrap_or_else(|| panic!("missing value for {}", k))
        };
        match k.as_str() {
            "--games" => games = next().parse().unwrap(),
            "--sims" => sims = next().parse().unwrap(),
            "--sims-b" => sims_b = Some(next().parse().unwrap()),
            "--leaf" => leaf_kind = next(),
            "--leaf-b" => leaf_b_kind = next(),
            "--attn-file" => attn_file = Some(next()),
            "--attn-file-b" => attn_file_b = Some(next()),
            "--prior-temp" => prior_temp = Some(next().parse().unwrap()),
            "--prior-c" => prior_c = Some(next().parse().unwrap()),
            "--greedy-net" => greedy_net = true,
            "--dev-tilt" => dev_tilt = next().parse().unwrap(),
            "--net-policy-temp" => net_policy_temp = Some(next().parse().unwrap()),
            "--net-policy-temp-b" => net_policy_temp_b = Some(next().parse().unwrap()),
            "--no-determinize" => no_determinize = true,
            "--root-dets" => root_dets = Some(next().parse().unwrap()),
            "--coherent" => coherent = true,
            "--coherent-b" => coherent_b = true,
            "--cpuct" => cpuct = Some(next().parse().unwrap()),
            "--cpuct-b" => cpuct_b = Some(next().parse().unwrap()),
            "--root-dets-b" => root_dets_b = Some(next().parse().unwrap()),
            "--minimax" => minimax = true,
            "--minimax-b" => minimax_b = true,
            "--fpu" => fpu = Some(next().parse().unwrap()),
            "--fpu-b" => fpu_b = Some(next().parse().unwrap()),
            "--max-depth" => max_depth = Some(next().parse().unwrap()),
            "--max-depth-b" => max_depth_b = Some(next().parse().unwrap()),
            "--rollout-steps" => rollout = Some(next().parse().unwrap()),
            "--rollout-steps-b" => rollout_b = Some(next().parse().unwrap()),
            "--seed" => seed0 = next().parse().unwrap(),
            other => panic!("unknown arg: {}", other),
        }
        i += 1;
    }
    let net = ValueNet::from_json_str(VALUE_NET_JSON).expect("load value_net.json");
    let net8 = QuantValueNet::from_f32(&net);
    let attn = AttnNet::from_json_str(ATTN_NET_JSON).expect("load attn_value_net.json"); // v1 (embedded)
    let attn2 = attn_file.map(|p| {
        AttnNet::from_json_str(&std::fs::read_to_string(&p).expect("read --attn-file")).expect("parse --attn-file")
    });
    let attn3 = attn_file_b.map(|p| {
        AttnNet::from_json_str(&std::fs::read_to_string(&p).expect("read --attn-file-b")).expect("parse --attn-file-b")
    });
    let pick = |kind: &str, which: &str| -> Leaf {
        match kind {
            "heur" => Leaf::Heuristic,
            "heurdev" => Leaf::HeuristicW(&duel_core::value::DEV_WEIGHTS),
            "heurcrown" => Leaf::HeuristicW(&duel_core::value::CROWN_WEIGHTS),
            "heurcolor" => Leaf::HeuristicW(&duel_core::value::COLOR_WEIGHTS),
            "heurpoints" => Leaf::HeuristicW(&duel_core::value::POINTS_WEIGHTS),
            "net" => Leaf::Net(&net),
            "net8" => Leaf::Net8(&net8),
            "netval" => Leaf::NetVal(&net),
            "attnval" => Leaf::AttnVal(&attn),
            "attnfile" => Leaf::AttnVal(attn2.as_ref().expect("--attn-file required for attnfile")),
            "attnfile2" => Leaf::AttnVal(attn3.as_ref().expect("--attn-file-b required for attnfile2")),
            o => panic!("{which} must be heur|heurdev|heurcrown|heurcolor|heurpoints|net|net8|netval|attnval|attnfile|attnfile2, got {o}"),
        }
    };
    let cfg_a = SideCfg {
        leaf: pick(&leaf_kind, "--leaf"),
        sims,
        prior: prior_temp.map(|t| (t, prior_c.unwrap_or(1.5))),
        greedy: greedy_net,
        dev_tilt,
        net_policy_temp,
        no_determinize,
        root_dets,
        coherent,
        cpuct,
        minimax,
        fpu,
        max_depth,
        rollout,
    };
    let cfg_b = SideCfg {
        leaf: pick(&leaf_b_kind, "--leaf-b"),
        sims: sims_b.unwrap_or(sims),
        net_policy_temp: net_policy_temp_b,
        coherent: coherent_b,
        cpuct: cpuct_b,
        root_dets: root_dets_b,
        minimax: minimax_b,
        fpu: fpu_b,
        max_depth: max_depth_b,
        rollout: rollout_b,
        ..SideCfg::plain(Leaf::Heuristic, sims)
    };
    // Mirror sanity: identical plain configs (heur vs heur) must read 0.5000.
    let (m, mn) = run_match(&SideCfg::plain(Leaf::Heuristic, sims), &SideCfg::plain(Leaf::Heuristic, sims), 8, seed0, cap);
    println!("[mirror] heur vs heur @ {sims} : {m:.4} (n={mn}) — must be 0.5000");
    let (r, n) = run_match(&cfg_a, &cfg_b, games, seed0, cap);
    let (lo, hi) = wilson(r, n);
    let sims_b_disp = sims_b.unwrap_or(sims);
    println!("NETLEAF GATE: {leaf_kind} vs {leaf_b_kind} @ {sims}v{sims_b_disp} sims : {r:.4} [{lo:.3}, {hi:.3}] (n={n})");
    // Config echo — every lever that differs from plain, so a sweep log is self-documenting.
    let mut notes: Vec<String> = Vec::new();
    if greedy_net {
        notes.push("A=1-PLY GREEDY (no search)".into());
    }
    if coherent {
        notes.push(format!("A=COHERENT K={} cpuct={:?}", cfg_a.root_dets.unwrap_or(1), cfg_a.cpuct));
    }
    if coherent_b {
        notes.push(format!("B=COHERENT K={} cpuct={:?}", cfg_b.root_dets.unwrap_or(1), cfg_b.cpuct));
    }
    if let Some(t) = net_policy_temp {
        notes.push(format!("A=policy-prior temp {t}"));
    }
    if let Some(t) = net_policy_temp_b {
        notes.push(format!("B=policy-prior temp {t}"));
    }
    if no_determinize {
        notes.push("A=PERFECT-INFO cheat".into());
    }
    if let Some(k) = root_dets {
        notes.push(format!("A=ROOT-DET K={k}"));
    }
    if dev_tilt != 0.0 {
        notes.push(format!("A=dev-tilt {dev_tilt}"));
    }
    if minimax {
        notes.push("A=MINIMAX select".into());
    }
    if minimax_b {
        notes.push("B=MINIMAX select".into());
    }
    if let Some(r) = fpu {
        notes.push(format!("A=fpu {r}"));
    }
    if let Some(r) = fpu_b {
        notes.push(format!("B=fpu {r}"));
    }
    if let Some(d) = max_depth {
        notes.push(format!("A=max-depth {d}"));
    }
    if let Some(d) = max_depth_b {
        notes.push(format!("B=max-depth {d}"));
    }
    if let Some(s) = rollout {
        notes.push(format!("A=rollout {s}"));
    }
    if let Some(s) = rollout_b {
        notes.push(format!("B=rollout {s}"));
    }
    if let Some((t, c)) = cfg_a.prior {
        notes.push(format!("A=1-ply heur prior temp={t} c={c}"));
    }
    if !coherent {
        if let Some(c) = cfg_a.cpuct {
            notes.push(format!("A=cpuct {c}"));
        }
    }
    if !coherent_b {
        if let Some(c) = cfg_b.cpuct {
            notes.push(format!("B=cpuct {c}"));
        }
    }
    if notes.is_empty() {
        notes.push("plain both sides".into());
    }
    println!("  ({}; >0.5 = A beats B)", notes.join(", "));
}
