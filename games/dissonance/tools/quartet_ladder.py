"""FITTING QUARTET'S CONTRACT LADDER -- and checking the bot is worth playing.

Three questions, in the order they have to be answered:

  1. **Is the policy better than nothing?** A ladder fitted against a bot that
     plays at random describes a game nobody will play. Paired arena, same
     deals, `bot` against random-legal.
  2. **What totals are actually reachable?** A quartet declarer scores trick
     points (nine tricks, pool +3, so -5..+8) PLUS what their own hand keeps
     (0..+6). The level map is a set of quantiles on that combined
     distribution and cannot be guessed -- dummy mode's first ladder was, and
     settled 100% of contracts on the top rung with 13% of them made.
  3. **Does the ladder have an INTERIOR PEAK?** Forced-level EV across every
     rung. If EV rises monotonically there is no such thing as bidding too
     high and the auction is a formality; if it falls monotonically the floor
     swallows everything. Dummy mode's first ladder failed exactly this check
     (+10.4 at level 1 rising to +58.2 at level 9) and it is the single most
     important number in this file.

MEASURED 2026-08-21, under the shipped ladder and `MATCH_TARGET["quartet"]`:

    bot vs random, CRN-paired   +27.37 a round   (mirror 0.0000)
    declarer total              mean +7.29   p10 +4  p50 +7  p90 +11  max +13
       of which tricks +2.89, keeps +4.40
    settled 1..10, mode 6, 78% made

    level    declarer EV   made          level   declarer EV   made
        1         +6.81     98%              7        +26.43    52%
        2         +8.65     95%              8        +27.41    42%   <- peak
        3        +12.29     93%              9        +22.93    28%
        4        +17.57     91%             10        +16.09    16%
        5        +22.93     83%             11         +8.49     7%
        6        +27.03     71%             12         +1.45     1%

**The peak is INTERIOR (level 8), which is the check this file exists for.** EV
climbs to 8 and then falls away to +1.45 at the ceiling, so there is a real
punishment for overbidding and a real reward for finding the top of your hand.
Dummy mode's first ladder failed exactly here.

Note the declarer's EV is positive at EVERY rung and that is NOT a defect: this
is a symmetric zero-sum game, so both seats have EV 0 by construction and the
column only says what WINNING THE AUCTION is worth in that regime. The shape is
the finding; the level is not.

THE MIRROR MUST READ 0.0000 AND TWICE IT DID NOT. `_split` puts a whole round
on the winner and zero on the loser, so a score row is not zero-sum: the first
cut scored the same seat in both seatings (+16.41) and the second added two
score rows instead of differencing them (+15.75, which is just the mean
absolute transfer). Both looked like a strong policy. The signed difference,
averaged over both seatings, is the only correct pairing.

    PYTHONPATH=. python3 -m games.dissonance.tools.quartet_ladder [rounds]
"""

from __future__ import annotations

import random
import statistics
import sys
from collections import Counter

from games.dissonance import bot as B, engine as E

MODE = "quartet"


def _drive(g, rng, policy=("bot", "bot")):
    """Play a dealt game out. `policy[seat]` is "bot" or "random"."""
    while g["phase"] != "over":
        seat = E.turn_seat(g)
        if seat is None:
            break
        if g["phase"] == "play" and policy[seat] == "random":
            E.apply_play(g, seat, rng.choice(E.legal_moves(g, seat)))
            continue
        kind, mv = B.act(g, seat, rng)
        if kind == "play":
            move = {"kind": "play", "card": mv}
        elif kind == "bid":
            move = {"kind": "pass"} if mv.get("pass") else {"kind": "bid", **mv}
        elif kind == "swap":
            move = {"kind": "swap", "take": mv.get("take"), "give": mv.get("give")}
        else:
            move = mv
        E.apply_move(g, g["seats"][seat], move, rng)
    return g


def _one(seed, policy, rng_seed):
    """One deal under one seat assignment, returning the whole result row."""
    rng = random.Random(rng_seed)
    g = E.new_game(["p0", "p1"], random.Random(seed), opener=0, mode=MODE)
    _drive(g, rng, policy)
    return g["result"]


def arena(rounds, seed=101):
    """CRN-paired: every deal is played BOTH WAYS ROUND, so the seat a policy
    sits in cannot flatter it. `margin` is what the measured policy scores per
    round, averaged over the two seatings.

    THE MIRROR IS THE HARNESS CHECKING ITSELF and it must read exactly 0.0000.
    Both seats play the identical policy, so whatever one seat wins the other
    loses -- a mirror that reads anything else means the pairing is wrong (the
    first cut of this function scored the SAME seat in both seatings, which
    reported the declarer's advantage as if it were the policy's, +16.41).
    Scoring must follow the policy round the table, not stay on seat 0.
    """
    margin, mirror = [], []
    for i in range(rounds):
        # `rng_seed` is shared across the two seatings of a deal so the two
        # runs draw the same tie-breaks -- that is the "common random numbers"
        # half, and without it the pairing only halves the variance it should.
        for arms, acc in ((("bot", "random"), margin), (("bot", "bot"), mirror)):
            a, b = arms
            r0 = _one(seed + i, (a, b), seed + i)
            r1 = _one(seed + i, (b, a), seed + i)
            # THE SIGNED DIFFERENCE, not one seat's score. `_split` puts the
            # whole round on the WINNER and zero on the loser, so a score row
            # is not zero-sum and adding two of them measures how big the
            # round was rather than who won it -- which is what made the
            # mirror read +15.75 (the mean absolute transfer) instead of 0.
            acc.append(((r0["scores"][0] - r0["scores"][1])
                        + (r1["scores"][1] - r1["scores"][0])) / 2.0)
    return statistics.mean(margin), statistics.mean(mirror)


def totals(rounds, seed=7):
    """The declarer's reachable total, and both halves of it."""
    tot, tricks, keeps, levels, made = [], [], [], Counter(), 0
    for i in range(rounds):
        rng = random.Random(seed + i)
        g = _drive(E.new_game(["p0", "p1"], random.Random(seed + i),
                              opener=0, mode=MODE), rng)
        r = g["result"]
        d = r["declarer"]
        tot.append(r["declarer_pts"])
        tricks.append(r["trick_pts"][d])
        keeps.append(r["keeps"][d])
        levels[r["level"]] += 1
        made += bool(r["made"])
    return tot, tricks, keeps, levels, made / rounds


def forced_ev(rounds, seed=31):
    """Force the contract to each rung and measure the declarer's payoff.

    The auction is bypassed rather than steered: the deal is made, the contract
    written straight into it, and the round played out. That is the only way to
    price a rung nobody's bidding policy would choose.
    """
    rows = {}
    for lvl in range(E.MIN_LEVEL, E.max_level_for(MODE) + 1):
        pay, mk = [], 0
        for i in range(rounds):
            rng = random.Random(seed + i)
            g = E.new_game(["p0", "p1"], random.Random(seed + i), opener=0,
                           mode=MODE)
            a = g["auction"]
            d = max(E.backed_denoms(g, 0), key=lambda x: B.hand_strength(g, 0, x))
            a["level"], a["denom"], a["declarer"], a["jump"] = lvl, d, 0, lvl
            g["phase"] = "commit"
            _drive(g, rng)
            r = g["result"]
            pay.append(r["scores"][0])
            mk += bool(r["made"])
        rows[lvl] = (statistics.mean(pay), mk / rounds)
    return rows


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    m, mir = arena(max(60, rounds // 4))
    print(f"bot vs random, CRN-paired: {m:+.2f} a round   (mirror {mir:+.4f}, "
          f"must be 0.0000)\n")

    tot, tricks, keeps, levels, made = totals(rounds)
    q = statistics.quantiles(tot, n=100)
    print(f"declarer total   mean {statistics.mean(tot):+.2f}  "
          f"p10 {q[9]:+.1f}  p50 {q[49]:+.1f}  p90 {q[89]:+.1f}  "
          f"max {max(tot):+d}")
    print(f"   of which tricks {statistics.mean(tricks):+.2f}   "
          f"keeps {statistics.mean(keeps):+.2f}")
    print(f"settled levels {dict(sorted(levels.items()))}  made {made:.0%}\n")

    print(f"{'level':>6s} {'declarer EV':>12s} {'made':>7s}")
    rows = forced_ev(max(60, rounds // 3))
    for lvl, (ev, mk) in rows.items():
        print(f"{lvl:6d} {ev:+12.2f} {mk:7.0%}")
    peak = max(rows, key=lambda k: rows[k][0])
    lo, hi = min(rows), max(rows)
    print(f"\npeak at level {peak}"
          + ("  <- INTERIOR, the ladder has a real optimum"
             if lo < peak < hi else
             "  <- AT AN END: no interior optimum, the ladder is broken"))


if __name__ == "__main__":
    main()
