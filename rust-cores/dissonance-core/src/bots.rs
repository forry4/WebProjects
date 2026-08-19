//! Bots, weakest first. Each one takes a `View`, never the truth.

use crate::dd::Dd;
use crate::game::Bot;
use crate::infer::sample_worlds;
use crate::policy::{policy_best, policy_sample};
use crate::rng::Rng;
use crate::cards::UNKNOWN;
use crate::state::*;
use crate::view::View;

pub struct RandomBot {
    pub rng: Rng,
}

impl Bot for RandomBot {
    fn pick(&mut self, v: &View) -> u8 {
        let mut m = [0u8; 16];
        let n = v.legal(&mut m);
        m[self.rng.below(n)]
    }
    fn name(&self) -> String {
        "random".into()
    }
}

/// One-trick-deep heuristic: take the +2 tricks as cheaply as possible, shed
/// the -1 tricks as expensively as possible. No lookahead, no card counting —
/// this is the floor a searching bot has to clear by a wide margin. It shares
/// its scoring with the inference model, so "what would a sensible player do"
/// is defined in exactly one place.
pub struct GreedyBot;

impl Bot for GreedyBot {
    fn pick(&mut self, v: &View) -> u8 {
        let mut m = [0u8; 16];
        let n = v.legal(&mut m);
        policy_best(&v.s, &m[..n])
    }
    fn name(&self) -> String {
        "greedy".into()
    }
}

/// How to collapse one value per world into one choice.
#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Agg {
    /// Average value across worlds. The textbook PIMC rule.
    Mean,
    /// Count the worlds where a move is (co-)optimal. Less swayed by a single
    /// world where one move is enormously good — which is exactly the shape
    /// strategy fusion produces.
    Vote,
    /// The q-th quantile of the value across worlds; q<0.5 is risk-averse and
    /// declines plans that only work if you know which world you are in.
    Quantile(f32),
}

/// Perfect-Information Monte Carlo: sample worlds consistent with what this
/// player knows, solve each one exactly, and combine.
///
/// Chosen over MCTS on purpose. The round is only 26 plies with a branching
/// factor that mandatory follow-suit keeps near 3, so an exact solve is cheap
/// — and an exact solve of a sampled world beats an approximate search of the
/// real one at this size.
///
/// `particles > 0` turns on opponent-aware resampling (see `infer.rs`);
/// `particles == 0` with `Agg::Mean` is textbook PIMC.
pub struct PimcBot {
    pub k: usize,
    pub particles: usize,
    pub temp: f32,
    pub agg: Agg,
    /// Weight on the IIMC term. 0 is pure double-dummy PIMC.
    pub lambda: f32,
    /// Imperfect-information playouts per world per root move.
    pub playouts: usize,
    pub ptemp: f32,
    /// When set, the search optimises this CONTRACT's payoff instead of trick
    /// points. Points are only the yardstick: they cannot see that a declarer
    /// past their target gains nothing more, that each point of a defender's
    /// shortfall is worth four, or that a declarer on no +2 trick is one ducked
    /// trick from scoring the Null consolation instead of being set.
    pub contract: Option<crate::dd::Contract>,
    /// The auction as evidence about the declarer's hand -- see
    /// `bid::BidPrior`. None is uniform sampling, which is every bot built
    /// before this existed and is what `PimcBot::new`/`full` still give.
    pub prior: Option<crate::bid::BidPrior>,
    pub dd: Dd,
    pub rng: Rng,
    buf: Vec<u8>,
    worlds: Vec<State>,
    pub label: String,
}

impl PimcBot {
    pub fn new(k: usize, seed: u64, tt_bits: u32) -> Self {
        PimcBot::full(k, 0, f32::INFINITY, Agg::Mean, 0.0, 0, 0.5, seed, tt_bits)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn full(
        k: usize,
        particles: usize,
        temp: f32,
        agg: Agg,
        lambda: f32,
        playouts: usize,
        ptemp: f32,
        seed: u64,
        tt_bits: u32,
    ) -> Self {
        let label = if particles == 0 && agg == Agg::Mean && lambda == 0.0 {
            format!("pimc{}", k)
        } else {
            format!(
                "pimc{}/p{}/t{}/{:?}/L{}/s{}",
                k, particles, temp, agg, lambda, playouts
            )
        };
        PimcBot {
            k,
            particles,
            temp,
            agg,
            lambda,
            playouts,
            ptemp,
            contract: None,
            dd: Dd::new(tt_bits),
            rng: Rng::new(seed),
            buf: Vec::with_capacity(16),
            prior: None,
            worlds: Vec::with_capacity(64),
            label,
        }
    }
}

impl Bot for PimcBot {
    fn pick(&mut self, v: &View) -> u8 {
        let mut m = [0u8; 16];
        let n = v.legal(&mut m);
        if n == 1 {
            return m[0];
        }
        sample_worlds(
            v,
            &mut self.rng,
            self.particles,
            self.temp,
            self.k,
            &mut self.buf,
            &mut self.worlds,
            self.prior.as_ref(),
        );

        // A contract solve is signed for the DECLARER; a points solve for seat
        // 0. Same aggregation either way -- only what is being aggregated moves.
        if let Some(c) = self.contract {
            let sign = if v.me == c.declarer { 1i32 } else { -1i32 };
            let mut cv = [0i32; 16];
            let mut score = [0f64; 16];
            for w in self.worlds.iter() {
                self.dd.solve_root_contract(w, &m[..n], &c, &mut cv);
                for i in 0..n {
                    score[i] += (sign * cv[i]) as f64;
                }
            }
            let mut best = 0usize;
            for i in 1..n {
                if score[i] > score[best] {
                    best = i;
                }
            }
            return m[best];
        }

        let sign = if v.me == 0 { 1i16 } else { -1i16 };
        let mut vals = [0i16; 16];
        let mut per_world: Vec<[i16; 16]> = Vec::with_capacity(self.worlds.len());
        for w in self.worlds.iter() {
            self.dd.solve_root(w, &m[..n], &mut vals);
            let mut row = [0i16; 16];
            for i in 0..n {
                row[i] = sign * vals[i];
            }
            per_world.push(row);
        }

        let mut score = [0f64; 16];
        match self.agg {
            Agg::Mean => {
                for row in &per_world {
                    for i in 0..n {
                        score[i] += row[i] as f64;
                    }
                }
            }
            Agg::Vote => {
                for row in &per_world {
                    let best = (0..n).map(|i| row[i]).max().unwrap();
                    for i in 0..n {
                        if row[i] == best {
                            score[i] += 1.0;
                        }
                    }
                }
            }
            Agg::Quantile(q) => {
                let w = per_world.len();
                let idx = (((w as f32 - 1.0) * q).round() as usize).min(w.saturating_sub(1));
                let mut col: Vec<i16> = Vec::with_capacity(w);
                for i in 0..n {
                    col.clear();
                    for row in &per_world {
                        col.push(row[i]);
                    }
                    col.sort_unstable();
                    score[i] = col[idx] as f64;
                }
            }
        }

        // IIMC: instead of asking what this move is worth to a player who will
        // KNOW the deal from here on, play the rest out with policies that
        // never see the hidden cards. That is what actually prices strategy
        // fusion -- a double-dummy value cannot, at any sample count.
        if self.lambda > 0.0 && self.playouts > 0 {
            let mut roll = [0f64; 16];
            for w in self.worlds.iter() {
                for i in 0..n {
                    let mut acc = 0f64;
                    for _ in 0..self.playouts {
                        let mut st = *w;
                        let mut d = st.play(m[i]) as i32;
                        let mut cands = [0u8; 16];
                        while !st.done() {
                            let cn = st.legal(&mut cands);
                            let c = policy_sample(&st, &cands[..cn], self.ptemp, &mut self.rng);
                            d += st.play(c) as i32;
                        }
                        acc += (sign as i32 * d) as f64;
                    }
                    roll[i] += acc / self.playouts as f64;
                }
            }
            let nw = self.worlds.len().max(1) as f64;
            for i in 0..n {
                // Both terms are in differential units, so they blend directly.
                let dd_mean = score[i] / nw;
                score[i] = (1.0 - self.lambda as f64) * dd_mean
                    + self.lambda as f64 * (roll[i] / nw);
            }
        }

        let mut best = 0;
        for i in 1..n {
            if score[i] > score[best] {
                best = i;
            }
        }
        m[best]
    }
    fn name(&self) -> String {
        self.label.clone()
    }
}

/// A cheat bot that sees everything — the strength ceiling, and the yardstick
/// for how much the hidden information is actually worth.
pub struct OracleBot {
    pub dd: Dd,
    pub truth: State,
}

impl OracleBot {
    pub fn new(tt_bits: u32) -> Self {
        OracleBot {
            dd: Dd::new(tt_bits),
            truth: State {
                hand: [0; 2],
                pile: [[Pile::default(); 3]; 2],
                trump: crate::cards::NOTRUMP,
                trick: 0,
                leader: 0,
                led: -1,
                pts: [0; 2],
                escored: 0,
                even: 2,
                cards: false,
                head: false,
            },
        }
    }
}

impl Bot for OracleBot {
    fn pick(&mut self, v: &View) -> u8 {
        let mut m = [0u8; 16];
        let n = v.legal(&mut m);
        if n == 1 {
            return m[0];
        }
        let mut vals = [0i16; 16];
        self.dd.solve_root(&self.truth, &m[..n], &mut vals);
        let sign = if v.me == 0 { 1i16 } else { -1i16 };
        let mut best = 0;
        for i in 1..n {
            if sign * vals[i] > sign * vals[best] {
                best = i;
            }
        }
        m[best]
    }
    fn name(&self) -> String {
        "oracle".into()
    }
    fn observe_truth(&mut self, s: &State) {
        self.truth = *s;
    }
}

/// One world inside an alpha-mu search: its state, the differential already
/// banked on the way here, and what WE have observed since the last decision.
#[derive(Clone)]
struct AmuNode {
    s: State,
    /// Seat 0's differential banked by the plays made so far in this world.
    g: i32,
    /// Everything we can SEE that could differ between worlds: both seats' pile
    /// tops, then the cards played since our previous decision. See
    /// `AmuNode::observable` -- getting this wrong is not a strength bug, it
    /// makes the search return cards that are illegal in the real position.
    key: Vec<u8>,
}

impl AmuNode {
    /// The part of this world we could actually be looking at.
    ///
    /// THE PILE TOPS ARE IN HERE AND THAT IS THE WHOLE POINT. Our own two
    /// OUTER pile bottoms are hidden from us as well as from the opponent, so
    /// the determinizer fills them differently in every world -- and the moment
    /// we play a pile top, the card underneath becomes both playable and
    /// public. Two worlds that expose different cards under our own pile are
    /// therefore worlds we can TELL APART, and they are also worlds with
    /// different legal sets for us.
    ///
    /// The first cut keyed on the opponent's played cards alone and took the
    /// group's legal moves from its first world. That reached
    /// `panic!("illegal card ... for player")` inside `State::play` on the
    /// second decision -- the search was offering a card that existed only in
    /// one member of the group, and `every_card_it_returns_is_legal_in_the_real_position`
    /// caught the same thing at the root.
    fn observable(&self, since: &[u8]) -> Vec<u8> {
        let mut k = Vec::with_capacity(6 + since.len());
        for q in 0..2 {
            for i in 0..3 {
                k.push(self.s.pile[q][i].top().unwrap_or(UNKNOWN));
            }
        }
        k.extend_from_slice(since);
        k
    }
}

/// ALPHA-MU: commit to ONE card across every world for `m` of our decisions,
/// and only then hand the rest to the double-dummy solver.
///
/// THE DEFECT IT ATTACKS. `diag` decomposed our residual and found the
/// signature of STRATEGY FUSION rather than of bad sampling: 89.5% of decisions
/// already optimal, and the world-MAJORITY move optimal only 82.9% of the time,
/// i.e. worse than the mean aggregator. CAMPAIGN.md's reading -- "a double-dummy
/// value prices a move for a player who will KNOW the deal from here on, and no
/// re-weighting and no re-aggregation of those values can fix it" -- is correct
/// about aggregation and is not the end of the story. Cazenave & Ventos's answer
/// for bridge was a different SEARCH: carry a vector of outcomes across the
/// possible worlds and refuse to collapse it, so the search cannot quietly play
/// a different strategy in each world.
///
/// WHAT IS FAITHFUL HERE AND WHAT IS NOT, stated plainly because the name
/// carries a claim. Faithful: the anti-fusion mechanism, which is that one card
/// must serve every world in an information set, iterated `m` deep, with
/// `m = 1` reproducing plain PIMC exactly. Not faithful: the published
/// algorithm keeps PARETO FRONTS over vectors of BOOLEAN outcomes (in bridge,
/// making the contract), and prunes on dominance. This game's shipped objective
/// is a real-valued payoff, where Pareto dominance is far too weak to prune on,
/// so our nodes aggregate by mean over the group's worlds. So this is alpha-mu's
/// commitment structure with PIMC's aggregator, not the paper's search.
///
/// THE GROUPING IS LOAD-BEARING AND IS NOT AN OPTIMISATION. After our card, the
/// opponent replies, and WHO IS ON LEAD NEXT depends on who won the trick --
/// which depends on the hidden cards, so it differs across worlds. So does the
/// card they lead, and therefore what we are allowed to play. "One card for all
/// worlds" is only correct across worlds we CANNOT TELL APART: worlds where
/// they led differently are different information sets for us and must be
/// allowed different answers. Hence `AmuNode::key` -- the cards played since our
/// last decision, all of which we see -- and hence the partition before every
/// one of our decisions. Committing across the whole sample instead would not
/// be a stronger search, it would be an illegal one.
///
/// THE OPPONENT IS LEFT CLAIRVOYANT, deliberately. They pick their double-dummy
/// best reply in each world independently, which is exactly what PIMC already
/// assumes about them and is the pessimistic half the crate documents. Removing
/// OUR fusion is the lever being tested here; removing theirs is a different
/// experiment and would confound this one.
pub struct AlphaMuBot {
    pub k: usize,
    /// How many of OUR decisions are committed across worlds before the solver
    /// takes over. 1 is plain PIMC, and is asserted to be so.
    pub m: usize,
    pub dd: Dd,
    pub rng: Rng,
    buf: Vec<u8>,
    worlds: Vec<State>,
    pub label: String,
    /// Double-dummy solves spent on the last `pick`, for the equal-time gate.
    pub solves: u64,
}

impl AlphaMuBot {
    pub fn new(k: usize, m: usize, seed: u64, tt_bits: u32) -> Self {
        AlphaMuBot {
            k,
            m: m.max(1),
            dd: Dd::new(tt_bits),
            rng: Rng::new(seed),
            buf: Vec::with_capacity(16),
            worlds: Vec::with_capacity(64),
            label: format!("amu{}:{}", m.max(1), k),
            solves: 0,
        }
    }

    /// The opponent's double-dummy best reply in this one world.
    fn opp_best(&mut self, s: &State, me: usize) -> u8 {
        let mut mv = [0u8; 16];
        let n = s.legal(&mut mv);
        if n == 1 {
            return mv[0];
        }
        let mut vals = [0i16; 16];
        self.dd.solve_root(s, &mv[..n], &mut vals);
        self.solves += n as u64;
        // `vals` are seat 0's differential. The mover here is `1 - me`: seat 0
        // maximises it, seat 1 minimises it.
        let opp_is_seat0 = (1 - me) == 0;
        let mut best = 0usize;
        for i in 1..n {
            let better = if opp_is_seat0 { vals[i] > vals[best] } else { vals[i] < vals[best] };
            if better {
                best = i;
            }
        }
        mv[best]
    }

    /// Summed value over `nodes`, signed for us, with `m_left` of our decisions
    /// still to be committed.
    fn amu(&mut self, mut nodes: Vec<AmuNode>, m_left: usize, me: usize, sign: i32) -> f64 {
        // THE LEAF IS CHECKED BEFORE THE OPPONENT IS ADVANCED, which is what
        // makes m = 1 exactly PIMC rather than merely equal to it: the solver
        // plays the opponent optimally anyway, so advancing first would spend
        // solves to reach the identical number.
        if m_left == 0 {
            let mut total = 0.0;
            for nd in &nodes {
                let v = if nd.s.done() { 0 } else { self.dd.solve(&nd.s) as i32 };
                self.solves += 1;
                total += (sign * (nd.g + v)) as f64;
            }
            return total;
        }

        // Advance every world to our next decision, opponent playing its own
        // double-dummy best, recording what we see on the way.
        for nd in nodes.iter_mut() {
            let mut since: Vec<u8> = Vec::new();
            while !nd.s.done() && nd.s.to_play() as usize != me {
                let c = self.opp_best(&nd.s, me);
                nd.g += nd.s.play(c) as i32;
                since.push(c);
            }
            nd.key = nd.observable(&since);
        }

        // Partition by what we observed: worlds we cannot tell apart must get
        // the same card, worlds we can must be free to differ.
        let mut groups: Vec<(Vec<u8>, Vec<AmuNode>)> = Vec::new();
        for nd in nodes {
            match groups.iter_mut().find(|(k, _)| *k == nd.key) {
                Some((_, g)) => g.push(nd),
                None => groups.push((nd.key.clone(), vec![nd])),
            }
        }

        let mut total = 0.0;
        for (_, group) in groups {
            if group[0].s.done() {
                for nd in &group {
                    total += (sign * nd.g) as f64;
                }
                continue;
            }
            let mut mv = [0u8; 16];
            let n = group[0].s.legal(&mut mv);
            let mut best = f64::NEG_INFINITY;
            for i in 0..n {
                let children: Vec<AmuNode> = group
                    .iter()
                    .map(|nd| {
                        let mut s = nd.s;
                        let g = nd.g + s.play(mv[i]) as i32;
                        AmuNode { s, g, key: Vec::new() }
                    })
                    .collect();
                let v = self.amu(children, m_left - 1, me, sign);
                if v > best {
                    best = v;
                }
            }
            total += best;
        }
        total
    }
}

impl Bot for AlphaMuBot {
    fn pick(&mut self, v: &View) -> u8 {
        self.solves = 0;
        let mut m = [0u8; 16];
        let n = v.legal(&mut m);
        if n == 1 {
            return m[0];
        }
        // The SAME sampler PimcBot uses, with the same arguments, so an
        // alpha-mu(1) arm draws the identical worlds from the identical stream.
        sample_worlds(
            v,
            &mut self.rng,
            0,
            f32::INFINITY,
            self.k,
            &mut self.buf,
            &mut self.worlds,
            None,
        );
        let sign = if v.me == 0 { 1i32 } else { -1i32 };
        let worlds = self.worlds.clone();
        let mut score = [f64::NEG_INFINITY; 16];
        for i in 0..n {
            let children: Vec<AmuNode> = worlds
                .iter()
                .map(|w| {
                    let mut s = *w;
                    let g = s.play(m[i]) as i32;
                    AmuNode { s, g, key: Vec::new() }
                })
                .collect();
            score[i] = self.amu(children, self.m - 1, v.me, sign);
        }
        let mut best = 0;
        for i in 1..n {
            if score[i] > score[best] {
                best = i;
            }
        }
        m[best]
    }
    fn name(&self) -> String {
        self.label.clone()
    }
}

#[cfg(test)]
mod amu_tests {
    use super::*;
    use crate::game::Game;

    /// THE NULL CONTROL, AND IT IS AN IDENTITY RATHER THAN A RESEMBLANCE.
    ///
    /// Every arm this crate trusts has one: `lambda = 0` reproduces `pimc:8`
    /// byte for byte, `Soft(0)` is the exact minimax, a `BidPrior` tilt of 0 is
    /// uniform sampling on the same RNG draws. Without it an alpha-mu result is
    /// confounded by whatever else differs between two bots that merely look
    /// alike. Here the claim is that alpha-mu(1) IS PIMC: one card committed
    /// across the worlds and the solver taking everything after it is exactly
    /// what `solve_root` computes, so the two must agree on every card of a
    /// whole game, from the same seed, on both seats.
    #[test]
    fn alpha_mu_at_depth_one_is_exactly_pimc() {
        for seed in 1..7u64 {
            for k in [1usize, 4, 8] {
                let mut g = Game::deal(&mut Rng::new(seed), (seed % 5) as u8, 0);
                let mut pimc: Vec<PimcBot> =
                    (0..2).map(|q| PimcBot::new(k, 0x11 ^ seed ^ (q as u64) << 8, 18)).collect();
                let mut amu: Vec<AlphaMuBot> =
                    (0..2).map(|q| AlphaMuBot::new(k, 1, 0x11 ^ seed ^ (q as u64) << 8, 18)).collect();
                let mut ply = 0;
                while !g.over() {
                    let p = g.s.to_play() as usize;
                    let v = g.view(p);
                    let a = pimc[p].pick(&v);
                    let b = amu[p].pick(&v);
                    assert_eq!(
                        a, b,
                        "seed {seed} k {k} ply {ply}: pimc played {a}, alpha-mu(1) played {b}"
                    );
                    g.apply(a);
                    ply += 1;
                }
            }
        }
    }

    /// ...AND DEPTH 2 IS A DIFFERENT BOT. A null control only means something
    /// beside a positive control: if alpha-mu(2) also agreed everywhere, the
    /// identity above would be telling us the depth knob does nothing rather
    /// than that the arm is clean.
    #[test]
    fn alpha_mu_at_depth_two_actually_diverges_from_pimc() {
        let mut differed = 0;
        let mut compared = 0;
        for seed in 1..7u64 {
            let mut g = Game::deal(&mut Rng::new(seed), (seed % 5) as u8, 0);
            let mut pimc: Vec<PimcBot> =
                (0..2).map(|q| PimcBot::new(4, 0x22 ^ seed ^ (q as u64) << 8, 18)).collect();
            let mut amu: Vec<AlphaMuBot> =
                (0..2).map(|q| AlphaMuBot::new(4, 2, 0x22 ^ seed ^ (q as u64) << 8, 18)).collect();
            while !g.over() {
                let p = g.s.to_play() as usize;
                let v = g.view(p);
                let a = pimc[p].pick(&v);
                let b = amu[p].pick(&v);
                let mut mv = [0u8; 16];
                if v.legal(&mut mv) > 1 {
                    compared += 1;
                    if a != b {
                        differed += 1;
                    }
                }
                g.apply(a);
            }
        }
        assert!(compared > 40, "only {compared} real choices were compared");
        assert!(
            differed > 0,
            "alpha-mu(2) agreed with PIMC on all {compared} choices -- the depth knob is inert"
        );
    }

    /// THE COMMITMENT IS ACROSS INDISTINGUISHABLE WORLDS ONLY. If the grouping
    /// were dropped, the search would force one card on worlds where the
    /// opponent led different suits -- frequently ILLEGAL, since follow-suit
    /// depends on what was led. So every card alpha-mu returns has to be legal
    /// in the real position, at every depth, which is the cheapest possible
    /// check that the partition exists and is being used.
    #[test]
    fn every_card_it_returns_is_legal_in_the_real_position() {
        for m in [1usize, 2, 3] {
            for seed in 1..5u64 {
                let mut g = Game::deal(&mut Rng::new(seed), (seed % 5) as u8, 0);
                let mut bots: Vec<AlphaMuBot> = (0..2)
                    .map(|q| AlphaMuBot::new(4, m, 0x33 ^ seed ^ (q as u64) << 8, 18))
                    .collect();
                while !g.over() {
                    let p = g.s.to_play() as usize;
                    let v = g.view(p);
                    let c = bots[p].pick(&v);
                    let mut mv = [0u8; 16];
                    let n = v.legal(&mut mv);
                    assert!(
                        mv[..n].contains(&c),
                        "m={m} seed={seed}: alpha-mu returned {c}, not among {:?}",
                        &mv[..n]
                    );
                    g.apply(c);
                }
            }
        }
    }
}
