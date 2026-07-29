"""Random-legal bot — every difficulty tier in v1.

Uniform over legal moves with the sibling bots' anti-stall bias: never end a
phase while something else is possible (an unbiased bot ends its turn
instantly ~1/N of the time and the game crawls). Decisions are answered with
`engine.sample_decision` — uniform over the frame's valid payloads.

`choose` is also the server scheduler's guaranteed turn-finisher: it must
return a valid move for ANY state where (pending_pid or turn) == pid, and it
must never consume the game's own rng_state (pass an explicit rng).
"""

import random

from . import engine


def choose(game, pid, rng=None):
    r = rng or random.Random()
    if game["pending_pid"] == pid:
        return {"type": "decision", **engine.sample_decision(game, pid, r)}
    moves = engine.legal_moves(game, pid)
    for m in moves:
        if m["type"] == "play_all_treasures":
            return m
    active = [m for m in moves if m["type"] not in ("end_phase", "play_treasure")]
    if active:
        return r.choice(active)
    return {"type": "end_phase"}


def play_turn(game, pid, rng=None, max_steps=200):
    """Drive pid until the actor is someone else / the game ends. Returns the
    moves played. Mirrors the sibling bots' shape (the scheduler's fallback)."""
    r = rng or random.Random()
    played = []
    for _ in range(max_steps):
        if engine.is_over(game):
            break
        if (game["pending_pid"] or game["turn"]) != pid:
            break
        mv = choose(game, pid, r)
        ok, _err = engine.apply_move(game, pid, mv)
        if not ok:
            break
        played.append(mv)
    return played
