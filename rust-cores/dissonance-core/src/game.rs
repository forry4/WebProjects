//! Round driver: deals, steps players through the 13 tricks, tracks the public
//! record. Holds ground truth — bots only ever receive a `View`, so a bot
//! cannot read hidden cards even by accident.

use crate::cards::*;
use crate::rng::Rng;
use crate::state::*;
use crate::view::{Knowledge, View};

/// `Clone` so a caller can build a view over a WIDER public set than the deal
/// has — `skatlab` copies a game with `out_public = out_shown` to get the
/// declarer's post-look beliefs, in which the three talon cards are known out
/// of play rather than possibly in the opponent's hand.
#[derive(Clone)]
pub struct Game {
    pub s: State,
    /// Cards played to completed or in-progress tricks.
    pub played: Mask,
    pub kn: Knowledge,
    /// The cards dealt out of play, revealed only at the end of the round.
    pub out: Mask,
    /// The subset of `out` turned face up at the deal instead. This is the
    /// CONTROL for the deck-width sweep: widening the deck adds out-of-play
    /// cards, but it also thins each suit, and those are two different effects
    /// on the game. Revealing k of the out-cards leaves the deck, the suit
    /// lengths and the ruffing frequency exactly as they were while removing
    /// the hidden information those cards carried, so the difference between
    /// `out_public = 0` and `out_public = NOUT` at the SAME deck width is the
    /// hidden information alone.
    pub out_public: Mask,
    /// The subset of `out` the DECLARER is shown after winning the auction,
    /// and from which they may take one card into hand. Fixed at the deal so
    /// that it does not depend on who wins -- but revealed to that player
    /// only, so it is an asymmetric information advantage as well as a
    /// hand-quality one. The defender knows a swap happened and nothing else.
    pub out_shown: Mask,
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
        Game::deal_with(rng, trump, leader, 0)
    }

    /// As `deal`, but shows `n_shown` of the out-of-play cards to whoever wins
    /// the auction.
    pub fn deal_shown(rng: &mut Rng, trump: u8, leader: u8, n_shown: usize) -> Game {
        Game::deal_full(rng, trump, leader, 0, n_shown)
    }

    /// As `deal`, but turns `n_public` of the out-of-play cards face up at the
    /// deal. `n_public == 0` is the shipped game.
    pub fn deal_with(rng: &mut Rng, trump: u8, leader: u8, n_public: usize) -> Game {
        Game::deal_full(rng, trump, leader, n_public, 0)
    }

    pub fn deal_full(
        rng: &mut Rng,
        trump: u8,
        leader: u8,
        n_public: usize,
        n_shown: usize,
    ) -> Game {
        let mut deck = [0u8; NCARD as usize];
        for i in 0..NCARD as usize {
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
            escored: 0,
            // The offline labs and the fixture generator run the classic
            // parity; a caller wanting minor sets `g.s.even` after the deal,
            // and one wanting card scoring sets `g.s.cards` (the deal itself
            // is scoring-independent).
            even: 2,
            cards: false,
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
        let mut out: Mask = 0;
        let mut out_public: Mask = 0;
        for (j, &c) in deck[k..].iter().enumerate() {
            out |= 1 << c;
            if j < n_public {
                out_public |= 1 << c;
            }
        }
        debug_assert_eq!(out.count_ones(), NOUT as u32);
        let mut out_shown: Mask = 0;
        for (j, &c) in deck[k..].iter().enumerate() {
            if j < n_shown.min(NOUT as usize) {
                out_shown |= 1 << c;
            }
        }
        Game {
            s,
            played: 0,
            kn: Knowledge::default(),
            out,
            out_public,
            out_shown,
            history: Vec::with_capacity(2 * NDEALT as usize),
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
    debug_assert_eq!(g.s.pts[0] + g.s.pts[1], g.s.pool());
    g.s.pts
}
