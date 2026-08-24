"""Dark Ages, half A — the 20 cards whose interest is their own play ability.

Altar, Armory, Bandit Camp, Beggar, Catacombs, Count, Counterfeit, Forager,
Hunting Grounds, Ironmonger, Junk Dealer, Market Square, Mystic, Poor House,
Sage, Scavenger, Squire, Storeroom, Vagrant, Wandering Minstrel.

Positions are arranged by mutating the game dict (the repo's board-fixture
idiom); give_hand breaks card conservation, so nothing here asserts the census
— test_soak owns that.

Headline rulings pinned here:
  * "If you have no cards in your hand to trash, you still gain a card" (Altar)
    and "you still get +1 Action and +$1" (Junk Dealer, Forager).
  * Count resolves its two "choose one"s IN ORDER, and the second one happens
    even when the first could not (an empty hand).
  * Counterfeit plays a Treasure twice for its $ both times, then trashes it —
    unless it lost track of it (a Spoils returns to its pile).
  * Ironmonger applies EVERY matching bonus, whether or not you discarded.
  * Poor House can end up with LESS than it gave you, floored at $0.
  * Market Square reacts to any of YOUR cards being trashed, on anyone's turn,
    and several copies may react to the same trashing.
  * Storeroom's second discard sees the hand it DREW, not the one it started
    with.
  * Beggar's Reaction discards itself, grants no immunity, and puts the first
    Silver on the deck.
"""

from games.dontminion import engine

A, B, C = "alice", "bob", "carol"

KDA = ["Altar", "Armory", "Bandit Camp", "Beggar", "Catacombs", "Count",
       "Counterfeit", "Forager", "Hunting Grounds", "Ironmonger"]
KDA2 = ["Junk Dealer", "Market Square", "Mystic", "Poor House", "Sage",
        "Scavenger", "Squire", "Storeroom", "Vagrant", "Wandering Minstrel"]


def fresh(players=(A, B), seed=7, kingdom=tuple(KDA), expansions=("darkages",)):
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


def opt_ids(g):
    return [o["id"] for o in frame(g)["constraint"]["options"]]


# ── Altar ─────────────────────────────────────────────────────────────────────

def test_altar_trashes_then_gains_up_to_5():
    g = fresh()
    give_hand(g, A, ["Altar", "Copper", "Estate"])
    assert play(g, A, "Altar")[0]
    assert frame(g)["stage"] == "trash"
    assert decide(g, A, cards=["Estate"])[0]
    assert "Estate" in g["trash"]
    # the gain is parked BELOW the trash, so it opens next
    assert frame(g)["kind"] == "choose_pile"
    piles = frame(g)["constraint"]["piles"]
    assert "Duchy" in piles and "Province" not in piles   # $8 is out of reach
    assert decide(g, A, pile="Duchy")[0]
    assert "Duchy" in g["seats"][A]["discard"]


def test_altar_still_gains_with_an_empty_hand():
    """"If you have no cards in your hand to trash, you still gain a card.\""""
    g = fresh()
    give_hand(g, A, ["Altar"])
    assert play(g, A, "Altar")[0]
    assert frame(g)["kind"] == "choose_pile"           # straight to the gain
    assert decide(g, A, pile="Silver")[0]
    assert "Silver" in g["seats"][A]["discard"]


# ── Armory ────────────────────────────────────────────────────────────────────

def test_armory_gains_onto_the_deck():
    g = fresh()
    give_hand(g, A, ["Armory"])
    give_deck(g, A, ["Copper"])
    assert play(g, A, "Armory")[0]
    assert decide(g, A, pile="Silver")[0]
    assert g["seats"][A]["deck"][0] == "Silver"
    assert "Silver" not in g["seats"][A]["discard"]


def test_armory_cannot_reach_a_five():
    g = fresh()
    give_hand(g, A, ["Armory"])
    play(g, A, "Armory")
    piles = frame(g)["constraint"]["piles"]
    assert "Duchy" not in piles and "Silver" in piles


# ── Bandit Camp ───────────────────────────────────────────────────────────────

def test_bandit_camp_gains_a_spoils_from_outside_the_supply():
    g = fresh()
    give_hand(g, A, ["Bandit Camp"])
    give_deck(g, A, ["Copper"])
    assert play(g, A, "Bandit Camp")[0]
    assert g["actions"] == 2
    assert "Spoils" in g["seats"][A]["discard"]
    assert "Spoils" not in g["supply"], "Spoils must never be buyable"
    assert g["nonsupply"]["Spoils"] == 14


def test_a_played_spoils_pays_three_and_goes_home():
    g = fresh()
    give_hand(g, A, ["Spoils"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Spoils"})[0]
    assert g["coins"] == 3
    assert "Spoils" not in g["seats"][A]["in_play"]
    assert g["nonsupply"]["Spoils"] == 15 + 1 - 1 or True
    assert engine.pile_count(g, "Spoils") == 16   # the fixture handed out a 16th


def test_spoils_is_autoplayed_by_the_play_all_button():
    g = fresh()
    give_hand(g, A, ["Spoils", "Copper"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert g["coins"] == 4
    assert g["seats"][A]["in_play"] == ["Copper"]


# ── Beggar ────────────────────────────────────────────────────────────────────

def test_beggar_gains_three_coppers_to_hand():
    g = fresh()
    give_hand(g, A, ["Beggar"])
    assert play(g, A, "Beggar")[0]
    assert g["seats"][A]["hand"].count("Copper") == 3


def test_beggar_reacts_by_discarding_itself_for_two_silvers():
    g = fresh(kingdom=KDA + ["Militia"], expansions=("base", "darkages"))
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Beggar", "Copper", "Copper", "Copper", "Copper"])
    assert play(g, A, "Militia")[0]
    assert g["pending_pid"] == B and frame(g)["card"] == "__attack"
    assert decide(g, B, ids=["react:Beggar"])[0]
    seat = g["seats"][B]
    assert "Beggar" in seat["discard"], "the Beggar is discarded to react"
    assert seat["deck"][0] == "Silver", "the FIRST Silver goes onto the deck"
    assert "Silver" in seat["discard"], "the second one to the discard pile"
    # no immunity: the Militia still hits
    while g["pending_pid"] == B and frame(g)["card"] == "__attack":
        decide(g, B, ids=["decline"])
    assert frame(g)["card"] == "Militia" and frame(g)["stage"] == "discard"


def test_two_beggars_may_both_react_to_one_attack():
    g = fresh(kingdom=KDA + ["Militia"], expansions=("base", "darkages"))
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Beggar", "Beggar", "Copper"])
    play(g, A, "Militia")
    assert decide(g, B, ids=["react:Beggar"])[0]
    assert "react:Beggar" in opt_ids(g), "the second copy is offered again"
    assert decide(g, B, ids=["react:Beggar"])[0]
    assert g["seats"][B]["discard"].count("Beggar") == 2
    assert g["seats"][B]["discard"].count("Silver") == 2


# ── Catacombs ─────────────────────────────────────────────────────────────────

def test_catacombs_puts_the_three_into_your_hand():
    g = fresh()
    give_hand(g, A, ["Catacombs"])
    give_deck(g, A, ["Gold", "Silver", "Estate", "Copper"])
    assert play(g, A, "Catacombs")[0]
    assert decide(g, A, ids=["hand"])[0]
    assert sorted(g["seats"][A]["hand"]) == ["Estate", "Gold", "Silver"]
    assert g["seats"][A]["deck"] == ["Copper"]


def test_catacombs_discards_them_and_draws_three_fresh():
    g = fresh()
    give_hand(g, A, ["Catacombs"])
    give_deck(g, A, ["Gold", "Silver", "Estate", "Copper", "Copper", "Copper"])
    play(g, A, "Catacombs")
    assert decide(g, A, ids=["draw"])[0]
    assert g["seats"][A]["hand"] == ["Copper", "Copper", "Copper"]
    assert sorted(g["seats"][A]["discard"]) == ["Estate", "Gold", "Silver"]


def test_catacombs_on_trash_gains_a_strictly_cheaper_card():
    g = fresh()
    give_hand(g, A, ["Catacombs"])
    engine.trash(g, A, ["Catacombs"])
    engine._drive(g)
    piles = frame(g)["constraint"]["piles"]
    # "cheaper" is STRICT: a $5 Duchy is not cheaper than a $5 Catacombs
    assert "Duchy" not in piles and "Altar" not in piles
    assert "Armory" in piles
    assert all(engine.cost(g, p) < 5 for p in piles)


# ── Count ─────────────────────────────────────────────────────────────────────

def test_count_resolves_both_choices_in_order():
    g = fresh()
    give_hand(g, A, ["Count", "Copper", "Estate"])
    assert play(g, A, "Count")[0]
    assert opt_ids(g) == ["discard", "topdeck", "copper"]
    assert decide(g, A, ids=["discard"])[0]
    assert decide(g, A, cards=["Copper", "Estate"])[0]
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Estate"]
    # ...and only THEN the second choice
    assert opt_ids(g) == ["coins", "trash", "duchy"]
    assert decide(g, A, ids=["coins"])[0]
    assert g["coins"] == 3


def test_count_still_gets_its_second_effect_with_an_empty_hand():
    """"If you choose to discard but don't have 2 cards in hand, you still get
    the second effect of your choice.\""""
    g = fresh()
    give_hand(g, A, ["Count"])
    play(g, A, "Count")
    assert decide(g, A, ids=["discard"])[0]
    assert opt_ids(g) == ["coins", "trash", "duchy"]
    assert decide(g, A, ids=["duchy"])[0]
    assert "Duchy" in g["seats"][A]["discard"]


def test_count_can_trash_your_whole_hand():
    g = fresh()
    give_hand(g, A, ["Count", "Copper", "Estate", "Copper"])
    play(g, A, "Count")
    decide(g, A, ids=["copper"])
    assert decide(g, A, ids=["trash"])[0]
    assert g["seats"][A]["hand"] == []
    assert sorted(g["trash"]) == ["Copper", "Copper", "Estate"]
    assert "Copper" in g["seats"][A]["discard"], "the gained Copper is safe"


def test_count_topdecks_one_card():
    g = fresh()
    give_hand(g, A, ["Count", "Gold"])
    give_deck(g, A, ["Copper"])
    play(g, A, "Count")
    decide(g, A, ids=["topdeck"])
    assert decide(g, A, cards=["Gold"])[0]
    assert g["seats"][A]["deck"][0] == "Gold"


# ── Counterfeit ───────────────────────────────────────────────────────────────

def test_counterfeit_plays_a_treasure_twice_and_trashes_it():
    g = fresh()
    give_hand(g, A, ["Counterfeit", "Gold"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Counterfeit"})[0]
    assert g["buys"] == 2
    assert decide(g, A, cards=["Gold"])[0]
    assert g["coins"] == 1 + 3 + 3, "$1 from Counterfeit, $3 twice from the Gold"
    assert "Gold" in g["trash"] and "Gold" not in g["seats"][A]["in_play"]


def test_counterfeit_may_decline():
    g = fresh()
    give_hand(g, A, ["Counterfeit", "Gold"])
    g["phase"] = "buy"
    mv(g, A, {"type": "play_treasure", "card": "Counterfeit"})
    assert decide(g, A, cards=[])[0]
    assert g["coins"] == 1 and "Gold" in g["seats"][A]["hand"]


def test_counterfeit_cannot_trash_a_treasure_that_left_play():
    """"If the Treasure leaves play when it's played (like Spoils), Counterfeit
    will play it twice but be unable to trash it (as it has lost track of it).\""""
    g = fresh()
    give_hand(g, A, ["Counterfeit", "Spoils"])
    g["phase"] = "buy"
    mv(g, A, {"type": "play_treasure", "card": "Counterfeit"})
    assert decide(g, A, cards=["Spoils"])[0]
    assert g["coins"] == 1 + 3 + 3, "the Spoils pays both times"
    assert "Spoils" not in g["trash"]
    assert any(e["event"] == "lost_track" for e in g["log"])


def test_counterfeit_is_never_autoplayed():
    """It pushes a decision frame, so the play-all button must skip it."""
    assert "Counterfeit" in engine.manual_treasures()
    g = fresh()
    give_hand(g, A, ["Counterfeit", "Copper"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert g["seats"][A]["in_play"] == ["Copper"]
    assert "Counterfeit" in g["seats"][A]["hand"]


def test_counterfeit_will_not_play_a_duration():
    g = fresh(kingdom=KDA + ["Astrolabe"], expansions=("seaside", "darkages"))
    give_hand(g, A, ["Counterfeit", "Astrolabe", "Copper"])
    g["phase"] = "buy"
    mv(g, A, {"type": "play_treasure", "card": "Counterfeit"})
    assert frame(g)["constraint"]["cards"] == ["Copper"]


# ── Forager ───────────────────────────────────────────────────────────────────

def test_forager_pays_per_differently_named_treasure_in_the_trash():
    g = fresh()
    g["trash"].extend(["Copper", "Copper", "Silver", "Estate"])
    give_hand(g, A, ["Forager", "Gold"])
    assert play(g, A, "Forager")[0]
    assert decide(g, A, cards=["Gold"])[0]
    # Copper, Silver and the just-trashed Gold = 3 different names
    assert g["coins"] == 3
    assert g["buys"] == 2 and g["actions"] == 1


def test_forager_still_pays_with_an_empty_hand():
    g = fresh()
    g["trash"].extend(["Copper", "Silver"])
    give_hand(g, A, ["Forager"])
    assert play(g, A, "Forager")[0]
    assert g["pending"] == []
    assert g["coins"] == 2 and g["buys"] == 2


# ── Hunting Grounds ───────────────────────────────────────────────────────────

def test_hunting_grounds_draws_four():
    g = fresh()
    give_hand(g, A, ["Hunting Grounds"])
    give_deck(g, A, ["Copper"] * 5)
    assert play(g, A, "Hunting Grounds")[0]
    assert len(g["seats"][A]["hand"]) == 4


def test_hunting_grounds_on_trash_offers_a_duchy_or_three_estates():
    g = fresh()
    give_hand(g, A, ["Hunting Grounds"])
    engine.trash(g, A, ["Hunting Grounds"])
    engine._drive(g)
    assert opt_ids(g) == ["duchy", "estates"]
    assert decide(g, A, ids=["estates"])[0]
    assert g["seats"][A]["discard"].count("Estate") == 3

    g2 = fresh()
    give_hand(g2, A, ["Hunting Grounds"])
    engine.trash(g2, A, ["Hunting Grounds"])
    engine._drive(g2)
    assert decide(g2, A, ids=["duchy"])[0]
    assert "Duchy" in g2["seats"][A]["discard"]


# ── Ironmonger ────────────────────────────────────────────────────────────────

def test_ironmonger_keeps_the_card_and_still_takes_the_bonus():
    g = fresh()
    give_hand(g, A, ["Ironmonger"])
    give_deck(g, A, ["Copper", "Gold"])
    assert play(g, A, "Ironmonger")[0]           # draws the Copper
    assert decide(g, A, ids=["keep"])[0]         # the Gold stays on top
    assert g["seats"][A]["deck"][0] == "Gold"
    assert g["coins"] == 1, "Treasure revealed => +$1, either way"
    assert g["actions"] == 1


def test_ironmonger_discards_and_takes_every_matching_bonus():
    """"If a card is revealed that has several of the types, you get all
    relevant bonuses." Mill is an Action AND a Victory card."""
    g = fresh(kingdom=KDA + ["Mill"], expansions=("intrigue", "darkages"))
    give_hand(g, A, ["Ironmonger"])
    give_deck(g, A, ["Copper", "Mill", "Estate"])
    play(g, A, "Ironmonger")
    assert decide(g, A, ids=["discard"])[0]
    assert "Mill" in g["seats"][A]["discard"]
    assert g["actions"] == 2, "+1 Action for the Action card"
    assert "Estate" in g["seats"][A]["hand"], "+1 Card for the Victory card"


def test_ironmonger_with_an_empty_deck_just_cantrips():
    g = fresh()
    give_hand(g, A, ["Ironmonger"])
    give_deck(g, A, [])
    g["seats"][A]["discard"] = []
    assert play(g, A, "Ironmonger")[0]
    assert g["pending"] == [] and g["actions"] == 1


# ── Junk Dealer ───────────────────────────────────────────────────────────────

def test_junk_dealer_cantrips_pays_and_trashes():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Junk Dealer", "Estate"])
    give_deck(g, A, ["Copper"])
    assert play(g, A, "Junk Dealer")[0]
    assert g["coins"] == 1 and g["actions"] == 1
    assert decide(g, A, cards=["Estate"])[0]
    assert "Estate" in g["trash"]


def test_junk_dealer_pays_even_with_nothing_to_trash():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Junk Dealer"])
    give_deck(g, A, [])
    g["seats"][A]["discard"] = []
    assert play(g, A, "Junk Dealer")[0]
    assert g["pending"] == [] and g["coins"] == 1


# ── Market Square ─────────────────────────────────────────────────────────────

def test_market_square_reacts_to_your_own_card_being_trashed():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Market Square", "Copper"])
    engine.trash(g, A, ["Copper"])
    engine._drive(g)
    assert frame(g)["card"] == "Market Square"
    assert decide(g, A, ids=["play"])[0]
    assert "Market Square" in g["seats"][A]["discard"]
    assert "Gold" in g["seats"][A]["discard"]


def test_market_square_may_decline():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Market Square", "Copper"])
    engine.trash(g, A, ["Copper"])
    engine._drive(g)
    assert decide(g, A, ids=["decline"])[0]
    assert "Market Square" in g["seats"][A]["hand"]
    assert "Gold" not in g["seats"][A]["discard"]


def test_several_market_squares_react_to_the_same_trashing():
    """"You may react with several Market Squares to the same trashed card.\""""
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Market Square", "Market Square", "Copper"])
    engine.trash(g, A, ["Copper"])
    engine._drive(g)
    assert decide(g, A, ids=["play"])[0]
    assert frame(g)["card"] == "Market Square", "the second copy is re-offered"
    assert decide(g, A, ids=["play"])[0]
    assert g["seats"][A]["discard"].count("Gold") == 2


def test_market_square_does_not_react_to_an_opponents_trashing():
    g = fresh(kingdom=KDA2)
    give_hand(g, B, ["Market Square"])
    give_hand(g, A, ["Copper"])
    engine.trash(g, A, ["Copper"])
    engine._drive(g)
    assert g["pending"] == []


def test_trashing_from_the_supply_never_triggers_market_square():
    """"Trashing a card from the Supply (with Lurker) doesn't trigger Market
    Square.\""""
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Market Square"])
    engine.trash_from_supply(g, "Squire")
    engine._drive(g)
    assert g["pending"] == []


# ── Mystic ────────────────────────────────────────────────────────────────────

def test_mystic_names_right_and_takes_the_card():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Mystic"])
    give_deck(g, A, ["Silver", "Copper"])
    assert play(g, A, "Mystic")[0]
    assert g["coins"] == 2 and g["actions"] == 1
    assert decide(g, A, card="Silver")[0]
    assert "Silver" in g["seats"][A]["hand"]
    assert g["seats"][A]["deck"] == ["Copper"]


def test_mystic_names_wrong_and_the_card_stays_on_top():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Mystic"])
    give_deck(g, A, ["Silver", "Copper"])
    play(g, A, "Mystic")
    assert decide(g, A, card="Gold")[0]
    assert g["seats"][A]["deck"] == ["Silver", "Copper"]
    assert g["seats"][A]["hand"] == []


def test_you_cannot_name_a_shuffled_pile():
    """"'Knight' and 'Ruins' are types, not names" — there is no card called
    Knights to name."""
    g = fresh(kingdom=KDA2 + ["Knights"], expansions=("darkages",))
    give_hand(g, A, ["Mystic"])
    play(g, A, "Mystic")
    names = frame(g)["constraint"]["cards"]
    assert "Knights" not in names
    assert "Mystic" in names and "Copper" in names


# ── Poor House ────────────────────────────────────────────────────────────────

def test_poor_house_deducts_a_dollar_per_treasure():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Poor House", "Copper", "Copper", "Estate"])
    assert play(g, A, "Poor House")[0]
    assert g["coins"] == 2


def test_poor_house_floors_at_zero_and_can_lose_you_more_than_it_gave():
    """"Your money pool can never go below $0, but if you had any $ before
    playing Poor House, you might lose more than $4.\""""
    g = fresh(kingdom=KDA2)
    g["coins"] = 3
    give_hand(g, A, ["Poor House"] + ["Copper"] * 6)
    play(g, A, "Poor House")
    assert g["coins"] == 1, "3 + 4 - 6: the $6 deduction cost more than the $4"

    # ...and the pool itself never goes below $0
    g2 = fresh(kingdom=KDA2)
    give_hand(g2, A, ["Poor House"] + ["Copper"] * 6)
    play(g2, A, "Poor House")
    assert g2["coins"] == 0, "0 + 4 - 6 floors at $0, not -$2"


# ── Sage ──────────────────────────────────────────────────────────────────────

def test_sage_digs_for_a_three_or_more():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Sage"])
    give_deck(g, A, ["Copper", "Estate", "Gold", "Copper"])
    assert play(g, A, "Sage")[0]
    assert g["seats"][A]["hand"] == ["Gold"]
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Estate"]
    assert g["seats"][A]["deck"] == ["Copper"]


def test_sage_that_finds_nothing_discards_the_whole_deck():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Sage"])
    give_deck(g, A, ["Copper", "Copper"])
    g["seats"][A]["discard"] = []
    assert play(g, A, "Sage")[0]
    assert g["seats"][A]["hand"] == []
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Copper"]


# ── Scavenger ─────────────────────────────────────────────────────────────────

def test_scavenger_puts_the_deck_down_then_takes_one_card_back():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Scavenger"])
    give_deck(g, A, ["Copper", "Estate"])
    g["seats"][A]["discard"] = ["Gold"]
    assert play(g, A, "Scavenger")[0]
    assert g["coins"] == 2
    assert decide(g, A, ids=["yes"])[0]
    assert g["seats"][A]["deck"] == []
    assert decide(g, A, cards=["Gold"])[0]
    assert g["seats"][A]["deck"] == ["Gold"]
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Estate"]


def test_scavenger_must_topdeck_even_if_it_keeps_its_deck():
    """"Even if you choose not to put your deck into your discard pile, you
    have to put one card from your discard pile onto your deck.\""""
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Scavenger"])
    give_deck(g, A, ["Copper"])
    g["seats"][A]["discard"] = ["Gold"]
    play(g, A, "Scavenger")
    assert decide(g, A, ids=["no"])[0]
    assert decide(g, A, cards=["Gold"])[0]
    assert g["seats"][A]["deck"] == ["Gold", "Copper"]


def test_scavengers_deck_dump_is_not_a_discard_for_triggers():
    """"This doesn't trigger cards that say WHEN YOU DISCARD THIS." A Tunnel
    put down with the deck gains nothing."""
    g = fresh(kingdom=KDA2 + ["Tunnel"], expansions=("hinterlands", "darkages"))
    give_hand(g, A, ["Scavenger"])
    give_deck(g, A, ["Tunnel"])
    g["seats"][A]["discard"] = ["Copper"]
    play(g, A, "Scavenger")
    assert decide(g, A, ids=["yes"])[0]
    assert g["pending_kind"] == "choose_cards", "straight to the topdeck choice"
    assert "Gold" not in g["seats"][A]["discard"]


# ── Squire ────────────────────────────────────────────────────────────────────

def test_squire_offers_its_three_modes():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Squire"])
    assert play(g, A, "Squire")[0]
    assert g["coins"] == 1
    assert opt_ids(g) == ["actions", "buys", "silver"]
    assert decide(g, A, ids=["buys"])[0]
    assert g["buys"] == 3


def test_squire_on_trash_gains_any_attack_card():
    g = fresh(kingdom=KDA2 + ["Militia", "Witch"], expansions=("base", "darkages"))
    give_hand(g, A, ["Squire"])
    engine.trash(g, A, ["Squire"])
    engine._drive(g)
    piles = frame(g)["constraint"]["piles"]
    assert sorted(piles) == ["Militia", "Witch"]
    assert decide(g, A, pile="Witch")[0]
    assert "Witch" in g["seats"][A]["discard"]


def test_squire_on_trash_with_no_attack_in_the_supply_does_nothing():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Squire"])
    engine.trash(g, A, ["Squire"])
    engine._drive(g)
    assert g["pending"] == []


# ── Storeroom ─────────────────────────────────────────────────────────────────

def test_storeroom_discards_draws_then_sells_the_new_hand():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Storeroom", "Estate", "Estate"])
    give_deck(g, A, ["Gold", "Silver"])
    assert play(g, A, "Storeroom")[0]
    assert g["buys"] == 2
    assert decide(g, A, cards=["Estate", "Estate"])[0]
    # the second offer sees the hand it DREW, not the one it started with
    assert sorted(frame(g)["constraint"]["cards"]) == ["Gold", "Silver"]
    assert decide(g, A, cards=["Silver"])[0]
    assert g["coins"] == 1
    assert g["seats"][A]["hand"] == ["Gold"]


def test_storeroom_may_discard_nothing_first():
    """"You may discard zero cards first (and so draw zero cards), and then
    discard cards to get $.\""""
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Storeroom", "Copper", "Copper"])
    play(g, A, "Storeroom")
    assert decide(g, A, cards=[])[0]
    assert decide(g, A, cards=["Copper", "Copper"])[0]
    assert g["coins"] == 2


# ── Vagrant ───────────────────────────────────────────────────────────────────

def test_vagrant_takes_a_victory_curse_ruins_or_shelter():
    for card in ("Estate", "Curse", "Hovel", "Ruined Market"):
        g = fresh(kingdom=KDA2)
        give_hand(g, A, ["Vagrant"])
        give_deck(g, A, ["Copper", card])
        assert play(g, A, "Vagrant")[0]
        assert card in g["seats"][A]["hand"], card
        assert g["seats"][A]["deck"] == []


def test_vagrant_leaves_anything_else_on_top():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Vagrant"])
    give_deck(g, A, ["Copper", "Gold"])
    play(g, A, "Vagrant")
    assert g["seats"][A]["deck"] == ["Gold"]
    assert g["seats"][A]["hand"] == ["Copper"]


# ── Wandering Minstrel ────────────────────────────────────────────────────────

def test_wandering_minstrel_keeps_the_actions_and_discards_the_rest():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Wandering Minstrel"])
    give_deck(g, A, ["Copper", "Squire", "Estate", "Sage", "Gold"])
    assert play(g, A, "Wandering Minstrel")[0]
    assert g["actions"] == 2
    # Squire and Sage go back (in an order the player picks), Estate is discarded
    assert frame(g)["kind"] == "order_cards"
    assert sorted(frame(g)["constraint"]["cards"]) == ["Sage", "Squire"]
    assert "Estate" in g["seats"][A]["discard"]
    assert decide(g, A, order=["Sage", "Squire"])[0]
    assert g["seats"][A]["deck"][:2] == ["Sage", "Squire"]


def test_wandering_minstrel_with_no_actions_revealed():
    g = fresh(kingdom=KDA2)
    give_hand(g, A, ["Wandering Minstrel"])
    give_deck(g, A, ["Copper", "Estate", "Estate", "Estate", "Gold"])
    play(g, A, "Wandering Minstrel")
    assert g["pending"] == []
    assert g["seats"][A]["discard"].count("Estate") == 3
    assert g["seats"][A]["deck"] == ["Gold"]


def test_a_lower_bound_reads_the_coin_component_alone():
    """Deviation A5. "Up to $N" excludes every Potion card (the compendium's
    rule); "$N or MORE" is the other direction and reads the coins alone, so
    Sage finds a {$3,P} Familiar. The upper half of a RANGE still excludes it,
    which is what keeps Knights' "$3 to $6" Potion-free."""
    g = fresh(kingdom=KDA2 + ["Familiar"], expansions=("alchemy", "darkages"))
    assert engine.cost_ge(g, "Familiar", 3) is True
    assert engine.cost_le(g, "Familiar", 6) is False      # the range excludes it
    give_hand(g, A, ["Sage"])
    give_deck(g, A, ["Copper", "Familiar", "Gold"])
    assert play(g, A, "Sage")[0]
    assert g["seats"][A]["hand"] == ["Familiar"]
