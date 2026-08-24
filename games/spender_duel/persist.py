"""At-rest compaction for the Duel `state_json` blob.

A PURE PERSISTENCE BOUNDARY (same shape as CoC's and Spender's): `compact_state` on the
way into the DB, `expand_state` on the way out, and nothing else knows the stored form.

Duel's live state is already id-compact by construction — cards are ids, tokens are
ints, hands are `{"id": cid}` — so there is nothing card-shaped left to squeeze. What
remained was `rng_state`: 625 words of Mersenne noise that zlib cannot touch, sitting in
a blob where everything else compresses ~8x. Packed to base64 it is **-15.0% of the
stored row** (8,240 -> 7,002, mean of 5 played-out games).

WHY THE SNAPSHOT COPY IS NOT OPTIONAL. `turn_undo` holds its own near-identical
`rng_state`, and zlib was already collapsing the duplicate to almost nothing. Packing
only the live copy destroys that dedup and the row comes out **+49.5% BIGGER than doing
nothing at all** — measured, not theorised, and pinned by
`tests/test_persist.py::test_packing_only_the_live_copy_would_make_the_row_bigger`.
The marginal cost of `rng_state` measured on a whole game reads as ~1.8% for the same
reason; strip `turn_undo` first and the remaining copy costs ~4,800 bytes. Neither
number is wrong, and neither alone tells you the pair is ~59% of the row.
"""
from __future__ import annotations

from core import rooms as _rooms

_VERSION = 1
_MARK = "_c"            # compaction marker; absent => a legacy row, expand is a no-op


def _apply(game: dict, fn) -> dict:
    """Every rng_state in the blob: the live one AND the undo snapshot's."""
    g = dict(game)
    if "rng_state" in g:
        g["rng_state"] = fn(g["rng_state"])
    snap = g.get("turn_undo")
    if isinstance(snap, dict) and "rng_state" in snap:
        snap = dict(snap)
        snap["rng_state"] = fn(snap["rng_state"])
        g["turn_undo"] = snap
    return g


def compact_state(state: dict) -> dict:
    """Shrink a save blob. Returns a new dict; `state` and its game are untouched —
    `state["game"]` is the LIVE game dict of a running room."""
    game = state.get("game")
    if not isinstance(game, dict):
        return state
    return {**state, "game": _apply(game, _rooms.pack_rng), _MARK: _VERSION}


def expand_state(state: dict) -> dict:
    """Inverse of `compact_state`. A blob written before this existed carries no marker
    and is returned unchanged, so old prod rows load with no migration."""
    if not isinstance(state, dict) or not state.get(_MARK):
        return state
    out = {k: v for k, v in state.items() if k != _MARK}
    game = out.get("game")
    if isinstance(game, dict):
        out["game"] = _apply(game, _rooms.unpack_rng)
    return out
