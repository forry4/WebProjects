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
use crate::state::State;
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
        let contract = self.contract_value(guaranteed_pts);
        if can_duck {
            contract.max(self.null)
        } else {
            contract
        }
    }

    /// The same price, EXACT: `payoff` above is the crate's one documented leaf
    /// error and this is what removes it.
    ///
    /// `payoff` takes the better of two SEPARATELY GUARANTEED plans -- reach the
    /// target, or duck every scoring trick -- and a declarer who can guarantee
    /// neither is credited with the worse of them. Real play does not work that
    /// way: the defender has to stop BOTH, and when they cannot, the declarer
    /// takes whichever the defence gave up. Measured over 900 (deal, contract)
    /// pairs, `payoff` agrees with an exact `solve_contract` 93.3% of the time
    /// and every one of the gaps is POSITIVE (+6.5 conditional, worst +27) --
    /// so the shipped leaf leans, one-directionally, toward CONCEDING.
    ///
    /// `threat` is `Dd::threat_value`: the most the declarer can force when the
    /// duck counts as winning outright. See that function for why two scalars
    /// are enough to price every level and every jump on one deal, which is the
    /// only reason an exact leaf is affordable in a tree that reaches fifty
    /// settlements.
    ///
    /// The fold, and each branch is a forcible set of outcomes:
    /// * `contract(P)` -- force `pts >= P`, taking whatever that pays;
    /// * `min(null, contract(Q))` -- force "duck OR `pts >= Q`", where the
    ///   defence picks whichever of the two is worse for us.
    ///
    /// A guaranteed duck is `Q == THREAT_TOP`, and the second branch collapses
    /// to `null` -- i.e. this REPRODUCES `payoff(.., true)` exactly there,
    /// which is what makes an A/B against it unconfounded.
    #[inline]
    pub fn payoff_exact(&self, guaranteed_pts: i32, threat: i32) -> i32 {
        let plain = self.contract_value(guaranteed_pts);
        if threat >= crate::dd::THREAT_TOP {
            return plain.max(self.null);
        }
        plain.max(self.null.min(self.contract_value(threat)))
    }

    /// What the contract alone pays at a point total, with no consolation --
    /// shared by both pricers so the two can never disagree about the curve.
    #[inline]
    fn contract_value(&self, pts: i32) -> i32 {
        if pts >= self.target {
            self.make + self.over * (pts - self.target)
        } else {
            let s = self.target - pts;
            -(self.set_base + self.short * s + self.ramp * s * (s + 1) / 2)
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
    /// `Dd::threat_value` -- the most the declarer can force when the duck
    /// counts as winning outright. With `pts` it prices every level and every
    /// jump EXACTLY (`Option_::payoff_exact`), which is the only reason an
    /// exact leaf fits in a tree that reaches fifty settlements. Solved only
    /// when the entry is an exact one; `duck` is then derived from it rather
    /// than searched separately.
    pub threat: [i32; NDENOM_SLOTS],
    /// The same two questions with the OPPONENT declaring, for pricing a pass.
    /// A separate solve, not a sign flip of the above: the declarer LEADS, so
    /// swapping who declares changes the position, not just the perspective.
    pub opp_pts: [i32; NDENOM_SLOTS],
    pub opp_duck: [bool; NDENOM_SLOTS],
    pub opp_threat: [i32; NDENOM_SLOTS],
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
    /// Whether these worlds carry `threat`, i.e. whether they can price an
    /// EXACT leaf. Part of the entry's identity rather than a detail: worlds
    /// solved without it answer a different question, and reading a zero
    /// `threat` as a real one would price every contract as though the
    /// declarer could force nothing at all -- a plausible-looking number, which
    /// is the failure shape this crate keeps paying for.
    pub exact: bool,
    pub worlds: Vec<World>,
    /// ONE BELIEF SAMPLE PER WORLD -- what the OPPONENT would be looking at, if
    /// the world at that index were the truth. Empty unless the tier asked for
    /// it (`OppModel::Belief`); see `belief_into`.
    ///
    /// A `Solved` inside a `Solved` is deliberate rather than a second type:
    /// the inner one is the same object doing the same job from the other
    /// seat's chair, and the tree reads it through the same `settled` it uses
    /// for ours. Nesting is ONE LEVEL by construction -- `belief_into` never
    /// fills the inner entries' own `belief`, so the modelled opponent models
    /// us as clairvoyant. That is the standard cut, and it is the honest place
    /// to make it: the regress is infinite and the second level is worth far
    /// less than the first.
    pub belief: Vec<Solved>,
}

/// Solve one determinized deal in every denomination in `todo`.
///
/// Only the denominations actually asked about: a declaration that has already
/// fixed its trump asks about one, and paying for the other four would be four
/// full 13-trick solves thrown away.
fn solve_world(dd: &mut Dd, base: &State, declarer: usize, wanted: u8, w: &mut World,
               for_opponent: bool, shown: Mask, swap: Option<&SwapPolicy>, exact: bool) {
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
        // The STATE's pool, not the classic constant: under minor parity the
        // pool is -1, and `(POOL + diff) / 2` would be the other player's
        // total half the time.
        let pool = s.pool() as i32;
        let p0 = (pool + diff) / 2;
        let mine = if declarer == 0 { p0 } else { pool - p0 };
        // THE EXACT LEAF SUBSUMES THE DUCKING SEARCH rather than adding to it:
        // a guaranteed duck is exactly the top of `threat_value`'s outcome
        // order, so this is one solve swapped for another and not a second one
        // bolted on. (`the_threat_value_prices_every_contract_exactly` asserts
        // the two agree, which is what lets this branch drop `nsearch`.)
        // Seeded with this denomination's own points value -- see
        // `Dd::threat_value`. `mine` is exactly the largest total the declarer
        // can force, and the threat can only be higher.
        let threat = if exact { dd.threat_value(&s, declarer, mine) } else { 0 };
        let duck = if exact {
            threat >= crate::dd::THREAT_TOP
        } else {
            dd.null_no_even_makeable(&s, declarer)
        };
        if for_opponent {
            w.opp_pts[d as usize] = mine;
            w.opp_duck[d as usize] = duck;
            w.opp_threat[d as usize] = threat;
        } else {
            w.pts[d as usize] = mine;
            w.duck[d as usize] = duck;
            w.threat[d as usize] = threat;
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
                  swap: Option<&SwapPolicy>, exact: bool) {
    let k = k.max(1);
    // The entry records which leaf it was solved FOR. An entry that has not
    // paid for the threat solves cannot price an exact leaf, and its zeroed
    // `threat` would read as "the declarer can force nothing" -- so the flag
    // rides with the worlds and the callers key on it.
    cache.exact = exact;
    deals_into(v, rng, k, cache, None);
    let todo = wanted & !cache.covered;
    let todo_opp = wanted_opp & !cache.covered_opp;
    if todo == 0 && todo_opp == 0 {
        return;
    }
    for ((deal, w), &shown) in cache.deals.iter().zip(cache.worlds.iter_mut())
        .zip(cache.shown.iter())
    {
        if todo != 0 {
            solve_world(dd, deal, declarer, todo, w, false, shown, swap, exact);
        }
        if todo_opp != 0 {
            // The other seat declaring, which is a DIFFERENT position and not a
            // sign flip: the declarer leads to trick 1. The SAME shown set:
            // `shown_at_deal` is fixed before the auction, whoever wins it.
            solve_world(dd, deal, 1 - declarer, todo_opp, w, true, shown, swap, exact);
        }
    }
    cache.covered |= todo;
    cache.covered_opp |= todo_opp;
}

/// One option against one world, by whichever leaf the entry was solved for.
///
/// ONE FUNCTION so the myopic and exact leaves can never disagree about which
/// scalars they read: the pricer and the tree both come through here, and the
/// `exact` flag is the entry's own (`Solved::exact`), never a caller's opinion.
#[inline]
pub fn leaf(o: &Option_, exact: bool, pts: i32, duck: bool, threat: i32) -> i32 {
    if exact {
        o.payoff_exact(pts, threat)
    } else {
        o.payoff(pts, duck)
    }
}

/// Solve, for every sampled world, the deals the OPPONENT would be choosing
/// against if that world were the truth.
///
/// THE COST, stated plainly: `k x m` extra determinizations, each solved in
/// every denomination the tree can price, on both sides. At the shipped k = 8
/// with m = 4 that is 4x the auction's solve budget -- which is why this is an
/// offline arm first and a serving question afterwards. Everything else about
/// the tier is unchanged, and `m = 0` does no work at all.
///
/// The belief sample is drawn from `View::belief_of`, i.e. from the OPPONENT's
/// information set in that world: they know the hand the world dealt them and
/// the same public cards, and OUR hand joins the pool they resample. So their
/// choice can depend on their own cards -- which is legitimate, they hold them
/// -- and cannot depend on ours, which is the whole point.
pub fn belief_into(v: &View, dd: &mut Dd, rng: &mut Rng, m: usize,
                   wanted: u8, wanted_opp: u8, declarer: usize,
                   cache: &mut Solved, swap: Option<&SwapPolicy>) {
    if m == 0 || cache.deals.is_empty() {
        return;
    }
    let opp = 1 - v.me;
    let mut out = Vec::with_capacity(cache.deals.len());
    for deal in &cache.deals {
        let bv = v.belief_of(deal.hand[opp]);
        let mut e = Solved::default();
        // The SAME denominations, both sides: the opponent is choosing among
        // the same settlements we are, and pricing their choice on a narrower
        // set would decide it for them.
        //
        // NOTE the sides swap with the seat: `belief_of` makes THEM the
        // observer, so what `solve_into` calls "mine" is theirs. The masks are
        // therefore crossed on the way in, and `Search` reads them back through
        // an inner search whose `me` is also them -- so the two agree by
        // construction rather than by a sign convention anyone has to remember.
        solve_into(&bv, dd, rng, m, wanted_opp, wanted, 1 - declarer, &mut e,
                   swap, false);
        out.push(e);
    }
    cache.belief = out;
}

/// THE CHEAP HALF: price each option against already-solved deals.
///
/// `have` is what the worlds actually hold. An option in a denomination nobody
/// solved must be left at zero rather than read out of a default `World`, where
/// it would price as a flat 0 points in every deal — a plausible-looking number
/// that would outrank genuinely bad contracts.
pub fn price(opts: &[Option_], worlds: &[World], have: u8, have_opp: u8,
             exact: bool) -> Vec<f64> {
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
                -leaf(o, exact, w.opp_pts[d], w.opp_duck[d], w.opp_threat[d]) as f64
            } else {
                leaf(o, exact, w.pts[d], w.duck[d], w.threat[d]) as f64
            };
        }
    }
    sums
}

/// Sample the determinized deals WITHOUT solving anything on them.
///
/// `solve_into` does this as its first step and then pays for a full points
/// solve per denomination. A decision on a SETTLED contract wants the deals and
/// none of that work, so the sampling is factored out here and both callers
/// share one definition of what a world IS -- two samplers would drift, and the
/// drift would be invisible (a slightly different world distribution is still a
/// perfectly plausible-looking answer).
/// THE AUCTION AS EVIDENCE — a belief prior over the declarer's hand (2026-08-14).
///
/// `determinize` samples the declarer's unseen cards UNIFORMLY from the pool.
/// But the declarer WON AN AUCTION, and a bid is loud evidence about the hand
/// that made it. MEASURED (`tools/beliefprobe.py`, 400 real rounds driven to the
/// double phase, 200 resamples each): the declarer's real holding sits at the
/// **0.765 percentile** of the uniform resample distribution, above the median
/// in 87.5% of rounds, and the gap GROWS with the level bid — 0.706 at level 3,
/// 0.830 at 5, 0.850 at 6. So every sampled world hands the declarer a weaker
/// hand than they really hold, contracts look likelier to fail than they are,
/// and a defender's search doubles too much. This is poker's "range" problem:
/// the belief has to be conditioned on the actions taken.
///
/// The correction is IMPORTANCE SAMPLING with an exponential tilt: draw `tries`
/// candidate worlds, weight each by `exp(tilt x strength)`, and keep one in
/// proportion. `tilt = 0` reproduces uniform sampling exactly, which is what
/// makes the A/B unconfoundable. Simulated over the same 400 rounds, a single
/// tilt of 0.40 re-centres the sample at 0.509.
///
/// THE LIKELIHOOD IS A MODELLING CHOICE, NOT A RULE, and that is deliberate: it
/// does not have to reproduce `bot.hand_strength` (whose suit-length terms would
/// be a second copy needing its own parity fixture), only to ORDER two holdings
/// the way a bidder would. So the curve crosses the wire as data — the
/// `swap_policy_terms` pattern — and a re-fit server-side moves it with no Rust
/// change and no wasm rebuild.
#[derive(Clone, Debug, Default)]
pub struct BidPrior {
    /// Worth per rank, indexed by strength (0 = the deck's lowest).
    pub curve: [f64; 10],
    /// What holding a card in the contract's own denomination multiplies by.
    pub trump_mult: f64,
    /// The tilt. 0 IS uniform sampling, in Rust and end to end.
    pub tilt: f64,
    /// Whose hand the evidence is about — the seat that won the auction.
    pub declarer: usize,
    /// Candidate worlds drawn per world kept. 1 disables the resampling.
    pub tries: usize,
}

impl BidPrior {
    /// The declarer's whole holding in a candidate world: hand plus every card
    /// still in their piles, which is exactly the thirteen they will play.
    fn strength(&self, s: &State) -> f64 {
        let tc = crate::cards::trump_class(s.trump);
        let mut tot = 0.0;
        let mut m = s.hand[self.declarer];
        while m != 0 {
            let c = m.trailing_zeros() as u8;
            m &= m - 1;
            tot += self.curve[rank(c) as usize]
                * if esuit(c, s.trump) == tc { self.trump_mult } else { 1.0 };
        }
        for i in 0..3 {
            let p = &s.pile[self.declarer][i];
            for j in 0..p.n as usize {
                let c = p.c[j];
                tot += self.curve[rank(c) as usize]
                    * if esuit(c, s.trump) == tc { self.trump_mult } else { 1.0 };
            }
        }
        tot
    }

    /// One world, drawn in proportion to how well it explains the bidding.
    pub fn draw(&self, v: &View, rng: &mut Rng, buf: &mut Vec<u8>) -> State {
        let tries = self.tries.max(1);
        if tries == 1 || self.tilt == 0.0 {
            return v.determinize(rng, buf);
        }
        let cands: Vec<State> = (0..tries).map(|_| v.determinize(rng, buf)).collect();
        let ss: Vec<f64> = cands.iter().map(|s| self.strength(s)).collect();
        // Shifted by the max before exponentiating: the shift cancels out of
        // the normalised weights and keeps `exp` off its overflow.
        let hi = ss.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let w: Vec<f64> = ss.iter().map(|s| (self.tilt * (s - hi)).exp()).collect();
        let tot: f64 = w.iter().sum();
        if !(tot > 0.0) || !tot.is_finite() {
            return cands.into_iter().next().unwrap();
        }
        // Fixed-point uniform: `Rng` deals in integers and a float draw here
        // would be one more thing to keep deterministic across targets.
        let mut r = tot * (rng.below(1 << 24) as f64) / ((1u32 << 24) as f64);
        for (i, wi) in w.iter().enumerate() {
            r -= wi;
            if r <= 0.0 {
                return cands[i];
            }
        }
        cands[tries - 1]
    }
}

/// ONE WORLD, honouring an optional prior — the single definition every sampler
/// in the crate goes through.
///
/// There are three of them (`deals_into` for the auction, `infer::sample_worlds`
/// for the card play, and `wasm::odd_pick_card`), and a prior applied in some
/// but not others is the quietest possible bug: every path still returns legal
/// moves, just searched against a different belief. Routing them all through
/// here means "does this sampler condition on the auction" has one answer.
#[inline]
pub fn draw_world(v: &View, rng: &mut Rng, buf: &mut Vec<u8>,
                  prior: Option<&BidPrior>) -> State {
    match prior {
        Some(p) => p.draw(v, rng, buf),
        None => v.determinize(rng, buf),
    }
}

/// It samples the world's talon too, even though a settled-contract caller has
/// no use for one: an entry filled here must be indistinguishable from an entry
/// filled by `solve_into`, or a later solve on the same key would run against a
/// world whose talon was never drawn and would quietly price the deal as dealt.
pub fn deals_into(v: &View, rng: &mut Rng, k: usize, cache: &mut Solved,
                  prior: Option<&BidPrior>) {
    let k = k.max(1);
    if cache.deals.len() == k {
        return;
    }
    // A different world count is a different sample: start over rather than
    // mixing two of them.
    let mut buf: Vec<u8> = Vec::with_capacity(16);
    cache.deals = (0..k).map(|_| draw_world(v, rng, &mut buf, prior)).collect();
    // The world's out-cards are whatever the determinizer did not place; three
    // of them are that world's talon. Sampled here, kept for the entry's whole
    // life (see the field's doc).
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

/// PRICE A SETTLED CONTRACT EXACTLY: one `solve_contract` per option per world.
///
/// WHY THIS EXISTS (2026-08-14). `price` values an option as
/// `Option_::payoff(guaranteed_points, can_duck)` — the POINTS proxy, whose
/// documented error is the adaptive Null threat and which is one-sided toward
/// under-valuing declaring. That is a reasonable trade in the AUCTION, where
/// ~50 candidates would each need their own contract solve. It is the wrong
/// trade for the DOUBLE, where:
///
/// * there is exactly ONE contract and two stakes on it, so the exact answer
///   costs `2 x k` solves rather than `options x k`;
/// * the question being asked is precisely "will this contract be SET", which
///   is the one question a points estimate answers worst — a point estimate of
///   the declarer's total says nothing about the distribution the bet is on;
/// * and the bet is settled, so there is no reply to model and no tree to run.
///
/// MEASURED against exact ground truth over 150 real rounds at the double
/// phase: the shipped points pricer doubled 16.8% of contracts that MADE and
/// 15.4% of contracts that FAILED — no discrimination at all.
///
/// Every number in `Option_` came off the wire from `engine.payoff_terms`, so
/// this rebuilds the same `Contract` the DD review and the card search price,
/// and nothing about the scoring is written twice.
pub fn price_exact(opts: &[Option_], deals: &[State], declarer: usize,
                   dd: &mut Dd) -> Vec<f64> {
    let mut sums = vec![0f64; opts.len()];
    for base in deals {
        for (i, o) in opts.iter().enumerate() {
            // A pass-out is a fresh deal, worth 0 by symmetry — and there is
            // nothing to solve. Kept for shape: every caller's option list is
            // the server's, and an entry it does not understand must price at
            // 0 rather than at a default `World`'s plausible-looking number.
            if o.redeal {
                continue;
            }
            // `opp` prices the contract with the OTHER seat declaring — which
            // is a different POSITION (the declarer leads), not a sign flip of
            // this one. No settled-contract phase ships one today; handled so
            // that a list which does cannot be silently mispriced.
            let decl = if o.opp { 1 - declarer } else { declarer };
            let s = State {
                trump: o.denom,
                trick: 0,
                led: -1,
                leader: decl as u8,
                pts: [0, 0],
                escored: 0,
                ..*base
            };
            let c = crate::dd::Contract {
                level: o.target,
                declarer: decl,
                make_base: o.make,
                over: o.over,
                set_base: o.set_base,
                short: o.short,
                ramp: o.ramp,
                null: Some(o.null),
            };
            let v = dd.solve_contract(&s, &c) as f64;
            sums[i] += if o.opp { -v } else { v };
        }
    }
    sums
}

/// A tiny LRU of solved hands, and it exists because ONE slot thrashes.
///
/// A browser worker answers for one seat, so a single slot was right there and
/// every measurement harness inherited it — but the ARENA and `cfrlab`'s
/// control arm drive BOTH seats through one process, and the seats alternate.
/// Seat 1's solve evicted seat 0's, so seat 0's next decision re-solved its
/// hand from scratch: measured at 2.7 auction decisions a deal costing 6.95s
/// EACH, where the cache's whole claim is that only the first decision of a
/// hand costs anything ("~1.0s for the first, ~0 for every one after it").
///
/// This is the same footgun the crate already recorded once from the other
/// direction — a cross-phase ask evicting the auction's entry, worked around by
/// routing those asks to a separate process. That workaround is unnecessary
/// with more than one slot.
///
/// Four slots: two seats' auction entries plus their exactly-priced Double
/// entries (a different key by construction). A `Solved` holds k sampled deals
/// and a value per denomination, so the whole cache is kilobytes.
pub struct SolvedCache {
    slots: Vec<(u64, Solved)>,
    cap: usize,
}

impl Default for SolvedCache {
    fn default() -> Self {
        Self { slots: Vec::new(), cap: 4 }
    }
}

impl SolvedCache {
    pub fn with_capacity(cap: usize) -> Self {
        Self { slots: Vec::new(), cap: cap.max(1) }
    }

    /// The entry for `key`, REMOVED from the cache — or a fresh one. Removing
    /// rather than borrowing keeps the caller's `entry` owned, which is what
    /// `solve_into` needs, and `put` is what returns it.
    pub fn take(&mut self, key: u64) -> (Solved, bool) {
        if let Some(i) = self.slots.iter().position(|(k, _)| *k == key) {
            return (self.slots.remove(i).1, true);
        }
        (Solved::default(), false)
    }

    /// Most recently used at the front; the oldest falls off the end.
    pub fn put(&mut self, key: u64, entry: Solved) {
        self.slots.retain(|(k, _)| *k != key);
        self.slots.insert(0, (key, entry));
        self.slots.truncate(self.cap);
    }
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
    // The SCORING is part of what was solved: worlds priced under the parity
    // must never answer for card scoring or the other way around -- the
    // contract-table bug's exact shape, one cache further out.
    mix(v.s.trump as u64
        | ((v.first_leader as u64) << 8)
        | ((v.s.even as u64) << 16)
        | ((v.s.cards as u64) << 24));
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
    solve_into(v, dd, rng, k, wanted, wanted_opp, declarer, &mut cache, None, false);
    price(opts, &cache.worlds, cache.covered, cache.covered_opp, false)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// THE BELIEF SAMPLE IS THE OPPONENT'S INFORMATION SET, and every clause of
    /// that is checked separately, because a sample that is merely PLAUSIBLE is
    /// the exact failure this crate keeps paying for: it would return legal,
    /// reasonable-looking numbers for a model of the wrong game.
    #[test]
    fn the_belief_sample_is_the_opponents_information_set() {
        let mut dd = Dd::new(16);
        let mut seen_ours = std::collections::HashSet::new();
        let mut checked = 0usize;
        for seed in 0..4u64 {
            let g = crate::game::Game::deal(&mut Rng::new(seed + 7700), 2, 0);
            let v = View::of(&g, 0);
            let mut rng = Rng::new(seed + 31);
            let mut cache = Solved::default();
            solve_into(&v, &mut dd, &mut rng, 3, 0b00001, 0b00001, 0, &mut cache,
                       None, false);
            belief_into(&v, &mut dd, &mut rng, 2, 0b00001, 0b00001, 0, &mut cache,
                        None);
            assert_eq!(cache.belief.len(), cache.deals.len(),
                       "one belief entry per sampled world");
            for (w, b) in cache.deals.iter().zip(&cache.belief) {
                assert_eq!(b.deals.len(), 2, "m sub-worlds per world");
                // ONE LEVEL OF NESTING. The regress has to stop somewhere and
                // this is where; an inner entry that had its own belief would
                // be a second level nobody paid for.
                assert!(b.belief.is_empty(), "the nesting is one level deep");
                for sub in &b.deals {
                    // (1) They know the hand that world dealt THEM...
                    assert_eq!(sub.hand[1], w.hand[1],
                               "the opponent's own hand must be fixed across \
                                their own belief -- they are holding it");
                    // (2) ...and they do NOT know ours: it is resampled, and
                    // must not simply come back as the hand we really hold.
                    assert_eq!(sub.hand[0].count_ones(), w.hand[0].count_ones(),
                               "our hand keeps its SIZE under their belief");
                    seen_ours.insert(sub.hand[0]);
                    // (3) The deal is still a legal one: no card in two places.
                    assert_eq!(sub.hand[0] & sub.hand[1], 0, "a card in both hands");
                    checked += 1;
                }
            }
        }
        assert!(checked >= 20, "only {checked} belief deals built");
        // NON-VACUITY, and it is the whole mechanism: if their belief always
        // handed them our real hand back, this would be plain minimax wearing a
        // different name -- which is precisely what `OppModel::Soft` could not
        // escape and what this exists to.
        assert!(seen_ours.len() > 4,
                "the opponent's belief about our hand never varied ({} distinct \
                 holdings over {checked} deals)", seen_ours.len());
    }

    /// THE CLAIM THE EXACT LEAF RESTS ON, swept rather than argued.
    ///
    /// `payoff_exact(P, Q)` must equal `Dd::solve_contract` on the same deal
    /// and the same contract, for EVERY level and denomination -- because the
    /// whole point of `threat_value` is that two per-DENOMINATION scalars price
    /// every one of a tree's fifty per-CONTRACT settlements. If the identity
    /// held only at some levels the saving would be imaginary and the leaf
    /// would be a new approximation wearing the word "exact".
    ///
    /// Swept over whole deals rather than sampled: this is a claim about the
    /// solver's outcome ordering, and the crate has already paid twice for
    /// checking that kind of claim at one point (`esuit`, `beats_mask`).
    ///
    /// IT IS THE SLOWEST TEST IN THE CRATE (~105s of a ~125s gate) and the cost is
    /// all CONTROL: one full-window `solve_contract` per contract, which is
    /// exactly the per-contract work `threat_value` exists to avoid paying at
    /// serving time. Seeding it would be checking the optimisation against
    /// itself. The deal count is what to turn down if this ever needs to be
    /// cheaper -- never the level or jump axes, which are what the identity
    /// could plausibly break along. **Three deals is the FLOOR, not a round
    /// number**: at two the sweep reaches no mis-priced contract at all and the
    /// non-vacuity assert below fails, which is how that floor was found.
    #[test]
    fn the_threat_value_prices_every_contract_exactly() {
        use crate::cards::DENOMS;
        let mut dd = Dd::new(18);
        let (mut checked, mut corrected, mut worst) = (0usize, 0usize, 0i32);
        for seed in 0..3u64 {
            let g = crate::game::Game::deal(&mut Rng::new(seed + 4400), 2, 0);
            for &d in DENOMS.iter() {
                for declarer in 0..2usize {
                    let s = State { trump: d, trick: 0, led: -1, leader: declarer as u8,
                                    pts: [0, 0], escored: 0, ..g.s };
                    // The two per-denomination scalars.
                    let raw = dd.solve_from(&s, 0) as i32;
                    let pool = s.pool() as i32;
                    let p0 = (pool + raw) / 2;
                    let p = if declarer == 0 { p0 } else { pool - p0 };
                    let q = dd.threat_value(&s, declarer, p);
                    // ...and the duck, which `threat_value` claims to subsume.
                    assert_eq!(q >= crate::dd::THREAT_TOP,
                               dd.null_no_even_makeable(&s, declarer),
                               "seed {seed} denom {d} declarer {declarer}: the \
                                threat solve disagrees with the ducking search");
                    // Levels across the whole ladder and BOTH jump sizes: the jump
                    // moves the set base, which is what moves where the consolation
                    // sits in the outcome order -- so it is the axis most likely to
                    // break an identity that folds two scalars into every level.
                    for level in [1i32, 3, 5, 7, 10] {
                        for jump in [0i32, 3] {
                            let o = Option_ {
                                denom: d, target: level, make: level * level + 4,
                                over: 1, set_base: 2 * level + 2 + 6 * jump,
                                short: 5, ramp: 0, null: 20,
                                opp: false, redeal: false,
                            };
                            let c = crate::dd::Contract {
                                level: o.target, declarer, make_base: o.make,
                                over: o.over, set_base: o.set_base, short: o.short,
                                ramp: o.ramp, null: Some(o.null),
                            };
                            let want = dd.solve_contract(&s, &c);
                            assert_eq!(o.payoff_exact(p, q), want,
                                       "seed {seed} denom {d} declarer {declarer} \
                                        level {level} jump {jump}: P={p} Q={q}");
                            checked += 1;
                            let gap = want - o.payoff(p, q >= crate::dd::THREAT_TOP);
                            if gap != 0 {
                                corrected += 1;
                                worst = worst.max(gap);
                            }
                            assert!(gap >= 0, "the shipped leaf OVER-priced a \
                                    contract, which contradicts the measured \
                                    one-sidedness: gap {gap}");
                        }
                    }
                }
            }
        }
        // NON-VACUITY, and it is the interesting half: the identity above is
        // trivially true on any contract the two pricers already agree on, so
        // the sweep is only evidence if it REACHED the disagreements.
        assert!(checked > 300, "only {checked} contracts swept");
        assert!(corrected > 0,
                "the sweep never reached a contract the shipped leaf mis-prices \
                 -- it is asserting nothing about the correction");
        eprintln!("threat leaf: {checked} contracts, {corrected} corrected \
                   ({:.1}%), worst +{worst}", 100.0 * corrected as f64 / checked as f64);
    }

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
        solve_into(&v, &mut dd, &mut rng, 2, 0b11111, 0, 0, &mut cache, None, false);
        assert_eq!(cache.covered, 0b11111);
        let after_open = dd.nodes;
        let pts = cache.worlds[0].pts;

        // The auction narrows, exactly as `auction_payoff_options` does.
        for wanted in [0b11111u8, 0b11110, 0b11100, 0b11000] {
            solve_into(&v, &mut dd, &mut rng, 2, wanted, 0, 0, &mut cache, None, false);
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
        solve_into(&v, &mut dd, &mut rng, 2, 0b00001, 0, 0, &mut cache, None, false);
        let first = cache.worlds[0].pts[0];
        let deals = cache.deals.clone();

        solve_into(&v, &mut dd, &mut rng, 2, 0b00011, 0, 0, &mut cache, None, false);
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
        assert_eq!(price(&[o], &worlds, 0b00000, 0, false), vec![0.0]);
        assert_eq!(price(&[o], &worlds, 0b01000, 0, false), vec![-20.0]);   // -(4 + 4x4)
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
        solve_into(&v, &mut dd, &mut rng, 2, 0b00100, 0b00100, 0, &mut cache, None, false);
        assert_eq!(cache.covered, 0b00100);
        assert_eq!(cache.covered_opp, 0b00100);

        let mine = Option_ { denom: 2, target: 3, make: 9, over: 1, set_base: 3,
                             short: 4, ramp: 0, null: 12, opp: false, redeal: false };
        let theirs = Option_ { opp: true, ..mine };
        let sums = price(&[mine, theirs], &cache.worlds, cache.covered, cache.covered_opp, false);
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
        assert_eq!(price(&[redeal], &worlds, 0, 0, false), vec![0.0]);
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
