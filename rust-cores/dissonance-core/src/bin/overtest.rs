//! Does a penalty for exceeding the contract have any teeth?
//!
//! The worry: a declarer who can make N+3 can usually just THROTTLE -- throw
//! tricks deliberately and finish on exactly N -- in which case an
//! over-penalty never fires and the whole idea is decoration. It only bites
//! when the DEFENDER can force unwanted winners onto the declarer.
//!
//! This measures exactly that. For each deal it finds the declarer's maximum
//! achievable total M, then for contracts at M, M-1, M-2, M-3 it solves the
//! game where the declarer's first priority is making the contract and second
//! priority is finishing as close to it as possible. The forced overshoot is
//! whatever they cannot shed.
//!
//!   overtest [deals] [threads]

use dissonance::dd::{Contract, Dd};
use dissonance::game::Game;
use dissonance::rng::Rng;
use dissonance::state::{State, POOL};

const BIG: i32 = 100_000;

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let deals: usize = a.first().and_then(|s| s.parse().ok()).unwrap_or(60);
    let threads: usize = a
        .get(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(
            std::thread::available_parallelism()
                .map(|n| n.get())
                .unwrap_or(4)
                .saturating_sub(1)
                .max(1),
        );

    let per = deals.div_ceil(threads);
    // For each slack (0..=3): [total cases, cases with a forced overshoot,
    // total forced overshoot, cases that could not even be made]
    let res: Vec<[[i64; 4]; 4]> = std::thread::scope(|sc| {
        let mut hs = Vec::new();
        for t in 0..threads {
            hs.push(sc.spawn(move || {
                let mut dd = Dd::new(20);
                let mut acc = [[0i64; 4]; 4];
                for i in 0..per {
                    let idx = t * per + i;
                    if idx >= deals {
                        break;
                    }
                    let seed = idx as u64 + 1;
                    for declarer in 0..2usize {
                        for den in 0..5u8 {
                            let g = Game::deal(&mut Rng::new(seed), den, 1 - declarer as u8);
                            let base = State {
                                trump: den,
                                trick: 0,
                                led: -1,
                                leader: 1 - declarer as u8,
                                pts: [0, 0],
                                ..g.s
                            };
                            // Maximum the declarer can take, playing greedily
                            // for points -- the current solver's objective.
                            dd.clear();
                            let diff = dd.solve(&base) as i32;
                            let p0 = (POOL as i32 + diff) / 2;
                            let max_pts = if declarer == 0 { p0 } else { POOL as i32 - p0 };

                            // Rows 0-1: bid AT your maximum, and one under.
                            // Rows 2-3: the TRAP bids -- absolute levels 1 and
                            // 2, far below what the hand is worth.
                            let levels = [max_pts, max_pts - 1, 1, 2];
                            for (si, level) in levels.into_iter().enumerate() {
                                // Priority 1: make it. Priority 2: land on it.
                                let c = Contract {
                                    level,
                                    declarer,
                                    make_base: 0,
                                    over: 1,
                                    set_base: BIG,
                                    short: 0,
                                    null: None,
                                };
                                dd.clear();
                                let v = dd.solve_contract(&base, &c);
                                acc[si][0] += 1;
                                if v <= -BIG {
                                    acc[si][3] += 1; // cannot even be made
                                } else {
                                    let overshoot = -v;
                                    if overshoot > 0 {
                                        acc[si][1] += 1;
                                        acc[si][2] += overshoot as i64;
                                    }
                                }
                            }
                        }
                    }
                }
                acc
            }));
        }
        hs.into_iter().map(|h| h.join().unwrap()).collect()
    });

    let mut acc = [[0i64; 4]; 4];
    for r in res {
        for i in 0..4 {
            for j in 0..4 {
                acc[i][j] += r[i][j];
            }
        }
    }

    println!("deals {} (x2 declarers x5 denominations)\n", deals);
    println!("contract set at (max achievable - slack); declarer tries to make it");
    println!("and then to land on it exactly.\n");
    println!("  contract        | cases | forced to overshoot | mean overshoot | unmakeable");
    for (si, slack) in ["max", "max-1", "level 1", "level 2"].into_iter().enumerate() {
        let [tot, forced, sum, bad] = acc[si];
        println!(
            "  {:>15} | {:>5} | {:>8} ({:5.1}%)  | {:>13.2} | {:>4}",
            slack,
            tot,
            forced,
            100.0 * forced as f64 / tot as f64,
            if forced > 0 { sum as f64 / forced as f64 } else { 0.0 },
            bad
        );
    }
    println!(
        "\nIf 'forced to overshoot' is near 0%, the declarer can always throttle\nand an over-penalty is decoration."
    );
}
