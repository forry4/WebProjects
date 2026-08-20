"""The Double, scored against ground truth, from EXPERT-BID positions.

THE FOLLOW-UP. `dblprobe` measured the shipped Double at **-3.73 payoff a
round** against **+2.84** available -- the doubles it takes cost the defender
more than they win -- and it barely discriminates: 30.7% of contracts that MADE
were doubled against 34.2% of contracts that FAILED. But it drives its rounds
with the SERVER bot, and this package's own rule is that **which bot did the
bidding IS the distribution**. Expert buys different contracts at different
levels, so the number has to be re-taken on Expert-bid ones before anything is
re-priced on it.

`auction_arena.py ... ARENA_DBL=1` records a `dbltruth` event at every Double of
a real arena run: what the tier chose, what it should have chosen, and what the
choice was worth, all against an exact double-dummy resolve of both branches.
This pools them.

    PYTHONPATH=. python3 games/dissonance/tools/dblreport.py <ckpt> [<ckpt> ...]
"""
from __future__ import annotations

import collections
import glob
import json
import sys


def rows_from(pats):
    out = []
    for p in sorted(x for pat in pats for x in glob.glob(pat)):
        for line in open(p):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            # BOTH FLIPS. A deal is played twice with the seats swapped, and each
            # flip is its own Double decision by its own tier -- taking only
            # `events[0]` would halve the sample and silently drop every
            # decision the other seating made.
            for flip in r.get("events", []):
                for e in flip:
                    if e[0] == "dbltruth" and len(e) >= 7:
                        out.append({"tier": e[1], "chose": e[2], "should": e[3],
                                    "gain": e[4], "made": e[5], "level": e[6]})
    return out


def report(rows, label):
    m = len(rows)
    if not m:
        print(f"  {label}: no doubles recorded")
        return
    chose = sum(1 for r in rows if r["chose"])
    should = sum(1 for r in rows if r["should"])
    agree = sum(1 for r in rows if r["chose"] == r["should"])
    tp = sum(1 for r in rows if r["chose"] and r["should"])
    fp = sum(1 for r in rows if r["chose"] and not r["should"])
    fn = sum(1 for r in rows if not r["chose"] and r["should"])
    got = sum(r["gain"] for r in rows if r["chose"]) / m
    best = sum(max(0.0, r["gain"]) for r in rows if r["should"]) / m
    made = [r for r in rows if r["made"]]
    fail = [r for r in rows if not r["made"]]
    dm = sum(1 for r in made if r["chose"])
    df = sum(1 for r in fail if r["chose"])
    print(f"\n=== {label}: {m} doubles ===")
    print(f"  doubles taken             {chose:4d} ({100*chose/m:.1f}%)")
    print(f"  doubles that SHOULD be    {should:4d} ({100*should/m:.1f}%)")
    print(f"  agreement with truth      {agree:4d} ({100*agree/m:.1f}%)")
    print(f"  hit / false alarm / miss  {tp} / {fp} / {fn}")
    print(f"  value captured            {got:+.2f} per round of an available {best:+.2f}")
    if made:
        print(f"  doubles contracts that MADE   {dm}/{len(made)} = {100*dm/len(made):.1f}%")
    if fail:
        print(f"  doubles contracts that FAILED {df}/{len(fail)} = {100*df/len(fail):.1f}%")
    if made and fail:
        # THE DISCRIMINATION IS THE POINT. A doubler that cannot separate these
        # two is not doubling on information, whatever its rate.
        print(f"  DISCRIMINATION (failed - made) {100*df/len(fail) - 100*dm/len(made):+.1f} points")


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    rows = rows_from(argv[1:])
    if not rows:
        raise SystemExit("no `dbltruth` events -- was the run made with ARENA_DBL=1?")
    report(rows, "ALL TIERS POOLED")
    by = collections.defaultdict(list)
    for r in rows:
        by[r["tier"]].append(r)
    if len(by) > 1:
        for t, v in sorted(by.items()):
            report(v, f"tier {t}")


if __name__ == "__main__":
    main(sys.argv)
