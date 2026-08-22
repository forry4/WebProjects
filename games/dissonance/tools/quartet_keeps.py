"""THE THREE CARDS NOBODY PLAYS -- are they a decision or a formality?

The four-hand deal is twelve cards a hand and NINE tricks, so every hand ends
holding three it never played, and those three score their card value
(`E.CARD_VALUES`) into the same total the contract is bid against. The idea is
that the last tricks become a squeeze: a 9/10/J/Q is +2 in your hand at the
end, and also the card most likely to win you a trick, so every ply asks which
you want.

THE MECHANIC HAS AN OBVIOUS FAILURE MODE AND THIS FILE EXISTS TO PRICE IT. The
best three cards in a twelve-card hand are worth +5.49 on average and the
ceiling is +6, which 80% of hands can reach -- so if a player can simply KEEP
their best three, every player scores +6 every round, the variance is zero and
the mechanic is decoration with extra steps. It is only a decision if
follow-suit drags those cards out of the hand against the owner's will.

So the number that matters is not what the keeps are worth. It is the GAP
between what a player wants to keep and what they are left holding:

    +5.49   the best three in the hand (what you would keep if free)
    +0.92   three at random (what you get with no control at all)

Anything landing near the top means no pressure; near the bottom means no
control. The measurement runs two policies over real deals to find out --
`random` (no attempt to protect) and `protect` (always play your cheapest card
first, which is the greedy every player would find immediately).

CAVEAT, and it is the same one `quartet_agency.py` carries: `protect` is a
greedy, not a searcher, and neither policy ATTACKS -- a real opponent leads the
suits your +2 cards live in to force them out, which no policy here does. So
the gap measured is a floor on the pressure a real game applies, not an
estimate of it.

MEASURED 2026-08-21, 4000 rounds a policy:

    policy      own-hand keeps    sd   at the +6 ceiling
    random               +0.91  2.00                2.3%
    protect              +4.41  1.70               44.4%

**The mechanic holds.** The greedy lands at +4.41 against a free ceiling of
+5.49, so follow-suit alone costs a protecting player 1.08 points and denies
them the ceiling 55.6% of the time -- they are forced to give something up in
more than half of all rounds, without anyone even trying to make them. `random`
reproducing the analytic +0.92 is the harness checking itself.

ONLY THE OWN HAND'S THREE SCORE, and the magnitude is why. The best SIX across
a player's two hands is +11.64 against a random +1.84 -- a 9.8-point skill band
against a trick range of -5..+8, i.e. three quarters of the round decided off
the table. One hand's three is a 4.6-point band, about a third, which is a
second currency rather than the main one.

THE DUMMY STILL KEEPS THREE AND THEY SCORE NOTHING -- deliberate, after the
alternative was measured and is worse. Dealing the dummy nine cards so it plays
out exactly (12/9/12/9, ten out) drops it to 2.88 choices and 24% forced, which
is dummy mode's 2.89 failure mark. So the dead keeps stay, and they are better
read as an ASYMMETRY than a wart: your own hand is under squeeze pressure and
hoards, while your dummy has nothing to protect and can spend freely to attack.
The two hands you command want opposite things in the endgame.

    PYTHONPATH=. python3 -m games.dissonance.tools.quartet_keeps [rounds]
"""

from __future__ import annotations

import random
import statistics
import sys

from games.dissonance import engine as E
from games.dissonance.tools.quartet_agency import Layout, deal, legal, _cls, _wins

#: Twelve a hand, nine tricks, three kept -- the deal `quartet_agency` fitted.
LAYOUT = Layout("12/12/12/12 9tr", 12, 0, 12, 0, 9)

#: Seats 0 and 1 are the players' OWN hands; 2 and 3 are their dummies. Only an
#: own hand's keeps score -- see the magnitude note in `main`.
OWN_SEATS = (0, 1)


def _pick(policy, opts, rng):
    if policy == "random":
        return rng.choice(opts)
    # protect: shed the cheapest card first, so -1s go before 0s before +2s.
    # Playing a -1 is doubly right -- it is a liability to keep AND the A/K are
    # the best trick-winners, so the greedy never has to trade the two off.
    return min(opts, key=lambda c: (E.card_points(c), E.rank(c)))


def one_round(rng, policy, trump):
    seats, _out = deal(LAYOUT, rng)
    leader = 0
    for _t in range(LAYOUT.ntricks):
        plays, led = [], None
        for k in range(4):
            pos = (leader + k) % 4
            opts = legal(seats[pos], led, trump)
            c = _pick(policy, opts, rng)
            seats[pos].play(c)
            if led is None:
                led = _cls(c, trump)
            plays.append((pos, c))
        leader = plays[_wins(plays, trump)][0]
    keeps = {}
    for pos in range(4):
        left = seats[pos].hand + [c for p in seats[pos].piles for c in p]
        assert len(left) == 3, (pos, left)
        keeps[pos] = sum(E.card_points(c) for c in left)
    return keeps


def measure(rounds, policy, seed=13):
    rng = random.Random(seed)
    own, dummy = [], []
    for _ in range(rounds):
        trump = rng.choice([0, 1, 2, 3, None])
        k = one_round(rng, policy, trump)
        own += [k[p] for p in OWN_SEATS]
        dummy += [k[p] for p in (2, 3)]
    return own, dummy


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    print("reference points (what a hand COULD hold, unconstrained):")
    print("   best three of twelve   +5.49      three at random   +0.92\n")
    print(f"{'policy':10s} {'own-hand keeps':>16s} {'sd':>5s} {'dummy keeps':>13s} "
          f"{'% at the +6 ceiling':>21s}")
    for policy in ("random", "protect"):
        own, dummy = measure(rounds, policy)
        ceil = sum(1 for v in own if v == 6) / len(own)
        print(f"{policy:10s} {statistics.mean(own):+16.2f} "
              f"{statistics.pstdev(own):5.2f} {statistics.mean(dummy):+13.2f} "
              f"{ceil:20.1%}")


if __name__ == "__main__":
    main()
