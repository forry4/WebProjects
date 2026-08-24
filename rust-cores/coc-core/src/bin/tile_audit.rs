//! tile_audit — does the champion systematically IGNORE the tiles/tempo strong
//! humans value? (user hypothesis, bot-vs-bot, no user games.)
//!   * monastery-6 ("once/turn spend 2 workers -> take a building tile") — the
//!     user has NEVER seen the bot buy it.
//!   * ships (advance the turn track -> first player) + the goods/ship
//!     monasteries (#3 #4 #5 #15 #25).
//!   * first-player-into-a-phase with silver+workers banked for the black depot.
//! Measures acquisition-given-AVAILABLE per monastery (each is a single tile, so
//! availability is crisp), ships/game, black-depot buys/game, and the first
//! player's banked silver/workers at each phase start. A near-zero acquisition
//! rate on an AVAILABLE, valuable tile = a self-play VALUE-HEAD blind spot (the
//! net never buys it -> never learns its value -> never buys it).
//!
//!   tile_audit <model.json> <games> <sims> <seed0>

use coc_core::engine::{self, State, A_BUY_BLACK0, PLAYING};
use coc_core::mcts::Search;
use coc_core::netio;
use coc_core::rng::Rng;
use coc_core::tiles::{monastery_effect, T_SHIP};
use coc_core::valuenet::PvEval;
use coc_core::vsearch;

/// Deployed-serving netval leaf (net prior + 30-step heuristic rollout + net
/// value at truncation, c_puct 1.0) — the config the live Expert uses, so this
/// faithfully represents the bot the user actually plays against.
fn choose_netval(net: &dyn PvEval, s: &State, sims: u32, seed: u64) -> usize {
    let legal = engine::legal_actions(s);
    if legal.len() == 1 {
        return legal[0];
    }
    let mut search = Search::new(s.clone(), vsearch::NETVAL_C_PUCT);
    let mut rng = Rng::new(seed ^ 0x9E77);
    let eval = |st: &State, actor: usize, lg: &[usize], r: &mut Rng| {
        vsearch::hybrid_netval_eval_steps(net, st, actor, lg, r, vsearch::NETVAL_ROLLOUT_STEPS)
    };
    for _ in 0..sims {
        search.sim(&mut rng, &eval);
    }
    let v = search.root_visits();
    *legal.iter().max_by_key(|&&a| v[a]).expect("nonempty legal")
}

const MON_DESC: [&str; 27] = [
    "",
    "1 no-1-per-type", "2 worker/mine/phase", "3 +2silver/sale", "4 worker/sale",
    "5 ship->adj-depot goods", "6 2wk->take building", "7 +1vp/livestock", "8 adjust die by 2",
    "9 free die-shift on building", "10 free shift ship/livestock", "11 free shift castle/mine/mon",
    "12 free shift on hex-take", "13 +1silver on 2-worker", "14 2-worker gives 4",
    "15 endgame 2vp/goods-type", "16 4vp/market", "17 4vp/watchtower", "18 4vp/carpenter",
    "19 4vp/church", "20 4vp/warehouse", "21 4vp/boarding", "22 4vp/bank", "23 4vp/townhall",
    "24 4vp/livestock-type", "25 endgame 1vp/goods-sold", "26 3vp/bonus-tile",
];

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 5 {
        eprintln!("usage: tile_audit <model.json> <games> <sims> <seed0> [pv|netval]");
        std::process::exit(2);
    }
    let net = netio::pv_from_json(&std::fs::read_to_string(&args[1]).expect("model"));
    let games: u64 = args[2].parse().unwrap();
    let sims: u32 = args[3].parse().unwrap();
    let seed0: u64 = args[4].parse().unwrap();
    let mode = args.get(5).map(|s| s.as_str()).unwrap_or("netval");
    let use_netval = mode == "netval";

    let mut mon_avail = [0u64; 27];
    let mut mon_acq = [0u64; 27];
    let mut ship_acq: u64 = 0;
    let mut ship_avail: u64 = 0;
    let mut black_buys: u64 = 0;
    let mut ps_silver: i64 = 0;
    let mut ps_workers: i64 = 0;
    let mut ps_count: u64 = 0;

    for g in 0..games {
        let pair = (g % 81) as u8;
        let mut s = State::new_game([pair / 9, pair % 9], seed0.wrapping_add(g.wrapping_mul(0x9E37_79B9)));
        let mut seen = [false; 27];
        let mut ship_seen = 0u64;
        let mut prev_phase = 255u8;
        let mut guard = 0u32;
        while !s.is_over() && guard < 4000 {
            guard += 1;
            if s.mode == PLAYING && s.phase != prev_phase {
                let fp = s.round_order[0] as usize;
                ps_silver += s.players[fp].silver as i64;
                ps_workers += s.players[fp].workers as i64;
                ps_count += 1;
                prev_phase = s.phase;
            }
            // depot availability scan
            for d in 0..6 {
                for slot in 0..2 {
                    let c = s.depot_hex[d][slot];
                    if (22..=47).contains(&c) {
                        seen[monastery_effect(c) as usize] = true;
                    } else if c == T_SHIP {
                        ship_seen += 1;
                    }
                }
            }
            for &c in s.black_depot.iter() {
                if (22..=47).contains(&c) {
                    seen[monastery_effect(c) as usize] = true;
                } else if c == T_SHIP {
                    ship_seen += 1;
                }
            }
            let legal = engine::legal_actions(&s);
            if legal.len() == 1 {
                engine::apply(&mut s, legal[0]);
                continue;
            }
            let sd = seed0 ^ (guard as u64) ^ (g << 20);
            let a = if use_netval {
                choose_netval(&net, &s, sims, sd)
            } else {
                vsearch::choose_action_pv(&net, &s, sims, sd)
            };
            if (A_BUY_BLACK0..A_BUY_BLACK0 + 4).contains(&a) {
                black_buys += 1;
            }
            engine::apply(&mut s, a);
        }
        for e in 1..=26 {
            if seen[e] {
                mon_avail[e] += 1;
            }
        }
        // ship_seen double-counts (same tile across turns); use presence as a coarse avail proxy
        if ship_seen > 0 {
            ship_avail += 1;
        }
        for seat in 0..2 {
            let mm = s.players[seat].mon_mask;
            for e in 1..=26 {
                if (mm >> (e - 1)) & 1 == 1 {
                    mon_acq[e] += 1;
                }
            }
            for sid in 0..37 {
                if s.players[seat].duchy[sid] == T_SHIP {
                    ship_acq += 1;
                }
            }
        }
    }

    println!("=== tile_audit: champion self-play, {} games @ {} sims, leaf={} ===",
        games, sims, if use_netval { "netval (DEPLOYED config)" } else { "pv" });
    println!("ships acquired/game (both seats): {:.2}   (games with a ship in a depot: {}/{})",
        ship_acq as f64 / games as f64, ship_avail, games);
    println!("black-depot buys/game: {:.2}", black_buys as f64 / games as f64);
    println!("phase-start FIRST player's banked resources (avg over {} phase-starts): silver {:.2}, workers {:.2}",
        ps_count, ps_silver as f64 / ps_count.max(1) as f64, ps_workers as f64 / ps_count.max(1) as f64);
    println!();
    println!("MONASTERY  avail  acq   acq-when-avail   effect");
    for e in 1..=26usize {
        let av = mon_avail[e];
        let aq = mon_acq[e];
        let rate = if av > 0 { aq as f64 / av as f64 } else { 0.0 };
        let flag = if av >= games / 4 && rate < 0.15 { "  <-- IGNORED" } else { "" };
        println!("  #{:<2}  {:>5}  {:>4}   {:.3}          {}{}", e, av, aq, rate, MON_DESC[e], flag);
    }
    let m6 = if mon_avail[6] > 0 { mon_acq[6] as f64 / mon_avail[6] as f64 } else { 0.0 };
    println!();
    println!("HEADLINE monastery-6: available {} games, acquired {} -> {:.3} acq-when-avail",
        mon_avail[6], mon_acq[6], m6);
}
