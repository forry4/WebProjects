"""Trigger-bus contract tests — prove the seams future sets rely on BEFORE a
real consumer exists: the "self" source (Hinterlands when-gain / Dark Ages
on-trash), the "buy" event, the "in_play" source, and the COST_MODS seam.
Synthetic registrations are injected into the merged effects registries and
removed again (the bus reads them live)."""

import pytest

from games.dontminion import effects, engine

A, B = "alice", "bob"
K7 = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room", "Gardens"]


@pytest.fixture
def g():
    return engine.new_game([A, B], ["base"], seed=3, kingdom=K7)


@pytest.fixture
def synthetic():
    """Register synthetic bus consumers; always clean up."""
    added_triggers, added_stages, added_mods = [], [], []

    def trigger(card, spec):
        effects.TRIGGERS.setdefault(card, []).append(spec)
        added_triggers.append(card)

    def stage(key, fn):
        effects.STAGES[key] = fn
        added_stages.append(key)

    def cost_mod(card, fn):
        effects.COST_MODS[card] = fn
        added_mods.append(card)

    yield trigger, stage, cost_mod
    for c in added_triggers:
        effects.TRIGGERS.pop(c, None)
    for k in added_stages:
        effects.STAGES.pop(k, None)
    for c in added_mods:
        effects.COST_MODS.pop(c, None)


def test_self_trigger_fires_when_the_subject_is_the_card(g, synthetic):
    trigger, stage, _ = synthetic
    hits = []
    trigger("Silver", {"on": "gain", "from": "self", "stage": "on_self_gain"})
    stage(("Silver", "on_self_gain"), lambda game, pid, frame, choice:
          hits.append((pid, frame["data"]["subject"])))
    engine.gain(g, A, "Silver")
    engine._drive(g)
    assert hits == [(A, "Silver")]
    engine.gain(g, A, "Gold")            # a different subject: no fire
    engine._drive(g)
    assert len(hits) == 1


def test_trash_event_reaches_self_triggers(g, synthetic):
    trigger, stage, _ = synthetic
    hits = []
    trigger("Copper", {"on": "trash", "from": "self", "stage": "on_self_trash"})
    stage(("Copper", "on_self_trash"), lambda game, pid, frame, choice:
          hits.append(frame["data"]["subject"]))
    g["seats"][A]["hand"] = ["Copper", "Estate"]
    engine.trash(g, A, ["Copper"])
    engine._drive(g)
    assert hits == ["Copper"]


def test_self_triggers_receive_the_emit_context(g, synthetic):
    """A self trigger must see the emit's extra context, not just
    actor+subject — it used to be dropped, which would stop a when-BUY-this
    card (Farmland) distinguishing a buy from any other gain."""
    trigger, stage, _ = synthetic
    seen = []
    trigger("Silver", {"on": "gain", "from": "self", "stage": "ctx"})
    stage(("Silver", "ctx"), lambda game, pid, frame, choice:
          seen.append(frame["data"].get("via_buy")))
    engine.gain(g, A, "Silver")                       # a plain gain
    engine._drive(g)
    g["coins"] = 99
    engine.apply_move(g, A, {"type": "end_phase"})
    engine.apply_move(g, A, {"type": "buy", "card": "Silver"})   # a BUY
    engine._drive(g)
    assert seen == [False, True] or seen == [None, True], seen


def test_discard_event_reaches_self_triggers(g, synthetic):
    """The `discard` emit point, paid as ph.3 pre-work for Tunnel/Trail/Weaver
    before any consumer exists."""
    trigger, stage, _ = synthetic
    hits = []
    trigger("Estate", {"on": "discard", "from": "self", "stage": "on_self_discard"})
    stage(("Estate", "on_self_discard"), lambda game, pid, frame, choice:
          hits.append((pid, frame["data"]["subject"], frame["data"]["zone"])))
    g["seats"][A]["hand"] = ["Estate", "Copper"]
    engine.discard(g, A, ["Estate", "Copper"])
    engine._drive(g)
    assert hits == [(A, "Estate", "hand")]      # only the registered subject


def test_discard_event_fires_after_the_WHOLE_batch_has_moved(g, synthetic):
    """2022 rules change: you discard all at once, not one at a time. The
    compendium's Tunnel ruling turns on it — discarding your hand while
    holding Tunnel + Watchtower lets you reveal Tunnel, but the Watchtower has
    already left your hand by then. So when the event fires, NO discarded card
    may still be in hand."""
    trigger, stage, _ = synthetic
    seen = []
    trigger("Estate", {"on": "discard", "from": "self", "stage": "on_batch"})
    stage(("Estate", "on_batch"), lambda game, pid, frame, choice:
          seen.append(list(game["seats"][pid]["hand"])))
    g["seats"][A]["hand"] = ["Estate", "Copper", "Silver"]
    engine.discard(g, A, ["Estate", "Copper"])
    engine._drive(g)
    assert seen == [["Silver"]], "the batch was not fully discarded before the emit"


def test_cleanup_discards_do_not_fire_when_discard(g, synthetic):
    """Tunnel/Trail/Weaver are all "other than during a Clean-up phase".
    _end_turn moves the cards directly rather than through discard(), so the
    event correctly never fires there. Pinned because routing Clean-up through
    discard() later (Scheme wants a Clean-up hook) would silently break it."""
    trigger, stage, _ = synthetic
    hits = []
    trigger("Copper", {"on": "discard", "from": "self", "stage": "on_cleanup"})
    stage(("Copper", "on_cleanup"), lambda game, pid, frame, choice: hits.append(1))
    g["seats"][A]["hand"] = ["Copper", "Copper"]
    g["seats"][A]["in_play"] = []
    engine.apply_move(g, A, {"type": "end_phase"})     # -> buy
    engine.apply_move(g, A, {"type": "end_phase"})     # -> clean-up + next turn
    assert hits == [], "a Clean-up discard fired a when-discard reaction"


def test_buy_event_reaches_in_play_triggers(g, synthetic):
    trigger, _, _ = synthetic
    hits = []
    trigger("Smithy", {"on": "buy", "from": "in_play",
                       "push": lambda game, pid, ctx: hits.append((pid, ctx["subject"]))})
    g["seats"][A]["in_play"] = ["Smithy"]
    g["phase"] = "buy"
    g["coins"] = 3
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Silver"})
    assert ok, err
    # the push receives WHAT WAS BOUGHT — Haggler is useless without it
    assert hits == [(A, "Silver")]
    # not fired for a seat without the card in play
    g2 = engine.new_game([A, B], ["base"], seed=4, kingdom=K7)
    g2["phase"] = "buy"
    g2["coins"] = 3
    assert engine.apply_move(g2, A, {"type": "buy", "card": "Silver"})[0]
    assert hits == [(A, "Silver")]


def test_cost_mods_apply_per_copy_on_any_table(g, synthetic):
    _, _, cost_mod = synthetic
    cost_mod("Smithy", lambda game, name: 2 if name == "Gold" else 0)
    assert engine.cost(g, "Gold") == 6              # no copy in play yet
    g["seats"][B]["in_play"] = ["Smithy"]           # ANY table counts
    assert engine.cost(g, "Gold") == 4
    g["seats"][A]["duration"] = [{"card": "Smithy", "fx": [], "riders": []}]
    assert engine.cost(g, "Gold") == 2              # persisting copies count too
    assert engine.cost(g, "Silver") == 3            # unmodified names untouched
    assert engine.cost(g, "Copper") == 0            # never below zero


def test_hand_reaction_window_shape(g, synthetic):
    trigger, stage, _ = synthetic
    taken = []
    trigger("Moat", {"on": "gain", "from": "hand", "stage": "react",
                     "when": lambda game, pid, ctx: ctx["subject"] == "Silver"})
    stage(("Moat", "react"), lambda game, pid, frame, choice:
          taken.append((pid, choice["ids"][0])))
    g["seats"][B]["hand"] = ["Moat"]
    engine.gain(g, A, "Silver")
    assert g["pending_pid"] == B and g["pending_kind"] == "choose_option"
    ok, err = engine.apply_move(g, B, {"type": "decision", "ids": ["play"]})
    assert ok, err
    assert taken == [(B, "play")]
    engine.gain(g, A, "Gold")                       # `when` filters it out
    assert g["pending_pid"] is None


# --- the WOULD-GAIN replacement protocol (Trader-class; built ahead of its
#     first real consumer so Hinterlands lands on proven machinery) ------------

def _register_traderx(trigger, stage):
    """Synthetic Trader: when you would gain a card costing >= 3, you may
    reveal to instead gain a Silver... (here: instead gain a Copper, so the
    replacement is observable against a Silver original)."""
    def react(game, pid, frame, choice):
        if choice["ids"][0] != "react":
            return                              # declined: the parked gain resolves
        parked = engine.cancel_pending_gain(game)
        assert parked is not None
        engine.gain(game, pid, "Copper")        # the replacement gain
    trigger("Moat", {"on": "would_gain", "from": "hand", "mode": "reveal",
                     "stage": "would", "when": lambda g, p, ctx: ctx["subject"] == "Silver"})
    stage(("Moat", "would"), react)


def test_would_gain_replacement_path(g, synthetic):
    trigger, stage, _ = synthetic
    _register_traderx(trigger, stage)
    g["seats"][A]["hand"] = ["Moat"]
    silver0, copper0 = g["supply"]["Silver"], g["supply"]["Copper"]
    assert engine.gain(g, A, "Silver")           # "a gain is underway"
    assert g["pending_pid"] == A and g["pending_kind"] == "choose_option"
    assert "Reveal Moat" in g["pending"][-1]["constraint"]["options"][0]["label"]
    ok, err = engine.apply_move(g, A, {"type": "decision", "ids": ["react"]})
    assert ok, err
    assert g["supply"]["Silver"] == silver0      # the original gain never happened
    assert g["supply"]["Copper"] == copper0 - 1  # the replacement did
    assert "Copper" in g["seats"][A]["discard"]
    assert "Silver" not in g["seats"][A]["discard"]
    assert g["pending_pid"] is None              # the parked frame resolved away


def test_would_gain_decline_resolves_the_original(g, synthetic):
    trigger, stage, _ = synthetic
    _register_traderx(trigger, stage)
    g["seats"][A]["hand"] = ["Moat"]
    silver0 = g["supply"]["Silver"]
    assert engine.gain(g, A, "Silver")
    ok, err = engine.apply_move(g, A, {"type": "decision", "ids": ["decline"]})
    assert ok, err
    assert g["supply"]["Silver"] == silver0 - 1  # the parked gain resolved
    assert "Silver" in g["seats"][A]["discard"]


def test_would_gain_only_intercepts_the_gainer(g, synthetic):
    trigger, stage, _ = synthetic
    _register_traderx(trigger, stage)
    g["seats"][B]["hand"] = ["Moat"]             # the OTHER player holds it
    assert engine.gain(g, A, "Silver")
    assert g["pending_pid"] is None              # no window: A gains directly
    assert "Silver" in g["seats"][A]["discard"]
