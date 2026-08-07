"""A `:hover` fill must never out-specify the SELECTED state it sits next to.

THIS ALSO FAILS SILENTLY, and worse than the token bug in `test_css_tokens.py`:
there, the selected button lost its background everywhere and at least looked
uniformly wrong. Here it looks perfect until you interact with it.

The mechanism, measured in Chromium rather than reasoned about:

    .dis-denoms button:hover:not(:disabled)  ->  (0,3,1)   grey fill
    .dis-denoms button.on                    ->  (0,2,1)   the accent

`:not()` contributes its ARGUMENT's specificity, so `:not(:disabled)` quietly
buys the hover rule a third class-level point and it beats `.on`. The selected
button repaints grey while `.on`'s near-black `color` still applies — the exact
unreadable pairing `--accent` was defined to fix, arriving by a different road.

**On a phone it is permanent, not transient.** `:hover` latches to the last
element tapped until you tap elsewhere (the same iOS behaviour Dontminion
already documents, and that Dissonance's own card rules are guarded for), so
the suit you just picked stays grey for the rest of the auction. Reported from
a phone: the number green, the suit not.

WHY A STATIC TEST AND NOT JUST THE BROWSER GATE. `screens.mjs` now hovers the
selected button too, but it can only check the families that are ON SCREEN in
the phase it happens to be in — and its Dissonance auction is SKAT, which bids
a number and shows no suit row. So the live gate covers `.dis-valgrid`, which
was the one family that was never broken: it ties on specificity and keeps its
colour purely because `.on` comes second in source order. Luck, not design.
This test covers every family at once and cannot be dodged by phase.

WHAT IT CHECKS: within one stylesheet, any `:hover` rule that sets `background`
and whose selector could also match an element carrying `.on` must exclude it
with `:not(.on)`. Narrow on purpose — it says nothing about rules that do not
paint a background, and nothing about states other than `.on`.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The selected-state class this repo uses for toggles/pickers.
SELECTED = ".on"


def _sheets():
    out = sorted((REPO / "games").rglob("*.css")) + sorted((REPO / "shared").rglob("*.css"))
    assert out, "no stylesheets found — this guard has rotted"
    return out


def _rules(css: str):
    """(selector, body) per rule. Comments are stripped FIRST — several sheets
    discuss `:hover` in prose, and this file does too."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def _base(part: str) -> str:
    """The selector with its pseudo-classes stripped — what it matches BEFORE
    hovering. `.dis-denoms button:hover:not(:disabled)` -> `.dis-denoms button`."""
    return re.sub(r":(?:hover|not\([^()]*\)|active|focus(?:-visible)?)", "", part).strip()


def _offenders(css: str):
    """A hover rule is only an offender if the SAME sheet paints a background on
    the SELECTED version of the very same elements. Pairing on the base selector
    is what makes this precise: `.coc-btn.gold:hover` looks identical in shape but
    has no `.coc-btn.gold.on` anywhere, so demanding `:not(.on)` there would be a
    test inventing work. Only a real (hover, selected) pair on one base can
    conflict, and then the hover ALWAYS wins — it has strictly more
    pseudo-classes, hence strictly higher specificity."""
    painted_on = set()          # base selectors that have a `.on` background rule
    hovers = []                 # (base, full selector) for hover backgrounds
    for selector, body in _rules(css):
        if "background" not in body:
            continue
        for part in (p.strip() for p in selector.split(",")):
            if ":hover" in part:
                if SELECTED not in part:        # already excluded => safe
                    hovers.append((_base(part), part))
            elif part.endswith(SELECTED):
                painted_on.add(part[: -len(SELECTED)].strip())
    return [full for base, full in hovers if base in painted_on]


def test_no_hover_fill_can_override_a_selected_button():
    found = {}
    for sheet in _sheets():
        offenders = _offenders(sheet.read_text(encoding="utf-8"))
        if offenders:
            found[sheet.relative_to(REPO).as_posix()] = offenders
    assert not found, (
        "a :hover background can repaint a SELECTED button here:\n"
        + "\n".join(f"  {s}\n    " + "\n    ".join(sel for sel in sels) for s, sels in found.items())
        + "\n\nAdd `:not(.on)` to the hover selector. `:hover` latches to the last "
          "tapped element on touch, so this is a permanent wrong colour on a phone, "
          "not a transient one."
    )


def test_the_guard_actually_fires():
    """Anti-vacuity — the whole file passes just as happily if `_rules` stops
    parsing or the offender test inverts, and a green tick over nothing is the
    failure mode this repo keeps paying for."""
    broken = ".x button:hover:not(:disabled) { background: #fff; }\n.x button.on { background: red; }"
    assert _offenders(broken) == [".x button:hover:not(:disabled)"]

    fixed = ".x button:hover:not(:disabled):not(.on) { background: #fff; }\n.x button.on { background: red; }"
    assert _offenders(fixed) == []

    # A hover rule that paints nothing is not this test's business.
    assert _offenders(".x button:hover { transform: scale(1.1); }") == []
    # ...and prose about :hover must not register as a rule.
    assert _offenders("/* .x button:hover { background: #fff } */ .y { color: red }") == []
