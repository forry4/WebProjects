#!/bin/bash
# Auxiliary-score-head experiment corpus (2026-07-11): champion (pv_ship_r2)
# plays itself with PCR — 25% of decisions at the FULL 6000-sim cap (mid-knee
# 4-8k -> policy rows), 75% at 300 (value-only rows). 5000 games, v1 encoder.
# Same recipe as coc_run_cap/harvest_cap.sh (that corpus's distill TIED the
# champion at equal sims) — the only variable this time is the harvest_boot
# BINARY, which now also writes the 14 terminal-score aux columns per row
# (see engine.rs's shadow VP ledger + harvest_boot.rs::aux_targets). GPU
# sidecar serves the forwards.
set -e
RUN=/c/Users/Forrest/coc_run_aux
RUNW=$(cygpath -m "$RUN")
CR=/c/Users/Forrest/forrestm_projects/coc-core/target/release
TOOLS=/c/Users/Forrest/forrestm_projects/coc-core/tools
CHAMP=C:/Users/Forrest/coc_run_r2/pv_ship_r2.json
LOG=$RUN/harvest_log.txt
gpu_pid=""
killtree() { taskkill //PID "$1" //T //F >/dev/null 2>&1 || true; }
reap_gpu_servers() {
    powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'gpu_server' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" \
        >/dev/null 2>&1 || true
}
cleanup() { [ -n "$gpu_pid" ] && killtree "$gpu_pid"; reap_gpu_servers; }
trap cleanup EXIT
reap_gpu_servers
COC_GPU_PAD=128 python "$TOOLS/gpu_server.py" "$CHAMP" --port 9911 >"$RUN/gpu_server.log" 2>&1 &
gpu_pid=$!
for i in $(seq 1 60); do grep -q "ready" "$RUN/gpu_server.log" 2>/dev/null && break; sleep 2; done
grep -q "ready" "$RUN/gpu_server.log" || { echo "FATAL: gpu server never came up"; exit 1; }
# CUDA-fallback guard (2026-07-11: a transient "CUDA unknown error" silently
# started the sidecar on CPU — ~3x slower harvest; refuse instead)
grep -q "dev=cuda" "$RUN/gpu_server.log" || { echo "FATAL: sidecar came up dev=cpu (CUDA init failed) — fix CUDA and relaunch"; exit 1; }
echo "=== aux-head harvest: 5000g PCR 250@300 full-cap 6000, teacher=champion, WITH aux columns ===" | tee -a "$LOG"
COC_GPU_ADDR="127.0.0.1:9911" "$CR/harvest_boot.exe" "$RUNW/aux_boot" 5000 6000 20 \
    13000000 10 "$CHAMP" netvalgpu 64 v1 250@300 2>&1 | tee -a "$LOG"
killtree "$gpu_pid"
gpu_pid=""
touch "$RUN/aux_boot.HARVESTED"
echo "=== harvest complete ===" | tee -a "$LOG"
