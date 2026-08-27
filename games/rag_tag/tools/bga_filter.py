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

from games.rag_tag.tools import bga_fight as tt_fight
from games.rag_tag.tools import bga_replay as tt_replay






def main():
    manifest = json.load(open(f"{CORP}/manifest.json"))
    paths = sorted(glob.glob(f"{CORP}/logs/*.json"))
    if not paths:
        print("no logs yet.")
        return 1

    keep, reasons, div = [], collections.Counter(), collections.Counter()
    pub, rev, trk = collections.Counter(), collections.Counter(), collections.Counter()
    for p in paths:
        tid = os.path.basename(p)[:-5]
        row = manifest.get(tid)
        if not row:
            reasons["not in manifest"] += 1
            continue
        # ALIGNMENT-FREE, and reported even for a log the engine cannot finish: does our
        # reconstruction of each build match BGA's own public record of it? A disagreement
        # here is a PARSE bug, which is worth telling apart from an engine bug before
        # anybody goes looking through the rules.
        try:
            ok, bad, _n = tt_replay.verify_against_public(
                list(tt_replay.tt_inspect.events(p)), row)
            pub["confirmed"] += ok
            pub["disagreed"] += bad
        except Exception:                             # noqa: BLE001 — never break the batch
            pub["errored"] += 1
        # THREE GATES OFF ONE REPLAY, in increasing resolution: the winner (one bit at the
        # end), the cards revealed (the whole sequence), and every fighter's health and
        # special track on every turn. The last one is what actually finds rules bugs --
        # the winner only tells you a game diverged somewhere.
        try:
            agreed, total, first_bad, r, theirs, ours = tt_fight.compare(p, row)
            trk["ok"] += agreed
            trk["tot"] += total
            trk["games"] += 1
            trk["clean"] += first_bad is None
            trk["turns"] += len(ours) == len(theirs)
            if first_bad and "-v" in sys.argv:
                print(f"  {tid}: TURN {first_bad[0]} {first_bad[1]} "
                      f"ours {first_bad[2]} vs BGA {first_bad[3]}")
        except Exception as e:                        # noqa: BLE001 — never break the batch
            print(f"  {tid}: per-turn gate: {type(e).__name__}: {e}")
            r = tt_replay.replay(p, row)
        dv = r.get("divergence")
        if dv:
            f0 = dv["fighters"][0]
            div[f"{f0[0]}: ours {f0[1]} vs BGA {f0[2]}"] += 1
            if "-v" in sys.argv:
                print(f"  {tid}: STATE DIVERGENCE mid {dv['mid']} "
                      f"round {dv['round']} phase={dv['phase']}: {dv['fighters']}")
        rev["ok"] += r.get("rev_ok", 0)
        rev["tot"] += r.get("rev_tot", 0)
        if r.get("rev_tot"):
            rev["games"] += 1
            if r.get("rev_first_bad") is None:
                rev["clean"] += 1
            elif not r["winner_match"]:
                rev["bad_and_wrong"] += 1
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
    tot = pub["confirmed"] + pub["disagreed"]
    if tot:
        print(f"  build parse vs BGA's own public record: {pub['confirmed']}/{tot} "
              f"({pub['confirmed'] / tot:.1%}) - a disagreement here is a PARSE bug")
    if rev["tot"]:
        print(f"  cards revealed, vs BGA's own fightLog: {rev['ok']}/{rev['tot']} "
              f"({rev['ok'] / rev['tot']:.1%}); {rev['clean']}/{rev['games']} games match the "
              f"WHOLE sequence")
        print(f"    -> reveals right but winner wrong = an ENGINE bug; reveals wrong = the "
              f"replay lost the deck order")
    if trk["tot"]:
        print(f"  every fighter's TRACKS, per turn, vs the fightLog: {trk['ok']}/{trk['tot']}"
              f" ({trk['ok'] / trk['tot']:.1%}); {trk['clean']}/{trk['games']} games exact "
              f"throughout, {trk['turns']}/{trk['games']} matching BGA's turn count")
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
