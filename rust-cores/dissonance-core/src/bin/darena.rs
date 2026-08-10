//! Does the dummy search beat the policy it would replace?
//!
//! The ship criterion, and it comes before any serving plumbing: if a searching
//! tier does not beat `greedy` there is nothing to serve. CRN-paired -- every
//! deal is played TWICE with the sides swapped, so the cards cancel and what is
//! left is the bot. The mirror (the same config against itself) must read
//! exactly 0.000 or the harness is measuring its own asymmetry, which is the
//! error `bin/cmatch` was caught making by seeding bots by identity.
//!
//! FULL INFORMATION, deliberately: no determinization yet, so this is the
//! search's ceiling rather than its served strength. A config that cannot win
//! here cannot win with sampling noise on top.
//!
//!     cargo run --release --bin darena -- [deals]

use dissonance::dummy::*;

#[derive(Clone, Copy)]
enum Bot {
    Greedy,
    Search(u8, Leaf),
}

fn pick(b: Bot, g: &State3) -> u8 {
    match b {
        Bot::Greedy => greedy_pick_pub(g),
        Bot::Search(d, leaf) => {
            let mut s = Search::new(leaf);
            let r = s.root(g, d);
            let side = g.side_of(g.to_play());
            // `root` values are SIDE 0's differential, so side 1 minimises.
            r.iter()
                .copied()
                .reduce(|a, b| {
                    let better = if side == 0 { b.1 > a.1 } else { b.1 < a.1 };
                    if better { b } else { a }
                })
                .map(|x| x.0)
                .unwrap()
        }
    }
}

/// One deal, `bots[s]` playing side s. Returns side 0's differential.
fn play(seed: u64, bots: [Bot; 2]) -> i32 {
    let mut g = deal(seed);
    while !g.done() {
        let side = g.side_of(g.to_play()) as usize;
        let c = pick(bots[side], &g);
        g.play(c);
    }
    (g.pts[0] - g.pts[1]) as i32
}

fn arena(n: u64, a: Bot, b: Bot) -> (f64, f64) {
    let mut tot = 0.0;
    let mut sq = 0.0;
    for seed in 1..=n {
        // CRN: the same deal both ways round, so the cards cancel exactly.
        let d1 = play(seed, [a, b]) as f64;
        let d2 = -(play(seed, [b, a]) as f64);
        let paired = (d1 + d2) / 2.0;
        tot += paired;
        sq += paired * paired;
    }
    let mean = tot / n as f64;
    let var = (sq / n as f64 - mean * mean).max(0.0);
    (mean, 1.96 * (var / n as f64).sqrt())
}

fn main() {
    let n: u64 = std::env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(120);
    let (m, e) = arena(n, Bot::Search(2, Leaf::Material), Bot::Search(2, Leaf::Material));
    println!("mirror (must be exactly 0.000): {:+.4} +- {:.3}", m, e);
    println!("\n{:>26} {:>10} {:>9}   (points/round to the searcher)", "config vs greedy", "edge", "+-");
    for (name, bot) in [
        ("depth 1, material", Bot::Search(1, Leaf::Material)),
        ("depth 2, material", Bot::Search(2, Leaf::Material)),
        ("depth 3, material", Bot::Search(3, Leaf::Material)),
        ("depth 1, playout", Bot::Search(1, Leaf::Playout)),
        ("depth 2, playout", Bot::Search(2, Leaf::Playout)),
    ] {
        let (m, e) = arena(n, bot, Bot::Greedy);
        println!("{:>26} {:>+10.3} {:>9.3}", name, m, e);
    }
    println!("\n{:>26} {:>10} {:>9}   (positive = the first one is better)", "head to head", "edge", "+-");
    let (m, e) = arena(n, Bot::Search(2, Leaf::Playout), Bot::Search(3, Leaf::Material));
    println!("{:>26} {:>+10.3} {:>9.3}", "d2 playout vs d3 material", m, e);
}
