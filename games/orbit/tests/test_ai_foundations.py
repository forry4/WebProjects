"""Information-boundary, archive, chance and generated-data gates (no Rust needed).

Native compilation and full transition parity run in rust-orbit.yml; this suite
always runs and never conditionally skips when a local toolchain is absent.
"""
import copy
import json
import random
from collections import Counter

import pytest

from games.orbit import engine as E
from games.orbit.ai.belief import sample_hidden
from games.orbit.ai.history import Session
from games.orbit.ai.state import action_key, native_state, observation, rules_fingerprint
from games.orbit.cards import CARDS, BONUS_POOL
from games.orbit.tools.export_native import OUTPUT, render
from games.orbit.tools.native_parity import actor, first_difference


def test_generated_data_is_current_and_rule_changes_invalidate_artifacts():
    assert OUTPUT.read_text(encoding="utf-8") == render()
    assert json.loads(render())["rules"] == rules_fingerprint()
    session = Session(E.new_game(["A", "B"], seed=3))
    archive = session.archive()
    archive["rules"] = "old rules"
    with pytest.raises(ValueError, match="rules/schema"):
        Session.restore(archive)


def test_different_hidden_worlds_have_identical_policy_inputs_and_samples():
    g = E.new_game(["A", "B"], seed=5)
    me, other = g["order"]
    before = copy.deepcopy(g)
    equivalent = copy.deepcopy(g)
    equivalent["players"][other]["hand"][0], equivalent["agent_deck"][0] = (
        equivalent["agent_deck"][0], equivalent["players"][other]["hand"][0])
    equivalent["agent_deck"].reverse()
    equivalent["bonus_deck"].reverse()
    equivalent["rng_state"] = ["SECRET_RNG"]
    equivalent["log"] = [{"message": "SECRET_LOG"}]
    equivalent["future_secret"] = "SECRET_ADDED_FIELD"
    equivalent["players"][other]["future_secret"] = "SECRET_PLAYER_FIELD"
    a, z = observation(g, me), observation(equivalent, me)
    assert a == z
    assert sample_hidden(a, random.Random(4)) == sample_hidden(z, random.Random(4))
    assert "SECRET" not in json.dumps(z)
    assert g == before
    z["players"][0]["credits"] += 20
    assert g == before, "Policy input must not alias live state"


def test_private_pending_queue_is_not_a_policy_feature():
    g = E.new_game(["A", "B"], seed=3)
    for pid in g["order"]:
        E.apply_move(g, pid, {"action": "mulligan", "card_ids": []})
    me, other = g["order"]
    g["pending_pid"] = other
    g["pending"] = {"source": "test", "context": {"secret": "SECRET_CONTEXT"}, "queue": [
        {"type": "discard_hand", "actor": other, "count": 1, "secret": "SECRET_TASK"},
        {"type": "credits", "actor": other, "amount": 1, "secret": "SECRET_FUTURE"},
    ]}
    a = observation(g, me)
    assert a["pending"] == {"source": "test", "waiting": True}
    assert a["legal_moves"] == []
    assert "SECRET" not in json.dumps(a)
    own = observation(g, other)
    assert own["pending"]["task"]["type"] == "discard_hand"
    assert "SECRET" not in json.dumps(own)
    assert set(m["card_id"] for m in own["legal_moves"]) == set(g["players"][other]["hand"])


def test_terminal_observation_does_not_gain_opponent_private_information():
    g = E.new_game(["A", "B"], seed=17)
    me, other = g["order"]
    g["phase"] = "over"
    obs = observation(g, me)
    assert "hand" not in obs["players"][1]
    assert len(E.player_view(g, me)["players"][other]["hand"]) == 4
    assert obs["legal_moves"] == []


def test_sampler_conserves_all_cards_and_bonus_multiplicities_through_a_game():
    g = E.new_game(["A", "B"], seed=37, configuration="random")
    chooser = random.Random(110)
    for _ in range(1500):
        if E.is_over(g):
            break
        for pid in g["order"]:
            obs = observation(g, pid)
            sample = sample_hidden(obs, chooser)
            cards = list(obs["players"][obs["seat"]]["hand"]) + obs["agent_discard"]
            for p in obs["players"]:
                for column in p["columns"]:
                    cards += column
            cards += sample["opponent_hand"] + sample["agent_deck"]
            assert sorted(cards) == sorted(CARDS)
            bonuses = sample["bonus_deck"] + obs["bonus_discard"]
            bonuses += [v for v in obs["planet_bonus"] + obs["technology_bonus"] if v is not None]
            assert Counter(bonuses) == Counter(BONUS_POOL)
        pid = actor(g)
        assert E.apply_move(g, pid, chooser.choice(E.legal_moves(g, pid)))[0]
    assert E.is_over(g)


def test_sampler_rejects_inconsistent_observations_and_varies_unknown_hand():
    obs = observation(E.new_game(["A", "B"], seed=11), "A")
    hands = {tuple(sample_hidden(obs, random.Random(seed))["opponent_hand"]) for seed in range(20)}
    assert len(hands) > 15
    obs["agent_deck_count"] += 1
    with pytest.raises(ValueError, match="counts"):
        sample_hidden(obs, random.Random(0))


def test_sampler_matches_an_enumerable_two_card_information_set():
    g = E.new_game(["A", "B"], seed=71)
    me, other = g["order"]
    # Expose every previously unknown card except a single opposing hand card
    # and a single deck card. There are exactly two feasible assignments.
    for card_id in g["players"][other]["hand"][1:]:
        g["players"][other]["columns"][CARDS[card_id]["planet"]].append(card_id)
    g["players"][other]["hand"] = g["players"][other]["hand"][:1]
    for card_id in g["agent_deck"][1:]:
        g["players"][me]["columns"][CARDS[card_id]["planet"]].append(card_id)
    g["agent_deck"] = g["agent_deck"][:1]
    E.validate_state(g)
    obs = observation(g, me)
    possibilities = set(g["players"][other]["hand"] + g["agent_deck"])
    counts = Counter(sample_hidden(obs, random.Random(seed))["opponent_hand"][0] for seed in range(1000))
    assert set(counts) == possibilities
    assert all(400 < count < 600 for count in counts.values())


def test_history_survives_json_restore_and_retains_more_than_display_log():
    session = Session(E.new_game(["A", "B"], seed=1))
    rng = random.Random(612)
    restored = None
    for i in range(1500):
        if E.is_over(session.game):
            break
        pid = actor(session.game)
        mv = rng.choice(E.legal_moves(session.game, pid))
        assert session.step(pid, mv)[0]
        if i == 10:
            restored = Session.restore(json.loads(json.dumps(session.archive())))
        elif restored is not None:
            assert restored.step(pid, mv)[0]
            for viewer in session.game["order"]:
                assert restored.policy_input(viewer) == session.policy_input(viewer)
    assert E.is_over(session.game)
    assert restored is not None
    assert len(session.game["log"]) == E.LOG_CAP, "Fixture must actually hit display truncation"
    assert session.game["log"][0]["turn"] > 0, "Mulligan events must have been evicted"
    for viewer in session.game["order"]:
        history = session.policy_input(viewer)["history"]
        assert len(history["events"]) == i
        assert history["initial"]["phase"] == "mulligan"
        reconstructed = copy.deepcopy(history["initial"])
        for event in history["events"]:
            reconstructed.update(event["changes"])
        assert reconstructed == observation(session.game, viewer)


def test_history_private_actions_invalid_move_and_corruption():
    session = Session(E.new_game(["A", "B"], seed=8))
    me, other = session.game["order"]
    card = session.game["players"][me]["hand"][0]
    assert session.step(me, {"action": "mulligan", "card_ids": [card]})[0]
    assert "own_action" in session.policy_input(me)["history"]["events"][0]
    assert "own_action" not in session.policy_input(other)["history"]["events"][0]
    assert session.policy_input(other)["history"]["events"][0]["public_action"] == {"action": "mulligan", "count": 1}
    before = session.archive()
    assert not session.step(me, {"action": "mulligan", "card_ids": []})[0]
    assert before == session.archive()
    bad = copy.deepcopy(before)
    bad["histories"][me]["initial"]["seat"] = 99
    with pytest.raises(ValueError, match="reconstruct"):
        Session.restore(bad)


def test_history_remembers_a_public_card_after_same_action_reshuffle():
    g = E.new_game(["A", "B"], seed=19)
    for pid in g["order"]:
        E.apply_move(g, pid, {"action": "mulligan", "card_ids": []})
    me, other = g["order"]
    # Put the entire remaining deck into public columns. The chosen leader card
    # is now the only discard: turn-end refill shuffles and immediately draws it.
    for card_id in g["agent_deck"]:
        g["players"][other]["columns"][CARDS[card_id]["planet"]].append(card_id)
    g["agent_deck"] = []
    # Human/robot leader actions do not mobilize the lone card into a column.
    card_id = next(cid for cid in g["players"][me]["hand"] if CARDS[cid]["faction"] != "animod")
    session = Session(g)
    mv = {"action": "leader", "card_id": card_id}
    assert session.step(me, mv)[0]
    assert card_id in session.game["players"][me]["hand"]
    assert card_id not in session.game["agent_discard"]
    public_event = session.policy_input(other)["history"]["events"][-1]
    assert public_event["public_action"] == mv
    assert "own_action" not in public_event


def test_move_identity_and_parity_comparator_are_not_vacuous():
    assert action_key({"action": "choose", "accept": True}) != action_key({"action": "choose", "accept": False})
    assert action_key({"action": "choose", "cost": 3, "amount": 1}) != action_key({"action": "choose", "cost": 7, "amount": 2})
    before = native_state(E.new_game(["A", "B"], seed=5))
    after = copy.deepcopy(before)
    assert first_difference(before, after) is None
    after["players"][0]["credits"] += 1
    assert "credits" in first_difference(before, after)
    after = copy.deepcopy(before)
    after["pending_pid"] = 1
    assert "pending_pid" in first_difference(before, after)
