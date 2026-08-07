//! The rules. Single source of truth — every bot and the solver drive this.
//!
//! Setup per player: 7 cards in hand + 3 piles of 2 on the table = 13 cards,
//! 13 tricks. Only a pile's TOP card is playable; the card beneath becomes
//! playable (and public) once the top is gone.
//!
//! Scoring: trick 2,4,6,8,10,12 are worth +2 to the winner; tricks
//! 1,3,5,7,9,11,13 are worth -1. Six positive and seven negative tricks, so
//! the two players' totals always sum to exactly +5 — the game is
//! constant-sum, which is why the solver can minimax a single number.
//!
//! Follow-suit is MANDATORY, and a pile top counts as a card you hold for
//! that purpose. (Optional-follow was considered and rejected: it makes every
//! odd trick fall deterministically to whoever leads it.)

use crate::cards::*;

/// One face-down stack of at most two cards. `c[0]` is the bottom.
/// Invariant: slots at or above `n` are zeroed, so equal piles compare and
/// hash equal.
#[derive(Clone, Copy, PartialEq, Eq, Debug, Default)]
pub struct Pile {
    pub c: [u8; 2],
    pub n: u8,
}

impl Pile {
    #[inline(always)]
    pub fn top(&self) -> Option<u8> {
        if self.n == 0 {
            None
        } else {
            Some(self.c[(self.n - 1) as usize])
        }
    }

    /// The covered card, if there is one.
    #[inline(always)]
    pub fn covered(&self) -> Option<u8> {
        if self.n == 2 {
            Some(self.c[0])
        } else {
            None
        }
    }

    #[inline(always)]
    fn pop(&mut self) {
        self.n -= 1;
        self.c[self.n as usize] = 0;
    }

    pub fn new(bottom: u8, top: u8) -> Self {
        Pile {
            c: [bottom, top],
            n: 2,
        }
    }
}

/// The trick-play position. Copy-able and ~32 bytes, so the solver just clones
/// per node rather than doing make/unmake.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct State {
    pub hand: [Mask; 2],
    pub pile: [[Pile; 3]; 2],
    /// 0..3 = trump suit, 4 = no-trump.
    pub trump: u8,
    /// 0-indexed trick being played; trick 0 is "trick 1" on the score sheet.
    pub trick: u8,
    pub leader: u8,
    /// Card led this trick, or -1 if nobody has played yet.
    pub led: i8,
    pub pts: [i8; 2],
    /// Bit p set once player p has won a +2 trick.
    ///
    /// A COUNT would be redundant -- nothing asks how many -- but the bit is
    /// not derivable from `pts`, which is the whole reason it is here: a total
    /// of -1 is one +2 trick and three -1s just as easily as it is one -1 and
    /// nothing else. Since 2026-08-07 a declarer who never wins a +2 trick
    /// scores the Null consolation instead of being set, so the payoff has a
    /// cliff at exactly this bit and a solver optimising points cannot see it.
    pub escored: u8,
}

/// Which parity of trick NUMBER scores +2. Default: even-numbered tricks.
#[cfg(feature = "odd-positive")]
pub const POSITIVE_IS_ODD: bool = true;
#[cfg(not(feature = "odd-positive"))]
pub const POSITIVE_IS_ODD: bool = false;

/// Value of the (0-indexed) trick. `trick` 0 is trick NUMBER 1.
#[inline(always)]
pub const fn trick_value(trick: u8) -> i8 {
    let odd_numbered = trick % 2 == 0;
    if odd_numbered == POSITIVE_IS_ODD {
        2
    } else {
        -1
    }
}

const fn compute_pool() -> i8 {
    let mut s = 0i8;
    let mut t = 0u8;
    while t < NTRICKS {
        s += trick_value(t);
        t += 1;
    }
    s
}

/// Total of both players' scores at the end of any complete round. 6 positive
/// and 7 negative tricks gives +5; flipped it is 7 positive and 6 negative,
/// giving +8.
pub const POOL: i8 = compute_pool();

pub const NTRICKS: u8 = 13;

/// Does `follow` beat `led`, given the trump denomination?
#[inline(always)]
pub fn beats(led: u8, follow: u8, trump: u8) -> bool {
    let ls = suit(led);
    let fs = suit(follow);
    if fs == ls {
        return rank(follow) > rank(led);
    }
    if trump < NOTRUMP {
        // Different suits: only a ruff can win, and only if the lead wasn't trump.
        return fs == trump && ls != trump;
    }
    false
}

impl State {
    #[inline(always)]
    pub fn to_play(&self) -> u8 {
        if self.led < 0 {
            self.leader
        } else {
            1 - self.leader
        }
    }

    #[inline(always)]
    pub fn done(&self) -> bool {
        self.trick >= NTRICKS
    }

    /// Every card `p` could legally reach right now, ignoring follow-suit.
    #[inline(always)]
    pub fn playable(&self, p: usize) -> Mask {
        let mut m = self.hand[p];
        for i in 0..3 {
            if let Some(c) = self.pile[p][i].top() {
                m |= 1 << c;
            }
        }
        m
    }

    /// Every card still held by either player (not yet played, not out of play).
    #[inline(always)]
    pub fn in_play(&self) -> Mask {
        let mut m = self.hand[0] | self.hand[1];
        for q in 0..2 {
            for i in 0..3 {
                let p = &self.pile[q][i];
                for k in 0..p.n as usize {
                    m |= 1 << p.c[k];
                }
            }
        }
        m
    }

    /// Legal cards for the player to move, written into `out`; returns the count.
    /// At most 10 (7 hand + 3 pile tops).
    #[inline]
    pub fn legal(&self, out: &mut [u8; 16]) -> usize {
        let p = self.to_play() as usize;
        let mut m = self.playable(p);
        if self.led >= 0 {
            let f = m & SUIT_MASK[suit(self.led as u8) as usize];
            if f != 0 {
                m = f;
            }
        }
        let mut n = 0;
        while m != 0 {
            out[n] = m.trailing_zeros() as u8;
            m &= m - 1;
            n += 1;
        }
        n
    }

    #[inline]
    fn remove(&mut self, p: usize, c: u8) {
        let b: Mask = 1 << c;
        if self.hand[p] & b != 0 {
            self.hand[p] &= !b;
            return;
        }
        for i in 0..3 {
            if self.pile[p][i].top() == Some(c) {
                self.pile[p][i].pop();
                return;
            }
        }
        panic!("illegal card {} for player {}", card_name(c), p);
    }

    /// Play `c` for the player to move. Returns the points this ply added to
    /// the differential (player 0's perspective) — non-zero only when the card
    /// completes a trick.
    #[inline]
    pub fn play(&mut self, c: u8) -> i8 {
        let p = self.to_play() as usize;
        self.remove(p, c);
        if self.led < 0 {
            self.led = c as i8;
            return 0;
        }
        let led = self.led as u8;
        let winner = if beats(led, c, self.trump) {
            p as u8
        } else {
            self.leader
        };
        let v = trick_value(self.trick);
        self.pts[winner as usize] += v;
        if v > 0 {
            self.escored |= 1 << winner;
        }
        self.trick += 1;
        self.leader = winner;
        self.led = -1;
        if winner == 0 {
            v
        } else {
            -v
        }
    }
}
