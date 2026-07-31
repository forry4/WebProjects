"""Harvest replayed BGA expert games into train_pv-format CSV rows.

Feeds every clean expert decision to coc-core's harvest_bga (which finds the micro-action
chain and emits one row per micro-decision, one-hot on the expert's action).

SEAT STRENGTH IS A FILTER (`min_elo`). The original premise here -- "the opponent of a
top-100 BGA player is also far above our net, so record BOTH seats" -- is FALSE for this
corpus, and cob_elo.py measures it: every game has a ~2000+ seeded top player, but the
median opponent is ~1635, a **median 396-ELO gap** (p75 514, max 753). At a 1900 bar only
9 of 114 rated games are pro-vs-pro. Harvesting both seats therefore trains the net to
imitate a ~400-ELO-weaker player on roughly half its rows, with no way to tell them apart.
So: a decision is harvested only if THAT MOVER cleared `min_elo`. Both seats of a
pro-vs-pro game still qualify; in a mismatch only the strong side is taken. Rating comes
from {CORP}/elo.json -- an unrated seat is DROPPED whenever min_elo > 0 (we cannot vouch
for it), which is why cob_elo.py should be re-run after every download batch.

mon6 games: harvested only up to the phase where a mon6 tile is DRAWN (cob_replay.max_phase).
Those phases are untainted -- nobody could see the tile, so no decision accounts for it.

Usage: python cob_harvest.py <out.csv> [min_elo]
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
    min_elo = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    elo_path = CORP + "/elo.json"
    elos = json.load(open(elo_path)) if os.path.exists(elo_path) else {}
    if min_elo and not elos:
        print(f"FATAL: min_elo={min_elo:.0f} but no {elo_path} — run cob_elo.py first.")
        return 2
    print(f"min_elo {min_elo:.0f} | ratings for {len(elos)} games", flush=True)

    proc = subprocess.Popen([EXE, out], stdin=subprocess.PIPE, text=True, bufsize=1,
                            encoding="utf-8")
    sent = [0]
    skipped = [0]
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
        seat_elo = elos.get(tid, {})
        kept_here = 0
        for proj, cm, seat in pending:
            if min_elo:
                r = seat_elo.get(str(order[seat]))
                if r is None or r < min_elo:
                    skipped[0] += 1
                    continue
            mine, theirs = vals[seat], vals[1 - seat]
            kept_here += 1
            proc.stdin.write(json.dumps(
                {"proj": proj, "move": cm, "label": 1 if mine > theirs else 0,
                 "margin": mine - theirs, "gid": int(tid) % 1000000},
                separators=(",", ":")) + "\n")
            sent[0] += 1
        games += 1 if kept_here else 0
        print(f"  {tid}: {kept_here}/{len(pending)} decisions "
              f"({'full' if max_phase is None else 'phases A-'+'ABCDE'[max_phase]})", flush=True)

    proc.stdin.close()
    proc.wait()
    print(f"\ngames contributing: {games} | decisions sent: {sent[0]} "
          f"(below the {min_elo:.0f} bar / unrated: {skipped[0]}) -> {out}")


if __name__ == "__main__":
    sys.exit(main() or 0)
