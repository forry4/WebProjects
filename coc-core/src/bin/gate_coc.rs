//! Paired-CRN gate: player A vs player B over seat-swapped pairs, all in Rust.
//!
//!   gate_coc <A> <B> <pairs> <sims_a> <sims_b> <seed0> <threads> [batch]
//!   player spec: SCAFFOLD | path/to/model.json | path/to/model.json:argmax
//!
//! CRN is EXACT in CoC: the dice stream advances 5 rolls/round regardless of play
//! and the supply is drawn deterministically, so the same seed gives both seat
//! orders identical decks AND dice. Search seeds derive from (game seed, step)
//! only, so A-vs-A is a deterministic mirror = exactly 0.5000 (the sanity control).
//!
//! `batch` (default 8): NETVAL players' decisions across `batch` concurrent
//! games per thread are advanced one sim per round and their leaves evaluated
//! in one `forward_batch` pass (see batch.rs) — BIT-IDENTICAL games to the
//! sequential path (batch=1), just ~2x+ faster. Non-netval players resolve
//! their decisions inline.

use coc_core::batch::{step_netval, SearchTask};
use coc_core::engine::{self, State};
use coc_core::netio::pv_from_json;
use coc_core::valuenet::{PolicyValueNet, PvEval, QuantPolicyValueNet};
use coc_core::vsearch;
use std::sync::atomic::{AtomicU64, Ordering};

enum Player {
    Scaffold,
    Net(PolicyValueNet),
    NetArgmax(PolicyValueNet),
    Hybrid(Box<dyn PvEval>),         // net prior + rollout-heuristic value (MLP or attention)
    NetVal(Box<dyn PvEval>, usize, f64), // net prior + rollout(steps) + net-value; c_puct
                                         // (MLP or ATTENTION json - detected by content)
    NetVal8(QuantPolicyValueNet, usize, f64), // netval on the int8+VNNI quantized net
}

/// Load an MLP or ATTENTION net by json content ("emb_w" = attention).
fn load_any(path: &str) -> Box<dyn PvEval> {
    let js = std::fs::read_to_string(path).expect("model");
    if js.contains("\"emb_w\"") {
        Box::new(coc_core::attn::AttnNet::from_json_str(&js))
    } else {
        Box::new(pv_from_json(&js))
    }
}

impl Player {
    fn parse(spec: &str) -> Player {
        if spec == "SCAFFOLD" {
            return Player::Scaffold;
        }
        if let Some(path) = spec.strip_suffix(":argmax") {
            return Player::NetArgmax(pv_from_json(
                &std::fs::read_to_string(path).expect("model"),
            ));
        }
        if let Some(path) = spec.strip_suffix(":hybrid") {
            return Player::Hybrid(load_any(path));
        }
        // netval8: int8-quantized netval (same @STEPS@CPUCT params). Checked
        // BEFORE :netval — find(":netval") would also match ":netval8".
        if let Some(idx) = spec.find(":netval8") {
            let path = &spec[..idx];
            let params: Vec<&str> = spec[idx + ":netval8".len()..]
                .split('@')
                .filter(|s| !s.is_empty())
                .collect();
            let steps = params.first().and_then(|s| s.parse().ok()).unwrap_or(20);
            let cpuct = params.get(1).and_then(|s| s.parse().ok()).unwrap_or(vsearch::C_PUCT);
            let f32net = pv_from_json(&std::fs::read_to_string(path).expect("model"));
            return Player::NetVal8(QuantPolicyValueNet::from_f32(&f32net), steps, cpuct);
        }
        // netval, optionally parameterized: "path:netval", "path:netval@STEPS",
        // "path:netval@STEPS@CPUCT" (@-delimited so a Windows path's ':' is safe).
        if let Some(idx) = spec.find(":netval") {
            let path = &spec[..idx];
            let params: Vec<&str> = spec[idx + ":netval".len()..]
                .split('@')
                .filter(|s| !s.is_empty())
                .collect();
            let steps = params.first().and_then(|s| s.parse().ok()).unwrap_or(20);
            let cpuct = params.get(1).and_then(|s| s.parse().ok()).unwrap_or(vsearch::C_PUCT);
            return Player::NetVal(load_any(path), steps, cpuct);
        }
        Player::Net(pv_from_json(&std::fs::read_to_string(spec).expect("model")))
    }

    /// (net, rollout_steps, c_puct) when this player is batchable netval.
    fn netval(&self) -> Option<(&dyn PvEval, usize, f64)> {
        match self {
            Player::NetVal(net, steps, cpuct) => Some((net.as_ref(), *steps, *cpuct)),
            Player::NetVal8(net, steps, cpuct) => Some((net, *steps, *cpuct)),
            _ => None,
        }
    }

    fn choose(&self, s: &State, sims: u32, seed: u64) -> usize {
        match self {
            Player::Scaffold => vsearch::choose_action_heur(s, sims, seed),
            Player::Net(net) => vsearch::choose_action_pv(net, s, sims, seed),
            Player::NetArgmax(net) => vsearch::choose_action_pv_argmax(net, s, seed),
            Player::Hybrid(net) => {
                let legal = engine::legal_actions(s);
                if legal.len() == 1 {
                    return legal[0];
                }
                let mut search = coc_core::mcts::Search::new(s.clone(), vsearch::C_PUCT);
                let mut rng = coc_core::rng::Rng::new(seed ^ 0x9E77);
                let eval = |st: &State, actor: usize, lg: &[usize], r: &mut coc_core::rng::Rng| {
                    vsearch::hybrid_eval(net.as_ref(), st, actor, lg, r)
                };
                for _ in 0..sims {
                    search.sim(&mut rng, &eval);
                }
                let visits = search.root_visits();
                *legal.iter().max_by_key(|&&a| visits[a]).unwrap()
            }
            Player::NetVal(net, steps, cpuct) => {
                choose_netval(net.as_ref(), s, sims, seed, *steps, *cpuct)
            }
            Player::NetVal8(net, steps, cpuct) => {
                choose_netval(net, s, sims, seed, *steps, *cpuct)
            }
        }
    }
}

/// Sequential netval decision (shared by the f32 and int8 players).
fn choose_netval(
    net: &dyn PvEval,
    s: &State,
    sims: u32,
    seed: u64,
    steps: usize,
    cpuct: f64,
) -> usize {
    let legal = engine::legal_actions(s);
    if legal.len() == 1 {
        return legal[0];
    }
    let mut search = coc_core::mcts::Search::new(s.clone(), cpuct);
    let mut rng = coc_core::rng::Rng::new(seed ^ 0x9E77);
    let eval = |st: &State, actor: usize, lg: &[usize], r: &mut coc_core::rng::Rng| {
        vsearch::hybrid_netval_eval_steps(net, st, actor, lg, r, steps)
    };
    for _ in 0..sims {
        search.sim(&mut rng, &eval);
    }
    let visits = search.root_visits();
    *legal.iter().max_by_key(|&&a| visits[a]).unwrap()
}

fn play(a: &Player, b: &Player, seed: u64, a_seat: usize, sims_a: u32, sims_b: u32) -> (f64, i32) {
    let pair = (seed % 81) as u8;
    let mut s = State::new_game([pair / 9, pair % 9], seed);
    let mut step = 0u64;
    while !s.is_over() {
        let actor = s.actor() as usize;
        let sseed = seed.wrapping_mul(7919).wrapping_add(step);
        let act = if actor == a_seat {
            a.choose(&s, sims_a, sseed)
        } else {
            b.choose(&s, sims_b, sseed)
        };
        engine::apply(&mut s, act);
        step += 1;
    }
    let scores = s.final_scores();
    let margin = (scores[a_seat] - scores[1 - a_seat]) as i32;
    let win = if s.winner as usize == a_seat { 1.0 } else { 0.0 };
    (win, margin)
}

/// One concurrent game within a batched gate thread.
struct Slot {
    seed: u64,
    a_seat: usize,
    s: State,
    step: u64,
    /// (in-flight netval search, belongs-to-player-A)
    task: Option<(SearchTask, bool)>,
}

/// Batched thread runner: `batch` games in flight; netval decisions advance one
/// sim per round with their leaves batch-evaluated per net; everything else
/// (scaffold/argmax/forced moves, game bookkeeping) resolves inline. Game
/// trajectories are BIT-IDENTICAL to `play` — same per-game search seeds
/// (`seed*7919+step`), same per-search rng streams, same net numerics.
#[allow(clippy::too_many_arguments)]
fn run_batched(
    a: &Player,
    b: &Player,
    queue: &[(u64, usize)],
    sims_a: u32,
    sims_b: u32,
    seed0: u64,
    batch: usize,
    pairs: u64,
    wins: &AtomicU64,
    margins: &AtomicU64,
    done: &AtomicU64,
) {
    let mut qi = 0usize;
    let mut next_slot = |qi: &mut usize| -> Option<Slot> {
        let &(g, a_seat) = queue.get(*qi)?;
        *qi += 1;
        let seed = seed0 + g;
        let pair = (seed % 81) as u8;
        Some(Slot { seed, a_seat, s: State::new_game([pair / 9, pair % 9], seed), step: 0, task: None })
    };
    let mut slots: Vec<Option<Slot>> = (0..batch).map(|_| next_slot(&mut qi)).collect();
    loop {
        // advance every slot to its next netval decision (or through game end)
        for so in slots.iter_mut() {
            'adv: while let Some(sl) = so.as_mut() {
                if sl.s.is_over() {
                    let scores = sl.s.final_scores();
                    let m = (scores[sl.a_seat] - scores[1 - sl.a_seat]) as i32;
                    let w = if sl.s.winner as usize == sl.a_seat { 1.0 } else { 0.0 };
                    wins.fetch_add((w * 1000.0) as u64, Ordering::Relaxed);
                    margins.fetch_add((m + 10000) as u64, Ordering::Relaxed);
                    let d = done.fetch_add(1, Ordering::Relaxed) + 1;
                    if d % 50 == 0 {
                        eprintln!("{d}/{} games...", pairs * 2);
                    }
                    *so = next_slot(&mut qi);
                    continue 'adv;
                }
                if sl.task.is_some() {
                    break 'adv;
                }
                let actor = sl.s.actor() as usize;
                let is_a = actor == sl.a_seat;
                let (pl, sims) = if is_a { (a, sims_a) } else { (b, sims_b) };
                let sseed = sl.seed.wrapping_mul(7919).wrapping_add(sl.step);
                if let Some((_, steps, cpuct)) = pl.netval() {
                    let legal = engine::legal_actions(&sl.s);
                    if legal.len() == 1 {
                        engine::apply(&mut sl.s, legal[0]);
                        sl.step += 1;
                        continue 'adv;
                    }
                    sl.task = Some((SearchTask::new(sl.s.clone(), cpuct, sseed, sims, steps), is_a));
                    break 'adv;
                }
                let act = pl.choose(&sl.s, sims, sseed);
                engine::apply(&mut sl.s, act);
                sl.step += 1;
            }
        }
        if slots.iter().all(|s| s.is_none()) {
            break;
        }
        // one batched sim per round, grouped by which player's net evaluates
        for want_a in [true, false] {
            let net = match if want_a { a.netval() } else { b.netval() } {
                Some((net, _, _)) => net,
                None => continue,
            };
            let mut tasks: Vec<&mut SearchTask> = slots
                .iter_mut()
                .filter_map(|so| {
                    so.as_mut().and_then(|sl| match &mut sl.task {
                        Some((t, ia)) if *ia == want_a && !t.finished() => Some(t),
                        _ => None,
                    })
                })
                .collect();
            if !tasks.is_empty() {
                step_netval(net, &mut tasks);
            }
        }
        // apply finished searches (most-visited legal root action, as `choose`)
        for so in slots.iter_mut() {
            if let Some(sl) = so.as_mut() {
                if let Some((task, _)) = &sl.task {
                    if task.finished() {
                        let legal = engine::legal_actions(&sl.s);
                        let visits = task.search.root_visits();
                        let act = *legal.iter().max_by_key(|&&x| visits[x]).unwrap();
                        engine::apply(&mut sl.s, act);
                        sl.step += 1;
                        sl.task = None;
                    }
                }
            }
        }
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 8 {
        eprintln!("usage: gate_coc <A> <B> <pairs> <sims_a> <sims_b> <seed0> <threads> [batch]");
        std::process::exit(2);
    }
    let (spec_a, spec_b) = (args[1].clone(), args[2].clone());
    let pairs: u64 = args[3].parse().unwrap();
    let sims_a: u32 = args[4].parse().unwrap();
    let sims_b: u32 = args[5].parse().unwrap();
    let seed0: u64 = args[6].parse().unwrap();
    let threads: usize = args[7].parse().unwrap();
    let batch: usize = args.get(8).map(|s| s.parse().unwrap()).unwrap_or(8);

    let wins_milli = AtomicU64::new(0); // wins * 1000 to stay integer
    let margin_sum = AtomicU64::new(0); // offset +10000 per game
    let done = AtomicU64::new(0);
    std::thread::scope(|scope| {
        for t in 0..threads {
            let (spec_a, spec_b) = (spec_a.clone(), spec_b.clone());
            let (wins, margins, done) = (&wins_milli, &margin_sum, &done);
            scope.spawn(move || {
                let a = Player::parse(&spec_a);
                let b = Player::parse(&spec_b);
                let batchable = batch > 1 && (a.netval().is_some() || b.netval().is_some());
                if batchable {
                    let mut queue: Vec<(u64, usize)> = Vec::new();
                    let mut g = t as u64;
                    while g < pairs {
                        queue.push((g, 0));
                        queue.push((g, 1));
                        g += threads as u64;
                    }
                    run_batched(
                        &a, &b, &queue, sims_a, sims_b, seed0, batch, pairs, wins, margins, done,
                    );
                    return;
                }
                let mut g = t as u64;
                while g < pairs {
                    let seed = seed0 + g;
                    for a_seat in 0..2 {
                        let (w, m) = play(&a, &b, seed, a_seat, sims_a, sims_b);
                        wins.fetch_add((w * 1000.0) as u64, Ordering::Relaxed);
                        margins.fetch_add((m + 10000) as u64, Ordering::Relaxed);
                    }
                    let d = done.fetch_add(1, Ordering::Relaxed) + 1;
                    if d % 25 == 0 {
                        eprintln!("{d}/{pairs} pairs...");
                    }
                    g += threads as u64;
                }
            });
        }
    });
    let n = (pairs * 2) as f64;
    let wr = wins_milli.load(Ordering::Relaxed) as f64 / 1000.0 / n;
    let avg_margin = margin_sum.load(Ordering::Relaxed) as f64 / n - 10000.0;
    let se = (wr * (1.0 - wr) / n).sqrt();
    println!(
        "gate: A={spec_a} (sims {sims_a}) vs B={spec_b} (sims {sims_b}): {wr:.4} +-{:.3} (n={}), avg margin {avg_margin:+.1}",
        1.96 * se,
        n as u64
    );
}
