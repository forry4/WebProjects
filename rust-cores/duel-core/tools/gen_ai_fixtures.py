"""Parity fixtures for the AI layer: the heuristic leaf `_value` and the pruned move
list `_legal` / `_rollout_top_tier`.

WHY A SEPARATE GATE FROM THE SEARCH ITSELF. The Rust MCTS can never be byte-identical to
the Python one — they draw from different RNGs, so their simulations diverge by
construction and no amount of care makes `rng.choice` line up across languages. That
leaves exactly two things to pin down, and they are the two that MATTER:

  * the LEAF (`_value`): if the Rust judges a position even slightly differently, its
    search is optimising a different game. Gated to ~1e-12 here.
  * the BRANCHES (`_legal`, `_rollout_top_tier`): if Rust considers a different set of
    moves — or the same set in a different ORDER — it is a different bot. Order is
    load-bearing: the rollout picks with `rng.choice(top)`, which indexes by position.

With the engine already state-exact (520 games / 54,271 moves) and these two pinned, the
only remaining freedom is the RNG stream, whose effect is measured statistically by the
cross-impl arena (Rust-vs-Python must read ~0.5 — the spender-core precedent).

Floats are written with repr(), which round-trips exactly through Rust's f64 parser, so
the comparison is on the actual bits and not a printed approximation.

    python duel-core/tools/gen_ai_fixtures.py --games 60
"""
import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import gen_engine_fixtures as G  # noqa: E402
from games.spender_duel import ai, bot, engine  # noqa: E402


def weights_blob() -> dict:
    """The exact WEIGHTS the fixtures were generated with.

    Shipped alongside so the Rust can assert it holds the SAME constants: a silently
    re-tuned Python weight would otherwise make every value fixture fail with no clue
    why, and — worse — a Rust that hardcodes stale weights would quietly play a
    different bot.
    """
    return dict(ai.WEIGHTS)


def play(seed: int, loaded: bool = False, max_moves: int = 4000) -> dict:
    fills: list = []
    orig_fill = engine._fill_board
    engine._fill_board = lambda game, rng: orig_fill(game, G._SpyRng(rng, fills))
    try:
        g = engine.new_game([G.A, G.B], seed=seed)
        setup = G.setup_of(g)
        setup_fills = list(fills)
        fills.clear()
        rng = random.Random(seed + 4241)
        pick = G._pick_loaded if loaded else bot.choose
        recs = []
        for _ in range(max_moves):
            if engine.is_over(g):
                break
            actor = g.get("pending_pid") or g["turn"]
            mv = pick(g, actor, rng)
            if mv is None:
                break
            fills.clear()
            ok, err = engine.apply_move(g, actor, mv)
            assert ok, (mv, err)
            rec = {"mv": G.enc_move(mv), "actor": g["order"].index(actor),
                   "fills": list(fills), "proj": G.proj(g)}
            # Leaf value from BOTH seats — a sign/perspective slip is a classic port bug
            # and would be invisible if we only ever checked the mover.
            rec["val"] = [repr(ai._value(g, p)) for p in g["order"]]
            if not engine.is_over(g):
                a2 = g.get("pending_pid") or g["turn"]
                rec["seat"] = g["order"].index(a2)
                rec["legal"] = [G.enc_move(m) for m in ai._legal(g, a2)]
                if g["pending_pid"] is None:
                    rec["top"] = [G.enc_move(m) for m in ai._rollout_top_tier(g, a2)]
            recs.append(rec)
    finally:
        engine._fill_board = orig_fill
    return {"seed": seed, "setup": setup, "setup_fills": setup_fills,
            "moves": recs, "over": engine.is_over(g)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--loaded", type=int, default=20)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "fixtures"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    dst = os.path.join(args.out, "ai_fixtures.jsonl")
    n = legal_n = top_n = 0
    with open(dst, "w", encoding="utf-8") as f:
        f.write(json.dumps({"weights": weights_blob()}) + "\n")   # header line
        for seed in range(args.games):
            fx = play(seed)
            n += len(fx["moves"])
            legal_n += sum(len(m.get("legal", ())) for m in fx["moves"])
            top_n += sum(len(m.get("top", ())) for m in fx["moves"])
            f.write(json.dumps(fx) + "\n")
        for seed in range(args.loaded):
            fx = play(2_000_000 + seed, loaded=True)
            n += len(fx["moves"])
            legal_n += sum(len(m.get("legal", ())) for m in fx["moves"])
            top_n += sum(len(m.get("top", ())) for m in fx["moves"])
            f.write(json.dumps(fx) + "\n")
    print(f"wrote {os.path.normpath(dst)}: {args.games + args.loaded} games, {n} positions")
    print(f"  value samples : {2 * n} (both seats)")
    print(f"  legal moves   : {legal_n}")
    print(f"  top-tier moves: {top_n}")


if __name__ == "__main__":
    main()
