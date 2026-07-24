"""Cross-impl arena: the coc-core Rust scaffold search vs the Python ai.py bot,
played on the AUTHORITATIVE Python engine (the P2 strength gate).

The Rust side answers per-DECISION through move_server_coc (stdin/stdout JSON,
compact moves resolved via bridge.compact_to_move); the Python side drives whole
turns exactly like ai_selfplay (_drive_ai_turn incl. the bot finisher). CRN
pairing: each seed is played twice with seats swapped (same deck shuffle + dice),
so dice/deck luck cancels.

Usage:
  python -m games.castles_of_crimson.az.rust_arena --games 200 --sims 2000 \
      --opp hard --workers 8
Build the server first:
  cargo build --release --features bridge   (in coc-core/)
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import os
import random
import subprocess
import sys
import time

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from games.castles_of_crimson import ai, bot, engine  # noqa: E402
from games.castles_of_crimson.az import bridge, compact  # noqa: E402

PIDS = ["P0", "P1"]
SERVER_DEFAULT = os.path.join(_REPO, "rust-cores", "coc-core", "target", "release", "move_server_coc.exe")

_SERVER = None
_ARGS = None


def _init_worker(args_dict):
    global _SERVER, _ARGS
    _ARGS = args_dict
    _SERVER = subprocess.Popen(
        [args_dict["server"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, bufsize=1, encoding="utf-8")


def _rust_decision(game, pid, sims, seed):
    req = {"proj": compact.project(game), "sims": sims, "seed": seed}
    _SERVER.stdin.write(json.dumps(req, separators=(",", ":")) + "\n")
    _SERVER.stdin.flush()
    line = _SERVER.stdout.readline()
    if not line:
        raise RuntimeError("move server died")
    resp = json.loads(line)
    return bridge.compact_to_move(game, pid, resp["move"])


def _drive_python_turn(game, pid, difficulty, rng):
    if difficulty == "random":
        bot.play_turn(game, pid, rng)
        return
    for mv in ai.play_turn_plan(game, pid, difficulty=difficulty, rng=rng):
        if ai._actor(game) != pid:
            break
        if not engine.apply_move(game, pid, mv)[0]:
            break
    guard = 0
    while not engine.is_over(game) and ai._actor(game) == pid and guard < 60:
        guard += 1
        bot.play_turn(game, pid, rng)


def play_one(spec):
    seed, b0, b1, rust_seat = spec
    sims = _ARGS["sims"]
    opp = _ARGS["opp"]
    rng = random.Random(9000 + seed)
    game = engine.new_game(PIDS, seed=seed, boards={"P0": b0, "P1": b1})
    rust_pid = PIDS[rust_seat]
    step = 0
    while not engine.is_over(game):
        pid = ai._actor(game)
        if pid is None:
            break
        if pid == rust_pid:
            mv = _rust_decision(game, pid, sims, seed * 1000 + step)
            ok, err = engine.apply_move(game, pid, mv)
            assert ok, f"rust move rejected (seed {seed} step {step}): {err} mv={mv}"
        elif game["phase"] == "setup":
            engine.apply_move(game, pid, ai._setup_move(game, pid))
        else:
            _drive_python_turn(game, pid, opp, rng)
        step += 1
        assert step < 6000, f"runaway game seed {seed}"
    scores = engine.final_scores(game)
    win = engine.winner(game)
    rust_win = 1.0 if win == rust_pid else (0.5 if isinstance(win, list) else 0.0)
    return rust_win, scores[rust_pid], scores[PIDS[1 - rust_seat]]


def wilson(p, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    e = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - e) / d, (c + e) / d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=200, help="total games (seed pairs x2)")
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--opp", default="hard", choices=["random", "normal", "hard"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed0", type=int, default=0)
    ap.add_argument("--server", default=SERVER_DEFAULT)
    args = ap.parse_args()

    boards_cycle = [(str(a + 1), str(b + 1)) for a in range(9) for b in range(9)]
    specs = []
    for g in range(args.games // 2):
        seed = args.seed0 + g
        b0, b1 = boards_cycle[g % len(boards_cycle)]
        specs.append((seed, b0, b1, 0))
        specs.append((seed, b0, b1, 1))

    conf = {"server": args.server, "sims": args.sims, "opp": args.opp}
    t0 = time.time()
    if args.workers <= 1:
        _init_worker(conf)
        results = [play_one(s) for s in specs]
    else:
        with mp.Pool(args.workers, initializer=_init_worker, initargs=(conf,)) as pool:
            results = pool.map(play_one, specs, chunksize=1)

    n = len(results)
    wr = sum(r[0] for r in results) / n
    rp = sum(r[1] for r in results) / n
    op = sum(r[2] for r in results) / n
    lo, hi = wilson(wr, n)
    print(
        f"rust-scaffold(sims={args.sims}) vs {args.opp}: {wr:.4f} "
        f"[{lo:.3f},{hi:.3f}] over {n} games (avg {rp:.1f} vs {op:.1f}) "
        f"in {time.time() - t0:.0f}s"
    )


if __name__ == "__main__":
    main()
