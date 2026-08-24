//! CAN THE DEFENCE DENY THE CONSOLATION AT ALL? (2026-08-14)
//!
//! Reported from real games: "Hard/Expert concede too many Nulls to me." Before
//! that is a bot complaint it has to be a RULES question, because the answer
//! bounds what any defence could do. The shipped consolation is "the declarer
//! won no SCORING trick" -- far weaker than the old Null contract `nullprobe`
//! measures (no trick AT ALL), so that harness cannot answer this.
//!
//! `Dd::null_no_even_makeable` is the exact predicate: with both sides seeing
//! everything, can the declarer FORCE taking no scoring trick? Where it says
//! yes, no defence -- searching, cheating or otherwise -- can deny the Null,
//! and a bot conceding there is playing correctly.
//!
//!   nulldeny [--deals N]
use dissonance::cards::NOTRUMP;
use dissonance::dd::Dd;
use dissonance::game::Game;
use dissonance::rng::Rng;

fn flag(a: &[String], n: &str) -> Option<String> {
    a.iter().position(|x| x == n).and_then(|i| a.get(i + 1)).cloned()
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let deals: usize = flag(&args, "--deals").and_then(|s| s.parse().ok()).unwrap_or(300);
    let mut dd = Dd::new(18);
    let mut rng = Rng::new(0xD1550_1234);
    // Both leads, because leading is the one seat you cannot duck from and the
    // declarer leads to trick 1 in this game.
    let (mut forced, mut n) = (0usize, 0usize);
    for _ in 0..deals {
        for declarer in 0..2 {
            // The DECLARER leads to trick 1, so the deal is made with them on
            // lead -- the seat you cannot duck from, and the handicap the whole
            // consolation question turns on.
            let g = Game::deal(&mut rng, NOTRUMP, declarer as u8);
            let s = g.s;
            n += 1;
            if dd.null_no_even_makeable(&s, declarer) {
                forced += 1;
            }
        }
    }
    println!("declarer can FORCE the consolation (no scoring trick), double dummy, \
              from trick 1: {forced}/{n} = {:.1}%", 100.0 * forced as f64 / n as f64);
    println!("...so a defence that concedes at about that rate is not losing anything.");
}
