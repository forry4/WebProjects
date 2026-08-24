"""FITTING THE FOUR-HAND AUCTION: backed bids, and what a bid can prove.

The design being fitted (chosen with `quartet_agency.py`, whose numbers pin the
DEAL; this file pins the AUCTION on top of it):

  * a bid may only name a denomination its bidder can BACK -- at least K cards
    in that suit across their two hands. So every bid is a provable statement
    about the bidder's holding, and the opponent can count against it. This is
    the substitute for bridge's partner conventions, which a two-player game
    cannot have: the information is enforced by legality rather than agreed.
  * NO-TRUMP IS ALWAYS LEGAL, which is what stops a hand being unbiddable. It
    also makes an NT bid ambiguous in a useful way -- real strength, or no suit
    at all -- rather than a tell.

THE THRESHOLD IS THE WHOLE DESIGN AND IT IS A TWO-SIDED FIT. Too low and every
denomination is legal, so a bid proves nothing and the mechanism is decoration.
Too high and one suit or none clears, so the bid is mechanical -- it proves a
lot and decides nothing, because the bidder had no choice to make. What is
wanted is a K that usually leaves TWO OR THREE legal suits (a real choice) while
excluding one or two (real information).

WHY THIS FILE IS POLICY-FREE, and why that matters. Every number here is a
property of the DEAL -- suit lengths, and what one player can infer about the
other's from the cards they hold themselves. No bot, no play, no scoring. So
unlike `quartet_agency.py` (whose random-play caveat is real), nothing here is
a lower bound waiting on a stronger policy: these numbers are final.

    PYTHONPATH=. python3 -m games.dissonance.tools.quartet_auction [deals]
"""

from __future__ import annotations

import random
import statistics
import sys
from collections import Counter
from math import log2

from games.dissonance import engine as E

NSUIT = E.NSUIT

#: The deal this auction sits on: four hands of twelve, four cards out, nine
#: tricks, three cards kept in every hand. See `quartet_agency.py`.
HAND = 12          # cards per hand
OWN = 2 * HAND     # what one player holds across their two hands
NOUT = E.NCARD_FULL - 4 * HAND


def deal(rng):
    """Returns (player A's 24, player B's 24, the out-pile)."""
    deck = list(range(E.NCARD_FULL))
    rng.shuffle(deck)
    a = deck[:HAND] + deck[2 * HAND:3 * HAND]
    b = deck[HAND:2 * HAND] + deck[3 * HAND:4 * HAND]
    return a, b, deck[4 * HAND:]


def lengths(cards):
    c = Counter(E.suit(x) for x in cards)
    return [c.get(s, 0) for s in range(NSUIT)]


def viability(deals, rng):
    """How many denominations can a player actually back, per threshold?"""
    rows = {}
    seen = [[] for _ in range(NSUIT)]
    for _ in range(deals):
        a, b, _out = deal(rng)
        for side in (a, b):
            ln = lengths(side)
            for s in range(NSUIT):
                seen[s].append(ln[s])
    flat = [n for s in seen for n in s]
    for k in range(4, 11):
        legal = []
        for i in range(0, len(flat), NSUIT):
            legal.append(sum(1 for n in flat[i:i + NSUIT] if n >= k))
        rows[k] = {
            "mean_legal": statistics.mean(legal),
            "none": sum(1 for n in legal if n == 0) / len(legal),
            "one": sum(1 for n in legal if n == 1) / len(legal),
            "two_plus": sum(1 for n in legal if n >= 2) / len(legal),
        }
    return rows, flat


def _entropy(counts):
    tot = sum(counts.values())
    return -sum((c / tot) * log2(c / tot) for c in counts.values() if c)


def informativeness(deals, rng, k):
    """WHAT A BACKED BID PROVES, from the opponent's chair.

    The opponent holds 24 cards, so they already know a great deal about the
    unknown 28 -- this measures what the BID adds on top of that, which is the
    only thing that counts. Prior: the bidder's length in suit S given only what
    the opponent holds. Posterior: the same, given the bid was legal (>= k).
    """
    prior, post = Counter(), Counter()
    shifts = []
    for _ in range(deals):
        a, b, _out = deal(rng)
        for me, them in ((a, b), (b, a)):
            mine = lengths(me)
            theirs = lengths(them)
            for s in range(NSUIT):
                # what I can infer about their length in s, knowing my own
                prior[theirs[s]] += 1
                if theirs[s] >= k:
                    post[theirs[s]] += 1
                    shifts.append((theirs[s], 13 - mine[s]))
    p_mean = sum(n * c for n, c in prior.items()) / sum(prior.values())
    q_mean = sum(n * c for n, c in post.items()) / sum(post.values())
    return {
        "prior_mean": p_mean,
        "posterior_mean": q_mean,
        "shift": q_mean - p_mean,
        "prior_bits": _entropy(prior),
        "posterior_bits": _entropy(post),
        "bits_gained": _entropy(prior) - _entropy(post),
        "rate": sum(post.values()) / sum(prior.values()),
    }


def main():
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    rng = random.Random(17)
    rows, flat = viability(deals, rng)

    print(f"deal: four hands of {HAND}, {NOUT} out, {OWN} cards a player")
    print(f"suit length across a player's {OWN}: mean {statistics.mean(flat):.2f} "
          f"sd {statistics.pstdev(flat):.2f}\n")

    print(f"{'K':>3s} {'mean legal suits':>17s} {'none':>7s} {'exactly 1':>10s} "
          f"{'2 or more':>10s}")
    for k, r in rows.items():
        print(f"{k:3d} {r['mean_legal']:17.2f} {r['none']:7.1%} "
              f"{r['one']:10.1%} {r['two_plus']:10.1%}")

    print(f"\n{'K':>3s} {'legal rate':>11s} {'E[len] prior':>13s} "
          f"{'posterior':>10s} {'shift':>7s} {'bits proved':>12s}")
    for k in range(5, 10):
        r = informativeness(deals // 4, random.Random(29), k)
        print(f"{k:3d} {r['rate']:11.1%} {r['prior_mean']:13.2f} "
              f"{r['posterior_mean']:10.2f} {r['shift']:+7.2f} "
              f"{r['bits_gained']:12.2f}")


if __name__ == "__main__":
    main()
