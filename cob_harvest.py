"""Harvest replayed BGA expert games into train_pv-format CSV rows.

Feeds every clean expert decision to coc-core's harvest_bga (which finds the micro-action
chain and emits one row per micro-decision, one-hot on the expert's action).

BOTH SEATS are recorded, not just the top player: the opponent of a top-100 BGA player is
also far above our net (that's the whole premise), and doubling the rows matters when the
corpus is this small. Each row carries that mover's own label/margin.

mon6 games: harvested only up to the phase where a mon6 tile is DRAWN (cob_replay.max_phase).
Those phases are untainted -- nobody could see the tile, so no decision accounts for it.

Usage: python cob_harvest.py <out.csv>
"""
import contextlib
import glob
import io
import json
import os
import subprocess
import sys

import cob_replay
from games.castles_of_crimson import engine
from games.castles_of_crimson.az import compact, bridge

# Inlined from cob_analyze (which parses sys.argv at import time, so importing it here would
# try to read OUR argv as its sims setting).
_KEYF = ("space_id", "tile_id", "die_index", "to", "depot", "color", "value", "sub")
def move_key(m):
    return (m.get("type"), tuple(str(m.get(k)) for k in _KEYF))

CORP = "C:/Users/Forrest/CoB_corpus"
LOGS = CORP + "/logs"
EXE = "C:/Users/Forrest/forrestm_projects-cobmining/coc-core/target/release/harvest_bga.exe"


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "C:/Users/Forrest/CoB_corpus/bga_rows.csv"
    proc = subprocess.Popen([EXE, out], stdin=subprocess.PIPE, text=True, bufsize=1,
                            encoding="utf-8")
    sent = [0]
    games = 0

    for p in sorted(glob.glob(LOGS + "/*.json")):
        tid = os.path.basename(p)[:-5]
        ev, _ = cob_replay.load_events(p)
        raw, loc, mon = cob_replay.build_catalog(ev)
        dp = cob_replay.mon6_draw_phase(ev, raw, mon)
        max_phase = (dp - 1) if dp else None
        if dp == 0:
            continue                       # mon6 dealt in phase A -> nothing untainted

        pending = []

        def on_move(g, pid, move, tag, _acc=pending):
            if g.get("phase") != "playing" or g.get("pending_kind"):
                return
            legal = engine.legal_moves(g, pid)
            if len(legal) < 2:
                return
            if move_key(move) not in {move_key(m) for m in legal}:
                return
            try:
                cm = bridge.move_to_compact(g, pid, move)
            except Exception:
                return
            _acc.append((compact.project(g), cm, g["order"].index(pid)))

        try:
            with contextlib.redirect_stdout(io.StringIO()):
                r = cob_replay.main(p, verbose=False, on_move=on_move, max_phase=max_phase)
        except Exception:
            continue

        # Labels: a completed replay gives our engine's own final scores (the CoC-world result
        # of this play). A TRUNCATED prefix has no ending we can replay -- take the outcome from
        # BGA's own finalScoring, which is still the real result of the real game.
        scores = None
        if r.get("completed"):
            gg = None
            def grab(g, pid, move, tag):
                nonlocal gg
                gg = g
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    cob_replay.main(p, verbose=False, on_move=grab, max_phase=max_phase)
                scores = engine.final_scores(gg) if gg and engine.is_over(gg) else None
                order = gg["order"] if gg else None
            except Exception:
                scores = None
        if scores is None:
            rec = None
            for mid, d in ev:
                if d["type"] == "finalScoring":
                    rec = d["args"]["scoreTable"]["total"]
            if not rec:
                continue
            pl = [k for k in rec if k != "0"]
            if len(pl) != 2:
                continue
            # order must match the replay's seat order
            order = None
            for mid, d in ev:
                if d["type"] == "playerEstate":
                    order = (order or []) + [str(d["args"]["plId"])]
            if not order or len(order) != 2:
                continue
            scores = {order[0]: int(rec[order[0]]), order[1]: int(rec[order[1]])}

        vals = [scores[order[0]], scores[order[1]]]
        for proj, cm, seat in pending:
            mine, theirs = vals[seat], vals[1 - seat]
            proc.stdin.write(json.dumps(
                {"proj": proj, "move": cm, "label": 1 if mine > theirs else 0,
                 "margin": mine - theirs, "gid": int(tid) % 1000000},
                separators=(",", ":")) + "\n")
            sent[0] += 1
        games += 1
        print(f"  {tid}: {len(pending)} decisions "
              f"({'full' if max_phase is None else 'phases A-'+'ABCDE'[max_phase]})", flush=True)

    proc.stdin.close()
    proc.wait()
    print(f"\ngames harvested: {games} | decisions sent: {sent[0]} -> {out}")


if __name__ == "__main__":
    main()
