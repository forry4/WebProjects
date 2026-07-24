"""Gate the LEARNED VALUE LEAF against the HAND-TUNED heuristic leaf (Phase 2).

Both sides are the SAME Rust MCTS; the only difference is the leaf evaluator - one truncates
to the trained value net (`value_net.json`), the other to the deployed rollout+heuristic. So
this measures exactly the thing that matters: is the net a better LEAF, and does that survive
the fact that it is SLOWER (fewer sims in the same wall-clock)?

TWO measurements, both CRN seat-swapped (first-player advantage cancels), driven through the
Python engine and replayed into the Rust `move_server` (the position the net searches is, by
construction, the position the game is in):

  * EQUAL WALL-CLOCK (--budget-ms, THE SHIP CRITERION): each side gets the same ms/decision.
    The net side does FEWER sims - that is the honest comparison. A win here means the better
    leaf pays for its cost.
  * EQUAL SIMS (--sims, the DIAGNOSTIC): both sides same sim count. Isolates "is the net a
    better leaf PER SIM" from its speed penalty.

Plus a MIRROR SANITY (heur-vs-heur AND net-vs-net, equal-sims greedy): under CRN with
per-seat deterministic RNGs a mirror is deterministic and must read EXACTLY 0.5000. If it
does not, the harness is biased and every other number is meaningless.

And the measured sims/s of each leaf (from the equal-time games) so the handicap is quantified.

    python duel-core/tools/gate_netleaf.py --games 60
    python duel-core/tools/gate_netleaf.py --games 60 --budget-ms 200 --sims 400
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gen_engine_fixtures as G  # noqa: E402
import rust_arena as R  # noqa: E402  (reuse Server, dec_move, wilson)
from games.spender_duel import engine  # noqa: E402


def req_for(cfg, setup, setup_fills, hist, seat, seed):
    """Build a move_server request for `cfg` = {leaf?, and (sims | budget_ms)}."""
    r = {"setup": setup, "setup_fills": setup_fills, "moves": hist,
         "seat": seat, "seed": (seed << 8) | seat}
    if cfg.get("leaf"):
        r["leaf"] = cfg["leaf"]           # "net" => learned leaf; absent => heuristic
    if cfg.get("budget_ms") is not None:
        r["budget_ms"] = cfg["budget_ms"]  # wall-clock mode (overrides sims)
    else:
        r["sims"] = cfg["sims"]            # fixed-iteration mode
    return r


def play(srv, seed, a_seat, cfg_a, cfg_b, thru):
    """One game, agent A in seat `a_seat`. Each decision goes to the Rust server with that
    seat's cfg. `thru` accumulates per-leaf {sims, ms} over decisions that actually searched
    (sims>0), so the caller can report each leaf's sims/s. Returns A's score (1/0/0.5)."""
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
            actor = g.get("pending_pid") or g["turn"]   # pending_pid is a truthy player-id or None
            seat = g["order"].index(actor)
            cfg = cfg_a if seat == a_seat else cfg_b
            rep = srv.ask(req_for(cfg, setup, setup_fills, hist, seat, seed))
            mv = R.dec_move(rep["mv"])
            sims = rep.get("sims", 0)
            if sims > 0:                                 # skip single-move decisions (no search)
                tag = "net" if cfg.get("leaf") == "net" else "heur"
                thru[tag]["sims"] += sims
                thru[tag]["ms"] += rep.get("elapsed_ms", 0.0)
            fills.clear()
            ok, err = engine.apply_move(g, actor, mv)
            assert ok, (cfg, mv, err)
            hist.append({"mv": G.enc_move(mv), "actor": seat, "fills": list(fills)})
    finally:
        engine._fill_board = orig
    if not engine.is_over(g) or g["winner"] is None:
        return 0.5                                       # stalled/draw - reported, never asserted away
    return 1.0 if g["order"].index(g["winner"]) == a_seat else 0.0


def match(srv, cfg_a, cfg_b, games, seed0, thru):
    total, n = 0.0, 0
    for i in range(games):
        for a_seat in (0, 1):                            # CRN: same deal, both seat orders
            total += play(srv, seed0 + i, a_seat, cfg_a, cfg_b, thru)
            n += 1
    lo, hi = R.wilson(total, n)
    return total / n, lo, hi, n


def new_thru():
    return {"net": {"sims": 0, "ms": 0.0}, "heur": {"sims": 0, "ms": 0.0}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=60, help="deck seeds; each played BOTH seat orders (2 games)")
    ap.add_argument("--budget-ms", type=float, default=200.0, help="equal-WALL-CLOCK budget per decision (the ship criterion)")
    ap.add_argument("--sims", type=int, default=400, help="equal-SIMS count per decision (the diagnostic)")
    ap.add_argument("--seed", type=int, default=90000)
    args = ap.parse_args()

    NET_S = {"leaf": "net", "sims": args.sims}
    HEUR_S = {"sims": args.sims}
    NET_T = {"leaf": "net", "budget_ms": args.budget_ms}
    HEUR_T = {"budget_ms": args.budget_ms}

    srv = R.Server()
    try:
        junk = new_thru()  # throughput from mirror/equal-sims runs is not reported

        print("== MIRROR SANITY (equal-sims greedy, CRN - must read EXACTLY 0.5000) ==", flush=True)
        hm, hlo, hhi, hn = match(srv, HEUR_S, HEUR_S, args.games, args.seed, junk)
        print(f"  heur vs heur @ {args.sims} sims : {hm:.4f} [{hlo:.3f},{hhi:.3f}] n={hn}", flush=True)
        nm, nlo, nhi, nn = match(srv, NET_S, NET_S, args.games, args.seed, junk)
        print(f"  net  vs net  @ {args.sims} sims : {nm:.4f} [{nlo:.3f},{nhi:.3f}] n={nn}", flush=True)

        print("\n== EQUAL SIMS (diagnostic: better leaf PER SIM?) ==", flush=True)
        es, elo, ehi, en = match(srv, NET_S, HEUR_S, args.games, args.seed, junk)
        print(f"  net vs heur @ {args.sims} sims  : {es:.4f} [{elo:.3f},{ehi:.3f}] n={en}", flush=True)

        print(f"\n== EQUAL WALL-CLOCK (THE SHIP CRITERION: {args.budget_ms:.0f} ms/decision) ==", flush=True)
        thru = new_thru()
        ts, tlo, thi, tn = match(srv, NET_T, HEUR_T, args.games, args.seed, thru)
        print(f"  net vs heur @ {args.budget_ms:.0f} ms   : {ts:.4f} [{tlo:.3f},{thi:.3f}] n={tn}", flush=True)

        print("\n== MEASURED sims/s per leaf (from the equal-time games) ==", flush=True)
        for tag in ("heur", "net"):
            s, ms = thru[tag]["sims"], thru[tag]["ms"]
            rate = (s / (ms / 1000.0)) if ms > 0 else float("nan")
            print(f"  {tag:>4s}: {rate:9.0f} sims/s  ({s:,} sims over {ms/1000.0:.1f}s search)", flush=True)
        hr = thru["heur"]["sims"] / (thru["heur"]["ms"] / 1000.0) if thru["heur"]["ms"] else float("nan")
        nr = thru["net"]["sims"] / (thru["net"]["ms"] / 1000.0) if thru["net"]["ms"] else float("nan")
        if nr and nr == nr and hr and hr == hr:
            print(f"  handicap: the net leaf runs {hr/nr:.1f}x FEWER sims than the heuristic at equal time", flush=True)
    finally:
        srv.close()

    print("\n== VERDICT ==", flush=True)
    print(f"  EQUAL-TIME (ship): net {ts:.4f} [{tlo:.3f},{thi:.3f}]  |  EQUAL-SIMS (diag): net {es:.4f} [{elo:.3f},{ehi:.3f}]", flush=True)
    print("  (>0.5 at equal wall-clock = the net leaf is a real strength gain; ~0.5 = wash; <0.5 = the speed cost outweighs it)", flush=True)


if __name__ == "__main__":
    main()
