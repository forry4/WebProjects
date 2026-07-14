#!/bin/bash
# BASIN-ESCAPE test: train a net FRESH (cold init, NOT warm from r2) on rung-3's
# 4000-sim corpus + aux, then gate vs the champion. r2 is a fixed point of the
# warm-continuation recipe (every continuation lands at parity because a
# converged net resists a fresh gradient). A cold student learning from
# super-champion 4000-sim targets can exceed the teacher where a warm one can't.
# Same net size first (isolates warm-vs-fresh); bigger only if this shows life.
# Cheap (~1h), reuses corpus on disk, rung-3 stays fully resumable.
set -o pipefail
RUN=/c/Users/Forrest/coc_run_hs2
RUNW=$(cygpath -m "$RUN")
CR=/c/Users/Forrest/forrestm_projects/coc-core/target/release
TOOLS=/c/Users/Forrest/forrestm_projects/coc-core/tools
CHAMP=C:/Users/Forrest/coc_run_r2/pv_ship_r2.json
ANCHOR="C:/Users/Forrest/coc_run_aux/aux_boot.t[0-1].csv"
EPOCHS=${EPOCHS:-8}
TRUNK=${TRUNK:-}          # empty = default 512,256 (champion size); set e.g. 768,384 for bigger
OUT=${OUT:-$RUNW/hs2_fresh.json}
LOG=$RUN/fresh_log.txt
reap() {
    powershell -NoProfile -Command \
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'gpu_server' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        >/dev/null 2>&1 || true
}
trap reap EXIT

# whatever high-sim corpus survives on disk + the champion anchor
data="$RUNW/sp_*.t*.csv;$RUNW/lg_*.t*.csv;$ANCHOR"
trunk_arg=""; [ -n "$TRUNK" ] && trunk_arg="--trunk $TRUNK"
echo "=== fresh cold-init train (epochs=$EPOCHS trunk=${TRUNK:-default} aux 0.3) ===" | tee -a "$LOG"
echo "data: $data" | tee -a "$LOG"
CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$data" --out "$OUT" \
    --epochs "$EPOCHS" --lr 1e-3 --aux-dim 14 --aux-weight 0.3 $trunk_arg 2>&1 | tee -a "$LOG" \
    || { echo "FATAL: fresh train failed" | tee -a "$LOG"; exit 1; }
"$CR/net_export_check.exe" "$OUT" | tee -a "$LOG"

echo "=== gate fresh vs champion (200v200, n=240) ===" | tee -a "$LOG"
reap
COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$OUT" --port 9941 >"$RUN/gpu_fresh_a.log" 2>&1 &
COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$CHAMP" --port 9942 >"$RUN/gpu_fresh_b.log" 2>&1 &
for _ in $(seq 1 30); do grep -q ready "$RUN/gpu_fresh_a.log" 2>/dev/null && grep -q ready "$RUN/gpu_fresh_b.log" 2>/dev/null && break; sleep 2; done
grep -q "dev=cuda" "$RUN/gpu_fresh_a.log" || { echo "FATAL: fresh sidecar A dev=cpu" | tee -a "$LOG"; exit 1; }
grep -q "dev=cuda" "$RUN/gpu_fresh_b.log" || { echo "FATAL: champ sidecar B dev=cpu" | tee -a "$LOG"; exit 1; }
g=$(COC_GPU_ADDR_A=127.0.0.1:9941 COC_GPU_ADDR_B=127.0.0.1:9942 \
    "$CR/gate_coc.exe" "$OUT:netvalgpu" "$CHAMP:netvalgpu" 120 200 200 51000 4 24 2>"$RUN/gates_err_fresh.log" | tail -1)
echo "FRESH-vs-CHAMPION: $g" | tee -a "$LOG"
reap
echo "=== fresh bootstrap done ===" | tee -a "$LOG"
