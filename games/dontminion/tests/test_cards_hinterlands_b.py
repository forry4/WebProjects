"""Hinterlands batch B rules tests: Berserker, Fool's Gold, Jack of All Trades,
Nomads, Scheme, Souk, Spice Merchant, Stables, Trader, Trail, Tunnel, Weaver.

Idioms (see test_engine.py / test_cards_seaside_b.py): positions are arranged by
mutating the game dict directly; give_hand breaks conservation on purpose. The
engine AUTO-ADVANCES action -> buy once the turn player has no Actions left or
no Action card in hand. Direct engine.gain/trash/discard calls from a test must
be followed by engine._drive(g) — the triggers they fire are parked as auto
frames until something drives them.

"""

import pytest

from games.dontminion import engine

A, B, C = "alice", "bob", "carol"



# Pinned kingdom = exactly this batch's 12 cards (the forced-kingdom test seam).
KB = ["Berserker", "Fool's Gold", "Jack of All Trades", "Nomads", "Scheme",
      "Souk", "Spice Merchant", "Stables", "Trader", "Trail", "Tunnel",
      "Weaver"]
# kingdom= mixes sets freely: the attacks/reactions/trashers these cards have to
# interact with, Bridge for the cost checks, Caravan as the Duration fixture.
KHB = KB + ["Militia", "Moat", "Chapel", "Cellar", "Village", "Throne Room",
            "Watchtower", "Bishop", "Bridge", "Caravan"]

EXPS = ["base", "intrigue", "seaside", "prosperity", "hinterlands"]


def fresh(players=(A, B), seed=42, kingdom=None, charlatan=False):
    k = list(kingdom or KHB)
    if charlatan:
        k = k + ["Charlatan"]
    g = engine.new_game(list(players), EXPS, seed=seed, kingdom=k)
    # Platinum/Colony ride on a random Prosperity proportion; pin them off so
    # the pile census and the end-game condition are the same in every test.
    g["colony"] = False
    g["supply"].pop("Platinum", None)
    g["supply"].pop("Colony", None)
    return g


def give_hand(g, pid, cs):
    g["seats"][pid]["hand"] = list(cs)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def play(g, pid, card):
    return mv(g, pid, {"type": "play_action", "card": card})


def decide(g, pid, **payload):
    return mv(g, pid, {"type": "decision", **payload})


def opts(g):
    return [o["id"] for o in g["pending"][-1]["constraint"]["options"]]


def end(g, pid):
    return mv(g, pid, {"type": "end_phase"})


def to_buy(g, pid):
    """Reach the buy phase — the engine may already have AUTO-ADVANCED there."""
    if g["phase"] == "action":
        assert end(g, pid)[0]
    assert g["phase"] == "buy"


def end_turn(g, pid):
    """End pid's turn from wherever they are (action or buy phase)."""
    to_buy(g, pid)
    assert end(g, pid)[0]


# ==========================================================================
# Stables
# ==========================================================================

def test_stables_declining_the_discard_gives_nothing():
    """'DO X FOR' (p48): no Treasure discarded => no +3 Cards, no +1 Action."""
    g = fresh()
    give_hand(g, A, ["Stables", "Copper", "Estate"])
    g["seats"][A]["deck"] = ["Gold"] * 5
    assert play(g, A, "Stables")[0]
    assert g["pending_kind"] == "choose_cards"
    assert g["pending"][-1]["constraint"]["cards"] == ["Copper"]   # treasures only
    assert decide(g, A, cards=[])[0]
    assert g["seats"][A]["hand"] == ["Copper", "Estate"]
    assert g["actions"] == 0


def test_stables_discarding_a_treasure_draws_three_and_gives_an_action():
    g = fresh()
    give_hand(g, A, ["Stables", "Copper"])
    g["seats"][A]["deck"] = ["Gold", "Gold", "Gold", "Estate"]
    assert play(g, A, "Stables")[0]
    assert decide(g, A, cards=["Copper"])[0]
    assert g["seats"][A]["hand"] == ["Gold", "Gold", "Gold"]
    assert g["seats"][A]["discard"] == ["Copper"]
    assert g["actions"] == 1


def test_stables_with_no_treasure_in_hand_pushes_no_frame():
    g = fresh()
    give_hand(g, A, ["Stables", "Estate"])
    assert play(g, A, "Stables")[0]
    assert g["pending_pid"] is None
    assert g["seats"][A]["hand"] == ["Estate"]


def test_stables_discarded_treasure_can_be_reshuffled_back_in():
    """DISCARD, THEN GET FROM DECK (p48): 'you could end up getting some or all
    of the cards you discarded'."""
    g = fresh()
    give_hand(g, A, ["Stables", "Gold"])
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = []
    assert play(g, A, "Stables")[0]
    assert decide(g, A, cards=["Gold"])[0]
    # the only card anywhere to draw from was the Gold we just discarded
    assert g["seats"][A]["hand"] == ["Gold"]


def test_stables_offers_a_charlatan_curse_as_a_treasure():
    """Charlatan's game-wide rule reaches card code only through has_type."""
    g = fresh(charlatan=True)
    give_hand(g, A, ["Stables", "Curse"])
    assert play(g, A, "Stables")[0]
    assert g["pending"][-1]["constraint"]["cards"] == ["Curse"]


# ==========================================================================
# Spice Merchant
# ==========================================================================

def test_spice_merchant_declining_the_trash_offers_no_mode():
    """'DO X TO' (p48): no trash => the two options are never offered."""
    g = fresh()
    give_hand(g, A, ["Spice Merchant", "Silver", "Estate"])
    assert play(g, A, "Spice Merchant")[0]
    assert g["pending"][-1]["constraint"]["cards"] == ["Silver"]
    assert decide(g, A, cards=[])[0]
    assert g["pending_pid"] is None
    assert g["trash"] == []


def test_spice_merchant_cards_mode_draws_two_and_gives_an_action():
    g = fresh()
    give_hand(g, A, ["Spice Merchant", "Silver"])
    g["seats"][A]["deck"] = ["Gold", "Gold", "Estate"]
    assert play(g, A, "Spice Merchant")[0]
    assert decide(g, A, cards=["Silver"])[0]
    assert g["trash"] == ["Silver"]
    assert opts(g) == ["cards", "coins"]
    assert decide(g, A, ids=["cards"])[0]
    assert g["seats"][A]["hand"] == ["Gold", "Gold"]
    assert g["actions"] == 1


def test_spice_merchant_coins_mode_gives_a_buy_and_two_coins():
    g = fresh()
    give_hand(g, A, ["Spice Merchant", "Copper"])
    assert play(g, A, "Spice Merchant")[0]
    assert decide(g, A, cards=["Copper"])[0]
    assert decide(g, A, ids=["coins"])[0]
    assert (g["buys"], g["coins"], g["actions"]) == (2, 2, 0)


def test_spice_merchant_with_an_empty_hand_pushes_no_frame():
    g = fresh()
    give_hand(g, A, ["Spice Merchant"])
    assert play(g, A, "Spice Merchant")[0]
    assert g["pending_pid"] is None


# ==========================================================================
# Jack of All Trades
# ==========================================================================

def test_jack_gains_a_silver_discards_the_top_card_and_draws_to_five():
    g = fresh()
    give_hand(g, A, ["Jack of All Trades", "Estate"])
    g["seats"][A]["deck"] = ["Copper", "Gold", "Gold", "Gold", "Gold", "Gold"]
    assert play(g, A, "Jack of All Trades")[0]
    assert g["seats"][A]["discard"] == ["Silver"]
    assert g["pending_kind"] == "choose_option"
    assert decide(g, A, ids=["discard"])[0]        # ditch the Copper
    assert "Copper" in g["seats"][A]["discard"]
    assert g["seats"][A]["aside"] == []
    assert len(g["seats"][A]["hand"]) == 5         # drew 4 Golds onto the Estate
    assert g["pending_kind"] == "choose_cards"     # the optional trash
    assert decide(g, A, cards=["Estate"])[0]
    assert g["trash"] == ["Estate"]


def test_jack_keeping_the_top_card_leaves_it_on_the_deck():
    g = fresh()
    give_hand(g, A, ["Jack of All Trades"])
    g["seats"][A]["deck"] = ["Duchy", "Copper", "Copper", "Copper", "Copper", "Copper"]
    assert play(g, A, "Jack of All Trades")[0]
    assert decide(g, A, ids=["keep"])[0]
    assert g["seats"][A]["hand"][0] == "Duchy"     # drawn first, still on top
    assert g["seats"][A]["aside"] == []


def test_jack_gains_tunnels_gold_before_drawing_to_five():
    """TRIGGERED ABILITY (p54), verbatim: 'if you play Jack of All Trades and
    discard a Tunnel from the top of your deck, you gain the Gold from Tunnel's
    when-discard BEFORE drawing to five cards in hand.'"""
    g = fresh()
    give_hand(g, A, ["Jack of All Trades"])
    g["seats"][A]["deck"] = ["Tunnel"] + ["Copper"] * 5
    assert play(g, A, "Jack of All Trades")[0]
    assert decide(g, A, ids=["discard"])[0]
    # Tunnel's window is open and the hand is still EMPTY: the draw waits
    assert g["pending"][-1]["card"] == "Tunnel"
    assert g["seats"][A]["hand"] == []
    assert decide(g, A, ids=["reveal"])[0]
    assert "Gold" in g["seats"][A]["discard"]
    assert len(g["seats"][A]["hand"]) == 5


def test_jack_with_five_cards_already_draws_none():
    g = fresh()
    give_hand(g, A, ["Jack of All Trades"] + ["Estate"] * 5)
    g["seats"][A]["deck"] = ["Gold"] * 5
    assert play(g, A, "Jack of All Trades")[0]
    assert decide(g, A, ids=["keep"])[0]
    assert g["seats"][A]["hand"] == ["Estate"] * 5   # never discards down
    assert decide(g, A, cards=[])[0]


def test_jack_trash_offer_excludes_treasures_including_a_charlatan_curse():
    g = fresh(charlatan=True)
    give_hand(g, A, ["Jack of All Trades", "Curse", "Estate", "Copper"])
    g["seats"][A]["deck"] = ["Gold"] * 5
    assert play(g, A, "Jack of All Trades")[0]
    assert decide(g, A, ids=["keep"])[0]
    # Curse is a Treasure in a Charlatan game, so only the Estate is offered
    assert g["pending"][-1]["constraint"]["cards"] == ["Estate"]


def test_jack_with_no_cards_to_look_at_skips_the_look():
    g = fresh()
    g["supply"]["Silver"] = 0          # else the gained Silver reshuffles in
    give_hand(g, A, ["Jack of All Trades"] + ["Estate"] * 5)
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = []
    assert play(g, A, "Jack of All Trades")[0]
    assert g["seats"][A]["aside"] == []
    assert g["pending_kind"] == "choose_cards"       # straight to the trash offer


def test_jack_with_an_empty_silver_pile_still_does_everything_else():
    g = fresh()
    g["supply"]["Silver"] = 0
    give_hand(g, A, ["Jack of All Trades"])
    g["seats"][A]["deck"] = ["Copper"] * 6
    assert play(g, A, "Jack of All Trades")[0]
    assert g["seats"][A]["discard"] == []
    assert decide(g, A, ids=["keep"])[0]
    assert len(g["seats"][A]["hand"]) == 5


# ==========================================================================
# Tunnel
# ==========================================================================

def test_tunnel_militia_batch_reveals_after_the_whole_hand_has_moved():
    """Tunnel (p159): 'If you have a Tunnel and a Watchtower in hand when your
    opponent plays Minion and makes you discard your hand, you can reveal
    Tunnel to gain a Gold after all cards are discarded, but at this time you no
    longer have Watchtower in your hand, so you can't use it.'"""
    g = fresh()
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Tunnel", "Watchtower", "Copper", "Copper", "Estate"])
    assert play(g, A, "Militia")[0]
    assert g["pending_pid"] == B and g["pending_kind"] == "choose_cards"
    assert decide(g, B, cards=["Tunnel", "Watchtower"])[0]
    # both left the hand before the Tunnel window opened
    assert g["seats"][B]["hand"] == ["Copper", "Copper", "Estate"]
    assert g["pending"][-1]["card"] == "Tunnel"
    assert decide(g, B, ids=["reveal"])[0]
    assert g["seats"][B]["discard"].count("Gold") == 1
    assert g["pending_pid"] is None            # no Watchtower window: it's gone


def test_tunnel_two_discarded_at_once_each_get_their_own_prompt():
    g = fresh()
    give_hand(g, A, ["Cellar", "Tunnel", "Tunnel"])
    g["seats"][A]["deck"] = ["Copper"] * 5
    assert play(g, A, "Cellar")[0]
    assert decide(g, A, cards=["Tunnel", "Tunnel"])[0]
    assert g["pending"][-1]["card"] == "Tunnel"
    assert decide(g, A, ids=["reveal"])[0]
    assert g["pending"][-1]["card"] == "Tunnel"
    assert decide(g, A, ids=["reveal"])[0]
    assert g["seats"][A]["discard"].count("Gold") == 2


def test_tunnel_declining_gains_nothing():
    g = fresh()
    give_hand(g, A, ["Cellar", "Tunnel"])
    g["seats"][A]["deck"] = ["Copper"] * 5
    assert play(g, A, "Cellar")[0]
    assert decide(g, A, cards=["Tunnel"])[0]
    assert decide(g, A, ids=["decline"])[0]
    assert "Gold" not in g["seats"][A]["discard"]
    assert g["supply"]["Gold"] == 30


def test_tunnel_is_not_triggered_by_a_cleanup_discard():
    """WHEN YOU DISCARD THIS (p56): 'When you discard cards during Clean-up, it
    doesn't trigger.'"""
    g = fresh()
    give_hand(g, A, ["Tunnel", "Copper", "Copper"])
    g["seats"][A]["deck"] = ["Estate"] * 10
    end_turn(g, A)
    assert g["pending_pid"] is None
    assert "Gold" not in g["seats"][A]["discard"]


def test_tunnel_revealed_for_another_reason_gains_nothing():
    """'You don't gain a Gold if Tunnel is revealed for some other reason.'"""
    g = fresh()
    give_hand(g, A, ["Tunnel", "Copper"])
    engine.reveal(g, A, ["Tunnel"], "hand")
    engine._drive(g)
    assert g["pending_pid"] is None
    assert g["supply"]["Gold"] == 30


def test_tunnel_gained_into_the_discard_pile_does_not_trigger():
    """'not when you put it into your discard pile through gaining it'."""
    g = fresh()
    assert engine.gain(g, A, "Tunnel")
    engine._drive(g)
    assert g["pending_pid"] is None
    assert g["supply"]["Gold"] == 30


# ==========================================================================
# Nomads
# ==========================================================================

def test_nomads_play_gives_a_buy_and_two_coins():
    g = fresh()
    give_hand(g, A, ["Nomads"])
    assert play(g, A, "Nomads")[0]
    assert (g["buys"], g["coins"]) == (2, 2)


def test_nomads_buying_it_pays_two_coins_back_for_the_second_buy():
    g = fresh()
    give_hand(g, A, [])
    to_buy(g, A)
    g["coins"], g["buys"] = 4, 2
    assert mv(g, A, {"type": "buy", "card": "Nomads"})[0]
    assert g["coins"] == 2                    # 4 - 4 + 2 from the when-gain
    assert mv(g, A, {"type": "buy", "card": "Estate"})[0]


def test_nomads_trashing_your_own_copy_gives_two_coins():
    g = fresh()
    give_hand(g, A, ["Chapel", "Nomads"])
    assert play(g, A, "Chapel")[0]
    assert decide(g, A, cards=["Nomads"])[0]
    assert g["coins"] == 2
    assert g["trash"] == ["Nomads"]


def test_nomads_gained_then_trashed_pays_twice():
    g = fresh()
    give_hand(g, A, ["Chapel"])
    assert engine.gain(g, A, "Nomads", dest="hand")
    engine._drive(g)
    assert g["coins"] == 2
    assert play(g, A, "Chapel")[0]
    assert decide(g, A, cards=["Nomads"])[0]
    assert g["coins"] == 4                    # both triggers fire independently


def test_nomads_trashed_on_an_opponents_turn_leaks_nothing_to_the_turn_player():
    """EFFECTS WHEN IT'S NOT YOUR TURN (p48): the +$2 belongs to whoever trashed
    it, and 'on another player's turn you always start with empty pools' — so it
    evaporates. It must NEVER land in the attacker's money pool."""
    g = fresh()
    give_hand(g, A, ["Bishop", "Estate"])
    give_hand(g, B, ["Nomads", "Copper"])
    assert play(g, A, "Bishop")[0]            # +$1 +1VP, then each opponent may trash
    assert g["pending_pid"] == A              # A's own mandatory trash first
    assert decide(g, A, cards=["Estate"])[0]
    coins_before = g["coins"]
    assert g["pending_pid"] == B
    assert decide(g, B, cards=["Nomads"])[0]
    assert g["trash"].count("Nomads") == 1
    assert g["coins"] == coins_before          # the turn player got nothing
    assert any(e["event"] == "off_turn_bonus" for e in g["log"])


# ==========================================================================
# Souk
# ==========================================================================

def test_souk_deducts_one_coin_per_card_in_hand():
    g = fresh()
    give_hand(g, A, ["Souk", "Copper", "Copper", "Estate"])
    assert play(g, A, "Souk")[0]               # Souk leaves the hand first
    assert (g["buys"], g["coins"]) == (2, 4)   # 7 - 3 cards left in hand


def test_souk_money_pool_floors_at_zero():
    """Souk (p148): 'Your money pool can never go below $0.'"""
    g = fresh()
    give_hand(g, A, ["Souk"] + ["Copper"] * 9)
    assert play(g, A, "Souk")[0]
    assert g["coins"] == 0                     # 0 + 7 - 9, clamped


def test_souk_can_deduct_more_than_it_gave():
    """'if you had any $ before playing Souk, you might lose more than $7'."""
    g = fresh()
    give_hand(g, A, ["Souk"] + ["Copper"] * 8)
    g["coins"] = 4
    assert play(g, A, "Souk")[0]
    assert g["coins"] == 3                     # 4 + 7 - 8


def test_souk_is_variable_production_read_at_resolution():
    """VARIABLE PRODUCTION (p56): 'the amount doesn't change later in the turn'."""
    g = fresh()
    give_hand(g, A, ["Souk", "Estate"])
    g["seats"][A]["deck"] = ["Copper"] * 6
    assert play(g, A, "Souk")[0]
    assert g["coins"] == 6                     # 7 - 1 (the Estate)
    engine.draw(g, A, 4)                       # the hand grows later in the turn
    assert g["coins"] == 6


def test_souk_on_gain_trashes_up_to_two_as_one_event():
    g = fresh()
    give_hand(g, A, ["Copper", "Estate", "Curse"])
    assert engine.gain(g, A, "Souk")
    engine._drive(g)
    assert g["pending"][-1]["constraint"]["max"] == 2
    assert decide(g, A, cards=["Estate", "Curse"])[0]
    assert sorted(g["trash"]) == ["Curse", "Estate"]
    assert [e for e in g["log"] if e["event"] == "trash"][-1]["cards"] \
        == ["Estate", "Curse"]                 # ONE trash event, not two


def test_souk_on_gain_trash_is_optional():
    g = fresh()
    give_hand(g, A, ["Copper"])
    assert engine.gain(g, A, "Souk")
    engine._drive(g)
    assert decide(g, A, cards=[])[0]
    assert g["trash"] == []


def test_souk_on_gain_with_an_empty_hand_pushes_no_frame():
    g = fresh()
    give_hand(g, A, [])
    assert engine.gain(g, A, "Souk")
    engine._drive(g)
    assert g["pending_pid"] is None


# ==========================================================================
# Fool's Gold
# ==========================================================================

def test_fools_gold_is_one_then_four_and_the_counter_resets_next_turn():
    g = fresh()
    give_hand(g, A, ["Fool's Gold", "Fool's Gold", "Fool's Gold"])
    to_buy(g, A)
    assert mv(g, A, {"type": "play_treasure", "card": "Fool's Gold"})[0]
    assert g["coins"] == 1
    assert mv(g, A, {"type": "play_treasure", "card": "Fool's Gold"})[0]
    assert g["coins"] == 5
    assert mv(g, A, {"type": "play_treasure", "card": "Fool's Gold"})[0]
    assert g["coins"] == 9
    assert end(g, A)[0]
    give_hand(g, B, [])
    end_turn(g, B)
    give_hand(g, A, ["Fool's Gold"])
    to_buy(g, A)
    assert mv(g, A, {"type": "play_treasure", "card": "Fool's Gold"})[0]
    assert g["coins"] == 1                      # a fresh turn_ctx counter


def test_fools_gold_autoplays_inside_the_bulk_play():
    g = fresh()
    give_hand(g, A, ["Copper", "Fool's Gold", "Fool's Gold"])
    to_buy(g, A)
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert g["coins"] == 6                      # 1 + 1 + 4
    assert g["pending_pid"] is None
    assert mv(g, A, {"type": "undo_turn"})[0]   # the bulk play stays undoable
    assert g["coins"] == 0
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Fool's Gold", "Fool's Gold"]


def test_fools_gold_reacts_to_an_opponents_province_but_not_your_own():
    g = fresh()
    give_hand(g, A, ["Fool's Gold"])
    give_hand(g, B, ["Fool's Gold"])
    to_buy(g, A)
    g["coins"] = 8
    assert mv(g, A, {"type": "buy", "card": "Province"})[0]
    # the GAINER is never offered; B is
    assert g["pending_pid"] == B
    assert decide(g, B, ids=["play"])[0]
    assert g["trash"] == ["Fool's Gold"]
    assert g["seats"][B]["deck"][0] == "Gold"   # gained ONTO the deck
    assert g["pending_pid"] is None
    assert "Fool's Gold" in g["seats"][A]["hand"]


def test_fools_gold_several_copies_react_to_the_same_province():
    """'You may react with several Fool's Golds to the same gained Province.'"""
    g = fresh()
    give_hand(g, A, [])
    give_hand(g, B, ["Fool's Gold", "Fool's Gold"])
    to_buy(g, A)
    g["coins"] = 8
    assert mv(g, A, {"type": "buy", "card": "Province"})[0]
    assert decide(g, B, ids=["play"])[0]
    assert g["pending_pid"] == B                # re-offered for the second copy
    assert decide(g, B, ids=["play"])[0]
    assert g["trash"].count("Fool's Gold") == 2
    assert g["seats"][B]["deck"][:2] == ["Gold", "Gold"]


def test_fools_gold_triggers_on_a_province_gained_without_buying():
    g = fresh()
    give_hand(g, B, ["Fool's Gold"])
    assert engine.gain(g, A, "Province")
    engine._drive(g)
    assert g["pending_pid"] == B
    assert decide(g, B, ids=["decline"])[0]
    assert g["supply"]["Gold"] == 30


def test_fools_gold_trashed_some_other_way_gains_nothing():
    """'You don't gain a Gold if you trash Fool's Gold some other way.'"""
    g = fresh()
    give_hand(g, A, ["Chapel", "Fool's Gold"])
    assert play(g, A, "Chapel")[0]
    assert decide(g, A, cards=["Fool's Gold"])[0]
    assert g["trash"] == ["Fool's Gold"]
    assert g["pending_pid"] is None
    assert g["supply"]["Gold"] == 30


# ==========================================================================
# Trader
# ==========================================================================

def test_trader_gains_a_silver_per_coin_of_the_trashed_card():
    g = fresh()
    give_hand(g, A, ["Trader", "Gold"])
    assert play(g, A, "Trader")[0]
    assert g["pending"][-1]["constraint"]["min"] == 1        # mandatory
    assert decide(g, A, cards=["Gold"])[0]
    assert g["trash"] == ["Gold"]
    assert g["seats"][A]["discard"] == ["Silver"] * 6
    assert g["supply"]["Silver"] == 34


def test_trader_stops_when_the_silver_pile_runs_out():
    g = fresh()
    g["supply"]["Silver"] = 3
    give_hand(g, A, ["Trader", "Gold"])
    assert play(g, A, "Trader")[0]
    assert decide(g, A, cards=["Gold"])[0]
    assert g["seats"][A]["discard"] == ["Silver"] * 3
    assert g["supply"]["Silver"] == 0


def test_trader_reads_the_cost_at_trash_time_so_a_bridge_gives_fewer_silvers():
    """'If there is a COST REDUCTION, Trader will give you fewer Silvers.'"""
    g = fresh()
    give_hand(g, A, ["Village", "Bridge", "Trader", "Gold"])
    g["seats"][A]["deck"] = ["Estate"] * 3
    assert play(g, A, "Village")[0]                          # +2 Actions
    assert play(g, A, "Bridge")[0]
    assert play(g, A, "Trader")[0]
    assert decide(g, A, cards=["Gold"])[0]
    assert g["seats"][A]["discard"] == ["Silver"] * 5        # $6 - $1


def test_trader_exchanges_a_gained_card_for_a_silver_in_the_discard_pile():
    g = fresh()
    give_hand(g, A, ["Trader"])
    assert engine.gain(g, A, "Gold")
    engine._drive(g)
    assert g["pending_pid"] == A and g["pending"][-1]["card"] == "Trader"
    assert decide(g, A, ids=["play"])[0]
    assert g["seats"][A]["discard"] == ["Silver"]
    assert g["supply"]["Gold"] == 30                          # returned to its pile
    assert g["supply"]["Silver"] == 39
    assert "Trader" in g["seats"][A]["hand"]                  # revealed, not played


def test_trader_puts_the_silver_in_the_discard_even_for_a_deck_gain():
    """'You place the Silver in your discard pile no matter where you gained the
    card to.'"""
    g = fresh()
    give_hand(g, A, ["Trader"])
    assert engine.gain(g, A, "Gold", dest="deck")
    engine._drive(g)
    assert decide(g, A, ids=["play"])[0]
    assert g["seats"][A]["deck"][:1] != ["Gold"]
    assert g["seats"][A]["discard"] == ["Silver"]


def test_trader_exchange_still_leaves_the_when_gain_ability_resolved():
    """The §1.1 acceptance case — 'Even if you exchanged it, you DID gain the
    card (and triggered any when-gain ability). You DIDN'T gain the Silver.'
    Nomads' when-gain +$2 stands even though the Nomads went back to its pile."""
    g = fresh()
    give_hand(g, A, ["Trader"])
    to_buy(g, A)
    g["coins"] = 4
    assert mv(g, A, {"type": "buy", "card": "Nomads"})[0]
    assert g["pending"][-1]["card"] == "Trader"
    assert decide(g, A, ids=["play"])[0]
    assert g["coins"] == 2                       # 4 - 4 + 2 from the when-gain
    assert g["supply"]["Nomads"] == 10           # handed straight back
    assert g["seats"][A]["discard"] == ["Silver"]


def test_trader_with_no_silvers_left_does_nothing():
    """'You may only do this if there are any Silvers left in the Supply.'"""
    g = fresh()
    g["supply"]["Silver"] = 0
    give_hand(g, A, ["Trader"])
    assert engine.gain(g, A, "Gold")
    engine._drive(g)
    assert decide(g, A, ids=["play"])[0]
    assert g["seats"][A]["discard"] == ["Gold"]  # kept: the exchange failed
    assert g["supply"]["Gold"] == 29


def test_trader_exchange_can_un_empty_a_supply_pile():
    """Empty Supply piles (p49): 'A Supply pile can stop being empty if a card
    is returned to it.'"""
    g = fresh()
    g["supply"]["Duchy"] = 1
    give_hand(g, A, ["Trader"])
    assert engine.gain(g, A, "Duchy")
    engine._drive(g)
    assert g["supply"]["Duchy"] == 0
    assert decide(g, A, ids=["play"])[0]
    assert g["supply"]["Duchy"] == 1
    assert engine.count_empty_piles(g) == 0


def test_trader_reaction_is_offered_on_every_gain_including_its_own_silvers():
    g = fresh()
    give_hand(g, A, ["Trader", "Trader", "Estate"])
    assert play(g, A, "Trader")[0]
    assert decide(g, A, cards=["Estate"])[0]     # Estate costs $2 -> 2 Silvers
    # the SECOND Trader is still in hand, so each Silver gain opens its window
    assert g["pending"][-1]["card"] == "Trader"
    assert decide(g, A, ids=["decline"])[0]
    assert g["pending"][-1]["card"] == "Trader"
    assert decide(g, A, ids=["decline"])[0]
    assert g["seats"][A]["discard"] == ["Silver", "Silver"]


# ==========================================================================
# Weaver
# ==========================================================================

def test_weaver_gains_two_silvers_as_two_separate_events():
    g = fresh()
    give_hand(g, A, ["Weaver", "Trader"])
    assert play(g, A, "Weaver")[0]
    assert opts(g) == ["silvers", "card"]
    assert decide(g, A, ids=["silvers"])[0]
    # a Trader in hand proves they are separate gains: one window per Silver
    assert g["pending"][-1]["card"] == "Trader"
    assert decide(g, A, ids=["decline"])[0]
    assert g["pending"][-1]["card"] == "Trader"
    assert decide(g, A, ids=["decline"])[0]
    assert g["seats"][A]["discard"] == ["Silver", "Silver"]


def test_weaver_gains_a_card_costing_up_to_four():
    g = fresh()
    give_hand(g, A, ["Weaver"])
    assert play(g, A, "Weaver")[0]
    assert decide(g, A, ids=["card"])[0]
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Trail" in piles and "Silver" in piles
    assert "Gold" not in piles and "Souk" not in piles
    assert decide(g, A, pile="Trail")[0]
    # the gained Trail immediately offers to play itself (its own when-gain)
    assert g["pending"][-1]["card"] == "Trail"
    assert decide(g, A, ids=["decline"])[0]
    assert g["seats"][A]["discard"] == ["Trail"]


def test_weaver_is_not_offered_by_a_cleanup_discard():
    g = fresh()
    give_hand(g, A, ["Weaver", "Copper"])
    g["seats"][A]["deck"] = ["Estate"] * 10
    end_turn(g, A)
    assert g["pending_pid"] is None
    assert "Weaver" in g["seats"][A]["discard"]


def test_weaver_two_discarded_at_once_each_get_a_prompt():
    g = fresh()
    give_hand(g, A, ["Cellar", "Weaver", "Weaver"])
    g["seats"][A]["deck"] = ["Copper"] * 5
    assert play(g, A, "Cellar")[0]
    assert decide(g, A, cards=["Weaver", "Weaver"])[0]
    assert g["pending"][-1]["card"] == "Weaver"
    assert decide(g, A, ids=["decline"])[0]
    assert g["pending"][-1]["card"] == "Weaver"
    assert decide(g, A, ids=["decline"])[0]
    assert g["seats"][A]["discard"].count("Weaver") == 2


def test_weaver_discarded_off_turn_plays_itself_without_touching_the_turn_player():
    """REACTION THAT PLAYS ITSELF (p53): no Action is spent, and the card is
    'discarded in THAT turn's Clean-up phase' — the attacker's, not the
    reactor's. An off-turn play must not bump the turn player's actions_played."""
    g = fresh()
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Weaver", "Copper", "Copper", "Estate", "Estate"])
    assert play(g, A, "Militia")[0]
    played_before = g["turn_ctx"]["actions_played"]
    actions_before = g["actions"]
    assert decide(g, B, cards=["Weaver", "Estate"])[0]
    assert g["pending"][-1]["card"] == "Weaver"
    assert decide(g, B, ids=["play"])[0]
    assert g["seats"][B]["in_play"] == ["Weaver"]
    assert g["turn_ctx"]["actions_played"] == played_before
    assert g["actions"] == actions_before
    assert decide(g, B, ids=["silvers"])[0]
    assert g["seats"][B]["discard"].count("Silver") == 2
    # the attacker's clean-up sweeps every seat's play area
    end_turn(g, A)
    assert g["seats"][B]["in_play"] == []
    assert "Weaver" in g["seats"][B]["discard"]


# ==========================================================================
# Trail
# ==========================================================================

def test_trail_plays_itself_when_gained():
    g = fresh()
    give_hand(g, A, [])
    g["seats"][A]["deck"] = ["Gold"] * 3
    assert engine.gain(g, A, "Trail")
    engine._drive(g)
    assert g["pending"][-1]["card"] == "Trail"
    assert decide(g, A, ids=["play"])[0]
    assert g["seats"][A]["in_play"] == ["Trail"]
    assert g["seats"][A]["discard"] == []
    assert g["seats"][A]["hand"] == ["Gold"]     # its +1 Card
    assert g["actions"] == 2                     # its +1 Action (own turn)


def test_trail_plays_itself_out_of_the_trash_when_trashed():
    """Trail (p157): 'WHEN YOU TRASH THIS, you may play it (moving it from trash
    to play). This is not gaining it, but it's yours again. It was still
    trashed.'"""
    g = fresh()
    give_hand(g, A, ["Chapel", "Trail"])
    g["seats"][A]["deck"] = ["Gold"] * 3
    assert play(g, A, "Chapel")[0]
    assert decide(g, A, cards=["Trail"])[0]
    assert g["trash"] == ["Trail"]
    assert decide(g, A, ids=["play"])[0]
    assert g["trash"] == []                      # left the trash for the table
    assert g["seats"][A]["in_play"] == ["Chapel", "Trail"]
    assert g["seats"][A]["hand"] == ["Gold"]


def test_trail_plays_itself_when_discarded():
    g = fresh()
    give_hand(g, A, ["Cellar", "Trail"])
    g["seats"][A]["deck"] = ["Gold"] * 5
    assert play(g, A, "Cellar")[0]
    assert decide(g, A, cards=["Trail"])[0]
    assert decide(g, A, ids=["play"])[0]
    assert g["seats"][A]["in_play"] == ["Cellar", "Trail"]
    assert "Trail" not in g["seats"][A]["discard"]


def test_trail_gained_onto_the_deck_plays_itself_from_the_deck():
    g = fresh()
    give_hand(g, A, [])
    g["seats"][A]["deck"] = ["Gold"]
    assert engine.gain(g, A, "Trail", dest="deck")
    engine._drive(g)
    assert decide(g, A, ids=["play"])[0]
    assert g["seats"][A]["in_play"] == ["Trail"]
    assert g["seats"][A]["deck"] == []
    assert g["seats"][A]["hand"] == ["Gold"]


def test_trail_is_not_offered_by_a_cleanup_discard():
    """'Trail has a when-gain, when-trash and when-discard ability, and none of
    them trigger during Clean-up.'"""
    g = fresh()
    give_hand(g, A, ["Trail", "Copper"])
    g["seats"][A]["deck"] = ["Estate"] * 10
    end_turn(g, A)
    assert g["pending_pid"] is None
    assert "Trail" in g["seats"][A]["discard"]


def test_trail_watchtower_trashing_a_gained_trail_still_plays_it_only_once():
    """'if you use Watchtower to trash a Trail on when-gain, Trail has triggered
    both on when-gain and on when-trash, but can only play itself once.'"""
    g = fresh()
    give_hand(g, A, ["Watchtower"])
    g["seats"][A]["deck"] = ["Gold"] * 3
    assert engine.gain(g, A, "Trail")
    engine._drive(g)
    # Trail's own when-gain and Watchtower are concurrent (p23 §2): the pool
    # asks; take the Trail offer first — the old fixed order — and decline it
    f = g["pending"][-1]
    assert (f["card"], f["stage"]) == ("__abilities", "pick")
    opts = {o["label"]: o["id"] for o in f["constraint"]["options"]}
    assert set(opts) == {"Trail", "Watchtower"}
    assert decide(g, A, ids=[opts["Trail"]])[0]
    assert g["pending"][-1]["card"] == "Trail"
    assert decide(g, A, ids=["decline"])[0]      # leave it for the Watchtower
    assert g["pending"][-1]["card"] == "Watchtower"
    assert decide(g, A, ids=["play"])[0]
    assert decide(g, A, ids=["trash"])[0]
    # trashing it re-triggers Trail, now out of the trash pile
    assert g["pending"][-1]["card"] == "Trail"
    assert decide(g, A, ids=["play"])[0]
    assert g["seats"][A]["in_play"] == ["Trail"]
    assert g["trash"] == []
    assert g["seats"][A]["discard"] == []


def test_trail_played_off_turn_draws_but_its_plus_action_evaporates():
    """EFFECTS WHEN IT'S NOT YOUR TURN (p48): 'on another player's turn you
    always start with empty pools' — the +1 Action must not reach the attacker."""
    g = fresh()
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Trail", "Copper", "Copper", "Estate", "Estate"])
    g["seats"][B]["deck"] = ["Gold"] * 3
    assert play(g, A, "Militia")[0]
    actions_before = g["actions"]
    assert decide(g, B, cards=["Trail", "Estate"])[0]
    assert decide(g, B, ids=["play"])[0]
    assert "Gold" in g["seats"][B]["hand"]        # B drew its +1 Card
    assert g["actions"] == actions_before         # nobody got the +1 Action
    assert any(e["event"] == "off_turn_bonus" for e in g["log"])
    assert g["turn_ctx"]["actions_played"] == 1   # only A's Militia
    # discarded in the ATTACKER's clean-up, not B's
    end_turn(g, A)
    assert g["seats"][B]["in_play"] == []
    assert "Trail" in g["seats"][B]["discard"]


def test_trail_bought_in_the_buy_phase_cannot_play_the_treasures_it_draws():
    """'When you buy & gain a Trail in your Buy phase, you cannot play any
    Treasures you draw with it.'"""
    g = fresh()
    give_hand(g, A, [])
    to_buy(g, A)
    g["coins"] = 4
    g["seats"][A]["deck"] = ["Gold"] * 3
    assert mv(g, A, {"type": "buy", "card": "Trail"})[0]
    assert decide(g, A, ids=["play"])[0]
    assert "Gold" in g["seats"][A]["hand"]
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Gold"})
    assert not ok and "buying" in err


# ==========================================================================
# Berserker
# ==========================================================================

def test_berserker_gains_a_cheaper_card_then_opponents_discard_to_three():
    g = fresh()
    give_hand(g, A, ["Berserker"])
    give_hand(g, B, ["Copper"] * 5)
    assert play(g, A, "Berserker")[0]
    piles = g["pending"][-1]["constraint"]["piles"]
    assert "Trail" in piles and "Souk" not in piles and "Berserker" not in piles
    assert decide(g, A, pile="Trail")[0]
    assert g["pending"][-1]["card"] == "Trail"    # the gain resolves first
    assert decide(g, A, ids=["decline"])[0]
    assert "Trail" in g["seats"][A]["discard"]
    assert g["pending_pid"] == B
    assert decide(g, B, cards=["Copper", "Copper"])[0]
    assert len(g["seats"][B]["hand"]) == 3


def test_berserker_with_no_cheaper_pile_still_attacks():
    g = fresh()
    for p in list(g["supply"]):
        if engine.cost(g, p) < 5:
            g["supply"][p] = 0
    give_hand(g, A, ["Berserker"])
    give_hand(g, B, ["Gold"] * 5)
    assert play(g, A, "Berserker")[0]
    assert g["pending_pid"] == B
    assert decide(g, B, cards=["Gold", "Gold"])[0]
    assert len(g["seats"][B]["hand"]) == 3


def test_berserker_moat_reveal_blocks_the_discard():
    """The immunity-capture regression: the attack runs from a LATER stage, so
    the play's immune set has to be carried in the frame data."""
    g = fresh()
    give_hand(g, A, ["Berserker"])
    give_hand(g, B, ["Moat", "Copper", "Copper", "Copper", "Copper"])
    assert play(g, A, "Berserker")[0]
    assert g["pending_pid"] == B                  # the reaction window
    assert decide(g, B, ids=["react:Moat"])[0]
    assert decide(g, A, pile="Silver")[0]
    assert g["pending_pid"] is None
    assert len(g["seats"][B]["hand"]) == 5         # the Moat held


def test_berserker_reads_its_own_current_cost_as_the_cap():
    """'Costing less than THIS' is measured against Berserker's CURRENT cost, so
    a cost reduction moves the cap with it — a cap cached from the printed $5
    would wrongly offer the (now $4) Souk."""
    g = fresh()
    give_hand(g, A, ["Village", "Bridge", "Berserker"])
    g["seats"][A]["deck"] = ["Estate"] * 3
    give_hand(g, B, ["Copper"] * 3)
    assert play(g, A, "Village")[0]
    assert play(g, A, "Bridge")[0]
    assert play(g, A, "Berserker")[0]
    piles = g["pending"][-1]["constraint"]["piles"]
    assert engine.cost(g, "Berserker") == 4 and engine.cost(g, "Souk") == 4
    assert "Souk" not in piles                    # equal cost is not "less than"
    assert "Trail" in piles                       # $4 -> $3, still cheaper


def test_berserker_plays_itself_when_gained_with_an_action_in_play():
    g = fresh()
    give_hand(g, A, ["Village"])
    give_hand(g, B, ["Copper"] * 5)
    g["seats"][A]["deck"] = ["Copper"] * 5
    assert play(g, A, "Village")[0]               # an Action now in play
    to_buy(g, A)
    g["coins"] = 5
    assert mv(g, A, {"type": "buy", "card": "Berserker"})[0]
    assert g["seats"][A]["in_play"].count("Berserker") == 1
    assert "Berserker" not in g["seats"][A]["discard"]
    assert g["pending_pid"] == A                  # its own gain-a-cheaper-card
    assert decide(g, A, pile="Silver")[0]
    assert g["pending_pid"] == B
    assert decide(g, B, cards=["Copper", "Copper"])[0]


def test_berserker_does_not_play_itself_without_an_action_in_play():
    g = fresh()
    give_hand(g, A, [])
    to_buy(g, A)
    g["coins"] = 5
    assert mv(g, A, {"type": "buy", "card": "Berserker"})[0]
    assert g["seats"][A]["discard"] == ["Berserker"]
    assert g["pending_pid"] is None


def test_berserker_counts_a_duration_persisting_on_the_table():
    """CARDS YOU HAVE IN PLAY (p47): 'Remember that Duration cards can be in
    play without having been played this turn.'"""
    g = fresh()
    give_hand(g, A, ["Caravan"])
    g["seats"][A]["deck"] = ["Copper"] * 10
    assert play(g, A, "Caravan")[0]
    end_turn(g, A)
    give_hand(g, B, [])
    end_turn(g, B)
    assert engine.duration_in_play(g, A, "Caravan")
    assert g["seats"][A]["in_play"] == []          # it lives in the duration zone
    give_hand(g, B, ["Copper"] * 3)
    assert engine.gain(g, A, "Berserker")
    engine._drive(g)
    assert g["seats"][A]["in_play"].count("Berserker") == 1   # it played itself


def test_berserker_that_has_lost_track_does_not_play_itself():
    """'If you instead move it with Watchtower ... first, Berserker fails to
    play itself.' Staged by moving the card between the gain and the trigger
    resolving — the frames are parked until something drives them."""
    g = fresh()
    give_hand(g, A, [])
    g["seats"][A]["in_play"] = ["Village"]         # an Action is on the table
    assert engine.gain(g, A, "Berserker")
    g["seats"][A]["discard"].remove("Berserker")   # a Watchtower trashed it
    g["trash"].append("Berserker")
    engine._drive(g)
    assert g["pending_pid"] is None
    assert "Berserker" not in g["seats"][A]["in_play"]


def test_berserker_that_played_itself_is_lost_track_of_by_watchtower():
    """MOVE GAINED CARD (p51): 'when you gain Berserker and play it, cards like
    Innovation and Watchtower lose track of it'."""
    g = fresh()
    give_hand(g, A, ["Watchtower"])
    give_hand(g, B, ["Copper"] * 3)
    g["seats"][A]["in_play"] = ["Village"]
    assert engine.gain(g, A, "Berserker")
    engine._drive(g)
    # Berserker's self-play and Watchtower are concurrent: play it FIRST, so
    # the Watchtower window that follows has lost track of it (the ruling)
    f = g["pending"][-1]
    assert (f["card"], f["stage"]) == ("__abilities", "pick")
    opts = {o["label"]: o["id"] for o in f["constraint"]["options"]}
    assert decide(g, A, ids=[opts["Berserker"]])[0]
    assert g["seats"][A]["in_play"] == ["Village", "Berserker"]
    assert decide(g, A, pile="Silver")[0]          # its own gain
    assert g["pending"][-1]["data"]["gained"] == "Silver"   # that gain's window
    assert decide(g, A, ids=["decline"])[0]
    assert g["pending"][-1]["data"]["gained"] == "Berserker"
    assert decide(g, A, ids=["play"])[0]
    assert decide(g, A, ids=["trash"])[0]
    assert g["trash"] == []                        # nothing to trash: it's in play
    assert "Berserker" in g["seats"][A]["in_play"]


def test_berserker_gained_off_turn_is_discarded_at_that_turns_cleanup():
    """'You may gain & play Berserker during an opponent's turn: discard it in
    that player's Clean-up phase.'"""
    g = fresh()
    give_hand(g, A, ["Copper"] * 5)
    give_hand(g, B, [])
    g["seats"][B]["in_play"] = ["Village"]
    assert engine.gain(g, B, "Berserker")
    engine._drive(g)
    assert g["pending_pid"] == B
    assert decide(g, B, pile="Silver")[0]
    assert g["seats"][B]["in_play"] == ["Village", "Berserker"]
    assert g["pending_pid"] == A                   # B's attack hits the turn player
    assert decide(g, A, cards=["Copper", "Copper"])[0]
    end_turn(g, A)
    assert g["seats"][B]["in_play"] == []
    assert "Berserker" in g["seats"][B]["discard"]


# ==========================================================================
# Scheme
# ==========================================================================

def test_scheme_topdecks_an_action_and_it_lands_in_the_new_hand():
    g = fresh()
    give_hand(g, A, ["Scheme", "Village"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert play(g, A, "Scheme")[0]
    assert play(g, A, "Village")[0]
    to_buy(g, A)
    assert end(g, A)[0]                            # end of buy phase
    assert g["pending"][-1]["card"] == "Scheme"
    assert sorted(g["pending"][-1]["constraint"]["cards"]) == ["Scheme", "Village"]
    assert decide(g, A, cards=["Village"])[0]
    assert "Village" in g["seats"][A]["hand"]      # topdecked, then drawn
    assert "Village" not in g["seats"][A]["discard"]
    assert "Scheme" in g["seats"][A]["discard"]


def test_scheme_declining_discards_everything_normally():
    g = fresh()
    give_hand(g, A, ["Scheme"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert play(g, A, "Scheme")[0]
    assert end(g, A)[0]
    assert decide(g, A, cards=[])[0]
    assert "Scheme" in g["seats"][A]["discard"]
    assert g["seats"][A]["in_play"] == []


def test_scheme_is_cumulative_and_the_second_pick_ends_up_on_top():
    """'If you play Scheme with a throne-room, you may choose multiple Action
    cards. You may choose the Scheme itself.'"""
    g = fresh()
    give_hand(g, A, ["Throne Room", "Scheme", "Village"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert play(g, A, "Throne Room")[0]
    assert decide(g, A, cards=["Scheme"])[0]       # played twice
    assert play(g, A, "Village")[0]
    to_buy(g, A)
    assert end(g, A)[0]
    assert decide(g, A, cards=["Village"])[0]      # first offer
    assert g["pending"][-1]["card"] == "Scheme"    # the second Scheme's offer
    assert "Village" not in g["pending"][-1]["constraint"]["cards"]
    assert decide(g, A, cards=["Scheme"])[0]
    assert g["seats"][A]["hand"][:2] == ["Scheme", "Village"]   # 2nd pick on top


def test_scheme_does_not_offer_a_duration_that_stays_in_play():
    """'If a card is not discarded (for instance if it's a Duration that stays
    in play) Scheme can't put it onto your deck.'"""
    g = fresh()
    give_hand(g, A, ["Scheme", "Caravan"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert play(g, A, "Scheme")[0]
    assert play(g, A, "Caravan")[0]
    to_buy(g, A)
    assert end(g, A)[0]
    assert g["pending"][-1]["constraint"]["cards"] == ["Scheme"]
    assert decide(g, A, cards=[])[0]
    assert engine.duration_in_play(g, A, "Caravan")


def test_scheme_trashed_from_play_still_schemes():
    """Removed from play (p54): 'If the removed card had set up future effects —
    such as Charm or Scheme — these continue.'"""
    g = fresh()
    give_hand(g, A, ["Scheme", "Village"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert play(g, A, "Scheme")[0]
    assert play(g, A, "Village")[0]
    g["seats"][A]["in_play"].remove("Scheme")      # a Mint/Procession-style removal
    g["trash"].append("Scheme")
    to_buy(g, A)
    assert end(g, A)[0]
    assert g["pending"][-1]["constraint"]["cards"] == ["Village"]
    assert decide(g, A, cards=["Village"])[0]
    assert "Village" in g["seats"][A]["hand"]


def test_scheme_does_not_survive_the_turn():
    g = fresh()
    give_hand(g, A, ["Scheme"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert play(g, A, "Scheme")[0]
    assert end(g, A)[0]
    assert decide(g, A, cards=[])[0]
    assert g["watchers"] == []
    give_hand(g, B, [])
    end_turn(g, B)
    give_hand(g, A, [])
    g["seats"][A]["in_play"] = ["Village"]         # an Action leaving play
    end_turn(g, A)
    assert g["pending_pid"] is None                # no offer this turn
    assert "Village" in g["seats"][A]["discard"]
