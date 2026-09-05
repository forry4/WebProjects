"""Serializable offline sessions with separate per-seat observation histories.

The archive contains privileged simulator state. Only `policy_input(pid)` may
cross into a policy. Live room persistence integration is intentionally Phase 5.
"""
from __future__ import annotations

import copy

from .. import engine
from .state import SCHEMA_VERSION, observation, rules_fingerprint


class Session:
    def __init__(self, game: dict):
        self.game = copy.deepcopy(game)
        self.rules = rules_fingerprint()
        self.histories = {
            pid: {"initial": observation(game, pid), "events": []}
            for pid in game["order"]
        }
        self.latest = {pid: observation(game, pid) for pid in game["order"]}

    def step(self, pid: str, move: dict) -> tuple[bool, str | None]:
        ok, error = engine.apply_move(self.game, pid, move)
        if not ok:
            return ok, error
        for viewer in self.game["order"]:
            after = observation(self.game, viewer)
            event = {"actor": self.game["order"].index(pid),
                     "changes": {k: v for k, v in after.items() if v != self.latest[viewer].get(k)}}
            # The played card is public even if a same-action reshuffle removes
            # it from the discard before the next snapshot. Snapshot diffs alone
            # would forget information the opponent actually observed.
            if move["action"] in ("recruit", "technology", "leader"):
                event["public_action"] = copy.deepcopy(move)
            elif move["action"] == "mulligan":
                event["public_action"] = {"action": "mulligan", "count": len(move["card_ids"])}
            # Private mulligan selections / hand choices never enter the other
            # seat's event. Public consequences are already in its observation.
            if viewer == pid:
                event["own_action"] = copy.deepcopy(move)
            self.histories[viewer]["events"].append(event)
            self.latest[viewer] = after
        return True, None

    def policy_input(self, pid: str) -> dict:
        return copy.deepcopy({"rules": self.rules, "observation": self.latest[pid],
                              "history": self.histories[pid]})

    def archive(self) -> dict:
        return copy.deepcopy({"schema": SCHEMA_VERSION, "rules": self.rules,
                              "game": self.game, "histories": self.histories})

    @classmethod
    def restore(cls, archive: dict) -> "Session":
        if archive["schema"] != SCHEMA_VERSION or archive["rules"] != rules_fingerprint():
            raise ValueError("Orbit session rules/schema mismatch; regenerate the trajectory")
        engine.validate_state(archive["game"])
        result = cls(archive["game"])
        if set(archive["histories"]) != set(result.game["order"]):
            raise ValueError("Orbit archive must have one history for each seat")
        result.histories = copy.deepcopy(archive["histories"])
        for pid, history in result.histories.items():
            reconstructed = copy.deepcopy(history["initial"])
            for event in history["events"]:
                reconstructed.update(copy.deepcopy(event["changes"]))
            if reconstructed != result.latest[pid]:
                raise ValueError("Orbit history does not reconstruct the current observation")
        return result
