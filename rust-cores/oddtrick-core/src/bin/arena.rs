//! Paired head-to-head arena.
//!
//! Every deal is played TWICE with the seats swapped (common random numbers),
//! so deal luck cancels. Two identical deterministic bots must therefore score
//! exactly 2.500 — that mirror reading is the harness's own correctness check,
//! and a run that does not produce it is measuring something other than skill.
//!
//!   arena <botA> <botB> [--games N] [--threads T] [--trump s|r] [--tt BITS]
//!   bot := random | greedy | pimc:K | oracle

use oddtrick::bots::*;

use oddtrick::game::{play_round, Bot, Game};
use oddtrick::rng::Rng;
use oddtrick::state::POOL;

/// `pimc:K` is textbook PIMC. `pimc:K:PARTICLES:TEMP:AGG` turns on
/// opponent-aware resampling; AGG is mean | vote | qNN (e.g. q25).
/// TEMP `inf` weights every world equally, which reproduces `pimc:K` exactly.
fn make(spec: &str, seed: u64, bits: u32) -> Box<dyn Bot> {
    if let Some(rest) = spec.strip_prefix("pimc:") {
        let f: Vec<&str> = rest.split(':').collect();
        let k: usize = f[0].parse().expect("pimc:K");
        if f.len() == 1 {
            return Box::new(PimcBot::new(k, seed, bits));
        }
        let particles: usize = f[1].parse().expect("particles");
        let temp: f32 = if f.len() > 2 {
            if f[2] == "inf" { f32::INFINITY } else { f[2].parse().expect("temp") }
        } else {
            f32::INFINITY
        };
        let agg = match f.get(3).copied().unwrap_or("mean") {
            "mean" => Agg::Mean,
            "vote" => Agg::Vote,
            q if q.starts_with('q') => Agg::Quantile(q[1..].parse::<f32>().expect("qNN") / 100.0),
            other => panic!("unknown aggregator {other:?}"),
        };
        let lambda: f32 = f.get(4).map(|x| x.parse().expect("lambda")).unwrap_or(0.0);
        let playouts: usize = f.get(5).map(|x| x.parse().expect("playouts")).unwrap_or(0);
        let ptemp: f32 = f.get(6).map(|x| x.parse().expect("ptemp")).unwrap_or(0.5);
        return Box::new(PimcBot::full(
            k, particles, temp, agg, lambda, playouts, ptemp, seed, bits,
        ));
    }
    match spec {
        "random" => Box::new(RandomBot {
            rng: Rng::new(seed),
        }),
        "greedy" => Box::new(GreedyBot),
        "oracle" => Box::new(OracleBot::new(bits)),
        _ => panic!("unknown bot {spec:?}"),
    }
}

fn flag(args: &[String], name: &str) -> Option<String> {
    args.iter()
        .position(|a| a == name)
        .and_then(|i| args.get(i + 1))
        .cloned()
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let spec_a = args.first().cloned().unwrap_or("greedy".into());
    let spec_b = args.get(1).cloned().unwrap_or("random".into());
    let games: u64 = flag(&args, "--games").and_then(|s| s.parse().ok()).unwrap_or(500);
    let threads: usize = flag(&args, "--threads")
        .and_then(|s| s.parse().ok())
        .unwrap_or((std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4)).saturating_sub(1).max(1));
    let bits: u32 = flag(&args, "--tt").and_then(|s| s.parse().ok()).unwrap_or(20);
    let trump_spec = flag(&args, "--trump").unwrap_or("r".into());
    let base: u64 = flag(&args, "--seed").and_then(|s| s.parse().ok()).unwrap_or(1);

    let per = games.div_ceil(threads as u64);
    let t0 = std::time::Instant::now();

    let results: Vec<(f64, u64, u64, u64)> = std::thread::scope(|sc| {
        let mut hs = Vec::new();
        for t in 0..threads {
            let (sa, sb, ts) = (spec_a.clone(), spec_b.clone(), trump_spec.clone());
            hs.push(sc.spawn(move || {
                let lo = base + t as u64 * per;
                let hi = lo + per;
                let mut a = make(&sa, 0x5EED ^ (t as u64), bits);
                let mut b = make(&sb, 0xB0B ^ (t as u64), bits);
                let (mut sum, mut w, mut l, mut d) = (0f64, 0u64, 0u64, 0u64);
                for seed in lo..hi {
                    let mut dr = Rng::new(seed);
                    let trump = match ts.as_str() {
                        "r" => (dr.next_u64() % 5) as u8,
                        s => s.parse().unwrap_or(4),
                    };
                    // Same deal, both seatings.
                    for swap in 0..2 {
                        let mut g = Game::deal(&mut Rng::new(seed), trump, 0);
                        let pts = if swap == 0 {
                            play_round(&mut g, &mut [&mut *a, &mut *b])
                        } else {
                            let p = play_round(&mut g, &mut [&mut *b, &mut *a]);
                            [p[1], p[0]]
                        };
                        sum += pts[0] as f64;
                        match pts[0].cmp(&(POOL - pts[0])) {
                            std::cmp::Ordering::Greater => w += 1,
                            std::cmp::Ordering::Less => l += 1,
                            std::cmp::Ordering::Equal => d += 1,
                        }
                    }
                }
                (sum, w, l, d)
            }));
        }
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });

    let (mut sum, mut w, mut l, mut d) = (0f64, 0u64, 0u64, 0u64);
    for r in results {
        sum += r.0;
        w += r.1;
        l += r.2;
        d += r.3;
    }
    let n = (w + l + d) as f64;
    let mean = sum / n;
    // Per-round scores are bounded, so a normal-approx SE on the mean is fine
    // for deciding whether a gap is real.
    println!("{} vs {}", spec_a, spec_b);
    println!("rounds        {} ({} deals x2 seatings)", n as u64, n as u64 / 2);
    println!("mean pts (A)  {:.4}   [par = {:.1}]", mean, POOL as f64 / 2.0);
    println!("edge          {:+.4} pts/round", mean - POOL as f64 / 2.0);
    println!("W-L-D         {}-{}-{}  ({:.1}% wins)", w, l, d, 100.0 * w as f64 / n);
    println!("elapsed       {:.1}s", t0.elapsed().as_secs_f64());
}
