"""Bot-vs-bot soak: seeded uniform-random games with per-move invariants.

The Dontminion analog of Duel's 25-token conservation soak. After EVERY move:
  1. card conservation — the multiset over supply + trash + every seat's
     deck/hand/discard/in_play/aside equals the initial multiset;
  2. at rest the top frame (if any) is a decision frame and the mirrors match;
  3. legal_moves(actor) is non-empty (the never-strand rule);
  4. the live vp map equals a fresh score_game recompute;
  5. the whole game dict stays JSON-serialisable.
Games must terminate under the move cap and produce scores/winners.
"""

import json
import random
from collections import Counter

import pytest

from games.dontminion import engine

A, B, C, D = "alice", "bob", "carol", "dave"
K7 = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room", "Gardens"]
MOVE_CAP = 6000


def _census(game):
    total = Counter(game["supply"])
    total.update(game["trash"])
    for seat in game["seats"].values():
        for zone in ("deck", "hand", "discard", "in_play", "aside",
                     "dur_aside", "island", "village_mat"):
            total.update(seat.get(zone, []))
        # duration entries hold real cards; dur_setup cards are still in in_play
        for entry in seat.get("duration", []):
            total.update([entry["card"]])
            total.update(entry.get("riders", []))
    return total


def _actor(game):
    return game["pending_pid"] or game["turn"]


def _random_move(game, pid, rng):
    if game["pending_pid"] == pid:
        return {"type": "decision", **engine.sample_decision(game, pid, rng)}
    return rng.choice(engine.legal_moves(game, pid))


def _assert_invariants(game, baseline):
    assert _census(game) == baseline, "card conservation broken"
    if game["pending"]:
        top = game["pending"][-1]
        assert top["kind"] != "auto", "auto frame visible at rest"
        assert game["pending_pid"] == top["pid"]
        assert game["pending_kind"] == top["kind"]
    else:
        assert game["pending_pid"] is None and game["pending_kind"] is None
    if not game["over"]:
        assert engine.legal_moves(game, _actor(game)), "actor stranded"
    assert game["vp"] == {p: s["vp"] for p, s in engine.score_game(game).items()}
    json.dumps(game)


@pytest.mark.parametrize("players,seed", [
    ([A, B], 1), ([A, B], 2), ([A, B, C], 3), ([A, B, C, D], 4),
])
def test_soak_full_games(players, seed):
    game = engine.new_game(players, ["base"], seed=seed, kingdom=K7)
    baseline = _census(game)
    rng = random.Random(seed * 1000 + 7)
    for _ in range(MOVE_CAP):
        if game["over"]:
            break
        pid = _actor(game)
        ok, err = engine.apply_move(game, pid, _random_move(game, pid, rng))
        assert ok, f"random legal move rejected: {err}"
        _assert_invariants(game, baseline)
    assert game["over"], "game did not terminate under the move cap"
    assert game["scores"] and game["winners"]
    for p in players:
        assert game["scores"][p]["turns"] == game["seats"][p]["turns_taken"]


def _all_kingdom_cards():
    from games.dontminion.cards import KINGDOM
    return sorted(KINGDOM["base"]) + sorted(KINGDOM["intrigue"]) + sorted(KINGDOM["seaside"])


@pytest.mark.parametrize("chunk", [0, 1, 2, 3, 4, 5, 6, 7])
def test_soak_forced_kingdoms_cover_all_cards(chunk):
    """Fixed kingdoms that together cover ALL kingdom cards (79 with Seaside) —
    every card effect runs inside full random games under the census."""
    cards = _all_kingdom_cards()
    kingdom = cards[chunk * 10: chunk * 10 + 10] if chunk < 7 else cards[-10:]
    game = engine.new_game([A, B, C], ["base", "intrigue", "seaside"], seed=1234 + chunk,
                           kingdom=kingdom)
    baseline = _census(game)
    rng = random.Random(4321 + chunk)
    for _ in range(MOVE_CAP):
        if game["over"]:
            break
        pid = _actor(game)
        ok, err = engine.apply_move(game, pid, _random_move(game, pid, rng))
        assert ok, f"random legal move rejected: {err}"
        _assert_invariants(game, baseline)
    assert game["over"], "game did not terminate under the move cap"


def test_soak_determinism_same_seed_same_game():
    def run():
        game = engine.new_game([A, B], ["base"], seed=11, kingdom=K7)
        rng = random.Random(99)
        for _ in range(MOVE_CAP):
            if game["over"]:
                break
            pid = _actor(game)
            ok, _ = engine.apply_move(game, pid, _random_move(game, pid, rng))
            assert ok
        return game
    g1, g2 = run(), run()
    assert json.dumps(g1, sort_keys=True) == json.dumps(g2, sort_keys=True)
