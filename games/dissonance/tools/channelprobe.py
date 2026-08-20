"""WHAT IS THE BELIEF PRIOR STILL MISSING? (2026-08-20)

`beliefprobe` established that a uniform resample under-rates the declarer --
their real holding sits at the 0.765 percentile of it -- and the shipped
`bid::BidPrior` corrects that: tilting by `exp(beta x strength)` brings the
STRENGTH percentile to about 0.50. That axis is finished; re-tuning the tilt has
no headroom left.

But the prior conditions on ONE observable (the level the contract settled at)
and corrects ONE statistic (a rank-curve sum). This asks whether the corrected
sample is still mis-calibrated on OTHER dimensions of the declarer's hand -- the
channels nobody has spent. Same method as `beliefprobe`, and the same reason to
trust it: a percentile of the TRUTH inside the sampler's own distribution is 0.50
if and only if the sampler is unbiased on that dimension.

FOUR STATISTICS, one of which is a control:
  * `strength`  -- the control. The prior targets this, so it must read ~0.50
                   after tilting, and a run where it does not is measuring
                   something other than the shipped prior.
  * `trumps`    -- cards in the DECLARED denomination. `trump_mult = 2.0` makes
                   trumps count double in the strength sum, which is not the
                   same as modelling suit LENGTH: a hand can reach the same sum
                   with high cards anywhere.
  * `tops`      -- cards in the top two ranks. Quick tricks against long-suit
                   tricks, the split `featlab` measured as the most independent
                   signal in a hand.
  * `voids`     -- suits the holding is empty in. Ruffing potential, which no
                   rank curve sees at all.

AND TWO CONDITIONAL SPLITS of the strength percentile, because a sampler can be
calibrated ON AVERAGE and wrong in every subgroup:
  * by BID PATH -- a declarer who opened low and was pushed up has a different
    hand from one who opened at the settled level, and the prior sees only where
    it ended.
  * by TALON SWAP -- the defender knows a swap happened. Declining to swap says
    the hand was already good enough, which is evidence the prior discards.

DELIBERATELY SOLVER-FREE, like `beliefprobe`: this measures the SAMPLING, not
the search.

    PYTHONPATH=. python3 games/dissonance/tools/channelprobe.py [rounds]
"""
from __future__ import annotations

import math
import random
import statistics
import sys

from games.dissonance import bot as B
from games.dissonance import engine as E
from games.dissonance.tools import beliefprobe as BP

DRAWS = 200


def stats_of(cards, trump):
    """The four statistics, over one holding."""
    tot = 0.0
    trumps = tops = 0
    suits = [0] * 4
    tc = E.trump_class(trump)
    for c in cards:
        v = B._RANK_VALUE[E.rank(c)]
        is_t = E.esuit(c, trump) == tc
        tot += v * (2.0 if is_t else 1.0)
        trumps += 1 if is_t else 0
        tops += 1 if E.rank(c) >= E.NRANK - 2 else 0
        suits[E.suit(c)] += 1
    return {"strength": tot, "trumps": float(trumps), "tops": float(tops),
            "voids": float(sum(1 for n in suits if n == 0))}


def weighted_percentile(mine, samples, weights):
    """Where `mine` sits among `samples` under `weights`. 0.50 is unbiased.

    MID-RANK, and that is not a refinement -- three of the four statistics here
    are small integers (a holding has 0-13 trumps, 0-4 tops, 0-4 voids), so ties
    are the common case and a strict `<` counts every tie as "above me". The
    first cut did that and `voids` read exactly 0.000 on every round, which is
    what a tie-blind percentile looks like when the truth is usually the modal
    value. `beliefprobe` can use strict `<` because its statistic is a float sum
    that essentially never ties; these cannot.
    """
    tot = below = equal = 0.0
    for s, w in zip(samples, weights):
        tot += w
        if s < mine:
            below += w
        elif s == mine:
            equal += w
    return (below + 0.5 * equal) / tot if tot else 0.5


def probe(g, rng, beta):
    """Per-statistic percentiles, uniform and under the SHIPPED tilt."""
    decl = g["auction"]["declarer"]
    defd = 1 - decl
    trump = g["auction"]["denom"]

    seen = set(g["hands"][defd])
    known_decl = []
    for owner in (0, 1):
        for i, p in enumerate(g["piles"][owner]):
            if not p:
                continue
            seen.add(p[-1])
            if len(p) == 2 and i == 1:
                seen.add(p[0])
            if owner == decl:
                known_decl.append(p[-1])
                if len(p) == 2 and i == 1:
                    known_decl.append(p[0])
    pool = [c for c in range(E.deck_size("classic")) if c not in seen]

    real = list(g["hands"][decl])
    for p in g["piles"][decl]:
        real += list(p)
    n_unknown = len(real) - len(known_decl)
    if n_unknown <= 0 or n_unknown > len(pool):
        return None

    truth = stats_of(real, trump)
    drawn = [stats_of(known_decl + rng.sample(pool, n_unknown), trump)
             for _ in range(DRAWS)]

    # THE TILT IS ON STRENGTH, which is what the shipped prior tilts on -- the
    # other statistics are then read UNDER THAT SAME WEIGHTING. That is the
    # whole question: does correcting strength incidentally correct them?
    ss = [d["strength"] for d in drawn]
    hi = max(ss)
    w = [math.exp(beta * (s - hi)) for s in ss]
    flat = [1.0] * len(drawn)

    out = {}
    for k in truth:
        col = [d[k] for d in drawn]
        out[k] = (weighted_percentile(truth[k], col, flat),
                  weighted_percentile(truth[k], col, w))
    return out


def bid_path(g):
    """`pushed` if the declarer's OPENING was below where it settled."""
    log = [m for m in g["auction"]["log"] if "level" in m]
    decl = g["auction"]["declarer"]
    mine = [m["level"] for m in log if m["seat"] == decl]
    if not mine:
        return None
    return "pushed" if mine[0] < g["auction"]["level"] else "direct"


def main(argv):
    n = int(argv[1]) if len(argv) > 1 else 400
    beta = B._BID_TILT
    rng = random.Random(0xC4A9)
    cols = ["strength", "trumps", "tops", "voids"]
    acc = {k: ([], []) for k in cols}
    by_path = {"pushed": [], "direct": []}
    by_swap = {True: [], False: []}

    got = 0
    for i in range(n * 3):
        if got >= n:
            break
        g = BP.to_double(1000 + i)
        if g is None:
            continue
        r = probe(g, rng, beta)
        if r is None:
            continue
        got += 1
        for k in cols:
            acc[k][0].append(r[k][0])
            acc[k][1].append(r[k][1])
        p = bid_path(g)
        if p:
            by_path[p].append(r["strength"][1])
        by_swap[bool(g.get("swapped"))].append(r["strength"][1])
        if got % 100 == 0:
            print(f"  {got}/{n} rounds", flush=True)

    def line(v):
        return f"{statistics.mean(v):.3f} +/- {statistics.stdev(v)/len(v)**0.5:.3f}" if len(v) > 1 else "n/a"

    print(f"\nchannelprobe: {got} rounds at the Double, {DRAWS} resamples each, "
          f"shipped tilt {beta}")
    print("\n  PER-STATISTIC CALIBRATION -- 0.500 is an unbiased sampler")
    print(f"  {'statistic':>10}  {'uniform':>16}  {'under the tilt':>18}")
    for k in cols:
        u, t = acc[k]
        mark = "   <- the control" if k == "strength" else ""
        print(f"  {k:>10}  {line(u):>16}  {line(t):>18}{mark}")

    print("\n  STRENGTH CALIBRATION, SPLIT -- a sampler can be right on average "
          "and wrong in every subgroup")
    for name, v in (("opened below the settled level", by_path["pushed"]),
                    ("opened at it", by_path["direct"])):
        print(f"    {name:>32}: {line(v):>16}  (n={len(v)})")
    for name, v in ((" swapped the talon", by_swap[True]),
                    ("declined the swap", by_swap[False])):
        print(f"    {name:>32}: {line(v):>16}  (n={len(v)})")
    print("\n  A channel reading 0.500 carries nothing the prior has not already "
          "taken.\n  One reading away from it is an uncorrected bias, i.e. a "
          "lever nobody has pulled.")


if __name__ == "__main__":
    main(sys.argv)
