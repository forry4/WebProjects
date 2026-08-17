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
#: A DOUBLED shortfall may charge its own rate (`DOUBLED_SHORT_PENALTY`, 2026-08-16).
#: Missing this made `invert` fail on exactly the doubled SET rows and drop them,
#: which left the doubled sample all-makes and printed "on FAIL 0.0%" with a
#: NEGATIVE discrimination -- a clean-looking table that was pure selection.
DSHORT = _E.DOUBLED_SHORT_PENALTY.get(MODE, SHORT)
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


def terms_of(r, D):
    """The engine's OWN terms for this round at doubling `D`.

    OFF THE ENGINE, NOT RE-DERIVED. This file used to rebuild the set base from
    copied constants, and that broke three separate times in one day -- the
    2026-08-16 re-pricing, then `DOUBLED_SHORT_PENALTY`, then the base/jump
    multipliers -- each time by silently failing to invert the DOUBLED rows and
    dropping exactly the sample the table was about. `_terms_for` is the function
    the game itself scores with, so there is nothing left to keep in sync.
    """
    return _E._terms_for(MODE, 0, r["N"], jump=r["j"], doubling=D)


def invert(r, jd=True):
    """Recover the round's final POINTS from its recorded payoff.

    Points are all the re-pricing needs -- `E.payoff` turns points plus terms
    into a number, so the other doubling is one more call rather than a
    decomposition this file has to model. A row that does not invert is DROPPED
    and REPORTED, which is the loud version of the failure above.

    THE ARENA'S `outcome` IS NOT THE PLAYED RESULT: it is a double-dummy label,
    so "null" means the optimal line went through Null whether or not the bots
    found it. It is used here only to break the one genuine ambiguity (a made
    contract that happens to pay exactly `NULL`), never as the answer.
    """
    D = 2 if r["doubled"] else 1
    t = terms_of(r, D)
    P = r["payoff"]
    hits = [pts for pts in range(-13, 14) if _E.payoff(t, pts, True) == P]
    if hits and not (P == NULL and r["outcome"] == "null"):
        r["pts"], r["scored"] = hits[0], True
        r["kind"] = "made" if hits[0] >= t["target"] else "set"
        return True
    if P == NULL:
        r["pts"], r["scored"], r["kind"] = 0, False, "null"
        return True
    return False


def pay(r, D, jd=True):
    """Re-price the round under doubling `D`, with the play it actually got."""
    return _E.payoff(terms_of(r, D), r["pts"], r["scored"])


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
    all_rows = rounds(pats)
    rs = [r for r in all_rows if invert(r, jd)]
    dropped = len(all_rows) - len(rs)
    if dropped:
        # LOUD, because a silent drop is selection. `invert` recovers the
        # overtricks/shortfall the recorded payoff implies, and it can only fail
        # if this tool's price list disagrees with the one the run was played
        # under -- in which case the rows it drops are the ones the mismatch
        # touches, and every column below is a biased subsample.
        print(f"*** {dropped} of {len(all_rows)} rounds did NOT invert and were "
              f"DROPPED.\n*** That is a PRICE-LIST MISMATCH, not noise: this tool's "
              f"constants disagree\n*** with the run's. Do not read the table until "
              f"it is 0.")
    if not rs:
        print("no rounds with a recorded double decision yet")
        return
    fail = [r for r in rs if r["kind"] == "set"]
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
        # ONLY A SET PAYS THE DOUBLE. Null pays the DECLARER +20, so the old
        # `outcome != "made"` test credited the bet for rounds where the
        # declarer escaped and the defender collected nothing.
        onf = sum(1 for r, d in zip(rs, dec) if d and r["kind"] == "set")
        onm = sum(1 for r, d in zip(rs, dec) if d and r["kind"] != "set")
        nf = sum(1 for r in rs if r["kind"] == "set")
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
        made = 100 * sum(1 for r in sel if r["kind"] != "set") / len(sel)
        bar = "#" * int(made / 4)
        print(f"    {lo:>6}-{hi if hi < 1e9 else '+':<7} {len(sel):>5} "
              f"{made:>12.1f}%  {bar}")


if __name__ == "__main__":
    main()
