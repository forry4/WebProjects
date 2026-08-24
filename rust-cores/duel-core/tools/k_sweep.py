#!/usr/bin/env python
"""Serving K-sweep: find the ideal number of coherent worlds to pool.

Production fans the search across ~N browser workers; each determinizes ONE world and searches it
coherently, and the results are pooled -> an N-world coherent ENSEMBLE. That N was chosen for CPU
parallelism, not strength. This sweep tests, at a FIXED TOTAL budget, how to allocate it: K worlds x
(total/K) sims each. K=1 = one deep world (what our 0.585 gate measured); large K = a shallow-but-
robust ensemble (what production actually runs, K ~= worker count ~= 8-12).

Each K is scored vs the OLD per-sim PIMC (champion-1 both leaves) so all K share one reference; the K
with the highest win is the ideal serving allocation. Also gates the best K vs K=1 directly (does the
ensemble beat a single deep world?).

  KSWEEP_GAMES=150 KSWEEP_SIMS=8000 python k_sweep.py
"""
import os, re, subprocess, sys

CORE = r"C:/Users/Forrest/forrestm_projects/rust-cores/duel-core"
GATE = CORE + "/target/release/gate_netleaf.exe"
CHAMP0 = CORE + "/src/attn_champion1_frozen.json"
GAMES = int(os.environ.get("KSWEEP_GAMES", 150))
# TOTAL sims split across K worlds = the REAL serving budget: main.py's _CLIENT_AI_MAX_SIMS
# aggregate cap, divided evenly across the pool (`perWorker = max_sims/n`). Tracks the cap —
# RAISED to 20000 on 2026-07-27 (saturation was measured under the old per-sim + max-max search).
# NOTE the wall-clock caveat: serving also stops at 3.5s, which now binds first on many machines,
# so the effective budget can be BELOW this; treat the sweep as the upper end of the range.
SIMS = int(os.environ.get("KSWEEP_SIMS", 20000))
SEED = int(os.environ.get("KSWEEP_SEED", 90000))
# REACHABLE K only. SpenderDuel.jsx sizes the pool `min(hardwareConcurrency-1, 4)` (the
# never-take-every-core rule), so serving K is 1-4 — typically 4 on >=5 cores, 3 on a quad-core.
# K=8/16 were in an earlier default and are UNREACHABLE in the browser: don't spend gates there.
KS = [int(x) for x in os.environ.get("KSWEEP_KS", "1,2,3,4").split(",")]
SUMMARY = r"C:/Users/Forrest/duel_run/phase1/summary.txt"

GATE_RE = re.compile(r"NETLEAF GATE: .*: (\d+\.\d+) \[(\d+\.\d+), (\d+\.\d+)\]")

# Adopt the E1 minimax verdict (same pattern as hp_sweep): serving will be coherent-K + MINIMAX,
# so the K allocation must be tuned under it. The per-sim reference side stays max-max — it is the
# historical baseline being measured against, not a config we'd ship.
def _minimax_won():
    try:
        txt = open(r"C:/Users/Forrest/duel_run/hp_sweep/summary.txt").read()
    except OSError:
        return False
    vals = [float(v) for v in re.findall(r"E1[ab] [^=]*= ([0-9.]+)", txt)]
    return bool(vals) and max(vals) >= 0.53
MM = _minimax_won()


def gate(a_extra, b_extra, games):
    cmd = ([GATE, "--leaf", "attnfile", "--attn-file", CHAMP0] + a_extra +
           ["--leaf-b", "attnfile2", "--attn-file-b", CHAMP0] + b_extra +
           ["--sims", str(SIMS), "--games", str(games), "--seed", str(SEED)])
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = GATE_RE.search(r.stdout or "")
    if not m:
        print(f"  GATE FAIL: {(r.stdout or '')[-200:]} {(r.stderr or '')[-150:]}", flush=True)
        return None, None, None
    return float(m.group(1)), float(m.group(2)), float(m.group(3))


def note(m):
    print(m, flush=True)
    try:
        with open(SUMMARY, "a") as f:
            f.write(m + "\n")
    except OSError:
        pass


def main():
    note(f"K-SWEEP: coherent-K{'+minimax' if MM else ''} vs per-sim PIMC (champion-1 both), {SIMS} total sims, {GAMES} games, seed {SEED}")
    # EARLY STOP on a clear negative trend: two CONSECUTIVE step-declines that leave us clearly below
    # the best-so-far (by > MARGIN). MARGIN guards the ~0.06 two-point noise at 150 games so a single
    # blip doesn't trip it; a genuine "2 worse than 1, 4 worse than 2" downtrend stops the sweep before
    # wasting gates on larger K. (Non-monotonic recovery resets the decline counter.)
    MARGIN = 0.04
    results = {}
    prev_v, best_v, best_k, declines = None, -1.0, None, 0
    mm_a = ["--minimax"] if MM else []
    for k in KS:
        v, lo, hi = gate(["--coherent", "--root-dets", str(k), "--cpuct", "1.0"] + mm_a, [], GAMES)
        results[k] = v
        note(f"  K={k:<2} coherent-{k}-world vs per-sim = {v} [{lo}, {hi}]  (K~=8-12 is current serving)")
        if v is None:
            continue
        declines = declines + 1 if (prev_v is not None and v < prev_v) else 0
        if v > best_v:
            best_v, best_k = v, k
        if declines >= 2 and v < best_v - MARGIN:
            note(f"EARLY STOP: {declines} consecutive declines, now {v:.4f} << peak K={best_k}={best_v:.4f} "
                 f"(by >{MARGIN}); larger K won't recover — skipping {[x for x in KS if x > k]}")
            break
        prev_v = v
    valid = {k: v for k, v in results.items() if v is not None}
    if not valid:
        note("K-SWEEP: all gates failed")
        return
    best = max(valid, key=valid.get)
    note(f"BEST K = {best} at {valid[best]:.4f}  (ideal serving world-count at {SIMS} total sims)")
    # Confirm the ensemble beats a single deep world head-to-head (unless best IS 1).
    if best != 1:
        mm_b = ["--minimax-b"] if MM else []
        v, lo, hi = gate(["--coherent", "--root-dets", str(best), "--cpuct", "1.0"] + mm_a,
                         ["--coherent-b", "--root-dets-b", "1", "--cpuct-b", "1.0"] + mm_b, GAMES)
        note(f"CONFIRM: coherent-K={best} vs coherent-K=1 (both champion-1) = {v} [{lo}, {hi}]  (>0.5 = ensemble beats single deep world)")
    note("K-SWEEP COMPLETE")


if __name__ == "__main__":
    main()
