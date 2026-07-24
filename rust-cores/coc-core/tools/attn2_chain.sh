#!/bin/bash
# Attention-escalation bootstrap chain: anchor harvest -> loop_coc_attn2.sh.
# Anchor = seed-net (attn_best) MIRROR self-play at the escalated config
# (1200 sims, PCR 250@300), token rows + aux columns — its t[0-1] become the
# loop's permanent anchor tail (P4b anchor-cliff discipline). The old
# attn_boot corpus is gone (disk cleanup) and predates the aux columns anyway.
set -o pipefail
RUN=/c/Users/Forrest/coc_run_attn2
RUNW=$(cygpath -m "$RUN")
CR=/c/Users/Forrest/forrestm_projects/coc-core/target/release
TOOLS=/c/Users/Forrest/forrestm_projects/coc-core/tools
SEED=${SEED_NET:-C:/Users/Forrest/coc_run_attn/attn_best.json}
LOG=$RUN/chain_log.txt
mkdir -p "$RUN"
CHILDREN=""
killtree() { taskkill //PID "$1" //T //F >/dev/null 2>&1 || true; }
reap_gpu_servers() {
    powershell -NoProfile -Command \
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'gpu_server' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        >/dev/null 2>&1 || true
}
cleanup() { for p in $CHILDREN; do killtree "$p"; done; reap_gpu_servers; }
trap cleanup EXIT

if [ ! -f "$RUN/attn2_boot.HARVESTED" ]; then
    echo "=== anchor harvest: 1500g attn_best mirror @1200 PCR 250@300 ===" | tee -a "$LOG"
    reap_gpu_servers
    COC_GPU_PAD=128 python "$TOOLS/gpu_server.py" "$SEED" --port 9911 >"$RUN/gpu_anchor.log" 2>&1 &
    gpu_pid=$!
    CHILDREN="$CHILDREN $gpu_pid"
    for _ in $(seq 1 30); do grep -q "ready" "$RUN/gpu_anchor.log" 2>/dev/null && break; sleep 2; done
    grep -q "ready" "$RUN/gpu_anchor.log" || { echo "FATAL: anchor gpu server never came up" | tee -a "$LOG"; exit 1; }
    grep -q "dev=cuda" "$RUN/gpu_anchor.log" || { echo "FATAL: anchor sidecar dev=cpu" | tee -a "$LOG"; exit 1; }
    if ! COC_GPU_ADDR="127.0.0.1:9911" "$CR/harvest_boot.exe" "$RUNW/attn2_boot" 1500 1200 20 \
        22000000 10 "$SEED" netvalgpu 64 tok 250@300 2>&1 | tee -a "$LOG"; then
        echo "FATAL: anchor harvest failed — NOT touching the HARVESTED marker" | tee -a "$LOG"
        exit 1
    fi
    ls "$RUN"/attn2_boot.t0.csv >/dev/null 2>&1 || { echo "FATAL: harvest exited 0 but produced no CSVs" | tee -a "$LOG"; exit 1; }
    killtree "$gpu_pid"
    reap_gpu_servers
    touch "$RUN/attn2_boot.HARVESTED"
else
    echo "anchor already harvested, skipping" | tee -a "$LOG"
fi

echo "=== starting attention escalation loop ===" | tee -a "$LOG"
SEED_NET="$SEED" exec bash "$TOOLS/loop_coc_attn2.sh"
