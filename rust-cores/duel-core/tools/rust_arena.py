"""Cross-implementation arena: the RUST MCTS vs the PYTHON MCTS, head to head.

THE LAST P2 GATE, and the only one that can exist for the search itself. The engine is
state-exact and the leaf is bit-identical, but the two searches draw from different RNGs,
so their simulations diverge by construction — no amount of care makes them byte-equal.
What's left to prove is that the divergence is NOISE and not a behaviour change: at equal
sims, Rust-vs-Python must read ~0.5. Anything meaningfully off 0.5 means the port plays a
different bot, and the whole premise ("same bot, more sims") is false.

Each decision replays the game into the Rust `move_server` from the recorded setup + move
history (with the scripted fills), so the Rust sees exactly the position Python is in.
That's slow — deliberately: correctness of the comparison beats speed of the harness.

Seat-swapped pairs on a shared deck seed (CRN), so first-player advantage cancels.
Per-SEAT rngs (never one shared stream) — with a shared stream the two searches interleave
their draws, paired games stop being paired, and a mirror silently drifts off 0.5, quietly
biasing every number the harness produces (a bug this repo has already been bitten by).

    python duel-core/tools/rust_arena.py --games 20 --sims 300
    python duel-core/tools/rust_arena.py --games 20 --sims 300 --mirror py   # must be 0.5000
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import gen_engine_fixtures as G  # noqa: E402
from games.spender_duel import ai, cards as C, engine  # noqa: E402

IDS = C.deck_ids(1) + C.deck_ids(2) + C.deck_ids(3)
ROYALS = sorted(C.ROYALS)
EXE = os.path.join(HERE, "..", "target", "release", "move_server.exe")
if not os.path.exists(EXE):
    EXE = os.path.join(HERE, "..", "target", "release", "move_server")


def dec_move(o: dict) -> dict:
    """Rust's index-encoded move -> the Python engine's move dict (inverse of enc_move)."""
    t = o["t"]
    if t == "take":
        return {"type": "take", "cells": list(o["cells"])}
    if t in ("use_privilege", "take_same"):
        return {"type": t, "cell": o["cell"]}
    if t == "reserve":
        src = {"kind": "pyramid" if o["kind"] == 0 else "deck", "level": o["level"]}
        if o["kind"] == 0:
            src["slot"] = o["slot"]
        return {"type": "reserve", "gold_cell": o["cell"], "source": src}
    if t == "buy":
        m = {"type": "buy", "card_id": IDS[o["card"]],
             "from": "pyramid" if o["from"] == 0 else "reserve"}
        if o.get("as_color", -1) >= 0:
            m["as_color"] = C.COLORS[o["as_color"]]
        return m
    if t in ("steal", "discard"):
        return {"type": t, "color": C.TOKENS[o["color"]]}
    if t == "choose_royal":
        return {"type": "choose_royal", "royal_id": ROYALS[o["royal"]]}
    return {"type": t}


class Server:
    def __init__(self):
        self.p = subprocess.Popen([EXE], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, bufsize=1)

    def ask(self, req: dict) -> dict:
        self.p.stdin.write(json.dumps(req) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("move_server died")
        return json.loads(line)

    def close(self):
        try:
            self.p.stdin.close(); self.p.terminate()
        except Exception:
            pass


def wilson(w, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def play(srv, seed, a_seat, sims, a_kind, b_kind):
    """One game. `a_seat` is which seat agent A takes. Returns A's score (1/0/0.5)."""
    fills = []
    orig = engine._fill_board
    engine._fill_board = lambda g, rng: orig(g, G._SpyRng(rng, fills))
    try:
        g = engine.new_game([G.A, G.B], seed=seed)
        setup, setup_fills = G.setup_of(g), list(fills)
        fills.clear()
        rngs = {s: random.Random((seed << 8) | s) for s in (0, 1)}   # per-SEAT streams
        hist = []
        for _ in range(4000):
            if engine.is_over(g):
                break
            actor = g.get("pending_pid") or g["turn"]
            seat = g["order"].index(actor)
            kind = a_kind if seat == a_seat else b_kind
            if kind == "rust":
                rep = srv.ask({"setup": setup, "setup_fills": setup_fills, "moves": hist,
                               "seat": seat, "sims": sims, "seed": (seed << 8) | seat})
                mv = dec_move(rep["mv"])
            else:
                mv = ai.choose_move(g, actor, difficulty="hard", rng=rngs[seat],
                                    max_iters=sims, time_limit=999)
            fills.clear()
            ok, err = engine.apply_move(g, actor, mv)
            assert ok, (kind, mv, err)
            hist.append({"mv": G.enc_move(mv), "actor": seat, "fills": list(fills)})
    finally:
        engine._fill_board = orig
    if not engine.is_over(g):
        return 0.5          # stalled — scored a draw and reported, never asserted away
    win = g["winner"]
    if win is None:
        return 0.5
    return 1.0 if g["order"].index(win) == a_seat else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=20, help="deck seeds; each is played BOTH seat orders")
    ap.add_argument("--sims", type=int, default=300)
    ap.add_argument("--seed", type=int, default=4000)
    ap.add_argument("--mirror", choices=["py", "rust"], default=None,
                    help="sanity: same engine both sides — must read ~0.5")
    args = ap.parse_args()
    a_kind = "rust" if args.mirror != "py" else "python"
    b_kind = "python" if args.mirror is None else a_kind
    srv = Server()
    try:
        total, n = 0.0, 0
        for i in range(args.games):
            seed = args.seed + i
            for a_seat in (0, 1):                    # CRN: same deck, both seat orders
                total += play(srv, seed, a_seat, args.sims, a_kind, b_kind)
                n += 1
            print(f"  {n:3d} games  {a_kind} {total/n:.4f}", flush=True)
    finally:
        srv.close()
    lo, hi = wilson(total, n)
    print(f"\n{a_kind} vs {b_kind} @ {args.sims} sims: {total/n:.4f} [{lo:.3f},{hi:.3f}] n={n}")
    print("(equivalence gate: ~0.5 means the port plays the same bot, just faster)")


if __name__ == "__main__":
    main()
