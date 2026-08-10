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

use dissonance::cards::DENOMS;
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
        // Over DENOMS, so GRAND is in the fixtures: it is the only trump
        // under which following suit means something different, and a
        // generator that sampled 0..=NOTRUMP would leave the Python port's
        // whole Grand path ungated.
        let trump = DENOMS[(rng.next_u64() % DENOMS.len() as u64) as usize];
        let leader = (rng.next_u64() % 2) as u8;
        // Every fourth fixture plays MINOR parity (+1 evens) and every fourth
        // plays CARD SCORING (skat mode's currency since 2026-08-09), so the
        // Python port's `trick_value_in` AND `card_points` paths are gated the
        // same way Grand's trump is: by the fixtures covering them, or not at
        // all. On the index rather than the RNG so the split cannot drift
        // with an unrelated draw.
        let even: i8 = if i % 4 == 3 { 1 } else { 2 };
        let cards = i % 4 == 1;
        // MUST-HEAD IS SHELVED SERVER-SIDE (see `engine.MUST_HEAD`), so the
        // fixtures play without it -- they mirror the SHIPPED rules or they
        // gate nothing, and `test_rust_parity` asserts that agreement rather
        // than assuming it (the port derives the flag from one mode string, so
        // a fixture that disagreed would fail as a mystery illegal move).
        // The rule's own coverage is `must_head_forces_a_winner_when_one_can_
        // follow` in tests/engine.rs, which drives the flag directly.
        let head = false;
        let mut g = Game::deal(&mut Rng::new(i + 1), trump, leader);
        g.s.even = even;
        g.s.cards = cards;
        g.s.head = head;

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

        assert_eq!(g.s.pts[0] + g.s.pts[1], g.s.pool());
        if even == 2 && !cards {
            assert_eq!(g.s.pool(), POOL);
        }
        println!(
            "{{\"hands\":[{}],\"piles\":[{}],\"out\":[{}],\"trump\":{},\"leader\":{},\
             \"even\":{},\"cards\":{},\"head\":{},\"moves\":[{}],\"pts\":[{},{}]}}",
            hands,
            piles,
            out.join(","),
            // The ACTUAL trump, not clamped to 4: GRAND is 6, and a
            // fixture that flattened it to no-trump would have the Python
            // port replay a different game and agree for the wrong reason.
            trump,
            leader,
            even,
            cards,
            head,
            moves.join(","),
            g.s.pts[0],
            g.s.pts[1]
        );
    }
}
