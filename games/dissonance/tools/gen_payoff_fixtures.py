"""The scoring rule as a table, for the Rust solver to be held to.

The Hard tier's search now maximises the CONTRACT PAYOFF rather than trick
points, which means `dd::Contract::payoff` has to agree with `engine.payoff`
about every outcome. It is a third parity surface after card play and the wire
view, and the quietest of the three: a solver optimising a payoff that is
slightly wrong still returns a legal card, still looks like it is thinking, and
simply plays worse than the tier claims.

The terms themselves are SHIPPED, not reimplemented — `_ai_search` carries
`engine.payoff_terms` to the browser — so this pins the one thing that is
genuinely written twice: the arithmetic that turns terms plus an outcome into a
number.

    PYTHONPATH=<repo root> python -m games.dissonance.tools.gen_payoff_fixtures \\
        > games/dissonance/tests/fixtures/payoff.jsonl

Committed, like the other fixtures — CI runs cargo with no Python available.
"""

from __future__ import annotations

import json
import random
import sys

from games.dissonance import engine as E


def _contracts():
    """Real settled contracts, not hand-written term dicts — so the fixture
    covers the levels, stakes and multiplier stacks the game can actually
    produce rather than the ones someone remembered to type."""
    for level in range(E.MIN_LEVEL, E.MAX_LEVEL + 1):
        for denom in range(E.NOTRUMP + 1):
            g = E.new_game(["a", "b"], random.Random(level * 8 + denom), opener=0)
            E.apply_bid(g, 0, level, denom)
            E.apply_pass(g, 1)
            E.apply_swap(g, 0, None, None)
            yield g
    for value, denom, level in ((12, 2, 4), (20, 0, 4), (36, 4, 6), (2, 1, 1)):
        for hand in (False, True):
            for sharp in (False, True):
                for kontra in (False, True):
                    g = E.new_game(["a", "b"], random.Random(value * 4 + level),
                                   opener=0, mode="skat")
                    E.apply_skat_bid(g, 0, value)
                    E.apply_pass(g, 1)
                    if hand:
                        E.apply_hand(g, 0)
                    else:
                        E.apply_look(g, 0)
                        E.apply_swap(g, 0, None, None)
                    E.apply_declare(g, 0, denom, level, sharp, False)
                    E.apply_kontra(g, 1, kontra)
                    if kontra:
                        E.apply_re(g, 0, True)
                    yield g


def main() -> None:
    out = []
    for g in _contracts():
        terms = E.payoff_terms(g)
        # Every total the round can reach, and both sides of the Null cliff.
        rows = [[p, s, E.payoff(terms, p, s)]
                for p in range(-7, 13) for s in (False, True)]
        out.append(json.dumps({"mode": E.mode_of(g), "terms": terms, "rows": rows},
                              separators=(",", ":")))
    sys.stdout.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
