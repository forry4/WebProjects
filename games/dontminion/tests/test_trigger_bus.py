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


def test_buy_event_reaches_in_play_triggers(g, synthetic):
    trigger, _, _ = synthetic
    hits = []
    trigger("Smithy", {"on": "buy", "from": "in_play",
                       "push": lambda game, pid: hits.append(pid)})
    g["seats"][A]["in_play"] = ["Smithy"]
    g["phase"] = "buy"
    g["coins"] = 3
    ok, err = engine.apply_move(g, A, {"type": "buy", "card": "Silver"})
    assert ok, err
    assert hits == [A]
    # not fired for a seat without the card in play
    g2 = engine.new_game([A, B], ["base"], seed=4, kingdom=K7)
    g2["phase"] = "buy"
    g2["coins"] = 3
    assert engine.apply_move(g2, A, {"type": "buy", "card": "Silver"})[0]
    assert hits == [A]


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
