"""Alchemy card tests — the 11 shipped kingdom cards, the Potion pile, and the
COST VECTOR they exist to exercise.

ONE file rather than the usual A/B split: at 11 cards this set is under half
the size of the ones that needed two batch agents, and a single fixture set
keeps the cost-vector tests (which have to reach cards from several sets at
once) in one place.

Positions are arranged by mutating the game dict directly (the repo's
board-fixture idiom). give_hand breaks card conservation, so no test here
asserts the census invariant (test_soak owns that).

Headline rulings pinned here:
  * THE COST VECTOR. "Up to $N" excludes every Potion card; "exactly $N more"
    requires the potion components to MATCH; "lower than" makes {$4,P} and
    {$5} INCOMPARABLE. The number forms and the card-reference forms differ
    exactly where a Potion is involved, and both are pinned.
  * A played Potion produces a POTION, not $, and both halves of a price are
    gated at buy time.
  * Alchemist and Herbalist are Clean-up cards, cumulative per play; Herbalist
    cannot topdeck a Treasure that is NOT being discarded (a Duration that
    stays in play).
  * Apprentice draws +2 for a Potion in the cost, and a cost reduction makes it
    draw fewer.
  * Transmute gains ALL the matching cards when the trashed card has several of
    the three types.
  * Scrying Pool's discard-or-keep is the ATTACKER's choice for every player
    including themselves, and the dig looks for a NON-Action.
"""

import pytest

from games.dontminion import engine

A, B, C = "alice", "bob", "carol"

# every Alchemy card we ship, as one board
KAL = ["Alchemist", "Apothecary", "Apprentice", "Familiar", "Golem", "Herbalist",
       "Philosopher's Stone", "Scrying Pool", "Transmute", "University"]
# a board with no Potion cost anywhere
KPLAIN = ["Village", "Smithy", "Moat", "Throne Room", "Market", "Festival",
          "Cellar", "Militia", "Workshop", "Laboratory"]


def fresh(players=(A, B), seed=42, kingdom=tuple(KAL), expansions=("alchemy",)):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom))


def give_hand(g, pid, cards):
    g["seats"][pid]["hand"] = list(cards)


def give_deck(g, pid, cards):
    g["seats"][pid]["deck"] = list(cards)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


def play(g, pid, card):
    return mv(g, pid, {"type": "play_action", "card": card})


def frame(g):
    return g["pending"][-1] if g["pending"] else None


def to_buy(g, coins=0, potions=0):
    g["phase"] = "buy"
    g["coins"] = coins
    g["potions"] = potions


def end_buy(g, pid):
    return mv(g, pid, {"type": "end_phase"})


# ── THE COST VECTOR ───────────────────────────────────────────────────────────

def test_up_to_a_number_excludes_every_potion_card():
    """"Up to {$3}" means a cost where the number of $ is no more than 3 AND
    the number of Potions is 0." This one rule is why the ~60 existing
    "costing up to $N" call sites needed no change at all."""
    g = fresh(kingdom=KAL + ["Village"], expansions=("base", "alchemy"))
    assert engine.cost(g, "Golem") == 4 and engine.potion_cost(g, "Golem") == 1
    assert engine.cost_le(g, "Golem", 4) is False
    assert engine.cost_le(g, "Golem", 99) is False
    assert engine.cost_lt(g, "Golem", 99) is False
    assert engine.cost_eq(g, "Golem", 4) is False
    # ...and a plain card is unaffected
    assert engine.cost_le(g, "Village", 3) and engine.cost_eq(g, "Village", 3)


def test_exactly_more_requires_the_potion_components_to_match():
    """"Costing exactly $1 more" means "having the same cost plus $1". So
    {$3,P} is exactly $1 more than {$2,P}, but NOT than {$2}."""
    g = fresh(kingdom=KAL, expansions=("base", "alchemy"))
    # Alchemist {$3,P} vs Apothecary {$2,P}
    assert engine.cost_eq_card(g, "Alchemist", "Apothecary", 1)
    # Alchemist {$3,P} vs Silver {$3} — same coins, different potions
    assert engine.cost_eq_card(g, "Alchemist", "Silver", 0) is False
    # Silver {$3} vs Estate {$2}
    assert engine.cost_eq_card(g, "Silver", "Estate", 1)


def test_lower_than_makes_a_potion_cost_incomparable():
    """"Both {$3} and {$4} are lower than {$5}. However, {$4,P} is not lower
    than {$5} (nor vice versa)." A vector is lower only if no component is
    higher and at least one is lower."""
    g = fresh(kingdom=KAL, expansions=("base", "alchemy"))
    # {$4,P} vs {$5}: coins lower but potions HIGHER -> incomparable
    assert engine.cost_lt_card(g, "Golem", "Duchy") is False
    assert engine.cost_lt_card(g, "Duchy", "Golem") is False
    # {$3} vs {$4,P}: nothing higher, coins lower -> genuinely lower
    assert engine.cost_lt_card(g, "Silver", "Golem")
    # {$2,P} vs {$4,P}: same potions, coins lower -> lower
    assert engine.cost_lt_card(g, "Apothecary", "Golem")


def test_workshop_cannot_gain_a_potion_card():
    """The payoff: a shipped card from another set became Potion-correct with
    no edit, because its bound is a NUMBER."""
    g = fresh(kingdom=["Workshop", "Golem", "Apothecary", "University",
                       "Village", "Smithy", "Market", "Festival", "Moat",
                       "Militia"],
              expansions=("base", "alchemy"))
    give_hand(g, A, ["Workshop"])
    assert play(g, A, "Workshop")[0]
    piles = frame(g)["constraint"]["piles"]
    assert "Golem" not in piles and "Apothecary" not in piles
    assert "University" not in piles          # {$2,P} is not "up to $4"
    assert "Silver" in piles


def test_remodelling_a_potion_card_can_reach_another_potion_card():
    """...and the other half: "up to $2 more than {$4,P}" is "up to {$6,P}",
    which a plain number bound could not express."""
    g = fresh(kingdom=["Remodel", "Golem", "Apothecary", "University",
                       "Alchemist", "Smithy", "Market", "Festival", "Moat",
                       "Militia"],
              expansions=("base", "alchemy"))
    give_hand(g, A, ["Remodel", "Golem"])
    assert play(g, A, "Remodel")[0]
    assert decide(g, A, cards=["Golem"])[0]          # trash {$4,P}
    piles = frame(g)["constraint"]["piles"]
    assert "Alchemist" in piles, "{$3,P} is within 'up to $2 more than {$4,P}'"
    assert "Apothecary" in piles
    assert "Gold" in piles, "{$6} has no potion, so nothing is higher"
    assert "Province" not in piles                    # $8 is out of range


# ── the Potion pile and the second money pool ────────────────────────────────

def test_the_potion_pile_joins_the_supply_only_when_a_card_needs_one():
    g = fresh()
    assert g["supply"]["Potion"] == 16
    g2 = fresh(kingdom=KPLAIN, expansions=("base",))
    assert "Potion" not in g2["supply"]


def test_playing_a_potion_produces_a_potion_not_coins():
    g = fresh()
    give_hand(g, A, ["Potion", "Copper"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Potion"})[0]
    assert g["potions"] == 1 and g["coins"] == 0
    assert mv(g, A, {"type": "play_treasure", "card": "Copper"})[0]
    assert g["coins"] == 1 and g["potions"] == 1


def test_you_cannot_buy_a_potion_card_without_a_potion():
    g = fresh()
    to_buy(g, coins=20, potions=0)
    assert {"type": "buy", "card": "Golem"} not in engine.legal_moves(g, A)
    ok, err = mv(g, A, {"type": "buy", "card": "Golem"})
    assert not ok and err == "not enough Potions"
    to_buy(g, coins=20, potions=1)
    assert {"type": "buy", "card": "Golem"} in engine.legal_moves(g, A)
    assert mv(g, A, {"type": "buy", "card": "Golem"})[0]
    assert g["potions"] == 0 and g["coins"] == 16


def test_buying_two_potion_cards_needs_two_potions():
    """"To buy two cards with a Potion in their costs you need to have played
    a Potion twice.\""""
    g = fresh()
    to_buy(g, coins=20, potions=1)
    g["buys"] = 2
    assert mv(g, A, {"type": "buy", "card": "Transmute"})[0]
    assert g["potions"] == 0
    assert {"type": "buy", "card": "Transmute"} not in engine.legal_moves(g, A)


def test_the_potion_pool_empties_at_the_turn_hand_off():
    g = fresh()
    give_hand(g, A, ["Potion"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Potion"})[0]
    assert g["potions"] == 1
    assert end_buy(g, A)[0]
    assert g["turn"] == B and g["potions"] == 0


def test_the_potion_cost_ships_on_the_wire_beside_the_coin_cost():
    g = fresh()
    v = engine.player_view(g, A)
    assert v["costs"]["Golem"] == 4
    assert v["potion_costs"]["Golem"] == 1
    assert "Silver" not in v["potion_costs"], "only non-zero entries ship"
    assert v["potions"] == 0


# ── Alchemist ─────────────────────────────────────────────────────────────────

def test_alchemist_topdecks_itself_when_a_potion_is_in_play():
    g = fresh()
    give_hand(g, A, ["Alchemist", "Potion"])
    give_deck(g, A, ["Gold"] * 6)
    assert play(g, A, "Alchemist")[0]
    assert g["seats"][A]["hand"].count("Gold") == 2 and g["actions"] == 1
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Potion"})[0]
    assert end_buy(g, A)[0]
    f = frame(g)
    assert f is not None and f["card"] == "Alchemist"
    assert decide(g, A, ids=["yes"])[0]
    # it went onto the DECK rather than the discard, so Clean-up's 5-card draw
    # picks it straight back up — which is the whole point of the card
    assert "Alchemist" in g["seats"][A]["hand"]
    assert "Alchemist" not in g["seats"][A]["discard"]


def test_alchemist_offers_nothing_without_a_potion_in_play():
    g = fresh()
    give_hand(g, A, ["Alchemist"])
    # deep enough that Clean-up's draw cannot reshuffle the discard back in,
    # so "it went to the discard" is a stable thing to assert
    give_deck(g, A, ["Gold"] * 20)
    assert play(g, A, "Alchemist")[0]
    to_buy(g)
    assert end_buy(g, A)[0]
    assert g["turn"] == B, "no prompt at all — the turn just ended"
    assert "Alchemist" in g["seats"][A]["discard"]


def test_alchemist_may_decline():
    g = fresh()
    give_hand(g, A, ["Alchemist", "Potion"])
    give_deck(g, A, ["Gold"] * 20)
    assert play(g, A, "Alchemist")[0]
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Potion"})[0]
    assert end_buy(g, A)[0]
    assert decide(g, A, ids=["no"])[0]
    assert "Alchemist" in g["seats"][A]["discard"]


def test_two_alchemists_each_get_their_own_offer():
    g = fresh()
    give_hand(g, A, ["Alchemist", "Alchemist", "Potion"])
    give_deck(g, A, ["Gold"] * 8)
    g["actions"] = 2
    assert play(g, A, "Alchemist")[0]
    assert play(g, A, "Alchemist")[0]
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Potion"})[0]
    assert end_buy(g, A)[0]
    seen = 0
    for _ in range(6):
        f = frame(g)
        if f is None or f["card"] != "Alchemist":
            break
        seen += 1
        assert decide(g, A, ids=["yes"])[0]
    assert seen == 2
    assert g["seats"][A]["hand"].count("Alchemist") == 2
    assert "Alchemist" not in g["seats"][A]["discard"]


# ── Apothecary ────────────────────────────────────────────────────────────────

def test_apothecary_takes_coppers_and_potions_and_reorders_the_rest():
    g = fresh()
    give_hand(g, A, ["Apothecary"])
    give_deck(g, A, ["Estate", "Copper", "Potion", "Gold", "Silver", "Duchy"])
    assert play(g, A, "Apothecary")[0]
    # +1 Card takes the Estate; the reveal is Copper/Potion/Gold/Silver
    assert "Copper" in g["seats"][A]["hand"] and "Potion" in g["seats"][A]["hand"]
    f = frame(g)
    assert f["kind"] == "order_cards"
    assert sorted(f["constraint"]["cards"]) == ["Gold", "Silver"]
    assert decide(g, A, order=["Silver", "Gold"])[0]
    assert g["seats"][A]["deck"][:2] == ["Silver", "Gold"]
    assert g["seats"][A]["aside"] == []


def test_apothecary_with_only_coppers_needs_no_reorder():
    g = fresh()
    give_hand(g, A, ["Apothecary"])
    give_deck(g, A, ["Estate", "Copper", "Copper", "Potion", "Copper"])
    assert play(g, A, "Apothecary")[0]
    assert g["pending"] == []
    assert g["seats"][A]["hand"].count("Copper") == 3


# ── Apprentice ────────────────────────────────────────────────────────────────

def test_apprentice_draws_one_per_coin():
    g = fresh(kingdom=KAL, expansions=("base", "alchemy"))
    give_hand(g, A, ["Apprentice", "Gold"])
    give_deck(g, A, ["Estate"] * 8)
    assert play(g, A, "Apprentice")[0]
    assert decide(g, A, cards=["Gold"])[0]           # $6
    assert g["seats"][A]["hand"].count("Estate") == 6
    assert g["trash"] == ["Gold"]
    assert g["actions"] == 1


def test_apprentice_draws_two_more_for_a_potion_in_the_cost():
    g = fresh()
    give_hand(g, A, ["Apprentice", "Golem"])
    give_deck(g, A, ["Estate"] * 10)
    assert play(g, A, "Apprentice")[0]
    assert decide(g, A, cards=["Golem"])[0]          # {$4,P} -> 4 + 2
    assert g["seats"][A]["hand"].count("Estate") == 6


def test_apprentice_on_a_pure_potion_cost_draws_only_the_bonus():
    g = fresh()
    give_hand(g, A, ["Apprentice", "Transmute"])
    give_deck(g, A, ["Estate"] * 6)
    assert play(g, A, "Apprentice")[0]
    assert decide(g, A, cards=["Transmute"])[0]      # {$0,P} -> 0 + 2
    assert g["seats"][A]["hand"].count("Estate") == 2


def test_apprentice_draws_fewer_under_a_cost_reduction():
    """"If there is a COST REDUCTION, Apprentice will draw fewer cards.\""""
    g = fresh(kingdom=KAL + ["Bridge"], expansions=("intrigue", "alchemy"))
    give_hand(g, A, ["Bridge", "Apprentice", "Gold"])
    g["actions"] = 2
    give_deck(g, A, ["Estate"] * 8)
    assert play(g, A, "Bridge")[0]
    assert play(g, A, "Apprentice")[0]
    assert decide(g, A, cards=["Gold"])[0]           # $6 - $1 = 5
    assert g["seats"][A]["hand"].count("Estate") == 5


def test_apprentice_with_an_empty_hand_does_nothing():
    g = fresh()
    give_hand(g, A, ["Apprentice"])
    assert play(g, A, "Apprentice")[0]
    assert g["pending"] == [] and g["trash"] == []


# ── Familiar ──────────────────────────────────────────────────────────────────

def test_familiar_is_a_cursing_cantrip():
    g = fresh(players=(A, B, C))
    give_hand(g, A, ["Familiar"])
    give_deck(g, A, ["Gold"])
    assert play(g, A, "Familiar")[0]
    assert "Gold" in g["seats"][A]["hand"] and g["actions"] == 1
    for p in (B, C):
        assert "Curse" in g["seats"][p]["discard"]


def test_familiar_is_blocked_by_a_moat():
    g = fresh(kingdom=KAL + ["Moat"], expansions=("base", "alchemy"))
    give_hand(g, A, ["Familiar"])
    give_deck(g, A, ["Gold"])
    give_hand(g, B, ["Moat"])
    assert play(g, A, "Familiar")[0]
    assert decide(g, B, ids=["react:Moat"])[0]
    assert "Curse" not in g["seats"][B]["discard"]


# ── Golem ─────────────────────────────────────────────────────────────────────

def test_golem_digs_past_golems_and_plays_both_actions():
    g = fresh(kingdom=KAL + ["Village", "Smithy"], expansions=("base", "alchemy"))
    give_hand(g, A, ["Golem"])
    give_deck(g, A, ["Copper", "Golem", "Village", "Estate", "Smithy", "Gold"])
    assert play(g, A, "Golem")[0]
    f = frame(g)
    assert f["card"] == "Golem" and f["kind"] == "choose_option"
    # the dug-past cards are discarded BEFORE the plays — asserted here because
    # Village and Smithy then draw, and on a short deck that reshuffles the
    # discard pile straight back into the deck
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Estate", "Golem"]
    assert decide(g, A, ids=["first"])[0]            # Village first
    assert "Village" in g["seats"][A]["in_play"]
    assert "Smithy" in g["seats"][A]["in_play"]
    assert g["seats"][A]["aside"] == []


def test_golem_can_play_the_second_action_first():
    g = fresh(kingdom=KAL + ["Village", "Smithy"], expansions=("base", "alchemy"))
    give_hand(g, A, ["Golem"])
    give_deck(g, A, ["Village", "Smithy"] + ["Gold"] * 6)
    assert play(g, A, "Golem")[0]
    assert decide(g, A, ids=["second"])[0]           # Smithy first
    played = [e for e in g["log"] if e["event"] == "play"]
    assert [e["card"] for e in played][-2:] == ["Smithy", "Village"]


def test_golem_with_only_one_action_in_the_deck_plays_just_it():
    g = fresh(kingdom=KAL + ["Village"], expansions=("base", "alchemy"))
    give_hand(g, A, ["Golem"])
    g["seats"][A]["deck"] = ["Copper", "Village", "Estate"]
    g["seats"][A]["discard"] = []
    assert play(g, A, "Golem")[0]
    assert "Village" in g["seats"][A]["in_play"]
    # Village drew the Estate back out of the reshuffle, so assert what was
    # discarded rather than what remains there
    assert "Copper" in engine.owned_cards(g, A)


def test_golem_does_not_prompt_when_both_actions_are_the_same_card():
    g = fresh(kingdom=KAL + ["Village"], expansions=("base", "alchemy"))
    give_hand(g, A, ["Golem"])
    give_deck(g, A, ["Village", "Village"] + ["Gold"] * 6)
    assert play(g, A, "Golem")[0]
    assert g["seats"][A]["in_play"].count("Village") == 2
    assert g["actions"] == 4                          # 1 - 1 + 2 + 2


# ── Herbalist ─────────────────────────────────────────────────────────────────

def test_herbalist_topdecks_a_treasure_it_discards_from_play():
    g = fresh()
    give_hand(g, A, ["Herbalist", "Gold"])
    assert play(g, A, "Herbalist")[0]
    assert g["buys"] == 2 and g["coins"] == 1
    to_buy(g, coins=1)
    assert mv(g, A, {"type": "play_treasure", "card": "Gold"})[0]
    assert end_buy(g, A)[0]
    f = frame(g)
    assert f["card"] == "Herbalist"
    assert "Gold" in f["constraint"]["cards"]
    assert decide(g, A, cards=["Gold"])[0]
    assert "Gold" in g["seats"][A]["hand"], "topdecked, then drawn by Clean-up"
    assert "Gold" not in g["seats"][A]["discard"]


def test_herbalist_may_decline():
    g = fresh()
    give_hand(g, A, ["Herbalist", "Gold"])
    assert play(g, A, "Herbalist")[0]
    to_buy(g, coins=1)
    assert mv(g, A, {"type": "play_treasure", "card": "Gold"})[0]
    assert end_buy(g, A)[0]
    assert decide(g, A, cards=[])[0]
    assert "Gold" in g["seats"][A]["discard"]


def test_herbalist_offers_nothing_with_no_treasure_in_play():
    g = fresh()
    give_hand(g, A, ["Herbalist"])
    assert play(g, A, "Herbalist")[0]
    to_buy(g, coins=1)
    assert end_buy(g, A)[0]
    assert g["turn"] == B


def test_herbalist_cannot_topdeck_a_treasure_that_stays_in_play():
    """"If a card is not discarded (for instance if it's a Duration that stays
    in play) Herbalist can't put it onto your deck." leaving_play is what makes
    that fall out rather than needing a special case."""
    g = engine.new_game([A, B], ["base", "seaside", "alchemy"], seed=4,
                        kingdom=["Herbalist", "Astrolabe", "Village", "Smithy",
                                 "Market", "Festival", "Laboratory", "Militia",
                                 "Mine", "Library"])
    give_hand(g, A, ["Herbalist", "Astrolabe", "Gold"])
    assert play(g, A, "Herbalist")[0]
    to_buy(g, coins=1)
    assert mv(g, A, {"type": "play_treasure", "card": "Astrolabe"})[0]
    assert mv(g, A, {"type": "play_treasure", "card": "Gold"})[0]
    assert end_buy(g, A)[0]
    f = frame(g)
    assert f is not None and f["card"] == "Herbalist"
    assert f["constraint"]["cards"] == ["Gold"], \
        "the Astrolabe is a Duration staying in play — it is not discarded"


def test_a_throne_roomed_herbalist_may_topdeck_two_treasures():
    """"If you play Herbalist with a throne-room, you may choose multiple
    Treasures" — which the per-play watcher gives for free."""
    g = fresh(kingdom=KAL + ["Throne Room"], expansions=("base", "alchemy"))
    give_hand(g, A, ["Throne Room", "Herbalist", "Gold", "Silver"])
    assert play(g, A, "Throne Room")[0]
    assert decide(g, A, cards=["Herbalist"])[0]
    to_buy(g, coins=2)
    assert mv(g, A, {"type": "play_treasure", "card": "Gold"})[0]
    assert mv(g, A, {"type": "play_treasure", "card": "Silver"})[0]
    assert end_buy(g, A)[0]
    picked = []
    for _ in range(4):
        f = frame(g)
        if f is None or f["card"] != "Herbalist":
            break
        want = f["constraint"]["cards"][0]
        picked.append(want)
        assert decide(g, A, cards=[want])[0]
    assert len(picked) == 2
    hand = g["seats"][A]["hand"]
    assert "Gold" in hand and "Silver" in hand
    assert "Gold" not in g["seats"][A]["discard"]


# ── Philosopher's Stone ───────────────────────────────────────────────────────

@pytest.mark.parametrize("deck,discard,want", [(0, 0, 0), (4, 0, 0), (5, 0, 1),
                                               (7, 8, 3), (12, 13, 5)])
def test_philosophers_stone_counts_deck_plus_discard(deck, discard, want):
    g = fresh()
    seat = g["seats"][A]
    seat["deck"] = ["Copper"] * deck
    seat["discard"] = ["Estate"] * discard
    give_hand(g, A, ["Philosopher's Stone"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Philosopher's Stone"})[0]
    assert g["coins"] == want


# ── Scrying Pool ──────────────────────────────────────────────────────────────

def test_scrying_pool_lets_the_attacker_choose_for_everyone_then_digs():
    g = fresh()
    give_hand(g, A, ["Scrying Pool"])
    give_deck(g, A, ["Village" if False else "Alchemist", "Familiar", "Copper", "Gold"])
    give_deck(g, B, ["Estate", "Gold"])
    assert play(g, A, "Scrying Pool")[0]
    # "EACH PLAYER" is turn order starting with YOU, so your own card is first
    f = frame(g)
    assert f["pid"] == A and f["data"]["target"] == A
    assert decide(g, A, ids=["keep"])[0]
    # ...then each opponent, still decided by the attacker
    f = frame(g)
    assert f["pid"] == A, "the ATTACKER chooses"
    assert f["data"]["target"] == B
    assert decide(g, A, ids=["discard"])[0]
    assert "Estate" in g["seats"][B]["discard"]
    # the dig then takes the Actions plus the first non-Action
    assert sorted(g["seats"][A]["hand"]) == ["Alchemist", "Copper", "Familiar"]
    assert g["seats"][A]["deck"] == ["Gold"]


def test_scrying_pool_includes_you_even_with_no_opponents_affected():
    g = fresh(kingdom=KAL + ["Moat"], expansions=("base", "alchemy"))
    give_hand(g, A, ["Scrying Pool"])
    give_deck(g, A, ["Copper", "Gold"])
    give_hand(g, B, ["Moat"])
    assert play(g, A, "Scrying Pool")[0]
    assert decide(g, B, ids=["react:Moat"])[0]
    f = frame(g)
    assert f["data"]["target"] == A, "you still reveal your own"
    assert decide(g, A, ids=["keep"])[0]
    assert "Copper" in g["seats"][A]["hand"]


def test_scrying_pool_digs_for_a_NON_action():
    """The 2018 rulebook says "Action card" and is an erratum — the dig stops
    on the first NON-Action."""
    g = fresh()
    give_hand(g, A, ["Scrying Pool"])
    give_deck(g, A, ["Copper", "Estate"])
    g["seats"][A]["discard"] = []
    give_deck(g, B, [])
    g["seats"][B]["discard"] = []
    assert play(g, A, "Scrying Pool")[0]
    assert decide(g, A, ids=["keep"])[0]              # A's own Copper stays
    assert g["seats"][A]["hand"] == ["Copper"], "stopped on the first non-Action"


# ── Transmute ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("card,want", [
    ("Village", ["Duchy"]),          # Action
    ("Copper", ["Transmute"]),       # Treasure
    ("Estate", ["Gold"]),            # Victory
])
def test_transmute_each_single_type(card, want):
    g = fresh(kingdom=KAL + ["Village"], expansions=("base", "alchemy"))
    give_hand(g, A, ["Transmute", card])
    assert play(g, A, "Transmute")[0]
    assert decide(g, A, cards=[card])[0]
    assert sorted(g["seats"][A]["discard"]) == sorted(want)
    assert g["trash"] == [card]


def test_transmute_gains_all_of_them_for_a_multi_type_card():
    """"If you trash a card that has several of the types, you gain all
    relevant cards (Duchy, Transmute, Gold)" — Farm is Treasure-Victory."""
    g = engine.new_game([A, B], ["intrigue", "alchemy"], seed=4,
                        kingdom=["Transmute", "Farm", "Courtyard", "Pawn",
                                 "Steward", "Baron", "Bridge", "Ironworks",
                                 "Mill", "Nobles"])
    give_hand(g, A, ["Transmute", "Farm"])
    assert play(g, A, "Transmute")[0]
    assert decide(g, A, cards=["Farm"])[0]
    assert sorted(g["seats"][A]["discard"]) == ["Gold", "Transmute"]


def test_transmute_gains_nothing_it_cannot_reach():
    g = fresh(kingdom=KAL + ["Village"], expansions=("base", "alchemy"))
    g["supply"]["Duchy"] = 0
    give_hand(g, A, ["Transmute", "Village"])
    assert play(g, A, "Transmute")[0]
    assert decide(g, A, cards=["Village"])[0]
    assert g["seats"][A]["discard"] == []
    assert g["trash"] == ["Village"]


# ── University ────────────────────────────────────────────────────────────────

def test_university_gains_an_action_up_to_five_and_never_a_potion_card():
    g = fresh(kingdom=KAL + ["Village"], expansions=("base", "alchemy"))
    give_hand(g, A, ["University"])
    assert play(g, A, "University")[0]
    assert g["actions"] == 2
    f = frame(g)
    # "You MAY gain" — a 0-or-1 pick, not a forced pile choice
    assert f["kind"] == "choose_cards" and f["constraint"]["min"] == 0
    piles = f["constraint"]["cards"]
    for p in piles:
        assert engine.has_type(g, p, "action") and engine.cost(g, p) <= 5
        assert engine.potion_cost(g, p) == 0, "'up to $5' excludes Potion costs"
    assert "Golem" not in piles and "Alchemist" not in piles
    assert "Silver" not in piles, "Actions only"
    assert decide(g, A, cards=["Village"])[0]
    assert "Village" in g["seats"][A]["discard"]


def test_university_may_decline_to_gain():
    """"You MAY gain an Action card" — a forced pile choice would have made it
    mandatory, which is the kind of thing only re-reading the card catches."""
    g = fresh(kingdom=KAL + ["Village"], expansions=("base", "alchemy"))
    give_hand(g, A, ["University"])
    assert play(g, A, "University")[0]
    assert decide(g, A, cards=[])[0]
    assert g["seats"][A]["discard"] == []
    assert g["pending"] == []


# ── Vineyard ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("n_actions,want", [(0, 0), (2, 0), (3, 1), (8, 2), (9, 3)])
def test_vineyard_scores_one_per_three_actions(n_actions, want):
    g = fresh(kingdom=KAL + ["Village"], expansions=("base", "alchemy"))
    seat = g["seats"][A]
    for z in ("deck", "hand", "discard", "in_play"):
        seat[z] = []
    seat["deck"] = ["Vineyard"] + ["Village"] * n_actions
    assert engine._vp_of(g, A) == want
    engine._post_move(g)
    assert g["vp"][A] == want


def test_vineyard_counts_every_action_you_own_wherever_it_is():
    g = fresh(kingdom=KAL + ["Village"], expansions=("base", "alchemy"))
    seat = g["seats"][A]
    for z in ("deck", "hand", "discard", "in_play"):
        seat[z] = []
    seat["deck"] = ["Vineyard", "Village"]
    seat["hand"] = ["Smithy"]
    seat["in_play"] = ["Market"]
    assert engine._vp_of(g, A) == 1          # 3 Actions -> 1 VP


def test_two_vineyards_each_score():
    g = fresh(kingdom=KAL + ["Village"], expansions=("base", "alchemy"))
    seat = g["seats"][A]
    for z in ("deck", "hand", "discard", "in_play"):
        seat[z] = []
    seat["deck"] = ["Vineyard", "Vineyard"] + ["Village"] * 3
    assert engine._vp_of(g, A) == 2


# ── the deferral, and the set as a whole ──────────────────────────────────────

def test_possession_is_absent_everywhere_it_would_otherwise_appear():
    """The deferral has to hold at every surface, not just in CARDS: an entry
    left in a kingdom pool or an effects registry would deal an unplayable
    card."""
    from games.dontminion import cards, effects
    assert "Possession" not in cards.CARDS
    assert "Possession" not in cards.KINGDOM["alchemy"]
    assert "Possession" not in effects.EFFECTS
    assert not any(k[0] == "Possession" for k in effects.STAGES)
    g = fresh(expansions=("alchemy",))
    assert "Possession" not in g["supply"]


def test_every_shipped_alchemy_card_does_something_when_played():
    from games.dontminion import cards, effects
    for name in cards.KINGDOM["alchemy"]:
        types = cards.CARDS[name]["types"]
        if "action" in types or "treasure" in types:
            assert name in effects.EFFECTS, f"{name} is playable but does nothing"
        else:
            assert name not in effects.EFFECTS
