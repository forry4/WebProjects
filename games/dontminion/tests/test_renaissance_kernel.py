"""KERNEL v9 (phase 9, Renaissance) — the seams, driven against synthetics.

The 6H/7H discipline: every seam is exercised end to end BEFORE the card batch
that consumes it, so the 25 cards + 20 Projects + 5 Artifacts land on paths
that were already walked, not paths that merely exist. Where a seam keys on a
REAL name ("Canal", "Capitalism", "Star Chart", "Fleet" — kernel clauses read
those strings), the synthetic landscape uses the real name; everything generic
uses invented names so nothing here depends on the card batch having landed.

The eight seams:
  * VILLAGERS — the `_SPENDABLES` registry's promised second consumer, with
    the timing Coffers does NOT have (Action-phase-only — Villagers never got
    the 2022 any-time change);
  * PROJECT ownership — the cube gates (no-rebuy, two cubes), buy-places-a-
    cube-and-runs-no-FX, and the trigger bus's ownership/recipient scoping;
  * ARTIFACTS — their own table (not cards, not landscapes), take/transfer,
    the from:"artifact" trigger source, and Flag's Clean-up draw clause;
  * FLEET — the after-game-end round (roster, skipped non-owners, queued
    extra turns resolving, the hard stop, end conditions ignored mid-round);
  * STAR CHART — the shuffle pick: full fidelity at the Clean-up hand draw
    and at whole-deck shuffles, the LOGGED skip elsewhere (deviation B9), and
    the entropy-identical proof;
  * CANAL / CAPITALISM — the two while-owned passives (cost() clause;
    types_of injection + the Buy-phase play routing + the state-aware
    autoplay exclusion);
  * the REVEAL emit (Patron's class);
  * the turn_ctx additions (played_actions order; buy_gains per BUY PHASE).
"""

import copy

import pytest

from games.dontminion import cards, effects, engine

A, B, C = "alice", "bob", "carol"
K10 = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room",
       "Gardens", "Market", "Cellar", "Festival"]

# Synthetic PROJECTS. The four real-name entries exist because kernel clauses
# key on the string; their texts are stand-ins (data lands with the batch).
LS = {
    "Canal":      {"kind": "project", "cost": 7, "expansion": "base",
                   "text": "During your turns, cards cost $1 less."},
    "Capitalism": {"kind": "project", "cost": 5, "expansion": "base",
                   "text": "During your turns, Actions with +$ amounts in their text are also Treasures."},
    "Star Chart": {"kind": "project", "cost": 3, "expansion": "base",
                   "text": "When shuffling, you may pick one of the cards to go on top."},
    "Fleet":      {"kind": "project", "cost": 5, "expansion": "base",
                   "text": "After the game ends, there's an extra round of turns just for players with this."},
    # generic synthetics
    "Aviary":     {"kind": "project", "cost": 3, "expansion": "base",
                   "text": "When you gain a card, +1 Coffers."},
    "Beacon":     {"kind": "project", "cost": 5, "expansion": "base",
                   "text": "When another player gains a Victory card, +1 Card."},
    "Sunrise":    {"kind": "project", "cost": 4, "expansion": "base",
                   "text": "At the start of your turn, +$1."},
}

ARTS = {
    "Whistle": {"by": "Smithy", "expansion": "base",
                "text": "At the start of your Buy phase, +$1."},
}


@pytest.fixture
def reg():
    """Temporary registry entries, restored afterwards — mutated in place, the
    test_landscapes rule (engine.py holds references to these objects)."""
    saved = (dict(cards.LANDSCAPES), dict(cards.ARTIFACTS),
             {k: list(v) for k, v in effects.TRIGGERS.items()},
             dict(effects.STAGES), dict(effects.LANDSCAPE_FX))
    cards.LANDSCAPES.update(copy.deepcopy(LS))
    cards.ARTIFACTS.update(copy.deepcopy(ARTS))
    yield effects
    for store, old in ((cards.LANDSCAPES, saved[0]),
                       (cards.ARTIFACTS, saved[1]),
                       (effects.TRIGGERS, saved[2]),
                       (effects.STAGES, saved[3]),
                       (effects.LANDSCAPE_FX, saved[4])):
        store.clear()
        store.update(old)


def fresh(players=(A, B), seed=42, kingdom=tuple(K10), expansions=("base",),
          landscapes=None):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom), landscapes=landscapes)


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


def end_turn(g, pid):
    """Drive pid's turn to its end (through both phases)."""
    if g["phase"] == "action":
        ok, err = engine.apply_move(g, pid, {"type": "end_phase"})
        assert ok, err
    if g["over"] or g["pending"]:
        return
    ok, err = engine.apply_move(g, pid, {"type": "end_phase"})
    assert ok, err


# ── VILLAGERS ─────────────────────────────────────────────────────────────────

def test_add_villagers_logs_count_and_persists_off_turn():
    g = fresh()
    g["turn"] = A
    engine.add_villagers(g, 2, B)          # earned on someone else's turn
    assert g["villagers"][B] == 2          # a MAT persists — never evaporates
    e = events(g, "villagers")[-1]
    assert e["count"] == 2 and e["total"] == 2   # count=, never n= (7H rule)


def test_villagers_spend_in_the_action_phase_only():
    g = fresh()
    g["villagers"][A] = 2
    assert engine.spendable(g, A).get("villagers") == 2
    ok, _ = engine.apply_move(g, A, {"type": "spend", "what": "villagers", "n": 2})
    assert ok
    assert g["actions"] == 3 and g["villagers"][A] == 0
    # ...and NOT in the Buy phase: Villagers never got Coffers' 2022 change
    g2 = fresh()
    g2["villagers"][A] = 2
    g2["phase"] = "buy"
    assert "villagers" not in engine.spendable(g2, A)
    ok, _ = engine.apply_move(g2, A, {"type": "spend", "what": "villagers", "n": 1})
    assert not ok
    assert not any(m for m in engine.legal_moves(g2, A)
                   if m.get("type") == "spend" and m.get("what") == "villagers")


def test_villagers_spend_mid_ability_in_the_action_phase():
    """"You can even spend Coffers or Villagers in the middle of resolving an
    ability" — as long as the ability is resolving in your Action phase."""
    g = fresh()
    g["villagers"][A] = 1
    engine.push_choose_cards(g, A, "Cellar", "discard",
                             list(g["seats"][A]["hand"]), 0, 5, "discard")
    engine._sync_pending(g)
    assert engine.spendable(g, A).get("villagers") == 1
    ok, _ = engine.apply_move(g, A, {"type": "spend", "what": "villagers", "n": 1})
    assert ok and g["actions"] == 2


def test_auto_advance_waits_for_a_player_holding_villagers():
    """A player out of Actions but holding tokens AND an Action card can still
    act — the phase must not advance from under them."""
    g = fresh()
    give_hand(g, A, ["Smithy", "Copper"])
    g["actions"] = 0
    g["villagers"][A] = 1
    assert not engine._maybe_auto_buy(g)
    assert g["phase"] == "action"
    ok, _ = engine.apply_move(g, A, {"type": "spend", "what": "villagers", "n": 1})
    assert ok
    ok, _ = engine.apply_move(g, A, {"type": "play_action", "card": "Smithy"})
    assert ok
    # ...but with no Action CARD, tokens alone hold nothing open
    g2 = fresh()
    give_hand(g2, A, ["Copper"])
    g2["actions"] = 0
    g2["villagers"][A] = 3
    assert engine._maybe_auto_buy(g2)
    assert g2["phase"] == "buy"


# ── PROJECTS: the cube gates ──────────────────────────────────────────────────

def test_a_project_buy_places_a_cube_and_runs_no_fx(reg):
    reg.LANDSCAPE_FX["Aviary"] = lambda game, pid: engine.add_coffers(game, 9, pid)
    g = fresh(landscapes=["Aviary"])
    g["phase"] = "buy"
    g["coins"] = 9
    ok, err = engine.apply_move(g, A, {"type": "buy_landscape", "name": "Aviary"})
    assert ok, err
    assert g["landscapes"]["Aviary"]["bought_by"] == [A]
    assert g["coins"] == 6 and g["buys"] == 0
    assert g["coffers"].get(A, 0) == 0     # the FX registry is for EVENTS only


def test_a_project_may_not_be_bought_twice_and_two_cubes_is_the_cap(reg):
    g = fresh(landscapes=["Aviary", "Sunrise", "Beacon"])
    g["phase"] = "buy"
    for name in ("Aviary", "Sunrise"):
        g["coins"], g["buys"] = 9, 1
        ok, err = engine.apply_move(g, A, {"type": "buy_landscape", "name": name})
        assert ok, err
    g["coins"], g["buys"] = 9, 1
    assert engine.landscape_gate(g, A, "Aviary") == "you already have a cube on that"
    assert engine.landscape_gate(g, A, "Beacon") == "you have no Project cubes left"
    ok, _ = engine.apply_move(g, A, {"type": "buy_landscape", "name": "Beacon"})
    assert not ok
    assert not any(m.get("type") == "buy_landscape" for m in engine.legal_moves(g, A))
    # the cap is PER PLAYER: bob still has both cubes
    assert engine.landscape_gate(g, B, "Beacon") is None


# ── PROJECTS: the trigger bus ─────────────────────────────────────────────────

def test_a_project_trigger_fires_for_the_actor_only_when_they_own_a_cube(reg):
    reg.TRIGGERS["Aviary"] = [{"on": "gain", "from": "landscape",
                               "stage": "take", "commutes": True}]
    reg.STAGES[("Aviary", "take")] = \
        lambda game, pid, fr, ch: engine.add_coffers(game, 1, pid)
    g = fresh(landscapes=["Aviary"])
    give_cube(g, "Aviary", A)
    engine.gain(g, A, "Silver")
    engine._drive(g)
    assert g["coffers"].get(A, 0) == 1
    engine.gain(g, B, "Silver")            # bob has no cube: nothing fires
    engine._drive(g)
    assert g["coffers"].get(B, 0) == 0


def test_owners_not_actor_scoping_is_the_road_network_shape(reg):
    reg.TRIGGERS["Beacon"] = [{"on": "gain", "from": "landscape",
                               "recipients": "owners-not-actor",
                               "stage": "draw", "commutes": True,
                               "when": lambda game, p, ctx:
                                   engine.has_type(game, ctx["subject"], "victory")}]
    reg.STAGES[("Beacon", "draw")] = \
        lambda game, pid, fr, ch: engine.draw(game, pid, 1)
    g = fresh(players=(A, B, C), landscapes=["Beacon"])
    give_cube(g, "Beacon", B)
    give_cube(g, "Beacon", C)
    for p in (A, B, C):
        g["seats"][p]["hand"] = []
    engine.gain(g, A, "Estate")            # alice gains: both OTHER owners draw
    engine._drive(g)
    assert len(g["seats"][B]["hand"]) == 1
    assert len(g["seats"][C]["hand"]) == 1
    assert len(g["seats"][A]["hand"]) == 0
    engine.gain(g, B, "Estate")            # bob is the actor: only carol draws
    engine._drive(g)
    assert len(g["seats"][B]["hand"]) == 1
    assert len(g["seats"][C]["hand"]) == 2
    engine.gain(g, A, "Silver")            # not a Victory card: nobody
    engine._drive(g)
    assert len(g["seats"][B]["hand"]) == 1 and len(g["seats"][C]["hand"]) == 2


def test_a_turn_start_project_joins_the_start_of_turn_pool(reg):
    reg.TRIGGERS["Sunrise"] = [{"on": "turn_start", "from": "landscape",
                                "stage": "coin", "commutes": True}]
    reg.STAGES[("Sunrise", "coin")] = \
        lambda game, pid, fr, ch: engine.add_coins(game, 1, pid)
    g = fresh(landscapes=["Sunrise"])
    give_cube(g, "Sunrise", B)
    g["phase"] = "buy"
    end_turn(g, A)
    assert g["turn"] == B
    assert g["coins"] == 1                 # +$1 at bob's turn start, kept
    g["phase"] = "buy"
    end_turn(g, B)
    assert g["turn"] == A and g["coins"] == 0    # alice owns no cube


def test_landscape_token_store_round_trips():
    g = fresh(landscapes=None)
    g["landscapes"]["Plot"] = {"kind": "project", "bought_turn": None,
                               "bought_by": [A]}
    assert engine.landscape_tokens(g, "Plot", A) == 0
    engine.add_landscape_tokens(g, "Plot", A)
    engine.add_landscape_tokens(g, "Plot", A)
    assert engine.landscape_tokens(g, "Plot", A) == 2
    assert engine.take_landscape_tokens(g, "Plot", A) == 2
    assert engine.landscape_tokens(g, "Plot", A) == 0
    assert "tokens" not in g["landscapes"]["Plot"]   # empty store leaves no key


# ── ARTIFACTS ─────────────────────────────────────────────────────────────────

def test_new_game_keeps_artifacts_available_for_their_granting_card(reg):
    g = fresh()                            # kingdom holds Smithy
    assert g["artifacts"] == {"Whistle": None}
    g2 = fresh(kingdom=[c for c in K10 if c != "Smithy"] + ["Chapel"])
    assert g2["artifacts"] == {}


def test_take_artifact_transfers_and_logs(reg):
    g = fresh()
    engine.take_artifact(g, A, "Whistle")
    assert engine.holds_artifact(g, A, "Whistle")
    engine.take_artifact(g, B, "Whistle")  # "you take it FROM another player"
    assert engine.holds_artifact(g, B, "Whistle")
    assert not engine.holds_artifact(g, A, "Whistle")
    e = events(g, "artifact")[-1]
    assert e["name"] == "Whistle" and e["from_pid"] == A
    engine.take_artifact(g, B, "Whistle")  # taking your own: no-op, still logs
    assert "from_pid" not in events(g, "artifact")[-1]
    with pytest.raises(ValueError):
        engine.take_artifact(g, A, "Sceptre of Nothing")


def test_an_artifact_trigger_fires_for_its_holder_only(reg):
    reg.TRIGGERS["Whistle"] = [{"on": "buy_phase_start", "from": "artifact",
                                "stage": "coin", "commutes": True}]
    reg.STAGES[("Whistle", "coin")] = \
        lambda game, pid, fr, ch: engine.add_coins(game, 1, pid)
    g = fresh()
    g["artifacts"]["Whistle"] = B
    ok, _ = engine.apply_move(g, A, {"type": "end_phase"})   # alice -> buy
    assert ok
    assert g["coins"] == 0                 # alice holds nothing
    g["turn"] = B                          # stage bob's Action phase directly
    g["phase"] = "action"
    ok, _ = engine.apply_move(g, B, {"type": "end_phase"})
    assert ok
    assert g["coins"] == 1                 # bob holds the Whistle


def test_the_flag_draws_a_sixth_card_at_cleanup(reg):
    g = fresh()
    g["artifacts"]["Flag"] = A             # the holder record is all Flag is
    g["phase"] = "buy"
    end_turn(g, A)
    assert len(g["seats"][A]["hand"]) == 6
    g["phase"] = "buy"
    end_turn(g, B)                         # bob holds nothing: the plain 5
    assert len(g["seats"][B]["hand"]) == 5


# ── FLEET ─────────────────────────────────────────────────────────────────────

def _empty_provinces(g):
    g["supply"]["Province"] = 0


def test_without_fleet_the_game_ends_as_ever(reg):
    g = fresh(landscapes=["Fleet"])        # dealt but nobody bought a cube
    _empty_provinces(g)
    g["phase"] = "buy"
    end_turn(g, A)
    assert g["over"] and g["fleet"] is None


def test_the_fleet_round_grants_owners_one_turn_each_then_ends(reg):
    g = fresh(players=(A, B, C), landscapes=["Fleet"])
    give_cube(g, "Fleet", A)
    give_cube(g, "Fleet", B)
    _empty_provinces(g)
    g["phase"] = "buy"
    end_turn(g, A)                         # alice triggers the end
    assert not g["over"]
    # "the first player to get a Fleet turn is the next player after the
    # player who last had a regular turn" — B, then wrapping to A; carol
    # (cube-less) never gets a turn
    assert g["fleet"]["remaining"] == [A]
    assert g["turn"] == B
    b_turns = g["seats"][B]["turns_taken"]
    g["phase"] = "buy"
    end_turn(g, B)
    assert not g["over"] and g["turn"] == A
    # "these Fleet turns are not counted for tie-breaker"
    assert g["seats"][B]["turns_taken"] == b_turns
    g["phase"] = "buy"
    end_turn(g, A)                         # the LAST fleet turn
    assert g["over"]
    assert events(g, "fleet_round")


def test_the_round_ends_even_if_the_end_conditions_no_longer_hold(reg):
    g = fresh(landscapes=["Fleet"])
    give_cube(g, "Fleet", B)
    _empty_provinces(g)
    g["phase"] = "buy"
    end_turn(g, A)
    assert not g["over"] and g["turn"] == B
    g["supply"]["Province"] = 8            # "returned to the Supply" mid-round
    g["phase"] = "buy"
    end_turn(g, B)
    assert g["over"]                       # "it also doesn't matter"


def test_a_queued_extra_turn_resolves_before_the_fleet_round(reg):
    g = fresh(landscapes=["Fleet"])
    give_cube(g, "Fleet", B)
    engine.request_extra_turn(g, A, source="Mission")
    _empty_provinces(g)
    g["phase"] = "buy"
    end_turn(g, A)
    assert not g["over"]
    assert g["turn"] == A and g["extra_turn"]   # the queued Mission turn first
    g["phase"] = "buy"
    end_turn(g, A)
    assert not g["over"] and g["turn"] == B     # then bob's fleet turn
    g["phase"] = "buy"
    end_turn(g, B)
    assert g["over"]


def test_an_extra_turn_taken_on_the_last_fleet_turn_is_still_resolved(reg):
    """AMBIGUITY A8, pinned. Ch. VII's Fleet entry has exactly three
    clarifications, and none of them speaks to an extra turn TRIGGERED during
    the round — only to those "already in queue", which "will now be
    resolved". We read the round uniformly: an extra turn generated on the
    last Fleet turn is resolved exactly like one generated on any other, and
    the game ends when no owner is owed a turn and nothing is queued.

    The alternative reading (the round stops dead after the last Fleet turn)
    is defensible too, and it is what this test asserted until the audit
    showed the sentence it quoted was not in the compendium."""
    g = fresh(landscapes=["Fleet"])
    give_cube(g, "Fleet", B)
    _empty_provinces(g)
    g["phase"] = "buy"
    end_turn(g, A)
    assert g["turn"] == B
    engine.request_extra_turn(g, B, source="Mission")
    g["phase"] = "buy"
    end_turn(g, B)
    assert not g["over"] and g["turn"] == B and g["extra_turn"]
    g["phase"] = "buy"
    end_turn(g, B)
    assert g["over"], "and now nothing is owed"


def test_buying_fleet_during_the_round_grants_no_turn(reg):
    g = fresh(players=(A, B, C), landscapes=["Fleet"])
    give_cube(g, "Fleet", B)
    _empty_provinces(g)
    g["phase"] = "buy"
    end_turn(g, A)
    assert g["turn"] == B
    ok, _ = engine.apply_move(g, B, {"type": "end_phase"})   # -> buy phase
    assert ok
    g["coins"], g["buys"] = 9, 1
    ok, err = engine.apply_move(g, C, {"type": "buy_landscape", "name": "Fleet"})
    assert not ok                          # not carol's turn — sanity
    ok, err = engine.apply_move(g, B, {"type": "buy_landscape", "name": "Fleet"})
    assert not ok                          # bob already has a cube
    # carol can never buy mid-round from her seat (not her turn), and the
    # roster was fixed at trigger time — pin that a late cube adds no turn by
    # writing one directly and finishing the round:
    give_cube(g, "Fleet", C)
    end_turn(g, B)
    assert g["over"]                       # carol's late cube granted nothing


# ── STAR CHART ────────────────────────────────────────────────────────────────

def _star_setup(g, deck, discard):
    give_cube(g, "Star Chart", A)
    g["seats"][A]["deck"] = list(deck)
    g["seats"][A]["discard"] = list(discard)


def test_the_cleanup_hand_draw_offers_the_pick_and_honours_it(reg):
    g = fresh(landscapes=["Star Chart"])
    _star_setup(g, [], ["Gold", "Copper", "Copper", "Estate", "Estate", "Curse"])
    give_hand(g, A, [])
    g["phase"] = "buy"
    ok, _ = engine.apply_move(g, A, {"type": "end_phase"})
    assert ok
    f = frame(g)
    assert f is not None and f["card"] == "Star Chart"
    assert f["pid"] == A and f["kind"] == "choose_cards"
    assert f["constraint"]["max"] == 1 and f["constraint"]["min"] == 0
    decide(g, A, cards=["Gold"])
    assert "Gold" in g["seats"][A]["hand"]     # guaranteed into the new hand
    assert len(g["seats"][A]["hand"]) == 5
    assert g["turn"] == B                      # the turn handed off normally
    pick = events(g, "star_chart")[-1]
    assert pick["card"] == "Gold" and pick["private_to"] == [A]


def test_declining_the_pick_still_draws_the_hand(reg):
    g = fresh(landscapes=["Star Chart"])
    _star_setup(g, [], ["Gold", "Copper", "Copper", "Estate", "Estate", "Curse"])
    give_hand(g, A, [])
    g["phase"] = "buy"
    ok, _ = engine.apply_move(g, A, {"type": "end_phase"})
    assert ok
    decide(g, A, cards=[])
    assert len(g["seats"][A]["hand"]) == 5
    assert g["turn"] == B


def test_the_pick_spends_no_extra_entropy(reg):
    """The pick moves a card AFTER rng.shuffle, so the rng sequence is the
    same picked or declined — the determinism-soak guarantee."""
    base = fresh(landscapes=["Star Chart"])
    _star_setup(base, [], ["Gold", "Copper", "Copper", "Estate", "Estate"])
    give_hand(base, A, [])
    base["phase"] = "buy"
    g1, g2 = copy.deepcopy(base), copy.deepcopy(base)
    for g, pick in ((g1, ["Gold"]), (g2, [])):
        ok, _ = engine.apply_move(g, A, {"type": "end_phase"})
        assert ok
        decide(g, A, cards=pick)
    assert g1["rng_state"] == g2["rng_state"]


def test_a_mid_ability_shuffle_skips_the_pick_and_says_so(reg):
    """Deviation B9: a shuffle inside an ability that continues afterwards
    cannot host a decision — it shuffles uniformly and LOGS the skip (a
    skipped ability must never be silent)."""
    g = fresh(landscapes=["Star Chart"])
    give_cube(g, "Star Chart", A)
    give_hand(g, A, ["Smithy"])
    g["seats"][A]["deck"] = ["Copper"]
    g["seats"][A]["discard"] = ["Gold", "Estate", "Estate"]
    ok, _ = engine.apply_move(g, A, {"type": "play_action", "card": "Smithy"})
    assert ok
    assert not g["pending"]                # no pick frame mid-Smithy
    assert events(g, "star_chart_skip")
    assert len(g["seats"][A]["hand"]) == 3


def test_shuffle_into_deck_offers_the_pick_from_the_whole_deck(reg):
    g = fresh(landscapes=["Star Chart"])
    give_cube(g, "Star Chart", A)
    g["seats"][A]["deck"] = ["Copper", "Copper"]
    g["seats"][A]["discard"] = ["Gold", "Estate"]
    engine.shuffle_into_deck(g, A, ["Gold", "Estate"])
    engine._sync_pending(g)
    f = frame(g)
    assert f is not None and f["card"] == "Star Chart"
    assert sorted(f["constraint"]["cards"]) == ["Copper", "Copper", "Estate", "Gold"]
    decide(g, A, cards=["Gold"])
    assert g["seats"][A]["deck"][0] == "Gold"


def test_a_non_owner_shuffle_is_byte_identical(reg):
    g = fresh(landscapes=["Star Chart"])   # dealt, nobody owns a cube
    give_hand(g, A, [])
    g["seats"][A]["deck"] = []
    g["seats"][A]["discard"] = ["Gold", "Copper", "Copper", "Estate", "Estate"]
    g["phase"] = "buy"
    ok, _ = engine.apply_move(g, A, {"type": "end_phase"})
    assert ok
    assert g["turn"] == B                  # no frame opened anywhere
    assert not events(g, "star_chart_skip")
    assert not events(g, "star_chart")


# ── CANAL ─────────────────────────────────────────────────────────────────────

def test_canal_reduces_costs_on_the_owners_turns_only(reg):
    g = fresh(landscapes=["Canal"])
    give_cube(g, "Canal", B)
    assert engine.cost(g, "Smithy") == 4   # alice's turn: bob's cube is idle
    g["turn"] = B
    assert engine.cost(g, "Smithy") == 3   # "during your turns"
    assert engine.cost(g, "Copper") == 0   # min 0 as ever


# ── CAPITALISM ────────────────────────────────────────────────────────────────

def test_the_derived_card_set_reads_plus_dollar_literally():
    assert "Festival" in cards.CAPITALISM_CARDS     # "+$2"
    assert "Militia" in cards.CAPITALISM_CARDS      # "+$2", an Attack
    assert "Smithy" not in cards.CAPITALISM_CARDS   # only +Cards
    assert "Gold" not in cards.CAPITALISM_CARDS     # a Treasure, not an Action


def test_capitalism_changes_types_on_the_owners_turn_only(reg):
    g = fresh(landscapes=["Capitalism"])
    give_cube(g, "Capitalism", A)
    assert engine.has_type(g, "Festival", "treasure")
    assert engine.has_type(g, "Festival", "action")  # ALSO a Treasure
    g["turn"] = B
    assert not engine.has_type(g, "Festival", "treasure")
    g["turn"] = A
    g["over"] = True                       # the Keep rule: not your turn at over
    assert not engine.has_type(g, "Festival", "treasure")


def test_a_changed_action_plays_in_the_buy_phase_without_an_action(reg):
    g = fresh(landscapes=["Capitalism"])
    give_cube(g, "Capitalism", A)
    give_hand(g, A, ["Festival", "Copper"])
    g["phase"] = "buy"
    moves = engine.legal_moves(g, A)
    assert {"type": "play_treasure", "card": "Festival"} in moves
    g["actions"] = 0                       # no Actions left — irrelevant here
    ok, err = engine.apply_move(g, A, {"type": "play_treasure", "card": "Festival"})
    assert ok, err
    assert g["coins"] == 2                 # Festival's +$2 came from its effect
    assert g["buys"] == 2                  # ...and its +1 Buy
    assert g["actions"] == 2               # +2 Actions granted, none SPENT
    assert g["turn_ctx"]["actions_played"] == 1    # it IS an Action play
    assert g["turn_ctx"]["played_actions"] == ["Festival"]


def test_a_changed_attack_still_opens_the_reaction_window(reg):
    g = fresh(landscapes=["Capitalism"])
    give_cube(g, "Capitalism", A)
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Moat", "Copper", "Copper", "Copper", "Copper"])
    g["phase"] = "buy"
    ok, err = engine.apply_move(g, A, {"type": "play_treasure", "card": "Militia"})
    assert ok, err
    f = frame(g)
    assert f is not None and f["pid"] == B   # bob's Moat window opened


def test_play_all_treasures_never_plays_a_changed_action(reg):
    g = fresh(landscapes=["Capitalism"])
    give_cube(g, "Capitalism", A)
    give_hand(g, A, ["Copper", "Festival", "Silver"])
    g["phase"] = "buy"
    assert engine.autoplay_treasures(g, A) == ["Copper", "Silver"]
    ok, _ = engine.apply_move(g, A, {"type": "play_all_treasures"})
    assert ok
    assert g["coins"] == 3
    assert "Festival" in g["seats"][A]["hand"]
    # a hand holding ONLY changed actions makes the bulk play a no-op — the
    # enumerator must not offer it (the livelock rule)
    give_hand(g, A, ["Festival"])
    assert not any(m.get("type") == "play_all_treasures"
                   for m in engine.legal_moves(g, A))
    ok, _ = engine.apply_move(g, A, {"type": "play_all_treasures"})
    assert not ok
    # ...and the wire ships the reader's answer for the client's button
    view = engine.player_view(g, A)
    assert view["autoplay"] == []


# ── THE REVEAL EVENT ──────────────────────────────────────────────────────────

def test_a_reveal_trigger_fires_per_copy_for_the_revealer(reg):
    reg.TRIGGERS["Market"] = [{"on": "reveal", "from": "self", "stage": "pat",
                               "commutes": True,
                               "when": lambda game, p, ctx:
                                   game["phase"] == "action"}]
    reg.STAGES[("Market", "pat")] = \
        lambda game, pid, fr, ch: engine.add_coffers(game, 1, pid)
    g = fresh()
    give_hand(g, B, ["Market", "Market", "Copper"])
    engine.reveal(g, B, ["Market", "Market", "Copper"], "hand")
    engine._drive(g)
    # two copies revealed -> two triggers, for the REVEALER, during alice's
    # ACTION phase (an opponent's Action phase counts — the Patron rule)
    assert g["coffers"].get(B, 0) == 2
    g["phase"] = "buy"
    engine.reveal(g, B, ["Market"], "hand")
    engine._drive(g)
    assert g["coffers"].get(B, 0) == 2     # the when-gate: not in a Buy phase


def test_a_reveal_with_no_consumer_parks_nothing():
    g = fresh()
    engine.reveal(g, A, ["Copper"], "hand")
    assert not g["pending"]


# ── turn_ctx bookkeeping ──────────────────────────────────────────────────────

def test_played_actions_records_names_in_play_order():
    g = fresh()
    give_hand(g, A, ["Village", "Smithy"])
    ok, _ = engine.apply_move(g, A, {"type": "play_action", "card": "Village"})
    assert ok
    ok, _ = engine.apply_move(g, A, {"type": "play_action", "card": "Smithy"})
    assert ok
    assert g["turn_ctx"]["played_actions"] == ["Village", "Smithy"]


def test_buy_gains_counts_per_buy_phase_not_per_turn():
    """Villa's return to the Action phase starts a FRESH count — Exploration
    checks "the Buy phase that just ended" and Merchant Guild counts the cards
    gained "in it"."""
    g = fresh()
    g["phase"] = "buy"
    g["turn_ctx"]["buy_gains"] = 2
    assert engine.return_to_action_phase(g, A)
    assert g["turn_ctx"]["buy_gains"] == 0


# ── the save shape ────────────────────────────────────────────────────────────

def test_schema_13_fills_villagers_artifacts_and_fleet():
    g = fresh()
    del g["villagers"]
    del g["artifacts"]
    del g["fleet"]
    for k in ("played_actions", "citadel_used", "innovation_used", "horn_used"):
        del g["turn_ctx"][k]
    g["schema"] = 12
    engine.migrate(g)
    assert g["schema"] == 13
    assert g["villagers"] == {A: 0, B: 0}
    assert g["artifacts"] == {}
    assert g["fleet"] is None
    assert g["turn_ctx"]["played_actions"] == []
    assert g["turn_ctx"]["horn_used"] is False


def test_the_new_keys_ship_public_on_the_wire(reg):
    g = fresh(landscapes=["Aviary"])
    give_cube(g, "Aviary", A)
    g["villagers"][A] = 3
    g["artifacts"]["Whistle"] = B
    view = engine.player_view(g, B)        # an OPPONENT's view
    assert view["villagers"][A] == 3       # mat tokens are open information
    assert view["artifacts"]["Whistle"] == B
    assert view["fleet"] is None
    assert view["landscapes"]["Aviary"]["bought_by"] == [A]   # the cube
