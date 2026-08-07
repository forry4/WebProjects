//! Skat mode: the numeric bid ladder, the declaration, and the announcements.
//!
//! The shipped auction makes level N both the price and the task, so naming
//! your bid tells the opponent what you intend to play. This mode splits them:
//! you bid a NUMBER, and only after winning do you declare the (denomination,
//! level) whose `base * level` reaches it. Many games clear the same number, so
//! the number cannot be read backwards into a denomination.
//!
//! The structural fact that made `AuctionSolver` exact holds here unchanged:
//! once a player has an estimate of both sides' results in every denomination,
//! the whole auction is arithmetic over that matrix. `HandEval` is therefore
//! reused verbatim — this is a sibling solver, not a second evaluator. What
//! changes is only what it maximises over: `{value, declaration, announcements}`
//! instead of `{level, denomination}`.
//!
//! ## What this lab CANNOT price, and why
//!
//! **Open is unmeasurable here.** It buys +1 to the multiplier in exchange for
//! playing with your hand face up — and a double-dummy solver already gives
//! both sides perfect information, so in this lab the reveal costs exactly
//! nothing. A solver allowed to announce it would take it on every single
//! contract, which would be an artefact of the instrument rather than a
//! measurement. Open is therefore excluded from the solver entirely, and the
//! multiplier here runs 1..3 (base / one announcement / both) rather than the
//! shipped 1..4. Pricing Open needs a lab whose defence plays from an
//! information set, which this is not.
//!
//! Hand and Sharp are both genuinely measurable: Hand costs the talon, which
//! double-dummy resolves exactly, and Sharp raises the point target, which is
//! arithmetic over the same matrix.

use crate::auction::{HandEval, MAX_LEVEL, NDEN, NULL_DENOM};
use std::collections::HashMap;

/// `value = base * level`, indexed by denomination (clubs..no-trump).
///
/// PRICED BY COLOUR since 2026-08-07: red 2, black 3, no-trump 5. It replaced a
/// four-tier table (D2 H3 S4 C5 NT6) mirroring real Skat's 9/10/11/12. The
/// suits are measured symmetric in this game (settled-denomination evenness
/// 0.943), which is why assigning prices works at all — but four tiers over
/// four symmetric suits priced a hand equally playable in hearts and spades a
/// whole rung apart for no reason a player could name, and the cheap suits
/// swallowed the auction. Two tiers keep the convention where it earns its
/// keep and make the within-colour choice a question about the cards.
///
/// Dropping base 6 costs no rung anyone bids: every multiple of 6 at or below
/// 36 is already a multiple of 2 or 3, so the ladder is identical through 40
/// and only 42/54/66/72 go. Ability stays real; only price is convention.
pub const SKAT_BASE: [i32; NDEN] = [3, 2, 2, 3, 5];

/// Null's flat value, sitting mid-ladder the way Skat's 23 does.
pub const SKAT_NULL_VALUE: i32 = 20;

/// Sharp promises the declared level plus this much. 2, not 3 — at 3 it
/// measured at 0% of contracts in every run, because the margin is taken off a
/// scale whose ceiling is 12 and whose two totals sum to +5.
pub const SHARP_BONUS: i32 = 2;

#[derive(Clone, Copy, Debug)]
pub struct SkatCfg {
    pub bases: [i32; NDEN],
    pub null_value: i32,
    pub sharp_bonus: i32,
    /// Points the defender gains per point the declarer finished short — the
    /// classic mode's shortfall term, kept so deep failures still hurt more
    /// than near misses.
    pub short: i32,
    pub allow_null: bool,
    pub allow_sharp: bool,
    pub allow_hand: bool,
    /// Whether a bidder is credited with knowing it may play Hand. Off by
    /// default: at auction time the talon has not been seen, so assuming the
    /// multiplier is available over-values winning.
    pub bid_expects_hand: bool,
    pub declarer_leads: bool,
    /// Confidence quantile for valuing a declaration: 0.0 scores it by its
    /// WORST sampled world, 0.5 by the median, 1.0 by the best.
    ///
    /// This is not a strength dial bolted on for flavour — it is the fix for a
    /// real bias. Choosing a declaration means maximising over ~120 candidates
    /// (5 denominations x 12 levels x Sharp), and the maximum of many noisy
    /// sample means is badly optimistic when k is small. Scored by the mean at
    /// k=3 the solver over-declares by +1.8 levels on 83% of contracts and the
    /// declarer nets -26 per contract, which is the winner's curse and not a
    /// property of the game. A lower quantile prices the same candidates by
    /// what they survive rather than by what they promise.
    pub q: f64,
    /// Confidence quantile for the DEFENDER's Kontra decision. Held separately
    /// from `q`, and that separation is load-bearing rather than tidy.
    ///
    /// `q` is a SELF-confidence dial: low means "assume my contract goes
    /// badly", which makes the declarer cautious. Point the same number at the
    /// defender, who is valuing the OPPONENT's contract, and low means "assume
    /// their contract goes badly" — maximal aggression. Sharing one number
    /// therefore makes the two seats timid and trigger-happy at the same
    /// setting. Measured, with both on q=0.0: the defender doubled 75-85% of
    /// contracts while 75% of them made, i.e. worse than never doubling.
    ///
    /// Default 0.5, the median world. A Kontra doubles a SYMMETRIC bet, so the
    /// risk-neutral rule is simply "double iff the contract is worth less than
    /// nothing to the declarer", with no confidence dial at all; anything away
    /// from the middle is a risk preference and should be set deliberately.
    pub kontra_q: f64,
}

impl Default for SkatCfg {
    fn default() -> Self {
        SkatCfg {
            bases: SKAT_BASE,
            null_value: SKAT_NULL_VALUE,
            sharp_bonus: SHARP_BONUS,
            short: 4,
            allow_null: true,
            allow_sharp: true,
            allow_hand: true,
            bid_expects_hand: false,
            declarer_leads: true,
            q: 0.5,
            kontra_q: 0.5,
        }
    }
}

/// The `q`-quantile of a set of per-world payoffs. Sorted rather than
/// interpolated: k is small, and an exact order statistic is easier to reason
/// about than a blend of two of them.
pub fn quantile(vals: &mut [i32], q: f64) -> f64 {
    if vals.is_empty() {
        return 0.0;
    }
    vals.sort_unstable();
    let i = ((vals.len() - 1) as f64 * q.clamp(0.0, 1.0)).round() as usize;
    vals[i] as f64
}

/// The legal bid ladder: every product `base * level`, plus Null's flat value.
///
/// DERIVED, never typed out. (The design note this mode came from enumerates it
/// by hand as "2,3,4,…,10,12,…" and counts 43 rungs; both are wrong — 7 is a
/// multiple of no base, so it is a hole. Under the shipped colour-priced table
/// that leaves 28 rungs from 2 to 60, with 7 still the only gap below ten.)
pub fn ladder(cfg: &SkatCfg) -> Vec<i32> {
    let mut v: Vec<i32> = Vec::new();
    for &base in &cfg.bases {
        for l in 1..=MAX_LEVEL as i32 {
            v.push(base * l);
        }
    }
    if cfg.allow_null {
        v.push(cfg.null_value);
    }
    v.sort_unstable();
    v.dedup();
    v
}

/// A declaration: what the winner of the auction actually plays.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Decl {
    pub denom: u8,
    pub level: u8,
    /// Played without looking at the talon.
    pub hand: bool,
    /// Promises `level + sharp_bonus`.
    pub sharp: bool,
}

impl Decl {
    pub fn is_null(&self) -> bool {
        self.denom == NULL_DENOM
    }

    pub fn value(&self, cfg: &SkatCfg) -> i32 {
        if self.is_null() {
            cfg.null_value
        } else {
            cfg.bases[self.denom as usize] * self.level as i32
        }
    }

    /// Announcements stack by ADDITION, Skat-style. Open is absent by design —
    /// see the module note.
    pub fn mult(&self) -> i32 {
        1 + self.hand as i32 + self.sharp as i32
    }

    pub fn stake(&self, cfg: &SkatCfg) -> i32 {
        self.value(cfg) * self.mult()
    }

    /// Trick points promised, Sharp included.
    pub fn target(&self, cfg: &SkatCfg) -> i32 {
        self.level as i32 + if self.sharp { cfg.sharp_bonus } else { 0 }
    }

    /// Net to the declarer given the points they actually took. Make it and
    /// they take the stake; miss any part of it and the defender takes the
    /// stake plus the shortfall term.
    pub fn payoff(&self, cfg: &SkatCfg, declarer_pts: i32) -> i32 {
        let stake = self.stake(cfg);
        let target = self.target(cfg);
        if declarer_pts >= target {
            stake
        } else {
            -(stake + cfg.short * (target - declarer_pts))
        }
    }

    /// Null pays flat either way — it is not a level-N contract.
    pub fn null_payoff(&self, cfg: &SkatCfg, made: bool) -> i32 {
        let stake = self.stake(cfg);
        if made {
            stake
        } else {
            -stake
        }
    }
}

/// Every declaration that satisfies a winning bid of `bid`.
///
/// Because the level is the declarer's free choice from 1..=MAX_LEVEL and the
/// dearest base at the top level is the ladder's last rung, EVERY legal bid is
/// declarable — Skat's "overbid loses at once" rule has nothing to fire on
/// here. The punishment for stretching is structural instead: a big number
/// forces you up the level ladder into a contract you cannot make, and past the
/// Null value it locks Null away.
pub fn declarable(cfg: &SkatCfg, bid: i32, hand: bool) -> Vec<Decl> {
    let mut v = Vec::new();
    for d in 0..NDEN {
        let base = cfg.bases[d];
        let lo = ((bid + base - 1) / base).max(1);
        for l in lo..=MAX_LEVEL as i32 {
            v.push(Decl { denom: d as u8, level: l as u8, hand, sharp: false });
            if cfg.allow_sharp {
                v.push(Decl { denom: d as u8, level: l as u8, hand, sharp: true });
            }
        }
    }
    if cfg.allow_null && bid <= cfg.null_value {
        // No margin to sharpen: Null is won outright or not at all.
        v.push(Decl { denom: NULL_DENOM, level: 0, hand, sharp: false });
    }
    v
}

/// Expected net (declarer minus defender) of a declaration across the sampled
/// worlds, in the declarer's own favour.
pub fn decl_value(ev: &HandEval, cfg: &SkatCfg, d: &Decl, declarer: usize) -> f64 {
    decl_value_q(ev, cfg, d, declarer, cfg.q)
}

/// As `decl_value`, at an explicit quantile. The defender needs its own, and
/// silently inheriting the declarer's is how this went wrong once already.
pub fn decl_value_q(ev: &HandEval, cfg: &SkatCfg, d: &Decl, declarer: usize,
                    q: f64) -> f64 {
    let mut v: Vec<i32> = (0..ev.k())
        .map(|w| {
            if d.is_null() {
                d.null_payoff(cfg, ev.null_of(w, declarer))
            } else {
                d.payoff(cfg, ev.pts[w][declarer][d.denom as usize] as i32)
            }
        })
        .collect();
    quantile(&mut v, q)
}

/// The declaration a bidder expects to make at `bid`, and what it is worth to
/// them. This is the arithmetic the whole auction is built on.
pub fn best_decl(
    ev: &HandEval,
    cfg: &SkatCfg,
    bid: i32,
    declarer: usize,
    hand: bool,
) -> (Decl, f64) {
    let mut best = (
        Decl { denom: 0, level: MAX_LEVEL, hand, sharp: false },
        f64::NEG_INFINITY,
    );
    for d in declarable(cfg, bid, hand) {
        let v = decl_value(ev, cfg, &d, declarer);
        if v > best.1 {
            best = (d, v);
        }
    }
    best
}

// ---------------------------------------------------------------------------
// The auction
// ---------------------------------------------------------------------------

/// Auction position. `vi` indexes the ladder; -1 means nothing stands yet.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub struct SkatAuc {
    pub vi: i16,
    /// -1 while nothing stands.
    pub declarer: i8,
    pub to_act: u8,
    /// Someone has already declined with nothing on the table, so a second
    /// decline throws the hand in.
    pub passed_at_zero: bool,
}

impl SkatAuc {
    pub fn open(opener: u8) -> SkatAuc {
        SkatAuc { vi: -1, declarer: -1, to_act: opener, passed_at_zero: false }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum SkatAction {
    /// With nothing standing this throws the hand in (if the opponent has also
    /// declined) or hands them the opening; with a bid standing it settles the
    /// auction on the last bidder.
    Pass,
    Bid(i32),
}

/// Solves the numeric auction by minimax under one player's beliefs.
///
/// Same deliberate first model as `AuctionSolver`: both sides are assumed to
/// reason from the SAME world sample, which is not true — the opponent has
/// their own hand. It is coherent, exactly solvable, and lets trap bids emerge
/// from the arithmetic rather than being hand-coded. Where it is wrong it is
/// wrong in a stated direction (it credits the opponent with knowing what we
/// know).
pub struct SkatSolver<'a> {
    pub ev: &'a HandEval,
    pub cfg: SkatCfg,
    pub me: usize,
    pub ladder: Vec<i32>,
    memo: HashMap<SkatAuc, f64>,
}

impl<'a> SkatSolver<'a> {
    pub fn new(ev: &'a HandEval, cfg: SkatCfg, me: usize) -> Self {
        SkatSolver { ev, cfg, me, ladder: ladder(&cfg), memo: HashMap::new() }
    }

    /// Expected (my score - their score) if the auction ends here.
    pub fn settled(&self, a: &SkatAuc) -> f64 {
        if a.declarer < 0 {
            return 0.0; // thrown in: nobody declares, nobody scores
        }
        let c = a.declarer as usize;
        let bid = self.ladder[a.vi as usize];
        let (_, v) = best_decl(self.ev, &self.cfg, bid, c, self.cfg.bid_expects_hand);
        if c == self.me {
            v
        } else {
            -v
        }
    }

    /// Value of the position with `to_act` still to choose.
    pub fn value(&mut self, a: SkatAuc) -> f64 {
        if let Some(&v) = self.memo.get(&a) {
            return v;
        }
        let maxing = a.to_act as usize == self.me;
        // Passing with nothing standing is not a settlement — it hands the
        // opponent the chance to take the hand at their own price, and only a
        // second decline throws it in. That is what makes an open pass safe
        // here and unsafe in classic mode, where the opener is FORCED to name a
        // contract and passing would be strictly better than a bad one.
        let mut best = if a.declarer < 0 {
            if a.passed_at_zero {
                0.0
            } else {
                let mut nxt = a;
                nxt.to_act = 1 - a.to_act;
                nxt.passed_at_zero = true;
                self.value(nxt)
            }
        } else {
            self.settled(&a)
        };
        // The ladder is ascending, so `vi + 1..` is exactly the set of rungs
        // that outbid the standing number.
        let lo = if a.vi < 0 { 0 } else { a.vi as usize + 1 };
        for i in lo..self.ladder.len() {
            let child = SkatAuc {
                vi: i as i16,
                declarer: a.to_act as i8,
                to_act: 1 - a.to_act,
                passed_at_zero: a.passed_at_zero,
            };
            let val = self.value(child);
            if maxing {
                if val > best {
                    best = val;
                }
            } else if val < best {
                best = val;
            }
        }
        self.memo.insert(a, best);
        best
    }

    /// The best of pass / any higher rung, for the player to act.
    pub fn best_action(&mut self, a: &SkatAuc) -> SkatAction {
        let mut best = if a.declarer < 0 {
            if a.passed_at_zero {
                0.0
            } else {
                let mut nxt = *a;
                nxt.to_act = 1 - a.to_act;
                nxt.passed_at_zero = true;
                self.value(nxt)
            }
        } else {
            self.settled(a)
        };
        let mut pick = SkatAction::Pass;
        let lo = if a.vi < 0 { 0 } else { a.vi as usize + 1 };
        for i in lo..self.ladder.len() {
            let v = self.ladder[i];
            let child = SkatAuc {
                vi: i as i16,
                declarer: a.to_act as i8,
                to_act: 1 - a.to_act,
                passed_at_zero: a.passed_at_zero,
            };
            let val = self.value(child);
            if val > best {
                best = val;
                pick = SkatAction::Bid(v);
            }
        }
        pick
    }

    /// The defender's Kontra decision: double iff the doubled contract is worth
    /// more to them than the undoubled one, which — since Kontra scales both
    /// outcomes equally — reduces to "do I expect this contract to fail".
    ///
    /// Read from the DEFENDER's own world sample, so it is a real posterior and
    /// not a peek. It is blind to the talon (they know only THAT a swap
    /// happened), which biases it toward doubling.
    pub fn kontra(&self, d: &Decl, declarer: usize) -> bool {
        // `kontra_q`, never `q` — see the field note. The defender is valuing
        // the OPPONENT's contract, so the confidence dial runs the other way.
        decl_value_q(self.ev, &self.cfg, d, declarer, self.cfg.kontra_q) < 0.0
    }
}
