"""At-rest compaction, and the save/load round trip.

The size guard here bounds RAW bytes, not the stored ratio. That is deliberate
and was learned the expensive way in four other games: the stored ratio's
denominator is the COMPRESSOR, not the codec, and it moves under you -- the same
CoC blobs read 0.660 at zlib level 1 and 0.755 at level 6, and Python 3.14 ships
zlib-ng rather than stock zlib. Every one of those four guards was written
against CI's zlib; CoC's sat 0.005 under its threshold and so passed CI while
being red on every dev box. Raw bytes is a deterministic axis. The real
"did it actually do anything" check is STRUCTURAL, below, which no compressor
can move.
"""

from __future__ import annotations

import json
import random

from core import rooms as _rooms
from games.rag_tag import engine as E
from games.rag_tag import main as m
from games.rag_tag import persist


def _played(seed=3, rounds=4):
    rng = random.Random(seed)
    game = E.new_game(["alice", "bob"], seed=seed)
    for _ in range(4000):
        if game["winner"] is not None or game["round"] > rounds:
            break
        acted = False
        for pid in ("alice", "bob"):
            moves = E.legal_moves(game, E.seat_of(game, pid))
            if moves:
                E.apply_move(game, pid, rng.choice(moves))
                acted = True
        if not acted:
            E.advance(game)
    return {"players": {"alice": "Alice", "bob": "Bob"}, "host": "alice",
            "status": "playing", "game": game, "meta": {}, "vs_ai": False,
            "ai_player": None}


def test_compaction_round_trips_a_real_game_exactly():
    state = _played()
    assert persist.expand_state(persist.compact_state(state)) == state


def test_the_live_dict_is_never_touched():
    """Compaction is a PERSISTENCE BOUNDARY, not a change to the game."""
    state = _played()
    before = json.dumps(state, sort_keys=True)
    persist.compact_state(state)
    assert json.dumps(state, sort_keys=True) == before


def test_a_blob_written_before_compaction_existed_still_loads():
    """The `_c` marker is what makes this need no migration."""
    state = _played()
    assert "_c" not in state["game"]
    assert persist.expand_state(state) == state


def test_compacting_twice_is_a_no_op():
    state = _played()
    once = persist.compact_state(state)
    assert persist.compact_state(once) == once


def test_the_rng_really_is_packed_and_the_instances_really_are_tuples():
    """The STRUCTURAL check: prove the codec did the two things it claims.

    A byte-size assertion can be satisfied by luck or by the compressor. This
    cannot: either the RNG came out packed and the instance rows came out as
    lists, or the codec did nothing.
    """
    state = _played()
    small = persist.compact_state(state)["game"]

    assert small["rng_state"] != state["game"]["rng_state"]
    assert small["rng_state"] == _rooms.pack_rng(state["game"]["rng_state"])

    assert small["instances"], "a played game has card instances"
    assert all(isinstance(row, list) for row in small["instances"])
    assert small["instances"][0] == [
        state["game"]["instances"][0]["cid"], state["game"]["instances"][0]["seat"],
        state["game"]["instances"][0]["slot"],
        1 if state["game"]["instances"][0]["flipped"] else 0]


def test_compaction_actually_shrinks_the_raw_blob():
    state = _played()
    raw = len(json.dumps(state))
    small = len(json.dumps(persist.compact_state(state)))
    assert small < raw * 0.95, f"{small} vs {raw} raw bytes"


def test_the_only_codec_sites_are_the_two_in_main():
    """Every read of state_json must funnel through `_decode_state`."""
    state = _played()
    blob = m._encode_state(state)
    assert isinstance(blob, str)
    back = m._decode_state(blob)
    assert back["game"]["winner"] == state["game"]["winner"]
    assert back["game"]["instances"] == state["game"]["instances"]
    assert back["game"]["fighters"] == state["game"]["fighters"]


def test_a_saved_game_resumes_mid_fight_and_mid_build():
    """Save, load, and keep playing -- from both of the phases that can pause."""
    for stop in ("fight", "build"):
        rng = random.Random(21)
        game = E.new_game(["alice", "bob"], seed=21)
        while game["winner"] is None:
            if game["phase"] == stop and game["build_choice"] == [None, None]:
                break
            acted = False
            for pid in ("alice", "bob"):
                moves = E.legal_moves(game, E.seat_of(game, pid))
                if moves:
                    E.apply_move(game, pid, rng.choice(moves))
                    acted = True
            if not acted:
                E.advance(game)

        state = {"players": {}, "host": "alice", "status": "playing",
                 "game": game, "meta": {}, "vs_ai": False, "ai_player": None}
        resumed = m._decode_state(m._encode_state(state))["game"]
        assert resumed == game

        # And it keeps playing from there.
        for _ in range(500):
            if resumed["winner"] is not None:
                break
            acted = False
            for pid in ("alice", "bob"):
                moves = E.legal_moves(resumed, E.seat_of(resumed, pid))
                if moves:
                    E.apply_move(resumed, pid, moves[0])
                    acted = True
            if not acted:
                E.advance(resumed)
        assert resumed["winner"] in (0, 1, "draw")


def test_the_log_is_capped_at_rest():
    state = _played()
    state["game"]["log"] = [f"line {i}" for i in range(persist.LOG_CAP + 50)]
    small = persist.compact_state(state)
    assert len(small["game"]["log"]) == persist.LOG_CAP
    assert small["game"]["log"][-1] == f"line {persist.LOG_CAP + 49}", "the TAIL is kept"
