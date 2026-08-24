"""Menagerie, half A — the 20 cards whose interest is their own play ability
(plus Horse) and all 20 EVENTS.

Horse, Supplies, Camel Train, Goatherd, Scrap, Snowy Village, Bounty Hunter,
Cavalry, Groom, Hostelry, Displace, Hunting Lodge, Kiln, Livery, Paddock,
Sanctuary, Destrier, Fisherman, Wayfarer, Animal Fair; Delay, Desperation,
Gamble, Pursue, Ride, Toil, Enhance, March, Transport, Banish, Bargain, Invest,
Seize the Day, Commerce, Demand, Stampede, Reap, Enclave, Alliance, Populate.

Positions are arranged by mutating the game dict (the repo's board-fixture
idiom); `give_hand` breaks card conservation, so nothing here asserts the
census — `test_soak` owns that.

Headline rulings pinned here:
  * **Horse is REMOVED FROM PLAY**, and a Throne Room gives +4 Cards / +2
    Actions with only ONE return; its cost is $3 for any ability that asks.
  * **Exiling from the Supply is not gaining** — no `gain` event, no when-gain
    ability, and the card still leaves its pile.
  * **Bounty Hunter's Exile is mandatory** and pays $3 only for a name you did
    not already have on the mat (so a Throne Room pays twice only for two
    different names).
  * **Goatherd counts the seat BEFORE you**, and counts TRASHES, not names.
  * **Scrap picks exactly one option per $1, all different**, capped at six,
    and resolves them in the printed order.
  * **Snowy Village drops every later +Action** — including a spent Villager
    (ph. 9) — but never takes back Actions you already had.
  * **Cavalry's when-gain returns you to your Action phase** and ENDS the Buy
    phase (ph. 8/9's `return_to_action_phase`), own turn only.
  * **Kiln's copy is gained BEFORE the played card resolves**, so a Livery
    played after a Kiln gives no Horse for its own copy — and Kiln fires on an
    ordinary TREASURE play, which is what ph. 10 widened `before_play` for.
  * **Wayfarer copies the last card gained by ANY player**, ignores its own
    gains, and bypasses cost reduction while it is copying.
  * **Animal Fair may be bought without $7** by trashing an Action, and the
    trash happens before the gain.
  * **Gamble (2025) discards first, then plays out of the discard pile.**
  * **Reap (2025) gains its Gold straight to the set-aside area.**
"""

from games.dontminion import cards, effects, engine

A, B, C = "alice", "bob", "carol"

# half A's own cards, in two boards (20 cards, 10 to a kingdom). Both carry a
# Horse producer, so both games include the Horse pile.
KA = ["Supplies", "Camel Train", "Goatherd", "Scrap", "Snowy Village",
      "Bounty Hunter", "Cavalry", "Groom", "Hostelry", "Displace"]
KB = ["Hunting Lodge", "Kiln", "Livery", "Paddock", "Sanctuary", "Destrier",
      "Fisherman", "Wayfarer", "Animal Fair", "Scrap"]
# mixed boards for the cross-set corners
KM = ["Throne Room", "Village", "Smithy", "Militia", "Mill", "Cavalry",
      "Groom", "Kiln", "Livery", "Scrap"]
# a plain board for the EVENTS: ten Action piles, none of which triggers on a
# gain, so an Event's own behaviour is what the test observes
KEV = ["Village", "Smithy", "Market", "Festival", "Laboratory", "Moat",
       "Cellar", "Workshop", "Vassal", "Mill"]


def fresh(players=(A, B), seed=7, kingdom=tuple(KA),
          expansions=("menagerie", "base", "intrigue"), landscapes=()):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom), landscapes=list(landscapes))


def give_hand(g, pid, cards_):
    g["seats"][pid]["hand"] = list(cards_)


def give_deck(g, pid, cards_):
    g["seats"][pid]["deck"] = list(cards_)


def give_discard(g, pid, cards_):
    g["seats"][pid]["discard"] = list(cards_)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def decide(g, pid, **payload):
    ok, err = engine.apply_move(g, pid, {"type": "decision", **payload})
    assert ok, err
    return ok, err


def play(g, pid, card):
    ok, err = mv(g, pid, {"type": "play_action", "card": card})
    assert ok, err
    return ok, err


def buy_event(g, pid, name, coins=None):
    g["phase"] = "buy"
    if coins is not None:
        g["coins"] = coins
    ok, err = mv(g, pid, {"type": "buy_landscape", "name": name})
    assert ok, err
    return ok, err


def frame(g):
    return g["pending"][-1] if g["pending"] else None


def opt_ids(g):
    return [o["id"] for o in frame(g)["constraint"]["options"]]


def pick(g, pid, option_id):
    """Answer the open choose_option BY ID, never by index — a guessed index
    passes for the wrong reason the day the option order changes."""
    ids = opt_ids(g)
    assert option_id in ids, ids
    return decide(g, pid, ids=[option_id])


def events(g, name):
    return [e for e in g["log"] if e.get("event") == name]


def end_turn(g, pid):
    """Drive pid's turn to its end (through both phases)."""
    if g["phase"] == "action":
        ok, err = mv(g, pid, {"type": "end_phase"})
        assert ok, err
    if g["over"] or g["pending"]:
        return
    ok, err = mv(g, pid, {"type": "end_phase"})
    assert ok, err


# ══ THE HORSE PILE ═══════════════════════════════════════════════════════════

def test_the_horse_pile_is_thirty_cards_outside_the_supply():
    g = fresh()
    assert engine.pile_count(g, "Horse") == 30
    assert "Horse" not in g["supply"] and not engine.is_supply_pile(g, "Horse")
    # "the cost of Horse is $3 FOR ANY ABILITY THAT REFERS TO ITS COST"
    assert engine.cost(g, "Horse") == 3


def test_a_horse_pile_that_empties_is_not_an_empty_supply_pile():
    """"Non-Supply piles are NOT counted" for the three-empty-piles end — and
    Paddock/Animal Fair count the same thing."""
    g = fresh()
    g["nonsupply"]["Horse"] = 0
    assert engine.count_empty_piles(g) == 0


def test_horse_draws_two_gives_an_action_and_returns_to_its_pile():
    g = fresh()
    give_hand(g, A, ["Horse"])
    give_deck(g, A, ["Gold", "Silver", "Copper"])
    before = engine.pile_count(g, "Horse")
    play(g, A, "Horse")
    assert g["seats"][A]["hand"] == ["Gold", "Silver"]
    assert g["actions"] == 1                       # 1 - 1 spent + 1
    assert g["seats"][A]["in_play"] == []          # REMOVED FROM PLAY
    assert engine.pile_count(g, "Horse") == before + 1
    assert events(g, "return_to_pile")[-1]["card"] == "Horse"


def test_a_throne_roomed_horse_draws_four_and_returns_once():
    """"If you play Horse WITHOUT MOVING IT INTO PLAY, you still get +2 Cards
    and +1 Action. (Throne Room + Horse will give you +4 Cards and +2
    Actions.)" — the second play finds nothing on the table to return."""
    g = fresh(kingdom=KM)
    give_hand(g, A, ["Throne Room", "Horse"])
    give_deck(g, A, ["Gold"] * 6)
    before = engine.pile_count(g, "Horse")
    play(g, A, "Throne Room")
    decide(g, A, cards=["Horse"])
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 4
    assert g["actions"] == 2                       # 1 - 1 + 1 + 1
    assert engine.pile_count(g, "Horse") == before + 1
    assert g["seats"][A]["in_play"] == ["Throne Room"]


# ══ $2 ═══════════════════════════════════════════════════════════════════════

# --- Supplies ----------------------------------------------------------------

def test_supplies_pays_a_coin_and_gains_a_horse_onto_the_deck():
    g = fresh()
    give_hand(g, A, ["Supplies"])
    give_deck(g, A, ["Estate"])
    g["phase"] = "buy"
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Supplies"})
    assert ok, err
    engine._drive(g)
    assert g["coins"] == 1
    assert g["seats"][A]["deck"] == ["Horse", "Estate"]   # ONTO YOUR DECK


def test_supplies_still_pays_its_coin_with_an_empty_horse_pile():
    """"You get the initial +$1 even if there are no Horses left"."""
    g = fresh()
    g["nonsupply"]["Horse"] = 0
    give_hand(g, A, ["Supplies"])
    give_deck(g, A, [])
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Supplies"})[0]
    engine._drive(g)
    assert g["coins"] == 1 and g["seats"][A]["deck"] == []


def test_supplies_is_manual_so_the_autoplay_button_skips_it():
    """Bucket 1: its play GAINS a card, and a gain can open a decision frame
    (Watchtower, Sleigh, Sheepdog, the Exile mat) halfway through a bulk play
    that is ONE move with ONE undo snapshot."""
    assert "Supplies" in effects.MANUAL_TREASURES
    g = fresh()
    give_hand(g, A, ["Supplies", "Copper"])
    g["phase"] = "buy"
    assert engine.autoplay_treasures(g, A) == ["Copper"]
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert g["seats"][A]["hand"] == ["Supplies"]
    assert g["coins"] == 1


# ══ $3 ═══════════════════════════════════════════════════════════════════════

# --- Camel Train -------------------------------------------------------------

def test_camel_train_exiles_a_non_victory_card_from_the_supply():
    g = fresh()
    give_hand(g, A, ["Camel Train"])
    play(g, A, "Camel Train")
    piles = frame(g)["constraint"]["piles"]
    assert "Silver" in piles
    for victory in ("Estate", "Duchy", "Province", "Gardens"):
        assert victory not in piles
    before = engine.pile_count(g, "Silver")
    decide(g, A, pile="Silver")
    engine._drive(g)
    assert g["seats"][A]["exile"] == ["Silver"]
    assert engine.pile_count(g, "Silver") == before - 1


def test_exiling_from_the_supply_is_not_a_gain():
    """"Exiling cards from the Supply is NOT considered gaining cards" — so no
    `gain` event fires and no when-gain ability sees it. Camel Train's own
    when-gain is the control: gaining one really does trigger."""
    g = fresh()
    give_hand(g, A, ["Camel Train"])
    play(g, A, "Camel Train")
    decide(g, A, pile="Silver")
    engine._drive(g)
    assert not events(g, "gain")
    assert events(g, "exile")[-1]["source"] == "supply"
    # ...the control
    engine.gain(g, A, "Silver")
    engine._drive(g)
    assert events(g, "gain")


def test_gaining_a_camel_train_exiles_a_gold_from_the_supply():
    g = fresh()
    before = engine.pile_count(g, "Gold")
    engine.gain(g, A, "Camel Train")
    engine._drive(g)
    assert g["seats"][A]["exile"] == ["Gold"]
    assert engine.pile_count(g, "Gold") == before - 1
    assert g["seats"][A]["discard"] == ["Camel Train"]


def test_gaining_a_camel_train_with_no_golds_left_exiles_nothing():
    g = fresh()
    g["supply"]["Gold"] = 0
    engine.gain(g, A, "Camel Train")
    engine._drive(g)
    assert g["seats"][A]["exile"] == []


# --- Goatherd ----------------------------------------------------------------

def test_goatherd_draws_one_per_card_the_player_to_your_right_trashed():
    g = fresh()
    g["last_turn_trashes"][B] = 2          # in 2p, B is the seat before A
    give_hand(g, A, ["Goatherd", "Copper"])
    give_deck(g, A, ["Gold"] * 4)
    play(g, A, "Goatherd")
    assert g["actions"] == 1
    decide(g, A, cards=[])                 # "you MAY trash"
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Copper", "Gold", "Gold"]
    assert g["trash"] == []


def test_goatherd_reads_the_seat_before_you_in_a_three_player_game():
    """"The player to your right" is the previous seat in turn order — the
    Smugglers/Monkey neighbour. Pinned with three seats so a 2-player test
    cannot pass by accident (there, both readings agree)."""
    g = fresh(players=(A, B, C))
    assert g["players"] == [A, B, C]
    g["last_turn_trashes"] = {A: 5, B: 1}
    g["turn"] = C
    give_hand(g, C, ["Goatherd"])
    give_deck(g, C, ["Gold"] * 4)
    play(g, C, "Goatherd")
    engine._drive(g)
    assert g["seats"][C]["hand"] == ["Gold"], "C's right-hand player is B, not A"


def test_the_goatherd_trash_resolves_before_its_draw():
    """"You may trash a card from your hand. +1 Card per card…" — the trash is
    first, so its own on-trash ability resolves before anything is drawn."""
    g = fresh()
    g["last_turn_trashes"][B] = 1
    give_hand(g, A, ["Goatherd", "Estate"])
    give_deck(g, A, ["Gold"] * 4)
    play(g, A, "Goatherd")
    decide(g, A, cards=["Estate"])
    engine._drive(g)
    assert g["trash"] == ["Estate"]
    assert g["seats"][A]["hand"] == ["Gold"]
    kinds = [e["event"] for e in g["log"] if e.get("event") in ("trash", "draw")]
    assert kinds[-2:] == ["trash", "draw"]


def test_last_turn_trashes_is_a_count_not_a_card_list():
    """"Goatherd counts HOW MANY TIMES your right-hand player trashed a card
    (so a Fortress trashed twice counts as two)" — a name list would collapse
    two copies into one."""
    g = fresh()
    g["turn"] = B
    give_hand(g, B, ["Copper", "Copper"])
    give_hand(g, A, ["Goatherd"])          # A's hand is untouched by B's Clean-up
    give_deck(g, A, ["Gold"] * 4)
    engine.trash(g, B, ["Copper", "Copper"])
    engine._drive(g)
    end_turn(g, B)
    engine._drive(g)
    assert g["last_turn_trashes"][B] == 2
    assert g["turn"] == A
    play(g, A, "Goatherd")
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Gold", "Gold"]


# --- Scrap -------------------------------------------------------------------

def test_scrap_picks_exactly_one_different_option_per_dollar():
    g = fresh()
    give_hand(g, A, ["Scrap", "Silver"])          # Silver costs $3
    give_deck(g, A, ["Gold"] * 4)
    play(g, A, "Scrap")
    decide(g, A, cards=["Silver"])
    engine._drive(g)
    f = frame(g)
    assert f["kind"] == "choose_option" and f["card"] == "Scrap"
    assert f["constraint"]["pick"] == 3 and f["constraint"]["distinct"]
    assert opt_ids(g) == ["card", "action", "buy", "coin", "silver", "horse"]
    # NOT OPTIONAL: you can't choose to do less
    assert not mv(g, A, {"type": "decision", "ids": ["card"]})[0]
    assert not mv(g, A, {"type": "decision", "ids": ["card", "card", "card"]})[0]
    decide(g, A, ids=["card", "buy", "horse"])
    engine._drive(g)
    assert g["trash"] == ["Silver"]
    assert g["seats"][A]["hand"] == ["Gold"]
    assert g["buys"] == 2
    assert g["seats"][A]["discard"] == ["Horse"]


def test_scrap_resolves_its_options_in_the_printed_order():
    """"You have to choose the options first, then do them, IN THE ORDER
    GIVEN" — so a Silver gain precedes a Horse gain however they were picked."""
    g = fresh()
    give_hand(g, A, ["Scrap", "Gold"])            # Gold costs $6 -> all six
    give_deck(g, A, ["Estate"] * 4)
    play(g, A, "Scrap")
    decide(g, A, cards=["Gold"])
    engine._drive(g)
    decide(g, A, ids=["horse", "silver", "coin", "buy", "action", "card"])
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Silver", "Horse"]
    assert g["coins"] == 1 and g["buys"] == 2 and g["actions"] == 1
    assert g["seats"][A]["hand"] == ["Estate"]


def test_scrap_caps_at_six_bonuses():
    """"You get MAXIMUM SIX bonuses, even if the trashed card costs more"."""
    g = fresh()
    give_hand(g, A, ["Scrap", "Province"])        # $8
    play(g, A, "Scrap")
    decide(g, A, cards=["Province"])
    engine._drive(g)
    assert frame(g)["constraint"]["pick"] == 6


def test_scrap_on_a_free_card_gives_no_options_at_all():
    g = fresh()
    give_hand(g, A, ["Scrap", "Copper"])          # $0
    play(g, A, "Scrap")
    decide(g, A, cards=["Copper"])
    engine._drive(g)
    assert g["pending"] == []
    assert g["trash"] == ["Copper"]


def test_a_cost_reduction_gives_scrap_fewer_options():
    """"If there is a COST REDUCTION, Scrap will give you fewer options"."""
    g = fresh()
    g["turn_ctx"]["bridges"] = 1
    give_hand(g, A, ["Scrap", "Silver"])
    play(g, A, "Scrap")
    decide(g, A, cards=["Silver"])
    engine._drive(g)
    assert frame(g)["constraint"]["pick"] == 2


# --- Snowy Village -----------------------------------------------------------

def test_snowy_village_gives_four_actions_then_ignores_further_ones():
    g = fresh()
    give_hand(g, A, ["Snowy Village"])
    give_deck(g, A, ["Village", "Gold"])
    play(g, A, "Snowy Village")
    assert g["actions"] == 4                       # 1 - 1 + 4
    assert g["buys"] == 2
    assert g["seats"][A]["hand"] == ["Village"]
    play(g, A, "Village")                          # +1 Card +2 Actions
    assert g["actions"] == 3, "the +2 Actions were ignored, the spend was not"
    assert events(g, "actions_ignored")[-1]["count"] == 2


def test_snowy_village_never_takes_back_actions_you_already_had():
    """"Only +Actions you would get AFTER playing Snowy Village are ignored
    (EFFECTS ARE IMMEDIATE). You keep any Actions you already had"."""
    g = fresh()
    g["actions"] = 5
    give_hand(g, A, ["Snowy Village"])
    give_deck(g, A, ["Gold"])
    play(g, A, "Snowy Village")
    assert g["actions"] == 8                       # 5 - 1 + 4


def test_after_snowy_village_a_spent_villager_gives_no_action():
    """"After having played Snowy Village, SPENDING VILLAGER TOKENS will not
    give you +Actions" — ph. 9's Villagers obey it for free, because spending
    one is "+1 Action" through `add_actions`."""
    g = fresh()
    g["villagers"][A] = 2
    give_hand(g, A, ["Snowy Village"])
    # an Action card in the drawn hand, so the phase does not auto-advance out
    # from under the Villager (which is Action-phase-only)
    give_deck(g, A, ["Village"])
    play(g, A, "Snowy Village")
    before = g["actions"]
    ok, err = mv(g, A, {"type": "spend", "what": "villagers", "n": 1})
    assert ok, err
    assert g["actions"] == before and g["villagers"][A] == 1


def test_ignore_actions_does_not_leak_into_the_next_turn():
    g = fresh()
    give_hand(g, A, ["Snowy Village"])
    give_deck(g, A, ["Gold"] * 6)
    play(g, A, "Snowy Village")
    end_turn(g, A)
    engine._drive(g)
    assert g["turn_ctx"]["ignore_actions"] is False


# ══ $4 ═══════════════════════════════════════════════════════════════════════

# --- Bounty Hunter -----------------------------------------------------------

def test_bounty_hunter_exiles_and_pays_three_for_a_new_name():
    g = fresh()
    give_hand(g, A, ["Bounty Hunter", "Estate", "Copper"])
    play(g, A, "Bounty Hunter")
    assert g["actions"] == 1
    f = frame(g)
    assert f["constraint"]["min"] == 1, "you HAVE TO Exile a card"
    decide(g, A, cards=["Estate"])
    engine._drive(g)
    assert g["seats"][A]["exile"] == ["Estate"]
    assert g["coins"] == 3


def test_bounty_hunter_pays_nothing_for_a_name_already_in_exile():
    """"+$3 only if the Exiled card is now the ONLY COPY OF THAT CARD you have
    in Exile" (VARIABLE $ PRODUCTION)."""
    g = fresh()
    g["seats"][A]["exile"] = ["Estate"]
    give_hand(g, A, ["Bounty Hunter", "Estate"])
    play(g, A, "Bounty Hunter")
    decide(g, A, cards=["Estate"])
    engine._drive(g)
    assert g["seats"][A]["exile"] == ["Estate", "Estate"]
    assert g["coins"] == 0


def test_bounty_hunter_with_an_empty_hand_gets_no_prompt_and_no_coins():
    """"If you can't Exile a card, you don't get +$3"."""
    g = fresh()
    give_hand(g, A, ["Bounty Hunter"])
    play(g, A, "Bounty Hunter")
    assert g["pending"] == []
    assert g["coins"] == 0 and g["actions"] == 1


def test_a_throne_roomed_bounty_hunter_pays_twice_only_for_two_names():
    """"Throne Room + Bounty Hunter will give you +$3 TWICE if you Exile a
    DIFFERENT card each time (with no copies in Exile already)"."""
    g = fresh(kingdom=["Throne Room", "Bounty Hunter", "Village", "Smithy",
                       "Militia", "Mill", "Cavalry", "Groom", "Kiln", "Scrap"])
    give_hand(g, A, ["Throne Room", "Bounty Hunter", "Estate", "Copper"])
    play(g, A, "Throne Room")
    decide(g, A, cards=["Bounty Hunter"])
    engine._drive(g)
    decide(g, A, cards=["Estate"])
    engine._drive(g)
    decide(g, A, cards=["Copper"])
    engine._drive(g)
    assert sorted(g["seats"][A]["exile"]) == ["Copper", "Estate"]
    assert g["coins"] == 6

    # ...and the counter-case: the SAME name twice pays only once
    g2 = fresh(kingdom=["Throne Room", "Bounty Hunter", "Village", "Smithy",
                        "Militia", "Mill", "Cavalry", "Groom", "Kiln", "Scrap"])
    give_hand(g2, A, ["Throne Room", "Bounty Hunter", "Copper", "Copper"])
    play(g2, A, "Throne Room")
    decide(g2, A, cards=["Bounty Hunter"])
    engine._drive(g2)
    decide(g2, A, cards=["Copper"])
    engine._drive(g2)
    decide(g2, A, cards=["Copper"])
    engine._drive(g2)
    assert g2["seats"][A]["exile"] == ["Copper", "Copper"]
    assert g2["coins"] == 3


# --- Cavalry -----------------------------------------------------------------

def test_cavalry_gains_two_horses():
    g = fresh()
    give_hand(g, A, ["Cavalry"])
    before = engine.pile_count(g, "Horse")
    play(g, A, "Cavalry")
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Horse", "Horse"]
    assert engine.pile_count(g, "Horse") == before - 2


def test_gaining_cavalry_draws_two_and_gives_a_buy():
    g = fresh()
    give_deck(g, A, ["Gold", "Silver", "Copper"])
    give_hand(g, A, [])
    engine.gain(g, A, "Cavalry")
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Gold", "Silver"]
    assert g["buys"] == 2


def test_gaining_cavalry_in_your_buy_phase_returns_you_to_your_action_phase():
    """"…keeping any Actions, Buys and $ you had left, plus the +1 Buy", and
    "when you return to your Action phase, YOUR BUY PHASE ENDS"."""
    g = fresh()
    g["phase"] = "buy"
    g["coins"] = 5
    g["actions"] = 1
    # an Action card among the 2 drawn, so the auto-advance does not send the
    # player straight back to the Buy phase they just left
    give_deck(g, A, ["Village", "Silver"])
    give_hand(g, A, [])
    ok, err = mv(g, A, {"type": "buy", "card": "Cavalry"})
    assert ok, err
    engine._drive(g)
    assert g["phase"] == "action"
    assert g["seats"][A]["hand"] == ["Village", "Silver"]
    assert g["coins"] == 1 and g["actions"] == 1
    assert g["buys"] == 1                # 1 - 1 for the buy + 1 from Cavalry
    assert g["turn_ctx"]["bought"] is False, "the treasure half is open again"
    # ...and the Buy phase really ENDED: its per-phase counter is back to zero
    # (the Cavalry gain had already bumped it), which is what makes
    # Exploration / Merchant Guild / Treasury / Wine Merchant fire again.
    assert g["turn_ctx"]["buy_gains"] == 0
    assert events(g, "phase")[-1]["phase"] == "action"


def test_gaining_cavalry_off_turn_changes_nobody_s_phase():
    """"If you gain Cavalry when it's not your turn … the +1 Buy is not usable,
    and you don't get an Action phase"."""
    g = fresh()
    g["phase"] = "buy"
    give_deck(g, B, ["Gold", "Silver"])
    give_hand(g, B, [])
    engine.gain(g, B, "Cavalry")
    engine._drive(g)
    assert g["phase"] == "buy" and g["turn"] == A
    assert g["seats"][B]["hand"] == ["Gold", "Silver"], "drawing is not a pool"
    assert events(g, "off_turn_bonus"), "the +1 Buy evaporated"


# --- Groom -------------------------------------------------------------------

def test_groom_gains_a_horse_for_an_action_card():
    g = fresh()
    give_hand(g, A, ["Groom"])
    play(g, A, "Groom")
    decide(g, A, pile="Camel Train")       # $3 Action
    engine._drive(g)
    assert sorted(g["seats"][A]["discard"]) == ["Camel Train", "Horse"]


def test_groom_gains_a_silver_for_a_treasure_card():
    g = fresh()
    give_hand(g, A, ["Groom"])
    play(g, A, "Groom")
    decide(g, A, pile="Supplies")          # $2 Treasure
    engine._drive(g)
    assert sorted(g["seats"][A]["discard"]) == ["Silver", "Supplies"]


def test_groom_draws_and_gives_an_action_for_a_victory_card():
    g = fresh()
    give_hand(g, A, ["Groom"])
    give_deck(g, A, ["Gold"])
    play(g, A, "Groom")
    decide(g, A, pile="Estate")
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Gold"]
    assert g["actions"] == 1
    assert g["seats"][A]["discard"] == ["Estate"]


def test_groom_pays_every_relevant_bonus_for_a_multi_type_card():
    """"If you gain a card that has SEVERAL of the types, you get ALL relevant
    bonuses" — Mill is an Action AND a Victory card."""
    g = fresh(kingdom=KM)
    give_hand(g, A, ["Groom"])
    give_deck(g, A, ["Gold"])
    play(g, A, "Groom")
    decide(g, A, pile="Mill")
    engine._drive(g)
    assert sorted(g["seats"][A]["discard"]) == ["Horse", "Mill"]
    assert g["seats"][A]["hand"] == ["Gold"] and g["actions"] == 1


def test_groom_gives_nothing_when_the_gain_fails():
    """"'It' refers to the gained card. If you didn't gain the card, you don't
    get any bonus."""
    g = fresh()
    for p in list(g["supply"]):
        if engine.cost_le(g, p, 4):
            g["supply"][p] = 0
    give_hand(g, A, ["Groom"])
    play(g, A, "Groom")
    assert g["pending"] == []
    assert g["seats"][A]["discard"] == []


# --- Hostelry ----------------------------------------------------------------

def test_hostelry_draws_one_and_gives_two_actions():
    g = fresh()
    give_hand(g, A, ["Hostelry"])
    give_deck(g, A, ["Gold"])
    play(g, A, "Hostelry")
    assert g["seats"][A]["hand"] == ["Gold"] and g["actions"] == 2


def test_gaining_hostelry_may_discard_treasures_revealed_for_horses():
    """"You gain the Horses ON WHEN-GAIN" and "you REVEAL the Treasures before
    discarding them"."""
    g = fresh()
    give_hand(g, A, ["Copper", "Silver", "Estate"])
    before = engine.pile_count(g, "Horse")
    engine.gain(g, A, "Hostelry")
    engine._drive(g)
    f = frame(g)
    assert f["card"] == "Hostelry"
    assert f["constraint"]["cards"] == ["Copper", "Silver"]
    assert f["constraint"]["min"] == 0 and f["constraint"]["max"] == 2
    decide(g, A, cards=["Copper", "Silver"])
    engine._drive(g)
    assert engine.pile_count(g, "Horse") == before - 2
    assert g["seats"][A]["hand"] == ["Estate"]
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Horse", "Horse",
                                                "Hostelry", "Silver"]
    assert events(g, "reveal")[-1]["cards"] == ["Copper", "Silver"]


def test_the_hostelry_discard_is_optional_and_absent_without_treasures():
    g = fresh()
    give_hand(g, A, ["Copper"])
    engine.gain(g, A, "Hostelry")
    engine._drive(g)
    decide(g, A, cards=[])
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Copper"]
    assert g["seats"][A]["discard"] == ["Hostelry"]

    g2 = fresh()
    give_hand(g2, A, ["Estate"])
    engine.gain(g2, A, "Hostelry")
    engine._drive(g2)
    assert g2["pending"] == []


# ══ $5 ═══════════════════════════════════════════════════════════════════════

# --- Displace ----------------------------------------------------------------

def test_displace_exiles_a_card_and_gains_a_differently_named_one():
    g = fresh()
    give_hand(g, A, ["Displace", "Estate"])        # Estate $2 -> up to $4
    play(g, A, "Displace")
    decide(g, A, cards=["Estate"])
    engine._drive(g)
    assert g["seats"][A]["exile"] == ["Estate"]
    piles = frame(g)["constraint"]["piles"]
    assert "Estate" not in piles, "a DIFFERENTLY NAMED card"
    assert "Silver" in piles and "Cavalry" in piles      # $3 and $4
    assert "Displace" not in piles, "$5 is more than $2 + $2"
    decide(g, A, pile="Cavalry")
    engine._drive(g)
    assert "Cavalry" in g["seats"][A]["discard"]


def test_displace_with_an_empty_hand_does_nothing():
    g = fresh()
    give_hand(g, A, ["Displace"])
    play(g, A, "Displace")
    assert g["pending"] == [] and g["seats"][A]["exile"] == []


# --- Hunting Lodge -----------------------------------------------------------

def test_hunting_lodge_draws_one_gives_two_actions_and_offers_the_swap():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Hunting Lodge", "Estate"])
    give_deck(g, A, ["Gold"] + ["Silver"] * 6)
    play(g, A, "Hunting Lodge")
    assert g["actions"] == 2
    assert opt_ids(g) == ["discard", "keep"]
    pick(g, A, "discard")
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Silver"] * 5
    assert sorted(g["seats"][A]["discard"]) == ["Estate", "Gold"]


def test_hunting_lodge_may_be_declined():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Hunting Lodge", "Estate"])
    give_deck(g, A, ["Gold"] + ["Silver"] * 6)
    play(g, A, "Hunting Lodge")
    pick(g, A, "keep")
    engine._drive(g)
    assert sorted(g["seats"][A]["hand"]) == ["Estate", "Gold"]


def test_hunting_lodge_with_an_empty_hand_still_draws_five():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Hunting Lodge"])
    give_deck(g, A, ["Silver"] * 6)
    play(g, A, "Hunting Lodge")
    pick(g, A, "discard")                  # the one card drawn is the whole hand
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Silver"] * 5


# --- Kiln --------------------------------------------------------------------

def test_kiln_offers_a_copy_of_the_next_action_played():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Kiln", "Sanctuary"])
    give_deck(g, A, ["Gold"] * 4)
    g["actions"] = 2
    play(g, A, "Kiln")
    assert g["coins"] == 2 and g["pending"] == []
    play(g, A, "Sanctuary")
    f = frame(g)
    assert f["card"] == "Kiln" and opt_ids(g) == ["yes", "no"]
    pick(g, A, "yes")
    engine._drive(g)
    assert "Sanctuary" in g["seats"][A]["discard"]


def test_kiln_fires_on_an_ordinary_treasure_play():
    """"The next time you play a card (OF ANY TYPE)" — ph. 10 widened
    `before_play` past Actions for exactly this, and the consumer resolves
    BEFORE the Treasure's own coins."""
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Kiln", "Copper"])
    play(g, A, "Kiln")
    g["phase"] = "buy"
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Copper"})
    assert ok, err
    engine._drive(g)
    assert frame(g)["card"] == "Kiln"
    pick(g, A, "yes")
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Copper"]
    assert g["coins"] == 3                 # $2 from Kiln + $1 from the Copper


def test_kiln_is_spent_on_the_very_next_card_played():
    """"You can only use Kiln on the VERY NEXT card you play" — spent whether
    or not you took the copy."""
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Kiln", "Copper", "Silver"])
    play(g, A, "Kiln")
    g["phase"] = "buy"
    assert mv(g, A, {"type": "play_treasure", "card": "Copper"})[0]
    engine._drive(g)
    pick(g, A, "no")
    engine._drive(g)
    assert mv(g, A, {"type": "play_treasure", "card": "Silver"})[0]
    engine._drive(g)
    assert g["pending"] == [], "Kiln is spent"
    assert g["seats"][A]["discard"] == []


def test_a_kiln_copy_is_gained_before_the_played_card_resolves():
    """"If after Kiln you play a Livery, you gain a copy BEFORE resolving the
    Livery, so the when-gain ability is not active yet: YOU DON'T GAIN A
    HORSE."""
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Kiln", "Livery"])
    g["actions"] = 2
    play(g, A, "Kiln")
    before = engine.pile_count(g, "Horse")
    play(g, A, "Livery")
    pick(g, A, "yes")
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Livery"]
    assert engine.pile_count(g, "Horse") == before, \
        "the copy was gained before Livery's watcher existed"
    assert g["coins"] == 5                 # $2 Kiln + $3 Livery


def test_kiln_never_fires_on_an_opponents_play():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Kiln"])
    play(g, A, "Kiln")
    give_hand(g, B, ["Copper"])
    engine.play_treasure_card(g, B, "Copper")
    engine._drive(g)
    assert g["pending"] == []


# --- Livery ------------------------------------------------------------------

def test_livery_gains_a_horse_for_each_four_plus_gain():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Livery"])
    play(g, A, "Livery")
    assert g["coins"] == 3
    before = engine.pile_count(g, "Horse")
    engine.gain(g, A, "Gold")              # $6
    engine._drive(g)
    assert engine.pile_count(g, "Horse") == before - 1
    engine.gain(g, A, "Silver")            # $3 — too cheap
    engine._drive(g)
    assert engine.pile_count(g, "Horse") == before - 1


def test_two_liverys_give_two_horses_for_one_gain():
    """"If you play Livery twice and then gain a card costing $4 or more, you
    gain two Horses"."""
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Livery", "Livery"])
    g["actions"] = 2
    play(g, A, "Livery")
    play(g, A, "Livery")
    before = engine.pile_count(g, "Horse")
    engine.gain(g, A, "Gold")
    engine._drive(g)
    assert engine.pile_count(g, "Horse") == before - 2


def test_livery_only_watches_its_own_owner():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Livery"])
    play(g, A, "Livery")
    before = engine.pile_count(g, "Horse")
    engine.gain(g, B, "Gold")
    engine._drive(g)
    assert engine.pile_count(g, "Horse") == before


def test_livery_does_not_survive_the_turn():
    """"THIS TURN, when you gain a card costing $4 or more" — a turn_end
    watcher, so Livery discards at its own Clean-up like any other card."""
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Livery"])
    give_deck(g, A, ["Copper"] * 10)
    play(g, A, "Livery")
    end_turn(g, A)
    engine._drive(g)
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A
    before = engine.pile_count(g, "Horse")
    engine.gain(g, A, "Gold")
    engine._drive(g)
    assert engine.pile_count(g, "Horse") == before
    assert "Livery" in g["seats"][A]["discard"] + g["seats"][A]["deck"] \
        + g["seats"][A]["hand"]


# --- Paddock -----------------------------------------------------------------

def test_paddock_pays_two_gains_two_horses_and_one_action_per_empty_pile():
    g = fresh(kingdom=KB)
    g["supply"]["Curse"] = 0
    g["supply"]["Estate"] = 0
    give_hand(g, A, ["Paddock"])
    before = engine.pile_count(g, "Horse")
    play(g, A, "Paddock")
    engine._drive(g)
    assert g["coins"] == 2
    assert engine.pile_count(g, "Horse") == before - 2
    assert g["actions"] == 2               # 1 - 1 + 2 empty piles


def test_paddock_still_pays_and_counts_with_no_horses_left():
    """"You get the initial +$2 even if you can't gain 2 Horses, and you still
    get the +Actions" — and the empty HORSE pile is not a Supply pile."""
    g = fresh(kingdom=KB)
    g["nonsupply"]["Horse"] = 0
    g["supply"]["Curse"] = 0
    give_hand(g, A, ["Paddock"])
    play(g, A, "Paddock")
    engine._drive(g)
    assert g["coins"] == 2
    assert g["actions"] == 1               # 1 - 1 + exactly 1 empty SUPPLY pile


# --- Sanctuary ---------------------------------------------------------------

def test_sanctuary_grants_three_things_and_may_exile():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Sanctuary", "Estate"])
    give_deck(g, A, ["Gold"])
    play(g, A, "Sanctuary")
    assert g["actions"] == 1 and g["buys"] == 2
    assert sorted(g["seats"][A]["hand"]) == ["Estate", "Gold"]
    f = frame(g)
    assert f["constraint"]["min"] == 0     # "you MAY Exile"
    decide(g, A, cards=["Estate"])
    engine._drive(g)
    assert g["seats"][A]["exile"] == ["Estate"]


def test_the_sanctuary_exile_may_be_declined():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Sanctuary", "Estate"])
    give_deck(g, A, ["Gold"])
    play(g, A, "Sanctuary")
    decide(g, A, cards=[])
    engine._drive(g)
    assert g["seats"][A]["exile"] == []


# ══ $6 ═══════════════════════════════════════════════════════════════════════

# --- Destrier ----------------------------------------------------------------

def test_destrier_draws_two_and_gives_an_action():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Destrier"])
    give_deck(g, A, ["Gold", "Silver", "Copper"])
    play(g, A, "Destrier")
    assert g["seats"][A]["hand"] == ["Gold", "Silver"] and g["actions"] == 1


def test_destrier_costs_one_less_per_card_gained_this_turn():
    g = fresh(kingdom=KB)
    assert engine.cost(g, "Destrier") == 6
    engine.gain(g, A, "Copper")
    engine._drive(g)
    assert engine.cost(g, "Destrier") == 5
    engine.gain(g, A, "Copper")
    engine._drive(g)
    assert engine.cost(g, "Destrier") == 4


def test_only_the_current_players_gains_change_destriers_cost():
    """"ONLY CARDS GAINED BY THE CURRENT PLAYER affect its cost" — which is
    what `_turn_gains` already means (it is Smugglers' list)."""
    g = fresh(kingdom=KB)
    engine.gain(g, B, "Copper")            # on A's turn
    engine._drive(g)
    assert engine.cost(g, "Destrier") == 6


def test_destriers_discount_resets_with_the_turn():
    g = fresh(kingdom=KB)
    give_deck(g, A, ["Copper"] * 10)
    engine.gain(g, A, "Copper")
    engine._drive(g)
    assert engine.cost(g, "Destrier") == 5
    end_turn(g, A)
    engine._drive(g)
    assert engine.cost(g, "Destrier") == 6


# --- Fisherman ---------------------------------------------------------------

def test_fisherman_grants_a_card_an_action_and_a_coin():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Fisherman"])
    give_deck(g, A, ["Gold", "Silver"])
    play(g, A, "Fisherman")
    assert g["seats"][A]["hand"] == ["Gold"]
    assert g["actions"] == 1 and g["coins"] == 1


def test_fisherman_costs_three_less_with_an_empty_discard_pile():
    g = fresh(kingdom=KB)
    give_discard(g, A, [])
    assert engine.cost(g, "Fisherman") == 2
    give_discard(g, A, ["Copper"])
    assert engine.cost(g, "Fisherman") == 5


def test_buying_anything_un_discounts_fisherman():
    """"Remember that when you gain a card (for instance through buying it),
    it's normally placed straight in your DISCARD PILE"."""
    g = fresh(kingdom=KB)
    give_discard(g, A, [])
    g["phase"] = "buy"
    g["coins"] = 2
    assert engine.cost(g, "Fisherman") == 2
    assert mv(g, A, {"type": "buy", "card": "Copper"})[0]
    engine._drive(g)
    assert engine.cost(g, "Fisherman") == 5


def test_fisherman_is_priced_from_the_turn_players_discard_pile():
    """"DURING YOUR TURNS" — the Ferry-token signature trick: `cost()` keys on
    whose turn it is, not on who is asking."""
    g = fresh(kingdom=KB)
    give_discard(g, A, ["Copper"])
    give_discard(g, B, [])
    assert engine.cost(g, "Fisherman") == 5
    g["turn"] = B
    assert engine.cost(g, "Fisherman") == 2


# --- Wayfarer ----------------------------------------------------------------

def test_wayfarer_draws_three_and_may_gain_a_silver():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Wayfarer"])
    give_deck(g, A, ["Gold"] * 4)
    play(g, A, "Wayfarer")
    assert len(g["seats"][A]["hand"]) == 3
    assert opt_ids(g) == ["yes", "no"]
    pick(g, A, "yes")
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Silver"]


def test_the_wayfarer_silver_may_be_declined():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Wayfarer"])
    give_deck(g, A, ["Gold"] * 4)
    play(g, A, "Wayfarer")
    pick(g, A, "no")
    engine._drive(g)
    assert g["seats"][A]["discard"] == []


def test_wayfarer_copies_the_cost_of_the_last_card_gained_this_turn():
    g = fresh(kingdom=KB)
    assert engine.cost(g, "Wayfarer") == 6
    engine.gain(g, A, "Estate")
    engine._drive(g)
    assert engine.cost(g, "Wayfarer") == 2
    engine.gain(g, A, "Gold")              # "or until another card is gained"
    engine._drive(g)
    assert engine.cost(g, "Wayfarer") == 6


def test_wayfarer_copies_a_gain_by_ANY_player():
    """"After ANY PLAYER gains a card (other than Wayfarer) on a given turn,
    Wayfarer gets the same cost" — `_turn_gains` records only the turn player's
    own gains, which is why this reads a separate tracker."""
    g = fresh(kingdom=KB)
    engine.gain(g, B, "Estate")            # on A's turn
    engine._drive(g)
    assert engine.cost(g, "Wayfarer") == 2


def test_wayfarer_ignores_gains_of_itself():
    g = fresh(kingdom=KB)
    engine.gain(g, A, "Estate")
    engine._drive(g)
    engine.gain(g, A, "Wayfarer")
    engine._drive(g)
    assert engine.cost(g, "Wayfarer") == 2, "the Wayfarer gain did not reset it"


def test_a_copying_wayfarer_bypasses_cost_reduction():
    """"COST REDUCTION only affects Wayfarer's DEFAULT cost of $6. If Wayfarer
    is copying the cost of another card, only cost reduction ON THAT CARD
    applies (which Wayfarer would copy), not cost reduction on Wayfarer
    itself."""
    g = fresh(kingdom=KB)
    g["turn_ctx"]["bridges"] = 2
    assert engine.cost(g, "Wayfarer") == 4, "its own $6 IS reduced"
    engine.gain(g, A, "Gold")
    engine._drive(g)
    # Gold's own cost is reduced to $4 and Wayfarer copies THAT, once — never
    # $6 - 2 - 2
    assert engine.cost(g, "Gold") == 4
    assert engine.cost(g, "Wayfarer") == 4


def test_wayfarer_follows_a_destriers_falling_cost():
    """"Wayfarer copies the CURRENT cost of the last-gained card. If you gain a
    Destrier costing $5, Destrier's cost will immediately fall to $4, and
    Wayfarer's cost will follow." — and the kernel's re-entry guard is what
    stops the two dynamic costs looping."""
    g = fresh(kingdom=KB)
    engine.gain(g, A, "Destrier")
    engine._drive(g)
    assert engine.cost(g, "Destrier") == 5
    assert engine.cost(g, "Wayfarer") == 5


def test_wayfarer_can_copy_a_potion_or_debt_cost():
    """"Wayfarer can have a cost with Potion or Debt in it"."""
    g = fresh(kingdom=["Wayfarer", "Herbalist", "Apprentice", "Familiar",
                       "Village", "Smithy", "Market", "Militia", "Moat", "Cellar"],
              expansions=("menagerie", "base", "alchemy"))
    engine.gain(g, A, "Familiar")          # {$3, 1P}
    engine._drive(g)
    assert engine.cost(g, "Wayfarer") == 3
    assert engine.potion_cost(g, "Wayfarer") == 1
    assert not engine.cost_le(g, "Wayfarer", 3), "a Potion cost is never 'up to $N'"


# ══ $7 ═══════════════════════════════════════════════════════════════════════

# --- Animal Fair -------------------------------------------------------------

def test_animal_fair_pays_four_and_one_buy_per_empty_supply_pile():
    g = fresh(kingdom=KB)
    g["supply"]["Curse"] = 0
    g["supply"]["Estate"] = 0
    give_hand(g, A, ["Animal Fair"])
    play(g, A, "Animal Fair")
    assert g["coins"] == 4 and g["buys"] == 3


def test_animal_fair_may_be_bought_by_trashing_an_action_instead_of_paying():
    """"You are allowed to choose Animal Fair EVEN WITHOUT HAVING $7, as long
    as you have an Action card in hand … (you always use 1 Buy)", and "if you
    buy it by trashing a card, the trashing happens BEFORE any when-buy
    abilities"."""
    g = fresh(kingdom=KB)
    g["phase"] = "buy"
    g["coins"] = 0
    give_hand(g, A, ["Sanctuary", "Copper"])
    assert engine.buy_pay_alt(g, A, "Animal Fair") is not None
    assert {"type": "buy", "card": "Animal Fair"} in engine.legal_moves(g, A)
    ok, err = mv(g, A, {"type": "buy", "card": "Animal Fair"})
    assert ok, err
    assert opt_ids(g) == ["alt"], "$0 cannot pay the $7"
    pick(g, A, "alt")
    engine._drive(g)
    decide(g, A, cards=["Sanctuary"])
    engine._drive(g)
    assert g["trash"] == ["Sanctuary"]
    assert g["seats"][A]["discard"] == ["Animal Fair"]
    assert g["buys"] == 0 and g["coins"] == 0


def test_paying_for_animal_fair_stays_a_real_choice():
    g = fresh(kingdom=KB)
    g["phase"] = "buy"
    g["coins"] = 7
    give_hand(g, A, ["Sanctuary"])
    assert mv(g, A, {"type": "buy", "card": "Animal Fair"})[0]
    assert opt_ids(g) == ["pay", "alt"]
    pick(g, A, "pay")
    engine._drive(g)
    assert g["coins"] == 0 and g["trash"] == []
    assert g["seats"][A]["discard"] == ["Animal Fair"]


def test_animal_fair_is_unbuyable_with_no_money_and_no_action_in_hand():
    """The enumerator and the handler must agree, or the bot gets a move that
    does nothing (the play_all_treasures livelock)."""
    g = fresh(kingdom=KB)
    g["phase"] = "buy"
    g["coins"] = 6
    give_hand(g, A, ["Copper", "Estate"])
    assert engine.buy_pay_alt(g, A, "Animal Fair") is None
    assert {"type": "buy", "card": "Animal Fair"} not in engine.legal_moves(g, A)
    assert not mv(g, A, {"type": "buy", "card": "Animal Fair"})[0]


def test_wayfarer_gets_the_cost_seven_even_from_a_trashed_animal_fair():
    """"Consequently, Wayfarer gets the cost $7 even when you gain Animal Fair
    BY TRASHING A CARD" — a live two-card interaction inside the set."""
    g = fresh(kingdom=KB)
    g["phase"] = "buy"
    g["coins"] = 0
    give_hand(g, A, ["Sanctuary"])
    assert mv(g, A, {"type": "buy", "card": "Animal Fair"})[0]
    pick(g, A, "alt")
    engine._drive(g)
    decide(g, A, cards=["Sanctuary"])
    engine._drive(g)
    assert engine.cost(g, "Wayfarer") == 7


# ══ THE 20 EVENTS ════════════════════════════════════════════════════════════

# --- Delay ($0) --------------------------------------------------------------

def test_delay_sets_an_action_aside_and_plays_it_next_turn():
    g = fresh(kingdom=KEV, landscapes=["Delay"])
    give_hand(g, A, ["Village", "Copper"])
    give_deck(g, A, ["Gold"] * 10)
    buy_event(g, A, "Delay", coins=0)
    f = frame(g)
    assert f["constraint"]["cards"] == ["Village"] and f["constraint"]["min"] == 0
    decide(g, A, cards=["Village"])
    engine._drive(g)
    assert g["seats"][A]["set_aside"] == ["Village"]
    end_turn(g, A)
    engine._drive(g)
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A
    assert "Village" in g["seats"][A]["in_play"]
    assert g["actions"] == 3               # 1 + Village's +2
    assert g["seats"][A]["set_aside"] == []


def test_delay_may_be_declined():
    g = fresh(kingdom=KEV, landscapes=["Delay"])
    give_hand(g, A, ["Village"])
    buy_event(g, A, "Delay", coins=0)
    decide(g, A, cards=[])
    engine._drive(g)
    assert g["seats"][A]["set_aside"] == []
    assert g["seats"][A]["hand"] == ["Village"]


# --- Desperation ($0, once per turn) -----------------------------------------

def test_desperation_gains_a_curse_for_a_buy_and_two_coins():
    g = fresh(kingdom=KEV, landscapes=["Desperation"])
    buy_event(g, A, "Desperation", coins=0)
    pick(g, A, "yes")
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Curse"]
    # "after resolving this Event, you still have the same number of Buys as
    # you had before"
    assert g["buys"] == 1 and g["coins"] == 2


def test_desperation_gives_nothing_when_declined_or_curseless():
    g = fresh(kingdom=KEV, landscapes=["Desperation"])
    buy_event(g, A, "Desperation", coins=0)
    pick(g, A, "no")
    engine._drive(g)
    assert g["seats"][A]["discard"] == [] and g["coins"] == 0 and g["buys"] == 0

    g2 = fresh(kingdom=KEV, landscapes=["Desperation"])
    g2["supply"]["Curse"] = 0
    buy_event(g2, A, "Desperation", coins=0)
    pick(g2, A, "yes")
    engine._drive(g2)
    assert g2["coins"] == 0 and g2["buys"] == 0, '"IF YOU DO"'


def test_desperation_is_once_per_turn():
    g = fresh(kingdom=KEV, landscapes=["Desperation"])
    buy_event(g, A, "Desperation", coins=0)
    pick(g, A, "no")
    engine._drive(g)
    g["buys"] = 2
    assert engine.landscape_gate(g, A, "Desperation")
    assert not mv(g, A, {"type": "buy_landscape", "name": "Desperation"})[0]


# --- Gamble ($2) — the 2025 erratum ------------------------------------------

def test_gamble_discards_the_top_card_first_then_may_play_it():
    """"2025 (current) version: Gamble now ALWAYS discards the top card first.
    Then, if you play it, it MOVES FROM YOUR DISCARD PILE to play."""
    g = fresh(kingdom=KEV, landscapes=["Gamble"])
    give_deck(g, A, ["Village", "Gold"])
    give_hand(g, A, [])
    buy_event(g, A, "Gamble", coins=2)
    assert g["buys"] == 1                  # spent one, +1 Buy back
    assert events(g, "discard")[-1]["cards"] == ["Village"]
    assert frame(g)["card"] == "Gamble" and opt_ids(g) == ["yes", "no"]
    pick(g, A, "yes")
    engine._drive(g)
    assert g["seats"][A]["in_play"] == ["Village"]
    assert g["seats"][A]["discard"] == []


def test_a_declined_gamble_leaves_the_card_discarded():
    g = fresh(kingdom=KEV, landscapes=["Gamble"])
    give_deck(g, A, ["Village", "Gold"])
    buy_event(g, A, "Gamble", coins=2)
    pick(g, A, "no")
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Village"]


def test_gamble_still_discards_a_card_it_cannot_play():
    g = fresh(kingdom=KEV, landscapes=["Gamble"])
    give_deck(g, A, ["Estate", "Gold"])
    buy_event(g, A, "Gamble", coins=2)
    engine._drive(g)
    assert g["pending"] == []
    assert g["seats"][A]["discard"] == ["Estate"]


def test_gamble_plays_a_treasure_from_the_discard_pile():
    g = fresh(kingdom=KEV, landscapes=["Gamble"])
    give_deck(g, A, ["Gold", "Copper"])
    buy_event(g, A, "Gamble", coins=2)
    pick(g, A, "yes")
    engine._drive(g)
    assert g["seats"][A]["in_play"] == ["Gold"]
    assert g["coins"] == 3                 # $2 spent on the Event, Gold pays 3


def test_gamble_on_an_empty_deck_does_nothing_but_the_buy():
    g = fresh(kingdom=KEV, landscapes=["Gamble"])
    give_deck(g, A, [])
    give_discard(g, A, [])
    buy_event(g, A, "Gamble", coins=2)
    assert g["pending"] == [] and g["buys"] == 1


# --- Pursue ($2) -------------------------------------------------------------

def test_pursue_keeps_the_matches_and_discards_the_rest():
    g = fresh(kingdom=KEV, landscapes=["Pursue"])
    give_deck(g, A, ["Gold", "Estate", "Gold", "Copper", "Silver"])
    buy_event(g, A, "Pursue", coins=2)
    f = frame(g)
    assert f["kind"] == "name_card" and f["card"] == "Pursue"
    decide(g, A, card="Gold")
    engine._drive(g)
    # two Golds go back (ordered by the player), Estate + Copper are discarded
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Estate"]
    decide(g, A, order=["Gold", "Gold"])
    engine._drive(g)
    assert g["seats"][A]["deck"] == ["Gold", "Gold", "Silver"]
    assert events(g, "reveal")[-1]["cards"] == ["Gold", "Estate", "Gold", "Copper"]


def test_pursue_with_no_matches_discards_everything_it_saw():
    g = fresh(kingdom=KEV, landscapes=["Pursue"])
    give_deck(g, A, ["Copper"] * 4)
    give_discard(g, A, [])
    buy_event(g, A, "Pursue", coins=2)
    decide(g, A, card="Gold")
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Copper"] * 4
    assert g["seats"][A]["deck"] == []


# --- Ride ($2) ---------------------------------------------------------------

def test_ride_gains_a_horse():
    g = fresh(kingdom=KEV, landscapes=["Ride"])
    before = engine.pile_count(g, "Horse")
    assert before == 30, "an Event that gains Horses brings the Horse pile"
    buy_event(g, A, "Ride", coins=2)
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Horse"]
    assert engine.pile_count(g, "Horse") == before - 1


# --- Toil ($2) ---------------------------------------------------------------

def test_toil_plays_an_action_from_your_hand_in_your_buy_phase():
    g = fresh(kingdom=KEV, landscapes=["Toil"])
    give_hand(g, A, ["Village", "Copper"])
    give_deck(g, A, ["Gold"] * 4)
    g["actions"] = 0
    buy_event(g, A, "Toil", coins=2)
    assert g["buys"] == 1
    decide(g, A, cards=["Village"])
    engine._drive(g)
    assert g["seats"][A]["in_play"] == ["Village"]
    assert g["seats"][A]["hand"] == ["Copper", "Gold"]
    assert g["actions"] == 2, "playing it this way uses no Action from the pool"


def test_toil_may_be_declined():
    g = fresh(kingdom=KEV, landscapes=["Toil"])
    give_hand(g, A, ["Village"])
    buy_event(g, A, "Toil", coins=2)
    decide(g, A, cards=[])
    engine._drive(g)
    assert g["seats"][A]["in_play"] == []


# --- Enhance ($3) ------------------------------------------------------------

def test_enhance_trashes_a_non_victory_card_to_gain_two_more():
    g = fresh(kingdom=KEV, landscapes=["Enhance"])
    give_hand(g, A, ["Silver", "Estate"])
    buy_event(g, A, "Enhance", coins=3)
    f = frame(g)
    assert f["constraint"]["cards"] == ["Silver"], "a NON-VICTORY card"
    assert f["constraint"]["min"] == 0
    decide(g, A, cards=["Silver"])
    engine._drive(g)
    assert g["trash"] == ["Silver"]
    piles = frame(g)["constraint"]["piles"]
    assert "Market" in piles and "Gold" not in piles     # $5 yes, $6 no
    decide(g, A, pile="Market")
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Market"]


def test_the_enhance_gain_is_parked_below_its_trash():
    """A gain that follows a trash must resolve AFTER it — push the
    continuation first, then trash."""
    g = fresh(kingdom=KEV, landscapes=["Enhance"])
    give_hand(g, A, ["Silver"])
    buy_event(g, A, "Enhance", coins=3)
    decide(g, A, cards=["Silver"])
    assert g["trash"] == ["Silver"], "the trash happened before the gain prompt"
    engine._drive(g)
    assert frame(g)["kind"] == "choose_pile"


def test_enhance_may_be_declined():
    g = fresh(kingdom=KEV, landscapes=["Enhance"])
    give_hand(g, A, ["Silver"])
    buy_event(g, A, "Enhance", coins=3)
    decide(g, A, cards=[])
    engine._drive(g)
    assert g["trash"] == [] and g["pending"] == []


# --- March ($3) --------------------------------------------------------------

def test_march_plays_an_action_out_of_your_discard_pile():
    g = fresh(kingdom=KEV, landscapes=["March"])
    give_discard(g, A, ["Village", "Copper"])
    give_deck(g, A, ["Gold"] * 4)
    give_hand(g, A, [])
    buy_event(g, A, "March", coins=3)
    f = frame(g)
    assert f["constraint"]["cards"] == ["Village"]
    decide(g, A, cards=["Village"])
    engine._drive(g)
    assert g["seats"][A]["in_play"] == ["Village"]
    assert g["seats"][A]["discard"] == ["Copper"]
    assert g["seats"][A]["hand"] == ["Gold"]


def test_march_with_no_action_in_the_discard_pile_does_nothing():
    g = fresh(kingdom=KEV, landscapes=["March"])
    give_discard(g, A, ["Copper", "Estate"])
    buy_event(g, A, "March", coins=3)
    assert g["pending"] == []


# --- Transport ($3) ----------------------------------------------------------

def test_transport_can_exile_an_action_card_from_the_supply():
    g = fresh(kingdom=KEV, landscapes=["Transport"])
    buy_event(g, A, "Transport", coins=3)
    assert opt_ids(g) == ["exile", "deck"]
    pick(g, A, "exile")
    engine._drive(g)
    piles = frame(g)["constraint"]["piles"]
    assert "Village" in piles and "Silver" not in piles and "Estate" not in piles
    before = engine.pile_count(g, "Village")
    decide(g, A, pile="Village")
    engine._drive(g)
    assert g["seats"][A]["exile"] == ["Village"]
    assert engine.pile_count(g, "Village") == before - 1


def test_transport_can_put_an_exiled_action_onto_your_deck():
    """"You may move an Action card from your Exile mat WHETHER IT WAS PUT
    THERE BY TRANSPORT OR BY ANOTHER ABILITY" — and onto the DECK, so it is not
    a discard and no when-discard ability sees it."""
    g = fresh(kingdom=KEV, landscapes=["Transport"])
    g["seats"][A]["exile"] = ["Village", "Estate"]
    give_deck(g, A, ["Gold"])
    buy_event(g, A, "Transport", coins=3)
    pick(g, A, "deck")
    engine._drive(g)
    assert frame(g)["constraint"]["cards"] == ["Village"], "an ACTION card"
    decide(g, A, cards=["Village"])
    engine._drive(g)
    assert g["seats"][A]["deck"] == ["Village", "Gold"]
    assert g["seats"][A]["exile"] == ["Estate"]
    assert not events(g, "discard")


def test_transport_offers_the_mat_branch_even_when_it_is_empty():
    """Choices are never feasibility-filtered — the branch is offered and then
    simply finds nothing to move."""
    g = fresh(kingdom=KEV, landscapes=["Transport"])
    buy_event(g, A, "Transport", coins=3)
    pick(g, A, "deck")
    engine._drive(g)
    assert g["pending"] == []


# --- Banish ($4) -------------------------------------------------------------

def test_banish_exiles_any_number_of_one_name():
    g = fresh(kingdom=KEV, landscapes=["Banish"])
    give_hand(g, A, ["Copper", "Copper", "Copper", "Estate"])
    buy_event(g, A, "Banish", coins=4)
    assert opt_ids(g) == ["Copper", "Estate"]
    pick(g, A, "Copper")
    engine._drive(g)
    f = frame(g)
    assert f["constraint"]["cards"] == ["Copper"] * 3
    assert (f["constraint"]["min"], f["constraint"]["max"]) == (0, 3)
    decide(g, A, cards=["Copper", "Copper"])
    engine._drive(g)
    assert g["seats"][A]["exile"] == ["Copper", "Copper"]
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Estate"]


def test_banish_may_exile_nothing():
    g = fresh(kingdom=KEV, landscapes=["Banish"])
    give_hand(g, A, ["Copper"])
    buy_event(g, A, "Banish", coins=4)
    pick(g, A, "Copper")
    engine._drive(g)
    decide(g, A, cards=[])
    engine._drive(g)
    assert g["seats"][A]["exile"] == []


# --- Bargain ($4) ------------------------------------------------------------

def test_bargain_gains_a_non_victory_card_then_a_horse_to_each_opponent():
    """"First gain, THEN opponents gain"."""
    g = fresh(players=(A, B, C), kingdom=KEV, landscapes=["Bargain"])
    buy_event(g, A, "Bargain", coins=4)
    piles = frame(g)["constraint"]["piles"]
    assert "Market" in piles                 # $5
    assert "Gold" not in piles               # $6
    assert "Duchy" not in piles and "Estate" not in piles
    decide(g, A, pile="Market")
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Market"]
    assert g["seats"][B]["discard"] == ["Horse"]
    assert g["seats"][C]["discard"] == ["Horse"]
    order = [e["pid"] for e in events(g, "gain")]
    assert order == [A, B, C], "the buyer first, then turn order"


# --- Invest ($4) -------------------------------------------------------------

def test_invest_exiles_an_action_from_the_supply_and_draws_on_another_gain():
    g = fresh(kingdom=KEV, landscapes=["Invest"])
    give_deck(g, A, ["Gold"] * 6)
    give_hand(g, A, [])
    buy_event(g, A, "Invest", coins=4)
    piles = frame(g)["constraint"]["piles"]
    assert "Village" in piles and "Silver" not in piles
    decide(g, A, pile="Village")
    engine._drive(g)
    assert g["seats"][A]["exile"] == ["Village"]
    # YOUR OWN gain does nothing
    engine.gain(g, A, "Village")
    engine._drive(g)
    assert g["seats"][A]["hand"] == []
    # ...another player's does
    engine.gain(g, B, "Village")
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Gold", "Gold"]


def test_invest_only_watches_the_card_it_invested_in():
    g = fresh(kingdom=KEV, landscapes=["Invest"])
    give_deck(g, A, ["Gold"] * 6)
    give_hand(g, A, [])
    buy_event(g, A, "Invest", coins=4)
    decide(g, A, pile="Village")
    engine._drive(g)
    engine.gain(g, B, "Smithy")
    engine._drive(g)
    assert g["seats"][A]["hand"] == []


def test_investing_in_a_copy_draws_the_other_investor_two_cards():
    """"…when another player gains OR INVESTS IN a copy of it, +2 Cards" — and
    no other Supply Exile may fire it, which is why the marker exists."""
    g = fresh(kingdom=KEV, landscapes=["Invest"])
    give_deck(g, A, ["Gold"] * 6)
    give_hand(g, A, [])
    buy_event(g, A, "Invest", coins=4)
    decide(g, A, pile="Village")
    engine._drive(g)
    g["turn"] = B
    g["buys"] = 1
    buy_event(g, B, "Invest", coins=4)
    decide(g, B, pile="Village")
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Gold", "Gold"]
    assert g["seats"][B]["exile"] == ["Village"]


def test_a_second_invest_in_the_same_card_draws_four():
    """"If you Invest in another copy of the same card, you draw 4 cards"."""
    g = fresh(kingdom=KEV, landscapes=["Invest"])
    give_deck(g, A, ["Gold"] * 8)
    give_hand(g, A, [])
    buy_event(g, A, "Invest", coins=8)
    decide(g, A, pile="Village")
    engine._drive(g)
    g["buys"] = 1
    assert mv(g, A, {"type": "buy_landscape", "name": "Invest"})[0]
    decide(g, A, pile="Village")
    engine._drive(g)
    assert g["seats"][A]["hand"] == [], "your own Invest never pays you"
    engine.gain(g, B, "Village")
    engine._drive(g)
    while g["pending"]:
        engine._drive(g)
        if g["pending"]:
            f = frame(g)
            decide(g, f["pid"], ids=[f["constraint"]["options"][0]["id"]])
    assert g["seats"][A]["hand"] == ["Gold"] * 4


def test_invest_stops_once_the_card_leaves_exile():
    """"WHILE IT'S IN EXILE" — the mat's own all-or-nothing discard can end
    an Invest."""
    g = fresh(kingdom=KEV, landscapes=["Invest"])
    give_deck(g, A, ["Gold"] * 6)
    give_hand(g, A, [])
    buy_event(g, A, "Invest", coins=4)
    decide(g, A, pile="Village")
    engine._drive(g)
    g["seats"][A]["exile"] = []
    engine.gain(g, B, "Village")
    engine._drive(g)
    assert g["seats"][A]["hand"] == []


def test_an_invest_watcher_never_conjures_a_card_into_the_census():
    """A landscape has no physical card, so its watcher must not leave a
    duration entry behind — `owned_cards` would count "Invest" as a card the
    player owns and the next scoring pass would raise."""
    g = fresh(kingdom=KEV, landscapes=["Invest"])
    give_deck(g, A, ["Copper"] * 10)
    buy_event(g, A, "Invest", coins=4)
    decide(g, A, pile="Village")
    engine._drive(g)
    end_turn(g, A)
    engine._drive(g)
    assert "Invest" not in engine.owned_cards(g, A)
    assert all(e["card"] != "Invest" for e in g["seats"][A]["duration"])
    engine._post_move(g)                    # the scoring pass the entry would break
    # ...and the watcher itself survived the turn boundary
    end_turn(g, B)
    engine._drive(g)
    give_hand(g, A, [])
    engine.gain(g, B, "Village")
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Copper", "Copper"]


# --- Seize the Day ($4, once per game) ---------------------------------------

def test_seize_the_day_takes_an_extra_turn():
    g = fresh(kingdom=KEV, landscapes=["Seize the Day"])
    give_deck(g, A, ["Copper"] * 10)
    buy_event(g, A, "Seize the Day", coins=4)
    end_turn(g, A)
    engine._drive(g)
    assert g["turn"] == A and g["extra_turn"] is True


def test_seize_the_day_is_once_per_game_and_per_player():
    g = fresh(kingdom=KEV, landscapes=["Seize the Day"])
    give_deck(g, A, ["Copper"] * 10)
    buy_event(g, A, "Seize the Day", coins=8)
    g["buys"] = 1
    assert engine.landscape_gate(g, A, "Seize the Day")
    assert not mv(g, A, {"type": "buy_landscape", "name": "Seize the Day"})[0]
    # ...but the other player may still buy it
    g["turn"] = B
    g["phase"] = "buy"
    g["buys"] = 1
    g["coins"] = 4
    assert engine.landscape_gate(g, B, "Seize the Day") is None


# --- Commerce ($5) -----------------------------------------------------------

def test_commerce_gains_a_gold_per_differently_named_card_gained_this_turn():
    g = fresh(kingdom=KEV, landscapes=["Commerce"])
    for c in ("Copper", "Copper", "Estate", "Village"):
        engine.gain(g, A, c)
        engine._drive(g)
    buy_event(g, A, "Commerce", coins=5)
    engine._drive(g)
    assert g["seats"][A]["discard"].count("Gold") == 3


def test_commerce_counts_only_gains_from_before_it_was_bought():
    """"Only the cards gained BEFORE buying Commerce are counted" — the Golds
    it gains must not feed its own count."""
    g = fresh(kingdom=KEV, landscapes=["Commerce"])
    engine.gain(g, A, "Silver")
    engine._drive(g)
    buy_event(g, A, "Commerce", coins=5)
    engine._drive(g)
    assert g["seats"][A]["discard"].count("Gold") == 1


def test_commerce_counts_only_your_own_gains():
    g = fresh(kingdom=KEV, landscapes=["Commerce"])
    engine.gain(g, B, "Silver")
    engine._drive(g)
    buy_event(g, A, "Commerce", coins=5)
    engine._drive(g)
    assert "Gold" not in g["seats"][A]["discard"]


# --- Demand ($5) -------------------------------------------------------------

def test_demand_puts_a_horse_and_a_cheap_card_onto_your_deck():
    g = fresh(kingdom=KEV, landscapes=["Demand"])
    give_deck(g, A, ["Estate"])
    buy_event(g, A, "Demand", coins=5)
    piles = frame(g)["constraint"]["piles"]
    assert "Smithy" in piles and "Market" not in piles
    decide(g, A, pile="Smithy")
    engine._drive(g)
    assert g["seats"][A]["deck"] == ["Smithy", "Horse", "Estate"]
    assert g["seats"][A]["discard"] == []


# --- Stampede ($5) -----------------------------------------------------------

def test_stampede_gains_five_horses_onto_your_deck():
    g = fresh(kingdom=KEV, landscapes=["Stampede"])
    give_deck(g, A, ["Estate"])
    g["seats"][A]["in_play"] = ["Copper"] * 5
    before = engine.pile_count(g, "Horse")
    buy_event(g, A, "Stampede", coins=5)
    engine._drive(g)
    assert g["seats"][A]["deck"] == ["Horse"] * 5 + ["Estate"]
    assert engine.pile_count(g, "Horse") == before - 5


def test_stampede_checks_the_cards_you_have_in_play():
    g = fresh(kingdom=KEV, landscapes=["Stampede"])
    give_deck(g, A, [])
    g["seats"][A]["in_play"] = ["Copper"] * 6
    before = engine.pile_count(g, "Horse")
    buy_event(g, A, "Stampede", coins=5)
    engine._drive(g)
    assert engine.pile_count(g, "Horse") == before
    assert g["seats"][A]["deck"] == []


# --- Reap ($7) — the 2025 erratum --------------------------------------------

def test_reap_sets_a_gold_aside_and_plays_it_next_turn():
    """"2025 (current) version: the card is now GAINED DIRECTLY to your
    'set aside' area" — it never visits the discard pile."""
    g = fresh(kingdom=KEV, landscapes=["Reap"])
    give_deck(g, A, ["Copper"] * 10)
    buy_event(g, A, "Reap", coins=7)
    engine._drive(g)
    assert g["seats"][A]["set_aside"] == ["Gold"]
    assert g["seats"][A]["discard"] == []
    assert events(g, "gain")[-1]["dest"] == "set_aside"
    end_turn(g, A)
    engine._drive(g)
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A
    assert g["seats"][A]["in_play"] == ["Gold"]
    assert g["coins"] == 3
    assert g["seats"][A]["set_aside"] == []


def test_reap_with_no_golds_left_sets_nothing_up():
    g = fresh(kingdom=KEV, landscapes=["Reap"])
    g["supply"]["Gold"] = 0
    give_deck(g, A, ["Copper"] * 10)
    buy_event(g, A, "Reap", coins=7)
    engine._drive(g)
    assert g["seats"][A]["start_fx"] == []


# --- Enclave ($8) ------------------------------------------------------------

def test_enclave_gains_a_gold_and_exiles_a_duchy():
    g = fresh(kingdom=KEV, landscapes=["Enclave"])
    before = engine.pile_count(g, "Duchy")
    buy_event(g, A, "Enclave", coins=8)
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Gold"]
    assert g["seats"][A]["exile"] == ["Duchy"]
    assert engine.pile_count(g, "Duchy") == before - 1


def test_enclave_does_each_half_even_when_the_other_pile_is_empty():
    """"If there are no Golds left, you still Exile a Duchy, and vice versa"."""
    g = fresh(kingdom=KEV, landscapes=["Enclave"])
    g["supply"]["Gold"] = 0
    buy_event(g, A, "Enclave", coins=8)
    engine._drive(g)
    assert g["seats"][A]["discard"] == [] and g["seats"][A]["exile"] == ["Duchy"]

    g2 = fresh(kingdom=KEV, landscapes=["Enclave"])
    g2["supply"]["Duchy"] = 0
    buy_event(g2, A, "Enclave", coins=8)
    engine._drive(g2)
    assert g2["seats"][A]["discard"] == ["Gold"] and g2["seats"][A]["exile"] == []


# --- Alliance ($10) ----------------------------------------------------------

def test_alliance_gains_all_six_cards_in_the_order_given():
    g = fresh(kingdom=KEV, landscapes=["Alliance"])
    buy_event(g, A, "Alliance", coins=10)
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Province", "Duchy", "Estate",
                                        "Gold", "Silver", "Copper"]


def test_alliance_gains_the_ones_it_can():
    """"You gain the ones you can, even if some piles are empty"."""
    g = fresh(kingdom=KEV, landscapes=["Alliance"])
    g["supply"]["Province"] = 0
    g["supply"]["Silver"] = 0
    buy_event(g, A, "Alliance", coins=10)
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Duchy", "Estate", "Gold", "Copper"]


# --- Populate ($10) ----------------------------------------------------------

def test_populate_gains_one_card_from_each_action_supply_pile():
    """"You gain the top card from each ACTION SUPPLY PILE … you do not gain a
    card from non-Supply piles", and "you gain them IN WHATEVER ORDER YOU
    CHOOSE"."""
    g = fresh(kingdom=KEV, landscapes=["Populate", "Ride"])
    before_horse = engine.pile_count(g, "Horse")
    buy_event(g, A, "Populate", coins=10)
    picked = []
    while True:
        engine._drive(g)
        f = frame(g)
        if f is None:
            break
        assert f["kind"] == "choose_pile" and f["card"] == "Populate"
        pile = sorted(f["constraint"]["piles"])[0]
        picked.append(pile)
        decide(g, A, pile=pile)
    got = g["seats"][A]["discard"]
    assert sorted(got) == sorted(KEV)
    assert got[:len(picked)] == picked, "gained in the order the player chose"
    assert engine.pile_count(g, "Horse") == before_horse
    assert "Copper" not in got and "Estate" not in got


def test_populate_skips_a_pile_that_ran_out():
    g = fresh(kingdom=KEV, landscapes=["Populate"])
    for name in KEV[2:]:
        g["supply"][name] = 0
    buy_event(g, A, "Populate", coins=10)
    engine._drive(g)
    decide(g, A, pile="Smithy")
    engine._drive(g)
    assert sorted(g["seats"][A]["discard"]) == ["Smithy", "Village"]


# ══ the roster ═══════════════════════════════════════════════════════════════

def test_every_card_and_event_in_this_half_is_registered():
    """The half's own manifest, by hand — a comprehension over the module would
    agree with any omission in it (the `bot_traits.REVIEWED` lesson)."""
    mine = ["Horse", "Supplies", "Camel Train", "Goatherd", "Scrap",
            "Snowy Village", "Bounty Hunter", "Cavalry", "Groom", "Hostelry",
            "Displace", "Hunting Lodge", "Kiln", "Livery", "Paddock",
            "Sanctuary", "Destrier", "Fisherman", "Wayfarer", "Animal Fair"]
    for name in mine:
        assert name in cards.CARDS, name
        assert name in effects.EFFECTS, name
    my_events = ["Delay", "Desperation", "Gamble", "Pursue", "Ride", "Toil",
                 "Enhance", "March", "Transport", "Banish", "Bargain", "Invest",
                 "Seize the Day", "Commerce", "Demand", "Stampede", "Reap",
                 "Enclave", "Alliance", "Populate"]
    for name in my_events:
        assert cards.landscape_kind(name) == "event", name
        assert name in effects.LANDSCAPE_FX, name
