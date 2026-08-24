#!/bin/bash
# RUNG-2 combined campaign: PCR x deeper-full-cap targets x GPU harvest, seeded
# from the hs-loop winner (pv_cand_3, fresh-seed 0.542/0.548/0.521 vs champion).
# PCR (KataGo playout-cap randomization, 250@200 = 25% of decisions at the FULL
# 2000-sim cap producing policy rows, 75% at 200 sims producing value-only rows)
# buys ~2x the games per hour: policy targets get DEEPER than the hs loop's 1200
# while the value head sees twice the outcomes. Gates stay CPU f32; the trainer
# carries the PCR patch (CE normalized by policy-row count, top1 masked).
#
#   RUN=/c/Users/Forrest/coc_run_r2 ITERS=8 GAMES=4000 SIMS=2000 bash coc-core/tools/loop_coc_r2.sh
set -e -o pipefail
RUN=${RUN:-/c/Users/Forrest/coc_run_r2}
RUNW=$(cygpath -m "$RUN")
CR=${CR:-/c/Users/Forrest/forrestm_projects/coc-core/target/release}
TOOLS=${TOOLS:-/c/Users/Forrest/forrestm_projects/coc-core/tools}
SEED_NET=${SEED_NET:-/c/Users/Forrest/coc_run_hs/pv_cand_3.json}
ITERS=${ITERS:-8}
GAMES=${GAMES:-4000}
SIMS=${SIMS:-2000}
PCR=${PCR:-250@200}
GATE_PAIRS=${GATE_PAIRS:-120}
GATE_SIMS=${GATE_SIMS:-200}
PROBE_PAIRS=${PROBE_PAIRS:-60}
YARD_PAIRS=${YARD_PAIRS:-50}
YARD_SIMS=${YARD_SIMS:-512}
YARD_OPP_SIMS=${YARD_OPP_SIMS:-2000}
THREADS=${THREADS:-10}
GPU_BATCH=${GPU_BATCH:-64}
GPU_PORT=${GPU_PORT:-9911}
LOG=$RUN/loop_log.txt
BEST=$RUN/pv_best.json
BESTW=$RUNW/pv_best.json
PROG=$RUN/progress_r2

mkdir -p "$RUN"
[ -f "$BEST" ] || { cp "$SEED_NET" "$BEST" && cp "$SEED_NET.check" "$BEST.check"; }
start=$(cat "$PROG" 2>/dev/null || echo 0)
echo "=== loop_coc_r2 from iter $start / $ITERS (games=$GAMES sims=$SIMS pcr=$PCR seed=$SEED_NET) ===" | tee -a "$LOG"

for ((k = start; k < ITERS; k++)); do
    if [ -f "$RUN/sp_$k.HARVESTED" ]; then
        echo "--- iter $k: r2 self-play already complete, skipping ---" | tee -a "$LOG"
    else
        echo "--- iter $k: r2 netval self-play (gpu, pcr $PCR) ---" | tee -a "$LOG"
        python "$TOOLS/gpu_server.py" "$BESTW" --port "$GPU_PORT" >"$RUN/gpu_server_$k.log" 2>&1 &
        gpu_pid=$!
        for _ in $(seq 1 30); do
            grep -q "ready" "$RUN/gpu_server_$k.log" 2>/dev/null && break
            sleep 2
        done
        grep -q "ready" "$RUN/gpu_server_$k.log" || { echo "iter $k FATAL: gpu server never came up" | tee -a "$LOG"; exit 1; }
        seed=$((6000000 + k * 100000))
        COC_GPU_ADDR="127.0.0.1:$GPU_PORT" "$CR/harvest_boot.exe" "$RUNW/sp_$k" "$GAMES" "$SIMS" 20 \
            "$seed" "$THREADS" "$BESTW" netvalgpu "$GPU_BATCH" v1 "$PCR" 2>>"$LOG"
        kill "$gpu_pid" 2>/dev/null || true
        touch "$RUN/sp_$k.HARVESTED"
    fi

    data="$RUNW/sp_$k.t*.csv"
    if [ "$k" -gt 0 ]; then data="$data;$RUNW/sp_$((k - 1)).t*.csv"; fi
    echo "--- iter $k: train (warm from best) ---" | tee -a "$LOG"
    python "$TOOLS/train_pv.py" --data "$data" --out "$RUNW/pv_cand_$k.json" \
        --warm "$BESTW" --epochs 2 2>&1 | tee -a "$LOG"

    echo "--- iter $k: gates ---" | tee -a "$LOG"
    "$CR/net_export_check.exe" "$RUNW/pv_cand_$k.json" | tee -a "$LOG"
    g1=$("$CR/gate_coc.exe" "$RUNW/pv_cand_$k.json:netval" "$BESTW:netval" "$GATE_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((7700 + k)) "$THREADS" 2>/dev/null | tail -1)
    echo "iter $k gate(cand-vs-best netval): $g1" | tee -a "$LOG"
    g2=$("$CR/gate_coc.exe" "$RUNW/pv_cand_$k.json:netval" "$RUNW/pv_cand_$k.json:hybrid" "$PROBE_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((8700 + k)) "$THREADS" 2>/dev/null | tail -1)
    echo "iter $k probe(netval vs hybrid, same net): $g2" | tee -a "$LOG"
    g3=$("$CR/gate_coc.exe" "$RUNW/pv_cand_$k.json:netval" SCAFFOLD "$YARD_PAIRS" "$YARD_SIMS" "$YARD_OPP_SIMS" \
        $((9700 + k)) "$THREADS" 2>/dev/null | tail -1)
    echo "iter $k yardstick(netval@$YARD_SIMS vs scaffold@$YARD_OPP_SIMS): $g3" | tee -a "$LOG"

    wr=$(echo "$g1" | sed -E 's/.*: ([0-9.]+) \+-.*/\1/')
    if [ -z "$wr" ] || ! awk "BEGIN{exit !($wr >= 0)}" 2>/dev/null; then
        echo "iter $k FATAL: gate produced no parseable win rate ('$g1')" | tee -a "$LOG"
        exit 1
    fi
    if awk "BEGIN{exit !($wr >= 0.52)}"; then
        cp "$RUN/pv_cand_$k.json" "$BEST"
        cp "$RUN/pv_cand_$k.json.check" "$BEST.check" 2>/dev/null || true
        echo "iter $k PROMOTED ($wr)" | tee -a "$LOG"
    else
        echo "iter $k kept best ($wr)" | tee -a "$LOG"
    fi
    rm -f "$RUN"/sp_$((k - 2)).t*.csv "$RUN/sp_$((k - 2)).HARVESTED" 2>/dev/null || true
    echo $((k + 1)) >"$PROG"
    echo "ITER $k DONE" | tee -a "$LOG"
done
echo "r2 loop complete at iter $ITERS" | tee -a "$LOG"
