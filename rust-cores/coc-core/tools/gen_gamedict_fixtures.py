"""Generate render-dict parity fixtures for the Rust offline serializer.

Plays random legal games through the PYTHON engine and, at sampled ENGINE-MOVE
boundaries, dumps:
  - `proj`: az_compact.project(game) — UNSORTED pools (the Rust test rebuilds a true
    State from it via from_proj; sorting is the wire caller's job, tested separately);
  - `wire`: the game dict exactly as mk_room_state ships it (engine dict minus _HIDE).

The Rust test re-renders each State through gamedict::to_game_dict and compares after
a shared canonicalization (implemented ONCE, in the Rust test, applied to BOTH sides):
tile ids are ledger-minted offline so id strings can never match, and a handful of
fields are order- or provenance-lossy in the compact state (see the test's canon()).

Pending-phase positions are always kept — pending_kind/ctx is where a serializer
drifts. Run:  python rust-cores/coc-core/tools/gen_gamedict_fixtures.py [n_games]
Writes: rust-cores/coc-core/tests/gamedict_fixtures.jsonl
"""
import copy
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)

from games.castles_of_crimson import engine  # noqa: E402
from games.castles_of_crimson.az import compact as az_compact  # noqa: E402

# main.py's _HIDE (mk_room_state) — the wire strips exactly these five keys.
HIDE = ("supply", "black_supply", "goods_supply", "rng_state", "turn_undo")

N = int(sys.argv[1]) if len(sys.argv) > 1 else 25


def wire_game(game):
    # DEEP copy — a shallow dict comprehension leaves every nested list/dict as a
    # live reference into the mutating game, so every record would serialize as the
    # FINAL position at json.dump time (caught exactly that way).
    return copy.deepcopy({k: v for k, v in game.items() if k not in HIDE})


def record(game):
    return {"proj": az_compact.project(game), "wire": wire_game(game)}


out = []
n_pending = 0
for g in range(N):
    rng = random.Random(3_000_000 + g)
    boards = {"p0": str(rng.randint(1, 9)), "p1": str(rng.randint(1, 9))}
    game = engine.new_game(["p0", "p1"], boards=boards, seed=rng.randint(0, 2**31))
    out.append(record(game))
    for step in range(1200):
        if engine.is_over(game):
            break
        actor = game["pending_pid"] or game["turn"]
        legal = engine.legal_moves(game, actor)
        if not legal:
            break
        mv = rng.choice(legal)
        ok, err = engine.apply_move(game, actor, mv)
        assert ok, f"engine rejected its own legal move: {err} ({mv})"
        pending = game["pending_pid"] is not None
        if pending:
            n_pending += 1
        if pending or step % 17 == 0 or engine.is_over(game):
            out.append(record(game))

assert n_pending > 0, "no pending-phase positions sampled — fixture would prove nothing"

dst = os.path.abspath(os.path.join(HERE, "..", "tests", "gamedict_fixtures.jsonl"))
with open(dst, "w", encoding="utf-8") as f:
    for rec in out:
        f.write(json.dumps(rec) + "\n")
print(f"wrote {dst}: {len(out)} positions ({n_pending} pending-phase)")
