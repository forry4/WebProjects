//! Round driver: deals, steps players through the 13 tricks, tracks the public
//! record. Holds ground truth — bots only ever receive a `View`, so a bot
//! cannot read hidden cards even by accident.

use crate::cards::*;
use crate::rng::Rng;
use crate::state::*;
use crate::view::{Knowledge, View};

pub struct Game {
    pub s: State,
    /// Cards played to completed or in-progress tricks.
    pub played: Mask,
    pub kn: Knowledge,
    /// The two cards dealt out of play, revealed only at the end of the round.
    pub out: Mask,
    /// Every play so far as (mover, card, source), where source is 0 for the
    /// hand and 1..=3 for a pile. ALL of this is public - everyone sees which
    /// pile shrank - which is what makes it usable for inference.
    pub history: Vec<(u8, u8, u8)>,
    pub first_leader: u8,
}

impl Game {
    /// `trump` is 0..3 or `NOTRUMP`; `leader` opens trick 1 (in the full game
    /// that is the defender).
    pub fn deal(rng: &mut Rng, trump: u8, leader: u8) -> Game {
        let mut deck: [u8; 28] = [0; 28];
        for i in 0..28 {
            deck[i] = i as u8;
        }
        rng.shuffle(&mut deck);

        let mut s = State {
            hand: [0; 2],
            pile: [[Pile::default(); 3]; 2],
            trump,
            trick: 0,
            leader,
            led: -1,
            pts: [0; 2],
        };
        let mut k = 0;
        for p in 0..2 {
            for _ in 0..7 {
                s.hand[p] |= 1 << deck[k];
                k += 1;
            }
            for i in 0..3 {
                s.pile[p][i] = Pile::new(deck[k], deck[k + 1]);
                k += 2;
            }
        }
        let out = (1 << deck[26]) | (1 << deck[27]);
        Game {
            s,
            played: 0,
            kn: Knowledge::default(),
            out,
            history: Vec::with_capacity(26),
            first_leader: leader,
        }
    }

    pub fn view(&self, p: usize) -> View {
        View::of(self, p)
    }

    pub fn apply(&mut self, c: u8) {
        let mover = self.s.to_play() as usize;
        debug_assert!({
            let mut m = [0u8; 16];
            let n = self.s.legal(&mut m);
            m[..n].contains(&c)
        });
        self.kn.observe(&self.s, mover, c);
        // `State::remove` checks the hand before the piles, so the recorded
        // source must resolve ties the same way or a replay diverges.
        let mut source = 0u8;
        if self.s.hand[mover] & (1 << c) == 0 {
            for i in 0..3 {
                if self.s.pile[mover][i].top() == Some(c) {
                    source = i as u8 + 1;
                    break;
                }
            }
        }
        self.history.push((mover as u8, c, source));
        self.played |= 1 << c;
        self.s.play(c);
    }

    pub fn over(&self) -> bool {
        self.s.done()
    }
}

pub trait Bot {
    fn pick(&mut self, v: &View) -> u8;
    fn name(&self) -> String;
    /// Hook for the cheating oracle only. Every honest bot leaves this alone,
    /// so "does this bot see hidden cards" is answerable by grepping for it.
    fn observe_truth(&mut self, _s: &State) {}
}

/// Play one round to the end. Returns both players' point totals.
pub fn play_round(g: &mut Game, bots: &mut [&mut dyn Bot; 2]) -> [i8; 2] {
    while !g.over() {
        let p = g.s.to_play() as usize;
        let v = g.view(p);
        bots[p].observe_truth(&g.s);
        let c = bots[p].pick(&v);
        g.apply(c);
    }
    debug_assert_eq!(g.s.pts[0] + g.s.pts[1], POOL);
    g.s.pts
}
