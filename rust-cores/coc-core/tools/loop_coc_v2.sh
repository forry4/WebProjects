#!/bin/bash
# NETVAL self-play ratchet for the v2 (feature-round-2, 1078-dim) net. Clone of
# loop_coc_netval.sh with the v2 specifics: seeds pv_best from the v2 DISTILL
# net (pv2_distill.json, trained on the champion's play with v2 rows), anchors
# iter-0 training on the boot2 distill corpus (v2 rows — the v1 boot csvs are
# dimensionally incompatible), and trains with --in-dim 1078. Gates/probe/
# yardstick unchanged — the encoder seam picks v2 automatically from each
# model's input dim.
#
#   RUN=/c/Users/Forrest/coc_run_v2 ITERS=6 GAMES=2000 SIMS=300 bash coc-core/tools/loop_coc_v2.sh
set -e -o pipefail
RUN=${RUN:-/c/Users/Forrest/coc_run_v2}
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
INDIM=${INDIM:-1078}
LOG=$RUN/loop_log.txt
BEST=$RUN/pv_best.json
BESTW=$RUNW/pv_best.json
PROG=$RUN/progress_v2

mkdir -p "$RUN"
[ -f "$BEST" ] || { cp "$RUN/pv2_distill.json" "$BEST" && cp "$RUN/pv2_distill.json.check" "$BEST.check"; }
start=$(cat "$PROG" 2>/dev/null || echo 0)
echo "=== loop_coc_v2 from iter $start / $ITERS (games=$GAMES sims=$SIMS indim=$INDIM) ===" | tee -a "$LOG"

for ((k = start; k < ITERS; k++)); do
    if [ -f "$RUN/sp_$k.HARVESTED" ]; then
        echo "--- iter $k: v2 netval self-play already complete, skipping ---" | tee -a "$LOG"
    else
        echo "--- iter $k: v2 netval self-play ---" | tee -a "$LOG"
        seed=$((2000000 + k * 100000))
        "$CR/harvest_boot.exe" "$RUNW/sp_$k" "$GAMES" "$SIMS" 20 "$seed" "$THREADS" "$BESTW" netval 8 \
            2>>"$LOG"
        touch "$RUN/sp_$k.HARVESTED"
    fi

    data="$RUNW/sp_$k.t*.csv"
    if [ "$k" -gt 0 ]; then data="$data;$RUNW/sp_$((k - 1)).t*.csv"; else data="$data;$RUNW/boot2.t0.csv;$RUNW/boot2.t1.csv"; fi
    echo "--- iter $k: train (warm from best, in-dim $INDIM) ---" | tee -a "$LOG"
    python "$TOOLS/train_pv.py" --data "$data" --out "$RUNW/pv_cand_$k.json" \
        --warm "$BESTW" --epochs 2 --in-dim "$INDIM" 2>&1 | tee -a "$LOG"

    echo "--- iter $k: gates ---" | tee -a "$LOG"
    "$CR/net_export_check.exe" "$RUNW/pv_cand_$k.json" | tee -a "$LOG"
    g1=$("$CR/gate_coc.exe" "$RUNW/pv_cand_$k.json:netval" "$BESTW:netval" "$GATE_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((7100 + k)) "$THREADS" 2>/dev/null | tail -1)
    echo "iter $k gate(cand-vs-best netval): $g1" | tee -a "$LOG"
    g2=$("$CR/gate_coc.exe" "$RUNW/pv_cand_$k.json:netval" "$RUNW/pv_cand_$k.json:hybrid" "$PROBE_PAIRS" \
        "$GATE_SIMS" "$GATE_SIMS" $((8100 + k)) "$THREADS" 2>/dev/null | tail -1)
    echo "iter $k probe(netval vs hybrid, same net): $g2" | tee -a "$LOG"
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
echo "v2 loop complete at iter $ITERS" | tee -a "$LOG"
