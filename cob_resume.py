"""Download the games ALREADY enumerated in the manifest — no re-enumeration.

Built to run UNATTENDED from cron. cob_collect.py re-scans getRanking/getGames on
every launch before it downloads; once the manifest exists that work is redundant
(and it was the stall that cost the first run ~1.5h).

Three things this gets right — do not regress:

1. QUOTA BACK-OFF. BGA free accounts cap replays at ~10-16/day, and the cap is NOT
   liftable by Premium (verified: BGA's Premium page never mentions replays; users
   who bought it still hit the cap; an admin calls limits anti-abuse). The
   authoritative signal is the logs.html JSON:
       {"status": 0, "error": "You have reached a limit (replay)"}
   Do NOT probe archive/replay/ to detect this — when capped that page answers
   "500 Wrong siteversion", a red herring that reads like a per-game build failure.
   An earlier guard checked exactly that, never fired, and let a run hammer 63 dead
   requests. So: preflight ONE probe, and abort on the first quota answer anywhere.

2. BGA's DAY IS PARIS TIME (verified: utc+2 matches the server's own reference
   clock). The cap resets at midnight CEST = 15:00 local — NOT local midnight.

3. POLITE + RESILIENT. Long jittered delays (we only get ~16/day, so speed buys
   nothing and looks robotic), retry-with-backoff on transient network errors, and
   a hard stop if the session dies or non-quota failures pile up.

Usage: python cob_resume.py [delay_sec] [max_downloads]
"""
import json, os, random, sys, time, urllib.error
from datetime import datetime
import cob_collect as cc

CORP = "C:/Users/Forrest/CoB_corpus"
MANIFEST, LOGS = CORP + "/manifest.json", CORP + "/logs"
LOGFILE = CORP + "/resume_log.txt"

QUOTA_MSG = "reached a limit"
RETRIES = 3                 # attempts per request before calling it a real failure
BACKOFF = [5, 15, 45]       # seconds between retries
MAX_CONSEC_FAIL = 5         # non-quota failures in a row => something's broken, bail


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class AuthDead(Exception):
    """Session cookie expired — stop immediately, retrying can't help."""


def api_retry(url, cookie, token):
    """cc.api with backoff on TRANSIENT errors. Raises AuthDead on a dead session."""
    last = None
    for attempt in range(RETRIES):
        try:
            return cc.api(url, cookie, token)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise AuthDead(f"HTTP {e.code} — session likely expired")
            last = e
        except Exception as e:
            last = e
        if attempt < RETRIES - 1:
            wait = BACKOFF[attempt] + random.uniform(0, 3)
            log(f"    transient ({type(last).__name__}), retry in {wait:.0f}s")
            time.sleep(wait)
    raise last


def fetch_logs(cookie, token, tid):
    """-> (logs|None, quota_hit: bool). The logs endpoint is the quota oracle."""
    d = api_retry(f"https://boardgamearena.com/archive/archive/logs.html"
                  f"?table={tid}&translated=true", cookie, token)
    if d.get("status") == 1 and d.get("data", {}).get("logs"):
        return d["data"]["logs"], False
    err = str(d.get("error", ""))
    if "must be logged" in err.lower() or "not logged" in err.lower():
        raise AuthDead(err[:120])
    return None, QUOTA_MSG in err


def get_one(cookie, token, tid, path, delay):
    """-> 'ok' | 'built' | 'fail' | 'quota'."""
    logs, quota = fetch_logs(cookie, token, tid)
    if logs:
        json.dump(logs, open(path, "w"))
        return "ok"
    if quota:
        return "quota"
    # Archive not built yet -> trigger a replay build, wait, retry once.
    try:
        ti = api_retry(f"https://boardgamearena.com/table/table/tableinfos.html?id={tid}",
                       cookie, token)
        data = ti.get("data", {})
        gv = data.get("gameversion")
        p0 = (data.get("result", {}).get("player") or [{}])[0].get("player_id", "")
        if not gv:
            return "fail"
        cc.raw_get(f"https://boardgamearena.com/archive/replay/{gv}/"
                   f"?table={tid}&player={p0}&comments=", cookie, token)
    except AuthDead:
        raise
    except Exception as e:
        log(f"    build trigger failed: {type(e).__name__}")
        return "fail"
    time.sleep(delay + random.uniform(0, 3))
    logs, quota = fetch_logs(cookie, token, tid)
    if logs:
        json.dump(logs, open(path, "w"))
        return "built"
    return "quota" if quota else "fail"


def main():
    delay = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    max_dl = int(sys.argv[2]) if len(sys.argv) > 2 else 100

    try:
        cookie, token = cc.load_cookie()
    except Exception as e:
        log(f"FATAL: cannot read session cookie: {type(e).__name__}")
        return 1
    manifest = json.load(open(MANIFEST))
    os.makedirs(LOGS, exist_ok=True)

    pending = [t for t in manifest if not os.path.exists(f"{LOGS}/{t}.json")]
    have = len(manifest) - len(pending)
    log(f"=== run start | manifest {len(manifest)} | have {have} | pending {len(pending)} ===")
    if not pending:
        log("nothing pending — corpus complete.")
        return 0

    # PREFLIGHT: one probe. If the cap is already spent, every further call is waste.
    try:
        _, quota = fetch_logs(cookie, token, pending[0])
    except AuthDead as e:
        log(f"FATAL: session dead ({e}) — re-export the BGA cookie. Stopping.")
        return 2
    except Exception as e:
        log(f"preflight failed ({type(e).__name__}) — BGA may be down. Stopping.")
        return 1
    if quota:
        log("QUOTA already exhausted — not starting. "
            f"corpus stays at {have}/{len(manifest)}.")
        return 0

    got = built = fail = 0
    consec = 0
    for i, tid in enumerate(pending, 1):
        if got + built >= max_dl:
            log(f"reached max_downloads={max_dl}, stopping.")
            break
        try:
            res = get_one(cookie, token, tid, f"{LOGS}/{tid}.json", delay)
        except AuthDead as e:
            log(f"FATAL: session died mid-run ({e}) — re-export the cookie. Stopping.")
            break
        except Exception as e:
            res, _ = "fail", log(f"  {tid}: {type(e).__name__}")

        if res == "quota":
            log(f"*** QUOTA reached after {got+built} new downloads — backing off. ***")
            break
        if res in ("ok", "built"):
            got += res == "ok"
            built += res == "built"
            consec = 0
            log(f"  [{i}/{len(pending)}] {tid}: {res}  (new this run: {got+built})")
        else:
            fail += 1
            consec += 1
            log(f"  [{i}/{len(pending)}] {tid}: fail ({consec} in a row)")
            if consec >= MAX_CONSEC_FAIL:
                log(f"*** {consec} consecutive non-quota failures — bailing out. ***")
                break
        # Polite, jittered. We only get ~16/day, so speed buys nothing.
        time.sleep(delay + random.uniform(0, delay * 0.4))

    total = len([t for t in manifest if os.path.exists(f"{LOGS}/{t}.json")])
    log(f"run done: {got} fetched + {built} built, {fail} failed | "
        f"corpus {total}/{len(manifest)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
