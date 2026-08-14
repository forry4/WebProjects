"""Does the DETERMINIZER ignore the auction, and by how much?

The searcher resamples the declarer's unseen cards UNIFORMLY from the pool the
defender cannot see. But the declarer won an auction to level N, which is loud
evidence their hand is strong -- so if the sampling is unbiased, the declarer's
REAL holding should sit at a uniform percentile inside the resampled
distribution (mean 0.50). If the auction selects strong hands, it sits high, and
every sampled world hands the declarer a weaker hand than they really have.

That is exactly the shape that would make a defender's search believe contracts
fail more often than they do -- the poker "range" problem, and the thing
`auction.declarer`-style uniform determinization cannot see.

DELIBERATELY SOLVER-FREE. This is a measurement of the SAMPLING, not of the
search, so it uses the bot's own rank curve rather than an exact solve: it costs
no CPU worth speaking of and can run beside a live arena. A solve-based
confirmation is the follow-up, not the first question.

Run:  PYTHONPATH=. python -m games.dissonance.tools.beliefprobe 400
"""
import random
import statistics
import sys

from games.dissonance import bot as B
from games.dissonance import engine as E

#: How many uniform resamples per round the real hand is ranked against.
DRAWS = 200


def strength(cards, trump):
    """The bot's own rank curve over a WHOLE holding, trump counted double.

    Not a contract estimate and not meant to be one -- it only has to order two
    holdings the same way a bidder would, which is what a percentile needs.
    """
    tot = 0.0
    for c in cards:
        v = B._RANK_VALUE[E.rank(c)]
        tot += v * (2.0 if E.esuit(c, trump) == E.trump_class(trump) else 1.0)
    return tot


def to_double(seed):
    """A real round driven by the server bot to the moment the Double is live."""
    g = E.new_game(["a", "b"], random.Random(seed), opener=seed % 2, mode="classic")
    for _ in range(60):
        if g["phase"] == "double":
            return g
        if g["phase"] == "over":
            return None
        seat = E.turn_seat(g)
        if seat is None:
            return None
        kind, p = B.act(g, seat, random.Random(seed))
        if kind == "move":
            mv = p
        elif kind == "swap":
            mv = {"kind": "swap", "take": p.get("take"), "give": p.get("give")}
        elif kind == "play":
            mv = {"kind": "play", "card": p}
        elif p.get("pass"):
            mv = {"kind": "pass"}
        else:
            mv = {"kind": "bid", "level": p["level"], "denom": p["denom"]}
        E.apply_move(g, g["seats"][seat], mv)
    return None


def percentile(g, rng):
    """Where the declarer's REAL holding sits among uniform resamples of it."""
    decl = g["auction"]["declarer"]
    defd = 1 - decl
    trump = g["auction"]["denom"]

    # What the DEFENDER can see: their own 13, plus every pile top, plus both
    # middle-pile bottoms. Everything else is the pool the searcher samples.
    seen = set(g["hands"][defd])
    known_decl = []
    for owner in (0, 1):
        for i, p in enumerate(g["piles"][owner]):
            if not p:
                continue
            seen.add(p[-1])                       # tops are public
            if len(p) == 2 and i == 1:
                seen.add(p[0])                    # middle bottom is dealt face up
            if owner == decl:
                known_decl.append(p[-1])
                if len(p) == 2 and i == 1:
                    known_decl.append(p[0])
    pool = [c for c in range(E.deck_size("classic")) if c not in seen]

    # The declarer's real holding: their hand plus every card in their piles.
    real = list(g["hands"][decl])
    for p in g["piles"][decl]:
        real += list(p)
    # ...of which this many are unknown to the defender and get resampled.
    n_unknown = len(real) - len(known_decl)
    if n_unknown <= 0 or n_unknown > len(pool):
        return None
    base = strength(known_decl, trump)
    mine = strength(real, trump)
    below = 0
    for _ in range(DRAWS):
        draw = rng.sample(pool, n_unknown)
        if base + strength(draw, trump) < mine:
            below += 1
    return mine, below / DRAWS, g["auction"]["level"], len(pool), n_unknown


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    rng = random.Random(12345)
    rows = []
    for s in range(n):
        g = to_double(600_000 + s)
        if g is None:
            continue
        r = percentile(g, rng)
        if r:
            rows.append(r)
    if not rows:
        print("no rounds reached the double phase")
        return
    ps = [r[1] for r in rows]
    print(f"\n=== {len(rows)} rounds at the double phase, {DRAWS} uniform "
          f"resamples each ===")
    print(f"  the searcher resamples {rows[0][4]} of the declarer's 13 cards "
          f"from a pool of {rows[0][3]}\n")
    print(f"  MEAN PERCENTILE of the declarer's real holding: {statistics.mean(ps):.3f}")
    print(f"  (0.500 = the determinizer is unbiased; higher = every sampled "
          f"world is WEAKER\n   than the hand the declarer really has)")
    print(f"  median {statistics.median(ps):.3f}   "
          f"above 0.5: {100*sum(1 for p in ps if p > 0.5)/len(ps):.1f}% of rounds")

    print(f"\n  ...BY THE LEVEL THEY BID -- the bias should GROW with the bid, "
          f"since a\n  bigger contract is stronger evidence of a bigger hand:")
    print(f"    {'level':>6} {'n':>5} {'mean percentile':>17}")
    for lv in sorted({r[2] for r in rows}):
        sel = [r[1] for r in rows if r[2] == lv]
        if len(sel) < 4:
            continue
        bar = "#" * int(statistics.mean(sel) * 40)
        print(f"    {lv:>6} {len(sel):>5} {statistics.mean(sel):>16.3f}  {bar}")


if __name__ == "__main__":
    main()
