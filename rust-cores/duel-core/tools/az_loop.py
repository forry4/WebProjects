#!/usr/bin/env python
"""Duel AZ co-evolution loop (the training investment champion-1 never got).

Each iteration:
  1. HARVEST self-play with the CURRENT champion + exploration (temp deep into mid-game),
     a couple of shards played vs a random FROZEN-POOL member (past champs / heuristic) for
     anti-blind-spot diversity.
  2. TRAIN a candidate: warm-start from the current champ, `--save-final` (the net must MOVE
     toward the fresh data, not sit at the warm-start optimum), fixed epochs.
  3. GATE the candidate vs the current champ (promotion test) + two frozen YARDSTICKS
     (champion-1 original, and the heuristic) so real strength is judged externally, not by an
     internal metric that can rise while play stays flat.
  4. PROMOTE if the candidate beats the champ; the old champ joins the frozen pool (co-evolution
     — the opponent improves with the net, so there is no fixed ceiling).

Logs to azloop/log.txt; checkpoints every promoted champ. Restartable: point --resume at a champ.
Run:  python az_loop.py <n_iters> [resume_champ.json]
"""
import os, sys, glob, random, subprocess, time

CORE = r"C:/Users/Forrest/forrestm_projects/rust-cores/duel-core"
RUN = os.environ.get("AZ_RUN", r"C:/Users/Forrest/duel_run/azloop")  # override for a scratch smoke
HARVEST = CORE + "/target/release/harvest_attn.exe"
GATE = CORE + "/target/release/gate_netleaf.exe"
TRAIN = CORE + "/tools/train_attn.py"
CHAMP0 = CORE + "/src/attn_expert_net.json"  # champion-1 = frozen external yardstick
PY = sys.executable

def _env(k, d):
    return int(os.environ.get(k, d))

SHARDS = _env("AZ_SHARDS", 8)
GAMES_PER_SHARD = _env("AZ_GAMES", 150)  # 1200 games/iter; the REPLAY buffer accumulates across iters
POOL_SHARDS = 2            # of the 8, this many play vs a frozen-pool member (diversity)
SIMS = _env("AZ_SIMS", 1500)  # HARVEST sims = TEACHER strength = the loop's ceiling (net saturates ~4k)
TEMP_PLIES = 30
TEMP = 0.6
NCOL = 517                 # 30-feat CSV width (2 + 15*30 + 15 + 47 + 3: hval, rootval, outcome)
REPLAY = _env("AZ_REPLAY", 3)  # train on the last REPLAY iters' data (replay buffer — curbs single-iter overfit)
EPOCHS = _env("AZ_EPOCHS", 10)  # best-val checkpointed (NOT --save-final, which overfit iter 1)
# Gating dominates iteration cost (3 gates x N games x 2 nets each). At 2000 sims x 300 games it
# was ~4x the harvest. 1000 sims x 200 games is a fine RELATIVE promotion signal (both nets equal
# sims; the champion-1 yardstick catches drift) and ~3.6x cheaper -> ~2.3x faster iterations.
GATE_GAMES = _env("AZ_GATE_GAMES", 200)
GATE_SIMS = _env("AZ_GATE_SIMS", 1000)
PROMOTE = 0.53             # promote if cand beats champ by this (yardstick vs CHAMP0 catches real climb vs drift)

os.makedirs(RUN, exist_ok=True)
_LOG = open(RUN + "/log.txt", "a")
def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    _LOG.write(line + "\n"); _LOG.flush()

def harvest(idir, champ, pool, it):
    os.makedirs(idir, exist_ok=True)
    procs = []
    for s in range(SHARDS):
        out = f"{idir}/shard_{s}.csv"
        # ITER-DEPENDENT SEED (critical): with a plain `s` seed, an unchanged champ regenerates the
        # IDENTICAL games every iteration -> the replay buffer becomes 3x duplicates + train/val
        # leakage (dup game, different gid) -> overfit + degradation. Vary the seed per iter for
        # genuinely fresh self-play each round.
        cmd = [HARVEST, "--leaf", "attnfile", "--attn-file", champ,
               "--games", str(GAMES_PER_SHARD), "--sims", str(SIMS),
               "--temp-plies", str(TEMP_PLIES), "--temp", str(TEMP),
               "--seed", str(it * 10007 + s), "--out", out]
        if s >= SHARDS - POOL_SHARDS:
            opp = random.choice(pool)
            if opp == "heur":
                cmd += ["--leaf-b", "heur"]
            else:
                cmd += ["--leaf-b", "attnfile2", "--attn-file-b", opp]
        lf = open(f"{idir}/log_{s}.txt", "w")
        procs.append(subprocess.Popen(cmd, stdout=lf, stderr=lf, cwd=CORE))
    for p in procs:
        p.wait()
    allc = f"{idir}/all.csv"
    first, n = True, 0
    with open(allc, "w") as o:
        for s in range(SHARDS):
            f = f"{idir}/shard_{s}.csv"
            if not os.path.exists(f):
                continue
            with open(f) as fh:
                hdr = fh.readline()
                if first:
                    o.write(hdr); first = False
                for line in fh:
                    if line.count(",") + 1 != NCOL:
                        continue
                    gid, rest = line.split(",", 1)
                    try:
                        g = int(gid)
                    except ValueError:
                        continue
                    o.write(f"{g + s * 100000},{rest}"); n += 1
    return allc, n

def train(data, out, init):
    # VALUE-BOOTSTRAP target (0.7*outcome + 0.3*search_root_value) + best-val checkpoint. Warm-started
    # from the champ; the CHANGED target + fresh replay data pull it OFF the warm-start optimum, so
    # best-val no longer just returns the checkpoint (the failure mode --save-final was papering over).
    cmd = [PY, TRAIN, "--data", data, "--out", out, "--init", init,
           "--lr", "5e-4", "--epochs", str(EPOCHS), "--rootval-blend", "0.3"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=CORE)
    if not os.path.exists(out):
        log(f"  TRAIN FAILED: {r.stderr[-500:]}")
    return out

def gate(a, b, heur=False):
    cmd = [GATE, "--leaf", "attnfile", "--attn-file", a]
    cmd += (["--leaf-b", "heur"] if heur else ["--leaf-b", "attnfile2", "--attn-file-b", b])
    cmd += ["--sims", str(GATE_SIMS), "--games", str(GATE_GAMES)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=CORE)
    for line in r.stdout.splitlines():
        if "NETLEAF GATE" in line:
            try:
                return float(line.split(":")[-1].split("[")[0].strip())
            except ValueError:
                pass
    return None

def main():
    n_iters = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    champ = sys.argv[2] if len(sys.argv) > 2 else CHAMP0
    pool = [CHAMP0, "heur"]
    log(f"=== AZ LOOP START: {n_iters} iters, champ={os.path.basename(champ)} ===")
    for it in range(1, n_iters + 1):
        t0 = time.time()
        idir = f"{RUN}/iter{it}"
        _, n = harvest(idir, champ, pool, it)
        # Replay buffer: train on the last REPLAY iters' merged self-play (not just this iter's) to
        # curb the single-iter overfit that sank iter 1, and smooth the co-evolution.
        recent = [f"{RUN}/iter{j}/all.csv" for j in range(max(1, it - REPLAY + 1), it + 1)]
        recent = [p for p in recent if os.path.exists(p)]
        data = ",".join(recent)
        cand = f"{RUN}/cand_iter{it}.json"
        train(data, cand, champ)
        if not os.path.exists(cand):
            log(f"iter {it}: no candidate, skipping"); continue
        vs_champ = gate(cand, champ)
        vs_c0 = vs_champ if champ == CHAMP0 else gate(cand, CHAMP0)  # identical while unpromoted -> skip the redundant gate (~1/3 of gate time)
        vs_h = gate(cand, None, heur=True)
        mins = (time.time() - t0) / 60
        log(f"iter {it}: pos={n} | cand-vs-champ={vs_champ} | vs-champion1={vs_c0} | vs-heur={vs_h} | {mins:.0f}m")
        if vs_champ is not None and vs_champ > PROMOTE:
            pool.append(champ)
            champ = cand
            log(f"iter {it}: *** PROMOTED *** (beat champ {vs_champ:.3f}); pool={len(pool)}")
    final = gate(champ, CHAMP0) if champ != CHAMP0 else 0.5
    log(f"=== AZ LOOP DONE. final champ vs champion-1 = {final} ===")

if __name__ == "__main__":
    main()
