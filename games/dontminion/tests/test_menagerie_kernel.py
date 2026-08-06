"""KERNEL v10 (phase 10, Menagerie) — the seams, driven against synthetics.

Same 6H/7H/9 discipline: every seam is exercised end to end BEFORE the card
batch that consumes it, so the 30 cards + Horse + 20 Events + 20 Ways land on
paths that were already walked, not paths that merely exist. Where a seam keys
on a REAL name (`Star Chart` for the ph.-9 pick composition, `Way of the Mouse`
for its setup rule) the synthetic uses that name because kernel clauses read
the string; everything else uses invented names so nothing here depends on the
card batch having landed.

The twelve seams:
  * EXILE — a genuinely OWNED public zone (it scores, it joins `owned_cards`
    and both conservation censuses) that sits outside the gain/discard economy
    in ONE direction only, plus the mat's own all-or-nothing when-gain ability,
    which the kernel contributes to the pool on its own behalf (a mat is not a
    card, so it can have no TRIGGERS entry);
  * `add_cards` — the printed "+N Cards" primitive, its `final=` composition
    with ph. 9's Star Chart pick, and the Way of the Chameleon swap in BOTH
    directions with the two seat tokens;
  * WAYS — `would_resolve` consumers offering a two-option prompt, never a
    move, and never buyable;
  * KILN — `before_play` widened to a card of ANY type, so an ordinary
    Treasure play gets the window;
  * WAYFARER — `COST_OVERRIDE`, an ABSOLUTE vector-valued cost that bypasses
    the whole discount stack, with the recursion guard;
  * ANIMAL FAIR — `BUY_PAY_ALT`, an escape inside the affordability check
    itself, read by the enumerator AND the handler;
  * SNOWY VILLAGE — `ignore_actions`, which ph. 9's Villagers obey for free;
  * GOATHERD — `last_turn_trashes`;
  * MASTERMIND — `link_duration` and its transitivity;
  * WAY OF THE MOUSE — `play_mouse_card` and the setup pick;
  * HORSE — a non-Supply pile of 30, included only when a card uses it;
  * SCHEMA 14 and the wire.
"""

import copy

import pytest

from games.dontminion import cards, effects, engine
from games.dontminion.tests.test_soak import _census

A, B, C = "alice", "bob", "carol"
K10 = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room",
       "Gardens", "Market", "Cellar", "Festival"]

# Synthetic landscapes. "Star Chart" and "Way of the Mouse" carry their real
# names because kernel clauses key on the string; the rest are invented.
LS = {
    "Star Chart":       {"kind": "project", "cost": 3, "expansion": "base",
                         "text": "When shuffling, you may pick one of the cards to go on top."},
    "Way of the Mouse": {"kind": "way", "cost": 0, "expansion": "base",
                         "text": "Play the set-aside card, leaving it there."},
    # generic synthetics
    "Way of the Newt":  {"kind": "way", "cost": 0, "expansion": "base",
                         "text": "+2 Cards."},
    "Way of the Toad":  {"kind": "way", "cost": 0, "expansion": "base",
                         "text": "+1 Buy."},
    "Aviary":           {"kind": "project", "cost": 3, "expansion": "base",
                         "text": "When you gain a card, +1 Coffers."},
}


@pytest.fixture
def reg():
    """Temporary registry entries, restored afterwards — mutated in place, the
    test_landscapes rule (engine.py holds references to these objects)."""
    saved = (dict(cards.LANDSCAPES),
             {k: list(v) for k, v in effects.TRIGGERS.items()},
             dict(effects.STAGES), dict(effects.EFFECTS),
             dict(effects.LANDSCAPE_FX),
             dict(getattr(effects, "COST_OVERRIDE", {})),
             dict(getattr(effects, "BUY_PAY_ALT", {})))
    cards.LANDSCAPES.update(copy.deepcopy(LS))
    if not hasattr(effects, "COST_OVERRIDE"):
        effects.COST_OVERRIDE = {}
    if not hasattr(effects, "BUY_PAY_ALT"):
        effects.BUY_PAY_ALT = {}
    yield effects
    for store, old in ((cards.LANDSCAPES, saved[0]),
                       (effects.TRIGGERS, saved[1]),
                       (effects.STAGES, saved[2]),
                       (effects.EFFECTS, saved[3]),
                       (effects.LANDSCAPE_FX, saved[4]),
                       (effects.COST_OVERRIDE, saved[5]),
                       (effects.BUY_PAY_ALT, saved[6])):
        store.clear()
        store.update(old)


def fresh(players=(A, B), seed=42, kingdom=tuple(K10), expansions=("base",),
          landscapes=None):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=None if kingdom is None else list(kingdom),
                           landscapes=landscapes)


def give_cube(g, name, pid):
    g["landscapes"][name]["bought_by"].append(pid)


def give_hand(g, pid, cards_):
    g["seats"][pid]["hand"] = list(cards_)


def frame(g):
    return g["pending"][-1] if g["pending"] else None


def events(g, name):
    return [e for e in g["log"] if e.get("event") == name]


def decide(g, pid, **payload):
    ok, err = engine.apply_move(g, pid, {"type": "decision", **payload})
    assert ok, err
    return ok, err


def pick(g, pid, option_id):
    """Answer the open choose_option by OPTION ID, never by index — the
    no-conditional-skips rule's twin (a guessed index passes for the wrong
    reason the day the option order changes)."""
    fr = frame(g)
    assert fr is not None and fr["kind"] == "choose_option", fr
    ids = [o["id"] for o in fr["constraint"]["options"]]
    assert option_id in ids, ids
    return decide(g, pid, ids=[option_id])


# ── EXILE: the zone ───────────────────────────────────────────────────────────

def test_exile_moves_cards_out_of_a_zone_and_emits_one_batch():
    g = fresh()
    give_hand(g, A, ["Copper", "Estate", "Copper"])
    seen = []
    engine.add_watcher(g, A, "Moat", "exile", stage=None)
    moved = engine.exile(g, A, ["Copper", "Copper"])
    assert moved == ["Copper", "Copper"]
    assert g["seats"][A]["exile"] == ["Copper", "Copper"]
    assert g["seats"][A]["hand"] == ["Estate"]
    e = events(g, "exile")[-1]
    assert e["cards"] == ["Copper", "Copper"] and e["source"] == "hand"
    del seen


def test_exile_ignores_a_card_that_is_not_there():
    g = fresh()
    give_hand(g, A, ["Copper"])
    assert engine.exile(g, A, ["Province"]) == []
    assert g["seats"][A]["exile"] == []
    assert not events(g, "exile")          # nothing moved, nothing logged


def test_exiling_from_the_supply_takes_the_pile_top_and_is_NOT_a_gain(reg):
    """"Exiling cards from the Supply is not considered gaining cards" — the
    `exchange` discipline: a gain emit here would fire every when-gain watcher
    in the game for a card nobody gained."""
    fired = []
    reg.TRIGGERS["Aviary"] = [{"on": "gain", "from": "landscape",
                               "stage": "take", "commutes": True}]
    reg.STAGES[("Aviary", "take")] = lambda game, pid, fr, ch: fired.append(pid)
    g = fresh(landscapes=["Aviary"])
    give_cube(g, "Aviary", A)
    before = engine.pile_count(g, "Silver")
    assert engine.exile(g, A, ["Silver"], zone="supply") == ["Silver"]
    engine._drive(g)
    assert engine.pile_count(g, "Silver") == before - 1
    assert g["seats"][A]["exile"] == ["Silver"]
    assert fired == []                     # NOT a gain
    assert not events(g, "gain")
    # ...and the control: a real gain DOES fire it, so the assertion above is
    # not passing because the trigger is simply broken.
    engine.gain(g, A, "Silver")
    engine._drive(g)
    assert fired == [A]


def test_exiling_from_an_empty_supply_pile_moves_nothing():
    g = fresh()
    g["supply"]["Curse"] = 0
    assert engine.exile(g, A, ["Curse"], zone="supply") == []
    assert g["seats"][A]["exile"] == []


def test_a_gain_may_land_directly_on_the_exile_mat():
    g = fresh()
    assert engine.gain(g, A, "Silver", dest="exile")
    assert g["seats"][A]["exile"] == ["Silver"]
    assert events(g, "gain")[-1]["dest"] == "exile"


def test_discarding_from_exile_is_a_real_discard_for_triggers(reg):
    """Only the INBOUND direction is exempt from the gain/discard economy:
    "when you discard cards from your Exile mat, when-discard abilities such as
    Faithful Hound, Trail, Tunnel, Village Green and Weaver trigger"."""
    saw = []
    engine.add_watcher(g0 := fresh(), A, "Moat", "discard", stage="note")
    reg.STAGES[("Moat", "note")] = lambda game, pid, fr, ch: saw.append(
        fr["data"]["subject"])
    g0["seats"][A]["exile"] = ["Estate", "Estate"]
    engine.discard_from_exile(g0, A, ["Estate"])
    engine._drive(g0)
    assert g0["seats"][A]["exile"] == ["Estate"]
    assert g0["seats"][A]["discard"] == ["Estate"]
    assert saw == ["Estate"]


def test_the_exile_mat_is_an_owned_zone_that_scores():
    g = fresh()
    g["seats"][A]["exile"] = ["Province", "Estate"]
    owned = engine.owned_cards(g, A)
    assert owned.count("Province") == 1 and owned.count("Estate") == 4
    engine._post_move(g)
    assert g["vp"][A] == 3 + 6 + 1          # 3 starting Estates + Province + Estate


def test_the_exile_mat_is_public_on_the_wire():
    """Ch. II lists "all cards you have set aside face up (including on any
    player mats)" as open information, and the Exile mat is face up."""
    g = fresh()
    g["seats"][B]["exile"] = ["Province"]
    view = engine.player_view(g, A)
    assert view["seats"][B]["exile"] == ["Province"]
    assert "hand" not in view["seats"][B] or view["seats"][B].get("hand") is None


def test_the_exile_mat_is_counted_by_the_conservation_census():
    """A zone missing from `_census` or from `owned_cards` goes unseen, and the
    soak would report cards vanishing the first time a card Exiles one. The two
    are the same claim asked from opposite ends — assert BOTH."""
    g = fresh()
    before = _census(g)
    engine.exile(g, A, ["Silver"], zone="supply")
    # CONSERVATION: the card left the pile and arrived on the mat, so the total
    # must not move. Without "exile" in the zone tuple the Silver simply
    # vanishes and every Menagerie soak fails on a card the game still has.
    assert _census(g) == before
    assert "Silver" in engine.owned_cards(g, A)


# ── EXILE: the mat's own ability ──────────────────────────────────────────────

def test_the_mats_ability_is_offered_on_a_gain_and_is_all_or_nothing():
    """"When you gain a card, you may discard any number of copies of it from
    your Exile mat" — but "you can't choose to just discard some of them", so
    it is a yes/no, never a choose_cards."""
    g = fresh()
    g["seats"][A]["exile"] = ["Silver", "Silver", "Estate"]
    engine.gain(g, A, "Silver")
    engine._drive(g)
    fr = frame(g)
    assert fr["kind"] == "choose_option" and fr["card"] == "__exile"
    assert [o["id"] for o in fr["constraint"]["options"]] == ["yes", "no"]
    pick(g, A, "yes")
    engine._drive(g)
    # BOTH copies went, and the gained one (in the discard) was never on the mat
    assert g["seats"][A]["exile"] == ["Estate"]
    assert g["seats"][A]["discard"].count("Silver") == 3


def test_the_mats_ability_may_be_declined_and_keeps_them_exiled():
    g = fresh()
    g["seats"][A]["exile"] = ["Silver", "Silver"]
    engine.gain(g, A, "Silver")
    engine._drive(g)
    pick(g, A, "no")
    engine._drive(g)
    assert g["seats"][A]["exile"] == ["Silver", "Silver"]


def test_the_mats_ability_is_not_offered_without_a_copy_on_the_mat():
    """The control that makes the two tests above non-vacuous — and the
    "OTHER copies" boundary (Gatekeeper 6): it counts what is ON THE MAT and
    never the card just gained."""
    g = fresh()
    g["seats"][A]["exile"] = ["Estate"]
    engine.gain(g, A, "Silver")
    engine._drive(g)
    assert g["pending"] == []
    assert g["seats"][A]["exile"] == ["Estate"]


def test_the_mats_ability_is_ordered_against_a_card_trigger_in_one_pool(reg):
    """A mat is not a card and can have no TRIGGERS entry, so the kernel
    contributes on its own behalf — but the ability is CONCURRENT with
    everything else the gain triggered (ch. VI lists it beside Watchtower,
    Sheepdog and Sleigh), so it must arrive through the POOL."""
    reg.TRIGGERS["Aviary"] = [{"on": "gain", "from": "landscape", "stage": "take"}]
    reg.STAGES[("Aviary", "take")] = \
        lambda game, pid, fr, ch: engine.add_coffers(game, 1, pid)
    g = fresh(landscapes=["Aviary"])
    give_cube(g, "Aviary", A)
    g["seats"][A]["exile"] = ["Silver"]
    engine.gain(g, A, "Silver")
    engine._drive(g)
    fr = frame(g)
    assert fr["kind"] == "choose_option" and fr["card"] == "__abilities"
    assert len(fr["constraint"]["options"]) == 2


def test_the_mats_ability_no_ops_when_an_earlier_pick_already_moved_them(reg):
    """The pool is collected before anything resolves, so a second consumer can
    find the mat already empty. It must no-op, not crash (the B11 shape)."""
    g = fresh()
    g["seats"][A]["exile"] = ["Silver"]
    engine.gain(g, A, "Silver")
    engine._drive(g)
    g["seats"][A]["exile"] = []            # something else took them
    pick(g, A, "yes")
    engine._drive(g)
    assert g["seats"][A]["exile"] == []


# ── add_cards: the printed +N Cards primitive ─────────────────────────────────

def test_add_cards_draws_and_returns_the_cards():
    g = fresh()
    g["seats"][A]["deck"] = ["Gold", "Silver", "Copper"]
    give_hand(g, A, [])
    assert engine.add_cards(g, 2) == ["Gold", "Silver"]
    assert g["seats"][A]["hand"] == ["Gold", "Silver"]
    assert engine.add_cards(g, 0) == [] and engine.add_cards(g, -1) == []


def test_add_cards_draws_off_turn_because_drawing_is_not_a_pool():
    """A Caravan Guard reaction draws on someone else's turn — drawing is not a
    per-turn POOL, which is why this does not go through `_grant`."""
    g = fresh()
    g["turn"] = A
    g["seats"][B]["deck"] = ["Gold"]
    assert engine.add_cards(g, 1, B) == ["Gold"]
    assert "Gold" in g["seats"][B]["hand"]


def test_a_final_plus_cards_offers_the_star_chart_pick(reg):
    g = fresh(landscapes=["Star Chart"])
    give_cube(g, "Star Chart", A)
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = ["Gold", "Silver"]
    give_hand(g, A, [])
    engine.add_cards(g, 2, final=True)
    fr = frame(g)
    assert fr is not None and fr["card"] == "Star Chart"
    decide(g, A, cards=["Gold"])
    engine._drive(g)
    assert g["seats"][A]["hand"][0] == "Gold"


def test_a_non_final_plus_cards_never_offers_the_pick(reg):
    """The control: `final=` is what distinguishes them, so a plain +Cards on
    the same board must shuffle uniformly."""
    g = fresh(landscapes=["Star Chart"])
    give_cube(g, "Star Chart", A)
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = ["Gold", "Silver"]
    give_hand(g, A, [])
    engine.add_cards(g, 2)
    assert g["pending"] == []
    assert len(g["seats"][A]["hand"]) == 2


# ── add_cards: the Way of the Chameleon swap ─────────────────────────────────

def test_the_chameleon_turns_a_printed_plus_cards_into_coins():
    g = fresh()
    g["turn_ctx"]["chameleon"] = True
    g["seats"][A]["deck"] = ["Gold", "Silver"]
    give_hand(g, A, [])
    assert engine.add_cards(g, 2) == []
    assert g["coins"] == 2
    assert g["seats"][A]["hand"] == []      # nothing drawn at all
    assert events(g, "chameleon_swap")[-1] == \
        {**events(g, "chameleon_swap")[-1], "got": "coins", "count": 2}


def test_the_chameleon_turns_a_printed_plus_coins_into_cards():
    """"…and vice versa (keeping their values)"."""
    g = fresh()
    g["turn_ctx"]["chameleon"] = True
    g["seats"][A]["deck"] = ["Gold", "Silver", "Copper"]
    give_hand(g, A, [])
    engine.add_coins(g, 2)
    assert g["coins"] == 0
    assert g["seats"][A]["hand"] == ["Gold", "Silver"]
    assert events(g, "chameleon_swap")[-1]["got"] == "cards"


def test_the_chameleon_leaves_a_NEGATIVE_plus_coins_alone():
    """"−$, as on Poor House or Souk, is not changed by this Way"."""
    g = fresh()
    g["turn_ctx"]["chameleon"] = True
    g["coins"] = 5
    engine.add_coins(g, -2)
    assert g["coins"] == 3
    assert not events(g, "chameleon_swap")


def test_a_plain_draw_is_untouched_by_the_chameleon():
    """"Only card drawing denoted with '+' is changed to +$. For instance
    'draw 2 cards' is unchanged" — which is the entire reason `add_cards`
    exists as a separate primitive."""
    g = fresh()
    g["turn_ctx"]["chameleon"] = True
    g["seats"][A]["deck"] = ["Gold", "Silver"]
    give_hand(g, A, [])
    engine.draw(g, A, 2)
    assert g["seats"][A]["hand"] == ["Gold", "Silver"] and g["coins"] == 0


def test_a_swapped_plus_cards_draws_nothing_so_final_needs_no_pick(reg):
    """The order inside `add_cards` matters: the swap is checked first, because
    a swapped +Cards can cause no shuffle and so needs no Star Chart pick."""
    g = fresh(landscapes=["Star Chart"])
    give_cube(g, "Star Chart", A)
    g["turn_ctx"]["chameleon"] = True
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = ["Gold", "Silver"]
    give_hand(g, A, [])
    engine.add_cards(g, 2, final=True)
    assert g["pending"] == []
    assert g["coins"] == 2 and g["seats"][A]["discard"] == ["Gold", "Silver"]


def test_the_minus_coin_token_eats_a_swapped_plus_cards():
    """"A Militia gives +2 Cards and will trigger your −1 Card token but not
    your −$ token" — read the other way for a card that printed +$: the token
    applies to the RESULT of the swap."""
    g = fresh()
    g["turn_ctx"]["chameleon"] = True
    g["seats"][A]["tokens"]["-coin"] = True
    engine.add_cards(g, 2)
    assert g["coins"] == 1
    assert not g["seats"][A]["tokens"].get("-coin")


def test_the_minus_card_token_eats_a_swapped_plus_coins():
    g = fresh()
    g["turn_ctx"]["chameleon"] = True
    g["seats"][A]["tokens"]["-card"] = True
    g["seats"][A]["deck"] = ["Gold", "Silver"]
    give_hand(g, A, [])
    engine.add_coins(g, 2)
    assert g["seats"][A]["hand"] == ["Gold"]
    assert not g["seats"][A]["tokens"].get("-card")


def test_the_chameleon_binds_the_turn_player_only():
    """A swapped +Cards becomes +$, and $ off-turn evaporates by rule — so an
    opponent's reaction draw must stay a draw."""
    g = fresh()
    g["turn"] = A
    g["turn_ctx"]["chameleon"] = True
    g["seats"][B]["deck"] = ["Gold"]
    assert engine.add_cards(g, 1, B) == ["Gold"]


# ── WAYS ──────────────────────────────────────────────────────────────────────

def way_board(reg, way="Way of the Newt", ability=None):
    """A board with one synthetic Way whose would_resolve stage offers it."""
    reg.TRIGGERS[way] = [{"on": "would_resolve", "from": "landscape",
                          "stage": "offer"}]
    reg.STAGES[(way, "offer")] = lambda game, pid, fr, ch: engine.push_way_offer(
        game, pid, way, fr["data"]["subject"], "do")
    reg.STAGES[(way, "do")] = ability or (
        lambda game, pid, fr, ch: engine.add_buys(game, 1))
    g = fresh(landscapes=[way])
    give_hand(g, A, ["Smithy", "Copper", "Copper", "Copper", "Copper"])
    g["seats"][A]["deck"] = ["Gold"] * 5
    return g


def test_a_way_offers_a_two_option_prompt_on_every_action_play(reg):
    g = way_board(reg)
    ok, err = engine.apply_move(g, A, {"type": "play_action", "card": "Smithy"})
    assert ok, err
    fr = frame(g)
    assert fr["kind"] == "choose_option" and fr["card"] == "Way of the Newt"
    assert [o["id"] for o in fr["constraint"]["options"]] == ["normal", "way"]


def test_declining_the_way_runs_the_printed_ability(reg):
    g = way_board(reg)
    engine.apply_move(g, A, {"type": "play_action", "card": "Smithy"})
    pick(g, A, "normal")
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 4 + 3      # Smithy left hand, +3 Cards
    assert g["buys"] == 1
    assert not events(g, "way")


def test_picking_the_way_replaces_the_ability_but_the_card_is_still_played(reg):
    """"You just resolve the Way instead" — the card still counts as PLAYED, is
    in play, bumped `actions_played`, and its after-play abilities still fire."""
    g = way_board(reg)
    engine.apply_move(g, A, {"type": "play_action", "card": "Smithy"})
    pick(g, A, "way")
    engine._drive(g)
    assert len(g["seats"][A]["hand"]) == 4         # no +3 Cards
    assert g["buys"] == 2                          # the Way's ability ran
    assert g["seats"][A]["in_play"] == ["Smithy"]
    assert g["turn_ctx"]["actions_played"] == 1
    e = events(g, "way")[-1]
    assert e["name"] == "Way of the Newt" and e["card"] == "Smithy"


def test_a_wayed_action_still_fires_its_after_play_abilities(reg):
    """"After-play abilities such as Coin of the Realm, Royal Carriage, Citadel
    or Flagship still trigger after you play an Enchanted Action card"."""
    seen = []
    reg.TRIGGERS["Aviary"] = [{"on": "action_resolved", "from": "landscape",
                               "stage": "note", "commutes": True}]
    reg.STAGES[("Aviary", "note")] = lambda game, pid, fr, ch: seen.append(
        fr["data"]["subject"])
    g = way_board(reg)
    cards.LANDSCAPES["Aviary"] = copy.deepcopy(LS["Aviary"])
    g["landscapes"]["Aviary"] = {"kind": "project", "bought_turn": {},
                                 "bought_by": [A]}
    engine.apply_move(g, A, {"type": "play_action", "card": "Smithy"})
    pick(g, A, "way")
    engine._drive(g)
    assert seen == ["Smithy"]


def test_a_way_is_not_buyable_and_grows_no_move(reg):
    """Ways are not in BUYABLE_LANDSCAPE_KINDS, and the offer is a trigger, not
    a `legal_moves` entry — the move surface does not grow."""
    g = way_board(reg)
    g["phase"] = "buy"
    g["coins"] = 20
    assert engine.landscape_gate(g, A, "Way of the Newt")
    ok, _ = engine.apply_move(g, A, {"type": "buy_landscape",
                                     "name": "Way of the Newt"})
    assert not ok
    assert not any(m.get("type") == "buy_landscape"
                   for m in engine.legal_moves(g, A))


def test_two_ways_on_one_play_are_ordered_in_the_pool(reg):
    """A Way is a would_resolve consumer like an Enchantress, so several on one
    occurrence are the player's ordering choice — not a fixed sequence."""
    g = way_board(reg)
    reg.TRIGGERS["Way of the Toad"] = [{"on": "would_resolve", "from": "landscape",
                                        "stage": "offer"}]
    reg.STAGES[("Way of the Toad", "offer")] = \
        lambda game, pid, fr, ch: engine.push_way_offer(
            game, pid, "Way of the Toad", fr["data"]["subject"], "do")
    reg.STAGES[("Way of the Toad", "do")] = \
        lambda game, pid, fr, ch: engine.add_coins(game, 3)
    g["landscapes"]["Way of the Toad"] = {"kind": "way", "bought_turn": {},
                                          "bought_by": []}
    engine.apply_move(g, A, {"type": "play_action", "card": "Smithy"})
    fr = frame(g)
    assert fr["card"] == "__abilities" and len(fr["constraint"]["options"]) == 2


def test_a_board_with_no_way_leaves_an_action_play_untouched(reg):
    """The would_resolve gate only parks when the emit actually collects a
    consumer, so an ordinary board is byte-identical to before."""
    g = fresh()
    give_hand(g, A, ["Smithy"])
    g["seats"][A]["deck"] = ["Gold"] * 5
    ok, err = engine.apply_move(g, A, {"type": "play_action", "card": "Smithy"})
    assert ok, err
    assert g["pending"] == []
    assert len(g["seats"][A]["hand"]) == 3


# ── KILN: before_play widened to a card of ANY type ───────────────────────────

def test_a_before_play_consumer_parks_an_ordinary_treasure_play(reg):
    """Kiln's "the next time you play a card this turn" is a card of ANY type,
    so a Treasure play needs the window — and it needs the same CONDITIONAL
    parking, because the coins run inline and a pool parked in front of them
    would resolve after them, i.e. backwards."""
    order = []
    reg.TRIGGERS["Aviary"] = [{"on": "before_play", "from": "landscape",
                               "stage": "kiln"}]

    def _kiln(game, pid, fr, ch):
        order.append(("kiln", game["coins"]))
        engine.gain(game, pid, "Silver")
    reg.STAGES[("Aviary", "kiln")] = _kiln
    g = fresh(landscapes=["Aviary"])
    give_cube(g, "Aviary", A)
    give_hand(g, A, ["Copper"])
    g["phase"] = "buy"
    ok, err = engine.apply_move(g, A, {"type": "play_treasure", "card": "Copper"})
    assert ok, err
    engine._drive(g)
    # the consumer saw $0 — it resolved BEFORE the Copper's own coins
    assert order == [("kiln", 0)]
    assert g["coins"] == 1
    assert g["seats"][A]["in_play"] == ["Copper"]
    assert "Silver" in g["seats"][A]["discard"]


def test_the_treasure_play_emit_still_fires_after_a_parked_play(reg):
    seen = []
    reg.TRIGGERS["Aviary"] = [{"on": "before_play", "from": "landscape",
                               "stage": "kiln", "commutes": True}]
    reg.STAGES[("Aviary", "kiln")] = lambda game, pid, fr, ch: None
    reg.TRIGGERS["Star Chart"] = [{"on": "play_treasure", "from": "landscape",
                                   "stage": "note", "commutes": True}]
    reg.STAGES[("Star Chart", "note")] = \
        lambda game, pid, fr, ch: seen.append(fr["data"]["subject"])
    g = fresh(landscapes=["Aviary", "Star Chart"])
    give_cube(g, "Aviary", A)
    give_cube(g, "Star Chart", A)
    give_hand(g, A, ["Copper"])
    g["phase"] = "buy"
    engine.apply_move(g, A, {"type": "play_treasure", "card": "Copper"})
    engine._drive(g)
    assert seen == ["Copper"]


def test_a_treasure_play_with_no_consumer_runs_inline(reg):
    g = fresh()
    give_hand(g, A, ["Copper"])
    g["phase"] = "buy"
    engine.apply_move(g, A, {"type": "play_treasure", "card": "Copper"})
    assert g["pending"] == [] and g["coins"] == 1


# ── WAYFARER: COST_OVERRIDE ───────────────────────────────────────────────────

def test_a_cost_override_replaces_the_whole_calculation(reg):
    """"Cost reduction only affects Wayfarer's default cost of $6. If Wayfarer
    is copying the cost of another card, only cost reduction ON THAT CARD
    applies (which Wayfarer would copy), not cost reduction on Wayfarer
    itself." — so it bypasses bridges, Quarry, Canal and every COST_MODS."""
    reg.COST_OVERRIDE["Gardens"] = lambda game: {"coins": 5, "potions": 0, "debt": 0}
    g = fresh()
    g["turn_ctx"]["bridges"] = 2
    assert engine.cost(g, "Gardens") == 5           # NOT 5 - 2
    assert engine.cost(g, "Estate") == 0            # ...and everything else is reduced


def test_a_cost_override_of_none_falls_back_to_the_normal_path(reg):
    reg.COST_OVERRIDE["Gardens"] = lambda game: None
    g = fresh()
    g["turn_ctx"]["bridges"] = 1
    assert engine.cost(g, "Gardens") == 3           # printed $4, reduced


def test_a_cost_override_is_a_VECTOR(reg):
    """"Wayfarer can have a cost with Potion or Debt in it"."""
    reg.COST_OVERRIDE["Gardens"] = lambda game: {"coins": 3, "potions": 1, "debt": 2}
    g = fresh()
    assert engine.cost(g, "Gardens") == 3
    assert engine.potion_cost(g, "Gardens") == 1
    assert engine.debt_cost(g, "Gardens") == 2


def test_a_cost_override_that_asks_about_itself_falls_through(reg):
    """Wayfarer copying a Destrier asks `cost()` again — the re-entry flag makes
    an override that asks about itself use the printed path rather than loop."""
    reg.COST_OVERRIDE["Gardens"] = \
        lambda game: {"coins": engine.cost(game, "Gardens"), "potions": 0, "debt": 0}
    g = fresh()
    assert engine.cost(g, "Gardens") == 4           # the printed cost, no recursion
    assert not g.get("_cost_over")                  # and the flag is cleaned up


def test_a_cost_override_reaches_the_comparators_and_the_buy(reg):
    reg.COST_OVERRIDE["Gardens"] = lambda game: {"coins": 2, "potions": 0, "debt": 0}
    g = fresh()
    assert engine.cost_le(g, "Gardens", 2) and not engine.cost_le(g, "Gardens", 1)
    assert engine.cost_lt(g, "Gardens", 3)
    g["phase"] = "buy"
    g["coins"] = 2
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Gardens"})
    assert ok, err
    assert g["coins"] == 0


# ── ANIMAL FAIR: BUY_PAY_ALT ──────────────────────────────────────────────────

def pay_alt_board(reg, pile="Gardens"):
    def _stage(game, pid, fr, ch):
        if ch["ids"][0] == "pay":
            game["coins"] -= fr["data"]["cost"]
        else:
            engine.trash(game, pid, ["Smithy"])
    reg.BUY_PAY_ALT[pile] = {
        "avail": lambda game, pid: "Smithy" in game["seats"][pid]["hand"],
        "label": "Trash an Action card from your hand",
        "stage": "pay_alt"}
    reg.STAGES[(pile, "pay_alt")] = _stage
    g = fresh()
    g["phase"] = "buy"
    return g


def test_the_pay_alt_escape_makes_an_unaffordable_card_buyable(reg):
    g = pay_alt_board(reg)
    give_hand(g, A, ["Smithy"])
    g["coins"] = 0
    assert engine.buy_pay_alt(g, A, "Gardens") is not None
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Gardens"})
    assert ok, err
    # ...and the escape is offered ALONE, since $0 cannot pay the $4
    fr = frame(g)
    assert [o["id"] for o in fr["constraint"]["options"]] == ["alt"]
    pick(g, A, "alt")
    engine._drive(g)
    assert g["trash"] == ["Smithy"]
    assert "Gardens" in g["seats"][A]["discard"]
    assert g["buys"] == 0 and g["coins"] == 0


def test_the_pay_alt_is_a_real_choice_even_when_you_could_pay(reg):
    """"You MAY choose to either pay its cost (if you have $7) or trash an
    Action card from your hand"."""
    g = pay_alt_board(reg)
    give_hand(g, A, ["Smithy"])
    g["coins"] = 4
    engine.apply_move(g, A, {"type": "buy", "card": "Gardens"})
    fr = frame(g)
    assert [o["id"] for o in fr["constraint"]["options"]] == ["pay", "alt"]
    pick(g, A, "pay")
    engine._drive(g)
    assert g["coins"] == 0 and g["trash"] == []


def test_the_enumerator_and_the_handler_agree_on_the_pay_alt(reg):
    """An enumerator and a handler that disagree hand the bot a move that does
    nothing (the play_all_treasures livelock)."""
    g = pay_alt_board(reg)
    give_hand(g, A, ["Smithy"])
    g["coins"] = 0
    assert {"type": "buy", "card": "Gardens"} in engine.legal_moves(g, A)
    # ...and without the escape available, NEITHER offers it
    give_hand(g, A, ["Copper"])
    assert engine.buy_pay_alt(g, A, "Gardens") is None
    assert {"type": "buy", "card": "Gardens"} not in engine.legal_moves(g, A)
    ok, _ = engine.apply_move(g, A, {"type": "buy", "card": "Gardens"})
    assert not ok


def test_the_alt_payment_runs_before_the_when_buy_abilities(reg):
    """"If you buy it by trashing a card, the trashing happens before any
    when-buy abilities"."""
    order = []
    g = pay_alt_board(reg)
    reg.TRIGGERS["Gardens"] = [{"on": "gain", "from": "self", "stage": "note"}]
    reg.STAGES[("Gardens", "note")] = \
        lambda game, pid, fr, ch: order.append(("gain", list(game["trash"])))
    give_hand(g, A, ["Smithy"])
    g["coins"] = 0
    engine.apply_move(g, A, {"type": "buy", "card": "Gardens"})
    pick(g, A, "alt")
    engine._drive(g)
    assert order == [("gain", ["Smithy"])]


# ── SNOWY VILLAGE: ignore_actions ─────────────────────────────────────────────

def test_ignore_actions_drops_further_plus_actions_and_says_so():
    """"Ignore any further +Actions you get this turn" — the grant is DROPPED,
    not zeroed later, so a Village played after it gives nothing. And it is
    never silent (the lose-track discipline)."""
    g = fresh()
    g["turn_ctx"]["ignore_actions"] = True
    before = g["actions"]
    engine.add_actions(g, 2)
    assert g["actions"] == before
    assert events(g, "actions_ignored")[-1]["count"] == 2


def test_ignore_actions_eats_a_spent_villager():
    """Spending a Villager is "+1 Action" and routes through `add_actions`, so
    ph. 9's Villagers obey this for free — the payoff for that routing."""
    g = fresh()
    g["villagers"][A] = 1
    g["turn_ctx"]["ignore_actions"] = True
    before = g["actions"]
    ok, err = engine.apply_move(g, A, {"type": "spend", "what": "villagers", "n": 1})
    assert ok, err
    assert g["actions"] == before and g["villagers"][A] == 0


def test_ignore_actions_binds_the_turn_player_only():
    g = fresh()
    g["turn"] = A
    g["turn_ctx"]["ignore_actions"] = True
    engine.add_actions(g, 2, B)            # an off-turn bonus evaporates anyway
    assert events(g, "off_turn_bonus")
    assert not events(g, "actions_ignored")


def test_ignore_actions_does_not_survive_the_turn():
    g = fresh()
    g["turn_ctx"]["ignore_actions"] = True
    engine._end_turn(g, A)
    engine._drive(g)
    assert g["turn_ctx"]["ignore_actions"] is False


# ── GOATHERD: last_turn_trashes ───────────────────────────────────────────────

def test_last_turn_trashes_records_the_count_at_the_end_of_the_turn():
    """"+1 Card per card the player to your right trashed on their last turn" —
    a COUNT, because that is all the card asks."""
    g = fresh()
    give_hand(g, A, ["Copper", "Estate"])
    engine.trash(g, A, ["Copper", "Estate"])
    engine._drive(g)
    assert g["turn_ctx"]["trashes"] == 2
    assert g["last_turn_trashes"].get(A, 0) == 0     # not yet — the turn is live
    engine._end_turn(g, A)
    engine._drive(g)
    assert g["last_turn_trashes"][A] == 2
    assert g["turn_ctx"]["trashes"] == 0             # the new turn starts fresh


def test_last_turn_trashes_counts_the_turn_not_the_trasher():
    """Counted for the TURN PLAYER's turn regardless of who trashed — that is
    whose turn it was (a Swindler trashes off the victim's deck on YOUR turn)."""
    g = fresh()
    g["turn"] = A
    g["seats"][B]["hand"] = ["Copper"]
    engine.trash(g, B, ["Copper"])
    engine._drive(g)
    engine._end_turn(g, A)
    engine._drive(g)
    assert g["last_turn_trashes"][A] == 1


# ── MASTERMIND: link_duration ─────────────────────────────────────────────────

def dur_entry(g, pid, card):
    lst = engine._dur_setup_list(g, pid)
    lst.append({"card": card, "fx": [], "watchers": 0, "riders": []})
    return [pid, len(lst) - 1]


def test_link_duration_makes_the_linking_card_ride_the_host():
    """"If the card is a Duration, Mastermind stays in play as long as that
    Duration stays in play"."""
    g = fresh()
    h = dur_entry(g, A, "Caravan")
    assert engine.link_duration(g, A, "Throne Room", h)
    assert engine._dur_setup_list(g, A)[h[1]]["riders"] == ["Throne Room"]
    # idempotent — linking twice does not double the rider
    engine.link_duration(g, A, "Throne Room", h)
    assert engine._dur_setup_list(g, A)[h[1]]["riders"] == ["Throne Room"]


def test_link_duration_refuses_a_handle_that_names_nothing():
    g = fresh()
    assert not engine.link_duration(g, A, "Throne Room", None)
    assert not engine.link_duration(g, A, "Throne Room", [A, 7])


def test_link_duration_is_transitive():
    """"If you Mastermind another Mastermind… if next turn you use the second
    Mastermind on another Duration, BOTH Masterminds stay in play as long as
    that Duration does." — each link copies the riders it already carries onto
    the new host, so a chain collapses onto whichever entry is alive."""
    g = fresh()
    first = dur_entry(g, A, "Mastermind")
    engine.link_duration(g, A, "Throne Room", first)     # TR rides Mastermind #1
    second = dur_entry(g, A, "Caravan")
    engine.link_duration(g, A, "Mastermind", second)     # #1 now rides the Caravan
    riders = engine._dur_setup_list(g, A)[second[1]]["riders"]
    assert set(riders) == {"Mastermind", "Throne Room"}


# ── WAY OF THE MOUSE: play_mouse_card + setup ────────────────────────────────

def test_play_mouse_card_runs_the_ability_and_leaves_the_card():
    """The third member of ch. VI's PLAY A CARD WHILE LEAVING IT family."""
    g = fresh()
    g["mouse_card"] = "Village"
    give_hand(g, A, [])
    g["seats"][A]["deck"] = ["Gold"]
    before = g["actions"]
    assert engine.play_mouse_card(g, A)
    engine._drive(g)
    assert g["seats"][A]["hand"] == ["Gold"]         # Village's +1 Card ran
    assert g["actions"] == before + 2                # ...and its +2 Actions
    assert g["mouse_card"] == "Village"              # left where it was
    assert "Village" not in g["seats"][A]["in_play"]
    assert g["turn_ctx"]["actions_played"] == 1
    assert events(g, "play_mouse")[-1]["card"] == "Village"


def test_play_mouse_card_with_no_card_set_aside_does_nothing():
    g = fresh()
    assert not engine.play_mouse_card(g, A)
    assert not events(g, "play_mouse")


def test_the_mouse_card_is_only_chosen_when_the_way_is_dealt(reg):
    g = fresh(landscapes=["Way of the Newt"])
    assert g["mouse_card"] is None
    g2 = fresh(landscapes=["Way of the Mouse"])
    assert g2["mouse_card"] is not None


def test_the_mouse_card_is_an_undealt_action_costing_2_or_3_and_never_a_duration(reg):
    """"Set aside an unused Action Kingdom card costing $2 or $3." The 2025
    errata adds NON-DURATION, which ch. I's setup section was never updated for
    — the card and ch. VII win."""
    seen = set()
    for seed in range(40):
        g = fresh(seed=seed, kingdom=None, expansions=("base", "seaside"),
                  landscapes=["Way of the Mouse"])
        m = g["mouse_card"]
        if m is None:
            continue                       # no eligible undealt card this board
        seen.add(m)
        assert m not in g["kingdom"]
        assert cards.printed_cost(m) in (2, 3)
        assert "action" in cards.CARDS[m]["types"]
        assert "duration" not in cards.CARDS[m]["types"]
    assert seen, "no board produced a Mouse card — the sampling proved nothing"


# ── HORSE: a non-Supply pile ─────────────────────────────────────────────────

def test_the_horse_pile_is_absent_when_no_card_uses_it():
    g = fresh()
    assert "Horse" not in g["piles"]
    assert "Horse" not in g["supply"] and "Horse" not in g["nonsupply"]


def test_the_horse_pile_joins_outside_the_supply_when_a_card_uses_it(monkeypatch):
    """"If any card in the Supply uses Horses, include the Horse pile (30
    cards) OUTSIDE the Supply" — so it is never buyable and never counts toward
    the three-empty-piles end, both free from ph. 3H's non-Supply index.

    The Horse CARD lands with the batch, so it is synthesised here — the same
    invented-data idiom this whole file uses, and it drives the real setup
    clause in `new_game` rather than a stand-in for it."""
    monkeypatch.setitem(cards.CARDS, "Horse",
                        {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "+2 Cards, +1 Action. Return this to the Horse pile.",
                         "expansion": "base", "kingdom": False})
    monkeypatch.setattr(engine, "cards_uses_horses", lambda c: c == "Smithy")
    g = fresh()
    assert engine.pile_count(g, "Horse") == cards.HORSE_PILE == 30
    assert "Horse" not in g["supply"] and g["nonsupply"]["Horse"] == 30
    assert not engine.is_supply_pile(g, "Horse")
    g["nonsupply"]["Horse"] = 0
    assert engine.count_empty_piles(g) == 0
    g["phase"] = "buy"
    g["coins"] = 20
    ok, _ = engine.apply_move(g, A, {"type": "buy", "card": "Horse"})
    assert not ok


# ── SCHEMA 14 + the wire ─────────────────────────────────────────────────────

def test_schema_is_14_and_the_new_keys_are_filled_unconditionally():
    """A fill is idempotent, so it can never be wrong — and a version-gated one
    skips the prod blobs written under an earlier stamp (the ph.-8 lesson)."""
    assert engine.SCHEMA == 14
    g = fresh()
    for key in ("last_turn_trashes", "mouse_card"):
        assert key in g
        del g[key]
    del g["seats"][A]["exile"]
    g["schema"] = 1
    engine.migrate(g)
    assert g["last_turn_trashes"] == {} and g["mouse_card"] is None
    assert g["seats"][A]["exile"] == []
    assert g["schema"] == 14


def test_the_new_game_keys_are_json_safe(reg):
    g = fresh(landscapes=["Way of the Mouse"])
    g["seats"][A]["exile"] = ["Silver"]
    import json
    json.dumps(engine.player_view(g, A))
    json.dumps(g, default=str)
