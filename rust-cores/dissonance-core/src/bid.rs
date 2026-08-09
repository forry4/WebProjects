//! The Hard tier's AUCTION, served the same way its card play is.
//!
//! WHAT THE OLD BOT DID. `bot.py` scored a hand by summing a rank-value curve
//! and mapping the total onto a level through hand-placed thresholds. Those
//! thresholds are guesses — `games/dissonance/CLAUDE.md` says so outright — and
//! they drive four different decisions (the classic bid, the skat number, the
//! declaration and which denomination the talon swap aims at), so being wrong
//! about a hand is wrong four times over.
//!
//! WHAT THIS DOES INSTEAD. Sample deals consistent with what the seat knows,
//! and in each one SOLVE the hand exactly in every denomination: what is the
//! most the declarer can guarantee, and can they take no +2 trick at all. Then
//! price every option the server says is legal against the payoff the server
//! says it pays. No thresholds anywhere.
//!
//! THE ONE APPROXIMATION, stated because it is the difference between this and
//! an exact answer. `solve` gives the most a declarer can guarantee when BOTH
//! sides play for points, which is not the same as either side playing for the
//! contract — past their target the declarer stops caring, and a defender who
//! cannot hold them down switches to bursting them. Pricing every candidate
//! exactly would need a `solve_contract` per (denomination, level) per world,
//! and the auction offers up to ~50 of those against five denominations. So the
//! points solve is the proxy and the payoff arithmetic is exact on top of it.
//! `auction.rs` has made the same trade since the design campaign.
//!
//! Null rides along for free and is the reason this is not just the old
//! `eval_hand`: since it stopped being a bid, a contract's value is not
//! `payoff(points)` any more but `max(payoff(points), null if I can duck)` —
//! and "can I duck in THIS trump" is a per-denomination question, where the old
//! Null was always played at no trump.

use crate::cards::{esuit, rank, Mask, DENOMS, NDENOM_SLOTS};
use crate::dd::Dd;
use crate::rng::Rng;
use crate::state::{State, POOL};
use crate::view::View;

/// One thing the seat could do, priced by the SERVER. Every number here comes
/// from `engine.payoff_terms` for that candidate contract, so the search is
/// ranking options against the score the room will actually pay rather than
/// against a second copy of the rules.
#[derive(Clone, Copy, Debug)]
pub struct Option_ {
    pub denom: u8,
    /// Trick points the declarer would be promising (Sharp included).
    pub target: i32,
    pub make: i32,
    /// What each point past the target adds to a made contract: 0 in classic,
    /// +1 in skat. It prices an option UPWARDS by the margin the guaranteed
    /// total already clears the target by — which is exactly the hand that
    /// should be declaring above its bid rather than at the minimum.
    pub over: i32,
    pub set_base: i32,
    pub short: i32,
    /// The Double's escalator -- see `dd::Contract::ramp`. 0 undoubled.
    pub ramp: i32,
    /// The Null consolation, if it applies to this option.
    pub null: i32,
    /// PRICED FOR THE OPPONENT. A pass hands the standing contract to them, so
    /// it is worth minus what that contract pays THEM -- which needs a solve of
    /// the same denomination with the other seat declaring (they lead) and the
    /// result negated, because every option in the list is signed for the seat
    /// being asked. False on every option a seat could buy for itself.
    pub opp: bool,
    /// A skat pass-out: nothing stands, the hand is thrown in. Worth 0 by
    /// symmetry -- a fresh deal neither seat has seen -- and priced rather than
    /// omitted so `pass` is always in the list when it is legal.
    pub redeal: bool,
}

impl Option_ {
    /// Declarer score minus defender score, given what the declarer can
    /// guarantee in this denomination and whether they could duck instead.
    ///
    /// The MAX is the whole point: a declarer holding a hand that cannot reach
    /// the target is not simply set any more, they can take the consolation —
    /// so a contract is worth the better of the two plans, and a bot that
    /// priced only the first would decline hands it should be bidding.
    #[inline]
    pub fn payoff(&self, guaranteed_pts: i32, can_duck: bool) -> i32 {
        let contract = if guaranteed_pts >= self.target {
            self.make + self.over * (guaranteed_pts - self.target)
        } else {
            let s = self.target - guaranteed_pts;
            -(self.set_base + self.short * s + self.ramp * s * (s + 1) / 2)
        };
        if can_duck {
            contract.max(self.null)
        } else {
            contract
        }
    }
}

/// The classic talon swap, as DATA from the server (2026-08-08).
///
/// WHY THE LEAF MODELS THE TALON AT ALL. `solve_world` used to solve the deal
/// AS DEALT, so winning an auction was priced without the thing winning it
/// buys. That was harmless while the server's swap policy was worth -0.48
/// against standing pat; the fitted replacement is worth **+1.500 +- 0.208**,
/// so a leaf that ignores it now under-prices every contract we could declare
/// by about a point and a half -- a one-directional bias toward CONCEDING, on
/// top of the tree's other documented leans the same way.
///
/// THE WEIGHTS CROSS THE WIRE; only the feature arithmetic lives here. They
/// are `bot.py`'s fitted constants (`_SWAP_TAKE_W` et al.), shipped on the
/// armed request, so re-fitting the policy server-side moves this leaf with no
/// Rust change and no wasm rebuild -- the same discipline as `payoff_terms`.
/// `tests/fixtures/swap_policy.jsonl` holds the two implementations of the
/// arithmetic to one answer.
///
/// Absent from the request (an old server, a skat room, a non-auction phase)
/// the leaf prices the deal as dealt, exactly as before.
#[derive(Clone, Copy, Debug, Default)]
pub struct SwapPolicy {
    pub take_w: [f64; 8],
    pub give_w: [f64; 8],
    pub take_trump: f64,
    pub give_trump: f64,
    pub void: f64,
    pub singleton: f64,
    pub length: f64,
}

impl SwapPolicy {
    /// The exchange `bot.choose_swap`'s classic branch would make, or None to
    /// stand pat. Iteration is ascending card id on both axes with a strict
    /// `>`, which is the Python branch's own tie-break once `shown` is read in
    /// sorted order; f64 throughout so equal inputs give equal sums.
    pub fn choose(&self, hand: Mask, shown: Mask, trump: u8) -> Option<(u8, u8)> {
        let tc = crate::cards::trump_class(trump);
        let mut best: Option<(u8, u8)> = None;
        let mut best_score = 0.0f64;
        let mut sm = shown;
        while sm != 0 {
            let t = sm.trailing_zeros() as u8;
            sm &= sm - 1;
            let mut hm = hand;
            while hm != 0 {
                let h = hm.trailing_zeros() as u8;
                hm &= hm - 1;
                let mut sc = self.take_w[rank(t) as usize] + self.give_w[rank(h) as usize];
                if esuit(t, trump) == tc {
                    sc += self.take_trump;
                }
                if esuit(h, trump) == tc {
                    sc += self.give_trump;
                }
                let (mut give_suit, mut take_suit) = (0u32, 0u32);
                let mut m = hand;
                while m != 0 {
                    let c = m.trailing_zeros() as u8;
                    m &= m - 1;
                    let e = esuit(c, trump);
                    give_suit += (e == esuit(h, trump)) as u32;
                    take_suit += (e == esuit(t, trump)) as u32;
                }
                if give_suit == 1 {
                    sc += self.void;
                } else if give_suit == 2 {
                    sc += self.singleton;
                }
                sc += self.length * take_suit as f64 / 7.0;
                if sc > best_score {
                    best_score = sc;
                    best = Some((t, h));
                }
            }
        }
        best
    }

    /// Cache identity: an entry solved under one policy must never answer for
    /// another (or for none). The contract-table bug was this exact shape.
    pub fn key(&self) -> u64 {
        let mut h: u64 = 0x51A9_0000_0001;
        let mut mix = |x: f64| {
            h ^= x.to_bits();
            h = h.wrapping_mul(0x1000_0000_01b3);
        };
        for w in self.take_w {
            mix(w);
        }
        for w in self.give_w {
            mix(w);
        }
        for w in [self.take_trump, self.give_trump, self.void, self.singleton, self.length] {
            mix(w);
        }
        h
    }
}

/// What one sampled deal says about a seat's hand, per denomination.
#[derive(Clone, Copy, Default)]
pub struct World {
    /// Most the declarer can guarantee, with both sides playing for points.
    /// Indexed by WIRE denomination, so Grand's slot is 6 and Null's 5 is a
    /// hole nothing ever writes.
    pub pts: [i32; NDENOM_SLOTS],
    /// Could the declarer take NO +2 trick, in that denomination as trump?
    pub duck: [bool; NDENOM_SLOTS],
    /// The same two questions with the OPPONENT declaring, for pricing a pass.
    /// A separate solve, not a sign flip of the above: the declarer LEADS, so
    /// swapping who declares changes the position, not just the perspective.
    pub opp_pts: [i32; NDENOM_SLOTS],
    pub opp_duck: [bool; NDENOM_SLOTS],
}

/// The sampled deals AND what has been solved on them so far.
///
/// The two halves are stored together because the cache extends: a later round
/// asking about a denomination this one did not cover must solve it on the SAME
/// deals, or the new denomination would be priced against a different sample
/// than its rivals and the comparison between them would be noise.
#[derive(Clone, Default)]
pub struct Solved {
    /// The determinizations, kept so a missing denomination can be filled in.
    pub deals: Vec<State>,
    /// Three of each deal's six out-cards, sampled once as that world's talon
    /// SHOWN set. Sampled WITH the deal and stored, never re-drawn: the cache
    /// fills denominations incrementally, and a shown set that moved between
    /// fills would price denominations against different talons -- the exact
    /// between-denomination noise the `covered` mask exists to prevent.
    pub shown: Vec<Mask>,
    /// Bit d set once every deal has been solved in denomination d.
    pub covered: u8,
    /// ...and the same for the OPPONENT-declaring solves a pass needs. Kept
    /// apart because the two sides are asked for independently: an auction
    /// round wants our five and their one, and the sets do not move together.
    pub covered_opp: u8,
    pub worlds: Vec<World>,
}

/// Solve one determinized deal in every denomination in `todo`.
///
/// Only the denominations actually asked about: a declaration that has already
/// fixed its trump asks about one, and paying for the other four would be four
/// full 13-trick solves thrown away.
fn solve_world(dd: &mut Dd, base: &State, declarer: usize, wanted: u8, w: &mut World,
               for_opponent: bool, shown: Mask, swap: Option<&SwapPolicy>) {
    // MTD(f) converges by a ladder of null-window probes, so each denomination
    // seeds the next: the same hand is worth a similar amount in hearts and in
    // spades, and the first full solve pays for the other four.
    let mut guess = 0i16;
    for d in DENOMS {
        if wanted & (1 << d) == 0 {
            continue;
        }
        // The declarer leads, which is the shipped rule and worth ~0.93 points
        // — evaluating from the wrong lead misprices every hand the same way.
        let mut s = State {
            trump: d,
            trick: 0,
            led: -1,
            leader: declarer as u8,
            pts: [0, 0],
            escored: 0,
            ..*base
        };
        // THE TALON. Whoever declares gets shown three out-cards and may swap
        // one in; the policy is denomination-aware, so the edit is per trump.
        // The give card goes to the out set, which the State represents only
        // by absence -- so the whole swap is one hand edit.
        if let Some(sp) = swap {
            if let Some((take, give)) = sp.choose(s.hand[declarer], shown, d) {
                s.hand[declarer] = (s.hand[declarer] & !(1 << give)) | (1 << take);
            }
        }
        let raw = dd.solve_from(&s, guess);
        guess = raw;
        let diff = raw as i32;
        let p0 = (POOL as i32 + diff) / 2;
        let mine = if declarer == 0 { p0 } else { POOL as i32 - p0 };
        let duck = dd.null_no_even_makeable(&s, declarer);
        if for_opponent {
            w.opp_pts[d as usize] = mine;
            w.opp_duck[d as usize] = duck;
        } else {
            w.pts[d as usize] = mine;
            w.duck[d as usize] = duck;
        }
    }
}

/// Sum each option's declarer-signed payoff over `k` sampled deals.
///
/// Returned per option INDEX, in the caller's order, so the totals are additive
/// across workers exactly the way the card search's are — the option list is
/// the server's and identical everywhere, so index `i` means the same candidate
/// in every worker and in the pick.
pub fn wanted_denoms(opts: &[Option_]) -> (u8, u8) {
    let (mut mine, mut theirs) = (0u8, 0u8);
    for o in opts {
        // Membership, not a range check: 5 is Null, which is never a trump,
        // and Grand's 6 sits above no-trump's 4 rather than beside it.
        if o.redeal || !DENOMS.contains(&o.denom) {
            continue;
        }
        if o.opp { theirs |= 1 << o.denom } else { mine |= 1 << o.denom }
    }
    (mine, theirs)
}

/// THE EXPENSIVE HALF: sample `k` deals and solve each in every wanted
/// denomination. Separated from the pricing because it is worth CACHING, and
/// the pricing is not.
///
/// An auction asks the same question of the same cards several times over — a
/// classic auction can run five or six rounds and a skat ladder more — and the
/// hand does not change while it does. The answer here depends only on what the
/// seat HOLDS, so it survives every one of those rounds; only the option list
/// changes, and pricing is arithmetic. Recomputing it per round was the single
/// biggest cost in the first wired version.
///
/// WHICH IS WHY THIS EXTENDS RATHER THAN REPLACES. The option list does not just
/// change, it SHRINKS: a classic seat cannot re-bid a denomination it has
/// already named, so the denominations asked about run 5, 5, 4, 4, 3, 3, 2 down
/// the auction. Keying the cache on the set asked for made every one of those
/// steps a miss that re-solved denominations already in hand — the whole auction
/// paid the opening's price on every round. The set asked for is now a QUERY
/// against what has been solved, not part of its identity: a subset is a hit,
/// and a superset solves only the difference, on the same deals.
pub fn solve_into(v: &View, dd: &mut Dd, rng: &mut Rng, k: usize,
                  wanted: u8, wanted_opp: u8, declarer: usize, cache: &mut Solved,
                  swap: Option<&SwapPolicy>) {
    let k = k.max(1);
    if cache.deals.len() != k {
        // A different world count is a different sample: start over rather than
        // mixing two of them.
        let mut buf: Vec<u8> = Vec::with_capacity(16);
        cache.deals = (0..k).map(|_| v.determinize(rng, &mut buf)).collect();
        // The world's out-cards are whatever the determinizer did not place;
        // three of them are that world's talon. Sampled here, kept for the
        // entry's whole life (see the field's doc).
        cache.shown = cache.deals.iter().map(|d| {
            let mut placed: Mask = d.hand[0] | d.hand[1];
            for q in 0..2 {
                for i in 0..3 {
                    let p = &d.pile[q][i];
                    for j in 0..p.n as usize {
                        placed |= 1 << p.c[j];
                    }
                }
            }
            let mut out = crate::cards::ALL & !placed;
            let mut shown: Mask = 0;
            for _ in 0..3 {
                if out == 0 {
                    break;
                }
                let n = out.count_ones();
                let mut pick = rng.below(n as usize) as u32;
                let mut o = out;
                while pick > 0 {
                    o &= o - 1;
                    pick -= 1;
                }
                let c = o.trailing_zeros();
                shown |= 1 << c;
                out &= !(1 << c);
            }
            shown
        }).collect();
        cache.worlds = vec![World::default(); k];
        cache.covered = 0;
        cache.covered_opp = 0;
    }
    let todo = wanted & !cache.covered;
    let todo_opp = wanted_opp & !cache.covered_opp;
    if todo == 0 && todo_opp == 0 {
        return;
    }
    for ((deal, w), &shown) in cache.deals.iter().zip(cache.worlds.iter_mut())
        .zip(cache.shown.iter())
    {
        if todo != 0 {
            solve_world(dd, deal, declarer, todo, w, false, shown, swap);
        }
        if todo_opp != 0 {
            // The other seat declaring, which is a DIFFERENT position and not a
            // sign flip: the declarer leads to trick 1. The SAME shown set:
            // `shown_at_deal` is fixed before the auction, whoever wins it.
            solve_world(dd, deal, 1 - declarer, todo_opp, w, true, shown, swap);
        }
    }
    cache.covered |= todo;
    cache.covered_opp |= todo_opp;
}

/// THE CHEAP HALF: price each option against already-solved deals.
///
/// `have` is what the worlds actually hold. An option in a denomination nobody
/// solved must be left at zero rather than read out of a default `World`, where
/// it would price as a flat 0 points in every deal — a plausible-looking number
/// that would outrank genuinely bad contracts.
pub fn price(opts: &[Option_], worlds: &[World], have: u8, have_opp: u8) -> Vec<f64> {
    let mut sums = vec![0f64; opts.len()];
    for w in worlds {
        for (i, o) in opts.iter().enumerate() {
            // A pass-out is worth 0 in every world -- a fresh deal, by
            // symmetry -- and needs no solve at all.
            if o.redeal {
                continue;
            }
            let d = o.denom as usize;
            let mask = if o.opp { have_opp } else { have };
            if d >= NDENOM_SLOTS || mask & (1 << d) == 0 {
                continue;
            }
            // NEGATED for a pass: the option is priced for the opponent, and
            // every entry in this list is signed for the seat being asked.
            sums[i] += if o.opp {
                -o.payoff(w.opp_pts[d], w.opp_duck[d]) as f64
            } else {
                o.payoff(w.pts[d], w.duck[d]) as f64
            };
        }
    }
    sums
}

/// What the seat HOLDS, as one number. Two auction decisions with the same key
/// are asking about the same cards and can share a solve; the talon swap
/// changes the hand and so changes this.
///
/// The denominations asked about are deliberately NOT in here — see
/// `solve_into`. `declarer` is, because it decides who leads, and `k` is,
/// because it decides how many deals the entry holds.
pub fn hand_key(v: &View, declarer: usize, k: usize) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    let mut mix = |x: u64| {
        h ^= x;
        h = h.wrapping_mul(0x1000_0000_01b3);
    };
    mix(v.s.hand[v.me]);
    mix(v.pool);
    mix(v.opp_hand_n as u64);
    mix((declarer as u64) << 8 | ((k as u64) << 16));
    mix(v.s.trump as u64 | ((v.first_leader as u64) << 8));
    for q in 0..2 {
        for i in 0..3 {
            let p = &v.s.pile[q][i];
            mix((p.n as u64) << 16 | (p.c[0] as u64) << 8 | p.c[1] as u64);
        }
    }
    h
}

pub fn eval_options(v: &View, dd: &mut Dd, rng: &mut Rng, k: usize,
                    opts: &[Option_], declarer: usize) -> Vec<f64> {
    if opts.is_empty() {
        return Vec::new();
    }
    let (wanted, wanted_opp) = wanted_denoms(opts);
    let mut cache = Solved::default();
    solve_into(v, dd, rng, k, wanted, wanted_opp, declarer, &mut cache, None);
    price(opts, &cache.worlds, cache.covered, cache.covered_opp)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A classic-mode option: a made contract pays flat, so `over` is 0.
    /// Set pays N + 4 a point short (2026-08-07: N, not N-1).
    fn opt(target: i32, make: i32, null: i32) -> Option_ {
        Option_ { denom: 0, target, make, over: 0, ramp: 0, opp: false, redeal: false,
                  set_base: target, short: 4, null }
    }

    /// A skat-mode option: the same contract with the overtrick bonus on it.
    fn skat_opt(target: i32, make: i32, null: i32) -> Option_ {
        Option_ { over: 1, set_base: make, ..opt(target, make, null) }
    }

    #[test]
    fn overtricks_price_a_skat_option_above_its_stake() {
        // Three points past a target of 4, at +1 each.
        assert_eq!(skat_opt(4, 16, 20).payoff(7, false), 19);
        assert_eq!(skat_opt(4, 16, 20).payoff(4, false), 16, "on target is the stake");
        // The bonus applies to the MAKE only -- being set is still the
        // shortfall rule, and it is the skat stake that is at risk.
        assert_eq!(skat_opt(4, 16, 20).payoff(1, false), -(16 + 4 * 3));
        // What it does to the "a cheap contract is a licence to duck" cliff: it
        // NARROWS the gap without closing it at the bottom. A stake of 6 played
        // out to the declarer's ceiling of 12 points is worth 6 + 9 = 15 — up
        // from a flat 6, and still under the consolation's 20, so this hand
        // ducks either way.
        assert_eq!(skat_opt(3, 6, 20).payoff(12, false), 15);
        assert_eq!(skat_opt(3, 6, 20).payoff(12, true), 20, "the duck still wins");
        // Dearer, and the contract is worth playing out on its own.
        assert_eq!(skat_opt(4, 20, 20).payoff(12, true), 28);
    }

    #[test]
    fn a_hand_that_reaches_the_target_is_worth_the_contract() {
        assert_eq!(opt(4, 16, 12).payoff(5, false), 16);
        assert_eq!(opt(4, 16, 12).payoff(4, false), 16, "exactly on target makes it");
    }

    #[test]
    fn falling_short_is_paid_by_the_shortfall() {
        // level 4, finishing on 1: -(4 + 4 x 3)
        assert_eq!(opt(4, 16, 12).payoff(1, false), -16);
    }

    #[test]
    fn a_declarer_who_can_duck_takes_the_better_of_the_two_plans() {
        // Hopeless on points, but the consolation is there: take it.
        assert_eq!(opt(6, 36, 12).payoff(-2, true), 12);
        // ...and a hand that MAKES the contract does not want the consolation,
        // which is the direction a naive `max` would get wrong if `null` were
        // ever bigger than a made contract of that size.
        assert_eq!(opt(6, 36, 12).payoff(6, true), 36);
        // The cliff the rule actually puts in the game: at these levels a made
        // contract is worth LESS than ducking, so the search prefers to duck.
        assert_eq!(opt(3, 9, 12).payoff(3, true), 12);
        assert_eq!(opt(3, 9, 12).payoff(3, false), 9, "...only when it can");
    }

    /// The bug this file was optimised for: a classic auction asks about fewer
    /// denominations every round, and re-solving the ones already in hand cost
    /// the opening's full price on every one of them.
    #[test]
    fn narrowing_the_denominations_asked_about_costs_nothing() {
        let mut dd = Dd::new(14);
        let mut rng = Rng::new(3);
        let g = crate::game::Game::deal(&mut Rng::new(11), 0, 0);
        let v = View::of(&g, 0);
        let mut cache = Solved::default();
        solve_into(&v, &mut dd, &mut rng, 2, 0b11111, 0, 0, &mut cache, None);
        assert_eq!(cache.covered, 0b11111);
        let after_open = dd.nodes;
        let pts = cache.worlds[0].pts;

        // The auction narrows, exactly as `auction_payoff_options` does.
        for wanted in [0b11111u8, 0b11110, 0b11100, 0b11000] {
            solve_into(&v, &mut dd, &mut rng, 2, wanted, 0, 0, &mut cache, None);
        }
        assert_eq!(dd.nodes, after_open, "a subset must not search a single node");
        assert_eq!(cache.worlds[0].pts, pts, "...nor disturb what was solved");
    }

    #[test]
    fn asking_about_a_new_denomination_solves_only_that_one() {
        let mut dd = Dd::new(14);
        let mut rng = Rng::new(3);
        let g = crate::game::Game::deal(&mut Rng::new(11), 0, 0);
        let v = View::of(&g, 0);
        let mut cache = Solved::default();
        solve_into(&v, &mut dd, &mut rng, 2, 0b00001, 0, 0, &mut cache, None);
        let first = cache.worlds[0].pts[0];
        let deals = cache.deals.clone();

        solve_into(&v, &mut dd, &mut rng, 2, 0b00011, 0, 0, &mut cache, None);
        assert_eq!(cache.covered, 0b00011);
        // The new denomination is solved on the SAME deals, so the two are
        // comparable — a fresh sample would make the choice between them noise.
        assert_eq!(cache.deals.len(), deals.len());
        for (a, b) in cache.deals.iter().zip(deals.iter()) {
            assert_eq!(a.hand, b.hand);
        }
        assert_eq!(cache.worlds[0].pts[0], first, "the old answer is untouched");
    }

    #[test]
    fn an_unsolved_denomination_prices_at_zero_not_at_a_default_world() {
        // `World::default()` reads as 0 points, which is a real-looking value.
        // An option nobody solved must contribute nothing instead.
        let o = Option_ { denom: 3, ..opt(4, 16, 12) };
        let worlds = vec![World::default()];
        assert_eq!(price(&[o], &worlds, 0b00000, 0), vec![0.0]);
        assert_eq!(price(&[o], &worlds, 0b01000, 0), vec![-20.0]);   // -(4 + 4x4)
    }

    #[test]
    fn a_pass_is_priced_from_the_OPPONENTS_side_and_negated() {
        // The whole point: a pass hands the standing contract to them, so it is
        // worth MINUS what it pays them -- and that needs its own solve, because
        // the declarer LEADS. A sign flip of our own solve would be a different
        // (and wrong) number.
        let mut dd = Dd::new(14);
        let mut rng = Rng::new(5);
        let g = crate::game::Game::deal(&mut Rng::new(31), 0, 0);
        let v = View::of(&g, 0);
        let mut cache = Solved::default();
        solve_into(&v, &mut dd, &mut rng, 2, 0b00100, 0b00100, 0, &mut cache, None);
        assert_eq!(cache.covered, 0b00100);
        assert_eq!(cache.covered_opp, 0b00100);

        let mine = Option_ { denom: 2, target: 3, make: 9, over: 1, set_base: 3,
                             short: 4, ramp: 0, null: 12, opp: false, redeal: false };
        let theirs = Option_ { opp: true, ..mine };
        let sums = price(&[mine, theirs], &cache.worlds, cache.covered, cache.covered_opp);
        let by_hand: f64 = cache.worlds.iter()
            .map(|w| -theirs.payoff(w.opp_pts[2], w.opp_duck[2]) as f64).sum();
        assert_eq!(sums[1], by_hand, "the pass is not the negated opponent solve");
        // ...and it is a genuinely different number from our own side, or the
        // separate solve would be buying nothing.
        assert!(cache.worlds.iter().any(|w| w.opp_pts[2] != w.pts[2]),
            "the two sides came out identical -- the opponent solve did not run");
    }

    #[test]
    fn a_pass_out_is_priced_at_zero_and_needs_no_solve() {
        let redeal = Option_ { denom: 0, target: 0, make: 0, over: 0, set_base: 0,
                               short: 0, ramp: 0, null: 0, opp: false, redeal: true };
        let (mine, theirs) = wanted_denoms(&[redeal]);
        assert_eq!((mine, theirs), (0, 0), "a pass-out asks for no solve at all");
        let worlds = vec![World::default(); 3];
        assert_eq!(price(&[redeal], &worlds, 0, 0), vec![0.0]);
    }

    #[test]
    fn the_two_denomination_masks_are_kept_apart() {
        let a = Option_ { denom: 2, target: 3, make: 9, over: 0, ramp: 0, set_base: 3,
                          short: 4, null: 12, opp: false, redeal: false };
        let b = Option_ { denom: crate::cards::GRAND, opp: true, ..a };
        let (mine, theirs) = wanted_denoms(&[a, b]);
        assert_eq!(mine, 1 << 2);
        assert_eq!(theirs, 1 << crate::cards::GRAND);
    }

    #[test]
    fn an_option_naming_no_denomination_is_skipped_not_panicked_on() {
        // The wire is server-supplied but not trusted to be in range.
        let bad = Option_ { denom: 99, target: 1, make: 1, over: 0, ramp: 0, opp: false, redeal: false,
                            set_base: 0, short: 4, null: 12 };
        let mut dd = Dd::new(10);
        let mut rng = Rng::new(1);
        let g = crate::game::Game::deal(&mut Rng::new(7), 0, 0);
        let v = View::of(&g, 0);
        let sums = eval_options(&v, &mut dd, &mut rng, 1, &[bad], 0);
        assert_eq!(sums, vec![0.0]);
    }
}
