"""Build a corpus of 2-player games from BGA for the game in scrape_target.py.
  getRanking -> top players -> getGames (2p, finished, non-concede) -> download logs.

Auth: cob_session (auto-login on a dead ticket). ENUMERATION (getRanking/getGames) uses the
page requestToken via `api_enum` — BGA rejects the idt cookie there with 'Invalid session
information'. DOWNLOADS use the idt path (`api`/`raw_get`), same as the daily cob_resume cron.
Usage: python cob_collect.py <n_players> <max_games_per_player> <delay_sec>
"""
import json
import os
import re
import sys
import time
import urllib.request

import cob_session as cs
import scrape_target as tgt

GAME_ID = tgt.GAME_ID
OUT_DIR = tgt.CORP
UA = cs.UA
COOKIE_FILE = cs.COOKIE_FILE


# ── Legacy standalone cookie/api helpers, kept for downstream cc.api users (cob_analyze).
# The scraper itself uses cob_session below; these read the idt cookie directly and are only
# valid for the endpoints that still accept it (getRanking). ──
def load_cookie():
    raw = open(COOKIE_FILE, encoding="utf-8").read()
    c = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^([A-Za-z0-9_]+)\s*:\s*"?(.+?)"?$', line)
        if m:
            c[m.group(1)] = m.group(2).strip(); continue
        m = re.match(r'^(\S+)[\t ]+"?([^"\s]+)"?', line)
        if m and "=" not in m.group(1) and ":" not in m.group(1):
            c[m.group(1)] = m.group(2)
        elif "=" in line:
            for p in re.split(r";\s*", line):
                if "=" in p:
                    k, v = p.split("=", 1); c[k.strip()] = v.strip()
    hdr = "; ".join(f"{k}={v}" for k, v in c.items()
                    if k.startswith("TournoiEnLigne") or k == "PHPSESSID")
    return hdr, c.get("TournoiEnLigneidt", "")


def api(url, cookie, token):
    req = urllib.request.Request(url, headers={
        "Cookie": cookie, "User-Agent": UA,
        "X-Request-Token": token, "X-Requested-With": "XMLHttpRequest"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def raw_get(url, cookie, token):
    req = urllib.request.Request(url, headers={"Cookie": cookie, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except Exception:
        return b""


def download_log(s, tid, path, delay):
    """Fetch a table's log; if BGA hasn't built the archive yet, trigger a replay build then retry."""
    logs_url = f"https://boardgamearena.com/archive/archive/logs.html?table={tid}&translated=true"
    d = s.api(logs_url)
    if d.get("status") == 1 and d.get("data", {}).get("logs"):
        json.dump(d["data"]["logs"], open(path, "w")); return "ok"
    ti = s.api(f"https://boardgamearena.com/table/table/tableinfos.html?id={tid}")
    data = ti.get("data", {})
    gv = data.get("gameversion")
    p0 = (data.get("result", {}).get("player") or [{}])[0].get("player_id", "")
    if not gv:
        return "fail"
    s.raw_get(f"https://boardgamearena.com/archive/replay/{gv}/?table={tid}&player={p0}&comments=")
    time.sleep(delay)
    d = s.api(logs_url)
    if d.get("status") == 1 and d.get("data", {}).get("logs"):
        json.dump(d["data"]["logs"], open(path, "w")); return "built"
    return "fail"


def top_players(s, n, delay):
    out, start = [], 0
    while len(out) < n:
        d = s.api_enum(f"https://boardgamearena.com/gamepanel/gamepanel/getRanking.html"
                       f"?game={GAME_ID}&mode=elo&start={start}")
        ranks = d.get("data", {}).get("ranks", [])
        if not ranks:
            break
        out += [(r["id"], r["name"], r.get("elo") or r.get("ranking")) for r in ranks]
        start += len(ranks); time.sleep(delay)
    return out[:n]


def player_2p_games(s, pid, cap, delay, max_pages=30):
    """A player's finished 2p games. Bounded by max_pages so a prolific player can't stall.

    PAGINATE WITH `page` (1-based), NOT `start`. getGames SILENTLY IGNORES `start` — it returns
    the same newest 10 tables for every value, with no error and no cursor in the response, so
    the old `start`-based walk looked like it worked and simply re-read page 1 until `cap` was
    hit. That capped every player at ~10 games and held the whole corpus at 147 when a single
    top player has 120+ tables (114 of them clean 2p) available. `offset`/`from`/`nb`/`limit`
    are ignored too; `page` is the only one that advances.

    The `seen` guard is deliberate belt-and-braces: if BGA ever renames the parameter again,
    a repeated page ends the walk instead of silently duplicating page 1 forever.
    """
    out, seen, page = [], set(), 1
    while len(out) < cap and page <= max_pages:
        d = s.api_enum(f"https://boardgamearena.com/gamestats/gamestats/getGames.html"
                       f"?player={pid}&game_id={GAME_ID}&finished=1&page={page}&updateStats=0")
        tables = d.get("data", {}).get("tables", [])
        if not tables:
            break
        fresh = [t for t in tables if t["table_id"] not in seen]
        if not fresh:                      # pagination stopped advancing -> stop, don't spin
            break
        seen.update(t["table_id"] for t in fresh)
        for t in fresh:
            if len(t["players"].split(",")) == 2 and t.get("normalend") == "1" and t.get("concede") == "0":
                out.append(t)
        page += 1; time.sleep(delay)
    return out[:cap]


def main():
    n_players = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 1.5
    # manifest-only: ENUMERATE and record tables, download nothing. Enumeration is unmetered but
    # replays are capped ~10/day, so a big manifest extension would otherwise spend 99% of its
    # run failing downloads against a spent quota. Build the worklist here; let the cron
    # (cob_resume, which has the real quota back-off) drain it over the following days.
    manifest_only = len(sys.argv) > 4 and sys.argv[4] in ("1", "manifest-only", "--manifest-only")
    print(f"target: {tgt.NAME} (game {GAME_ID}) -> {OUT_DIR}"
          f"{'  [MANIFEST ONLY — no downloads]' if manifest_only else ''}", flush=True)

    s = cs.Session()
    # Enumeration needs a LIVE session (the page requestToken comes from a logged-in page),
    # so log in fresh up front and drop any cached token from the old jar.
    if not s.login(lambda m: print(" ", m, flush=True)):
        print("FATAL: auto-login failed — check credentials / re-export the cookie.", flush=True)
        return 2
    s._rt = ""
    os.makedirs(OUT_DIR, exist_ok=True); os.makedirs(OUT_DIR + "/logs", exist_ok=True)

    players = top_players(s, n_players, delay)
    print(f"top {len(players)} players: {[p[1] for p in players]}", flush=True)

    manifest_path = f"{OUT_DIR}/manifest.json"
    manifest = {}
    if os.path.exists(manifest_path):
        try:
            manifest = json.load(open(manifest_path))
        except Exception:
            manifest = {}

    got = built = skip = fail = 0
    for pi, (pid, name, elo) in enumerate(players, 1):
        try:
            games = player_2p_games(s, pid, cap, delay)
        except Exception as e:
            print(f"  [{pi}/{len(players)}] {name}: ENUM FAILED {type(e).__name__} {e}", flush=True)
            continue
        print(f"  [{pi}/{len(players)}] {name}: {len(games)} 2p games -> "
              f"{'manifest only' if manifest_only else 'downloading'}", flush=True)
        for t in games:
            tid = t["table_id"]
            manifest[tid] = {
                "players": t["players"], "player_names": t["player_names"],
                "scores": t["scores"], "ranks": t["ranks"], "end": t["end"]}
            path = f"{OUT_DIR}/logs/{tid}.json"
            if manifest_only or os.path.exists(path):
                skip += 1; continue
            try:
                res = download_log(s, tid, path, delay)
                if res == "ok": got += 1
                elif res == "built": built += 1
                else: fail += 1
            except Exception as e:
                fail += 1; print(f"    dl fail {tid}: {type(e).__name__} {e}", flush=True)
            time.sleep(delay)
        json.dump(manifest, open(manifest_path, "w"), indent=1)
        print(f"    totals: ok {got} built {built} cached {skip} fail {fail}; "
              f"manifest {len(manifest)} games", flush=True)
    print(f"\nDONE. logs -> {OUT_DIR}/logs/ ({got} fetched + {built} built + {skip} cached, "
          f"{fail} failed); {len(manifest)} games in manifest", flush=True)


if __name__ == "__main__":
    main()
