//! DUMMY MODE — three hands, two players, the wide deck, free discard.
//!
//! Deliberately SELF-CONTAINED, and that is the load-bearing decision in this
//! file. Every other mode's search is `state.rs` + `dd.rs`, whose shapes are
//! two-seat to the bone (`hand: [Mask; 2]`, a solver that alternates two
//! players, a wire reader that partitions a two-hand pool) and which are held
//! to the Python engine by 400 committed parity fixtures and a committed wasm.
//! Generalising them to three hands would have put the three shipped modes'
//! solver at risk to serve a fourth, so this module re-states the rules it
//! needs instead. The duplication is real and is the price; what it buys is
//! that nothing in here can change what classic, skat or minor play.
//!
//! # Why this is not an exact solver, measured before it was written
//!
//! Hard is an exact double-dummy solve in every other mode (~74ms a world).
//! Dummy cannot be, and the reason is NOT the third hand. Node counts for the
//! same crude alpha-beta at k tricks remaining:
//!
//! | k | two-seat (shipped) | dummy + follow-suit | dummy, free discard |
//! |---|---|---|---|
//! | 5 | 583 | 10,392 | 30,998 |
//! | 7 | 10,282 | 183,003 | 2,430,759 |
//! | 10 | 570,342 | 18,648,672 | — |
//! | 12 | 24,182,296 | — | — |
//!
//! Extrapolated to the full 13 tricks the third hand costs about **8x** the
//! two-seat game, which would be servable. FREE DISCARD costs another ~500x on
//! top — every ply branches over the whole playable set instead of one suit —
//! putting an exact solve around 4x10^11 nodes, i.e. minutes a world against a
//! ~70ms budget. Three orders of magnitude is not an optimisation away.
//!
//! **So the per-world search here is DEPTH-LIMITED, and the campaign's own
//! numbers say that is where the strength was anyway**: `pimc:1` — one
//! perfectly EXACT world — measured +0.04 +- 0.11 against the greedy policy,
//! inside its own error bar, while `pimc:8` measured +1.10. Hard's edge is
//! averaging over uncertainty, not the exactness of any single solve. This
//! keeps the averaging and spends the per-world budget on depth instead.
//!
//! # Depth and leaf were MEASURED, and the obvious reading of it is a trap
//!
//! `bin/dbench` (cost, native release, per decision averaged over a round) and
//! `bin/darena` (strength, CRN-paired full information, mirror exactly 0.0000):
//!
//! | config | ms/decision | vs greedy |
//! |---|---|---|
//! | depth 1, material | 0.21 | +4.86 +- 1.60 |
//! | depth 2, material | 0.80 | +5.96 +- 1.53 |
//! | **depth 3, material** | **15.4** | **+9.79 +- 1.34** |
//! | depth 1, playout | 0.33 | +11.79 +- 0.84 |
//! | depth 2, playout | 9.0 | +10.61 +- 0.85 |
//! | depth 4, material | 635 | — (7.1s at trick 1: out of budget) |
//!
//! Read down the "vs greedy" column and the playout leaf wins by a street. **It
//! does not.** Head to head, depth-2-playout against depth-3-material measures
//! **-2.62 +- 0.81** — the material leaf is clearly stronger. The vs-greedy
//! column is biased because the playout leaf rolls out WITH THE GREEDY POLICY,
//! so against greedy specifically its leaf is a perfect model of the opponent.
//! That also explains the otherwise impossible depth-1-playout > depth-2-playout
//! inversion: extra search on top of an already-exact opponent model buys
//! nothing and adds minimax pessimism. Against anything but greedy the effect
//! evaporates, which is why the head-to-head is the number that decided this.
//!
//! SHIPPED: **depth 3, material leaf** — 15ms a decision, inside the ~70ms a
//! world every other mode's Hard tier lives in. The general lesson is the
//! repo's own rule with a sharper edge: a rollout leaf must never be judged
//! against the policy it rolls out with.
//!
//! # The wide deck
//!
//! Dummy deals 40 cards: the base 32 plus a 5 and a 6 in each suit, as ids
//! 32..39 so that no existing card id moves (see `engine.rank` on the Python
//! side for the full argument). `d_rank` therefore returns a STRENGTH index
//! 0..9 rather than the id's low bits, and this module never calls
//! `cards::rank` / `cards::suit`, which are right only for the base deck.
//!
//! Dummy runs CLASSIC's auction, so trump is 0..3 or no-trump — there is no
//! Grand here and no `esuit` indirection to carry.

use crate::cards::{Mask, NOTRUMP};
use crate::state::Pile;

/// Cards in the base deck. Ids below this are `suit * 8 + rank`.
pub const D_NBASE: u8 = 32;
/// Extra ranks per suit in the wide deck (the 5 and the 6).
pub const D_NEXTRA: u8 = 2;
/// The wide deck.
pub const D_NCARD: u8 = 40;
/// Rank slots, strength-ordered: 0 = the 5, 9 = the ace.
pub const D_NRANKS: usize = 10;
/// The dummy's seat POSITION. Positions 0 and 1 are the players.
pub const DUMMY_POS: u8 = 2;
/// Tricks in a dummy round — three seats of thirteen.
pub const D_NTRICKS: u8 = 13;
/// Cards a seat holds: 7 in hand + three 2-card piles.
pub const D_NDEALT: u8 = 13;

/// What capturing a card is worth, by strength rank. The wide deck's 5 and 6
/// are worth ZERO — the only inert cards in the game, which is what breaks the
/// mod-3 granularity of the contract ladder and gives free discard something
/// genuinely safe to throw.
pub const D_CARD_VALUES: [i8; D_NRANKS] = [0, 0, -1, -1, 2, 2, 2, 2, -1, -1];

#[inline(always)]
pub fn d_suit(c: u8) -> u8 {
    if c < D_NBASE {
        c / 8
    } else {
        (c - D_NBASE) / D_NEXTRA
    }
}

/// STRENGTH, 0 (the 5) to 9 (the ace) — not the id's low bits. Ordering is a
/// plain `>` everywhere because of this, and the base deck simply never
/// produces a 0 or a 1.
#[inline(always)]
pub fn d_rank(c: u8) -> u8 {
    if c < D_NBASE {
        c % 8 + D_NEXTRA
    } else {
        (c - D_NBASE) % D_NEXTRA
    }
}

#[inline(always)]
pub fn d_card_points(c: u8) -> i8 {
    D_CARD_VALUES[d_rank(c) as usize]
}

/// The whole wide deck's worth: +16, the same as the base deck's. That the two
/// agree is a design constraint, not a coincidence — it is what let the
/// contract ladder survive the deck widening without being re-priced.
pub fn d_deck_pool() -> i8 {
    (0..D_NCARD).map(d_card_points).sum()
}

#[inline(always)]
pub fn d_beats(led: u8, follow: u8, trump: u8) -> bool {
    let ls = d_suit(led);
    let fs = d_suit(follow);
    if fs == ls {
        return d_rank(follow) > d_rank(led);
    }
    // Off-suit wins only by ruffing, and only if the lead was not itself trump.
    // At no-trump nothing ruffs.
    trump < NOTRUMP && fs == trump && ls != trump
}

/// A dummy-mode trick position. Three hands, two sides.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct State3 {
    /// Indexed by POSITION. Position 2 is the dummy.
    pub hand: [Mask; 3],
    pub pile: [[Pile; 3]; 3],
    /// 0..3 = trump suit, 4 = no-trump. Never GRAND — dummy runs the classic
    /// auction, which ranks denominations rather than pricing them.
    pub trump: u8,
    pub trick: u8,
    /// POSITION that led this trick. Never the dummy: it plays second and never
    /// leads, so a trick it wins passes the lead to the side commanding it.
    pub leader: u8,
    /// Cards down in the trick being played, in play order; -1 for empty.
    pub play: [i8; 3],
    pub nplay: u8,
    /// Indexed by SIDE (the player who scores), not by position.
    pub pts: [i8; 2],
    /// Bit s set once side s has won a POSITIVE trick — the Null consolation's
    /// cliff, which is not derivable from `pts` (a total of -1 is one +2 and
    /// three -1s just as easily as one -1 alone).
    pub escored: u8,
}

impl State3 {
    /// WHOEVER LEADS THE TRICK PLAYS THE DUMMY. The whole of the command rule
    /// lives here, and everything else — who is maximising, who banks a trick,
    /// who leads next — derives from it.
    #[inline(always)]
    pub fn side_of(&self, pos: u8) -> u8 {
        if pos == DUMMY_POS {
            self.leader
        } else {
            pos
        }
    }

    /// The POSITION to play next. Order is leader, dummy, the other player.
    #[inline(always)]
    pub fn to_play(&self) -> u8 {
        match self.nplay {
            0 => self.leader,
            1 => DUMMY_POS,
            _ => 1 - self.leader,
        }
    }

    #[inline(always)]
    pub fn done(&self) -> bool {
        self.trick >= D_NTRICKS
    }

    /// Every card a position can reach: its hand plus each pile's top.
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

    /// Every card still held by anybody, the dummy included.
    #[inline(always)]
    pub fn in_play(&self) -> Mask {
        let mut m = self.hand[0] | self.hand[1] | self.hand[2];
        for q in 0..3 {
            for i in 0..3 {
                let p = &self.pile[q][i];
                for k in 0..p.n as usize {
                    m |= 1 << p.c[k];
                }
            }
        }
        m
    }

    /// FREE DISCARD: every playable card is legal, always. Dummy is the one
    /// mode without follow-suit, which is what makes the tree too wide to solve
    /// exactly and is also the reason the mode has decisions worth searching.
    #[inline]
    pub fn legal(&self, out: &mut [u8; 16]) -> usize {
        let mut m = self.playable(self.to_play() as usize);
        let mut n = 0;
        while m != 0 && n < out.len() {
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
                self.pile[p][i].pop_top();
                return;
            }
        }
        panic!("illegal card {} for position {}", c, p);
    }

    /// Play `c` for the position to move. Returns what this ply added to SIDE
    /// 0's differential — non-zero only on the card that completes a trick.
    #[inline]
    pub fn play(&mut self, c: u8) -> i8 {
        let pos = self.to_play();
        self.remove(pos as usize, c);
        self.play[self.nplay as usize] = c as i8;
        self.nplay += 1;
        if self.nplay < 3 {
            return 0;
        }
        // Fold the trick. Positions played in `to_play` order, so index 0 is
        // the leader, 1 the dummy, 2 the other player.
        let order = [self.leader, DUMMY_POS, 1 - self.leader];
        let mut best = 0usize;
        for i in 1..3 {
            if d_beats(self.play[best] as u8, self.play[i] as u8, self.trump) {
                best = i;
            }
        }
        let v: i8 = (0..3).map(|i| d_card_points(self.play[i] as u8)).sum();
        let winner_pos = order[best];
        let winner = self.side_of(winner_pos);
        self.pts[winner as usize] += v;
        if v > 0 {
            self.escored |= 1 << winner;
        }
        self.trick += 1;
        // The dummy never leads: a trick it takes leaves the lead with the side
        // that was commanding it, which is the same seat by construction.
        self.leader = winner;
        self.nplay = 0;
        self.play = [-1, -1, -1];
        if winner == 0 {
            v
        } else {
            -v
        }
    }

    /// Both sides' totals over this deal — points banked plus everything still
    /// in play, since every card in play ends up captured by somebody. Correct
    /// from any position, which is what lets a partial search convert a
    /// differential back into a total.
    pub fn pool(&self) -> i8 {
        let mut s = self.pts[0] + self.pts[1];
        let mut m = self.in_play();
        for i in 0..self.nplay as usize {
            m |= 1 << (self.play[i] as u8);
        }
        while m != 0 {
            s += d_card_points(m.trailing_zeros() as u8);
            m &= m - 1;
        }
        s
    }
}

// --- the per-world search --------------------------------------------------
//
// Depth-limited alpha-beta over SIDE 0's point differential. The game is NOT
// strictly alternating -- within a trick the commanding side moves TWICE (its
// own card, then the dummy's) before the other side answers -- so every node
// asks `side_of(to_play())` who is maximising rather than assuming it flips.
// That is the one structural difference from `dd.rs` and it falls out for free;
// alpha-beta never required alternation, only a single number to optimise.

/// What to do at the horizon. The repo's standing rule is that this choice is
/// game-specific and MEASURED, never assumed -- Spender and Duel measured a
/// static leaf better, CoC measured a short rollout better, on purpose. Both
/// are here so the question is a one-line switch and an offline arena rather
/// than a rewrite.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Leaf {
    /// The differential as banked. Cheapest, and blind to every card still
    /// held -- with card scoring the points are IN the cards, so a pure
    /// material leaf lets the search duck everything past the horizon.
    Material,
    /// Play the rest of the round out with the greedy policy and read the real
    /// total. No horizon effect at all, which is why it is the default: the
    /// truncation this is correcting is exactly the delayed-capture problem CoC
    /// measured a rollout to be the answer to.
    Playout,
}

/// One-trick greedy score for `c`, the policy `bot.policy_score` ports. Used
/// for the playout leaf and for move ordering, where a good guess is worth far
/// more than it costs.
fn greedy_score(s: &State3, c: u8) -> i32 {
    let pos = s.to_play();
    let mine = s.side_of(pos);
    if s.nplay > 0 {
        let led = s.play[0] as u8;
        // Who is winning the trick so far, and would this card take it over?
        let order = [s.leader, DUMMY_POS, 1 - s.leader];
        let mut best = 0usize;
        for i in 1..s.nplay as usize {
            if d_beats(s.play[best] as u8, s.play[i] as u8, s.trump) {
                best = i;
            }
        }
        let winning_pos = order[best];
        let take = d_beats(s.play[best] as u8, c, s.trump);
        let _ = led;
        let winner_side = if take { mine } else { s.side_of(winning_pos) };
        let mut total: i32 = (0..s.nplay as usize)
            .map(|i| d_card_points(s.play[i] as u8) as i32)
            .sum();
        total += d_card_points(c) as i32;
        // A card played before the LAST one can still be taken off you, so back
        // the same total less confidently -- the dummy's dilemma at position 2.
        let w = if s.nplay + 1 >= 3 { 100 } else { 60 };
        let signed = if winner_side == mine { total } else { -total };
        return 400 + w * signed / 100 - d_rank(c) as i32 / 4;
    }
    // Leading: low, keeping the +2s back rather than leading them into the
    // opponent's ducking range.
    200 - d_rank(c) as i32 * 4 - 30 * d_card_points(c).max(0) as i32
}

/// The greedy policy, for arenas and benches -- the exact bot a searching tier
/// has to beat, since an unanswered decision falls back to it server-side.
pub fn greedy_pick_pub(s: &State3) -> u8 {
    greedy_pick(s)
}

fn greedy_pick(s: &State3) -> u8 {
    let mut buf = [0u8; 16];
    let n = s.legal(&mut buf);
    let mut best = buf[0];
    let mut bv = i32::MIN;
    for &c in buf[..n].iter() {
        let v = greedy_score(s, c);
        if v > bv {
            bv = v;
            best = c;
        }
    }
    best
}

/// SIDE 0's differential once the round is played out greedily from here.
fn playout(s: &State3) -> i8 {
    let mut g = *s;
    let mut guard = 0;
    while !g.done() && guard < 64 {
        let c = greedy_pick(&g);
        g.play(c);
        guard += 1;
    }
    g.pts[0] - g.pts[1]
}

#[inline]
fn eval3(s: &State3, leaf: Leaf) -> i8 {
    match leaf {
        Leaf::Material => s.pts[0] - s.pts[1],
        Leaf::Playout => playout(s),
    }
}

/// EQUIVALENCE COLLAPSE, and it must be SOUND rather than a pruning heuristic.
/// Two cards of the same suit play identically when they are worth the same AND
/// no card between them is still reachable by anybody -- then nothing can ever
/// fall between them, so which one you spend cannot matter. Restricted to equal
/// worth because the 8/9 and Q/K boundaries change what a trick pays, which is
/// the same guard `dd.rs` needed the day card scoring shipped.
///
/// **HAND CARDS ONLY, and this is the Dissonance-specific half.** A pile TOP is
/// never interchangeable with anything, however identical it looks as a card:
/// spending it UNCOVERS the card beneath, so it has a side effect on the
/// position that an equal-worth hand card does not. The first version of this
/// merged the two and the soundness control caught it on the second seed
/// (-22 against -20) -- an unsound merge is a quietly wrong VALUE, not a crash,
/// and every other test in this file passed straight through it.
fn collapse(s: &State3, buf: &mut [u8; 16], n: usize) -> usize {
    let mut live = s.in_play();
    for i in 0..s.nplay as usize {
        live |= 1 << (s.play[i] as u8);
    }
    let in_hand = s.hand[s.to_play() as usize];
    let mut keep = [0u8; 16];
    let mut k = 0;
    'outer: for i in 0..n {
        let c = buf[i];
        if in_hand & (1 << c) == 0 {
            keep[k] = c; // a pile top: uncovers something, so never merged
            k += 1;
            continue;
        }
        for j in 0..k {
            let o: u8 = keep[j];
            if in_hand & (1 << o) == 0
                || d_suit(o) != d_suit(c)
                || d_card_points(o) != d_card_points(c)
            {
                continue;
            }
            let (lo, hi) = if d_rank(o) < d_rank(c) { (o, c) } else { (c, o) };
            // Every card of this suit strictly between them must be gone.
            let mut blocked = false;
            for x in 0..D_NCARD {
                if d_suit(x) == d_suit(c)
                    && d_rank(x) > d_rank(lo)
                    && d_rank(x) < d_rank(hi)
                    && live & (1 << x) != 0
                {
                    blocked = true;
                    break;
                }
            }
            if !blocked {
                continue 'outer; // equivalent to one we are already trying
            }
        }
        keep[k] = c;
        k += 1;
    }
    buf[..k].copy_from_slice(&keep[..k]);
    k
}

pub struct Search {
    pub nodes: u64,
    pub leaf: Leaf,
    /// Off only for the soundness control in the tests. A sound collapse
    /// changes the WORK and never the value, so the only way to test it is to
    /// run the same position both ways -- an unsound merge returns a wrong
    /// number quietly, which nothing else here would notice.
    pub collapse_on: bool,
    tt: Vec<(u64, i8, u8, u8)>,
}

const TT_BITS: usize = 18;

impl Search {
    pub fn new(leaf: Leaf) -> Self {
        Search {
            nodes: 0,
            leaf,
            collapse_on: true,
            tt: vec![(0, 0, 0, 0); 1 << TT_BITS],
        }
    }

    fn key_of(&self, s: &State3) -> u64 {
        let mut h: u64 = 0xcbf2_9ce4_8422_2325;
        for q in 0..3 {
            h ^= s.hand[q];
            h = h.wrapping_mul(0x100_0000_01b3);
            for i in 0..3 {
                h ^= (s.pile[q][i].c[0] as u64) << 8
                    | (s.pile[q][i].c[1] as u64) << 16
                    | (s.pile[q][i].n as u64);
                h = h.wrapping_mul(0x100_0000_01b3);
            }
        }
        h ^= (s.leader as u64) << 1
            | (s.nplay as u64) << 3
            | ((s.play[0] as u8 as u64) << 8)
            | ((s.play[1] as u8 as u64) << 16)
            | ((s.trump as u64) << 24);
        h.wrapping_mul(0x100_0000_01b3)
    }

    /// SIDE 0's differential from here, searching `depth` more COMPLETE TRICKS
    /// and then evaluating. Depth counts tricks rather than plies so the
    /// horizon always falls on a trick boundary -- cutting mid-trick counts
    /// some of a trick's cards and none of the others, which biases the leaf
    /// by up to a whole trick's worth in whichever direction the deal happens
    /// to lie.
    pub fn solve(&mut self, s: &State3, depth: u8, mut alpha: i8, mut beta: i8) -> i8 {
        if s.done() {
            return s.pts[0] - s.pts[1];
        }
        if depth == 0 && s.nplay == 0 {
            return eval3(s, self.leaf);
        }
        let key = self.key_of(s);
        let slot = (key as usize) & ((1 << TT_BITS) - 1);
        let (k, v, d, f) = self.tt[slot];
        if k == key && d >= depth {
            match f {
                1 => return v,                        // exact
                2 if v <= alpha => return v,          // upper bound
                3 if v >= beta => return v,           // lower bound
                _ => {}
            }
        }

        let mut buf = [0u8; 16];
        let n = s.legal(&mut buf);
        let n = if self.collapse_on { collapse(s, &mut buf, n) } else { n };
        // Move ordering by the greedy score: a cheap guess is worth far more
        // than it costs here, since a good first move is what makes the cutoff.
        let mut scored: [(i32, u8); 16] = [(0, 0); 16];
        for i in 0..n {
            scored[i] = (greedy_score(s, buf[i]), buf[i]);
        }
        let mover = s.side_of(s.to_play());
        scored[..n].sort_by(|a, b| b.0.cmp(&a.0));

        let a0 = alpha;
        let b0 = beta;
        let mut best = if mover == 0 { i8::MIN } else { i8::MAX };
        for i in 0..n {
            let c = scored[i].1;
            let mut g = *s;
            g.play(c);
            self.nodes += 1;
            // A completed trick is where a trick of depth is spent.
            let nd = if g.nplay == 0 && depth > 0 { depth - 1 } else { depth };
            let v = self.solve(&g, nd, alpha, beta);
            if mover == 0 {
                if v > best {
                    best = v;
                }
                if best > alpha {
                    alpha = best;
                }
            } else {
                if v < best {
                    best = v;
                }
                if best < beta {
                    beta = best;
                }
            }
            if alpha >= beta {
                break;
            }
        }
        let flag = if best <= a0 {
            2
        } else if best >= b0 {
            3
        } else {
            1
        };
        self.tt[slot] = (key, best, depth, flag);
        best
    }

    /// Every legal card for the position to move, with SIDE 0's differential
    /// after it. The caller sums these across worlds, so the ORDER must be a
    /// pure function of the position -- `legal`'s ascending card order, with no
    /// collapse applied, or index i would mean a different card in each world.
    pub fn root(&mut self, s: &State3, depth: u8) -> Vec<(u8, i8)> {
        let mut buf = [0u8; 16];
        let n = s.legal(&mut buf);
        let mut out = Vec::with_capacity(n);
        for &c in buf[..n].iter() {
            let mut g = *s;
            g.play(c);
            let nd = if g.nplay == 0 && depth > 0 { depth - 1 } else { depth };
            out.push((c, self.solve(&g, nd, i8::MIN + 1, i8::MAX - 1)));
        }
        out
    }
}

// --- building a state from a dealt round -----------------------------------

/// A whole dummy deal, for benches and fixtures. `hands[q]` is the 7 in hand,
/// `piles[q][i]` is `[bottom, top]`.
pub fn state_from(
    hands: [Vec<u8>; 3],
    piles: [[[u8; 2]; 3]; 3],
    trump: u8,
    leader: u8,
) -> State3 {
    let mut hand = [0 as Mask; 3];
    let mut pile = [[Pile::default(); 3]; 3];
    for q in 0..3 {
        for &c in &hands[q] {
            hand[q] |= 1 << c;
        }
        for i in 0..3 {
            pile[q][i] = Pile::new(piles[q][i][0], piles[q][i][1]);
        }
    }
    State3 {
        hand,
        pile,
        trump,
        trick: 0,
        leader,
        play: [-1, -1, -1],
        nplay: 0,
        pts: [0, 0],
        escored: 0,
    }
}

/// Deal a wide-deck round from a seed. Only for benches and tests — the serving
/// path reads a real position off the wire.
pub fn deal(seed: u64) -> State3 {
    let mut deck: Vec<u8> = (0..D_NCARD).collect();
    let mut s = seed | 1;
    for i in (1..deck.len()).rev() {
        s ^= s << 13;
        s ^= s >> 7;
        s ^= s << 17;
        let j = (s % (i as u64 + 1)) as usize;
        deck.swap(i, j);
    }
    let mut hands: [Vec<u8>; 3] = [vec![], vec![], vec![]];
    let mut piles = [[[0u8; 2]; 3]; 3];
    let mut k = 0;
    for q in 0..3 {
        for _ in 0..7 {
            hands[q].push(deck[k]);
            k += 1;
        }
        for i in 0..3 {
            piles[q][i] = [deck[k], deck[k + 1]];
            k += 2;
        }
    }
    state_from(hands, piles, 2, 0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_wide_deck_is_forty_cards_worth_sixteen_with_the_lows_inert() {
        assert_eq!(d_deck_pool(), 16, "the wide deck totals what the base one does");
        for c in D_NBASE..D_NCARD {
            assert_eq!(d_card_points(c), 0, "card {} should be inert", c);
        }
        // Every base id keeps its meaning -- the whole reason the extra cards
        // were appended rather than the deck renumbered.
        for c in 0..D_NBASE {
            assert_eq!(d_suit(c), c / 8);
            assert_eq!(d_rank(c), c % 8 + D_NEXTRA);
        }
        // ...and the new ones are a 5 and a 6 in each suit, under every 7.
        for c in D_NBASE..D_NCARD {
            assert!(d_rank(c) < 2);
            for b in 0..D_NBASE {
                if d_suit(b) == d_suit(c) {
                    assert!(d_beats(c, b, NOTRUMP), "every base card beats a 5/6");
                    assert!(!d_beats(b, c, NOTRUMP));
                }
            }
        }
    }

    #[test]
    fn the_dummy_plays_second_every_trick_and_never_leads() {
        let mut g = deal(7);
        let mut seen_dummy = 0;
        while !g.done() {
            assert_eq!(g.to_play(), g.leader, "the leader opens");
            assert_ne!(g.leader, DUMMY_POS, "the dummy never leads");
            g.play(greedy_pick(&g));
            assert_eq!(g.to_play(), DUMMY_POS, "the dummy answers second");
            g.play(greedy_pick(&g));
            seen_dummy += 1;
            g.play(greedy_pick(&g));
        }
        assert_eq!(seen_dummy, D_NTRICKS as i32);
        assert_eq!(g.trick, D_NTRICKS);
    }

    #[test]
    fn a_whole_round_conserves_the_pool() {
        for seed in 1..25u64 {
            let mut g = deal(seed);
            let pool = g.pool();
            while !g.done() {
                g.play(greedy_pick(&g));
            }
            assert_eq!(
                g.pts[0] + g.pts[1],
                pool,
                "seed {}: every dealt-in card ends up captured",
                seed
            );
            // 39 of the 40 are dealt, so the pool is 16 minus the one out-card.
            assert!((14..=17).contains(&pool), "seed {} pool {}", seed, pool);
        }
    }

    #[test]
    fn free_discard_means_every_playable_card_is_legal() {
        let mut g = deal(3);
        let mut buf = [0u8; 16];
        while !g.done() {
            let n = g.legal(&mut buf);
            let want = g.playable(g.to_play() as usize).count_ones() as usize;
            assert_eq!(n, want, "no card is ever filtered out");
            g.play(buf[0]);
        }
    }

    #[test]
    fn the_commanding_side_moves_twice_a_trick_and_it_follows_the_lead() {
        let mut g = deal(11);
        while !g.done() {
            let lead = g.leader;
            assert_eq!(g.side_of(g.to_play()), lead);
            g.play(greedy_pick(&g));
            assert_eq!(
                g.side_of(g.to_play()),
                lead,
                "the dummy scores for whoever led"
            );
            g.play(greedy_pick(&g));
            assert_eq!(g.side_of(g.to_play()), 1 - lead, "then the other player");
            g.play(greedy_pick(&g));
        }
    }

    #[test]
    fn the_collapse_is_sound_it_changes_the_work_and_never_the_value() {
        // The real control: the SAME positions searched with the collapse on
        // and off. An unsound merge returns a quietly wrong number, which no
        // other test here would notice -- and it must also actually SAVE work,
        // or it is a no-op wearing an optimisation's name.
        let mut saved = 0u64;
        for seed in 1..8u64 {
            let mut g = deal(seed);
            for _ in 0..21 {
                if g.done() {
                    break;
                }
                g.play(greedy_pick(&g));
            }
            let mut on = Search::new(Leaf::Material);
            let mut off = Search::new(Leaf::Material);
            off.collapse_on = false;
            let a = on.solve(&g, 3, i8::MIN + 1, i8::MAX - 1);
            let b = off.solve(&g, 3, i8::MIN + 1, i8::MAX - 1);
            assert_eq!(a, b, "seed {}: the collapse moved the VALUE", seed);
            assert!(on.nodes <= off.nodes);
            saved += off.nodes - on.nodes;
        }
        assert!(saved > 0, "the collapse never fired -- it is not being tested");
    }

    #[test]
    fn searching_deeper_never_costs_the_side_to_move() {
        // Not a strength claim -- a sanity one. A depth-0 search is the leaf
        // itself, so the root's own best move must at least be reachable.
        let g = deal(5);
        let mut s = Search::new(Leaf::Playout);
        let r = s.root(&g, 1);
        assert_eq!(
            r.len(),
            g.playable(g.leader as usize).count_ones() as usize,
            "root offers every legal card, uncollapsed, in card order"
        );
        let mut sorted: Vec<u8> = r.iter().map(|x| x.0).collect();
        let orig = sorted.clone();
        sorted.sort();
        assert_eq!(sorted, orig, "ascending card order, so index i is stable");
    }
}

// --- determinization -------------------------------------------------------

/// What one seat can honestly see of a dummy round. Everything else is
/// resampled per world.
#[derive(Clone, Debug, Default)]
pub struct DView {
    /// The seat this view belongs to: 0 or 1, never the dummy.
    pub me: u8,
    /// My own hand, exactly.
    pub my_hand: Vec<u8>,
    /// The DUMMY'S hand, exactly -- it is face up from the deal, to both
    /// players. That is the mode's premise, and it is why a dummy world has
    /// markedly less to resample than any other mode's.
    pub dummy_hand: Vec<u8>,
    /// How many cards the opponent holds in hand.
    pub opp_hand_n: usize,
    /// Per position, per pile: the top (or None if the pile is spent) and the
    /// covered card if it is public. `n` is how many cards remain.
    pub piles: [[(Option<u8>, Option<u8>, u8); 3]; 3],
    pub trump: u8,
    pub trick: u8,
    pub leader: u8,
    /// Cards down in the current trick, as (position, card) in play order.
    pub plays: Vec<(u8, u8)>,
    /// Points already banked, by SIDE.
    pub pts: [i8; 2],
    pub escored: u8,
    /// Every card already played, plus every card visible anywhere -- the
    /// complement of what a world has to invent.
    pub seen: Mask,
}

impl DView {
    /// The cards this seat cannot place: the opponent's hand, every covered
    /// outer pile bottom (its own included -- a seat is not shown its own),
    /// and whatever sits out of play.
    pub fn unseen(&self) -> Mask {
        let all: Mask = (1 << D_NCARD) - 1;
        all & !self.seen
    }

    fn hidden_slots(&self) -> usize {
        let mut n = 0;
        for q in 0..3 {
            for i in 0..3 {
                let (_, under, cnt) = self.piles[q][i];
                if cnt == 2 && under.is_none() {
                    n += 1;
                }
            }
        }
        n
    }

    /// Deal one world consistent with everything above. Returns None when the
    /// arithmetic does not balance -- FAIL CLOSED, exactly as `wire.rs` does
    /// for the two-seat modes: a searcher fed a world that cannot exist returns
    /// a legal card computed from a lie, which the room then plays at full
    /// speed while still saying Hard.
    pub fn determinize(&self, seed: u64) -> Option<State3> {
        let mut pool: Vec<u8> = Vec::new();
        let mut m = self.unseen();
        while m != 0 {
            pool.push(m.trailing_zeros() as u8);
            m &= m - 1;
        }
        let slots = self.hidden_slots();
        if pool.len() < self.opp_hand_n + slots {
            return None; // more hidden holdings than there are cards for
        }
        // Shuffle the pool; the leftovers after hands and pile bottoms are
        // whatever sat out of play, which nobody plays and nothing reads.
        let mut s = seed | 1;
        for i in (1..pool.len()).rev() {
            s ^= s << 13;
            s ^= s >> 7;
            s ^= s << 17;
            let j = (s % (i as u64 + 1)) as usize;
            pool.swap(i, j);
        }
        let mut k = 0;
        let opp = 1 - self.me;
        let mut hand = [0 as Mask; 3];
        for &c in &self.my_hand {
            hand[self.me as usize] |= 1 << c;
        }
        for &c in &self.dummy_hand {
            hand[DUMMY_POS as usize] |= 1 << c;
        }
        for _ in 0..self.opp_hand_n {
            hand[opp as usize] |= 1 << pool[k];
            k += 1;
        }
        let mut pile = [[Pile::default(); 3]; 3];
        for q in 0..3 {
            for i in 0..3 {
                let (top, under, cnt) = self.piles[q][i];
                pile[q][i] = match (cnt, top, under) {
                    (0, _, _) => Pile::default(),
                    (1, Some(t), _) => Pile { c: [t, 0], n: 1 },
                    (2, Some(t), Some(u)) => Pile::new(u, t),
                    (2, Some(t), None) => {
                        let u = pool[k];
                        k += 1;
                        Pile::new(u, t)
                    }
                    _ => return None, // a shape the server cannot produce
                };
            }
        }
        let mut st = State3 {
            hand,
            pile,
            trump: self.trump,
            trick: self.trick,
            leader: self.leader,
            play: [-1, -1, -1],
            nplay: 0,
            pts: self.pts,
            escored: self.escored,
        };
        // Replay the trick in progress so `to_play` and the fold agree with the
        // server's, rather than trusting a count.
        for (pos, c) in self.plays.iter().copied() {
            if st.to_play() != pos {
                return None;
            }
            st.play[st.nplay as usize] = c as i8;
            st.nplay += 1;
            // The card is already out of its holder's hand server-side.
            st.hand[pos as usize] &= !(1 << c);
            for i in 0..3 {
                if st.pile[pos as usize][i].top() == Some(c) {
                    st.pile[pos as usize][i].pop_top();
                    break;
                }
            }
        }
        Some(st)
    }
}

/// PIMC: sample `k` worlds, search each, and SUM each legal card's value across
/// them. Summing (rather than voting) is what makes the pooled answer identical
/// to one worker with the combined k, which is what lets the browser split the
/// worlds across a worker pool -- the same contract `odd_best_card` already
/// rests on for the two-seat modes.
///
/// The returned vector is indexed by `State3::legal`'s ascending card order,
/// which is a pure function of the position and therefore the same in every
/// world and every worker.
pub fn pimc(v: &DView, k: u32, depth: u8, leaf: Leaf, seed: u64) -> Option<Vec<(u8, i32)>> {
    let probe = v.determinize(seed)?;
    let mut buf = [0u8; 16];
    let n = probe.legal(&mut buf);
    let mut out: Vec<(u8, i32)> = buf[..n].iter().map(|&c| (c, 0)).collect();
    let mut worlds = 0;
    for w in 0..k {
        let st = match v.determinize(seed.wrapping_add(0x9e37_79b9_7f4a_7c15u64.wrapping_mul(w as u64 + 1))) {
            Some(s) => s,
            None => continue,
        };
        let mut s = Search::new(leaf);
        for (c, val) in s.root(&st, depth) {
            if let Some(slot) = out.iter_mut().find(|x| x.0 == c) {
                slot.1 += val as i32;
            }
        }
        worlds += 1;
    }
    if worlds == 0 {
        return None;
    }
    Some(out)
}

/// The pick rule, HERE rather than in the worker's JS -- a copy that drifted
/// would be a different bot wearing the same name. Highest total to the side
/// asking, ties to the earliest legal card.
pub fn best_card(vals: &[(u8, i32)], side: u8) -> Option<u8> {
    vals.iter()
        .copied()
        .reduce(|a, b| {
            let better = if side == 0 { b.1 > a.1 } else { b.1 < a.1 };
            if better { b } else { a }
        })
        .map(|x| x.0)
}

// --- the wire --------------------------------------------------------------
//
// A SECOND PARITY SURFACE, and it fails silently by nature: a reader that
// mis-sizes the hidden pool or drops a visible card still returns a legal
// card, just a worse one -- a room that says Hard while playing below it, with
// nothing red anywhere. Hence the fixture replay in `tests/dummy_wire.rs` and
// the fail-closed partition check in `DView::determinize`.

#[cfg(any(feature = "bridge", target_arch = "wasm32"))]
mod wire {
    use super::*;
    use serde_json::Value;

    fn u8s(v: &Value) -> Vec<u8> {
        v.as_array()
            .map(|a| a.iter().filter_map(|x| x.as_u64()).map(|x| x as u8).collect())
            .unwrap_or_default()
    }

    /// Read `engine.view_for`'s payload for a DUMMY room into a `DView`.
    ///
    /// Returns None for anything it cannot honour -- a non-dummy view, a seat
    /// that is the dummy, a pile shape the server cannot produce, or a card
    /// count that does not balance. Every None is the ordinary per-decision
    /// degradation: the server plays that one decision with its own bot.
    pub fn dview_from_json(s: &str) -> Option<DView> {
        let raw: Value = serde_json::from_str(s).ok()?;
        // The browser wraps the payload (`{view, payoff, auction}`) while the
        // fixtures and the harnesses hand over a bare view. Accept both, as
        // `wire.rs` already does -- the wrapper is what the worker actually
        // sends, and reading only the bare shape made every real decision
        // return "not a searchable dummy position" while all 468 fixtures
        // passed. Silent, naturally: the room just played the server bot.
        let v: &Value = raw.get("view").unwrap_or(&raw);
        if v.get("mode")?.as_str()? != "dummy" {
            return None;
        }
        if v.get("phase")?.as_str()? != "play" {
            return None;
        }
        let me = v.get("you")?.as_u64()? as u8;
        if me >= DUMMY_POS {
            return None;
        }
        let my_hand = u8s(v.get("hand")?);
        let dummy_hand = u8s(v.get("dummy")?);
        let opp_hand_n = v.get("opp_hand_n")?.as_u64()? as usize;
        let trump = v.get("trump")?.as_u64()? as u8;
        // Dummy runs the classic auction: suits and no-trump only. A Grand here
        // would mean the server changed the mode's auction without this reader
        // learning the rule, which must fail closed rather than mis-play tens.
        if trump > NOTRUMP {
            return None;
        }
        let trick = v.get("trick")?.as_u64()? as u8;
        let leader = v.get("leader")?.as_u64()? as u8;
        if leader >= DUMMY_POS {
            return None; // the dummy never leads
        }
        let pts_raw = u8s(v.get("pts")?);
        let pts_arr = v.get("pts")?.as_array()?;
        let mut pts = [0i8; 2];
        for i in 0..2 {
            pts[i] = pts_arr.get(i)?.as_i64()? as i8;
        }
        let _ = pts_raw;
        let mut escored = 0u8;
        for (i, e) in v.get("etricks")?.as_array()?.iter().enumerate() {
            if i < 2 && e.as_i64().unwrap_or(0) > 0 {
                escored |= 1 << i;
            }
        }

        let mut seen: Mask = 0;
        let mut mark = |c: u8| -> Option<()> {
            if c >= D_NCARD {
                return None;
            }
            seen |= 1 << c;
            Some(())
        };
        for &c in my_hand.iter().chain(dummy_hand.iter()) {
            mark(c)?;
        }
        // Every card already played is placed for good.
        for h in v.get("history")?.as_array()? {
            let e = h.as_array()?;
            mark(e.get(1)?.as_u64()? as u8)?;
        }
        let mut plays: Vec<(u8, u8)> = Vec::new();
        for p in v.get("plays")?.as_array()? {
            let e = p.as_array()?;
            let pos = e.first()?.as_u64()? as u8;
            let c = e.get(1)?.as_u64()? as u8;
            mark(c)?;
            plays.push((pos, c));
        }

        let mut piles = [[(None, None, 0u8); 3]; 3];
        let parr = v.get("piles")?.as_array()?;
        if parr.len() != 3 {
            return None;
        }
        for (q, seat) in parr.iter().enumerate() {
            let ps = seat.as_array()?;
            if ps.len() != 3 {
                return None;
            }
            for (i, p) in ps.iter().enumerate() {
                let n = p.get("n")?.as_u64()? as u8;
                let top = p.get("top").and_then(|x| x.as_u64()).map(|x| x as u8);
                let under = p.get("under").and_then(|x| x.as_u64()).map(|x| x as u8);
                if let Some(t) = top {
                    mark(t)?;
                }
                if let Some(u) = under {
                    mark(u)?;
                }
                if n > 0 && top.is_none() {
                    return None; // a live pile must show its top
                }
                piles[q][i] = (top, under, n);
            }
        }

        let dv = DView {
            me,
            my_hand,
            dummy_hand,
            opp_hand_n,
            piles,
            trump,
            trick,
            leader,
            plays,
            pts,
            escored,
            seen,
        };
        // THE PARTITION CHECK. Everything unseen must be exactly the opponent's
        // hand, the covered outer bottoms, and the cards out of play -- and a
        // dummy deal puts exactly ONE card out (three seats of thirteen off
        // forty). Anything else means this reader and the server disagree about
        // the deal, so it must not search.
        let unseen = dv.unseen().count_ones() as usize;
        let want = dv.opp_hand_n + dv.hidden_slots();
        if unseen < want || unseen - want != (D_NCARD - 3 * D_NDEALT) as usize {
            return None;
        }
        Some(dv)
    }
}

#[cfg(any(feature = "bridge", target_arch = "wasm32"))]
pub use wire::dview_from_json;
