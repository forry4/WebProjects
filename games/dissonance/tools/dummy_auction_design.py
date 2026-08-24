"""What SHAPE of contract ladder does dummy mode's spread support?

`dummy_auction_probe` showed the shipped ladder is not a decision: expected
payoff climbs from +10 at level 1 to +60 at level 9 and never really turns
over, so there is no such thing as bidding too high. This asks WHY, and what
would fix it, from the one distribution everything follows from -- how many
points the declarer actually takes.

Two candidate causes, and they want different fixes:
  * THE SCALE. The declarer commands two of three hands, so they bank ~70% of
    the pool before making any decision at all. Every rung below that is a
    contract you make by doing nothing, which is most of the ladder.
  * THE CURVE. Make pays N^2 and a set costs N + 5 x short, so reward grows
    quadratically against linear risk. Calibrated at classic's levels 3-5 that
    is fine; at 9-12 it means a 20%-likely contract is still +EV.

...and one thing that would sink ANY ladder: if the declarer's total barely
varies, the contract is a bid on a near-constant and no pricing makes it a
decision. That is what the spread below is for.

    PYTHONPATH=. python -m games.dissonance.tools.dummy_auction_design [rounds]
"""

from __future__ import annotations

import random
import statistics
import sys
from collections import Counter
from math import gcd

from games.dissonance import engine as E
from games.dissonance.tools.dummy_auction_probe import forced_round

#: Classic's curve, the one dummy mode inherited.
SHORT = E.SHORT_PENALTY
OVER = 1


def collect(n: int, seed: int = 23):
    """The declarer's point total over `n` rounds, and the pool it came from."""
    rng = random.Random(seed)
    pts, pools = [], []
    for _ in range(n):
        # Level 1 so nothing is ever set -- we want the POINTS the cards yield,
        # not a distribution shaped by the contract on top of them.
        g = forced_round(rng, 1)
        pts.append(g["result"]["declarer_pts"])
        pools.append(E.played_pool(g))
    return pts, pools


def ev_curve(pts, target_of, max_level):
    """Expected payoff per level under a proposed target mapping."""
    out = []
    for lvl in range(1, max_level + 1):
        t = target_of(lvl)
        made = [p for p in pts if p >= t]
        rate = len(made) / len(pts)
        gain = sum(lvl * lvl + OVER * (p - t) for p in made)
        loss = sum(lvl + SHORT * (t - p) for p in pts if p < t)
        out.append((lvl, t, rate, (gain - loss) / len(pts)))
    return out


def show(name, curve):
    print(f"\n  {name}")
    print(f"  {'lvl':>4} {'target':>7} {'made':>6} {'EV':>8}")
    for lvl, t, rate, ev in curve:
        print(f"  {lvl:>4} {t:>7} {100 * rate:>5.0f}% {ev:>+8.1f}")
    best = max(curve, key=lambda r: r[3])
    top = curve[-1]
    print(f"  peak at level {best[0]} (EV {best[3]:+.1f}); "
          f"ceiling EV {top[3]:+.1f} -- "
          f"{'A REAL CHOICE' if best[0] < top[0] else 'STILL BID THE TOP'}")


def main(n: int) -> None:
    pts, pools = collect(n)
    print(f"\n== dummy: what the cards actually yield ({n} rounds) ==")
    print(f"declarer points: mean {statistics.mean(pts):.1f}  "
          f"sd {statistics.pstdev(pts):.1f}  "
          f"min {min(pts)}  max {max(pts)}")
    q = sorted(pts)
    for label, frac in (("p10", .1), ("p25", .25), ("p50", .5), ("p75", .75), ("p90", .9)):
        print(f"   {label} {q[int(frac * (len(q) - 1))]}", end="")
    print()
    print("pool:", dict(sorted(Counter(pools).items())))
    share = statistics.mean(p / pl for p, pl in zip(pts, pools))
    print(f"the declarer banks {100 * share:.0f}% of the pool on average "
          f"-- before deciding anything, just for holding the dummy")

    # THE GRANULARITY, which is what decides how fine a ladder can be, and it
    # is COMPUTED rather than asserted -- it was 3 and is 1 now, and a hardcoded
    # step would have gone on printing the old claim under the new deck.
    #
    # The old table made every card -1 or +2, both 2 mod 3, so THREE of them
    # always summed to a multiple of 3 (a two-card trick has no such property:
    # -2/+1/+4). Every dummy total was a multiple of 3, so contracts of 7, 8
    # and 9 were literally the same contract and two thirds of the ladder was
    # duplicate rungs. The wide deck's zero-worth 5 and 6 break it.
    step = 0
    for a in E.CARD_VALUES:
        for b in E.CARD_VALUES:
            for c in E.CARD_VALUES:
                step = gcd(step, abs(a + b + c))
    step = step or 1
    print(f"\nreachable totals: {sorted(set(pts))}")
    print(f"a three-card trick is always a multiple of {step} -- so a ladder "
          f"finer than {step} is mostly duplicate rungs")

    print("\n== candidate ladders ==")
    show("SHIPPED: target = level, 1..12",
         ev_curve(pts, lambda l: l, 12))
    show("STEP-3: target = 3 x level, 1..6",
         ev_curve(pts, lambda l: 3 * l, 6))
    show("STEP-3 above a floor: target = 3 + 3 x level, 1..5",
         ev_curve(pts, lambda l: 3 + 3 * l, 5))
    show("STEP-3 above par: target = 6 + 3 x level, 1..4",
         ev_curve(pts, lambda l: 6 + 3 * l, 4))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 300)
