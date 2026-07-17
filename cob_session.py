"""Self-refreshing BGA session.

WHY THIS EXISTS: cob_collect.load_cookie() pins a static PHPSESSID from a browser
export. PHPSESSID is short-lived, so a long unattended grind would eventually 401
and stall until a human re-exported cookies by hand.

THE KEY FACT (verified empirically): PHPSESSID is DISPOSABLE. Send only the
persistent ticket -- TournoiEnLignetkt (plus the sso_id/sso_user pair) -- with no
PHPSESSID at all, and BGA answers status:1 with real data AND mints a fresh
PHPSESSID back via Set-Cookie. So `tkt` is the real credential and the session
re-establishes itself with no password and no human.

Therefore: seed a cookie jar from the file and let Set-Cookie ride. The jar keeps
the freshly-minted PHPSESSID for the rest of the run, and each new run re-mints
from tkt. The file's PHPSESSID going stale becomes a non-event.

The ONLY thing that needs a human is `tkt` itself expiring (BGA's remember-me
ticket, typically long-lived). is_auth_error() spots that so callers can say so
plainly instead of retrying a dead credential.

REFRESHING THE SESSION (only needed if the TICKET dies — you'll see
"persistent ticket rejected" / "re-export the BGA cookie" in resume_log.txt):

  1. Log in to boardgamearena.com in the browser, ticking "remember me" so a
     fresh long-lived TournoiEnLignetkt is issued.
  2. DevTools -> Application -> Cookies -> https://boardgamearena.com
  3. Overwrite C:/Users/Forrest/.bga_session/session.txt with the cookie rows.
     Format is forgiving: either "NAME<tab>VALUE" per line or "k=v; k=v".
     Required: TournoiEnLignetkt, TournoiEnLigneidt, TournoiEnLigne_sso_id,
     TournoiEnLigne_sso_user. PHPSESSID is optional — it gets re-minted.
  4. Verify:  python -c "import cob_session; s=cob_session.Session(); \
                print(s.has_ticket(), s.api('https://boardgamearena.com/gamepanel/\
gamepanel/getRanking.html?game=1390&mode=elo&start=0')['status'])"
     Expect: True 1

The cron then picks straight back up — progress is on disk, nothing is lost.
"""
import http.cookiejar as cj
import json
import re
import urllib.request

import cob_collect as cc

# Cookies BGA actually needs. tkt = the persistent ticket (the real credential).
KEEP = ("TournoiEnLigne_sso_id", "TournoiEnLigne_sso_user",
        "TournoiEnLigneidt", "TournoiEnLignetkt", "PHPSESSID")


def _pairs():
    """Parse the exported session file -> {name: value}.

    Tolerates three hand-export formats (cookie NAMES are [A-Za-z0-9_]+; VALUES can contain
    '=', '%', etc., so always split on the FIRST delimiter only):
      1. `name: value`   (colon-space -- DevTools 'copy as' often uses this)
      2. `name<tab>value` / `name value`
      3. `k=v; k=v`      (a raw Cookie header)
    """
    raw = open(cc.COOKIE_FILE, encoding="utf-8").read()
    out = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^([A-Za-z0-9_]+)\s*:\s*"?(.+?)"?$', line)     # name: value
        if m:
            out[m.group(1)] = m.group(2).strip()
            continue
        m = re.match(r'^(\S+)[\t ]+"?([^"\s]+)"?', line)             # name<tab>value
        if m and "=" not in m.group(1) and ":" not in m.group(1):
            out[m.group(1)] = m.group(2)
        elif "=" in line:                                           # k=v; k=v
            for p in re.split(r";\s*", line):
                if "=" in p:
                    k, v = p.split("=", 1)
                    out[k.strip()] = v.strip()
    return out


class Session:
    """An opener whose jar starts from the file and then self-updates via Set-Cookie."""

    def __init__(self):
        p = _pairs()
        self.token = p.get("TournoiEnLigneidt", "")
        self.tkt = p.get("TournoiEnLignetkt", "")
        jar = cj.CookieJar()
        for k, v in p.items():
            if k in KEEP:
                jar.set_cookie(cj.Cookie(
                    0, k, v, None, False, ".boardgamearena.com", True, True,
                    "/", True, True, None, False, None, None, {}))
        self.jar = jar
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(jar))

    def has_ticket(self):
        return bool(self.tkt)

    def api(self, url):
        """JSON GET. The jar supplies cookies and absorbs any refreshed PHPSESSID."""
        req = urllib.request.Request(url, headers={
            "User-Agent": cc.UA, "X-Request-Token": self.token,
            "X-Requested-With": "XMLHttpRequest"})
        with self.opener.open(req, timeout=45) as r:
            return json.load(r)

    def raw_get(self, url):
        """GET that tolerates errors (the replay page 500s but still triggers a build)."""
        req = urllib.request.Request(url, headers={"User-Agent": cc.UA})
        try:
            with self.opener.open(req, timeout=60) as r:
                return r.read()
        except Exception:
            return b""

    def has_session(self):
        """True if a PHPSESSID is present. Deliberately returns a BOOLEAN, never any
        part of the value — a live session token must not reach logs or a transcript,
        and a truncated prefix is still the secret."""
        return any(c.name == "PHPSESSID" for c in self.jar)

    def _session_value(self):
        """Internal only: used to DETECT a re-mint by comparison. Never printed."""
        for c in self.jar:
            if c.name == "PHPSESSID":
                return c.value
        return None


def is_auth_error(err_text):
    """True only when the persistent TICKET is dead — i.e. a human must re-export."""
    t = str(err_text).lower()
    return "must be logged" in t or "not logged" in t or "invalid session" in t
