//! Bootstrap harvest: scaffold (heuristic rollout-leaf PUCT) self-play, recording
//! per searched decision: mover features + root visit distribution + searched root
//! value, then per-game outcome labels. The distill warm-start trains on this.
//!
//!   harvest_boot <out_prefix> <games> <sims> <temp_micro> <seed0> <threads> [model.json] [mode] [batch]
//!   mode: scaffold (default, heuristic rollout leaf) | hybrid (net prior +
//!   rollout value — the P4 ratchet's self-play config) | pv (pure net leaf)
//!   e.g. harvest_boot C:/Users/Forrest/coc_run/boot 5000 1500 20 0 10
//!        harvest_boot C:/Users/Forrest/coc_run/it1 3000 600 20 5000 10 best.json hybrid
//!
//! `batch` (default 8, netval mode only): each thread drives `batch` games in
//! lockstep and batch-evaluates their leaves (see batch.rs) — search semantics
//! unchanged (same per-decision search seeds/rng streams); the ONE behavior
//! delta vs the sequential path is that opening temperature-sampling uses a
//! PER-GAME rng (seeded from the game seed) instead of a thread-shared one, so
//! trajectories are deterministic regardless of interleaving.
//!
//! Writes <out_prefix>.t<k>.csv per thread. Columns (no header):
//!   game_id, f0..f933, label (1/0 mover won), margin (mover score diff),
//!   value (searched root value, mover perspective), policy ("a:n a:n ..." sparse)
//! Forced (single-legal) decisions are applied without search and NOT recorded.
//! Board pairs cycle uniformly over the 81 combinations; openings are
//! visit-temperature-sampled for the first <temp_micro> searched decisions.

use std::fs::File;
use std::io::{BufWriter, Write};

use coc_core::engine::{self, State};
use coc_core::feats;
use coc_core::mcts::Search;
use coc_core::rng::Rng;
use coc_core::valuenet::{PolicyValueNet, PvEval, QuantPolicyValueNet};
use coc_core::vsearch;

#[derive(Clone, Copy, PartialEq)]
enum Mode {
    Scaffold,
    Hybrid,
    Pv,
    Netval, // net prior + rollout + net-value-at-truncation (the shipped Expert leaf)
}

struct Row {
    actor: usize,
    feats: Vec<f32>,
    policy: String,
    value: f64,
}

fn root_readout(
    s: &State,
    sims: u32,
    seed: u64,
    mode: Mode,
    net: Option<&dyn PvEval>,
) -> (Vec<i32>, f64) {
    match mode {
        Mode::Scaffold => vsearch::root_readout_heur(s, sims, vsearch::C_PUCT, seed),
        Mode::Pv => vsearch::root_readout_pv(net.unwrap(), s, sims, vsearch::C_PUCT, seed),
        Mode::Hybrid => {
            let net = net.unwrap();
            let mut search = Search::new(s.clone(), vsearch::C_PUCT);
            let mut rng = Rng::new(seed ^ 0x9E77);
            let eval = |st: &State, actor: usize, lg: &[usize], r: &mut Rng| {
                vsearch::hybrid_eval(net, st, actor, lg, r)
            };
            for _ in 0..sims {
                search.sim(&mut rng, &eval);
            }
            let n: i64 = search.root_visits().iter().map(|&x| x as i64).sum();
            let w: f64 = search.root_wins().iter().sum();
            (search.root_visits().to_vec(), if n > 0 { w / n as f64 } else { 0.0 })
        }
        Mode::Netval => {
            let net = net.unwrap();
            let mut search = Search::new(s.clone(), vsearch::C_PUCT);
            let mut rng = Rng::new(seed ^ 0x9E77);
            let eval = |st: &State, actor: usize, lg: &[usize], r: &mut Rng| {
                vsearch::hybrid_netval_eval(net, st, actor, lg, r)
            };
            for _ in 0..sims {
                search.sim(&mut rng, &eval);
            }
            let n: i64 = search.root_visits().iter().map(|&x| x as i64).sum();
            let w: f64 = search.root_wins().iter().sum();
            (search.root_visits().to_vec(), if n > 0 { w / n as f64 } else { 0.0 })
        }
    }
}

fn run_thread(
    out: &str,
    t: usize,
    games: u64,
    sims: u32,
    temp_micro: usize,
    seed0: u64,
    mode: Mode,
    net: Option<&dyn PvEval>,
) {
    let path = format!("{out}.t{t}.csv");
    let mut w = BufWriter::new(File::create(&path).expect("create out"));
    let mut rng = Rng::new(seed0 ^ 0xB007_0000 ^ (t as u64) << 32);
    for g in 0..games {
        let seed = seed0 + (t as u64) * games + g;
        let pair = (seed % 81) as u8;
        let mut s = State::new_game([pair / 9, pair % 9], seed);
        let mut rows: Vec<Row> = Vec::with_capacity(200);
        let mut searched = 0usize;
        while !s.is_over() {
            let legal = engine::legal_actions(&s);
            if legal.len() == 1 {
                engine::apply(&mut s, legal[0]);
                continue;
            }
            let actor = s.actor() as usize;
            let (visits, value) =
                root_readout(&s, sims, seed.wrapping_mul(977) + searched as u64, mode, net);
            let mut policy = String::new();
            for &a in &legal {
                if visits[a] > 0 {
                    if !policy.is_empty() {
                        policy.push(' ');
                    }
                    policy.push_str(&format!("{}:{}", a, visits[a]));
                }
            }
            let a = if searched < temp_micro {
                // temperature 1: sample proportional to visits
                let total: i64 = legal.iter().map(|&a| visits[a] as i64).sum();
                let mut pick = (rng.next_u64() % total.max(1) as u64) as i64;
                let mut chosen = legal[0];
                for &la in &legal {
                    pick -= visits[la] as i64;
                    if pick < 0 {
                        chosen = la;
                        break;
                    }
                }
                chosen
            } else {
                *legal.iter().max_by_key(|&&a| visits[a]).unwrap()
            };
            rows.push(Row { actor, feats: feats::features(&s, actor), policy, value });
            engine::apply(&mut s, a);
            searched += 1;
        }
        let scores = s.final_scores();
        for r in &rows {
            let label = if s.winner as usize == r.actor { 1 } else { 0 };
            let margin = scores[r.actor] - scores[1 - r.actor];
            let mut line = String::with_capacity(feats::N_FEATS * 8 + 64);
            line.push_str(&format!("{}", seed));
            for &f in &r.feats {
                line.push_str(&format!(",{}", trim_f(f)));
            }
            line.push_str(&format!(",{label},{margin},{:.4},{}", r.value, r.policy));
            writeln!(w, "{line}").expect("write row");
        }
        if (g + 1) % 100 == 0 {
            eprintln!("[t{t}] {}/{games} games", g + 1);
        }
    }
    w.flush().expect("flush");
    eprintln!("[t{t}] done -> {path}");
}

/// One in-flight game in the batched netval harvest.
struct GSlot {
    seed: u64,
    s: State,
    rows: Vec<Row>,
    searched: usize,
    temp_rng: Rng,
    task: Option<coc_core::batch::SearchTask>,
}

/// Batched netval harvest thread: `batch` games in lockstep, one sim per game
/// per round, leaves evaluated together (batch.rs). Row format and search
/// seeding identical to `run_thread`; opening temp-sampling uses a per-game rng.
#[allow(clippy::too_many_arguments)]
fn run_thread_batched(
    out: &str,
    t: usize,
    games: u64,
    sims: u32,
    temp_micro: usize,
    seed0: u64,
    net: &dyn PvEval,
    batch: usize,
) {
    use coc_core::batch::{step_netval, SearchTask};
    let path = format!("{out}.t{t}.csv");
    let mut w = BufWriter::new(File::create(&path).expect("create out"));
    let mut next_g = 0u64;
    let mut mk_slot = |next_g: &mut u64| -> Option<GSlot> {
        if *next_g >= games {
            return None;
        }
        let g = *next_g;
        *next_g += 1;
        let seed = seed0 + (t as u64) * games + g;
        let pair = (seed % 81) as u8;
        Some(GSlot {
            seed,
            s: State::new_game([pair / 9, pair % 9], seed),
            rows: Vec::with_capacity(200),
            searched: 0,
            temp_rng: Rng::new(seed ^ 0x7E3A_1100),
            task: None,
        })
    };
    let mut slots: Vec<Option<GSlot>> = (0..batch).map(|_| mk_slot(&mut next_g)).collect();
    let mut done_games = 0u64;
    loop {
        for so in slots.iter_mut() {
            'adv: while let Some(sl) = so.as_mut() {
                if sl.s.is_over() {
                    let scores = sl.s.final_scores();
                    for r in &sl.rows {
                        let label = if sl.s.winner as usize == r.actor { 1 } else { 0 };
                        let margin = scores[r.actor] - scores[1 - r.actor];
                        let mut line = String::with_capacity(feats::N_FEATS * 8 + 64);
                        line.push_str(&format!("{}", sl.seed));
                        for &f in &r.feats {
                            line.push_str(&format!(",{}", trim_f(f)));
                        }
                        line.push_str(&format!(",{label},{margin},{:.4},{}", r.value, r.policy));
                        writeln!(w, "{line}").expect("write row");
                    }
                    done_games += 1;
                    if done_games % 100 == 0 {
                        eprintln!("[t{t}] {done_games}/{games} games");
                    }
                    *so = mk_slot(&mut next_g);
                    continue 'adv;
                }
                if sl.task.is_some() {
                    break 'adv;
                }
                let legal = engine::legal_actions(&sl.s);
                if legal.len() == 1 {
                    engine::apply(&mut sl.s, legal[0]);
                    continue 'adv;
                }
                let sseed = sl.seed.wrapping_mul(977) + sl.searched as u64;
                sl.task = Some(SearchTask::new(
                    sl.s.clone(),
                    vsearch::C_PUCT,
                    sseed,
                    sims,
                    vsearch::ROLLOUT_MICRO_STEPS,
                ));
                break 'adv;
            }
        }
        if slots.iter().all(|s| s.is_none()) {
            break;
        }
        let mut tasks: Vec<&mut coc_core::batch::SearchTask> = slots
            .iter_mut()
            .filter_map(|so| so.as_mut().and_then(|sl| sl.task.as_mut().filter(|t| !t.finished())))
            .collect();
        if !tasks.is_empty() {
            step_netval(net, &mut tasks);
        }
        for so in slots.iter_mut() {
            let Some(sl) = so.as_mut() else { continue };
            let Some(task) = &sl.task else { continue };
            if !task.finished() {
                continue;
            }
            let legal = engine::legal_actions(&sl.s);
            let visits = task.search.root_visits();
            let value = task.root_value();
            let actor = sl.s.actor() as usize;
            let mut policy = String::new();
            for &a in &legal {
                if visits[a] > 0 {
                    if !policy.is_empty() {
                        policy.push(' ');
                    }
                    policy.push_str(&format!("{}:{}", a, visits[a]));
                }
            }
            let a = if sl.searched < temp_micro {
                let total: i64 = legal.iter().map(|&a| visits[a] as i64).sum();
                let mut pick = (sl.temp_rng.next_u64() % total.max(1) as u64) as i64;
                let mut chosen = legal[0];
                for &la in &legal {
                    pick -= visits[la] as i64;
                    if pick < 0 {
                        chosen = la;
                        break;
                    }
                }
                chosen
            } else {
                *legal.iter().max_by_key(|&&a| visits[a]).unwrap()
            };
            sl.rows.push(Row { actor, feats: feats::features(&sl.s, actor), policy, value });
            engine::apply(&mut sl.s, a);
            sl.searched += 1;
            sl.task = None;
        }
    }
    w.flush().expect("flush");
    eprintln!("[t{t}] done -> {path}");
}

/// Compact float formatting (5 significant digits, strips zero noise).
fn trim_f(f: f32) -> String {
    if f == 0.0 {
        return "0".to_string();
    }
    if f == 1.0 {
        return "1".to_string();
    }
    format!("{:.5}", f)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 7 {
        eprintln!("usage: harvest_boot <out_prefix> <games> <sims> <temp_micro> <seed0> <threads>");
        std::process::exit(2);
    }
    let out = args[1].clone();
    let games: u64 = args[2].parse().unwrap();
    let sims: u32 = args[3].parse().unwrap();
    let temp_micro: usize = args[4].parse().unwrap();
    let seed0: u64 = args[5].parse().unwrap();
    let threads: usize = args[6].parse().unwrap();
    let net: Option<PolicyValueNet> = args.get(7).map(|p| {
        coc_core::netio::pv_from_json(&std::fs::read_to_string(p).expect("model"))
    });
    // "netval8" = netval search on the int8+VNNI quantized net (quantized at
    // load from the same f32 json — no new file format); everything downstream
    // treats it as Netval with a different net behind the PvEval seam.
    let mode_arg = args.get(8).map(|s| s.as_str());
    let quantize = mode_arg == Some("netval8");
    let mode = match mode_arg {
        None | Some("scaffold") => Mode::Scaffold,
        Some("hybrid") => Mode::Hybrid,
        Some("pv") => Mode::Pv,
        Some("netval") | Some("netval8") => Mode::Netval,
        Some(m) => panic!("bad mode {m}"),
    };
    if mode != Mode::Scaffold {
        assert!(net.is_some(), "hybrid/pv modes need a model path");
    }
    let batch: usize = args.get(9).map(|s| s.parse().unwrap()).unwrap_or(8);
    let per = games / threads as u64;
    let qnet: Option<QuantPolicyValueNet> =
        if quantize { net.as_ref().map(QuantPolicyValueNet::from_f32) } else { None };
    let net_ref: Option<&dyn PvEval> = if quantize {
        qnet.as_ref().map(|q| q as &dyn PvEval)
    } else {
        net.as_ref().map(|n| n as &dyn PvEval)
    };
    std::thread::scope(|scope| {
        for t in 0..threads {
            let out = out.clone();
            scope.spawn(move || {
                if mode == Mode::Netval && batch > 1 {
                    run_thread_batched(
                        &out, t, per, sims, temp_micro, seed0, net_ref.unwrap(), batch,
                    );
                } else {
                    run_thread(&out, t, per, sims, temp_micro, seed0, mode, net_ref);
                }
            });
        }
    });
    eprintln!("harvest complete: {} games total", per * threads as u64);
}
