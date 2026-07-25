"""Spender's static card/noble data + the pure cost helpers.

A LEAF module: it imports nothing from this package (no FastAPI, no DB, no AI).
That is the whole point. The AI serving stack used to reach UP into the web layer
for this data —

    games/spender/ai/serving/engine.py:  from games.spender.main import LEVEL1, ...

— which inverted the documented layering (core -> features -> app) *inside* the
feature: importing the AI brain dragged in the router, the DB, and every AI
variant at module load, and the card tables couldn't move without touching the
serving module. Both sides now import this leaf instead.

Everything here is deterministic and side-effect-free except `build_deck`, which
shuffles. Card ids are `L{level}-{index}` where the index is the position in the
LEVEL* list below — that is what makes `card_catalog()` a constant map and lets
the move log store ids only.
"""
from __future__ import annotations

import random

GEM_COLORS = ["white", "blue", "green", "red", "black"]

# Multiplayer: human lobbies seat 2-4 players (AI games stay 2-player). Standard
# Splendor scales the gem bank by player count; gold is always 5, nobles = players+1.
MAX_PLAYERS = 4
_BANK_PER_COLOR = {2: 4, 3: 5, 4: 7}


def empty_gems() -> dict[str, int]:
    return {c: 0 for c in GEM_COLORS + ["gold"]}


def bank_for(n_players: int) -> dict[str, int]:
    """Starting gem bank for an n-player game (standard Splendor counts)."""
    per = _BANK_PER_COLOR.get(n_players, 4)
    bank = {c: per for c in GEM_COLORS}
    bank["gold"] = 5
    return bank


# ─── Card / Noble data ──────────────────────────────────────────────────────

LEVEL1: list[tuple] = [
    (0,"black",{"white":1,"blue":1,"green":1,"red":1}),(0,"black",{"green":2,"red":1}),
    (0,"black",{"white":2,"green":2}),(0,"black",{"green":1,"red":3,"black":1}),
    (0,"black",{"green":3}),(0,"black",{"white":1,"blue":2,"green":1,"red":1}),
    (0,"black",{"white":2,"blue":2,"red":1}),(1,"black",{"blue":4}),
    (0,"blue",{"white":1,"black":2}),(0,"blue",{"white":1,"green":1,"red":2,"black":1}),
    (0,"blue",{"white":1,"green":1,"red":1,"black":1}),(0,"blue",{"blue":1,"green":3,"red":1}),
    (0,"blue",{"black":3}),(0,"blue",{"white":1,"green":2,"red":2}),
    (0,"blue",{"green":2,"black":2}),(1,"blue",{"red":4}),
    (0,"green",{"white":2,"blue":1}),(0,"green",{"blue":2,"red":2}),
    (0,"green",{"white":1,"blue":3,"green":1}),(0,"green",{"white":1,"blue":1,"red":1,"black":1}),
    (0,"green",{"white":1,"blue":1,"red":1,"black":2}),(0,"green",{"blue":1,"red":2,"black":2}),
    (0,"green",{"red":3}),(1,"green",{"black":4}),
    (0,"red",{"white":3}),(0,"red",{"white":1,"red":1,"black":3}),
    (0,"red",{"blue":2,"green":1}),(0,"red",{"white":2,"green":1,"black":2}),
    (0,"red",{"white":2,"blue":1,"green":1,"black":1}),(0,"red",{"white":1,"blue":1,"green":1,"black":1}),
    (0,"red",{"white":2,"red":2}),(1,"red",{"white":4}),
    (0,"white",{"blue":2,"green":2,"black":1}),(0,"white",{"red":2,"black":1}),
    (0,"white",{"blue":1,"green":1,"red":1,"black":1}),(0,"white",{"blue":3}),
    (0,"white",{"blue":2,"black":2}),(0,"white",{"blue":1,"green":2,"red":1,"black":1}),
    (0,"white",{"white":3,"blue":1,"black":1}),(1,"white",{"green":4}),
]

LEVEL2: list[tuple] = [
    (1,"black",{"white":3,"blue":2,"green":2}),(1,"black",{"white":3,"green":3,"black":2}),
    (2,"black",{"blue":1,"green":4,"red":2}),(2,"black",{"white":5}),
    (2,"black",{"green":5,"red":3}),(3,"black",{"black":6}),
    (1,"blue",{"blue":2,"green":2,"red":3}),(1,"blue",{"blue":2,"green":3,"black":3}),
    (2,"blue",{"white":5,"blue":3}),(2,"blue",{"blue":5}),
    (2,"blue",{"white":2,"red":1,"black":4}),(3,"blue",{"blue":6}),
    (1,"green",{"white":3,"green":2,"red":3}),(1,"green",{"white":2,"blue":3,"black":2}),
    (2,"green",{"white":4,"blue":2,"black":1}),(2,"green",{"green":5}),
    (2,"green",{"blue":5,"green":3}),(3,"green",{"green":6}),
    (1,"red",{"blue":3,"red":2,"black":3}),(1,"red",{"white":2,"red":2,"black":3}),
    (2,"red",{"white":1,"blue":4,"green":2}),(2,"red",{"white":3,"black":5}),
    (2,"red",{"black":5}),(3,"red",{"red":6}),
    (1,"white",{"green":3,"red":2,"black":2}),(1,"white",{"white":2,"blue":3,"red":3}),
    (2,"white",{"green":1,"red":4,"black":2}),(2,"white",{"red":5}),
    (2,"white",{"red":5,"black":3}),(3,"white",{"white":6}),
]

LEVEL3: list[tuple] = [
    (3,"black",{"white":3,"blue":3,"green":5,"red":3}),(4,"black",{"red":7}),
    (4,"black",{"green":3,"red":6,"black":3}),(5,"black",{"red":7,"black":3}),
    (3,"blue",{"white":3,"green":3,"red":3,"black":5}),(4,"blue",{"white":7}),
    (4,"blue",{"white":6,"blue":3,"black":3}),(5,"blue",{"white":7,"blue":3}),
    (3,"green",{"white":5,"blue":3,"red":3,"black":3}),(4,"green",{"white":3,"blue":6,"green":3}),
    (4,"green",{"blue":7}),(5,"green",{"blue":7,"green":3}),
    (3,"red",{"white":3,"blue":5,"green":3,"black":3}),(4,"red",{"green":7}),
    (4,"red",{"blue":3,"green":6,"red":3}),(5,"red",{"green":7,"red":3}),
    (3,"white",{"blue":3,"green":3,"red":5,"black":3}),(4,"white",{"black":7}),
    (4,"white",{"white":3,"red":3,"black":6}),(5,"white",{"white":3,"black":7}),
]

ALL_NOBLES = [
    {"id":"n1","points":3,"req":{"red":4,"green":4}},
    {"id":"n2","points":3,"req":{"blue":4,"green":4}},
    {"id":"n3","points":3,"req":{"blue":4,"white":4}},
    {"id":"n4","points":3,"req":{"white":4,"black":4}},
    {"id":"n5","points":3,"req":{"black":4,"red":4}},
    {"id":"n6","points":3,"req":{"black":3,"red":3,"green":3}},
    {"id":"n7","points":3,"req":{"black":3,"red":3,"white":3}},
    {"id":"n8","points":3,"req":{"black":3,"blue":3,"white":3}},
    {"id":"n9","points":3,"req":{"green":3,"blue":3,"red":3}},
    {"id":"n10","points":3,"req":{"green":3,"blue":3,"white":3}},
]


# ─── Deck construction ──────────────────────────────────────────────────────

def make_card(level: int, data: tuple, idx: int) -> dict:
    pts, bonus, cost = data
    return {"id": f"L{level}-{idx}", "level": level, "points": pts, "bonus": bonus, "cost": cost}


def build_deck() -> dict:
    l1 = [make_card(1, d, i) for i, d in enumerate(LEVEL1)]
    l2 = [make_card(2, d, i) for i, d in enumerate(LEVEL2)]
    l3 = [make_card(3, d, i) for i, d in enumerate(LEVEL3)]
    random.shuffle(l1); random.shuffle(l2); random.shuffle(l3)
    return {"L1": l1, "L2": l2, "L3": l3}


def card_catalog() -> dict:
    """Static id -> {level, points, bonus, cost} map for every card in the deck.
    The deck is deterministic (ids are LEVEL-list indices like 'L2-7'), so this is
    constant across games. Used to resolve the id-only move log (the log stores
    card_id, not the full card) when analysing a game outside the live client."""
    out: dict = {}
    for lvl, data in ((1, LEVEL1), (2, LEVEL2), (3, LEVEL3)):
        for i, d in enumerate(data):
            c = make_card(lvl, d, i)
            out[c["id"]] = {"level": c["level"], "points": c["points"],
                            "bonus": c["bonus"], "cost": c["cost"]}
    return out


# ─── Cost helpers (pure) ────────────────────────────────────────────────────

def bonuses_from(purchased: list[dict]) -> dict[str, int]:
    b = empty_gems()
    for card in purchased:
        b[card["bonus"]] = b.get(card["bonus"], 0) + 1
    return b


def can_afford(cost: dict, tokens: dict, bonuses: dict) -> bool:
    gold_needed = 0
    for c in GEM_COLORS:
        need = max(0, cost.get(c, 0) - bonuses.get(c, 0))
        have = tokens.get(c, 0)
        if have < need:
            gold_needed += need - have
    return gold_needed <= tokens.get("gold", 0)


def calc_spend(cost: dict, tokens: dict, bonuses: dict) -> dict[str, int]:
    spend = empty_gems()
    for c in GEM_COLORS:
        need = max(0, cost.get(c, 0) - bonuses.get(c, 0))
        have = min(tokens.get(c, 0), need)
        spend[c] = have
        spend["gold"] = spend.get("gold", 0) + (need - have)
    return spend
