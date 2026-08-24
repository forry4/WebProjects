#!/bin/bash
# Stager-teacher pipeline, stages 1b-2 (2026-07-12, /goal: beat champion 67%
# at EQUAL sims). The r2 recipe with a stronger, staging-aware teacher:
#   1b. TEACHER CORPUS: champion+stager(w=0.3) MIRROR self-play (stagerboth),
#       PCR 250@300 full-cap 2000 (r2's recipe), 3000g, aux columns, CPU.
#   2.  aux distill (fresh 512,256, the +9.6pp gradient) + extended training
#       (the +5.4pp lesson) -> equal-sims gates vs champion @200 n=240.
# r2 precedent: a distill can TIE its teacher; this teacher carries the
# staging knowledge the champion lacks.
set -o pipefail
RUN=/c/Users/Forrest/coc_run_stg
RUNW=$(cygpath -m "$RUN")
CR=/c/Users/Forrest/forrestm_projects/coc-core/target/release
TOOLS=/c/Users/Forrest/forrestm_projects/coc-core/tools
CHAMP=C:/Users/Forrest/coc_run_r2/pv_ship_r2.json
LOG=$RUN/stg_log.txt
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
start_server() { # model, port, logname -> sets SRV_PID
    COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$1" --port "$2" >"$RUN/$3" 2>&1 &
    SRV_PID=$!
    CHILDREN="$CHILDREN $SRV_PID"
    for _ in $(seq 1 30); do grep -q "ready" "$RUN/$3" 2>/dev/null && break; sleep 2; done
    grep -q "ready" "$RUN/$3" || { echo "FATAL: gate server $3 never came up" | tee -a "$LOG"; exit 1; }
}
gate() { # A_spec, B_spec, seed, label -> stdout = win rate
    local g
    g=$("$CR/gate_coc.exe" "$1" "$2" 120 200 200 "$3" 4 24 2>>"$RUN/gates_err_stg.log" | tail -1)
    echo "GATE $4: $g" >>"$LOG"
    echo "$g" | sed -E 's/.*: ([0-9.]+) \+-.*/\1/'
}

echo "=== stg_chain: waiting for running gates to release CPU ===" | tee -a "$LOG"
for i in $(seq 1 240); do
    tasklist //FI "IMAGENAME eq gate_coc.exe" 2>/dev/null | grep -q gate_coc || break
    sleep 30
done

if [ ! -f "$RUN/stg_boot.HARVESTED" ]; then
    echo "=== stage 1b: stager-teacher corpus (3000g stagerboth@0.3, PCR 250@300 cap 2000) ===" | tee -a "$LOG"
    "$CR/harvest_boot.exe" "$RUNW/stg_boot" 3000 2000 20 20000000 10 "$CHAMP" \
        netval 1 v1 stagerboth@0.3 250@300 2>&1 | tee -a "$LOG"
    touch "$RUN/stg_boot.HARVESTED"
else
    echo "stage 1b already harvested, skipping" | tee -a "$LOG"
fi

echo "=== stage 2: aux distill (fresh 512,256) ===" | tee -a "$LOG"
CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$RUNW/stg_boot.t*.csv" \
    --out "$RUNW/pv_stg.json" --epochs 4 --aux-dim 14 --aux-weight 0.3 2>&1 | tee -a "$LOG" || {
    echo "distill CRASHED — retrying once" | tee -a "$LOG"
    CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$RUNW/stg_boot.t*.csv" \
        --out "$RUNW/pv_stg.json" --epochs 4 --aux-dim 14 --aux-weight 0.3 2>&1 | tee -a "$LOG"
}
echo "=== stage 2: extended training (warm, lr 5e-4, +4 epochs) ===" | tee -a "$LOG"
CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$RUNW/stg_boot.t*.csv" \
    --out "$RUNW/pv_stg_ext.json" --warm "$RUNW/pv_stg.json" \
    --epochs 4 --lr 5e-4 --aux-dim 14 --aux-weight 0.3 2>&1 | tee -a "$LOG" || {
    echo "ext train CRASHED — retrying once" | tee -a "$LOG"
    CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$RUNW/stg_boot.t*.csv" \
        --out "$RUNW/pv_stg_ext.json" --warm "$RUNW/pv_stg.json" \
        --epochs 4 --lr 5e-4 --aux-dim 14 --aux-weight 0.3 2>&1 | tee -a "$LOG"
}
"$CR/net_export_check.exe" "$RUNW/pv_stg.json" 2>&1 | tee -a "$LOG"
"$CR/net_export_check.exe" "$RUNW/pv_stg_ext.json" 2>&1 | tee -a "$LOG"

echo "=== stage 2 gates: equal-sims vs champion @200 (n=240) ===" | tee -a "$LOG"
reap_gpu_servers
start_server "$RUNW/pv_stg.json" 9951 gpu_stg.log; p1=$SRV_PID
stg_champ=$(COC_GPU_ADDR_A=127.0.0.1:9951 gate "$RUNW/pv_stg.json:netvalgpu" "$CHAMP:netval" 41000 "stg-vs-champ")
killtree "$p1"; reap_gpu_servers; sleep 3
start_server "$RUNW/pv_stg_ext.json" 9952 gpu_stg_ext.log; p1=$SRV_PID
stgext_champ=$(COC_GPU_ADDR_A=127.0.0.1:9952 gate "$RUNW/pv_stg_ext.json:netvalgpu" "$CHAMP:netval" 42000 "stgext-vs-champ")
killtree "$p1"; reap_gpu_servers

echo "SUMMARY(stg) stg_champ=$stg_champ stgext_champ=$stgext_champ" | tee -a "$LOG"
echo "=== STG CHAIN DONE ===" | tee -a "$LOG"
