# Forrest Games — Claude Context

A four-game multiplayer board-game website (+ a Books feature) sharing one backend, auth
layer, and frontend shell. Real-time play over WebSockets, server-authoritative game state,
and per-game AI opponents that range from simple heuristics to client-side neural nets
compiled to WASM.

> **AI campaign history, dated session narratives, and rejected-experiment postmortems live in
> [`docs/ai-research-log.md`](docs/ai-research-log.md).** This file is the operating manual —
> what's durable and expensive to relearn. When an AI section here says "see the research log,"
> that's where the blow-by-blow + "do not relitigate" detail is.

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
- Smoke gate before pushing frontend: `cd webapp && npm run smoke` (see Footguns → smoke test).
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
                       #   ai/serving/legacy_variants.py = retired-but-still-serving variants Z/H
  castles_of_crimson/  # CoC — engine.py + ai.py + main.py (coc_app @ /coc) + CastlesOfCrimson.jsx
  wherewolf/           # Where Wolf? — engine.py + main.py (werewolf_app @ /werewolf) + WhereWolf.jsx
  spender_duel/        # Spender Duel — engine.py + ai.py + main.py (duel_app @ /duel) + SpenderDuel.jsx
books/                 # Books feature (wired into the app, not a sub-app)
shared/                # theme.js (baseCss), lobby.jsx, splendor.jsx, router.js — cross-game frontend kits
webapp/                # Vite + React build (neutral, repo-root) — main.jsx mounts Spender.jsx (the shell)
wwsd/                  # "What Would Steve Do" — browser autoplayer for a friend's external site
rust-cores/            # Per-game Rust→WASM search crates (client-side serving). NOT the Python core/.
  spender-core/        #   Spender variant S/N search core (client-side serving)
  coc-core/            #   CoC Expert (netval) search core
  duel-core/           #   Spender Duel card-set ATTENTION value-net search core
docs/                  # GitHub Pages build output + ai-research-log.md
```

**Naming caution:** `core/` (top-level, singular) is the **Python** backend platform every feature
imports. `rust-cores/*-core/` are **Rust→WASM** crates, one per game — build artifacts, imported by
nothing in Python. They are per-game siblings (like `games/*`), not part of `core/`; the shared word
"core" is the only thing they have in common.

**Layering:** `core/` (bottom, depends on nothing) → features (games, books) → `app.py` (top). The
composition root depends on features; features depend only on `core`. This is the extraction that
removed the old circular imports — never reintroduce a `games.*` import into `core/`.

**Why the split is non-obvious:** cross-cutting infra (DB + auth) was pulled OUT of
`games/spender/main.py` into `core/` so features depend on a neutral platform, not on a game. Each
game is a thin FastAPI sub-app (`rooms`/WS/REST/persistence) that delegates all rules to its pure
`engine.py`. Root-level `render.yaml`/`docs/` stay at root (repo-wide deploy orchestration; the
Docker image is built from `games/spender/Dockerfile` per `render.yaml`).

---

## Shared backend platform (`core/`)

- **`core/db.py`** — `get_db_conn()` is a dual backend behind a driver-agnostic wrapper
  (`_Conn`/`_Cursor`/`_Row` — rows work by index AND column name). Local **sqlite3** by default;
  **Turso/libSQL** when `TURSO_DATABASE_URL`+`TURSO_AUTH_TOKEN` are set. A boot-time `_turso_selftest()`
  round-trips a row and **falls back to local sqlite on any failure** (site stays up, just
  non-persistent). `init_core_schema(conn)` creates the cross-cutting `users`/`admins`/`reconnect_tokens`
  tables. `cleanup_stale_games(table)` / `maybe_cleanup_games(table)` handle retention (all-guest game
  24h, any-registered-player 30d).
- **`core/auth.py`** — sessions/passwords (PBKDF2 + legacy), `create_user`/`authenticate_user`/
  `get_user_by_session`, `validate_credentials` (register: name 1–16 `[A-Za-z0-9]`, password 1–16),
  SITE_OWNER/admin helpers, reconnect-token create/validate/mark-used + throttled cleanup.
- **`core/config.py`** — `cors_allowed_origins()` **merges** `CORS_ALLOWED_ORIGINS` env with the always-on
  defaults (Pages `forry4.github.io`, the Cloudflare staging worker, localhost). Do NOT make it
  replace-semantics — that once silently locked out the staging mirror.

### Composition root — `app.py`
Creates `app = FastAPI()`, applies CORS + a pure-ASGI `SecurityHeadersMiddleware` (nosniff, DENY,
Referrer-Policy, HSTS, Permissions-Policy — threaded into the mounted sub-apps too), `include_router`s
Spender's `router`, `setup_books(...)`, `setup_puzzles(...)`, and mounts CoC/WW/Duel each behind a **defensive try/except**
(so the core backend never goes down if a game package is absent). No CSP on the API (it serves JSON;
CSP is Pages' job). Deploy entrypoint is unchanged: `games/spender/app.py` is a thin shim re-exporting
the root `app`, so the Dockerfile/render.yaml keep targeting `games.spender.app:app`.

### Persistence — Turso/libSQL (prod)
Render's free filesystem is ephemeral — sqlite `users.db` is recreated empty on every deploy/cold-start.
Prod uses Turso so accounts, games, and books persist. **Turso is LIVE and verified on Render** — prod
IS persistent; don't tell the user to set it up. The **libsql path cannot be tested locally** (no wheel
for Python 3.14 on this box; prod Docker is Python 3.11 where wheels exist) — validate it via Render logs
+ a login that survives a redeploy. The sqlite path (identical wrapper) IS locally tested.

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
  displaced the victim's live socket. (The follow-on trap: the connect-time registration was also what
  made the room get cleaned up, so removing it leaked an empty `ROOMS` shell per connect —
  `core.rooms.release_socket` now collects phantom rooms independently of socket ownership.)
- **`is_admin` is computed the same way on every path** — `is_admin_id(conn, id)` (plain SELECT) or a
  live `SITE_OWNER` username match. NEVER a correlated subquery — it reads NULL on the libsql driver
  (works on sqlite → invisible in tests), which made the owner lose admin on every session refresh.
- **Usernames are unique case-insensitively** — `users.name` has no UNIQUE constraint, so `create_user`
  checks `WHERE name=? COLLATE NOCASE` and `init_core_schema` builds `idx_users_name_ci`. Login looks up
  NOCASE too.
- **Tokens use a CSPRNG** (`secrets`, not `random`) — `gen_token` mints session/account/reconnect tokens
  AND password salts.
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

**The generic half now lives in `core/rooms.py`** (all four games use it, aliased to their historical
private names): `normalize_room`, `gen_room_token`, `db_conn`, `ensure_room_loaded`, `send_json`,
`delete_open_game(table, host_col, ...)` (the SELECT-then-DELETE rule — never `cursor.rowcount`), and
`release_socket` (the stale-socket guard + phantom-room collection; per-game policy stays explicit as
the `disarm_client_ai` / `drop_empty_open_only` flags). Extracting it was not tidiness: the same
hidden-info broadcast leak had to be found and fixed THREE times because three copies of
`mk_room_state` each leaked differently.

**Still duplicated (~25 functions, the obvious next extraction):** `save_game`, `load_game_to_memory`,
`_persist_row` and the `list_open_games`/`list_user_games`/`list_user_history`/`list_active_games`
family. Same shape in all four games, differing only in table name and columns.

```python
ROOMS[room_id] = {
  "players": {pid: name}, "sockets": {pid: WebSocket},
  "status": "open"|"playing"|"over", "host": pid,
  "game": {...} | None, "meta": {pid: {"token": str, ...}},
}
```

**Load-bearing invariants across all four games:**
- **Pending sub-decisions are real game-state keys**, not transient message fields — so they survive
  saves/reconnects and are server-enforced (Spender `pending_noble_pid`/`pending_discard_pid`; CoC
  `pending_pid`/`pending_kind`/`pending`; Duel `pending_pid`/`pending_kind`/`pending`; WW `night_step`). A stray `room_update` can't
  clear an unmet requirement.
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
  `rowcount` (it raised → 500'd the cancel endpoint in prod). Any libsql write needing an affected-row
  count uses an existence SELECT.
- `_schedule_*_turn` is safe to call any time (internal guards no-op when it's not the AI's turn / not
  playing) — deliberately called after reconnect to unstick socket-dropped games.

---

## AI opponents — difficulty levers (the fast reference)

Per the "what actually changes between tiers" question. Full campaign detail: **research log**.

### Spender
Lobby exposes persona pills mapping Easy→Expert. Internally there's a variant zoo; the ones that matter:

| Tier / variant | What it is | Where it runs | Lever |
|---|---|---|---|
| **N** (Expert / "Nina") | card-set **attention** net (`net_attn_3`) in determinized PUCT | **client-side WASM** (`spender-core`), ~20k sims/move; server-S fallback | the net; a 21-pt game auto-swaps to a 21-pt-trained net |
| **S** (strong search) | `v_state` V(state) leaf + determinized PUCT + H3 policy prior | client-WASM or server thread pool | sims budget (proven #1 lever); Cython-compiled leaf |
| H / H2 / H3 | 1-ply greedy heuristics (`take_value` / turns-horizon) | server | eval weights only |
| A / B / C2 / Z | MCTS with heuristic weight sets / older AZ numpy net | server | weights / net |

- **Serving:** on the AI's turn the server ships `ai_search` (the AI-perspective compact state) in room
  state; the browser worker pool searches and submits `ai_move`; the server validates it's in
  `legal_actions` and applies it. `CLIENT_AI_TIMEOUT` (15s; raised for N's heavier WASM worker) → server
  computes the fallback. Discard/noble
  finishes are routed to the client net too (`defer_discard`) so ONE brain decides take+discard (see
  Spender AI notes). Absent a WASM client it's byte-identical to server play.
- **21-pt "Long" mode** is a per-game `win_points`; any picked AI auto-adapts, and N/S have 21-pt
  specializations (a 21-trained net; a `turns_table_21.json` horizon).

### Castles of Crimson — lobby tiers Easy / Hard / Expert
| Tier | What it is | Where it runs | Lever |
|---|---|---|---|
| **Easy** | server determinized-MCTS bot at its strong config (`ai.play_turn_plan`) | server thread pool | sims/time budget |
| **Hard** | the first netval champion net (`coc_pv_model_hard.bin`) | **client WASM** (`coc-core`, netval leaf) | which net bin |
| **Expert** | the r2 champion net (`coc_pv_model.bin`) | **client WASM** (netval leaf, ~20k sims) | which net bin |

- **netval leaf** = net policy prior + a short priority rollout + the net VALUE head at truncation
  (`NETVAL_ROLLOUT_STEPS=30`, `NETVAL_C_PUCT=1.0`). CoC is a delayed-payoff game, so a 0-step static leaf
  undervalues in-flight turns — the short rollout is why netval works (see research log).
- **Serving mirrors Spender:** per-decision `ai_search` (compact state, undrawn pools sorted) → client
  searches → `ai_move`; watchdog `CLIENT_AI_TIMEOUT=8s` → falls back to the server hard bot.
- **Model upgrade = no wasm rebuild:** `python rust-cores/coc-core/tools/pv_json_to_bin.py <winner.json>
  webapp/public/wasm/coc_pv_model.bin` + push. The net blob is fetched (browser-cached), not embedded.

### Spender Duel — Easy / Normal / Hard
| Tier | What it is | Lever |
|---|---|---|
| **Easy** | `bot.py` random-legal | — |
| **Normal** | determinized MCTS, **softmax(Q/T) sampling** (T≈0.08) | temperature (beatable) |
| **Hard** | determinized MCTS, greedy pick, **card-set ATTENTION value net leaf** (netval = 12-step rollout + attention value) — SHIPPED `e4b2c06` | the net (retrain / self-play iteration) |

Duel is ported to Rust→WASM (client-side, ~150× sims; SHIPPED). **Hard's leaf is now a card-set ATTENTION
value net** (`attn.rs` + `feats::features_tokens`, PyTorch twin `tools/attn_net.py`, parity 6.1e-8), served
as a netval leaf — it replaced the board/deck-blind heuristic and beats it 0.58→0.62 across the sims ladder
(edge GROWS with depth; fresh-seed confirmed). The heuristic leaf is retained for Normal/Easy + the server
fallback + the rollout. **CORRECTION: sims are NOT saturated at ~700** (that figure was stale) — more search
wins to ~4-8k and prod runs ~60k, which is why the heavier attention leaf still wins at the deployed budget.
Full campaign + do-not-relitigate verdicts (endgame + geometry both washed): the research log.

### Where Wolf?
No AI — a real-time social-deduction party game, humans only.

### Cross-game AI facts (do not relitigate — full detail in research log)
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
  beats rollout (A/B by equal *time*, since static gets ~16× the sims); CoC → a short rollout is needed
  (delayed payoffs). The repo has opposite precedents on purpose.
- **The strength lever is SEARCH DEPTH (sims throughput), not eval re-weighting** — every eval-weight and
  eval-feature tuning campaign saturated. The remaining lever after that is the training *distribution*.

---

## Spender (Splendor)

### Rules — `games/spender/engine.py` (the single source of truth)
`apply_move(game, pid, mv) -> (ok, err, effects)`, mirroring CoC/WW/Duel. Mutates in place, returns
`(False, "reason", {})` untouched on an illegal move, and reports sub-decisions via
`effects["discard_pid"]` / `effects["noble_choice_pid"]`. Imports only the `cards` leaf — no FastAPI,
no DB, no rooms. **Historically these rules lived INLINE in the WS handler and nothing tested them**
(the suite covered helpers + the MCTS simulator, and the parity chain tied the AZ engine and the Rust
port to each other, never to the live path). `tests/test_engine_rules.py` drives this module.

**Card data + the pure cost maths live in the leaf `games/spender/cards.py`** — imported by both the
engine and the AI stack, so `ai/serving/*` no longer reaches up into the web module for it.

- **Move handler error hierarchy** (order matters — enforced in `engine.apply_move`, except the first
  three which are ROOM-level and stay in `main.py`'s WS handler):
  ```
  not game        → "game not started"        (room-level, main.py)
  status "over"   → "game is over"            (room-level, main.py)
  status not playing → "game not started"     (room-level, main.py)
  phase "over"    → "game is over"
  turn != pid     → "not your turn"
  pending_noble_pid == pid & type != pick_noble  → "must choose a noble first"
  pending_discard_pid == pid & type not in (discard, undo_discard) → "must discard down to 10 gems first"
  ```

### Backend (`games/spender/main.py` → `router`)
- Rooms/WS/persistence/AI dispatch + the original MCTS bot live here; rules are `engine.py`, card data
  is `cards.py`, and `ai/` holds all AI data + the AZ/heuristic stacks.
- **Retired AI variants (Z, H) live in `ai/serving/legacy_variants.py`** — retired means no lobby
  offers them, NOT dead: `ai_variant` is persisted, so an old saved game must still get a real move on
  its next AI turn. That is also why they are in `ai/serving/` and not `ai/offline/` (which the server
  never imports). Weight variants A/B/C/C2 are pure data (`weights*.json`) fed to `_mcts_choose_move`.
- **`engine.apply_move` still deep-copies the whole game on EVERY `take_gems`/`reserve`** for the undo
  snapshot, before checking whether the token cap will actually be exceeded — measured ~106% overhead
  on moves that never need it. Deferring it is predictable (`tokens + taken > 10`) but must not break
  undo. Known, not yet done.
- **Pending state in the game dict** (`pending_noble_pid`, `pending_discard_pid`) is set when the
  condition arises, cleared when resolved, and rejects any other move meanwhile. Frontend derives
  `needsNobleChoice`/`needsDiscard` from these keys (not message fields).
- **Discard undo**: an action overfilling past 10 gems deep-copies the pre-action game into
  `g["pre_discard_snapshot"]`; the modal's "↩ Undo turn" (`undo_discard`) restores it. Popped on normal
  completion; part of saved state so undo survives reconnect.
- **`ai_variant` is persisted** and restored on load (with a back-compat recovery from the `"AI (X)"`
  display name) — else a redeploy silently downgrades a vs-AI game to variant A.
- **Client-net discard routing (split-brain fix, do not regress):** on the website, N's PLAY move is
  searched client-side but an over-cap discard was historically finished by the server `_ai_discard_one`
  heuristic — a DIFFERENT brain than the net → the take→discard→re-take loop. Fix: `_run_ai_turn(...,
  defer_discard=True)` (client path only) sets `pending_discard_pid` and RETURNS without finishing; the
  existing `mk_room_state` `ai_search` block ships the DISCARD-phase state, the ply-keyed client effect
  re-searches and submits a `discard` `ai_move`. `_schedule_ai_discard_fallback` (ply-guarded, 15s) lets
  the reserved-aware heuristic finish on any client failure. Only benefits N (S one-hots H3 discards).
- **Move log is id-only + a static catalog** (`card_catalog()` resolves id→card; deck is fixed), cap 500
  → the whole game logs. Blind-reserve redaction strips `card_id` (the id reveals the card via the catalog).
- **Game reconstruction / review** (`ai/serving/replay.py`): `_capture_setup(g)` snapshots the dealt board +
  deck order + nobles into `g["setup"]` at creation (stripped from the wire, persisted), and discards are
  logged — together these make a finished game replayable move-by-move and re-scorable. `GET
  /games/{id}/review` (player-only) returns per-turn snapshots; the frontend renders a read-only rewind.
  Games created before `setup` shipped show only the final board.

### AI stack (`games/spender/ai/`)
Organized into three clearly-separated subpackages (the old 70-file `ai/az/` dump was split so the
deployed brain is legible and offline probes can't trigger a backend deploy):
- **`ai/serving/`** — the deployed brain `main.py` imports at runtime: `engine`, `actions`,
  `heuristic{,2,3}`, `valuation{,2,3}` (`valuation3` = the Cython hot leaf), `v_state`, `vsearch`,
  `mcts`, `infer_np`, `replay`, `distill_features`, `features` + the `turns_table*.json` data. Along
  with `ai/models/`, this is a `deploy-render.yml` path-filter trigger (`ai/offline/` is deliberately
  NOT). `valuation3` reads its `turns_table*.json` and (experimental) `leaf_model.npz`/`vsearch_s21.json`
  from this dir via `dirname(__file__)`.
- **`ai/offline/`** — the research toolkit (never imported by the server; imports the serving stack via
  `from ..serving import …`): the AZ training stack (`train_az`/`selfplay`/`league`/`net*`), the
  `h2_*`/`h3_*`/`s_*`/`vsearch_*` campaigns, `arena`/`bench`/probes/distill/bootstrap, `s_checkpoints/`,
  and the `FEATURES_V4.md`/`H2.md` campaign notes. Editing anything here does NOT redeploy the backend.
- **`ai/models/`** — the committed model artifacts loaded at import by `main.py`: `weights*.json`
  (variants A/B/C/C2/tactics/targeting), `az_model.npz` (variant Z), `value_model.json`.

The current deployed Expert is variant **N** (attention net, client-WASM). The learned weights, the
AlphaZero stack (variant Z), heuristics H/H2/H3, variant S, and the whole strength campaign that produced
them are documented in the **research log**. Offline tooling entry: `python -m games.spender.ai.train`
(writes `ai/models/weights.json`); the many benches live in `ai/offline/`.

**Rust→WASM serving core (`rust-cores/spender-core/`) — durable architecture:** a pure-Rust port of the engine +
`v_state`/`heuristic3`/`vsearch`/`mcts` + `feats` (attention tokenizer) + the action↔move-dict bridge,
compiled with `wasm-pack --target web`. Validated bit-exact against Python (engine, leaf, policy, move
bridge; Rust-S ≈ Python-S at 0.50). Deploy = `cd rust-cores/spender-core && wasm-pack build --target web --release
--no-typescript` → `cp pkg/spender_core.{js,_bg.wasm} ../../webapp/public/wasm/` → commit those two files (CI
does NOT rebuild Rust; the wasm is a committed artifact) → push. **Same wasm filename ⇒ browsers may
serve the cached old wasm** (~10 min Pages TTL / hard-refresh). The crate is in **neither** CI path filter,
so committing it never deploys anything on its own.

---

## Castles of Crimson (Castles of Burgundy port)

2–4 player faithful port (human-vs-human seats 2–4; vs-bot games stay 2p). Mounted at `/coc`. LIVE on prod. **Now a
4-animal CoB port** (chicken added; monastery 6 = spend 1 silver → 2 workers; boards 2/4 = 2019 layouts).

### Engine contract (`engine.py` — single source of truth for server, bot, tests, AI)
- `new_game(player_ids, names=None, seed=None)` — deterministic given seed.
- `legal_moves(game, pid)` — normal die-actions AND pending sub-decisions.
- `apply_move(game, pid, move) → (ok, err)` — validates + mutates in place; ALL scoring / replenish /
  phase-turn lifecycle / pending logic lives here.
- `is_over` / `final_scores` / `winner`.
- **RNG persisted in `game["rng_state"]`** (JSON-safe lists) so per-phase depot replenishment + dice stay
  reproducible across save/load. The whole game dict is JSON-safe (no sets).
- **Pending sub-decisions are game-state keys** (`pending_pid`/`pending_kind`/`pending`), server-enforced
  and reconnect-safe. Kinds: `extra_action`, `ship_choose_depot`, `ship_adjacent_depot`,
  `building_take_choice`, `warehouse_sell`, `townhall_place`, `goods_pick` — each also accepts
  `skip_pending` (bot/engine never deadlock). A new pending kind needs a matching frontend `PendingModal`
  block or the human can't resolve it.
- Move types: `take_hex`/`place_tile`/`sell_goods`/`take_workers`/`buy_black`/`adjust_die`/
  `discard_storage`/`end_turn`/`monastery6_take` + the pending resolvers.
- **Rulebook-fidelity invariants locked by tests** (do not "simplify" away): seat-dependent starting
  workers; the exact base-game hex supply; black depot refills 2×players per phase (4/6/8 for 2/3/4p via
  `tiles.black_fill`; `BLACK_FILL_2P`=4 is legacy-2p-only); starting castles
  never score; monastery 5 *chooses* the adjacent depot.
- **House variant — fixed depot layout** (`tiles.DEPOT_PLAN`): each numbered depot refills each phase with
  two hex tiles of fixed TYPES (the specific building/monastery still varies by seed). Locked by tests.
- **Shadow VP ledger** (`region_vp`/`color_vp`/`livestock_vp`) is telemetry OUTSIDE the canonical
  projection — for AI aux training only; don't fold it into `proj`/parity.

### Frontend (`CastlesOfCrimson.jsx`) — durable facts
- Self-contained; mounted at `screen === "coc"`; namespaced localStorage (`coc_*`); WS/HTTP derive `/coc`.
- **2–4 players + 3-column game screen** (`.coc-game-cols` grid `board | your duchy | opponent duchy` at
  ≥1280px): a 2p game shows the board + BOTH duchies at once; **3–4p games add opponent peek tabs**
  (`.coc-opp-tab` + `viewOppId`) to switch which opponent duchy is shown. Player count is host-chosen
  (create-modal 2/3/4 selector + a **Same board** toggle → backend `max_players`/`same_board`); depots, the
  2-col black depot, and the turn-order track all scale to N, and the board height is measured + pinned so
  it never grows with content. Layout math (depot pinning, black-depot clearance, storage zoom-to-fit) is
  in the research log.
- **"burgundy" is the DATA KEY, "crimson" is the display name — do NOT rename the key** (it's persisted in
  saved games AND generated into the Rust parity tables). Only the display maps burgundy→crimson.
- **Depot ghost outlines** (memory aid): a taken hex leaves a faint colored hex rim in its planned slot.
  Uniform rim = fill + an inner hex shrunk by a true perpendicular offset (correct only because tiles are a
  fixed 70×81, uniformly zoomed).
- **Monastery benefit icons**: each of the 26 monasteries shows a pictogram (`MONASTERY_ICON`); goods are
  barrel-shaped; the color-bonus chip is the shared `BonusTileBadge`.
- **Mounted bare (no baseCss)**: CoC resets `html,body{margin:0;…;background:#120c0d}` scoped to while it's
  mounted; its reset only targets `.coc *`. Append shared-kit CSS AFTER the `.coc *` reset so the reset
  can't zero its padding.
- **Board-column `zoom`** (`.coc-board-hex` zoom .85 @≥1280 / 1 @≥1600): percentages inside a zoomed
  element already resolve in zoomed units — `width:100%` fills; `width:calc(100%/zoom)` double-compensates.

### Serving & reliability (do not regress)
- `main.py` mounts `coc_app` at its tail behind try/except; imports auth/DB directly from `core`.
- **Auto-reconnect is load-bearing** — a vs-bot turn is re-driven only when the client reconnects, so a
  Render cold-start / iOS backgrounding that drops the socket froze the bot's turn until manual refresh.
  `useSocket` has a backoff reconnect loop (reconnects with the **`reconnect` action, not `join`**) +
  a `visibilitychange` nudge + a `socketReady()` guard (don't abort a still-CONNECTING cold-start socket).
- **Building-placement highlight** reproduces `_building_town_ok` client-side (one building type per
  same-color region unless you own monastery effect 1) so the legal-glow matches what the click accepts.

---

## Where Wolf? (One Night Ultimate Werewolf)

Real-time social deduction, 3–10 players, one device each. Mounted at `/werewolf`. LIVE on prod.

### Engine model (`engine.py` — single source of truth)
- **`dealt_role` is the role you PERFORM all night (immutable); `card` is your FINAL role (swappable).**
  Whatever card sits in front of you when night ends IS your final role. The WIN uses FINAL cards.
- **`player_view(game, pid)` is the hidden-information boundary** — a per-recipient redaction; a client is
  only ever sent cards it may see this phase (everything else is literally `None` in the payload).
  Redaction matrix (do not regress): werewolves see each other; **minion sees the wolves but wolves do NOT
  see the minion (asymmetric)**; masons see each other; seer sees the peek; **drunk sees NOTHING of its own
  (blind swap)**; lone wolf's center peek is private. Self-target rejected for robber/seer/troublemaker.
- **Voting is MULTI-DEATH** (`resolve_votes`): most-voted die; a tie for most → all tied die; nobody ≥2
  votes → no one dies. Hunter: a dead hunter also kills whom they voted (cycle-guarded).
- **Win (the load-bearing care points):** ≥1 **werewolf CARD** dies → village; else wolf-in-play + none died
  → wolves; no wolf in play → village iff nobody died. **Killing the MINION is NOT a werewolf death.** A
  **tanner death with no werewolf death suppresses the wolf win** (only the tanner wins).
- JSON-safe + reconnect-safe (RNG as lists; all collections are lists).

### Night conductor + host picker
- `_run_night` iterates `roles.NIGHT_ORDER` keyed on **deck presence** — every role in the deck is
  announced even if entirely in the center (silence can't leak which roles are out). Each step is a
  **fixed-duration window** (no early-advance, no per-step Event → uniform timing → leak-free).
- **Lone-wolf no-leak (do not regress):** the werewolves step ALWAYS uses the action window and ALWAYS
  narrates the conditional lone-wolf line, so a 1-wolf and 2-wolf game look/sound identical.
- Host picks the deck in the lobby via `set_roles` → `roles.validate_deck(deck, n, partial=True)` (the
  `partial` flag skips only the exact-count check so an in-progress selection broadcasts live). Full
  re-validation at deal, silently falling back to `recommended_deck(n)`.
- Doppelgänger is deferred (in the deck data but excluded from the picker + `validate_deck`).

### Frontend + deploy
- Circle seating (you at 6 o'clock); mobile reshapes into a tall ellipse; SVG vote-arrows; browser TTS
  narration + caption; auto-reconnect. WW has **no "Abandon"** (leaving just returns to lobby). The `css`
  literal must contain NO backtick (shared blank-page footgun).
- **WS identity is bound server-side** (a hardening fix — was a hidden-role compromise). Launched to prod
  by a **selective frontend add**, not a `staging→main` push (staging had a stale WW backend — see
  Footguns → never blind-push staging).

---

## Spender Duel (Splendor Duel)

Strictly 2-player. Mounted at `/duel`. LIVE on prod.

- **Hidden info is first-class:** `player_view(game, pid)` strips `bag` (→ `bag_count`), `decks` (→
  `deck_counts`), rng, and the OPPONENT's reserve identities (→ `{level, facedown}`); reveals all at game
  over. `main.py` broadcasts **per-recipient views** (`broadcast_state`) — the one structural difference
  from CoC/WW's shared snapshot. Blind deck reserves log level only.
- **Cell choices are strategic, not cosmetic** — take-same resolution, privilege takes, the reserve's gold
  token all carry a board CELL index (removing a specific token changes line-take geometry). Don't
  "simplify" them to color choices.
- **Turn pipeline:** one mandatory action → `_after_action` recheck loop (royal entitlement
  `(crowns>=3)+(crowns>=6)` vs `royals_claimed`; then discard-to-10) → `_finish_turn` (victory check
  pre-empts the AGAIN extra turn). Payments return to the BAG (not a bank); token conservation (exact
  25-multiset across board+bag+hands) is soak-tested after every move.
- **Review** (`replay.py`): reconstruction is EXACT from the persisted seed + move log (no `setup`
  snapshot needed — `new_game` is seeded). The log interleaves player moves with engine-written records
  (auto-abilities, `again`, `extra_turn`), and an auto-resolved take is byte-identical to a chosen one —
  so records can't be classified by shape; `_replay` lets the engine disambiguate by counting how many
  records the sim's log grew by. A finished game reveals reserves.
- **AI determinization needs `players[pid]["reserved_from_deck"]`** (a list of card ids stripped by
  `player_view`) — the log can't answer "was this reserve blind?" because it omits `card_id` for blind
  draws. Blind reserves resample PER LEVEL (which deck is public; identity is secret).

---

## Books (site feature — not a game)

Standalone page for ranking favorite books + collecting reading suggestions. Deliberately its own
top-level package (neither a game nor part of Spender).
- **Backend** (`books/api.py`) — tables in the shared DB (`books`, `books_meta`, `book_suggestions`).
  **Wired into the app via dependency injection** (`setup_books(app, get_db_conn, get_user_by_session,
  token_resolver)`) so `books` never imports a game (no cycle). Pure functions unit-tested against
  `:memory:`. Owner = `SITE_OWNER` env (a username), else first-authenticated-saver claims.
- **Frontend** (`books/Books.jsx`) — two-column layout; ▲/▼ reorder buttons (native drag doesn't work on
  touch); only the ⠿ handle is `draggable`; `makeDrop` inserts AFTER when dragging downward; Open Library
  keyless search-to-add (12s abort guard); covers cached as inline `data:` URIs on save (the remote CDN
  double-redirects with a 3h cache). Existing books need one Edit→Save to backfill covers.

---

## Shared frontend kits (`shared/`)

- **`theme.js` — `baseCss`** is the single source of truth for the design system (font `@import`/
  `@font-face` first, `:root` tokens, `.btn`/`.input`). Spender + Books + Duel + WW import it; CoC renders
  it too (CoC carries a copy since it mounts bare).
- **`lobby.jsx`** — shared lobby chrome (`LobbyHeader`/`LobbySectionHd`/`LobbyEmpty`/`LobbyLoading`/
  `TurnBadge`, cache helpers) + `GameMenu` (the in-game ☰ dropdown: Return / View rules / Abandon; falsy
  items filtered; Esc/click-outside close) + `CreateModal`/`LobbyCreateRow` (the unified "New Game" modal
  + create/join-by-code/refresh row). Token-driven via a per-game `--lby-accent` with **hard fallbacks so
  it renders in CoC's bare mount** — append its CSS AFTER the `.coc *` reset.
- **`splendor.jsx`** — Spender + Duel SHARE gems, jewel cards, and the move log
  (`GemToken`/`CardView`/`TokenPill`/`BonusPill`/`LogEntry` + CSS), lifted verbatim from Spender.jsx.
  **If a second game needs a Spender visual, EXTRACT it here — don't re-approximate it** (Duel drifted
  before this existed). Gems are matte gradient via a `--gc` custom property + drop shadow, **no ring**
  (a same-hue ring paints a bright lower-edge arc). `CardView` is game-rule-free (Duel's extras are
  optional props). Verify a splice against the pristine pre-refactor commit `dc1b005`, not a `.bak`.
- **`router.js`** — URL routing (below).

### Verification harness for shared UI (reusable)
esbuild-bundle a scratch React harness importing the real component + shared CSS, with **react aliased to
`webapp/node_modules`** (`--alias:react=<webapp>/node_modules/react`), then Playwright-screenshot
(`chromium.launch()`, fall back to `channel:"msedge"`). `npm run smoke` only renders the Spender LOBBY, so
game-screen changes need this isolation render or a live staging check.

---

## Spender frontend architecture (`Spender.jsx` — the shell)

`webapp/main.jsx` mounts `Spender.jsx`, which is both the site shell (home menu, auth, routing to every
game/Books/Puzzles) and Spender's own game UI.

### Screen flow & derived state
- `"auth"` → `"browser"` → `"waiting"` (2-player) | `"game"` (vs-AI goes straight to game).
- `inGame(status)` = `"playing"` OR `"over"` (a finished game stays on the game screen for the review UI).
- **Derived game state (`game`, `me`, `myTurn`, `aiThinking`, review flags) MUST be hoisted ABOVE all
  `useEffect` hooks** — they appear in dep arrays; a later declaration throws a TDZ ReferenceError in
  Firefox production builds. This is a recurring, load-bearing rule.
- **`WS_BASE = import.meta.env.VITE_WS_URL` is baked in at build time** (not from `window.location`) — so
  a separate frontend host (Cloudflare staging) points at the prod backend just by setting `VITE_WS_URL`.
- Reconnect tokens in `localStorage` as `spender_token_${roomId}_${myId}`; sent as `{action:"reconnect",
  token}`. Identity: logged-in `myId === user.id`; guest gets a random `spender_myId`.
- **Session validation on load**: `GET /auth/session?token=` runs before routing — a definitively-dead
  token (expired / superseded by a login elsewhere) clears the stale login; a network error NEVER logs you
  out.

### Lobby & multiplayer (2–4 players)
- Spender seats 2–4 humans (AI games stay 2-player); the engine is player-count-agnostic. `_bank_for(n)`
  scales the gem bank at start; nobles are `players+1`. DB has `player3/4_*` columns.
- 3-column lobby (**Open Games | Active Games | History**), each column caps to viewport and scrolls
  internally. **Explicit `grid-row` on every item is REQUIRED** (DOM order ≠ column order → sparse
  auto-flow wraps Active to row 2). Open Games is filtered by the Classic/Long toggle; Active is not.
- Open lobbies live ONLY in Open Games (owner sees Return+Cancel, others Join); Active = `myGames` filtered
  to `status==="playing"`. A game lives in exactly one section.
- **Cancel authorizes by live session OR the host's `player_id`** (open games are public; a session-only
  check failed silently after token expiry). Clear the local resume pointer only AFTER the server confirms
  the delete.
- **Joining a cancelled game is rejected** (`not r.get("host") or r.get("game") is None`) — the WS
  `setdefault` fabricated a phantom hostless room otherwise. Tab-back reconnect is gated to
  `screenRef.current === "game"` (else it re-opened a stale waiting room).

### Layout (do not regress the footguns)
- Desktop is **proportional off one anchor** — `--card-h:clamp(104px,17vh,205px)` on `.game`, every
  desktop dimension a `calc()` ratio of it (replaced 5 stepped max-height breakpoints). Base styles are
  the phone/compact foundation; the desktop look is added in `@media(min-width:901px)`.
- **CSS-grid "staircase"**: a later DOM element placed in an earlier column makes sparse auto-flow drop it
  to a new row → diagonal staircase. Fix: pin every grid child to an explicit `grid-row`. (`grid-row:1/-1`
  needs an explicit `grid-template-rows` or `-1` collapses to line 1.)
- The `.game`/`.game-sidebar` grids need BOTH a definite height AND `grid-template-rows:minmax(0,1fr)`,
  and the move log carries a belt-and-suspenders `max-height`, or content pushes past the viewport / the
  log clips instead of scrolling.
- **`zoom` (not transform:scale)** for player-box indicators (scales box+text+inline dots WITH reflow);
  remember the zoom factor when a request says "+1px" (on-screen delta is `px × zoom`).
- **Container-query `cqw` resolves against an ANCESTOR container, not the element itself** — reserved-card
  padding stays `--card-h`-based; only descendants use `cqw`.
- **Nobles never shift on claim**: the row renders the full id-sorted set; a claimed noble shows as a blank
  slot in its fixed position (frontend reconstruction — the backend removes it from `game["nobles"]`).
- **Action animations** (`.fly-layer`): one `useEffect([game])` diffs tokens/purchased/board-slot ids and
  spawns flyers — covers every player incl. the AI. Keep the `data-color`/`data-pid`/`data-pos` anchors.
- **Ping**: tapping another player's box plays a chime locally + sends `{action:"ping", target}`; the
  backend relays `{type:"ping", from}` to **ONLY the target's socket** (never broadcast — verified it
  reaches only the tapped player + clicker). Tab-hidden + your-turn/ping flashes the title + swaps favicon.

### No-layout-shift architecture (do not regress)
Self-hosted Cinzel/Crimson fonts (`webapp/public/fonts/`, `@font-face` in baseCss, preloaded in
`index.html`); the loading effect `await document.fonts.load(...)` (capped 1.5s) BEFORE routing so first
paint uses web fonts; `font-display:optional` + metric-matched `local('Georgia')` fallbacks (measured
`size-adjust`) so an unloaded font never swaps. Inline dark `background` in `index.html` (the `--bg` token
only exists in baseCss). The **CLS smoke gate** catches new shifts.

### URL routing (`shared/router.js` — LIVE on prod)
Every mode has a path (`/spender /coc /duel /werewolf /books /puzzles`) and every room a sub-path
(`/spender/ABC123`) — reload/reconnect lands right, Back/Forward work, room URLs double as invite links.
- **The load-bearing contract:** `pushPath`/`replacePath` are **NO-OPS when the path is already current**
  (one function serves both a click and a popstate call → no duplicate history); `subscribe` fires on
  **popstate ONLY** (programmatic writes never notify → no echo loop).
- **Ownership split:** the shell owns segment 1 (`nav(screen)` writes the URL FIRST, then sets the screen —
  a sub-game reads `parsePath()` at mount, so its URL must already be correct); each sub-game owns its own
  room segment via a mount `parsePath()` + a `subscribe()` popstate handler (routed through a per-render
  ref so the mount-once effect never runs a stale closure).
- Room URL is pushed at **server-confirmed success** (`created`/`joined`/`reconnected`), never at click
  time. Entering a room by URL runs the existing resume semantics (token → `reconnect`, else `join`).
- **The race (caught by e2e):** Back during a join round-trip must abort a still-connecting attempt
  (`urlAttemptRef`/WW's `attemptRef`) or the late confirm re-pushes the room URL.
- **Deploy:** `dist/404.html` is REQUIRED (Pages has no rewrite rules) — `deploy-pages.yml` copies
  `index.html`→`404.html` AFTER build. **Cloudflare staging SPA-routes natively, so staging green NEVER
  validates prod deep links** — always cold-load a prod deep link after shipping.

---

## Spender Puzzle mode (`games/spender/puzzle/` — LIVE on prod)

The player is dropped into one position and must find the single move N most favours. Reached from the
home-menu 🧩 button; backend is static (no serve-time AI).
- **Two `kind`s:** `win` (scripted forced-win, multi-move — kept but NOT surfaced live) and `advantage`
  (the shipped single-move "only-move" puzzles). The frontend filters to `advantage`.
- **A puzzle = a position where ONE move's N eval beats every other by a margin IN RANGE** (buy/reserve
  `[0.25,0.50]`, take `[0.25,0.60]`). The upper bound rejects obvious blowouts. The eval of a move = apply
  it + re-search the child, **averaged over K=8 independent determinization seeds**. Answers must not force
  a discard/noble sub-step.
- **Serving** (`serve.py`, `setup_puzzles` in `app.py`): `GET /puzzles` (listing incl. `answer_type`) +
  `GET /puzzles/{id}` (embedded per-step snapshots + every move's N eval). Frontend draws by a weighted
  type mix (`PUZ_TYPE_WEIGHTS` 60% buy / 15% take / 25% reserve), tracks a `spender_puzzle_seen` set,
  shows a category-only hint popup; the exact move is behind Answer.

### Hard-won puzzle findings (do not relitigate — full detail in research log)
- **Multi-move "hold the advantage" chains don't exist in Splendor** (positions branch too much) — only
  single-move puzzles are viable.
- **You can't select puzzles from the self-play search's per-move numbers** — PUCT starves alternatives
  (1–5 visits → their Q is noise); you MUST re-search each alternative to prove the gap. Generation is
  inherently slow.
- **A single search's VALUE is noise-dominated for open positions** (seed spread ~0.42) — average K
  independent searches. Take-gems answers are the noisy ones; buy/reserve stable.
- The `n_eval_server` returns `value=0.0` for DISCARD/NOBLE-phase roots — expand hero sub-decisions to
  PLAY/OVER leaves (max-of-means) before certifying a gap.
- N's real play is fine (~20k sims, picks by visit count) — this was puzzle-tooling noise only.
- **Candidate LEDGER** (`puzzle/candidates/candidate_ledger.jsonl.gz`) persists every verified position's
  K=8 move-evals so a threshold change is a pure re-filter (`rebuild_from_ledger`), zero recompute.

---

## Testing

- **The suite is defined ONCE** in `pytest.ini` `testpaths`; both CI workflows run a bare `pytest`.
  They used to carry two hand-maintained path lists that drifted (Duel's tests ran only at deploy).
- **Rules/engine unit tests are the most valuable to protect** — each game has them: Spender
  `tests/test_engine_rules.py` (the AUTHORITATIVE `engine.apply_move`: error hierarchy, every move
  type, pending sub-decisions + undo, a differential check against the MCTS simulator pinning where it
  deliberately DIFFERS, and a token-conservation soak) + `test_game_logic.py` (helpers + the simulator)
  + `test_ws_auth.py` + `test_replay.py`/`test_review.py`; CoC `tests/` (~319, board invariants,
  placement, scoring, lifecycle, one-per-monastery, endgame) + `test_client_ai.py`; WW `tests/` (~73, deck
  validation, every night action, win-condition matrix, `player_view` redaction matrix); Duel `tests/`
  (card invariants, redaction, bot-vs-bot soak with a 25-token conservation invariant); `core/tests/`
  (db/auth/ratelimit/retention, in-memory sqlite); Books `tests/` (17, in-memory DB).
- **CoC Python↔Rust differential parity** — regen fixtures via `gen_engine_fixtures.py`, then
  `cargo test --release --features bridge` in `rust-cores/coc-core`. Spender: `rust-cores/spender-core`
  `cargo test --lib` (`src/bin/*` need `--features bridge`).
- **CI runs `core/tests/` first; Render deploy is gated on tests.** Frontend deploy is gated by
  `npm run smoke`.
- AI strength benchmarking is offline (per-game `ai_selfplay` / arena / gate bins) — never in a serving
  path. Judge changes with CRN paired arenas + a mirror sanity that must read exactly 0.5000; the ship
  criterion is EQUAL-TIME, not equal-sims. Detail in the research log.

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
  twice. **Do not move CSS back into a JS literal.** The smoke test's backtick guard is kept as a net
  for any new one. `build.cssMinify` is deliberately **false**: these strings were never processed by
  Vite before, so keeping the emitted CSS byte-identical makes the move provably behaviour-free (worth
  ~45KB if you ever turn it on deliberately, with a visual check).
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
  after ANY edit or workers silently run stale code. Verify byte-identity via the build-gate tests +
  the `engine_value` signature hash. Prod builds its own Linux `.so` in the Dockerfile (build FAILS on
  miscompile, so a bad compile can't reach prod).

**Deploy verification**
- **Verify a Pages deploy by a CONTENT marker in the live bundle, not the filename hash** (CDN lag / Vite
  chunking can keep the hash looking unchanged). The `deploy-pages.yml` run status is the authoritative
  signal (Pages source = "GitHub Actions").
- **A stale `vite preview --port 5173` process serves an OLD `dist/`** — kill listeners on the port before
  serving, confirm the fresh bundle by a content marker.
- **Never blind-push `staging:main`** — `staging` has DIVERGED (behind main on backends; has historically
  carried the WW card). A force-push would wipe main's backend history. To ship staging frontend, branch
  off `origin/main` and selectively take/merge only the intended files.

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
  polls `/health` until it reports the pushed commit and FAILS if that never happens (see below).
  CoC model swap needs no wasm rebuild (fetch a new `.bin`).
- **The deploy hook returning 200 is NOT a successful deploy** (this cost a real gap): it only means
  Render accepted the request. A failed Docker build — the Dockerfile's Cython parity gate is *designed*
  to fail one — or a boot crash used to leave prod silently on the old code behind a green tick.
  `core/build_info.py` puts `commit` + `started_at` in every `/health`, and `deploy-render.yml` polls
  for the pushed SHA (falling back to "a process booted after we fired the hook", with a loud warning,
  if `RENDER_GIT_COMMIT` isn't set on the service). A timeout means the build failed — check Render's
  logs; nothing was rolled back, prod is still serving the previous build.
- **Deploy preference (user):** land changes on `main` directly — don't hand over a PR (`gh` isn't
  installed; branch off `origin/main`, push `<branch>:main` to fast-forward).
- **COUPLED backend+frontend changes: use expand/contract, don't guess an order.** One push fires both
  workflows in parallel, and Pages caches the bundle ~10 min on top of that, so *some* client always
  runs the old frontend against the new backend. The old "ship backend first" rule only covers one
  direction — when the BACKEND adds a requirement that the FRONTEND must satisfy, backend-first is the
  wrong order (the seat-binding release: a cached bundle omitted `session_token` on join, so re-entering
  your own seat answered "seat already taken"). Instead, in three pushes:
    1. **expand** — backend accepts BOTH the old and new shapes;
    2. ship the frontend that sends the new shape;
    3. **contract** — remove the compatibility path.
  Order-independent, zero broken window. The exception is a change whose whole point is to STOP
  accepting the old shape (closing a security hole): there the compat window *is* the vulnerability, so
  break deliberately — and rely on the update nudge below to explain it.
- **Stale-tab nudge**: the build stamps `__BUILD_ID__` into the bundle and emits a matching
  `version.json`; `shared/update-nudge.js` re-checks it on tab-focus and offers "A new version is
  available — Refresh". It compares frontend-to-frontend, **never** against the backend's commit — the
  backend only redeploys when backend paths change, so the two SHAs are legitimately different after any
  frontend-only push and a cross-comparison would cry wolf on every deploy.
- **Render keep-alive** (free tier spins down ~15min idle, ~30-50s cold start): `keepalive.yml`
  (GitHub Actions) is the SOLE mechanism — several INDEPENDENT long-lived (~90min) pre-7am runs, each
  HOLDING the connection open and retrying through the spin-up 503s (`curl --retry-all-errors` + long
  `--max-time`, like a browser) so any firing completes the wake (~7s). **Key lesson (do not regress):**
  a SHORT 30s pinger (the old cron-job.org job) is worse than nothing — it disconnects mid-spin-up and
  ABORTS the wake, which was the actual cause of the 7-9am outages (not "GitHub fired late"). The only
  *guaranteed* fix is the $7/mo Starter tier.
- **Staging** (Cloudflare Worker `webprojectsstaging.forry4.workers.dev`, tracks the `staging` branch,
  reuses the prod backend) — test frontend/layout changes on a real URL first. Local↔Cloudflare bundle
  hashes differ; verify by served content. Use vs-AI games so test data stays private.

### Querying the prod DB directly
Turso creds live in gitignored `C:\Users\Forrest\.spender_turso`; query via `curl` POST to the libSQL
HTTP `/v2/pipeline` (no libsql wheel needed — use a BOUND arg for an id, a double-quoted SQL id is read as
a column). Note `list_user_games` excludes `status='over'` — query the DB directly for finished games.

---

## Design decisions & hard-won conclusions (do not relitigate)

**Product/design**
- Noble-path commitment is rejected — the AI must never LOCK onto a noble target; noble value is instead
  scaled inversely with board efficiency (few efficient L2/L3 targets ⇒ go wide on L1 ⇒ nobles come free).
- **Strategy model** (from a strong human, informs AI feature design): backward-plan from cost-effective
  high-point targets (5/8, 4/7, 3/6 deals); scarcity → nobles; contested cards are worth more
  (acquisition + denial); endgame denial (reserve a card the opponent is one buy from).

**AI strength (the campaigns)**
- **Eval-weight tuning is saturated** — one gain (learned weights 0.725 vs original), nothing since. Static
  eval accuracy plateaus ~0.65 regardless of model class or features; the missing info (future draws, deep
  lines) needs LOOKAHEAD, not a better static eval.
- **Search was the bottleneck, and it's been realized** — Spender variant S (v_state + PUCT) then variant
  N (attention net) each broke the plateau via search + better inductive bias; CoC's r2 net serves via
  netval search. The remaining lever after search saturates is the training DISTRIBUTION.
- **Self-play is blind to tactics the opponent never demonstrates** (denial/racing) — a documented
  blind-spot class. For CoC, every value-bias arena testing a human-proposed tactic came back
  already-priced; the CoC "ceiling" verdicts are CONDITIONAL on the current net + its frozen encoder —
  **re-run the probes if the net materially changes.** For Spender N, a same-arch exploiter mirrors to ~0.5
  (needs injected asymmetry).
- **`az_model.npz`, the AZ league/curriculum, and the CoC ladder history**: full detail in the research
  log. The AZ degenerate-equilibrium fix (reward shaping so a 0-0 tiebreak game becomes neutral, not a
  buy-nothing reward) is the most important single AZ finding.

---

*Full AI campaign history, dated sessions, and rejected-experiment postmortems:*
[`docs/ai-research-log.md`](docs/ai-research-log.md).
