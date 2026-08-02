# Dontminion — full-catalog expansion roadmap

Goal (user directive 2026-07-29): every Dominion expansion, faithful to the Knutsen
compendium v11.1 (`C:\Users\Forrest\Downloads\Dominion_CompleteRules_v11.1.pdf`).
Scale: 452 kingdom piles + 193 landscape cards across 16 sets. This lands in PHASES —
each phase = the kernel mechanics that set needs + its complete card roster + tests,
shipped only when whole (a partial set would poison the random-kingdom picker).

Rules of the road (same as the original build): 2nd-edition rosters where they exist;
kernel changes are serial and stop-the-line; card batches parallelize against the frozen
API; every set's cards verified against compendium ch. VII (current texts + rulings).

| Phase | Set (edition) | New kernel systems needed | Status |
|---|---|---|---|
| 1 | **Seaside 2E** (27) | Durations, turn-start frames, cross-player watchers, gain reactions, protection, mats, duration set-aside, extra turns, interruptible clean-up | **SHIPPED** 2026-07-30 + audited |
| 2 | **Prosperity 2E** (25 + Platinum/Colony) | VP tokens, would-gain protocol, via_buy, buy gates, dynamic self-costs, game-aware type queries (Charlatan), treasure-throne, Platinum/Colony setup | **SHIPPED** 2026-07-30 + audited |
| 3 | **Hinterlands 2E** (26) | `discard` emit, unfiltered offers, self-trigger context, registry-driven attack reactions + reaction-that-plays-itself (Guard Dog), attack-typed Treasures opening the window (Cauldron), plays from non-hand zones + lose-track (Trail), actor-aware resource pools, coin floor (Souk), `exchange` (Trader), `shuffle_into_deck` (Inn), `cost_lt`, all-seats clean-up sweep, `discard_then_putback` | **SHIPPED** 2026-07-30 + audited |
| 3H | **HARDENING: the pile & source model** (no new cards) | see below — pays two ledger rows at once, standalone, behavior-preserving | **SHIPPED** 2026-07-31 |
| 4 | **Cornucopia & Guilds 2E** (26 + 6 Rewards) | Coffers (spendable counter + UI counters row + generic `spend` move), overpay-on-buy, differing-names, Rewards non-supply pile (rode 3H), Young Witch's Bane + Ferryman's extra pile, Footpad's game rule, per-seat set-asides + start-of-turn abilities | **SHIPPED** 2026-08-01 + audited |
| 5 | **Alchemy** (11 of 12 + Potion) | cost VECTOR dimension 1 (Potion) — landed inside cost_le/cost_eq/cost_lt + the new `*_card` forms; Potion production/payment in the buy flow. ⚠ **POSSESSION DEFERRED** (user decision) — see `cards.DEFERRED` | **kernel + cards landed**, held out of the picker: per-card tests, cross-set batch and audit outstanding |
| 6 | Dark Ages (35 + Ruins/Shelters/Spoils/Knights) | on-trash triggers (emit exists), Shelters setup, Madman/Mercenary/Spoils non-supply (3H), Ruins + Knights ordered piles (3H), ⚠ **card identity / "play-as" system** (Band of Misfits — see ledger) | planned |
| 7 | Adventures (30 + 20 Events + Travellers) | LANDSCAPE system v1: Events (generic `buy_landscape` move + board row UI), Reserve/Tavern mat + generic `call` move, Adventures tokens on piles, exchange-on-discard (Travellers); Inheritance rides the identity system | planned |
| 8 | Empires (24 + Events + 21 Landmarks) | Debt = cost vector dimension 2 + debt-payoff in the buy flow, split piles + Castles (3H), Landmarks (scoring pipeline hook), gathering VP tokens on piles | planned |
| 9 | Renaissance (25 + 20 Projects + Artifacts) | Villagers (same shape as Coffers), Projects (landscape purchase + permanent per-player abilities), Artifacts (unique pass-around objects) | planned |
| 10 | Menagerie (30 + Events + 20 Ways) | Exile mat (+ discard-from-exile on gain), Horses non-supply (3H), Ways (alternative play modes — rides the identity system) | planned |
| 11 | Nocturne (33 + Boons/Hexes/Heirlooms) | ⚠ **BIGGEST PHASE**: Night phase (turn-structure change: phase enum, auto-advance, legal_moves, bot, undo, frontend), Boon/Hex shared decks (new persisted RNG streams + receive flow), Heirlooms setup, Spirits non-supply, Zombies start in trash, Exorcist exchange | planned |
| 12 | Allies (31 + 23 Allies) | Favors (Coffers shape), Allies (shared per-game global ability), ROTATING split piles (3H's model must support rotate) | planned |
| 13 | Plunder (40 + Loot + 15 Traits + Events) | Loot non-supply deck (3H), Traits attached to piles (per-pile modifier hook), duration-heavy (ready) | planned |
| 14 | Rising Sun (25 + 10 Prophecies + Events) | Prophecies (global countdown + sun tokens), Shadow cards (playable from inside the deck — play-surface change), Debt reuse | planned |
| 15 | Promos (11) | mostly rides earlier systems; Stash (choose position at shuffle — touches the RNG discipline), Black Market (side deck + mid-action treasure playing) | planned |

Sequencing rationale: Seaside's durations and Prosperity/Hinterlands' gain/buy triggers
are the two surfaces half the later sets assume. The **3H hardening phase** sits after
Hinterlands (which is pure bus consumption and needs none of it) and before C&G (the
first set that cannot ship without it). Landscape UI (ph. 7) is the next big FRONTEND
lift; Nocturne (ph. 11) is the biggest single phase and must not be combined with
anything else.

## Phase 3H — the pile & source model — SHIPPED 2026-07-31

`supply = {name: count}` could not represent what five later sets need, and non-supply
gain sources appear in six. One behaviour-preserving refactor paid both ledger rows with
the whole suite + soak as the net, instead of bundling the biggest schema change into
Dark Ages' 35 cards. **Full model + API: `CLAUDE.md`, "THE PILE MODEL".** What landed:

- **Pile objects** (`game["piles"]`): `face` / ORDERED `contents` / `members` / `attach`,
  covering Ruins and Knights (ph. 6), split piles + Castles (ph. 8), ROTATING piles
  (ph. 12), per-pile Traits (ph. 13) and Adventures tokens (ph. 7). Cost/type of "the
  pile" = its top card, resolved inside `cost`/`types_of`/`coins_of` so every cost rule
  the game has — and every one it grows — reaches an ordered pile for free. `contents`
  never ships (pile order is hidden info).
- **Gain sources beyond the supply**: `gain_from(game, pid, pile, dest=)` for Rewards
  (ph. 4), Spoils/Madman/Mercenary (ph. 6), Horses (ph. 10), Spirits (ph. 11), Loot
  (ph. 13), plus `return_to_pile` for the cards that go home. Non-supply piles live in
  their own count index, so they are never buyable and never count toward the game end.
- Wire compatibility held: `supply` and `costs` ship unchanged, `piles` is additive.
  SCHEMA 6 + a presence-based fill; all 17 real prod saves (v1/v2/v5) replayed forward.
  Census/soak extended; the frontend reads pile FACES instead of assuming pile==card.

**The judgement call worth keeping.** The first cut put `count` on the pile object and made
`game["supply"]` a kernel-maintained mirror. It broke 25 tests immediately — because ~110
fixtures across 16 files set `g["supply"]["Curse"] = 0` by hand, and every card batch to
come will write the same line. That is not test churn to be absorbed; it is a permanent
trap where the familiar idiom silently desyncs the model. Inverting it — the count stays
in a flat index, ORDERED piles alone keep a mirror written by two functions and asserted
by the soak — cost one extra concept and zero call sites. **Prefer the shape the codebase
already speaks; make the NEW thing carry the complexity.**

Two things only the new tests could have caught, both invisible to "the suite still
passes": `traits()` KeyErrors on a pile name, so `bmplus` crashed the moment a board held
an ordered pile (scheduled to surface inside the server's turn-finisher, on a live game,
in ph. 6); and `exchange` reached for `supply[card] = supply.get(card, 0) + 1`, which
would have conjured a buyable pile out of a returned card's name. A hardening phase whose
only evidence is a green suite has proved it changed nothing — which is half the job.

## Phase 3 — Hinterlands 2E: VERIFIED roster + rules findings (2026-07-30)

Roster confirmed from TWO independent sources that agree exactly: the compendium's
per-card "❖ Not included in the 2022 Second Edition" markers, and the Update Pack
contents. **26 = 17 kept + 9 new.**

- **Kept (17)**: Crossroads, Fool's Gold, Develop, Oasis, Scheme, Tunnel, Jack of All
  Trades, Spice Merchant, Trader, Cartographer, Haggler, Highway, Inn, Margrave, Stables,
  Border Village, Farmland.
- **New in 2E (9)**: Berserker, Cauldron, Guard Dog, Nomads, Souk, Trail, Weaver,
  Wheelwright, Witch's Hut.
- **Removed, do NOT implement (9)**: Cache, Duchess, Embassy, Ill-Gotten Gains, Mandarin,
  Noble Brigand, Nomad Camp, Oracle, Silk Road.

**Rules findings that change the plan** (each verified in the compendium, not taken on trust):
- **Trader is an EXCHANGE, not a would-gain replacement.** "Trader's Reaction is now a
  when-gain ability that exchanges the gained card for a Silver… Even if you exchanged it, you
  DID gain the card (and triggered any when-gain ability). You didn't gain the Silver." So it
  registers as a Watchtower-shaped hand reaction on `gain` and needs a new `exchange()`
  primitive — return to pile, take from pile, and **no `gain` emit**. The would-gain protocol
  paid in ph. 2 was built for Trader (1V) and is NOT what this card wants.
- **Haggler 2022 is a per-play `until="turn_end"` watcher** (Hoard's exact shape): "SETS UP A
  LATER ABILITY … for the rest of this turn: It triggers when you gain a card instead of when
  you buy it, but only a card that you bought… cumulative if played with a throne-room."
- **Highway needs no new counter — it IS `turn_ctx["bridges"]`.** Its current text is
  word-for-word Bridge ("This turn, cards cost $1 less"), so it reuses the existing turn-scoped
  reduction: no kernel change, no frontend change, and the cost banner stays correct.
- **Highway 2022 is NOT a `COST_MODS` card.** "The cost reduction is now caused by PLAYING
  the Highway… (Pre-2022 version:) WHILE THIS IS IN PLAY". So it is turn-scoped and
  cumulative per play, exactly Quarry's 2022 shape (`turn_ctx` counter + `engine.cost`) —
  it survives the Highway leaving play. The old roadmap row calling it "the first real
  COST_MODS consumer" described the 1E card.
- **Vault's opponent offer** (paid): the compendium's Capital City ruling under the same
  DISCARD-THEN-GET-FROM-DECK heading — "if you choose to discard 2 cards with only 1 card
  in your hand, you discard that card but do not get any +".
- **When-discard fires after the WHOLE batch** (2022 change, was one-at-a-time). The Tunnel
  ruling depends on it: discarding your hand to Minion with Tunnel + Watchtower lets you
  reveal the Tunnel, but the Watchtower has already left your hand.
- **Berserker/Cauldron/Souk/Guard Dog/Trail** each have compendium entries with real
  edge-case rulings (Cauldron counts only Actions gained AFTER it was played; Guard Dog is
  a REACTION THAT PLAYS ITSELF and may be revealed multiple times to one attack; Souk has
  VARIABLE PRODUCTION that can deduct more than it gives). Mine these per card at build.

### SOURCES OF TRUTH — and which one wins (settled 2026-07-30)

| Question | Authority |
|---|---|
| Roster / which edition a card is in | wiki chart's **Set** column (`Hinterlands, 2E` vs `, 1E`), cross-checked against the compendium's "Not included in the 2022 Second Edition" markers |
| Name, cost, types | **wiki chart** — accuracy-gated at 112/113 against our own verified cards |
| Printed card TEXT | wiki chart, **except where the compendium quotes the card** — the chart can be stale (it shows Mill as "If you do, +$2"; compendium p19 quotes the current card as "You may discard 2 cards, for +$"). Compendium wins on any conflict |
| Behaviour, timing, edge cases, version history | **compendium**, always |
| Any NUMBER | wiki chart. The compendium's coin/VP digits are inline images its text layer DROPS — never take a number from extracted PDF text |

The chart lives at `wiki.dominionstrategy.com/index.php/List_of_cards`, unreachable live (Anubis
wall on the page AND `action=raw`). Read it from the **Wayback Machine**; the newest usable
capture is **2025-10-17** (later ones archived the wall itself). Parse with the scratchpad
`parse_wiki.py`: 836 rows × 14 cols, and coin icons carry `alt="$5"` so costs read cleanly.

⚠ Our stored card texts appear to be DERIVED from this same wiki source, so a near-zero
text-diff against it is weaker evidence than it looks. The compendium sweep is the independent
axis — it is what rules out a Highway-class bug (code following a superseded version).

⚠ **EARLIER SOURCING CONSTRAINT (now solved by the chart, kept for context).** The compendium carries RULINGS,
not printed card text — Bank's own text does not appear in it — and its coin/VP digits are
inline images the text layer drops (rasterize pages to read numbers). The dominionstrategy
card lists predate all 2E rosters, the wiki is Anubis-walled, and transcription sites
refuse verbatim text on copyright. So **exact cost/types/text for the 9 new cards must come
from the physical cards or an owned digital copy**; the compendium then verifies every
behavior, threshold and version. Do not fill this gap from memory — that is risk #2 in the
original plan, and the audit step cannot catch it if the audit runs from the same memory.

## Phase 4 — Cornucopia & Guilds 2E — SHIPPED 2026-08-01

The 2024 Second Edition is a COMBINED set. **26 kingdom cards = 18 kept + 8 new**, plus 6
Rewards outside the Supply. Full build spec (roster, per-card rulings, kernel checklist):
`.claude-plans/dontminion-phase4-cornucopia-guilds.md`.

Roster verified by two independent sources that agree exactly, the same standard phase 3 used:
the compendium's 13 `❖ Not included in the 2024 Second Edition` markers, and the wiki chart's
`Cornucopia & Guilds, 1E` label — they name the same 13 (Doctor, Farming Village, Fortune
Teller, Harvest, Horse Traders, Masterpiece, Taxman, Tournament and the 5 Prizes). Every one of
the 32 shipped cards had its cost, types and overpay flag checked back against the chart
programmatically rather than by eye.

**Kernel added** (frozen in `CLAUDE.md`, "Kernel v4"): Coffers + the generic `spend` move,
overpay-on-buy as a when-gain ability, the `"game"` trigger source, per-seat set-asides and
start-of-turn abilities, `play_treasure_card`, two turn counters, three setup-chosen piles and
two computed VP kinds. Every one of them is a bus extension or a registry entry — no bespoke
mechanism, which is the contract phase 3 set.

**What the playbook caught this time**, each by a different step:

- **Step 4/5 (per-card tests) found two real bugs.** Hamlet and Coronet each pushed BOTH of
  their optional offers up front, so the second offer's constraint held a hand the first had
  already changed — a decision the engine then refused to apply. The soak found it as a
  `ValueError` inside `discard`; the lesson generalises: **a card with two optional offers must
  push them SEQUENTIALLY**, because a constraint is a snapshot.
- **Step 7 (the audit) found the sharper one.** Coronet queued its Treasure half from the answer
  to its Action half, so a hand with no playable Action silently lost the entire Treasure
  ability. Nothing else would have found it — the card "worked" in every test that had an
  Action to play, which is every test written from the card's own text. Re-deriving from the
  compendium ("you may play a non-Reward Action... you may play a non-Reward Treasure" — two
  independent mays) is what exposed it.
- **A third, cheaper class**: the tests kept failing on boards that also held Footpad, because
  its game-wide rule fires on the same gain and the ability pool (correctly) asks which resolves
  first. Those were test-premise errors, not defects — but they are also the evidence that the
  new `from="game"` source joins the pool like any other consumer instead of cutting ahead, so
  one of them was kept as a test on purpose.

**One judgement call recorded rather than asserted** (CLAUDE.md row A4): whether the Coffers
Butcher spends also pay their +$1 each. We said yes — the global spending rule is unconditional
and Butcher only adds a use for the count — but the compendium's phrasing can be read the other
way, so it is a pinned deviation, not a silent choice.

## Phase 5 — Alchemy: status, and the one card we did not build

**Possession is deliberately NOT implemented** (user decision, 2026-08-02, after it was scoped).
It is recorded in `cards.DEFERRED` — as DATA, not a comment — with its reason and a pointer to
`.claude-plans/dontminion-phase5-alchemy-possession-scope.md`.
`test_the_deferred_cards_are_recorded_and_still_absent` asserts that Alchemy's published roster
(12 kingdom cards) still reconciles as "what we ship + what we defer", so the hole cannot be
quietly forgotten, and the day Possession is built the test points at the counts to update.

**This breaks the roadmap's own whole-set rule on purpose.** A set is meant to ship only when
whole, because a partial set poisons the random-kingdom picker. Alchemy is therefore **held out
of `KNOWN_EXPANSIONS`** for now, so no live game can deal it — the same gate C&G sat behind
while its audit was outstanding.

### What landed

- **THE COST VECTOR.** A cost is `{coins, potions}`. The three rules from the compendium's
  POTIONS section live in `engine.py` and nowhere else:
  "up to $3" = coins ≤ 3 **and potions == 0**; "exactly $1 more" = *the same cost plus $1*, so
  the potion components must MATCH; "lower than" = no component higher and at least one lower,
  which makes `{$4,P}` and `{$5}` **incomparable**.
  The number forms (`cost_le`/`cost_eq`/`cost_lt`) took the first rule; the other two needed new
  **card-reference** forms (`cost_le_card` / `cost_eq_card` / `cost_lt_card`), because "up to $2
  more than IT" is only expressible against the card, not against a number.
- **The remodel family was migrated to them** — Remodel, Mine, Remake, Upgrade, Develop, Expand,
  Swindler, Stonemason. This is the payoff for the `cost_le`/`cost_eq` boundary introduced in
  ph. 2: the *number* call sites needed no change at all, and only the ones whose bound is a
  CARD had to move. Exactly the "thirty batch call sites" that comment promised to avoid.
- Potion production (a Potion adds to a second money pool, not to `$`), the Potion pile's setup
  rule, the buy gate on both components, `potion_costs` on the wire, and Vineyard's VP kind.
- 11 cards in `effects_alchemy.py`, green under the conservation soak on an all-Alchemy board.

### Still outstanding before it can be released

Per-card test batches, the cross-set batch, and the adversarial audit — which is where phase 4
found all three of its real bugs, so this is not a formality.

### A finding for whoever picks this up

**Alchemist and Herbalist take the half-paid "`_end_turn` is not interruptible" ledger row from
one consumer to three.** Both are implemented with the same per-play `buy_phase_end` watcher as
Scheme. For Herbalist that is faithful rather than approximate only because the candidate set
comes from `leaving_play()` — "the cards that WILL be discarded from play at this Clean-up" —
which is what correctly excludes a Duration that stays out ("if a card is not discarded…
Herbalist can't put it onto your deck"). If a future set adds a card that cares about the order
of Clean-up itself, pay the row properly instead of adding a fourth watcher.

## Structural-debt ledger (pay these ON TIME — kernel work first, stop-the-line)

| Debt | First bitten by | Pay when |
|---|---|---|
| ~~Replacement effects (would-gain)~~ **PAID ph. 2** — park/window/cancel_pending_gain, contract-tested | Trader (ph. 3) | done |
| ~~Cost comparison helpers~~ **PAID ph. 2** — cost_le/cost_eq everywhere | Alchemy/Empires | done (the vector itself lands ph. 5/8, confined to two functions) |
| ~~Client-side price math~~ **PAID post-ph. 2** — `player_view` ships `costs`; the client never re-derives | Peddler bug (found live) | done |
| ~~Undo/save bloat~~ **PAID (pre-ph. 3)** — snapshots store `_log_len` and undo truncates; measured 487 KB → 150 KB on a late-game blob, per save-write | was live | done |
| ~~Versioned save migration~~ **PAID (pre-ph. 3)** — `SCHEMA`=3 + `engine.migrate()` at load; 28 defensive gets retired; `test_migrate.py` downgrades a CURRENT game to each old shape. EVERY PHASE OWES: bump + migrate step + test | was growing | done |
| ~~Unknown-log-event fallback~~ **PAID (pre-ph. 3)** — fmtLog renders a readable fallback for events it doesn't know yet, so a new engine event is never silent | was live | done |
| ~~Vault's opponent offer is feasibility-filtered~~ **PAID (pre-ph.3)** — offered to any non-empty hand; 1 card discards 1 and draws nothing (Capital City ruling) | Tunnel's when-discard (ph. 3) | done |
| ~~No `discard` emit point~~ **PAID (pre-ph.3)** — `discard()` emits per card AFTER the whole batch (the 2022 all-at-once change the Tunnel ruling needs); Clean-up bypasses `discard()` so when-discard correctly can't fire there, pinned by a test | Tunnel/Trail/Weaver (ph. 3) | done |
| ~~`self` triggers couldn't see the emit context~~ **PAID (pre-ph.3)** — `**extra` now reaches self-trigger data, so a when-BUY-this card can tell a buy from any other gain | Farmland (ph. 3) | done |
| ~~`in_play` triggers get no SUBJECT~~ **PAID, but the premise was WRONG.** Paid for Haggler — except Haggler 2022 "SETS UP A LATER ABILITY … for the rest of this turn", i.e. Hoard's per-play `until="turn_end"` watcher, NOT an `in_play` trigger. The row described the pre-2022 card. The fix (push receives `ctx`) is kept: a trigger seeing its own event's context is the right contract and Treasury ignores it. But nothing in ph. 3 needed it — a reminder that a ledger row written from a card's OLD text schedules the wrong work | (nothing — mis-scheduled) | done, not needed |
| **HALF-PAID: `cleanup_discard` event exists, `_end_turn` is still NOT interruptible.** The event fires per in-play card before the sweep, and is deliberately separate from `discard` (Tunnel/Trail/Weaver are all "other than during a Clean-up phase" and must not see it) — but `emit` parks an AUTO FRAME and `_end_turn` never drives frames, so a consumer cannot yet MOVE the card. Scheme needs `_end_turn` restructured to resolve a decision before the sweep and before the 5-card draw | Scheme (ph. 3) | ph. 3, WITH Scheme |
| ~~Off-turn resource leak~~ **PAID ph. 3** — the kernel binds `_actor` around every effect and stage, so card code still calls `add_*` with no pid and a bonus earned on someone else's turn EVAPORATES (logged `off_turn_bonus`) instead of landing in the turn player's pool. NB the first attempt (an optional `pid=` argument) did NOT work: card code never passes one | Trail, Nomads | done |
| ~~Clean-up doesn't sweep OTHER seats' `in_play`~~ **PAID ph. 3** — every seat's table is swept at each clean-up; durations and riders protected | Guard Dog/Trail/Weaver/Berserker | done |
| ~~The put-back jumped the discard's when-discard triggers~~ **PAID ph. 3** — `discard_then_putback` encodes "first discard, THEN put cards back" ONCE; four cards (Sentry, Lookout, Rabble, Cartographer) each had their own copy and all four had it backwards | Tunnel/Trail via Cartographer — found by the CROSS-SET step, not per-set tests | done |
| ~~Non-supply gain sources~~ **PAID ph. 3H** — `gain_from` + a second count index, so "a card from the Supply" excludes them by construction rather than by remembering | Rewards (ph. 4) | done |
| ~~Pile abstraction~~ **PAID ph. 3H** — `game["piles"]`: ordered `contents` + retained `face` + `members` + `attach`; cost/type resolve through the face, the census unpacks it, the wire never sees the order | Ruins/Knights (ph. 6), scheduled early deliberately | done |
| **Move-surface trio**: ~~generic `spend`~~ **PAID ph. 4** — `{"type":"spend","what":...,"n":...}` + `spendable()` as THE reader + a counters row in the resbar; Villagers/Favors/Debt-payoff are now registry + data. Still owed: `buy_landscape` (Events/Projects), `call` (Reserves) | spend: ph. 4 · buy_landscape/call: ph. 7 | spend done · ph. 7 pre-work |
| **Card identity / "play-as"**: a physical card played AS another (Band of Misfits ph. 6, Inheritance ph. 7, Ways ph. 10, Overlord). Needs `play_card_as(game, pid, physical, as_name)` where identity-vs-physicality is explicit (types/cost read from WHICH?— the compendium's lose-track rules decide). The Charlatan `types_of` seam is the foothold | Band of Misfits (ph. 6) | ph. 6 pre-work, DESIGN reviewed against ph. 7/10 consumers before freezing |
| **`play_all_treasures` suppression must become a STATE predicate.** Today it's a static card list (`MANUAL_TREASURES` — treasures that push a decision). Highwayman negates the FIRST Treasure its victim plays, so which treasure goes first becomes a real choice and the button must not make it for them — a condition the card list cannot express, since it depends on game state and LIFTS once the negation is spent. Wanted: `autoplay_block(game, pid) -> reason \| None`, fed by both the static set and watcher-registered blocks, read by `legal_moves` + the handler + shipped in `player_view` (state-dependent ⇒ NOT `/catalog`, unlike the static set) so the button hides AND says why. Also fixes the ordering row below if the block carries an order | Highwayman (ph. 12) | ph. 12 pre-work — but build it at the FIRST set that adds an order-sensitive treasure |
| ~~Autoplay ORDER is hand order~~ **PAID (post-ph. 2)** — `AUTOPLAY_LAST` registry + a stable sort in the handler; Bank now plays after the rest ($6 → $10 on the measured hand, matching optimal play). Adding a Treasure with an ability now means choosing a bucket: manual / autoplay-last / autoplay — see CLAUDE.md | Bank (was live) | done |
| **Landscape cards** (Events/Landmarks/Projects/Ways/Traits/Prophecies/Allies) + a "global" trigger source + the board-row UI | Adventures (ph. 7) | ph. 7 kernel+UI work |
| **Scoring pipeline hook** (Landmarks add/subtract at game end beyond card VP + tokens) | Empires (ph. 8) | ph. 8 pre-work |
| **Turn structure** — Night phase breaks the action/buy enum, auto-advance, bot, undo gating, frontend phase logic | Nocturne (ph. 11) | ph. 11, sized as its own kernel campaign |
| **Shared side-decks with persisted RNG** (Boons/Hexes ph. 11, Loot ph. 13, Black Market ph. 15) — same `_make_rng/_save_rng` discipline, new streams | Nocturne (ph. 11) | ph. 11 |

Rule: when a phase's spec hits a row, the KERNEL work comes first, the row gets deleted,
and the audit agent re-runs on the phase.

## The per-phase playbook (proven on ph. 1 and ph. 2 — follow it, it catches real bugs)

1. **Spec agent** mines the compendium alone into a scratchpad spec: exact 2E roster,
   CURRENT texts, per-card rulings, pile sizes, "new engine hooks" checklist.
   ⚠ The PDF's text layer DROPS coin/VP digits (inline images) — rasterize the entries
   (PyMuPDF) and read numbers from renders; never trust memory for a threshold.
2. **Ledger pre-work**: pay every row due this phase before anything else.
3. **Kernel**: extend engine.py behind the bus ("new event name + registry entries,
   never a bespoke mechanism"); contract-test unconsumed seams; existing suite green.
4. **Freeze** the API delta in CLAUDE.md, then **two batch agents** in parallel — a
   simple half and a complex half, each owning ONLY its module-half + its test file.
   Batches report kernel gaps; the INTEGRATOR fixes them kernel-side (never accept a
   batch's private-accessor workaround — both phases produced one).
5. **Concatenate** the halves into the one `effects_<set>.py` (registry UNION, not
   last-assignment-wins). Test files stay split (their fixtures differ by design).
6. **Cross-set batch**: new mechanic × old mechanics — Throne Room/King's Court sweep,
   Watchtower/would-gain × new gains, UNDO audit (what marks revealed?), Bridge/Quarry ×
   new cost checks, save-blob compat for the previous schema.
7. **Adversarial audit agent**: re-derives every card from the compendium ONLY (never
   the spec), challenges the code, classifies BUG/EDGE/COSMETIC/DOC'D. Fix bugs, ledger
   the deferred edges, flip pinned deviations when fixed. (Found real bugs both phases:
   immunity bypass, info leak.)
8. **Gates + ship**: package suite, full repo suite, screens, smoke, e2e sanity with the
   new expansion toggled on, push, verify BOTH deploys by SHA, prod spot-check, update
   CLAUDE.md/memory/this file.
9. **Replay every REAL prod save** (Turso creds `~/.spender_turso` → `/v2/pipeline`): run
   each blob through `engine.migrate` exactly as `load_game_to_memory` does, then play it
   forward with the bot under the soak's invariants. This is NOT redundant with the suite
   — `migrate`'s input is HISTORY, not the current tree, so tests built by downgrading a
   current game cannot synthesize what prod actually holds. It caught both bugs 75f2900
   shipped: a schema stamp that didn't partition shapes (two live games would have
   KeyError'd) and a bot livelock on a no-op move (two live games stuck). ~30 lines,
   ~2 min; run it whenever the game dict's shape or the move surface changes.

Cost note: a phase runs 4-6 subagents (~0.8-1.2M tokens). The audit step is the cheapest
insurance in the pipeline — do not skip it to save a run.

**What phase 3 added to this playbook** (each of these caught something no earlier step did):

- **Step 6 is not optional, and it must test against OLD sets.** The cross-set batch found the
  put-back/when-discard ordering bug in FOUR cards — three of them shipped sets. A batch agent had
  flagged that ordering as ambiguous and resolved it by copying the shipped Rabble precedent,
  which was itself wrong. **A batch can only ever be as correct as the precedent it copies**, so
  per-set tests structurally cannot find this class.
- **Give the auditor your own uncertain calls as explicit questions.** Two judgement calls
  (off-turn bonuses evaporating, Scheme's timing) went to it as questions rather than being
  quietly asserted. Both came back confirmed with citations, and the second correctly separated
  the timing (fine) from the real defect next to it (the candidate set).
- **New coverage has to reach the soak.** The forced-kingdom chunks were hardcoded to four
  expansions, so all 26 new cards would have integrated green without ever running under the
  conservation census. They derive from `KINGDOM` now — check this whenever a set lands.
- **A batch's "no kernel gaps" is only as good as the frozen API.** Both halves reported zero
  gaps, which is the return on doing step 3 fully before step 4 rather than patching mid-flight.
- **Ask what the FRONTEND hardcodes.** The expansion picker mapped a literal list, so the set
  would have been unpickable however correct the backend was — invisible to the wire-contract
  test, because the field was being sent and merely never read.

**THE TRIGGER BUS** (the extension contract): kernel `emit()` — events today: `gain`
(with via_buy/dest), `buy`, `play_treasure`, `trash`, `buy_phase_end`, `turn_start`,
plus the `would_gain` interception — consumed by dynamic watchers (`add_watcher`,
per-play instances, immunity-aware) and the static `TRIGGERS` registry (sources:
hand-reaction window w/ reveal|play modes + actor scoping, in-play prompt, self-trigger),
plus `COST_MODS` / `DYN_COSTS` / `BUY_GATES` / `MANUAL_TREASURES`. A future set should
need at most a NEW EVENT NAME and registry entries — if a set seems to need a new
bespoke kernel mechanism, STOP and extend the bus instead.
