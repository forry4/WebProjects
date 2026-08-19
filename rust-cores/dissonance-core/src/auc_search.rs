//! THE EXPERT TIER'S AUCTION: minimax over the auction tree.
//!
//! WHAT HARD DOES AND WHY IT IS NOT ENOUGH. `bid.rs` prices every option the
//! server offers as "if I end up declaring THIS contract, what does it pay",
//! and takes the best. Pricing the pass (2026-08-08) told it what CONCEDING
//! costs; it still has no model of the opponent's REPLY, and that shows up in
//! two ways in real play:
//!
//!   * it cannot UNDERBID to cap an auction. Opening at 1 on a hand worth 4
//!     prices as ~1 point, so the myopic search never picks it — even when
//!     opening low is the play that holds a strong opponent to 9 instead of
//!     letting the bidding climb to 25.
//!   * it cannot judge RE-ENTERING after being overtaken, because "what does
//!     bidding 4 pay me" is not the question — the question is what they do
//!     after it.
//!
//! Measured on the shipped Hard tier: of 43 classic rounds that opened at level
//! 1, only 30% passed when overtaken, and the settled level came out at 4–5
//! rather than the auction being capped at 3.
//!
//! WHAT THIS DOES. Expand the auction as a game tree, minimax it, and evaluate
//! a leaf — a settled contract — against the SOLVED worlds. The expensive half
//! is already paid for: `bid::Solved` holds each sampled deal solved in every
//! denomination for BOTH declarers, so every leaf here is arithmetic and the
//! whole search costs no double-dummy solves at all beyond what Hard already
//! runs. (It does ask for MORE denominations — both sides of all of them rather
//! than our five and their one — but that is the same `solve_into` cache, and
//! it is paid once per hand.)
//!
//! WHAT CROSSES THE WIRE IS DATA, NOT RULES. The leaf prices come from a TABLE
//! the server builds with `engine._terms_for` — one row per settlement the
//! auction could reach — so the scoring still lives in exactly one place, the
//! same discipline `payoff_terms` established for card play. The auction's
//! LEGALITY is mirrored here, which is the one duplication this buys;
//! `tests/test_expert.py` replays the engine's own option list against
//! `legal_bids` at every reachable node so the two cannot drift in silence.
//!
//! THREE APPROXIMATIONS, stated because they are the difference between this
//! and an exact answer:
//!
//!   1. **The leaf value is `bid.rs`'s.** A settled contract is priced by what
//!      the declarer can guarantee with both sides playing for POINTS, which is
//!      the same proxy Hard uses and for the same reason (an exact price needs
//!      a `solve_contract` per candidate per world).
//!   2. **The opponent is modelled against OUR sample.** Their branch of the
//!      minimax maximises over the worlds we drew, i.e. they are assumed to
//!      hold what we think they hold. That is the standard PIMC-in-the-auction
//!      trade; a genuinely double-blind auction search is a different program.
//!   3. **Classic's Double is not modelled.** The auction settles and the tree
//!      stops; the defender's bet is priced on its own turn, by Hard's pricing,
//!      which is exactly right for a decision with no reply after it.

use std::collections::HashMap;

use crate::bid::{Option_, Solved};

/// Which auction is being searched. They share `Solved`, the terms table and
/// the minimax; they share no legality rule at all.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum AucMode {
    /// Level + denomination, ranked C < D < H < S < NT, opener may not pass.
    Classic,
    /// A bare ascending number; either seat may pass, both passing redeals.
    Skat,
}

/// Where an auction has got to.
///
/// `level == 0` (classic) / `value == 0` (skat) means nothing stands yet.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub struct AucState {
    /// Classic: the standing level. Unused in skat.
    pub level: u8,
    /// Classic: the standing denomination. Unused in skat.
    pub denom: u8,
    /// Skat: the standing number. Unused in classic.
    pub value: u16,
    /// -1 while nothing stands.
    pub declarer: i8,
    /// Classic: bit d set when that seat has already named denomination d.
    pub used: [u8; 2],
    /// Skat: how many seats have passed with nothing standing. Two throws the
    /// hand in, which is why a skat pass is not always a leaf.
    pub passes: u8,
    pub to_act: u8,
    /// Classic: how far the STANDING bid raised the level of the bid it
    /// overtook (the opening counts, as a raise over level 0; a same-level
    /// overtake is 0). Part of the node's identity, not bookkeeping: a pass
    /// settles on this state, and the settled set price pays the defender
    /// `jump_set_bonus` per level of it — so two nodes identical but for how
    /// their standing bid arrived really are worth different amounts, and the
    /// memo must tell them apart.
    pub jump: u8,
    /// Classic: each seat's OWN previous bid's denomination, `NO_LAST` while
    /// that seat has not bid. What `DenomRule::OwnLast` reads.
    pub last: [u8; 2],
}

/// `AucState.last`'s "this seat has not bid" sentinel. Any value no legal
/// denomination can take; 7 keeps the field honest under Grand's 6.
pub const NO_LAST: u8 = 7;

impl AucState {
    pub fn opening(to_act: u8) -> Self {
        AucState { level: 0, denom: 0, value: 0, declarer: -1, used: [0, 0], passes: 0, to_act,
                   jump: 0, last: [NO_LAST, NO_LAST] }
    }
}

/// The knobs the engine owns, shipped rather than assumed.
#[derive(Clone, Debug)]
pub struct AucRules {
    pub mode: AucMode,
    pub min_level: u8,
    pub max_level: u8,
    pub max_raise: u8,
    /// HOW HEAVILY THE SEARCH WEIGHTS THE JUMP, against how heavily the room
    /// PAYS it. 1.0 is the shipped scoring exactly, and is bit-identical.
    ///
    /// A SEARCH CALIBRATION, not a rules change: the engine still scores a set
    /// at `jump_set_bonus x j` and nothing about what a round pays moves. This
    /// scales only what the tree BELIEVES that term is worth while it decides,
    /// the same shape as `double_margin` and `open_bias` -- a per-decision nudge
    /// the server computes.
    ///
    /// WHY IT EXISTS. Measured against this abstraction's equilibrium, the
    /// tree's concession is FLAT in the jump where the equilibrium's rotates
    /// hard on it: at standing 4 the equilibrium concedes 2% of one-rung climbs
    /// and 28% of leaps, the tree 52% and 53%. The term does reach the argmax
    /// (editing only `state.jump` moves the option sums by a median of 54 and
    /// flips 2 decisions in 40), so this is a magnitude question and not a
    /// wiring one -- and 44.4% of the tree's attributed exploitability sits at
    /// jump 1, the cheap climbs it hands over.
    ///
    /// It is the first treatment in this campaign that ROTATES rather than
    /// SHIFTS. Four uniform ones came back null or monotonically worse.
    pub jump_weight: f64,
    /// Classic's jump bonus (2026-08-13): what each level the SETTLING bid
    /// jumped adds to the defender's set score. A rule rather than a term row,
    /// because the rows are keyed by the settlement and the jump is a property
    /// of the PATH to it — the tree does the one multiply at the leaf. 0 in
    /// every mode that does not price jumps (and on any payload old enough not
    /// to carry the field).
    pub jump_set_bonus: i32,
    /// Which denominations an overtake may name — see `DenomRule`.
    pub denom_rule: DenomRule,
    /// Classic only: may the OPENER pass? False as shipped (the opener must
    /// bid); when true, nothing standing behaves exactly as skat's open pass —
    /// the first hands the deal over, the second throws it in.
    pub opener_may_pass: bool,
    /// Highest denomination index a classic bid may name (no-trump).
    pub top_denom: u8,
    /// Skat's bid ladder, ascending. Empty in classic.
    pub ladder: Vec<u16>,
    /// HOW MUCH of the cross-fit correction to apply -- see `Search::combine`.
    /// 0 as shipped and on any payload that predates it, and 0 is bit-identical
    /// to the tree that has always run, so an A/B against it is unconfounded
    /// (the `opp_temp` discipline, one rung further in).
    ///
    /// A WEIGHT rather than a flag because the full correction OVERSHOOTS,
    /// measured: at 1.0 the tree concedes less and bids higher exactly as
    /// intended (settled mean 4.48 -> 4.92, probe-pass 81.7% -> 77.0%) and its
    /// contracts stop coming home (made 68.5% -> 49.2%, exploitability 5.45 ->
    /// 6.11). The reason is not a bug and cannot be tuned away by a better
    /// scheme: removing a selection bias entirely costs the selection. When the
    /// sampling noise is larger than the gap between two actions, a cross-fitted
    /// choice cannot tell them apart and returns roughly their MEAN where the
    /// truth is their MIN. Leave-one-out is already the sharpest cross-fit there
    /// is (it selects on k-1 worlds); a coarser fold would correct HARDER, not
    /// softer. So the only axis left is how much of the correction to take.
    pub xfit: f64,
    /// How the opponent's turns are modelled -- see `OppModel`.
    pub opp: OppModel,
}

/// What the search believes the seat across the table will do.
///
/// `Minimax` is the classical assumption and it is MEASURABLY too strong here,
/// in a specific, diagnosed way: the tree runs from OUR information set, so at
/// every MIN node the modelled opponent chooses knowing our exact holding, and
/// it best-responds with the search's own depth -- while the opponent it
/// actually faces prices one contract at a time. Against that phantom,
/// aggression is worthless, so the search shades everything down; measured, it
/// opened <=2 and got LEFT THERE by a real opponent's simple pass in 10% of
/// rounds, declaring level 1-2 on hands worth ~+8.4.
///
/// `Myopic` replaces the min with the reply a HARD-tier opponent would pick:
/// their own best option, priced their way (each candidate contract by its own
/// payoff on their side of the sampled worlds, the pass by conceding ours),
/// with no lookahead past it. That is a best response to the bidder the tier
/// actually plays against -- and only their MODEL changes; our side still
/// searches the full tree.
/// `Soft` is the 2026-08-14 answer to the diagnosis both halves of this crate
/// arrived at independently: **the modelled opponent sees our hand.** The tree
/// runs from OUR information set, so at every MIN node they choose knowing our
/// exact holding and always find the punishing reply — against that phantom
/// aggression really is worthless, so the search shades every line of ours
/// down. (CAMPAIGN.md reaches the same conclusion about card play from the
/// other end: "standard PIMC is pessimistic in a specific way — its opponent
/// sees our hand".)
///
/// Rather than model their information set — a different program, and the one
/// `CLAUDE.md` files under "not built yet" — `Soft` prices the CONSEQUENCE:
/// an opponent who cannot see our cards does not reliably find the one reply
/// that punishes us, and how often they miss it depends on how much better it
/// is than the alternatives. So a MIN node becomes a softmax over their
/// options at temperature `temp`, in per-world payoff points:
///
///   w_i  ∝  exp(-(v_i / worlds) / temp)      (v is signed for US, so lower
///   value = Σ w_i v_i                         is better for them)
///
/// `temp <= 0` is EXACTLY the old `min`, which is what makes an A/B against
/// today's Expert unconfoundable — the same discipline CAMPAIGN.md's IIMC
/// blend used (`lambda = 0` reproduces `pimc:8` exactly). A large `temp`
/// approaches "they reply at random", which is a strictly worse model; the
/// useful range is the one that stops the search believing they are clairvoyant
/// without pretending they are careless.
///
/// IT COSTS NOTHING. A MIN node already evaluates every child to take the min,
/// and `bid::Solved` is cached per hand, so this adds no double-dummy solves
/// at all — the whole change is how the children are aggregated.
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum OppModel {
    Minimax,
    Myopic,
    /// Softmax over the opponent's replies; `temp` is in per-world payoff
    /// points. See the type note above.
    Soft(f64),
}

/// The classic-shape auction's denomination restriction (2026-08-13).
///
/// `Used` is the original per-player forever-ban (`AucState.used` bitmasks);
/// `Standing` bars only the STANDING bid's own denomination — the same suit is
/// never bid twice in a row, by anyone; `OwnLast` bars only the denomination
/// of THAT SEAT'S OWN previous bid (`AucState.last`) — you personally never
/// bid the same suit twice in a row, but you may raise the opponent's
/// standing suit and may return to yours after bidding something else.
/// Classic ships `OwnLast`; a payload without the field mirrors `Used`, the
/// rule every older server ran.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum DenomRule {
    Used,
    Standing,
    OwnLast,
}

/// One thing a seat may do. The two bid shapes are separate variants rather
/// than one struct with dead fields: they index the terms table differently and
/// they come off the wire from different move kinds.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Bid {
    Pass,
    /// Classic: a level in a denomination.
    Contract { level: u8, denom: u8 },
    /// Skat: a rung on the ladder.
    Number { value: u16 },
}

impl Bid {
    /// Which row(s) of the terms table this settlement is priced by.
    #[inline]
    pub fn key(&self) -> u16 {
        match *self {
            // denom is 0..=6 (Grand is 6), so three bits are not enough for the
            // classic shape either -- shift by 8 and let the two modes' key
            // spaces be whatever they are. They never share a table.
            Bid::Contract { level, denom } => ((level as u16) << 8) | denom as u16,
            Bid::Number { value } => value,
            Bid::Pass => 0,
        }
    }
}

/// Every legal action from `s`, mirroring `engine.auction_options` exactly.
///
/// CLASSIC. The opener names any level in any denomination and MAY NOT PASS. An
/// overtake stands at the same level in a higher-RANKED denomination, or raises
/// by up to `max_raise` in any denomination that seat has not named before.
///
/// SKAT. Any rung strictly above the standing number, and a pass is always
/// legal — including the open pass that hands the deal over at the opponent's
/// price.
pub fn legal_bids(s: &AucState, r: &AucRules, out: &mut Vec<Bid>) {
    out.clear();
    if r.mode == AucMode::Skat {
        for &v in &r.ladder {
            if v > s.value {
                out.push(Bid::Number { value: v });
            }
        }
        out.push(Bid::Pass);
        return;
    }
    let me = s.to_act as usize;
    // `Standing` frees everything while nothing stands (the engine normalises
    // the no-bid denom to 0 on the wire, so `d != s.denom` alone would wrongly
    // bar clubs from the opener).
    let free = |d: u8| match r.denom_rule {
        DenomRule::Used => (s.used[me] >> d) & 1 == 0,
        DenomRule::Standing => s.level == 0 || d != s.denom,
        DenomRule::OwnLast => d != s.last[me],
    };
    if s.level == 0 {
        for d in 0..=r.top_denom {
            if free(d) {
                for lvl in r.min_level..=r.max_level {
                    out.push(Bid::Contract { level: lvl, denom: d });
                }
            }
        }
        if r.opener_may_pass {
            out.push(Bid::Pass);
        }
        return; // ...otherwise the opener must bid
    }
    let hi = r.max_level.min(s.level + r.max_raise);
    for d in 0..=r.top_denom {
        if !free(d) {
            continue;
        }
        for lvl in s.level..=hi {
            // Same level: only a higher-ranked denomination outranks.
            if lvl == s.level && d <= s.denom {
                continue;
            }
            out.push(Bid::Contract { level: lvl, denom: d });
        }
    }
    out.push(Bid::Pass);
}

/// What a bid leads to: another node, or a settled auction.
///
/// A skat pass is the reason this is not simply "pass is the leaf": with
/// nothing standing the first pass hands the deal over and play CONTINUES, and
/// only the second throws it in.
#[derive(Clone, Copy, Debug)]
pub enum Step {
    Node(AucState),
    /// The auction settled on this state — price it.
    Settled(AucState),
    /// The hand was thrown in. Worth 0 by symmetry: a fresh deal neither seat
    /// has seen, which is what `engine.pass_options` prices a redeal at too.
    Redeal,
}

pub fn step(s: &AucState, r: &AucRules, b: Bid) -> Step {
    match b {
        Bid::Pass => {
            // NOTHING STANDING is the pass-out shape, in either auction: skat
            // has always allowed it, and classic does under OPENER_MAY_PASS.
            // The first pass hands the deal over, the second throws it in.
            let nothing_stands = if r.mode == AucMode::Skat { s.value == 0 } else { s.level == 0 };
            if nothing_stands && (r.mode == AucMode::Skat || r.opener_may_pass) {
                if s.passes >= 1 {
                    return Step::Redeal;
                }
                let mut n = *s;
                n.passes += 1;
                n.to_act = 1 - s.to_act;
                return Step::Node(n);
            }
            Step::Settled(*s)
        }
        Bid::Contract { level, denom } => {
            let mut n = *s;
            n.used[s.to_act as usize] |= 1 << denom;
            n.last[s.to_act as usize] = denom;
            // The engine's own rule (`apply_bid`): every bid carries its rise
            // over the standing level -- the OPENING included, as a raise
            // over level 0 (v2 of the jump rule).
            n.jump = level - s.level;
            n.level = level;
            n.denom = denom;
            n.declarer = s.to_act as i8;
            n.to_act = 1 - s.to_act;
            Step::Node(n)
        }
        Bid::Number { value } => {
            let mut n = *s;
            n.value = value;
            n.declarer = s.to_act as i8;
            n.to_act = 1 - s.to_act;
            Step::Node(n)
        }
    }
}

/// Priced settlements, keyed by the bid that reaches them. Built by the server.
///
/// SEVERAL ROWS PER KEY IS THE SKAT CASE AND NOT AN ODDITY. A skat number is a
/// PRICE, not a shape — the winner names their game afterwards — so a rung is
/// worth the best declaration it buys, which is exactly what `skat_declarable`
/// enumerates and what `engine.pass_options` already prices a conceded bid at.
/// Classic keys hold one row and the max is the identity.
#[derive(Clone, Default)]
pub struct TermsTable {
    rows: HashMap<u16, Vec<Option_>>,
}

impl TermsTable {
    pub fn new() -> Self {
        TermsTable { rows: HashMap::new() }
    }
    pub fn insert(&mut self, key: u16, o: Option_) {
        self.rows.entry(key).or_default().push(o);
    }
    pub fn get(&self, key: u16) -> Option<&[Option_]> {
        self.rows.get(&key).map(|v| v.as_slice())
    }
    pub fn len(&self) -> usize {
        self.rows.len()
    }
    pub fn is_empty(&self) -> bool {
        self.rows.is_empty()
    }
    /// Every denomination any leaf could be priced in, as a `Solved` mask.
    ///
    /// THIS IS WHY EXPERT COSTS MORE THAN HARD. Hard solves the denominations
    /// its own option list spans plus the ONE the opponent is standing in;
    /// a tree has to price whatever either seat might still bid, on both sides.
    /// Same `solve_into` cache, so it is paid once per hand and every later
    /// decision in the auction is arithmetic.
    pub fn denoms_mask(&self) -> u8 {
        let mut m = 0u8;
        for rows in self.rows.values() {
            for o in rows {
                m |= 1 << o.denom;
            }
        }
        m
    }
}

/// The bid that settled `s`, reconstructed so the terms table can be indexed.
fn settling_bid(s: &AucState, mode: AucMode) -> Bid {
    match mode {
        AucMode::Classic => Bid::Contract { level: s.level, denom: s.denom },
        AucMode::Skat => Bid::Number { value: s.value },
    }
}

pub struct Search<'a> {
    me: usize,
    rules: AucRules,
    terms: &'a TermsTable,
    worlds: &'a Solved,
    memo: HashMap<AucState, Vec<f64>>,
    pub nodes: u64,
}

impl<'a> Search<'a> {
    pub fn new(me: usize, rules: AucRules, terms: &'a TermsTable, worlds: &'a Solved) -> Self {
        Search { me, rules, terms, worlds, memo: HashMap::new(), nodes: 0 }
    }

    /// What the standing contract is worth TO `me`, SUMMED over the sampled
    /// worlds — the same convention `bid::price` uses, so the numbers are
    /// comparable and pool across workers by addition the same way.
    ///
    /// The declarer's guaranteed points come from the side of `Solved` that
    /// matches who is declaring — `pts` when it is us, `opp_pts` when it is
    /// them. Those are two separate solves and not a sign flip, because the
    /// declarer leads to trick 1.
    ///
    /// A denomination nobody solved is left at 0 rather than read out of a
    /// default `World`, where it would price as a flat 0 points in every deal —
    /// a plausible-looking number that would outrank genuinely bad contracts.
    ///
    /// PER WORLD, because the selection de-biasing above it needs to hold one
    /// action's value out of the sample it was chosen on. `settled` sums this
    /// in the same world order the old scalar version accumulated in, so the
    /// un-de-biased path is bit-identical rather than merely equivalent.
    pub fn settled_v(&self, s: &AucState) -> Vec<f64> {
        let mut out = vec![0.0; self.k()];
        if s.declarer < 0 {
            return out; // nothing was ever bid
        }
        let rows = match self.terms.get(settling_bid(s, self.rules.mode).key()) {
            Some(r) if !r.is_empty() => r,
            _ => return out,
        };
        let decl = s.declarer as usize;
        let mine = decl == self.me;
        let mask = if mine { self.worlds.covered } else { self.worlds.covered_opp };
        for (wi, w) in self.worlds.worlds.iter().enumerate() {
            // The DECLARER picks the game, so the best row wins — for them.
            let mut best: Option<i32> = None;
            for o in rows {
                let d = o.denom as usize;
                if d >= w.pts.len() || mask & (1 << o.denom) == 0 {
                    continue;
                }
                // The settling bid's jump fattens the set — the rows cannot
                // carry it (they are keyed by the settlement, the jump belongs
                // to the path), so it lands here, inside the set base exactly
                // where the engine folds it.
                let o = self.with_jump(o, s.jump);
                // THE LEAF IS THE ENTRY'S OWN, never this tree's opinion:
                // `Solved::exact` says whether the worlds carry the threat
                // solves, and `bid::leaf` is the one fold both pricers use.
                // A tree reading an exact leaf out of myopic worlds would price
                // every contract as though the declarer could force nothing.
                let ex = self.worlds.exact;
                let v = if mine {
                    crate::bid::leaf(&o, ex, w.pts[d], w.duck[d], w.threat[d])
                } else {
                    crate::bid::leaf(&o, ex, w.opp_pts[d], w.opp_duck[d], w.opp_threat[d])
                };
                best = Some(best.map_or(v, |b: i32| b.max(v)));
            }
            if let Some(v) = best {
                out[wi] = if mine { v as f64 } else { -v as f64 };
            }
        }
        out
    }

    /// The settled value summed over the worlds -- the number every caller
    /// outside the tree wants, and the one the tests are written against.
    pub fn settled(&self, s: &AucState) -> f64 {
        self.settled_v(s).iter().sum()
    }

    /// How many worlds the entry holds. Every per-world vector in this tree is
    /// exactly this long, so a child's `j`th entry is the same deal as a
    /// parent's -- which is what makes holding one out meaningful at all.
    #[inline]
    fn k(&self) -> usize {
        self.worlds.worlds.len()
    }

    /// A terms row adjusted for how the settling bid arrived: the jump bonus
    /// rides inside `set_base`, exactly where `engine._terms_for` puts it, so
    /// `payoff` needs no new arm and a doubled row would double it the same
    /// way. Identity when the rule or the jump is zero — every mode but
    /// classic, every payload old enough not to carry the rate.
    #[inline]
    fn with_jump(&self, o: &Option_, jump: u8) -> Option_ {
        let mut o = *o;
        // `jump_weight` scales what the SEARCH thinks the term is worth, never
        // what the room pays. At 1.0 this is `set_base += rate * jump`, the
        // integer arithmetic the engine does, and the rounding below is exact
        // on it -- so the default is bit-identical rather than merely equal.
        o.set_base += (self.rules.jump_set_bonus as f64 * jump as f64
                       * self.rules.jump_weight).round() as i32;
        o
    }

    fn step_value_v(&mut self, s: &AucState, b: Bid) -> Vec<f64> {
        match step(s, &self.rules, b) {
            Step::Settled(t) => self.settled_v(&t),
            Step::Redeal => vec![0.0; self.k()],
            Step::Node(n) => self.value(n),
        }
    }

    fn step_value(&mut self, s: &AucState, b: Bid) -> f64 {
        self.step_value_v(s, b).iter().sum()
    }

    /// CHOOSE ON THE OTHER WORLDS, SCORE ON THE HELD-OUT ONE (2026-08-19).
    ///
    /// THE DEFECT. `min` and `max` over noisy estimates are biased -- the
    /// winner is partly whichever estimate's noise favoured it, so a min reads
    /// LOW and a max reads HIGH. This crate already records the consequence
    /// ("the optimiser's curse compounds with depth... Expert takes max/min
    /// repeatedly down the tree"), and what it had not recorded is that the
    /// bias is therefore DEPTH-DEPENDENT and the auction's two branch kinds
    /// have different depths: PASSING settles immediately, while RAISING buys
    /// one more opponent `min` before anything settles. So every raise is
    /// shaded down against every pass, at every strength -- which is exactly
    /// the defect measured against the abstraction's equilibrium, where both
    /// tiers concede level 4 on 31-67% of decisions and the equilibrium
    /// concedes it on 0-5%.
    ///
    /// It is not a leaf-accuracy problem (an exact leaf was built and measured:
    /// no change) and not a marginal-shape problem (the opening bias: no
    /// change). It is the selection itself.
    ///
    /// THE FIX is the standard one for a selection bias, and it costs no
    /// solves: pick the action using every world EXCEPT `j`, then take that
    /// action's value ON `j`. The choice is then independent of the sample it
    /// is scored against, so the node's value is an unbiased estimate of a
    /// good action instead of a biased estimate of the best one. Averaging
    /// over every held-out `j` (leave-one-out rather than a single split) uses
    /// the whole sample for both jobs and keeps the selection nearly as sharp
    /// as the full-sample one.
    ///
    /// It is applied at BOTH kinds of node deliberately. Correcting only the
    /// opponent's would be a directional thumb on the scale dressed as a
    /// principle -- our own max carries the identical bias with the opposite
    /// sign, and a de-biasing that only ever helps is not one.
    ///
    /// OFF unless `rules.xfit`, and off it takes the same argmax over the same
    /// world-major sums the tree always did, so the control arm is bit-
    /// identical rather than merely equivalent.
    fn combine(&self, kids: &[Vec<f64>], maxing: bool) -> Vec<f64> {
        if kids.is_empty() {
            return Vec::new();
        }
        // THE VECTORS' OWN LENGTH, not `self.k()`: they are the sample being
        // held out, and reading the count from somewhere else is how a guard
        // ends up disabling the thing it guards.
        let k = kids[0].len();
        let totals: Vec<f64> = kids.iter().map(|v| v.iter().sum()).collect();
        let better = |a: f64, b: f64| if maxing { a > b } else { a < b };
        // The tree's own answer: one action, chosen on the whole sample.
        let mut pick = 0usize;
        for i in 1..kids.len() {
            if better(totals[i], totals[pick]) {
                pick = i;
            }
        }
        let hard = &kids[pick];
        if self.rules.xfit <= 0.0 || k < 2 || kids.len() < 2 {
            return hard.clone();
        }
        let lam = self.rules.xfit;
        let mut out = vec![0.0; k];
        for j in 0..k {
            // The leave-one-out total. Subtracting is exact enough here and
            // avoids an O(k x a x k) re-sum; the quantity being compared is a
            // sum of payoffs, not a cancellation of near-equal terms.
            let mut pick = 0usize;
            let mut best = totals[0] - kids[0][j];
            for i in 1..kids.len() {
                let v = totals[i] - kids[i][j];
                if better(v, best) {
                    pick = i;
                    best = v;
                }
            }
            // SHRUNK toward the tree's own answer. `lam = 1` is the full
            // correction and overshoots; 0 is the tree unchanged, bit for bit,
            // because this line is then never reached.
            out[j] = hard[j] + lam * (kids[pick][j] - hard[j]);
        }
        out
    }

    /// What bid `b` is worth TO THE OPPONENT, priced the way the Hard tier
    /// prices its own options: a contract by its payoff with them declaring
    /// (their side of the sampled worlds -- a separate solve, not a sign
    /// flip, because the declarer leads), a pass by minus what the standing
    /// contract pays its declarer, an open pass by the redeal's flat zero.
    ///
    /// SUMMED over the worlds before any choice is made, exactly as the real
    /// Hard argmaxes one summed vector -- a per-world argmax would model an
    /// opponent that adapts its bid to cards it has not seen.
    fn opp_myopic(&self, s: &AucState, b: Bid) -> f64 {
        match step(s, &self.rules, b) {
            // Their pass settles what stands; its value to them is minus its
            // value to whoever holds it, and `settled` is already signed for
            // US, so their side is the negation exactly when we hold it.
            Step::Settled(t) => -self.settled(&t),
            Step::Redeal => 0.0,
            Step::Node(_) => match b {
                // Their open pass in skat: nothing stands, Hard prices the
                // redeal at 0 and so does the model.
                Bid::Pass => 0.0,
                _ => {
                    let rows = match self.terms.get(b.key()) {
                        Some(r) if !r.is_empty() => r,
                        _ => return f64::NEG_INFINITY, // unpriced: never chosen
                    };
                    // A myopic bidder prices a candidate as its own FINAL bid
                    // — the same assumption the server's Hard pricing makes —
                    // so its jump is the rise over the level standing now
                    // (the opening's whole level, per the v2 rule).
                    let jump = match b {
                        Bid::Contract { level, .. } => level - s.level,
                        _ => 0,
                    };
                    let mask = self.worlds.covered_opp;
                    let mut total = 0.0;
                    for w in &self.worlds.worlds {
                        let mut best: Option<i32> = None;
                        for o in rows {
                            let d = o.denom as usize;
                            if d >= w.opp_pts.len() || mask & (1 << o.denom) == 0 {
                                continue;
                            }
                            let v = crate::bid::leaf(
                                &self.with_jump(o, jump), self.worlds.exact,
                                w.opp_pts[d], w.opp_duck[d], w.opp_threat[d]);
                            best = Some(best.map_or(v, |x: i32| x.max(v)));
                        }
                        if let Some(v) = best {
                            total += v as f64;
                        }
                    }
                    total
                }
            },
        }
    }

    /// Minimax value of `s` to `me`, PER WORLD -- see `combine` for why the
    /// tree carries a vector rather than a scalar.
    pub fn value(&mut self, s: AucState) -> Vec<f64> {
        if let Some(v) = self.memo.get(&s) {
            return v.clone();
        }
        self.nodes += 1;
        let maxing = s.to_act as usize == self.me;
        let mut moves = Vec::with_capacity(64);
        legal_bids(&s, &self.rules, &mut moves);
        if !maxing && self.rules.opp == OppModel::Myopic {
            // THE OPPONENT PLAYS HARD, NOT US-IN-A-MIRROR. Pick the one reply
            // a myopic bidder would make from their side and evaluate only
            // that child -- ties to the earliest, the same rule everywhere.
            let mut pick: Option<(Bid, f64)> = None;
            for &b in &moves {
                let v = self.opp_myopic(&s, b);
                if pick.map_or(true, |(_, pv)| v > pv) {
                    pick = Some((b, v));
                }
            }
            let best = match pick {
                Some((b, _)) => self.step_value_v(&s, b),
                None => self.settled_v(&s),
            };
            self.memo.insert(s, best.clone());
            return best;
        }
        // SOFT MIN: the opponent is good, not clairvoyant. Every child is
        // evaluated either way (the exact min needs them all), so the only
        // difference is the aggregation — see `OppModel::Soft`.
        if !maxing {
            if let OppModel::Soft(temp) = self.rules.opp {
                if temp > 0.0 {
                    let kids: Vec<Vec<f64>> =
                        moves.iter().map(|&b| self.step_value_v(&s, b)).collect();
                    if !kids.is_empty() {
                        let out = self.soft(&kids, temp);
                        self.memo.insert(s, out.clone());
                        return out;
                    }
                }
            }
        }
        let kids: Vec<Vec<f64>> =
            moves.iter().map(|&b| self.step_value_v(&s, b)).collect();
        // No legal action at all: treat the auction as settled where it stands
        // rather than propagating an infinity into an average.
        let best = if kids.is_empty() {
            self.settled_v(&s)
        } else {
            self.combine(&kids, maxing)
        };
        self.memo.insert(s, best.clone());
        best
    }

    /// The soft opponent (`OppModel::Soft`), per world and cross-fitted.
    ///
    /// The weights are a softmin over the SUMS -- the opponent commits to one
    /// reply across the whole sample, which is what keeps this less fused than
    /// a per-world choice would be -- and under `xfit` the weights for world
    /// `j` are formed from every world except `j`, exactly as `combine` picks
    /// its action. So the two aggregations are de-biased the same way and a
    /// tier is never half-corrected.
    fn soft(&self, kids: &[Vec<f64>], temp: f64) -> Vec<f64> {
        let k = kids.first().map_or(0, |v| v.len());
        let totals: Vec<f64> = kids.iter().map(|v| v.iter().sum()).collect();
        // Their preference is DESCENDING in our value; shift by the max
        // exponent before exponentiating or a wide spread overflows to
        // inf/NaN and the node returns garbage that propagates up the tree.
        let mix = |ex: Vec<f64>, at: &dyn Fn(usize) -> f64| -> Option<f64> {
            let hi = ex.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
            let w: Vec<f64> = ex.iter().map(|e| (e - hi).exp()).collect();
            let z: f64 = w.iter().sum();
            if z > 0.0 && z.is_finite() {
                Some(w.iter().enumerate().map(|(i, wi)| wi * at(i)).sum::<f64>() / z)
            } else {
                None
            }
        };
        if self.rules.xfit <= 0.0 || k < 2 || kids.len() < 2 {
            let n = k.max(1) as f64;
            let ex: Vec<f64> = totals.iter().map(|v| -(v / n) / temp).collect();
            let out = match mix(ex, &|i| totals[i]) {
                Some(v) => v,
                // Degenerate weights (every term underflowed) mean one option
                // dominates by a mile: that is the exact min, which is the
                // right answer anyway.
                None => totals.iter().cloned().fold(f64::INFINITY, f64::min),
            };
            // The scalar is spread back over the worlds so the node still
            // returns a vector; only its SUM is ever read above.
            return vec![out / k.max(1) as f64; k.max(1)];
        }
        let n = (k - 1) as f64;
        let mut out = vec![0.0; k];
        for j in 0..k {
            let ex: Vec<f64> = totals.iter().enumerate()
                .map(|(i, v)| -((v - kids[i][j]) / n) / temp).collect();
            let full = match mix(ex, &|i| kids[i][j]) {
                Some(v) => v,
                None => {
                    let mut pick = 0usize;
                    for i in 1..kids.len() {
                        if totals[i] - kids[i][j] < totals[pick] - kids[pick][j] {
                            pick = i;
                        }
                    }
                    kids[pick][j]
                }
            };
            out[j] = full;
        }
        // The soft opponent's own aggregation is already a smoothing of the
        // min, so its correction is shrunk by the same weight for the same
        // reason -- a tier must never be half-corrected.
        if self.rules.xfit < 1.0 {
            let n = k.max(1) as f64;
            let ex: Vec<f64> = totals.iter().map(|v| -(v / n) / temp).collect();
            let plain = match mix(ex, &|i| totals[i]) {
                Some(v) => v,
                None => totals.iter().cloned().fold(f64::INFINITY, f64::min),
            } / n;
            let lam = self.rules.xfit;
            for v in out.iter_mut() {
                *v = plain + lam * (*v - plain);
            }
        }
        out
    }

    /// The node's value summed over the worlds -- what every caller outside the
    /// tree means by "the value", and what the pooling protocol adds up.
    pub fn value_of(&mut self, s: AucState) -> f64 {
        self.value(s).iter().sum()
    }

    /// The minimax value of each of `bids` from `s`, in the caller's order.
    ///
    /// Indexed by the SERVER'S option list, which is what makes the answer drop
    /// straight into the existing protocol: the client still sums vectors by
    /// index across the worker pool and sends back the move it was handed. Only
    /// what the numbers MEAN changes.
    pub fn values(&mut self, s: AucState, bids: &[Bid]) -> Vec<f64> {
        bids.iter().map(|&b| self.step_value(&s, b)).collect()
    }

    /// The action to play, and what the search thinks it is worth. Ties go to
    /// the earliest, the same rule the card search's `pick` uses.
    pub fn best(&mut self, s: AucState) -> (Bid, f64) {
        let mut moves = Vec::with_capacity(64);
        legal_bids(&s, &self.rules, &mut moves);
        let vals = self.values(s, &moves);
        let maxing = s.to_act as usize == self.me;
        let mut pick = 0usize;
        for i in 1..vals.len() {
            let better = if maxing { vals[i] > vals[pick] } else { vals[i] < vals[pick] };
            if better {
                pick = i;
            }
        }
        if moves.is_empty() {
            return (Bid::Pass, self.settled(&s));
        }
        (moves[pick], vals[pick])
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bid::World;

    fn classic_rules() -> AucRules {
        AucRules { mode: AucMode::Classic, min_level: 1, max_level: 12, max_raise: 2,
                   jump_set_bonus: 0, denom_rule: DenomRule::Used,
                   opener_may_pass: false, top_denom: 4, xfit: 0.0, jump_weight: 1.0,
                   ladder: Vec::new(), opp: OppModel::Minimax }
    }

    fn skat_rules(ladder: Vec<u16>) -> AucRules {
        AucRules { mode: AucMode::Skat, min_level: 1, max_level: 12, max_raise: 2,
                   jump_set_bonus: 0, denom_rule: DenomRule::Used,
                   opener_may_pass: false, top_denom: 6, xfit: 0.0, jump_weight: 1.0,
                   ladder, opp: OppModel::Minimax }
    }

    /// THE CURSE IS A POPULATION BIAS, so it has to be SIMULATED, not asserted
    /// on one world set.
    ///
    /// Over any FIXED set of worlds the hard min is the correct answer -- the
    /// opponent really does want the option with the lowest total on those
    /// worlds. The bias only exists relative to the distribution the worlds are
    /// a SAMPLE from: `E[min_a mean_w v(a,w)] <= min_a E[v(a)]`, because the
    /// winner is partly whichever option's sampling noise happened to favour
    /// it. That is why a single hand-built example proves nothing here and this
    /// test draws many samples instead.
    ///
    /// Setup: two options of EQUAL true value (0), differing only by per-world
    /// noise. The truth a node should report is 0. The hard min reports well
    /// below it; cross-fitting -- choose on the other worlds, score on the
    /// held-out one -- reports close to it.
    #[test]
    fn cross_fitting_removes_the_selection_bias_a_hard_min_carries() {
        let t = classic_terms();
        let w = one_world(3, 10);
        let plain = Search::new(0, classic_rules(), &t, &w);
        let mut fit = classic_rules();
        fit.xfit = 1.0;
        let xf = Search::new(0, fit, &t, &w);

        let mut rng = crate::rng::Rng::new(20260819);
        // A cheap symmetric noise: +-1 per world, so each option's true mean is
        // exactly 0 and the sample mean is the only thing that moves.
        let mut draw = |rng: &mut crate::rng::Rng, k: usize| -> Vec<f64> {
            (0..k).map(|_| if rng.below(2) == 0 { -1.0 } else { 1.0 }).collect()
        };
        const K: usize = 8;
        const TRIALS: usize = 4000;
        let (mut hard, mut cross) = (0.0f64, 0.0f64);
        for _ in 0..TRIALS {
            let kids: Vec<Vec<f64>> =
                (0..4).map(|_| draw(&mut rng, K)).collect();
            hard += plain.combine(&kids, false).iter().sum::<f64>() / K as f64;
            cross += xf.combine(&kids, false).iter().sum::<f64>() / K as f64;
        }
        let (hard, cross) = (hard / TRIALS as f64, cross / TRIALS as f64);
        eprintln!("min node over {TRIALS} samples: hard {hard:+.3}, cross-fit {cross:+.3}");
        // The truth is 0. Both numbers are estimates of it.
        assert!(hard < -0.3, "the hard min is not showing the bias: {hard:+.3}");
        assert!(cross.abs() < hard.abs() / 2.0,
                "cross-fitting did not halve the bias: hard {hard:+.3}, cross {cross:+.3}");
        // ...and the correction has a SIGN: a min reads low, so de-biasing it
        // reads higher. The opposite would mean the fix is making the tree more
        // pessimistic, which is the defect it exists to remove.
        assert!(cross > hard, "cross-fitting must lift a min, not lower it");

        // THE WEIGHT IS A WEIGHT: half the correction must be half of it, and
        // zero must be none at all. Without this a shrinkage knob can silently
        // be a flag -- which is what the campaign's `open_bias` weight turned
        // out to be, measured only after a 20-hour sweep was proposed for it.
        let kids = vec![vec![1.0, 1.0, 1.0, -9.0], vec![-1.0, -1.0, -1.0, -1.0]];
        let at = |lam: f64| {
            let mut r = classic_rules();
            r.xfit = lam;
            Search::new(0, r, &t, &w).combine(&kids, false).iter().sum::<f64>()
        };
        let (off, full) = (at(0.0), at(1.0));
        assert_ne!(off, full, "the correction does nothing on a case built for it");
        assert!((at(0.5) - (off + full) / 2.0).abs() < 1e-9,
                "half the weight is not half the correction: {} vs {}",
                at(0.5), (off + full) / 2.0);
        assert_eq!(at(0.0), Search::new(0, classic_rules(), &t, &w)
                   .combine(&kids, false).iter().sum::<f64>(),
                   "zero must be the untouched tree, bit for bit");

        // A MAX node carries the identical bias with the opposite sign, and is
        // corrected the same way -- asserted because correcting only the
        // opponent's node would be a thumb on the scale dressed as a principle.
        let mut rng = crate::rng::Rng::new(20260819);
        let (mut hard, mut cross) = (0.0f64, 0.0f64);
        for _ in 0..TRIALS {
            let kids: Vec<Vec<f64>> =
                (0..4).map(|_| draw(&mut rng, K)).collect();
            hard += plain.combine(&kids, true).iter().sum::<f64>() / K as f64;
            cross += xf.combine(&kids, true).iter().sum::<f64>() / K as f64;
        }
        let (hard, cross) = (hard / TRIALS as f64, cross / TRIALS as f64);
        eprintln!("max node over {TRIALS} samples: hard {hard:+.3}, cross-fit {cross:+.3}");
        assert!(hard > 0.3, "the hard max is not showing the bias: {hard:+.3}");
        assert!(cross < hard, "cross-fitting must lower a max, not lift it");
        assert!(cross.abs() < hard.abs() / 2.0);
    }

    /// THE JUMP WEIGHT SCALES THE TERM AND NOTHING ELSE, and 1.0 is the
    /// shipped arithmetic bit for bit.
    ///
    /// Worth pinning because this is a SEARCH calibration sitting inside a
    /// SCORING term: get it wrong and the tree is priced against a set base the
    /// room does not charge, which is the drift `payoff_terms` exists to
    /// prevent. A made contract must not move at any weight -- the jump bonus
    /// is a set price only, which the engine-side test
    /// `the_settling_bids_jump_fattens_the_set_and_only_the_set` already pins
    /// on the other side of the wire.
    #[test]
    fn the_jump_weight_scales_the_set_price_and_only_that() {
        let t = classic_terms();
        let w = one_world(3, 10);
        let mut r = classic_rules();
        r.jump_set_bonus = 3;
        let base = Option_ { denom: 0, target: 4, make: 20, over: 1, set_base: 10,
                             short: 5, ramp: 0, null: 20, opp: false, redeal: false };
        let at = |lam: f64| {
            let mut rr = r.clone();
            rr.jump_weight = lam;
            let s = Search::new(0, rr, &t, &w);
            s.with_jump(&base, 2)
        };
        assert_eq!(at(1.0).set_base, 16, "1.0 must be the engine's own 10 + 3x2");
        assert_eq!(at(1.0).make, base.make, "the make base must never move");
        assert_eq!(at(3.0).set_base, 28, "3x weight is 10 + 3x(3x2)");
        assert_eq!(at(3.0).make, base.make, "...still only the set price");
        assert_eq!(at(0.0).set_base, base.set_base, "0 removes the term entirely");
        // A jump of ZERO -- the same-level overtake, the one jump-free way to
        // buy a contract -- must be untouched at every weight, or the tier
        // would price the auction's one free rung as though it had leapt.
        for lam in [0.0, 1.0, 3.0, 7.5] {
            let mut rr = r.clone();
            rr.jump_weight = lam;
            assert_eq!(Search::new(0, rr, &t, &w).with_jump(&base, 0).set_base,
                       base.set_base, "weight {lam} charged a jump of zero");
        }
    }

    /// OFF IS THE TREE THAT HAS ALWAYS RUN, and on really does something.
    ///
    /// The first half is what makes an A/B against this unconfounded -- the
    /// `opp_temp` discipline, which this crate adopted after an arm that
    /// silently ran two changes wide. The second is non-vacuity: a flag that
    /// changes no answer would measure as a clean null forever.
    #[test]
    fn cross_fitting_is_off_by_default_and_changes_something_when_on() {
        let t = classic_terms();
        let w = one_world(3, 10);
        assert_eq!(classic_rules().xfit, 0.0, "shipped default must be off");
        let plain = Search::new(0, classic_rules(), &t, &w)
            .value_of(AucState::opening(0));
        let mut fit = classic_rules();
        fit.xfit = 1.0;
        let single = Search::new(0, fit.clone(), &t, &w).value_of(AucState::opening(0));
        // ONE world cannot hold anything out, so the flag is inert there -- and
        // it must be inert rather than divide by zero.
        assert_eq!(single, plain,
                   "with a single world there is nothing to hold out");

        // With a real sample it must move. `combine` is where it lives, so the
        // demonstration above is the mechanism; this pins that the tree is
        // actually wired to it.
        let s = Search::new(0, fit, &t, &w);
        let kids = vec![vec![3.0, -9.0], vec![-1.0, -1.0]];
        assert_ne!(s.combine(&kids, false).iter().sum::<f64>(),
                   Search::new(0, classic_rules(), &t, &w)
                       .combine(&kids, false).iter().sum::<f64>(),
                   "the tree is not reading the flag");
    }

    #[test]
    fn an_opener_that_may_pass_passes_the_deal_over_then_throws_it_in() {
        let mut r = classic_rules();
        r.opener_may_pass = true;
        let s0 = AucState::opening(0);
        assert!(bids(&s0, &r).contains(&Bid::Pass), "the opener may pass");
        match step(&s0, &r, Bid::Pass) {
            Step::Node(n) => {
                assert_eq!((n.passes, n.to_act), (1, 1), "the deal is handed over");
                assert!(matches!(step(&n, &r, Bid::Pass), Step::Redeal),
                        "the second pass throws the hand in");
                // ...and the seat handed the deal may still open normally.
                assert!(bids(&n, &r).contains(&Bid::Contract { level: 4, denom: 2 }));
            }
            other => panic!("the first open pass is a node, got {other:?}"),
        }
        // With the flag off it is still a leaf, i.e. the shipped rule.
        let off = classic_rules();
        assert!(!bids(&s0, &off).contains(&Bid::Pass));
        assert!(matches!(step(&s0, &off, Bid::Pass), Step::Settled(_)));
    }

    /// One world where WE can guarantee 3 and THEY can guarantee 10: the
    /// opponent has a crushing reply to anything, which is exactly the
    /// position the soft model exists for.
    #[test]
    fn a_soft_opponent_reduces_to_minimax_at_zero_and_never_shades_below_it() {
        let t = classic_terms();
        let w = one_world(3, 10);
        let exact = Search::new(0, classic_rules(), &t, &w).value_of(AucState::opening(0));
        let mut zero = classic_rules();
        zero.opp = OppModel::Soft(0.0);
        assert_eq!(Search::new(0, zero, &t, &w).value_of(AucState::opening(0)), exact,
                   "temp 0 must BE the old minimax — an A/B that moves here is confounded");
        // Warmer opponents miss the punishing reply more often, so our lines
        // are worth at least what the clairvoyant model said, monotonically.
        let mut prev = exact;
        for temp in [1.0, 4.0, 16.0] {
            let mut r = classic_rules();
            r.opp = OppModel::Soft(temp);
            let v = Search::new(0, r, &t, &w).value_of(AucState::opening(0));
            assert!(v.is_finite(), "temp {temp} produced {v}");
            assert!(v >= prev - 1e-9,
                    "temp {temp}: {v} shaded below the clairvoyant {prev}");
            prev = v;
        }
        assert!(prev > exact, "no temperature changed anything: {prev} vs {exact}");
    }

    #[test]
    fn a_soft_opponent_still_prefers_its_better_replies() {
        // The weights must be an OPINION, not a coin flip: with one reply far
        // better for them, a small temperature must land near the exact min
        // rather than near the mean of their options.
        let t = classic_terms();
        let w = one_world(3, 10);
        let mut r = classic_rules();
        r.opp = OppModel::Soft(0.5);
        let soft = Search::new(0, r, &t, &w).value_of(AucState::opening(0));
        let exact = Search::new(0, classic_rules(), &t, &w).value_of(AucState::opening(0));
        let mut hot = classic_rules();
        hot.opp = OppModel::Soft(64.0);
        let random = Search::new(0, hot, &t, &w).value_of(AucState::opening(0));
        assert!((soft - exact).abs() < (random - exact).abs(),
                "cold {soft} should sit nearer the exact {exact} than hot {random}");
    }

    #[test]
    fn the_own_last_rule_bars_only_that_seats_own_previous_suit() {
        let mut r = classic_rules();
        r.denom_rule = DenomRule::OwnLast;
        // 1C (seat 0), 1S (seat 1): seat 0 may not bid clubs again -- 2C
        // repeats its own previous suit -- but may raise in SPADES, the
        // opponent's standing suit, which Standing forbade.
        let s0 = AucState::opening(0);
        let s1 = match step(&s0, &r, Bid::Contract { level: 1, denom: 0 }) {
            Step::Node(n) => n,
            other => panic!("{other:?}"),
        };
        let s2 = match step(&s1, &r, Bid::Contract { level: 1, denom: 3 }) {
            Step::Node(n) => n,
            other => panic!("{other:?}"),
        };
        assert_eq!(s2.last, [0, 3]);
        let v = bids(&s2, &r);
        assert!(v.iter().all(|b| !matches!(*b, Bid::Contract { denom: 0, .. })),
                "seat 0 never bids its own clubs twice in a row: {v:?}");
        assert!(v.contains(&Bid::Contract { level: 2, denom: 3 }),
                "raising the opponent's standing suit is legal here");
        // ...and after bidding something else, clubs come back.
        let s3 = match step(&s2, &r, Bid::Contract { level: 2, denom: 1 }) {
            Step::Node(n) => n,
            other => panic!("{other:?}"),
        };
        let s4 = match step(&s3, &r, Bid::Contract { level: 2, denom: 2 }) {
            Step::Node(n) => n,
            other => panic!("{other:?}"),
        };
        assert!(bids(&s4, &r).contains(&Bid::Contract { level: 3, denom: 0 }),
                "seat 0 returns to clubs once its own last bid moved off them");
    }

    #[test]
    fn the_standing_rule_bars_only_the_standing_suit_and_forgets_nothing_else() {
        let mut r = classic_rules();
        r.denom_rule = DenomRule::Standing;
        // The opener names anything -- including clubs, whose index is the
        // normalised no-bid denom.
        let v = bids(&AucState::opening(0), &r);
        assert_eq!(v.len(), 5 * 12);
        // Hearts stand; hearts may not be bid again this instant, even by a
        // seat that never named them -- and a seat that HAS named a suit may
        // return to it, which is the whole relaxation.
        let s = AucState { level: 3, denom: 2, declarer: 0, to_act: 1,
                           used: [1 << 2, 1 << 3], ..AucState::opening(1) };
        let v = bids(&s, &r);
        assert!(v.iter().all(|b| !matches!(*b, Bid::Contract { denom: 2, .. })),
                "the standing suit is never bid twice in a row: {v:?}");
        assert!(v.contains(&Bid::Contract { level: 4, denom: 3 }),
                "a suit this seat already named is free again");
        assert!(v.contains(&Bid::Contract { level: 4, denom: 0 }));
    }

    fn bids(s: &AucState, r: &AucRules) -> Vec<Bid> {
        let mut v = Vec::new();
        legal_bids(s, r, &mut v);
        v
    }

    #[test]
    fn the_classic_opener_names_every_level_in_every_denomination_and_cannot_pass() {
        let r = classic_rules();
        let v = bids(&AucState::opening(0), &r);
        assert_eq!(v.len(), 5 * 12);
        assert!(!v.contains(&Bid::Pass), "the opener must bid");
    }

    #[test]
    fn a_same_level_overtake_needs_a_higher_ranked_denomination() {
        let r = classic_rules();
        let s = AucState { level: 3, denom: 2, declarer: 0, to_act: 1, ..AucState::opening(1) };
        let v = bids(&s, &r);
        // At the standing level only 3 and 4 outrank denomination 2.
        for d in 0..=4u8 {
            let same = Bid::Contract { level: 3, denom: d };
            assert_eq!(v.contains(&same), d > 2, "denom {d} at the standing level");
        }
        assert!(v.contains(&Bid::Pass));
    }

    #[test]
    fn a_raise_is_capped_at_max_raise_and_never_repeats_a_denomination() {
        let r = classic_rules();
        let s = AucState { level: 3, denom: 0, declarer: 0, to_act: 1, used: [1, 1 << 4],
                           ..AucState::opening(1) };
        let v = bids(&s, &r);
        assert!(v.iter().all(|b| match *b {
            Bid::Contract { level, denom } => level <= 5 && denom != 4,
            _ => true,
        }), "capped at +2 and no-trump is used: {v:?}");
        assert!(v.contains(&Bid::Contract { level: 5, denom: 3 }));
        assert!(!v.contains(&Bid::Contract { level: 6, denom: 3 }));
    }

    #[test]
    fn the_raise_cap_never_climbs_past_the_top_level() {
        let r = classic_rules();
        let s = AucState { level: 11, denom: 4, declarer: 0, to_act: 1, ..AucState::opening(1) };
        assert!(bids(&s, &r).iter().all(|b| match *b {
            Bid::Contract { level, .. } => level <= 12,
            _ => true,
        }));
    }

    #[test]
    fn a_skat_bid_is_any_rung_above_the_standing_number() {
        let r = skat_rules(vec![2, 3, 4, 6, 8]);
        let s = AucState { value: 3, declarer: 0, to_act: 1, ..AucState::opening(1) };
        let v = bids(&s, &r);
        assert_eq!(v, vec![Bid::Number { value: 4 }, Bid::Number { value: 6 },
                           Bid::Number { value: 8 }, Bid::Pass]);
    }

    #[test]
    fn two_skat_passes_with_nothing_standing_throw_the_hand_in() {
        let r = skat_rules(vec![2, 3]);
        let s = AucState::opening(0);
        match step(&s, &r, Bid::Pass) {
            Step::Node(n) => {
                assert_eq!(n.passes, 1);
                assert_eq!(n.to_act, 1);
                assert!(matches!(step(&n, &r, Bid::Pass), Step::Redeal));
            }
            other => panic!("the first open pass hands the deal over: {other:?}"),
        }
    }

    /// One world in which denomination `d` guarantees `pts` for us and `opp`
    /// for them, in every denomination.
    fn one_world(pts: i32, opp: i32) -> Solved {
        let mut w = World::default();
        for d in 0..w.pts.len() {
            w.pts[d] = pts;
            w.opp_pts[d] = opp;
        }
        Solved { deals: Vec::new(), shown: Vec::new(), covered: 0x7f, covered_opp: 0x7f, exact: false,
                 worlds: vec![w] }
    }

    fn classic_terms() -> TermsTable {
        let mut t = TermsTable::new();
        for lvl in 1..=12i32 {
            for d in 0..=4u8 {
                t.insert(Bid::Contract { level: lvl as u8, denom: d }.key(),
                         Option_ { denom: d, target: lvl, make: lvl * lvl, over: 1,
                                   set_base: lvl, short: 5, ramp: 0, null: 12,
                                   opp: false, redeal: false });
            }
        }
        t
    }

    #[test]
    fn a_settled_contract_is_priced_from_the_declarers_side() {
        let t = classic_terms();
        let w = one_world(6, 9);
        let r = classic_rules();
        let s = Search::new(0, r, &t, &w);
        // We declare 4: 6 points against a target of 4 is made, 16 + 2 over.
        let mine = AucState { level: 4, denom: 0, declarer: 0, to_act: 1, ..AucState::opening(0) };
        assert_eq!(s.settled(&mine), 18.0);
        // They declare 4 and can guarantee 9: made, and it is worth minus that.
        let theirs = AucState { declarer: 1, ..mine };
        assert_eq!(s.settled(&theirs), -(16.0 + 5.0));
    }

    /// The whole point of the tier, as a unit test: a hand that can only reach
    /// 3 but whose opponent can reach 10 should OPEN LOW rather than at the
    /// level it can make, because the opener's level caps how high the reply
    /// can climb.
    #[test]
    fn the_search_underbids_to_cap_an_auction() {
        let t = classic_terms();
        let w = one_world(3, 10);
        let r = classic_rules();
        let mut s = Search::new(0, r, &t, &w);
        let (b, _) = s.best(AucState::opening(0));
        match b {
            Bid::Contract { level, .. } => assert!(level <= 3,
                "a myopic bot opens at the level it can make; this one caps the reply, got {level}"),
            other => panic!("the opener must bid, got {other:?}"),
        }
        assert!(s.nodes > 0);
    }

    #[test]
    fn the_settling_bids_jump_fattens_the_set_and_only_the_set() {
        // A raise carries its rise; the leaf pays the defender
        // `jump_set_bonus` per level of it on a set, and a made contract or
        // an opening bid owes nothing.
        let t = classic_terms();
        let mut r = classic_rules();
        r.jump_set_bonus = 3;
        // step() records the jump exactly as the engine does.
        let open = AucState::opening(0);
        let s1 = match step(&open, &r, Bid::Contract { level: 1, denom: 0 }) {
            Step::Node(n) => n,
            other => panic!("{other:?}"),
        };
        assert_eq!(s1.jump, 1, "the opening counts, as a raise over level 0 (v2)");
        let s5 = match step(&s1, &r, Bid::Contract { level: 5, denom: 1 }) {
            Step::Node(n) => n,
            other => panic!("{other:?}"),
        };
        assert_eq!(s5.jump, 4, "1 -> 5 is a jump of 4");
        // Declarer (seat 1) can guarantee only 2 points: level 5 is 3 short.
        // Flat: -(5 + 5*3) = -20 to the declarer. With the bonus the settling
        // jump of 4 adds 12 to the set: -32.
        let w = one_world(9, 2);
        let searcher = Search::new(0, r.clone(), &t, &w);
        assert_eq!(searcher.settled(&s5), 32.0, "us defending: the jump pays US");
        let mut no_bonus = classic_rules();
        no_bonus.max_raise = r.max_raise;
        let plain = Search::new(0, no_bonus, &t, &w);
        assert_eq!(plain.settled(&s5), 20.0, "rate 0 is the old arithmetic");
        // A MADE contract is untouched by the rate: seat 0 declares 4 having
        // jumped to it, guarantees 9 -> 16 + 5 over, bonus or not.
        let made = AucState { level: 4, denom: 0, declarer: 0, to_act: 1, jump: 3,
                              ..AucState::opening(0) };
        assert_eq!(searcher.settled(&made), 21.0, "the bonus is a set price only");
    }

    #[test]
    fn a_skat_rung_is_worth_the_best_declaration_it_buys() {
        // Two declarations at the same rung: one is a make, one is not. The
        // declarer picks, so the rung is worth the better of them.
        let mut t = TermsTable::new();
        let mk = |denom: u8, target: i32, make: i32| Option_ {
            denom, target, make, over: 1, set_base: make, short: 5, ramp: 0, null: 20,
            opp: false, redeal: false,
        };
        t.insert(Bid::Number { value: 12 }.key(), mk(0, 6, 12));
        t.insert(Bid::Number { value: 12 }.key(), mk(1, 4, 12));
        let w = one_world(5, 0);
        let r = skat_rules(vec![12]);
        let s = Search::new(0, r, &t, &w);
        let st = AucState { value: 12, declarer: 0, to_act: 1, ..AucState::opening(0) };
        // Target 6 is one short (-(12 + 5)); target 4 is made with one over
        // (12 + 1). The max is what the rung is worth.
        assert_eq!(s.settled(&st), 13.0);
    }

    #[test]
    fn values_come_back_in_the_callers_order() {
        let t = classic_terms();
        let w = one_world(6, 2);
        let r = classic_rules();
        let mut s = Search::new(0, r, &t, &w);
        let asked = vec![Bid::Contract { level: 1, denom: 0 },
                         Bid::Contract { level: 6, denom: 0 }];
        let v = s.values(AucState::opening(0), &asked);
        assert_eq!(v.len(), 2);
        let mut alone = Search::new(0, classic_rules(), &t, &w);
        assert_eq!(v[0], alone.step_value(&AucState::opening(0), asked[0]));
    }
}
