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
  * each round-review ``deal`` snapshot is a FIXED partition of the whole deck,
    so its nesting is redundant -- see ``_pack_deal``.
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


# The review snapshot is stored once per round for the life of a match, so its
# shape is the one thing here that grows with the game rather than with the
# round. MEASURED on played-out 7-10 round matches, after zlib at level 6:
# verbose it cost +135% on the stored blob, flattened it costs +96%. The
# nesting carries no information -- the partition is FIXED (7 + 7 in hand,
# 3 x 2 piles each, 6 out of play), so structure is implied by position alone
# and only the 32 card ids are real.
#
# Read the RATIO with the absolute beside it or it reads as a disaster: this
# game's rows are ~600 bytes because only the CURRENT round's history is kept,
# so a whole reviewable match is ~1.3KB. Nearly doubling a very small number is
# still a very small number, and the review is worth it.
#
# What is left is mostly `terms`, and it rides through untouched deliberately:
# it is the contract's own arithmetic, it is what the review is priced against,
# and inventing a second encoding for the numbers `payoff_terms` produces is
# exactly the drift that function exists to stop.
_DEAL_SLICES = ((0, 7), (7, 14))


def _pack_deal(d: dict) -> dict:
    if not isinstance(d, dict) or "hands" not in d:
        return d
    flat = list(d["hands"][0]) + list(d["hands"][1])
    for q in (0, 1):
        for pile in d["piles"][q]:
            flat += list(pile)
    flat += list(d["out"])
    packed = {k: v for k, v in d.items() if k not in ("hands", "piles", "out")}
    packed["c"] = flat
    return packed


def _unpack_deal(d: dict) -> dict:
    if not isinstance(d, dict) or "c" not in d:
        return d
    f = d["c"]
    out = {k: v for k, v in d.items() if k != "c"}
    out["hands"] = [f[0:7], f[7:14]]
    out["piles"] = [[f[14 + q * 6 + i * 2: 16 + q * 6 + i * 2] for i in range(3)]
                    for q in (0, 1)]
    out["out"] = f[26:32]
    return out


def _map_deals(g: dict, fn) -> None:
    """Apply `fn` to the live snapshot and to every banked round's copy.

    BOTH, or neither is worth doing: the live one is a single round while the
    banked ones are the part that accumulates, and a packer that reached only
    one of them would leave the growth exactly where it was.
    """
    if isinstance(g.get("deal"), dict):
        g["deal"] = fn(g["deal"])
    m = g.get("match")
    if isinstance(m, dict) and isinstance(m.get("rounds"), list):
        rounds = []
        for r in m["rounds"]:
            if isinstance(r, dict) and isinstance(r.get("deal"), dict):
                r = dict(r)
                r["deal"] = fn(r["deal"])
            rounds.append(r)
        g["match"] = dict(m) | {"rounds": rounds}


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
        _map_deals(cg, _pack_deal)
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
        _map_deals(eg, _unpack_deal)
        out["game"] = eg
    return out
