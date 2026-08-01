"""Cornucopia & Guilds batch-B card tests — Butcher, Coronet, Farmhands,
Farrier, Ferryman, Footpad, Herald, Horn of Plenty, Infirmary, Jester,
Journeyman, Stonemason, Young Witch — plus the two kernel systems this half
owns: COFFERS (the spendable counter + the generic `spend` move) and OVERPAY.

Positions are arranged by mutating the game dict directly (the repo's
board-fixture idiom). give_hand breaks card conservation, so no test here
asserts the census invariant (test_soak owns that).

Headline rulings pinned here:
  * COFFERS are spendable AT ANY TIME DURING YOUR TURN (the 2022 rules change),
    not just in the Buy phase; each token is +$1 and gone. They are a MAT, so
    unlike the per-turn pools they survive the turn and a Coffers earned on an
    opponent's turn is kept rather than evaporating.
  * OVERPAY is paid when you PAY for the card, and the ability it buys is a
    WHEN-GAIN ability (the 2022 retiming) that reads how much you overpaid.
    You cannot overpay $0, and any ability reading the card's cost ignores the
    `+`. Consumers: Farrier, Herald, Infirmary, Stonemason.
  * Herald's overpay may choose the just-gained Herald itself, because the
    ability now resolves after the gain lands in the discard pile.
  * Infirmary plays ITSELF once per $1 overpaid; each play draws and then
    optionally trashes.
  * Farrier's cards are drawn at the END of the turn, after the new hand — the
    point of the card is a bigger hand NEXT turn.
  * Farmhands' set-aside fires on ANY gain, including on an opponent's turn,
    and the card must be played at the start of your next turn.
  * Footpad's second ability is a GAME rule: every player who gains a card in
    an Action phase draws one, whether or not they own a Footpad.
  * Young Witch's Bane is a setup-chosen 11th Supply pile; "Bane" is not a
    type, and the reveal happens AFTER the attacker's draw-and-discard.
  * Ferryman's extra pile is outside the Supply, so it is unbuyable and cannot
    be reached by any other gain.
"""

import pytest

from games.dontminion import engine

A, B, C = "alice", "bob", "carol"

KB = ["Butcher", "Farmhands", "Farrier", "Footpad", "Herald",
      "Horn of Plenty", "Infirmary", "Jester", "Journeyman", "Stonemason"]
# a plain board with none of this set's setup cards on it
KPLAIN = ["Village", "Smithy", "Moat", "Throne Room", "Market", "Festival",
          "Cellar", "Militia", "Workshop", "Laboratory"]
# Farmhands WITHOUT Footpad. With both on the board every gain triggers two
# abilities and the ability pool (correctly) asks which resolves first, which
# would make each Farmhands test a test of the pool instead.
KFARM = ["Farmhands", "Village", "Smithy", "Moat", "Market", "Festival",
         "Cellar", "Militia", "Workshop", "Laboratory"]
# Jester WITHOUT Footpad, for the same reason plus a sharper one: Footpad's
# rule makes the cursed player DRAW, and on a short deck that draw reshuffles
# the discard pile — so the card Jester just discarded is no longer there to
# assert on. That is correct behaviour, and it is not what these tests are
# about.
KJEST = ["Jester", "Village", "Smithy", "Moat", "Market", "Festival",
         "Cellar", "Militia", "Workshop", "Laboratory"]


def fresh(players=(A, B), seed=42, kingdom=tuple(KB)):
    return engine.new_game(list(players), ["base"], seed=seed,
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


def buy(g, pid, card):
    return mv(g, pid, {"type": "buy", "card": card})


def to_buy(g, coins=0):
    g["phase"] = "buy"
    g["coins"] = coins


# ── COFFERS (the kernel system) ───────────────────────────────────────────────

def test_spending_a_coffers_gives_a_dollar_and_removes_the_token():
    g = fresh()
    g["coffers"][A] = 3
    ok, err = mv(g, A, {"type": "spend", "what": "coffers", "n": 2})
    assert ok, err
    assert g["coins"] == 2 and g["coffers"][A] == 1


def test_coffers_are_spendable_in_either_phase():
    """The 2022 rules change: "Coffers tokens can be spent at any time during
    your turn" — before, only in the first part of the Buy phase."""
    g = fresh()
    g["coffers"][A] = 2
    assert g["phase"] == "action"
    assert {"type": "spend", "what": "coffers", "n": 1} in engine.legal_moves(g, A)
    assert mv(g, A, {"type": "spend", "what": "coffers", "n": 1})[0]
    to_buy(g, coins=g["coins"])
    assert {"type": "spend", "what": "coffers", "n": 1} in engine.legal_moves(g, A)
    assert mv(g, A, {"type": "spend", "what": "coffers", "n": 1})[0]
    assert g["coins"] == 2


def test_you_cannot_spend_more_coffers_than_you_have_or_none_at_all():
    g = fresh()
    g["coffers"][A] = 1
    assert mv(g, A, {"type": "spend", "what": "coffers", "n": 2})[0] is False
    assert mv(g, A, {"type": "spend", "what": "coffers", "n": 0})[0] is False
    assert mv(g, A, {"type": "spend", "what": "coffers", "n": -1})[0] is False
    assert g["coffers"][A] == 1
    g["coffers"][A] = 0
    ok, err = mv(g, A, {"type": "spend", "what": "coffers", "n": 1})
    assert not ok and err == "nothing to spend"


def test_you_cannot_spend_another_players_coffers_or_on_their_turn():
    g = fresh()
    g["coffers"][B] = 5
    assert engine.spendable(g, B) == {}
    assert mv(g, B, {"type": "spend", "what": "coffers", "n": 1})[0] is False
    assert g["coffers"][B] == 5


def test_an_unknown_spendable_is_refused():
    g = fresh()
    g["coffers"][A] = 2
    ok, err = mv(g, A, {"type": "spend", "what": "villagers", "n": 1})
    assert not ok and err == "nothing to spend"


def test_coffers_survive_the_turn_unlike_the_per_turn_pools():
    g = fresh()
    g["coffers"][A] = 2
    give_hand(g, A, [])
    assert mv(g, A, {"type": "end_phase"})[0]      # action -> buy
    assert mv(g, A, {"type": "end_phase"})[0]      # buy -> clean-up
    assert g["turn"] == B
    assert g["coffers"][A] == 2


def test_a_coffers_earned_off_turn_is_KEPT_where_a_coin_would_evaporate():
    """Coffers are a MAT, so the "empty pools on another player's turn" rule
    does not apply — routing them through _grant would silently eat them."""
    g = fresh()
    g["turn"] = B
    before = g["coffers"][A]
    engine.add_coffers(g, 2, A)
    assert g["coffers"][A] == before + 2
    engine.add_coins(g, 2, A)                      # the control
    assert g["coins"] == 0


def test_the_spend_move_is_not_offered_while_a_decision_is_open():
    g = fresh(kingdom=KPLAIN)
    g["coffers"][A] = 3
    give_hand(g, A, ["Cellar", "Copper"])
    assert play(g, A, "Cellar")[0]
    assert g["pending"], "Cellar opens a discard choice"
    assert engine.spendable(g, A) == {}
    ok, err = mv(g, A, {"type": "spend", "what": "coffers", "n": 1})
    assert not ok


def test_coffers_are_public_table_state():
    g = fresh()
    g["coffers"][A] = 4
    for viewer in (A, B, None):
        assert engine.player_view(g, viewer)["coffers"][A] == 4


# ── OVERPAY (the kernel system) ──────────────────────────────────────────────

def test_buying_an_overpay_card_with_money_left_asks_how_much():
    g = fresh()
    to_buy(g, coins=5)
    assert buy(g, A, "Farrier")[0]                 # $2, leaving $3
    f = frame(g)
    assert f["card"] == "Farrier" and f["kind"] == "choose_option"
    assert [o["id"] for o in f["constraint"]["options"]] == ["0", "1", "2", "3"]
    assert f["constraint"]["options"][0]["label"] == "Don't overpay"
    assert decide(g, A, ids=["2"])[0]
    assert g["coins"] == 1                         # 5 - 2 cost - 2 overpaid
    assert "Farrier" in g["seats"][A]["discard"]


def test_declining_to_overpay_costs_nothing():
    g = fresh()
    to_buy(g, coins=5)
    assert buy(g, A, "Farrier")[0]
    assert decide(g, A, ids=["0"])[0]
    assert g["coins"] == 3
    assert g["turn_ctx"]["end_draw"] == 0


def test_no_overpay_prompt_when_the_card_takes_your_last_coin():
    """"You can't overpay $0" — with nothing left there is nothing to ask."""
    g = fresh()
    to_buy(g, coins=2)
    assert buy(g, A, "Farrier")[0]
    assert g["pending"] == []
    assert g["coins"] == 0


def test_a_plain_card_never_asks():
    g = fresh()
    to_buy(g, coins=8)
    assert buy(g, A, "Gold")[0]
    assert g["pending"] == []
    assert g["coins"] == 2


def test_an_ability_reading_an_overpay_cards_cost_ignores_the_plus():
    """"For any ability that refers to a card's cost, ignore the +.\""""
    g = fresh()
    assert engine.cost(g, "Farrier") == 2
    assert engine.cost_eq(g, "Farrier", 2) and engine.cost_le(g, "Farrier", 2)
    assert engine.cost(g, "Stonemason") == 2 and engine.cost(g, "Infirmary") == 3
    assert engine.cost(g, "Herald") == 4


def test_gaining_an_overpay_card_without_buying_it_gives_no_overpay():
    g = fresh(kingdom=["Farrier", "Workshop"] + KPLAIN[:8])
    give_hand(g, A, ["Workshop"])
    assert play(g, A, "Workshop")[0]
    assert decide(g, A, pile="Farrier")[0]
    assert g["pending"] == []
    assert g["turn_ctx"]["end_draw"] == 0


# --- Farrier -----------------------------------------------------------------

def test_farrier_is_a_cantrip_with_a_buy():
    g = fresh()
    give_hand(g, A, ["Farrier"])
    give_deck(g, A, ["Gold"])
    assert play(g, A, "Farrier")[0]
    assert "Gold" in g["seats"][A]["hand"]
    assert g["actions"] == 1 and g["buys"] == 2


def test_farriers_overpay_draws_at_the_END_of_the_turn_after_the_new_hand():
    g = fresh()
    to_buy(g, coins=5)
    give_deck(g, A, ["Gold"] * 12)
    give_hand(g, A, [])
    assert buy(g, A, "Farrier")[0]
    assert decide(g, A, ids=["2"])[0]
    assert g["turn_ctx"]["end_draw"] == 2
    assert mv(g, A, {"type": "end_phase"})[0]
    assert len(g["seats"][A]["hand"]) == 7, "5 for the new hand, then 2 more"


def test_farriers_end_of_turn_draw_does_not_leak_into_the_next_turn():
    g = fresh()
    to_buy(g, coins=4)
    give_deck(g, A, ["Gold"] * 20)
    give_hand(g, A, [])
    assert buy(g, A, "Farrier")[0]
    assert decide(g, A, ids=["2"])[0]
    assert mv(g, A, {"type": "end_phase"})[0]      # A's turn ends: 5 + 2
    assert len(g["seats"][A]["hand"]) == 7
    assert g["turn_ctx"]["end_draw"] == 0
    give_hand(g, B, [])
    assert mv(g, B, {"type": "end_phase"})[0]
    assert len(g["seats"][B]["hand"]) == 5


# --- Herald ------------------------------------------------------------------

def test_herald_plays_a_revealed_action_and_it_is_not_optional():
    g = fresh(kingdom=KB + ["Village"])
    give_hand(g, A, ["Herald"])
    give_deck(g, A, ["Copper", "Village", "Gold"])
    assert play(g, A, "Herald")[0]
    assert "Copper" in g["seats"][A]["hand"]       # the +1 Card
    # the revealed Village is PLAYED, with no prompt
    assert "Village" in g["seats"][A]["in_play"]
    assert g["actions"] == 3                       # 1 -1 +1 (Herald) +2 (Village)


def test_herald_discards_a_revealed_non_action():
    g = fresh()
    give_hand(g, A, ["Herald"])
    give_deck(g, A, ["Copper", "Estate"])
    assert play(g, A, "Herald")[0]
    assert g["seats"][A]["discard"] == ["Estate"]
    assert g["seats"][A]["aside"] == []


def test_heralds_overpay_topdecks_one_card_per_dollar():
    g = fresh()
    to_buy(g, coins=7)
    g["seats"][A]["discard"] = ["Gold", "Estate", "Curse"]
    give_deck(g, A, [])
    assert buy(g, A, "Herald")[0]                  # $4, leaving $3
    assert decide(g, A, ids=["2"])[0]
    f = frame(g)
    assert f["card"] == "Herald" and f["kind"] == "choose_cards"
    assert "Herald" in f["constraint"]["cards"], \
        "the just-gained Herald is in the discard pile and may be chosen"
    assert decide(g, A, cards=["Gold"])[0]
    assert decide(g, A, cards=["Herald"])[0]
    assert g["seats"][A]["deck"][:2] == ["Herald", "Gold"]
    assert g["pending"] == []


def test_heralds_overpay_stops_when_the_discard_pile_runs_out():
    g = fresh()
    to_buy(g, coins=9)
    g["seats"][A]["discard"] = []
    assert buy(g, A, "Herald")[0]
    assert decide(g, A, ids=["3"])[0]
    assert decide(g, A, cards=["Herald"])[0]       # only the Herald is there
    assert g["pending"] == []
    assert g["seats"][A]["deck"][0] == "Herald"


# --- Infirmary ---------------------------------------------------------------

def test_infirmary_draws_and_may_trash():
    g = fresh()
    give_hand(g, A, ["Infirmary", "Curse"])
    give_deck(g, A, ["Gold"])
    assert play(g, A, "Infirmary")[0]
    assert "Gold" in g["seats"][A]["hand"]
    assert decide(g, A, cards=["Curse"])[0]
    assert g["trash"] == ["Curse"]


def test_infirmary_may_decline_the_trash():
    g = fresh()
    give_hand(g, A, ["Infirmary", "Curse"])
    give_deck(g, A, ["Gold"])
    assert play(g, A, "Infirmary")[0]
    assert decide(g, A, cards=[])[0]
    assert g["trash"] == []


def test_infirmarys_overpay_plays_it_once_per_dollar():
    g = fresh()
    to_buy(g, coins=5)
    give_deck(g, A, ["Gold", "Silver", "Copper"])
    give_hand(g, A, [])
    assert buy(g, A, "Infirmary")[0]               # $3, leaving $2
    assert decide(g, A, ids=["2"])[0]
    # two plays: each draws, then offers a trash
    assert "Infirmary" in g["seats"][A]["in_play"]
    assert decide(g, A, cards=[])[0]
    assert decide(g, A, cards=[])[0]
    assert sorted(g["seats"][A]["hand"]) == ["Gold", "Silver"]
    assert g["pending"] == []


def test_infirmary_bought_without_overpaying_is_not_played():
    g = fresh()
    to_buy(g, coins=3)
    assert buy(g, A, "Infirmary")[0]
    assert g["pending"] == []
    assert "Infirmary" in g["seats"][A]["discard"]


# --- Stonemason --------------------------------------------------------------

def test_stonemason_trashes_one_and_gains_two_strictly_cheaper():
    g = fresh(kingdom=KB + ["Village"])
    give_hand(g, A, ["Stonemason", "Gold"])
    assert play(g, A, "Stonemason")[0]
    assert decide(g, A, cards=["Gold"])[0]         # $6
    f = frame(g)
    assert all(engine.cost(g, p) < 6 for p in f["constraint"]["piles"])
    assert "Gold" not in f["constraint"]["piles"], "'less than' is STRICT"
    assert decide(g, A, pile="Silver")[0]
    assert decide(g, A, pile="Village")[0]
    assert sorted(g["seats"][A]["discard"]) == ["Silver", "Village"]
    assert g["trash"] == ["Gold"]


def test_stonemason_trashing_a_copper_gains_nothing():
    g = fresh()
    give_hand(g, A, ["Stonemason", "Copper"])
    assert play(g, A, "Stonemason")[0]
    assert decide(g, A, cards=["Copper"])[0]       # nothing costs less than $0
    assert g["trash"] == ["Copper"]
    assert g["pending"] == []


def test_stonemasons_overpay_gains_two_actions_at_exactly_that_price():
    g = fresh(kingdom=KB + ["Village"])
    to_buy(g, coins=6)
    give_hand(g, A, [])
    assert buy(g, A, "Stonemason")[0]              # $2, leaving $4
    assert decide(g, A, ids=["3"])[0]              # exactly $3 Actions
    f = frame(g)
    assert f["card"] == "Stonemason" and f["kind"] == "choose_pile"
    for p in f["constraint"]["piles"]:
        assert engine.cost(g, p) == 3 and engine.has_type(g, p, "action")
    assert "Silver" not in f["constraint"]["piles"], "Actions only"
    assert decide(g, A, pile="Village")[0]
    assert decide(g, A, pile="Village")[0]
    assert g["seats"][A]["discard"].count("Village") == 2


def test_stonemasons_overpay_for_a_price_nothing_matches_gains_nothing():
    g = fresh(kingdom=KPLAIN + ["Stonemason"])
    to_buy(g, coins=13)
    assert buy(g, A, "Stonemason")[0]
    assert decide(g, A, ids=["11"])[0]             # no Action costs $11
    assert g["pending"] == []


# --- Butcher -----------------------------------------------------------------

def test_butcher_gives_two_coffers_and_remodels_per_coffers_spent():
    g = fresh(kingdom=KB + ["Village"])
    g["coffers"][A] = 0
    give_hand(g, A, ["Butcher", "Estate"])
    assert play(g, A, "Butcher")[0]
    assert g["coffers"][A] == 2
    assert decide(g, A, cards=["Estate"])[0]       # $2
    f = frame(g)
    assert f["card"] == "Butcher" and f["kind"] == "choose_option"
    assert [o["id"] for o in f["constraint"]["options"]] == ["0", "1", "2"]
    assert decide(g, A, ids=["2"])[0]              # $2 + 2 -> up to $4
    assert g["coffers"][A] == 0
    assert g["coins"] == 2, "spending a Coffers still pays +$1 each"
    f = frame(g)
    assert all(engine.cost(g, p) <= 4 for p in f["constraint"]["piles"])
    assert any(engine.cost(g, p) == 4 for p in f["constraint"]["piles"])
    assert decide(g, A, pile="Farmhands")[0]
    assert "Farmhands" in g["seats"][A]["discard"]
    assert g["trash"] == ["Estate"]


def test_butcher_may_trash_nothing():
    g = fresh()
    g["coffers"][A] = 0
    give_hand(g, A, ["Butcher", "Estate"])
    assert play(g, A, "Butcher")[0]
    assert decide(g, A, cards=[])[0]
    assert g["coffers"][A] == 2 and g["trash"] == []
    assert g["pending"] == []


def test_butcher_may_spend_no_coffers_at_all():
    g = fresh()
    g["coffers"][A] = 0
    give_hand(g, A, ["Butcher", "Estate"])
    assert play(g, A, "Butcher")[0]
    assert decide(g, A, cards=["Estate"])[0]
    assert decide(g, A, ids=["0"])[0]
    assert g["coffers"][A] == 2, "kept for later"
    f = frame(g)
    assert all(engine.cost(g, p) <= 2 for p in f["constraint"]["piles"])


def test_butcher_may_spend_MORE_than_the_two_it_just_gave_you():
    """"You may spend more than 2 if you had Coffers tokens from before.\""""
    g = fresh()
    g["coffers"][A] = 4
    give_hand(g, A, ["Butcher", "Estate"])
    assert play(g, A, "Butcher")[0]
    assert g["coffers"][A] == 6
    assert decide(g, A, cards=["Estate"])[0]
    f = frame(g)
    assert [o["id"] for o in f["constraint"]["options"]][-1] == "6"
    assert decide(g, A, ids=["6"])[0]              # $2 + 6 -> up to $8
    assert g["coffers"][A] == 0
    f = frame(g)
    assert "Province" in f["constraint"]["piles"]


# --- Farmhands ---------------------------------------------------------------

def test_farmhands_is_a_village_that_draws():
    g = fresh(kingdom=KFARM)
    give_hand(g, A, ["Farmhands"])
    give_deck(g, A, ["Gold"])
    assert play(g, A, "Farmhands")[0]
    assert g["actions"] == 2 and "Gold" in g["seats"][A]["hand"]


def test_gaining_farmhands_sets_a_card_aside_and_plays_it_next_turn():
    g = fresh(kingdom=KFARM)
    give_hand(g, A, ["Village", "Copper"])
    engine.gain(g, A, "Farmhands")
    engine._drive(g)
    f = frame(g)
    assert f["card"] == "Farmhands"
    assert sorted(f["constraint"]["cards"]) == ["Copper", "Village"]
    assert decide(g, A, cards=["Village"])[0]
    assert g["seats"][A]["set_aside"] == ["Village"]
    assert "Village" not in g["seats"][A]["hand"]
    # ...and at the start of A's NEXT turn it is played
    give_hand(g, A, [])
    assert mv(g, A, {"type": "end_phase"})[0]
    give_hand(g, B, [])
    assert mv(g, B, {"type": "end_phase"})[0]
    assert g["turn"] == A
    assert "Village" in g["seats"][A]["in_play"]
    assert g["seats"][A]["set_aside"] == []
    assert g["actions"] == 3                       # 1 + Village's +2


def test_farmhands_may_set_aside_a_treasure_and_plays_it_at_turn_start():
    g = fresh(kingdom=KFARM)
    give_hand(g, A, ["Gold"])
    engine.gain(g, A, "Farmhands")
    engine._drive(g)
    assert decide(g, A, cards=["Gold"])[0]
    give_hand(g, A, [])
    assert mv(g, A, {"type": "end_phase"})[0]
    give_hand(g, B, [])
    assert mv(g, B, {"type": "end_phase"})[0]
    assert "Gold" in g["seats"][A]["in_play"]
    assert g["coins"] == 3, "a Treasure played in the Action phase still pays"


def test_farmhands_gained_on_an_opponents_turn_still_sets_a_card_aside():
    """"You may also set aside a card from hand if you gain a Farmhands on an
    opponent's turn.\""""
    g = fresh(kingdom=KFARM)
    g["turn"] = B
    give_hand(g, A, ["Village" if False else "Copper"])
    engine.gain(g, A, "Farmhands")
    engine._drive(g)
    f = frame(g)
    assert f is not None and f["pid"] == A and f["card"] == "Farmhands"
    assert decide(g, A, cards=["Copper"])[0]
    assert g["seats"][A]["set_aside"] == ["Copper"]


def test_farmhands_may_decline_to_set_anything_aside():
    g = fresh(kingdom=KFARM)
    give_hand(g, A, ["Copper"])
    engine.gain(g, A, "Farmhands")
    engine._drive(g)
    assert decide(g, A, cards=[])[0]
    assert g["seats"][A]["set_aside"] == []
    assert g["seats"][A]["start_fx"] == []


def test_farmhands_offers_only_actions_and_treasures():
    g = fresh(kingdom=KFARM)
    give_hand(g, A, ["Estate", "Curse", "Copper", "Farmhands"])
    engine.gain(g, A, "Farmhands")
    engine._drive(g)
    assert sorted(frame(g)["constraint"]["cards"]) == ["Copper", "Farmhands"]


def test_a_farmhands_gained_to_hand_may_set_ITSELF_aside():
    g = fresh(kingdom=KFARM)
    give_hand(g, A, [])
    engine.gain(g, A, "Farmhands", dest="hand")
    engine._drive(g)
    assert frame(g)["constraint"]["cards"] == ["Farmhands"]
    assert decide(g, A, cards=["Farmhands"])[0]
    assert g["seats"][A]["set_aside"] == ["Farmhands"]


def test_a_set_aside_card_is_owned_but_not_in_play():
    g = fresh(kingdom=KFARM)
    give_hand(g, A, ["Copper"])
    engine.gain(g, A, "Farmhands")
    engine._drive(g)
    decide(g, A, cards=["Copper"])
    assert "Copper" in engine.owned_cards(g, A)
    assert "Copper" not in g["seats"][A]["in_play"]
    # owner-only on the wire, with a public count
    assert engine.player_view(g, A)["seats"][A]["set_aside"] == ["Copper"]
    assert "set_aside" not in engine.player_view(g, B)["seats"][A]
    assert engine.player_view(g, B)["seats"][A]["set_aside_count"] == 1


# --- Ferryman ----------------------------------------------------------------

def test_ferrymans_extra_pile_is_chosen_at_setup_and_is_not_in_the_supply():
    g = engine.new_game([A, B], ["cornucopia"], seed=7,
                        kingdom=list(KB))
    assert "Ferryman" not in g["kingdom"]          # control: not this board
    g2 = engine.new_game([A, B], ["cornucopia"], seed=7,
                         kingdom=["Ferryman"] + list(KPLAIN[:9]))
    pile = g2["ferryman_pile"]
    assert pile is not None
    assert engine.cost(g2, pile) in (3, 4)
    assert pile not in g2["supply"] and pile in g2["piles"]
    assert pile not in g2["kingdom"]


def test_gaining_a_ferryman_gains_one_from_its_extra_pile():
    g = engine.new_game([A, B], ["cornucopia"], seed=7,
                        kingdom=["Ferryman"] + list(KPLAIN[:9]))
    pile = g["ferryman_pile"]
    n = engine.pile_count(g, pile)
    engine.gain(g, A, "Ferryman")
    engine._drive(g)
    assert pile in g["seats"][A]["discard"]
    assert engine.pile_count(g, pile) == n - 1


def test_ferryman_draws_two_and_discards_one():
    g = engine.new_game([A, B], ["cornucopia"], seed=7,
                        kingdom=["Ferryman"] + list(KPLAIN[:9]))
    give_hand(g, A, ["Ferryman"])
    give_deck(g, A, ["Gold", "Silver", "Copper"])
    assert play(g, A, "Ferryman")[0]
    assert g["actions"] == 1
    f = frame(g)
    assert sorted(f["constraint"]["cards"]) == ["Gold", "Silver"]
    assert f["constraint"]["min"] == 1, "the discard is mandatory"
    assert decide(g, A, cards=["Silver"])[0]
    assert g["seats"][A]["discard"] == ["Silver"]


def test_ferrymans_pile_can_never_be_bought():
    g = engine.new_game([A, B], ["cornucopia"], seed=7,
                        kingdom=["Ferryman"] + list(KPLAIN[:9]))
    pile = g["ferryman_pile"]
    to_buy(g, coins=20)
    assert {"type": "buy", "card": pile} not in engine.legal_moves(g, A)
    ok, err = buy(g, A, pile)
    assert not ok and err == "no such pile"


# --- Footpad -----------------------------------------------------------------

def test_footpad_gives_coffers_and_discards_opponents_down_to_three():
    g = fresh(players=(A, B, C))
    g["coffers"][A] = 0
    give_hand(g, A, ["Footpad"])
    give_hand(g, B, ["Copper"] * 5)
    give_hand(g, C, ["Copper"] * 2)
    assert play(g, A, "Footpad")[0]
    assert g["coffers"][A] == 2
    f = frame(g)
    assert f["pid"] == B and f["constraint"]["min"] == 2
    assert decide(g, B, cards=["Copper", "Copper"])[0]
    assert len(g["seats"][B]["hand"]) == 3
    assert g["pending"] == [], "C is already at 2 cards"


def test_footpads_game_rule_draws_for_ANY_player_gaining_in_an_action_phase():
    """"In games with Footpad, every player who gains a card in an Action phase
    draws a card... It doesn't matter if anyone has any Footpads.\""""
    g = fresh()                                    # Footpad IS in this kingdom
    assert g["footpad_draw"] is True
    give_hand(g, A, [])
    give_deck(g, A, ["Gold", "Silver"])
    assert g["phase"] == "action"
    engine.gain(g, A, "Copper")
    engine._drive(g)
    assert "Gold" in g["seats"][A]["hand"], "nobody owns a Footpad — still draws"


def test_footpads_rule_fires_on_an_opponents_action_phase_too():
    g = fresh()
    g["turn"] = B
    give_hand(g, A, [])
    give_deck(g, A, ["Gold"])
    engine.gain(g, A, "Copper")
    engine._drive(g)
    assert "Gold" in g["seats"][A]["hand"]


def test_footpads_rule_does_not_fire_in_the_buy_phase():
    g = fresh()
    to_buy(g, coins=8)
    give_hand(g, A, [])
    give_deck(g, A, ["Gold"])
    assert buy(g, A, "Silver")[0]
    assert g["seats"][A]["hand"] == []


def test_no_footpad_in_the_kingdom_means_no_rule():
    g = fresh(kingdom=KPLAIN)
    assert g["footpad_draw"] is False
    give_hand(g, A, [])
    give_deck(g, A, ["Gold"])
    engine.gain(g, A, "Copper")
    engine._drive(g)
    assert g["seats"][A]["hand"] == []


def test_footpads_rule_draws_once_per_card_gained():
    g = fresh()
    give_hand(g, A, [])
    give_deck(g, A, ["Gold", "Silver", "Copper"])
    engine.gain(g, A, "Copper")
    engine._drive(g)
    engine.gain(g, A, "Copper")
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 2


# --- Horn of Plenty ----------------------------------------------------------

def test_horn_of_plenty_gains_up_to_the_distinct_names_in_play():
    g = fresh(kingdom=KB + ["Village"])
    g["seats"][A]["in_play"] = ["Village", "Village", "Smithy"]
    give_hand(g, A, ["Horn of Plenty"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Horn of Plenty"})[0]
    assert g["coins"] == 0, "Horn of Plenty is worth no $ itself"
    f = frame(g)
    # distinct in play: Village, Smithy, Horn of Plenty = 3
    assert all(engine.cost(g, p) <= 3 for p in f["constraint"]["piles"])
    assert any(engine.cost(g, p) == 3 for p in f["constraint"]["piles"])
    assert decide(g, A, pile="Silver")[0]
    assert "Silver" in g["seats"][A]["discard"]
    assert "Horn of Plenty" in g["seats"][A]["in_play"], "no Victory card gained"


def test_horn_of_plenty_trashes_itself_on_a_victory_card():
    g = fresh()
    g["seats"][A]["in_play"] = ["Smithy", "Village", "Market", "Festival",
                                "Laboratory", "Moat", "Cellar", "Militia"]
    give_hand(g, A, ["Horn of Plenty"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Horn of Plenty"})[0]
    assert decide(g, A, pile="Estate")[0]
    assert "Estate" in g["seats"][A]["discard"]
    assert "Horn of Plenty" in g["trash"]
    assert "Horn of Plenty" not in g["seats"][A]["in_play"]


def test_horn_of_plenty_is_manual_so_the_bulk_play_skips_it():
    from games.dontminion import effects
    assert "Horn of Plenty" in effects.MANUAL_TREASURES
    assert "Horn of Plenty" in engine.manual_treasures()


def test_horn_of_plenty_alone_can_still_gain_a_dollar_card():
    g = fresh()
    g["seats"][A]["in_play"] = []
    give_hand(g, A, ["Horn of Plenty"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Horn of Plenty"})[0]
    f = frame(g)
    assert all(engine.cost(g, p) <= 1 for p in f["constraint"]["piles"])
    assert "Copper" in f["constraint"]["piles"]


# --- Jester ------------------------------------------------------------------

def test_jester_on_a_victory_card_hands_out_a_curse():
    g = fresh(kingdom=KJEST)
    give_hand(g, A, ["Jester"])
    give_deck(g, B, ["Estate"])
    assert play(g, A, "Jester")[0]
    assert g["coins"] == 2
    assert "Estate" in g["seats"][B]["discard"]
    assert "Curse" in g["seats"][B]["discard"]
    assert g["pending"] == []


def test_jester_on_a_non_victory_lets_the_attacker_choose_who_gains_it():
    g = fresh(kingdom=KJEST)
    give_hand(g, A, ["Jester"])
    give_deck(g, B, ["Silver"])
    assert play(g, A, "Jester")[0]
    f = frame(g)
    assert f["pid"] == A, "the ATTACKER chooses"
    assert [o["id"] for o in f["constraint"]["options"]] == ["me", "them"]
    assert decide(g, A, ids=["me"])[0]
    assert "Silver" in g["seats"][A]["discard"]
    assert g["seats"][B]["discard"].count("Silver") == 1   # only the discarded one


def test_jester_can_give_the_copy_to_the_victim_instead():
    g = fresh(kingdom=KJEST)
    give_hand(g, A, ["Jester"])
    give_deck(g, B, ["Silver"])
    assert play(g, A, "Jester")[0]
    assert decide(g, A, ids=["them"])[0]
    assert g["seats"][B]["discard"].count("Silver") == 2
    assert "Silver" not in g["seats"][A]["discard"]


def test_jester_with_an_empty_deck_does_nothing_to_that_player():
    g = fresh(kingdom=KJEST)
    give_hand(g, A, ["Jester"])
    g["seats"][B]["deck"] = []
    g["seats"][B]["discard"] = []
    assert play(g, A, "Jester")[0]
    assert g["pending"] == []


def test_jester_is_blocked_by_a_moat():
    g = fresh(kingdom=KJEST)
    give_hand(g, A, ["Jester"])
    give_hand(g, B, ["Moat"])
    give_deck(g, B, ["Estate"])
    assert play(g, A, "Jester")[0]
    assert decide(g, B, ids=["react:Moat"])[0]
    assert "Curse" not in g["seats"][B]["discard"]
    assert g["coins"] == 2, "the attacker still gets the $2"


# --- Journeyman --------------------------------------------------------------

def test_journeyman_digs_for_three_cards_without_the_named_one():
    g = fresh()
    give_hand(g, A, ["Journeyman"])
    give_deck(g, A, ["Copper", "Estate", "Copper", "Silver", "Copper", "Gold"])
    assert play(g, A, "Journeyman")[0]
    f = frame(g)
    assert f["kind"] == "name_card"
    assert decide(g, A, card="Copper")[0]
    assert sorted(g["seats"][A]["hand"]) == ["Estate", "Gold", "Silver"]
    assert g["seats"][A]["discard"] == ["Copper"] * 3
    assert g["seats"][A]["aside"] == []


def test_journeyman_stops_when_the_deck_runs_out():
    g = fresh()
    give_hand(g, A, ["Journeyman"])
    g["seats"][A]["deck"] = ["Estate", "Silver"]
    g["seats"][A]["discard"] = []
    assert play(g, A, "Journeyman")[0]
    assert decide(g, A, card="Copper")[0]
    assert sorted(g["seats"][A]["hand"]) == ["Estate", "Silver"]


def test_journeyman_can_name_any_supply_pile():
    g = fresh()
    give_hand(g, A, ["Journeyman"])
    give_deck(g, A, ["Gold"] * 4)
    assert play(g, A, "Journeyman")[0]
    names = frame(g)["constraint"]["cards"]
    assert set(names) == set(g["supply"])


# --- Young Witch -------------------------------------------------------------

def _young_witch_game(seed=11):
    """Young Witch plus nine others, leaving unused $2/$3 piles for the Bane."""
    return engine.new_game(
        [A, B], ["base", "cornucopia"], seed=seed,
        kingdom=["Young Witch", "Smithy", "Market", "Festival", "Laboratory",
                 "Militia", "Mine", "Library", "Council Room", "Artisan"])


def test_young_witch_adds_a_bane_pile_to_the_supply():
    g = _young_witch_game()
    bane = g["bane"]
    assert bane is not None
    assert engine.cost(g, bane) in (2, 3)
    assert bane in g["supply"], "the Bane pile IS in the Supply"
    assert engine.is_supply_pile(g, bane)
    assert bane not in g["kingdom"], "it is the 11th pile, not one of the 10"
    assert engine.pile_count(g, bane) > 0


def test_young_witch_draws_two_discards_two_then_curses():
    g = _young_witch_game()
    give_hand(g, A, ["Young Witch", "Copper", "Estate"])
    give_deck(g, A, ["Gold", "Silver"])
    give_hand(g, B, ["Copper"])
    assert play(g, A, "Young Witch")[0]
    f = frame(g)
    assert f["pid"] == A and f["constraint"]["min"] == 2
    assert decide(g, A, cards=["Copper", "Estate"])[0]
    assert "Curse" in g["seats"][B]["discard"]


def test_revealing_the_bane_blocks_the_curse():
    g = _young_witch_game()
    bane = g["bane"]
    give_hand(g, A, ["Young Witch"])
    give_deck(g, A, ["Gold", "Silver"])
    give_hand(g, B, [bane])
    assert play(g, A, "Young Witch")[0]
    assert decide(g, A, cards=["Gold", "Silver"])[0]
    f = frame(g)
    assert f["pid"] == B and f["card"] == "Young Witch"
    assert [o["id"] for o in f["constraint"]["options"]] == ["reveal", "no"]
    assert decide(g, B, ids=["reveal"])[0]
    assert "Curse" not in g["seats"][B]["discard"]
    assert bane in g["seats"][B]["hand"], "revealed, not discarded"


def test_declining_to_reveal_the_bane_takes_the_curse():
    g = _young_witch_game()
    bane = g["bane"]
    give_hand(g, A, ["Young Witch"])
    give_deck(g, A, ["Gold", "Silver"])
    give_hand(g, B, [bane])
    assert play(g, A, "Young Witch")[0]
    assert decide(g, A, cards=["Gold", "Silver"])[0]
    assert decide(g, B, ids=["no"])[0]
    assert "Curse" in g["seats"][B]["discard"]


def test_the_bane_reveal_happens_AFTER_the_attackers_draw_and_discard():
    """Order is load-bearing: "then the other players may reveal a Bane card.
    Consequently, if a Reaction card is the Bane card, they need to have it in
    their hand at that point.\""""
    g = _young_witch_game()
    give_hand(g, A, ["Young Witch"])
    give_deck(g, A, ["Gold", "Silver"])
    give_hand(g, B, [g["bane"]])
    assert play(g, A, "Young Witch")[0]
    f = frame(g)
    assert f["pid"] == A, "the attacker discards first"
    assert f["kind"] == "choose_cards"


def test_young_witch_attacks_even_with_nothing_to_discard():
    g = _young_witch_game()
    give_hand(g, A, ["Young Witch"])
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = []
    give_hand(g, B, [])
    assert play(g, A, "Young Witch")[0]
    assert "Curse" in g["seats"][B]["discard"]


def test_bane_is_not_a_type_it_is_whichever_pile_setup_chose():
    g = _young_witch_game()
    assert "bane" not in engine.types_of(g, g["bane"])


def test_a_moat_still_blocks_young_witch_outright():
    g = engine.new_game(
        [A, B], ["base", "cornucopia"], seed=5,
        kingdom=["Young Witch", "Smithy", "Market", "Festival", "Laboratory",
                 "Militia", "Mine", "Library", "Council Room", "Moat"])
    give_hand(g, A, ["Young Witch"])
    give_deck(g, A, ["Gold", "Silver"])
    give_hand(g, B, ["Moat"])
    assert play(g, A, "Young Witch")[0]
    assert decide(g, B, ids=["react:Moat"])[0]
    assert decide(g, A, cards=["Gold", "Silver"])[0]
    assert "Curse" not in g["seats"][B]["discard"]


# --- Coronet -----------------------------------------------------------------

def _coronet_game():
    g = engine.new_game([A, B], ["base", "cornucopia"], seed=3,
                        kingdom=["Joust", "Smithy", "Village", "Market",
                                 "Festival", "Laboratory", "Militia", "Mine",
                                 "Library", "Council Room"])
    return g


def test_coronet_plays_an_action_twice():
    g = _coronet_game()
    give_hand(g, A, ["Coronet", "Smithy"])
    give_deck(g, A, ["Gold"] * 8)
    assert play(g, A, "Coronet")[0]
    f = frame(g)
    assert f["data"]["kind"] == "action"
    assert f["constraint"]["cards"] == ["Smithy"]
    assert decide(g, A, cards=["Smithy"])[0]
    assert g["seats"][A]["hand"].count("Gold") == 6, "3 + 3"
    assert g["seats"][A]["in_play"].count("Smithy") == 1


def test_coronet_then_offers_a_treasure():
    g = _coronet_game()
    give_hand(g, A, ["Coronet", "Village", "Gold"])
    give_deck(g, A, ["Silver"] * 6)
    assert play(g, A, "Coronet")[0]
    assert decide(g, A, cards=["Village"])[0]      # Action half
    f = frame(g)
    assert f["data"]["kind"] == "treasure"
    assert "Gold" in f["constraint"]["cards"]
    assert decide(g, A, cards=["Gold"])[0]
    assert g["coins"] == 6, "a Gold played twice"


def test_coronet_never_offers_another_reward():
    g = _coronet_game()
    give_hand(g, A, ["Coronet", "Courser", "Huge Turnip", "Smithy"])
    give_deck(g, A, ["Gold"] * 8)
    assert play(g, A, "Coronet")[0]
    assert frame(g)["constraint"]["cards"] == ["Smithy"], "non-Reward Actions only"
    assert decide(g, A, cards=[])[0]
    assert frame(g) is None, "no non-Reward Treasure in hand: nothing to offer"


def test_coronet_gives_no_money_of_its_own():
    g = _coronet_game()
    give_hand(g, A, ["Coronet"])
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Coronet"})[0]
    assert g["coins"] == 0


def test_coronet_is_manual_so_the_bulk_play_skips_it():
    from games.dontminion import effects
    assert "Coronet" in effects.MANUAL_TREASURES


def test_coronet_may_decline_both_halves():
    g = _coronet_game()
    give_hand(g, A, ["Coronet", "Smithy", "Gold"])
    give_deck(g, A, ["Silver"] * 6)
    assert play(g, A, "Coronet")[0]
    assert decide(g, A, cards=[])[0]
    assert decide(g, A, cards=[])[0]
    assert g["pending"] == []
    assert sorted(g["seats"][A]["hand"]) == ["Gold", "Smithy"]


def test_farmhands_and_footpad_on_one_gain_are_the_players_ordering_choice():
    """Both fire on the same gain — Farmhands' own when-gain and Footpad's game
    rule — so the ability pool asks which resolves first (compendium p23 §2).
    Worth pinning: it is also the proof that the new `from="game"` trigger
    source joins the pool like any other consumer rather than cutting ahead."""
    g = fresh()                                    # KB has BOTH cards
    assert "Farmhands" in g["kingdom"] and "Footpad" in g["kingdom"]
    give_hand(g, A, ["Copper"])
    give_deck(g, A, ["Gold"])
    engine.gain(g, A, "Farmhands")
    engine._drive(g)
    f = frame(g)
    assert f["card"] == "__abilities"
    assert sorted(o["label"] for o in f["constraint"]["options"]) == [
        "Farmhands", "Footpad"]
    # take the draw first, then the set-aside — both must still happen
    ids = [o["id"] for o in f["constraint"]["options"]
           if o["label"] == "Footpad"]
    assert decide(g, A, ids=ids)[0]
    assert "Gold" in g["seats"][A]["hand"]
    assert frame(g)["card"] == "Farmhands"
    assert decide(g, A, cards=["Copper"])[0]
    assert g["seats"][A]["set_aside"] == ["Copper"]


# ── audit findings (step 7: re-derived from the compendium, not the spec) ─────

def test_coronet_plays_an_action_in_your_BUY_phase():
    """"This lets you play an Action card in your Buy phase." Coronet is both
    an Action and a Treasure at all times, so the Buy-phase treasure play still
    offers the Action half."""
    g = _coronet_game()
    give_hand(g, A, ["Coronet", "Smithy"])
    give_deck(g, A, ["Gold"] * 8)
    to_buy(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Coronet"})[0]
    f = frame(g)
    assert f["data"]["kind"] == "action" and f["constraint"]["cards"] == ["Smithy"]
    assert decide(g, A, cards=["Smithy"])[0]
    assert g["seats"][A]["hand"].count("Gold") == 6


def test_coronet_plays_a_treasure_in_your_ACTION_phase():
    """"This card lets you play a Treasure in your Action phase.\""""
    g = _coronet_game()
    give_hand(g, A, ["Coronet", "Gold"])
    give_deck(g, A, ["Silver"] * 4)
    assert g["phase"] == "action"
    assert play(g, A, "Coronet")[0]
    # no non-Reward Action in hand, so the Action half is never offered and
    # the Treasure half comes straight up — in the ACTION phase
    f = frame(g)
    assert f["data"]["kind"] == "treasure"
    assert g["phase"] == "action", "the offer is open DURING the Action phase"
    assert decide(g, A, cards=["Gold"])[0]
    assert g["coins"] == 6
    # Coronet grants no +Action, so once its frames resolve the turn player has
    # no Actions left and the kernel auto-advances — that is the phase machine
    # doing its job, not the Treasure being played in the Buy phase.
    assert g["seats"][A]["in_play"].count("Gold") == 1


def test_young_witch_still_works_when_no_pile_can_be_the_bane():
    """The Bane comes from the kingdom cards this game did NOT deal. With none
    eligible we play without one — a legal board where the attack simply cannot
    be blocked — rather than re-dealing the whole kingdom."""
    g = engine.new_game([A, B], ["cornucopia"], seed=3,
                        kingdom=["Young Witch", "Butcher", "Baker", "Carnival",
                                 "Ferryman", "Footpad", "Herald",
                                 "Horn of Plenty", "Jester", "Journeyman"])
    # every remaining C&G pile costs $2-$3, so a Bane IS found here; the point
    # of the assertion is that whichever way it goes the game is playable
    give_hand(g, A, ["Young Witch"])
    give_deck(g, A, ["Gold", "Silver"])
    give_hand(g, B, [])
    assert play(g, A, "Young Witch")[0]
    assert decide(g, A, cards=["Gold", "Silver"])[0]
    assert "Curse" in g["seats"][B]["discard"]


def test_a_bane_pile_may_itself_be_an_overpay_card():
    """Nothing stops setup choosing Farrier or Stonemason as the Bane — both
    cost $2. Buying one then has to run the overpay prompt off a pile that is
    in the Supply but not in the dealt 10."""
    g = engine.new_game([A, B], ["cornucopia"], seed=3,
                        kingdom=["Young Witch", "Butcher", "Baker", "Carnival",
                                 "Ferryman", "Footpad", "Herald",
                                 "Horn of Plenty", "Jester", "Journeyman"])
    bane = g["bane"]
    # ASSERTED, not skipped-around: this seed deals Farrier as the Bane, and if
    # the deal ever changes this fails loudly rather than quietly testing
    # nothing (the repo has zero conditional skips).
    assert bane == "Farrier" and bane not in g["kingdom"]
    assert engine.cards_overpay(bane)
    to_buy(g, coins=8)
    assert buy(g, A, bane)[0]
    f = frame(g)
    assert f is not None and f["card"] == bane, "the overpay prompt still opens"
    assert decide(g, A, ids=["3"])[0]
    assert g["turn_ctx"]["end_draw"] == 3
    assert bane in g["seats"][A]["discard"]


def test_the_new_alt_vp_cards_reach_the_real_scoring_path():
    """_vp_of is not the API — score_game and the live vp map are. A computed
    VP rule that only worked in _vp_of would read 0 on the scoreboard."""
    g = fresh(kingdom=["Fairgrounds"] + KPLAIN[:9])
    seat = g["seats"][A]
    seat["deck"], seat["hand"], seat["discard"], seat["in_play"] = [], [], [], []
    seat["deck"] = ["Fairgrounds", "Copper", "Silver", "Gold", "Estate"]
    engine._post_move(g)
    assert g["vp"][A] == 3                         # 2 (Fairgrounds) + 1 (Estate)
    assert engine.score_game(g)[A]["vp"] == 3
    seat["deck"] = ["Demesne", "Gold", "Gold"]
    engine._post_move(g)
    assert g["vp"][A] == 2
    assert engine.score_game(g)[A]["vp"] == 2


def test_every_cornucopia_card_has_an_effect_or_is_pure_data():
    """A card with no EFFECTS entry is silently a blank when played. Only pure
    Victory cards may have none (the handlers and cards.py cover those)."""
    from games.dontminion import effects
    from games.dontminion.cards import CARDS, KINGDOM, REWARDS
    for name in list(KINGDOM["cornucopia"]) + list(REWARDS):
        types = CARDS[name]["types"]
        playable = "action" in types or "treasure" in types
        if playable:
            assert name in effects.EFFECTS, f"{name} is playable but does nothing"
        else:
            assert name not in effects.EFFECTS, f"{name} is pure data"


def test_every_overpay_card_registers_a_when_gain_ability():
    """The `$N+` cost is only half of an overpay card: the money it takes has
    to buy something, and since 2022 that something is a when-gain ability. A
    cost flag with no trigger would take the player's money and do nothing."""
    from games.dontminion import effects
    from games.dontminion.cards import CARDS, KINGDOM
    overpay = [n for n in KINGDOM["cornucopia"] if CARDS[n].get("overpay")]
    assert sorted(overpay) == ["Farrier", "Herald", "Infirmary", "Stonemason"]
    for name in overpay:
        specs = effects.TRIGGERS.get(name, [])
        assert any(s["on"] == "gain" and s.get("from") == "self" for s in specs), \
            f"{name} costs $N+ but nothing consumes the overpay"
