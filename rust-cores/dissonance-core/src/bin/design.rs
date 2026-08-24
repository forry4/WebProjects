//! Calibration data for the auction.
//!
//! For every deal it solves all 5 denominations for both players as declarer,
//! with the DEFENDER on lead to trick 1. Two numbers come out of this that the
//! bidding rules need and cannot be guessed:
//!   * par — what an average hand is worth, i.e. where the bid ladder starts
//!     being a real commitment;
//!   * the distribution of the best makeable contract, i.e. how much of the
//!     1-12 bid range is actually live.
//!
//! These are double-dummy values: both sides play with perfect information, so
//! they are an UPPER bound on what a real bidder can take. Treat them as the
//! ceiling of the live range, not the mean of it.
//!
//!   design [deals] [threads]

use dissonance::dd::Dd;
use dissonance::game::Game;
use dissonance::rng::Rng;
use dissonance::state::POOL;

const NDEN: usize = 5;

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let deals: usize = a.first().and_then(|s| s.parse().ok()).unwrap_or(200);
    let threads: usize = a
        .get(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4).saturating_sub(1).max(1));

    let per = deals.div_ceil(threads);
    let out: Vec<(Vec<i64>, Vec<i64>, Vec<u64>, Vec<u64>, i64, i64, usize)> =
        std::thread::scope(|sc| {
            let mut hs = Vec::new();
            for t in 0..threads {
                hs.push(sc.spawn(move || {
                    let mut dd = Dd::new(20);
                    // sum/count of declarer points per denomination
                    let mut den_sum = vec![0i64; NDEN];
                    let mut den_n = vec![0i64; NDEN];
                    // histogram of declarer points (offset by 7: range -7..12)
                    let mut hist = vec![0u64; 20];
                    // histogram of the best contract over all 5 denominations
                    let mut best_hist = vec![0u64; 20];
                    let (mut lead_sum, mut nolead_sum) = (0i64, 0i64);
                    let mut n = 0usize;
                    for i in 0..per {
                        let seed = (t * per + i) as u64 + 1;
                        if t * per + i >= deals {
                            break;
                        }
                        for declarer in 0..2usize {
                            let mut best = -7i64;
                            for d in 0..NDEN {
                                // The defender opens trick 1.
                                let g = Game::deal(&mut Rng::new(seed), d as u8, (1 - declarer) as u8);
                                dd.clear();
                                let diff = dd.solve(&g.s) as i64;
                                let p0 = (POOL as i64 + diff) / 2;
                                let pts = if declarer == 0 { p0 } else { POOL as i64 - p0 };
                                den_sum[d] += pts;
                                den_n[d] += 1;
                                hist[(pts + 7) as usize] += 1;
                                if pts > best {
                                    best = pts;
                                }
                                // Same solve, read from the leader's seat.
                                let lead_pts = if (1 - declarer) == 0 { p0 } else { POOL as i64 - p0 };
                                lead_sum += lead_pts;
                                nolead_sum += POOL as i64 - lead_pts;
                            }
                            best_hist[(best + 7) as usize] += 1;
                            n += 1;
                        }
                    }
                    (den_sum, den_n, hist, best_hist, lead_sum, nolead_sum, n)
                }));
            }
            hs.into_iter().map(|h| h.join().unwrap()).collect()
        });

    let mut den_sum = vec![0i64; NDEN];
    let mut den_n = vec![0i64; NDEN];
    let mut hist = vec![0u64; 20];
    let mut best_hist = vec![0u64; 20];
    let (mut lead, mut nolead, mut n) = (0i64, 0i64, 0usize);
    for r in out {
        for d in 0..NDEN {
            den_sum[d] += r.0[d];
            den_n[d] += r.1[d];
        }
        for i in 0..20 {
            hist[i] += r.2[i];
            best_hist[i] += r.3[i];
        }
        lead += r.4;
        nolead += r.5;
        n += r.6;
    }

    println!("hands solved     {}  ({} deals x 2 declarers x 5 denominations)", n, n / 2);
    println!("\n-- who wants to be on lead to trick 1 --");
    let denom = (n * NDEN) as f64;
    println!("  defender, on lead to trick 1   {:.4} pts", lead as f64 / denom);
    println!("  declarer, not on lead          {:.4} pts", nolead as f64 / denom);
    println!("  the opening lead is worth      {:+.4} pts", (lead - nolead) as f64 / denom);

    println!("\n-- declarer points by denomination --");
    for d in 0..NDEN {
        println!(
            "  {:<10} {:.4}",
            dissonance::cards::denom_name(d as u8),
            den_sum[d] as f64 / den_n[d] as f64
        );
    }

    let show = |name: &str, h: &Vec<u64>| {
        let tot: u64 = h.iter().sum();
        let mut acc = 0u64;
        println!("\n-- {} --", name);
        let mut mean = 0f64;
        for i in 0..20 {
            mean += (i as f64 - 7.0) * h[i] as f64;
        }
        println!("  mean {:.3}", mean / tot as f64);
        for i in (0..20).rev() {
            if h[i] == 0 {
                continue;
            }
            acc += h[i];
            println!(
                "  {:>3} pts  {:>6}  ({:5.2}%)   >= this: {:5.2}%",
                i as i64 - 7,
                h[i],
                100.0 * h[i] as f64 / tot as f64,
                100.0 * acc as f64 / tot as f64
            );
        }
    };
    show("declarer points, any denomination", &hist);
    show("BEST contract available (max over the 5 denominations)", &best_hist);
}
