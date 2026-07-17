"""Collect a corpus of 2-player Castles of Burgundy games from BGA.
  getRanking -> top players -> getGames (2p, finished, non-concede) -> download logs.
Usage: python cob_collect.py <n_players> <max_games_per_player> <delay_sec>
Reads the session cookie from ~/.bga_session/session.txt (token = TournoiEnLigneidt).
"""
import json, sys, time, os, re, urllib.request

GAME_ID = 1390
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36"
COOKIE_FILE = "C:/Users/Forrest/.bga_session/session.txt"
OUT_DIR = "C:/Users/Forrest/CoB_corpus"

def load_cookie():
    raw = open(COOKIE_FILE, encoding="utf-8").read()
    c = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        # `name: value` (colon-space) -- split on the FIRST delimiter (values may contain '=').
        m = re.match(r'^([A-Za-z0-9_]+)\s*:\s*"?(.+?)"?$', line)
        if m:
            c[m.group(1)] = m.group(2).strip()
            continue
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
    """GET that tolerates errors (the replay page 500s but still triggers the build)."""
    req = urllib.request.Request(url, headers={"Cookie": cookie, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except Exception:
        return b""

def download_log(cookie, token, tid, path, delay):
    """Fetch a table's log; if BGA hasn't built the archive yet, trigger a replay build then retry."""
    logs_url = f"https://boardgamearena.com/archive/archive/logs.html?table={tid}&translated=true"
    d = api(logs_url, cookie, token)
    if d.get("status") == 1 and d.get("data", {}).get("logs"):
        json.dump(d["data"]["logs"], open(path, "w")); return "ok"
    # not built -> trigger replay generation
    ti = api(f"https://boardgamearena.com/table/table/tableinfos.html?id={tid}", cookie, token)
    data = ti.get("data", {})
    gv = data.get("gameversion")
    p0 = (data.get("result", {}).get("player") or [{}])[0].get("player_id", "")
    if not gv:
        return "fail"
    raw_get(f"https://boardgamearena.com/archive/replay/{gv}/?table={tid}&player={p0}&comments=", cookie, token)
    time.sleep(delay)
    d = api(logs_url, cookie, token)
    if d.get("status") == 1 and d.get("data", {}).get("logs"):
        json.dump(d["data"]["logs"], open(path, "w")); return "built"
    return "fail"

def top_players(cookie, token, n, delay):
    out, start = [], 0
    while len(out) < n:
        d = api(f"https://boardgamearena.com/gamepanel/gamepanel/getRanking.html"
                f"?game={GAME_ID}&mode=elo&start={start}", cookie, token)
        ranks = d.get("data", {}).get("ranks", [])
        if not ranks:
            break
        out += [(r["id"], r["name"], r.get("elo") or r.get("ranking")) for r in ranks]
        start += len(ranks); time.sleep(delay)
    return out[:n]

def player_2p_games(cookie, token, pid, cap, delay, max_pages=30):
    """Scan a player's finished CoB games for 2p ones. Bounded by `max_pages` so a
    prolific player with a huge (mostly-multiplayer) history can't stall the run."""
    out, start, pages = [], 0, 0
    while len(out) < cap and pages < max_pages:
        d = api(f"https://boardgamearena.com/gamestats/gamestats/getGames.html"
                f"?player={pid}&game_id={GAME_ID}&finished=1&start={start}&updateStats=0",
                cookie, token)
        tables = d.get("data", {}).get("tables", [])
        if not tables:
            break
        for t in tables:
            pl = t["players"].split(",")
            if len(pl) == 2 and t.get("normalend") == "1" and t.get("concede") == "0":
                out.append(t)
        start += len(tables); pages += 1; time.sleep(delay)
    return out[:cap]

def main():
    n_players = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    delay = float(sys.argv[3]) if len(sys.argv) > 3 else 1.5
    cookie, token = load_cookie()
    os.makedirs(OUT_DIR, exist_ok=True); os.makedirs(OUT_DIR + "/logs", exist_ok=True)

    players = top_players(cookie, token, n_players, delay)
    print(f"top {len(players)} players: {[p[1] for p in players]}", flush=True)

    # Resume: reload any manifest from a prior run so re-launching skips finished work.
    manifest_path = f"{OUT_DIR}/manifest.json"
    manifest = {}
    if os.path.exists(manifest_path):
        try:
            manifest = json.load(open(manifest_path))
        except Exception:
            manifest = {}

    # DOWNLOAD-AS-YOU-GO: enumerate one player's 2p games, download them immediately,
    # then persist the manifest — so a stall on a later player never loses progress.
    got = built = skip = fail = 0
    for pi, (pid, name, elo) in enumerate(players, 1):
        try:
            games = player_2p_games(cookie, token, pid, cap, delay)
        except Exception as e:
            print(f"  [{pi}/{len(players)}] {name}: ENUM FAILED {type(e).__name__} {e}", flush=True)
            continue
        print(f"  [{pi}/{len(players)}] {name}: {len(games)} 2p games -> downloading", flush=True)
        for t in games:
            tid = t["table_id"]
            manifest[tid] = {
                "players": t["players"], "player_names": t["player_names"],
                "scores": t["scores"], "ranks": t["ranks"], "end": t["end"]}
            path = f"{OUT_DIR}/logs/{tid}.json"
            if os.path.exists(path):
                skip += 1; continue
            try:
                res = download_log(cookie, token, tid, path, delay)
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
