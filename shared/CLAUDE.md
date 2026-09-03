# Shared frontend kits (`shared/`) — notes

Cross-game frontend kits. **Dependency direction is one-way: `games/* → shared/`, never back.**

- **`theme.js` — `baseCss`** is the single source of truth for the design system (font `@import`/
  `@font-face` first, `:root` tokens, `.btn`/`.input`). Spender + Books + Duel + WW import it; CoC renders
  it too (CoC carries a copy since it mounts bare).
  **`font-display` IS `swap` AND MUST NOT GO BACK TO `optional`.** `optional` gives a face a
  ~100ms block period and then, if it has not arrived, uses the fallback **for the lifetime of
  the page** — the font still lands in the cache and `document.fonts.check()` starts answering
  true, but nothing on screen changes. So Spender.jsx's `waitFonts` gate would wait for Cinzel,
  see it resolve, and then the whole site painted in Georgia; only the SECOND visit looked
  right. Caught in the shot harness, where every browser context is a cold cache: the wordmark
  came out in lowercase Georgia with `cinzel:true` in the same probe. `swap` is safe here
  precisely because of the `size-adjust` metric-matched fallbacks — the worst case is a repaint
  at the same widths, not a reflow.
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
  **`LobbyCreateRow` has ONE optional `extra` node**, rendered after Rules, for a control a
  single game keeps there — today Dissonance's paper scorecard. A node rather than another
  `onX`/`xLabel` pair, so the kit never learns what any one game puts in it; style its button
  `.lby-extra`, which the sheet gives the Rules look. **Deliberately NOT `.lby-rules`**: the
  render gate counts Rules buttons by that class, so a second button wearing it reads there as a
  duplicate. `RulesModal` also takes an `icon` (default 📖) — the panel is reused for things that
  are not a rulebook.
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
  **THE THREE SHELL SCREENS ARE ONE DESIGN, HELD TOGETHER BY PAIRED SELECTORS**
  (`.home,.auth-screen,.loading-screen` in `games/spender/Spender.css` — the loading
  screen still lives in `Spender.jsx`). The ground (fixed warm top light + vignette +
  a tiled feTurbulence grain), the foiled wordmark and the `HERO_RULE` ornament are
  written ONCE and listed on all three, and `HERO_RULE`/`SITE_FOOT` are exported from
  `HomeScreen.jsx` and passed into `AuthScreen`. Do not copy a declaration to a second
  screen — a user sees two of these ten seconds apart, and a copied rule always drifts.
  **The wordmark lockup is GATED, not just documented**: `screens.mjs` renders all three
  (the loading screen by stalling `**/games**` past the shell's 250ms fast path) and
  fails if the type size, tracking, ornament width or the gap under the title differ.
  It was written because they DID: clamp(...,3.1rem)/(...,3.4rem)/(...,4rem) meant the
  title grew 50→54→67px at 1920 while a visitor watched, and `.home-rule` at `74%` drew
  at 253/241/265px because the three columns are padded 32/20/16. The ornament is
  viewport-relative now for exactly that reason. Note that the h1's own BOX width still
  differs (it is its container's) and is deliberately not compared. **It runs at TWO
  viewports, and the second one is the whole point**: at 1440x900 it passed while the
  wordmark was 48px on the menu and 64px on the two screens in front of it at 1280x800,
  because the short-viewport tier (height <= 880) compressed only `.home-logo` and 900
  sits just above it. A gate that tests one viewport tests one branch of a ramp.
  **The emblem plate is gated too** — that it is visibly tinted at all, and that it holds
  its accent's HUE. It is derived by mixing the accent into the card ground, and mixing
  `in srgb` let the warm ground win: Where Wolf's plate came out chromatically neutral
  and read as disabled beside six tinted siblings, and Dontminion's cyan rendered green.
  It mixes `in oklab` at 36% now, and 36 is the measured floor — 30% still drifted Duel
  and Dissonance past 22 degrees.
  **Any colour probe in that gate must go through a 1x1 canvas.** `getComputedStyle`
  returns whatever notation the DECLARATION used, so a `color-mix(in oklab, ...)` comes
  back as `oklab(0.36 0.002 0.04)` — and a regex that assumes `rgb()` reads those three
  numbers as R,G,B and reports a near-black grey. That is how the plate check first
  "failed" on plates that were perfectly correct. `canvas.fillStyle` parses any CSS
  colour and hands back sRGB bytes.
  **The footer is `.shell-foot`, ONE class on all three screens, and it must stay one.**
  It was `.home-foot`/`.auth-foot`/`.loading-foot` — five rules across four different
  selector lists — and they drifted exactly as that arrangement guarantees: the loading
  one missed the `<=430px` step and set 24% larger than its neighbours on a phone, the
  auth one missed the `>=1500` step and set 11% smaller at 1920, and home let it flow at
  the end of a centred column while the other two pinned it, so at 2560 the same
  sentence sat 207px off the bottom against their 35. All three screens use the same
  `main` + `shell-foot` shell now.
  **A banner rule must be keyed on the LAYOUT the card landed in, not on its index.**
  `:last-child:nth-child(3n+1)` also matches at ONE column, where every card is full
  width and there is nothing to distinguish the last one — so the banner's half-lit
  chevron made exactly one of seven identical phone rows look selected, on the tier that
  has no hover to explain it. The `@media(max-width:559px)` counter-block has to undo
  every banner property, and it has now been missed twice (the pill's 2px title-line
  offset, then the chevron).
  **`.auth-panel`'s `min-height` is a MEASURED number and rots on any copy change.** It
  is the tallest tab's natural height, so the three tabs come out one height and the
  centred card cannot move the tab strip under the cursor. Adding one helper line moved
  it 272 -> 344. `screens.mjs` gates the card height AND the CTA's offset across the
  three tabs at two viewports, and caught that on the first run after the edit. Note the
  `>=1500` floor is LOWER than the base one (310 vs 344) and that is not a mistake: the
  card is 480px wide there against 420, so the helper lines wrap less.
  Two layout rules there are load-bearing rather than stylistic:
  - **The card is a list ROW at 1–2 columns and a POSTER at 3.** At two columns the card
    is 440–550px wide and ~190 tall (nearly 3:1), and the poster stacks everything down
    the left, so 40% of every card was empty. One DOM serves both via
    `grid-template-areas` over four flat children (emblem / text / players / go).
  - **A card that would be alone on its row SPANS the row** (`:last-child:nth-child(3n+1)`
    at three columns, `2n+1` at two, and the same for `.home-extra`). It is keyed on the
    COUNT, not on "seven games": an eighth game turns it off by itself. Centring a
    partial row instead only lands on the grid for some column/remainder parities, so it
    was on-grid at the laptop width and straddling a gutter at the tablet width.
    **The banner's composition is ONE rule shared by both tiers**; only the
    `flex-basis:100%` lives per tier. It first kept the list-row stack at two columns
    (everything in the left 40% of a 1400px card) and sent the pill to the far container
    edge at three (1000px from the description it annotates) — two fallbacks rather than
    a design. Note the `@media(max-width:559px)` counter-block: at one column EVERY card
    is `:last-child`-eligible in the sense that matters, so without it the whole list
    turned into banners.
  - **`@media(min-width:1000px) and (max-height:880px)` compresses the ramp**, and it is
    keyed on HEIGHT because that is what runs out. 1280x800 is the one common desktop
    size where the page overflowed, and the fold landed within ~20px of the "Also here"
    rule — a section divider and three card tops as the last thing on screen, which is
    the worst possible cut. A 1280x1100 window keeps the full ramp. It is LAST in the
    section so it out-orders what it overrides; a media query adds no specificity.
- **`.home` NEEDS `width:100%`, and this is not tidiness.** It is a flex ITEM (`.app` is a
  column flex container) and it carries `margin:0 auto`. **Auto inline margins on a flex
  item switch off the default `stretch`**, so with `max-width:900px` alone the box sized to
  fit-content — about 516px — and the max-width never applied at any viewport. The site
  rendered as a narrow ribbon down the middle of every desktop, with the game titles
  wrapping in 240px columns, for as long as that rule existed. `.offline-hub` already
  carried `width:100%` and is why IT looked right. **Every DOM-level check passed the whole
  time**, which is why `screens.mjs`'s `homeScreen` block now asserts a WIDTH.
- **`--text-soft` (`theme.base-css.css`) is the body-copy dim; `--text-dim` is for labels and
  `--text-muted` is DECORATION ONLY.** Measured on `--surface`: soft 6.1:1, dim 4.40:1 (fails
  AA for normal-size text), muted 2.5:1. A sentence in `--text-dim` on a card is below AA.
- **The home accents are BOUND, not chosen** (`GAMES` in `HomeScreen.jsx`): each is its card
  title's ink, so ≥4.5:1 on `--surface`; ≥23° apart in hue, or the colour stops doing the
  identifying job it exists for; and inside a 0.364–0.404 luminance band, or the seven
  titles read as different weights. `screens.mjs` measures all three off the live page —
  it caught Spender and Rag Tag landing 21° apart, which looked fine by eye.
- **`update-nudge.js`** — the stale-tab refresh prompt. It compares frontend-to-frontend via
  `version.json` / `__BUILD_ID__`, **never** against the backend's commit (frontend-only pushes leave the
  two SHAs legitimately different — a cross-comparison would cry wolf on every deploy).

---

## `CmSeg` CLIPS RATHER THAN SCROLLS, so a long picker needs `wrap` (2026-08-18)

The segmented control is `overflow: hidden` with `white-space: nowrap` buttons.
That is right for the 2–3 option pickers every create modal uses, and it fails
TOTALLY the moment the options outgrow one phone row: an option past the fold is
not off-screen, it is **unreachable** — nothing to scroll, nothing to swipe, no
affordance that anything is missing. The only symptom is a game that appears not
to exist.

**Measured when Dissonance became the offline hub's FOURTH game**: 485px of
buttons in a 330px box at a 390px viewport, the last option ending **154px past
the right edge**. Every width below ~545px was affected.

* **`<CmSeg wrap>` is the opt-in**, and it becomes separate CHIPS rather than a
  segmented bar: the shared 1px dividers (`border-left` between siblings) cannot
  survive wrapping — the first chip of each later row would wear one against the
  container edge, and nothing would divide the rows at all. Chips read as a group
  without dividers, so the container drops its border and each button takes one.
* **The basis is measured, not picked.** `flex: 1 1 10.5rem` — the hub's panel
  caps at 560px, so the row's widest client box is ~512px, and any smaller basis
  packs THREE chips with the fourth stranded alone on row 2 at every desktop
  width. 10.5rem is the smallest that cannot fit three there, giving 2×2 on a
  desktop, 2×2 from ~430px and one per row on a small phone.
* **A BASIS rather than a percentage**, so a fifth option adds a row instead of
  silently re-clipping.
* **Gated by rectangles, not by the DOM** (`screens.mjs`, `offlineDissonance` at
  a 390px viewport): every button must sit inside its container's box and the
  container must not overflow. A DOM-only check passed the entire time the bug
  was live. Verified non-vacuous by dropping `wrap` — it fails and NAMES the
  options that fall outside.

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
