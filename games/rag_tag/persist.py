"""At-rest compaction of the stored game blob. A PERSISTENCE BOUNDARY only.

The live dict, the wire, the engine and the bot all keep the verbose shape. The
only two places that ever see the compact one are ``_encode_state`` and
``_decode_state`` in ``main.py``, and every reader must funnel through those --
offline tools included -- or a compacted blob reaches code expecting the other
shape.

Blobs carry a ``_c`` marker, so rows written before this existed load untouched
and no migration is needed.

WHAT IS ACTUALLY BIG, measured rather than assumed:

* ``rng_state`` is 625 words of Mersenne noise. It is INCOMPRESSIBLE, so it
  survives the ~8x zlib around it untouched and ends up dominating the row.
  ``core.rooms.pack_rng`` halves it. Rag Tag has no undo stack, so there is
  exactly one copy to pack -- which sidesteps the trap the other games pay for,
  where packing only the live copy destroys zlib's dedup against the snapshot
  copies and the row comes out BIGGER than doing nothing.
* ``instances`` is 40 four-key dicts whose keys repeat forty times. As tuples it
  is a quarter of the characters, and unlike the RNG this is real structure
  rather than noise, so zlib was already doing well on it -- the win is small
  and honest.
* ``beats`` is replaced every round rather than appended to, so it is bounded by
  one round's turns and needs no cap. That was a design decision in the engine,
  not something to fix here: the repo has paid for unbounded in-state logs three
  separate times.
"""

from __future__ import annotations

from core import rooms as _rooms

MARKER = "_c"
INSTANCE_KEYS = ("cid", "seat", "slot", "flipped")

#: The move log is the one thing here that grows all game. It is small per entry
#: and the History panel only ever shows the tail, so it is capped rather than
#: compressed -- see the repo-wide note that move logs are already as small as
#: they get and re-encoding them is not worth relitigating per game.
LOG_CAP = 400


def compact_state(state: dict) -> dict:
    """Shrink a room state for storage. Never mutates the caller's dict."""
    if not isinstance(state, dict):
        return state
    game = state.get("game")
    if not isinstance(game, dict) or game.get(MARKER):
        return state

    small = dict(game)
    small[MARKER] = 1

    if isinstance(small.get("rng_state"), list):
        small["rng_state"] = _rooms.pack_rng(small["rng_state"])

    insts = small.get("instances")
    if isinstance(insts, list) and insts and isinstance(insts[0], dict):
        small["instances"] = [[i["cid"], i["seat"], i["slot"], 1 if i["flipped"] else 0]
                              for i in insts]

    if isinstance(small.get("log"), list) and len(small["log"]) > LOG_CAP:
        small["log"] = small["log"][-LOG_CAP:]

    out = dict(state)
    out["game"] = small
    return out


def expand_state(state: dict) -> dict:
    """Undo `compact_state`. A blob without the marker is returned as it came."""
    if not isinstance(state, dict):
        return state
    game = state.get("game")
    if not isinstance(game, dict) or not game.get(MARKER):
        return state

    big = dict(game)
    big.pop(MARKER, None)

    if big.get("rng_state") is not None:
        big["rng_state"] = _rooms.unpack_rng(big["rng_state"])

    insts = big.get("instances")
    if isinstance(insts, list) and insts and isinstance(insts[0], list):
        big["instances"] = [
            {"cid": row[0], "seat": row[1], "slot": row[2], "flipped": bool(row[3])}
            for row in insts]

    out = dict(state)
    out["game"] = big
    return out
