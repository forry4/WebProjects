# Shared frontend kits (`shared/`) — notes

Cross-game frontend kits. **Dependency direction is one-way: `games/* → shared/`, never back.**

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
