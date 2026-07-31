# Dontminion (Dominion: Base + Intrigue + Seaside + Prosperity + Hinterlands, all 2E)

2–4 players, 139 cards. Mounted at `/dontminion`. Plan + full domain spec:
`.claude-plans/i-want-to-add-luminous-pebble.md`; the FULL-CATALOG expansion roadmap (all 16
sets, phased by kernel mechanic) is `EXPANSIONS.md`. Rules source of truth: the Knutsen
compendium `C:\Users\Forrest\Downloads\Dominion_CompleteRules_v11.1.pdf` (ch. VII = per-card
rulings); card texts cross-checked against dominionstrategy.com/card-lists/.

## Layout

| File | Role |
|---|---|
| `cards.py` | static data ONLY (schema below); `DATA_COMPLETE` sentinel; `BANDIT_VICTIM_CHOOSES` ruling |
| `engine.py` | the kernel: rules, frames, attack window, validation, scoring, `player_view` |
| `effects_base.py`, `effects_intrigue.py`, `effects_seaside.py`, `effects_prosperity.py`, `effects_hinterlands.py` | ONE module per expansion, each owning a disjoint card set |
| `effects.py` | merges the registries; duplicate registration raises |
| `bot.py` | the bots: random-legal (easy/normal/hard) + the Big Money buy ladder (`bigmoney`) |
| `main.py` | FastAPI sub-app: rooms/WS/persistence/multi-bot scheduler |
| `tests/` | engine, soak, per-batch card tests, cross-set, migrate, server, ws-auth, wire-redaction, wire-contract |
| `tools/replay_prod_saves.py` | THE migration gate — replays every real prod save (see below) |

**Card batches are still written in two halves per expansion** (a simple half and a
mechanically complex half) by two parallel agents that may touch only files they own — the
halves are CONCATENATED into the one module when the phase lands. The `tests/test_cards_<set>_a/b.py`
files stay split: each half's fixtures (`fresh`/`give_hand`/`decide`) differ, so merging them
would silently let one definition win and change what the other half's tests exercise.

## Save-shape versioning (`SCHEMA` + `migrate`) — READ BEFORE ADDING A GAME-DICT KEY

`engine.SCHEMA` (now **3**: 1 = Base+Intrigue, 2 = Seaside, 3 = Prosperity) is the game-dict
shape version, stamped by `new_game`. `engine.migrate(game)` upgrades any older persisted blob
in place and is called by `main.load_game_to_memory` — THE migration point. Because of it the
kernel may assume the CURRENT shape: **do not add defensive `.get()` for a key `migrate`
guarantees** (28 of them were retired when this landed). Genuinely lazy transients
(`dur_setup`, `_turn_gains`, `_cur_dur`) stay lazy.

**Every phase that adds a key the kernel reads owes: a `SCHEMA` bump, an entry in
`_GAME_FILLS`/`_SEAT_FILLS`, and a case in `tests/test_migrate.py`** (which downgrades a CURRENT
game to each old shape, so the tests stay honest as the dict grows). Live prod games predate
every later phase.

**Fills are UNCONDITIONAL — never put a key-fill behind `if v < N:`.** A stamp only partitions
shapes if it was bumped in the same commit that added the key, and ours wasn't: prod carries
`schema = 2` blobs written across the whole Seaside AND Prosperity eras, including games that
predate keys added later under that same stamp. Replaying all 26 real prod saves found two live
games at `schema = 2` with no `last_turn_gains` — a version-gated fill skips them and the kernel
(no longer defensive) `KeyError`s at the next end of turn. `setdefault` is idempotent, so an
unconditional fill can never be wrong and costs one lookup. The version gate is reserved for
genuine **transforms** — a key whose meaning or value shape changed, where re-running the step
would corrupt a current game. There are none yet.

**CARD RENAMES go through `_RENAMES` + a SCHEMA bump.** We ship the publisher's CURRENT names
(user directive) — Intrigue's Harem is **Farm** (renamed 2023). A rename is not a cosmetic
edit: the string sits inside live prod decks, hands, discards, in-play, mats, duration entries
and riders, trash, the supply's KEYS, the kingdom list, `last_turn_gains`, open pending frames'
constraint/data, every undo snapshot (whole game dicts) and the log. `_apply_renames` therefore
walks the entire structure rather than enumerating zones. It protects player identity
POSITIONALLY — by which key holds it, never by comparing values — because a display name can
legitimately equal a card name, and a value-blind guard would then refuse to rename the real
card and leave the game holding one the kernel no longer knows. This is the FIRST genuine
transform step, and its `v < 4` gate is sound precisely because SCHEMA was bumped in the same
commit (the condition the unconditional fills above could not rely on).

**Replaying prod saves is the migration gate.** `migrate` is the one piece of code whose input
is history rather than the current tree, so tests built from a current game can't fully cover it
— pull the real blobs (Turso creds in `~/.spender_turso`, query `/v2/pipeline`) and play each
one forward before shipping a shape change.

**Undo snapshots exclude the LOG.** The log is append-only, so a snapshot stores `_log_len` and
`_undo_move` restores by truncating (`n` stays == index). Copying it put up to `_UNDO_CAP`
copies of a growing log into every save blob — measured 487 KB → 150 KB on a late-game
position, written to Turso on every move.

## THE FROZEN ENGINE API (stop-the-line to change — escalate, never edit the kernel from a batch)

**Moves** are dicts keyed on `"type"`: `play_action` / `play_treasure` / `play_all_treasures` /
`buy` / `end_phase` / `decision` (+payload). WS envelope: `{"action":"move","move":{...}}`.

**Frames** (`game["pending"]` stack; `pending_pid`/`pending_kind` mirror the top; auto frames are
run by `_drive` so at rest the top is a decision frame or the stack is empty):

```python
frame = {"kind", "pid", "card", "stage", "constraint", "data"}
# choose_cards   {"cards","min","max","purpose"} -> {"cards":[...]}   sub-multiset, count in [min,max]
# choose_pile    {"piles"}                        -> {"pile"}          pusher guards non-empty
# choose_option  {"options":[{"id","label"}],"pick","distinct"} -> {"ids":[...]}
# order_cards    {"cards"}                        -> {"order"}         multiset-equal permutation
# place_in_deck  {"card","deck_len"}              -> {"position"}      0 = top of deck
# name_card      {"cards"}                        -> {"card"}          any supply pile name
# auto           parked continuation; never observable at rest
```

**Engine API**: `new_game(player_ids, expansions, seed=None, names=None, kingdom=None)` (players
arrive in seat order — the SERVER shuffles; `kingdom` overrides the random 10: the forced-kingdom
test seam) · `apply_move(game,pid,move)->(ok,err)` (gate order: over → pending → turn → handler;
then `_drive` → `_post_move`) · `legal_moves` (never empty for the actor; complete iff ≤200) ·
`sample_decision(game,pid,rng)` (uniform valid payload; caller's rng, never the game's) ·
`is_over`/`winners`/`score_game` · `player_view` · `cost(game,card)` (base − bridges, min 0 — THE
only cost function; never read `CARDS[c]["cost"]` for a comparison).

**Kernel helpers for card code** (game mutations go ONLY through these + the `push_*` family):
`draw(game,pid,n)` · `look_top(game,pid,n)` (→ seat `aside`; excluded from mid-look shuffles) ·
`gain(game,pid,card,dest="discard"|"hand"|"deck")->bool` (False on empty pile — "gain nothing") ·
`gain_from_trash` · `trash(game,pid,cards,zone="hand")` · `trash_from_supply(game,card)` ·
`discard(game,pid,cards,zone="hand",public=False)` (hand discards log count only) ·
`topdeck(game,pid,card,zone="hand",public=False)` · `reveal(game,pid,cards,source)` (log-only;
revealed hand cards STAY in hand) · `play_action_card(game,pid,card,from_zone="hand"|"discard"|
"aside"|None)` (None = throne-room replay / lost-track: runs the effect without moving; counts
`actions_played`; wraps Attack plays in the reaction window) · `take_aside(game,pid,cards,dest="hand"|"discard")` (out of the aside zone) ·
`deck_from_aside(game,pid,order)` (aside → top of deck, order[0] on top: Sentry/Patrol) ·
`deck_insert(game,pid,card,position,zone="hand")` (Secret Passage; 0 = top) ·
`pass_card(game,giver,receiver,card)` (Masquerade; logs privately to the pair) ·
`add_actions/add_buys/add_coins` (each logs a public `plus` line — the client's
"gets +$2 / +1 Action" sub-effect lines come from these, so don't bypass them) ·
`opponents(game,pid)` (turn order) · `count_empty_piles` ·
`attack_opponents(game,pid,card,per_opp_stage,data=None,immune=None)` (a card whose attack part
runs in a LATER stage — Minion, Replace — must capture `list(game["_atk_immune"])` into its frame
data during on_play and pass it back via `immune=`) · `_log(game,pid,event,
private_to=None,**kw)`. Turn counters (`game["turn_ctx"]["bridges"/"merchants"]`) are incremented
directly by the owning card's effect.

**Kernel v3 — the phase-3 (Hinterlands) delta. FROZEN: batch agents build against this.**
- `cost_lt(game,card,coins)` — "cheaper" / "costing less than" is STRICT, unlike `cost_le`.
  Border Village, Berserker, Haggler. Like `cost_le`, this is where the future cost VECTOR lands.
- `exchange(game,pid,card,into,zone="discard") -> bool` — return `card` to its pile, take `into`
  from its pile into the DISCARD ("no matter where you gained the card to"). **Emits nothing**:
  Trader's "you DID gain the card… you DIDN'T gain the Silver", so a `gain` here would
  double-fire every when-gain watcher. False if `into`'s pile is empty or the card moved.
- `shuffle_into_deck(game,pid,cards,zone="discard")` — Inn. Shuffles **even when `cards` is
  empty** ("if you shuffle zero cards into your deck, you still shuffle"); marks revealed.
- `find_card_zone(game,pid,card,zones=("discard","hand","trash")) -> zone|None` — the LOSE-TRACK
  guard. A when-gain/trash/discard reaction fires after the card landed, but something may have
  moved it since; "cards that are lost track of can't be played". Ask this instead of assuming a
  zone, or you will `remove()` a card that isn't there.
- `play_action_card(..., from_zone="trash")` now works (the shared pile, not a seat zone) — Trail.
  Pass `count=(pid == game["turn"])` for any OFF-TURN play: an opponent's reaction must not bump
  the turn player's `actions_played`.
- **`add_actions/add_buys/add_coins` are actor-aware.** Card code still calls them with no pid;
  the kernel binds `_actor` around every effect and stage, and a bonus earned on someone else's
  turn EVAPORATES (logged `off_turn_bonus`) instead of landing in the turn player's pool — pools
  are per-turn ("your money pool is empty" at turn start). `add_coins` also accepts a NEGATIVE n,
  clamped at $0 (Souk: "you might lose more than $X when deducting").
- **`discard_then_putback(game,pid,card,chosen,rest)`** — THE look-at-cards / discard-some /
  put-the-rest-back shape (Sentry, Lookout, Rabble, Cartographer). It pushes the put-back FIRST
  so it sits BELOW the discard's when-discard triggers, which the discard then stacks on top:
  compendium, Sentry — "TRIGGERED ABILITY (first trash, then discard, **then put cards back**)".
  Doing the obvious thing instead (push the put-back last) returned the kept cards to the deck
  before a discarded Tunnel/Trail/Weaver could react, and a Trail's +1 Card then drew a card the
  player was never allowed to see. Four cards each had their own copy of this ordering and all
  four had it backwards, including a shipped one the new card was told to copy. Use the helper.
  It relies on **kernel stages named `__*` being usable by ANY card** (`_stage_fn` falls back to
  `("*", stage)`), so the frame still displays the card's own name.
- **`ATTACK_REACTIONS`** — a module-level registry (merged like EFFECTS): `{card: {"label",
  "when": fn(game,pid), "immunity": bool, "mode": "reveal"|"play", "stage": str|None,
  "repeatable": bool}}`. `mode:"play"` is REACTION THAT PLAYS ITSELF (p53) — plays from hand, no
  Action spent, no immunity, discarded in THAT turn's clean-up. A `stage` must call
  `reopen_attack_window(game,pid)` when done; without a stage the kernel re-opens it for you.
- Attack-typed **Treasures** open the reaction window too (Cauldron).
- Clean-up discards EVERY seat's `in_play`, not just the turn player's.
- `emit`s available: `gain` (via_buy/dest), `buy`, `play_treasure`, `trash`, `discard` (per card,
  AFTER the whole batch moves), `cleanup_discard`, `buy_phase_end`, `turn_start`, `would_gain`.
  ⚠ **`cleanup_discard` fires but `_end_turn` is NOT interruptible** — `emit` parks an auto frame
  and the sweep doesn't drive frames, so a consumer cannot yet MOVE the card. Scheme needs that
  built; do not assume it works.

**Kernel v2 — DURATIONS (Seaside; the contract for later expansions too):**
`add_duration_fx(game,pid,card,stage,data=None)` — register a start-of-NEXT-turn ability on the
duration card currently being played (callable from on_play or any later stage of the same play;
the physical-card setup entry is created eagerly by `play_action_card`/`_play_one_treasure` for
duration-typed cards, and Throne Room replays add to the SAME entry). At the owner's next turn
start the fx run as auto frames (they may push decisions); the card (plus riders) then discards
at that turn's clean-up. An effect that registers NOTHING = "failed to set up" → discarded
normally · `add_watcher(game,pid,card,event,stage=None,data=None,until="owner_turn_start")` —
cross-player trigger; events: `"gain"` (any player gains; stage data gets actor/subject/owner),
`"play_treasure"`, `"protect"` (Lighthouse 2022 until-next-turn attack immunity — no stage;
`attack_protected(game,pid)` consults it, auto-immunity is applied+logged by the attack wrap);
`until="turn_end"` for this-turn triggers (Sailor) · `watcher_data(game,owner,card)` — the LIVE
data dict (per-turn bookkeeping, e.g. Corsair's first-treasure-per-player) ·
`remove_watcher(game,owner,card,n=1)` · `mark_duration_rider(game,pid,duration_card,rider)` —
Throne Room stays out with a Duration it directly played (effects_base does this) ·
`set_aside_duration`/`take_dur_aside(game,pid,cards,dest)` — the owner-only `dur_aside` zone
(Haven; Blockade gains straight there via `gain(...,dest="dur_aside")`) · `to_island(game,pid,
cards,zone)` / `to_village_mat` / `take_village_mat(game,pid)` — the scoring mats ·
`request_extra_turn(game,pid)` — Outpost: clean-up draws 3 ALWAYS once played; the extra turn
only if the previous turn wasn't also pid's · `duration_in_play(game,pid,card)` — "is it on the
table" (in_play or persisting; Sea Chart's copy check). Kernel also records
`game["last_turn_gains"][pid]` = cards pid gained during their own last completed turn
(Smugglers) and `turn_ctx["gained_victory_in_buy"]` (Treasury's gate). KNOWN SIMPLIFICATIONS
(documented, acceptable): start-of-turn fx resolve in registration order (officially
owner-sequenced); the 2025 lose-track rule is approximated (fx die with the entry); Sailor
won't offer to play a Duration gained into the Blockade set-aside. Duration discard follows
the OFFICIAL timing: done entries sweep at the next clean-up whoever's turn it is (a denied
Outpost is marked done between turns). Play-time attack immunity (Moat/Lighthouse) is captured
into watchers, so Corsair/Blockade delayed effects respect it. Vault skips the pointless
0-1-card opponent discard offer (feasibility-filtered against the engine's own no-filter rule
— MUST be unfiltered before a when-discard card ships; Tunnel is PHASE 3, see the ledger).
Watchtower can trash but not topdeck a card gained to Blockade's set-aside (lose-track
reading; cross-set corner).

**THE TRIGGER BUS (the extension contract for every future set):** the kernel `emit()`s a
single event vocabulary — today `"gain"`, `"buy"`, `"play_treasure"`, `"trash"`,
`"buy_phase_end"` (all fired AFTER the change applies) — consumed by (1) dynamic WATCHERS
(`add_watcher`, per-play instances) and (2) the static `TRIGGERS` registry. Adding a new set's
timing = at most one new `emit()` call site plus registry entries; NEVER a new bespoke kernel
mechanism. `TRIGGERS[card] = [{"on": event, "from": source, ...}]` with sources: `"hand"`
(reaction window offered to each holder in turn order — Pirate; Watchtower/Sheepdog later;
needs `stage`, optional `when(game,pid,ctx)`), `"in_play"` (runs `push(game, actor)` once if
the actor has a copy in play — Treasury; Hoard/Goons-class later), `"self"` (fires when the
event's SUBJECT is this card — the whole Hinterlands when-gain theme and Dark Ages on-trash;
needs `stage`). `COST_MODS[card] = fn(game, priced_name) -> reduction` is the while-in-play
cost-modifier seam (Quarry-class), summed per copy on ANY table inside `cost()`.

**Kernel v3 (Prosperity):** `add_vp_tokens(game,pid,n)` (public, score-counted, never lost) ·
`cost_le`/`cost_eq` are THE cost comparators (raw `cost() <= n` in card code is a review
reject — the future Potion/Debt vector lands inside them) · `has_type`/`types_of`/`coins_of`
are THE type/coin queries (game-wide injections live there: `game["curse_is_treasure"]`,
Charlatan's rule, set at new_game from the kingdom) · `turn_ctx["quarries"]` (turn-scoped
Action discount, applied inside cost()) · `buy_gate()` consults `BUY_GATES` in _h_buy AND
legal_moves (gaining bypasses) · Peddler-class self-costs via `DYN_COSTS` · `MANUAL_TREASURES`
are skipped by play_all_treasures (interactive treasures stay in hand for individual plays) ·
the WOULD-GAIN protocol: `gain()` parks as __gain/resolve + reaction window when a
`TRIGGERS on="would_gain"/from="hand"` matches the gainer; replacement stages call
`cancel_pending_gain(game)`; gain events carry `via_buy` + `dest` (Hoard vs Mint) ·
Platinum/Colony: probabilistic setup per the official randomizer-proportion rule
(`game["colony"]`), Colony-empty ends the game · `_start_of_turn` emits `"turn_start"`
(Clerk-class hand reactions) · hand-reaction specs take `mode:"reveal"` and `who:"actor"`.

**Registration** — each effects module exports exactly:
```python
EFFECTS: {card_name: on_play(game, pid)}
STAGES:  {(card_name, stage): fn(game, pid, frame, choice)}   # choice None for auto frames
TRIGGERS: {card: [spec, ...]}      # optional — trigger-bus entries (shape above)
COST_MODS: {card: fn(game, name)}  # optional — while-in-play cost modifiers
DYN_COSTS: {card: fn(game)}        # optional — the card's own dynamic cost (Peddler)
BUY_GATES: {card: fn(game, pid)}   # optional — buy restrictions (Grand Market)
MANUAL_TREASURES: {names}          # optional — treasures play_all must skip
```
The resolver pops the frame BEFORE dispatching (stages never clean up). Treasures and pure
Victory/Curse cards need NO entries (handlers + `cards.py` data cover them).

**Attack timing (kernel-owned — card batches implement ONLY the per-opponent stage):** reaction
windows (Moat; Diplomat iff hand ≥5) open per opponent in turn order when the Attack is PLAYED,
BEFORE its play ability — before the attacker's own benefits and before any mode choice. Immunity
is per attack PLAY (frame-local). Opponents with no reaction get no window (accepted timing
side-channel). Then the ability runs: attacker effects, then `attack_opponents` queues the
per-opponent stage for non-immune opponents, each fully resolving before the next.

**cards.py schema**: `CARDS[name] = {cost:int, types:[lowercase], coins:int, vp:int|"gardens"|
"duke", text:str, expansion:"basic"|"base"|"intrigue", kingdom:bool}`; `KINGDOM={"base":[26],
"intrigue":[26]}`; `pile_size(name,n)` (Copper 60−7n, Silver 40, Gold 30, Curse 10(n−1),
victory-typed 8/12, else 10); `DATA_COMPLETE`.

## Rules the engine enforces globally (don't re-implement per card)

- Choices are never feasibility-filtered (a player may pick an option they can't fully do);
  effects then do as much as possible; `push_choose_cards` clamps min/max to availability.
- "If you do/did" contingency is the CARD's job (e.g. Trading Post checks it trashed 2).
- Effects are immediate (a trashed Mining Village still gives its bonuses); Conspirator-style
  conditions are read at the card's own resolution.
- Multi-player effects resolve in turn order from the current player (`attack_opponents` /
  `opponents` give that order).
- Shuffle only when short (2E rule); reveals/looks go through `aside` so mid-look shuffles
  exclude them; treasures can't be played after a buy (`turn_ctx["bought"]`).
- **`play_all_treasures` classifies every Treasure into one of three buckets** — adding a
  Treasure with an ability means picking one, and "has an effect" is NOT the criterion:
  1. **`MANUAL_TREASURES`** — playing it pushes a DECISION frame (Anvil, Crystal Ball,
     Investment, Tiara, War Chest), which can't be answered mid-autoplay. Also the bucket for a
     Treasure where playing EARLY might genuinely be right (the button must not choose for the
     player), **and for any Treasure that DRAWS, LOOKS or REVEALS** — see the undo rule below.
  2. **`AUTOPLAY_LAST`** — its value depends on what is already in play, and later is NEVER
     worse (Bank: +$1 per Treasure in play counting itself). Autoplayed, but sorted after the
     rest. Hand order is arbitrary from the player's side, so leaving Bank where it fell cost up
     to 40% of a turn's coins — measured $6 vs $10 on one five-card hand. The sort is STABLE, so
     everything else keeps hand order (replay determinism compares on it).
  3. **autoplayed** — everything else, including Treasures whose rider lands later anyway
     (Collection, Hoard, Quarry, Astrolabe: their effects fire at buy time or next turn, so
     ordering can't matter). These are exactly the cards players want one-clicked; do NOT make
     them manual.

  **The bulk play MUST stay undoable, and that constrains bucket 3.** `play_all_treasures` is
  ONE move with ONE undo snapshot, so a single reveal anywhere inside it clears the stack and
  takes the WHOLE bulk down — including the treasures that were perfectly reversible. Played one
  at a time the player could still rewind everything up to the revealing card, so autoplaying it
  would strictly REDUCE what they can undo, on a bulk action whose riders (Hoard/Collection
  watchers, Bank's total) they may not have anticipated. A drawing/looking/revealing Treasure
  therefore goes in bucket 1, where the player chooses when to burn their undo.
  `test_every_autoplayed_treasure_leaves_the_bulk_play_undoable` enumerates the autoplay bucket
  FROM THE REGISTRIES and asserts undo both succeeds and fully restores state (zones, coins,
  buys, watchers, turn_ctx, durations), so a future set's treasure is covered the day it lands;
  a companion test demotes Crystal Ball to prove the guard isn't vacuous.

  A fourth case exists and is NOT built: suppression that depends on GAME STATE rather than the
  card (Allies' Highwayman negates the first Treasure its victim plays, so which one goes first
  becomes a real choice — and the block LIFTS once spent). A card list cannot express that; it
  needs an `autoplay_block(game, pid)` predicate shipped in `player_view`, not `/catalog`. See
  the ledger in EXPANSIONS.md — build it at the first set that needs it.
- **A move that changes nothing must be REJECTED, and `legal_moves` must not offer it.** The
  interactive treasures (`effects.MANUAL_TREASURES` — War Chest, Anvil) are skipped by
  `play_all_treasures` because they'd push a decision frame mid-autoplay; `legal_moves` offered
  that move for a hand holding *only* those, the handler played none and returned ok, and the
  bot (which prefers it unconditionally) burned the scheduler's whole 300-iteration cap on
  no-op broadcasts + DB saves, leaving two live prod games stuck. Read the registry through
  `engine.manual_treasures()` — the enumerator, the handler, and `/catalog` (which the frontend
  uses to hide the button) all go through it so they can't disagree. The soak now asserts every
  accepted move changes the game dict; a decision that logs nothing is fine, since it still pops
  its frame.
- **Action→buy AUTO-ADVANCES** (`_maybe_auto_buy`): once effects are fully resolved (no
  pending) and the turn player has no Actions left or no Action card in hand, the phase flips
  to buy. Evaluated after each move (inside apply_move) and at the `_end_turn` hand-off —
  NEVER at new_game, so test fixtures that stage a hand post-deal still start in the action
  phase. It folds into the causing move, so that move's undo snapshot restores the pre-move
  action phase.
- **Undo is per-MOVE and gated on HIDDEN INFORMATION** (the Duel model, one step at a time):
  `apply_move` pushes a snapshot onto `game["undo_stack"]` before each of the TURN PLAYER's own
  moves (popped back off if the move is rejected); `{"type":"undo_turn"}` pops one — press
  repeatedly to walk back to the start of the turn ("nothing to undo"). `_mark_revealed` (draw /
  look_top / reveal / pass_card / any non-turn player's decision) locks AND clears the stack —
  nothing this turn is undoable once information was exposed. Snapshots exclude the stack itself
  (no nesting), never ship (`player_view` sends only `undo_depth` + `turn_revealed`, which drive
  the client button), and undo is handled BEFORE the pending gate (an unrevealed Militia can be
  taken back before the opponent answers). `legal_moves` never offers it (keeps the bot honest).

## OPEN AMBIGUITIES & DELIBERATE DEVIATIONS — the standing list

Every entry here is a place where we made a CHOICE the rules didn't force. They are recorded so
a future change is a visible decision rather than a silent drift, and so an auditor can tell
"we picked a legal branch" apart from "this is a bug". **Add a row whenever you resolve a
genuine ambiguity; delete one when a later source settles it (and say which).** Each has a test
pinning the current behaviour, so changing your mind means changing a test on purpose.

**A. Rules genuinely ambiguous — we picked one legal branch**

| # | Question | What we do | Why it's open |
|---|---|---|---|
| A1 | A **throne-roomed Attack**: one reaction window, or one per replay? | One window **per replay** — a Moat holder is asked twice and must reveal twice; immunity is per-play. | p53 says a reaction triggers "whenever an Attack card is *played*" and Cultist 3 wants a reveal per play; but Moat reads "unaffected by **it**" and Reckless 8 says one reveal covers both resolutions of a single play. Not settled either way. Pinned by `test_throne_room_on_a_new_attack_opens_a_reaction_window_per_play` + its decline twin. |
| A2 | A gained card's **own when-gain** vs a **hand-reaction window** (Watchtower/Trader) firing on the same gain | The gained card's own ability resolves **first**. | The compendium (p26) explicitly lets the PLAYER choose the order; we don't model that choice. Ours is one of the two legal orders, and is exactly the branch the compendium's worked Example 1 walks through (Inn shuffles itself in, Watchtower then loses track). |
| A3 | Two of the player's **own triggers** firing simultaneously | Registration order wins — and because `effects.py` merges modules in `_MODULES` order with the newest last, the newest set's `self` trigger always resolves first. | Same p26 player's-choice rule as A2. Concretely: gaining a Trail or Berserker while holding a Watchtower always self-plays first, never the reverse. |

**B. Deliberate simplifications — the rules are clear, we do something simpler**

| # | Rule | What we do | Cost |
|---|---|---|---|
| B1 | **Scheme** triggers "when you discard it from play" | A per-play `buy_phase_end` watcher (the pre-2016 "choose at the start of Clean-up" timing) | The compendium says the two have "no practical difference", and in today's pool `buy_phase_end` genuinely coincides. It diverges only if a card discards an Action from play mid-turn, or a Cavalry/Villa-class card returns you to your Action phase (which makes end-of-buy fire more than once). Neither exists yet. Root cause is `_end_turn` not being interruptible — see the ledger in EXPANSIONS.md. |
| B2 | Deck and discard **counts** are owner-only officially | Shown to everyone | A digital-port convenience, consistent with showing live VP. Recorded in the original plan §6. |
| B3 | A **cost read for a "remodel"** should be read at the moment it is used | Develop / Farmland / Trader capture the trashed card's cost **before** the trash resolves | Only observable if trashing a card can change costs mid-resolution; nothing in the 139-card pool does. Revisit when a cost-changing on-trash card lands. |

**C. Settled — do NOT relitigate** (kept because each cost real time to establish)

- **Off-turn bonuses EVAPORATE**, they are not banked: "on another player's turn you always start
  with empty pools" (compendium pp. 48–49, which names Nomads and Trail explicitly). Independently
  confirmed by the phase-3 audit.
- **"Cheaper" is STRICT** (`cost_lt`), not "up to" — Border Village, Berserker, Haggler.
- **First discard, THEN put cards back** — see `discard_then_putback`. Four cards had this
  backwards; it is not a matter of taste.
- **Highway is turn-scoped** (`turn_ctx["bridges"]`), not while-in-play. The 1E card was the
  other way; the roadmap described the 1E card for a while.
- **A card name is not a card COPY.** Zones hold names, so a seat can have a Duration finishing at
  this clean-up AND a fresh copy of the same Duration just played; only the count separates them.
  `topdeck_from_play` matched `in_play` by name and took the wrong one, stranding the persisting
  copy — `_end_turn`'s kept-out removal then raised `ValueError` and the game was unplayable
  (~1.5% of random-bot games on a Scheme + Tide Pools kingdom, found by bot replay, fixed
  2026-07-31). Both readers now go through `_in_play_leaving`, a MULTISET subtraction. Any new
  code that picks a card off the table owes the same treatment.

## Hidden information / wire view

`player_view` BUILDS the view (build-not-filter): deck order never exists on the wire (counts
only — showing deck/discard counts to everyone is a documented convenience; officially they're
not open info), hands only to their owner, discard = top + count, `aside` = count, raw `pending`
replaced by `pending_view` (actor: kind+card+constraint; others: card + waiting_on), log entries
honor `private_to`, `rng_state`/`seed` popped. Seaside zones: `duration_view` (card+riders,
public — fx/data stripped), `island` public, `dur_aside`/`village_mat` owner-only with public
counts, watchers shipped as identity-only (event/owner/card; data may hold hidden resume info),
`dur_setup` never ships. Everything reveals at game over.

**The log is VERBOSE by design** (the Dominion-online look): every `draw` entry carries the
drawn card NAMES — per-field redacted to the owner until game over (count `n` stays public);
`discard`/`trash`/`reveal` log names publicly (faithful — those cards land face-up at the
table); `add_*` emit public `plus` lines; treasure `play` entries carry `coins`; entries logged
inside a card's resolution carry `d` (depth 1–3, set around every effect/stage dispatch,
always 0 at rest) which the client renders as indentation. The client folds the adjacent
`buy`+`gain` pair into one "buys and gains" line. Live VP totals
(`game["vp"]`) are public by product decision.

## Replay discipline (replay.py is a follow-up; the discipline is NOT)

`seed` persists; every random event (kingdom pick, deals, every shuffle) round-trips
`_make_rng`/`_save_rng` and logs an engine record; same seed + same moves ⇒ byte-identical game
(pinned by `test_soak.py::test_soak_determinism_same_seed_same_game`).

## Room server (main.py)

Structural mirror of Duel's (per-recipient `broadcast_state`, WS seat binding, single-thread DB
write executor, SELECT-then-DELETE) with the three Dontminion differences: 2–4 players
(`dontminion_games` has player1..player4 columns), validated create-time options (`expansions` /
`max_players` / `num_bots` / `ai_difficulty`, kept in sync across create → save blob → load →
`mk_room_state` — extend ALL FOUR when adding one), and MULTIPLE bot seats: `room["ai_players"]`
is a list (`bot1..bot3`, names "Bot N", NO meta entry ⇒ unjoinable), and `_schedule_bots` is a
single-flighted finisher loop that recomputes `_bot_to_act` EVERY iteration — that is what drains
chained decisions across different bots and lets bots answer a human's Militia mid-human-turn.
The scheduler passes the room's persisted `ai_difficulty` into `bot.choose`, which dispatches on
it — both tiers are O(legal moves), so there is still no executor and nothing heavy under
ROOM_LOCK. An unknown tier coerces to the default, so the ladder grows without a migration. All
entropy runs through `_new_rng()` (the test seam). vs-AI rooms start at create (never "open");
friend rooms are host-started with shuffled seat order.

## The bots (`bot.py`)

Two strategies, selected by `ai_difficulty`. **easy/normal/hard are all still the same
random-legal bot** — the frontend's picker therefore offers exactly two entries ("Random" =
`easy`, "Big Money" = `bigmoney`, the default) rather than pretending to three tiers.

**Big Money** is the classic buy ladder: Treasure and Victory only, greening on a Province-count
clock. It is a real opponent — 238/238 against random-legal across both seats and all five
expansions (median 30 turns). Three things about it are load-bearing:
- **`choose` is stateless** — the scheduler re-enters it per move, so the ladder re-reads the
  CURRENT coins every call. That is sound *because* there is exactly one buy a turn: the bot buys
  no Action, so nothing in its deck ever grants a second buy and no rung needs to plan a
  follow-up. Don't add a rung that wants two buys without giving the bot turn-scoped memory.
- **All treasures go down before the ladder is read** — a buy decided mid-treasure reads the
  wrong rung.
- **Deliberate gaps, both faithful to the ladder as specified**: Colony/Platinum are not in it
  (in a Prosperity colony game it still buys Province at $10-12), and it plays no Actions at all —
  it never buys one, so it only holds one an opponent handed it (Masquerade/Jester/Swindler), and
  a random play of an unknown Action is as likely to hurt as help.

`engine.owned_cards(game, pid)` (the scoring census, made public for this) is what the $8
"really early" exception counts Golds and Silvers with — every zone, so a Silver in play or on a
mat still counts.

## Frontend (Dontminion.jsx)

Peer contract `{myId, authUser, onExit}`; root class `.dm` on every branch (the screens.mjs
marker). Because engine constraints are generic, the decision UI is SIX renderers over
`game.pending_view` — no per-card frontend code anywhere; everyone else gets a
"Waiting for <name>" bar. Cards are text-only faces (no art) on the shared `.card` frame via
`--card-w/--card-h`; in-play cards use ONE size for both your box and the opponents' (56px), so
a played card doesn't change size depending on who played it. Supply affordance mirrors
`engine.cost` via `turn_ctx.bridges` — display only, the server stays authoritative.

**Reading a card is its own gesture: right-click, or press-and-hold on touch.** A plain click is
always the card's PRIMARY action (play / buy / pick), and the card you most want to read is the
one whose click is already taken — so info can't be the click. `useCardInfoGesture` handles both:
`contextmenu` (which Android also fires on a long press) and, because iOS Safari does NOT fire it
and runs its own selection callout instead, a real 450ms timer on touch pointers with a 10px
slop so a scroll isn't a hold. Both paths share one `fired` flag, so whichever wins the other
no-ops and the release is swallowed — holding a card can never also play it. The face sets
`-webkit-touch-callout: none` + `user-select: none` or iOS answers the hold first. **Every
`DmCardFace` needs an `onInfo` that is PURE info** — the supply's used to be `pileClick`, which
buys when the pile is affordable. `screens.mjs` pins all three behaviours (right-click opens
without buying, hold opens without buying, a short tap still buys and opens nothing).

**The card face has ONE inset token, `--cf-pad`** (on `.dm-card`, used by the name, rules text
and foot). The face also zeroes the shared `.card` frame's own padding — the two stacked, so the
real buffer was 12px per side, a fifth of a 56px card's width. Three things follow and all three
are pinned by `screens.mjs`:
- **All four insets must stay equal.** `FitText` measured `clientWidth`, which is the PADDING
  box, so a name it had to shrink grew into (and past) its own right inset — the title sat
  visibly closer to the right edge than the left. It fits to the CONTENT box now.
- **The foot must fit `[types][coin]` on ONE row at 56px**, which is what `--cf-pad: 4px` plus a
  13px coin floor and a 2px gap buy: the widest label we ship ("Duration") measures 29.4px
  against 31px available. `flex-wrap` stays on the foot as the net — if a future set's type word
  is longer, the coin wraps under rather than overlapping. **That 1.6px is the budget any type
  font increase spends.** The name and type scales carry a deliberate +15% (`.12075`/`16.1px`
  and `.0782`/`12.65px`), but the type FLOOR stays 5.5px: at 56px the scale term lands on 5.69px
  and the floor never binds, so raising it would buy nothing and cost the fit. Above ~70px card
  height the full +15% applies. The title can be raised freely — FitText shrinks any name that
  needs it, so a bigger base only helps names that already fit.
- **The pile-count pill straddles the card's bottom edge**, so tightening the foot walked the
  type label straight under it (7px of overlap on every supply pile). Any further change to the
  foot inset has to re-check the pill.

**Kingdom REQUIREMENTS ("Require: +2 Actions / +1 Buy / +2 Cards")** — create-time options that
guarantee the dealt 10 contains at least one card giving each checked bonus.
- **The pools are DERIVED from card text** (`cards.REQUIREMENTS` + `grants`), like `KINGDOM` is
  derived from the `expansion` flag — a new set's villages and smithies join the day it ships. The
  bar is the **printed** bonus, which deliberately excludes variable/draw-to-X cards (Cellar,
  Library) and multipliers (Throne Room): being narrow only ever adds a card the player asked for,
  being broad would let the guarantee be satisfied by a card that doesn't satisfy it.
- **`deal_kingdom` with nothing required is EXACTLY `rng.sample(pool, 10)`** — same rng call
  sequence, so every existing seed still deals the same board (the determinism soak and every
  forced-kingdom test rest on that). Requirements are honoured in `REQUIREMENT_ORDER`, never the
  order the client sent them, so the deal stays reproducible from (seed, options); a card already
  picked that covers a second requirement doesn't spend another slot.
- Every expansion **alone** can satisfy all three (pinned by a test), so the option can't produce
  an unsatisfiable create. `new_game` raises if a pool ever can't, rather than dealing a board that
  quietly breaks the promise.
- `requires` is a create-time option like the others: extend **all four** of create / save blob /
  load / `mk_room_state` — `test_kingdom_requirements_reach_the_deal_and_survive_the_blob` captures
  the REAL blob (inline write executor) rather than rebuilding one, so a `save_game` that forgot the
  key fails instead of passing.

**Platinum/Colony follow the official randomizer rule and need no option**: they join the Supply
with probability equal to the Prosperity PROPORTION of the dealt 10, so a kingdom with none of the
set is never a Colony game, and it is always both piles or neither
(`test_colony_only_ever_appears_with_a_prosperity_kingdom_card`).

**The create modal's expansion picker is a game-local `DmChecks`** (the shared kit has no
multi-select; promote it if a second game needs one). It defaults to **Base Set alone**, and the
LIST scrolls inside its own cap rather than the modal growing — the set count rises every phase,
and the failure mode is Create sliding below the fold. **That cap is a BUDGET: `.cm-panel` is
`max-height:88vh` = 633px on a 720px laptop, so adding a row means MEASURING the panel there, not
guessing.** The Require row cost 60px and Bot style another 56; the 148px cap survived only because
Bots and Bot style were put side by side. Both side-by-side rows are selected as `.cm-row.dm-cm-two`
/ `.cm-row.dm-req-row` — a bare `.dm-cm-two` has EQUAL specificity to the shared kit's
`.cm-row{flex-direction:column}` and silently loses on source order, which left them stacked (119px
instead of 56px) and looked like the flex rule simply not working. Select all toggles both ways, so **empty
is reachable**: Create is disabled for it (the server rejects an empty expansion set and the
error would be opaque). `screens.mjs` pins all three; verified non-vacuous by regressing the
default and watching it fail.

**Prompt-button labels wrap to a SECOND row rather than clipping** (`FitLabel`): one line if it
fits, otherwise the label wraps and the button grows, shrinking the type only as far as two rows
actually need. Minion's "discard your hand, +4 Cards…" option forced this — no font size fits it
on one row of a prompt button, so the old shrink-only version clipped it.

## Tests

**`test_wire_contract.py` guards the server↔client seam** — it reads `Dontminion.jsx` and asserts
every `game.X` / `seat.X` / `catalog.X` field it consumes is actually shipped by `player_view` /
`/catalog`. Both frontend bugs found in live play were drift here, and NEITHER suite sees it: the
Python tests never render, and `npm run screens` mounts the route without playing a game. It is a
NAME check only — it proves the server still sends a field, not that the client uses it right —
but that is precisely how both bugs failed. Verified against both by simulating each regression.
Keep its allowlists short; a growing allowlist means the check is being worked around.

**NO CONDITIONAL SKIPS — the suite has zero, keep it there.** A test that can't reach the state
it means to test has to FAIL, not opt out: `test_vassal_duration_full_cycle_forced_yes` guessed
its option id and `pytest.skip`'d when the Caravan didn't reach play, so every regression in that
path was a green tick — and it swallowed a real `duration_in_play` breakage during the Scheme
fix. Pin the frame's option ids and pick by name. Same for a sampled choice: assert BOTH branches
(`test_vassal_plays_a_duration_off_the_deck_and_it_persists` asserted only the "play" branch, so a
Vassal that played nothing passed). And derive parametrize counts from the data
(`range(len(_chunks()))`) — the hardcoded `range(13)` + skip only guarded the roster shrinking, so
the next expansion's kingdoms would have gone unsoaked in silence.

`test_engine.py` (kernel + exemplars + redaction), `test_soak.py` (per-move card-conservation
census over full random games — the Duel 25-token analog — plus never-strand, mirror-sync, vp
recompute, JSON-safety, per-move progress, termination, determinism), `test_cards.py` (WP1
data), per-batch `test_cards_*.py`, `test_migrate.py` (every historical save shape),
`test_server.py`/`test_ws_auth.py`/`test_view_wire.py` (WP5). Any test module driving the WS
loop MUST reset `core.rooms._ws_connect_limiter` per test (repo rule).
