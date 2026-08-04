"""The at-rest compaction must be EXACTLY lossless.

Dontminion has the biggest rows in the DB and draws constantly, so a lossy `rng_state`
pack would silently change every shuffle and draw in a resumed game — the kind of bug
that never fails a test that doesn't replay the stream. `test_packed_rng_reproduces_the
_same_stream` is the load-bearing one; the rest guard the undo stack, whose snapshots
each carry their own copy (up to `_UNDO_CAP` = 30 of them mid-turn).
"""
import copy
import json
import random

from core import rooms as _rooms
from games.dontminion import bot, engine, persist


def _play(seed=7, expansions=("base",), n=2, moves=10**9):
    players = [f"p{i}" for i in range(n)]
    g = engine.new_game(players, list(expansions), seed=seed)
    rngs = {p: random.Random((seed << 8) + i) for i, p in enumerate(players)}
    k = 0
    while not g["over"] and k < moves:
        pid = g["pending_pid"] or g["turn"]
        ok, err = engine.apply_move(g, pid, bot.choose(g, pid, rngs[pid], "hard"))
        assert ok, err
        k += 1
    return g


def _state(game):
    return {"players": {"p0": "A", "p1": "B"}, "host": "p0", "status": "playing",
            "game": game, "meta": {}, "vs_ai": False, "ai_players": [],
            "ai_difficulty": "hard", "expansions": ["base"], "max_players": 2}


# ── losslessness ─────────────────────────────────────────────────────────────
def test_round_trip_is_exact():
    for seed, exps, n in ((7, ("base",), 2),
                          (11, ("base", "intrigue"), 2),
                          (23, ("base", "seaside", "prosperity"), 4)):
        for moves in (0, 60, 10**9):
            state = _state(_play(seed, exps, n, moves))
            before = json.loads(json.dumps(state))
            assert persist.expand_state(persist.compact_state(state)) == before, \
                (seed, exps, n, moves)


def test_round_trip_through_the_real_db_codec():
    state = _state(_play())
    before = json.loads(json.dumps(state))
    blob = _rooms.encode_state(persist.compact_state(state))
    assert blob.startswith("z:")
    assert persist.expand_state(_rooms.decode_state(blob)) == before


def test_compaction_does_not_mutate_the_live_game():
    state = _state(_play(7, moves=60))
    untouched = copy.deepcopy(state)
    persist.compact_state(state)
    assert state == untouched


def test_packed_rng_reproduces_the_same_stream():
    """THE test. Dontminion shuffles and draws every turn; a lossy pack would change
    every one of them in a resumed game without failing anything else here."""
    g = _play(7, moves=60)
    restored = persist.expand_state(persist.compact_state(_state(g)))["game"]
    a, b = random.Random(), random.Random()
    a.setstate((g["rng_state"][0], tuple(g["rng_state"][1]), g["rng_state"][2]))
    b.setstate((restored["rng_state"][0], tuple(restored["rng_state"][1]),
                restored["rng_state"][2]))
    assert [a.random() for _ in range(200)] == [b.random() for _ in range(200)]
    assert [a.getrandbits(32) for _ in range(50)] == [b.getrandbits(32) for _ in range(50)]


# ── the undo stack: EVERY snapshot carries its own copy ──────────────────────
def _mid_turn_with_undo(seed=7):
    """A game stopped part-way through a turn, so the undo stack is non-empty."""
    for moves in range(40, 200):
        g = _play(seed, moves=moves)
        if g.get("undo_stack"):
            return g
    raise AssertionError("could not reach a state with a non-empty undo_stack")


def test_every_undo_snapshot_gets_packed():
    g = _mid_turn_with_undo()
    packed = persist.compact_state(_state(g))["game"]
    snaps = [s for s in packed["undo_stack"] if isinstance(s, dict) and "rng_state" in s]
    assert snaps, "test needs snapshots carrying rng_state"
    for s in snaps:
        assert isinstance(s["rng_state"][1], dict), \
            "an unpacked snapshot copy breaks zlib's dedup and GROWS the row"


def test_a_mid_turn_game_round_trips():
    g = _mid_turn_with_undo()
    state = _state(g)
    before = json.loads(json.dumps(state))
    assert persist.expand_state(persist.compact_state(state)) == before


# ── backward compatibility + effect ──────────────────────────────────────────
def test_legacy_uncompacted_blob_passes_through():
    legacy = json.loads(json.dumps(_state(_play())))
    assert persist.expand_state(legacy) == legacy


def test_compaction_actually_shrinks_the_blob():
    state = _state(_play())
    plain = len(_rooms.encode_state(state))
    packed = len(_rooms.encode_state(persist.compact_state(state)))
    assert packed < plain * 0.96, f"{packed} vs {plain} — compaction lost its effect"
