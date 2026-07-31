#!/usr/bin/env bash
# Two-arm anchored fine-tune ladder on the GROWN BGA corpus, to separate the two things that
# changed since the July null result:
#
#   arm ALL   14,601 rows, every seat        -> isolates DATA VOLUME (1.7x the Jul-20 run)
#   arm E1800  8,394 rows, mover >= 1800 ELO -> isolates PURITY (size-matched to Jul-20's 8,641,
#                                               but with the ~46% weak-seat rows removed)
#
# Why purity is the live hypothesis: cob_elo.py measured a MEDIAN 396-ELO gap between the two
# seats (stronger med 2040, weaker med 1635). Harvesting both seats trained the net to imitate a
# ~400-ELO-weaker player on roughly half its rows.
#
# The anchor is subsampled to 3x EACH arm's own row count, so BGA stays ~25% of both mixes -- we
# are testing the BGA rows' quality, not the mix ratio (the documented P4b anchor-cliff: 100%
# new-distribution rows collapse a converged net, 0.408).
#
# PATHS ARE WINDOWS-STYLE ON PURPOSE. Git Bash skips its /c/... -> C:/... conversion for any arg
# containing ';' or ':', which is exactly the shape of `--data a.csv;b.csv` and `net:netval@30@1.0`
# -- a /c/... path would reach python/the exe unconverted and glob to nothing.
set -euo pipefail

RUN="C:/Users/Forrest/coc_run_bga"
CORP="C:/Users/Forrest/CoB_corpus"
CH="C:/Users/Forrest/coc_run_4animal/pv_warm936.json"
CORE="C:/Users/Forrest/forrestm_projects-cobmining/coc-core"
GATE="$CORE/target/release/gate_coc.exe"
PAIRS=200          # n = 400 games, CRN-paired
SIMS=200           # serving config; both nets are the same arch/size so equal-sims == equal-time
SEED=4242
THREADS=10

echo "=== harness tripwire: champion vs itself (MUST read 0.5000) ==="
"$GATE" "$CH:netval@30@1.0" "$CH:netval@30@1.0" 60 $SIMS $SIMS $SEED $THREADS 2>&1 | tail -2
echo

run_arm () {
  local name="$1" bga="$2"
  local mix="$RUN/anchor_mix.$name.csv"
  local out="$RUN/pv_bga.$name.json"

  echo "=================================================================="
  echo "=== ARM $name  ($(wc -l < "$bga") bga rows) ==="
  echo "=================================================================="

  echo "[1/3] strip aux (955 -> 941) + subsample anchor so BGA is ~25% of the mix"
  python - "$RUN" "$bga" "$mix" <<'PY'
import glob, random, sys
run, bga, out = sys.argv[1], sys.argv[2], sys.argv[3]
n_bga = sum(1 for _ in open(bga))
target = n_bga * 3                       # anchor : bga = 3 : 1  -> bga = 25%
rows = []
for f in glob.glob(run + "/anchor.t*.csv"):
    rows.extend(open(f).readlines())
random.Random(7).shuffle(rows)
keep = rows[:target]
with open(out, "w") as w:
    for line in keep:
        p = line.rstrip("\n").split(",")
        # 0 gid | 1..936 feats | 937 label | 938 margin | 939 rootv | 940..953 aux | 954 policy
        w.write(",".join(p[:940] + [p[-1]]) + "\n")
print(f"      anchor pool {len(rows)} -> kept {len(keep)} "
      f"(bga {n_bga}, mix {n_bga/(len(keep)+n_bga)*100:.0f}% bga)")
got, want = len(open(out).readline().split(",")), len(open(bga).readline().split(","))
assert got == want, f"column mismatch: anchor {got} vs bga {want}"
print(f"      stripped cols: {got} == bga {want}")
PY

  echo "[2/3] fine-tune (warm from champion, anchor + bga)"
  python "$CORE/tools/train_pv.py" \
    --data "$mix;$bga" \
    --out "$out" \
    --warm "$CH" --in-dim 936 --aux-dim 0 \
    --epochs 6 --batch 256 --lr 5e-5 2>&1 | grep -Ev "UserWarning|vloss_s" | tail -8

  echo "[3/3] GATE vs champion (netval@30@1.0, $SIMS sims, n=$((PAIRS*2)))"
  "$GATE" "$out:netval@30@1.0" "$CH:netval@30@1.0" \
    $PAIRS $SIMS $SIMS $SEED $THREADS 2>&1 | tail -2
  echo
}

run_arm ALL   "$CORP/bga_rows.all.csv"
run_arm E1800 "$CORP/bga_rows.elo1800.csv"

echo "=================================================================="
echo "reference: Jul-15 anchored (4,490 rows, unfiltered) = 0.4875 +-0.063"
echo "           Jul-20        (8,641 rows, unfiltered) = 0.52, CI included 0.5"
echo "ship bar: >=0.52 with the CI excluding 0.5"
