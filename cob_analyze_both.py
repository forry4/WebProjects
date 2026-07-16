"""DECISIVE TEST: is our ~43% agreement with top players a move-DIVERSITY ceiling, or a
STRENGTH gap?

Every kept game has a top-ranked player AND a lower-ranked opponent. Measure our net's
agreement with BOTH, in the SAME games, over the SAME kind of decisions:

  agreement(net, top) ~= agreement(net, weak)   -> DIVERSITY. Many moves are near-equal, so
                                                  nobody agrees with anybody much, and the
                                                  number says nothing about strength.
  agreement(net, weak) >  agreement(net, top)   -> STRENGTH GAP. Our net plays more like the
                                                  weaker player than the stronger one, which
                                                  is exactly what "we're below the pros"
                                                  predicts.

This controls for diversity because both rates are measured on the same boards, same
position types, same legal-move counts -- the only thing that changes is whose move we
compare against.

Usage: python cob_analyze_both.py [sims]
"""
import collections
import io
import json
import os
import subprocess
import sys

import cob_replay
from cob_analyze import move_key, rank_map
from games.castles_of_crimson import engine
from games.castles_of_crimson.az import compact, bridge

CORP = "C:/Users/Forrest/CoB_corpus"
LOGS, MANIFEST, KEPT = CORP + "/logs", CORP + "/manifest.json", CORP + "/kept_games.txt"
EXE = "C:/Users/Forrest/forrestm_projects-cobmining/coc-core/target/release/move_server_coc.exe"
MODEL = "C:/Users/Forrest/coc_run_4animal/pv_warm936.json"
SIMS = int(sys.argv[1]) if len(sys.argv) > 1 else 2000


def main():
    srv = [None]
    seed = [1]

    def start():
        srv[0] = subprocess.Popen([EXE, MODEL, "30", "1.0"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, bufsize=1,
                                  encoding="utf-8")

    def net_move(g, pid):
        if srv[0] is None or srv[0].poll() is not None:
            start()
        try:
            srv[0].stdin.write(json.dumps(
                {"proj": compact.project(g), "sims": SIMS, "seed": seed[0]},
                separators=(",", ":")) + "\n")
            srv[0].stdin.flush()
            seed[0] += 1
            return bridge.compact_to_move(g, pid, json.loads(srv[0].stdout.readline())["move"])
        except Exception:
            try: srv[0].kill()
            except Exception: pass
            srv[0] = None
            raise

    ranks = rank_map()
    man = json.load(open(MANIFEST))
    agg = {"top": [0, 0], "weak": [0, 0]}
    per_game = []

    for tid in sorted(os.path.basename(p)[:-5] for p in
                      __import__("glob").glob(LOGS + "/*.json")):
        entry = man.get(tid, {})
        pl = [p for p in entry.get("players", "").split(",") if p]
        if len(pl) != 2:
            continue
        top = min(pl, key=lambda p: ranks.get(p, 999))
        weak = [p for p in pl if p != top][0]
        if ranks.get(top, 999) == ranks.get(weak, 999):
            continue                      # can't tell them apart -> skip
        st = {"top": [0, 0], "weak": [0, 0]}

        def on_move(g, pid, move, tag, _t=top, _w=weak, _st=st):
            who = "top" if pid == _t else ("weak" if pid == _w else None)
            if who is None or g.get("phase") != "playing" or g.get("pending_kind"):
                return
            legal = engine.legal_moves(g, pid)
            if len(legal) < 2:
                return
            hk = move_key(move)
            if hk not in {move_key(m) for m in legal}:
                return
            try:
                bot = net_move(g, pid)
            except Exception:
                return
            _st[who][1] += 1
            if hk == move_key(bot):
                _st[who][0] += 1

        try:
            with __import__("contextlib").redirect_stdout(io.StringIO()):
                cob_replay.main(f"{LOGS}/{tid}.json", verbose=False, on_move=on_move)
        except Exception:
            pass
        if st["top"][1] and st["weak"][1]:
            for k in ("top", "weak"):
                agg[k][0] += st[k][0]
                agg[k][1] += st[k][1]
            per_game.append((tid, st))
            rt = st["top"][0] / st["top"][1] * 100
            rw = st["weak"][0] / st["weak"][1] * 100
            print(f"  {tid}  top {st['top'][0]:>3}/{st['top'][1]:<3} ({rt:4.1f}%)   "
                  f"weak {st['weak'][0]:>3}/{st['weak'][1]:<3} ({rw:4.1f}%)", flush=True)

    try:
        if srv[0]: srv[0].terminate()
    except Exception:
        pass

    print(f"\n=== net agreement, same games, same decision filter ({len(per_game)} games) ===")
    for k in ("top", "weak"):
        a, n = agg[k]
        print(f"  vs {k:<5} player: {a}/{n} = {a/n*100:.1f}%" if n else f"  vs {k}: no data")
    if agg["top"][1] and agg["weak"][1]:
        rt = agg["top"][0] / agg["top"][1]
        rw = agg["weak"][0] / agg["weak"][1]
        import math
        se = math.sqrt(rt * (1 - rt) / agg["top"][1] + rw * (1 - rw) / agg["weak"][1])
        d = rw - rt
        print(f"\n  weak - top = {d*100:+.1f}pp  (+-{1.96*se*100:.1f})  -> "
              f"{'STRENGTH GAP: we play more like the weaker player' if d > 1.96*se else 'no significant difference -> consistent with a diversity ceiling'}")


if __name__ == "__main__":
    main()
