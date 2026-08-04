"""At-rest compaction for the Dontminion `state_json` blob.

A PURE PERSISTENCE BOUNDARY (same shape as CoC's, Spender's and Duel's).

Dontminion has the BIGGEST rows in the database — ~15-20 KB stored against CoC's ~9.5 KB
and Spender's ~0.7 KB — and its zones are already name-strings with a `{name: count}`
supply, so the structure itself is lean. What was left is `rng_state`: 625 words of
Mersenne noise, incompressible where everything around it compresses ~8x, measured at
**27-34% of the stored row**. Packing it to base64 is **-8.1%** (mean of 6 played-out
games across 2p/base and 4p/4-expansion boards).

EVERY UNDO SNAPSHOT CARRIES ITS OWN COPY. `_push_undo` excludes the stack and the log
but keeps `rng_state`, and the stack runs up to `_UNDO_CAP` (30) deep mid-turn — so a
blob saved part-way through a turn can hold 30 copies. They must all be packed: zlib
dedups near-identical copies, so packing some and not others breaks the dedup and can
make the row BIGGER than doing nothing (measured at +49.5% on Duel — see the rule in
`core.rooms.pack_rng`).

The move log is deliberately left alone. It is 58-67% of the row and looks like the
obvious target, but it is highly repetitive (the same card names over and over) and zlib
already handles that: encoding every card name to a table index took the raw blob
104,863 -> 93,436 and the STORED blob only 20,042 -> 19,474, i.e. **-2.8%** for a
rewrite of the most-read structure in the game. What is left after zlib is the log's
actual information content; the only way to shrink it further is to log less, which is a
product decision about replay and scrollback, not a compaction one.
"""
from __future__ import annotations

from core import rooms as _rooms

_VERSION = 1
_MARK = "_c"            # compaction marker; absent => a legacy row, expand is a no-op


def _apply(game: dict, fn) -> dict:
    """Every rng_state in the blob: the live one AND all `undo_stack` snapshots."""
    g = dict(game)
    if "rng_state" in g:
        g["rng_state"] = fn(g["rng_state"])
    stack = g.get("undo_stack")
    if isinstance(stack, list):
        g["undo_stack"] = [
            {**s, "rng_state": fn(s["rng_state"])}
            if isinstance(s, dict) and "rng_state" in s else s
            for s in stack
        ]
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
