"""Download the games ALREADY enumerated in the manifest — no re-enumeration.

cob_collect.py re-scans getRanking/getGames on every launch before it downloads;
once the manifest exists that work is redundant (and it was the stall that cost the
first run ~1.5h). This walks manifest.json and downloads whatever's missing.

QUOTA BACK-OFF (the load-bearing part — do not regress):
BGA free accounts cap replays at ~10-16/day. The authoritative signal is the
logs.html JSON: {"status": 0, "error": "You have reached a limit (replay)"}.
Do NOT probe the archive/replay/ page to detect this — when the cap is hit that
page answers "500 Wrong siteversion", a red herring that looks like a per-game
build failure. An earlier guard checked exactly that and never fired, so a run
hammered 63 dead requests against a closed door.

So: preflight ONE probe before the loop, and abort on the first quota answer.

Usage: python cob_resume.py [delay_sec] [max_downloads]
"""
import json, os, sys, time
import cob_collect as cc

CORP = "C:/Users/Forrest/CoB_corpus"
MANIFEST, LOGS = CORP + "/manifest.json", CORP + "/logs"
QUOTA_MSG = "reached a limit"


def fetch_logs(cookie, token, tid):
    """-> (logs|None, quota_hit: bool). The logs endpoint is the quota oracle."""
    d = cc.api(f"https://boardgamearena.com/archive/archive/logs.html"
               f"?table={tid}&translated=true", cookie, token)
    if d.get("status") == 1 and d.get("data", {}).get("logs"):
        return d["data"]["logs"], False
    return None, QUOTA_MSG in str(d.get("error", ""))


def get_one(cookie, token, tid, path, delay):
    """-> 'ok' | 'built' | 'fail' | 'quota'."""
    logs, quota = fetch_logs(cookie, token, tid)
    if logs:
        json.dump(logs, open(path, "w"))
        return "ok"
    if quota:
        return "quota"
    # Archive not built yet -> trigger a replay build, then retry once.
    try:
        ti = cc.api(f"https://boardgamearena.com/table/table/tableinfos.html?id={tid}",
                    cookie, token)
        data = ti.get("data", {})
        gv = data.get("gameversion")
        p0 = (data.get("result", {}).get("player") or [{}])[0].get("player_id", "")
        if not gv:
            return "fail"
        cc.raw_get(f"https://boardgamearena.com/archive/replay/{gv}/"
                   f"?table={tid}&player={p0}&comments=", cookie, token)
    except Exception:
        return "fail"
    time.sleep(delay)
    logs, quota = fetch_logs(cookie, token, tid)
    if logs:
        json.dump(logs, open(path, "w"))
        return "built"
    return "quota" if quota else "fail"


def main():
    delay = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    max_dl = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    cookie, token = cc.load_cookie()
    manifest = json.load(open(MANIFEST))
    os.makedirs(LOGS, exist_ok=True)

    pending = [t for t in manifest if not os.path.exists(f"{LOGS}/{t}.json")]
    have = len(manifest) - len(pending)
    print(f"manifest {len(manifest)} | have {have} | pending {len(pending)}", flush=True)
    if not pending:
        print("nothing pending.", flush=True)
        return

    # PREFLIGHT: one probe. If the cap is already spent, every further call is waste.
    _, quota = fetch_logs(cookie, token, pending[0])
    if quota:
        print("\n*** BGA daily replay QUOTA is already exhausted — not starting. ***")
        print(f"corpus stays at {have}/{len(manifest)}. Retry after the daily reset.")
        return

    got = built = fail = 0
    for i, tid in enumerate(pending, 1):
        if got + built >= max_dl:
            print(f"\nreached max_downloads={max_dl}, stopping.", flush=True)
            break
        res = get_one(cookie, token, tid, f"{LOGS}/{tid}.json", delay)
        if res == "quota":
            print(f"\n*** QUOTA reached after {got+built} new downloads — backing off. ***",
                  flush=True)
            break
        if res in ("ok", "built"):
            got += res == "ok"
            built += res == "built"
            print(f"  [{i}/{len(pending)}] {tid}: {res}  (new: {got+built})", flush=True)
        else:
            fail += 1
            print(f"  [{i}/{len(pending)}] {tid}: fail", flush=True)
        time.sleep(delay)

    total = len([t for t in manifest if os.path.exists(f"{LOGS}/{t}.json")])
    print(f"\nDONE. new this run: {got} fetched + {built} built, {fail} failed", flush=True)
    print(f"corpus now: {total}/{len(manifest)} games downloaded", flush=True)


if __name__ == "__main__":
    main()
