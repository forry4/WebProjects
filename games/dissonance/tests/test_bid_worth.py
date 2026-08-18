"""The client prices contracts ITSELF — guard that second copy.

`pricing.js` renders "makes 29 · down for 23" beside the bid keys, the Kontra
prompt's now/doubled table, the contract box's "set pays" row, the result
panel's maths line and every row of the paper scorecard, which means the
make/set curve is written twice: once in `engine._terms_for`, once in the
client. Nothing at runtime notices when they
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

JSX = Path(__file__).resolve().parents[1] / "pricing.js"
BOARD = Path(__file__).resolve().parents[1] / "Dissonance.jsx"
CARD = Path(__file__).resolve().parents[1] / "scorecard.jsx"

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
    # THE DOUBLE'S DIALS. The same panel prices a Kontra -- the prompt's
    # now/doubled table, the contract box's "set pays" row and the result
    # panel's maths line -- and those three spent months printing a flat x2 on
    # both bases plus the retired shortfall ramp, i.e. a rule the game had
    # stopped applying. Served and read for the same reason as the curve above.
    "double_make_mult": lambda: E.DOUBLE_MAKE_MULT,
    "double_base_mult": lambda: E.DOUBLE_BASE_MULT,
    "double_jump_mult": lambda: E.DOUBLE_JUMP_MULT,
    "jump_doubled": lambda: E.JUMP_DOUBLED,
    "doubled_short_penalty": lambda: E.DOUBLED_SHORT_PENALTY,
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
    body = src[src.index("const price = ("):]
    body = body[:body.index("\n\t};") + 4]
    for name in ("flatMake", "flatSet", "setRate", "linMake", "jumpBonus",
                 "dblMake", "dblBase", "dblJump", "dblShort"):
        assert name in body, f"the price function no longer uses {name!r} -- hardcoded?"
    for key in TERMS:
        assert re.search(rf"catalog\?\.{key}\b", src), \
            f"{key!r} is no longer read from the catalog in pricing.js"
    # `double_ramp` is a scalar rather than a per-mode dict, so it is read
    # without the `?.[mode]` the others carry -- and it is what decides whether
    # the shortfall row prints a flat rate or a rising sequence.
    assert re.search(r"catalog\?\.double_ramp\b", src), \
        "double_ramp is no longer read from the catalog in pricing.js"


def test_nothing_outside_the_mirror_prices_a_contract():
    """ONE copy, and it is `pricing.js`.

    The board and the scorecard must both go through it -- a screen that starts
    multiplying a level by itself is a second price list, which is the whole
    failure this module exists to catch and the reason the mirror was pulled out
    of `Dissonance.jsx` in the first place.
    """
    for path in (BOARD, CARD):
        src = path.read_text(encoding="utf-8")
        for key in TERMS:
            assert not re.search(rf"catalog\?\.{key}\b", src), \
                f"{path.name} reads {key!r} directly -- price through pricing.js"
        assert "contractPrices" in src or "prices.price" in src, \
            f"{path.name} no longer imports the shared price list"


def test_the_panels_price_the_double_the_way_the_engine_does():
    """The doubled arm of the same mirror -- the one that had actually drifted.

    Written like the undoubled test below it: a throwaway copy of the JSX line
    for line, so an engine move that leaves the client behind fails here with
    both numbers rather than on a screen nobody is diffing.
    """
    m = "classic"
    fm, fs = E.FLAT_MAKE_BONUS[m], E.FLAT_SET_PENALTY[m]
    sr, lm, jb = E.SET_LEVEL_RATE[m], E.LINEAR_MAKE_BONUS[m], E.JUMP_SET_BONUS[m]
    mm = E.DOUBLE_MAKE_MULT.get(m, 2)
    bm = E.DOUBLE_BASE_MULT.get(m, 2)
    jm = E.DOUBLE_JUMP_MULT.get(m, bm if E.JUMP_DOUBLED.get(m, True) else 1)
    sh = E.DOUBLED_SHORT_PENALTY.get(m, E.CLASSIC_SHORT_PENALTY)
    for level in range(1, E.max_level_for(m) + 1):
        for jump in (0, 1, level):
            terms = E._terms_for(m, 0, level, jump=jump, doubling=2)
            make = (level * level + lm * level + fm) * mm
            base = (sr * level + fs) * bm + jb * max(0, jump) * jm
            assert make == terms["make"], f"L{level} j{jump}: make {make} vs {terms['make']}"
            assert base == terms["set_base"], \
                f"L{level} j{jump}: set base {base} vs {terms['set_base']}"
            assert sh == terms["short"], f"L{level}: short {sh} vs {terms['short']}"
            # …and the row the Kontra prompt draws its "per point short" from is
            # the rate itself, so a ramp coming back would have to move this.
            assert terms.get("ramp", 0) == E.DOUBLE_RAMP


def test_the_scorecards_payoff_matches_the_engine():
    """`payoffFor` in `pricing.js`, held against `engine.payoff`.

    The paper scorecard is the one screen that computes a SCORE rather than
    quoting one -- nothing it shows was ever settled by the server -- so its
    arithmetic is the copy with no second opinion anywhere. Same throwaway-copy
    style as the tests around it: written to match the JS line for line.
    """
    m = "classic"
    for level in range(1, E.max_level_for(m) + 1):
        for jump in (0, 1, level):
            for doubling in (1, 2):
                terms = E._terms_for(m, 0, level, jump=jump, doubling=doubling)
                for pts in range(-7, 13):
                    p = terms
                    # The JS: Null first and flat, then make + over x overtricks,
                    # else -(set base + short x shortfall + the ramp's triangle).
                    want = E.payoff(terms, pts, True)
                    got = (p["make"] + p["over"] * (pts - level) if pts >= level
                           else -(p["set_base"] + p["short"] * (level - pts)
                                  + p.get("ramp", 0) * (level - pts) * (level - pts + 1) // 2))
                    assert got == want, f"L{level} j{jump} x{doubling} pts {pts}"
                assert E.payoff(terms, -3, False) == terms["null"]
    # ...and the JS really is that function. The loop above is a Python copy of
    # it, so on its own it would only ever agree with itself; this is what ties
    # the copy to the file it claims to mirror.
    body = JSX.read_text(encoding="utf-8")
    body = body[body.index("export function payoffFor"):]
    for frag in ("nullMade", "prices.nullMake", "p.make + p.over * (pts - level)",
                 "p.setBase + p.short * s", "p.ramp * s * (s + 1)"):
        assert frag in body, f"payoffFor no longer contains {frag!r}"


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
            # short, which is what "down for" claims on screen.
            assert down == -E.payoff(terms, level - 1, True), \
                f"L{level} j{jump}: down {down} vs {-E.payoff(terms, level - 1, True)}"
