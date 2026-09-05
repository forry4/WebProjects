"""The detail modal's glossary must reach every rules string in the game.

`Orbit.jsx` prints BGA's own sentence on a card, a technology space and a bonus
token, and defines the jargon in it underneath.  The definitions live in the
JSX; the strings they have to cover live in Python.  So the check reads the JSX
AS TEXT — the same trick `core/tests/test_history_limit.py` uses for the other
constant that is one number seen from two ends — because a glossary that
silently stops matching renders an empty heading and a player back where they
started.

Only NON-EMPTINESS is asserted, and deliberately: whether a definition is
*right* is a reading of the engine, which is what the definitions of `middle`
and `dominated` were transcribed from and what a rules test would have to own.
"""

from __future__ import annotations

from pathlib import Path
import re

from games.orbit.cards import BONUS_TYPES, CARDS, TECHNOLOGIES


JSX = Path(__file__).resolve().parents[1] / "Orbit.jsx"


def _glossary_patterns() -> list[re.Pattern[str]]:
    source = JSX.read_text(encoding="utf-8")
    block = source.split("const GLOSSARY = [", 1)[1].split("\n];", 1)[0]
    raw = re.findall(r"re:\s*/(.+?)/i,", block)
    assert raw, "GLOSSARY entries no longer expose a `re: /.../i` pattern"
    # These are deliberately plain patterns, shared verbatim by both engines.
    return [re.compile(pattern, re.I) for pattern in raw]


def _every_rules_string() -> list[tuple[str, str]]:
    rows = [(f"card {c['id']}", c["description"]) for c in CARDS.values()]
    rows += [(f"tech {t['faction']}/{t['side']}/{t['level']}", t["description"])
             for t in TECHNOLOGIES.values()]
    rows += [(f"bonus {b['type']}", b["description"]) for b in BONUS_TYPES.values()]
    return rows


def test_every_printed_rules_string_has_at_least_one_definition():
    patterns = _glossary_patterns()
    rows = _every_rules_string()
    assert len(rows) == len(CARDS) + len(TECHNOLOGIES) + len(BONUS_TYPES) == 128
    unexplained = [
        label for label, text in rows
        if not any(pattern.search(text) for pattern in patterns)
    ]
    assert not unexplained, f"no glossary term matches: {unexplained}"


def test_the_scan_can_actually_fail():
    """A pattern list that matched everything would make the test above free."""

    patterns = _glossary_patterns()
    assert not any(pattern.search("") for pattern in patterns)
    assert not any(pattern.search("qwx zzq") for pattern in patterns)
