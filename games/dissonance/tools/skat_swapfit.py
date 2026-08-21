"""FIT skat's talon swap, the way classic's was fitted (2026-08-20).

`bot.choose_swap`'s skat branch is `worth(take) - worth(give)` -- SEPARABLE, so
its 3x7 "search" can only ever mean "take the highest card shown, throw the
lowest card held". Classic ran the identical rule until 2026-08-08 and it
measured -0.477 +- 0.226 score/round against simply standing pat; skat has kept
it, deliberately, because classic's fitted weights were trained where the
denomination and level are already known and skat's talon resolves BEFORE the
game is named. This is skat's own run.

WHAT THE ORACLE SAID (310 decisions, `swaplab.py skat`):

    policy regret vs the oracle   mean 4.10   median 1.0   worst 50
    policy vs standing pat        +2.18
    ORACLE vs standing pat        +6.28        <- the recoverable headroom
    oracle stands pat 23% of the time, the policy 1%
    the policy is WORSE THAN PAT on 12% of decisions
    it picks the oracle's exchange 9% of the time

and the histograms show the separability directly: the policy GIVES an 8 on 55%
of decisions and a 10/J/Q on 1%, where the oracle gives a 10/J/Q on 36%.

THE FEATURES ARE INFORMATION-LEGAL AND INTERPRETABLE, which is the whole point
of fitting rather than searching: the shipped policy has to run on the hand, the
shown talon and the public piles, with no contract named. Nothing here reads the
opponent's cards or the solve.

    PYTHONPATH=. python3 games/dissonance/tools/skat_swapfit.py
"""
import glob
import json
import os
import sys

from games.dissonance import engine as E, bot as B
from games.dissonance.tools import talon as T

SP = os.environ.get("SWAPLAB_DIR", ".")
#: WHICH CORPUS. `dd` labels are the exact-solve oracle this file was built
#: around; `play` labels are the same enumeration scored by the SHIPPED card
#: play (`swaplab.py <mode> <n> <lo> <hi> play`). They are different objectives
#: and the fits differ -- see the module docstring.
GLOB = os.environ.get("SWAPLAB_GLOB", "skatswap_*.jsonl")
#: RANK SLOTS, not `NRANK`. `E.rank` returns a card's STRENGTH on the WIDE
#: deck's scale (0..9, the 5 through the ace) even in a 32-card mode, where only
#: 2..9 are ever reachable. Sizing the one-hot blocks by `NRANK` (8) instead
#: OVERLAPS them: the give block would start at 8 and run to 17, and 16/17 are
#: the trump features -- so "give a king" and "the take is trump" would be the
#: same weight. Caught by the shipped policy raising IndexError on an ace.
NRANKS = E.NRANKS


def replay(m):
    """Re-drive deal `m` to its talon. Deterministic: same seeds as `swaplab`."""
    at = T.drive_to_talon(m, "skat")
    return None if at is None else at[0]


def feats(g, seat, take, give):
    """One candidate exchange as a feature vector.

    STANDING PAT IS THE ZERO VECTOR, because the target is `value - pat`: the
    fit then answers "what is this exchange worth over doing nothing", and a
    policy reading it stands pat exactly when no exchange scores positive. That
    is the half the shipped rule cannot express at all -- its `best_gain > 0`
    floor compares two separable worths, so it stands pat on 1% of decisions
    where the oracle does on 23%.
    """
    n = 2 * NRANKS + 7
    x = [0.0] * n
    if take is None:
        return x
    # AN INTERCEPT ON EVERY EXCHANGE, and pat's zero vector is what gives it
    # meaning: it is the BAR an exchange has to clear to be worth making at all.
    # Classic tried a fitted stand-pat bar and dropped it because there it
    # cancels out of the argmax -- every candidate carried it equally. Here pat
    # is itself a candidate scored at exactly 0, so the term does not cancel and
    # is the only thing that can teach the policy to do nothing. The shipped
    # rule cannot express that at any weight: its floor compares two separable
    # worths, which is why it stands pat on 1% of decisions and the oracle on 23%.
    x[-1] = 1.0
    d = B.swap_denom(g, seat)
    hand = list(g["hands"][seat])
    tc = E.trump_class(d)
    x[E.rank(take)] = 1.0                       # what comes in, by rank
    x[NRANKS + E.rank(give)] = 1.0               # what goes out, by rank
    i = 2 * NRANKS
    x[i] = 1.0 if E.esuit(take, d) == tc else 0.0
    x[i + 1] = 1.0 if E.esuit(give, d) == tc else 0.0
    # SHAPE, from the hand AFTER the exchange: how short the give leaves its
    # suit, and how long the take makes its own.
    gs = sum(1 for c in hand if E.esuit(c, d) == E.esuit(give, d))
    ts = sum(1 for c in hand if E.esuit(c, d) == E.esuit(take, d))
    x[i + 2] = 1.0 if gs == 1 else 0.0          # the give voids a suit
    x[i + 3] = 1.0 if gs == 2 else 0.0          # ...or leaves a singleton
    x[i + 4] = ts / 7.0                         # the take joins a long suit
    # THE POOL. Skat scores the CARDS captured, and a discard leaves play
    # entirely -- so what the talon swallows changes what the round is worth to
    # both seats. Classic has no analogue of this term.
    x[i + 5] = (E.card_points(take) - E.card_points(give)) / 2.0
    return x


def ridge(X, y, lam=1.0):
    n = len(X[0])
    A = [[sum(r[i] * r[j] for r in X) + (lam if i == j else 0.0) for j in range(n)]
         for i in range(n)]
    b = [sum(r[i] * t for r, t in zip(X, y)) for i in range(n)]
    for c in range(n):                       # Gaussian elimination
        p = max(range(c, n), key=lambda r: abs(A[r][c]))
        A[c], A[p] = A[p], A[c]
        b[c], b[p] = b[p], b[c]
        if abs(A[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r == c:
                continue
            f = A[r][c] / A[c][c]
            for k in range(c, n):
                A[r][k] -= f * A[c][k]
            b[r] -= f * b[c]
    return [b[i] / A[i][i] if abs(A[i][i]) > 1e-12 else 0.0 for i in range(n)]


def main():
    rows = [json.loads(l[5:]) for p in glob.glob(SP + "/" + GLOB)
            for l in open(p) if l.startswith("SWAP ")]
    rows.sort(key=lambda r: r["deal"])
    print(f"  {len(rows)} decisions")
    data = []
    for r in rows:
        g = replay(r["deal"])
        if g is None:
            continue
        seat = g["auction"]["declarer"]
        cands = [(t, h, v, feats(g, seat, t, h)) for t, h, v in r["cands"]]
        data.append((r, cands))
    print(f"  {len(data)} replayed")
    # HELD OUT BY DEAL, not by candidate: every candidate of one decision shares
    # its hand, so splitting inside a decision would leak it across the split.
    cut = int(0.7 * len(data))
    tr, te = data[:cut], data[cut:]
    X, y = [], []
    for r, cands in tr:
        for _t, _h, v, f in cands:
            X.append(f)
            y.append(v - r["pat"])
    w = ridge(X, y)

    def pick(cands):
        best, bs = (None, None), 0.0
        for t, h, v, f in cands:
            s = sum(a * b for a, b in zip(w, f))
            if s > bs:
                bs, best = s, (t, h)
        return best

    def regret(split, chooser):
        out = []
        for r, cands in split:
            t, h = chooser(r, cands)
            v = next(c[2] for c in cands if (c[0], c[1]) == (t, h))
            out.append(r["best"] - v)
        return sum(out) / len(out)

    def old(r, _c):
        return (r["cur_take"], r["cur_give"])

    def pat(_r, _c):
        return (None, None)

    print(f"\n  HELD-OUT regret against the oracle ({len(te)} decisions):")
    print(f"    shipped rule   {regret(te, old):>6.2f}")
    print(f"    standing pat   {regret(te, pat):>6.2f}")
    print(f"    FITTED         {regret(te, lambda r, c: pick(c)):>6.2f}")
    print(f"\n  ...and in-sample ({len(tr)}): "
          f"shipped {regret(tr, old):.2f}  fitted {regret(tr, lambda r, c: pick(c)):.2f}")
    npat = sum(1 for r, c in te if pick(c) == (None, None))
    print(f"  fitted stands pat on {100*npat/len(te):.0f}% of held-out decisions "
          f"(oracle 23%, shipped 1%)")
    names = ([f"take {E.RANK_NAMES[i]}" for i in range(NRANKS)]
             + [f"give {E.RANK_NAMES[i]}" for i in range(NRANKS)]
             + ["take trump", "give trump", "give voids", "give singleton",
                "take suit len", "card-point delta", "SWAP AT ALL (bar)"])
    # A NAME PER WEIGHT, asserted. The layout bug this file shipped with was
    # exactly a length mismatch (one-hot blocks sized by `NRANK`, indexed by a
    # `NRANKS` rank), and the only reason it surfaced at all was the policy
    # raising IndexError on an ace -- the fit itself printed 23 happy numbers.
    assert len(names) == len(w), (len(names), len(w))
    print("\n  WEIGHTS")
    for n, v in zip(names, w):
        print(f"    {n:>18} {v:>+8.3f}")


if __name__ == "__main__":
    main()
