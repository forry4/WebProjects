#!/bin/bash
# Capacity x aux-head stack test (2026-07-12 morning). The two levers were each
# measured against the SAME 512,256 fresh-distill control (0.3667 vs champion):
#   capacity alone (1024,512, yesterday's pv_big): 0.4958
#   aux heads alone (512,256, overnight w03):      0.4625 (direct vs ctl 0.5750)
# If they stack even partially, a big-trunk aux distill lands 0.50-0.55 from
# one train. Champion-warm aux looping was tried first and drifted DOWN
# (0.4958 -> 0.4250) — a converged champion resists the fresh-head gradient;
# consolidating a strong fresh distill in its own basin is the r2 playbook.
set -o pipefail
RUN=/c/Users/Forrest/coc_run_aux
RUNW=$(cygpath -m "$RUN")
CR=/c/Users/Forrest/forrestm_projects/coc-core/target/release
TOOLS=/c/Users/Forrest/forrestm_projects/coc-core/tools
CHAMP=C:/Users/Forrest/coc_run_r2/pv_ship_r2.json
LOG=$RUN/overnight_log.txt
CHILDREN=""
killtree() { taskkill //PID "$1" //T //F >/dev/null 2>&1 || true; }
reap_gpu_servers() {
    powershell -NoProfile -Command \
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'gpu_server' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        >/dev/null 2>&1 || true
}
cleanup() { for p in $CHILDREN; do killtree "$p"; done; reap_gpu_servers; }
trap cleanup EXIT

echo "=== big-aux stack train (trunk 1024,512 + aux 0.3) ===" | tee -a "$LOG"
CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$RUNW/aux_boot.t*.csv" \
    --out "$RUNW/pv_aux_big.json" --epochs 4 --trunk 1024,512 \
    --aux-dim 14 --aux-weight 0.3 2>&1 | tee -a "$LOG" || {
    echo "big-aux train CRASHED — retrying once" | tee -a "$LOG"
    CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$RUNW/aux_boot.t*.csv" \
        --out "$RUNW/pv_aux_big.json" --epochs 4 --trunk 1024,512 \
        --aux-dim 14 --aux-weight 0.3 2>&1 | tee -a "$LOG"
}
"$CR/net_export_check.exe" "$RUNW/pv_aux_big.json" 2>&1 | tee -a "$LOG"

echo "=== big-aux gate vs champion (n=240) ===" | tee -a "$LOG"
reap_gpu_servers
COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$RUNW/pv_aux_big.json" --port 9941 >"$RUN/gpu_bigaux.log" 2>&1 &
SRV=$!
CHILDREN="$CHILDREN $SRV"
for _ in $(seq 1 30); do grep -q "ready" "$RUN/gpu_bigaux.log" 2>/dev/null && break; sleep 2; done
grep -q "ready" "$RUN/gpu_bigaux.log" || { echo "FATAL: big-aux gate server never came up" | tee -a "$LOG"; exit 1; }
g=$(COC_GPU_ADDR_A=127.0.0.1:9941 "$CR/gate_coc.exe" "$RUNW/pv_aux_big.json:netvalgpu" \
    "$CHAMP:netval" 120 200 200 21010 4 24 2>>"$RUN/gates_err_bigaux.log" | tail -1)
echo "GATE bigaux-vs-champ: $g" | tee -a "$LOG"
killtree "$SRV"
reap_gpu_servers
echo "=== BIG-AUX CHAIN DONE ===" | tee -a "$LOG"
