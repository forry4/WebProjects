//! Self-play harvest for the learned ATTENTION policy+value net (AZ; native-only, `--features bridge`).
//!
//! The attention-arch twin of `harvest_pv`: plays full games with the shipped HARD bot (v2 attention
//! netval search) and dumps, per DECISION POINT, one row of
//! `game_id, token-features(tok/mask/state), outcome, softmax-over-Q policy target(320-space)`.
//! `harvest_pv` records the 275-dim FLAT feats for the MLP PV net; this records the card-set
//! ATTENTION token-features (`feats::features_tokens`) so the target trains an attention POLICY head
//! on the SAME trunk that already serves the strong v2 VALUE (a policy head was measured to need the
//! attention arch — the MLP prior washed). The value head warm-starts from v2; the policy head is new.
//!
//! POLICY TARGET = SOFTMAX OVER MEAN-Q, **not** visit counts — identical rationale to `harvest_pv`:
//! Duel's determinized PUCT is exploration-heavy, so visits come out ~uniform ("quality lives in Q").
//! `build_target` is copied verbatim from `harvest_pv`; the SANITY readout (target entropy vs
//! log(n_legal)) is the make-or-break check that the target is genuinely peaked.
//!
//! BINARY FORMAT (little-endian):
//!   header (once):  b"DUELAP01" | u32 tok_n | u32 tok_f | u32 tok_state | u32 n_actions
//!   each row:       u32 game_id
//!                   f32 * (tok_n*tok_f)  token features (mover's seat)
//!                   f32 * tok_n          token present-mask
//!                   f32 * tok_state      global state features
//!                   f32 outcome          (+1 the mover won, -1 lost)
//!                   u16 n_legal          (== number of target entries)
//!                   n_legal x [ u16 action_index, f32 target_prob ]
//! A sibling `<out>.meta.json` records the row count, args, dims, and this layout.
//!
//!     cargo run --release --features bridge --bin harvest_attn_pv -- \
//!         --games 1000 --sims 700 --seed 0 --out C:/Users/Forrest/duel_run/pv/shard_0.bin

use std::io::{BufWriter, Write};

use duel_core::actions::{move_to_index, N_ACTIONS};
use duel_core::attn::AttnNet;
use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::clock::Clock;
use duel_core::engine::{State, EMPTY, N_CELLS};
use duel_core::feats::{features_tokens, TOK_F, TOK_N, TOK_STATE};
use duel_core::mcts::{pick, root_search_with_leaf, Leaf, Opts, RngShuffler, RootStats};
use duel_core::rng::Rng;

// The search that produces the policy target runs the SHIPPED v2 ATTENTION value net (netval leaf),
// exactly as `harvest_pv`'s re-test does — a sharper evaluator gives sharper root Q -> a learnable
// target. Rollout is 2-step (gate-verified equal to 12, ~3x faster).
static ATTN_NET_JSON: &str = include_str!("../attn_value_net.json");

const TOK_LEN: usize = TOK_N * TOK_F;

/// Deal a fresh game with `rng` — structural copy of `harvest_pv::new_game` / `engine.py::new_game`.
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

/// A finished row: token features + the mover seat's outcome + the sparse policy target.
struct Row {
    game_id: u64,
    tok: Vec<f64>,
    mask: Vec<f64>,
    state: Vec<f64>,
    outcome: f32,
    entries: Vec<(u16, f32)>, // one per legal root move: (action_index, target_prob)
    argmax_root: usize,       // root move with the highest target prob (highest mean Q)
    greedy_root: usize,       // the search's greedy pick (visits, tie-break Q)
    collision: bool,          // two root moves mapped to the same action index (should never happen)
}

/// Build the softmax-over-Q policy target for a decision, plus the target's argmax root index.
/// Copied verbatim from `harvest_pv` (the target definition must not drift between the two harvests).
fn build_target(st: &State, stats: &RootStats, target_temp: f64) -> (Vec<(u16, f32)>, usize) {
    let n = stats.moves.len();
    let idxs: Vec<u16> = stats.moves.iter().map(|m| move_to_index(st, m) as u16).collect();

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
fn play_game(
    game_id: u64,
    sims: u64,
    temp_plies: usize,
    temp: f64,
    target_temp: f64,
    seed: u64,
    cap: usize,
    net: &AttnNet,
    net_policy_temp: Option<f64>,
) -> Vec<Row> {
    let mut rng = Rng::new(seed);
    let mut st = new_game(&mut rng);
    // (mover, tok, mask, state, entries, argmax_root, greedy_root, collision) — outcome at the end.
    type Pend = (usize, Vec<f64>, Vec<f64>, Vec<f64>, Vec<(u16, f32)>, usize, usize, bool);
    let mut pending: Vec<Pend> = Vec::new();
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

        // Iteration-bounded search (clock-free -> reproducible). Temperature is a pick-time knob, so
        // one search serves both the recorded target and the played move.
        let opts = Opts { max_iters: Some(sims), time_limit: Some(f64::INFINITY), rollout_steps: Some(2), net_policy_temp, ..Default::default() };
        let stats = match root_search_with_leaf(&st, mover, "hard", &opts, Leaf::AttnVal(net), &mut rng) {
            Some(s) => s,
            None => break,
        };

        let (entries, argmax_root) = build_target(&st, &stats, target_temp);
        let collision = {
            let mut ks: Vec<u16> = entries.iter().map(|&(k, _)| k).collect();
            ks.sort_unstable();
            ks.windows(2).any(|w| w[0] == w[1])
        };
        let greedy_root = pick(&stats, 0.0, &mut rng);
        pending.push((mover, tok, mask, state, entries, argmax_root, greedy_root, collision));

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
    pending
        .into_iter()
        .map(|(seat, tok, mask, state, entries, argmax_root, greedy_root, collision)| Row {
            game_id,
            tok,
            mask,
            state,
            outcome: if winner == seat as i32 { 1.0 } else { -1.0 },
            entries,
            argmax_root,
            greedy_root,
            collision,
        })
        .collect()
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
    wu16(w, row.entries.len() as u16);
    for &(idx, p) in &row.entries {
        wu16(w, idx);
        wf32(w, p);
    }
}

// ── Sanity accumulators (identical to harvest_pv) ──────────────────────────────
#[derive(Default)]
struct Sanity {
    rows: u64,
    sum_n_legal: f64,
    multi_rows: u64,
    sum_entropy: f64,
    sum_log_nlegal: f64,
    argmax_pick_match: u64,
    forced_rows: u64,
    collisions: u64,
}

impl Sanity {
    fn add(&mut self, row: &Row) {
        self.rows += 1;
        let n = row.entries.len();
        self.sum_n_legal += n as f64;
        if row.collision {
            self.collisions += 1;
        }
        if n <= 1 {
            self.forced_rows += 1;
            return;
        }
        self.multi_rows += 1;
        let ent: f64 = row
            .entries
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
        self.sum_entropy += ent;
        self.sum_log_nlegal += (n as f64).ln();
        if row.argmax_root == row.greedy_root {
            self.argmax_pick_match += 1;
        }
    }
}

struct Args {
    games: u64,
    sims: u64,
    temp_plies: usize,
    temp: f64,
    target_temp: f64,
    seed: u64,
    out: String,
    cap: usize,
    attn_file: Option<String>,
    net_policy_temp: Option<f64>,
}

fn parse_args() -> Args {
    let mut a = Args {
        games: 1000,
        sims: 700,
        temp_plies: 12,
        temp: 0.5,
        target_temp: 0.1,
        seed: 0,
        out: "duel_attn_pv.bin".to_string(),
        cap: 600,
        attn_file: None,
        net_policy_temp: None,
    };
    let argv: Vec<String> = std::env::args().collect();
    let mut i = 1;
    while i < argv.len() {
        let key = argv[i].as_str();
        let mut next = || {
            i += 1;
            argv.get(i).cloned().unwrap_or_else(|| panic!("missing value for {}", key))
        };
        match key {
            "--games" => a.games = next().parse().expect("--games N"),
            "--sims" => a.sims = next().parse().expect("--sims S"),
            "--temp-plies" => a.temp_plies = next().parse().expect("--temp-plies P"),
            "--temp" => a.temp = next().parse().expect("--temp T"),
            "--target-temp" => a.target_temp = next().parse().expect("--target-temp T"),
            "--seed" => a.seed = next().parse().expect("--seed K"),
            "--out" => a.out = next(),
            "--cap" => a.cap = next().parse().expect("--cap N"),
            "--attn-file" => a.attn_file = Some(next()),
            "--net-policy-temp" => a.net_policy_temp = Some(next().parse().expect("--net-policy-temp T")),
            other => panic!("unknown arg: {}", other),
        }
        i += 1;
    }
    a
}

fn main() {
    let args = parse_args();
    assert!(args.target_temp > 0.0, "--target-temp must be > 0");

    // The search net: the embedded v2 (unguided iteration-0 harvest), OR a loaded PV net (with a
    // policy head) played GUIDED via --net-policy-temp — the AZ iteration-N>=1 data generator. The
    // value leaf is the loaded net's value; for a frozen-trunk PV net that is byte-identical to v2.
    let net = match &args.attn_file {
        Some(p) => AttnNet::from_json_str(&std::fs::read_to_string(p).expect("read --attn-file")).expect("parse --attn-file"),
        None => AttnNet::from_json_str(ATTN_NET_JSON).expect("load embedded attn_value_net.json"),
    };

    let file = std::fs::File::create(&args.out).expect("create --out file");
    let mut w = BufWriter::new(file);
    w.write_all(b"DUELAP01").unwrap();
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
        let rows = play_game(g, args.sims, args.temp_plies, args.temp, args.target_temp, gseed, args.cap, &net, args.net_policy_temp);
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
    let mean_n_legal = if san.rows > 0 { san.sum_n_legal / san.rows as f64 } else { 0.0 };
    let mean_entropy = if san.multi_rows > 0 { san.sum_entropy / san.multi_rows as f64 } else { 0.0 };
    let mean_log_nlegal = if san.multi_rows > 0 { san.sum_log_nlegal / san.multi_rows as f64 } else { 0.0 };
    let peaked_ratio = if mean_log_nlegal > 0.0 { mean_entropy / mean_log_nlegal } else { 0.0 };
    let argmax_pick_frac =
        if san.multi_rows > 0 { san.argmax_pick_match as f64 / san.multi_rows as f64 } else { 0.0 };

    let meta = serde_json::json!({
        "magic": "DUELAP01",
        "tok_n": TOK_N,
        "tok_f": TOK_F,
        "tok_len": TOK_LEN,
        "tok_state": TOK_STATE,
        "n_actions": N_ACTIONS,
        "rows": san.rows,
        "games_played": args.games,
        "games_terminated": terminated_games,
        "games_discarded": discarded_games,
        "args": {
            "games": args.games, "sims": args.sims, "temp_plies": args.temp_plies,
            "temp": args.temp, "target_temp": args.target_temp, "seed": args.seed, "cap": args.cap,
        },
        "row_layout": "u32 game_id | f32*tok_len tok | f32*tok_n mask | f32*tok_state state | f32 outcome | u16 n_legal | n_legal*(u16 action_index, f32 prob), all little-endian",
    });
    let meta_path = format!("{}.meta.json", args.out);
    std::fs::write(&meta_path, serde_json::to_string_pretty(&meta).unwrap()).expect("write meta.json");

    eprintln!("── attn pv harvest complete ──");
    eprintln!("out                 : {}", args.out);
    eprintln!("meta                : {}", meta_path);
    eprintln!("tok {}x{} state {} act {}", TOK_N, TOK_F, TOK_STATE, N_ACTIONS);
    eprintln!("mode                : {}", match (&args.attn_file, args.net_policy_temp) {
        (Some(f), Some(t)) => format!("GUIDED self-play (prior net {f}, temp {t})"),
        (Some(f), None) => format!("value-net {f}, UNGUIDED"),
        _ => "embedded v2, UNGUIDED (iteration-0)".to_string(),
    });
    eprintln!("games (played)      : {}", args.games);
    eprintln!("games (terminated)  : {}", terminated_games);
    eprintln!("games (discarded)   : {}", discarded_games);
    eprintln!("rows                : {}  ({} multi-move, {} forced)", san.rows, san.multi_rows, san.forced_rows);
    eprintln!("elapsed             : {:.2}s", elapsed);
    eprintln!(
        "throughput          : {:.2} games/s, {:.0} rows/s",
        args.games as f64 / elapsed,
        san.rows as f64 / elapsed
    );
    eprintln!("mean n_legal        : {:.2}", mean_n_legal);
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
        eprintln!("!! The policy-prior premise is unsupported at this --target-temp/--sims. Rethink before training.");
    } else {
        eprintln!("OK: the Q-softmax target is peaked (well below uniform) — a real policy signal.");
    }
}
