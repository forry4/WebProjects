//! Net-leaf vs heuristic-leaf at EQUAL SIMS, up a sims ladder. Tests whether a LEARNED evaluator is
//! actually better than the hand heuristic when speed is held constant (equal sims, not equal wall-
//! clock) — the question that decides whether a heavier-but-better eval (e.g. an attention net) is
//! worth pursuing + making fast. Side A = the chosen net leaf (0-step eval); side B = heuristic
//! (rollout+value). CRN seat-swapped, greedy.
//!
//!   >0.5 at a sim level = the net is a better evaluator there. If it wins at low sims but DECAYS to
//!   ~0.5 by ~6k, it is the leaf/search-redundancy trap (a flat net search recovers) — the signal to
//!   change the ARCHITECTURE, not just the speed.
//!
//!   cargo run --release --features bridge --bin gate_netleaf -- --leaf net --sims 2000 --games 200

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

fn agent_move(st: &State, mover: usize, leaf: Leaf, sims: u64, dseed: u64, prior: Option<(f64, f64)>, greedy: bool, dev_tilt: f64, net_policy_temp: Option<f64>) -> Option<Move> {
    if greedy {
        if let Leaf::AttnVal(net) = leaf {
            return greedy_net_move(st, mover, net); // 1-ply greedy net, NO search
        }
    }
    let (prior_temp, prior_c) = match prior {
        Some((t, c)) => (Some(t), Some(c)),
        None => (None, None),
    };
    let opts = Opts {
        max_iters: Some(sims),
        time_limit: Some(f64::INFINITY),
        temperature: None,
        prior_temp,
        prior_c,
        dev_tilt,
        net_policy_temp,
        ..Default::default()
    };
    let mut rng = Rng::new(dseed ^ 0x4D43_5453);
    choose_move_with_leaf(st, mover, "hard", &opts, leaf, &mut rng)
}

/// Agent A (seat `a_seat`) uses `leaf_a`; B uses `leaf_b`. Both at `sims`. Returns A's score.
fn play(gseed: u64, a_seat: usize, leaf_a: Leaf, leaf_b: Leaf, sims: u64, cap: usize, prior_a: Option<(f64, f64)>, greedy_a: bool, dev_tilt_a: f64, net_policy_temp_a: Option<f64>) -> f64 {
    let mut setup = Rng::new(mix(gseed, 0x5E7));
    let mut st = new_game(&mut setup);
    let mut game_rng = Rng::new(mix(gseed, 0x6A3E));
    let mut ply = 0usize;
    while !st.is_over() && ply < cap {
        let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
        let leaf = if mover == a_seat { leaf_a } else { leaf_b };
        // Side A's levers (prior / 1-ply greedy) apply only on A's own moves; B is plain search.
        let prior = if mover == a_seat { prior_a } else { None };
        let greedy = mover == a_seat && greedy_a;
        let dev_tilt = if mover == a_seat { dev_tilt_a } else { 0.0 };
        let net_policy_temp = if mover == a_seat { net_policy_temp_a } else { None };
        let dseed = mix(mix(gseed, mover as u64), ply as u64);
        let mv = match agent_move(&st, mover, leaf, sims, dseed, prior, greedy, dev_tilt, net_policy_temp) {
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

fn run_match(leaf_a: Leaf, leaf_b: Leaf, sims: u64, games: u64, seed0: u64, cap: usize, prior_a: Option<(f64, f64)>, greedy_a: bool, dev_tilt_a: f64, net_policy_temp_a: Option<f64>) -> (f64, u64) {
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
                    local += play(seed0 + g, 0, leaf_a, leaf_b, sims, cap, prior_a, greedy_a, dev_tilt_a, net_policy_temp_a);
                    local += play(seed0 + g, 1, leaf_a, leaf_b, sims, cap, prior_a, greedy_a, dev_tilt_a, net_policy_temp_a);
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
    let mut leaf_kind = "net".to_string();
    let mut leaf_b_kind = "heur".to_string(); // side B (default heuristic)
    let mut attn_file: Option<String> = None; // a net loaded from disk (e.g. v2), leaf kind "attnfile"
    let mut prior_temp: Option<f64> = None; // side-A 1-ply heuristic prior temperature (off = None)
    let mut prior_c: Option<f64> = None; // side-A C_PUCT override when the prior is on
    let mut greedy_net: bool = false; // side-A plays 1-ply GREEDY net (no search) instead
    let mut dev_tilt: f64 = 0.0; // side-A development-tilt on the net leaf (0 = off)
    let mut net_policy_temp: Option<f64> = None; // side-A LEARNED policy prior temperature (off = None)
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
            "--leaf" => leaf_kind = next(),
            "--leaf-b" => leaf_b_kind = next(),
            "--attn-file" => attn_file = Some(next()),
            "--prior-temp" => prior_temp = Some(next().parse().unwrap()),
            "--prior-c" => prior_c = Some(next().parse().unwrap()),
            "--greedy-net" => greedy_net = true,
            "--dev-tilt" => dev_tilt = next().parse().unwrap(),
            "--net-policy-temp" => net_policy_temp = Some(next().parse().unwrap()),
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
    let pick = |kind: &str, which: &str| -> Leaf {
        match kind {
            "heur" => Leaf::Heuristic,
            "net" => Leaf::Net(&net),
            "net8" => Leaf::Net8(&net8),
            "netval" => Leaf::NetVal(&net),
            "attnval" => Leaf::AttnVal(&attn),
            "attnfile" => Leaf::AttnVal(attn2.as_ref().expect("--attn-file required for attnfile")),
            o => panic!("{which} must be heur|net|net8|netval|attnval|attnfile, got {o}"),
        }
    };
    let leaf_a = pick(&leaf_kind, "--leaf");
    let leaf_b = pick(&leaf_b_kind, "--leaf-b");
    // Side A's optional 1-ply heuristic prior (temp, c_puct); c defaults to C_PUCT (1.5) if only temp given.
    let prior_a = prior_temp.map(|t| (t, prior_c.unwrap_or(1.5)));
    // Mirror sanity: identical configs (heur vs heur, no prior/greedy/tilt) must read 0.5000.
    let (m, mn) = run_match(Leaf::Heuristic, Leaf::Heuristic, sims, 8, seed0, cap, None, false, 0.0, None);
    println!("[mirror] heur vs heur @ {sims} : {m:.4} (n={mn}) — must be 0.5000");
    let (r, n) = run_match(leaf_a, leaf_b, sims, games, seed0, cap, prior_a, greedy_net, dev_tilt, net_policy_temp);
    let (lo, hi) = wilson(r, n);
    println!("NETLEAF GATE: {leaf_kind} vs {leaf_b_kind} @ {sims} sims : {r:.4} [{lo:.3}, {hi:.3}] (n={n})");
    if greedy_net {
        println!("  (side A = {leaf_kind} 1-PLY GREEDY net, NO search; side B = {leaf_b_kind} full search @ {sims} sims; >0.5 = greedy beats search)");
    } else if dev_tilt != 0.0 {
        println!("  (side A = {leaf_kind} + dev-tilt {dev_tilt}; side B = {leaf_b_kind} plain; >0.5 = dev-tilt helps => v2 UNDER-values development)");
    } else if let Some(t) = net_policy_temp {
        println!("  (side A = {leaf_kind} + LEARNED policy prior temp={t}; side B = {leaf_b_kind} plain; >0.5 = the learned policy prior helps)");
    } else {
        match prior_a {
            Some((t, c)) => println!("  (side A = {leaf_kind} + 1-ply prior temp={t} c_puct={c}; side B = {leaf_b_kind} plain; >0.5 = prior helps)"),
            None => println!("  (side A = {leaf_kind}; >0.5 = A beats B)"),
        }
    }
}
