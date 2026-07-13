#!/bin/bash
# Recovery for the 2026-07-12 overnight gate failures: the orchestrator reused
# port 9913 across back-to-back gate-server swaps and the OLD server kept
# answering (Windows SO_REUSEADDR double-bind — killtree alone doesn't
# guarantee the port), so gate_coc's per-side startup parity probe panicked
# (correctly: it was being served a different model). LESSON: one port per
# server per script run, and reap_gpu_servers between every server swap.
# Re-runs the three failed gates on DISTINCT ports (9931/9932/9933), then the
# verdict: if the direct w03-vs-ctl gate shows the aux signal (>=0.53), start
# the consolidation loop seeded from the CHAMPION (the 0.37 distill arms are
# too weak to seed a shippable line; champion+aux-gradient is the integration
# that matters).
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

gate() { # A_spec, B_spec, seed, label
    local g
    g=$("$CR/gate_coc.exe" "$1" "$2" 120 200 200 "$3" 4 24 2>>"$RUN/gates_err_rerun.log" | tail -1)
    echo "GATE $4: $g" >>"$LOG"
    echo "$g" | sed -E 's/.*: ([0-9.]+) \+-.*/\1/'
}
start_server() { # model, port, logname -> sets SRV_PID
    COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$1" --port "$2" >"$RUN/$3" 2>&1 &
    SRV_PID=$!
    CHILDREN="$CHILDREN $SRV_PID"
    for _ in $(seq 1 30); do grep -q "ready" "$RUN/$3" 2>/dev/null && break; sleep 2; done
    grep -q "ready" "$RUN/$3" || { echo "FATAL: gate server $3 never came up" | tee -a "$LOG"; exit 1; }
}

echo "=== gate re-run (distinct ports, reap between swaps) ===" | tee -a "$LOG"
reap_gpu_servers
sleep 3
start_server "$RUNW/pv_aux_w03.json" 9931 gpu_rerun_w03.log; p1=$SRV_PID
start_server "$RUNW/pv_aux_ctl.json" 9932 gpu_rerun_ctl.log; p2=$SRV_PID
w03_champ=$(COC_GPU_ADDR_A=127.0.0.1:9931 gate "$RUNW/pv_aux_w03.json:netvalgpu" "$CHAMP:netval" 21001 "w03-vs-champ")
w03_ctl=$(COC_GPU_ADDR_A=127.0.0.1:9931 COC_GPU_ADDR_B=127.0.0.1:9932 \
    gate "$RUNW/pv_aux_w03.json:netvalgpu" "$RUNW/pv_aux_ctl.json:netvalgpu" 21003 "w03-vs-ctl-DIRECT")
killtree "$p1"; killtree "$p2"
reap_gpu_servers
sleep 3
start_server "$RUNW/pv_aux_w03L.json" 9933 gpu_rerun_w03L.log; p1=$SRV_PID
w03L_champ=$(COC_GPU_ADDR_A=127.0.0.1:9933 gate "$RUNW/pv_aux_w03L.json:netvalgpu" "$CHAMP:netval" 21002 "w03L-vs-champ")
killtree "$p1"
reap_gpu_servers

echo "SUMMARY(rerun) ctl_champ=0.3667 w03_champ=$w03_champ w03L_champ=$w03L_champ w03_ctl_direct=$w03_ctl" | tee -a "$LOG"

go=0
awk "BEGIN{exit !($w03_ctl >= 0.53)}" 2>/dev/null && go=1
if [ "$go" = 1 ]; then
    echo "VERDICT(rerun): GO — aux signal confirmed (direct $w03_ctl); starting consolidation loop from the CHAMPION" | tee -a "$LOG"
    SEED_NET="$CHAMP" exec bash "$TOOLS/loop_coc_aux.sh"
else
    echo "VERDICT(rerun): NO-GO — direct w03-vs-ctl=$w03_ctl (w03_champ=$w03_champ w03L_champ=$w03L_champ); aux gradient did not move play strength" | tee -a "$LOG"
fi
