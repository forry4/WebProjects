#!/bin/bash
# P4 ratchet (loop_attn.sh pattern): HYBRID self-play (net prior + rollout value —
# the config that beats the scaffold at equal sims) -> train both heads (warm from
# best) -> paired-CRN gate -> greedy ratchet. Per iter also probes (a) pure-net
# leaf vs hybrid (the value-head takeover signal: switch self-play to pv mode once
# it wins) and (b) the scaffold@2000 yardstick. Resumable via progress file.
#
#   bash coc-core/tools/loop_coc.sh            (from the repo root)
#   ITERS=8 GAMES=2000 SIMS=400 bash coc-core/tools/loop_coc.sh
set -e
RUN=${RUN:-/c/Users/Forrest/coc_run}
CR=${CR:-/c/Users/Forrest/forrestm_projects/coc-core/target/release}
TOOLS=${TOOLS:-/c/Users/Forrest/forrestm_projects/coc-core/tools}
ITERS=${ITERS:-8}
GAMES=${GAMES:-2000}
SIMS=${SIMS:-400}
GATE_PAIRS=${GATE_PAIRS:-60}
GATE_SIMS=${GATE_SIMS:-200}
THREADS=${THREADS:-10}
LOG=$RUN/loop_log.txt
BEST=$RUN/pv_best.json
PROG=$RUN/progress_coc

[ -f "$BEST" ] || cp "$RUN/pv_boot.json" "$BEST"
start=$(cat "$PROG" 2>/dev/null || echo 0)
echo "=== loop_coc from iter $start / $ITERS (games=$GAMES sims=$SIMS) ===" | tee -a "$LOG"

for ((k = start; k < ITERS; k++)); do
    echo "--- iter $k: self-play ---" | tee -a "$LOG"
    seed=$((100000 + k * 100000))
    "$CR/harvest_boot.exe" "$RUN/sp_$k" "$GAMES" "$SIMS" 20 "$seed" "$THREADS" "$BEST" hybrid \
        2>>"$LOG"

    data="$RUN/sp_$k.t*.csv"
    if [ "$k" -gt 0 ]; then data="$data;$RUN/sp_$((k - 1)).t*.csv"; else data="$data;$RUN/boot.t0.csv;$RUN/boot.t1.csv"; fi
    echo "--- iter $k: train (warm from best) ---" | tee -a "$LOG"
    python "$TOOLS/train_pv.py" --data "$data" --out "$RUN/pv_cand_$k.json" \
        --warm "$BEST" --epochs 2 2>&1 | tee -a "$LOG"

    echo "--- iter $k: gates ---" | tee -a "$LOG"
    "$CR/net_export_check.exe" "$RUN/pv_cand_$k.json" | tee -a "$LOG"
    g1=$("$CR/gate_coc.exe" "$RUN/pv_cand_$k.json:hybrid" "$BEST:hybrid" "$GATE_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((7000 + k)) "$THREADS" 2>/dev/null | tail -1)
    echo "iter $k gate(cand-vs-best hybrid): $g1" | tee -a "$LOG"
    g2=$("$CR/gate_coc.exe" "$RUN/pv_cand_$k.json" "$RUN/pv_cand_$k.json:hybrid" 40 \
        "$GATE_SIMS" "$GATE_SIMS" $((8000 + k)) "$THREADS" 2>/dev/null | tail -1)
    echo "iter $k probe(pure-pv vs hybrid): $g2" | tee -a "$LOG"
    g3=$("$CR/gate_coc.exe" "$RUN/pv_cand_$k.json:hybrid" SCAFFOLD 40 512 2000 \
        $((9000 + k)) "$THREADS" 2>/dev/null | tail -1)
    echo "iter $k yardstick(hybrid@512 vs scaffold@2000): $g3" | tee -a "$LOG"

    wr=$(echo "$g1" | sed -E 's/.*: ([0-9.]+) \+-.*/\1/')
    if awk "BEGIN{exit !($wr >= 0.52)}"; then
        cp "$RUN/pv_cand_$k.json" "$BEST"
        cp "$RUN/pv_cand_$k.json.check" "$BEST.check" 2>/dev/null || true
        echo "iter $k PROMOTED ($wr)" | tee -a "$LOG"
    else
        echo "iter $k kept best ($wr)" | tee -a "$LOG"
    fi
    # keep disk bounded: drop self-play data older than the training window
    rm -f "$RUN"/sp_$((k - 2)).t*.csv 2>/dev/null || true
    echo $((k + 1)) >"$PROG"
    echo "ITER $k DONE" | tee -a "$LOG"
done
echo "loop complete at iter $ITERS" | tee -a "$LOG"
