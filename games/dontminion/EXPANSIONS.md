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
| 5 | **Alchemy** (11 of 12 + Potion) | cost VECTOR dimension 1 (Potion) — landed inside cost_le/cost_eq/cost_lt + the new `*_card` forms; Potion production/payment in the buy flow. ⚠ **POSSESSION DEFERRED** (user decision) — see `cards.DEFERRED` | **SHIPPED** 2026-08-02 + audited (11 of 12 — Possession deferred) |
| 6 | **Dark Ages** (35 piles + Ruins/Shelters/Spoils/Madman/Mercenary) | on-trash triggers (the `trash` emit + `from:"self"`), Shelters setup, Madman/Mercenary/Spoils non-supply (3H), Ruins + Knights ordered piles (3H), Band of Misfits rides `play_from_supply` (5H); added `cost_ge`, `from_trash`, `deck_to_discard`, the `play_attack` before-play window and two reaction modes | **SHIPPED** 2026-08-04 + audited |
| 6H | **HARDENING: the LANDSCAPE kernel + board-row UI** (no new cards) | pays the two ph.-7 ledger rows standalone: `cards.LANDSCAPES` + `game["landscapes"]` (a purchasable thing that is NOT a card and NOT a pile), the `buy_landscape` move (printed cost — "cannot be changed by cards like Bridge" — + once-per-turn/game gates with ONE reader), the Tavern mat seat zone + the `from:"tavern"` call window, the `action_resolved` continuation-emit, `play_attack`→`before_play` generalization, Adventures-token storage + the `-cost` hook in `cost()`, and the landscapes/tavern/token frontend | **SHIPPED** 2026-08-04 |
| 7 | **Adventures** (30 + 8 Travellers + 20 Events) | Reserves + the Tavern mat and `from:"tavern"` call windows (6H), the 20 Events on `LANDSCAPE_FX` + `buy_landscape` (6H), Traveller chains on `add_pile(supply=False)` (3H) + `exchange` (ph. 3) + the interruptible Clean-up (5H), Adventures tokens (6H) — plus the ph.-7 kernel delta: `until="forever"` durations (Champion/Hireling), the −1 Card / −$1 / Journey seat tokens, Mission's no-buy extra turn, Save's end-of-turn hand return, Inheritance's Estate-token type injection, and `gain(**extra)`. **RETIRED deviation B6** (Coffers mid-ability, for Storyteller) | **SHIPPED** 2026-08-04 |
| 7H | **HARDENING: the DEBT vector + the scoring pipeline** (no new cards) | pays the two ph.-8 ledger rows standalone: the cost vector's third dimension inside the SAME six comparators (`debt_cost`, printed, no reduction reaches it), `game["debt"]` + the buyer-level buy gate + the payoff via a real `_SPENDABLES` registry (the 2024 "any time during your turn" timing), `effects.LANDSCAPE_SCORING` summed into `_total_vp`, `LANDSCAPE_SETUP`, landscape/pile VP + Debt stores on 6H's state and 3H's `attach`, and the `from:"landscape"` trigger source. SCHEMA 11 (fill-only) | **SHIPPED** 2026-08-05 |
| 8 | **Empires** (24 piles + 13 Events + 21 Landmarks) | **7H's seams took their first consumers with NO change** (Debt, LANDSCAPE_SCORING, LANDSCAPE_SETUP, the VP stores, `from:"landscape"`). Six kernel additions were still needed: pile identity follows the RANDOMIZER (`pile_types`), the `would_resolve` window + `cancel_pending_play` (Enchantress — and the ph.-10 Ways kernel, early), `return_to_action_phase` (Villa), `finish_duration` (Archive), `return_at_cleanup` (Encampment) and `emit("buy_phase_start")` (Arena). SCHEMA 12 (fill-only) | **SHIPPED** 2026-08-05 |
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

**This breaks the roadmap's own whole-set rule on purpose**, and the rule is worth restating so
the exception stays an exception: a set normally ships only when whole, because a partial set
poisons the random-kingdom picker. Alchemy ships at 11 of 12 by explicit decision, with the
twelfth recorded in `cards.DEFERRED` and reconciled by a test.

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

### What the audit caught

**University's gain is a "MAY" and I had made it mandatory** — a `choose_pile` frame has no way
to decline, so the card forced a gain every time. Nothing else would have found it: it "worked"
in every test written from the behaviour, because a test author reading the same implementation
asks the same question. Re-reading the printed text is what exposed it. It is a 0-or-1
`choose_cards` now, and `test_university_may_decline_to_gain` pins it.

### A finding for whoever picks this up

**Alchemist and Herbalist take the half-paid "`_end_turn` is not interruptible" ledger row from
one consumer to three.** Both are implemented with the same per-play `buy_phase_end` watcher as
Scheme. For Herbalist that is faithful rather than approximate only because the candidate set
comes from `leaving_play()` — "the cards that WILL be discarded from play at this Clean-up" —
which is what correctly excludes a Duration that stays out ("if a card is not discarded…
Herbalist can't put it onto your deck"). If a future set adds a card that cares about the order
of Clean-up itself, pay the row properly instead of adding a fourth watcher.

## Phase 5H — the Clean-up and Command hardening (no new cards) — SHIPPED 2026-08-04

Two ledger rows, standalone and behaviour-preserving, with the full suite as the net. Same
shape as 3H and for the same reason: both rows came due at ph. 6, and Dark Ages is the biggest
card batch yet (35). Bundling a kernel change into it is exactly what 3H existed to avoid.

**1. Clean-up is interruptible.** `_end_turn` now parks the sweep as a `__cleanup/sweep`
continuation and emits `cleanup_start` (new) and `cleanup_discard` before anything moves. A
consumer can push a real decision frame and relocate a card, with the whole table still intact —
nothing discarded, no new hand drawn, the turn not yet counted. Before this the events fired
into a sweep that carried straight on, so the seam LOOKED usable and was not; three cards worked
around it. Alchemist moved onto `cleanup_start`, which is its printed timing exactly, and all
four of its tests passed unchanged — which is itself the evidence the compendium was right that
the workaround had no practical difference. Scheme and Herbalist stay where they are on purpose:
their triggers are per-play, so a literal per-card consumer would ask yes/no for every card
instead of once with the list.

**2. "Play a card while leaving it" — and the ledger row was describing a retired card.**

This is the finding worth keeping. The row said we needed `play_card_as(game, pid, physical,
as_name)` with "identity-vs-physicality explicit". That is the PRE-2019 Band of Misfits. The
current card, and Overlord with it, does not change itself into anything — it plays an Action
card **from the Supply, leaving it there**. Inheritance's Estates turn out to be the same shape.
So the whole identity system was unnecessary: what shipped is `play_from_supply` +
`command_may_play` + `playable_from_supply`, about forty lines, reusing the existing attack
window and effect dispatch.

**This is the SECOND ledger row written from a card's old text** — phase 3 found the same thing
with Haggler and wrote "a reminder that a ledger row written from a card's OLD text schedules
the wrong work". It happened again, and cost more this time, because the wrong work was sized as
a kernel campaign. **Re-read the current card before building a row, not just when the row comes
due.** The compendium marks version history explicitly (`2019/2025 (current) version`); that
marker is the thing to check first.

Two rules came free from reading the current text: a Command card may not play a **Duration**
(the 2025 change) or another **Command** card ("to prevent loops from occurring"), and only the
**top card of a Supply pile** is choosable — which is why `playable_from_supply` asks
`pile_top` rather than the pile name, and why ph. 3H's ordered piles matter here.

One real bug, caught by the contract tests: the first cut parked its own ability continuation
ABOVE the reaction windows, so a Supply-played Attack resolved before anyone could Moat it — and
then, once reordered, ran twice, because `_open_attack_window` already parks the ability itself.
The fix was to delete the continuation and reuse the kernel's own machinery, which is the right
answer anyway: an attack is an attack however it reached play.

## Phase 6 — Dark Ages: SHIPPED 2026-08-04

**55 card definitions**, the largest batch in the roadmap and the first set with no second
edition to trim it: 34 ordinary kingdom piles + the Knights pile (10 cards) + Ruins (5) +
Shelters (3) + Spoils/Madman/Mercenary. Roster, costs, types and texts from the wiki chart
(Wayback capture of `List_of_cards`, all 55 rows); every behaviour and edge case from the
compendium's ch. VII entries, read per card rather than recalled.

**The kernel readiness call in the plan held.** Phases 3H and 5H had already paid every row this
set was going to hit, and the delta ended up being five small seams rather than a mechanism:
`cost_ge`, `from_trash`, `deck_to_discard`, the `play_attack` before-play emit and the
`discard`/`trash` reaction modes. Full list: `CLAUDE.md`, "Kernel v6".

**What the playbook caught this time:**

- **A GAIN THAT FOLLOWS A TRASH MUST BE PARKED BELOW IT.** Procession, Graverobber and Rebuild
  each pushed their gain prompt *after* calling `trash()`. Pushes are LIFO, so the player was
  asked what to gain before the trashed card's own when-trash ability resolved — a processioned
  Fortress came back to hand only after the gain was picked, and the compendium spells the order
  out for all three ("first play twice, then trash, then check cost, then gain"). Found by the
  per-card test for the set's most famous combo. It is the phase-3 put-back lesson in the
  opposite direction: there the discard had to come first, here the continuation does.
- **A Bane or a Ferryman pile is IN THE GAME** ("if these extra cards have a special setup rule,
  do that setup"), so a Hermit chosen as Young Witch's Bane has to bring the Madman pile. Found
  by the audit pass, not by a test — nothing else looks at the interaction between two sets'
  setup rules.
- **The pile-name-is-not-a-card design was forced, not chosen.** `_priced` resolves a name that
  IS a card to itself, so giving "Knights" a `CARDS` entry would have made the pile show its own
  cost instead of its top card's — a Sir Martin on top really does cost $4. Everything that walks
  a kingdom list had to tolerate a pile name instead: `grants`, `expansion_of`, `printed_cost`,
  `push_name_card`, `bot_plan.features`, `REVIEWED`. That is the cost 3H deferred, paid here.

**The bots.** `BM_TERMINALS` gained five measured entries (Cultist 76, Rogue/Marauder 62,
Hunting Grounds 61, Catacombs 58 — all at 300 games, since the sweep's default 50 left four of
them inside the noise band), and every non-drawing Dark Ages terminal was measured and rejected
(Death Cart 0.008 … Hermit 0.350). `TERMINAL_CAPS` gained one: **Catacombs wants exactly one**
(cap1 0.593 at n=400, confirmed after the n=120 signal, per the regression-to-the-mean rule the
quantity sweep established).

**Gates:** package suite (1240), full repo suite, the conservation soak over all four forced
Dark Ages kingdoms, and all 27 REAL prod saves replayed v1/v2/v5/v7/v8 → 9.

## Phase 6H — the LANDSCAPE kernel (no new cards) — SHIPPED 2026-08-04

Hardening, in the 3H/5H mold: seams built and contract-tested with NO consumer, so Adventures'
30 cards + 20 Events land on paths that were already exercised rather than paths that merely
existed. `cards.LANDSCAPES` ships **empty** — there is nothing to buy on any board today.

**The design call the phase turned on: a landscape gets its OWN home.** It has no copies, is
never gained, never sits in a zone, and "buying an Event is not buying a card" (p32) — so a
`CARDS` entry would give it a cost `cost()` would then discount, a `kingdom` flag that would
deal it as one of the ten, and a name every card-shaped census would have to learn to skip.
That is the **Knights lesson in reverse**: there an existing structure had to be taught to
tolerate a foreign name, and the cost was six call sites (`grants`, `expansion_of`,
`printed_cost`, `push_name_card`, `bot_plan.features`, `REVIEWED`). Here the foreign thing
arrived before its first consumer, so it got its own table and cost none of them.

**Two spec'd pieces came out different, both deliberately:**

- **There is NO `call` move, and the plan was wrong to promise one.** Every Reserve call in
  Adventures is a timed WINDOW — at the start of your turn (Guide, Ratcatcher, Transmogrify),
  when you gain a card (Duplicate), directly after resolving an Action (Royal Carriage, Coin of
  the Realm), at the end of your Buy phase (Wine Merchant). A free move would have been a rules
  deviation: a call has to be ordered in the ability POOL against everything else the same
  occurrence triggered, which a move enumerated in `legal_moves` cannot be. So calling rides
  the existing offer machinery as a new trigger source, **`from:"tavern"`** — the hand-reaction
  shape on the other public per-seat zone — and `engine.call_card` is the kernel helper its
  stage calls. Move surface unchanged; bots, undo, redaction and all six renderers untouched.
- **The `CALLS` registry was dropped for saying nothing.** A trigger spec already names the
  stage that runs when the call is accepted; a second registry mapping card → the same stage
  would have been a place for the two to disagree.

**The generalization that had to be conditional.** Ph. 6's `play_attack` emit became
`before_play`, fired for EVERY Action play, because an Adventures "+" token is the same timing
class as Urchin ("after before-play abilities like Adventures tokens, Kiln, Urchin", p33) and
one event beats two. But an Attack gets the ordering free (`_open_attack_window` already parks
the play ability) while an ordinary play runs its effect INLINE — and a pool parked before an
inline call resolves *after* it, i.e. exactly backwards. So the ability is parked underneath the
window only when the emit actually collects a consumer, and runs inline when it doesn't. That
is what makes the change byte-identical on today's boards rather than merely equivalent, and
Urchin's existing suite passing UNCHANGED is the net.

**"Directly after resolving" is not a place in `play_action_card`.** It returns while the play's
frames are still pending, and "completely resolve the play ability before playing it again"
(p17) defines resolution as those frames having drained. `action_resolved` is therefore a
`("__play","resolved")` continuation parked before the play pushes anything, so LIFO fires it
exactly then — and a throne-roomed Action emits twice, once per resolution, which is what a
Royal Carriage called after each needs.

**The behaviour-preservation proof is the rng, not the test count.** Setup is one call sequence,
so inserting a step into it re-deals every existing seed's board. `deal_landscapes` returns
before touching the rng while the pool is empty — which is every set today — so the sequence is
untouched, and that is why the whole pre-6H suite (forced boards, expected kingdoms, the
determinism soak) still reads the same. Pinned directly by
`test_the_dealer_draws_no_entropy_when_there_is_nothing_to_deal`.

**What the playbook caught:** the wire-contract test's emit scan named all five new log events
before any of them could ship as raw field names, and the prod-save replay tool crashed on a
correct migration because it derived its seat-key check from `_SEAT_FILLS` but hardcoded `list`
— the phase's token store is a dict. Both are the mechanical guards doing their job.

**The dormant frontend WAS rendered once, by hand.** "Ships dormant" otherwise means "ships
unverified": the standing `screens.mjs` pin can only assert the row renders NOTHING, which a
component that throws on its first real landscape would also satisfy. So three real Adventures
Events were temporarily put in `cards.LANDSCAPES`, the gate re-run against a board that dealt
one, and the row inspected live (name/cost/kind/text present, 223×76px, no overflow, inside the
board's width, first child of `.dm-supply`) before both patches were reverted. Do this at every
dormant-UI phase — it costs one run and it is the only thing between "the empty case is pinned"
and "the feature works".

**Gates:** package suite (1291, +48), full repo suite (2362), `npm run smoke` + `npm run screens`
(with a new dormant-row pin), and all **27 real prod saves** replayed v1/v2/v5/v7/v8 → 10.

## Phase 7 — Adventures: SHIPPED 2026-08-04

**58 definitions**: 30 kingdom cards, the 8 Traveller upgrades (non-Supply piles of 5) and the
**first 20 landscapes** the game has ever had. 276 cards, 9 sets.

**The 6H bet paid off, but the "registry-only" claim on the old roadmap row did not.** Reserves,
Events, Travellers and tokens all landed on paths built and contract-tested one phase earlier,
and none of them needed a kernel change. What still did:

- **`until="forever"` durations** — Champion and Hireling stay in play for the rest of the game.
  `_start_of_turn` marked every entry `done` unconditionally, which discarded them at the next
  clean-up; a `forever` flag on the ENTRY (a property of the physical card, so a throne-roomed
  Hireling doubles its fx) keeps both the fx and the card.
- **Three seat tokens with real behaviour** — the −1 Card token eats the next DRAW and nothing
  else (a reveal leaves it, an otherwise-empty deck does not reshuffle to feed it, and it comes
  off even with nothing to draw), the −$1 token is "only removed when you get $1 or more, not
  when you get $0", and the Journey token is stored as its DOWN state so absence means the
  face-up start.
- **Mission's extra turn** — `request_extra_turn(source=, no_buy=)`. Outpost's own transient was
  left untouched deliberately: a save can be caught mid-turn holding it.
- **Inheritance** — a game-wide type injection in `types_of` keyed on `game["turn"]`, plus
  `play_set_aside`. It is NOT an identity system: the 2019 errata retired that reading, and
  ph. 5H had already ruled the system unnecessary. Estates stop being Actions once the game is
  over, which is the compendium's Vineyard ruling.
- **`gain(**extra)`** — a card marking a gain it caused and reading the mark back in its own
  when-gain condition (Port's "the when-gain doesn't trigger again"). A transient on the game
  dict would NOT do: the would-gain protocol can park the physical gain, so the emit may happen
  long after the call returned.

**TEN CARDS DIFFER FROM EVERY CARD-LIST SITE AND THE 2015 RULEBOOK.** The compendium's ch. V
lists Bonfire, Bridge Troll, Haunted Woods, Inheritance, Messenger, Plan, Port, Storyteller and
Swamp Hag among the 2022 printings, and Mission among the 2023 no-third-turn changes. The 2022
pass did two things across the catalogue — "when-buy triggers were changed to when-gain, and
while-in-play timers were removed" — and both bite here: Haunted Woods, Swamp Hag, Messenger,
Port and Plan's token now trigger on a GAIN; Bridge Troll's cost reduction is turn-scoped like
Highway's; Bonfire only trashes Coppers; Storyteller gives +1 Card instead of the +$1 it used to
pay itself with. Reading the errata chapter FIRST, before writing a line, is what made this a
data decision rather than nine bugs.

**Two real defects, both found by fuzzing rather than by tests, and both PRE-DATING this set:**

- **A persisting Duration was counted TWICE while Clean-up was interrupted.** ph. 5H made
  Clean-up interruptible, but `_cleanup_durations` promotes an entry while the card is still in
  `in_play` — so a consumer's open decision froze the game with the card in both places, and
  `game["vp"]` is recomputed after every move. Adventures made it reachable in an ordinary
  random game (a Traveller's exchange offer holds Clean-up open while a Champion persists). The
  card now leaves `in_play` as it is promoted.
- **...and fixing that exposed a second, worse one.** The sweep re-read `in_play` and subtracted
  `kept_out` AGAIN, so a seat holding two copies of one Duration (one persisting, one not) had
  the second copy **destroyed** by `seat["in_play"] = []`. The frame now carries a `pulled` flag
  — expand/contract, because a mid-clean-up frame can genuinely be sitting in a live save.
- The promotion also **rebuilt the entry from three hand-copied keys**, silently dropping
  `watchers` (so nothing could ask a promoted entry whether it had any) and, once ph. 7 added
  it, `forever`. It carries the whole entry now.

**A GUARD THAT COULD NEVER FAIL.** `bot_traits.REVIEWED` was rebuilt in ph. 6 as a comprehension
over `KINGDOM` — which is exactly what `test_every_kingdom_card_is_reviewed` compares it against,
so the difference was empty by construction. Dark Ages passed it while 55 unreviewed cards
shipped. It is an explicit list of 260 names again, and it was re-verified by deleting one name
and watching the test go red. **Reviewing a card is a human act; the record of it cannot be a
derivation of the thing it is meant to check.**

**Bots.** `BM_TERMINALS` gained three measured entries at n=300 — **Swamp Hag 91, Giant 78,
Haunted Woods 76** — and the three rejections are the instructive half: Ranger is a WASH (0.5333,
its +5 Cards only arrives every other turn), Gear 0.4558, and **Bridge Troll 0.1983**, the set's
clearest engine-part-wearing-an-attack's-clothes. `bmplus` beats plain money **0.796** on
Adventures boards with the mirror reading exactly 0.5000.

**Gates:** package suite (1408, +110), full repo suite (2479), 480 forced-Adventures fuzz games
+ 224 mixed-set ones under the conservation census with zero failures, `npm run smoke` +
`npm run screens` (with a REAL Adventures board rendering its Event row), and all **27 real prod
saves** replayed. **No SCHEMA bump** — every key this set reads was added by 6H's v10.

## Phase 7H — the DEBT vector + the scoring pipeline (no new cards) — SHIPPED 2026-08-05

Hardening, in the 3H/5H/6H mold, and **ph. 7's postmortem is the argument for doing it**: the
roadmap called Adventures "registry-only" and it wasn't — six kernel additions were needed
mid-batch — while everything that HAD been pre-built in 6H (Reserves, Events, tokens,
Travellers) landed without touching the kernel. So Empires' 24 kingdom cards + Events + 21
Landmarks now land on paths that were already exercised. No card and no landscape in the data
carries a `debt` key, nothing registers a scoring fn, and the `landmark` kind stays undealt.

**The Debt vector cost SIX comparator clauses and nothing else, and that is the whole point of
the ph.-2 discipline.** Raw `cost() <= n` in card code has been a review-reject since phase 2
precisely so a future cost dimension would land in one place; Potion proved it in ph. 5 and Debt
proved it again here, both with **zero call-site changes across nine effects modules**. The
compendium's own worked comparisons ({$4} and {4D} both lower than {$4,4D}; {$5} and {$4,4D}
incomparable) are the tests, verbatim.

**Two rules that a card-list site would have got wrong**, which is the ph.-7 errata lesson
applied before the fact rather than after:

- **Paying off Debt happens "at any time during your turn", including mid-ability, and uses up
  no Buy.** That is the **2024 rules change**. The 2016 rulebook and the card-list sites confine
  payoff to the second part of the Buy phase — build from those and Capital's own "you may pay
  it off" becomes unreachable at the moment it fires. `_h_spend` touches neither `game["buys"]`
  nor `turn_ctx["bought"]`, so a player who pays off in the Buy phase may still play Treasures.
- **The buy gate is about the BUYER, not about a pile.** "You can't buy anything (cards, Events
  or Projects)" is one predicate consulted by both handlers and by `legal_moves`, NOT a
  `BUY_GATES` entry — that registry is per-card and would have needed an entry per pile, missing
  Events entirely. As a side effect ph. 9's Projects are already covered, since they buy through
  the landscape handler.

**The `spend` move surface finally got the registry it always implied.** Ph. 4 shipped it naming
Villagers, Favors and this Debt payoff as the three things it was built for, and `_h_spend` then
hardcoded Coffers. `_SPENDABLES = {kind: {"avail", "apply"}}` makes `spendable`/`_h_spend`
generic; `_spend_moves` needed no change at all. Debt's `avail` is `min(coins, debt)`, so a $0
player is offered **nothing** — which is the livelock guard, the same shape as the
`play_all_treasures` no-op that once stuck two live prod games.

**The scoring hook is continuous, not end-of-game, and that is free.** `LANDSCAPE_SCORING` is
summed into `_total_vp`, which `_post_move` already recomputes after every move — so a
Landmark's VP displays live all game and `score_game` reads the same number. The one edge is the
ph.-7 Inheritance lesson: a scoring fn must not change value at `game["over"]`, and the
type-sensitive case is already pinned by `types_of`'s over-gate.

**THE FUZZ CENSUS FOUND A LIVE CARD-CONSERVATION BUG, pre-existing since ph. 7 — fixed here.**
`_cur_dur` points `add_duration_fx` at the physical card being played, and it is set by
`play_action_card`. That holds while a play resolves inline — but an Attack's ability is PARKED
under the reaction windows, and anything resolving in the gap that plays a card of its own
repoints it. **Caravan Guard is the collision**: a reaction that plays ITSELF and is a Duration.
So a Haunted Woods played into a Caravan Guard reaction found the pointer on the reactor's
entry, saw the names disagree, and minted a SECOND setup entry for a card played once.

One mis-pointed entry is only latent — the empty eager entry is never promoted, so the count
still comes out right. It becomes a **conjured card** when the ability runs TWICE (a Throne Room
or Royal Carriage replay of a Duration Attack with a Duration-playing reaction inside each
window): both entries carry fx, both promote at Clean-up, and `owned_cards` counts one physical
card twice. Found on a 4p `adventures+alchemy+base` board, seed 4, move 343.

The fix is `_restore_cur_dur`: the two parked-play frames (`__attack/play_ability` and
`__play/ability`) now carry the pointer they were pushed with and re-point it before running the
ability. **Restore, not save-and-revert** — the pointer must stay live for the later stages the
ability pushes (Haven's pick, Throne Room's rider marking), which is exactly what the inline
path gives them. Guarded on the data key being PRESENT, not on its value (expand/contract: a
live save can be sitting on an attack window right now, and `None` is a meaningful value — a
non-Duration play sets the pointer to None). Four cross-set tests, two of which go red when the
restore is disabled.

**A third bug, from writing one log line:** `coffers`, `spend` and `end_draw` logged their count
as `n=`, and `_log` stamps the log SEQUENCE into `entry["n"]` LAST — so the client had been
rendering the sequence number ("gets +917 Coffers"). All three log `count=` now, `fmtLog` reads
`e.count ?? e.n` so entries already in prod render exactly as they did, and
`test_no_log_call_passes_a_count_as_n` is the guard, because the failure is invisible to any
test that doesn't read the rendered string.

**Gates:** package suite (1460, +52), full repo suite (2531), a 348-game fuzz census over real
boards (every set, sampled pairs, rolling triples, all-sets; 2p/3p/4p; random + bmplus) — **zero
failures, and no Debt token reached a real board, asserted per move** — a 220-game
duration-and-attack-heavy fuzz (random 3-set combos, 2p/3p/4p) clean, a synthetic-Debt fuzz
board where random-legal bots take Debt and pay their way out, all **27 real prod saves**
replayed at v11, `npm run smoke` + `npm run screens`. The Debt chip and payoff control are
dormant UI, hand-verified like 6H's landscape row.

## Phase 8 — EMPIRES: SHIPPED 2026-08-05

**24 Supply piles (36 card definitions), 13 Events and the game's first 21 LANDMARKS.** 312
cards, 10 sets, 54 landscapes.

**7H's bet paid in full, and this time the roadmap row was ALSO wrong in the other direction.**
It said "registry + data on 7H's seams"; six kernel items were needed. But the things 7H
pre-built took their first consumers with **no change whatsoever** — Debt (`debt_cost`, the six
comparators, the buy gate, `_SPENDABLES`), `LANDSCAPE_SCORING` (11 Landmarks are nothing else),
`LANDSCAPE_SETUP` (9 of them), the pile and landscape VP stores, `add_pile_debt`, and
`from:"landscape"` (8 Landmarks). That is the hardening-phase argument holding twice in a row:
what gets built one phase early against synthetics lands free, and what doesn't gets found
mid-batch. The full list of what was needed is `CLAUDE.md` "Kernel v8"; the two that generalise:

- **A PILE'S IDENTITY IS NOT ITS FACE.** `types_of(pile)` resolves through the top card, which
  is right for buying and wrong for every setup rule and token rule. Three of the five split
  piles show a Treasure once the dear half surfaces while the pile stays an ACTION pile. The
  distinction had been latent since ph. 6 — **Knights has been answering from its top card the
  whole time** — and only became observable when a set shipped a pile whose halves differ in
  TYPE. New reader, one line changed in each of the two consumers.
- **THE WOULD-RESOLVE WINDOW IS THE WAYS KERNEL (ph. 10), TWO PHASES EARLY.** Enchantress needs
  to replace what a played card does, and the compendium puts that in its own timing class —
  after before-play, after reactions — alongside "all Ways". So ph. 10 now inherits a built and
  tested `emit("would_resolve")` + `cancel_pending_play` instead of scoping one.

**THE SET STRADDLES THREE ERRATA PASSES — 16 of ~70 objects differ from every card-list site
and from BOTH Empires rulebooks.** 2021 (Farmers' Market, Mountain Pass, Opulent Castle,
Temple), 2022 (Charm, Forum, Groundskeeper, Tax, Basilica, Colonnade, Defiled Shrine) and 2025
(Capital, Chariot Race, Gladiator, Overlord, Ritual). Reading ch. V before writing a line is
what kept this data rather than sixteen bugs, and the one nobody would have guessed:

- **"the Farmers' Market SUPPLY pile" (2021) is a real rule, not tidier wording.** Farmers'
  Market, Temple and Gladiator all cost $3 or $4, so **any of them can be drawn as FERRYMAN's
  extra pile** — a pile that is in the game and NOT in the Supply. Gathering VP onto it, or
  trashing a Gladiator from it, would be operating on a pile nobody can buy from. A cross-set
  corner that exists only because we ship C&G 2E, and that an errata-blind port gets wrong.
- The 2022 pass's condition is **"in your Buy phase"**, which is not "when you buy": a Workshop
  gain in the Buy phase counts and a gain on an opponent's turn does not.

**One latent defect found and fixed on the way**: `trash_from_supply` emitted NOTHING, so a
card trashed out of the Supply never ran its own on-trash ability. Lurker has been able to do
that since ph. 1; it was invisible because no card or landmark consumed a Supply trash until
Tomb. It takes an optional `pid` and emits when given one.

**And one of this set's own, found by the fuzz census rather than by a test: CROWN pushed its
replay AFTER the first play.** LIFO then ran the second play before the first had resolved, so
a Crowned Oasis opened its second discard prompt against a hand snapshot the first prompt was
about to invalidate — and answering it crashed the move (`list.remove(x): x not in list`). The
fix is the ordering rule this repo has now learned three times (ph. 3's put-back, ph. 6's
gain-after-trash): **push the continuation FIRST so it sits below what the play pushes**, which
is exactly what Throne Room has always done. Pinned by a regression test verified red against
the old order.

**A degenerate state worth naming, because it is RULES-FAITHFUL and looks like a hang:** buy
Donate, trash your entire deck, and hold Debt. You then have no cards, so no income; Debt
blocks every buy; and no pile can ever empty, so no game-end condition can fire. Two random
bots reached it in the fuzz. Real Dominion has the identical property — there is nothing to
fix — but it means a fuzz harness on a Donate board must assert PROGRESS (turns advancing)
rather than termination, which is what these runs do.

**The bots owed one rule and would otherwise have been crippled silently.** Debt blocks ALL
buying, so a tier that bought an Engineer and never paid it off would end every remaining turn
with its coins unspent — no error, no stall, no test failure, just a bot that stops playing.
`_pay_off_debt` runs before anything else in the Buy phase for all four policy tiers. Split
piles and Castles stay out of `BM_TERMINALS` under the ph.-3H rule that a face which changes is
nobody's reliable terminal.

**Gates:** package suite (**1603**, +143), full repo suite (**2674**), a 408-game fuzz census
over real boards across every set (2p/3p/4p, random + bmplus) with zero failures, a **306-game
forced-landscape fuzz** that puts each of the 34 Empires landscapes on a board one at a time
(paired with Museum and Tomb so the scoring pipeline and the trash trigger run on every board)
— zero failures, all **28 real prod saves** replayed at v12, `npm run smoke`, and `npm run
screens` with a REAL Empires board asserting the two render paths this set adds: a landmark
that prints no price at all, and a Debt badge that REPLACES the coin cost on a {ND} card.

## Structural-debt ledger (pay these ON TIME — kernel work first, stop-the-line)

| Debt | First bitten by | Pay when |
|---|---|---|
| ~~Replacement effects (would-gain)~~ **PAID ph. 2** — park/window/cancel_pending_gain, contract-tested | Trader (ph. 3) | done |
| ~~Cost comparison helpers~~ **PAID ph. 2** — cost_le/cost_eq everywhere; **BOTH vector dimensions have now landed inside them** (Potion ph. 5, Debt ph. 7H) with zero call-site changes across nine effects modules, which is the return on banning raw `cost() <= n` three phases before either was needed | Alchemy/Empires | done |
| ~~Client-side price math~~ **PAID post-ph. 2** — `player_view` ships `costs`; the client never re-derives | Peddler bug (found live) | done |
| ~~Undo/save bloat~~ **PAID (pre-ph. 3)** — snapshots store `_log_len` and undo truncates; measured 487 KB → 150 KB on a late-game blob, per save-write | was live | done |
| ~~Versioned save migration~~ **PAID (pre-ph. 3)** — `SCHEMA`=3 + `engine.migrate()` at load; 28 defensive gets retired; `test_migrate.py` downgrades a CURRENT game to each old shape. EVERY PHASE OWES: bump + migrate step + test | was growing | done |
| ~~Unknown-log-event fallback~~ **PAID (pre-ph. 3)** — fmtLog renders a readable fallback for events it doesn't know yet, so a new engine event is never silent | was live | done |
| ~~Vault's opponent offer is feasibility-filtered~~ **PAID (pre-ph.3)** — offered to any non-empty hand; 1 card discards 1 and draws nothing (Capital City ruling) | Tunnel's when-discard (ph. 3) | done |
| ~~No `discard` emit point~~ **PAID (pre-ph.3)** — `discard()` emits per card AFTER the whole batch (the 2022 all-at-once change the Tunnel ruling needs); Clean-up bypasses `discard()` so when-discard correctly can't fire there, pinned by a test | Tunnel/Trail/Weaver (ph. 3) | done |
| ~~`self` triggers couldn't see the emit context~~ **PAID (pre-ph.3)** — `**extra` now reaches self-trigger data, so a when-BUY-this card can tell a buy from any other gain | Farmland (ph. 3) | done |
| ~~`in_play` triggers get no SUBJECT~~ **PAID, but the premise was WRONG.** Paid for Haggler — except Haggler 2022 "SETS UP A LATER ABILITY … for the rest of this turn", i.e. Hoard's per-play `until="turn_end"` watcher, NOT an `in_play` trigger. The row described the pre-2022 card. The fix (push receives `ctx`) is kept: a trigger seeing its own event's context is the right contract and Treasury ignores it. But nothing in ph. 3 needed it — a reminder that a ledger row written from a card's OLD text schedules the wrong work | (nothing — mis-scheduled) | done, not needed |
| ~~`_end_turn` is not interruptible~~ **PAID ph. 5H** — the Clean-up SWEEP is a parked `__cleanup/sweep` continuation, so a `cleanup_start` or `cleanup_discard` consumer can push a real decision and MOVE a card before anything is discarded and before the new hand is drawn. Alchemist moved onto `cleanup_start` (its printed timing); Scheme and Herbalist stay on `buy_phase_end` deliberately — their triggers are per-play, not per-card, so asking once with the whole list is the same decision with fewer prompts | Scheme (ph. 3) | done |
| ~~Off-turn resource leak~~ **PAID ph. 3** — the kernel binds `_actor` around every effect and stage, so card code still calls `add_*` with no pid and a bonus earned on someone else's turn EVAPORATES (logged `off_turn_bonus`) instead of landing in the turn player's pool. NB the first attempt (an optional `pid=` argument) did NOT work: card code never passes one | Trail, Nomads | done |
| ~~Clean-up doesn't sweep OTHER seats' `in_play`~~ **PAID ph. 3** — every seat's table is swept at each clean-up; durations and riders protected | Guard Dog/Trail/Weaver/Berserker | done |
| ~~The put-back jumped the discard's when-discard triggers~~ **PAID ph. 3** — `discard_then_putback` encodes "first discard, THEN put cards back" ONCE; four cards (Sentry, Lookout, Rabble, Cartographer) each had their own copy and all four had it backwards | Tunnel/Trail via Cartographer — found by the CROSS-SET step, not per-set tests | done |
| ~~Non-supply gain sources~~ **PAID ph. 3H** — `gain_from` + a second count index, so "a card from the Supply" excludes them by construction rather than by remembering | Rewards (ph. 4) | done |
| ~~Pile abstraction~~ **PAID ph. 3H** — `game["piles"]`: ordered `contents` + retained `face` + `members` + `attach`; cost/type resolve through the face, the census unpacks it, the wire never sees the order | Ruins/Knights (ph. 6), scheduled early deliberately | done |
| ~~**Move-surface trio**~~ **PAID — `spend` ph. 4, `buy_landscape` ph. 6H, and `call` TURNED OUT NOT TO BE A MOVE.** `spend` gave Villagers/Favors/Debt-payoff one surface + `spendable()` as THE reader — and ph. 7H turned the hardcoded-Coffers handler into the `_SPENDABLES` registry the row had promised, so each remaining counter is now one dict entry. `buy_landscape` is the same shape for Events/Projects, with `landscape_gate()` as THE reader. The third was mis-scheduled by this row: every Reserve call in the game is a timed WINDOW, so it belongs in the ability POOL (ordered against everything else the occurrence triggered) and not in `legal_moves` — it shipped as the trigger source `from:"tavern"` instead, and the move surface did not grow | spend: ph. 4 · buy_landscape: ph. 6H · call: n/a | done |
| ~~Card identity / "play-as"~~ **PAID ph. 5H — AND THE ROW'S PREMISE WAS WRONG.** It described the PRE-2019 Band of Misfits, which turned itself into another card. The current one does not: "unlike the first version, this version does not change itself to another card, nor does it play itself. Instead it PLAYS AN ACTION CARD from the Supply" — and Inheritance's Estates resolve to the same shape ("play the card with your Estate token, leaving it there"). So no identity system was needed at all: `play_from_supply` + `command_may_play` + `playable_from_supply`, ~40 lines. **Ways (ph. 10) is a DIFFERENT and smaller mechanism** — substitute a card's play ability, not change what it is — and should be designed then, not now | Band of Misfits (ph. 6) | done |
| **`play_all_treasures` suppression must become a STATE predicate.** Today it's a static card list (`MANUAL_TREASURES` — treasures that push a decision). Highwayman negates the FIRST Treasure its victim plays, so which treasure goes first becomes a real choice and the button must not make it for them — a condition the card list cannot express, since it depends on game state and LIFTS once the negation is spent. Wanted: `autoplay_block(game, pid) -> reason \| None`, fed by both the static set and watcher-registered blocks, read by `legal_moves` + the handler + shipped in `player_view` (state-dependent ⇒ NOT `/catalog`, unlike the static set) so the button hides AND says why. Also fixes the ordering row below if the block carries an order | Highwayman (ph. 12) | ph. 12 pre-work — but build it at the FIRST set that adds an order-sensitive treasure |
| ~~Autoplay ORDER is hand order~~ **PAID (post-ph. 2)** — `AUTOPLAY_LAST` registry + a stable sort in the handler; Bank now plays after the rest ($6 → $10 on the measured hand, matching optimal play). Adding a Treasure with an ability now means choosing a bucket: manual / autoplay-last / autoplay — see CLAUDE.md | Bank (was live) | done |
| ~~**Landscape cards** (Events/Landmarks/Projects/Ways/Traits/Prophecies/Allies) + the board-row UI~~ **PAID ph. 6H** — `cards.LANDSCAPES` (all six kinds framed, only `event` wired) + `game["landscapes"]` + the official randomizer-mix deal + `buy_landscape` + the wide board row, all contract-tested against synthetic landscapes. The "global trigger source" half of this row was already **PAID ph. 4** (`TRIGGERS from:"game"`, Footpad) — the row predated it | Adventures (ph. 7) | done |
| ~~**Scoring pipeline hook**~~ **PAID ph. 7H** — `effects.LANDSCAPE_SCORING = {name: fn(game, pid) -> int}`, summed into `_total_vp` for every landscape DEALT (no ownership test: "a Landmark's ability is always active for all players"). Because `_post_move` already recomputes `game["vp"]` after every move, during-game landmark VP display fell out for free and "at game end" turned out to be the wrong framing — the constraint is only that a scoring fn must not change value at `over`. Shipped with `LANDSCAPE_SETUP`, the landscape/pile VP + Debt stores, and the `from:"landscape"` trigger source | Empires (ph. 8) | done |
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
