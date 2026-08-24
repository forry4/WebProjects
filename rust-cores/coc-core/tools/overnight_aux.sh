#!/bin/bash
# Overnight aux-head orchestrator (2026-07-11 -> 12). Fully autonomous chain —
# survives Claude/session restarts (launched detached; every stage is a plain
# process this script owns). Waits for the running aux corpus harvest, then:
#   1. CPU stager-league harvest (1200g champion-vs-stager w=0.6, NEW format)
#      CONCURRENT with the GPU trains
#   2. paired trains on aux_boot: control (--aux-weight 0) vs treatment (0.3)
#      — identical seed/init/data; the ONLY delta is the aux gradient
#   3. third arm: treatment + league mix (aux signal x staged positions —
#      the combined thesis; today's league dose WITHOUT aux heads didn't
#      shift style, the aux head is the gradient that can price staged assets)
#   4. gates vs champion @200 (n=240 each) + a direct treatment-vs-control
#   5. VERDICT: if any aux arm clears the bar, exec loop_coc_aux.sh seeded
#      from the better arm (the proven netval consolidation converter) so the
#      remaining night hours run loop iterations instead of idling
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

echo "=== overnight_aux: waiting for aux corpus harvest ===" | tee -a "$LOG"
for i in $(seq 1 360); do
    [ -f "$RUN/aux_boot.HARVESTED" ] && break
    sleep 60
done
[ -f "$RUN/aux_boot.HARVESTED" ] || { echo "FATAL: harvest never completed (6h timeout)" | tee -a "$LOG"; exit 1; }
echo "=== harvest complete; starting league (cpu) + trains (gpu) ===" | tee -a "$LOG"
reap_gpu_servers

# 1. stager league on CPU, concurrent with the GPU trains. Champion plays both
# seats (stager bias on alternating seat) — same corpus recipe as the day's
# validated league, but the new binary logs the aux columns.
if [ ! -f "$RUN/lg_aux.HARVESTED" ]; then
    "$CR/harvest_boot.exe" "$RUNW/lg_aux" 1200 300 20 16500000 10 "$CHAMP" \
        netval 1 v1 "stager@0.6" >"$RUN/league_aux.log" 2>&1 &
    league_pid=$!
    CHILDREN="$CHILDREN $league_pid"
else
    league_pid=""
    echo "league already harvested, skipping" | tee -a "$LOG"
fi

# 2. paired trains (GPU, sequential). --aux-dim 0 would MIS-PARSE the new
# 14-column CSVs; weight 0 is the control knob (same parse, same init, zero
# aux gradient).
run_train() { # out, aux_weight, data
    CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$3" --out "$1" \
        --epochs 4 --aux-dim 14 --aux-weight "$2" 2>&1 | tee -a "$LOG" || {
        echo "train $1 CRASHED — retrying once" | tee -a "$LOG"
        CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$3" --out "$1" \
            --epochs 4 --aux-dim 14 --aux-weight "$2" 2>&1 | tee -a "$LOG"
    }
}
echo "=== control train (aux-weight 0) ===" | tee -a "$LOG"
run_train "$RUNW/pv_aux_ctl.json" 0 "$RUNW/aux_boot.t*.csv"
echo "=== treatment train (aux-weight 0.3) ===" | tee -a "$LOG"
run_train "$RUNW/pv_aux_w03.json" 0.3 "$RUNW/aux_boot.t*.csv"

# 3. league-mix arm (needs the league corpus)
if [ -n "$league_pid" ]; then
    wait "$league_pid" || { echo "FATAL: league harvest failed (see league_aux.log)" | tee -a "$LOG"; exit 1; }
    touch "$RUN/lg_aux.HARVESTED"
fi
echo "=== league-mix train (aux-weight 0.3, +lg_aux) ===" | tee -a "$LOG"
run_train "$RUNW/pv_aux_w03L.json" 0.3 "$RUNW/aux_boot.t*.csv;$RUNW/lg_aux.t*.csv"

echo "=== export parity checks ===" | tee -a "$LOG"
for n in pv_aux_ctl pv_aux_w03 pv_aux_w03L; do
    "$CR/net_export_check.exe" "$RUNW/$n.json" 2>&1 | tee -a "$LOG"
done

# 4. gates. Champion side runs CPU f32 (:netval), candidate side on a sidecar.
# gate() prints ONLY the parsed win rate on stdout (callers capture it); the
# human-readable line goes straight to the log.
gate() { # A_spec, B_spec, seed, label
    local g
    g=$("$CR/gate_coc.exe" "$1" "$2" 120 200 200 "$3" 4 24 2>>"$RUN/gates_err_night.log" | tail -1)
    echo "GATE $4: $g" >>"$LOG"
    echo "$g" | sed -E 's/.*: ([0-9.]+) \+-.*/\1/'
}
start_server() { # model, port, logname -> sets SRV_PID (NOT $(): exit in a
    # command substitution only kills the subshell, and the pid echo would race
    # the FATAL tee)
    COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$1" --port "$2" >"$RUN/$3" 2>&1 &
    SRV_PID=$!
    CHILDREN="$CHILDREN $SRV_PID"
    for _ in $(seq 1 30); do grep -q "ready" "$RUN/$3" 2>/dev/null && break; sleep 2; done
    grep -q "ready" "$RUN/$3" || { echo "FATAL: gate server $3 never came up" | tee -a "$LOG"; exit 1; }
}
echo "=== gates (n=240 each) ===" | tee -a "$LOG"
reap_gpu_servers
start_server "$RUNW/pv_aux_ctl.json" 9913 gpu_night_ctl.log; p1=$SRV_PID
ctl_champ=$(COC_GPU_ADDR_A=127.0.0.1:9913 gate "$RUNW/pv_aux_ctl.json:netvalgpu" "$CHAMP:netval" 21000 "ctl-vs-champ")
killtree "$p1"
start_server "$RUNW/pv_aux_w03.json" 9913 gpu_night_w03.log; p1=$SRV_PID
start_server "$RUNW/pv_aux_ctl.json" 9914 gpu_night_ctl2.log; p2=$SRV_PID
w03_champ=$(COC_GPU_ADDR_A=127.0.0.1:9913 gate "$RUNW/pv_aux_w03.json:netvalgpu" "$CHAMP:netval" 21001 "w03-vs-champ")
w03_ctl=$(COC_GPU_ADDR_A=127.0.0.1:9913 COC_GPU_ADDR_B=127.0.0.1:9914 \
    gate "$RUNW/pv_aux_w03.json:netvalgpu" "$RUNW/pv_aux_ctl.json:netvalgpu" 21003 "w03-vs-ctl-DIRECT")
killtree "$p1"; killtree "$p2"
start_server "$RUNW/pv_aux_w03L.json" 9913 gpu_night_w03L.log; p1=$SRV_PID
w03L_champ=$(COC_GPU_ADDR_A=127.0.0.1:9913 gate "$RUNW/pv_aux_w03L.json:netvalgpu" "$CHAMP:netval" 21002 "w03L-vs-champ")
killtree "$p1"
reap_gpu_servers

echo "SUMMARY ctl_champ=$ctl_champ w03_champ=$w03_champ w03L_champ=$w03L_champ w03_ctl_direct=$w03_ctl" | tee -a "$LOG"

# 5. verdict: spend the remaining night hours on the consolidation loop iff
# the aux signal shows up anywhere (lenient bar — worst case idle compute is
# spent on a loop we discard in the morning; the morning gates re-arbitrate).
go=0
awk "BEGIN{exit !($w03_ctl >= 0.53)}" 2>/dev/null && go=1
awk "BEGIN{exit !($w03_champ >= 0.51)}" 2>/dev/null && go=1
awk "BEGIN{exit !($w03L_champ >= 0.51)}" 2>/dev/null && go=1
if [ "$go" = 1 ]; then
    seed_net="$RUNW/pv_aux_w03.json"
    if awk "BEGIN{exit !($w03L_champ > $w03_champ)}" 2>/dev/null; then
        seed_net="$RUNW/pv_aux_w03L.json"
    fi
    echo "VERDICT: GO — starting consolidation loop from $seed_net" | tee -a "$LOG"
    SEED_NET="$seed_net" exec bash "$TOOLS/loop_coc_aux.sh"
else
    echo "VERDICT: NO-GO — aux arms did not clear the bar (ctl=$ctl_champ w03=$w03_champ w03L=$w03L_champ direct=$w03_ctl); no loop started" | tee -a "$LOG"
fi
