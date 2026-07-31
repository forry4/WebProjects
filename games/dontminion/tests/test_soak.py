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


def _fingerprint(game):
    """State identity for the progress check — and the JSON-safety assertion,
    since it round-trips the whole dict with no coercion. undo_stack is excluded
    because it grows on its own and would mask a move that changed nothing
    else; it holds nothing but past copies of these same keys."""
    return json.dumps({k: v for k, v in game.items() if k != "undo_stack"},
                      sort_keys=True)


def _assert_invariants(game, baseline, before=None):
    """Returns the post-move fingerprint so the caller can feed it back in as
    the next move's `before` — one dump per move rather than two."""
    assert _census(game) == baseline, "card conservation broken"
    # An accepted move must CHANGE something. A no-op that reported success is
    # what let a bot livelock on prod: play_all_treasures with only
    # MANUAL_TREASURES in hand played nothing, and the bot prefers that move.
    # (Note a decision may legitimately log nothing — declining a reaction,
    # choosing zero cards — but it still pops its frame, so the state moves.)
    after = _fingerprint(game)
    if before is not None:
        assert after != before, "accepted move changed nothing"
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
    return after


@pytest.mark.parametrize("players,seed", [
    ([A, B], 1), ([A, B], 2), ([A, B, C], 3), ([A, B, C, D], 4),
])
def test_soak_full_games(players, seed):
    game = engine.new_game(players, ["base"], seed=seed, kingdom=K7)
    baseline = _census(game)
    before = _fingerprint(game)
    rng = random.Random(seed * 1000 + 7)
    for _ in range(MOVE_CAP):
        if game["over"]:
            break
        pid = _actor(game)
        ok, err = engine.apply_move(game, pid, _random_move(game, pid, rng))
        assert ok, f"random legal move rejected: {err}"
        before = _assert_invariants(game, baseline, before)
    assert game["over"], "game did not terminate under the move cap"
    assert game["scores"] and game["winners"]
    for p in players:
        assert game["scores"][p]["turns"] == game["seats"][p]["turns_taken"]


def _all_kingdom_cards():
    """NOTE: the chunks below are cut from this SORTED list, so renaming a card
    reshuffles which cards share a kingdom and the soak plays different games.
    Total coverage is unaffected (the assertion below pins it), but wall-clock
    can move a lot — the Harem->Farm rename cut this file from ~19s to ~4s
    purely by changing the alphabetical cut points. Don't read a speed change
    here as lost coverage, and don't read it as a regression either."""
    from games.dontminion.cards import KINGDOM
    # EVERY expansion, derived — a new set joins the soak the moment it ships,
    # instead of needing this list edited (and silently going unsoaked if not).
    out = []
    for exp in sorted(KINGDOM):
        out.extend(sorted(KINGDOM[exp]))
    return out


def _chunks():
    """Ten-card kingdoms covering the whole roster; the last one back-fills."""
    cards = _all_kingdom_cards()
    n = (len(cards) + 9) // 10
    return [cards[i * 10: i * 10 + 10] if i * 10 + 10 <= len(cards)
            else cards[-10:] for i in range(n)]


def test_the_forced_kingdom_chunks_really_cover_every_card():
    """The chunking is derived, so an off-by-one or a roster change could drop
    cards from coverage silently. Pin it."""
    covered = set()
    for k in _chunks():
        assert len(k) == 10, k
        covered |= set(k)
    assert covered == set(_all_kingdom_cards()), \
        sorted(set(_all_kingdom_cards()) - covered)


@pytest.mark.parametrize("chunk", list(range(13)))
def test_soak_forced_kingdoms_cover_all_cards(chunk):
    """Fixed kingdoms that together cover EVERY kingdom card (130 across five
    expansions) — every card effect runs inside full random games under the
    conservation census."""
    from games.dontminion.cards import KINGDOM
    chunks = _chunks()
    if chunk >= len(chunks):
        pytest.skip("fewer chunks than parameters")
    kingdom = chunks[chunk]
    game = engine.new_game([A, B, C], sorted(KINGDOM),
                           seed=1234 + chunk, kingdom=kingdom)
    baseline = _census(game)
    before = _fingerprint(game)
    rng = random.Random(4321 + chunk)
    for _ in range(MOVE_CAP):
        if game["over"]:
            break
        pid = _actor(game)
        ok, err = engine.apply_move(game, pid, _random_move(game, pid, rng))
        assert ok, f"random legal move rejected: {err}"
        before = _assert_invariants(game, baseline, before)
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
