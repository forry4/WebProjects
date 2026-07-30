"""Engine-kernel tests: setup, phases, frames, the attack/reaction window,
redaction, scoring, determinism, and the six exemplar cards.

Tests arrange positions by mutating the game dict directly (the repo's
board-fixture idiom); every mutation keeps the dict shape valid.
"""

import copy
import json
import random

import pytest

from games.dontminion import engine
from games.dontminion.cards import CARDS, pile_size

A, B, C, D = "alice", "bob", "carol", "dave"

# The provisional kingdom used until WP1 lands the full roster; new_game accepts
# an explicit kingdom list of any size (the forced-kingdom test seam).
K7 = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room", "Gardens"]


def fresh(players=(A, B), seed=42, kingdom=tuple(K7), expansions=("base",)):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom))


def give_hand(g, pid, cards):
    """Force a hand to exactly `cards` (conservation not preserved — tests that
    use this don't assert the conservation invariant)."""
    g["seats"][pid]["hand"] = list(cards)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


# --- setup -------------------------------------------------------------------

def test_setup_deal_and_supply():
    for n, players in ((2, [A, B]), (3, [A, B, C]), (4, [A, B, C, D])):
        g = fresh(players=players)
        assert g["players"] == players and g["turn"] == players[0]
        assert g["phase"] == "action" and g["actions"] == 1 and g["buys"] == 1
        for pid in players:
            s = g["seats"][pid]
            assert len(s["hand"]) == 5 and len(s["deck"]) == 5
            owned = s["deck"] + s["hand"]
            assert owned.count("Copper") == 7 and owned.count("Estate") == 3
        assert g["supply"]["Copper"] == 60 - 7 * n
        assert g["supply"]["Curse"] == 10 * (n - 1)
        assert g["supply"]["Estate"] == (8 if n == 2 else 12)
        assert g["supply"]["Gardens"] == (8 if n == 2 else 12)
        assert g["supply"]["Smithy"] == 10


def test_setup_validation():
    with pytest.raises(ValueError):
        engine.new_game([A], ["base"], kingdom=K7)
    with pytest.raises(ValueError):
        engine.new_game([A, B, C, D, "eve"], ["base"], kingdom=K7)
    with pytest.raises(ValueError):
        engine.new_game([A, B], [], kingdom=K7)
    with pytest.raises(ValueError):
        engine.new_game([A, B], ["seaside"], kingdom=K7)
    with pytest.raises(ValueError):
        engine.new_game([A, B], ["base"], kingdom=["Nonsense"])


def test_seeded_determinism():
    g1, g2 = fresh(seed=7), fresh(seed=7)
    assert json.dumps(g1, sort_keys=True) == json.dumps(g2, sort_keys=True)
    for g in (g1, g2):
        assert mv(g, A, {"type": "end_phase"}) == (True, None)
        assert mv(g, A, {"type": "play_all_treasures"}) == (True, None)
        assert mv(g, A, {"type": "end_phase"}) == (True, None)
    assert json.dumps(g1, sort_keys=True) == json.dumps(g2, sort_keys=True)


# --- draw / shuffle ----------------------------------------------------------

def test_draw_shuffles_only_when_needed():
    g = fresh()
    s = g["seats"][A]
    s["deck"] = ["Copper"]
    s["discard"] = ["Estate", "Estate", "Silver"]
    s["hand"] = []
    got = engine.draw(g, A, 2)
    assert got[0] == "Copper"           # remaining deck cards come first
    assert len(got) == 2 and len(s["deck"]) == 2 and s["discard"] == []


def test_draw_partial_when_short():
    g = fresh()
    s = g["seats"][A]
    s["deck"], s["discard"], s["hand"] = ["Copper"], [], []
    assert engine.draw(g, A, 5) == ["Copper"]
    assert s["hand"] == ["Copper"] and s["deck"] == []


def test_look_top_excludes_aside_from_shuffle():
    g = fresh()
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Gold"], ["Estate", "Estate"]
    moved = engine.look_top(g, A, 3)
    assert moved[0] == "Gold" and len(moved) == 3
    assert s["aside"] == moved and s["discard"] == [] and s["deck"] == []


# --- zone helpers ------------------------------------------------------------

def test_gain_destinations_and_empty_pile():
    g = fresh()
    assert engine.gain(g, A, "Silver")
    assert g["seats"][A]["discard"][-1] == "Silver"
    assert engine.gain(g, A, "Silver", dest="hand")
    assert g["seats"][A]["hand"][-1] == "Silver"
    assert engine.gain(g, A, "Silver", dest="deck")
    assert g["seats"][A]["deck"][0] == "Silver"
    g["supply"]["Witch"] = 0
    assert engine.gain(g, A, "Witch") is False


def test_trash_and_gain_from_trash():
    g = fresh()
    give_hand(g, A, ["Copper", "Estate"])
    engine.trash(g, A, ["Copper"])
    assert g["trash"] == ["Copper"]
    assert engine.gain_from_trash(g, A, "Copper")
    assert g["trash"] == [] and g["seats"][A]["discard"][-1] == "Copper"
    assert engine.gain_from_trash(g, A, "Gold") is False
    assert engine.trash_from_supply(g, "Moat")
    assert g["trash"] == ["Moat"] and g["supply"]["Moat"] == 9


def test_opponents_order_and_empty_piles():
    g = fresh(players=[A, B, C])
    assert engine.opponents(g, B) == [C, A]
    assert engine.count_empty_piles(g) == 0
    g["supply"]["Moat"] = 0
    g["supply"]["Curse"] = 0
    assert engine.count_empty_piles(g) == 2


def test_cost_with_bridges():
    g = fresh()
    assert engine.cost(g, "Smithy") == 4
    g["turn_ctx"]["bridges"] = 3
    assert engine.cost(g, "Smithy") == 1
    assert engine.cost(g, "Copper") == 0     # never negative
    g["turn_ctx"]["bridges"] = 9
    assert engine.cost(g, "Province") == 0


# --- move gate + phases ------------------------------------------------------

def test_gate_rejections():
    g = fresh()
    assert mv(g, B, {"type": "end_phase"}) == (False, "not your turn")
    ok, err = mv(g, A, {"type": "nonsense"})
    assert not ok and "unknown move" in err
    ok, err = decide(g, A, cards=[])
    assert not ok and err == "nothing to decide"
    give_hand(g, A, ["Copper"])
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Copper"})
    assert not ok and "buy phase" in err
    give_hand(g, A, ["Smithy"])
    mv(g, A, {"type": "end_phase"})
    ok, err = mv(g, A, {"type": "play_action", "card": "Smithy"})
    assert not ok and "action phase" in err


def test_action_phase_gates():
    g = fresh()
    give_hand(g, A, ["Smithy", "Copper"])
    ok, err = mv(g, A, {"type": "play_action", "card": "Copper"})
    assert not ok and err == "not an action card"
    ok, err = mv(g, A, {"type": "play_action", "card": "Witch"})
    assert not ok and err == "card not in hand"
    assert mv(g, A, {"type": "play_action", "card": "Smithy"})[0]
    give_hand(g, A, ["Smithy"] + g["seats"][A]["hand"])
    ok, err = mv(g, A, {"type": "play_action", "card": "Smithy"})
    assert not ok and err == "no actions left"


def test_buy_math_and_bought_gate():
    g = fresh()
    give_hand(g, A, ["Gold", "Silver", "Copper"])
    mv(g, A, {"type": "end_phase"})
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert g["coins"] == 6 and g["seats"][A]["in_play"] == ["Gold", "Silver", "Copper"]
    ok, err = mv(g, A, {"type": "buy", "card": "Province"})
    assert not ok and err == "can't afford it"
    assert mv(g, A, {"type": "buy", "card": "Gold"})[0]
    assert g["coins"] == 0 and g["buys"] == 0 and g["supply"]["Gold"] == 29
    assert g["seats"][A]["discard"][-1] == "Gold"
    ok, err = mv(g, A, {"type": "buy", "card": "Copper"})
    assert not ok and err == "no buys left"
    give_hand(g, A, ["Copper"])
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Copper"})
    assert not ok and err == "can't play treasures after buying"


def test_buy_empty_pile_and_unknown_pile():
    g = fresh()
    mv(g, A, {"type": "end_phase"})
    g["supply"]["Moat"] = 0
    g["coins"] = 10
    assert mv(g, A, {"type": "buy", "card": "Moat"}) == (False, "pile is empty")
    assert mv(g, A, {"type": "buy", "card": "Bandit"}) == (False, "no such pile")


def test_merchant_silver_hook():
    g = fresh()
    give_hand(g, A, ["Silver", "Silver"])
    mv(g, A, {"type": "end_phase"})
    g["turn_ctx"]["merchants"] = 2      # as if two Merchants were played
    assert mv(g, A, {"type": "play_treasure", "card": "Silver"})[0]
    assert g["coins"] == 4              # 2 + the one-time 2-Merchant bonus
    assert mv(g, A, {"type": "play_treasure", "card": "Silver"})[0]
    assert g["coins"] == 6              # second Silver: no bonus


def test_cleanup_and_turn_advance():
    g = fresh()
    give_hand(g, A, ["Smithy"])
    assert mv(g, A, {"type": "play_action", "card": "Smithy"})[0]
    # big enough deck that the cleanup draw needs no reshuffle (Smithy must
    # still be sitting in the discard afterwards)
    g["seats"][A]["deck"] = ["Copper"] * 6 + g["seats"][A]["deck"]
    mv(g, A, {"type": "end_phase"})
    g["turn_ctx"]["bridges"] = 2
    g["coins"] = 5
    assert mv(g, A, {"type": "end_phase"})[0]
    sa = g["seats"][A]
    assert sa["in_play"] == [] and len(sa["hand"]) == 5
    assert "Smithy" in sa["discard"]
    assert g["turn"] == B and g["phase"] == "action"
    assert g["actions"] == 1 and g["buys"] == 1 and g["coins"] == 0
    assert g["turn_ctx"]["bridges"] == 0
    assert g["seats"][A]["turns_taken"] == 1 and g["seats"][B]["turns_taken"] == 0


# --- game end + scoring ------------------------------------------------------

def _finish_turn(g, pid):
    if g["phase"] == "action":
        assert mv(g, pid, {"type": "end_phase"})[0]
    assert mv(g, pid, {"type": "end_phase"})[0]


def test_game_ends_on_provinces_at_end_of_turn():
    g = fresh()
    g["supply"]["Province"] = 0
    assert not g["over"]                 # mid-turn emptiness does not end it
    _finish_turn(g, A)
    assert g["over"] and g["scores"] and g["winners"]
    assert mv(g, B, {"type": "end_phase"}) == (False, "game is over")


def test_game_ends_on_three_empty_piles():
    g = fresh()
    g["supply"]["Moat"] = 0
    g["supply"]["Curse"] = 0
    _finish_turn(g, A)
    assert not g["over"]                 # two piles is not enough
    g["supply"]["Copper"] = 0
    _finish_turn(g, B)
    assert g["over"]


def test_scoring_gardens_and_tiebreaks():
    g = fresh()
    sa, sb = g["seats"][A], g["seats"][B]
    sa["deck"], sa["hand"], sa["discard"], sa["in_play"] = (
        ["Estate"] * 3 + ["Copper"] * 7, [], ["Gardens"] * 2 + ["Copper"] * 8, [])
    sb["deck"], sb["hand"], sb["discard"], sb["in_play"] = (
        ["Duchy", "Curse"], [], [], [])
    # A: 3 Estates + 2 Gardens x floor(20/10) = 3 + 4 = 7; B: 3 - 1 = 2
    s = engine.score_game(g)
    assert s[A]["vp"] == 7 and s[B]["vp"] == 2
    engine._finish_game(g)
    assert g["winners"] == [A]
    # vp tie -> fewest turns; full tie -> shared victory
    g2 = fresh()
    for pid in (A, B):
        st = g2["seats"][pid]
        st["deck"], st["hand"], st["discard"], st["in_play"] = ["Province"], [], [], []
    g2["seats"][A]["turns_taken"] = 5
    g2["seats"][B]["turns_taken"] = 4
    engine._finish_game(g2)
    assert g2["winners"] == [B]
    g2["over"] = False
    g2["seats"][A]["turns_taken"] = 4
    engine._finish_game(g2)
    assert g2["winners"] == [A, B]


def test_vp_map_tracks_every_move():
    g = fresh()
    assert g["vp"] == {A: 3, B: 3}
    mv(g, A, {"type": "end_phase"})
    g["coins"] = 8
    assert mv(g, A, {"type": "buy", "card": "Province"})[0]
    assert g["vp"][A] == 9


# --- decision validation -----------------------------------------------------

def test_choose_cards_validation():
    g = fresh()
    give_hand(g, A, ["Smithy", "Militia"])
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    # 2p, B has 5 cards, no reactions -> straight to B's discard-2 frame
    assert g["pending_kind"] == "choose_cards" and g["pending_pid"] == B
    ok, err = mv(g, A, {"type": "end_phase"})
    assert not ok and err == "not your decision"
    ok, err = mv(g, B, {"type": "end_phase"})
    assert not ok and "must resolve choose_cards" in err
    ok, err = decide(g, B, cards=["Gold", "Gold"])
    assert not ok and err == "cards not available"
    ok, err = decide(g, B, cards=g["seats"][B]["hand"][:1])
    assert not ok and "between 2 and 2" in err
    hand2 = g["seats"][B]["hand"][:2]
    assert decide(g, B, cards=hand2)[0]
    assert len(g["seats"][B]["hand"]) == 3 and g["pending_pid"] is None


def test_choose_option_validation():
    g = fresh()
    engine.push_choose_option(g, A, "Militia", "discard",
                              options=[{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}],
                              pick=1)
    ok, err = decide(g, A, ids=["x", "y"])
    assert not ok and "exactly 1" in err
    ok, err = decide(g, A, ids=["z"])
    assert not ok and err == "unknown option"


def test_order_place_name_pile_validation():
    g = fresh()
    engine.push_order_cards(g, A, "Smithy", "discard", cards=["Copper", "Estate"])
    ok, err = decide(g, A, order=["Copper", "Copper"])
    assert not ok
    g["pending"].clear(); engine._sync_pending(g)
    engine.push_place_in_deck(g, A, "Smithy", "discard", deck_card="Copper")
    n = len(g["seats"][A]["deck"])
    ok, err = decide(g, A, position=n + 1)
    assert not ok and f"0..{n}" in err
    g["pending"].clear(); engine._sync_pending(g)
    engine.push_name_card(g, A, "Smithy", "discard")
    ok, err = decide(g, A, card="Bandit")
    assert not ok
    g["pending"].clear(); engine._sync_pending(g)
    engine.push_choose_pile(g, A, "Smithy", "discard", piles=["Moat"])
    ok, err = decide(g, A, pile="Witch")
    assert not ok and err == "not an eligible pile"
    with pytest.raises(ValueError):
        engine.push_choose_pile(g, A, "Smithy", "discard", piles=[])


def test_legal_moves_and_sampling():
    g = fresh()
    give_hand(g, A, ["Smithy", "Copper", "Silver"])
    moves = engine.legal_moves(g, A)
    assert {"type": "play_action", "card": "Smithy"} in moves
    assert {"type": "end_phase"} in moves
    assert engine.legal_moves(g, B) == []
    mv(g, A, {"type": "end_phase"})
    moves = engine.legal_moves(g, A)
    assert {"type": "play_treasure", "card": "Copper"} in moves
    assert {"type": "play_all_treasures"} in moves
    assert {"type": "buy", "card": "Copper"} in moves       # cost 0 is buyable
    assert all(m != {"type": "buy", "card": "Gold"} for m in moves)
    engine.push_choose_cards(g, A, "Militia", "discard",
                             cards=["Copper", "Estate"], mn=0, mx=2, purpose="discard")
    dec = engine.legal_moves(g, A)
    assert {"type": "decision", "cards": []} in dec
    assert {"type": "decision", "cards": ["Copper", "Estate"]} in dec
    assert engine.legal_moves(g, B) == []
    rng = random.Random(0)
    for _ in range(20):
        payload = engine.sample_decision(g, A, rng)
        assert engine._validate_choice(g["pending"][-1], {"type": "decision", **payload})[0]


# --- exemplar cards ----------------------------------------------------------

def test_smithy_village_moat_play():
    g = fresh()
    give_hand(g, A, ["Village", "Smithy", "Moat"])
    g["seats"][A]["deck"] = ["Copper"] * 8    # enough for all the draws
    assert mv(g, A, {"type": "play_action", "card": "Village"})[0]
    assert g["actions"] == 2 and len(g["seats"][A]["hand"]) == 3
    assert mv(g, A, {"type": "play_action", "card": "Smithy"})[0]
    assert g["actions"] == 1 and len(g["seats"][A]["hand"]) == 5
    assert mv(g, A, {"type": "play_action", "card": "Moat"})[0]
    assert g["actions"] == 0 and len(g["seats"][A]["hand"]) == 6
    assert g["turn_ctx"]["actions_played"] == 3


def test_militia_attack_no_reactions():
    g = fresh(players=[A, B, C])
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Copper"] * 5)
    give_hand(g, C, ["Copper"] * 3)
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    assert g["coins"] == 2                       # no windows -> resolved through
    assert g["pending_pid"] == B                 # B first in turn order
    assert g["pending"][-1]["constraint"]["min"] == 2
    assert decide(g, B, cards=["Copper", "Copper"])[0]
    assert len(g["seats"][B]["hand"]) == 3
    assert g["pending_pid"] is None              # C had <=3 cards: no frame
    assert len(g["seats"][C]["hand"]) == 3


def test_reaction_window_precedes_play_ability():
    g = fresh(players=[A, B, C])
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Copper"] * 5)
    give_hand(g, C, ["Moat"] + ["Copper"] * 4)
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    # C holds Moat -> C's window opens BEFORE the attacker's own +$2
    assert g["coins"] == 0 and g["pending_pid"] == C
    ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
    assert ids == ["reveal_moat", "decline"]
    assert decide(g, C, ids=["reveal_moat"])[0]
    assert g["coins"] == 2                       # ability resolved after windows
    assert g["pending_pid"] == B                 # B still discards
    assert decide(g, B, cards=g["seats"][B]["hand"][:2])[0]
    assert len(g["seats"][C]["hand"]) == 5       # Moat holder untouched
    assert g["pending_pid"] is None


def test_witch_curses_in_turn_order_and_depletion():
    g = fresh(players=[A, B, C])
    g["supply"]["Curse"] = 1
    give_hand(g, A, ["Witch"])
    give_hand(g, B, ["Copper"])
    give_hand(g, C, ["Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Witch"})[0]
    assert g["pending_pid"] is None
    assert g["seats"][B]["discard"] == ["Curse"]     # first in turn order got it
    assert "Curse" not in g["seats"][C]["discard"]   # pile ran dry
    assert g["supply"]["Curse"] == 0


def test_all_opponents_immune_attacker_still_benefits():
    g = fresh()
    give_hand(g, A, ["Witch"])
    give_hand(g, B, ["Moat"] + ["Copper"] * 4)
    hand_before = len(g["seats"][A]["hand"]) - 1     # Witch leaves the hand
    assert mv(g, A, {"type": "play_action", "card": "Witch"})[0]
    assert decide(g, B, ids=["reveal_moat"])[0]
    assert len(g["seats"][A]["hand"]) == hand_before + 2   # attacker still draws
    assert g["seats"][B]["discard"] == []


def test_diplomat_reaction_chain():
    g = fresh()
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Diplomat"] + ["Copper"] * 4)
    g["seats"][B]["deck"] = ["Silver", "Gold"] + g["seats"][B]["deck"]
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
    assert ids == ["reveal_diplomat", "decline"]
    assert decide(g, B, ids=["reveal_diplomat"])[0]
    assert len(g["seats"][B]["hand"]) == 7           # drew Silver + Gold
    assert g["pending_kind"] == "choose_cards"
    assert decide(g, B, cards=["Copper", "Copper", "Copper"])[0]
    # hand now 4 (<5): no re-offer; Militia's discard-to-3 still hits
    assert g["pending_kind"] == "choose_cards" and g["pending_pid"] == B
    assert g["pending"][-1]["card"] == "Militia"
    assert decide(g, B, cards=["Copper"])[0]
    assert len(g["seats"][B]["hand"]) == 3
    assert g["coins"] == 2


def test_throne_room_doubles_and_double_attack():
    g = fresh()
    give_hand(g, A, ["Throne Room", "Smithy"])
    g["seats"][A]["deck"] = ["Copper"] * 6 + g["seats"][A]["deck"]
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert g["pending_kind"] == "choose_cards"
    assert decide(g, A, cards=["Smithy"])[0]
    assert len(g["seats"][A]["hand"]) == 6           # +3 twice
    assert g["turn_ctx"]["actions_played"] == 3      # TR + two Smithy plays
    assert g["actions"] == 0                         # only TR consumed an action

    g = fresh()
    give_hand(g, A, ["Throne Room", "Militia"])
    give_hand(g, B, ["Moat"] + ["Copper"] * 5)
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert decide(g, A, cards=["Militia"])[0]
    # first play: B's window
    assert g["pending_pid"] == B
    assert decide(g, B, ids=["reveal_moat"])[0]
    # second play: a NEW attack -> fresh window, Moat offerable again
    assert g["pending_pid"] == B
    ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
    assert "reveal_moat" in ids
    assert decide(g, B, ids=["decline"])[0]
    assert g["pending_pid"] == B and g["pending"][-1]["card"] == "Militia"
    assert decide(g, B, cards=g["seats"][B]["hand"][:3])[0]
    assert g["coins"] == 4                           # +$2 twice
    assert len(g["seats"][B]["hand"]) == 3


def test_throne_room_with_no_actions_or_skip():
    g = fresh()
    give_hand(g, A, ["Throne Room", "Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert g["pending_pid"] is None                  # no actions in hand: no frame
    g = fresh()
    give_hand(g, A, ["Throne Room", "Smithy"])
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert decide(g, A, cards=[])[0]                 # "may" — declined
    assert g["pending_pid"] is None
    assert "Smithy" in g["seats"][A]["hand"]


# --- turn undo (reveal-gated — the Duel model) --------------------------------
# give_hand changes the state AFTER new_game armed the snapshot, so these tests
# re-arm with engine._arm_undo once the position is staged.

def test_undo_steps_back_one_move_at_a_time():
    g = fresh()
    give_hand(g, A, ["Gold", "Copper"])
    engine._arm_undo(g)
    mv(g, A, {"type": "end_phase"})
    mv(g, A, {"type": "play_all_treasures"})
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert g["supply"]["Silver"] == 39 and g["coins"] == 1
    # 1st undo: just the buy comes back
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["supply"]["Silver"] == 40 and g["coins"] == 4
    assert g["phase"] == "buy" and sorted(g["seats"][A]["in_play"]) == ["Copper", "Gold"]
    assert g["log"][-1]["event"] == "undo"
    # 2nd undo: the treasures return to hand
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["coins"] == 0 and sorted(g["seats"][A]["hand"]) == ["Copper", "Gold"]
    assert g["phase"] == "buy" and g["seats"][A]["in_play"] == []
    # 3rd undo: back to the action phase — the start of the turn
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["phase"] == "action"
    ok, err = mv(g, A, {"type": "undo_turn"})
    assert not ok and err == "nothing to undo"
    assert mv(g, A, {"type": "end_phase"})[0]       # play continues after undos


def test_undo_depth_ships_and_rejected_moves_dont_count():
    g = fresh()
    give_hand(g, A, ["Gold"])
    engine._arm_undo(g)
    mv(g, A, {"type": "end_phase"})
    mv(g, A, {"type": "play_all_treasures"})
    v = engine.player_view(g, A)
    assert v["undo_depth"] == 2 and "undo_stack" not in v
    ok, _ = mv(g, A, {"type": "buy", "card": "Province"})   # can't afford: rejected
    assert not ok
    assert engine.player_view(g, A)["undo_depth"] == 2      # no phantom snapshot


def test_undo_ok_for_no_reveal_actions_blocked_after_draw():
    g = fresh()
    give_hand(g, A, ["Festival"])
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_action", "card": "Festival"})[0]
    assert g["coins"] == 2
    assert mv(g, A, {"type": "undo_turn"})[0]        # +actions/+buys/+$: no reveal
    assert "Festival" in g["seats"][A]["hand"] and g["coins"] == 0
    give_hand(g, A, ["Smithy"])
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_action", "card": "Smithy"})[0]
    ok, err = mv(g, A, {"type": "undo_turn"})        # a draw can't be un-seen
    assert not ok and "revealed" in err
    assert engine.player_view(g, A)["undo_depth"] == 0   # the reveal clears the stack


def test_undo_before_opponent_answers_but_not_after():
    g = fresh()
    give_hand(g, A, ["Militia", "Militia"])
    give_hand(g, B, ["Copper"] * 5)
    g["actions"] = 2
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    assert g["pending_pid"] == B
    assert mv(g, A, {"type": "undo_turn"})[0]        # B revealed nothing yet
    assert g["pending_pid"] is None
    assert g["seats"][A]["hand"].count("Militia") == 2
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    assert decide(g, B, cards=g["seats"][B]["hand"][:2])[0]
    ok, err = mv(g, A, {"type": "undo_turn"})        # B's choice = new information
    assert not ok and "revealed" in err


def test_undo_with_own_pending_open_and_after_self_reveal():
    g = fresh()
    give_hand(g, A, ["Workshop"])
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_action", "card": "Workshop"})[0]
    assert g["pending_kind"] == "choose_pile"
    assert mv(g, A, {"type": "undo_turn"})[0]        # own unrevealed pending: fine
    assert g["pending_pid"] is None and "Workshop" in g["seats"][A]["hand"]
    give_hand(g, A, ["Shanty Town", "Moat"])
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_action", "card": "Shanty Town"})[0]
    ok, err = mv(g, A, {"type": "undo_turn"})        # revealed OWN hand to others
    assert not ok and "revealed" in err


def test_undo_walks_back_through_own_decisions():
    """A decision by the turn player (Throne Room's pick) is its own undo step."""
    g = fresh()
    give_hand(g, A, ["Throne Room", "Militia"])
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert g["pending_kind"] == "choose_cards"
    assert decide(g, A, cards=[])[0]                 # declined the pick
    assert engine.player_view(g, A)["undo_depth"] == 2
    assert mv(g, A, {"type": "undo_turn"})[0]        # back to the open pick
    assert g["pending_kind"] == "choose_cards" and g["pending_pid"] == A
    assert mv(g, A, {"type": "undo_turn"})[0]        # back before Throne Room
    assert g["pending_pid"] is None
    assert "Throne Room" in g["seats"][A]["hand"] and g["actions"] == 1


def test_undo_gates_and_wire_shape():
    g = fresh()
    assert mv(g, B, {"type": "undo_turn"}) == (False, "not your turn")
    assert all(m["type"] != "undo_turn" for m in engine.legal_moves(g, A))
    v = engine.player_view(g, A)
    assert "undo_stack" not in v and "turn_undo" not in v
    assert v["turn_revealed"] is False and v["undo_depth"] == 0


# --- redaction ---------------------------------------------------------------

def test_player_view_redaction():
    g = fresh(players=[A, B, C])
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Copper"] * 5)
    give_hand(g, C, ["Copper"] * 2)
    mv(g, A, {"type": "play_action", "card": "Militia"})
    assert g["pending_pid"] == B
    va, vb = engine.player_view(g, A), engine.player_view(g, B)
    for view, viewer in ((va, A), (vb, B)):
        assert "rng_state" not in view and "seed" not in view
        assert "pending" not in view
        for p, seat in view["seats"].items():
            assert "deck" not in seat and "discard" not in seat and "aside" not in seat
            assert seat["deck_count"] >= 0 and "discard_view" in seat
            if p != viewer:
                assert "hand" not in seat
            else:
                assert isinstance(seat["hand"], list)
    assert vb["pending_view"]["kind"] == "choose_cards"
    assert vb["pending_view"]["constraint"]["min"] == 2
    assert va["pending_view"] == {"card": "Militia", "waiting_on": B}
    assert engine.player_view(g, None)["pending_view"]["waiting_on"] == B


def test_player_view_private_log_and_game_over_reveal():
    g = fresh()
    engine._log(g, A, "masq_pass", private_to=[A, B], card="Gold")
    engine._log(g, A, "masq_pass", private_to=[A], card="Silver")
    vb = engine.player_view(g, B)
    passed = [e for e in vb["log"] if e["event"] == "masq_pass"]
    assert len(passed) == 1 and passed[0]["card"] == "Gold"
    g["over"] = True
    vb = engine.player_view(g, B)
    for seat in vb["seats"].values():
        assert "hand" in seat and "deck" in seat and "discard" in seat


def test_wire_view_is_json_safe():
    g = fresh(players=[A, B, C])
    give_hand(g, A, ["Witch"])
    mv(g, A, {"type": "play_action", "card": "Witch"})
    for viewer in (A, B, C, None):
        json.dumps(engine.player_view(g, viewer))


# --- verbose log (round-3 UI: effect lines, depth, draw-name privacy) ----------

def test_log_plus_events_and_depth_under_a_play():
    g = fresh(kingdom=K7 + ["Festival"])
    give_hand(g, A, ["Festival"])
    n0 = len(g["log"])
    ok, err = mv(g, A, {"type": "play_action", "card": "Festival"})
    assert ok, err
    new = g["log"][n0:]
    assert [e["event"] for e in new] == ["play", "plus", "plus", "plus"]
    assert "d" not in new[0]                      # the play itself is top-level
    for e in new[1:]:
        assert e["d"] == 1                        # its effects indent under it
    assert {"actions": 2} .items() <= new[1].items()
    assert {"buys": 1} .items() <= new[2].items()
    assert {"coins": 2} .items() <= new[3].items()
    assert g["log_depth"] == 0                    # always zero at rest


def test_log_treasure_play_carries_coins_and_merchant_bonus():
    g = fresh(kingdom=K7 + ["Merchant"])
    g["phase"] = "buy"
    g["turn_ctx"]["merchants"] = 1
    give_hand(g, A, ["Silver"])
    ok, _ = mv(g, A, {"type": "play_treasure", "card": "Silver"})
    assert ok
    play = [e for e in g["log"] if e["event"] == "play" and e.get("card") == "Silver"][-1]
    assert play["coins"] == 2
    bonus = [e for e in g["log"] if e["event"] == "plus" and e.get("why") == "Merchant"]
    assert len(bonus) == 1 and bonus[0]["coins"] == 1
    assert g["coins"] == 3


def test_log_draw_names_are_owner_only_until_over():
    g = fresh()
    engine.draw(g, A, 2)
    e = [x for x in g["log"] if x["event"] == "draw"][-1]
    assert e["pid"] == A and len(e["cards"]) == e["n"] == 2
    va = engine.player_view(g, A)
    vb = engine.player_view(g, B)
    ea = [x for x in va["log"] if x["event"] == "draw" and x["pid"] == A][-1]
    eb = [x for x in vb["log"] if x["event"] == "draw" and x["pid"] == A][-1]
    assert ea["cards"] == e["cards"]
    assert "cards" not in eb and eb["n"] == 2     # count public, names private
    g["over"] = True
    eb = [x for x in engine.player_view(g, B)["log"]
          if x["event"] == "draw" and x["pid"] == A][-1]
    assert eb["cards"] == e["cards"]              # everything reveals at over


def test_log_discards_are_named_and_opponent_effects_indent():
    g = fresh(players=[A, B])
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Copper", "Copper", "Estate", "Estate", "Gold"])
    ok, _ = mv(g, A, {"type": "play_action", "card": "Militia"})
    assert ok
    ok, err = decide(g, B, cards=["Estate", "Estate"])
    assert ok, err
    disc = [e for e in g["log"] if e["event"] == "discard" and e["pid"] == B][-1]
    assert disc["cards"] == ["Estate", "Estate"] and disc["n"] == 2
    assert disc.get("d", 0) >= 1                  # indents under the Militia
