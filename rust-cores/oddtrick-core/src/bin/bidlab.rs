//! Bidding lab: runs full auctions and reports both who wins and WHAT the
//! winning bidder actually does.
//!
//! The contract outcome is resolved by an exact double-dummy solve of the real
//! deal rather than by playing the cards. That is deliberate: it removes
//! card-play noise entirely, so a difference between two bidding strategies is
//! a difference in BIDDING. It also means reported "made" rates are ceilings —
//! a real declarer will make fewer.
//!
//!   bidlab <styleA> <styleB> [--deals N] [--k K] [--make lin|quad]
//!          [--set lin|quad] [--short S] [--min L] [--flat F] [--double]
//!   style := solve | myopic | nosac | shade+1 | shade-1
//!
//! Cost note: a deal needs 2 players x K worlds x 5 denominations x 2
//! declarers double-dummy solves, at ~77 ms each. The hand evaluations depend
//! only on the deal, NOT on which strategy sits in which seat, so they are
//! computed once and reused across both seatings — worth an exact 2x.

use oddtrick::auction::*;
use oddtrick::dd::Dd;
use oddtrick::game::Game;
use oddtrick::rng::Rng;
use oddtrick::state::POOL;

fn parse_style(s: &str) -> Style {
    match s {
        "solve" => Style::Solve,
        "myopic" => Style::Myopic,
        "nosac" => Style::NoSac,
        x if x.starts_with("shade") => Style::Shade(x[5..].parse().expect("shade+N")),
        other => panic!("unknown style {other:?}"),
    }
}

fn flag(a: &[String], n: &str) -> Option<String> {
    a.iter().position(|x| x == n).and_then(|i| a.get(i + 1)).cloned()
}

#[derive(Default, Clone)]
struct Stats {
    n: f64,
    score: f64,
    opened: f64,
    open_level: [u64; 14],
    open_best_denom: f64,
    declared: f64,
    made: f64,
    overtook: f64,
    sacrificed: f64,
    contract_level: f64,
    contracts: u64,
    clevel: [u64; 14],
    cmade: [u64; 14],
    doubled: f64,
    doubled_made: f64,
    thrown_in: f64,
    overshoot: f64,
    overshoot_n: f64,
    /// Joint distribution: where the auction OPENED vs where it SETTLED,
    /// over all contracts. The only way to see whether a level is rare
    /// because nobody opens there or because it never survives.
    o2s: [[u64; 14]; 14],
    bids: [u64; 12],
}

fn hist(name: &str, h: &[u64; 14], made: Option<&[u64; 14]>) {
    let tot: u64 = h.iter().sum();
    if tot == 0 {
        return;
    }
    println!("\n-- {} --", name);
    for l in 0..14 {
        if h[l] == 0 {
            continue;
        }
        let bar: String = std::iter::repeat('#')
            .take((60.0 * h[l] as f64 / tot as f64).round() as usize)
            .collect();
        match made {
            Some(m) => println!(
                "  {:>2}  {:>5}  ({:5.1}%)  made {:5.1}%  {}",
                l,
                h[l],
                100.0 * h[l] as f64 / tot as f64,
                100.0 * m[l] as f64 / h[l] as f64,
                bar
            ),
            None => println!(
                "  {:>2}  {:>5}  ({:5.1}%)  {}",
                l,
                h[l],
                100.0 * h[l] as f64 / tot as f64,
                bar
            ),
        }
    }
    println!("      {} total", tot);
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let sa = parse_style(&args.first().cloned().unwrap_or("solve".into()));
    let sb = parse_style(&args.get(1).cloned().unwrap_or("solve".into()));
    let deals: usize = flag(&args, "--deals").and_then(|s| s.parse().ok()).unwrap_or(200);
    let k: usize = flag(&args, "--k").and_then(|s| s.parse().ok()).unwrap_or(4);
    let cfg = ScoreCfg {
        bonus_at: flag(&args, "--bonus-at").and_then(|s| s.parse().ok()).unwrap_or(99),
        bonus: flag(&args, "--bonus").and_then(|s| s.parse().ok()).unwrap_or(0),
        short: flag(&args, "--short").and_then(|s| s.parse().ok()).unwrap_or(4),
        over: flag(&args, "--over").and_then(|s| s.parse().ok()).unwrap_or(0),
        burst: flag(&args, "--burst").and_then(|s| s.parse().ok()).unwrap_or(2.5),
        allow_open_pass: args.iter().any(|a| a == "--openpass"),
        global_denoms: args.iter().any(|a| a == "--globaldenoms"),
        slope: 0,
        min_level: flag(&args, "--min").and_then(|s| s.parse().ok()).unwrap_or(1),
        flat: flag(&args, "--flat").and_then(|s| s.parse().ok()).unwrap_or(0),
        allow_double: args.iter().any(|a| a == "--double"),
        declarer_leads: args.iter().any(|a| a == "--declarer-leads"),
        step: flag(&args, "--step").and_then(|s| s.parse().ok()).unwrap_or(1),
        allow_jump: args.iter().any(|a| a == "--jump"),
        max_raise: flag(&args, "--maxraise").and_then(|s| s.parse().ok()).unwrap_or(1),
        straight_mult: flag(&args, "--straight").and_then(|s| s.parse().ok()).unwrap_or(1),
        make_curve: if flag(&args, "--make").as_deref() == Some("lin") {
            Curve::Linear
        } else {
            Curve::Quad
        },
        set_curve: if flag(&args, "--set").as_deref() == Some("quad") {
            Curve::Quad
        } else {
            Curve::Linear
        },
    };
    let threads: usize = flag(&args, "--threads")
        .and_then(|s| s.parse().ok())
        .unwrap_or(
            std::thread::available_parallelism()
                .map(|n| n.get())
                .unwrap_or(4)
                .saturating_sub(1)
                .max(1),
        );

    let per = deals.div_ceil(threads);
    let out: Vec<Stats> = std::thread::scope(|sc| {
        let mut hs = Vec::new();
        for t in 0..threads {
            hs.push(sc.spawn(move || {
                let mut dd = Dd::new(20);
                let mut st = Stats::default();
                for i in 0..per {
                    let idx = t * per + i;
                    if idx >= deals {
                        break;
                    }
                    let seed = idx as u64 + 1;
                    let g = Game::deal(&mut Rng::new(seed), 4, 0);

                    // Computed ONCE per deal: a player's read on their own cards
                    // does not depend on which strategy occupies which seat.
                    let evs: Vec<_> = (0..2)
                        .map(|p| {
                            let v = g.view(p);
                            let mut r = Rng::new(seed ^ ((p as u64 + 1) << 32));
                            eval_hand(&v, &mut dd, &mut r, k, cfg.declarer_leads, false)
                        })
                        .collect();

                    for swap in 0..2usize {
                        let styles = if swap == 0 { [sa, sb] } else { [sb, sa] };
                        let a_seat = if swap == 0 { 0usize } else { 1 };
                        let first = (idx % 2) as u8;

                        // With `allow_open_pass`, a hand that expects to lose
                        // by declaring anything simply declines; the turn then
                        // passes to the other player, and if they decline too
                        // the hand is thrown in.
                        let mut chosen: Option<(u8, u8, u8)> = None;
                        for who in [first, 1 - first] {
                            let mut s = AuctionSolver::new(&evs[who as usize], cfg, who as usize);
                            let (l, d) = s.open(styles[who as usize], who);
                            if !cfg.allow_open_pass {
                                chosen = Some((who, l, d));
                                break;
                            }
                            if s.value(Auc::after_open(who, l, d)) > 0.0 {
                                chosen = Some((who, l, d));
                                break;
                            }
                        }
                        let Some((opener, lvl0, den0)) = chosen else {
                            // Passed out: nobody declares, nobody scores.
                            st.n += 1.0;
                            st.thrown_in += 1.0;
                            continue;
                        };
                        let mut lvl = lvl0;
                        let mut den = den0;
                        if opener as usize == a_seat {
                            st.opened += 1.0;
                            st.open_level[lvl as usize] += 1;
                            let sv =
                                AuctionSolver::new(&evs[opener as usize], cfg, opener as usize);
                            let best_d = (0..NDEN)
                                .max_by(|&x, &y| {
                                    sv.mean_pts(opener as usize, x)
                                        .partial_cmp(&sv.mean_pts(opener as usize, y))
                                        .unwrap()
                                })
                                .unwrap();
                            if best_d == den as usize {
                                st.open_best_denom += 1.0;
                            }
                        }

                        let open_lvl = lvl;
                        let mut nbids = 1usize;
                        let mut auc = Auc::after_open(opener, lvl, den);
                        let mut a_overtook = false;
                        loop {
                            let actor = auc.to_act as usize;
                            let mut s = AuctionSolver::new(&evs[actor], cfg, actor);
                            match s.respond(styles[actor], &auc) {
                                BidAction::Pass => break,
                                BidAction::Double => {
                                    auc.doubled = true;
                                    break;
                                }
                                BidAction::Overtake(l, d) => {
                                    nbids += 1;
                                    if actor == a_seat {
                                        st.overtook += 1.0;
                                        a_overtook = true;
                                    }
                                    auc = auc.overtake(l, d);
                                    lvl = auc.level;
                                    den = auc.denom;
                                }
                            }
                        }

                        let decl = auc.declarer as usize;
                        let real = oddtrick::state::State {
                            trump: den,
                            trick: 0,
                            led: -1,
                            leader: if cfg.declarer_leads {
                                decl as u8
                            } else {
                                1 - decl as u8
                            },
                            pts: [0, 0],
                            ..g.s
                        };
                        let diff = dd.solve(&real) as i32;
                        let p0 = (POOL as i32 + diff) / 2;
                        let dpts = if decl == 0 { p0 } else { POOL as i32 - p0 };
                        let made = dpts >= lvl as i32;
                        let (ds, fs) = if cfg.over > 0 {
                            if made {
                                st.overshoot += cfg.burst;
                                st.overshoot_n += 1.0;
                            }
                            outcome(&cfg, lvl, dpts, 0)
                        } else {
                            contract_score(&cfg, lvl, dpts)
                        };
                        let m = if auc.doubled { 2 } else { 1 };
                        let straight = if lvl == auc.opened_at { cfg.straight_mult } else { 1 };
                        let (ds, fs) = (ds * m * straight, fs * m);

                        let a_score = if decl == a_seat { ds } else { fs };
                        let b_score = if decl == a_seat { fs } else { ds };
                        st.score += (a_score - b_score) as f64;
                        st.n += 1.0;
                        st.contract_level += lvl as f64;
                        st.contracts += 1;
                        st.clevel[lvl as usize] += 1;
                        st.o2s[open_lvl as usize][lvl as usize] += 1;
                        st.bids[nbids.min(11)] += 1;
                        if made {
                            st.cmade[lvl as usize] += 1;
                        }
                        // Counted over ALL contracts so numerator and
                        // denominator share a denominator.
                        if auc.doubled {
                            st.doubled += 1.0;
                            if made {
                                st.doubled_made += 1.0;
                            }
                        }
                        if decl == a_seat {
                            st.declared += 1.0;
                            if made {
                                st.made += 1.0;
                            } else if a_overtook {
                                st.sacrificed += 1.0;
                            }
                        }
                    }
                }
                st
            }));
        }
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });

    let mut s = Stats::default();
    for r in out {
        s.n += r.n;
        s.score += r.score;
        s.opened += r.opened;
        s.open_best_denom += r.open_best_denom;
        s.declared += r.declared;
        s.made += r.made;
        s.overtook += r.overtook;
        s.sacrificed += r.sacrificed;
        s.contract_level += r.contract_level;
        s.contracts += r.contracts;
        s.thrown_in += r.thrown_in;
        s.doubled += r.doubled;
        s.doubled_made += r.doubled_made;
        s.overshoot += r.overshoot;
        s.overshoot_n += r.overshoot_n;
        for i in 0..14 {
            s.open_level[i] += r.open_level[i];
            s.clevel[i] += r.clevel[i];
            s.cmade[i] += r.cmade[i];
            for j in 0..14 {
                s.o2s[i][j] += r.o2s[i][j];
            }
        }
        for i in 0..12 {
            s.bids[i] += r.bids[i];
        }
    }

    println!("A={:?}  B={:?}", sa, sb);
    println!(
        "make {:?}(N)+{} flat, set {:?}(N-1) + {}/pt short, min bid {}, doubling {}",
        cfg.make_curve,
        cfg.flat,
        cfg.set_curve,
        cfg.short,
        cfg.min_level,
        if cfg.allow_double { "ON" } else { "off" }
    );
    println!(
        "step {}, max raise {}, jump {}, straight x{}",
        cfg.step,
        cfg.max_raise,
        if cfg.allow_jump { "ON" } else { "off" },
        cfg.straight_mult
    );
    println!(
        "opening lead to        {}",
        if cfg.declarer_leads { "DECLARER" } else { "defender" }
    );
    println!("rounds                {}", s.n as u64);
    println!("A net score           {:+.4} per round", s.score / s.n);
    println!("mean contract level   {:.2}", s.contract_level / s.contracts as f64);
    println!(
        "A declared            {:.1}%  (made {:.1}%)",
        100.0 * s.declared / s.n,
        100.0 * s.made / s.declared.max(1.0)
    );
    println!("A overtook            {:.1}%", 100.0 * s.overtook / s.n);
    println!("A sacrificed          {:.1}%", 100.0 * s.sacrificed / s.n);
    println!(
        "contracts doubled     {:.1}%  (of those, declarer still made {:.1}%)",
        100.0 * s.doubled / s.contracts as f64,
        100.0 * s.doubled_made / s.doubled.max(1.0)
    );
    println!("opened in BEST denom  {:.1}%", 100.0 * s.open_best_denom / s.opened.max(1.0));
    if cfg.allow_open_pass {
        println!("hands thrown in       {:.1}%  (both players declined)", 100.0 * s.thrown_in / s.n);
    }
    if cfg.over > 0 {
        println!(
            "mean forced overshoot {:.2} pts on made contracts (penalty {}/pt)",
            s.overshoot / s.overshoot_n.max(1.0),
            cfg.over
        );
    }
    hist("OPENING level (A only)", &s.open_level, None);
    hist("SETTLED CONTRACT level (all contracts)", &s.clevel, Some(&s.cmade));

    println!("
-- OPENED (row) -> SETTLED (col), all contracts --");
    print!("  open |");
    for j in 0..9 {
        print!(" {:>4}", j);
    }
    println!("   | total");
    for i in 0..9 {
        let tot: u64 = s.o2s[i].iter().sum();
        if tot == 0 {
            continue;
        }
        print!("  {:>4} |", i);
        for j in 0..9 {
            if s.o2s[i][j] == 0 {
                print!("    .");
            } else {
                print!(" {:>4}", s.o2s[i][j]);
            }
        }
        println!("   | {:>4}", tot);
    }

    println!("
-- bids in the auction (1 = opened and passed out) --");
    let bt: u64 = s.bids.iter().sum();
    for i in 0..12 {
        if s.bids[i] == 0 {
            continue;
        }
        println!("  {:>2} bids  {:>5}  ({:5.1}%)", i, s.bids[i], 100.0 * s.bids[i] as f64 / bt as f64);
    }
}
