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
import math
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
    samples = [base + strength(rng.sample(pool, n_unknown), trump)
               for _ in range(DRAWS)]
    below = sum(1 for s in samples if s < mine)
    return (mine, below / DRAWS, g["auction"]["level"], len(pool), n_unknown,
            samples)


def tilted(mine, samples, beta):
    """Where the real holding sits once the sample is EXPONENTIALLY TILTED.

    The fix is importance sampling: give a candidate world weight `exp(beta x
    strength)`, so strong hands -- the ones consistent with having won the
    auction -- are drawn more often. `beta = 0` is uniform, i.e. today.

    Computed by REWEIGHTING the draws already taken rather than by resampling
    them, which is the same quantity exactly and costs nothing, so a whole
    grid of beta is one pass.
    """
    hi = max(samples)
    num = tot = 0.0
    for s in samples:
        w = math.exp(beta * (s - hi))       # shifted for overflow, cancels out
        tot += w
        if s < mine:
            num += w
    return num / tot if tot else 0.5


def from_arena(pats):
    """Positions recorded at the double by `auction_arena.py ... ARENA_DEALS=1`.

    THE POINT OF THIS PATH: the tilt map was first fitted against auctions the
    SERVER bot bid, and that bot scores hands on the same rank curve the probe
    measures with -- so the two share a yardstick and the magnitude is inflated
    even though the direction is not. These positions come from EXPERT-driven
    auctions, i.e. the bidder that actually plays, which is what the map has to
    describe.

    Only the five fields `percentile` reads are rebuilt; nothing here needs a
    playable game.
    """
    import glob
    import json
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
            for e in (r["events"][0] if r.get("events") else []):
                if e[0] == "deal" and len(e) >= 7:
                    out.append({
                        "auction": {"declarer": e[2], "level": e[3], "denom": e[4]},
                        "hands": e[5], "piles": e[6],
                    })
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    arena = [a[len("--from-arena="):] for a in sys.argv[1:]
             if a.startswith("--from-arena=")]
    rng = random.Random(12345)
    rows = []
    if arena:
        games = from_arena(arena)
        print(f"  positions from EXPERT-driven arena auctions: {len(games)}")
        for g in games:
            r = percentile(g, rng)
            if r:
                rows.append(r)
    else:
        n = int(args[0]) if args else 200
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

    # --- CAN A TILT ACTUALLY FIX THE CENTRING? ------------------------------
    print(f"\n=== THE FIX, SIMULATED: exponential tilt `w = exp(beta x strength)` ===")
    print(f"  beta = 0 is today. The target is a mean percentile of 0.500 --")
    print(f"  a sample centred on the truth rather than under it.\n")
    print(f"    {'beta':>6} {'mean pctile':>13} {'|error|':>9}")
    grid = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.7, 1.0]
    best = None
    for b in grid:
        mu = statistics.mean(tilted(r[0], r[5], b) for r in rows)
        flag = ""
        if best is None or abs(mu - 0.5) < abs(best[1] - 0.5):
            best, flag = (b, mu), "  <-- closest"
        print(f"    {b:>6.2f} {mu:>12.3f} {abs(mu-0.5):>9.3f}{flag}")
    print(f"\n  best single beta = {best[0]:.2f} -> mean percentile {best[1]:.3f}")

    print(f"\n  ...and PER LEVEL, since the bias grows with the bid:")
    print(f"    {'level':>6} {'n':>5} {'beta*':>7} {'pctile at beta*':>17}")
    per = {}
    for lv in sorted({r[2] for r in rows}):
        sel = [r for r in rows if r[2] == lv]
        if len(sel) < 8:
            continue
        b_best, mu_best = None, None
        for b in [x / 100 for x in range(0, 121, 5)]:
            mu = statistics.mean(tilted(r[0], r[5], b) for r in sel)
            if b_best is None or abs(mu - 0.5) < abs(mu_best - 0.5):
                b_best, mu_best = b, mu
        per[lv] = b_best
        print(f"    {lv:>6} {len(sel):>5} {b_best:>7.2f} {mu_best:>17.3f}")
    if per:
        print(f"\n  per-level tilt map: {per}")


if __name__ == "__main__":
    main()
