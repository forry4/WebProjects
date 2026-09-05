"""The three reserved cards must stay on ONE row, at every width.

This is a CSS-TEXT test on purpose, and the reason is the whole point of the file.
The bug it guards was: `.duel-player` is a container-query container AND, on desktop,
a vertical scroll container (`overflow-y:auto`). Chrome does not subtract a classic
scrollbar from the container-query size, so a scrolling box reported `100cqw` about
17px wider than the row it actually contained; the reserved cards are sized at exactly
`(100cqw - 24px) / 3` with `flex-shrink:0`, so the third one wrapped onto a second row.
Reported on Chrome/Windows at 2560x1600.

`npm run screens` CANNOT see it. Its headless Chromium uses OVERLAY scrollbars, which
are 0px wide, so the discrepancy that causes the wrap does not exist there — the bug
reproduces only in a headed browser on a platform with classic scrollbars. An assertion
in that harness would be a green tick over a thing it never measured, which is exactly
the shape this repo has paid for before. What IS checkable without a browser is that the
three declarations holding the row together are still written down.
"""

from __future__ import annotations

import pathlib
import re

CSS = (pathlib.Path(__file__).resolve().parents[1] / "SpenderDuel.css").read_text(encoding="utf-8")


def _rules(selector_contains: str) -> list[tuple[str, str]]:
    """(selector, body) for every rule whose selector mentions `selector_contains`.

    Comments are stripped first: this sheet documents its own footguns at length,
    and a text search that reads them finds `overflow-y:auto` in prose. (The same
    lesson as `core/tests/test_no_conditional_skips.py` parsing the AST rather than
    grepping — here a comment strip is enough, since CSS has no nested rules.)
    """
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    return [(m.group(1).strip(), m.group(2))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)
            if selector_contains in m.group(1)]


def _decls(body: str) -> dict[str, str]:
    out = {}
    for part in body.split(";"):
        if ":" in part:
            k, _, v = part.partition(":")
            out[k.strip()] = v.strip()
    return out


def test_the_reserved_row_never_wraps():
    wraps = [(sel, _decls(body)["flex-wrap"])
             for sel, body in _rules(".duel-reserved-row")
             if "flex-wrap" in _decls(body)]
    assert wraps, "no rule sets flex-wrap on .duel-reserved-row — the row can wrap again"
    assert all(v == "nowrap" for _, v in wraps), (
        f"the reserved row must never wrap; found {wraps}. Three reserves are the maximum "
        "the rules allow and they read as one hand — a fourth line is the bug, not a fallback."
    )


def test_a_reserved_card_can_shrink_to_the_row_it_is_actually_in():
    """The belt to scrollbar-gutter's braces: any few-px over-report of 100cqw
    (a scrollbar, sub-pixel rounding, a wider scrollbar theme) must cost width,
    never a second row. The shared `.card` is flex-shrink:0 and its automatic
    minimum is its MIN-CONTENT width — measured at 86-99% of the assigned width
    for the 3-crown card — so BOTH have to be overridden here."""
    # The CARD itself, not its innards: `.duel-reserved-row .card.card-small .card-points`
    # also carries a min-width:0 (for a different reason), and reading that one instead
    # made this assertion pass with the card's own min-width deleted.
    found = {}
    for sel, body in _rules(".duel-reserved-row"):
        if sel.split(".duel-reserved-row")[-1].strip() != ".card.card-small":
            continue
        found.update({k: v for k, v in _decls(body).items()
                      if k in ("flex-shrink", "min-width")})
    assert found.get("flex-shrink") == "1" and found.get("min-width") == "0", (
        "`.duel-reserved-row .card.card-small` must set flex-shrink:1 and min-width:0; "
        f"found {found or 'neither'}"
    )


def test_a_scrolling_player_box_reserves_its_scrollbar_gutter():
    """.duel-player is a container-query container, so the moment it also becomes a
    scroll container its 100cqw starts lying by the scrollbar's width. A reserved
    gutter IS subtracted from cqw, which makes the arithmetic honest again (and stops
    every card in the rail resizing when the scrollbar appears). So: wherever this
    sheet makes .duel-player scroll, it must reserve the gutter in the same rule."""
    scrollers = [(sel, _decls(body)) for sel, body in _rules(".duel-player")
                 if _decls(body).get("overflow-y") in ("auto", "scroll")
                 or _decls(body).get("overflow") in ("auto", "scroll")]
    assert scrollers, (
        "no rule makes .duel-player a scroll container — either the desktop rail "
        "layout changed or this test is reading the wrong file"
    )
    missing = [sel for sel, d in scrollers if d.get("scrollbar-gutter") != "stable"]
    assert not missing, (
        "these rules make .duel-player scroll without reserving the scrollbar gutter, "
        f"so 100cqw over-reports the row and the third reserved card wraps: {missing}"
    )
