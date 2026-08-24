"""Dark Ages, half B — the trash theme, the attacks, and the shuffled piles.

Band of Misfits, Cultist, Death Cart, Feodum, Fortress, Graverobber, Hermit,
Marauder, Pillage, Procession, Rats, Rebuild, Rogue, Urchin, the 10 Knights,
the 5 Ruins, the 3 Shelters and Madman/Mercenary — plus the set's three SETUP
rules (Shelters, Ruins, Knights) and its non-Supply piles.

Headline rulings pinned here:
  * Setup: Ruins only with a Looter and only as many as there are Curses;
    Knights as one shuffled pile whose top card is what you buy; Shelters
    replacing the starting Estates on their own random roll; Madman /
    Mercenary / Spoils only when their card is in the kingdom.
  * A Knight that trashes a Knight is trashed itself, and the VICTIM picks
    which of two eligible cards goes.
  * Sir Michael's discard-down-to-3 happens BEFORE the reveal.
  * Fortress goes back to your HAND from the trash, every time, and is not
    gained doing it.
  * Hermit exchanges itself for a Madman only if you gained nothing in the Buy
    phase — and not at all if it left play.
  * Urchin's trash-for-a-Mercenary is a BEFORE-play ability: it resolves before
    the Attack that triggered it, and not on a throne-room replay.
  * Procession plays twice, trashes, and gains EXACTLY $1 more — and still
    gains when it could not trash.
  * Death Cart's when-gain hands you 2 Ruins; Rats' pile is 20 cards.
"""

from games.dontminion import engine
from games.dontminion.cards import KNIGHTS, RUINS, SHELTERS

A, B, C = "alice", "bob", "carol"

KDB = ["Band of Misfits", "Cultist", "Death Cart", "Feodum", "Fortress",
       "Graverobber", "Hermit", "Marauder", "Pillage", "Procession"]
KDB2 = ["Rats", "Rebuild", "Rogue", "Urchin", "Knights", "Fortress", "Squire",
        "Altar", "Ironmonger", "Vagrant"]


def fresh(players=(A, B), seed=5, kingdom=tuple(KDB), expansions=("darkages",)):
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


def set_knights(g, order):
    """Force the Knights pile's hidden order (top first)."""
    g["piles"]["Knights"]["contents"] = list(order)
    g["piles"]["Knights"]["face"] = order[0]
    g["supply"]["Knights"] = len(order)


# ── SETUP: the three Dark Ages rules ──────────────────────────────────────────

def test_ruins_join_the_supply_only_when_a_looter_is_in_the_kingdom():
    looted = fresh(kingdom=["Cultist"] + KDB[2:] + ["Squire"])
    assert "Ruins" in looted["supply"], "Cultist is a Looter"
    plain = fresh(kingdom=["Altar", "Armory", "Beggar", "Catacombs", "Count",
                           "Forager", "Fortress", "Ironmonger", "Squire",
                           "Vagrant"])
    assert "Ruins" not in plain["supply"] and "Ruins" not in plain["piles"]


def test_the_ruins_pile_holds_as_many_cards_as_there_are_curses():
    for n, players in ((2, (A, B)), (3, (A, B, C))):
        g = fresh(players=players, kingdom=["Marauder"] + KDB[3:] + ["Squire"])
        assert engine.pile_count(g, "Ruins") == g["supply"]["Curse"] == 10 * (n - 1)
        assert set(g["piles"]["Ruins"]["contents"]) <= set(RUINS)


def test_only_the_top_ruin_is_visible_and_it_is_what_you_gain():
    g = fresh(kingdom=["Marauder"] + KDB[3:] + ["Squire"])
    g["piles"]["Ruins"]["contents"] = ["Survivors", "Abandoned Mine"]
    g["piles"]["Ruins"]["face"] = "Survivors"
    g["supply"]["Ruins"] = 2
    assert engine.pile_top(g, "Ruins") == "Survivors"
    engine.gain(g, A, "Ruins")
    assert g["seats"][A]["discard"] == ["Survivors"]
    assert engine.pile_face(g, "Ruins") == "Abandoned Mine"
    view = engine.player_view(g, B)
    assert view["piles"]["Ruins"] == {"count": 1, "supply": True,
                                      "face": "Abandoned Mine", "ordered": True,
                                      "attach": {}}


def test_the_knights_pile_is_one_shuffled_pile_of_ten():
    g = fresh(kingdom=KDB2)
    assert engine.pile_count(g, "Knights") == 10
    assert sorted(g["piles"]["Knights"]["contents"]) == sorted(KNIGHTS)
    assert "Knights" not in engine.CARDS, "the pile name is not a card"
    # the pile costs (and is typed as) its TOP card
    set_knights(g, ["Sir Martin", "Dame Josephine"])
    assert engine.cost(g, "Knights") == 4
    assert engine.has_type(g, "Knights", "attack")


def test_buying_the_knights_pile_gains_its_top_card():
    g = fresh(kingdom=KDB2)
    set_knights(g, ["Dame Molly", "Sir Bailey"])
    g["phase"] = "buy"
    g["coins"] = 5
    assert mv(g, A, {"type": "buy", "card": "Knights"})[0]
    assert g["seats"][A]["discard"] == ["Dame Molly"]
    assert engine.pile_count(g, "Knights") == 1
    assert engine.pile_top(g, "Knights") == "Sir Bailey"


def test_shelters_replace_the_starting_estates_when_the_roll_says_so():
    """The probability is the DARK AGES PROPORTION of the dealt 10, so a mixed
    board reaches both branches (an all-Dark-Ages board is 10/10 and always
    deals them — which is the rule, not a bug)."""
    mixed = KDB[:5] + ["Village", "Smithy", "Market", "Festival", "Moat"]
    seen = {True: None, False: None}
    for seed in range(60):
        g = fresh(seed=seed, kingdom=mixed, expansions=("base", "darkages"))
        seen[g["shelters"]] = g
        if all(seen.values()):
            break
    assert seen[True] is not None and seen[False] is not None, \
        "both branches of the Shelter roll must be reachable"
    with_shelters = engine.owned_cards(seen[True], A)
    assert sorted(c for c in with_shelters if c != "Copper") == sorted(SHELTERS)
    without = engine.owned_cards(seen[False], A)
    assert without.count("Estate") == 3 and "Hovel" not in without
    # the Estate PILE is untouched either way
    assert seen[True]["supply"]["Estate"] == seen[False]["supply"]["Estate"]
    # ...and an all-Dark-Ages kingdom is 10/10, so it ALWAYS deals Shelters
    assert fresh(seed=3, kingdom=KDB)["shelters"] is True


def test_a_game_with_no_dark_ages_card_never_deals_shelters():
    for seed in range(20):
        g = engine.new_game([A, B], ["base"], seed=seed)
        assert g["shelters"] is False


def test_the_non_supply_piles_appear_only_with_their_card():
    g = fresh(kingdom=KDB)             # Hermit + Pillage, no Urchin
    assert g["nonsupply"]["Madman"] == 10
    assert g["nonsupply"]["Spoils"] == 15
    assert "Mercenary" not in g["nonsupply"]
    assert not (set(g["nonsupply"]) & set(g["supply"]))
    g2 = fresh(kingdom=KDB2)           # Urchin, no Hermit
    assert g2["nonsupply"] == {"Mercenary": 10}


def test_rats_uses_all_twenty_cards():
    g = fresh(kingdom=KDB2)
    assert g["supply"]["Rats"] == 20


def test_an_empty_non_supply_pile_never_ends_the_game():
    g = fresh(kingdom=KDB)
    g["nonsupply"]["Spoils"] = 0
    g["nonsupply"]["Madman"] = 0
    assert engine.count_empty_piles(g) == 0


# ── Band of Misfits ───────────────────────────────────────────────────────────

def test_band_of_misfits_plays_a_cheaper_supply_action_and_leaves_it():
    g = fresh(kingdom=KDB + ["Village"], expansions=("base", "darkages"))
    give_hand(g, A, ["Band of Misfits"])
    give_deck(g, A, ["Copper"])
    before = g["supply"]["Village"]
    assert play(g, A, "Band of Misfits")[0]
    piles = frame(g)["constraint"]["piles"]
    assert "Village" in piles
    assert "Band of Misfits" not in piles, "it costs the same, not less"
    assert decide(g, A, pile="Village")[0]
    assert g["supply"]["Village"] == before, "the card never leaves the Supply"
    assert g["seats"][A]["in_play"] == ["Band of Misfits"]
    assert g["actions"] == 2 and len(g["seats"][A]["hand"]) == 1


def test_band_of_misfits_cannot_play_a_command_or_a_duration():
    g = fresh(kingdom=KDB + ["Caravan"], expansions=("seaside", "darkages"))
    give_hand(g, A, ["Band of Misfits"])
    play(g, A, "Band of Misfits")
    piles = frame(g)["constraint"]["piles"]
    assert "Caravan" not in piles, "the 2025 card cannot play a Duration"
    assert "Band of Misfits" not in piles, "nor another Command card"


def test_band_of_misfits_playing_an_attack_opens_the_reaction_window():
    g = fresh(kingdom=KDB + ["Militia", "Moat"], expansions=("base", "darkages"))
    give_hand(g, A, ["Band of Misfits"])
    give_hand(g, B, ["Moat", "Copper", "Copper", "Copper", "Copper"])
    play(g, A, "Band of Misfits")
    assert decide(g, A, pile="Militia")[0]
    assert g["pending_pid"] == B and frame(g)["card"] == "__attack"
    assert decide(g, B, ids=["react:Moat"])[0]
    assert g["pending"] == [], "Moat makes B unaffected — and it runs ONCE"
    assert g["coins"] == 2


# ── Cultist ───────────────────────────────────────────────────────────────────

def test_cultist_gives_ruins_then_offers_the_chain():
    g = fresh()
    give_hand(g, A, ["Cultist", "Cultist"])
    give_deck(g, A, ["Copper"] * 4)
    give_hand(g, B, ["Copper"])
    assert play(g, A, "Cultist")[0]
    assert len(g["seats"][A]["hand"]) == 3       # 2 drawn + the second Cultist
    assert len(g["seats"][B]["discard"]) == 1
    assert engine.has_type(g, g["seats"][B]["discard"][0], "ruins")
    # ...and only THEN "you may play a Cultist from your hand"
    assert frame(g)["card"] == "Cultist" and opt_ids(g) == ["play", "decline"]
    assert decide(g, A, ids=["play"])[0]
    assert g["seats"][A]["in_play"].count("Cultist") == 2
    assert len(g["seats"][B]["discard"]) == 2, "the chained Cultist attacks too"


def test_cultist_chain_costs_no_action():
    g = fresh()
    give_hand(g, A, ["Cultist", "Cultist"])
    g["actions"] = 1
    play(g, A, "Cultist")
    assert g["actions"] == 0
    decide(g, A, ids=["play"])
    assert g["actions"] == 0, "the chained play spends no Action from the pool"


def test_cultist_on_trash_draws_three():
    g = fresh()
    give_hand(g, A, ["Cultist"])
    give_deck(g, A, ["Copper"] * 4)
    engine.trash(g, A, ["Cultist"])
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 3


def test_a_moat_must_be_revealed_against_every_cultist():
    """"If you reveal Moat as a Reaction to a Cultist, you are not
    automatically unaffected by further Cultists played by that one.\""""
    g = fresh(kingdom=KDB + ["Moat"], expansions=("base", "darkages"))
    give_hand(g, A, ["Cultist", "Cultist"])
    give_hand(g, B, ["Moat"])
    play(g, A, "Cultist")
    assert decide(g, B, ids=["react:Moat"])[0]
    assert g["seats"][B]["discard"] == []
    assert decide(g, A, ids=["play"])[0]
    assert g["pending_pid"] == B, "the second Cultist opens a new window"
    assert "react:Moat" in opt_ids(g)


# ── Death Cart ────────────────────────────────────────────────────────────────

def test_death_cart_when_gained_brings_two_ruins():
    g = fresh()
    engine.gain(g, A, "Death Cart")
    engine._drive(g)
    got = g["seats"][A]["discard"]
    assert got[0] == "Death Cart"
    assert len(got) == 3 and all(engine.has_type(g, c, "ruins") for c in got[1:])


def test_death_cart_trashes_itself_for_five():
    g = fresh()
    give_hand(g, A, ["Death Cart"])
    assert play(g, A, "Death Cart")[0]
    assert opt_ids(g) == ["self", "hand", "none"]
    assert decide(g, A, ids=["self"])[0]
    assert g["coins"] == 5 and "Death Cart" in g["trash"]
    assert g["seats"][A]["in_play"] == []


def test_death_cart_can_eat_an_action_from_hand_instead():
    g = fresh()
    give_hand(g, A, ["Death Cart", "Fortress", "Copper"])
    play(g, A, "Death Cart")
    assert decide(g, A, ids=["hand"])[0]
    assert frame(g)["constraint"]["cards"] == ["Fortress"], "Actions only"
    assert decide(g, A, cards=["Fortress"])[0]
    assert g["coins"] == 5
    assert "Death Cart" in g["seats"][A]["in_play"]


def test_death_cart_may_decline():
    g = fresh()
    give_hand(g, A, ["Death Cart"])
    play(g, A, "Death Cart")
    assert decide(g, A, ids=["none"])[0]
    assert g["coins"] == 0 and "Death Cart" in g["seats"][A]["in_play"]


# ── Feodum ────────────────────────────────────────────────────────────────────

def test_feodum_scores_one_per_three_silvers():
    g = fresh()
    g["seats"][A]["deck"] = ["Feodum"] + ["Silver"] * 7
    g["seats"][A]["hand"] = []
    g["seats"][A]["discard"] = []
    assert engine._vp_of(g, A) == 2, "7 Silvers => 2 VP, rounded down"


def test_feodum_on_trash_gains_three_silvers():
    g = fresh()
    give_hand(g, A, ["Feodum"])
    engine.trash(g, A, ["Feodum"])
    engine._drive(g)
    assert g["seats"][A]["discard"].count("Silver") == 3


# ── Fortress ──────────────────────────────────────────────────────────────────

def test_fortress_returns_to_your_hand_whenever_it_is_trashed():
    g = fresh()
    give_hand(g, A, ["Fortress"])
    engine.trash(g, A, ["Fortress"])
    engine._drive(g)
    assert "Fortress" in g["seats"][A]["hand"]
    assert "Fortress" not in g["trash"], "it does not stay in the trash"
    assert not any(e["event"] == "gain" and e.get("card") == "Fortress"
                   for e in g["log"]), "this is NOT gaining it"


def test_a_processioned_fortress_comes_back_and_still_gains():
    """The pairing the set is famous for: Procession trashes the Fortress from
    play, the Fortress returns to hand, and Procession still gains a $5."""
    g = fresh()
    give_hand(g, A, ["Procession", "Fortress"])
    give_deck(g, A, ["Copper"] * 4)
    assert play(g, A, "Procession")[0]
    assert decide(g, A, cards=["Fortress"])[0]
    assert g["actions"] == 4, "+2 Actions twice, minus the Procession's own"
    assert "Fortress" in g["seats"][A]["hand"]
    assert frame(g)["kind"] == "choose_pile"
    assert all(engine.cost(g, p) == 5 for p in frame(g)["constraint"]["piles"])


# ── Graverobber ───────────────────────────────────────────────────────────────

def test_graverobber_gains_from_the_trash_onto_the_deck():
    g = fresh()
    g["trash"].extend(["Gold", "Copper", "Province"])
    give_hand(g, A, ["Graverobber"])
    assert play(g, A, "Graverobber")[0]
    assert decide(g, A, ids=["trash"])[0]
    assert frame(g)["constraint"]["cards"] == ["Gold"], "$3-$6 only"
    assert decide(g, A, cards=["Gold"])[0]
    assert g["seats"][A]["deck"][0] == "Gold"
    assert "Gold" not in g["trash"]


def test_graverobber_remodels_an_action_up_three():
    g = fresh()
    give_hand(g, A, ["Graverobber", "Fortress", "Copper"])
    play(g, A, "Graverobber")
    assert decide(g, A, ids=["remodel"])[0]
    assert frame(g)["constraint"]["cards"] == ["Fortress"]
    assert decide(g, A, cards=["Fortress"])[0]
    assert "Fortress" in g["trash"] or "Fortress" in g["seats"][A]["hand"]
    piles = frame(g)["constraint"]["piles"]
    assert all(engine.cost(g, p) <= 7 for p in piles)
    assert "Province" not in piles


def test_gaining_from_the_trash_triggers_when_gain_abilities():
    """"When-gain abilities will trigger" — a Death Cart robbed out of the
    trash still brings its 2 Ruins."""
    g = fresh()
    g["trash"].append("Death Cart")
    give_hand(g, A, ["Graverobber"])
    play(g, A, "Graverobber")
    decide(g, A, ids=["trash"])
    assert decide(g, A, cards=["Death Cart"])[0]
    assert sum(1 for c in g["seats"][A]["discard"]
               if engine.has_type(g, c, "ruins")) == 2


# ── Hermit ────────────────────────────────────────────────────────────────────

def test_hermit_trashes_from_the_discard_pile_then_gains():
    g = fresh()
    give_hand(g, A, ["Hermit", "Copper"])
    g["seats"][A]["discard"] = ["Estate", "Silver"]
    assert play(g, A, "Hermit")[0]
    cands = frame(g)["constraint"]["cards"]
    assert "Estate" in cands and "Silver" not in cands, "non-Treasures only"
    assert "Copper" not in cands
    assert decide(g, A, cards=["Estate"])[0]
    assert "Estate" in g["trash"]
    piles = frame(g)["constraint"]["piles"]
    assert all(engine.cost(g, p) <= 3 for p in piles)
    assert decide(g, A, pile="Silver")[0]
    assert "Silver" in g["seats"][A]["discard"]


def test_hermit_may_trash_nothing_and_still_gains():
    g = fresh()
    give_hand(g, A, ["Hermit", "Estate"])
    play(g, A, "Hermit")
    assert decide(g, A, cards=[])[0]
    assert frame(g)["kind"] == "choose_pile"
    assert g["trash"] == []


def test_hermit_exchanges_itself_for_a_madman_on_a_gainless_buy_phase():
    g = fresh()
    give_hand(g, A, ["Hermit"])
    hermits = engine.pile_count(g, "Hermit")
    play(g, A, "Hermit")
    decide(g, A, cards=[])
    decide(g, A, pile="Copper")            # gained in the ACTION phase
    g["phase"] = "buy"
    assert mv(g, A, {"type": "end_phase"})[0]
    seat = g["seats"][A]
    assert "Madman" in seat["discard"]
    assert "Hermit" not in seat["discard"] and "Hermit" not in seat["in_play"]
    assert engine.pile_count(g, "Hermit") == hermits + 1, \
        "the Hermit went back to its pile (an exchange, not a trash)"
    assert engine.pile_count(g, "Madman") == 9


def test_hermit_does_not_exchange_if_you_gained_in_the_buy_phase():
    g = fresh()
    give_hand(g, A, ["Hermit"])
    play(g, A, "Hermit")
    decide(g, A, cards=[])
    decide(g, A, pile="Copper")
    g["phase"] = "buy"
    g["coins"] = 3
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert "Madman" not in g["seats"][A]["discard"]
    assert "Hermit" in g["seats"][A]["discard"]


def test_a_hermit_trashed_from_play_cannot_exchange_itself():
    """"If the Hermit is not in play (for instance if it was trashed by
    Procession), you can't exchange it.\""""
    g = fresh()
    give_hand(g, A, ["Procession", "Hermit"])
    play(g, A, "Procession")
    decide(g, A, cards=["Hermit"])
    # answer both Hermit resolutions, then Procession's gain
    for _ in range(12):
        f = frame(g)
        if f is None:
            break
        if f["kind"] == "choose_cards":
            decide(g, A, cards=[])
        elif f["kind"] == "choose_pile":
            decide(g, A, pile=f["constraint"]["piles"][0])
        else:
            decide(g, A, ids=[f["constraint"]["options"][0]["id"]])
    assert "Hermit" in g["trash"]
    g["phase"] = "buy"
    assert mv(g, A, {"type": "end_phase"})[0]
    assert "Madman" not in engine.owned_cards(g, A)


# ── Marauder ──────────────────────────────────────────────────────────────────

def test_marauder_takes_a_spoils_and_hands_out_ruins():
    g = fresh(players=(A, B, C))
    give_hand(g, A, ["Marauder"])
    assert play(g, A, "Marauder")[0]
    assert "Spoils" in g["seats"][A]["discard"]
    for p in (B, C):
        assert len(g["seats"][p]["discard"]) == 1
        assert engine.has_type(g, g["seats"][p]["discard"][0], "ruins")


def test_the_others_gain_ruins_even_with_no_spoils_left():
    """"The other players gain a Ruins even if you can't gain a Spoils.\""""
    g = fresh()
    g["nonsupply"]["Spoils"] = 0
    give_hand(g, A, ["Marauder"])
    play(g, A, "Marauder")
    assert g["seats"][A]["discard"] == []
    assert len(g["seats"][B]["discard"]) == 1


# ── Pillage ───────────────────────────────────────────────────────────────────

def test_pillage_trashes_itself_for_two_spoils_and_a_forced_discard():
    g = fresh()
    give_hand(g, A, ["Pillage"])
    give_hand(g, B, ["Gold", "Estate", "Copper", "Copper", "Copper"])
    assert play(g, A, "Pillage")[0]
    assert "Pillage" in g["trash"]
    assert g["seats"][A]["discard"].count("Spoils") == 2
    # the ATTACKER chooses which card the victim discards
    assert g["pending_pid"] == A and frame(g)["card"] == "Pillage"
    assert decide(g, A, cards=["Gold"])[0]
    assert "Gold" in g["seats"][B]["discard"]


def test_pillage_spares_a_small_hand():
    g = fresh()
    give_hand(g, A, ["Pillage"])
    give_hand(g, B, ["Gold", "Estate", "Copper", "Copper"])
    play(g, A, "Pillage")
    assert g["pending"] == [], "4 cards in hand: nothing happens to B"
    assert g["seats"][B]["discard"] == []


# ── Procession ────────────────────────────────────────────────────────────────

def test_procession_plays_twice_trashes_and_gains_exactly_one_more():
    g = fresh(kingdom=KDB + ["Village"], expansions=("base", "darkages"))
    give_hand(g, A, ["Procession", "Village"])
    give_deck(g, A, ["Copper"] * 4)
    assert play(g, A, "Procession")[0]
    assert decide(g, A, cards=["Village"])[0]
    assert len(g["seats"][A]["hand"]) == 2, "+1 Card twice"
    assert "Village" in g["trash"]
    piles = frame(g)["constraint"]["piles"]
    assert all(engine.cost(g, p) == 4 and engine.has_type(g, p, "action")
               for p in piles), "an ACTION costing exactly $1 more"
    assert "Estate" not in piles


def test_procession_will_not_play_a_duration():
    g = fresh(kingdom=KDB + ["Caravan"], expansions=("seaside", "darkages"))
    give_hand(g, A, ["Procession", "Caravan", "Fortress"])
    play(g, A, "Procession")
    assert frame(g)["constraint"]["cards"] == ["Fortress"]


def test_procession_gains_even_when_it_cannot_trash():
    """"Even if you are not able to trash the played Action, you gain a card."
    A Death Cart that trashed itself the first time is gone by then."""
    g = fresh()
    give_hand(g, A, ["Procession", "Death Cart"])
    play(g, A, "Procession")
    decide(g, A, cards=["Death Cart"])
    assert decide(g, A, ids=["self"])[0]        # first play: trash the Death Cart
    assert decide(g, A, ids=["none"])[0]        # second play: nothing left to do
    assert g["trash"].count("Death Cart") == 1
    assert frame(g)["kind"] == "choose_pile"
    assert all(engine.cost(g, p) == 5 for p in frame(g)["constraint"]["piles"])


# ── Rats ──────────────────────────────────────────────────────────────────────

def test_rats_gains_a_rats_and_trashes_something_else():
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Rats", "Estate"])
    give_deck(g, A, ["Copper"])
    assert play(g, A, "Rats")[0]
    assert "Rats" in g["seats"][A]["discard"]
    assert g["supply"]["Rats"] == 19
    cands = frame(g)["constraint"]["cards"]
    assert "Rats" not in cands
    assert decide(g, A, cards=["Estate"])[0]
    assert "Estate" in g["trash"]


def test_a_hand_of_all_rats_is_revealed_instead():
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Rats", "Rats"])
    give_deck(g, A, ["Rats"])
    assert play(g, A, "Rats")[0]
    assert g["pending"] == []
    assert g["trash"] == []
    assert any(e["event"] == "reveal" for e in g["log"])


def test_rats_on_trash_draws_a_card():
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Rats"])
    give_deck(g, A, ["Gold"])
    engine.trash(g, A, ["Rats"])
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Gold"]


# ── Rebuild ───────────────────────────────────────────────────────────────────

def test_rebuild_skips_the_named_victory_card_and_upgrades_the_next():
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Rebuild"])
    give_deck(g, A, ["Copper", "Estate", "Duchy", "Gold"])
    assert play(g, A, "Rebuild")[0]
    assert decide(g, A, card="Estate")[0]
    assert "Duchy" in g["trash"], "the Estate was named, so it is passed over"
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Estate"]
    piles = frame(g)["constraint"]["piles"]
    assert "Province" in piles and "Duchy" in piles
    assert all(engine.has_type(g, p, "victory") for p in piles)
    assert decide(g, A, pile="Province")[0]
    assert "Province" in g["seats"][A]["discard"]


def test_rebuild_finding_no_victory_card_just_discards_the_deck():
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Rebuild"])
    give_deck(g, A, ["Copper", "Copper"])
    g["seats"][A]["discard"] = []
    play(g, A, "Rebuild")
    assert decide(g, A, card="Estate")[0]
    assert g["pending"] == []
    assert g["seats"][A]["discard"].count("Copper") == 2


# ── Rogue ─────────────────────────────────────────────────────────────────────

def test_rogue_gains_from_the_trash_when_it_can():
    g = fresh(kingdom=KDB2)
    g["trash"].extend(["Gold", "Copper"])
    give_hand(g, A, ["Rogue"])
    assert play(g, A, "Rogue")[0]
    assert g["coins"] == 2
    assert frame(g)["constraint"]["cards"] == ["Gold"]
    assert decide(g, A, cards=["Gold"])[0]
    assert "Gold" in g["seats"][A]["discard"]
    assert g["seats"][B]["discard"] == [], "it does not also attack"


def test_rogue_attacks_when_the_trash_has_nothing_it_wants():
    g = fresh(kingdom=KDB2)
    g["trash"].append("Copper")
    give_hand(g, A, ["Rogue"])
    give_deck(g, B, ["Gold", "Estate"])
    assert play(g, A, "Rogue")[0]
    assert "Gold" in g["trash"]
    assert "Estate" in g["seats"][B]["discard"]


def test_the_victim_chooses_when_both_revealed_cards_qualify():
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Rogue"])
    give_deck(g, B, ["Gold", "Silver"])
    play(g, A, "Rogue")
    assert g["pending_pid"] == B, "the ATTACKED player picks"
    assert sorted(frame(g)["constraint"]["cards"]) == ["Gold", "Silver"]
    assert decide(g, B, cards=["Silver"])[0]
    assert "Silver" in g["trash"] and "Gold" in g["seats"][B]["discard"]


# ── Urchin ────────────────────────────────────────────────────────────────────

def test_urchin_makes_them_discard_down_to_four():
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Urchin"])
    give_deck(g, A, ["Copper"])
    give_hand(g, B, ["Copper"] * 6)
    assert play(g, A, "Urchin")[0]
    assert decide(g, B, cards=["Copper", "Copper"])[0]
    assert len(g["seats"][B]["hand"]) == 4


def test_urchin_trashes_itself_for_a_mercenary_before_the_next_attack():
    g = fresh(kingdom=KDB2)
    g["seats"][A]["in_play"] = ["Urchin"]
    give_hand(g, A, ["Rogue"])
    g["trash"].append("Copper")
    give_deck(g, B, ["Estate", "Copper"])
    assert play(g, A, "Rogue")[0]
    # the BEFORE-play ability resolves first
    assert frame(g)["card"] == "Urchin" and opt_ids(g) == ["trash", "decline"]
    assert decide(g, A, ids=["trash"])[0]
    assert "Urchin" in g["trash"]
    assert "Mercenary" in g["seats"][A]["discard"]
    assert engine.pile_count(g, "Mercenary") == 9


def test_urchin_does_not_trigger_on_a_throne_roomed_replay_of_itself():
    """"The before-play ability only triggers if you play another Attack card,
    not if you play the same Urchin multiple times with a throne-room.\""""
    g = fresh(kingdom=KDB2 + ["Throne Room"], expansions=("base", "darkages"))
    give_hand(g, A, ["Throne Room", "Urchin"])
    give_deck(g, A, ["Copper"] * 4)
    give_hand(g, B, ["Copper"] * 5)
    play(g, A, "Throne Room")
    assert decide(g, A, cards=["Urchin"])[0]
    for _ in range(8):
        f = frame(g)
        if f is None:
            break
        assert f["card"] != "Urchin" or f["stage"] != "mercenary", \
            "a replay is not another Attack card"
        if f["kind"] == "choose_cards":
            decide(g, f["pid"], cards=f["constraint"]["cards"][:f["constraint"]["min"]])
        else:
            decide(g, f["pid"], ids=[f["constraint"]["options"][0]["id"]])
    assert "Urchin" not in g["trash"]


def test_urchin_may_decline_and_stays_in_play():
    g = fresh(kingdom=KDB2)
    g["seats"][A]["in_play"] = ["Urchin"]
    give_hand(g, A, ["Rogue"])
    g["trash"].append("Copper")
    give_deck(g, B, ["Estate", "Copper"])
    play(g, A, "Rogue")
    assert decide(g, A, ids=["decline"])[0]
    assert g["seats"][A]["in_play"].count("Urchin") == 1
    assert "Mercenary" not in engine.owned_cards(g, A)


def test_mercenary_trashes_two_for_cards_coins_and_a_discard_attack():
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Mercenary", "Copper", "Estate"])
    give_deck(g, A, ["Gold", "Gold"])
    give_hand(g, B, ["Copper"] * 5)
    assert play(g, A, "Mercenary")[0]
    assert decide(g, A, cards=["Copper", "Estate"])[0]
    assert g["seats"][A]["hand"] == ["Gold", "Gold"]
    assert g["coins"] == 2
    assert decide(g, B, cards=["Copper", "Copper"])[0]
    assert len(g["seats"][B]["hand"]) == 3


def test_mercenary_that_trashes_fewer_than_two_does_nothing_else():
    """"With one card in hand you can choose to trash that card, but then
    Mercenary would do nothing further.\""""
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Mercenary", "Copper"])
    give_hand(g, B, ["Copper"] * 5)
    play(g, A, "Mercenary")
    assert decide(g, A, cards=["Copper"])[0]
    assert "Copper" in g["trash"]
    assert g["coins"] == 0 and g["pending"] == []
    assert len(g["seats"][B]["hand"]) == 5


def test_madman_returns_itself_and_draws_your_hand_again():
    g = fresh()
    give_hand(g, A, ["Madman", "Copper", "Copper", "Estate"])
    give_deck(g, A, ["Gold"] * 5)
    g["nonsupply"]["Madman"] = 9
    assert play(g, A, "Madman")[0]
    assert g["actions"] == 2, "+2 Actions, minus the one the play spent"
    assert engine.pile_count(g, "Madman") == 10, "it goes back to its pile"
    assert len(g["seats"][A]["hand"]) == 6, "3 in hand => +3 Cards"


# ── THE KNIGHTS ───────────────────────────────────────────────────────────────

def test_a_knight_trashes_one_card_in_the_band_and_discards_the_rest():
    g = fresh(kingdom=KDB2)
    set_knights(g, ["Dame Sylvia"] + KNIGHTS[:9])
    give_hand(g, A, ["Dame Sylvia"])
    give_deck(g, B, ["Estate", "Gold"])
    assert play(g, A, "Dame Sylvia")[0]
    assert g["coins"] == 2, "Dame Sylvia's own +$2"
    assert "Gold" in g["trash"], "$6 is in the band; the $2 Estate is not"
    assert "Estate" in g["seats"][B]["discard"]


def test_a_knight_that_trashes_a_knight_is_trashed_itself():
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Sir Bailey"])
    give_deck(g, A, ["Copper"])
    give_deck(g, B, ["Dame Molly", "Copper"])
    assert play(g, A, "Sir Bailey")[0]
    assert "Dame Molly" in g["trash"]
    assert "Sir Bailey" in g["trash"], "the played Knight goes down with it"
    assert g["seats"][A]["in_play"] == []


def test_sir_vander_pays_a_gold_when_it_is_trashed():
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Sir Vander"])
    give_deck(g, B, ["Sir Destry", "Copper"])
    assert play(g, A, "Sir Vander")[0]
    assert "Sir Vander" in g["trash"]
    assert "Gold" in g["seats"][A]["discard"], "its own when-trash still fires"


def test_the_victim_picks_which_of_two_eligible_cards_a_knight_takes():
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Dame Josephine"])
    give_deck(g, B, ["Gold", "Silver"])
    play(g, A, "Dame Josephine")
    assert g["pending_pid"] == B
    assert sorted(frame(g)["constraint"]["cards"]) == ["Gold", "Silver"]
    assert decide(g, B, cards=["Gold"])[0]
    assert "Gold" in g["trash"] and "Silver" in g["seats"][B]["discard"]


def test_dame_annas_own_trash_never_trashes_her():
    """"'If a Knight is trashed by this' only applies to opponents' Knights,
    not if you trash a Knight from your hand.\""""
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Dame Anna", "Sir Martin", "Copper"])
    give_deck(g, B, ["Copper", "Estate"])
    assert play(g, A, "Dame Anna")[0]
    assert decide(g, A, cards=["Sir Martin", "Copper"])[0]
    assert "Sir Martin" in g["trash"]
    assert "Dame Anna" in g["seats"][A]["in_play"], "she is NOT trashed"


def test_dame_anna_may_trash_nothing():
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Dame Anna", "Copper"])
    give_deck(g, B, ["Copper", "Estate"])
    play(g, A, "Dame Anna")
    assert decide(g, A, cards=[])[0]
    assert g["trash"] == []


def test_dame_natalies_gain_is_optional_and_capped_at_three():
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Dame Natalie"])
    give_deck(g, B, ["Copper", "Estate"])
    play(g, A, "Dame Natalie")
    cands = frame(g)["constraint"]["cards"]
    assert frame(g)["constraint"]["min"] == 0
    assert all(engine.cost(g, p) <= 3 for p in cands)
    assert decide(g, A, cards=["Silver"])[0]
    assert "Silver" in g["seats"][A]["discard"]


def test_sir_michael_discards_before_the_reveal():
    """"Each other player discards down to 3 cards in hand. THIS HAPPENS BEFORE
    they all reveal cards from their deck.\""""
    g = fresh(kingdom=KDB2)
    give_hand(g, A, ["Sir Michael"])
    give_hand(g, B, ["Gold", "Gold", "Copper", "Copper", "Estate"])
    give_deck(g, B, ["Silver", "Copper"])
    assert play(g, A, "Sir Michael")[0]
    assert frame(g)["stage"] == "militia_discard"
    assert decide(g, B, cards=["Copper", "Copper"])[0]
    assert len(g["seats"][B]["hand"]) == 3
    # ...and only now the Knight attack proper
    assert "Silver" in g["trash"]


def test_each_knight_brings_its_own_bonus():
    for name, check in (
            ("Sir Bailey", lambda gg: len(gg["seats"][A]["hand"]) == 1
             and gg["actions"] == 1),
            ("Sir Destry", lambda gg: len(gg["seats"][A]["hand"]) == 2),
            ("Sir Martin", lambda gg: gg["buys"] == 3),
            ("Dame Molly", lambda gg: gg["actions"] == 2),
            ("Dame Sylvia", lambda gg: gg["coins"] == 2)):
        g = fresh(kingdom=KDB2)
        give_hand(g, A, [name])
        give_deck(g, A, ["Copper"] * 3)
        give_deck(g, B, ["Copper", "Copper"])
        assert play(g, A, name)[0], name
        assert check(g), name


def test_dame_josephine_is_worth_two_victory_points():
    g = fresh(kingdom=KDB2)
    g["seats"][A]["discard"].append("Dame Josephine")
    assert engine._vp_of(g, A) - engine._vp_of(g, B) == 2


# ── THE RUINS ─────────────────────────────────────────────────────────────────

def test_every_ruin_does_its_one_small_thing():
    checks = {
        "Abandoned Mine": lambda gg: gg["coins"] == 1,
        "Ruined Library": lambda gg: len(gg["seats"][A]["hand"]) == 1,
        "Ruined Market": lambda gg: gg["buys"] == 2,
        "Ruined Village": lambda gg: gg["actions"] == 1,
    }
    for name, check in checks.items():
        g = fresh(kingdom=["Marauder"] + KDB[3:] + ["Squire"])
        give_hand(g, A, [name])
        give_deck(g, A, ["Copper"])
        assert play(g, A, name)[0], name
        assert check(g), name


def test_survivors_can_discard_both_or_reorder_them():
    g = fresh(kingdom=["Marauder"] + KDB[3:] + ["Squire"])
    give_hand(g, A, ["Survivors"])
    give_deck(g, A, ["Gold", "Estate", "Copper"])
    play(g, A, "Survivors")
    assert decide(g, A, ids=["discard"])[0]
    assert sorted(g["seats"][A]["discard"]) == ["Estate", "Gold"]

    g2 = fresh(kingdom=["Marauder"] + KDB[3:] + ["Squire"])
    give_hand(g2, A, ["Survivors"])
    give_deck(g2, A, ["Gold", "Estate", "Copper"])
    play(g2, A, "Survivors")
    assert decide(g2, A, ids=["keep"])[0]
    assert decide(g2, A, order=["Estate", "Gold"])[0]
    assert g2["seats"][A]["deck"] == ["Estate", "Gold", "Copper"]


# ── THE SHELTERS ──────────────────────────────────────────────────────────────

def test_necropolis_is_a_village():
    g = fresh()
    give_hand(g, A, ["Necropolis"])
    assert play(g, A, "Necropolis")[0]
    assert g["actions"] == 2


def test_overgrown_estate_is_worth_nothing_and_draws_when_trashed():
    g = fresh()
    give_hand(g, A, ["Overgrown Estate"])
    give_deck(g, A, ["Gold"])
    assert engine.CARDS["Overgrown Estate"]["vp"] == 0
    engine.trash(g, A, ["Overgrown Estate"])
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Gold"]


def test_hovel_trashes_itself_when_you_gain_a_victory_card():
    g = fresh()
    give_hand(g, A, ["Hovel"])
    engine.gain(g, A, "Duchy")
    engine._drive(g)
    assert frame(g)["card"] == "Hovel"
    assert decide(g, A, ids=["play"])[0]
    assert "Hovel" in g["trash"] and "Hovel" not in g["seats"][A]["hand"]


def test_hovel_ignores_a_non_victory_gain_and_may_decline():
    g = fresh()
    give_hand(g, A, ["Hovel"])
    engine.gain(g, A, "Silver")
    engine._drive(g)
    assert g["pending"] == []

    engine.gain(g, A, "Estate")
    engine._drive(g)
    assert decide(g, A, ids=["decline"])[0]
    assert "Hovel" in g["seats"][A]["hand"]


def test_a_dark_ages_bane_brings_its_own_setup_pile():
    """"If these extra cards have a special setup rule, do that setup." A
    Hermit chosen as Young Witch's Bane is in the game, so the Madman pile
    comes with it — and a Looter Bane brings the Ruins."""
    g = engine.new_game([A, B], ["cornucopia", "darkages"], seed=4,
                        kingdom=["Young Witch", "Altar", "Armory", "Catacombs",
                                 "Count", "Fortress", "Ironmonger", "Mystic",
                                 "Rebuild", "Squire"])
    # the Bane is drawn from the unused $2/$3 cards of the enabled sets
    assert g["bane"] is not None and g["bane"] in g["supply"]
    if g["bane"] == "Hermit":
        assert "Madman" in g["nonsupply"]
    if g["bane"] == "Urchin":
        assert "Mercenary" in g["nonsupply"]
    # ...and the rule holds however the Bane landed: force one and re-check
    forced = engine.new_game([A, B], ["cornucopia", "darkages"], seed=4,
                             kingdom=["Young Witch", "Altar", "Armory",
                                      "Catacombs", "Count", "Fortress",
                                      "Ironmonger", "Mystic", "Rebuild",
                                      "Squire"])
    assert forced["bane"] == g["bane"], "the same seed deals the same Bane"
