//! Times an exact solve of a full 13-trick deal from trick 1 — the inner loop
//! everything else is built on.
//!
//!   bench [deals] [tt_bits]

use dissonance::bots::*;
use dissonance::cards::*;
use dissonance::dd::Dd;
use dissonance::game::{Bot, Game};
use dissonance::rng::Rng;
use std::time::Instant;

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    let deals: usize = a.first().and_then(|s| s.parse().ok()).unwrap_or(200);
    let bits: u32 = a.get(1).and_then(|s| s.parse().ok()).unwrap_or(20);

    let mut rng = Rng::new(0xC0FFEE);
    let mut dd = Dd::new(bits);
    let mut tot_nodes = 0u64;
    let mut tot_ms = 0f64;
    let mut worst = 0f64;
    let mut sum_val = 0i64;

    for i in 0..deals {
        let trump = (i % 5) as u8;
        let g = Game::deal(&mut rng, trump, (i % 2) as u8);
        dd.clear();
        let n0 = dd.nodes;
        let t = Instant::now();
        let v = dd.solve(&g.s);
        let ms = t.elapsed().as_secs_f64() * 1000.0;
        tot_nodes += dd.nodes - n0;
        tot_ms += ms;
        sum_val += v as i64;
        if ms > worst {
            worst = ms;
        }
    }

    println!("deals            {}", deals);
    println!("tt               2^{} ({} MB)", bits, (1usize << bits) * 16 / 1048576);
    println!("mean nodes/solve {:.0}", tot_nodes as f64 / deals as f64);
    println!("mean ms/solve    {:.3}", tot_ms / deals as f64);
    println!("worst ms         {:.3}", worst);
    println!("solves/sec       {:.0}", deals as f64 / (tot_ms / 1000.0));
    println!(
        "mean p0 value    {:+.3}   (constant-sum pool is {})",
        sum_val as f64 / deals as f64 + 0.0,
        dissonance::POOL
    );

    // A rough read on how a PIMC decision costs, since that is deals * moves.
    let mut bot = PimcBot::new(20, 7, bits);
    let mut g = Game::deal(&mut rng, 3, 0);
    let v = g.view(0);
    let t = Instant::now();
    let c = bot.pick(&v);
    println!(
        "\npimc20 first decision {:.1} ms -> {}",
        t.elapsed().as_secs_f64() * 1000.0,
        card_name(c)
    );
}
