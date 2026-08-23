# Rag Tag — a seventh game

## Context

Add **Rag Tag**, a faithful implementation of *Tag Team* (Le Scorpion Masqué, 2025 —
2 players, 12 fighters, ~15 min), as the site's seventh game: **the full roster in one
slice**, plus a bot that picks at random, so it can be played and playtested before the bot
gets any real strength.

The rules are already nailed down (below). The gap was always the per-fighter data — card
lists, health-track layouts, special tracks. Your console dump settles how to close it:
**BGA ships each fighter's full definition to the client** (`fighter: {…}` on every
`fighterDrafted` notif). That object, plus the game's static data, is everything we need,
and it arrives as structured JSON rather than something to be read off cardboard.

**I cannot reach BGA from this sandbox.** Verified: every `boardgamearena.com` and
`boardgamearena.net` host fails the egress proxy's CONNECT (000/403), as do BGG, the
publisher and the rulebook PDF host. Web search reaches BGA's Gamehelp text indirectly and
that is how the rules below were established, but it cannot open a table, a replay or a
script bundle. **The extraction runs in your browser** (Stage 0); everything after that is
mine.

One note on what we store: keep `fighters.py` to *mechanics* — numbers, op lists, track
layouts — and let the UI render our own icon vocabulary. Rules aren't copyrightable but the
publisher's card text and art are, and a mechanical table is the better engineering anyway.

---

## Handoff to the local session

Rather than pasting this plan into a new chat, it ships with the code: on approval I commit
it as `games/rag_tag/PLAN.md` and push `claude/rag-tag-team-foundation-zmfmrr`. The VS Code
session then does `git fetch && git checkout claude/rag-tag-team-foundation-zmfmrr` and has
the plan in the repo, next to the tree it describes, with no transcription drift.

**What the local session can do that this one can't** — and what it still can't:

- **Public URLs: yes.** The BGA client bundle (`x.boardgamearena.net/.../games/tagteam/.../tagteam.js`)
  and the rulebook PDF (`gamers-hq.de/media/pdf/81/2d/2c/TT_Rules_01_EN_06may2025.pdf`) need
  no login. **Try these first** — if the bundle carries the static fighter/card tables, the
  whole console exercise below is unnecessary, and the PDF settles the resolution order.
- **Logged-in BGA pages: still no.** `gameui.gamedatas` only exists inside an authenticated
  browser session, and WebFetch fails on authenticated URLs from any machine. That part is
  browser-console work (or Playwright driving a logged-in profile) regardless of which
  session is asking.

Suggested split: run Stage 0 locally, commit the dumps to `games/rag_tag/data/`, push. After
that the data is in the repo and **either** session can build Stages 1–5 — this one included.

---

## Stage 0 — extract the roster from BGA (in a browser)

Try the public bundle first (above). If it doesn't carry the tables, open any Tag Team table
or replay on BGA and run these in the devtools console. Three sources, most valuable first;
**A is probably sufficient on its own.**

### A. The live game data

```js
(() => {
  const d = JSON.stringify(gameui.gamedatas, null, 1);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([d], {type: 'application/json'}));
  a.download = 'tagteam_gamedatas.json';
  a.click();
})()
```

`gamedatas` is the full server-sent state. If the fighter objects in it carry their decks
and health tracks, this alone is the whole roster.

### B. The client bundle (the static tables)

```js
Array.from(document.scripts).map(s => s.src).filter(s => /tagteam/i.test(s))
```

Open that URL and save the file. BGA game bundles usually carry the card/fighter constants
and the icon vocabulary inline — which is also where the *names* of each effect live, and
those names become our op vocabulary.

### C. A replay's notification stream — the verification corpus

```js
(() => {
  const log = [];
  const orig = gameui.notifqueue.setSynchronous.bind(gameui.notifqueue);
  ['fighterDrafted','draftCompleted','gameLog'].forEach(() => {});
  const push = gameui.notifqueue.onPlaceLogOnChannel;
  window.__rt = log;
  const d = gameui.dojo || dojo;
  d.subscribe('*', null, (n) => log.push(n));   // fall back to per-channel subscribes if '*' is unsupported
  console.log('capturing — play the replay to the end, then run __rtdump()');
  window.__rtdump = () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(log, null, 1)], {type: 'application/json'}));
    a.download = 'tagteam_replay.json'; a.click();
  };
})()
```

This is the high-value one and the reason to grab more than one game: **a captured replay
is a parity fixture.** Every turn's revealed cards and every resulting HP / power / track
delta, produced by the real implementation. Two or three replays covering different
fighters give us a gate that turns "faithful" from an aspiration into a test (see
*Verification*).

Drop whatever you get into `games/rag_tag/data/` and I'll write the importer.

**Known roster so far (10 of 12), for sanity-checking the dump:** Joan (= "Jeanne" in BGA's
FAQ — the Divine Voice dial), Ching Shih, Bödvar, Wong Fei-Hung, Milady, Shango, Mephisto,
Maman Brijit, The Wild Bunch, Mordred. *Mordred may be from the* Arthur's Legacy *expansion
rather than the base box — the dump will say.*

---

## Rules established (verified against BGA's Gamehelp)

**Round = FIGHT! step + BUILD! step**, repeating until a KO.

- **FIGHT!** — both players simultaneously flip the top card of their Fight Deck and
  resolve both cards **simultaneously**. The fighter whose card was revealed is the
  **Active Fighter** (performs the actions; is the opponent's default target); the other is
  the **Partner**. Continues until both Fight Decks are exhausted. Played cards keep their
  order and become next round's Fight Deck — **the deck is never shuffled**.
- **BUILD!** — draw the top 3 of your Build Deck, **secretly** pick 1, insert it anywhere
  into your Fight Deck (top, bottom, or between any two cards) without reordering what's
  already there. The other 2 go to the bottom of the Build Deck. **Instant Bonus** cards
  announce and apply their bonus immediately, after both players have inserted.
- **Setup** — the real draft, now that the whole roster is in: deal 6 draft cards to each
  player, each picks 1, swap the remaining 5, each picks a second. Then take each of your
  two fighters' **starting card** and choose which sits on top → your 2-card Fight Deck;
  all their other cards shuffle together into your Build Deck.

**Action glossary** — Attack (target loses HP equal to the Active Fighter's Power);
Block (negates *all* Attacks by the opponent and their Partner this turn — not Direct
Damage, not other effects — and if it negated ≥1 Attack, even a 0-Power one, its **Bonus
Action** fires, once per turn); Direct Damage (unblockable, still triggers Health Track
icons, still stopped by STOP; if combined with a blocked Attack the Attack dies and the
Direct Damage lands); Heal (move the marker up; cannot heal a fighter at KO); Power
Gain/Loss (add/remove cubes from that fighter's Power Supply); Cancel (the opposing
fighter's card is **completely ignored**); Partner / Opponent's-Partner icons (retarget —
"Multiple Attack" is simply both); Instant Bonus.

**Health tracks** — the marker never goes above Max HP nor below the last space (KO). Icons
trigger when the marker **lands on or passes through** a space, **after all markers have
finished moving**; multiple icons passed all trigger simultaneously. A **STOP** icon halts
the marker's movement immediately, up or down, from Attack, Direct Damage or Heal alike.

**End** — a fighter whose marker is on KO **at the end of the turn, after everything has
resolved**, loses the game for their team. Both teams KO'd in the same turn → **draw**.

**Known special tracks** (from BGA's FAQ; the dump supersedes this): Joan's circular Divine
Voice dial, marker starting on the central Halo space and stepping clockwise · Ching Shih's
0–20 Navigation track, gains past 20 ignored · Wong Fei-Hung's Spiritual Balance, his Power
dropping to match his Partner's when theirs is lower · Bödvar's double-sided board, a Rage
track whose top space grants 3 Power and flips him to Berserker Bear, who starts at HP =
Bödvar's cubes at the moment of transformation (capped 15), carries his tokens over, and is
immune to all HP change on the transform turn; some cards print separate Bödvar and Bear
halves and only the visible face applies · The Wild Bunch's HP track where every space is
worth one and the marker moves at most one space per turn regardless of damage or healing.

### Resolution order the engine will implement

1. Reveal both cards; Active Fighter per side = the card's fighter.
2. Snapshot each side's **Power at start of turn** — attack damage uses this, not the value
   after this turn's power changes.
3. Resolve **Cancel** first: a cancelled card contributes nothing at all.
4. Resolve **Blocks**: a Block kills every Attack from the opposing fighter *and* their Partner.
5. Accumulate HP deltas — surviving Attacks, all Direct Damage, all Heals.
6. Move each Health marker, honouring STOP mid-movement; clamp to `[KO, MaxHP]`; a fighter
   at KO cannot be healed.
7. **Then** fire every Health Track icon landed on or passed through, all at once.
8. Apply Power changes, Partner effects, and fighter hooks.
9. Fire each successful Block's **Bonus Action** (once per turn).
10. End-of-turn KO check → loss, or draw if both.

This ordering is inferred from the glossary and is the single highest-risk piece of the
build — which is exactly what the Stage 0(C) replay fixtures are for.

---

## Design

### Package: `games/rag_tag/`

Sub-app `ragtag_app` mounted at `/ragtag`; mode id `ragtag`; table `ragtag_games`; CSS
namespace `.ragtag`. Mirrors `games/dissonance/` — the newest and closest-shaped game (2p,
hidden ordered state, simple room lifecycle).

| File | Purpose |
|---|---|
| `engine.py` | Pure rules: draft, the turn resolution above, build step, KO |
| `fighters.py` | **Generated** static data — all 12 boards, health tracks and decks |
| `effects.py` | `ACTION_OPS` + `FIGHTER_FX` + `FIGHTER_HOOKS` registries |
| `bot.py` | Random bot |
| `main.py` | `ragtag_app`: rooms, WS, REST, persistence, bot scheduling |
| `persist.py` | `compact_state` / `expand_state` |
| `rules.jsx` | Words for the shared `RulesModal` |
| `RagTag.jsx` / `RagTag.css` | Lobby + draft + board + fight animation + build UI |
| `tools/import_bga.py` | `data/*.json` → `fighters.py` (re-runnable) |
| `tools/replay_bga.py` | Replays a captured BGA game through our engine |
| `CLAUDE.md` | Per-area operating manual (repo convention) |
| `tests/` | `test_engine` · `test_fighters` · `test_parity` · `test_ws_auth` · `test_server` · `test_redaction` · `test_bot` · `test_persist` |

`fighters.py` is **generated and committed**, not hand-written — `import_bga.py` is the
source of truth for the transform, so a corrected dump is a re-run, not a re-transcription.
The raw dumps stay in `data/` so the generation is reproducible.

### Game dict

JSON-safe, no sets, RNG as a list — the repo-wide invariant.

```python
{"version": 1,
 "phase": "draft"|"order"|"fight"|"build"|"over",
 "seats": [pid, pid], "teams": [[fid, fid], [fid, fid]],
 "draft_hands": [[fid x6], [fid x6]],     # secret, swapped after the first pick
 "fighters": {...},          # per seat/slot: hp index, power cubes, tracks{}, face, ko
 "fight_deck": [[cid,...], [cid,...]],    # ORDERED — hidden from the opponent
 "build_deck": [[cid,...], [cid,...]],    # ORDERED — hidden from BOTH
 "build_offer": [[c,c,c], [c,c,c]],       # secret, per seat
 "build_choice": [None|{"card":cid,"pos":int}, ...],   # secret until both submitted
 "beats": [...],             # this round's resolution log, for the client animation
 "round": int, "turn_index": int,
 "pending_pid": None, "pending_kind": None, "pending": None,
 "log": [...], "rng_state": [...], "winner": None|0|1|"draw"}
```

`pending_pid`/`pending_kind` exist from day one: a sub-decision must be **real game state**,
not a message field, so it survives saves and reconnects (repo invariant). With 12 fighters
some card will need it. **No undo stack**, which sidesteps the snapshot/`rng_state` dedup
trap the other games pay for.

### Data-driven cards, escape hatch for the weird ones

Mirrors Dontminion's frozen API (`EFFECTS[name](game, pid)` + `STAGES[(name, stage)]`, card
code touching state only through engine helpers):

- A card is a list of ops — `attack`, `block{bonus:[...]}`, `damage N`, `heal N`,
  `power ±N`, `cancel`, `instant_bonus` — each with an optional target
  (`self` / `partner` / `opp` / `opp_partner`).
- Anything not expressible declaratively becomes `{"fx": "<name>"}` → `FIGHTER_FX["<name>"]`,
  keyed on BGA's own effect names so the mapping is mechanical rather than interpretive.
- Health-track spaces carry the same op lists, plus `stop`.
- `FIGHTER_HOOKS` gives each fighter lifecycle callbacks: `setup`, `power` (Wong),
  `on_track` (Bödvar's Rage → transform), `hp_immune` (the transform turn), `hp_move`
  (The Wild Bunch's one-space cap).
- `tests/test_fighters.py` asserts every op name in the generated data resolves to a
  registered handler, deck sizes are consistent, and each health track ends in KO — so an
  unhandled effect from the dump fails loudly instead of silently doing nothing.

### Draft and the two simultaneous-secret submissions

The real draft: deal 6 each, pick 1, swap the remaining 5, pick 1. Then `phase:"order"`.

`order` and `build` are the same shape: each seat **submits secretly** and the phase
advances only when both are in. So there is no "whose turn it is" — the board shows
*waiting for opponent*, and `TurnBadge` needs that state. The bot submits behind a
`BOT_FLOOR_SECONDS`-style floor (as `games/dissonance/main.py` does) so it doesn't answer
instantly.

### The fight animation

The engine resolves the whole FIGHT! step in one call and writes `beats` — one entry per
turn holding both revealed cards and every HP / power / track delta. The server broadcasts
once; `RagTag.jsx` plays the beats with a per-turn dwell (Dissonance's completed-trick beat
is the precedent) plus a Skip. Because `beats` lives in game state, a reconnect mid-animation
re-ships it. **`beats` is replaced each round, never appended** — the repo has already paid
for unbounded in-state logs three times.

### Redaction

`mk_room_state` builds per recipient and must hide, per viewer: the **opponent's**
`fight_deck` (its order is the entire game — ship a count only), **both** `build_deck`s, the
opponent's `draft_hand`, `build_offer`, an unsubmitted `build_choice`, and `rng_state`. Your
own Fight Deck stays visible to you. Per the repo rule, `test_redaction.py` asserts against
the **whole serialized payload of a real in-progress game**, not a synthetic dict.

### Bot (`bot.py`)

Random, seeded off the game RNG: `choose_draft`, `choose_start_order`, `choose_build`
(random card of 3, random insertion index), `choose_pending`. Every move is re-validated by
the engine on arrival. Runs in a thread pool via `_schedule_bot_turn`, **never under
`ROOM_LOCK`** — snapshot under lock, release, run, re-lock, re-validate the phase hasn't
moved, apply, save and broadcast outside the lock.

**No difficulty picker in v1.** `shared/tests/test_ai_difficulty_memory.py` derives its
roster by grepping `games/*/[A-Z]*.jsx` for `ai_difficulty`, so shipping without that field
keeps us honestly out of the roster — and auto-enrols the game the moment tiers land, which
is exactly when `useLastDifficulty` must be wired.

### Reuse

`core/rooms.py` throughout — `normalize_room`, `gen_room_token`, `db_conn`,
`ensure_room_loaded`, `send_json`, `delete_open_game`, `release_socket`,
`encode_state`/`decode_state`, `pack_rng`/`unpack_rng`, `HISTORY_LIMIT`,
`reject_if_connecting_too_fast`, `MessageThrottle`. Frontend: the whole `shared/lobby.jsx`
kit (`.lby-*` grid, `LobbySectionHd`, `LobbyTabs`, `TurnBadge`, `LobbyAction`, `GameMenu`,
`RulesModal`, `useProgressiveList`) — `shared/tests/test_lobby_kit.py` enforces it.

---

## Wiring checklist

Ten edits outside the package. Each is a one-liner whose omission fails quietly.

1. `app.py` — defensive `try/except` mount of `ragtag_app` at `/ragtag` (copy the Dissonance block, `app.py:133-141`)
2. `pytest.ini` — add `games/rag_tag/tests` to `testpaths`
3. `shared/router.js:18` — `MODES` += `"ragtag"`
4. `shared/HomeScreen.jsx:22,38` — tile entry + inline icon SVG
5. `games/spender/Spender.jsx` — `lazyChunk` (~:45), `SCREEN_FOR_MODE` (:111), `MODE_FOR_SCREEN` (:112), the screen branch (~:2853)
6. `webapp/test/screens.mjs` — `SCREENS` entry `{path:"/ragtag", chunk:"RagTag", marker:".ragtag"}` (~:41), the route loops at ~:622 and ~:2056, a new block, **listed in `laneB`** at the foot of the file (an unlisted block passes without running)
7. `.github/workflows/deploy-render.yml` — `games/rag_tag/**/*.py`
8. `.github/workflows/deploy-pages.yml` — `games/rag_tag/**`

   Both files end in trailing negative patterns (`'!**/*.md'`, `'!**/tests/**'`) and *later
   patterns override earlier ones* — so the new glob goes **above** them, or a docs-only or
   test-only commit starts restarting prod again.
9. Root `CLAUDE.md` — the per-area table row, the repo-layout tree, the games list
10. `games/rag_tag/CLAUDE.md`

**Auto-enrolled guards** — no edit needed, but the new files must comply, because these
derive their roster from `games/*/[A-Z]*.jsx` and `games/*/*.css` globs:
`test_lobby_kit` (shared classes, all three columns pinned, `LobbyTabs` with keys and no
`data-tab`, own `--lby-accent`, `GameMenu` offering return/rules/abandon, `LobbyAction` for
row buttons, waiting rooms filtered out of Active) · `test_css_tokens` (no dead tokens) ·
`test_btn_has_a_variant` · `test_hover_never_eats_selection` · `test_no_conditional_skips`
(**zero** `skip`/`skipif`/`xfail` — a state we can't reach must FAIL).

Also: the game's own sheet must **not** set `display`/`grid-template-columns`/`gap` on its
lobby-grid class (game sheets concatenate after the shared one and would pin a phone to
three columns), and CSS goes in a real `.css` file imported `?inline` — never a JS template
literal.

---

## Order of work

| Stage | Contents |
|---|---|
| **0** | *You:* the BGA dumps into `games/rag_tag/data/` |
| **1** | `tools/import_bga.py` → `fighters.py`; `effects.py` registries; `test_fighters` — the dump tells us the real op vocabulary, so this comes before the engine |
| **2** | `engine.py` + `test_engine`; `tools/replay_bga.py` + `test_parity` against the captured replays |
| **3** | `main.py` + `persist.py` + `bot.py` + server/auth/redaction/persist tests; `app.py` + `pytest.ini` |
| **4** | `RagTag.jsx` + `.css` + `rules.jsx`; router / HomeScreen / Spender.jsx / screens.mjs |
| **5** | Both `CLAUDE.md`s, workflow path filters, full gates |

Commit per stage on `claude/rag-tag-team-foundation-zmfmrr`.

---

## Verification

- **Parity against real games** — the gate that makes this faithful rather than plausible.
  `tools/replay_bga.py` feeds a captured BGA notification stream through our engine and
  asserts every turn's HP, power and track values match BGA's, turn by turn. Fixtures
  committed under `tests/fixtures/`, run by `test_parity.py`. This is the same shape as
  Dissonance's Rust parity gate and Dontminion's `replay_prod_saves.py`, and it is what
  will catch a wrong guess in the resolution order above.
- `pytest games/rag_tag/tests -n0` — the new suite, serial, readable output.
- `pytest` — the whole suite; the shared guards auto-enrol the new game.
- **Soak:** `test_bot.py` plays N seeded random-vs-random games to completion over randomly
  drafted teams, asserting every game terminates with a legal winner or a draw, no engine
  exception, no illegal move accepted, and HP/power never out of bounds. With 12 fighters
  the soak must cover **every** fighter — derive the roster from `fighters.py`, never a
  hardcoded count (the `range(13)` lesson).
- **Round-trip:** save → load → resume mid-fight and mid-build reproduces the same state;
  `compact_state`/`expand_state` round-trip on a real game; blob carries the `_c` marker.
- **Redaction:** serialize a real in-progress room per viewer, assert the opponent's Fight
  Deck order, both Build Decks, the opponent's draft hand and build offer, and `rng_state`
  are absent from the bytes.
- `cd webapp && npm run smoke && npm run screens` — smoke never renders a game, so
  **screens** is the real gate; its new block must mount `.ragtag`, fetch the `RagTag`
  chunk, and log no page errors.
- **Play it:** backend `python -m uvicorn app:app --reload --port 8000`; frontend
  `cd webapp && VITE_BASE=/ VITE_WS_URL=ws://localhost:8000/ws npm run dev` — **port 5173**,
  the only port `core/config.py` allowlists for CORS. Create a vs-bot game, run the draft,
  order the starting cards, watch a fight play out, build, and run to a KO. Two human seats
  need two different browser profiles (same-browser incognito shares `localStorage` → one
  identity).
