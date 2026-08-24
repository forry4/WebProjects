"""The swap-policy ARITHMETIC, held to one answer in both languages.

The fitted swap weights cross the wire (`bot.swap_policy_terms` ->
`bid::SwapPolicy`), so the numbers live once -- but the FEATURES (trumpness,
void, singleton, take-suit length) are arithmetic that exists in both
`bot.choose_swap`'s classic branch and `SwapPolicy::choose`. Two
implementations of one function drift silently; this pins them.

Each row is a synthetic decision -- a 7-card hand, 3 shown cards, a trump --
plus Python's answer. The first line carries the weights themselves, so the
Rust replay builds its policy from the fixture and the test never grows its
own copy of the constants. `shown` is emitted SORTED and the Rust side
iterates ascending card id, which makes the two tie-breaks identical (Python's
is first-strict-max in iteration order).

    PYTHONPATH=<repo root> python -m games.dissonance.tools.gen_swap_fixtures \\
        > games/dissonance/tests/fixtures/swap_policy.jsonl

Committed, like every parity fixture -- CI runs cargo with no Python available.
"""

from __future__ import annotations

import json
import random
import sys

from games.dissonance import bot as B
from games.dissonance import engine as E


def main() -> None:
    rng = random.Random(818118)
    rows = [json.dumps({"policy": B.swap_policy_terms()}, separators=(",", ":"))]
    for i in range(400):
        deck = list(range(E.NCARD))
        rng.shuffle(deck)
        hand = sorted(deck[:7])
        shown = sorted(deck[7:10])
        # Classic denominations only -- the policy is gated to classic rooms and
        # 0..4 is what its auction can name. (Grand is skat's.)
        denom = rng.randrange(E.NOTRUMP + 1)
        g = {"auction": {"denom": denom, "level": rng.randint(1, 8)},
             "hands": [hand, []], "shown": shown}
        sw = B.choose_swap(g, 0)
        rows.append(json.dumps({"hand": hand, "shown": shown, "denom": denom,
                                "take": sw["take"], "give": sw["give"]},
                               separators=(",", ":")))
    # STAND PAT is a branch, and 400 random rows produced zero of it -- random
    # talons almost always offer something. Engineer it: middle-rank talons
    # against hands of honours, the shape where every exchange scores <= 0.
    pats = 0
    for i in range(4000):
        suits = [rng.randrange(4) for _ in range(7)]
        # `suit * NRANK + k` is the base deck's ID layout, where k runs 0..7 for
        # 7..A -- so 5/6/7 here are Q/K/A. IDs, not `E.rank` values: those are
        # strength indices over the wide deck's ten ranks and sit two higher.
        hand = sorted({s_ * E.NRANK + r for s_, r in zip(suits, [5, 6, 7, 6, 7, 5, 6])})
        if len(hand) != 7:
            continue
        pool = [c for c in range(E.NCARD) if c not in hand and E.rank(c) in (3, 4, 5)]
        rng.shuffle(pool)
        shown = sorted(pool[:3])
        denom = rng.randrange(E.NOTRUMP + 1)
        g = {"auction": {"denom": denom, "level": 4}, "hands": [hand, []],
             "shown": shown}
        sw = B.choose_swap(g, 0)
        rows.append(json.dumps({"hand": hand, "shown": shown, "denom": denom,
                                "take": sw["take"], "give": sw["give"]},
                               separators=(",", ":")))
        pats += sw["take"] is None
        if pats >= 25:
            break
    assert pats >= 10, f"only {pats} stand-pat rows -- the branch is uncovered"
    sys.stdout.write("\n".join(rows) + "\n")


if __name__ == "__main__":
    main()
