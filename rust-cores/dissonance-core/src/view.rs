//! What one player actually knows, and how to sample deals consistent with it.
//!
//! Hidden from a player at the start of a round: the opponent's 7 hand cards,
//! all four covered SIDE-pile bottoms (including their own two), and the 2
//! cards out of play — 13 unknowns against 15 knowns.
//!
//! Void inference has a wrinkle worth stating, because it is a real
//! consequence of the pile rule: failing to follow suit proves the player had
//! no card of that suit *among hand + pile tops*. Hands only ever shrink, so
//! the hand void is permanent and safe to assert forever. But a covered pile
//! bottom may still be that suit, and will become playable later. Piles
//! launder voids — the inference is strictly weaker than in a plain
//! trick-taking game, and asserting it over the whole holding would be wrong.

use crate::cards::*;
use crate::game::Game;
use crate::rng::Rng;
use crate::state::*;

#[derive(Clone, Copy, Default, Debug)]
pub struct Knowledge {
    /// `hand_void[p][s]` — player p is known to hold no `s` IN HAND.
    pub hand_void: [[bool; 4]; 2],
}

impl Knowledge {
    /// Call after every card is played, before the state advances.
    pub fn observe(&mut self, s: &State, mover: usize, played_card: u8) {
        if s.led >= 0 {
            let ls = suit(s.led as u8);
            if suit(played_card) != ls {
                self.hand_void[mover][ls as usize] = true;
            }
        }
    }
}

/// A position as one player sees it. Unknown pile bottoms carry `UNKNOWN`;
/// the opponent's hand is an empty mask plus a count.
#[derive(Clone)]
pub struct View {
    pub me: usize,
    pub s: State,
    pub opp_hand_n: u32,
    /// Cards the observer cannot place: opponent's hand, covered side-pile
    /// bottoms (theirs and their own), and the two out of play.
    pub pool: Mask,
    pub kn: Knowledge,
    /// Public record of the round so far, for inference.
    pub history: Vec<(u8, u8, u8)>,
    pub first_leader: u8,
    /// Out-of-play cards still unidentified, i.e. how much of `pool` belongs
    /// to nobody. Not `NOUT` when some out-cards were dealt face up.
    pub n_out_hidden: u32,
}

/// Cards visible to both players: every pile top, plus the middle pile's
/// bottom, which is dealt face-up.
fn public_pile_cards(s: &State) -> Mask {
    let mut m = 0;
    for q in 0..2 {
        for i in 0..3 {
            let p = &s.pile[q][i];
            if let Some(c) = p.top() {
                m |= 1 << c;
            }
            if i == 1 {
                if let Some(c) = p.covered() {
                    m |= 1 << c;
                }
            }
        }
    }
    m
}

impl View {
    pub fn of(g: &Game, me: usize) -> View {
        let truth = &g.s;
        let opp = 1 - me;
        let known = truth.hand[me] | public_pile_cards(truth) | g.out_public;
        let mut s = *truth;
        s.hand[opp] = 0;
        for q in 0..2 {
            for i in [0usize, 2] {
                if s.pile[q][i].n == 2 {
                    s.pile[q][i].c[0] = UNKNOWN;
                }
            }
        }
        View {
            me,
            s,
            opp_hand_n: truth.hand[opp].count_ones(),
            pool: ALL & !g.played & !known,
            kn: g.kn,
            history: g.history.clone(),
            first_leader: g.first_leader,
            n_out_hidden: NOUT as u32 - g.out_public.count_ones(),
        }
    }

    /// Legal moves for the observer — unaffected by the hidden cards, since
    /// everything the observer can play is something the observer can see.
    pub fn legal(&self, out: &mut [u8; 16]) -> usize {
        self.s.legal(out)
    }

    /// Covered side-pile slots that need filling, as (player, pile index).
    pub fn hidden_slots(&self) -> ([(usize, usize); 4], usize) {
        let mut slots = [(0usize, 0usize); 4];
        let mut n = 0;
        for q in 0..2 {
            for i in [0usize, 2] {
                if self.s.pile[q][i].n == 2 {
                    slots[n] = (q, i);
                    n += 1;
                }
            }
        }
        (slots, n)
    }

    /// A complete deal consistent with everything the observer knows.
    pub fn determinize(&self, rng: &mut Rng, buf: &mut Vec<u8>) -> State {
        let opp = 1 - self.me;
        let (slots, nslots) = self.hidden_slots();

        let nh = self.opp_hand_n as usize;
        debug_assert_eq!(
            self.pool.count_ones() as usize,
            nh + nslots + self.n_out_hidden as usize,
            "pool must be exactly the unplaceable cards"
        );

        // Partition the pool by whether a card may sit in the opponent's hand.
        let voids = self.kn.hand_void[opp];
        buf.clear();
        let mut m = self.pool;
        let mut n_allowed = 0;
        while m != 0 {
            let c = m.trailing_zeros() as u8;
            m &= m - 1;
            if !voids[suit(c) as usize] {
                buf.insert(n_allowed, c);
                n_allowed += 1;
            } else {
                buf.push(c);
            }
        }

        // Uniform over consistent deals: pick the hand uniformly from the
        // allowed prefix, then scatter the remainder uniformly.
        if n_allowed >= nh {
            rng.partial_shuffle(&mut buf[..n_allowed], nh);
            let tail = buf.len();
            rng.shuffle(&mut buf[nh..tail]);
        } else {
            // Unreachable if the inference is sound; degrade rather than hang.
            rng.shuffle(&mut buf[..]);
        }

        let mut d = self.s;
        let mut hm: Mask = 0;
        for &c in &buf[..nh] {
            hm |= 1 << c;
        }
        d.hand[opp] = hm;
        for k in 0..nslots {
            let (q, i) = slots[k];
            d.pile[q][i].c[0] = buf[nh + k];
        }
        d
    }
}
