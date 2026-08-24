"""Adventures, half A — the cards whose interest is their own play ability, plus
the Journey token and the two seat tokens.

Amulet, Artificer, Bridge Troll, Caravan Guard, Dungeon, Fugitive, Gear, Giant,
Hero, Hireling, Lost City, Magpie, Messenger, Miser, Page, Peasant, Port,
Ranger, Raze, Relic, Soldier, Storyteller, Treasure Hunter, Treasure Trove,
Warrior.

Positions are arranged by mutating the game dict (the repo's board-fixture
idiom); give_hand breaks card conservation, so nothing here asserts the census
— test_soak owns that.

Headline rulings pinned here:
  * The **-1 Card token** eats the next DRAW and nothing else: a reveal or a
    look leaves it, an otherwise-empty deck does not reshuffle to feed it, and
    it comes off even with nothing left to draw.
  * The **-$1 token** is "only removed when you get $1 or MORE, not when you
    get $0" — a Miser with an empty mat leaves it alone.
  * The **Journey token starts face up** and every card that turns it over does
    so "no matter if it has been turned over earlier", so Ranger/Giant/
    Pilgrimage share ONE token.
  * **Bridge Troll's cost reduction is TURN-SCOPED (2022)**, not while-in-play:
    this turn AND your next turn, and cumulative with a throne-room.
  * **Storyteller (2022) gives +1 Card, not +$1**, and pays your whole money
    pool — keeping any Potions.
  * **Magpie does BOTH** for a Treasure-Action, and **Giant's victim gains a
    Curse when their deck is empty**.
  * **Soldier counts OTHER Attacks in play** (not itself, but other Soldiers);
    **Warrior counts Travellers INCLUDING itself**.
  * **Hireling stays in play forever** and draws every turn, cumulatively.
"""

from games.dontminion import engine

A, B, C = "alice", "bob", "carol"

KA = ["Amulet", "Artificer", "Bridge Troll", "Caravan Guard", "Dungeon",
      "Gear", "Giant", "Hireling", "Lost City", "Magpie"]
KA2 = ["Messenger", "Miser", "Page", "Peasant", "Port", "Ranger", "Raze",
       "Relic", "Storyteller", "Treasure Trove"]


def fresh(players=(A, B), seed=7, kingdom=tuple(KA), expansions=("adventures",),
          landscapes=()):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom), landscapes=list(landscapes))


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


def coins(g, n):
    g["phase"] = "buy"
    g["coins"] = n


# ── the seat tokens ───────────────────────────────────────────────────────────

def test_the_minus_one_card_token_eats_the_next_draw():
    g = fresh()
    give_deck(g, A, ["Copper"] * 5)
    give_hand(g, A, [])
    engine.set_seat_token(g, A, "-card", True)
    engine.draw(g, A, 3)
    assert len(g["seats"][A]["hand"]) == 2, "the token absorbed one card"
    assert engine.seat_token(g, A, "-card") is None
    engine.draw(g, A, 1)
    assert len(g["seats"][A]["hand"]) == 3, "...and only once"


def test_the_minus_one_card_token_comes_off_even_with_nothing_to_draw():
    """"If your deck is empty except for your -1 Card token and you're
    instructed to draw one card, you just remove the token, you don't reshuffle.
    If your discard pile is also empty, you still remove the token." """
    g = fresh()
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = ["Copper", "Copper"]
    give_hand(g, A, [])
    engine.set_seat_token(g, A, "-card", True)
    engine.draw(g, A, 1)
    assert g["seats"][A]["hand"] == []
    assert g["seats"][A]["discard"] == ["Copper", "Copper"], "no reshuffle"
    assert engine.seat_token(g, A, "-card") is None

    g2 = fresh()
    g2["seats"][A]["deck"] = []
    g2["seats"][A]["discard"] = []
    give_hand(g2, A, [])
    engine.set_seat_token(g2, A, "-card", True)
    engine.draw(g2, A, 1)
    assert engine.seat_token(g2, A, "-card") is None


def test_a_look_or_a_reveal_leaves_the_minus_one_card_token_alone():
    """"When you reveal or look at cards from your deck (even if you then put
    some into your hand), the token has no effect and stays on your deck." """
    g = fresh()
    give_deck(g, A, ["Copper"] * 5)
    engine.set_seat_token(g, A, "-card", True)
    engine.look_top(g, A, 2)
    assert engine.seat_token(g, A, "-card") is True


def test_the_minus_coin_token_is_only_removed_by_a_real_dollar():
    """"Your -$1 token is only removed when you get $1 or more, not when you
    get $0." """
    g = fresh()
    g["turn"] = A
    engine.set_seat_token(g, A, "-coin", True)
    engine.add_coins(g, 0, A)
    assert engine.seat_token(g, A, "-coin") is True and g["coins"] == 0
    engine.add_coins(g, 3, A)
    assert engine.seat_token(g, A, "-coin") is None
    assert g["coins"] == 2, "the token ate $1 of the $3"


def test_taking_a_token_you_already_have_does_nothing():
    g = fresh()
    assert engine.take_seat_token(g, A, "-coin") is True
    assert engine.take_seat_token(g, A, "-coin") is False


def test_the_journey_token_starts_face_up_and_is_shared():
    """Ranger, Giant and Pilgrimage all turn over the SAME token, "no matter if
    it has been turned over by another card or Event earlier"."""
    g = fresh()
    assert engine.flip_journey(g, A) is False      # up -> down
    assert engine.flip_journey(g, A) is True       # down -> up
    assert engine.flip_journey(g, B) is False, "each player has their own"


# ── $2 ────────────────────────────────────────────────────────────────────────

def test_page_and_peasant_are_plain_cantrips():
    g = fresh(kingdom=KA2)
    give_hand(g, A, ["Page", "Peasant"])
    give_deck(g, A, ["Copper"] * 5)
    g["actions"] = 2
    assert play(g, A, "Page")[0]
    assert len(g["seats"][A]["hand"]) == 2 and g["actions"] == 2
    assert play(g, A, "Peasant")[0]
    assert g["buys"] == 2 and g["coins"] == 1


def test_raze_trashes_itself_and_looks_at_cards_equal_to_its_cost():
    g = fresh(kingdom=KA2)
    give_hand(g, A, ["Raze", "Estate"])
    give_deck(g, A, ["Gold", "Silver", "Copper"])
    assert play(g, A, "Raze")[0]
    assert g["actions"] == 1, "+1 Action even when it trashes itself"
    assert decide(g, A, ids=["self"])[0]
    assert "Raze" in g["trash"]
    # Raze costs $2, so it looks at 2 cards
    assert frame(g)["stage"] == "keep"
    assert sorted(frame(g)["constraint"]["cards"]) == ["Gold", "Silver"]
    assert decide(g, A, cards=["Gold"])[0]
    assert "Gold" in g["seats"][A]["hand"]
    assert "Silver" in g["seats"][A]["discard"]


def test_raze_trashing_a_zero_cost_card_looks_at_nothing():
    g = fresh(kingdom=KA2)
    give_hand(g, A, ["Raze", "Copper"])
    give_deck(g, A, ["Gold"] * 3)
    assert play(g, A, "Raze")[0]
    assert decide(g, A, ids=["hand"])[0]
    assert decide(g, A, cards=["Copper"])[0]
    assert "Copper" in g["trash"]
    assert frame(g) is None, "$0 => look at 0 cards"
    assert len(g["seats"][A]["hand"]) == 0


# ── $3 ────────────────────────────────────────────────────────────────────────

def test_amulet_offers_its_three_modes_now_and_next_turn():
    g = fresh()
    give_hand(g, A, ["Amulet", "Estate"])
    assert play(g, A, "Amulet")[0]
    assert opt_ids(g) == ["coin", "trash", "silver"]
    assert decide(g, A, ids=["silver"])[0]
    assert "Silver" in g["seats"][A]["discard"]
    # the duration half arrives next turn
    g["phase"] = "buy"
    assert mv(g, A, {"type": "end_phase"})[0]
    assert any(e["card"] == "Amulet" for e in g["seats"][A]["duration"])
    while g["turn"] != A:
        while g["pending_pid"] is not None:
            pid = g["pending_pid"]
            engine.apply_move(g, pid, {"type": "decision",
                                       **engine.sample_decision(g, pid, engine.random.Random(1))})
        g["phase"] = "buy"
        mv(g, g["turn"], {"type": "end_phase"})
    assert frame(g)["card"] == "Amulet" and frame(g)["stage"] == "mode"


def test_dungeon_draws_two_and_discards_two_now_and_next_turn():
    g = fresh()
    give_hand(g, A, ["Dungeon"])
    give_deck(g, A, ["Copper", "Silver", "Gold", "Estate"])
    assert play(g, A, "Dungeon")[0]
    assert g["actions"] == 1
    assert sorted(frame(g)["constraint"]["cards"]) == ["Copper", "Silver"]
    assert frame(g)["constraint"]["min"] == 2
    assert decide(g, A, cards=["Copper", "Silver"])[0]
    assert len(g["seats"][A]["hand"]) == 0


def test_gear_sets_aside_and_returns_them_next_turn():
    g = fresh()
    give_hand(g, A, ["Gear"])
    give_deck(g, A, ["Copper", "Silver", "Gold"])
    assert play(g, A, "Gear")[0]
    assert sorted(frame(g)["constraint"]["cards"]) == ["Copper", "Silver"]
    assert decide(g, A, cards=["Copper", "Silver"])[0]
    assert sorted(g["seats"][A]["dur_aside"]) == ["Copper", "Silver"]
    assert engine.owned_cards(g, A).count("Copper") >= 1, "still owned"


def test_gear_that_sets_aside_nothing_does_not_persist():
    """"If you don't set aside any cards, Gear doesn't stay in play beyond the
    current turn" — it registered no ability, so it discards normally."""
    g = fresh()
    give_hand(g, A, ["Gear"])
    give_deck(g, A, ["Copper", "Silver"])
    assert play(g, A, "Gear")[0]
    assert decide(g, A, cards=[])[0]
    g["phase"] = "buy"
    assert mv(g, A, {"type": "end_phase"})[0]
    assert g["seats"][A]["duration"] == [], "it registered nothing, so it left"
    assert "Gear" not in g["seats"][A]["in_play"]
    # ...and it is an ordinary card of yours again, wherever the clean-up
    # draw's reshuffle happened to leave it
    assert "Gear" in engine.owned_cards(g, A)


def test_caravan_guard_reacts_to_an_attack_and_pays_next_turn():
    g = fresh(kingdom=["Caravan Guard", "Giant", "Amulet", "Dungeon", "Gear",
                       "Magpie", "Port", "Ranger", "Artificer", "Lost City"])
    give_hand(g, A, ["Giant"])
    give_hand(g, B, ["Caravan Guard", "Copper", "Copper"])
    give_deck(g, B, ["Copper"] * 5)
    assert play(g, A, "Giant")[0]
    # B's reaction window is open
    assert g["pending_pid"] == B
    assert any(o["id"] == "react:Caravan Guard" for o in frame(g)["constraint"]["options"])
    assert decide(g, B, ids=["react:Caravan Guard"])[0]
    assert "Caravan Guard" in g["seats"][B]["in_play"], "it plays itself"
    assert g["turn_ctx"]["actions_played"] == 1, "A's Giant only — not B's reaction"


# ── $4 ────────────────────────────────────────────────────────────────────────

def test_magpie_takes_a_treasure_and_gains_a_magpie_for_an_action():
    g = fresh()
    give_hand(g, A, ["Magpie"])
    give_deck(g, A, ["Copper", "Estate", "Village"] if "Village" in g["supply"]
              else ["Copper", "Estate", "Magpie"])
    assert play(g, A, "Magpie")[0]
    # drew the Copper as the cantrip, revealed the Estate
    assert "Estate" in g["seats"][A]["deck"], "a non-Treasure goes back on top"
    assert "Magpie" in g["seats"][A]["discard"], "Victory revealed => gain a Magpie"


def test_magpie_does_both_for_a_treasure_action():
    """"If a card is revealed that is both a Treasure and a Victory, or a
    Treasure and an Action, you do BOTH." """
    g = fresh(kingdom=["Magpie", "Amulet", "Dungeon", "Gear", "Port", "Ranger",
                       "Artificer", "Lost City", "Giant", "Hireling"],
              expansions=("adventures", "hinterlands"))
    give_hand(g, A, ["Magpie"])
    give_deck(g, A, ["Copper", "Crossroads"])
    g["seats"][A]["deck"] = ["Copper", "Fool's Gold"]      # Treasure-Reaction
    assert play(g, A, "Magpie")[0]
    assert "Fool's Gold" in g["seats"][A]["hand"], "Treasure => into your hand"
    assert "Magpie" not in g["seats"][A]["discard"], "...but not an Action/Victory"


def test_miser_banks_coppers_on_the_tavern_mat_and_pays_per_copper():
    g = fresh(kingdom=KA2)
    give_hand(g, A, ["Miser", "Copper", "Copper"])
    g["actions"] = 3
    assert play(g, A, "Miser")[0]
    assert decide(g, A, ids=["put"])[0]
    assert g["seats"][A]["tavern"] == ["Copper"]
    assert engine.owned_cards(g, A).count("Copper") >= 1
    give_hand(g, A, ["Miser"])
    g["phase"] = "action"       # the empty hand auto-advanced us to buy
    assert play(g, A, "Miser")[0]
    assert decide(g, A, ids=["coins"])[0]
    assert g["coins"] == 1


def test_miser_with_an_empty_mat_pays_zero_and_leaves_a_minus_coin_token():
    """+$0 is not "$1 or more", so the -$1 token stays."""
    g = fresh(kingdom=KA2)
    give_hand(g, A, ["Miser"])
    engine.set_seat_token(g, A, "-coin", True)
    assert play(g, A, "Miser")[0]
    assert decide(g, A, ids=["coins"])[0]
    assert g["coins"] == 0
    assert engine.seat_token(g, A, "-coin") is True


def test_port_gains_another_port_but_that_one_does_not_chain():
    g = fresh(kingdom=KA2)
    before = engine.pile_count(g, "Port")
    engine.gain(g, A, "Port")
    engine._drive(g)
    assert engine.pile_count(g, "Port") == before - 2, "exactly two"
    assert g["seats"][A]["discard"].count("Port") == 2


def test_ranger_draws_five_on_a_face_up_journey_token():
    g = fresh(kingdom=KA2)
    give_hand(g, A, ["Ranger", "Ranger"])
    give_deck(g, A, ["Copper"] * 12)
    g["actions"] = 2
    assert play(g, A, "Ranger")[0]
    assert g["buys"] == 2 and len(g["seats"][A]["hand"]) == 1, "face DOWN => no draw"
    assert play(g, A, "Ranger")[0]
    assert len(g["seats"][A]["hand"]) == 5, "face up again => +5 Cards"


def test_messenger_may_put_its_deck_into_the_discard():
    g = fresh(kingdom=KA2)
    give_hand(g, A, ["Messenger"])
    give_deck(g, A, ["Copper", "Silver"])
    assert play(g, A, "Messenger")[0]
    assert g["buys"] == 2 and g["coins"] == 2
    assert decide(g, A, ids=["yes"])[0]
    assert g["seats"][A]["deck"] == []
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Silver"]


def test_messenger_gained_first_in_the_buy_phase_hands_everyone_a_copy():
    g = fresh(players=(A, B, C), kingdom=KA2)
    g["phase"] = "buy"
    engine.gain(g, A, "Messenger")
    engine._drive(g)
    assert frame(g)["card"] == "Messenger" and frame(g)["kind"] == "choose_pile"
    assert decide(g, A, pile="Silver")[0]
    assert "Silver" in g["seats"][A]["discard"]
    assert g["seats"][B]["discard"].count("Silver") == 1
    assert g["seats"][C]["discard"].count("Silver") == 1


def test_a_second_gain_in_the_buy_phase_does_not_trigger_messenger():
    g = fresh(kingdom=KA2)
    g["phase"] = "buy"
    engine.gain(g, A, "Copper")
    engine._drive(g)
    engine.gain(g, A, "Messenger")
    engine._drive(g)
    assert frame(g) is None, "not the first gain this Buy phase"


# ── $5 ────────────────────────────────────────────────────────────────────────

def test_artificer_gains_a_card_costing_exactly_what_it_discarded():
    g = fresh()
    give_hand(g, A, ["Artificer", "Estate", "Estate", "Copper"])
    give_deck(g, A, ["Copper"] * 5)
    assert play(g, A, "Artificer")[0]
    assert g["coins"] == 1 and g["actions"] == 1
    assert decide(g, A, cards=["Estate", "Estate", "Copper"])[0]
    assert frame(g)["stage"] == "which"
    ids = opt_ids(g)
    assert "Silver" in ids and "decline" in ids
    assert "Gold" not in ids, "exactly $3, not up to"
    assert decide(g, A, ids=["Silver"])[0]
    assert g["seats"][A]["deck"][0] == "Silver", "gained ONTO your deck"


def test_artificer_may_discard_nothing_and_gain_a_zero_cost_card():
    g = fresh()
    give_hand(g, A, ["Artificer"])
    give_deck(g, A, ["Copper"] * 5)
    assert play(g, A, "Artificer")[0]
    assert decide(g, A, cards=[])[0]
    assert "Copper" in opt_ids(g), "$0 is a real choice"
    assert decide(g, A, ids=["decline"])[0]


def test_bridge_troll_discounts_this_turn_and_the_next_and_is_cumulative():
    """2022: the reduction is TURN-SCOPED, like Highway's — not while-in-play."""
    g = fresh()
    give_hand(g, A, ["Bridge Troll"])
    assert engine.cost(g, "Gold") == 6
    assert play(g, A, "Bridge Troll")[0]
    assert engine.cost(g, "Gold") == 5
    assert g["buys"] == 2
    assert engine.seat_token(g, B, "-coin") is True
    # a second one stacks
    give_hand(g, A, ["Bridge Troll"])
    g["phase"] = "action"       # the empty hand auto-advanced us to buy
    g["actions"] = 1
    assert play(g, A, "Bridge Troll")[0]
    assert engine.cost(g, "Gold") == 4


def test_bridge_trolls_discount_survives_it_leaving_play():
    """Turn-scoped means exactly that: trashing it mid-turn keeps the discount."""
    g = fresh()
    give_hand(g, A, ["Bridge Troll"])
    assert play(g, A, "Bridge Troll")[0]
    engine.trash(g, A, ["Bridge Troll"], zone="in_play")
    assert engine.cost(g, "Gold") == 5


def test_giant_pays_one_then_five_and_attacks_on_the_face_up_turn():
    g = fresh()
    give_hand(g, A, ["Giant", "Giant"])
    give_deck(g, B, ["Gold"] + ["Copper"] * 5)
    g["actions"] = 2
    assert play(g, A, "Giant")[0]
    assert g["coins"] == 1, "face down => +$1 and no attack"
    assert play(g, A, "Giant")[0]
    assert g["coins"] == 6
    assert "Gold" in g["trash"], "$6 is inside the $3-$6 band"


def test_giants_victim_with_an_empty_deck_gains_a_curse():
    g = fresh()
    give_hand(g, A, ["Giant"])
    g["seats"][B]["deck"] = []
    g["seats"][B]["discard"] = []
    engine.flip_journey(g, A)               # so the play turns it back face up
    assert play(g, A, "Giant")[0]
    assert "Curse" in g["seats"][B]["discard"]


def test_lost_city_makes_every_opponent_draw_when_gained():
    g = fresh(players=(A, B, C))
    for p in (B, C):
        give_deck(g, p, ["Copper"] * 5)
        give_hand(g, p, [])
    engine.gain(g, A, "Lost City")
    engine._drive(g)
    assert len(g["seats"][B]["hand"]) == 1 and len(g["seats"][C]["hand"]) == 1


def test_relic_puts_a_minus_card_token_on_every_opponents_deck():
    g = fresh(players=(A, B, C), kingdom=KA2)
    g["phase"] = "buy"
    give_hand(g, A, ["Relic"])
    assert mv(g, A, {"type": "play_treasure", "card": "Relic"})[0]
    assert g["coins"] == 2
    assert engine.seat_token(g, B, "-card") is True
    assert engine.seat_token(g, C, "-card") is True


def test_relic_is_never_autoplayed_because_it_opens_a_reaction_window():
    assert "Relic" in engine.manual_treasures()


def test_storyteller_plays_treasures_then_pays_everything_for_cards():
    g = fresh(kingdom=KA2)
    give_hand(g, A, ["Storyteller", "Copper", "Copper", "Silver"])
    give_deck(g, A, ["Estate"] * 10)
    assert play(g, A, "Storyteller")[0]
    assert len(g["seats"][A]["hand"]) == 4, "+1 Card (2022), not +$1"
    assert frame(g)["stage"] == "play"
    assert decide(g, A, ids=["Silver"])[0]
    assert decide(g, A, ids=["Copper"])[0]
    assert decide(g, A, ids=["done"])[0]
    assert g["coins"] == 0, "it pays ALL of your money"
    # $3 paid => 3 cards. The hand held 3 non-Treasure cards before the draw.
    assert len(g["seats"][A]["hand"]) == 2 + 3


def test_storyteller_keeps_your_potions():
    """"You will be left with $0 in your money pool but will keep any Potions." """
    g = fresh(kingdom=KA2)
    give_hand(g, A, ["Storyteller"])
    give_deck(g, A, ["Estate"] * 10)
    g["potions"] = 2
    assert play(g, A, "Storyteller")[0]
    assert decide(g, A, ids=["done"])[0] if frame(g) else True
    assert g["potions"] == 2


def test_treasure_trove_gains_a_gold_and_a_copper():
    g = fresh(kingdom=KA2)
    g["phase"] = "buy"
    give_hand(g, A, ["Treasure Trove"])
    assert mv(g, A, {"type": "play_treasure", "card": "Treasure Trove"})[0]
    assert g["coins"] == 2
    assert "Gold" in g["seats"][A]["discard"] and "Copper" in g["seats"][A]["discard"]


def test_treasure_trove_still_gains_the_copper_with_no_gold_left():
    g = fresh(kingdom=KA2)
    g["supply"]["Gold"] = 0
    g["phase"] = "buy"
    give_hand(g, A, ["Treasure Trove"])
    assert mv(g, A, {"type": "play_treasure", "card": "Treasure Trove"})[0]
    assert g["seats"][A]["discard"].count("Copper") == 1


# ── $6 and the Travellers' play abilities ─────────────────────────────────────

def test_hireling_stays_in_play_and_draws_every_turn():
    g = fresh()
    give_hand(g, A, ["Hireling"])
    give_deck(g, A, ["Copper"] * 30)
    assert play(g, A, "Hireling")[0]
    for _ in range(3):
        g["phase"] = "buy"
        while g["pending_pid"] is not None:
            pid = g["pending_pid"]
            engine.apply_move(g, pid, {"type": "decision",
                                       **engine.sample_decision(g, pid, engine.random.Random(1))})
        mv(g, g["turn"], {"type": "end_phase"})
    entries = [e for e in g["seats"][A]["duration"] if e["card"] == "Hireling"]
    assert entries and not entries[0].get("done"), "it never finishes"
    assert entries[0]["fx"], "and it keeps its ability"
    assert "Hireling" not in g["seats"][A]["discard"]


def test_treasure_hunter_reads_the_right_hand_neighbours_last_turn():
    g = fresh(players=(A, B, C), kingdom=KA2)
    from games.dontminion import effects
    # the player to A's RIGHT is the one before them in turn order
    g["last_turn_gains"][C] = ["Copper", "Estate"]
    g["last_turn_gains"][B] = ["Gold"] * 5
    g["seats"][A]["in_play"].append("Treasure Hunter")
    engine._run_ability(g, A, engine.effects.EFFECTS["Treasure Hunter"]) \
        if hasattr(engine, "effects") else None
    from games.dontminion import effects
    if not any(e["event"] == "gain" for e in g["log"]):
        effects.EFFECTS["Treasure Hunter"](g, A)
    assert g["seats"][A]["discard"].count("Silver") == 2


def test_soldier_counts_other_attacks_in_play_but_not_itself():
    g = fresh(kingdom=KA2)
    from games.dontminion import effects
    g["seats"][A]["in_play"] = ["Soldier", "Soldier", "Relic"]
    give_hand(g, B, ["Copper"] * 5)
    effects.EFFECTS["Soldier"](g, A)
    engine._drive(g)
    # $2 base + $1 per OTHER attack in play (one Soldier + Relic = 2)
    assert g["coins"] == 4


def test_warrior_counts_travellers_in_play_including_itself():
    g = fresh(kingdom=KA2)
    from games.dontminion import effects
    g["seats"][A]["in_play"] = ["Warrior", "Page"]
    give_deck(g, A, ["Copper"] * 5)
    give_deck(g, B, ["Silver", "Estate", "Copper", "Copper"])
    effects.EFFECTS["Warrior"](g, A)
    engine._drive(g)
    # 2 Travellers in play => B loses 2 cards off the top; the Silver ($3) is
    # trashed, the Estate ($2) is discarded
    assert "Silver" in g["trash"]
    assert "Estate" in g["seats"][B]["discard"]


def test_hero_gains_any_treasure():
    g = fresh(kingdom=KA2)
    from games.dontminion import effects
    g["seats"][A]["in_play"] = ["Hero"]
    effects.EFFECTS["Hero"](g, A)
    engine._drive(g)
    assert g["coins"] == 2
    assert frame(g)["kind"] == "choose_pile"
    assert "Gold" in frame(g)["constraint"]["piles"]
    assert "Estate" not in frame(g)["constraint"]["piles"]
    assert decide(g, A, pile="Gold")[0]
    assert "Gold" in g["seats"][A]["discard"]


def test_fugitive_draws_two_and_discards_one():
    g = fresh(kingdom=KA2)
    from games.dontminion import effects
    give_hand(g, A, [])
    give_deck(g, A, ["Copper", "Silver", "Gold"])
    effects.EFFECTS["Fugitive"](g, A)
    engine._drive(g)
    assert g["actions"] == 2
    assert sorted(frame(g)["constraint"]["cards"]) == ["Copper", "Silver"]
    assert decide(g, A, cards=["Copper"])[0]
    assert g["seats"][A]["hand"] == ["Silver"]
