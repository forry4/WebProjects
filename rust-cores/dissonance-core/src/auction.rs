//! The auction, its scoring, and an exact solver for it under a player's
//! beliefs.
//!
//! Rules as agreed:
//!   * The opener names any level 1..=12 and any denomination (4 suits or
//!     no-trump), and commits to scoring at least that many POINTS — not
//!     tricks. Points are +2 per even-numbered trick taken and -1 per odd.
//!   * The other player may pass, or overtake at exactly level+1 while naming
//!     a NEW denomination.
//!   * A player may never name a denomination twice, which caps the auction at
//!     five bids each and makes denominations a spendable budget.
//!   * The defender leads to trick 1 (measured to be worth +0.93 pts).
//!
//! The key structural fact: once a player has an estimate of both sides'
//! results in every denomination, the WHOLE auction is arithmetic over that
//! matrix — no further card-play search. So the auction can be solved exactly
//! rather than played by hand-written heuristics, and we can read the
//! resulting strategy off instead of guessing it.

use crate::cards::NOTRUMP;
use std::collections::HashMap;

/// Highest biddable level: every positive trick taken and no negative one.
pub const MAX_LEVEL: u8 = if crate::state::POSITIVE_IS_ODD { 14 } else { 12 };
pub const NDEN: usize = 5;

/// NULL: "I will take no trick at all." Skat's escape hatch for a hand with no
/// power, and the answer to the one thing every scoring experiment failed to
/// move — the opener is forced to bid, a weak hand has nowhere to put itself,
/// and ~42% of openings pile onto the floor as a result.
///
/// The constant-sum pool forecloses the obvious alternative: "I score >= N"
/// and "my opponent scores <= 5-N" are the SAME bid, so there is no inverse
/// contract to be had on the point scale. Null has to be a trick-COUNT
/// condition, exactly as it is in Skat, which is why it needs its own solver.
///
/// What makes it a gamble here rather than a technical exercise is the piles.
/// A player cannot see their own outer pile bottoms, so a Null can be blown up
/// by a card they were never allowed to know they held.
///
/// It bids as a denomination ranked above no-trump, at one fixed level.
pub const NULL_DENOM: u8 = 5;
/// Denominations that can be NAMED, as against scored in `HandEval`.
pub const NDEN_BID: usize = 6;

/// How a score grows with the contract level.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Curve {
    /// value = N
    Linear,
    /// value = N*N
    Quad,
}

pub fn curve_val(c: Curve, n: i32) -> i32 {
    match c {
        Curve::Linear => n,
        Curve::Quad => n * n,
    }
}

/// Scoring knobs. Defaults are the agreed baseline; the calibration run says
/// `bonus_at` at 7 is reachable on only ~3.5% of deals, so it is a parameter
/// rather than a constant.
#[derive(Clone, Copy, Debug)]
pub struct ScoreCfg {
    /// Level at which the flat bonus starts applying.
    pub bonus_at: u8,
    pub bonus: i32,
    /// Points the defender gains per point the declarer finished short.
    pub short: i32,
    /// Penalty per point the declarer finishes ABOVE the contract. Because
    /// only the contract outcome scores, the defence is completely indifferent
    /// to giving tricks away, so this hands them a free weapon: burst the
    /// contract instead of setting it. Measured to be forceable ~89% of the
    /// time by ~3 points, which is a rounding error against a made 6 (N^2 =
    /// 36) and ruinous against a made 1.
    pub over: i32,
    /// Expected points the defence can force the declarer ABOVE the contract,
    /// once the contract is safe. Measured by `overtest`, not assumed.
    pub burst: f64,
    /// Let the OPENER pass. If both players pass the hand is thrown in for
    /// 0-0. Without this a weak hand is forced to name something, and the
    /// cheapest place to park it is the floor -- which is most of why the
    /// level-1 cluster exists at all.
    pub allow_open_pass: bool,
    /// Denominations are a SHARED budget: naming one burns it for both
    /// players, not just the namer. Turns the choice of denomination into a
    /// denial decision and caps the whole auction at five bids.
    pub global_denoms: bool,
    /// Lowest level the opener may name. 0 means "I will not finish negative",
    /// which is nearly free -- the point of it is to cap what the opponent can
    /// reach, not to score.
    pub min_level: u8,
    /// Allow DOUBLING: instead of passing or overtaking, freeze the contract
    /// here and double whatever it pays -- to whichever side ends up earning
    /// it. Only the non-declarer is ever on turn, so a double is always by the
    /// defender.
    pub allow_double: bool,
    /// Who opens trick 1. The defender leading was worth +0.93 pts in the
    /// calibration run, so flipping this hands roughly a full point to the
    /// declarer -- the most direct lever there is on how attractive it is to
    /// win the contract at all.
    pub declarer_leads: bool,
    /// How far an overtake must raise the level. A bigger step makes
    /// overtaking a bigger commitment, which protects HIGH openings most:
    /// open 5 against step 2 and they have to find 7.
    pub step: u8,
    /// Let an overtake jump to any higher level rather than exactly +step.
    /// This removes the whole reason to open low: a floor bid no longer caps
    /// what the opponent can reach.
    pub allow_jump: bool,
    /// Largest raise an overtake may make. 1 is the plain ladder; unlimited
    /// (set by `allow_jump`) turns the auction into a sealed-bid declaration.
    /// Anything in between is the interesting middle: a floor opening can be
    /// punished, but not by conceding the entire range in one bid.
    pub max_raise: u8,
    /// Multiplier on the make score when the opener was never overtaken.
    /// Rewards naming your value up front instead of trapping.
    pub straight_mult: i32,
    /// RANK the denominations (C < D < H < S < NT, i.e. by index) so that an
    /// overtake need only outrank the standing bid, not out-LEVEL it. This is
    /// Skat's structural idea without Skat's arithmetic: the bid becomes a
    /// price, and the price is no longer the same thing as the task.
    ///
    /// The point is the floor cluster. ~42% of openings sit at level 1 under
    /// every scoring configuration tried, because the opener is forced to bid
    /// and has nowhere to put a weak hand. Every fix so far attacked the price
    /// and washed. This does not try to empty the floor -- it gives the floor
    /// five distinguishable rungs, so a crowded floor stops being a degenerate
    /// one. (18 is the most common bid in Skat too, and nobody calls that
    /// broken: the number is not the whole bid.)
    ///
    /// `max_raise` still caps how far a single overtake may climb, and the
    /// per-player no-repeat rule still caps the whole auction at five bids
    /// each, so same-level rungs cannot make the auction drag.
    pub rank_denoms: bool,
    /// Offer the NULL contract (see `NULL_DENOM`).
    pub allow_null: bool,
    /// The level Null bids AS. It has no level of its own — like Skat's fixed
    /// 23 it is a single rung on the ladder, and where that rung sits is what
    /// decides which hands can afford it.
    pub null_level: u8,
    /// Fixed score for making Null, and for the defence when it is broken.
    /// Held apart from the make/set curves because Null is not a level-N
    /// contract and pricing it off N would be meaningless.
    pub null_make: i32,
    pub null_set: i32,
    /// Curve for MAKING a contract.
    pub make_curve: Curve,
    /// Curve for SETTING one. Keeping these independent is the whole point:
    /// a steeper make curve also steepens the reward for setting a high
    /// contract, which rewards the very floor bid that invites the climb. Only
    /// the RATIO between them can lift the bidding.
    pub set_curve: Curve,
    /// Flat reward for MAKING any contract, on top of N. Raises the value of
    /// declaring at every level -- but proportionally most at the bottom, so
    /// its effect on the floor cluster is not obvious in advance.
    pub flat: i32,
    /// Extra reward per level above 1, i.e. make score = N + slope*(N-1).
    /// slope 0 is the flat "score N" baseline; raising it is the direct test
    /// of whether a steeper curve pulls opening bids up off the floor.
    pub slope: i32,
}

impl Default for ScoreCfg {
    fn default() -> Self {
        ScoreCfg {
            bonus_at: 7,
            bonus: 5,
            short: 1,
            over: 0,
            burst: 2.5,
            allow_open_pass: false,
            global_denoms: false,
            slope: 0,
            min_level: 1,
            flat: 0,
            allow_double: false,
            declarer_leads: false,
            step: 1,
            allow_jump: false,
            max_raise: 1,
            straight_mult: 1,
            rank_denoms: false,
            allow_null: false,
            null_level: 3,
            null_make: 12,
            null_set: 10,
            make_curve: Curve::Linear,
            set_curve: Curve::Linear,
        }
    }
}

/// Returns (declarer score, defender score).
#[inline]
pub fn contract_score(cfg: &ScoreCfg, n: u8, declarer_pts: i32) -> (i32, i32) {
    if declarer_pts >= n as i32 {
        // The slope term is clamped so a level-0 contract cannot be penalised
        // by it, and the set base likewise cannot go negative.
        let mut s = curve_val(cfg.make_curve, n as i32)
            + cfg.slope * (n as i32 - 1).max(0)
            + cfg.flat;
        if n >= cfg.bonus_at {
            s += cfg.bonus;
        }
        (s, 0)
    } else {
        // Set base is the value of one level lower on the set curve, so with
        // matched curves a sacrifice costs exactly the shortfall penalty on
        // top of what you were going to concede anyway.
        let base = if n == 0 {
            0
        } else {
            curve_val(cfg.set_curve, n as i32 - 1)
        };
        (0, base + cfg.short * (n as i32 - declarer_pts))
    }
}

/// One player's belief: for each sampled world, what each player would do as
/// declarer in each denomination.
#[derive(Clone)]
pub struct HandEval {
    /// Most the declarer can guarantee against a defence trying to hold them
    /// down. Decides whether a contract can be MADE.
    pub pts: Vec<[[i8; NDEN]; 2]>,
    /// Least the declarer can hold themselves to against a defence trying to
    /// BURST them. Decides how far they overshoot. Empty when `over` is 0.
    pub floor: Vec<[[i8; NDEN]; 2]>,
    /// Whether each player could make NULL in this world. Empty when Null is
    /// off — it is a separate search, not a column of `pts`.
    pub null: Vec<[bool; 2]>,
}

/// Resolve a contract. Beyond what the declarer can guarantee, the defence
/// simply holds them down; at or below it, the defence switches to BURSTING
/// them past the contract.
///
/// `floor_pts` is ignored -- kept only so callers need not change. The forced
/// overshoot is taken from `cfg.burst`, a MEASURED constant, because the
/// obvious two-bound model is wrong: the totals a declarer can guarantee under
/// adversarial play do not form an interval, so knowing the minimum they can
/// shed to says nothing about whether they can pin an intermediate value.
/// `overtest` measures the real thing at 2.3-3.5 points, near enough flat in
/// the level bid.
pub fn outcome(cfg: &ScoreCfg, level: u8, max_pts: i32, _floor_pts: i32) -> (i32, i32) {
    if (level as i32) > max_pts {
        let base = if level == 0 {
            0
        } else {
            curve_val(cfg.set_curve, level as i32 - 1)
        };
        return (0, base + cfg.short * (level as i32 - max_pts));
    }
    let mut sc = curve_val(cfg.make_curve, level as i32)
        + cfg.slope * (level as i32 - 1).max(0)
        + cfg.flat
        - (cfg.over as f64 * cfg.burst).round() as i32;
    if level >= cfg.bonus_at {
        sc += cfg.bonus;
    }
    (sc, 0)
}

impl HandEval {
    pub fn k(&self) -> usize {
        self.pts.len()
    }

    /// Whether `declarer` makes Null in world `w`. Absent evaluation reads as
    /// "cannot", so a config that forgot to compute it never bids Null rather
    /// than bidding it for free.
    #[inline]
    pub fn null_of(&self, w: usize, declarer: usize) -> bool {
        !self.null.is_empty() && self.null[w][declarer]
    }

    #[inline]
    pub fn floor_of(&self, w: usize, declarer: usize, d: usize) -> i32 {
        if self.floor.is_empty() {
            i32::MIN / 4
        } else {
            self.floor[w][declarer][d] as i32
        }
    }
}

/// Auction position. `used` is a bitmask per player of denominations already
/// named by that player.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub struct Auc {
    pub level: u8,
    pub denom: u8,
    pub declarer: u8,
    pub used: [u8; 2],
    pub to_act: u8,
    pub doubled: bool,
    /// The level the auction opened at, so "never overtaken" is decidable.
    pub opened_at: u8,
}

/// What a player may do when it is their turn to respond.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum BidAction {
    Pass,
    Double,
    Overtake(u8, u8),
}

impl Auc {
    pub fn after_open(opener: u8, level: u8, denom: u8) -> Auc {
        let mut used = [0u8; 2];
        used[opener as usize] |= 1 << denom;
        Auc {
            level,
            denom,
            declarer: opener,
            used,
            to_act: 1 - opener,
            doubled: false,
            opened_at: level,
        }
    }

    /// Every (level, denomination) an overtake could name.
    pub fn options(&self, cfg: &ScoreCfg) -> Vec<(u8, u8)> {
        // With ranked denominations an overtake may stand at the SAME level in
        // a higher-ranked denomination, so the floor of the range is the
        // standing level rather than one step above it.
        let lo = if cfg.rank_denoms {
            self.level
        } else {
            self.level + cfg.step
        };
        if lo > MAX_LEVEL {
            return Vec::new();
        }
        let raise = if cfg.allow_jump {
            MAX_LEVEL
        } else {
            cfg.max_raise.max(cfg.step)
        };
        let hi = MAX_LEVEL.min(self.level.saturating_add(raise)).max(lo);
        let blocked = if cfg.global_denoms {
            self.used[0] | self.used[1]
        } else {
            self.used[self.to_act as usize]
        };
        let mut v = Vec::new();
        for d in 0..NDEN as u8 {
            if blocked & (1 << d) != 0 {
                continue;
            }
            for l in lo..=hi {
                // At the standing level, only a higher-ranked denomination
                // outranks the standing bid. Above it, any denomination does.
                if cfg.rank_denoms && l == self.level && d <= self.denom {
                    continue;
                }
                v.push((l, d));
            }
        }
        // Null sits at one fixed rung, above no-trump at its own level. It is
        // reachable whenever that rung outranks the standing bid AND is within
        // the raise cap -- so a high standing contract shuts it out, which is
        // what stops it being a free escape from any position.
        if cfg.allow_null
            && blocked & (1 << NULL_DENOM) == 0
            && cfg.null_level >= lo
            && cfg.null_level <= hi
            && !(cfg.null_level == self.level && (!cfg.rank_denoms || self.denom >= NULL_DENOM))
        {
            v.push((cfg.null_level, NULL_DENOM));
        }
        v
    }

    pub fn overtake(&self, level: u8, denom: u8) -> Auc {
        let mut a = *self;
        a.level = level;
        a.denom = denom;
        a.declarer = self.to_act;
        a.used[self.to_act as usize] |= 1 << denom;
        a.to_act = 1 - self.to_act;
        a
    }
}

/// Solves the auction by minimax under one player's beliefs.
///
/// Both sides are assumed to reason from the SAME world sample, which is not
/// true — the opponent has their own hand and their own beliefs. It is a
/// deliberate first model: it is coherent, it is exactly solvable, and it lets
/// trap bids and sacrifices EMERGE from the arithmetic rather than being
/// hand-coded. Where it is wrong it is wrong in a stated direction (it credits
/// the opponent with knowing what we know).
pub struct AuctionSolver<'a> {
    pub ev: &'a HandEval,
    pub cfg: ScoreCfg,
    /// Whose point of view the returned values are from.
    pub me: usize,
    /// Rotates the denomination scan order. The suits are SYMMETRIC in this
    /// game, so a hand that just wants to park at the cheapest rung is
    /// genuinely indifferent between them — and a scan that keeps the first
    /// maximum then dumps every one of those ties on denomination 0. Measured:
    /// 96% of floor openings came out in clubs, which is a property of the
    /// loop, not of the game. Vary this per deal and indifference spreads
    /// evenly instead of piling up, which is what any histogram over
    /// denominations has to do before it can be read.
    pub tie_salt: u64,
    memo: HashMap<Auc, f64>,
}

impl<'a> AuctionSolver<'a> {
    pub fn new(ev: &'a HandEval, cfg: ScoreCfg, me: usize) -> Self {
        AuctionSolver {
            ev,
            cfg,
            me,
            tie_salt: 0,
            memo: HashMap::new(),
        }
    }

    /// Rotate a candidate list so that ties do not all fall on the same
    /// denomination. Order-only: the SET of candidates is untouched, so this
    /// cannot change which bids are legal or what any of them is worth.
    fn rotate(&self, mut v: Vec<(u8, u8)>) -> Vec<(u8, u8)> {
        let n = v.len() as u64;
        if self.tie_salt != 0 && n != 0 {
            v.rotate_left((self.tie_salt % n) as usize);
        }
        v
    }

    /// Expected (my score - their score) if the auction ends here.
    pub fn settled(&self, a: &Auc) -> f64 {
        let d = a.denom as usize;
        let c = a.declarer as usize;
        let mult = if a.doubled { 2 } else { 1 };
        // A contract still at its opening level was never overtaken.
        let straight = if a.level == a.opened_at {
            self.cfg.straight_mult
        } else {
            1
        };
        // Null pays a flat amount either way: it is not a level-N contract, so
        // neither curve applies to it.
        if d == NULL_DENOM as usize {
            let mut acc = 0f64;
            for wi in 0..self.ev.k() {
                let (ds, fs) = if self.ev.null_of(wi, c) {
                    (self.cfg.null_make * mult, 0)
                } else {
                    (0, self.cfg.null_set * mult)
                };
                acc += (if c == self.me { ds - fs } else { fs - ds }) as f64;
            }
            return acc / self.ev.k() as f64;
        }
        let mut acc = 0f64;
        for (wi, w) in self.ev.pts.iter().enumerate() {
            let (ds, fs) = if self.cfg.over > 0 {
                outcome(
                    &self.cfg,
                    a.level,
                    w[c][d] as i32,
                    self.ev.floor_of(wi, c, d),
                )
            } else {
                contract_score(&self.cfg, a.level, w[c][d] as i32)
            };
            let (ds, fs) = (ds * mult * straight, fs * mult);
            let net = if c == self.me { ds - fs } else { fs - ds };
            acc += net as f64;
        }
        acc / self.ev.k() as f64
    }

    /// Value of the position with `to_act` still to choose.
    pub fn value(&mut self, a: Auc) -> f64 {
        if let Some(&v) = self.memo.get(&a) {
            return v;
        }
        let pass = self.settled(&a);
        let mut best = pass;
        let maxing = a.to_act as usize == self.me;
        if self.cfg.allow_double && !a.doubled {
            let mut dbl = a;
            dbl.doubled = true;
            let dv = self.settled(&dbl);
            if maxing {
                if dv > best {
                    best = dv;
                }
            } else if dv < best {
                best = dv;
            }
        }
        for (l, d) in a.options(&self.cfg) {
            let child = a.overtake(l, d);
            let v = self.value(child);
            if maxing {
                if v > best {
                    best = v;
                }
            } else if v < best {
                best = v;
            }
        }
        self.memo.insert(a, best);
        best
    }

    /// The best of pass / double / overtake.
    pub fn best_response(&mut self, a: &Auc) -> BidAction {
        let mut best = self.settled(a);
        let mut pick = BidAction::Pass;
        if self.cfg.allow_double && !a.doubled {
            let mut dbl = *a;
            dbl.doubled = true;
            let v = self.settled(&dbl);
            if v > best {
                best = v;
                pick = BidAction::Double;
            }
        }
        for (l, d) in self.rotate(a.options(&self.cfg)) {
            let v = self.value(a.overtake(l, d));
            if v > best {
                best = v;
                pick = BidAction::Overtake(l, d);
            }
        }
        pick
    }

    /// The opening bid. The opener must bid, so passing is not an option; the
    /// whole rest of the auction is searched, which is what lets a deliberately
    /// LOW opening in a second-best denomination show up as optimal when it is.
    pub fn best_open(&mut self, opener: u8) -> (u8, u8, f64) {
        let mut best = (self.cfg.min_level, 0u8, f64::NEG_INFINITY);
        for (level, d) in self.rotate(self.openings()) {
            let a = Auc::after_open(opener, level, d);
            let v = self.value(a);
            if v > best.2 {
                best = (level, d, v);
            }
        }
        best
    }

    /// How much the choice of denomination at the FLOOR level is actually
    /// worth: (best - worst) in solver value across everything biddable at
    /// `min_level`.
    ///
    /// This is the honest version of the floor question, and the histogram is
    /// not. A denomination histogram can be flattened for free by breaking
    /// ties differently, which changes how the floor LOOKS without giving the
    /// opener a single new decision. A spread near zero means the five floor
    /// bids are interchangeable and the floor is degenerate however evenly the
    /// picture is spread; a spread well above zero means picking among them is
    /// a real decision. That is the claim ranking has to satisfy.
    ///
    /// Cheap: `best_open` has already memoised every one of these positions.
    pub fn floor_spread(&mut self, opener: u8) -> f64 {
        let (mut hi, mut lo) = (f64::NEG_INFINITY, f64::INFINITY);
        for (level, d) in self.openings() {
            if level != self.cfg.min_level {
                continue;
            }
            let v = self.value(Auc::after_open(opener, level, d));
            hi = hi.max(v);
            lo = lo.min(v);
        }
        if hi.is_finite() && lo.is_finite() {
            hi - lo
        } else {
            0.0
        }
    }

    /// Every opening bid available, Null included. One list so the solver and
    /// the myopic control cannot disagree about what is legal.
    pub fn openings(&self) -> Vec<(u8, u8)> {
        let mut v = Vec::new();
        for level in self.cfg.min_level..=MAX_LEVEL {
            for d in 0..NDEN as u8 {
                v.push((level, d));
            }
        }
        if self.cfg.allow_null {
            v.push((self.cfg.null_level, NULL_DENOM));
        }
        v
    }
}

pub fn denom_str(d: u8) -> &'static str {
    match d {
        0..=3 => ["C", "D", "H", "S"][d as usize],
        4 => "NT",
        _ => "Null",
    }
}

// ---------------------------------------------------------------------------
// Hand evaluation and bidding styles
// ---------------------------------------------------------------------------

use crate::dd::Dd;
use crate::rng::Rng;
use crate::state::State;
use crate::view::View;

/// Estimate both players' results in every denomination, by sampling worlds
/// consistent with what this player can see and solving each exactly.
///
/// The same world is reused across all ten (denomination, declarer) cells,
/// which makes the comparison BETWEEN denominations paired — the choice of
/// trump is exactly what the auction turns on, so that is where the noise
/// most needs cancelling.
pub fn eval_hand(
    v: &View,
    dd: &mut Dd,
    rng: &mut Rng,
    k: usize,
    declarer_leads: bool,
    need_floor: bool,
    need_null: bool,
) -> HandEval {
    let mut buf = Vec::new();
    let mut pts = Vec::with_capacity(k);
    let mut floor: Vec<[[i8; NDEN]; 2]> = Vec::with_capacity(k);
    let mut null: Vec<[bool; 2]> = Vec::with_capacity(k);
    for _ in 0..k {
        let w = v.determinize(rng, &mut buf);
        let mut row = [[0i8; NDEN]; 2];
        let mut frow = [[0i8; NDEN]; 2];
        if need_null {
            // Null is played at no trump, as in Skat: with a trump suit the
            // declarer gets a second way to be forced to win a trick.
            // `null_no_even_makeable`, NOT `null_makeable`: the contract that
            // is actually scored -- here and in the shipped engine -- is "win
            // no +2 trick", and the zero-TRICK version is a different, far
            // rarer condition (measured 0.7% of hands against ~7%).
            //
            // This used to read `null_makeable`, so the bidder evaluated a
            // contract nobody was ever paid on: it believed Null was makeable
            // in ~0.7% of worlds while resolution then made it 33% of the time.
            // That mis-specification is upstream of every Null conclusion in
            // CAMPAIGN.md's rung sweep -- in particular "all 18 arrived by
            // OVERTAKE, none by opening" is exactly the signature of a bidder
            // that thinks the contract never makes.
            let mut nrow = [false; 2];
            for declarer in 0..2usize {
                let s = State {
                    trump: NOTRUMP,
                    trick: 0,
                    led: -1,
                    leader: if declarer_leads {
                        declarer as u8
                    } else {
                        1 - declarer as u8
                    },
                    pts: [0, 0],
                    ..w
                };
                nrow[declarer] = dd.null_no_even_makeable(&s, declarer);
            }
            null.push(nrow);
        }
        for declarer in 0..2usize {
            for d in 0..NDEN {
                let s = State {
                    trump: d as u8,
                    trick: 0,
                    led: -1,
                    leader: if declarer_leads {
                        declarer as u8
                    } else {
                        1 - declarer as u8
                    },
                    pts: [0, 0],
                    ..w
                };
                let diff = dd.solve(&s) as i32;
                let p0 = (crate::state::POOL as i32 + diff) / 2;
                row[declarer][d] =
                    (if declarer == 0 { p0 } else { crate::state::POOL as i32 - p0 }) as i8;
                if need_floor {
                    frow[declarer][d] = forced_floor(dd, &s, declarer) as i8;
                }
            }
        }
        pts.push(row);
        if need_floor {
            floor.push(frow);
        }
    }
    HandEval { pts, floor, null }
}

/// The lowest final total the declarer can hold themselves to, against a
/// defence doing everything it can to push them higher. One exact solve.
pub fn forced_floor(dd: &mut Dd, s: &State, declarer: usize) -> i32 {
    const LOW: i32 = -30;
    let c = crate::dd::Contract {
        level: LOW,
        declarer,
        make_base: 0,
        over: 1,
        set_base: 1_000_000,
        short: 0,
    };
    -dd.solve_contract(s, &c) + LOW
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Style {
    /// Full minimax over the remaining auction — the reference bidder.
    Solve,
    /// One level deep: bid as if the opponent will simply pass. The control
    /// that shows whether auction lookahead is worth anything.
    Myopic,
    /// Solve, then shade the opening level. Tests whether the solver's own
    /// level is actually the peak.
    Shade(i8),
    /// Solve, but refuse to overtake unless expecting to MAKE the contract.
    /// Isolates how much of the solver's edge is sacrifice bidding.
    NoSac,
}

impl<'a> AuctionSolver<'a> {
    /// Mean points for `declarer` in denomination `d` across the sampled worlds.
    pub fn mean_pts(&self, declarer: usize, d: usize) -> f64 {
        let s: i32 = self.ev.pts.iter().map(|w| w[declarer][d] as i32).sum();
        s as f64 / self.ev.k() as f64
    }

    pub fn open(&mut self, style: Style, opener: u8) -> (u8, u8) {
        match style {
            Style::Solve | Style::NoSac => {
                let (l, d, _) = self.best_open(opener);
                (l, d)
            }
            Style::Shade(i) => {
                let (l, d, _) = self.best_open(opener);
                let l = (l as i32 + i as i32)
                    .clamp(self.cfg.min_level as i32, MAX_LEVEL as i32) as u8;
                (l, d)
            }
            Style::Myopic => {
                let mut best = (self.cfg.min_level, 0u8, f64::NEG_INFINITY);
                for (level, d) in self.rotate(self.openings()) {
                    let a = Auc::after_open(opener, level, d);
                    let v = self.settled(&a);
                    if v > best.2 {
                        best = (level, d, v);
                    }
                }
                (best.0, best.1)
            }
        }
    }

    pub fn respond(&mut self, style: Style, a: &Auc) -> BidAction {
        let dbl = |s: &Self, best: &mut f64, pick: &mut BidAction| {
            if s.cfg.allow_double && !a.doubled {
                let mut d = *a;
                d.doubled = true;
                let v = s.settled(&d);
                if v > *best {
                    *best = v;
                    *pick = BidAction::Double;
                }
            }
        };
        match style {
            Style::Solve | Style::Shade(_) => self.best_response(a),
            Style::Myopic => {
                let mut best = self.settled(a);
                let mut pick = BidAction::Pass;
                dbl(self, &mut best, &mut pick);
                for (l, d) in self.rotate(a.options(&self.cfg)) {
                    let v = self.settled(&a.overtake(l, d));
                    if v > best {
                        best = v;
                        pick = BidAction::Overtake(l, d);
                    }
                }
                pick
            }
            Style::NoSac => {
                let me = a.to_act as usize;
                let mut best = self.settled(a);
                let mut pick = BidAction::Pass;
                dbl(self, &mut best, &mut pick);
                for (l, d) in a.options(&self.cfg) {
                    // Null has no point target, so "would I make this?" is the
                    // Null solve itself rather than a comparison against l.
                    if d == NULL_DENOM {
                        let made = (0..self.ev.k()).filter(|&w| self.ev.null_of(w, me)).count();
                        if made * 2 < self.ev.k() {
                            continue;
                        }
                    } else if self.mean_pts(me, d as usize) < l as f64 {
                        continue;
                    }
                    let v = self.value(a.overtake(l, d));
                    if v > best {
                        best = v;
                        pick = BidAction::Overtake(l, d);
                    }
                }
                pick
            }
        }
    }
}
