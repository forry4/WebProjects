# Rag Tag — Claude Context

A faithful implementation of **Tag Team** (Le Scorpion Masqué, 2025): two players,
teams of two Fighters from a roster of twelve, decks that are never shuffled.
Mounted at `/ragtag`, table `ragtag_games`, CSS namespace `.ragtag`.

Read this before touching `engine.py`, and read `data/README.md` before touching
anything under `data/`.

---

## The game, in one paragraph

Draft two Fighters each. Their two Starting Cards, in an order you choose, are your
whole Fight Deck; their other 18 cards shuffle into your Build Deck. Each **round**
is a **FIGHT!** step — both players flip the top card of their Fight Deck at the
same time and resolve both at once, until the decks run out — followed by a
**BUILD!** step: draw three, secretly keep one, slide it anywhere into your Fight
Deck *without reordering what is already there*. The played cards keep their order
and become next round's deck, one card longer. Nothing is ever shuffled again, so
both players eventually know the whole sequence; the game is about where you put
things.

---

## Where the data came from

`PLAN.md` assumed the per-fighter data could only be got out of a logged-in
BoardGameArena table via a devtools dump. **It is all public.** BGA's client CSS is
an asset manifest and the assets it names are on the CDN without a login: 12
fighter boards, 2 backs, 78 card faces. The rulebook PDF fetches fine, and BGA's
Gamehelp wiki page carries a per-fighter section for all twelve plus the FAQ that
settles most of the awkward interactions. The client bundle itself carries **no**
card tables — it is UI only — but its i18n strings name every special track and
list Milady's Intrigue effects verbatim.

`data/*.json` is a **mechanical transcription** of that art — numbers, op lists,
track layouts. The art is not committed: rules are not copyrightable, card text and
illustration are, and a mechanical table is the better engineering anyway.
`tools/fetch_bga_assets.py` re-downloads the sources so a correction can be checked
against the same pixels.

**`fighters.py` is GENERATED and COMMITTED.** `tools/import_bga.py` is the source of
truth for the transform, so a corrected dump is a re-run, never a re-transcription.
`--check` regenerates in memory and the suite fails on a stale file.

### The one gap
Milady's 11 Intrigue tokens carry only **9 distinct** abilities. Which two are
duplicated is not visible in any public source — the pile is face down. It is in
`data/cards.json` §`known_gaps` rather than guessed. A `gameui.gamedatas` dump or a
replay settles it.

### Still wanted: replay parity fixtures
`PLAN.md` §Verification wants `tools/replay_bga.py` feeding a captured BGA
notification stream through this engine and asserting identical state transitions
turn by turn. **That capture is the only part that still needs a logged-in
browser** — the snippet is in `data/README.md`. Until then the resolution order is
pinned by the rulebook and the Gamehelp FAQ rather than tested against the real
implementation. Good, but not the same thing, and it is what would settle the three
INFERRED readings below.

---

## The engine

`engine.py`'s module docstring holds the authoritative turn order. Two things there
correct `PLAN.md`, which guessed:

* **Bonus Actions are not a late step.** "All Actions are considered simultaneous,
  INCLUDING Actions that are conditional to a success" — so a Block's bonus and an
  Attack's bonus join the same pool and net into the same single marker movement.
* **Success is not Block-only.** An unblocked Attack is equally a success (Joan's
  Sword of St. Michael, Wong's Tiger Fist).

### DECLARATION IS TWO PASSES. Do not collapse it.
Conditions that ask about the opposing card — `no_opponent_attacked`,
`self_attacked`, `own_attack_blocked` (the `OPPONENT_DEPENDENT` set) — cannot be
answered while that card is still unwalked. Seat 0 is always walked first, so a
single pass answers them against a half-declared turn **for seat 0 only, every
time**. That is a rules bug that never crashes: it showed up as seat 0 winning 45%
of a 600-game soak and nothing else. Pass one collects the unconditional actions,
the block sweep runs, pass two answers the rest, and the sweep runs again.
`test_bot.py::test_random_play_is_not_biased_towards_a_seat` is the regression.

### Three INFERRED readings
The printed rules do not settle these; they are marked in the docstring and are
what the replay fixtures would confirm.
1. A conditional Attack gated on `no_opponent_attacked` does not itself count as an
   Attack when evaluating that clause — otherwise two mirrored Hidden Daggers are
   circular.
2. "If you are Attacked" counts an Attack that was declared and not cancelled, even
   if a Block negated its damage. Consistent with a 0-Power Attack still triggering
   a Block's Bonus.
3. Maman Brijit's *You are Mine* redirects the Attacks her Block caught onto the
   opposing Partner. Both readings land the damage in the same place, so it is
   harmless either way.

### The op vocabulary is CLOSED
`effects.py` declares every op, condition kind, computed value and target with the
fields each takes, and `import_bga.py` validates the data against it. A
mis-transcribed card fails at import with its path named rather than resolving to
nothing at the table. It earned that on the first run: the Fey Folk's per-Spirit
scaling had been written `per` on one card and `times` on another.

Anything not expressible declaratively is `{"op": "fx", "name": ...}` →
`FIGHTER_FX`. `UNIMPLEMENTED_FX` is empty and the test asserts the data's fx names
are **exactly** `FIGHTER_FX | UNIMPLEMENTED_FX` in both directions, so neither an
unhandled effect nor a stale entry can survive.

### Fighters that break the general rules
| Fighter | What is special |
|---|---|
| Bödvar | Double-sided board. Rage tops out → +3 Power, **then** flip; the Bear's opening HP is his cubes *at that instant* (so the transform flushes his queued Power first), capped 15, not a ceiling afterwards. Immune to all HP change that turn. |
| Maman Brijit | **Two** KO spaces with a revive space *below* them. Pushed past both she gains 1 Power and returns to HP 4 at end of turn; the revive space is the floor, so further losses there are ignored. |
| The Wild Bunch | Moves at most one space a turn, up or down, whatever the total. Falls out of a STOP on every space below the top — no hook needed. |
| The Fey Folk | Three Characters, one at a time, each with their own track and no KO space. Losing the last HP moves the marker to Spirit; at end of turn the Spirits track advances and the next Character is chosen (a real `pending`). With all three gone they still act but cannot lose or recover HP, and they are KO **only** to their own *All Legends Must Pass*. |
| Shango | Incineration (5 Aflame!) is an instant loss that **overrides** a double KO. |
| Mephisto | *Drag You to Hell*: lose this turn for any reason and you win instead — Incineration included. |
| Wong Fei-Hung | *Crippling Touch* removes both cards from the game permanently, so decks shrink. |
| The Golem | *Reanimation* resolves the next card twice, the second pass as a fresh turn for him alone. |

### Game state
JSON-safe throughout: no sets, RNG as a list, sub-decisions in
`pending_pid`/`pending_kind`/`pending` so they survive saves and reconnects.
**No undo stack**, which sidesteps the snapshot/`rng_state` dedup trap the other
games pay for — there is exactly one RNG copy for `persist.py` to pack.

Cards are **instances**, not ids: `instances[i] = {cid, seat, slot, flipped}`, and
decks are lists of instance indices. The Fey Folk's Summoning cards flip per copy
and Crippling Touch removes specific copies, so a bare card id is not enough.

---

## The server

`main.py` is the shared six-game scaffolding. What differs:

**The game is SIMULTANEOUS**, so there is no seat on turn. The server asks
`engine.may_act`, and `_position_key` **includes who has already submitted** — a
phase-and-round key would call a simultaneous submission "unchanged", letting a
stale bot move apply against a position that had already moved on while the human
acted.

**Redaction.** Both players know which cards exist (the fighters are face up), so
the hidden information is unusually concentrated: your Fight Deck's **order** is
very nearly all of it. `test_redaction.py` searches the serialized payload for the
opponent's deck **sequence** rather than membership, because the instance→card
table is legitimately public.

**The bot plays at random**, deliberately, so the game is playable and testable
before strength work begins. There is **no difficulty picker**, which keeps this
game honestly out of `shared/tests/test_ai_difficulty_memory.py`'s roster — that
test derives its roster by grepping `games/*/[A-Z]*.jsx` for `ai_difficulty` and
will auto-enrol Rag Tag the moment tiers land, which is exactly when
`useLastDifficulty` must be wired.

---

## The frontend

Four files: `RagTag.jsx` (the screens), `art.jsx` (every drawn thing),
`narrate.jsx` (beats → sentences), `RagTag.css`.

`RagTag.jsx` renders cards from their **op lists**, not from text — the generated
data is mechanics only, so the UI says what a card does in its own vocabulary and
no second transcription lives in the frontend to drift. The one exception is
`FX_TEXT` in `art.jsx`: the `fx` ops are the cards the op vocabulary cannot
express, and rendering the literal op name put the word "Special" on the table.
Its wording follows the fx docstrings in `effects.py`.

**`you_owe` comes from the server.** A simultaneous game has no "your turn" to read
off the phase; a client that re-derives it shows the wrong prompt the moment the two
disagree, which the first draft of this file did.

### THE FIGHT IS STEPPED BY HAND
The FIGHT! step arrives as `beats` — one entry per turn with both revealed cards and
every delta. It used to play itself at a fixed 900ms a turn, which meant the only
thing worth watching was gone before it could be read. **Every turn now waits for a
click** (Back / Next turn / To the end), and nothing here drives the server: the
whole round is resolved and saved before the first card is shown, so stepping is
pure replay and a reconnect just restarts it. Beats live in game state and are
**replaced each round, never appended**.

Two consequences worth knowing:
* **The next prompt is held until the last turn is on screen** (`owes` returns null
  while `!atEnd`). Otherwise the round's outcome arrives as a question before the
  player has seen what happened.
* **A beat is not always a turn.** Setup and instant-bonus beats carry no revealed
  cards, and counting them made the stage read "Turn 1 of 1" over two empty card
  slots before anything had been played. `isTurnBeat` is the test, in both
  `RagTag.jsx` and `narrate.jsx`.

### The log is history, the stage is the moment
`narrate.jsx` turns a beat's events into sentences, and the SAME function feeds the
ribbon under the cards and the battle log — so the two cannot disagree. The log
shows the turns **already stepped past**, not the one on the stage; rendering both
put the same four sentences on screen twice, ~700px apart, which three independent
reviewers each called out. Finished rounds are archived as their NARRATED ROWS, not
as beats, because the text depends on board state that has since moved on.

### Press-and-hold / right-click reads anything
Every face that stands for a fighter or a card — the four board panels, both
played cards, the draft picks, the who-leads options, the build offers and the
rows of your Fight Deck — opens a detail modal on right-click or a long press.
The gesture is `useCardInfoGesture` in **`shared/gestures.js`**, shared with
Dontminion: the hard half is that **Android fires `contextmenu` on a long press
and iOS Safari does not**, so touch needs a real timer, and that is not a thing
to keep two copies of. Both paths funnel through one `fired` flag so a hold can
never also play the card.

Because most of those faces are rendered inside `.map()`, they go through
`<InfoTarget>` rather than calling the hook directly — a hook cannot be called
in a loop, and the wrapper gives each element its own instance.

The modal is where the rules text lives that will not fit on a face: the
**per-card notes** from the data (20 cards have one, and they settle exactly the
interactions a player stops and wonders about), and `boardFacts` — a fighter's
oddities DERIVED from their track rather than written out, so a corrected import
fixes the modal too. Watch the three shapes `special_track` comes in: a real
space list (Bödvar, Joan), a min/max range with `spaces: []` (Ching Shih, the
Fey Folk), and **an empty object for a fighter that has none** — which is
truthy, and printed a track Milady does not have.

### Everything visual is drawn in the bundle
There is no licensed art in the repo (see *Where the data came from*), so `art.jsx`
carries a hand-authored emblem and accent colour per fighter plus the mechanical
icon set. Hand-drawn beats a hash — a hashed hue puts the pirate and the devil on
neighbouring reds. No file is fetched, so nothing can 404 or need a cache-bust.

### Two layout traps, both paid for twice
* **`baseCss` is not optional.** Rag Tag shipped without it. The shared lobby kit is
  written against the site theme tokens (`--surface`, `--border`, `--radius`), so
  every `border: 1px solid var(--border)` in that kit was invalid at
  computed-value time and resolved to `0px none`. The lobby still laid out, so it
  read as a design choice rather than a missing import.
* **`.app` is a COLUMN FLEX container**, and both `.rt-wrap` and the shared
  `.lby-cols` carry `margin-inline: auto`. Auto margins beat `align-items: stretch`
  on a flex item, so both shrink-wrapped to their content: the whole game rendered
  in a ~430px strip on an 834px tablet, and the layout WIDTH CHANGED BETWEEN PHASES
  because content was driving it. Any centred wrapper inside `.app` needs an
  explicit `width: 100%`. Dontminion hit this and fixed it the same way;
  **Spender Duel still has it** (`.duel-lobby-cols`, measured 851px of 1440).

CSS is a real `.css` file imported `?inline` — never a JS template literal. The
sheet must not set `display`/`grid-template-columns`/`gap` on `.rt-lobby-cols`: it
is concatenated after the shared one, so a base rule there out-orders the shared
media rules and pins a phone to three columns. Width and padding ARE fair game.

---

## Testing

`pytest games/rag_tag/tests -n0 -q` — 94 tests.

| File | Covers |
|---|---|
| `test_fighters` | the generated data: staleness, the closed op vocabulary, deck sizes, every track able to end a fighter, and that no `--` transcription artefact reaches the detail modal |
| `test_engine` | the rules, mostly by rigging an exact position and resolving ONE turn — a simultaneous game has no "make a move and see"; plus the beat NARRATION events (attack/block/cancel), which render as an empty log line rather than as any kind of failure |
| `test_bot` | the soak: whole games over random teams, every fighter forced in, invariants, seat symmetry |
| `test_server` | rooms, moves, the bot scheduler end to end |
| `test_ws_auth` | seat identity binding |
| `test_redaction` | the whole serialized payload of a REAL played game |
| `test_persist` | compaction round trip, structural proof it did something, resume mid-fight and mid-build |

Frontend: `webapp/test/screens.mjs` §`ragtagFight` (lane A) creates a vs-bot game
and plays a full round in a browser. Mounting the route proves nothing about a
simultaneous game; only playing one does. It specifically asserts the two things a
render test would miss: that the fight **does not advance on its own**, and that the
next decision is **held back** until the last turn is on screen.

**No `test_parity` yet** — it needs the BGA replay fixtures above. It is absent
rather than skipped, because the repo's rule is that a test which cannot reach its
state must FAIL, not opt out.

---

## Open follow-ups

* The replay parity fixtures, and with them `tools/replay_bga.py` + `test_parity`.
* Milady's two duplicated Intrigue tokens.
* A bot with any strength at all, and the difficulty picker that comes with it.
* The lobby empty states, the emoji Rules glyph and the History column width are
  all the SHARED kit (`shared/lobby.jsx`), flagged repeatedly by the visual review
  but owned by seven games — a change there is a seven-game change.
* The 14 expansion fighters BGA also serves (Arthur's Legacy and one more) — the
  importer and the op vocabulary already handle their shape; only the transcription
  and their special rules are missing.
