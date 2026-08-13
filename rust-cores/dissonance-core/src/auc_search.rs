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
    /// overtook (0 for an opening bid or a same-level overtake). Part of the
    /// node's identity, not bookkeeping: a pass settles on this state, and the
    /// settled set price pays the defender `jump_set_bonus` per level of it —
    /// so two nodes identical but for how their standing bid arrived really
    /// are worth different amounts, and the memo must tell them apart.
    pub jump: u8,
}

impl AucState {
    pub fn opening(to_act: u8) -> Self {
        AucState { level: 0, denom: 0, value: 0, declarer: -1, used: [0, 0], passes: 0, to_act,
                   jump: 0 }
    }
}

/// The knobs the engine owns, shipped rather than assumed.
#[derive(Clone, Debug)]
pub struct AucRules {
    pub mode: AucMode,
    pub min_level: u8,
    pub max_level: u8,
    pub max_raise: u8,
    /// Classic's jump bonus (2026-08-13): what each level the SETTLING bid
    /// jumped adds to the defender's set score. A rule rather than a term row,
    /// because the rows are keyed by the settlement and the jump is a property
    /// of the PATH to it — the tree does the one multiply at the leaf. 0 in
    /// every mode that does not price jumps (and on any payload old enough not
    /// to carry the field).
    pub jump_set_bonus: i32,
    /// Highest denomination index a classic bid may name (no-trump).
    pub top_denom: u8,
    /// Skat's bid ladder, ascending. Empty in classic.
    pub ladder: Vec<u16>,
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
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum OppModel {
    Minimax,
    Myopic,
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
    let free = |d: u8| (s.used[me] >> d) & 1 == 0;
    if s.level == 0 {
        for d in 0..=r.top_denom {
            if free(d) {
                for lvl in r.min_level..=r.max_level {
                    out.push(Bid::Contract { level: lvl, denom: d });
                }
            }
        }
        return; // the opener must bid
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
            if r.mode == AucMode::Skat && s.value == 0 {
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
            // The engine's own rule (`apply_bid`): an opening bid carries no
            // jump, a raise carries its rise over the level it overtook.
            n.jump = if s.level > 0 { level - s.level } else { 0 };
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
    memo: HashMap<AucState, f64>,
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
    pub fn settled(&self, s: &AucState) -> f64 {
        if s.declarer < 0 {
            return 0.0; // nothing was ever bid
        }
        let rows = match self.terms.get(settling_bid(s, self.rules.mode).key()) {
            Some(r) if !r.is_empty() => r,
            _ => return 0.0,
        };
        let decl = s.declarer as usize;
        let mine = decl == self.me;
        let mask = if mine { self.worlds.covered } else { self.worlds.covered_opp };
        let mut total = 0.0;
        for w in &self.worlds.worlds {
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
                let v = if mine {
                    o.payoff(w.pts[d], w.duck[d])
                } else {
                    o.payoff(w.opp_pts[d], w.opp_duck[d])
                };
                best = Some(best.map_or(v, |b: i32| b.max(v)));
            }
            if let Some(v) = best {
                total += if mine { v as f64 } else { -v as f64 };
            }
        }
        total
    }

    /// A terms row adjusted for how the settling bid arrived: the jump bonus
    /// rides inside `set_base`, exactly where `engine._terms_for` puts it, so
    /// `payoff` needs no new arm and a doubled row would double it the same
    /// way. Identity when the rule or the jump is zero — every mode but
    /// classic, every payload old enough not to carry the rate.
    #[inline]
    fn with_jump(&self, o: &Option_, jump: u8) -> Option_ {
        let mut o = *o;
        o.set_base += self.rules.jump_set_bonus * jump as i32;
        o
    }

    fn step_value(&mut self, s: &AucState, b: Bid) -> f64 {
        match step(s, &self.rules, b) {
            Step::Settled(t) => self.settled(&t),
            Step::Redeal => 0.0,
            Step::Node(n) => self.value(n),
        }
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
                    // so its jump is the rise over the level standing now.
                    let jump = match b {
                        Bid::Contract { level, .. } if s.level > 0 => level - s.level,
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
                            let v = self.with_jump(o, jump)
                                .payoff(w.opp_pts[d], w.opp_duck[d]);
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

    /// Minimax value of `s` to `me`.
    pub fn value(&mut self, s: AucState) -> f64 {
        if let Some(&v) = self.memo.get(&s) {
            return v;
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
                Some((b, _)) => self.step_value(&s, b),
                None => self.settled(&s),
            };
            self.memo.insert(s, best);
            return best;
        }
        let mut best = if maxing { f64::NEG_INFINITY } else { f64::INFINITY };
        for b in moves {
            let v = self.step_value(&s, b);
            if maxing {
                if v > best {
                    best = v
                }
            } else if v < best {
                best = v
            }
        }
        if !best.is_finite() {
            // No legal action at all: treat the auction as settled where it
            // stands rather than propagating an infinity into an average.
            best = self.settled(&s);
        }
        self.memo.insert(s, best);
        best
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
                   jump_set_bonus: 0, top_denom: 4, ladder: Vec::new(),
                   opp: OppModel::Minimax }
    }

    fn skat_rules(ladder: Vec<u16>) -> AucRules {
        AucRules { mode: AucMode::Skat, min_level: 1, max_level: 12, max_raise: 2,
                   jump_set_bonus: 0, top_denom: 6, ladder, opp: OppModel::Minimax }
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
        Solved { deals: Vec::new(), shown: Vec::new(), covered: 0x7f, covered_opp: 0x7f,
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
        assert_eq!(s1.jump, 0, "an opening bid carries no jump");
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
