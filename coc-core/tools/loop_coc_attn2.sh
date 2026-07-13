#!/bin/bash
# ATTENTION ESCALATION loop (2026-07-13, /goal 0.60-vs-champion at equal sims).
# The P4b attention line folded at 300-sims self-play (yardstick flat ~0.44);
# this is the escalation that was never run, with everything the 2026-07-11..13
# campaign built layered on:
#   * self-play at SIMS=1200 with PCR 250@300 (the hs/r2 target-quality levers)
#   * vs-CHAMPION league each iter (fixes the internal-up/yardstick-down
#     divergence; only the training net's rows recorded)
#   * aux score-decomposition gradient (--aux-dim 14, +9.6pp on MLP distills)
#   * anchor tail = attn2_boot.t[0-1] (1200-sims seed-quality rows; the P4b
#     iter-3 anchor-cliff lesson — attention craters without a tail)
#   * shared-queue harvests, stop@0.52 promote gates
# Seed: the folded run's best (coc_run_attn/attn_best.json, ~0.44 vs champ).
#
#   SEED_NET=C:/Users/Forrest/coc_run_attn/attn_best.json bash loop_coc_attn2.sh
set -e -o pipefail
RUN=${RUN:-/c/Users/Forrest/coc_run_attn2}
RUNW=$(cygpath -m "$RUN")
CR=${CR:-/c/Users/Forrest/forrestm_projects/coc-core/target/release}
TOOLS=${TOOLS:-/c/Users/Forrest/forrestm_projects/coc-core/tools}
[ -n "$SEED_NET" ] || { echo "FATAL: SEED_NET env required"; exit 1; }
CHAMP_YARD=${CHAMP_YARD:-C:/Users/Forrest/coc_run_r2/pv_ship_r2.json}
ITERS=${ITERS:-6}
GAMES=${GAMES:-2000}
LEAGUE_GAMES=${LEAGUE_GAMES:-400}
LEAGUE_SIMS=${LEAGUE_SIMS:-300}
LEAGUE_THREADS=${LEAGUE_THREADS:-6}
SIMS=${SIMS:-1200}
PCR_SPEC=${PCR_SPEC:-250@300}
AUX_W=${AUX_W:-0.3}
GPU_BATCH=${GPU_BATCH:-64}
GPU_PORT=${GPU_PORT:-9911}
GATE_PAIRS=${GATE_PAIRS:-120}
GATE_SIMS=${GATE_SIMS:-200}
YARD_PAIRS=${YARD_PAIRS:-60}
THREADS=${THREADS:-10}
LEAGUE_SPEC=${LEAGUE_SPEC:-vs@$CHAMP_YARD}
LOG=$RUN/loop_attn2_log.txt
BEST=$RUN/attn2_best.json
BESTW=$RUNW/attn2_best.json
PROG=$RUN/progress_attn2

mkdir -p "$RUN"

LOCKDIR=$RUN/loop_attn2.lock
if mkdir "$LOCKDIR" 2>/dev/null; then
    echo $$ >"$LOCKDIR/pid"
else
    oldpid=$(cat "$LOCKDIR/pid" 2>/dev/null || true)
    if [ -n "$oldpid" ] && kill -0 "$oldpid" 2>/dev/null; then
        echo "FATAL: loop instance pid $oldpid is ALIVE — refusing to double-launch" | tee -a "$LOG"
        exit 1
    fi
    rm -rf "$LOCKDIR"; mkdir "$LOCKDIR"; echo $$ >"$LOCKDIR/pid"
fi
CHILDREN=""
killtree() { taskkill //PID "$1" //T //F >/dev/null 2>&1 || true; }
reap_gpu_servers() {
    powershell -NoProfile -Command \
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'gpu_server' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        >/dev/null 2>&1 || true
}
cleanup() {
    for p in $CHILDREN; do killtree "$p"; done
    reap_gpu_servers
    rm -rf "$LOCKDIR" 2>/dev/null || true
}
trap cleanup EXIT
if tasklist //FI "IMAGENAME eq harvest_boot.exe" 2>/dev/null | grep -q harvest_boot; then
    echo "FATAL: a harvest_boot.exe is already running — clean up first" | tee -a "$LOG"
    exit 1
fi
for port in "$GPU_PORT" 9913 9914; do
    if netstat -ano 2>/dev/null | grep -q ":$port .*LISTENING"; then
        echo "FATAL: port $port already bound — a gpu_server is lingering; clean up first" | tee -a "$LOG"
        exit 1
    fi
done
ls "$RUN"/attn2_boot.t0.csv >/dev/null 2>&1 || {
    echo "FATAL: anchor corpus missing (attn2_boot.t0.csv) — run the anchor harvest first" | tee -a "$LOG"; exit 1; }

# seed .check may not exist for older nets (regenerable) — must not kill the
# loop under set -e
[ -f "$BEST" ] || { cp "$SEED_NET" "$BEST"; cp "$SEED_NET.check" "$BEST.check" 2>/dev/null || true; }
start=$(cat "$PROG" 2>/dev/null || echo 0)
echo "=== loop_coc_attn2 from iter $start / $ITERS (games=$GAMES+$LEAGUE_GAMES-league sims=$SIMS pcr=$PCR_SPEC aux_w=$AUX_W seed=$SEED_NET) ===" | tee -a "$LOG"

for ((k = start; k < ITERS; k++)); do
    league_pid=""
    if [ -f "$RUN/lg_$k.HARVESTED" ]; then
        echo "--- iter $k: league already complete, skipping ---" | tee -a "$LOG"
    else
        echo "--- iter $k: league (cpu, $LEAGUE_SPEC, $LEAGUE_GAMES g @$LEAGUE_SIMS) ---" | tee -a "$LOG"
        lseed=$((23000000 + k * 100000))
        "$CR/harvest_boot.exe" "$RUNW/lg_$k" "$LEAGUE_GAMES" "$LEAGUE_SIMS" 20 \
            "$lseed" "$LEAGUE_THREADS" "$BESTW" netval 1 tok "$LEAGUE_SPEC" >>"$RUN/league_$k.log" 2>&1 &
        league_pid=$!
        CHILDREN="$CHILDREN $league_pid"
    fi

    if [ -f "$RUN/sp_$k.HARVESTED" ]; then
        echo "--- iter $k: self-play already complete, skipping ---" | tee -a "$LOG"
    else
        echo "--- iter $k: netval self-play (gpu sidecar, attention) ---" | tee -a "$LOG"
        sp_ok=0
        for attempt in 1 2; do
            reap_gpu_servers
            COC_GPU_PAD=$((GPU_BATCH * 2)) python "$TOOLS/gpu_server.py" "$BESTW" --port "$GPU_PORT" >"$RUN/gpu_server_a$k.log" 2>&1 &
            gpu_pid=$!
            CHILDREN="$CHILDREN $gpu_pid"
            for _ in $(seq 1 30); do
                grep -q "ready" "$RUN/gpu_server_a$k.log" 2>/dev/null && break
                sleep 2
            done
            grep -q "ready" "$RUN/gpu_server_a$k.log" || { echo "iter $k FATAL: gpu server never came up" | tee -a "$LOG"; exit 1; }
            grep -q "dev=cuda" "$RUN/gpu_server_a$k.log" || { echo "iter $k FATAL: sidecar came up dev=cpu" | tee -a "$LOG"; exit 1; }
            seed=$((24000000 + k * 100000))
            if COC_GPU_ADDR="127.0.0.1:$GPU_PORT" "$CR/harvest_boot.exe" "$RUNW/sp_$k" "$GAMES" "$SIMS" 20 \
                "$seed" "$THREADS" "$BESTW" netvalgpu "$GPU_BATCH" tok "$PCR_SPEC" 2>>"$LOG"; then
                sp_ok=1
                killtree "$gpu_pid"
                break
            fi
            echo "iter $k self-play harvest FAILED (attempt $attempt) — reaping and retrying" | tee -a "$LOG"
            killtree "$gpu_pid"
        done
        [ "$sp_ok" = 1 ] || { echo "iter $k FATAL: self-play harvest failed twice" | tee -a "$LOG"; exit 1; }
        touch "$RUN/sp_$k.HARVESTED"
    fi
    if [ -n "$league_pid" ]; then
        wait "$league_pid" || { echo "iter $k FATAL: league harvest failed (see league_$k.log)" | tee -a "$LOG"; exit 1; }
        touch "$RUN/lg_$k.HARVESTED"
    fi

    data="$RUNW/sp_$k.t*.csv;$RUNW/lg_$k.t*.csv"
    if [ "$k" -gt 0 ]; then data="$data;$RUNW/sp_$((k - 1)).t*.csv;$RUNW/lg_$((k - 1)).t*.csv"; fi
    # permanent anchor TAIL (P4b anchor-cliff discipline): seed-quality 1200-sims rows
    data="$data;$RUNW/attn2_boot.t[0-1].csv"
    echo "--- iter $k: train_attn (warm from best, lr 5e-4, aux_w=$AUX_W) ---" | tee -a "$LOG"
    CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_attn.py" --data "$data" --out "$RUNW/attn2_cand_$k.json" \
        --warm "$BESTW" --lr 5e-4 --epochs 2 --aux-dim 14 --aux-weight "$AUX_W" 2>&1 | tee -a "$LOG" || {
        echo "iter $k train CRASHED — retrying once" | tee -a "$LOG"
        CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_attn.py" --data "$data" --out "$RUNW/attn2_cand_$k.json" \
            --warm "$BESTW" --lr 5e-4 --epochs 2 --aux-dim 14 --aux-weight "$AUX_W" 2>&1 | tee -a "$LOG"
    }

    echo "--- iter $k: gates (gpu) ---" | tee -a "$LOG"
    "$CR/attn_export_check.exe" "$RUNW/attn2_cand_$k.json" | tee -a "$LOG"
    reap_gpu_servers
    COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$RUNW/attn2_cand_$k.json" --port 9913 >"$RUN/gpu_gate_c$k.log" 2>&1 &
    gpu_c=$!
    CHILDREN="$CHILDREN $gpu_c"
    COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$BESTW" --port 9914 >"$RUN/gpu_gate_b$k.log" 2>&1 &
    gpu_b=$!
    CHILDREN="$CHILDREN $gpu_b"
    for _ in $(seq 1 30); do
        grep -q "ready" "$RUN/gpu_gate_c$k.log" 2>/dev/null && grep -q "ready" "$RUN/gpu_gate_b$k.log" 2>/dev/null && break
        sleep 2
    done
    g1=$(COC_GPU_ADDR_A=127.0.0.1:9913 COC_GPU_ADDR_B=127.0.0.1:9914 \
        "$CR/gate_coc.exe" "$RUNW/attn2_cand_$k.json:netvalgpu" "$BESTW:netvalgpu" "$GATE_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((37500 + k)) 4 24 stop@0.52 2>>"$RUN/gates_err_a$k.log" | tail -1)
    [ -n "$g1" ] || { echo "iter $k FATAL: g1 produced NO output (see gates_err_a$k.log)" | tee -a "$LOG"; exit 1; }
    echo "iter $k gate(cand-vs-best netval,gpu): $g1" | tee -a "$LOG"
    g3=$(COC_GPU_ADDR_A=127.0.0.1:9913 \
        "$CR/gate_coc.exe" "$RUNW/attn2_cand_$k.json:netvalgpu" "$CHAMP_YARD:netval" "$YARD_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((39500 + k)) 4 24 2>>"$RUN/gates_err_a$k.log" | tail -1 || true)
    [ -n "$g3" ] || echo "iter $k WARNING: yardstick produced NO output (see gates_err_a$k.log)" | tee -a "$LOG"
    echo "iter $k yardstick(cand vs r2-champ @$GATE_SIMS, folded-line baseline ~0.44): $g3" | tee -a "$LOG"
    killtree "$gpu_c"
    killtree "$gpu_b"

    wr=$(echo "$g1" | sed -E 's/.*: ([0-9.]+) \+-.*/\1/')
    if [ -z "$wr" ] || ! awk "BEGIN{exit !($wr >= 0)}" 2>/dev/null; then
        echo "iter $k FATAL: gate produced no parseable win rate ('$g1')" | tee -a "$LOG"
        exit 1
    fi
    if awk "BEGIN{exit !($wr >= 0.52)}"; then
        cp "$RUN/attn2_cand_$k.json" "$BEST"
        cp "$RUN/attn2_cand_$k.json.check" "$BEST.check" 2>/dev/null || true
        echo "iter $k PROMOTED ($wr)" | tee -a "$LOG"
    else
        echo "iter $k kept best ($wr)" | tee -a "$LOG"
    fi
    rm -f "$RUN"/sp_$((k - 2)).t*.csv "$RUN/sp_$((k - 2)).HARVESTED" \
          "$RUN"/lg_$((k - 2)).t*.csv "$RUN/lg_$((k - 2)).HARVESTED" 2>/dev/null || true
    echo $((k + 1)) >"$PROG"
    echo "ITER $k DONE" | tee -a "$LOG"
done
echo "attn2 loop complete at iter $ITERS" | tee -a "$LOG"
