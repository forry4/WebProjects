#!/usr/bin/env python
"""How many rows does this net actually need? — the data-vs-capacity diagnostic.

Prompted by "at how many rows does it saturate? is 500k / 1M worth it?" (2026-07-28). The answer
decides which lever is next: if the curve is still climbing, harvest more (raise games/iter, or a
dedicated big run); if it has flattened, the net is CAPACITY-limited and more data is wasted —
the lever becomes a bigger net / better architecture (Phase-3 rung 4).

METHOD, and why the obvious version is invalid: `train_attn_pv` normally carves its val split out
of --data, so two runs on different data sizes are scored on DIFFERENT held-out games and their
val_top1 / val_auc are not comparable. (Exactly the trap that made "visits beats qsoftmax" look
true when A2/G2 were measuring different things.) So every point here trains with `--val-data`
pointing at ONE fixed holdout shard.

Points come from the PIVOTAL harvest only — one distribution (unguided, runoff-winner teacher).
A final MIXED point appends flywheel data (guided, netB2 teacher) and is labelled separately: it
answers a different question (does more OFF-distribution data help?) and must not be read as part
of the clean curve.

Offline metrics are a SCREEN, not a verdict — confirm the endpoints with a play gate before
concluding anything about strength.

  python data_scaling.py
"""
import glob, json, os, re, subprocess, sys

CORE = r"C:/Users/Forrest/forrestm_projects/rust-cores/duel-core"
PY = r"C:/Users/Forrest/forrestm_projects/.venv/Scripts/python"
PIV = r"C:/Users/Forrest/duel_run/phase1/pv"
AZPV = r"C:/Users/Forrest/duel_run/azpv"
SEED_NET = r"C:/Users/Forrest/duel_run/phase1/netB2.json"
RUN = r"C:/Users/Forrest/duel_run/data_scaling"
EPOCHS = int(os.environ.get("DS_EPOCHS", 15))
os.makedirs(RUN, exist_ok=True)

HOLDOUT = f"{PIV}/shard_7.bin"          # fixed for every point — never in any train set
TRAIN_SHARDS = [f"{PIV}/shard_{i}.bin" for i in range(7)]


def note(m):
    print(m, flush=True)
    with open(RUN + "/summary.txt", "a") as f:
        f.write(m + "\n")


def rows_of(shard):
    try:
        return json.load(open(shard + ".meta.json"))["rows"]
    except Exception:
        return 0


def train(data_globs, tag):
    out = f"{RUN}/net_{tag}.json"
    cmd = [PY, CORE + "/tools/train_attn_pv.py", "--data", ",".join(data_globs),
           "--val-data", HOLDOUT, "--init", SEED_NET, "--out", out,
           "--no-freeze-trunk", "--rootval-blend", "0.3",
           "--policy-target", "visits", "--lr", "5e-4", "--epochs", str(EPOCHS)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=CORE)
    txt = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"saved .*val_top1 ([\d.]+), val_vauc ([\d.]+)", txt)
    if not m:  # fall back to the last per-epoch line
        eps = re.findall(r"val_top1 ([\d.]+).*?val_vauc ([\d.]+)", txt)
        m2 = eps[-1] if eps else None
        if not m2:
            note(f"  {tag}: TRAIN FAILED — {txt.strip()[-300:]}")
            return None, None, out
        return float(m2[0]), float(m2[1]), out
    return float(m.group(1)), float(m.group(2)), out


def main():
    note("=== DATA SCALING (fixed holdout = pivotal shard_7; all points comparable) ===")
    note(f"holdout rows: {rows_of(HOLDOUT):,}   epochs {EPOCHS}   seed net = netB2")

    # Clean curve: pivotal only, one distribution.
    plan = [1, 2, 4, 7]
    results = []
    for k in plan:
        shards = TRAIN_SHARDS[:k]
        n = sum(rows_of(s) for s in shards)
        t1, auc, _ = train(shards, f"piv{k}")
        results.append((n, t1, auc))
        note(f"  {n:>7,} rows ({k} pivotal shard{'s' if k>1 else ''}): val_top1 {t1}  val_vauc {auc}")

    # Mixed point: + flywheel data (DIFFERENT distribution — guided harvest). Labelled apart.
    fly = sorted(glob.glob(f"{AZPV}/iter*/shard_*.bin"))
    if fly:
        n_fly = sum(rows_of(s) for s in fly)
        t1, auc, _ = train(TRAIN_SHARDS + [f"{AZPV}/iter*/shard_*.bin"], "mixed")
        base = sum(rows_of(s) for s in TRAIN_SHARDS)
        note(f"  {base + n_fly:>7,} rows (+{n_fly:,} FLYWHEEL, mixed distribution): "
             f"val_top1 {t1}  val_vauc {auc}   [NOT part of the clean curve]")

    note("")
    note("READ: if val_vauc is still rising at 285k -> data-limited, harvesting more pays.")
    note("      if it flattened by ~160k -> capacity-limited; more rows are wasted and the")
    note("      lever is a bigger net (Phase-3 rung 4). CONFIRM endpoints with a play gate")
    note("      before acting — offline metrics have misled twice this campaign.")
    note("=== DATA SCALING COMPLETE ===")


if __name__ == "__main__":
    main()
