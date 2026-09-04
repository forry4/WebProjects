from __future__ import annotations

import copy
import random

from games.orbit import engine as E
from games.orbit.cards import BONUS_POOL, CARDS, FACTIONS, PLANETS, TECHNOLOGIES


def finish_mulligan(game):
    for pid in list(game["players"]):
        assert E.apply_move(game, pid, {"action": "mulligan", "card_ids": []})[0]


def resolve_randomly(game, seed=1, cap=500):
    rng = random.Random(seed)
    for _ in range(cap):
        if not game.get("pending") or E.is_over(game):
            return
        pid = game["pending_pid"]
        moves = E.legal_moves(game, pid)
        assert moves
        assert E.apply_move(game, pid, rng.choice(moves))[0]
    raise AssertionError("effect resolution did not terminate")


def test_reference_is_complete():
    assert len(CARDS) == 90
    assert len(TECHNOLOGIES) == 30
    assert len(BONUS_POOL) == 16
    for planet in PLANETS:
        for faction in FACTIONS:
            assert sum(c["planet"] == planet and c["faction"] == faction for c in CARDS.values()) == 6


def test_setup_and_mulligan_contract():
    game = E.new_game(["A", "B"], seed=8)
    assert game["phase"] == "mulligan"
    assert game["board_sides"] == {"robot": 1, "human": 1, "animod": 1}
    assert {len(p["hand"]) for p in game["players"].values()} == {4}
    assert all(p["credits"] == 12 and p["zenithium"] == 1 for p in game["players"].values())
    assert game["influence"]["terra"] == -1
    assert len([v for v in game["planet_bonus"].values() if v]) == 5
    assert len([v for v in game["technology_bonus"].values() if v]) == 3
    first = game["order"][0]
    replaced = list(game["players"][first]["hand"][:2])
    assert E.apply_move(game, first, {"action": "mulligan", "card_ids": sorted(replaced)})[0]
    other = game["order"][1]
    assert E.apply_move(game, other, {"action": "mulligan", "card_ids": []})[0]
    assert game["phase"] == "play" and game["turn_pid"] == first
    E.validate_state(game)


def test_recruit_discount_base_influence_and_effect():
    game = E.new_game(["A", "B"], seed=2)
    finish_mulligan(game)
    pid = game["turn_pid"]
    # Cresus: Venus, cost 1, +6 Credits after the universal Venus influence.
    card_id = 209
    old = game["players"][pid]["hand"][0]
    game["players"][pid]["hand"][0] = card_id
    game["agent_deck"][game["agent_deck"].index(card_id)] = old
    assert E.apply_move(game, pid, {"action": "recruit", "card_id": card_id})[0]
    assert game["players"][pid]["credits"] == 17
    direction = 1 if pid == game["order"][0] else -1
    assert game["influence"]["venus"] == direction
    E.validate_state(game)


def test_technology_cascades_level_two_bonus_then_level_one():
    game = E.new_game(["A", "B"], seed=11, configuration={"robot": 1, "human": 1, "animod": 1})
    finish_mulligan(game)
    pid = game["turn_pid"]
    player = game["players"][pid]
    player["technology"]["robot"] = 1
    player["zenithium"] = 10
    token = game["technology_bonus"]["robot"]
    card_id = next((cid for cid in player["hand"] if CARDS[cid]["faction"] == "robot"), None)
    if card_id is None:
        card_id = next(c["id"] for c in CARDS.values() if c["faction"] == "robot")
        displaced = player["hand"][0]
        player["hand"][0] = card_id
        game["agent_deck"][game["agent_deck"].index(card_id)] = displaced
    assert E.apply_move(game, pid, {"action": "technology", "card_id": card_id})[0]
    resolve_randomly(game)
    assert player["technology"]["robot"] == 2
    assert game["technology_bonus"]["robot"] is None
    assert token in game["bonus_discard"]
    assert game["leader"]["owner"] == pid
    E.validate_state(game)


def test_capture_bonus_and_all_three_victory_conditions():
    for captures in (
        ["mars", "mars"],
        ["mercury", "venus", "terra"],
        ["mercury", "mercury", "venus", "terra"],
    ):
        game = E.new_game(["A", "B"], seed=17)
        finish_mulligan(game)
        pid = game["turn_pid"]
        game["players"][pid]["captured"] = captures
        target = "mars" if captures[0] == "mars" else ("jupiter" if len(set(captures)) >= 3 else "venus")
        game["influence"][target] = 3
        game["planet_bonus"][target] = None
        E._gain_influence(game, pid, target, 1)
        assert E.is_over(game) and E.winner(game) == pid


def test_hidden_information_is_redacted_from_a_real_pending_game():
    game = E.new_game(["A", "B"], seed=4)
    finish_mulligan(game)
    me = game["turn_pid"]
    other = E._opponent(game, me)
    view = E.player_view(game, me)
    assert "agent_deck" not in view and "bonus_deck" not in view and "rng_state" not in view
    assert all(card.get("hidden") for card in view["players"][other]["hand"])
    assert all("name" in card for card in view["players"][me]["hand"])


def test_exile_tier_is_mandatory_when_a_threshold_is_available():
    game = E.new_game(["A", "B"], seed=4)
    finish_mulligan(game)
    pid = game["turn_pid"]
    game["players"][pid]["columns"]["mercury"] = [101, 102, 103, 104]
    game["pending_pid"] = pid
    game["pending"] = {
        "source": "test",
        "queue": [{"type": "exile_tier", "actor": pid, "planet": "mercury", "reward": "zenithium"}],
        "context": {},
    }
    moves = E.legal_moves(game, pid)
    assert {move["tier"] for move in moves} == {2, 4}


def test_seeded_random_soak_plays_complete_games():
    for seed in range(25):
        rng = random.Random(seed * 97)
        game = E.new_game(["A", "B"], seed=seed, configuration="random")
        for _ in range(1000):
            if E.is_over(game):
                break
            if game["phase"] == "mulligan":
                pid = next(p for p in game["players"] if p not in game["mulligan_done"])
            else:
                pid = game["pending_pid"] if game.get("pending") else game["turn_pid"]
            moves = E.legal_moves(game, pid)
            assert moves
            assert E.apply_move(game, pid, rng.choice(moves))[0]
            E.validate_state(game)
        assert E.is_over(game)


def test_illegal_move_is_atomic():
    game = E.new_game(["A", "B"], seed=2)
    before = copy.deepcopy(game)
    assert E.apply_move(game, "A", {"action": "recruit", "card_id": 999}) == (False, "Illegal move")
    assert game == before
