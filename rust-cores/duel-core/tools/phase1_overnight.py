#!/usr/bin/env python
"""Phase-1 overnight driver: value-Expert runoff + the PIVOTAL policy-prior experiment.

Sequence (fully unattended; each result appends to the log + summary as it lands):
  0. Wait for the running value loop (azloop_coherent) to write "AZ LOOP DONE".
  1. cargo build all bridge bins (retry while gate_netleaf.exe is file-locked), mirror smoke.
  2. RUNOFF (tools/runoff.py): high-N disjoint-seed re-gate of all loop candidates -> the verified
     value-only champion (ship-gate #1) + the pivotal harvest's teacher/donor.
  3. PIVOTAL HARVEST: 4000 coherent games (8 shards x 500 @1200 sims, cpuct 0.3), teacher = winner.
  4. TRAINS: A = freeze-trunk qsoftmax (clean prior isolation), A2 = freeze-trunk visits,
     B = co-train + rootval-blend (the Phase-2 seed candidate).
  5. GATE SWEEP: G1-G3 prior-on-vs-off temps {1.0, 2.0, 0.5} @1000 sims x400g (THE GO/NO-GO),
     then B-gate, G4 (cpuct 0.3), G5 (depth 4000), G6 (equal-budget 2k-vs-8k), A2 at T*.
  Writes C:/Users/Forrest/duel_run/phase1/summary.txt incrementally; VERDICT line after G3.
"""
import json, os, re, subprocess, sys, time

CORE = r"C:/Users/Forrest/forrestm_projects/rust-cores/duel-core"
GATE = CORE + "/target/release/gate_netleaf.exe"
HARVEST = CORE + "/target/release/harvest_attn_pv.exe"
TRAIN = CORE + "/tools/train_attn_pv.py"
RUNOFF = CORE + "/tools/runoff.py"
CHAMP0 = CORE + "/src/attn_champion1_frozen.json"
VLOOP_LOG = r"C:/Users/Forrest/duel_run/azloop_coherent/log.txt"
P1 = r"C:/Users/Forrest/duel_run/phase1"
PY = sys.executable

os.makedirs(P1, exist_ok=True)
LOG = open(P1 + "/driver.log", "a")
SUMMARY = P1 + "/summary.txt"

def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    LOG.write(line + "\n"); LOG.flush()

def summarize(m):
    with open(SUMMARY, "a") as f:
        f.write(m + "\n")
    log(f"SUMMARY: {m}")

def run(cmd, cwd=CORE, timeout=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    return r.stdout or "", r.stderr or ""

GATE_RE = re.compile(r"NETLEAF GATE: .*: (\d+\.\d+) \[(\d+\.\d+), (\d+\.\d+)\]")

def gate(args):
    out, err = run([GATE] + args)
    m = GATE_RE.search(out)
    if not m:
        log(f"GATE PARSE FAIL: {out[-300:]} {err[-200:]}")
        return None, None, None
    return float(m.group(1)), float(m.group(2)), float(m.group(3))

# PHASE-1B controls (the minimax interception, 2026-07-26): the E1 minimax A/B was fired EARLY,
# concurrent with the runoff, because the pivotal harvest + GO/NO-GO gate are DOWNSTREAM of the
# search — running them under a search the E1 verdict is about to obsolete would mint another
# generation of conditional verdicts (the per-sim lesson). An interceptor kills this driver at
# runoff-end and relaunches it with:
#   P1_RESUME_FROM_RUNOFF=1  -> skip wait/build/smoke/runoff; read the winner from phase1/runoff.txt
#   P1_MINIMAX=1             -> harvest AND every gate run actor-signed (--minimax both sides)
RESUME_FROM_RUNOFF = os.environ.get("P1_RESUME_FROM_RUNOFF") == "1"
MINIMAX = os.environ.get("P1_MINIMAX") == "1"
MM_BOTH = ["--minimax", "--minimax-b"] if MINIMAX else []

def coherent_both(extra):
    return ["--coherent", "--cpuct", "1.0", "--coherent-b", "--cpuct-b", "1.0"] + MM_BOTH + extra

def main():
    if RESUME_FROM_RUNOFF:
        try:
            ro = open(P1 + "/runoff.txt").read()
        except OSError:
            summarize("ABORT: P1_RESUME_FROM_RUNOFF set but phase1/runoff.txt is missing")
            return
        mw = re.search(r"WINNER:\s*\n\s*(\S+)\s+->\s+(\S+)", ro)
        if not mw:
            summarize("ABORT: P1_RESUME_FROM_RUNOFF set but runoff.txt has no WINNER")
            return
        summarize(f"PHASE-1B RESUME: teacher={mw.group(1)} | minimax={'ON' if MINIMAX else 'OFF'} "
                  f"(E1 verdict) — harvest + ALL gates under this search")
        run_pivotal(mw.group(2))
        return

    # ── 0. wait for the value loop ──
    log("waiting for azloop_coherent to finish...")
    while True:
        try:
            if "AZ LOOP DONE" in open(VLOOP_LOG).read():
                break
        except OSError:
            pass
        time.sleep(120)
    log("value loop DONE — building bins")

    # ── 1. build (retry on file locks) + smoke ──
    for attempt in range(30):
        out, err = run(["cargo", "build", "--release", "--features", "bridge",
                        "--bin", "gate_netleaf", "--bin", "harvest_attn_pv", "--bin", "harvest_attn"])
        if "error" not in err.lower() or "Finished" in err:
            break
        log(f"build attempt {attempt}: retrying in 60s ({err[-150:]})")
        time.sleep(60)
    v, lo, hi = gate(coherent_both(["--leaf", "attnfile", "--attn-file", CHAMP0,
                                    "--leaf-b", "attnfile2", "--attn-file-b", CHAMP0,
                                    "--sims", "300", "--games", "10"]))
    log(f"smoke self-gate (must be ~0.5): {v}")
    if v is None:
        summarize("ABORT: smoke gate failed to run — investigate before anything else")
        return

    # ── 2. runoff ──
    log("runoff starting...")
    env = dict(os.environ, RUNOFF_GAMES="500", RUNOFF_HEUR_GAMES="300", RUNOFF_SIMS="1500")
    r = subprocess.run([PY, RUNOFF], capture_output=True, text=True, cwd=CORE, env=env)
    ro = r.stdout or ""
    with open(P1 + "/runoff.txt", "w") as f:
        f.write(ro + "\n--- stderr ---\n" + (r.stderr or ""))
    mw = re.search(r"WINNER:\s*\n\s*(\S+)\s+->\s+(\S+)", ro)
    ms = re.search(r"SHIP-GATE: vs-champ1 (\S+) .*vs-heur (\S+) vs baseline (\S+)", ro)
    if not mw:
        summarize("ABORT: runoff produced no WINNER — see phase1/runoff.txt")
        return
    winner_tag, winner = mw.group(1), mw.group(2)
    summarize(f"RUNOFF WINNER: {winner_tag} = {winner}")
    if ms:
        vc, vh, base = ms.group(1), ms.group(2), ms.group(3)
        try:
            ship = float(vc) >= 0.55 and float(vh) >= float(base) - 0.02
        except ValueError:
            ship = False
        summarize(f"SHIP-GATE-1: vs-champ1={vc} vs-heur={vh} baseline={base} -> {'PASS (ship the value Expert)' if ship else 'FAIL (no value ship; flywheel is the path)'}")

    run_pivotal(winner)

def run_pivotal(winner):
    # ── 3. pivotal harvest (teacher = winner) ──
    log(f"pivotal harvest: 8 x 500 games @1200 sims cpuct 0.3 minimax={MINIMAX}")
    os.makedirs(P1 + "/pv", exist_ok=True)
    procs = []
    for s in range(8):
        cmd = [HARVEST, "--attn-file", winner, "--games", "500", "--sims", "1200",
               "--cpuct", "0.3", "--target-temp", "0.03", "--temp-plies", "12", "--temp", "0.5",
               "--seed", str(5000 + s), "--out", f"{P1}/pv/shard_{s}.bin"]
        if MINIMAX:
            cmd.append("--minimax")
        lf = open(f"{P1}/pv/log_{s}.txt", "w")
        procs.append(subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=CORE))
    for p in procs:
        p.wait()
    ratios = []
    for s in range(8):
        try:
            txt = open(f"{P1}/pv/log_{s}.txt").read()
            m = re.search(r"ratio (\d+\.\d+)", txt)
            if m:
                ratios.append(float(m.group(1)))
        except OSError:
            pass
    summarize(f"HARVEST: entropy ratios {ratios} (tripwire >= 0.85)")
    if ratios and min(ratios) >= 0.85:
        summarize("ABORT: ALL shards near-uniform — coherent-Q premise failed at these settings; NO-GO by construction")
        return

    # ── 4. trains ──
    data = f"{P1}/pv/shard_*.bin"
    def train(out, extra):
        r = subprocess.run([PY, TRAIN, "--data", data, "--init", winner, "--out", out] + extra,
                           capture_output=True, text=True, cwd=CORE)
        m = re.search(r"saved .*val_top1 (\d+\.\d+)", r.stdout or "")
        return m.group(1) if m else None
    a_top1 = train(P1 + "/netA.json", ["--policy-target", "qsoftmax", "--target-temp", "0.03", "--epochs", "40"])
    summarize(f"TRAIN A (freeze, qsoftmax): val_top1={a_top1}")
    a2_top1 = train(P1 + "/netA2.json", ["--policy-target", "visits", "--epochs", "40"])
    summarize(f"TRAIN A2 (freeze, visits): val_top1={a2_top1}")
    b_top1 = train(P1 + "/netB.json", ["--no-freeze-trunk", "--rootval-blend", "0.3",
                                        "--policy-target", "qsoftmax", "--target-temp", "0.03", "--epochs", "15"])
    summarize(f"TRAIN B (co-train + rootval): val_top1={b_top1}")
    if not os.path.exists(P1 + "/netA.json"):
        summarize("ABORT: train A produced no net")
        return

    # ── 5. THE PIVOTAL GATE: prior-on vs prior-off, same net A both sides (value identical) ──
    A = P1 + "/netA.json"
    results = {}
    for tag, temp in [("G1_t1.0", "1.0"), ("G2_t2.0", "2.0"), ("G3_t0.5", "0.5")]:
        v, lo, hi = gate(coherent_both(["--leaf", "attnfile", "--attn-file", A,
                                        "--net-policy-temp", temp,
                                        "--leaf-b", "attnfile2", "--attn-file-b", A,
                                        "--sims", "1000", "--games", "400", "--seed", "80000"]))
        results[tag] = (v, lo, hi)
        summarize(f"PIVOTAL {tag}: prior-on vs prior-off = {v} [{lo}, {hi}]")
    best_tag = max((t for t in results if results[t][0] is not None), key=lambda t: results[t][0], default=None)
    if best_tag is None:
        summarize("ABORT: all pivotal gates failed to run")
        return
    bv, blo, bhi = results[best_tag]
    tstar = best_tag.split("_t")[1]
    if bv >= 0.53 and blo > 0.50:
        verdict = f"GO (strong)" if bv >= 0.55 else "GO"
    elif bv >= 0.52:
        verdict = "MARGINAL — run a 1200-game confirm before committing the loop"
    else:
        verdict = "NO-GO — prior dead even under coherent search (real closure)"
    summarize(f"VERDICT: {verdict} | best T*={tstar} at {bv} [{blo}, {bhi}]")

    # ── extras (may still be running in the morning; each appends as it lands) ──
    v, lo, hi = gate(coherent_both(["--leaf", "attnfile", "--attn-file", P1 + "/netB.json",
                                    "--net-policy-temp", tstar,
                                    "--leaf-b", "attnfile2", "--attn-file-b", winner,
                                    "--sims", "1000", "--games", "300", "--seed", "80000"]))
    summarize(f"B-GATE (co-train+prior vs donor): {v} [{lo}, {hi}] -> Phase-2 seed = {'netB' if (v or 0) >= 0.50 else 'donor + netA head'}")
    v, lo, hi = gate(["--leaf", "attnfile", "--attn-file", A, "--net-policy-temp", tstar,
                      "--coherent", "--cpuct", "0.3", "--coherent-b", "--cpuct-b", "0.3",
                      "--leaf-b", "attnfile2", "--attn-file-b", A,
                      "--sims", "1000", "--games", "400", "--seed", "80000"] + MM_BOTH)
    summarize(f"G4 (cpuct 0.3 both): {v} [{lo}, {hi}]")
    v, lo, hi = gate(coherent_both(["--leaf", "attnfile", "--attn-file", A, "--net-policy-temp", tstar,
                                    "--leaf-b", "attnfile2", "--attn-file-b", A,
                                    "--sims", "4000", "--games", "200", "--seed", "80000"]))
    summarize(f"G5 (depth 4000): {v} [{lo}, {hi}]")
    v, lo, hi = gate(coherent_both(["--leaf", "attnfile", "--attn-file", A, "--net-policy-temp", tstar,
                                    "--leaf-b", "attnfile2", "--attn-file-b", A,
                                    "--sims", "2000", "--sims-b", "8000", "--games", "200", "--seed", "80000"]))
    summarize(f"G6 (equal-budget guided@2k vs unguided@8k): {v} [{lo}, {hi}]")
    v, lo, hi = gate(coherent_both(["--leaf", "attnfile", "--attn-file", P1 + "/netA2.json",
                                    "--net-policy-temp", tstar,
                                    "--leaf-b", "attnfile2", "--attn-file-b", P1 + "/netA2.json",
                                    "--sims", "1000", "--games", "400", "--seed", "80000"]))
    summarize(f"A2-GATE (visits target, prior-on vs off): {v} [{lo}, {hi}]")
    summarize("PHASE-1 COMPLETE")

if __name__ == "__main__":
    main()
