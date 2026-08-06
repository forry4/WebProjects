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
            slope: 0,
            min_level: 1,
            flat: 0,
            allow_double: false,
            declarer_leads: false,
            step: 1,
            allow_jump: false,
            max_raise: 1,
            straight_mult: 1,
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

/// One player's belief: for each sampled world, the points each player would
/// score as declarer in each denomination.
#[derive(Clone)]
pub struct HandEval {
    /// `pts[world][denom][declarer]`
    pub pts: Vec<[[i8; NDEN]; 2]>,
}

impl HandEval {
    pub fn k(&self) -> usize {
        self.pts.len()
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
        let lo = self.level + cfg.step;
        if lo > MAX_LEVEL {
            return Vec::new();
        }
        let raise = if cfg.allow_jump {
            MAX_LEVEL
        } else {
            cfg.max_raise.max(cfg.step)
        };
        let hi = MAX_LEVEL.min(self.level.saturating_add(raise)).max(lo);
        let mut v = Vec::new();
        for d in 0..NDEN as u8 {
            if self.used[self.to_act as usize] & (1 << d) != 0 {
                continue;
            }
            for l in lo..=hi {
                v.push((l, d));
            }
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
    memo: HashMap<Auc, f64>,
}

impl<'a> AuctionSolver<'a> {
    pub fn new(ev: &'a HandEval, cfg: ScoreCfg, me: usize) -> Self {
        AuctionSolver {
            ev,
            cfg,
            me,
            memo: HashMap::new(),
        }
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
        let mut acc = 0f64;
        for w in self.ev.pts.iter() {
            let (ds, fs) = contract_score(&self.cfg, a.level, w[c][d] as i32);
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
        for (l, d) in a.options(&self.cfg) {
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
        for level in self.cfg.min_level..=MAX_LEVEL {
            for d in 0..NDEN as u8 {
                let a = Auc::after_open(opener, level, d);
                let v = self.value(a);
                if v > best.2 {
                    best = (level, d, v);
                }
            }
        }
        best
    }
}

pub fn denom_str(d: u8) -> &'static str {
    if d >= NOTRUMP {
        "NT"
    } else {
        ["C", "D", "H", "S"][d as usize]
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
) -> HandEval {
    let mut buf = Vec::new();
    let mut pts = Vec::with_capacity(k);
    for _ in 0..k {
        let w = v.determinize(rng, &mut buf);
        let mut row = [[0i8; NDEN]; 2];
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
                row[declarer][d] = (if declarer == 0 { p0 } else { crate::state::POOL as i32 - p0 }) as i8;
            }
        }
        pts.push(row);
    }
    HandEval { pts }
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
                for level in self.cfg.min_level..=MAX_LEVEL {
                    for d in 0..NDEN as u8 {
                        let a = Auc::after_open(opener, level, d);
                        let v = self.settled(&a);
                        if v > best.2 {
                            best = (level, d, v);
                        }
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
                for (l, d) in a.options(&self.cfg) {
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
                    if self.mean_pts(me, d as usize) < l as f64 {
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
