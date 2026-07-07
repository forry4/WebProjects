#!/bin/bash
# NETVAL self-play ratchet — the structural lever the hybrid ratchet lacked. The
# hybrid loop BENCHED the value head (rollout did the eval), so self-play never
# improved it and the ratchet plateaued. Here self-play + the gate BOTH use the
# NETVAL leaf (net prior + 20-step rollout + net VALUE at truncation), so training
# the value head on netval-self-play outcomes improves it WHERE IT IS USED.
#
#   RUN=/c/Users/Forrest/coc_run_nv ITERS=6 GAMES=2000 SIMS=300 bash coc-core/tools/loop_coc_netval.sh
# netval leaf is ~2x the hybrid leaf (extra net forward), so SIMS default is lower.
set -e -o pipefail
RUN=${RUN:-/c/Users/Forrest/coc_run_nv}
RUNW=$(cygpath -m "$RUN")
CR=${CR:-/c/Users/Forrest/forrestm_projects/coc-core/target/release}
TOOLS=${TOOLS:-/c/Users/Forrest/forrestm_projects/coc-core/tools}
ITERS=${ITERS:-6}
GAMES=${GAMES:-2000}
SIMS=${SIMS:-300}
GATE_PAIRS=${GATE_PAIRS:-80}
GATE_SIMS=${GATE_SIMS:-200}
PROBE_PAIRS=${PROBE_PAIRS:-60}
YARD_PAIRS=${YARD_PAIRS:-50}
YARD_SIMS=${YARD_SIMS:-512}
YARD_OPP_SIMS=${YARD_OPP_SIMS:-2000}
THREADS=${THREADS:-10}
LOG=$RUN/loop_log.txt
BEST=$RUN/pv_best.json
BESTW=$RUNW/pv_best.json
PROG=$RUN/progress_coc

mkdir -p "$RUN"
# Seed the netval run from the deployed bootstrap net (the ratchet found nothing
# better; netval's gain is the leaf, so we retrain the SAME net under netval play).
[ -f "$RUN/pv_boot.json" ] || cp /c/Users/Forrest/coc_run/pv_boot.json "$RUN/pv_boot.json"
[ -f "$BEST" ] || cp "$RUN/pv_boot.json" "$BEST"
start=$(cat "$PROG" 2>/dev/null || echo 0)
echo "=== loop_coc_netval from iter $start / $ITERS (games=$GAMES sims=$SIMS) ===" | tee -a "$LOG"

for ((k = start; k < ITERS; k++)); do
    if [ -f "$RUN/sp_$k.HARVESTED" ]; then
        echo "--- iter $k: netval self-play already complete, skipping ---" | tee -a "$LOG"
    else
        echo "--- iter $k: netval self-play ---" | tee -a "$LOG"
        seed=$((200000 + k * 100000))
        "$CR/harvest_boot.exe" "$RUNW/sp_$k" "$GAMES" "$SIMS" 20 "$seed" "$THREADS" "$BESTW" netval \
            2>>"$LOG"
        touch "$RUN/sp_$k.HARVESTED"
    fi

    data="$RUNW/sp_$k.t*.csv"
    if [ "$k" -gt 0 ]; then data="$data;$RUNW/sp_$((k - 1)).t*.csv"; else data="$data;/c/Users/Forrest/coc_run/boot.t0.csv;/c/Users/Forrest/coc_run/boot.t1.csv"; fi
    echo "--- iter $k: train (warm from best) ---" | tee -a "$LOG"
    python "$TOOLS/train_pv.py" --data "$data" --out "$RUNW/pv_cand_$k.json" \
        --warm "$BESTW" --epochs 2 2>&1 | tee -a "$LOG"

    echo "--- iter $k: gates ---" | tee -a "$LOG"
    "$CR/net_export_check.exe" "$RUNW/pv_cand_$k.json" | tee -a "$LOG"
    # PROMOTE gate: cand netval vs best netval (the value head trained where it's used)
    g1=$("$CR/gate_coc.exe" "$RUNW/pv_cand_$k.json:netval" "$BESTW:netval" "$GATE_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((7100 + k)) "$THREADS" 2>/dev/null | tail -1)
    echo "iter $k gate(cand-vs-best netval): $g1" | tee -a "$LOG"
    # sanity: does the cand's netval still beat its own hybrid (leaf advantage intact)?
    g2=$("$CR/gate_coc.exe" "$RUNW/pv_cand_$k.json:netval" "$RUNW/pv_cand_$k.json:hybrid" "$PROBE_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((8100 + k)) "$THREADS" 2>/dev/null | tail -1)
    echo "iter $k probe(netval vs hybrid, same net): $g2" | tee -a "$LOG"
    # yardstick vs the FIXED scaffold reference (the trustworthy absolute-strength signal)
    g3=$("$CR/gate_coc.exe" "$RUNW/pv_cand_$k.json:netval" SCAFFOLD "$YARD_PAIRS" "$YARD_SIMS" "$YARD_OPP_SIMS" \
        $((9100 + k)) "$THREADS" 2>/dev/null | tail -1)
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
echo "loop complete at iter $ITERS" | tee -a "$LOG"
