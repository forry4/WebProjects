"""Canonical compact projection of an engine.py game dict — the parity surface
shared with the Rust engine (coc-core).

`project(game)` maps the authoritative game dict to the exact int shape of the Rust
`State` (canonical space order, tile codes, per-color goods counts, pendings as
tagged ints). `proj_string(proj)` renders it as ONE canonical space-separated int
string, and `fnv64` hashes it — coc-core/src/proj.rs produces the IDENTICAL string
from a Rust State, so equal hashes == equal states. Field order here and in proj.rs
must never drift independently.

Tile codes (mirror of coc-core/src/tiles.rs):
  0 empty | 1 starting castle | 2 castle | 3 mine | 4 ship |
  5..13 livestock (5 + animal*3 + count-2) | 14..21 building (+bt index) |
  22..47 monastery (+effect_id-1)
"""
from __future__ import annotations

from games.castles_of_crimson import board, tiles
from games.castles_of_crimson.ai.az import spaces

COLORS = board.COLORS  # burgundy blue gray green beige yellow
GOODS = tiles.GOODS_COLORS
BUILDINGS = tiles.BUILDING_TYPES
ANIMALS = tiles.ANIMALS
# TileType discriminant = the COLOR index of the space the type places on.
TYPE_IDX = {"castle": 0, "ship": 1, "mine": 2, "livestock": 3, "building": 4, "monastery": 5}

PENDING_TAG = {
    None: 0,
    "extra_action": 1,
    "ship_choose_depot": 2,
    "ship_adjacent_depot": 3,
    "goods_pick": 4,
    "building_take_choice": 5,
    "warehouse_sell": 6,
    "townhall_place": 7,
}


def tile_code(tile: dict | None) -> int:
    if tile is None:
        return 0
    t = tile["type"]
    if t == "castle":
        return 1 if tile.get("starting") else 2
    if t == "mine":
        return 3
    if t == "ship":
        return 4
    if t == "livestock":
        return 5 + ANIMALS.index(tile["animal"]) * 3 + (tile["count"] - 2)
    if t == "building":
        return 14 + BUILDINGS.index(tile["building"])
    if t == "monastery":
        return 22 + tile["effect_id"] - 1
    raise ValueError(f"unknown tile type {t!r}")


def _seat_of(game: dict, pid) -> int:
    return game["order"].index(pid)


def _goods_counts(goods: dict) -> list[int]:
    return [goods.get(c, 0) for c in GOODS]


def _sold_counts(sold: list) -> list[int]:
    out = [0] * 6
    for c in sold:
        out[GOODS.index(c)] += 1
    return out


def _pending_fields(game: dict) -> tuple[int, list[int]]:
    kind = game.get("pending_kind")
    tag = PENDING_TAG[kind]
    ctx = (game.get("pending") or {}).get("ctx", {})
    if kind == "ship_adjacent_depot":
        cands = 0
        for d in ctx.get("candidates", []):
            cands |= 1 << (d - 1)
        return tag, [cands]
    if kind == "goods_pick":
        colors = 0
        for c in ctx.get("colors", []):
            colors |= 1 << GOODS.index(c)
        m5 = ctx.get("m5_from")
        return tag, [ctx["depot"] - 1, colors, (m5 - 1) if m5 is not None else -1]
    if kind == "building_take_choice":
        types = 0
        for t in ctx.get("types", []):
            types |= 1 << TYPE_IDX[t]
        return tag, [types]
    return tag, []


def project(game: dict) -> dict:
    """The structured canonical projection (seat order = game['order'])."""
    assert game.get("ship_advance_pending", 0) == 0, "legacy ship_advance_pending must be 0"
    order = game["order"]
    assert len(order) == 2, "compact projection is 2-player"

    mode = {"setup": 0, "playing": 1, "over": 2}[game["phase"]]
    win = game.get("winner")
    winner = -2 if win is None else (-1 if isinstance(win, list) else _seat_of(game, win))

    # track: positions + top-of-stack seat when shared
    track_pos = [0, 0]
    for s, stack in enumerate(game["track"]):
        for pid in stack:
            track_pos[_seat_of(game, pid)] = s
    track_top = -1
    if track_pos[0] == track_pos[1]:
        stack = game["track"][track_pos[0]]
        track_top = _seat_of(game, stack[-1])

    dice = []
    for pid in order:
        d = game["dice"].get(pid)
        if d is None:
            dice.append([[0, 0, 0, 0], [0, 0, 0, 0]])
        else:
            orig = d.get("orig", d["values"])
            adj = d.get("adjusted", [False, False])
            dice.append([
                [d["values"][i], orig[i], int(d["used"][i]), int(adj[i])] for i in (0, 1)
            ])

    depot_hex = []
    depot_goods = []
    for i in range(1, 7):
        d = game["depots"][str(i)]
        hx = [tile_code(t) for t in d["hexes"]][:2]
        depot_hex.append(hx + [0] * (2 - len(hx)))
        dg = [0] * 6
        for g in d["goods"]:
            dg[GOODS.index(g["color"])] += 1
        depot_goods.append(dg)

    black = [tile_code(t) for t in game["black_depot"]][:4]
    black += [0] * (4 - len(black))

    players = []
    for pid in order:
        p = game["players"][pid]
        bidx = spaces.board_index(p.get("board_id"))
        duchy = [tile_code(p["duchy"][sid]) for sid in spaces.SPACE_IDS]
        storage = [tile_code(t) for t in p["storage"]][:3]
        storage += [0] * (3 - len(storage))
        mon_mask = 0
        for eid in p["monastery_effects"]:
            mon_mask |= 1 << (eid - 1)
        lmask = 0
        for a in p["livestock_types"]:
            lmask |= 1 << ANIMALS.index(a)
        town = [0] * spaces.MAX_REGIONS
        for rid, bts in p["town_buildings"].items():
            idx = spaces.REGION_INDEX[bidx][rid]
            for bt in bts:
                town[idx] |= 1 << BUILDINGS.index(bt)
        players.append({
            "board": bidx,
            "duchy": duchy,
            "castle_sid": 255 if p["castle_sid"] is None else spaces.INDEX_OF[p["castle_sid"]],
            "storage": storage,
            "goods": _goods_counts(p["goods"]),
            "sold": _sold_counts(p["sold_goods"]),
            "workers": p["workers"],
            "silver": p["silver"],
            "vp": p["vp"],
            "bonus_claimed": len(p["claimed_bonus"]),
            "mines": p["mines_count"],
            "buildings": [p["buildings_placed"].get(bt, 0) for bt in BUILDINGS],
            "livestock_mask": lmask,
            "mon_mask": mon_mask,
            "town_bldg": town,
        })

    tag, pfields = _pending_fields(game)

    return {
        "boards": [players[0]["board"], players[1]["board"]],
        "phase": tiles.PHASES.index(game["phase_letter"]),
        "round": game["round"],
        "mode": mode,
        "winner": winner,
        "track_pos": track_pos,
        "track_top": track_top,
        "round_order": [_seat_of(game, pid) for pid in game["round_order"]],
        "start_player": _seat_of(game, game["start_player"]),
        "turn": -1 if game["turn"] is None else _seat_of(game, game["turn"]),
        "white_die": game["white_die"] or 0,
        "dice": dice,
        "black_used": int(game["black_depot_used_this_turn"]),
        "m6_used": int(game["m6_used_this_turn"]),
        "depot_hex": depot_hex,
        "depot_goods": depot_goods,
        "black_depot": black,
        "supply": [tile_code(t) for t in game["supply"]],
        "black_supply": [tile_code(t) for t in game["black_supply"]],
        "goods_supply": [GOODS.index(g["color"]) for g in game["goods_supply"]],
        "goods_queue": [GOODS.index(g["color"]) for g in game["goods_queue"]],
        "bonus_left": [len(game["bonus_tiles"].get(c, [])) for c in COLORS],
        "players": players,
        "pending_pid": -1 if game["pending_pid"] is None else _seat_of(game, game["pending_pid"]),
        "pending_tag": tag,
        "pending_fields": pfields,
    }


def proj_string(proj: dict) -> str:
    """The ONE canonical string both engines render — see proj.rs for the twin."""
    out: list[int] = []
    out += proj["boards"]
    out += [proj["phase"], proj["round"], proj["mode"], proj["winner"]]
    out += proj["track_pos"]
    out.append(proj["track_top"])
    out += proj["round_order"]
    out += [proj["start_player"], proj["turn"], proj["white_die"]]
    for seat in (0, 1):
        for die in (0, 1):
            out += proj["dice"][seat][die]
    out += [proj["black_used"], proj["m6_used"]]
    for d in proj["depot_hex"]:
        out += d
    for d in proj["depot_goods"]:
        out += d
    out += proj["black_depot"]
    out.append(len(proj["supply"]))
    out += proj["supply"]
    out.append(len(proj["black_supply"]))
    out += proj["black_supply"]
    out.append(len(proj["goods_supply"]))
    out += proj["goods_supply"]
    out.append(len(proj["goods_queue"]))
    out += proj["goods_queue"]
    out += proj["bonus_left"]
    for p in proj["players"]:
        out += p["duchy"]
        out.append(p["castle_sid"])
        out += p["storage"]
        out += p["goods"]
        out += p["sold"]
        out += [p["workers"], p["silver"], p["vp"], p["bonus_claimed"], p["mines"]]
        out += p["buildings"]
        out += [p["livestock_mask"], p["mon_mask"]]
        out += p["town_bldg"]
    out += [proj["pending_pid"], proj["pending_tag"]]
    out += proj["pending_fields"]
    return " ".join(str(x) for x in out)


def fnv64(s: str) -> int:
    h = 0xCBF29CE484222325
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def proj_hash(game: dict) -> str:
    """FNV-1a 64 of the canonical projection string, as a decimal string
    (JSON-safe — u64 doesn't fit exactly in a double)."""
    return str(fnv64(proj_string(project(game))))
