"""Static data for Spender Duel (Splendor Duel port): cards, royals, tokens, board.

Pure data + tiny constructors — no engine logic (mirrors castles_of_crimson/tiles.py).

Card schema (dict):
    id          "d{level}_{idx}" — deterministic, so an id-only move log resolves
    level       1 | 2 | 3
    points      prestige points (0+)
    crowns      0..3
    bonus       one of COLORS | "wild" (grey card — attaches to an owned color) | None
    bonus_count 1 | 2 (a few cards give a double bonus; wild/None are always 1)
    ability     None | "again" | "take_same" | "privilege" | "steal"
    cost        sparse dict over COLORS + "pearl" (there are NO pearl bonuses)

DATA_COMPLETE: True — the deck below is the REAL Splendor Duel card set,
transcribed from the BGG community card-list (v3) cross-checked against four
independent open-source implementations (every card supported by >=3 sources;
totals: 28 crowns, 92 points, abilities 6 again / 5 take_same / 5 steal /
5 privilege, 9 wild cards, 3 bonus-less cards, 5 double-bonus L2 cards).
The layout is per-color symmetric — a good corruption tell. Comments carry the
community list's card numbers (two of its ids collide; ours are positional).
"""
from __future__ import annotations

COLORS = ["white", "blue", "green", "red", "black"]
TOKENS = COLORS + ["pearl", "gold"]

# The 25-token bag: 4 of each gem color + 2 pearls + 3 gold.
TOKEN_BAG = [c for c in COLORS for _ in range(4)] + ["pearl"] * 2 + ["gold"] * 3

PYRAMID_SIZES = {1: 5, 2: 4, 3: 3}
DECK_SIZES = {1: 30, 2: 24, 3: 13}

# 5x5 board, row-major indexing (index = row*5 + col). SPIRAL_ORDER is the printed
# center-out refill order used by setup + replenish (center 12, inner ring, outer
# ring; every consecutive pair adjacent). Exact printed orientation is functionally
# cosmetic — the bag order is random — but fixed here for determinism.
SPIRAL_ORDER = [12, 7, 6, 11, 16, 17, 18, 13, 8, 3, 2, 1, 0, 5, 10, 15, 20, 21, 22, 23, 24, 19, 14, 9, 4]

DATA_COMPLETE = True

W, B, G, R, K, P = "white", "blue", "green", "red", "black", "pearl"

# Row format: (points, crowns, bonus, bonus_count, ability, cost)
_L1 = [
    (0, 0, W, 1, None,        {B: 1, G: 1, R: 1, K: 1}),       # 1-01
    (0, 1, W, 1, None,        {B: 3}),                          # 1-02
    (0, 0, W, 1, "again",     {B: 2, G: 2, P: 1}),              # 1-03
    (0, 0, W, 1, "take_same", {R: 2, K: 2}),                    # 1-04
    (1, 0, W, 1, None,        {G: 2, R: 3}),                    # 1-05
    (0, 0, B, 1, None,        {W: 1, G: 1, R: 1, K: 1}),        # 1-06
    (0, 1, B, 1, None,        {G: 3}),                          # 1-07
    (0, 0, B, 1, "again",     {G: 2, R: 2, P: 1}),              # 1-08
    (0, 0, B, 1, "take_same", {W: 2, K: 2}),                    # 1-09
    (1, 0, B, 1, None,        {R: 2, K: 3}),                    # 1-10
    (0, 0, G, 1, None,        {W: 1, B: 1, R: 1, K: 1}),        # 1-11
    (0, 1, G, 1, None,        {R: 3}),                          # 1-12
    (0, 0, G, 1, "again",     {R: 2, K: 2, P: 1}),              # 1-13
    (0, 0, G, 1, "take_same", {W: 2, B: 2}),                    # 1-14
    (1, 0, G, 1, None,        {W: 3, K: 2}),                    # 1-15
    (0, 0, R, 1, None,        {W: 1, B: 1, G: 1, K: 1}),        # 1-21
    (0, 1, R, 1, None,        {K: 3}),                          # 1-22
    (0, 0, R, 1, "again",     {W: 2, K: 2, P: 1}),              # 1-23
    (0, 0, R, 1, "take_same", {B: 2, G: 2}),                    # 1-24
    (1, 0, R, 1, None,        {W: 2, B: 3}),                    # 1-25
    (0, 0, K, 1, None,        {W: 1, B: 1, G: 1, R: 1}),        # 1-16
    (0, 1, K, 1, None,        {W: 3}),                          # 1-17
    (0, 0, K, 1, "again",     {W: 2, B: 2, P: 1}),              # 1-18
    (0, 0, K, 1, "take_same", {G: 2, R: 2}),                    # 1-19
    (1, 0, K, 1, None,        {B: 2, G: 3}),                    # 1-20
    (1, 0, "wild", 1, None,   {K: 4, P: 1}),                    # 1-26
    (0, 1, "wild", 1, None,   {W: 4, P: 1}),                    # 1-27
    (1, 0, "wild", 1, None,   {B: 2, R: 2, K: 1, P: 1}),        # 1-29
    (1, 0, "wild", 1, None,   {W: 2, G: 2, K: 1, P: 1}),        # 1-30
    (3, 0, None, 1, None,     {R: 4, P: 1}),                    # 1-28 (pure points, no bonus)
]
_L2 = [
    (2, 1, W, 1, None,        {G: 2, R: 2, K: 2, P: 1}),        # 2-01
    (1, 0, W, 1, "steal",     {B: 4, R: 3}),                    # 2-02
    (2, 0, W, 1, "privilege", {W: 4, K: 2, P: 1}),              # 2-03
    (1, 0, W, 2, None,        {B: 5, G: 2}),                    # 2-04 (double bonus)
    (2, 1, B, 1, None,        {W: 2, R: 2, K: 2, P: 1}),        # 2-05
    (1, 0, B, 1, "steal",     {G: 4, K: 3}),                    # 2-06
    (2, 0, B, 1, "privilege", {W: 2, B: 4, P: 1}),              # 2-07
    (1, 0, B, 2, None,        {G: 5, R: 2}),                    # 2-08 (double bonus)
    (2, 1, G, 1, None,        {W: 2, B: 2, K: 2, P: 1}),        # 2-09
    (1, 0, G, 1, "steal",     {W: 3, R: 4}),                    # 2-10
    (2, 0, G, 1, "privilege", {B: 2, G: 4, P: 1}),              # 2-11
    (1, 0, G, 2, None,        {R: 5, K: 2}),                    # 2-12 (double bonus)
    (2, 1, R, 1, None,        {W: 2, B: 2, G: 2, P: 1}),        # 2-17
    (1, 0, R, 1, "steal",     {B: 3, K: 4}),                    # 2-18
    (2, 0, R, 1, "privilege", {G: 2, R: 4, P: 1}),              # 2-19
    (1, 0, R, 2, None,        {W: 2, K: 5}),                    # 2-20 (double bonus)
    (2, 1, K, 1, None,        {B: 2, G: 2, R: 2, P: 1}),        # 2-13
    (1, 0, K, 1, "steal",     {W: 4, G: 3}),                    # 2-14
    (2, 0, K, 1, "privilege", {R: 2, K: 4, P: 1}),              # 2-15
    (1, 0, K, 2, None,        {W: 5, B: 2}),                    # 2-16 (double bonus)
    (2, 0, "wild", 1, None,   {G: 6, P: 1}),                    # 2-21
    (0, 2, "wild", 1, None,   {G: 6, P: 1}),                    # 2-22 (same cost as 2-21 — verified, not an error)
    (0, 2, "wild", 1, None,   {B: 6, P: 1}),                    # 2-23
    (5, 0, None, 1, None,     {B: 6, P: 1}),                    # 2-24 (pure points, no bonus)
]
_L3 = [
    (3, 2, W, 1, None,        {B: 3, R: 5, K: 3, P: 1}),        # 3-01
    (4, 0, W, 1, None,        {W: 6, B: 2, K: 2}),              # 3-02
    (3, 2, B, 1, None,        {W: 3, G: 3, K: 5, P: 1}),        # 3-03
    (4, 0, B, 1, None,        {W: 2, B: 6, G: 2}),              # 3-04
    (3, 2, G, 1, None,        {W: 5, B: 3, R: 3, P: 1}),        # 3-05
    (4, 0, G, 1, None,        {B: 2, G: 6, R: 2}),              # 3-06
    (3, 2, R, 1, None,        {B: 5, G: 3, K: 3, P: 1}),        # 3-09
    (4, 0, R, 1, None,        {G: 2, R: 6, K: 2}),              # 3-10
    (3, 2, K, 1, None,        {W: 3, G: 5, R: 3, P: 1}),        # 3-07
    (4, 0, K, 1, None,        {W: 2, R: 2, K: 6}),              # 3-08
    (3, 0, "wild", 1, "again", {R: 8}),                         # 3-11
    (0, 3, "wild", 1, None,   {K: 8}),                          # 3-12
    (6, 0, None, 1, None,     {W: 8}),                          # 3-13 (pure points, no bonus)
]
_RAW = {1: _L1, 2: _L2, 3: _L3}


def _make_card(level: int, idx: int, row: tuple) -> dict:
    pts, crowns, bonus, bcount, ability, cost = row
    return {
        "id": f"d{level}_{idx:02d}",
        "level": level,
        "points": pts,
        "crowns": crowns,
        "bonus": bonus,
        "bonus_count": bcount,
        "ability": ability,
        "cost": dict(cost),
    }


CARDS: dict[str, dict] = {}
for _lvl, _rows in _RAW.items():
    for _i, _row in enumerate(_rows):
        _c = _make_card(_lvl, _i, _row)
        CARDS[_c["id"]] = _c

ROYALS = {
    "r0": {"id": "r0", "points": 3, "ability": None},
    "r1": {"id": "r1", "points": 2, "ability": "again"},
    "r2": {"id": "r2", "points": 2, "ability": "steal"},
    "r3": {"id": "r3", "points": 2, "ability": "privilege"},
}


def deck_ids(level: int) -> list[str]:
    """All card ids of a level, in fixed catalog order (shuffled by the engine)."""
    return [cid for cid, c in CARDS.items() if c["level"] == level]
