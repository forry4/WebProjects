"""Renaissance, half B — the mechanically complex twelve, twelve Projects and
the five Artifacts.

Headline rulings pinned here (each one cost a design decision):

  * **Cargo Ship does NOT stay in play if you set nothing aside**, and the
    set-aside choice is made AT GAIN TIME, only for gains after it was played.
  * **Research with a $0 trash (or an empty deck) doesn't stay in play either**,
    and a cost reduction shrinks the count it sets aside.
  * **Border Guard reads the LANTERN off the PLAYER** (2019 errata) — 3 cards
    and 2 discarded, and all three must be Actions for the artifact choice;
    with one card to reveal you simply put it into your hand.
  * **Patron's trigger is the WORD "reveal"** — a hand reveal in an opponent's
    Action phase pays, a Buy-phase reveal doesn't, and discarding never does.
  * **Priest's own trash pays nothing** ("effects are immediate") while a
    second trash — including a SUPPLY trash — pays +$2.
  * **Sewers fires once per CARD of a batch trash** and never off its own.
  * **Improve's candidates are `leaving_play`**, so a Duration that stays out
    is not offered and the Improve itself is.
  * **Innovation is once per turn and own-turn only**; **Citadel replays the
    FIRST Action play and only that one.**
  * **Scepter's targets are "played this turn AND still in play", non-Command**
    — including a card that has not finished resolving.
"""

from games.dontminion import cards, effects, engine

A, B, C = "alice", "bob", "carol"

# the half-B kingdom
KB = ["Border Guard", "Cargo Ship", "Experiment", "Improve", "Inventor",
      "Mountain Village", "Patron", "Priest", "Research", "Scepter"]
# a mixed board for the cross-set corners (Chapel batches, Throne Room,
# Command cards, a Potion cost for Seer's ceiling)
KMIX = ["Seer", "Treasurer", "Border Guard", "Priest", "Improve",
        "Chapel", "Village", "Smithy", "Throne Room", "Familiar"]


def fresh(players=(A, B), seed=11, kingdom=tuple(KB), landscapes=(),
          expansions=("renaissance",)):
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


def give_hand(g, pid, cards_):
    g["seats"][pid]["hand"] = list(cards_)


def give_deck(g, pid, cards_):
    g["seats"][pid]["deck"] = list(cards_)


def give_cube(g, name, pid):
    g["landscapes"][name]["bought_by"].append(pid)


def events(g, name):
    return [e for e in g["log"] if e.get("event") == name]


def play(g, pid, card):
    ok, err = mv(g, pid, {"type": "play_action", "card": card})
    assert ok, err


def to_buy(g, pid):
    if g["phase"] == "action":
        ok, err = mv(g, pid, {"type": "end_phase"})
        assert ok, err


def end_turn(g, pid):
    to_buy(g, pid)
    if g["over"] or g["pending"]:
        return
    ok, err = mv(g, pid, {"type": "end_phase"})
    assert ok, err


def gain(g, pid, pile, **kw):
    out = engine.gain(g, pid, pile, **kw)
    engine._drive(g)
    return out


# ══ BORDER GUARD ═════════════════════════════════════════════════════════════

def test_border_guard_keeps_one_of_two_and_discards_the_other():
    g = fresh()
    give_hand(g, A, ["Border Guard"])
    give_deck(g, A, ["Copper", "Estate", "Gold"])
    play(g, A, "Border Guard")
    assert g["actions"] == 1, "+1 Action"
    assert sorted(frame(g)["constraint"]["cards"]) == ["Copper", "Estate"]
    assert decide(g, A, cards=["Copper"])[0]
    assert g["seats"][A]["hand"] == ["Copper"]
    assert g["seats"][A]["discard"] == ["Estate"]
    assert not g["pending"], "neither was an Action: no artifact choice"


def test_border_guard_two_actions_offers_the_lantern_or_the_horn():
    g = fresh()
    give_hand(g, A, ["Border Guard"])
    give_deck(g, A, ["Improve", "Priest", "Gold"])
    play(g, A, "Border Guard")
    assert decide(g, A, cards=["Improve"])[0]
    assert frame(g)["card"] == "Border Guard"
    assert sorted(opt_ids(g)) == ["Horn", "Lantern"]
    assert decide(g, A, ids=["Horn"])[0]
    assert engine.holds_artifact(g, A, "Horn")
    assert g["artifacts"]["Lantern"] is None


def test_border_guard_with_the_lantern_reveals_three_and_discards_two():
    """2019: "Border Guards you play reveal 3 cards and discard 2. (It takes
    all 3 being Actions to take the Horn.)" — and the check is on the PLAYER
    holding it, not on whose Border Guard it is."""
    g = fresh()
    g["artifacts"]["Lantern"] = A
    give_hand(g, A, ["Border Guard"])
    give_deck(g, A, ["Improve", "Priest", "Patron", "Gold"])
    play(g, A, "Border Guard")
    assert sorted(frame(g)["constraint"]["cards"]) == ["Improve", "Patron", "Priest"]
    assert decide(g, A, cards=["Patron"])[0]
    assert g["seats"][A]["hand"] == ["Patron"]
    assert sorted(g["seats"][A]["discard"]) == ["Improve", "Priest"], "discard 2"
    assert sorted(opt_ids(g)) == ["Horn", "Lantern"], "all 3 were Actions"
    assert decide(g, A, ids=["Lantern"])[0]
    assert engine.holds_artifact(g, A, "Lantern"), "taking your own is a no-op"


def test_border_guard_with_the_lantern_needs_all_three_to_be_actions():
    g = fresh()
    g["artifacts"]["Lantern"] = A
    give_hand(g, A, ["Border Guard"])
    give_deck(g, A, ["Improve", "Priest", "Gold", "Gold"])
    play(g, A, "Border Guard")
    assert decide(g, A, cards=["Improve"])[0]
    assert not g["pending"], "the Gold breaks the all-Actions test"


def test_border_guard_with_one_card_to_reveal_puts_it_into_your_hand():
    """"If you don't have enough cards (after shuffling) to reveal 2 cards …
    you don't take Lantern or Horn. If you only have one card to reveal, put it
    into your hand.\""""
    g = fresh()
    give_hand(g, A, ["Border Guard"])
    give_deck(g, A, ["Priest"])
    g["seats"][A]["discard"] = []
    play(g, A, "Border Guard")
    assert g["seats"][A]["hand"] == ["Priest"]
    assert not g["pending"], "no choice, and no artifact"


def test_border_guard_with_an_empty_deck_does_nothing_further():
    g = fresh()
    give_hand(g, A, ["Border Guard"])
    give_deck(g, A, [])
    g["seats"][A]["discard"] = []
    play(g, A, "Border Guard")
    assert not g["pending"] and g["actions"] == 1


# ══ CARGO SHIP ═══════════════════════════════════════════════════════════════

def _cargo_setup(g):
    give_hand(g, A, ["Cargo Ship"])
    play(g, A, "Cargo Ship")
    to_buy(g, A)
    return g


def test_cargo_ship_pays_two_and_offers_a_gain_it_can_catch():
    g = _cargo_setup(fresh())
    assert g["coins"] == 2
    gain(g, A, "Silver")
    f = frame(g)
    assert f is not None and f["card"] == "Cargo Ship"
    assert decide(g, A, ids=["yes"])[0]
    assert g["seats"][A]["dur_aside"] == ["Silver"]
    assert "Silver" not in g["seats"][A]["discard"]


def test_cargo_ship_returns_the_set_aside_card_at_your_next_turn_start():
    g = _cargo_setup(fresh())
    gain(g, A, "Silver")
    decide(g, A, ids=["yes"])
    end_turn(g, A)
    assert [e["card"] for e in g["seats"][A]["duration"]] == ["Cargo Ship"], \
        "it stays in play"
    assert "Cargo Ship" not in g["seats"][A]["discard"]
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A
    assert "Silver" in g["seats"][A]["hand"]
    assert g["seats"][A]["dur_aside"] == []


def test_cargo_ship_does_not_stay_in_play_when_nothing_was_set_aside():
    """"Cargo Ship is discarded in Clean-up if you haven't set aside any
    cards, which means you may 'remodel' it [with Improve].\""""
    g = _cargo_setup(fresh())
    gain(g, A, "Silver")
    assert decide(g, A, ids=["no"])[0]
    end_turn(g, A)
    assert g["seats"][A]["duration"] == []
    assert "Cargo Ship" in g["seats"][A]["discard"]


def test_cargo_ship_never_stays_in_play_with_no_gain_at_all():
    g = _cargo_setup(fresh())
    end_turn(g, A)
    assert g["seats"][A]["duration"] == []
    assert "Cargo Ship" in g["seats"][A]["discard"]


def test_cargo_ship_only_catches_gains_after_it_was_played():
    g = fresh()
    give_hand(g, A, ["Cargo Ship"])
    gain(g, A, "Silver")                    # BEFORE the play
    assert not g["pending"]
    play(g, A, "Cargo Ship")
    to_buy(g, A)
    gain(g, A, "Gold")
    assert frame(g)["card"] == "Cargo Ship"


def test_cargo_ship_is_once_per_play():
    g = _cargo_setup(fresh())
    gain(g, A, "Silver")
    decide(g, A, ids=["yes"])
    gain(g, A, "Gold")
    assert not g["pending"], "this copy's once-a-turn set-aside is spent"


def test_two_cargo_ship_plays_are_two_independent_set_asides():
    g = fresh()
    give_hand(g, A, ["Cargo Ship", "Cargo Ship"])
    g["actions"] = 2
    play(g, A, "Cargo Ship")
    play(g, A, "Cargo Ship")
    to_buy(g, A)
    gain(g, A, "Silver")
    assert decide(g, A, ids=["yes"])[0]
    engine._drive(g)
    gain(g, A, "Gold")
    assert frame(g) is not None and frame(g)["card"] == "Cargo Ship"
    assert decide(g, A, ids=["yes"])[0]
    assert sorted(g["seats"][A]["dur_aside"]) == ["Gold", "Silver"]


# ══ EXPERIMENT ═══════════════════════════════════════════════════════════════

def test_experiment_draws_two_and_returns_itself_to_its_pile():
    g = fresh()
    give_hand(g, A, ["Experiment"])
    give_deck(g, A, ["Copper", "Estate", "Gold"])
    before = engine.pile_count(g, "Experiment")
    play(g, A, "Experiment")
    assert len(g["seats"][A]["hand"]) == 2 and g["actions"] == 1
    assert "Experiment" not in g["seats"][A]["in_play"]
    assert engine.pile_count(g, "Experiment") == before + 1


def test_gaining_an_experiment_gains_another_that_does_not_chain():
    g = fresh()
    before = engine.pile_count(g, "Experiment")
    gain(g, A, "Experiment")
    assert g["seats"][A]["discard"].count("Experiment") == 2
    assert engine.pile_count(g, "Experiment") == before - 2, "exactly two"


def test_a_thrown_experiment_still_bonuses_after_it_left_play():
    """"Play-without-moving still gives +2 Cards +1 Action" — the Throne Room
    replay resolves after the card has returned to its pile."""
    g = fresh(kingdom=KB[:9] + ["Throne Room"], expansions=("renaissance", "base"))
    give_hand(g, A, ["Throne Room", "Experiment"])
    give_deck(g, A, ["Copper"] * 6)
    play(g, A, "Throne Room")
    assert decide(g, A, cards=["Experiment"])[0]
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 4, "+2 Cards twice"
    assert g["actions"] == 2


# ══ IMPROVE ══════════════════════════════════════════════════════════════════

def test_improve_remodels_a_card_leaving_play_at_the_start_of_cleanup():
    g = fresh(kingdom=KB[:9] + ["Village"], expansions=("renaissance", "base"))
    give_hand(g, A, ["Improve", "Village"])
    g["actions"] = 2
    play(g, A, "Improve")
    assert g["coins"] == 2
    play(g, A, "Village")
    end_turn(g, A)
    f = frame(g)
    assert f is not None and f["card"] == "Improve"
    assert sorted(f["constraint"]["cards"]) == ["Improve", "Village"], \
        "you can choose the Improve itself"
    assert decide(g, A, cards=["Village"])[0]      # Village costs $3
    assert "Village" in g["trash"]
    piles = frame(g)["constraint"]["piles"]
    assert all(engine.cost(g, p) == 4 for p in piles), "exactly $1 more"
    assert decide(g, A, pile="Inventor")[0]
    engine._drive(g)
    assert "Inventor" in engine.owned_cards(g, A)


def test_improve_may_trash_the_improve_itself():
    g = fresh()
    give_hand(g, A, ["Improve"])
    play(g, A, "Improve")
    end_turn(g, A)
    assert decide(g, A, cards=["Improve"])[0]
    assert "Improve" in g["trash"]
    piles = frame(g)["constraint"]["piles"]
    assert all(engine.cost(g, p) == 4 for p in piles)


def test_improve_declined_does_nothing():
    g = fresh()
    give_hand(g, A, ["Improve"])
    play(g, A, "Improve")
    end_turn(g, A)
    assert decide(g, A, cards=[])[0]
    assert g["trash"] == []
    assert g["turn"] == B


def test_improve_never_offers_a_duration_that_stays_in_play():
    """"You can only choose a card that would be discarded this turn, so not a
    Duration that will stay in play." Cargo Ship is the in-set case: it stays
    only when it caught a gain."""
    g = fresh()
    give_hand(g, A, ["Improve", "Cargo Ship"])
    g["actions"] = 2
    play(g, A, "Improve")
    play(g, A, "Cargo Ship")
    to_buy(g, A)
    gain(g, A, "Silver")
    decide(g, A, ids=["yes"])              # the Cargo Ship now stays out
    engine._drive(g)
    ok, err = mv(g, A, {"type": "end_phase"})
    assert ok, err
    assert frame(g)["constraint"]["cards"] == ["Improve"], "no Cargo Ship"


def test_improve_offers_a_cargo_ship_that_set_nothing_aside():
    g = fresh()
    give_hand(g, A, ["Improve", "Cargo Ship"])
    g["actions"] = 2
    play(g, A, "Improve")
    play(g, A, "Cargo Ship")
    end_turn(g, A)
    assert sorted(frame(g)["constraint"]["cards"]) == ["Cargo Ship", "Improve"]


def test_two_improves_each_get_a_go():
    g = fresh(kingdom=KB[:9] + ["Village"], expansions=("renaissance", "base"))
    give_hand(g, A, ["Improve", "Improve", "Village"])
    g["actions"] = 3
    play(g, A, "Improve")
    play(g, A, "Improve")
    play(g, A, "Village")
    end_turn(g, A)
    assert decide(g, A, cards=["Village"])[0]
    engine._drive(g)
    assert decide(g, A, pile="Inventor")[0]
    engine._drive(g)
    f = frame(g)
    assert f is not None and f["card"] == "Improve", "the second Improve"


# ══ INVENTOR ═════════════════════════════════════════════════════════════════

def test_inventor_gains_first_then_reduces_costs():
    """"Card costs are not reduced when you gain the card.\""""
    g = fresh()
    give_hand(g, A, ["Inventor"])
    play(g, A, "Inventor")
    piles = frame(g)["constraint"]["piles"]
    assert "Improve" in piles and "Priest" in piles
    assert "Scepter" not in piles, "$5 — the reduction is not live yet"
    assert decide(g, A, pile="Priest")[0]
    engine._drive(g)
    assert g["turn_ctx"]["bridges"] == 1
    assert engine.cost(g, "Priest") == 3
    assert engine.cost(g, "Copper") == 0, "min 0 as ever"


def test_inventor_reduces_even_with_nothing_to_gain():
    g = fresh()
    for pile in list(g["supply"]):
        if engine.cost(g, pile) <= 4:
            g["supply"][pile] = 0
    give_hand(g, A, ["Inventor"])
    play(g, A, "Inventor")
    engine._drive(g)
    assert g["turn_ctx"]["bridges"] == 1


def test_two_inventors_stack_their_reductions():
    g = fresh()
    give_hand(g, A, ["Inventor", "Inventor"])
    g["actions"] = 2
    play(g, A, "Inventor")
    assert decide(g, A, pile="Copper")[0]
    engine._drive(g)
    play(g, A, "Inventor")
    assert decide(g, A, pile="Copper")[0]
    engine._drive(g)
    assert g["turn_ctx"]["bridges"] == 2


# ══ MOUNTAIN VILLAGE ═════════════════════════════════════════════════════════

def test_mountain_village_takes_from_the_discard_pile_and_it_is_mandatory():
    g = fresh()
    give_hand(g, A, ["Mountain Village"])
    g["seats"][A]["discard"] = ["Gold", "Estate"]
    play(g, A, "Mountain Village")
    assert g["actions"] == 2
    f = frame(g)
    assert f["constraint"]["min"] == 1, "NOT OPTIONAL 'IF YOU DO'"
    assert sorted(f["constraint"]["cards"]) == ["Estate", "Gold"]
    assert decide(g, A, cards=["Gold"])[0]
    assert g["seats"][A]["hand"] == ["Gold"]
    assert g["seats"][A]["discard"] == ["Estate"]


def test_mountain_village_draws_only_when_the_discard_pile_is_empty():
    g = fresh()
    give_hand(g, A, ["Mountain Village"])
    g["seats"][A]["discard"] = []
    give_deck(g, A, ["Gold"])
    play(g, A, "Mountain Village")
    assert not g["pending"]
    assert g["seats"][A]["hand"] == ["Gold"] and g["actions"] == 2


# ══ PATRON ═══════════════════════════════════════════════════════════════════

def test_patron_gives_a_villager_and_two_coins():
    g = fresh()
    give_hand(g, A, ["Patron"])
    play(g, A, "Patron")
    assert g["villagers"][A] == 1 and g["coins"] == 2


def test_patron_pays_coffers_when_revealed_in_an_action_phase():
    """"When something causes you to reveal this (using the word 'reveal') in
    an Action phase" — including an OPPONENT's Action phase."""
    g = fresh()
    give_hand(g, B, ["Patron", "Patron", "Copper"])
    assert g["turn"] == A and g["phase"] == "action"
    engine.reveal(g, B, ["Patron", "Patron", "Copper"], "hand")
    engine._drive(g)
    assert g["coffers"].get(B, 0) == 2, "one per revealed copy, to the revealer"


def test_patron_pays_nothing_in_a_buy_phase():
    g = fresh()
    give_hand(g, A, ["Patron"])
    to_buy(g, A)
    engine.reveal(g, A, ["Patron"], "hand")
    engine._drive(g)
    assert g["coffers"].get(A, 0) == 0


def test_discarding_or_trashing_a_patron_is_not_revealing_it():
    """"Discarding or trashing a Patron does not count as revealing it, even
    though the other players can see it.\""""
    g = fresh()
    give_hand(g, A, ["Patron", "Patron"])
    engine.discard(g, A, ["Patron"], zone="hand", public=True)
    engine._drive(g)
    engine.trash(g, A, ["Patron"], zone="hand")
    engine._drive(g)
    assert g["coffers"].get(A, 0) == 0


def test_a_patron_revealed_at_the_start_of_your_turn_is_in_your_action_phase():
    g = fresh()
    give_deck(g, A, ["Patron"] * 10)
    end_turn(g, A)
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A and g["phase"] == "action"
    hand = list(g["seats"][A]["hand"])
    assert hand.count("Patron") == 5
    engine.reveal(g, A, hand, "hand")
    engine._drive(g)
    assert g["coffers"].get(A, 0) == 5


# ══ PRIEST ═══════════════════════════════════════════════════════════════════

def test_priest_own_trash_pays_nothing_but_a_later_trash_does():
    """EFFECTS ARE IMMEDIATE: Priest's own trash precedes the ongoing ability,
    so it is not paid; the next trash this turn is."""
    g = fresh()
    give_hand(g, A, ["Priest", "Copper", "Estate"])
    play(g, A, "Priest")
    assert decide(g, A, cards=["Copper"])[0]
    engine._drive(g)
    assert g["coins"] == 2, "+$2 from the card, nothing for its own trash"
    engine.trash(g, A, ["Estate"], zone="hand")
    engine._drive(g)
    assert g["coins"] == 4


def test_a_second_priests_trash_is_paid_by_the_first():
    g = fresh()
    give_hand(g, A, ["Priest", "Priest", "Copper", "Estate"])
    g["actions"] = 2
    play(g, A, "Priest")
    assert decide(g, A, cards=["Copper"])[0]
    engine._drive(g)
    assert g["coins"] == 2
    play(g, A, "Priest")
    assert decide(g, A, cards=["Estate"])[0]
    engine._drive(g)
    # +$2 for the second Priest, +$2 from the first Priest's watcher
    assert g["coins"] == 6


def test_priest_arms_its_watcher_even_with_an_empty_hand():
    g = fresh()
    give_hand(g, A, ["Priest"])
    play(g, A, "Priest")
    engine._drive(g)
    assert not g["pending"] and g["coins"] == 2
    engine.trash_from_supply(g, "Copper", A)
    engine._drive(g)
    assert g["coins"] == 4, "it triggers on a SUPPLY trash too"


def test_a_thrown_priest_pays_twice_per_later_trash():
    g = fresh(kingdom=KB[:9] + ["Throne Room"], expansions=("renaissance", "base"))
    give_hand(g, A, ["Throne Room", "Priest", "Copper", "Copper", "Estate"])
    play(g, A, "Throne Room")
    assert decide(g, A, cards=["Priest"])[0]
    assert decide(g, A, cards=["Copper"])[0]
    engine._drive(g)
    assert decide(g, A, cards=["Copper"])[0]
    engine._drive(g)
    assert g["coins"] == 4 + 2, "$2+$2 printed, and the first watcher paid the second trash"
    engine.trash(g, A, ["Estate"], zone="hand")
    engine._drive(g)
    assert g["coins"] == 6 + 4, "both watchers now"


def test_priest_does_not_pay_for_an_opponents_trash():
    g = fresh()
    give_hand(g, A, ["Priest"])
    play(g, A, "Priest")
    engine._drive(g)
    give_hand(g, B, ["Estate"])
    engine.trash(g, B, ["Estate"], zone="hand")
    engine._drive(g)
    assert g["coins"] == 2


# ══ RESEARCH ═════════════════════════════════════════════════════════════════

def test_research_sets_aside_one_card_per_dollar_and_returns_them():
    g = fresh()
    give_hand(g, A, ["Research", "Improve"])       # Improve costs $3
    give_deck(g, A, ["Gold", "Silver", "Estate", "Copper"])
    play(g, A, "Research")
    assert g["actions"] == 1
    assert decide(g, A, cards=["Improve"])[0]
    engine._drive(g)
    assert "Improve" in g["trash"]
    assert g["seats"][A]["dur_aside"] == ["Gold", "Silver", "Estate"]
    end_turn(g, A)
    assert [e["card"] for e in g["seats"][A]["duration"]] == ["Research"]
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A
    for c in ("Gold", "Silver", "Estate"):
        assert c in g["seats"][A]["hand"]
    assert g["seats"][A]["dur_aside"] == []


def test_research_with_a_zero_cost_trash_does_not_stay_in_play():
    """"If you trash a card that costs $0 … the Research doesn't stay in
    play.\""""
    g = fresh()
    give_hand(g, A, ["Research", "Copper"])
    give_deck(g, A, ["Gold", "Silver"] + ["Copper"] * 10)
    play(g, A, "Research")
    assert decide(g, A, cards=["Copper"])[0]
    engine._drive(g)
    assert g["seats"][A]["dur_aside"] == []
    end_turn(g, A)
    assert g["seats"][A]["duration"] == []
    assert g["seats"][A]["in_play"] == []
    assert "Research" in g["seats"][A]["discard"]


def test_research_with_an_empty_deck_does_not_stay_in_play():
    """"…or you don't have any cards in your deck to set aside.\""""
    g = fresh()
    give_hand(g, A, ["Research", "Improve"])
    give_deck(g, A, [])
    g["seats"][A]["discard"] = []
    play(g, A, "Research")
    assert decide(g, A, cards=["Improve"])[0]
    engine._drive(g)
    end_turn(g, A)
    assert g["seats"][A]["duration"] == []
    assert g["seats"][A]["in_play"] == []
    assert "Research" in engine.owned_cards(g, A)


def test_a_cost_reduction_shrinks_researchs_set_aside_count():
    g = fresh()
    give_hand(g, A, ["Research", "Improve"])
    give_deck(g, A, ["Gold", "Silver", "Estate", "Copper"])
    g["turn_ctx"]["bridges"] = 1                   # Improve now costs $2
    play(g, A, "Research")
    assert decide(g, A, cards=["Improve"])[0]
    engine._drive(g)
    assert g["seats"][A]["dur_aside"] == ["Gold", "Silver"]


def test_research_with_an_empty_hand_trashes_nothing():
    g = fresh()
    give_hand(g, A, ["Research"])
    play(g, A, "Research")
    engine._drive(g)
    assert not g["pending"] and g["trash"] == []
    end_turn(g, A)
    assert "Research" in g["seats"][A]["discard"]


# ══ SCEPTER ══════════════════════════════════════════════════════════════════

def test_scepter_is_never_autoplayed():
    g = fresh()
    give_hand(g, A, ["Scepter", "Copper"])
    to_buy(g, A)
    assert "Scepter" in effects.MANUAL_TREASURES
    assert engine.autoplay_treasures(g, A) == ["Copper"]


def test_scepter_can_just_pay_two():
    g = fresh()
    give_hand(g, A, ["Scepter"])
    to_buy(g, A)
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Scepter"})
    assert ok, err
    assert sorted(opt_ids(g)) == ["coins", "replay"]
    assert decide(g, A, ids=["coins"])[0]
    assert g["coins"] == 2


def test_scepter_replays_an_action_you_played_this_turn_and_still_have_in_play():
    g = fresh(kingdom=KB[:9] + ["Village"], expansions=("renaissance", "base"))
    give_hand(g, A, ["Village", "Scepter"])
    give_deck(g, A, ["Gold"] * 4)
    play(g, A, "Village")
    to_buy(g, A)
    ok, err = mv(g, A, {"type": "play_treasure", "card": "Scepter"})
    assert ok, err
    assert decide(g, A, ids=["replay"])[0]
    assert frame(g)["constraint"]["cards"] == ["Village"]
    hand = len(g["seats"][A]["hand"])
    assert decide(g, A, cards=["Village"])[0]
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == hand + 1, "Village's +1 Card again"


def test_scepter_offers_nothing_that_left_play():
    """"'Still in play' means the Action card can't have left play after you
    played it, even if it has entered play again.\""""
    g = fresh(kingdom=KB[:9] + ["Village"], expansions=("renaissance", "base"))
    give_hand(g, A, ["Village", "Scepter"])
    give_deck(g, A, ["Gold"] * 4)
    play(g, A, "Village")
    g["seats"][A]["in_play"].remove("Village")     # something took it away
    g["seats"][A]["discard"].append("Village")
    to_buy(g, A)
    mv(g, A, {"type": "play_treasure", "card": "Scepter"})
    assert decide(g, A, ids=["replay"])[0]
    assert not g["pending"], "no legal target"


def test_scepter_will_not_replay_a_command_card():
    """The 2024 errata: Scepter "now only lets you replay non-Command cards,
    and is itself a Command card"."""
    g = fresh(kingdom=KB[:8] + ["Band of Misfits", "Village"],
              expansions=("renaissance", "base", "darkages"))
    assert "command" in cards.CARDS["Scepter"]["types"]
    give_hand(g, A, ["Scepter"])
    # stage a turn that played both, both still on the table
    g["turn_ctx"]["played_actions"] = ["Village", "Band of Misfits"]
    g["seats"][A]["in_play"] = ["Village", "Band of Misfits"]
    to_buy(g, A)
    mv(g, A, {"type": "play_treasure", "card": "Scepter"})
    assert decide(g, A, ids=["replay"])[0]
    assert frame(g)["constraint"]["cards"] == ["Village"]


def test_two_scepters_may_replay_the_same_card_twice():
    g = fresh(kingdom=KB[:9] + ["Village"], expansions=("renaissance", "base"))
    give_hand(g, A, ["Village", "Scepter", "Scepter"])
    give_deck(g, A, ["Gold"] * 6)
    play(g, A, "Village")
    to_buy(g, A)
    for _ in range(2):
        ok, err = mv(g, A, {"type": "play_treasure", "card": "Scepter"})
        assert ok, err
        assert decide(g, A, ids=["replay"])[0]
        assert decide(g, A, cards=["Village"])[0]
        engine._drive(g)
    # played once (-1 Action, +2) and then resolved twice more (+2, +2)
    assert g["actions"] == 1 - 1 + 2 + 2 + 2


def test_scepter_may_replay_a_card_that_is_still_resolving():
    """"Scepter can replay a card that isn't finished being resolved yet" — a
    Storyteller that played this very Scepter is a legal target. IMPLEMENTED
    rather than pinned as a deviation: the replay's frames simply stack over
    the Scepter chooser's continuation."""
    g = fresh(kingdom=KB[:9] + ["Storyteller"],
              expansions=("renaissance", "adventures"))
    give_hand(g, A, ["Storyteller", "Scepter"])
    give_deck(g, A, ["Gold"] * 8)
    play(g, A, "Storyteller")
    assert frame(g)["card"] == "Storyteller"
    assert decide(g, A, ids=["Scepter"])[0]        # Storyteller plays it
    # Storyteller re-offers on top; decline so the Scepter chooser surfaces
    assert frame(g)["card"] == "Storyteller"
    assert decide(g, A, ids=["done"])[0]
    engine._drive(g)
    f = frame(g)
    assert f is not None and f["card"] == "Scepter"
    assert decide(g, A, ids=["replay"])[0]
    assert frame(g)["constraint"]["cards"] == ["Storyteller"]


# ══ SEER ═════════════════════════════════════════════════════════════════════

def test_seer_pockets_the_two_to_four_cards_and_orders_the_rest_back():
    g = fresh(kingdom=KMIX, expansions=("renaissance", "base", "alchemy"))
    give_hand(g, A, ["Seer"])
    give_deck(g, A, ["Copper", "Gold", "Silver", "Village", "Estate"])
    play(g, A, "Seer")
    assert g["actions"] == 1
    # drew the Copper, then revealed Gold ($6), Silver ($3), Village ($3)
    assert sorted(g["seats"][A]["hand"]) == ["Copper", "Silver", "Village"]
    f = frame(g)
    assert f is None or f["kind"] != "order_cards", "only one card goes back"
    assert g["seats"][A]["deck"][0] == "Gold"


def test_seer_orders_two_returned_cards():
    g = fresh(kingdom=KMIX, expansions=("renaissance", "base", "alchemy"))
    give_hand(g, A, ["Seer"])
    give_deck(g, A, ["Copper", "Gold", "Province", "Silver"])
    play(g, A, "Seer")
    f = frame(g)
    assert f["kind"] == "order_cards"
    assert sorted(f["constraint"]["cards"]) == ["Gold", "Province"]
    assert decide(g, A, order=["Province", "Gold"])[0]
    assert g["seats"][A]["deck"][:2] == ["Province", "Gold"]
    assert "Silver" in g["seats"][A]["hand"]


def test_seers_ceiling_is_the_whole_cost_vector_but_its_floor_is_coins_alone():
    """Deviation A5: "up to $4" excludes a Potion component, while "from $2"
    reads the coin component alone. Familiar costs {$3,P} — it is NOT in
    range; Silver ($3) is."""
    g = fresh(kingdom=KMIX, expansions=("renaissance", "base", "alchemy"))
    assert engine.cost_ge(g, "Familiar", 2) and not engine.cost_le(g, "Familiar", 4)
    give_hand(g, A, ["Seer"])
    give_deck(g, A, ["Copper", "Familiar", "Silver", "Copper"])
    play(g, A, "Seer")
    assert "Silver" in g["seats"][A]["hand"]
    assert "Familiar" not in g["seats"][A]["hand"]
    assert "Familiar" in g["seats"][A]["deck"] + g["seats"][A]["aside"]


def test_seer_with_an_empty_deck_just_draws():
    g = fresh(kingdom=KMIX, expansions=("renaissance", "base", "alchemy"))
    give_hand(g, A, ["Seer"])
    give_deck(g, A, ["Gold"])
    g["seats"][A]["discard"] = []
    play(g, A, "Seer")
    assert g["seats"][A]["hand"] == ["Gold"] and not g["pending"]


# ══ TREASURER ════════════════════════════════════════════════════════════════

def test_treasurer_pays_three_and_offers_three_ways():
    g = fresh(kingdom=KMIX, expansions=("renaissance", "base", "alchemy"))
    give_hand(g, A, ["Treasurer", "Silver"])
    play(g, A, "Treasurer")
    assert g["coins"] == 3
    assert sorted(opt_ids(g)) == ["key", "recover", "trash"]
    assert decide(g, A, ids=["trash"])[0]
    assert decide(g, A, cards=["Silver"])[0]
    assert "Silver" in g["trash"]


def test_treasurer_recovers_a_treasure_from_the_trash_to_your_hand():
    """"It's GAINED TO YOUR HAND" — when-gain abilities fire."""
    g = fresh(kingdom=KMIX, expansions=("renaissance", "base", "alchemy"))
    g["trash"] = ["Gold", "Estate"]
    give_hand(g, A, ["Treasurer"])
    play(g, A, "Treasurer")
    assert decide(g, A, ids=["recover"])[0]
    assert frame(g)["constraint"]["cards"] == ["Gold"], "Treasures only"
    assert decide(g, A, cards=["Gold"])[0]
    assert "Gold" in g["seats"][A]["hand"]
    assert g["trash"] == ["Estate"]
    assert events(g, "gain_from_trash")[-1] == {
        **events(g, "gain_from_trash")[-1], "card": "Gold", "dest": "hand"}


def test_treasurer_takes_the_key_and_the_key_pays_at_your_turn_start():
    g = fresh(kingdom=KMIX, expansions=("renaissance", "base", "alchemy"))
    give_hand(g, A, ["Treasurer"])
    play(g, A, "Treasurer")
    assert decide(g, A, ids=["key"])[0]
    assert engine.holds_artifact(g, A, "Key")
    end_turn(g, A)
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A and g["coins"] == 1


def test_the_key_pays_nobody_else():
    g = fresh(kingdom=KMIX, expansions=("renaissance", "base", "alchemy"))
    g["artifacts"]["Key"] = A
    end_turn(g, A)
    engine._drive(g)
    assert g["turn"] == B and g["coins"] == 0


# ══ THE HORN ═════════════════════════════════════════════════════════════════

def test_the_horn_topdecks_a_discarded_border_guard_once_per_turn():
    g = fresh()
    g["artifacts"]["Horn"] = A
    give_hand(g, A, ["Border Guard", "Border Guard"])
    give_deck(g, A, ["Gold"] * 12)
    g["actions"] = 2
    for _ in range(2):
        play(g, A, "Border Guard")
        assert decide(g, A, cards=["Gold"])[0]
        engine._drive(g)
    end_turn(g, A)
    f = frame(g)
    assert f is not None and f["card"] == "Horn"
    assert decide(g, A, ids=["yes"])[0]
    engine._drive(g)
    seat = g["seats"][A]
    assert seat["discard"].count("Border Guard") == 1, "only one goes back on top"
    assert "Border Guard" in seat["hand"], "the topdecked one was drawn straight back"


def test_the_horn_may_be_declined():
    g = fresh()
    g["artifacts"]["Horn"] = A
    give_hand(g, A, ["Border Guard"])
    give_deck(g, A, ["Gold"] * 12)
    play(g, A, "Border Guard")
    assert decide(g, A, cards=["Gold"])[0]
    engine._drive(g)
    end_turn(g, A)
    assert decide(g, A, ids=["no"])[0]
    engine._drive(g)
    assert "Border Guard" in g["seats"][A]["discard"]


def test_the_horn_does_nothing_for_a_non_holder():
    g = fresh()
    g["artifacts"]["Horn"] = B
    give_hand(g, A, ["Border Guard"])
    give_deck(g, A, ["Gold"] * 12)
    play(g, A, "Border Guard")
    assert decide(g, A, cards=["Gold"])[0]
    engine._drive(g)
    end_turn(g, A)
    assert "Border Guard" in g["seats"][A]["discard"]


# ══ TREASURE CHEST ═══════════════════════════════════════════════════════════

def test_the_treasure_chest_gains_a_gold_at_your_buy_phase_start():
    g = fresh()
    g["artifacts"]["Treasure Chest"] = A
    ok, err = mv(g, A, {"type": "end_phase"})
    assert ok, err
    engine._drive(g)
    assert "Gold" in g["seats"][A]["discard"]
    end_turn(g, A)
    assert g["seats"][B]["discard"].count("Gold") == 0


def test_the_treasure_chest_fires_again_after_a_villa_re_entry():
    """Its own entry names Villa among the cards that give you another Buy
    phase, and "at the start of your Buy phase" is per entrance."""
    g = fresh()
    g["artifacts"]["Treasure Chest"] = A
    ok, err = mv(g, A, {"type": "end_phase"})
    assert ok, err
    engine._drive(g)
    assert g["seats"][A]["discard"].count("Gold") == 1
    assert engine.return_to_action_phase(g, A)
    ok, err = mv(g, A, {"type": "end_phase"})
    assert ok, err
    engine._drive(g)
    assert g["seats"][A]["discard"].count("Gold") == 2


# ══ SEWERS ═══════════════════════════════════════════════════════════════════

def _sewers(players=(A, B)):
    g = fresh(players=players, kingdom=KMIX,
              expansions=("renaissance", "base", "alchemy"),
              landscapes=["Sewers"])
    give_cube(g, "Sewers", A)
    return g


def test_sewers_offers_one_trash_per_card_of_a_batch_trash():
    """"Sewers triggers once per CARD of a batch trash (a Chapel trashing 4 →
    up to 4 Sewers trashes)"."""
    g = _sewers()
    give_hand(g, A, ["Chapel"] + ["Estate"] * 4 + ["Copper"] * 4)
    play(g, A, "Chapel")
    assert decide(g, A, cards=["Estate"] * 4)[0]
    engine._drive(g)
    assert g["trash"].count("Estate") == 4
    for _ in range(4):
        f = frame(g)
        assert f is not None and f["card"] == "Sewers", "one offer per trashed card"
        assert decide(g, A, cards=["Copper"])[0]
        engine._drive(g)
    assert g["trash"].count("Copper") == 4
    assert g["seats"][A]["hand"] == []


def test_sewers_never_re_triggers_off_its_own_trash():
    g = _sewers()
    give_hand(g, A, ["Estate", "Copper", "Copper"])
    engine.trash(g, A, ["Estate"], zone="hand")
    engine._drive(g)
    assert frame(g)["card"] == "Sewers"
    assert decide(g, A, cards=["Copper"])[0]
    engine._drive(g)
    assert not g["pending"], "'other than with this'"
    assert g["trash"] == ["Estate", "Copper"]


def test_sewers_may_be_declined_and_then_nothing_happens():
    g = _sewers()
    give_hand(g, A, ["Estate", "Copper"])
    engine.trash(g, A, ["Estate"], zone="hand")
    engine._drive(g)
    assert decide(g, A, cards=[])[0]
    engine._drive(g)
    assert g["trash"] == ["Estate"]


def test_sewers_fires_on_a_supply_trash_and_on_an_opponents_turn():
    g = _sewers()
    give_hand(g, A, ["Copper"])
    engine.trash_from_supply(g, "Curse", A)
    engine._drive(g)
    assert frame(g)["card"] == "Sewers"
    assert decide(g, A, cards=["Copper"])[0]
    engine._drive(g)
    assert g["trash"] == ["Curse", "Copper"]
    # ...and on someone else's turn (the owner trashes, e.g. to Old Witch)
    g["turn"] = B
    give_hand(g, A, ["Estate", "Copper"])
    engine.trash(g, A, ["Estate"], zone="hand")
    engine._drive(g)
    assert frame(g) is not None and frame(g)["card"] == "Sewers"


def test_sewers_does_nothing_for_a_player_without_a_cube():
    g = _sewers()
    give_hand(g, B, ["Estate", "Copper"])
    engine.trash(g, B, ["Estate"], zone="hand")
    engine._drive(g)
    assert not g["pending"]


# ══ INNOVATION ═══════════════════════════════════════════════════════════════

def _innovation():
    g = fresh(landscapes=["Innovation"])
    give_cube(g, "Innovation", A)
    return g


def test_innovation_plays_a_gained_action_without_spending_one():
    g = _innovation()
    give_deck(g, A, ["Gold"] * 5)
    to_buy(g, A)
    g["actions"] = 0
    gain(g, A, "Mountain Village")
    f = frame(g)
    assert f is not None and f["card"] == "Innovation"
    assert decide(g, A, ids=["yes"])[0]
    engine._drive(g)
    assert "Mountain Village" in g["seats"][A]["in_play"]
    assert g["actions"] == 2, "+2 Actions from the card, none spent playing it"
    assert g["turn_ctx"]["innovation_used"] is True


def test_innovation_is_once_per_turn_but_any_qualifying_gain():
    """2022: "you can now use Innovation on ANY Action card you gain on your
    turn (not just the first one), but only once per turn"."""
    g = _innovation()
    give_deck(g, A, ["Gold"] * 5)
    to_buy(g, A)
    gain(g, A, "Silver")                       # not an Action: no trigger
    assert not g["pending"]
    gain(g, A, "Improve")
    assert frame(g)["card"] == "Innovation"
    assert decide(g, A, ids=["yes"])[0]
    engine._drive(g)
    gain(g, A, "Priest")
    assert not g["pending"], "once per turn"
    assert "Priest" in g["seats"][A]["discard"]


def test_declining_innovation_leaves_it_available():
    g = _innovation()
    give_deck(g, A, ["Gold"] * 5)
    to_buy(g, A)
    gain(g, A, "Improve")
    assert decide(g, A, ids=["no"])[0]
    engine._drive(g)
    assert g["turn_ctx"]["innovation_used"] is False
    gain(g, A, "Priest")
    assert frame(g)["card"] == "Innovation"


def test_innovation_does_not_trigger_on_an_opponents_turn():
    """"If you gain an Action card during an opponent's turn, Innovation
    doesn't trigger.\""""
    g = _innovation()
    gain(g, B, "Improve")                      # bob has no cube anyway
    assert not g["pending"]
    g["turn"] = B
    gain(g, A, "Improve")                      # alice owns the cube, wrong turn
    assert not g["pending"]


# ══ CITADEL ══════════════════════════════════════════════════════════════════

def _citadel(kingdom=None):
    g = fresh(kingdom=tuple(kingdom or (KB[:9] + ["Village"])),
              expansions=("renaissance", "base"), landscapes=["Citadel"])
    give_cube(g, "Citadel", A)
    return g


def test_citadel_replays_the_first_action_after_it_resolves():
    g = _citadel()
    give_hand(g, A, ["Village", "Village"])
    give_deck(g, A, ["Gold"] * 6)
    play(g, A, "Village")
    engine._drive(g)
    assert g["turn_ctx"]["citadel_used"] is True
    assert g["actions"] == 1 - 1 + 2 + 2, "played once, resolved twice"
    assert len(g["seats"][A]["hand"]) == 1 + 2, "the second Village + two draws"


def test_citadel_replays_only_the_first_play_of_the_turn():
    g = _citadel()
    give_hand(g, A, ["Village", "Village"])
    give_deck(g, A, ["Gold"] * 6)
    play(g, A, "Village")
    engine._drive(g)
    actions = g["actions"]
    play(g, A, "Village")
    engine._drive(g)
    assert g["actions"] == actions - 1 + 2, "the second play is replayed no more"


def test_citadel_fires_again_next_turn():
    g = _citadel()
    give_hand(g, A, ["Village"])
    give_deck(g, A, ["Gold"] * 12)
    play(g, A, "Village")
    engine._drive(g)
    end_turn(g, A)
    end_turn(g, B)
    engine._drive(g)
    assert g["turn"] == A and g["turn_ctx"]["citadel_used"] is False


def test_citadel_does_nothing_for_a_player_without_a_cube():
    g = _citadel()
    give_hand(g, B, ["Village"])
    give_deck(g, B, ["Gold"] * 6)
    g["turn"] = B
    g["phase"] = "action"
    g["actions"] = 1
    play(g, B, "Village")
    engine._drive(g)
    assert g["actions"] == 2, "one play, one resolution"


# ══ PIAZZA ═══════════════════════════════════════════════════════════════════

def test_piazza_plays_a_revealed_action_at_your_turn_start():
    g = fresh(kingdom=KB[:9] + ["Village"], expansions=("renaissance", "base"),
              landscapes=["Piazza"])
    give_cube(g, "Piazza", B)
    g["seats"][B]["deck"] = ["Village"] + ["Gold"] * 10
    end_turn(g, A)
    engine._drive(g)
    assert g["turn"] == B
    assert "Village" in g["seats"][B]["in_play"]
    assert g["actions"] == 1 + 2, "the Village's +2 Actions, no Action spent"


def test_piazza_puts_a_non_action_back_on_top():
    g = fresh(landscapes=["Piazza"])
    give_cube(g, "Piazza", B)
    g["seats"][B]["deck"] = ["Gold"] + ["Copper"] * 10
    end_turn(g, A)
    engine._drive(g)
    assert g["turn"] == B
    assert g["seats"][B]["deck"][0] == "Gold", "revealed and put straight back"
    assert g["seats"][B]["in_play"] == []
    assert events(g, "reveal")[-1]["cards"] == ["Gold"]


# ══ CITY GATE ════════════════════════════════════════════════════════════════

def test_city_gate_draws_one_then_topdecks_one():
    g = fresh(landscapes=["City Gate"])
    give_cube(g, "City Gate", B)
    g["seats"][B]["deck"] = ["Gold"] + ["Copper"] * 10
    end_turn(g, A)
    engine._drive(g)
    assert g["turn"] == B
    f = frame(g)
    assert f is not None and f["card"] == "City Gate"
    assert len(g["seats"][B]["hand"]) == 6, "+1 Card first"
    assert decide(g, B, cards=["Gold"])[0]
    assert len(g["seats"][B]["hand"]) == 5
    assert g["seats"][B]["deck"][0] == "Gold"


# ══ SINISTER PLOT ════════════════════════════════════════════════════════════

def test_sinister_plot_banks_tokens_and_cashes_them_for_cards():
    g = fresh(landscapes=["Sinister Plot"])
    give_cube(g, "Sinister Plot", B)
    for pid in (A, B):
        g["seats"][pid]["deck"] = ["Copper"] * 20
    end_turn(g, A)
    engine._drive(g)
    assert sorted(opt_ids(g)) == ["add", "take"]
    assert decide(g, B, ids=["add"])[0]
    assert engine.landscape_tokens(g, "Sinister Plot", B) == 1
    end_turn(g, B)
    end_turn(g, A)
    engine._drive(g)
    assert decide(g, B, ids=["add"])[0]
    assert engine.landscape_tokens(g, "Sinister Plot", B) == 2
    end_turn(g, B)
    end_turn(g, A)
    engine._drive(g)
    hand = len(g["seats"][B]["hand"])
    assert decide(g, B, ids=["take"])[0]
    engine._drive(g)
    assert len(g["seats"][B]["hand"]) == hand + 2
    assert engine.landscape_tokens(g, "Sinister Plot", B) == 0


# ══ EXPLORATION ══════════════════════════════════════════════════════════════

def test_exploration_pays_when_you_gained_nothing_in_your_buy_phase():
    g = fresh(landscapes=["Exploration"])
    give_cube(g, "Exploration", A)
    to_buy(g, A)
    ok, err = mv(g, A, {"type": "end_phase"})
    assert ok, err
    assert g["coffers"].get(A, 0) == 1 and g["villagers"].get(A, 0) == 1


def test_exploration_pays_nothing_when_you_gained_a_card():
    g = fresh(landscapes=["Exploration"])
    give_cube(g, "Exploration", A)
    to_buy(g, A)
    gain(g, A, "Copper")
    ok, err = mv(g, A, {"type": "end_phase"})
    assert ok, err
    assert g["coffers"].get(A, 0) == 0 and g["villagers"].get(A, 0) == 0


def test_exploration_judges_a_second_buy_phase_on_its_own():
    """"If you have several Buy phases due to Villa, Exploration triggers each
    time, checking the Buy phase that just ended.\""""
    g = fresh(landscapes=["Exploration"])
    give_cube(g, "Exploration", A)
    to_buy(g, A)
    gain(g, A, "Copper")
    assert engine.return_to_action_phase(g, A)
    to_buy(g, A)
    ok, err = mv(g, A, {"type": "end_phase"})
    assert ok, err
    assert g["coffers"].get(A, 0) == 1, "the SECOND buy phase gained nothing"


# ══ ROAD NETWORK ═════════════════════════════════════════════════════════════

def test_road_network_draws_for_every_other_owner_on_a_victory_gain():
    g = fresh(players=(A, B, C), landscapes=["Road Network"])
    give_cube(g, "Road Network", B)
    give_cube(g, "Road Network", C)
    for p in (A, B, C):
        g["seats"][p]["hand"] = []
        g["seats"][p]["deck"] = ["Copper"] * 10
    gain(g, A, "Estate")
    assert len(g["seats"][B]["hand"]) == 1
    assert len(g["seats"][C]["hand"]) == 1
    assert len(g["seats"][A]["hand"]) == 0, "'when ANOTHER player gains'"
    gain(g, B, "Estate")
    assert len(g["seats"][B]["hand"]) == 1, "the actor never draws"
    assert len(g["seats"][C]["hand"]) == 2
    gain(g, A, "Silver")
    assert len(g["seats"][C]["hand"]) == 2, "Victory cards only"


# ══ the four kernel-side Projects need no entry from this half ═══════════════

def test_the_four_kernel_side_projects_register_nothing_here():
    """Star Chart, Canal, Capitalism and Fleet are entirely kernel clauses —
    `final_draw`, `cost()`, `types_of`/`autoplay_treasures` and the game-end
    round. A card-code entry for any of them would be a second, disagreeing
    authority."""
    from games.dontminion import effects_renaissance as ren
    for name in ("Star Chart", "Canal", "Capitalism", "Fleet"):
        assert name not in ren.TRIGGERS
        assert name not in ren.LANDSCAPE_FX
        assert not any(k[0] == name for k in ren.STAGES)


def test_no_project_registers_a_landscape_fx():
    """A Project buy runs NO LANDSCAPE_FX — that registry is an Event's
    one-shot buy ability; a Project's ability is ongoing. Asserted over the
    WHOLE table, not just this set's, so a future Project cannot drift."""
    from games.dontminion import effects
    projects = {n for n, d in cards.LANDSCAPES.items() if d["kind"] == "project"}
    assert projects and not (projects & set(effects.LANDSCAPE_FX))
