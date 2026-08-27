"""Replay every downloaded Tag Team log through games/rag_tag and report where they stop.

This is the ENGINE-PARITY gate. A log that replays to the recorded winner is a real game
BGA and our engine agree about; a divergence names a rule we have wrong and hands you a
reproduction. The stop-reason histogram is the actual output — the percentage is noise
until the corpus is large, but the reasons are informative from game one.

  python tt_filter.py [-v]
"""
import collections
import glob
import json
import os
import sys

# The corpus lives OUTSIDE the repo (BGA table logs, ~9MB per 100 games) — override with
# TAGTEAM_CORPUS. The `cob-mining` branch's scraper writes it; nothing here downloads.
CORP = os.environ.get("TAGTEAM_CORPUS", "C:/Users/Forrest/TagTeam_corpus")

from games.rag_tag.tools import bga_replay as tt_replay






def main():
    manifest = json.load(open(f"{CORP}/manifest.json"))
    paths = sorted(glob.glob(f"{CORP}/logs/*.json"))
    if not paths:
        print("no logs yet.")
        return 1

    keep, reasons, div = [], collections.Counter(), collections.Counter()
    for p in paths:
        tid = os.path.basename(p)[:-5]
        row = manifest.get(tid)
        if not row:
            reasons["not in manifest"] += 1
            continue
        r = tt_replay.replay(p, row)
        dv = r.get("divergence")
        if dv:
            f0 = dv["fighters"][0]
            div[f"{f0[0]}: ours {f0[1]} vs BGA {f0[2]}"] += 1
            if "-v" in sys.argv:
                print(f"  {tid}: STATE DIVERGENCE mid {dv['mid']} "
                      f"round {dv['round']} phase={dv['phase']}: {dv['fighters']}")
        if r["winner_match"]:
            keep.append(tid)
        else:
            why = r["stopped"] or (
                f"completed but winner {r['winner']} != recorded {r['recorded_winner']}"
                if r["over"] else f"ran out of plan in phase={r.get('phase')}")
            reasons[why.split(" (")[0][:72]] += 1
            if "-v" in sys.argv:
                print(f"  {tid}: applied {r['applied']:>3} | {why}")

    print(f"\n{len(paths)} logs | KEEP (replays to the recorded winner): {len(keep)}")
    for why, n in reasons.most_common(15):
        print(f"  {n:>3}  {why}")
    if div:
        print()
        print("STATE DIVERGENCES (oracle calibrated at lag +1; a lead, not a verdict):")
        for what, n in div.most_common(12):
            print(f"  {n:>3}  {what}")
    open(f"{CORP}/kept_games.txt", "w").write("\n".join(keep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
