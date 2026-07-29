#!/usr/bin/env python
"""Opponent-model sweep: where between MINIMAX and EXPECTIMAX should the search sit?

`Opts::opp_c` is the c_puct used at nodes whose actor is not the root player. With minimax on, an
opponent node selects by `-Q + c·P·√N/(1+n)`:
  * LOW  opp_c -> it commits to its single best reply            = hard minimax
  * HIGH opp_c -> its visits stay spread, so what propagates up
                  is closer to an average over its replies       = expectimax (unknown/weak opponent)

Both extremes are wrong for different reasons, which is why an interior optimum is plausible:
hard minimax in a DETERMINIZED search models an opponent who can SEE the sampled hidden world
(deck order, our reserves) — the classic PIMC over-pessimism — while pure averaging is the
accidental behaviour the per-sim era had (U dominated, visits near-uniform). Every other
temperature-like knob in this campaign has had an interior optimum: the policy prior peaked at
T*=2.0 and LOST at 0.5.

There is also a target-specific reason to look: against a HUMAN who blunders, strict minimax is
pessimistic — it avoids lines the opponent could refute but probably won't. The goal is beating a
person, not solving the game.

Method: screen at K=1 (cheap), then CONFIRM the winner at serving shape (--pool 4) — the
2026-07-27 rule. Side B is always the shipped config (opp_c unset = same c as ours).

  OPP_GAMES=200 OPP_SIMS=1500 python opp_model_sweep.py
"""
import os, re, subprocess

CORE = r"C:/Users/Forrest/forrestm_projects/rust-cores/duel-core"
# The fresh binary (target/ is held by the flywheel; target-pool/ is the side build).
GATE = os.environ.get("OPP_GATE", CORE + "/target-pool/release/gate_netleaf.exe")
NET = os.environ.get("OPP_NET", r"C:/Users/Forrest/duel_run/phase1/netB.json")  # the SHIPPED net
RUN = r"C:/Users/Forrest/duel_run/opp_model"
GAMES = int(os.environ.get("OPP_GAMES", 200))
SIMS = int(os.environ.get("OPP_SIMS", 1500))
POOL_SIMS = int(os.environ.get("OPP_POOL_SIMS", 1200))  # per worker, at the confirm
SEED = int(os.environ.get("OPP_SEED", 97000))  # disjoint from every other seed base in use
POINTS = [float(x) for x in os.environ.get("OPP_POINTS", "0.3,3.0,10.0").split(",")]

GATE_RE = re.compile(r"NETLEAF GATE: .*: (\d+\.\d+) \[(\d+\.\d+), (\d+\.\d+)\]")
os.makedirs(RUN, exist_ok=True)


def note(m):
    print(m, flush=True)
    with open(RUN + "/summary.txt", "a") as f:
        f.write(m + "\n")


def gate(a_extra, games, sims, pool=None):
    """Side A = shipped config + a_extra; side B = shipped config exactly."""
    def side(tag, extra):
        s = ([f"--leaf{tag}", "attnfile" if not tag else "attnfile2",
              f"--attn-file{tag}", NET,
              f"--net-policy-temp{tag}", "2.0",
              f"--coherent{tag}", f"--cpuct{tag}", "1.0", f"--minimax{tag}"] + extra)
        if pool:
            s += [f"--pool{tag}", str(pool)]
        return s
    cmd = ([GATE] + side("", a_extra) + side("-b", []) +
           ["--sims", str(sims), "--games", str(games), "--seed", str(SEED)])
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = GATE_RE.search(r.stdout or "")
    if not m:
        note(f"  GATE FAIL: {(r.stdout or '')[-200:]} {(r.stderr or '')[-150:]}")
        return None, None, None
    return float(m.group(1)), float(m.group(2)), float(m.group(3))


def main():
    note(f"=== OPPONENT-MODEL SWEEP (netB both sides, shipped config, seed {SEED}) ===")
    note("low opp_c = hard minimax | 1.0 = shipped | high = expectimax-ish")

    # CONTROL: opp_c == our c_puct is literally the same code path -> must read ~0.5000 exactly.
    # If it does not, the knob is not inert at its default and nothing below can be trusted.
    v, lo, hi = gate(["--opp-c", "1.0"], 40, SIMS)
    note(f"CONTROL opp_c=1.0 (== default) = {v} [{lo}, {hi}]  (must be ~0.5000)")
    if v is None or abs(v - 0.5) > 0.02:
        note("!! CONTROL FAILED — the knob is not inert at its default. Stopping.")
        return

    # POINTS is a LADDER in opponent-node concentration (low = hard minimax -> high = expectimax),
    # not an unordered argmax over independent options, so the campaign's early-stop rule applies:
    # once the ladder turns down, further points go further in the losing direction. Retrofitted
    # 2026-07-28 after the first run measured 0.3=0.540 and would have spent ~35min on 10.0 anyway.
    results = {}
    prev = None
    for p in POINTS:
        v, lo, hi = gate(["--opp-c", str(p)], GAMES, SIMS)
        results[p] = v
        kind = "harder minimax" if p < 1.0 else "softer / expectimax-ish"
        note(f"  opp_c={p:<5} ({kind:<22}) = {v} [{lo}, {hi}]  ({GAMES}g @{SIMS} sims, K=1)")
        if v is not None and prev is not None and v < prev:
            note(f"  EARLY STOP: the ladder turned down ({v:.4f} < {prev:.4f}) — "
                 f"remaining points go further in the losing direction, not running them")
            break
        if v is not None:
            prev = v

    valid = {p: v for p, v in results.items() if v is not None}
    if not valid:
        note("all points failed")
        return
    best = max(valid, key=valid.get)
    note(f"BEST opp_c = {best} at {valid[best]:.4f} (K=1 screen)")
    if valid[best] < 0.53:
        note("no point clears 0.53 -> the shipped symmetric opponent model stands; NOT confirming at pool.")
        return
    # CONFIRM at serving shape — a K=1 screen never ships (the 2026-07-27 rule).
    v, lo, hi = gate(["--opp-c", str(best)], 150, POOL_SIMS, pool=4)
    note(f"CONFIRM opp_c={best} @pool=4 x{POOL_SIMS} = {v} [{lo}, {hi}]  (>0.53 lower-CI>0.50 to ship)")
    note("=== OPPONENT-MODEL SWEEP COMPLETE ===")


if __name__ == "__main__":
    main()
