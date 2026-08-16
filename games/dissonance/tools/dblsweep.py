"""Sweep the doubling threshold OFFLINE, off one run's recorded decisions.

`main.DOUBLE_MARGIN` is the number this prices. The search's two sums at each
double are recorded by `auction_arena.py` under `ARENA_CKPT`, and the decision
under a margin M is `(on - off) / k > M`. Neither sum depends on M, so ONE
recorded run prices EVERY threshold exactly -- the `swaplab` method applied to
the Double. That is the whole point of the tool: a margin sweep by re-running
the arena per candidate is hours of play per value and comes back inside its own
error bars anyway.

Run:  PYTHONPATH=. python -m games.dissonance.tools.dblsweep --live 20 'dbl.jsonl*'
      (shard globs are fine -- every file matching every pattern is pooled)

`--live M` IS MANDATORY AND IT IS THE TRAP THIS TOOL SET ONCE. The recorded
sums ALREADY carry whatever `DOUBLE_MARGIN` was live during the run --
`wire.rs` does `sums[esc] += margin * deals.len()` and the arena records what
`wire.rs` returned. So a raw threshold swept over those sums is a DELTA on top
of the live margin, not an absolute margin. Read as absolute it is wrong by
exactly the live value, silently, with a perfectly plausible table.

That is not hypothetical: on 2026-08-16 a sweep of data recorded at live 20 was
read as absolute, so column 4 (really margin 24) was shipped as `4`. The
measured consequence was doubling at 49.4% against the 22.7% the old value
gave. Verified both ways since -- column 0 reproduces the directly measured
doubling rate of its own dataset (23.1% vs 22.7% at live 20; 47.2% vs 49.4% at
live 4), which is the check that pins the semantics.

WHICH COLUMNS DECIDE. The rate columns (`dbl%`, `on FAIL`, `on MADE`, `disc`)
are DECISIONS: each round's edge is recorded, so every margin's choice on it is
exact and the only sampling error is which rounds were played. The payoff
columns are not -- at the sample sizes this is run at they carry about +-10 on a
mean of 10, so they inform and do not choose.

ONE APPROXIMATION, stated: a round the margin UN-doubles is re-priced under the
undoubled terms with the play it actually got. The declarer would have played a
little differently without the Double on the table, so the un-doubled payoffs
are indicative rather than exact. It cannot affect the RATE columns.
"""
import glob
import json
import math
import os
import statistics
import sys

# OFF THE ENGINE, NOT TYPED OUT. These were literals -- 10, 5, 1, 3 -- fitted to
# the pre-2026-08-16 prices, and the re-pricing moved three of them plus added a
# level RATE the literals could not express at all (`set = 2L + 2`, not `L + 10`).
# A sweep run against stale constants prices thresholds for a game nobody plays,
# and every number it prints looks perfectly reasonable.
from games.dissonance import engine as _E

MODE = "classic"
FLAT_SET = _E.FLAT_SET_PENALTY[MODE]
SET_RATE = _E.SET_LEVEL_RATE[MODE]
SHORT = _E.CLASSIC_SHORT_PENALTY
RAMP = _E.DOUBLE_RAMP
JUMP = _E.JUMP_SET_BONUS[MODE]
NULL = _E.NULL_MAKE
FLAT_MAKE = _E.FLAT_MAKE_BONUS[MODE]
LIN_MAKE = _E.LINEAR_MAKE_BONUS[MODE]
K = 8


def rounds(pats):
    """One row per round: the settled contract, the outcome, and the double."""
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
            # BOTH FLIPS. A checkpoint line holds one deal's two flips (same
            # cards, seats swapped) and this read only `events[0]` for its
            # first month, halving every sample it ever reported.
            for evs in r.get("events", []):
                # FILTER BY TIER. In an asymmetric arm the two seats run
                # different knobs, so a double event belongs to whichever tier
                # was DEFENDING. Pooling would average the arm with its control.
                want = os.environ.get("SWEEP_TIER")
                dbl = next((e for e in evs if e[0] == "double" and len(e) >= 5
                            and (want is None or e[1] == want)), None)
                st = next((e for e in evs if e[0] == "settled" and len(e) >= 12),
                          None)
                if st is None or dbl is None or dbl[3] is None:
                    continue
                lv = st[11]
                out.append({"N": st[2], "outcome": st[3], "doubled": bool(st[4]),
                            "price": st[8], "payoff": st[10], "m": r.get("m"),
                            "j": lv[-1] - (lv[-2] if len(lv) > 1 else 0),
                            "edge": (dbl[3] - dbl[4]) / K})
    return out


def base_set(N, j, D, jump_doubled=True):
    stake, bonus = SET_RATE * N + FLAT_SET, JUMP * j
    if D <= 1:
        return stake + bonus
    return (stake + bonus) * D if jump_doubled else stake * D + bonus


def invert(r, jd=True):
    """Recover the overtricks / tricks-short the recorded payoff implies.

    The arena records the payoff, not its decomposition, and re-pricing a round
    under the other doubling needs the decomposition. Solving for it rather than
    logging it keeps the arena's own output byte-compatible -- and it is checked:
    a row that does not invert is DROPPED, so a scoring change this file has not
    caught up with shows as a collapsing `n` and not as quietly wrong prices.
    """
    N, j, D = r["N"], r["j"], 2 if r["doubled"] else 1
    P = r["payoff"]
    if r["outcome"] == "null":
        return P == NULL
    if r["outcome"] == "set":
        ramp = RAMP if D > 1 else 0
        for s in range(1, N + 1):
            if -(base_set(N, j, D, jd) + SHORT * s + ramp * s * (s + 1) // 2) == P:
                r["s"] = s
                return True
        return False
    for over in range(0, 13):
        if D * (N * N + LIN_MAKE * N + FLAT_MAKE) + D * over == P:
            r["over"] = over
            return True
    return False


def pay(r, D, jd=True):
    if r["outcome"] == "null":
        return NULL
    if r["outcome"] == "made":
        return D * (r["N"] ** 2 + LIN_MAKE * r["N"] + FLAT_MAKE) + D * r["over"]
    ramp = RAMP if D > 1 else 0
    return -(base_set(r["N"], r["j"], D, jd) + SHORT * r["s"]
             + ramp * r["s"] * (r["s"] + 1) // 2)


def se(x):
    return 1.96 * statistics.stdev(x) / math.sqrt(len(x)) if len(x) > 1 else 0.0


def main():
    jd = "--jump-outside" not in sys.argv
    if "--live" not in sys.argv:
        print("REFUSING TO GUESS. Pass --live <M>: the DOUBLE_MARGIN that was "
              "live when\nthis data was recorded (0 if none). The recorded sums "
              "already carry it, so\nwithout it every row below is wrong by "
              "exactly that value -- see the header.")
        sys.exit(2)
    live = float(sys.argv[sys.argv.index("--live") + 1])
    skip = {"--live", str(sys.argv[sys.argv.index("--live") + 1])}
    pats = [a for a in sys.argv[1:] if not a.startswith("--") and a not in skip]
    rs = [r for r in rounds(pats) if invert(r, jd)]
    if not rs:
        print("no rounds with a recorded double decision yet")
        return
    fail = [r for r in rs if r["outcome"] == "set"]
    print(f"n={len(rs)} rounds with a recorded double  "
          f"(jump {'inside' if jd else 'OUTSIDE'} the x2)")
    print(f"recorded at LIVE margin {live:g} -- the `margin` column below is "
          f"ABSOLUTE\n(live + the swept delta), so the {live:g} row reproduces "
          f"this run's own behaviour.")
    print(f"oracle floor = the set rate = {100*len(fail)/len(rs):.1f}%\n")
    print(f"{'margin':>7} {'dbl%':>6} {'on FAIL':>8} {'on MADE':>8} {'disc':>7} "
          f"{'prec':>6} {'declarer EV':>16} {'defender gain':>15}")
    for M_abs in (0, 2, 4, 6, 8, 10, 12, 15, 20, 24, 28, 32, 36, 40):
        M = M_abs - live          # the delta this data can actually express
        if M < 0:
            continue              # below the live margin is not recoverable
        dec = [r["edge"] > M for r in rs]
        # A round the margin un-doubles is re-priced undoubled (same play).
        pays = [(r["payoff"] if d == r["doubled"] else pay(r, 2 if d else 1, jd))
                for r, d in zip(rs, dec)]
        gain = [(-(p - pay(r, 1, jd)) if d else 0.0)
                for r, d, p in zip(rs, dec, pays)]
        nd = sum(dec)
        onf = sum(1 for r, d in zip(rs, dec) if d and r["outcome"] != "made")
        onm = sum(1 for r, d in zip(rs, dec) if d and r["outcome"] == "made")
        nf = sum(1 for r in rs if r["outcome"] != "made")
        nm = len(rs) - nf
        disc = 100 * onf / max(1, nf) - 100 * onm / max(1, nm)
        print(f"{M_abs:>7} {100*nd/len(rs):>5.1f}% {100*onf/max(1,nf):>7.1f}% "
              f"{100*onm/max(1,nm):>7.1f}% {disc:>+6.1f} "
              f"{100*onf/max(1,nd):>5.1f}% "
              f"{statistics.mean(pays):>+8.2f} +-{se(pays):5.2f} "
              f"{statistics.mean(gain):>+8.2f}")
    print("\n  declarer EV is signed for the DECLARER (higher = the declarer keeps more);")
    print("  defender gain is what the doubles taken are worth to the defender.")

    # where the marginal doubles are
    print(f"\n  edge distribution over the doubles taken at margin 0 "
          f"(per-world payoff points):")
    e = sorted(r["edge"] for r in rs if r["edge"] > 0)
    if e:
        qs = [e[int(q * (len(e) - 1))] for q in (0.1, 0.25, 0.5, 0.75, 0.9)]
        print("    p10 %.1f   p25 %.1f   median %.1f   p75 %.1f   p90 %.1f"
              % tuple(qs))

    # IS IT NOISE OR BIAS? THE DECISIVE TABLE.
    #
    # A margin is the right instrument for NOISE: if the wrong doubles cluster
    # near edge 0, they are a selection effect and a threshold removes them. If
    # a contract the search was CONFIDENT about still makes at a healthy rate,
    # the estimate is BIASED and no threshold fixes it -- the determinizer is
    # then the thing to look at, since it resamples the declarer's hand
    # uniformly while the auction is loud evidence that hand is strong.
    print(f"\n  CALIBRATION: how often the contract actually MADE, by how "
          f"confident the search was")
    print(f"    {'edge/world':>14} {'n':>5} {'really made':>13}  "
          f"{'(break-even is ~40%)':>22}")
    buckets = [(0, 5), (5, 10), (10, 20), (20, 30), (30, 1e9)]
    for lo, hi in buckets:
        sel = [r for r in rs if lo < r["edge"] <= hi]
        if not sel:
            continue
        made = 100 * sum(1 for r in sel if r["outcome"] == "made") / len(sel)
        bar = "#" * int(made / 4)
        print(f"    {lo:>6}-{hi if hi < 1e9 else '+':<7} {len(sel):>5} "
              f"{made:>12.1f}%  {bar}")


if __name__ == "__main__":
    main()
