"""Intrigue batch B rules tests: Lurker, Masquerade, Swindler, Diplomat,
Secret Passage, Courtier, Minion, Patrol, Replace, Torturer."""

from games.dontminion import engine

A, B, C = "alice", "bob", "carol"
KIB = ["Lurker", "Masquerade", "Swindler", "Diplomat", "Secret Passage",
       "Courtier", "Minion", "Patrol", "Replace", "Torturer", "Harem",
       "Moat", "Smithy"]


def fresh(players=(A, B), seed=42):
    return engine.new_game(list(players), ["base", "intrigue"], seed=seed, kingdom=KIB)


def give_hand(g, pid, cards):
    g["seats"][pid]["hand"] = list(cards)


def play(g, pid, card):
    return engine.apply_move(g, pid, {"type": "play_action", "card": card})


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


# --- Lurker ---------------------------------------------------------------------

def test_lurker_both_branches():
    g = fresh()
    give_hand(g, A, ["Lurker", "Lurker"])
    g["actions"] = 2
    assert play(g, A, "Lurker")[0]
    assert decide(g, A, ids=["trash"])[0]
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Smithy" in piles and "Harem" not in piles and "Silver" not in piles
    assert decide(g, A, pile="Smithy")[0]
    assert "Smithy" in g["trash"] and g["supply"]["Smithy"] == 9
    assert play(g, A, "Lurker")[0]
    assert decide(g, A, ids=["gain"])[0]
    assert decide(g, A, cards=["Smithy"])[0]
    assert g["trash"] == [] and g["seats"][A]["discard"][-1] == "Smithy"


def test_lurker_gain_with_empty_trash_does_nothing():
    g = fresh()
    give_hand(g, A, ["Lurker"])
    assert play(g, A, "Lurker")[0]
    assert decide(g, A, ids=["gain"])[0]
    assert g["pending_pid"] is None


# --- Masquerade -------------------------------------------------------------------

def test_masquerade_three_player_ring():
    g = fresh(players=[A, B, C])
    give_hand(g, A, ["Masquerade", "Gold"])
    g["seats"][A]["deck"] = ["Copper", "Copper"] + g["seats"][A]["deck"]
    give_hand(g, B, ["Silver"])
    give_hand(g, C, ["Estate"])
    assert play(g, A, "Masquerade")[0]
    # sequential secret picks, in ring order A -> B -> C
    assert g["pending_pid"] == A
    assert decide(g, A, cards=["Gold"])[0]
    assert "Gold" in g["seats"][A]["hand"]            # stays put until execution
    assert g["pending_pid"] == B
    assert decide(g, B, cards=["Silver"])[0]
    assert g["pending_pid"] == C
    assert decide(g, C, cards=["Estate"])[0]
    # all passes executed at once: A->B, B->C, C->A
    assert sorted(g["seats"][B]["hand"]) == ["Gold"]
    assert sorted(g["seats"][C]["hand"]) == ["Silver"]
    assert "Estate" in g["seats"][A]["hand"] and "Gold" not in g["seats"][A]["hand"]
    # the trailing may-trash for the Masquerade player
    assert g["pending_pid"] == A and g["pending"][-1]["constraint"]["purpose"] == "trash"
    assert decide(g, A, cards=["Estate"])[0]
    assert "Estate" in g["trash"]
    # pass identities are private to the pair
    passes = [e for e in g["log"] if e["event"] == "pass"]
    assert len(passes) == 3
    assert all(sorted(e["private_to"]) != sorted([A, B, C]) for e in passes)
    a_to_b = [e for e in passes if e["pid"] == A][0]
    assert a_to_b["card"] == "Gold" and sorted(a_to_b["private_to"]) == sorted([A, B])


def test_masquerade_skips_empty_hands_and_is_not_an_attack():
    g = fresh(players=[A, B, C])
    give_hand(g, A, ["Masquerade", "Gold"])
    g["seats"][A]["deck"] = ["Copper", "Copper"] + g["seats"][A]["deck"]
    give_hand(g, B, [])                                # skipped by the ring
    give_hand(g, C, ["Moat"])                          # Moat CANNOT respond
    assert play(g, A, "Masquerade")[0]
    assert g["pending_pid"] == A                       # no reaction window
    assert decide(g, A, cards=["Gold"])[0]
    assert g["pending_pid"] == C
    assert decide(g, C, cards=["Moat"])[0]
    assert "Gold" in g["seats"][C]["hand"]             # A -> C
    assert "Moat" in g["seats"][A]["hand"]             # C -> A
    assert g["seats"][B]["hand"] == []


def test_masquerade_ring_of_one_no_pass():
    g = fresh()
    give_hand(g, A, ["Masquerade"])
    g["seats"][A]["deck"] = ["Copper", "Copper"] + g["seats"][A]["deck"]
    give_hand(g, B, [])
    assert play(g, A, "Masquerade")[0]
    assert g["pending"][-1]["constraint"]["purpose"] == "trash"   # straight to may-trash
    assert decide(g, A, cards=[])[0]
    assert g["pending_pid"] is None


# --- Swindler ---------------------------------------------------------------------

def test_swindler_attacker_chooses_same_cost_replacement():
    g = fresh()
    give_hand(g, A, ["Swindler"])
    g["seats"][B]["deck"] = ["Estate"] + g["seats"][B]["deck"]
    assert play(g, A, "Swindler")[0]
    assert g["coins"] == 2
    assert "Estate" in g["trash"]
    assert g["pending_pid"] == A                       # "that you choose"
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Estate" in piles and "Moat" in piles and "Silver" not in piles
    assert decide(g, A, pile="Moat")[0]
    assert g["seats"][B]["discard"][-1] == "Moat"      # the victim gains it


def test_swindler_no_same_cost_pile_gains_nothing():
    g = fresh()
    give_hand(g, A, ["Swindler"])
    g["seats"][B]["deck"] = ["Copper"] + g["seats"][B]["deck"]
    g["supply"]["Copper"] = 0
    g["supply"]["Curse"] = 0                           # no $0 pile left
    assert play(g, A, "Swindler")[0]
    assert g["pending_pid"] is None
    assert "Copper" in g["trash"]
    assert g["seats"][B]["discard"] == []


# --- Diplomat (action side) ----------------------------------------------------------

def test_diplomat_conditional_actions():
    g = fresh()
    give_hand(g, A, ["Diplomat", "Copper", "Copper", "Copper"])
    g["seats"][A]["deck"] = ["Silver"] * 3
    assert play(g, A, "Diplomat")[0]
    assert len(g["seats"][A]["hand"]) == 5             # 3 + 2 drawn
    assert g["actions"] == 2                           # <=5 in hand: +2 actions
    g = fresh()
    give_hand(g, A, ["Diplomat"] + ["Copper"] * 5)
    g["seats"][A]["deck"] = ["Silver"] * 3
    assert play(g, A, "Diplomat")[0]
    assert len(g["seats"][A]["hand"]) == 7
    assert g["actions"] == 0                           # >5: no bonus


# --- Secret Passage ---------------------------------------------------------------

def test_secret_passage_positions_and_public_position_log():
    for pos, idx in ((0, 0), (2, 2), (3, 3)):          # top, middle, bottom
        g = fresh()
        give_hand(g, A, ["Secret Passage", "Province"])
        g["seats"][A]["deck"] = ["Copper", "Copper", "Copper", "Copper"]
        assert play(g, A, "Secret Passage")[0]         # draws 2 -> deck len 2...
        # after drawing 2 the deck has 2 cards; clamp test positions accordingly
        deck_len = len(g["seats"][A]["deck"])
        p = min(pos, deck_len)
        assert decide(g, A, cards=["Province"])[0]
        assert g["pending_kind"] == "place_in_deck"
        assert g["pending"][-1]["constraint"]["deck_len"] == deck_len
        assert decide(g, A, position=p)[0]
        assert g["seats"][A]["deck"][p] == "Province"
        entry = [e for e in g["log"] if e["event"] == "secret_passage"][-1]
        assert entry["position"] == p and "card" not in entry
        assert "private_to" not in entry               # open information


# --- Courtier ---------------------------------------------------------------------

def test_courtier_bonus_count_matches_types():
    g = fresh()
    give_hand(g, A, ["Courtier", "Swindler", "Curse"])
    assert play(g, A, "Courtier")[0]
    assert decide(g, A, cards=["Swindler"])[0]         # action+attack: K=2
    assert g["pending"][-1]["constraint"]["pick"] == 2
    assert decide(g, A, ids=["coins", "gold"])[0]
    assert g["coins"] == 3
    assert g["seats"][A]["discard"][-1] == "Gold"
    g = fresh()
    give_hand(g, A, ["Courtier", "Curse"])
    assert play(g, A, "Courtier")[0]
    assert decide(g, A, cards=["Curse"])[0]            # K=1
    assert g["pending"][-1]["constraint"]["pick"] == 1
    assert decide(g, A, ids=["action"])[0]
    assert g["actions"] == 1


# --- Minion -----------------------------------------------------------------------

def test_minion_coins_mode():
    g = fresh()
    give_hand(g, A, ["Minion", "Copper"])
    give_hand(g, B, ["Copper"] * 5)
    assert play(g, A, "Minion")[0]
    assert decide(g, A, ids=["coins"])[0]
    assert g["coins"] == 2 and g["actions"] == 1
    assert len(g["seats"][B]["hand"]) == 5             # untouched in coins mode


def test_minion_discard_mode_window_first_and_immune_threading():
    g = fresh(players=[A, B, C])
    give_hand(g, A, ["Minion", "Copper", "Copper"])
    g["seats"][A]["deck"] = ["Silver"] * 5
    give_hand(g, B, ["Moat", "Copper", "Copper", "Copper", "Copper"])
    g["seats"][B]["deck"] = ["Silver"] * 5
    give_hand(g, C, ["Copper"] * 5)
    g["seats"][C]["deck"] = ["Silver"] * 5
    assert play(g, A, "Minion")[0]
    # the reaction window comes BEFORE the mode choice
    assert g["pending_pid"] == B and g["pending"][-1]["card"] == "__attack"
    assert decide(g, B, ids=["reveal_moat"])[0]
    assert g["pending_pid"] == A and g["pending"][-1]["card"] == "Minion"
    assert decide(g, A, ids=["discard"])[0]
    assert len(g["seats"][A]["hand"]) == 4             # discarded 2, drew 4
    assert sorted(g["seats"][B]["hand"])[0] == "Copper" and len(g["seats"][B]["hand"]) == 5
    assert len(g["seats"][C]["hand"]) == 4             # 5-card hand was hit
    assert "Moat" in g["seats"][B]["hand"]             # immune, kept everything


def test_minion_small_hands_untouched():
    g = fresh()
    give_hand(g, A, ["Minion"])
    g["seats"][A]["deck"] = ["Silver"] * 4
    give_hand(g, B, ["Copper"] * 4)                    # under 5: safe
    assert play(g, A, "Minion")[0]
    assert decide(g, A, ids=["discard"])[0]
    assert len(g["seats"][B]["hand"]) == 4


# --- Patrol -----------------------------------------------------------------------

def test_patrol_pockets_victories_and_orders_rest():
    g = fresh()
    give_hand(g, A, ["Patrol"])
    g["seats"][A]["deck"] = (["Copper", "Copper", "Copper"] +
                             ["Estate", "Curse", "Silver", "Smithy"])
    assert play(g, A, "Patrol")[0]
    hand = g["seats"][A]["hand"]
    assert len(hand) == 5 and "Estate" in hand and "Curse" in hand
    assert g["pending_kind"] == "order_cards"
    assert decide(g, A, order=["Smithy", "Silver"])[0]
    assert g["seats"][A]["deck"][:2] == ["Smithy", "Silver"]
    assert g["seats"][A]["aside"] == []


def test_patrol_single_leftover_needs_no_order():
    g = fresh()
    give_hand(g, A, ["Patrol"])
    g["seats"][A]["deck"] = ["Copper", "Copper", "Copper", "Estate", "Curse", "Harem", "Silver"]
    assert play(g, A, "Patrol")[0]                     # Harem is a victory too
    assert g["pending_pid"] is None
    assert g["seats"][A]["deck"][0] == "Silver"
    assert "Harem" in g["seats"][A]["hand"]


# --- Replace ----------------------------------------------------------------------

def test_replace_topdecks_action_treasure_and_curses_on_victory():
    g = fresh()
    give_hand(g, A, ["Replace", "Estate"])
    give_hand(g, B, ["Copper"] * 5)
    assert play(g, A, "Replace")[0]
    assert decide(g, A, cards=["Estate"])[0]
    assert decide(g, A, pile="Silver")[0]              # treasure -> onto the deck
    assert g["seats"][A]["deck"][0] == "Silver"
    assert g["seats"][B]["discard"] == []              # no curse for a treasure
    g = fresh()
    give_hand(g, A, ["Replace", "Smithy"])             # $4 -> cap 6
    give_hand(g, B, ["Copper"] * 5)
    assert play(g, A, "Replace")[0]
    assert decide(g, A, cards=["Smithy"])[0]
    assert decide(g, A, pile="Estate")[0]              # victory -> discard + curses
    assert g["seats"][A]["discard"][-1] == "Estate"
    assert g["seats"][B]["discard"] == ["Curse"]


def test_replace_dual_type_harem_topdecks_and_curses():
    g = fresh()
    give_hand(g, A, ["Replace", "Harem"])              # $6 -> cap 8
    give_hand(g, B, ["Copper"] * 5)
    assert play(g, A, "Replace")[0]
    assert decide(g, A, cards=["Harem"])[0]
    assert decide(g, A, pile="Harem")[0]               # treasure+victory
    assert g["seats"][A]["deck"][0] == "Harem"
    assert g["seats"][B]["discard"] == ["Curse"]


def test_replace_moat_blocks_the_curse():
    g = fresh()
    give_hand(g, A, ["Replace", "Smithy"])
    give_hand(g, B, ["Moat"] + ["Copper"] * 4)
    assert play(g, A, "Replace")[0]
    assert decide(g, B, ids=["reveal_moat"])[0]        # window precedes everything
    assert decide(g, A, cards=["Smithy"])[0]
    assert decide(g, A, pile="Estate")[0]
    assert g["seats"][B]["discard"] == []              # immune threaded to the curse


# --- Torturer ---------------------------------------------------------------------

def test_torturer_choices_never_filtered():
    g = fresh()
    give_hand(g, A, ["Torturer"])
    g["seats"][A]["deck"] = ["Silver"] * 4
    give_hand(g, B, ["Copper"])                        # 1-card hand: both options offered
    assert play(g, A, "Torturer")[0]
    assert len(g["seats"][A]["hand"]) == 3
    ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
    assert ids == ["discard", "curse"]
    assert decide(g, B, ids=["discard"])[0]
    assert g["pending"][-1]["constraint"]["min"] == 1  # clamped to what they have
    assert decide(g, B, cards=["Copper"])[0]
    assert g["seats"][B]["hand"] == []


def test_torturer_curse_to_hand_and_empty_pile():
    g = fresh()
    give_hand(g, A, ["Torturer"])
    g["seats"][A]["deck"] = ["Silver"] * 4
    give_hand(g, B, ["Copper"] * 5)
    assert play(g, A, "Torturer")[0]
    assert decide(g, B, ids=["curse"])[0]
    assert "Curse" in g["seats"][B]["hand"]            # to the HAND
    g = fresh()
    g["supply"]["Curse"] = 0
    give_hand(g, A, ["Torturer"])
    g["seats"][A]["deck"] = ["Silver"] * 4
    give_hand(g, B, ["Copper"] * 5)
    assert play(g, A, "Torturer")[0]
    assert decide(g, B, ids=["curse"])[0]              # picked an option they can't do
    assert "Curse" not in g["seats"][B]["hand"]
    assert len(g["seats"][B]["hand"]) == 5
