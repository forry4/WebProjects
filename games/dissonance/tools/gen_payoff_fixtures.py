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
    # ...to the LADDER'S top, not MAX_LEVEL: classic caps at 10, and a loop to
    # 12 dies on an unbiddable opening (found 2026-08-11, regenerating for the
    # flat stake -- the fixture had sat committed since the cap landed).
    for level in range(E.MIN_LEVEL, E.max_level_for("classic") + 1):
        for denom in range(E.NOTRUMP + 1):
            g = E.new_game(["a", "b"], random.Random(level * 8 + denom), opener=0)
            E.apply_bid(g, 0, level, denom)
            E.apply_pass(g, 1)
            E.apply_swap(g, 0, None, None)
            yield g
    # CLASSIC REACHED BY A JUMP (2026-08-13): the raise cap is gone and the
    # FINAL bid's rise pays the defender JUMP_SET_BONUS per level on a set --
    # folded inside `set_base`, inside the Double. Real jumped auctions, both
    # Doubled and not, because a fixture set holding only passed-out openings
    # would never price the fold and the solver would be held to nothing here.
    for opening, level, denom, doubled in ((1, 4, 1, False), (2, 7, 3, True),
                                           (1, 10, 4, False), (3, 5, 2, True)):
        g = E.new_game(["a", "b"], random.Random(level * 32 + denom), opener=0)
        E.apply_bid(g, 0, opening, 0)
        E.apply_bid(g, 1, level, denom)
        E.apply_pass(g, 0)
        E.apply_swap(g, 1, None, None)
        E.apply_double(g, 0, doubled)
        yield g
    # MINOR: the same classic shape on the re-anchored prices (Null 6, set
    # rate 2, ladder 1..6), both Doubled and not -- a fixture set that never
    # priced a minor contract would leave the solver held to nothing there.
    for level in range(E.MIN_LEVEL, E.MINOR_MAX_LEVEL + 1):
        for denom in range(E.NOTRUMP + 1):
            for doubled in (False, True):
                g = E.new_game(["a", "b"], random.Random(level * 16 + denom),
                               opener=0, mode="minor")
                E.apply_bid(g, 0, level, denom)
                E.apply_pass(g, 1)
                E.apply_swap(g, 0, None, None)
                E.apply_double(g, 1, doubled)
                yield g
    # DERIVE the level from the bid rather than writing the pair out. Hand-typed
    # levels rot the moment the bases move: three of the four here stopped
    # reaching their bid when the denominations were re-priced by colour, and
    # because CI does not run cargo the stale fixture sat committed and unnoticed.
    # `+ raise_` covers declaring ABOVE the minimum, which is where the overtrick
    # bonus and the shortfall are measured from different targets.
    # Every denomination ON THE LADDER appears, Grand included -- its base is
    # what the stake is built from, so a denomination missing here is a whole
    # column of the price table the solver is never held to.
    for value, denom, raise_ in ((12, 2, 0), (20, 0, 0), (36, 4, 0), (2, 1, 0),
                                 (12, 3, 2), (6, 1, 3),
                                 (12, E.GRAND, 0), (20, E.GRAND, 2)):
        level = min(E.MAX_LEVEL, E.skat_min_level(denom, value) + raise_)
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


#: SYNTHETIC RAMPED TERMS, because the shipped `DOUBLE_RAMP` is 0 (retired
#: 2026-08-16) and the ramp arithmetic still exists in BOTH implementations --
#: `E.payoff`'s `ramp x s(s+1)//2` and `dd::Contract::payoff`'s `ramp * s * (s+1)
#: / 2`. Generating only reachable contracts would leave that term at ramp=0 on
#: every row, so the two copies could silently diverge and the gate would pass:
#: a term nothing exercises is a term nobody is holding to anything. These rows
#: are NOT reachable game states and are not claimed to be -- they exist purely
#: to pin one shared formula, which is what this fixture set is for.
_RAMPED = [
    {"denom": 0, "level": 3, "target": 3, "make": 26, "over": 2,
     "set_base": 28, "short": 5, "ramp": 1, "null": 20, "declarer": 0},
    {"denom": 2, "level": 6, "target": 6, "make": 80, "over": 2,
     "set_base": 40, "short": 5, "ramp": 2, "null": 20, "declarer": 1},
    {"denom": 4, "level": 1, "target": 1, "make": 10, "over": 2,
     "set_base": 20, "short": 4, "ramp": 3, "null": 20, "declarer": 0},
]


def main() -> None:
    out = []
    for terms in _RAMPED:
        rows = [[p, s, E.payoff(terms, p, s)]
                for p in range(-7, 13) for s in (False, True)]
        out.append(json.dumps({"mode": "classic", "terms": terms, "rows": rows},
                              separators=(",", ":")))
    for g in _contracts():
        terms = E.payoff_terms(g)
        # Every total the round can reach, and both sides of the Null cliff.
        # Card scoring (skat, 2026-08-09) reaches a much wider range than the
        # parity pool: the whole deck is worth 16 gross of the out-cards, and
        # a total is bounded by the captured cards' extremes.
        lo, hi = ((-12, 25) if E.uses_card_points(E.mode_of(g)) else (-7, 13))
        rows = [[p, s, E.payoff(terms, p, s)]
                for p in range(lo, hi) for s in (False, True)]
        out.append(json.dumps({"mode": E.mode_of(g), "terms": terms, "rows": rows},
                              separators=(",", ":")))
    sys.stdout.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
