"""Batch replay-filter the collected CoB corpus through the CoC engine.
Keeps games that replay to completion AND produce the same winner as recorded
(winner-preservation). Drops the rest with reasons.
Usage: python cob_filter.py
"""
import os, glob, collections
import cob_replay

LOGS = "C:/Users/Forrest/CoB_corpus/logs"
OUT = "C:/Users/Forrest/CoB_corpus"

def main():
    logs = sorted(glob.glob(LOGS + "/*.json"))
    keep = []
    drop = collections.Counter()
    stop_reasons = collections.Counter()
    for path in logs:
        tid = os.path.basename(path).replace(".json", "")
        try:
            r = cob_replay.main(path, verbose=False)
        except Exception as e:
            drop["exception"] += 1
            stop_reasons[f"exc:{type(e).__name__}"] += 1
            continue
        if not r["over"]:
            drop["did_not_complete"] += 1
            stop_reasons[(r.get("stopped") or "?").split(" err=")[0][:50]] += 1
            continue
        if not r["winner_match"]:
            drop["winner_mismatch"] += 1
            continue
        keep.append(tid)

    n = len(logs)
    print(f"corpus: {n} games")
    print(f"  KEEP (complete + winner match): {len(keep)}")
    for k, v in drop.most_common():
        print(f"  drop [{k}]: {v}")
    if stop_reasons:
        print("  top stop/exception reasons:")
        for reason, c in stop_reasons.most_common(8):
            print(f"    {c:3d}  {reason}")
    open(f"{OUT}/kept_games.txt", "w").write("\n".join(keep))
    print(f"\nkept table_ids -> {OUT}/kept_games.txt")

if __name__ == "__main__":
    main()
