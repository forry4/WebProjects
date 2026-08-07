"""The shared lobby kit is a CONTRACT, and this is the only thing enforcing it.

`shared/lobby.jsx` + its stylesheet own the whole lobby: the column grid, the
card rows, the empty states, the phone tab bar. A game opts in by using the
kit's class names — and nothing checked that it actually did, so Oddtrick
shipped a lobby using `lby-cardmain`, `lby-cardsub`, `lby-cardtitle`, `lby-col`
and `lby-history`, none of which exist in the shared sheet. Every one of those
rows rendered completely unstyled, and it looked like a theming problem rather
than five typos.

Read as TEXT, the way `core/tests/test_history_limit.py` reads the same file:
CI has no browser here, and a class name that is never defined is a static
fact about the source, not something that needs rendering to see.

`screens.mjs` covers what these files LOOK like; this covers whether a new game
is wired into the kit at all. Neither subsumes the other — a game can render a
perfectly fine-looking lobby out of its own private classes, which is exactly
what happened.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared"


def _shared_css() -> str:
    return "\n".join(p.read_text(encoding="utf-8")
                     for p in sorted(SHARED.glob("*.css")))


def _lobby_games() -> list[pathlib.Path]:
    """Every game screen that renders the shared column grid."""
    out = [p for p in sorted((ROOT / "games").glob("*/[A-Z]*.jsx"))
           if "lby-cols" in p.read_text(encoding="utf-8")]
    # Derived from the tree, never hardcoded: a hardcoded roster is how the next
    # game gets added without anything noticing (the Dontminion lesson).
    assert len(out) >= 5, f"expected the lobby games, found {[p.name for p in out]}"
    return out


def test_every_lby_class_a_game_uses_is_one_the_shared_sheet_defines():
    css = _shared_css()
    defined = set(re.findall(r"\.(lby-[a-z0-9-]+)", css))
    # Custom properties are used as `var(--lby-accent)`, not as classes.
    defined |= set(re.findall(r"--(lby-[a-z0-9-]+)", css))
    assert "lby-card-info" in defined and "lby-col-active" in defined, \
        "the stylesheet moved; this test is reading the wrong thing"

    problems: dict[str, set[str]] = {}
    for jsx in _lobby_games():
        used = set(re.findall(r"\b(lby-[a-z0-9-]+)", jsx.read_text(encoding="utf-8")))
        unknown = used - defined
        if unknown:
            problems[jsx.name] = unknown
    assert not problems, (
        "these lobby classes are not defined anywhere in shared/*.css, so they "
        f"render unstyled: {problems}")


def test_a_lobby_pins_all_three_columns():
    """Grid auto-flow follows DOM order, so an unpinned column lands wherever the
    JSX happens to emit it — and the phone tab bar hides columns by these exact
    class names, so an unpinned one cannot be shown or hidden at all."""
    for jsx in _lobby_games():
        text = jsx.read_text(encoding="utf-8")
        for cls in ("lby-col-open", "lby-col-active", "lby-col-history"):
            assert cls in text, f"{jsx.name} renders .lby-cols without .{cls}"


def test_the_phone_tab_bar_is_wired_to_the_grid():
    """Two halves that must agree, and neither fails loudly on its own.

    `LobbyTabs` reads `t.key`; a game passing `id` renders a bar whose every
    click sets the tab to `undefined`. The grid hides columns off a `tab-<key>`
    CLASS; a game setting `data-tab` matches no rule, so nothing hides. Oddtrick
    did both, and the result was a tab bar that looked right, changed nothing,
    and left all three sections stacked on a phone.
    """
    for jsx in _lobby_games():
        text = jsx.read_text(encoding="utf-8")
        if "LobbyTabs" not in text:
            continue
        # Read a window around the grid rather than one literal shape: the five
        # games spell the same className three different ways (template literal,
        # string concat, and with a game-specific class in front), and a regex
        # pinned to one of them fails the other two for no reason.
        near = [text[max(0, m.start() - 200):m.end() + 200]
                for m in re.finditer(r"lby-cols", text)]
        assert any("tab-" in w for w in near), \
            f"{jsx.name} must put a tab-<key> class on .lby-cols"
        # `data-tab=` with the equals, i.e. the ATTRIBUTE — the bare string also
        # appears in a comment explaining why not to use it, and a test that
        # cannot tell those apart makes the explanation unwritable.
        assert "data-tab=" not in text, \
            f"{jsx.name} sets data-tab; the CSS hides columns off a CLASS, so it matches no rule"
        tabs = re.search(r"<LobbyTabs[\s\S]{0,600}?/>", text)
        assert tabs, f"{jsx.name} renders LobbyTabs in a shape this test cannot read"
        assert "key:" in tabs.group(0), \
            f"{jsx.name} passes tabs without `key:` — LobbyTabs reads t.key, not t.id"


def test_each_lobby_sets_its_own_accent():
    """`--lby-accent` falls back to Spender's gold, so a game that forgets it
    wears another game's colour rather than rendering visibly wrong."""
    missing = []
    for jsx in _lobby_games():
        game_dir = jsx.parent
        sheets = "\n".join(p.read_text(encoding="utf-8") for p in game_dir.glob("*.css"))
        if "--lby-accent" not in sheets + jsx.read_text(encoding="utf-8"):
            missing.append(jsx.name)
    assert not missing, f"no --lby-accent, so these inherit the default gold: {missing}"


def test_every_game_uses_the_shared_in_game_menu():
    """At a board, the header is ONE hamburger, never a row of buttons.

    Oddtrick was the last game still showing Back + Rules in its in-game header
    while the other five used `GameMenu` — and it already imported `GameMenu`
    without ever rendering it, which is the shape this catches. `LobbyHeader`
    takes a `menu` node for exactly this; `onBack`/`onRules` stay for the lobby,
    where a plain Back is right.
    """
    missing = [jsx.name for jsx in _lobby_games()
               if "<GameMenu" not in jsx.read_text(encoding="utf-8")]
    assert not missing, (
        "these render a game board without the shared ☰ menu: " f"{missing}")


def test_the_in_game_menu_offers_the_same_three_actions():
    """Return / rules / abandon, in that order, on every game that can be
    abandoned. A game that quietly drops one leaves players with no way out of a
    live room except closing the tab — Oddtrick's server had supported abandon
    since it shipped, with nothing in the UI ever calling it."""
    for jsx in _lobby_games():
        text = jsx.read_text(encoding="utf-8")
        # A window after the tag, not a closing-delimiter match: the six games
        # format the items array six different ways and a regex that has to find
        # the end of it fails on formatting rather than on substance.
        at = text.find("<GameMenu")
        assert at >= 0, f"{jsx.name} does not render GameMenu"
        body = text[at:at + 900]
        assert re.search(r"Return to (menu|lobby)", body), \
            f"{jsx.name}'s menu has no way back to the lobby"
        assert "rules" in body.lower(), f"{jsx.name}'s menu does not offer the rules"
