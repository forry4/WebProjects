"""At-rest compaction for the CoC `state_json` blob.

This is a PURE PERSISTENCE BOUNDARY: `compact_state` runs on the way into the DB and
`expand_state` on the way back out. The live game dict, the wire (`mk_room_state` /
the WebSocket broadcast), the engine, the bot and the Rust parity fixtures all keep
seeing full tile objects — nothing outside this module knows the stored shape. That is
deliberate: the tile `id` is load-bearing in both directions (engine moves address a
tile by `tile_id`, and the frontend's flyer animation tracks a tile across locations by
its id), so compacting the LIVE dict would have been a wire break for a disk win.

Measured on 5 played-out 2p games, against the shared zlib layer in `core.rooms`:

    baseline                          84,230 raw   20,729 stored
    tiles dict-encoded                62,560 raw   11,171 stored   -46%
    + engine: undo drops the log      44,275 raw   10,769 stored   -48%
    + rng_state packed                37,538 raw    9,517 stored   -54%

Two findings worth keeping, because both are counter-intuitive:

* **Measure after zlib, not before.** `rng_state` looks like 8% of the raw dict but
  22% of the COMPRESSED one — it is 625 words of Mersenne state, i.e. incompressible
  noise, where everything around it compresses ~8x.

* **Transform BOTH copies of a key or none.** The game and its `turn_undo` snapshot
  hold near-identical `rng_state`s, and zlib was already collapsing the second one to
  almost nothing. Packing only the live copy destroyed that dedup and made the blob
  BIGGER than not packing at all (-37% -> -17% in the A/B). Anything applied here must
  be applied to the snapshot too.
"""
from __future__ import annotations

import base64

_VERSION = 1
_MARK = "_c"            # compaction version marker; absent => a legacy row, expand is a no-op

# Tiles carry an id of `<prefix><n>` minted by `tiles._mk`, one prefix per kind.
_PREFIX = {"hex": "h", "goods": "g"}


# ── tiles ────────────────────────────────────────────────────────────────────
# Every tile is one of a few dozen distinct SHAPES (type/color/building/animal/
# count/effect_id/black/starting) plus a unique id, so the shape goes in a table once
# and each tile stores `[id_number, shape_index]` — ~85 bytes of JSON down to ~8.

def _enc_tile(t, shapes: dict, order: list):
    if not isinstance(t, dict):
        return t
    tid, pre = t.get("id"), _PREFIX.get(t.get("kind"))
    if pre is None or not isinstance(tid, str) or not tid[len(pre):].isdigit() \
            or not tid.startswith(pre):
        return t                                  # unrecognized -> verbatim, still lossless
    rest = [(k, v) for k, v in t.items() if k != "id"]
    try:
        key = tuple(sorted(rest))
    except TypeError:                             # unhashable extra -> verbatim
        return t
    idx = shapes.get(key)
    if idx is None:
        idx = shapes[key] = len(order)
        order.append(dict(rest))
    return [int(tid[len(pre):]), idx]


def _dec_tile(v, shapes: list):
    if not (isinstance(v, list) and len(v) == 2 and isinstance(v[1], int)):
        return v
    num, idx = v
    if not 0 <= idx < len(shapes):
        return v
    shape = shapes[idx]
    pre = _PREFIX.get(shape.get("kind"))
    if pre is None:
        return v
    return {"id": f"{pre}{num}", **shape}


# The tile locations, spelled out rather than discovered by a generic walk: a walk
# that guessed at "looks like a tile" would also have to run over `rng_state`'s list
# of ints and `track`'s lists of pids, and a false positive there is a corrupt save.
# `tests/test_persist.py` asserts this list still covers every tile in a played game —
# it is what caught `moves[].tile` below, which a by-eye reading of `new_game` misses.
_TILE_LISTS = ("supply", "black_supply", "goods_supply", "black_depot", "goods_queue")

# Log records embed the tile an action was performed on (`take_hex`/`place_tile`/
# `buy_black`/`discard_storage`/`building_take` all log `tile=`). It is the only
# tile-valued log field, and always a single tile.
_MOVE_TILE_KEY = "tile"


def _map_tiles(game: dict, fn) -> dict:
    """Return a copy of `game` with `fn` applied to every tile. Never mutates the
    input — `state["game"]` is the LIVE game dict of a running room."""
    g = dict(game)
    for k in _TILE_LISTS:
        if isinstance(g.get(k), list):
            g[k] = [fn(t) for t in g[k]]
    if isinstance(g.get("depots"), dict):
        depots = {}
        for d, v in g["depots"].items():
            if isinstance(v, dict):
                v = dict(v)
                for kk in ("hexes", "goods"):
                    if isinstance(v.get(kk), list):
                        v[kk] = [fn(t) for t in v[kk]]
            depots[d] = v
        g["depots"] = depots
    if isinstance(g.get("moves"), list):
        g["moves"] = [{**m, _MOVE_TILE_KEY: fn(m[_MOVE_TILE_KEY])}
                      if isinstance(m, dict) and m.get(_MOVE_TILE_KEY) is not None else m
                      for m in g["moves"]]
    if isinstance(g.get("players"), dict):
        players = {}
        for pid, p in g["players"].items():
            if isinstance(p, dict):
                p = dict(p)
                if isinstance(p.get("storage"), list):
                    p["storage"] = [fn(t) for t in p["storage"]]
                if isinstance(p.get("duchy"), dict):
                    p["duchy"] = {sid: (fn(t) if t is not None else None)
                                  for sid, t in p["duchy"].items()}
            players[pid] = p
        g["players"] = players
    return g


# ── rng_state ────────────────────────────────────────────────────────────────
# `random.getstate()` is (version, 625 words, gauss_next). As a JSON list of ints
# that is ~6.7 KB of noise which zlib cannot touch; packed little-endian into base64
# it is ~3.3 KB. Words are 32-bit (624 state + 1 index), so this is exact.

def _pack_rng(st):
    if not (isinstance(st, list) and len(st) >= 2 and isinstance(st[1], list)):
        return st
    try:
        blob = b"".join(int(w).to_bytes(4, "little") for w in st[1])
    except (OverflowError, ValueError, TypeError):
        return st
    return [st[0], {"b64": base64.b64encode(blob).decode("ascii")}] + list(st[2:])


def _unpack_rng(st):
    if not (isinstance(st, list) and len(st) >= 2 and isinstance(st[1], dict)
            and "b64" in st[1]):
        return st
    blob = base64.b64decode(st[1]["b64"])
    words = [int.from_bytes(blob[i:i + 4], "little") for i in range(0, len(blob), 4)]
    return [st[0], words] + list(st[2:])


# ── public API ───────────────────────────────────────────────────────────────
def _apply(game: dict, tile_fn, rng_fn) -> dict:
    g = _map_tiles(game, tile_fn)
    if "rng_state" in g:
        g["rng_state"] = rng_fn(g["rng_state"])
    snap = g.get("turn_undo")
    if isinstance(snap, dict):                    # snapshots never nest, so one level
        g["turn_undo"] = _apply(snap, tile_fn, rng_fn)
    return g


def compact_state(state: dict) -> dict:
    """Shrink a save blob. Returns a new dict; `state` and its game are untouched."""
    game = state.get("game")
    if not isinstance(game, dict):
        return state
    shapes: dict = {}
    order: list = []
    g = _apply(game, lambda t: _enc_tile(t, shapes, order), _pack_rng)
    g["_tile_shapes"] = order
    return {**state, "game": g, _MARK: _VERSION}


def expand_state(state: dict) -> dict:
    """Inverse of `compact_state`. A blob written before this existed carries no
    marker and is returned unchanged, so old prod rows load with no migration."""
    if not isinstance(state, dict) or not state.get(_MARK):
        return state
    game = state.get("game")
    if not isinstance(game, dict):
        return {k: v for k, v in state.items() if k != _MARK}
    shapes = game.get("_tile_shapes") or []
    g = _apply(game, lambda v: _dec_tile(v, shapes), _unpack_rng)
    g.pop("_tile_shapes", None)
    if isinstance(g.get("turn_undo"), dict):
        g["turn_undo"].pop("_tile_shapes", None)
    return {**{k: v for k, v in state.items() if k != _MARK}, "game": g}
