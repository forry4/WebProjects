"""The at-rest compaction must be EXACTLY lossless.

`persist.compact_state` sits on the DB boundary, so a bug here is not a wrong pixel —
it is a saved game that loads back subtly different, or not at all. These tests round-
trip real played-out games rather than hand-built dicts, and check the two things a
round-trip alone can't: that the tile-location list still covers every tile in the
game (a tile in a location `persist` doesn't know about would silently stay verbose),
and that compaction never touches the live dict it was handed.
"""
import copy
import json
import random

from games.castles_of_crimson import engine, persist
from core import rooms as _rooms


def _play(seed, max_moves=100000):
    """A real game, played to the end by random-legal moves."""
    g = engine.new_game(["p0", "p1"], names={"p0": "Alice", "p1": "Bob"}, seed=seed)
    rng = random.Random(seed * 31 + 5)
    n = 0
    while not engine.is_over(g) and n < max_moves:
        pid = g.get("pending_pid") or g.get("turn")
        moves = engine.legal_moves(g, pid)
        if not moves:
            break
        engine.apply_move(g, pid, rng.choice(moves))
        n += 1
    return g


def _state(game):
    return {"players": {"p0": "Alice", "p1": "Bob"}, "host": "p0", "status": "playing",
            "game": game, "meta": {}, "vs_ai": False, "ai_player": None,
            "ai_difficulty": "hard", "max_players": 2, "same_board": False, "boards": {}}


def _count_tiles(o):
    """Every tile ANYWHERE in the structure, found structurally."""
    if isinstance(o, dict):
        if o.get("kind") in ("hex", "goods"):
            return 1
        return sum(_count_tiles(v) for v in o.values())
    if isinstance(o, list):
        return sum(_count_tiles(v) for v in o)
    return 0


# ── losslessness ─────────────────────────────────────────────────────────────
def test_round_trip_is_exact_mid_and_end_game():
    for seed in (7, 11, 23, 42, 99):
        for cut in (40, 120, 100000):          # mid-turn, mid-game, finished
            game = _play(seed, max_moves=cut)
            state = _state(game)
            before = json.loads(json.dumps(state))
            after = persist.expand_state(persist.compact_state(state))
            assert after == before, f"seed={seed} cut={cut}"


def test_round_trip_through_the_real_db_codec():
    """The shape that actually reaches the column, not just the dict transform."""
    state = _state(_play(7))
    before = json.loads(json.dumps(state))
    blob = _rooms.encode_state(persist.compact_state(state))
    assert blob.startswith("z:")
    assert persist.expand_state(_rooms.decode_state(blob)) == before


def test_compaction_does_not_mutate_the_live_game():
    """`state["game"]` is the LIVE dict of a running room — save must not touch it."""
    game = _play(11, max_moves=120)
    state = _state(game)
    untouched = copy.deepcopy(state)
    persist.compact_state(state)
    assert state == untouched


# ── coverage of the explicit tile-location list ──────────────────────────────
def test_every_tile_in_the_game_is_reached():
    """`persist` enumerates tile locations by hand instead of walking generically.
    If the engine ever puts tiles somewhere new, this fails instead of silently
    leaving them verbose."""
    for seed in (7, 42):
        for cut in (40, 100000):
            game = _play(seed, max_moves=cut)
            total = _count_tiles(game)
            assert total > 0
            packed = persist.compact_state(_state(game))["game"]
            # the shape TABLE is made of tile-shaped dicts by construction — it is the
            # output of compaction, not something left uncompacted
            packed.pop("_tile_shapes", None)
            left = _count_tiles(packed)
            assert left == 0, f"{left}/{total} tiles were not compacted (seed={seed})"


def test_a_tile_in_an_unknown_location_survives_verbatim():
    """The fallback path: an unrecognized shape must round-trip, not be dropped."""
    game = _play(7, max_moves=40)
    game["some_future_key"] = [{"id": "h999", "kind": "hex", "type": "mine", "color": "gray"}]
    state = _state(game)
    before = json.loads(json.dumps(state))
    assert persist.expand_state(persist.compact_state(state)) == before


# ── backward compatibility ───────────────────────────────────────────────────
def test_legacy_uncompacted_blob_passes_through():
    """Rows written before compaction carry no marker and must load untouched."""
    state = _state(_play(7, max_moves=80))
    legacy = json.loads(json.dumps(state))
    assert persist.expand_state(legacy) == legacy


def test_compaction_actually_shrinks_the_blob():
    """The size guard, on the two axes where each claim is actually meaningful.

    A SIZE RATIO IS A MEASUREMENT, NOT AN INVARIANT, AND ITS DENOMINATOR IS THE
    COMPRESSOR. This assertion used to be a single `stored < plain * 0.75`, and
    it was red on any box whose zlib differed from the CI runner's: on Python
    3.14 (which ships **zlib-ng**) the same five games read 0.751–0.758 against
    that 0.75. Nothing about compaction had changed — the stored ratio for these
    exact blobs swings 0.660 → 0.758 across zlib LEVELS 1..9 alone, so a
    threshold sitting 0.005 from the observed value was measuring the
    compressor, not the codec.

    So the two claims are split onto the axes that can carry them:

    * RAW is fully deterministic — no compressor in it at all — so it takes the
      TIGHT bound. This is the real regression detector.
    * STORED keeps the module docstring's rule ("measure after zlib"): a
      transform that shrinks raw but not stored is worthless, because stored is
      what the DB pays for. But as a *bound* it only gets a loose one, chosen
      well clear of the compressor's own swing.

    Neither is the no-op guard — `test_every_tile_in_the_game_is_reached` is,
    and it is structural and compressor-independent. A no-op scores 1.000 on
    both axes here and would fail these too, with room to spare.
    """
    for seed in (7, 11, 23, 42, 99):
        state = _state(_play(seed))
        packed_state = persist.compact_state(state)

        def _raw(s):
            return len(json.dumps(s, separators=(",", ":")).encode("utf-8"))

        raw_ratio = _raw(packed_state) / _raw(state)
        assert raw_ratio < 0.70, (
            f"seed {seed}: compaction shrank the raw blob to {raw_ratio:.3f} "
            f"of its size (measured 0.598–0.618; a no-op is 1.0)")

        stored_ratio = (len(_rooms.encode_state(packed_state))
                        / len(_rooms.encode_state(state)))
        assert stored_ratio < 0.90, (
            f"seed {seed}: compaction is not paying for itself after zlib "
            f"({stored_ratio:.3f}) — the DB pays the STORED size, so a raw-only "
            f"win is no win. Measured 0.644–0.758 across zlib levels 1..9; this "
            f"bound is deliberately loose because the ratio moves with the "
            f"compressor (zlib vs zlib-ng), not with the codec")


# ── the rng pack, which the game's determinism rests on ──────────────────────
def test_packed_rng_reproduces_the_same_stream():
    """The rng_state is packed to base64 words; a lossy pack would silently change
    every future dice roll and depot refill."""
    game = _play(7, max_moves=80)
    state = _state(game)
    restored = persist.expand_state(persist.compact_state(state))["game"]
    a, b = random.Random(), random.Random()
    a.setstate(tuple([game["rng_state"][0], tuple(game["rng_state"][1]), game["rng_state"][2]]))
    b.setstate(tuple([restored["rng_state"][0], tuple(restored["rng_state"][1]), restored["rng_state"][2]]))
    assert [a.random() for _ in range(50)] == [b.random() for _ in range(50)]
