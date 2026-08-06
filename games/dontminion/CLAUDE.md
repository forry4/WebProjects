# Dontminion (Dominion: Base + Intrigue + Seaside + Prosperity + Hinterlands + Cornucopia & Guilds (all 2E) + Alchemy + Dark Ages + Adventures + Empires + Renaissance + Menagerie)

2–4 players, 368 cards + 114 LANDSCAPE cards (53 Events, 21 Landmarks, 20 Projects, 20 Ways) + 5 Artifacts. Mounted at `/dontminion`. Plan + full domain spec:
`.claude-plans/i-want-to-add-luminous-pebble.md`; the FULL-CATALOG expansion roadmap (all 16
sets, phased by kernel mechanic) is `EXPANSIONS.md`. Rules source of truth: the Knutsen
compendium `C:\Users\Forrest\Downloads\Dominion_CompleteRules_v11.1.pdf` (ch. VII = per-card
rulings); card texts cross-checked against dominionstrategy.com/card-lists/.

## Layout

| File | Role |
|---|---|
| `cards.py` | static data ONLY (schema below): `CARDS`, `PILES`, `LANDSCAPES`; `DATA_COMPLETE` sentinel; `BANDIT_VICTIM_CHOOSES` ruling |
| `engine.py` | the kernel: rules, frames, attack window, validation, scoring, `player_view` |
| `effects_base.py`, `effects_intrigue.py`, `effects_seaside.py`, `effects_prosperity.py`, `effects_hinterlands.py`, `effects_cornucopia.py`, `effects_alchemy.py`, `effects_darkages.py`, `effects_adventures.py` | ONE module per expansion, each owning a disjoint card set |
| `effects.py` | merges the registries; duplicate registration raises |
| `bot.py` | the bots: random-legal (easy/normal/hard) + `bmplus`, the only shipped opponent; the Big Money ladder stays as the arena's reference rung |
| `main.py` | FastAPI sub-app: rooms/WS/persistence/multi-bot scheduler |
| `tests/` | engine, soak, per-batch card tests, cross-set, migrate, server, ws-auth, wire-redaction, wire-contract |
| `tools/replay_prod_saves.py` | THE migration gate — replays every real prod save (see below) |

**Card batches are still written in two halves per expansion** (a simple half and a
mechanically complex half) by two parallel agents that may touch only files they own — the
halves are CONCATENATED into the one module when the phase lands. The `tests/test_cards_<set>_a/b.py`
files stay split: each half's fixtures (`fresh`/`give_hand`/`decide`) differ, so merging them
would silently let one definition win and change what the other half's tests exercise.

## Save-shape versioning (`SCHEMA` + `migrate`) — READ BEFORE ADDING A GAME-DICT KEY

`engine.SCHEMA` (now **14**: 1 = Base+Intrigue, 2 = Seaside, 3 = Prosperity, 4 = card renames,
5 = Hinterlands, 6 = the pile model, 7 = Cornucopia & Guilds, 8 = Alchemy, 9 = Dark Ages,
10 = the landscape kernel, 11 = the Debt vector, 12 = Empires, 13 = Renaissance,
14 = Menagerie — the last four are all FILL-ONLY bumps: v11 `game["debt"]`,
v12 `seat["cleanup_return"]`, v13 `villagers`/`artifacts`/`fleet`, v14
`seat["exile"]` + `game["last_turn_trashes"]`/`game["mouse_card"]`)
is the game-dict shape version,
stamped by `new_game`. `engine.migrate(game)` upgrades any older persisted blob
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

**At-rest compaction (`persist.py`).** Dontminion has the BIGGEST rows in the DB (~15–20 KB stored
vs CoC ~9.5 KB, Spender ~0.7 KB), so it is worth knowing exactly what is in them. `rng_state` is
packed to base64 via `core.rooms.pack_rng` — **-8.1% stored** (mean of 6 played-out games, 2p/base
through 4p/4-expansion). `_encode_state`/`_decode_state` in `main.py` are the only codec sites and
every read must funnel through them — including `tools/replay_prod_saves.py`, which calls
`expand_state` explicitly (a packed `rng_state` reaching `engine._load_rng` would hand it a base64
blob where it wants 625 ints). **Every `undo_stack` snapshot carries its own `rng_state` and must be
packed too** — up to `_UNDO_CAP` (30) of them mid-turn; packing some and not others breaks zlib's
dedup and can make the row bigger than doing nothing (measured +49.5% on Duel).

**The LOG is deliberately left uncompacted, and this is measured, not an oversight.** It is 58–67%
of the row (1,426 entries on a played-out 2p game) and looks like the obvious target, but it is
enormously repetitive and zlib already collapses it: encoding every card name to a table index took
raw 104,863 → 93,436 and STORED only 20,042 → 19,474, i.e. **-2.8%** for a rewrite of the most-read
structure in the game. What survives zlib is the log's actual information content — the only way to
shrink it further is to log less, which is a product decision about replay and scrollback. The same
measurement was run on CoC's and Duel's logs with the same verdict; don't relitigate it per game.

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

**Moves** now also include `spend` (ph. 4) and `buy_landscape` (ph. 6H).

**Engine API**: `new_game(player_ids, expansions, seed=None, names=None, kingdom=None,
requires=None, landscapes=None)` (players
arrive in seat order — the SERVER shuffles; `kingdom` overrides the random 10 and `landscapes`
the dealt Events/Projects: the forced-board
test seams) · `apply_move(game,pid,move)->(ok,err)` (gate order: over → pending → turn → handler;
then `_drive` → `_post_move`) · `legal_moves` (never empty for the actor; complete iff ≤200) ·
`sample_decision(game,pid,rng)` (uniform valid payload; caller's rng, never the game's) ·
`is_over`/`winners`/`score_game` · `player_view` · `cost(game,card)` (base − bridges, min 0 — THE
only cost function; never read `CARDS[c]["cost"]` for a comparison).

**Kernel helpers for card code** (game mutations go ONLY through these + the `push_*` family):
`draw(game,pid,n)` · `look_top(game,pid,n)` (→ seat `aside`; excluded from mid-look shuffles) ·
`gain(game,pid,card,dest="discard"|"hand"|"deck",**extra)->bool` (False on empty pile — "gain
nothing"; `**extra` rides the gain EVENT, for a card marking a gain it caused — Port) ·
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
`take_seat_token` / `flip_journey` / `play_set_aside` / `take_from_pile_aside` /
`request_extra_turn(game,pid,source=,no_buy=)` / `estate_token_card` (ph. 7) ·
`to_tavern(game,pid,card,zone="in_play")` / `call_card(game,pid,card)` /
`discard_from_tavern` / `on_tavern` (ph. 6H — calling is NOT playing, see Kernel v6H) ·
`move_token(game,pid,kind,pile)` / `pile_tokens` / `token_pile` / `seat_token` /
`set_seat_token` (ph. 6H) · `landscape_cost` / `landscape_gate` (ph. 6H — THE readers) ·
`add_debt(game,pid,n)` / `debt_cost` / `debt_blocks_buying` · `add_landscape_vp` /
`take_landscape_vp` / `landscape_vp` · `add_pile_vp` / `take_pile_vp` / `pile_vp` /
`add_pile_debt` / `take_pile_debt` / `pile_debt` · `landscape_scoring` (ph. 7H) ·
`attack_opponents(game,pid,card,per_opp_stage,data=None,immune=None)` (a card whose attack part
runs in a LATER stage — Minion, Replace — must capture `list(game["_atk_immune"])` into its frame
data during on_play and pass it back via `immune=`) · `_log(game,pid,event,
private_to=None,**kw)`. Turn counters (`game["turn_ctx"]["bridges"/"merchants"]`) are incremented
directly by the owning card's effect.

**THE PILE MODEL (phase 3H) — read before touching the Supply.** `supply = {name: count}` could
only ever say "N copies of the card this pile is named after". A pile is a real object now, but
its COUNT deliberately stays in a flat `{name: count}` index, because that is the shape ~60 read
sites across five effects modules, both bots, the client and ~110 test fixtures already speak.
- **Two count indexes, identical in shape.** `game["supply"]` — the BUYABLE piles, **untouched by
  this phase**: still hand-writable, so `g["supply"]["Curse"] = 0` in a fixture is still exactly
  right. `game["nonsupply"]` — piles outside the Supply (Rewards ph. 4, Spoils/Madman/Mercenary
  ph. 6, Horses ph. 10, Spirits ph. 11, Loot ph. 13): never buyable, never counted for the
  three-empty-piles end.
- **`game["piles"][name]`** = `{supply, face, contents|None, members, attach}`. `face` is the card
  whose cost/types the pile SHOWS (itself for an ordinary pile, the top card for an ordered one,
  and it is RETAINED when the pile empties so `cost()`/`types_of()` stay total). `contents` is the
  ordered list, top first — Ruins/Knights ph. 6, split piles + Castles ph. 8, rotating ph. 12.
  `members` is every card the pile can hold, which is how a RETURNED card finds its way home once
  `contents` is empty. `attach` is per-pile public state (Adventures tokens ph. 7, gathered VP
  ph. 8, Traits ph. 13).
- **EXACTLY ONE AUTHORITY PER COUNT.** An ordinary pile's count is its index entry; an ORDERED
  pile's is `len(contents)`, and for those the index is a MIRROR written only by
  `_pile_take`/`_pile_return` and never read by `pile_count`. Putting the count on the pile object
  instead would have made every existing `g["supply"][x] = 0` a silent desync — in fixtures today
  and in every future card batch. `test_soak._assert_piles_agree` asserts the mirror per move.
- **API**: `pile_count` (THE count reader) · `pile_top(game,name)` (the card a gain/buy yields,
  None if empty) · `pile_face` (total, even when empty) · `pile_of(game,card)` · `is_supply_pile` ·
  `supply_piles` · `pile_cards(game)` (the CENSUS — a pile's NAME is not a card) ·
  `add_pile(game,name,count=|contents=,supply=False,members=)` (setup only; refuses a duplicate,
  an empty ordered pile, or a face that is not a real card) · `gain_from(game,pid,pile,dest=)` ·
  `return_to_pile(game,pid,card,zone=)` · `pile_attach`/`pile_attachment`.
- **`gain`, `cost`, `types_of`, `coins_of` and `_h_buy` all take a PILE name** and resolve it
  through the face. You buy a pile and get its top card: the `gain`/`buy` events, the log and the
  gained-card zone all carry the REAL card, never the pile name.
- **Non-supply piles are kept OUT of `game["supply"]` rather than flagged inside it**, deliberately:
  every "piles costing up to $4" enumeration in card code reads that dict, so "gain a card from
  the Supply" excludes a Spoils by construction, in every module, with no call site to remember.
- **Wire**: `piles` ships as `{count, supply, face, ordered, attach}` — never `contents` (an
  ordered pile's order below the top is hidden information) and never `members`. `supply` and
  `costs` ship unchanged; `costs` now prices every pile, including the unbuyable ones.
- **The bots read the Supply too.** `bot_traits.pile_traits(game, pile)` is THE bot-side face
  resolution — `traits()` is a pure function of a CARD and KeyErrors on a pile name. Anything
  starting from a Supply key goes through it (`bot_endgame` does); `best_bm_terminal` skips a
  pile that isn't a card, since a face that changes is nobody's reliable terminal.
- 3H ships no card that uses any of this. `tests/test_piles.py` drives every seam end to end
  (buy, gain, the trigger bus, the game end, redaction, census, migration, all three bot tiers)
  and `test_soak_a_board_carrying_every_kind_of_pile` plays full random games on a board holding
  both shapes under the conservation census.

**Kernel v10 — the phase-10 (Menagerie) delta. FROZEN — card batches build against this.**
**SCHEMA 14**, a fill-only bump for one seat zone (`exile`) and two game keys
(`last_turn_trashes`, `mouse_card`). Twelve items, each with a consumer in this set:

- **EXILE — a new per-seat PUBLIC zone, and the first zone that is OWNED but sits outside
  the gain/discard economy IN ONE DIRECTION ONLY.** `exile(game, pid, cards, zone="hand"|
  "supply")` / `discard_from_exile` / `on_exile(game, pid, card)` (THE "do I have a copy
  there" reader). Exiled cards SCORE, so the mat joins `owned_cards` **and both
  conservation censuses** — `engine.owned_cards` and `test_soak._census` are the same claim
  asked from opposite ends, and a zone missing from either goes unseen. Coming IN is not a
  gain ("Exiling cards from the Supply is not considered gaining cards" — the `exchange`
  discipline, since a gain emit here would fire every when-gain watcher in the game for a
  card nobody gained); going OUT to the discard **is** a discard for triggers ("when you
  discard cards from your Exile mat, when-discard abilities such as Faithful Hound, Trail,
  Tunnel, Village Green and Weaver trigger"), which is why that direction routes through
  `discard()`. A new `exile` emit rides the move (Invest reads it). `gain(..., dest="exile")`
  lands a gain straight on the mat.
- **THE MAT'S OWN ABILITY IS A KERNEL POOL CONTRIBUTOR** (`_collect_exile_abilities`), the
  ph.-7 token shape a second time: a mat is not a card, a landscape or an artifact, so it can
  have no `TRIGGERS` entry — but "when you gain a card, you may discard any number of copies
  of it from your Exile mat" is CONCURRENT with everything else the gain triggered (ch. VI
  lists it beside Watchtower, Sheepdog and Sleigh), so it must arrive through the POOL rather
  than inline. It is a **yes/no, never a `choose_cards`**: "you can't choose to just discard
  some of them". Gated on a copy actually being on the mat, so an ordinary board pays one
  list lookup.
- **`add_cards(game, n, pid=None, final=False)` — THE PRINTED "+N CARDS" PRIMITIVE, and the
  riskiest item in the set.** Card code had always called `draw()` for three different printed
  things — "+3 Cards" (Smithy), "draw 2 cards" and "draw until you have 6" — and **Way of the
  Chameleon changes exactly one of them** ("only card drawing denoted with '+' is changed to
  +$. For instance 'draw 2 cards' is unchanged"). Nothing at the call site could tell them
  apart, so all 145 printed-plus sites were migrated and the line is held at AST level by
  `test_every_plus_cards_grant_uses_add_cards`, with an explicit 16-entry allowlist carrying
  each genuine non-"+" draw's printed wording. Without it the next set's Smithy silently opts
  out of the Chameleon and nothing fails. `final=True` composes with ph. 9's `final_draw`
  (the Star Chart pick) and **the order matters: a SWAPPED +Cards draws nothing at all**, so
  it can cause no shuffle and needs no pick. Off-turn it still draws — drawing is not a
  per-turn POOL — which is why it does not go through `_grant`; the swap binds the turn
  player only, since a swapped +Cards becomes +$ and $ off-turn evaporates by rule. Both seat
  tokens apply to the RESULT of a swap, so their handling is duplicated in `add_cards`
  deliberately rather than skipped.
- **WAYS — `push_way_offer(game, pid, way, card, stage)`, and NO NEW MOVE.** Ph. 8 built the
  `would_resolve` window for Enchantress and the compendium puts Ways in that exact class
  ("Ways are triggered at the same time as Enchantress, replacing what you do"), so a Way is
  a `TRIGGERS` entry with `{"on":"would_resolve","from":"landscape"}` whose stage offers a
  two-option prompt. It is a window, not a `legal_moves` entry, because it has to be ordered
  in the ability pool against whatever else that occurrence collected — the 6H `call`
  finding again. Picking the Way calls `cancel_pending_play` and runs the Way's stage; the
  card **still counts as PLAYED** (in play, `actions_played` bumped, `action_resolved` still
  fires). **A DECISION ON EVERY ACTION PLAY IS THIS SET'S PRODUCT COST, and it is the rule.**
  Ways are not in `BUYABLE_LANDSCAPE_KINDS`, so their `cost` field is inert. Six of the twenty
  ("this" — Butterfly, Chameleon, Frog, Horse, Rat, Turtle) mean **the played Action card,
  not the Way** (ch. IV WAYS).
- **KILN — `before_play` widened to a card of ANY TYPE** (`_before_play_then_treasure` +
  `_k_play_treasure_rest`). "The next time you play a card this turn" is not just an Action,
  so an ordinary Treasure play needs the window — and it needs the same CONDITIONAL parking
  as 6H's Action version, for the same reason: the coins and the card's own ability run
  INLINE, so a pool parked in front of them would resolve after them, i.e. backwards. A board
  without a Kiln is byte-identical to before.
- **WAYFARER — `effects.COST_OVERRIDE[card] = fn(game) -> {coins,potions,debt} | None`, an
  ABSOLUTE cost, not a reduction.** `DYN_COSTS` subtracts inside `cost()`, which serves
  Destrier and Fisherman exactly — but "if Wayfarer is copying the cost of another card, only
  cost reduction ON THAT CARD applies (which Wayfarer would copy), not cost reduction on
  Wayfarer itself", so it bypasses `bridges`, Canal, Quarry, the −$2 Ferry token and every
  `COST_MODS` entry. It is a **VECTOR** ("Wayfarer can have a cost with Potion or Debt in
  it"), consulted at the top of all three readers, and **recursion-guarded**: Wayfarer copying
  a Destrier asks `cost()` again, and the re-entry flag makes an override that asks about
  itself fall through to the printed path rather than loop.
- **ANIMAL FAIR — `effects.BUY_PAY_ALT[card] = {"avail", "label", "stage"}`, an escape inside
  the AFFORDABILITY CHECK ITSELF.** "You are allowed to choose Animal Fair even without having
  $7, as long as you have an Action card in hand. You may choose to either pay its cost (if
  you have $7) or trash an Action card from your hand. (You always use 1 Buy.)" `buy_pay_alt`
  is THE reader, consulted by `_h_buy` AND `legal_moves` — an enumerator and a handler that
  disagree hand the bot a move that does nothing (the `play_all_treasures` livelock). The
  stage runs BEFORE the gain: "if you buy it by trashing a card, the trashing happens before
  any when-buy abilities."
- **SNOWY VILLAGE — `turn_ctx["ignore_actions"]`.** "Ignore any further +Actions you get this
  turn" — the grant is DROPPED inside `add_actions`, not zeroed later, so a Village played
  afterwards gives nothing, and it is LOGGED (`actions_ignored`) rather than silent. **Ph. 9's
  Villagers obey it for free**, because spending one is "+1 Action" and routes through the
  same function — the payoff for that routing decision, one phase later.
- **GOATHERD — `game["last_turn_trashes"]`, `turn_ctx["trashes"]`'s twin of
  `last_turn_gains`.** A COUNT, because that is all the card asks ("+1 Card per card the
  player to your right trashed on their last turn"), and counted for the TURN PLAYER's turn
  regardless of who did the trashing — that is whose turn it was.
- **MASTERMIND — `link_duration(game, pid, card, handle)`.** "Mastermind stays in play as
  long as that Duration stays in play": a rider like `mark_duration_rider`, but attached from
  a LATER WINDOW (a start-of-turn stage, a whole turn after its own entry was created), which
  is exactly what ph. 9's `duration_handle` exists for. **TRANSITIVE**, and the entry it
  chases is the LINKING CARD'S OWN (`other["card"] == card`), never one the card merely rides
  — a Throne Room and a Mastermind can both ride one Caravan without the Throne Room belonging
  to the Mastermind. It **MOVES** the riders rather than copying them: a rider recorded on two
  live entries is one physical card counted twice by the conservation census, and both
  entries promote at Clean-up.
- **WAY OF THE MOUSE — `play_mouse_card` + `game["mouse_card"]`.** The third member of ch.
  VI's PLAY A CARD WHILE LEAVING IT family, and it needed its own wrapper because neither
  sibling fits: `play_from_supply` (5H) wants a Supply pile and `play_set_aside` (ph. 7) wants
  a card in a SEAT's zone, while the Mouse card is a single game-level card belonging to
  nobody. Chosen at setup from the kingdom cards this game did NOT deal (the Bane/Ferryman
  shape) and **non-Duration** — the 2025 errata, which ch. I's own setup paragraph was never
  updated for; the card and ch. VII win. It is **not a pile** ("isn't a pile. No VP tokens
  will accumulate if the card is Farmers' Market").
- **THE HORSE PILE — 30 cards, OUTSIDE the Supply**, so it is never buyable and never counts
  toward the three-empty-piles end, both free from ph. 3H's non-Supply index. ⚠ **"If any
  cards referring to Horses are used" means EVERY CARD IN THE GAME, not just the Supply**:
  four Events (Bargain, Demand, Ride, Stampede) gain Horses with no kingdom producer needed,
  and Sleigh ($2) and Scrap ($3) are both eligible **Mouse cards**. `cards.uses_horses` reads
  CARDS *or* LANDSCAPES, and the Mouse pick moved ABOVE the Horse clause in `new_game` so it
  can be consulted. Reading the Supply alone left all three shapes gaining from a pile that
  was never built.
- **Wire**: every seat's `exile` is PUBLIC and ships as-is — ch. II lists "all cards you have
  set aside face up (including on any player mats)" as open information, and the Exile mat is
  face up. Everything above is contract-tested in `tests/test_menagerie_kernel.py` (62)
  against synthetic Ways, Projects and an invented Horse card.

⚠ **ADDING 40 LANDSCAPES RE-DEALS EVERY EXISTING SEED'S LANDSCAPES.** `deal_landscapes`
simulates the randomizer mix literally, so pool SIZE is an input — the ph.-9 side effect
again. Expect forced-board soak churn on the data commit; the `_WAY_CAP` of 1 and
`_LANDSCAPE_CAP` of 2 have been in place since 6H and need no change.

**Kernel v9 — the phase-9 (Renaissance) delta. FROZEN — card batches build against this.**
**SCHEMA 13**, a fill-only bump for three game keys (`villagers`, `artifacts`, `fleet`).
7H's `_SPENDABLES` and 6H's landscape kernel took their promised consumers with no change;
eight items were still needed, each with a consumer in this set:

- **VILLAGERS — `add_villagers(game, n, pid=None)` + `game["villagers"]` + the
  `_SPENDABLES["villagers"]` entry.** Coffers' exact shape (a MAT, so an off-turn Villager is
  KEPT, never evaporated) with **a different TIMING, and this is the trap**: Coffers got the
  2022 "at any time during your turn" change and **Villagers did not** — "Villager tokens can
  be spent at any time in your ACTION PHASE. Each spent Villager gives you +1 Action". The
  phase gate lives in `avail`, so a Buy-phase ability offers no villager move at all while a
  mid-ability spend inside the Action phase stays legal. `_maybe_auto_buy` also had to learn
  them: a player out of Actions holding tokens AND an Action card can still act, so the phase
  must not advance from under them.
- **PROJECTS — ownership semantics on 6H's landscape kernel; `project_owned(game, name, pid)`
  is THE reader.** The cube IS `bought_by`, which `_h_buy_landscape` has written since 6H —
  no new store. `landscape_gate` grows two clauses *for the kind*, never as `once` data ("you
  can buy two Projects during the game, but not the same one twice"): already-has-a-cube, and
  the `_PROJECT_CUBES` (2) cap. **A project buy runs NO `LANDSCAPE_FX`** — that registry is an
  Event's one-shot buy ability; a Project's ability is ongoing and its consumers read
  `project_owned`.
- **`from:"landscape"` GREW OWNERSHIP SCOPING, and the recipient is not always the actor.**
  A landmark is unowned (unchanged: fires for the actor). A **project** filters to cube
  OWNERS via the spec's optional `recipients` key: `"owner-actor"` (default — Academy,
  Guildhall, Sewers, Innovation) or **`"owners-not-actor"`** (Road Network: "when ANOTHER
  player gains a Victory card, +1 Card" — every other owner draws, mid-resolution if need be).
  Each recipient's `when` is evaluated for THEM, and the ability lands in their own pool.
- **`from:"artifact"` — a new trigger source**, the ownership shape on `game["artifacts"]`
  (Treasure Chest on `buy_phase_start`, Horn on `cleanup_discard`, Key on `turn_start`).
  **ARTIFACTS get their own table** (`cards.ARTIFACTS`, `{by, expansion, text}`) — the 6H
  lesson a third time: one copy, never gained/bought/dealt, "never belong to any player and
  are never considered to be in play", so a `CARDS` entry would lie about cost and kingdom and
  a `LANDSCAPES` entry would deal it. `take_artifact` / `holds_artifact`; taking your own is a
  logged no-op; `new_game` keeps available exactly those whose `by` card is IN THE GAME (a
  Bane or Ferryman Border Guard counts). **Flag is NOT a general draw hook** — it is one clause
  on the Clean-up hand count ("as long as you have Flag, you draw one more card in Clean-up").
- **FLEET — the game-end restructure, and the reason `_end_turn` now has TWO parked stages.**
  `game["fleet"] = {"remaining": [...], "on_turn": bool}`, None until the end check trips with
  a cube on Fleet. Then: the roster is every owner in turn order **starting after the player
  who last had a regular turn**; queued extra turns still resolve first ("any extra turns
  already in queue will now be resolved"); fleet turns don't bump `turns_taken` ("not counted
  for tie-breaker"); and once the last one is played **the game is immediately over — no more
  extra turns, and it doesn't matter if the end conditions no longer hold**. Buying Fleet
  during the round grants nothing (the roster was fixed when the round began).
- **STAR CHART — `final_draw(game, pid, n)` is the new card-code helper, and the FROZEN RULE
  is: a draw that ENDS its ability calls `final_draw`, never `draw`.** The pick is a real
  decision, so it can only be offered where the rest of the caller can be parked. Full
  fidelity at the Clean-up hand draw and at `shuffle_into_deck` (Inn/Donate-class, which
  pushes the frame itself — so **anything that must happen after that shuffle goes in a
  continuation pushed BEFORE the call**; Donate was reshaped for exactly this). Anywhere else
  the shuffle is uniform and **logs `star_chart_skip`** — deviation **B9**, the lose-track
  discipline: a skipped ability must never be silent. The pick moves its card AFTER
  `rng.shuffle`, so entropy spend is identical picked, declined or skipped.
- **CANAL is a `cost()` clause, NOT a `COST_MODS` entry** — that seam is per-COPY while in
  play, and a Project is never in play and has no copies. Flat −$1 keyed on the TURN player
  owning the cube (the Ferry-token/Inheritance signature trick: "during your opponent's turn,
  costs are reduced if your OPPONENT has a cube on Canal, but not if only you have one").
- **CAPITALISM — a `types_of` injection, a play-surface routing, and the ledger's
  `autoplay_block` row arriving three phases early.** `cards.CAPITALISM_CARDS` is DERIVED from
  the text field over the WHOLE catalogue (an Action whose text contains a literal `"+$"` —
  "it doesn't change a card with just $ without the plus… it also changes Teacher") and pinned
  by an explicit-list test, the ph.-7 REVIEWED lesson. `types_of` adds `treasure` during the
  cube owner's turn, everywhere, reverting off-turn and at `over` (the **Keep** ruling — a
  shipped Empires landmark, so a real cross-set test). `capitalism_changed(game, card)` is THE
  reader: `_play_one_treasure` delegates such a card to **`play_action_card`** — attack window,
  before_play, would_resolve, duration setup, `actions_played`, all of it — while **spending no
  Action** ("this doesn't use an Action from your Action pool"), then emits `play_treasure`.
  And **`autoplay_treasures(game, pid)` replaces the static membership test** in
  `play_all_treasures`: it is THE reader for the handler, `legal_moves` AND `player_view`
  (shipped as `autoplay`, since a state-dependent rule can't live in `/catalog`), because a
  changed Militia must never be fired by the button.
- **`emit("reveal")` from `reveal()` — Patron's class, and the word is the whole rule.** A
  BATCH emit for the cards' OWNER (two revealed Patrons pool together). `reveal()` was already
  the single choke point, so this is one line — but the audit owes a sweep for any
  "reveal"-worded card that logs without calling it. Draws, looks and discards do NOT emit:
  "discarding or trashing a Patron does not count as revealing it, even though the other
  players can see it. Revealing your hand or discard pile DOES count."
- **`turn_ctx` grew four keys**: `played_actions` (Action NAMES in play order — Scepter's
  replay targets, and `[0]` is Citadel's first play, since "a card is considered played even
  before it's resolved") and the once-per-turn flags `citadel_used` / `innovation_used` /
  `horn_used`. Also **`buy_gains` now resets on `return_to_action_phase`** — it counts per BUY
  PHASE, not per turn, because Exploration checks "the Buy phase that just ended" and Merchant
  Guild counts the cards gained "in it", and Villa can give you two.
- **Landscape token store**: `add_landscape_tokens` / `take_landscape_tokens` /
  `landscape_tokens` on `st["tokens"] = {pid: n}` (Sinister Plot — "keep them on Sinister Plot
  next to your Project cube"; the take removes ALL of yours). Presence-based like 7H's VP
  store, so an untouched landscape ships no key.
- **Wire**: `villagers`, `artifacts`, `fleet` and each project's `bought_by` cube record are
  all PUBLIC and ship as-is (mat tokens are open information, an Artifact sits in front of its
  holder, the round roster is table state), plus `autoplay`. Everything is contract-tested in
  `tests/test_renaissance_kernel.py` (38) against synthetic projects and an invented artifact.

**Kernel v8 — the phase-8 (Empires) delta. FROZEN.** The set consumes 7H wholesale — Debt, the
scoring pipeline, `LANDSCAPE_SETUP`, the pile/landscape VP stores and `from:"landscape"` all
arrived with a consumer for the first time and needed **no change at all**. **SCHEMA 12**, a
fill-only bump for one seat zone. What the set DID need, six items, each with a consumer:

- **A PILE'S TYPE AND COST FOLLOW ITS RANDOMIZER, NOT ITS FACE** — `pile_types` /
  `pile_has_type`, reading a new `PILES[name]["types"]`. "Split piles instead follow the
  Randomizer card" (SPLIT PILES: PILE TYPE AND COST § IV), and three of the five Empires
  splits show a **Treasure** once the bottom half surfaces while the pile stays an **Action**
  pile: "you can put your +$1 token on the Catapult/Rocks pile, and then get +$1 when you play
  a Catapult OR A ROCKS". `types_of(pile)` still resolves through the FACE, which is the right
  answer for BUYING (a Fortune on top really does cost {$8,8D} and really is a Treasure) —
  these are two different questions and ph. 8 is where they stopped having the same answer.
  Everything that asks what KIND of pile something is moves onto the new reader: Defiled
  Shrine's and Obelisk's setup, `_action_supply_piles` (six Adventures Events). It also fixes
  **Knights**, which has been answering from its top card since ph. 6.
- **THE WOULD-RESOLVE WINDOW — `emit("would_resolve")` + `cancel_pending_play`.** Enchantress
  replaces what the played card does, and the compendium gives that its own timing class,
  strictly after before-play AND after reactions: "Enchantress is triggered when you WOULD
  RESOLVE the played Action card. So if you play an Enchanted Attack card, Reactions are
  resolved first, as normal. Good Harvest, Kiln, Urchin and Adventures tokens are also
  resolved first." Same park-only-when-a-consumer-is-collected shape as 6H's `before_play`, so
  a board without Enchantress is byte-identical; the parked half is `("__play","resolve")` and
  `cancel_pending_play` flags it, the twin of `cancel_pending_gain`. The card still counts as
  PLAYED — it is in play, `actions_played` is bumped, and the `action_resolved` emit parked
  under everything still fires ("after-play abilities such as Coin of the Realm, Royal Carriage
  or Citadel still trigger after you play an Enchanted Action card"). **This is the ph.-10 WAYS
  kernel arriving early** — "Ways are triggered at the same time as Enchantress, replacing what
  you do" — and `add_watcher` now takes a play-time event, since the Enchantress sits in the
  ATTACKER's play area while the actor is an opponent (neither `in_play` nor `self` can see
  that).
- **RETURNING TO THE ACTION PHASE MID-TURN — `return_to_action_phase`.** Villa. The phase had
  only ever advanced. "You return to your Action phase, keeping the Actions, Buys and $ you had
  left", and `turn_ctx["bought"]` clears with it, because that flag exists to stop Treasures
  being played after a buy and re-entering the Buy phase gives you its treasure half again.
  Own turn only ("if you gain Villa when it's not your turn, the +1 Action is not usable, and
  you don't get an Action phase").
- **A MULTI-TURN DURATION THAT ENDS ITSELF — `finish_duration`.** Archive's "now and at the
  start of your next TWO turns" is neither `add_duration_fx`'s one-shot nor ph. 7's
  rest-of-the-game `forever`: it rides `forever=True` to survive the turn start and its own
  stage ends it when the set-aside runs out ("Archive will only stay in play as long as it has
  cards set aside"). The three cards live in `dur_aside` for the census, but their NAMES are
  recorded per-fx so two Archives keep **separate sets** — zones hold names, so the flat zone
  alone would pool all six into one heap.
- **RETURN TO THE SUPPLY AT CLEAN-UP — `return_at_cleanup` + `seat["cleanup_return"]`.**
  Encampment. A separate zone from ph. 4's `cleanup_aside` because the DESTINATION differs, not
  the timing: that one goes to the owner's discard, this one leaves the deck entirely. Swept
  for EVERY seat, since "if you play Encampment during another player's turn and set it aside,
  you return it in THAT player's Clean-up phase". **The SCHEMA 12 key.**
- **`emit("buy_phase_start")` + `_enter_buy_phase`.** Arena. "At the start of your Buy phase" is
  a real timing point with TWO entrances — the player ending their Action phase and the
  kernel's auto-advance — so both had to route through one function or the event would fire on
  only one of them. It can now fire twice in a turn, which is correct: Arena's own entry names
  Villa among the cards that give you another Buy phase.
- **...and one correctness fix with no new API: `trash_from_supply(game, card, pid)` EMITS.**
  A card trashed out of the Supply really is trashed — its own on-trash ability fires and the
  trasher gets the benefit — and Tomb is explicit that it "triggers even when you trash a card
  from the Supply (with Gladiator, Lurker or Salt the Earth)". Lurker (ph. 1) shipped without
  it because nothing in the pool consumed a Supply trash until now; `pid` is optional so a
  fixture staging the trash pile keeps its silent behaviour.

**THE ERRATA ARE AGAIN THE STORY, and this set straddles THREE passes** (compendium ch. V).
Sixteen of ~70 objects differ from every card-list site and from both Empires rulebooks:
**2021** Farmers' Market, Mountain Pass, Opulent Castle, Temple; **2022** Charm, Forum,
Groundskeeper, Tax + the Landmarks Basilica, Colonnade, Defiled Shrine; **2025** Capital,
Chariot Race, Gladiator, Overlord, Ritual. Three things generalise:
- **The 2022 pass's condition is "in your Buy phase", not "when you buy"** — a Workshop gain in
  the Buy phase counts, a gain on an opponent's turn does not. Four triggers read it, through
  one helper.
- **The word SUPPLY on Farmers' Market, Temple and Gladiator is not cosmetic HERE**, because
  all three cost $3 or $4 and can therefore be drawn as **Ferryman's extra pile** — in the game
  and outside the Supply, with no Supply pile to gather onto or trash from. `_supply_pile_for`
  is the guard, and this is a cross-set corner an errata-blind port would have got wrong.
- **Chariot Race now DRAWS its card**, which is the only reason the −1 Card token can deny its
  bonuses; **Capital LOST its "then pay off Debt" clause** to the 2024 rules change.

**The bots learned one thing: `_pay_off_debt`, run before anything else in the Buy phase.**
A tier that ignores Debt and buys an Engineer is locked out of the whole Supply for the rest of
the game — quietly, with no error and no stall, just ending every turn with its coins unspent.
Split piles and Castles stay OUT of `BM_TERMINALS` by the ph.-3H rule that a face which changes
is nobody's reliable terminal.

**Kernel v7H — the DEBT vector + the SCORING PIPELINE. FROZEN.** Hardening with no consumer,
in the 3H/5H/6H mold: no card and no landscape in the data carries a `debt` key, nothing
registers a scoring fn, and no `landmark` is dealt on any board. Everything here is
contract-tested against synthetics in `tests/test_debt.py` (31) and the ph.-7H half of
`tests/test_landscapes.py`. **SCHEMA 11** — a fill-only bump for `game["debt"]`.

- **A COST IS NOW `{coins, potions, debt}`.** `debt_cost(game, card)` is the exact twin of
  `potion_cost` — the PRINTED value, because "cards that reduce $ costs (like Bridge) don't
  affect Debt costs", so nothing in `cost()`'s discount stack (Bridge, Quarry, Ferry's −$2
  token, `DYN_COSTS`) reaches it. Data: an optional `"debt"` int on `CARDS[name]` and on
  `LANDSCAPES[name]`, read through `cards.debt_of` / `cards.landscape_debt` — never indexed.
  The comparators each grow one clause, which is the whole reason ph. 2 banned raw
  `cost() <= n` in card code:

  | comparator | Debt clause | compendium |
  |---|---|---|
  | `cost_le` / `cost_eq` / `cost_lt` (numbers) | `debt_cost == 0` | "up to $N" is an upper bound on the whole vector |
  | `cost_eq_card` | components must MATCH | "exactly $1 more" = "the same cost plus $1" |
  | `cost_le_card` | may not be HIGHER than the ref's | "up to $2 more than {$3,2D}" = "up to {$5,2D}" |
  | `cost_lt_card` | no component higher, at least one lower | "Both {$4} and {4D} are lower than {$4,4D}. However, {$5} is not lower than {$4,4D} (nor vice versa)" |
  | `cost_ge` | none — COINS alone | stated for upper bounds only; **A5 now covers Debt too, same reasoning** |

- **`game["debt"] = {pid: 0}`** — public, game-level like `coffers`/`vp_tokens`, shipped
  as-is in `player_view` (Debt sits in front of you and everyone must be able to count it:
  it is why that player is not buying). `add_debt(game, pid, n)` is public API, not a
  buy-flow internal — "+xD" / "take x Debt" is real card text (Capital, Tax). There is
  deliberately **no `remove_debt`**: paying off is a MOVE, and a card that pays it off
  (Capital) offers that same choice.
- **The buy flow grows two lines in each of `_h_buy` and `_h_buy_landscape`.** The GATE
  first — `debt_blocks_buying(game, pid)`, "when you have Debt tokens, you can't buy
  anything (cards, Events or Projects). This is the only effect of having Debt." It is NOT
  a `BUY_GATES` entry: that registry is per-CARD, and this is a rule about the BUYER, so it
  binds every pile and every landscape at once — which is also how ph. 9's Projects are
  covered for free. Then the TAKE, after the coins are paid: the affordability check reads
  the COIN component alone, so an {8D} card is buyable with $0. `legal_moves` consults the
  same gate (the enumerator/handler agreement rule). **Gaining bypasses all of it** —
  "gaining a Debt-cost card without buying it doesn't give you Debt" — which falls out of
  `gain` not knowing about Debt, and is pinned anyway.
- **`_SPENDABLES` — the registry `spend` always implied.** `{kind: {"avail", "apply"}}`;
  `spendable`/`_h_spend` are now generic, and `_spend_moves` needed no change. Debt's
  `avail` is `min(coins, debt)` — so **avail 0 enumerates nothing**, which is the livelock
  guard for a $0 player. **Paying off uses no Buy and is not buying**: the handler touches
  neither `game["buys"]` nor `turn_ctx["bought"]`, so Treasures stay playable afterwards.
  Legal in EITHER phase and MID-ABILITY — "at any time during your turn … you can even pay
  off Debt in the middle of resolving an ability". **This is the 2024 rules change**; the
  2016 rulebook and every card-list site confine payoff to the second part of the Buy
  phase. Ph. 9's Villagers and ph. 12's Favors are now one dict entry each.
- **`effects.LANDSCAPE_SCORING = {name: fn(game, pid) -> int}`** — THE scoring-pipeline
  hook, summed into `_total_vp` for every landscape DEALT ("a Landmark's ability is always
  active for all players", so there is no ownership test — the `from:"game"` shape). Because
  `_post_move` recomputes `game["vp"]` after every move, during-game landmark VP display
  falls out for free, and a "when scoring" landmark is just a function of final deck
  composition. **The one edge: a scoring fn must not change value at game over** — the
  ph.-7 Inheritance lesson, already pinned by `types_of`'s over-gate.
- **`effects.LANDSCAPE_SETUP = {name: fn(game, rng)}`** — run by `new_game` after every pile
  exists and before the opening deal (Obelisk needs the rng + an Action-pile query; Tax and
  Aqueduct write pile attach). It re-saves the rng **only when a setup actually ran**, which
  is the deal-preservation proof for this phase, the same shape as 6H's `deal_landscapes`
  returning `[]`.
- **Stores.** `add_landscape_vp` / `take_landscape_vp` on `game["landscapes"][name]["vp"]`
  (the Arena/Battlefield class — an empty store gives nothing, takes are capped) and
  `add_pile_vp` / `take_pile_vp` / `add_pile_debt` / `take_pile_debt` on 3H's `attach`
  (Aqueduct/Defiled Shrine/gathering piles; Tax's per-pile Debt). Both delete their key at
  zero, so an untouched pile ships none — and the token cleanup in `move_token` must not
  take a pile's VP with it (pinned).
- **`from:"landscape"` — a landmark on the trigger bus.** The `from:"game"` shape keyed on
  `card in game["landscapes"]` instead of the Supply. The ability goes to the event's ACTOR
  (Aqueduct: "when YOU gain a Treasure…"), lands in that player's pool like any other
  consumer, and displays under the landmark's own name.
- **Frontend, dormant like 6H's landscape row**: a Debt chip on every seat row (public) plus
  a payoff control in the resource bar driven by the SERVER's `spendable.debt`; `debtBlocks`
  mirrors `debt_blocks_buying` so the board greys out instead of bouncing the click.
  `fmtLog` cases for `debt` / `pile_vp` / `pile_debt` / `landscape_vp` and a Debt wording
  for `spend`.
- **A PARKED PLAY MUST CARRY ITS DURATION POINTER — `_restore_cur_dur` (a live bug fixed
  here, pre-existing since ph. 7).** `_cur_dur` says which `dur_setup` entry
  `add_duration_fx` writes to, and `play_action_card` sets it for the physical card. That is
  correct while a play resolves INLINE — but an Attack's ability is parked under the reaction
  windows, and anything in the gap that plays a card repoints it. **Caravan Guard is the
  collision: a reaction that plays ITSELF and is a Duration.** A Haunted Woods played into it
  found the pointer on the reactor's entry, saw the names disagree, and minted a SECOND entry
  for a card played once; with a Throne Room / Royal Carriage replay both entries carry fx,
  both promote at Clean-up, and the card is OWNED TWICE (a conjured card — found by the fuzz
  census on 4p `adventures+alchemy+base`, seed 4, move 343). Both parked-play frames
  (`__attack/play_ability`, `__play/ability`) now carry the pointer and re-point it before
  running the ability. **Restore, never save-and-revert**: it must stay live for the later
  stages the ability pushes (Haven's pick, Throne Room's rider marking), which is what the
  inline path gives them. Guarded on the data key being PRESENT (expand/contract — a live
  save can be sitting on an attack window, and `None` is a meaningful value). **Any future
  deferral of a play owes the same treatment.**
- **`_log` kwargs: a COUNT goes in `count=`, never `n=`.** `_log` stamps the log SEQUENCE
  into `entry["n"]` LAST so an event kwarg can never clobber a core field — which silently
  discards an `n=`. Three sites did it (`coffers`, `spend`, `end_draw`) and the client
  rendered the sequence ("gets +917 Coffers"). Fixed; `fmtLog` reads `e.count ?? e.n` so
  entries already in prod render as before, and `test_no_log_call_passes_a_count_as_n` is the
  guard — the failure is invisible to any test that doesn't read the rendered string.
- 7H ships **no landmark, no Debt card and no Event** — the `landmark` kind stays undealt
  until Empires, exactly as 6H shipped zero Events. **What ph. 8 must VERIFY, not rebuild**:
  split piles + Castles are 3H ordered piles priced through their face (pinned by
  `test_an_ordered_piles_cost_follows_its_current_face`), `attach` already ships on the
  wire, and Landmarks deal as landscapes by construction.

**Kernel v7 — the phase-7 (Adventures) delta. FROZEN.** The set consumes 6H wholesale (Reserves
on the Tavern mat, Events on `LANDSCAPE_FX`, tokens on `attach`, Travellers on 5H's interruptible
Clean-up + ph. 3's `exchange`) and **needs no SCHEMA bump** — every key it reads was added by
v10. What it did add:

- **`until="forever"` watchers and `add_duration_fx(..., forever=True)`** — a REST-OF-THE-GAME
  ability (Champion, Hireling). `_start_of_turn` marked every entry `done` unconditionally,
  which discarded the card at the next clean-up; the flag lives on the ENTRY because "this stays
  in play" is a property of the physical card, so a throne-roomed Hireling doubles the fx on one
  entry and draws +2 every turn. A `forever` watcher also survives its owner's turn start, which
  is what expires every other one.
- **Three SEAT tokens with behaviour** (`seat["tokens"]`, storage from 6H): **−1 Card** eats the
  next DRAW inside `draw()` and nothing else — a reveal or a look leaves it, an otherwise-empty
  deck does NOT reshuffle to feed it, and it comes off even with nothing left to draw. **−$1** is
  applied in `add_coins` and is "only removed when you get $1 or MORE, not when you get $0", so a
  Miser with an empty mat leaves it alone. **Journey** is stored as its DOWN state
  (`journey_down`) so absence means the face-up start — which is what a fresh seat and an old
  save both correctly mean; `flip_journey` returns the NEW face. `take_seat_token` returns False
  when you already have it ("an effect that makes you take it does nothing").
- **The kernel contributes to ability POOLS on its own behalf** (`_collect_token_abilities`). A
  token is not a card, so it can have no `TRIGGERS` entry — but its ability is concurrent with
  every card ability the same occurrence triggers, so it has to arrive through the pool rather
  than be applied inline. The four "+" tokens are `before_play` abilities (p33 puts them in the
  same class as Urchin and Champion) and `commutes`, since taking +1 Action can never change
  what +1 Card does. Plan's Trashing token is the `gain` one, and it is the exception the
  compendium calls out — its 2022 version "can also be on an opponent's turn".
- **`request_extra_turn(game, pid, source=, no_buy=)`** — Mission. Outpost's own transient is
  left untouched deliberately (a save can be caught mid-turn holding it), and Outpost's 3-card
  draw is still Outpost's alone. `turn_ctx["no_buy"]` bans buying CARDS only: Events stay
  buyable, which is what the card says.
- **`turn_ctx["end_hand"]`** — Save's "put it into your hand at END OF TURN (after drawing)", so
  the saved card is an EXTRA card in the new hand rather than one of the five.
- **`gain(game, pid, pile, **extra)`** — `**extra` rides the `gain` EVENT, so a card can mark a
  gain it caused and read the mark back in its own when-gain condition. Port needs exactly one
  bit of that ("when you gain a Port DUE TO Port's when-gain, it doesn't trigger again"), and a
  transient on the game dict would NOT do: the would-gain protocol can PARK the physical gain,
  so the emit may happen long after the call returned.
- **INHERITANCE — a game-wide type injection, not an identity system.** `types_of` adds
  `action`+`command` to **Estate** while the turn player has an Estate token, which changes
  EVERY Estate in the game (opponents', in play, in the Supply, in the trash) and only on that
  owner's turns — keyed on `game["turn"]`, exactly like the −$2 token in `cost()`, so `types_of`
  keeps its two-argument signature. It stops once the game is OVER, which is the compendium's
  Vineyard ruling ("Estates are not Action cards when you score, as it's not your turn at the
  end of the game"). `play_set_aside` is `play_from_supply`'s twin for a card set aside FROM the
  Supply, and `take_from_pile_aside` puts it there without a gain ("this is not considered
  gaining a card"). An Estate played by someone who is not the token owner "goes into play but
  does nothing", which falls out of `play_set_aside` returning False.
- **`"distant_lands"` joins the computed VP kinds** — the first VP that depends on WHERE a card
  is rather than on what else you own, so it is counted from the `tavern` zone in `_vp_of`
  rather than from the flat owned list, which cannot say where anything is.
- **New card types**: `reserve` and `traveller`, both read only by the cards themselves.

**THE 2022/2023 ERRATA ARE THE STORY OF THIS SET, and reading them FIRST is what made it data
rather than nine bugs.** Ten Adventures cards differ from every card-list site and from the 2015
rulebook: Bonfire, Bridge Troll, Haunted Woods, Inheritance, Messenger, Plan, Port, Storyteller,
Swamp Hag (2022) and Mission (2023). The 2022 pass did two things across the catalogue —
"when-buy triggers were changed to when-gain, and while-in-play timers were removed" — so
Haunted Woods, Swamp Hag, Messenger, Port and Plan's token trigger on a GAIN (the first two on a
BOUGHT gain, which is why an Event purchase does not set them off); Bridge Troll's cost
reduction is turn-scoped like Highway's and cumulative with a throne-room; Bonfire only trashes
Coppers; Storyteller gives +1 Card instead of the +$1 it used to pay itself with. `cards.py`
carries the per-card list.

**Kernel v6H — the LANDSCAPE kernel. FROZEN.** Hardening with no consumer: `cards.LANDSCAPES`
is EMPTY and nothing on any board today uses a line of it. Everything here is contract-tested
in `tests/test_landscapes.py` against synthetic landscapes and a synthetic Reserve.

- **A LANDSCAPE IS NOT A CARD AND NOT A PILE**, so it gets its own table:
  `cards.LANDSCAPES[name] = {kind, cost, text, expansion, once?}` + `game["landscapes"][name] =
  {kind, bought_turn, bought_by}`. It has no copies, is never gained, never sits in a zone, and
  "buying an Event is not buying a card" — a `CARDS` entry would give it a cost `cost()` would
  discount and a `kingdom` flag that would deal it as one of the ten. **This is the Knights
  lesson in REVERSE**: there a card-shaped structure had to learn to tolerate a foreign name (at
  six call sites); here the foreign thing arrived before its first consumer, so it cost none.
  All six `LANDSCAPE_KINDS` are framed up front (`event` `project` `way` `landmark` `trait`
  `prophecy`); only `event` is wired, and only `BUYABLE_LANDSCAPE_KINDS` may be bought.
- **Setup is the official randomizer mix** (p11: "shuffle them in with the Randomizer cards and
  use the first landscape cards that show up before hitting 10 Kingdom cards; no more than two,
  no more than one a Way"), simulated literally so pool SIZE matters. `new_game(landscapes=...)`
  is the forced-board seam, the `kingdom=` idiom. **`deal_landscapes` draws NO entropy while the
  pool is empty** — that is the whole behaviour-preservation proof for this phase, since setup is
  one rng call sequence and inserting a step into it would re-deal every existing seed's board.
  There is no create-modal row: the deal is automatic, like Platinum/Colony.
- **`{"type":"buy_landscape","name":...}`** — spends a Buy and coins, sets `turn_ctx["bought"]`
  (buying anything ends the treasure half of the Buy phase), and emits **nothing**: no `gain`,
  no `buy`, no `buy_gains` bump, so no Hoard/Haggler/Merchant Guild-class watcher can see it.
  **`landscape_cost()` is the PRINTED cost and never `engine.cost()`** — "its cost cannot be
  changed by cards like Bridge". **`landscape_gate(game, pid, name)` is THE reader**, consulted
  by `legal_moves` AND the handler (the `spendable`/`manual_treasures` lesson); it owns the
  buyable-kind test and the once-per-turn (`bought_turn` vs `turn_number`) and once-per-game
  (`bought_by`) gates, both per player. Abilities live in `effects.LANDSCAPE_FX` (merged like
  EFFECTS) and may push frames, which display under the landscape's own name.
- **The TAVERN MAT + calling** — seat zone `tavern` (public: the cards lie face up), joined to
  `owned_cards` (Distant Lands scores ON the mat) and both census copies. `to_tavern` /
  `call_card` / `discard_from_tavern` / `on_tavern`. **Calling is NOT playing**: no
  `actions_played` bump, no `before_play`, no `action_resolved`, no attack window even for an
  Attack-typed Reserve — which is exactly why it is its own helper and not a detour through
  `play_action_card`. A called card sits in `in_play` and the all-seats clean-up sweep (ph. 3)
  discards it in THAT turn's Clean-up, including an off-turn call.
- **THERE IS NO `call` MOVE, and the ledger row that promised one was wrong.** Every Reserve
  call in the game is a timed window — start of your turn, on a gain, directly after resolving
  an Action, end of your Buy phase — so it must be ordered in the ability POOL against
  everything else the same occurrence triggered, which a `legal_moves` entry cannot be. Calling
  is therefore a new TRIGGER SOURCE, **`from:"tavern"`**: the `from:"hand"` offer shape on the
  other public per-seat zone, with `mode:"call"` (verb "Call", "from your Tavern mat"). The
  stage performs the move, like every other reaction mode. No `CALLS` registry — a trigger spec
  already names its stage, and a second map to the same stage is only somewhere to disagree.
- **`emit("play_attack")` → `emit("before_play")`, fired for EVERY Action play**, carrying
  `attack=` and `replay=` in the ctx. Adventures' "+" tokens are the same timing class as Urchin
  ("after before-play abilities like Adventures tokens, Kiln, Urchin", p33), so one event serves
  both. **The catch, and the reason this is conditional:** an Attack gets the ordering free
  (`_open_attack_window` already parks the play ability under the windows) but an ordinary play
  runs its effect INLINE, and a pool parked before an inline call resolves AFTER it — backwards.
  So `_before_play_then_ability` parks the ability as `("__play","ability")` **only when the
  emit actually collects a consumer**, and runs it inline when it doesn't. That is what makes
  the widening byte-identical rather than merely equivalent; Urchin's existing suite passing
  UNCHANGED is the net, and its `when` now reads `ctx["attack"]` explicitly.
- **`emit("action_resolved")` — the one genuinely new event.** "Directly after resolving an
  Action card" cannot be emitted from `play_action_card`: it returns while the play's frames are
  still pending, and "completely resolve the play ability before playing it again" (p17) defines
  resolution as those frames having drained. So it is a `("__play","resolved")` continuation
  parked BEFORE the play pushes anything — LIFO fires it exactly then. A throne-roomed Action
  emits twice, once per resolution (`replay` tells them apart), which is what a Royal Carriage
  called after each needs. Zero consumers today.
- **Adventures TOKENS, storage + one hook.** Per-PILE tokens ride 3H's `attach`
  (`attach["tokens"] = {pid: [kind]}`, already on the wire) via **`move_token(game, pid, kind,
  pile)`** — the only writer, because "if you move a token that is already on a pile, it is
  moved FROM that pile", and it accepts an EMPTY pile ("tokens may be put on an empty pile").
  Readers: `pile_tokens`, `token_pile`. Per-SEAT tokens (−1 Card, −$1, Journey) live in
  `seat["tokens"]` via `seat_token`/`set_seat_token` — storage only, wired to the draw and the
  +$ at ph. 7, landed now so migrate is done once. **The `-cost` token reaches `cost()`**:
  "cards from that pile cost $2 less ON YOUR TURNS" keys on `game["turn"]`, not on an asking
  player, which is what lets `cost(game, card)` keep its signature and its ~60 call sites; it is
  read BEFORE `_priced` collapses a pile name into its face, and guarded by a cheap
  `_any_pile_tokens` scan so an ordinary board pays nothing.
- **`_run_ability(game, pid, fn)`** — the `_actor` binding + log depth every non-stage dispatch
  point now shares (a card's on_play, a Command's borrowed ability, a landscape's ability). It
  was three copies of the same eight lines.
- **Frontend**: a wide landscape ROW above the Supply that renders NOTHING when the game has
  none (pinned by `screens.mjs` — a ghost row would push the whole board down on every game for
  a feature nobody can use yet); Tavern mats as public `DmMatChip`s for every seat (contents and
  all, unlike the Native Village mat); token chips in a pile's top-LEFT corner (the Bane marker
  owns top-right, the count pill straddles the bottom); `fmtLog` cases for all five new events.

**Kernel v6 — the phase-6 (Dark Ages) delta. FROZEN.** The set is almost pure card work — the
on-trash theme is `trash()`'s existing emit read `from:"self"`, and both shuffled piles are ph.
3H ordered piles. What it did add:

- **A KINGDOM ENTRY MAY BE A PILE NAME, NOT A CARD.** `cards.PILES` holds the dealt piles whose
  name is not a card ("Knights" today) — `{cost, expansion, kingdom, members, size}`. This is
  forced, not stylistic: `_priced` resolves a name that IS a card to itself, so a `CARDS["Knights"]`
  entry would make the pile show its own printed cost instead of its top card's, and a Sir Martin
  on top really does cost $4. Everything that walks a kingdom list therefore tolerates one:
  `cards.grants` returns False, `cards.expansion_of`/`cards.printed_cost` answer for it,
  `bot_traits.best_bm_terminal` and `bot_plan.features` skip it, `REVIEWED` reviews its MEMBERS,
  and `push_name_card` leaves it out of the offer ("'Knight' and 'Ruins' are types, not names").
- **Setup rules** (all three from SPECIAL SETUP § I, all in `new_game`): `game["shelters"]` is
  Colony's probabilistic shape — the Dark Ages PROPORTION of the dealt 10 — on a SEPARATE rng
  draw ("it should not be the same card you check for Colonies"), and replaces each player's 3
  starting Estates with a Hovel/Necropolis/Overgrown Estate (the Estate PILE is untouched; the
  Shelters belong to no pile). A `looter`-typed kingdom card includes the **Ruins** pile: as many
  cards as there are Curses, drawn from a shuffled 10-of-each-of-5. **Knights** is one shuffled
  pile of its 10 distinct cards. Both are ordered piles, so only the top card is visible and
  `contents` never ships. Hermit/Urchin/(Bandit Camp|Marauder|Pillage) add the **Madman /
  Mercenary / Spoils** non-Supply piles — and so does a Bane or Ferryman pile that happens to be
  one of them ("if these extra cards have a special setup rule, do that setup").
- **`cost_ge(game, card, coins)`** — "costing $N or MORE" (Sage; the lower half of Knights' and
  Rogue's "$3 to $6"). It reads the COIN component alone: the compendium's Potion rule is about
  UPPER bounds, so a range's `cost_le` half is what (correctly) excludes Potion cards. Recorded
  as an open ambiguity (A5) — the rule is stated for "up to", not for "or more".
- **`from_trash(game, pid, card, dest="hand")`** — take a card OUT of the trash WITHOUT gaining
  it (Fortress: "This is not gaining it. It was still trashed"). Emits nothing. Distinct from
  `gain_from_trash`, which IS a gain — and which now **emits** one (compendium, Graverobber 4:
  "When-gain abilities will trigger"), and takes `dest=` for Graverobber's onto-your-deck.
- **`deck_to_discard(game, pid)`** — Scavenger's "put your deck into your discard pile". NOT a
  discard for triggers ("this doesn't trigger cards that say WHEN YOU DISCARD THIS"), so it never
  goes through `discard()`; it does mark revealed, since the bottom of the deck becomes visible.
- **`emit("play_attack")`** — the BEFORE-play window (Urchin). Emitted AFTER
  `_open_attack_window`, so its ability pool sits ABOVE the reaction windows and resolves first,
  which is what "you may FIRST trash this" means. It carries `replay=` so a throne-room replay of
  the same card does not count as "another Attack card".
- **Reaction MODES `"discard"` and `"trash"`** — a hand reaction whose cost is the card itself
  (Beggar discards, Hovel trashes, Market Square discards). `_REACT_VERB` is the one place a
  mode's verb is named, shared by the attack window and the `from:"hand"` trigger offer; the
  STAGE still performs the move.
- **`"feodum"`** joins the computed VP kinds (1 VP per 3 Silvers), and four inert TYPES arrive
  (`looter`, `ruins`, `knight`, `shelter`) that only the cards themselves read.

**The ordering rule this phase re-proved: a gain that follows a trash must be parked BELOW it.**
Procession, Graverobber and Rebuild all first pushed the gain prompt after calling `trash()` —
LIFO, so the player was asked what to gain before the trashed card's own when-trash ability
resolved, and a processioned Fortress came back to hand only afterwards. The compendium spells
the order out for each ("first play twice, then trash, then check cost, then gain"). Push the
continuation FIRST; `trash()`'s pool then stacks on top of it. Same shape as the phase-3
put-back lesson, in the opposite direction.

**Kernel v5H — Clean-up and Command. FROZEN.**
- **CLEAN-UP IS INTERRUPTIBLE.** `_end_turn` parks the sweep as a `("__cleanup","sweep")`
  continuation and emits **`cleanup_start`** (new) then `cleanup_discard` for the whole in-play
  row as ONE `emit_batch`, all before anything moves. A consumer may push a real decision frame
  and RELOCATE a card:
  with the prompt open, nothing is discarded, no new hand is drawn and the turn is not yet
  counted. **The batch is load-bearing, not tidiness**: the table is discarded SIMULTANEOUSLY, so
  every card's consumers belong in ONE pool and the player orders them (p23 §2). A per-card emit
  ordered them by in_play POSITION instead — the ledger-B4 accident — and with two Travellers
  finishing their journey that order is a real decision (exchanging the Fugitive returns it to
  its pile, which is what lets the Soldier exchange into it).
  The sweep RE-READS the table rather than trusting a snapshot. Alchemist rides
  `cleanup_start`; Scheme and Herbalist stay on the per-play `buy_phase_end` watcher on
  purpose (their triggers are per-play, not per-card, so one prompt with the whole list is
  the same decision with fewer clicks).
- **`play_from_supply(game, pid, pile, count=True)`** — PLAY A CARD WHILE LEAVING IT: run a
  Supply pile's top card's play ability with the card never moving. Band of Misfits and
  Overlord (Command) and Inheritance's Estates all do exactly this. **It is NOT "play this
  card as that one"** — the 2019 errata retired that reading. Attacks route through the
  kernel's own `_open_attack_window`, so reactions resolve first, once.
  `command_may_play(game, card)` is the eligibility rule (an Action, not a Command — "to
  prevent loops" — and not a Duration, per the 2025 change); `playable_from_supply(game, pid,
  pred=None)` enumerates the piles, asking **`pile_top`** because only the top card of a pile
  is choosable. `"command"` is an allowed card type awaiting its first card in ph. 6.

**Kernel v5 — the phase-5 (Alchemy) delta: THE COST VECTOR. FROZEN.**
A cost is `{coins, potions}` — **and, since ph. 7H, `{coins, potions, debt}`; see Kernel
v7H for the third dimension, which obeys every rule below identically.** `cost()` still
returns the COIN component, so every existing caller is unchanged; `potion_cost(game, card)`
is the second dimension (printed — cost reductions only ever touch coins). The compendium's
three rules (POTIONS § IV) live in engine.py and nowhere else:
- **"up to $N"** = coins ≤ N **and potions == 0**. So `cost_le`/`cost_eq`/`cost_lt` — the
  NUMBER forms — now exclude every Potion card, which is what makes "gain a card costing up to
  $4" correct on an Alchemy board with no call-site change anywhere.
- **"exactly $N more"** = *the same cost plus $N*, so the potion components must MATCH:
  `{$3,P}` is exactly $1 more than `{$2,P}` but **not** than `{$2}`.
- **"lower than"** = no component higher and at least one lower, so `{$4,P}` and `{$5}` are
  **incomparable** — neither is cheaper than the other.

The last two are not expressible against a number, so they get **card-reference** forms:
`cost_le_card(game, card, ref, delta)` · `cost_eq_card(game, card, ref, delta=0)` ·
`cost_lt_card(game, card, ref)`. **Any "N more/less than THIS CARD" comparison must use them**;
the number forms are for literal bounds only (Workshop's $4, University's $5, Stonemason's
overpay). The remodel family (Remodel, Mine, Remake, Upgrade, Develop, Expand, Swindler,
Stonemason) is already migrated — copy one of those, not a number bound.

Also: `game["potions"]` is the second money pool (a played Potion produces one, per-turn like
coins, so it evaporates off-turn); `_h_buy` and `legal_moves` gate on both components; the
Potion pile joins the Supply whenever any kingdom card has one in its cost; `player_view` ships
`potion_costs` (non-zero entries only) beside `costs`; `"vineyard"` joins the computed VP kinds.

**`cards.DEFERRED`** records cards we have deliberately not built (today: Possession), as DATA
with a reason and a plan pointer, so `test_cards.py` can reconcile a set's published roster
against what ships. Deleting a row is how you hand the work back in.

**Kernel v4 — the phase-4 (Cornucopia & Guilds) delta. FROZEN.**
- **COFFERS** — `game["coffers"][pid]` + `add_coffers(game, n, pid=None)`. Deliberately NOT routed
  through `_grant`: the per-turn pools evaporate off-turn because "on another player's turn you
  always start with empty pools", but Coffers are a MAT and persist by their nature, so an
  off-turn Coffers is KEPT. Setup: Baker in the kingdom starts everyone on 1.
- **The generic `spend` MOVE** — `{"type":"spend","what":"coffers","n":k}`, the first of the
  move-surface trio (Villagers ph. 9, Favors ph. 12, Debt payoff ph. 8 are all the same shape).
  `spendable(game, pid) -> {kind: count}` is THE reader — `legal_moves`, the handler and the
  client all go through it, because an enumerator and a handler that disagree hand the bot a
  no-op move (the `play_all_treasures` livelock). Legal in EITHER phase: "Coffers tokens can be
  spent at any time during your turn" (2022 change).
- **OVERPAY** — `cards.py` carries `"overpay": True` (the `$N+` cost); `cost()` still returns the
  plain number, because "for any ability that refers to a card's cost, ignore the +". `_h_buy`
  pays the cost, then — if any money is left — pushes a `choose_option` for the amount under a
  parked `("__buy","finish")`; `("*","__overpay")` is a kernel stage, so the prompt displays
  under the BOUGHT CARD's own name. **The ability the money buys is a WHEN-GAIN ability** (the
  2022 retiming): the amount rides the `gain` event as `overpay=N`, and each card registers
  `{"on":"gain","from":"self"}`. Pre-2022 it was a when-buy ability — the compendium's older
  examples describe that version and do not apply.
- **`TRIGGERS` source `"game"`** — "in games using this, ..." (Footpad). Fires for the event's
  ACTOR when the card is in the **Supply** (not merely the dealt 10, so a set-up extra pile
  counts), whether or not anyone owns a copy. On the bus rather than a game-dict flag
  (Charlatan's shape) because it must resolve in the player's chosen order against the other
  abilities the same occurrence triggered.
- **Per-seat set-asides + start-of-turn abilities** — `set_aside(game,pid,cards,zone,until=None)`
  / `take_set_aside` / `add_start_fx(game,pid,card,stage,data)`. Farmhands is the reason: its
  set-aside is NOT a Duration (the Farmhands itself goes to the discard), so there is nothing on
  the table to hang a duration fx off. `_start_of_turn` drains `seat["start_fx"]` into the SAME
  ability pool as the duration fx and the `turn_start` reactions — they are simultaneous.
  `until="cleanup"` uses the second zone, `cleanup_aside`, swept to the discard by `_end_turn`
  (Joust's "discard the Province in Clean-up"). Both zones are set-aside, NOT in play, which is
  what keeps them out of Horn of Plenty's and Shop's in-play counts.
- **`play_treasure_card(game,pid,card,from_zone="hand")`** — a Treasure played out of band
  (Coronet plays one twice; Farmhands plays a set-aside one at turn start). `from_zone=None` is
  the throne-room replay.
- **`turn_ctx["buy_gains"]`** (cards GAINED in this Buy phase — Merchant Guild counts all gains,
  including ones from before it was played) and **`turn_ctx["end_draw"]`** (drawn by `_end_turn`
  AFTER the new hand — Farrier's overpay is cards for NEXT turn).
- **Setup-chosen piles**, all riding ph. 3H: `game["bane"]` (Young Witch — an 11th pile added TO
  the Supply, cost $2/$3; "Bane" is not a type), `game["ferryman_pile"]` (an unused $3/$4 pile
  OUTSIDE the Supply), and the six Rewards as six non-supply piles (one of each at 2 players,
  two otherwise). All are drawn from the kingdom cards this game did not deal; with none eligible
  we play without one rather than re-dealing the board.
- **New computed VP kinds**: `"fairgrounds"` (2 VP per 5 differently named cards you have) and
  `"demesne"` (1 VP per Gold), alongside `gardens`/`duke` in `_vp_of`.

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
  AFTER the whole batch moves), `cleanup_start`, `cleanup_discard`, `buy_phase_end`, `turn_start`,
  `would_gain`, `before_play` (attack/replay — ph. 6H, was `play_attack`), `action_resolved`
  (replay — ph. 6H). Sources: `"self"`, `"in_play"`, `"hand"`, `"game"`, `"tavern"` (ph. 6H),
  `"landscape"` (ph. 7H — a LANDMARK, keyed on being dealt).
  ⚠ **`cleanup_discard` fires but `_end_turn` is NOT interruptible** — `emit` parks an auto frame
  and the sweep doesn't drive frames, so a consumer cannot yet MOVE the card. Scheme needs that
  built; do not assume it works.

**Kernel v2 — DURATIONS (Seaside; the contract for later expansions too):**
`add_duration_fx(game,pid,card,stage,data=None,forever=False)` — register a start-of-NEXT-turn
ability (`forever=True` = "at the start of EACH of your turns for the rest of the game" — the
entry is never marked done, so the card stays on the table: Hireling, Champion) on the
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

**CONCURRENT-ABILITY ORDERING (p23 §2 — the ability POOL):** when ONE occurrence hands a player
several abilities, the player chooses what resolves first — `park_abilities(game, pid,
[{card, stage, data}, ...])`. It parks a `("__abilities", "pool")` auto frame; the pool groups
interchangeable copies (same card+stage — two Tide Pools never prompt; a per-pair `ORDER_MATTERS`
opt-out exists for a future card whose copies differ), runs a single group directly in the
historical order, and otherwise pushes a plain `choose_option` (card `"__abilities"`, mapped to a
display string client-side like `"__attack"`). Picking resolves ONE instance fully on top of the
stack (atomicity for free), then the remainder pool re-surfaces and RE-OFFERS — sequential choice,
never order-the-list-up-front, so later picks can react to what earlier resolutions revealed and
interleaving (p24 §3) falls out naturally. Because it's a plain choose_option, legal_moves /
sample_decision / both bots / redaction / all six renderers work untouched. **CONTRACT: any code
path pushing ≥2 same-player frames from one occurrence must route through park_abilities.** Wired
today: `_start_of_turn` duration fx (phase 1) and **`emit()` itself** (phase 2) — every event's
consumers (watcher autos, `self` triggers, `in_play` pushes, `hand` windows) are collected into ONE
pool per player, pushed in reversed turn order (current player's resolves first, p23 §3). Three
supporting pieces, all load-bearing:
- **Deferral runners**: a pooled hand window parks as `("*", "__offer_window")` and an in_play push
  as `("*", "__inplay_push")` — each re-checks card PRESENCE at resolution and logs `lost_track` if
  an earlier pick moved it (the spec index rides in the frame for `__inplay_push`).
- **`WATCHER_WHENS`** (per-module registry, merged like STAGES): `(card, stage) -> fn(game, w, ctx)`
  — does this WATCHER actually fire for this occurrence? Evaluated at JOIN time (p25 §3), so a
  watcher whose ability would no-op (Monkey on anyone but the right-hand neighbour, a spent Sailor,
  Haggler on a non-buy gain) never enters the pool — a prompt ordering a no-op against a real
  ability implies the no-op will do something. **A new watcher with an internal no-op condition
  OWES a WATCHER_WHENS entry**; the stage keeps its own guard as the resolve-time re-check.
- **`commutes`** (add_watcher kwarg / TRIGGERS spec key): decision-free AND order-independent
  abilities (Collection's +1 VP, Nomads' +$2) auto-run first and never appear in the prompt.
  Declare it only when resolving the stage can never change what any other pending ability does.
Bucket order inside a pool = self, in_play, hand, watchers — the pre-pool engine's exact pop order,
so the FIRST option is always the historical default and a single consumer is byte-identical to the
old direct push. **Multi-card discard/trash batches go through `emit_batch(game, event, actor,
subjects, **extra)`** (phase 3): the cards moved SIMULTANEOUSLY, so every card's consumers collect
into one pool per player — never per-card emits in list order, which re-creates the retired
reverse-click-order accident. Gains stay per-emit on purpose (gains resolve one at a time by rule).
**`_start_of_turn` merges the duration fx and the `turn_start` emit into ONE set of pools** (phase
4): all start-of-turn abilities are simultaneous, so a Clerk in hand and a finishing Wharf are the
player's ordering choice, and pools park current-player-first (p23 §3). **The plan is COMPLETE** —
`.claude-plans/concurrent-ability-ordering.md` is the history; rows A2/A3/B4 are retired.

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

⚠ **`from:"in_play"` ASKS ONLY "is the card on the table" — it is SUBJECT-BLIND.** That is right
for Treasury/Hoard ("while this is in play, when you gain a card…") and wrong for anything whose
ability is about ITSELF, which is what `"self"` is for. A spec that needs the push function to
read which card triggered it (the Travellers' `_traveller_offer`, which is one function shared by
all eight) must therefore carry its OWN identity test in `when` — `ctx["subject"] == card`,
closed over at registration. Without it the spec fires on **every** emit of that event: the
Clean-up emits one `cleanup_discard` per card in play, so a Soldier and a Fugitive on the table
each collected an offer from the other's emit as well (N Travellers in play ⇒ N² prompts), and
the offer resolved the EMIT's subject rather than the option the player picked — choosing
"Fugitive" exchanged the Soldier, then logged `lost_track` at the player for the leftovers.
Reported from a real game and fixed 2026-08-05; pinned by two tests in
`test_cards_adventures_b.py`.

**Kernel v3 (Prosperity):** `add_vp_tokens(game,pid,n)` (public, score-counted, never lost) ·
`cost_le`/`cost_eq` are THE cost comparators (raw `cost() <= n` in card code is a review
reject — the Potion vector landed inside them in ph. 5 and the Debt one in ph. 7H, with
zero call-site changes: the discipline paid for itself twice) · `has_type`/`types_of`/`coins_of`
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
WATCHER_WHENS: {(card, stage): fn(game, watcher, ctx)}  # optional — join-time
                                   # pool filters for watchers (see the
                                   # concurrent-ability section above)
LANDSCAPE_FX: {landscape_name: fn(game, pid)}  # optional (ph. 6H) — the ability
                                   # an Event/Project hands you when you BUY it.
                                   # A landscape is not a card, so it cannot
                                   # live in EFFECTS without making every
                                   # `card in EFFECTS` test wrong.
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
victory-typed 8/12, else 10); `PILES` (a dealt pile whose name is not a card — Knights);
`LANDSCAPES[name] = {kind, cost, text, expansion, once?}` (ph. 6H — NOT cards and NOT piles;
empty until Adventures) + `landscape_pool(expansions)` / `landscape_kind(name)`;
`DATA_COMPLETE`.

**A SKIPPED ABILITY MUST NEVER BE SILENT — call `lost_track(game, pid, card[, verb][, why])`.**
The lose-track rule ("cards that are lost track of can't be played") means a prompt correctly never
opens, and from the player's seat that is indistinguishable from a trigger that failed to fire —
which is exactly how Trail × Tide Pools got reported as a bug. There is NO runtime signal either:
the correct behaviour and a genuinely broken trigger leave identical game state, so it is guarded at
SOURCE level by `test_every_find_card_zone_guard_logs_lost_track`, which walks the effects modules'
AST and fails on any `find_card_zone` guard that returns without logging. It covers both guard
shapes (inline `if find_card_zone(...) is None:` and `zone = …` / `if zone is None:`) — an earlier
regex version scanned a 6-line window and comments pushed two real sites out of it, so it passed
while checking 5 of 7. **It found an 8th site the manual sweep had missed** (Sailor's offer). Today's
eight: Trail/Weaver (offer + answer), Tunnel (offer + answer), Berserker, Sailor (offer + answer),
and Watchtower — whose membership-test guard is NOT mechanically detectable and is on you.
`verb` is what can't happen ("played"/"revealed"; omit for Watchtower's trash-or-topdeck), `why`
replaces the default "it moved" where nothing actually moved (Sailor's gain landing somewhere it was
never playable from).

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
| ~~A2~~ | ~~A gained card's own when-gain vs a hand reaction on the same gain~~ | **RETIRED (phase 2 of the ability pool)** — the player now chooses, per p23 §2. `test_watchtower_and_inn_the_player_chooses_and_each_order_differs` plays the compendium's worked Example 1 down BOTH branches. | — |
| ~~A3~~ | ~~Two of the player's own triggers firing simultaneously~~ | **RETIRED (phase 2)** — same pool. Registration order survives only as the pool's OPTION order (the first option is the historical default). | — |
| A4 | **Butcher**: do the Coffers you spend for its "remodel" ALSO pay you the +$1 each? | **Yes** — one rule for spending. `_butcher_spend` goes through the same accounting as the `spend` move: tokens off the mat, +$1 each, and the count also raises the gain's cost limit. | The global rule is unconditional ("each spent token gives you +$ and is immediately removed") and Butcher only adds a use for the COUNT. But the compendium's phrasing cuts the other way — "any Coffers tokens you get from Butcher that you don't use to 'remodel' a card, you save for later to spend for +$ **as normal**" reads as though the ones spent on Butcher were spent for something else instead. We took the branch that keeps ONE rule for spending rather than two. Pinned by `test_butcher_gives_two_coffers_and_remodels_per_coffers_spent`. |
| A6 | **Outpost played AND Mission bought on the same turn** — you get ONE extra turn (no third turn in a row); is it a Mission turn (no buying cards) or an Outpost one? | **A Mission turn**: `extra_no_buy` is set whenever the granted turn was requested by Mission, even if Outpost also asked. Outpost's 3-card draw still applies. | Each card describes the turn IT gives, and the rules never say which one "wins" when both fire and only one turn is taken. We took the stricter reading — a restriction that is simply swallowed is the more surprising outcome, and the player chose to buy Mission. Pinned by `test_outpost_and_mission_on_one_turn_give_one_mission_turn`. |
| A5 | **"costing $N or MORE"** with a Potion **or Debt** in the cost — is a {$3,P} card "costing $3 or more"? Is a {$2,4D} one "costing $2 or more"? | **Yes to both** — `cost_ge` reads the COIN component alone, so Sage finds a Familiar, a Knight can trash one, and a Debt-costed card is reachable the same way. | The compendium states the exclusion rule for UPPER bounds only ("up to $N" = coins ≤ N and potions == 0 and debt == 0); it says nothing about a lower bound, and both readings are defensible. **Debt inherits this row unchanged rather than getting one of its own** — same rule, same silence, same reasoning ("Debt functions like another kind of cost, just like Potion"). Ours keeps a range like Knights' "from $3 to $6" excluding both, because its `cost_le` half still does. Pinned by `test_sage_digs_for_a_three_or_more`, the cost-vector tests, and `test_cost_ge_reads_the_coin_component_alone`. |
| A7 | **Innovation** is "once during each of your turns" — does DECLINING the offer spend the use? | **No** — the flag counts USES, not triggers, so a player who declines on one gain may still play a later one that turn. | The card says "once during each of your turns, when you gain an Action card, you MAY play it", which reads either way: the "once" could bound the offer or the play. We took the reading that never punishes a player for being asked — declining is not using it, and the alternative makes an unwanted early prompt silently cost the ability. Pinned by `test_declining_innovation_leaves_it_available`. |
| A8 | **Fleet**: an extra turn TRIGGERED during the Fleet round (an Outpost played on a Fleet turn) — resolved, or does the round stop dead? | **Resolved, uniformly** — the round ends when no owner is still owed a turn AND nothing is queued behind it, so a turn triggered on the LAST Fleet turn is treated exactly like one triggered on any other. | Ch. VII's Fleet entry has exactly THREE clarifications and none of them mentions turns triggered *during* the round — only those "already in queue", which "will now be resolved… (This also applies to any other after-turn abilities.)". Both readings fit. We took the one that makes the round internally consistent; the code previously did BOTH (granting a turn triggered on an early Fleet turn and dropping one triggered on the last), which is the only reading nothing supports. **The ph.-9 audit is why this row exists**: the code comment quoted a "once the last Fleet turn has been played, the game is immediately over" sentence that is not in ch. VII v11.1. Pinned by `test_an_extra_turn_taken_on_the_last_fleet_turn_is_still_resolved`. |

**B. Deliberate simplifications — the rules are clear, we do something simpler**

| # | Rule | What we do | Cost |
|---|---|---|---|
| B1 | **Scheme**, **Alchemist** and **Herbalist** each trigger at Clean-up ("when you discard it from play" / "at the start of Clean-up") | Per-play `buy_phase_end` watchers, filtered on the event's new `final` flag | The compendium says Scheme's two timings have "no practical difference", and in today's pool the last `buy_phase_end` of a turn genuinely coincides with Clean-up. **Ph. 9 made the divergence REAL and paid for it**: Villa returns you to your Action phase, which genuinely ENDS a Buy phase, and six cards printed "at the end of your Buy phase … in it" (Merchant Guild, Treasury, Hermit, Wine Merchant, Exploration, Pageant) must see every one — so `return_to_action_phase` now emits the event too, and it can fire twice in a turn. These three carry `ctx["final"]` in their join-time filter so they still fire once, at the real end. **They cannot simply move to `cleanup_start`**, which looks like the right seam: `_end_turn` discards done Duration entries BEFORE emitting it, and a Duration finishing at this Clean-up IS a legal Scheme target (pinned by `test_scheme_topdecks_the_finishing_duration_not_the_one_just_played`). Pinned by `test_villa_ends_a_buy_phase_and_only_the_last_one_is_final` and `test_a_scheme_is_not_topdecked_by_a_villa_mid_turn`. The remaining half — a card that discards an Action from play mid-turn — still does not exist. |
| B8 | **Donate (2021)** resolves "at the start of your next turn, BEFORE any other start-of-turn abilities" | It joins the same start-of-turn ability POOL as everything else, so with a second ability pending the player CHOOSES the order | The pool is a superset of the required behaviour — resolving Donate first is always available and is what a player wants (it is why the 2021 version exists) — so this only diverges if they deliberately pick something else first. Honouring the "before" strictly would mean a second, privileged start-of-turn queue for one Event; the pool exists precisely so that concurrent abilities are the player's call (p23 §2). Revisit if a later set adds another ability with a stated precedence. Pinned by `test_donate_rebuilds_your_deck_at_the_start_of_your_next_turn`. |
| B2 | Deck and discard **counts** are owner-only officially | Shown to everyone | A digital-port convenience, consistent with showing live VP. Recorded in the original plan §6. |
| B3 | A **cost read for a "remodel"** should be read at the moment it is used | Develop / Farmland / Trader capture the trashed card's cost **before** the trash resolves | Only observable if trashing a card can change costs mid-resolution; nothing in the 139-card pool does. Revisit when a cost-changing on-trash card lands. |
| B5 | **Stop-moving rule: a card that moved away and BACK is still lost track of** (wiki Stop moving rule; compendium p26 Example 6) | `find_card_zone` is PRESENCE-based — it can't tell "still there" from "left and returned", so a returned card would wrongly be movable/playable. **The IN-PLAY half is now exact** (`continuously_in_play`); the other zones are still presence-based | **PH. 9 IS WHERE THIS STOPPED BEING UNREACHABLE, exactly as the row predicted.** Scepter replays "a non-Command Action card you played this turn THAT'S STILL IN PLAY", and "'still in play' means the Action card can't have left play after you played it, even if it has entered play again … if you play a Duplicate or Royal Carriage and call it the same turn, you still can't replay it with Scepter" (Scepter 5). A called Reserve is the one thing in the pool that leaves play and returns, so `to_tavern` now records the departure in `turn_ctx["left_play"]` and `continuously_in_play` subtracts it — a MULTISET, so two Royal Carriages with one called still leave one legal target. It is the per-window counter this row asked for, scoped to the one zone that can round-trip; the general fix is still open, and the next card that round-trips a DIFFERENT zone owes it. Found by the ph.-9 cross-set batch, pinned by `test_scepter_may_not_replay_a_card_that_left_play_and_came_back`. |
| ~~B6~~ | ~~**Coffers may be spent "even in the middle of resolving an ability"**~~ | **RETIRED ph. 7 — the restriction became reachable and was removed.** It was safe while every card the compendium names for mid-ability spending (Black Market, Capital City, Diadem, Fortune, **Storyteller**) was one we didn't ship. Adventures ships Storyteller, which pays your whole money pool for cards, and the compendium says outright that you may spend Coffers in the middle of resolving it. `spendable()` now allows it; what replaced the restriction is narrower and is about the ACTOR — while a frame is open only the player it belongs to may act, so an open OPPONENT decision still blocks you. Three places had to agree or the move is offered and then refused (the reader, `legal_moves`, and `apply_move`'s pending gate). Pinned by `test_coffers_may_be_spent_in_the_middle_of_resolving_an_ability` + `test_you_still_cannot_spend_while_an_OPPONENT_is_deciding`. | — |
| B9 | **The 2025 Duration rule**: "the future effects of a played Duration STOP if the card fails to be in play" | Not implemented — a Duration's registered fx run at the next turn start whether or not the card survived | Reachable for the first time in ph. 9: Improve can trash a Cargo Ship out of play at Clean-up, and Cargo Ship 5 says the card set aside on it "would stay set aside for the rest of the game". Ours returns it to hand next turn — a strictly kinder outcome, and the alternative is a card permanently stranded outside every zone the census counts (which is its own correctness question). The general fix is a live "is my card still in play" check on every fx at `_start_of_turn`, which touches every Duration in the game; the payoff is one corner of one card pairing. Revisit when a set makes a Duration's death routine rather than an accident. Pinned by `test_a_cargo_ship_still_catches_the_card_improve_gained_from_remodelling_it`. |
| B10 | **Star Chart's pick at a shuffle that happens MID-ABILITY** | Honoured in full at the Clean-up hand draw and at whole-deck shuffles (`final_draw`, `shuffle_into_deck`); a shuffle inside an ability that continues afterwards shuffles uniformly and LOGS `star_chart_skip` | The pick is a real decision ("you MAY look through the cards … and keep one aside"), and a decision cannot be inserted into a synchronous `draw()` whose caller expects the cards back — that needs the CPS rewrite of ~100 draw sites the ledger already schedules for the next "when shuffling" consumer (Stash, ph. 15). The two honoured cases are where the card is actually used and where the choice set is knowable. **It is never silent** (the lose-track discipline): the skip is logged, so a player cannot mistake it for a trigger that failed. Pinned by `test_a_mid_ability_shuffle_skips_the_pick_and_says_so`. |
| B11 | **Horn with TWO Border Guards discarded in one Clean-up batch** | The second consumer joins the pool and its stage silently no-ops rather than prompting | "You may only put ONE Border Guard onto your deck each turn with Horn", so the second offer could never do anything — but the once-per-turn flag is only false at the moment the batch is collected, so both consumers join. Same shape as B7's double Urchin, same cause (zones hold names, the pool is collected before either resolves), and the same cost: one dead option in a prompt in the rare double-Border-Guard turn. Pinned by `test_the_horn_topdecks_a_discarded_border_guard_once_per_turn`. |
| B7 | **Urchin's before-play ability with TWO Urchins in play** | The offer opens ONCE per Attack played, not once per Urchin | Zones hold NAMES, so two copies of one card are only a count — the pool would have to carry per-copy identity to offer two trashes. The trigger correctly fires when the played Attack IS an Urchin and a second one is on the table (that second copy is "another Attack card"), and correctly does NOT fire on a throne-room replay. Costs one Mercenary in the rare double-Urchin turn. Pinned by `test_urchin_does_not_trigger_on_a_throne_roomed_replay_of_itself`. |
| ~~B4~~ | ~~Concurrent same-player abilities: the player chooses resolution order (p23 §2)~~ | **RETIRED — all four phases of the ability pool shipped.** Start-of-turn duration fx (1), every emit-driven event (2), multi-card discard/trash batches via `emit_batch` (3 — `test_batch_discard_reactions_are_the_players_choice_not_click_order`), and turn_start reactions folded into the same pool as the fx (4 — `test_turn_start_reaction_and_duration_fx_share_one_pool`: a Clerk and a Wharf are one choice, and the cross-player park order is current-player-first per p23 §3, where the old separate emit let reactions cut ahead). | — |

**C. Settled — do NOT relitigate** (kept because each cost real time to establish)

- **Off-turn bonuses EVAPORATE**, they are not banked: "on another player's turn you always start
  with empty pools" (compendium pp. 48–49, which names Nomads and Trail explicitly). Independently
  confirmed by the phase-3 audit.
- **"Cheaper" is STRICT** (`cost_lt`), not "up to" — Border Village, Berserker, Haggler.
- **First discard, THEN put cards back** — see `discard_then_putback`. Four cards had this
  backwards; it is not a matter of taste.
- **Highway is turn-scoped** (`turn_ctx["bridges"]`), not while-in-play. The 1E card was the
  other way; the roadmap described the 1E card for a while.
- **Discarding two Trails offers only ONE of them when the first one's draw shuffles** — and that
  is CORRECT, not a missed trigger. Playing Trail #1 draws; on an empty deck the draw shuffles the
  discard pile — Trail #2 with it — into the deck, and "cards that are lost track of can't be
  played", so the second offer never opens. The compendium walks through this very sequence in the
  Witch's Hut ruling (p168). Reported from a real game (GQVIQY) and confirmed against the live save.
  The actual defect was that it happened in SILENCE, so every lose-track guard now logs `lost_track`.
  Pinned both ways: `test_playing_the_first_discarded_trail_can_lose_track_of_the_second` plus a
  control with a deep deck where both Trails ARE offered (without it, a Trail trigger that simply
  stopped firing would pass).
- **Overpay is a WHEN-GAIN ability, not a when-buy one** (2022 retiming). That is why Herald may
  put the just-bought Herald back on its own deck, and why Infirmary plays a card that has
  already been gained. Any compendium example describing the when-buy order is the old version.
- **"In games using this" binds the SUPPLY, not the owner** — Footpad's draw applies to every
  player, in anyone's Action phase, with nobody owning a copy.
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
`dur_setup` never ships. ph. 6H's three new keys are PUBLIC and ship as-is — `landscapes` (they
sit face up on the table), every seat's `tavern` (mat contents are face UP, unlike the Native
Village mat) and every seat's `tokens` — listed here because build-not-filter means a new key's
publicity is a decision somebody made, and `test_view_wire` asserts all three against the
payloads a REAL room sent. Everything reveals at game over.

**The lobby History line carries every player's score** (`Won vs Bot 1  31–12`), matching CoC's.
`list_user_history` ships `standings` — seat-ordered, YOU FIRST, `{name, vp, you, won}` per player —
alongside the older `your_vp`/`scores`. The pid-derived list exists because the legacy `scores` map
is keyed by display NAME, so two players sharing one collapse into a single entry and the line would
show a wrong score; the old fields stay only for bundles cached before this shipped. The client
renders nothing rather than a partial line if any score is missing.

**The log renders CHRONOLOGICALLY** — oldest at the top, newest appended at the bottom, view
auto-scrolled to follow it (and pinned to the bottom on entering a game). It reversed to
newest-first until 2026-08; the ordering matters because sub-effects INDENT under the play that
caused them (`d` depth), and newest-first put every effect ABOVE its own cause. Scrolling up to
re-read a turn isn't yanked away by the opponent's next move — but **"the reader scrolled up"
must mean a scroll THE READER CAUSED, and a position-only test cannot say that.** The list
renders only the newest 200 lines, so past 200 entries every turn EVICTS lines off the top, and
Chrome/Firefox **scroll anchoring** then moves `scrollTop` on its own to hold the visible text
still. Read as intent, that latched the log in place for the rest of the game — and only on a
PC, because iOS Safari implements no scroll anchoring, which is exactly why this survived the
mobile autoscroll fix. So: reaching the bottom always re-arms, and only a scroll inside a real
gesture window (wheel / pointerdown / touchmove on the log, 1.5s for inertia) may un-arm.
`screens.mjs` pins it by firing a genuine no-gesture scroll and asserting the log still follows
(non-vacuous — it fails against the position-only version). **The brightened line and the
slide-in animation key off `:last-child`** — they were `:first-child` under the old order, so
flipping without moving them highlights the OLDEST line forever. The other four games are still
newest-first. `screens.mjs` pins the order by asserting the on-screen lines before a BUY are a
PREFIX of the lines after it (a buy always logs; the phase-change click renders nothing, which made
an earlier version of this check deal-dependent and flaky).

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

## The bots (`bot.py` + `bot_traits`/`bot_decisions`/`bot_endgame`/`bot_plan`/`bot_champion`)

**Shipped ladder** (`main.AI_DIFFICULTIES`, persisted per room; an unknown value coerces to
`DEFAULT_DIFFICULTY`, which is how the ladder grows without a migration):
`easy`/`normal`/`hard` (all still the one random-legal bot) · **`bmplus` (default)**.

Full campaign, every number, and the negative results: `docs/ai-research-log.md`, session
2026-07-31. Distilled strategy corpus: `.claude-plans/dontminion-bot-ladder.md`.

**PLAIN `bigmoney` WAS RETIRED AS AN OPPONENT (2026-08-04) BUT NOT DELETED.** It is a strict
SUBSET of bmplus — the same buy ladder minus the terminal, the Colony rungs and the endgame —
which bmplus beats **0.77** (base) / **0.73** (all sets), so offering it only ever added a choice
no one should pick. It had already been dropped from the create modal; this took it out of
`AI_DIFFICULTIES`, so the server now coerces it exactly like `strategist`/`champion`.
- **Removing a tier from that tuple RETIERS LIVE GAMES**, because `load_game_to_memory` re-runs
  `_valid_difficulty` on the persisted value — the same coercion that lets the ladder grow
  without a migration also silently upgrades an in-progress room, which is precisely the "a live
  game can't be retiered by a redeploy" property the tuple exists to protect. Checked against
  prod before shipping: 27 rows, 4 on `bigmoney` and **all 4 already `over`** (a finished game's
  bot never acts again), the single in-progress game on `bmplus`. Query the DB, don't reason
  about it — and if a future removal does find live games, give the load path its own legacy set
  rather than retiering them mid-game.
- **It stays in `bot.py` as the arena's REFERENCE RUNG.** "Is bmplus still better than just
  buying money?" is the most informative gate the ladder has, the pace anchors (pure BM reaches
  4 Provinces ~turn 17) are how we know the buy ladder is faithful to the published one, and
  `choose_big_money` is the only clean harness for the shared `_want` ladder — bmplus's own buy
  path wraps it in terminal, Colony and endgame logic. `_want` itself is **live production
  code**: bmplus falls back to it for every rung it doesn't override.
- Two tests pin the split: `test_the_unshipped_tiers_are_not_offered_and_coerce_to_the_default`
  (no room can select it) and `test_bigmoney_is_still_dispatchable_for_the_arena` (`bot.choose`
  still routes the string to the LADDER — falling through to `choose_random` would turn the
  baseline into a coin flip and make every number measured against it meaningless).
- **`test_every_bot_tier_the_picker_offers_is_one_the_server_accepts`** (in `test_wire_contract.py`)
  keeps the JSX `BOTS` ids a subset of `AI_DIFFICULTIES`. This seam fails SILENTLY: an id that
  drifts out of the tuple doesn't error, it quietly seats a different bot than the player picked.
- It also cost a server test its discriminator. `test_the_room_tier_reaches_the_bot` told the
  tiers apart by "random-legal plays an Action in hand, Big Money never does" — bmplus owns
  Actions and plays them, so that probe stopped discriminating and the test would have PASSED
  while checking nothing. It now uses **$0 with an empty hand**: random takes any active move
  over ending the phase and buys a Copper/Curse, every ladder tier wants nothing below $2.
  Verified non-vacuous by breaking the scheduler's tier read and watching it fail.

**Big Money** is the classic buy ladder: Treasure and Victory only, greening on a Province-count
clock. Three things about it are load-bearing:
- **`choose` is stateless** — the scheduler re-enters it per move, so the ladder re-reads the
  CURRENT coins every call. That is sound *because* there is exactly one buy a turn: the bot buys
  no Action, so nothing in its deck ever grants a second buy and no rung needs to plan a
  follow-up. Don't add a rung that wants two buys without giving the bot turn-scoped memory.
- **All treasures go down before the ladder is read** — a buy decided mid-treasure reads the
  wrong rung.
- **Deliberate gaps, both faithful to the ladder as specified**: Colony/Platinum are not in it,
  and it plays no Actions at all. `bmplus` closes both.

**`bmplus`** = Big Money + three named skills, and **the only real opponent the game ships**: the
kingdom's best terminal off `bot_traits.BM_TERMINALS` (with the <=2-copy budget and "second copy
at ~16 cards"), the Colony/Platinum rungs, and `bot_endgame` on every buy. It also drops Big
Money's "really early: Gold at $8" quirk once the game is ending — the reference `bigmoney` keeps
it, being faithful to the published ladder.

**`BM_TERMINALS` IS MEASURED, NOT JUDGED** (`tools/bm_terminal_sweep.py`). Each candidate
plays as bmplus's forced terminal against bmplus forced to buy NO terminal, on a board of
inert filler, 25 CRN pairs - the article's own question, "is this better than just buying
money?". The no-terminal control reads exactly 0.5000 on every board, so the values share a
baseline, and **the rank IS the measured win rate x100**; a card at or below 0.5 is absent.
The hand-written table it replaced was wrong in both directions - Steward (rank 30) measured
**0.36** and Footpad (62) measured **0.28**, i.e. both were bought over a Silver and LOSING,
while Vault (58) measured 0.82 - and it was missing seven cards entirely, including
**Masquerade**, which the source article names as a Big Money opener.

Three cautions on that sweep, all learned from it:
- **It scores each card in ISOLATION against a common baseline**, while the rank is used to
  choose BETWEEN cards on a board holding several. Good proxy, not a proof; re-run
  head-to-head if a pairing looks wrong. Ranks within ~10 points are inside the noise band
  (n=50 each), so don't pin an ordering that close in a test.
- **It OVERRATES attacks**, because the opponent it beats up has no terminal to defend with.
  Corsair measured 0.80 that way and its MIRROR is degenerate (below).
- Aggregate gates dilute it to nothing: new table vs old reads 0.5050 (n.s.) across random
  boards, because **61% of boards pick the same card either way**; restricted to the 39%
  where the pick actually changes it reads 0.5242 (still n.s. at n=310). The per-card adds
  and drops are individually significant; the re-ordering among already-good cards is not.

**TERMINAL QUANTITIES ARE MEASURED TOO** (`tools/bm_quantity_sweep.py`). How many copies,
and when the extra one is allowed, were the article's rules of thumb. Most survived:

- **cap 2 stands.** Capping at 1, 3 or 4 all measured BELOW it on random boards
  (0.458 / 0.446 / 0.446).
- **the deck>=16 gate stands, and its challenger is a cautionary tale.** deck>=12 read
  0.550 (random, n=120) and 0.545 (colony, n=100) - two independent samples agreeing - and
  then **collapsed to 0.5050 at n=400**. Textbook regression to the mean. Confirm a
  promising arm at higher n BEFORE shipping it.
- **longer games do want slightly more, but not enough to act on:** cap 3 improves from
  0.446 on random boards to 0.508 on COLONY boards. Still n.s. If revisited, that knob
  should key on the Colony pile rather than being global.

`TERMINAL_CAPS` holds the per-card exceptions, each measured at n=120 on a board where that
card is the only terminal: **Sea Witch 3** (cap3 0.5917 sig; cap1 0.2958 sig), Council Room
1 (2nd copy 0.4042 sig), Magnate 1 (0.4208 n.s., point estimate agrees), and **Witch's Hut
back to 2** - it was hand-listed as single-copy and allowing a second measures **0.6000**,
so that exception was simply wrong. Margrave measured 0.3833 for a third, which the default
cap already blocks.

**THE MIRROR CAVEAT (user-raised, and it checks out).** A cap sweep pits cap-N against
cap-M with BOTH seats buying the same card, so a junking attack is measured in a mutual
curse war - both decks clogged, both racing the same 10-card Curse pile. Sea Witch's third
copy is worth **+0.100 in that mirror but only +0.028 against a strong non-junking
opponent** (and vs pure money the comparison saturates entirely at ~99% either way). It is
never harmful, so it ships, but it is NOT a general "buy three terminals" result. **Any
future quantity or attack measurement owes the same asymmetric check** - this is the same
confound that made Corsair look like a 0.80 card while its mirror could not terminate.

Combined gate for the cap change, restricted to boards whose chosen terminal is affected:
0.5354 (n.s., n=240) - directionally positive, consistent with the per-card results, and
diluted for the usual reason (the cap only binds once a second or third copy is affordable).

**THE STALL BREAKER (`bot_endgame.STALL_TURNS`) - a game that cannot end is worse than one
someone loses.** Two bots both refusing to end a game they would lose is a deadlock with no
exit, and it is reachable: on a Corsair board each side trashes the other's first Silver or
Gold every turn, so neither ever reaches $8 again - measured, the pair ran **4,448 turns**
and never finished, with Estates and Duchies gone and only Curse (10) and Copper (46)
affordable. Past turn 60 the refusal stops applying, and because no single buy ended anything
in that position the breaker also **PILEDRIVES**: it buys down the shallowest affordable pile
(never Copper - 46 deep and always affordable, so it would win that comparison forever) until
a third pile empties. Seed 43 now ends on turn 35. Termination soak: 150 boards across all
seven expansions, longest game 38 turns, zero failures.

**Alchemy contributes no BM terminals, and that is correct, not an omission** - every
Alchemy card costs a Potion, and this tier buys none. `_wants_terminal` checks
`engine.potion_cost` explicitly: `cost()` returns only the COIN component, so a Golem reads
as $4 and looked affordable at $4. Naming a card it could not pay for made the bot END ITS
TURN buying nothing; `_buy_or_fall_back` now drops to the money ladder whenever the wanted
pile is not actually legal (a Potion cost, a buy_gate, an emptied pile).

**COLONY GAMES ARE A DIFFERENT ECONOMY, and the clock is what matters.** The density a deck
needs rises 1.6 -> 2.2, and the pile the game ends on is the COLONY pile — but the plain ladder
keys every green threshold to the Province count, so 2 Colonies left with 8 Provinces untouched
reads as "no urgency" while the game ends underneath. `COLONY_POLICY` (shipped: `v3`) fixes
both halves, and `_colony_green` is consulted **before** `_colony_rungs` — checked after it, a
$9 hand with one Colony left still bought a Platinum, i.e. economy the game would end before
the deck ever drew. Measured on 120 Colony-only boards, 240 CRN games each, mirror 0.5000:

| policy | change | vs the old policy |
|---|---|---|
| v2 | $8 -> Gold while Colonies are deep | 0.5312 (n.s.) |
| v4 | Colony-keyed greening clock only | 0.5896 **significant** |
| **v3** | **both — SHIPPED** | **0.6562 significant** (0.6687 on a fresh 80-board sample) |

The clock is the lever; the $8 rung adds a little and never hurts (v3 vs v4 = 0.5188, n.s.).
`_COLONY_GREEN_AT = 4` is a swept interior optimum (2/3 = 0.66, **4 = 0.68**, 5 = 0.63,
6 = 0.59). **Non-Colony play is untouched by construction** — every path is gated on
`game["colony"]`, verified move-for-move identical to the old policy across 40 non-Colony
boards. Variants stay reachable as `bmplus:<policy>` for re-measurement (arena/tests only).

**`bot_decisions.decide` replaces `engine.sample_decision` for every tier above `random`**, and is
the cheapest strength in the ladder (**0.62** on the full card pool). Two value scales, kept
separate on purpose — `hand_value` (worth for the coming turn; green is 0) and `deck_value`
(worth of owning it; green flips once the game is ending). Conflating them is the classic bug: a
Province is the best card you can own and the most useless one in hand. **Every branch falls
through to `sample_decision` and answers are re-validated (`_clamp`)**, because this sits behind
the scheduler's guaranteed turn-finisher — a policy bug must degrade to legal-but-silly, never to
rejected.

**`bot_traits` is half derived, half REVIEWED.** Derived (villages/drawers/cantrips) classify
themselves from card text the day a set ships, like `cards.grants`. The rest cannot be derived —
"trash up to 4" and "trash the top card of their deck" read identically to a regex — so they are
hand-tagged, and **`test_every_kingdom_card_is_reviewed` fails on any kingdom card missing from
`REVIEWED`. Every expansion phase owes its cards to those tables.** Two traits exist because
their absence produced measured disasters: `PILE_GAINERS` (Bureaucrat "gains a Silver" is not a
pile-drainer, and counting it fired a Gardens rush on boards with no rush) and `DRAW_TO_X`
(Library prints no "+N Cards", so a text-derived classifier cannot see the board's best drawer).

**`tools/bot_arena.py` is the gate.** CRN-paired: each pair plays one seed twice with the tiers
swapped between seats, and **the rng is keyed on the SEAT, never the tier**, so a tier against
itself produces two byte-identical games and `--mirror` reads exactly 0.5000. Anything else means
the harness leaked state and every number it printed is suspect. Ship criterion for a new rung:
>= 0.60 against the rung below, plus the pace anchors (pure BM reaches 4 Provinces ~turn 17,
BM+Smithy ~14 — ours read 16.3 and 15.3, which is how we know the ladder is faithful).

### NOT shipped — built, measured, and beaten by `bmplus` (do not relitigate as-is)

`bigmoney`, `strategist` and `champion` exist in `bot.py` behind difficulty strings **the server
refuses** (`_valid_difficulty` coerces them), pinned by a test. They are the research harness,
not opponents. `bigmoney` is here for a different reason from the other two — not a failed
experiment but a RETIRED one, kept as the measurement baseline (above).

- **`strategist` (archetype board-read) = 0.35 vs bmplus.** Engine 0.231, minion 0.237,
  cursing-money 0.381, rush 0.000; even its plain money plan reads 0.4667 over 120 games. This is
  the corpus's own "a simple engine loses to Big Money", reproduced from the inside.
- **`champion` (kingdom plan tournament + determinized rollout buys) = a wash, at ~160x the
  cost.** An oracle picking the best hand-written plan per board only reaches ~0.596 (optimistic)
  and picks plain money on 45 of 60 boards, so archetype selection is a small lever by
  construction.
- **The Rust simulation core was NOT built, on purpose.** Its justification is making rollout
  search deep enough to pay, and that premise is testable in Python first. The measured ladder
  (champion vs bmplus, n=20 per rung): **4 rollouts 0.250 | 16 = 0.300 | 64 = 0.425** — a real
  upward trend, but still losing, and walking toward parity rather than past it. The mechanism:
  **the rollouts play `bmplus`, so the search asks "how does this end if both sides play Big
  Money" — its ceiling is the rollout POLICY, not sims/sec.** Porting 139 cards, plus a recurring
  tax for ~13 more planned sets, to buy depth for a search that converges on a wash is the trade
  this campaign declined. Rust becomes obvious the moment a better rollout policy or
  action-phase search shows a rollout-count trend that crosses 0.5.

Two harness bugs worth remembering, both of which look like "the search is weak": a "buy nothing"
candidate that never ends the phase is really "let a fresh policy decide" and beats every real
buy; and UNPAIRED rollouts put more noise on the estimate than the gap between the options
(same buy, three batches of 12: 0.417 / 0.167 / 0.250). Rollouts are CRN-paired now. Also:
**read tunable constants at CALL time** — `rollouts=ROLLOUTS` as a default argument binds once at
def time, so a sweep patching the module constant silently measured one depth three times.

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

**Card rules text is rendered per face SIZE, two ways.** Large faces (hand, the `cardInfo`/kingdom
modals) size text off the length-tiered `.dm-text-{l,xl,xxl}` CSS clamps. **Supply piles opt in
with `<DmCardFace body>`**, which renders `FitBodyText` instead: it MEASURES the real box and fills
the text within a 10-16px band (`BODY_MIN_PX`/`BODY_MAX_PX`), truncating with a trailing "…" when
even the floor won't fit — press/right-click (or the face's `title`) reads the full card. The 56px
in-play/hand/mat faces stay text-free — they are `small` but never pass `body`, so the one-size
in-play rule is unaffected. No wire change: `card.text` is already on the client (`/catalog`), so
`test_wire_contract.py` is untouched. `screens.mjs` pins that supply faces render fitted text, that
the band holds (short cards capped, nothing overflows), and that a face truncates IFF its full rule
can't fit at the floor. **Truncation is reached at ~≤130px cards — including the 1440 two-column
laptop layout, where the 340px sidebar squeezes kingdom piles to the ~88px floor — not just phones.**

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

**…and the gesture is NOT card-only — the detail modal answers for everything on the table.** A
Dominion board is not only cards, and every other thing on it used to be unreadable: an Event's
text is CLIPPED by its own face, a Landmark is never bought so nothing ever opened it, the mats
carried a `title` tooltip that touch cannot see, and an **Artifact nobody has taken yet appears
NOWHERE on the board at all** — Lantern and Horn existed in the rules and in no pixel. So
`useCardInfoGesture` is now worn by the landscapes (`DmLandscape`), the mat chips (`DmMatChip`),
and every badge, token and resource counter (`DmChip`), and the modal's state is a DESCRIPTOR —
`{kind:"card"|"landscape"|"thing", …}` — rendered by one `renderInfoModal` with three left-hand
columns (a card face / a wide landscape face / an emblem) and identical chrome. Three things are
load-bearing:
- **`DmLandscape` and `DmChip` are COMPONENTS, not render helpers.** They call a hook, and
  `renderLandscape` is invoked from a `.map` — a hook there is a rules-of-hooks violation. Any
  future not-a-card thing goes through one of them for the same reason.
- **A `DmChip` may contain BUTTONS** (the Coffers/Villagers/Debt counters carry their spend
  controls), so its plain click is gated on `!e.target.closest("button")` and the hold's
  `onClickCapture` swallow is what stops a press-and-hold ALSO spending.
- **The rules text for a mat / token / counter lives in `THINGS`, in the frontend**, because the
  server has no table for it (`cards.py` has CARDS, LANDSCAPES and ARTIFACTS — a mat is none of
  those). An Artifact's own text still comes from `/catalog`; the `THINGS.artifact` entry adds
  only the part no card explains, i.e. what an Artifact IS. Same for `LANDSCAPE_BLURB`: what a
  KIND of landscape is, as opposed to what one particular Event does.

**The Kingdom browser shows what the board can't: the landscapes and the Artifacts.** Events,
Projects and Landmarks are dealt WITH the kingdom, so they belong in the thing that calls itself
"this game's Kingdom" — grouped by kind (`landscapeGroups`, ordered by `KIND_ORDER`, headed by
`kindPlural`, so a set that adds Ways or Traits gets its section free), each section led by its
`LANDSCAPE_BLURB`, and each face `readOnly` — a click there READS the Event, it must never spend a
Buy from behind an open modal. Artifacts follow, held or not. `screens.mjs`'s `dmInfoModal` block
pins all of it, and derives the expected Artifact roster from the DEALT kingdom (the
`cards.ARTIFACTS` `by` column, inverted) rather than hardcoding one — it re-deals up to 8 times to
reach a board with both a landscape and an Artifact bearer, and FAILS rather than skipping if it
never does (Renaissance-only makes that ~1e-8).

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
- **It is REJECTION SAMPLING, and that is the whole point.** Deal an ordinary random 10, re-deal
  until it satisfies every checked requirement. The output is therefore the normal kingdom
  distribution CONDITIONED on "at least one of each" — the option deletes the boards with none of a
  checked bonus and changes nothing else. **Do not "optimise" this into constructing the board**
  (force one qualifying card per requirement, fill the rest): that guarantees three DIFFERENT
  qualifying cards when all three are ticked and skews the game badly — measured, it moved the mean
  village count 1.58 → 1.95 and cut exactly-one-village boards from 57% to 35%. It was the first
  implementation and was replaced on that measurement. `test_requirements_preserve_the_natural_
  distribution` compares the dealer against an independently rejection-sampled reference and fails
  on the constructive version; `test_requirements_do_not_reserve_a_slot_each` pins that one card
  doing double duty is still common.
- Accept rates are comfortable (~0.55 on the full pool, ~0.46 on Base alone with all three), so the
  500-try cap is unreachable in practice; an unsatisfiable POOL is detected up front instead, so it
  fails with a usable message rather than after 500 doomed re-deals.
- **`deal_kingdom` with nothing required is EXACTLY `rng.sample(pool, 10)`** — same rng call
  sequence, so every existing seed still deals the same board (the determinism soak and every
  forced-kingdom test rest on that). Requirements are read in `REQUIREMENT_ORDER`, never the order
  the client sent them, so the deal stays reproducible from (seed, options).
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

`test_cards_adventures_a/b.py` (the ph. 7 batches — half A is the cards whose interest is
their own play ability plus the three seat tokens, half B the Reserves and their call windows,
the Traveller chains, the 20 Events, the pile tokens and Inheritance),
`test_landscapes.py` (THE LANDSCAPE KERNEL — every ph. 6H seam, none of which a shipped card
consumes yet: the setup dealer and its no-entropy proof, `buy_landscape` and its gates, the
enumerator/handler agreement sweep, the Tavern mat and calling, `before_play`/`action_resolved`,
tokens and the `-cost` hook, the bots, and a full random game on a landscape board),
`test_cards_darkages_a/b.py` (the ph. 6 batches — half A is the 20 cards whose interest is
their own play ability, half B the trash theme, the attacks, the two shuffled piles and all
three setup rules), `test_cards_cornucopia_a/b.py` (the ph. 4 batches, incl. the Coffers and
overpay kernels),
`test_piles.py` (THE PILE MODEL — every ph. 3H seam, none of which a shipped card consumes yet),
`test_engine.py` (kernel + exemplars + redaction), `test_soak.py` (per-move card-conservation
census over full random games — the Duel 25-token analog — plus never-strand, mirror-sync, vp
recompute, JSON-safety, per-move progress, termination, determinism), `test_cards.py` (WP1
data), per-batch `test_cards_*.py`, `test_migrate.py` (every historical save shape),
`test_server.py`/`test_ws_auth.py`/`test_view_wire.py` (WP5). Any test module driving the WS
loop MUST reset `core.rooms._ws_connect_limiter` per test (repo rule).
