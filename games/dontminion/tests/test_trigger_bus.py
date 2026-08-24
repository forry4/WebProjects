"""Trigger-bus contract tests — prove the seams future sets rely on BEFORE a
real consumer exists: the "self" source (Hinterlands when-gain / Dark Ages
on-trash), the "buy" event and the "in_play" source. Synthetic registrations
are injected into the merged effects registries and removed again (the bus
reads them live).

⚠ A CONTRACT TEST KEEPS A SEAM ALIVE IN THE DOCS WITHOUT KEEPING IT HONEST.
This module used to cover a fourth seam, COST_MODS, which shipped EMPTY for
twelve expansions — the synthetic consumer here was the only one it ever had,
and it passed all the way through, so four documents went on describing a
mechanism no card used. Deleted post-ph. 10 (see engine.cost). When adding a
contract test for an unconsumed seam, add its row to
`test_seam_consumers.py::UNCONSUMED` too — that is what makes the seam's
emptiness visible instead of merely covered."""

import random

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
    added_triggers, added_stages = [], []

    def trigger(card, spec):
        effects.TRIGGERS.setdefault(card, []).append(spec)
        added_triggers.append(card)

    def stage(key, fn):
        effects.STAGES[key] = fn
        added_stages.append(key)

    yield trigger, stage
    for c in added_triggers:
        effects.TRIGGERS.pop(c, None)
    for k in added_stages:
        effects.STAGES.pop(k, None)


def test_self_trigger_fires_when_the_subject_is_the_card(g, synthetic):
    trigger, stage = synthetic
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
    trigger, stage = synthetic
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
    trigger, stage = synthetic
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
    trigger, stage = synthetic
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
    trigger, stage = synthetic
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
    trigger, stage = synthetic
    hits = []
    trigger("Copper", {"on": "discard", "from": "self", "stage": "on_cleanup"})
    stage(("Copper", "on_cleanup"), lambda game, pid, frame, choice: hits.append(1))
    g["seats"][A]["hand"] = ["Copper", "Copper"]
    g["seats"][A]["in_play"] = []
    engine.apply_move(g, A, {"type": "end_phase"})     # -> buy
    engine.apply_move(g, A, {"type": "end_phase"})     # -> clean-up + next turn
    assert hits == [], "a Clean-up discard fired a when-discard reaction"


def test_attack_reactions_come_from_the_registry_not_the_kernel(g):
    """Moat and Diplomat used to be hardcoded inside _reaction_options, so
    every new reaction was a kernel edit. They are registry entries now."""
    from games.dontminion import effects
    reg = engine.attack_reactions()
    assert reg is effects.ATTACK_REACTIONS
    assert reg["Moat"]["immunity"] is True
    assert reg["Diplomat"].get("immunity") is not True      # NOT immunity
    assert reg["Diplomat"]["repeatable"] is True

    g["seats"][A]["hand"] = ["Militia"]
    g["seats"][B]["hand"] = ["Moat"] + ["Copper"] * 4
    assert engine.apply_move(g, A, {"type": "play_action", "card": "Militia"})[0]
    ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
    assert "react:Moat" in ids and "decline" in ids


def test_a_registered_reaction_that_PLAYS_itself(g, synthetic):
    """Guard Dog's shape (compendium p53 REACTION THAT PLAYS ITSELF): the card
    is PLAYED from hand rather than revealed, costs no Action, grants no
    immunity, and may be used again against the same attack."""
    from games.dontminion import effects
    played = []
    effects.ATTACK_REACTIONS["Village"] = {
        "label": "Play Village", "mode": "play", "repeatable": True}
    trigger, stage = synthetic          # only for its cleanup of STAGES
    try:
        g["seats"][A]["hand"] = ["Militia"]
        g["seats"][B]["hand"] = ["Village", "Village", "Copper", "Copper", "Copper"]
        g["seats"][B]["deck"] = ["Estate", "Estate", "Silver"]
        assert engine.apply_move(g, A, {"type": "play_action", "card": "Militia"})[0]
        actions_before = g["actions"]          # AFTER the Militia spent A's action
        assert engine.apply_move(g, B, {"type": "decision", "ids": ["react:Village"]})[0]

        # it really PLAYED: it is in B's in_play, not revealed-and-kept
        assert "Village" in g["seats"][B]["in_play"]
        assert g["seats"][B]["hand"].count("Village") == 1
        # Village's +2 Actions belong to B, who has no pool on A's turn — so
        # they evaporate rather than landing in the ATTACKER's pool (they did:
        # this read 2 before `_actor` taught the resource helpers who is acting)
        assert g["actions"] == actions_before
        assert any(e.get("event") == "off_turn_bonus" for e in g["log"])
        # repeatable: the second copy is offered again
        ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
        assert "react:Village" in ids
        # ...and it granted no immunity — the Militia still hits
        assert engine.apply_move(g, B, {"type": "decision", "ids": ["decline"]})[0]
        assert g["pending_kind"] == "choose_cards"       # discard-to-3 prompt
    finally:
        effects.ATTACK_REACTIONS.pop("Village", None)


def test_a_frame_written_by_the_pre_registry_kernel_still_resolves(g):
    """The window's option ids are PERSISTED inside an open frame, so a game
    paused on an attack window survives a deploy holding the OLD ids. Both the
    legacy id and the legacy Diplomat stage must still resolve."""
    g["seats"][A]["hand"] = ["Militia"]
    g["seats"][B]["hand"] = ["Moat"] + ["Copper"] * 4
    assert engine.apply_move(g, A, {"type": "play_action", "card": "Militia"})[0]
    # forge the pre-registry option id into the open frame, as a save would hold
    g["pending"][-1]["constraint"]["options"] = [
        {"id": "reveal_moat", "label": "Reveal Moat"},
        {"id": "decline", "label": "Don't react"}]
    assert engine.apply_move(g, B, {"type": "decision", "ids": ["reveal_moat"]})[0]
    atk = engine._current_attack_frame(g)
    assert atk is None or B in atk["data"]["immune"], "legacy Moat id lost its immunity"


def test_an_attack_TREASURE_opens_the_reaction_window(g):
    """Cauldron is an Attack Treasure. The treasure play path never wrapped
    attacks, so no window opened and `_atk_immune` was never set — the attack
    would have been unblockable by Moat, silently. An attack is an attack
    whichever way it reached the table."""
    from games.dontminion.cards import CARDS
    from games.dontminion import effects
    CARDS["Silver"]["types"] = ["treasure", "attack"]      # stand in for Cauldron
    effects.EFFECTS["Silver"] = lambda game, pid: None
    try:
        g["seats"][A]["hand"] = ["Silver"]
        g["seats"][B]["hand"] = ["Moat"] + ["Copper"] * 4
        assert engine.apply_move(g, A, {"type": "end_phase"})[0]
        assert engine.apply_move(g, A, {"type": "play_treasure", "card": "Silver"})[0]
        assert g["pending_pid"] == B, "an Attack Treasure opened no window"
        ids = [o["id"] for o in g["pending"][-1]["constraint"]["options"]]
        assert "react:Moat" in ids
        assert engine.apply_move(g, B, {"type": "decision", "ids": ["react:Moat"]})[0]
        atk = engine._current_attack_frame(g)
        assert atk is None or B in atk["data"]["immune"]
    finally:
        CARDS["Silver"]["types"] = ["treasure"]
        effects.EFFECTS.pop("Silver", None)


def test_cleanup_sweeps_a_reaction_played_on_someone_elses_turn(g):
    """"You discard the card in THAT turn's Clean-up phase" (p53) — the
    attacker's. Left in the reactor's in_play it would still be on the table
    on their own next turn, wrongly counting as a card in play for
    Bank/Peddler/Grand Market/Conspirator."""
    from games.dontminion import effects
    effects.ATTACK_REACTIONS["Village"] = {
        "label": "Play Village", "mode": "play", "repeatable": False}
    try:
        g["seats"][A]["hand"] = ["Militia"]
        g["seats"][B]["hand"] = ["Village", "Copper", "Copper", "Copper", "Copper"]
        assert engine.apply_move(g, A, {"type": "play_action", "card": "Militia"})[0]
        assert engine.apply_move(g, B, {"type": "decision", "ids": ["react:Village"]})[0]
        assert "Village" in g["seats"][B]["in_play"]
        # B answers the Militia, then A ends the turn
        if g["pending_pid"] == B:
            c = g["pending"][-1]["constraint"]
            engine.apply_move(g, B, {"type": "decision",
                                     "cards": c["cards"][:c["min"]]})
        while g["turn"] == A and not g["over"]:
            assert engine.apply_move(g, A, {"type": "end_phase"})[0]
        assert g["seats"][B]["in_play"] == [], \
            "the off-turn reaction survived into its owner's turn"
        assert "Village" in g["seats"][B]["discard"]
    finally:
        effects.ATTACK_REACTIONS.pop("Village", None)


def test_exchange_is_not_a_gain(g):
    """Trader: "you DID gain the card... you DIDN'T gain the Silver." So an
    exchange must fire no `gain` event, or every when-gain watcher on the
    returned card double-fires."""
    seen = []
    from games.dontminion import effects
    effects.TRIGGERS.setdefault("Silver", []).append(
        {"on": "gain", "from": "self", "stage": "boom"})
    effects.STAGES[("Silver", "boom")] = lambda game, pid, frame, choice: seen.append(1)
    try:
        g["seats"][A]["discard"] = ["Estate"]
        before_estate = g["supply"]["Estate"]
        before_silver = g["supply"]["Silver"]
        assert engine.exchange(g, A, "Estate", "Silver") is True
        engine._drive(g)
        assert g["seats"][A]["discard"] == ["Silver"]
        assert g["supply"]["Estate"] == before_estate + 1    # returned to its pile
        assert g["supply"]["Silver"] == before_silver - 1
        assert seen == [], "exchange fired a gain event"
        # empty target pile: nothing happens at all
        g["supply"]["Silver"] = 0
        g["seats"][A]["discard"] = ["Estate"]
        assert engine.exchange(g, A, "Estate", "Silver") is False
        assert g["seats"][A]["discard"] == ["Estate"]
    finally:
        effects.TRIGGERS.pop("Silver", None)
        effects.STAGES.pop(("Silver", "boom"), None)


def test_shuffle_into_deck_shuffles_even_with_zero_cards(g):
    """Inn: "if you shuffle zero cards into your deck, you still shuffle" —
    the shuffle itself randomises deck order, which is the point."""
    g["seats"][A]["deck"] = [f"Copper{i}" for i in range(0)] or ["Copper"] * 6
    g["seats"][A]["deck"] = ["Copper", "Silver", "Gold", "Estate", "Duchy", "Province"]
    g["seats"][A]["discard"] = ["Militia", "Moat"]
    before = list(g["seats"][A]["deck"])
    engine.shuffle_into_deck(g, A, ["Militia"])
    seat = g["seats"][A]
    assert "Militia" in seat["deck"] and "Militia" not in seat["discard"]
    assert seat["discard"] == ["Moat"]
    assert sorted(seat["deck"]) == sorted(before + ["Militia"])

    # zero cards still shuffles (order changes for a deck this size)
    g2 = engine.new_game([A, B], ["base"], seed=11, kingdom=K7)
    g2["seats"][A]["deck"] = [f"C{i}" for i in range(20)]
    snap = list(g2["seats"][A]["deck"])
    engine.shuffle_into_deck(g2, A, [])
    assert sorted(g2["seats"][A]["deck"]) == sorted(snap)
    assert g2["seats"][A]["deck"] != snap, "a zero-card shuffle did not shuffle"


def test_cleanup_discard_is_a_SEPARATE_event_from_discard(g, synthetic):
    """Scheme triggers on the Clean-up discard from play. It must be its own
    event: Tunnel/Trail/Weaver are all "other than during a Clean-up phase" and
    must NOT see it.

    LIMITATION, pinned deliberately: the event fires, but `emit` parks an AUTO
    FRAME and `_end_turn` does not drive frames before sweeping the table, so a
    consumer cannot yet MOVE the card (Scheme topdecking it). Implementing
    Scheme needs the interruptible `_end_turn` — see the ledger."""
    trigger, stage = synthetic
    cleanup_hits, discard_hits = [], []
    trigger("Copper", [{"on": "cleanup_discard", "from": "self", "stage": "cu"}][0])
    stage(("Copper", "cu"), lambda game, pid, frame, choice:
          cleanup_hits.append(frame["data"]["subject"]))
    trigger("Silver", {"on": "discard", "from": "self", "stage": "d"})
    stage(("Silver", "d"), lambda game, pid, frame, choice: discard_hits.append(1))

    g["seats"][A]["hand"] = ["Copper", "Silver"]
    g["seats"][A]["in_play"] = []
    assert engine.apply_move(g, A, {"type": "end_phase"})[0]     # -> buy
    assert engine.apply_move(g, A, {"type": "play_treasure", "card": "Copper"})[0]
    assert engine.apply_move(g, A, {"type": "end_phase"})[0]     # clean-up

    assert cleanup_hits == ["Copper"], "the in-play card fired no cleanup_discard"
    assert discard_hits == [], "a Clean-up discard fired the ordinary discard event"


def test_a_protected_player_is_still_offered_a_non_immunity_reaction():
    """AUDIT BUG: _open_attack_window skipped already-immune opponents entirely,
    so a Lighthouse-protected Guard Dog holder was never asked — losing pure
    upside on every attack. Compendium p53: the reaction "triggers whenever an
    Attack card is played, no matter if the card would have any effect on you."
    A protected player holding only a MOAT must still be offered nothing,
    though: revealing it would gain them precisely nothing."""
    from games.dontminion import effects
    K = ["Guard Dog", "Margrave", "Lighthouse", "Moat", "Village", "Smithy",
         "Militia", "Market", "Festival", "Laboratory"]

    def protected_game(bob_hand):
        gg = engine.new_game([A, B], ["base", "seaside", "hinterlands"],
                             seed=5, kingdom=K)
        gg["turn"] = B
        gg["seats"][B]["hand"] = ["Lighthouse"]
        engine.apply_move(gg, B, {"type": "play_action", "card": "Lighthouse"})
        while gg["turn"] == B and not gg["over"]:
            engine.apply_move(gg, B, {"type": "end_phase"})
        assert engine.attack_protected(gg, B)
        gg["turn"], gg["phase"], gg["actions"] = A, "action", 1
        gg["seats"][B]["hand"] = list(bob_hand)
        gg["seats"][A]["hand"] = ["Margrave"]
        engine.apply_move(gg, A, {"type": "play_action", "card": "Margrave"})
        return gg

    g1 = protected_game(["Guard Dog", "Estate", "Estate"])
    assert g1["pending_pid"] == B, "protected Guard Dog holder was never asked"
    assert "react:Guard Dog" in [o["id"] for o
                                 in g1["pending"][-1]["constraint"]["options"]]

    g2 = protected_game(["Moat", "Estate", "Estate"])
    ids = ([o["id"] for o in g2["pending"][-1]["constraint"]["options"]]
           if g2["pending_pid"] == B else [])
    assert "react:Moat" not in ids, "offered a pointless Moat to an immune player"


@pytest.mark.parametrize("attack", ["Margrave", "Witch's Hut", "Berserker", "Militia"])
def test_lighthouse_protection_blocks_every_attack(attack):
    """AUDIT TEST-GAP: every immunity test in the card files used MOAT, so the
    Lighthouse path (`immune0`, computed before any window opens) was untested
    for all four attacks — which is how the protected-Guard-Dog bug hid. Moat
    and Lighthouse reach immunity by DIFFERENT routes; both need pinning."""
    K = ["Margrave", "Witch's Hut", "Berserker", "Lighthouse", "Guard Dog",
         "Militia", "Village", "Smithy", "Market", "Laboratory"]
    gg = engine.new_game([A, B], ["base", "seaside", "hinterlands"],
                         seed=3, kingdom=K)
    gg["turn"] = B
    gg["seats"][B]["hand"] = ["Lighthouse"]
    engine.apply_move(gg, B, {"type": "play_action", "card": "Lighthouse"})
    while gg["turn"] == B and not gg["over"]:
        engine.apply_move(gg, B, {"type": "end_phase"})
    assert engine.attack_protected(gg, B)

    gg["turn"], gg["phase"], gg["actions"] = A, "action", 1
    gg["seats"][B]["hand"] = ["Estate", "Estate", "Estate", "Estate", "Estate"]
    gg["seats"][B]["discard"] = []
    hand_before = list(gg["seats"][B]["hand"])
    curses_before = gg["supply"]["Curse"]
    gg["seats"][A]["hand"] = [attack]
    ok, err = engine.apply_move(gg, A, {"type": "play_action", "card": attack})
    assert ok, err
    # drive any decisions the ATTACKER owes (Berserker's gain, Witch's Hut's discard)
    for _ in range(12):
        if gg["pending_pid"] != A:
            break
        engine.apply_move(gg, A, {"type": "decision",
                                  **engine.sample_decision(gg, A, random.Random(1))})

    assert gg["seats"][B]["hand"] == hand_before, f"{attack} hit a protected player"
    assert "Curse" not in gg["seats"][B]["discard"]
    assert gg["supply"]["Curse"] == curses_before or attack == "Militia"


def test_scheme_can_topdeck_a_duration_finishing_this_cleanup():
    """AUDIT BUG: the candidate list read `in_play` only, so a Duration whose
    last ability resolved — discarded from play by THIS clean-up, sitting in
    the duration zone marked done — was never offered, though it is as much
    "discarded from play" as anything in in_play."""
    K = ["Scheme", "Fishing Village", "Village", "Smithy", "Market", "Festival",
         "Laboratory", "Moat", "Militia", "Cellar"]
    gg = engine.new_game([A, B], ["base", "seaside", "hinterlands"],
                         seed=9, kingdom=K)
    gg["seats"][A]["hand"] = ["Fishing Village"]
    engine.apply_move(gg, A, {"type": "play_action", "card": "Fishing Village"})
    while gg["turn"] == A and not gg["over"]:
        engine.apply_move(gg, A, {"type": "end_phase"})
    while gg["turn"] == B and not gg["over"]:
        engine.apply_move(gg, B, {"type": "end_phase"})
    assert [e["card"] for e in gg["seats"][A]["duration"]] == ["Fishing Village"]

    gg["seats"][A]["hand"] = ["Scheme"]
    gg["phase"], gg["actions"] = "action", 1
    engine.apply_move(gg, A, {"type": "play_action", "card": "Scheme"})
    engine.apply_move(gg, A, {"type": "end_phase"})       # buy_phase_end
    assert gg["pending"][-1]["card"] == "Scheme"
    assert "Fishing Village" in gg["pending"][-1]["constraint"]["cards"]

    # ...and choosing it really moves it out of the duration zone onto the
    # deck. Clean-up then draws the new hand off that deck, so the card lands
    # in hand rather than sitting on top — which is the whole point of Scheme.
    engine.apply_move(gg, A, {"type": "decision", "cards": ["Fishing Village"]})
    seat = gg["seats"][A]
    assert all(e["card"] != "Fishing Village" for e in seat["duration"])
    assert "Fishing Village" not in seat["discard"], "it was discarded, not kept"
    assert "Fishing Village" in seat["hand"] or seat["deck"][:1] == ["Fishing Village"]


def test_cost_lt_is_strict(g):
    assert engine.cost_lt(g, "Estate", 3) and not engine.cost_lt(g, "Estate", 2)
    assert engine.cost_le(g, "Estate", 2)          # le includes equal, lt doesn't


def test_buy_event_reaches_in_play_triggers(g, synthetic):
    trigger, _ = synthetic
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


def test_hand_reaction_window_shape(g, synthetic):
    trigger, stage = synthetic
    taken = []
    trigger("Moat", {"on": "gain", "from": "hand", "stage": "react",
                     "when": lambda game, pid, ctx: ctx["subject"] == "Silver"})
    stage(("Moat", "react"), lambda game, pid, frame, choice:
          taken.append((pid, choice["ids"][0])))
    g["seats"][B]["hand"] = ["Moat"]
    engine.gain(g, A, "Silver")
    # emit() parks consumers as an ability-pool auto; a real move drives it via
    # apply_move, a direct engine.gain in a test drives it here
    engine._drive(g)
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
    trigger, stage = synthetic
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
    trigger, stage = synthetic
    _register_traderx(trigger, stage)
    g["seats"][A]["hand"] = ["Moat"]
    silver0 = g["supply"]["Silver"]
    assert engine.gain(g, A, "Silver")
    ok, err = engine.apply_move(g, A, {"type": "decision", "ids": ["decline"]})
    assert ok, err
    assert g["supply"]["Silver"] == silver0 - 1  # the parked gain resolved
    assert "Silver" in g["seats"][A]["discard"]


def test_would_gain_only_intercepts_the_gainer(g, synthetic):
    trigger, stage = synthetic
    _register_traderx(trigger, stage)
    g["seats"][B]["hand"] = ["Moat"]             # the OTHER player holds it
    assert engine.gain(g, A, "Silver")
    assert g["pending_pid"] is None              # no window: A gains directly
    assert "Silver" in g["seats"][A]["discard"]


# --- lose-track must never be SILENT -------------------------------------------

def _calls(node, name):
    import ast
    return any(isinstance(n, ast.Call)
               and getattr(n.func, "attr", getattr(n.func, "id", None)) == name
               for n in ast.walk(node))


def test_every_find_card_zone_guard_logs_lost_track():
    """A lose-track guard that just `return`s makes a prompt vanish with no
    explanation — indistinguishable from a broken trigger, which is exactly how
    the Trail x Tide Pools interaction got reported as a bug. Source-level,
    because there is NO runtime signal: correct behaviour and the silent-skip
    bug leave identical game state.

    AST, not a regex over a line window — the first version of this test used a
    6-line window and comments pushed two real call sites out of it, so it
    passed while checking 5 of 7 guards.

    Scope is exactly `find_card_zone(...)` guards. A lose-track check written
    another way (Watchtower's `card not in seat[dest]`) is not mechanically
    detectable; those are covered by their own tests.
    """
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    guards, offenders = 0, []

    def is_zone_finder(call):
        fn = getattr(call.func, "attr", getattr(call.func, "id", ""))
        return fn == "find_card_zone" or fn.endswith("_zone")

    for path in sorted(root.glob("effects_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            # BOTH guard shapes are in use and the first version of this test
            # only saw one: `if find_card_zone(...) is None:` inline, and
            # `zone = find_card_zone(...)` followed by `if zone is None:`.
            zone_names = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
                          for t in n.targets if isinstance(t, ast.Name)
                          if isinstance(n.value, ast.Call) and is_zone_finder(n.value)}
            for node in ast.walk(fn):
                if not isinstance(node, ast.If):
                    continue
                inline = any(is_zone_finder(c) for c in ast.walk(node.test)
                             if isinstance(c, ast.Call))
                via_name = any(isinstance(n, ast.Name) and n.id in zone_names
                               for n in ast.walk(node.test))
                if not (inline or via_name):
                    continue
                # only the "bail out" shape — a guard that goes on to USE the
                # zone it found isn't skipping anything
                if not any(isinstance(n, ast.Return) for n in ast.walk(node)):
                    continue
                guards += 1
                if not _calls(node, "lost_track"):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert guards >= 6, f"only found {guards} guards — the scan stopped working"
    assert not offenders, (
        "silent lose-track guard(s) — call E.lost_track(game, pid, card[, verb]) "
        "so the player is told why the ability was skipped: " + ", ".join(offenders))
