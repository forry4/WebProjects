"""Is dummy mode's auction a DECISION, or is bidding the ceiling always right?

The suspicion this answers: the contract curve (make N^2, set N + 5 x short)
was calibrated for CLASSIC, where contracts settle at levels 3-5. With a
dummy the declarer commands two of three hands and takes ~10-12 of a ~15
pool, so contracts settle at 9-12 -- and a QUADRATIC make against a LINEAR
set means the reward grows far faster than the risk. If that is right, the
expected payoff rises monotonically with the level and there is no such thing
as bidding too high, which would make the whole auction theatre.

Forces the declarer to a fixed level (the bot plays the cards as usual) and
reports the mean payoff per round at each rung.

    PYTHONPATH=. python -m games.dissonance.tools.dummy_auction_probe [rounds]
"""

from __future__ import annotations

import random
import sys

from games.dissonance import bot, engine as E


def forced_round(rng: random.Random, level: int, denom: int | None = None) -> dict:
    """One round in which the declarer is FORCED to `level`, cards played by
    the shipped policy on both sides."""
    g = E.new_game(["a", "b"], rng, opener=0, mode="dummy")
    # Seat 0 opens at the forced level in its best denomination; seat 1 passes,
    # so the level is the experiment's variable and nothing else is.
    d = denom
    if d is None:
        d = max(range(E.NOTRUMP + 1), key=lambda x: bot.hand_strength(g, 0, x))
    E.apply_bid(g, 0, level, d)
    E.apply_pass(g, 1)
    E.apply_double(g, 1, False)
    while g["phase"] == "play":
        seat = E.playing_seat(g)
        E.apply_play(g, seat, bot.choose_card(g, seat))
    return g


def sweep(n: int, seed: int = 17) -> None:
    print(f"\n== dummy: forced-level probe ({n} rounds a rung) ==")
    print(f"{'lvl':>4} {'made':>6} {'declarer EV':>12} {'mean pts':>9} "
          f"{'make pays':>10} {'set costs':>10}")
    evs = {}
    for level in range(1, E.MAX_LEVEL + 1):
        rng = random.Random(seed)
        tot = made = pts = 0
        makes, sets_ = [], []
        for _ in range(n):
            g = forced_round(rng, level)
            res = g["result"]
            decl = res["declarer"]
            # Signed for the DECLARER: what the round did to their score.
            v = res["scores"][decl] - res["scores"][1 - decl]
            tot += v
            pts += res["declarer_pts"]
            if res["made"] or res["null"]:
                made += 1
                makes.append(v)
            else:
                sets_.append(-v)
        evs[level] = tot / n
        mk = sum(makes) / len(makes) if makes else 0
        st = sum(sets_) / len(sets_) if sets_ else 0
        print(f"{level:>4} {100 * made / n:>5.0f}% {tot / n:>12.1f} "
              f"{pts / n:>9.1f} {mk:>10.1f} {st:>10.1f}")
    best = max(evs, key=lambda k: evs[k])
    print(f"\nbest rung: {best} (EV {evs[best]:+.1f})")
    rising = all(evs[l] <= evs[l + 1] + 1e-9 for l in range(1, E.MAX_LEVEL))
    print("monotonically rising:", rising,
          "-- if so the auction has no ceiling and bidding the top is free")


if __name__ == "__main__":
    sweep(int(sys.argv[1]) if len(sys.argv) > 1 else 150)
