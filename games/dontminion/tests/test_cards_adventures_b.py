"""Adventures, half B — the RESERVE cards and their call windows, the TRAVELLER
chains, the 20 EVENTS, the Adventures tokens on piles, and the setup rules.

Headline rulings pinned here:
  * **Calling is not playing** — no Action spent, no before-play or after-play
    ability, and the called card is discarded in THAT turn's Clean-up even when
    the call happened on an opponent's turn (Duplicate).
  * **A Reserve played without moving into play never reaches the mat**, and
    Wine Merchant still gives its +1 Buy and +$4 when that happens.
  * **Royal Carriage may only be called if the played Action is still in play**,
    and may be called several times for the same play.
  * **Travellers exchange when DISCARDED FROM PLAY**, which is ph. 5H's
    interruptible Clean-up; the exchange is not a gain, and it is not offered
    at all when the upgrade's pile is empty.
  * **Teacher may only move a token to a pile you have NO tokens on** — any of
    yours, including the -$2 Cost and Trashing tokens; opponents' don't hinder.
  * **Haunted Woods and Swamp Hag (2022) trigger on a BOUGHT GAIN**, not on the
    buy, and not on an Event purchase.
  * **Mission's extra turn can't buy cards** but can still buy Events, and
    can't be a third turn in a row.
  * **Inheritance changes every Estate in the game, only on its owner's turns**,
    and not once the game is over (the Vineyard ruling).
"""

import json

from games.dontminion import cards, effects, engine

A, B, C = "alice", "bob", "carol"

KRES = ["Coin of the Realm", "Ratcatcher", "Guide", "Duplicate", "Transmogrify",
        "Royal Carriage", "Wine Merchant", "Distant Lands", "Page", "Peasant"]
KPLAIN = ["Magpie", "Port", "Ranger", "Artificer", "Lost City", "Treasure Trove",
          "Miser", "Raze", "Amulet", "Dungeon"]


def fresh(players=(A, B), seed=7, kingdom=tuple(KRES), expansions=("adventures",),
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


def buy_ls(g, pid, name):
    return mv(g, pid, {"type": "buy_landscape", "name": name})


def frame(g):
    return g["pending"][-1] if g["pending"] else None


def opt_ids(g):
    return [o["id"] for o in frame(g)["constraint"]["options"]]


def to_buy(g, pid=A, coins=20, buys=1):
    g["turn"] = pid
    g["phase"] = "buy"
    g["coins"] = coins
    g["buys"] = buys


def end_turn(g):
    """Finish the current turn, answering anything that comes up."""
    rng = engine.random.Random(1)
    g["phase"] = "buy"
    mv(g, g["turn"], {"type": "end_phase"})
    for _ in range(60):
        if g["pending_pid"] is None or g["over"]:
            break
        pid = g["pending_pid"]
        mv(g, pid, {"type": "decision", **engine.sample_decision(g, pid, rng)})


# ── the Tavern mat and calling ────────────────────────────────────────────────

def test_a_reserve_goes_to_the_mat_when_played():
    g = fresh()
    give_hand(g, A, ["Ratcatcher"])
    give_deck(g, A, ["Copper"] * 5)
    assert play(g, A, "Ratcatcher")[0]
    assert g["seats"][A]["tavern"] == ["Ratcatcher"]
    assert "Ratcatcher" not in g["seats"][A]["in_play"]
    assert len(g["seats"][A]["hand"]) == 1 and g["actions"] == 1


def test_a_reserve_played_without_moving_into_play_never_reaches_the_mat():
    """"If you play it without moving it into play, it won't go to your Tavern
    mat" — the throne-room replay shape."""
    g = fresh()
    give_deck(g, A, ["Copper"] * 5)
    engine.play_action_card(g, A, "Ratcatcher", from_zone=None)
    engine._drive(g)
    assert g["seats"][A]["tavern"] == []


def test_wine_merchant_still_pays_when_it_cannot_reach_the_mat():
    """"If you play Wine Merchant without moving it into play, you still get
    +1 Buy and +$4." """
    g = fresh()
    engine.play_action_card(g, A, "Wine Merchant", from_zone=None)
    engine._drive(g)
    assert g["buys"] == 2 and g["coins"] == 4
    assert g["seats"][A]["tavern"] == []


def test_calling_a_reserve_is_not_playing_it():
    g = fresh()
    give_deck(g, A, ["Copper"] * 5)
    g["seats"][A]["tavern"] = ["Coin of the Realm"]
    before_played = g["turn_ctx"]["actions_played"]
    before_actions = g["actions"]
    assert engine.call_card(g, A, "Coin of the Realm") is True
    engine._drive(g)
    assert "Coin of the Realm" in g["seats"][A]["in_play"]
    assert g["turn_ctx"]["actions_played"] == before_played
    assert g["actions"] == before_actions, "the call itself grants nothing"


def test_the_start_of_turn_call_window_offers_every_reserve_on_the_mat():
    """Two Reserves both want calling at the same instant, so they arrive as ONE
    ability pool and the player picks the order — the p23 §2 contract, which
    calls get for free by riding the offer machinery instead of being a move."""
    g = fresh()
    g["seats"][A]["tavern"] = ["Ratcatcher", "Guide"]
    give_hand(g, A, [])
    give_deck(g, A, ["Copper"] * 20)
    # hand the turn to B and back WITHOUT auto-answering anything, so the
    # start-of-turn window is still open when we look at it
    g["phase"] = "buy"
    mv(g, A, {"type": "end_phase"})
    g["phase"] = "buy"
    mv(g, B, {"type": "end_phase"})
    assert g["turn"] == A
    assert frame(g) is not None
    labels = json.dumps(frame(g)["constraint"])
    assert "Ratcatcher" in labels and "Guide" in labels


def test_guide_discards_your_hand_and_draws_five():
    g = fresh()
    g["seats"][A]["tavern"] = ["Guide"]
    give_hand(g, A, ["Estate", "Estate"])
    give_deck(g, A, ["Copper"] * 8)
    effects.STAGES[("Guide", "call")](g, A, {"data": {}}, {"ids": ["play"]})
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 5
    assert g["seats"][A]["discard"].count("Estate") == 2
    assert "Guide" in g["seats"][A]["in_play"]


def test_guide_can_be_called_with_an_empty_hand():
    """"You can call this to draw 5 cards even if you have no cards in hand." """
    g = fresh()
    g["seats"][A]["tavern"] = ["Guide"]
    give_hand(g, A, [])
    give_deck(g, A, ["Copper"] * 8)
    effects.STAGES[("Guide", "call")](g, A, {"data": {}}, {"ids": ["play"]})
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 5


def test_transmogrify_remodels_into_your_hand():
    """"The card is GAINED TO YOUR HAND" (clear in the current card text)."""
    g = fresh()
    g["seats"][A]["tavern"] = ["Transmogrify"]
    give_hand(g, A, ["Estate"])
    effects.STAGES[("Transmogrify", "call")](g, A, {"data": {}}, {"ids": ["play"]})
    engine._drive(g)
    assert decide(g, A, cards=["Estate"])[0]
    assert "Estate" in g["trash"]
    assert frame(g)["kind"] == "choose_pile"
    piles = frame(g)["constraint"]["piles"]
    assert "Silver" in piles and "Gold" not in piles, "up to $1 more than $2"
    assert decide(g, A, pile="Silver")[0]
    assert "Silver" in g["seats"][A]["hand"], "into your HAND"


def test_duplicate_is_called_on_a_gain_and_copies_it():
    g = fresh()
    g["seats"][A]["tavern"] = ["Duplicate"]
    to_buy(g, A, coins=5)
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert frame(g) is not None and frame(g)["card"] == "Duplicate"
    assert decide(g, A, ids=["play"])[0]
    assert g["seats"][A]["discard"].count("Silver") == 2


def test_duplicate_is_not_offered_for_a_card_costing_more_than_six():
    g = fresh()
    g["seats"][A]["tavern"] = ["Duplicate"]
    to_buy(g, A, coins=20)
    assert mv(g, A, {"type": "buy", "card": "Province"})[0]
    assert frame(g) is None, "Province costs $8"


def test_a_duplicate_called_on_an_opponents_turn_is_discarded_in_their_cleanup():
    """"You may call Duplicate if you gain a card on another player's turn.
    Your Duplicate is then discarded in the Clean-up of that player." """
    g = fresh()
    g["seats"][B]["tavern"] = ["Duplicate"]
    to_buy(g, A, coins=5)
    engine.gain(g, B, "Silver")           # B gains on A's turn
    engine._drive(g)
    assert g["pending_pid"] == B
    assert decide(g, B, ids=["play"])[0]
    assert "Duplicate" in g["seats"][B]["in_play"]
    end_turn(g)
    assert g["seats"][B]["in_play"] == []
    assert "Duplicate" in g["seats"][B]["discard"]


def test_royal_carriage_replays_the_action_that_just_resolved():
    g = fresh(kingdom=["Royal Carriage", "Magpie", "Port", "Ranger", "Artificer",
                       "Lost City", "Miser", "Raze", "Amulet", "Dungeon"])
    g["seats"][A]["tavern"] = ["Royal Carriage"]
    give_hand(g, A, ["Lost City"])
    give_deck(g, A, ["Copper"] * 10)
    assert play(g, A, "Lost City")[0]
    assert frame(g) is not None and frame(g)["card"] == "Royal Carriage"
    assert decide(g, A, ids=["play"])[0]
    assert len(g["seats"][A]["hand"]) == 4, "+2 Cards twice"
    assert "Royal Carriage" in g["seats"][A]["in_play"]


def test_royal_carriage_is_not_offered_when_the_action_left_play():
    """"You may only call Royal Carriage if the played Action card is still in
    play." Raze that trashed itself is the case."""
    g = fresh(kingdom=["Royal Carriage", "Raze", "Port", "Ranger", "Artificer",
                       "Lost City", "Miser", "Magpie", "Amulet", "Dungeon"])
    g["seats"][A]["tavern"] = ["Royal Carriage"]
    give_hand(g, A, ["Raze"])
    give_deck(g, A, ["Copper"] * 5)
    assert play(g, A, "Raze")[0]
    assert decide(g, A, ids=["self"])[0]        # trash the Raze
    while frame(g) is not None and frame(g)["card"] == "Raze":
        assert decide(g, A, cards=[frame(g)["constraint"]["cards"][0]])[0]
    assert frame(g) is None or frame(g)["card"] != "Royal Carriage"


def test_wine_merchant_is_discarded_from_the_mat_at_the_end_of_the_buy_phase():
    g = fresh()
    g["seats"][A]["tavern"] = ["Wine Merchant"]
    to_buy(g, A, coins=3)
    give_hand(g, A, [])
    assert mv(g, A, {"type": "end_phase"})[0]
    assert frame(g) is not None and frame(g)["card"] == "Wine Merchant"
    assert decide(g, A, ids=["play"])[0]
    assert g["seats"][A]["tavern"] == []
    assert "Wine Merchant" in g["seats"][A]["discard"]


def test_wine_merchant_is_not_offered_below_two_dollars():
    g = fresh()
    g["seats"][A]["tavern"] = ["Wine Merchant"]
    to_buy(g, A, coins=1)
    give_hand(g, A, [])
    assert mv(g, A, {"type": "end_phase"})[0]
    assert "Wine Merchant" in g["seats"][A]["tavern"]


def test_distant_lands_scores_four_only_on_the_mat():
    g = fresh()
    base = engine._vp_of(g, A)
    give_hand(g, A, ["Distant Lands"])
    assert play(g, A, "Distant Lands")[0]
    assert g["seats"][A]["tavern"] == ["Distant Lands"]
    on_mat = engine._vp_of(g, A)
    # ...and 0 anywhere else (give_hand ate some starting Estates, so this is a
    # DELTA rather than an absolute score)
    g["seats"][A]["tavern"] = []
    g["seats"][A]["discard"].append("Distant Lands")
    off_mat = engine._vp_of(g, A)
    assert on_mat - off_mat == 4
    assert off_mat <= base


def test_two_distant_lands_one_on_the_mat_score_four_not_eight():
    g = fresh()
    g["seats"][A]["tavern"] = ["Distant Lands"]
    g["seats"][A]["deck"].append("Distant Lands")
    assert engine._vp_of(g, A) == 3 + 4


# ── the Travellers ────────────────────────────────────────────────────────────

def test_a_traveller_offers_its_exchange_when_discarded_from_play():
    g = fresh()
    give_hand(g, A, ["Page"])
    give_deck(g, A, ["Copper"] * 10)
    assert play(g, A, "Page")[0]
    g["phase"] = "buy"
    assert mv(g, A, {"type": "end_phase"})[0]
    assert frame(g) is not None and frame(g)["card"] == "Page"
    assert opt_ids(g) == ["yes", "no"]
    assert decide(g, A, ids=["yes"])[0]
    assert "Treasure Hunter" in g["seats"][A]["discard"]
    assert "Page" not in engine.owned_cards(g, A), "the Page went back to its pile"
    assert engine.pile_count(g, "Treasure Hunter") == 4


def test_the_exchange_is_not_a_gain():
    """ph. 3's `exchange` emits nothing: you did not gain the upgrade."""
    g = fresh()
    give_hand(g, A, ["Page"])
    give_deck(g, A, ["Copper"] * 10)
    assert play(g, A, "Page")[0]
    n = len([e for e in g["log"] if e.get("event") == "gain"])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "end_phase"})[0]
    assert decide(g, A, ids=["yes"])[0]
    assert len([e for e in g["log"] if e.get("event") == "gain"]) == n


def test_declining_the_exchange_keeps_the_traveller():
    g = fresh()
    give_hand(g, A, ["Page"])
    give_deck(g, A, ["Copper"] * 10)
    assert play(g, A, "Page")[0]
    g["phase"] = "buy"
    assert mv(g, A, {"type": "end_phase"})[0]
    assert decide(g, A, ids=["no"])[0]
    assert "Page" in engine.owned_cards(g, A)
    assert engine.pile_count(g, "Treasure Hunter") == 5


def test_no_exchange_is_offered_when_the_upgrade_pile_is_empty():
    g = fresh()
    g["nonsupply"]["Treasure Hunter"] = 0
    give_hand(g, A, ["Page"])
    give_deck(g, A, ["Copper"] * 10)
    assert play(g, A, "Page")[0]
    g["phase"] = "buy"
    assert mv(g, A, {"type": "end_phase"})[0]
    assert frame(g) is None, "a prompt for an impossible choice is noise"


# Two Travellers finishing their journey on the same table. The whole in-play
# row is discarded SIMULTANEOUSLY, so the offers are concurrent and the player
# orders them (p23 §2) — and the order is a real decision, not noise: exchanging
# the Fugitive returns it to its pile, which is what lets the Soldier exchange
# into it. Both tests are regressions on one bug, reported from a live game.

def _drain_prompts(g, pid, limit=24):
    """Answer pid's Clean-up prompts with their FIRST option until none are
    left, and return how many were answered."""
    for n in range(limit):
        f = frame(g)
        if f is None or f["pid"] != pid:
            return n
        assert f["kind"] == "choose_option", f
        ok, err = decide(g, pid, ids=[f["constraint"]["options"][0]["id"]])
        assert ok, err
    raise AssertionError("the Clean-up prompts never drained")


def test_two_travellers_in_play_are_ONE_ordering_choice_and_you_get_the_one_you_pick():
    """REGRESSION. The exchange spec is registered `from:"in_play"`, and that
    source only asks "is the card on the table" — so it was consulted on EVERY
    `cleanup_discard` the Clean-up emits, one per card in play. A Soldier and a
    Fugitive therefore each collected an offer from the OTHER's emit as well:
    two pools of two, four prompts for two cards. Worse, `_traveller_offer`
    reads the EMIT's subject rather than the option that was picked, so
    choosing "Fugitive" exchanged the Soldier and the leftovers then logged
    `lost_track` at the player."""
    g = fresh()
    g["seats"][A]["in_play"] = ["Soldier", "Fugitive"]
    give_deck(g, A, ["Copper"] * 10)
    g["phase"] = "buy"
    assert mv(g, A, {"type": "end_phase"})[0]

    f = frame(g)
    assert f["card"] == "__abilities", "both exchanges belong to one pool"
    labels = [o["label"] for o in f["constraint"]["options"]]
    assert sorted(labels) == ["Fugitive", "Soldier"], labels
    pick = next(o["id"] for o in f["constraint"]["options"]
                if o["label"] == "Fugitive")
    assert decide(g, A, ids=[pick])[0]
    assert frame(g)["card"] == "Fugitive", \
        f"picked Fugitive, was offered {frame(g)['card']}"
    assert decide(g, A, ids=["yes"])[0]
    assert "Disciple" in g["seats"][A]["discard"]

    # ...and only THEN the Soldier's own offer, which the returned Fugitive is
    # now available for
    assert frame(g)["card"] == "Soldier"
    assert decide(g, A, ids=["yes"])[0]
    ex = [(e["card"], e["into"]) for e in g["log"] if e.get("event") == "exchange"]
    assert ex == [("Fugitive", "Disciple"), ("Soldier", "Fugitive")], ex
    assert not [e for e in g["log"] if e.get("event") == "lost_track"]


def test_each_traveller_copy_in_play_is_offered_exactly_once():
    """REGRESSION on the same bug, counted: N Traveller copies in play produced
    one offer per (copy x distinct Traveller name), i.e. N^2 prompts for N
    cards, most of them resolving a card that had already left the table."""
    g = fresh()
    g["seats"][A]["in_play"] = ["Peasant", "Peasant", "Fugitive"]
    give_deck(g, A, ["Copper"] * 10)
    g["phase"] = "buy"
    assert mv(g, A, {"type": "end_phase"})[0]
    _drain_prompts(g, A)
    ex = sorted(e["card"] for e in g["log"] if e.get("event") == "exchange")
    assert ex == ["Fugitive", "Peasant", "Peasant"], ex
    assert not [e for e in g["log"] if e.get("event") == "lost_track"]
    assert not g["seats"][A]["in_play"], "Clean-up still swept the table"


def test_the_traveller_chain_walks_all_the_way_to_champion():
    g = fresh()
    for a, b in cards.TRAVELLERS.items():
        if a in ("Page", "Peasant"):
            continue
        assert engine.pile_count(g, a) == 5, a
    assert cards.traveller_chain("Page") == ["Treasure Hunter", "Warrior",
                                             "Hero", "Champion"]
    assert cards.traveller_chain("Champion") == []


def test_the_traveller_piles_are_never_in_the_supply():
    g = fresh()
    for up in cards.traveller_chain("Page") + cards.traveller_chain("Peasant"):
        assert up not in g["supply"], up
        assert engine.is_supply_pile(g, up) is False
    to_buy(g, A, coins=20)
    assert not [m for m in engine.legal_moves(g, A)
                if m.get("card") in ("Champion", "Teacher")]


def test_no_traveller_piles_without_page_or_peasant():
    g = fresh(kingdom=KPLAIN)
    assert g["nonsupply"] == {}


def test_champion_protects_forever_and_gives_an_action_per_action():
    g = fresh(kingdom=KPLAIN)
    engine.add_pile(g, "Champion", count=5)
    g["seats"][A]["in_play"] = []
    give_hand(g, A, ["Magpie"])
    give_deck(g, A, ["Copper"] * 10)
    effects.EFFECTS["Champion"](g, A)
    engine._drive(g)
    assert g["actions"] == 2, "+1 Action, not 2, on the Champion's own play"
    assert engine.attack_protected(g, A) is True
    # every later Action play gets +1 Action FIRST
    before = g["actions"]
    assert play(g, A, "Magpie")[0]
    assert g["actions"] == before + 1, "Magpie's own +1 Action plus the token"


def test_teacher_moves_a_token_to_a_pile_you_have_none_on():
    g = fresh()
    g["seats"][A]["tavern"] = ["Teacher"]
    engine.move_token(g, A, "-cost", "Guide")
    effects.STAGES[("Teacher", "call")](g, A, {"data": {}}, {"ids": ["play"]})
    engine._drive(g)
    assert decide(g, A, ids=["+card"])[0]
    piles = frame(g)["constraint"]["piles"]
    assert "Guide" not in piles, "you already have a token there"
    assert "Ratcatcher" in piles
    assert "Copper" not in piles, "an ACTION Supply pile"
    assert decide(g, A, pile="Ratcatcher")[0]
    assert engine.pile_tokens(g, "Ratcatcher", A) == ["+card"]


def test_an_opponents_token_does_not_hinder_teacher():
    g = fresh()
    g["seats"][A]["tavern"] = ["Teacher"]
    engine.move_token(g, B, "+buy", "Guide")
    effects.STAGES[("Teacher", "call")](g, A, {"data": {}}, {"ids": ["play"]})
    engine._drive(g)
    assert decide(g, A, ids=["+card"])[0]
    assert "Guide" in frame(g)["constraint"]["piles"]


# ── the Adventures tokens on piles ────────────────────────────────────────────

def test_a_plus_card_token_draws_before_the_played_card_resolves():
    g = fresh(kingdom=KPLAIN)
    engine.move_token(g, A, "+card", "Magpie")
    give_hand(g, A, ["Magpie"])
    give_deck(g, A, ["Estate", "Estate", "Estate", "Copper"])
    assert play(g, A, "Magpie")[0]
    # the token's +1 Card, then Magpie's own +1 Card
    assert len(g["seats"][A]["hand"]) == 2


def test_a_token_only_fires_for_its_owner():
    g = fresh(kingdom=KPLAIN)
    engine.move_token(g, B, "+coin", "Magpie")
    give_hand(g, A, ["Magpie"])
    give_deck(g, A, ["Copper"] * 5)
    assert play(g, A, "Magpie")[0]
    assert g["coins"] == 0, "B's token, A's play"


def test_the_trashing_token_offers_a_trash_on_a_gain_from_that_pile():
    g = fresh(kingdom=KPLAIN)
    engine.move_token(g, A, "trashing", "Magpie")
    give_hand(g, A, ["Estate", "Copper"])
    to_buy(g, A, coins=4)
    assert mv(g, A, {"type": "buy", "card": "Magpie"})[0]
    assert frame(g) is not None and frame(g)["card"] == "__token"
    assert decide(g, A, cards=["Estate"])[0]
    assert "Estate" in g["trash"]


def test_the_trashing_token_does_not_fire_for_another_pile():
    g = fresh(kingdom=KPLAIN)
    engine.move_token(g, A, "trashing", "Magpie")
    give_hand(g, A, ["Estate"])
    to_buy(g, A, coins=4)
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert frame(g) is None


# ── the Events ────────────────────────────────────────────────────────────────

def test_alms_gains_only_with_no_treasures_in_play():
    g = fresh(landscapes=["Alms"])
    to_buy(g, A, coins=0, buys=2)
    g["seats"][A]["in_play"] = ["Copper"]
    assert buy_ls(g, A, "Alms")[0]
    assert frame(g) is None, "a Treasure in play => nothing"
    g["landscapes"]["Alms"]["bought_turn"] = None
    g["seats"][A]["in_play"] = []
    assert buy_ls(g, A, "Alms")[0]
    assert frame(g)["kind"] == "choose_pile"
    assert decide(g, A, pile="Silver")[0]
    assert "Silver" in g["seats"][A]["discard"]


def test_borrow_takes_the_minus_card_token_for_a_dollar_once():
    g = fresh(landscapes=["Borrow"])
    to_buy(g, A, coins=0, buys=3)
    assert buy_ls(g, A, "Borrow")[0]
    assert engine.seat_token(g, A, "-card") is True
    assert g["coins"] == 1 and g["buys"] == 3, "+1 Buy pays for the one it spent"
    ok, err = buy_ls(g, A, "Borrow")
    assert not ok, "once per turn"


def test_quest_needs_the_whole_discard_to_pay_off():
    g = fresh(landscapes=["Quest"])
    to_buy(g, A, coins=0, buys=3)
    give_hand(g, A, ["Curse", "Estate"])
    assert buy_ls(g, A, "Quest")[0]
    assert decide(g, A, ids=["curses"])[0]
    assert "Gold" not in g["seats"][A]["discard"], "only ONE Curse in hand"
    g["landscapes"]["Quest"]["bought_turn"] = None
    give_hand(g, A, ["Curse", "Curse"])
    assert buy_ls(g, A, "Quest")[0]
    assert decide(g, A, ids=["curses"])[0]
    assert decide(g, A, cards=["Curse", "Curse"])[0]
    assert "Gold" in g["seats"][A]["discard"]


def test_save_returns_the_card_to_your_hand_after_the_cleanup_draw():
    g = fresh(landscapes=["Save"])
    to_buy(g, A, coins=1, buys=2)
    give_hand(g, A, ["Gold", "Copper"])
    give_deck(g, A, ["Estate"] * 10)
    assert buy_ls(g, A, "Save")[0]
    assert decide(g, A, cards=["Gold"])[0]
    assert g["seats"][A]["set_aside"] == ["Gold"]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert len(g["seats"][A]["hand"]) == 6, "5 drawn + the saved card"
    assert "Gold" in g["seats"][A]["hand"]
    assert g["seats"][A]["set_aside"] == []


def test_travelling_fair_lets_you_topdeck_what_you_gain():
    g = fresh(landscapes=["Travelling Fair"])
    to_buy(g, A, coins=5, buys=2)
    assert buy_ls(g, A, "Travelling Fair")[0]
    assert g["buys"] == 3
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert frame(g) is not None and frame(g)["card"] == "Travelling Fair"
    assert decide(g, A, ids=["yes"])[0]
    assert g["seats"][A]["deck"][0] == "Silver"


def test_bonfire_trashes_only_coppers_from_play():
    """2022: "Bonfire can now only trash Coppers"."""
    g = fresh(landscapes=["Bonfire"])
    to_buy(g, A, coins=3)
    g["seats"][A]["in_play"] = ["Copper", "Copper", "Silver"]
    assert buy_ls(g, A, "Bonfire")[0]
    assert sorted(frame(g)["constraint"]["cards"]) == ["Copper", "Copper"]
    assert decide(g, A, cards=["Copper", "Copper"])[0]
    assert g["trash"].count("Copper") == 2
    assert g["seats"][A]["in_play"] == ["Silver"]


def test_expedition_draws_two_more_at_the_end_of_the_turn():
    g = fresh(landscapes=["Expedition"])
    to_buy(g, A, coins=6, buys=3)
    give_hand(g, A, [])
    give_deck(g, A, ["Estate"] * 12)
    assert buy_ls(g, A, "Expedition")[0]
    assert buy_ls(g, A, "Expedition")[0], "you can buy several in a turn"
    assert mv(g, A, {"type": "end_phase"})[0]
    assert len(g["seats"][A]["hand"]) == 9


def test_ferry_moves_the_cost_token_and_discounts_that_pile():
    g = fresh(landscapes=["Ferry"], kingdom=KPLAIN)
    to_buy(g, A, coins=3)
    assert buy_ls(g, A, "Ferry")[0]
    assert "Copper" not in frame(g)["constraint"]["piles"], "an ACTION pile"
    assert decide(g, A, pile="Lost City")[0]
    assert engine.cost(g, "Lost City") == 3
    g["turn"] = B
    assert engine.cost(g, "Lost City") == 5, "only on the owner's turns"


def test_mission_takes_an_extra_turn_that_cannot_buy_cards():
    g = fresh(landscapes=["Mission", "Alms"])
    to_buy(g, A, coins=4)
    assert buy_ls(g, A, "Mission")[0]
    end_turn(g)
    assert g["turn"] == A and g["extra_turn"] is True
    assert g["turn_ctx"]["no_buy"] is True
    g["phase"] = "buy"
    g["coins"] = 8
    assert not [m for m in engine.legal_moves(g, A) if m["type"] == "buy"]
    ok, err = mv(g, A, {"type": "buy", "card": "Silver"})
    assert not ok and "can't buy cards" in err
    # ...but Events are still buyable
    assert {"type": "buy_landscape", "name": "Alms"} in engine.legal_moves(g, A)


def test_mission_cannot_give_a_third_turn_in_a_row():
    g = fresh(landscapes=["Mission"])
    to_buy(g, A, coins=4)
    assert buy_ls(g, A, "Mission")[0]
    end_turn(g)
    assert g["turn"] == A
    to_buy(g, A, coins=4)
    assert buy_ls(g, A, "Mission")[0]
    end_turn(g)
    assert g["turn"] == B, "no third turn in a row"


def test_outpost_and_mission_on_one_turn_give_one_mission_turn():
    """AMBIGUITY A6: both fire, only one extra turn is taken, and we take the
    stricter reading — it is a Mission turn (no buying cards). Outpost's 3-card
    draw still applies."""
    g = fresh(landscapes=["Mission"], expansions=("adventures", "seaside"),
              kingdom=["Outpost", "Magpie", "Port", "Ranger", "Artificer",
                       "Lost City", "Miser", "Raze", "Amulet", "Dungeon"])
    give_hand(g, A, ["Outpost"])
    give_deck(g, A, ["Estate"] * 12)
    assert play(g, A, "Outpost")[0]
    to_buy(g, A, coins=4)
    assert buy_ls(g, A, "Mission")[0]
    end_turn(g)
    assert g["turn"] == A and g["extra_turn"] is True
    assert g["turn_ctx"]["no_buy"] is True
    assert len(g["seats"][A]["hand"]) == 3, "Outpost's 3-card draw still applies"


def test_pilgrimage_gains_copies_of_up_to_three_named_cards_in_play():
    g = fresh(landscapes=["Pilgrimage"], kingdom=KPLAIN)
    to_buy(g, A, coins=9, buys=3)
    g["seats"][A]["in_play"] = ["Magpie", "Magpie", "Port", "Silver"]
    assert buy_ls(g, A, "Pilgrimage")[0]
    assert frame(g) is None, "the token was face up, so it turns face DOWN"
    g["landscapes"]["Pilgrimage"]["bought_turn"] = None
    assert buy_ls(g, A, "Pilgrimage")[0]
    assert sorted(frame(g)["constraint"]["cards"]) == ["Magpie", "Port", "Silver"]
    assert frame(g)["constraint"]["max"] == 3
    assert decide(g, A, cards=["Magpie", "Silver"])[0]
    assert g["seats"][A]["discard"].count("Magpie") == 1
    assert g["seats"][A]["discard"].count("Silver") == 1


def test_ball_takes_the_minus_coin_token_and_gains_two_cards():
    g = fresh(landscapes=["Ball"])
    to_buy(g, A, coins=5)
    assert buy_ls(g, A, "Ball")[0]
    assert engine.seat_token(g, A, "-coin") is True
    assert decide(g, A, pile="Silver")[0]
    assert decide(g, A, pile="Estate")[0]
    assert sorted(g["seats"][A]["discard"])[-2:] == ["Silver", "Estate"] \
        or {"Silver", "Estate"} <= set(g["seats"][A]["discard"])


def test_raid_gains_a_silver_per_silver_in_play_and_tokens_the_opponents():
    g = fresh(players=(A, B, C), landscapes=["Raid"])
    to_buy(g, A, coins=5)
    g["seats"][A]["in_play"] = ["Silver", "Silver", "Copper"]
    assert buy_ls(g, A, "Raid")[0]
    assert g["seats"][A]["discard"].count("Silver") == 2
    assert engine.seat_token(g, B, "-card") is True
    assert engine.seat_token(g, C, "-card") is True


def test_seaway_gains_an_action_and_moves_the_buy_token_to_its_pile():
    g = fresh(landscapes=["Seaway"], kingdom=KPLAIN)
    to_buy(g, A, coins=5)
    assert buy_ls(g, A, "Seaway")[0]
    piles = frame(g)["constraint"]["piles"]
    assert "Magpie" in piles and "Silver" not in piles
    assert decide(g, A, pile="Magpie")[0]
    assert "Magpie" in g["seats"][A]["discard"]
    assert engine.pile_tokens(g, "Magpie", A) == ["+buy"]


def test_trade_trashes_up_to_two_for_silvers():
    g = fresh(landscapes=["Trade"])
    to_buy(g, A, coins=5)
    give_hand(g, A, ["Estate", "Estate", "Copper"])
    assert buy_ls(g, A, "Trade")[0]
    assert decide(g, A, cards=["Estate", "Estate"])[0]
    assert g["trash"].count("Estate") == 2
    assert g["seats"][A]["discard"].count("Silver") == 2


def test_the_token_events_each_move_their_own_token():
    for name, kind in (("Lost Arts", "+action"), ("Training", "+coin"),
                       ("Pathfinding", "+card"), ("Plan", "trashing")):
        g = fresh(landscapes=[name], kingdom=KPLAIN)
        to_buy(g, A, coins=9)
        assert buy_ls(g, A, name)[0], name
        assert decide(g, A, pile="Magpie")[0]
        assert engine.pile_tokens(g, "Magpie", A) == [kind], name


def test_an_event_purchase_is_not_a_buy_for_haunted_woods():
    """2022 Haunted Woods triggers on a BOUGHT GAIN. Buying an Event gains
    nothing, so it must not fire — "nor if they buy an Event or Project"."""
    g = fresh(landscapes=["Alms"],
              kingdom=["Haunted Woods", "Magpie", "Port", "Ranger", "Artificer",
                       "Lost City", "Miser", "Raze", "Amulet", "Dungeon"])
    give_hand(g, A, ["Haunted Woods"])
    assert play(g, A, "Haunted Woods")[0]
    end_turn(g)
    assert g["turn"] == B
    to_buy(g, B, coins=0, buys=2)
    give_hand(g, B, ["Copper", "Estate"])
    assert buy_ls(g, B, "Alms")[0]
    assert len(g["seats"][B]["hand"]) == 2, "no topdecking for an Event"


def test_haunted_woods_topdecks_a_bought_gain():
    g = fresh(kingdom=["Haunted Woods", "Magpie", "Port", "Ranger", "Artificer",
                       "Lost City", "Miser", "Raze", "Amulet", "Dungeon"])
    give_hand(g, A, ["Haunted Woods"])
    assert play(g, A, "Haunted Woods")[0]
    end_turn(g)
    to_buy(g, B, coins=3)
    give_hand(g, B, ["Copper", "Estate"])
    assert mv(g, B, {"type": "buy", "card": "Silver"})[0]
    while g["pending_pid"] == B and frame(g)["card"] == "Haunted Woods":
        assert decide(g, B, order=list(frame(g)["constraint"]["cards"]))[0]
    assert g["seats"][B]["hand"] == []
    assert "Copper" in g["seats"][B]["deck"][:2]


def test_swamp_hag_curses_a_bought_gain_and_pays_next_turn():
    g = fresh(kingdom=["Swamp Hag", "Magpie", "Port", "Ranger", "Artificer",
                       "Lost City", "Miser", "Raze", "Amulet", "Dungeon"])
    give_hand(g, A, ["Swamp Hag"])
    assert play(g, A, "Swamp Hag")[0]
    end_turn(g)
    to_buy(g, B, coins=3)
    assert mv(g, B, {"type": "buy", "card": "Silver"})[0]
    assert "Curse" in g["seats"][B]["discard"]
    end_turn(g)
    assert g["turn"] == A
    assert g["coins"] == 3, "+$3 at the start of your next turn"


# ── Inheritance ───────────────────────────────────────────────────────────────

def test_inheritance_makes_every_estate_an_action_on_your_turns_only():
    g = fresh(landscapes=["Inheritance"], kingdom=KPLAIN)
    to_buy(g, A, coins=7)
    assert engine.has_type(g, "Estate", "action") is False
    assert buy_ls(g, A, "Inheritance")[0]
    piles = frame(g)["constraint"]["piles"]
    assert "Magpie" in piles and "Lost City" not in piles, "up to $4"
    assert decide(g, A, pile="Magpie")[0]
    assert engine.seat_token(g, A, "estate") == "Magpie"
    assert g["seats"][A]["set_aside"] == ["Magpie"]
    assert engine.has_type(g, "Estate", "action") is True
    assert engine.has_type(g, "Estate", "command") is True
    g["turn"] = B
    assert engine.has_type(g, "Estate", "action") is False, "only on YOUR turns"


def test_an_inherited_estate_plays_the_set_aside_card():
    g = fresh(landscapes=["Inheritance"], kingdom=KPLAIN)
    to_buy(g, A, coins=7)
    assert buy_ls(g, A, "Inheritance")[0]
    assert decide(g, A, pile="Magpie")[0]
    g["phase"] = "action"
    g["actions"] = 1
    give_hand(g, A, ["Estate"])
    give_deck(g, A, ["Copper", "Estate", "Copper"])
    assert play(g, A, "Estate")[0]
    assert "Estate" in g["seats"][A]["in_play"]
    assert g["seats"][A]["set_aside"] == ["Magpie"], "the set-aside card stays"
    assert len(g["seats"][A]["hand"]) >= 1, "Magpie's +1 Card ran"


def test_the_set_aside_card_is_not_gained_and_still_counts_as_yours():
    """"The Action card you set aside from the Supply is counted as one of your
    cards at the end of the game. This is not considered gaining a card." """
    g = fresh(landscapes=["Inheritance"], kingdom=KPLAIN)
    to_buy(g, A, coins=7)
    n = len([e for e in g["log"] if e.get("event") == "gain"])
    before = engine.pile_count(g, "Magpie")
    assert buy_ls(g, A, "Inheritance")[0]
    assert decide(g, A, pile="Magpie")[0]
    assert len([e for e in g["log"] if e.get("event") == "gain"]) == n
    assert engine.pile_count(g, "Magpie") == before - 1
    assert "Magpie" in engine.owned_cards(g, A)


def test_estates_are_not_actions_once_the_game_is_over():
    """"Estates are not Action cards when you score for Vineyards, as it's not
    your turn at the end of the game." """
    g = fresh(landscapes=["Inheritance"], kingdom=KPLAIN)
    engine.set_seat_token(g, A, "estate", "Magpie")
    g["turn"] = A
    assert engine.has_type(g, "Estate", "action") is True
    g["over"] = True
    assert engine.has_type(g, "Estate", "action") is False


def test_inheritance_is_once_per_game_per_player():
    g = fresh(landscapes=["Inheritance"], kingdom=KPLAIN)
    to_buy(g, A, coins=20, buys=3)
    assert buy_ls(g, A, "Inheritance")[0]
    assert decide(g, A, pile="Magpie")[0]
    ok, err = buy_ls(g, A, "Inheritance")
    assert not ok and "this game" in err
    assert engine.landscape_gate(g, B, "Inheritance") is None


# ── setup ─────────────────────────────────────────────────────────────────────

def test_an_adventures_board_deals_events_from_the_randomizer_mix():
    seen = set()
    for seed in range(40):
        g = engine.new_game([A, B], ["adventures"], seed=seed)
        assert len(g["landscapes"]) <= 2
        seen |= set(g["landscapes"])
    assert seen, "some board must deal an Event"
    assert seen <= set(cards.LANDSCAPES)


def test_every_event_has_an_ability_registered():
    """Every BUYABLE landscape owes an ability. A Landmark (ph. 8) is never
    bought — its ability is a scoring fn or a trigger — so the equality is
    against the buyable kinds rather than the whole table."""
    buyable = {n for n, d in cards.LANDSCAPES.items()
               if d["kind"] in cards.BUYABLE_LANDSCAPE_KINDS}
    assert buyable == set(effects.LANDSCAPE_FX)


def test_a_full_adventures_game_round_trips_through_json_and_migrate():
    g = engine.new_game([A, B], ["adventures"], seed=11, kingdom=list(KRES),
                        landscapes=["Ferry", "Inheritance"])
    rng = engine.random.Random(3)
    for _ in range(400):
        if g["over"]:
            break
        pid = g["pending_pid"] or g["turn"]
        mv(g, pid, rng.choice(engine.legal_moves(g, pid)))
    blob = json.loads(json.dumps(g))
    engine.migrate(blob)
    assert blob == json.loads(json.dumps(g)), "migrate mutated a current save"
    for viewer in (A, B, None):
        json.dumps(engine.player_view(blob, viewer))
