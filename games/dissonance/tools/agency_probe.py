"""How much CHOICE does a player actually get, and does their hand decide it?

Two design goals want measuring before anything is built:

  1. "different hand types compete differently in the auction" -- needs hands
     to DIFFER in a way the auction can express. `spread` below is how far
     apart two hands sit on the one axis the auction currently has.
  2. "both sides have interesting decisions over what cards to play" -- needs
     players to HAVE decisions. `choices` is the mean number of legal cards at
     a decision and `forced` the share of plies with exactly one. A game where
     most plies are forced has no card play to be interesting.

THE SUSPECT this exists to test: a Dissonance seat keeps most of its holding
in PILES, of which only the top is playable. Classic deals 7 in hand + 6 in
piles (46% on rails); dummy mode deals 4 + 6 (60% on rails) because three
seats had to come out of one deck. If agency is what is missing, no value
table or ladder fixes it.

    PYTHONPATH=. python -m games.dissonance.tools.agency_probe [rounds]
"""

from __future__ import annotations

import random
import statistics
import sys

from games.dissonance import bot, engine as E


def agency(mode: str, rounds: int, seed: int = 5):
    """Play rounds out with the shipped policy, counting choices per ply."""
    rng = random.Random(seed)
    counts, forced, plies = [], 0, 0
    by_pos = {}
    for _ in range(rounds):
        g = E.new_game(["a", "b"], rng, opener=0, mode=mode)
        # Straight to play on a floor contract: this is about the CARDS.
        if mode == "skat":
            E.apply_skat_bid(g, 0, E.SKAT_BASE[2] * 2)
            E.apply_pass(g, 1)
            E.apply_hand(g, 0)
            E.apply_declare(g, 0, 2, 2)
            E.apply_kontra(g, 1, False)
        else:
            E.apply_bid(g, 0, 1, 2)
            E.apply_pass(g, 1)
            if not E.has_dummy(mode):
                E.apply_swap(g, 0, None, None)
            E.apply_double(g, 1, False)
        while g["phase"] == "play":
            seat = E.playing_seat(g)
            pos = E.to_play(g)
            n = len(E.legal_moves(g, seat))
            counts.append(n)
            plies += 1
            forced += (n == 1)
            by_pos.setdefault(pos, []).append(n)
            E.apply_play(g, seat, bot.choose_card(g, seat))
    return {
        "choices": statistics.mean(counts),
        "forced": forced / plies,
        "plies": plies / rounds,
        "by_pos": {k: statistics.mean(v) for k, v in sorted(by_pos.items())},
    }


def hand_spread(mode: str, rounds: int, seed: int = 9):
    """How far apart two hands sit on the auction's single axis, relative to
    how much the axis moves at all. A tight cluster means every hand looks the
    same to the auction, whatever the ladder does."""
    rng = random.Random(seed)
    best, gaps = [], []
    for _ in range(rounds):
        g = E.new_game(["a", "b"], rng, opener=0, mode=mode)
        denoms = E.SKAT_DENOMS if mode == "skat" else range(E.NOTRUMP + 1)
        s0 = max(bot.hand_strength(g, 0, d) for d in denoms)
        s1 = max(bot.hand_strength(g, 1, d) for d in denoms)
        best.append(s0)
        gaps.append(abs(s0 - s1))
        # ...and how much a seat's OWN best denomination beats its worst: the
        # room the auction has to express "I want THIS game, not that one".
        per = [bot.hand_strength(g, 0, d) for d in denoms]
        gaps.append(gaps[-1])
        best.append(max(per) - min(per))
    return {"sd": statistics.pstdev(best[::2]),
            "mean_gap": statistics.mean(gaps[::2]),
            "denom_range": statistics.mean(best[1::2])}


def main(n: int) -> None:
    print(f"\n== agency: do players get decisions? ({n} rounds a mode) ==")
    print("choices = mean legal cards at a decision (2.0 means a coin flip)")
    print("forced  = share of plies with exactly ONE legal card")
    print(f"\n{'mode':>9} {'hand/piles':>11} {'on rails':>9} "
          f"{'choices':>8} {'forced':>7} {'plies':>6}")
    for mode in ("classic", "skat", "dummy"):
        _, in_hand, _, _ = E.layout_for(mode)
        rails = 6 / (in_hand + 6)
        a = agency(mode, n)
        print(f"{mode:>9} {f'{in_hand}+6':>11} {100 * rails:>8.0f}% "
              f"{a['choices']:>8.2f} {100 * a['forced']:>6.0f}% {a['plies']:>6.0f}")

    print(f"\n  dummy, by seat position (0/1 = players, 2 = the dummy):")
    print("   ", agency("dummy", n)["by_pos"])

    print(f"\n== how differently do two hands look to the auction? ==")
    print(f"{'mode':>9} {'strength sd':>12} {'mean gap':>9} {'denom range':>12}")
    for mode in ("classic", "skat", "dummy"):
        h = hand_spread(mode, n)
        print(f"{mode:>9} {h['sd']:>12.2f} {h['mean_gap']:>9.2f} "
              f"{h['denom_range']:>12.2f}")
    print("\ndenom range = how much a seat's best denomination beats its worst.")
    print("Near zero means every game looks alike to a hand, so 'which game do")
    print("I want to play' is not a question the auction can be about.")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
