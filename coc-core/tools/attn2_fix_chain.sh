#!/bin/bash
# Crater fix (attn2): the anchor tail must be CHAMPION-quality (cross-
# distribution), not the seed's own mirror. attn2_boot = seed self-play =
# functionally anchor-free => the P4b iter-3 anchor cliff reproduced exactly
# (gate ~0.29, margin -25, val metrics blind). Fix: harvest a champion (r2
# MLP) 1200-sims anchor logging token rows, retrain iter-0 with it at ~22%
# share, re-gate. Mirror sanity first (attention netvalgpu-vs-netvalgpu was
# never mirror-checked).
set -o pipefail
RUN=/c/Users/Forrest/coc_run_attn2
RUNW=$(cygpath -m "$RUN")
CR=/c/Users/Forrest/forrestm_projects/coc-core/target/release
TOOLS=/c/Users/Forrest/forrestm_projects/coc-core/tools
CHAMP=C:/Users/Forrest/coc_run_r2/pv_ship_r2.json
LOG=$RUN/fix_chain_log.txt
reap() {
    powershell -NoProfile -Command \
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'gpu_server' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        >/dev/null 2>&1 || true
}
trap reap EXIT
srv() { # srv <model> <port> <log> <pad>
    COC_GPU_PAD=$4 python "$TOOLS/gpu_server.py" "$1" --port "$2" >"$3" 2>&1 &
    for _ in $(seq 1 30); do grep -q ready "$3" 2>/dev/null && break; sleep 2; done
    grep -q ready "$3" || { echo "FATAL: server $2 never ready" | tee -a "$LOG"; exit 1; }
    grep -q "dev=cuda" "$3" || { echo "FATAL: server $2 dev=cpu" | tee -a "$LOG"; exit 1; }
}

echo "=== [1/4] mirror sanity: seed netvalgpu vs seed netvalgpu (expect 0.5000) ===" | tee -a "$LOG"
reap
srv "$RUNW/attn2_best.json" 9923 "$RUN/gpu_mir_a.log" 48
srv "$RUNW/attn2_best.json" 9924 "$RUN/gpu_mir_b.log" 48
g=$(COC_GPU_ADDR_A=127.0.0.1:9923 COC_GPU_ADDR_B=127.0.0.1:9924 \
    "$CR/gate_coc.exe" "$RUNW/attn2_best.json:netvalgpu" "$RUNW/attn2_best.json:netvalgpu" \
    40 200 200 43500 4 24 2>"$RUN/gates_err_mir.log" | tail -1)
echo "MIRROR: $g" | tee -a "$LOG"
reap

echo "=== [2/4] champion anchor harvest: 2000g @1200 (plain, tok rows) ===" | tee -a "$LOG"
if [ ! -f "$RUN/attn2_champ.HARVESTED" ]; then
    srv "$CHAMP" 9925 "$RUN/gpu_champ.log" 128
    if ! COC_GPU_ADDR="127.0.0.1:9925" "$CR/harvest_boot.exe" "$RUNW/attn2_champ" 2000 1200 20 \
        25000000 10 "$CHAMP" netvalgpu 64 tok 2>&1 | tee -a "$LOG"; then
        echo "FATAL: champion anchor harvest failed" | tee -a "$LOG"; exit 1
    fi
    ls "$RUN"/attn2_champ.t0.csv >/dev/null 2>&1 || { echo "FATAL: harvest exited 0, no CSVs" | tee -a "$LOG"; exit 1; }
    reap
    touch "$RUN/attn2_champ.HARVESTED"
else
    echo "champion anchor already harvested, skipping" | tee -a "$LOG"
fi

echo "=== [3/4] retrain iter-0 with champion anchor tail ===" | tee -a "$LOG"
data="$RUNW/sp_0.t*.csv;$RUNW/lg_0.t*.csv;$RUNW/attn2_champ.t[0-2].csv"
CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_attn.py" --data "$data" --out "$RUNW/attn2_cand_0b.json" \
    --warm "$RUNW/attn2_best.json" --lr 5e-4 --epochs 2 --aux-dim 14 --aux-weight 0.3 2>&1 | tee -a "$LOG" \
    || { echo "FATAL: retrain failed" | tee -a "$LOG"; exit 1; }
"$CR/attn_export_check.exe" "$RUNW/attn2_cand_0b.json" | tee -a "$LOG"

echo "=== [4/4] gates: cand_0b vs seed + yardstick vs champion ===" | tee -a "$LOG"
reap
srv "$RUNW/attn2_cand_0b.json" 9926 "$RUN/gpu_fix_a.log" 48
srv "$RUNW/attn2_best.json" 9927 "$RUN/gpu_fix_b.log" 48
g1=$(COC_GPU_ADDR_A=127.0.0.1:9926 COC_GPU_ADDR_B=127.0.0.1:9927 \
    "$CR/gate_coc.exe" "$RUNW/attn2_cand_0b.json:netvalgpu" "$RUNW/attn2_best.json:netvalgpu" \
    120 200 200 43600 4 24 stop@0.52 2>"$RUN/gates_err_fix.log" | tail -1)
echo "FIX GATE (cand_0b vs seed): $g1" | tee -a "$LOG"
g3=$(COC_GPU_ADDR_A=127.0.0.1:9926 \
    "$CR/gate_coc.exe" "$RUNW/attn2_cand_0b.json:netvalgpu" "$CHAMP:netval" \
    60 200 200 43700 4 24 2>>"$RUN/gates_err_fix.log" | tail -1)
echo "FIX YARDSTICK (cand_0b vs r2-champ, baseline ~0.44): $g3" | tee -a "$LOG"
reap
echo "=== fix chain done ===" | tee -a "$LOG"
