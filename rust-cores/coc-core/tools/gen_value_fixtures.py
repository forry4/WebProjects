"""Scalar parity fixtures for the heuristic leaf: ai.py `_value` on sampled
positions, replayed by coc-core heuristic::value (tolerance 1e-9).

Run:  python coc-core/tools/gen_value_fixtures.py
Output: coc-core/tests/fixtures/values.jsonl  {proj, v0, v1}
"""
from __future__ import annotations

import json
import os
import random
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)

from games.castles_of_crimson import ai, engine  # noqa: E402
from games.castles_of_crimson.az import compact  # noqa: E402

PIDS = ["P0", "P1"]


def main():
    out_path = os.path.join(_REPO, "coc-core", "tests", "fixtures", "values.jsonl")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    n = 0
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for seed in range(40):
            rng = random.Random(seed)
            game = engine.new_game(
                PIDS, seed=seed,
                boards={"P0": str(seed % 9 + 1), "P1": str((seed * 3) % 9 + 1)})
            step = 0
            while not engine.is_over(game):
                pid = game["pending_pid"] or game["turn"]
                moves = engine.legal_moves(game, pid)
                ok, err = engine.apply_move(game, pid, rng.choice(moves))
                assert ok, err
                step += 1
                if step % 10 == 0 or engine.is_over(game):
                    rec = {
                        "proj": compact.project(game),
                        "v0": repr(ai._value(game, "P0")),
                        "v1": repr(ai._value(game, "P1")),
                    }
                    f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                    n += 1
                assert step < 4000
    print(f"wrote {n} value fixtures to {out_path}")


if __name__ == "__main__":
    main()
