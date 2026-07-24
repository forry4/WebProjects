//! harvest_featscreen — CHEAP feature-ablation screen (Spender methodology).
//! Plays r2 self-play (netval leaf) and logs, per training-seat decision:
//!   game_seed, base_feats[N_FEATS], cand_feats[CAND], label(win=1/loss=0)
//! A Python probe then trains an MLP on base vs base+cand (GAME-split holdout)
//! and reports the held-out-AUC delta — does the candidate cross-reference
//! feature carry outcome signal the frozen 934-dim encoder LACKS?
//!
//! Candidates (cheap, STATIC — no lookahead, so serving-safe if adopted):
//!   P1 per-color region-completion progress (12): F only sees one region per
//!      space, never "all crimson regions" for the color bonus.
//!   P2 per-placement marginal VP (6): aggregate over reachable empty spaces of
//!      the exact VP a completing placement scores (AREA_SCORE+PHASE_BONUS) PLUS
//!      the color-completion-bonus trigger — a multi-space/color cross-reference
//!      a flat MLP can't express from the per-space block.
//!
//!   harvest_featscreen <model.json> <out_prefix> <games> <sims> <threads> <seed0>

use coc_core::boards_gen::{
    NEIGHBOR_MASK, N_REGIONS, N_SPACES, REGION_COLOR, REGION_MASK, REGION_OF, REGION_SIZE,
    SPACE_COLOR,
};
use coc_core::engine::{self, State};
use coc_core::feats;
use coc_core::mcts::Search;
use coc_core::netio;
use coc_core::rng::Rng;
use coc_core::tiles::{AREA_SCORE, PHASE_BONUS};
use coc_core::valuenet::PvEval;
use coc_core::vsearch;
use std::fs::File;
use std::io::{BufWriter, Write};
use std::sync::atomic::{AtomicU64, Ordering};

pub const CAND: usize = 18;

/// Per-color region-completion fraction for one seat's board (6).
fn color_completion(filled: u64, board: usize) -> [f32; 6] {
    let mut tot = [0u32; 6];
    let mut done = [0u32; 6];
    for r in 0..N_REGIONS[board] as usize {
        let c = REGION_COLOR[board][r] as usize;
        tot[c] += 1;
        let m = REGION_MASK[board][r];
        if filled & m == m {
            done[c] += 1;
        }
    }
    let mut out = [0f32; 6];
    for c in 0..6 {
        out[c] = if tot[c] > 0 { done[c] as f32 / tot[c] as f32 } else { 0.0 };
    }
    out
}

/// Round-3 DECISIVE screen: compare, on IDENTICAL data,
///   G1 = MY per-color completion (6)   — expected wash (block F encodes my board richly)
///   G2 = OPP per-color completion (6)   — the P3a flicker; the encoder gives opp only 14 dims
///   G3 = OPP THREAT (6)                 — sharper: imminent scoring + best placement the opp can grab
/// If G2/G3 >> G1 stably, the encoder's opponent-thinness is a real, exploitable gap.
fn candidate_feats(s: &State, seat: usize) -> Vec<f32> {
    let me = &s.players[seat];
    let opp = 1 - seat;
    let op = &s.players[opp];
    let b = s.boards[seat] as usize;
    let ob = s.boards[opp] as usize;
    let mut out = Vec::with_capacity(CAND);

    // G1 (6): MY per-color completion
    out.extend_from_slice(&color_completion(me.filled, b));
    // G2 (6): OPP per-color completion
    out.extend_from_slice(&color_completion(op.filled, ob));

    // G3 (6): OPPONENT threat — how close is the opponent to SCORING?
    let phase = s.phase as usize;
    let pbon = PHASE_BONUS[phase] as f32;
    let mut opp_oneaway = 0u32; // regions the opp completes with ONE more tile
    let mut opp_best_oneaway_vp = 0.0f32; // best such region's completion VP
    for r in 0..N_REGIONS[ob] as usize {
        let m = REGION_MASK[ob][r];
        let size = REGION_SIZE[ob][r] as u32;
        let f = (op.filled & m).count_ones();
        if f >= 1 && f + 1 == size {
            opp_oneaway += 1;
            let vp = AREA_SCORE[size as usize - 1] as f32 + pbon;
            if vp > opp_best_oneaway_vp {
                opp_best_oneaway_vp = vp;
            }
        }
    }
    // opp best placement VP available NOW (reachable empty that completes a region)
    let mut opp_best_place = 0.0f32;
    for sid in 0..N_SPACES {
        if op.filled >> sid & 1 == 1 || op.filled & NEIGHBOR_MASK[sid] == 0 {
            continue;
        }
        let r = REGION_OF[ob][sid] as usize;
        let size = REGION_SIZE[ob][r] as u32;
        let f = (op.filled & REGION_MASK[ob][r]).count_ones();
        if f >= 1 && f + 1 == size {
            let vp = AREA_SCORE[size as usize - 1] as f32 + pbon;
            if vp > opp_best_place {
                opp_best_place = vp;
            }
        }
        let _ = SPACE_COLOR[ob][sid];
    }
    let opp_empties = N_SPACES as u32 - op.filled.count_ones();
    // opp near a COLOR bonus: a color with exactly one region left AND bonus available
    let oc = color_completion(op.filled, ob);
    let mut opp_near_color = 0u32;
    for c in 0..6 {
        if oc[c] > 0.0 && oc[c] < 1.0 && s.bonus_left[c] > 0 {
            // count regions remaining for this color
            let mut rem = 0u32;
            for r in 0..N_REGIONS[ob] as usize {
                if REGION_COLOR[ob][r] as usize == c {
                    let m = REGION_MASK[ob][r];
                    if op.filled & m != m {
                        rem += 1;
                    }
                }
            }
            if rem == 1 {
                opp_near_color += 1;
            }
        }
    }
    out.push(opp_oneaway as f32 / 8.0);
    out.push((opp_best_oneaway_vp / 46.0).min(1.5));
    out.push((opp_best_place / 46.0).min(1.5));
    out.push(opp_empties as f32 / 37.0);
    out.push(opp_near_color as f32 / 6.0);
    out.push((op.silver.min(12) as f32 / 12.0 + op.workers.min(12) as f32 / 12.0) / 2.0);
    debug_assert_eq!(out.len(), CAND);
    out
}

struct Row {
    actor: usize,
    base: Vec<f32>,
    cand: Vec<f32>,
}

fn trim(f: f32) -> String {
    if f == 0.0 {
        "0".into()
    } else {
        format!("{:.5}", f)
    }
}

#[allow(clippy::too_many_arguments)]
fn run_thread(
    out: &str,
    t: usize,
    sims: u32,
    seed0: u64,
    net: &dyn PvEval,
    queue: &AtomicU64,
    total: u64,
) {
    let path = format!("{out}.t{t}.csv");
    let mut w = BufWriter::new(File::create(&path).expect("create"));
    loop {
        let g = queue.fetch_add(1, Ordering::Relaxed);
        if g >= total {
            break;
        }
        let seed = seed0 + g;
        let pair = (seed % 81) as u8;
        let mut s = State::new_game([pair / 9, pair % 9], seed);
        let mut trng = Rng::new(seed ^ 0x7E3A_1100);
        let mut rows: Vec<Row> = Vec::with_capacity(200);
        let mut ply = 0u32;
        let mut guard = 0u32;
        while !s.is_over() && guard < 4000 {
            guard += 1;
            let legal = engine::legal_actions(&s);
            if legal.len() == 1 {
                engine::apply(&mut s, legal[0]);
                continue;
            }
            let actor = s.actor() as usize;
            let sd = seed ^ (guard as u64).wrapping_mul(0x9E37_79B9);
            let mut search = Search::new(s.clone(), vsearch::NETVAL_C_PUCT);
            let mut srng = Rng::new(sd ^ 0x9E77);
            let eval = |st: &State, ac: usize, lg: &[usize], r: &mut Rng| {
                vsearch::hybrid_netval_eval_steps(net, st, ac, lg, r, vsearch::NETVAL_ROLLOUT_STEPS)
            };
            for _ in 0..sims {
                search.sim(&mut srng, &eval);
            }
            let visits = search.root_visits();
            // opening temperature (first ~30 micro-decisions) for position diversity
            let a = if ply < 30 {
                let total_v: i64 = legal.iter().map(|&a| visits[a] as i64).sum();
                let mut pick = (trng.next_u64() % total_v.max(1) as u64) as i64;
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
            rows.push(Row {
                actor,
                base: feats::features(&s, actor),
                cand: candidate_feats(&s, actor),
            });
            engine::apply(&mut s, a);
            ply += 1;
        }
        for r in &rows {
            let label = if s.winner as usize == r.actor { 1 } else { 0 };
            let mut line = String::with_capacity(feats::N_FEATS * 8 + 256);
            line.push_str(&format!("{seed}"));
            for &f in &r.base {
                line.push(',');
                line.push_str(&trim(f));
            }
            for &f in &r.cand {
                line.push(',');
                line.push_str(&trim(f));
            }
            line.push_str(&format!(",{label}"));
            writeln!(w, "{line}").expect("write");
        }
    }
    w.flush().expect("flush");
    eprintln!("[t{t}] done -> {path}");
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 7 {
        eprintln!("usage: harvest_featscreen <model.json> <out_prefix> <games> <sims> <threads> <seed0>");
        std::process::exit(2);
    }
    let net = netio::pv_from_json(&std::fs::read_to_string(&args[1]).expect("model"));
    let out = args[2].clone();
    let games: u64 = args[3].parse().unwrap();
    let sims: u32 = args[4].parse().unwrap();
    let threads: usize = args[5].parse().unwrap();
    let seed0: u64 = args[6].parse().unwrap();
    eprintln!(
        "featscreen: {games} games @ {sims} sims, {threads} threads, base={} cand={CAND}",
        feats::N_FEATS
    );
    let queue = AtomicU64::new(0);
    std::thread::scope(|sc| {
        for t in 0..threads {
            let netref: &dyn PvEval = &net;
            let outref = &out;
            let qref = &queue;
            sc.spawn(move || run_thread(outref, t, sims, seed0, netref, qref, games));
        }
    });
    eprintln!("featscreen done: {games} games, {CAND} candidate features appended after {} base cols (col0=seed, last col=label)", feats::N_FEATS);
}
