"""Play reproducible random Orbit games through the public engine boundary.

Usage::

    python -m games.orbit.tools.soak --games 2000
"""

from __future__ import annotations

import argparse
import random

from games.orbit import engine


def play(seed: int, move_cap: int) -> tuple[int, str | None]:
    chooser = random.Random(seed * 104_729 + 17)
    game = engine.new_game(["A", "B"], seed=seed, configuration="random")
    for move_number in range(1, move_cap + 1):
        if engine.is_over(game):
            return move_number - 1, engine.winner(game)
        if game["phase"] == "mulligan":
            pid = next(pid for pid in game["players"] if pid not in game["mulligan_done"])
        else:
            pid = game["pending_pid"] if game.get("pending") else game["turn_pid"]
        moves = engine.legal_moves(game, pid)
        if not moves:
            raise AssertionError(f"seed {seed} stalled at move {move_number}")
        ok, error = engine.apply_move(game, pid, chooser.choice(moves))
        if not ok:
            raise AssertionError(f"seed {seed} rejected a legal move: {error}")
        engine.validate_state(game)
    raise AssertionError(f"seed {seed} exceeded {move_cap} moves")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, default=1000)
    parser.add_argument("--move-cap", type=int, default=1500)
    args = parser.parse_args()
    if args.games < 1 or args.move_cap < 1:
        parser.error("--games and --move-cap must both be positive")

    longest = (0, 0)
    results = {"A": 0, "B": 0, "draw": 0}
    for seed in range(args.games):
        moves, winner = play(seed, args.move_cap)
        if moves > longest[1]:
            longest = (seed, moves)
        results[winner or "draw"] += 1
    print(
        f"Orbit soak passed: {args.games} games; "
        f"A={results['A']} B={results['B']} draws={results['draw']}; "
        f"longest seed={longest[0]} moves={longest[1]}"
    )


if __name__ == "__main__":
    main()
