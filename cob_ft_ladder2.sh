#!/usr/bin/env bash
# Round 2, on the COMPLETE 147-game corpus (100 replay-complete + 39 mon6 prefixes).
#
#   arm V2ALL    17,483 rows, every seat        (the shipped net trained on 14,601 -> +20%)
#   arm V2E1700  12,434 rows, mover >= 1700 ELO (85% of the SHIPPED net's row count, all vetted)
#
# WHY 1700 AND NOT 1800: round 1 showed the seat filter is a size trade, not a quality question.
# >=1800 cost 43% of the rows and gated BELOW unfiltered (0.5450 vs 0.5725) -- the contamination
# was real but removing it wasn't repaid. At the full corpus, >=1700 keeps 201/278 seats (72%)
# vs >=1800's 164 (59%), so purity now costs far less data. Median seat gap is still 378 ELO
# (stronger med 2028 / weaker med 1655), so there is still real contamination to remove.
#
# YARDSTICK = THE SHIPPED NET, not the old champion. The question is "does this beat what is
# SERVING", so both arms gate against pv_bga.ALL.json (live Expert, bin sha d773dea).
#
# WARM-START STAYS pv_warm936 (the PRE-BGA champion), deliberately. Warming from the shipped net
# would re-train it on the same 14,601 rows it already fit, which measures re-fitting rather than
# the new data; keeping the recipe identical to the ship also keeps the scaling curve
# (4,490 -> 8,641 -> 14,601 -> 17,483) an apples-to-apples series.
#
# Gates are RUNG-MAJOR so an interrupted run still leaves both arms comparable.
# Windows-style paths on purpose (Git Bash skips conversion for args containing ';' or ':').
set -euo pipefail

RUN="C:/Users/Forrest/coc_run_bga"
CORP="C:/Users/Forrest/CoB_corpus"
WARM="C:/Users/Forrest/coc_run_4animal/pv_warm936.json"      # warm-start seed (pre-BGA champion)
SHIP="$RUN/pv_bga.ALL.json"                                  # yardstick = the LIVE Expert
CORE="C:/Users/Forrest/forrestm_projects-cobmining/coc-core"
GATE="$CORE/target/release/gate_coc.exe"
THREADS=10
SEED=31337                                                   # fresh seed (round 1 used 4242/7777)

declare -A ROWS=( [V2ALL]="$CORP/bga_rows.v2_0.csv" [V2E1700]="$CORP/bga_rows.v2_1700.csv" )
ARMS=(V2ALL V2E1700)

echo "=== harness tripwire: SHIPPED net vs itself (MUST read 0.5000) ==="
"$GATE" "$SHIP:netval@30@1.0" "$SHIP:netval@30@1.0" 60 200 200 $SEED $THREADS 2>&1 | tail -1
echo

for arm in "${ARMS[@]}"; do
  bga="${ROWS[$arm]}"; mix="$RUN/anchor_mix.$arm.csv"; out="$RUN/pv_bga.$arm.json"
  echo "=== TRAIN $arm ($(wc -l < "$bga") bga rows) ==="
  python - "$RUN" "$bga" "$mix" <<'PY'
import glob, random, sys
run, bga, out = sys.argv[1], sys.argv[2], sys.argv[3]
n_bga = sum(1 for _ in open(bga))
rows = []
for f in glob.glob(run + "/anchor.t*.csv"):
    rows.extend(open(f).readlines())
random.Random(7).shuffle(rows)
keep = rows[:n_bga * 3]                 # anchor : bga = 3 : 1  -> bga = 25% of the mix
with open(out, "w") as w:
    for line in keep:
        p = line.rstrip("\n").split(",")
        # 0 gid | 1..936 feats | 937 label | 938 margin | 939 rootv | 940..953 aux | 954 policy
        w.write(",".join(p[:940] + [p[-1]]) + "\n")
got, want = len(open(out).readline().split(",")), len(open(bga).readline().split(","))
assert got == want, f"column mismatch: anchor {got} vs bga {want}"
print(f"      anchor {len(keep)} + bga {n_bga} = {n_bga/(len(keep)+n_bga)*100:.0f}% bga, {got} cols")
PY
  python "$CORE/tools/train_pv.py" --data "$mix;$bga" --out "$out" \
    --warm "$WARM" --in-dim 936 --aux-dim 0 \
    --epochs 6 --batch 256 --lr 5e-5 2>&1 | grep -Ev "UserWarning|vloss_s" | tail -3
  echo
done

for rung in "200:200" "1024:200"; do
  sims="${rung%%:*}"; pairs="${rung##*:}"
  echo "=================================================================="
  echo "=== RUNG @${sims} sims, n=$((pairs*2)), vs SHIPPED net, seed $SEED ==="
  echo "=================================================================="
  for arm in "${ARMS[@]}"; do
    printf '%-8s ' "$arm"
    "$GATE" "$RUN/pv_bga.$arm.json:netval@30@1.0" "$SHIP:netval@30@1.0" \
      "$pairs" "$sims" "$sims" "$SEED" "$THREADS" 2>&1 | tail -1
  done
  echo
done

echo "=================================================================="
echo "BASELINE = the LIVE Expert (pv_bga.ALL, d773dea). >0.5 means BETTER THAN WHAT SHIPS."
echo "round 1 for reference (vs the OLD champion): ALL 0.5300@200 -> 0.5725@1024"
echo "ship bar: >=0.52 at @1024 with the CI excluding 0.5, edge holding or growing with depth"
