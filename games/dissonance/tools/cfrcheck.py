"""IS THE SAMPLER'S ESTIMATOR UNBIASED? Exact enumeration vs both samplers.

WHY THIS EXISTS. `walk_os` (outcome-sampling MCCFR) is ~260x cheaper than
external sampling on the real action space, which is the whole reason it was
built -- but on the level-only abstraction the two samplers converge to
DIFFERENT equilibria, and external is the one that is stable across iteration
counts. That is the signature of a biased estimator rather than a slow one.

A convergence ladder says THAT something is wrong. It cannot say WHERE, because
regret matching is a feedback loop: a small weighting error changes the
strategy, which changes the next estimate. So this freezes the strategy at
UNIFORM and asks the one question that has an exact answer:

    does the sampler's mean regret estimate equal the true counterfactual
    regret, v(I,a) - v(I), computed by full enumeration?

That is the textbook unbiasedness property of MCCFR and it holds INDEPENDENTLY
of the dynamics. If external passes and outcome fails, the bug is in the
importance weighting and nowhere else.

TINY GAME ON PURPOSE. `CFR_MAXL=3` and one deal record: the history tree is a
few hundred leaves, so the enumeration is exact and instant, and both samplers
run the identical code path they run for real. A unit test on a small instance
of the real thing beats a big instance of an approximation.

    PYTHONPATH=. CFR_MAXL=3 python3 games/dissonance/tools/cfrcheck.py [iters]
"""
from __future__ import annotations

import json
import os
import random
import sys
from collections import defaultdict

_ARGV = list(sys.argv)
sys.argv = ["cfrlab.py"]                    # `cfrlab` parses argv at import
from games.dissonance.tools import cfrlab as C   # noqa: E402
sys.argv = _ARGV                            # ...and put it back, so IMPORTING
#: this module is side-effect-free and `tests/test_cfr_unbiased.py` can reuse
#: `exact`/`Frozen` without stealing pytest's own argv.


def exact(rec, me):
    """True counterfactual values under a UNIFORM strategy, by enumeration.

    Walks HISTORIES, not states: several bid sequences can reach the same
    abstract state, and `v(I) = sum over h in I of pi_-i(h) * ...` sums over
    all of them. Collapsing to states first would silently drop that sum, which
    is exactly the kind of shortcut that makes a checker agree with a bug.
    """
    cfa = defaultdict(lambda: defaultdict(float))
    cfi = defaultdict(float)

    def go(level, prev, holds, to_act, pi_opp):
        acts = C.actions(level, holds)
        key = (rec["b"][to_act], level, prev, holds)
        p = 1.0 / len(acts)
        vals = {}
        for a in acts:
            if a == -1:
                holder = 1 - to_act
                vals[a] = C.leaf(rec, level, prev, holder, holds) * \
                    (1 if holder == me else -1)
            else:
                nl, np_, nh = C._step(level, prev, holds, a)
                vals[a] = go(nl, np_, nh, 1 - to_act,
                             pi_opp * (1.0 if to_act == me else p))
        node = sum(p * v for v in vals.values())
        if to_act == me:
            for a in acts:
                cfa[key][a] += pi_opp * vals[a]
            cfi[key] += pi_opp * node
        return node

    go(0, 0, 0, 0, 1.0)
    return cfa, cfi


class Frozen(C.CFR):
    """Uniform strategy, raw (unfloored) regret accumulation."""

    def __init__(self, recs):
        super().__init__(recs)
        self.raw = defaultdict(lambda: defaultdict(float))

    def strategy(self, key, acts):
        return {a: 1.0 / len(acts) for a in acts}

    def bump(self, key, a, r):
        self.raw[key][a] += r


def run(recs, rec, me, sampling, iters, seed=11):
    C.SAMPLING = sampling
    cfr = Frozen(recs)
    rng = random.Random(seed)
    for i in range(iters):
        cfr.t = i + 1
        cfr.iterate(rec, me, rng)
    return {k: {a: v / iters for a, v in d.items()} for k, d in cfr.raw.items()}


def main(argv):
    iters = int(argv[1]) if len(argv) > 1 else 400000
    ck = os.environ.get("CFR_CKPT")
    recs = [json.loads(x) for x in open(ck) if x.strip()][:200]
    C.bucketise(recs)
    rec, me = recs[0], 0
    cfa, cfi = exact(rec, me)
    truth = {k: {a: cfa[k][a] - cfi[k] for a in cfa[k]} for k in cfa}

    print(f"MAXL={C.MAXL}  DENOMS={C.DENOMS}  opening actions="
          f"{len(C.actions(0, 0))}  infosets for seat {me}: {len(truth)}")
    print(f"iters={iters:,}\n")
    for sampling in ("external", "outcome"):
        got = run(recs, rec, me, sampling, iters)
        num = den = 0.0
        worst = (0.0, None)
        for k, row in truth.items():
            for a, t in row.items():
                g = got.get(k, {}).get(a, 0.0)
                num += abs(g - t)
                den += abs(t)
                if abs(g - t) > worst[0]:
                    worst = (abs(g - t), (k, a, t, g))
        rel = num / den if den else 0.0
        flag = "OK  " if rel < 0.05 else "BIAS"
        print(f"  {flag} {sampling:<9} mean |estimate - truth| / mean |truth| "
              f"= {rel:.4f}")
        if worst[1]:
            k, a, t, g = worst[1]
            print(f"       worst infoset {k} action {a}: "
                  f"truth {t:+.4f}  estimate {g:+.4f}")
    print("\n  Both samplers estimate the SAME quantity under a frozen "
          "strategy.\n  A sampler that misses it is mis-weighted, and the "
          "ladder cannot say which.")


if __name__ == "__main__":
    main(_ARGV)
