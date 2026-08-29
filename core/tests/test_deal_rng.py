"""`deal_rng` is the seam that makes the render gate's deals reproducible.

It exists because of a measured failure mode, not a hypothetical one: of the 15
failed Pages deploys in the 500 runs to 2026-08-28, 11 were the `screens` gate,
and the ones that were the HARNESS rather than the product were all the same
bug — an assertion that holds on SOME deals, written green locally and drawn red
in CI. Four of them went red->green with the application code byte-identical.

Two properties carry that fix and neither is visible by reading the callers:

  * PRODUCTION IS UNCHANGED. With the env var unset this must be an ordinary
    unseeded RNG. A regression here does not fail a game — it silently pins
    every deal in production to one hand, which in a hidden-info game is the
    whole game. That is the direction worth a test.
  * A KEY'S SEQUENCE IS INDEPENDENT OF WHAT ELSE RAN. screens.mjs runs its
    blocks in two lanes, so anything assigned in global call order is assigned
    in interleaving order and moves between runs. A per-key counter is what
    makes a block's second deal depend only on that block. This is the property
    a naive global counter would quietly fail while still looking deterministic
    on a single-lane run.
"""
import random

import pytest

from core import rooms as _rooms


@pytest.fixture(autouse=True)
def _clean_counters(monkeypatch):
    """Each test starts from a fresh process's worth of state."""
    monkeypatch.setattr(_rooms, "_DEAL_COUNTERS", {})
    monkeypatch.delenv("GAMES_DEAL_SEED", raising=False)
    yield


def _draw(rng):
    """A stand-in for a deal: the shape of what a caller pulls out."""
    return [rng.randrange(2 ** 31) for _ in range(8)]


# ── the production path ──────────────────────────────────────────────────────
def test_unset_env_is_an_ordinary_unseeded_rng():
    a, b = _rooms.deal_rng(["p1", "p2"]), _rooms.deal_rng(["p1", "p2"])
    assert isinstance(a, random.Random)
    # Same players, same mode, twice — in production these must NOT match.
    assert _draw(a) != _draw(b)


def test_an_empty_seed_is_treated_as_unset(monkeypatch):
    # Belt and braces for a CI runner that exports the var as "".
    monkeypatch.setenv("GAMES_DEAL_SEED", "")
    assert _draw(_rooms.deal_rng(["p1"])) != _draw(_rooms.deal_rng(["p1"]))


# ── the gate path ────────────────────────────────────────────────────────────
def test_the_same_table_replays_the_same_deal(monkeypatch):
    monkeypatch.setenv("GAMES_DEAL_SEED", "screens-1")
    first = _draw(_rooms.deal_rng(["skat-harness", "bot"], mode="skat"))
    # A fresh process, same table: the same hand comes back.
    monkeypatch.setattr(_rooms, "_DEAL_COUNTERS", {})
    assert _draw(_rooms.deal_rng(["skat-harness", "bot"], mode="skat")) == first


def test_seat_order_does_not_change_the_deal(monkeypatch):
    monkeypatch.setenv("GAMES_DEAL_SEED", "screens-1")
    a = _draw(_rooms.deal_rng(["bot", "hard-harness"], mode="classic"))
    monkeypatch.setattr(_rooms, "_DEAL_COUNTERS", {})
    b = _draw(_rooms.deal_rng(["hard-harness", "bot"], mode="classic"))
    # Callers pass `room["players"].keys()`, whose order is insertion order and
    # therefore depends on who joined first. That must not move the deal.
    assert a == b


def test_different_tables_and_modes_get_different_deals(monkeypatch):
    monkeypatch.setenv("GAMES_DEAL_SEED", "screens-1")
    seen = {
        tuple(_draw(_rooms.deal_rng(players, mode=mode)))
        for players, mode in [
            (["skat-harness", "bot"], "skat"),
            (["hard-harness", "bot"], "classic"),
            (["quartet-harness", "bot"], "quartet"),
            # Same table, different mode: still a different hand.
            (["skat-harness", "bot"], "classic"),
        ]
    }
    assert len(seen) == 4


def test_a_second_game_at_one_table_is_a_different_deal(monkeypatch):
    monkeypatch.setenv("GAMES_DEAL_SEED", "screens-1")
    tbl = (["hold-harness", "bot"], "classic")
    first = _draw(_rooms.deal_rng(tbl[0], mode=tbl[1]))
    second = _draw(_rooms.deal_rng(tbl[0], mode=tbl[1]))
    # A block that plays two games must not play the identical hand twice —
    # that would make its second game vacuous coverage of the first.
    assert first != second


def test_a_tables_sequence_does_not_depend_on_what_else_ran(monkeypatch):
    """The lane-independence property — the reason the counter is per-key."""
    monkeypatch.setenv("GAMES_DEAL_SEED", "screens-1")
    tbl = ["beat-harness", "bot"]

    alone = [_draw(_rooms.deal_rng(tbl, mode="classic")) for _ in range(3)]

    # Now replay the same three deals with OTHER blocks interleaved between
    # them, the way a second screens lane would.
    monkeypatch.setattr(_rooms, "_DEAL_COUNTERS", {})
    interleaved = []
    for i in range(3):
        _rooms.deal_rng([f"other-{i}-harness", "bot"], mode="skat")
        interleaved.append(_draw(_rooms.deal_rng(tbl, mode="classic")))
        _rooms.deal_rng(["third-harness", "bot"], mode="quartet")

    assert interleaved == alone


# ── the bot half ─────────────────────────────────────────────────────────────
# Pinning the deal without pinning the bot leaves the game branching at the
# first bot decision, which is the failure `d1bdc1e` actually was.
def test_bot_seed_is_unpredictable_in_production():
    pos = ("bidding", 3, 0)
    seeds = {_rooms.bot_seed(pos, 1, "hard") for _ in range(20)}
    # The direction that matters: a bot answering every identical position
    # identically is one a player can learn by rote.
    assert len(seeds) > 1


def test_bot_seed_is_a_function_of_the_position_when_seeded(monkeypatch):
    monkeypatch.setenv("GAMES_DEAL_SEED", "screens-1")
    pos = ("bidding", 3, 0)
    assert _rooms.bot_seed(pos, 1, "hard") == _rooms.bot_seed(pos, 1, "hard")
    # A re-entered scheduler asks the same question of the same position and
    # must get the same answer — that is why this keys on the position and not
    # on a move counter, which reconnects and retries would drift.
    assert _rooms.bot_seed(pos, 1, "hard") != _rooms.bot_seed(("bidding", 4, 0), 1, "hard")
    assert _rooms.bot_seed(pos, 1, "hard") != _rooms.bot_seed(pos, 0, "hard")
    assert _rooms.bot_seed(pos, 1, "hard") != _rooms.bot_seed(pos, 1, "normal")


def test_bot_seed_is_in_range(monkeypatch):
    monkeypatch.setenv("GAMES_DEAL_SEED", "screens-1")
    # Callers pass it straight to random.Random(seed) / engine seeds that the
    # unseeded path bounded at 2**31.
    for i in range(50):
        assert 0 <= _rooms.bot_seed(("p", i), i) < 2 ** 32


def test_changing_the_seed_re_rolls_every_table(monkeypatch):
    monkeypatch.setenv("GAMES_DEAL_SEED", "screens-1")
    tbl = (["dummy-harness", "bot"], "dummy")
    a = _draw(_rooms.deal_rng(tbl[0], mode=tbl[1]))
    # The escape hatch: bumping the seed must move the hand, so a maintainer can
    # check that a green gate is not merely memorising one deal.
    monkeypatch.setenv("GAMES_DEAL_SEED", "screens-2")
    monkeypatch.setattr(_rooms, "_DEAL_COUNTERS", {})
    assert _draw(_rooms.deal_rng(tbl[0], mode=tbl[1])) != a
