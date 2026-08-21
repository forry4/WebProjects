"""FOUR-HAND AGENCY: how much CHOICE does each seat get, before the mode exists?

The four-hand mode deals 52 cards as 13 / 10 / 13 / 10 -- two player hands and
two dummy hands, each player commanding the seat opposite them -- plays TEN
tricks of four, and leaves the six cards nobody played out of the round. Every
number in that sentence except the deck size is still a candidate, and the one
that decides whether the mode has card play at all is the PILE SPLIT: only a
pile's top is playable, so every card buried in a pile is a card the deal chose
for you instead of you.

`agency_probe.py` is the same measurement for the shipped modes and the reason
this file exists: dummy mode's FIRST layout (4 in hand + 6 in piles) measured
2.89 legal cards at a decision and a third of all plies forced outright,
against classic's 4.07 and 46% on rails, and it had to be re-dealt onto a wider
deck after it shipped. Fitting the split BEFORE the mode is built is the whole
point.

WHY THIS IS A STANDALONE SIMULATOR AND NOT A DRIVE OF `engine.py`. The layouts
it sweeps do not exist as modes, and wiring each candidate into the engine to
measure it would cost more than the question is worth -- so this file models
the deal, follow-suit and the trick loop directly. It is NOT a second engine:
card semantics (`suit`, `rank`, `beats`, `card_of`) all come from `engine`, so
a rank curve or a trump rule cannot drift between the two. What it does NOT
model is scoring, the auction or visibility, none of which move a choice count.

THE POLICY IS RANDOM LEGAL PLAY, and that is a real caveat rather than a
convenience: there is no bot for this mode yet, and which cards get played
changes what is left to choose from later. A skilled policy would read
somewhat differently. Random is the neutral prior, and the SPLIT between
candidate layouts is what this is being read for, not the absolute level.

MEASURED 2026-08-21, 1500 rounds an arm, stable to +-0.02 over three seeds.
Classic through the real engine reads 4.02 choices / 22% forced / 46% on rails.

    structure                      choices  forced  player  dummy
    13/10  6 out  dummy 4+3p          3.68     25%    4.77   2.59
    13/10  6 out  dummy flat          3.93     22%    4.78   3.08
    13/13  0 out  dummy 7+3p          4.21     18%    4.76   3.66
    13/13  0 out  dummy flat          4.52     15%    4.75   4.29
    12/11  6 out  dummy 5+3p          3.65     22%    4.35   2.95
    12/11  6 out  dummy flat          3.95     18%    4.37   3.53
    11/12  6 out  dummy 6+3p          3.61     20%    3.89   3.33

THE PILE SPLIT WAS THE WRONG QUESTION, and finding that out is what this cost.
Every 13/10 arm leaves the DUMMY seats starved -- 2.59 legal cards buried at
4+3 piles, and only 3.08 with no piles at all, against the 2.89 that sent dummy
mode back to be re-dealt. Burial moves the dummy by 0.5; what actually
constrains it is its CARD COUNT. A 10-card hand playing ten tricks is down to
one forced card at trick 10 while a 13-card hand still holds four, and the
endgame gradient shows it: every 13/10 arm ends the round at 1.98-2.10 choices,
every 13/13 arm at 2.84-2.98.

SO THE FOUR-HAND DEAL WANTS TO BE 13/13/13/13, and the cost is that 52 cards in
four equal hands leaves NOTHING OUT -- no six out-cards, and so no talon to cut
a declarer's prize from. That is a product decision, not a measurement, and it
is the one this file cannot make.

`13/13, dummy 7+3p` is the arm to beat: 4.21 / 18% beats classic on both, the
dummy at 3.66 clears the failure threshold with room, and the player hand stays
the freer of the two (4.76 vs 3.66) -- which is the asymmetry the layout is
for. Your hand is where you choose; your dummy is where you discover.

    PYTHONPATH=. python3 -m games.dissonance.tools.quartet_agency [rounds]
"""

from __future__ import annotations

import random
import statistics
import sys
from collections import defaultdict

from games.dissonance import engine as E

NTRICK = 10          # tricks played
NSEAT = 4            # 0 and 2 are player A, 1 and 3 are player B
PLAYER_POS = (0, 2)  # the seats a human holds in their own hand


class Layout:
    """A candidate deal. `hand` cards go straight to hand; `piles` 2-card piles
    sit on top of each other's bottoms, only the top playable."""

    def __init__(self, name, p_hand, p_piles, d_hand, d_piles):
        self.name = name
        self.p_hand, self.p_piles = p_hand, p_piles
        self.d_hand, self.d_piles = d_hand, d_piles

    def size(self, pos):
        h, p = ((self.p_hand, self.p_piles) if pos in PLAYER_POS
                else (self.d_hand, self.d_piles))
        return h + 2 * p

    def split(self, pos):
        return ((self.p_hand, self.p_piles) if pos in PLAYER_POS
                else (self.d_hand, self.d_piles))

    def on_rails(self, pos):
        """Share of the holding that is buried -- a pile's BOTTOM is a card the
        deal picked. A pile top is playable, so it is not on rails."""
        _h, p = self.split(pos)
        return p / self.size(pos)


class Seat:
    def __init__(self, hand, piles):
        self.hand = list(hand)
        self.piles = [list(p) for p in piles]   # each [bottom, top]

    def playable(self):
        return self.hand + [p[-1] for p in self.piles if p]

    def play(self, c):
        if c in self.hand:
            self.hand.remove(c)
            return
        for p in self.piles:
            if p and p[-1] == c:
                p.pop()
                return
        raise ValueError("card not playable")


def deal(layout, rng):
    deck = list(range(E.NCARD_FULL))
    rng.shuffle(deck)
    seats, i = [], 0
    for pos in range(NSEAT):
        h, p = layout.split(pos)
        hand = deck[i:i + h]
        i += h
        piles = [deck[i + 2 * k:i + 2 * k + 2] for k in range(p)]
        i += 2 * p
        seats.append(Seat(hand, piles))
    return seats, deck[i:]          # the rest sit out


def legal(seat, led_suit, trump):
    """Follow-suit is mandatory and A PILE TOP COUNTS AS A CARD YOU HOLD --
    Dissonance's rule, not bridge's. Ruffing when void is allowed, never
    forced."""
    cards = seat.playable()
    if led_suit is None:
        return cards
    follow = [c for c in cards if _cls(c, trump) == led_suit]
    return follow or cards


def _cls(c, trump):
    """Follow-suit class. Plain suit here -- Grand's ten rule is a skat
    denomination and the four-hand auction does not offer it."""
    return E.suit(c)


def _wins(plays, trump):
    """Index into `plays` [(pos, card)] of the card taking the trick."""
    led = _cls(plays[0][1], trump)
    best = 0
    for i in range(1, len(plays)):
        c, b = plays[i][1], plays[best][1]
        c_t = trump is not None and E.suit(c) == trump
        b_t = trump is not None and E.suit(b) == trump
        if c_t and not b_t:
            best = i
        elif c_t == b_t and _cls(c, trump) == _cls(b, trump) == led \
                and E.rank(c) > E.rank(b):
            best = i
        elif c_t and b_t and E.rank(c) > E.rank(b):
            best = i
    return best


def one_round(layout, rng, trump):
    seats, _out = deal(layout, rng)
    leader = 0
    counts, forced, plies = [], 0, 0
    by_pos = defaultdict(list)
    by_trick = defaultdict(list)
    for t in range(NTRICK):
        plays, led_suit = [], None
        for k in range(NSEAT):
            pos = (leader + k) % NSEAT
            opts = legal(seats[pos], led_suit, trump)
            if not opts:
                raise AssertionError("no legal card: layout deals too few")
            counts.append(len(opts))
            by_pos[pos].append(len(opts))
            by_trick[t].append(len(opts))
            plies += 1
            forced += (len(opts) == 1)
            c = rng.choice(opts)
            seats[pos].play(c)
            if led_suit is None:
                led_suit = _cls(c, trump)
            plays.append((pos, c))
        leader = plays[_wins(plays, trump)][0]
    # every player seat must finish holding exactly its keep count
    for pos in range(NSEAT):
        left = len(seats[pos].hand) + sum(len(p) for p in seats[pos].piles)
        assert left == layout.size(pos) - NTRICK, (pos, left)
    return counts, forced, plies, by_pos, by_trick


def measure(layout, rounds, seed=11, trump="sample"):
    rng = random.Random(seed)
    counts, forced, plies = [], 0, 0
    by_pos, by_trick = defaultdict(list), defaultdict(list)
    for _ in range(rounds):
        t = rng.choice([0, 1, 2, 3, None]) if trump == "sample" else trump
        c, f, p, bp, bt = one_round(layout, rng, t)
        counts += c
        forced += f
        plies += p
        for k, v in bp.items():
            by_pos[k] += v
        for k, v in bt.items():
            by_trick[k] += v
    return {
        "choices": statistics.mean(counts),
        "forced": forced / plies,
        "player": statistics.mean(by_pos[0] + by_pos[2]),
        "dummy": statistics.mean(by_pos[1] + by_pos[3]),
        "by_trick": [round(statistics.mean(by_trick[t]), 2)
                     for t in range(NTRICK)],
        "rails_p": layout.on_rails(0),
        "rails_d": layout.on_rails(1),
    }


#: THE PILE SWEEP. The player hand is 13 and the dummy 10 in all of these --
#: the split this file was written to test. What is open is how much of each is
#: BURIED.
CANDIDATES = [
    Layout("player 13 flat  / dummy 4+3p", 13, 0, 4, 3),
    Layout("player 13 flat  / dummy 6+2p", 13, 0, 6, 2),
    Layout("player 13 flat  / dummy 8+1p", 13, 0, 8, 1),
    Layout("player 13 flat  / dummy 10 flat", 13, 0, 10, 0),
    Layout("player 11+1p    / dummy 4+3p", 11, 1, 4, 3),
    Layout("player 11+1p    / dummy 6+2p", 11, 1, 6, 2),
    Layout("player 9+2p     / dummy 4+3p", 9, 2, 4, 3),
    Layout("player 7+3p     / dummy 4+3p", 7, 3, 4, 3),
]


#: THE STRUCTURE SWEEP, and the reason it exists: the pile sweep above answered
#: its own question and turned up a bigger one. Every pile arrangement leaves
#: the DUMMY seats starved -- 2.58 legal cards at 4+3 piles and only 3.08 with
#: no piles at all, against classic's 4.02 -- so burial is not what constrains
#: them. THEIR CARD COUNT IS: a 10-card hand playing all ten tricks is down to
#: one forced card at trick 10, while a 13-card hand still holds four. Piles
#: move the dummy by 0.5; the hand size is worth more than that.
#:
#: So these vary the DEAL rather than the burial. The constraint is that four
#: hands and six out must come to 52, and that every hand must survive ten
#: tricks:
#:   * 13/10 -- six out, a talon to cut from, dummy exhausted at trick 10
#:   * 13/13 -- nothing out, no talon, but ALL FOUR hands keep three
#:   * 12/11 and 11/12 -- six out, the shortage spread more evenly
STRUCTURES = [
    Layout("13/10  6 out  dummy 4+3p", 13, 0, 4, 3),
    Layout("13/10  6 out  dummy flat", 13, 0, 10, 0),
    Layout("13/13  0 out  dummy 7+3p", 13, 0, 7, 3),
    Layout("13/13  0 out  dummy flat", 13, 0, 13, 0),
    Layout("12/11  6 out  dummy 5+3p", 12, 0, 5, 3),
    Layout("12/11  6 out  dummy flat", 12, 0, 11, 0),
    Layout("11/12  6 out  dummy 6+3p", 11, 0, 6, 3),
]


def baseline(rounds):
    """Classic, through the REAL engine, so the comparison is live rather than
    quoted from a doc that may describe an older game."""
    from games.dissonance.tools.agency_probe import agency
    return agency("classic", max(20, rounds // 20))


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    base = baseline(rounds)
    print(f"classic baseline (real engine): choices {base['choices']:.2f}  "
          f"forced {base['forced']:.0%}  46% on rails\n")
    print(f"{'layout':32s} {'choices':>8s} {'forced':>7s} {'player':>7s} "
          f"{'dummy':>7s} {'rails P/D':>11s}")
    for lay in CANDIDATES:
        assert lay.size(0) == 13 and lay.size(1) == 10, lay.name
        r = measure(lay, rounds)
        print(f"{lay.name:32s} {r['choices']:8.2f} {r['forced']:7.0%} "
              f"{r['player']:7.2f} {r['dummy']:7.2f} "
              f"{r['rails_p']:5.0%}/{r['rails_d']:<5.0%}")
    print("\nchoices per trick (the endgame gradient):")
    for lay in CANDIDATES[:4]:
        r = measure(lay, rounds)
        print(f"  {lay.name:32s} {r['by_trick']}")

    print(f"\n{'structure':32s} {'choices':>8s} {'forced':>7s} {'player':>7s} "
          f"{'dummy':>7s} {'kept P/D':>10s}")
    for lay in STRUCTURES:
        dealt = 2 * lay.size(0) + 2 * lay.size(1)
        assert dealt + (E.NCARD_FULL - dealt) == E.NCARD_FULL
        assert lay.size(0) >= NTRICK and lay.size(1) >= NTRICK, lay.name
        r = measure(lay, rounds)
        print(f"{lay.name:32s} {r['choices']:8.2f} {r['forced']:7.0%} "
              f"{r['player']:7.2f} {r['dummy']:7.2f} "
              f"{lay.size(0) - NTRICK:4d}/{lay.size(1) - NTRICK:<5d}"
              f"   ({E.NCARD_FULL - dealt} out)")
    print("\nendgame gradient, structures:")
    for lay in STRUCTURES:
        r = measure(lay, rounds)
        print(f"  {lay.name:32s} {r['by_trick']}")


if __name__ == "__main__":
    main()
