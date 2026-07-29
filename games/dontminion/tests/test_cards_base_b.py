"""Base-set batch B rules tests: Bureaucrat, Bandit, Council Room, Library,
Mine, Sentry, Artisan. Arrangements mutate the game dict directly (the repo
idiom); conservation is covered by the soak, not here."""

import random

from games.dontminion import engine
from games.dontminion.cards import BANDIT_VICTIM_CHOOSES

A, B, C = "alice", "bob", "carol"
KB = ["Bureaucrat", "Bandit", "Council Room", "Library", "Mine", "Sentry",
      "Artisan", "Smithy", "Moat"]


def fresh(players=(A, B), seed=42):
    return engine.new_game(list(players), ["base"], seed=seed, kingdom=KB)


def give_hand(g, pid, cards):
    g["seats"][pid]["hand"] = list(cards)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def play(g, pid, card):
    return mv(g, pid, {"type": "play_action", "card": card})


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


# --- Bureaucrat ----------------------------------------------------------------

def test_bureaucrat_silver_onto_deck_and_single_victory_auto():
    g = fresh()
    give_hand(g, A, ["Bureaucrat"])
    give_hand(g, B, ["Estate", "Copper", "Copper", "Copper", "Copper"])
    silver_before = g["supply"]["Silver"]
    assert play(g, A, "Bureaucrat")[0]
    assert g["seats"][A]["deck"][0] == "Silver"
    assert g["supply"]["Silver"] == silver_before - 1
    # single distinct victory: forced -> auto-resolved, no frame
    assert g["pending_pid"] is None
    assert g["seats"][B]["deck"][0] == "Estate"
    assert len(g["seats"][B]["hand"]) == 4


def test_bureaucrat_no_victory_reveals_hand():
    g = fresh()
    give_hand(g, A, ["Bureaucrat"])
    give_hand(g, B, ["Copper"] * 5)
    assert play(g, A, "Bureaucrat")[0]
    assert g["pending_pid"] is None
    assert len(g["seats"][B]["hand"]) == 5
    reveals = [e for e in g["log"] if e["event"] == "reveal" and e["pid"] == B]
    assert reveals and sorted(reveals[-1]["cards"]) == ["Copper"] * 5


def test_bureaucrat_two_distinct_victories_prompts():
    g = fresh()
    give_hand(g, A, ["Bureaucrat"])
    give_hand(g, B, ["Estate", "Duchy", "Copper", "Copper", "Copper"])
    assert play(g, A, "Bureaucrat")[0]
    assert g["pending_pid"] == B and g["pending_kind"] == "choose_cards"
    assert sorted(g["pending"][-1]["constraint"]["cards"]) == ["Duchy", "Estate"]
    assert decide(g, B, cards=["Duchy"])[0]
    assert g["seats"][B]["deck"][0] == "Duchy"
    assert "Duchy" not in g["seats"][B]["hand"]


def test_bureaucrat_empty_silver_still_attacks_and_moat_blocks():
    g = fresh(players=[A, B, C])
    g["supply"]["Silver"] = 0
    give_hand(g, A, ["Bureaucrat"])
    give_hand(g, B, ["Moat", "Estate", "Copper", "Copper", "Copper"])
    give_hand(g, C, ["Estate", "Copper", "Copper", "Copper", "Copper"])
    assert play(g, A, "Bureaucrat")[0]
    assert decide(g, B, ids=["reveal_moat"])[0]      # window precedes the ability
    assert g["seats"][A]["deck"][0] != "Silver"      # pile was empty
    assert g["pending_pid"] is None                  # C's single victory auto-resolved
    assert "Estate" in g["seats"][B]["hand"]         # B untouched (immune)
    assert g["seats"][C]["deck"][0] == "Estate"      # C still hit


# --- Bandit ---------------------------------------------------------------------

def test_bandit_two_distinct_eligible_victim_chooses():
    assert BANDIT_VICTIM_CHOOSES is True
    g = fresh()
    give_hand(g, A, ["Bandit"])
    g["seats"][B]["deck"] = ["Silver", "Gold"] + g["seats"][B]["deck"]
    gold_before = g["supply"]["Gold"]
    assert play(g, A, "Bandit")[0]
    assert g["seats"][A]["discard"][-1] == "Gold"
    assert g["supply"]["Gold"] == gold_before - 1
    assert g["pending_pid"] == B                      # the VICTIM picks
    assert sorted(g["pending"][-1]["constraint"]["cards"]) == ["Gold", "Silver"]
    assert decide(g, B, cards=["Silver"])[0]
    assert "Silver" in g["trash"]
    assert g["seats"][B]["discard"][-1] == "Gold"     # the rest discarded
    assert g["seats"][B]["aside"] == []


def test_bandit_same_name_pair_no_prompt():
    g = fresh()
    give_hand(g, A, ["Bandit"])
    g["seats"][B]["deck"] = ["Silver", "Silver"] + g["seats"][B]["deck"]
    assert play(g, A, "Bandit")[0]
    assert g["pending_pid"] is None
    assert g["trash"].count("Silver") == 1
    assert g["seats"][B]["discard"][-1] == "Silver"


def test_bandit_no_eligible_discards_both():
    g = fresh()
    give_hand(g, A, ["Bandit"])
    g["seats"][B]["deck"] = ["Copper", "Estate"] + g["seats"][B]["deck"]
    assert play(g, A, "Bandit")[0]
    assert g["trash"] == []
    d = g["seats"][B]["discard"]
    assert "Copper" in d and "Estate" in d


def test_bandit_shuffles_when_short_and_empty_gold():
    g = fresh()
    g["supply"]["Gold"] = 0
    give_hand(g, A, ["Bandit"])
    g["seats"][B]["deck"] = ["Gold"]
    g["seats"][B]["discard"] = ["Copper", "Copper"]
    assert play(g, A, "Bandit")[0]
    assert "Gold" not in g["seats"][A]["discard"]     # no Gold to gain
    assert "Gold" in g["trash"]                       # revealed Gold trashed
    assert g["seats"][B]["aside"] == []
    shuffles = [e for e in g["log"] if e["event"] == "shuffle" and e["pid"] == B]
    assert shuffles                                    # had to shuffle to reveal 2


# --- Council Room ----------------------------------------------------------------

def test_council_room_everyone_draws():
    g = fresh(players=[A, B, C])
    give_hand(g, A, ["Council Room"])
    g["seats"][A]["deck"] = ["Copper"] * 6
    hb, hc = len(g["seats"][B]["hand"]), len(g["seats"][C]["hand"])
    assert play(g, A, "Council Room")[0]
    assert len(g["seats"][A]["hand"]) == 4 and g["buys"] == 2
    assert len(g["seats"][B]["hand"]) == hb + 1       # mandatory, no windows
    assert len(g["seats"][C]["hand"]) == hc + 1
    assert g["pending_pid"] is None


# --- Library ----------------------------------------------------------------------

def test_library_draws_to_seven_plain():
    g = fresh()
    give_hand(g, A, ["Library", "Copper", "Copper", "Copper", "Copper"])
    g["seats"][A]["deck"] = ["Copper"] * 8
    assert play(g, A, "Library")[0]
    assert len(g["seats"][A]["hand"]) == 7
    assert g["seats"][A]["aside"] == [] and g["pending_pid"] is None


def test_library_skip_actions_discarded_after_and_keep_counts():
    g = fresh()
    give_hand(g, A, ["Library", "Copper", "Copper", "Copper", "Copper"])
    g["seats"][A]["deck"] = ["Smithy", "Copper", "Smithy", "Copper", "Copper", "Copper"]
    assert play(g, A, "Library")[0]
    # first Smithy: skip it
    assert g["pending_kind"] == "choose_option"
    assert decide(g, A, ids=["aside"])[0]
    # second Smithy: keep it
    assert g["pending_kind"] == "choose_option"
    assert decide(g, A, ids=["hand"])[0]
    hand = g["seats"][A]["hand"]
    assert len(hand) == 7 and hand.count("Smithy") == 1
    assert g["seats"][A]["discard"].count("Smithy") == 1   # the skipped one
    assert g["seats"][A]["aside"] == []


def test_library_seven_plus_hand_draws_nothing():
    g = fresh()
    give_hand(g, A, ["Library"] + ["Copper"] * 7)
    deck_before = list(g["seats"][A]["deck"])
    assert play(g, A, "Library")[0]
    assert len(g["seats"][A]["hand"]) == 7
    assert g["seats"][A]["deck"] == deck_before and g["pending_pid"] is None


def test_library_mid_shuffle_excludes_set_asides():
    g = fresh()
    give_hand(g, A, ["Library", "Copper", "Copper"])
    g["seats"][A]["deck"] = ["Smithy"]
    g["seats"][A]["discard"] = ["Copper", "Copper", "Copper", "Copper", "Copper"]
    assert play(g, A, "Library")[0]
    assert decide(g, A, ids=["aside"])[0]              # skip the Smithy
    # the loop shuffled the discard to keep drawing — the aside Smithy stayed out
    assert "Smithy" not in g["seats"][A]["hand"]
    assert len(g["seats"][A]["hand"]) == 7
    assert g["seats"][A]["discard"].count("Smithy") == 1
    assert g["seats"][A]["aside"] == []


# --- Mine -------------------------------------------------------------------------

def test_mine_trash_copper_gain_silver_to_hand():
    g = fresh()
    give_hand(g, A, ["Mine", "Copper"])
    assert play(g, A, "Mine")[0]
    assert decide(g, A, cards=["Copper"])[0]
    assert "Copper" in g["trash"]
    assert g["pending_kind"] == "choose_pile"
    assert decide(g, A, pile="Silver")[0]
    assert "Silver" in g["seats"][A]["hand"]           # to HAND, not discard
    assert g["seats"][A]["discard"] == []


def test_mine_decline_and_no_treasures():
    g = fresh()
    give_hand(g, A, ["Mine", "Copper"])
    assert play(g, A, "Mine")[0]
    assert decide(g, A, cards=[])[0]                   # "may" — declined
    assert g["trash"] == [] and g["pending_pid"] is None
    g2 = fresh()
    give_hand(g2, A, ["Mine", "Estate"])
    assert play(g2, A, "Mine")[0]
    assert g2["pending_pid"] is None                   # nothing to trash at all


def test_mine_cap_respects_bridge():
    g = fresh()
    give_hand(g, A, ["Mine", "Copper"])
    g["turn_ctx"]["bridges"] = 3                       # Gold: cost 6 -> 3 == 0+3 cap
    assert play(g, A, "Mine")[0]
    assert decide(g, A, cards=["Copper"])[0]
    assert "Gold" in g["pending"][-1]["constraint"]["piles"]
    assert decide(g, A, pile="Gold")[0]
    assert "Gold" in g["seats"][A]["hand"]


# --- Sentry -----------------------------------------------------------------------

def test_sentry_trash_discard_order_sequence():
    g = fresh()
    give_hand(g, A, ["Sentry"])
    g["seats"][A]["deck"] = ["Copper", "Curse", "Estate", "Gold"]
    assert play(g, A, "Sentry")[0]                     # draws the Copper
    assert g["seats"][A]["hand"] == ["Copper"]
    assert g["pending"][-1]["constraint"]["purpose"] == "trash"
    assert decide(g, A, cards=["Curse"])[0]
    assert "Curse" in g["trash"]
    assert g["pending"][-1]["constraint"]["purpose"] == "discard"
    assert decide(g, A, cards=[])[0]
    assert g["pending_pid"] is None                    # 1 left: order auto-skipped
    assert g["seats"][A]["deck"][0] == "Estate"


def test_sentry_keep_both_orders():
    g = fresh()
    give_hand(g, A, ["Sentry"])
    g["seats"][A]["deck"] = ["Copper", "Curse", "Estate"]
    assert play(g, A, "Sentry")[0]
    assert decide(g, A, cards=[])[0]                   # trash none
    assert decide(g, A, cards=[])[0]                   # discard none
    assert g["pending_kind"] == "order_cards"
    assert decide(g, A, order=["Estate", "Curse"])[0]
    assert g["seats"][A]["deck"][:2] == ["Estate", "Curse"]


def test_sentry_trash_both_no_further_frames():
    g = fresh()
    give_hand(g, A, ["Sentry"])
    g["seats"][A]["deck"] = ["Copper", "Curse", "Curse"]
    assert play(g, A, "Sentry")[0]
    assert decide(g, A, cards=["Curse", "Curse"])[0]
    assert g["pending_pid"] is None
    assert g["trash"].count("Curse") == 2


# --- Artisan ----------------------------------------------------------------------

def test_artisan_gain_to_hand_then_topdeck():
    g = fresh()
    give_hand(g, A, ["Artisan", "Estate"])
    assert play(g, A, "Artisan")[0]
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Duchy" in piles and "Gold" not in piles    # cap $5
    assert decide(g, A, pile="Duchy")[0]
    assert "Duchy" in g["seats"][A]["hand"]
    assert g["pending"][-1]["constraint"]["purpose"] == "topdeck"
    assert decide(g, A, cards=["Estate"])[0]
    assert g["seats"][A]["deck"][0] == "Estate"
    assert "Duchy" in g["seats"][A]["hand"]


def test_artisan_can_topdeck_the_gained_card():
    g = fresh()
    give_hand(g, A, ["Artisan"])
    assert play(g, A, "Artisan")[0]
    assert decide(g, A, pile="Silver")[0]
    assert decide(g, A, cards=["Silver"])[0]
    assert g["seats"][A]["deck"][0] == "Silver"
    assert "Silver" not in g["seats"][A]["hand"]
