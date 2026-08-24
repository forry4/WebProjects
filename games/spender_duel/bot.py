"""Simple opponent for Spender Duel: greedy-tiered random-legal moves.

Both the v1 bot and the server scheduler's guaranteed turn-finisher. A future
``ai.py`` (determinized MCTS, CoC pattern) replaces ``choose`` behind this same
engine contract; its determinization surface is: shuffle the bag, shuffle each
deck's hidden remainder, and deal the opponent's blind-reserved cards from the
unseen pool (face-up pyramid reserves are public via the log).
"""
from __future__ import annotations

import random

from . import engine


def _tier(move: dict, game: dict) -> int:
    """Lower = preferred. Buy > 3-take (same-color/pearl pairs first) > any take
    > reserve > replenish > privilege > pass."""
    mt = move["type"]
    if mt == "buy":
        card = engine._card(move["card_id"])
        return 0 - card["points"] - card["crowns"]  # negative: best buys sort first
    if mt == "take":
        cells = move["cells"]
        colors = [game["board"][i] for i in cells]
        if len(cells) == 3:
            return 10 if len(set(colors)) == 1 else 11
        return 12 + (3 - len(cells))
    if mt == "reserve":
        return 20
    if mt == "replenish":
        return 30
    if mt == "use_privilege":
        return 40
    return 50  # pass


def choose(game: dict, pid: str, rng: random.Random | None = None) -> dict | None:
    """Pick a move for `pid` (whichever decision is pending)."""
    moves = engine.legal_moves(game, pid)
    if not moves:
        return None
    r = rng or random
    if game.get("pending_pid") == pid:
        real = [m for m in moves if m["type"] != "skip_pending"]
        return r.choice(real if real else moves)
    best = min(_tier(m, game) for m in moves)
    return r.choice([m for m in moves if _tier(m, game) == best])


def play_turn(game: dict, pid: str, rng: random.Random | None = None, max_steps: int = 100) -> None:
    """Drive `pid`'s decisions (its turn + any pendings it owns) to a stop."""
    steps = 0
    while steps < max_steps and not engine.is_over(game):
        steps += 1
        actor = game.get("pending_pid") or game.get("turn")
        if actor != pid:
            break
        move = choose(game, pid, rng)
        if move is None:
            break
        ok, _ = engine.apply_move(game, pid, move)
        if not ok:
            break  # legal_moves should never yield an illegal move; bail defensively
