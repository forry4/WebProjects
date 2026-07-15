"""Compare OUR NET (the warm-started r2 936-net, via the coc-core move server) against
the TOP player in each kept CoB game — the real "our bot vs top humans" test.

Same decision filter as cob_analyze.py (top player's clean primary decisions: play
phase, no pending, >=2 legal, human move directly legal), but the bot is the netval
search. Excludes the one board-4 game (880518518) — boards 2/4 changed in board.py
and the net was warm-started from r2, so board-4 is fine now, BUT we keep it simple.

Usage: python cob_analyze_net.py [sims] [model.json]
"""
import json, os, sys, subprocess, collections
import cob_replay, cob_collect as cc
from cob_analyze import move_key, rank_map
from games.castles_of_crimson import engine
from games.castles_of_crimson.az import compact, bridge

CORP = "C:/Users/Forrest/CoB_corpus"
LOGS, MANIFEST, KEPT = CORP + "/logs", CORP + "/manifest.json", CORP + "/kept_games.txt"
EXE = "C:/Users/Forrest/forrestm_projects-cobmining/coc-core/target/release/move_server_coc.exe"

SIMS = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
MODEL = sys.argv[2] if len(sys.argv) > 2 else "C:/Users/Forrest/coc_run_4animal/pv_warm936.json"
EXCLUDE = {"880518518"}  # board 4 (kept for reference; excluded to be conservative)

def main():
    srv = [None]
    seed = [1]

    def start_srv():
        srv[0] = subprocess.Popen([EXE, MODEL, "30", "1.0"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, text=True, bufsize=1, encoding="utf-8")

    def net_move(g, pid):
        if srv[0] is None or srv[0].poll() is not None:
            start_srv()
        try:
            req = {"proj": compact.project(g), "sims": SIMS, "seed": seed[0]}
            seed[0] += 1
            srv[0].stdin.write(json.dumps(req, separators=(",", ":")) + "\n"); srv[0].stdin.flush()
            line = srv[0].stdout.readline()
            if not line:
                raise RuntimeError("server died")
            resp = json.loads(line)
            return bridge.compact_to_move(g, pid, resp["move"])
        except Exception:
            # a bad projection can panic the server; kill it so the next call restarts.
            try: srv[0].kill()
            except Exception: pass
            srv[0] = None
            raise

    ranks = rank_map()
    kept = [l.strip() for l in open(KEPT) if l.strip() and l.strip() not in EXCLUDE]
    man = json.load(open(MANIFEST))
    print(f"NET comparison | model {os.path.basename(MODEL)} | {SIMS} sims | {len(kept)} games\n")

    agg = collections.Counter()
    bytype = collections.defaultdict(lambda: [0, 0])
    rows = []
    for tid in kept:
        entry = man.get(tid, {})
        pl = [p for p in entry.get("players", "").split(",") if p]
        names = entry.get("player_names", "").split(",")
        if len(pl) != 2:
            continue
        top = min(pl, key=lambda p: ranks.get(p, 999))
        top_name = names[pl.index(top)] if len(names) == 2 else top
        st = {"agree": 0, "total": 0, "fail": 0}

        def on_move(g, pid, move, tag, _top=top, _st=st):
            if pid != _top or g.get("phase") != "playing" or g.get("pending_kind"):
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
                _st["fail"] += 1; return
            _st["total"] += 1
            t = move.get("type"); bytype[t][1] += 1
            if hk == move_key(bot):
                _st["agree"] += 1; bytype[t][0] += 1

        try:
            r = cob_replay.main(f"{LOGS}/{tid}.json", verbose=False, on_move=on_move)
        except Exception as e:
            print(f"  {tid}: replay error {type(e).__name__}"); continue
        won = (r.get("coc_winner") == top)
        rate = st["agree"] / st["total"] if st["total"] else 0.0
        rows.append((tid, top_name, won, st["agree"], st["total"], rate))
        agg["agree"] += st["agree"]; agg["total"] += st["total"]
        print(f"  {tid}  {top_name:<16} {'WON ' if won else 'lost'} "
              f"agree {st['agree']:>3}/{st['total']:<3} ({rate*100:4.1f}%)  fails {st['fail']}")

    try:
        if srv[0]: srv[0].terminate()
    except Exception:
        pass
    tot = agg["total"]
    print("\n=== OVERALL (net vs top player's decisions) ===")
    print(f"games: {len(rows)} | top-player decisions: {tot}")
    print(f"NET agreed with top player: {agg['agree']}/{tot} = {(agg['agree']/tot*100) if tot else 0:.1f}%")
    print("\n=== agreement by move type ===")
    for t, (a, n) in sorted(bytype.items(), key=lambda kv: -kv[1][1]):
        print(f"  {t:<22} {a:>3}/{n:<3} ({(a/n*100) if n else 0:4.1f}%)")

if __name__ == "__main__":
    main()
