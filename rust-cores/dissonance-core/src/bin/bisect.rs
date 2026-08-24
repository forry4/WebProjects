//! Isolates a solver value regression to a single technique.

use dissonance::dd::Dd;
use dissonance::game::Game;
use dissonance::rng::Rng;
use dissonance::state::State;

fn naive(s: &State) -> i16 {
    if s.done() {
        return 0;
    }
    let mut m = [0u8; 16];
    let n = s.legal(&mut m);
    let maxing = s.to_play() == 0;
    let mut best: i16 = if maxing { -64 } else { 64 };
    for i in 0..n {
        let mut t = *s;
        let g = t.play(m[i]) as i16;
        let v = g + naive(&t);
        best = if maxing { best.max(v) } else { best.min(v) };
    }
    best
}

fn main() {
    let combos = [
        ("plain            ", false, false, false),
        ("+equiv           ", false, false, true),
        ("+bounds          ", true, false, false),
        ("+mtdf            ", false, true, false),
        ("all              ", true, true, true),
    ];
    let mut bad = vec![0usize; combos.len()];
    let mut n = 0;
    for seed in 0..40u64 {
        let mut g = Game::deal(&mut Rng::new(seed), (seed % 5) as u8, (seed % 2) as u8);
        let mut r = Rng::new(seed ^ 0xABCD);
        while g.s.trick < 8 {
            let mut m = [0u8; 16];
            let k = g.s.legal(&mut m);
            g.apply(m[r.below(k)]);
        }
        let truth = naive(&g.s);
        n += 1;
        for (i, &(_, b, m, e)) in combos.iter().enumerate() {
            let mut dd = Dd::new(16);
            dd.use_bounds = b;
            dd.use_mtdf = m;
            dd.use_equiv = e;
            if dd.solve(&g.s) != truth {
                bad[i] += 1;
            }
        }
    }
    for (i, c) in combos.iter().enumerate() {
        println!("{}  wrong on {}/{}", c.0, bad[i], n);
    }
}
