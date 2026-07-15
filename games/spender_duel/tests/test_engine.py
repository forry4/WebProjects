"""Engine rules tests for Spender Duel (pure engine, seeded, no server)."""
import copy
import json
import random
from collections import Counter

import pytest

from games.spender_duel import bot, cards as C, engine

A, B = "alice", "bob"


def fresh(seed=42):
    return engine.new_game([A, B], names={A: "Alice", B: "Bob"}, seed=seed)


def clear_board(g):
    g["board"] = [None] * 25


def put(g, cell, tok):
    g["board"][cell] = tok


def give(g, pid, **toks):
    for k, v in toks.items():
        g["players"][pid]["tokens"][k] += v


def find_card(**want):
    """First catalog card matching all given fields."""
    for c in C.CARDS.values():
        if all(c.get(k) == v for k, v in want.items()):
            return c
    raise AssertionError(f"no card with {want}")


def stage_pyramid(g, cid):
    """Force cid into its pyramid row (slot 0), removing it from wherever it is."""
    lvl = str(C.CARDS[cid]["level"])
    for row in g["pyramid"].values():
        for i, x in enumerate(row):
            if x == cid:
                row[i] = None
    for d in g["decks"].values():
        if cid in d:
            d.remove(cid)
    old = g["pyramid"][lvl][0]
    if old is not None:
        g["decks"][lvl].insert(0, old)
    g["pyramid"][lvl][0] = cid


def afford(g, pid, cid):
    """Give pid exactly enough tokens for cid (no bonuses assumed)."""
    for col, n in C.CARDS[cid]["cost"].items():
        give(g, pid, **{col: n})


def buy(g, pid, cid, **extra):
    return engine.apply_move(g, pid, {"type": "buy", "card_id": cid, "from": "pyramid", **extra})


def grant_purchase(g, pid, cid, as_color=None):
    """Teleport a card into pid's purchased pile (test setup shortcut)."""
    g["players"][pid]["purchased"].append({"id": cid, "as_color": as_color})


# ── setup ────────────────────────────────────────────────────────────────────

def test_new_game_setup():
    g = fresh()
    assert g["turn"] == A
    assert g["players"][B]["privileges"] == 1      # opponent of first player
    assert g["privileges_board"] == 2
    assert all(t is not None for t in g["board"])  # all 25 tokens dealt
    assert g["bag"] == []
    assert [len(r) for r in (g["pyramid"]["1"], g["pyramid"]["2"], g["pyramid"]["3"])] == [5, 4, 3]
    assert len(g["decks"]["1"]) == 25 and len(g["decks"]["2"]) == 20 and len(g["decks"]["3"]) == 10
    assert json.loads(json.dumps(g)) == g          # JSON-safe

def test_new_game_deterministic():
    assert fresh(7) == fresh(7)
    assert fresh(7) != fresh(8)


# ── 1. line takes ────────────────────────────────────────────────────────────

def line_take(g, cells):
    return engine.apply_move(g, A, {"type": "take", "cells": cells})

def test_take_lines_valid():
    for cells in ([12], [12, 13], [10, 11, 12],          # horizontal
                  [2, 7, 12],                            # vertical
                  [0, 6, 12], [4, 8, 12]):               # both diagonals
        g = fresh()
        clear_board(g)
        for i in cells:
            put(g, i, "white")
        ok, err = line_take(g, cells)
        assert ok, (cells, err)
        assert g["players"][A]["tokens"]["white"] == len(cells)

def test_take_rejects_bad_shapes():
    g0 = fresh()
    for cells, board in [
        ([10, 12], {10: "white", 12: "white"}),                 # gap
        ([10, 11, 12], {10: "white", 11: "gold", 12: "white"}),  # gold in set
        ([0, 1, 12], {0: "white", 1: "white", 12: "white"}),     # bent
        ([0, 12, 24], {0: "white", 12: "white", 24: "white"}),   # non-unit steps
        ([12, 12], {12: "white"}),                               # dupes
        ([], {}),                                                # empty
        ([10, 11, 12, 13], {i: "white" for i in range(10, 14)}),  # 4 tokens
        ([12], {}),                                              # empty cell
    ]:
        g = copy.deepcopy(g0)
        clear_board(g)
        for i, t in board.items():
            put(g, i, t)
        ok, _ = line_take(g, cells)
        assert not ok, cells

def test_take_middle_gold_blocks_but_pair_around_is_two_moves():
    g = fresh()
    clear_board(g)
    put(g, 10, "red"); put(g, 11, "gold"); put(g, 12, "red")
    ok, _ = line_take(g, [10, 11, 12])
    assert not ok
    ok, _ = line_take(g, [10, 12])   # skipping over the gold is a gap -> illegal
    assert not ok
    ok, _ = line_take(g, [10])
    assert ok


# ── 2. privileges ────────────────────────────────────────────────────────────

def test_take_three_same_grants_opponent_privilege():
    g = fresh()
    clear_board(g)
    for i in (10, 11, 12):
        put(g, i, "green")
    assert line_take(g, [10, 11, 12])[0]
    assert g["players"][B]["privileges"] == 2      # setup 1 + granted 1
    assert g["privileges_board"] == 1

def test_take_two_pearls_grants_privilege_even_in_mixed_triple():
    g = fresh()
    clear_board(g)
    put(g, 10, "pearl"); put(g, 11, "pearl"); put(g, 12, "red")
    assert line_take(g, [10, 11, 12])[0]
    assert g["players"][B]["privileges"] == 2

def test_privilege_scarcity_takes_from_opponent():
    g = fresh()
    g["privileges_board"] = 0
    g["players"][A]["privileges"] = 2
    g["players"][B]["privileges"] = 1
    assert engine._grant_privilege(g, B)
    assert g["players"][B]["privileges"] == 2 and g["players"][A]["privileges"] == 1

def test_privilege_noop_when_holding_all_three():
    g = fresh()
    g["privileges_board"] = 0
    g["players"][B]["privileges"] = 3
    g["players"][A]["privileges"] = 0
    assert not engine._grant_privilege(g, B)
    assert g["players"][B]["privileges"] == 3

def test_use_privilege_returns_scroll_to_pool():
    g = fresh()
    g["players"][A]["privileges"] = 1
    clear_board(g)
    put(g, 5, "blue"); put(g, 6, "red")
    ok, err = engine.apply_move(g, A, {"type": "use_privilege", "cell": 5})
    assert ok, err
    assert g["players"][A]["tokens"]["blue"] == 1
    assert g["players"][A]["privileges"] == 0
    assert g["privileges_board"] == 3
    # turn did NOT end — the mandatory action is still owed
    assert g["turn"] == A

def test_use_privilege_rejects_gold_and_empty():
    g = fresh()
    g["players"][A]["privileges"] = 1
    clear_board(g)
    put(g, 5, "gold")
    assert not engine.apply_move(g, A, {"type": "use_privilege", "cell": 5})[0]
    assert not engine.apply_move(g, A, {"type": "use_privilege", "cell": 6})[0]


# ── 3. replenish ─────────────────────────────────────────────────────────────

def test_replenish_fills_spiral_and_grants_opponent_privilege():
    g = fresh()
    clear_board(g)
    g["bag"] = ["white", "blue", "green"]
    ok, err = engine.apply_move(g, A, {"type": "replenish"})
    assert ok, err
    filled = [i for i, t in enumerate(g["board"]) if t is not None]
    assert sorted(filled) == sorted(C.SPIRAL_ORDER[:3])   # center-out spiral
    assert g["bag"] == []
    assert g["players"][B]["privileges"] == 2
    assert g["turn_flags"]["replenished"] is True

def test_replenish_deterministic_given_state():
    g1 = fresh(5)
    clear_board(g1)
    g1["bag"] = list("wbgrk")
    g1["bag"] = ["white", "blue", "green", "red", "black"]
    g2 = copy.deepcopy(g1)
    engine.apply_move(g1, A, {"type": "replenish"})
    engine.apply_move(g2, A, {"type": "replenish"})
    assert g1["board"] == g2["board"]

def test_replenish_illegal_when_bag_empty_or_board_full_or_repeated():
    g = fresh()
    assert not engine.apply_move(g, A, {"type": "replenish"})[0]  # board full (and bag empty)
    clear_board(g)
    g["bag"] = []
    assert not engine.apply_move(g, A, {"type": "replenish"})[0]  # bag empty
    g["bag"] = ["white", "blue"]
    assert engine.apply_move(g, A, {"type": "replenish"})[0]
    g["bag"] = ["red"]
    assert not engine.apply_move(g, A, {"type": "replenish"})[0]  # once per turn

def test_privilege_use_illegal_after_replenish_strict_order():
    g = fresh()
    g["players"][A]["privileges"] = 1
    clear_board(g)
    put(g, 5, "blue")
    g["bag"] = ["red"]
    assert engine.apply_move(g, A, {"type": "replenish"})[0]
    ok, err = engine.apply_move(g, A, {"type": "use_privilege", "cell": 5})
    assert not ok and "before replenish" in err

def test_forced_replenish_emergent():
    g = fresh()
    clear_board(g)
    put(g, 12, "gold")
    g["players"][A]["reserved"] = ["x", "y", "z"][:3]     # fake full reserve blocks gold+reserve
    g["players"][A]["reserved"] = [C.deck_ids(1)[0], C.deck_ids(1)[1], C.deck_ids(1)[2]]
    g["bag"] = ["white"]
    moves = engine.legal_moves(g, A)
    assert all(m["type"] == "replenish" for m in moves)   # only the forced replenish
    assert engine.apply_move(g, A, {"type": "replenish"})[0]
    moves = engine.legal_moves(g, A)
    assert any(m["type"] == "take" for m in moves)        # a mandatory action now exists


# ── 5. reserve ───────────────────────────────────────────────────────────────

def gold_at(g, cell=12):
    clear_board(g)
    put(g, cell, "gold")

def test_reserve_pyramid_takes_gold_and_refills():
    g = fresh()
    gold_at(g)
    cid = g["pyramid"]["2"][1]
    top = g["decks"]["2"][-1]
    ok, err = engine.apply_move(g, A, {"type": "reserve", "gold_cell": 12,
                                       "source": {"kind": "pyramid", "level": 2, "slot": 1}})
    assert ok, err
    p = g["players"][A]
    assert p["reserved"] == [cid]
    assert p["tokens"]["gold"] == 1
    assert g["board"][12] is None
    assert g["pyramid"]["2"][1] == top                    # refilled from deck top
    assert g["log"][-1].get("card_id") == cid             # face-up reserve is public

def test_reserve_deck_blind_no_card_id_in_log():
    g = fresh()
    gold_at(g)
    top = g["decks"]["3"][-1]
    ok, _ = engine.apply_move(g, A, {"type": "reserve", "gold_cell": 12,
                                     "source": {"kind": "deck", "level": 3}})
    assert ok
    assert g["players"][A]["reserved"] == [top]
    assert "card_id" not in g["log"][-1] and g["log"][-1]["from_deck"] is True

def test_reserve_requires_gold_and_free_slot():
    g = fresh()
    clear_board(g)
    put(g, 3, "red")
    ok, _ = engine.apply_move(g, A, {"type": "reserve", "gold_cell": 3,
                                     "source": {"kind": "deck", "level": 1}})
    assert not ok                                          # not a gold cell
    gold_at(g)
    g["players"][A]["reserved"] = list(g["decks"]["1"][:3])
    ok, err = engine.apply_move(g, A, {"type": "reserve", "gold_cell": 12,
                                       "source": {"kind": "deck", "level": 1}})
    assert not ok and "3 reserved" in err

def test_reserve_empty_slot_stays_empty_when_deck_out():
    g = fresh()
    gold_at(g)
    g["decks"]["3"] = []
    cid = g["pyramid"]["3"][0]
    ok, _ = engine.apply_move(g, A, {"type": "reserve", "gold_cell": 12,
                                     "source": {"kind": "pyramid", "level": 3, "slot": 0}})
    assert ok
    assert g["pyramid"]["3"][0] is None
    ok, _ = engine.apply_move(g, B, {"type": "reserve", "gold_cell": 12,
                                     "source": {"kind": "deck", "level": 3}})
    assert not ok                                          # empty deck blind draw (also not B's turn)


# ── 6. buy + abilities ───────────────────────────────────────────────────────

def test_buy_pays_to_bag_with_bonuses_and_gold():
    g = fresh()
    clear_board(g)
    # any L1 card with a >=3 cost in one color, no crowns/ability (keeps the chain quiet)
    card = next(c for c in C.CARDS.values()
                if c["level"] == 1 and c["ability"] is None and c["crowns"] == 0
                and c["bonus"] in C.COLORS and max(c["cost"].values()) >= 3)
    cid, cost = card["id"], card["cost"]
    col = max(cost, key=lambda k: cost[k])                 # the >=3 color
    stage_pyramid(g, cid)
    bonus_cid = next(c["id"] for c in C.CARDS.values()
                     if c["bonus"] == col and c["id"] != cid and c["crowns"] == 0)
    grant_purchase(g, A, bonus_cid)                        # -1 effective in col
    for c2, n in cost.items():
        give(g, A, **{c2: n})
    p = g["players"][A]
    p["tokens"][col] -= 2                                  # now short 1 after the bonus
    give(g, A, gold=1)
    bag_before = len(g["bag"])
    ok, err = buy(g, A, cid)
    assert ok, err
    spent = sum(cost.values()) - 1 - 1 + 1                 # cost - bonus - shorted + gold token
    assert len(g["bag"]) == bag_before + spent
    assert p["tokens"]["gold"] == 0
    assert {"id": cid, "as_color": None} in p["purchased"]

def test_buy_cost_floor_zero():
    g = fresh()
    clear_board(g)
    cid = find_card(level=1, bonus="blue", ability=None)["id"]
    stage_pyramid(g, cid)
    for _ in range(8):                                     # massive over-bonus, every color
        for col in C.COLORS:
            bcid = find_card(bonus=col)["id"]
            grant_purchase(g, A, bcid)
    cost = C.CARDS[cid]["cost"]
    pearls = cost.get("pearl", 0)
    give(g, A, pearl=pearls)                               # pearls have no bonuses
    ok, err = buy(g, A, cid)
    assert ok, err
    assert sum(g["players"][A]["tokens"].values()) == 0    # paid only the pearls

def test_buy_unaffordable_rejected():
    g = fresh()
    clear_board(g)
    cid = find_card(level=3, points=4)["id"]
    stage_pyramid(g, cid)
    assert not buy(g, A, cid)[0]

def test_buy_from_reserve():
    g = fresh()
    clear_board(g)
    cid = find_card(level=1, ability=None, bonus="green")["id"]
    for d in g["decks"].values():
        if cid in d:
            d.remove(cid)
    for row in g["pyramid"].values():
        for i, x in enumerate(row):
            if x == cid:
                row[i] = None
    g["players"][A]["reserved"] = [cid]
    afford(g, A, cid)
    ok, err = engine.apply_move(g, A, {"type": "buy", "card_id": cid, "from": "reserve"})
    assert ok, err
    assert g["players"][A]["reserved"] == []

def test_wild_requires_owned_bonus_and_as_color():
    g = fresh()
    clear_board(g)
    wild = find_card(level=1, bonus="wild")["id"]
    stage_pyramid(g, wild)
    afford(g, A, wild)
    ok, err = buy(g, A, wild, as_color="red")
    assert not ok and "bonus card" in err                  # no bonuses owned at all
    grant_purchase(g, A, find_card(bonus="red")["id"])
    ok, err = buy(g, A, wild, as_color="blue")
    assert not ok                                          # blue not owned
    ok, err = buy(g, A, wild, as_color="red")
    assert ok, err
    assert engine.bonuses_of(g["players"][A])["red"] == 2  # wild counts as red now

def test_wild_chaining_attaches_to_a_wild():
    g = fresh()
    clear_board(g)
    grant_purchase(g, A, find_card(bonus="black")["id"])
    grant_purchase(g, A, find_card(level=1, bonus="wild")["id"], as_color="black")
    wild2 = find_card(level=2, bonus="wild")["id"]
    stage_pyramid(g, wild2)
    afford(g, A, wild2)
    ok, err = buy(g, A, wild2, as_color="black")
    assert ok, err
    assert engine.bonuses_of(g["players"][A])["black"] == 3

def test_as_color_rejected_on_normal_card():
    g = fresh()
    clear_board(g)
    cid = find_card(level=1, bonus="white", ability=None)["id"]
    stage_pyramid(g, cid)
    afford(g, A, cid)
    assert not buy(g, A, cid, as_color="white")[0]

def test_ability_take_same_auto_single_and_pending_multi():
    g = fresh()
    clear_board(g)
    cid = find_card(level=1, ability="take_same", bonus="white")["id"]
    # single matching token -> auto
    put(g, 3, "white")
    stage_pyramid(g, cid)
    afford(g, A, cid)
    ok, err = buy(g, A, cid)
    assert ok, err
    assert g["players"][A]["tokens"]["white"] == 1 and g["board"][3] is None
    assert g["pending_pid"] is None
    # multiple matches -> pending with cell choice
    g2 = fresh()
    clear_board(g2)
    put(g2, 3, "white"); put(g2, 9, "white")
    cid2 = find_card(level=1, ability="take_same", bonus="white")["id"]
    stage_pyramid(g2, cid2)
    afford(g2, A, cid2)
    assert buy(g2, A, cid2)[0]
    assert g2["pending_kind"] == "take_same" and g2["pending_pid"] == A
    moves = engine.legal_moves(g2, A)
    assert {"type": "take_same", "cell": 9} in moves
    assert engine.apply_move(g2, A, {"type": "take_same", "cell": 9})[0]
    assert g2["board"][9] is None and g2["players"][A]["tokens"]["white"] == 1
    assert g2["pending_pid"] is None

def test_ability_take_same_no_match_ignored():
    g = fresh()
    clear_board(g)
    cid = find_card(level=1, ability="take_same", bonus="white")["id"]
    stage_pyramid(g, cid)
    afford(g, A, cid)
    assert buy(g, A, cid)[0]
    assert g["pending_pid"] is None
    assert g["players"][A]["tokens"]["white"] == 0

def test_ability_steal_never_gold_and_pending_choice():
    g = fresh()
    clear_board(g)
    cid = find_card(level=2, ability="steal")["id"]
    stage_pyramid(g, cid)
    afford(g, A, cid)
    give(g, B, gold=2)                                     # gold alone: nothing to steal
    assert buy(g, A, cid)[0]
    assert g["pending_pid"] is None
    assert g["players"][B]["tokens"]["gold"] == 2
    # two colors -> pending choice
    g2 = fresh()
    clear_board(g2)
    cid2 = find_card(level=2, ability="steal")["id"]
    stage_pyramid(g2, cid2)
    afford(g2, A, cid2)
    give(g2, B, red=1, pearl=1, gold=1)
    assert buy(g2, A, cid2)[0]
    assert g2["pending_kind"] == "steal"
    moves = engine.legal_moves(g2, A)
    assert {"type": "steal", "color": "pearl"} in moves
    assert all(m.get("color") != "gold" for m in moves)
    assert engine.apply_move(g2, A, {"type": "steal", "color": "pearl"})[0]
    assert g2["players"][A]["tokens"]["pearl"] == 1 and g2["players"][B]["tokens"]["pearl"] == 0

def test_ability_privilege_and_again():
    g = fresh()
    clear_board(g)
    cid = find_card(ability="privilege")["id"]
    stage_pyramid(g, cid)
    afford(g, A, cid)
    assert buy(g, A, cid)[0]
    assert g["players"][A]["privileges"] == 1
    # AGAIN: same player's turn continues after the buy
    g2 = fresh()
    clear_board(g2)
    cid2 = find_card(ability="again", level=1)["id"]
    stage_pyramid(g2, cid2)
    afford(g2, A, cid2)
    assert buy(g2, A, cid2)[0]
    assert g2["turn"] == A and not g2["again"]             # consumed into an extra turn
    assert g2["turn_number"] == 2


# ── 7. royals ────────────────────────────────────────────────────────────────

def crown_card(n):
    """A card with n crowns — colored-bonus preferred (no as_color needed);
    falls back to any (the only 3-crown card in the real deck is a wild)."""
    for c in C.CARDS.values():
        if c["crowns"] == n and c["bonus"] in C.COLORS:
            return c["id"]
    return find_card(crowns=n)["id"]

def test_royal_at_third_crown_and_jumped_threshold():
    g = fresh()
    clear_board(g)
    grant_purchase(g, A, crown_card(2))                    # 2 crowns: no royal yet
    cid = crown_card(2)                                    # 2 -> 4 crosses 3
    stage_pyramid(g, cid)
    afford(g, A, cid)
    assert buy(g, A, cid)[0]
    assert g["pending_kind"] == "choose_royal"
    ok, err = engine.apply_move(g, A, {"type": "choose_royal", "royal_id": "r0"})
    assert ok, err
    p = g["players"][A]
    assert p["royals"] == ["r0"] and p["royals_claimed"] == 1
    assert "r0" not in g["royals_available"]
    assert g["pending_pid"] is None and g["turn"] == B

def test_royal_double_cross_two_choices_and_royal_ability_chains():
    g = fresh()
    clear_board(g)
    give(g, B, red=1)
    grant_purchase(g, A, crown_card(2))                    # 2 crowns
    cid = crown_card(3)                                    # wild L3 with 3 crowns: 2 -> 5... need >=6
    grant_purchase(g, A, crown_card(1))                    # 3 total -> pre-claim royal 1 manually
    g["players"][A]["royals_claimed"] = 1                  # pretend first royal already taken
    g["players"][A]["royals"] = ["r0"]
    g["royals_available"] = ["r1", "r2", "r3"]
    stage = find_card(crowns=3)                            # 3 + 3 = 6 crosses the 6 threshold
    stage_pyramid(g, stage["id"])
    afford(g, A, stage["id"])
    as_color = None
    if stage["bonus"] == "wild":
        grant_purchase(g, A, find_card(bonus="red", level=1)["id"])
        as_color = "red"
    ok, err = buy(g, A, stage["id"], **({"as_color": as_color} if as_color else {}))
    assert ok, err
    assert g["pending_kind"] == "choose_royal"
    red_before = g["players"][A]["tokens"]["red"]
    # choose the STEAL royal -> its ability chains into an auto-steal (B has 1 color)
    assert engine.apply_move(g, A, {"type": "choose_royal", "royal_id": "r2"})[0]
    assert g["players"][A]["tokens"]["red"] == red_before + 1  # stolen via the royal
    assert g["players"][B]["tokens"]["red"] == 0
    assert g["players"][A]["royals_claimed"] == 2
    assert g["pending_pid"] is None

def test_royal_skip_forfeits():
    g = fresh()
    clear_board(g)
    cid = crown_card(3)
    stage_pyramid(g, cid)
    afford(g, A, cid)
    as_color = None
    if C.CARDS[cid]["bonus"] == "wild":
        grant_purchase(g, A, find_card(bonus="red", level=1)["id"])
        as_color = "red"
    assert buy(g, A, cid, **({"as_color": as_color} if as_color else {}))[0]
    assert g["pending_kind"] == "choose_royal"
    assert engine.apply_move(g, A, {"type": "skip_pending"})[0]
    p = g["players"][A]
    assert p["royals"] == [] and p["royals_claimed"] == 1  # forfeited, no re-fire
    assert g["pending_pid"] is None


# ── 8. discard to 10 ─────────────────────────────────────────────────────────

def test_discard_pending_after_take_over_ten():
    g = fresh()
    clear_board(g)
    put(g, 10, "red"); put(g, 11, "red"); put(g, 12, "blue")
    give(g, A, white=4, green=4, gold=1)                   # 9 held
    assert line_take(g, [10, 11, 12])[0]                   # 12 held
    assert g["pending_kind"] == "discard"
    assert g["pending"]["ctx"]["excess"] == 2
    moves = engine.legal_moves(g, A)
    assert {"type": "discard", "color": "gold"} in moves   # gold IS discardable
    assert not any(m["type"] == "skip_pending" for m in moves)
    bag0 = len(g["bag"])
    assert engine.apply_move(g, A, {"type": "discard", "color": "white"})[0]
    assert g["pending_kind"] == "discard"                  # still 11
    assert engine.apply_move(g, A, {"type": "discard", "color": "gold"})[0]
    assert g["pending_pid"] is None and g["turn"] == B
    assert sum(g["players"][A]["tokens"].values()) == 10
    assert len(g["bag"]) == bag0 + 2                       # discards go to the bag

def test_no_discard_at_exactly_ten():
    g = fresh()
    clear_board(g)
    put(g, 10, "red")
    give(g, A, white=4, green=4, blue=1)                   # 9 held
    assert line_take(g, [10])[0]
    assert g["pending_pid"] is None and g["turn"] == B


# ── 9. victory ───────────────────────────────────────────────────────────────

def win_by(g, pid, cards_needed):
    for cid in cards_needed:
        grant_purchase(g, pid, cid)

def end_a_turn(g):
    """A takes any single token to trigger the end-of-turn checks."""
    clear_board(g)
    put(g, 12, "white")
    return engine.apply_move(g, A, {"type": "take", "cells": [12]})

def test_victory_20_points():
    g = fresh()
    for c in C.CARDS.values():
        if c["points"] >= 4:
            grant_purchase(g, A, c["id"], as_color="red" if c["bonus"] == "wild" else None)
        if engine.points_of(g["players"][A]) >= 20:
            break
    assert engine.points_of(g["players"][A]) >= 20
    assert end_a_turn(g)[0]
    assert engine.is_over(g) and engine.winner(g) == A
    assert g["win_condition"] == "points"

def test_victory_10_crowns():
    g = fresh()
    total = 0
    for c in C.CARDS.values():
        if c["crowns"] and c["points"] < 4:
            grant_purchase(g, A, c["id"], as_color="red" if c["bonus"] == "wild" else None)
            total += c["crowns"]
        if total >= 10:
            break
    g["players"][A]["royals_claimed"] = 2                  # mute royal pendings for the test
    assert end_a_turn(g)[0]
    assert g["win_condition"] == "crowns" and engine.winner(g) == A

def test_victory_10_points_one_color_with_wild():
    g = fresh()
    pts = 0
    for c in C.CARDS.values():
        if c["bonus"] == "green" and c["points"]:
            grant_purchase(g, A, c["id"])
            pts += c["points"]
    for c in C.CARDS.values():
        if c["bonus"] == "wild" and c["points"] and pts < 10:
            grant_purchase(g, A, c["id"], as_color="green")
            pts += c["points"]
    assert pts >= 10, "placeholder deck must allow a 10-point green group"
    assert engine.points_of(g["players"][A]) < 20
    g["players"][A]["royals_claimed"] = 2
    assert end_a_turn(g)[0]
    assert g["win_condition"] == "color" and g["win_color"] == "green"

def test_no_color_victory_when_split():
    g = fresh()
    grant_purchase(g, A, find_card(bonus="white", points=4)["id"])
    grant_purchase(g, A, find_card(bonus="black", points=4)["id"])
    grant_purchase(g, A, find_card(bonus="green", points=4)["id"])
    g["players"][A]["royals_claimed"] = 2
    assert end_a_turn(g)[0]
    assert not engine.is_over(g)                           # 12 pts split across colors

def test_victory_preempts_again():
    g = fresh()
    clear_board(g)
    cid = find_card(ability="again", level=3)["id"] if any(
        c["ability"] == "again" and c["level"] == 3 for c in C.CARDS.values()) else None
    # build A to 19 points, then buy an again-card worth enough to win
    pts = 0
    for c in C.CARDS.values():
        if c["points"] >= 3 and c["ability"] is None and c["bonus"] != "wild" and pts <= 15:
            grant_purchase(g, A, c["id"])
            pts += c["points"]
    again_card = next(c for c in C.CARDS.values() if c["ability"] == "again" and c["points"] >= 2)
    stage_pyramid(g, again_card["id"])
    afford(g, A, again_card["id"])
    g["players"][A]["royals_claimed"] = 2
    kw = {}
    if again_card["bonus"] == "wild":
        kw["as_color"] = "white"
        grant_purchase(g, A, find_card(bonus="white", level=1)["id"])
    assert engine.points_of(g["players"][A]) + again_card["points"] >= 20
    assert buy(g, A, again_card["id"], **kw)[0]
    assert engine.is_over(g) and engine.winner(g) == A
    assert g["again"] is False                             # victory pre-empted the extra turn


# ── redaction ────────────────────────────────────────────────────────────────

def test_player_view_redaction():
    g = fresh()
    gold_at(g)
    assert engine.apply_move(g, A, {"type": "reserve", "gold_cell": 12,
                                    "source": {"kind": "deck", "level": 2}})[0]
    va = engine.player_view(g, A)
    vb = engine.player_view(g, B)
    assert "bag" not in va and "decks" not in va and "rng_state" not in va
    assert isinstance(va["bag_count"], int) and va["deck_counts"]["1"] >= 0
    assert va["players"][A]["reserved"] == g["players"][A]["reserved"]     # own: full
    assert vb["players"][A]["reserved"] == [{"level": 2, "facedown": True}]  # opponent: level only
    vs = engine.player_view(g, None)
    assert vs["players"][A]["reserved"][0]["facedown"] is True

def test_player_view_reveals_at_game_over():
    g = fresh()
    gold_at(g)
    engine.apply_move(g, A, {"type": "reserve", "gold_cell": 12,
                             "source": {"kind": "deck", "level": 2}})
    g["phase"] = "over"
    vb = engine.player_view(g, B)
    assert vb["players"][A]["reserved"] == g["players"][A]["reserved"]


# ── 10. conservation + soak ──────────────────────────────────────────────────

def token_census(g):
    c = Counter()
    for t in g["board"]:
        if t is not None:
            c[t] += 1
    c.update(g["bag"])
    for p in g["players"].values():
        for t, n in p["tokens"].items():
            if n:
                c[t] += n
    return c

def test_soak_bot_vs_bot():
    full = Counter(C.TOKEN_BAG)
    for seed in range(12):
        g = engine.new_game([A, B], seed=seed)
        rng = random.Random(seed + 1000)
        steps = 0
        while not engine.is_over(g) and steps < 2000:
            steps += 1
            actor = g["pending_pid"] or g["turn"]
            moves = engine.legal_moves(g, actor)
            assert moves, f"no legal moves for {actor} (seed {seed})"
            mv = bot.choose(g, actor, rng)
            ok, err = engine.apply_move(g, actor, mv)
            assert ok, (mv, err)
            assert token_census(g) == full, f"token leak (seed {seed}, step {steps})"
            assert json.loads(json.dumps(g)) == g
        assert engine.is_over(g), f"game did not terminate (seed {seed})"
        assert g["winner"] in (A, B)
        # privileges also conserve
        assert g["privileges_board"] + sum(p["privileges"] for p in g["players"].values()) == 3
