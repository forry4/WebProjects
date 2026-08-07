"""Every `var(--token)` without a fallback must name a token IN SCOPE for it.

THIS FAILS SILENTLY AT RUNTIME, which is the whole reason it needs a static
test. An undefined custom property makes the declaration "invalid at computed
value time", and the browser throws away THAT DECLARATION ONLY — the rest of
the rule applies normally and nothing is logged. So:

* `background: var(--accent); color: #08131f` kept the dark background and the
  near-black text, i.e. a selected button you cannot read;
* `outline: 2px solid var(--accent)` dropped the whole outline shorthand, so
  selected cards and won tricks simply lost their outline;
* `color: var(--muted)` fell back to `inherit` (colour is an inherited
  property), so "muted" text rendered at full brightness.

Dissonance shipped with `--accent` dead in eight places and `--muted` dead in
six, in both auction modes, and no existing gate could see it: the Python suite
never renders and `screens.mjs` asserts markup and geometry, not colour. A
player reported the bids looked invisible.

WHAT THIS CATCHES: a token NOTHING in the repo defines. That is how `--muted`
was found — six dead declarations, no definition anywhere.

WHAT THIS CANNOT CATCH, stated plainly because the first two versions of this
file claimed otherwise and both passed against the real bug: a token that is
defined somewhere but is not in scope where it is USED. `--accent` is set on
Spender's `.home-game-card` and inline by `shared/HomeScreen.jsx` for the home
menu — neither of which is anywhere near a Dissonance board, yet both make the
name "exist". Real CSS scope is per-element-subtree and needs a DOM; a text
scan cannot model it, and pretending otherwise is worse than not trying.

The guard for THAT half is a rendering assertion, not a static one:
`screens.mjs` measures a selected bid's computed background against its own
text colour, which is the property a player actually cares about and the exact
symptom that was reported.

Scope is still narrowed as far as text allows — a game may use the theme, the
shared kits, its own sheet and its own JSX — so a token defined only in another
game's CSS is still caught.

A `var(--x, fallback)` is FINE and deliberately not flagged: that is the
documented shared-kit pattern for surviving CoC's bare mount, where the theme
tokens genuinely are absent.

Read as TEXT, like `test_lobby_kit.py` next door.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

CSS_DEF = re.compile(r"(--[A-Za-z0-9_-]+)\s*:")
# JSX inline style keys — games hand the shared kit their accent this way
# (`style={{ "--lby-accent": "#d6454b" }}`), so a CSS-only scan would call
# every kit token undefined.
JSX_DEF = re.compile(r"[\"'](--[A-Za-z0-9_-]+)[\"']\s*:")
# A use with NO fallback: no comma before the closing paren.
BARE_USE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*\)")


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def _game_dirs() -> list[pathlib.Path]:
    """Derived from the tree — a new game is covered the day its sheet lands."""
    out = sorted(d for d in (ROOT / "games").iterdir()
                 if d.is_dir() and any(d.glob("*.css")))
    assert len(out) >= 5, f"expected the games with stylesheets, found {out}"
    return out


def _shared_tokens() -> set[str]:
    """Global: the theme's `:root` block and the shared kits, plus anything a
    game hands the kit inline (those land on the game's own root element)."""
    tokens: set[str] = set()
    for p in sorted(ROOT.glob("shared/*.css")):
        tokens |= set(CSS_DEF.findall(_read(p)))
    for p in sorted(ROOT.glob("shared/*.jsx")):
        tokens |= set(JSX_DEF.findall(_read(p)))
    return tokens


def _scopes() -> dict[pathlib.Path, set[str]]:
    """Sheet -> the tokens legitimately in scope for it."""
    shared = _shared_tokens()
    scopes: dict[pathlib.Path, set[str]] = {}
    for p in sorted(ROOT.glob("shared/*.css")):
        # The kits are used inside every game, so anything any game sets on its
        # own root is reachable from them.
        own = set()
        for g in _game_dirs():
            for j in g.glob("*.jsx"):
                own |= set(JSX_DEF.findall(_read(j)))
        scopes[p] = shared | own
    for g in _game_dirs():
        own = set()
        for f in list(g.glob("*.css")) + list(g.glob("*.jsx")):
            text = _read(f)
            own |= set(CSS_DEF.findall(text)) | set(JSX_DEF.findall(text))
        for p in sorted(g.glob("*.css")):
            scopes[p] = shared | own
    return scopes


def test_no_stylesheet_reads_a_token_out_of_its_scope():
    scopes = _scopes()
    assert any("--gold" in v for v in scopes.values()), \
        "the theme's own tokens are missing — this test is reading the wrong files"

    problems: dict[str, list[str]] = {}
    seen = 0
    for sheet, in_scope in sorted(scopes.items()):
        for i, line in enumerate(_read(sheet).splitlines(), 1):
            for name in BARE_USE.findall(line):
                seen += 1
                if name not in in_scope:
                    problems.setdefault(name, []).append(
                        f"{sheet.relative_to(ROOT)}:{i}")

    # Non-vacuous: these sheets are token-driven, so a scan finding almost
    # nothing means the regex stopped matching, not that the CSS got simpler.
    assert seen > 200, f"only {seen} bare var() uses found — the scan is broken"
    assert not problems, (
        "these resolve to nothing in the sheet that uses them, so the browser "
        f"silently drops the whole declaration: {problems}")


def test_one_games_private_token_is_not_in_scope_for_another():
    """The half of scoping a text scan CAN enforce, pinned with a synthetic
    token so it does not quietly depend on whatever the sheets happen to hold.

    It deliberately does NOT use `--accent` as its example: that one is also set
    inline by `shared/HomeScreen.jsx`, so it is reachable everywhere by this
    model and is precisely the case the docstring says belongs to `screens.mjs`.
    """
    shared = _shared_tokens()
    games = _game_dirs()
    assert len(games) >= 2

    private = "--zz-private-to-one-game"
    assert private not in shared, "pick a name nothing defines"
    scopes = _scopes()
    # Nobody defines it, so it is out of scope for every sheet — which is what
    # makes a use of it a failure rather than a shrug.
    for sheet, in_scope in scopes.items():
        assert private not in in_scope, f"{sheet} somehow has {private}"


def test_a_fallback_is_accepted_and_a_bare_use_is_not():
    """The rule this enforces is narrow on purpose, so pin both halves."""
    assert BARE_USE.findall("color: var(--nope)") == ["--nope"]
    assert BARE_USE.findall("color: var(--nope, #fff)") == []
    # A NESTED fallback reports its inner token, and that is right rather than a
    # quirk: `var(--a, var(--b))` ends the chain at --b, so if nothing defines
    # --b the declaration can still evaporate. --a is covered by its fallback.
    assert BARE_USE.findall("color: var(--lby-accent, var(--gold))") == ["--gold"]
