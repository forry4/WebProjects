//! Bootstrap harvest: scaffold (heuristic rollout-leaf PUCT) self-play, recording
//! per searched decision: mover features + root visit distribution + searched root
//! value, then per-game outcome labels. The distill warm-start trains on this.
//!
//!   harvest_boot <out_prefix> <games> <sims> <temp_micro> <seed0> <threads> [model.json] [mode] [batch]
//!   mode netvalgpu: netval with the forward on tools/gpu_server.py (COC_GPU_ADDR)
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
//!   value (searched root value, mover perspective),
//!   m_region,m_color,m_livestock,m_sold,m_mines,m_silver,m_mon_end (mover's
//!     TERMINAL score decomposition — auxiliary training targets, KataGo-style;
//!     read from engine.rs's shadow VP ledger + final holdings, backfilled from
//!     the game's end onto every row like label/margin already are),
//!   o_region,o_color,o_livestock,o_sold,o_mines,o_silver,o_mon_end (same, opponent),
//!   policy ("a:n a:n ..." sparse)
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
    stager_w: Option<f64>,
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
            // league mode: the stager seat's decisions add the staged-asset
            // value bias (style-forcing; see vsearch::stager_bias)
            let eval = |st: &State, actor: usize, lg: &[usize], r: &mut Rng| match stager_w {
                Some(w) => vsearch::hybrid_netval_eval_stager(net, st, actor, lg, r, 20, w),
                None => vsearch::hybrid_netval_eval(net, st, actor, lg, r),
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

#[allow(clippy::too_many_arguments)]
fn run_thread(
    out: &str,
    t: usize,
    games: u64,
    sims: u32,
    temp_micro: usize,
    seed0: u64,
    mode: Mode,
    net: Option<&dyn PvEval>,
    log_enc: feats::Enc,
    stager: Option<f64>,
    stager_both: bool,
    pcr: Option<(u64, u32)>, // sequential-path PCR (mirrors the batched semantics)
    // OPPONENT-league mode ("vs@path", 2026-07-12): seat (g%2) plays with the
    // primary net and is the ONLY seat whose rows are recorded; the other seat
    // plays with this net. The Spender league lesson applied to CoC's observed
    // divergence (internal gates up, champion yardstick down): train on games
    // vs the ACTUAL TARGET, learning to beat it — not imitate it (opponent
    // rows are dropped; training on them would be a weak 300-sim distill).
    opp: Option<&dyn PvEval>,
    // shared work queue — see run_thread_batched; same bit-identical argument
    // now that temp sampling uses a per-game rng (below)
    queue: &std::sync::atomic::AtomicU64,
    total_games: u64,
) {
    use std::sync::atomic::Ordering;
    let path = format!("{out}.t{t}.csv");
    let mut w = BufWriter::new(File::create(&path).expect("create out"));
    let mut done_games = 0u64;
    loop {
        let g = queue.fetch_add(1, Ordering::Relaxed);
        if g >= total_games {
            break;
        }
        let seed = seed0 + g;
        let pair = (seed % 81) as u8;
        let mut s = State::new_game([pair / 9, pair % 9], seed);
        let mut rows: Vec<Row> = Vec::with_capacity(200);
        let mut searched = 0usize;
        // Seat (g % 2) is the TRAINING seat: the stager bias (league mode) and
        // the vs@-opponent's other seat both key off it, and alternating it
        // washes first-player advantage out of the outcome labels. stager_both
        // (the TEACHER-corpus mode) biases BOTH seats — mirror self-play of
        // the strongest agent, the r2 imitation-target pattern.
        let train_seat = (g % 2) as usize;
        // per-game rngs, same seeding as the batched path: trajectories are
        // deterministic regardless of which thread pulls the game (the old
        // thread-level temp rng was the one scheduling-dependent piece)
        let mut rng = Rng::new(seed ^ 0x7E3A_1100);
        let mut pcr_rng = Rng::new(seed ^ 0x9C41_0C41);
        while !s.is_over() {
            let legal = engine::legal_actions(&s);
            if legal.len() == 1 {
                engine::apply(&mut s, legal[0]);
                continue;
            }
            let actor = s.actor() as usize;
            let is_train = actor == train_seat || opp.is_none();
            let acting_net = if is_train { net } else { opp };
            let sw = stager.filter(|_| stager_both || actor == train_seat);
            // PCR: FULL cap -> policy+value row; CHEAP cap -> value-only row
            let full = pcr.is_none_or(|(pm, _)| pcr_rng.next_u64() % 1000 < pm);
            let cap = if full { sims } else { pcr.unwrap().1 };
            let (visits, value) = root_readout(
                &s,
                cap,
                seed.wrapping_mul(977) + searched as u64,
                mode,
                acting_net,
                sw,
            );
            let mut policy = String::new();
            if full {
                for &a in &legal {
                    if visits[a] > 0 {
                        if !policy.is_empty() {
                            policy.push(' ');
                        }
                        policy.push_str(&format!("{}:{}", a, visits[a]));
                    }
                }
            }
            // opening temperature applies to the TRAINING seat only — a vs@
            // opponent plays straight (greedy), matching the Spender league
            let a = if searched < temp_micro && is_train {
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
            if is_train {
                rows.push(Row { actor, feats: feats::encode(log_enc, &s, actor), policy, value });
            }
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
            line.push_str(&format!(",{label},{margin},{:.4}", r.value));
            push_aux(&mut line, &s, r.actor);
            line.push_str(&format!(",{}", r.policy));
            writeln!(w, "{line}").expect("write row");
        }
        done_games += 1;
        if done_games % 100 == 0 {
            eprintln!("[t{t}] {done_games} games (shared pool of {total_games})");
        }
    }
    let _ = games; // per-thread quota superseded by the shared queue
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
    // KataGo-style playout-cap randomization: a dedicated rng (so opening
    // temp-sampling draws are untouched) decides per decision whether this
    // search gets the FULL cap (policy row) or the CHEAP cap (value-only row).
    pcr_rng: Rng,
    task: Option<coc_core::batch::SearchTask>,
    task_full: bool,
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
    log_enc: feats::Enc,
    pcr: Option<(u64, u32)>, // (full-cap permille, cheap sims)
    // SHARED work queue (straggler-tail fix, 2026-07-12): threads pull the next
    // global game index instead of owning a static quota, so the small-batch
    // drain-tail happens ONCE at the very end of the whole harvest instead of
    // once per thread (~10-20% of harvest time under PCR). Game seeds derive
    // from the GLOBAL index and every per-game rng keys off the seed, so the
    // produced games are BIT-IDENTICAL to static assignment — only their
    // distribution across the .t<k>.csv files changes.
    queue: &std::sync::atomic::AtomicU64,
    total_games: u64,
) {
    use coc_core::batch::{step_netval, SearchTask};
    use std::sync::atomic::Ordering;
    let path = format!("{out}.t{t}.csv");
    let mut w = BufWriter::new(File::create(&path).expect("create out"));
    let mk_slot = |queue: &std::sync::atomic::AtomicU64| -> Option<GSlot> {
        let g = queue.fetch_add(1, Ordering::Relaxed);
        if g >= total_games {
            return None;
        }
        let seed = seed0 + g;
        let pair = (seed % 81) as u8;
        Some(GSlot {
            seed,
            s: State::new_game([pair / 9, pair % 9], seed),
            rows: Vec::with_capacity(200),
            searched: 0,
            temp_rng: Rng::new(seed ^ 0x7E3A_1100),
            pcr_rng: Rng::new(seed ^ 0x9C41_0C41),
            task: None,
            task_full: true,
        })
    };
    let mut slots: Vec<Option<GSlot>> = (0..batch).map(|_| mk_slot(queue)).collect();
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
                        line.push_str(&format!(",{label},{margin},{:.4}", r.value));
                        push_aux(&mut line, &sl.s, r.actor);
                        line.push_str(&format!(",{}", r.policy));
                        writeln!(w, "{line}").expect("write row");
                    }
                    done_games += 1;
                    if done_games % 100 == 0 {
                        eprintln!("[t{t}] {done_games} games (shared pool of {total_games})");
                    }
                    *so = mk_slot(queue);
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
                // Playout-cap randomization: FULL cap -> policy+value row;
                // CHEAP cap -> value-only row (empty policy field, which the
                // trainer's CE treats as a zero target = no policy gradient).
                let full = pcr.is_none_or(|(pm, _)| sl.pcr_rng.next_u64() % 1000 < pm);
                sl.task_full = full;
                let cap = if full { sims } else { pcr.unwrap().1 };
                sl.task = Some(SearchTask::new(
                    sl.s.clone(),
                    vsearch::C_PUCT,
                    sseed,
                    cap,
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
            if sl.task_full {
                for &a in &legal {
                    if visits[a] > 0 {
                        if !policy.is_empty() {
                            policy.push(' ');
                        }
                        policy.push_str(&format!("{}:{}", a, visits[a]));
                    }
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
            sl.rows.push(Row { actor, feats: feats::encode(log_enc, &sl.s, actor), policy, value });
            engine::apply(&mut sl.s, a);
            sl.searched += 1;
            sl.task = None;
        }
    }
    w.flush().expect("flush");
    eprintln!("[t{t}] done -> {path}");
}

/// Terminal-state score decomposition for one seat — auxiliary training
/// targets (KataGo-style: predict FINAL score components, not just win/loss).
/// Pure reads of engine.rs's shadow VP ledger (region_vp/color_vp/
/// livestock_vp — additive telemetry, never used by game logic) + existing
/// final-holdings fields. Caller backfills onto every row of the game, same
/// as label/margin already are.
fn aux_targets(s: &State, seat: usize) -> [f32; 7] {
    let p = &s.players[seat];
    [
        p.region_vp as f32,
        p.color_vp as f32,
        p.livestock_vp as f32,
        p.sold.iter().map(|&c| c as i32).sum::<i32>() as f32,
        p.mines as f32,
        p.silver as f32,
        s.endgame_monastery_vp(seat) as f32,
    ]
}

fn push_aux(line: &mut String, s: &State, actor: usize) {
    for &v in aux_targets(s, actor).iter().chain(aux_targets(s, 1 - actor).iter()) {
        line.push_str(&format!(",{}", trim_f(v)));
    }
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
    // MLP or ATTENTION json, detected by content ("emb_w" = attention). The
    // attention path exists for GPU self-play: the sidecar runs the torch twin,
    // the local net here only feeds the startup parity guard + logenc default
    // (an attention net's in_dim -> Enc::Tokens, so it logs token rows).
    let model_js: Option<String> =
        args.get(7).map(|p| std::fs::read_to_string(p).expect("model"));
    let is_attn = model_js.as_deref().is_some_and(|js| js.contains("\"emb_w\""));
    let net: Option<Box<dyn PvEval>> = model_js.as_deref().map(|js| {
        if is_attn {
            Box::new(coc_core::attn::AttnNet::from_json_str(js)) as Box<dyn PvEval>
        } else {
            Box::new(coc_core::netio::pv_from_json(js)) as Box<dyn PvEval>
        }
    });
    // "netval8" = netval search on the int8+VNNI quantized net (quantized at
    // load from the same f32 json — no new file format); everything downstream
    // treats it as Netval with a different net behind the PvEval seam.
    // "netvalgpu" = netval with the forward on the torch sidecar
    // (tools/gpu_server.py, addr from COC_GPU_ADDR, default 127.0.0.1:9911);
    // the model path arg is still required — it is forward-checked against the
    // server at startup so a stale server model can't poison a harvest.
    let mode_arg = args.get(8).map(|s| s.as_str());
    let quantize = mode_arg == Some("netval8");
    let gpu = mode_arg == Some("netvalgpu");
    let mode = match mode_arg {
        None | Some("scaffold") => Mode::Scaffold,
        Some("hybrid") => Mode::Hybrid,
        Some("pv") => Mode::Pv,
        Some("netval") | Some("netval8") | Some("netvalgpu") => Mode::Netval,
        Some(m) => panic!("bad mode {m}"),
    };
    if mode != Mode::Scaffold {
        assert!(net.is_some(), "hybrid/pv modes need a model path");
    }
    let batch: usize = args.get(9).map(|s| s.parse().unwrap()).unwrap_or(8);
    // arg 11: playout-cap randomization "PERMILLE@CHEAP_SIMS" (e.g. 250@200 =
    // 25% of decisions get the FULL <sims> cap and a policy row; the rest get
    // CHEAP_SIMS and a value-only row). Absent = off (every decision full).
    // KataGo-style: value data is game-limited, policy data needs deep search —
    // cheap moves buy ~2-3x more games/hour at the same compute. Batched
    // netval path only. (@-delimited: MSYS mangles ':' args.)
    // "stager@W" in any trailing slot = LEAGUE harvest: seat (game_idx % 2)
    // plays with the staged-asset value bias (vsearch::stager_bias, weight W) —
    // champion-vs-stager games inject asymmetric staged-endgame positions the
    // mirror self-play distribution never contains (the 2026-07-11 human-games
    // mining finding). "stagerboth@W" = TEACHER-corpus mode: BOTH seats biased
    // (mirror self-play of the strongest agent — the imitation-target pattern).
    // Sequential netval path only.
    let stager_both = args.iter().skip(9).any(|s| s.starts_with("stagerboth@"));
    let stager: Option<f64> = args.iter().skip(9).find_map(|s| {
        s.strip_prefix("stagerboth@")
            .or_else(|| s.strip_prefix("stager@"))
            .map(|w| w.parse().expect("stager w"))
    });
    if stager.is_some() {
        assert!(
            mode == Mode::Netval && batch == 1 && !gpu,
            "stager league needs the sequential CPU netval path (batch 1, no gpu)"
        );
    }
    // "vs@<model.json>" = OPPONENT league: the trailing net plays seat (1 - g%2)
    // and only the primary net's rows are recorded (see run_thread). MLP f32,
    // sequential CPU path only.
    let opp_net: Option<Box<dyn PvEval>> = args.iter().skip(9).find_map(|s| {
        s.strip_prefix("vs@").map(|p| {
            let js = std::fs::read_to_string(p).expect("vs@ opponent model");
            assert!(!js.contains("\"emb_w\""), "vs@ opponent must be an MLP json");
            Box::new(coc_core::netio::pv_from_json(&js)) as Box<dyn PvEval>
        })
    });
    if opp_net.is_some() {
        assert!(
            mode == Mode::Netval && batch == 1 && !gpu,
            "vs@ league needs the sequential CPU netval path (batch 1, no gpu)"
        );
    }
    // PCR spec "PERMILLE@CHEAP_SIMS": first trailing arg (slot 11+) with an
    // '@' that is not a stager spec. Works on BOTH the batched netval path and
    // (since 2026-07-12) the sequential path — same per-game rng seeding, so a
    // stager teacher corpus can use the r2 PCR recipe.
    let pcr: Option<(u64, u32)> = args
        .iter()
        .skip(11)
        .find(|s| s.contains('@') && s.chars().next().is_some_and(|c| c.is_ascii_digit()))
        .map(|s| {
            let (pm, cheap) = s.split_once('@').expect("pcr spec is PERMILLE@CHEAP_SIMS");
            (pm.parse().expect("pcr permille"), cheap.parse().expect("pcr cheap sims"))
        });
    if pcr.is_some() {
        assert!(mode == Mode::Netval, "pcr needs a netval-mode harvest");
    }
    // arg 10: which encoder to LOG in the rows (v1|v2). Defaults to the playing
    // net's encoder (else v1) — override for a distill harvest where the v1
    // champion PLAYS but the rows must carry the NEW encoder's features.
    let log_enc = match args.get(10).map(|s| s.as_str()) {
        Some("v1") => feats::Enc::V1,
        Some("v2") => feats::Enc::V2,
        Some("tok") => feats::Enc::Tokens, // P4b attention rows (tokfeats layout)
        None => net.as_deref().map_or(feats::Enc::V1, |n| feats::Enc::from_in_dim(n.in_dim())),
        Some(m) => panic!("bad logenc {m}"),
    };
    let per = games / threads as u64;
    // shared work queue: total = per*threads (kept for arithmetic-compat with
    // the old static split, so the same game-seed set is produced)
    let total_games = per * threads as u64;
    let queue = std::sync::atomic::AtomicU64::new(0);
    let qnet: Option<QuantPolicyValueNet> = if quantize {
        assert!(!is_attn, "netval8 is MLP-only");
        model_js.as_deref().map(|js| {
            QuantPolicyValueNet::from_f32(&coc_core::netio::pv_from_json(js))
        })
    } else {
        None
    };
    let gnet: Option<coc_core::gpueval::GpuEval> = if gpu {
        let addr =
            std::env::var("COC_GPU_ADDR").unwrap_or_else(|_| "127.0.0.1:9911".to_string());
        let g = coc_core::gpueval::GpuEval::connect(&addr).expect("gpu server connect");
        let n = net.as_ref().unwrap().as_ref();
        assert_eq!(g.in_dim, n.in_dim(), "gpu server model dim != local model dim");
        // same-model guard: one deterministic probe forward, CPU vs server
        let mut rng = coc_core::rng::Rng::new(0xC0C0_57A7);
        let mut raw: Vec<f32> =
            (0..g.in_dim).map(|_| (rng.next_u64() % 2000) as f32 / 1000.0 - 1.0).collect();
        if g.in_dim == coc_core::tokfeats::N_FEATS_TOK {
            // tokfeats contract: the mask block is 0/1 — the torch twin uses mask
            // VALUES as pooling weights while Rust treats them as booleans, so a
            // random-valued mask makes the two forwards legitimately diverge
            // (false-alarmed this guard once; the .check fixtures are binary).
            let m0 = coc_core::tokfeats::TOK_N * coc_core::tokfeats::TOK_F;
            for v in raw.iter_mut().skip(m0).take(coc_core::tokfeats::TOK_N) {
                *v = if *v > 0.0 { 1.0 } else { 0.0 };
            }
            raw[m0] = 1.0; // token 0 always live (never fully masked)
        }
        let (cv, cl) = n.forward_raw(&raw);
        let (gv, gl) = g.forward_raw(&raw);
        let md = cl.iter().zip(&gl).map(|(a, b)| (a - b).abs()).fold(0f32, f32::max);
        assert!(
            (cv - gv).abs() < 1e-3 && md < 1e-2,
            "gpu server output != local model (value {cv} vs {gv}, max logit diff {md}) — \
             is the server serving a different model?"
        );
        eprintln!(
            "[gpu] server verified: in_dim {}, value diff {:.2e}, max logit diff {:.2e}",
            g.in_dim,
            (cv - gv).abs(),
            md
        );
        Some(g)
    } else {
        None
    };
    let net_ref: Option<&dyn PvEval> = if gpu {
        gnet.as_ref().map(|g| g as &dyn PvEval)
    } else if quantize {
        qnet.as_ref().map(|q| q as &dyn PvEval)
    } else {
        net.as_ref().map(|n| n.as_ref())
    };
    let opp_ref: Option<&dyn PvEval> = opp_net.as_deref();
    std::thread::scope(|scope| {
        for t in 0..threads {
            let out = out.clone();
            let queue = &queue;
            scope.spawn(move || {
                if mode == Mode::Netval && batch > 1 {
                    run_thread_batched(
                        &out, t, per, sims, temp_micro, seed0, net_ref.unwrap(), batch, log_enc,
                        pcr, queue, total_games,
                    );
                } else {
                    run_thread(
                        &out, t, per, sims, temp_micro, seed0, mode, net_ref, log_enc, stager,
                        stager_both, pcr, opp_ref, queue, total_games,
                    );
                }
            });
        }
    });
    eprintln!("harvest complete: {total_games} games total");
}
