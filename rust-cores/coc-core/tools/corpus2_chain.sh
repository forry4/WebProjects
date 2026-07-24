#!/bin/bash
# Corpus-doubling + aux-weight sweep chain (2026-07-13 early AM, GPU idle).
# The weekend's verdict: consolidation is flat on the aux line at ~0.47 — the
# binding constraint is the DISTILL STARTING POINT. Two untested free levers:
#   1. corpus size: +5000g champion 6000-cap PCR games (aux_boot2) -> 10k total
#   2. aux-weight response curve: fresh distills at w={0.15,0.3,0.6} on the
#      combined corpus (0.3 was a first guess that paid +9.6pp; the curve is
#      unexplored), + an ext pass (lr 5e-4 +4ep) on the best-by-gate
# Gates: full n=240 vs champion (measurement — no early stop).
set -o pipefail
RUN=/c/Users/Forrest/coc_run_aux
RUNW=$(cygpath -m "$RUN")
CR=/c/Users/Forrest/forrestm_projects/coc-core/target/release
TOOLS=/c/Users/Forrest/forrestm_projects/coc-core/tools
CHAMP=C:/Users/Forrest/coc_run_r2/pv_ship_r2.json
LOG=$RUN/corpus2_log.txt
CHILDREN=""
killtree() { taskkill //PID "$1" //T //F >/dev/null 2>&1 || true; }
reap_gpu_servers() {
    powershell -NoProfile -Command \
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'gpu_server' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        >/dev/null 2>&1 || true
}
cleanup() { for p in $CHILDREN; do killtree "$p"; done; reap_gpu_servers; }
trap cleanup EXIT
start_server() { # model, port, logname -> sets SRV_PID
    COC_GPU_PAD="${SRV_PAD:-48}" python "$TOOLS/gpu_server.py" "$1" --port "$2" >"$RUN/$3" 2>&1 &
    SRV_PID=$!
    CHILDREN="$CHILDREN $SRV_PID"
    for _ in $(seq 1 30); do grep -q "ready" "$RUN/$3" 2>/dev/null && break; sleep 2; done
    grep -q "ready" "$RUN/$3" || { echo "FATAL: server $3 never came up" | tee -a "$LOG"; exit 1; }
    grep -q "dev=cuda" "$RUN/$3" || { echo "FATAL: server $3 came up dev=cpu" | tee -a "$LOG"; exit 1; }
}
gate() { # A_spec, B_spec, seed, label -> stdout = win rate
    local g
    g=$("$CR/gate_coc.exe" "$1" "$2" 120 200 200 "$3" 4 24 2>>"$RUN/gates_err_c2.log" | tail -1)
    echo "GATE $4: $g" >>"$LOG"
    echo "$g" | sed -E 's/.*: ([0-9.]+) \+-.*/\1/'
}

if [ ! -f "$RUN/aux_boot2.HARVESTED" ]; then
    echo "=== corpus extension: +5000g champion PCR 250@300 cap 6000 ===" | tee -a "$LOG"
    reap_gpu_servers
    SRV_PAD=128 start_server "$CHAMP" 9911 gpu_c2harvest.log
    hpid=$SRV_PID
    COC_GPU_ADDR="127.0.0.1:9911" "$CR/harvest_boot.exe" "$RUNW/aux_boot2" 5000 6000 20 \
        21000000 10 "$CHAMP" netvalgpu 64 v1 250@300 2>&1 | tee -a "$LOG"
    killtree "$hpid"
    reap_gpu_servers
    touch "$RUN/aux_boot2.HARVESTED"
else
    echo "corpus extension already harvested, skipping" | tee -a "$LOG"
fi

DATA="$RUNW/aux_boot.t*.csv;$RUNW/aux_boot2.t*.csv"
for w in 0.15 0.3 0.6; do
    tag=$(echo "$w" | tr -d '.')
    echo "=== sweep train w=$w on 10k corpus ===" | tee -a "$LOG"
    CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$DATA" \
        --out "$RUNW/pv_10k_w$tag.json" --epochs 4 --aux-dim 14 --aux-weight "$w" 2>&1 | tee -a "$LOG" || {
        echo "train w=$w CRASHED — retrying once" | tee -a "$LOG"
        CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$DATA" \
            --out "$RUNW/pv_10k_w$tag.json" --epochs 4 --aux-dim 14 --aux-weight "$w" 2>&1 | tee -a "$LOG"
    }
    "$CR/net_export_check.exe" "$RUNW/pv_10k_w$tag.json" 2>&1 | tee -a "$LOG"
done

echo "=== sweep gates vs champion (n=240 each) ===" | tee -a "$LOG"
best_wr=0; best_tag=""
for tag in 015 03 06; do
    reap_gpu_servers; sleep 3
    start_server "$RUNW/pv_10k_w$tag.json" 9961 "gpu_c2_$tag.log"
    p=$SRV_PID
    wr=$(COC_GPU_ADDR_A=127.0.0.1:9961 gate "$RUNW/pv_10k_w$tag.json:netvalgpu" "$CHAMP:netval" $((51000 + tag)) "10k-w$tag-vs-champ")
    killtree "$p"
    echo "w$tag: $wr" | tee -a "$LOG"
    if awk "BEGIN{exit !($wr > $best_wr)}" 2>/dev/null; then best_wr=$wr; best_tag=$tag; fi
done
echo "SWEEP BEST: w$best_tag at $best_wr" | tee -a "$LOG"

echo "=== ext pass on winner (lr 5e-4 +4ep) ===" | tee -a "$LOG"
CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$DATA" \
    --out "$RUNW/pv_10k_best_ext.json" --warm "$RUNW/pv_10k_w$best_tag.json" \
    --epochs 4 --lr 5e-4 --aux-dim 14 --aux-weight 0.3 2>&1 | tee -a "$LOG"
"$CR/net_export_check.exe" "$RUNW/pv_10k_best_ext.json" 2>&1 | tee -a "$LOG"
reap_gpu_servers; sleep 3
start_server "$RUNW/pv_10k_best_ext.json" 9962 gpu_c2_ext.log
p=$SRV_PID
ext_wr=$(COC_GPU_ADDR_A=127.0.0.1:9962 gate "$RUNW/pv_10k_best_ext.json:netvalgpu" "$CHAMP:netval" 52000 "10k-ext-vs-champ")
killtree "$p"
reap_gpu_servers
echo "SUMMARY(corpus2) best_distill=w$best_tag@$best_wr ext=$ext_wr (baselines: 5k-corpus w03=0.4625, w03_ext=0.4708)" | tee -a "$LOG"
echo "=== CORPUS2 CHAIN DONE ===" | tee -a "$LOG"
