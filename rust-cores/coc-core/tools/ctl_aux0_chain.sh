#!/bin/bash
# Crater forensics (attn2 iter-0): control retrain of the EXACT iter-0 corpus
# with --aux-weight 0 (aux-dim stays 14 — parse only; zero weight = zero aux
# gradient, the documented control convention). Gate vs the seed isolates the
# aux gradient as cause of the 0.2914 crater.
set -o pipefail
RUN=/c/Users/Forrest/coc_run_attn2
RUNW=$(cygpath -m "$RUN")
CR=/c/Users/Forrest/forrestm_projects/coc-core/target/release
TOOLS=/c/Users/Forrest/forrestm_projects/coc-core/tools
LOG=$RUN/ctl_aux0_log.txt
reap() {
    powershell -NoProfile -Command \
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'gpu_server' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        >/dev/null 2>&1 || true
}
trap reap EXIT

data="$RUNW/sp_0.t*.csv;$RUNW/lg_0.t*.csv;$RUNW/attn2_boot.t[0-1].csv"
echo "=== control: aux-weight 0 retrain on the iter-0 corpus ===" | tee -a "$LOG"
if [ ! -f "$RUN/attn2_ctl_aux0.json" ]; then
    CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_attn.py" --data "$data" --out "$RUNW/attn2_ctl_aux0.json" \
        --warm "$RUNW/attn2_best.json" --lr 5e-4 --epochs 2 --aux-dim 14 --aux-weight 0 2>&1 | tee -a "$LOG" \
        || { echo "FATAL: control train failed" | tee -a "$LOG"; exit 1; }
fi
"$CR/attn_export_check.exe" "$RUNW/attn2_ctl_aux0.json" | tee -a "$LOG"

reap
COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$RUNW/attn2_ctl_aux0.json" --port 9915 >"$RUN/gpu_ctl_a.log" 2>&1 &
COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$RUNW/attn2_best.json" --port 9916 >"$RUN/gpu_ctl_b.log" 2>&1 &
for _ in $(seq 1 30); do
    grep -q ready "$RUN/gpu_ctl_a.log" 2>/dev/null && grep -q ready "$RUN/gpu_ctl_b.log" 2>/dev/null && break
    sleep 2
done
grep -q "dev=cuda" "$RUN/gpu_ctl_a.log" || { echo "FATAL: ctl sidecar A dev=cpu" | tee -a "$LOG"; exit 1; }
grep -q "dev=cuda" "$RUN/gpu_ctl_b.log" || { echo "FATAL: ctl sidecar B dev=cpu" | tee -a "$LOG"; exit 1; }
g=$(COC_GPU_ADDR_A=127.0.0.1:9915 COC_GPU_ADDR_B=127.0.0.1:9916 \
    "$CR/gate_coc.exe" "$RUNW/attn2_ctl_aux0.json:netvalgpu" "$RUNW/attn2_best.json:netvalgpu" \
    120 200 200 41500 4 24 stop@0.52 2>"$RUN/gates_err_ctl.log" | tail -1)
[ -n "$g" ] || { echo "FATAL: ctl gate produced no output (see gates_err_ctl.log)" | tee -a "$LOG"; exit 1; }
echo "CTL GATE (aux0 retrain vs seed, 200v200): $g" | tee -a "$LOG"
echo "=== control chain done ===" | tee -a "$LOG"
