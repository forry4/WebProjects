"""Renaissance, half A — the 13 cards whose interest is their own play ability
(plus their when-gain/when-trash riders) and the 8 Projects that ride seams the
kernel already had.

Acting Troupe, Ducat, Flag Bearer, Hideout, Lackeys, Old Witch, Recruiter,
Scholar, Sculptor, Silk Merchant, Spices, Swashbuckler, Villain; Academy,
Barracks, Cathedral, Crop Rotation, Fair, Guildhall, Pageant, Silos.

Positions are arranged by mutating the game dict (the repo's board-fixture
idiom); give_hand breaks card conservation, so nothing here asserts the census
— test_soak owns that. A PROJECT CUBE is written straight into
`landscapes[name]["bought_by"]`, which is all a cube is (Kernel v9).

Headline rulings pinned here:
  * **Scholar with an empty hand still draws 7.**
  * **Swashbuckler reads the discard pile AFTER drawing** — the +3 Cards can
    shuffle it away, and then nothing further happens — and the >=4 Coffers
    test is made AFTER the +1.
  * **Old Witch**: an empty Curse pile still lets them trash; an UNAFFECTED
    player neither gains nor may trash; per opponent it is gain-THEN-may-trash.
  * **Sculptor's "it" is the gained card** — no gain, no Villager.
  * **Villain** only hits a hand of 5+, tests the COIN component alone, and
    "reveals they can't" reveals the WHOLE HAND through `reveal()`.
  * **Acting Troupe played without moving still pays 4 Villagers** (Throne
    Room = 8) and trashes once.
  * **Cathedral's trash is MANDATORY.**
"""

from games.dontminion import engine

A, B, C = "alice", "bob", "carol"

# half A's own cards, in two boards (13 cards, 10 to a kingdom). Flag Bearer
# and Swashbuckler must be IN THE GAME for their Artifacts to be kept
# available (cards.artifacts_for), which is why KA carries both.
KA = ["Lackeys", "Acting Troupe", "Flag Bearer", "Hideout", "Silk Merchant",
      "Old Witch", "Recruiter", "Scholar", "Sculptor", "Swashbuckler"]
KB = ["Ducat", "Spices", "Villain", "Lackeys", "Hideout", "Recruiter",
      "Scholar", "Sculptor", "Acting Troupe", "Silk Merchant"]
# a mixed board for the cross-set corners (Moat's immunity, Throne Room)
KM = ["Old Witch", "Villain", "Acting Troupe", "Flag Bearer", "Silk Merchant",
      "Scholar", "Sculptor", "Swashbuckler", "Moat", "Throne Room"]


def fresh(players=(A, B), seed=7, kingdom=tuple(KA),
          expansions=("renaissance", "base"), landscapes=()):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom), landscapes=list(landscapes))


def give_hand(g, pid, cards):
    g["seats"][pid]["hand"] = list(cards)


def give_deck(g, pid, cards):
    g["seats"][pid]["deck"] = list(cards)


def give_discard(g, pid, cards):
    g["seats"][pid]["discard"] = list(cards)


def give_cube(g, name, pid):
    """A Project cube IS the `bought_by` record (Kernel v9)."""
    g["landscapes"][name]["bought_by"].append(pid)


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


def frame(g):
    return g["pending"][-1] if g["pending"] else None


def opt_ids(g):
    return [o["id"] for o in frame(g)["constraint"]["options"]]


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


# ══ $2 ═══════════════════════════════════════════════════════════════════════

# --- Lackeys -----------------------------------------------------------------

def test_lackeys_draws_two():
    g = fresh()
    give_hand(g, A, ["Lackeys"])
    give_deck(g, A, ["Copper", "Estate", "Silver"])
    play(g, A, "Lackeys")
    assert g["seats"][A]["hand"] == ["Copper", "Estate"]


def test_gaining_lackeys_pays_two_villagers():
    g = fresh()
    engine.gain(g, A, "Lackeys")
    engine._drive(g)
    assert g["villagers"][A] == 2
    # a mat persists off turn: bob gains one on alice's turn and keeps it
    engine.gain(g, B, "Lackeys")
    engine._drive(g)
    assert g["villagers"][B] == 2


def test_lackeys_bought_pays_its_villagers_too():
    g = fresh()
    g["phase"] = "buy"
    g["coins"] = 2
    ok, err = mv(g, A, {"type": "buy", "card": "Lackeys"})
    assert ok, err
    engine._drive(g)
    assert g["villagers"][A] == 2


# --- Ducat -------------------------------------------------------------------

def test_ducat_is_a_coffers_and_a_buy():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Ducat"])
    g["phase"] = "buy"
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Ducat"})
    assert ok, err
    assert g["coffers"].get(A, 0) == 1
    assert g["buys"] == 2
    assert g["coins"] == 0, "Ducat produces no $"


def test_gaining_a_ducat_may_trash_a_copper():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Copper", "Estate"])
    engine.gain(g, A, "Ducat")
    engine._drive(g)
    f = frame(g)
    assert f is not None and f["card"] == "Ducat"
    assert f["constraint"]["cards"] == ["Copper"] and f["constraint"]["min"] == 0
    decide(g, A, cards=["Copper"])
    assert g["trash"] == ["Copper"]
    assert g["seats"][A]["hand"] == ["Estate"]


def test_the_ducat_trash_is_optional_and_skipped_with_no_copper():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Copper"])
    engine.gain(g, A, "Ducat")
    engine._drive(g)
    decide(g, A, cards=[])                       # "you MAY trash"
    assert g["trash"] == [] and g["seats"][A]["hand"] == ["Copper"]

    g2 = fresh(kingdom=KB)
    give_hand(g2, A, ["Estate"])
    engine.gain(g2, A, "Ducat")
    engine._drive(g2)
    assert frame(g2) is None, "no Copper in hand: no prompt at all"


# ══ $3 ═══════════════════════════════════════════════════════════════════════

# --- Acting Troupe -----------------------------------------------------------

def test_acting_troupe_pays_four_villagers_and_trashes_itself():
    g = fresh()
    give_hand(g, A, ["Acting Troupe"])
    play(g, A, "Acting Troupe")
    assert g["villagers"][A] == 4
    assert g["trash"] == ["Acting Troupe"]
    assert g["seats"][A]["in_play"] == []


def test_a_throne_roomed_acting_troupe_pays_eight_and_trashes_once():
    """"You get +4 Villagers even if you don't trash this" — the second play
    finds nothing on the table, so a Throne Room gives 8 Villagers and one
    trashed Acting Troupe."""
    g = fresh(kingdom=KM)
    give_hand(g, A, ["Throne Room", "Acting Troupe"])
    play(g, A, "Throne Room")
    decide(g, A, cards=["Acting Troupe"])
    assert g["villagers"][A] == 8
    assert g["trash"] == ["Acting Troupe"]


def test_the_villagers_are_spendable_for_actions_in_the_action_phase():
    g = fresh()
    give_hand(g, A, ["Acting Troupe", "Scholar"])
    play(g, A, "Acting Troupe")
    assert g["actions"] == 0 and g["villagers"][A] == 4
    ok, err = mv(g, A, {"type": "spend", "what": "villagers", "n": 2})
    assert ok, err
    assert g["actions"] == 2 and g["villagers"][A] == 2


# ══ $4 ═══════════════════════════════════════════════════════════════════════

# --- Flag Bearer -------------------------------------------------------------

def test_flag_bearer_is_two_coins():
    g = fresh()
    give_hand(g, A, ["Flag Bearer"])
    play(g, A, "Flag Bearer")
    assert g["coins"] == 2


def test_the_flag_is_taken_on_gain_and_on_trash():
    g = fresh()
    assert g["artifacts"]["Flag"] is None
    engine.gain(g, A, "Flag Bearer")
    engine._drive(g)
    assert engine.holds_artifact(g, A, "Flag")
    # ...and on a TRASH, including one on someone else's turn
    give_hand(g, B, ["Flag Bearer"])
    engine.trash(g, B, ["Flag Bearer"])
    engine._drive(g)
    assert engine.holds_artifact(g, B, "Flag")
    assert not engine.holds_artifact(g, A, "Flag"), "one copy — B took it from A"


def test_the_flag_draws_a_sixth_card_at_cleanup():
    """"As long as you have Flag, you draw one more card in Clean-up." """
    g = fresh()
    engine.gain(g, A, "Flag Bearer")
    engine._drive(g)
    g["phase"] = "buy"
    end_turn(g, A)
    assert len(g["seats"][A]["hand"]) == 6


# --- Hideout -----------------------------------------------------------------

def test_hideout_is_a_cantrip_with_two_actions_and_a_trash():
    g = fresh()
    give_hand(g, A, ["Hideout", "Copper"])
    give_deck(g, A, ["Silver"] * 5)
    play(g, A, "Hideout")
    assert g["actions"] == 2
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Silver"]
    decide(g, A, cards=["Copper"])
    assert g["trash"] == ["Copper"]
    assert g["supply"]["Curse"] == 10, "a Copper is not a Victory card"


def test_hideout_trashing_a_victory_card_gains_a_curse():
    g = fresh()
    give_hand(g, A, ["Hideout", "Estate"])
    give_deck(g, A, ["Silver"] * 5)
    play(g, A, "Hideout")
    decide(g, A, cards=["Estate"])
    engine._drive(g)
    assert g["trash"] == ["Estate"]
    assert g["seats"][A]["discard"] == ["Curse"]
    assert g["supply"]["Curse"] == 9


# --- Silk Merchant -----------------------------------------------------------

def test_silk_merchant_draws_two_and_a_buy():
    g = fresh()
    give_hand(g, A, ["Silk Merchant"])
    give_deck(g, A, ["Copper", "Estate", "Silver"])
    play(g, A, "Silk Merchant")
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Estate"]
    assert g["buys"] == 2


def test_silk_merchant_pays_a_coffers_and_a_villager_on_gain_and_on_trash():
    g = fresh()
    engine.gain(g, A, "Silk Merchant")
    engine._drive(g)
    assert g["coffers"].get(A, 0) == 1 and g["villagers"][A] == 1
    give_hand(g, A, ["Silk Merchant"])
    engine.trash(g, A, ["Silk Merchant"])
    engine._drive(g)
    assert g["coffers"].get(A, 0) == 2 and g["villagers"][A] == 2


# ══ $5 ═══════════════════════════════════════════════════════════════════════

# --- Old Witch ---------------------------------------------------------------

def _answer_old_witch(g, pid, cards):
    f = frame(g)
    assert f is not None and f["pid"] == pid and f["card"] == "Old Witch"
    decide(g, pid, cards=cards)


def test_old_witch_draws_three_and_curses_each_opponent():
    g = fresh(players=(A, B, C))
    give_hand(g, A, ["Old Witch"])
    give_deck(g, A, ["Silver"] * 5)
    for p in (B, C):
        give_hand(g, p, ["Estate"])
    play(g, A, "Old Witch")
    assert len(g["seats"][A]["hand"]) == 3
    # in turn order: bob first, then carol — each gains, then MAY trash a Curse
    for p in (B, C):
        assert "Curse" in g["seats"][p]["discard"]
        # the Curse they just gained is in the DISCARD, not the hand, so with
        # no Curse in hand there is no prompt for them at all
    assert g["supply"]["Curse"] == 10 * (3 - 1) - 2
    assert frame(g) is None


def test_an_opponent_may_trash_a_curse_from_hand_after_gaining_one():
    g = fresh()
    give_hand(g, A, ["Old Witch"])
    give_deck(g, A, ["Silver"] * 5)
    give_hand(g, B, ["Curse", "Estate"])
    play(g, A, "Old Witch")
    _answer_old_witch(g, B, ["Curse"])
    assert g["trash"] == ["Curse"]
    assert g["seats"][B]["hand"] == ["Estate"]
    assert g["seats"][B]["discard"] == ["Curse"], "the gained one still landed"
    # ...and declining is legal, too
    g2 = fresh()
    give_hand(g2, A, ["Old Witch"])
    give_deck(g2, A, ["Silver"] * 5)
    give_hand(g2, B, ["Curse"])
    play(g2, A, "Old Witch")
    _answer_old_witch(g2, B, [])
    assert g2["trash"] == [] and g2["seats"][B]["hand"] == ["Curse"]


def test_an_empty_curse_pile_still_lets_them_trash():
    """"If the Curse pile is empty, the other players may still trash a
    Curse." """
    g = fresh()
    g["supply"]["Curse"] = 0
    give_hand(g, A, ["Old Witch"])
    give_deck(g, A, ["Silver"] * 5)
    give_hand(g, B, ["Curse"])
    play(g, A, "Old Witch")
    _answer_old_witch(g, B, ["Curse"])
    assert g["trash"] == ["Curse"]
    assert g["seats"][B]["discard"] == [], "nothing was gained"


def test_an_unaffected_player_neither_gains_nor_may_trash():
    """"A player who is not affected by the attack (Moat, Lighthouse, …)
    neither gains a Curse nor may trash one." """
    g = fresh(kingdom=KM)
    give_hand(g, A, ["Old Witch"])
    give_deck(g, A, ["Silver"] * 5)
    give_hand(g, B, ["Moat", "Curse"])
    play(g, A, "Old Witch")
    f = frame(g)
    assert f["pid"] == B and "react:Moat" in opt_ids(g)
    decide(g, B, ids=["react:Moat"])
    assert frame(g) is None, "no gain, and no trash offer either"
    assert g["seats"][B]["discard"] == []
    assert g["seats"][B]["hand"] == ["Moat", "Curse"]
    assert g["supply"]["Curse"] == 10


# --- Recruiter ---------------------------------------------------------------

def test_recruiter_draws_two_and_pays_a_villager_per_dollar():
    g = fresh()
    give_hand(g, A, ["Recruiter"])
    give_deck(g, A, ["Gold", "Copper", "Estate"])
    play(g, A, "Recruiter")
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Gold"]
    decide(g, A, cards=["Gold"])                 # Gold costs $6
    engine._drive(g)
    assert g["trash"] == ["Gold"]
    assert g["villagers"][A] == 6


def test_recruiter_trashing_a_free_card_pays_nothing():
    g = fresh()
    give_hand(g, A, ["Recruiter"])
    give_deck(g, A, ["Copper", "Copper"])
    play(g, A, "Recruiter")
    decide(g, A, cards=["Copper"])               # Copper costs $0
    engine._drive(g)
    assert g["villagers"][A] == 0


# --- Scholar -----------------------------------------------------------------

def test_scholar_discards_your_hand_and_draws_seven():
    g = fresh()
    give_hand(g, A, ["Scholar", "Copper", "Estate"])
    give_deck(g, A, ["Silver"] * 8)
    play(g, A, "Scholar")
    engine._drive(g)
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Estate"]
    assert g["seats"][A]["hand"] == ["Silver"] * 7


def test_scholar_with_an_empty_hand_still_draws_seven():
    """"If you don't have any cards in your hand to discard, you still draw 7
    cards." """
    g = fresh()
    give_hand(g, A, ["Scholar"])
    give_deck(g, A, ["Silver"] * 8)
    play(g, A, "Scholar")
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Silver"] * 7


# --- Sculptor ----------------------------------------------------------------

def test_sculptor_gains_to_hand_and_a_treasure_pays_a_villager():
    g = fresh()
    give_hand(g, A, ["Sculptor"])
    play(g, A, "Sculptor")
    f = frame(g)
    assert "Silver" in f["constraint"]["piles"]
    assert "Gold" not in f["constraint"]["piles"], "Gold costs $6"
    decide(g, A, pile="Silver")
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Silver"], "gained TO YOUR HAND"
    assert g["villagers"][A] == 1


def test_sculptor_gaining_a_non_treasure_pays_no_villager():
    g = fresh()
    give_hand(g, A, ["Sculptor"])
    play(g, A, "Sculptor")
    decide(g, A, pile="Estate")
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Estate"]
    assert g["villagers"][A] == 0


def test_sculptor_with_nothing_gainable_gains_nothing_and_pays_nothing():
    """"'It' refers to the gained card" — no gain, no Villager."""
    g = fresh()
    for pile in list(g["supply"]):
        if engine.cost_le(g, pile, 4):
            g["supply"][pile] = 0
    give_hand(g, A, ["Sculptor"])
    play(g, A, "Sculptor")
    assert frame(g) is None
    assert g["villagers"][A] == 0
    assert g["seats"][A]["hand"] == []


# --- Spices ------------------------------------------------------------------

def test_spices_is_two_coins_and_a_buy():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Spices"])
    g["phase"] = "buy"
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Spices"})
    assert ok, err
    assert g["coins"] == 2 and g["buys"] == 2


def test_gaining_spices_pays_two_coffers():
    g = fresh(kingdom=KB)
    engine.gain(g, A, "Spices")
    engine._drive(g)
    assert g["coffers"].get(A, 0) == 2


def test_spices_and_ducat_are_played_by_the_bulk_button():
    """Neither pushes a frame, draws, looks or reveals — bucket 3."""
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Copper", "Spices", "Ducat"])
    g["phase"] = "buy"
    assert engine.autoplay_treasures(g, A) == ["Copper", "Spices", "Ducat"]
    ok, err = mv(g, A, {"type": "play_all_treasures"})
    assert ok, err
    assert g["coins"] == 3 and g["buys"] == 3
    assert g["coffers"].get(A, 0) == 1


# --- Swashbuckler ------------------------------------------------------------

def test_swashbuckler_draws_three_and_pays_a_coffers():
    g = fresh()
    give_hand(g, A, ["Swashbuckler"])
    give_deck(g, A, ["Silver"] * 5)
    give_discard(g, A, ["Estate"])
    play(g, A, "Swashbuckler")
    assert g["seats"][A]["hand"] == ["Silver"] * 3
    assert g["coffers"].get(A, 0) == 1
    assert g["artifacts"]["Treasure Chest"] is None


def test_swashbuckler_does_nothing_when_the_draw_shuffles_the_discard_away():
    """"If your discard pile is empty AFTER drawing, you do nothing further" —
    the +3 Cards can be the very shuffle that empties it."""
    g = fresh()
    give_hand(g, A, ["Swashbuckler"])
    give_deck(g, A, [])
    give_discard(g, A, ["Silver", "Silver", "Silver"])
    play(g, A, "Swashbuckler")
    assert len(g["seats"][A]["hand"]) == 3
    assert g["seats"][A]["discard"] == []
    assert g["coffers"].get(A, 0) == 0


def test_swashbuckler_takes_the_treasure_chest_at_four_coffers():
    """The threshold is checked AFTER the +1: three on the mat is enough."""
    g = fresh()
    g["coffers"][A] = 3
    give_hand(g, A, ["Swashbuckler"])
    give_deck(g, A, ["Silver"] * 5)
    give_discard(g, A, ["Estate"])
    play(g, A, "Swashbuckler")
    assert g["coffers"][A] == 4
    assert engine.holds_artifact(g, A, "Treasure Chest")

    g2 = fresh()
    g2["coffers"][A] = 2
    give_hand(g2, A, ["Swashbuckler"])
    give_deck(g2, A, ["Silver"] * 5)
    give_discard(g2, A, ["Estate"])
    play(g2, A, "Swashbuckler")
    assert g2["coffers"][A] == 3
    assert not engine.holds_artifact(g2, A, "Treasure Chest")


def test_the_treasure_chest_is_only_available_with_swashbuckler():
    """`new_game` keeps exactly the Artifacts whose granting card is in the
    game — Swashbuckler's is the Treasure Chest. (Its own ability lives with
    the other four Artifacts in half B.)"""
    g = fresh()
    assert g["artifacts"]["Treasure Chest"] is None
    g2 = fresh(kingdom=KB)
    assert "Treasure Chest" not in g2["artifacts"]
    assert "Flag" not in g2["artifacts"], "no Flag Bearer on this board either"


# --- Villain -----------------------------------------------------------------

def test_villain_makes_a_five_card_hand_discard_a_two_or_more():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Villain"])
    give_hand(g, B, ["Copper", "Copper", "Estate", "Silver", "Gold"])
    play(g, A, "Villain")
    assert g["coffers"].get(A, 0) == 2
    f = frame(g)
    assert f["pid"] == B and f["card"] == "Villain"
    # Copper ($0) and Estate ($2)... Estate DOES cost $2
    assert sorted(f["constraint"]["cards"]) == ["Estate", "Gold", "Silver"]
    decide(g, B, cards=["Silver"])
    assert g["seats"][B]["discard"] == ["Silver"]
    assert len(g["seats"][B]["hand"]) == 4


def test_villain_skips_a_hand_below_five():
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Villain"])
    give_hand(g, B, ["Gold", "Gold", "Gold", "Gold"])
    play(g, A, "Villain")
    assert frame(g) is None
    assert g["seats"][B]["hand"] == ["Gold"] * 4


def test_villain_reveals_the_whole_hand_when_nothing_qualifies():
    """"Or reveals they can't" reveals the WHOLE hand — which is why it goes
    through reveal() (a Patron in it would pay its owner)."""
    g = fresh(kingdom=KB)
    give_hand(g, A, ["Villain"])
    give_hand(g, B, ["Copper"] * 5)
    play(g, A, "Villain")
    assert frame(g) is None
    e = events(g, "reveal")[-1]
    assert e["pid"] == B and sorted(e["cards"]) == ["Copper"] * 5
    assert g["seats"][B]["hand"] == ["Copper"] * 5, "revealed cards stay in hand"


def test_villain_reads_the_coin_component_alone():
    """"A card costing '$x or more' must have a coin amount of x or more; it
    may have any Potion and Debt amount" — the A5 reading, via cost_ge."""
    g = fresh(kingdom=KB[:9] + ["Alchemist"],
              expansions=("renaissance", "alchemy"))
    give_hand(g, A, ["Villain"])
    give_hand(g, B, ["Copper", "Copper", "Copper", "Copper", "Alchemist"])
    play(g, A, "Villain")
    f = frame(g)
    # Alchemist costs {$3,P}: the Potion component is irrelevant to a LOWER
    # bound, so it is discardable — while a Copper ($0) is not
    assert f["constraint"]["cards"] == ["Alchemist"]


# ══ THE PROJECTS ═════════════════════════════════════════════════════════════

def test_academy_pays_a_villager_for_an_action_gain_only_to_a_cube_owner():
    g = fresh(landscapes=["Academy"])
    give_cube(g, "Academy", A)
    engine.gain(g, A, "Silver")
    engine._drive(g)
    assert g["villagers"][A] == 0, "a Treasure is not an Action"
    engine.gain(g, A, "Scholar")
    engine._drive(g)
    assert g["villagers"][A] == 1
    engine.gain(g, B, "Scholar")           # bob has no cube
    engine._drive(g)
    assert g["villagers"][B] == 0


def test_academy_fires_on_an_opponents_turn_too():
    """"You might gain a card on another player's turn" — Academy and Guildhall
    both carry that note."""
    g = fresh(landscapes=["Academy"])
    give_cube(g, "Academy", B)
    assert g["turn"] == A
    engine.gain(g, B, "Scholar")
    engine._drive(g)
    assert g["villagers"][B] == 1


def test_guildhall_pays_a_coffers_for_a_treasure_gain():
    g = fresh(landscapes=["Guildhall"])
    give_cube(g, "Guildhall", A)
    engine.gain(g, A, "Silver")
    engine._drive(g)
    assert g["coffers"].get(A, 0) == 1
    engine.gain(g, A, "Estate")
    engine._drive(g)
    assert g["coffers"].get(A, 0) == 1, "an Estate is not a Treasure"


def test_barracks_gives_an_extra_action_at_the_start_of_your_turn():
    g = fresh(landscapes=["Barracks"])
    give_cube(g, "Barracks", B)
    g["phase"] = "buy"
    end_turn(g, A)
    assert g["turn"] == B and g["actions"] == 2
    g["phase"] = "buy"
    end_turn(g, B)
    assert g["turn"] == A and g["actions"] == 1, "alice owns no cube"


def test_fair_gives_an_extra_buy_at_the_start_of_your_turn():
    g = fresh(landscapes=["Fair"])
    give_cube(g, "Fair", B)
    g["phase"] = "buy"
    end_turn(g, A)
    assert g["turn"] == B and g["buys"] == 2
    g["phase"] = "buy"
    end_turn(g, B)
    assert g["turn"] == A and g["buys"] == 1


def test_cathedrals_trash_is_mandatory():
    """"Trashing is of course not optional." """
    g = fresh(landscapes=["Cathedral"])
    give_cube(g, "Cathedral", B)
    g["phase"] = "buy"
    end_turn(g, A)
    assert g["turn"] == B
    f = frame(g)
    assert f is not None and f["card"] == "Cathedral"
    assert f["constraint"]["min"] == 1 and f["constraint"]["max"] == 1
    card = f["constraint"]["cards"][0]
    decide(g, B, cards=[card])
    assert g["trash"] == [card]
    assert len(g["seats"][B]["hand"]) == 4


def test_cathedral_with_an_empty_hand_asks_nothing():
    g = fresh(landscapes=["Cathedral"])
    give_cube(g, "Cathedral", A)
    give_hand(g, A, [])
    engine._start_of_turn(g, A)
    engine._drive(g)
    assert frame(g) is None and g["trash"] == []


def test_crop_rotation_discards_a_victory_card_for_two_cards():
    g = fresh(landscapes=["Crop Rotation"])
    give_cube(g, "Crop Rotation", A)
    give_hand(g, A, ["Estate", "Copper"])
    give_deck(g, A, ["Silver"] * 4)
    engine._start_of_turn(g, A)
    engine._drive(g)
    f = frame(g)
    assert f["card"] == "Crop Rotation"
    assert f["constraint"]["cards"] == ["Estate"] and f["constraint"]["min"] == 0
    decide(g, A, cards=["Estate"])
    engine._drive(g)
    assert g["seats"][A]["discard"] == ["Estate"]
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Silver", "Silver"]


def test_crop_rotation_may_be_declined_and_asks_nothing_without_a_victory_card():
    g = fresh(landscapes=["Crop Rotation"])
    give_cube(g, "Crop Rotation", A)
    give_hand(g, A, ["Estate"])
    give_deck(g, A, ["Silver"] * 4)
    engine._start_of_turn(g, A)
    engine._drive(g)
    decide(g, A, cards=[])                       # "you MAY discard"
    assert g["seats"][A]["hand"] == ["Estate"]

    g2 = fresh(landscapes=["Crop Rotation"])
    give_cube(g2, "Crop Rotation", A)
    give_hand(g2, A, ["Copper", "Silver"])
    engine._start_of_turn(g2, A)
    engine._drive(g2)
    assert frame(g2) is None


def test_silos_discards_revealed_coppers_and_draws_that_many():
    g = fresh(landscapes=["Silos"])
    give_cube(g, "Silos", A)
    give_hand(g, A, ["Copper", "Copper", "Estate"])
    give_deck(g, A, ["Silver"] * 4)
    engine._start_of_turn(g, A)
    engine._drive(g)
    f = frame(g)
    assert f["card"] == "Silos"
    assert f["constraint"]["cards"] == ["Copper", "Copper"]
    assert f["constraint"]["min"] == 0 and f["constraint"]["max"] == 2
    decide(g, A, cards=["Copper", "Copper"])
    engine._drive(g)
    assert sorted(g["seats"][A]["discard"]) == ["Copper", "Copper"]
    assert sorted(g["seats"][A]["hand"]) == ["Estate", "Silver", "Silver"]
    e = events(g, "reveal")[-1]
    assert e["cards"] == ["Copper", "Copper"], "'discard … REVEALED'"


def test_silos_asks_nothing_without_a_copper():
    g = fresh(landscapes=["Silos"])
    give_cube(g, "Silos", A)
    give_hand(g, A, ["Estate", "Silver"])
    engine._start_of_turn(g, A)
    engine._drive(g)
    assert frame(g) is None


def test_pageant_pays_a_dollar_for_a_coffers_at_the_end_of_the_buy_phase():
    g = fresh(landscapes=["Pageant"])
    give_cube(g, "Pageant", A)
    g["phase"] = "buy"
    g["coins"] = 3
    ok, err = mv(g, A, {"type": "end_phase"})
    assert ok, err
    f = frame(g)
    assert f is not None and f["card"] == "Pageant"
    assert opt_ids(g) == ["pay", "no"]
    decide(g, A, ids=["pay"])
    assert g["coffers"].get(A, 0) == 1
    assert g["turn"] == B, "the turn still ended"


def test_pageant_may_be_declined():
    g = fresh(landscapes=["Pageant"])
    give_cube(g, "Pageant", A)
    g["phase"] = "buy"
    g["coins"] = 1
    ok, err = mv(g, A, {"type": "end_phase"})
    assert ok, err
    decide(g, A, ids=["no"])
    assert g["coffers"].get(A, 0) == 0
    assert g["turn"] == B


def test_pageant_offers_nothing_with_an_empty_money_pool():
    """"If you have at least $1 in your money pool, you may pay $1" — with
    none, there is nothing to offer."""
    g = fresh(landscapes=["Pageant"])
    give_cube(g, "Pageant", A)
    g["phase"] = "buy"
    g["coins"] = 0
    ok, err = mv(g, A, {"type": "end_phase"})
    assert ok, err
    assert frame(g) is None and g["turn"] == B


def test_pageant_is_offered_once_per_buy_phase_end():
    """The kernel emits `buy_phase_end` once per buy->Clean-up transition, so
    the card's "only once per Buy phase" needs no flag of its own. (A Villa
    return to the Action phase does NOT re-emit it — see the KERNEL GAP note
    in the batch report; this test pins today's behaviour.)"""
    g = fresh(landscapes=["Pageant"])
    give_cube(g, "Pageant", A)
    g["phase"] = "buy"
    g["coins"] = 5
    ok, err = mv(g, A, {"type": "end_phase"})
    assert ok, err
    decide(g, A, ids=["pay"])
    assert g["coffers"].get(A, 0) == 1
    assert frame(g) is None, "one offer, not a loop"


def test_pageant_is_offered_once_per_buy_phase_including_after_a_villa():
    """The KERNEL GAP this batch reported, now CLOSED.

    "If you have several Buy phases due to … Villa, Exploration triggers each
    time, checking the Buy phase that just ended", and Pageant's "once per Buy
    phase" is the same per-entrance limit. `return_to_action_phase` now emits
    `buy_phase_end` (with `final=False`, which is what keeps the three cards
    that only RIDE that event to approximate Clean-up timing — Alchemist,
    Herbalist, Scheme — firing once)."""
    g = fresh(kingdom=KA[:9] + ["Villa"],
              expansions=("renaissance", "empires"), landscapes=["Pageant"])
    give_cube(g, "Pageant", A)
    g["phase"] = "buy"
    g["coins"], g["buys"] = 8, 3
    ok, err = mv(g, A, {"type": "buy", "card": "Villa"})
    assert ok, err
    engine._drive(g)
    assert g["phase"] == "action"
    assert frame(g) is not None, "the first Buy phase ended — Pageant asks"
    decide(g, A, ids=["pay"])
    assert g["coffers"].get(A, 0) == 1
    ok, err = mv(g, A, {"type": "end_phase"})             # back to buy
    assert ok, err
    ok, err = mv(g, A, {"type": "end_phase"})             # buy -> clean-up
    assert ok, err
    decide(g, A, ids=["pay"])
    assert g["coffers"].get(A, 0) == 2, "one offer per Buy phase, so two"


def test_a_project_ability_needs_the_cube():
    """Every one of half A's Projects is inert for a player without a cube —
    the dealt landscape alone does nothing."""
    g = fresh(landscapes=["Fair", "Guildhall"])
    g["phase"] = "buy"
    end_turn(g, A)
    assert g["buys"] == 1
    engine.gain(g, B, "Silver")
    engine._drive(g)
    assert g["coffers"].get(B, 0) == 0
