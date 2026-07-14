//! firstplayer_audit — does the player who is FIRST-PLAYER in more phases win
//! more? (user hypothesis.) Self-play; per game count each seat's phase-starts
//! as start player (round_order[0]) and the winner. Reports P(win | first in
//! more phases), bucketed by the first-player-count margin.
//! CAVEAT (reported, not hidden): in self-play this is partly REVERSE causation
//! — a winning position also lets you control the track — so a correlation here
//! shows first-player advantage is real but does NOT prove the bot under-weights
//! it; the causal test is the biased arena.
//!
//!   firstplayer_audit <model.json> <games> <sims> <seed0>

use coc_core::engine::{self, State, PLAYING};
use coc_core::netio;
use coc_core::valuenet::PvEval;
use coc_core::vsearch;

fn pv_pick(net: &dyn PvEval, s: &State, sims: u32, seed: u64) -> usize {
    let legal = engine::legal_actions(s);
    if legal.len() == 1 {
        return legal[0];
    }
    let (visits, _) = vsearch::root_readout_pv(net, s, sims, vsearch::C_PUCT, seed);
    *legal.iter().max_by_key(|&&a| visits[a]).expect("nonempty")
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 5 {
        eprintln!("usage: firstplayer_audit <model.json> <games> <sims> <seed0>");
        std::process::exit(2);
    }
    let net = netio::pv_from_json(&std::fs::read_to_string(&args[1]).expect("model"));
    let games: u64 = args[2].parse().unwrap();
    let sims: u32 = args[3].parse().unwrap();
    let seed0: u64 = args[4].parse().unwrap();

    // margin bucket: |fp0-fp1| in {0,1,2,3,4,5} -> (games, more-first-player wins)
    let mut bucket_games = [0u64; 6];
    let mut bucket_wins = [0u64; 6];
    let mut decisive_games = 0u64; // fp0 != fp1
    let mut decisive_firstwins = 0u64;

    for g in 0..games {
        let pair = (g % 81) as u8;
        let mut s = State::new_game([pair / 9, pair % 9], seed0.wrapping_add(g.wrapping_mul(0x9E37_79B9)));
        let mut fp = [0u32; 2];
        let mut prev_phase = 255u8;
        let mut guard = 0u32;
        while !s.is_over() && guard < 4000 {
            guard += 1;
            if s.mode == PLAYING && s.phase != prev_phase {
                fp[s.round_order[0] as usize] += 1;
                prev_phase = s.phase;
            }
            let legal = engine::legal_actions(&s);
            if legal.len() == 1 {
                engine::apply(&mut s, legal[0]);
                continue;
            }
            let a = pv_pick(&net, &s, sims, seed0 ^ (guard as u64) ^ (g << 20));
            engine::apply(&mut s, a);
        }
        let margin = (fp[0] as i32 - fp[1] as i32).unsigned_abs() as usize;
        let b = margin.min(5);
        bucket_games[b] += 1;
        if s.winner < 0 {
            continue; // draw
        }
        let w = s.winner as usize;
        if fp[0] != fp[1] {
            decisive_games += 1;
            let more_first = if fp[0] > fp[1] { 0 } else { 1 };
            if w == more_first {
                decisive_firstwins += 1;
                bucket_wins[b] += 1;
            }
        }
    }

    println!("=== firstplayer_audit: {} games @ {} sims ===", games, sims);
    let rate = decisive_firstwins as f64 / decisive_games.max(1) as f64;
    let se = (rate * (1.0 - rate) / decisive_games.max(1) as f64).sqrt();
    println!(
        "P(win | first-player in MORE phases): {:.4} +-{:.3}  (over {} decisive games)",
        rate, 1.96 * se, decisive_games
    );
    println!(">0.50 => first-player-more correlates with winning (advantage real, but see reverse-causation caveat)");
    println!();
    println!("by first-player-count margin |fp0-fp1|:");
    for b in 0..6usize {
        if bucket_games[b] == 0 {
            continue;
        }
        // for margin 0, "wins" is meaningless (no more-first player); report n only
        if b == 0 {
            println!("  margin 0 (tied): {} games", bucket_games[b]);
        } else {
            println!(
                "  margin {}: {} games, more-first-player win rate {:.3}",
                b, bucket_games[b], bucket_wins[b] as f64 / bucket_games[b] as f64
            );
        }
    }
}
