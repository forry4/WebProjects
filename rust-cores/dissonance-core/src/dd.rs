//! Double-dummy solver: exact minimax over a fully-known deal.
//!
//! The round is constant-sum (+5), so a single number — player 0's point
//! differential — is all the search needs. `search` returns the differential
//! earned *from this position onward*, deliberately excluding points already
//! banked, so a transposition table entry is valid regardless of how the
//! position was reached.
//!
//! Note the search does NOT alternate strictly: the trick winner leads next,
//! so the same player often moves twice in a row. That rules out negamax —
//! hence the explicit max/min.
//!
//! Speed comes from four things, in order of how much they mattered:
//!   1. MTD(f) — a ladder of null-window searches instead of one wide window.
//!   2. Static bounds: the best and worst differential still reachable from a
//!      given trick number is known in closed form, which cuts whole subtrees.
//!   3. A best-move hint in the table, tried first on re-entry.
//!   4. Equivalence pruning of interchangeable hand cards.

use crate::cards::*;
use crate::state::*;

const F_EMPTY: u8 = 0;
const F_EXACT: u8 = 1;
const F_LOWER: u8 = 2;
const F_UPPER: u8 = 3;
const NO_MOVE: u8 = 255;

#[derive(Clone, Copy)]
struct Entry {
    key: u64,
    val: i8,
    flag: u8,
    mv: u8,
}

impl Default for Entry {
    fn default() -> Self {
        Entry {
            key: 0,
            val: 0,
            flag: F_EMPTY,
            mv: NO_MOVE,
        }
    }
}

/// `MAXD[t]` / `MIND[t]`: the largest and smallest differential still
/// obtainable when the trick with index `t` is about to be played. Player 0
/// gains 2 by winning a +2 trick and gains 1 by making the opponent eat a -1
/// trick, so each remaining trick is worth 2 or 1 in absolute terms.
static MAXD: [i16; 14] = build_bounds(true);
static MIND: [i16; 14] = build_bounds(false);

const fn build_bounds(max: bool) -> [i16; 14] {
    let mut a = [0i16; 14];
    let mut t = 13usize;
    while t > 0 {
        t -= 1;
        // 2 for a +2 trick, 1 for a -1 trick, whichever parity those are.
        let w: i16 = if trick_value(t as u8) == 2 { 2 } else { 1 };
        a[t] = a[t + 1] + if max { w } else { -w };
    }
    a
}

/// A contract to be played out exactly, rather than for maximum points.
///
/// With a penalty for exceeding the contract the payoff stops being linear in
/// the point differential, so the constant-sum trick that `search` relies on
/// no longer applies: the value now depends on the declarer's FINAL total, and
/// accumulated points have to enter the transposition key.
#[derive(Clone, Copy, Debug)]
pub struct Contract {
    pub level: i32,
    pub declarer: usize,
    pub make_base: i32,
    /// Penalty per point ABOVE the contract.
    pub over: i32,
    pub set_base: i32,
    /// Defender's reward per point the declarer finished short.
    pub short: i32,
    /// What the declarer scores for taking NO +2 TRICK ALL ROUND, if the rule
    /// is in play. `None` for the auction lab's synthetic contracts, which use
    /// this struct to ask a different question (`forced_floor`) and must not
    /// have a consolation appear underneath it.
    pub null: Option<i32>,
}

impl Contract {
    /// Declarer score minus defender score, given the declarer's final total
    /// and whether they ever won a +2 trick.
    ///
    /// THE NULL TERM IS CHECKED FIRST AND WINS, exactly as `engine._finish`
    /// does. It can never collide with a make: only +2 tricks add points, so a
    /// declarer on zero of them cannot have reached any target. It is also the
    /// only part of this function that is not a function of `declarer_pts`,
    /// which is why the flag had to go into `State` -- a solver that reads the
    /// points alone is blind to a cliff worth up to `null + set_base + short x
    /// level` in one bit.
    #[inline]
    pub fn payoff(&self, declarer_pts: i32, declarer_scored: bool) -> i32 {
        if let Some(n) = self.null {
            if !declarer_scored {
                return n;
            }
        }
        if declarer_pts >= self.level {
            self.make_base - self.over * (declarer_pts - self.level)
        } else {
            -(self.set_base + self.short * (self.level - declarer_pts))
        }
    }
}

#[derive(Clone, Copy)]
struct CEntry {
    key: u64,
    val: i32,
    flag: u8,
}

impl Default for CEntry {
    fn default() -> Self {
        CEntry {
            key: 0,
            val: 0,
            flag: F_EMPTY,
        }
    }
}

pub struct Dd {
    tt: Vec<Entry>,
    ctt: Vec<CEntry>,
    cmask: usize,
    mask: usize,
    pub nodes: u64,
    /// Bisection switches, for isolating a value regression to one technique.
    pub use_bounds: bool,
    pub use_mtdf: bool,
    pub use_equiv: bool,
}

#[inline(always)]
fn mix(mut x: u64) -> u64 {
    x ^= x >> 33;
    x = x.wrapping_mul(0xff51afd7ed558ccd);
    x ^= x >> 29;
    x = x.wrapping_mul(0xc4ceb9fe1a85ec53);
    x ^ (x >> 32)
}

/// Full position key. Banked points are excluded on purpose (see module doc);
/// `trick` is included because parity scoring makes timing matter.
#[inline]
fn key_of(s: &State) -> u64 {
    // Pack the piles densely: 6 piles x (2 cards + count) fits two words.
    let mut a: u64 = 0;
    let mut b: u64 = 0;
    for i in 0..3 {
        let p = &s.pile[0][i];
        a = (a << 21) | ((p.n as u64) << 16) | ((p.c[1] as u64) << 8) | p.c[0] as u64;
        let q = &s.pile[1][i];
        b = (b << 21) | ((q.n as u64) << 16) | ((q.c[1] as u64) << 8) | q.c[0] as u64;
    }
    // The two hands are mixed separately rather than packed into one word:
    // they are NCARD bits each, so any packing that fits a 28-card deck
    // overflows a wider one, and the failure mode is a silent hash collision
    // returning another position's value.
    let h = mix(s.hand[0]) ^ mix(s.hand[1]).rotate_left(29) ^ mix(s.trump as u64 | (1 << 60));
    let t = (s.trick as u64) | ((s.leader as u64) << 8) | ((((s.led as i16) as u16) as u64) << 16);
    // Mix each component on its own before combining. Folding two fields
    // together with XOR first would let their overlapping bit ranges alias,
    // which silently returns another position's value out of the table.
    mix(h ^ mix(a).rotate_left(17) ^ mix(b).rotate_left(37) ^ mix(t | (1 << 40)))
}

impl Dd {
    /// `bits` sizes the table at 2^bits entries (16 bytes each). Bigger is not
    /// automatically better — past L3 every probe is a cache miss.
    pub fn new(bits: u32) -> Self {
        let n = 1usize << bits;
        let cn = 1usize << bits.saturating_sub(1).max(10);
        Dd {
            tt: vec![Entry::default(); n],
            ctt: vec![CEntry::default(); cn],
            cmask: cn - 1,
            mask: n - 1,
            nodes: 0,
            use_bounds: true,
            use_mtdf: true,
            use_equiv: true,
        }
    }

    pub fn clear(&mut self) {
        for e in self.tt.iter_mut() {
            e.flag = F_EMPTY;
        }
        for e in self.ctt.iter_mut() {
            e.flag = F_EMPTY;
        }
    }

    /// Per-move contract values for the player to move: `out[i]` is the exact
    /// payoff (declarer minus defender) after playing `moves[i]`.
    ///
    /// The contract twin of `solve_root`, and the reason the served bot has one
    /// at all: a points solver optimises the YARDSTICK. It cannot see that a
    /// declarer three points past their target gains nothing more, that every
    /// point of a defender's shortfall is worth four, or that a declarer who
    /// has taken no +2 trick is one ducked trick away from scoring instead of
    /// being set.
    pub fn solve_root_contract(&mut self, s: &State, moves: &[u8], c: &Contract,
                               out: &mut [i32; 16]) {
        for (i, &m) in moves.iter().enumerate() {
            let mut t = *s;
            t.play(m);
            out[i] = self.solve_contract(&t, c);
        }
    }

    /// Exact value of playing out a CONTRACT, as declarer score minus defender
    /// score. Unlike `solve`, the declarer here is not maximising points -- an
    /// over-penalty makes their payoff single-peaked at the contract level, so
    /// they may have to deliberately shed tricks, and the defence's weapon
    /// becomes forcing unwanted winners on them.
    pub fn solve_contract(&mut self, s: &State, c: &Contract) -> i32 {
        self.csearch(s, c, -1_000_000, 1_000_000)
    }

    fn csearch(&mut self, s: &State, c: &Contract, mut alpha: i32, mut beta: i32) -> i32 {
        if s.done() {
            return c.payoff(
                s.pts[c.declarer] as i32,
                s.escored & (1 << c.declarer) != 0,
            );
        }
        self.nodes += 1;

        // Accumulated points MUST be in the key here. The sum of both players'
        // points is fixed by the trick index, so one side's total suffices.
        // So must `escored`: two positions identical in cards and points can
        // pay off differently when one declarer has already broken their Null,
        // and a table that conflated them would return the other one's value.
        let key = key_of(s)
            ^ mix(0x9E37_79B9_7F4A_7C15
                ^ ((s.pts[0] as i64 as u64) << 8)
                ^ ((s.escored as u64) << 40));
        let slot = (key as usize) & self.cmask;
        {
            let e = unsafe { *self.ctt.get_unchecked(slot) };
            if e.flag != F_EMPTY && e.key == key {
                match e.flag {
                    F_EXACT => return e.val,
                    F_LOWER if e.val >= beta => return e.val,
                    F_UPPER if e.val <= alpha => return e.val,
                    _ => {}
                }
            }
        }

        let (a0, b0) = (alpha, beta);
        let mover = s.to_play() as usize;
        let maxing = mover == c.declarer;

        let mut moves = [0u8; 16];
        let n = s.legal(&mut moves);
        let n = self.prune_and_order(s, mover, &mut moves, n, NO_MOVE);

        let mut best = if maxing { -1_000_000 } else { 1_000_000 };
        for i in 0..n {
            let mut t = *s;
            t.play(moves[i]);
            let v = self.csearch(&t, c, alpha, beta);
            if maxing {
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
            F_UPPER
        } else if best >= b0 {
            F_LOWER
        } else {
            F_EXACT
        };
        unsafe {
            *self.ctt.get_unchecked_mut(slot) = CEntry {
                key,
                val: best,
                flag,
            }
        };
        best
    }

    /// Can `declarer` guarantee taking NO TRICK AT ALL, against a defence
    /// doing everything it can to force one on them?
    ///
    /// This cannot go through `Contract`, which pays off on `pts`: taking no
    /// tricks scores zero, but so does taking one even trick and two odd ones,
    /// and those are completely different contracts. Null is a trick-COUNT
    /// condition and needs its own search.
    ///
    /// It is also much cheaper than the point game. The value is a boolean, so
    /// there are no windows to widen and no MTD(f) driver; and a line dies the
    /// instant a trick falls the wrong way, where the point game has to play
    /// every deal out to trick thirteen.
    pub fn null_makeable(&mut self, s: &State, declarer: usize) -> bool {
        self.nsearch(s, declarer, false)
    }

    /// The reachable Null: take no SCORING trick — none of the six +2 tricks.
    /// Odd tricks may be taken freely.
    ///
    /// Six tricks to dodge instead of thirteen, which is why this lives where
    /// the zero-trick version does not (0.7%). It also carries a tension the
    /// zero-trick version has not got: winning an odd trick makes you LEAD the
    /// even one that follows, and leading is the one position from which you
    /// cannot duck. So the odd tricks are not free after all — every one you
    /// take hands you the hardest seat at the next scoring trick.
    ///
    /// It is the natural contract for a parity game in a way Skat's is not:
    /// the condition is stated in the game's own currency.
    pub fn null_no_even_makeable(&mut self, s: &State, declarer: usize) -> bool {
        self.nsearch(s, declarer, true)
    }

    /// `scoring_only` restricts the losing condition to +2 tricks.
    fn nsearch(&mut self, s: &State, declarer: usize, scoring_only: bool) -> bool {
        if s.done() {
            return true; // survived all thirteen
        }
        self.nodes += 1;

        // Banked points are deliberately NOT in the key: two positions that
        // differ only in points already scored are the same Null problem.
        // The two variants are DIFFERENT problems on the same position, so
        // they must not share transposition entries.
        let key = key_of(s)
            ^ mix(0x4E75_6C6C_0000 ^ declarer as u64 ^ ((scoring_only as u64) << 32));
        let slot = (key as usize) & self.cmask;
        {
            let e = unsafe { *self.ctt.get_unchecked(slot) };
            if e.flag == F_EXACT && e.key == key {
                return e.val != 0;
            }
        }

        let mover = s.to_play() as usize;
        let maxing = mover == declarer;

        let mut moves = [0u8; 16];
        let n = s.legal(&mut moves);
        // The move ORDER this produces is tuned for the point game and is
        // merely suboptimal here, but its equivalence collapse is about which
        // cards are interchangeable, which holds whatever the objective is.
        let n = self.prune_and_order(s, mover, &mut moves, n, NO_MOVE);

        // The declarer needs ONE surviving line; the defence needs every line
        // to survive, so the initial value is the identity of each quantifier.
        let mut ok = !maxing;
        for i in 0..n {
            let mut t = *s;
            let completing = t.led >= 0;
            t.play(moves[i]);
            // Only a trick the declarer must not win ends the line. Under
            // `scoring_only` the -1 tricks are theirs to take.
            let fatal = completing
                && t.leader as usize == declarer
                && (!scoring_only || trick_value(s.trick) > 0);
            let v = if fatal {
                false
            } else {
                self.nsearch(&t, declarer, scoring_only)
            };
            if maxing {
                if v {
                    ok = true;
                    break;
                }
            } else if !v {
                ok = false;
                break;
            }
        }

        unsafe {
            *self.ctt.get_unchecked_mut(slot) = CEntry {
                key,
                val: ok as i32,
                flag: F_EXACT,
            }
        };
        ok
    }

    /// Fewest tricks `declarer` can be held to, against a defence trying to
    /// force as many on them as it can. `null_makeable` is the special case
    /// where this returns 0 — measured at under 1% of hands, which is why the
    /// general number matters: it says where a REACHABLE version of the same
    /// contract would have to sit.
    pub fn min_tricks(&mut self, s: &State, declarer: usize) -> i32 {
        self.tsearch(s, declarer, false, -1, NTRICKS as i32 + 1)
    }

    /// Fewest SCORING (+2) tricks `declarer` can be held to. The parity-game
    /// version of the same question, and the one that matters: the -1 tricks
    /// are not what a low contract is trying to dodge.
    pub fn min_even_tricks(&mut self, s: &State, declarer: usize) -> i32 {
        self.tsearch(s, declarer, true, -1, NTRICKS as i32 + 1)
    }

    /// Future tricks taken by `declarer` under optimal play from both sides.
    /// Tricks already banked are excluded, which is what keeps them out of the
    /// key: two positions differing only in tricks already won pose the same
    /// remaining problem.
    fn tsearch(
        &mut self,
        s: &State,
        declarer: usize,
        scoring_only: bool,
        mut alpha: i32,
        mut beta: i32,
    ) -> i32 {
        if s.done() {
            return 0;
        }
        self.nodes += 1;

        let key = key_of(s)
            ^ mix(0x7472_6963_6B73 ^ declarer as u64 ^ ((scoring_only as u64) << 32));
        let slot = (key as usize) & self.cmask;
        let (a0, b0) = (alpha, beta);
        {
            let e = unsafe { *self.ctt.get_unchecked(slot) };
            if e.flag != F_EMPTY && e.key == key {
                match e.flag {
                    F_EXACT => return e.val,
                    F_LOWER if e.val >= beta => return e.val,
                    F_UPPER if e.val <= alpha => return e.val,
                    _ => {}
                }
            }
        }

        let mover = s.to_play() as usize;
        // The declarer wants FEW tricks, so the declarer is the minimiser here
        // — the opposite of every other search in this file.
        let maxing = mover != declarer;

        let mut moves = [0u8; 16];
        let n = s.legal(&mut moves);
        let n = self.prune_and_order(s, mover, &mut moves, n, NO_MOVE);

        let mut best = if maxing { -1 } else { NTRICKS as i32 + 1 };
        for i in 0..n {
            let mut t = *s;
            let completing = t.led >= 0;
            t.play(moves[i]);
            let counts = !scoring_only || trick_value(s.trick) > 0;
            let got = i32::from(completing && t.leader as usize == declarer && counts);
            // The child reports the count AFTER this trick's `got`, so its
            // window must be shifted by it -- the same trap that was live in
            // `search` once already.
            let v = got + self.tsearch(&t, declarer, scoring_only, alpha - got, beta - got);
            if maxing {
                best = best.max(v);
                alpha = alpha.max(best);
            } else {
                best = best.min(v);
                beta = beta.min(best);
            }
            if alpha >= beta {
                break;
            }
        }

        let flag = if best <= a0 {
            F_UPPER
        } else if best >= b0 {
            F_LOWER
        } else {
            F_EXACT
        };
        unsafe {
            *self.ctt.get_unchecked_mut(slot) = CEntry { key, val: best, flag }
        };
        best
    }

    /// Exact value of the position: player 0's future point differential.
    pub fn solve(&mut self, s: &State) -> i16 {
        self.solve_from(s, 0)
    }

    /// `solve`, seeded. MTD(f) converges by a ladder of null-window probes, so
    /// starting near the answer skips most of the rungs — `solve_root` has done
    /// this between sibling moves since the campaign. The auction wants it
    /// between DENOMINATIONS: the same hand is worth a similar amount in hearts
    /// and in spades, so the first solve pays for the other four.
    pub fn solve_from(&mut self, s: &State, guess: i16) -> i16 {
        if self.use_mtdf {
            self.mtdf(s, guess)
        } else {
            self.search(s, -64, 64)
        }
    }

    /// MTD(f): converge on the value with a ladder of null-window probes.
    /// Every remaining trick shifts the differential by 1 or 2, so the value's
    /// parity is fixed by how many odd-value tricks remain — which lets the
    /// ladder step by 2 and halve the number of probes.
    fn mtdf(&mut self, s: &State, guess: i16) -> i16 {
        let t = s.trick as usize;
        let (mut lo, mut hi) = (MIND[t], MAXD[t]);
        if lo >= hi {
            return lo;
        }
        // Parity of the reachable value set: each remaining trick contributes
        // an odd amount exactly when it is a -1 trick.
        let par = (MAXD[t] & 1).abs();
        let mut g = guess.clamp(lo, hi);
        if (g & 1).abs() != par {
            g += 1;
        }
        while lo < hi {
            let beta = if g <= lo { lo + 2 } else { g };
            let v = self.search(s, beta - 2, beta);
            if v < beta {
                hi = v;
            } else {
                lo = v;
            }
            g = v;
        }
        g
    }

    /// Value of every legal move, in the order `State::legal` produces them.
    /// Each is solved exactly — PIMC averages these across determinizations,
    /// so bounds from a narrowed window would be wrong to average.
    pub fn solve_root(&mut self, s: &State, moves: &[u8], out: &mut [i16]) {
        let mut guess = 0i16;
        for (i, &c) in moves.iter().enumerate() {
            let mut t = *s;
            let g = t.play(c) as i16;
            // Sibling moves usually score close together, so seeding MTD(f)
            // with the previous answer saves most of the ladder.
            let v = if self.use_mtdf {
                g + self.mtdf(&t, guess - g)
            } else {
                g + self.search(&t, -64, 64)
            };
            out[i] = v;
            guess = v;
        }
    }

    fn search(&mut self, s: &State, mut alpha: i16, mut beta: i16) -> i16 {
        if s.done() {
            return 0;
        }
        // Nothing left to play for can still decide the node.
        let t = s.trick as usize;
        if self.use_bounds {
            if MAXD[t] <= alpha {
                return MAXD[t];
            }
            if MIND[t] >= beta {
                return MIND[t];
            }
        }
        self.nodes += 1;

        let key = key_of(s);
        let slot = (key as usize) & self.mask;
        let mut hint = NO_MOVE;
        {
            let e = unsafe { *self.tt.get_unchecked(slot) };
            if e.flag != F_EMPTY && e.key == key {
                let v = e.val as i16;
                match e.flag {
                    F_EXACT => return v,
                    F_LOWER if v >= beta => return v,
                    F_UPPER if v <= alpha => return v,
                    _ => {}
                }
                hint = e.mv;
            }
        }

        let (a0, b0) = (alpha, beta);
        let mover = s.to_play() as usize;
        let maxing = mover == 0;

        let mut moves = [0u8; 16];
        let n = s.legal(&mut moves);
        let n = self.prune_and_order(s, mover, &mut moves, n, hint);

        let mut best: i16 = if maxing { -64 } else { 64 };
        let mut best_mv = moves[0];
        for i in 0..n {
            let mut t = *s;
            let g = t.play(moves[i]) as i16;
            // The child reports the differential AFTER this trick's `g`, so its
            // window must be shifted by g. Handing it the parent's window makes
            // every cutoff and every static bound comparison off by the trick's
            // value — wide windows hide it, tight ones do not.
            let v = g + self.search(&t, alpha - g, beta - g);
            if maxing {
                if v > best {
                    best = v;
                    best_mv = moves[i];
                }
                if best > alpha {
                    alpha = best;
                }
            } else {
                if v < best {
                    best = v;
                    best_mv = moves[i];
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
            F_UPPER
        } else if best >= b0 {
            F_LOWER
        } else {
            F_EXACT
        };
        let ent = Entry {
            key,
            val: best as i8,
            flag,
            mv: best_mv,
        };
        unsafe { *self.tt.get_unchecked_mut(slot) = ent };
        best
    }

    /// Drop provably-redundant moves, then sort by how likely they are to be
    /// best. Both are pure node-count wins; neither changes the value.
    fn prune_and_order(
        &self,
        s: &State,
        mover: usize,
        moves: &mut [u8; 16],
        n: usize,
        hint: u8,
    ) -> usize {
        // The led card has already left its owner's holding, but it still ranks
        // between cards and still decides this trick — so it must count when
        // testing whether two of our cards are interchangeable. Without it, K
        // and J look adjacent while the led Q sits between them.
        let mut inplay = s.in_play();
        if s.led >= 0 {
            inplay |= 1 << (s.led as u8);
        }
        let hand = s.hand[mover];

        // Equivalence collapse: two cards of the same follow-suit CLASS with no
        // in-play card between them are interchangeable — but only if BOTH sit
        // in hand. Two pile tops are never equivalent, because they cover
        // different cards, and a hand card is never equivalent to a pile top
        // for the same reason. Keep the lower of each run.
        //
        // The class, not the suit, and under Grand that changes the answer in
        // both directions. A ten is no longer between its own 9 and J, so those
        // two ARE adjacent — reading the raw suit mask would find the ten
        // sitting between them and refuse a collapse that is legal. And all
        // four tens are mutually interchangeable (they cannot even be ranked
        // against each other), which the trump class expresses and the four
        // separate suit masks cannot.
        let mut kept = [0u8; 16];
        let mut score = [0i32; 16];
        let mut k = 0;
        let want_win = trick_value(s.trick) > 0;
        for i in 0..n {
            let c = moves[i];
            if self.use_equiv && hand & (1 << c) != 0 {
                let below = follow_mask(esuit(c, s.trump), s.trump)
                    & inplay
                    & (((1 as Mask) << c) - 1);
                if below != 0 {
                    let lower = Mask::BITS - 1 - below.leading_zeros();
                    if hand & (1 << lower) != 0 {
                        continue; // the lower card plays identically
                    }
                }
            }
            let r = rank(c) as i32;
            // Order by this trick's intent: on a +2 trick the mover wants it,
            // on a -1 trick they want to duck it.
            let mut sc = if s.led >= 0 {
                let w = beats(s.led as u8, c, s.trump);
                match (want_win, w) {
                    (true, true) => 1000 - r,   // win as cheaply as possible
                    (true, false) => r,         // can't win: keep the big ones
                    (false, false) => 1000 + r, // duck, and dump something big
                    (false, true) => 100 - r,   // forced to win: pay the least
                }
            } else {
                let trumpish = esuit(c, s.trump) == trump_class(s.trump);
                if want_win {
                    r + if trumpish { 7 } else { 0 }
                } else {
                    // Lead low: the point is to force the odd trick onto them.
                    (6 - r) - if trumpish { 7 } else { 0 }
                }
            };
            // Tiebreak toward the hand — playing a pile top hands the opponent
            // a free look at the card underneath.
            if hand & (1 << c) != 0 {
                sc += 1;
            }
            if c == hint {
                sc += 100_000; // whatever refuted this node last time
            }
            kept[k] = c;
            score[k] = sc;
            k += 1;
        }

        for i in 1..k {
            let (c, sc) = (kept[i], score[i]);
            let mut j = i;
            while j > 0 && score[j - 1] < sc {
                kept[j] = kept[j - 1];
                score[j] = score[j - 1];
                j -= 1;
            }
            kept[j] = c;
            score[j] = sc;
        }
        moves[..k].copy_from_slice(&kept[..k]);
        k
    }
}
