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
import math
import os
import sys


def paired_rows(pats):
    """Every Double with BOTH its search sums and its ground truth.

    THE MARGIN CAN BE SWEPT EXACTLY OFF THIS, with no arena and no extra play.
    `double` carries the search's two sums and `dbltruth` carries what each
    branch is really worth, so for any candidate margin M the decision is
    `(on - off)/k > M` and its value is the recorded `gain` -- the same deals,
    the same rounds, paired by construction. An arena would re-measure exactly
    this through 18 points of per-deal payoff noise; this measures it with none.
    (`dblsweep` prices the DECISIONS this way already; what it lacks is the
    truth, so it can report rates but not what they were worth.)

    The two events are emitted back to back inside one flip, so they pair by
    position within the flip rather than by any id.
    """
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
            for flip in r.get("events", []):
                pending = None
                for e in flip:
                    if e[0] == "double" and len(e) >= 6:
                        pending = e
                    elif e[0] == "dbltruth" and len(e) >= 7 and pending is not None:
                        on, off = pending[3], pending[4]
                        if on is not None and off is not None:
                            out.append({"on": on, "off": off, "gain": e[4],
                                        "made": e[5], "level": e[6]})
                        pending = None
    return out


def sweep(rows, live, k=8):
    """What each candidate margin would have been worth, exactly.

    `live` IS MANDATORY AND IT IS THE TRAP `dblsweep` SET ONCE: the recorded
    sums already carry whatever margin was live during the run (`wire.rs` adds
    `margin * deals.len()` before returning them), so a raw threshold swept over
    them is a DELTA on top of the live value, not an absolute margin. Read as
    absolute it is wrong by exactly the live value, silently, with a perfectly
    plausible table.
    """
    print(f"\n=== MARGIN SWEEP, exact on {len(rows)} recorded doubles "
          f"(live margin {live:g}, column is ABSOLUTE) ===")
    print(f"  {'margin':>7}  {'dbl%':>6}  {'on FAIL':>8}  {'on MADE':>8}  "
          f"{'disc':>7}  {'value/round':>12}  {'vs live':>9}  {'SE':>6}  "
          f"{'t':>6}  {'moved':>6}")
    base = [r["gain"] if (r["on"] - r["off"]) / k > 0 else 0.0 for r in rows]
    best = None
    for m in (0, 4, 8, 12, 14, 16, 18, 20, 22, 24, 28, 32, 40):
        delta = m - live
        took = [r for r in rows if (r["on"] - r["off"]) / k > delta]
        n = len(rows)
        made = [r for r in rows if r["made"]]
        fail = [r for r in rows if not r["made"]]
        tm = sum(1 for r in made if (r["on"] - r["off"]) / k > delta)
        tf = sum(1 for r in fail if (r["on"] - r["off"]) / k > delta)
        val = sum(r["gain"] for r in took) / n if n else 0.0
        pm = 100.0 * tm / len(made) if made else 0.0
        pf = 100.0 * tf / len(fail) if fail else 0.0
        # PAIRED AGAINST THE LIVE MARGIN, WHICH IS THE ONLY HONEST ERROR BAR
        # HERE. Every candidate is scored on the SAME rounds -- the margin
        # changes which doubles are TAKEN and nothing else, since the auction
        # tree does not model the Double and the card play is untouched -- so
        # the difference is per-round paired and most rounds contribute exactly
        # zero. `moved` is how many of them the candidate actually re-decides;
        # the SE is a statement about those and nothing else.
        cand = [r["gain"] if (r["on"] - r["off"]) / k > delta else 0.0
                for r in rows]
        d = [c - b for c, b in zip(cand, base)]
        mu = sum(d) / n if n else 0.0
        var = sum((x - mu) ** 2 for x in d) / (n - 1) if n > 1 else 0.0
        se = math.sqrt(var / n) if n else 0.0
        moved = sum(1 for x in d if x != 0.0)
        t = mu / se if se else 0.0
        if best is None or val > best[1]:
            best = (m, val)
        print(f"  {m:>7}  {100.0*len(took)/n:>5.1f}%  {pf:>7.1f}%  {pm:>7.1f}%  "
              f"{pf-pm:>+6.1f}  {val:>+12.3f}  {mu:>+9.3f}  {se:>6.3f}  "
              f"{t:>+6.2f}  {moved:>6}")
    if best:
        cur = [r for r in rows if (r["on"] - r["off"]) / k > 0]
        curval = sum(r["gain"] for r in cur) / len(rows)
        print(f"\n  shipped ({live:g}) is worth {curval:+.3f}/round; "
              f"best swept is {best[0]} at {best[1]:+.3f}/round "
              f"({best[1]-curval:+.3f})")


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
    pr = paired_rows(argv[1:])
    if pr:
        sweep(pr, float(os.environ.get("DBL_LIVE", "12")))
    by = collections.defaultdict(list)
    for r in rows:
        by[r["tier"]].append(r)
    if len(by) > 1:
        for t, v in sorted(by.items()):
            report(v, f"tier {t}")


if __name__ == "__main__":
    main(sys.argv)
