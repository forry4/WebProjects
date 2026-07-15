"""Offline arena for the Spender Duel AI — validation + tuning. No server, no DB.

    python -m games.spender_duel.ai_selfplay arena --a hard --b random --games 40
    python -m games.spender_duel.ai_selfplay arena --a hard --b normal --games 30
    python -m games.spender_duel.ai_selfplay probe --games 6      # leaf-mode A/B

Seat-swapped pairs on a shared deck seed (CRN): each deck is played both seat
orders, so first-player advantage cancels and A-vs-A scores ~0.5 by construction.
Score is from A's perspective (1 win / 0 loss), reported with a Wilson interval.
"""
from __future__ import annotations

import argparse
import math
import random
import time

from . import ai, bot, engine

P0, P1 = "a0", "a1"


def _wilson(wins: float, n: int, z: float = 1.96) -> tuple:
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _agent(spec: str):
    """Agent spec -> callable(game, pid, rng) -> move.

    "random"          the trivial tiered bot
    "hard" / "normal" an ai.DIFFICULTY tier, as shipped
    "hard@N"          that tier with the leaf's rollout overridden to N steps
                      (N=0 -> a purely static leaf). A PER-AGENT override, so a leaf
                      A/B changes ONE side — flipping the module global would change
                      both players and measure nothing.
    "hard@N/I"        ...and max_iters=I   (equal-SIMS comparisons)
    "hard@N/I/T"      ...and time_limit=T  (equal-TIME comparisons — the ship test)
    """
    if spec == "random":
        return lambda g, pid, rng: bot.choose(g, pid, rng)
    kind, _, rest = spec.partition("@")
    steps = iters = tl = None
    if rest:
        parts = rest.split("/")
        steps = int(parts[0])
        if len(parts) > 1 and parts[1]:
            iters = int(parts[1])
        if len(parts) > 2 and parts[2]:
            tl = float(parts[2])
    return lambda g, pid, rng: ai.choose_move(
        g, pid, difficulty=kind, rng=rng, rollout_steps=steps,
        max_iters=iters, time_limit=tl)


def play_game(a_kind: str, b_kind: str, seed: int, a_seat: int, rng=None) -> dict:
    """One game. `a_seat` (0/1) is which seat agent A takes.

    Each SEAT gets its own rng seeded from (seed, seat) — NOT one shared stream. That
    is what makes the seat-swapped pair a true CRN pair: with the same deck and the
    same per-seat randomness, a MIRROR match (identical configs) replays the identical
    game both ways, so the same seat wins both and A scores exactly 0.5. A shared rng
    interleaves the two searches' draws, so the paired games diverge and even a mirror
    drifts off 0.5 (measured 0.625 before this fix) — which quietly biases every A/B.
    """
    order = [P0, P1]
    game = engine.new_game(order, names={P0: "A0", P1: "A1"}, seed=seed)
    agents = {order[a_seat]: _agent(a_kind), order[1 - a_seat]: _agent(b_kind)}
    rngs = {order[s]: random.Random((seed << 8) | s) for s in (0, 1)}
    a_pid = order[a_seat]
    moves = 0
    for _ in range(4000):
        if engine.is_over(game):
            break
        actor = game.get("pending_pid") or game["turn"]
        mv = agents[actor](game, actor, rngs[actor])
        if mv is None:
            break
        ok, err = engine.apply_move(game, actor, mv)
        if not ok:
            raise AssertionError(f"agent produced an illegal move: {mv} ({err})")
        moves += 1
    winner = game.get("winner")
    return {
        "a_win": 1.0 if winner == a_pid else 0.0,
        "over": engine.is_over(game),
        "moves": moves,
        "cond": game.get("win_condition"),
        "a_pts": engine.points_of(game["players"][a_pid]),
        "b_pts": engine.points_of(game["players"][order[1 - a_seat]]),
    }


def arena(a_kind: str, b_kind: str, games: int, base_seed: int = 5000, quiet: bool = False) -> float:
    """Seat-swapped CRN pairs. Returns A's score in [0,1]."""
    score, n, conds, tot_moves, stalled = 0.0, 0, {}, 0, 0
    t0 = time.monotonic()
    pairs = max(1, games // 2)
    for i in range(pairs):
        seed = base_seed + i
        for a_seat in (0, 1):
            r = play_game(a_kind, b_kind, seed, a_seat)
            # Splendor Duel has NO turn limit: it ends only when someone meets a win
            # condition, so two players who never buy can play forever. Score a
            # stalled game as a draw and REPORT it — a rising `stalled` count is the
            # tell that an agent has stopped developing (it never crashes the run).
            if not r["over"]:
                stalled += 1
                score += 0.5
            else:
                score += r["a_win"]
                conds[r["cond"]] = conds.get(r["cond"], 0) + 1
            n += 1
            tot_moves += r["moves"]
    lo, hi = _wilson(score, n)
    dt = time.monotonic() - t0
    if not quiet:
        print(f"{a_kind} vs {b_kind}: {score/n:.4f} [{lo:.3f},{hi:.3f}] "
              f"n={n}  ({dt:.1f}s, {tot_moves/n:.0f} moves/game)")
        print(f"  win conditions: {conds}" + (f"  STALLED: {stalled}/{n}" if stalled else ""))
    return score / n


def probe(games: int) -> None:
    """Leaf A/B, head-to-head under CRN: is the rollout worth its ~40x sim cost?

    Two comparisons, because they answer different questions:
      * equal TIME  — the shipping question (the rollout must beat the ~40x extra
        sims a static leaf buys in the same budget).
      * equal SIMS  — the diagnostic (is the rollout a better leaf per simulation?).
    A mirror (same config both sides) must score ~0.5 — the harness sanity check.
    """
    # Budgets are trimmed vs the shipped tier so the probe finishes in minutes; the
    # COMPARISON is what matters and both sides get the identical budget.
    print("mirror sanity (must be ~0.5 — an unbiased harness):")
    arena("hard@12/600/0.4", "hard@12/600/0.4", games, base_seed=9000)
    print("equal TIME (the ship criterion — static gets ~16x the sims):")
    arena("hard@12/9999/0.4", "hard@0/9999/0.4", games, base_seed=9100)
    print("equal SIMS (diagnostic — is the rollout a better leaf PER sim?):")
    arena("hard@12/400/9", "hard@0/400/9", games, base_seed=9200)


def main() -> None:
    ap = argparse.ArgumentParser(description="Spender Duel AI arena")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("arena")
    a.add_argument("--a", default="hard")
    a.add_argument("--b", default="random")
    a.add_argument("--games", type=int, default=20)
    a.add_argument("--seed", type=int, default=5000)
    p = sub.add_parser("probe")
    p.add_argument("--games", type=int, default=6)
    args = ap.parse_args()
    if args.cmd == "arena":
        arena(args.a, args.b, args.games, args.seed)
    else:
        probe(args.games)


if __name__ == "__main__":
    main()
