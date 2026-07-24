//! Self-play harvest for the learned POLICY+value net (Phase 3; native-only, `--features bridge`).
//!
//! Plays full games with the current HARD bot and dumps, per DECISION POINT, one row of:
//! `game_id, features(275), outcome, a policy target over the 320-action space`. Phase 3 trains
//! a policy net on the target and wires it into PUCT as a PRIOR while KEEPING the heuristic value
//! leaf (a learned value leaf was measured to degrade with depth — see `feats.rs`). The action
//! index space is `actions.rs`; the encoder is `feats.rs` — both are the one source of truth.
//!
//! THE POLICY TARGET IS SOFTMAX OVER MEAN-Q, **NOT** VISIT COUNTS. Duel's determinized PUCT is
//! deliberately exploration-heavy (see `mcts::select`: no prior scaling), so its visit counts
//! come out near-UNIFORM across ~76 root moves — "quality lives in Q, not in the visit
//! distribution" (this is exactly why the "normal" tier samples softmax-over-Q, and why
//! visit-temperature was measured to collapse to random). Training a prior on visits would learn
//! a useless ~uniform policy. So the target is `softmax(Q_i / T)` over the legal root moves (Q_i =
//! w[i]/n[i] in [-1,1]; unvisited moves get weight 0), which says "these are the good moves" — the
//! thing a PUCT prior should encode. `--target-temp` (T, default 0.1) is the peaking knob; the
//! printed target ENTROPY vs log(n_legal) is the sanity check that it is genuinely peaked.
//!
//! WHY THE KNOBS MATTER (mirrors `harvest_value`):
//!   * `--sims` (400) — near the heuristic plateau, iteration-bounded (clock-free) so a busy box
//!     can't weaken play and skew the target.
//!   * `--temp`/`--temp-plies` — opening PLAY diversity (softmax-over-Q PICK for the first
//!     `temp-plies` decisions, then greedy). WITHOUT it every game is near-identical and worthless.
//!     This is the play temperature, DISTINCT from `--target-temp` (the recorded target's peak).
//!   * game seed = `--seed` XOR-mixed with the game index — fully reproducible, no shared streams.
//!     The rng is consumed in the same order as `harvest_value` (root_search then the play pick),
//!     so the two harvests generate the SAME games given the same seed.
//!
//! BINARY FORMAT (compact — a 320-wide policy is far too big/slow for CSV). Little-endian:
//!   header (once):  b"DUELPV01" | u32 n_feats | u32 n_actions
//!   each row:       u32 game_id
//!                   f32 * n_feats   (features from the mover's seat)
//!                   f32 outcome     (+1 the mover won the game, -1 lost)
//!                   u16 n_legal     (number of legal root moves == number of target entries)
//!                   n_legal x [ u16 action_index, f32 target_prob ]
//! `game_id` is the per-shard game index; the trainer OFFSETS it per shard for a game-split
//! holdout (rows of one game must never straddle the train/val boundary). A sibling
//! `<out>.meta.json` records the row count, the args, N_FEATS/N_ACTIONS, and this layout.
//!
//! SANITY (printed): mean n_legal; mean target ENTROPY vs mean log(n_legal) — the target MUST be
//! well below uniform (peaked), or the Q signal is weak and the whole prior approach needs a
//! rethink (a crucial early signal — the run says so loudly if it is ~uniform); and the fraction
//! of rows where the target's argmax == the search's greedy pick (should be high — the peaked
//! target agrees with the move the search would actually play).
//!
//!     cargo run --release --features bridge --bin harvest_pv -- \
//!         --games 200 --sims 400 --out /tmp/duel_pv.bin

use std::io::{BufWriter, Write};

use duel_core::actions::{move_to_index, N_ACTIONS};
use duel_core::attn::AttnNet;
use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::clock::Clock;
use duel_core::engine::{State, EMPTY, N_CELLS};
use duel_core::feats::{features, N_FEATS};
use duel_core::mcts::{pick, root_search_with_leaf, Leaf, Opts, RngShuffler, RootStats};
use duel_core::rng::Rng;

// POLICY RE-TEST: the search that produces the policy target now runs the SHIPPED ATTENTION NET
// (v2), not the heuristic. The old "policy is near-uniform / dead" verdict was measured on the
// COARSE heuristic's search; a sharper evaluator should give sharper root Q -> a more learnable
// policy target. Rollout is 2-step (gate-verified equal to 12, ~3x faster).
static ATTN_NET_JSON: &str = include_str!("../attn_value_net.json");

/// Deal a fresh game with `rng` — a faithful structural copy of `harvest_value::new_game` (and of
/// `engine.py::new_game`): shuffle each level's deck, deal the pyramid off the top, spiral-fill
/// the board from the 25-token bag, grant seat 1 the setup privilege (board pool left at 2).
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

/// A finished row: features + the mover seat's outcome + the sparse policy target, plus the two
/// aux indices the sanity readout compares.
struct Row {
    game_id: u64,
    feats: Vec<f32>,
    outcome: f32,
    entries: Vec<(u16, f32)>, // one per legal root move: (action_index, target_prob)
    argmax_root: usize,       // root move with the highest target prob (highest mean Q)
    greedy_root: usize,       // the search's greedy pick (visits, tie-break Q)
    collision: bool,          // two root moves mapped to the same action index (should never happen)
}

/// Build the softmax-over-Q policy target for a decision, plus the target's argmax root index.
///
/// One entry PER legal root move (so the trainer gets both the legal MASK and the soft target):
/// unvisited moves get prob 0; a single-move (forced) decision puts prob 1.0 on that move. Returns
/// `(entries, argmax_root_idx)`.
fn build_target(st: &State, stats: &RootStats, target_temp: f64) -> (Vec<(u16, f32)>, usize) {
    let n = stats.moves.len();
    let idxs: Vec<u16> = stats.moves.iter().map(|m| move_to_index(st, m) as u16).collect();

    if n == 1 {
        return (vec![(idxs[0], 1.0)], 0);
    }

    // Highest mean Q among visited moves = the target's argmax.
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
        // No move visited (unreachable for n>=2 at any real sim count): fall back to uniform.
        for x in w.iter_mut() {
            *x = 1.0 / n as f64;
        }
    }

    let entries: Vec<(u16, f32)> = (0..n).map(|i| (idxs[i], w[i] as f32)).collect();
    (entries, argmax)
}

/// Play one game to a terminal, recording every decision. Returns the labeled rows, or empty if
/// the game failed to terminate (pathological — discarded, never mislabeled as a truncation).
fn play_game(
    game_id: u64,
    sims: u64,
    temp_plies: usize,
    temp: f64,
    target_temp: f64,
    seed: u64,
    cap: usize,
    net: &AttnNet,
) -> Vec<Row> {
    let mut rng = Rng::new(seed);
    let mut st = new_game(&mut rng);
    // (mover_seat, feats, entries, argmax_root, greedy_root, collision) — outcome filled at the end.
    let mut pending: Vec<(usize, Vec<f32>, Vec<(u16, f32)>, usize, usize, bool)> = Vec::new();
    let mut ply = 0usize;

    loop {
        if st.is_over() {
            break;
        }
        if ply >= cap {
            return Vec::new(); // never terminated: discard rather than label a truncation
        }
        let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };
        let f = features(&st, mover);

        // Iteration-bounded search (clock-free -> reproducible, load-independent). Temperature
        // does NOT affect the SEARCH (it is a pick-time knob), so one search serves both the
        // recorded target and the played move.
        let opts = Opts { max_iters: Some(sims), time_limit: Some(f64::INFINITY), rollout_steps: Some(2), ..Default::default() };
        let stats = match root_search_with_leaf(&st, mover, "hard", &opts, Leaf::AttnVal(net), &mut rng) {
            Some(s) => s,
            None => break, // no legal move — unreachable (Pass fallback)
        };

        let (entries, argmax_root) = build_target(&st, &stats, target_temp);
        // Detect an index collision across root moves (would merge two moves' probs on the trainer
        // side). Impossible over `root_moves` (see actions.rs), but flagged rather than assumed.
        let collision = {
            let mut ks: Vec<u16> = entries.iter().map(|&(k, _)| k).collect();
            ks.sort_unstable();
            ks.windows(2).any(|w| w[0] == w[1])
        };
        // The greedy pick (temperature 0 draws nothing from the rng) — the sanity reference.
        let greedy_root = pick(&stats, 0.0, &mut rng);
        pending.push((mover, f, entries, argmax_root, greedy_root, collision));

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
        return Vec::new(); // ended without a winner — discard
    }
    let winner = st.winner;
    pending
        .into_iter()
        .map(|(seat, feats, entries, argmax_root, greedy_root, collision)| Row {
            game_id,
            feats,
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
    for &v in &row.feats {
        wf32(w, v);
    }
    wf32(w, row.outcome);
    wu16(w, row.entries.len() as u16);
    for &(idx, p) in &row.entries {
        wu16(w, idx);
        wf32(w, p);
    }
}

// ── Sanity accumulators ────────────────────────────────────────────────────────
#[derive(Default)]
struct Sanity {
    rows: u64,
    sum_n_legal: f64,
    // multi-move rows only (n_legal >= 2) — where entropy vs uniform is a real test.
    multi_rows: u64,
    sum_entropy: f64,
    sum_log_nlegal: f64,
    argmax_pick_match: u64, // over multi rows
    forced_rows: u64,       // n_legal == 1
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
}

fn parse_args() -> Args {
    let mut a = Args {
        games: 200,
        sims: 400,
        temp_plies: 12,
        temp: 0.5,
        target_temp: 0.1,
        seed: 0,
        out: "duel_pv.bin".to_string(),
        cap: 600,
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
            other => panic!("unknown arg: {}", other),
        }
        i += 1;
    }
    a
}

fn main() {
    let args = parse_args();
    assert!(args.target_temp > 0.0, "--target-temp must be > 0");

    let net = AttnNet::from_json_str(ATTN_NET_JSON).expect("load embedded attn_value_net.json");

    let file = std::fs::File::create(&args.out).expect("create --out file");
    let mut w = BufWriter::new(file);
    w.write_all(b"DUELPV01").unwrap();
    wu32(&mut w, N_FEATS as u32);
    wu32(&mut w, N_ACTIONS as u32);

    let mut san = Sanity::default();
    let mut terminated_games: u64 = 0;
    let mut discarded_games: u64 = 0;
    let clock = Clock::start();

    for g in 0..args.games {
        // Mix the base seed with the game index — an independent, reproducible stream per game
        // (splitmix constant; the first shuffle mixes it thoroughly). Matches `harvest_value`.
        let gseed = args.seed ^ (g.wrapping_mul(0x9E37_79B9_7F4A_7C15));
        let rows = play_game(g, args.sims, args.temp_plies, args.temp, args.target_temp, gseed, args.cap, &net);
        if rows.is_empty() {
            discarded_games += 1;
            continue;
        }
        terminated_games += 1;
        for row in &rows {
            san.add(row);
            write_row(&mut w, row);
        }
        w.flush().unwrap(); // flush per game
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

    // Sibling metadata: row count + args + layout, so the trainer reads the file without guessing.
    let meta = serde_json::json!({
        "magic": "DUELPV01",
        "n_feats": N_FEATS,
        "n_actions": N_ACTIONS,
        "rows": san.rows,
        "games_played": args.games,
        "games_terminated": terminated_games,
        "games_discarded": discarded_games,
        "args": {
            "games": args.games, "sims": args.sims, "temp_plies": args.temp_plies,
            "temp": args.temp, "target_temp": args.target_temp, "seed": args.seed, "cap": args.cap,
        },
        "row_layout": "u32 game_id | f32*n_feats feats | f32 outcome | u16 n_legal | n_legal*(u16 action_index, f32 prob), all little-endian",
    });
    let meta_path = format!("{}.meta.json", args.out);
    std::fs::write(&meta_path, serde_json::to_string_pretty(&meta).unwrap()).expect("write meta.json");

    eprintln!("── pv harvest complete ──");
    eprintln!("out                : {}", args.out);
    eprintln!("meta               : {}", meta_path);
    eprintln!("N_FEATS / N_ACTIONS: {} / {}", N_FEATS, N_ACTIONS);
    eprintln!("games (played)     : {}", args.games);
    eprintln!("games (terminated) : {}", terminated_games);
    eprintln!("games (discarded)  : {}", discarded_games);
    eprintln!("rows               : {}  ({} multi-move, {} forced)", san.rows, san.multi_rows, san.forced_rows);
    eprintln!("elapsed            : {:.2}s", elapsed);
    eprintln!(
        "throughput         : {:.2} games/s, {:.0} rows/s",
        args.games as f64 / elapsed,
        san.rows as f64 / elapsed
    );
    eprintln!("mean n_legal       : {:.2}", mean_n_legal);
    eprintln!(
        "target entropy     : {:.4} nats   (mean log(n_legal) = {:.4}; ratio {:.3} — PEAKED if << 1)",
        mean_entropy, mean_log_nlegal, peaked_ratio
    );
    eprintln!("argmax==greedy pick: {:.3}   (over {} multi-move rows)", argmax_pick_frac, san.multi_rows);
    if san.collisions > 0 {
        eprintln!("!! {} row(s) had an action-index COLLISION across root moves — investigate actions.rs", san.collisions);
    }

    // The one make-or-break signal: if the Q-softmax target is ~uniform, the whole prior premise
    // is unsupported. Say so loudly.
    if peaked_ratio >= 0.85 {
        eprintln!("!! WARNING: the policy target is NEAR-UNIFORM (entropy ~= log(n_legal)). The Q");
        eprintln!("!! signal is weak at this --target-temp/--sims; the policy-prior approach needs a");
        eprintln!("!! rethink (or a lower --target-temp). Do NOT train a prior on this data as-is.");
    } else {
        eprintln!("OK: the Q-softmax target is peaked (well below uniform) — a real policy signal.");
    }
}
