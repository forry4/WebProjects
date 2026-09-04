"""Pure, server-authoritative rules engine for Orbit (Zenith, 2025).

The state is a plain JSON-safe dictionary.  Every forced or optional sub-choice
is persisted in ``pending`` and exposed only as validated legal moves; clients
render the game but never calculate outcomes.
"""

from __future__ import annotations

import copy
import itertools
import random
from typing import Iterable

from .boards import SUN_CONFIGURATION, board_reference, random_configuration
from .cards import BONUS_POOL, BONUS_TYPES, CARDS, FACTIONS, PLANETS, public_card
from .effects import bonus_effects, card_effects, technology_effects


STARTING_CREDITS = 12
STARTING_ZENITHIUM = 1
BASE_HAND_LIMIT = 4
CONTROL_POSITION = 4


def _make_rng(game: dict) -> random.Random:
    rng = random.Random()
    state = game.get("rng_state")
    if state is not None:
        rng.setstate((state[0], tuple(state[1]), state[2]))
    return rng


def _save_rng(game: dict, rng: random.Random) -> None:
    state = rng.getstate()
    game["rng_state"] = [state[0], list(state[1]), state[2]]


def _opponent(game: dict, pid: str) -> str:
    first, second = game["order"]
    return second if pid == first else first


def _player(game: dict, pid: str) -> dict:
    return game["players"][pid]


def _log(game: dict, message: str, **data) -> None:
    game["log"].append({"turn": game["turn_number"], "message": message, **data})
    if len(game["log"]) > 300:
        del game["log"][:-300]


def _draw_agent(game: dict) -> int | None:
    if not game["agent_deck"]:
        if not game["agent_discard"]:
            return None
        rng = _make_rng(game)
        rng.shuffle(game["agent_discard"])
        game["agent_deck"] = game["agent_discard"]
        game["agent_discard"] = []
        _save_rng(game, rng)
    return game["agent_deck"].pop()


def _draw_to(game: dict, pid: str, limit: int) -> None:
    hand = _player(game, pid)["hand"]
    while len(hand) < limit:
        card_id = _draw_agent(game)
        if card_id is None:
            return
        hand.append(card_id)


def _leader_limit(game: dict, pid: str) -> int:
    leader = game["leader"]
    if leader["owner"] != pid:
        return BASE_HAND_LIMIT
    return 6 if leader["level"] >= 2 else 5


def _gain_leader(game: dict, pid: str, requested_level: int = 1) -> None:
    badge = game["leader"]
    if requested_level >= 2:
        badge.update(owner=pid, level=2)
    elif badge["owner"] == pid:
        badge["level"] = min(2, badge["level"] + 1)
    else:
        badge.update(owner=pid, level=1)
    _log(game, f"{game['names'][pid]} takes the Leader badge.", pid=pid)


def _give_up_leader(game: dict, pid: str) -> None:
    if game["leader"]["owner"] == pid:
        game["leader"] = {"owner": None, "level": 0}
        _log(game, f"{game['names'][pid]} gives up the Leader badge.", pid=pid)


def _winner_pid(game: dict) -> str | None:
    for pid, player in game["players"].items():
        captured = player["captured"]
        if any(captured.count(planet) >= 3 for planet in PLANETS):
            return pid
        if len(set(captured)) >= 4:
            return pid
        if len(captured) >= 5:
            return pid
    return None


def _check_victory(game: dict) -> bool:
    victor = _winner_pid(game)
    if victor is None:
        return False
    game["phase"] = "over"
    game["winner"] = victor
    game["pending"] = None
    game["pending_pid"] = None
    _log(game, f"{game['names'][victor]} wins Orbit.", pid=victor)
    return True


def _queue_tasks(game: dict, tasks: Iterable[dict], actor: str, *, front: bool = True) -> None:
    prepared = []
    for raw in copy.deepcopy(list(tasks)):
        raw.setdefault("actor", actor)
        prepared.append(raw)
    if not prepared:
        return
    queue = game["pending"]["queue"]
    if front:
        queue[0:0] = prepared
    else:
        queue.extend(prepared)


def _draw_bonus_type(game: dict) -> int | None:
    if not game["bonus_deck"]:
        if not game["bonus_discard"]:
            return None
        rng = _make_rng(game)
        rng.shuffle(game["bonus_discard"])
        game["bonus_deck"] = game["bonus_discard"]
        game["bonus_discard"] = []
        _save_rng(game, rng)
    return game["bonus_deck"].pop()


def _award_bonus(game: dict, pid: str, token_type: int) -> None:
    game["bonus_discard"].append(token_type)
    _log(
        game,
        f"{game['names'][pid]} resolves a bonus: {BONUS_TYPES[token_type]['description']}.",
        pid=pid,
        bonus=token_type,
    )
    _queue_tasks(game, bonus_effects(token_type), pid)


def _capture(game: dict, pid: str, planet: str) -> list[dict]:
    player = _player(game, pid)
    player["captured"].append(planet)
    game["captured_this_turn"].append(planet)
    game["influence"][planet] = None
    _log(game, f"{game['names'][pid]} captures {planet.title()}.", pid=pid, planet=planet)
    if _check_victory(game):
        return []
    token = game["planet_bonus"].get(planet)
    if token is None:
        return []
    game["planet_bonus"][planet] = None
    game["bonus_discard"].append(token)
    _log(
        game,
        f"{game['names'][pid]} claims {planet.title()}'s bonus.",
        pid=pid,
        planet=planet,
        bonus=token,
    )
    return bonus_effects(token)


def _gain_influence(game: dict, pid: str, planet: str, amount: int) -> list[dict]:
    """Move one disc step at a time and return any immediate bonus tasks."""

    if amount <= 0 or game["influence"][planet] is None:
        return []
    direction = 1 if pid == game["order"][0] else -1
    gained_tasks: list[dict] = []
    for _ in range(amount):
        position = game["influence"][planet]
        if position is None:
            break
        position += direction
        game["influence"][planet] = position
        if abs(position) >= CONTROL_POSITION:
            gained_tasks.extend(_capture(game, pid, planet))
            break
    return gained_tasks


def _columns(game: dict, pid: str) -> dict[str, list[int]]:
    return _player(game, pid)["columns"]


def _top_candidates(
    game: dict,
    pid: str,
    owner: str,
    *,
    exclude: str | None = None,
    allowed: list[str] | None = None,
    used: list[str] | None = None,
) -> list[str]:
    target_pid = pid if owner == "self" else _opponent(game, pid)
    columns = _columns(game, target_pid)
    return [
        planet
        for planet in PLANETS
        if columns[planet]
        and planet != exclude
        and (allowed is None or planet in allowed)
        and (used is None or planet not in used)
    ]


def _eligible_planets(game: dict, pid: str, task: dict) -> list[str]:
    choices = [
        planet
        for planet in PLANETS
        if planet != task.get("exclude") and game["influence"][planet] is not None
    ]
    restriction = task.get("restriction")
    if restriction == "middle":
        choices = [planet for planet in choices if game["influence"][planet] == 0]
    elif restriction in ("opponent_side", "dominated"):
        direction = 1 if pid == game["order"][0] else -1
        choices = [
            planet
            for planet in choices
            if game["influence"][planet] is not None
            and game["influence"][planet] * direction < 0
        ]
    if task.get("distinct_from"):
        choices = [p for p in choices if p not in task["distinct_from"]]
    return choices


def _pay_cost(game: dict, pid: str, cost: dict) -> bool:
    player = _player(game, pid)
    resource = cost["resource"]
    amount = int(cost.get("amount", 1))
    if resource == "leader":
        if game["leader"]["owner"] != pid:
            return False
        _give_up_leader(game, pid)
        return True
    if resource == "credits_to_opponent":
        if player["credits"] < amount:
            return False
        player["credits"] -= amount
        _player(game, _opponent(game, pid))["credits"] += amount
        return True
    if resource == "zenithium_to_opponent":
        if player["zenithium"] < amount:
            return False
        player["zenithium"] -= amount
        _player(game, _opponent(game, pid))["zenithium"] += amount
        return True
    if player[resource] < amount:
        return False
    player[resource] -= amount
    if resource == "zenithium_to_opponent":
        _player(game, _opponent(game, pid))["zenithium"] += amount
    return True


def _can_pay(game: dict, pid: str, cost: dict) -> bool:
    resource = cost["resource"]
    amount = int(cost.get("amount", 1))
    if resource == "leader":
        return game["leader"]["owner"] == pid
    if resource == "credits_to_opponent":
        resource = "credits"
    elif resource == "zenithium_to_opponent":
        resource = "zenithium"
    return _player(game, pid).get(resource, 0) >= amount


def _develop_tasks(game: dict, pid: str, faction: str) -> list[dict]:
    player = _player(game, pid)
    level = player["technology"][faction]
    side = game["board_sides"][faction]
    tasks: list[dict] = []
    for resolved_level in range(level, 0, -1):
        tasks.extend(technology_effects(faction, side, resolved_level))
        if resolved_level == 2 and game["technology_bonus"].get(faction) is not None:
            tasks.append({"type": "fixed_bonus", "faction": faction})
    tasks.append({"type": "row_bonus_check"})
    return tasks


def _advance_technology(game: dict, pid: str, faction: str, discount: int = 0) -> bool:
    player = _player(game, pid)
    old_level = player["technology"][faction]
    if old_level >= 5:
        return False
    cost = max(0, old_level + 1 - discount)
    if player["zenithium"] < cost:
        return False
    player["zenithium"] -= cost
    player["technology"][faction] = old_level + 1
    _log(
        game,
        f"{game['names'][pid]} develops {faction.title()} technology to level {old_level + 1}.",
        pid=pid,
        faction=faction,
        level=old_level + 1,
    )
    _queue_tasks(game, _develop_tasks(game, pid, faction), pid)
    return True


def _discard_top(game: dict, owner_pid: str, planet: str) -> int:
    card_id = _columns(game, owner_pid)[planet].pop()
    game["agent_discard"].append(card_id)
    return card_id


def _transfer_top(game: dict, pid: str, planet: str) -> int:
    card_id = _columns(game, _opponent(game, pid))[planet].pop()
    _columns(game, pid)[planet].append(card_id)
    return card_id


def _task_possible(game: dict, pid: str, task: dict) -> bool:
    kind = task["type"]
    if kind == "transfer":
        return bool(_top_candidates(game, pid, "opponent"))
    if kind in ("influence", "influence_other"):
        if task.get("planet"):
            return game["influence"][task["planet"]] is not None
        probe = task
        if kind == "influence_other":
            probe = {**task, "distinct_from": [game["pending"]["context"].get("last_planet")]}
        return bool(_eligible_planets(game, pid, probe))
    return True


def _choice_moves(game: dict, task: dict) -> list[dict]:
    pid = task["actor"]
    kind = task["type"]
    if kind in ("influence", "influence_other"):
        probe = task
        if kind == "influence_other":
            probe = {**task, "distinct_from": [game["pending"]["context"].get("last_planet")]}
        return [{"action": "choose", "planet": planet} for planet in _eligible_planets(game, pid, probe)]
    if kind == "split_influence":
        selected = task.get("selected", [])
        return [
            {"action": "choose", "planet": planet}
            for planet in PLANETS
            if planet not in selected
        ]
    if kind == "optional":
        moves = [{"action": "choose", "accept": False}]
        if not task.get("then") or _task_possible(game, pid, task["then"][0]):
            moves.append({"action": "choose", "accept": True})
        return moves
    if kind == "choose_branch":
        options = [
            index
            for index, branch in enumerate(task["branches"])
            if not branch["tasks"] or _task_possible(game, pid, branch["tasks"][0])
        ]
        if not options:
            options = list(range(len(task["branches"])))
        return [{"action": "choose", "branch": index} for index in options]
    if kind in ("exile", "exile_for_matching"):
        owner = task.get("owner", "self" if kind == "exile_for_matching" else "opponent")
        candidates = _top_candidates(
            game,
            pid,
            owner,
            exclude=task.get("exclude"),
            used=task.get("used") if task.get("distinct") else None,
        )
        return [{"action": "choose", "planet": planet} for planet in candidates]
    if kind == "transfer":
        return [
            {"action": "choose", "planet": planet}
            for planet in _top_candidates(game, pid, "opponent")
        ]
    if kind == "discard_hand":
        return [
            {"action": "choose", "card_id": card_id}
            for card_id in _player(game, pid)["hand"]
        ]
    if kind == "develop":
        player = _player(game, pid)
        factions = [task["faction"]] if task.get("faction") else list(FACTIONS)
        if task.get("lowest"):
            lowest = min(player["technology"].values())
            factions = [f for f in factions if player["technology"][f] == lowest]
        factions = [
            faction
            for faction in factions
            if player["technology"][faction] < 5
            and player["zenithium"] >= max(0, player["technology"][faction] + 1 - task.get("discount", 0))
        ]
        return [{"action": "choose", "faction": faction} for faction in factions]
    if kind == "exile_tier":
        size = len(_columns(game, pid)[task["planet"]])
        choices = [
            {"action": "choose", "tier": threshold}
            for threshold in (2, 4, 7)
            if size >= threshold
        ]
        return choices or [{"action": "choose", "tier": 0}]
    if kind == "spend_tier":
        amount = _player(game, pid)[task["resource"]]
        return [
            {"action": "choose", "cost": cost, "amount": reward}
            for cost, reward in task["tiers"]
            if amount >= cost
        ] + [{"action": "choose", "cost": 0, "amount": 0}]
    if kind == "reset_planet":
        return [
            {"action": "choose", "planet": planet}
            for planet in PLANETS
            if game["influence"][planet] not in (None, 0)
        ]
    if kind == "take_board_bonus":
        moves = [
            {"action": "choose", "bonus_area": "planet", "slot": planet}
            for planet, token in game["planet_bonus"].items()
            if token is not None
        ]
        moves += [
            {"action": "choose", "bonus_area": "technology", "slot": faction}
            for faction, token in game["technology_bonus"].items()
            if token is not None
        ]
        return moves
    if kind == "optional_exile_each":
        planet = task["planets"][task.get("index", 0)]
        moves = [{"action": "choose", "accept": False}]
        if _columns(game, pid)[planet]:
            moves.append({"action": "choose", "accept": True})
        return moves
    if kind == "two_adjacent":
        return [
            {"action": "choose", "planets": [PLANETS[i], PLANETS[i + 1]]}
            for i in range(4)
        ]
    if kind == "adjacent_three":
        return [
            {"action": "choose", "planet": PLANETS[i]}
            for i in range(1, 4)
        ]
    raise ValueError(f"Unknown Orbit choice task: {kind}")


def _apply_task_choice(game: dict, task: dict, move: dict) -> None:
    pid = task["actor"]
    queue = game["pending"]["queue"]
    kind = task["type"]
    if kind in ("influence", "influence_other"):
        queue.pop(0)
        planet = move["planet"]
        game["pending"]["context"]["last_planet"] = planet
        bonus = _gain_influence(game, pid if task.get("target") != "opponent" else _opponent(game, pid), planet, task["amount"])
        _queue_tasks(game, bonus, pid if task.get("target") != "opponent" else _opponent(game, pid))
    elif kind == "split_influence":
        selected = task.setdefault("selected", [])
        index = len(selected)
        planet = move["planet"]
        selected.append(planet)
        game["pending"]["context"]["last_planet"] = planet
        bonus = _gain_influence(game, pid, planet, task["amounts"][index])
        if len(selected) >= len(task["amounts"]):
            queue.pop(0)
        _queue_tasks(game, bonus, pid)
    elif kind == "optional":
        queue.pop(0)
        if move["accept"] and _pay_cost(game, pid, task["cost"]):
            _queue_tasks(game, task["then"], pid)
    elif kind == "choose_branch":
        queue.pop(0)
        _queue_tasks(game, task["branches"][move["branch"]]["tasks"], pid)
    elif kind in ("exile", "exile_for_matching"):
        owner = task.get("owner", "self" if kind == "exile_for_matching" else "opponent")
        owner_pid = pid if owner == "self" else _opponent(game, pid)
        planet = move["planet"]
        card_id = _discard_top(game, owner_pid, planet)
        task["done"] = task.get("done", 0) + 1
        task.setdefault("used", []).append(planet)
        _log(game, f"{game['names'][pid]} exiles {CARDS[card_id]['name']} from {planet.title()}.", pid=pid, card_id=card_id)
        reward = task.get("reward")
        if reward == "matching_influence" or kind == "exile_for_matching":
            _queue_tasks(game, [{"type": "influence", "planet": planet, "amount": task.get("amount", 1)}], pid)
        elif reward == "card_cost":
            _queue_tasks(game, [{"type": "credits", "amount": CARDS[card_id]["cost"], "target": "self"}], pid)
        target = task.get("count", 1)
        if task["done"] >= target:
            queue.remove(task)
            if isinstance(reward, dict):
                _queue_tasks(game, [{"type": reward["resource"], "amount": reward["amount"], "target": "self"}], pid)
    elif kind == "transfer":
        planet = move["planet"]
        card_id = _transfer_top(game, pid, planet)
        task["done"] = task.get("done", 0) + 1
        _log(game, f"{game['names'][pid]} transfers {CARDS[card_id]['name']} from {planet.title()}.", pid=pid, card_id=card_id)
        reward = task.get("reward")
        if reward == "matching_influence":
            _queue_tasks(game, [influence_task(planet, 1)], pid)
        elif reward == "card_cost":
            _queue_tasks(game, [{"type": "credits", "amount": CARDS[card_id]["cost"], "target": "self"}], pid)
        if task["done"] >= task["count"]:
            queue.remove(task)
    elif kind == "discard_hand":
        card_id = move["card_id"]
        _player(game, pid)["hand"].remove(card_id)
        game["agent_discard"].append(card_id)
        reward = task.get("reward")
        if reward == "matching_influence":
            _queue_tasks(game, [influence_task(CARDS[card_id]["planet"], 1)], pid)
        elif reward == "card_cost":
            _queue_tasks(game, [{"type": "credits", "amount": CARDS[card_id]["cost"], "target": "self"}], pid)
        if task["count"] == "all":
            if not _player(game, pid)["hand"]:
                queue.remove(task)
        else:
            task["done"] = task.get("done", 0) + 1
            if task["done"] >= int(task["count"]):
                queue.remove(task)
    elif kind == "develop":
        queue.pop(0)
        _advance_technology(game, pid, move["faction"], task.get("discount", 0))
    elif kind == "exile_tier":
        queue.pop(0)
        threshold = move["tier"]
        if threshold:
            for _ in range(threshold):
                _discard_top(game, pid, task["planet"])
            reward_amount = {2: 2, 4: 4, 7: 7}[threshold] if task["reward"] == "zenithium" else {2: 1, 4: 2, 7: 3}[threshold]
            reward = {"type": task["reward"], "amount": reward_amount, "target": "self"}
            if task["reward"] == "influence":
                reward["planet"] = task["planet"]
            _queue_tasks(game, [reward], pid)
    elif kind == "spend_tier":
        queue.pop(0)
        cost = move["cost"]
        if cost:
            _player(game, pid)[task["resource"]] -= cost
            _queue_tasks(game, [{"type": "influence", "amount": move["amount"], "exclude": task["exclude"]}], pid)
    elif kind == "reset_planet":
        queue.pop(0)
        game["influence"][move["planet"]] = 0
    elif kind == "take_board_bonus":
        queue.pop(0)
        area = move["bonus_area"]
        slot = move["slot"]
        board = game["planet_bonus"] if area == "planet" else game["technology_bonus"]
        token = board[slot]
        board[slot] = None
        _award_bonus(game, pid, token)
    elif kind == "optional_exile_each":
        index = task.get("index", 0)
        planet = task["planets"][index]
        if move["accept"] and _columns(game, pid)[planet]:
            _discard_top(game, pid, planet)
            reward = task["reward"]
            if reward == "influence":
                _queue_tasks(game, [influence_task(planet, 1)], pid)
            else:
                _queue_tasks(game, [{"type": "zenithium", "amount": 1, "target": "self"}], pid)
        task["index"] = index + 1
        if task["index"] >= len(task["planets"]):
            queue.remove(task)
    elif kind == "two_adjacent":
        queue.pop(0)
        tasks = [influence_task(planet, task["amount"]) for planet in move["planets"]]
        _queue_tasks(game, tasks, pid)
    elif kind == "adjacent_three":
        queue.pop(0)
        index = PLANETS.index(move["planet"])
        _queue_tasks(
            game,
            [
                influence_task(PLANETS[index], task["center"]),
                influence_task(PLANETS[index - 1], task["neighbor"]),
                influence_task(PLANETS[index + 1], task["neighbor"]),
            ],
            pid,
        )


def influence_task(planet: str, amount: int, target: str = "self") -> dict:
    return {"type": "influence", "planet": planet, "amount": amount, "target": target}


def _drain_pending(game: dict) -> None:
    while game.get("pending") and game["pending"]["queue"] and game["phase"] != "over":
        task = game["pending"]["queue"][0]
        pid = task["actor"]
        game["pending_pid"] = pid
        kind = task["type"]

        # Choice tasks remain at the front until the owning player responds.
        if kind == "optional" and not _can_pay(game, pid, task["cost"]):
            game["pending"]["queue"].pop(0)
            continue
        if kind in {
            "influence",
            "influence_other",
            "split_influence",
            "optional",
            "choose_branch",
            "exile",
            "exile_for_matching",
            "transfer",
            "discard_hand",
            "develop",
            "exile_tier",
            "spend_tier",
            "reset_planet",
            "take_board_bonus",
            "optional_exile_each",
            "two_adjacent",
            "adjacent_three",
        }:
            if kind == "exile" and task.get("require_full") and not task.get("done"):
                owner_pid = pid if task.get("owner") == "self" else _opponent(game, pid)
                available = sum(
                    len(cards)
                    for planet, cards in _columns(game, owner_pid).items()
                    if planet != task.get("exclude")
                )
                if available < task["count"]:
                    game["pending"]["queue"].pop(0)
                    continue
            if kind == "influence" and task.get("planet"):
                game["pending"]["queue"].pop(0)
                target_pid = pid if task.get("target") != "opponent" else _opponent(game, pid)
                bonus = _gain_influence(game, target_pid, task["planet"], task["amount"])
                _queue_tasks(game, bonus, target_pid)
                continue
            moves = _choice_moves(game, task)
            if moves:
                task["options"] = moves
                return
            # Unavailable effects are ignored.  A full exile cost does not pay
            # its reward unless the required number of cards existed.
            game["pending"]["queue"].pop(0)
            continue

        game["pending"]["queue"].pop(0)
        player = _player(game, pid)
        if kind in ("credits", "zenithium"):
            target_pid = pid if task.get("target", "self") == "self" else _opponent(game, pid)
            _player(game, target_pid)[kind] += task["amount"]
        elif kind == "leader":
            _gain_leader(game, pid, task.get("level", 1))
        elif kind == "if_leader":
            if game["leader"]["owner"] == pid:
                _queue_tasks(game, task["then"], pid)
        elif kind == "if_credits":
            if player["credits"] >= task["amount"]:
                _queue_tasks(game, task["then"], pid)
        elif kind == "draw_bonus":
            token = _draw_bonus_type(game)
            if token is not None:
                _award_bonus(game, pid, token)
        elif kind == "fixed_bonus":
            token = game["technology_bonus"].get(task["faction"])
            if token is not None:
                game["technology_bonus"][task["faction"]] = None
                _award_bonus(game, pid, token)
        elif kind == "mobilize":
            draw_count = 1 if task.get("influence_each") else task["count"]
            for _ in range(draw_count):
                card_id = _draw_agent(game)
                if card_id is None:
                    break
                planet = CARDS[card_id]["planet"]
                _columns(game, pid)[planet].append(card_id)
                _log(game, f"{game['names'][pid]} mobilizes {CARDS[card_id]['name']}.", pid=pid, card_id=card_id)
                if task.get("influence_each"):
                    followups = [influence_task(planet, 1)]
                    if task["count"] > 1:
                        followups.append({**task, "count": task["count"] - 1})
                    _queue_tasks(game, followups, pid)
        elif kind == "transfer_each":
            for planet in task["planets"]:
                if _columns(game, _opponent(game, pid))[planet]:
                    card_id = _transfer_top(game, pid, planet)
                    _log(
                        game,
                        f"{game['names'][pid]} transfers {CARDS[card_id]['name']} from {planet.title()}.",
                        pid=pid,
                        card_id=card_id,
                    )
        elif kind == "steal":
            opponent = _player(game, _opponent(game, pid))
            amount = min(task["amount"], opponent[task["resource"]])
            opponent[task["resource"]] -= amount
            player[task["resource"]] += amount
        elif kind == "per_tech_first":
            count = sum(level >= 1 for level in player["technology"].values())
            player[task["resource"]] += count * task["amount"]
        elif kind == "per_nonempty":
            owner_pid = pid if task["owner"] == "self" else _opponent(game, pid)
            count = sum(bool(column) for column in _columns(game, owner_pid).values())
            player["credits"] += count * task["amount"]
        elif kind == "all_planets":
            _queue_tasks(
                game,
                [influence_task(planet, task["amount"]) for planet in PLANETS],
                pid,
            )
        elif kind == "row_bonus_check":
            newly = []
            for level in (1, 2, 3):
                if level not in player["row_bonuses"] and all(value >= level for value in player["technology"].values()):
                    player["row_bonuses"].append(level)
                    newly.append(influence_task("", level))
            for reward in newly:
                reward.pop("planet")
            _queue_tasks(game, newly, pid)
        else:
            raise ValueError(f"Unknown Orbit task: {kind}")

    if game.get("pending") and not game["pending"]["queue"] and game["phase"] != "over":
        _finish_turn(game)


def _finish_turn(game: dict) -> None:
    pid = game["turn_pid"]
    _draw_to(game, pid, _leader_limit(game, pid))
    for planet in game["captured_this_turn"]:
        if game["influence"][planet] is None:
            game["influence"][planet] = 0
    game["captured_this_turn"] = []
    game["pending"] = None
    game["pending_pid"] = None
    game["turn_number"] += 1
    game["turn_pid"] = _opponent(game, pid)
    # The published game assumes a card is available when a hand refills.  A
    # deliberately perverse random game can temporarily strand a player with
    # no hand while the opponent later creates a discard pile.  Recover at the
    # next turn boundary so the random opponent can never deadlock a room.
    if not _player(game, game["turn_pid"])["hand"]:
        _draw_to(game, game["turn_pid"], _leader_limit(game, game["turn_pid"]))
    if (
        not _player(game, game["turn_pid"])["hand"]
        and not game["agent_deck"]
        and not game["agent_discard"]
    ):
        game["phase"] = "over"
        game["winner"] = None
        _log(game, "The Agent supply is exhausted; the game ends in a draw.")


def _begin_resolution(game: dict, pid: str, tasks: list[dict], source: str) -> None:
    game["pending"] = {"source": source, "queue": [], "context": {}}
    game["pending_pid"] = pid
    _queue_tasks(game, tasks, pid, front=False)
    _drain_pending(game)


def _play_card_action(game: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    player = _player(game, pid)
    card_id = int(move["card_id"])
    card = CARDS[card_id]
    player["hand"].remove(card_id)
    action = move["action"]
    if action == "recruit":
        cost = max(0, card["cost"] - len(player["columns"][card["planet"]]))
        player["credits"] -= cost
        player["columns"][card["planet"]].append(card_id)
        _log(game, f"{game['names'][pid]} recruits {card['name']} for {cost} Credits.", pid=pid, card_id=card_id, action=action)
        _begin_resolution(game, pid, [influence_task(card["planet"], 1), *card_effects(card_id)], card["name"])
    elif action == "technology":
        game["agent_discard"].append(card_id)
        faction = card["faction"]
        _log(game, f"{game['names'][pid]} discards {card['name']} to develop {faction.title()} technology.", pid=pid, card_id=card_id, action=action)
        game["pending"] = {"source": card["name"], "queue": [], "context": {}}
        game["pending_pid"] = pid
        if not _advance_technology(game, pid, faction):
            raise AssertionError("Validated technology action became illegal")
        _drain_pending(game)
    elif action == "leader":
        game["agent_discard"].append(card_id)
        faction = card["faction"]
        tasks = [{"type": "leader", "level": 1}]
        if faction == "robot":
            tasks.append({"type": "zenithium", "amount": 1, "target": "self"})
        elif faction == "human":
            tasks.append({"type": "credits", "amount": 3, "target": "self"})
        else:
            tasks.append({"type": "mobilize", "count": 2, "influence_each": False})
        _log(game, f"{game['names'][pid]} discards {card['name']} for the {faction.title()} Leader action.", pid=pid, card_id=card_id, action=action)
        _begin_resolution(game, pid, tasks, card["name"])
    return True, None


def new_game(
    player_ids: list[str],
    names: dict[str, str] | None = None,
    seed: int | None = None,
    configuration: str | dict[str, int] = "sun",
) -> dict:
    if len(player_ids) != 2 or len(set(player_ids)) != 2:
        raise ValueError("Orbit requires exactly two distinct players")
    rng = random.Random(seed)
    order = list(player_ids)
    rng.shuffle(order)
    deck = list(CARDS)
    rng.shuffle(deck)
    bonuses = list(BONUS_POOL)
    rng.shuffle(bonuses)
    if configuration == "sun":
        board_sides = dict(SUN_CONFIGURATION)
    elif configuration == "random":
        board_sides = random_configuration(rng)
    elif isinstance(configuration, dict) and set(configuration) == set(FACTIONS) and all(v in (1, 2) for v in configuration.values()):
        board_sides = dict(configuration)
    else:
        raise ValueError("configuration must be 'sun', 'random', or a complete side map")
    game = {
        "version": 1,
        "phase": "mulligan",
        "order": order,
        "names": names or {pid: pid for pid in player_ids},
        "players": {
            pid: {
                "credits": STARTING_CREDITS,
                "zenithium": STARTING_ZENITHIUM,
                "hand": [],
                "columns": {planet: [] for planet in PLANETS},
                "technology": {faction: 0 for faction in FACTIONS},
                "row_bonuses": [],
                "captured": [],
            }
            for pid in player_ids
        },
        "turn_pid": None,
        "turn_number": 0,
        "influence": {planet: 0 for planet in PLANETS},
        "captured_this_turn": [],
        "leader": {"owner": None, "level": 0},
        "board_sides": board_sides,
        "planet_bonus": {},
        "technology_bonus": {},
        "agent_deck": deck,
        "agent_discard": [],
        "bonus_deck": bonuses,
        "bonus_discard": [],
        "mulligan_done": [],
        "pending": None,
        "pending_pid": None,
        "winner": None,
        "log": [],
        "rng_state": None,
    }
    for pid in order:
        _draw_to(game, pid, 4)
    for planet in PLANETS:
        game["planet_bonus"][planet] = game["bonus_deck"].pop()
    for faction in FACTIONS:
        game["technology_bonus"][faction] = game["bonus_deck"].pop()
    # The second player begins one step toward their Terra control zone.
    game["influence"]["terra"] = -1
    _save_rng(game, rng)
    return game


def legal_moves(game: dict, pid: str) -> list[dict]:
    if pid not in game["players"] or game["phase"] == "over":
        return []
    if game["phase"] == "mulligan":
        if pid in game["mulligan_done"]:
            return []
        hand = sorted(_player(game, pid)["hand"])
        return [
            {"action": "mulligan", "card_ids": list(combo)}
            for count in range(len(hand) + 1)
            for combo in itertools.combinations(hand, count)
        ]
    if game.get("pending"):
        if game["pending_pid"] != pid:
            return []
        task = game["pending"]["queue"][0]
        return copy.deepcopy(task.get("options") or _choice_moves(game, task))
    if game["turn_pid"] != pid:
        return []
    player = _player(game, pid)
    moves: list[dict] = []
    for card_id in player["hand"]:
        card = CARDS[card_id]
        recruit_cost = max(0, card["cost"] - len(player["columns"][card["planet"]]))
        if player["credits"] >= recruit_cost:
            moves.append({"action": "recruit", "card_id": card_id})
        next_level = player["technology"][card["faction"]] + 1
        if next_level <= 5 and player["zenithium"] >= next_level:
            moves.append({"action": "technology", "card_id": card_id})
        moves.append({"action": "leader", "card_id": card_id})
    return moves


def apply_move(game: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    if move not in legal_moves(game, pid):
        return False, "Illegal move"
    if game["phase"] == "mulligan":
        selected = list(move["card_ids"])
        hand = _player(game, pid)["hand"]
        for card_id in selected:
            hand.remove(card_id)
            game["agent_discard"].append(card_id)
        _draw_to(game, pid, 4)
        game["mulligan_done"].append(pid)
        _log(game, f"{game['names'][pid]} replaces {len(selected)} starting card(s).", pid=pid)
        if len(game["mulligan_done"]) == 2:
            game["phase"] = "play"
            game["turn_pid"] = game["order"][0]
            game["turn_number"] = 1
        return True, None
    if game.get("pending"):
        task = game["pending"]["queue"][0]
        task.pop("options", None)
        _apply_task_choice(game, task, move)
        if game["phase"] != "over":
            _drain_pending(game)
        return True, None
    return _play_card_action(game, pid, move)


def is_over(game: dict) -> bool:
    return game.get("phase") == "over"


def winner(game: dict) -> str | None:
    return game.get("winner")


def _public_player(player: dict, *, reveal_hand: bool) -> dict:
    result = copy.deepcopy(player)
    if reveal_hand:
        result["hand"] = [public_card(card_id) for card_id in player["hand"]]
    else:
        result["hand"] = [{"hidden": True} for _ in player["hand"]]
    result["columns"] = {
        planet: [public_card(card_id) for card_id in cards]
        for planet, cards in player["columns"].items()
    }
    return result


def player_view(game: dict, pid: str | None) -> dict:
    """Return a per-recipient view with all deck order and opposing hands hidden."""

    view = copy.deepcopy(game)
    view["players"] = {
        player_id: _public_player(player, reveal_hand=is_over(game) or player_id == pid)
        for player_id, player in game["players"].items()
    }
    view["agent_deck_count"] = len(view.pop("agent_deck"))
    view["agent_discard"] = [public_card(card_id) for card_id in view["agent_discard"]]
    view["bonus_deck_count"] = len(view.pop("bonus_deck"))
    view.pop("rng_state", None)
    view["board"] = board_reference(view["board_sides"])
    if view.get("pending"):
        current = view["pending"]["queue"][0] if view["pending"]["queue"] else None
        if current is None:
            view["pending"] = None
        elif view["pending_pid"] == pid:
            task_view = {
                key: value
                for key, value in current.items()
                if key not in {"actor", "then", "branches"}
            }
            if current.get("branches"):
                task_view["branch_labels"] = [branch["label"] for branch in current["branches"]]
            view["pending"] = {
                "source": view["pending"]["source"],
                "task": task_view,
            }
        else:
            view["pending"] = {"source": view["pending"]["source"], "waiting": True}
    view["legal_moves"] = legal_moves(game, pid) if pid else []
    return view


def validate_state(game: dict) -> None:
    """Raise on conservation, range, or turn-contract drift."""

    all_cards: list[int] = list(game["agent_deck"]) + list(game["agent_discard"])
    for player in game["players"].values():
        all_cards.extend(player["hand"])
        for column in player["columns"].values():
            all_cards.extend(column)
        if player["credits"] < 0 or player["zenithium"] < 0:
            raise AssertionError("Resources cannot be negative")
        if any(level < 0 or level > 5 for level in player["technology"].values()):
            raise AssertionError("Technology level out of range")
    if sorted(all_cards) != sorted(CARDS):
        raise AssertionError("Agent card conservation failed")
    all_bonuses = list(game["bonus_deck"]) + list(game["bonus_discard"])
    all_bonuses += [token for token in game["planet_bonus"].values() if token is not None]
    all_bonuses += [token for token in game["technology_bonus"].values() if token is not None]
    if sorted(all_bonuses) != sorted(BONUS_POOL):
        raise AssertionError("Bonus token conservation failed")
    for position in game["influence"].values():
        if position is not None and not -3 <= position <= 3:
            raise AssertionError("Influence position out of range")
