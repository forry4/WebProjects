"""THE PILE MODEL (phase 3H) — the seams no shipped card consumes yet.

3H is hardening: it changes no card and no game we can play today. Every claim
it makes is therefore about behaviour that FIRST arrives one to ten phases from
now — ordered piles (Ruins and Knights in Dark Ages, split piles and Castles in
Empires, rotating piles in Allies), and gain sources outside the Supply
(Rewards, Spoils, Horses, Spirits, Loot). A refactor whose only evidence is
"the existing suite still passes" has proved that it changed nothing, which is
half the job: the other half is that the thing it was built for works.

So these drive the unconsumed seams end to end against the real kernel — buy,
gain, the trigger bus, the game end, redaction, the census and migration —
using piles invented here. When Dark Ages lands, its cards ride paths that were
already exercised rather than paths that merely existed.
"""

import copy
import json

import pytest

from games.dontminion import engine
from games.dontminion.cards import CARDS

A, B = "alice", "bob"
K7 = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room", "Gardens"]

# A stand-in for Dark Ages' Knights: one ordered pile whose TOP card is what it
# costs, what it is, and what it hands you. Real cards, so cards.py stays
# untouched — what matters is that the pile's NAME is not one of them.
#
# They are deliberately cards OUTSIDE the kingdoms below, mirroring the real
# sets: nothing in an ordered pile also has a Supply pile of its own, and using
# a card that did would make pile_of() ambiguous in a way no set is.
KNIGHTS = ["Bandit", "Cellar", "Harbinger"]      # $5, $2, $3 — deliberately unequal
TOP, MID, LAST = KNIGHTS
# ...and a stand-in for Spoils: a real card (every pile's face must be one),
# outside the kingdom, so nothing here can reach it except through its pile.
SPOILS = "Poacher"


def fresh(players=(A, B), seed=42, kingdom=tuple(K7), expansions=("base",)):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom))


def knights(g, name="Knights", contents=tuple(KNIGHTS)):
    return engine.add_pile(g, name, contents=list(contents), supply=True)


def buy_phase(g, pid, coins=20):
    g["turn"] = pid
    g["phase"] = "buy"
    g["coins"] = coins
    g["buys"] = 1
    g["pending"] = []
    engine._sync_pending(g)


# --- the shape ----------------------------------------------------------------

def test_a_new_game_models_every_supply_pile():
    g = fresh()
    assert set(g["piles"]) == set(g["supply"])
    assert g["nonsupply"] == {}
    for name, p in g["piles"].items():
        assert p["supply"] is True
        assert p["face"] == name             # an ordinary pile is its own face
        assert p["contents"] is None         # ...and keeps no list of copies
        assert p["members"] == [name]
        assert p["attach"] == {}
        assert engine.pile_count(g, name) == g["supply"][name]


def test_the_supply_index_is_still_hand_writable():
    """The ~110 existing `g["supply"]["Curse"] = 0` fixtures — and every future
    card batch's — must keep meaning what they say. This is why an ordinary
    pile's count lives in the index and NOT on the pile object: putting it on
    the object would have made every one of them a silent desync."""
    g = fresh()
    g["supply"]["Curse"] = 0
    assert engine.pile_count(g, "Curse") == 0
    assert engine.pile_top(g, "Curse") is None
    assert engine.gain(g, A, "Curse") is False
    assert engine.count_empty_piles(g) == 1


def test_pile_helpers_are_total_on_unknown_names():
    """Card code asks about names it may not own (a pile that isn't in this
    game, a card in nobody's pile). None of these may raise."""
    g = fresh()
    assert engine.pile_count(g, "Nonesuch") == 0
    assert engine.pile_top(g, "Nonesuch") is None
    assert engine.pile_of(g, "Nonesuch") is None
    assert engine.is_supply_pile(g, "Nonesuch") is False
    assert engine.pile_face(g, "Nonesuch") == "Nonesuch"
    assert engine.pile_attachment(g, "Nonesuch", "token") is None


# --- ordered piles ------------------------------------------------------------

def test_an_ordered_pile_costs_and_is_its_top_card():
    g = fresh()
    knights(g)
    assert engine.pile_count(g, "Knights") == 3
    assert engine.pile_top(g, "Knights") == TOP
    assert engine.cost(g, "Knights") == CARDS[TOP]["cost"]
    assert engine.has_type(g, "Knights", "attack")        # Bandit is an Attack
    # ...and all of it changes as the pile is drawn down
    engine.gain(g, A, "Knights")
    assert engine.pile_top(g, "Knights") == MID
    assert engine.cost(g, "Knights") == CARDS[MID]["cost"]
    assert not engine.has_type(g, "Knights", "attack")
    assert engine.has_type(g, "Knights", "action")


def test_gaining_an_ordered_pile_hands_you_the_top_card_not_the_pile_name():
    g = fresh()
    knights(g)
    assert engine.gain(g, A, "Knights") is True
    assert g["seats"][A]["discard"][-1] == TOP
    assert "Knights" not in g["seats"][A]["discard"]
    assert engine.pile_count(g, "Knights") == 2
    assert g["supply"]["Knights"] == 2          # the index mirror kept in step
    gained = [e for e in g["log"] if e["event"] == "gain"][-1]
    assert gained["card"] == TOP


def test_an_ordered_pile_empties_in_order_and_keeps_its_last_face():
    """An emptied pile still has a price and a picture on the board, so `face`
    is RETAINED rather than cleared — that is what keeps cost()/types_of()
    total for the client's `costs` map and for any card pricing the pile."""
    g = fresh()
    knights(g)
    for expected in KNIGHTS:
        assert engine.pile_top(g, "Knights") == expected
        assert engine.gain(g, A, "Knights") is True
    assert g["seats"][A]["discard"][-3:] == KNIGHTS
    assert engine.pile_count(g, "Knights") == 0
    assert engine.pile_top(g, "Knights") is None      # nothing left to gain
    assert engine.pile_face(g, "Knights") == LAST
    assert engine.cost(g, "Knights") == CARDS[LAST]["cost"]
    assert engine.gain(g, A, "Knights") is False


def test_buying_an_ordered_pile_pays_the_top_price_and_logs_the_real_card():
    g = fresh()
    knights(g)
    buy_phase(g, A, coins=8)
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Knights"})
    assert ok, err
    assert g["coins"] == 8 - CARDS[TOP]["cost"]
    assert g["seats"][A]["discard"][-1] == TOP
    bought = [e for e in g["log"] if e["event"] == "buy"][-1]
    assert bought["card"] == TOP, "the log must name the card, not the pile"


def test_an_ordered_pile_is_offered_by_legal_moves_at_its_top_cards_price():
    g = fresh()
    knights(g)
    buy_phase(g, A, coins=CARDS[TOP]["cost"])
    assert {"type": "buy", "card": "Knights"} in engine.legal_moves(g, A)
    buy_phase(g, A, coins=CARDS[TOP]["cost"] - 1)
    assert {"type": "buy", "card": "Knights"} not in engine.legal_moves(g, A)


def test_an_emptied_ordered_supply_pile_counts_toward_the_game_end():
    g = fresh()
    knights(g)
    for _ in KNIGHTS:
        engine.gain(g, A, "Knights")
    assert engine.count_empty_piles(g) == 1


def test_a_cost_reduction_applies_to_an_ordered_piles_top_card():
    """Bridge reduces what the pile costs, because the pile costs what its top
    card costs — the resolution happens inside cost(), so every cost rule the
    game has (and every one it grows) reaches an ordered pile for free."""
    g = fresh()
    knights(g)
    g["turn_ctx"]["bridges"] = 2
    assert engine.cost(g, "Knights") == CARDS[TOP]["cost"] - 2
    assert engine.cost_le(g, "Knights", CARDS[TOP]["cost"] - 2)
    assert engine.cost_lt(g, "Knights", CARDS[TOP]["cost"])


# --- piles outside the Supply -------------------------------------------------

def test_a_non_supply_pile_is_never_in_the_supply_index():
    """The property card code relies on WITHOUT KNOWING IT: every "piles
    costing up to $4" enumeration in every effects module reads
    game["supply"], so a Workshop can never offer a Spoils."""
    g = fresh()
    engine.add_pile(g, SPOILS, count=15)
    assert SPOILS not in g["supply"]
    assert g["nonsupply"][SPOILS] == 15
    assert engine.pile_count(g, SPOILS) == 15
    assert engine.is_supply_pile(g, SPOILS) is False
    assert SPOILS not in engine.supply_piles(g)


def test_a_non_supply_pile_cannot_be_bought():
    g = fresh()
    engine.add_pile(g, SPOILS, count=15)
    buy_phase(g, A, coins=20)
    assert {"type": "buy", "card": SPOILS} not in engine.legal_moves(g, A)
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": SPOILS})
    assert not ok and err == "no such pile"
    assert engine.pile_count(g, SPOILS) == 15


def test_an_empty_non_supply_pile_does_not_end_the_game():
    g = fresh()
    engine.add_pile(g, SPOILS, count=1)
    engine.gain_from(g, A, SPOILS)
    assert engine.pile_count(g, SPOILS) == 0
    assert engine.count_empty_piles(g) == 0
    g["supply"]["Village"] = 0
    g["supply"]["Smithy"] = 0
    g["supply"]["Moat"] = 0
    assert engine.count_empty_piles(g) == 3      # three SUPPLY piles, not four


def test_gain_from_a_non_supply_pile_is_a_real_gain():
    """It is a gain, not a special move — the same physical path, so when-gain
    abilities and the would-gain protocol see it. Losing that is how a Spoils
    would silently fail to wake a Watchtower."""
    g = fresh()
    engine.add_pile(g, SPOILS, count=15)
    assert engine.gain_from(g, A, SPOILS) is True
    assert g["seats"][A]["discard"][-1] == SPOILS
    assert engine.pile_count(g, SPOILS) == 14
    ev = [e for e in g["log"] if e["event"] == "gain"][-1]
    assert ev["card"] == SPOILS


def test_gaining_from_an_empty_non_supply_pile_gains_nothing():
    g = fresh()
    engine.add_pile(g, SPOILS, count=0)
    before = list(g["seats"][A]["discard"])
    assert engine.gain_from(g, A, SPOILS) is False
    assert g["seats"][A]["discard"] == before


# --- returning cards to piles --------------------------------------------------

def test_return_to_pile_takes_a_card_off_the_table():
    """Spoils/Madman/Mercenary "return this to its pile" (ph. 6). Not a trash
    and not a discard — the card leaves play and the pile grows back."""
    g = fresh()
    engine.add_pile(g, SPOILS, count=14)
    g["seats"][A]["in_play"].append(SPOILS)
    assert engine.return_to_pile(g, A, SPOILS) is True
    assert SPOILS not in g["seats"][A]["in_play"]
    assert engine.pile_count(g, SPOILS) == 15
    assert [e["event"] for e in g["log"]][-1] == "return_to_pile"


def test_return_to_pile_refuses_a_card_that_is_not_there():
    g = fresh()
    engine.add_pile(g, SPOILS, count=14)
    assert engine.return_to_pile(g, A, SPOILS) is False
    assert engine.pile_count(g, SPOILS) == 14


def test_a_card_returned_to_an_ordered_pile_goes_back_on_top():
    g = fresh()
    knights(g)
    engine.gain(g, A, "Knights")                      # the top card comes off
    assert engine.pile_top(g, "Knights") == MID
    g["seats"][A]["in_play"].append(TOP)
    assert engine.return_to_pile(g, A, TOP) is True
    assert engine.pile_top(g, "Knights") == TOP
    assert engine.pile_count(g, "Knights") == 3
    assert g["supply"]["Knights"] == 3


def test_an_ordered_piles_members_outlive_its_contents():
    """`members` exists because once a pile is EMPTY its contents can no longer
    say what belongs to it — and an empty pile is exactly when a card is most
    likely to be coming back."""
    g = fresh()
    knights(g)
    for _ in KNIGHTS:
        engine.gain(g, A, "Knights")
    assert engine.pile_count(g, "Knights") == 0
    assert engine.pile_of(g, LAST) == "Knights"
    g["seats"][A]["in_play"].append(LAST)
    assert engine.return_to_pile(g, A, LAST) is True
    assert engine.pile_top(g, "Knights") == LAST


def test_exchanging_a_card_that_belongs_to_no_pile_changes_nothing():
    """The pre-3H code did `supply[card] = supply.get(card, 0) + 1` here, which
    would have CONJURED a buyable pile out of the returned card's name."""
    g = fresh()
    g["seats"][A]["discard"].append("Peddler")        # not in this kingdom
    before = copy.deepcopy(g["supply"])
    assert engine.exchange(g, A, "Peddler", "Silver") is False
    assert g["supply"] == before
    assert "Peddler" not in g["piles"]
    assert g["seats"][A]["discard"][-1] == "Peddler"  # still where it was


# --- the trigger bus ----------------------------------------------------------

def test_a_when_gain_trigger_fires_off_an_ordered_pile():
    """The `gain` event's subject is the card you actually GOT, so a self
    trigger on an ordered pile's top card has to fire — that is Dark Ages'
    whole on-gain/on-trash theme riding a pile whose name is not a card."""
    hinter = ["Inn", "Trader", "Oasis", "Nomads", "Souk", "Trail", "Weaver",
              "Highway", "Stables", "Margrave"]
    g = fresh(kingdom=hinter, expansions=("hinterlands",))
    knights(g, contents=["Border Village", "Cellar"])   # a when-gain card on top
    buy_phase(g, A, coins=8)
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Knights"})
    assert ok, err
    # Border Village's when-gain ("gain a cheaper card") opens a pile choice
    assert g["pending_pid"] == A and g["pending_kind"] == "choose_pile"
    assert g["pending"][-1]["card"] == "Border Village"


def test_a_hand_reaction_is_told_the_card_the_pile_handed_over():
    """Watchtower reacts to what you GAINED, and what you gained is the top
    card — not the pile. A window naming "Knights" would be offering to trash
    a card nobody owns."""
    pros = ["Watchtower", "Anvil", "Bishop", "City", "Clerk", "Collection",
            "Crystal Ball", "Investment", "Monument", "Quarry"]
    g = fresh(kingdom=pros, expansions=("prosperity",))
    knights(g)
    buy_phase(g, A, coins=8)
    g["seats"][A]["hand"] = ["Watchtower"]
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Knights"})
    assert ok, err
    top = g["pending"][-1]
    assert top["card"] == "Watchtower" and top["kind"] == "choose_option"
    assert top["data"]["gained"] == TOP, top["data"]


# --- the bots -------------------------------------------------------------------

@pytest.mark.parametrize("difficulty", ["random", "bigmoney", "bmplus"])
def test_every_bot_tier_plays_a_board_holding_an_ordered_and_a_non_supply_pile(difficulty):
    """The bots read the Supply to decide what to buy, and a pile whose NAME is
    not a card is a KeyError waiting in `traits()` and in the endgame's VP
    scan. That crash is scheduled for Dark Ages (ph. 6), which is a bad place
    to find it — the scheduler's turn-finisher would raise mid-turn on a live
    game. Play a whole game per tier now."""
    from games.dontminion import bot
    g = fresh(kingdom=list(K7) + ["Market", "Laboratory", "Festival"])
    engine.add_pile(g, "Knights", supply=True,
                    contents=["Cellar", "Harbinger", "Poacher", "Bandit"])
    engine.add_pile(g, SPOILS, count=8)
    rng = __import__("random").Random(4)
    for _ in range(3000):
        if g["over"]:
            break
        pid = g["pending_pid"] or g["turn"]
        ok, err = engine.apply_move(g, pid, bot.choose(g, pid, rng, difficulty))
        assert ok, err
    assert g["over"], "the bots did not finish the game"
    assert "Knights" not in engine.owned_cards(g, A) + engine.owned_cards(g, B)


# --- attachments ---------------------------------------------------------------

def test_something_can_sit_on_a_pile():
    """Adventures tokens (ph. 7), Empires' gathered VP (ph. 8) and Plunder's
    Traits (ph. 13) all attach to a PILE rather than to a card or a player."""
    g = fresh()
    engine.pile_attach(g, "Village", "trait", "Cursed")
    engine.pile_attach(g, "Village", "vp", 3)
    assert engine.pile_attachment(g, "Village", "trait") == "Cursed"
    assert engine.pile_attachment(g, "Village", "vp") == 3
    assert engine.pile_attachment(g, "Smithy", "trait") is None
    assert engine.pile_attachment(g, "Smithy", "trait", "none") == "none"
    # it is table state: public, and it survives the wire
    view = engine.player_view(g, B)
    assert view["piles"]["Village"]["attach"] == {"trait": "Cursed", "vp": 3}


# --- the wire ------------------------------------------------------------------

def test_the_pile_view_never_ships_a_piles_hidden_order():
    """Ruins and Knights are SHUFFLED — the order below the top is hidden
    information. The repo has paid three times for "an honest client ignores
    it", so contents never reach the wire at all, in any game state."""
    g = fresh()
    knights(g)
    for viewer in (A, B, None):
        v = engine.player_view(g, viewer)
        blob = json.dumps(v)
        assert "contents" not in blob and "members" not in blob
        assert v["piles"]["Knights"] == {
            "count": 3, "supply": True, "face": TOP,
            "ordered": True, "attach": {}}
    g["over"] = True
    assert "contents" not in json.dumps(engine.player_view(g, A))


def test_the_view_prices_every_pile_including_the_ones_you_cannot_buy():
    g = fresh()
    knights(g)
    engine.add_pile(g, SPOILS, count=15)
    v = engine.player_view(g, A)
    assert v["costs"]["Knights"] == CARDS[TOP]["cost"]
    assert v["costs"][SPOILS] == CARDS[SPOILS]["cost"]
    assert v["piles"][SPOILS] == {"count": 15, "supply": False, "face": SPOILS,
                                  "ordered": False, "attach": {}}
    assert v["supply"] == g["supply"], "the supply index ships unchanged"


# --- the census ----------------------------------------------------------------

def test_the_census_counts_the_cards_in_a_pile_not_the_piles_name():
    g = fresh()
    plain = engine.pile_cards(g)
    assert plain == {n: c for n, c in g["supply"].items() if c}
    knights(g)
    engine.add_pile(g, SPOILS, count=15)
    census = engine.pile_cards(g)
    assert "Knights" not in census, "the pile name is not a card anyone can own"
    for c in KNIGHTS:
        assert census[c] == plain.get(c, 0) + 1
    assert census[SPOILS] == plain.get(SPOILS, 0) + 15
    engine.gain(g, A, "Knights")
    assert engine.pile_cards(g).get(TOP, 0) == plain.get(TOP, 0)


# --- migration ------------------------------------------------------------------

def test_a_pre_pile_save_rebuilds_the_whole_model():
    """Every pile a pre-3H save can hold is an ordinary Supply pile of the card
    it is named after, so the model rebuilds from the count index alone."""
    g = fresh()
    old = json.loads(json.dumps(g))
    old.pop("piles")
    old.pop("nonsupply")
    old["schema"] = 5
    engine.migrate(old)
    assert old["schema"] == engine.SCHEMA
    assert old["nonsupply"] == {}
    assert set(old["piles"]) == set(old["supply"])
    assert old["piles"] == g["piles"]
    # and it still plays
    assert engine.apply_move(old, A, {"type": "end_phase"})[0]
    ok, err = engine.apply_move(old, A, {"type": "play_all_treasures"})
    assert ok, err


def test_migrate_leaves_a_game_that_already_has_piles_alone():
    """The fill is presence-based (never `if v < N`), so it must not stamp over
    a game carrying real piles — which after ph. 6 will include ordered and
    non-supply ones the supply index cannot describe."""
    g = fresh()
    knights(g)
    engine.add_pile(g, SPOILS, count=15)
    engine.gain(g, A, "Knights")
    snapshot = json.loads(json.dumps(g))
    engine.migrate(g)
    assert g["piles"] == snapshot["piles"]
    assert g["nonsupply"] == snapshot["nonsupply"]
    assert engine.pile_top(g, "Knights") == MID


def test_a_game_with_every_kind_of_pile_survives_json():
    g = fresh()
    knights(g)
    engine.add_pile(g, SPOILS, count=15)
    engine.pile_attach(g, "Knights", "token", "+1 Card")
    round_tripped = json.loads(json.dumps(g))
    assert round_tripped["piles"] == g["piles"]
    assert engine.pile_top(round_tripped, "Knights") == TOP


# --- setup guards ---------------------------------------------------------------

def test_add_pile_refuses_to_shadow_an_existing_pile():
    g = fresh()
    with pytest.raises(ValueError):
        engine.add_pile(g, "Village", count=10)


def test_an_ordered_pile_cannot_start_empty():
    """An ordered pile with no cards has no face, and every cost/type query
    would grow a None branch. Fail at setup instead."""
    g = fresh()
    with pytest.raises(ValueError):
        engine.add_pile(g, "Knights", contents=[])


def test_a_pile_whose_face_is_not_a_real_card_is_refused_at_setup():
    """cost() prices a pile through its face and player_view prices EVERY pile
    on every wire build, so an unknown face is a KeyError inside a view the
    client is waiting on. Fail where the pile is named instead."""
    g = fresh()
    with pytest.raises(ValueError):
        engine.add_pile(g, "Spoils", count=15)          # not a card we ship yet
    with pytest.raises(ValueError):
        engine.add_pile(g, "Knights", contents=["Sir Martin"])
