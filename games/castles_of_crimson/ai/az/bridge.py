"""engine.py move dicts ↔ compact slot-addressed moves (the Rust bridge).

A COMPACT move addresses tiles by (container, slot) and spaces by canonical index —
no string tile ids — so the Rust engine (and the WASM client) can work in pure ints.
The Python side owns both directions because it has the live game dict:

  move_to_compact(game, pid, move)   engine dict  -> compact   (fixtures, harvest)
  compact_to_move(game, pid, cmove)  compact      -> engine dict  (serving: ai_move)

Compact schema ("t" field):
  {"t":"end"} | {"t":"skip"}
  {"t":"take_hex","die":i,"depot":d0,"slot":s}      d0/slot 0-based
  {"t":"place","die":i,"slot":s,"space":idx}
  {"t":"sell","die":i} | {"t":"workers","die":i}
  {"t":"adjust","die":i,"to":v}
  {"t":"black","slot":s} | {"t":"discard","slot":s}
  {"t":"m6","depot":d0,"slot":s} | {"t":"btake","depot":d0,"slot":s}
  {"t":"castle","space":idx}
  {"t":"extra","value":v,"sub":{compact sub without "die"}}
  {"t":"ship","depot":d0} | {"t":"ship_adj","depot":d0}
  {"t":"pick","color":c} | {"t":"wh","color":c}
  {"t":"townhall","slot":s,"space":idx}

The Rust-side expansion of a compact move into its micro-action chain lives in
coc-core (tests/engine_parity.rs; later wasm.rs) — keep the two in sync.
"""
from __future__ import annotations

from games.castles_of_crimson import tiles
from games.castles_of_crimson.ai.az import spaces

GOODS = tiles.GOODS_COLORS


def _storage_slot(p: dict, tile_id: str) -> int:
    for i, t in enumerate(p["storage"]):
        if t["id"] == tile_id:
            return i
    raise ValueError(f"tile {tile_id} not in storage")


def _depot_slot(game: dict, tile_id: str) -> tuple[int, int]:
    for d in range(1, 7):
        for s, t in enumerate(game["depots"][str(d)]["hexes"]):
            if t["id"] == tile_id:
                return d - 1, s
    raise ValueError(f"tile {tile_id} not in any depot")


def _black_slot(game: dict, tile_id: str) -> int:
    for s, t in enumerate(game["black_depot"]):
        if t["id"] == tile_id:
            return s
    raise ValueError(f"tile {tile_id} not in black depot")


def move_to_compact(game: dict, pid: str, move: dict) -> dict:
    p = game["players"][pid]
    mt = move["type"]
    if mt == "end_turn":
        return {"t": "end"}
    if mt == "skip_pending":
        return {"t": "skip"}
    if mt == "take_hex":
        v = game["dice"][pid]["values"][move["die_index"]]
        d0 = move.get("depot", v) - 1
        slot = next(
            s for s, t in enumerate(game["depots"][str(d0 + 1)]["hexes"])
            if t["id"] == move["tile_id"]
        )
        return {"t": "take_hex", "die": move["die_index"], "depot": d0, "slot": slot}
    if mt == "place_tile":
        return {"t": "place", "die": move["die_index"],
                "slot": _storage_slot(p, move["tile_id"]),
                "space": spaces.INDEX_OF[move["space_id"]]}
    if mt == "sell_goods":
        return {"t": "sell", "die": move["die_index"]}
    if mt == "take_workers":
        return {"t": "workers", "die": move["die_index"]}
    if mt == "adjust_die":
        return {"t": "adjust", "die": move["die_index"], "to": move["to"]}
    if mt == "buy_black":
        return {"t": "black", "slot": _black_slot(game, move["tile_id"])}
    if mt == "discard_storage":
        return {"t": "discard", "slot": _storage_slot(p, move["tile_id"])}
    if mt == "monastery6_take":
        d0, slot = _depot_slot(game, move["tile_id"])
        return {"t": "m6", "depot": d0, "slot": slot}
    if mt == "building_take_choice":
        d0, slot = _depot_slot(game, move["tile_id"])
        return {"t": "btake", "depot": d0, "slot": slot}
    if mt == "place_starting_castle":
        return {"t": "castle", "space": spaces.INDEX_OF[move["space_id"]]}
    if mt == "ship_take_goods":
        return {"t": "ship", "depot": move["depot"] - 1}
    if mt == "ship_adjacent_take":
        return {"t": "ship_adj", "depot": move["depot"] - 1}
    if mt == "goods_pick":
        return {"t": "pick", "color": GOODS.index(move["color"])}
    if mt == "warehouse_sell":
        return {"t": "wh", "color": GOODS.index(move["color"])}
    if mt == "townhall_place":
        return {"t": "townhall", "slot": _storage_slot(p, move["tile_id"]),
                "space": spaces.INDEX_OF[move["space_id"]]}
    if mt == "extra_action":
        sub = move.get("sub") or {}
        st = sub.get("type")
        v = move["value"]
        if st == "take_workers":
            csub = {"t": "workers"}
        elif st == "sell_goods":
            csub = {"t": "sell"}
        elif st == "take_hex":
            d0 = sub.get("depot", v) - 1
            slot = next(
                s for s, t in enumerate(game["depots"][str(d0 + 1)]["hexes"])
                if t["id"] == sub["tile_id"]
            )
            csub = {"t": "take_hex", "depot": d0, "slot": slot}
        elif st == "place_tile":
            csub = {"t": "place", "slot": _storage_slot(p, sub["tile_id"]),
                    "space": spaces.INDEX_OF[sub["space_id"]]}
        else:
            raise ValueError(f"bad extra_action sub {st!r}")
        return {"t": "extra", "value": v, "sub": csub}
    raise ValueError(f"unknown move type {mt!r}")


def compact_to_move(game: dict, pid: str, c: dict) -> dict:
    """Inverse of move_to_compact against the LIVE game dict (the serving path)."""
    p = game["players"][pid]
    t = c["t"]
    if t == "end":
        return {"type": "end_turn"}
    if t == "skip":
        return {"type": "skip_pending"}
    if t == "take_hex":
        tile = game["depots"][str(c["depot"] + 1)]["hexes"][c["slot"]]
        return {"type": "take_hex", "die_index": c["die"], "depot": c["depot"] + 1,
                "tile_id": tile["id"]}
    if t == "place":
        return {"type": "place_tile", "die_index": c["die"],
                "tile_id": p["storage"][c["slot"]]["id"],
                "space_id": spaces.SPACE_IDS[c["space"]]}
    if t == "sell":
        return {"type": "sell_goods", "die_index": c["die"]}
    if t == "workers":
        return {"type": "take_workers", "die_index": c["die"]}
    if t == "adjust":
        return {"type": "adjust_die", "die_index": c["die"], "to": c["to"]}
    if t == "black":
        return {"type": "buy_black", "tile_id": game["black_depot"][c["slot"]]["id"]}
    if t == "discard":
        return {"type": "discard_storage", "tile_id": p["storage"][c["slot"]]["id"]}
    if t == "m6":
        tile = game["depots"][str(c["depot"] + 1)]["hexes"][c["slot"]]
        return {"type": "monastery6_take", "tile_id": tile["id"]}
    if t == "btake":
        tile = game["depots"][str(c["depot"] + 1)]["hexes"][c["slot"]]
        return {"type": "building_take_choice", "tile_id": tile["id"]}
    if t == "castle":
        return {"type": "place_starting_castle", "space_id": spaces.SPACE_IDS[c["space"]]}
    if t == "ship":
        return {"type": "ship_take_goods", "depot": c["depot"] + 1}
    if t == "ship_adj":
        return {"type": "ship_adjacent_take", "depot": c["depot"] + 1}
    if t == "pick":
        return {"type": "goods_pick", "color": GOODS[c["color"]]}
    if t == "wh":
        return {"type": "warehouse_sell", "color": GOODS[c["color"]]}
    if t == "townhall":
        return {"type": "townhall_place", "tile_id": p["storage"][c["slot"]]["id"],
                "space_id": spaces.SPACE_IDS[c["space"]]}
    if t == "extra":
        sub = c["sub"]
        st = sub["t"]
        v = c["value"]
        if st == "workers":
            esub = {"type": "take_workers"}
        elif st == "sell":
            esub = {"type": "sell_goods"}
        elif st == "take_hex":
            tile = game["depots"][str(sub["depot"] + 1)]["hexes"][sub["slot"]]
            esub = {"type": "take_hex", "depot": sub["depot"] + 1, "tile_id": tile["id"]}
        elif st == "place":
            esub = {"type": "place_tile", "tile_id": p["storage"][sub["slot"]]["id"],
                    "space_id": spaces.SPACE_IDS[sub["space"]]}
        else:
            raise ValueError(f"bad compact extra sub {st!r}")
        return {"type": "extra_action", "value": v, "sub": esub}
    raise ValueError(f"unknown compact type {t!r}")
