"""Attach a per-SEAT, at-the-time ELO to every game in the corpus manifest.

Why this exists: the manifest records who played, but not how good they were. The corpus was
seeded from top-ranked players, so roughly half of every game is a top player -- and the OTHER
half is whoever they happened to be matched against, which is often 500-700 ELO weaker. Harvesting
both seats teaches the net the weak side's mistakes as if they were expert play.

SOURCE: `tableinfos` -- it returns `rank_after_game` (the post-game ELO) for EVERY seat in one
call. Do NOT use gamestats/getGames for this: it reports elo_after only for the player you query,
AND its `start` parameter is silently IGNORED (every page returns the same first 10 tables), so
paging back to an older game is impossible. That same bug caps cob_collect at ~10 games/player.

This is table metadata, not a replay archive -- it costs nothing against the download quota.

Writes {CORP}/elo.json:  {table_id: {player_id: elo_float}}
Usage: python cob_elo.py [delay_sec]
"""
import json
import os
import sys
import time

import cob_session as cs
import scrape_target as tgt

CORP = tgt.CORP


def table_elos(s, tid):
    """{player_id: post-game ELO} for one table, or {} if BGA won't say."""
    d = s.api(f"https://boardgamearena.com/table/table/tableinfos.html?id={tid}")
    players = (d.get("data", {}) or {}).get("result", {}).get("player") or []
    out = {}
    for p in players:
        r = p.get("rank_after_game")
        if r not in (None, ""):
            out[str(p["player_id"])] = float(r)
    return out


def main():
    delay = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0

    manifest = json.load(open(f"{CORP}/manifest.json"))
    have = sorted(f[:-5] for f in os.listdir(f"{CORP}/logs") if f.endswith(".json"))

    out_path = f"{CORP}/elo.json"
    elo = json.load(open(out_path)) if os.path.exists(out_path) else {}

    s = cs.Session()
    if not s.login(lambda m: print(" ", m, flush=True)):
        print("FATAL: auto-login failed.", flush=True)
        return 2

    todo = [t for t in have if len(elo.get(t, {})) < 2]
    print(f"{len(have)} downloaded games; {len(todo)} still need ratings", flush=True)
    fail = 0
    for i, tid in enumerate(todo, 1):
        try:
            got = table_elos(s, tid)
        except Exception as e:
            print(f"  [{i}/{len(todo)}] {tid}: FAIL {type(e).__name__} {e}", flush=True)
            fail += 1
            time.sleep(delay * 3)
            continue
        if got:
            elo[tid] = got
        else:
            fail += 1
        if i % 10 == 0 or i == len(todo):
            json.dump(elo, open(out_path, "w"), indent=0)
            print(f"  [{i}/{len(todo)}] rated {len(elo)} tables ({fail} unrated)", flush=True)
        time.sleep(delay)

    json.dump(elo, open(out_path, "w"), indent=0)
    both = sum(1 for t in have if len(elo.get(t, {})) == 2)
    print(f"\nDONE. both seats rated: {both}/{len(have)} -> {out_path}", flush=True)


if __name__ == "__main__":
    sys.exit(main() or 0)
