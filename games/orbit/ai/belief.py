"""Conservation-correct CURRENT-OBSERVATION prior, not a history posterior.

Never accepts a true game dict. Phase 2 must add sequential conditioning before
using this as a claim about beliefs given the entire observed game history.
"""
from __future__ import annotations

from collections import Counter
import random

from ..cards import BONUS_POOL, CARDS


def sample_hidden(observation: dict, rng: random.Random) -> dict:
    me = observation["seat"]
    known = list(observation["players"][me]["hand"]) + list(observation["agent_discard"])
    for player in observation["players"]:
        for column in player["columns"]:
            known.extend(column)
    if len(set(known)) != len(known) or not set(known) <= set(CARDS):
        raise ValueError("Inconsistent observed Agent inventory")
    unseen = sorted(set(CARDS) - set(known))
    hand_count = observation["players"][1 - me]["hand_count"]
    if len(unseen) != hand_count + observation["agent_deck_count"]:
        raise ValueError("Observed Agent counts do not conserve the deck")
    rng.shuffle(unseen)
    visible = list(observation["bonus_discard"])
    visible += [v for v in observation["planet_bonus"] + observation["technology_bonus"] if v is not None]
    remaining = Counter(BONUS_POOL)
    remaining.subtract(visible)
    if any(v < 0 for v in remaining.values()):
        raise ValueError("Inconsistent observed bonus inventory")
    bonuses = sorted(remaining.elements())
    if len(bonuses) != observation["bonus_deck_count"]:
        raise ValueError("Observed bonus counts do not conserve the reserve")
    rng.shuffle(bonuses)
    return {"opponent_hand": sorted(unseen[:hand_count]),
            "agent_deck": unseen[hand_count:], "bonus_deck": bonuses}
