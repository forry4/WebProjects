"""Pins `engine.py` to the Rust reference it was ported from.

`rust-cores/oddtrick-core` is the solver-validated implementation of these
rules; `engine.py` is a hand port. Two implementations of the same rules drift
silently, so this replays complete playthroughs generated there and demands
identical results.

The fixture file IS committed, unlike CoC's equivalent: those feed a cargo
test, these feed pytest, so CI needs them present. Regenerate whenever the
rules change -- a stale fixture failing here is the gate doing its job:

    cd rust-cores/oddtrick-core
    cargo run --release --bin gen_fixtures 400 \\
        > ../../games/oddtrick/tests/fixtures/play.jsonl
"""

import json
import os

import pytest

from games.oddtrick import engine as E

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "play.jsonl")


def _load():
    if not os.path.exists(FIXTURES):
        pytest.fail(
            "Rust parity fixtures missing at %s -- this is NOT a rules failure.\n"
            "Regenerate with:\n"
            "  cd rust-cores/oddtrick-core && cargo run --release --bin gen_fixtures 400"
            " > ../../games/oddtrick/tests/fixtures/play.jsonl" % FIXTURES
        )
    with open(FIXTURES, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _game_from(fx):
    """Rebuild the exact dealt position the reference started from."""
    g = E.new_game(["a", "b"])
    g["hands"] = [sorted(fx["hands"][0]), sorted(fx["hands"][1])]
    g["piles"] = [[list(p) for p in fx["piles"][0]], [list(p) for p in fx["piles"][1]]]
    g["out"] = list(fx["out"])
    g["phase"] = "play"
    g["trump"] = fx["trump"]
    g["leader"] = fx["leader"]
    g["trick"] = 0
    g["led"] = None
    g["pts"] = [0, 0]
    # The reference plays cards only; give it a settled contract so the engine
    # will accept plays and score at the end.
    #
    # THE LEVEL IS MAX_LEVEL ON PURPOSE, and it is load-bearing. `engine` stops a
    # round the moment the score can no longer change -- a contract that cannot
    # fail pays a flat amount, so the rest is dead time -- and at a level of 1
    # that fires most of the way through most deals, which cut the replay short
    # and made every fixture's final points diverge. The reference always plays
    # all thirteen, so the harness has to name a contract that can never settle
    # early. MAX_LEVEL is exactly that: one player's ceiling is sweeping the six
    # +2 tricks, so `_score_is_settled` would need more points than the game
    # contains. Asserted rather than assumed, because it is a coincidence of two
    # constants and would rot in silence.
    ceiling = sum(v for v in (E.trick_value(t) for t in range(E.NTRICKS)) if v > 0)
    assert E.MAX_LEVEL >= ceiling, (
        "MAX_LEVEL no longer exceeds what a declarer can score, so this harness "
        "can settle a round early and truncate the replay")
    g["auction"] = {"level": E.MAX_LEVEL, "denom": fx["trump"],
                    "declarer": fx["leader"], "used": [0, 0],
                    "to_act": fx["leader"], "log": []}
    return g


def test_fixtures_exist_and_are_substantial():
    fx = _load()
    assert len(fx) >= 100, "want a few hundred playthroughs, got %d" % len(fx)


def test_card_play_matches_the_rust_reference_exactly():
    """Every legal-move set, trick winner and point total must agree."""
    fx = _load()
    for i, f in enumerate(fx):
        g = _game_from(f)
        for ply, c in enumerate(f["moves"]):
            seat = E.to_play(g)
            legal = E.legal_moves(g, seat)
            assert c in legal, (
                "fixture %d ply %d: reference played %s but the port calls it "
                "illegal (legal: %s)" % (i, ply, E.card_name(c),
                                         [E.card_name(x) for x in legal])
            )
            E.apply_play(g, seat, c)
        assert g["trick"] == E.NTRICKS, "fixture %d did not complete" % i
        assert g["pts"] == f["pts"], (
            "fixture %d: points diverged -- port %s, reference %s"
            % (i, g["pts"], f["pts"])
        )


def test_the_port_agrees_on_which_tricks_are_worth_what():
    """A parity break in trick VALUES would show up as scores, so pin it directly."""
    fx = _load()
    for f in fx[:50]:
        g = _game_from(f)
        for c in f["moves"]:
            E.apply_play(g, E.to_play(g), c)
        assert sum(g["pts"]) == E.POOL
        assert g["pts"] == f["pts"]
