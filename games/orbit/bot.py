"""The deliberately random Orbit opponent used for the first playable release."""

from __future__ import annotations

import random

from . import engine


def choose_move(game: dict, pid: str, seed: int | None = None) -> dict | None:
    moves = engine.legal_moves(game, pid)
    if not moves:
        return None
    return random.Random(seed).choice(moves)
