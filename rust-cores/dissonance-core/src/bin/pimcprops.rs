//! The three game-tree properties that predict whether PIMC search is close to
//! optimal — leaf correlation, bias, disambiguation — measured on THIS game.
//!
//! Long, Sturtevant, Buro & Bowling (AAAI 2010) parameterise a synthetic tree
//! by three numbers and show which combinations make PIMC near-optimal and
//! which make it badly wrong. Their headline for a reader in our position:
//! **a LOW disambiguation factor is good for PIMC and a MID-RANGE one is the
//! worst case.** CAMPAIGN.md has already diagnosed our residual as strategy
//! fusion by a different route (`diag`); this says how much of it the shape of
//! the game says is recoverable at all, and therefore whether a fusion-aware
//! search (alpha-mu) is worth building before it is built.
//!
//! WHAT THESE NUMBERS ARE, EXACTLY. The paper's three parameters are knobs on
//! a SYNTHETIC binary tree, not quantities with a canonical estimator on a real
//! game — the paper itself says a real game is "a cloud of parameters" rather
//! than a point. So each is operationalised here, and the operationalisation is
//! stated rather than implied:
//!
//! * **leaf correlation** — their model: with probability `lc` a sibling pair
//!   of TERMINAL nodes shares a payoff, otherwise they are anti-correlated.
//!   Here: at a real reachable node where the mover has >= 2 legal cards, solve
//!   the TRUE world for every one of them and ask whether they all come back
//!   equal. Reported per trick, because "near a leaf" is the part of their
//!   model that matters and a curve says more than a scalar. `lc` proper is the
//!   deepest trick that still has choices in it.
//! * **bias** — their model: the probability the game favours one player.
//!   Here: P(seat 0 takes the better half of the +5 pool) under exact
//!   double-dummy play from the deal, i.e. off the root solve rather than off
//!   the bots, so it is a property of the GAME and not of who is playing it.
//! * **disambiguation factor** — their model: how fast an information set
//!   shrinks with depth. Here: |I| is COUNTED EXACTLY (see `infoset_log10`),
//!   and df_t = 1 - |I_(t+1)| / |I_t| per ply.
//!
//! The exact count is the part worth trusting. `View::determinize` is uniform
//! over consistent deals and its constraint structure is simple enough to
//! count in closed form rather than sample: the opponent's hand is any `nh`-
//! subset of the cards no void and no must-head ceiling excludes, and every
//! remaining pool card falls into a labelled covered-pile slot or the unordered
//! out-pile. So |I| = C(n_allowed, nh) * (nslots + n_out)! / n_out!, which is
//! the determinizer's own sample space read as a number.
//!
//! AND IT IS DECOMPOSED, which is the part this repo actually wants. The same
//! count with the void/cap constraints DROPPED is what a searcher that does no
//! inference at all faces. The gap between the two curves is, in bits, exactly
//! what following-suit inference buys — the quantity CAMPAIGN.md's washed
//! inference experiments spent a campaign on without ever sizing.
//!
//!   pimcprops [deals] [k]

use dissonance::bots::*;
use dissonance::cards::NCARD;
use dissonance::dd::Dd;
use dissonance::game::{Bot, Game};
use dissonance::rng::Rng;

struct Acc {
    /// nodes with >= 2 legal cards, by trick
    choice: [u64; 13],
    /// ... of those, how many had every sibling solving to the same value
    flat: [u64; 13],
    /// summed (max - min) over sibling values, by trick
    spread: [f64; 13],
    /// summed log10 |I| by (seat, ply), with and without inference, and counts.
    ///
    /// PER SEAT, and that is not a detail. An information set shrinks on EVERY
    /// ply -- both seats learn a card whoever played it -- but ply t and ply
    /// t+1 are different seats' turns, so a ratio taken across consecutive
    /// plies of the pooled series divides one seat's count by the other's and
    /// reports a set that GROWS. The first cut of this file did exactly that
    /// and printed negative disambiguation, which is what caught it.
    iset: [[f64; 27]; 2],
    iset_noinf: [[f64; 27]; 2],
    iset_n: [[u64; 27]; 2],
    /// bias: deals where seat 0's double-dummy differential is positive / zero
    dd_pos: u64,
    dd_tie: u64,
    deals: u64,
}

impl Acc {
    fn new() -> Acc {
        Acc {
            choice: [0; 13],
            flat: [0; 13],
            spread: [0.0; 13],
            iset: [[0.0; 27]; 2],
            iset_noinf: [[0.0; 27]; 2],
            iset_n: [[0; 27]; 2],
            dd_pos: 0,
            dd_tie: 0,
            deals: 0,
        }
    }
    fn merge(&mut self, o: &Acc) {
        for i in 0..13 {
            self.choice[i] += o.choice[i];
            self.flat[i] += o.flat[i];
            self.spread[i] += o.spread[i];
        }
        for q in 0..2 {
            for i in 0..27 {
                self.iset[q][i] += o.iset[q][i];
                self.iset_noinf[q][i] += o.iset_noinf[q][i];
                self.iset_n[q][i] += o.iset_n[q][i];
            }
        }
        self.dd_pos += o.dd_pos;
        self.dd_tie += o.dd_tie;
        self.deals += o.deals;
    }
}

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

    let parts: Vec<Acc> = std::thread::scope(|sc| {
        let mut hs = Vec::new();
        for t in 0..threads {
            hs.push(sc.spawn(move || {
                let mut acc = Acc::new();
                let mut oracle = Dd::new(20);
                let mut root = Dd::new(20);
                let mut bots: Vec<PimcBot> = (0..2)
                    .map(|i| PimcBot::new(k, 0x9C11 ^ (t as u64) ^ (i as u64) << 8, 20))
                    .collect();

                for i in 0..per {
                    let idx = t * per + i;
                    if idx >= deals {
                        break;
                    }
                    let seed = idx as u64 + 1;
                    let mut g = Game::deal(&mut Rng::new(seed), (seed % 5) as u8, 0);

                    // BIAS is a property of the game, so it comes off the exact
                    // root value and not off whoever is playing.
                    let v0 = root.solve(&g.s);
                    match v0.cmp(&0) {
                        std::cmp::Ordering::Greater => acc.dd_pos += 1,
                        std::cmp::Ordering::Equal => acc.dd_tie += 1,
                        std::cmp::Ordering::Less => {}
                    }
                    acc.deals += 1;

                    let mut ply = 0usize;
                    while !g.over() {
                        let p = g.s.to_play() as usize;
                        let v = g.view(p);

                        // BOTH seats, every ply: a set shrinks when the other
                        // side plays too, and the ratio is only meaningful
                        // within one seat's own series.
                        for q in 0..2 {
                            let vq = if q == p { v.clone() } else { g.view(q) };
                            acc.iset[q][ply] += vq.infoset_log10(true);
                            acc.iset_noinf[q][ply] += vq.infoset_log10(false);
                            acc.iset_n[q][ply] += 1;
                        }

                        let mut m = [0u8; 16];
                        let n = v.legal(&mut m);
                        if n >= 2 {
                            let tr = g.s.trick as usize;
                            let mut truth = [0i16; 16];
                            oracle.solve_root(&g.s, &m[..n], &mut truth);
                            let hi = truth[..n].iter().copied().max().unwrap();
                            let lo = truth[..n].iter().copied().min().unwrap();
                            acc.choice[tr] += 1;
                            if hi == lo {
                                acc.flat[tr] += 1;
                            }
                            acc.spread[tr] += (hi - lo) as f64;
                        }

                        let c = bots[p].pick(&v);
                        g.apply(c);
                        ply += 1;
                    }
                }
                acc
            }));
        }
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });

    let mut acc = Acc::new();
    for p in &parts {
        acc.merge(p);
    }

    println!("pimcprops: {} deals, PimcBot k={}, classic parity, {} cards", acc.deals, k, NCARD);
    println!();

    println!("LEAF CORRELATION -- P(all sibling moves solve to the SAME value), by trick");
    println!("  trick   nodes-with-choice   all-equal   lc      mean spread (pts)");
    let mut deepest: Option<(usize, f64, u64)> = None;
    for tr in 0..13 {
        if acc.choice[tr] == 0 {
            continue;
        }
        let lc = acc.flat[tr] as f64 / acc.choice[tr] as f64;
        let sp = acc.spread[tr] / acc.choice[tr] as f64;
        println!(
            "  {:>5}   {:>17}   {:>9}   {:.3}   {:.2}",
            tr + 1,
            acc.choice[tr],
            acc.flat[tr],
            lc,
            sp
        );
        deepest = Some((tr + 1, lc, acc.choice[tr]));
    }
    let tot_choice: u64 = acc.choice.iter().sum();
    let tot_flat: u64 = acc.flat.iter().sum();
    if let Some((tr, lc, n)) = deepest {
        println!("  lc (deepest trick with choices, trick {}): {:.3}  (n={})", tr, lc, n);
    }
    println!(
        "  lc (pooled over every node with a choice): {:.3}  (n={})",
        tot_flat as f64 / tot_choice.max(1) as f64,
        tot_choice
    );
    println!();

    let b = acc.dd_pos as f64 / acc.deals.max(1) as f64;
    println!("BIAS -- P(seat 0 ahead under exact double-dummy play from the deal)");
    println!(
        "  seat0 ahead {:.3}   tied {:.3}   seat1 ahead {:.3}   (n={})",
        b,
        acc.dd_tie as f64 / acc.deals.max(1) as f64,
        1.0 - b - acc.dd_tie as f64 / acc.deals.max(1) as f64,
        acc.deals
    );
    println!("  bias (distance from an even game): {:.3}", (b - 0.5).abs() * 2.0);
    println!();

    println!("DISAMBIGUATION -- log10 |information set| by ply, PER SEAT, and the per-ply shrink");
    println!("  ply   log10|I| s0   s1     no-inf s0   s1     inference (bits)   df s0    df s1");
    let mean = |s: &[f64; 27], n: &[u64; 27], i: usize| -> f64 { s[i] / n[i] as f64 };
    let mut dfs: [Vec<f64>; 2] = [Vec::new(), Vec::new()];
    for ply in 0..27 {
        if acc.iset_n[0][ply] == 0 {
            continue;
        }
        let cur = [
            mean(&acc.iset[0], &acc.iset_n[0], ply),
            mean(&acc.iset[1], &acc.iset_n[1], ply),
        ];
        let noinf = [
            mean(&acc.iset_noinf[0], &acc.iset_n[0], ply),
            mean(&acc.iset_noinf[1], &acc.iset_n[1], ply),
        ];
        let bits = ((noinf[0] - cur[0]) + (noinf[1] - cur[1])) / 2.0 / 0.30103;
        let mut df_s = [String::from("-"), String::from("-")];
        for q in 0..2 {
            if ply + 1 < 27 && acc.iset_n[q][ply + 1] > 0 {
                let nxt = mean(&acc.iset[q], &acc.iset_n[q], ply + 1);
                let d = 1.0 - 10f64.powf(nxt - cur[q]);
                dfs[q].push(d);
                df_s[q] = format!("{:.3}", d);
            }
        }
        println!(
            "  {:>3}   {:>8.3}  {:>6.3}     {:>7.3}  {:>6.3}     {:>16.2}   {:>6}  {:>6}",
            ply, cur[0], cur[1], noinf[0], noinf[1], bits, df_s[0], df_s[1]
        );
    }
    let all: Vec<f64> = dfs[0].iter().chain(dfs[1].iter()).copied().collect();
    if !all.is_empty() {
        println!("  df (mean over every ply, both seats): {:.3}", all.iter().sum::<f64>() / all.len() as f64);
        let early: Vec<f64> = dfs[0].iter().take(13).chain(dfs[1].iter().take(13)).copied().collect();
        println!("  df (mean over the first 13 plies): {:.3}", early.iter().sum::<f64>() / early.len() as f64);
    }
    let tot_bits = {
        let mut b = 0.0;
        let mut n = 0.0;
        for ply in 0..27 {
            if acc.iset_n[0][ply] == 0 { continue; }
            for q in 0..2 {
                b += (mean(&acc.iset_noinf[q], &acc.iset_n[q], ply) - mean(&acc.iset[q], &acc.iset_n[q], ply)) / 0.30103;
                n += 1.0;
            }
        }
        b / n
    };
    println!("  inference is worth {:.2} bits per ply on average (void + must-head only)", tot_bits);
}
