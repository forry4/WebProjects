"""Does the net leaf's per-sim edge GROW with sims? The decisive follow-up to the gate.

The equal-wall-clock gate at a TIGHT 200ms budget showed the net leaf losing (0.30):
it runs 6.9x fewer sims than the cheap heuristic leaf, so at a tight budget it's
sim-starved. But the DEPLOYED Hard runs at ~1.5s x 4 cores — a far larger budget where
BOTH leaves may be saturated. If the net's per-sim edge grows with sims, it wins at that
large budget despite losing at 200ms; if the edge is flat, the equal-time loss stands.

So: net-vs-heur at increasing EQUAL sim counts (does the edge grow?), plus net-vs-net
adjacent doublings (where does the NET leaf's own strength saturate?). CRN, mirror-clean.

    python duel-core/tools/netleaf_simtrend.py --games 60
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gate_netleaf as GN  # noqa: E402  (reuse Server/match/new_thru/cfgs)
import rust_arena as R  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--seed", type=int, default=123000)
    ap.add_argument("--levels", default="400,1000,2000,4000")
    args = ap.parse_args()
    levels = [int(x) for x in args.levels.split(",")]
    srv = R.Server()
    try:
        print("== net vs heur, EQUAL SIMS — does the net's per-sim edge grow with depth? ==",
              flush=True)
        for s in levels:
            net = {"leaf": "net", "sims": s}
            heur = {"sims": s}
            p, lo, hi, n = GN.match(srv, net, heur, args.games, args.seed, GN.new_thru())
            print(f"  @ {s:5d} sims : net {p:.4f} [{lo:.3f},{hi:.3f}]  n={n}", flush=True)
        print("\n== net vs net, adjacent doublings — where does the NET leaf saturate? ==",
              flush=True)
        for a, b in [(1000, 2000), (2000, 4000), (4000, 8000)]:
            p, lo, hi, n = GN.match(srv, {"leaf": "net", "sims": b}, {"leaf": "net", "sims": a},
                                    args.games, args.seed + 5000, GN.new_thru())
            print(f"  net@{b} vs net@{a} : {p:.4f} [{lo:.3f},{hi:.3f}]  n={n}", flush=True)
    finally:
        srv.close()


if __name__ == "__main__":
    main()
