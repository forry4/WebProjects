//! WHAT THE SHIPPED DEFENCE ACTUALLY CONCEDES (2026-08-14).
//!
//! `nulldeny` gives the ceiling: double dummy, a declarer can FORCE the
//! consolation only ~3.5% of the time. This asks what the tier the browser
//! runs concedes against a declarer genuinely trying for it -- the shape of
//! the complaint "Hard/Expert concede too many Nulls to me".
//!
//! The declarer plays the DUCKING line by exact search (`null_no_even_makeable`
//! per candidate: play any card that keeps a no-scoring-trick line alive),
//! which is the strongest possible run at it. The defender is `PimcBot` with
//! the CONTRACT set, i.e. exactly what a Hard/Expert browser runs.
//!
//!   nullbot [--deals N] [--k K]
use dissonance::bots::PimcBot;
use dissonance::game::Bot;
use dissonance::cards::NOTRUMP;
use dissonance::dd::{Contract, Dd};
use dissonance::game::Game;
use dissonance::rng::Rng;

fn flag(a: &[String], n: &str) -> Option<String> {
    a.iter().position(|x| x == n).and_then(|i| a.get(i + 1)).cloned()
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let deals: usize = flag(&args, "--deals").and_then(|s| s.parse().ok()).unwrap_or(150);
    let k: usize = flag(&args, "--k").and_then(|s| s.parse().ok()).unwrap_or(8);
    let level = 6;                       // a contract gone wrong: the duck case
    let mut rng = Rng::new(0x5EED_1234);
    let mut dd = Dd::new(20);
    let (mut got, mut forced, mut n) = (0usize, 0usize, 0usize);
    for d in 0..deals {
        for declarer in 0..2usize {
            let g = Game::deal(&mut rng, NOTRUMP, declarer as u8);
            let c = Contract { level, declarer, make_base: level * level + 10, over: 1,
                               set_base: level + 10, short: 5, ramp: 0, null: Some(20) };
            n += 1;
            if dd.null_no_even_makeable(&g.s, declarer) { forced += 1; }
            let mut def = PimcBot::new(k, 0xB07 ^ (d as u64), 20);
            def.contract = Some(c);
            let mut g = g;
            while !g.s.done() {
                let me = g.s.to_play() as usize;
                let mut m = [0u8; 16];
                let cnt = g.s.legal(&mut m);
                let card = if me == declarer {
                    // DUCK: prefer any card that keeps a no-scoring-trick line
                    // alive; the exact search is the strongest possible try.
                    let mut best = m[0];
                    for &card in &m[..cnt] {
                        let mut t = g.s; t.play(card);
                        if dd.null_no_even_makeable(&t, declarer) { best = card; break; }
                    }
                    best
                } else {
                    def.pick(&g.view(me))
                };
                g.apply(card);
            }
            if g.s.escored & (1 << declarer) == 0 { got += 1; }
        }
    }
    println!("declarer TOOK the consolation vs the shipped defence: {got}/{n} = {:.1}%",
             100.0 * got as f64 / n as f64);
    println!("...of which double dummy it was FORCEABLE in only {forced}/{n} = {:.1}%",
             100.0 * forced as f64 / n as f64);
}
