"""BOTH MCCFR SAMPLERS MUST ESTIMATE THE SAME THING. A permanent gate.

WHY THIS IS A TEST AND NOT A NOTE. `cfrlab` grew a second sampler
(outcome-sampling MCCFR) because external sampling costs the BRANCHING FACTOR
at our own nodes and the real action space has 40x more of it. The first
version of that sampler ran, converged, and printed a plausible auction policy
-- and was importance-weighted wrong, systematically shrinking every estimate
toward zero (the worst infoset read 2.83 against a true 6.64). Nothing crashed
and no existing test moved, because the thing it broke was a NUMBER nobody had
an independent source for.

The independent source is enumeration. Freeze the strategy at uniform and both
samplers estimate exactly `v(I,a) - v(I)`, which a tiny game can compute
exactly -- and that unbiasedness holds regardless of the regret-matching
dynamics, so the check is sharp rather than a convergence race. A convergence
ladder can only say THAT the two disagree; this says WHICH one is wrong.

SYNTHETIC DEALS ON PURPOSE. The solver's deal cache is a gitignored research
artifact, and a test that needs one is a test that skips -- which this package
forbids. `leaf` reads only `pts`/`duck` off a record and `bucketise` only
`str`, so a handful of hand-written records exercises the identical code path.
"""
import random

import pytest

from games.dissonance.tools import cfrcheck as K
from games.dissonance.tools import cfrlab as C


#: Small enough to enumerate exactly and instantly, big enough that the
#: auction actually branches: at `MAXL = 3` the opening offers three actions
#: and the tree still runs several plies deep.
MAXL = 3

#: PER SAMPLER, because their costs and their variances run in OPPOSITE
#: directions: external evaluates every action at our nodes (~10x the wall
#: clock per iteration) and lands inside 0.5%, outcome walks one path and pays
#: for it in variance. Sized off five seeds so the band is headroom over a
#: measured worst case rather than a guess: external reads ~0.005 at 60k,
#: outcome 0.036-0.045 at 400k.
ITERS = {"external": 60_000, "outcome": 400_000}


@pytest.fixture
def tiny(monkeypatch):
    """A three-level auction over four hand-written deals."""
    monkeypatch.setattr(C, "MAXL", MAXL)
    monkeypatch.setattr(C, "SAMPLING", "external")
    recs = [{"str": [s0, s1], "pts": [p0, p1], "duck": [False, False]}
            for s0, s1, p0, p1 in [(6.0, 13.0, 2, 6), (15.0, 6.0, 7, 2),
                                   (10.0, 11.0, 4, 4), (12.0, 8.0, 5, 3)]]
    C.bucketise(recs)
    return recs


def _relative_error(recs, sampling, iters=None):
    """Mean |estimate - truth| over mean |truth|, across every infoset."""
    rec, me = recs[0], 0
    iters = iters or ITERS[sampling]
    cfa, cfi = K.exact(rec, me)
    got = K.run(recs, rec, me, sampling, iters)
    num = den = 0.0
    for k, row in cfa.items():
        for a in row:
            truth = row[a] - cfi[k]
            num += abs(got.get(k, {}).get(a, 0.0) - truth)
            den += abs(truth)
    assert den > 0, "the enumeration found no counterfactual value to check"
    return num / den


@pytest.mark.parametrize("sampling", ["external", "outcome"])
def test_the_sampler_estimates_the_true_counterfactual_regret(tiny, sampling):
    """The gate. One band for both, at ~2x the worst of five seeds for outcome
    and ~20x for external -- and the weighting bug this exists to catch read
    71%, so neither margin is anywhere near it."""
    assert _relative_error(tiny, sampling) < 0.10


def test_the_check_is_sharp_enough_to_catch_a_mis_weighting(tiny,
                                                            monkeypatch):
    """...and the gate above cannot pass by being generous.

    The defect that shipped was a MISSING MULTIPLICATIVE FACTOR in `1/q`: a
    terminal reached by a pass was priced without the sampled action's own
    probability, so every such estimate came back shrunk. This injects the same
    shape with a constant factor -- and deliberately a MILDER one (0.5, against
    a real probe mass that ran nearer 0.33), so passing says the gate catches
    less than what actually happened. Without this, a band wide enough to
    absorb outcome sampling's variance is also wide enough to absorb a real
    bug, and nobody would know which until the next campaign measured
    something false.
    """
    real = C.CFR.walk_os

    def unweighted(self, rec, level, prev, holds, to_act, me, rng,
                   pi_me=1.0, pi_opp=1.0, q=1.0):
        # `leaf`'s utility is divided by the trajectory probability; dropping
        # the last factor is a plain under-count of every terminal.
        u, tail = real(self, rec, level, prev, holds, to_act, me, rng,
                       pi_me, pi_opp, q)
        return u * 0.5, tail

    monkeypatch.setattr(C.CFR, "walk_os", unweighted)
    assert _relative_error(tiny, "outcome") > 0.10
