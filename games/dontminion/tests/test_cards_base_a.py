"""WP3a card tests — Cellar, Chapel, Harbinger, Merchant, Vassal, Workshop,
Moneylender, Poacher, Remodel, Laboratory, Festival, Market.

Positions are arranged by mutating the game dict directly (the repo's
board-fixture idiom). give_hand breaks card conservation, so no test here
asserts the census invariant (test_soak owns that).
"""

from games.dontminion import engine

A, B = "alice", "bob"

# Pinned kingdom = exactly this batch's 12 cards (the forced-kingdom test seam).
KA = ["Cellar", "Chapel", "Harbinger", "Merchant", "Vassal", "Workshop",
      "Moneylender", "Poacher", "Remodel", "Laboratory", "Festival", "Market"]


def fresh(players=(A, B), seed=42):
    return engine.new_game(list(players), ["base"], seed=seed, kingdom=list(KA))


def give_hand(g, pid, cards):
    """Force a hand to exactly `cards` (conservation not preserved)."""
    g["seats"][pid]["hand"] = list(cards)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


# --- Cellar ------------------------------------------------------------------

def test_cellar_discard_then_draw_with_midshuffle():
    g = fresh()
    give_hand(g, A, ["Cellar", "Estate", "Estate", "Estate"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Copper"], []
    assert mv(g, A, {"type": "play_action", "card": "Cellar"})[0]
    assert g["actions"] == 1                        # -1 for the play, +1 Cellar
    assert g["pending_kind"] == "choose_cards" and g["pending_pid"] == A
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 0 and c["max"] == 3 and c["purpose"] == "discard"
    assert decide(g, A, cards=["Estate", "Estate", "Estate"])[0]
    # All three discarded at once, THEN the 3-card draw: 1 from the old deck
    # plus a forced mid-draw shuffle that INCLUDES the just-discarded Estates.
    assert sorted(s["hand"]) == ["Copper", "Estate", "Estate"]
    assert s["deck"] == ["Estate"] and s["discard"] == []
    assert g["pending_pid"] is None


def test_cellar_decline_and_empty_hand():
    g = fresh()
    give_hand(g, A, ["Cellar", "Estate"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Copper"], []
    assert mv(g, A, {"type": "play_action", "card": "Cellar"})[0]
    assert decide(g, A, cards=[])[0]                # discard nothing, draw nothing
    assert s["hand"] == ["Estate"] and s["deck"] == ["Copper"] and s["discard"] == []
    g = fresh()
    give_hand(g, A, ["Cellar"])                     # hand empty after the play
    assert mv(g, A, {"type": "play_action", "card": "Cellar"})[0]
    assert g["pending_pid"] is None and g["actions"] == 1


# --- Chapel ------------------------------------------------------------------

def test_chapel_trashes_up_to_four():
    g = fresh()
    give_hand(g, A, ["Chapel", "Copper", "Copper", "Estate", "Estate", "Estate"])
    assert mv(g, A, {"type": "play_action", "card": "Chapel"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 0 and c["max"] == 4 and c["purpose"] == "trash"
    assert decide(g, A, cards=["Copper", "Copper", "Estate", "Estate"])[0]
    assert g["trash"] == ["Copper", "Copper", "Estate", "Estate"]
    assert g["seats"][A]["hand"] == ["Estate"]


def test_chapel_empty_hand_and_decline():
    g = fresh()
    give_hand(g, A, ["Chapel"])
    assert mv(g, A, {"type": "play_action", "card": "Chapel"})[0]
    assert g["pending_pid"] is None and g["trash"] == []
    g = fresh()
    give_hand(g, A, ["Chapel", "Estate"])
    assert mv(g, A, {"type": "play_action", "card": "Chapel"})[0]
    assert decide(g, A, cards=[])[0]
    assert g["trash"] == [] and g["seats"][A]["hand"] == ["Estate"]


# --- Harbinger ---------------------------------------------------------------

def test_harbinger_topdecks_from_discard():
    g = fresh()
    give_hand(g, A, ["Harbinger"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Copper", "Copper"], ["Silver", "Estate"]
    assert mv(g, A, {"type": "play_action", "card": "Harbinger"})[0]
    assert g["actions"] == 1 and s["hand"] == ["Copper"]
    c = g["pending"][-1]["constraint"]
    assert sorted(c["cards"]) == ["Estate", "Silver"]   # whole discard, to the actor
    assert c["min"] == 0 and c["max"] == 1
    assert decide(g, A, cards=["Silver"])[0]
    assert s["deck"] == ["Silver", "Copper"] and s["discard"] == ["Estate"]


def test_harbinger_decline_keeps_discard():
    g = fresh()
    give_hand(g, A, ["Harbinger"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Copper", "Copper"], ["Silver", "Estate"]
    assert mv(g, A, {"type": "play_action", "card": "Harbinger"})[0]
    assert decide(g, A, cards=[])[0]
    assert s["discard"] == ["Silver", "Estate"] and s["deck"] == ["Copper"]


def test_harbinger_no_frame_when_draw_consumes_discard():
    # +1 Card comes FIRST: its shuffle can leave the discard empty -> no frame.
    g = fresh()
    give_hand(g, A, ["Harbinger"])
    s = g["seats"][A]
    s["deck"], s["discard"] = [], ["Silver"]
    assert mv(g, A, {"type": "play_action", "card": "Harbinger"})[0]
    assert s["hand"] == ["Silver"] and s["discard"] == []
    assert g["pending_pid"] is None


# --- Merchant ----------------------------------------------------------------

def test_merchant_then_silver_end_to_end():
    g = fresh()
    give_hand(g, A, ["Merchant", "Silver", "Silver"])
    g["seats"][A]["deck"] = ["Copper", "Copper"]
    assert mv(g, A, {"type": "play_action", "card": "Merchant"})[0]
    assert g["actions"] == 1 and g["turn_ctx"]["merchants"] == 1
    assert mv(g, A, {"type": "end_phase"})[0]
    assert mv(g, A, {"type": "play_treasure", "card": "Silver"})[0]
    assert g["coins"] == 3                    # $2 + the Merchant bonus
    assert mv(g, A, {"type": "play_treasure", "card": "Silver"})[0]
    assert g["coins"] == 5                    # second Silver is plain


def test_two_merchants_bonus_first_silver_only():
    g = fresh()
    give_hand(g, A, ["Merchant", "Merchant", "Silver", "Silver"])
    g["seats"][A]["deck"] = ["Copper", "Copper"]
    assert mv(g, A, {"type": "play_action", "card": "Merchant"})[0]
    assert mv(g, A, {"type": "play_action", "card": "Merchant"})[0]
    assert g["turn_ctx"]["merchants"] == 2
    assert mv(g, A, {"type": "end_phase"})[0]
    assert mv(g, A, {"type": "play_treasure", "card": "Silver"})[0]
    assert g["coins"] == 4                    # $2 + $2 bonus, on the first only
    assert mv(g, A, {"type": "play_treasure", "card": "Silver"})[0]
    assert g["coins"] == 6


# --- Vassal ------------------------------------------------------------------

def test_vassal_nonaction_top_stays_discarded():
    g = fresh()
    give_hand(g, A, ["Vassal"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Gold", "Copper"], []
    assert mv(g, A, {"type": "play_action", "card": "Vassal"})[0]
    assert g["coins"] == 2
    assert g["pending_pid"] is None           # non-action: no choice offered
    assert s["discard"] == ["Gold"] and s["aside"] == [] and s["deck"] == ["Copper"]


def test_vassal_plays_top_action_without_consuming_actions():
    g = fresh()
    give_hand(g, A, ["Vassal"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Market", "Gold"], []
    assert mv(g, A, {"type": "play_action", "card": "Vassal"})[0]
    assert g["coins"] == 2 and g["actions"] == 0
    assert g["pending_kind"] == "choose_option" and g["pending_pid"] == A
    ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
    assert ids == ["play", "discard"]
    assert g["turn_ctx"]["actions_played"] == 1
    assert decide(g, A, ids=["play"])[0]
    # Market resolved: +1 Card +1 Action +1 Buy +$1 — free of game["actions"].
    assert g["turn_ctx"]["actions_played"] == 2
    assert g["actions"] == 1                  # 0 + Market's +1; none consumed
    assert s["in_play"] == ["Vassal", "Market"] and s["aside"] == []
    assert s["hand"] == ["Gold"]
    assert g["buys"] == 2 and g["coins"] == 3


def test_vassal_decline_discards_the_action():
    g = fresh()
    give_hand(g, A, ["Vassal"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Festival", "Copper"], []
    assert mv(g, A, {"type": "play_action", "card": "Vassal"})[0]
    assert decide(g, A, ids=["discard"])[0]
    assert s["discard"] == ["Festival"] and s["aside"] == []
    assert "Festival" not in s["in_play"]
    assert g["actions"] == 0 and g["turn_ctx"]["actions_played"] == 1


def test_vassal_empty_deck_and_discard():
    g = fresh()
    give_hand(g, A, ["Vassal"])
    s = g["seats"][A]
    s["deck"], s["discard"] = [], []
    assert mv(g, A, {"type": "play_action", "card": "Vassal"})[0]
    assert g["coins"] == 2 and g["pending_pid"] is None
    assert s["aside"] == [] and s["discard"] == []


# --- Workshop ----------------------------------------------------------------

def test_workshop_gains_up_to_four():
    g = fresh()
    give_hand(g, A, ["Workshop"])
    assert mv(g, A, {"type": "play_action", "card": "Workshop"})[0]
    assert g["pending_kind"] == "choose_pile"
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Silver" in piles and "Moneylender" in piles and "Estate" in piles
    assert "Festival" not in piles and "Gold" not in piles and "Province" not in piles
    assert decide(g, A, pile="Silver")[0]
    assert g["seats"][A]["discard"][-1] == "Silver"
    assert g["supply"]["Silver"] == 39


def test_workshop_respects_bridge():
    g = fresh()
    give_hand(g, A, ["Workshop"])
    g["turn_ctx"]["bridges"] = 1
    assert mv(g, A, {"type": "play_action", "card": "Workshop"})[0]
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Festival" in piles and "Duchy" in piles     # 5-1 = 4: now in reach
    assert "Gold" not in piles                          # 6-1 = 5: still out
    assert decide(g, A, pile="Festival")[0]
    assert g["seats"][A]["discard"][-1] == "Festival"


def test_workshop_skips_empty_piles():
    g = fresh()
    give_hand(g, A, ["Workshop"])
    g["supply"]["Silver"] = 0
    assert mv(g, A, {"type": "play_action", "card": "Workshop"})[0]
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Silver" not in piles and "Estate" in piles


# --- Moneylender -------------------------------------------------------------

def test_moneylender_trashes_copper_for_three():
    g = fresh()
    give_hand(g, A, ["Moneylender", "Copper", "Copper", "Estate"])
    assert mv(g, A, {"type": "play_action", "card": "Moneylender"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["cards"] == ["Copper"] and c["min"] == 0 and c["max"] == 1
    assert decide(g, A, cards=["Copper"])[0]
    assert g["trash"] == ["Copper"] and g["coins"] == 3
    assert g["seats"][A]["hand"] == ["Copper", "Estate"]


def test_moneylender_decline_and_no_copper():
    g = fresh()
    give_hand(g, A, ["Moneylender", "Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Moneylender"})[0]
    assert decide(g, A, cards=[])[0]
    assert g["coins"] == 0 and g["trash"] == []
    g = fresh()
    give_hand(g, A, ["Moneylender", "Estate"])      # no Copper: nothing happens
    assert mv(g, A, {"type": "play_action", "card": "Moneylender"})[0]
    assert g["pending_pid"] is None and g["coins"] == 0 and g["trash"] == []


# --- Poacher -----------------------------------------------------------------

def test_poacher_zero_empty_piles_no_frame():
    g = fresh()
    give_hand(g, A, ["Poacher", "Estate"])
    g["seats"][A]["deck"] = ["Copper"]
    assert mv(g, A, {"type": "play_action", "card": "Poacher"})[0]
    assert g["actions"] == 1 and g["coins"] == 1
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Estate"]
    assert g["pending_pid"] is None


def test_poacher_discards_one_per_empty_pile():
    g = fresh()
    give_hand(g, A, ["Poacher", "Estate", "Estate", "Copper"])
    g["seats"][A]["deck"] = ["Copper"]
    g["supply"]["Curse"] = 0
    g["supply"]["Chapel"] = 0
    assert mv(g, A, {"type": "play_action", "card": "Poacher"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 2 and c["max"] == 2          # exactly the empty-pile count
    assert decide(g, A, cards=["Estate", "Copper"])[0]
    assert g["seats"][A]["discard"] == ["Estate", "Copper"]
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Estate"]


def test_poacher_clamps_to_hand_size():
    g = fresh()
    give_hand(g, A, ["Poacher"])
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Copper"], []
    for p in ("Curse", "Chapel", "Cellar"):
        g["supply"][p] = 0
    assert mv(g, A, {"type": "play_action", "card": "Poacher"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1          # min(3 empty, 1 in hand)
    assert decide(g, A, cards=["Copper"])[0]
    assert s["hand"] == [] and s["discard"] == ["Copper"]


# --- Remodel -----------------------------------------------------------------

def test_remodel_empty_hand_no_frame():
    g = fresh()
    give_hand(g, A, ["Remodel"])
    assert mv(g, A, {"type": "play_action", "card": "Remodel"})[0]
    assert g["pending_pid"] is None
    assert g["trash"] == [] and g["seats"][A]["discard"] == []


def test_remodel_trash_then_gain():
    g = fresh()
    give_hand(g, A, ["Remodel", "Estate", "Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Remodel"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1 and sorted(c["cards"]) == ["Copper", "Estate"]
    assert decide(g, A, cards=["Estate"])[0]
    assert g["trash"] == ["Estate"]
    assert g["pending_kind"] == "choose_pile"
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Moneylender" in piles and "Silver" in piles      # cost <= 2+2
    assert "Festival" not in piles and "Duchy" not in piles  # cost 5
    assert decide(g, A, pile="Moneylender")[0]
    assert g["seats"][A]["discard"][-1] == "Moneylender"
    assert g["supply"]["Moneylender"] == 9


def test_remodel_trash_with_no_eligible_pile():
    g = fresh()
    give_hand(g, A, ["Remodel", "Copper"])
    for p in ("Copper", "Curse", "Estate", "Cellar", "Chapel"):
        g["supply"][p] = 0              # every cost-<=2 pile emptied
    assert mv(g, A, {"type": "play_action", "card": "Remodel"})[0]
    assert decide(g, A, cards=["Copper"])[0]
    assert g["trash"] == ["Copper"]     # the trash still happened
    assert g["pending_pid"] is None     # ... but there is no gain frame
    assert g["seats"][A]["discard"] == []


def test_remodel_respects_bridge():
    # Bridge lowers pile costs but Copper is already at the $0 floor, so the
    # $0+2 cap now reaches Silver (3-1=2) — the cutoff genuinely moves.
    g = fresh()
    give_hand(g, A, ["Remodel", "Copper"])
    g["turn_ctx"]["bridges"] = 1
    assert mv(g, A, {"type": "play_action", "card": "Remodel"})[0]
    assert decide(g, A, cards=["Copper"])[0]
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Silver" in piles and "Harbinger" in piles       # 3-1 = 2
    assert "Moneylender" not in piles                       # 4-1 = 3 > 2
    # Control: without the bridge, Silver is out of a Copper's reach.
    g2 = fresh()
    give_hand(g2, A, ["Remodel", "Copper"])
    assert mv(g2, A, {"type": "play_action", "card": "Remodel"})[0]
    assert decide(g2, A, cards=["Copper"])[0]
    piles2 = g2["pending"][-1]["constraint"]["piles"]
    assert "Silver" not in piles2 and "Estate" in piles2


# --- Laboratory / Festival / Market ------------------------------------------

def test_laboratory():
    g = fresh()
    give_hand(g, A, ["Laboratory"])
    g["seats"][A]["deck"] = ["Copper", "Silver", "Gold"]
    assert mv(g, A, {"type": "play_action", "card": "Laboratory"})[0]
    assert g["seats"][A]["hand"] == ["Copper", "Silver"]
    assert g["actions"] == 1 and g["buys"] == 1 and g["coins"] == 0


def test_festival():
    g = fresh()
    give_hand(g, A, ["Festival"])
    assert mv(g, A, {"type": "play_action", "card": "Festival"})[0]
    assert g["actions"] == 2 and g["buys"] == 2 and g["coins"] == 2
    assert g["seats"][A]["hand"] == []


def test_market():
    g = fresh()
    give_hand(g, A, ["Market"])
    g["seats"][A]["deck"] = ["Silver", "Gold"]
    assert mv(g, A, {"type": "play_action", "card": "Market"})[0]
    assert g["seats"][A]["hand"] == ["Silver"]
    assert g["actions"] == 1 and g["buys"] == 2 and g["coins"] == 1
