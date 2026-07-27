//! Self-play harvest for the learned ATTENTION policy+value net (AZ; native-only, `--features bridge`).
//!
//! The COHERENT-search flywheel generator: plays full games with the coherent single-world search
//! (determinize once + chance frozen — the regime that made policy targets learnable; per-sim PIMC
//! injected the old flatness) and dumps, per DECISION POINT, the mover's token features, the game
//! outcome, the search ROOT VALUE (value-bootstrap), and the RAW root statistics `(action, mean_q,
//! visits)` per legal move — so the trainer can build softmax-over-Q at ANY temperature AND visit-pi
//! targets from ONE harvest (no re-harvest for target sweeps).
//!
//! `--leaf-b` plays side B as a different net/heuristic (frozen-pool / style opponents for league
//! diversity). Opponent-seat rows keep their VALUE label but get `policy_valid=0` — pool games
//! diversify the value head without injecting foreign priors into the POLICY head.
//!
//! BINARY FORMAT (little-endian):
//!   header (once):  b"DUELAP02" | u32 tok_n | u32 tok_f | u32 tok_state | u32 n_actions
//!   each row:       u32 game_id
//!                   f32 * (tok_n*tok_f)  token features (mover's seat)
//!                   f32 * tok_n          token present-mask
//!                   f32 * tok_state      global state features
//!                   f32 outcome          (+1 the mover won, -1 lost)
//!                   f32 rootval          (search root value, mover's perspective; see flags bit1)
//!                   u8  flags            (bit0 = policy_valid, bit1 = rootval_valid)
//!                   u16 n_legal          (== number of entries; 1 == forced move -> target prob 1.0)
//!                   n_legal x [ u16 action_index, f32 mean_q, f32 visits ]
//!                     (visits == 0.0 -> mean_q meaningless; exclude from any softmax, like the
//!                      sanity readout's build_target does)
//! A sibling `<out>.meta.json` records the row count, args, dims, and this layout.
//!
//!     cargo run --release --features bridge --bin harvest_attn_pv -- \
//!         --games 500 --sims 1200 --cpuct 0.3 --seed 0 --out C:/Users/Forrest/duel_run/pv/shard_0.bin
//!
//! The printed SANITY readout (target entropy at `--target-temp` vs log(n_legal), argmax==greedy)
//! is the F1 tripwire: a near-uniform target means the coherent-Q premise failed at these settings.

use std::io::{BufWriter, Write};

use duel_core::actions::{move_to_index, N_ACTIONS};
use duel_core::attn::AttnNet;
use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::clock::Clock;
use duel_core::engine::{State, EMPTY, N_CELLS};
use duel_core::feats::{features_tokens, TOK_F, TOK_N, TOK_STATE};
use duel_core::mcts::{pick, root_search_with_leaf, Leaf, Opts, RngShuffler, RootStats};
use duel_core::rng::Rng;

// Default search net (side A when no --attn-file): the shipped v2 attention value net.
static ATTN_NET_JSON: &str = include_str!("../attn_value_net.json");

const TOK_LEN: usize = TOK_N * TOK_F;

/// Deal a fresh game with `rng` — structural copy of `harvest_attn::new_game` / `engine.py::new_game`.
fn new_game(rng: &mut Rng) -> State {
    let mut decks: [Vec<usize>; 3] = [(0..30).collect(), (30..54).collect(), (54..67).collect()];
    let sizes = [5usize, 4, 3];
    let mut pyramid: [Vec<i32>; 3] = [Vec::new(), Vec::new(), Vec::new()];
    for lvl in 0..3 {
        rng.shuffle(&mut decks[lvl]);
        for _ in 0..sizes[lvl] {
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

/// A finished row: token features + labels + the raw sparse root stats.
struct Row {
    game_id: u64,
    seat: usize, // the mover (outcome is filled per-seat at game end; not serialized)
    tok: Vec<f64>,
    mask: Vec<f64>,
    state: Vec<f64>,
    outcome: f32,
    rootval: f32,
    rootval_valid: bool,             // false for unsearched (forced-move) roots — rootval is meaningless
    policy_valid: bool,              // false for opponent-seat rows in a --leaf-b matchup
    entries: Vec<(u16, f32, f32)>,   // one per legal root move: (action_index, mean_q, visits)
    // ── sanity scalars (computed at --target-temp; readout only, not part of the format) ──
    target_entropy: f64,
    argmax_root: usize,
    greedy_root: usize,
    collision: bool,
}

/// Build the softmax-over-Q policy target for the SANITY readout (kept verbatim from DUELAP01 so the
/// peakedness numbers stay comparable across harvests). The trainer builds its own targets from the
/// raw entries; this is only the tripwire.
fn build_target(idxs: &[u16], stats: &RootStats, target_temp: f64) -> (Vec<(u16, f32)>, usize) {
    let n = stats.moves.len();
    if n == 1 {
        return (vec![(idxs[0], 1.0)], 0);
    }
    let mut best_q = f64::NEG_INFINITY;
    let mut argmax = 0usize;
    let mut any = false;
    for i in 0..n {
        if stats.n[i] != 0 {
            let q = stats.w[i] / stats.n[i] as f64;
            if q > best_q {
                best_q = q;
                argmax = i;
            }
            any = true;
        }
    }
    let mut w = vec![0f64; n];
    if any {
        let mut sum = 0.0;
        for i in 0..n {
            if stats.n[i] != 0 {
                let e = ((stats.w[i] / stats.n[i] as f64 - best_q) / target_temp).exp();
                w[i] = e;
                sum += e;
            }
        }
        for x in w.iter_mut() {
            *x /= sum;
        }
    } else {
        for x in w.iter_mut() {
            *x = 1.0 / n as f64;
        }
    }
    let entries: Vec<(u16, f32)> = (0..n).map(|i| (idxs[i], w[i] as f32)).collect();
    (entries, argmax)
}

/// Play one game to a terminal, recording every decision. Empty if the game failed to terminate.
#[allow(clippy::too_many_arguments)]
fn play_game(
    game_id: u64,
    sims: u64,
    temp_plies: usize,
    temp: f64,
    target_temp: f64,
    cpuct: f64,
    seed: u64,
    cap: usize,
    a_seat: usize,
    leaf_a: Leaf,
    leaf_b: Leaf,
    matchup: bool,
    net_policy_temp: Option<f64>,
    minimax: bool,
) -> Vec<Row> {
    let mut rng = Rng::new(seed);
    let mut st = new_game(&mut rng);
    let mut rows: Vec<Row> = Vec::new();
    let mut ply = 0usize;

    loop {
        if st.is_over() {
            break;
        }
        if ply >= cap {
            return Vec::new(); // never terminated: discard rather than label a truncation
        }
        let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
        let (tok, mask, state) = features_tokens(&st, mover);
        let leaf = if mover == a_seat { leaf_a } else { leaf_b };

        // COHERENT search (determinize once + chance frozen) at a tight-ish c_puct — the regime whose
        // Q separation makes the policy target learnable. Iteration-bounded (clock-free, reproducible).
        let opts = Opts {
            max_iters: Some(sims),
            time_limit: Some(f64::INFINITY),
            rollout_steps: Some(2),
            net_policy_temp,
            coherent: true,
            prior_c: Some(cpuct),
            minimax,
            ..Default::default()
        };
        let stats = match root_search_with_leaf(&st, mover, "hard", &opts, leaf, &mut rng) {
            Some(s) => s,
            None => break,
        };

        // Root value (value-bootstrap): Σw/Σn — same definition as choose_move_and_rootval_with_leaf.
        let tot_n: i64 = stats.n.iter().map(|&x| x as i64).sum();
        let (rootval, rootval_valid) = if tot_n > 0 {
            ((stats.w.iter().sum::<f64>() / tot_n as f64) as f32, true)
        } else {
            (0.0, false)
        };

        let idxs: Vec<u16> = stats.moves.iter().map(|m| move_to_index(&st, m) as u16).collect();
        let collision = {
            let mut ks = idxs.clone();
            ks.sort_unstable();
            ks.windows(2).any(|w| w[0] == w[1])
        };
        let (sanity_target, argmax_root) = build_target(&idxs, &stats, target_temp);
        let target_entropy: f64 = sanity_target
            .iter()
            .map(|&(_, p)| {
                let p = p as f64;
                if p > 0.0 {
                    -p * p.ln()
                } else {
                    0.0
                }
            })
            .sum();
        let entries: Vec<(u16, f32, f32)> = (0..stats.moves.len())
            .map(|i| {
                let q = if stats.n[i] != 0 { (stats.w[i] / stats.n[i] as f64) as f32 } else { 0.0 };
                (idxs[i], q, stats.n[i] as f32)
            })
            .collect();
        let greedy_root = pick(&stats, 0.0, &mut rng);

        rows.push(Row {
            game_id,
            seat: mover,
            tok,
            mask,
            state,
            outcome: 0.0, // filled per-seat at game end
            rootval,
            rootval_valid,
            policy_valid: !matchup || mover == a_seat,
            entries,
            target_entropy,
            argmax_root,
            greedy_root,
            collision,
        });

        // Opening diversity: sample the first `temp-plies` picks by softmax-over-Q, then greedy.
        let play_temp = if ply < temp_plies { temp } else { 0.0 };
        let chosen = pick(&stats, play_temp, &mut rng);
        let mv = stats.moves[chosen].clone();
        let mut sh = RngShuffler { rng: &mut rng };
        if st.apply_move(mover, &mv, &mut sh).is_err() {
            break;
        }
        ply += 1;
    }

    if !st.is_over() {
        return Vec::new();
    }
    let winner = st.winner;
    for row in rows.iter_mut() {
        row.outcome = if winner == row.seat as i32 { 1.0 } else { -1.0 };
    }
    rows
}

// ── Binary writers (little-endian) ────────────────────────────────────────────
#[inline]
fn wf32<W: Write>(w: &mut W, x: f32) {
    w.write_all(&x.to_le_bytes()).unwrap();
}
#[inline]
fn wu16<W: Write>(w: &mut W, x: u16) {
    w.write_all(&x.to_le_bytes()).unwrap();
}
#[inline]
fn wu32<W: Write>(w: &mut W, x: u32) {
    w.write_all(&x.to_le_bytes()).unwrap();
}

fn write_row<W: Write>(w: &mut W, row: &Row) {
    wu32(w, row.game_id as u32);
    for &v in &row.tok {
        wf32(w, v as f32);
    }
    for &v in &row.mask {
        wf32(w, v as f32);
    }
    for &v in &row.state {
        wf32(w, v as f32);
    }
    wf32(w, row.outcome);
    wf32(w, row.rootval);
    let flags: u8 = (row.policy_valid as u8) | ((row.rootval_valid as u8) << 1);
    w.write_all(&[flags]).unwrap();
    wu16(w, row.entries.len() as u16);
    for &(idx, q, n) in &row.entries {
        wu16(w, idx);
        wf32(w, q);
        wf32(w, n);
    }
}

// ── Sanity accumulators (policy_valid rows only — the readout describes the TRAINING policy data) ──
#[derive(Default)]
struct Sanity {
    rows: u64,
    value_only_rows: u64,
    sum_n_legal: f64,
    multi_rows: u64,
    sum_entropy: f64,
    sum_log_nlegal: f64,
    argmax_pick_match: u64,
    forced_rows: u64,
    collisions: u64,
    // corr(rootval, outcome) over rootval_valid rows — the value-bootstrap wiring check (F3 drift).
    rv_n: f64,
    rv_sx: f64,
    rv_sy: f64,
    rv_sxx: f64,
    rv_syy: f64,
    rv_sxy: f64,
}

impl Sanity {
    fn add(&mut self, row: &Row) {
        self.rows += 1;
        if row.collision {
            self.collisions += 1;
        }
        if row.rootval_valid {
            let (x, y) = (row.rootval as f64, row.outcome as f64);
            self.rv_n += 1.0;
            self.rv_sx += x;
            self.rv_sy += y;
            self.rv_sxx += x * x;
            self.rv_syy += y * y;
            self.rv_sxy += x * y;
        }
        if !row.policy_valid {
            self.value_only_rows += 1;
            return;
        }
        let n = row.entries.len();
        self.sum_n_legal += n as f64;
        if n <= 1 {
            self.forced_rows += 1;
            return;
        }
        self.multi_rows += 1;
        self.sum_entropy += row.target_entropy;
        self.sum_log_nlegal += (n as f64).ln();
        if row.argmax_root == row.greedy_root {
            self.argmax_pick_match += 1;
        }
    }
    fn corr_rv(&self) -> f64 {
        let cov = self.rv_n * self.rv_sxy - self.rv_sx * self.rv_sy;
        let vx = self.rv_n * self.rv_sxx - self.rv_sx * self.rv_sx;
        let vy = self.rv_n * self.rv_syy - self.rv_sy * self.rv_sy;
        let d = (vx * vy).sqrt();
        if d == 0.0 {
            0.0
        } else {
            cov / d
        }
    }
}

struct Args {
    games: u64,
    sims: u64,
    temp_plies: usize,
    temp: f64,
    target_temp: f64,
    cpuct: f64,
    seed: u64,
    out: String,
    cap: usize,
    attn_file: Option<String>,
    attn_file_b: Option<String>,
    leaf_b: String,
    net_policy_temp: Option<f64>,
    minimax: bool,
}

fn parse_args() -> Args {
    let mut a = Args {
        games: 1000,
        sims: 700,
        temp_plies: 12,
        temp: 0.5,
        target_temp: 0.1,
        cpuct: 0.3,
        seed: 0,
        out: "duel_attn_pv.bin".to_string(),
        cap: 600,
        attn_file: None,
        attn_file_b: None,
        leaf_b: String::new(),
        net_policy_temp: None,
        minimax: false,
    };
    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        let key = argv[i].clone();
        let mut next = || {
            i += 1;
            argv.get(i).cloned().unwrap_or_else(|| panic!("missing value for {}", key))
        };
        match key.as_str() {
            "--games" => a.games = next().parse().expect("--games N"),
            "--sims" => a.sims = next().parse().expect("--sims S"),
            "--temp-plies" => a.temp_plies = next().parse().expect("--temp-plies P"),
            "--temp" => a.temp = next().parse().expect("--temp T"),
            "--target-temp" => a.target_temp = next().parse().expect("--target-temp T"),
            "--cpuct" => a.cpuct = next().parse().expect("--cpuct C"),
            "--seed" => a.seed = next().parse().expect("--seed K"),
            "--out" => a.out = next(),
            "--cap" => a.cap = next().parse().expect("--cap N"),
            "--attn-file" => a.attn_file = Some(next()),
            "--attn-file-b" => a.attn_file_b = Some(next()),
            "--leaf-b" => a.leaf_b = next(),
            "--net-policy-temp" => a.net_policy_temp = Some(next().parse().expect("--net-policy-temp T")),
            "--minimax" => a.minimax = true,
            other => panic!("unknown arg: {}", other),
        }
        i += 1;
    }
    a
}

fn main() {
    let args = parse_args();
    assert!(args.target_temp > 0.0, "--target-temp must be > 0");
    assert!(args.cpuct > 0.0, "--cpuct must be > 0");

    // Side A: the embedded v2 (iteration-0) or a loaded net (champion / PV net; GUIDED when
    // --net-policy-temp is set and the net carries a policy head). Side B (optional): a frozen-pool
    // net (attnfile2) or a style heuristic — league diversity.
    let net = match &args.attn_file {
        Some(p) => AttnNet::from_json_str(&std::fs::read_to_string(p).expect("read --attn-file")).expect("parse --attn-file"),
        None => AttnNet::from_json_str(ATTN_NET_JSON).expect("load embedded attn_value_net.json"),
    };
    let net_b = args.attn_file_b.as_ref().map(|p| {
        AttnNet::from_json_str(&std::fs::read_to_string(p).expect("read --attn-file-b")).expect("parse --attn-file-b")
    });
    let mk_leaf_b = |kind: &str| -> Leaf {
        match kind {
            "attnfile2" => Leaf::AttnVal(net_b.as_ref().expect("--attn-file-b required for attnfile2")),
            "heurdev" => Leaf::HeuristicW(&duel_core::value::DEV_WEIGHTS),
            "heur" => Leaf::Heuristic,
            o => panic!("--leaf-b must be attnfile2|heurdev|heur, got {o}"),
        }
    };
    let matchup = !args.leaf_b.is_empty();
    let leaf_a = Leaf::AttnVal(&net);
    let leaf_b = if matchup { mk_leaf_b(&args.leaf_b) } else { leaf_a };

    let file = std::fs::File::create(&args.out).expect("create --out file");
    let mut w = BufWriter::new(file);
    w.write_all(b"DUELAP02").unwrap();
    wu32(&mut w, TOK_N as u32);
    wu32(&mut w, TOK_F as u32);
    wu32(&mut w, TOK_STATE as u32);
    wu32(&mut w, N_ACTIONS as u32);

    let mut san = Sanity::default();
    let mut terminated_games: u64 = 0;
    let mut discarded_games: u64 = 0;
    let clock = Clock::start();

    for g in 0..args.games {
        let gseed = args.seed ^ (g.wrapping_mul(0x9E37_79B9_7F4A_7C15));
        let a_seat = (g % 2) as usize; // seat alternation for first-player balance in matchups
        let rows = play_game(
            g, args.sims, args.temp_plies, args.temp, args.target_temp, args.cpuct, gseed, args.cap,
            a_seat, leaf_a, leaf_b, matchup, args.net_policy_temp, args.minimax,
        );
        if rows.is_empty() {
            discarded_games += 1;
            continue;
        }
        terminated_games += 1;
        for row in &rows {
            san.add(row);
            write_row(&mut w, row);
        }
        w.flush().unwrap();
    }
    w.flush().unwrap();
    drop(w);

    let elapsed = clock.elapsed_secs().max(1e-9);
    let policy_rows = san.rows - san.value_only_rows;
    let mean_n_legal = if policy_rows > 0 { san.sum_n_legal / policy_rows as f64 } else { 0.0 };
    let mean_entropy = if san.multi_rows > 0 { san.sum_entropy / san.multi_rows as f64 } else { 0.0 };
    let mean_log_nlegal = if san.multi_rows > 0 { san.sum_log_nlegal / san.multi_rows as f64 } else { 0.0 };
    let peaked_ratio = if mean_log_nlegal > 0.0 { mean_entropy / mean_log_nlegal } else { 0.0 };
    let argmax_pick_frac =
        if san.multi_rows > 0 { san.argmax_pick_match as f64 / san.multi_rows as f64 } else { 0.0 };

    let meta = serde_json::json!({
        "magic": "DUELAP02",
        "tok_n": TOK_N,
        "tok_f": TOK_F,
        "tok_len": TOK_LEN,
        "tok_state": TOK_STATE,
        "n_actions": N_ACTIONS,
        "rows": san.rows,
        "policy_rows": policy_rows,
        "value_only_rows": san.value_only_rows,
        "games_played": args.games,
        "games_terminated": terminated_games,
        "games_discarded": discarded_games,
        "args": {
            "games": args.games, "sims": args.sims, "temp_plies": args.temp_plies,
            "temp": args.temp, "target_temp": args.target_temp, "cpuct": args.cpuct,
            "seed": args.seed, "cap": args.cap,
            "attn_file": args.attn_file, "attn_file_b": args.attn_file_b, "leaf_b": args.leaf_b,
            "net_policy_temp": args.net_policy_temp,
        },
        "row_layout": "u32 game_id | f32*tok_len tok | f32*tok_n mask | f32*tok_state state | f32 outcome | f32 rootval | u8 flags(bit0=policy_valid,bit1=rootval_valid) | u16 n_legal | n_legal*(u16 action_index, f32 mean_q, f32 visits), all little-endian; n_legal==1 => forced (target prob 1.0); visits==0 entries excluded from any softmax",
    });
    let meta_path = format!("{}.meta.json", args.out);
    std::fs::write(&meta_path, serde_json::to_string_pretty(&meta).unwrap()).expect("write meta.json");

    eprintln!("── attn pv harvest complete (DUELAP02, COHERENT cpuct {}) ──", args.cpuct);
    eprintln!("out                 : {}", args.out);
    eprintln!("meta                : {}", meta_path);
    eprintln!("tok {}x{} state {} act {}", TOK_N, TOK_F, TOK_STATE, N_ACTIONS);
    eprintln!("mode                : {}", match (&args.attn_file, args.net_policy_temp) {
        (Some(f), Some(t)) => format!("GUIDED self-play (prior net {f}, temp {t})"),
        (Some(f), None) => format!("value-net {f}, UNGUIDED"),
        (None, Some(t)) => format!("embedded v2, GUIDED temp {t}"),
        _ => "embedded v2, UNGUIDED (iteration-0)".to_string(),
    });
    if matchup {
        eprintln!("side B              : {} {}", args.leaf_b, args.attn_file_b.as_deref().unwrap_or(""));
    }
    eprintln!("games (terminated)  : {} / {} ({} discarded)", terminated_games, args.games, discarded_games);
    eprintln!("rows                : {}  ({} policy [{} multi, {} forced], {} value-only)", san.rows, policy_rows, san.multi_rows, san.forced_rows, san.value_only_rows);
    eprintln!("elapsed             : {:.2}s  ({:.2} games/s, {:.0} rows/s)", elapsed, args.games as f64 / elapsed, san.rows as f64 / elapsed);
    eprintln!("mean n_legal        : {:.2}", mean_n_legal);
    eprintln!("corr(rootval,outc)  : {:.4}  (value-bootstrap wiring check; must be > 0)", san.corr_rv());
    eprintln!(
        "target entropy      : {:.4} nats   (mean log(n_legal) = {:.4}; ratio {:.3} — PEAKED if << 1)",
        mean_entropy, mean_log_nlegal, peaked_ratio
    );
    eprintln!("argmax==greedy pick : {:.3}   (over {} multi-move rows)", argmax_pick_frac, san.multi_rows);
    if san.collisions > 0 {
        eprintln!("!! {} row(s) had an action-index COLLISION across root moves — investigate actions.rs", san.collisions);
    }
    if peaked_ratio >= 0.85 {
        eprintln!("!! WARNING: policy target is NEAR-UNIFORM (entropy ~= log(n_legal)) — weak Q signal.");
        eprintln!("!! The policy-prior premise is unsupported at this --target-temp/--sims/--cpuct. Rethink before training.");
    } else {
        eprintln!("OK: the Q-softmax target is peaked (well below uniform) — a real policy signal.");
    }
}
