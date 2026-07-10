#!/bin/bash
# P4b ATTENTION netval self-play loop — climb the attention distill out of its
# deficit vs the r2 champion (distill gate baseline: 0.2917 @200v200, seeds 21000).
# Seeds attn_best from the distill net; self-play at SIMS=300 (the proven nv-loop
# operating point) with the GPU sidecar serving the torch twin (attention branch);
# harvest auto-logs token rows (Enc from the model's in_dim) and its startup parity
# guard verifies server==local forward every launch.
#
# Training keeps the DISTILL corpus (attn_boot.t*.csv — champion-quality teacher
# rows) as an anchor for the first ANCHOR_ITERS iters only, then a pure 2-iter
# self-play window (the nv washout lesson: judge the trend only once the window is
# pure self-play). Gates are CPU f32; the FIXED yardstick is the r2 champion at
# equal sims — directly comparable to the 0.2917 distill-gate baseline.
#
#   RUN=/c/Users/Forrest/coc_run_attn ITERS=8 GAMES=2500 SIMS=300 bash coc-core/tools/loop_coc_attn.sh
set -e -o pipefail
RUN=${RUN:-/c/Users/Forrest/coc_run_attn}
RUNW=$(cygpath -m "$RUN")
CR=${CR:-/c/Users/Forrest/forrestm_projects/coc-core/target-perf/release}
TOOLS=${TOOLS:-/c/Users/Forrest/forrestm_projects/coc-core/tools}
SEED_NET=${SEED_NET:-$RUN/attn_distill.json}
CHAMP_YARD=${CHAMP_YARD:-C:/Users/Forrest/coc_run_r2/pv_ship_r2.json}
ITERS=${ITERS:-8}
GAMES=${GAMES:-2500}
SIMS=${SIMS:-300}
ANCHOR_ITERS=${ANCHOR_ITERS:-3}
GPU_BATCH=${GPU_BATCH:-64}   # K=128 MEASURED SLOWER even at SIMS=300 (40-48k vs 70k+ evals/s,
                             # CPU 91%/GPU 41%): 1280 in-flight trees thrash the CPU CACHE —
                             # the K warning isn't just RAM. 64 is the sweet spot.
GPU_PORT=${GPU_PORT:-9911}
GATE_PAIRS=${GATE_PAIRS:-120}
GATE_SIMS=${GATE_SIMS:-200}
PROBE_PAIRS=${PROBE_PAIRS:-60}
YARD_PAIRS=${YARD_PAIRS:-60}
THREADS=${THREADS:-10}
LOG=$RUN/loop_log.txt
BEST=$RUN/attn_best.json
BESTW=$RUNW/attn_best.json
PROG=$RUN/progress_attn

mkdir -p "$RUN"
[ -f "$BEST" ] || { cp "$SEED_NET" "$BEST" && cp "$SEED_NET.check" "$BEST.check"; }
start=$(cat "$PROG" 2>/dev/null || echo 0)
echo "=== loop_coc_attn from iter $start / $ITERS (games=$GAMES sims=$SIMS seed=$SEED_NET) ===" | tee -a "$LOG"

for ((k = start; k < ITERS; k++)); do
    if [ -f "$RUN/asp_$k.HARVESTED" ]; then
        echo "--- iter $k: attention self-play already complete, skipping ---" | tee -a "$LOG"
    else
        echo "--- iter $k: attention netval self-play (gpu sidecar) ---" | tee -a "$LOG"
        COC_GPU_PAD=$((GPU_BATCH * 2)) python "$TOOLS/gpu_server.py" "$BESTW" --port "$GPU_PORT" >"$RUN/gpu_server_a$k.log" 2>&1 &
        gpu_pid=$!
        for _ in $(seq 1 30); do
            grep -q "ready" "$RUN/gpu_server_a$k.log" 2>/dev/null && break
            sleep 2
        done
        grep -q "ready" "$RUN/gpu_server_a$k.log" || { echo "iter $k FATAL: gpu server never came up" | tee -a "$LOG"; exit 1; }
        seed=$((8000000 + k * 100000))
        COC_GPU_ADDR="127.0.0.1:$GPU_PORT" "$CR/harvest_boot.exe" "$RUNW/asp_$k" "$GAMES" "$SIMS" 20 \
            "$seed" "$THREADS" "$BESTW" netvalgpu "$GPU_BATCH" 2>>"$LOG"
        kill "$gpu_pid" 2>/dev/null || true
        touch "$RUN/asp_$k.HARVESTED"
    fi

    data="$RUNW/asp_$k.t*.csv"
    if [ "$k" -gt 0 ]; then data="$data;$RUNW/asp_$((k - 1)).t*.csv"; fi
    if [ "$k" -lt "$ANCHOR_ITERS" ]; then data="$data;$RUNW/attn_boot.t*.csv"; fi
    echo "--- iter $k: train_attn (warm from best) ---" | tee -a "$LOG"
    python "$TOOLS/train_attn.py" --data "$data" --out "$RUNW/attn_cand_$k.json" \
        --warm "$BESTW" --epochs 2 2>&1 | tee -a "$LOG"

    echo "--- iter $k: gates ---" | tee -a "$LOG"
    "$CR/attn_export_check.exe" "$RUNW/attn_cand_$k.json" | tee -a "$LOG"
    g1=$("$CR/gate_coc.exe" "$RUNW/attn_cand_$k.json:netval" "$BESTW:netval" "$GATE_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((7500 + k)) "$THREADS" 2>/dev/null | tail -1)
    echo "iter $k gate(cand-vs-best netval): $g1" | tee -a "$LOG"
    g2=$("$CR/gate_coc.exe" "$RUNW/attn_cand_$k.json:netval" "$RUNW/attn_cand_$k.json:hybrid" "$PROBE_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((8500 + k)) "$THREADS" 2>/dev/null | tail -1 || true)
    echo "iter $k probe(netval vs hybrid, same net): $g2" | tee -a "$LOG"
    g3=$("$CR/gate_coc.exe" "$RUNW/attn_cand_$k.json:netval" "$CHAMP_YARD:netval" "$YARD_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((9500 + k)) "$THREADS" 2>/dev/null | tail -1 || true)
    echo "iter $k yardstick(cand vs r2-champ @$GATE_SIMS, baseline 0.2917): $g3" | tee -a "$LOG"

    wr=$(echo "$g1" | sed -E 's/.*: ([0-9.]+) \+-.*/\1/')
    if [ -z "$wr" ] || ! awk "BEGIN{exit !($wr >= 0)}" 2>/dev/null; then
        echo "iter $k FATAL: gate produced no parseable win rate ('$g1')" | tee -a "$LOG"
        exit 1
    fi
    if awk "BEGIN{exit !($wr >= 0.52)}"; then
        cp "$RUN/attn_cand_$k.json" "$BEST"
        cp "$RUN/attn_cand_$k.json.check" "$BEST.check" 2>/dev/null || true
        echo "iter $k PROMOTED ($wr)" | tee -a "$LOG"
    else
        echo "iter $k kept best ($wr)" | tee -a "$LOG"
    fi
    rm -f "$RUN"/asp_$((k - 2)).t*.csv "$RUN/asp_$((k - 2)).HARVESTED" 2>/dev/null || true
    echo $((k + 1)) >"$PROG"
    echo "ITER $k DONE" | tee -a "$LOG"
done
echo "attn loop complete at iter $ITERS" | tee -a "$LOG"
