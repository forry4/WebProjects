"""At-rest compaction for the Dissonance ``state_json`` blob.

This is a PERSISTENCE BOUNDARY, never a change to the live dict. The engine,
the wire, the bots and the tests all keep the verbose shape; only the two
functions here ever see the compact one, and only via ``_encode_state`` /
``_decode_state`` in ``main.py``.

Blobs carry a ``_c`` marker, so rows written before compaction existed load
untouched and need no migration.

There is no ``rng_state`` to pack. All of this game's randomness is spent in
the deal and nothing draws afterwards, so the engine never stores one — which
sidesteps the whole "pack every copy or none" trap that bit Duel.

What is actually worth removing:
  * ``played`` is exactly the cards in ``history``, so it is dropped and
    rebuilt.
  * each ``history`` entry is ``[seat, card, source]`` with tiny ranges, so it
    packs into a single int -- 78 numbers become 26.
"""

from __future__ import annotations

MARKER = "_c"
VERSION = 1


def _pack_hist(entry) -> int:
    seat, card, source = entry
    # seat 0..1, card 0..31 (32-card deck), source 0..3. card<<1 tops out at
    # 62, safely below the source field at bit 7.
    return (seat & 1) | (card << 1) | (source << 7)


def _unpack_hist(v: int) -> list:
    return [v & 1, (v >> 1) & 0x3F, (v >> 7) & 0x3]


def compact_state(state: dict) -> dict:
    """Shrink a room state for storage. Never mutates the input."""
    if not isinstance(state, dict) or state.get(MARKER):
        return state
    out = dict(state)
    g = state.get("game")
    if isinstance(g, dict):
        cg = dict(g)
        hist = cg.get("history") or []
        if hist and isinstance(hist[0], (list, tuple)):
            cg["history"] = [_pack_hist(h) for h in hist]
        # Derivable from history; storing it twice is pure waste.
        cg.pop("played", None)
        out["game"] = cg
    out[MARKER] = VERSION
    return out


def expand_state(state: dict) -> dict:
    """Restore the verbose shape. A blob without the marker passes through."""
    if not isinstance(state, dict) or not state.get(MARKER):
        return state
    out = dict(state)
    out.pop(MARKER, None)
    g = state.get("game")
    if isinstance(g, dict):
        eg = dict(g)
        hist = eg.get("history") or []
        if hist and isinstance(hist[0], int):
            eg["history"] = [_unpack_hist(h) for h in hist]
        eg["played"] = [h[1] for h in (eg.get("history") or [])]
        out["game"] = eg
    return out
