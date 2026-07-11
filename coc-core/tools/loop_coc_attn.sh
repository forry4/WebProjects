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

# ── SINGLETON + PRE-FLIGHT (2026-07-10 incident: three racing loop instances —
# doubled gates, port fights, and two trainers sharing 6GB VRAM = the likely
# cublas crashes). The lock refuses a second launch; the trap kills children on
# any NORMAL/crash exit; the pre-flight catches stragglers a HARD kill (TaskStop
# doesn't cascade on Windows) left behind, so the NEXT launch fails loudly
# instead of racing them. ──
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
cleanup() {
    for p in $CHILDREN; do kill "$p" 2>/dev/null || true; done
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
echo "=== loop_coc_attn from iter $start / $ITERS (games=$GAMES sims=$SIMS seed=$SEED_NET) ===" | tee -a "$LOG"

for ((k = start; k < ITERS; k++)); do
    if [ -f "$RUN/asp_$k.HARVESTED" ]; then
        echo "--- iter $k: attention self-play already complete, skipping ---" | tee -a "$LOG"
    else
        echo "--- iter $k: attention netval self-play (gpu sidecar) ---" | tee -a "$LOG"
        COC_GPU_PAD=$((GPU_BATCH * 2)) python "$TOOLS/gpu_server.py" "$BESTW" --port "$GPU_PORT" >"$RUN/gpu_server_a$k.log" 2>&1 &
        gpu_pid=$!
        CHILDREN="$CHILDREN $gpu_pid"
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
    lr=1e-3
    if [ "$k" -lt "$ANCHOR_ITERS" ]; then
        data="$data;$RUNW/attn_boot.t*.csv"
    else
        # ITER-3 CRATER (2026-07-10): the first fully-anchor-free train collapsed
        # BOTH heads onto the self-play distribution — gate 0.2667 (margin −25),
        # yardstick 0.4333→0.2083, probe netval-vs-hybrid 0.55→0.46 — while val
        # AUC/top1 hit record HIGHS (the val split shares the collapsed
        # distribution, so the metrics can't see it). The MLP nv loop survived
        # this same cliff; the higher-capacity attention net does not. Fix: keep
        # a ~22%-of-mix anchor TAIL (3 of 10 boot files — champion-quality
        # 1200-sims rows tether BOTH heads' calibration) + halve the lr (warm
        # fine-tune precedent 5e-4). Do NOT return this to a hard anchor cliff.
        data="$data;$RUNW/attn_boot.t[0-2].csv"
        lr=5e-4
    fi
    echo "--- iter $k: train_attn (warm from best, lr $lr) ---" | tee -a "$LOG"
    # CUDA_LAUNCH_BLOCKING: three cublas-backward crashes on 2026-07-10 with a
    # misattributed async op — sync reporting captures the TRUE op if it recurs.
    # Retry once: a transient GPU hiccup self-heals; a deterministic crash
    # fails twice and stops the loop with two full tracebacks in the log.
    CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_attn.py" --data "$data" --out "$RUNW/attn_cand_$k.json" \
        --warm "$BESTW" --lr "$lr" --epochs 2 2>&1 | tee -a "$LOG" || {
        echo "iter $k train CRASHED — retrying once" | tee -a "$LOG"
        CUDA_LAUNCH_BLOCKING=1 python "$TOOLS/train_attn.py" --data "$data" --out "$RUNW/attn_cand_$k.json" \
            --warm "$BESTW" --lr "$lr" --epochs 2 2>&1 | tee -a "$LOG"
    }

    echo "--- iter $k: gates (gpu) ---" | tee -a "$LOG"
    "$CR/attn_export_check.exe" "$RUNW/attn_cand_$k.json" | tee -a "$LOG"
    # GPU-served gates: the attention forwards go through graphed sidecars
    # (cand on 9913, best on 9914). g1 is both-sides-gpu (shared arithmetic =
    # unbiased, the int8 screening discipline); final SHIP gates stay CPU f32.
    # Gate threads drop to 4 with batch 24 so each thread's lockstep is big
    # enough to feed useful GPU batches.
    COC_GPU_PAD=48 python "$TOOLS/gpu_server.py" "$RUNW/attn_cand_$k.json" --port 9913 >"$RUN/gpu_gate_c$k.log" 2>&1 &
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
        "$CR/gate_coc.exe" "$RUNW/attn_cand_$k.json:netvalgpu" "$BESTW:netvalgpu" "$GATE_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((7500 + k)) 4 24 2>>"$RUN/gates_err_$k.log" | tail -1)
    [ -n "$g1" ] || { echo "iter $k FATAL: g1 produced NO output (see gates_err_$k.log)" | tee -a "$LOG"; exit 1; }
    echo "iter $k gate(cand-vs-best netval,gpu): $g1" | tee -a "$LOG"
    if [ $((k % 3)) -eq 0 ]; then
        # the value-head-vs-heuristic probe answered its question at iter 0
        # (0.55, value head ahead) — every 3rd iter is enough to watch it
        g2=$(COC_GPU_ADDR_A=127.0.0.1:9913 \
            "$CR/gate_coc.exe" "$RUNW/attn_cand_$k.json:netvalgpu" "$RUNW/attn_cand_$k.json:hybrid" "$PROBE_PAIRS" \
            "$GATE_SIMS" "$GATE_SIMS" $((8500 + k)) 4 24 2>>"$RUN/gates_err_$k.log" | tail -1 || true)
        echo "iter $k probe(netval vs hybrid, same net): $g2" | tee -a "$LOG"
    else
        echo "iter $k probe: skipped (runs every 3rd iter)" | tee -a "$LOG"
    fi
    g3=$(COC_GPU_ADDR_A=127.0.0.1:9913 \
        "$CR/gate_coc.exe" "$RUNW/attn_cand_$k.json:netvalgpu" "$CHAMP_YARD:netval" "$YARD_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((9500 + k)) 4 24 2>>"$RUN/gates_err_$k.log" | tail -1 || true)
    [ -n "$g3" ] || echo "iter $k WARNING: yardstick produced NO output (see gates_err_$k.log)" | tee -a "$LOG"
    echo "iter $k yardstick(cand vs r2-champ @$GATE_SIMS, baseline 0.2917): $g3" | tee -a "$LOG"
    kill "$gpu_c" "$gpu_b" 2>/dev/null || true

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
