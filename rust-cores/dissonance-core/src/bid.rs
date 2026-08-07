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

use crate::cards::{DENOMS, NDENOM_SLOTS};
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
    pub set_base: i32,
    pub short: i32,
    /// The Null consolation, if it applies to this option.
    pub null: i32,
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
            self.make
        } else {
            -(self.set_base + self.short * (self.target - guaranteed_pts))
        };
        if can_duck {
            contract.max(self.null)
        } else {
            contract
        }
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
    /// Bit d set once every deal has been solved in denomination d.
    pub covered: u8,
    pub worlds: Vec<World>,
}

/// Solve one determinized deal in every denomination in `todo`.
///
/// Only the denominations actually asked about: a declaration that has already
/// fixed its trump asks about one, and paying for the other four would be four
/// full 13-trick solves thrown away.
fn solve_world(dd: &mut Dd, base: &State, declarer: usize, wanted: u8, w: &mut World) {
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
        let s = State {
            trump: d,
            trick: 0,
            led: -1,
            leader: declarer as u8,
            pts: [0, 0],
            escored: 0,
            ..*base
        };
        let raw = dd.solve_from(&s, guess);
        guess = raw;
        let diff = raw as i32;
        let p0 = (POOL as i32 + diff) / 2;
        w.pts[d as usize] = if declarer == 0 { p0 } else { POOL as i32 - p0 };
        w.duck[d as usize] = dd.null_no_even_makeable(&s, declarer);
    }
}

/// Sum each option's declarer-signed payoff over `k` sampled deals.
///
/// Returned per option INDEX, in the caller's order, so the totals are additive
/// across workers exactly the way the card search's are — the option list is
/// the server's and identical everywhere, so index `i` means the same candidate
/// in every worker and in the pick.
pub fn wanted_denoms(opts: &[Option_]) -> u8 {
    let mut m = 0u8;
    for o in opts {
        // Membership, not a range check: 5 is Null, which is never a trump,
        // and Grand's 6 sits above no-trump's 4 rather than beside it.
        if DENOMS.contains(&o.denom) {
            m |= 1 << o.denom;
        }
    }
    m
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
                  wanted: u8, declarer: usize, cache: &mut Solved) {
    let k = k.max(1);
    if cache.deals.len() != k {
        // A different world count is a different sample: start over rather than
        // mixing two of them.
        let mut buf: Vec<u8> = Vec::with_capacity(16);
        cache.deals = (0..k).map(|_| v.determinize(rng, &mut buf)).collect();
        cache.worlds = vec![World::default(); k];
        cache.covered = 0;
    }
    let todo = wanted & !cache.covered;
    if todo == 0 {
        return;
    }
    for (deal, w) in cache.deals.iter().zip(cache.worlds.iter_mut()) {
        solve_world(dd, deal, declarer, todo, w);
    }
    cache.covered |= todo;
}

/// THE CHEAP HALF: price each option against already-solved deals.
///
/// `have` is what the worlds actually hold. An option in a denomination nobody
/// solved must be left at zero rather than read out of a default `World`, where
/// it would price as a flat 0 points in every deal — a plausible-looking number
/// that would outrank genuinely bad contracts.
pub fn price(opts: &[Option_], worlds: &[World], have: u8) -> Vec<f64> {
    let mut sums = vec![0f64; opts.len()];
    for w in worlds {
        for (i, o) in opts.iter().enumerate() {
            let d = o.denom as usize;
            if d >= NDENOM_SLOTS || have & (1 << d) == 0 {
                continue;
            }
            sums[i] += o.payoff(w.pts[d], w.duck[d]) as f64;
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
    let wanted = wanted_denoms(opts);
    let mut cache = Solved::default();
    solve_into(v, dd, rng, k, wanted, declarer, &mut cache);
    price(opts, &cache.worlds, cache.covered)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn opt(target: i32, make: i32, null: i32) -> Option_ {
        Option_ { denom: 0, target, make, set_base: (target - 1).max(0), short: 4, null }
    }

    #[test]
    fn a_hand_that_reaches_the_target_is_worth_the_contract() {
        assert_eq!(opt(4, 16, 12).payoff(5, false), 16);
        assert_eq!(opt(4, 16, 12).payoff(4, false), 16, "exactly on target makes it");
    }

    #[test]
    fn falling_short_is_paid_by_the_shortfall() {
        // level 4, finishing on 1: -(3 + 4 x 3)
        assert_eq!(opt(4, 16, 12).payoff(1, false), -15);
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
        solve_into(&v, &mut dd, &mut rng, 2, 0b11111, 0, &mut cache);
        assert_eq!(cache.covered, 0b11111);
        let after_open = dd.nodes;
        let pts = cache.worlds[0].pts;

        // The auction narrows, exactly as `auction_payoff_options` does.
        for wanted in [0b11111u8, 0b11110, 0b11100, 0b11000] {
            solve_into(&v, &mut dd, &mut rng, 2, wanted, 0, &mut cache);
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
        solve_into(&v, &mut dd, &mut rng, 2, 0b00001, 0, &mut cache);
        let first = cache.worlds[0].pts[0];
        let deals = cache.deals.clone();

        solve_into(&v, &mut dd, &mut rng, 2, 0b00011, 0, &mut cache);
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
        assert_eq!(price(&[o], &worlds, 0b00000), vec![0.0]);
        assert_eq!(price(&[o], &worlds, 0b01000), vec![-19.0]);   // -(3 + 4x4)
    }

    #[test]
    fn an_option_naming_no_denomination_is_skipped_not_panicked_on() {
        // The wire is server-supplied but not trusted to be in range.
        let bad = Option_ { denom: 99, target: 1, make: 1, set_base: 0, short: 4, null: 12 };
        let mut dd = Dd::new(10);
        let mut rng = Rng::new(1);
        let g = crate::game::Game::deal(&mut Rng::new(7), 0, 0);
        let v = View::of(&g, 0);
        let sums = eval_options(&v, &mut dd, &mut rng, 1, &[bad], 0);
        assert_eq!(sums, vec![0.0]);
    }
}
