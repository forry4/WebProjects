"""Full BGG harvest for the filter tool.

BGG's XML API needs a registered app token now, so this uses the endpoints the
website itself calls:
  /search/boardgame  advanced search  - ranked list, filtered server-side
  /geekitempoll.php  action=view      - find a game's player-count poll id
  /geekpoll.php      action=results   - the Best/Recommended/Not-Rec vote matrix
  api.geekdo.com/api/dynamicinfo      - exact weight + rating stats

The advanced search hard-caps at 50 pages, so the universe is enumerated in
weight bands and de-duplicated by id.
"""
import json, os, re, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
MIN_RATINGS = 500
BANDS = [(1.0,1.5),(1.5,2.0),(2.0,2.5),(2.5,3.0),(3.0,3.5),(3.5,4.0),(4.0,5.0)]
WORKERS = 6
COUNTS = ["1","2","3","4","5"]

_sem = threading.Semaphore(WORKERS)
_done = [0]
_lock = threading.Lock()


CHALLENGE = ("Just a moment", "cf-browser-verification", "__cf_chl",
             "Attention Required", "Checking your browser")


def reject(body, accept):
    """Why this response is unusable, or None if it looks real.

    Cloudflare answers a burst with a 200-OK challenge page. Caching one of
    those silently truncated three whole weight bands on the first run, so a
    response has to prove itself before it is written to the cache.
    """
    if not body.strip():
        return "empty body"
    if any(s in body for s in CHALLENGE):
        return "cloudflare challenge"
    if "json" in accept:
        head = body.lstrip()[:1]
        if head not in ("{", "["):
            return "expected json, got " + repr(body.lstrip()[:40])
    elif len(body) < 4000:
        return f"suspiciously short html ({len(body)}b)"
    return None


def fetch(url, key=None, accept="text/html,*/*;q=0.8", tries=5):
    if key:
        p = os.path.join(CACHE, key)
        if os.path.exists(p) and os.path.getsize(p) > 0:
            return open(p, encoding="utf-8", errors="replace").read()
    last = None
    for a in range(tries):
        try:
            with _sem:   # BGG 403s Python's TLS fingerprint -> go through curl
                r = subprocess.run(
                    ["curl", "-sS", "--compressed", "--max-time", "45", "-A", UA,
                     "-H", "Accept-Language: en-US,en;q=0.9", "-H", "Accept: " + accept, url],
                    capture_output=True, timeout=60)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.decode("utf-8", "replace")[:160])
            body = r.stdout.decode("utf-8", "replace")
            bad = reject(body, accept)
            if bad:
                raise RuntimeError(bad)     # never cache a challenge/garbage response
            if key:
                open(os.path.join(CACHE, key), "w", encoding="utf-8").write(body)
            return body
        except Exception as e:
            last = e
            time.sleep(min(60, 5 * (a + 1) ** 2))
    raise RuntimeError(f"failed {url}: {last}")


SEARCH = ("https://boardgamegeek.com/search/boardgame/page/{pg}?advsearch=1"
          "&range%5Bnumvoters%5D%5Bmin%5D={mv}"
          "&floatrange%5Bavgweight%5D%5Bmin%5D={lo}&floatrange%5Bavgweight%5D%5Bmax%5D={hi}"
          "&sort=rank&sortdir=asc")

ROW = re.compile(
    r"<td class='collection_rank'.*?>\s*(?:<a name=\"\d+\"></a>)?\s*([\d]+|N/A)\s*</td>.*?"
    r"href=\"/boardgame/(\d+)/[^\"]*\"\s*class='primary'\s*>([^<]*)</a>\s*"
    r"(?:<span class='smallerfont dull'>\((\d{4})\)</span>)?.*?"
    r"<td class='collection_bggrating' align='center'>\s*([\d.]+|N/A)\s*</td>\s*"
    r"<td class='collection_bggrating' align='center'>\s*([\d.]+|N/A)\s*</td>\s*"
    r"<td class='collection_bggrating' align='center'>\s*([\d]+|N/A)\s*</td>", re.S)


def search_page(lo, hi, pg):
    html = fetch(SEARCH.format(pg=pg, mv=MIN_RATINGS, lo=lo, hi=hi), f"s_{lo}_{hi}_{pg}.html")
    out = []
    for rank, gid, name, year, geek, avg, v in ROW.findall(html):
        out.append({
            "id": gid, "n": " ".join(name.split()),
            "y": int(year) if year else None,
            "rk": int(rank) if rank.isdigit() else None,
            "geek": float(geek) if geek != "N/A" else None,
            "avg": float(avg) if avg != "N/A" else None,
            "v": int(v) if v != "N/A" else 0,
        })
    return out


def poll_matrix(gid):
    """{count: [best, recommended, not_recommended]} plus the poll's voter total."""
    view = fetch("https://boardgamegeek.com/geekitempoll.php?action=view"
                 f"&itempolltype=numplayers&objecttype=thing&objectid={gid}",
                 f"pv_{gid}.json", accept="application/json")
    try:
        pid = json.loads(view)["poll"]["pollid"]
    except Exception:
        return None, 0
    res = fetch(f"https://boardgamegeek.com/geekpoll.php?pollid={pid}&action=results",
                f"pr_{gid}.json", accept="application/json")
    try:
        d = json.loads(res)
        q = d["pollquestions"][0]["results"]
    except Exception:
        return None, 0
    col = {"Best": 0, "Recommended": 1, "Not Recommended": 2}
    m = {}
    for cell in q.get("results", []):
        row, c = cell["rowbody"], cell["columnbody"]
        if row in COUNTS and c in col:
            m.setdefault(row, [0, 0, 0])[col[c]] = int(cell["votes"])
    return m, int(d["poll"].get("voters") or 0)


def enrich(g):
    try:
        st = json.loads(fetch("https://api.geekdo.com/api/dynamicinfo"
                              f"?objectid={g['id']}&objecttype=thing",
                              f"dy_{g['id']}.json", accept="application/json"))["item"]["stats"]
        g["w"] = round(float(st.get("avgweight") or 0), 4) or None
        g["v"] = int(st.get("usersrated") or g["v"])
        if st.get("baverage"): g["geek"] = round(float(st["baverage"]), 4)
        if st.get("average"):  g["avg"] = round(float(st["average"]), 4)
    except Exception:
        g["w"] = None
    m, tot = poll_matrix(g["id"])
    g["p"] = m or {}
    g["pt"] = tot
    with _lock:
        _done[0] += 1
        if _done[0] % 400 == 0:
            print(f"    enriched {_done[0]}", flush=True)
    return g


def main():
    seen, games = set(), []
    for lo, hi in BANDS:
        n0, pg = len(games), 1
        while pg <= 50:
            rows = search_page(lo, hi, pg)
            if not rows:
                break
            for r in rows:
                if r["id"] not in seen:
                    seen.add(r["id"]); games.append(r)
            pg += 1
        print(f"band {lo}-{hi}: {pg-1} pages, +{len(games)-n0} new ({len(games)} total)", flush=True)

    print(f"\nenriching {len(games)} games (weight + full player-count poll)...", flush=True)
    with ThreadPoolExecutor(WORKERS) as ex:
        games = list(ex.map(enrich, games))

    nof = [g for g in games if not g.get("w")]
    if nof:
        print(f"  WARNING: {len(nof)} games had no weight and were dropped", flush=True)
    games = [g for g in games if g["rk"] is not None and g["geek"] and g["w"]]
    games.sort(key=lambda g: -g["geek"])
    out = os.path.join(HERE, "results_all.json")
    json.dump({"min_ratings": MIN_RATINGS, "games": games},
              open(out, "w", encoding="utf-8"), indent=None)
    print(f"\nDONE {len(games)} ranked games -> {out}", flush=True)
    withpoll = sum(1 for g in games if g["p"].get("2"))
    print(f"  with a 2-player poll row: {withpoll}", flush=True)


if __name__ == "__main__":
    main()
