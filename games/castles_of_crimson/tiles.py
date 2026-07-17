"""Static tile data, scoring tables, and the tile supply for Castles of Crimson.

No web/game dependency. The hex-tile supply is the exact base-game component
breakdown: **164 tiles total** (124 colored-back + 40 black-back). This count is
fixed, not tunable. Monastery effect_ids 1-26 each denote a unique tile; their
behaviour lives in ``effects.py`` and is summarized in ``MONASTERY_META``.

Supply breakdown (colored-back / black-back):
    Buildings  : 40 beige   / 16 black   (8 types)
    Livestock  : 20 green   /  8 black
    Mines      : 10 gray    /  2 black
    Ships      : 20 blue    /  6 black
    Castles    : 14 burgundy/  2 black
    Monasteries: 20 yellow  /  6 black    (effect_ids 1-26)
"""
from __future__ import annotations

# ── Colors / types ──────────────────────────────────────────────────────────
# Hex-tile color -> the tile type placed on that colored space.
COLOR_TO_TYPE = {
    "burgundy": "castle",
    "blue": "ship",
    "gray": "mine",
    "green": "livestock",
    "beige": "building",
    "yellow": "monastery",
}
TYPE_TO_COLOR = {v: k for k, v in COLOR_TO_TYPE.items()}

# ── Scoring tables ──────────────────────────────────────────────────────────
PHASES = ["A", "B", "C", "D", "E"]
# Completing an area of size n (1..8) scores AREA_SCORE[n-1] (triangular-ish).
AREA_SCORE = [1, 3, 6, 10, 15, 21, 28, 36]
# Plus a bonus by the phase in which the area is completed.
PHASE_BONUS = {"A": 10, "B": 8, "C": 6, "D": 4, "E": 2}

# Selling a stack of goods always yields 1 silver in total (regardless of count).
SELL_SILVER = 1


def sell_vp_per_tile(num_players: int) -> int:
    """VP per sold goods tile: 2/3/4 for 2/3/4 players."""
    return num_players


def bonus_first(num_players: int) -> int:
    """VP for being first to fully cover a color: 5/6/7 for 2/3/4 players."""
    return num_players + 3


def bonus_second(num_players: int) -> int:
    """VP for being second to fully cover a color: 2/3/4 for 2/3/4 players."""
    return num_players

# ── Goods ───────────────────────────────────────────────────────────────────
# Six trade-goods colors, indexed by die value 1..6 for the "sell goods" action
# and for the white-die goods placement.
GOODS_COLORS = ["amber", "rose", "jade", "cobalt", "plum", "rust"]


def goods_color_for_die(die: int) -> str:
    return GOODS_COLORS[die - 1]


# ── Buildings ───────────────────────────────────────────────────────────────
BUILDING_TYPES = [
    "market",      # take a ship or livestock tile from a depot -> storage
    "carpenter",   # take a building tile -> storage
    "church",      # take a mine/monastery/castle tile -> storage
    "warehouse",   # immediately sell a goods type
    "boarding",    # +4 workers
    "bank",        # +2 silver
    "townhall",    # place an additional hex from storage
    "watchtower",  # +4 VP
]

# ── Monasteries (26 unique) ─────────────────────────────────────────────────
# timing: "continuous" (queried at the relevant trigger), "endgame" (scored in
# final_scores), or "on_place" (resolved when placed). Full behaviour: effects.py.
MONASTERY_META = {
    1:  {"timing": "continuous", "desc": "No longer limited to one building of each type per town."},
    2:  {"timing": "continuous", "desc": "Gain a worker (in addition to silver) for each mine, each phase."},
    3:  {"timing": "continuous", "desc": "Gain 2 silver instead of 1 whenever you sell goods."},
    4:  {"timing": "continuous", "desc": "Gain a worker whenever you sell goods."},
    5:  {"timing": "continuous", "desc": "When placing a ship, also take goods from an adjacent depot."},
    6:  {"timing": "continuous", "desc": "You may spend 1 silver to gain 2 workers (no limit)."},
    7:  {"timing": "continuous", "desc": "Livestock placement scores +1 VP per livestock tile that scores."},
    8:  {"timing": "continuous", "desc": "Workers adjust a die by 2 instead of 1."},
    9:  {"timing": "continuous", "desc": "May shift the die by 1 (free) when placing a building."},
    10: {"timing": "continuous", "desc": "May shift the die by 1 (free) when placing a ship or livestock."},
    11: {"timing": "continuous", "desc": "May shift the die by 1 (free) when placing a castle/mine/monastery."},
    12: {"timing": "continuous", "desc": "May shift the die by 1 (free) when taking a hex tile from the board."},
    13: {"timing": "continuous", "desc": "Gain 1 silver in addition when taking the 2-workers action."},
    14: {"timing": "continuous", "desc": "The 2-workers action gives 4 workers instead of 2."},
    15: {"timing": "endgame",    "desc": "Score 2 VP per different goods type in your sold pile."},
    16: {"timing": "endgame",    "desc": "Score 4 VP per market building placed."},
    17: {"timing": "endgame",    "desc": "Score 4 VP per watchtower building placed."},
    18: {"timing": "endgame",    "desc": "Score 4 VP per carpenter building placed."},
    19: {"timing": "endgame",    "desc": "Score 4 VP per church building placed."},
    20: {"timing": "endgame",    "desc": "Score 4 VP per warehouse building placed."},
    21: {"timing": "endgame",    "desc": "Score 4 VP per boarding house placed."},
    22: {"timing": "endgame",    "desc": "Score 4 VP per bank placed."},
    23: {"timing": "endgame",    "desc": "Score 4 VP per town hall placed."},
    24: {"timing": "endgame",    "desc": "Score 4 VP per different livestock type placed."},
    25: {"timing": "endgame",    "desc": "Score 1 VP per goods tile sold."},
    26: {"timing": "endgame",    "desc": "Score 3 VP per bonus tile owned."},
}
MONASTERY_IDS = list(range(1, 27))
# Which monastery tiles have black backs (reachable mainly via the black depot).
BLACK_MONASTERY_IDS = {21, 22, 23, 24, 25, 26}

# Each end-game "4 VP per building of type X" monastery maps to its building.
MONASTERY_BUILDING_SCORING = {
    16: "market", 17: "watchtower", 18: "carpenter", 19: "church",
    20: "warehouse", 21: "boarding", 22: "bank", 23: "townhall",
}

# ── Livestock kinds ─────────────────────────────────────────────────────────
ANIMALS = ["cow", "sheep", "pig", "chicken"]
LIVESTOCK_KINDS = [(a, c) for a in ANIMALS for c in (2, 3, 4)]  # 12 kinds

# ── Depot fill (2-player board) ─────────────────────────────────────────────
# Each numbered depot is refilled at the START OF EVERY PHASE with exactly the
# two hex TYPES listed for it — a fixed layout, NOT random draws. Livestock is the
# green tile. The specific building/monastery/animal still comes from
# the shuffled supply (so it varies by seed); only the types are fixed.
# Each numbered depot has FOUR ordered hex-tile spaces (the 4-player board); a
# game fills the first `num_players` of them each phase (2p→2, 3p→3, 4p→4). The
# first two match the original 2-player layout, so 2-player games are unchanged.
# Space types drawn by `_draw_type` from the shuffled supply (specific tile varies
# by seed). At 4p this drains the 124-colored / 40-black base supply almost exactly
# over 5 phases (ship 20, building 40, monastery 20, livestock 20, mine 10, castle 10).
DEPOT_PLAN = {
    1: ("ship", "building", "monastery", "livestock"),
    2: ("castle", "monastery", "building", "building"),
    3: ("livestock", "building", "ship", "monastery"),
    4: ("ship", "building", "livestock", "mine"),
    5: ("mine", "monastery", "building", "building"),
    6: ("livestock", "building", "castle", "ship"),   # space 3 castle: 3p B/D → mine (see engine)
}
DEPOT_FILL_2P = 2     # legacy 2-player fill (see depot_fill / black_fill below)
BLACK_FILL_2P = 4     # legacy 2-player black-depot fill


def depot_fill(num_players: int) -> int:
    """Hex tiles per numbered depot at phase start = one per active space (2/3/4)."""
    return num_players


def black_fill(num_players: int) -> int:
    """Central black-depot fill at phase start: 4/6/8 for 2/3/4 players.
    (The black supply is exactly 40 = 8 x 5 phases, sized for the 4-player game.)"""
    return 2 * num_players
GOODS_PER_PHASE = 5   # goods tiles distributed (one per round) each phase
START_SILVER = 1
# Starting workers are assigned by seat in engine.new_game (start player 1,
# next player 2, ...). This constant is only the floor / placeholder default.
START_WORKERS = 0
START_GOODS = 3       # random goods tiles each player starts with


_tile_counter = 0


def _mk(prefix: str) -> str:
    global _tile_counter
    _tile_counter += 1
    return f"{prefix}{_tile_counter}"


def _hex_tile(ttype: str, color: str, **extra) -> dict:
    t = {"id": _mk("h"), "kind": "hex", "type": ttype, "color": color}
    t.update(extra)
    return t


def build_supply() -> tuple[list[dict], list[dict]]:
    """Return (non_black_supply, black_supply) as fresh tile lists.

    Deterministic content (the *order* is randomized later by the seeded RNG).
    Produces exactly the 164-tile base-game supply: 124 colored-back +
    40 black-back (see module docstring for the per-type breakdown).
    """
    global _tile_counter
    _tile_counter = 0
    non_black: list[dict] = []
    black: list[dict] = []

    # Buildings: 8 types. 5 beige each (40), 2 black each (16).
    for bt in BUILDING_TYPES:
        for _ in range(5):
            non_black.append(_hex_tile("building", "beige", building=bt))
        for _ in range(2):
            black.append(_hex_tile("building", "beige", building=bt, black=True))

    # Livestock: 4 animals x 7 tiles = 28 (20 green + 8 black). Per animal:
    # colored = 2x count-2, 2x count-3, 1x count-4 (5); black = 1x count-3, 1x count-4 (2).
    for animal in ANIMALS:
        for count, n in ((2, 2), (3, 2), (4, 1)):
            for _ in range(n):
                non_black.append(_hex_tile("livestock", "green", animal=animal, count=count))
        for count in (3, 4):
            black.append(_hex_tile("livestock", "green", animal=animal, count=count, black=True))

    # Mines: 10 gray, 2 black.
    for _ in range(10):
        non_black.append(_hex_tile("mine", "gray"))
    for _ in range(2):
        black.append(_hex_tile("mine", "gray", black=True))

    # Ships: 20 blue, 6 black.
    for _ in range(20):
        non_black.append(_hex_tile("ship", "blue"))
    for _ in range(6):
        black.append(_hex_tile("ship", "blue", black=True))

    # Castles: 14 burgundy, 2 black (starting castles are created separately).
    for _ in range(14):
        non_black.append(_hex_tile("castle", "burgundy"))
    for _ in range(2):
        black.append(_hex_tile("castle", "burgundy", black=True))

    # Monasteries: 26 unique. effect_ids 1-20 yellow, 21-26 black.
    for eid in MONASTERY_IDS:
        tile = _hex_tile("monastery", "yellow", effect_id=eid)
        if eid in BLACK_MONASTERY_IDS:
            tile["black"] = True
            black.append(tile)
        else:
            non_black.append(tile)

    return non_black, black


def starting_castle_tile() -> dict:
    """A pre-placed starting castle (does not score and isn't drawn from supply)."""
    t = _hex_tile("castle", "burgundy", starting=True)
    return t


def build_goods_pool() -> list[dict]:
    """42 goods tiles (7 per color)."""
    pool: list[dict] = []
    for color in GOODS_COLORS:
        for _ in range(7):
            pool.append({"id": _mk("g"), "kind": "goods", "color": color})
    return pool
