"""Strength-neutrality A/B: the int8-quantized value leaf (:net8) vs the f32 value leaf (:net).

int8 is NOT bit-equal to f32 (per-position value MAE ~3.5e-3), so it CANNOT be gated by float
parity like the engine/leaf ports — it is gated by STRENGTH. Both sides are the SAME Rust MCTS
at EQUAL SIMS; the only difference is the trunk arithmetic (int8 vs f32). If the quantization is
strength-neutral (as intended — it exists for wasm throughput, not to change the bot), this reads
~0.5000.

Plus a net8-vs-net8 MIRROR that must read EXACTLY 0.5000: under CRN with per-seat deterministic
RNGs a mirror is deterministic, so a non-0.5000 means the harness (or the int8 path) is
nondeterministic and every other number is meaningless.

Reuses `gate_netleaf`'s play/match machinery (drive the Python engine, replay each decision into
the Rust `move_server` so the position the leaf searches IS the game position) — this just swaps
the two cfgs to net8/net. Requires the move_server built with the `net8` leaf:
    cargo build --release --features bridge
    python duel-core/tools/gate_net8.py --games 60 --sims 400
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import gate_netleaf as GN  # noqa: E402  (reuse match/new_thru; drives the Python engine + Rust server)
import rust_arena as R  # noqa: E402  (Server)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=60, help="deck seeds; each played BOTH seat orders")
    ap.add_argument("--sims", type=int, default=400, help="equal-SIMS count per decision")
    ap.add_argument("--seed", type=int, default=90000)
    args = ap.parse_args()

    NET8 = {"leaf": "net8", "sims": args.sims}
    NET = {"leaf": "net", "sims": args.sims}

    srv = R.Server()
    try:
        junk = GN.new_thru()  # throughput not reported here

        print("== MIRROR SANITY (CRN greedy - must read EXACTLY 0.5000) ==", flush=True)
        m, lo, hi, n = GN.match(srv, NET8, NET8, args.games, args.seed, junk)
        print(f"  net8 vs net8 @ {args.sims} sims : {m:.4f} [{lo:.3f},{hi:.3f}] n={n}", flush=True)

        print("\n== STRENGTH-NEUTRAL A/B (int8 leaf vs f32 leaf, equal sims) ==", flush=True)
        m, lo, hi, n = GN.match(srv, NET8, NET, args.games, args.seed, junk)
        print(f"  net8 vs net  @ {args.sims} sims : {m:.4f} [{lo:.3f},{hi:.3f}] n={n}", flush=True)
        print("  (~0.5000 = the int8 quantization is strength-neutral; the wasm throughput is free)", flush=True)
    finally:
        srv.close()


if __name__ == "__main__":
    main()
