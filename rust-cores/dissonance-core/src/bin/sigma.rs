//! How far real play lands from the double-dummy value — and therefore how
//! much looser the real contract ladder is than the one every table in
//! CAMPAIGN.md and the Dissonance manual was built on.
//!
//! THE STANDING NOTE THIS ANSWERS. `pts` is what a declarer can guarantee
//! against a defence that sees every card. Real play is noisier, and noise
//! WIDENS the achieved-points distribution, which flattens P(make) per rung.
//! The manual quantified that by CONVOLVING the double-dummy distribution with
//! noise of an assumed scale sigma, and said in terms: "Sigma is measurable —
//! compare double-dummy `pts` against what the shipped PIMC search actually
//! achieves on the same deal and contract — and it has not been measured. Until
//! it is, read every 'the ladder is too coarse' statement here as an upper
//! bound." This measures it.
//!
//! AND IT DOES BETTER THAN SIGMA, which is worth saying because sigma was only
//! ever a modelling device. Once both seats have played the deal out, the real
//! ladder can be READ OFF rather than convolved: P(make level N) under actual
//! play, beside P(make level N) under the double-dummy value, on the same
//! deals. The convolution assumed the noise was additive, symmetric and
//! independent of the position; the measurement assumes none of that.
//!
//! SIGMA IS NOT A PURE WIDENING, and the sign of the mean is the reason to
//! report it separately. Two errors run in opposite directions: an imperfect
//! DECLARER falls short of what it could guarantee, and an imperfect DEFENCE
//! lets it past. Both seats here run the shipped `pimc:8`, so the mean delta is
//! the net of those and is a fact about the tier, not about the game.
//!
//!   sigma [deals] [k]
//!
//! Every deal is played in all five denominations, so a row is (deal, denom)
//! and the shuffle is amortised over five contracts the way the par table's is.

use dissonance::bots::*;
use dissonance::dd::Dd;
use dissonance::game::{Bot, Game};
use dissonance::rng::Rng;
use dissonance::state::POOL;

const DENOMS_PLAYED: [u8; 5] = [0, 1, 2, 3, dissonance::cards::NOTRUMP];
/// Levels a classic auction can name. 12 is the ceiling (all six even tricks).
const MAXLEVEL: i32 = 12;

struct Acc {
    dd: Vec<i32>,
    got: Vec<i32>,
}

impl Acc {
    fn new() -> Acc {
        Acc { dd: Vec::new(), got: Vec::new() }
    }
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
    let a: Vec<String> = std::env::args().skip(1).collect();
    let deals: usize = a.first().and_then(|s| s.parse().ok()).unwrap_or(200);
    let k: usize = a.get(1).and_then(|s| s.parse().ok()).unwrap_or(8);

    let threads = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4)
        .saturating_sub(1)
        .max(1);
    let per = deals.div_ceil(threads);

    let parts: Vec<Acc> = std::thread::scope(|sc| {
        let mut hs = Vec::new();
        for t in 0..threads {
            hs.push(sc.spawn(move || {
                let mut acc = Acc::new();
                let mut root = Dd::new(20);
                for i in 0..per {
                    let idx = t * per + i;
                    if idx >= deals {
                        break;
                    }
                    let seed = idx as u64 + 1;
                    for &den in DENOMS_PLAYED.iter() {
                        // SAME DEAL, five denominations: the shuffle is the
                        // expensive shared thing and the contract is what
                        // varies, exactly as the par table does it.
                        let g0 = Game::deal(&mut Rng::new(seed), den, 0);

                        // What seat 0 can guarantee, seeing everything.
                        let diff = root.solve(&g0.s) as i32;
                        let dd0 = (POOL as i32 + diff) / 2;

                        // What it actually gets, both seats on the shipped tier.
                        // Bot seeds are per SEAT, never per identity — the
                        // cmatch lesson: seeding by identity swaps the RNG
                        // streams along with the roles and manufactures an edge.
                        let mut g = g0.clone();
                        let mut bots: Vec<PimcBot> = (0..2)
                            .map(|q| {
                                PimcBot::new(
                                    k,
                                    0x5164 ^ seed.wrapping_mul(31) ^ (den as u64) << 40 ^ (q as u64) << 56,
                                    20,
                                )
                            })
                            .collect();
                        while !g.over() {
                            let p = g.s.to_play() as usize;
                            let v = g.view(p);
                            let c = bots[p].pick(&v);
                            g.apply(c);
                        }
                        acc.dd.push(dd0);
                        acc.got.push(g.s.pts[0] as i32);
                    }
                }
                acc
            }));
        }
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });

    let mut acc = Acc::new();
    for p in &parts {
        acc.dd.extend_from_slice(&p.dd);
        acc.got.extend_from_slice(&p.got);
    }
    let n = acc.dd.len();

    let ddf: Vec<f64> = acc.dd.iter().map(|&x| x as f64).collect();
    let gotf: Vec<f64> = acc.got.iter().map(|&x| x as f64).collect();
    let delta: Vec<f64> = acc
        .dd
        .iter()
        .zip(&acc.got)
        .map(|(&d, &g)| (g - d) as f64)
        .collect();

    println!("sigma: {} deals x {} denominations = {} rows, both seats pimc:{}", deals, DENOMS_PLAYED.len(), n, k);
    println!();
    println!("POINTS DISTRIBUTION (seat 0, pool = {})", POOL);
    println!("  double-dummy   mean {:+.3}   sd {:.3}", mean(&ddf), sd(&ddf));
    println!("  real play      mean {:+.3}   sd {:.3}", mean(&gotf), sd(&gotf));
    println!();
    println!("SIGMA -- real play minus what the deal was worth double-dummy");
    let se = sd(&delta) / (n as f64).sqrt();
    println!("  mean  {:+.3} +/- {:.3}   (negative = the shipped tier leaves points on the table)", mean(&delta), se);
    println!("  sd    {:.3}   <- THIS IS SIGMA", sd(&delta));
    let exact = delta.iter().filter(|&&d| d == 0.0).count();
    println!("  landed exactly on the double-dummy value: {:.1}%", 100.0 * exact as f64 / n as f64);
    println!();

    println!("THE LADDER, MEASURED RATHER THAN CONVOLVED");
    println!("  level   P(make) dd    P(make) real    diff");
    let pmake = |v: &Vec<i32>, lvl: i32| v.iter().filter(|&&x| x >= lvl).count() as f64 / n as f64;
    // THE LIVE RANGE ONLY. Averaging the drop over all twelve rungs dilutes it
    // with the dead top of the ladder and reads about half the real slope --
    // the manual's 17.6 is the slope where contracts actually settle, so the
    // comparison has to be taken there or it is not a comparison.
    let mut live: Vec<i32> = Vec::new();
    for lvl in 1..=MAXLEVEL {
        let p_dd = pmake(&acc.dd, lvl);
        let p_re = pmake(&acc.got, lvl);
        println!("  {:>5}   {:>10.3}    {:>12.3}    {:+.3}", lvl, p_dd, p_re, p_re - p_dd);
        if p_dd >= 0.02 {
            live.push(lvl);
        }
    }
    println!();
    if live.len() >= 2 {
        let (lo, hi) = (live[0], live[live.len() - 1]);
        let span = (hi - lo) as f64;
        let rung_dd = (pmake(&acc.dd, lo) - pmake(&acc.dd, hi)) / span * 100.0;
        let rung_re = (pmake(&acc.got, lo) - pmake(&acc.got, hi)) / span * 100.0;
        println!(
            "  per-rung cost in P(make), over the live range (levels {}-{}):",
            lo, hi
        );
        println!("    double-dummy {:.1} pts     real play {:.1} pts     {:.1}% looser", rung_dd, rung_re, 100.0 * (1.0 - rung_re / rung_dd));
        println!("  (the manual's convolution predicted 17.6 at sigma 0, 16.0 at sigma 1, 13.1 at sigma 2)");
    }
}
