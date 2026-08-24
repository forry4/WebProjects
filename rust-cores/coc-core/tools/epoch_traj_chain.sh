#!/bin/bash
# Crater forensics step 3 (attn2): the EPOCH-CALIBRATION hypothesis.
# P4b precedent: the 1200-sims distill first gated 0.2917 and +8 warm epochs
# lifted it to 0.4458 — value-head calibration settles over epochs while val
# AUC/top1 stay blind. The loop gave iter-0 ONE effective epoch (best-val
# export picked epoch 0). Train the loop config 6 epochs with per-epoch
# snapshots, gate the trajectory vs the seed. Gates climbing toward ~0.5 =>
# fix the loop (epochs + export-final) and relaunch.
set -o pipefail
RUN=/c/Users/Forrest/coc_run_attn2
RUNW=$(cygpath -m "$RUN")
CR=/c/Users/Forrest/forrestm_projects/coc-core/target/release
TOOLS=/c/Users/Forrest/forrestm_projects/coc-core/tools
LOG=$RUN/epoch_traj_log.txt
reap() {
    powershell -NoProfile -Command \
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'gpu_server' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        >/dev/null 2>&1 || true
}
trap reap EXIT

data="$RUNW/sp_0.t*.csv;$RUNW/lg_0.t*.csv;$RUNW/attn2_boot.t[0-1].csv"
echo "=== epoch-trajectory: loop config x6 epochs, per-epoch snapshots ===" | tee -a "$LOG"
if [ ! -f "$RUN/attn2_ep_ep5.json" ]; then
    CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_attn.py" --data "$data" --out "$RUNW/attn2_ep_best.json" \
        --warm "$RUNW/attn2_best.json" --lr 5e-4 --epochs 6 --aux-dim 14 --aux-weight 0.3 \
        --snap-prefix "$RUNW/attn2_ep_" 2>&1 | tee -a "$LOG" \
        || { echo "FATAL: trajectory train failed" | tee -a "$LOG"; exit 1; }
fi

port_a=9917
for ep in 2 4 5; do
    snap=$RUNW/attn2_ep_ep$ep.json
    [ -f "/c/Users/Forrest/coc_run_attn2/attn2_ep_ep$ep.json" ] || { echo "missing snapshot ep$ep" | tee -a "$LOG"; continue; }
    "$CR/attn_export_check.exe" "$snap" | tee -a "$LOG"
    reap
    port_b=$((port_a + 1))
    COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$snap" --port $port_a >"$RUN/gpu_ep${ep}_a.log" 2>&1 &
    COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$RUNW/attn2_best.json" --port $port_b >"$RUN/gpu_ep${ep}_b.log" 2>&1 &
    for _ in $(seq 1 30); do
        grep -q ready "$RUN/gpu_ep${ep}_a.log" 2>/dev/null && grep -q ready "$RUN/gpu_ep${ep}_b.log" 2>/dev/null && break
        sleep 2
    done
    grep -q "dev=cuda" "$RUN/gpu_ep${ep}_a.log" || { echo "FATAL: ep$ep sidecar A dev=cpu" | tee -a "$LOG"; exit 1; }
    grep -q "dev=cuda" "$RUN/gpu_ep${ep}_b.log" || { echo "FATAL: ep$ep sidecar B dev=cpu" | tee -a "$LOG"; exit 1; }
    g=$(COC_GPU_ADDR_A=127.0.0.1:$port_a COC_GPU_ADDR_B=127.0.0.1:$port_b \
        "$CR/gate_coc.exe" "$snap:netvalgpu" "$RUNW/attn2_best.json:netvalgpu" \
        120 200 200 $((42500 + ep * 100)) 4 24 stop@0.52 2>"$RUN/gates_err_ep$ep.log" | tail -1)
    echo "EPOCH-TRAJ GATE ep$ep vs seed: $g" | tee -a "$LOG"
    port_a=$((port_a + 2))
done
reap
echo "=== epoch-trajectory chain done ===" | tee -a "$LOG"
