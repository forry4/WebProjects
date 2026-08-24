"""Two candidate fixes for dummy mode, measured on the same footing.

`dummy_auction_design` found the auction has nothing to be about: the declarer
banks 69% of the pool just for holding the dummy, and the points they take
correlate +0.06 with the hand they can see -- and +0.06 with a CHEATING count
of the cards really in their two hands. Two suspects:

  * THE DUMMY OVERSHOOTS. Two of three hands plus the lead is so much control
    that the cards stop mattering. `DUMMY_COMMAND = "leader"` hands the third
    hand to whoever won the last trick instead.
  * THE CARDS ARE TOO ALIKE. Every card is -1 or +2, sixteen of each, so the
    deck carries almost no information per card -- and since both values are
    2 mod 3, three of them always sum to a multiple of 3, which is separately
    why two thirds of the contract ladder are duplicate rungs.

THE NUMBER THAT DECIDES IT is `corr`: how well what a bidder can SEE predicts
what they will TAKE. Below ~0.2 an auction is a lottery however its rungs are
priced. `share` is the declarer's slice of the pool -- 50% would mean the
dummy confers nothing, 69% is what the shipped rule measures.

    PYTHONPATH=. python -m games.dissonance.tools.dummy_matrix [rounds]
"""

from __future__ import annotations

import copy
import random
import statistics
import sys
from math import gcd

from games.dissonance import bot, engine as E

#: Candidate value tables, indexed by `E.rank` -- STRENGTH order, and the wide
#: deck's 5 and 6 lead every row. They are 0 in the shipped table (a safe
#: discard, and what breaks the mod-3 granularity); a candidate that wants them
#: to carry worth says so in its own first two entries.
TABLES = {
    # The shipped table: two values, sixteen cards each.
    "shipped  0/-1/+2": [0, 0, -1, -1, 2, 2, 2, 2, -1, -1],
    # A zero in the middle of the low end -- the cheapest possible break of the
    # mod-3 granularity, and it gives the game a genuinely SAFE discard.
    "low-sting -1 all": [-1, -1, -1, -1, 2, 2, 2, 2, -1, -1],
    # Spread, still anti-aligned with rank (the winners are the liabilities).
    "spread   anti": [0, -1, -2, -1, 1, 2, 3, 4, -3, -4],
    # Real Skat's shape: value ALIGNED with trick-winning power, so taking a
    # trick with your ace is what captures the points.
    "skatlike aligned": [0, 0, 0, 0, 0, 10, 2, 3, 4, 11],
    # Aligned but gentler, and signed so ducking still matters.
    "aligned  gentle": [-2, -1, -1, -1, 0, 3, 1, 2, 4, 5],
    # MONOTONIC and signed: worth rises with rank, and the two lowest cards are
    # still small liabilities, so dumping a 7 on someone's trick keeps stinging
    # and a low card is still a tool. No Skat quirk (a ten worth more than a
    # queen), which is one fewer thing a player has to be told.
    "aligned  monotonic": [-3, -2, -1, -1, 0, 1, 2, 3, 4, 5],
}


def granularity(vals, width):
    sums = set()
    def rec(n, acc):
        if n == 0:
            sums.add(acc); return
        for v in set(vals):
            rec(n - 1, acc + v)
    rec(width, 0)
    g = 0
    for s in sums:
        g = gcd(g, abs(s))
    return g or 1


def visible(g, q):
    return E.playable(g, q) + [p[0] for i, p in enumerate(g["piles"][q])
                               if len(p) == 2 and i == 1]


def run(rounds: int, table, command: str, seed: int = 61):
    """Play `rounds` under a value table and a dummy-command rule."""
    # The deck total used to be a module CONSTANT computed from the table at
    # import, so patching the values without it reported the share of a pool the
    # deck no longer had (it read 12.88 for a table whose real pool is ~110).
    # `E.card_pool_for` computes it from `CARD_VALUES` on every call now, so
    # patching the table is enough -- the trap is documented rather than
    # deleted, because it is the reason that function is not a constant.
    old_vals, old_cmd = list(E.CARD_VALUES), E.DUMMY_COMMAND
    E.CARD_VALUES[:] = table
    E.DUMMY_COMMAND = command
    try:
        rng = random.Random(seed)
        strengths, pts, shares = [], [], []
        for _ in range(rounds):
            g0 = E.new_game(["a", "b"], rng, opener=0, mode="dummy")
            st = max(bot.hand_strength(g0, 0, d) for d in range(E.NOTRUMP + 1))
            d = max(range(E.NOTRUMP + 1), key=lambda x: bot.hand_strength(g0, 0, x))
            g = copy.deepcopy(g0)
            E.apply_bid(g, 0, 1, d)
            E.apply_pass(g, 1)
            E.apply_double(g, 1, False)
            while g["phase"] == "play":
                s = E.playing_seat(g)
                E.apply_play(g, s, bot.choose_card(g, s))
            p = g["result"]["declarer_pts"]
            pool = E.played_pool(g)
            strengths.append(st)
            pts.append(p)
            if pool:
                shares.append(p / pool)
        sx, sy = statistics.pstdev(strengths), statistics.pstdev(pts)
        mx, my = statistics.mean(strengths), statistics.mean(pts)
        r = 0.0
        if sx and sy:
            r = sum((a - mx) * (b - my) for a, b in zip(strengths, pts)) \
                / len(pts) / (sx * sy)
        return {"corr": r, "sd": sy, "share": statistics.mean(shares),
                "mean": my, "levels": len(set(pts)),
                "pool": E.card_pool_for("dummy")}
    finally:
        E.CARD_VALUES[:] = old_vals
        E.DUMMY_COMMAND = old_cmd


def main(n: int) -> None:
    print(f"\n== dummy mode: two fixes, same footing ({n} rounds a cell) ==")
    print("corr  = does what a bidder SEES predict what they TAKE (want > ~0.2)")
    print("share = the declarer's slice of the pool (0.50 = the dummy is worth nothing)")
    print("gran  = every trick is a multiple of this (3 means 2/3 of the ladder is duplicates)")
    print(f"\n{'value table':>20} {'cmd':>9} {'gran':>5} {'deck':>5} "
          f"{'corr':>7} {'share':>7} {'sd':>6} {'totals':>7}")
    for name, table in TABLES.items():
        gr = granularity(table, 3)
        for command in ("declarer", "leader"):
            m = run(n, table, command)
            print(f"{name:>20} {command:>9} {gr:>5} {m['pool']:>5} "
                  f"{m['corr']:>+7.3f} {m['share']:>7.2f} {m['sd']:>6.2f} "
                  f"{m['levels']:>7}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 250)
