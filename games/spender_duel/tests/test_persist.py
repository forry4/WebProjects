"""The at-rest compaction must be EXACTLY lossless.

Duel's blob is already id-compact, so the only thing `persist` touches is `rng_state`.
That makes correctness narrow but sharp: a lossy pack silently changes every future
deck draw and token pull in a resumed game, which no assertion on sizes would catch.
`test_packed_rng_reproduces_the_same_stream` is therefore the load-bearing test here.
"""
import copy
import json
import random

from core import rooms as _rooms
from games.spender_duel import engine, persist


def _play(seed=7, plies=10**9):
    g = engine.new_game(["p0", "p1"], seed=seed)
    rng = random.Random(seed * 31 + 5)
    n = 0
    while not engine.is_over(g) and n < plies:
        pid = g.get("pending_pid") or g.get("turn")
        moves = engine.legal_moves(g, pid)
        if not moves:
            break
        engine.apply_move(g, pid, rng.choice(moves))
        n += 1
    return g


def _state(game):
    return {"players": {"p0": "A", "p1": "B"}, "host": "p0", "status": "playing",
            "game": game, "meta": {}, "vs_ai": False, "ai_player": None,
            "ai_difficulty": "hard"}


# ── losslessness ─────────────────────────────────────────────────────────────
def test_round_trip_is_exact():
    for seed in (7, 11, 23, 42, 99):
        for plies in (0, 25, 10**9):
            state = _state(_play(seed, plies))
            before = json.loads(json.dumps(state))
            assert persist.expand_state(persist.compact_state(state)) == before, (seed, plies)


def test_round_trip_through_the_real_db_codec():
    state = _state(_play())
    before = json.loads(json.dumps(state))
    blob = _rooms.encode_state(persist.compact_state(state))
    assert blob.startswith("z:")
    assert persist.expand_state(_rooms.decode_state(blob)) == before


def test_compaction_does_not_mutate_the_live_game():
    state = _state(_play(11, 25))
    untouched = copy.deepcopy(state)
    persist.compact_state(state)
    assert state == untouched


def test_packed_rng_reproduces_the_same_stream():
    """THE test. A lossy pack would silently change every future draw in a resumed
    game — no size assertion catches that, only replaying the stream does."""
    g = _play(7, 25)
    restored = persist.expand_state(persist.compact_state(_state(g)))["game"]
    a, b = random.Random(), random.Random()
    a.setstate((g["rng_state"][0], tuple(g["rng_state"][1]), g["rng_state"][2]))
    b.setstate((restored["rng_state"][0], tuple(restored["rng_state"][1]),
                restored["rng_state"][2]))
    assert [a.random() for _ in range(200)] == [b.random() for _ in range(200)]
    assert [a.getrandbits(32) for _ in range(50)] == [b.getrandbits(32) for _ in range(50)]


# ── the snapshot copy, and why it is not optional ────────────────────────────
def test_the_undo_snapshots_rng_is_packed_too():
    g = _play(7, 25)
    assert "turn_undo" in g and "rng_state" in g["turn_undo"], "test needs both copies"
    packed = persist.compact_state(_state(g))["game"]
    assert isinstance(packed["rng_state"][1], dict)
    assert isinstance(packed["turn_undo"]["rng_state"][1], dict), \
        "packing only the live copy breaks zlib's dedup and GROWS the row"


def test_packing_only_the_live_copy_would_make_the_row_bigger():
    """Pins the measured trap: pack every copy in the blob or none of them. Doing it
    half-way came out +49.5% versus doing nothing — worse than not compacting."""
    g = _play(7, 25)
    plain = len(_rooms.encode_state(_state(g)))
    both = len(_rooms.encode_state(persist.compact_state(_state(g))))

    half = copy.deepcopy(g)                       # the WRONG way, for contrast
    half["rng_state"] = _rooms.pack_rng(half["rng_state"])
    only_live = len(_rooms.encode_state(_state(half)))

    assert both < plain, "packing both copies must shrink the row"
    assert only_live > plain, "the half-done version is expected to be WORSE than plain"
    assert both < only_live


# ── backward compatibility + effect ──────────────────────────────────────────
def test_legacy_uncompacted_blob_passes_through():
    legacy = json.loads(json.dumps(_state(_play())))
    assert persist.expand_state(legacy) == legacy


def test_compaction_actually_shrinks_the_blob():
    state = _state(_play())
    plain = len(_rooms.encode_state(state))
    packed = len(_rooms.encode_state(persist.compact_state(state)))
    assert packed < plain * 0.93, f"{packed} vs {plain} — compaction lost its effect"
