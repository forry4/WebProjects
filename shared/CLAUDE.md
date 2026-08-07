# Shared frontend kits (`shared/`) — notes

Cross-game frontend kits. **Dependency direction is one-way: `games/* → shared/`, never back.**

- **`theme.js` — `baseCss`** is the single source of truth for the design system (font `@import`/
  `@font-face` first, `:root` tokens, `.btn`/`.input`). Spender + Books + Duel + WW import it; CoC renders
  it too (CoC carries a copy since it mounts bare).
- **`lobby.jsx`** — shared lobby chrome (`LobbyHeader`/`LobbySectionHd`/`LobbyEmpty`/`LobbyLoading`/
  `TurnBadge`, cache helpers) + `GameMenu` (the in-game ☰ dropdown: Return / View rules / Abandon; falsy
  items filtered; Esc/click-outside close) + `CreateModal`/`LobbyCreateRow` (the unified "New Game" modal
  + create/join-by-code/refresh/**rules** row).
  **THE HOW-TO-PLAY MODAL IS SHARED TOO** (`RulesModal` + `RulesSection`/`RulesFacts`/`RulesDefs`/
  `RulesTip` + `rulesModalCss`, appended AFTER `lobbyCreateRowCss`); each game keeps only its WORDS,
  in a `games/<game>/rules.jsx` that rides its own lazy chunk. The panel is capped to the viewport
  and **`.rl-body` is the only scroller** — `min-height:0` on it is load-bearing (a flex item won't
  shrink below its content, so without it the panel grows past `max-height`, nothing scrolls and
  "Got it" sits below the fold, which is what two of the five per-game copies did). Every lobby
  passes `onRules`; the button is opt-in only so the component stays usable without one, and
  `screens.mjs` drives all six lobbies precisely because a game that forgets it still renders a
  perfectly fine lobby with no way in.
  **On phones (≤600px) `.lby-create-row` SCROLLS SIDEWAYS instead of wrapping** — five controls stop
  fitting at ~430px, and a wrap pushed the lists a whole row down. It uses `justify-content:safe
  center`: plain `center` pushes the overflow off the LEFT edge, where no scroll can reach it. Token-driven via a per-game `--lby-accent` with **hard fallbacks so
  it renders in CoC's bare mount** — append its CSS AFTER the `.coc *` reset.
  **THE WHOLE LOBBY LAYOUT IS HERE as of 2026-08-05** — `.lby-cols` (the column grid + the single
  responsive ladder: 3 columns ≥1041px, 2 columns 761–1040 with History spanning below, 1 column +
  tabs ≤760), `.lby-list` (the card list, and the only thing the desktop internal scroll can hang
  off — cap via `--lby-list-max`), `.lby-card-hist` (a history title WRAPS instead of truncating),
  and `LobbyTabs` (the phone segmented bar; `key` must match the column's `lby-col-<key>` class,
  because show/hide is pure CSS off `tab-<key>` on the grid, so a hidden column stays mounted and
  keeps its scroll position and History paging). Spender was converted onto all of it in the same
  pass — it had been the ORIGINAL this kit was extracted from and the only game never moved onto it.
  **A game's own sheet must not set `display`/`grid-template-columns`/`gap` on its lobby-grid class**:
  four of the five are concatenated AFTER this one, so a base rule out-orders these MEDIA rules and
  pins the lobby to three columns on a phone (CoC is the exception — its sheet comes first).
  Where Wolf? keeps its own 2-column grid (no History column) but uses `.lby-list`.
  Also **`useProgressiveList` + `HISTORY_PAGE`/`HISTORY_MAX`** — the lobby History list's 10-at-a-time
  reveal, wired identically into all four games. **`HISTORY_MAX` must equal `core.rooms.HISTORY_LIMIT`**
  (the SQL row cap); `core/tests/test_history_limit.py` reads this file as TEXT to hold the two
  together, since `core/` may not import a feature. It pages off a SENTINEL + IntersectionObserver
  rather than a scroll handler, because the four lobbies scroll different elements — see the root
  `CLAUDE.md`.
  **And `useLastDifficulty` — the create modal's AI-difficulty row defaults to the tier the player
  LAST PLAYED**, per game and per identity (localStorage `lastdiff.<ns>.<myId>`, same discipline as
  the cache above). It returns `[value, setValue, remember]` and a game opts in by holding its
  difficulty state in it and calling `remember` **where the vs-AI game is created** — not from the
  picker's `onChange`, or browsing the tiers and backing out would rewrite the default. The stored
  id is validated against the tiers the picker currently OFFERS, because a retired one (Spender's
  variant codes, Dontminion's plain Big Money) would otherwise restore as a selection the server
  silently coerces to a different bot than the label names. **A game that skips this compiles and
  renders a perfectly normal picker; it just forgets** — so
  `shared/tests/test_ai_difficulty_memory.py` derives the roster from the tree (any game screen
  whose create message carries `ai_difficulty`/`ai_variant`) and fails the next game that lands
  without it. `screens.mjs` covers the behaviour end-to-end on Duel.
- **`splendor.jsx`** — Spender + Duel SHARE gems, jewel cards, and the move log
  (`GemToken`/`CardView`/`TokenPill`/`BonusPill`/`LogEntry` + CSS), lifted verbatim from Spender.jsx.
  **If a second game needs a Spender visual, EXTRACT it here — don't re-approximate it** (Duel drifted
  before this existed). Gems are matte gradient via a `--gc` custom property + drop shadow, **no ring**
  (a same-hue ring paints a bright lower-edge arc). `CardView` is game-rule-free (Duel's extras are
  optional props). Verify a splice against the pristine pre-refactor commit `dc1b005`, not a `.bak`.
- **`AuthScreen.jsx` / `HomeScreen.jsx`** — site-SHELL screens, here for the DEPENDENCY DIRECTION, not
  for semantics. See `games/spender/CLAUDE.md` → Frontend for why, and what finishing the split needs.
- **`update-nudge.js`** — the stale-tab refresh prompt. It compares frontend-to-frontend via
  `version.json` / `__BUILD_ID__`, **never** against the backend's commit (frontend-only pushes leave the
  two SHAs legitimately different — a cross-comparison would cry wolf on every deploy).

---

## URL routing (`router.js` — LIVE on prod)

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

## Verification harness for shared UI (reusable)

esbuild-bundle a scratch React harness importing the real component + shared CSS, with **react aliased to
`webapp/node_modules`** (`--alias:react=<webapp>/node_modules/react`), then Playwright-screenshot
(`chromium.launch()`, fall back to `channel:"msedge"`). `npm run smoke` only renders the Spender LOBBY, so
game-screen changes need this isolation render or a live staging check.
