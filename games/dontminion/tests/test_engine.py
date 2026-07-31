"""Engine-kernel tests: setup, phases, frames, the attack/reaction window,
redaction, scoring, determinism, and the six exemplar cards.

Tests arrange positions by mutating the game dict directly (the repo's
board-fixture idiom); every mutation keeps the dict shape valid.
"""

import copy
import json
import random

import pytest

from games.dontminion import engine
from games.dontminion.cards import CARDS, pile_size

A, B, C, D = "alice", "bob", "carol", "dave"

# The provisional kingdom used until WP1 lands the full roster; new_game accepts
# an explicit kingdom list of any size (the forced-kingdom test seam).
K7 = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room", "Gardens"]


def fresh(players=(A, B), seed=42, kingdom=tuple(K7), expansions=("base",)):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom))


def give_hand(g, pid, cards):
    """Force a hand to exactly `cards` (conservation not preserved — tests that
    use this don't assert the conservation invariant)."""
    g["seats"][pid]["hand"] = list(cards)


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


# --- setup -------------------------------------------------------------------

def test_setup_deal_and_supply():
    for n, players in ((2, [A, B]), (3, [A, B, C]), (4, [A, B, C, D])):
        g = fresh(players=players)
        assert g["players"] == players and g["turn"] == players[0]
        assert g["phase"] == "action" and g["actions"] == 1 and g["buys"] == 1
        for pid in players:
            s = g["seats"][pid]
            assert len(s["hand"]) == 5 and len(s["deck"]) == 5
            owned = s["deck"] + s["hand"]
            assert owned.count("Copper") == 7 and owned.count("Estate") == 3
        assert g["supply"]["Copper"] == 60 - 7 * n
        assert g["supply"]["Curse"] == 10 * (n - 1)
        assert g["supply"]["Estate"] == (8 if n == 2 else 12)
        assert g["supply"]["Gardens"] == (8 if n == 2 else 12)
        assert g["supply"]["Smithy"] == 10


ALL_SETS = ["base", "intrigue", "seaside", "prosperity", "hinterlands"]


def test_colony_only_ever_appears_with_a_prosperity_kingdom_card():
    """The official randomizer rule: Platinum/Colony join the Supply with
    probability equal to the Prosperity PROPORTION of the dealt 10 — so a
    kingdom with none of the set can never be a Colony game. Both piles or
    neither, always."""
    seen_with, seen_without = 0, 0
    for seed in range(400):
        g = engine.new_game([A, B], ALL_SETS, seed=seed)
        prosperity = sum(1 for c in g["kingdom"] if CARDS[c]["expansion"] == "prosperity")
        assert ("Colony" in g["supply"]) is g["colony"]
        assert ("Platinum" in g["supply"]) is g["colony"]     # never one alone
        if prosperity == 0:
            assert not g["colony"], f"seed {seed}: Colony with no Prosperity card"
            seen_without += 1
        elif g["colony"]:
            seen_with += 1
    assert seen_without and seen_with, "the sample never exercised both branches"
    # and a game that can't deal a Prosperity card never deals the piles at all
    for seed in range(60):
        g = engine.new_game([A, B], ["base", "intrigue"], seed=seed)
        assert not g["colony"] and "Colony" not in g["supply"] and "Platinum" not in g["supply"]


def test_kingdom_requirements_are_honoured():
    from games.dontminion.cards import grants, REQUIREMENT_ORDER
    for exp in ALL_SETS:                    # every set can satisfy all three alone
        for seed in range(12):
            g = engine.new_game([A, B], [exp], seed=seed, requires=list(REQUIREMENT_ORDER))
            assert len(g["kingdom"]) == len(set(g["kingdom"])) == 10
            for req in REQUIREMENT_ORDER:
                assert any(grants(c, req) for c in g["kingdom"]), (exp, seed, req)
    # requesting one leaves the others to chance — the dealer forces the asked-for
    # bonus and nothing else
    forced = [engine.new_game([A, B], ALL_SETS, seed=s, requires=["buys"])["kingdom"]
              for s in range(60)]
    assert all(any(grants(c, "buys") for c in k) for k in forced)
    assert not all(any(grants(c, "draw") for c in k) for k in forced)


def _req_counts(kingdom):
    from games.dontminion.cards import grants, REQUIREMENT_ORDER
    return [sum(1 for c in kingdom if grants(c, r)) for r in REQUIREMENT_ORDER]


def test_requirements_do_not_reserve_a_slot_each():
    """Ticking all three must not FORCE three different qualifying cards. The
    option only deletes the boards that have none of a checked bonus; a board
    where one Worker's Village covers both the village and the +Buy is a
    perfectly good answer and must still turn up at its natural rate."""
    from games.dontminion.cards import grants, REQUIREMENT_ORDER
    pool = sorted({c for e in ALL_SETS for c in engine.KINGDOM[e]})
    rng = random.Random(11)
    double_duty = 0
    for _ in range(400):
        kingdom = engine.deal_kingdom(pool, list(REQUIREMENT_ORDER), rng)
        assert all(n >= 1 for n in _req_counts(kingdom))         # the promise
        if any(sum(grants(c, r) for r in REQUIREMENT_ORDER) >= 2 for c in kingdom):
            double_duty += 1
    # a constructive dealer can still produce these by luck in the random fill,
    # but never at this rate — it spends a dedicated slot per requirement
    assert double_duty > 200, f"only {double_duty}/400 boards had a card doing double duty"


def test_requirements_preserve_the_natural_distribution():
    """The dealer is rejection sampling, so its output IS the ordinary kingdom
    distribution conditioned on the requirements — not merely 'satisfies them'.
    Compared against that conditional distribution computed independently.
    Deterministic (fixed seeds), so this passes always or fails always."""
    from games.dontminion.cards import REQUIREMENT_ORDER
    pool = sorted({c for e in ALL_SETS for c in engine.KINGDOM[e]})
    reqs = list(REQUIREMENT_ORDER)

    rng = random.Random(21)                      # independent reference: plain
    natural, tries = [], 0                       # deals, keeping the ones that pass
    while len(natural) < 1500:
        k = rng.sample(pool, 10)
        tries += 1
        counts = _req_counts(k)
        if all(n >= 1 for n in counts):
            natural.append(counts)
    assert tries < 6000, "accept rate collapsed — rejection sampling would be slow"

    rng = random.Random(22)
    dealt = [_req_counts(engine.deal_kingdom(pool, reqs, rng)) for _ in range(1500)]

    for i, req in enumerate(reqs):
        want = sum(c[i] for c in natural) / len(natural)
        got = sum(c[i] for c in dealt) / len(dealt)
        assert abs(got - want) < 0.15, f"{req}: dealer mean {got:.2f} vs natural {want:.2f}"


def test_no_requirements_deals_exactly_the_unconstrained_kingdom():
    """The requirement dealer must not perturb the rng call sequence when
    nothing is asked for, or every existing seed deals a different board."""
    for seed in range(20):
        plain = engine.new_game([A, B], ALL_SETS, seed=seed)["kingdom"]
        for empty in (None, [], ()):
            same = engine.new_game([A, B], ALL_SETS, seed=seed, requires=empty)
            assert same["kingdom"] == plain, (seed, empty)


def test_setup_validation():
    with pytest.raises(ValueError):
        engine.new_game([A, B], ["base"], requires=["cantrips"])   # unknown requirement
    with pytest.raises(ValueError):
        engine.new_game([A], ["base"], kingdom=K7)
    with pytest.raises(ValueError):
        engine.new_game([A, B, C, D, "eve"], ["base"], kingdom=K7)
    with pytest.raises(ValueError):
        engine.new_game([A, B], [], kingdom=K7)
    with pytest.raises(ValueError):
        engine.new_game([A, B], ["nocturne"], kingdom=K7)      # not ported yet
    with pytest.raises(ValueError):
        engine.new_game([A, B], ["base"], kingdom=["Nonsense"])


def test_seeded_determinism():
    g1, g2 = fresh(seed=7), fresh(seed=7)
    assert json.dumps(g1, sort_keys=True) == json.dumps(g2, sort_keys=True)
    for g in (g1, g2):
        assert mv(g, A, {"type": "end_phase"}) == (True, None)
        assert mv(g, A, {"type": "play_all_treasures"}) == (True, None)
        assert mv(g, A, {"type": "end_phase"}) == (True, None)
    assert json.dumps(g1, sort_keys=True) == json.dumps(g2, sort_keys=True)


# --- draw / shuffle ----------------------------------------------------------

def test_draw_shuffles_only_when_needed():
    g = fresh()
    s = g["seats"][A]
    s["deck"] = ["Copper"]
    s["discard"] = ["Estate", "Estate", "Silver"]
    s["hand"] = []
    got = engine.draw(g, A, 2)
    assert got[0] == "Copper"           # remaining deck cards come first
    assert len(got) == 2 and len(s["deck"]) == 2 and s["discard"] == []


def test_draw_partial_when_short():
    g = fresh()
    s = g["seats"][A]
    s["deck"], s["discard"], s["hand"] = ["Copper"], [], []
    assert engine.draw(g, A, 5) == ["Copper"]
    assert s["hand"] == ["Copper"] and s["deck"] == []


def test_look_top_excludes_aside_from_shuffle():
    g = fresh()
    s = g["seats"][A]
    s["deck"], s["discard"] = ["Gold"], ["Estate", "Estate"]
    moved = engine.look_top(g, A, 3)
    assert moved[0] == "Gold" and len(moved) == 3
    assert s["aside"] == moved and s["discard"] == [] and s["deck"] == []


# --- zone helpers ------------------------------------------------------------

def test_gain_destinations_and_empty_pile():
    g = fresh()
    assert engine.gain(g, A, "Silver")
    assert g["seats"][A]["discard"][-1] == "Silver"
    assert engine.gain(g, A, "Silver", dest="hand")
    assert g["seats"][A]["hand"][-1] == "Silver"
    assert engine.gain(g, A, "Silver", dest="deck")
    assert g["seats"][A]["deck"][0] == "Silver"
    g["supply"]["Witch"] = 0
    assert engine.gain(g, A, "Witch") is False


def test_trash_and_gain_from_trash():
    g = fresh()
    give_hand(g, A, ["Copper", "Estate"])
    engine.trash(g, A, ["Copper"])
    assert g["trash"] == ["Copper"]
    assert engine.gain_from_trash(g, A, "Copper")
    assert g["trash"] == [] and g["seats"][A]["discard"][-1] == "Copper"
    assert engine.gain_from_trash(g, A, "Gold") is False
    assert engine.trash_from_supply(g, "Moat")
    assert g["trash"] == ["Moat"] and g["supply"]["Moat"] == 9


def test_opponents_order_and_empty_piles():
    g = fresh(players=[A, B, C])
    assert engine.opponents(g, B) == [C, A]
    assert engine.count_empty_piles(g) == 0
    g["supply"]["Moat"] = 0
    g["supply"]["Curse"] = 0
    assert engine.count_empty_piles(g) == 2


def test_cost_with_bridges():
    g = fresh()
    assert engine.cost(g, "Smithy") == 4
    g["turn_ctx"]["bridges"] = 3
    assert engine.cost(g, "Smithy") == 1
    assert engine.cost(g, "Copper") == 0     # never negative
    g["turn_ctx"]["bridges"] = 9
    assert engine.cost(g, "Province") == 0


# --- move gate + phases ------------------------------------------------------

def test_gate_rejections():
    g = fresh()
    assert mv(g, B, {"type": "end_phase"}) == (False, "not your turn")
    ok, err = mv(g, A, {"type": "nonsense"})
    assert not ok and "unknown move" in err
    ok, err = decide(g, A, cards=[])
    assert not ok and err == "nothing to decide"
    give_hand(g, A, ["Copper"])
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Copper"})
    assert not ok and "buy phase" in err
    give_hand(g, A, ["Smithy"])
    mv(g, A, {"type": "end_phase"})
    ok, err = mv(g, A, {"type": "play_action", "card": "Smithy"})
    assert not ok and "action phase" in err


def test_action_phase_gates():
    g = fresh()
    give_hand(g, A, ["Smithy", "Copper"])
    ok, err = mv(g, A, {"type": "play_action", "card": "Copper"})
    assert not ok and err == "not an action card"
    ok, err = mv(g, A, {"type": "play_action", "card": "Witch"})
    assert not ok and err == "card not in hand"
    assert mv(g, A, {"type": "play_action", "card": "Smithy"})[0]
    assert g["phase"] == "buy"          # last Action spent -> auto-advanced
    # the no-actions gate still guards direct submissions (fixture-forced state)
    g["phase"] = "action"
    g["actions"] = 0
    give_hand(g, A, ["Smithy"] + g["seats"][A]["hand"])
    ok, err = mv(g, A, {"type": "play_action", "card": "Smithy"})
    assert not ok and err == "no actions left"


def test_buy_math_and_bought_gate():
    g = fresh()
    give_hand(g, A, ["Gold", "Silver", "Copper"])
    mv(g, A, {"type": "end_phase"})
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert g["coins"] == 6 and g["seats"][A]["in_play"] == ["Gold", "Silver", "Copper"]
    ok, err = mv(g, A, {"type": "buy", "card": "Province"})
    assert not ok and err == "can't afford it"
    assert mv(g, A, {"type": "buy", "card": "Gold"})[0]
    assert g["coins"] == 0 and g["buys"] == 0 and g["supply"]["Gold"] == 29
    assert g["seats"][A]["discard"][-1] == "Gold"
    ok, err = mv(g, A, {"type": "buy", "card": "Copper"})
    assert not ok and err == "no buys left"
    give_hand(g, A, ["Copper"])
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Copper"})
    assert not ok and err == "can't play treasures after buying"


def test_buy_empty_pile_and_unknown_pile():
    g = fresh()
    mv(g, A, {"type": "end_phase"})
    g["supply"]["Moat"] = 0
    g["coins"] = 10
    assert mv(g, A, {"type": "buy", "card": "Moat"}) == (False, "pile is empty")
    assert mv(g, A, {"type": "buy", "card": "Bandit"}) == (False, "no such pile")


def test_merchant_silver_hook():
    g = fresh()
    give_hand(g, A, ["Silver", "Silver"])
    mv(g, A, {"type": "end_phase"})
    g["turn_ctx"]["merchants"] = 2      # as if two Merchants were played
    assert mv(g, A, {"type": "play_treasure", "card": "Silver"})[0]
    assert g["coins"] == 4              # 2 + the one-time 2-Merchant bonus
    assert mv(g, A, {"type": "play_treasure", "card": "Silver"})[0]
    assert g["coins"] == 6              # second Silver: no bonus


def test_cleanup_and_turn_advance():
    g = fresh()
    give_hand(g, A, ["Smithy"])
    assert mv(g, A, {"type": "play_action", "card": "Smithy"})[0]
    assert g["phase"] == "buy"      # no actions left -> auto-advanced
    # big enough deck that the cleanup draw needs no reshuffle (Smithy must
    # still be sitting in the discard afterwards)
    g["seats"][A]["deck"] = ["Copper"] * 6 + g["seats"][A]["deck"]
    g["turn_ctx"]["bridges"] = 2
    g["coins"] = 5
    assert mv(g, A, {"type": "end_phase"})[0]
    sa = g["seats"][A]
    assert sa["in_play"] == [] and len(sa["hand"]) == 5
    assert "Smithy" in sa["discard"]
    # B's dealt hand decides B's starting phase now (no Action cards -> buy)
    b_has_action = any("action" in CARDS[c]["types"] for c in g["seats"][B]["hand"])
    assert g["turn"] == B and g["phase"] == ("action" if b_has_action else "buy")
    assert g["actions"] == 1 and g["buys"] == 1 and g["coins"] == 0
    assert g["turn_ctx"]["bridges"] == 0
    assert g["seats"][A]["turns_taken"] == 1 and g["seats"][B]["turns_taken"] == 0


# --- game end + scoring ------------------------------------------------------

def _finish_turn(g, pid):
    if g["phase"] == "action":
        assert mv(g, pid, {"type": "end_phase"})[0]
    assert mv(g, pid, {"type": "end_phase"})[0]


def test_game_ends_on_provinces_at_end_of_turn():
    g = fresh()
    g["supply"]["Province"] = 0
    assert not g["over"]                 # mid-turn emptiness does not end it
    _finish_turn(g, A)
    assert g["over"] and g["scores"] and g["winners"]
    assert mv(g, B, {"type": "end_phase"}) == (False, "game is over")


def test_game_ends_on_three_empty_piles():
    g = fresh()
    g["supply"]["Moat"] = 0
    g["supply"]["Curse"] = 0
    _finish_turn(g, A)
    assert not g["over"]                 # two piles is not enough
    g["supply"]["Copper"] = 0
    _finish_turn(g, B)
    assert g["over"]


def test_scoring_gardens_and_tiebreaks():
    g = fresh()
    sa, sb = g["seats"][A], g["seats"][B]
    sa["deck"], sa["hand"], sa["discard"], sa["in_play"] = (
        ["Estate"] * 3 + ["Copper"] * 7, [], ["Gardens"] * 2 + ["Copper"] * 8, [])
    sb["deck"], sb["hand"], sb["discard"], sb["in_play"] = (
        ["Duchy", "Curse"], [], [], [])
    # A: 3 Estates + 2 Gardens x floor(20/10) = 3 + 4 = 7; B: 3 - 1 = 2
    s = engine.score_game(g)
    assert s[A]["vp"] == 7 and s[B]["vp"] == 2
    engine._finish_game(g)
    assert g["winners"] == [A]
    # vp tie -> fewest turns; full tie -> shared victory
    g2 = fresh()
    for pid in (A, B):
        st = g2["seats"][pid]
        st["deck"], st["hand"], st["discard"], st["in_play"] = ["Province"], [], [], []
    g2["seats"][A]["turns_taken"] = 5
    g2["seats"][B]["turns_taken"] = 4
    engine._finish_game(g2)
    assert g2["winners"] == [B]
    g2["over"] = False
    g2["seats"][A]["turns_taken"] = 4
    engine._finish_game(g2)
    assert g2["winners"] == [A, B]


def test_vp_map_tracks_every_move():
    g = fresh()
    assert g["vp"] == {A: 3, B: 3}
    mv(g, A, {"type": "end_phase"})
    g["coins"] = 8
    assert mv(g, A, {"type": "buy", "card": "Province"})[0]
    assert g["vp"][A] == 9


# --- decision validation -----------------------------------------------------

def test_choose_cards_validation():
    g = fresh()
    give_hand(g, A, ["Smithy", "Militia"])
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    # 2p, B has 5 cards, no reactions -> straight to B's discard-2 frame
    assert g["pending_kind"] == "choose_cards" and g["pending_pid"] == B
    ok, err = mv(g, A, {"type": "end_phase"})
    assert not ok and err == "not your decision"
    ok, err = mv(g, B, {"type": "end_phase"})
    assert not ok and "must resolve choose_cards" in err
    ok, err = decide(g, B, cards=["Gold", "Gold"])
    assert not ok and err == "cards not available"
    ok, err = decide(g, B, cards=g["seats"][B]["hand"][:1])
    assert not ok and "between 2 and 2" in err
    hand2 = g["seats"][B]["hand"][:2]
    assert decide(g, B, cards=hand2)[0]
    assert len(g["seats"][B]["hand"]) == 3 and g["pending_pid"] is None


def test_choose_option_validation():
    g = fresh()
    engine.push_choose_option(g, A, "Militia", "discard",
                              options=[{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}],
                              pick=1)
    ok, err = decide(g, A, ids=["x", "y"])
    assert not ok and "exactly 1" in err
    ok, err = decide(g, A, ids=["z"])
    assert not ok and err == "unknown option"


def test_order_place_name_pile_validation():
    g = fresh()
    engine.push_order_cards(g, A, "Smithy", "discard", cards=["Copper", "Estate"])
    ok, err = decide(g, A, order=["Copper", "Copper"])
    assert not ok
    g["pending"].clear(); engine._sync_pending(g)
    engine.push_place_in_deck(g, A, "Smithy", "discard", deck_card="Copper")
    n = len(g["seats"][A]["deck"])
    ok, err = decide(g, A, position=n + 1)
    assert not ok and f"0..{n}" in err
    g["pending"].clear(); engine._sync_pending(g)
    engine.push_name_card(g, A, "Smithy", "discard")
    ok, err = decide(g, A, card="Bandit")
    assert not ok
    g["pending"].clear(); engine._sync_pending(g)
    engine.push_choose_pile(g, A, "Smithy", "discard", piles=["Moat"])
    ok, err = decide(g, A, pile="Witch")
    assert not ok and err == "not an eligible pile"
    with pytest.raises(ValueError):
        engine.push_choose_pile(g, A, "Smithy", "discard", piles=[])


def test_legal_moves_and_sampling():
    g = fresh()
    give_hand(g, A, ["Smithy", "Copper", "Silver"])
    moves = engine.legal_moves(g, A)
    assert {"type": "play_action", "card": "Smithy"} in moves
    assert {"type": "end_phase"} in moves
    assert engine.legal_moves(g, B) == []
    mv(g, A, {"type": "end_phase"})
    moves = engine.legal_moves(g, A)
    assert {"type": "play_treasure", "card": "Copper"} in moves
    assert {"type": "play_all_treasures"} in moves
    assert {"type": "buy", "card": "Copper"} in moves       # cost 0 is buyable
    assert all(m != {"type": "buy", "card": "Gold"} for m in moves)
    engine.push_choose_cards(g, A, "Militia", "discard",
                             cards=["Copper", "Estate"], mn=0, mx=2, purpose="discard")
    dec = engine.legal_moves(g, A)
    assert {"type": "decision", "cards": []} in dec
    assert {"type": "decision", "cards": ["Copper", "Estate"]} in dec
    assert engine.legal_moves(g, B) == []
    rng = random.Random(0)
    for _ in range(20):
        payload = engine.sample_decision(g, A, rng)
        assert engine._validate_choice(g["pending"][-1], {"type": "decision", **payload})[0]


# --- exemplar cards ----------------------------------------------------------

def test_smithy_village_moat_play():
    g = fresh()
    give_hand(g, A, ["Village", "Smithy", "Moat"])
    g["seats"][A]["deck"] = ["Copper"] * 8    # enough for all the draws
    assert mv(g, A, {"type": "play_action", "card": "Village"})[0]
    assert g["actions"] == 2 and len(g["seats"][A]["hand"]) == 3
    assert mv(g, A, {"type": "play_action", "card": "Smithy"})[0]
    assert g["actions"] == 1 and len(g["seats"][A]["hand"]) == 5
    assert mv(g, A, {"type": "play_action", "card": "Moat"})[0]
    assert g["actions"] == 0 and len(g["seats"][A]["hand"]) == 6
    assert g["turn_ctx"]["actions_played"] == 3


def test_militia_attack_no_reactions():
    g = fresh(players=[A, B, C])
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Copper"] * 5)
    give_hand(g, C, ["Copper"] * 3)
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    assert g["coins"] == 2                       # no windows -> resolved through
    assert g["pending_pid"] == B                 # B first in turn order
    assert g["pending"][-1]["constraint"]["min"] == 2
    assert decide(g, B, cards=["Copper", "Copper"])[0]
    assert len(g["seats"][B]["hand"]) == 3
    assert g["pending_pid"] is None              # C had <=3 cards: no frame
    assert len(g["seats"][C]["hand"]) == 3


def test_reaction_window_precedes_play_ability():
    g = fresh(players=[A, B, C])
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Copper"] * 5)
    give_hand(g, C, ["Moat"] + ["Copper"] * 4)
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    # C holds Moat -> C's window opens BEFORE the attacker's own +$2
    assert g["coins"] == 0 and g["pending_pid"] == C
    ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
    assert ids == ["react:Moat", "decline"]
    assert decide(g, C, ids=["react:Moat"])[0]
    assert g["coins"] == 2                       # ability resolved after windows
    assert g["pending_pid"] == B                 # B still discards
    assert decide(g, B, cards=g["seats"][B]["hand"][:2])[0]
    assert len(g["seats"][C]["hand"]) == 5       # Moat holder untouched
    assert g["pending_pid"] is None


def test_witch_curses_in_turn_order_and_depletion():
    g = fresh(players=[A, B, C])
    g["supply"]["Curse"] = 1
    give_hand(g, A, ["Witch"])
    give_hand(g, B, ["Copper"])
    give_hand(g, C, ["Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Witch"})[0]
    assert g["pending_pid"] is None
    assert g["seats"][B]["discard"] == ["Curse"]     # first in turn order got it
    assert "Curse" not in g["seats"][C]["discard"]   # pile ran dry
    assert g["supply"]["Curse"] == 0


def test_all_opponents_immune_attacker_still_benefits():
    g = fresh()
    give_hand(g, A, ["Witch"])
    give_hand(g, B, ["Moat"] + ["Copper"] * 4)
    hand_before = len(g["seats"][A]["hand"]) - 1     # Witch leaves the hand
    assert mv(g, A, {"type": "play_action", "card": "Witch"})[0]
    assert decide(g, B, ids=["react:Moat"])[0]
    assert len(g["seats"][A]["hand"]) == hand_before + 2   # attacker still draws
    assert g["seats"][B]["discard"] == []


def test_diplomat_reaction_chain():
    g = fresh()
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Diplomat"] + ["Copper"] * 4)
    g["seats"][B]["deck"] = ["Silver", "Gold"] + g["seats"][B]["deck"]
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
    assert ids == ["react:Diplomat", "decline"]
    assert decide(g, B, ids=["react:Diplomat"])[0]
    assert len(g["seats"][B]["hand"]) == 7           # drew Silver + Gold
    assert g["pending_kind"] == "choose_cards"
    assert decide(g, B, cards=["Copper", "Copper", "Copper"])[0]
    # hand now 4 (<5): no re-offer; Militia's discard-to-3 still hits
    assert g["pending_kind"] == "choose_cards" and g["pending_pid"] == B
    assert g["pending"][-1]["card"] == "Militia"
    assert decide(g, B, cards=["Copper"])[0]
    assert len(g["seats"][B]["hand"]) == 3
    assert g["coins"] == 2


def test_throne_room_doubles_and_double_attack():
    g = fresh()
    give_hand(g, A, ["Throne Room", "Smithy"])
    g["seats"][A]["deck"] = ["Copper"] * 6 + g["seats"][A]["deck"]
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert g["pending_kind"] == "choose_cards"
    assert decide(g, A, cards=["Smithy"])[0]
    assert len(g["seats"][A]["hand"]) == 6           # +3 twice
    assert g["turn_ctx"]["actions_played"] == 3      # TR + two Smithy plays
    assert g["actions"] == 0                         # only TR consumed an action

    g = fresh()
    give_hand(g, A, ["Throne Room", "Militia"])
    give_hand(g, B, ["Moat"] + ["Copper"] * 5)
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert decide(g, A, cards=["Militia"])[0]
    # first play: B's window
    assert g["pending_pid"] == B
    assert decide(g, B, ids=["react:Moat"])[0]
    # second play: a NEW attack -> fresh window, Moat offerable again
    assert g["pending_pid"] == B
    ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
    assert "react:Moat" in ids
    assert decide(g, B, ids=["decline"])[0]
    assert g["pending_pid"] == B and g["pending"][-1]["card"] == "Militia"
    assert decide(g, B, cards=g["seats"][B]["hand"][:3])[0]
    assert g["coins"] == 4                           # +$2 twice
    assert len(g["seats"][B]["hand"]) == 3


def test_throne_room_with_no_actions_or_skip():
    g = fresh()
    give_hand(g, A, ["Throne Room", "Copper"])
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert g["pending_pid"] is None                  # no actions in hand: no frame
    g = fresh()
    give_hand(g, A, ["Throne Room", "Smithy"])
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert decide(g, A, cards=[])[0]                 # "may" — declined
    assert g["pending_pid"] is None
    assert "Smithy" in g["seats"][A]["hand"]


# --- turn undo (reveal-gated — the Duel model) --------------------------------
# give_hand changes the state AFTER new_game armed the snapshot, so these tests
# re-arm with engine._arm_undo once the position is staged.

def test_undo_steps_back_one_move_at_a_time():
    g = fresh()
    give_hand(g, A, ["Gold", "Copper"])
    engine._arm_undo(g)
    mv(g, A, {"type": "end_phase"})
    mv(g, A, {"type": "play_all_treasures"})
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert g["supply"]["Silver"] == 39 and g["coins"] == 1
    # 1st undo: just the buy comes back
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["supply"]["Silver"] == 40 and g["coins"] == 4
    assert g["phase"] == "buy" and sorted(g["seats"][A]["in_play"]) == ["Copper", "Gold"]
    assert g["log"][-1]["event"] == "undo"
    # 2nd undo: the treasures return to hand
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["coins"] == 0 and sorted(g["seats"][A]["hand"]) == ["Copper", "Gold"]
    assert g["phase"] == "buy" and g["seats"][A]["in_play"] == []
    # 3rd undo: back to the action phase — the start of the turn
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["phase"] == "action"
    ok, err = mv(g, A, {"type": "undo_turn"})
    assert not ok and err == "nothing to undo"
    assert mv(g, A, {"type": "end_phase"})[0]       # play continues after undos


def test_undo_depth_ships_and_rejected_moves_dont_count():
    g = fresh()
    give_hand(g, A, ["Gold"])
    engine._arm_undo(g)
    mv(g, A, {"type": "end_phase"})
    mv(g, A, {"type": "play_all_treasures"})
    v = engine.player_view(g, A)
    assert v["undo_depth"] == 2 and "undo_stack" not in v
    ok, _ = mv(g, A, {"type": "buy", "card": "Province"})   # can't afford: rejected
    assert not ok
    assert engine.player_view(g, A)["undo_depth"] == 2      # no phantom snapshot


def test_undo_ok_for_no_reveal_actions_blocked_after_draw():
    g = fresh()
    give_hand(g, A, ["Festival"])
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_action", "card": "Festival"})[0]
    assert g["coins"] == 2
    assert mv(g, A, {"type": "undo_turn"})[0]        # +actions/+buys/+$: no reveal
    assert "Festival" in g["seats"][A]["hand"] and g["coins"] == 0
    give_hand(g, A, ["Smithy"])
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_action", "card": "Smithy"})[0]
    ok, err = mv(g, A, {"type": "undo_turn"})        # a draw can't be un-seen
    assert not ok and err == "nothing to undo"
    assert engine.player_view(g, A)["undo_depth"] == 0   # the reveal clears the stack
    # ...but the reveal only bars rewinding PAST it: later moves in the same
    # turn are undoable again (a sticky flag used to kill the whole turn)
    assert g["phase"] == "buy"                      # Smithy emptied the hand
    g["coins"] = 5
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert engine.player_view(g, A)["undo_depth"] == 1
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["coins"] == 5 and "Silver" not in g["seats"][A]["discard"]


def test_undo_before_opponent_answers_but_not_after():
    g = fresh()
    give_hand(g, A, ["Militia", "Militia"])
    give_hand(g, B, ["Copper"] * 5)
    g["actions"] = 2
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    assert g["pending_pid"] == B
    assert mv(g, A, {"type": "undo_turn"})[0]        # B revealed nothing yet
    assert g["pending_pid"] is None
    assert g["seats"][A]["hand"].count("Militia") == 2
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    assert decide(g, B, cards=g["seats"][B]["hand"][:2])[0]
    ok, err = mv(g, A, {"type": "undo_turn"})        # B's choice = new information
    assert not ok and err == "nothing to undo"
    # A's OWN later moves stay undoable (only the rewind PAST B's answer is barred)
    assert mv(g, A, {"type": "end_phase"})[0]
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["phase"] == "action"


def test_undo_with_own_pending_open_and_after_self_reveal():
    g = fresh()
    give_hand(g, A, ["Workshop"])
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_action", "card": "Workshop"})[0]
    assert g["pending_kind"] == "choose_pile"
    assert mv(g, A, {"type": "undo_turn"})[0]        # own unrevealed pending: fine
    assert g["pending_pid"] is None and "Workshop" in g["seats"][A]["hand"]
    give_hand(g, A, ["Shanty Town", "Moat"])
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_action", "card": "Shanty Town"})[0]
    ok, err = mv(g, A, {"type": "undo_turn"})        # revealed OWN hand to others
    assert not ok and err == "nothing to undo"


def test_undo_walks_back_through_own_decisions():
    """A decision by the turn player (Throne Room's pick) is its own undo step."""
    g = fresh()
    give_hand(g, A, ["Throne Room", "Militia"])
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_action", "card": "Throne Room"})[0]
    assert g["pending_kind"] == "choose_cards"
    assert decide(g, A, cards=[])[0]                 # declined the pick
    assert engine.player_view(g, A)["undo_depth"] == 2
    assert mv(g, A, {"type": "undo_turn"})[0]        # back to the open pick
    assert g["pending_kind"] == "choose_cards" and g["pending_pid"] == A
    assert mv(g, A, {"type": "undo_turn"})[0]        # back before Throne Room
    assert g["pending_pid"] is None
    assert "Throne Room" in g["seats"][A]["hand"] and g["actions"] == 1


def test_undo_gates_and_wire_shape():
    g = fresh()
    assert mv(g, B, {"type": "undo_turn"}) == (False, "not your turn")
    assert all(m["type"] != "undo_turn" for m in engine.legal_moves(g, A))
    v = engine.player_view(g, A)
    assert "undo_stack" not in v and "turn_undo" not in v
    assert v["turn_revealed"] is False and v["undo_depth"] == 0


# --- redaction ---------------------------------------------------------------

def test_player_view_redaction():
    g = fresh(players=[A, B, C])
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Copper"] * 5)
    give_hand(g, C, ["Copper"] * 2)
    mv(g, A, {"type": "play_action", "card": "Militia"})
    assert g["pending_pid"] == B
    va, vb = engine.player_view(g, A), engine.player_view(g, B)
    for view, viewer in ((va, A), (vb, B)):
        assert "rng_state" not in view and "seed" not in view
        assert "pending" not in view
        for p, seat in view["seats"].items():
            assert "deck" not in seat and "discard" not in seat and "aside" not in seat
            assert seat["deck_count"] >= 0 and "discard_view" in seat
            if p != viewer:
                assert "hand" not in seat
            else:
                assert isinstance(seat["hand"], list)
    assert vb["pending_view"]["kind"] == "choose_cards"
    assert vb["pending_view"]["constraint"]["min"] == 2
    assert va["pending_view"] == {"card": "Militia", "waiting_on": B}
    assert engine.player_view(g, None)["pending_view"]["waiting_on"] == B


def test_player_view_private_log_and_game_over_reveal():
    g = fresh()
    engine._log(g, A, "masq_pass", private_to=[A, B], card="Gold")
    engine._log(g, A, "masq_pass", private_to=[A], card="Silver")
    vb = engine.player_view(g, B)
    passed = [e for e in vb["log"] if e["event"] == "masq_pass"]
    assert len(passed) == 1 and passed[0]["card"] == "Gold"
    g["over"] = True
    vb = engine.player_view(g, B)
    for seat in vb["seats"].values():
        assert "hand" in seat and "deck" in seat and "discard" in seat


def test_wire_view_is_json_safe():
    g = fresh(players=[A, B, C])
    give_hand(g, A, ["Witch"])
    mv(g, A, {"type": "play_action", "card": "Witch"})
    for viewer in (A, B, C, None):
        json.dumps(engine.player_view(g, viewer))


# --- verbose log (round-3 UI: effect lines, depth, draw-name privacy) ----------

def test_log_plus_events_and_depth_under_a_play():
    g = fresh(kingdom=K7 + ["Festival"])
    # the second action card keeps the phase from auto-advancing after the play
    give_hand(g, A, ["Festival", "Smithy"])
    n0 = len(g["log"])
    ok, err = mv(g, A, {"type": "play_action", "card": "Festival"})
    assert ok, err
    new = g["log"][n0:]
    assert [e["event"] for e in new] == ["play", "plus", "plus", "plus"]
    assert "d" not in new[0]                      # the play itself is top-level
    for e in new[1:]:
        assert e["d"] == 1                        # its effects indent under it
    assert {"actions": 2} .items() <= new[1].items()
    assert {"buys": 1} .items() <= new[2].items()
    assert {"coins": 2} .items() <= new[3].items()
    assert g["log_depth"] == 0                    # always zero at rest


def test_log_treasure_play_carries_coins_and_merchant_bonus():
    g = fresh(kingdom=K7 + ["Merchant"])
    g["phase"] = "buy"
    g["turn_ctx"]["merchants"] = 1
    give_hand(g, A, ["Silver"])
    ok, _ = mv(g, A, {"type": "play_treasure", "card": "Silver"})
    assert ok
    play = [e for e in g["log"] if e["event"] == "play" and e.get("card") == "Silver"][-1]
    assert play["coins"] == 2
    bonus = [e for e in g["log"] if e["event"] == "plus" and e.get("why") == "Merchant"]
    assert len(bonus) == 1 and bonus[0]["coins"] == 1
    assert g["coins"] == 3


def test_log_draw_names_are_owner_only_until_over():
    g = fresh()
    engine.draw(g, A, 2)
    e = [x for x in g["log"] if x["event"] == "draw"][-1]
    assert e["pid"] == A and len(e["cards"]) == e["count"] == 2
    assert e["n"] == len(g["log"]) - 1          # the SEQUENCE n — never the count
    va = engine.player_view(g, A)
    vb = engine.player_view(g, B)
    ea = [x for x in va["log"] if x["event"] == "draw" and x["pid"] == A][-1]
    eb = [x for x in vb["log"] if x["event"] == "draw" and x["pid"] == A][-1]
    assert ea["cards"] == e["cards"]
    assert "cards" not in eb and eb["count"] == 2  # count public, names private
    g["over"] = True
    eb = [x for x in engine.player_view(g, B)["log"]
          if x["event"] == "draw" and x["pid"] == A][-1]
    assert eb["cards"] == e["cards"]              # everything reveals at over


def test_log_discards_are_named_and_opponent_effects_indent():
    g = fresh(players=[A, B])
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Copper", "Copper", "Estate", "Estate", "Gold"])
    ok, _ = mv(g, A, {"type": "play_action", "card": "Militia"})
    assert ok
    ok, err = decide(g, B, cards=["Estate", "Estate"])
    assert ok, err
    disc = [e for e in g["log"] if e["event"] == "discard" and e["pid"] == B][-1]
    assert disc["cards"] == ["Estate", "Estate"] and disc["count"] == 2
    assert disc.get("d", 0) >= 1                  # indents under the Militia


def test_log_sequence_n_is_unique_and_ordered():
    # regression: the draw/discard count kwarg used to CLOBBER the sequence n
    g = fresh()
    give_hand(g, A, ["Smithy", "Copper", "Copper"])
    mv(g, A, {"type": "play_action", "card": "Smithy"})
    mv(g, A, {"type": "end_phase"})
    mv(g, A, {"type": "play_all_treasures"})
    mv(g, A, {"type": "end_phase"})           # cleanup draws + next turn
    ns = [e["n"] for e in g["log"]]
    assert ns == list(range(len(ns)))


# --- auto-advance to the buy phase --------------------------------------------

def test_auto_advance_to_buy_and_undo_restores_action_phase():
    g = fresh(kingdom=K7 + ["Festival"])
    give_hand(g, A, ["Festival"])
    assert mv(g, A, {"type": "play_action", "card": "Festival"})[0]
    # actions remain (+2) but no Action card is left in hand -> advanced
    assert g["phase"] == "buy" and g["actions"] == 2
    # the skip folded into the play's snapshot: one undo restores the pre-play
    # ACTION phase, not a dangling phase change
    ok, err = mv(g, A, {"type": "undo_turn"})
    assert ok, err
    assert g["phase"] == "action" and g["actions"] == 1
    assert "Festival" in g["seats"][A]["hand"]


def test_auto_advance_waits_for_pending_effects():
    g = fresh()
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Copper"] * 5)
    assert mv(g, A, {"type": "play_action", "card": "Militia"})[0]
    assert g["phase"] == "action"          # opponent still resolving the attack
    assert decide(g, B, cards=["Copper", "Copper"])[0]
    assert g["phase"] == "buy"             # effects done, no actions -> advanced


def test_undo_survives_a_drawing_card_and_the_auto_advance_to_buy():
    """USER-REPORTED REGRESSION: a sticky 'something was revealed this turn'
    flag used to kill undo for the REST of the turn, so after any +1 Card
    (Upgrade, Laboratory, a start-of-turn Duration draw) every later buy /
    treasure play / decision was permanently un-undoable — including the
    moves that follow the auto-advance into the buy phase."""
    g = fresh(kingdom=K7 + ["Upgrade", "Laboratory"])
    give_hand(g, A, ["Upgrade", "Estate"])
    g["seats"][A]["deck"] = ["Copper"] * 8
    engine._arm_undo(g)
    assert mv(g, A, {"type": "play_action", "card": "Upgrade"})[0]
    # Upgrade drew (+1 Card): nothing before this point may be rewound
    assert engine.player_view(g, A)["undo_depth"] == 0
    # its trash choice is a move of MINE — undoable again
    assert g["pending_kind"] == "choose_cards"
    assert decide(g, A, cards=["Estate"])[0]
    assert engine.player_view(g, A)["undo_depth"] == 1
    assert g["pending_kind"] == "choose_pile"       # gain a card costing exactly $3
    assert decide(g, A, pile="Silver")[0]
    assert "Silver" in g["seats"][A]["discard"]
    assert g["phase"] == "buy"                      # auto-advanced (no actions left)
    # the gain + auto-advance are still reversible
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["phase"] == "action" and g["pending_kind"] == "choose_pile"
    assert "Silver" not in g["seats"][A]["discard"]
    # and so is a buy made after all of it
    assert decide(g, A, pile="Silver")[0]
    g["coins"] = 6
    assert mv(g, A, {"type": "buy", "card": "Gold"})[0]
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert g["coins"] == 6 and "Gold" not in g["seats"][A]["discard"]


def test_undo_after_a_start_of_turn_duration_draw():
    """The same lockout hit any turn that OPENED with a Duration draw."""
    g = fresh(kingdom=K7 + ["Caravan"], expansions=("base", "seaside"))
    give_hand(g, A, ["Caravan"])
    g["seats"][A]["deck"] = ["Copper"] * 12
    assert mv(g, A, {"type": "play_action", "card": "Caravan"})[0]
    assert mv(g, A, {"type": "end_phase"})[0]
    if g["turn"] == A:
        assert mv(g, A, {"type": "end_phase"})[0]
    while g["turn"] == B:
        assert mv(g, B, {"type": "end_phase"})[0]
    # A's turn opened with Caravan's +1 Card
    assert g["turn"] == A and engine.player_view(g, A)["undo_depth"] == 0
    if g["phase"] == "action":
        assert mv(g, A, {"type": "end_phase"})[0]
    g["coins"] = 3
    assert mv(g, A, {"type": "buy", "card": "Silver"})[0]
    assert mv(g, A, {"type": "undo_turn"})[0]        # still undoable
    assert g["coins"] == 3 and "Silver" not in g["seats"][A]["discard"]


def test_off_turn_bonuses_are_lost_not_given_to_the_turn_player():
    """Actions/Buys/Coins are ONE set of pools belonging to whoever's turn it
    is, and they reset each turn (compendium ch. II), so a bonus earned on an
    opponent's turn has no pool to land in. Before `pid`, these credited the
    CURRENT TURN PLAYER — an off-turn reaction handed its bonus to the
    ATTACKER. Latent until a card grants resources off-turn; Hinterlands'
    Trail (+1 Action) and Nomads (+$2) are the first."""
    g = fresh()
    assert g["turn"] == A
    before = (g["actions"], g["buys"], g["coins"])

    engine.add_actions(g, 1, pid=B)          # B reacting on A's turn
    engine.add_buys(g, 1, pid=B)
    engine.add_coins(g, 2, pid=B)
    assert (g["actions"], g["buys"], g["coins"]) == before, \
        "an off-turn bonus leaked into the turn player's pools"
    assert any(e.get("event") == "off_turn_bonus" for e in g["log"])

    # the turn player's own bonuses still land, with or without an explicit pid
    engine.add_coins(g, 3)
    engine.add_coins(g, 1, pid=A)
    assert g["coins"] == before[2] + 4


def test_coins_can_be_deducted_and_floor_at_zero():
    """Souk deducts $1 per card in hand and can take more than it gave."""
    g = fresh()
    engine.add_coins(g, 7)
    engine.add_coins(g, -3)
    assert g["coins"] == 4
    engine.add_coins(g, -99)
    assert g["coins"] == 0, "the money pool must never go negative"


def _autoplayed_treasures():
    """Every Treasure play_all_treasures would autoplay — read from the
    REGISTRIES, so a future expansion's treasure is covered the day it lands."""
    manual = engine.manual_treasures()
    return sorted(n for n, d in CARDS.items()
                  if "treasure" in d["types"] and n not in manual)


@pytest.mark.parametrize("card", _autoplayed_treasures())
def test_every_autoplayed_treasure_leaves_the_bulk_play_undoable(card):
    """play_all_treasures is ONE move, so one reveal anywhere inside it clears
    the undo stack and takes the WHOLE bulk down with it — including the
    treasures that were perfectly reversible. Playing one at a time, you'd
    still be able to take back everything up to the revealing card, so the
    button would strictly REDUCE what you can undo. A Treasure that draws,
    looks or reveals therefore belongs in MANUAL_TREASURES, where the player
    chooses when to burn their undo.

    Registry-driven on purpose: this fails the day a set adds a revealing
    treasure to the autoplay bucket, which is exactly when it's easy to fix."""
    g = fresh(kingdom=K7, expansions=("base",))
    g["supply"].setdefault(card, 10)
    assert mv(g, A, {"type": "end_phase"})[0]          # -> buy phase
    give_hand(g, A, ["Copper", card])
    engine._post_move(g)            # give_hand changes VP; resync before baselining
    engine._arm_undo(g)                                 # as a fresh turn arms it

    before = _state(g)
    assert mv(g, A, {"type": "play_all_treasures"})[0]
    assert g["seats"][A]["in_play"], f"{card}: nothing was played"

    ok, err = mv(g, A, {"type": "undo_turn"})
    assert ok, f"{card} made the bulk treasure play un-undoable: {err}"
    assert _state(g) == before, f"{card}: undo did not fully restore the state"


def test_the_autoplay_undo_guard_actually_bites(monkeypatch):
    """Proves the invariant above isn't vacuous. Crystal Ball looks at the top
    of the deck, so it's MANUAL; demote it to the autoplay bucket and the bulk
    play stops being undoable — which is what the guard exists to catch."""
    from games.dontminion import effects
    monkeypatch.setattr(effects, "MANUAL_TREASURES",
                        effects.MANUAL_TREASURES - {"Crystal Ball"})
    g = fresh()
    g["supply"].setdefault("Crystal Ball", 10)
    assert mv(g, A, {"type": "end_phase"})[0]
    give_hand(g, A, ["Copper", "Crystal Ball"])
    engine._post_move(g)
    engine._arm_undo(g)

    assert mv(g, A, {"type": "play_all_treasures"})[0]      # now autoplays it
    assert g["turn_revealed"] is True                       # it looked at the deck
    ok, _err = mv(g, A, {"type": "undo_turn"})
    assert not ok, "guard is vacuous — a revealing treasure stayed undoable"


def _state(g):
    """Everything undo must restore — coins/buys, zones, watchers, turn_ctx,
    duration set-ups. Excludes the log (truncated by design) and the stack."""
    return json.dumps({k: v for k, v in g.items()
                       if k not in ("undo_stack", "log", "turn_revealed")},
                      sort_keys=True)


def test_undo_snapshots_do_not_copy_the_log():
    """HYGIENE: the log is append-only, so a snapshot stores only its LENGTH
    and undo restores by truncation. Copying it put up to _UNDO_CAP copies of
    a growing log in every save blob (and in the deepcopy on every move)."""
    g = fresh()
    give_hand(g, A, ["Copper", "Copper", "Copper", "Estate", "Estate"])
    engine._arm_undo(g)
    assert mv(g, A, {"type": "end_phase"})[0]
    for _ in range(4):
        assert mv(g, A, {"type": "play_treasure", "card": "Copper"})[0] or True
    stack = g["undo_stack"]
    assert stack, "snapshots were taken"
    for snap in stack:
        assert "log" not in snap                  # the whole point
        assert isinstance(snap["_log_len"], int)
    # the snapshots hold no copy of the log at all
    assert json.dumps(stack).count('"event"') == 0
    # ...and undo rewinds the log EXACTLY to the snapshot, then logs itself
    depth = len(stack)
    snap_len = stack[-1]["_log_len"]
    before = [dict(e) for e in g["log"]]
    assert mv(g, A, {"type": "undo_turn"})[0]
    assert len(g["log"]) == snap_len + 1          # truncated, plus the "undo" line
    assert g["log"][-1]["event"] == "undo"
    assert g["log"][:snap_len] == before[:snap_len]   # earlier lines untouched
    assert len(g["undo_stack"]) == depth - 1
    assert [e["n"] for e in g["log"]] == list(range(len(g["log"])))  # n stays == index
    # replaying to the start of the turn leaves a consistent log
    while g["undo_stack"]:
        assert mv(g, A, {"type": "undo_turn"})[0]
    assert [e["n"] for e in g["log"]] == list(range(len(g["log"])))
    assert g["phase"] == "action" and g["coins"] == 0


# --- concurrent-ability ordering: the START-OF-TURN pool (p23 §2) ---------------

KSEA = ["Wharf", "Tide Pools", "Smithy", "Village", "Moat", "Militia",
        "Witch", "Gardens", "Warehouse", "Bazaar"]


def _to_turn2_with(durations, seed=5):
    """Play `durations` from A's hand on turn 1, cycle through B, and stop at
    the moment A's turn 2 begins (the pool, if any, is on the stack)."""
    g = engine.new_game([A, B], ["base", "seaside"], seed=seed, kingdom=KSEA)
    g["seats"][A]["hand"] = list(durations)
    g["actions"] = len(durations)
    for i, c in enumerate(durations):
        ok, err = engine.apply_move(g, A, {"type": "play_action", "card": c})
        assert ok, err
        if i < len(durations) - 1:
            g["phase"] = "action"                # auto-advance flips it per play
    if g["phase"] == "action":
        assert engine.apply_move(g, A, {"type": "end_phase"})[0]
    assert engine.apply_move(g, A, {"type": "end_phase"})[0]
    assert engine.apply_move(g, B, {"type": "end_phase"})[0]
    if g["turn"] == B:
        assert engine.apply_move(g, B, {"type": "end_phase"})[0]
    assert g["turn"] == A
    return g


def _pool_labels(g):
    assert g["pending_kind"] == "choose_option", g["pending_kind"]
    assert g["pending"][-1]["card"] == "__abilities"
    return {o["label"]: o["id"] for o in g["pending"][-1]["constraint"]["options"]}


def test_two_distinct_durations_prompt_for_resolution_order():
    g = _to_turn2_with(["Wharf", "Tide Pools"])
    labels = _pool_labels(g)
    assert set(labels) == {"Wharf", "Tide Pools"}
    # the frame is a plain choose_option: enumerable, sampleable, JSON-safe
    assert {"type": "decision", "ids": [labels["Tide Pools"]]} in engine.legal_moves(g, A)
    json.dumps(g)
    hand0 = len(g["seats"][A]["hand"])
    # pick Tide Pools first -> its discard decision comes up next
    assert engine.apply_move(g, A, {"type": "decision", "ids": [labels["Tide Pools"]]})[0]
    assert g["pending_kind"] == "choose_cards" and g["pending"][-1]["card"] == "Tide Pools"
    picks = g["pending"][-1]["constraint"]["cards"][:2]
    assert engine.apply_move(g, A, {"type": "decision", "cards": picks})[0]
    # ONE ability left -> Wharf runs directly, no second prompt
    assert g["pending_pid"] is None
    assert len(g["seats"][A]["hand"]) == hand0 - 2 + 2    # -2 discard, +2 Wharf
    assert g["buys"] == 2                                  # Wharf's +1 Buy landed


def test_identical_durations_collapse_no_prompt():
    """Two Tide Pools are interchangeable — the pool must NOT nag (the exact
    real game that motivated the lose-track work saw no prompt, correctly)."""
    g = _to_turn2_with(["Tide Pools", "Tide Pools"], seed=6)
    assert g["pending_kind"] == "choose_cards"             # straight to discard #1
    assert g["pending"][-1]["card"] == "Tide Pools"
    picks = g["pending"][-1]["constraint"]["cards"][:2]
    assert engine.apply_move(g, A, {"type": "decision", "cards": picks})[0]
    assert g["pending_kind"] == "choose_cards"             # then discard #2
    picks = g["pending"][-1]["constraint"]["cards"][:2]
    assert engine.apply_move(g, A, {"type": "decision", "cards": picks})[0]
    assert g["pending_pid"] is None


def test_pool_reoffers_after_each_pick_and_interleaves():
    """2x Tide Pools + Wharf: the copies share ONE option ("Tide Pools ×2");
    picking it resolves ONE copy, then the pool re-offers — so Wharf can
    resolve BETWEEN the two Tide Pools, the interleaving p24 §3 requires."""
    g = _to_turn2_with(["Tide Pools", "Wharf", "Tide Pools"], seed=7)
    labels = _pool_labels(g)
    assert set(labels) == {"Tide Pools ×2", "Wharf"}
    assert engine.apply_move(g, A, {"type": "decision", "ids": [labels["Tide Pools ×2"]]})[0]
    picks = g["pending"][-1]["constraint"]["cards"][:2]
    assert engine.apply_move(g, A, {"type": "decision", "cards": picks})[0]
    labels = _pool_labels(g)                               # re-offered, re-grouped
    assert set(labels) == {"Tide Pools", "Wharf"}
    assert engine.apply_move(g, A, {"type": "decision", "ids": [labels["Wharf"]]})[0]
    # Wharf resolved between the two Tide Pools; the last one runs directly
    assert g["pending_kind"] == "choose_cards" and g["pending"][-1]["card"] == "Tide Pools"
    picks = g["pending"][-1]["constraint"]["cards"][:2]
    assert engine.apply_move(g, A, {"type": "decision", "cards": picks})[0]
    assert g["pending_pid"] is None
    assert g["buys"] == 2


def test_pool_prompt_redacts_and_reconnects_like_any_decision():
    g = _to_turn2_with(["Wharf", "Tide Pools"], seed=8)
    mine = engine.player_view(g, A)
    theirs = engine.player_view(g, B)
    assert mine["pending_view"]["kind"] == "choose_option"
    assert {o["label"] for o in mine["pending_view"]["constraint"]["options"]} \
        == {"Wharf", "Tide Pools"}
    assert theirs["pending_view"]["waiting_on"] == A
    assert "constraint" not in theirs["pending_view"]
    # save/load mid-prompt round-trips (frames are plain JSON)
    g2 = json.loads(json.dumps(g))
    assert g2["pending"][-1] == g["pending"][-1]


def test_pool_is_answerable_by_the_bot_path():
    g = _to_turn2_with(["Wharf", "Tide Pools"], seed=9)
    for _ in range(6):                                     # drain via sampling
        if g["pending_pid"] != A:
            break
        mv = {"type": "decision", **engine.sample_decision(g, A, random.Random(3))}
        ok, err = engine.apply_move(g, A, mv)
        assert ok, err
    assert g["pending_pid"] is None


def test_turn_start_reaction_and_duration_fx_share_one_pool():
    """Phase 4: ALL start-of-turn abilities are one concurrent set — a Clerk in
    hand and a Wharf finishing pool together, and the player may resolve the
    Wharf's draw BEFORE deciding whether to play the Clerk (before the fold,
    Clerk's window always cut ahead of the fx with no choice)."""
    g = engine.new_game([A, B], ["base", "seaside", "prosperity"], seed=4,
                        kingdom=["Wharf", "Clerk", "Tide Pools", "Smithy", "Village",
                                 "Moat", "Militia", "Witch", "Gardens", "Bazaar"])
    g["seats"][A]["hand"] = ["Wharf"]
    ok, err = engine.apply_move(g, A, {"type": "play_action", "card": "Wharf"})
    assert ok, err
    if g["phase"] == "action":
        assert engine.apply_move(g, A, {"type": "end_phase"})[0]
    assert engine.apply_move(g, A, {"type": "end_phase"})[0]
    # A's next hand was already drawn at A's own clean-up — put the Clerk
    # straight into it (and refill the deck so Wharf's +2 Cards can land)
    g["seats"][A]["hand"].append("Clerk")
    g["seats"][A]["deck"] = ["Copper"] * 6
    assert engine.apply_move(g, B, {"type": "end_phase"})[0]
    if g["turn"] == B:
        assert engine.apply_move(g, B, {"type": "end_phase"})[0]
    assert g["turn"] == A and "Clerk" in g["seats"][A]["hand"]
    labels = _pool_labels(g)
    assert set(labels) == {"Wharf", "Clerk"}
    # resolve the Wharf first — the choice the old fixed order never offered
    hand0 = len(g["seats"][A]["hand"])
    assert engine.apply_move(g, A, {"type": "decision", "ids": [labels["Wharf"]]})[0]
    assert len(g["seats"][A]["hand"]) == hand0 + 2       # Wharf's +2 Cards landed
    # ONE ability left: Clerk's window opens directly, no second prompt
    assert g["pending_kind"] == "choose_option" and g["pending"][-1]["card"] == "Clerk"
    assert engine.apply_move(g, A, {"type": "decision", "ids": ["play"]})[0]
    assert "Clerk" in g["seats"][A]["in_play"]
    assert g["pending_pid"] == B                         # Clerk's attack hits B
