# Castles of Crimson (Castles of Burgundy port) — package notes

2–4 player faithful port (human-vs-human seats 2–4; vs-bot games stay 2p). Mounted at `/coc`. LIVE on
prod. **Now a 4-animal CoB port** (chicken added; monastery 6 = spend 1 silver → 2 workers; boards 2/4 =
2019 layouts). See the root `CLAUDE.md` for the room-server invariants and deploy.

---

## Engine contract (`engine.py` — single source of truth for server, bot, tests, AI)

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
  `tiles.black_fill`; `BLACK_FILL_2P`=4 is legacy-2p-only); starting castles never score; monastery 5
  *chooses* the adjacent depot.
- **House variant — fixed depot layout** (`tiles.DEPOT_PLAN`): each numbered depot refills each phase with
  two hex tiles of fixed TYPES (the specific building/monastery still varies by seed). Locked by tests.
- **Shadow VP ledger** (`region_vp`/`color_vp`/`livestock_vp`) is telemetry OUTSIDE the canonical
  projection — for AI aux training only; don't fold it into `proj`/parity.

---

## AI tiers — lobby Easy / Hard / Expert

| Tier | What it is | Where it runs | Lever |
|---|---|---|---|
| **Easy** | server determinized-MCTS bot at its strong config (`ai.play_turn_plan`) | server thread pool | sims/time budget |
| **Hard** | the first netval champion net (`coc_pv_model_hard.bin`) | **client WASM** (`coc-core`, netval leaf) | which net bin |
| **Expert** | the r2 champion **fine-tuned on the BGA expert corpus** (`coc_pv_model.bin`) | **client WASM** (netval leaf, ~20k sims) | which net bin |

- **netval leaf** = net policy prior + a short priority rollout + the net VALUE head at truncation
  (`NETVAL_ROLLOUT_STEPS=30`, `NETVAL_C_PUCT=1.0`). CoC is a delayed-payoff game, so a 0-step static leaf
  undervalues in-flight turns — the short rollout is why netval works (see research log). This is the
  OPPOSITE of Spender/Duel, where a static leaf wins; the repo has opposite precedents on purpose.
- **Serving mirrors Spender:** per-decision `ai_search` (compact state, undrawn pools sorted) → client
  searches → `ai_move`; watchdog `CLIENT_AI_TIMEOUT=8s` → falls back to the server hard bot.
- **Model upgrade = no wasm rebuild:** `python rust-cores/coc-core/tools/pv_json_to_bin.py <winner.json>
  webapp/public/wasm/coc_pv_model.bin` + push. The net blob is fetched (browser-cached), not embedded.
- Campaign status, ceiling verdicts, and the BGA-mining line: `docs/ai-research-log.md`. Every
  "exhausted" verdict there is CONDITIONAL on the current net + its frozen encoder — re-run the probes
  if the net materially changes.

---

## Frontend (`CastlesOfCrimson.jsx`) — durable facts

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
- **Mobile media-query ordering**: mobile `@media` blocks sit BEFORE the base rules, so every mobile
  override must be higher-specificity (`.coc `-prefixed) or a later base rule wins.

---

## Serving & reliability (do not regress)

- `main.py` mounts `coc_app` at its tail behind try/except; imports auth/DB directly from `core`.
- **Auto-reconnect is load-bearing** — a vs-bot turn is re-driven only when the client reconnects, so a
  Render cold-start / iOS backgrounding that drops the socket froze the bot's turn until manual refresh.
  `useSocket` has a backoff reconnect loop (reconnects with the **`reconnect` action, not `join`**) +
  a `visibilitychange` nudge + a `socketReady()` guard (don't abort a still-CONNECTING cold-start socket).
- **Building-placement highlight** reproduces `_building_town_ok` client-side (one building type per
  same-color region unless you own monastery effect 1) so the legal-glow matches what the click accepts.
- **The WASM worker pool must not take every core** — `hc<=4 ? hc-1 : min(hc-2, 8)`. CoC shipped without
  this for months and pegged every core on a 4-core machine.

---

## Tests

`tests/` (~319: board invariants, placement, scoring, lifecycle, one-per-monastery, endgame) +
`test_client_ai.py` + `test_ws_auth.py`. **Python↔Rust differential parity** — regen fixtures via
`gen_engine_fixtures.py`, then `cargo test --release --features bridge` in `rust-cores/coc-core`.
