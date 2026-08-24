"""Gate the EXACT ENDGAME SEARCH augmentation against the PLAIN MCTS (Part C).

Both sides are the SAME Rust bot; the only difference is that the AUGMENTED side, when a
position is `in_endgame` and the exact `endgame` minimax is CONCLUSIVE, plays the exact
minimax's move instead of the sampled MCTS pick (and pays for it out of the same wall-clock
budget — inconclusive/non-endgame decisions fall back to the MCTS with the remaining time).
So this measures exactly the thing that matters: does perfect endgame play, PAID FOR at equal
wall-clock, make Hard stronger?

  * THE GATE (equal WALL-CLOCK, the ship criterion): augmented vs plain, same ms/decision,
    CRN seat-swapped (first-player advantage cancels). >0.5 = it helps; ~0.5 = a wash.
  * MIRROR SANITY (equal-SIMS greedy, CRN, deterministic): plain-vs-plain AND aug-vs-aug must
    read EXACTLY 0.5000 — the endgame search is deterministic given its seed, so a mirror is a
    fixed game whose seat-swapped pair sums to 1. Anything off 0.5 means the harness is biased
    and every other number is meaningless.
  * TRIGGER STATS (from the augmented side's responses): how often the endgame search fired,
    how often it was conclusive, and how often it proved a forced win.

    python duel-core/tools/gate_endgame.py --games 60
    python duel-core/tools/gate_endgame.py --games 60 --budget-ms 200
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gen_engine_fixtures as G  # noqa: E402
import rust_arena as R  # noqa: E402  (reuse Server, dec_move, wilson)
from games.spender_duel import engine  # noqa: E402

# Keys forwarded verbatim into the move_server request (the endgame knobs).
EG_KEYS = ("eg_depth", "eg_node_cap", "eg_dets", "eg_thresh")


def req_for(cfg, setup, setup_fills, hist, seat, seed):
    """Build a move_server request. `cfg` carries `endgame` (bool) + a budget (`budget_ms` for
    the wall-clock gate, or `sims` for the deterministic mirror) + optional `eg_*` knobs."""
    r = {"setup": setup, "setup_fills": setup_fills, "moves": hist,
         "seat": seat, "seed": (seed << 8) | seat}
    if cfg.get("budget_ms") is not None:
        r["budget_ms"] = cfg["budget_ms"]
    else:
        r["sims"] = cfg["sims"]
    if cfg.get("endgame"):
        r["endgame"] = True
        for k in EG_KEYS:
            if k in cfg:
                r[k] = cfg[k]
    return r


def play(srv, seed, a_seat, cfg_a, cfg_b, stats):
    """One game, agent A in seat `a_seat`. `stats` accumulates the AUGMENTED side's per-decision
    endgame telemetry. Returns A's score (1/0/0.5)."""
    fills = []
    orig = engine._fill_board
    engine._fill_board = lambda g, rng: orig(g, G._SpyRng(rng, fills))
    try:
        g = engine.new_game([G.A, G.B], seed=seed)
        setup, setup_fills = G.setup_of(g), list(fills)
        fills.clear()
        hist = []  # the growing move history; the stateless server replays it each request
        for _ in range(4000):
            if engine.is_over(g):
                break
            actor = g.get("pending_pid") or g["turn"]
            seat = g["order"].index(actor)
            cfg = cfg_a if seat == a_seat else cfg_b
            rep = srv.ask(req_for(cfg, setup, setup_fills, hist, seat, seed))
            _accumulate(cfg, rep, stats)
            mv = R.dec_move(rep["mv"])
            fills.clear()
            ok, err = engine.apply_move(g, actor, mv)
            assert ok, (cfg, mv, err)
            hist.append({"mv": G.enc_move(mv), "actor": seat, "fills": list(fills)})
    finally:
        engine._fill_board = orig
    if not engine.is_over(g) or g["winner"] is None:
        return 0.5
    return 1.0 if g["order"].index(g["winner"]) == a_seat else 0.0


def _accumulate(cfg, rep, stats):
    if not cfg.get("endgame"):
        return
    stats["decisions"] += 1
    if rep.get("endgame_triggered"):
        stats["triggered"] += 1
        if rep.get("endgame_conclusive"):
            stats["conclusive"] += 1
            if rep.get("proven_win"):
                stats["proven"] += 1


def new_stats():
    return {"decisions": 0, "triggered": 0, "conclusive": 0, "proven": 0}


def match(srv, cfg_a, cfg_b, games, seed0, stats):
    total, n = 0.0, 0
    for i in range(games):
        for a_seat in (0, 1):  # CRN: same deal, both seat orders
            total += play(srv, seed0 + i, a_seat, cfg_a, cfg_b, stats)
            n += 1
    lo, hi = R.wilson(total, n)
    return total / n, lo, hi, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=60, help="deck seeds; each played BOTH seat orders (2 games)")
    ap.add_argument("--budget-ms", type=float, default=200.0, help="equal-WALL-CLOCK budget per decision (the ship criterion)")
    ap.add_argument("--mirror-sims", type=int, default=300, help="deterministic mirror-sanity sim count")
    ap.add_argument("--mirror-games", type=int, default=10, help="mirror-sanity deck seeds (the aug mirror runs the exact search to its node cap, so keep it small — determinism makes a handful enough)")
    ap.add_argument("--seed", type=int, default=70000)
    ap.add_argument("--eg-depth", type=int, default=None)
    ap.add_argument("--eg-node-cap", type=int, default=None)
    ap.add_argument("--eg-dets", type=int, default=None)
    ap.add_argument("--eg-thresh", type=float, default=None)
    args = ap.parse_args()

    eg = {}
    if args.eg_depth is not None:
        eg["eg_depth"] = args.eg_depth
    if args.eg_node_cap is not None:
        eg["eg_node_cap"] = args.eg_node_cap
    if args.eg_dets is not None:
        eg["eg_dets"] = args.eg_dets
    if args.eg_thresh is not None:
        eg["eg_thresh"] = args.eg_thresh

    # Gate configs (equal wall-clock).
    AUG_T = {"endgame": True, "budget_ms": args.budget_ms, **eg}
    PLAIN_T = {"budget_ms": args.budget_ms}
    # Mirror configs (equal sims, deterministic → exactly 0.5000).
    AUG_S = {"endgame": True, "sims": args.mirror_sims, **eg}
    PLAIN_S = {"sims": args.mirror_sims}

    srv = R.Server()
    try:
        junk = new_stats()
        print("== MIRROR SANITY (equal-sims, CRN — must read EXACTLY 0.5000) ==", flush=True)
        pm, plo, phi, pn = match(srv, PLAIN_S, PLAIN_S, args.mirror_games, args.seed, junk)
        print(f"  plain vs plain @ {args.mirror_sims} sims : {pm:.4f} [{plo:.3f},{phi:.3f}] n={pn}", flush=True)
        junk = new_stats()
        am, alo, ahi, an = match(srv, AUG_S, AUG_S, args.mirror_games, args.seed, junk)
        print(f"  aug   vs aug   @ {args.mirror_sims} sims : {am:.4f} [{alo:.3f},{ahi:.3f}] n={an}", flush=True)

        print(f"\n== THE GATE (equal WALL-CLOCK: {args.budget_ms:.0f} ms/decision) ==", flush=True)
        stats = new_stats()
        gm, glo, ghi, gn = match(srv, AUG_T, PLAIN_T, args.games, args.seed, stats)
        print(f"  augmented vs plain : {gm:.4f} [{glo:.3f},{ghi:.3f}] n={gn}", flush=True)

        print("\n== ENDGAME TRIGGER STATS (augmented side) ==", flush=True)
        d = max(stats["decisions"], 1)
        tr = max(stats["triggered"], 1)
        print(f"  decisions            : {stats['decisions']}", flush=True)
        print(f"  in_endgame triggered : {stats['triggered']} ({100.0*stats['triggered']/d:.1f}% of decisions)", flush=True)
        print(f"  conclusive           : {stats['conclusive']} ({100.0*stats['conclusive']/tr:.1f}% of triggered)", flush=True)
        print(f"  proven forced wins   : {stats['proven']}", flush=True)
    finally:
        srv.close()

    print("\n== VERDICT ==", flush=True)
    print(f"  GATE (equal wall-clock): augmented {gm:.4f} [{glo:.3f},{ghi:.3f}]", flush=True)
    print("  (>0.5 = exact endgame play is a real strength gain; ~0.5 = wash; <0.5 = its cost outweighs it)", flush=True)


if __name__ == "__main__":
    main()
