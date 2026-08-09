"""Pins `engine.py` to the Rust reference it was ported from.

`rust-cores/dissonance-core` is the solver-validated implementation of these
rules; `engine.py` is a hand port. Two implementations of the same rules drift
silently, so this replays complete playthroughs generated there and demands
identical results.

The fixture file IS committed, unlike CoC's equivalent: those feed a cargo
test, these feed pytest, so CI needs them present. Regenerate whenever the
rules change -- a stale fixture failing here is the gate doing its job:

    cd rust-cores/dissonance-core
    cargo run --release --bin gen_fixtures 400 \\
        > ../../games/dissonance/tests/fixtures/play.jsonl
"""

import json
import os

import pytest

from games.dissonance import engine as E

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "play.jsonl")


def _load():
    if not os.path.exists(FIXTURES):
        pytest.fail(
            "Rust parity fixtures missing at %s -- this is NOT a rules failure.\n"
            "Regenerate with:\n"
            "  cd rust-cores/dissonance-core && cargo run --release --bin gen_fixtures 400"
            " > ../../games/dissonance/tests/fixtures/play.jsonl" % FIXTURES
        )
    with open(FIXTURES, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _game_from(fx):
    """Rebuild the exact dealt position the reference started from.

    `even` is the fixture's even-trick value: 2 is the classic parity, 1 is
    MINOR mode -- the generator plays every fourth fixture there, so the
    port's runtime-parity path (`trick_value_in`) is gated by replay the same
    way Grand's trump is. Absent on a fixture file from before the mode,
    which is classic. `cards` marks a CARD-SCORED fixture (skat mode's
    currency since 2026-08-09), also one in four, gating `card_points` the
    same way; absent means parity.
    """
    if fx.get("cards"):
        mode = "skat"
    else:
        mode = "minor" if fx.get("even", 2) == 1 else "classic"
    g = E.new_game(["a", "b"], mode=mode)
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
    top = E.max_level_for(mode)
    if E.uses_card_points(mode):
        # Card scoring never settles early at all (`_score_is_settled` returns
        # False for it outright -- its floor arithmetic is parity-shaped), so
        # the ceiling coincidence below is not needed here.
        assert not E._score_is_settled(dict(g, auction={
            "level": 1, "denom": 0, "declarer": 0, "used": [0, 0],
            "to_act": 0, "log": [], "value": 0}))
    else:
        even = E.even_value(mode)
        ceiling = sum(v for v in (E.trick_value(t, even)
                                  for t in range(E.NTRICKS)) if v > 0)
        assert top >= ceiling, (
            "the mode's max level no longer exceeds what a declarer can score, "
            "so this harness can settle a round early and truncate the replay")
    g["auction"] = {"level": top, "denom": fx["trump"],
                    "declarer": fx["leader"], "used": [0, 0],
                    "to_act": fx["leader"], "log": [],
                    # Skat's finisher reads the numeric bid off the auction;
                    # zero is honest for a synthetic contract.
                    "value": 0, "passes": 0}
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
    """A break in trick VALUES would show up as scores, so pin it directly.
    The pool is per-currency: the parity modes' constant, or the worth of the
    26 dealt-in cards for a card-scored fixture."""
    fx = _load()
    for f in fx[:50]:
        g = _game_from(f)
        for c in f["moves"]:
            E.apply_play(g, E.to_play(g), c)
        if E.uses_card_points(E.mode_of(g)):
            assert sum(g["pts"]) == E.played_pool(g)
        else:
            assert sum(g["pts"]) == E.pool_for(E.mode_of(g))
        assert g["pts"] == f["pts"]


def test_the_fixtures_cover_the_minor_parity():
    """A regenerate that quietly stopped sampling minor would leave the +1
    path replayed by nothing while the file still looked comprehensive --
    the exact shape the Grand fixtures already guard against."""
    fx = _load()
    minor = [f for f in fx if f.get("even", 2) == 1 and not f.get("cards")]
    assert len(minor) >= len(fx) // 8, (
        "only %d of %d fixtures play minor parity" % (len(minor), len(fx)))
    for f in minor[:20]:
        g = _game_from(f)
        for c in f["moves"]:
            E.apply_play(g, E.to_play(g), c)
        assert sum(g["pts"]) == -1
        assert g["pts"] == f["pts"]


def test_the_fixtures_cover_card_scoring():
    """Same guard for the card-scored (skat) fixtures: a regenerate that
    quietly stopped sampling them would leave `card_points` replayed by
    nothing while the file still looked comprehensive."""
    fx = _load()
    cards = [f for f in fx if f.get("cards")]
    assert len(cards) >= len(fx) // 8, (
        "only %d of %d fixtures play card scoring" % (len(cards), len(fx)))
    for f in cards[:20]:
        g = _game_from(f)
        for c in f["moves"]:
            E.apply_play(g, E.to_play(g), c)
        assert sum(g["pts"]) == E.played_pool(g)
        assert g["pts"] == f["pts"]
    # ...and at least one of them really has a deal-dependent pool away from
    # the parity constant, or the whole distinction proved nothing.
    pools = {E.played_pool(_game_from(f)) for f in cards}
    assert pools - {5}, "every card fixture's pool read the parity constant"
