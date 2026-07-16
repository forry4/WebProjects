#!/usr/bin/env bash
# Anchored fine-tune of the champion on BGA expert rows, then gate.
#
# The unanchored attempt gated 0.4083 (worse than the champion) while val metrics looked great
# -- the documented P4b anchor-cliff: train on 100% new-distribution rows and a converged net
# collapses onto them. Every working loop in this campaign mixes a champion anchor tail in.
#
# Mix: the anchor is SUBSAMPLED so the BGA rows are ~25% of the training set (the documented
# ~22% anchor tail, inverted -- here the SCARCE data is the new one, so the anchor is the bulk
# but not so dominant that the expert signal is drowned).
#
# aux: harvest_boot writes 14 aux cols (955); the BGA rows have none (941). They must share a
# layout to mix, so aux is stripped and training runs --aux-dim 0. (Aux is a documented +9.6pp
# on the big self-play loops; secondary for a 4.5k-row fine-tune.)
set -euo pipefail

RUN=/c/Users/Forrest/coc_run_bga
BGA=/c/Users/Forrest/CoB_corpus/bga_rows.csv
CH=/c/Users/Forrest/coc_run_4animal/pv_warm936.json
CORE=/c/Users/Forrest/forrestm_projects-cobmining/coc-core
export PATH="$HOME/.cargo/bin:$PATH"

echo "[1/4] waiting for the anchor harvest to finish..."
while tasklist //FI "IMAGENAME eq harvest_boot.exe" 2>/dev/null | grep -q harvest_boot; do sleep 20; done
echo "      anchor rows: $(cat $RUN/anchor.t*.csv | wc -l)"

echo "[2/4] strip aux (955 -> 941) + subsample so BGA is ~25% of the mix"
python - "$RUN" "$BGA" <<'PY'
import glob, random, sys
run, bga = sys.argv[1], sys.argv[2]
n_bga = sum(1 for _ in open(bga))
target = int(n_bga * 3)          # anchor : bga = 3 : 1  -> bga = 25%
rows = []
for f in glob.glob(run + "/anchor.t*.csv"):
    for line in open(f):
        rows.append(line)
random.Random(7).shuffle(rows)
keep = rows[:target]
out = run + "/anchor_mix.csv"
with open(out, "w") as w:
    for line in keep:
        p = line.rstrip("\n").split(",")
        # 0 gid | 1..936 feats | 937 label | 938 margin | 939 rootv | 940..953 aux | 954 policy
        w.write(",".join(p[:940] + [p[-1]]) + "\n")
print(f"      anchor pool {len(rows)} -> kept {len(keep)} (bga {n_bga}, mix {n_bga/(len(keep)+n_bga)*100:.0f}% bga)")
print(f"      stripped cols: {len(open(out).readline().split(','))} (must equal {len(open(bga).readline().split(','))})")
PY

echo "[3/4] fine-tune (warm from champion, anchor + bga)"
python "$CORE/tools/train_pv.py" \
  --data "$RUN/anchor_mix.csv;$BGA" \
  --out "$RUN/pv_bga_anchored.json" \
  --warm "$CH" --in-dim 936 --aux-dim 0 \
  --epochs 6 --batch 256 --lr 5e-5 2>&1 | grep -Ev "UserWarning|vloss_s" | tail -10

echo "[4/4] GATE vs champion (serving config 30/1.0, 200 sims, n=240)"
"$CORE/target/release/gate_coc.exe" \
  "$RUN/pv_bga_anchored.json:netval@30@1.0" "$CH:netval@30@1.0" \
  120 200 200 4242 10 2>&1 | tail -2
echo
echo "reference: UNANCHORED attempt was 0.4083 +-0.062 (margin -9.6); mirror sanity 0.5000"
