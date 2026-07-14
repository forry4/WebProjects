# Spender Project — Claude Context

## Critical rule
**NEVER add `Co-Authored-By: Claude` (or any Anthropic attribution) to commit messages.** The user has explicitly prohibited this.

---

## Project layout

All Spender code/data lives under `games/spender/`. Root-level files (`Procfile`,
`render.yaml`, `docs/`, `requirements-lock.txt`) are repo-level deploy/Pages
orchestration and stay at root (they're structurally pinned there and will
orchestrate future games too). **Cross-cutting backend infrastructure (the DB
connection + the user/session/admin auth layer) lives in the top-level `core/`
package, NOT under `games/spender/`** — it was extracted out of
`games/spender/main.py` so features depend on `core`, not on a game (see
"`core/` — shared backend platform" below).

```
games/spender/
  main.py          # Spender server + MCTS AI logic; exposes `router` (APIRouter), not the app
  app.py           # deploy-entrypoint shim → re-exports the top-level composition-root app
  Spender.jsx      # React 18 frontend (single file)
  users.db         # SQLite — users + games tables
  Dockerfile, requirements.txt
  ai/              # ── all AI data + training tooling ──
    train.py       # OFFLINE self-play trainer (evolve/TD/value/tournament/coevolve)
    strategist.py  # scripted benchmark opponent
    weights.json   # deployed learned weights (variant A); loaded by main at import
    weights.tactics.json / weights.tactics_c.json   # variant B / C weight sets
    weights.targeting.json                          # playtest variant
    value_model.json                                # learned value-leaf model
    weights.coevolved.json                          # coevolve harvest (0.600 vs A)
    weights.c2.json                                 # C2 variant (noble_scarcity=2.5, pos_noble_scarcity=0.5); 0.583 vs B
    play_A_volume.ps1 / play_B_tactics.ps1 / play_B_targeting.ps1  # local launch scripts
    az/            # ── AlphaZero stack (offline training; serving via az_model.npz) ──
      engine.py    # fast compact-state simulator (rule-parity with main.py)
      actions.py   # 70-action space, masks, dict-move bridge (both directions)
      features.py / net.py / mcts.py / selfplay.py / train_az.py
      arena.py     # AZ vs heuristic tournaments;  bench.py  # throughput
      export.py / infer_np.py   # .pt -> .npz -> pure-numpy production inference
      checkpoints/ # gitignored: az_best.pt, az_last.pt, buffer.pkl, az_model.npz
  tests/
    test_game_logic.py
    test_train.py    # offline trainer: harness, evolve/TD phases, weight I/O
    test_az_engine.py   # az engine: 200-game differential parity vs main.py + edge cases
    test_az_actions.py  # masks, features, MCTS smoke, arena bridge, variant-Z serving
app.py             # ── composition root (REPO ROOT): FastAPI app + middleware + feature wiring ──
core/              # ── shared backend platform (imported by spender, coc, books) ──
  db.py            # dual sqlite/Turso connection wrapper (_Conn/_Cursor/_Row) + get_db_conn + init_core_schema
  auth.py          # users/sessions/passwords, admin + SITE_OWNER identity, reconnect tokens
  tests/test_db_auth.py   # wrapper + password + admin unit tests (in-memory sqlite, no server)
webapp/            # ── Vite + React build (REPO ROOT, neutral — not under games/spender/) ──
  main.jsx         # mounts games/spender/Spender.jsx (the shell, which routes to all features)
  index.html / vite.config.js / package.json
docs/              # GitHub Pages static site (Vite production build output) — REPO ROOT
  index.html
  assets/          # Hashed JS bundles (e.g. index-XXXXXXXX.js)
```

**`main.py` loads its AI data from `ai/`** via `_AI_DIR` (`weights*.json`,
`value_model.json`). The trainer is `python -m games.spender.ai.train` and writes
into `games/spender/ai/` by default.

### Serving
- Backend: `uvicorn games.spender.main:app --reload` (port 8000)
- Dev frontend: `cd webapp && npm run dev` (port 5173, proxies /ws to 8000) — repo-root, neutral
- Production: GitHub Pages is served via the **official Actions pipeline** (Pages source = "GitHub Actions", since 2026-07-05; was the `gh-pages` branch, was `main`/`docs`). CI (`deploy-pages.yml`) **builds + publishes via `upload-pages-artifact`/`deploy-pages`** on every frontend push to `main` — one run we own (no more flaky gh-pages double-hop; re-run the `deploy` job if it ever hiccups). **Never hand-build/commit the bundle** — commit source only and let CI deploy. `gh-pages` branch + `docs/` are kept only as rollback nets. See "Build + deploy steps" below.

---

## Castles of Crimson (second game)

`Castles of Crimson` is the **second game** in the Forrest Games collection — a
faithful digital port of the duchy-building dice-and-tile euro game (full base
game: 6 hex-tile types, 8 buildings, 26 unique monasteries, goods/ships, area
scoring, 5 phases × 5 rounds, bonus tiles, workers, central black depot, full
end-game scoring). 2-player only (human-vs-human or human-vs-bot).

```
games/castles_of_crimson/
  board.py     # the ONE standard duchy: radius-3 hexagon (37 spaces), axial (q,r),
               #   computed ADJACENCY + REGIONS (same-color connected components, size 1-8)
  tiles.py     # tile/supply data, AREA_SCORE/PHASE_BONUS, 8 buildings, 26 monastery meta
  engine.py    # PURE rules engine (no web deps): new_game/legal_moves/apply_move/
               #   final_scores/winner/is_over + all placement effects + lifecycle
  bot.py       # trivial random-legal-move opponent (choose / play_turn); rollout policy + fallback
  ai.py        # STRONG opponent: determinized MCTS + heuristic eval (Normal / Hard)
  ai_selfplay.py  # offline arena (hard vs normal vs random) — validation/tuning, no server/DB
  main.py      # FastAPI sub-app `coc_app` (rooms/WS/REST/persistence); thin — delegates rules to engine
  CastlesOfCrimson.jsx   # self-contained React component the shell mounts at screen "coc"
  tests/       # pytest, 102 tests (board invariants, placement, scoring, lifecycle,
               #   effects, one-per-monastery, endgame, random-vs-random smoke)
```

### Engine contract (the single source of truth for server, bot, tests, future AI)
- `new_game(player_ids, names=None, seed=None) -> game` — deterministic given seed.
- `legal_moves(game, pid) -> [move]` — covers normal die-actions AND pending sub-decisions.
- `apply_move(game, pid, move) -> (ok, err)` — validates + mutates in place; ALL scoring/
  replenish/phase-turn lifecycle/pending logic lives here.
- `is_over` / `final_scores` / `winner`.
- **RNG is persisted in `game["rng_state"]`** (getstate as JSON-safe lists) so per-phase depot
  replenishment + dice rolls stay reproducible across save/load. The game dict is JSON-safe
  (no sets anywhere — town_buildings/livestock_types/monastery_effects are lists).
- **Pending sub-decisions are real game-state keys** (`pending_pid`/`pending_kind`/`pending`),
  mirroring Spender's hard-won lesson, so they survive reconnect and are server-enforced.
  Kinds: `extra_action` (castle), `ship_choose_depot`, `ship_adjacent_depot` (monastery 5's
  optional second depot), `building_take_choice`, `warehouse_sell`, `townhall_place`. Every kind
  also accepts `skip_pending` (the bot/engine never deadlock).
- Move types: `take_hex`/`place_tile`/`sell_goods`/`take_workers`/`buy_black`/`adjust_die`/
  `discard_storage` (free; only legal when storage is full, to make room per the rulebook)/
  `end_turn`/`monastery6_take` + the pending resolvers above.
- **Rulebook-fidelity invariants** (audited against the base-game PDF): starting workers are
  seat-dependent (start player 1, next 2 — set in `new_game`, NOT a flat `START_WORKERS`); the
  hex supply is the exact **164-tile** base-game count (124 colored + 40 black, fixed/not tunable
  — see `tiles.build_supply` docstring); the black depot refills **4** tiles/phase
  (`BLACK_FILL_2P`). Starting castles never score; monastery 5 lets you *choose* the adjacent
  depot. These are locked by tests — don't "simplify" them away.
- **Deliberate house variant — fixed depot layout** (overrides the rulebook's random
  replenishment): each numbered depot is refilled every phase with exactly **two** hex tiles of
  fixed TYPES per `tiles.DEPOT_PLAN` (1: ship+building, 2: castle+monastery, 3: pasture+building,
  4: ship+building, 5: mine+monastery, 6: pasture+building). `_replenish_depots` draws those types
  from the shuffled supply via `_draw_type` (so the specific building/monastery/animal still varies
  by seed). The supply (124 colored) comfortably covers 5 phases × 12 = 60 typed draws. Locked by
  `test_depots_follow_fixed_plan` / `test_depots_refilled_each_phase`.

### AI opponent (`ai.py`) — determinized MCTS, two levels (Normal / Hard)
The real bot. Pure Python, no new prod deps; reuses the engine contract.
- **Determinized UCT** over `legal_moves`/`apply_move`. The ONLY hidden info is the *undrawn*
  supply order + future dice (`supply`/`black_supply`/`goods_supply` + `rng_state`); everything
  else is public. `_determinize` (per iteration) **canonicalizes** the undrawn pools (sort by tile
  id) then shuffles + reseeds the RNG, so the search provably can't depend on the hidden order
  (`test_move_invariant_under_supply_reshuffle`). Depots/duchies are left TRUE (visible). Bounded
  in-tree horizon (`_MAX_TREE_DEPTH`) → truncated rollout → **heuristic leaf eval `_value`** (the
  strength lever: realized `final_scores`-style score + weighted potential — mine income, area/
  color-completion proximity, monastery effects, empties penalty; weights in `WEIGHTS`).
- **Perf (was the hard part)**: two hot-path fixes give ~430 it/s in pure Python — (1) engine
  `_snapshot_turn` early-returns when `game["_skip_undo"]` is set (the AI sets it on clones; avoids
  a full `copy.deepcopy` on every simulated turn — the dominant cost), (2) `ai._clone_game` is an
  explicit shallow clone that SHARES immutable tile dicts + the wholesale-replaced `rng_state` and
  drops the move log (~120× faster than deepcopy). **Tiles are never mutated in place** — this
  invariant is what makes sharing safe; don't break it.
- **Difficulty** (`ai.DIFFICULTY`): per-decision budgets. `hard` = bigger time/iters, greedy.
  `normal` = small budget + visit-count **temperature** sampling (beatable blunders). Measured:
  **hard ≫ normal ≫ random** (hard 4/4 vs random by ~80-pt margins; hard 6/6 vs normal, 100 vs 39
  avg). Tune via `ai_selfplay.arena`; final calibration is a human playtest.
- **Serving**: `main._schedule_bot_turn` snapshots under `ROOM_LOCK` → plans the **whole bot turn**
  in a thread pool (`ai.play_turn_plan` via `run_in_executor`, mirrors Spender's `_schedule_ai_turn`)
  → re-locks → applies the move sequence → a trivial-`bot` finisher guarantees the turn ends (no
  deadlock). Room carries `ai_difficulty` (`_valid_difficulty`, default `hard`); frontend lobby has
  a Normal/Hard "vs Bot" pair sending `ai_difficulty`. The module import is aliased
  `from . import ai as coc_ai` because `ai` is a local var for the bot pid in `main.py`.

### Server (`coc_app`, mounted under `/coc`)
- `games/spender/main.py` mounts it at its **tail** with a **defensive try/except** (an earlier
  unconditional import was reverted in `fc6a2fa` because it crashed prod when the package wasn't
  committed; the wrapper means the core backend never goes down if the package is absent).
  WS = `/coc/ws/{room}/{player}`, REST = `/coc/...`, health = `/coc/health`, `/coc/board`
  serves the static layout to the frontend.
- Mirrors Spender's patterns: in-memory `ROOMS` under `ROOM_LOCK`, `save_game`/`load_game_to_memory`,
  `broadcast_room`, `mk_room_state`, stale-socket disconnect guard, async opponent scheduler.
- **Shared site identity**: imports the auth/DB helpers **directly at the top** from the `core`
  package (`from core.db import get_db_conn`, `from core.auth import gen_token, get_user_by_session,
  validate_reconnect_token, mark_reconnect_token_used`). These used to be lazy imports from
  `games.spender.main` to dodge an import-time circular dep; the `core` extraction removed the cycle
  (core depends on no game), so the lazy shims are gone. Persists rooms in its **own `coc_games`
  table** in the shared site DB; reuses the `reconnect_tokens` table (created by `core.init_core_schema`).
- **Cancel must NOT use `cur.rowcount` (libsql 500 gotcha — DO NOT regress).** `delete_open_game`
  uses a **SELECT-then-DELETE** existence check, not `cursor.rowcount`: the driver-agnostic
  `core.db` wrapper doesn't expose `rowcount` on the libsql/**Turso** backend (it raised), so the
  rowcount form **500'd the cancel endpoint in production** (the frontend's `r.json()` then choked on
  the plain-text "Internal Server Error" body → "Could not cancel"). This is the same fix Spender's
  `delete_open_game` already had; CoC just hadn't gotten it. Any new libsql write that needs an
  affected-row count must use SELECT-then-DELETE/UPDATE, never `rowcount`.

### Frontend (`CastlesOfCrimson.jsx`)
- Self-contained component the shell (`Spender.jsx`) mounts when `screen === "coc"`, passed
  `{ myId, authUser, onExit }`. Owns its own WebSocket + lobby + game screens.
- Namespaced localStorage (`coc_roomId`, `coc_token_{roomId}_{pid}`) so it never collides with
  Spender. WS/HTTP bases derive `/coc` from `VITE_WS_URL`.
- **Visual simplifications (user-requested)**: SVG hex duchy with plain single-color tiles (no
  icons) except **monasteries show their number**; empty spaces show their required die number;
  VP is a plain per-player counter; only your board is shown with a **View Opponent** peek button.
- **Depot ghost outlines (memory aid)**: because each numbered depot refills with the same two
  TYPES every phase (`tiles.DEPOT_PLAN`), a taken hex leaves a faint **colored hex outline** in its
  planned slot so the player remembers what goes where next phase. Driven by `DEPOT_PLAN_COLORS` +
  `depotGhostColors(d, hexes)` (planned-minus-present multiset) in the JSX; `.coc-tile-ghost` is a
  full-color clip-path hex with an inset `::after` filled `var(--surface2)` (the depot bg), leaving
  only a rim. Ghosts are inert (no click) and the central **black depot** (no fixed plan) is left
  untouched. `DEPOT_PLAN_COLORS`/`COLOR_TYPE_LABEL` are hardcoded mirrors of the backend plan.
- **Pending modals** render by `game.pending_kind` in `PendingModal` — one block per kind
  (`ship_choose_depot`, `ship_adjacent_depot`, `building_take_choice`, `warehouse_sell`,
  `townhall_place`, `extra_action`); each has a Skip. A new engine pending kind needs a matching
  block here or the human has no way to resolve it.
- **Discard button**: shown in the action row only when storage is full (`me.storage.length >= 3`)
  and disabled until a storage tile is selected — sends `discard_storage` to free a key space
  (mirrors the engine rule that the move is legal only when full).
- **No white frame (mounted-bare gotcha):** the shell early-returns `<CastlesOfCrimson/>` WITHOUT
  Spender's `baseCss`, and CoC's reset only targets `.coc *` descendants — never `body`. So the
  browser-default `body{margin:8px}` over an unstyled (white) body showed as a frame around the dark
  page. Fix: CoC's own `<style>` resets `html,body{margin:0;padding:0;background:#120c0d}` (scoped to
  while CoC is mounted, so no cross-screen effect). If you ever wrap CoC in `.app`/baseCss, this is
  moot — but don't drop the body reset while it's mounted bare.
- **Lobby mirrors Spender (Open Games / Active Games — NO "Your Games"):** three sections —
  (1) a localStorage **fallback "Active Games" card** (`coc_roomId`/`coc_token_*`) for guests (who
  have no `/games/mine`), guarded so it never renders when the game is already listed, while games
  load, or when the real Active Games section shows (no duplicate header); (2) **Open Games** (all
  open games; **your own** open lobby shows **Return + Cancel**, others show **Join**); (3) **Active
  Games** = `myGames.filter(status==="playing")` with matchup + Your Turn/Their Turn badge + Resume.
  The old "Your Games" section listed all your non-over games, so an open lobby appeared in BOTH it
  and Open Games — splitting open(→Open Games)/playing(→Active Games) makes a game live in exactly
  one place. Section CSS: `.coc-section-hd`/`.coc-muted`/`.coc-turn-badge`/`.coc-their-badge`/
  `.coc-spinner`; `timeAgo()` is a module-level helper. Backend already returns
  `you_are_p1`/`your_turn`/`created_at`/`updated_at`/`host_*`.
- **Bot's default board is board 1** (`oppBoard` default `"1"`, was `"2"`) so a fresh vs-bot game
  doesn't preselect a different board than the player's.

### Deploy / branch notes
- Both workflow path filters now watch `games/castles_of_crimson/**` (pages = whole folder so the
  bundled `.jsx` rebuilds; render = `**/*.py`). The Dockerfile already `COPY . /app`s the package.
- **LIVE as of 2026-06-16.** `coc-game` was merged to `main` (PR #1) and the game is deployed:
  the **Castles of Crimson** home card is `status: "ready"` (shows **Play**), GitHub Pages serves
  the CoC-bundled frontend, and the backend mounts `coc_app` at `/coc` (`GET /coc/health` → ok).
  The merge brought `coc-game` (which was 48 commits behind) current with `main` — the only manual
  conflict resolutions were the two deploy workflows (path-filter unions), `Spender.jsx` (kept main's
  Books/variant-H additions + re-added the CoC import/entry/mount, dropped the old "Coming Soon"
  placeholder), and the `az_model.npz` binary (took main's). Validated by the full suite (433 passed)
  + a scripted vs-bot smoke (hard/normal to completion, no deadlock).
- **Frontend is feature-complete**: lobby board pickers, per-player board rendering, the setup-phase
  castle-selection UI (`setupPhase`/`setupMine`; clicking a glowing burgundy space during
  `game.phase === "setup"` sends `place_starting_castle`), and the depot ghost outlines (above).
- **Deploy flow (per user preference — see memory):** land changes on `main` directly, don't hand
  over a PR. `gh` is not installed and `main` is checked out in the `forrestm_projects-ai` worktree,
  so from the primary worktree: branch off `origin/main`, make the change, then
  `git push origin <branch>:main` (fast-forwards `origin/main`); CI builds + publishes to the `gh-pages` branch + redeploys.
  **Primary worktree is now ON `main`** (not `-ai`), so these small changes are just commit-on-main +
  `git push origin main` (fetch/`0 0` ahead-behind first). Backend (`engine.py`/`ai.py`/`main.py`)
  redeploys to Render; frontend (`.jsx`) publishes to gh-pages (CDN ~few min). After a backend push,
  poll `/coc/health` + `/coc/games` (DB read) across the deploy window — Render's zero-downtime swap
  keeps it 200 throughout for a clean deploy.

### Session (July 2026) — dice UX, bonus-bar split, richer log, final-score display, bot flail fix
UI/UX polish + one bot fix, all shipped to prod. Durable, non-obvious facts:
- **`dice[pid]` now has four fields: `values` / `orig` / `used` / `adjusted`** (was just `values`/`used`).
  `orig` = the rolled values; `adjusted` = per-die bools. Set together in `_begin_round`; all JSON-safe;
  every reader defaults via `.get(..., [False,False])` / `.get("orig", values)` so old saved games load
  fine. `_snapshot_turn` deep-copies the whole game, so undo is automatic. `ai._clone_game` copies both.
- **Die-adjust WORKER REFUND (house rule beyond the base game).** `_h_adjust_die` charges the **net
  distance from `orig`**: `delta = _adjust_cost(orig,to) − _adjust_cost(orig,frm)`, so nudging a die
  back toward its roll **refunds** workers (`delta<0`) and moving toward the roll is allowed even at 0
  workers (only `delta>0` is affordability-gated). `_adjust_cost` is a metric (min-wrap distance, ÷
  per-worker for monastery-8), so a multi-step path is never cheaper than one direct jump — refunds make
  "away then back" free. Frontend: the incremental **±1 buttons** stay (humans chain freely in the
  engine); `adjustDelta(i,dir)` mirrors the cost model (incl. monastery-8 halving) to disable a button
  only when that step is unaffordable, and tooltips say "refunds a worker" when moving toward the roll.
- **Bot dice-flail fix (`ai._legal`) — the "adjust a die to 6, then take 2 workers" waste.** The AI
  prunes, for an already-`adjusted` die, BOTH re-adjusting it AND `take_workers` with it — both are
  strictly dominated (`take_workers` ignores the die value, so paying workers to set it first is pure
  waste; a 2nd adjust is never cheaper than one jump). Pruning `take_workers` makes a pointless adjust
  **self-defeating in the search**, so the bot stops doing it. Strictly-correct (never removes an optimal
  line); **humans unaffected** (engine-level rules unchanged — the prune is AI-only). **REJECTED (do not
  relitigate):** valuing workers at `*0.5` instead of the floored `//2` in `ai._value` — an A/B showed it
  made the flail WORSE (15 vs 6 wasteful adjacencies across 6 games) and increased total adjusts;
  reverted. The eval is NOT the lever here; the legal-move prune is.
- **Turn-start roll log:** `engine._log_roll(game, pid)` logs `{type:"roll", d0, d1}` at each turn start
  (`_begin_round` for the start player, `_advance_turn` for the next). Frontend `moveText` → "X rolled a
  A and a B". Logs are DISPLAY-only records (never re-applied), so new types are harmless.
- **Phase-end income log:** `_end_of_phase` logs per player `mine_income {silver,mines}` +
  `monastery_income {workers,effect=2}` (monastery-2's worker-per-mine), then a `phase_end {phase}`
  DIVIDER with **`pid=None`**. `vp_breakdown` is unaffected (it skips any record without a `vp` field, and
  `phase_end`/income carry none). Frontend renders the income lines normally and the divider as a centered
  ".coc-log-phase" "— Phase X ended —"; the log render **guards the player-name prefix** (`m.pid ? … : ""`)
  for the pid-less divider.
- **Bonus bar SPLIT into three groups:** "Region phase bonus +N" (the per-phase time bonus,
  `PHASE_BONUS` A10→B8→C6→D4→E2) · "Region size bonus" (the fixed `AREA_SCORE` scale 1/3/6/10/15/21/28/36
  by region size) · "Color bonuses" (the existing large/small color-completion chips). `PHASE_BONUS`/
  `AREA_SCORE` are JSX-mirrored constants of `tiles.*`. Region completion pays size + phase, so both are
  now surfaced.
- **Spelling:** all UI text is "color" (was "colour"), including the backend `vp_breakdown` "Color bonus"
  label. **Goods are ALWAYS named by number** ("#N goods"), never by color — the last offender was the
  castle bonus (`extra_action`) modal's "Sell {color}" button, now a numbered goods token.
- **Final score at game end:** the top status-bar score shows `roomData.final_scores[pid]` (leftover
  goods/silver/workers + monastery end-game bonuses folded in) once `over`, and live placed VP during
  play. `mk_room_state` already ships `final_scores` + `vp_breakdown` every update (also feeds the
  click-to-open mid-game breakdown).
- **Rendering gotcha (recap — do not regress):** the gold rim on **legal-placement spaces AND placed
  tiles** is drawn as a **top-most `pointer-events:none` stroke-only `<polygon>`** (over the socket/raise
  gradient). A stroke on the BASE polygon gets its inner half painted over by the gradient → pale-top /
  dark-bottom asymmetric rim. The base polygon still catches clicks, so placement is unaffected.

### Session (June-July 2026) — earlier CoC polish now on prod (context)
Shipped in prior sessions; recorded here since they weren't in this doc: a **`goods_pick` pending kind**
(when a depot offers more new goods TYPES than you have free goods slots, you pick which — floating modal
+ pulsing depot tokens); an **in-game VP review** (`VpReview` component, click the score any time — mid-game
shows end-of-game bonuses faded until `over`); a lobby **History** section with per-game **Review** (HTTP
`GET /coc/games/{id}/review`, read-only, synthesizes `roomData`, `reviewOnly` guards localStorage); **worker/
silver visual tokens** with spend/gain flyer animations (`data-workers`/`data-silver` anchors, `resFly`);
goods named "#N goods"; **1s bot move pacing** (`_BOT_MOVE_DELAY`); auto-open View Opponent on the bot's turn.
- **OUTAGE LESSON (do not regress):** a rewrite of `_schedule_bot_turn` to animate a bot's *consecutive*
  turns (ship → retake first player) fully on the View-Opponent screen **hung the backend event loop** and
  took prod down. Root cause: the finisher's **synchronous `bot.play_turn` loop runs UNDER `ROOM_LOCK` on
  the event-loop thread**; looping it up to ~12× per bot turn + ~12 DB saves/turn starved the single-process
  loop. Reverted (`git revert`). **Keep `_schedule_bot_turn` as the single-turn plan-then-apply version**
  (MCTS in the thread pool, apply move-by-move with per-move broadcast + `_BOT_MOVE_DELAY`); never loop
  heavy synchronous engine work under the lock. This is the same class of hazard as any lock-held blocking.

### Session (July 2026) — mobile layout, warehouse modal, phase pause+popup, bot no-waste, randomize first, log/animation polish (SHIPPED `45ea1ae`)
A batch of CoC UI/UX fixes + two engine/bot fixes, all on prod. Durable, non-obvious facts:
- **MOBILE CSS CASCADE TRAP (do not regress — bit us repeatedly).** The `@media(max-width:600px)` block sits
  BEFORE the base component rules in the `css` string, so a **single-class** mobile override
  (`.coc-bonus-sw{…}`) LOSES to a later equal-specificity base rule (silently dead). **Every mobile override
  must be `.coc `-prefixed** (`.coc .coc-bonus-sw{…}`) to win on specificity. Noted in a code comment. (This
  is the CoC analog of Spender's documented media-query ordering footgun.)
- **Color-bonus chips no longer wrap to a 2nd row on mobile.** The wide Cinzel "Color bonus" label can't
  share the row, so the label is forced onto its own line and a `~`-sibling divider break
  (`.coc .coc-bonus-div ~ .coc-bonus-div{flex-basis:100%;height:0;background:none}`) wraps the chips under it.
  Labels renamed **"Color bonuses"→"Color bonus"** and **"Your dice"→"Dice"** so dice+silver/workers fit one
  row and label+chips fit one row on mobile.
- **Warehouse ability is now a FLOATING bottom modal** (`<Modal interactive>` = `coc-modal-float`,
  pointer-events pass through), matching every other ability — click a Sell chip in the modal OR click one of
  your own goods (`.coc-goods-pick`, a pulsing chip, shown when `warehouseMine && me.goods[c]>0`) to sell.
  **AUDIT RESULT (recorded): `warehouse_sell` was the ONLY ability covering the whole screen.** View Opponent
  + the score breakdown stay full-screen deliberately (they're informational views, not abilities).
- **Phase-end pause + phase popup.** `_PHASE_END_PAUSE=2.6s` in `main.py`: `_schedule_bot_turn` sleeps this
  (instead of `_BOT_MOVE_DELAY`) whenever `game["phase_letter"]` advanced (before its first move + between
  moves that cross a phase boundary), so the player can see mine-silver/monastery income before the board
  moves on. Frontend: a `phasePop` overlay (`.coc-phase-pop`, z-120) driven by a `[game.phase_letter]` effect
  that diffs `prevPhaseRef` and shows `{from,to,silver:me.mines_count,workers}` for 3300ms (skipped while
  reviewing/over).
- **Bot no longer wastes a die (TWO fixes; verified 0/0 wasted across 60 sim games).** The waste ("adjust both
  dice to no purpose, then end") came from the search painting itself into a corner: `ai._legal` pruned
  `take_workers` for an already-`adjusted` die, so when no depot action remained the only legal move left was
  `end_turn`. Fix: **`ai._legal` keeps `take_workers` as a guaranteed fallback** — it only prunes the wasteful
  take-workers when a *productive* move still exists (`productive` = any move not in
  `take_workers/adjust_die/end_turn/skip_pending`), and it still forbids `end_turn` while an unused die has a
  non-end option. And **`bot.py` (the random finisher) `choose` prefers real actions + take_workers over
  wasteful adjusts over passing** (`_WASTEFUL={"adjust_die"}`; `useful` excludes `_PASSIVE`∪`_WASTEFUL`;
  `take_workers` is legal with any unused die so `useful` is non-empty whenever a die is unused → the finisher
  never ends with an unused die and never burns workers adjusting).
- **First player randomized for vs-bot games.** `main.py` create-vs-AI now `random.shuffle(seats)` before
  `engine.new_game(seats,…)` (seats = `[pid, AI_PID]`), so the bot is start-player ~half the time (also
  fairer — starting workers are seat-dependent).
- **"Select a die to act" hint removed** (the action-hint fallback is now `""`).
- **Die-adjust log states the VALUE, not the index.** `engine._h_adjust_die` now logs `frm` (the die value
  BEFORE the adjust: `frm = d["values"][i]`); frontend `moveText` renders **"adjusted a 5 to a 1"** (falls
  back to "adjusted a die to a X" for old saved games without `frm`).
- **Flyer alignment fixes (two fragile endpoints).** Goods flyers landed at a hardcoded offset into the goods
  row; they now target the **exact per-color goods chip** (`rectOf({kind:"goodchip",c})`, anchored by
  `data-goodchip`/`data-oppgoodchip` on each chip). Silver/worker token flyers landed between the icon and the
  count; the token anchors (`data-workers`/`data-silver` + opp variants) **moved onto the icon `<span>`** so
  they land on the coin/hammer glyph.
- **Starting-castle placement animation** (was broken for the human AND when viewing the bot): the `data-sid`
  placement anchor was gated on `interactive` (gone once the turn ended) and the View-Opponent modal covered
  the board instantly. Fix: `data-sid` is **always** on my board (`data-sid={opp ? undefined : sid}`), and the
  setup auto-view-opponent is **delayed 550ms** (`setupOpenTimer` ref + cleanup) so the placement flyer plays
  before the peek swaps the view. (SUPERSEDED — see the reveal rewrite in the next session entry.)

### Session (July 2026) — labels, crimson, ability logging, reconnect fix, keep-alive, arm-then-act, review polish
A large batch of CoC UI/UX + one load-bearing reliability fix, all shipped to prod. Durable, non-obvious facts:
- **Phase-round labels ("A-1".."E-5") replace turn numbers in the log + review.** `engine._log` stamps every
  record with `ph`/`rd` (phase letter + round). Income/`phase_end` log BEFORE `phase_letter` advances, so they
  correctly stamp the ENDING phase. Old saved games lack `ph` → the UI falls back to the `T#` turn number
  (`m.ph ? \`${m.ph}-${m.rd}\` : \`T${m.t}\``). `vp_breakdown` items carry `ph`/`rd` too so the review segments
  by phase.
- **"burgundy" is the DATA KEY, "crimson" the display name (do not rename the key).** All user-facing text
  says crimson (`colorLabel`, the setup error message, the `vp_breakdown` "Color bonus" label). But the space
  ids (`burgundy-1`, …) are **persisted in every saved game** AND generated into the Rust **coc-core parity
  tables**, so renaming the key would corrupt saved games + break engine parity. Only the *display* maps
  burgundy→crimson.
- **Color bonus is labeled small/large.** `bonus_tile` is tagged `large=(len(remaining)==2)` before the
  `remaining.pop(0)` — the FIRST claim (both tiles present) takes the LARGE bonus (`bonus_first`, n+3), the
  second the SMALL (`bonus_second`, n). `vp_breakdown` falls back to comparing `vp == tiles.bonus_first(n)` for
  pre-flag saved games. Label: "Color bonus — large (crimson)".
- **Tile-ability logging via a `via` field (the consistency fix).** Every ability-driven ACTION log carries
  `via` = a source-tile key: a building key (`market`…), `"ship"`, `"castle"`, or `"monastery:N"`. The FRONTEND
  LOG RENDER appends ` (${viaLabel(via)})` at the very END of the line (NOT `moveText`, so the tile name lands
  after any "(+VP)"): "took a Ship (Market)", "sold #3 goods x2 (+4 VP) (Warehouse)", "advanced 1 on the turn
  track (Ship)", "(Castle)", "(Monastery #6)". `_log` drops a `None` via so normal actions stay clean.
  Threading: the immediate-gain buildings (boarding/bank/watchtower) log a NEW `build_gain` record
  (`via=bt`, + workers/silver/vp) INSTEAD of the old generic `building_effect` "used X" line; pending-action
  buildings (market/carpenter/church/warehouse/townhall) log NOTHING at placement — their resolver tags the
  resulting action's log with the building; ship/castle/monastery pass `via` into the shared cores
  (`_do_take_hex/_do_place_tile/_do_sell_goods/_do_take_workers` + `_sell_color` gained a `via=` param).
  `vp_breakdown` catches watchtower under `build_gain` (only vp-bearing building). The log render skips the
  generic "(+VP)" suffix for `build_gain` (it already states "gained 4 VP") to avoid doubling. **Legacy
  `building_effect` records still render** ("used X") for old saved games.
- **THE RECONNECT FIX (load-bearing — a bot turn froze for MINUTES).** CoC's `useSocket` had **NO
  auto-reconnect** — `ws.onclose` only set `connected=false`. A vs-bot turn is re-driven ONLY when the client
  reconnects (`_handle_reconnect` re-triggers `_schedule_bot_turn`), so a Render cold-start (or any blip / iOS
  backgrounding) that dropped the socket left the bot's turn un-driven until a manual refresh. Fix (frontend-
  only): a backoff reconnect loop (`attemptReconnect`, reused by a `visibilitychange` nudge so neither leaves
  the loop dead) that reconnects with the **`reconnect` action, NOT `join`** (join doesn't resume the bot),
  retries through the ~30-50s cold-start window, and **checks `socketReady()` (readyState) to NOT abort a
  pending CONNECTING socket** (a cold-starting Render holds the WS open until up — aborting it every timer tick
  would thrash). A "Reconnecting…" banner (`.coc-reconnbar`) shows the state. On reconnect the client
  re-arms `client_ai` automatically (existing effect). Diagnosed by pulling the stuck game from Turso (it had
  COMPLETED — proving it was a client-side un-driven-turn issue, not a backend deadlock).
- **Post-turn settle + close linger (bot-turn pacing).** Backend `_POST_TURN_PAUSE=1.0` in `_schedule_bot_turn`:
  waits before the bot's FIRST move on a *playing* turn (skipped during setup / superseded by the longer
  `_PHASE_END_PAUSE` on a phase change) so finishing your turn isn't instantly steamrolled. Frontend matches it:
  the opponent-board auto-open is **delayed ~1s**, and when the bot's turn ends the board **lingers ~1s** before
  returning to yours (both via `botViewTimer`, gated so the setup-reveal `revealHoldRef` wins). **GOTCHA (cost a
  CI failure):** `test_client_ai.py`'s isolation zeroes the pacing constants for speed but didn't know about the
  new `_POST_TURN_PAUSE`, so the real 1s-per-turn sleeps overflowed its driver loop on CI's fine timers (it
  passed locally only because Windows' coarse timer resolution inflated the loop's wall-clock) → **any new
  pacing constant must be zeroed in `_isolate`.**
- **Setup castle reveal REWRITE (supersedes the 550ms delay above).** The bug: the bot's SECOND starting castle
  transitions the game straight to "playing" in the SAME update that places it, so the generic `aiThinking`
  auto-close fired at the exact moment the pop-in played → board vanished as the animation ran. Fix: a DEDICATED
  effect owns the reveal — on a **witnessed null→placed transition** of the opponent's castle (`prevOppCastleRef`
  starts `undefined` = first snapshot = never reveal → reconnect-safe), it opens their board, spawns the pop-in
  (two rAFs so `[data-oppsid]` exists), holds ~1.9s (`revealHoldRef` BLOCKS the generic handler from closing),
  then releases. `botViewTimer`/`revealHoldRef`/`aiThinkingRef` coordinate the generic open/close with the reveal.
- **Arm-then-act interaction pattern (now consistent across the game).** Every resource spend requires an
  explicit selection first, then a target click: **select a die** before take-hex/place/sell; **click the
  workers token** to arm **Monastery #6** then click a building tile in a depot (2 workers); **click the silver
  token** to arm a **black-depot buy** then click a black tile (2 silver). `canUseM6`/`canBuyBlack` mirror the
  engine's `legal_moves` gates so the token only rings gold (`.coc-arm`) / pulses when armed (`.coc-on`) when the
  action will actually succeed; a reset effect disarms the moment it's no longer usable. **Monastery #6 had NO
  UI at all before this** (the frontend never sent `monastery6_take` — the engine always supported it).
- **Goods click-to-sell.** Click a goods chip in your storage to sell it. Ability sells (Warehouse pending /
  Castle bonus's chosen die) sell on click directly; a NON-ability sell requires a **die SELECTED first** whose
  value == the goods' sell number (only those goods pulse/are clickable), else the click just shows the goods
  description. `sellDieForGood`/`canSellGood`/`sellGood`.
- **Review section headers.** Dropped the "During the game" subheader (the per-phase dividers already segment
  it) and render "End of game" as a **centered divider** (`.coc-review-phase`, `.proj` fade), so the review reads
  Phase A…E then End of game.
- **Client-AI sim logging (Expert tier).** The client-AI driver prints ONE `[coc client-AI] turn used N sims`
  line per bot turn to the dev console (sum of root visits across the worker pool, accumulated in `turnSimsRef`
  across the turn's decisions, printed when the bot hands back). Nothing prints if the server watchdog took the
  turn (client did no searching).

### Session (July 2026) — keep-alive / cold-start mitigation (deploy infra, NOT a game change)
Render free tier spins the backend down after ~15 min idle (~30-50s cold start), which surfaced as slow site
loads AND mid-game freezes (see the reconnect fix above). Durable facts:
- **GitHub Actions SCHEDULED workflows are too unreliable for keep-alive** — measured **~1 of 28 expected 5-min
  runs actually fired** in 2+ hours (they're heavily delayed/skipped, worst near :00). So `.github/workflows/
  keepalive.yml` is now a **LONG-LIVED pinger**: each run pings `/health` every ~4 min for ~56 min before
  exiting (public repo → free Actions minutes), so a single sparse firing keeps the backend warm for ~an hour;
  hourly-ish starts (`23 14-23,0-5 * * *`, off-peak minute) chain to cover the window. **This is only a backup.**
- **cron-job.org is the recommended RELIABLE primary** (fires on time; user sets it up — external account): URL
  `https://splendid-nelz.onrender.com/health`, every 5 min, timezone **America/Los_Angeles** (auto-DST) restricted
  to **07:00-22:00**. GitHub cron is UTC-only (no DST); the window `14:00-05:59 UTC` covers 7am-10pm PST/PDT with
  ≤1h overhang.
- **Budget:** Render free tier caps at **~750 instance-hours/month**; daytime-only warming (~15h/day ≈ 450h)
  fits with headroom, but keeping BOTH Render services (spender-backend + the decommissionable wwsd one) warm
  24/7 would blow it. `/health` (site-root, no DB) is the cheap warm endpoint.
- **Warm-on-load ping** in `webapp/index.html` (`<head>` inline script, **prod hosts only** — `forry4.github.io`
  / `*.workers.dev`): fires a fire-and-forget `fetch('/health')` before the bundle loads so a cold start overlaps
  page load. CAVEAT (do not oversell): this does NOT help the visitor who TRIGGERS the cold start (the site needs
  the backend immediately; the spin-up takes 30-50s regardless) — it only helps a later visitor. The daytime cron
  is the load-bearing part. The only *guaranteed* fix is the $7/mo Render Starter tier (no spin-down).
- Query the stuck/finished prod game state directly from Turso (creds in gitignored `C:\Users\Forrest\.spender_turso`;
  `curl` POST to `<https-host>/v2/pipeline`, use a BOUND arg `{"type":"text","value":"ROOMID"}` — a
  double-quoted id in SQL is read as a column). The room dict is `state_json`; `coc_games` has the game.

### Session (2026-07-08) — wwsd decommission + CoC turn-latency levers + building-placement highlight fix
- **wwsd Render service DECOMMISSIONED (`bdcf8e6`).** The 2nd free Render web service (`wwsd-backend`) is removed
  from `render.yaml` (user deleted it in the Render dashboard). WWSD runs entirely in the friend's browser now —
  the Rust→WASM Tampermonkey userscript `wwsd/wwsd_browser_n.user.js` makes ZERO backend calls (verified: 0
  `onrender` refs; its lone `fetch` is dead wasm-loader boilerplate, since the wasm is inlined as base64). The old
  `wwsd/autoplay.user.js` was the only remaining caller of `/move` (long superseded). The `wwsd/` Python package
  stays as reference; to restore, re-add a `- type: web` block running `uvicorn wwsd.app:app` + recreate the
  service. Unrelated: the spender-backend keep-alive (cron-job.org) auto-disabled after a Render-side **~2h 503**
  outage that aligned exactly with the daytime cron window OPENING (14:00–16:05 UTC = the first pings after the
  overnight spin-down; NOT a deploy — last deploy was 8h prior) → re-enable the cron + loosen its failure
  tolerance; the only *guaranteed* cold-start/blip fix stays the $7/mo Render Starter tier.
- **④ Overlap the Expert bot's client search with its move-animation pause (`f86fe3e`, backend — CORRECTS the P5
  "the ai_move handler applies" doc).** `_client_bot_turn` now ships the NEXT decision's `ai_search` BEFORE
  awaiting the current move's animation pause, and **`_handle_ai_move` BUFFERS the resolved move into
  `room["_ai_pending_move"]` (+ clears `_ai_search`, sets the evt) — it NO LONGER applies/broadcasts/saves**; the
  apply moved into `_client_bot_turn`, which applies the buffered move AFTER awaiting the pause (a `pause_task`
  from the previous move that runs concurrently with the client's next search). So the ~900ms search hides under
  the ~1s inter-move pace instead of adding to it (~0.9s/decision, ~2-3s/bot turn saved; NO strength or per-move
  pacing change). DO NOT REGRESS: the illegal/stale early-returns stay ABOVE the buffer (an illegal submit leaves
  `_ai_search` armed for the watchdog — `test_illegal_client_move_is_dropped`); `_ai_pending_move` is cleared
  alongside `_ai_search` on timeout AND in `_schedule_bot_turn`'s finally so a stale move can't leak; the old
  `_ai_phase_changed` room key was REMOVED (phase_changed is computed in the apply block). `test_client_ai.py` +
  the full 307-test CoC suite pass.
- **① Optimistic move preview (`d35d3ce`, frontend).** Your own moves render INSTANTLY instead of waiting the
  ~90ms round trip. `mv()` runs the module-level `optimisticMove(game, move, myId)` — deep-clones the game dict
  and applies the CERTAIN visible effect of the core moves (place_tile / take_hex / discard_storage: tile in/out
  of storage/duchy + die marked used), then `setRoomData` shows it; the server's authoritative `room_update`
  reconciles wholesale (clears `optimisticRef`), and an `error` reverts to `preOptimisticRoomRef`. SAFE BY
  CONSTRUCTION — the server never sees the preview (it's a PREVIEW not a client engine: the coc-core WASM is
  search-only, `coc_step_info`/`coc_search_timed`/`coc_chain_move` over the LOSSY compact projection, no
  apply→renderable-dict entry), it's scoped + guarded (bails to null on not-my-turn / a pending / missing tile /
  occupied space / full storage), and it can't corrupt game state. Only those 3 moves are predicted — they don't
  touch workers/silver/goods, so no spurious resource flyers; everything else falls through to send-and-wait. The
  diff-based flyer animates the previewed tile ~90ms SOONER with no double-fire (the reconcile diffs
  optimistic→server, same tile → no re-animate). ① lives in its own commit; `git revert d35d3ce` removes ①+②.
- **② Faster flyers (`d35d3ce`, frontend).** Tile flyer `coc-fly .5s→.35s`, worker/silver token flyers
  `coc-tok-out/in .6s→.42s`, flyer cleanup timer `640→460ms`.
- **BUILDING-PLACEMENT HIGHLIGHT FIX (frontend-only).** The yellow legal-placement glow wrongly invited placing a
  building in a region that ALREADY holds that same building type. The engine's `_building_town_ok` rejects that
  (unless you own **monastery effect 1**) — enforced in `_do_place_tile` + all three `legal_moves` enumerations
  (die / extra_action / townhall) — so the CLICK failed, but the `legalTarget` highlight in
  `CastlesOfCrimson.jsx` mirrored color/number/adjacency/occupancy and OMITTED the one-building-per-region rule.
  Fixed by reproducing `_building_town_ok` client-side: flood-fill the same-color connected component of `sid`
  (== the engine REGIONS, since the 37-cell grid + adjacency are identical across all boards) over the board
  spaces, reject if any placed tile in that region is a building of the same `.building` type; skipped when
  `me.monastery_effects` includes 1. No backend/payload change — tiles already carry `.type`/`.building` (used
  elsewhere in the render) and regions are derivable from the board-space colors the client already has.

### CoC Expert AI campaign ("CoC-N") — coc-core crate (July 2026; P0-P2 DONE, gates passed)
Building an N-class learned AI for CoC by the proven Spender recipe. Approved plan:
`.claude-plans/i-want-to-develop-staged-charm.md` (user decisions: plateau-gated strength, client-side
Rust→WASM serving, straight-to-learned-net — the heuristic scaffold is training infra only, never
shipped — and a NEW "Expert" lobby tier; Normal/Hard untouched). New **`coc-core/` crate at repo root**
(sibling of spender-core, patterns cloned not shared; in NO CI path filter, so committing it never
deploys anything). Memory: [[coc-expert-ai-campaign-status]].
- **P0 (done):** generated static tables (`tools/gen_board_tables.py` → `boards_gen.rs` + the canonical
  space index mirrored to `games/castles_of_crimson/az/spaces.py` — spaces sorted by (r,q); the 37-cell
  grid AND adjacency are IDENTICAL across all 9 boards, asserted; MAX_REGIONS=21). Tile codes u16
  (1 start-castle, 2 castle, 3 mine, 4 ship, 5-13 livestock, 14-21 building, 22-47 monastery=effect_id).
  State = fully inline fixed-capacity (816B, clone=memcpy 22ns); PV-net probe 2.8-4.5k evals/s/core at
  700-900 dims → feature budget up to ~900 dims is fine.
- **P1 (done): Rust engine port + differential parity.** `engine.rs` behind a fixed **102-action
  micro-decomposed space** ("spend die → menu → place-slot → space"; XVALUE kills the 150-move
  extra_action node; `Micro::None` invariant at every engine-move boundary; A_WORKERS always legal ⇒
  no micro deadlock). Monastery effects = one 26-bit `mon_mask` switch. 7.8M micro-moves/s
  (legal+apply). **Parity: 2300 fixture games / 567,080 engine moves, state-exact** (FNV-64 of the
  canonical projection string after EVERY move; `compact.py` ⇄ `proj.rs` must never drift
  independently), legal-move TRIE equality at recorded positions (proves the decomposition equals
  `engine.legal_moves` in BOTH directions), coverage gate all-green (all 26 monasteries, all pending
  chains, refunds, tiebreaks; "loaded" scenario games backfill rare paths). Dice injected per-move via
  `State.dice_script` (sidesteps Mersenne-vs-splitmix). Parity-critical engine facts: `_draw` pops the
  pile END / `_draw_type` scans from 0; legal-adjust affordability uses cost-from-CURRENT-value while
  apply charges net-from-orig; ship_choose offers all 6 depots even empty; pendings clear BEFORE their
  sub-action (chains survive); dice roll in SEAT order; ShipAdj pending stores the CANDIDATES mask
  (source depot unrecoverable from engine ctx). Run tests with `--features bridge`
  (`cargo test --release --features bridge`; fixtures via `tools/gen_engine_fixtures.py`, gitignored).
- **P2 (done, gate PASSED): scaffold search.** `mcts.rs` = spender determinized-PUCT clone
  (canonicalize-sort + shuffle the 3 undrawn piles + reseed dice stream per sim; identity-based backup;
  terminal = tanh(margin/12)); `heuristic.rs` = exact ai.py `_value` port (scalar parity 857 pos ≤1e-9);
  `vsearch.rs` = priors from move-type priority softmax + **rollout-then-eval leaf**; ai.py `_legal`
  pruning ported into `engine::legal_actions` (full vs search variants). Cross-impl gate via
  `move_server_coc` (bridge bin) + `games/castles_of_crimson/az/rust_arena.py` (CRN seat-swapped pairs,
  per-decision server calls, Python side driven exactly like ai_selfplay): **0.715 [0.649,0.773] vs
  ai.py hard over 200 games** at 2000 sims/decision (vs normal 0.95).
- **FINDING (do not regress): a PURELY STATIC heuristic leaf FAILS in CoC** — 0.235 vs hard. CoC's
  `_value` was tuned as a PAIR with the Python bot's rollout (storage credit 0.35/tile stands in for
  "about to be placed for a region score"), so a static leaf undervalues in-flight turns. The scaffold
  leaf runs a 20-micro-step priority rollout then evaluates → 0.715. This does NOT contradict the
  Spender static-value-leaf lesson; it means the P3 learned value must price in-turn continuations
  (outcome-trained does this naturally).
- **OUTAGE-CLASS LESSON (fixed in `6dbbcbf`): never create a package named like an existing module.**
  The az tooling briefly lived at `games/castles_of_crimson/ai/az/` — the new `ai/` PACKAGE shadowed
  `ai.py`, breaking `from . import ai as coc_ai` in prod (bot turns would AttributeError). Tooling now
  lives at **`games/castles_of_crimson/az/`** (compact.py projection, bridge.py engine-dict⇄compact
  moves both directions, spaces.py generated, rust_arena.py).
- **P3 (done): bootstrap net + the pivotal decomposition.** `feats.rs` = the FROZEN 934-dim encoder
  (groups documented in-file; per-space block feeds the 37-way SPACE head; input-dim change = full
  restart). Harvest 5000 scaffold self-play games (1.15M rows, `C:\Users\Forrest\coc_run\boot.t*.csv`);
  `tools/train_pv.py` (streaming, GAME-split holdout, SHAPE_A=0.3 ⊕ β=0.3 root value, margin SCALE
  auto ≈34) → `pv_boot.json`: val AUC 0.798, top-1 0.586; torch↔Rust `net_export_check` 3.5e-7.
  **CRN is EXACT in CoC** (the dice stream advances 5 rolls/round regardless of play ⇒ one seed fixes
  deck+dice for both seat orders; position-derived search seeds make the A-vs-A gate control EXACTLY
  0.5000). **VERDICT (do not relitigate): the pure net leaf LOSES to the scaffold at equal sims
  (0.275 @128v128; depth doesn't rescue it), but the HYBRID — net PRIOR + rollout-heuristic VALUE —
  BEATS the scaffold 0.567 at equal sims.** The policy head distilled well; the value head lags
  (CoC's rollout-augmented teacher leaf sets a higher bar than Spender's static v_state). Net-argmax
  vs full search ≈0.03 is normal (1-ply), not a distill failure.
- **P4 (RUNNING): hybrid ratchet** — `tools/loop_coc.sh` (resumable: `progress_coc` + ITER-k-DONE +
  `sp_k.HARVESTED` markers so a mid-iter restart skips a completed harvest):
  hybrid self-play (`harvest_boot <out> <games> <sims> 20 <seed> 10 pv_best.json hybrid`) → train both
  heads warm-from-best (2-iter window + boot anchor) → cand-vs-best hybrid gate (promote ≥0.52) +
  **pure-pv-vs-hybrid probe (the value-head takeover signal: flip self-play mode to `pv` when it
  crosses 0.5)** + scaffold@2000 yardstick. Watch `coc_run/loop_log.txt`. If flat after ~8 iters:
  raise self-play sims first (the proven lever) before touching targets/architecture.
  **MSYS ARG-CONVERSION FOOTGUN (cost 3 silent no-op iterations — do not regress):** Git Bash
  auto-converts `/c/...` args for native exes but SKIPS args containing `*` (train_pv's `--data`
  globs → Python glob matched NOTHING) and `:` (`model.json:hybrid` gate specs → Rust `File::open`
  on an unresolvable POSIX path). loop_coc.sh now passes **cygpath'd `$RUNW` Windows-style paths to
  every native tool** + `set -o pipefail` + a gate-parse FATAL guard so a failed stage aborts loudly
  instead of "kept best ()". Validate any loop change with a miniature dry iteration
  (`RUN=<dry-dir> ITERS=1 GAMES=20 SIMS=32 GATE_PAIRS=2 ... bash tools/loop_coc.sh`).
- **P5 (DONE, LIVE on prod): Expert tier = client-side WASM serving.** Prod e2e PASSED (Playwright
  on forry4.github.io: guest → CoC → Expert game → the bot's decision shipped as `ai_search`, the
  browser's 4-worker pool searched it and submitted `ai_move`, server validated + applied).
  - **Protocol (per-DECISION, prefix-based):** the server (`games/castles_of_crimson/main.py`)
    ships each bot ENGINE-MOVE decision in room state as `ai_search = {decision, seat, mode,
    budget_ms, max_sims, state: az.compact.project(game) with the 3 undrawn pools SORTED}` (lives in
    room state so re-broadcasts/reconnects re-ship it); the client loops stepInfo → (forced |
    root-parallel `coc_search_timed`, visits SUMMED across workers) → append to prefix → at the
    Micro::None boundary `coc_chain_move` → `ai_move {decision, move}`. Server resolves via
    `az.bridge.compact_to_move`, validates by MEMBERSHIP in `engine.legal_moves`, applies, wakes the
    scheduler (`_client_bot_turn` + asyncio.Event). Single-legal decisions apply server-side.
    Watchdog `CLIENT_AI_TIMEOUT=8s` → the turn falls back to the HARD server bot (per-turn
    degradation, deadlock impossible — the finisher still guarantees turn end); stale/illegal
    ai_moves are logged + dropped (never a user toast); `client_ai` disarms on socket disconnect.
    Tests: `tests/test_client_ai.py` (full game through the simulated client, watchdog, illegal-drop).
  - **Model is NOT embedded in the wasm** (improves on the Spender include_str pattern): the worker
    fetches `webapp/public/wasm/coc_pv_model.bin` (compact f32 blob, ~2.6MB, browser-cached) once
    and passes it to `coc_init_model`. **A model upgrade = `python coc-core/tools/pv_json_to_bin.py
    <winner.json> webapp/public/wasm/coc_pv_model.bin` + push — NO wasm rebuild.** The wasm itself is
    192KB (`coc_core.js`/`coc_core_bg.wasm`, wasm-pack --target web). `netio::pv_from_bin` is
    bit-identical to the JSON loader (verified by `net_export_check <json> <bin>`).
  - **Serving mode `_EXPERT_MODE="netval"`** in CoC main.py (see the P4/P6 result below — netval
    beats hybrid). Serves the P3 bootstrap net (`coc_pv_model.bin`) — the ratchet produced no
    better net (winner's curse), and netval's gain is the LEAF not the weights, so no model swap.
    Lobby: Expert joins Normal/Hard in the vs-Bot picker (`AI_DIFFICULTIES` += "expert").
  - **wasm entries** (`coc-core/src/wasm.rs`): `coc_init_model(bytes)`, `coc_step_info(state,
    prefix)` → `{over,boundary,actor,forced,legal}`, `coc_search_timed(state, prefix, mode,
    budget_ms, max_sims, seed)` → visits[102] (`mode` ∈ `netval`|`hybrid`|`pv`|`heur`),
    `coc_chain_move(state, prefix)` → compact move JSON. `pxio::from_proj` (the P2-arena-validated
    ingestion) is the shared Dump path (gate widened to wasm32). Worker:
    `webapp/public/wasm/coc-worker.js`; frontend pool + driver effect in `CastlesOfCrimson.jsx`
    (Spender s-worker pattern; re-announces `client_ai_ready` per socket; forwards the server's
    `mode`).
- **P4/P6 RESULT (2026-07-06/07) — the hybrid ratchet PLATEAUED; `netval` is the one real gain
  (SHIPPED, `f0cb97a`). DO NOT relitigate.** Full detail in memory
  [[coc-expert-ai-campaign-status]].
  - The 8-iter hybrid ratchet (sims=400) produced NOTHING over the P3 bootstrap: its one "promotion"
    (iter-3, gate 0.5417 @n=120) was **winner's curse** — a fresh-seed re-gate (iter-3 vs bootstrap,
    both hybrid, n=240) = **0.4833**. The promote gate (candidate-vs-MOVING-best @200 sims, n=120,
    ±0.09) is too noisy to detect small gains; the **scaffold yardstick (FIXED reference) is the
    trustworthy signal** and was flat (~0.36-0.44) all run. (Loop bug fixed: MSYS skips `/c/`
    conversion on args with `*` or `:`, so the trainer/gate got POSIX paths and silently no-op'd 3
    iters → cygpath every native-tool arg (`$RUNW`), `set -o pipefail`, gate-parse FATAL guard,
    `sp_k.HARVESTED` resume markers.)
  - **Value-head takeover is CLOSED (two ways): (1)** outcome-target retrain
    (`coc-core/tools/train_pv_exp.py`, `--shape-a/--beta`; 80% outcome vs the loop's 49%) left the
    value head IDENTICAL as a pure-PV leaf (h2h 0.50, AUC unchanged 0.80) and still losing to the
    rollout (0.275) — NOT a training-target problem. **(2)** P3 gates re-confirm the pure net fails
    vs scaffold (argmax@0 vs scaffold@2000 = 0.025; pure-pv@128 vs scaffold@2000 = 0.135).
  - **THE FIX = `netval` (`vsearch::hybrid_netval_eval`): net policy prior + 20-step priority
    rollout + the net VALUE HEAD at the truncation** (learned long-horizon read) instead of the
    heuristic `_value`. WHY it works where a static leaf fails: CoC is a DELAYED-PAYOFF game (mine
    income compounds over phases, regions score at completion, monasteries at endgame), so a 0-step
    static eval (heuristic OR net) undervalues in-flight turns (the P2 fact: static 0.235 vs rollout
    0.715); netval plays the near-term payoffs out THEN applies the learned eval. **Gated: netval vs
    hybrid = 0.542/0.579 (two fresh seed bases) @200, 0.606 @512 (edge GROWS with sims → transfers
    to serving's ~20k); netval@512 vs scaffold@2000 = 0.52 (hybrid was 0.36); sanity
    netval-vs-netval = 0.5000.** SAME bootstrap net — the gain is the leaf.
  - **LEVER LESSON:** in CoC the value head IS impactful, but only AFTER a short rollout resolves the
    near-term delayed payoffs. More hybrid-ratchet self-play/sims is dead; the leaf architecture was
    the lever.
  - **UNTESTED LEVERS DONE (2026-07-07):**
    - **Rollout-length + C_PUCT sweep → tuned netval SHIPPED (`c119eb3`).** The inherited 20-step
      rollout was too SHORT for the net-value leaf. Fresh-seed confirmed vs `netval@20@1.5`:
      steps=30 alone 0.583 @200 but SOFTENS to 0.54 @1024 (a low-sims win); c_puct=1.0 alone 0.538;
      **COMBO steps=30 + c_puct=1.0 = 0.617 @200 / 0.570 @512 / 0.642 @1024 — GROWS with sims so it
      TRANSFERS** (the c_puct=1.0 'commit faster' part carries at depth; steps alone decays). Serving
      uses `vsearch::NETVAL_ROLLOUT_STEPS=30` + `NETVAL_C_PUCT=1.0` (wasm netval arm); scaffold/
      hybrid/pv keep 1.5/20. Same net (`coc_pv_model.bin` unchanged) — the gain is the leaf CONFIG.
      Tool: `gate_coc <path>:netval@STEPS@CPUCT` (@-delimited so a Windows path's `:` is safe).
    - **`netval` self-play loop — `coc-core/tools/loop_coc_netval.sh` (RUN=`/c/Users/Forrest/coc_run_nv`).**
      The structural test the hybrid ratchet couldn't be: self-play + gate BOTH use the netval leaf
      (`harvest_boot` gained a `netval` mode), so the value head trains WHERE IT'S USED. If the
      promote gate MOVES (unlike the hybrid ratchet's flat plateau) → netval self-play improves the
      net → re-gate the winner at the serving config (30/1.0) + swap `coc_pv_model.bin`. Loop
      self-plays at the default 20/1.5 (leaf config is ~irrelevant to the value head, which trains on
      outcomes; re-gate the winner at 30/1.0 before shipping). Watch `coc_run_nv/loop_log.txt`.
      **RESULT (2026-07-07): NETVAL SELF-PLAY WORKS — the loop's iter-5 net SHIPPED (`d0156cb`).**
      Gates ran 0.475/0.4625/0.450 (flat — looked like the hybrid plateau) then CLIMBED
      0.506/0.544*/0.569* (iters 4+5 promoted). **Fresh-seed re-gate vs the bootstrap: 0.5875
      ±0.044 (n=480, margin +7.1) — NOT winner's curse**; at the SERVING config (30/1.0):
      **0.6208 ±0.043 @200 (n=480), 0.6083 ±0.062 @512 (holds at depth → transfers to ~20k).**
      Swapped `coc_pv_model.bin` (pv_json_to_bin, json↔bin bit-identical PASS; no wasm rebuild);
      winner preserved as `coc_run_nv/pv_ship_iter5.json`. **LESSON (supersedes the early plateau
      read): the flat first 3 iters were the BOOT-ANCHORED data washing out of the 2-iter training
      window — judge a self-play loop only after the window is pure self-play data.** The
      hybrid-ratchet conclusion stands unchanged (it benched the value head); netval self-play
      trains it where it's used and genuinely improves it. **EXTENDED RUN COMPLETE (12 iters
      total): iters 6-11 = SIX consecutive non-promotions vs the iter-5 bar (0.475/0.475/0.425/
      0.469/0.506/0.469) → the recipe CONVERGED on the iter-5 net (the shipped one). Do not
      re-run this loop as-is expecting more** — the next gain needs a STRUCTURAL change first
      (feature round 2: time-discounted per-tile depot values + 26-way monastery identity —
      per-depot tiles are currently type-onehot + ONE effect_id/26 scalar, see feats.rs
      push_tile; and/or higher-sims teacher; and/or attention P4b), then netval self-play to
      consolidate it (now proven to work in CoC). Human playtest verdict pre-upgrade: the user
      beats the Expert soundly; re-test against the upgraded one, and mine the user's coc_games
      for the concrete edge before locking the feature set.
    - **PERF: vectorized net forward ~6.5x native / ~3x wasm (`21c7d9a` + `89099bc` — DO NOT regress).**
      The netval leaf was ~97% net forward (bench_coc breakdown: forward 489µs vs features 2.9µs, heur
      0.1µs, rollout ~6µs), and `valuenet::linear`'s single-accumulator dot is a serial FP dependency
      chain LLVM may NOT vectorize (float reassociation forbidden) — ~1.3 GFLOPS on a Zen 4 core. Fix:
      32-lane (4×8) chunked multi-accumulator `dot` (autovectorizes) + **`coc-core/.cargo/config.toml`
      `-C target-cpu=native`** (native x86_64-msvc only; wasm32 untouched) + `forward_value_raw`
      (value-head-only truncation eval) + inv_sd precomputed at load. **Native: forward 489→73µs, netval
      search ~1,000→~5,300-5,800 sims/s/core (~5.5x); wasm (`+simd128` via RUSTFLAGS on the wasm-pack
      call): 466→~1,420 sims/s single-thread → the live Expert gets ~3x the sims/decision in its 900ms
      budget (same net/protocol; a no-simd browser fails wasm init → existing hard-bot fallback).**
      Parity holds (net_export_check 3.3e-7, tighter than before). The netval loop was killed mid-iter-1
      + relaunched on the fast build (clean: HARVESTED markers + File::create truncation; iter-0 gate ran
      on the old binary — win rates stay comparable, CRN is within-gate). Remaining perf levers if ever
      needed (diminishing): int8 quantization, GPU inference server.
    - **PERF round 2 (`675f8c5`): BATCHED netval leaf evals, ~2.3x more on the forward, BIT-IDENTICAL —
      the default for all offline experiments.** Each harvest/gate thread drives K games (default 8) in
      lockstep — one sim per game per round, all leaves through ONE `valuenet::forward_batch` pass. No
      virtual loss / no cross-thread sync → search semantics unchanged; **batched runs reproduce
      sequential (`batch=1`) EXACTLY** (verified: identical gate lines netval-netval + netval-SCAFFOLD;
      batched A-vs-A = 0.5000/+0.0). Key pieces: `valuenet::dot4` (register-blocked 4-input kernel —
      weights stream K/4 times, x-block L1-resident; 80→34µs/eval @K=8), `mcts::Search::descend`/
      `complete` (sim() split at the leaf seam, one shared code path), `batch.rs` (SearchTask +
      step_netval), `[batch]` arg on gate_coc/harvest_boot (default 8 — loop scripts need no change).
      **FINDINGS (do not relitigate): (1) plain row-reuse tiling was a WASH** — it trades L3 weight
      traffic for L2 activation streaming; the register-blocked kernel is what pays; **(2) an 8-input
      block CRATERED** (register spills, 4× worse) — 4 is the sweet spot; **(3) `dot` is now a single
      8-lane chain = the CANONICAL accumulation order `dot4` replicates per pair** (this shared order IS
      the bit-identity mechanism; multi-chain ILP bought nothing — the matvec is load-bound). Harvest
      batched path uses a PER-GAME opening-temp rng (deterministic under interleaving; the one behavior
      delta vs sequential). **WASM CAUTION:** dot's chain width changed (4×8→1×8); native is identical
      (load-bound) but v128 has no FMA — A/B any future wasm rebuild in Node vs the deployed 466→1,420
      sims/s baseline before shipping.
    - **PERF round 3 (`ed579dd`): int8+VNNI quantized netval — STRENGTH-NEUTRAL (fresh-seed gate
      0.5000 ±0.069 n=200; a first-gate 0.450 was seed noise, pooled 0.481 ±0.055) — use for
      SCREENING experiments.** Opt-in: gate spec `:netval8[@STEPS@CPUCT]` / harvest mode `netval8`;
      f32 stays the default and model files stay f32 JSON (quantized at LOAD:
      `QuantPolicyValueNet::from_f32`, per-row symmetric int8 on the two trunk layers = 96% of MACs;
      heads/z-score f32; dynamic per-vector activation quant, zero-point-128 u8 for `vpdpbusd`).
      `qdot` = AVX-512 VNNI intrinsic under `cfg(target_feature="avx512vnni")` (true via
      target-cpu=native on the Zen 4 box) with an exact-same-INTEGER-result scalar fallback → int8
      runs are deterministic and machine-portable (netval8 A-vs-A mirror = exactly 0.5000). Quality:
      value MAE ~5e-4, policy-argmax 62/64 vs f32. Speed: int8 SINGLE forward (137µs loaded) already
      beats the f32 blocked-BATCH path (169µs) — no int8 batch blocking built yet (model is
      L2-resident at 640KB, so blocking pays less; optional future work). **USAGE GUIDANCE: int8 for
      screening/paired experiments (both sides share arithmetic → unbiased); f32 for final/ship
      gates and the FIXED scaffold-yardstick trend line (cross-arithmetic comparability). Do NOT
      switch a RUNNING campaign's arithmetic mid-loop.** The `PvEval` trait (valuenet.rs) is the
      seam: `pv_eval`/`hybrid*eval*`/`root_readout_pv`/`batch::step_netval` are generic over it.
      NOTE `:netval8` must parse BEFORE `:netval` in gate_coc (substring).
    - **PERF round 4 (`384eb49`): GPU inference sidecar for harvests — ~3.7x (325-333k evals/s vs
      ~88k CPU f32-batch).** `tools/gpu_server.py` (torch cu128, localhost TCP, z-score FOLDED into
      trunk[0] at load + zero-copy request parse) + `src/gpueval.rs` (`GpuEval` behind the `PvEval`
      seam, pooled connections, native-only) + harvest mode `netvalgpu` (addr via `COC_GPU_ADDR`).
      **Startup parity guard (do not remove): harvest forwards one probe through BOTH paths and
      asserts ≤1e-3/1e-2 — a stale/wrong server model can never poison a harvest** (measured diff
      3.6e-7). HARVEST TIER ONLY (torch GPU arithmetic, not bit-identical) — ship gates stay CPU
      f32. FINDINGS: per-REQUEST overhead (client RPC + server GIL ~590µs) is the whole game —
      rows/request = 2×K, so **K=64 is the config** (128-row requests; the 20-game smoke test at
      K=2-per-thread ran 60x slower than CPU); **K=128 memory-thrashes** (~1280 in-flight trees
      blow past free RAM → near-zero throughput, not a crash); games/thread must be ≥K to fill the
      lockstep. Server prints 10s `[stats]` lines (evals/s, reqs/s, rows/req). Loop wiring
      (`loop_coc_hs.sh`): server started per iteration with the CURRENT pv_best, **PID-killed
      after harvest — NEVER `taskkill //IM python.exe` mid-loop (the trainer is python too)**.
      Net effect: a 2000g@1200-sims harvest ~2.3h → ~36 min; hs-loop iteration ~2.8h → ~1.1h.
    - **FEATURE ROUND 2 (2026-07-08): time-value features = WASH (do not relitigate the flat-MLP
      form).** Encoder v2 (`feats::features_v2`, 1078 = v1 934 byte-identical prefix + Group J 144:
      per-offer-slot `tile_time_value` (mine/continuous-monastery yield × phases_left; endgame-mon
      exact multiplier + headroom) for my 19 slots + 16 contested opp slots, flags, 26-dim effect
      unions). Full unattended chain (`tools/loop_coc_v2.sh` + overnight orchestration): champion
      distill-harvest 5000g@500 logging v2 (`coc_run_v2/boot2`) → fresh v2 distill (val AUC 0.791,
      top1 0.695, parity 1.8e-7; **0.425 vs champion** — distill compression loss) → 9 netval
      self-play iters. The v2 line ONLY RECOVERED its distill deficit: fresh-seed cross-gates vs
      the v1 champion **0.496 ±0.045 (n=480) train config / 0.521 ±0.045 serving config @200 /
      0.492 ±0.063 @512** (no depth transfer), then iters 6-8 = 0.481/0.450/0.506 non-promotions →
      user stopped it. **Verdict: the MLP already infers the time×tile-value interaction from
      phase/round one-hots × tile types; explicit Group J adds nothing** (the CoC analog of
      Spender's v3/v4 feature-screen washes — attention/MLP already computes the cross-terms).
      Infra keeps: the `Enc` seam (input-dim → encoder, so v1/v2 nets coexist), `logenc` harvest
      arg (play vX, log vY — the distill-harvest pattern), `train_pv.py --in-dim`. State preserved
      resumable in `coc_run_v2` (progress_v2=9). **Next levers, in order: mine the user's
      coc_games for the concrete human edge (BEFORE more feature guesses); higher-sims teacher
      re-bootstrap; attention (P4b).**
    - **RUNG 1+2 (2026-07-08/09): high-sims teacher + PCR both PAID — new champion SHIPPED + the
      lobby ladder RESHUFFLED (`1d93cdd` backend + `5ec78cf` frontend).**
      - **Rung 1 — high-sims continuation (`loop_coc_hs.sh`, coc_run_hs):** netval self-play at
        SIMS=1200 (4x the converged 300), warm-seeded FROM the champion (no distill compression —
        the FR2 trap), NO boot anchor, GPU harvest. 4 iters, promotions at iter 0 (0.546) + iter 3
        (0.521). Fresh-seed cross-gates: **iter-3 net = +0.04 real** (0.542 train / 0.548 serve /
        0.521 @512); the iter-0 net's gain did NOT transfer to serving config (0.500) — always
        cross-gate at the serving config before believing a training-config gain.
      - **Rung 2 — PCR combined campaign (`loop_coc_r2.sh`, coc_run_r2):** PCR 250@200 (25% of
        decisions at the FULL 2000-sim cap -> policy rows; 75% at 200 -> value-only rows) x 4000
        games/iter x GPU, seeded from hs iter-3. Iter-1 promoted 0.550; iters 2-4 failed vs it
        (0.413/0.488/0.408) -> converged; yardsticks hit RECORD levels (0.61-0.73 vs scaffold).
        **SHIP GATES (fresh seeds): r2 net vs champion 0.6083 +-0.044 train / 0.5250 serve@200 /
        0.5500 serve@512 (grows with depth); vs its hs seed 0.5604 serve.** Winner preserved as
        `coc_run_r2/pv_ship_r2.json`. PER-ITER COST NOTE: r2 spent PCR's savings on 2x games +
        deeper caps (~equal compute/iter, ~3.2-3.5h — and the end-of-harvest straggler tail is
        LONGER under PCR: the last games crawl in tiny GPU batches; a shared work queue across
        threads would fix it).
      - **TIER RESHUFFLE (user-specified):** lobby = **Easy / Hard / Expert** — easy = the server
        MCTS bot at its STRONG config (formerly sold as "hard"; ai.play_turn_plan "hard"), hard =
        the first netval champion net (client WASM, **NEW `coc_pv_model_hard.bin`**), expert = the
        r2 net (`coc_pv_model.bin`). "normal" is LEGACY-only (old saved rooms keep their weaker
        bot; picker dropped). `CLIENT_AI_TIERS=("hard","expert")` both use the client path;
        `ai_search` carries a `model` field; the worker picks its bin from `?model=` on its URL
        (whitelisted). Watchdog fallback for both tiers = server hard bot, unchanged.
      - **Ship hygiene:** bins bit-identical to their jsons (net_export_check json+bin); wasm
        rebuilt (+simd128) carrying the surplus-discard fix — Node smoke on BOTH bins, 3.2-3.4k
        sims/s single-thread (baseline 1,420 — no dot-chain regression); 307 CoC tests; npm smoke
        CLS 0. Rollback = revert `1d93cdd`+`5ec78cf` (the old expert net lives on as the hard bin).
    - **SURPLUS-DISCARD search fix (`306517c`) — from a USER OBSERVATION (do not regress).** The
      search-legality prune dropped ALL discards ("never discard a stored tile"), so the bot could
      never discard — with storage full of unplaceable tiles it was LOCKED OUT of hex takes/black
      buys/m6 for the rest of the game. Now a SURPLUS tile (its color has more stored copies than
      the board has empty spaces of that color left — fixed color capacity only, so provably dead
      under every future) MAY be discarded; live-tile discards stay pruned; engine rules + parity
      surface untouched. Weakly dominant (discards are free, opponent-independent, board never
      grows). Mirror sanity exactly 0.5000. **Side effect: self-play now EXPERIENCES dead-tile
      discards, creating the cost signal the over-TAKING problem needs.** The take-side prune
      (don't take tiles you can't fit) is PARKED — denial takes can be correct (user call);
      revisit with evidence.
    - **Browser sims/s (`667b117`): worker pool now min(cores-2, 8) on >4-core machines (~2x
      sims/decision on desktops; small devices keep min(cores,4)). MULTI-TREE BATCHED wasm search
      = MEASURED NEGATIVE (do not relitigate): 874 vs 2,852 sims/s single-tree, flat across
      K=8/16 — the batched forward is a memory-BANDWIDTH optimization (native is load-bound with
      16 wide registers) but v128 is 4-lane FMA-less COMPUTE-bound and the 4-input block spills.**
      `coc_search_timed_multi` stays in the wasm as tooling (feature-detected in the worker,
      never routed); a relaxed-SIMD int8 build is the only thing that would change the economics.
      Remaining browser levers: the 900ms budget (user UX call) and per-move tree reuse across
      micro-decisions (~1.3x, unbuilt).
    - **P4b ATTENTION campaign (STARTED 2026-07-09; commits `557ecc1`, `02b3bda`, `e51a6c4`,
      `2933e6c`) — the architecture bet after the recipe axis was wrung out.** State + durable
      facts:
      - **Throughput gate PASSED — shape locked T=32 tokens x 28 feats, D=48, 4 heads, FF=96,
        L=2, trunk 128.** Native 1,482 / wasm 917 evals/s single-thread → ~3.2k sims/decision on
        8 workers (~1.6k on a 4-core visitor). T=44/D=64+ FAILS (467 native). The bench
        calibration row reproduces Spender's documented 2,041 evals/s within 3% — after
        replacing the naive serial dot with valuenet's chunked kernel (the round-1 lesson
        re-bit: the first bench read 3-4x slow). **The explicit bet: per-sim quality must beat
        a ~7x sims handicap vs the MLP's ~20k/decision — the final arbiter is an
        equal-WALL-CLOCK gate, never equal-sims.**
      - **`src/attn.rs`** = runtime-parameterized forward (adapted from spender-core's proven
        attn.rs): embed → Lx[key-masked MHA + FFN, residual + no-affine LayerNorm] → masked
        mean-pool + state-embed → trunk → value(tanh) + policy. **Policy = 80 GLOBAL logits
        scattered to action ids + token-TIED logits** (depot tokens 1:1 with TAKE_HEX, black →
        BUY_BLACK, my-storage → DISCARD + PLACE_SLOT — CoC's action space token-aligns BETTER
        than Spender's); masked tokens stay -1e9 (their tied actions are illegal whenever the
        token is empty, so priors never read them). `AttnNet: PvEval` (forward_raw splits the
        flat row; encode_state = the token encoder) → gates/harvests/netval/self-play all work
        UNCHANGED.
      - **`src/tokfeats.rs` = the FROZEN input schema (code-as-spec): 32x28 tokens + 32 mask +
        96 state = 1024 flat f32** (`Enc::Tokens`; in_dim 1024 discriminates in the seam).
        Tokens: 12 depot-hex + 4 black + 3+3 storage (carries the SURPLUS/dead flag) + top-5
        regions per player (**value-at-stake salience with deterministic tie-break lives in the
        RUST encoder** so training rows and serving can never disagree). Tile tokens reuse the
        FR2 `tile_time_value`/`endgame_mult` helpers — washed as flat-MLP inputs, but tokens
        are where attention can cross-reference them. State: dice/track/resources/goods/phase/
        round/bonus/monastery aggregates + pending/micro onehots (leaf evals happen mid-chain).
      - **Torch twin `tools/attn_net.py` — PARITY PASS 5.4e-7 value / 2.6e-6 logits, masked
        slots exact** (`attn_export_check` bin; non-negotiable before any trained json is
        trusted). export_json/import_json/write_check; identity normalization everywhere
        (tokfeats is bounded by construction — NO mu/sd in this stack).
      - **Plumbing:** `PvEval` gained **`in_dim()`**; gate_coc + harvest_boot load MLP OR
        attention jsons by CONTENT detection (`"emb_w"` = attention; netval8 stays MLP-only,
        asserted); an attention model in harvest_boot auto-selects Enc::Tokens for logging via
        in_dim (self-play logs token rows with zero extra flags); harvest `logenc` arg accepts
        `tok`; gpu_server.py grew an attention branch (attn_net.import_json + forward_flat) so
        attention SELF-PLAY runs the same sidecar protocol. `tools/train_attn.py` = streaming
        token-row trainer (SHAPE_A=0.3 ⊕ BETA=0.3 blend — the proven fresh-retrain target;
        PCR-safe CE normalization; game-split holdout; exports json + parity .check per best).
      - **DISTILL LINE (2026-07-09/10): harvested 5000g/1.21M token rows @1200 sims → trained
        (AUC 0.838 / top1 0.448) → gate 0.2917 vs the r2 champion → 8 MORE warm epochs @lr 5e-4
        (top1 → 0.4646, decelerating — NOT epoch-starved) → re-gate 0.4458.** The +15pp from
        extended training dwarfs what +1.7pp top1 implied — **val top1/AUC are weak proxies; the
        VALUE-head calibration is what the netval leaf consumes; always re-GATE after more
        training.** Starts above FR2's 0.425. `attn_distill2.json` = the loop seed.
      - **SELF-PLAY LOOP (`tools/loop_coc_attn.sh`, RUN=coc_run_attn, ITERS=8, 2500g@300 sims,
        promote ≥0.52, FIXED r2-champ yardstick @200 each iter) — RUN COMPLETE (2026-07-11).**
        Iter 0 PROMOTED 0.5750 (first self-play iter beats the distill seed +7.5pp); its probe
        netval-vs-hybrid = **0.5500 — the attention VALUE head beats the heuristic leaf at iter
        0** (took the MLP line a whole campaign). Iter 1 kept (0.5042), iter 2 kept (0.4708).
      - **ITER-3 CRATER — the ANCHOR-CLIFF lesson (fixed in `1168e9c`; DO NOT return to a hard
        anchor cliff).** The first fully-anchor-free train (the designed ANCHOR_ITERS=3 drop)
        collapsed BOTH heads onto the self-play distribution: gate **0.2667 (margin −25)**,
        yardstick 0.4333→**0.2083**, probe 0.55→0.46 — while **val AUC/top1 hit record HIGHS
        (0.8377/0.6106): the val split shares the collapsed distribution, so train metrics are
        structurally BLIND to this failure.** Data + harness exonerated (asp_3 row stats ==
        asp_2; parity probes green). The MLP nv loop survived this same cliff; the
        higher-capacity attention net does not. **Fix: post-anchor iters keep a ~22%-of-mix
        anchor TAIL (attn_boot.t[0-2] — champion-quality 1200-sims rows) + lr halved to 5e-4.**
        Validated immediately: iter 4 gated 0.5250 → PROMOTED (first since iter 0); iters 5-7
        back in the normal band (0.3958/0.4750/0.4917, kept).
      - **RUN VERDICT (iters 0-7): the value head improves but the PACKAGE is FLAT.** Probe
        (netval-vs-hybrid, same net) climbed 0.5500 (it0) → **0.5917 (it6) — the largest
        value-head-over-heuristic edge measured in the whole CoC campaign.** But the yardstick
        was FLAT across all 8 healthy points: 0.4458 → 0.4417 → 0.4667 → 0.4333 → [crater
        excluded] → 0.4417 → 0.4250 → 0.4250 → 0.4667 (±0.089 each; no slope — the policy
        head / whole package is the bottleneck at 300-sims self-play targets).
        **EQUAL-WALL-CLOCK ship gate (the arbiter, 500ms/decision both sides, CPU f32, n=120):
        attn_best:netval@20@1.5 vs r2-champ:netval@30@1.0 = 0.3083 ±0.083 (margin −12)** —
        the equal-sims 0.4417 minus the predicted 12-16pp sims handicap lands EXACTLY on the
        measurement, empirically confirming the two-gate model (ship bar ≈ 0.63-0.65
        equal-sims). Gap to ship: ~20pp equal-sims with zero slope after 8 iters. Escalation
        options if resumed: self-play sims 300→1200 + PCR (the levers that built r2 itself;
        ~2.5-3h/iter with the GPU sidecar), int8-ATTENTION wasm kernel (halves the serving
        handicap → bar ~0.57). Crater net preserved: `attn_cand_3_crater.json`.
    - **SIMS-SATURATION LADDER (2026-07-10, user hypothesis CONFIRMED — do not relitigate): CoC's
      knee is ~4-8k sims vs Spender's ~1.2k.** Champion self-gates at serving config (30/1.0),
      CRN adjacent doublings: 512v1024 **0.5417**, 1024v2048 **0.5833**, 2048v4096 **0.5667**,
      4096v8192 **0.5000** (knee). Mechanism: multiplicative micro-decision turn chains + dice
      chance every round + delayed payoffs. Consequences: the browser Expert sat BELOW the knee
      (→ the serving push below); the **attention wall-clock ship bar ≈ 0.65 equal-sims vs the
      champion** (~7× eval cost ≈ 2.5-3 doublings ≈ 12-16pp on this curve). Spender transfer
      DECLINED by user (its serving is ~16× past its knee; an N-specific ladder was offered).
      Tool: `scratchpad simgate_ladder` pattern — early-exit rung chain, results in
      `coc_run_simgate/ladder_log.txt`.
    - **SERVING SHIPPED (`ce747ca` + `5ecd735`, live on Pages/Render):**
      (a) **Per-decision TREE REUSE** — wasm `TreeCache` (thread-local, keyed state-hash + mode +
      prefix): a LONGER prefix re-roots through applied actions (`mcts::advance_root_child` =
      arena `nodes.swap(0, child)` + `set_root_state`; orphans bounded per move; micro actions
      within a chain are deterministic so replay==stepping); an EQUAL prefix CONTINUES the tree.
      **Returned visits are CUMULATIVE per worker under reuse — the JSX uses the LATEST response,
      never sums across chunks.** (b) **Adaptive Expert budget**: `_EXPERT_BUDGET_MS` 900→1500
      TOTAL; the JSX searches in ~500ms slices (continuation = same prefix) and stops early when
      the summed visit lead > achievable-remaining-sims (uncatchable) — easy decisions ~500ms,
      contested get 1.5s. (c) **int8+simd128 wasm forward (+24%)**: `qdot` gained a wasm arm via
      `i32x4_dot_i16x8` (v128 lacks f32 FMA but HAS integer dot — the one kernel change that
      pays); quantized at `coc_init_model`; wasm "netval" now serves int8, **"netvalf32" = the
      A/B + rollback mode**; strength-neutrality transfers from the native int8 gate
      (deterministic integer math). Node A/B: 3,514 vs 2,825 sims/s.
    - **SIDECAR PERF (torch twin serving; `d603891` + `4d3128a`): 10.5k → ~150k evals/s.**
      (1) The attention forward was KERNEL-LAUNCH-BOUND (python tied-scatter loop ≈38 launches +
      manual attention ≈140/req → 11.5ms per 121-row request): vectorized the scatter (index
      tensors as **non-persistent module buffers** — CPU-index H2D copies are both slow AND
      ILLEGAL inside CUDA-graph capture) + SDPA → 70k (6.7×), bit-vs-.check 0.00e0. (2)
      **CUDA-graph runner** (`GraphRunner`, static padded buffers, lock-serialized replays;
      eager fallback + `COC_GPU_GRAPH=0`) → 146k @8 clients (~2.1×); replays are the captured
      kernels = eager-exact. **(3) THE PAD MUST MATCH THE REQUEST SIZE (`COC_GPU_PAD` =
      2×GPU_BATCH)**: a 256-pad graph on 128-row requests pays the full replay → capped 65k with
      clients starved at 27% CPU. **(4) K=128 thrashes the CLIENT CPU cache even at 300 sims**
      (40-48k evals/s, CPU 91%/GPU 41%) — the K warning isn't just RAM; **64 is the sweet spot**.
      (`torch.compile` unusable — inductor needs Triton, Linux-only; manual graph capture is the
      Windows path.)
    - **GPU GATES + WALL-CLOCK GATES (`5fa8b90`):** gate_coc spec `path:netvalgpu[@S@C]` routes a
      netval player's forward through a sidecar — addr per SIDE via `COC_GPU_ADDR_A/_B` (TWO
      servers when A≠B models), per-side startup parity probe vs the local json. **GPU-vs-CPU
      same-net CRN mirror = 0.5000 with margin +0.0 — identical decisions every game**, so the
      yardstick trend is comparable across the switch; ship gates stay CPU f32 by discipline.
      Sims args also accept **"1500ms" = per-DECISION wall-clock budgets** (sequential path only)
      — **the equal-TIME harness for the attention ship decision** (at equal ms the faster net
      earns its sims advantage naturally; native cost ratios ≈ wasm ratios). Loop gates run GPU
      (cand 9913 / best 9914, threads 4 batch 24, pads 48); g2 probe every 3rd iter.
    - **TRAINER PARSE (do not relitigate the numpy paths): np.fromstring(sep) AND np.loadtxt both
      ~0.55µs/field — same as split+array; NO fast numpy text path.** pyarrow verified BIT-exact
      (0 mismatches, margin-scale bit-equal, same row order) and multithreaded — **but two
      cublas-backward crashes with arrow in-process → OPT-IN via `COC_ARROW=1`** (attribution
      unresolved: arrow readahead RAM vs the triple-race VRAM contention below; a clean
      arrow-then-backward mini-repro PASSES). Trainer runs the python loader (~40-min trains)
      with **CUDA_LAUNCH_BLOCKING=1 + retry-once armor** (async CUDA errors misattribute to later
      ops — sync mode captures the true op if it recurs) + **atomic exports** (tmp+rename).
    - **PER-SIM CPU PROFILE (bench_coc arms, do not re-derive): NO dominant component.** tokfeats
      encode **5.5µs** (~2× v1's 2.6µs — NOT first-order), determinize **1.9µs**, rollout ~6µs,
      engine ~0.56µs/micro-move. Encoder-caching and sort-hoisting levers are DEAD; remaining
      offline throughput levers = straggler-tail work queue (10-20%), cloud burst (~3×), PCR.
      Iterations now ~35-50 min (was ~2.5h).
    - **TRIPLE-RACE POSTMORTEM (2026-07-10) + LOOP HARDENING (`f7ed70d`) — DO NOT regress.** Three
      loop instances raced (relaunch-after-crash without verifying death, twice): doubled log
      lines, gate-port fights (a blank yardstick line — recovered manually: iter-1 = 0.4667),
      and plausibly the cublas crashes (two trainers on 6GB VRAM). A watcher also matched a
      STALE traceback in the log tail → a false "crash #3" → a wrong "pyarrow exonerated" call
      (corrected). Hardening now in the loop script: **singleton lock** (mkdir-atomic + live-pid;
      refuses double launch), **trap-EXIT cleanup** of registered child servers (crash exits),
      **launch pre-flight** (straggler harvest_boot / bound ports → refuse loudly; covers HARD
      kills, which don't cascade on Windows), **gate stderr → per-iter `gates_err_$k.log`** with
      empty-result guards (g1 fatal, yardstick loud warning). Watcher discipline: match only
      content AFTER an armed byte offset. (Curio from forensics: iter-0's net emits ~1e8 logits
      on off-manifold random inputs while fully sane on-manifold — Adam with no weight decay
      leaves unconstrained directions; harmless so far, worth remembering.)
    - The escalate-or-fold decision RESOLVED 2026-07-13: user chose ESCALATE — see the
      "Session (2026-07-11..13) — aux-head arc" entry below (the escalation runs 1200-sims PCR
      self-play + the vs-champion league + the aux gradient, three levers the folded run never
      had). The human playtest of the NEW ladder (Expert = r2 net at ~3× the sims of the last
      playtested Expert) is STILL outstanding.

### Session (2026-07-11..13) — aux-head arc: the ONE confirmed training-signal lever; distill ceiling; goal = 0.60-vs-champion at equal sims (commit `e39c934` + follow-ups)
The post-r2 strength campaign. Standing GOAL (user, revised down from 0.67): a SHIPPABLE bot that
beats the r2 champion **≥0.60 at EQUAL sims**. Durable facts, verdicts, and infra — all gates are
n=240 vs `coc_run_r2/pv_ship_r2.json` at 200v200 unless noted:
- **AUX SCORE-DECOMPOSITION HEADS (KataGo-style) = the one causally-confirmed training-signal gain.**
  `engine.rs` gained a **shadow VP ledger** (`region_vp`/`color_vp`/`livestock_vp` on PlayerState —
  pure telemetry, OUTSIDE `proj.rs`'s canonical projection, parity suite untouched); `harvest_boot`
  writes **14 terminal score-decomposition aux columns** per row (mover+opponent: region/color/
  livestock VP, goods sold, mines, silver, endgame-monastery — `aux_targets()`); `train_pv`/`pv_net`
  (and later `train_attn`/`attn_net`) gained `--aux-dim/--aux-weight`: z-scored aux MSE on a
  trunk-shared head that is **EXCLUDED from export** (json stays shape-identical → ZERO Rust/wasm
  change; the head re-inits on warm starts and reconverges in a fraction of an epoch). Paired
  experiment (same corpus/seed/init, only the gradient differs — control = `--aux-weight 0`, NOT
  `--aux-dim 0`, which would MIS-PARSE the new CSVs): control 0.3667 vs champ, aux 0.4625, **DIRECT
  aux-vs-control 0.5750 ±0.063** (+9.6pp on the champ gates). **Aux-weight curve is an inverted-U
  peaking at 0.3** (0.15→0.4250, 0.3→0.4792, 0.6→0.4208, 10k corpus). A league-mix arm gated
  IDENTICAL to plain aux → the aux gradient extracts the staging economics from ordinary self-play.
- **THE DISTILL CEILING (structural — do not relitigate): every distill from the champion caps
  ~0.48-0.50.** Student≤teacher: the 6000-sim search amplification in the corpus is eaten by distill
  fidelity loss (pv_big's 0.4958 tie = the ceiling, not a near-miss). Measured exhaustively: corpus
  doubling 5k→10k = +1.7pp (wash); extended training (warm +4ep @5e-4) = +0.4-5.4pp (best net:
  `pv_10k_best_ext.json` **0.4833**, margin +0.5); **capacity×aux INTERFERE** (big-trunk 1024,512 +
  aux = 0.3917, worse than either alone). ALSO EXPOSED: the 07-11 "capacity +12.9pp" was
  CORPUS-CONFOUNDED (pv_big trained on cap+league corpus, the controls on the aux corpus — the only
  controlled lever ever measured is the aux gradient).
- **CONSOLIDATION IS FLAT ON THE AUX LINE at every config (the past-champion mechanism is broken
  here):** 300-sims, 1200-sims+PCR, and champion-warm loops all failed. Champion-warm actively
  degrades (0.4958→0.4250 — a converged net RESISTS a fresh-head gradient; own-basin only).
  Recurring signature: internal cand-vs-best gates rise while the champion yardstick sinks
  (self-play basin divergence — the Spender league lesson replayed). **The vs-CHAMPION league FIXES
  the divergence but not growth**: yardsticks 0.4917/0.4167/0.4833/0.4750 (stable around the seed's
  0.4708) vs prior monotonic sinks. Note ALL champion-line loops (nv/hs/r2) ENDED in this same flat
  state — the recipe family is at its plateau; approaching it from below doesn't reopen it.
- **STAGER: dead as a ship lever.** Beats champ 0.58 at loop config (300 sims) but is a LOW-SIMS
  phenomenon: equal-sims @2000v2000 = 0.4875 (w0.3) / 0.5000 (w0.6). The stager-teacher corpus idea
  died with it (a 2000-cap stager teacher ≈ plain champion; the 6000-cap aux corpus is strictly
  better). UNEQUAL-sims demo (the original /goal form): champ+stager@0.3 @3200 sims vs expert@200 =
  **0.7250/0.6625** (fresh seeds) — a compute-edge bot, not shippable; re-confirms the sims ladder.
- **HARVEST/GATE INFRA (permanent, commit `e39c934`):** `harvest_boot` — sequential-path **PCR**
  (`PERMILLE@CHEAP` arg, must start with a digit — `vs@` specs also contain '@'); **shared work
  queue** (global-index game seeds + per-game rngs → BIT-identical games under any scheduling; kills
  the straggler tail; the sequential path's temp-sampling moved to a per-game rng); **`stagerboth@W`**
  (mirror stager teacher); **`vs@<model.json>` OPPONENT LEAGUE** (seat g%2 = training net, ONLY its
  rows recorded — learn to BEAT the target, not imitate its cheap-sims policy; opponent plays greedy).
  `gate_coc` — **`stop@BAR` sequential early-stop** for DECISION gates (z=2.5 conservative bound,
  80-game floor, exact-n reporting; measurement gates/yardsticks must NOT use it — optional stopping
  biases estimates). Sidecar launches carry a **dev=cpu FATAL guard** (a transient CUDA error once
  silently started a 3× slower CPU sidecar). **GATE-SERVER PORT-REUSE LESSON (cost 3 gates): never
  reuse a port across model swaps in one script** — Windows double-binds, the OLD server keeps
  answering, and gate_coc's per-side parity probe panics (correctly). One port per server + reap
  between swaps.
- **OPS:** disk hit 100% mid-train (retry armor + loop both died cleanly; resume markers held) →
  `az_run` purged 92GB→356MB (CSVs/npz deleted, ALL weight jsons/pools kept — every Spender line
  there is a closed verdict) + `coc_run_attn` CSVs (7.4GB, folded run, regenerable). Trainer val
  metrics were AGAIN near-blind to gate differences (ties on AUC/top1 across arms that gate 6pp
  apart) — gates are the only arbiter. A `Start-Process`-detached chain once died before its first
  log write (unreproduced; the rerun as a harness-tracked task worked) — prefer harness-visible
  launches for NEW chains, detach only proven-stable ones.
- **ATTENTION ESCALATION (RUNNING as of 2026-07-13, user-approved):** the P4b fold is reopened with
  the three levers that run never had — 1200-sims PCR self-play targets, the vs-champion league, and
  the aux gradient (`attn_net.py`/`train_attn.py` extended: `_backbone`/`_heads` refactor +
  `forward_with_aux`, aux head excluded from export, **parity re-verified 8.9e-7** post-refactor;
  `import_json(aux_dim=)`). `tools/attn2_chain.sh` (anchor harvest: 1500g attn_best mirror @1200-PCR
  → t[0-1] = the anchor tail, P4b anchor-cliff discipline) → `tools/loop_coc_attn2.sh` (6 iters,
  RUN=coc_run_attn2, gates via `attn_export_check`). Baseline to beat: the folded line's FLAT ~0.44
  yardstick; the goal path needs ~0.50+ and climbing. VERDICT PENDING — if flat again, the
  architecture bet is closed at both sims regimes.

### Session (2026-07-13..14) — attention escalation FOLDED, sims-warm + cold-distill + denial all ≤ r2: the SELF-PLAY CEILING (goal 0.60-vs-champion UNMET; awaiting user fork)
The escalation + the two follow-on levers all landed at-or-below the champion. Durable, do-not-relitigate:
- **ATTENTION ESCALATION (coc_run_attn2) — anchor-cliff CRATER, diagnosed + folded.** iter-0 gate
  0.2914 / yardstick 0.3417 (margin −26) with HEALTHY val metrics (AUC 0.83, top1 0.57). Forensics
  RULED OUT: aux (an `--aux-weight 0` control cratered IDENTICALLY 0.3371 → aux exonerated), corpus/
  parse/targets (audited field-by-field clean — PCR fractions 25%/100%, root-value sign-agree ~0.75,
  953-col layout), and epoch calibration (6-epoch trajectory gates flat 0.29-0.33). **ROOT CAUSE = the
  P4b anchor cliff, reintroduced by my own error:** the disk-cleanup deleted the folded run's champion
  anchor CSVs (regenerable — the deletion was safe, every NET was kept), and I regenerated `attn2_boot`
  as the SEED's OWN mirror self-play = same distribution as the corpus = functionally anchor-FREE → the
  high-capacity attention net collapsed onto its own manifold. **Fix = anchor on CHAMPION (r2 @1200)
  cross-distribution rows (`attn2_champ`): gate 0.29→0.377 vs seed, yardstick 0.34→0.433 (folded ~0.44
  baseline RESTORED).** Relaunched with the champion anchor → iter-0 cand landed 0.433 (= folded
  baseline, a hair BELOW seed = warm-from-converged degradation). VERDICT: the escalated levers do NOT
  lift attention above the folded ~0.44; folded. **Prior experiments UNAFFECTED — verified: the folded
  run used the CORRECT champion anchor (its loop header documents `attn_boot` as "champion-quality
  teacher rows"; its iters 0-2 gated 0.47-0.575 without cratering; the crater was ONLY the deliberate
  anchor-FREE iter 3), and the MLP lines are cliff-immune.** Tooling: `train_attn.py --snap-prefix`
  (per-epoch export for gating the calibration trajectory), `loop_coc_attn2.sh` anchor patched to
  `attn2_champ`, forensic chains `ctl_aux0/epoch_traj/attn2_fix` (commits `95e464b` + `19ec0bc`).
- **RUNG-3 high-sims warm continuation (`loop_coc_hs2.sh`, coc_run_hs2) — PARITY, sims-warm lever
  TAPPED.** The clean ladder next rung: seed r2, SIMS=**4000** (PCR 250@1200, toward the 4-8k knee),
  aux + vs-champion league + `aux_boot` (6000-sim champ) anchor, GPU sidecar. 3 iters pooled two-seed:
  **0.483 → 0.500 → 0.508 — upward but DECELERATING (+1.7pp, +0.8pp), asymptoting at parity, never
  crossing the 0.52 promote bar** (each gate ±0.06; the yardstick UNDERCUT the gate both iters:
  it1 .508/.492, it2 .517/.500). STOPPED (resumable, progress=3). **Warm-continuing r2 at 4000 sims
  gets a net to champion-LEVEL and plateaus — it does not climb toward 0.60.**
- **FRESH cold-init train (`fresh_bootstrap.sh`) — 0.3958 vs champion, CONVERGED (not under-trained;
  val AUC plateaued 0.805 by ep3, declining by ep6).** Same 4000-sim corpus, cold init (no `--warm`,
  8 ep, aux). CONFIRMS the distill ceiling definitively: **training on champion self-play caps at ≤
  champion — WARM inherits r2's weights → parity; COLD learns only the data → BELOW (distill loss).**
- **DENIAL — NOT the lever (do not relitigate; bot-vs-bot, no user games).** `src/bin/denial_probe.rs`
  (built, smoke-verified; one bug fixed — depots are COMPACT arrays, deny by remove-and-shift not
  zero-in-place). Regret oracle = double shallow-search of the opponent's turn (END_TURN hands them the
  board with their KNOWN dice — `_begin_round` rolls everyone at once, so denial is PERFECT-INFO),
  toggling the tile. 60-game run: champion take-rate **SCALES with regret (0.13→0.28→0.46)** = it
  already values regret-denial (a blind spot would be flat); and high-regret spots are **RARE**
  (~0.33/game, ~2% of denial opportunities). Perfect-info ⇒ the search finds it; no league. The user's
  regret model (denial value = opponent's best-response DROP, highest when they're dice-constrained) is
  CORRECT as a tactic — the champion just isn't missing it. (Also corrected mid-investigation: first-
  player denial priority is the dynamic TURN-TRACK order, not game-start seat — a game-level split can't
  see it; and 22 completed games can't pin a win rate. USER DIRECTIVE: **do NOT analyze the user's CoC
  games** — all evaluation is bot-vs-bot.)
- **THE STRUCTURAL VERDICT (the point of the whole arc): r2 sits at CoC's SELF-PLAY CEILING.** Every
  training method that learns from champion self-play caps at ≤ r2 (warm→parity, cold→below, distill/
  consolidation/attention/capacity/stager all documented ≤ r2). To EXCEED r2 you need targets STRONGER
  than r2, whose only source is deeper search — but the sims ladder proved CoC's search SATURATES
  ~4-8k, and r2 trained near there. So self-play at any achievable sims can't generate better-than-r2
  data to bootstrap from. **0.60-vs-r2 at equal sims is NOT reachable by more of the same recipe.** The
  one remaining path WITH A MECHANISM = a FRESH higher-sim LADDER from a weaker seed (nv→hs→r2 re-run
  with 4000-sim self-play throughout, so each rung plays at ~4000-sim-saturation ≈ 0.57 over r2's
  2000-sim training level — NOT continuing r2, which is rung-3's capped basin). Odds moderate-LOW (cold
  0.40 + rung-3 parity both warn the practical ceiling ≈ r2), cost = days. **Fork put to the user
  2026-07-14; awaiting the call (fresh ladder vs grind rung-3 to a marginal ~0.52 vs reconsider a
  dropped constraint). Champion r2 stays deployed; nothing shipped this arc.**

### Session (2026-07-14) — TACTICAL BLIND-SPOT investigation: the user's hypotheses tested bot-vs-bot; ALL FOUR refuted/wash (do not relitigate)
After the self-play ceiling verdict, the user (a strong CoC player) proposed the plateau is a
VALUE-HEAD BLIND-SPOT problem — self-play never learns to value tactics the shared net never plays,
so r2 could be below the GAME ceiling for a fixable reason. A genuinely new lever if true (inject the
missing experience). Tested each specific claim bot-vs-bot (NO user games — user directive; all via
new probe/arena bins gating vs `pv_ship_r2.json`). Every one came back the bot ALREADY handles it —
the same lesson as Spender ("a strong search prices the tactics a strong human describes"):
- **AUDIT first (tile_audit.rs, pv 100g + DEPLOYED-netval 80g):** the champion is NOT ignoring
  anything. Monastery-6 acquired **0.62/0.65 of available games** (user thought "never"); goods-VP
  monasteries #15/#25 the MOST-acquired (0.86-0.94); ~4 ships/player/game; ~11 black-depot buys/game;
  banks ~1.7 silver + ~2.8 workers as first player at phase starts (the user's ideal). The
  netval-leaf audit REFUTES a serving-leaf-drag hypothesis (deployed 0.65 ≈ pure-net 0.62). "Never
  buys M6" was a salience/sample gap (M6 in ~29% of games).
- **DENIAL (denial_probe.rs):** regret oracle = double shallow-search of the opponent's turn (their
  dice are PUBLIC — `_begin_round` rolls everyone at once — so denial is PERFECT-INFO) toggling a
  tile. Champion take-rate SCALES with regret (0.13→0.28→0.46) = it already values regret-denial
  (a blind spot would be flat); high-regret spots RARE (~0.33/game). Perfect-info ⇒ the search finds
  it. NOT a lever.
- **M6 "should be 100%" (m6_arena.rs):** value-bias a champion copy toward owning M6 (storage-or-owned,
  so the reward is within the search horizon), gate vs normal, CRN. Uniform bias **0.46**; the user's
  refinement (M6 compounds EARLY → phase-scaled `(5-phase)/5` reward) **0.4625** — every config ≤0.50.
  Driving M6 32%→42% never helped. The champion's ~65% is CORRECT (the 35% skipped aren't worth the
  die/2-workers/space). w6=0 is an exact-0.5000 CRN mirror.
- **FIRST-PLAYER (firstplayer_audit.rs + firstplayer_arena.rs):** (A) correlational — first-in-more-
  phases wins **0.6333, DOSE-DEPENDENT** (margin 1/3/5 → 0.60/0.64/0.69), so the advantage is REAL.
  (B) causal — bias toward turn-track lead: secured MORE first-player (2.50→2.69 phases) but win rate
  **0.5125 (margin −1.5) = WASH.** So the 0.63 was largely REVERSE causation (a winning position
  controls the track); forcing the cause doesn't create wins. Bot already weights first-player right.
- **SHIP-TIMING "hold ships till the last round for next-phase first-player" (ship_timing_arena.rs):**
  placing a ship is the ONLY track-advance (`place_ship_effect`→`advance_track(seat,1)`), so forced the
  biased bot to prune ship-placement in rounds 1-4. Mechanism worked (round-5 ship-advances 0.917) but
  win rate **0.40 (margin −4.9) — HURTS.** Blunt hold-all-ships clogs storage + delays goods/track more
  than the locked first-player is worth. Natural timing was better.
- **VERDICT: no exploitable tactical blind spot found in the four most-promising candidates.** The
  champion's tactical valuations are SOUND; ~50/50 vs the user is genuine strength. HONEST HEDGE (do
  not overstate): these are BLUNT forcings of NUANCED human judgment ("hold all ships" ≠ "hold a ship
  when it matters"), so a subtle micro-edge isn't ruled out — only that there's no big FORCEABLE lever.
  Combined with the self-play ceiling, BOTH angles (how it's trained + what it might misvalue) are now
  exhausted. Reusable tooling (all bot-vs-bot, no user games): the six bins above, each a value-bias-
  or-forced arena vs the champion with a mechanism check + CRN mirror sanity.

### Session (2026-07-12) — CoC game-screen 3-COLUMN REWORK (SHIPPED to prod)
The CoC game screen was rebuilt so the shared board **and both players' duchies are all visible
at once** (3 columns on wide screens), inspired by the physical Castles of Burgundy layout. Built in
worktree `forrestm_projects-cocui` (branch `coc-ui-rework`), staged on `staging`, then merged to `main`.
All frontend (`CastlesOfCrimson.jsx`), no engine/backend change. Durable, non-obvious facts:
- **`.coc-game-cols` = the table**: CSS grid `minmax(360px,9fr) minmax(0,11.5fr) minmax(0,11.5fr)` at
  ≥1280px (board | your duchy | opponent duchy), 2+1 medium, stacked on phones. Grid items STRETCH so
  the three panels share height; the board ring (`.coc-board-hex`) is `flex:1 1 auto` to fill.
- **The View Opponent modal + its reveal choreography are GONE** (the opponent's board is always on
  screen). Opponent moves animate on their board via the EXISTING flyer diff (`popIn` covers the
  starting castle). The old single-board + "View Opponent" peek + `botViewTimer`/`revealHoldRef`
  dance described in earlier sessions no longer applies to the game screen.
- **Top area is 3 rows, no status box.** (1) Title row: `← Menu` (left) · centered "Castles of
  Crimson" · **Abandon** (right, `.coc-top-abandon`). (2) **Bonuses row** (`.coc-bonusbar`, grid
  `1fr auto 1fr`): left group = `BONUSES:` + `PHASE`/`SIZE`/`COLOR` sections (`.coc-bonus-groups`);
  CENTER = the live score (`.coc-vp`, You/Bot); RIGHT spacer (`.coc-bonus-spacer`) holds the **turn
  badge** — "Your turn" / "Bot is playing…" / setup+decision variants, and **"Game over"** when over
  (`over ? gameover : mineActive ? myBadge : oppBadge`). (3) The **board header** row
  (`.coc-board-head` / `.coc-board-status`) REPLACED the "The Board" title: it now carries
  Phase/Round/Goods-left, with the white die on the right. The old `.coc-statusbar` box
  (phase/round/goods/score/turnbadge/abandon) was DELETED — its pieces were redistributed as above.
  (An earlier iteration put the turn badge on the active player's own panel header, next to Discard;
  that was reverted per the user — the badge lives in the bonuses-row spacer, right of the score.)
- **Depots** (`DEPOT_POS`, `[{50,9},{83,30},{83,70},{50,88},{17,70},{17,30}]`): 2/3/5/6 are SIDE
  depots (`coc-depot-side`, tiles stacked VERTICALLY, goods below, anchored to the board's left/right
  EDGES via `coc-anchor-l`/`-r` + `left:0`/`100%` — NOT `left%`); 1/4 are top/bottom
  (`coc-depot-tb`, horizontal tile row, `width:46%`). The pair positions (2/3 at 30/70, 5/6 at 30/70)
  are tuned so each pair sits CLOSE without overlapping near the **zoom boundary (~1600px)** where the
  boxes are tallest — and depot 4 at top:88 so its mini-die clears the central black depot. Turn-order
  track: space NUMBERS and the "furthest right…" caption were removed.
- **Uniform ghost (taken-tile) rim — DO NOT regress to a rectangular inset.** A `::after` with
  `inset:3px` + the SAME hex clip-path leaves a THINNER rim on the slanted edges than the vertical
  sides (a rectangular inset ≠ a perpendicular inset on a non-square hexagon). Fix: fill the tile with
  the color, overlay an inner hex shrunk by a true ~3px PERPENDICULAR offset computed for the 70×81
  tile — `clip-path:polygon(50% 4.3%,95.7% 27.1%,95.7% 72.9%,50% 95.7%,4.3% 72.9%,4.3% 27.1%)` — so the
  gap is a constant-width rim. Correct only because tiles are a FIXED 70×81 (`HEX_W`), only ZOOMED
  (uniform scale preserves the perpendicular width); if the tile aspect ever changes, recompute.
- **Board-column `zoom` (recap — same footgun as the earlier session):** `.coc-col-board .coc-board-hex`
  uses `zoom:.85` at ≥1280px, `zoom:1` at ≥1600px. Percentages inside a zoomed element already resolve
  in zoomed units, so `width:100%` fills correctly — `width:calc(100%/zoom)` DOUBLE-compensates (spills
  the ring past the panel). `getBoundingClientRect()` returns post-zoom (screen) px, so overlap
  measurements are valid in real pixels.
- **Local verify loop (gotchas):** backend `python -m uvicorn app:app --port 8000`; vite MUST be on
  **5173** (`core/config.py` CORS allowlist only lists `localhost:5173`; on 5174 the browser fetch is
  CORS-blocked → the app hangs on the "Waking up the server…" loader). MSYS mangles `VITE_BASE=/` into
  `/Program Files/Git/` → use `MSYS_NO_PATHCONV=1` or just omit it (vite.config defaults base to `/`).
  Playwright drives guest → CoC card → Create → **Easy** (server bot, no wasm) → place starting castle,
  then measures panel/header/depot geometry + screenshots at 1500/1600/1710/1920 (the user runs display
  scaling, so their effective viewport is ~1500–1600 — test there, not just 1920).

---

## Where Wolf? (third game)

`Where Wolf?` is the **third game** — a faithful **One Night Ultimate Werewolf** clone (real-time
social-deduction party game, **3–10 players, one device each**). Built in the `forrestm_projects-wherewolf`
worktree on the **`wherewolf`** branch. Same architecture as CoC: pure `engine.py` + thin FastAPI sub-app
`main.py` (mounted at `/werewolf`) + a self-contained `WhereWolf.jsx`. See memory
[[wherewolf-game-status]] for the live deploy state.

```
games/wherewolf/
  roles.py     # deck data: DECK_COUNTS, TOKEN_LETTERS, TEAMS/team_of, NIGHT_ORDER/STEP_ROLE/
               #   ACTION_STEPS/INFO_STEPS, recommended_deck(n) + validate_deck(deck,n), NARRATION
  engine.py    # PURE rules: new_game(deck=)/apply_move/resolve_votes/player_view/is_over/winner +
               #   the night-action handlers and the multi-death win logic
  main.py      # FastAPI sub-app `werewolf_app`; ROOMS/ROOM_LOCK; WS /werewolf/ws/{room}/{player};
               #   the async NIGHT CONDUCTOR; own `werewolf_games` table
  WhereWolf.jsx  # self-contained React component the shell mounts at screen "werewolf"
  tests/       # pytest, 67 tests (deck validation incl. partial in-progress decks, every night action,
               #   the win-condition matrix, the player_view redaction matrix, multi-deck smoke)
```

### Engine model (the single source of truth)
- **`dealt_role` is the role you PERFORM all night (immutable); `card` is your FINAL role
  (swappable).** Swaps (robber/troublemaker/drunk) only ever move `card`/`center`, never `dealt_role`.
  Whatever card sits in front of you when night ends IS your final role (possibly unknown to you).
  The WIN uses FINAL cards. **Self-target is rejected for robber/seer AND the troublemaker** — the
  troublemaker swaps two OTHER players (it once wrongly allowed itself; a stale test had frozen the bug).
- **`player_view(game, pid)` is the hidden-information boundary** — a per-recipient redaction. A
  client is only ever sent the cards it may see in the current phase/step (everything else is
  literally `None` in the payload, so a snooping client can't read a hidden card). `dealt_role` is
  only ever sent for the recipient's OWN seat. The visibility matrix (do not regress): OVER → all;
  DEALING → own; NIGHT own only for robber (new card) + insomniac (own current card); werewolves see
  each other; **minion sees the wolves but wolves do NOT see the minion (asymmetric)**; masons see
  each other; seer sees the peeked player/center; **drunk sees NOTHING of its own (blind swap)**;
  lone wolf's center peek is private. Tests in `tests/test_view.py` + `test_night.py`.
- JSON-safe + reconnect-safe (RNG persisted in `rng_state` as lists; no sets — `wolf_pids`/`mason_pids`/
  `minion_pids`/`deaths`/`winners` are LISTS). The whole `game` dict is persisted.

### Roles + win logic (official ONUW — DEPLOYED)
All roles **except the Doppelgänger** (deferred — its copy-a-role dual-timing is a separate larger
effort; it stays in the deck data but is excluded from the picker + `validate_deck`). Wake order:
werewolves (lone wolf may peek 1 center card) → minion → masons → seer → robber → troublemaker →
drunk (blind-swaps own card with a center card) → insomniac (views own card). Hunter/tanner/villager
have no night action. Teams: village {villager,seer,robber,troublemaker,drunk,insomniac,mason,hunter},
werewolf {werewolf,minion}, **tanner** (own — wins only by dying).
- **Voting is MULTI-DEATH** (`resolve_votes`): the player(s) with the most votes die; a tie for most
  → ALL tied die; if **nobody gets ≥2 votes, no one dies**. **Hunter:** a dead hunter also kills the
  player they voted for (transitive, cycle-guarded).
- **Win (the load-bearing care points — DO NOT regress):** ≥1 **werewolf card** dies → village wins;
  else werewolf-in-play + none died → wolves win; no werewolf in play → village wins iff nobody died.
  **Killing the MINION is NOT a werewolf death** (most error-prone line). **A tanner death with no
  werewolf death SUPPRESSES the wolf-team win** (only the tanner wins). **Minion** wins with the wolf
  team, AND in a no-werewolf-in-play game (with a minion present) wins if any non-minion dies.
  "Werewolf in play" counts a PLAYER's final card only (center wolves don't count). Produces
  `deaths`/`winners`/`winning_teams`/`headline` (+ legacy `winner`/`revealed_pid`). Matrix in
  `tests/test_win.py`.

### Night conductor (`main.py`) — data-driven, fixed windows (NO Events)
`_run_night` iterates `roles.NIGHT_ORDER` keyed on **deck presence** (`game["deck"]`): every role IN
THE DECK is announced — *even one entirely in the center* — so silence can't leak which roles are
out (the announcer calls every role in the game). Each step is a **FIXED-DURATION window** (action
~15s / info ~6s): `set_step` + narrate + `sleep(window)`; player actions arrive via the normal move
handler during the window (validated against `night_step`) and the actor sees their result for the
remainder. **No early-advance and no per-step `asyncio.Event`** (uniform timing → leak-free; the
v1 Event mechanism was removed). Restart recovery (NIGHT→DAY fast-forward) unchanged.
- **Lone-wolf no-leak (DO NOT regress):** the werewolves step ALWAYS uses the action window and ALWAYS
  narrates the conditional lone-wolf line (*"If you are the only werewolf, you may look at a card in the
  center."*). Earlier it only did so when there was actually ONE wolf — leaking (by timing AND narration)
  that the game had a single werewolf, which is supposed to be secret. Now a 1-wolf and a 2-wolf game
  look/sound identical; the lone wolf just peeks a center card during the window, nobody else does.

### Host role picker — `set_roles` (lobby-only, host-only)
Before dealing, the host picks the deck (a multiset of role names) in the waiting room. WS action
`set_roles {deck}` → **`roles.validate_deck(deck, len(players), partial=True)`** (copy caps
`≤3 villagers / ≤2 werewolves / ≤2 masons / 1 each single` + player range + no doppelganger, but
**NOT** the exact-count check — `partial` skips only that) → stored on `room["deck"]` (persisted) →
broadcast (public — the upcoming token row). **`partial=True` is what lets the host's IN-PROGRESS
selection broadcast live** as they tap +/−; the exact `players+3` count is enforced only at deal
(`_handle_start`, which re-validates fully and silently falls back to `recommended_deck(n)` if the
deck went stale or was never set). Frontend: host gets a +/- picker (live "selected X / need
players+3" counter + Recommended button); **non-hosts see EXACTLY `room.deck`** — no recommended
fallback, so they see nothing until the host picks (not a misleading minimum) and see over-/under-full
selections as-is. The "3-10" player-range message (was "3..10"). Deal & Start is gated on
`deckCount === players+3`. Hovering a role (host rows + non-host chips) shows what it does (`roleDesc`).

### Frontend (`WhereWolf.jsx`) — do not regress
Self-contained component (`{myId, authUser, onExit}`); namespaced localStorage
(`werewolf_roomId`/`werewolf_token_*`/`werewolf_narrate`); WS/HTTP bases derive `/werewolf` from
`VITE_WS_URL`; imports `baseCss`. Circle seating (each client at 6 o'clock); the 3 center cards + the
public token row in the middle; SVG vote-arrows on the day phase (computed from seat angles — unit
viewBox `preserveAspectRatio:none`, no DOM measuring); a 3-min day countdown.
- **Responsive seat/center cards (`cardVars(n, isMobile)` → inline `--pcw/--pch/--pcf`):** seat cards
  scale DOWN as the table fills (76×98 at ≤7 players → 56×76 at 10) so up to 10 still ring the circle;
  a separate smaller mobile tier. **Long role names wrap on the cards** (`cardLabel`): the 12-char names
  (Troublemaker/Doppelganger) take a HARD `<br>` (a soft `<wbr>` is not honored inside a flex item in
  every browser — it overflowed on desktop), the borderline ones a soft `<wbr>` + `overflow-wrap:anywhere`.
- **Mobile layout (`@media(max-width:600px)` + `useIsMobile`) — DO NOT regress:** the table reshapes into
  a TALL ellipse filling the screen (`.ww-table-wrap`/`.ww-table` flex to fill, `aspect-ratio:auto`) so
  **YOU sit at the very bottom and everyone else rings the edges**, cards auto-shrink to fit 10. (Was a
  small centred square that left the bottom of a phone empty and overlapped cards.)
- **Token info / role tooltips:** the in-game token row renders from the public `game.deck` (role keys,
  not just letters) so hover (desktop) / tap (mobile) shows the role + what it does (`roleDesc`) — and the
  shared "T" letter (Tanner vs Troublemaker) is correctly disambiguated.
- **Self-vote → a loop arrow** (`selfLoopPath`) curling back to the voter's own card (red for you, gold
  for others), drawn alongside the straight cross-vote arrows.
- **Narration:** browser `SpeechSynthesis` TTS + an always-on caption banner. Server broadcasts
  `{type:"narrate", text, key}`; the client speaks it. Per-device 🔊/🔇 toggle (default ON for host).
- **Reconnect/rejoin hardening (do not regress):** auto-reconnect when the socket drops while in a
  room (bounded retries) + a manual "⟳ Reconnecting…" button; "Your Games"/Resume rejoin paths;
  leaving keeps you a room member + the resume pointer so "back out and rejoin" works and the host
  stays host; auto-resume/reconnect failures recover **silently** (no "invalid token" flash); a join
  that hits a transient "no such room" retries once. A finished game (`phase==="over"`) **clears the
  resume pointer** so it's gone (not resumable/listed) without kicking anyone off the results screen.
- **CSS gotcha:** the `css` template literal must contain NO backtick (the documented blank-page
  smoke-test footgun, shared with Spender/CoC).

### Deploy — LIVE on production as of 2026-06-21
The game **is launched to prod**: the Where Wolf? home card is `status:"ready"` on `main`, so prod
users can play it (commit `7efcb84`). `app.py` mounts `/werewolf` with the same defensive try/except
as CoC. How it was launched (and the lessons, DO NOT regress):
- **Backend** (`engine.py`/`roles.py`/`main.py`) had already been on **`main`**/prod (dormant — no
  home card) so `/werewolf` served the logic; the staging Cloudflare site (frontend) talked to that
  prod backend, which is why the backend had to ship first (staging shares the prod backend).
- **Launched by a SELECTIVE add, NOT a `staging→main` push.** Brought only the wherewolf FRONTEND
  forward onto `main` (`games/wherewolf/WhereWolf.jsx` + the Spender.jsx card hooks: import / `GAMES`
  entry / `screen==="werewolf"` route). A blind `staging→main` push was **unsafe** because `staging`
  had diverged: it was *behind* `main` on the wherewolf backend (lacked the troublemaker + lone-wolf
  fixes, host-picker backend) so a force-push would have **reverted** them. main's wherewolf backend
  is a strict superset of staging's, and the staging site already ran staging's `WhereWolf.jsx`
  against the prod backend, so the launch pairing was pre-validated. (See the staging-divergence
  warning in "Staging environment" below for the selective-deploy recipe.)
- **Historical note (pre-launch):** the frontend lived staging-only while the card was kept off
  `main`; `staging` gets force-resynced by other frontend work (which once wiped the wherewolf card),
  so the rule was to re-apply onto the current `origin/staging` tip + `npm run smoke` + push.
- **Testing gotcha:** distinct local players need distinct browser storage — two same-browser
  incognito windows SHARE localStorage → same `spender_myId` → they collapse into one identity. Use
  different browsers/profiles/devices.

---

## Books (site feature — not a game)

A standalone site page for ranking favorite books + collecting reading suggestions
from other users. **Deliberately NOT under `games/` or `spender/`** — it lives in
its own top-level package so it's neither a game nor part of Spender.

```
books/
  __init__.py
  api.py            # FastAPI routes + SQLite logic (pure functions + thin handlers)
  Books.jsx         # self-contained React page the shell mounts at screen "books"
  tests/test_books.py   # 14 tests, in-memory DB (no server / no real users.db)
shared/
  theme.js          # baseCss — the site's shared design system (see below)
```

### Backend (`books/api.py`)
- Tables in the **shared `users.db`**: `books` (ranking), `books_meta` (owner claim),
  `book_suggestions` (per-user). Created by `init_books_db` via injected `get_db_conn`.
- Routes: `GET/PUT /books` (public read; owner-only write — full-list replace, blanks
  skipped, rating clamped 1–5, `sort_order` recomputed per-rating from incoming order)
  and `GET/PUT /books/suggestions` (each logged-in user manages their own up to
  `MAX_SUGGESTIONS=10` ranked picks + a why-read-it blurb; the **owner** `GET` also
  returns everyone's, grouped by suggester; 10-cap enforced server-side).
- **Wired into Spender's app**, not its own sub-app: `main.py` does
  `from books.api import setup_books; setup_books(app, get_db_conn, get_user_by_session)`.
  Deps are **injected** so `books` never imports `main` (no cycle). The absolute import
  is safe because `books` is a **sibling top-level package of `games/`** — repo root is
  on `sys.path` wherever `games.spender.app` loads (Procfile `python -m uvicorn`,
  Dockerfile `COPY . /app` + WORKDIR /app, pytest from root).
- Pure functions (`fetch_books`/`replace_books`/`fetch_user_suggestions`/
  `replace_user_suggestions`/`can_user_edit`/`is_owner`) take a sqlite conn → unit-tested
  against `:memory:` with no web server.

### Site-owner identity (reusable, in `main.py`)
- `site_owner_name()` / `is_site_owner(user)` read the **`SITE_OWNER` env var** (a
  *username*; read at call time). This is the **site-wide** owner check — books is the
  first consumer, but it's intended for any future owner/admin feature.
- `SITE_OWNER` **is set on Render** (to the owner's username). `books/api.py` reads the
  same `SITE_OWNER` key. If unset, books falls back to **first-authenticated-saver
  claims ownership** (stored in `books_meta.owner_id`) — convenient for local dev.
  `is_owner` is strict (unclaimed → nobody); `can_user_edit` treats unclaimed as
  editable-by-any-auth-user (so the first save can claim).

### Frontend (`books/Books.jsx`)
- Mounted by the shell (`Spender.jsx`) on `screen === "books"`; reached from a "📚 Books"
  link on the home menu (separate from the games grid). Props `{ authUser, onExit }`.
- Public ranking view (sections per star tier 5→1, ordered within) + owner edit mode
  (reorder within a tier, rating picker, manual add). Suggestions section: owner
  sees all (grouped by suggester); other logged-in users get their own up-to-10 editor;
  logged-out users see a "log in to suggest" prompt.
- **Two-column layout** (`.bk-columns` grid, capped 1160px, top-aligned): bookshelf left,
  suggestions in a 360px right column. Collapses to ONE stacked column below 920px (the
  `.bk-section` top-border separator is restored there). The `>` child combinator scopes
  the column overrides to the top-level `.bk-list`/`.bk-section` (NOT the nested `.bk-list`
  inside the suggestion editor).
- **Reorder UX (don't regress):** each edit row has **▲/▼ buttons** that move a book within
  its star tier (and a suggestion within its flat list), disabled at the tier/list ends —
  these exist because native HTML5 drag-and-drop **doesn't work on touch** and is fiddly on
  desktop. Drag is the secondary path: **only the ⠿ handle is `draggable`** (so the row's
  text inputs stay selectable — making the whole row draggable fought with editing), the row
  is the drop target and highlights (`.bk-dragover`). **`makeDrop` inserts AFTER the target
  when dragging downward** (source index < target), BEFORE when upward — otherwise a downward
  drop re-inserts before the target, which is where the source already was, so nothing
  visibly moved (the original asymmetric "drag up works, drag down doesn't" bug).
- **Open Library** search-to-add (`<BookSearch>`, reused by both editors): keyless,
  CORS-enabled, queried client-side; picking a result auto-fills title/author/cover.
  **The fetch is capped at 12s** (a guard timer aborts the AbortController) — Open Library is
  flaky (observed 7-10s connects) and has no timeout of its own, so a hung request would
  otherwise stick on "Searching…" forever. A real timeout/network failure shows a recoverable
  message; a supersede-abort (newer keystroke) is distinguished so it doesn't flash an error.
- **Covers are cached as inline `data:` URIs** (`inlineCover`, applied to ranking + suggestions
  on **save**): `covers.openlibrary.org` serves through **two 302 redirects** (→ archive.org)
  with only a **3-hour** cache, so covers re-fetch slowly every few hours. CORS is open
  (`ACAO *`), so on save the browser fetches each remote cover once, **downscales** it
  (128×192, JPEG q0.82) via canvas, and stores a self-contained data URI in `cover_url` — it
  then renders instantly from the list payload with no external request. Any fetch/CORS/decode
  failure falls back to keeping the original URL (graceful). **Existing books need one
  Edit→Save to backfill**; new adds bake in on the next save. (Inline data URIs are ideal for a
  shelf of dozens; at hundreds, a cacheable backend image endpoint would scale better.)

### Shared theme (`shared/theme.js`)
- `baseCss` is the **single source of truth** for the site design: Cinzel/Crimson Pro
  font `@import`, `:root` color tokens, base `body`/`.app`, and `.btn`/`.input`
  primitives. Both `Spender.jsx` and `Books.jsx` import it and prepend it to their own
  CSS (`<style>{baseCss + screenCss}</style>`); the `@import` must stay first, so
  baseCss always leads. Extracting it left Spender's rendered CSS byte-identical (the
  primitives just moved out of Spender.jsx into the shared file).

### Deploy / branch notes
- Work lives on the **`feat/books`** branch (off `main`, isolated in worktree
  `forrestm_projects-books`). Pages workflow watches `books/**` + `shared/**`; Render
  watches `books/**`. `COPY . /app` already ships the new top-level dirs.
- **CLAUDE.md is no longer gitignored**

### Persistence — Turso/libSQL (production DB) — SITE-WIDE, not just Books
**The Render free plan has an ephemeral filesystem**: the SQLite `users.db` (which
holds users, games, coc_games, books, book_suggestions) is recreated **empty on
every deploy and every cold-start after the free service idles**. So accounts,
games, AND book rankings did not persist across restarts. Books made this pressing
(its whole point is a persistent ranking), but it affects the whole site.

Fix (now in **`core/db.py`** — extracted out of `games/spender/main.py`):
`get_db_conn()` is a **dual backend** behind a tiny driver-agnostic wrapper:
- **Local sqlite3** (default) — dev + the test suite + the prod *fallback*.
- **Turso / libSQL remote** — used when **`TURSO_DATABASE_URL`** (and
  `TURSO_AUTH_TOKEN`) env vars are set, so data persists off the ephemeral disk.
- `_Conn`/`_Cursor`/`_Row` wrap either driver so rows work by BOTH index (`row[0]`)
  and column name (`row["id"]`) — the existing queries are unchanged. `executemany`
  is implemented as a loop (libsql may lack a native one).
- A **boot-time `_turso_selftest()`** connects + round-trips a row through the
  wrapper; **any failure logs a warning and falls back to local sqlite** (site stays
  up, just non-persistent) — it never crashes boot. Watch the log for
  `Turso/libsql verified` vs `falling back to LOCAL sqlite`.
- `libsql` is in `requirements.txt` but **imported lazily** only when Turso is
  configured. **`libsql` has no wheel for Python 3.14** (local dev) and can't build
  without Rust — but **prod Docker is Python 3.11** (wheels exist), so it's
  install-and-run there. **Consequence: the Turso path cannot be tested locally on
  this machine** — validate it via Render logs + a live login that survives a
  redeploy. The sqlite path (identical wrapper) IS locally tested.
- **Setup the user must do** (one-time): create a free Turso DB + auth token
  (`turso db create` / `turso db tokens create`, or dashboard), then add
  `TURSO_DATABASE_URL` (the `libsql://...turso.io` URL) and `TURSO_AUTH_TOKEN` as
  Render env vars. Until then prod silently uses ephemeral sqlite (zero behavior
  change). `SITE_OWNER` is unaffected (it's env-based, not stored).

---

## WWSD ("What Would Steve Do") — variant-N autoplayer for a FRIEND's external Splendor site

`wwsd/` (top-level package) is a standalone tool that recommends a move for a Splendor position taken
from a **friend's external site** — mattle's "spendee" (`spendee.mattle.online`, a **Meteor** app),
NOT the user's own Spender game. A browser **bookmarklet** on the friend's page reads the live game
state out of the Meteor client cache (`Meteor.connection._mongo_livedata_collections['games'].find()
.fetch()` — a request-free LOCAL read of already-synced Minimongo), POSTs it to a public endpoint,
and renders variant **S**'s move (+ position eval) in an injected overlay panel.

### Deployed as a SECOND Render service (process isolation is the whole point)
- Its own Render web service **`wwsd`** → `https://wwsd.onrender.com`, a **separate process** from
  the game backend `spender-backend`. **Why separate:** `wwsd.analyze` rewrites the shared
  `games.spender.ai.az.engine` deck globals (`COST/PTS/BONUS/NOBLE_REQ/WIN_POINTS`) to the friend's
  deck; the live game backend's own AI (`_az/_h2/_h3_choose_move`) reads those SAME globals inside a
  thread-pool compute that does NOT hold `ROOM_LOCK`, so sharing a process would corrupt live game
  moves. The override runs in `analyze.prepare()` (called at `app.py` startup; lazy in `analyze()`),
  **never at import** — a stray `import wwsd` can't corrupt anything.
- Defined in `render.yaml` as a 2nd `web` service: SAME repo/`Dockerfile` (`COPY . /app` ships
  `wwsd/`), only the **dockerCommand** differs (`uvicorn wwsd.app:app`). Env: `WWSD_SECRET`
  (`sync:false`, set in the dashboard — NOT in the repo), `WWSD_ORIGIN`, `WWSD_TIME`,
  `SPENDER_AZ_MODEL=none` (skip the numpy AZ load — unused here). Created manually in the Render
  dashboard (or via blueprint sync).
- **Variant S is already on `main`** (`vsearch`/`v_state`/`mcts` `leaf_state`/`heuristic3`/
  `valuation3`/`engine`), so wwsd just `import`s the az modules — **no vendoring**. Built in a
  dedicated `forrestm_projects-wwsd` worktree off `origin/main`, pushed to `main` (auto-deploys).

### The deck (`wwsd/wwsd_defs.json`)
The friend's 90-card + 10-noble deck, **extracted from THEIR site's client** (their Meteor module
`games/spendee/imports/api/utils/constants.js`, read via the browser console — no server request).
It's the canonical Splendor deck in the SAME colour order as ours (identity matches **89/90**; our
Spender deck deviates on one card). `analyze.override_engine()` rebuilds the engine's card/noble
tables from THEIRS so S analyses their EXACT game (their card index = our engine card id; 0-39 L1 /
40-69 L2 / 70-89 L3). Validated against a finished-game dump (90-card partition + token conservation
+ noble satisfaction).

### Files + API
- `wwsd/analyze.py` — `analyze(doc, time_limit)` (a dumped `{games:[...]}` doc → engine State →
  variant S → structured dict); `to_state`, `override_engine`/`prepare`, and `_search_with_eval`
  (runs the search, then reads the root value + per-edge Q **without** modifying `vsearch`).
  - **Win-points auto-detect (Classic 15 / Long 21).** `_detect_target(game, data)` reads
    `settings.targetScore` (spendee stores it as a STRING, e.g. `"15"`/`"21"`; falls back to
    `data.targetScore`, then 15) and `analyze` threads it BOTH ways: `set_target(t)` aligns the
    engine GLOBAL `E.WIN_POINTS` (non-S leaves + getattr fallbacks) AND `to_state(data, target)`
    sets the **per-state `s.win_points`** — which is authoritative, since the engine win check
    (`_finish_turn`) and the whole S stack (`v_state._points_term` convex zone, `heuristic3`,
    `valuation3`) read `s.win_points` per-state. **`to_state` MUST set it** or the search
    AttributeErrors mid-rollout (the State is built via `__new__`, so every slot is set by hand).
    21-pt games are analysed correctly (right victory zone), just with the 15-pt `turns_table`
    horizon (best-effort, see Caveats).
- `wwsd/app.py` — FastAPI: `POST /move` (gated by header `X-WWSD-Secret` via `hmac.compare_digest`;
  small self-contained per-IP sliding-window rate limit; CORS pinned to `WWSD_ORIGIN`; honours a
  `?t=<seconds>` think-time override **clamped 1-60s** to stay under Cloudflare's ~100s ceiling),
  `GET /health`, `GET /` (the bookmarklet generator/tester page).
- `wwsd/bookmarklet.py` — the overlay bookmarklet (config vars `SECS`/`SVC`/`KEY` hoisted to the
  FRONT for easy editing) + `build_bookmarklet()` + the `GET /` page (builds the bookmarklet
  CLIENT-side, so the secret never reaches the server).
- `wwsd/tests/test_wwsd.py` — deck-rebuild correctness, `analyze` on real dumps, secret/json guards,
  `?t=` clamp, bookmarklet generation, eval fields (`python -m pytest wwsd/tests -q`).
- **`analyze` response**: `recommendation` + `rec_eval`; `alternatives[]` (pct + text + `eval`);
  `eval` = S's POST-search **position** value (root `sum(W)/sum(N)`, [-1,1] from the side to move);
  `sims`, `budget`, `turn_name`, `target`. Per-move evals are the MCTS **edge Q** (searched → noisy
  at low sims; higher `SECS` steadies them). A static-`v_state`-after-each-move alternative was
  discussed (stable but shallow + needs refill-averaging for buy/reserve) — not implemented.

### Caveats
Render free tier: ~30-50s cold start; slow shared CPU → far FEWER sims than local (~hundreds at a few
seconds vs ~4,600 on a dev box). **Sims, not seconds, is the strength currency** — bump `WWSD_TIME`
or the bookmarklet's `SECS` (`?t=`) to climb toward the local strength (capped by `vsearch`'s
`SERVE_MAX_SIMS`). For full local strength without the wait, a tunnel (Tailscale Funnel / Cloudflare)
or a cheap dedicated-core VPS beats the free tier. `turns_table.json` (H3-vs-H2-measured, 15-pt) feeds
S's leaf eval → 15-pt games exact, 21-pt approximate.

---

### Browser-N userscript — run variant N (`net_attn_3` attention net) in the friend's browser via WASM (LIVE June 2026; CSP confirmed; FULL UI AUTOPLAY working)
**Status:** the advisor overlay AND fully hands-off **UI autoplay** both work on spendee (WASM CSP is
fine). Current userscript **v0.9.21**, which runs **variant N (= the card-set attention net `net_attn_3`,
the strongest AI)** — it calls the same `search_pv_full_timed` WASM entry the website uses (the `searchPV`/
`browser_n` names are legacy from the PV era; the 15-pt branch runs the attention net). The build is `wwsd/build_browser_n.py` (assembles the editable
`browser_n.template.user.js` + inlined WASM → `wwsd/wwsd_browser_n.user.js`, **~2.8MB** self-contained
now that the PV model is embedded); the user installs the assembled file in Tampermonkey and **must
reinstall after each version bump** (the `@version` header is the tell — Tampermonkey doesn't auto-update
a local file). Deploy = commit both files to `main` (push from the `forrestm_projects-wwsd` worktree). The
two big build-it findings — the deck **id-remap** (cost-correctness) and the **canvas synthetic-click
autoplay** (Meteor 403 dead-end) — are documented in the deck section above and the "UI AUTOPLAY" bullet
below; both are leaf-agnostic so they carried over from N to PV unchanged (same engine Dump, same remap,
same flows — only the search/eval *function* changed).
The user's directive: move WWSD's COMPUTE off Render and into the friend's browser (like the main
Spender site's WASM AI), using the strongest variant. This **supersedes the bookmarklet+Render-S path**
— PV > N > S, and a real CPU runs thousands of sims/move vs Render's ~300 (sims-starved 0.1-core). The
advisor overlay (top move + position eval + alternatives) is leaf-agnostic, so it's preserved unchanged.
- **PV (and N) are Rust/WASM-ONLY — there is NO Python PV/N; server-side both fall back to S.** PV is the
  **AlphaZero policy+value net** in main's `spender-core`: a **125-feature `feats::features_az` encoder**
  (separate from N's 101-feat `feats::features`) + the embedded **`src/pv_model.json`** (`PolicyValueNet`,
  value+policy forward). The net supplies BOTH the MCTS **leaf value** AND the **policy prior** (legal-masked
  softmax of the policy logits; H3 fallback at discard/noble). Beats N (0.60–0.67 across 160–800 sims) and
  S (0.758) in paired-CRN eval.
- **Build from `main`, NOT a pinned rust-search commit (CHANGED with the PV switch — do not regress).**
  The build worktree **`forrestm_projects-wwsd-wasm`** (branch `wwsd-wasm`) is now **synced to `origin/main`**
  (was pinned to `rust-search@0bcf0a8` for the N era; old tip saved as tag `wwsd-wasm-prePV-backup`). main's
  `spender-core` already carries PV, so the build worktree just needs to track main. The old 101-feat-net
  hazard (an uncommitted 149-col `feats.rs` on rust-search) no longer applies — main is the source of truth.
- **WASM eval export — 2 ADDITIVE edits, committed to `main` (`550525c`), none touch the webapp's PV/N
  paths:** `vsearch.rs` `root_nw_until_pv()` (PV analog of `root_nw_until_leaf` — net supplies leaf value +
  policy prior, returns root visits + per-edge W) and `wasm.rs` **`search_pv_full_timed(state_json, seat,
  budget_ms, max_sims, seed) -> JSON {visits,value,q}`** (the PV analog of the N-era `search_n_full_timed`,
  which stays for reference). The shipped `search_visits_pv_timed` returns **visits ONLY** (enough to PICK a
  move, no eval); the new full export adds the searched position value (`sum W / sum N`, side-to-move,
  [-1,1]) + per-edge Q (`W[a]/N[a]`, null if unvisited) so the overlay keeps its eval. Built `wasm-pack
  build --release --target no-modules --out-dir pkg-nomod` (defines a global `wasm_bindgen` for inlining;
  the no-modules WASM grew 928KB→2.07MB with the PV model). Toolchain: `cargo`/`wasm-pack` in
  `C:\Users\Forrest\.cargo\bin` (off-PATH; `export PATH=$PATH:/c/Users/Forrest/.cargo/bin`). Smoke-tested
  the no-modules build in **Node** (a small vm harness loads the glue, inits with the `_bg.wasm`
  ArrayBuffer, calls `search_pv_full_timed` on a fresh-game Dump → valid `{visits,value,q}`).
- **Userscript — worktree `forrestm_projects-wwsd` (branch `wwsd-autoplay`):** `wwsd/browser_n.template.user.js`
  (editable LOGIC) + `wwsd/build_browser_n.py` (assembler) → **`wwsd/wwsd_browser_n.user.js`** (~1.28MB,
  **SELF-CONTAINED**: inlines the no-modules glue + the wasm as **base64** → NO hosting/CORS/fetch/Render
  dependency; re-run the assembler after any wasm rebuild). Ports `analyze.to_state` → the `wasm.rs::Dump`
  JSON (`toDump`; card ids/colours are identity; **Node-validated byte-identical** to a hand-built dump)
  and the action index → text/machine move (`describeMove`/`structuredMove`, ports of
  `_describe_move`/`_structured_move`). Tampermonkey **`@grant none`** (runs in PAGE context → the page's
  `Meteor` global is reachable). Loader call: `await wasm_bindgen({module_or_path: base64Bytes})` then
  `wasm_bindgen.search_pv_full_timed(JSON.stringify(dump), seat, THINK_SECS*1000, MAX_SIMS, seedBigInt)`
  (was `search_n_full_timed` in the N era).
  Embeds `BONUS[90]/PTS[90]/NOBLE_PTS[10]` (from `wwsd_defs.json`) to compute the Dump's bonuses+score.
  Engine consts for the Dump: `PLAY=0, WIN_NONE=-1, A_PASS=30, N_ACTIONS=70`.
- **Validated end-to-end in Node** (scratchpad `verify_n.mjs` + `verify_browser.mjs`): `toDump` of the
  real spendee-format LIVE fixture is byte-identical to the known-good dump, and the full path returns a
  sane move + eval (~1,200 sims/s single-threaded; opening favours Take3).
- **Deck remap — friend ids ↔ Spender ids (the load-bearing fix; June 2026).** The WASM embeds OUR
  Spender deck at compile time and CANNOT do the Python WWSD's runtime `override_engine`. **The two decks
  are the same MULTISET but ordered COMPLETELY differently** (NOT "1/90 different" — that earlier note was
  wrong and shipped a real bug: the advisor recommended buying cards the user couldn't afford, because the
  WASM looked up `COST[friendId]` = a totally different card's cost). Fix in `browser_n.template.user.js`:
  `F2S[90]` (friend→Spender id, a verified **exact** 90/90 bijection — friend #3→Spender #36 is exact too,
  post card-36 fix) and `F2S_NOBLE[10]` (nobles are reordered too). `toEngineDump(dump)` remaps **every** card
  id (board/decks/purchased/reserved) + noble id (board nobles + nobles_won) friend→Spender BEFORE the WASM
  call, so the engine's compiled COST/BONUS/PTS describe the SAME physical cards. The **original
  friend-space `dump` is kept for display + execution** — action indices are positional/by-slot so they
  line up across both spaces (a buy of slot s → `dump.board[s]` is the friend id for the label + spendee
  `cardIndex`). Belt-and-suspenders: `actionAffordable(dump,a)` checks the recommendation against the
  friend's TRUE costs (`COST_F[90]` from `wwsd_defs.json`) and **filters out any unaffordable buy** before
  selecting the top move (a safety net for any future deck drift). Validated end-to-end in
  Node against the real WASM: the un-remapped path recommends an unaffordable buy on a crafted position;
  the remapped path + guard never does, and a symmetric opening evaluates ~0.00 (was a false +0.10).
  **Regenerate F2S/F2S_NOBLE/COST_F if either deck changes** (compare `wwsd_defs.json` vs
  `engine._build_tables()` by `(cost,bonus,pts,level)`).
- **Browser CSP** — instantiating WASM needs `script-src 'wasm-unsafe-eval'`; confirmed working on
  spendee in practice (the panel shows "WASM failed (CSP?)" if ever blocked).
- **UI AUTOPLAY — WORKING (canvas synthetic clicks; the Meteor path is DEAD). DO NOT try to revive
  `/gameActions/insert`.** spendee's server **403s ("Access denied")** ANY programmatic Meteor insert
  (Meteor.call, raw `_send`, even stub-bypassed) — confirmed un-bypassable; it's a server-side allow gate.
  So autoplay drives the **real UI** instead: the whole game is ONE `<canvas>` (`div.board > canvas`), and
  the engine **accepts synthetic events** (`isTrusted` is NOT checked — the make-or-break finding). The
  adapter (`browser_n.template.user.js`) dispatches pointer/mouse events at **canvas-fraction coordinates**
  (resize-tolerant; recorded via the panel's **Rec DOM** button which logs each click's `canvasFrac`):
  - `synthClickCanvas(fx,fy)` (full pointer+mouse+click sequence) and `synthHoldCanvas(fx,fy,ms)` (press-
    and-hold, for **Reserve** which is a hold button). All coords live in the `UI` map; timing knobs in
    `CONFIG`: **`SETTLE_MS`** (pause at the START of our turn, after the opponent's move, so the board
    finishes animating before the first click), **`OPEN_MS`** (post-modal-open wait), **`TAKE_OPEN_MS`**
    (the take-gems modal specifically is slow to become interactive — its own longer wait), `STEP_MS`
    (between in-modal clicks), `HOLD_MS` (reserve hold). **Why SETTLE_MS/TAKE_OPEN_MS exist (v0.8.5 fix):**
    playing instantly after the opponent moved sometimes clicked before the UI re-rendered — most visibly
    a take "red green black" landing only the LAST gem because the pick-chips modal wasn't interactive when
    the first clicks fired. Raise `TAKE_OPEN_MS` first if a take still drops gems.
  - Flows (each `ui*` fn): **take** = open select-chips modal → click each gem in-modal → "pick" (+ auto
    **discard** via the gold-topped discard column + "return" if the take overfills 10); **buy board** =
    click card (exact 12-slot `cardFrac` table) → "Buy"; **reserve board/deck** = click card/pile → hold
    "Reserve" (+ auto-discard if the granted gold overfills 10); **buy reserved** = click your reserve pile
    (**seat-aware**: P1 top / P2 bottom) → click the card row in the modal (oldest at top = engine index 0);
    **pass** = Pass → confirm; **noble choice** (2+ eligible after a buy) = click all 3 board noble slots
    (the eligible one claims). Discard choice is a heuristic (drop most-abundant colour, keep gold).
  - `playMove(action, dump)` dispatches N's structured action to the right flow. The autoplay loop adds
    human pacing (2–4s) then **verifies the move committed** (turn advanced / sub-decision arose); if a
    click missed (turn stuck, modal open) it closes the modal and retries ≤2× before asking the user to
    finish that one move manually — so a single misfire never hard-freezes.
  - **GOTCHA — record & play at the SAME window size.** Coords are canvas FRACTIONS; if the game
    pillarboxes, right-edge targets (the **Buy** button) drift when the canvas aspect changes. Recording at
    a 1335px-wide canvas then playing maximized made Buy miss. Play maximized, record maximized.
  - Toggle from the panel: **Autoplay on/off** (default off; turning on plays the current turn
    immediately). `AUTO_PLAY=false` default = advisor-only. `WWSD_N.*` exposes every `ui*`/`synth*` fn for
    console testing.
- **Now-vestigial / superseded:** the `/move` `action` field added to `analyze.py` (`_structured_move`)
  + the FIRST userscript `wwsd/autoplay.user.js` were the OLD Render+S autoplay path; browser-N builds the
  structured move client-side, so both are superseded (harmless, backward-compatible). Once browser-N is
  browser-confirmed → retire the bookmarklet + `autoplay.user.js` + the `/move action` field, and
  optionally decommission the Render service (browser-N/PV needs no backend). **DEPLOYED to main:** the
  userscript+tooling+docs, the N-era `search_n_full_timed`, and (with the PV upgrade) `search_pv_full_timed`
  — each an ADDITIVE commit to main's `spender-core`, applied cleanly. The eval-export source also lives on
  the `wwsd-wasm` build worktree (now synced to main, see the build bullet above).
  **RESOLVED since:** browser-CSP works; autoplay does NOT use Meteor methods at all (server 403s them) —
  it drives the canvas via synthetic clicks (see "UI AUTOPLAY" above). The bookmarklet + `autoplay.user.js`
  + `/move action` field can now be retired, and the Render WWSD service is decommissionable (browser-N
  needs no backend).

---


## `core/` — shared backend platform (DB + auth)

The **top-level `core/` package** holds the cross-cutting backend infrastructure
that every site feature needs. It was **extracted out of `games/spender/main.py`**
(Phase 1 of the architecture cleanup) so features depend on a neutral platform
layer instead of reaching into a game module. **`core` imports nothing from
`games`/`books`** — it is the bottom layer, which is what removed the circular
imports the old arrangement required.

- **`core/db.py`** — the dual **sqlite/Turso** connection: `_Row`/`_Cursor`/`_Conn`
  wrapper, `_turso_selftest`, `get_db_conn`, and **`init_core_schema(conn)`** (creates
  the cross-cutting `users` / `admins` / `reconnect_tokens` tables). `DB_PATH`
  defaults to the legacy `games/spender/users.db` for backward-compat (override with
  `SITE_DB_PATH`); in prod Turso is used and this path is only the fallback.
- **`core/auth.py`** — `gen_token` (**CSPRNG via `secrets`** — see Security hardening),
  `hash_password`/`verify_password` (PBKDF2 + legacy), `create_user`, `authenticate_user`,
  `get_user_by_session`, `validate_credentials` (registration input rules), the SITE_OWNER/admin
  identity helpers (`site_owner_name`, `grant_admin`, `is_admin_id`, `is_site_owner`), and the
  reconnect-token helpers (`create`/`validate`/`mark_used` + `cleanup_reconnect_tokens`/
  `maybe_cleanup_reconnect_tokens`). Imports `get_db_conn` from `core.db`.
- **`core/ratelimit.py`** — `SlidingWindowLimiter` (in-memory per-process abuse throttle; used by the
  auth routes). **`core/config.py`** — `cors_allowed_origins()` (env-driven CORS allowlist, no
  web-framework deps so both `app.py` and the CoC sub-app share it).
- **Auth correctness (hard-won, June 2026 — DO NOT regress):**
  - **`is_admin` is computed the SAME way on every path** — `is_admin_id(conn, id)` (a plain
    `SELECT 1 FROM admins WHERE user_id=?`) OR a live `SITE_OWNER` username match. `get_user_by_session`
    previously used a **correlated subquery** `(SELECT 1 FROM admins WHERE user_id=users.id)` that read
    **NULL on the prod libsql driver** (works on sqlite, so invisible in tests): a refreshed session
    reported the owner as non-admin while login (via `is_admin_id`) said admin → the admin UI vanished
    on every reload until re-login. **Never use a correlated subquery here; reuse `is_admin_id`.**
  - **Usernames are unique, CASE-INSENSITIVELY.** `users.name` has **no UNIQUE column constraint**, so
    `create_user` checks `WHERE name=? COLLATE NOCASE` before inserting (the old `except
    sqlite3.IntegrityError` guard never fired — no constraint to violate, and libsql wouldn't raise that
    type anyway — so duplicate "Forrestm" rows slipped in). `init_core_schema` builds a NOCASE unique
    index **`idx_users_name_ci`** (dropping the earlier case-sensitive `idx_users_name`), tolerant of
    pre-existing dups so boot never fails. `authenticate_user` looks up NOCASE too, so login matches
    registration regardless of case.
- **Security hardening (June 2026 — DO NOT regress):**
  - **Tokens use a CSPRNG.** `gen_token` uses `secrets.choice`, NOT `random.choices` — it mints
    session tokens, account ids, reconnect tokens, AND password salts, and `random`'s Mersenne Twister
    is reconstructable from observed output (predict-the-next-token). Never revert it to `random`.
  - **Registration input validation.** `validate_credentials(name, password)` returns a human message
    or `None`: username **1–16 chars, `[A-Za-z0-9]` only**; password **1–16 chars**. Enforced at
    `/auth/register` ONLY — login stays permissive so pre-existing accounts still sign in (with a guard:
    reject name>64 / password>128 *unhashed*, a PBKDF2-on-huge-input DoS guard). Frontend input
    `maxLength` mirrors it (register 16/16; login 64/128, so legacy passwords stay typeable).
  - **Auth rate limiting** (`core/ratelimit.py` — in-memory, per-process; OK because the Procfile runs
    a SINGLE uvicorn process). `/auth/login`: 20/5min per IP + 10 **failures**/15min per username (the
    per-username streak resets on success, so multi-device logins aren't locked out). `/auth/register`:
    10/hour per IP. Client IP from `X-Forwarded-For` first hop (Render proxy), socket peer otherwise.
    Over-limit returns `{ok:False, message}` at **HTTP 200** (NOT 429) so the existing frontend error UI
    shows it. Residual: XFF is client-spoofable to rotate the per-IP key — the per-username failure
    limiter is the real brute-force defense.
  - **Session token in the `Authorization: Bearer` header, not the URL.** `bearer_token` (FastAPI
    dependency in `games/spender/main.py`) reads `Authorization: Bearer <tok>` with a `?token=` query
    **fallback** (so cached clients don't break mid-deploy). Applied to every session-token route in
    Spender, Books (injected into `setup_books` as `token_resolver` so books still imports no game), and
    CoC (a LOCAL `_bearer_token` copy — keeps CoC independent of Spender). The WS path is unchanged: it
    uses room-meta / reconnect tokens in the message BODY, never the URL. Frontends send the header
    (Spender 3 fetches, Books 4, CoC 2). Goal: keep the secret out of access/proxy logs + browser history.
  - **Reconnect-token cleanup.** `cleanup_reconnect_tokens()` deletes used/expired rows;
    `maybe_cleanup_reconnect_tokens()` throttles to ≤1/h/process and runs opportunistically inside
    `create_reconnect_token` (short-lived single-use tokens were accumulating forever).
- **Game retention** (`core/db.py`): `cleanup_stale_games(table)` deletes stale rows
  from a games table (`games` / `coc_games` — same shape) by **last activity
  (`updated_at`)**: an **all-guest** game (no player id present in `users`) after **24h**,
  a game with **any registered player** after **30d** (so a registered user's history
  survives even a game played with a guest). `maybe_cleanup_games(table)` is the throttled
  wrapper (≤1×/hour/table/process). Wired in BOTH games: `cleanup_stale_games(...)` once at
  module import (cold-start) + `maybe_cleanup_games(...)` at the top of each `list_open_games`
  (so it also runs during long-awake periods — Render's free tier has no cron). Tests:
  `core/tests/test_game_retention.py`.
- **Who imports it now**: `games/spender/main.py` (`from core.db import …`,
  `from core.auth import …`; its `init_db()` calls `init_core_schema` then creates only
  the Spender-owned `games` table), `games/castles_of_crimson/main.py` (directly at the
  top — the old lazy shims are gone), and Books (via the injected `get_db_conn`/
  `get_user_by_session` `setup_books` still receives — main passes the core functions).
- **Tests**: `core/tests/test_db_auth.py` (wrapper + password + admin + `init_core_schema` +
  `gen_token`/`validate_credentials`/reconnect-token cleanup) and `core/tests/test_ratelimit.py`
  (sliding-window limiter, `now` injected so it's deterministic), in-memory sqlite. CI runs
  `core/tests/` first; Render watches `core/**/*.py`.
- **Frontend** (partial, by design): the Vite build was relocated to a neutral top-level
  `webapp/` (no longer under `games/spender/`). The deeper **stateful shell/game split of
  `Spender.jsx` was deliberately SKIPPED** — it's a re-architecture of shared `screen` state
  + the mount-time WS auto-resume on a test-free, auto-deploying, TDZ-prone component, for
  purity only (the real coupling — CoC/Books reaching into Spender — was the backend, already
  fixed). Don't attempt it without a strong reason + local playtest gate.
- **Not yet done**: DRYing the duplicated room-server scaffolding (`ROOMS`/`ROOM_LOCK`/
  `broadcast_room`/`save_game`/`mk_room_state`/`_schedule_*_turn` are copy-mirrored in Spender
  and CoC `main.py`) into a shared `core` helper — Phase 3, defer until game #3.

### Composition root — top-level `app.py` (Phase 2, done)
The FastAPI **`app` and the feature wiring no longer live in a game module.** The
top-level **`app.py`** is the composition root: it creates `app = FastAPI(...)`,
applies CORS + security-headers middleware (see below), `include_router`s Spender's routes,
`setup_books(...)`, and mounts Castles of Crimson at `/coc` (same defensive try/except as before).
- `games/spender/main.py` now exposes **`router = APIRouter()`** (all its routes use
  `@router.…`, including the single `/ws/{room}/{player}` websocket) instead of owning
  the app. It still runs `init_db()` at import.
- **Layering**: `core/` (bottom) → features (`games.spender`, `games.castles_of_crimson`,
  `books`) → `app.py` (top). The composition root depends on features; features don't
  depend on it. `core` depends on neither.
- **CORS + security headers** (`app.py` + `core/config.py`): CORS is **pinned** to
  `cors_allowed_origins()` — the site's own frontends are ALWAYS allowed: `https://forry4.github.io`
  (GitHub Pages USER site served at the root `https://forry4.github.io/`, so the Vite `base` is `/`),
  the **Cloudflare staging mirror** `https://webprojectsstaging.forry4.workers.dev` (it reuses this same
  backend over HTTP), plus localhost dev. **`CORS_ALLOWED_ORIGINS`** (comma-separated) ADDS extra origins
  (e.g. a future custom domain) — it **merges with, no longer replaces, the defaults** (do not regress:
  the old replace-semantics meant setting the env var silently locked out the staging mirror, so its
  browser fetches got no `Access-Control-Allow-Origin` → the loading screen hung at 90% on `/games`;
  staging is frontend-only on the prod backend, so this is the ONLY way it can call the API). Methods
  GET/POST/PUT/OPTIONS, headers Authorization/Content-Type, **no credentials** (token auth, not cookies
  — so `*`-origin was never a credential leak, but pinning is hygiene). `SecurityHeadersMiddleware`
  (pure-ASGI, in `app.py`) adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy`, `Strict-Transport-Security` (HSTS), `Permissions-Policy` to EVERY response —
  **including the mounted `/coc` sub-app**, because the parent ASGI middleware threads `send` down into
  the mount. CoC's own CORS is aligned to the same list (the parent overrides it when mounted, but it
  matters if CoC runs standalone). **No CSP on the API** — it serves JSON (CSP guards HTML, which is
  GitHub Pages' job) and a strict policy would break FastAPI's `/docs` Swagger UI; a frontend `<meta>`
  CSP is a deferred follow-up.
- **Deploy entrypoint is unchanged**: `games/spender/app.py` is a thin shim doing
  `from app import app` (absolute import of the top-level module — repo root is on
  sys.path), so Procfile/Dockerfile/render.yaml keep targeting `games.spender.app:app`.
  Render also watches the new top-level `app.py`.

---

## Tech stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI, asyncio, SQLite (via `sqlite3`), `asyncio.create_task` + `loop.run_in_executor` for async AI |
| Frontend | React 18, plain JS (no TypeScript), Vite, single-file component (`Spender.jsx`) |
| AI | MCTS with `_MCTSNode` class (`__slots__`), 5-second time limit, runs in thread pool |
| Auth | JWT-less: session tokens stored in `users` table, reconnect tokens per-player per-room |

---

## Backend architecture (main.py)

### In-memory state
`ROOMS: dict[str, dict]` — keyed by room_id. Each room:
```python
{
  "players": {pid: name},
  "sockets": {pid: WebSocket},
  "status": "open" | "playing" | "over",
  "host": pid,
  "game": { ... },   # None until started
  "meta": {pid: {"token": str, ...}},
}
```

### DB persistence
- `save_game(room_id)` — upserts room to `games` table (called after every state change, outside lock)
- `load_game_to_memory(room_id)` — called on WS connect if room not in ROOMS; loads from DB
- **`ai_variant` is persisted** in the saved room state and restored on load. Without it, a vs-AI game
  reconnected after a redeploy (which wipes in-memory `ROOMS`) lost the room-level variant: the move
  scheduler fell back to variant **"A"** (wrong bot) and `mk_room_state` dropped `ai_variant` +
  `ai_card_values` (so the admin value-overlay button disappeared, working only on a fresh game).
  `load_game_to_memory` has a **back-compat fallback** recovering the variant from the AI player's
  `"AI (X)"` display name for games saved before the field was persisted.

### Lock
`ROOM_LOCK = asyncio.Lock()` — all ROOMS mutations happen under this lock.

### Async AI turn flow
1. Human's move is processed under lock, `_post_turn` called (just syncs status now).
2. After `broadcast_room`, `asyncio.create_task(_schedule_ai_turn(room_id))` is fired.
3. `_schedule_ai_turn`:
   - Acquires lock → snapshots game → releases lock
   - Runs `_mcts_choose_move` in thread pool (`loop.run_in_executor(None, ...)`) — 5 seconds
   - Acquires lock again → verifies turn/phase haven't changed → applies AI move → releases lock
   - Calls `save_game` and `broadcast_room` outside lock
4. This means the UI updates immediately after the human moves, then again after the AI thinks.

### `_schedule_ai_turn` is safe to call any time
It guards internally: returns immediately if not AI's turn, game not found, or phase not "playing".
Called from: move handler, create action (vs_ai), both reconnect handlers.

### WS disconnect cleanup — stale-socket guard
The `finally` block in `ws_room_player` only removes a socket and potentially the room if `r["sockets"].get(pid) is websocket` (the exact WS object for this handler). This prevents a reconnect race: when WS1→WS2, WS2 registers its socket first; without the guard, WS1's finally would remove WS2 and delete the room, causing "game not started" on the next move or a waiting-screen flash if the reconnect response was built after deletion.

### AI pipeline
- `_mcts_choose_move(game, ai_pid, time_limit=5.0, max_iters=None)` — tree MCTS with `_MCTSNode`. Stops at whichever of `time_limit` (wall-clock, prod) or `max_iters` (iteration count, training) is hit first.
- `_MCTSNode` uses `__slots__`, UCB1 child selection (negates exploit for opponent nodes), iterative backprop
- `_fast_rollout_move` — rollout policy: buy > reserve high-value > take gems
- `_ai_score_card` — heuristic with deficit-weighted accessibility multiplier
- `_sim_rollout` — max 25 turns, linear position evaluator (`pos_points*pts + pos_buyable*buyable + pos_noble*noble_proximity + pos_bonus_count*bonus_count`)

### AI weights (`WEIGHTS` / `weights.json`)
All heuristic magic-numbers live in `DEFAULT_WEIGHTS` (a module-level dict); the live values are in the global `WEIGHTS`. `load_weights()` runs **at import**: it merges `weights.json` (if present, in the package dir) over the defaults — unknown keys ignored, missing keys keep defaults, malformed/missing file falls back silently. **Defaults equal the original hand-tuned constants, so production play is byte-identical unless a `weights.json` is deployed.** Two weight groups:
- **Card-scoring** (`point_urgency_mult`, `bonus_l1/l2/l3`, `bonus_reserved`, `bonus_urgency_decay`, `noble_card`, `access_base`, `access_urgency`, `rollout_reserve_threshold`) — drive `_ai_score_card` + rollout policy (how the AI *picks moves*).
- **Position-eval** (`pos_points`, `pos_buyable`, `pos_noble`, `pos_bonus_count`) — drive `_sim_rollout`'s truncation evaluator (how the AI *evaluates positions*).

### Self-play training (`train.py`, offline only)
`train.py` plays the AI against itself headlessly (~290 greedy games/s) to learn `WEIGHTS`, then writes `weights.json`. It imports `main`'s game logic directly; it never starts the server or touches `users.db`. It swaps the global `main.WEIGHTS` to each mover's weights before its decision.
- **Phase 1 — `evolve`**: population of card-scoring weight vectors plays a round-robin self-play tournament; mutate + select by win rate. Tunes the move policy.
- **Phase 2 — `td`**: TD(λ) with eligibility traces learns the linear position-eval weights toward the realised point margin from self-play trajectories. (TD(0) was tried first and **diverged** on the highly-correlated consecutive board states — `pos_points` collapsed, error rose — so λ-traces + feature scaling are used; λ→1 recovers Monte Carlo.)
- **`all`** runs both in sequence; **`validate`** plays learned-vs-default with real MCTS and reports the learned side's score (only deploy `weights.json` if >0.5).
```bash
python -m games.spender.ai.train all --generations 20 --pop 12 --games-per-pair 12 \
    --td-games 3000 --validate-games 40 --out games/spender/ai/weights.json
```

### Deployed weights (current)
A trained `weights.json` **is currently deployed** (the backend loads it at startup). It beat the original hand-tuned defaults **0.725 vs 0.275** over 40 MCTS validation games (150 iters/move, seats swapped). Notable shifts the AI learned:
- `bonus_l1` 0.2→0.63 (values cheap L1 engine-building more), `bonus_reserved` 0.5→0.01 (stopped valuing bonuses toward reserved cards), `access_urgency` 0.4→0 (dropped late-game distance penalty), `rollout_reserve_threshold` 5.0→8.8 (much more selective about reserving).
- `pos_noble` 0.3→2.19 (noble proximity is ~7× more predictive of final margin than hand-tuned), `pos_bonus_count` 0→0.91.

To **revert to the original AI**, delete `games/spender/ai/weights.json` — `load_weights()` falls back to `DEFAULT_WEIGHTS` with zero behaviour change. Caveats: validation ran at 150 MCTS iters/move, not production's 5-second budget; evolve fitness plateaued at 0.674 by gen 4 (search converged early — larger pop / higher `sigma` to explore further).

### Stage 1: learned value leaf evaluation (`value_model.json`)
NNUE-style: when a `value_model.json` is present, MCTS evaluates leaf nodes with a learned logistic value model (`_value_estimate`/`_value_logit`, **pure-Python inference** — no production ML dependency) instead of a greedy rollout. Absent → rollout, byte-identical. `_value_features` is a 10-feature `order[0]`-minus-`order[1]` diff + turn indicator. `load_value_model` rejects a model whose feature count ≠ `VALUE_FEATURES` (falls back to rollout). Trained offline by `train.py value` (numpy) on exploratory self-play; a **linear** model is deployed.
- **Validated**: value-leaf beats rollout **0.533 vs 0.467** on equal *wall-time* (cheaper eval → more MCTS iterations). At equal *iters* it loses — its advantage is speed, so always A/B by **time** (`--time`), not iters.
- Playtest toggles: `SPENDER_VALUE_MODEL=none uvicorn …` forces rollout; `SPENDER_WEIGHTS=…` swaps weight sets.

### AlphaZero stack (`ai/az/`) — the current strength roadmap
Approved plan: fast engine → AlphaZero self-play → tournament eval → serve as
variant **Z**. 2-player only. Key facts:
- **engine.py** is a compact int-state simulator with **proven rule parity**:
  200 random games stepped through both engines with state compared after every
  move (`test_az_engine.py`). Card/noble data is imported from `main.py`, never
  duplicated. ~100k moves/s/core (pure Python; Rust port not needed).
  Gold DOES count toward the 10-token cap. Discard/noble-choice are real
  decision phases (the policy learns them). `to_game_dict`/`from_game_dict`
  convert to/from the incumbent dict format.
- **mcts.py**: PUCT, hidden info via per-simulation determinization (unseen =
  decks + opponent blind reserves, reshuffled within level). Turns don't
  strictly alternate, so backups credit edges by acting-player identity.
- **train_az.py**: self-play → train → gate (promote at >=0.55) → auto-export
  `.npz`. Resumable (`--resume`). Trains on the user's RTX 4050 (torch cu128,
  Python 3.14). `selfplay.run_games` is the single batched driver for both
  self-play and net-vs-net gating.
  - **`--iters` is an absolute total**, not "N more": on resume the loop runs
    `range(start_iter, args.iters)`. To add 70 iters after a 30-iter run:
    `--resume --iters 100`.
  - **Exploration / reward knobs** (added after the degenerate-equilibrium
    diagnosis below): `--reward-shaping` (0..1), `--shaping-scale`,
    `--temperature`, `--temp-moves`, `--dirichlet-eps`. Self-play log prints
    `winpts` (winner's avg points/game) + `combined` — the scoreboard that
    makes the 0-0 collapse visible.
  - **Parallel self-play** (`--workers N`, default 1): fans games across N CPU
    processes via `selfplay.run_games_parallel` (each worker does CPU numpy
    inference off a `.npz` snapshot of the current net; GPU stays free for the
    training step). The gate parallelizes too. `--workers 1` keeps the old
    single-process torch path. ~4.8x self-play throughput at 10 workers on the
    12-core laptop (~700s -> ~160s/iter self-play); ~3-4x end-to-end.
    - **CRITICAL — single-thread BLAS/OMP.** `train_az.py` sets
      `OMP/OPENBLAS/MKL/NUMEXPR/VECLIB_*_NUM_THREADS=1` at the very TOP (before
      numpy/torch import) so spawned workers inherit it. Without this, every
      worker's BLAS spins one thread per core -> 10 workers x 12 threads thrash
      the box (observed: 30+ min hang producing zero output). GPU training in
      the parent is unaffected (CUDA, not BLAS). Do not remove this block.
- **watch_game.py**: prints a human-readable play-by-play of one
  AZ-vs-heuristic game (board, both players' state, AZ's top MCTS visit
  distribution, the move taken). The diagnostic that surfaced the equilibrium
  bug. `python -m games.spender.ai.az.watch_game --az <npz> --opp C2 --seed N`.
  (Keep output ASCII-only — Windows console is cp1252; no box-draw/arrow glyphs.)
- **Serving**: `main.py` loads `ai/az_model.npz` if present → variant "Z"
  (numpy-only PUCT via `infer_np.py`, same 5s thread-pool path). No file → Z
  falls back to A; zero behavior change. `SPENDER_AZ_MODEL=none` disables.
  Production deps gained only `numpy`; torch stays out of prod.
  **`az_model.npz` is currently deployed** (exported from iter-177 best checkpoint,
  p=0.90, 113 promotions, sims=512). Variant Z is live on the website. Export process:
  `ckpt = torch.load('az_best.pt', map_location='cpu'); net.load_state_dict(ckpt['best']); export_npz(net, 'az_model.npz')`.
  Render auto-deploys on push to `ai/az_model.npz` (wired in `deploy-render.yml`).
  Can export mid-training safely (training writes `az_best.pt`; export reads it and
  writes `az_model.npz` — separate files, no interference).
- **arena.py**: AZ vs heuristic tournaments (heuristic plays via dict
  conversion + its own `_mcts_choose_move`; sub-decisions replicate
  `_ai_discard_one`/`_ai_pick_noble`). Wilson CIs. Deploy gate: >=0.70 vs B
  and C2 at production budgets + human playtest.

### AZ — the degenerate-equilibrium bug and the reward-shaping fix (June 2026)
**This is the most important AZ finding so far. Do not relitigate.**

The first AZ run (`checkpoints/`, 58 iters, pure terminal win/loss reward)
trained healthily by its own gate (candidate-vs-best score rising, promote→dip→
recover) but **lost ~0.0 vs C2** in the arena at every checkpoint measured:
| Checkpoint | AZ vs C2 (60g) | notes |
|------------|----------------|-------|
| Iter 13    | 0.017          | 300 sims |
| Iter 28    | 0.050          | 300 sims |
| Iter 40    | 0.017          | 300 sims; **also 0.000 at 1000 sims** |
| Iter 54    | 0.017          | 300 sims (best gate score 0.683) |

More search did NOT help (1000 sims = 0.000) → the **policy**, not search depth,
was the problem. `watch_game.py` on iter-40 vs C2 (seed 42) showed why: **AZ
scored 0 points the entire game**, bought 7 cards (all 0-point L1), hoarded
tokens and discarded them ~15×, and opened by reserving two 7-cost L3 cards it
could never afford. C2 scored 16, bought 26 cards, claimed a noble.

**Root cause — a degenerate self-play equilibrium.** Both self-play players share
one net. Early nets rarely score, so games end 0-0 and the winner is decided by
the **fewest-cards tiebreak**. That makes "buy as little as possible" the
self-play-optimal strategy — the exact opposite of what beats a scoring
opponent. The net faithfully optimized the tiebreak. This explains all three
symptoms: healthy gate scores (it got better at the tiebreak vs itself), zero
arena wins (vs a scorer the tiebreak never triggers), and no benefit from more
sims (searching harder for the wrong objective). It is the same blind-spot class
as the documented "self-play is blind to tactics the opponent never demonstrates."

**Fix (shipped in `selfplay.py` / `train_az.py`):**
1. **Reward shaping** (`--reward-shaping`, default 0): value target blends
   terminal win/loss with `tanh(point_margin / shaping_scale)` per mover
   perspective. A 0-0 game becomes a true neutral instead of rewarding the
   buy-nothing tiebreak winner; actually scoring is what gets rewarded. Verified:
   shaping=0 → value targets take 2 distinct values (±1); shaping=0.5 → 28
   graded values in [-1,1].
2. **More exploration**: `--temp-moves` 10→20, `--dirichlet-eps` 0.25→0.35, so
   the net stumbles into point-card buys often enough to learn they're good.
3. **`winpts` scoreboard** in the self-play log makes the equilibrium visible:
   ~0 = degenerate; climbing toward 12–16 = the net is learning to score.

**Validation run** (fresh, NOT resumed — old net/buffer are attractors toward the
broken strategy; new dir `checkpoints_shaped/`):
```bash
python -m games.spender.ai.az.train_az --iters 60 --games 400 --sims 128 \
  --parallel 128 --gate-games 60 --gate-threshold 0.55 \
  --reward-shaping 0.5 --shaping-scale 6.0 --temperature 1.0 --temp-moves 20 \
  --dirichlet-eps 0.35 --out games/spender/ai/az/checkpoints_shaped
```
Iter 0 (random-net baseline): winpts 15.7. The verdict is whether iters 1–5 HOLD
winpts high (fix works) vs collapse toward 0 (the old run would have collapsed
here). **Do not ship az_model.npz until arena shows >=0.70 vs B and C2.**

### AZ league — training vs opponents, not just self (the strength lever)
Pure self-play hit a hard ceiling vs the heuristics: arena AZ-vs-C2 was **0.033
at iter 9 and 0.025 at iter 27** — FLAT across 18 iters of shaped self-play,
even though the self-gate score kept rising (the net got better at beating its
own clones in a strategy space that doesn't overlap C2's). This is the
documented "self-play is blind to a style the opponent never demonstrates."
**Cure = play against the real targets.** (`league.py` + `--league` in train_az.)

- **`league.py`**: `play_recorded_game(net_eval, opponent_fn, ...)` plays one
  game where the training net searches+records ONLY its own moves (shaped value
  targets, same as selfplay) while the opponent moves via a callback. Opponents:
  heuristic A/B/C2 (`arena._heuristic_action`, incumbent MCTS in dict format) or
  a frozen past-AZ checkpoint (`_az_opponent_action`, greedy PUCT on its npz).
  We record only the net's moves — learning to BEAT opponents, not imitate them.
  These games are NOT batchable (opponent isn't the net), so they run
  one-at-a-time inside pool workers via `run_league_games`, which also returns
  per-opponent net win rate — the live progress-toward-goal signal.
- **`--league`** (needs `--workers>1`): each iter mixes `--self-frac` self-play
  (batched) + `--heur-frac` split across `--heur-variants` + `--league-frac` vs
  sampled past-AZ checkpoints from `out/league_pool/` (snapshotted on each
  promotion, capped at `--pool-size`). Empty pool folds the past-fraction into
  self. Reward shaping is doubly important here: the net loses most early games,
  so the margin term ("lost by 2" vs "lost by 15") is what provides the climb
  gradient. Deployed mix (user-approved broad): self .4 / heur .4 (A,B,C2) /
  past .2, `opp_iters=120`.
- **League gate**: candidate vs best on the SAME heuristic set, greedy
  (`_league_gate`), promote if cand >= best (ties promote early while both lose
  to C2). Replaces the self-gate, which was exactly the misleading metric (it
  rose while real strength stayed flat). The `[iter] league:` log line prints
  `net-vs: A .. B .. C2 ..` — watch C2 climb off ~0.
- **Launch** (resumes from the shaped iter-27 net):
  ```bash
  python -m games.spender.ai.az.train_az --iters 80 --games 400 --sims 128 \
    --workers 10 --gate-games 60 --gate-sims 96 --reward-shaping 0.5 \
    --temperature 1.0 --temp-moves 20 --dirichlet-eps 0.35 \
    --league --self-frac 0.4 --heur-frac 0.4 --league-frac 0.2 \
    --heur-variants A,B,C2 --opp-iters 120 --opp-sims 96 --pool-size 6 \
    --out games/spender/ai/az/checkpoints_shaped --resume
  ```

### AZ open risk — single-strategy collapse (raised by the user, valid)
Even with scoring fixed, pure self-play can tunnel on ONE plan (e.g. wide-L1 →
nobles) and never learn that rushing efficient high-point L2/L3 cards beats it on
many boards — because both shared-net players adopt the same plan, the
counterexample is never generated, and the value head mis-evaluates the unplayed
line (so search can't rescue it; garbage value → garbage search). The user's own
strategy model says the right plan is **board-conditional**, and the features
encode the board, so the net CAN represent "rush here, go wide there" — it just
needs to SEE both resolve. **Planned mitigation = opponent diversity (a league):**
train/gate against a sampled pool of {past AZ checkpoints + heuristic A/B/C2},
not only the current best. This is the real reason to keep the heuristic-in-loop
idea (it was deferred for breaking the 0-0 equilibrium, where shaping subsumes
it, but it is the primary cure for strategic diversity). Build after scoring is
confirmed stable.

### AZ — the fitness-valley wall and the adaptive curriculum (June 2026)
**Reward shaping was NOT the bottleneck — don't relitigate it.** Both the league
(tanh) and a linear-shaping rerun left the net FLAT at ~4 pts / −12 margin vs C2
across 10–27 iters (margin probe: net scores ~4, C2 ~16, win rate ~0). Linear
shaping gives a ~6× stronger per-point gradient (verified) yet moved nothing.

**Root cause — a fitness valley, not a weak gradient.** Against a *fast* opponent
(C2 reaches 15 in ~16 plies), the loss-minimizing play is to grab a few quick
points (~4) — a local optimum. WINNING requires building an engine (cheap
0-point cards early) that only pays off later — but C2 ends the game before the
payoff, so margin-minimization *punishes* the very investment winning needs. The
winning strategy sits across a valley from the loss-minimizing one; gradient
won't cross it. Evidence the net CAN play well given time: it scores 15+ in
self-play (80–120-ply games) — it just builds engines ~5× too slowly and never
faces a beatable racer to learn tempo from.

**Probes that found the curriculum axis** (current net vs opponent, 30g):
- vs **random**: net **wins 0.87** (scores 14) — beats non-racers easily.
- vs heuristic at **any** `opp_iters` (even 1): **0.00–0.20** — every competent
  eval RACES (opp ~16 pts) regardless of search depth. So `opp_iters` is a
  *cliff*, not a ramp — wrong curriculum axis.
- **eps-mixed opponent** (heuristic move w.p. `p`, else random) gives a SMOOTH
  ramp: net win rate 0.80 / 0.70 / 0.47 / 0.20 / 0.07 at p = 0 / .25 / .5 / .75 / 1.
  `p` is a **tempo** knob — the right axis.

**Adaptive curriculum** (`--curriculum` in train_az, `eps` kind in league.py):
the heuristic fraction faces an eps-opponent at difficulty `p`; after each iter
`p` auto-climbs if the net's win rate vs the current level ≥ `--curr-target`
(0.55), drops if it falls behind — keeping the net at its winnable frontier. Goal:
ride `p` → 1.0 (full racer) with the net still winning, which means it learned to
race. `p` persists in checkpoints. Log line: `[iter] league: p=X.XX … net-vs:
cur Y.YY`. Launched resuming the v3 net (competent at low p) with a CLEARED
buffer (so the value head drops its "always lose" pessimism). Watch `p` climb;
a stall = the tempo wall it can't yet cross.

**`p` adapts from the GREEDY GATE score, not the generation win rate.** Early on
the generation `net-vs cur` (~0.38) ran far below the gate's greedy score (0.667
at the same p) because self-play exploration (temp + Dirichlet) depresses
play — using it to drive `p` kept the curriculum stuck artificially low. So the
adapt step moved to *after* the gate, using the promoted/best net's greedy gate
win rate (`_curriculum_gate`): `p += --curr-step` if ability ≥ target+0.05,
`-=` if ≤ target−0.10, deadband holds. With this, `p` climbed 0.35→0.40→0.45→0.50.
End condition (beat full racer greedily ≥0.55) aligns with the deploy arena gate.

**Search depth is the quality lever (`--sims`).** Bumped 128→384 (`--gate-sims`
96→192), user OK with ~3× slower iters. Rationale: the net distills the MCTS
visit distribution, so shallow search = weak policy targets; deeper search also
finds the efficient racing lines the net otherwise never sees (directly attacks
the tempo problem) AND makes the curriculum games themselves better-played. Try a
bigger net (the MLP is only ~600k params) ONLY if sims plateaus — capacity before
data/search quality just overfits. **sims bumped 384→512** after plateau at p=0.80
— confirmed working, frontier moved to p=0.85 then p=0.90. **sims bumped again
512→768** (gate-sims 256, opp-sims 128) after plateau at p=0.90 for ~18 iters
with gate scores stuck at 0.53–0.58 — watching whether frontier moves to p=0.95.

**gate-games bumped 60→120** (SE ±0.065 → ±0.046) after variance was causing
artificial p drops: a single unlucky 26/60 gate ended a 14-iter p=0.90 streak.
With 120 games the net held p=0.90 for 18+ consecutive iters cleanly before the
sims bump.

Current run: `checkpoints_v3`, at iter ~196, p=0.95, sims=768, --iters 300.
sims=768 pushed frontier to p=0.95 by iter 191 (best=0.617) and the net is
**holding p=0.95** for the first time (5 consecutive iters 192–196, gate scores
0.40–0.52). `az_model.npz` deployed at iter 177 (113 promotions). Next milestone:
gate score ≥0.60 at p=0.95 → push to p=1.0 → arena vs B/C2 → ship if ≥0.70.

**Human playtest finding (iter 177 net):** the net **over-reserves** — reserving
frequently and often reserving cards that don't make strategic sense. Root cause:
(1) self-play doesn't punish tempo loss from bad reserves because both players do
it; (2) gold token over-valuation in the value head biases toward reserving;
(3) shallow search doesn't see the downstream cost of a wasted turn. Sims bump
directly attacks (3). (1) and (2) require structural fixes:
- **Better features** (planned for next retrain — incompatible with current weights,
  requires fresh start): three high-value additions:
  1. **Effective cost** per card (raw cost minus player's current bonuses, per color).
     The net can technically derive this from existing features but has to learn
     the subtraction internally; explicit = much easier to use.
  2. **Engine value** per card — pre-computed scalar: this card's bonus color ×
     sum of cost-reduction it provides to every other visible card, weighted by
     those cards' point value. This is a *cross-card interaction* an MLP cannot
     easily discover on its own from a flat feature vector (requires reasoning
     across multiple cards simultaneously). Pre-computing it as a feature is a
     genuine win — directly addresses "which card is worth reserving/buying."
  3. **Turns-to-afford** per card — cost gap per color ÷ estimated gems/turn.
     Addresses reserve *frequency* (tempo awareness), not just card selection.
     "This card needs 4 more red gems; I'm collecting ~1/turn → 4 turns away"
     directly distinguishes smart reserves from wasteful ones.
  Noble-progress per card (how many noble requirements this satisfies) is also
  worth adding but partially encoded already.
  **Do NOT add these features mid-run** — input dimension change invalidates all
  current weights. Schedule for a fresh retrain after the current run finishes.
- **Harder opponents**: C2 races but doesn't punish bad reserves as severely as a
  human. The net needs to face opponents that end the game before wasteful reserves
  pay off.
- **Sims ceiling**: more search helps up to a point, but if the value head
  fundamentally misvalues tempo, MCTS just finds better moves within a flawed
  strategy. The remaining lever after sims is value function quality + features.

**Checkpoint system and branching (how to experiment safely):**
- Training saves to `checkpoints_v3/`: `az_best.pt` (best promoted net — dict with
  `best` weights, `iter`, `promotions`, `curr_p`), `az_last.pt` (latest candidate),
  `buffer.pkl` (300k-position replay buffer). All gitignored.
- **Fully resumable**: stop anytime, restart with `--resume` — picks up exact iter,
  p value, and buffer. Can pause indefinitely.
- **Branching for a feature experiment**:
  1. Stop current run.
  2. Copy `checkpoints_v3/` → `checkpoints_v3_backup/` to preserve the original.
  3. Modify `features.py` (new features change input dimension → old weights incompatible).
  4. Start a **fresh** run in a new dir (e.g. `checkpoints_v4_features/`) — no `--resume`.
  5. If new net wins arena → ship; if worse → delete branch, `--resume` from backup.
  - The branch is a genuine fresh start — the 196+ iters of learned weights cannot
    carry over to a new input dimension. Trade-off: known-good current net vs
    untested feature-enriched net that starts from zero.
  - **Decision point**: finish current run first, evaluate iter-300 net strength,
    then decide if a feature-enriched retrain is worth losing the current weights.

### Heuristic-tuning campaign results (June 2026 — superseded by AZ stack)
- Ablation (40g, 120 iters, seed 777): `noble_scarcity=1.5` → 0.688 vs B was
  the only strong feature; `pos_noble_scarcity` 0.588; `lose_prevention` 0.525;
  `efficiency_weight`/`bonus_target_pts`/`gold_reserve` all hurt.
- Sweep grid (seed 42): best combo `noble_scarcity=2.5 + pos_noble_scarcity=0.5`
  → 0.675 screening, but **0.583 on the fresh-seed 60-game confirm** —
  regression to the mean; the gain is real but ~0.58-0.65 true, NOT 0.70.
  Candidate file: `ai/weights.c2_candidate.json` (uncommitted).
- Coevolve (6 gens, real MCTS): `lose_prevention`/`gold_reserve` selected out
  to 0.0; best individual validated 0.600 vs A → `ai/weights.coevolved.json`.
- Conclusion: weight-space tuning over the existing features saturates around
  0.6 vs B. This is why the AZ rewrite exists.

### Variant H2 (`ai/az/heuristic2.py` + `valuation2.py`) — the `take_value` heuristic (DEPLOYED)
A from-scratch greedy heuristic, **served as website variant "H2"**, separate from variant H.
**Full write-up: `games/spender/ai/az/H2.md` — read it before touching H2.**
- **Model:** `take_value = (engine_value + point_value) / (1 + total_cost)`. cost = `W_TEMPO·tempo +
  W_GEM·gem + W_GOLD·gold` (all post-bonus); points are game-STAGE-scaled (engine early → points late,
  + `ENG_DECAY` fades engine as cards accumulate); `engine_value` includes a forward-looking
  undealt-deck-demand term. 1-ply greedy, same serving path as H.
- **Deployed config (committed on main; beats H ~0.69 greedy):** `heuristic2` W_TEMPO 0.5 / W_GEM 0.2 /
  W_GOLD 0.4 / NOBLE_SCALE 3.0 / STAGE_K 8 / STAGE_FLOOR 0.25 / ENG_DECAY 0.3; `valuation2` ENG_DECK_W 3.5
  / ENG_DIV 8 / ENG_FLOOR 0.2 / NOBLE_CLOSE_FLOOR 0.2 / GOLD_BANK_CAP 2. The big levers were ENG_DECK_W↑
  + NOBLE_SCALE↑ (~+0.06); ENG_DECAY +0.011; cost weights saturated.
- **Tooling (offline; restore modules after):** `h2_tune.py` (CRN A/B; `--opp H` vs heuristic H, `--opp h2`
  = self-gate vs the CURRENT committed H2 — far more sensitive once H2 ≫ H) and `h2_autotune.py`
  (autonomous coordinate-descent campaign, NO human input: screen → validate on disjoint holdout vs self
  AND vs H → adopt → re-screen; prints a vetted config, never edits source).
- **Tuning methodology — DO NOT regress:** CRN (same seeds across configs) is for the *comparison*; the
  final estimate MUST come from FRESH **disjoint** holdout seeds (tuning-set optimism shrank gains ~⅔).
  **Seed-spacing bug:** `h2_tune` uses deck seed `base_seed+i` over N games, so two base seeds must be
  spaced **≥ N apart** to be independent (seeds 1–3 apart share ~1598/1600 games → fake "agreement").
  Self-gate tuning needs a **self-exploit guard**: adopt only if the change ALSO doesn't regress vs H — a
  change can beat *this* config via rock-paper-scissors yet be weaker vs the external yardstick.
- **Tested & REJECTED — parked default-OFF behind flags in `heuristic2.py` (do not relitigate):**
  `USE_TAKE2` (take-2-of-a-color): naive form made bad moves (−0.03), reserved-only form ~neutral (fires
  0.27% — winning reserves are gold-necessary, the opposite of take-2's full-bank need). `W_SHORTFALL`
  (bank-aware gold shortfall in cost): cuts a 14.9%→11.6% "stall on an un-completable card" rate, +0.006
  lean but sub-significant. `NOBLE_SCARCITY` (scarcity-gated nobles): INERT — `board_scarcity`≈0 on 98%
  of boards (real Splendor boards almost always offer an efficient L2/L3 deal). `USE_OPP_SNIPE` (pivot off
  a card the opponent will buy): wash/negative — contention is a documented 1-ply greedy wash. **All four
  are good NET-feature candidates, not greedy levers** (see FEATURES_V4.md + `.claude-plans` H2 feature doc).
- **On-card AI-values overlay is now ADMIN-ONLY (default OFF):** the per-card T/E/P/C box (H2) / single
  value (H) only renders for `authUser.is_admin`, behind a "Show/Hide AI values" toggle in the game
  action bar (AI games only; persisted in `localStorage.spender_show_ai_vals`). Frontend gating in
  `Spender.jsx` — the data is still in the WS payload (non-sensitive AI valuations), just not shown to
  non-admins; a backend per-recipient gate was deemed not worth it for this non-sensitive overlay.
- **Overlay follows WHOEVER'S TURN IT IS (June 2026, `82120c8`):** `mk_room_state` computes
  `ai_card_values` from `game["turn"]`'s seat (not always the AI's) and sends `ai_values_pid`. So on
  YOUR turn the box shows what each card is worth to YOU ("what should I take" — tinted **green**,
  tooltip "Your values"; your own reserved cards get values too), and on the AI's turn it shows the
  AI's perspective (**gold**, "AI's values"). The `_s/_h3/_h2/_v4_card_values(game, seat_pid)` helpers
  take the perspective seat (param renamed `ai_pid`→`seat_pid`); reserved cards follow that seat
  (so blind opponent reserves never leak — they're redacted and keyed by a non-real id anyway).
  Frontend (`Spender.jsx`): `valsMine = roomData.ai_values_pid === myId` drives a `.mine` tint on the
  `.ai-vals`/`.ai-val` box; the **Show/Hide AI values** toggle moved OUT of `.actions-panel-top` INTO
  the actions buttons box (desktop `.actions-panel-btns` + mobile `.board-actions-btns`) via
  `renderAiValsToggle()`, **far-left** (`.ai-vals-toggle{margin-right:auto}`) and styled like the Take
  button (`btn btn-gold`), rendered on EITHER turn so the overlay is toggleable any time.
- **Admin-button login bug fixed (same commit):** `handleAuth` rebuilt the user object as
  `{id, name, session_token}`, **dropping `is_admin`** from the `/auth/login`/`/auth/register` response,
  so the admin-gated overlay button only appeared after a page reload (the on-load `/auth/session` path
  at `Spender.jsx` repopulates `is_admin`). `handleAuth` now preserves `is_admin: !!data.user.is_admin`,
  matching the on-load path — admin features light up immediately on login, no reload.

### Variant H3 (`ai/az/heuristic3.py` + `valuation3.py`) — turns-remaining engine horizon (DEPLOYED)
A sandbox fork of H2, **served as website variant "H3"** (a playable opponent + a per-card potential overlay,
wired in `main.py`). Same 1-ply greedy `choose_action`/`components` contract; it reframes H2's value model around
a **potential vs take** distinction and a **turns-remaining horizon**. Permanent invariants live in
`games/spender/tests/test_h3_valuation.py` (9 tests) — keep them green.

**Model** (`components`): `take = (engine_term + point) / (1 + cost)`
- `cost = W_TEMPO·tempo + W_GEM·gem + W_GOLD·gold` (post-bonus; one currency used everywhere).
- `point = PTS + NOBLE_SCALE·noble_progress + noble_completion` — **NOT stage-scaled** (full value always; H2's
  point-staging, `ENG_DECAY`, and the per-card tempo-discount were all REMOVED).
- `engine_term = W_ENGINE · max(0, turns_remaining − tempo) · engine_value(ci)` — engine value × the turns it
  will COMPOUND. A card you can't finish before the game ends contributes ~0 engine. This horizon replaces
  stage/eng_decay (`W_ENGINE` is the engine-vs-points balance knob).
- `engine_value(ci) = Σ over OTHER cards cj still needing ci's bonus color of _delta_take(cj)` (+ reserved
  premium + deck-demand term); `_delta_take(cj) = potential(cj) · [1/(1+cost') − 1/(1+cost)]` — the take-value
  uplift ci's +1 gives cj; the `1/(1+cost)` convexity auto-weights a near-affordable discount (2→1) over a far
  one (6→5), no extra knob.
- `potential(cj) = (PTS + POT_ENGINE_W·eng_base) · (1 + POT_REACH_W·reachability)` — worth as a DESTINATION,
  distinct from take_value (a far high-point card has high potential but ~0 take, which is exactly why its
  *builders* earn engine value while chasing it now is bad). `eng_base` = the legacy level-0 engine value (cached).
- `turns_remaining`: estimated future main-turns from `turns_table.json` (a MEASURED `(cards, points, gems) →
  avg turns-left` table from H3-vs-H2 games; rebuild with `h3_measure_turns.py`), **min over both players** (the
  leader sets the clock). NN-filled, gems weighted 0.25× a card. Absent file → flat fallback.

**Noble time-gate** (`NOBLE_TIME_GATE=True`, `NOBLE_TURN_W=1.0`) — the one structural fix that paid: a 0-pt card
advancing a far/late noble used to contribute a flat ~0.5 (no time awareness). Now `noble_progress` is smoothly
discounted by completability — `× eff/(eff + NOBLE_TURN_W·deficit)`, `eff = max(0, turns_remaining − tempo(ci))`
(turns left AFTER acquiring the card), `deficit` = bonuses still needed. Smooth fade toward 0, **no hard cliff**
(turns_remaining is an estimate). **~+0.02 vs H2** (the biggest recent greedy gain; `NOBLE_TURN_W` peaks at 1.0).

**Deferred idea — time-gate the raw card POINTS too (not done; noted on request):** `noble_progress` and the
engine term are both gated by buy-in-time feasibility (`max(0, T − tempo)`), but the raw `E.PTS[ci]` term in
`components` is NOT — so late-game `_choose_take` can still collect gems toward a high-point card it can't finish
before the game ends (the same blind spot the noble gate fixed, applied to a card's own points). The fix would be a
**clamped step** `min(1, max(0, (T − tempo)/M))` on `E.PTS[ci]` — distinct from the engine's *linear* ramp (points
are a ONE-TIME grab, so extra spare turns don't multiply them) and from the noble *deficit* fade. NOT double-counting
the `(1+cost)` denominator (that's time-blind). Likely a NARROW win at best — the engine term already zeroes an
unfinishable card's engine contribution, so only the points leak remains. A/B it behind a `POINT_TIME_GATE` flag if
revisited; expect it could be a wash (like the TURNS_FLOOR test was).

**Baked config**: `W_TEMPO=0.1, W_GEM=0.3, W_GOLD=0.4, NOBLE_SCALE=3.0, NOBLE_CLOSE_FLOOR=0.3, POT_ENGINE_W=0.5,
W_ENGINE=0.15, NOBLE_TIME_GATE on / NOBLE_TURN_W=1.0, POT_REACH_W=0 (OFF), BUILD_FLOOR_W=0 (OFF)`. Strength: **~0.54
vs H2, ~0.76 vs H** greedy (edges the old stage model; beats the external yardstick H by more than H2 does). To
recover exact-H2 for A/B: `USE_POTENTIAL_ENGINE=False` + `W_GEM=0.2`.

**Noble-weight campaign (June 2026) — `NOBLE_SCALE` 3.0→5.0 is the only gain, and it's small.** A broad campaign
(curves on noble closeness/engine distance; game-stage scaling of points/nobles/cost-weights; victory-proximity;
quadratic/exponent engine-distance reshapes) was run against the **H2 racer family** — `H2R` (rusher, `NOBLE_SCALE
×0.4`) and `H2N` (noble-heavy, `×2.0`), ported from `feat/az-v4-features` as `_AggrH2` wrappers in `h3_vs_h2.py`
(kept as **test infra**; H2N dropped from the metric as too weak/circular). Verdict on a **10-seed-base CRN
confirm** (the single-seed batches inflated badly): `NOBLE_SCALE=5.0` = **+0.0073 avg(H2,H2R)** (won 7–8/10 seeds
vs each racer), neutral vs H — shipped. **Everything else washed or hurt** on confirm: STAGE-scaling was robustly
**−0.02**; `NOBLE_CLOSE_EXP` (convex closeness), `VICT_PROX_W`, all engine-distance curves ≤ flat. This re-confirms
the **static greedy eval is saturated** — re-weighting can't beat ~+1pp; the remaining lever is search/net (see the
recursion/depth+1 direction noted for "at some point"). Campaign scratch (`h3_camp.py`/`h3_final.py`/`camp_*.out`)
was removed; the H2N/H2R wrappers + `h3_autotune` plumbing stay.

**Tuning findings — DO NOT relitigate** (validated on disjoint seeds, N≥3000):
- **The engine balance is a flat RIDGE.** `W_ENGINE` and `POT_ENGINE_W` both scale the engine term (pe sits
  inside potential → engine_value, which W_ENGINE multiplies), so they trade off — tune W_ENGINE *jointly* with
  pe, never in isolation. Optimal band `W_ENGINE 0.15–0.20 × pe 0.25–0.5`, all ~0.54; outside (we≤0.1 / ≥0.3,
  or we=0.2+pe=0.5) is worse. vs-H2 is **flat ~0.54** across the band — no sharp peak.
- **Reachability (`POT_REACH_W`) doesn't pay** in greedy — win-rate wash-to-negative across the full `we×pe×pr`
  grid (≥0.4 clearly hurts). The reworked formula (cost-reduction-weighted, affordable-gated, value-per-cost
  builders) is *correct and unit-tested*, but it's a NET-feature candidate, not a greedy lever. Left OFF.
- **`BUILD_FLOOR_W` hurts** (over-invests in builders for far targets it never finishes). OFF.
- **Sharpening the take denominator (`take = num/(C0+cost)`, C0<1) is the strongest REJECT measured.** Tested
  C0 = 0.7 / 0.5 / 0.3 to "make cost matter more" (motivated by an expensive L2 1-pointer edging a cheaper L1
  on turn 1): cratered **−0.025 / −0.060 / −0.122 avg(H2,H2R), 0/10 seeds, monotonic**, also negative vs H. The
  `+1` constant is **load-bearing** — making cost bite harder makes H3 too cheap-greedy and it under-builds toward
  point/engine cards. The take *numerator* should win those ties; a near-tie favoring the point-bearing card is
  correct, not a bug. (Confirms again: cost-side reshapes don't pay; the static greedy eval is saturated.)
- **`W_GEM=0.3` (vs H2's 0.2) is coupled to the engine** — neutral with the engine off; only helps with the
  turns-remaining engine on.
- **Greedy H3-vs-H2 saturates ~0.54** regardless of potential/reachability weights — same ceiling as H2's
  weight-tuning. Remaining lever is search/net. The exception that paid was the noble time-gate (structure, not
  a re-weight) — look for structural fixes, not more weight-tuning.

**Tooling** (offline; all parallel via multiprocessing — pure-Python games, BLAS is NOT a factor): `h3_vs_h2.py`
(H3-vs-H/H2 arena, `--set`/`--opp`), `h3_eval.py` (named-config A/B), `h3_autotune.py` (coordinate descent,
screen→disjoint-holdout), `h3_measure_turns.py` (rebuild `turns_table.json`), `h3_sanity.py` (interactive value
probes), `h3_stage_sweep.py`. **Methodology: a UNIQUE output file per run** (two runs writing the same `>` file
interleave and corrupt — happened once); confirm gains on DISJOINT seeds; re-measure `turns_table.json` after big
model changes (it's mildly self-referential). `h3_*.out`/`h3_best.json` are gitignored scratch.
- **Cross-worktree import gotcha — `python -m` runs the CWD's code, NOT `PYTHONPATH`'s (DO NOT regress).**
  `python -m games.spender.ai.az.<tool>` puts the **current working directory's** worktree FIRST on
  `sys.path`; `PYTHONPATH=<other-worktree>` does **not** override CWD for `-m`. So launching a self-gate /
  arena / autotune from the **primary (main) worktree** silently runs **main's** `v_state`/`config_selfgate`/
  etc. — NOT your experiment branch's. The candidate's `--set`/config `setattr`s then land on a module
  lacking the new code (no error), and `config_selfgate`'s `[frozen]` dict / `_PROBE_KEYS` silently **omit
  the new knob** (that absence is the tell). **ALWAYS `cd <experiment-worktree> &&` before `python -m`** (cwd
  wins), and sanity-check that `[frozen]` contains your new knob before trusting the run. (A plain
  `python path/to/script.py` is fine — `sys.path[0]` is the script's own dir, then `PYTHONPATH`.) This cost a
  wasted `W_RESERVE_SLOTS` self-gate that ran main's code with the knob absent from `[frozen]`.
- **Serving + overlay specifics:** `_h3_choose_move` (1-ply `choose_action`) + `_h3_card_values` are wired
  into `_ai_variant_valid` + `mk_room_state` + the move scheduler (same path as H/H2; `mk_room_state`
  includes `ai_card_values` only for in-progress H/H2/H3/S games, **now from whoever's-turn-it-is's seat**
  — see the "Overlay follows WHOEVER'S TURN IT IS" bullet under Variant H2). The admin overlay shows H2's T/E/P/C
  **plus a 5th `Po` (potential)** — gated in `Spender.jsx` by `aiValue.pot != null`, leaving H2's 4-value
  box unchanged. (Aside: an `az_vs_h2.py` arena measured H2/H3 **beating the deployed AZ net
  `az_model.npz` ~0.75 @ 300 sims** — the greedy heuristics currently out-play variant Z.)

### Variant S (`ai/az/v_state.py` + `vsearch.py`) — V(state) whole-position eval + determinized PUCT (STRONGEST; DEPLOYED June 2026)
The first variant to pair the strong H-family judgment with **real search** (the documented #1 remaining
lever). **Strongest variant yet:** panel avg **0.758** — vs greedy **H3 0.733**, H2 0.729, H2N 0.808, H2R
0.762 (N=120, sims=160) — beating greedy H3, which itself beats the deployed AZ net Z ~0.75. Served as
website variant **"S"**.
- **`v_state.py` — the position evaluator (the new piece).** The H-family scores ACTIONS (`take_value` of
  acquiring a card); `v_state.value(s, seat)` scores a whole POSITION:
  `V = tanh((STAND(me) − STAND(opp)) / SCALE)` in [−1,1]. `STAND(seat)` = weighted sum of five terms, each
  REUSING H3 primitives: realized points (+ convex near-win kicker); **engine_stock** (held bonuses' forward
  value, deck-demand-weighted × turns-remaining horizon); **progress** (top-k `take_value` of reachable
  targets); **noble_stand** (closest completable noble, time-gated); **econ** (useful gold − hoard penalty,
  aimed at the AZ-net over-reserve weakness). Scoring the opponent with the IDENTICAL function and
  subtracting makes **denial fall out of the search backup for free** (no `contested_weight` knob — the
  structural cure for the self-play denial blind spot). Opp blind reserves are an expected CONSTANT in static
  V (mirrors `features.encode`), concretized by determinization inside search. Public `value`/`components`
  build the Valuation; internal helpers read `val.s` (one source of truth).
- **`vsearch.py` — determinized PUCT, V leaf, H3 policy prior.** Reuses `az/mcts.Search` UNCHANGED for the
  hard parts (ISMCTS determinization of hidden info; correct non-alternating-turn backups) via a minimal
  `leaf_state=True` mode (hands the leaf State to the evaluator instead of `features.encode`). Leaf VALUE =
  `v_state.value_with` (NOT a rollout). Policy PRIOR = softmax over H3 per-action scores (buys/reserves by
  `take_value`, takes by the NORMALIZED need-vector) + an **H3-greedy-pick anchor** (`H3_PICK_W`). Serving
  uses a wall-clock budget (`SERVE_TIME=4.5s`); offline A/B uses fixed `sims`.
- **Serving:** `_s_choose_move` in `main.py` (mirrors `_h3_choose_move`/`_az_choose_move`) wired into
  `_ai_variant_valid` ("S") + `_schedule_ai_turn` + `mk_room_state` (reuses the H3 `_h3_card_values` overlay);
  `Spender.jsx` lobby picker includes "S".
- **DO NOT relitigate (findings):**
  - **Static value-leaf ≫ rollout leaf** (`h3l_probe.py`: static 0.58 panel vs rollout **0.28**, ~10× slower).
    Confirms "value-leaf beats rollout" — V is the judge, never a playout.
  - **Single-sample determinization is noisy** (the crude `h3_lookahead.py` 1-ply); PUCT AVERAGING over many
    determinized sims is the fix.
  - **The policy prior MUST be scale-normalized.** First cut used the raw need-vector (~5–45) for takes vs
    `take_value` (~1–3) for buys → softmax put ~all mass on taking gems → the bot bought nothing, lost
    **0/16**. Normalizing the take score + the H3-pick anchor → 0.69+ instantly (same class as the AZ
    buy-nothing collapse).
  - **Search is the lever, empirically:** greedy H3 ≈0.5 vs panel → V+search **0.73**. The static eval alone
    saturates ~0.65 (the plateau); the gain is from SEARCH.
- **Hardening — DO NOT regress (`valuation3`):** `Valuation` captures a `(ply, phase, turn)` fingerprint at
  construction; a single inlined `assert` in `estimated_turns_remaining` (the one method every scoring path
  hits; `-O`-strippable) catches a Valuation reused after its state mutated — the lookahead/distillation
  footgun `val = Valuation(s); apply(s, a); val.<query>()` (silently mixes post-apply live state with
  pre-apply caches). The vestigial `s` param was DROPPED from `heuristic3.components`/`take_value` + all
  callers (never used; the state is `val.s`); `v_state` helpers read `val.s`.
- **Perf (behavior-preserving; profile: ~84% of search time is the V leaf):** `_cost_scalar` rewritten as one
  inlined loop (no `b(c)` closure / genexprs) = **2.75× less work**; `_delta_take` memoized per-Valuation
  (`_dt_cache`, ~**78% hit**) = 4.5× fewer `_cost_scalar` calls; `heuristic3.choose_action` accepts an
  optional `val=` and the H3-prior anchor in `vsearch` passes the leaf's Valuation (no 2nd build — 2/sim →
  1/sim — and the anchor's `take_value` sweep hits the warm cache: `_cost_scalar` 298K → 200K, a modest
  ~5–7% on top). Net ~**2–2.6× more sims/move** in timed serving; offline fixed-sims play is BYTE-IDENTICAL
  (exact-value tests in `test_h3_valuation.py` + `test_vsearch.py` gate it). The fingerprint catches
  turn-ending AND phase-transition mutations. **Profiling note:** measure throughput on a QUIET box —
  `vsearch_profile.py`'s clean sims/s is corrupted by a busy autotuner; the contention-independent truth is
  the cProfile call counts (builds/sim, `_cost_scalar` calls).
- **Perf round 2 — deployed sims-starvation diagnosed + leaf sped ~1.76× (June 2026).** Production
  serving logs (`vsearch._run_search_timed` now logs `[S] serving search: N sims in Ts (sims/s)` per move)
  showed **Render's free CPU runs ~330–450 sims/move at ~85 sims/s in the decisive midgame — ~10–11× FEWER
  than local's ~4,300 @ ~950 sims/s** (only trivial near-terminal moves spike, where most sims hit OVER
  cheaply). So the deployed S a strong human beats is badly sims-starved, NOT algorithmically weaker — and
  per the speedcurve strength climbs with sims, so the lever is leaf SPEED (no UX cost; the user declined
  raising `SERVE_TIME`). Profiling the leaf found redundant recomputation, all fixed BYTE-IDENTICAL (gated by
  the exact-value tests, 254 pass): (1) `valuation3._steps` replaces the `sorted(positives)==[1,1,1,1]` test
  in `tempo`/`_reduces_tempo` with `max==1 and count_positive==4` — killed **100% of the ~592k sorts/move**
  (the #1 self-time; +24%); (2) `_color_deficits` append-loop → walrus comprehension (drops ~1.2M appends);
  (3) `noble_progress`/`noble_completion_pts` memoized by **`(bcol, seat)`** (the 3-noble loop depends only on
  the bonus COLOR, not the card — only `noble_progress`'s time-gate `eff/(eff+W·deficit)` combine stays
  per-card via `_noble_terms`); (4) `_w_card` memoized by `(cj, bcol, seat)` (`_rtempo_cache`) — the engine
  loop recomputed `_reduces_tempo` identically for every ci sharing a color (213k→96k). Net **891 → ~1,570
  clean sims/s (1.76×)**; so deployed midgame ~380 → ~670 sims/move. A follow-up memoized **`tempo(ci,seat)`**
  (pure in (ci,seat), recomputed ~197k×/move across the noble/cost paths — caching it also kills the
  `_color_deficits`/`_steps` it spawned) and **`_cost_scalar`** by (ci,seat,extra_bcol): paired A/B ~1545 →
  ~1636 (**+6%, →1.84× cumulative**, byte-identical). That exhausted pure-Python (rounds gave +24/+24/+6% —
  tapering); the remaining hotspots are already-memoized core work + interpreter overhead → next lever is
  compilation (round 3).
- **Perf round 3 — Cython "pure-Python mode" hot leaf (~1.27× more, single source; June 2026).** The
  remaining leaf time is raw CPython interpreter overhead on the numeric loops (no redundancy left to cache).
  Compiled it with Cython — but in **pure-Python mode, NOT a separate `.pyx`** (the deliberate architecture
  choice): the hot functions in `valuation3.py` (`_cost_scalar`/`_color_deficits`/`_steps`/`_reduces_tempo`)
  carry `cython.*` type annotations that are **inert under CPython** (`from __future__ import annotations`
  makes them strings; nothing is evaluated, and `import cython` is guarded → no runtime dep) and become a
  **typed C extension when Cython compiles the module**. ONE source of truth — no duplicated logic, no parity
  test to maintain (a separate `.pyx` was prototyped first — 8.7× on `cost_scalar`, 1.25× end-to-end — then
  discarded for the single-source pure-mode form, which matched it). **Serving = the compiled `valuation3.so`
  shadows the `.py`** (extension > source in import priority); **local dev / any box without a C compiler runs
  the `.py` unchanged** (byte-identical fallback).
  - **Build wiring (`games/spender/Dockerfile`):** the *builder* stage `pip install cython` + `cythonize -i -3
    games/spender/ai/az/valuation3.py`; the slim *runtime* `COPY --from=builder` the `.so` in next to the
    `.py`, then a **build GATE** — `RUN python -m pytest test_h3_valuation test_vsearch` against the COMPILED
    module — so a Cython miscompile fails the image build and can never reach prod (a failed build just leaves
    the previous image serving; the site can't break from this). Shared by the wwsd service too (same
    Dockerfile). `.gitignore`/`.dockerignore` keep the generated `.c`/`.so`/`build/` out of git + context.
  - **Validated in a `python:3.11` container (= prod):** compiled **2114 vs uncompiled 1666 clean sims/s
    (~1.27×)**, 24 exact-value tests pass compiled. Cumulative session ≈ **2.3×** (1.84 × 1.27); Render midgame
    ~380 → ~870 sims/move.
  - **Build env reality:** the dev box (Windows / Python 3.14) has **no C compiler**, so this is built +
    validated in Docker (`python:3.11`, matches prod). There is **no runtime kill-switch** anymore (pure-mode
    has no `if _FV` branch — it's compiled or not at build time); the byte-identical guarantee is the
    build-gate tests, not a flag.
  - **The ceiling — DO NOT relitigate the deeper Cython without a strong reason.** Pure-mode annotations got
    ~most of what this code can give: the whole module compiling is the baseline gain, typed loops add the
    rest. Going to the targeted **2–3×** would need (a) making `Valuation` a **`@cython.cclass`** (cdef
    methods/typed attrs) to kill the now-dominant **method-dispatch + dict-cache** overhead — a big, risky
    rewrite of a 1,000-line cached class — AND (b) Cythonizing `mcts.py`/`engine.py`, because **~15–25% of
    per-sim time (determinize / `_select` / `clone` / `legal_actions`) lives OUTSIDE `valuation3`** — a hard
    ceiling on any leaf-only effort. Judged poor effort/risk/reward vs the 2.3× already banked + diminishing
    sim-returns; **stopped at the leaf.** **(SUPERSEDED IN PART — see Perf round 4: the deeper typed-C-array
    rewrite of the `engine_value` CHAIN (short of the full cclass) WAS done on branch `cython-perf`,
    byte-identical, ~1.85–2.74×. The `@cython.cclass` Valuation + mcts/engine port is still deferred.)**
- **Perf round 4 — typed-C-array rewrite of the `engine_value` chain (branch `cython-perf`, NOT merged; June 2026).**
  Round 3's pure-mode annotations only typed loop COUNTERS — the DATA (`s.bonuses[seat]`, `E.COST[ci]`) stayed
  PyObject lists/tuples, so a naive recompile of the deeper chain was **~1.0× (measured 13.1 vs 12.7 s/game)**.
  The win needs the data in **C arrays** + collapsing the per-card scoring so it crosses the Python boundary ONCE
  per call instead of thousands of times. Done in the SAME single-source pure-mode `.py` (composes with round 3):
  - **Module-level C tables** `COST_C[90][5]`/`BONUS_C[90]`/`PTS_C[90]` filled at import inside `if cython.compiled`
    (gotcha: Cython REVERSES array dims — `cython.int[5][90]` emits C `int[90][5]`; declaring it un-flipped is a
    silent OOB write). **cdef helpers** `_steps_c`/`_reduces_tempo_c`/`_cost_scalar_c`/`_color_deficits_c`/`_eng_base_c`
    (`int*`/`double` C signatures, no PyObject) carry the leaf math.
  - **`_engine_value_h3_c`** inlines the WHOLE H3 `engine_value`
    (delta_take→potential→eng_base→w_card→reduces_tempo→cost_scalar) in C over C arrays with **NO sub-call caches** —
    recompute is byte-identical because every memoized helper is a deterministic pure function. Also converted: the
    `components` cost vector (`tempo`/`gem_cost`/`gold_cost`), the per-Valuation `deck_color_demand` `__init__` loop,
    and `noble_progress` (`_noble_progress_c`).
  - **Every C path is gated `cython.compiled and ci < 90`** so the unchanged Python path still serves the
    synthetic-card unit tests (which append cards past the 90-deck) and any non-deployed flag config; nobles read the
    **LIVE `E.NOBLE_REQ`** (tests replace it) not a frozen table; tuning constants are read **LIVE per call** (NOT
    frozen into C globals) so the offline autotuners can still sweep them.
  - **GOTCHA — a genexpr in the same function scope as a `cython.declare(C-array)` breaks Cython codegen**
    (`GeneratorExpressionScope` error): the C-path functions are genexpr-free (pure fallbacks rewritten without
    `sum(... for ...)`); int/int closeness divisions forced to double via `1.0 *`.
  - **Results — byte-identical (60-game S self-play differential parity char-identical + 32 unit tests, compiled AND
    pure):** engine_value alone **1.49×**, +cost vector **1.85×**, +init/noble **2.74×** (cumulative). The ratio is
    LOAD-dependent (the local box's 11-core tuning job fluctuated): the **compiled path is contention-STABLE at
    ~2.66 s/game** while pure swings 4.9–7.3 — so ~1.85× on an idle box, ~2.74× on a busy one, and compiled is far
    more robust to a loaded CPU (the Render shared-core scenario).
  - **Built + validated LOCALLY** (the dev box now has MSVC + cython 3.2.5; Python 3.14 →
    `valuation3.cp314-win_amd64.pyd`) AND in a **`python:3.11` Docker build** matching prod (cython==3.2.5 manylinux
    wheel, cythonize under cp311+gcc → `COST_C[90][5]` identical, the line-39 gate `32 passed` on the cp311 `.so`).
    **No Dockerfile change beyond pinning** `cython==3.2.5` (the builder already `cythonize`s `valuation3.py` + gates
    on `test_h3_valuation`/`test_vsearch`, so this ships automatically). To fold into `heuristics`/main the
    engine_value chain is unchanged between branches, so it applies cleanly. **Still deferred:** the `@cython.cclass`
    Valuation + Cythonizing `mcts.py`/`engine.py` (the ~15–25% per-sim time OUTSIDE valuation3 — the hard ceiling
    on any leaf-only effort).
- **Tooling** (offline, parallel): `vsearch_camp.py` (panel A/B, CRN, Wilson CIs), `vsearch_autotune.py`
  (coordinate descent, **MAXIMIN objective over {H3,H2,H2N,H2R}** — maximize the WORST matchup, mean only as a
  tie-break (`MEAN_EPS`), with larger screen/holdout N since the min is a noisier statistic. Switched FROM
  panel-mean after the mean run found ZERO adoptions on the disjoint holdout — i.e. the hand-set V weights are
  already near-optimal, confirming "weight-tuning saturates"; vs-H3 (~0.635 @ sims=120) is the lone weakness
  maximin targets), `v_state_eval.py` (sign(V) win-prediction discrimination vs the ~0.65 plateau),
  `vsearch_profile.py` (clean wall-clock + cProfile), `h3l_probe.py` (the static-vs-rollout probe). Tests:
  `games/spender/tests/test_vsearch.py`.
- **THREE-WAY diagnostic (RUN, June 2026) → Path C favored.** `v_state_eval.py --teacher S` plays S-vs-S
  (search-driven) and at every PLAY snapshot records {static V, search-backed root value `sum(W)/sum(N)`,
  eventual outcome} from the mover's perspective, then compares each eval's AUC/Brier vs outcome. The
  decisive question was whether the search-over-leaf advantage GROWS with depth. It does — sweep at
  sims=128/384/768 (240 S-vs-S games each, ~13k snapshots):
  | sims | V_static AUC | V_search AUC | dAUC | agree corr |
  |------|------|------|------|------|
  | 128 | 0.642 | 0.680 | +0.038 | 0.822 |
  | 384 | 0.688 | 0.737 | +0.049 | 0.811 |
  | 768 | 0.645 | 0.700 | +0.055 | 0.789 |
  Three concordant trends: **dAUC grows, Brier gap widens, agreement falls** as search deepens — deeper search
  increasingly diverges from AND outperforms the leaf. The leaf AUC ~0.64 sits exactly on the documented
  static plateau (re-confirmed now against STRONG S-vs-S labels, not H3-level) → **re-weighting V is dead**.
  Only the WITHIN-row paired dAUC is a clean comparison (each sims row plays a different game set, so absolute
  AUCs wobble); all three deltas move the same way → trust the trend. Verdict: **Path C (distill V+search →
  numpy net → deeper search) is the lever.** **Do NOT re-tune V on self-play OUTCOMES as the objective** — a
  mirror match is ~0.5 (no gradient) and reintroduces single-strategy-collapse / denial-blind risks; the
  style-diverse MAXIMIN panel stays the arbiter. (For the framing/decomposition that designed this test —
  static-V-vs-outcome = "biased leaf?" vs static-V-vs-searchV = "needs depth?", and why you need the outcome
  as a third anchor since searchV inherits the leaf's bias — see git history of this section.)
- **Take-pruning of dominated gem-takes — TESTED & REJECTED (wash; do not relitigate).** The engine offers
  take-2-different / take-1 even when a superset take-3 is available; under the token cap these are weakly
  dominated. A search-local prune (`legal_fn` hook on `Search` + a `_search_legal` that drops them when total
  tokens ≤7) was sound in theory but **panel A/B was an exact wash (0.8104 = 0.8104)**, with a noise-level
  per-opp wobble that if anything nudged the worst matchup (vs-H3) down. Reason: the **policy prior already
  soft-prunes** them (low `take_value`/need → ~0 prior → ~0 visits), so explicit pruning frees no sims.
  Reverted. (At 8/9 tokens take-fewer is genuinely distinct anyway; the equivalence "take-3 then discard the
  just-taken gem ≡ take-2D" holds only in the search's model, and serving executes that discard via greedy H3,
  not search — a separate reason not to lean on it.)
- **Mixmax / pessimistic backup — TESTED & REJECTED (do not relitigate; June 2026).** The user's intuition
  "assume the opponent plays at least somewhat well" → blend each edge's diluted mean Q with the best reply
  one ply down (`mcts.Search(backup_lambda=L)`, `vsearch.BACKUP_LAMBDA`, parked default-0 = byte-identical;
  the best-reply Q is averaged over determinizations so it pessimizes over DECISIONS not deck luck — correct
  ISMCTS). **Self-gate vs FROZEN today's-S (paired CRN, the sharp instrument) showed a clean MONOTONIC
  degradation:** lam=0.15/0.3/0.5 → 0.481/0.463/0.383 on the same seed base (lam=0.5 ~4 SE below 0.5). A lone
  fresh-seed 0.520 for lam=0.15 contradicted its own 0.481 screen (regression-to-mean noise ~0.5); the panel
  +0.046-min is the documented weak/noisy discriminator (~1.2 SE, different game set) — not ship-grade. The
  negative slope matches the **maximization bias** (the max is over noisy 1-visit grandchildren → over-estimates
  the opponent's best reply → over-pessimism that grows with lam). A min-visit guard on the max could debias it
  but was not pursued (the naive monotonic-negative result + the strong prior make a small-lam rescue unlikely).
  Confirms again: the static eval is **already used near-optimally by the plain averaging backup** — re-shaping
  *how* the leaf is aggregated in PUCT washes, same as re-shaping the leaf itself. Tooling: `backup_lambda_ab.py`
  (focused self-gate: screen → fresh disjoint-seed → panel RPS guard for the one knob).
- **Search exploration breadth — TESTED & REJECTED (wash; do not relitigate; June 2026).** Hypothesis
  (from a human who still beats S): "S never CONSIDERS the move that beats me" → widen the policy prior so
  PUCT visits moves H3 dislikes. Two mechanisms, both parked default-off byte-identical: `vsearch.PRIOR_UNIFORM`
  (mix uniform mass: `P=(1-u)*softmax + u/n`, the REAL floor) and `POLICY_TEMP`↑ (flatten the H3 prior).
  **Discovery: the existing `PRIOR_BASE=0.1` is a VESTIGIAL no-op** — it's added to EVERY action's score so it
  cancels in the softmax (softmax is shift-invariant). Self-gate vs frozen-S at sims=200: `PRIOR_UNIFORM`
  0.1/0.25 screened 0.546/0.538 but 0.1 fell to **0.494 on FRESH disjoint seeds** (regression to mean),
  `POLICY_TEMP=1.0` = 0.496, panel a slight wash. **No gain because `mcts._select`'s `_EPS_PRIOR=1e-3` floor +
  PUCT's `sqrt(N)/(1+n)` term ALREADY make every legal move get visited** — dark moves are NOT starved; S sees
  them, evaluates them, and correctly doesn't prefer them at the depth it searches. So the human-exploitable
  gap is **eval-depth/search-budget, not exploration breadth** (and widening breadth at the LOW sims the
  deployed Render CPU runs would only spread the budget thinner). Re-confirms the two remaining live levers:
  search DEPTH (needs a faster leaf/engine → more sims) and the production sim budget. Tooling:
  `config_selfgate.py` (generic config-vs-frozen self-gate, screen → fresh → panel guard).
- **Search-efficiency / "fewer sims needed" (sharper prior) — REAL low-sims effect, but NOT shippable; do
  not relitigate (June 2026).** Idea: a sharper prior concentrates visits faster, so the deployed sims-starved
  S plays better at a fixed (small) budget. Self-gate vs frozen-S **at sims=80** (below the original
  sims=120–160 tuning regime) found **`C_PUCT=1.0` (less exploration) beats the current 1.5**: fresh-seed
  0.531 (consistent with its 0.563 screen) AND panel **+0.025 min, up on all four matchups** (RPS-clean) — a
  genuine, non-artifact win that confirms the principle (when sims are scarce, commit faster). `POLICY_TEMP=0.5`
  (0.49) and `H3_PICK_W=2.5` (0.44) failed even at 80 — it's specifically PUCT exploration, not prior shape.
  **But it's a LOW-SIMS-ONLY win below the deployed operating point:** the maximin tuning already found
  `C_PUCT=1.5` optimal at sims=120–160 and transferring to 400, so there's a **crossover ~80–160**, and the
  deployed box runs ~380 midgame sims (more after Cython) — well above it. Shipping `1.0` globally would help
  only rare very-low-sim moves and HURT the typical midgame → net neutral-to-negative for deployed. The only
  way to capture it is a **sim-budget-conditional `C_PUCT`** (sims unknown until after the search, box speed
  varies — too fiddly for a sub-significant edge). **Verdict: keep `C_PUCT=1.5`; search-efficiency tuning
  saturates at the operating point too.** Transposition caching was dismissed un-tested (determinization
  reshuffles boards per sim → near-zero exact-state hit rate in Splendor's wide state space). Tooling:
  `config_selfgate.py --sims N`.
- **Path C (distill V+search → numpy net) PROTOTYPED & the bottleneck PINNED to FEATURES, not arch (June
  2026).** Tooling: `vsearch_distill.py` (harvest `(features, V_static, V_search, outcome)` from S-vs-S +
  ridge/MLP distill, with a `--enriched` mode + `--cache`), `attn_distill.py` (card-set attention pre-check on
  the cache). Findings, all measured on ~33k S-vs-S snapshots @ sims=384 (leaf AUC ~0.69, search target ~0.74):
  - **Cheap-feature distillation STALLS.** ridge/MLP/**card-attention** all cap **AUC ~0.65–0.67** predicting
    V_search — *below* the leaf, far below the search target. Not validated.
  - **It's a FEATURE-information bottleneck, not architecture.** Targeting V_static, models REPRODUCE the leaf
    at **corr ~0.91** yet still cap AUC ~0.66; the ceiling is the SAME (~0.66) whether the target is V_search or
    V_static → the limit is what the 305 encoder *contains*. **Attention ≈ linear** here (no arch advantage)
    because neither has the inputs: the encoder omits the leaf's derived terms — **turns-remaining horizon,
    deck composition/per-color demand, engine/reachability/potential**. This is the truer cause of variant Z's
    plateau: Z trained on these same lossy features → capped ~0.65 *before architecture mattered*. (Bug noted:
    the attention pre-check first looked negative because per-card tokens lacked the mover's bonuses — fixed by
    injecting them; still capped, confirming features not arch.)
  - **Redirect → ENRICH THE ENCODER** (the #1 pre-retrain adjustment). Feed the net the leaf's own derived
    terms (base 305 + per-board-card H3 `(take,engine,point,cost)` + `v_state` component breakdown + turns).
    Costs ~leaf-level compute (so NOT the Path-C "100× cheaper for deeper search" bet — the retrain chases
    STRENGTH, not speed). **Pre-check RESULT (RUN, `--enriched`, same 600-game/sims384 harvest): enrichment
    UNBLOCKS it — direction validated.** On THIS test set (leaf 0.670, search target 0.717): ridge **0.694**,
    MLP 0.681 — both now ABOVE the leaf (on base features NOTHING beat it), capturing **51% of the search-vs-leaf
    gap**; ridge's fit to V_search jumped corr 0.76→0.85. So a *learnable* eval can beat the hand-leaf once the
    features carry its terms. Caveats: magnitude is modest (+0.024 linear; the other ~49% of the gap is pure
    lookahead no static eval recovers — search on the better leaf reclaims it), and the harness MLP is still
    undertrained (< ridge — a regularization/early-stop issue, NOT capacity), so the true NET ceiling is likely
    higher, and the per-card-terms-in-attention-tokens test (not yet run on enriched) should push further.
    Verdict: **retrain green light, with bounded-but-real upside.**
  - **The retrain decision (locked direction):** if green, it's an AlphaZero retrain with (a) **enriched
    encoder** [feature set must be locked BEFORE start — input-dim change = full restart], (b) **card-set
    attention** value+policy heads, (c) **bootstrap by distilling S's (V_search value, MCTS visit-policy)** so
    self-play starts competent — NOT from-scratch (every from-scratch/flat-feature net LOST to the heuristics).
    Reuse the built shaping/league/curriculum. Verify a numpy-export path for attention before committing, and
    consider a C/Cython engine first (self-play game-gen is the wall-clock sink). `distill_cache*.npz` are
    gitignored scratch.
- **DEPLOYED + MAXIMIN-TUNED (June 2026):** shipped to `main` (variant S = `da18bab`; maximin config =
  `31bbfbd`). The maximin `vsearch_autotune` pass-0 adopted exactly two knobs — **`W_ENGINE_STK` 0.8→0.4**
  (`v_state.py`) and **`C_PUCT` 2.0→1.5** (`vsearch.py`) — confirmed on DISJOINT fresh seeds (N=360, sims=120):
  worst-matchup **min 0.664→0.750**, mean 0.729→0.777, every panel matchup up; validated at higher sims via the
  panel-vs-sims speedcurve (min 0.812 / vs-H3 0.875 at sims=800). The bigger lever was `C_PUCT` (a SEARCH knob,
  not a leaf weight) — consistent with "search is the lever." We stopped the autotuner after pass 0 (a watcher
  tree-killed it at the first `[p1]`); pass-1+ gains are marginal. Speedcurve also showed raw-sims strength
  still climbing but with **diminishing returns** by 400–800 sims (S@hi-vs-S@lo adjacent doublings ~0.5–0.59;
  8× span 0.73) → speed micro-opts give modest gains; leaf quality is the bigger lever.
- **Behavioral audit + self-gate campaign (June 2026):**
  - **Over-reserve — TESTED & REJECTED (don't relitigate).** `blunder_finder.py` found S reserves ~4.3×
    greedy H3 (12.6% of moves vs 2.9%, ~56% never bought) — an EVAL bias (a deep search AMPLIFIES it → the
    leaf over-values reserving, not a shallow-search artifact). BUT the **human playtest** verdict was
    "reserves mostly GOOD, only slightly excessive," and a new `v_state.RESERVE_PENALTY` knob (default 0 =
    byte-identical) at 0.3 **HURT the worst matchup** (vs-H3 min 0.785→0.745) for no avg gain → the reserves
    are tactically useful (denial/securing vs the racing H3); "wasted at game-end" ≠ a blunder. **Keep
    `RESERVE_PENALTY=0`.** The self-gate later re-rejected it independently (screened ≤0.50 vs frozen-S).
    Lesson: win-rate-vs-a-beatable-panel is blind to behavioral biases, and so is self-play *mirror* (both
    sides share them) — only a behavioral audit vs a non-sharing reference (H3) + a human caught it, and you
    need the fix-knob to EXIST and an *asymmetric* comparison that varies that axis to tune it.
  - **Policy head — ruled out.** `policy_precheck.py`: the H3 policy prior already matches the search's
    top move ~86% (the learned net underperformed it, undertrained) → little room. Low priority.
  - **Self-gate autotuner `vsearch_selfgate.py` (tune vs a STRONG opponent) — paid off.** Candidate config
    vs FROZEN today's-S (NOT the weak panel), **paired CRN**: each board is played both first-player ways
    with `vsearch._RNG` reset, so `cand==frozen` scores EXACTLY 0.5 (unbiased + race-free; `engine.new_game`
    always makes seat 0 first, so the pairing is what balances first-player). Found **`W_PROGRESS` 1.5→2.5**
    that the maximin run (judged on the beatable panel's MIN) had missed: vs-frozen **+0.024** (fresh N=200)
    AND panel avg 0.766→0.797 / **min 0.741→0.778 (+0.037)**, RPS-clean (objectively stronger). Confirms the
    user's thesis: weak-panel tuning saturates; a strong equal opponent sharpens the gradient. All other
    knobs (incl. RESERVE_PENALTY) held. **SHIPPED (on main):** the sims=400 panel confirm HELD — avg
    0.8125→0.8262, **min not worse** (H3 .770→.772; only H2N −.013, within ±.029 noise) — so `v_state.py`
    now has `W_PROGRESS=2.5` deployed (variant S). Tuned at sims=160, confirmed it transfers up to 400.
  - **Turns-remaining estimator — TESTED, NO CHANGE (don't relitigate).** Hypothesis: `turns_table.json` (the
    horizon, measured from H3-vs-H2) is mis-calibrated for the far-stronger S, inflating the horizon-gated
    terms (`_engine_stock`/`_noble_stand`/noble time-gate) and feeding the over-reserve. **Both fixes failed.**
    (1) Re-measuring the table from **S-vs-S** play (`s_measure_turns.py`, 320 games @ sims=128) gives a table
    essentially IDENTICAL to the H3 one: count-weighted mean(S − H3) = **−0.020 turns**, and even the start
    cell (0,0,0) matches (26.35 vs 26.28). The table keys on the **game STATE** (cards/points/gems), which
    already encodes progress, so turns-to-finish from a fixed state is ~play-quality-invariant — a stronger
    player REACHES good states sooner but the trajectory FROM a state is the same (so the docstring's
    "self-referential" caveat is genuinely mild). (2) A board-CONDITIONAL greedy **turns-to-win planner**
    (`valuation3._planner_turns_seat`, behind `TURNS_MODE`, default off) is a WORSE turns predictor (corr
    0.946 vs the table's 0.981; MAE 2.21 vs 1.30) AND makes S weaker in the A/B (`turns_ab.py`): **0.469 vs
    frozen-S**, panel avg 0.720 vs 0.783. Board composition barely moves turns-left once points-needed is
    known. **Keep `TURNS_MODE="table"`.** The planner/`table_s` machinery is parked default-off (byte-identical).
    `s_measure_turns.py` (also reusable for the 21-point turns re-measure) + `turns_ab.py` are committed tooling;
    `turns_table_s.json` + the `.out` logs are gitignored scratch. (3) The KEY-lossiness follow-up (the user's
    sharper point — the key is RESERVE-BLIND, and H3 barely reserves while S reserves constantly): `turns_feat_diag.py`
    confirms reserved-count carries **real** omitted signal — holding a reserve correlates with ~**−0.72 turns**
    left (monotonic residual −0.35/−0.86/−1.40 at 1/2/3+ reserves) — so the table genuinely over-estimates the
    horizon in S's reserve-heavy states (your hypothesis was directionally CORRECT). BUT correcting it
    (`valuation3.RESERVE_TURN_ADJ`, subtract turns/reserve, default 0) is a **WASH for PLAY**: vs frozen-S the
    head-to-head is 0.527/0.510/0.517 at adj 0.4/0.7/1.0 (all CIs cross 0.50) and the panel is non-monotonic
    (noise). It doesn't convert because the horizon scales only the SECONDARY engine/noble standing terms;
    points/progress dominate move-choice, so a sub-turn horizon shift barely moves it (aggregate dR²=+0.0024).
    **Gold weighting is NOT supported either** — controlling for reserves, gold advances you LESS per token than
    a colored gem (coef −0.20 vs −0.41); its raw effect was just reserve-correlation. **Keep `RESERVE_TURN_ADJ=0`.**
    Net lesson: R² gain ≠ strength; the turns horizon is not a strength lever for S (3 independent washes).
  - **Net retrain / learnable-leaf path — EXHAUSTED, beats nothing (DO NOT relitigate).** A pre-retrain
    derisking sweep (offline scripts: `distill_features.py`/`distill_fit.py`/`leaf_ab.py`, `bootstrap_harvest.py`/
    `bootstrap_train.py`/`net_vs_s.py`, `policy_arch_test.py`) tested every lever a learned net could give S.
    **Six converging negatives:** (a) **leaf-swap** — an enriched ridge leaf distilled toward V_search (held-out
    AUC 0.718 vs the static leaf's 0.670) made S only **0.534** vs frozen-S (n.s.), panel wash → a sharper static
    leaf does NOT convert through search. (b) **base-feature bootstrap** — a net distilled from S (value+policy)
    scored **0.042** vs S (near-uniform policy CE 2.67). (c) **enriched bootstrap** — value sharp (MSE 0.027),
    policy lifted to 0.52 top-1 but still **0.315** vs S. (d) **structured/per-card policy head** — 0.554 top-1 ≈
    flat 0.535, both ≪ the H3 prior's **0.86**. The wall is NOT features or architecture: **S's search move ≈
    H3's greedy move 86%, and predicting it essentially requires recomputing H3** — any net is a lossy
    approximation (~0.55). So the best static policy IS the H3 prior, which **S already uses**; "H3 prior + net
    value" just rebuilds ≈ S. Combined with "better value doesn't convert," **no net configuration beats S.**
    The only untested path is self-play discovering a >H3 policy from the 0.315 enriched bootstrap, but the net
    represents policies at ~0.55 fidelity and base-feature self-play already capped sub-S (variant Z) → low odds,
    not pursued. **Conclusion: S is at the ceiling of the heuristic+search approach; the learnable-net path can't
    surpass it.** (Reusable byproduct kept on main: `league.py`/`train_az.py` now accept **`S` as a league/gate
    opponent** via `--heur-variants S` + `--opp-s-sims`; `vsearch.LEAF_MODE`/`net.SpenderNet(in_features=)` are
    byte-identical-default. `*cache*.npz`/`leaf_model.npz`/`checkpoints_bootstrap*` are gitignored scratch.)
- **21-point "Long" mode — LIVE + specialized.** Per-game `win_points` (default 15) is wired through the
  engine, production rules (`main._win_points`), and the AI stack (v_state convex zone, `victory_closeness`,
  heuristic3 win-checks all read `s.win_points`); the lobby has a **Classic 15 / Long 21** toggle threading
  `win_points` into `create`. **Any picked AI auto-adapts to 21** (no separate variant needed). Shipped 836ad6d
  (Phase 1) + 567e5d8 (toggle); byte-identical for Classic.
  - **Lobby UX follow-ups (June 2026):** the toggle was reworked to a segmented `.length-toggle`/`.len-btn`
    whose selected state changes ONLY background+color (fixed border/padding) — the old `.mode-toggle`
    swapped `btn-outline`↔`btn-gold` whose borders differ, which **shifted the page on select**. The toggle
    now ALSO **filters the Open Games list** to the selected length (`openGames.filter(g => (g.win_points||15)
    === winPoints)`; `list_open_games` parses `win_points` out of `state_json` and returns it). In-game, a
    "**Target: N**" label sits above the hint (`.hint-col` wraps target+hint in the desktop actions-panel; an
    inline `.target-label` in the mobile action-bar), reading `game.win_points || 15`. Create button is just
    "+ Create Game" (length comes from the toggle).
  - **The genuine specialization is STRUCTURAL (done):** (1) the convex near-win zone auto-shifts to the last 5
    of `win_points` (→16 at 21); (2) **`turns_table_21.json`** — a 21-point-MEASURED horizon table, auto-loaded
    by valuation3 when `s.win_points==21` (the 15-table under-counts the 21 horizon by ~3.8 turns — a real
    structural gap, unlike the player-strength recalibration which was a wash). S-at-21 beats the heuristic
    panel ~0.76 (H3 .70 / H2 .82 / H2N .70 / H2R .81).
  - **Weight retune — NO honest change (don't relitigate).** The self-gate at `--win-points 21` (vs frozen-S-at-21)
    adopted `W_ENGINE_STK 0.4→0.2` on the reused per-knob holdout (0.529), but it **failed the fresh disjoint-seed
    re-measurement (0.4979, below 0.50) AND the RPS guard** (worse vs H3) → a holdout artifact, not adopted.
    Everything else screened-high-but-failed-holdout (W_ECON 0.637, W_POINTS 0.575, W_PROGRESS 2.0). So
    **`vsearch_s21.json` is empty** → S21 = S's 15-weights + the structural 21-adaptations. Serving:
    `_s_choose_move` applies any S21 overrides under `_S21_LOCK` only on `win_points==21` (empty config = no-op,
    byte-identical). Harnesses gained `--win-points` (`s_measure_turns`/`vsearch_camp`/`vsearch_selfgate`).
- **Endgame & multi-noble experiments (June 2026) — default-off knobs, committed LOCALLY (`2c27b14`,
  `2da6e4d`), NOT pushed; under test.** Three structural ideas (a human still beats S in their own games),
  each byte-identical at its default and unit-tested (`test_vsearch.py`):
  - **Gap A — `v_state.ENDGAME_TIEBREAK_W` (tiebreak awareness)**: a CROSS-seat leaf term (added in the value
    diff `value_with`/`components`, NOT per-seat STAND) that — gated to near-win + near-tie + differing card
    counts — nudges toward the pts→fewest-cards tiebreak. **DEAD:** wash at sims=160 (0.500/0.502), wash→NEGATIVE
    at sims=500 (0.02=0.500, 0.06=0.465). As predicted: the leaf tiebreak only helps when search MISSES
    terminals, which happens LESS at higher sims (a true terminal already returns the engine's exact
    tiebreak-aware win/loss). Reject. Don't relitigate.
  - **Gap B — `vsearch.ENDGAME_SIM_MULT` / `ENDGAME_SERVE_TIME` (deeper final-round search)**: spend more
    search once `final_trigger>=0` or a seat is within `ENDGAME_NEAR=3` of the win (offline sim multiplier /
    longer serving wall-clock; `_is_endgame`). **Faint wash:** ~0.51-0.53 screen (160 and 500), never clears
    the +0.02 holdout bar, no panel gain. The endgame is too few moves + already near sim-saturation to pay.
  - **Multi-noble — `v_state.NOBLE_MULTI_W`** (the USER's idea): `_noble_stand` counted only the single best
    noble (max over 3); W>0 adds `W*(sum of the OTHER nobles' time-gated standings)` so a position advancing
    2-3 nobles outscores one advancing 1. (Per-card `valuation3.noble_progress` ALREADY rewards multi-noble
    cards via its n-normalized sum; this is its POSITION-eval counterpart, the real gap.) **Implemented +
    unit-tested, NOT YET RUN** (queued behind the sims=500 autotune; don't oversubscribe cores). **Strong
    real-game evidence (a 15-10 loss to a human):** S piled red4/black4 (enough for its one noble n6, +1 spare
    each) but left blue at 2 → finished EXACTLY one blue short of a 2nd noble (n9 = g3/b3/r3), while the human
    balanced w3 b3 g3 r3 and claimed TWO nobles (6 vs 3 = the game's whole margin). The max-over-nobles leaf
    gave S no gradient to balance. **Most promising of the three** — test sims=160 screen → sims=500 confirm.
  - Tooling: `vsearch_selfgate` gained the endgame + `NOBLE_MULTI_W` knobs (finer search-knob grids) + a
    `--knobs` subset filter (full set intact for future full tunes); `config_selfgate._PROBE_KEYS` pins them.
- **sims=500 self-gate autotune (endgame + search knobs) — IN PROGRESS.** Run at the PROD operating point —
  the user flagged that sims=160 tuning may not transfer to prod's ~600 (valid: the documented C_PUCT crossover).
  Screen 240 g/candidate, holdout 600 (CI ±0.04). Interim findings (stable): **`C_PUCT=1.5` confirmed optimal
  at sims=500 — NO crossover above 160** (every alt screens <0.5; the 1.0-best crossover is below ~120 only);
  tiebreak dead; sim-mult faint wash; one **borderline `H3_PICK_W` 1.5→2.0 adoption (holdout 0.524, barely over
  the +0.02 bar; its screen was 0.467 → screen↔holdout inconsistency ⇒ likely noise, and sharper-prior is the
  documented don't-survive family)** pending the final fresh-seed + panel RPS arbiter.
- **Open / next:** finish the sims=500 autotune (treat the H3_PICK_W adoption skeptically — confirm or reject
  via fresh + panel); then run `NOBLE_MULTI_W`. The proven lever remains search DEPTH (sims throughput), not
  eval re-weighting (re-confirmed: every endgame/search re-weight washed at the prod operating point). Parked:
  "search owns DISCARD/NOBLE + a discard prior" (low gain).

### Session (late June 2026) — metric directive, NOBLE_SCALE 3.5, Cython rewrite (ON MAIN), weakness audit

**TUNING METRIC DIRECTIVE (user instruction — SUPERSEDES the MAXIMIN {H3,H2,H2N,H2R} panel described above).**
Judge AI tuning ONLY by **S vs frozen-S** (the self-gate; primary), with **H3 / H3N / H3R** as a strong secondary
sanity panel. **NEVER report or weight H2 / H2N / H2R again** — too weak; weighting them gave misleading verdicts
(e.g. the lower-`NOBLE_SCALE` "wash" was an H2N artifact). H3N = `_AggrH3(2.0)` (noble-heavy), H3R = `_AggrH3(0.4)`
(rusher), built fixed-base off the committed `NOBLE_SCALE` so they don't drift with the candidate;
`config_selfgate.PANEL=["H3","H3N","H3R"]`. These opponents + the rejected-experiment flags below are currently
**UNCOMMITTED on the `heuristics` worktree** (pending a selective finalize), not yet on main. Mirror in memory
`spender-tuning-metric-s-selfgate`.

**NOBLE_SCALE 5.0 -> 3.5 -> 3.0 — SHIPPED (3.5 on `15717fe`; 3.0 on current commit).** Lower-noble S-vs-frozen-S sweep (sims=400, N=350) was a
wash on the self-gate (3.5 fresh 0.516; all values' CIs straddle 0.5); shipped on the user's call (faint-positive
self-gate + H3 +0.025). Affects BOTH H3 and S. COUNTERINTUITIVE H3-panel trade: lower noble HELPS vs a noble-player
(H3N +0.068) and HURTS vs a racer (H3R -0.050) — a racer leaves S's nobles UNCONTESTED, so nobles are an edge vs
racers; the change is matchup-lopsided, not a clean gain. (Supersedes the "3.0->5.0" note above.)

**Cython `engine_value` rewrite — ON MAIN (`f82cc79`, ~1.85-2.74x).** `valuation3.py`'s engine_value chain
(`engine_value`/`_delta_take`/`_cost_scalar` + cost/deficit primitives) is typed-Cython on C int arrays (static
`E.COST/BONUS/PTS` -> module C arrays; per-state bonuses/tokens extracted per call). **Single-source, runs three
ways** (verified): pure Python with cython ABSENT (an `ImportError` shim no-ops the type/decorator constructs;
C-array blocks gated on `cython.compiled`), pure Python with cython installed, and the compiled `.so`/`.pyd` (fast).
The **Dockerfile multi-stage-compiles it** (builder `cythonize` -> `.so`; slim runtime carries only the `.so`; build
FAILS on miscompile, so a bad compile can't reach prod) — so merging the `.py` is enough; prod builds its own Linux
`.so`. Gated byte-identical by the exact-value tests + a differential-parity check. PyPy was tried + REJECTED (slower
+ not bit-parity — numpy in the search hot path goes via cpyext). To prototype eval ideas, hack the readable
pre-Cython `valuation3.py` from git history, then re-Cythonize only the winner.

**Rejected this session (DO NOT relitigate — all judged by S-vs-frozen-S; flags default-off / byte-identical,
uncommitted on `heuristics`):** endgame tiebreak (`ENDGAME_TIEBREAK_W`) + deeper-final-round sims
(`ENDGAME_SIM_MULT`) = noise; the sims=500 autotune's `H3_PICK_W`/`POLICY_TEMP` adopts = noise ratchet (0.480 fresh);
multi-noble position term (`NOBLE_MULTI_W`) = inert; per-card overlap reward (`NOBLE_COUNT_W`) = behaviorally ==
pure magnitude; supply-aware noble gate (`SUPPLY_PENALTY`) = cuts a late-buy "blunder" rate ~11% but washes
win-rate. Re-confirms eval re-weighting is saturated UP **and** DOWN; the lever is search / eval-class, not weights.

**Weakness audit (7 user wins vs S over 4 days, queried straight from the Turso prod DB).** S wins the large
majority vs the user; the losses share ONE dominant cause — **S races too slow / inefficiently**: ~0.75 pts/card
(avg 16 cards, ~12 of them 0-point, ~12 pts) vs the human's ~1.16 (efficient point-cards); the user reaches the win
first in 6/7. Secondary: over-reserve (4/7 end with an unbought 3+pt L3) and a horizon-1 **endgame-denial blind
spot** (1/7, game `IYGWJQ` — `_deny`/`_opp_best_buy` only catch a NEXT-TURN opponent win, missing a 2-turn
reserve-then-buy threat). This cluster is **human-exploitable but tuning-resistant** — S beats the synthetic racers
(81.5% vs H3R) *because* they don't punish it, which is why every weight experiment washed while the human keeps
winning. **QUEUED fix:** a 2-turn endgame-denial horizon (extend `_opp_best_buy`/`_deny`/`_secure_win`; `IYGWJQ` is
the regression test). The deeper "race efficiently" fix is the documented hard lever (search / net).

**Querying the prod DB directly:** Turso creds (`TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN`, Render-only) live in a
local gitignored file `C:\Users\Forrest\.spender_turso`; query via `curl` POST to `<https-host>/v2/pipeline` (the
libSQL HTTP API) — no libsql Python wheel needed. Note `list_user_games` excludes `status='over'`, so finished
games aren't listable via the API — query the DB directly for them.

### Session (June 23 2026, `evaluations` worktree — SHIPPED to main with the k6 push, June 24)
**Tuning metric HARDENED + harness trimmed.** Judge AI tuning by **S-vs-frozen-S ONLY** — the H3/H3N/H3R panel is now **opt-in** behind `config_selfgate --panel` (default = sanity + screen + fresh holdout, nothing else; never run the panel unless explicitly asked). `--sanity-n` (default 10 PAIRS = 20 games): frozen-vs-frozen is *deterministically* 0.5 under paired CRN, so a handful confirms the harness is unbiased — don't spend the full `--n` on it. Ported the `_AggrH3` H3N/H3R opponents (were uncommitted on `heuristics`) into the evaluations `h3_vs_h2.py` + `vsearch_camp.py` `OPP` so `--panel` doesn't `KeyError`.

**#4 — seat-aware / bonus-discounted deck demand (`valuation3.DECK_BONUS_DISCOUNT`) — ADOPTED (default True).** `engine_value`'s deck term was seat-BLIND (raw undealt-deck color cost, same for all players). Now seat-AWARE (`_deck_demand_seat`): per undealt card subtract the seat's bonuses (`max(0, cost[c]-bonus[c])`), **normalized by the RAW deck total** — so a color you've fully covered → ~0, the OTHER colors keep their TRUE value, and overall magnitude legitimately SHRINKS as your engine fills in. WON: **fresh 0.5425 vs frozen-S (SHIP)**. The first cut RENORMALIZED (÷ discounted total → sum 1) and LOST (fresh 0.4775): **DO NOT renormalize a bonus-discount** — it inflates the un-built colors (fabricated demand); let magnitude drop, compensate via `ENG_DECK_W` if needed. Only the TOP-LEVEL deck term is seat-aware; `eng_base` (legacy level-0, inside `potential`/`_delta_take`) STILL uses the seat-blind `deck_color_demand` — matches the validated Python path.

**Dev-box Cython + the #4 monolith fix.** Compiled `valuation3` on the dev box (cython 3.2.5 / Py3.14 → `valuation3.cp314-win_amd64.pyd`) so the offline gates run the compiled leaf, not pure Python. **The `.pyd` SHADOWS the `.py` — recompile (`cythonize -i -3 games/spender/ai/az/valuation3.py`) after EVERY `valuation3` edit or workers silently use STALE code** (verify byte-identical via the build-gate tests + a differential `engine_value` signature hash). **Extended the C monolith `_engine_value_h3_c` to handle #4** (it was gated `not DECK_BONUS_DISCOUNT`, routing #4 to the slow Python path). FOOTGUN: the monolith fed ONE `dcd` vector into BOTH the inner `_eng_base_c` AND the top-level deck term; a naive single-vector swap to seat-aware broke byte-identity (**0.077 error**) because `eng_base` must stay seat-blind. Fix = TWO vectors — `dcd` (seat-blind → `_eng_base_c`) + `dcd_top` (seat-aware → the top-level `ev += dcd_top[bcol]*deck_w` only). Byte-identical confirmed (sig match + max-diff 0.000 + 32 tests).

**REJECTED this session (all S-vs-frozen-S; flags default-off / byte-identical):**
- **`heuristic3.TEMPO_TURNS_SCALE`** (late-game tempo-weight scaling off measured turns_remaining): WASH (fresh 0.5012). Time is already carried by the `compound_turns` engine horizon; re-penalizing tempo in the cost denominator is redundant.
- **Progress breadth — PARTLY SUPERSEDED, see the June 24 "k6" block below.** `v_state` gained `PROGRESS_TOPK`/`PROGRESS_DECAY` (cascade-weighted progress over the top-K take_values; `W_PROGRESS` now a probe key) — `_progress` was a top-2 mean, blind to ~10 reachable cards. The cascade "winner" (top-5, W=3.4, fresh 0.5275) was a **CONFOUND**: the true magnitude-match for flat top-5 is **W=2.92, not 3.4** (measured take_value means: top-2 ≈1.93, top-5 ≈1.65, top-8 ≈1.48), so it ran ~16% extra progress weight. At TRULY matched magnitude, **k=8 WASHED** (flat W=3.26 fresh 0.5038) — so breadth *at matched magnitude* is NOT a lever, and *pure* magnitude (top-2 + W∈{2.7,2.9}) also went sub-0.5. **The June-24 follow-up found the real effect is the INTERACTION** — breadth (K≈4–6) AND over-magnitude (~1.16–1.3×) *together* give ~+4pp; neither alone does. (Magnitude-compensation is MULTIPLICATIVE: progress contribution = `W_PROGRESS × mean(top-k)`; match the PRODUCT — `W = 2.5 × baseline_mean / new_mean` — not the mean.)
- Built-but-unrun: `valuation3.DECK_STAGE_TILT`/`DECK_STAGE_T0` (level-realization tilt of the deck term — the "L1 over-counted, never shifts to L3" idea) and an asymmetric-progress idea (top-1 for the side-to-move, top-2 for the waiter — bakes denial/tempo into the leaf).

**Game-replay limitation (found analyzing a real loss — LBBMRC, lost 14–20 to S: led on points but ignored the noble race; S swept 3 nobles).** Per-turn `v_state` CANNOT be reconstructed for EXISTING games: the saved game stores only the FINAL board/deck + an id-only move log — NOT per-turn board snapshots NOR the initial deck order/seed — and `progress` needs the board each turn. **To make FUTURE games replayable** (and re-scorable under any eval variant): in `main.py` store an initial `setup` snapshot (shuffled deck order + board + nobles) at game creation (`_deal_board` mutates `decks` in place; no seed is saved), AND **log `discard` moves** (the human `discard` path + `_ai_discard_one` aren't logged → token counts drift on replay). Then replay = rebuild from `setup` → re-apply the log → `from_game_dict` → `v_state.value` per ply. NOT yet implemented.

**Ops — gates kept dying with exit 127 = OOM.** Root cause: an ORPHAN PILEUP — a failed `mp.Pool` run leaves worker processes alive that eat RAM → the next gate OOMs → more orphans (vicious cycle). **Reap `C:\Python314\python.exe` procs before each gate.** Run gates with **`SPENDER_AZ_MODEL=none`** (the self-gate uses S/H3, NOT variant Z — skips the per-worker `az_model.npz` load, a big memory saver). The box is ~16GB but often <1GB free (VS Code + Firefox) and **CPU-bound at ~10 of 12 cores** (more workers don't help). **Don't edit `az/` modules while a gate runs** (Windows `mp` spawn re-imports → BrokenPipe crash). Remaining speed levers (diminishing — leaf already compiled): naive-cythonize `mcts.py`+`engine.py` (~10–15%), then `@cython.cclass` Valuation (~1.3–1.4×, large rewrite); past that, a bigger box (CPU-bound).

### Session (June 24 2026) — k6 progress adoption + past-S checkpoints (SHIPPED to main)
**k6 — `v_state` PROGRESS_TOPK 2→6 + W_PROGRESS 2.5→3.54 — ADOPTED + DEPLOYED.** This REVERSES the
June-23 "breadth is not a lever" conclusion: breadth IS a small lever, but **only paired with an
over-matched magnitude** — the INTERACTION the prior session missed by testing each axis alone. An
overnight K×magnitude grid (sims=500) then a **fresh disjoint-seed confirmation** found a coherent
ridge peaking at **K≈4–6, magnitude ~1.16–1.3×M0**: k4@1.30× and k6@1.16× both held ~0.54 across
seed bases; k3 (too little breadth) and k5@1.30× (too much magnitude) fell off. `PROGRESS_DECAY`
stayed **1.0** (plain mean) — the cascade/decay shape was a confound, not the lever. Evidence (all
S-vs-frozen-S unless noted): self-gate **0.543 / 0.545 / 0.531 across THREE disjoint seed bases**
(pooled ~0.540, the third-seed pullback says the true effect is the LOW end, ~+4pp); **H3/H3N/H3R RPS
panel PASS** (worst matchup +0.018, no exploitation — slight −0.017 vs racer H3R, +0.033 vs noble
H3N, the documented progress-helps-vs-noble pattern); **past-selves panel ≥0.5 vs all** (0.579 vs
frozen, 0.591 vs s_original, 0.574 vs s_pre_progress, **0.500 vs s_noble_heavy**, avg 0.561 — never
loses to a style, worst case a tie vs the noble-lean). A real, robust, SMALL gain — eval-weight
tuning remains otherwise saturated; this snuck through as a structure (breadth)×magnitude combo.

**Past-S checkpoint system — NEW offline tooling (`s_checkpoints.py` + `s_vs_checkpoints.py`).** S has
no weight file; its "weights" are module constants. A **checkpoint** = a JSON snapshot of all **90
strategy constants, PER-MODULE** (so dup names like `NOBLE_TURN_W` in both v_state & valuation3 are
unambiguous) across v_state/vsearch/heuristic3/valuation3; serving/infra (`SIMS`/`SERVE_*`/caps) are
excluded. Small, **committed** JSON in `games/spender/ai/az/s_checkpoints/` (NOT gitignored, unlike AZ
weights); each stamps git commit + timestamp.
- **`s_checkpoints.py`**: `snapshot`/`save`/`load`/`apply_config` + **`reconstruct <commit>`** (overlay
  a past commit's constant values on today's full snapshot — keys absent then keep today's default) +
  **`derive --set K=V`** (today + targeted overrides) + CLI (`save`/`list`/`show`/`reconstruct`/`derive`).
- **KEY semantic (do not misread):** a checkpoint reproduces "that era's WEIGHTS on TODAY's code" — a
  reproducible **STYLE**, NOT a bit-exact old S. So every newer feature (#4, the Cython leaf, structural
  fixes) is present and ON in all past selves; they differ only in the weight LEVERS that existed and
  were set differently. Intentional: we want strong, same-strength, style-DIVERSE sparring partners
  (resurrecting old code would just give a weaker S). Confirmed e.g. `s_original` carries pre-maximin
  `W_ENGINE_STK=0.8`/`C_PUCT=2.0` but `DECK_BONUS_DISCOUNT=True` (too new to exist at da18bab).
- **`s_vs_checkpoints.py`**: panel-of-past-selves runner — protagonist (live ± `--set`) vs a set of
  checkpoints via the **per-turn config swap** (the ONLY safe way to run S-vs-S with two configs sharing
  module globals: re-assert each side's full config before its move). Paired CRN, parallel. Validated:
  `live vs its-own-checkpoint = 0.5000 EXACTLY`.
- **Purpose + CAVEAT:** a same-strength, diverse **RPS guard** the H3 panel can't be (S beats the
  heuristics ~80% regardless, so 75-vs-80 is saturated) + a progress tracker. It does **NOT** probe a
  brand-new knob's OWN axis (every checkpoint has `PROGRESS_TOPK=2` — topk is newer than every commit),
  so it tests a candidate vs diverse *other-lever* styles, not vs topk variety; k6's real validation was
  the self-gate + H3 panel, the past-selves run a bonus robustness check. **Value compounds — save a
  checkpoint on every adoption.** 5 committed: `s_2026-06-24` (pre-k6 baseline), `s_2026-06-24_k6`
  (ADOPTED/deployed), `s_original` (da18bab), `s_pre_progress` (fb813cf^), `s_noble_heavy` (today+NOBLE 5.0).

**Forward direction the user raised: build the panel from S-strength diverse opponents** (past-S
checkpoints + future "S-rusher"/"S-nobler" derived variants), and consider an **"S-lite" playable tier**
(depth-2 or tiny-sim search) as a strong-but-instant opponent given the heuristics are too weak and the
deployed S is sims-starved on Render's 0.1 CPU.

### Session (June 24 2026) — over-reserve deep-dive + game-loss trace-back (DIAGNOSIS, nothing shipped)
Investigated one real game a strong human WON vs deployed S (`YINAIM`, dumped from Turso). Three durable
conclusions; DO NOT relitigate:
- **Over-reserve "fix" — TWO mechanisms TESTED & REJECTED (neither converts through search).** Symptom:
  S over-reserves, filling all 3 slots with cards it never converts → at YINAIM turn 50 it had 3/3
  reserves and could NOT reserve-deny the human's winning L3-6 (a public, affordable board card). Built
  on a local **`reserve-slots` worktree branch (default-off, byte-identical, NOT merged):** (1)
  `v_state.W_RESERVE_SLOTS` — a position-leaf free-slot **optionality** term (concave `O(eff_free)`,
  `eff_free = 3 − Σ deadness(held reserves)`; deadness from **`valuation3.tempo`** = the STEEPEST
  single-color remaining need so 6-of-a-color reads far / 2+2+2 near — a raw gem-SUM misses steepness;
  NEAR_T=1/FAR_T=6 turns; horizon-faded; symmetric). (2) `vsearch.RESERVE_DISCOUNT_W` — discounts a
  reserve ACTION's prior by `deadness(card) × load` (far reserves already held) so the 1st speculative
  reserve is free and the cost escalates as you stack far ones. **Both wash:** W_RESERVE_SLOTS self-gate
  ≈0.5 and the move never flips even at high W; `RESERVE_DISCOUNT_W=8` self-gate **0.455** (sims=500,
  n=100) and even a ~90% prior cut does NOT flip the reserve move. **Why: the reserve's Q (denial +
  acquisition of a 4-pt L3) is genuinely high — a modified static leaf OR prior can't beat it through
  search** (re-confirms the documented "doesn't convert through search" wall). Also the self-gate MIRROR
  is structurally blind to a slot-lock cost (both copies over-reserve; neither races to exploit the
  other's full slots — only a human/exploiter would). Knobs parked default-off on the branch as
  NET-feature candidates; not merged. (NB H3 itself has `USE_SPECULATIVE_RESERVE=False` — the
  over-reserving is the SEARCH PRIOR's `RESERVE_PRIOR_W*take_value`, not H3 greedy.)
- **MCTS mean-backup is blind to a sharp 1-ply opponent threat until more sims / the opponent commits
  (quantified).** YINAIM's winning L3-6 was public + affordable + exactly 1 ply ahead, yet S's searched
  value the turn before was **+0.033 at 600 sims, −0.552 at 3000 sims** (true ≈ −0.45). Not hidden-info
  / not horizon — the root value is a visit-weighted MEAN that dilutes the single sharp reply among the
  opponent's explored weaker replies; depth (or the opponent actually playing it next ply) converges it.
  Reinforces the rejected mixmax/`BACKUP_LAMBDA` and that **search THROUGHPUT (faster leaf → more sims)
  is the lever, not a backup tweak.**
- **Trace-back self-play diagnostic → real games are lost in the EARLY-MIDGAME, not at the visible late
  symptom.** Reusable diagnostic (scratch `trace.py`, built on `replay.py`): for each historical turn T,
  play N self-play games (both seats frozen-S, remaining deck reshuffled per game) from that position to
  the end, record seat-0 win-rate, walk T back to where it was last ~0.5. **Validated unbiased** (fresh
  `new_game` seat-0 = 0.53 first-player edge; 5/5 distinct lines from a position = real variance, not one
  deterministic game — so the win-rate is meaningful, addressing the "they play the same game every time"
  worry). On YINAIM (N=80, sims=256): S started **even/slightly-favored** (turn 0 = 0.53), held ~0.5
  through **turn 8**, then slid **0.48 → 0.16 over turns 9–14** (early-midgame engine race), bleeding from
  there to the turn-50 corpse. **No single blunder — a gradual out-building.** The over-reserve /
  slot-lock / can't-deny-L3-6 at turn 50 were all DOWNSTREAM symptoms of a position already lost ~13 plies
  earlier. **Conclusion: the lever is early-midgame DEVELOPMENT TEMPO (build a faster/more-efficient
  engine) — not reserves, denial, or the endgame.** That's the hard eval/search lever, not a knob.

### Variant S — Rust→WASM client-side serving (the sims-throughput rewrite; DEPLOYED June 2026)
The proven #1 lever is **sims/move**, and deployed S was sims-starved on Render's 0.1 shared CPU
(~380/move). So variant S's **entire search core was rewritten in Rust → compiled to WASM → runs in
the PLAYER'S browser** (their real CPU, root-parallel across cores), for ~100× more sims, free. Full
detail + resumption state: memory **`spender-rust-search-rewrite.md`**. Don't relitigate the parity
methodology or the saturation findings without reading it.
- **Crate `spender-core/`** (top-level, ON MAIN since `80d4f67`; built in the `forrestm_projects-rust`
  worktree / branch `rust-search`). Pure-Rust port of `engine`/`valuation3`/`heuristic3`/`v_state`/
  `vsearch`/`mcts`/`turns` + `cards` (generated by `tools/gen_cards.py`) + `actions` (action→move-dict
  bridge). `src/wasm.rs` = the `#[cfg(target_arch="wasm32")]` entry points; `src/bin/{bench,move_server,
  simgate}.rs` = offline tooling. **Validated:** engine bit-exact (15.4k steps), v_state leaf 1e-9,
  policy `choose_action` exact (800 cases), move bridge exact (7019), and **Rust-S vs Python-S = 0.5025
  ± 0.069 over 200 games** (the search plays equivalently). `cargo test` (10 suites) + `tools/gen_*_
  fixtures.py` regenerate the differential fixtures (gitignored). **Cross-worktree: always `cd
  forrestm_projects-rust` before `cargo`/`wasm-pack`; rustup is at `~/.cargo/bin` (prepend to PATH).**
- **Throughput:** native ~68k sims/s, WASM-in-V8 ~55k (after the perf round below) vs Render ~85-200.
  WASM ≈ native. So a browser worker does ~250k sims/move at the 4.5s budget; ~4× that aggregated across
  the root-parallel pool.
- **Serving = client-side, server stays authoritative (gated, zero-regression).** Backend (`main.py`,
  behind a per-room **`client_ai`** flag): on the AI's turn `mk_room_state` ships **`ai_search`**
  `{state, seat, sims, ply}` (the AI-perspective compact state via `_compact_state_dict`); WS actions
  **`client_ai_ready`** (arms the room) + **`ai_move {move}`** (validates the move is LEGAL via
  `actions.move_to_action`∈`legal_actions`, then `_run_ai_turn` — which does the cheap discard/noble
  FINISH server-side); `_schedule_ai_turn` waits `CLIENT_AI_TIMEOUT`=**8s** for the client, else computes
  the FALLBACK itself. Absent a WASM client it's byte-identical to before. Variants **S and N** are ported
  (other variants stay server-side; N's worker uses the `searchN` kind = learned leaf). Frontend (`Spender.jsx`): a pool of module Web Workers
  (`webapp/public/wasm/s-worker.js` + the wasm-pack `--target web` glue + `.wasm`, all in
  `webapp/public/wasm/`), root-parallel — each worker runs an independent determinized search (distinct
  seed), the main thread SUMS root visit vectors → argmax → `action_to_move_for` → submits `ai_move`.
  Graceful fallback (no module-worker / wasm load fail → never arms → server computes). **Trust:**
  client-side AI is sound for vs-AI (tampering only weakens the player's OWN opponent).
- **Time-budgeted + sims-capped.** Each worker searches a **4.5s** wall-clock budget OR a **per-worker
  sims cap** (`CLIENT_AI_MAX_SIMS=100000` in Spender.jsx → `search_visits_timed(…, max_sims, …)`),
  whichever first. The cap **bounds browser-tab memory** (~1 node/sim; 4×250k-node trees ≈ 1.4GB was a
  mobile-OOM risk → cap → ~580MB) and makes fast devices snappy (~2s). **The cap is BROWSER-ONLY** — it
  lives in Spender.jsx→worker→the wasm `search_visits_timed`; the offline bins (`bench`/`simgate`/
  `move_server`) call `vsearch::choose_action(…, sims, …)` with the explicit, UNCAPPED sim count. Pool
  size = `min(navigator.hardwareConcurrency, 4)`.
- **PERF: per-Valuation leaf memoization ~2.6-3× sims/s (DO NOT remove).** Profiling (`SP_NOLEAF`/
  `SP_NOVALUE`/`SP_NOPOLICY` env probes in the vsearch eval) showed **the V leaf is ~95% of search time**
  (machinery ~2.3µs/sim). The Rust port had OMITTED the Python's memoization, so the cross-card
  `engine_value` chain recomputed O(cards²)×. Added per-`Valuation` caches (byte-identical — store/return
  the exact f64; all parity tests pass): `eng_base`/`cost_scalar`/`delta_take`/`engine_value`/`tempo`/
  seat-aware `deck_demand_seat` + `heuristic::components`, + a thread-local `turns` memo + fixed-array
  MCTS Node. `deck_demand_seat` (an O(deck) loop recomputed ~16×/leaf) was the single biggest win. After
  this the leaf is balanced (value ~3.7µs, policy ~4.4µs) with NO dominant chunk — **caching as a speed
  lever is EXHAUSTED at ~3×; SIMD won't vectorize the 5-element per-color loops.**
- **Deploy flow:** `cd forrestm_projects-rust/spender-core && wasm-pack build --target web --release
  --no-typescript`, `cp pkg/spender_core.js pkg/spender_core_bg.wasm ../webapp/public/wasm/`; the wasm +
  `s-worker.js` + `Spender.jsx` are FRONTEND files → push to `main` → gh-pages (smoke-gated). A `main.py`
  change deploys to Render (its path filter); **`spender-core/**` is in NEITHER CI path filter** (no
  deploy from the crate). Backend-before-frontend ordering when both change (else a new client hits an
  old backend → transient "unknown action"). **LIVE + user-confirmed working on forry4.github.io.**

### Session (June 25 2026) — value-first ladder: variant N (learned value leaf) BEATS S (VERIFIED)
**The learnable path is not just OPEN — it produced a concrete win.** A learned **value leaf** used
inside variant-S's determinized search (+ the H3 prior) **beats the hand v_state leaf**, verified 5
independent ways. New variant **N** (Neural), a SEPARATE option alongside S. Built in the
`forrestm_projects-rust/spender-core` crate (the Rust→WASM search core); full write-ups in memory
`spender-N-learned-leaf-beats-S` + `spender-az-retrain-plan`, plan `.claude-plans/az-retrain-rust-scale.md`.
- **The recipe that beat the documented wall:** **outcome-trained** value (target 2·win−1 from self-play
  game OUTCOMES, NOT V_search) on an **enriched 101-feature** encoder (`spender-core/src/feats.rs` = raw
  state + v_state components + per-card derived + deck), a 256-hidden MLP (GPU/torch), used as the MCTS
  **LEAF**. Why it works where the documented "distilled leaf washes by 1200 sims" did not: that wash was
  for leaves distilled toward **V_search** (redundant with search); an **outcome-trained** leaf carries
  **beyond-search-horizon** signal search can't recover, so it converts AND holds at depth.
- **The 5 guards (harness `spender-core/src/bin/rung2.rs`, 80 games each, SE~0.05):** (1) CONTROL
  v_state-vs-v_state via the same path = **0.5000 exactly** (harness unbiased); (2) N-vs-S holds across
  depth **0.69/0.71/0.69** @ 400/800/1200 sims; (3) OUT-OF-SAMPLE on fresh decks (seed≥1M, outside the
  harvest's 0–5999) **0.64/0.71**; (4) **EQUAL-TIME** N@600 vs v_state@1200 = **0.66** (wins at a 2×
  handicap — the calibrated-leaf's killer, beaten); (5) PANEL N-vs-H3 **0.94** > baseline S-vs-H3 **0.84**
  (generally stronger, NOT RPS-vs-S).
- **The ladder (do not re-derive):** Rung 0/Phase 0 — Rust value-net inference is NOT a binding constraint
  (`bin/net_bench`: all candidate nets feasible for self-play; export-path numpy-parity verified
  `bin/net_export_check`). Rung 1 — a learned value at **1-ply** LOSES (vs H3 .12, vs v_state@1ply .07),
  but that's expected: **1-ply is unkind to position-values** (even v_state@1ply loses to H3 at .37);
  search is what makes a position-value strong. Rung 2 — the value as the **search leaf** is where it
  shines (the 5 guards above).
- **simgate (1M vs 1.2k sims, both v_state-S) = 0.5100 (a TIE, ±0.098, 100 games):** search **SATURATES
  ~1.2k sims** for the current eval. So the lever is **eval/policy quality, NOT more sims** — re-tuning
  sims is dead, and the WASM push *beyond* ~1.2k gave little serving strength (its real value is the fast
  offline self-play that enables value-learning + N's equal-time win, since N@600 is already near-saturated).
- **NEXT:** (a) ~~ship N as a served variant~~ DONE (`c96e3fd`, "Nina"/expert in the lobby; see the next
  session note); (b) un-anchored **self-play** (N-vs-N, value bootstraps on its own improving play beyond
  S's distribution) — N's supervised net is the proven FLOOR. Training: torch/GPU (the `python` with cu128,
  NOT `/c/Python314` which lacks torch + numpy there is ~1.5 GFLOPS / 17-min fits); reap orphaned-python.

### Session (June 26 2026) — N served-variant bug fixes (deployed `da60406`)
N shipped as the website "Nina" (expert) option (`c96e3fd`) but three serving issues showed up in real
play; all fixed on `main`. **N's leaf runs CLIENT-side (WASM, `searchN`), with the server falling back to
S's v_state search if the client doesn't submit in time.**
- **"not the AI's turn" error toast (the headline bug).** N's WASM worker `build_n_net()` parses its
  **embedded ~600KB `n_model.json` ONCE PER MOVE, BEFORE its search budget timer even starts** (see
  `spender-core/src/wasm.rs::search_visits_n_timed`), so N's wall-clock runs ~1-2s longer than S's and was
  **losing the 6s client/server race** on slower devices — its late `ai_move` then hit the `ai_move`
  handler's `g.turn != ai_pid` guard, which sent `{type:"error","message":"not the AI's turn"}` → a toast.
  **Two-part fix:** (1) `CLIENT_AI_TIMEOUT` 6.0→**8.0** so N reliably WINS the race (and when the client
  wins, the move applies the instant it's submitted — the human never waits the full timeout; it only
  bounds the truly-can't-compute fallback); (2) the `ai_move` handler now **LOGS stale submissions instead
  of toasting** — a late client move is a normal race artifact, never the user's fault, and the server
  fallback already guarantees the turn advances (so silently dropping it is safe; never re-add the toast).
- **Admin "Vals" overlay now works for N (position eval ONLY, by request).** N had no overlay (the per-card
  block only handled H/H2/H3/S), so the gold Vals button never rendered. Added a **faithful Python port of
  N's value net** in `main.py`: `_load_n_model` (loads the **SAME `spender-core/src/n_model.json` the WASM
  embeds** — single source, no drift; path = repo-root/spender-core/src; shipped by the Dockerfile `COPY .`),
  `_n_features` (a line-for-line port of `spender-core/src/feats.rs::features` — the 101-feature vector,
  reusing the Python `v_state`/`valuation3` helpers the Rust was ported from), and `_n_position_eval`
  (z-score → dense→ReLU→dense→tanh, [-1,1] from the mover's seat). Wired into `_compute_overlay` (N →
  **`ai_position_eval` only, NO `ai_card_values`**) + the `mk_room_state` overlay gate. Frontend
  (`Spender.jsx`): the Vals toggle + eval pill now gate on **(card values OR a position eval)** so they
  appear for N; the pill is N-aware (label **`eval`**, NO never-resolving "srch …" — that's S-only). Cost is
  one tiny MLP forward per broadcast (~same as S's `_s_position_eval`). Gracefully omits if numpy/the file
  is unavailable. (It IS admin-only, same as every variant's overlay.)
- **Take button right-aligned.** The action-button rows (`.actions-panel-btns`/`.board-actions-btns`) were
  `justify-content:center`, so with no Vals button (N before the fix) Take floated to the MIDDLE. Changed to
  **`flex-end`**; the Vals toggle's `margin-right:auto` keeps it on the LEFT when present, so **Take is now
  always against the right edge** for every variant (no regression — with the toggle present the auto-margin
  already pinned Take right under `center` too).
- Validated: backend review/replay/game-logic tests pass (119); N eval verified in [-1,1] with correct
  mover-perspective; `npm run smoke` clean (CLS 0). The WASM was UNCHANGED (already shipped `searchN` in
  `c96e3fd`); this was a Python-timeout + JS-gating + CSS fix only.

### Session (June 26 2026) — Plan-A AZ retrain → variant PV (policy+VALUE net) SHIPPED as "N"; league run launched
**The learnable-net path is REALIZED (this UPDATES the "learnable-leaf path" question above):** a
warm-started **policy+value** net ("PV", `net_pv_4`) BEATS both old-N and S in search. Prior learnable
attempts lost because they distilled-S / trained from-scratch on flat features; PV wins because it pairs
the **enriched 125-feat encoder** + a **warm start from the N value-leaf bootstrap** + AZ self-play.

- **The PV stack (Rust, `rust-search` worktree + `C:\Users\Forrest\az_run`):** `PolicyValueNet`
  (valuenet.rs — trunk + value head + 70-action policy head), `feats::features_az` (125 = base 101 +
  per-card `engine_value`+`noble_progress`; the per-card adds earned their slot in a policy pre-check,
  +0.024/+0.017; engfwd/turns/oppdem DROPPED as no-lift), `vsearch::root_visits_until_pv` (determinized
  PUCT, legal-masked softmax of net policy logits at PLAY, H3-prior fallback at discard/noble, net value
  leaf). Bins: `selfplay_pv` (self-play harvest), `train_pv.py` (GPU value+policy trainer, value MSE +
  policy CE, reward-shaped `(1-a)(2y-1)+a·tanh(margin/6)`), `eval_pv` (vs S), `eval_vs_n` (vs old-N via
  `features_n101`, the 101 encoder lifted from HEAD), `harvest_az` (S-vs-S bootstrap → `boot125.csv`,
  2.26M rows). `azloop.sh` ran it.
- **Self-play PLATEAUED (do not relitigate):** vs-S FLAT ~0.735 across 12 iters while value-AUC kept
  RISING — the documented self-play-diverges-from-the-external-opponent signature (the net got better at
  beating its own clones, not S). The per-iter "peaks" (0.80) were **n=160 eval noise**; a 600-game
  fresh-decks re-eval regressed them to ~0.73–0.76 (net_pv_4/8/12 statistically tied). One-time gain
  over N, did NOT compound. **net_pv_4 = champion.**
- **PV champion validated:** vs old-N **0.60 / 0.66 / 0.67 @ 160 / 400 / 800 sims** (robust, edge GROWS
  with sims — a good policy compounds with depth), replicated on net_pv_8/12 (0.63/0.68); vs S **0.758**.
  The learned POLICY adds **+0.58 over the H3 prior** at a matched value head (control bin
  `eval_policy_ctrl`: full-PV vs PV-value+H3-prior). So both the richer value head AND the policy head
  pull their weight.
- **SHIPPED, served AS variant "N" (Nina, the top tier):** first as a separate "PV"/Percy variant (commit
  `2a50b5a`), then **folded INTO "N"** (commit `12fc540`) per the user — `Spender.jsx` routes
  `ai_variant==="N"` → `searchPV`, and the Percy/PV lobby option + persona were removed. **Old value-leaf
  N is KEPT AS A RECORD** (`n_model.json` + `search_visits_n_timed`/`searchN`/`build_n_net` all stay in
  code, just not routed to). **Upgrade path: swap `spender-core/src/pv_model.json` → rebuild wasm → push;
  "N" instantly plays the stronger net, no UI change.** (The WWSD browser autoplayer also adopted PV —
  `search_pv_full_timed`, v0.9.0; see the WWSD section.) See memory [[spender-variant-pv-shipped]].
- **DEPLOY GOTCHA (do not relitigate):** the AZ/WASM work was built on **stale `rust-search` (49 behind
  origin/main)**; production = main ALREADY had the WASM client-AI + variant-N foundation via a different
  history, but NOT the Plan-A additions. So deploy = **PORT onto main** (fresh worktree off `origin/main`,
  add-only edits, `push origin <branch>:main`) — **NEVER push `rust-search:main`** (non-ff wipes 49
  commits). **Dual-encoder split (load-bearing):** main's `features()` stays **101 (old-N's net)**;
  `features_az()` is the NEW **125 (PV)** — kept separate so old-N isn't fed the wrong dims (on rust-search
  `features()` had been redefined to 125, which BREAKS old-N — that working tree isn't deployable as-is).
  All Rust diffs onto main verified **purely additive (0 deletions)** → N byte-unchanged. The built
  `spender_core_bg.wasm` is a COMMITTED artifact (Pages CI does NOT rebuild Rust→wasm); wasm grew to
  ~2.07MB (embeds the net) — candidate for external-load later.
- **Discard-search = WASH (do not relitigate):** `selfgate_discard.rs` found **93/93 multi-option discards
  where the searched pick == greedy H3 `choose_discard` (0% divergence)** → the greedy discard is already
  search-optimal; searching it just burns sims. `root_visits_until_leaf_ds` parked on the branch.
- **LEAGUE run (IN PROGRESS, `az_run/league_loop.sh`) — escape the plateau via opponent diversity (the
  documented cure for self-play tunneling):** `league_pv.rs` (the BEST net records ONLY its own moves vs a
  FIXED opponent — S / old-N / a rotating past-PV checkpoint — shaped by margin; learn to BEAT them, not
  imitate) + `pv_vs_pv.rs` (gate PRIMARY: candidate vs frozen best, paired-CRN, =0.5000 for identical
  nets). Mix **self .4 / past-PV .25 / S .2 / old-N .15** — **H3 DROPPED** (PV crushes it ~95% → saturated
  targets, near-zero margin gradient; its share went to past-PV, the closest/most-informative opponent).
  Buffer ~**50/50** (subsampled `boot125_sub.csv` anchor, 600k rows, so the league signal isn't drowned —
  the self-play loop's 87% bootstrap anchor was part of why it stalled). **Gate = beat frozen best ≥0.52
  AND RPS guard (vs-S ≥0.72, vs-old-N ≥0.60 — net_pv_4's scores minus noise).** **Verdict to watch: the
  per-promotion `best vs SHIPPED net_pv_4` line — >~0.55 = the league broke the plateau (swap
  `pv_model.json` + ship); ~0.5 across many iters = the architecture ceiling, net_pv_4 stands.**

### Session (June 27 2026) — ENRICHED 178-feat retrain BEATS net_pv_4; `net_ext_19` SHIPPED as "N" (`613c91f`)
**The feature-enrich retrain WORKED — refuting the "variant N is at the ceiling" pessimism (the league above only TIED net_pv_4; ENRICHING THE FEATURES + self-play broke through).** `net_ext_19` (a 178-feat policy+value net) beats the shipped champion net_pv_4 **~0.59-0.60, DEPTH-ROBUST** (256/800/3200 sims = 0.586/0.584/0.602 on fresh decks — no decay, unlike the calibrated-leaf wash). **DEPLOYED as N** (`613c91f` on main): selecting N now plays net_ext_19. The enrich+self-play loop is now a REPEATABLE strength engine, not a one-off.
- **Encoder `feats::features_ext` (178)** = deployed base 125 (`features_az`) + 5 groups: A per-color self-need (5), B opp face-up reserve content (12), C own reserve content (12), D per-card take_value (12), E per-card turns-to-afford (12). Trained on the **rust-search** worktree (`az_run/loop_ext.sh`): warm-started by distilling net_pv_4's PV-vs-PV play into the 178 net (clean distill 0.517 vs net_pv_4), then self-play with the anchor annealed off. CONVERGED at iter 24 (champion edge flat ~0.58-0.60 for ~10 iters; `cand_vs_best` oscillating at the 0.52 bar).
- **Pick the best net by RE-GATING ALL candidates on FRESH decks — NOT the in-loop promotion (winner's curse; DO NOT regress).** The noisy 0.52 gate (SE 0.032 ⇒ ~27% false-promote on a tie) doesn't reliably pick the strongest net. High-N re-gate (960 games, disjoint deck base): `net_ext_15` (highest in-loop, 0.635) REGRESSED to 0.577; **`net_ext_19` (a KEPT, not-promoted iter, logged 0.606) held/rose to 0.618 → the actual best.** Always re-gate the candidate set on fresh decks.
- **C_PUCT swept** (`gate_cpuct.rs` self-gate vs varying c_puct + `vsearch::root_visits_until_pv_c`): flat 1.0-2.0, falloff >2.0; the faint c_puct=1.0 edge (+0.02 @ 800 sims) VANISHED at 3200 (0.489) → **keep C_PUCT=1.5** (same low-sims crossover trap documented for S).
- **Deploy = PORT onto main** (worktree `forrestm_projects-pvdeploy`, branch `ext-deploy` off origin/main; **NEVER push rust-search:main**): added `features_ext` to main's feats.rs (reuses `features_az` as base — VERIFIED functionally byte-identical to rust-search's `features()`) + the 5 groups VERBATIM; **encoder PARITY byte-verified over 170 states** (`dump_ext.rs` on both crates — guaranteed because engine/valuation/v_state/heuristic are byte-identical across the branches); overwrote embedded `pv_model.json` with net_ext_19; switched the two PV serving closures `features_az`→`features_ext` in wasm.rs; rebuilt wasm (`wasm-pack build --target web --release --no-typescript` → cp to `webapp/public/wasm/`); `npm run smoke` PASS. **N routing UNCHANGED** (`ai_variant N`→`searchPV`→`search_visits_pv_timed`). **Rollback = `git revert 613c91f`** (restores net_pv_4 + the features_az path; both kept in the tree). wasm ~2.07→2.37MB.
- **The 0.59-0.60 is a SELF-GATE edge — it does NOT prove the human-found weakness is fixed.** That weakness (efficient **race-to-15 ignoring nobles**; single-strategy collapse) is self-gate-BLIND. Confirmed offline on real game **`XJJJDF`** (user won 15-11 vs deployed N): the human raced 12 cards / 15 pts all-from-cards / 0 nobles / **1.25 pts-per-card** (two 4/7 L3s + a 3/6 L2), while N went wide+noble — 16 cards, **12 zero-point**, 0.50 pts/card + a noble (spent turns 33-43 on six straight 0-point L1s). The static leaf rated N AHEAD the whole midgame (it under-prices the human's reserved-but-uncashed L3 race). Regression set: `XJJJDF`/`IYGWJQ`/`YINAIM`. **The live playtest is the real test; the RACER track is still the gate** (build a Rust racer proxy → confirm the weakness reproduces → add the racer to the training mix + gate vs it; the generic league is REJECTED, but a TARGETED racer is the new ingredient self-play can't generate).
- **Overnight (RUNNING, `az_run/loop_night.sh`, capped ITERS=40):** continuation from net_ext_19 at **SIMS=512** (the documented plateau lever — higher-quality targets) + TEMP=30, gating vs net_ext_19. Crosses ~0.55+ → high-N re-gate + ship; flat → 200 sims wasn't the ceiling, pivot to the feature round + racer track.
- **Next enrichment round = MORE FEATURES (the proven higher-EV lever), done ATTENDED** (new dim ⇒ warm-start distill, a multi-step build like this one). Memory `spender-feature-backlog`: **HEADLINE = the user's same-color payoff-concentration / denial-robust-fork idea** — ≥2 steep same-color point cards ⇒ that color is a multi-target, *un-deniable* investment (opp can reserve-deny ONE payoff card, not both without crippling themselves); encode as a per-color top-2 of `PTS×color-need` (distinct from per-card `engine_value`). Plus racing-aware features (points-per-turn race read, per-card noble-overlap, victory-proximity) + the parked H2 net-feature candidates.
- **Offline tooling added** (rust-search + pvdeploy crates): `gate_seat.rs` (per-seat win-rate split), `gate_cpuct.rs` + `vsearch::root_visits_until_pv_c` (c_puct sweep, byte-identical to `root_visits_until_pv` but caller-chosen c_puct), `dump_ext.rs` (feature-parity dump). Prod finished-game analysis: query Turso direct (creds `C:\Users\Forrest\.spender_turso`; `list_user_games` excludes `status='over'`; the saved row is the ROOM dict — game is `state_json→game`, carries `setup` → replayable via `replay.py`).

### Session (June 27-28 2026) — net_night_14 → 15-pt N; **21-pt Long-mode net SHIPPED**; three feature/exploration verdicts (15-pt N at ceiling); card-set-attention big bet started
- **`net_night_14` was the deployed 15-point N** (`6c3e66b`, superseded net_ext_19): a higher-sims (512) self-play continuation, beats net_ext_19 ~0.55-0.58, S 0.827. PURE net swap (same 178 `features_ext` encoder). **(SUPERSEDED for Classic 15 by the card-set attention net `net_attn_3` — see "Variant N (CURRENT CHAMPION)" below; net_night_14 now lives on only as the 21-pt N base.)**
- **21-POINT ("Long" mode) SPECIALIST SHIPPED — `b91a744` on main. The one clear win this session.** N now serves **`net_ext21_13`** when `win_points==21`, keeping net_night_14 for Classic 15 — ONE opponent, auto-picked by game length (like S auto-adapts), NOT a separate lobby entry. The deployed 15-net was trained ONLY on 15-pt self-play and merely auto-adapted to 21; a net that actually TRAINS on 21-pt games captures real Long-mode signal it never had. **Validated: beats net_night_14 AT 21 = 0.6325 on fresh decks (600g), holds 0.58-0.65 across the 256/512/1024/2048 sims-ladder (depth-robust), beats runner-up net_ext21_32 head-to-head 0.477/0.467.** Mechanism: `wasm.rs` `search_visits_pv_timed`+`search_pv_full_timed` branch on `s.win_points` → `build_pv_net_21()`; `pv_model_21.json` embedded next to `pv_model.json` (both 178-feat, same encoder/serving path; wasm 2.37→3.78MB). Trained by `az_run/loop_ext21.sh` (`selfplay_ext`+`gate_ext` gained a `win_points` arg, default 15 = byte-identical; the whole Rust stack is already win_points-parametric — it's even an encoder feature, feats.rs:27), warm-started by WEIGHT-COPY from net_night_14. The loop CONVERGED (~0.58-0.60 vs champion, best net_ext21_13 by iter 13, plateau through iter 32). **Lesson: the gain came from NEW TRAINING EXPERIENCE (21-pt games), not new features/arch** — the pattern that actually works. Classic byte-identical; rollback = `git revert b91a744`. (Deploy gotcha: pvdeploy `ext-deploy` was 13 wwsd-commits BEHIND origin/main → rebased the 1 commit on top before pushing; core unchanged across them.)
- **THREE NEGATIVE VERDICTS — the 15-point N is at its ceiling (DO NOT RELITIGATE):**
  1. **Round-2 feature enrichment WASHED.** `features_ext2` (204 = 178 + 5 AGGREGATE groups: same-color concentration/fork, race-state, noble-race, buying-power, color-coverage) self-play loop (`loop_ext2*`) plateaued ~0.547 vs net_night_14, no promotion past the early best in 13 iters. The aggregates are REDUNDANT with the per-card features the net already has — unlike round-1's per-card features which converted. (Note: the user's headline "payoff-concentration/fork" idea was IN this round → washed.)
  2. **Dirichlet root-noise exploration WASHED.** The self-play loop had NO Dirichlet (only visit-sampling first 30 plies); ADDED it (`mcts::Search::apply_root_dirichlet` Marsaglia-Tsang gamma/dirichlet + `vsearch::root_visits_until_pv_noise` + `selfplay_ext2` `dir_eps/dir_alpha` args, default 0 = byte-identical). eps=0.25 tracked dead-even with no-noise (9 iters); eps=0.40/alpha=0.15 dipped (noise-degraded data) then recovered to parity. **Exploration is NOT the bottleneck.**
  3. **Round-3 per-card features WASHED (cheap pre-check, ~15 min — no loop spent).** `features_ext3` (214 = 178 + 3 NEW per-card groups: per-card CLOSING `(my pts after buying ci incl. free noble)/win_points`, per-card OPP take_value, per-card OPP-affordable-now) → harvest net_night_14 self-play (227k rows) → `precheck3.py` leave-one-out vs the deployed 178 base. ALL washed: closing dtop1 **-0.0004** (the net already derives closeness-to-win), opptv **+0.0046** (sub-threshold + AUC down), oppaff **-0.0031**. (Round-1's +0.009 didn't convert, so +0.0046 won't.) **The "new per-card info" well that fed round-1's win is dry — adding more derived per-card quantities is redundant once the net has take/turns/engine/reserves.**
- **RACER ROUTE REFUTED (DO NOT relitigate the heuristic-racer form).** Hypothesis: N is blind to a pure-efficient-L2 racer that ignores nobles (the human's winning style). Built `heuristic::choose_action_racer` (H3 with a `Valuation.noble_scale` field, default `heuristic::NOBLE_SCALE`=3.0, lowered to de-emphasize noble-CHASING; `noble_completion_pts` untouched so it still grabs free nobles) + `racer_probe.rs`. **N CRUSHES the racer 0.92-0.95 at every noble weight {3.0,1.2,0.5,0.0}, and win-rate RISES as nobles drop** (a low-noble H3 is just a weaker H3). N out-searches ANY 1-ply heuristic regardless of style → a heuristic racer can't expose the weakness (the documented "MCTS saturates a competent heuristic"). The human's exploit is value-CALIBRATION (N read +0.8 in a 15-13 coin-flip), not "N loses to racers" (it doesn't). A search-based racer is the only untested racer form (low odds; S already loses 0.24 to N).
- **BIG BET STARTED (user-chosen): CARD-SET ATTENTION net.** The deployed net is a tiny single-hidden-layer MLP over a flat 178-vector; untested whether a better INDUCTIVE BIAS (attention over per-card tokens) breaks the ~0.65 plateau via the same self-play (the earlier ~0.66 cap was a feature-limited DISTILL test, not a self-play policy net). **Arch locked:** 18 tokens (12 board + 3 own-reserved + 3 nobles, masked) × ~24 feats → embed D=64 → 2×[4-head MHA + FFN128] (residual+LN) → mean-pool + state-embed(28) → trunk128 → value(tanh)+70-policy. **Phase 0 throughput gate PASS** (`attn_bench.rs`): attention forward 2041 eval/s vs MLP 49055 = **24× slower** → ~17k aggregate sims/move, but the deployed MLP is ~400k sims/move (~500-1000× past the ~400-800 sim diminishing-returns knee) so 17k is still ~20-40× past it → **servable client-side** (WASM ~1.5-2× + per-call allocs ~2-3× recoverable → ~8-12k real, still fine). **Next = Phase 0 PARITY**: `features_tokens(s,seat)→(tokens,mask,state)` + the attention forward in BOTH Rust lib (`attn.rs`, for self-play+serving) AND PyTorch (training), parity ±1e-4 (self-play infers in Rust, trains in PyTorch — MUST match), then Phase 1 self-play→train→gate vs net_night_14. Memory `spender-variant-pv-shipped` + `spender-racer-blindspot-confirmed`.


### Variant N is now the CARD-SET ATTENTION net (Rust→WASM, client-side) — context for June 29
The deployed 15-pt variant **N** is no longer the heuristic/MLP stack: it's a **card-set attention net**
(`net_attn_3`: 18 card-tokens × 24 feats → attention → value+policy heads), trained offline (PyTorch
`az_run/attn_net.py` + `train_attn.py`) and **served client-side via Rust→WASM determinized PUCT** in the
player's browser (the `forrestm_projects-rust/spender-core` crate: `feats.rs` tokenizer, `attn.rs` forward,
`vsearch.rs`/`mcts.rs` search). It beats variant S ~0.88 and the prior MLP N (`net_night_14`) ~0.567 on
fresh decks. **Prod sim budget is ~20k sims/move** (measured telemetry — the heavier attention leaf dropped
it from the MLP's ~100k; still well above the ~1.2k saturation knee, so matched-sims strength transfers).
Full history in memory: `spender-attention-net`, `spender-variant-pv-shipped`, `spender-rust-search-rewrite`.

### Session (July 2026) — DISCARD-root search fix (deployed N + wwsd) + Rust-WASM build facts
**The determinized PUCT one-hot the H3 pick at ANY non-PLAY root, so DISCARDS were decided by H3's STATIC
heuristic — NOT the net (DO NOT regress).** In `spender-core/src/vsearch.rs`, `root_visits_until_pv` and
`root_nw_until_pv` short-circuited `if s.phase != PLAY || legal.len()==1 { one-hot heuristic::choose_action }`.
So a discard used H3's `choose_discard` (drops ITS OWN least-needed color) — a DIFFERENT brain than the net
that chose the take → the "take gems, then discard the ones it wants" loop, with zero lookahead. **Fix:** search
DISCARD roots too — `if legal.len()==1 || (s.phase != PLAY && s.phase != DISCARD)` — so the net's value head
evaluates each of the ≤6 discard options after rolling into the opponent's turn (ONE brain decides take+discard,
with lookahead). NOBLE/OVER/single-legal still one-hot H3. Lib regression test `discard_root_is_searched`. Only
the `_pv` variants (variant **N**) were fixed; the `_leaf` variants (variant **S**, `root_*_until_leaf`) still
one-hot H3 discards — left as-is (changing S is an unvalidated strength change).
- **Two serving paths share this crate (both fixed):** website N = `Spender.jsx` `ai_variant==="N"` → worker
  `kind:"searchPV"` → `search_visits_pv_timed` → `root_visits_until_pv`; the wwsd userscript →
  `search_pv_full_timed` → `root_nw_until_pv` (its `decideDiscards` builds the post-take DISCARD state
  `phase=1` and reads the searched top action — was 1 sim ≈ raw H3, now a real search).
- **wasm is NOT built by CI — it's committed pre-built artifacts.** Website:
  `webapp/public/wasm/{spender_core.js,spender_core_bg.wasm}` (`wasm-pack --target web`), loaded by the
  hand-written `webapp/public/wasm/s-worker.js`; rebuild + commit those two files, CI (deploy-pages, watches
  `webapp/**`) publishes. **Same filename ⇒ browsers may serve the CACHED old wasm** (~10 min GH-Pages TTL /
  hard-refresh). Variant routing: N→"searchPV", S/others→"search", old value-leaf N→"searchN" (not routed).
  wwsd: `wasm-pack --target no-modules --out-dir pkg-nomod` → `wwsd/build_browser_n.py` inlines base64 wasm+glue
  into `wwsd/wwsd_browser_n.user.js` (manual Tampermonkey install; no prod/CI surface).
- **Toolchain is now LOCAL** (cargo 1.96 + wasm-pack 0.15 + wasm32 + MSVC, `$HOME/.cargo/bin` off PATH →
  `export PATH="$HOME/.cargo/bin:$PATH"`). Use `cargo test --lib` (the `src/bin/*` need `--features bridge`).
  The crate lives in the **forry4.github.io repo** (`spender-core/`), NOT a separate repo — despite memory
  `spender-rust-search-rewrite` naming it `forrestm_projects-rust/spender-core`. Build worktree:
  `forrestm_projects-wwsd-wasm` (branch `wwsd-wasm`); the `vsearch.rs` edit was made there then copied to main.
- **wwsd userscript this session (v0.9.29):** minimize/collapse toggle; chat capture (schema-agnostic Minimongo
  auto-detect → per-game `chat[]` for suggestion-mining; `WWSD_N.chatProbe()`/`listCollections()`,
  `CONFIG.CHAT_COLL` override — UNVERIFIED vs spendee's real schema, run chatProbe live); reserve hold fix
  (`synthHoldCanvas` keeps the press ALIVE with ~90ms sub-pixel pointermoves — a static long-press is ignored by
  the canvas; `HOLD_MS`→2200); auto-lobby **circuit-breaker** (a loss where NOBODY hit the target = our
  timeout/forfeit → `CONFIG.AUTO_LOBBY=false` in `logFinalize`, before the tick's `autoLobbyStep`, so no runaway;
  `AUTO_START` is dead code). Console paste is blocked by the browser self-XSS guard → type `allow pasting` once.

### Session (July 2026, cont.) — website N discard ROUTED TO THE CLIENT NET + wwsd failure-logging + chat-schema fix
**The website N discard loop RECURRED even after the July DISCARD-root Rust fix — because the site is SPLIT-BRAIN and the discard was a DIFFERENT code path (DO NOT regress).** On the website, N's PLAY move is searched client-side (WASM), but the over-cap discard was finished **server-side in Python** by the `_ai_discard_one` heuristic — NOT the Rust `vsearch.rs` `root_visits_until_pv` the DISCARD-root fix touched. So that Rust fix helped wwsd (all-in-browser) but did nothing for the site. A different brain (heuristic) than the net that chose the take → the take→discard→re-take loop persisted on the site. Fixed in TWO commits:
- **(a) Heuristic patch — `_ai_discard_one` was reserved-blind + holdings-penalized (`814a407`).** It only summed demand over BOARD cards (ignoring the AI's RESERVED cards → gems saved for a reserved card looked surplus) and used `max(0, cost−bonus−HELD)` (so the more of a color you stockpiled, the more "surplus" it read — backwards). Rewritten to sum demand over **board + reserved** using **raw** effective cost (`cost − bonus`, holdings-independent). Kills the obvious loop; now also the timeout FALLBACK for (b). Test `test_ai_discard_respects_reserved_cards`.
- **(b) Route the discard to the client's NET search — the real fix (`9292170`), like WWSD does.** `_run_ai_turn(game, ai_pid, mv, defer_discard=True)` (set ONLY on the client `ai_move` path; the server-fallback path keeps `defer_discard=False` → heuristic): after an over-cap take/reserve, `_defer_or_finish_discards` sets **`pending_discard_pid = ai_pid` and RETURNS WITHOUT finishing the turn**. A pending discard keeps `phase=="playing"`/`turn==ai_pid`, so **`from_game_dict` maps `pending_discard_pid` → DISCARD phase** (turn = AI seat) and the EXISTING `mk_room_state` `ai_search` block ships that DISCARD-phase compact state UNCHANGED — the take was logged so `ply` advanced, tripping `Spender.jsx`'s **ply-keyed** client-AI effect, which auto-re-searches and submits a `{type:"discard"}` `ai_move`. The handler validates it (legal in the DISCARD state via `move_to_action`∈`legal_actions`), applies it with `_apply_ai_discard` (one token → bank, logged), loops until ≤10, then `_finish_turn`. **`_schedule_ai_discard_fallback`** arms a `CLIENT_AI_TIMEOUT`(8s), **ply-guarded** watcher after each deferral: if the client never answers, the (now reserved-aware) heuristic finishes it — so the whole path **degrades to today's behavior on any client failure** (the safety guarantee). **NO client or WASM change needed** (the deployed website wasm ALREADY searches DISCARD roots per the July Rust fix; the worker already converts any action; the effect already re-fires per ply). Backend-only → Render deploys on `**/*.py`. Test `test_ai_run_turn_defers_discard_for_client`. Note: the defer is variant-agnostic (S/N/PV) but only benefits **N** — S's client search (`kind:"search"` → `root_visits_until_leaf`) still one-hots H3 discards, so S's routed discard == the old heuristic anyway (no regression).
- **wwsd userscript v0.9.30 — failure logging (`WWSD_N.logFailures()`).** Every autoplay move that doesn't commit is recorded on the per-game log's `failures[]` (ply, intended action, seat state, retry, gave_up) at all four `tick()` failure sites: **move_missed** (canvas click didn't advance the turn — the reserve-miss case, carries `action_kind`), **discard_missed**, **subdecision_manual** (unknown job bailed to manual), **exception** (claimNoble/discardSubDecision/tick threw). Rides along in the ⤓ Logs export.
- **wwsd userscript v0.9.31 — chat capture FIXED to spendee's REAL schema (VERIFIED live).** A `listCollections()` dump proved the v0.9.29 auto-detect captured NOTHING: chat is **NOT its own collection** — it's the **`conversation[]` array embedded in the `rooms` collection doc**, linked by **`room.gameId === game._id`**; each entry `{ isSystem, userId, name, content, createdAt }` with **NO `_id`**. The old code explicitly SKIPPED the `rooms` collection and only read top-level docs. Now `logCaptureChat` reads `_roomForGame(g).conversation`, skips `isSystem` lines, dedups by `(createdAt|userId|content)`, text field = `content`. `chatProbe()` previews the current room's conversation (verified: returns the sent messages). `CONFIG.CHAT_COLL` kept as a flat-collection override escape hatch. (Both v0.9.30/0.9.31 are wwsd-only → no CI/prod surface; **reinstall in Tampermonkey** — the `@version` is the tell.)

### Session (June 29 2026) — eval-axis screens: FEATURES + VALUE-TARGET both saturated for the champion
Two independent, cheap "harvest → ablation/gate" screens, both NEGATIVE for raising N, both pointing the
same way: **the remaining lever is the training DISTRIBUTION, not the evaluation.** Reusable tooling on the
rust-search worktree + `az_run`: `harvest_attn_v{3,4}` / `harvest_attn_val` (net_attn_3 self-play logging
candidate features / the search root value; a `game` id col for leak-free game-split), `gate_attn_attn`
(attn-vs-attn paired-CRN gate), `ablate_v{3,4}.py` (a small MLP distill predicting the OUTCOME, leave-one-
IN/OUT column-zeroing configs; the box has <800MB free + no pandas, so the loader STREAMS the CSV straight
to the GPU), `train_attn.py` gained a `value`-column/`BETA` value-target blend + a warm-start JSON loader +
a low-RAM streaming/`MAXROWS` parser (the old list-of-floats parse peaked ~2.8GB and OOM'd).

- **Eval-FEATURE enrichment is saturated ON THE NET (do not relitigate these four).** Held-out-outcome-AUC
  ablation over net_attn_3's v1 features: per-card **deck-unlock**, **post-buy-unlock**, **opponent-model**
  (opp eng/nob/tempo), state **fork-count** ALL fail to clear the bar (full vs v1only ≈ −0.0002; same even
  restricted to the uncertain ply≤28 regime). Only deck-unlock flickered +0.0007 (~1σ). Reason: the
  attention mechanism already computes board-card cross-aggregates, so explicit versions are redundant.
  **CAVEAT: the screen runs on SELF-PLAY data → it is structurally BLIND to the racer weakness** (a
  distribution problem); a flat feature screen on self-play cannot evaluate that. Memory `spender-v3-feature-screen`.
- **#3 value-bootstrap raises the FLOOR not the CEILING (RESOLVED).** Extend AlphaZero's policy-distillation
  to the VALUE head: value target = `(1-β)·outcome + β·search_root_value` (the denoised verdict the 128-sim
  PUCT *concluded*, vs the raw win/loss). From-scratch it beats the outcome-only baseline **+0.077, FLAT
  across 256/512/1024 sims** (transfers past the knee to ~20k) — the OPPOSITE of the S leaf-swap precedent.
  BUT warm-fine-tuning the CHAMPION toward its own search values gives NO gain (β=0.3 vs ship 0.463, β=1.0
  0.468, β1.0==β0.3 0.498; control β=0 ≈ ship 0.489): search-value is a more EFFICIENT target (helps an
  under-fit head catch up) but ship already sits at that fixed point from its outcome-trained loop. **KEEPER:
  use β≈0.3 in any FRESH retrain** (better/faster value signal while the head is being built; keep β<1 in a
  loop so the outcome anchor prevents value drift). Memory `spender-value-bootstrap`.
- **Blind (deck-top) reserve — a structural MCTS blind spot, not a tuning miss.** The bot never blind-reserves
  even though it's legal (`engine.A_RES_DECK` = actions 43–45). Determinized PUCT can't value it: (1) the deck
  is reshuffled per sim and the tree keys the child by ACTION not drawn card, so all blind draws MERGE into
  one node → the move's convex/upside-tail payoff (game-winning when stuck/behind on a dead board) is
  collapsed to a mediocre mean it can't plan around; (2) the opponent is modeled as knowing everything, so the
  hidden-information value is invisible. Near-unfixable without belief-state / chance-node (expectimax-over-
  draw) search; niche → not worth it. Same CLASS as the denial/racer blind spots (perfect-info determinization).
- **Per-level deck (the user's idea) — passed the flat-MLP AUC screen but WASHED in play (do not relitigate).**
  N has NO explicit deck features (only an aggregate, level-blind term inside `engine_value`). `features_tokens_v4`
  adds STATE groups: per-level×color demand (P), aggregate control (G), per-level counts (N3). The flat-MLP screen
  liked it (full vs v1only +0.0033 ~3 SE; level-split onlyP−onlyG +0.0005/+0.0011 marginal), BUT on the real
  AttnNet the value-AUC was near-tied (+0.0010) and the **PLAY A/B washed: v4net vs v1ctl 0.533@256 → 0.507@1024**
  (decays with sims → ~0 at prod's ~20k; sanity v1ctl-vs-ship 0.40 healthy). The attention net already extracts the
  deck signal from the `engine_value` tokens, so explicit deck features help a weak FLAT learner but NOT the real
  architecture. **NOT a keeper.** GOTCHA (cost an hour): `train_attn.py` didn't skip `harvest_v3/v4`'s leading
  `game` column → trained on features shifted one slot → train/serve mismatch → a FAKE 0.66→0.76-GROWING result;
  the **sanity control (v1ctl-vs-ship = 0/400) caught it**. Fixed (`f0` skip); `data_attn_val.csv`/the #3 nets were
  unaffected (no game col). Lesson: always gate vs a known reference — a bug can fake a play gain AND a transfer curve.

### Session (June 30 2026) — EXPLOITER net vs champion N = NO EXPLOIT (clean mirror; DO NOT relitigate)
The greenlit research bet from `spender-racer-league-deadend` (train a net whose SOLE objective is to BEAT the
deployed attention-net champion **N**, AlphaStar-style, to DISCOVER the human's racing exploit) was run
(`az_run/loop_exploit.sh`, Rust `selfplay_attn_exploit.exe` + `gate_attn_attn.exe`, 10 iters). **Result: no
exploit found — N is unexploitable by a same-arch warm-start mirror.**
- **Setup:** the exploiter is a **byte copy of ship N** (`cp net_attn3_ship.json exploit_best.json`) — SAME
  card-set-attention architecture, SAME 24-feat tokens, SAME initial weights. The ONLY differences are the
  training *distribution* and *target*: each iter the best exploiter plays **1500 games vs the FIXED ship**
  (`self_frac=0`, recording ONLY its own moves + search root value), heavy early-ply exploration (`temp=15`),
  warm-from-ship fine-tune (LR 5e-4, value-target β=0.3, rolling 2-iter window, MAXROWS 100k), gate 300g@256
  vs ship, promote iff `cand_vs_ship > best`.
- **All 10 gated results bounced in 0.45–0.51 with NO upward trend:** 0.491 / 0.481 / 0.478 / 0.471 /
  **0.5083 (iter 5, the only "promotion", within noise of 0.50)** / 0.489 / 0.505 / 0.449 / (iter 9) / **0.456
  (iter 10)**. best_wr ended at **0.5083** — a dead-even mirror. (Train-time win-rate ~0.36–0.39 is just the
  temp-15 exploration depressing play; the clean gate is the truth and it says EVEN.)
- **Diagnosis (exactly the pre-flagged risk):** a net with N's architecture, N's features, initialized to N's
  weights, taking small gradient steps on games against N has **no structural asymmetry to exploit** — gradient
  just walks around N's own policy basin and the gate sits at ~0.50. This is the "same-arch exploiter mirrors
  to ~0.5 without asymmetry" failure mode called out in `spender-racer-league-deadend`.
- **Conclusion:** a real exploiter REQUIRES injected asymmetry the mirror loop deliberately omitted — enriched/
  racer-aware features, a racer-biased reward or opponent track, a **cold (from-scratch) init** so it can't fall
  back into N's basin, or a different head/arch. As configured this is a clean NEGATIVE control proving N is not
  exploitable by a mirror of itself. Reusable harness kept: `loop_exploit.sh` + `selfplay_attn_exploit.exe` +
  `gate_attn_attn.exe`. Memory `spender-racer-league-deadend` (updated with this outcome).


### Hard-won conclusions — DO NOT relitigate
These cost many self-play/training cycles to establish:
- **Eval-weight tuning is saturated.** One gain (0.725 vs original), nothing since. The first run captured it.
- **Evaluation quality is NOT the bottleneck.** Static-eval accuracy plateaus ~0.65 *regardless of model class or features*: an **MLP** (more capacity) and **Stage 1c richer features** (per-colour bonuses/tokens, reachability/threat) both gave the same ~0.64–0.66 and were reverted. The missing information (future deck draws, deep lines) isn't in any static snapshot — it needs **lookahead**. **The remaining lever is SEARCH, not evaluation.**
- **Self-play is blind to blocking/contested tactics** — its opponent never threatens coherently, so denial never pays off and those features (`contested_weight`, `block_urgency_gate`) train toward off. A scripted `strategist.py` opponent is competent (~greedy strength) but **MCTS saturates it 12–0**, so it can't measure improvements above current strength either. **The only reliable judge of the human-exploitable weakness is a human playtest.**
- **Next lever = search**: (1) audit `_get_all_moves` pruning (winning lines may never be enumerated), (2) tree reuse between moves + UCB sweep, (3) AlphaZero-style policy head + real exploration (the eventual cure for tactics, biggest build). **UPDATE (June 2026): the search lever is realized by variant S** — `v_state` V(state) + determinized PUCT on the H3 eval — at **0.733 vs greedy H3 / 0.758 panel**, confirming search (not eval) was the bottleneck. See "Variant S" above.
- **The EVAL AXIS is saturated for the champion attention net N — confirmed on BOTH sub-axes (June 29, do not relitigate; see the "Session (June 29 2026)" entry above).** (a) Eval-FEATURE enrichment: four candidate groups all fail the held-out-AUC ablation over N's features (attention already does board-card cross-aggregates). (b) Value-TARGET (search-value bootstrap, #3): raises a from-scratch net (+0.077, transfers) but NOT the champion (warm-from-ship washes — N is already at the fixed point). So neither richer inputs nor a sharper value target moves N. **The remaining lever is the training DISTRIBUTION** — a racer-track league targeting the confirmed (human-playtest) racer/early-midgame weakness self-play can't generate. KEEPER for any fresh retrain: train with the β≈0.3 search-value target.

### Move handler error hierarchy
```python
if not r:                          → "game not started"
elif r.get("status") == "over":    → "game is over"
elif r.get("status") != "playing": → "game not started"
else:
    if g.get("phase") == "over":   → "game is over"
    elif g.get("turn") != pid:     → "not your turn"
    # per-turn pending-action guards (move must resolve these first):
    elif g.get("pending_noble_pid")   == pid and type != "pick_noble": → "must choose a noble first"
    elif g.get("pending_discard_pid") == pid and type != "discard":    → "must discard down to 10 gems first"
```

**Pending-action state lives in the `game` dict** (not transient message fields), so it survives saves/reconnects and is enforced server-side: `pending_noble_pid` (multi-noble choice) and `pending_discard_pid` (over-10 gems). Both are set when the condition arises and cleared when resolved. The frontend derives `needsNobleChoice`/`needsDiscard` from these game-state keys — a stray `room_update` can't clear an unmet requirement.

**Discard undo**: any action that overfills past 10 gems (`take_gems`/`reserve`) first deep-copies the pre-action game into `g["pre_discard_snapshot"]` (only persisted when it actually overfills). The discard modal offers "↩ Undo turn" → `move type: "undo_discard"`, which restores `r["game"]` from the snapshot (reverting the take/reserve **and** any partial discards) and re-opens the player's turn. The snapshot is popped when the discard completes normally, and (like `pending_discard_pid`) it's part of saved game state so undo survives a reconnect.

---

## Frontend architecture (Spender.jsx)

### Screen flow
`"auth"` → `"browser"` → `"waiting"` (2-player) | `"game"` (vs-AI goes directly)

### Message handlers that transition screen
`inGame(status)` = status is `"playing"` **or** `"over"` (a finished game stays on the game screen so the winner/review UI shows; only a not-yet-started game goes to `"waiting"`).
- `"created"`: → `"game"` if `inGame`, else `"waiting"`
- `"joined"`: → `"game"` if `inGame`, else `"waiting"` (mirrors `"reconnected"`)
- `"reconnected"`: → `"game"` if `inGame`, else `"waiting"`
- `"room_update"`: → `"game"` only if `inGame` AND screen is not already `"game"`

### Key derived state (hoisted ABOVE all useEffect hooks — required to avoid TDZ)
```javascript
const game = roomData?.game;
const me = game?.players?.[myId];
const myTurn = game?.turn === myId && game?.phase === "playing";
const myBonuses = me ? bonusesFrom(me.purchased) : emptyGems();
const aiThinking = game?.ai_player && game?.turn === game?.ai_player && game?.phase === "playing";
```
**These must stay before all `useEffect` hooks** — they appear in dep arrays and must be initialized first or Firefox throws a TDZ ReferenceError in production builds.

### WebSocket URL
`WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws"` — **baked in at
build time** (NOT derived from `window.location`). `HTTP_BASE` is derived from it.
This is why a separate front-end host (e.g. the Cloudflare staging build) can point
at the prod backend just by setting `VITE_WS_URL=wss://splendid-nelz.onrender.com/ws`
(see "Staging environment" below).

### Reconnect tokens
Stored in `localStorage` as `spender_token_${roomId}_${myId}`. Sent on reconnect as `{action: "reconnect", token}`.

### Identity
For a logged-in user `myId === user.id` (account id = `gen_token(10)`); a guest
gets a random `uid()` in `localStorage.spender_myId`. The room player id (`pid`)
sent in the WS path IS `myId`, so a created game's `player1_id`/`host_id` equals
the creator's `myId` (= account id when logged in). `normalize_room` uppercases.

### Session validation on load (stale-token fix)
The frontend restores its "logged in" state from `localStorage` (`spender_user`),
but a stored `session_token` can be silently dead — it expires after 7 days, and
there's **one token per user**, so a login on another browser/device supersedes the
old one. A dead token downgrades every authenticated request to anonymous while the
UI still shows you logged in (e.g. the Books "Edit ranking" button vanishes for the
admin until a re-login). Fix: the loading effect validates the token **before
routing**. **`GET /auth/session?token=`** (thin wrapper over `core.auth.get_user_by_session`)
returns `{ok:false}` for a definitively-dead token → the app clears the stale login
and routes to the auth screen; `{ok:true,user}` → stays logged in and refreshes the
cached identity (name/is_admin). A network error/timeout NEVER logs you out (a blip
must not), validation runs only after the backend is confirmed reachable, and it
degrades safely if `/auth/session` isn't deployed yet (404 → stay logged in).

### Lobby UI (June 2026)
- **AI opponent picker** is a floating dropdown (`.ai-picker`, `position:absolute`
  in a `.ai-picker-wrap`), NOT inline — inline reveal shifted the whole page.
  One "Play vs AI ▾" toggle reveals A/B/C/C2/Z; picking one closes it.
- **Matchup display**: game cards show `player1_name vs player2_name` (AI shows as
  `AI (X)`); backend `list_user_games` returns both names + `you_are_p1`.
- **Cancel own open game**: open games where `g.host_id === myId` show Cancel
  (you only Join *others'* games). `list_open_games` returns `host_id`.
- **In-progress section is ALWAYS "Active Games", never "Resume".** Two sections —
  **Open Games** (`/games`; your own open lobby shows Return + Cancel) and **Active
  Games** (`myGames.filter(status==="playing")`). The localStorage fallback card
  (saved `spender_roomId`, shown to guests with no `/games/mine`) is ALSO titled
  "Active Games" and guarded (`!inLists && !browserLoading && !hasActiveGames`) so it
  never co-renders with the real Active Games section (no duplicate header). There is
  no "Resume" *section* heading anymore — only the per-card **Resume** *button*.
- **`.action-bar` has `min-height:62px`** so the turn badge row doesn't shrink
  when the contextual button (Take Gems / Buy) is absent.
- **Reserve = click a card then the gold coin** (bidirectional: gold-first arms
  `reserveArmed`, then click a card). No Reserve button. The gold token in the
  bank lights/pulses (`.reserve-ready`) when a card is selected and a slot is free.
- **Deck cards**: sized to match dealt cards (88px wide, min-height 120px). Level
  numeral (III/II/I) appears inside the deck outline above "DECK". No "Level I/II/III"
  panel titles — they were removed to reduce vertical space.
- **Move log = id-only + a static catalog (June 2026; `e4beb19`).** `_log_move` stores only
  `card_id` per buy/reserve (+ `noble_id` on noble claims), NOT the full card dict — entries are now
  ~one short string, so the **50-cap was raised to 500** and `game["moves"]` holds the WHOLE game (and
  every `room_update` WS payload shrank). Resolve ids via `main.card_catalog()` (deterministic
  id→{level,points,bonus,cost} for all 90 cards; the deck is fixed). Frontend: a `cardsById` useMemo
  built from visible state (board + both players' purchased/reserved) resolves the log ids — complete by
  construction (a logged card is always somewhere in the live state). **Backward-compatible**: old saved
  games carry verbose `mv.card`, new ones `mv.card_id`; `renderMove` reads `mv.card || cardsById[mv.card_id]`.
  Clickable condition is now that-resolved-card. **Blind-reserve redaction strips `card_id` too** (the id
  alone reveals the hidden card via the catalog).
- **Admin game-dump endpoint `GET /games/{id}/full`** (admin-gated): returns the complete persisted game
  (final state + full id-only move log) + a `card_catalog`, a self-contained dump for offline analysis
  (prefers the live in-memory copy, falls back to the DB row). Prod data lives in Turso (no local access),
  so the workflow is a browser console snippet that reads `spender_roomId`+`spender_user.session_token`
  from localStorage, fetches the endpoint, and downloads the JSON (clipboard `copy()`/chat-paste choke on
  the ~20-30KB blob → download-to-file + Read is the reliable path). Used to analyse real vs-S games.
- **Game reconstruction + per-turn S re-scoring (`games/spender/ai/az/replay.py`; June 2026).** A finished
  game can be replayed move-by-move offline and re-scored with variant S at every turn. Two additive,
  default-safe captures made this possible (without them the per-turn board — S's biggest eval input — was
  unrecoverable, because the deck is shuffled in place and popped with NO seed stored):
  1. **`main._capture_setup(g)`** snapshots the dealt **initial board / deck-order / nobles (ids only)** into
     `g["setup"]`, called in BOTH create paths (vs-AI + multiplayer start) right after the nobles are dealt.
     ids-only → compact; resolved via `card_catalog()`. **Kept off the wire** — `mk_room_state` strips
     `setup` from the broadcast (static, client-unused, ~75 ids), but `save_game` persists it and the `/full`
     dump serves it. (No new info leak: `game["decks"]` — the remaining draw order — is already broadcast.)
  2. **Discards are now logged** (`_log_move(... "discard", color=...)`): the human handler logs on COMMIT
     (an `undo_discard` restores the pre-take snapshot, so the entries correctly vanish), and the AI path
     logs each `_ai_discard_one` — which now **returns the discarded colour** (the MCTS-sim applier ignores
     it). The primary `take_gems`/`reserve` is logged BEFORE its discard loop so the newest-first log
     reverses to correct chronological order. (Buys never overfill; payment/spends stay derivable.)
  - **`replay.py`** rebuilds the initial game dict from `setup`, re-applies the logged moves (payment via
    `calc_spend`; turn advancement reuses `main._finish_turn`; nobles applied straight from the log, single
    auto-claims included), converts each turn-start to an AZ `State` via `engine.from_game_dict`, and emits
    `v_state.value` + the 5-component breakdown. CLI:
    `python -m games.spender.ai.az.replay dump.json [--seat ai|mover|0|1] [--csv out] [--json out]` (loads a
    `/full` dump, a `state_json` row, or a bare game dict). **2-player only** (v_state is). A game created
    BEFORE the snapshot (LBBMRC, all pre-deploy prod games) has no `setup` → `evaluate` raises a clear error;
    only the points+noble proxy is available for those. Every game created after deploy is fully replayable.
  - **Test** `games/spender/tests/test_replay.py`: a **differential round-trip** — play random AZ games, emit
    the log in main's EXACT persisted format (synthesizing the silent single-noble auto-claims + deck-reserve
    `card_id`/`from_deck`), reconstruct from `setup` alone, assert the replayed state matches the engine at
    every turn with **deck order compared exactly** (60 games) + direct guards on each `main.py` change.
- **In-game review + turn-by-turn replay (the game-review feature; June 2026).** Every game in the lobby
  **History** column has a **Review** button (right of the score) that opens a READ-ONLY review of that game
  where you can rewind to any turn. Builds directly on `replay.py` (above).
  - **Backend — `GET /games/{id}/review`** (`main.py`; session-gated AND restricted to a player who was in
    the game — `viewer in game["order"]`). Returns `final` (the end board, redacted-from-the-viewer +
    `setup`-stripped via `_review_view`) + `snapshots` (one renderable game dict per turn, from
    `replay.reconstruct` → `replay.turn_snapshots`, each redacted via `_review_view`). `snapshots` is **null**
    for a game created before the `setup` snapshot (review still shows the final board, just no turn nav) or on
    any reconstruction glitch — `_build_review_snapshots` swallows `ReplayError`/anything. Loads in-memory
    first, else the DB row (mirrors `/full`). **Player-count-agnostic** (only `replay.evaluate`/v_state is
    2-player; reconstruction isn't), so multiplayer games review too. Does NOT need numpy/AZ. Test
    `games/spender/tests/test_review.py` (pure helpers + an endpoint e2e is in scratchpad, not committed).
  - **Frontend — read-only replay mode (`Spender.jsx`).** `enterReview(id)` does an HTTP fetch (NO WebSocket;
    synthesizes `roomData` from `final`) for a History entry; the end-game "Review Board & Log" button also
    calls `enterReview(roomId)` (the `haveLive` path keeps the live socket, just adds snapshots). State
    `reviewing`/`replaySnapshots`/`replayTurn` is declared **BEFORE the derived `game` block** (TDZ — same
    hard rule as the other derived state). `liveGame = roomData.game`; the **BOARD** renders
    `replaySnapshots[replayTurn].game` (or liveGame), but the **move log + `cardsById` stay sourced from
    liveGame** so every turn stays clickable and logged cards resolve even on an early board.
  - **Read-only is enforced, do not regress:** `myTurn`/`aiThinking`/`needsDiscard`/`needsNobleChoice` are all
    gated `!reviewing`, and the fly/flash `useEffect`s early-return on `reviewing` (no spurious animations
    while rewinding). Nav chrome uses **`reviewChrome = reviewing || liveGame.phase==="over"`** (the LIVE
    game's phase, NOT the rewound snapshot's) so a historical `"playing"` snapshot can't leak the live
    Abandon/Menu chrome. The visibility/tab-back reconnect is also gated `!reviewing` (a History review has no
    socket to reconnect).
  - **Snapshot semantics (the load-bearing index rule): `snapshots[idx]` is the board AFTER move `idx-1`** —
    idx 0 = the initial board (before anyone moved), idx N = the final position. The log (newest-first) renders:
    an **unclickable** `🏆 X won the game` label at the top (derived from `game.winner`; ties → "A & B tied"),
    each **move row** jumping to `goToTurn(turnIdx + 1)` (the board AFTER that move) and highlighting **only its
    PRIMARY row** (`take_gems`/`buy`/`reserve`) so a buy-plus-noble turn lights ONE row, and a clickable
    `▶ Game started` at the bottom → `goToTurn(0)` (the initial board). The action-bar banner
    (`renderReplayBar`) describes the move that PRODUCED the shown board (`snapshots[idx-1]`): `Game start` /
    `Turn k / N · {mover} · {move}` / `Final position`, with Prev/Next/Latest.
- **Loading screen**: 250ms fast-path — AbortController fetch with 250ms timeout;
  if server responds in time → skip loading screen entirely; if not → show spinner
  + progress polling. `showLoading` state gates the spinner so a blank flash never
  appears on fast connections.

### Multiplayer (2-4 players), History & 3-column lobby (June 2026 — LIVE on prod)
- **Spender seats 2-4 humans** (AI games stay 2-player). The engine was already
  player-count-agnostic (`game["order"]` + modular `_advance_turn` + single-winner
  `_resolve_winner` with the points/fewest-cards tiebreak); the additions are setup +
  plumbing: `MAX_PLAYERS=4`; `_bank_for(n)` scales the gem bank to standard Splendor
  (**4/5/7** per colour for 2/3/4p, gold always 5) at START; nobles already `players+1`.
  `join` accepts up to 4 for **OPEN, non-AI lobbies only** (rejects joining an AI game or
  an already-started game). The host starts when **≥2** present (the existing `start`
  flow). DB gained nullable **`player3/4_id`+`player3/4_name`** columns (in CREATE for
  fresh DBs + a tolerant ALTER for the prod table); `save_game` / `list_user_games` /
  `list_active_games` handle all four seats. Tests in `test_game_logic.py`
  (`_bank_for`, nobles, 4-seat turn cycle, single winner among 4, final-round around all
  seats). Dormant-safe: the backend shipped to prod first, invisible until the frontend.
- **History** — `GET /games/history` → `list_user_history(user_id)`: your FINISHED games
  (`status='over'`, any of the 4 seats), newest first, each with per-player final scores
  (`_calc_points`), a winner flag, `is_you`, and `you_won`. Session-gated (like
  `/games/mine`). Frontend renders **"Won/Lost vs <opponent(s)>  your-their"** (no
  repeated username; "their" = the top opponent's score for 3-4p). Retained 30d for a
  registered player (guest-only 24h), per `cleanup_stale_games`.
- **3-column lobby** (`.lobby-grid` = `grid-template-columns:1fr 1fr 340px`): **Open
  Games | Active Games | History**, each its OWN column so a long History never pushes
  Active down. **Explicit `grid-row` on EVERY item is REQUIRED (do not regress):** the
  DOM order is Open, History, Active, so column-only placement makes the sparse auto-flow
  cursor (past col 3 after History) wrap Active to row 2 ("pushed down"). Each column's
  `.game-cards` is **capped to the viewport and scrolls internally like the move log**
  (`max-height:calc(100vh - 230px);overflow-y:auto;scrollbar-gutter:stable`) — desktop
  3-col only. Collapses to 2-col <1280px (History spans row 2), 1-col <780px. **Active
  Games ALWAYS renders** (with a "No games in progress." empty-state) so the middle
  column never gaps.
- **Open Games** show the lobby size **`x/4`** (`list_open_games` returns `player_count`
  + `max_players`). **Active Games** list each player **one-per-line** (`.matchup`,
  you first then `vs <opp>` per line). The Classic/Long + Create + vs-AI button row is
  **centered** (`.browser-create{justify-content:center}`); the refresh button is a
  **fixed 30×30** box so the ↻↔spinner swap doesn't resize/shift it.
- **Full-width banner (flush, do not regress):** the lobby header lives OUTSIDE the
  centered max-width `.browser` (a direct child of `.app`) so its border spans the
  screen — three sections, **back left / game name centered / user right** (left+right
  `flex:1`, title `flex:0`). Same for CoC (`.coc-top-lobby` moved outside `.coc-wrap`).
- **Home-exit button reads "← Back"** everywhere (Spender / CoC / Where Wolf? / Books);
  in-game "← Menu" / "Back to lobby" buttons are unchanged (they navigate within a game).

### Cancel / session-expiry gotcha (do not regress)
`POST /games/{id}/cancel` authorizes by a live session **OR** the host's
`player_id` (open games are public waiting rooms; `host_id` is already in
`/games`). This is deliberate: `get_user_by_session` rejects *expired* tokens, so
a session-only check made cancel fail silently after expiry (and the same expiry
quietly empties "Your Games"). The frontend `handleCancel` only clears the
`spender_roomId` resume pointer + reconnect token **after the server confirms the
delete** (`data.ok`); on failure it toasts the reason. Never clear local resume
state before confirming the delete.

### Tab-back + cancelled-join fixes (June 2026; do not regress)
- **Tab-back only rejoins ACTIVE games.** The visibilitychange reconnect (iOS kills backgrounded
  WS) now also guards `screenRef.current === "game"` — without it, tabbing back while in the
  lobby/waiting re-opened a stale waiting room (the "dumped into waiting" report).
- **Joining a cancelled game is rejected.** On WS connect the handler `ROOMS.setdefault`s a fresh
  empty room for ANY id (needed so the creator can then `create`). After a host cancels (room
  popped from ROOMS + deleted from DB), a second client connecting to that id fabricated a
  **phantom hostless room**, and `join` then succeeded into it → neither player was host →
  un-startable (the bug the user hit). Fix: the `join` action rejects when
  `not r.get("host") or r.get("game") is None` ("this game is no longer available"); the frontend
  error handler clears the stale resume pointer and `fetchGames` to drop the dead game. Verified
  e2e (create→cancel→join-rejected).

### Lobby Open/Active split + Resume card (June 2026; do not regress)
- **The lobby is split into "Open Games" (top) + "Active Games" (below), with NO overlap.** "Open
  Games" (from `list_open_games` — ALL `status='open'` lobbies) is the SOLE home for not-yet-started
  lobbies: the owner (`g.host_id === myId`) gets **Return** (`handleContinue`, re-enter to start once
  someone joins) **+ Cancel**; everyone else gets **Join**. "Active Games" filters `myGames` (from
  `list_user_games`, which returns the user's `status != 'over'` games) to **`status === "playing"`
  only**. Before the split, a user's own open lobby showed in BOTH lists (because `list_user_games`
  also returns open games) — that's the overlap this removed. Active Games is intentionally NOT
  length-filtered (you want all your in-progress games); **Open Games IS** filtered by the Classic 15 /
  Long 21 toggle (`openGames.filter(g => (g.win_points||15) === winPoints)`). Frontend-only — the
  backend endpoints were already returning `status` per game.
- **The Resume card no longer flashes on Back-to-Menu.** The `Resume` fallback IIFE (shows a saved
  `spender_roomId`+token that isn't in your fetched lists) is gated on **`!browserLoading`** AND hidden
  when the saved id is in **`openGames` OR `myGames`** (not just `myGames`). Without the `browserLoading`
  gate it flashed right after creating a game: Back-to-Menu re-rendered the browser with STALE lists
  before `fetchGames` resolved → Resume appeared → vanished once the new game landed in Open Games. The
  `openGames` check also removes a **guest-side duplicate** (guests have an empty `myGames` because
  `/games/mine` is logged-in-only, so a guest's own open lobby lives only in `openGames`).
- **In-game "Target: X" label** (`.target-label`) is `font-size:1.05rem` (bumped 50% from `.7rem`),
  shared by the desktop `.hint-col` and the mobile action-bar placements.

### Responsive game layout (June 2026 — the big UI overhaul; do not regress)
The game screen has THREE layouts driven by width; all CSS lives in the one `css`
string in `Spender.jsx`. **The base styles are the small/compact foundation; the
DESKTOP look is added in `@media(min-width:901px)`** (an inversion worth knowing —
editing base affects phone/tablet, not desktop):
- **Desktop (`@media(min-width:901px)`)**: `.app.game-screen{height:100vh;overflow:hidden}`
  locks the screen to the window (no page scroll). `.game` is a 2-col grid
  `1fr 560px` (board | sidebar) that **needs an explicit definite height**
  (`flex:none; height:calc(100vh - 48px)`) **AND `grid-template-rows:minmax(0,1fr)`** —
  both, and it took 3 tries to learn why. `flex:1` yields a `flex-basis:0%` that is NOT
  a definite height the grid `fr`/`minmax` can resolve against, so the row grows to its
  tallest content (the recent-moves list) and pushes past the screen; the explicit
  height + `minmax(0,…)` bounds the row to the viewport. **The SAME bound must be
  repeated on the inner `.game-sidebar` grid** (`grid-template-rows:minmax(0,1fr)`) —
  bounding only the outer `.game` left the sidebar's own auto row growing to the moves,
  so the log was CLIPPED, not scrolled (the "EXACT SAME ISSUE" recurrence). **Belt-and-
  suspenders:** the move log ALSO carries an explicit `max-height:calc(100vh - 140px)`,
  so it bounds + scrolls even if the nested-grid height chain ever fails to propagate.
  `.game-main` is a 3-col / 2-row grid
  `grid-template-columns:auto 1fr 132px; grid-template-rows:auto 1fr`: row 1 =
  nobles box (horizontal, `data`-less) + an **actions box** (turn hint + Take/Buy/✕,
  right-aligned); row 2 = the **levels** (`grid-column:1/3`, `1fr` so the 3 card rows
  spread flush to the bottom via `justify-content:space-between`); the **gem bank** is
  a vertical column (`grid-column:3; grid-row:1/span 2`) with the gold/wild token
  FIRST (top). The **sidebar** is itself a 2-col grid (players left | recent moves
  far-right), both `grid-row:1` full-height — player boxes `flex:1` (top & bottom
  halves), the move log `flex:1; min-height:0` so it **scrolls internally** instead of
  growing the page. Card size is driven by `--card-w/--card-h` (≈144×185) set on
  `.game-main`.
- **Tablet/phone (`@media(max-width:900px)`)**: single column; the nobles and an
  **actions box** sit side by side as TWO SEPARATE boxes — `.nobles-panel.panel` goes
  transparent (just a flex row), `.nobles-row` gets its own tight box hugging ONLY the
  nobles, and `.board-actions` is the box to its right holding the win-points **Target**
  label (`Target: 15/21`; `justify-content:flex-start` pins it to the TOP so it doesn't
  shift up when the Take/Buy/✕ buttons appear below it) + the controls. The hint is
  dropped here (no room beside the nobles); the box is only rendered while
  `game.phase !== "over"`. **Cascade gotcha (do not regress):** the mobile rules use
  higher-specificity selectors (`.nobles-panel .board-actions`, `.nobles-panel.panel`)
  because the unconditional base `.board-actions{display:none}` / `.panel{…}` rules
  appear LATER in the stylesheet — at equal specificity they'd win, and
  `.board-actions{display:none}` had been hiding the actions box on mobile ENTIRELY.
- **Phone (`@media(max-width:600px)`)**: board-first order; the nav scrolls (not
  fixed); player panels collapse to a one-line `cards | gems` summary that taps to
  expand reserved cards; the move log shows the most-recent entry + a tap-to-expand;
  L3/L2/L1 merge into one box.
- **Card sizing is fully CSS-driven** — `CardView`/empty slots set NO inline width;
  `.card`/`.card-slot`/`.deck-pile` use `var(--card-w/--card-h)`, and
  `.level-row>*{flex:1 1 0;max-width:var(--card-w)}` makes a full level (deck + 4
  cards) shrink to fit any column width.
- **CSS-grid "staircase" gotcha (hit TWICE — board + sidebar):** if DOM order places
  a later element in an EARLIER column (descending columns), grid's *sparse* auto-flow
  refuses to backtrack and drops it to a new row → a diagonal staircase. **Fix: pin
  every grid child to an explicit `grid-row`.** Relatedly, `grid-row:1/-1` needs an
  explicit `grid-template-rows` or `-1` collapses to line 1 (item spans only row 1).

### Proportional desktop layout rewrite + searched-eval / review overlay (June 25 2026 — do not regress)
The desktop game layout was rewritten to be fully PROPORTIONAL (supersedes the desktop part
of "Responsive game layout" above), and the admin S position-eval overlay gained a SEARCHED
value + now works in game review. All frontend in `Spender.jsx`; backend in `main.py` /
`ai/az/vsearch.py`. Live on staging AND prod.

**Proportional desktop (`@media(min-width:901px)`):**
- **One anchor drives everything: `--card-h:clamp(104px, 17vh, 205px)` on `.game`**, with
  `--card-w:calc(var(--card-h)*0.778)` (the prod 144:185 card aspect). EVERY desktop
  dimension is a `calc()` ratio of `--card-h` (ratios = old-full-size-px / 185), so the
  whole board scales as ONE unit and looks identical at 1280×720 / 1920×1080 / 2560×1600
  (clamp only floors/caps on extremes). This REPLACED the old fixed `1fr 560px` grid +
  `132px` bank + `≈144×185` cards + FIVE max-height breakpoints that STEPPED the board in
  discrete jumps (so it looked different per resolution).
- Grids: `.game` = `minmax(0,1fr) clamp(440px,32vw,560px)` (board | sidebar); `.game-main`
  = cols `auto 1fr calc(var(--card-h)*0.714)` (nobles | cards | vertical bank), rows
  `auto 1fr`; sidebar = `1.6fr 1fr` (players | log). The definite-height + `minmax(0,1fr)`
  chain on `.game` AND `.game-sidebar` (+ the move-log `max-height` belt) from the old
  section STILL applies — keep it (same clipping footgun).
- **Per-level card boxes:** each level row is wrapped in a `.level-panel` (a `.panel`,
  `flex:1`) so the three levels are individually boxed AND fill the column height; `.levels`
  packs them at the TOP with a fixed proportional gap (`justify-content:flex-start`), so
  spare viewport height becomes whitespace BELOW — NOT bigger inter-level gaps (uniform gaps
  were a hard request). Board cards hold a strict 0.778 aspect via a container query on
  `.level-row` (`container-type:size`, `width:min(slot, 100cqh*0.72)`) — true contain, no
  overflow. **Gotcha (do not regress): container-query units (`cqw`) on the RESERVED cards
  blew up the flex-basis circularly** (309px-wide cards); reserved cards use a plain
  `flex:0 0 calc((100% - …)/3)` + `--card-h`-relative content + `width:100%` on
  `.player-reserved`/`.reserved-row`, NOT a container query.
- **Player pills (the hard rules the user enforced):** gems (`.token-pill`) AND card
  indicators (`.bonus-pill`) are each fixed at **1/6 of the row** (`flex:0 1 calc((100% -
  …)/6)`) so a full set of 6 fills the row edge-to-edge; capsule-shaped
  (`border-radius:999px`), prod-shaped but BIGGER (height + dot/count, NOT just wider); the
  "N gems" total (`.gem-total`) is centered between the two rows. **Reserved cards are fixed
  1/3 of the row** (3 fill it, fewer left-aligned NOT stretched), 0.778 aspect, cost/pts/
  color sized to match the board cards' ratio.
- **Eval pill top-right:** the S position-eval pill (`.ai-pos-eval-row`, rendered by
  `renderAiEval` — split out of `renderAiValsToggle`, which is now just the Hide/Vals
  button) is `position:absolute` at the top-right of the actions box (the box is
  `position:relative`: `.actions-panel` desktop / `.nobles-panel .board-actions` mobile) so
  it never displaces the Target / buttons / hint. "Show vals" button label is just "Vals".
- **Layout-verify harness** (`webapp/_harness.mjs`, gitignored scratch — NOT committed): a
  Playwright script that extracts `baseCss` + the game `css` from the two backtick template
  literals, builds a MOCK game DOM (must include the `.level-panel` wrapper or per-level
  boxing/gaps measure wrong — a real bug this caught), renders at the target viewports, and
  measures + screenshots proportions / row-fit. The fast way to verify a layout change
  without a live game; row-fit must be measured by element CENTER, not `top` (buttons of
  different heights on one row have different tops). `npm run smoke` still gates blank-page
  / CLS on every push (run it in `webapp/` before pushing).

**Admin S overlay — searched eval + game review (`main.py` / `vsearch.py`):**
- The admin position-eval pill shows BOTH **`leaf`** (static `v_state.value`) AND **`srch`**
  (S's PUCT search ROOT value `sum(W)/sum(N)`, side-to-move perspective). `vsearch` gained
  `_root_value(search)`, `choose_action_value(s, seat, …)→(action, root_value|None)`, and
  `searched_value(…)`.
- The searched value costs NOTHING extra on the AI's turn and is fresh on yours: (1) the
  AI's move already searches → `_s_choose_move` uses `choose_action_value` and stores the
  root value; (2) on the HUMAN's turn `_schedule_s_searched_eval` runs a fresh `SERVE_TIME`
  (~4.5s) async search in the thread pool (guarded ONCE-per-ply via a `_s_eval_running`
  marker) and broadcasts. Both stamp `game["s_searched"]={value, ply}`; `mk_room_state` only
  emits `ai_position_eval_searched` when `s_searched["ply"] == len(game["moves"])` (a stale
  eval is never shown — the ply fingerprint validates the position). `s_searched` / `setup`
  / `_s_eval_running` are stripped from the broadcast game view.
- **Vals work in game review:** `_compute_overlay(game, persp, variant)` was EXTRACTED (per-
  card values + the static `ai_position_eval`, dispatching H/H2/H3/S; `{}` on exception) and
  is reused by BOTH `mk_room_state` (live) and `_build_review_snapshots` (per PLAYING past
  snapshot, computed from THAT turn's mover's seat) — so rewinding a finished AI game shows
  each turn's per-card values + static eval. STATIC only (no per-snapshot search → `srch` is
  hidden in review; one search per snapshot would be far too slow). Frontend:
  `aiCardValues` / `aiValuesPid` / `aiPositionEval` are derived state (hoisted above hooks,
  TDZ rule) that read the rewound snapshot when `reviewing`, else live `roomData`; the Vals
  toggle no longer hides on a finished game (so it shows while rewound to a playing turn).

### Session (June 25 2026) — tap-to-ping, "waiting for you" tab alert, reserved-card + actions-box sizing (SHIPPED to main; do not regress)
Four small Spender UI changes, all frontend-only except the ping relay (one backend WS action). Built in the
`forrestm_projects-sound` worktree (branch `sound`), pushed straight to `main`. The `sound` worktree is the
standing scratchpad for these one-off UI fixes.
- **Tap-to-ping a player (chime for you + them).** Clicking ANOTHER player's box (`.player-panel.pingable`,
  gated `!isMe && !reviewing`) plays a short rising two-tone WebAudio chime locally and sends
  `{action:"ping", target: pid}`. **Backend (`main.py` WS loop): the `ping` action relays
  `{type:"ping", from: pid}` to ONLY the target player's socket** (`tws = ROOMS[room]["sockets"][target]`,
  guarded `target != pid`); the clicker already played locally, so there's no echo-back. **VERIFIED with a
  4-client integration test: a ping reaches only the tapped player + the clicker — the other 2-3 players hear
  NOTHING** (do not "broadcast to the room" — that would leak to everyone). `playPing()` is a module-level
  helper (one lazily-created shared `AudioContext`, no audio asset) used by both the click handler and the
  `msg.type==="ping"` message branch.
- **"Someone's waiting for you" tab indicator (permission-free).** A `useEffect([myTurn, pinged])` gated on the
  Page Visibility API: while the tab is HIDDEN and (it's your turn OR a ping arrived), it FLASHES
  `document.title` between `Forrest Games` and `🔔 Your turn!` / `👋 Someone's waiting!` (~1.1s) and swaps the
  favicon to **`webapp/public/favicon-alert.svg`** (the tree + a red badge). Cleared the instant you return
  (`visibilitychange`→visible restores title/favicon + clears `pinged`). New `pinged` state set only when a ping
  arrives AND `document.hidden` (so a stale ping doesn't fire later). NO Notifications API (no permission prompt,
  by user choice). Spender-only so far; CoC/Where Wolf? would need the same small addition.
- **Reserved-card content sized via container query (cqw), NOT `--card-h`.** The reserved-card cost/points/color
  were sized off `--card-h` assuming a reserved card was ~0.58× a board card; it's actually ~0.8-1.0× (and the
  ratio drifts with the sidebar/`--card-h` clamps), so the text rendered ~half-size. Fix: `.player-reserved .card`
  is now `container-type:inline-size` and its content (`.card-points`/`.card-bonus`/`.cost-gem`/`.cost-num`/
  `.card-cost` gap/`.card-header` margin) uses **cqw** so each reserved card is a faithful MINI board card
  (content = same fraction of the card as on the board cards, ≈ board's `--card-h` multiple ÷ 0.72). **GOTCHA
  (do not regress): cqw on the card's OWN padding resolves against an ANCESTOR container/viewport, not itself —
  so the card's padding STAYS `--card-h`-based; only DESCENDANTS use cqw.** Verified within ±2.7% across
  resolutions by a headless measurement harness.
- **Slimmer actions box (the 3-4p layout-shift fix).** The Take/✕ buttons were too wide and, in 3-4p lobbies
  (the wider nobles row squeezes the actions `1fr` column), forced that grid track wider and shoved the
  board/sidebar around. (1) **Removed the ✕/cancel button entirely** from `renderActionButtons` (all states) —
  clicking a selected gem or card again already toggles it off (`handleGemClick` / the card `onClick`), so it was
  redundant. (2) Tightened the Take/Buy horizontal padding (`.actions-panel-btns .btn` `0.162→0.08 × --card-h`).
  (3) **`min-width:0` on `.actions-panel` + `.actions-panel-btns` (and `max-width:100%` on the button) is the
  structural guarantee** the box can never grow its own grid track — a grid item defaults to `min-width:auto`
  (=min-content), which is what let a wide button expand the `1fr` track; `min-width:0` makes the track purely
  space-derived. Verified: with `min-width:0` the grid width is STABLE regardless of button width (the old code
  overflowed its container by ~220px with a wide button). The `.action-bar-spacer ✕` (in the legacy
  `visibility:hidden` action-bar paths) is a height placeholder, not a real button — left alone.
- **Minimal actions-box hint (the follow-up height fix).** Even after the width fix, the hint (`getHint()` →
  `.action-hint`) was still bloating the box: the verbose per-action guidance (e.g. *"Take gems, or click a card
  then the gold coin to reserve"*, *"Reserve armed — …"*) wrapped to several lines in the squeezed 3-4p column,
  growing the actions row (row 1) and shrinking the card board (row 2). Per the user, **`getHint()` now returns
  ONLY `Waiting for {name}…` (opponent's turn) and `""` on YOUR turn** — the Take/Buy buttons, the card
  affordability highlight, and the discard/noble modals already convey everything else (the per-action hints were
  deliberately dropped). On your turn the empty hint collapses to 0 height, so the box is just Target + buttons.
  The desktop `.actions-panel .action-hint` is **`white-space:normal` + `overflow-wrap:anywhere`** so the short
  waiting text WRAPS to the next line for a long name (no ellipsis — show the full name) while `overflow-wrap:
  anywhere` breaks a long unbroken name so it still can't force the column wider (keeps the width guarantee); a
  2-3 line wrap of that short string stays within the nobles' height, so it doesn't regrow the actions row.


### Player box + nobles details (desktop; do not regress)
- **Indicator sizing uses `zoom`, not font/padding math.** The desktop player box scales
  its indicators with `zoom` (scales box + text + the inline gem dots together, WITH
  reflow — unlike `transform:scale`, which overlaps neighbors): gem pills (`.token-pill`)
  and card/bonus pills (`.bonus-pill`) `zoom:1.2`, the "N gems" total (`.gem-total`)
  `zoom:1.2`, reserved cards (`.player-reserved .card`) `zoom:1.1` + `width:89px` (the
  sidebar does NOT inherit `--card-w`, so reserved cards fall back to 88px — set width
  explicitly). Per-px width nudges ride on top via horizontal padding (e.g.
  `.bonus-pill{padding:3px 9.5px}`). `zoom` is supported in current Firefox (126+) and
  Chromium. **Remember the zoom factor when a request says "+1px"** — the on-screen delta
  is `px × zoom`.
- **0 gems must not shift the bonus pills.** The "N gems" total ALWAYS renders (even
  "0 gems"), and `.player-tokens` has a `min-height` reserving the empty token row — but
  with `align-items:flex-start` so that `min-height` does NOT stretch the pills taller
  (the row is `display:flex`; default `align-items:stretch` made the pills grow — a
  regression the user caught immediately).
- **Nobles are square + fixed-position.** Desktop `.noble` is `width:120px;aspect-ratio:1`
  (exactly square); requirement markers (`.noble-req-dot`) are rounded SQUARES
  (`border-radius:2px`), reading as cards not gems. **Claiming a noble never moves the
  others**: the row renders the FULL original set in a stable id-sorted order
  (`game.nobles` ∪ every player's claimed `nobles`, sorted by id), and a claimed noble
  shows as a **blank slot** (`.noble.noble-empty`, dashed placeholder) in its fixed
  position during play (dimmed + claimer's name only in the end-game review). The backend
  removes claimed nobles from `game["nobles"]` (so positions would otherwise compact/
  shift) — this position-preserving reconstruction is frontend-only.

### Action animations — flying gems + cards (`.fly-layer` / `flyers`)
A single `useEffect([game])` diff (mirrors the `prevBankRef`/`flashGems` pattern)
drives all move animations, so it covers EVERY player incl. the AI with no per-handler
hooks. It snapshots each player's **tokens + purchased ids** and the **board slot ids**;
on the next state it computes deltas and, **only when the move log advanced by exactly
one** (burst guard for load/reconnect), spawns absolutely-positioned flyers in a fixed
`.fly-layer` overlay:
- gem gained (delta>0) → fly bank→player, shrink (take / reserve-gold);
- gem spent (delta<0) → fly player→bank, grow (buy / discard);
- a player's `purchased` grew → fly a card-shaped flyer from the board slot it came
  from to the buyer's box, shrink.
Positions are measured at runtime via `getBoundingClientRect()` on `data-color`
(bank tokens), `data-pid` (player boxes), and `data-pos` (board card slots — the slot
persists after the buy because it's replenished). One `@keyframes fly` (translate +
scale via per-flyer `--dx/--dy/--s0/--s1` inline vars); flyers are removed by a
timeout. Keep these three `data-*` attributes when touching the bank/players/board.

---

## Design decisions (do not relitigate)

- **Noble path commitment rejected (but scarcity-gated)**: The AI must never *lock* onto a specific noble target. BUT per the user's strategy model, noble value is not flat — it scales **inversely with board efficiency**. When L2/L3 has efficient high-point cards to race, nobles are noise; when the board is poor in such cards, the only way to afford the inefficient L2/L3 cards is a wide pile of L1 bonuses, and breadth delivers nobles for free. So `noble_card` / `pos_noble` are modulated by `_board_scarcity` (high when few efficient targets exist) via the `noble_scarcity` / `pos_noble_scarcity` weights — this is contextual weighting, NOT target locking.

### Strategy model (informs AI feature design)
From a strong human player; drives the structural features (not just weights — self-play can only re-weight features that already exist, so these are encoded as new structure then tuned):
1. **Backward planning from efficient targets**: identify cost-effective high-point L2/L3 cards (points-per-gem: 5/8, 4/7, 3/6 are good deals), then value L1 bonuses by whether they advance *those specific targets* — not generic gem demand. (`_card_efficiency`, `bonus_target_pts`, `efficiency_weight`.)
2. **Scarcity → nobles** (see design note above): few efficient targets ⇒ go wide on L1 ⇒ nobles come along. (`_board_scarcity`, `noble_scarcity`, `pos_noble_scarcity`.)
3. **Contested-card value**: a card good for both you AND the opponent is worth more (acquisition + denial). (`_opp_reach`, `contested_weight` — boosts a point card's value by how close the opponent is to it.)
4. **Endgame denial**: reserve a card the opponent is one buy from (e.g. they have 4 white bonuses + 3 white tokens and a 7-white L3 is on the board). The rollout policy (`_fast_rollout_move`) now blocks too — gated by `block_urgency_gate` (default 1.1 = off; training lowers it) — so MCTS can finally *value* denial lines instead of never simulating them.
- **`_schedule_ai_turn` unconditional call is fine**: Its internal guards make it a no-op when conditions aren't met. Calling it after reconnect is intentional (unsticks games after socket drops).
- **No Co-Authored-By in commits**: User explicitly prohibited this.
- **`save_game` is synchronous** (SQLite ~1ms write), called outside ROOM_LOCK.
- **Thread pool for MCTS**: `loop.run_in_executor(None, ...)` — no dedicated executor needed; default thread pool is fine for single vs-AI game.
- **AI weights default to the original hand-tuned constants**: `DEFAULT_WEIGHTS` reproduces pre-training behaviour exactly. A `weights.json` is opt-in; do not commit one unless `train.py validate` shows it beats the defaults (>0.5) with real MCTS.
- **`train.py` is offline-only**: it imports game logic from `main` but must never start the server, open WebSockets, or write `users.db`. Self-play swaps the global `main.WEIGHTS` per mover — safe because training is single-threaded.
- **TD uses λ-traces, not TD(0)**: pure one-step bootstrapping diverged on this game's correlated states; don't "simplify" it back to TD(0).

---

## Known bugs / fixes applied this session

| Bug | Fix |
|-----|-----|
| TDZ `ReferenceError` in Firefox prod build | Moved derived game state (`game`, `me`, `myTurn`, etc.) before all `useEffect` hooks in Spender.jsx |
| AI blocking UI for 5s (human + AI moves batched) | Replaced sync `_post_turn` AI call with async `_schedule_ai_turn` task |
| "Game Not Started" when game was actually over | Split status check: `== "over"` → "game is over" before generic "not started" |
| Game stuck after socket drop during AI think | `_schedule_ai_turn` now called in both reconnect handlers |
| "Game Not Started" toast + waiting screen flash on reconnect | Race: WS1→WS2 reconnect, WS1 `finally` removed WS2's socket and deleted the room. Fixed with `r["sockets"].get(pid) is websocket` guard in `finally`. Also fixed `"joined"` handler to check `msg.room?.status` before setting screen (was always going to `"waiting"`). |
| Room-code (waiting) screen popped up over the end-game review | `created`/`joined`/`reconnected` sent any non-`"playing"` status to `"waiting"`; a finished game is `"over"`, so a reconnect after game end bounced the user off the review screen. Now an `inGame(status)` helper treats `"playing"` **and** `"over"` as the game screen; the winner/review UI lives there gated by the `reviewing` flag, so reconnects no longer kick out. |
| Reserve at 10 gems → 11 gems, no discard prompt, AI turn skipped, replay with 11 | Discard requirement was transient (one-shot `needs_discard` message field, **no** server guard); a later `room_update` reset the frontend modal and let the player move again. Fixed by making discard real game state like nobles: backend sets/clears `g["pending_discard_pid"]` on the three over-10 paths (take_gems/discard/reserve) and **rejects any non-`discard` move** while it's set (guard beside the `pending_noble_pid` one). Frontend `needsDiscard`/`needsNobleChoice` are now **derived** from `game.pending_discard_pid`/`game.pending_noble_pid` (not message fields), so they survive reconnects/saves and can't be cleared by a stray broadcast. |
| Review board missing claimed nobles | Noble row rendered only `game.nobles` (unclaimed), so nobles a player won vanished from the board. In review (`phase === "over"`) the row now also shows each player's claimed nobles, dimmed + labeled with the claimer (`★ name`), reconstructing the full original board. |
| Move log rows not clickable for buy/reserve | Backend only logged `{color, points}` — no `cost`/`id`, so frontend `mv.card?.id` was always null. Fixed: backend now logs full card dict on all 4 buy/reserve paths; frontend checks `mv.card?.cost`. |
| Move log border flash on new entry | `.log-entry:last-child{border-bottom:none}` rule meant adding a new entry at top changed the last-child, briefly revealing a border. Fixed: removed per-entry `border-bottom`; use sibling combinator `.log-entry+.log-entry{border-top:...}` so no element's border changes on prepend. |
| Hover on log row showed horizontal scrollbar | `margin:0 -4px` on hover exceeded container width. Fixed: removed negative margin; added `overflow-x:hidden` to `.move-log`. |
| Variant Z showed "AI (A)" in UI | Two-step failure: (1) `deploy-render.yml` didn't trigger on `az_model.npz` push, (2) accidental CoC import (`games.castles_of_crimson.main`) committed via stash/pop caused Render deploy to fail. Fixed: added `az_model.npz` to deploy-render.yml trigger paths; removed CoC import block (replaced with TODO comment). |

---

## Build + deploy steps (production)

**The build is CI-owned — NEVER build or commit the bundle by hand.**
As of **2026-07-05** the Pages source is **"GitHub Actions"** (`build_type=workflow`), NOT the old
`gh-pages` branch and NOT `main`/`docs`. The `.github/workflows/deploy-pages.yml` Action fires on
every push to `main` touching the frontend (`webapp/**`, `games/spender/**`,
`games/castles_of_crimson/**`, `games/wherewolf/**`, `books/**`, `shared/**`, or the workflow
itself): a **`build` job** builds the top-level `webapp/` (with
`VITE_WS_URL=wss://splendid-nelz.onrender.com/ws` baked in), runs the smoke gate, and uploads
`webapp/dist/` via `actions/upload-pages-artifact`; a **`deploy` job** publishes it via
`actions/deploy-pages` (the `github-pages` environment). It does **NOT commit anything to `main`** and
**NOT push to any branch**.

**Why this replaced the gh-pages double-hop (2026-07-05 — DO NOT regress to force-pushing gh-pages).**
The old flow force-pushed `dist/` to a `gh-pages` branch, which then triggered a **SEPARATE,
GitHub-managed "pages build and deployment" run** whose **Deploy step is outside our control and
repeatedly FLAKED** — the build succeeded and gh-pages held the new bundle, but the native Deploy step
failed, so the **live site silently served a STALE bundle** (the "I don't see my changes" symptom).
`rerun-failed-jobs` on that native run was **unreliable** (it re-failed twice in a row); the only
reliable recovery was a fresh `POST /repos/forry4/forry4.github.io/pages/builds`. The Actions-based
flow is a **single run we own**: build + deploy are both jobs in `deploy-pages.yml`, so **if the deploy
ever flakes, just re-run this workflow's `deploy` job** (Actions UI or
`POST /actions/runs/<id>/rerun-failed-jobs`) — it retries the same official deploy path. `concurrency:
group: pages, cancel-in-progress: false` queues a rapid second push instead of aborting a publish.

**Rollback to the old flow** (only if the Actions flow ever breaks): flip Settings → Pages → Source
back to **`gh-pages` / root** (`PUT /repos/.../pages -d '{"build_type":"legacy","source":{"branch":"gh-pages","path":"/"}}'`)
and `git revert` this workflow to the force-push-gh-pages version. The **`gh-pages` branch is left
intact** as that safety net (last legacy bundle). **`docs/` is also still vestigial** (older rollback net).

**Deploy verification (recommended after a frontend push):** poll the `deploy-pages.yml` run to
`completed success` (both `build` + `deploy` jobs), then confirm the live bundle hash changed:
`curl -s https://forry4.github.io/index.html | grep -o 'assets/index-[A-Za-z0-9_-]*\.js'`. With the
Actions flow there is **no second native run to check** — if `deploy-pages.yml` is green, the site is
published. (Token for the API, if needed: `printf "protocol=https\nhost=github.com\n\n" | git
credential fill | grep '^password=' | cut -d= -f2-`.)

**Frontend deploy = commit source only:**
```bash
# edit games/spender/Spender.jsx (do NOT npm run build, do NOT touch docs/ or gh-pages)
git sync-main                      # ff the main worktree to origin/main first (global alias)
git add games/spender/Spender.jsx
git commit -m "feat(ui): ..."
git push                           # deploy-pages.yml builds + publishes via Actions (~2-3 min)
```
The two deploy workflows: **deploy-pages.yml** (frontend → builds + publishes via the official Pages
Actions pipeline) and **deploy-render.yml** (backend → Render). Backend (`main.py` etc.) also deploys
on push to main. `npm run build` locally is only for *verifying a build compiles* — discard the
`dist/`, never copy it anywhere.

**`git sync-main` (global alias)** ff's the primary main worktree to `origin/main` from anywhere
(`git -C "<main-worktree>" fetch origin && merge --ff-only origin/main`). Local `main` carries no
unique commits, so it's always a clean ff — but it drifts because feature branches push straight to
`main` from sibling worktrees. When branching, branch off `origin/main` after a `fetch`, not stale
local `main`.

### Staging environment (Cloudflare — test frontend changes live before prod)
A live staging site mirrors the front end so UI changes (esp. mobile/desktop layout)
can be tested on a real URL before shipping to prod:
- **URL:** https://webprojectsstaging.forry4.workers.dev/ — a **Cloudflare Worker**
  (`name: webprojectsstaging`) that auto-rebuilds on every push to the **`staging`**
  git branch. Build config (Cloudflare dashboard): root `webapp`, build `npm run build`,
  output `dist`; env `VITE_BASE=/`, `VITE_WS_URL=wss://splendid-nelz.onrender.com/ws`,
  `NODE_VERSION=20`. It **reuses the prod backend** (no separate Render service / DB),
  so only FRONTEND changes are testable and any test games/accounts hit the real DB
  (use vs-AI games to stay private).
- **Enabling code (now on main):** `webapp/vite.config.js` reads `base` from
  `VITE_BASE` (default `/` — the GitHub Pages user site serves at the root); Vite was upgraded **5→6**
  (Cloudflare auto-config requires ≥6); `webapp/wrangler.jsonc`
  (`name: webprojectsstaging`, `assets: ./dist`, SPA) drives the Worker deploy and is
  ignored by GitHub Pages.
- **Workflow:** work in a `staging` worktree → `git push` → test at the workers.dev
  URL → to ship, integrate with main: `git rebase origin/main` (UI vs backend work
  usually touch disjoint files), `git push origin staging:main` (fast-forward), then
  `git push -f origin staging` to resync. CI then builds + publishes to `gh-pages` + redeploys prod.
- **⚠️ `staging` has DIVERGED — NEVER blind-push `staging:main` (do not regress).**
  As of 2026-06-21 `staging` is a long-lived branch that is **behind `main` on the
  backend** (it lacks main's wherewolf engine/role fixes, Spender move-log/card-catalog,
  S-variant perf, etc.) AND has historically **carried the Where Wolf? home card**. So
  `git push origin staging:main` would be a non-fast-forward whose force **wipes main's
  backend history** (and could re-introduce or revert game state unexpectedly). **To ship
  staging frontend selectively** (the method used for the CoC overhaul + active-games +
  Spender mobile actions-box + the Where Wolf? launch): branch off `origin/main`;
  wholesale-take any file where main is unchanged since the merge-base (e.g.
  `git checkout origin/staging -- games/castles_of_crimson/CastlesOfCrimson.jsx`, or just
  `games/wherewolf/WhereWolf.jsx` for the wherewolf launch); for files both sides changed
  (`Spender.jsx`) 3-way merge them (`git merge-file -p ours base theirs`, base =
  `git merge-base`) and re-add/strip only the intended blocks; `npm run smoke`; push the
  branch → `main`. Verify with `grep` on the shipped file + the built bundle size.
- The local↔Cloudflare bundle **hashes differ** (different build envs), so verify a
  deploy by the served CSS/markers, not the filename.
- **Fastest iteration loop = local vite dev pointed at the prod backend** (the
  Cloudflare deploy is ~30–45s/change; HMR is instant). From `webapp/`:
  `VITE_BASE=/ VITE_WS_URL=wss://splendid-nelz.onrender.com/ws npm run dev` — open the
  printed `localhost:<port>` (vite bumps the port if 5173 is taken, e.g. 5174), log in,
  and **resume your real game from the account-based games list** (so the long-move
  board is there to test layout). Edits hot-reload into that tab. Gotcha hit once: a
  stale 302-redirecting server on :5173 sent the user to prod — confirm the exact port
  vite printed.

### Frontend smoke test (`npm run smoke`) — catch blank-page AND layout-shift regressions
`webapp/test/smoke.mjs` (Playwright) builds the app, serves it with `vite preview`,
loads it in a headless browser, and FAILS if `#root` doesn't render, any uncaught
page error fires, **or the page shifts its layout on load past a budget** (Cumulative
Layout Shift). This catches two classes: (1) **the bundle compiles but throws at
runtime → a blank white page**; (2) **content/fonts/styles arriving after first paint →
the "snaps into place" reflow** (a `layout-shift` PerformanceObserver accumulates CLS;
budget `0.1` — current load ~0.008). The bug that motivated it: a CSS comment
in the `css` template literal contained backticks (`` `.game` ``); a backtick inside
a JS template literal terminates it, so the rest parsed as a stray tagged-template
(`str.game\`…\`` → "…is not a function" at load). **NEVER put a backtick inside the
`css` string** (the css const spans ~`Spender.jsx:69–515`; only its two delimiters
may be backticks).
- **Run `npm run smoke` (in `webapp/`) before pushing** — esp. to the `staging`
  branch, since Cloudflare does NOT run it. Locally it uses the system Edge channel
  (no browser download); in CI it uses bundled chromium.
- It **gates the prod deploy**: `deploy-pages.yml` runs `npx playwright install
  --with-deps chromium` + `npm run smoke` BEFORE the real build, so a blank-page
  build can't reach GitHub Pages. (It runs before the WS-URL build so its throwaway
  build doesn't become the deployed artifact.)

### No-layout-shift architecture (June 2026 — do not regress)
We kept hitting reload "snaps into place" reflows; the structural fixes (so it stops
being whack-a-mole):
- **Self-hosted fonts.** Cinzel + Crimson Pro are served from `webapp/public/fonts/`
  (latin-subset **variable** woff2 — one file per family covers all weights; 3 files
  incl. italic), `@font-face` in `shared/theme.js` baseCss (+ a copy in CoC, which
  renders bare without baseCss; the browser dedupes by src url). The Google-Fonts
  `<link>`/`@import` are GONE. The two main files are **preloaded** in `index.html`
  (`<link rel="preload" as="font" crossorigin>` — crossorigin required even same-origin).
- **Render gate.** The loading effect (`Spender.jsx`) calls **`document.fonts.load(...)`**
  for Cinzel 400/600/700 + Crimson 400 and AWAITS them (capped 1.5s) before routing to
  a real screen, so the first paint already uses the web fonts — no swap. `document.fonts.ready`
  ALONE is insufficient (the blank loading screen renders no text, so nothing triggers
  the load; `.load()` triggers + awaits it). On reload (cached) it resolves instantly.
- **`font-display:optional`** on every face: if a font isn't ready in its tiny window it
  uses the fallback for that load and NEVER swaps (no late reflow). Belt-and-suspenders:
  **metric-matched fallbacks** — `'Cinzel Fallback'`/`'Crimson Fallback'` = `local('Georgia')`
  with `size-adjust` from MEASURED width ratios (Cinzel 1.118× Georgia → 111.8%, Crimson
  0.879× → 87.9%), wired into every font stack (`'Cinzel','Cinzel Fallback',serif`), so an
  unloaded font occupies the same space.
- **Inline dark bg** in `index.html` (`html,body{background:#0f0e0c}`) avoids a white flash
  before the JS-injected CSS loads (the `--bg` token only exists in baseCss).
- **Reserve space for stateful elements** (fixed button/icon sizes, `scrollbar-gutter:stable`,
  `min-height` on swap-y rows) — and the **CLS smoke gate** (above) catches any new shift.
- Known longer-term option (not done): the CSS-in-JS `<style>{baseCss+css}</style>` injects
  styles at render; a static `<link>` stylesheet would make them render-blocking/earlier, but
  it conflicts with the self-contained single-`.jsx` game pattern, so it was deferred.

## Spender Puzzle mode (`games/spender/puzzle/`) — LIVE on prod (July 2026)

A **"Spender Puzzles"** feature: the player is dropped straight into a single position and must find
**the one move** N most favours. Reached from the home-menu **🧩 Spender Puzzles** button. Backend is
static (no AI at serve time); all the hard work is offline.

```
games/spender/puzzle/
  serve.py    # two read-only routes wired in the composition-root app.py (setup_puzzles):
              #   GET /puzzles (listing: id/title/kind/win_points/K/n_hero_moves/difficulty)
              #   GET /puzzles/{id} (the full puzzle: embedded per-step snapshots + moves)
  schema.py   # build_puzzle(start, sol, opponent, meta) -> a fully-scripted walkthrough with a
              #   game-dict SNAPSHOT embedded per step, so serving needs ZERO engine/AI compute
  author.py   # hand-crafted-puzzle authoring (build_state / verify / emit) — the chain/reserve set
  solver.py   # forced-win + uniqueness search (s_opponent/h3_opponent oracles; every_deviation_loses)
  generate.py # harvest H3/S self-play -> screen for unique forced wins (the puzzle_00N set)
  puzzles/    # the committed static bank (advantage_*.json = the shipped single-move puzzles)
```

### Two puzzle KINDS (top-level `kind` field; serve.py `_meta` exposes it)
- **`kind:"win"`** — scripted forced-win puzzles (the original `chain_*`/`reserve_*`/`strict_*`/
  `puzzle_00N`). Multi-move; solver-verified UNIQUE (any deviation provably loses). These EXIST
  because the "reach `win_points`" terminal pins the line down. **NOT surfaced in the live mode**
  (the frontend filters to `kind:"advantage"`); kept in the repo but orphaned.
- **`kind:"advantage"`** — the shipped SINGLE-MOVE "only-move" puzzles. One hero step; "solved" =
  play that move. `meta.move_evals` = every legal move's N eval (dict-move + name + eval) so the UI
  can show the eval of ANY move; `best_eval`/`second_eval`/`eval_seeds`/`gap_hi` too. serve's
  listing also exposes **`answer_type`** ("buy" | "reserve" | "take") per puzzle — the frontend's
  weighted draw needs it without fetching each file.

### Single-move "advantage" pipeline (offline; the current content)
- **`spender-core/src/bin/n_eval_server.rs`** (build `--features bridge`): the N (net_attn_3
  attention net) EVAL bridge. One JSON req/line `{state,seat,sims,seed}` -> `{best,value,visits,
  wins}`. Same determinized PUCT as `n_move_server` but returns the rich root readout (per-move Q).
  Serving/tooling only; NOT shipped to prod. **GOTCHA: it does NOT search DISCARD/NOBLE-phase
  roots** — it returns `value=0.0, visits=1` (see the eval bug below).
- **`scratchpad` tooling (not committed): `advantage.py`** (NEval bridge wrapper w/ seed-offset for
  independent samples + hang/crash-resilience; `_sub_terminals` sub-decision expansion;
  `hero_move_evals_avg`; `move_forces_subphase`), **`gen_single.py`** (self-play generator),
  **`wwsd_source.py`** (WWSD dump -> engine State loader), **`harvest_wwsd.py`** (real-game
  harvester), `reverify_bank.py`/`rebuild_bank.py` + audit/finalize scripts.
- **A puzzle = a position where ONE move's N eval beats every other legal move by a margin IN A
  RANGE: `0.25 <= (best − second) <= 0.5`** (`--gap`/`--gap-hi`), hero doing well (`--floor` 0.10).
  The **upper bound rejects blowouts** — a move that's massively better (forced win, gap 1.0+) is
  obvious, not a puzzle (user rule; 10 over-obvious originals were purged retroactively). The eval
  of a move = APPLY it + re-search the child (negamax), **averaged over K=8 independent
  determinization seeds** (`--K`); a move that leaves pending hero sub-decisions (discard/noble) is
  scored **max over resolutions of the K-seed mean** (max-of-means — per-seed max would leak hidden
  info). **Answers must not force a discard/noble sub-step** (`move_forces_subphase` guard in
  `critical_single` — "take then discard" is bad puzzle UX; user rule). `gen_single` does a cheap
  root-Q prefilter (recall) then the averaged verify (the gate); `--answer-types` filters kept
  answer types.
- **TWO position sources**: (1) N-vs-N self-play (`gen_single`), which already looks like real games
  (nobles, mixed board, loose tokens — no decoration needed); (2) **real spendee games from a WWSD
  IndexedDB download** (`harvest_wwsd.py`) — each ply logs a compact engine `dump` + N's search
  readout. VALIDATED: our N reproduces the logged values (0.224->0.222 etc.), so their positions load
  exactly. Real games yield far more genuine only-moves than self-play (esp. reserve answers), and
  more varied/human-relevant positions. `--skip-dumps` skips positions a prior file already covered.

### HARD-WON FINDINGS — DO NOT RELITIGATE
- **Multi-move "hold the advantage" chains DON'T EXIST in Splendor.** 0 chains of length >=2 across
  20 seat-games at every threshold. Positions branch too much; after the one sharp move + N's best
  reply, the next position almost always has several near-equal moves. Unlike chess, there is no
  *unique* eval-based continuation to force. (The forced-WIN puzzles chain only because the 15-pt
  terminal pins the line.) So single-move puzzles are the only viable eval-based kind.
- **You CANNOT select puzzles from the sample game's per-move numbers.** Trusting the self-play
  search's root-Q was **11% precise**. PUCT is greedy — it pours ~all its sims into the best move and
  barely grades the alternatives (1-5 visits each -> their Q is noise). "Few visits = bad" is FALSE
  (a 2-visit move measured 0.99 true value). So to prove "every OTHER move is >=0.25 worse" you MUST
  re-search each alternative — the roads the game-playing search deliberately prunes. This is why
  generation is inherently slow (per candidate: ~#moves x K searches).
- **A single search's VALUE is noise-dominated for open positions.** Same position, same 1000 sims,
  different RNG seed -> root value spread **0.42** (e.g. a take-gems move ranged -0.08..+0.34). The
  1000 sims are CORRELATED (shared tree + PUCT concentration), so the average isn't converged. The
  gap can be pure luck (one puzzle's "0.41 gap" was really ~0). **Take-gems answers are the noisy
  ones (leave the outcome to future draws); buy/reserve are stable (spread <=0.066).**
- **The fix = average K independent searches (fresh seed each).** The MEAN is the true expected value
  over reveals, so even take-gems answers get a well-defined eval. Baked into `gen_single`
  (`critical_single` averages) + the displayed `move_evals` are means. An audit of the shipped bank
  confirmed all solid under averaging; store the averaged means, not one sample.
- **A single root search's edge-Q OVERSTATES the gap — and it gets WORSE with more sims.** PUCT
  starves the runner-up (7813/8000 visits into the best move, 64 into 2nd), so the 2nd move's root-Q
  is a handful of shallow pessimistic sims. Measured on a real position: fair per-move re-search gap
  = **0.154**; the same two moves read off one root = 0.41 @2k sims, **0.54 @8k** (grows with sims —
  deeper best-line, more starved alternative). So a bot's 20k-sim one-shot readout ("this take is
  +0.27 better") is NOT evidence a position is an only-move — candidates surfaced that way MUST go
  through the per-move re-search verify. Visit count picks the best move fine; edge-Q cannot measure
  HOW MUCH better it is.
- **The n_eval_server returns value=0.0 for DISCARD/NOBLE-phase roots (the "take-3 shows 0.00"
  bug).** Any move that overfills past 10 tokens (take/reserve at 8+ tokens) left the child in
  DISCARD phase -> its eval silently became exactly 0.0. This (a) showed users "N eval 0.00" for
  wrong takes, and (b) **corrupted gap certification** — 186 stored move_evals across 18 puzzles were
  0.0, and re-verification with the fixed evaluator (expand hero sub-decisions to PLAY/OVER leaves,
  max-of-means) changed real verdicts (one puzzle's "alternative" truly evals ABOVE its stored
  answer). Fixed in `advantage._sub_terminals`/`_leaf_eval`; the whole bank was re-verified. If a
  new eval path ever queries the server, check the phase first.
- **N's REAL PLAY is fine — this was a puzzle-tooling artifact.** Determinization (ISMCTS) IS the
  correct averaging over hidden info; N runs **~20k sims** in the browser (far better converged than
  the 1k puzzle-gen sims) and **picks by VISIT COUNT, not the noisy value**, so its move choice is
  robust. Only the puzzle's displayed eval needed the extra care.

### Frontend (`Spender.jsx`) — one-at-a-time, no menu
- Home button -> `enterPuzzles()` loads the list and immediately `startPuzzle(random)`. There is NO
  picker screen (it's a brief loading state). `pickPuzzleId` filters to `kind:"advantage"`, excludes
  a localStorage `spender_puzzle_seen` set (reshuffles when exhausted), and **draws the answer TYPE
  by a target mix — `PUZ_TYPE_WEIGHTS` = 60% buy / 15% take / 25% reserve** (user-set) — then a
  random unseen puzzle of that type (falls through the other types by weight if a bucket is empty,
  so small pools still serve). Uses the listing's `answer_type`.
- Always-available **Next ▸** (skip/advance), **Try Again** (restart on a wrong move via the fail
  overlay), **Return** (dismiss the result overlay to re-examine the board), **Exit** -> home.
- Shows N's eval: on solve "The only move: X · N eval +0.29"; on a WRONG move ONLY the move you
  played ("You played X · N eval -0.09 — not the move..."), **never revealing the answer** (the
  Answer button is the explicit reveal). `fmtEval`/`puzMoveEval(move)` read `meta.move_evals` (mean).
- **Hint = a POPUP showing ONLY the answer's category** — "Buy" / "Reserve" / "Take gems"
  (`puzHintOpen` + a `modal-backdrop` modal, `.puzzle-hint-word`). The old two-level escalating hint
  (category then exact move) is GONE (user request); the exact move lives only behind Answer.
- Backend `kind` + `move_evals` come from serve; the single-move flow reuses the existing
  submitPuzzleMove/showPuzzleAt path (1 hero step -> solved).

### Deploy — LIVE on prod (July 2026)
- Backend bank + serve are on `main` (Render watches `games/spender/puzzle/**/*.py` +
  `puzzles/*.json`; `setup_puzzles` wired in `app.py`). Frontend on `main` too (Pages CI smoke-gates
  + publishes). Staging mirrors it. **Ship pattern:** puzzle JSONs/`serve.py` -> main; `Spender.jsx`
  -> main (Pages) and force-resync `staging`. Grow the bank via `gen_single`/`harvest_wwsd` +
  `rebuild_bank` (renumbers contiguously; the frontend shows no per-puzzle number, so renumbering is
  UX-safe).
- **Takes use `[0.25, 0.60]` — same 0.25 lower bound, a HIGHER upper bound than buys/reserves (0.50).**
  Rationale (data-driven, user-approved): a big-gap BUY is an obvious forced win, but a big-gap TAKE is
  subtler — the wrong gem-combos look identical to the right one, so it's still a find-the-gems puzzle
  (measured: most takes with gap ≥0.25 have another *take* as the runner-up; the high end is dominated
  by `take2same` — counterintuitive since players default to take-3-different). So takes get more
  headroom than 0.50 — but the VERY-extreme ones (>0.60, e.g. gap 1.7 near-win endgames) read as forced,
  so they're still capped (`GAP_HI_TAKE=0.60` in `rebuild_bank`; the tuning history went no-cap → 0.60).
  The old `GAP_LO_TAKE=0.20` softer-lower-bound experiment is REMOVED — takes needed the upper bound
  raised, not the lower one dropped. Genuine only-move takes stay rare (7 in [0.25,0.60] across all
  sources), which is why the headroom over 0.50 matters.
- **Candidate LEDGER (`games/spender/puzzle/candidates/`) — persist the expensive verification.** Every
  position the miners VERIFY (pass or fail) is appended to `candidate_ledger.jsonl.gz` (1 line =
  compact engine state + every legal move's K=8-averaged N eval). That table costs ~#moves×8 searches
  to produce, so persisting it makes a future threshold change a **pure re-filter with ZERO recompute**:
  `python -m games.spender.puzzle.candidates.rebuild_from_ledger --stats` (report gap bands) or
  `--out DIR --types take --gap-take 0.15 --gap-take-hi 0.6` (re-emit at any bar). Miners take
  `--ledger PATH`; merge new runs' ledgers in (dedupe by `(dump, hero)`). Committed (gzipped, ~550 KB);
  not served, not in the build.
- Current bank: **53** advantage puzzles (23 buy / 23 reserve / 7 take), gaps 0.25–0.49, sourced from
  N self-play + WWSD real-game harvests (117 + 161 files) + the ledger's `[0.25,0.60]` take finds. The
  60/15/25 weighted draw (`PUZ_TYPE_WEIGHTS`) delivers the target mix regardless of the bank's skew.
