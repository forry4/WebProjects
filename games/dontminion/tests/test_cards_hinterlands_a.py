"""Hinterlands batch-A card tests — Border Village, Cartographer, Cauldron,
Crossroads, Develop, Farmland, Guard Dog, Haggler, Highway, Inn, Margrave,
Oasis, Wheelwright, Witch's Hut.

Positions are arranged by mutating the game dict directly (the repo's
board-fixture idiom). give_hand breaks card conservation, so no test here
asserts the census invariant (test_soak owns that).

Direct engine.gain(...) calls must be followed by engine._drive(g) — the
when-gain trigger parks an auto frame that only apply_move would drive.

Headline rulings pinned here (hinterlands-spec.md):
  * Highway is turn_ctx["bridges"] — cumulative per play, and it survives the
    Highway being trashed from play (a while-in-play modifier would not).
  * "A cheaper card" is STRICT (cost_lt): Border Village and Haggler never
    offer an equally-priced pile.
  * Border Village / Farmland / Inn fire on ANY gain of themselves, not only
    on a buy, and their gained card lands in the DISCARD pile even when the
    trigger card was gained to the deck.
  * Haggler 2022 is a per-play until="turn_end" watcher: only cards gained
    AFTER the play count, only bought ones fire it, Victory cards are excluded,
    it stacks per play and survives Haggler being trashed from play.
  * Develop gains both cards onto the DECK in a player-chosen order, so the
    second ends up on top; the cost is read at trash time.
  * Cauldron counts Actions gained from TURN START but only fires if the third
    lands after it was played ("the first two could be gained before").
  * Witch's Hut reveals both cards BEFORE discarding them, and its attack half
    runs from a later stage so it must carry the play's immunity set.
  * Guard Dog checks hand size AFTER its first +2 Cards, grants NO immunity,
    is repeatable against one attack, and is discarded in THAT turn's clean-up.

"""

import pytest

from games.dontminion import engine

A, B = "alice", "bob"



# Pinned kingdom = exactly this batch's 14 cards (the forced-kingdom test seam).
KA = ["Border Village", "Cartographer", "Cauldron", "Crossroads", "Develop",
      "Farmland", "Guard Dog", "Haggler", "Highway", "Inn", "Margrave",
      "Oasis", "Wheelwright", "Witch's Hut"]
# kingdom= mixes sets freely: Moat (the attack-reaction fixture), Throne Room
# (the cumulative-per-play fixture), Militia + Throne Room as the only $4 piles.
KX = KA + ["Moat", "Throne Room", "Militia"]


def fresh(players=(A, B), seed=42, kingdom=tuple(KA)):
    # expansions= only gates the RANDOM kingdom pick; kingdom= overrides it, so
    # this stays valid whether or not "hinterlands" is in KINGDOM yet.
    return engine.new_game(list(players), ["base"], seed=seed,
                           kingdom=list(kingdom))


def give_hand(g, pid, cards):
    """Force a hand to exactly `cards` (conservation not preserved)."""
    g["seats"][pid]["hand"] = list(cards)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


def to_buy(g):
    """Stage-a-hand fixtures enter the buy phase directly (treasure plays)."""
    g["phase"] = "buy"


def end_turn(g, pid):
    guard = 0
    while g["turn"] == pid and not g["over"]:
        ok, err = mv(g, pid, {"type": "end_phase"})
        assert ok, err
        guard += 1
        assert guard < 4, "end_turn did not terminate"


def piles_offered(g):
    return g["pending"][-1]["constraint"]["piles"]


def events(g, event, pid=None):
    return [e for e in g["log"]
            if e.get("event") == event and (pid is None or e.get("pid") == pid)]


# --- Oasis -------------------------------------------------------------------

def test_oasis_draws_gives_an_action_a_coin_and_discards():
    g = fresh()
    give_hand(g, A, ["Oasis", "Estate"])
    g["seats"][A]["deck"] = ["Copper"]
    assert mv(g, A, {"type": "play_action", "card": "Oasis"})[0]
    assert g["actions"] == 1 and g["coins"] == 1
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1          # the discard is MANDATORY
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Estate"]
    assert decide(g, A, cards=["Estate"])[0]
    assert g["seats"][A]["discard"] == ["Estate"]
    assert g["seats"][A]["hand"] == ["Copper"]


def test_oasis_empty_hand_still_gets_the_action_and_the_coin():
    """p125: 'you get +1 Action and +$1 even if you don't have a card in your
    hand to discard.'"""
    g = fresh()
    give_hand(g, A, ["Oasis"])
    g["seats"][A]["deck"], g["seats"][A]["discard"] = [], []
    assert mv(g, A, {"type": "play_action", "card": "Oasis"})[0]
    assert g["actions"] == 1 and g["coins"] == 1
    assert g["pending"] == []


# --- Cartographer ------------------------------------------------------------

def test_cartographer_looks_at_four_discards_some_and_orders_the_rest():
    g = fresh()
    give_hand(g, A, ["Cartographer"])
    g["seats"][A]["deck"] = ["Copper", "Estate", "Silver", "Gold", "Province"]
    g["seats"][A]["discard"] = []
    assert mv(g, A, {"type": "play_action", "card": "Cartographer"})[0]
    assert g["seats"][A]["hand"] == ["Copper"] and g["actions"] == 1
    c = g["pending"][-1]["constraint"]
    assert c["cards"] == ["Estate", "Silver", "Gold", "Province"]
    assert c["min"] == 0 and c["max"] == 4
    assert decide(g, A, cards=["Estate"])[0]
    assert g["seats"][A]["discard"] == ["Estate"]
    # the un-discarded looked-at cards wait in `aside` (p54), not in hand/deck
    assert sorted(g["seats"][A]["aside"]) == ["Gold", "Province", "Silver"]
    assert decide(g, A, order=["Gold", "Silver", "Province"])[0]
    assert g["seats"][A]["deck"] == ["Gold", "Silver", "Province"]
    assert g["seats"][A]["aside"] == []


def test_cartographer_short_deck_looks_at_what_is_there():
    g = fresh()
    give_hand(g, A, ["Cartographer"])
    g["seats"][A]["deck"] = ["Copper", "Estate", "Silver"]
    g["seats"][A]["discard"] = []
    assert mv(g, A, {"type": "play_action", "card": "Cartographer"})[0]
    assert g["pending"][-1]["constraint"]["cards"] == ["Estate", "Silver"]


def test_cartographer_discarding_everything_leaves_nothing_to_order():
    g = fresh()
    give_hand(g, A, ["Cartographer"])
    g["seats"][A]["deck"] = ["Copper", "Estate", "Silver", "Gold", "Province"]
    g["seats"][A]["discard"] = []
    assert mv(g, A, {"type": "play_action", "card": "Cartographer"})[0]
    assert decide(g, A, cards=["Estate", "Silver", "Gold", "Province"])[0]
    assert g["pending"] == []
    assert g["seats"][A]["aside"] == [] and g["seats"][A]["deck"] == []
    assert sorted(g["seats"][A]["discard"]) == ["Estate", "Gold", "Province", "Silver"]


# --- Margrave ----------------------------------------------------------------

def test_margrave_opponent_draws_a_card_then_discards_down_to_three():
    g = fresh()
    give_hand(g, A, ["Margrave"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    give_hand(g, B, ["Copper", "Copper", "Estate", "Estate"])
    g["seats"][B]["deck"], g["seats"][B]["discard"] = ["Gold"], []
    assert mv(g, A, {"type": "play_action", "card": "Margrave"})[0]
    assert len(g["seats"][A]["hand"]) == 3 and g["buys"] == 2
    assert g["pending_pid"] == B
    assert "Gold" in g["seats"][B]["hand"]           # drew first
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 2 and c["max"] == 2
    assert decide(g, B, cards=["Estate", "Estate"])[0]
    assert len(g["seats"][B]["hand"]) == 3
    assert sorted(g["seats"][B]["discard"]) == ["Estate", "Estate"]


def test_margrave_small_hand_still_draws_but_discards_nothing():
    g = fresh()
    give_hand(g, A, ["Margrave"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    give_hand(g, B, ["Copper", "Estate"])
    g["seats"][B]["deck"], g["seats"][B]["discard"] = ["Gold"], []
    assert mv(g, A, {"type": "play_action", "card": "Margrave"})[0]
    assert sorted(g["seats"][B]["hand"]) == ["Copper", "Estate", "Gold"]
    assert g["pending"] == []


def test_margrave_discards_the_whole_batch_at_once():
    """R1 (p47) 'discard down to x cards in hand ... discard all these cards at
    once' — one discard event for the batch, not one per card."""
    g = fresh()
    give_hand(g, A, ["Margrave"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    give_hand(g, B, ["Copper", "Copper", "Estate", "Estate"])
    g["seats"][B]["deck"], g["seats"][B]["discard"] = ["Gold"], []
    assert mv(g, A, {"type": "play_action", "card": "Margrave"})[0]
    assert decide(g, B, cards=["Estate", "Estate"])[0]
    batches = events(g, "discard", B)
    assert len(batches) == 1 and batches[0]["count"] == 2


def test_margrave_moat_immunity_skips_the_whole_hit():
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Margrave"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    give_hand(g, B, ["Moat", "Copper", "Copper", "Estate"])
    g["seats"][B]["deck"], g["seats"][B]["discard"] = ["Gold"], []
    assert mv(g, A, {"type": "play_action", "card": "Margrave"})[0]
    assert g["pending_pid"] == B and g["pending_kind"] == "choose_option"
    assert decide(g, B, ids=["react:Moat"])[0]
    assert len(g["seats"][A]["hand"]) == 3          # the attacker still benefits
    assert g["seats"][B]["deck"] == ["Gold"]        # B never even drew
    assert g["seats"][B]["discard"] == [] and g["pending"] == []


# --- Crossroads --------------------------------------------------------------

def test_crossroads_draws_one_per_victory_card_and_gives_three_actions():
    g = fresh()
    give_hand(g, A, ["Crossroads", "Estate", "Duchy", "Copper"])
    g["seats"][A]["deck"] = ["Silver", "Gold", "Province"]
    assert mv(g, A, {"type": "play_action", "card": "Crossroads"})[0]
    assert g["actions"] == 3                        # 1 - 1 spent + 3
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Duchy", "Estate",
                                             "Gold", "Silver"]


def test_crossroads_counts_victory_cards_before_drawing():
    """The count is read from the revealed (pre-draw) hand — a Victory card
    drawn by the Crossroads never counts itself."""
    g = fresh()
    give_hand(g, A, ["Crossroads", "Estate"])
    g["seats"][A]["deck"] = ["Duchy", "Duchy", "Duchy"]
    assert mv(g, A, {"type": "play_action", "card": "Crossroads"})[0]
    assert sorted(g["seats"][A]["hand"]) == ["Duchy", "Estate"]   # exactly 1 drawn


def test_crossroads_second_copy_this_turn_gives_no_actions():
    g = fresh()
    give_hand(g, A, ["Crossroads", "Crossroads", "Estate"])
    g["seats"][A]["deck"] = ["Copper"] * 4
    assert mv(g, A, {"type": "play_action", "card": "Crossroads"})[0]
    assert g["actions"] == 3
    assert mv(g, A, {"type": "play_action", "card": "Crossroads"})[0]
    assert g["actions"] == 2                        # 3 - 1 spent, no +3
    assert g["turn_ctx"]["crossroads"] == 2


def test_crossroads_throne_room_gives_the_actions_only_once():
    """p78: 'if it's played again with a throne-room, you will get +3 Actions
    only the first time.'"""
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Throne Room", "Crossroads", "Estate"])
    g["seats"][A]["deck"] = ["Copper"] * 4
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert decide(g, A, cards=["Crossroads"])[0]
    assert g["actions"] == 3                        # 1 - 1 + 3, once
    assert g["turn_ctx"]["crossroads"] == 2


def test_crossroads_actions_come_back_on_a_later_turn():
    g = fresh()
    give_hand(g, A, ["Crossroads", "Estate"])
    g["seats"][A]["deck"] = ["Copper"] * 5
    assert mv(g, A, {"type": "play_action", "card": "Crossroads"})[0]
    assert g["actions"] == 3
    end_turn(g, A)
    end_turn(g, B)
    assert g["turn"] == A and "crossroads" not in g["turn_ctx"]
    give_hand(g, A, ["Crossroads", "Estate"])
    g["phase"] = "action"          # the hand-off auto-advanced on the dealt hand
    assert mv(g, A, {"type": "play_action", "card": "Crossroads"})[0]
    assert g["actions"] == 3


# --- Highway -----------------------------------------------------------------

def test_highway_makes_every_card_cost_one_less():
    g = fresh()
    give_hand(g, A, ["Highway"])
    g["seats"][A]["deck"] = ["Copper"]
    assert mv(g, A, {"type": "play_action", "card": "Highway"})[0]
    assert g["actions"] == 1 and len(g["seats"][A]["hand"]) == 1
    assert g["turn_ctx"]["bridges"] == 1            # THE generic -$1 counter
    assert engine.cost(g, "Province") == 7
    assert engine.cost(g, "Copper") == 0            # floors at 0


def test_two_highways_stack_to_two_dollars_off():
    g = fresh()
    give_hand(g, A, ["Highway", "Highway"])
    g["seats"][A]["deck"] = ["Copper"] * 2
    assert mv(g, A, {"type": "play_action", "card": "Highway"})[0]
    assert mv(g, A, {"type": "play_action", "card": "Highway"})[0]
    assert engine.cost(g, "Province") == 6


def test_highway_throne_room_stacks_the_discount():
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Throne Room", "Highway"])
    g["seats"][A]["deck"] = ["Copper"] * 4
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert decide(g, A, cards=["Highway"])[0]
    assert g["turn_ctx"]["bridges"] == 2


def test_highway_discount_survives_being_trashed_from_play():
    """p54 SET UP A LATER ABILITY: the card 'can be removed from play without
    losing its effect'. The turn-scoped counter gives that for free."""
    g = fresh()
    give_hand(g, A, ["Highway"])
    g["seats"][A]["deck"] = ["Copper"]
    assert mv(g, A, {"type": "play_action", "card": "Highway"})[0]
    engine.trash(g, A, ["Highway"], zone="in_play")
    assert "Highway" in g["trash"]
    assert engine.cost(g, "Province") == 7


def test_highway_discount_is_gone_next_turn():
    g = fresh()
    give_hand(g, A, ["Highway"])
    g["seats"][A]["deck"] = ["Copper"] * 6
    assert mv(g, A, {"type": "play_action", "card": "Highway"})[0]
    end_turn(g, A)
    assert engine.cost(g, "Province") == 8


# --- Border Village ----------------------------------------------------------

def test_border_village_plays_for_a_card_and_two_actions():
    g = fresh()
    give_hand(g, A, ["Border Village"])
    g["seats"][A]["deck"] = ["Copper"]
    assert mv(g, A, {"type": "play_action", "card": "Border Village"})[0]
    assert g["actions"] == 2 and g["seats"][A]["hand"] == ["Copper"]


def test_border_village_on_gain_offers_only_strictly_cheaper_piles():
    """R9: 'cheaper' is STRICT — an equally-priced $6 pile is never offered."""
    g = fresh()
    assert engine.gain(g, A, "Border Village")
    engine._drive(g)
    assert g["pending_kind"] == "choose_pile"
    piles = piles_offered(g)
    assert "Gold" not in piles and "Farmland" not in piles
    assert "Border Village" not in piles
    assert "Duchy" in piles and "Cauldron" in piles
    assert decide(g, A, pile="Duchy")[0]
    assert sorted(g["seats"][A]["discard"]) == ["Border Village", "Duchy"]


def test_border_village_triggers_on_a_gain_that_was_not_a_buy():
    g = fresh()
    to_buy(g)
    g["coins"] = 6
    assert mv(g, A, {"type": "buy", "card": "Border Village"})[0]
    assert g["pending_kind"] == "choose_pile"        # bought works too
    g2 = fresh()
    engine.gain(g2, A, "Border Village")             # plain gain: same trigger
    engine._drive(g2)
    assert g2["pending_kind"] == "choose_pile"


def test_border_village_cheaper_card_lands_in_the_discard_pile():
    """GAIN ON WHEN-GAIN (p49): 'if you somehow gain the first card to your
    deck, the other card is still gained to your discard pile'."""
    g = fresh()
    g["seats"][A]["discard"] = []
    assert engine.gain(g, A, "Border Village", dest="deck")
    engine._drive(g)
    assert decide(g, A, pile="Duchy")[0]
    assert g["seats"][A]["deck"][0] == "Border Village"
    assert g["seats"][A]["discard"] == ["Duchy"]


def test_border_village_with_no_cheaper_pile_asks_nothing():
    g = fresh()
    g["turn_ctx"]["bridges"] = 6                     # Border Village now costs $0
    assert engine.cost(g, "Border Village") == 0
    assert engine.gain(g, A, "Border Village")
    engine._drive(g)
    assert g["pending"] == []


# --- Wheelwright -------------------------------------------------------------

def test_wheelwright_discard_then_gain_an_action_of_that_cost_or_less():
    g = fresh()
    give_hand(g, A, ["Wheelwright", "Duchy"])
    g["seats"][A]["deck"] = ["Copper"]
    assert mv(g, A, {"type": "play_action", "card": "Wheelwright"})[0]
    assert g["actions"] == 1
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 0 and c["max"] == 1           # "you MAY discard"
    assert decide(g, A, cards=["Duchy"])[0]
    piles = piles_offered(g)
    assert "Highway" in piles and "Cartographer" in piles
    assert "Cauldron" not in piles                   # a Treasure, not an Action
    assert "Border Village" not in piles             # $6 > $5
    assert "Farmland" not in piles                   # a Victory card
    assert decide(g, A, pile="Highway")[0]
    assert "Highway" in g["seats"][A]["discard"]
    assert "Duchy" in g["seats"][A]["discard"]


def test_wheelwright_declining_discards_nothing_and_gains_nothing():
    """R7 'DO X TO' (p48): no discard => no gain, and no offer at all."""
    g = fresh()
    give_hand(g, A, ["Wheelwright", "Duchy"])
    g["seats"][A]["deck"] = ["Copper"]
    assert mv(g, A, {"type": "play_action", "card": "Wheelwright"})[0]
    assert decide(g, A, cards=[])[0]
    assert g["pending"] == []
    assert g["seats"][A]["discard"] == []


def test_wheelwright_may_gain_a_copy_of_the_discarded_card():
    """p167: 'it can be a copy of the discarded card.'"""
    g = fresh()
    give_hand(g, A, ["Wheelwright", "Wheelwright"])
    g["seats"][A]["deck"] = ["Copper"]
    assert mv(g, A, {"type": "play_action", "card": "Wheelwright"})[0]
    assert decide(g, A, cards=["Wheelwright"])[0]
    assert "Wheelwright" in piles_offered(g)
    assert decide(g, A, pile="Wheelwright")[0]
    assert g["seats"][A]["discard"].count("Wheelwright") == 2


def test_wheelwright_discard_stands_when_no_action_pile_qualifies():
    """p167: 'you may discard a card even if there are no Action cards of that
    cost or less.'"""
    g = fresh()
    give_hand(g, A, ["Wheelwright", "Copper"])
    g["seats"][A]["deck"] = ["Estate"]
    assert mv(g, A, {"type": "play_action", "card": "Wheelwright"})[0]
    assert decide(g, A, cards=["Copper"])[0]         # $0: no Action costs $0
    assert g["pending"] == []
    assert g["seats"][A]["discard"] == ["Copper"]


# --- Develop -----------------------------------------------------------------

def test_develop_offers_the_order_when_both_sides_have_candidates():
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Develop", "Silver"])
    assert mv(g, A, {"type": "play_action", "card": "Develop"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1           # the trash is MANDATORY
    assert decide(g, A, cards=["Silver"])[0]         # $3
    ids = {o["id"] for o in g["pending"][-1]["constraint"]["options"]}
    assert ids == {"hi_first", "lo_first"}


def test_develop_gains_both_onto_the_deck_second_on_top():
    """R13 (p50): 'if both cards are gained to your deck, the second card ends
    up on top of the first.'"""
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Develop", "Silver"])
    g["seats"][A]["deck"] = []
    assert mv(g, A, {"type": "play_action", "card": "Develop"})[0]
    assert decide(g, A, cards=["Silver"])[0]
    assert decide(g, A, ids=["hi_first"])[0]
    assert decide(g, A, pile="Throne Room")[0]       # $4, gained first
    assert decide(g, A, pile="Estate")[0]            # $2, gained second
    assert g["seats"][A]["deck"][:2] == ["Estate", "Throne Room"]
    assert "Silver" in g["trash"]


def test_develop_the_other_order_reverses_the_deck():
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Develop", "Silver"])
    g["seats"][A]["deck"] = []
    assert mv(g, A, {"type": "play_action", "card": "Develop"})[0]
    assert decide(g, A, cards=["Silver"])[0]
    assert decide(g, A, ids=["lo_first"])[0]
    assert piles_offered(g) == sorted(p for p in g["supply"]
                                      if engine.cost_eq(g, p, 2) and g["supply"][p] > 0)
    assert decide(g, A, pile="Estate")[0]
    assert decide(g, A, pile="Militia")[0]
    assert g["seats"][A]["deck"][:2] == ["Militia", "Estate"]


def test_develop_one_empty_side_skips_the_order_question():
    g = fresh()
    give_hand(g, A, ["Develop", "Estate"])           # $2: nothing costs $1
    assert mv(g, A, {"type": "play_action", "card": "Develop"})[0]
    assert decide(g, A, cards=["Estate"])[0]
    assert g["pending_kind"] == "choose_pile"
    assert all(engine.cost_eq(g, p, 3) for p in piles_offered(g))


def test_develop_trashing_a_zero_cost_card_has_no_cheaper_side():
    """p81: 'if you remodel a card that costs $0, you won't gain a card costing
    less.' (And in this kingdom nothing costs $1, so nothing is gained.)"""
    g = fresh()
    give_hand(g, A, ["Develop", "Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Develop"})[0]
    assert decide(g, A, cards=["Copper"])[0]
    assert g["pending"] == []
    assert g["trash"] == ["Copper"]


def test_develop_reads_the_cost_at_trash_time_under_a_highway():
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Highway", "Develop", "Silver"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    g["actions"] = 2
    assert mv(g, A, {"type": "play_action", "card": "Highway"})[0]
    assert mv(g, A, {"type": "play_action", "card": "Develop"})[0]
    assert decide(g, A, cards=["Silver"])[0]         # Silver now costs $2
    assert decide(g, A, ids=["hi_first"])[0]
    # $3 under the Highway == the printed-$4 piles
    assert "Throne Room" in piles_offered(g)
    assert all(engine.cost_eq(g, p, 3) for p in piles_offered(g))


def test_develop_with_an_empty_hand_does_nothing():
    g = fresh()
    give_hand(g, A, ["Develop"])
    assert mv(g, A, {"type": "play_action", "card": "Develop"})[0]
    assert g["pending"] == []


# --- Farmland ----------------------------------------------------------------

def test_farmland_is_a_two_vp_victory_card():
    g = fresh()
    base = engine.score_game(g)[A]["vp"]
    g["seats"][A]["discard"].append("Farmland")
    assert engine.score_game(g)[A]["vp"] == base + 2


def test_farmland_on_gain_trashes_and_upgrades_by_exactly_two():
    g = fresh(kingdom=KX)
    to_buy(g)
    g["coins"] = 6
    give_hand(g, A, ["Estate", "Copper"])
    assert mv(g, A, {"type": "buy", "card": "Farmland"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1           # mandatory when hand is non-empty
    assert decide(g, A, cards=["Estate"])[0]         # $2 -> $4
    assert "Estate" in g["trash"]
    assert all(engine.cost_eq(g, p, 4) for p in piles_offered(g))
    assert decide(g, A, pile="Throne Room")[0]
    assert "Throne Room" in g["seats"][A]["discard"]


def test_farmland_triggers_on_a_gain_that_was_not_a_buy():
    """2022 text is 'when you GAIN this', not 'when you buy this' (p90)."""
    g = fresh()
    give_hand(g, A, ["Estate"])
    assert engine.gain(g, A, "Farmland")
    engine._drive(g)
    assert g["pending_kind"] == "choose_cards"
    assert g["pending"][-1]["card"] == "Farmland"


def test_farmland_never_offers_another_farmland():
    """'but not another Farmland' is a NAME exclusion, not a cost one."""
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Throne Room"])                 # $4 + $2 = exactly $6
    assert engine.gain(g, A, "Farmland")
    engine._drive(g)
    assert decide(g, A, cards=["Throne Room"])[0]
    piles = piles_offered(g)
    assert "Farmland" not in piles                   # equal cost, still excluded
    assert "Gold" in piles and "Border Village" in piles


def test_farmland_with_an_empty_hand_does_nothing():
    g = fresh()
    give_hand(g, A, [])
    assert engine.gain(g, A, "Farmland")
    engine._drive(g)
    assert g["pending"] == []


# --- Inn ---------------------------------------------------------------------

def test_inn_draws_two_gives_two_actions_and_discards_two():
    g = fresh()
    give_hand(g, A, ["Inn", "Copper", "Estate"])
    g["seats"][A]["deck"] = ["Silver", "Gold"]
    g["seats"][A]["discard"] = []
    assert mv(g, A, {"type": "play_action", "card": "Inn"})[0]
    assert g["actions"] == 2
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 2 and c["max"] == 2
    assert decide(g, A, cards=["Copper", "Estate"])[0]
    assert sorted(g["seats"][A]["hand"]) == ["Gold", "Silver"]


def test_inn_discards_what_it_has_when_it_could_not_draw():
    """R5 (p50): 'you have to discard y cards (if possible) even if you were
    not able to draw all x cards.' push_choose_cards clamps to the hand."""
    g = fresh()
    give_hand(g, A, ["Inn", "Copper"])
    g["seats"][A]["deck"], g["seats"][A]["discard"] = [], []
    assert mv(g, A, {"type": "play_action", "card": "Inn"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1
    assert decide(g, A, cards=["Copper"])[0]
    assert g["seats"][A]["discard"] == ["Copper"]


def test_inn_on_gain_shuffles_chosen_actions_out_of_the_discard_pile():
    g = fresh()
    to_buy(g)
    g["coins"] = 5
    g["seats"][A]["discard"] = ["Oasis", "Copper", "Highway"]
    g["seats"][A]["deck"] = ["Estate"]
    assert mv(g, A, {"type": "buy", "card": "Inn"})[0]
    c = g["pending"][-1]["constraint"]
    # the just-gained Inn is itself an Action in the discard pile
    assert c["cards"] == ["Highway", "Inn", "Oasis"] and c["max"] == 3
    assert decide(g, A, cards=["Highway", "Oasis"])[0]
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Inn"]
    assert sorted(g["seats"][A]["deck"]) == ["Estate", "Highway", "Oasis"]


def test_inn_shuffles_even_when_nothing_is_chosen():
    """p109: 'if you shuffle zero cards into your deck when gaining Inn, you
    still shuffle.'"""
    g = fresh()
    to_buy(g)
    g["coins"] = 5
    g["seats"][A]["discard"] = ["Copper"]
    assert mv(g, A, {"type": "buy", "card": "Inn"})[0]
    assert decide(g, A, cards=[])[0]
    shuffles = events(g, "shuffle_into_deck", A)
    assert len(shuffles) == 1 and shuffles[0]["count"] == 0


def test_inn_can_shuffle_itself_into_the_deck():
    g = fresh()
    to_buy(g)
    g["coins"] = 5
    g["seats"][A]["discard"] = []
    g["seats"][A]["deck"] = ["Estate"]
    assert mv(g, A, {"type": "buy", "card": "Inn"})[0]
    assert decide(g, A, cards=["Inn"])[0]
    assert g["seats"][A]["discard"] == []
    assert sorted(g["seats"][A]["deck"]) == ["Estate", "Inn"]


def test_inn_on_gain_with_no_actions_in_the_discard_pile_still_shuffles():
    g = fresh()
    g["seats"][A]["discard"] = []
    assert engine.gain(g, A, "Inn", dest="deck")     # Inn never reaches discard
    engine._drive(g)
    assert g["pending"] == []
    assert len(events(g, "shuffle_into_deck", A)) == 1


# --- Haggler -----------------------------------------------------------------

def _play_haggler(g, n=1):
    give_hand(g, A, ["Haggler"] * n)
    g["actions"] = n
    for _ in range(n):
        assert mv(g, A, {"type": "play_action", "card": "Haggler"})[0]
    to_buy(g)


def test_haggler_gives_two_coins_and_a_cheaper_non_victory_card_on_a_buy():
    g = fresh()
    _play_haggler(g)
    assert g["coins"] == 2
    g["coins"] = 3
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    piles = piles_offered(g)
    assert "Estate" not in piles                     # Victory cards excluded
    assert "Silver" not in piles                     # strictly cheaper
    assert "Crossroads" in piles and "Copper" in piles
    assert decide(g, A, pile="Crossroads")[0]
    assert sorted(g["seats"][A]["discard"]) == ["Crossroads", "Silver"]


def test_haggler_ignores_a_gain_that_was_not_a_buy():
    g = fresh()
    _play_haggler(g)
    engine.gain(g, A, "Silver")
    engine._drive(g)
    assert g["pending"] == []


def test_haggler_only_sees_cards_gained_after_it_was_played():
    g = fresh()
    to_buy(g)
    g["coins"] = 3
    engine.gain(g, A, "Silver")                      # before any Haggler
    engine._drive(g)
    assert g["pending"] == []


def test_two_hagglers_stack_into_two_offers():
    """'It's cumulative if played with a throne-room' — and per copy played."""
    g = fresh()
    _play_haggler(g, 2)
    g["coins"] = 3
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert decide(g, A, pile="Copper")[0]
    assert g["pending_kind"] == "choose_pile"        # the second Haggler
    assert decide(g, A, pile="Copper")[0]
    assert g["seats"][A]["discard"].count("Copper") == 2


def test_haggler_keeps_firing_after_being_trashed_from_play():
    """until="turn_end" is a watcher, not a while-in-play position."""
    g = fresh()
    _play_haggler(g)
    engine.trash(g, A, ["Haggler"], zone="in_play")
    g["coins"] = 3
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert g["pending_kind"] == "choose_pile"


def test_haggler_chains_into_the_gained_cards_own_when_gain():
    g = fresh()
    _play_haggler(g)
    g["coins"] = 8
    assert mv(g, A, {"type": "buy", "card": "Province"})[0]
    assert "Border Village" in piles_offered(g)
    assert decide(g, A, pile="Border Village")[0]
    # Border Village's own when-gain now asks for its cheaper card
    assert g["pending_kind"] == "choose_pile"
    assert g["pending"][-1]["card"] == "Border Village"


# --- Witch's Hut -------------------------------------------------------------

def test_witchs_hut_two_discarded_actions_curse_every_opponent():
    g = fresh()
    give_hand(g, A, ["Witch's Hut"])
    g["seats"][A]["deck"] = ["Oasis", "Highway", "Copper", "Estate"]
    g["seats"][B]["discard"] = []
    assert mv(g, A, {"type": "play_action", "card": "Witch's Hut"})[0]
    assert len(g["seats"][A]["hand"]) == 4
    assert decide(g, A, cards=["Oasis", "Highway"])[0]
    assert g["seats"][B]["discard"] == ["Curse"]
    assert sorted(g["seats"][A]["discard"]) == ["Highway", "Oasis"]


def test_witchs_hut_non_actions_give_no_curses():
    g = fresh()
    give_hand(g, A, ["Witch's Hut"])
    g["seats"][A]["deck"] = ["Copper", "Estate", "Copper", "Estate"]
    g["seats"][B]["discard"] = []
    assert mv(g, A, {"type": "play_action", "card": "Witch's Hut"})[0]
    assert decide(g, A, cards=["Copper", "Estate"])[0]
    assert g["seats"][B]["discard"] == []


def test_witchs_hut_reveals_both_cards_before_discarding_them():
    """p168: 'you reveal both cards before discarding them' — which is why a
    discarded Trail that moves the other card can't cancel the Curses."""
    g = fresh()
    give_hand(g, A, ["Witch's Hut"])
    g["seats"][A]["deck"] = ["Oasis", "Highway", "Copper", "Estate"]
    assert mv(g, A, {"type": "play_action", "card": "Witch's Hut"})[0]
    assert decide(g, A, cards=["Oasis", "Highway"])[0]
    rev = events(g, "reveal", A)[-1]
    dis = events(g, "discard", A)[-1]
    assert sorted(rev["cards"]) == ["Highway", "Oasis"]
    assert rev["n"] < dis["n"]


def test_witchs_hut_short_hand_cannot_satisfy_both_actions():
    g = fresh()
    give_hand(g, A, ["Witch's Hut", "Oasis"])
    g["seats"][A]["deck"], g["seats"][A]["discard"] = [], []
    g["seats"][B]["discard"] = []
    assert mv(g, A, {"type": "play_action", "card": "Witch's Hut"})[0]
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 1 and c["max"] == 1           # clamped by the hand
    assert decide(g, A, cards=["Oasis"])[0]
    assert g["seats"][B]["discard"] == []


def test_witchs_hut_moat_revealer_gets_no_curse():
    """The immunity-capture regression: the attack half runs from a LATER
    stage, so the play's _atk_immune must be carried in the frame data."""
    g = fresh(kingdom=KX)
    give_hand(g, A, ["Witch's Hut"])
    g["seats"][A]["deck"] = ["Oasis", "Highway", "Copper", "Estate"]
    give_hand(g, B, ["Moat"])
    g["seats"][B]["discard"] = []
    assert mv(g, A, {"type": "play_action", "card": "Witch's Hut"})[0]
    assert g["pending_pid"] == B
    assert decide(g, B, ids=["react:Moat"])[0]
    assert decide(g, A, cards=["Oasis", "Highway"])[0]
    assert g["seats"][B]["discard"] == []
    assert g["pending"] == []


# --- Cauldron ----------------------------------------------------------------

def _play_cauldron(g, n=1):
    give_hand(g, A, ["Cauldron"] * n)
    to_buy(g)
    for _ in range(n):
        assert mv(g, A, {"type": "play_treasure", "card": "Cauldron"})[0]


def _gain_action(g, pid=A, card="Oasis"):
    assert engine.gain(g, pid, card)
    engine._drive(g)


def test_cauldron_banks_two_coins_and_a_buy():
    g = fresh()
    _play_cauldron(g)
    assert g["coins"] == 2 and g["buys"] == 2


def test_cauldron_fires_when_the_third_action_lands_after_the_play():
    """p70: 'the Cursing ability only triggers if the third Action is gained
    after Cauldron was played. (The first two could be gained before.)'"""
    g = fresh()
    to_buy(g)
    g["seats"][B]["discard"] = []
    _gain_action(g)
    _gain_action(g)                                  # two gained BEFORE the play
    _play_cauldron(g)
    _gain_action(g)                                  # the third, after
    assert g["seats"][B]["discard"] == ["Curse"]


def test_cauldron_gives_nothing_when_all_three_were_gained_before_it():
    """'If you gain the third Action before playing Cauldron, Cauldron doesn't
    give out Curses that turn.'"""
    g = fresh()
    to_buy(g)
    g["seats"][B]["discard"] = []
    for _ in range(3):
        _gain_action(g)
    _play_cauldron(g)
    _gain_action(g)                                  # the FOURTH: no trigger
    assert g["seats"][B]["discard"] == []


def test_cauldron_does_not_re_fire_on_later_gains():
    g = fresh()
    to_buy(g)
    g["seats"][B]["discard"] = []
    _play_cauldron(g)
    for _ in range(5):
        _gain_action(g)
    assert g["seats"][B]["discard"] == ["Curse"]


def test_cauldron_ignores_non_action_gains():
    g = fresh()
    to_buy(g)
    g["seats"][B]["discard"] = []
    _play_cauldron(g)
    for _ in range(3):
        _gain_action(g, card="Silver")
    assert g["seats"][B]["discard"] == []


def test_two_cauldrons_each_hand_out_their_own_curse():
    """'has a cumulative effect if played multiple times' — one counter each."""
    g = fresh()
    to_buy(g)
    g["seats"][B]["discard"] = []
    _play_cauldron(g, 2)
    for _ in range(3):
        _gain_action(g)
    assert g["seats"][B]["discard"] == ["Curse", "Curse"]


def test_cauldron_keeps_firing_after_being_trashed_from_play():
    g = fresh()
    to_buy(g)
    g["seats"][B]["discard"] = []
    _play_cauldron(g)
    engine.trash(g, A, ["Cauldron"], zone="in_play")
    for _ in range(3):
        _gain_action(g)
    assert g["seats"][B]["discard"] == ["Curse"]


def test_cauldron_moat_revealed_at_play_time_blocks_the_later_curse():
    """An Attack TREASURE opens the reaction window when it is PLAYED; the
    immune set has to survive into the much later Curse distribution."""
    g = fresh(kingdom=KX)
    give_hand(g, B, ["Moat"])
    g["seats"][B]["discard"] = []
    give_hand(g, A, ["Cauldron"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Cauldron"})[0]
    assert g["pending_pid"] == B and g["pending_kind"] == "choose_option"
    assert decide(g, B, ids=["react:Moat"])[0]
    assert g["coins"] == 2 and g["buys"] == 2
    for _ in range(3):
        _gain_action(g)
    assert g["seats"][B]["discard"] == []


def test_cauldron_is_a_manual_treasure_and_bulk_play_is_not_offered_alone():
    g = fresh()
    to_buy(g)
    give_hand(g, A, ["Cauldron"])
    assert "Cauldron" in engine.manual_treasures()
    assert mv(g, A, {"type": "play_all_treasures"})[0] is False
    assert not any(m["type"] == "play_all_treasures"
                   for m in engine.legal_moves(g, A))


def test_cauldron_is_skipped_by_a_bulk_play_that_has_other_treasures():
    g = fresh()
    to_buy(g)
    give_hand(g, A, ["Cauldron", "Copper"])
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert g["seats"][A]["hand"] == ["Cauldron"]
    assert g["coins"] == 1


# --- Guard Dog ---------------------------------------------------------------

def test_guard_dog_draws_two_more_when_the_hand_is_five_or_fewer():
    """p101: 'each time you play a Guard Dog, AFTER drawing two cards, check
    how many cards you have in hand.' 3 in hand + 2 = 5 => +2 more."""
    g = fresh()
    give_hand(g, A, ["Guard Dog", "Copper", "Copper", "Copper"])
    g["seats"][A]["deck"] = ["Estate"] * 4
    assert mv(g, A, {"type": "play_action", "card": "Guard Dog"})[0]
    assert len(g["seats"][A]["hand"]) == 7


def test_guard_dog_stops_at_two_cards_when_the_hand_grows_past_five():
    """4 in hand + 2 = 6 => no extra draw."""
    g = fresh()
    give_hand(g, A, ["Guard Dog", "Copper", "Copper", "Copper", "Copper"])
    g["seats"][A]["deck"] = ["Estate"] * 4
    assert mv(g, A, {"type": "play_action", "card": "Guard Dog"})[0]
    assert len(g["seats"][A]["hand"]) == 6


def test_guard_dog_reacts_to_an_attack_but_grants_no_immunity():
    g = fresh()
    give_hand(g, A, ["Margrave"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    give_hand(g, B, ["Guard Dog", "Estate", "Estate"])
    g["seats"][B]["deck"] = ["Copper"] * 6
    g["seats"][B]["discard"] = []
    assert mv(g, A, {"type": "play_action", "card": "Margrave"})[0]
    assert g["pending_pid"] == B and g["pending_kind"] == "choose_option"
    ids = {o["id"] for o in g["pending"][-1]["constraint"]["options"]}
    assert ids == {"react:Guard Dog", "decline"}
    assert decide(g, B, ids=["react:Guard Dog"])[0]
    assert "Guard Dog" in g["seats"][B]["in_play"]
    # 2 left in hand + 2 drawn = 4 (<=5) => +2 more, then Margrave still hits
    assert g["pending_pid"] == B and g["pending_kind"] == "choose_cards"
    c = g["pending"][-1]["constraint"]
    assert c["min"] == 4 and c["max"] == 4           # 7 in hand -> down to 3
    assert decide(g, B, cards=c["cards"][:4])[0]
    assert len(g["seats"][B]["hand"]) == 3           # NO immunity


def test_two_guard_dogs_may_react_to_the_same_attack():
    """p101: 'you may react with several Guard Dogs to the same played
    Attack.'"""
    g = fresh()
    give_hand(g, A, ["Margrave"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    give_hand(g, B, ["Guard Dog", "Guard Dog"])
    g["seats"][B]["deck"] = ["Copper"] * 10
    g["seats"][B]["discard"] = []
    assert mv(g, A, {"type": "play_action", "card": "Margrave"})[0]
    assert decide(g, B, ids=["react:Guard Dog"])[0]
    ids = {o["id"] for o in g["pending"][-1]["constraint"]["options"]}
    assert "react:Guard Dog" in ids                  # repeatable: offered again
    assert decide(g, B, ids=["react:Guard Dog"])[0]
    assert g["seats"][B]["in_play"].count("Guard Dog") == 2


def test_a_guard_dog_drawn_off_the_first_one_may_still_be_played():
    """p101: 'if you react with Guard Dog and draw a Guard Dog, you may still
    play it.'"""
    g = fresh()
    give_hand(g, A, ["Margrave"])
    g["seats"][A]["deck"] = ["Copper"] * 3
    give_hand(g, B, ["Guard Dog", "Copper"])
    g["seats"][B]["deck"] = ["Guard Dog"] + ["Copper"] * 8
    g["seats"][B]["discard"] = []
    assert mv(g, A, {"type": "play_action", "card": "Margrave"})[0]
    assert decide(g, B, ids=["react:Guard Dog"])[0]
    assert "Guard Dog" in g["seats"][B]["hand"]      # drawn off the first
    ids = {o["id"] for o in g["pending"][-1]["constraint"]["options"]}
    assert "react:Guard Dog" in ids
    assert decide(g, B, ids=["react:Guard Dog"])[0]
    assert g["seats"][B]["in_play"].count("Guard Dog") == 2


def test_an_off_turn_guard_dog_is_discarded_in_that_turns_cleanup():
    """R12 (p53): 'you discard the card in THAT turn's Clean-up phase' — the
    attacker's, which is why clean-up sweeps every seat's play area."""
    g = fresh()
    give_hand(g, A, ["Margrave"])
    g["seats"][A]["deck"] = ["Copper"] * 8
    give_hand(g, B, ["Guard Dog", "Estate", "Estate"])
    g["seats"][B]["deck"] = ["Copper"] * 8
    g["seats"][B]["discard"] = []
    assert mv(g, A, {"type": "play_action", "card": "Margrave"})[0]
    assert decide(g, B, ids=["react:Guard Dog"])[0]
    c = g["pending"][-1]["constraint"]
    assert decide(g, B, cards=c["cards"][:c["min"]])[0]
    assert g["seats"][B]["in_play"] == ["Guard Dog"]
    end_turn(g, A)
    assert g["seats"][B]["in_play"] == []
    assert "Guard Dog" in g["seats"][B]["discard"]


def test_guard_dog_played_normally_spends_an_action():
    g = fresh()
    give_hand(g, A, ["Guard Dog"])
    g["seats"][A]["deck"] = ["Copper"] * 4
    assert mv(g, A, {"type": "play_action", "card": "Guard Dog"})[0]
    assert g["actions"] == 0
