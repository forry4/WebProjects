# Dontminion (Dominion, Base 2E + Intrigue 2E) — package notes

2–4 players. Mounted at `/dontminion`. Plan + full domain spec:
`.claude-plans/i-want-to-add-luminous-pebble.md`. Rules source of truth: the Knutsen
compendium `C:\Users\Forrest\Downloads\Dominion_CompleteRules_v11.1.pdf` (ch. VII = per-card
rulings); card texts cross-checked against dominionstrategy.com/card-lists/.

## Layout

| File | Role |
|---|---|
| `cards.py` | static data ONLY (schema below); `DATA_COMPLETE` sentinel; `BANDIT_VICTIM_CHOOSES` ruling |
| `engine.py` | the kernel: rules, frames, attack window, validation, scoring, `player_view` |
| `effects_core.py` | WP2-owned exemplars: Smithy, Village, Moat, Militia, Witch, Throne Room |
| `effects_base_a/b.py`, `effects_intrigue_a/b.py` | card batches (each owns ONLY its module + its test file) |
| `effects.py` | merges the registries; duplicate registration raises |
| `bot.py` | random-legal bot (all difficulty tiers, v1) |
| `main.py` | FastAPI sub-app: rooms/WS/persistence/multi-bot scheduler |
| `tests/` | engine, soak, per-batch card tests, server, ws-auth, wire-redaction |

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
`add_actions/add_buys/add_coins` ·
`opponents(game,pid)` (turn order) · `count_empty_piles` ·
`attack_opponents(game,pid,card,per_opp_stage,data=None,immune=None)` (a card whose attack part
runs in a LATER stage — Minion, Replace — must capture `list(game["_atk_immune"])` into its frame
data during on_play and pass it back via `immune=`) · `_log(game,pid,event,
private_to=None,**kw)`. Turn counters (`game["turn_ctx"]["bridges"/"merchants"]`) are incremented
directly by the owning card's effect.

**Registration** — each effects module exports exactly:
```python
EFFECTS: {card_name: on_play(game, pid)}
STAGES:  {(card_name, stage): fn(game, pid, frame, choice)}   # choice None for auto frames
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
- **Turn undo is gated on HIDDEN INFORMATION, not on which actions you took** (the Duel model):
  `_arm_undo` snapshots the whole game at turn start (`turn_undo`, stripped from `player_view` —
  it holds every hidden zone; `turn_revealed` DOES ship, driving the client button);
  `_mark_revealed` fires on draw / look_top / reveal / pass_card and on any decision resolved by
  a non-turn player. `{"type":"undo_turn"}` is handled BEFORE the pending gate (an unrevealed
  Militia can be taken back before the opponent answers) and `legal_moves` never offers it (keeps
  the bot honest). Treasures, buys, end_phase, and no-reveal actions (Festival, Chapel, Workshop…)
  are all undoable; anything that draws or reveals is not.

## Hidden information / wire view

`player_view` BUILDS the view (build-not-filter): deck order never exists on the wire (counts
only — showing deck/discard counts to everyone is a documented convenience; officially they're
not open info), hands only to their owner, discard = top + count, `aside` = count, raw `pending`
replaced by `pending_view` (actor: kind+card+constraint; others: card + waiting_on), log entries
honor `private_to`, `rng_state`/`seed` popped. Everything reveals at game over. Live VP totals
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
Every tier is `bot.choose` (random-legal) in v1 — no executor, nothing heavy under ROOM_LOCK; the
tier is validated + persisted anyway so a future strength ladder needs no migration. All entropy
runs through `_new_rng()` (the test seam). vs-AI rooms start at create (never "open"); friend
rooms are host-started with shuffled seat order.

## Frontend (Dontminion.jsx)

Peer contract `{myId, authUser, onExit}`; root class `.dm` on every branch (the screens.mjs
marker). Because engine constraints are generic, the decision UI is SIX renderers over
`game.pending_view` — no per-card frontend code anywhere; everyone else gets a
"Waiting for <name>" bar. Cards are text-only faces (no art) on the shared `.card` frame via
`--card-w/--card-h`. The create modal's expansion picker is a game-local `DmChecks` (the shared
kit has no multi-select; promote it if a second game needs one). Supply affordance mirrors
`engine.cost` via `turn_ctx.bridges` — display only, the server stays authoritative.

## Tests

`test_engine.py` (kernel + exemplars + redaction), `test_soak.py` (per-move card-conservation
census over full random games — the Duel 25-token analog — plus never-strand, mirror-sync, vp
recompute, JSON-safety, termination, determinism), `test_cards.py` (WP1 data), per-batch
`test_cards_*.py`, `test_server.py`/`test_ws_auth.py`/`test_view_wire.py` (WP5). Any test module
driving the WS loop MUST reset `core.rooms._ws_connect_limiter` per test (repo rule).
