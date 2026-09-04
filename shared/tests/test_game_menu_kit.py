"""The in-game ☰ menu is ONE menu, and this is the only thing enforcing it.

`GameMenu` in `shared/lobby.jsx` was shared CHROME with per-game CONTENT: it took
an `items` array, and nine call sites each typed out the same three rows. That is
the arrangement this repo has already paid for twice — the lobby card row and the
create button, both of which grew a per-game vocabulary the moment nothing was
watching — and it had drifted here too. Orbit shipped "How to play" ABOVE "Return
to lobby", with `?` and `×` for icons: different words, different glyphs and a
different order from the other eight, in the one control on every game screen
that a player uses to leave.

The menu now builds its own rows from three callbacks, so a game cannot express
that drift. What a test still has to hold is the boundary itself: that no game
goes back to handing in its own rows, and that the labels and glyphs live in
exactly one file. Both are static facts about the source, so this reads the JSX
as TEXT the way `test_lobby_kit.py` and `core/tests/test_history_limit.py` do —
CI has no browser here, and `screens.mjs` covers what the menu LOOKS like rather
than whether a ninth game was wired into the kit at all.

THE ROSTER IS DERIVED FROM THE TREE, never hardcoded. A hardcoded list only ever
guards the tree SHRINKING; the next game joins unguarded, which is the exact
shape of the `range(13)` bug in `docs/`-era Dontminion soak coverage.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
KIT = ROOT / "shared" / "lobby.jsx"

# The words and glyphs a menu row is made of. Every one of these was a per-game
# literal before, and each is a thing a new game would otherwise re-type slightly
# differently. They may appear in `shared/lobby.jsx` and nowhere else.
ROW_LABELS = (
    "Return to menu",
    "View rules",
    "Abandon game",
    "Back to Local Games",
    "Delete game",
)

# Where Wolf has no Abandon and that is deliberate, not an oversight: its
# server-side `abandon` on a game in progress only drops the socket (the player
# is voted in absentia), so there is nothing to forfeit and the row would promise
# an action the game does not have. Same standing as its missing History column.
# A SECOND exemption belongs in this dict with its reason, or it is drift.
NO_ABANDON = {"WhereWolf.jsx": "abandon only drops the socket; players are voted in absentia"}


def _menu_games() -> list[pathlib.Path]:
    """Every game screen that mounts the shared ☰."""
    out = [p for p in sorted((ROOT / "games").glob("*/[A-Z]*.jsx"))
           if "<GameMenu" in p.read_text(encoding="utf-8")]
    assert len(out) >= 8, f"expected every game to mount the menu, found {[p.name for p in out]}"
    return out


def test_no_game_hands_the_menu_its_own_rows():
    """`items=` is gone from the component; passing it must not silently no-op.

    This is the failure mode that matters most, because it is INVISIBLE: React
    drops an unknown prop, so a game that kept its old `items={[…]}` call would
    render a perfectly normal-looking menu built from the shared defaults and the
    author's three carefully-written rows would go nowhere.
    """
    offenders = [p.name for p in _menu_games()
                 if re.search(r"<GameMenu[^>]*\bitems\s*=", p.read_text(encoding="utf-8"))]
    assert not offenders, (
        f"{offenders} pass `items` to GameMenu, which no longer reads it — the rows "
        f"would be silently dropped. Pass onLeave/onRules/onAbandon instead.")


def test_the_rows_words_live_in_exactly_one_file():
    kit = KIT.read_text(encoding="utf-8")
    for label in ROW_LABELS:
        assert f'"{label}"' in kit, f"{label!r} is not in the kit; this test is reading the wrong file"

    problems: dict[str, list[str]] = {}
    for jsx in _menu_games():
        text = jsx.read_text(encoding="utf-8")
        # The exact quoted literal, so a game's own prose is not a false hit:
        # CoC's abandon confirm legitimately reads "Abandon game?", which is a
        # different string and stays a game's own words.
        hits = [lbl for lbl in ROW_LABELS if f'"{lbl}"' in text]
        if hits:
            problems[jsx.name] = hits
    assert not problems, (
        f"menu row labels re-typed outside the kit: {problems}. The words belong to "
        f"GameMenu in shared/lobby.jsx so all nine menus cannot drift apart.")


def test_every_game_offers_the_way_out_and_the_rules():
    """The two rows every menu has. A game that forgets one still renders."""
    missing: dict[str, list[str]] = {}
    for jsx in _menu_games():
        text = jsx.read_text(encoding="utf-8")
        for mount in re.findall(r"<GameMenu\b.*?/>", text, flags=re.S):
            gaps = [p for p in ("onLeave", "onRules") if p not in mount]
            if gaps:
                missing.setdefault(jsx.name, []).extend(gaps)
    assert not missing, f"menus with no way out or no rules: {missing}"


def test_abandon_is_offered_everywhere_it_means_something():
    silent = {}
    for jsx in _menu_games():
        if "onAbandon" not in jsx.read_text(encoding="utf-8"):
            silent[jsx.name] = "no onAbandon anywhere"
    unexplained = {k: v for k, v in silent.items() if k not in NO_ABANDON}
    assert not unexplained, (
        f"{unexplained} offer no Abandon and are not in NO_ABANDON. If that is "
        f"deliberate, add it there with the reason; otherwise wire it up.")
    # ...and the exemption must still be REACHED, so a renamed file or a broken
    # walk fails loudly instead of quietly exempting nothing.
    assert set(silent) == set(NO_ABANDON), (
        f"NO_ABANDON is stale: exempted {sorted(NO_ABANDON)}, actually silent {sorted(silent)}")


def test_the_menu_still_builds_its_own_rows():
    """Non-vacuity: everything above is worthless if the kit stopped owning them."""
    kit = KIT.read_text(encoding="utf-8")
    assert re.search(r"export function GameMenu\(\{[^}]*onLeave", kit), \
        "GameMenu no longer takes onLeave — the rest of this file is measuring nothing"
    for glyph in ("←", "📖", "⚑"):
        assert f'icon: "{glyph}"' in kit, f"the {glyph} row lost its icon in the kit"
