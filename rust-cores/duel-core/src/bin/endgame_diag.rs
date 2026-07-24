//! ENDGAME diagnostic (Part B; native-only, `--features bridge`).
//!
//! Direct, game-independent evidence of the exact endgame search's VALUE: gather real
//! near-endgame positions from HARD self-play, and at each one ask two questions the exact
//! search can answer but a sampled MCTS might get wrong —
//!
//!   1. FORCED WIN: does `endgame_search` prove a forced win (all lines lead to a terminal
//!      win within the depth budget)? If so, does a serving-budget MCTS ALSO pick a
//!      proven-winning move? Every position where the exact search proves a win but the MCTS
//!      picks a non-winning move is a forced win the deployed bot MISSES.
//!   2. FORCED LOSS (blocking): when the position is NOT a forced loss but SOME legal move IS
//!      (a line that hands the opponent a win), does the MCTS avoid it? A position where the
//!      MCTS walks into an avoidable loss is a block it MISSES.
//!
//! Both are measured against the SAME determinizations the exact search used, so the
//! comparison is apples-to-apples (is the move the MCTS chose actually winning / non-losing,
//! per exact play?). Also reports tractability: nodes + wall-time per endgame search, and how
//! often it completes vs hits the node cap.
//!
//!     cargo run --release --features bridge --bin endgame_diag -- \
//!         --games 100 --diag-sims 2000 --depth 16 --node-cap 2000000

use duel_core::cards::{SPIRAL_ORDER, TOKEN_BAG};
use duel_core::clock::Clock;
use duel_core::endgame::{endgame_decide, endgame_move_value, in_endgame};
use duel_core::engine::{State, EMPTY, N_CELLS};
use duel_core::mcts::{choose_move, root_moves, Opts, RngShuffler};
use duel_core::rng::Rng;

/// Fresh game (structural copy of engine.py::new_game — a legal, seed-varied opening; the
/// RULES that play it out are already parity-gated).
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

struct Args {
    games: u64,
    sims: u64,      // self-play move budget (game trajectory)
    diag_sims: u64, // serving-budget MCTS to compare against the exact search
    depth: usize,
    node_cap: u64,
    dets: usize,
    thresh: f64,
    seed: u64,
    temp_plies: usize,
    temp: f64,
    cap: usize,
    max_ms: f64, // per-search wall-clock ceiling (0 = unbounded)
}

fn parse_args() -> Args {
    let mut a = Args {
        games: 100,
        sims: 400,
        diag_sims: 2000,
        depth: 16,
        node_cap: 2_000_000,
        dets: 8,
        thresh: 0.7,
        seed: 0,
        temp_plies: 12,
        temp: 0.5,
        cap: 600,
        max_ms: 0.0,
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
            "--games" => a.games = next().parse().unwrap(),
            "--sims" => a.sims = next().parse().unwrap(),
            "--diag-sims" => a.diag_sims = next().parse().unwrap(),
            "--depth" => a.depth = next().parse().unwrap(),
            "--node-cap" => a.node_cap = next().parse().unwrap(),
            "--dets" => a.dets = next().parse().unwrap(),
            "--thresh" => a.thresh = next().parse().unwrap(),
            "--seed" => a.seed = next().parse().unwrap(),
            "--temp-plies" => a.temp_plies = next().parse().unwrap(),
            "--temp" => a.temp = next().parse().unwrap(),
            "--cap" => a.cap = next().parse().unwrap(),
            "--max-ms" => a.max_ms = next().parse().unwrap(),
            other => panic!("unknown arg: {}", other),
        }
        i += 1;
    }
    a
}

#[derive(Default)]
struct Tally {
    endgame_decisions: u64, // in_endgame fired AND >1 legal move
    conclusive: u64,        // endgame_decide returned Some (>=1 det completed)
    inconclusive: u64,      // all dets blew the cap / deadline
    // node/time distribution over conclusive searches
    nodes_sum: u64,
    nodes_max: u64,
    ms_sum: f64,
    ms_max: f64,
    // forced-win detection
    forced_win_positions: u64,  // exact search proves a forced win
    mcts_agreed_win: u64,       // MCTS played the SAME move (found the win)
    mcts_diff_win: u64,         // MCTS played a DIFFERENT winning move
    mcts_missed_win: u64,       // MCTS played a resolved NON-winning move (a real miss)
    mcts_win_unknown: u64,      // MCTS played a different move whose value couldn't resolve
    // forced-loss (blocking) detection
    nonloss_positions: u64,     // root can avoid a loss (exact best value > -1)
    mcts_walked_into_loss: u64, // MCTS played a move that is a forced loss (-1)
}

fn main() {
    let args = parse_args();
    let mut t = Tally::default();
    let clock = Clock::start();

    for g in 0..args.games {
        let gseed = args.seed ^ (g.wrapping_mul(0x9E37_79B9_7F4A_7C15));
        let mut rng = Rng::new(gseed);
        let mut st = new_game(&mut rng);
        let mut ply = 0usize;

        while !st.is_over() && ply < args.cap {
            let mover = if st.pending_pid != -1 { st.pending_pid as usize } else { st.turn };

            // Diagnostic probe: a real near-endgame DECISION (>1 legal move).
            if in_endgame(&st, args.thresh) {
                let moves = root_moves(&st, mover, true);
                if moves.len() > 1 {
                    t.endgame_decisions += 1;
                    // Exact search over the position (per-decision fresh seed).
                    let eseed = gseed ^ (ply as u64).wrapping_mul(0xD1B5_4A32_D192_ED03);
                    let deadline = if args.max_ms > 0.0 { Some(args.max_ms / 1000.0) } else { None };
                    let c = Clock::start();
                    // FAST root-alpha-beta decision (win-ordered), so it resolves forced-win
                    // positions even when a non-winning sibling would go deep.
                    let res = endgame_decide(
                        &st, mover, args.depth, args.node_cap, args.dets, eseed, deadline,
                    );
                    let ms = c.elapsed_secs() * 1000.0;
                    match res {
                        None => t.inconclusive += 1,
                        Some(d) => {
                            t.conclusive += 1;
                            t.nodes_sum += d.nodes;
                            t.nodes_max = t.nodes_max.max(d.nodes);
                            t.ms_sum += ms;
                            t.ms_max = t.ms_max.max(ms);

                            // The serving-budget MCTS pick (greedy hard), fresh rng so the game
                            // stream is untouched.
                            let mut drng = Rng::new(eseed ^ 0xABCD_1234);
                            let opts = Opts {
                                max_iters: Some(args.diag_sims),
                                time_limit: Some(f64::INFINITY),
                                ..Default::default()
                            };
                            let mmove = choose_move(&st, mover, "hard", &opts, &mut drng)
                                .expect("mcts move");
                            let same = mmove == d.best;
                            // The exact value of the MCTS move over the SAME determinizations —
                            // only needed when it DIFFERS from the exact best move.
                            let vmc = if same {
                                None
                            } else {
                                endgame_move_value(&st, mover, &mmove, args.depth, args.node_cap, args.dets, eseed)
                            };

                            // FORCED WIN: exact proves a win; did the MCTS pick a winning move?
                            if d.proven_win {
                                t.forced_win_positions += 1;
                                if same {
                                    t.mcts_agreed_win += 1;
                                } else {
                                    match vmc {
                                        Some(v) if v >= 1.0 - 1e-9 => t.mcts_diff_win += 1,
                                        Some(_) => t.mcts_missed_win += 1,
                                        None => t.mcts_win_unknown += 1,
                                    }
                                }
                            }
                            // AVOIDABLE LOSS: the exact best avoids a loss; did the MCTS walk into one?
                            if d.value > -1.0 + 1e-9 {
                                t.nonloss_positions += 1;
                                if !same {
                                    if let Some(v) = vmc {
                                        if v < -1.0 + 1e-9 {
                                            t.mcts_walked_into_loss += 1;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            // Advance the game with a normal HARD self-play move (opening temp for diversity).
            let temperature = if ply < args.temp_plies { Some(args.temp) } else { None };
            let opts = Opts {
                max_iters: Some(args.sims),
                time_limit: Some(f64::INFINITY),
                temperature,
                ..Default::default()
            };
            let mv = match choose_move(&st, mover, "hard", &opts, &mut rng) {
                Some(m) => m,
                None => break,
            };
            let mut sh = RngShuffler { rng: &mut rng };
            if st.apply_move(mover, &mv, &mut sh).is_err() {
                break;
            }
            ply += 1;
        }

        if (g + 1) % 10 == 0 {
            eprintln!(
                "  {}/{} games | endgame decisions {} (concl {} / inconcl {}) | missed wins {}/{}",
                g + 1, args.games, t.endgame_decisions, t.conclusive, t.inconclusive,
                t.mcts_missed_win, t.forced_win_positions
            );
        }
    }

    let secs = clock.elapsed_secs().max(1e-9);
    let concl = t.conclusive.max(1) as f64;
    println!("\n── ENDGAME DIAGNOSTIC ──");
    println!("games                    : {}", args.games);
    println!("config                   : depth {}, node_cap {}, dets {}, thresh {}, diag_sims {}, max_ms {}",
        args.depth, args.node_cap, args.dets, args.thresh, args.diag_sims, args.max_ms);
    println!("wall time                : {:.1}s", secs);
    println!("endgame decisions        : {}", t.endgame_decisions);
    println!("  conclusive             : {} ({:.1}%)", t.conclusive,
        100.0 * t.conclusive as f64 / t.endgame_decisions.max(1) as f64);
    println!("  inconclusive (cap hit) : {} ({:.1}%)", t.inconclusive,
        100.0 * t.inconclusive as f64 / t.endgame_decisions.max(1) as f64);
    println!("per conclusive search    : nodes avg {:.0} / max {} | ms avg {:.1} / max {:.1}",
        t.nodes_sum as f64 / concl, t.nodes_max, t.ms_sum / concl, t.ms_max);
    println!();
    let fw = t.forced_win_positions.max(1) as f64;
    println!("FORCED WINS proven        : {}", t.forced_win_positions);
    println!("  MCTS@{} agreed (found)  : {}  ({:.1}%)", args.diag_sims, t.mcts_agreed_win, 100.0 * t.mcts_agreed_win as f64 / fw);
    println!("  MCTS found a DIFF win    : {}  ({:.1}%)", t.mcts_diff_win, 100.0 * t.mcts_diff_win as f64 / fw);
    println!("  MCTS MISSED the win      : {}  ({:.1}%)  <-- the payoff", t.mcts_missed_win, 100.0 * t.mcts_missed_win as f64 / fw);
    println!("  MCTS diff, unresolved    : {}  ({:.1}%)", t.mcts_win_unknown, 100.0 * t.mcts_win_unknown as f64 / fw);
    println!();
    println!("NON-LOSS positions (best>-1): {}", t.nonloss_positions);
    println!("  MCTS WALKED into a loss  : {}  ({:.2}%)  <-- the payoff", t.mcts_walked_into_loss,
        100.0 * t.mcts_walked_into_loss as f64 / t.nonloss_positions.max(1) as f64);
    println!();
    println!("READ: a high 'MISSED'/'WALKED into' count = the exact endgame search fixes real");
    println!("blunders the sampled MCTS makes. ~0 = the MCTS already finds these; exact adds nothing.");
}
