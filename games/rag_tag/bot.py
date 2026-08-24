"""The Rag Tag opponent. It plays at random, and that is deliberate for v1.

The point of shipping it is to make the game playable and playtestable end to
end; strength comes later, once the shape of a good Rag Tag decision is
understood rather than guessed. Two things are worth keeping when it is replaced:

* every move goes back through ``engine.apply_move``, so the bot has no more
  authority than a browser does;
* it is seeded off the caller, never off global randomness, so a soak that finds
  a bad game can replay it.

There is deliberately NO difficulty picker yet.
``shared/tests/test_ai_difficulty_memory.py`` builds its roster by grepping
``games/*/[A-Z]*.jsx`` for ``ai_difficulty``, so shipping without that field
keeps this game honestly out of that roster -- and auto-enrols it the moment
tiers land, which is exactly when ``useLastDifficulty`` has to be wired.
"""

from __future__ import annotations

import random

from . import engine


def choose_move(game: dict, seat: int, seed: int | None = None) -> dict | None:
    """One legal move for `seat`, or None if it owes nothing right now."""
    rng = random.Random(seed)
    moves = engine.legal_moves(game, seat)
    if not moves:
        return None

    kind = moves[0]["kind"]
    if kind == "build":
        # Flat over (card, position) would bias towards whatever the deck
        # happens to allow; pick the card first, then where it goes.
        offer = game["build_offer"][seat] or []
        inst = rng.choice(offer)
        positions = engine.legal_build_positions(game, seat)
        move = {"kind": "build", "inst": inst, "pos": rng.choice(positions)}
        rest = [i for i in offer if i != inst]
        if rest:
            move["bottom_last"] = rng.choice(rest)
        return move

    return rng.choice(moves)
