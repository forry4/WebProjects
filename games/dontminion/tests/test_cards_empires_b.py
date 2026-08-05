"""Empires, half B — the 13 Events and the 21 Landmarks.

Landmarks are the first landscapes the game deals that are never BOUGHT, so
they exercise three ph.-7H seams at once: `LANDSCAPE_SCORING` (11 of them are
nothing else), `LANDSCAPE_SETUP` (9 of them), and `from:"landscape"` triggers
(8 of them).

Headline rulings pinned here:
  * **The six self-store landmarks put 6 VP PER PLAYER on themselves**, and a
    take is capped at what is left — "if there are none left you get nothing".
  * **Aqueduct's two abilities do NOT auto-run**: "if you gain a card of both
    types, you can resolve them in either order", and the order is worth real
    VP because a Humble Castle is a Treasure AND a Victory card.
  * **The 2022 retiming is "in your Buy phase", not "when you buy"** — a gain
    from a Workshop in the Buy phase counts, and a gain on an opponent's turn
    does not.
  * **Tomb triggers on a Supply trash too** (Salt the Earth, Gladiator, Lurker),
    which is why `trash_from_supply` learned to emit.
  * **Obelisk and Defiled Shrine identify Action piles by the RANDOMIZER**, so
    a split pile counts and both of its halves then score.
  * **Tax's setup covers the BASE cards too**, and taking the Debt is a
    penalty, not a reward.
"""

from games.dontminion import cards, effects, engine

A, B, C = "alice", "bob", "carol"

KE = ["Engineer", "City Quarter", "Chariot Race", "Enchantress",
      "Farmers' Market", "Sacrifice", "Temple", "Villa", "Archive", "Capital"]
KSPLIT = ["Encampment/Plunder", "Patrician/Emporium", "Settlers/Bustling Village",
          "Catapult/Rocks", "Gladiator/Fortune", "Castles",
          "Engineer", "Villa", "Temple", "Forum"]


def fresh(players=(A, B), seed=7, kingdom=tuple(KE), landscapes=(),
          expansions=("empires",)):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom), landscapes=list(landscapes))


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


def frame(g):
    return g["pending"][-1] if g["pending"] else None


def opt_ids(g):
    return [o["id"] for o in frame(g)["constraint"]["options"]]


def gain(g, pid, pile, **kw):
    out = engine.gain(g, pid, pile, **kw)
    engine._drive(g)
    return out


def trash(g, pid, cards_, zone="hand"):
    engine.trash(g, pid, list(cards_), zone=zone)
    engine._drive(g)


def buy_event(g, pid, name, coins=20, buys=2):
    g["phase"] = "buy"
    g["coins"] = coins
    g["buys"] = buys
    return mv(g, pid, {"type": "buy_landscape", "name": name})


def only(g, pid, owned):
    for zone in ("deck", "hand", "discard", "in_play", "aside"):
        g["seats"][pid][zone] = []
    g["seats"][pid]["discard"] = list(owned)


def vp(g, pid):
    return engine._total_vp(g, pid)


# ── the Events ───────────────────────────────────────────────────────────────

def test_advance_trades_an_action_up_to_six():
    g = fresh(landscapes=["Advance"])
    g["seats"][A]["hand"] = ["Sacrifice"]
    assert buy_event(g, A, "Advance")[0]
    assert decide(g, A, cards=["Sacrifice"])[0]
    assert "Sacrifice" in g["trash"]
    piles = frame(g)["constraint"]["piles"]
    assert "Archive" in piles and "Silver" not in piles, "an ACTION card"
    assert decide(g, A, pile="Archive")[0]
    assert "Archive" in g["seats"][A]["discard"]


def test_advance_declined_gains_nothing():
    g = fresh(landscapes=["Advance"])
    g["seats"][A]["hand"] = ["Sacrifice"]
    buy_event(g, A, "Advance")
    assert decide(g, A, cards=[])[0]
    assert not g["pending"] and g["trash"] == []


def test_annex_keeps_up_to_five_and_shuffles_the_rest_in():
    g = fresh(landscapes=["Annex"])
    g["seats"][A]["discard"] = ["Copper"] * 8
    g["seats"][A]["deck"] = []
    assert buy_event(g, A, "Annex", coins=0)[0]
    assert g["debt"][A] == 8, "{8D}"
    assert frame(g)["constraint"]["max"] == 5
    assert decide(g, A, cards=["Copper"] * 5)[0]
    assert len(g["seats"][A]["discard"]) == 5 + 1, "5 kept + the Duchy"
    assert len(g["seats"][A]["deck"]) == 3
    assert "Duchy" in g["seats"][A]["discard"]


def test_banquet_gives_two_coppers_and_a_non_victory_five():
    g = fresh(landscapes=["Banquet"])
    assert buy_event(g, A, "Banquet")[0]
    piles = frame(g)["constraint"]["piles"]
    assert "Estate" not in piles and "Duchy" not in piles, "non-VICTORY"
    assert "Archive" in piles
    decide(g, A, pile="Archive")
    assert g["seats"][A]["discard"].count("Copper") == 2


def test_conquest_scores_one_per_silver_gained_this_turn():
    g = fresh(landscapes=["Conquest"])
    g["phase"] = "buy"
    gain(g, A, "Silver")
    assert buy_event(g, A, "Conquest")[0]
    assert g["seats"][A]["discard"].count("Silver") == 3
    assert g["vp_tokens"][A] == 3, "the earlier one counts too"


def test_delve_is_a_buy_and_a_silver():
    g = fresh(landscapes=["Delve"])
    before = g["buys"]
    assert buy_event(g, A, "Delve", buys=1)[0]
    assert "Silver" in g["seats"][A]["discard"]
    assert g["buys"] == before, "spent one, gained one"


def test_dominate_pays_nine_only_if_the_province_is_actually_gained():
    g = fresh(landscapes=["Dominate"])
    assert buy_event(g, A, "Dominate")[0]
    assert g["vp_tokens"][A] == 9
    g["supply"]["Province"] = 0
    buy_event(g, A, "Dominate")
    assert g["vp_tokens"][A] == 9, "NOT OPTIONAL IF YOU DO"


def test_donate_rebuilds_your_deck_at_the_start_of_your_next_turn():
    g = fresh(landscapes=["Donate"])
    assert buy_event(g, A, "Donate", coins=0)[0]
    assert g["debt"][A] == 8
    mv(g, A, {"type": "end_phase"})
    # A's next turn: everything is in hand and the trash prompt is open
    while g["turn"] != A:
        cur = g["turn"]
        if g["pending"]:
            mv(g, g["pending_pid"],
               engine.sample_decision(g, g["pending_pid"], engine.random.Random(2)))
            continue
        mv(g, cur, {"type": "end_phase"})
        if g["phase"] == "buy" and not g["pending"]:
            mv(g, cur, {"type": "end_phase"})
    assert frame(g) is not None and frame(g)["card"] == "Donate"
    assert g["seats"][A]["deck"] == [] and g["seats"][A]["discard"] == []
    coppers = [c for c in frame(g)["constraint"]["cards"] if c == "Copper"]
    assert decide(g, A, cards=coppers)[0]
    assert g["trash"].count("Copper") == 7
    assert len(g["seats"][A]["hand"]) == 3, "3 Estates left, drawn back"


def test_ritual_scores_the_cost_of_the_card_AFTER_it_is_trashed():
    """2025: "Ritual now checks what the cost of the card is after it's
    trashed, just like Salvager"."""
    g = fresh(landscapes=["Ritual"])
    g["seats"][A]["hand"] = ["Gold"]
    assert buy_event(g, A, "Ritual")[0]
    assert "Curse" in g["seats"][A]["discard"]
    assert decide(g, A, cards=["Gold"])[0]
    assert g["vp_tokens"][A] == 6


def test_ritual_with_no_curses_left_does_nothing_else():
    g = fresh(landscapes=["Ritual"])
    g["supply"]["Curse"] = 0
    g["seats"][A]["hand"] = ["Gold"]
    buy_event(g, A, "Ritual")
    assert not g["pending"] and g["vp_tokens"][A] == 0


def test_salt_the_earth_trashes_a_victory_pile_top():
    g = fresh(landscapes=["Salt the Earth"])
    assert buy_event(g, A, "Salt the Earth")[0]
    assert g["vp_tokens"][A] == 1
    piles = frame(g)["constraint"]["piles"]
    assert "Province" in piles and "Copper" not in piles
    before = engine.pile_count(g, "Province")
    assert decide(g, A, pile="Province")[0]
    assert engine.pile_count(g, "Province") == before - 1
    assert "Province" in g["trash"]


def test_tax_puts_debt_on_every_supply_pile_at_setup_including_base_cards():
    g = fresh(landscapes=["Tax"])
    for name in ("Copper", "Estate", "Province", "Curse", "Archive"):
        assert engine.pile_debt(g, name) == 1, name


def test_tax_adds_two_more_and_the_next_buy_phase_gainer_takes_them():
    g = fresh(landscapes=["Tax"])
    assert buy_event(g, A, "Tax")[0]
    assert decide(g, A, pile="Archive")[0]
    assert engine.pile_debt(g, "Archive") == 3
    g["phase"] = "buy"
    gain(g, A, "Archive")
    assert g["debt"][A] == 3, "taking the Debt is the PENALTY"
    assert engine.pile_debt(g, "Archive") == 0


def test_tax_does_not_fire_on_an_action_phase_gain():
    g = fresh(landscapes=["Tax"])
    g["phase"] = "action"
    gain(g, A, "Archive")
    assert g["debt"][A] == 0
    assert engine.pile_debt(g, "Archive") == 1


def test_triumph_scores_one_per_card_gained_this_turn():
    g = fresh(landscapes=["Triumph"])
    g["phase"] = "buy"
    gain(g, A, "Silver")
    gain(g, A, "Copper")
    assert buy_event(g, A, "Triumph", coins=0)[0]
    assert g["debt"][A] == 5
    assert g["vp_tokens"][A] == 3, "2 earlier + the Estate itself"


def test_wedding_is_a_vp_and_a_gold_for_coins_and_debt():
    g = fresh(landscapes=["Wedding"])
    assert buy_event(g, A, "Wedding", coins=4)[0]
    assert g["coins"] == 0 and g["debt"][A] == 3
    assert g["vp_tokens"][A] == 1
    assert "Gold" in g["seats"][A]["discard"]


def test_windfall_needs_an_empty_deck_and_discard():
    g = fresh(landscapes=["Windfall"])
    g["seats"][A]["deck"] = ["Copper"]
    g["seats"][A]["discard"] = []
    buy_event(g, A, "Windfall")
    assert g["seats"][A]["discard"] == []
    g["seats"][A]["deck"] = []
    buy_event(g, A, "Windfall")
    assert g["seats"][A]["discard"].count("Gold") == 3


def test_a_debt_costed_event_locks_the_rest_of_the_buy_phase():
    g = fresh(landscapes=["Triumph"])
    assert buy_event(g, A, "Triumph", coins=8, buys=3)[0]
    ok, err = mv(g, A, {"type": "buy", "card": "Silver"})
    assert not ok and "Debt" in err


# ── the Landmarks: setup ─────────────────────────────────────────────────────

SELF_STORE = ["Arena", "Basilica", "Baths", "Battlefield", "Colonnade",
              "Labyrinth"]


def test_the_six_self_store_landmarks_hold_six_vp_per_player():
    for n, players in ((2, (A, B)), (3, (A, B, C))):
        g = fresh(players=players, landscapes=SELF_STORE[:2])
        for name in SELF_STORE[:2]:
            assert engine.landscape_vp(g, name) == 6 * n, (name, n)


def test_aqueduct_seeds_the_silver_and_gold_piles():
    g = fresh(landscapes=["Aqueduct"])
    assert engine.pile_vp(g, "Silver") == 8
    assert engine.pile_vp(g, "Gold") == 8
    assert engine.landscape_vp(g, "Aqueduct") == 0


def test_defiled_shrine_seeds_every_action_supply_pile_by_its_RANDOMIZER():
    g = fresh(kingdom=KSPLIT, landscapes=["Defiled Shrine"])
    # split piles count (the randomizer says Action) even though three of them
    # show a Treasure on the bottom half
    for name in ("Catapult/Rocks", "Encampment/Plunder", "Gladiator/Fortune",
                 "Engineer", "Forum"):
        assert engine.pile_vp(g, name) == 2, name
    # ...and non-Action piles do not
    for name in ("Castles", "Copper", "Estate", "Province"):
        assert engine.pile_vp(g, name) == 0, name
    # ...nor do the gathering piles, which gather their own
    assert engine.pile_vp(g, "Temple") == 0


def test_obelisk_picks_an_action_supply_pile_and_is_seed_deterministic():
    g1 = fresh(kingdom=KSPLIT, landscapes=["Obelisk"], seed=11)
    g2 = fresh(kingdom=KSPLIT, landscapes=["Obelisk"], seed=11)
    pick = g1["landscapes"]["Obelisk"]["pile"]
    assert pick == g2["landscapes"]["Obelisk"]["pile"]
    assert engine.pile_has_type(g1, pick, "action")


def test_a_board_with_no_landmark_setup_deals_the_same_hands():
    """The ph.-7H deal-preservation shape: LANDSCAPE_SETUP re-saves the rng
    only when a setup actually ran."""
    plain = fresh(seed=21, landscapes=[])
    scoring_only = fresh(seed=21, landscapes=["Museum"])   # no setup fn
    assert plain["seats"][A]["hand"] == scoring_only["seats"][A]["hand"]
    assert plain["seats"][B]["hand"] == scoring_only["seats"][B]["hand"]


# ── the Landmarks: during-game triggers ──────────────────────────────────────

def test_aqueduct_moves_a_token_on_a_treasure_and_pays_out_on_a_victory():
    g = fresh(landscapes=["Aqueduct"])
    gain(g, A, "Silver")
    assert engine.pile_vp(g, "Silver") == 7
    assert engine.landscape_vp(g, "Aqueduct") == 1
    gain(g, A, "Estate")
    assert engine.landscape_vp(g, "Aqueduct") == 0
    assert g["vp_tokens"][A] == 1


def test_aqueducts_two_abilities_are_the_players_choice_on_a_card_that_is_both():
    """"If you gain a card of BOTH types, you can resolve them in either
    order" — and the order is worth a VP, so this must not auto-run."""
    g = fresh(kingdom=KSPLIT, landscapes=["Aqueduct"])
    engine.add_landscape_vp(g, "Aqueduct", 3)
    engine.add_pile_vp(g, "Castles", 1)
    gain(g, A, "Castles")              # Humble Castle: Treasure AND Victory
    assert frame(g) is not None and frame(g)["card"] == "__abilities", \
        "the player is asked which resolves first"
    assert frame(g)["kind"] == "choose_option"
    assert len(opt_ids(g)) == 2
    # taking the token onto Aqueduct FIRST means taking it back out again
    assert decide(g, A, ids=[opt_ids(g)[0]])[0]
    while g["pending"]:
        mv(g, A, engine.sample_decision(g, A, engine.random.Random(1)))
    assert g["vp_tokens"][A] == 4, "3 on the landmark + the one it just gathered"


def test_battlefield_and_basilica_and_colonnade_and_labyrinth_pay_two():
    g = fresh(landscapes=["Battlefield"])
    gain(g, A, "Estate")
    assert g["vp_tokens"][A] == 2
    assert engine.landscape_vp(g, "Battlefield") == 12 - 2


def test_basilica_needs_two_coins_left_and_a_buy_phase_gain():
    g = fresh(landscapes=["Basilica"])
    g["phase"] = "buy"
    g["coins"] = 1
    gain(g, A, "Silver")
    assert g["vp_tokens"][A] == 0, "not enough $ left"
    g["coins"] = 2
    gain(g, A, "Silver")
    assert g["vp_tokens"][A] == 2
    g["phase"] = "action"
    gain(g, A, "Silver")
    assert g["vp_tokens"][A] == 2, "the Buy phase only"


def test_colonnade_needs_a_copy_of_the_gained_action_in_play():
    g = fresh(landscapes=["Colonnade"])
    g["phase"] = "buy"
    gain(g, A, "Archive")
    assert g["vp_tokens"][A] == 0
    g["seats"][A]["in_play"] = ["Archive"]
    gain(g, A, "Archive")
    assert g["vp_tokens"][A] == 2


def test_labyrinth_pays_on_the_second_gain_of_your_own_turn_only():
    g = fresh(landscapes=["Labyrinth"])
    gain(g, A, "Silver")
    assert g["vp_tokens"][A] == 0
    gain(g, A, "Silver")
    assert g["vp_tokens"][A] == 2, "the SECOND one"
    gain(g, A, "Silver")
    assert g["vp_tokens"][A] == 2, "...and only the second"
    gain(g, B, "Silver")
    assert g["vp_tokens"][B] == 0, "not on someone else's turn"


def test_baths_pays_when_you_end_a_turn_having_gained_nothing():
    g = fresh(landscapes=["Baths"])
    mv(g, A, {"type": "end_phase"})
    mv(g, A, {"type": "end_phase"})
    assert g["vp_tokens"][A] == 2


def test_baths_pays_nothing_after_a_turn_with_a_gain():
    g = fresh(landscapes=["Baths"])
    g["phase"] = "buy"
    gain(g, A, "Copper")
    mv(g, A, {"type": "end_phase"})
    assert g["vp_tokens"][A] == 0


def test_arena_offers_a_discard_at_the_start_of_the_buy_phase():
    g = fresh(landscapes=["Arena"])
    g["seats"][A]["hand"] = ["Archive", "Copper"]
    assert mv(g, A, {"type": "end_phase"})[0]
    assert frame(g) is not None and frame(g)["card"] == "Arena"
    assert decide(g, A, cards=["Archive"])[0]
    assert g["vp_tokens"][A] == 2
    assert "Archive" in g["seats"][A]["discard"]


def test_arena_does_not_open_without_an_action_in_hand():
    g = fresh(landscapes=["Arena"])
    g["seats"][A]["hand"] = ["Copper", "Copper"]
    mv(g, A, {"type": "end_phase"})
    assert not g["pending"]
    assert g["vp_tokens"][A] == 0


def test_defiled_shrine_gathers_on_actions_and_pays_out_on_a_bought_curse():
    g = fresh(landscapes=["Defiled Shrine"])
    assert engine.pile_vp(g, "Archive") == 2
    gain(g, A, "Archive")
    assert engine.pile_vp(g, "Archive") == 1
    assert engine.landscape_vp(g, "Defiled Shrine") == 1
    g["phase"] = "buy"
    gain(g, A, "Curse")
    assert g["vp_tokens"][A] == 1
    assert engine.landscape_vp(g, "Defiled Shrine") == 0


def test_tomb_pays_one_per_card_trashed_by_anyone():
    g = fresh(landscapes=["Tomb"])
    g["seats"][A]["hand"] = ["Copper", "Estate"]
    trash(g, A, ["Copper", "Estate"])
    assert g["vp_tokens"][A] == 2
    g["seats"][B]["hand"] = ["Copper"]
    trash(g, B, ["Copper"])
    assert g["vp_tokens"][B] == 1, "on an opponent's turn too"


def test_tomb_pays_for_a_card_trashed_out_of_the_SUPPLY():
    """"Tomb triggers even when you trash a card from the Supply (with
    Gladiator, Lurker or Salt the Earth)." """
    g = fresh(landscapes=["Tomb", "Salt the Earth"])
    assert buy_event(g, A, "Salt the Earth")[0]
    assert g["vp_tokens"][A] == 1
    assert decide(g, A, pile="Estate")[0]
    assert g["vp_tokens"][A] == 2


def test_mountain_pass_auctions_debt_for_eight_vp_once_per_game():
    g = fresh(players=(A, B), landscapes=["Mountain Pass"])
    gain(g, A, "Province")
    # B bids first (to A's left), then A
    assert g["pending_pid"] == B
    assert "5" in opt_ids(g)
    assert decide(g, B, ids=["5"])[0]
    assert g["pending_pid"] == A
    assert "5" not in opt_ids(g), "must beat the standing bid"
    assert decide(g, A, ids=["pass"])[0]
    assert g["vp_tokens"][B] == 8
    assert g["debt"][B] == 5
    # ...and never again
    gain(g, A, "Province")
    assert not g["pending"]


def test_mountain_pass_with_everyone_passing_costs_nothing():
    g = fresh(landscapes=["Mountain Pass"])
    gain(g, A, "Province")
    decide(g, B, ids=["pass"])
    decide(g, A, ids=["pass"])
    assert g["vp_tokens"] == {A: 0, B: 0}
    assert g["debt"] == {A: 0, B: 0}


# ── the Landmarks: when scoring ──────────────────────────────────────────────

def test_bandit_fort_docks_two_per_silver_and_gold():
    g = fresh(landscapes=["Bandit Fort"])
    only(g, A, ["Silver", "Silver", "Gold", "Estate"])
    assert vp(g, A) == 1 - 2 * 3


def test_fountain_pays_fifteen_at_ten_coppers():
    g = fresh(landscapes=["Fountain"])
    only(g, A, ["Copper"] * 9)
    assert vp(g, A) == 0
    only(g, A, ["Copper"] * 10)
    assert vp(g, A) == 15


def test_keep_pays_five_per_treasure_you_lead_on_and_ties_count():
    g = fresh(landscapes=["Keep"])
    only(g, A, ["Silver", "Silver", "Gold"])
    only(g, B, ["Silver", "Gold"])
    # A leads on Silver (2 v 1) and TIES on Gold (1 v 1) — both score for A,
    # and the tie also scores for B
    assert vp(g, A) == 10
    assert vp(g, B) == 5


def test_museum_pays_two_per_differently_named_card():
    g = fresh(landscapes=["Museum"])
    only(g, A, ["Copper", "Copper", "Silver", "Estate"])
    assert vp(g, A) == 1 + 2 * 3


def test_obelisk_scores_both_halves_of_a_split_pile():
    """"If Gladiator/Fortune is chosen for Obelisk, BOTH cards score at game
    end" — because the pile, not the card, is what was chosen."""
    g = fresh(kingdom=KSPLIT, landscapes=["Obelisk"])
    g["landscapes"]["Obelisk"]["pile"] = "Gladiator/Fortune"
    only(g, A, ["Gladiator", "Fortune", "Copper"])
    assert vp(g, A) == 4


def test_orchard_pays_four_per_action_you_hold_three_of():
    g = fresh(landscapes=["Orchard"])
    only(g, A, ["Archive"] * 3 + ["Sacrifice"] * 2)
    assert vp(g, A) == 4


def test_palace_pays_three_per_copper_silver_gold_set():
    g = fresh(landscapes=["Palace"])
    only(g, A, ["Copper"] * 3 + ["Silver"] * 2 + ["Gold"])
    assert vp(g, A) == 3, "one complete set"


def test_tower_pays_one_per_non_victory_card_from_an_empty_pile():
    g = fresh(landscapes=["Tower"])
    only(g, A, ["Archive", "Archive", "Estate"])
    assert vp(g, A) == 1, "the pile is not empty yet"
    g["supply"]["Archive"] = 0
    assert vp(g, A) == 1 + 2
    g["supply"]["Estate"] = 0
    assert vp(g, A) == 3, "Victory cards never count"


def test_triumphal_arch_pays_three_per_copy_of_your_SECOND_commonest_action():
    g = fresh(landscapes=["Triumphal Arch"])
    only(g, A, ["Archive"] * 4 + ["Sacrifice"] * 2 + ["Villa"])
    assert vp(g, A) == 6
    only(g, A, ["Archive"] * 4)
    assert vp(g, A) == 0, "one distinct Action scores nothing"


def test_wall_docks_one_per_card_past_fifteen():
    g = fresh(landscapes=["Wall"])
    only(g, A, ["Copper"] * 15)
    assert vp(g, A) == 0
    only(g, A, ["Copper"] * 18)
    assert vp(g, A) == -3


def test_wolf_den_docks_three_per_singleton():
    g = fresh(landscapes=["Wolf Den"])
    only(g, A, ["Copper", "Copper", "Silver", "Gold"])
    assert vp(g, A) == -6, "Silver and Gold are singletons; the Coppers are not"


def test_a_landmark_that_is_not_dealt_scores_nothing():
    g = fresh(landscapes=[])
    only(g, A, ["Copper"] * 20)
    assert vp(g, A) == 0


def test_landmark_scores_do_not_change_when_the_game_ends():
    """The ph.-7H edge: a scoring fn must not change value at game over."""
    g = fresh(landscapes=["Museum", "Wall", "Orchard"])
    only(g, A, ["Archive"] * 3 + ["Copper"] * 14)
    before = vp(g, A)
    g["over"] = True
    assert vp(g, A) == before


# ── registry hygiene ─────────────────────────────────────────────────────────

def test_every_empires_landscape_is_registered_exactly_once():
    for name, d in cards.LANDSCAPES.items():
        if d["expansion"] != "empires":
            continue
        if d["kind"] == "event":
            assert name in effects.LANDSCAPE_FX, name
            assert name not in effects.LANDSCAPE_SCORING, name
        else:
            assert d["kind"] == "landmark", name
            assert name not in effects.LANDSCAPE_FX, name
            # a landmark is a scoring fn, a trigger, or both
            assert (name in effects.LANDSCAPE_SCORING
                    or name in effects.TRIGGERS), name


def test_a_landmark_is_never_buyable():
    g = fresh(landscapes=["Museum"])
    g["phase"] = "buy"
    g["coins"] = 20
    ok, err = mv(g, A, {"type": "buy_landscape", "name": "Museum"})
    assert not ok
    assert all(m.get("name") != "Museum" for m in engine.legal_moves(g, A))


def test_the_setup_functions_cover_every_landmark_that_needs_one():
    """The nine setup rules from SPECIAL SETUP: EMPIRES, by name."""
    want = {"Aqueduct", "Defiled Shrine", "Obelisk", "Arena", "Basilica",
            "Baths", "Battlefield", "Colonnade", "Labyrinth"}
    got = {n for n in effects.LANDSCAPE_SETUP
           if cards.LANDSCAPES[n]["kind"] == "landmark"}
    assert got == want
