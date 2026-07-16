"""Measure Duel's strength-vs-sims curve, Rust-vs-Rust, to place the difficulty tiers.

The tiers (Easy/Normal/Hard) can only be separated by a sim cap if MORE sims actually
buys MORE strength across the range we'd use — and only up to the point where it
saturates. This measures exactly that: candidate sim levels vs a common reference, CRN
seat-swapped, so the win rates sit on one comparable axis.

Rust (not Python) because the reference and the top rungs run at sim counts that are
impractical in Python — and the two are equivalence-validated (leaf bit-identical, arena
0.560), which is all tier CALIBRATION needs. Greedy (temperature 0) by default so a
mirror is deterministic under CRN and reads EXACTLY 0.5000 — the harness sanity check.

    python duel-core/tools/sims_ladder.py --ref 2000 --levels 250,2000,8000 --games 20
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gen_engine_fixtures as G  # noqa: E402
import rust_arena as R  # noqa: E402  (reuse Server, dec_move, wilson)
from games.spender_duel import engine  # noqa: E402


def play(srv, seed, a_seat, cfg_a, cfg_b):
    """One game, A in seat `a_seat`. Each side searches with its own {sims, temperature}."""
    fills = []
    orig = engine._fill_board
    engine._fill_board = lambda g, rng: orig(g, G._SpyRng(rng, fills))
    try:
        g = engine.new_game([G.A, G.B], seed=seed)
        setup, setup_fills = G.setup_of(g), list(fills)
        fills.clear()
        hist = []
        for _ in range(4000):
            if engine.is_over(g):
                break
            actor = g.get("pending_pid") or g["turn"]
            seat = g["order"].index(actor)
            cfg = cfg_a if seat == a_seat else cfg_b
            req = {"setup": setup, "setup_fills": setup_fills, "moves": hist,
                   "seat": seat, "sims": cfg["sims"], "seed": (seed << 8) | seat}
            if cfg.get("temperature"):
                req["temperature"] = cfg["temperature"]
            mv = R.dec_move(srv.ask(req)["mv"])
            fills.clear()
            ok, err = engine.apply_move(g, actor, mv)
            assert ok, (cfg, mv, err)
            hist.append({"mv": G.enc_move(mv), "actor": seat, "fills": list(fills)})
    finally:
        engine._fill_board = orig
    if not engine.is_over(g) or g["winner"] is None:
        return 0.5
    return 1.0 if g["order"].index(g["winner"]) == a_seat else 0.0


def match(srv, cfg_a, cfg_b, games, seed0):
    total, n = 0.0, 0
    for i in range(games):
        for a_seat in (0, 1):                    # CRN: same deal, both seat orders
            total += play(srv, seed0 + i, a_seat, cfg_a, cfg_b)
            n += 1
    lo, hi = R.wilson(total, n)
    return total / n, lo, hi, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", type=int, default=2000, help="reference sims (the common opponent)")
    ap.add_argument("--levels", default="250,2000,8000", help="candidate sim levels")
    ap.add_argument("--games", type=int, default=20, help="deck seeds; each played both seat orders")
    ap.add_argument("--seed", type=int, default=41000)
    ap.add_argument("--temp", type=float, default=0.0, help="temperature for the CANDIDATE side")
    args = ap.parse_args()
    ref = {"sims": args.ref}
    levels = [int(x) for x in args.levels.split(",")]
    srv = R.Server()
    try:
        print(f"reference = greedy@{args.ref} sims   (candidate temp={args.temp})\n")
        print(f"  {'candidate':>18s}  {'win vs ref':>10s}  {'95% CI':>16s}")
        for lv in levels:
            cfg = {"sims": lv, "temperature": args.temp}
            p, lo, hi, n = match(srv, cfg, ref, args.games, args.seed)
            tag = f"greedy@{lv}" if not args.temp else f"t{args.temp}@{lv}"
            flag = "  <- mirror (want 0.5000)" if lv == args.ref and not args.temp else ""
            print(f"  {tag:>18s}  {p:10.4f}  [{lo:.3f},{hi:.3f}]{flag}", flush=True)
    finally:
        srv.close()


if __name__ == "__main__":
    main()
