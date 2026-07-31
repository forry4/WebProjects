"""SERVER↔CLIENT CONTRACT: every field Dontminion.jsx reads off the wire must
actually be shipped.

Both frontend bugs found in live play were drift on this seam, not logic
errors — the client re-derived prices the server owned (Peddler showed printed
costs, so discounted piles never lit up and the buy was refused), and it
rendered a button off a fact the server never sent (Play-all-treasures offered
itself for a hand of nothing but manual treasures, doing nothing when clicked).
Neither is visible to the Python suite (which never renders) or to
`npm run screens` (which mounts the route but plays no Dontminion game), so
this reads the JSX source and checks the field names against a real view.

It is deliberately a NAME check, not a render test: it cannot prove the client
uses a field correctly, only that the server still sends it. That is exactly
the failure both bugs had — the client asking for something that wasn't there.
"""

import pathlib
import re

import pytest

from games.dontminion import engine
from games.dontminion.cards import KINGDOM

A, B = "alice", "bob"
JSX = "games/dontminion/Dontminion.jsx"
MAIN = "games/dontminion/main.py"

# Reads that are NOT wire fields — locals, client-derived state, or optional
# chaining onto something built in the component. Keep this SHORT and justified;
# a growing allowlist means the check is being worked around.
ALLOW_GAME = {
    # nested reads the regex flattens (game.turn_ctx.bought, game.seats[pid]...)
    "seats", "turn_ctx",
}
ALLOW_SEAT = set()


def _src(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _reads(src, obj):
    """Every `obj.X` / `obj?.X` property read in the source."""
    return set(re.findall(rf"\b{obj}\??\.(\w+)", src))


def _views():
    """Wire views across every shape the client can be looking at: owner,
    opponent, spectator, and a finished game (which reveals everything)."""
    kingdom = sorted(KINGDOM["prosperity"])[:10]
    g = engine.new_game([A, B], ["prosperity"], seed=5, kingdom=kingdom)
    engine.apply_move(g, A, {"type": "end_phase"})
    out = [engine.player_view(g, v) for v in (A, B, None)]
    g["over"] = True
    out.append(engine.player_view(g, A))
    return out


def test_every_game_field_the_client_reads_is_shipped():
    views = _views()
    shipped = set().union(*(set(v) for v in views))
    missing = _reads(_src(JSX), "game") - shipped - ALLOW_GAME
    assert not missing, (
        f"Dontminion.jsx reads game.{{{', '.join(sorted(missing))}}} but "
        f"player_view does not ship it — the client will silently render "
        f"undefined (the Peddler-cost bug's shape)")


@pytest.mark.parametrize("obj", ["mySeat", "seat", "opp"])
def test_every_seat_field_the_client_reads_is_shipped(obj):
    views = _views()
    shipped = set()
    for v in views:
        for s in v["seats"].values():
            shipped |= set(s)
    missing = _reads(_src(JSX), obj) - shipped - ALLOW_SEAT
    assert not missing, (
        f"Dontminion.jsx reads {obj}.{{{', '.join(sorted(missing))}}} but no "
        f"seat view ships it")


def test_every_catalog_field_the_client_reads_is_shipped():
    """/catalog is the other wire surface — it carries the static card data
    plus MANUAL_TREASURES (which the Play-all button needs to not render
    itself for a hand it cannot act on)."""
    main_src = _src(MAIN)
    body = main_src.split("async def catalog()", 1)[1].split("\n@", 1)[0]
    shipped = set(re.findall(r'"(\w+)":', body))
    missing = _reads(_src(JSX), "catalog") - shipped
    assert not missing, (
        f"Dontminion.jsx reads catalog.{{{', '.join(sorted(missing))}}} but "
        f"/catalog does not return it")


def test_every_log_event_the_engine_emits_has_a_fmtLog_case():
    """The unknown-event FALLBACK exists so a new event is never silent — but
    it renders raw field names, which can actively mislead: `off_turn_bonus`
    came out as "bob off turn bonus: coins 2", reading as though he got the
    coins when the point is that he lost them. So the fallback is the safety
    net, not the destination: every event the engine actually emits owes a
    case. (A future set may add an event before its UI wording — that is what
    the fallback covers, and this test is what stops it staying that way.)"""
    events = set()
    for path in pathlib.Path("games/dontminion").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        events |= set(re.findall(r'_log\(\s*game\s*,\s*[^,]+,\s*"([a-z_]+)"', src))
        events |= set(re.findall(r'"event":\s*"([a-z_]+)"', src))

    jsx = _src(JSX)
    body = jsx[jsx.find("function fmtLog"):][:12000]
    cased = set(re.findall(r'case "([a-z_]+)"', body))

    assert len(events) > 20, "the emit scan found almost nothing — regex rotted"
    missing = sorted(events - cased)
    assert not missing, (
        f"engine emits {missing} with no fmtLog case — they will render as raw "
        f"field names in the game log")


def test_every_pinned_ambiguity_names_a_test_that_exists():
    """The OPEN AMBIGUITIES list in CLAUDE.md claims each entry is pinned by a
    test. A list that cites a test which has been renamed or deleted is worse
    than no list — it reads as "this is covered" when nothing is watching. So
    every `test_...` name the section mentions must actually exist."""
    doc = _src("games/dontminion/CLAUDE.md")
    start = doc.find("## OPEN AMBIGUITIES")
    assert start != -1, "the ambiguity list is gone from CLAUDE.md"
    section = doc[start:doc.find("\n## ", start + 10)]
    cited = set(re.findall(r"`(test_\w+)`", section))
    assert cited, "the ambiguity list cites no tests at all"

    defined = set()
    for path in pathlib.Path("games/dontminion/tests").glob("test_*.py"):
        defined |= set(re.findall(r"^def (test_\w+)",
                                  path.read_text(encoding="utf-8"), re.M))
    missing = sorted(cited - defined)
    assert not missing, (
        f"CLAUDE.md's ambiguity list cites tests that do not exist: {missing}")


def test_the_contract_check_actually_resolves_fields():
    """Guard against the checks passing because the regex found nothing."""
    src = _src(JSX)
    assert len(_reads(src, "game")) > 15, "game.X reads not being found"
    assert len(_reads(src, "mySeat")) > 2, "mySeat.X reads not being found"
    assert "manual_treasures" in _reads(src, "catalog")
    assert "costs" in _reads(src, "game")     # the two fields the bugs added
