//! Bots, weakest first. Each one takes a `View`, never the truth.

use crate::dd::Dd;
use crate::game::Bot;
use crate::infer::sample_worlds;
use crate::policy::{policy_best, policy_sample};
use crate::rng::Rng;
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
