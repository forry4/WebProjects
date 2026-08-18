"""The auction panel prices a bid BEFORE it is made — guard that second copy.

`priceBid` in `Dissonance.jsx` renders "makes 29 · down from 23" beside the bid
keys, which means the make/set curve is now written twice: once in
`engine._terms_for`, once in the client. Nothing at runtime notices when they
disagree — the server still scores every settled round itself, so a drift here
pays out correctly and simply LIES to the player while they are choosing, which
is the worst place to be wrong and the least likely to be noticed.

Two things are checked, and the split matters:

  1. THE CATALOG SERVES EVERY TERM. The client is only allowed to be right
     because `/catalog` hands it the engine's own dicts; a term that stops being
     served makes the client fall back to a literal and drift silently.
  2. THE CLIENT READS THEM ALL. Asserted as TEXT, because the alternative is a
     JS runtime in the test suite. It cannot catch a reordered formula -- it
     catches the thing that actually happens, which is somebody hardcoding a
     number that was easier to type than to plumb.

What it deliberately does NOT do is re-derive the formula here: a third copy
would need its own guard.
"""
import asyncio
import re
from pathlib import Path

from games.dissonance import engine as E
from games.dissonance import main as M

JSX = Path(__file__).resolve().parents[1] / "Dissonance.jsx"

#: Every scoring term the panel's arithmetic needs, and the catalog key serving
#: it. `classic_short_penalty` is here rather than `short_penalty` on purpose:
#: classic stopped using `SHORT_PENALTY` when `CLASSIC_SHORT_PENALTY` was split
#: out (2026-08-16), and they are both 5 today -- so a client reading the wrong
#: one is invisible until the day the two diverge.
TERMS = {
    "flat_make_bonus": lambda: E.FLAT_MAKE_BONUS,
    "flat_set_penalty": lambda: E.FLAT_SET_PENALTY,
    "set_level_rate": lambda: E.SET_LEVEL_RATE,
    "linear_make_bonus": lambda: E.LINEAR_MAKE_BONUS,
    "jump_set_bonus": lambda: E.JUMP_SET_BONUS,
    "classic_short_penalty": lambda: E.CLASSIC_SHORT_PENALTY,
}


def _catalog():
    return asyncio.run(M.catalog())


def test_the_catalog_serves_every_term_the_panel_prices_with():
    cat = _catalog()
    for key, get in TERMS.items():
        assert key in cat, f"/catalog stopped serving {key!r}"
        assert cat[key] == get(), f"{key!r} does not match the engine"


def test_the_client_reads_every_term_off_the_catalog():
    src = JSX.read_text(encoding="utf-8")
    body = src[src.index("const priceBid"):]
    body = body[:body.index("});") + 3]
    for name in ("flatMake", "flatSet", "setRate", "linMake", "jumpBonus", "shortRate"):
        assert name in body, f"priceBid no longer uses {name!r} -- hardcoded?"
    for key in TERMS:
        assert re.search(rf"catalog\?\.{key}\b", src), \
            f"{key!r} is no longer read from the catalog in Dissonance.jsx"


def test_the_panels_arithmetic_matches_the_engine():
    """The formula the client renders, evaluated here against `_terms_for`.

    A third copy of the curve -- but a THROWAWAY one, written to match the JSX
    line for line, so if the engine moves and the client does not, this fails
    with the two numbers side by side instead of the panel quietly lying.
    """
    m = "classic"
    fm, fs = E.FLAT_MAKE_BONUS[m], E.FLAT_SET_PENALTY[m]
    sr, lm, jb = E.SET_LEVEL_RATE[m], E.LINEAR_MAKE_BONUS[m], E.JUMP_SET_BONUS[m]
    sh = E.CLASSIC_SHORT_PENALTY
    for level in range(1, E.max_level_for(m) + 1):
        for jump in (0, 1, 2, level):
            terms = E._terms_for(m, 0, level, jump=jump, doubling=1)
            make = level * level + lm * level + fm
            down = sr * level + fs + jb * max(0, jump) + sh
            assert make == terms["make"], f"L{level} j{jump}: make {make} vs {terms['make']}"
            # `down` is the CHEAPEST loss: the set base plus exactly one point
            # short, which is what "down from" claims on screen.
            assert down == -E.payoff(terms, level - 1, True), \
                f"L{level} j{jump}: down {down} vs {-E.payoff(terms, level - 1, True)}"
