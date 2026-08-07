//! Does searching the CONTRACT beat searching the trick points?
//!
//! The shipped Hard tier solves each sampled deal exactly and totals the value
//! of every root card. Until now that value was the trick-point difference --
//! the game's YARDSTICK, not its score. The score is a contract payoff, and
//! since 2026-08-07 it has a cliff in it: a declarer who wins no +2 trick all
//! round scores the Null consolation instead of being set, which a
//! point-maximising solver cannot see at any sample count.
//!
//! Paired, like `arena`: every deal is played TWICE with the seats swapped
//! (common random numbers), so deal luck cancels and two identical bots read
//! exactly 0.500. The score is the CONTRACT PAYOFF, because that is the
//! question -- a run scored on points would be asking the losing bot's own
//! question and would have nothing to say.
//!
//!   cmatch [--deals N] [--k K] [--level L] [--tt BITS] [--seed S]

use oddtrick::auction::NDEN;
use oddtrick::bots::PimcBot;
use oddtrick::dd::Contract;
use oddtrick::game::{play_round, Bot, Game};
use oddtrick::rng::Rng;

fn arg(name: &str, dflt: i64) -> i64 {
    let a: Vec<String> = std::env::args().collect();
    a.iter()
        .position(|x| x == name)
        .and_then(|i| a.get(i + 1))
        .and_then(|x| x.parse().ok())
        .unwrap_or(dflt)
}

/// The shipped classic-mode scoring, as `engine.payoff_terms` builds it.
fn contract_for(level: i32, declarer: usize) -> Contract {
    Contract {
        level,
        declarer,
        make_base: level * level,
        over: 0,
        set_base: (level - 1).max(0),
        short: 4,
        null: Some(12),
    }
}

fn main() {
    let deals = arg("--deals", 60) as usize;
    let k = arg("--k", 8) as usize;
    let level = arg("--level", 4) as i32;
    let bits = arg("--tt", 18) as u32;
    let seed0 = arg("--seed", 0xC0FFEE) as u64;
    // Both sides plain: the two orderings then play byte-identical games and the
    // edge must read EXACTLY 0.000. Anything else means the harness leaked state
    // and every number it printed is measuring something other than the change.
    let mirror = std::env::args().any(|a| a == "--mirror");

    // Contract-aware A vs point-searching B, each taking the declarer's seat
    // half the time -- the two sides of this rule are completely different
    // problems (the declarer decides whether to duck, the defender has to force
    // one +2 trick on them) and a run that only measured one would be a
    // measurement of half a change.
    let mut tot = [0f64; 2];
    let mut decl_pay = [0f64; 2];
    let mut def_pay = [0f64; 2];
    let mut nulls = [0usize; 2];
    for d in 0..deals {
        let trump = (d % NDEN) as u8;
        let declarer = d % 2;
        let c = contract_for(level, declarer);
        // Both orderings of the SAME deal: A declares in one, B in the other.
        for swap in 0..2 {
            let mut rng = Rng::new(seed0 ^ (d as u64) << 8);
            let mut g = Game::deal(&mut rng, trump, declarer as u8);
            // SEEDED BY SEAT, NEVER BY TIER. Swapping which bot sits where must
            // not also swap their random streams, or the pairing is not common
            // random numbers at all -- and the mirror below, the only thing that
            // can tell a real edge from a leaked one, would never read zero.
            // (`arena` documents the same rule.)
            let mut b0 = PimcBot::new(k, seed0 ^ 0xA5A5 ^ (d as u64) << 4, bits);
            let mut b1 = PimcBot::new(k, seed0 ^ 0x5A5A ^ (d as u64) << 4, bits);
            let (i_aware, i_plain) = if swap == 0 { (0usize, 1usize) } else { (1usize, 0usize) };
            if !mirror {
                if i_aware == 0 { b0.contract = Some(c); } else { b1.contract = Some(c); }
            }
            let pts = play_round(&mut g, &mut [&mut b0, &mut b1]);
            let scored = g.s.escored & (1 << declarer) != 0;
            let pay = c.payoff(pts[declarer] as i32, scored);
            // Signed for the declarer, so flip it for whoever is defending.
            for (who, seat) in [(0usize, i_aware), (1usize, i_plain)] {
                let v = if seat == declarer { pay } else { -pay };
                tot[who] += v as f64;
                if seat == declarer {
                    decl_pay[who] += v as f64;
                    if !scored {
                        nulls[who] += 1;
                    }
                } else {
                    def_pay[who] += v as f64;
                }
            }
        }
    }
    let n = (deals * 2) as f64;
    println!("deals {deals} x2 (paired)   k={k}   level={level}{}",
             if mirror { "   MIRROR (both plain)" } else { "" });
    println!("                     contract-aware      points");
    println!("mean payoff          {:12.3} {:11.3}", tot[0] / n, tot[1] / n);
    println!("  ...as declarer     {:12.3} {:11.3}", decl_pay[0] / (n / 2.0), decl_pay[1] / (n / 2.0));
    println!("  ...as defender     {:12.3} {:11.3}", def_pay[0] / (n / 2.0), def_pay[1] / (n / 2.0));
    println!("Nulls taken          {:12} {:11}", nulls[0], nulls[1]);
    println!("edge (aware - points) {:11.3} per round", (tot[0] - tot[1]) / n);
}
