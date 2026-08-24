#!/usr/bin/env python
"""High-N runoff to pick the strongest candidate across the azloop runs, de-biasing the winner's
curse in the 150-game per-iter gates (max over ~N noisy estimates overstates its winner by ~6pp).

Shortlists the top-K candidates by EACH fixed yardstick (per-iter vs-champion1 and vs-heur), then
re-gates each survivor vs champion-1 AND the heuristic at high N on a DISJOINT seed base (90000 —
the loop gates use 70000; re-using the loop's decks would re-include the lucky ones and NOT de-bias).
Gates run SERVING-REAL: coherent both sides at cpuct 1.0; a PV candidate carries its policy prior.
Also measures the champion-1-vs-heur baseline row so ship criteria have a measured reference.

  RUNOFF_DRY=1 python runoff.py                    # print the shortlist only (validates parsing)
  RUNOFF_GAMES=500 RUNOFF_HEUR_GAMES=300 RUNOFF_SIMS=1500 python runoff.py
"""
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys

CORE = r"C:/Users/Forrest/forrestm_projects/rust-cores/duel-core"
GATE = CORE + "/target/release/gate_netleaf.exe"
CHAMP0 = CORE + "/src/attn_champion1_frozen.json"  # champion-1 (the Expert yardstick)
RUNS = [
    r"C:/Users/Forrest/duel_run/azloop",
    r"C:/Users/Forrest/duel_run/azloop2",
    r"C:/Users/Forrest/duel_run/azloop3",
    r"C:/Users/Forrest/duel_run/azloop_coherent",
    r"C:/Users/Forrest/duel_run/azpv",
]

GAMES = int(os.environ.get("RUNOFF_GAMES", 500))            # vs champion-1
HEUR_GAMES = int(os.environ.get("RUNOFF_HEUR_GAMES", 300))  # vs heuristic
SIMS = int(os.environ.get("RUNOFF_SIMS", 1500))
K = int(os.environ.get("RUNOFF_K", 3))       # top-K by each yardstick
SEED = int(os.environ.get("RUNOFF_SEED", 90000))  # DISJOINT from the loops' 70000 base
PRIOR_TEMP = float(os.environ.get("RUNOFF_PRIOR_TEMP", 1.0))  # serving temp for PV candidates

LINE = re.compile(r"iter (\d+): .*vs-champion1=([\d.]+) \| vs-heur=([\d.]+)")


def has_policy(path):
    try:
        with open(path) as f:
            return bool(json.load(f).get("pb"))
    except Exception:
        return False


def candidates():
    out = []
    for run in RUNS:
        log = run + "/log.txt"
        if not os.path.exists(log):
            continue
        for ln in open(log):
            m = LINE.search(ln)
            if not m:
                continue
            it, vc, vh = int(m.group(1)), float(m.group(2)), float(m.group(3))
            path = f"{run}/cand_iter{it}.json"
            if os.path.exists(path):
                out.append({"run": os.path.basename(run), "iter": it, "path": path, "vc": vc, "vh": vh})
    return out


def shortlist(cands):
    picks, seen = [], set()
    for c in sorted(cands, key=lambda c: -c["vc"])[:K] + sorted(cands, key=lambda c: -c["vh"])[:K]:
        if c["path"] not in seen:
            seen.add(c["path"])
            picks.append(c)
    return picks


def gate(cand_path, opp, games):  # opp = "heur" or an opponent net path
    cmd = [GATE, "--leaf", "attnfile", "--attn-file", cand_path,
           "--coherent", "--cpuct", "1.0", "--coherent-b", "--cpuct-b", "1.0",
           "--sims", str(SIMS), "--games", str(games), "--seed", str(SEED)]
    cmd += ["--leaf-b", "heur"] if opp == "heur" else ["--leaf-b", "attnfile2", "--attn-file-b", opp]
    if has_policy(cand_path):
        cmd += ["--net-policy-temp", str(PRIOR_TEMP)]
    if opp != "heur" and has_policy(opp):
        cmd += ["--net-policy-temp-b", str(PRIOR_TEMP)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    for ln in r.stdout.splitlines():
        if "NETLEAF GATE" in ln:
            try:
                return float(ln.split(":")[-1].split("[")[0].strip())
            except ValueError:
                pass
    return None


def main():
    cands = candidates()
    if not cands:
        sys.exit("no candidates found (are the azloop logs present?)")
    short = shortlist(cands)
    print(f"shortlist ({len(short)} of {len(cands)} candidates):", flush=True)
    for c in short:
        print(f"  {c['run']}#{c['iter']:<2}  per-iter vs-champion1={c['vc']:.3f}  vs-heur={c['vh']:.3f}"
              f"{'  [PV]' if has_policy(c['path']) else ''}", flush=True)
    if os.environ.get("RUNOFF_DRY"):
        print("(dry run — no gates)", flush=True)
        return

    print(f"\nBASELINE: champion-1 vs heur @ {HEUR_GAMES} games / {SIMS} sims (coherent-both, seed {SEED})...", flush=True)
    base_vh = gate(CHAMP0, "heur", HEUR_GAMES)
    print(f"  champion-1 vs heur = {base_vh}", flush=True)

    print(f"\nre-gating each vs champion-1 ({GAMES}g) + heur ({HEUR_GAMES}g) @ {SIMS} sims, SEQUENTIAL (gate bin is multi-threaded)...", flush=True)
    jobs = [(c, "champ1", CHAMP0, GAMES) for c in short] + [(c, "heur", "heur", HEUR_GAMES) for c in short]
    results = {}
    with cf.ThreadPoolExecutor(max_workers=1) as ex:  # sequential: each gate saturates all cores
        futs = {ex.submit(gate, c["path"], opp, g): (c, tag) for (c, tag, opp, g) in jobs}
        for fut in cf.as_completed(futs):
            c, tag = futs[fut]
            results[(c["path"], tag)] = fut.result()
            print(f"  {c['run']}#{c['iter']} vs {tag} = {results[(c['path'], tag)]}", flush=True)

    for c in short:
        c["hi_vc"] = results.get((c["path"], "champ1"))
        c["hi_vh"] = results.get((c["path"], "heur"))
    # RANK by high-N vs-champion1 (the STRENGTH signal — a fixed STRONG anchor). vs-heur is only a
    # COMPETENCE FLOOR: a candidate that regressed vs the weak heuristic (>~0.05 below baseline) smells
    # degenerate/overfit and sinks below the floor, even if it looks good vs champion-1. vs-heur is NOT
    # a climb metric — it saturates and is partly in-distribution (heur is a training league opponent).
    heur_floor = (base_vh - 0.05) if base_vh is not None else None
    def rankkey(c):
        vc = c["hi_vc"] if c["hi_vc"] is not None else -1.0
        vh = c["hi_vh"] if c["hi_vh"] is not None else 0.0
        passes = heur_floor is None or vh >= heur_floor
        return (1 if passes else 0, vc)
    short.sort(key=rankkey, reverse=True)
    print(f"\n=== RUNOFF RESULTS (ranked by high-N vs-champion1 = STRENGTH; vs-heur is a competence "
          f"floor at {heur_floor}, NOT a climb metric; baseline champion-1 vs heur = {base_vh}) ===", flush=True)
    print(f"{'cand':<18}{'per-iter vc/vh':<18}{'hiN vs-champ1':<15}{'hiN vs-heur':<12}", flush=True)
    for c in short:
        tag = f"{c['run']}#{c['iter']}"
        print(f"{tag:<18}{c['vc']:.3f}/{c['vh']:.3f}       {str(c['hi_vc']):<15}{str(c['hi_vh']):<12}", flush=True)
    best = short[0]
    print(f"\nWINNER:\n  {best['run']}#{best['iter']}  ->  {best['path']}", flush=True)
    print(f"SHIP-GATE: vs-champ1 {best['hi_vc']} (bar 0.55) | vs-heur {best['hi_vh']} vs baseline {base_vh} (bar baseline-0.02)", flush=True)


if __name__ == "__main__":
    main()
