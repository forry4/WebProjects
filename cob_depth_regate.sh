#!/usr/bin/env bash
# Depth re-gate: does the BGA fine-tune's @200 edge SURVIVE toward serving depth?
#
# WHY THIS IS THE DECIDING NUMBER, not the @200 screen. CoC's search saturates ~4k sims
# (coc_run_simgate/ladder_log.txt: 1024v512 0.5417, 2048v1024 0.5833, 4096v2048 0.5667,
# 8192v4096 0.5000 = knee) and Expert SERVES at ~20k. A gate at 200 sits ~20x below the knee,
# where the LEAF net dominates the result; deeper search washes leaf differences out. So a
# fine-tuned-leaf edge measured @200 is an UPPER BOUND on serving behaviour, never an estimate.
# The repo has this both ways on record: r2 shipped on 0.5250 @200 -> 0.5500 @512 ("grows with
# depth"), while a steps=30 config read 0.583 @200 and softened to 0.54 @1024 ("a low-sims win").
#
# 4096 is the meaningful top rung -- it is AT the knee, so it predicts ~20k serving. Gating at
# 20k itself buys nothing past the knee except wall-clock.
#
# RUNG-MAJOR ON PURPOSE (all arms at one depth, then all arms at the next), not arm-major: the
# run is ~3.4h and may be read before it finishes, so it must DEGRADE GRACEFULLY -- an interrupted
# arm-major run leaves one arm fully measured and the other untouched, which answers nothing about
# whether purity or volume is the lever. Rung-major always leaves both arms comparable.
#
# Both nets are the same arch and size, so equal-sims == equal-time at every rung.
# Windows-style paths on purpose (Git Bash skips conversion for args containing ':').
set -euo pipefail

CH="C:/Users/Forrest/coc_run_4animal/pv_warm936.json"
CORE="C:/Users/Forrest/forrestm_projects-cobmining/coc-core"
GATE="$CORE/target/release/gate_coc.exe"
THREADS=10
SEED=7777          # FRESH seed -- the @200 screen used 4242. A one-seed base has burned this
                   # repo before ("VARY THE SEED"); a depth trend read on the screen's own seed
                   # could be the same lucky base seen at more depth. The @200 rung below is
                   # therefore NOT redundant: it re-reads the headline number on new dice.
ARMS=("$@")

# sims:pairs -- pairs fall as sims rise so each rung costs roughly equal wall-clock
for rung in "200:200" "1024:200" "4096:120"; do
  sims="${rung%%:*}"; pairs="${rung##*:}"
  echo "=================================================================="
  echo "=== RUNG @${sims} sims, n=$((pairs*2)), seed $SEED ==="
  echo "=================================================================="
  for arm in "${ARMS[@]}"; do
    net="C:/Users/Forrest/coc_run_bga/pv_bga.$arm.json"
    [ -f "$net" ] || { echo "!! missing $net -- skipping $arm"; continue; }
    printf '%-6s ' "$arm"
    "$GATE" "$net:netval@30@1.0" "$CH:netval@30@1.0" \
      "$pairs" "$sims" "$sims" "$SEED" "$THREADS" 2>&1 | tail -1
  done
  echo
done

echo "=================================================================="
echo "READ: edge HOLDS or GROWS 200 -> 1024 -> 4096  => transfers to ~20k serving, shippable."
echo "      edge DECAYS toward 0.5                   => a low-sims leaf artifact, do NOT ship."
echo "ship bar: >=0.52 at 4096 with the CI excluding 0.5"
