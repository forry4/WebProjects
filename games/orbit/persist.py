"""At-rest-only compaction for Orbit room blobs."""

from __future__ import annotations

from core import rooms as _rooms


MARKER = "_c"
LOG_CAP = 300


def compact_state(state: dict) -> dict:
    if not isinstance(state, dict):
        return state
    game = state.get("game")
    if not isinstance(game, dict) or game.get(MARKER):
        return state
    small = dict(game)
    small[MARKER] = 1
    if isinstance(small.get("rng_state"), list):
        small["rng_state"] = _rooms.pack_rng(small["rng_state"])
    if isinstance(small.get("log"), list) and len(small["log"]) > LOG_CAP:
        small["log"] = small["log"][-LOG_CAP:]
    out = dict(state)
    out["game"] = small
    return out

def expand_state(state: dict) -> dict:
    if not isinstance(state, dict):
        return state
    game = state.get("game")
    if not isinstance(game, dict) or not game.get(MARKER):
        return state
    big = dict(game)
    big.pop(MARKER, None)
    if big.get("rng_state") is not None:
        big["rng_state"] = _rooms.unpack_rng(big["rng_state"])
    out = dict(state)
    out["game"] = big
    return out
