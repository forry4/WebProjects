//! Skat-mode bidding lab — the measurement instrument for the second auction.
//!
//! Same discipline as `bidlab`: the contract outcome is resolved by an exact
//! double-dummy solve of the real deal rather than by playing the cards, so a
//! difference between configurations is a difference in BIDDING. Reported
//! "made" rates are therefore ceilings.
//!
//!   skatlab [--deals N] [--k K] [--null-value V] [--short S]
//!           [--no-hand] [--no-sharp] [--no-null] [--expect-hand] [--dump P]
//!
//! ## What is exact and what is not
//!
//! * **The auction is talon-UNAWARE.** A bidder has not seen the talon, so this
//!   is faithful rather than a shortcut — but it means declarers systematically
//!   under-bid, and settled values read low.
//! * **The talon and the declaration are resolved EXACTLY**, and this is where
//!   the 22x the design note asked for is spent: all 21 candidate swaps plus
//!   standing pat plus playing Hand, each scored against a real double-dummy
//!   solve. That is what makes the Hand rate a measurement rather than a guess.
//!   As in `bidlab`, resolving exactly credits the declarer with knowing the
//!   deal, so it answers "how often does OPTIMAL play choose Hand", not "how
//!   often would a human".
//! * **The level choice is free.** `dd.solve` returns the declarer's points in
//!   a denomination; which level to declare on top of that is pure arithmetic,
//!   so the exhaustive declaration search costs 6 solves per candidate state,
//!   not one per (denomination, level) pair.
//! * **Open is not modelled at all** — a double-dummy defence already has
//!   perfect information, so the face-up reveal is free here and a solver would
//!   take it every time. See the note in `src/skat.rs`.

use oddtrick::auction::{eval_hand, denom_str, HandEval, MAX_LEVEL, NDEN, NULL_DENOM};
use oddtrick::cards::NOTRUMP;
use oddtrick::dd::Dd;
use oddtrick::game::Game;
use oddtrick::rng::Rng;
use oddtrick::skat::*;
use oddtrick::state::POOL;

fn flag(a: &[String], n: &str) -> Option<String> {
    a.iter().position(|x| x == n).and_then(|i| a.get(i + 1)).cloned()
}

#[derive(Default, Clone)]
struct Stats {
    n: f64,
    thrown_in: f64,
    contracts: u64,
    /// Net to the DECLARER per contract — the sign test on whether winning the
    /// auction is worth anything at all.
    decl_net: f64,
    made: u64,
    /// Settled bid value, and the value the declaration actually came out at.
    /// They differ whenever the declarer volunteered a bigger game than the
    /// number forced, which is the mode's "bid against yourself" claim.
    bid_hist: Vec<(i32, u64)>,
    over_declared: u64,
    over_declared_by: f64,
    clevel: [u64; 16],
    cmade: [u64; 16],
    cdenom: [u64; 6],
    hand: u64,
    sharp: u64,
    hand_made: u64,
    sharp_made: u64,
    null_contracts: u64,
    null_made: u64,
    kontra: u64,
    kontra_right: u64,
    stake: f64,
    /// Auctions in which the opener declined and the opponent took it.
    open_pass: u64,
    /// Believed minus true declarer points, summed over contracts. Positive
    /// means the world sample flatters the declarer.
    belief_gap: f64,
    belief_n: f64,
    bids: [u64; 12],
    rows: Vec<String>,
}

/// Declarer points in `denom` for this exact deal, by double-dummy.
fn pts_in(dd: &mut Dd, base: &oddtrick::state::State, denom: u8, decl: usize,
          declarer_leads: bool) -> i32 {
    let s = oddtrick::state::State {
        trump: denom,
        trick: 0,
        led: -1,
        leader: if declarer_leads { decl as u8 } else { 1 - decl as u8 },
        pts: [0, 0],
        ..*base
    };
    let diff = dd.solve(&s) as i32;
    let p0 = (POOL as i32 + diff) / 2;
    if decl == 0 { p0 } else { POOL as i32 - p0 }
}

fn null_makes(dd: &mut Dd, base: &oddtrick::state::State, decl: usize,
              declarer_leads: bool) -> bool {
    let s = oddtrick::state::State {
        trump: NOTRUMP,
        trick: 0,
        led: -1,
        leader: if declarer_leads { decl as u8 } else { 1 - decl as u8 },
        pts: [0, 0],
        ..*base
    };
    dd.null_no_even_makeable(&s, decl)
}

/// The declarer's post-auction decision: talon-or-Hand, then the declaration
/// and the Sharp announcement on top.
///
/// **Chosen under the declarer's own uncertainty, resolved exactly afterwards.**
/// That split is the whole point. An earlier version of this chose the
/// declaration by maximising the EXACT double-dummy net, which is clairvoyance
/// rather than optimal play: a declarer who already knows the outcome simply
/// picks the highest-paying game it happens to make, and the measured make rate
/// pins at ~96% by construction while Kontra reads 6% correct. Beliefs first,
/// truth only at resolution.
///
/// The declarer's beliefs ARE talon-aware, which is what the design note asked
/// the 22x be spent on: after looking, the three shown cards are known out of
/// play, so the post-look world sample is drawn from a strictly smaller pool
/// than the auction's was. A Hand game keeps the blind view, because a declarer
/// who never looked genuinely does not know them.
///
/// Returns (chosen declaration, the state actually played, exact declarer
/// points in the chosen denomination, whether Null exactly made, and the points
/// the declarer BELIEVED it would take in that denomination).
#[allow(clippy::too_many_arguments)]
fn resolve_declarer(
    dd: &mut Dd,
    cfg: &SkatCfg,
    g: &Game,
    bid: i32,
    decl: usize,
    rng: &mut Rng,
    tk: usize,
) -> (Decl, oddtrick::state::State, i32, bool, f64) {
    // After looking, the shown cards are known out of play; before looking they
    // are not. `out_public` is exactly "out-cards this observer can place", so
    // the post-look view is the same constructor over a wider public set.
    let mut looked_g = g.clone();
    looked_g.out_public = g.out_shown;
    let v_blind = g.view(decl);
    let v_look = looked_g.view(decl);

    // The SAME sampled worlds are reused across every candidate holding, so the
    // comparison between them is paired — the exchange is exactly what this
    // decision turns on, which is where the noise most needs cancelling.
    let mut buf = Vec::new();
    let blind_worlds: Vec<oddtrick::state::State> =
        (0..tk).map(|_| v_blind.determinize(rng, &mut buf)).collect();
    let look_worlds: Vec<oddtrick::state::State> =
        (0..tk).map(|_| v_look.determinize(rng, &mut buf)).collect();

    // Candidate holdings: play Hand (never look), or look and then either stand
    // pat or make one of the 21 exchanges. A holding is a (mask-in, mask-out)
    // edit applied to whichever world we are evaluating.
    let mut cands: Vec<(bool, u64, u64)> = Vec::new(); // (hand, take, give)
    if cfg.allow_hand {
        cands.push((true, 0, 0));
    }
    cands.push((false, 0, 0)); // looked, stood pat
    let mut sh = g.out_shown;
    while sh != 0 {
        let oc = sh.trailing_zeros() as u8;
        sh &= sh - 1;
        let mut hand = g.s.hand[decl];
        while hand != 0 {
            let hc = hand.trailing_zeros() as u8;
            hand &= hand - 1;
            cands.push((false, 1u64 << oc, 1u64 << hc));
        }
    }

    let mut best: Option<(Decl, u64, u64, f64)> = None;
    for (is_hand, take, give) in cands {
        let worlds = if is_hand { &blind_worlds } else { &look_worlds };
        // Six solves per world per candidate; every level and Sharp choice on
        // top of them is arithmetic, so the declaration search is free.
        let mut pts: Vec<[i32; NDEN]> = Vec::with_capacity(worlds.len());
        let mut nulls: Vec<bool> = Vec::with_capacity(worlds.len());
        for w in worlds {
            let mut st = *w;
            st.hand[decl] = (st.hand[decl] & !give) | take;
            let mut row = [0i32; NDEN];
            for (d, slot) in row.iter_mut().enumerate() {
                *slot = pts_in(dd, &st, d as u8, decl, cfg.declarer_leads);
            }
            pts.push(row);
            nulls.push(if cfg.allow_null && bid <= cfg.null_value {
                null_makes(dd, &st, decl, cfg.declarer_leads)
            } else {
                false
            });
        }
        for d in declarable(cfg, bid, is_hand) {
            // Same confidence quantile the auction bid on, so the declarer does
            // not suddenly become an optimist the moment it wins.
            let mut vals: Vec<i32> = (0..worlds.len())
                .map(|wi| {
                    if d.is_null() {
                        d.null_payoff(cfg, nulls[wi])
                    } else {
                        d.payoff(cfg, pts[wi][d.denom as usize])
                    }
                })
                .collect();
            let v = oddtrick::skat::quantile(&mut vals, cfg.q);
            if best.as_ref().map_or(true, |b| v > b.3) {
                best = Some((d, take, give, v));
            }
        }
    }
    let (d, take, give, _) = best.expect("every bid has at least one declaration");

    // What the declarer BELIEVED it would score in the game it chose, at the
    // same quantile it chose by. Paired against the truth below, this is the
    // direct test of whether the world sample is optimistic -- which is the
    // difference between "the mode is mispriced" and "the instrument is
    // under-sampled", and not something to settle by argument.
    let believed = if d.is_null() {
        0.0
    } else {
        let worlds = if d.hand { &blind_worlds } else { &look_worlds };
        let mut v: Vec<i32> = worlds
            .iter()
            .map(|w| {
                let mut st = *w;
                st.hand[decl] = (st.hand[decl] & !give) | take;
                pts_in(dd, &st, d.denom, decl, cfg.declarer_leads)
            })
            .collect();
        oddtrick::skat::quantile(&mut v, cfg.q)
    };

    // Only now does the truth come in.
    let mut played = g.s;
    played.hand[decl] = (played.hand[decl] & !give) | take;
    let dpts = if d.is_null() {
        0
    } else {
        pts_in(dd, &played, d.denom, decl, cfg.declarer_leads)
    };
    let nm = d.is_null() && null_makes(dd, &played, decl, cfg.declarer_leads);
    (d, played, dpts, nm, believed)
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let deals: usize = flag(&args, "--deals").and_then(|s| s.parse().ok()).unwrap_or(120);
    let k: usize = flag(&args, "--k").and_then(|s| s.parse().ok()).unwrap_or(4);
    // Worlds for the declarer's talon/declaration decision. Held separately
    // because that stage costs 23 candidate holdings x tk x 6 solves — it is
    // where the 22x lives, so it is the knob you turn when the run is too slow.
    let tk: usize = flag(&args, "--tk").and_then(|s| s.parse().ok()).unwrap_or(k);
    let dump = flag(&args, "--dump");
    let dumping = dump.is_some();
    let cfg = SkatCfg {
        null_value: flag(&args, "--null-value").and_then(|s| s.parse().ok())
            .unwrap_or(SKAT_NULL_VALUE),
        short: flag(&args, "--short").and_then(|s| s.parse().ok()).unwrap_or(4),
        allow_null: !args.iter().any(|a| a == "--no-null"),
        allow_sharp: !args.iter().any(|a| a == "--no-sharp"),
        allow_hand: !args.iter().any(|a| a == "--no-hand"),
        bid_expects_hand: args.iter().any(|a| a == "--expect-hand"),
        q: flag(&args, "--q").and_then(|s| s.parse().ok()).unwrap_or(0.5),
        ..SkatCfg::default()
    };
    let threads: usize = flag(&args, "--threads").and_then(|s| s.parse().ok()).unwrap_or(
        std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4)
            .saturating_sub(1).max(1),
    );

    let rungs = ladder(&cfg);
    let per = deals.div_ceil(threads);
    let out: Vec<Stats> = std::thread::scope(|sc| {
        let mut hs = Vec::new();
        for t in 0..threads {
            let rungs = rungs.clone();
            hs.push(sc.spawn(move || {
                let mut dd = Dd::new(20);
                let mut st = Stats::default();
                st.bid_hist = rungs.iter().map(|&v| (v, 0u64)).collect();
                for i in 0..per {
                    let idx = t * per + i;
                    if idx >= deals {
                        break;
                    }
                    let seed = idx as u64 + 1;
                    let g = Game::deal_shown(&mut Rng::new(seed), 4, 0, 3);
                    let evs: Vec<HandEval> = (0..2)
                        .map(|p| {
                            let v = g.view(p);
                            let mut r = Rng::new(seed ^ ((p as u64 + 1) << 32));
                            eval_hand(&v, &mut dd, &mut r, k, cfg.declarer_leads,
                                      false, cfg.allow_null)
                        })
                        .collect();

                    let opener = (idx % 2) as u8;
                    let mut auc = SkatAuc::open(opener);
                    let mut nbids = 0usize;
                    let mut opener_passed = false;
                    loop {
                        let actor = auc.to_act as usize;
                        let mut s = SkatSolver::new(&evs[actor], cfg, actor);
                        match s.best_action(&auc) {
                            SkatAction::Pass => {
                                if auc.declarer >= 0 {
                                    break; // a bid stands: it settles here
                                }
                                if auc.passed_at_zero {
                                    break; // both declined: thrown in
                                }
                                opener_passed = true;
                                auc.passed_at_zero = true;
                                auc.to_act = 1 - auc.to_act;
                            }
                            SkatAction::Bid(v) => {
                                nbids += 1;
                                auc.vi = rungs.iter().position(|&x| x == v).unwrap() as i16;
                                auc.declarer = auc.to_act as i8;
                                auc.to_act = 1 - auc.to_act;
                            }
                        }
                    }

                    st.n += 1.0;
                    if auc.declarer < 0 {
                        st.thrown_in += 1.0;
                        continue;
                    }
                    if opener_passed {
                        st.open_pass += 1;
                    }
                    let decl = auc.declarer as usize;
                    let bid = rungs[auc.vi as usize];
                    let mut trng = Rng::new(seed ^ 0xD1CE_5EED);
                    let (d, _played, dpts, nm, believed) =
                        resolve_declarer(&mut dd, &cfg, &g, bid, decl, &mut trng, tk);
                    if !d.is_null() {
                        st.belief_gap += believed - dpts as f64;
                        st.belief_n += 1.0;
                    }

                    let made = if d.is_null() { nm } else { dpts >= d.target(&cfg) };
                    // The defender replies from THEIR OWN sample, blind to the
                    // talon — a real posterior, not a peek at the answer.
                    let def = SkatSolver::new(&evs[1 - decl], cfg, 1 - decl);
                    let kontra = def.kontra(&d, decl);
                    let doubling = if kontra { 2 } else { 1 };
                    let net = if d.is_null() {
                        d.null_payoff(&cfg, nm)
                    } else {
                        d.payoff(&cfg, dpts)
                    } * doubling;

                    st.contracts += 1;
                    st.decl_net += net as f64;
                    st.stake += (d.stake(&cfg) * doubling) as f64;
                    st.bids[nbids.min(11)] += 1;
                    if let Some(slot) = st.bid_hist.iter_mut().find(|(v, _)| *v == bid) {
                        slot.1 += 1;
                    }
                    if made {
                        st.made += 1;
                    }
                    if d.hand {
                        st.hand += 1;
                        if made {
                            st.hand_made += 1;
                        }
                    }
                    if d.sharp {
                        st.sharp += 1;
                        if made {
                            st.sharp_made += 1;
                        }
                    }
                    if kontra {
                        st.kontra += 1;
                        if !made {
                            st.kontra_right += 1;
                        }
                    }
                    st.cdenom[d.denom as usize] += 1;
                    if d.is_null() {
                        st.null_contracts += 1;
                        if nm {
                            st.null_made += 1;
                        }
                    } else {
                        st.clevel[d.level as usize] += 1;
                        if made {
                            st.cmade[d.level as usize] += 1;
                        }
                        // Declaring above what the number forced is the mode's
                        // "the declarer bids against themselves" claim, stated
                        // as a number.
                        let forced = declarable(&cfg, bid, d.hand)
                            .into_iter()
                            .filter(|x| x.denom == d.denom)
                            .map(|x| x.level)
                            .min()
                            .unwrap_or(d.level);
                        if d.level > forced {
                            st.over_declared += 1;
                            st.over_declared_by += (d.level - forced) as f64;
                        }
                    }
                    if dumping {
                        st.rows.push(format!(
                            "{{\"seed\":{},\"opener\":{},\"decl\":{},\"bid\":{},\"denom\":{},\"level\":{},\"hand\":{},\"sharp\":{},\"null\":{},\"made\":{},\"kontra\":{},\"stake\":{},\"net\":{},\"nbids\":{},\"dpts\":{}}}",
                            seed, opener, decl, bid, d.denom, d.level, d.hand, d.sharp,
                            d.is_null(), made, kontra, d.stake(&cfg) * doubling, net,
                            nbids, dpts
                        ));
                    }
                }
                st
            }));
        }
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });

    let mut s = Stats::default();
    s.bid_hist = rungs.iter().map(|&v| (v, 0u64)).collect();
    for r in out {
        s.n += r.n;
        s.thrown_in += r.thrown_in;
        s.contracts += r.contracts;
        s.decl_net += r.decl_net;
        s.made += r.made;
        s.over_declared += r.over_declared;
        s.over_declared_by += r.over_declared_by;
        s.hand += r.hand;
        s.sharp += r.sharp;
        s.hand_made += r.hand_made;
        s.sharp_made += r.sharp_made;
        s.null_contracts += r.null_contracts;
        s.null_made += r.null_made;
        s.kontra += r.kontra;
        s.kontra_right += r.kontra_right;
        s.stake += r.stake;
        s.open_pass += r.open_pass;
        s.belief_gap += r.belief_gap;
        s.belief_n += r.belief_n;
        s.rows.extend(r.rows.iter().cloned());
        for i in 0..16 {
            s.clevel[i] += r.clevel[i];
            s.cmade[i] += r.cmade[i];
        }
        for i in 0..6 {
            s.cdenom[i] += r.cdenom[i];
        }
        for i in 0..12 {
            s.bids[i] += r.bids[i];
        }
        for (j, (_, c)) in r.bid_hist.iter().enumerate() {
            s.bid_hist[j].1 += c;
        }
    }

    let c = s.contracts.max(1) as f64;
    println!("SKAT MODE — {} deals, k={} worlds, ladder {} rungs ({}..{})",
             s.n as u64, k, rungs.len(), rungs[0], rungs[rungs.len() - 1]);
    println!("bases C{} D{} H{} S{} NT{}, Null {}, short {}/pt, q={}",
             cfg.bases[0], cfg.bases[1], cfg.bases[2], cfg.bases[3], cfg.bases[4],
             cfg.null_value, cfg.short, cfg.q);
    println!("declarer decision worlds tk={} (23 holdings x tk x 6 solves per contract)", tk);
    println!("announcements: Hand {}, Sharp {} (+{}), Open NOT MODELLED (free under double dummy)",
             if cfg.allow_hand { "on" } else { "off" },
             if cfg.allow_sharp { "on" } else { "off" }, cfg.sharp_bonus);
    println!();
    println!("contracts             {} ({:.1}% of deals)", s.contracts, 100.0 * c / s.n.max(1.0));
    println!("hands thrown in       {:.1}%  (both players declined)", 100.0 * s.thrown_in / s.n.max(1.0));
    println!("opener declined       {:.1}%  (opponent took it)", 100.0 * s.open_pass as f64 / c);
    println!("declarer made         {:.1}%", 100.0 * s.made as f64 / c);
    println!("declarer net          {:+.2} per contract", s.decl_net / c);
    println!("mean stake            {:.1}", s.stake / c);
    println!("belief gap            {:+.2} pts (believed - true, in the declared denomination)",
             s.belief_gap / s.belief_n.max(1.0));
    println!();
    println!("-- Q1  ANNOUNCEMENT RATES (target: Hand a real temptation, ~15-30%) --");
    println!("  Hand              {:5.1}%   (made {:.1}%)", 100.0 * s.hand as f64 / c,
             100.0 * s.hand_made as f64 / s.hand.max(1) as f64);
    println!("  Sharp             {:5.1}%   (made {:.1}%)", 100.0 * s.sharp as f64 / c,
             100.0 * s.sharp_made as f64 / s.sharp.max(1) as f64);
    println!();
    println!("-- Q2  OVERBID --");
    println!("  structurally impossible: every rung <= NT x {} is declarable, so", MAX_LEVEL);
    println!("  the rule can never fire. Declaring ABOVE what the bid forced is the");
    println!("  live decision instead: {:.1}% of contracts, by +{:.2} levels on average.",
             100.0 * s.over_declared as f64 / c,
             s.over_declared_by / s.over_declared.max(1) as f64);
    println!();
    println!("-- Q3  NULL AT {} --", cfg.null_value);
    println!("  contracts         {} ({:.1}% of all), made {:.1}%",
             s.null_contracts, 100.0 * s.null_contracts as f64 / c,
             100.0 * s.null_made as f64 / s.null_contracts.max(1) as f64);
    println!();
    println!("-- Q4  KONTRA (target: ~10-20%, right more often than not) --");
    println!("  doubled           {:5.1}%   correct {:.1}%", 100.0 * s.kontra as f64 / c,
             100.0 * s.kontra_right as f64 / s.kontra.max(1) as f64);
    println!();

    println!("-- Q5  SETTLED BID VALUE (the ladder actually used) --");
    let tot: u64 = s.bid_hist.iter().map(|(_, n)| n).sum();
    let mut ent = 0f64;
    let mut used = 0usize;
    for (v, n) in &s.bid_hist {
        if *n == 0 {
            continue;
        }
        used += 1;
        let p = *n as f64 / tot as f64;
        ent -= p * p.ln();
        let bar: String = std::iter::repeat('#').take((60.0 * p).round() as usize).collect();
        println!("  {:>3}  {:>4}  ({:5.1}%)  {}", v, n, 100.0 * p, bar);
    }
    println!("      {} contracts on {}/{} rungs, evenness {:.3}",
             tot, used, rungs.len(), ent / (rungs.len() as f64).ln());

    println!("\n-- SETTLED DECLARED LEVEL (comparable to bidlab's histogram) --");
    let ltot: u64 = s.clevel.iter().sum();
    let mut lent = 0f64;
    for l in 0..16 {
        if s.clevel[l] == 0 {
            continue;
        }
        let p = s.clevel[l] as f64 / ltot as f64;
        lent -= p * p.ln();
        let bar: String = std::iter::repeat('#').take((60.0 * p).round() as usize).collect();
        println!("  {:>2}  {:>4}  ({:5.1}%)  made {:5.1}%  {}", l, s.clevel[l], 100.0 * p,
                 100.0 * s.cmade[l] as f64 / s.clevel[l] as f64, bar);
    }
    println!("      {} contracts, evenness {:.3} over {} levels",
             ltot, lent / (MAX_LEVEL as f64).ln(), MAX_LEVEL);

    println!("\n-- SETTLED DECLARED DENOMINATION --");
    let dtot: u64 = s.cdenom.iter().sum();
    let mut dent = 0f64;
    for d in 0..6 {
        if s.cdenom[d] == 0 {
            continue;
        }
        let p = s.cdenom[d] as f64 / dtot as f64;
        dent -= p * p.ln();
        let bar: String = std::iter::repeat('#').take((50.0 * p).round() as usize).collect();
        println!("  {:>4}  {:>4}  ({:5.1}%)  {}", denom_str(d as u8), s.cdenom[d], 100.0 * p, bar);
    }
    println!("      evenness {:.3}", dent / (NDEN as f64).ln());
    let _ = NULL_DENOM;

    println!("\n-- bids in the auction --");
    let bt: u64 = s.bids.iter().sum();
    for i in 0..12 {
        if s.bids[i] == 0 {
            continue;
        }
        println!("  {:>2} bids  {:>5}  ({:5.1}%)", i, s.bids[i], 100.0 * s.bids[i] as f64 / bt as f64);
    }

    if let Some(path) = dump {
        use std::io::Write;
        let mut f = std::fs::File::create(&path).expect("--dump path");
        for r in &s.rows {
            writeln!(f, "{}", r).expect("write dump row");
        }
        println!("\nwrote {} rows to {}", s.rows.len(), path);
    }
}
