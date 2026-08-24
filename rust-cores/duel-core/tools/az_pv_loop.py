#!/usr/bin/env python
"""Duel AZ POLICY+VALUE flywheel on the COHERENT search (the compounding loop the value-only
`az_loop.py` couldn't be — its plateau was the missing policy term).

Each iteration:
  1. HARVEST coherent self-play with the CURRENT champion (GUIDED by its own policy prior from the
     first PV champion on — the AZ compounding step), 8 shards: 5 self-play / 2 frozen-pool / 1 style.
     Raw root stats (q, visits) + rootval per decision (DUELAP02).
  2. TRAIN a candidate: co-train policy CE + value MSE (value-bootstrap 0.7*outcome + 0.3*rootval),
     warm from the champ, replay buffer over the last REPLAY iters.
  3. GATE serving-real (coherent both sides, cpuct 1.0), each side with its own policy prior:
     cand vs champ (promotion), vs champion-1 (the STRENGTH yardstick — a fixed strong anchor; trust
     the HIGH-N runoff value, not the noisy per-iter one), vs heur (a COMPETENCE FLOOR only — a DROP is
     a red flag; a rise is ~meaningless: it saturates + heur is an in-distribution league opponent).
     The real climb signal is high-N runoff vs-champion1 (+ later a near-peer past-champion panel) +
     user playtests — NOT vs-heur, and NOT noisy per-iter promotions.
  4. PROMOTE if cand beats champ; old champ joins the frozen pool. state.json persists {champ, pool,
     iter} per iteration — resumable after a shutdown (laptop reality).

Log format keeps the `az_loop.py` "iter N: ..." prefix so tools/runoff.py parses both loop
generations; PV-specific fields (top1/entropy/argmax tripwires) append after.

Run:  python az_pv_loop.py <n_iters> <seed_champ.json> [--resume]
Env:  AZ_RUN, AZ_GAMES(100/shard), AZ_SIMS(1200), AZ_CPUCT(0.3), AZ_GATE_GAMES(150), AZ_GATE_SIMS(800),
      AZ_REPLAY(3), AZ_EPOCHS(10), AZ_PRIOR_TEMP(1.0 — set from the Phase-1 winner), AZ_GUIDE(1;
      0 = F1 kill-switch: unguided harvest, policy still trained + served), AZ_PTARGET(qsoftmax),
      AZ_TTEMP(0.03), AZ_MINIMAX(0; 1 = actor-signed selection in harvest AND both gate sides —
      set it if the E1 minimax A/B won, so the loop trains/gates on the search we actually fly)
"""
import json, os, random, re, subprocess, sys, time

CORE = r"C:/Users/Forrest/forrestm_projects/rust-cores/duel-core"
RUN = os.environ.get("AZ_RUN", r"C:/Users/Forrest/duel_run/azpv")
HARVEST = CORE + "/target/release/harvest_attn_pv.exe"
GATE = CORE + "/target/release/gate_netleaf.exe"
TRAIN = CORE + "/tools/train_attn_pv.py"
CHAMP0 = CORE + "/src/attn_champion1_frozen.json"  # champion-1 = frozen external yardstick
PY = sys.executable

def _env(k, d, cast=int):
    return cast(os.environ.get(k, d))

SHARDS = 8
SELF_SHARDS = 5          # shards 0-4: guided self-play
POOL_SHARDS = 2          # shards 5-6: vs a frozen-pool member (league diversity; value-only rows)
                         # shard 7: style opponent (heurdev/heur alternating by iter parity)
GAMES_PER_SHARD = _env("AZ_GAMES", 100)
SIMS = _env("AZ_SIMS", 1200)
CPUCT = _env("AZ_CPUCT", 0.3, float)
TEMP_PLIES = 30
TEMP = 0.6
REPLAY = _env("AZ_REPLAY", 3)
EPOCHS = _env("AZ_EPOCHS", 10)
GATE_GAMES = _env("AZ_GATE_GAMES", 150)
GATE_SIMS = _env("AZ_GATE_SIMS", 800)
PRIOR_TEMP = _env("AZ_PRIOR_TEMP", 1.0, float)   # serving temp for the learned prior (Phase-1 T*)
GUIDE = _env("AZ_GUIDE", 1)                      # F1 kill-switch
PTARGET = os.environ.get("AZ_PTARGET", "qsoftmax")
TTEMP = _env("AZ_TTEMP", 0.03, float)
MINIMAX = _env("AZ_MINIMAX", 0)
# Opponent-model sharpness at OPPONENT nodes (Opts::opp_c). Serving ships 0.1 (e355d23, 2026-07-29):
# the ladder ran 3.0 = 0.4875 | 1.0 = old default | 0.3 = 0.5400 | 0.1 = 0.5970 | 0.03 = 0.5913 |
# 0.0 = 0.4412 COLLAPSE, and confirmed 0.6900 [0.643, 0.733] at pool=4 x5000 on the served net.
# It improves the TEACHER at this loop's own K=1 shape too (0.5970 @1500), so it makes strictly
# better targets AND keeps harvest/gates/serving on one search. Empty string = inherit --cpuct
# (what every harvest before 2026-07-30 did).
OPPC = os.environ.get("AZ_OPPC", "0.1").strip()
PROMOTE = 0.53

os.makedirs(RUN, exist_ok=True)
_LOG = open(RUN + "/log.txt", "a")
def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    _LOG.write(line + "\n"); _LOG.flush()

def has_policy(path):
    """Does this net JSON carry a policy head? (Cheap tail check — pw is the largest late key.)"""
    try:
        with open(path) as f:
            js = json.load(f)
        return bool(js.get("pb"))
    except Exception:
        return False

def harvest(idir, champ, pool, it):
    os.makedirs(idir, exist_ok=True)
    guided = GUIDE and has_policy(champ)
    procs = []
    for s in range(SHARDS):
        out = f"{idir}/shard_{s}.bin"
        # ITER-DEPENDENT SEED (the az_loop.py lesson): identical seeds re-generate identical games.
        cmd = [HARVEST, "--attn-file", champ,
               "--games", str(GAMES_PER_SHARD), "--sims", str(SIMS), "--cpuct", str(CPUCT),
               "--temp-plies", str(TEMP_PLIES), "--temp", str(TEMP), "--target-temp", str(TTEMP),
               "--seed", str(it * 10007 + s), "--out", out]
        if MINIMAX:
            cmd += ["--minimax"]
        if OPPC:
            cmd += ["--opp-c", OPPC]
        if guided:
            cmd += ["--net-policy-temp", str(PRIOR_TEMP)]
        if SELF_SHARDS <= s < SELF_SHARDS + POOL_SHARDS:
            opp = random.choice(pool)
            if opp == "heur":
                cmd += ["--leaf-b", "heur"]
            else:
                cmd += ["--leaf-b", "attnfile2", "--attn-file-b", opp]
        elif s == SHARDS - 1:
            cmd += ["--leaf-b", "heurdev" if it % 2 == 0 else "heur"]
        lf = open(f"{idir}/log_{s}.txt", "w")
        procs.append(subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=CORE))
    for p in procs:
        p.wait()
    # Tripwires (F1): pull the sanity readout from shard 0's log.
    ratio, argmax = None, None
    try:
        with open(f"{idir}/log_0.txt") as f:
            txt = f.read()
        m = re.search(r"ratio (\d+\.\d+)", txt)
        ratio = float(m.group(1)) if m else None
        m = re.search(r"argmax==greedy pick : (\d+\.\d+)", txt)
        argmax = float(m.group(1)) if m else None
    except Exception:
        pass
    rows = 0
    for s in range(SHARDS):
        meta = f"{idir}/shard_{s}.bin.meta.json"
        if os.path.exists(meta):
            with open(meta) as f:
                rows += json.load(f).get("rows", 0)
    return rows, guided, ratio, argmax

def train(data, out, init):
    cmd = [PY, TRAIN, "--data", data, "--out", out, "--init", init,
           "--no-freeze-trunk", "--rootval-blend", "0.3",
           "--policy-target", PTARGET, "--target-temp", str(TTEMP),
           "--lr", "5e-4", "--epochs", str(EPOCHS)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=CORE)
    top1 = None
    m = re.search(r"saved .*val_top1 (\d+\.\d+)", r.stdout or "")  # the trainer's final summary line
    if m:
        top1 = float(m.group(1))
    if not os.path.exists(out):
        log(f"  TRAIN FAILED: {(r.stderr or '')[-500:]}")
    return top1

def gate(a, b, heur=False, npt_a=None, npt_b=None):
    """Serving-real gate: coherent both sides at cpuct 1.0; each side carries its prior if given."""
    cmd = [GATE, "--leaf", "attnfile", "--attn-file", a,
           "--coherent", "--cpuct", "1.0", "--coherent-b", "--cpuct-b", "1.0",
           "--sims", str(GATE_SIMS), "--games", str(GATE_GAMES)]
    if MINIMAX:
        cmd += ["--minimax", "--minimax-b"]
    if OPPC:
        # BOTH sides — the gate asks "is this NET better", so the search must be identical across
        # it. Putting opp_c on one side only would measure the (already-shipped) search knob again.
        # heur side B has no opp_c knob of its own, so skip it there.
        cmd += ["--opp-c", OPPC] + ([] if heur else ["--opp-c-b", OPPC])
    cmd += (["--leaf-b", "heur"] if heur else ["--leaf-b", "attnfile2", "--attn-file-b", b])
    if npt_a is not None:
        cmd += ["--net-policy-temp", str(npt_a)]
    if npt_b is not None:
        cmd += ["--net-policy-temp-b", str(npt_b)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=CORE)
    for line in r.stdout.splitlines():
        if "NETLEAF GATE" in line:
            try:
                return float(line.split(":")[-1].split("[")[0].strip())
            except ValueError:
                pass
    return None

def save_state(it, champ, pool):
    with open(RUN + "/state.json", "w") as f:
        json.dump({"iter": it, "champ": champ, "pool": pool}, f)

def main():
    n_iters = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    champ = sys.argv[2] if len(sys.argv) > 2 else CHAMP0
    resume = "--resume" in sys.argv
    pool = [CHAMP0, "heur"]
    start_it = 1
    if resume and os.path.exists(RUN + "/state.json"):
        with open(RUN + "/state.json") as f:
            st = json.load(f)
        champ, pool, start_it = st["champ"], st["pool"], st["iter"] + 1
        log(f"=== RESUME from iter {st['iter']} champ={os.path.basename(champ)} pool={len(pool)} ===")
    log(f"=== AZ PV LOOP START: iters {start_it}..{n_iters}, champ={os.path.basename(champ)}, "
        f"guide={GUIDE} prior_temp={PRIOR_TEMP} ptarget={PTARGET}@{TTEMP} cpuct={CPUCT} ===")
    for it in range(start_it, n_iters + 1):
        t0 = time.time()
        idir = f"{RUN}/iter{it}"
        rows, guided, ratio, argmax = harvest(idir, champ, pool, it)
        # Replay buffer: the last REPLAY iters' shards.
        recent = [f"{RUN}/iter{j}/shard_*.bin" for j in range(max(1, it - REPLAY + 1), it + 1)]
        data = ",".join(recent)
        cand = f"{RUN}/cand_iter{it}.json"
        top1 = train(data, cand, champ)
        if not os.path.exists(cand):
            log(f"iter {it}: no candidate, skipping"); continue
        npt_champ = PRIOR_TEMP if has_policy(champ) else None
        vs_champ = gate(cand, champ, npt_a=PRIOR_TEMP, npt_b=npt_champ)
        vs_c0 = vs_champ if champ == CHAMP0 else gate(cand, CHAMP0, npt_a=PRIOR_TEMP)
        vs_h = gate(cand, None, heur=True, npt_a=PRIOR_TEMP)
        mins = (time.time() - t0) / 60
        log(f"iter {it}: pos={rows} | cand-vs-champ={vs_champ} | vs-champion1={vs_c0} | vs-heur={vs_h} | {mins:.0f}m"
            f" | guided={int(guided)} top1={top1} ratio={ratio} argmax={argmax}")
        # HARD STOP on a dead gate. Three times this campaign a None-returning gate has been
        # absorbed silently and let a run continue producing nothing: the 2026-07-27 taskkill (which
        # then wrote "no knob cleared 0.53" as a verdict from an empty set), the hp_sweep results-dict
        # bug, and 2026-07-30 iters 1-4 here — five hours of harvest with EVERY gate panicking on
        # `unknown arg: --opp-c`, because this loop points at target/release/gate_netleaf.exe while
        # the freshly-built gate lived in target-pool/release. A gate that cannot run is a broken
        # harness, not a bad candidate, and the two must never look alike in a log.
        if vs_champ is None:
            log(f"iter {it}: !! GATE RETURNED None — the harness is broken, not the candidate. "
                f"Check that {GATE} is current (a stale binary panics on newer flags). ABORTING; "
                f"harvested shards are kept and --resume will reuse them.")
            save_state(it, champ, pool)
            raise SystemExit(2)
        # F1 tripwires: near-uniform target or search-pick divergence.
        if ratio is not None and ratio >= 0.85:
            log(f"iter {it}: !! TRIPWIRE entropy ratio {ratio} >= 0.85 (near-uniform target)")
        if argmax is not None and argmax < 0.70:
            log(f"iter {it}: !! TRIPWIRE argmax==greedy {argmax} < 0.70 (guided search diverging)")
        if vs_champ is not None and vs_champ > PROMOTE:
            pool.append(champ)
            champ = cand
            log(f"iter {it}: *** PROMOTED *** (beat champ {vs_champ:.3f}); pool={len(pool)}")
        save_state(it, champ, pool)
    final = gate(champ, CHAMP0, npt_a=PRIOR_TEMP if has_policy(champ) else None) if champ != CHAMP0 else 0.5
    log(f"=== AZ PV LOOP DONE. final champ vs champion-1 = {final} ===")

if __name__ == "__main__":
    main()
