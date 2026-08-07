//! Decomposes the oracle gap into per-decision regret.
//!
//! At every decision it solves the TRUE world to get the exact value of each
//! legal move, then asks what the bot actually played. The difference is that
//! decision's regret, in points. Summed over a round it must reconstruct the
//! arena's oracle gap — which makes this the map of where the strength is
//! being lost, rather than a guess.
//!
//! It also reports how often the sampled worlds AGREE on the best move. That
//! number decides whether "which worlds we solve" is a live lever at all: if
//! the worlds already agree, no amount of re-weighting or re-aggregating
//! double-dummy values can change the choice.
//!
//!   diag [deals] [k]

use dissonance::bots::*;
use dissonance::dd::Dd;
use dissonance::game::{Bot, Game};
use dissonance::rng::Rng;

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let deals: usize = a.first().and_then(|s| s.parse().ok()).unwrap_or(40);
    let k: usize = a.get(1).and_then(|s| s.parse().ok()).unwrap_or(8);

    let threads = std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4)
        .saturating_sub(1)
        .max(1);
    let per = deals.div_ceil(threads);

    let res: Vec<([f64; 13], [u64; 13], u64, u64, u64, u64, u64)> = std::thread::scope(|sc| {
        let mut hs = Vec::new();
        for t in 0..threads {
            hs.push(sc.spawn(move || {
                let mut oracle = Dd::new(20);
                let mut probe = Dd::new(20);
                let mut bots: Vec<PimcBot> = (0..2)
                    .map(|i| PimcBot::new(k, 0xD1A6 ^ (t as u64) ^ (i as u64) << 8, 20))
                    .collect();
                let mut rs = Rng::new(0x51DE ^ t as u64);
                let mut buf = Vec::new();

                let mut regret = [0f64; 13];
                let mut count = [0u64; 13];
                let (mut dec, mut zero, mut agree, mut worlds_pick_truth, mut multi) =
                    (0u64, 0u64, 0u64, 0u64, 0u64);

                for i in 0..per {
                    let idx = t * per + i;
                    if idx >= deals {
                        break;
                    }
                    let seed = idx as u64 + 1;
                    let mut g = Game::deal(&mut Rng::new(seed), (seed % 5) as u8, 0);
                    while !g.over() {
                        let p = g.s.to_play() as usize;
                        let v = g.view(p);
                        let mut m = [0u8; 16];
                        let n = v.legal(&mut m);
                        if n == 1 {
                            let c = bots[p].pick(&v);
                            g.apply(c);
                            continue;
                        }
                        multi += 1;

                        // Exact value of every move in the real world.
                        let mut truth = [0i16; 16];
                        oracle.solve_root(&g.s, &m[..n], &mut truth);
                        let sign = if p == 0 { 1i16 } else { -1i16 };
                        let best = (0..n).map(|i| sign * truth[i]).max().unwrap();

                        // Do the sampled worlds even disagree about the answer?
                        let mut first: Option<usize> = None;
                        let mut same = true;
                        let mut vals = [0i16; 16];
                        let mut votes = [0u32; 16];
                        for _ in 0..k {
                            let w = v.determinize(&mut rs, &mut buf);
                            probe.solve_root(&w, &m[..n], &mut vals);
                            let mut bi = 0;
                            for j in 1..n {
                                if sign * vals[j] > sign * vals[bi] {
                                    bi = j;
                                }
                            }
                            votes[bi] += 1;
                            match first {
                                None => first = Some(bi),
                                Some(f) => {
                                    if f != bi {
                                        same = false;
                                    }
                                }
                            }
                        }
                        if same {
                            agree += 1;
                        }
                        let mut mj = 0;
                        for j in 1..n {
                            if votes[j] > votes[mj] {
                                mj = j;
                            }
                        }
                        if sign * truth[mj] == best {
                            worlds_pick_truth += 1;
                        }

                        let c = bots[p].pick(&v);
                        let ci = m[..n].iter().position(|&x| x == c).unwrap();
                        // Differential units are 2 points per unit.
                        let r = (best - sign * truth[ci]) as f64 / 2.0;
                        let tr = g.s.trick as usize;
                        regret[tr] += r;
                        count[tr] += 1;
                        dec += 1;
                        if r == 0.0 {
                            zero += 1;
                        }
                        g.apply(c);
                    }
                }
                (regret, count, dec, zero, agree, worlds_pick_truth, multi)
            }));
        }
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });

    let mut regret = [0f64; 13];
    let mut count = [0u64; 13];
    let (mut dec, mut zero, mut agree, mut wpt, mut multi) = (0u64, 0u64, 0u64, 0u64, 0u64);
    for r in res {
        for i in 0..13 {
            regret[i] += r.0[i];
            count[i] += r.1[i];
        }
        dec += r.2;
        zero += r.3;
        agree += r.4;
        wpt += r.5;
        multi += r.6;
    }
    let total: f64 = regret.iter().sum();

    println!("deals                    {}", deals);
    println!("decisions with a choice  {}", multi);
    println!("perfect decisions        {:.1}%", 100.0 * zero as f64 / dec as f64);
    println!(
        "total regret             {:.3} pts / round  (both seats combined)",
        total / deals as f64
    );
    println!(
        "                         {:.3} pts / round / seat",
        total / deals as f64 / 2.0
    );
    println!(
        "\nsampled worlds AGREE on the best move  {:.1}%  <- if high, reweighting worlds cannot help",
        100.0 * agree as f64 / multi as f64
    );
    println!(
        "world-majority move is truly optimal   {:.1}%",
        100.0 * wpt as f64 / multi as f64
    );

    println!("\n-- regret by trick (pts lost per round, both seats) --");
    for t in 0..13 {
        if count[t] == 0 {
            continue;
        }
        let v = regret[t] / deals as f64;
        let bar: String = std::iter::repeat('#')
            .take((v * 40.0).round().max(0.0) as usize)
            .collect();
        println!(
            "  trick {:>2} ({:+}) {:>6.3}  {}",
            t + 1,
            dissonance::state::trick_value(t as u8),
            v,
            bar
        );
    }
}
