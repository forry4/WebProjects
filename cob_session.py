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

When `tkt` itself expires, Session.login() AUTO-RENEWS it: a real BGA login with
stored credentials (env BGA_EMAIL/BGA_PASSWORD or CREDS_FILE) mints a fresh
remember-me ticket, saves it to the session file, and the grind continues with no
human. is_auth_error() spots the dead ticket so callers relogin instead of retrying
a dead credential; a human is only needed if login() also fails (bad password /
CAPTCHA / 2FA).

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
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import cob_collect as cc

# Cookies BGA actually needs. tkt = the persistent ticket (the real credential).
KEEP = ("TournoiEnLigne_sso_id", "TournoiEnLigne_sso_user",
        "TournoiEnLigneidt", "TournoiEnLignetkt", "PHPSESSID")

# Credentials for AUTO-RENEW (Session.login): env BGA_EMAIL/BGA_PASSWORD first, else this
# file (same private dir as the session file, OUTSIDE the repo). Never commit real creds.
CREDS_FILE = os.path.join(os.path.dirname(cc.COOKIE_FILE), "login.txt")
# BGA's login contract (endpoint + field names), captured from a real login HAR (2026-07-19):
#   POST .../account/auth/loginUserWithPassword.html
#   body: username, password, remember_me=true, request_token   (+ X-Request-Token header)
# The request_token is the page's `requestToken` (64-hex), tied to the PHPSESSID the same jar
# just picked up, so the token GET and the login POST MUST share one opener (they do).
LOGIN_URL = "https://en.boardgamearena.com/account/auth/loginUserWithPassword.html"
TOKEN_URL = "https://en.boardgamearena.com/"


def _load_creds():
    """(email, password) from env (BGA_EMAIL/BGA_PASSWORD) or CREDS_FILE.
    File format is forgiving: `email: you@x.com` / `password: ...` (or `=`), one per line;
    keys email|user|username|login all mean the login id, pass|password the secret."""
    email = os.environ.get("BGA_EMAIL", "").strip()
    pw = os.environ.get("BGA_PASSWORD", "")
    if email and pw:
        return email, pw
    try:
        for line in open(CREDS_FILE, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r'(?i)^(email|user(?:name)?|login|pass(?:word)?)\s*[:=]\s*"?(.+?)"?$', line)
            if not m:
                continue
            k, v = m.group(1).lower(), m.group(2).strip()
            if k.startswith("pass"):
                pw = pw or v
            else:
                email = email or v
    except FileNotFoundError:
        pass
    return email, pw


def _write_session(jar):
    """Persist the KEEP cookies (name<tab>value) so the next run reuses the fresh ticket."""
    lines = [f"{c.name}\t{c.value}" for c in jar if c.name in KEEP and c.value]
    os.makedirs(os.path.dirname(cc.COOKIE_FILE), exist_ok=True)
    tmp = cc.COOKIE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, cc.COOKIE_FILE)


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

    def login(self, log=lambda m: None):
        """AUTO-RENEW: mint a FRESH ticket via a real BGA login (email+password), persist the
        new cookies to the session file, and adopt the live jar. Returns True on success.

        This is what removes the human from the loop when the remember-me ticket dies: on an
        auth error the caller calls this instead of stopping. A dead ticket must NOT ride along,
        so we log in on a clean jar. Fails cleanly (returns False, logs why) when there are no
        credentials, or when BGA answers with a CAPTCHA/2FA challenge or rejects the password."""
        email, pw = _load_creds()
        if not email or not pw:
            log(f"auto-login: no credentials — set BGA_EMAIL/BGA_PASSWORD or write {CREDS_FILE} "
                "(email: / password: lines). Cannot renew the ticket automatically.")
            return False
        jar = cj.CookieJar()   # clean jar — the dead ticket does not ride along
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        # 1) a fresh request token (BGA embeds `requestToken` in the page bootstrap); it must
        #    ride the SAME opener/PHPSESSID as the login POST below.
        token = ""
        try:
            req = urllib.request.Request(TOKEN_URL, headers={"User-Agent": cc.UA})
            html = opener.open(req, timeout=45).read().decode("utf-8", "replace")
            m = re.search(r'requestToken["\']?\s*[:=]\s*["\']([A-Za-z0-9]+)', html)
            token = m.group(1) if m else ""
        except Exception as e:
            log(f"auto-login: could not fetch request token ({type(e).__name__})")
        if not token:
            log("auto-login: no request_token on the login page — BGA changed the bootstrap.")
            return False
        # 2) POST credentials WITH remember_me so the new ticket is long-lived
        body = urllib.parse.urlencode({
            "username": email, "password": pw, "remember_me": "true", "request_token": token,
        }).encode()
        headers = {"User-Agent": cc.UA,
                   "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                   "Origin": "https://en.boardgamearena.com",
                   "Referer": "https://en.boardgamearena.com/?step=2&page=login",
                   "X-Request-Token": token}
        try:
            req = urllib.request.Request(LOGIN_URL, data=body, headers=headers)
            payload = opener.open(req, timeout=45).read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            log(f"auto-login: HTTP {e.code} from the login endpoint")
            return False
        except Exception as e:
            log(f"auto-login: request failed ({type(e).__name__})")
            return False
        # success = a fresh ticket cookie is now in the jar (login mints it via Set-Cookie)
        tkt = next((c.value for c in jar if c.name == "TournoiEnLignetkt"), "")
        try:
            ok = json.loads(payload).get("status") in (1, "1", True)
        except Exception:
            ok = bool(tkt)
        if not (tkt and ok):
            log("auto-login: rejected — no fresh ticket issued. Likely a wrong password, a "
                "CAPTCHA/2FA challenge, or a changed login contract. Manual re-export needed.")
            return False
        self.jar, self.opener, self.tkt = jar, opener, tkt
        self.token = next((c.value for c in jar if c.name == "TournoiEnLigneidt"), self.token)
        _write_session(jar)
        log("auto-login: fresh ticket minted and saved to the session file.")
        return True

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
