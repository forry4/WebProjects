# Forrest Games — Claude Context

A four-game multiplayer board-game website (+ a Books feature) sharing one backend, auth
layer, and frontend shell. Real-time play over WebSockets, server-authoritative game state,
and per-game AI opponents that range from simple heuristics to client-side neural nets
compiled to WASM.

**This file is the cross-cutting operating manual** — what applies no matter which part you touch.
Per-area detail lives in a `CLAUDE.md` next to the code, loaded when you read files there:

| File | Covers |
|---|---|
| [`games/spender/CLAUDE.md`](games/spender/CLAUDE.md) | Spender engine/backend, the AI variant zoo, Puzzle mode, and `Spender.jsx` (also the site shell) |
| [`games/castles_of_crimson/CLAUDE.md`](games/castles_of_crimson/CLAUDE.md) | CoC engine contract, AI tiers, frontend layout maths |
| [`games/wherewolf/CLAUDE.md`](games/wherewolf/CLAUDE.md) | WW roles, redaction matrix, night conductor |
| [`games/spender_duel/CLAUDE.md`](games/spender_duel/CLAUDE.md) | Duel engine, hidden info, and the current coherent/minimax search |
| [`shared/CLAUDE.md`](shared/CLAUDE.md) | Shared frontend kits + URL routing |
| [`books/CLAUDE.md`](books/CLAUDE.md) | The Books feature |
| [`docs/ai-research-log.md`](docs/ai-research-log.md) | **AI campaign history, dated sessions, rejected-experiment postmortems.** When something here says "see the research log," that's the blow-by-blow + "do not relitigate" detail. |

---

## Tech stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI + asyncio, one uvicorn process; SQLite locally / **Turso (libSQL)** in prod |
| Realtime | WebSockets (one per room+player); in-memory `ROOMS` under a single `asyncio.Lock` |
| Frontend | React 18, plain JS (no TypeScript), Vite 6, one self-contained `.jsx` per game |
| AI | determinized MCTS / PUCT; heuristics; learned nets served **client-side via Rust→WASM** |
| Deploy | Backend → Render; Frontend → GitHub Pages (Actions pipeline); Cloudflare staging mirror |

- **Server is authoritative for all game state.** Clients render and send moves; the server
  validates every move through the engine. Client-side AI is safe because tampering only weakens
  the tamperer's own opponent (the move is still validated server-side before it's applied).
- **Games**: Spender (Splendor), Castles of Crimson (Castles of Burgundy), Where Wolf? (One Night
  Ultimate Werewolf), Spender Duel (Splendor Duel). Plus **Books** (a ranking/suggestions page)
  and **WWSD** (a browser autoplayer for a friend's external Splendor site).

### Run it locally
- Backend: `python -m uvicorn app:app --reload --port 8000` (the composition-root app at repo root).
  Spender is a `router` included by the root `app` (no separate Spender server); the deploy shim
  `games/spender/app.py` just re-exports the root `app`.
- Frontend: `cd webapp && VITE_BASE=/ VITE_WS_URL=wss://splendid-nelz.onrender.com/ws npm run dev`
  — HMR against the **prod backend** is the fastest loop (resume a real game from your account).
  For a fully local stack point `VITE_WS_URL` at `ws://localhost:8000/ws`.
- **Vite MUST run on port 5173** — `core/config.py` CORS only allowlists `localhost:5173`; on 5174
  the browser fetch is CORS-blocked and the app hangs on the loader.
- Smoke gate before pushing frontend: `cd webapp && npm run smoke` (see Testing — it is weaker than
  it looks).
- Distinct local players need **distinct browser storage** — two incognito windows in the same
  browser share `localStorage` → same `spender_myId` → they collapse into one identity. Use
  different browsers/profiles.

---

## Repo layout

```
app.py                 # COMPOSITION ROOT: FastAPI app + CORS/security middleware + feature wiring
core/                  # SHARED BACKEND PLATFORM (imported by every feature; imports no game)
  db.py                #   dual sqlite/Turso conn wrapper + get_db_conn + init_core_schema + retention
  auth.py              #   users/sessions/passwords, admin + SITE_OWNER identity, reconnect tokens
  ratelimit.py         #   SlidingWindowLimiter (auth + WebSocket abuse throttle)
  config.py            #   cors_allowed_origins()
  rooms.py             #   shared room-server primitives (normalize/token/db/send/delete/release_socket)
  build_info.py        #   commit + started_at for /health, so a deploy can be VERIFIED not assumed
games/
  spender/             # Spender (Splendor) — main.py exposes `router` (APIRouter), + ai/ stack
                       #   engine.py = the rules (single source of truth); cards.py = static card data
  castles_of_crimson/  # CoC — engine.py + ai.py + main.py (coc_app @ /coc) + CastlesOfCrimson.jsx
  wherewolf/           # Where Wolf? — engine.py + main.py (werewolf_app @ /werewolf) + WhereWolf.jsx
  spender_duel/        # Spender Duel — engine.py + ai.py + main.py (duel_app @ /duel) + SpenderDuel.jsx
books/                 # Books feature (wired into the app, not a sub-app)
shared/                # theme.js (baseCss), lobby.jsx, splendor.jsx, router.js — cross-game frontend kits
                       #   + AuthScreen.jsx / HomeScreen.jsx — site-SHELL screens, here for the
                       #   dependency direction (games -> shared, never back)
webapp/                # Vite + React build (neutral, repo-root) — main.jsx mounts Spender.jsx (the shell)
  test/                #   smoke.mjs (blank-page/CLS gate) + screens.mjs (real render gate)
wwsd/                  # "What Would Steve Do" — browser autoplayer for a friend's external site
rust-cores/            # Per-game Rust→WASM search crates (client-side serving). NOT the Python core/.
  spender-core/        #   Spender variant S/N search core
  coc-core/            #   CoC Expert (netval) search core
  duel-core/           #   Duel attention-net search core
docs/                  # GitHub Pages build output + ai-research-log.md
```

**Naming caution:** `core/` (top-level, singular) is the **Python** backend platform every feature
imports. `rust-cores/*-core/` are **Rust→WASM** crates, one per game — build artifacts, imported by
nothing in Python. They are per-game siblings (like `games/*`), not part of `core/`.

**Layering:** `core/` (bottom, depends on nothing) → features (games, books) → `app.py` (top). The
composition root depends on features; features depend only on `core`. This is the extraction that
removed the old circular imports — **never reintroduce a `games.*` import into `core/`.** Each game is
a thin FastAPI sub-app (`rooms`/WS/REST/persistence) that delegates all rules to its pure `engine.py`.
Root-level `render.yaml`/`docs/` stay at root (the Docker image is built from `games/spender/Dockerfile`
per `render.yaml`).

---

## Shared backend platform (`core/`)

- **`core/db.py`** — `get_db_conn()` is a dual backend behind a driver-agnostic wrapper
  (`_Conn`/`_Cursor`/`_Row` — rows work by index AND column name). Local **sqlite3** by default;
  **Turso/libSQL** when `TURSO_DATABASE_URL`+`TURSO_AUTH_TOKEN` are set. A boot-time `_turso_selftest()`
  round-trips a row and **falls back to local sqlite on any failure** (site stays up, just
  non-persistent). `init_core_schema(conn)` creates `users`/`admins`/`reconnect_tokens`.
  `cleanup_stale_games(table)` / `maybe_cleanup_games(table)` handle retention (all-guest game 24h,
  any-registered-player 30d).
- **`core/auth.py`** — sessions/passwords (PBKDF2 + legacy), `create_user`/`authenticate_user`/
  `get_user_by_session`, `validate_credentials` (register: name 1–16 `[A-Za-z0-9]`, password 1–16),
  SITE_OWNER/admin helpers, reconnect-token create/validate/mark-used + throttled cleanup.
- **`core/config.py`** — `cors_allowed_origins()` **merges** `CORS_ALLOWED_ORIGINS` env with the always-on
  defaults (Pages `forry4.github.io`, the Cloudflare staging worker, localhost). Do NOT make it
  replace-semantics — that once silently locked out the staging mirror.
- **`app.py`** creates `app = FastAPI()`, applies CORS + a pure-ASGI `SecurityHeadersMiddleware`
  (threaded into the mounted sub-apps too), `include_router`s Spender's `router`, `setup_books(...)`,
  `setup_puzzles(...)`, and mounts CoC/WW/Duel each behind a **defensive try/except** (so the core
  backend never goes down if a game package is absent). No CSP on the API (it serves JSON).

**Persistence:** Render's free filesystem is ephemeral, so prod uses Turso. **Turso is LIVE and verified
on Render — prod IS persistent; don't tell the user to set it up.** The libsql path **cannot be tested
locally** (no wheel for Python 3.14 on this box; prod Docker is 3.11) — validate it via Render logs + a
login that survives a redeploy. The sqlite path (identical wrapper) IS locally tested.

### Auth correctness & security (hard-won — do not regress)
- **WS SEAT IDENTITY IS BOUND IN ALL FOUR GAMES.** The `player` path segment is client-supplied and
  every pid is broadcast in the public players map, so a socket must PROVE it owns its pid before it
  can act as that seat or receive that seat's view. `authed` flips true only via create / join-as-a-new-
  seat / join-with-a-matching-`session_token` / reconnect-with-the-room-token / auth_reconnect; every
  mutating action is gated on it. Frontends send `session_token` on join. Tests: each game's
  `tests/test_ws_auth.py`.
- **NEVER register a socket in `room["sockets"]` before that handshake.** Spender used to, at connect
  time, and `broadcast_room` rebuilds state PER RECIPIENT keyed on the socket's pid — so merely opening
  a socket claiming a victim's pid and sending NOTHING returned that seat's blind reserves AND its
  `reconnect_tokens` entry, which replays as `{"action":"reconnect"}` for a full takeover. It also
  displaced the victim's live socket. (The follow-on trap: that registration was also what made the room
  get cleaned up, so removing it leaked an empty `ROOMS` shell per connect — `core.rooms.release_socket`
  now collects phantom rooms independently of socket ownership.)
- **Any new broadcast field must be per-field redacted** — "an honest client ignores it" is NOT security.
  A 2026-07 audit found 3 of 4 games shipping raw hidden ordered state (Spender `decks`, WW `deck`, CoC
  supplies + `rng_state`).
- **`is_admin` is computed the same way on every path** — `is_admin_id(conn, id)` (plain SELECT) or a
  live `SITE_OWNER` username match. NEVER a correlated subquery — it reads NULL on the libsql driver
  (works on sqlite → invisible in tests), which made the owner lose admin on every session refresh.
- **Usernames are unique case-insensitively** — `users.name` has no UNIQUE constraint, so `create_user`
  checks `WHERE name=? COLLATE NOCASE` and `init_core_schema` builds `idx_users_name_ci`. Login too.
- **Tokens use a CSPRNG** (`secrets`, not `random`) — session/account/reconnect tokens AND password salts.
- **Auth rate-limited** (in-memory, per-process — OK because one uvicorn process): login 20/5min per IP +
  10 failures/15min per username (resets on success); register 10/hr per IP. Over-limit returns HTTP 200
  `{ok:False, message}` so the existing error UI shows it.
- **Session token in `Authorization: Bearer`**, not the URL (with a `?token=` fallback for cached
  clients). WS uses room-meta/reconnect tokens in the message body, never the URL.

---

## Shared room-server pattern (mirrored in every game's `main.py`)

Each game's `main.py` builds the same scaffolding: in-memory `ROOMS: dict[str, dict]` under a single
`ROOM_LOCK`, `save_game`/`load_game_to_memory`, `broadcast_room`, `mk_room_state`, a stale-socket
disconnect guard, and an async opponent scheduler.

```python
ROOMS[room_id] = {
  "players": {pid: name}, "sockets": {pid: WebSocket},
  "status": "open"|"playing"|"over", "host": pid,
  "game": {...} | None, "meta": {pid: {"token": str, ...}},
}
```

**The generic half lives in `core/rooms.py`** (all four games use it, aliased to their historical
private names): `normalize_room`, `gen_room_token`, `db_conn`, `ensure_room_loaded`, `send_json`,
`delete_open_game(table, host_col, ...)`, and `release_socket` (the stale-socket guard + phantom-room
collection; per-game policy stays explicit as the `disarm_client_ai` / `drop_empty_open_only` flags).
Extracting it was not tidiness: the same hidden-info broadcast leak had to be found and fixed THREE
times because three copies of `mk_room_state` each leaked differently.

**Still duplicated (~25 functions, the obvious next extraction):** `save_game`, `load_game_to_memory`,
`_persist_row` and the `list_open_games`/`list_user_games`/`list_user_history`/`list_active_games`
family. Same shape in all four games, differing only in table name and columns.

**Load-bearing invariants across all four games:**
- **Pending sub-decisions are real game-state keys**, not transient message fields — so they survive
  saves/reconnects and are server-enforced (Spender `pending_noble_pid`/`pending_discard_pid`; CoC and
  Duel `pending_pid`/`pending_kind`/`pending`; WW `night_step`). A stray `room_update` can't clear an
  unmet requirement.
- **The game dict is JSON-safe** (no sets anywhere; RNG persisted as lists in `rng_state`) → reconnect-
  and save/load-safe.
- **AI turns run in a thread pool, never under `ROOM_LOCK`.** `_schedule_*_turn` snapshots under the lock
  → releases → runs the search via `loop.run_in_executor` → re-locks → re-validates turn/phase hasn't
  changed → applies → saves + broadcasts outside the lock. **OUTAGE LESSON (do not regress): never loop
  heavy synchronous engine work under `ROOM_LOCK` on the event-loop thread** — a CoC rewrite that did
  ~12 sync bot turns + ~12 DB saves under the lock hung the loop and took prod down.
- **Stale-socket disconnect guard**: the WS `finally` only removes a socket / deletes a room if
  `r["sockets"].get(pid) is websocket` (the exact object for this handler) — prevents a reconnect race
  (WS1→WS2) from deleting the live room.
- **Cancel/delete must use SELECT-then-DELETE, not `cur.rowcount`** — the libsql wrapper doesn't expose
  `rowcount` (it raised → 500'd the cancel endpoint in prod).
- `_schedule_*_turn` is safe to call any time (internal guards no-op when it's not the AI's turn / not
  playing) — deliberately called after reconnect to unstick socket-dropped games.

---

## Cross-game AI facts (do not relitigate — per-game tiers in each package's `CLAUDE.md`)

- **A client-WASM worker pool must NEVER take every core.** The search is CPU-bound; a pool that pegs
  all of them starves the browser's main/compositor/raster threads and the animations stutter while the
  AI thinks. Each game sizes its own pool by hand, so the rule has to be re-applied every time: Spender
  `min(hc-1, 4)`, Duel `min(hc-1, 4)`, CoC `hc<=4 ? hc-1 : min(hc-2, 8)`. Spender had it; **Duel and CoC
  shipped without it for months.** Only bites at ≤4 cores (the caps dominate above that).
- **Determinization is a correctness requirement, not a strength knob** — the AI holds the real game
  dict server-side, so it must resample everything it can't legally see (decks, opponent blind reserves,
  future dice), canonicalizing each pool before reshuffling so the search provably can't read hidden order.
- **Scoring BOTH seats with the same eval and subtracting makes denial fall out of the search for free**
  — no "contested-card" knob (Spender `v_state`, Duel `_standing`, CoC via `heuristic::value`).
- **A resource must not out-score what it converts into** (privileges/gold/reserves vs their sink) — the
  documented buy-nothing / hoard-forever collapse.
- **Break MCTS visit ties by mean value, not first index** — Splendor/Duel have no turn limit, so a
  plain `max(visits)` bot takes tokens forever and the game never ends.
- **Static-vs-rollout leaf is game-specific and MEASURED, never assumed:** Spender/Duel → static leaf
  beats rollout (A/B by equal *time*); CoC → a short rollout is needed (delayed payoffs). The repo has
  opposite precedents on purpose. Note the cost side doesn't transfer either — rollout is ~free behind
  Duel's attention leaf but expensive behind a heuristic one.
- **The strength lever is SEARCH (sims throughput and search *soundness*), not eval re-weighting** —
  every eval-weight and eval-feature tuning campaign saturated. Duel's 2026-07-26 coherent-search and
  minimax fixes are the current proof that soundness bugs can hide under noise for a whole campaign.
- **Benchmark offline only** (per-game `ai_selfplay` / arena / gate bins) — never in a serving path.
  Judge with CRN paired arenas + a mirror sanity that must read exactly 0.5000; the ship criterion is
  EQUAL-TIME, not equal-sims.
- **A measurement harness must reproduce the SERVING shape.** Duel serves a 4-worker root-summed
  ensemble; a whole campaign of single-tree numbers had to be re-confirmed at `--pool 4`.

---

## Testing

- **The suite is defined ONCE** in `pytest.ini` `testpaths`; both CI workflows run a bare `pytest`.
  They used to carry two hand-maintained path lists that drifted (Duel's tests ran only at deploy).
- **Rules/engine unit tests are the most valuable to protect** — each game has them (per-package
  `CLAUDE.md` lists what each covers), plus `core/tests/` (db/auth/ratelimit/retention, in-memory
  sqlite) and Books `tests/` (17, in-memory DB).
- **CI runs `core/tests/` first; Render deploy is gated on tests.** Frontend deploy is gated by
  `npm run smoke` AND `npm run screens`.
- **`npm run smoke` NEVER RENDERS A GAME — don't mistake it for render coverage.** The shell pings the
  backend before it routes, and smoke has no backend, so all three of its routes sit on the loading
  screen. It genuinely catches a blank page, a bundle that throws at load, and layout shift. That is all.
- **`npm run screens` is the real render gate** (`webapp/test/screens.mjs`): boots the actual backend,
  builds, serves on **5173** (load-bearing — `core/config.py` only allowlists that port for CORS;
  anywhere else the fetch is blocked and the app hangs on the loader), seeds a guest identity, and
  asserts each game route mounts ITS OWN markup (`.duel`/`.coc`/`.ww`/`.bk-app`), fetches its lazy
  chunk, and logs no page errors. Proven to work by injecting a mount-time throw into WhereWolf:
  **smoke PASSED, screens FAILED** with the exact TypeError. It builds first on purpose — a failed
  build leaves the previous working `dist/` in place, which once made a broken change look green.
- **The four games + Books are CODE-SPLIT** (`React.lazy` in Spender.jsx): the entry chunk is ~310KB
  instead of ~600KB. Adding a game screen means a `lazy()` + `<Suspense>` branch, and a `SCREENS` entry
  in `webapp/test/screens.mjs`.
- **The WS throttle is process-global and keyed on client IP** (`core.rooms`, 60 connects/min,
  300 msgs/min). Test fake sockets all report `"unknown"`, so they share ONE budget: any test module
  driving `ws_room_player` MUST reset `_rooms._ws_connect_limiter` per test, or the suite eventually
  throttles itself and the failures look like anything but a rate limit (measured: 90 of 150
  in-process connects rejected without the reset).
- **Rust parity:** CoC — regen fixtures via `gen_engine_fixtures.py`, then `cargo test --release
  --features bridge`. Spender — `cargo test --lib` (`src/bin/*` need `--features bridge`).

---

## Footguns (grouped — the expensive-to-relearn traps)

**Shell / MSYS / worktrees**
- **Git Bash auto-converts `/c/...` args for native exes but SKIPS args containing `*`, `:`, or `;`** — so
  globs, `path:spec` gate args, and `a.csv;b.csv` reach the exe unconverted → silent no-op. Pass
  Windows-style `C:/...` paths (cygpath) to native tools.
- **`python -m pkg.mod` runs the CWD's worktree code, not `PYTHONPATH`'s** — always `cd <worktree>` before
  `python -m` / `cargo` / `wasm-pack` / `cythonize`. rustup is at `~/.cargo/bin` (off PATH → prepend it).

**Frontend / CSS**
- **CSS lives in real `.css` files, imported with `?inline`** (`games/*/X.css`, `shared/*.css`) — the
  string is still injected by each component's own `<style>` tag, only while mounted, so CoC's bare
  mount and its `html,body` reset are unaffected. This RETIRED the repo's most expensive footgun: CSS
  used to be a `const css = ` \` … \` template literal, where one stray backtick terminated the literal,
  reparsed the rest of the file as a tagged template, and blanked the page — it shipped a blank deploy
  twice. **Do not move CSS back into a JS literal.** The smoke test's backtick guard is kept as a net.
  `build.cssMinify` is deliberately **false**: keeping the emitted CSS byte-identical made the move
  provably behaviour-free (worth ~45KB if you ever turn it on deliberately, with a visual check).
- **Media-query cascade ordering**: mobile `@media` blocks sit BEFORE the base rules, so a single-class
  mobile override loses to a later equal-specificity base rule. Every mobile override must be
  higher-specificity (e.g. `.coc `-prefixed).
- Shared-kit CSS with `var(--token, fallback)` must be appended AFTER a game's `* {margin:0;padding:0}`
  reset (CoC's bare mount) or the reset zeros its padding.

**Backend / DB**
- **libsql has no `cur.rowcount`** → use SELECT-then-DELETE/UPDATE for any affected-row count (it 500'd
  the cancel endpoint).
- **Turso can't be tested locally** (no libsql wheel on Python 3.14) — validate via Render logs + a login
  surviving a redeploy.
- Never use a correlated subquery for `is_admin` (NULL on libsql); usernames are unique NOCASE.

**Cython (Spender `valuation3`)**
- **A compiled `valuation3.pyd`/`.so` SHADOWS the `.py`** — recompile (`cythonize -i -3 …/valuation3.py`)
  after ANY edit or workers silently run stale code. Prod builds its own Linux `.so` in the Dockerfile
  (build FAILS on miscompile, so a bad compile can't reach prod).

**Deploy verification**
- **Verify a Pages deploy by a CONTENT marker in the live bundle, not the filename hash** (CDN lag / Vite
  chunking can keep the hash looking unchanged). The `deploy-pages.yml` run status is authoritative.
- **A stale `vite preview --port 5173` process serves an OLD `dist/`** — kill listeners on the port before
  serving, confirm the fresh bundle by a content marker.
- **Never blind-push `staging:main`** — `staging` has DIVERGED (behind main on backends). A force-push
  would wipe main's backend history. To ship staging frontend, branch off `origin/main` and selectively
  take/merge only the intended files.

---

## Build + deploy

**The build is CI-owned — NEVER build or commit the frontend bundle by hand.** Pages source = "GitHub
Actions" (since 2026-07-05). `.github/workflows/deploy-pages.yml` fires on every push to `main` touching
the frontend (`webapp/**`, each game's dir, `shared/**`, `books/**`): a `build` job builds `webapp/`
(bakes `VITE_WS_URL=wss://splendid-nelz.onrender.com/ws`), runs the smoke gate, uploads via
`upload-pages-artifact`; a `deploy` job publishes via `deploy-pages`. It commits/pushes nothing. If deploy
flakes, re-run the workflow's `deploy` job. `gh-pages` branch + `docs/` are kept only as rollback nets.

```bash
git sync-main                 # ff the primary main worktree to origin/main (global alias)
# edit source only — do NOT npm run build, do NOT touch docs/ or gh-pages
git add <files> && git commit -m "..."
git push                      # deploy-pages.yml builds + publishes (~2-3 min)
```

- **Backend** (`**/*.py`) deploys to Render on push to main. The deploy job **verifies itself**: it
  polls `/health` until it reports the pushed commit and FAILS if that never happens.
- **The deploy hook returning 200 is NOT a successful deploy** (this cost a real gap): it only means
  Render accepted the request. A failed Docker build — the Dockerfile's Cython parity gate is *designed*
  to fail one — or a boot crash used to leave prod silently on the old code behind a green tick.
  `core/build_info.py` puts `commit` + `started_at` in every `/health`, and `deploy-render.yml` polls
  for the pushed SHA (falling back to "a process booted after we fired the hook", with a loud warning,
  if `RENDER_GIT_COMMIT` isn't set). A timeout means the build failed — check Render's logs; nothing was
  rolled back, prod is still serving the previous build.
- **Deploy preference (user):** land changes on `main` directly — don't hand over a PR (`gh` isn't
  installed; branch off `origin/main`, push `<branch>:main` to fast-forward).
- **COUPLED backend+frontend changes: use expand/contract, don't guess an order.** One push fires both
  workflows in parallel, and Pages caches the bundle ~10 min on top of that, so *some* client always
  runs the old frontend against the new backend. The old "ship backend first" rule only covers one
  direction — when the BACKEND adds a requirement the FRONTEND must satisfy, backend-first is wrong (the
  seat-binding release: a cached bundle omitted `session_token` on join, so re-entering your own seat
  answered "seat already taken"). Instead, in three pushes:
    1. **expand** — backend accepts BOTH the old and new shapes;
    2. ship the frontend that sends the new shape;
    3. **contract** — remove the compatibility path.
  Order-independent, zero broken window. The exception is a change whose whole point is to STOP
  accepting the old shape (closing a security hole): there the compat window *is* the vulnerability.
- **Stale-tab nudge**: the build stamps `__BUILD_ID__` into the bundle and emits a matching
  `version.json`; `shared/update-nudge.js` re-checks it on tab-focus and offers a Refresh.
- **WASM is a committed artifact** — CI does not rebuild Rust. Build with `wasm-pack build --target web
  --release --no-typescript`, copy `pkg/*.{js,_bg.wasm}` into `webapp/public/wasm/`, commit. **Same
  filename ⇒ browsers may serve the cached old wasm** (~10 min Pages TTL / hard-refresh). The crates are
  in **neither** CI path filter, so committing one never deploys anything on its own. CoC is the
  exception where a *model* swap needs no rebuild (the `.bin` is fetched); Spender and Duel embed nets.
- **Render keep-alive** (free tier spins down ~15min idle, ~30-50s cold start): `keepalive.yml`
  (GitHub Actions) is the SOLE mechanism — several INDEPENDENT long-lived (~90min) pre-7am runs, each
  HOLDING the connection open and retrying through the spin-up 503s (`curl --retry-all-errors` + long
  `--max-time`, like a browser) so any firing completes the wake (~7s). **Key lesson (do not regress):**
  a SHORT 30s pinger is worse than nothing — it disconnects mid-spin-up and ABORTS the wake, which was
  the actual cause of the 7-9am outages (not "GitHub fired late"). The only *guaranteed* fix is the
  $7/mo Starter tier.
- **Staging** (Cloudflare Worker `webprojectsstaging.forry4.workers.dev`, tracks the `staging` branch,
  reuses the prod backend) — test frontend/layout changes on a real URL first. Local↔Cloudflare bundle
  hashes differ; verify by served content. Use vs-AI games so test data stays private.

### Querying the prod DB directly
Turso creds live in gitignored `C:\Users\Forrest\.spender_turso`; query via `curl` POST to the libSQL
HTTP `/v2/pipeline` (no libsql wheel needed — use a BOUND arg for an id; a double-quoted SQL id is read
as a column). Note `list_user_games` excludes `status='over'` — query the DB directly for finished games.

---

## Design decisions & hard-won conclusions (do not relitigate)

**Product/design**
- Noble-path commitment is rejected — the AI must never LOCK onto a noble target; noble value is instead
  scaled inversely with board efficiency (few efficient L2/L3 targets ⇒ go wide on L1 ⇒ nobles come free).
- **Strategy model** (from a strong human, informs AI feature design): backward-plan from cost-effective
  high-point targets (5/8, 4/7, 3/6 deals); scarcity → nobles; contested cards are worth more
  (acquisition + denial); endgame denial (reserve a card the opponent is one buy from).

**AI strength (the campaigns)**
- **Eval-weight tuning is saturated** — one gain (learned weights 0.725 vs original), nothing since.
  Static eval accuracy plateaus ~0.65 regardless of model class or features; the missing info (future
  draws, deep lines) needs LOOKAHEAD, not a better static eval.
- **Search was the bottleneck, and it's been realized** — Spender variant S then variant N each broke the
  plateau via search + better inductive bias; CoC's r2 net serves via netval search; Duel's coherent +
  minimax fixes did it again in 2026-07. The remaining lever after search saturates is the training
  DISTRIBUTION.
- **Self-play is blind to tactics the opponent never demonstrates** (denial/racing/development) — a
  documented blind-spot class. Every "ceiling" or "exhausted" verdict in the research log is CONDITIONAL
  on the net + encoder that produced it — **re-run the probes if the net materially changes.**
- **The AZ degenerate-equilibrium fix** (reward shaping so a 0-0 tiebreak game becomes neutral, not a
  buy-nothing reward) is the most important single AZ finding.

---

*Full AI campaign history, dated sessions, and rejected-experiment postmortems:*
[`docs/ai-research-log.md`](docs/ai-research-log.md).
