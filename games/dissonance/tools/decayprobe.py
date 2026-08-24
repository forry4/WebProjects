"""How long into the round is the AUCTION still evidence?

The belief prior corrects a real bias at trick 1: the declarer won an auction,
so their holding is stronger than a uniform resample of the cards the defender
cannot see (measured 0.765 percentile against server-bot bidding, 0.711 against
Expert's). Extending it to the CARD PLAY is only worth the work if that bias
survives past the opening lead -- every trick played reveals cards and shrinks
the unseen pool, and at some point the position speaks for itself.

DECISIVE AND CHEAP. No solver: this measures the SAMPLING, exactly like
`beliefprobe`, so it can run beside a live arena and answers "is there anything
here" before anything is built.

WHY IT CANNOT BE ANSWERED BY `bin/arena`: that harness plays card rounds with a
fixed trump and NO auction, so the declarer's hand is not selected by anything
and the prior's premise is simply absent there. `bin/cmatch` is worse for this
purpose -- it imposes a contract on a random hand, so a tilt would be wrong
rather than merely unmeasurable. The only valid vehicle is the full
auction-then-play pipeline, which is why measuring the bias directly is worth
more than a strength run that cannot be afforded.

Run:  PYTHONPATH=. python -m games.dissonance.tools.decayprobe 250
"""
import random
import statistics
import sys

from games.dissonance import bot as B
from games.dissonance import engine as E
from games.dissonance.tools.beliefprobe import strength, to_double

DRAWS = 120


def unseen_and_holding(g, viewer):
    """What `viewer` cannot place, and how much of it the DECLARER still holds.

    A seat may name: its own hand, every pile TOP, both middle-pile bottoms, and
    every card already played. Everything else is the pool a determinizer draws
    from -- the opponent's hand, all four outer bottoms, and the out-cards.
    """
    decl = g["auction"]["declarer"]
    seen = set(g["hands"][viewer])
    # `played` is the engine's own set of spent cards (rebuilt from `history`
    # by `expand_state`, so it is never merely absent). A history entry is a
    # TRIPLE and unpacking it as a pair is how this first went wrong.
    seen |= set(g.get("played") or [])
    known_decl, hidden_decl = [], 0
    for owner in (0, 1):
        for i, p in enumerate(g["piles"][owner]):
            if not p:
                continue
            if p[-1] not in seen:
                seen.add(p[-1])
                if owner == decl:
                    known_decl.append(p[-1])
            elif owner == decl and p[-1] in seen:
                if owner == decl and p[-1] not in known_decl:
                    known_decl.append(p[-1])
            if len(p) == 2:
                if i == 1:
                    seen.add(p[0])
                    if owner == decl:
                        known_decl.append(p[0])
                elif owner == decl:
                    hidden_decl += 1
    pool = [c for c in range(E.deck_size("classic")) if c not in seen]
    hidden_decl += len(g["hands"][decl])
    return pool, known_decl, hidden_decl


def percentile_now(g, rng):
    """Where the declarer's remaining holding sits among uniform resamples."""
    decl = g["auction"]["declarer"]
    viewer = 1 - decl
    trump = g["auction"]["denom"]
    pool, known, n_hidden = unseen_and_holding(g, viewer)
    if n_hidden <= 0 or n_hidden > len(pool):
        return None
    real = list(g["hands"][decl])
    for p in g["piles"][decl]:
        real += [c for c in p]
    mine = strength(real, trump)
    base = strength(known, trump)
    below = 0
    for _ in range(DRAWS):
        if base + strength(rng.sample(pool, n_hidden), trump) < mine:
            below += 1
    return below / DRAWS


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    rng = random.Random(999)
    by_trick = {}
    rounds = 0
    for s in range(n):
        g = to_double(600_000 + s)
        if g is None:
            continue
        E.apply_double(g, 1 - g["auction"]["declarer"], False)
        rounds += 1
        guard = 0
        while g["phase"] == "play" and guard < 40:
            guard += 1
            t = g["trick"]
            if g["led"] is None:                     # top of a fresh trick
                p = percentile_now(g, rng)
                if p is not None:
                    by_trick.setdefault(t, []).append(p)
            seat = E.turn_seat(g)
            if seat is None:
                break
            kind, card = B.act(g, seat, random.Random(s))
            if kind != "play":
                break
            E.apply_move(g, g["seats"][seat], {"kind": "play", "card": card})

    print(f"\n=== {rounds} rounds, the declarer's remaining holding vs a uniform "
          f"resample ===")
    print("  0.500 = the position speaks for itself and the auction adds nothing.")
    print("  Higher = the sampler still imagines the declarer WEAKER than they are.\n")
    print(f"  {'trick':>6} {'n':>5} {'mean percentile':>16}")
    for t in sorted(by_trick):
        v = by_trick[t]
        if len(v) < 10:
            continue
        mu = statistics.mean(v)
        print(f"  {t + 1:>6} {len(v):>5} {mu:>15.3f}  {'#' * int(mu * 40)}")
    early = [p for t, v in by_trick.items() if t <= 3 for p in v]
    late = [p for t, v in by_trick.items() if t >= 8 for p in v]
    if early and late:
        print(f"\n  tricks 1-4: {statistics.mean(early):.3f}   "
              f"tricks 9-13: {statistics.mean(late):.3f}")


if __name__ == "__main__":
    main()
