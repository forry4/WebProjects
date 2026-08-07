//! Emits card-play fixtures for the Python port to replay.
//!
//! `games/dissonance/engine.py` is a hand port of `state.rs`. Two independent
//! implementations of the same rules drift silently, so this writes complete
//! playthroughs -- the exact deal, every card in order, and the resulting
//! points -- and `games/dissonance/tests/test_rust_parity.py` replays them and
//! demands identical results.
//!
//! The deal is written out explicitly rather than as a seed: the two languages
//! have different RNGs, so a shared seed would prove nothing.
//!
//!   gen_fixtures [games] > games/dissonance/tests/fixtures/play.jsonl

use dissonance::cards::NOTRUMP;
use dissonance::game::Game;
use dissonance::rng::Rng;
use dissonance::state::POOL;

fn main() {
    let n: usize = std::env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(400);

    for i in 0..n as u64 {
        let mut rng = Rng::new(i + 1);
        let trump = (rng.next_u64() % 5) as u8;
        let leader = (rng.next_u64() % 2) as u8;
        let mut g = Game::deal(&mut Rng::new(i + 1), trump, leader);

        // The dealt layout, before a card is played.
        let mut hands = String::new();
        for p in 0..2 {
            let mut v: Vec<String> = Vec::new();
            let mut m = g.s.hand[p];
            while m != 0 {
                v.push((m.trailing_zeros()).to_string());
                m &= m - 1;
            }
            if p == 1 {
                hands.push(',');
            }
            hands.push_str(&format!("[{}]", v.join(",")));
        }
        let mut piles = String::new();
        for p in 0..2 {
            if p == 1 {
                piles.push(',');
            }
            let mut ps: Vec<String> = Vec::new();
            for i in 0..3 {
                let pl = &g.s.pile[p][i];
                ps.push(format!("[{},{}]", pl.c[0], pl.c[1]));
            }
            piles.push_str(&format!("[{}]", ps.join(",")));
        }
        let mut out: Vec<String> = Vec::new();
        let mut m = g.out;
        while m != 0 {
            out.push((m.trailing_zeros()).to_string());
            m &= m - 1;
        }

        // Play it out with a reproducible pseudo-random legal move each ply,
        // so the fixture exercises odd lines rather than only sensible ones.
        let mut moves: Vec<String> = Vec::new();
        let mut r = Rng::new(0xF1_1E ^ (i + 1));
        while !g.over() {
            let mut buf = [0u8; 16];
            let k = g.s.legal(&mut buf);
            let c = buf[r.below(k)];
            moves.push(c.to_string());
            g.apply(c);
        }

        assert_eq!(g.s.pts[0] + g.s.pts[1], POOL);
        println!(
            "{{\"hands\":[{}],\"piles\":[{}],\"out\":[{}],\"trump\":{},\"leader\":{},\
             \"moves\":[{}],\"pts\":[{},{}]}}",
            hands,
            piles,
            out.join(","),
            if trump >= NOTRUMP { 4 } else { trump },
            leader,
            moves.join(","),
            g.s.pts[0],
            g.s.pts[1]
        );
    }
}
