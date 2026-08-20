"""Is there anything to widen the auction abstraction WITH? (2026-08-20)

`cfrlab`'s abstraction sees one number about a hand: the quantile bucket of
`bot.hand_strength` over the seat's best denomination. Edelkamp's outer-learning
work argues for richer, compactly-hashed hand features bootstrapped from
self-play, and that is the direction this measures the ground for -- BEFORE a
wider table gets built around features that may carry nothing.

THE QUESTION IS INCREMENTAL, not marginal. "Feature X correlates with the leaf"
is nearly meaningless when X also correlates with `hand_strength`; what decides
whether the abstraction should carry X is how much X adds ON TOP of the feature
already in it. So every candidate is scored by the R^2 it adds to a model that
already has `s_best`.

EVERY FEATURE HERE IS INFORMATION-LEGAL BY CONSTRUCTION. A seat holds thirteen
cards and may only NAME eleven -- the two outer pile bottoms are face down to
their owner as well as to the opponent -- so features read exactly
`playable + the middle pile bottom`, which is the set `bot.hand_strength`
itself uses. Reading the owner's hidden bottoms would build an abstraction the
rules do not permit, and this package has shipped that bug once already.

    PYTHONPATH=. python3 games/dissonance/tools/featlab.py [deals]
"""
from __future__ import annotations

import sys

from games.dissonance import engine as E, bot as B
from games.dissonance.tools import cfrlab as C


def visible(g, seat):
    """The cards this seat may name -- `hand_strength`'s own set."""
    return (E.playable(g, seat)
            + [p[0] for i, p in enumerate(g["piles"][seat])
               if len(p) == 2 and i == 1])


def features(g, seat):
    strengths = [B.hand_strength(g, seat, d) for d in range(E.NOTRUMP + 1)]
    order = sorted(strengths, reverse=True)
    best_d = max(range(len(strengths)), key=lambda d: strengths[d])
    cards = visible(g, seat)
    suits = [0] * 4
    for c in cards:
        suits[E.suit(c)] += 1
    ranks = [E.rank(c) for c in cards]
    top = E.NRANK - 1
    return {
        # The feature the abstraction already has.
        "s_best": order[0],
        # How CONCENTRATED the hand is. A hand strong in one denomination and a
        # hand strong in all five bucket identically today, and they are not the
        # same hand -- classic bans a denomination once a seat has named it, so
        # concentration is exactly the thing the forever-ban punishes.
        "s_gap": order[0] - order[1],
        "s_mean": sum(strengths) / len(strengths),
        # Flexibility: how many denominations are nearly as good as the best.
        "n_near": sum(1 for s in strengths if s >= order[0] - 1.0),
        # Shape, in the denomination the seat would actually name.
        "trump_len": suits[best_d] if best_d < 4 else max(suits),
        "longest": max(suits),
        "shortest": min(suits),
        "voids": sum(1 for n in suits if n == 0),
        # Quick tricks against long-suit tricks -- two ways to the same
        # `hand_strength` that play very differently at a high contract.
        "tops": sum(1 for r in ranks if r >= top - 1),
    }


def r2(xs, ys):
    """R^2 of an ordinary least-squares fit of ys on the columns of xs (plus an
    intercept), by normal equations with Gaussian elimination -- numpy is not a
    dependency of this package's shipped path and this is a handful of columns.
    """
    n = len(ys)
    k = len(xs[0])
    a = [[0.0] * (k + 2) for _ in range(k + 1)]
    rows = [[1.0] + list(x) for x in xs]
    for i in range(k + 1):
        for j in range(k + 1):
            a[i][j] = sum(r[i] * r[j] for r in rows)
        a[i][k + 1] = sum(r[i] * y for r, y in zip(rows, ys))
    for i in range(k + 1):
        p = max(range(i, k + 1), key=lambda q: abs(a[q][i]))
        if abs(a[p][i]) < 1e-12:
            return 0.0
        a[i], a[p] = a[p], a[i]
        for q in range(k + 1):
            if q == i:
                continue
            f = a[q][i] / a[i][i]
            for col in range(i, k + 2):
                a[q][col] -= f * a[i][col]
    beta = [a[i][k + 1] / a[i][i] for i in range(k + 1)]
    ybar = sum(ys) / n
    sse = sum((y - sum(b * v for b, v in zip(beta, r))) ** 2 for r, y in zip(rows, ys))
    sst = sum((y - ybar) ** 2 for y in ys)
    return 1.0 - sse / sst if sst > 0 else 0.0


def main(argv):
    n = int(argv[1]) if len(argv) > 1 else 400
    import random
    rows = []
    for i in range(n):
        seed = 900_000 + i
        g = E.new_game(["a", "b"], random.Random(seed), opener=0, mode="classic")
        for seat in (0, 1):
            f = features(g, seat)
            best_d = max(range(E.NOTRUMP + 1),
                         key=lambda d: B.hand_strength(g, seat, d))
            r = C.rpc({"resolve": {
                "hands": [sorted(h) for h in g["hands"]],
                "piles": [[list(x) for x in q] for q in g["piles"]],
                "trump": best_d, "leader": seat,
                "terms": {"declarer": seat, "target": 1, "make": 1,
                          "set_base": 1, "short": 1, "over": 1, "null": 20},
            }})
            f["pts"] = r.get("pts", 0)
            rows.append(f)
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{n} deals", flush=True)

    ys = [r["pts"] for r in rows]
    names = [k for k in rows[0] if k != "pts"]
    base = r2([[r["s_best"]] for r in rows], ys)
    print(f"\nfeatlab: {len(rows)} seat-hands, target = points guaranteed in the "
          f"seat's best denomination")
    print(f"\n  BASELINE  R^2 of s_best alone: {base:.4f}   "
          f"(the abstraction's whole private signal today)")
    print(f"\n  {'feature':>10}  {'R^2 alone':>10}  {'R^2 with s_best':>16}  {'INCREMENTAL':>12}")
    scored = []
    for nm in names:
        if nm == "s_best":
            continue
        alone = r2([[r[nm]] for r in rows], ys)
        both = r2([[r["s_best"], r[nm]] for r in rows], ys)
        scored.append((both - base, nm, alone, both))
    for inc, nm, alone, both in sorted(scored, reverse=True):
        print(f"  {nm:>10}  {alone:>10.4f}  {both:>16.4f}  {inc:>+12.4f}")
    allf = r2([[r[nm] for nm in names] for r in rows], ys)
    print(f"\n  ALL features together: {allf:.4f}  "
          f"(+{allf - base:.4f} over s_best alone)")
    print(f"\n  Read the INCREMENTAL column and nothing else: a feature that "
          f"correlates\n  with the leaf but not beyond `s_best` gives the "
          f"abstraction no new ability\n  to condition, it just splits the same "
          f"buckets thinner and starves the CFR.")


if __name__ == "__main__":
    main(sys.argv)
