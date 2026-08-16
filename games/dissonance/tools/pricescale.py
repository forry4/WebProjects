"""How far did a re-pricing move the payoff scale, and what does it re-tune?

THE COMPANION TO `dblsweep.py`. That one re-fits ONE constant exactly, off
recorded decisions; this one asks the cheaper prior question -- by how much did
the scale under every payoff-unit constant move at all -- so the expensive
sweeps can be pointed only at constants that actually left their band.

Run:  PYTHONPATH=. python -m games.dissonance.tools.pricescale

WHAT IT IS FOR. `DOUBLE_MARGIN` and `EXPERT_OPP_TEMP` are both in per-world
payoff points. The 2026-08-16 re-pricing broke the first and left the second
alone, and the reason is not their units:

  * a THRESHOLD sits in the TAIL of a distribution. It is hypersensitive --
    and to the distribution MOVING, not merely to the scale shrinking. The
    margin went from selective to useless while the payoff sd moved 10%,
    because the new prices changed how often doubling is correct at all
    (54.4% -> 23.1% of positions at margin 0).
  * a SCALE PARAMETER acts across the BULK. It degrades proportionally, so
    the ratios below are the whole story for it, and a band check settles it.

So: use this tool's ratios to clear scale parameters, and do NOT use them to
clear thresholds. A threshold needs its own recorded-decision sweep, because
the quantity it cuts can move much further than the price list does.

THE BASELINE IS TYPED IN ON PURPOSE. `NEW` comes off `engine.py` so it can
never go stale; `OLD` is a historical price list that by definition no longer
exists in the tree. Update `OLD` (and the date) at the next re-pricing.
"""
import statistics

from games.dissonance import engine as E

MODE = "classic"

#: The pre-2026-08-16 classic price list. History, so it is a literal.
OLD = dict(FLAT_MAKE=10, LIN_MAKE=0, SET_RATE=1, FLAT_SET=10, JUMP=3, SHORT=5)
#: Today's, off the engine -- never typed, so a re-price shows up here at once.
NEW = dict(FLAT_MAKE=E.FLAT_MAKE_BONUS[MODE], LIN_MAKE=E.LINEAR_MAKE_BONUS[MODE],
           SET_RATE=E.SET_LEVEL_RATE[MODE], FLAT_SET=E.FLAT_SET_PENALTY[MODE],
           JUMP=E.JUMP_SET_BONUS[MODE], SHORT=E.CLASSIC_SHORT_PENALTY)

#: The settled distributions each price list actually produced, with the Double
#: in the tree. The scale a constant sees is the scale of the games REACHED, so
#: a comparison on a common grid understates a re-price that also moved which
#: levels get played.
OLD_LEVELS, OLD_W = [3, 4, 5, 6], [0.08, 0.15, 0.60, 0.09]
NEW_LEVELS, NEW_W = [1, 2, 3, 4, 5, 6], [.05, .05, .08, .09, .55, .18]


def pay(c, level, made, delta, jump=1):
    """delta = overtricks when made, tricks short when set."""
    if made:
        return level * level + c["LIN_MAKE"] * level + c["FLAT_MAKE"] + delta
    return -(c["SET_RATE"] * level + c["FLAT_SET"] + c["JUMP"] * jump
             + c["SHORT"] * delta)


def scale(c, levels, wts, jump=1):
    vals, w = [], []
    for lv, pw in zip(levels, wts):
        for over in range(0, 4):
            vals.append(pay(c, lv, True, over, jump)); w.append(pw)
        for short in range(1, 4):
            vals.append(pay(c, lv, False, short, jump)); w.append(pw)
    m = sum(v * x for v, x in zip(vals, w)) / sum(w)
    var = sum(x * (v - m) ** 2 for v, x in zip(vals, w)) / sum(w)
    gaps = [pay(c, lv, True, 0, jump) - pay(c, lv, False, 1, jump) for lv in levels]
    return var ** 0.5, statistics.mean(gaps)


def main():
    print("PAYOFF SCALE -- the quantity every per-world payoff constant divides\n")
    print(f"  old {OLD}")
    print(f"  new {NEW}\n")

    print("  what DOUBLING adds per world (the Double's own scale):")
    print(f"    {'L':>3} {'set base o/n':>16} {'make o/n':>14}")
    for L in range(1, 7):
        so = OLD['SET_RATE'] * L + OLD['FLAT_SET'] + OLD['JUMP']
        sn = NEW['SET_RATE'] * L + NEW['FLAT_SET'] + NEW['JUMP']
        mo, mn = L * L + OLD['FLAT_MAKE'], L * L + NEW['FLAT_MAKE']
        print(f"    {L:>3} {so:>7} ->{sn:>4}      {mo:>5} ->{mn:>4}")

    sdc_o, gapc_o = scale(OLD, [3, 4, 5, 6], [.25] * 4)
    sdc_n, gapc_n = scale(NEW, [3, 4, 5, 6], [.25] * 4)
    print(f"\n  common grid (levels 3-6), price change ALONE:")
    print(f"    sd  {sdc_o:6.2f} -> {sdc_n:6.2f}   ratio {sdc_n/sdc_o:.3f}")
    print(f"    gap {gapc_o:6.2f} -> {gapc_n:6.2f}   ratio {gapc_n/gapc_o:.3f}")

    sd_o, gap_o = scale(OLD, OLD_LEVELS, OLD_W)
    sd_n, gap_n = scale(NEW, NEW_LEVELS, NEW_W)
    print(f"\n  AS PLAYED (each price list on its own settled distribution):")
    print(f"    sd  {sd_o:6.2f} -> {sd_n:6.2f}   ratio {sd_n/sd_o:.3f}")
    print(f"    gap {gap_o:6.2f} -> {gap_n:6.2f}   ratio {gap_n/gap_o:.3f}")

    print(f"\n  BAND CHECK for scale parameters -- rescale the fitted band and"
          f"\n  ask whether the shipped value is still inside it.")
    print(f"    EXPERT_OPP_TEMP, shipped 5.0, fitted band 5-12:")
    for lbl, r in (("by sd", sd_n / sd_o), ("by make/set gap", gap_n / gap_o)):
        lo, hi = 5 * r, 12 * r
        inside = "IN BAND" if lo <= 5.0 <= hi else "*** OUT OF BAND ***"
        print(f"      {lbl:16} -> {lo:5.1f}-{hi:5.1f}   {inside}")

    print(f"\n  Thresholds are NOT cleared by this tool -- run dblsweep.py.")


if __name__ == "__main__":
    main()
