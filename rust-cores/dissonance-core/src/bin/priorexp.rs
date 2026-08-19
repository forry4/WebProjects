//! Does the shipped belief prior cost EXPLOITABILITY? (2026-08-19)
//!
//! Solinas, Rebstock & Buro's *Policy Based Inference in Trick-Taking Card
//! Games* (2019) reports that inference improves a determinized player's
//! results and that the gain "comes at the cost of increasing the player's
//! exploitability". This crate ships exactly such an inference -- `bid::BidPrior`
//! reweights the defender's sampled worlds by `exp(tilt * strength)` conditioned
//! on the level the declarer bought the contract at -- and shipped it on a gain
//! that was never established (+0.161 +- 0.623 at the Double, +0.617 +- 2.522 in
//! card play; both span zero). An unestablished benefit with an unmeasured cost
//! is worth pricing.
//!
//! THE MECHANISM, AND WHY AN ORACLE OPPONENT WOULD NOT MEASURE IT. The obvious
//! cheap proxy -- play the prior against a cheating opponent and see if it loses
//! more -- tests the wrong thing: an oracle does not model us at all, so it
//! cannot feed our belief model anything. PI is exploitable specifically by an
//! opponent who DEVIATES FROM THE MODEL the inference assumes. Our prior assumes
//! a declarer's level tracks their strength; a declarer who deliberately
//! underbids a strong hand therefore makes the correction wrong in a known
//! direction, and the defender resamples them WEAKER than they are on top of a
//! bias that was already in that direction.
//!
//! SO THIS IS A DIFFERENCE IN DIFFERENCES, which is what removes the confound.
//! Underbidding changes the contract, and a cheaper contract is worth a
//! different amount whatever anybody believes. That effect is identical with
//! the prior on and off, so it cancels:
//!
//!   cost = [deviate - honest | prior ON] - [deviate - honest | prior OFF]
//!
//! A negative number is the paper's finding reproducing here: the deviation
//! hurts the inferring defender more than it hurts the one that never inferred.
//!
//! Paired throughout, and BOTH ARMS SEE THE SAME DEALS AND THE SAME BOT SEEDS,
//! so the only thing varying inside each difference is the contract level and
//! inside the outer difference is the prior.
//!
//!   priorexp [--deals N] [--k K] [--under U] [--tt BITS]

use dissonance::bid::BidPrior;
use dissonance::bots::PimcBot;
use dissonance::dd::{shipped_classic_terms, Dd};
use dissonance::game::{Bot, Game};
use dissonance::rng::Rng;
use dissonance::state::POOL;

fn arg(name: &str, dflt: i64) -> i64 {
    let a: Vec<String> = std::env::args().collect();
    a.iter()
        .position(|x| x == name)
        .and_then(|i| a.get(i + 1))
        .and_then(|x| x.parse().ok())
        .unwrap_or(dflt)
}

/// The SHIPPED curve, from `bot._RANK_VALUE` sliced at `engine.NEXTRA = 2`, with
/// `trump_mult` 2.0 and the flat `_BID_TILT` of 0.35 over 24 candidate draws.
/// Mirrored rather than imported because the wire only ever carries the curve.
fn shipped_prior(declarer: usize, tilt: f64) -> BidPrior {
    let mut curve = [0f64; 10];
    for (i, v) in [0.0, 0.0, 0.0, 0.2, 0.5, 1.0, 1.6, 2.4].iter().enumerate() {
        curve[i] = *v;
    }
    BidPrior { curve, trump_mult: 2.0, tilt, declarer, tries: 24 }
}

/// One round at an imposed contract. Returns the payoff to the DEFENDER.
#[allow(clippy::too_many_arguments)]
fn play_at(
    seed: u64,
    den: u8,
    declarer: usize,
    level: i32,
    k: usize,
    bits: u32,
    tilt: Option<f64>,
) -> i32 {
    let mut g = Game::deal(&mut Rng::new(seed), den, declarer as u8);
    let c = shipped_classic_terms(level, declarer);
    let mut bots: Vec<PimcBot> = (0..2)
        .map(|q| {
            // Seeded per SEAT, never per identity -- the cmatch lesson.
            let mut b = PimcBot::new(k, 0xB1A5 ^ seed.wrapping_mul(31) ^ (q as u64) << 56, bits);
            b.contract = Some(c);
            // Only the DEFENDER infers: the prior is about the declarer's hand.
            if q != declarer {
                if let Some(t) = tilt {
                    b.prior = Some(shipped_prior(declarer, t));
                }
            }
            b
        })
        .collect();
    while !g.over() {
        let p = g.s.to_play() as usize;
        let v = g.view(p);
        let card = bots[p].pick(&v);
        g.apply(card);
    }
    let dpts = g.s.pts[declarer] as i32;
    let scored = g.s.escored & (1 << declarer) != 0;
    // Signed for the defender.
    -c.payoff(dpts, scored)
}

fn mean(v: &[f64]) -> f64 {
    v.iter().sum::<f64>() / v.len().max(1) as f64
}
fn sd(v: &[f64]) -> f64 {
    if v.len() < 2 {
        return 0.0;
    }
    let m = mean(v);
    (v.iter().map(|x| (x - m) * (x - m)).sum::<f64>() / (v.len() - 1) as f64).sqrt()
}

fn main() {
    let deals = arg("--deals", 120) as usize;
    let k = arg("--k", 8) as usize;
    let under = arg("--under", 2) as i32;
    let bits = arg("--tt", 20) as u32;
    let tilt = 0.35f64;

    let threads = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4)
        .saturating_sub(1)
        .max(1);
    let per = deals.div_ceil(threads);

    // Per deal: four numbers, (honest|deviate) x (prior on|off).
    let parts: Vec<Vec<[f64; 4]>> = std::thread::scope(|sc| {
        let mut hs = Vec::new();
        for t in 0..threads {
            hs.push(sc.spawn(move || {
                let mut root = Dd::new(bits);
                let mut out: Vec<[f64; 4]> = Vec::new();
                for i in 0..per {
                    let idx = t * per + i;
                    if idx >= deals {
                        break;
                    }
                    let seed = idx as u64 + 1;
                    let den = (seed % 5) as u8;
                    for declarer in 0..2usize {
                        let g0 = Game::deal(&mut Rng::new(seed), den, declarer as u8);
                        // What the declarer can actually make: the honest level.
                        let diff = root.solve(&g0.s) as i32;
                        let d0 = (POOL as i32 + diff) / 2;
                        let dpts = if declarer == 0 { d0 } else { POOL as i32 - d0 };
                        let honest = dpts.clamp(1, 12);
                        let deviate = (honest - under).clamp(1, 12);
                        if honest == deviate {
                            continue; // no deviation available; contributes nothing
                        }
                        out.push([
                            play_at(seed, den, declarer, honest, k, bits, Some(tilt)) as f64,
                            play_at(seed, den, declarer, deviate, k, bits, Some(tilt)) as f64,
                            play_at(seed, den, declarer, honest, k, bits, None) as f64,
                            play_at(seed, den, declarer, deviate, k, bits, None) as f64,
                        ]);
                    }
                }
                out
            }));
        }
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });

    let rows: Vec<[f64; 4]> = parts.into_iter().flatten().collect();
    let n = rows.len();
    if n < 2 {
        println!("no rows -- every deal's honest level was already at the floor");
        return;
    }
    let on: Vec<f64> = rows.iter().map(|r| r[1] - r[0]).collect();
    let off: Vec<f64> = rows.iter().map(|r| r[3] - r[2]).collect();
    let did: Vec<f64> = rows.iter().map(|r| (r[1] - r[0]) - (r[3] - r[2])).collect();

    println!(
        "priorexp: {} rows, pimc:{}, tilt {}, declarer underbids by {}",
        n, k, tilt, under
    );
    println!("  payoff is signed for the DEFENDER, who is the seat that infers");
    println!();
    println!(
        "  defender's gain from the deviation, prior ON   {:+.3} +/- {:.3}",
        mean(&on),
        sd(&on) / (n as f64).sqrt()
    );
    println!(
        "  defender's gain from the deviation, prior OFF  {:+.3} +/- {:.3}",
        mean(&off),
        sd(&off) / (n as f64).sqrt()
    );
    println!();
    println!(
        "  DIFFERENCE IN DIFFERENCES  {:+.3} +/- {:.3}",
        mean(&did),
        sd(&did) / (n as f64).sqrt()
    );
    println!("  (negative = the deviation punishes the inferring defender MORE,");
    println!("   i.e. the paper's exploitability cost reproducing here)");
}
