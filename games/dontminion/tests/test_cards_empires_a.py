"""Empires, half A — the setup, the 24 piles' own play abilities, and the six
kernel additions this set needed.

Positions are arranged by mutating the game dict (the repo's board-fixture
idiom); give_hand breaks card conservation, so nothing here asserts the census
— test_soak owns that, except where a test is explicitly about a card leaving
the players' hands (Encampment), which builds its baseline after staging.

Headline rulings pinned here:
  * **A PILE'S TYPE AND COST FOLLOW ITS RANDOMIZER, NOT ITS FACE.**
    Catapult/Rocks is an Action pile even while the Rocks (a Treasure) show —
    "you can put your +$1 token on the Catapult/Rocks pile, and then get +$1
    when you play a Catapult OR A ROCKS". Buying still reads the face.
  * **Enchantress REPLACES the play** (the ph.-8 would-resolve window):
    reactions resolve first, before-play abilities resolve first, and only then
    is the card's own ability cancelled. Two Enchantresses do not stack.
  * **Villa walks the phase backwards**, keeps the Actions/Buys/$ you had, and
    restarts the treasure half of the Buy phase — but does nothing off-turn.
  * **Archive is a repeat that ENDS**, and two Archives keep SEPARATE SETS.
  * **Encampment goes back to its PILE**, not to the discard, and does so in
    the Clean-up of whoever's turn it was played on.
  * **Farmers' Market, Temple and Gladiator name the SUPPLY pile** (2021/2025),
    which matters because all three are Ferryman-pile eligible.
  * **Chariot Race DRAWS its card (2025)**, so the -1 Card token denies the
    bonuses outright.
"""

import pytest

from games.dontminion import cards, effects, engine

A, B, C = "alice", "bob", "carol"

# a 10-pile Empires board that carries one of everything structural: an
# ordinary card, three split piles, Castles, and two Debt-costed Actions
KE = ["Engineer", "City Quarter", "Chariot Race", "Enchantress",
      "Farmers' Market", "Sacrifice", "Temple", "Villa", "Archive", "Capital"]
KE2 = ["Charm", "Crown", "Forum", "Groundskeeper", "Legionary", "Wild Hunt",
       "Overlord", "Royal Blacksmith", "Castles", "Catapult/Rocks"]
KSPLIT = ["Encampment/Plunder", "Patrician/Emporium", "Settlers/Bustling Village",
          "Catapult/Rocks", "Gladiator/Fortune", "Castles",
          "Engineer", "Villa", "Temple", "Forum"]


def fresh(players=(A, B), seed=7, kingdom=tuple(KE), expansions=("empires",),
          landscapes=()):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom), landscapes=list(landscapes))


def give_hand(g, pid, cards_):
    g["seats"][pid]["hand"] = list(cards_)


def give_deck(g, pid, cards_):
    g["seats"][pid]["deck"] = list(cards_)


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


def gain(g, pid, pile, **kw):
    """A gain called outside apply_move parks its when-gain pool as an auto
    frame; nothing drives it until the next move, so drive it here."""
    out = engine.gain(g, pid, pile, **kw)
    engine._drive(g)
    return out


def trash(g, pid, cards_, zone="hand"):
    """As with `gain`: a trash outside apply_move parks its pool."""
    engine.trash(g, pid, list(cards_), zone=zone)
    engine._drive(g)


def drain(g, pile, n):
    """Take n cards off an ordered pile the way the game does — through
    _pile_take, so the pile's FACE follows. Rewriting `contents` by hand leaves
    the face on the card that was showing, which is the whole thing under
    test."""
    for _ in range(n):
        engine._pile_take(g, pile)


def _only(g, pid, owned):
    """Make `owned` the player's ENTIRE deck — the starting Estates otherwise
    score alongside whatever the test is measuring."""
    for zone in ("deck", "hand", "discard", "in_play", "aside"):
        g["seats"][pid][zone] = []
    g["seats"][pid]["discard"] = list(owned)


def end_turn(g, pid):
    """End pid's turn from whatever phase they are in."""
    if g["phase"] == "action":
        mv(g, pid, {"type": "end_phase"})
    mv(g, pid, {"type": "end_phase"})


def hand_off(g, pid, hand, deck=()):
    """End the current turn and stage the next player an ACTION phase with the
    given hand. The auto-advance flips a dealt hand with no Action card
    straight to the Buy phase, so a staged hand has to put the phase back."""
    end_turn(g, g["turn"])
    assert g["turn"] == pid
    g["seats"][pid]["hand"] = list(hand)
    if deck:
        g["seats"][pid]["deck"] = list(deck)
    g["phase"] = "action"
    g["actions"] = 1


# ── setup: split piles, Castles, and pile identity ───────────────────────────

def test_a_split_pile_is_five_of_the_cheap_half_on_top_of_five_of_the_dear():
    g = fresh(kingdom=KSPLIT)
    for name, (cheap, dear) in cards.EMPIRES_SPLITS.items():
        pile = g["piles"][name]
        assert pile["contents"] == [cheap] * 5 + [dear] * 5, name
        assert engine.pile_count(g, name) == 10, name
        assert engine.pile_top(g, name) == cheap, name


def test_the_castles_pile_is_one_of_each_at_two_players_and_two_of_each_above():
    two = fresh(players=(A, B), kingdom=KSPLIT)
    assert two["piles"]["Castles"]["contents"] == cards.CASTLES
    three = engine.new_game([A, B, C], ["empires"], seed=4,
                            kingdom=list(KSPLIT), landscapes=[])
    want = [c for c in cards.CASTLES for _ in range(2)]
    assert three["piles"]["Castles"]["contents"] == want
    # ...sorted by cost with the cheapest on top, which is what makes the
    # $3 Humble Castle the first thing anyone can buy from it
    costs = [cards.CARDS[c]["cost"] for c in cards.CASTLES]
    assert costs == sorted(costs)


def test_a_split_piles_type_follows_the_randomizer_not_the_face():
    """THE ph.-8 pile rule. Three of the five splits show a Treasure once the
    bottom half surfaces, and the pile stays an Action pile throughout."""
    g = fresh(kingdom=KSPLIT)
    for name in ("Catapult/Rocks", "Encampment/Plunder", "Gladiator/Fortune"):
        assert engine.pile_has_type(g, name, "action"), name
        drain(g, name, 5)           # the cheap half is gone; the dear half shows
        assert engine.has_type(g, name, "treasure"), f"{name} face is a Treasure"
        assert engine.pile_has_type(g, name, "action"), \
            f"{name} is STILL an Action pile — the randomizer decides"
        assert not engine.pile_has_type(g, name, "treasure"), name


def test_buying_a_split_pile_reads_the_FACE_not_the_randomizer():
    """The other half of the same rule: the pile's own cost/type is for setup
    rules and tokens, never for the purchase. A Fortune on top costs {$8,8D}
    even though its pile's randomizer says $3."""
    g = fresh(kingdom=KSPLIT)
    assert engine.cost(g, "Gladiator/Fortune") == 3
    drain(g, "Gladiator/Fortune", 5)
    assert engine.cost(g, "Gladiator/Fortune") == 8
    assert engine.debt_cost(g, "Gladiator/Fortune") == 8
    assert cards.PILES["Gladiator/Fortune"]["cost"] == 3


def test_an_adventures_token_may_be_moved_to_a_split_pile_showing_a_treasure():
    """"You can put your +$1 token on the Catapult/Rocks pile, and then get +$1
    when you play a Catapult OR A ROCKS." The token event enumerates Action
    Supply piles, so this is the pile-identity rule reaching a real card."""
    g = engine.new_game([A, B], ["empires", "adventures"], seed=3,
                        kingdom=KSPLIT[:9] + ["Amulet"], landscapes=["Training"])
    drain(g, "Catapult/Rocks", 5)
    coins(g, 6)
    assert mv(g, A, {"type": "buy_landscape", "name": "Training"})[0]
    assert "Catapult/Rocks" in frame(g)["constraint"]["piles"]


def test_the_knights_pile_also_answers_from_its_randomizer():
    """Not an Empires card, but the same reader — Knights has had a face that
    changes since ph. 6 and was answering from its top card until now."""
    g = engine.new_game([A, B], ["darkages"], seed=5,
                        kingdom=["Knights"] + sorted(cards.KINGDOM["darkages"])[:9])
    assert engine.pile_has_type(g, "Knights", "action")
    assert engine.pile_has_type(g, "Knights", "knight")


# ── the DEBT-costed cards ────────────────────────────────────────────────────

def test_the_four_debt_actions_print_no_coin_cost_at_all():
    g = fresh(kingdom=KE2)
    for name, debt in (("Overlord", 8), ("Royal Blacksmith", 8)):
        assert engine.cost(g, name) == 0, name
        assert engine.debt_cost(g, name) == debt, name
    g2 = fresh()
    assert engine.cost(g2, "Engineer") == 0
    assert engine.debt_cost(g2, "Engineer") == 4
    assert engine.cost(g2, "City Quarter") == 0
    assert engine.debt_cost(g2, "City Quarter") == 8


def test_buying_a_debt_card_with_no_money_takes_the_debt_and_locks_the_buy():
    g = fresh()
    coins(g, 0)
    assert mv(g, A, {"type": "buy", "card": "Engineer"})[0]
    assert g["debt"][A] == 4
    assert "Engineer" in g["seats"][A]["discard"]
    # "when you have Debt tokens, you can't buy anything"
    g["buys"] = 1
    g["coins"] = 8
    ok, err = mv(g, A, {"type": "buy", "card": "Silver"})
    assert not ok and "Debt" in err


def test_gaining_a_debt_card_without_buying_it_gives_no_debt():
    g = fresh()
    gain(g, A, "City Quarter")
    assert g["debt"][A] == 0


# ── the four Debt-costed Actions ─────────────────────────────────────────────

def test_engineer_gains_then_offers_to_trash_itself_for_a_second_gain():
    g = fresh()
    give_hand(g, A, ["Engineer"])
    assert play(g, A, "Engineer")[0]
    assert frame(g)["kind"] == "choose_pile"
    assert decide(g, A, pile="Silver")[0]
    assert opt_ids(g) == ["yes", "no"]
    assert decide(g, A, ids=["yes"])[0]
    assert "Engineer" in g["trash"]
    assert decide(g, A, pile="Estate")[0]
    assert sorted(g["seats"][A]["discard"]) == ["Estate", "Silver"]


def test_engineer_kept_is_not_trashed_and_gains_only_once():
    g = fresh()
    give_hand(g, A, ["Engineer"])
    play(g, A, "Engineer")
    decide(g, A, pile="Silver")
    decide(g, A, ids=["no"])
    assert "Engineer" not in g["trash"]
    assert g["seats"][A]["discard"] == ["Silver"]
    assert not g["pending"]


def test_city_quarter_draws_one_per_action_revealed():
    g = fresh()
    give_hand(g, A, ["City Quarter", "Village", "Village", "Copper"])
    give_deck(g, A, ["Gold"] * 5)
    g["seats"][A]["hand"] = ["City Quarter", "Chariot Race", "Sacrifice", "Copper"]
    assert play(g, A, "City Quarter")[0]
    assert g["actions"] == 2 + 0            # 1 - 1 spent + 2
    # two Actions left in hand after the City Quarter left it
    assert g["seats"][A]["hand"].count("Gold") == 2


def test_royal_blacksmith_draws_five_then_discards_every_copper():
    g = fresh(kingdom=KE2)
    give_hand(g, A, ["Royal Blacksmith", "Copper"])
    give_deck(g, A, ["Copper", "Estate", "Copper", "Silver", "Gold"])
    assert play(g, A, "Royal Blacksmith")[0]
    hand = g["seats"][A]["hand"]
    assert "Copper" not in hand
    assert sorted(hand) == ["Estate", "Gold", "Silver"]
    assert g["seats"][A]["discard"].count("Copper") == 3


def test_overlord_plays_a_supply_action_leaving_it_there():
    g = fresh(kingdom=KE2)
    give_hand(g, A, ["Overlord"])
    assert play(g, A, "Overlord")[0]
    piles = frame(g)["constraint"]["piles"]
    assert "Forum" in piles
    # a Command may not play another Command, nor a Duration (2025)
    assert "Overlord" not in piles
    before = engine.pile_count(g, "Forum")
    assert decide(g, A, pile="Forum")[0]
    assert engine.pile_count(g, "Forum") == before, "left in the Supply"
    assert "Forum" not in g["seats"][A]["in_play"]


# ── $3 ───────────────────────────────────────────────────────────────────────

def test_chariot_race_draws_its_card_and_scores_when_it_costs_more():
    g = fresh()
    give_hand(g, A, ["Chariot Race"])
    give_deck(g, A, ["Gold"])
    give_deck(g, B, ["Copper"])
    assert play(g, A, "Chariot Race")[0]
    assert "Gold" in g["seats"][A]["hand"], "2025: it DRAWS the card"
    assert g["coins"] == 1
    assert g["vp_tokens"][A] == 1
    assert g["seats"][B]["deck"] == ["Copper"], "their reveal goes back on top"


def test_chariot_race_scores_nothing_on_a_tie_or_a_loss():
    g = fresh()
    give_hand(g, A, ["Chariot Race"])
    give_deck(g, A, ["Copper"])
    give_deck(g, B, ["Copper"])
    play(g, A, "Chariot Race")
    assert g["coins"] == 0 and g["vp_tokens"][A] == 0


def test_the_minus_one_card_token_denies_chariot_race_its_bonuses():
    """2025: "if Way of the Chameleon or your -1 Card token prevents you from
    DRAWING with Chariot Race, you don't get the bonuses" — which only became
    true when the card stopped revealing and started drawing."""
    g = engine.new_game([A, B], ["empires", "adventures"], seed=6,
                        kingdom=KE[:9] + ["Amulet"], landscapes=[])
    give_hand(g, A, ["Chariot Race"])
    give_deck(g, A, ["Gold"])
    give_deck(g, B, ["Copper"])
    engine.set_seat_token(g, A, "-card", True)
    play(g, A, "Chariot Race")
    assert g["coins"] == 0 and g["vp_tokens"][A] == 0


def test_farmers_market_climbs_to_four_then_cashes_out_and_trashes_itself():
    g = fresh()
    for want in (1, 2, 3, 4):
        g["coins"] = 0
        give_hand(g, A, ["Farmers' Market"])
        g["actions"] = 1
        g["phase"] = "action"
        assert play(g, A, "Farmers' Market")[0]
        assert g["coins"] == want, want
        assert engine.pile_vp(g, "Farmers' Market") == want
    g["coins"] = 0
    give_hand(g, A, ["Farmers' Market"])
    g["actions"] = 1
    g["phase"] = "action"
    play(g, A, "Farmers' Market")
    assert g["coins"] == 0, "the fifth play takes the tokens and gives no $"
    assert g["vp_tokens"][A] == 4
    assert engine.pile_vp(g, "Farmers' Market") == 0
    assert "Farmers' Market" in g["trash"]


def test_farmers_market_gathers_on_the_SUPPLY_pile_only():
    """2021 gave it the word SUPPLY, and it earns its keep: Farmers' Market
    costs $3, so it can be drawn as FERRYMAN's extra pile — in the game and
    outside the Supply, with no Supply pile to gather onto."""
    g = fresh()
    del g["supply"]["Farmers' Market"]
    g["nonsupply"]["Farmers' Market"] = 10
    g["piles"]["Farmers' Market"]["supply"] = False
    give_hand(g, A, ["Farmers' Market"])
    assert play(g, A, "Farmers' Market")[0]
    assert g["buys"] == 2, "the +1 Buy still happens"
    assert engine.pile_vp(g, "Farmers' Market") == 0
    assert g["coins"] == 0


# ── Enchantress: the would-resolve window ────────────────────────────────────

def _enchantress_board(seed=9):
    g = fresh(kingdom=KE)
    give_hand(g, A, ["Enchantress"])
    assert play(g, A, "Enchantress")[0]
    while g["pending"]:
        pid = g["pending_pid"]
        mv(g, pid, engine.sample_decision(g, pid, engine.random.Random(1)))
    return g


def test_enchantress_replaces_the_first_action_an_opponent_plays():
    g = _enchantress_board()
    hand_off(g, B, ["Sacrifice", "Sacrifice"], ["Gold"] * 4)
    before_trash = list(g["trash"])
    assert play(g, B, "Sacrifice")[0]
    assert not g["pending"], "Sacrifice's own trash prompt never opened"
    assert g["trash"] == before_trash
    assert "Gold" in g["seats"][B]["hand"], "+1 Card instead"
    assert g["actions"] == 1, "1 - 1 spent + 1 from Enchantress"
    assert "Sacrifice" in g["seats"][B]["in_play"], "it was still PLAYED"


def test_enchantress_affects_only_the_first_action_of_the_turn():
    g = _enchantress_board()
    hand_off(g, B, ["Sacrifice", "Sacrifice"], ["Gold"] * 6)
    play(g, B, "Sacrifice")
    g["actions"] = 1
    assert play(g, B, "Sacrifice")[0]
    assert frame(g)["kind"] == "choose_cards", "the SECOND one resolves normally"


def test_two_enchantresses_do_not_stack():
    """"The first Enchantress replaces what the players do, and Enchantresses
    after that can't replace it again." """
    g = fresh()
    give_hand(g, A, ["Enchantress", "Enchantress"])
    g["actions"] = 2
    play(g, A, "Enchantress")
    play(g, A, "Enchantress")
    while g["pending"]:
        pid = g["pending_pid"]
        mv(g, pid, engine.sample_decision(g, pid, engine.random.Random(1)))
    hand_off(g, B, ["Sacrifice"], ["Gold"] * 4)
    play(g, B, "Sacrifice")
    assert g["seats"][B]["hand"].count("Gold") == 1, "+1 Card, not +2"
    assert g["actions"] == 1


def test_enchantress_does_not_affect_its_own_owner():
    g = _enchantress_board()
    g["actions"] = 1
    g["phase"] = "action"
    g["seats"][A]["hand"] = ["Sacrifice", "Copper"]
    assert play(g, A, "Sacrifice")[0]
    assert frame(g)["kind"] == "choose_cards", "the owner resolves normally"


def test_a_moat_reveal_makes_a_player_immune_to_enchantress():
    g = engine.new_game([A, B], ["empires", "base"], seed=8,
                        kingdom=KE[:9] + ["Moat"], landscapes=[])
    give_hand(g, A, ["Enchantress"])
    give_hand(g, B, ["Moat"])
    play(g, A, "Enchantress")
    # B is offered the reaction window and reveals the Moat
    assert g["pending_pid"] == B
    reveal_id = [o["id"] for o in frame(g)["constraint"]["options"]
                 if "Moat" in o["id"]][0]
    assert decide(g, B, ids=[reveal_id])[0]
    while g["pending"]:
        pid = g["pending_pid"]
        mv(g, pid, engine.sample_decision(g, pid, engine.random.Random(1)))
    hand_off(g, B, ["Sacrifice", "Copper"], ["Gold"] * 4)
    play(g, B, "Sacrifice")
    assert frame(g)["kind"] == "choose_cards", "immune: the play resolves"


def test_cancel_pending_play_returns_false_with_nothing_parked():
    g = fresh()
    assert engine.cancel_pending_play(g) is False


# ── $4 ───────────────────────────────────────────────────────────────────────

def test_sacrifice_pays_every_type_the_trashed_card_has():
    g = fresh()
    give_hand(g, A, ["Sacrifice", "Humble Castle"])
    give_deck(g, A, ["Gold"] * 4)
    play(g, A, "Sacrifice")
    assert decide(g, A, cards=["Humble Castle"])[0]
    # Humble Castle is a Treasure AND a Victory card
    assert g["coins"] == 2
    assert g["vp_tokens"][A] == 2
    assert g["seats"][A]["hand"].count("Gold") == 0, "not an Action, no draw"


def test_sacrifice_on_an_action_gives_two_cards_and_two_actions():
    g = fresh()
    give_hand(g, A, ["Sacrifice", "Village"])
    g["seats"][A]["hand"] = ["Sacrifice", "Forum"]
    give_deck(g, A, ["Gold"] * 4)
    play(g, A, "Sacrifice")
    decide(g, A, cards=["Forum"])
    assert g["seats"][A]["hand"].count("Gold") == 2
    assert g["actions"] == 2


def test_temple_offers_one_of_each_NAME_and_gathers_on_its_pile():
    g = fresh()
    give_hand(g, A, ["Temple", "Copper", "Copper", "Estate"])
    play(g, A, "Temple")
    assert g["vp_tokens"][A] == 1
    assert sorted(frame(g)["constraint"]["cards"]) == ["Copper", "Estate"]
    assert frame(g)["constraint"]["max"] == 2
    assert decide(g, A, cards=["Copper", "Estate"])[0]
    assert engine.pile_vp(g, "Temple") == 1


def test_gaining_a_temple_takes_the_tokens_off_its_pile():
    g = fresh()
    engine.add_pile_vp(g, "Temple", 3)
    gain(g, A, "Temple")
    assert g["vp_tokens"][A] == 3
    assert engine.pile_vp(g, "Temple") == 0


def test_villa_returns_you_to_your_action_phase_and_restarts_the_treasures():
    g = fresh()
    coins(g, 4)
    g["turn_ctx"]["bought"] = False
    assert mv(g, A, {"type": "buy", "card": "Villa"})[0]
    assert g["phase"] == "action", "back to the Action phase"
    assert "Villa" in g["seats"][A]["hand"], "and into your hand"
    assert g["actions"] == 2, "the default 1 plus Villa's +1"
    assert g["turn_ctx"]["bought"] is False, "the treasure half restarts"


def test_villa_gained_off_turn_gives_no_action_phase():
    """"If you gain Villa when it's not your turn, the +1 Action is not usable,
    and you don't get an Action phase." """
    g = fresh()
    g["phase"] = "buy"
    gain(g, B, "Villa")
    assert g["phase"] == "buy"
    assert g["turn"] == A


def test_villa_gained_in_the_action_phase_only_goes_to_hand():
    g = fresh()
    assert g["phase"] == "action"
    gain(g, A, "Villa")
    assert "Villa" in g["seats"][A]["hand"]
    assert g["phase"] == "action"


# ── $5 ───────────────────────────────────────────────────────────────────────

def test_archive_hands_out_one_card_a_turn_for_three_turns_then_leaves():
    g = fresh()
    give_hand(g, A, ["Archive"])
    give_deck(g, A, ["Gold", "Silver", "Estate"] + ["Copper"] * 6)
    assert play(g, A, "Archive")[0]
    assert sorted(frame(g)["constraint"]["cards"]) == ["Estate", "Gold", "Silver"]
    assert decide(g, A, cards=["Gold"])[0]
    assert "Gold" in g["seats"][A]["hand"]
    assert len(g["seats"][A]["dur_aside"]) == 2
    # ...turn 2
    _next_own_turn(g, A)
    assert frame(g) is not None and frame(g)["card"] == "Archive"
    assert decide(g, A, cards=["Silver"])[0]
    assert "Archive" in [e["card"] for e in g["seats"][A]["duration"]]
    # ...turn 3, the last card, and the Archive then goes away
    _next_own_turn(g, A)
    assert decide(g, A, cards=["Estate"])[0]
    assert g["seats"][A]["dur_aside"] == []
    entry = [e for e in g["seats"][A]["duration"] if e["card"] == "Archive"]
    assert entry and entry[0]["done"], "finished, so it discards at Clean-up"


def _next_own_turn(g, pid):
    """Drive turns (answering anything asked) until it is pid's turn again."""
    rng = engine.random.Random(5)
    for _ in range(60):
        if g["pending"]:
            p = g["pending_pid"]
            if p == pid and frame(g)["card"] == "Archive":
                return
            mv(g, p, engine.sample_decision(g, p, rng))
            continue
        cur = g["turn"]
        mv(g, cur, {"type": "end_phase"})
        if not g["pending"] and g["phase"] == "buy":
            mv(g, cur, {"type": "end_phase"})
    raise AssertionError("never got back to a turn")


def test_two_archives_keep_separate_sets():
    """"If you play multiple Archives, keep SEPARATE SETS of cards and take one
    from each set each turn." Zones hold names, so the flat dur_aside alone
    would pool all six into one heap."""
    g = fresh()
    give_hand(g, A, ["Archive", "Archive"])
    g["actions"] = 2
    give_deck(g, A, ["Gold", "Gold", "Gold", "Estate", "Estate", "Estate"]
              + ["Copper"] * 6)
    play(g, A, "Archive")
    assert sorted(set(frame(g)["constraint"]["cards"])) == ["Gold"]
    decide(g, A, cards=["Gold"])
    play(g, A, "Archive")
    assert sorted(set(frame(g)["constraint"]["cards"])) == ["Estate"], \
        "the second Archive offers ITS OWN three, not the first one's"
    decide(g, A, cards=["Estate"])


def test_capital_hands_you_six_debt_when_it_is_discarded_from_play():
    g = fresh()
    coins(g, 0)
    g["seats"][A]["in_play"] = ["Capital"]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert g["debt"][A] == 6


def test_capital_removed_from_play_gives_no_debt():
    """"If you REMOVE Capital from play, preventing it from being discarded,
    you don't get the Debt." """
    g = fresh()
    coins(g, 0)
    g["seats"][A]["in_play"] = ["Capital"]
    engine.trash(g, A, ["Capital"], zone="in_play")
    mv(g, A, {"type": "end_phase"})
    assert g["debt"][A] == 0


def test_charm_can_take_the_buy_and_coins():
    g = fresh(kingdom=KE2)
    coins(g, 0)
    g["seats"][A]["hand"] = ["Charm"]
    assert mv(g, A, {"type": "play_treasure", "card": "Charm"})[0]
    assert decide(g, A, ids=["coins"])[0]
    assert g["coins"] == 2 and g["buys"] == 2


def test_charm_copies_the_cost_of_your_next_gain_with_a_different_name():
    g = fresh(kingdom=KE2)
    coins(g, 5)
    g["seats"][A]["hand"] = ["Charm"]
    mv(g, A, {"type": "play_treasure", "card": "Charm"})
    decide(g, A, ids=["gain"])
    # a $5 gain with NO when-gain of its own, so Charm's rider is the only
    # consumer and there is no ability-pool prompt in between
    gain(g, A, "Groundskeeper")
    piles = frame(g)["constraint"]["piles"]
    assert "Groundskeeper" not in piles, "differently NAMED"
    assert "Forum" in piles and "Silver" not in piles, "same cost"
    assert decide(g, A, pile="Forum")[0]
    assert "Forum" in g["seats"][A]["discard"]


def test_crown_plays_an_action_twice_in_the_action_phase():
    g = fresh(kingdom=KE2)
    g["seats"][A]["hand"] = ["Crown", "Forum"]
    give_deck(g, A, ["Copper"] * 12)
    assert play(g, A, "Crown")[0]
    assert decide(g, A, cards=["Forum"])[0]
    # Forum: +3 Cards, +1 Action, discard 2 — twice
    for _ in range(2):
        assert frame(g)["kind"] == "choose_cards"
        decide(g, A, cards=frame(g)["constraint"]["cards"][:2])
    assert g["seats"][A]["in_play"].count("Forum") == 1


def test_crown_plays_a_treasure_twice_in_the_buy_phase():
    g = fresh(kingdom=KE2)
    coins(g, 0)
    g["seats"][A]["hand"] = ["Crown", "Gold"]
    assert mv(g, A, {"type": "play_treasure", "card": "Crown"})[0]
    assert decide(g, A, cards=["Gold"])[0]
    assert g["coins"] == 6


def test_forum_gives_a_buy_when_you_GAIN_it():
    g = fresh(kingdom=KE2)
    coins(g, 5)
    before = g["buys"]
    gain(g, A, "Forum")
    assert g["buys"] == before + 1, "2022: a when-GAIN ability"


def test_groundskeeper_scores_only_victory_cards_gained_after_it():
    g = fresh(kingdom=KE2)
    gain(g, A, "Estate")
    assert g["vp_tokens"][A] == 0
    give_hand(g, A, ["Groundskeeper"])
    give_deck(g, A, ["Copper"] * 4)
    play(g, A, "Groundskeeper")
    gain(g, A, "Estate")
    assert g["vp_tokens"][A] == 1
    gain(g, A, "Silver")
    assert g["vp_tokens"][A] == 1, "Victory cards only"


def test_groundskeeper_is_cumulative_and_dies_with_the_turn():
    g = fresh(kingdom=KE2)
    give_hand(g, A, ["Groundskeeper", "Groundskeeper"])
    g["actions"] = 2
    give_deck(g, A, ["Copper"] * 8)
    play(g, A, "Groundskeeper")
    play(g, A, "Groundskeeper")
    gain(g, A, "Estate")
    assert g["vp_tokens"][A] == 2
    mv(g, A, {"type": "end_phase"})
    mv(g, A, {"type": "end_phase"})
    gain(g, A, "Estate")
    assert g["vp_tokens"][A] == 2, "the ability was for THAT turn"


def test_legionary_makes_them_discard_to_two_then_draw_one():
    g = fresh(kingdom=KE2)
    give_hand(g, A, ["Legionary", "Gold"])
    g["seats"][B]["hand"] = ["Copper"] * 5
    give_deck(g, B, ["Estate"] * 3)
    assert play(g, A, "Legionary")[0]
    assert g["coins"] == 3
    assert decide(g, A, ids=["yes"])[0]
    assert g["pending_pid"] == B
    assert decide(g, B, cards=["Copper"] * 3)[0]
    assert len(g["seats"][B]["hand"]) == 3, "2 left, then draw 1"


def test_legionary_with_two_or_fewer_cards_still_draws_one():
    g = fresh(kingdom=KE2)
    give_hand(g, A, ["Legionary", "Gold"])
    g["seats"][B]["hand"] = ["Copper"]
    give_deck(g, B, ["Estate"] * 3)
    play(g, A, "Legionary")
    decide(g, A, ids=["yes"])
    assert len(g["seats"][B]["hand"]) == 2
    assert not g["pending"]


def test_wild_hunt_gathers_or_cashes_out_for_an_estate():
    g = fresh(kingdom=KE2)
    give_hand(g, A, ["Wild Hunt"])
    give_deck(g, A, ["Copper"] * 6)
    play(g, A, "Wild Hunt")
    assert decide(g, A, ids=["draw"])[0]
    assert engine.pile_vp(g, "Wild Hunt") == 1
    assert g["seats"][A]["hand"].count("Copper") == 3
    g["actions"] = 1
    g["phase"] = "action"
    g["seats"][A]["hand"] = ["Wild Hunt"]
    play(g, A, "Wild Hunt")
    assert decide(g, A, ids=["estate"])[0]
    assert "Estate" in g["seats"][A]["discard"]
    assert g["vp_tokens"][A] == 1
    assert engine.pile_vp(g, "Wild Hunt") == 0


# ── the split-pile halves ────────────────────────────────────────────────────

def test_encampment_revealing_a_gold_keeps_it_in_play():
    g = fresh(kingdom=KSPLIT)
    give_hand(g, A, ["Encampment", "Gold"])
    give_deck(g, A, ["Copper"] * 4)
    assert play(g, A, "Encampment")[0]
    assert g["actions"] == 2
    assert decide(g, A, cards=["Gold"])[0]
    assert "Encampment" in g["seats"][A]["in_play"]
    assert g["seats"][A]["cleanup_return"] == []


def test_encampment_goes_back_to_its_pile_at_cleanup():
    g = fresh(kingdom=KSPLIT)
    give_hand(g, A, ["Encampment"])
    give_deck(g, A, ["Copper"] * 8)
    base = engine.pile_count(g, "Encampment/Plunder")
    play(g, A, "Encampment")            # no Gold or Plunder in hand
    assert g["seats"][A]["cleanup_return"] == ["Encampment"]
    assert "Encampment" in engine.owned_cards(g, A), "still yours until Clean-up"
    mv(g, A, {"type": "end_phase"})
    mv(g, A, {"type": "end_phase"})
    assert g["seats"][A]["cleanup_return"] == []
    assert "Encampment" not in g["seats"][A]["discard"]
    assert engine.pile_count(g, "Encampment/Plunder") == base + 1
    assert engine.pile_top(g, "Encampment/Plunder") == "Encampment"


def test_plunder_is_two_coins_and_a_vp():
    g = fresh(kingdom=KSPLIT)
    coins(g, 0)
    g["seats"][A]["hand"] = ["Plunder"]
    assert mv(g, A, {"type": "play_treasure", "card": "Plunder"})[0]
    assert g["coins"] == 2 and g["vp_tokens"][A] == 1


def test_patrician_pockets_a_five_and_puts_a_cheap_card_back():
    g = fresh(kingdom=KSPLIT)
    give_hand(g, A, ["Patrician"])
    give_deck(g, A, ["Copper", "Gold", "Copper"])
    play(g, A, "Patrician")
    # +1 Card takes the Copper; the Gold is then REVEALED off the top and, at
    # $6, put into hand as well. The third card stays on the deck.
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Gold"]
    assert g["seats"][A]["deck"] == ["Copper"]


def test_emporium_scores_two_vp_when_gained_with_five_actions_in_play():
    g = fresh(kingdom=KSPLIT)
    g["seats"][A]["in_play"] = ["Village"] * 5
    g["seats"][A]["in_play"] = ["Temple"] * 5
    gain(g, A, "Patrician/Emporium")
    assert g["vp_tokens"][A] == 0, "the pile's TOP card is a Patrician"
    drain(g, "Patrician/Emporium", 5)
    gain(g, A, "Patrician/Emporium")
    assert g["vp_tokens"][A] == 2


def test_settlers_fishes_a_copper_out_of_the_discard_pile():
    g = fresh(kingdom=KSPLIT)
    give_hand(g, A, ["Settlers"])
    give_deck(g, A, ["Estate"] * 3)
    g["seats"][A]["discard"] = ["Copper", "Silver"]
    play(g, A, "Settlers")
    assert decide(g, A, ids=["yes"])[0]
    assert "Copper" in g["seats"][A]["hand"]
    assert g["seats"][A]["discard"] == ["Silver"]


def test_bustling_village_fishes_a_settlers_and_gives_three_actions():
    g = fresh(kingdom=KSPLIT)
    give_hand(g, A, ["Bustling Village"])
    give_deck(g, A, ["Estate"] * 3)
    g["seats"][A]["discard"] = ["Settlers"]
    play(g, A, "Bustling Village")
    assert g["actions"] == 3
    decide(g, A, ids=["yes"])
    assert "Settlers" in g["seats"][A]["hand"]


def test_catapult_curses_on_a_three_and_hits_hands_on_a_treasure():
    g = fresh(kingdom=KSPLIT)
    give_hand(g, A, ["Catapult", "Gold"])
    g["seats"][B]["hand"] = ["Copper"] * 5
    assert play(g, A, "Catapult")[0]
    assert g["coins"] == 1
    assert decide(g, A, cards=["Gold"])[0]
    # Gold costs $6 (>= $3) AND is a Treasure, so both halves fire
    assert "Curse" in g["seats"][B]["discard"]
    assert g["pending_pid"] == B
    assert decide(g, B, cards=["Copper", "Copper"])[0]
    assert len(g["seats"][B]["hand"]) == 3


def test_catapult_on_a_cheap_non_treasure_does_neither():
    g = fresh(kingdom=KSPLIT)
    give_hand(g, A, ["Catapult", "Estate"])
    g["seats"][B]["hand"] = ["Copper"] * 5
    play(g, A, "Catapult")
    decide(g, A, cards=["Estate"])
    assert "Curse" not in g["seats"][B]["discard"]
    assert not g["pending"]


def test_rocks_gains_a_silver_to_the_deck_in_your_buy_phase_and_to_hand_otherwise():
    g = fresh(kingdom=KSPLIT)
    drain(g, "Catapult/Rocks", 5)       # the Rocks are showing
    g["phase"] = "buy"
    gain(g, A, "Catapult/Rocks")
    assert g["seats"][A]["deck"][0] == "Silver"
    g["phase"] = "action"
    g["seats"][A]["discard"] = ["Rocks"]
    trash(g, A, ["Rocks"], zone="discard")
    assert "Silver" in g["seats"][A]["hand"], "trashing gives one too"


def test_gladiator_pays_and_trashes_when_the_left_player_cannot_match():
    g = fresh(kingdom=KSPLIT)
    give_hand(g, A, ["Gladiator", "Estate"])
    g["seats"][B]["hand"] = ["Copper"]
    base = engine.pile_count(g, "Gladiator/Fortune")
    assert play(g, A, "Gladiator")[0]
    assert g["coins"] == 2
    assert decide(g, A, cards=["Estate"])[0]
    assert g["coins"] == 3
    assert engine.pile_count(g, "Gladiator/Fortune") == base - 1
    assert "Gladiator" in g["trash"]


def test_gladiator_matched_pays_nothing_extra():
    g = fresh(kingdom=KSPLIT)
    give_hand(g, A, ["Gladiator", "Estate"])
    g["seats"][B]["hand"] = ["Estate"]
    base = engine.pile_count(g, "Gladiator/Fortune")
    play(g, A, "Gladiator")
    decide(g, A, cards=["Estate"])
    assert g["coins"] == 2
    assert engine.pile_count(g, "Gladiator/Fortune") == base


def test_gladiator_cannot_trash_when_a_fortune_is_on_top():
    """"You can only trash a Gladiator if it's on top of the pile." """
    g = fresh(kingdom=KSPLIT)
    drain(g, "Gladiator/Fortune", 5)
    give_hand(g, A, ["Gladiator", "Estate"])
    g["seats"][B]["hand"] = ["Copper"]
    play(g, A, "Gladiator")
    decide(g, A, cards=["Estate"])
    assert g["coins"] == 3, "you still get the +$1"
    assert "Gladiator" not in g["trash"]


def test_fortune_doubles_your_coins_once_a_turn():
    g = fresh(kingdom=KSPLIT)
    coins(g, 5)
    g["seats"][A]["hand"] = ["Fortune", "Fortune"]
    mv(g, A, {"type": "play_treasure", "card": "Fortune"})
    assert g["coins"] == 10 and g["buys"] == 2
    mv(g, A, {"type": "play_treasure", "card": "Fortune"})
    assert g["coins"] == 10, "only the +1 Buy the second time"
    assert g["buys"] == 3


def test_gaining_a_fortune_gains_a_gold_per_gladiator_in_play():
    g = fresh(kingdom=KSPLIT)
    g["seats"][A]["in_play"] = ["Gladiator", "Gladiator"]
    drain(g, "Gladiator/Fortune", 5)
    gain(g, A, "Gladiator/Fortune")
    assert g["seats"][A]["discard"].count("Gold") == 2


# ── the Castles ──────────────────────────────────────────────────────────────

def test_humble_and_kings_castle_count_every_castle_you_have():
    g = fresh(kingdom=KSPLIT)
    _only(g, A, ["Humble Castle", "King's Castle", "Small Castle"])
    # Humble = 1 per Castle (3), King's = 2 per Castle (6), Small = flat 2
    assert engine._vp_of(g, A) == 3 + 6 + 2


def test_a_lone_humble_castle_counts_itself():
    g = fresh(kingdom=KSPLIT)
    _only(g, A, ["Humble Castle"])
    assert engine._vp_of(g, A) == 1


def test_crumbling_castle_pays_on_both_gaining_and_trashing():
    g = fresh(kingdom=KSPLIT)
    drain(g, "Castles", 1)              # Crumbling Castle is now on top
    gain(g, A, "Castles")
    assert g["vp_tokens"][A] == 1
    assert "Silver" in g["seats"][A]["discard"]
    trash(g, A, ["Crumbling Castle"], zone="discard")
    assert g["vp_tokens"][A] == 2
    assert g["seats"][A]["discard"].count("Silver") == 2


def test_small_castle_trashes_itself_to_gain_the_next_castle():
    g = fresh(kingdom=KSPLIT)
    drain(g, "Castles", 3)          # Haunted Castle is now the pile top
    give_hand(g, A, ["Small Castle"])
    assert play(g, A, "Small Castle")[0]
    assert "self" in opt_ids(g)
    assert decide(g, A, ids=["self"])[0]
    assert "Small Castle" in g["trash"]
    assert "Haunted Castle" in g["seats"][A]["discard"]


def test_haunted_castle_gained_on_your_turn_hits_full_hands():
    g = fresh(kingdom=KSPLIT)
    drain(g, "Castles", 3)          # Haunted Castle is now on top
    g["seats"][B]["hand"] = ["Copper"] * 5
    gain(g, A, "Castles")
    assert "Gold" in g["seats"][A]["discard"]
    assert g["pending_pid"] == B
    assert decide(g, B, cards=["Copper", "Copper"])[0]
    assert decide(g, B, order=["Copper", "Copper"])[0]
    assert len(g["seats"][B]["hand"]) == 3
    assert g["seats"][B]["deck"][:2] == ["Copper", "Copper"]


def test_haunted_castle_gained_off_turn_does_nothing():
    g = fresh(kingdom=KSPLIT)
    drain(g, "Castles", 3)          # Haunted Castle is now on top
    g["seats"][B]["hand"] = ["Copper"] * 5
    gain(g, B, "Castles")     # A's turn
    assert "Gold" not in g["seats"][B]["discard"]
    assert not g["pending"]


def test_opulent_castle_pays_two_per_victory_card_discarded():
    g = fresh(kingdom=KSPLIT)
    give_hand(g, A, ["Opulent Castle", "Estate", "Duchy", "Copper"])
    assert play(g, A, "Opulent Castle")[0]
    assert sorted(frame(g)["constraint"]["cards"]) == ["Duchy", "Estate"]
    assert decide(g, A, cards=["Estate", "Duchy"])[0]
    assert g["coins"] == 4


def test_sprawling_castle_gives_a_duchy_or_three_estates():
    g = fresh(kingdom=KSPLIT)
    drain(g, "Castles", 5)          # Sprawling Castle is now on top
    gain(g, A, "Castles")
    assert sorted(opt_ids(g)) == ["duchy", "estates"]
    assert decide(g, A, ids=["estates"])[0]
    assert g["seats"][A]["discard"].count("Estate") == 3


def test_grand_castle_counts_victory_cards_in_every_play_area():
    """"This counts Victory cards IN PLAY, but not just in your play area. If
    other players have Victory cards in play, they count too." """
    g = fresh(kingdom=KSPLIT)
    drain(g, "Castles", 6)          # Grand Castle is now on top
    give_hand(g, A, ["Estate", "Duchy", "Copper"])
    g["seats"][A]["in_play"] = ["Humble Castle"]
    g["seats"][B]["in_play"] = ["Estate"]
    gain(g, A, "Castles")
    assert g["vp_tokens"][A] == 2 + 1 + 1


# ── the trigger-bus / registry hygiene ───────────────────────────────────────

def test_every_empires_kingdom_card_that_needs_an_effect_has_one():
    """A Treasure or a pure Victory card needs no EFFECTS entry; anything else
    does, or play_action_card raises at the table."""
    for name, c in cards.CARDS.items():
        if c["expansion"] != "empires":
            continue
        if "action" not in c["types"]:
            continue
        assert name in effects.EFFECTS, name


def test_no_empires_stage_is_registered_twice():
    seen = {}
    for (card, stage) in effects.STAGES:
        seen.setdefault(card, set()).add(stage)
    assert seen["Temple"] == {"trash", "gain"}


# ── the bots ─────────────────────────────────────────────────────────────────

def test_a_policy_bot_pays_off_its_debt_before_anything_else():
    """Debt blocks ALL buying, so a tier that ignores it stops playing: no
    error, no stall, just a bot that ends every remaining turn with its coins
    unspent. `_pay_off_debt` runs first in the Buy phase for every policy
    tier."""
    from games.dontminion import bot
    g = fresh()
    coins(g, 0)
    assert mv(g, A, {"type": "buy", "card": "Engineer"})[0]
    assert g["debt"][A] == 4
    g["coins"] = 5
    move = bot.choose_bm_plus(g, A, engine.random.Random(1))
    assert move == {"type": "spend", "what": "debt", "n": 4}
    assert mv(g, A, move)[0]
    assert g["debt"][A] == 0 and g["coins"] == 1


def test_the_debt_payoff_is_skipped_when_there_is_no_debt():
    from games.dontminion import bot
    g = fresh()
    coins(g, 5)
    move = bot.choose_bm_plus(g, A, engine.random.Random(1))
    assert move["type"] != "spend"


def test_a_split_pile_is_never_the_bots_terminal():
    """An ordered pile's face changes, so it is nobody's reliable terminal
    (the ph.-3H rule) — and `best_bm_terminal` skips a kingdom entry that is
    not a card at all."""
    from games.dontminion import bot_traits
    assert bot_traits.best_bm_terminal(KSPLIT) not in KSPLIT[:6]


# ── the deviations the docs promise ──────────────────────────────────────────

def test_merchant_guild_is_paid_for_the_buy_phase_villa_ended():
    """"If you have several Buy phases due to … Villa, a played Merchant Guild
    triggers each time, CHECKING THE BUY PHASE THAT JUST ENDED."

    The regression this pins is subtle and was SILENT: `emit` only PARKS the
    ability pool, so a consumer that reads the live `buy_gains` reads it after
    the next phase has already reset it. Merchant Guild's join filter saw the
    pre-reset value and let it into the pool, and its stage then paid 0 — no
    error, no log, just a card that stopped working behind a Villa. The count
    rides the EVENT now, the same discipline as `gain(**extra)`."""
    g = engine.new_game([A, B], ["cornucopia", "empires", "base"], seed=3,
                        kingdom=["Merchant Guild", "Villa", "Cellar", "Smithy",
                                 "Village", "Market", "Moat", "Militia",
                                 "Festival", "Gardens"])
    give_hand(g, A, ["Merchant Guild"])
    assert mv(g, A, {"type": "play_action", "card": "Merchant Guild"})[0]
    coins(g, 20)
    g["buys"] = 5
    engine.gain(g, A, "Cellar")
    engine._drive(g)
    assert g["turn_ctx"]["buy_gains"] == 1
    assert mv(g, A, {"type": "buy", "card": "Villa"})[0]
    assert g["phase"] == "action", "Villa sent us back"
    engine._drive(g)
    # the Cellar AND the Villa were both gained in the phase that just ended
    assert g["coffers"].get(A, 0) == 2
    assert g["turn_ctx"]["buy_gains"] == 0, "the next Buy phase starts fresh"


def test_villa_ends_a_buy_phase_and_only_the_last_one_is_final():
    """Deviation B1's other half, RESOLVED IN PH. 9 — and the resolution is
    the opposite of what ph. 8 pinned here.

    Villa really does end a Buy phase, and four shipped cards print "at the
    end of your Buy phase … in it" (Merchant Guild, Treasury, Hermit, Wine
    Merchant) plus Renaissance's Exploration and Pageant, all of which must
    see BOTH. So the event now fires per Buy phase. What protects the three
    cards that only RIDE it to approximate Clean-up timing (Alchemist,
    Herbalist, Scheme — each printed "when you discard it from play") is the
    `final` flag on the ctx, not the emit being unique."""
    g = fresh()
    fired = []
    real = engine.emit

    def spy(game, event, **kw):
        if event == "buy_phase_end":
            fired.append(kw.get("final"))
        return real(game, event, **kw)

    engine.emit = spy
    try:
        coins(g, 4)
        mv(g, A, {"type": "buy", "card": "Villa"})
        assert g["phase"] == "action", "Villa sent us back"
        mv(g, A, {"type": "end_phase"})     # action -> buy again
        mv(g, A, {"type": "end_phase"})     # buy -> clean-up
    finally:
        engine.emit = real
    assert fired == [False, True], "one per Buy phase, the last one final"


def test_a_scheme_is_not_topdecked_by_a_villa_mid_turn():
    """The behaviour the test above used to protect, pinned directly: Scheme's
    offer must open ONCE, at the real end of the turn, even though the event
    it rides now fires twice."""
    g = engine.new_game([A, B], ["empires", "hinterlands"], seed=4,
                        kingdom=["Villa", "Scheme", "Engineer", "Forum",
                                 "Charm", "Crossroads", "Oasis", "Haggler",
                                 "Highway", "Stables"])
    give_hand(g, A, ["Scheme", "Copper", "Copper", "Copper", "Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Scheme"})[0]
    assert g["phase"] == "buy", "no Action left in hand: auto-advanced"
    coins(g, 4)
    assert mv(g, A, {"type": "buy", "card": "Villa"})[0]
    assert g["phase"] == "action", "Villa sent us back"
    # THE POINT: a Buy phase just ended, and Scheme must not have been offered
    assert g["pending_pid"] is None, "Scheme jumped in mid-turn"
    assert mv(g, A, {"type": "end_phase"})[0]           # action -> buy again
    assert mv(g, A, {"type": "end_phase"})[0]           # buy -> Clean-up
    # ...and now it is, exactly once, with the Scheme still on the table
    assert g["pending_pid"] == A and g["pending"][-1]["card"] == "Scheme"
    assert mv(g, A, {"type": "decision", "cards": ["Scheme"]})[0]
    # topdecked, so the Clean-up draw takes it straight back into the new hand
    assert "Scheme" in g["seats"][A]["hand"]
    assert "Scheme" not in g["seats"][A]["discard"]


def test_crown_fully_resolves_the_first_play_before_the_second():
    """"You must completely resolve the play ability before playing it again"
    (p17). The replay is parked BELOW the first play's frames, so a Crowned
    card that pushes a decision gets its two prompts in the right order —
    pushed the other way round, a Crowned Oasis's second discard prompt was
    answered against a hand the first one had already discarded from, and the
    move crashed (found by the ph.-8 fuzz census)."""
    g = engine.new_game([A, B], ["empires", "hinterlands"], seed=4,
                        kingdom=["Crown", "Oasis", "Forum", "Villa", "Temple",
                                 "Archive", "Sacrifice", "Capital", "Trail",
                                 "Nomads"],
                        landscapes=[])
    g["seats"][A]["hand"] = ["Crown", "Oasis", "Copper", "Estate"]
    give_deck(g, A, ["Silver", "Gold", "Duchy", "Copper"])
    assert play(g, A, "Crown")[0]
    assert decide(g, A, cards=["Oasis"])[0]
    # first Oasis: +1 Card, +$1, discard 1 — answered BEFORE the replay runs
    seen = 0
    for _ in range(2):
        assert frame(g)["card"] == "Oasis", "one prompt at a time"
        pick = frame(g)["constraint"]["cards"][0]
        assert pick in g["seats"][A]["hand"], "the offer matches the LIVE hand"
        assert decide(g, A, cards=[pick])[0]
        seen += 1
    assert seen == 2
    assert g["coins"] == 2
