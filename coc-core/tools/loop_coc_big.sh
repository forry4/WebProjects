#!/bin/bash
# BIG-MLP consolidation loop (capacity bet, 2026-07-11). Seeds from pv_big.json
# (trunk 1024/512, fresh-distilled from the champion's 6000-sim PCR corpus + the
# stager league — gates 0.4958 vs champion at equal sims, i.e. the distill TIES
# the teacher, ahead of every distill precedent). This loop is the proven
# converter (nv +7pp, hs +4pp, r2 +5pp): netval self-play + train + gate.
#
# TWO deliberate additions over loop_coc_attn.sh:
#  * IN-LOOP STAGER LEAGUE: each iter also harvests LEAGUE_GAMES champion-vs-
#    stager games (vsearch::stager_bias w=0.6 — beats the plain net 0.58 at this
#    config) on the CPU, CONCURRENT with the GPU self-play harvest. Mirror
#    self-play keeps staged assets symmetric so the value head never learns
#    their price (the 2026-07-11 human-games mining: the user wins phase E
#    29-61 while the bot leads through D); the league keeps injecting
#    asymmetric staged positions with honest outcome labels as the net evolves
#    (a single 19% distill dose measurably did NOT shift style).
#  * PERMANENT ANCHOR TAIL + lr 5e-4 from iter 0 (the attention iter-3 crater
#    lesson, pre-applied: 4x capacity drifts faster than the small MLP that
#    survived the anchor cliff). Tail = 2 cap files (teacher calibration) + 2
#    league files (staging calibration).
#
#   bash coc-core/tools/loop_coc_big.sh          # RUN=/c/Users/Forrest/coc_run_cap
set -e -o pipefail
RUN=${RUN:-/c/Users/Forrest/coc_run_cap}
RUNW=$(cygpath -m "$RUN")
CR=${CR:-/c/Users/Forrest/forrestm_projects/coc-core/target-perf/release}
CRB=${CRB:-/c/Users/Forrest/forrestm_projects/coc-core/target/release}   # bridge-feature bins (stager league)
TOOLS=${TOOLS:-/c/Users/Forrest/forrestm_projects/coc-core/tools}
SEED_NET=${SEED_NET:-$RUN/pv_big.json}
CHAMP_YARD=${CHAMP_YARD:-C:/Users/Forrest/coc_run_r2/pv_ship_r2.json}
ITERS=${ITERS:-8}
GAMES=${GAMES:-2000}
LEAGUE_GAMES=${LEAGUE_GAMES:-400}
LEAGUE_SIMS=${LEAGUE_SIMS:-300}
LEAGUE_THREADS=${LEAGUE_THREADS:-6}
STAGER_W=${STAGER_W:-0.6}
SIMS=${SIMS:-300}
GPU_BATCH=${GPU_BATCH:-64}
GPU_PORT=${GPU_PORT:-9911}
GATE_PAIRS=${GATE_PAIRS:-120}
GATE_SIMS=${GATE_SIMS:-200}
PROBE_PAIRS=${PROBE_PAIRS:-60}
YARD_PAIRS=${YARD_PAIRS:-60}
THREADS=${THREADS:-10}
LOG=$RUN/loop_big_log.txt
BEST=$RUN/big_best.json
BESTW=$RUNW/big_best.json
PROG=$RUN/progress_big

mkdir -p "$RUN"

# ── SINGLETON + PRE-FLIGHT (the 2026-07-10 triple-race hardening) ──
LOCKDIR=$RUN/loop.lock
if mkdir "$LOCKDIR" 2>/dev/null; then
    echo $$ >"$LOCKDIR/pid"
else
    oldpid=$(cat "$LOCKDIR/pid" 2>/dev/null || true)
    if [ -n "$oldpid" ] && kill -0 "$oldpid" 2>/dev/null; then
        echo "FATAL: loop instance pid $oldpid is ALIVE — refusing to double-launch" | tee -a "$LOG"
        exit 1
    fi
    echo "stale lock (pid ${oldpid:-?} dead) — taking over" | tee -a "$LOG"
    echo $$ >"$LOCKDIR/pid"
fi
CHILDREN=""
# THE VENV-REDIRECTOR KILL GAP (2026-07-11 iter-1 OOM incident — do not regress):
# on Windows, the venv's python.exe is a LAUNCHER that spawns the real
# interpreter as a CHILD. A plain `kill $!` kills only the launcher and ORPHANS
# the real torch server — which is how gpu_servers accumulated all campaign
# (the six-orphan pileup, the port double-bind, and the iter-1 CUDA OOM: two
# orphaned server contexts + the live one exhausted VRAM mid-request).
# killtree kills the whole Windows process tree; reap_gpu_servers sweeps any
# survivor by command line before every server launch.
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
    echo "FATAL: a harvest_boot.exe is already running — a prior run's straggler; clean up first" | tee -a "$LOG"
    exit 1
fi
for port in "$GPU_PORT" 9913 9914; do
    if netstat -ano 2>/dev/null | grep -q ":$port .*LISTENING"; then
        echo "FATAL: port $port already bound — a gpu_server is lingering; clean up first" | tee -a "$LOG"
        exit 1
    fi
done

[ -f "$BEST" ] || { cp "$SEED_NET" "$BEST" && cp "$SEED_NET.check" "$BEST.check"; }
start=$(cat "$PROG" 2>/dev/null || echo 0)
echo "=== loop_coc_big from iter $start / $ITERS (games=$GAMES+$LEAGUE_GAMES-league sims=$SIMS seed=$SEED_NET) ===" | tee -a "$LOG"

for ((k = start; k < ITERS; k++)); do
    # CPU stager league runs CONCURRENT with the GPU self-play harvest —
    # disjoint resources (league = sequential f32 netval, no sidecar).
    league_pid=""
    if [ -f "$RUN/lg_$k.HARVESTED" ]; then
        echo "--- iter $k: league already complete, skipping ---" | tee -a "$LOG"
    else
        echo "--- iter $k: stager league (cpu, w=$STAGER_W, $LEAGUE_GAMES g @$LEAGUE_SIMS) ---" | tee -a "$LOG"
        lseed=$((14000000 + k * 100000))
        "$CRB/harvest_boot.exe" "$RUNW/lg_$k" "$LEAGUE_GAMES" "$LEAGUE_SIMS" 20 \
            "$lseed" "$LEAGUE_THREADS" "$BESTW" netval 1 v1 "stager@$STAGER_W" >>"$RUN/league_$k.log" 2>&1 &
        league_pid=$!
        CHILDREN="$CHILDREN $league_pid"
    fi

    if [ -f "$RUN/sp_$k.HARVESTED" ]; then
        echo "--- iter $k: self-play already complete, skipping ---" | tee -a "$LOG"
    else
        echo "--- iter $k: netval self-play (gpu sidecar) ---" | tee -a "$LOG"
        sp_ok=0
        for attempt in 1 2; do
            reap_gpu_servers
            COC_GPU_PAD=$((GPU_BATCH * 2)) python "$TOOLS/gpu_server.py" "$BESTW" --port "$GPU_PORT" >"$RUN/gpu_server_b$k.log" 2>&1 &
            gpu_pid=$!
            CHILDREN="$CHILDREN $gpu_pid"
            for _ in $(seq 1 30); do
                grep -q "ready" "$RUN/gpu_server_b$k.log" 2>/dev/null && break
                sleep 2
            done
            grep -q "ready" "$RUN/gpu_server_b$k.log" || { echo "iter $k FATAL: gpu server never came up" | tee -a "$LOG"; exit 1; }
            seed=$((15000000 + k * 100000))
            if COC_GPU_ADDR="127.0.0.1:$GPU_PORT" "$CR/harvest_boot.exe" "$RUNW/sp_$k" "$GAMES" "$SIMS" 20 \
                "$seed" "$THREADS" "$BESTW" netvalgpu "$GPU_BATCH" 2>>"$LOG"; then
                sp_ok=1
                killtree "$gpu_pid"
                break
            fi
            echo "iter $k self-play harvest FAILED (attempt $attempt) — reaping servers and retrying" | tee -a "$LOG"
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
    # permanent anchor TAIL (crater discipline pre-applied): teacher + staging calibration
    data="$data;$RUNW/cap_boot.t[0-1].csv;$RUNW/league_boot.t[0-1].csv"
    echo "--- iter $k: train_pv (warm from best, lr 5e-4) ---" | tee -a "$LOG"
    CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$data" --out "$RUNW/big_cand_$k.json" \
        --warm "$BESTW" --lr 5e-4 --epochs 2 2>&1 | tee -a "$LOG" || {
        echo "iter $k train CRASHED — retrying once" | tee -a "$LOG"
        CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_pv.py" --data "$data" --out "$RUNW/big_cand_$k.json" \
            --warm "$BESTW" --lr 5e-4 --epochs 2 2>&1 | tee -a "$LOG"
    }

    echo "--- iter $k: gates (gpu) ---" | tee -a "$LOG"
    "$CR/net_export_check.exe" "$RUNW/big_cand_$k.json" | tee -a "$LOG"
    reap_gpu_servers
    COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$RUNW/big_cand_$k.json" --port 9913 >"$RUN/gpu_gate_c$k.log" 2>&1 &
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
        "$CR/gate_coc.exe" "$RUNW/big_cand_$k.json:netvalgpu" "$BESTW:netvalgpu" "$GATE_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((17500 + k)) 4 24 2>>"$RUN/gates_err_b$k.log" | tail -1)
    [ -n "$g1" ] || { echo "iter $k FATAL: g1 produced NO output (see gates_err_b$k.log)" | tee -a "$LOG"; exit 1; }
    echo "iter $k gate(cand-vs-best netval,gpu): $g1" | tee -a "$LOG"
    if [ $((k % 3)) -eq 0 ]; then
        g2=$(COC_GPU_ADDR_A=127.0.0.1:9913 \
            "$CR/gate_coc.exe" "$RUNW/big_cand_$k.json:netvalgpu" "$RUNW/big_cand_$k.json:hybrid" "$PROBE_PAIRS" \
            "$GATE_SIMS" "$GATE_SIMS" $((18500 + k)) 4 24 2>>"$RUN/gates_err_b$k.log" | tail -1 || true)
        echo "iter $k probe(netval vs hybrid, same net): $g2" | tee -a "$LOG"
    else
        echo "iter $k probe: skipped (runs every 3rd iter)" | tee -a "$LOG"
    fi
    g3=$(COC_GPU_ADDR_A=127.0.0.1:9913 \
        "$CR/gate_coc.exe" "$RUNW/big_cand_$k.json:netvalgpu" "$CHAMP_YARD:netval" "$YARD_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((19500 + k)) 4 24 2>>"$RUN/gates_err_b$k.log" | tail -1 || true)
    [ -n "$g3" ] || echo "iter $k WARNING: yardstick produced NO output (see gates_err_b$k.log)" | tee -a "$LOG"
    echo "iter $k yardstick(cand vs r2-champ @$GATE_SIMS, distill baseline 0.4958): $g3" | tee -a "$LOG"
    killtree "$gpu_c"
    killtree "$gpu_b"

    wr=$(echo "$g1" | sed -E 's/.*: ([0-9.]+) \+-.*/\1/')
    if [ -z "$wr" ] || ! awk "BEGIN{exit !($wr >= 0)}" 2>/dev/null; then
        echo "iter $k FATAL: gate produced no parseable win rate ('$g1')" | tee -a "$LOG"
        exit 1
    fi
    if awk "BEGIN{exit !($wr >= 0.52)}"; then
        cp "$RUN/big_cand_$k.json" "$BEST"
        cp "$RUN/big_cand_$k.json.check" "$BEST.check" 2>/dev/null || true
        echo "iter $k PROMOTED ($wr)" | tee -a "$LOG"
    else
        echo "iter $k kept best ($wr)" | tee -a "$LOG"
    fi
    rm -f "$RUN"/sp_$((k - 2)).t*.csv "$RUN/sp_$((k - 2)).HARVESTED" \
          "$RUN"/lg_$((k - 2)).t*.csv "$RUN/lg_$((k - 2)).HARVESTED" 2>/dev/null || true
    echo $((k + 1)) >"$PROG"
    echo "ITER $k DONE" | tee -a "$LOG"
done
echo "big loop complete at iter $ITERS" | tee -a "$LOG"
