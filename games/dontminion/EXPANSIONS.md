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
| 3 | Hinterlands 2E (26) | when-gain everywhere (bus-ready); NEW: `discard` emit point (Tunnel) + unfiltered offers (Vault row), reactions from NON-hand zones (Trail: gain/trash/discard from anywhere), attack-reaction that PLAYS (Guard Dog), on-gain deck insertion (Inn), when-buy remodel (Farmland), Highway (first real `COST_MODS` consumer) | next |
| 3H | **HARDENING: the pile & source model** (no new cards) | see below — pays two ledger rows at once, standalone, behavior-preserving | planned |
| 4 | Cornucopia & Guilds 2E (26 + Rewards) | Coffers (spendable counter + UI counters row + generic `spend` move), overpay-on-buy, differing-names, Rewards non-supply pile (needs 3H), Young Witch's Bane (11th pile + marker) | planned |
| 5 | Alchemy (12 + Potion) | cost VECTOR dimension 1 (Potion) — lands inside cost_le/cost_eq; Potion production/payment in the buy flow. ⚠ **Possession is phase-sized on its own** (take a turn controlling another player's cards) — budget it like a kernel system, not a card | planned |
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

## Phase 3H — the pile & source model (standalone hardening, no new cards)

`supply = {name: count}` cannot represent what five later sets need, and non-supply
gain sources appear in six. One behavior-preserving refactor pays both ledger rows with
the full 344-test suite + soak as the net, instead of bundling the biggest schema change
into Dark Ages' 35 cards:

- **Pile objects**: named piles with `count`, and where needed ORDERED `contents` +
  visible `top` (Ruins and Knights ph. 6, split piles + Castles ph. 8, ROTATING piles
  ph. 12, Traits attach per-pile ph. 13, Adventures tokens sit on piles ph. 7). Cost/type
  of "the pile" = its top card. Uniform random-order redaction (pile order is hidden info).
- **Gain sources beyond the supply**: one `gain_from(source, ...)` surface covering
  Rewards (ph. 4), Spoils/Madman/Mercenary (ph. 6), Horses (ph. 10), Spirits (ph. 11),
  Loot (ph. 13) — non-supply piles never count for empty-pile game end, never buyable.
- Wire compatibility: keep `supply` counts + `costs` shape the client already reads;
  add `pile_view` only for ordered piles. Save-blob migration via the versioned loader
  (ledger row below). Census/soak extended to the new zones. Frontend renderPile reads
  tops from the view instead of assuming pile==card.

## Structural-debt ledger (pay these ON TIME — kernel work first, stop-the-line)

| Debt | First bitten by | Pay when |
|---|---|---|
| ~~Replacement effects (would-gain)~~ **PAID ph. 2** — park/window/cancel_pending_gain, contract-tested | Trader (ph. 3) | done |
| ~~Cost comparison helpers~~ **PAID ph. 2** — cost_le/cost_eq everywhere | Alchemy/Empires | done (the vector itself lands ph. 5/8, confined to two functions) |
| ~~Client-side price math~~ **PAID post-ph. 2** — `player_view` ships `costs`; the client never re-derives | Peddler bug (found live) | done |
| ~~Undo/save bloat~~ **PAID (pre-ph. 3)** — snapshots store `_log_len` and undo truncates; measured 487 KB → 150 KB on a late-game blob, per save-write | was live | done |
| ~~Versioned save migration~~ **PAID (pre-ph. 3)** — `SCHEMA`=3 + `engine.migrate()` at load; 28 defensive gets retired; `test_migrate.py` downgrades a CURRENT game to each old shape. EVERY PHASE OWES: bump + migrate step + test | was growing | done |
| ~~Unknown-log-event fallback~~ **PAID (pre-ph. 3)** — fmtLog renders a readable fallback for events it doesn't know yet, so a new engine event is never silent | was live | done |
| **Vault's opponent offer is feasibility-filtered** (0-1-card hands never asked) | Tunnel's when-discard (ph. 3) | ph. 3, WITH the `discard` emit point |
| **Non-supply gain sources** | Rewards (ph. 4) | **ph. 3H** |
| **Pile abstraction** (ordered/split/rotating piles, per-pile attachments) | Ruins/Knights (ph. 6), but scheduled early deliberately | **ph. 3H** |
| **Move-surface trio**: generic `spend` (Coffers/Villagers/Favors/Debt-payoff + a counters row in the resbar UI), `buy_landscape` (Events/Projects), `call` (Reserves). Design each ONCE at first need; every later consumer is registry + data | spend: ph. 4 · buy_landscape/call: ph. 7 | ph. 4 / ph. 7 pre-work |
| **Card identity / "play-as"**: a physical card played AS another (Band of Misfits ph. 6, Inheritance ph. 7, Ways ph. 10, Overlord). Needs `play_card_as(game, pid, physical, as_name)` where identity-vs-physicality is explicit (types/cost read from WHICH?— the compendium's lose-track rules decide). The Charlatan `types_of` seam is the foothold | Band of Misfits (ph. 6) | ph. 6 pre-work, DESIGN reviewed against ph. 7/10 consumers before freezing |
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

**THE TRIGGER BUS** (the extension contract): kernel `emit()` — events today: `gain`
(with via_buy/dest), `buy`, `play_treasure`, `trash`, `buy_phase_end`, `turn_start`,
plus the `would_gain` interception — consumed by dynamic watchers (`add_watcher`,
per-play instances, immunity-aware) and the static `TRIGGERS` registry (sources:
hand-reaction window w/ reveal|play modes + actor scoping, in-play prompt, self-trigger),
plus `COST_MODS` / `DYN_COSTS` / `BUY_GATES` / `MANUAL_TREASURES`. A future set should
need at most a NEW EVENT NAME and registry entries — if a set seems to need a new
bespoke kernel mechanism, STOP and extend the bus instead.
