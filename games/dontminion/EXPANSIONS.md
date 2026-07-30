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
| 1 | **Seaside 2E** (27) | Durations (stay-in-play, next-turn fx, riders), turn-start frames, cross-player watchers (gain / treasure-play), gain reactions from hand (Pirate), Lighthouse protection, Island + Native Village mats, duration set-aside (Haven), extra turns (Outpost), interruptible clean-up (Treasury) | **IN PROGRESS** |
| 2 | Prosperity 2E (25 + Platinum/Colony) | Platinum/Colony basics toggle, VP tokens, while-in-play cost modifiers (Quarry), on-buy/on-gain hooks (Hoard/Mint/Watchtower reaction), King's Court | planned |
| 3 | Hinterlands 2E (26) | when-gain abilities everywhere (kernel gain hooks exist after Phase 1/2) | planned |
| 4 | Cornucopia & Guilds 2E (26 + Rewards) | Coffers, overpay-on-buy, differing-names counting, non-Supply Reward pile | planned |
| 5 | Alchemy (12 + Potion) | Potion as a second cost/currency dimension | planned |
| 6 | Dark Ages (35 + Ruins/Shelters/Spoils) | on-trash triggers, Ruins mixed pile, Shelters setup, non-Supply Spoils, Knights split pile | planned |
| 7 | Adventures (30 + 20 Events + Travellers) | Reserve cards + Tavern mat, LANDSCAPE UI (Events), Adventures tokens on piles, exchange (Traveller lines) | planned |
| 8 | Empires (24 + Events + 21 Landmarks) | Debt, split piles, Landmarks scoring, gathering VP tokens | planned |
| 9 | Renaissance (25 + 20 Projects + Artifacts) | Villagers, Projects (bought abilities), Artifacts (pass-around states) | planned |
| 10 | Menagerie (30 + Events + 20 Ways) | Exile mat, Horses (non-Supply), Ways | planned |
| 11 | Nocturne (33 + Boons/Hexes/Heirlooms) | NIGHT PHASE (turn structure change), Boon/Hex decks, Heirloom setup, Spirits/Zombies non-Supply | planned |
| 12 | Allies (31 + 23 Allies) | Favors, rotating split piles, Ally abilities | planned |
| 13 | Plunder (40 + Loot + 15 Traits + Events) | Loot deck, Traits attached to piles (durations exist since Phase 1) | planned |
| 14 | Rising Sun (25 + 10 Prophecies + Events) | Shadow cards (play from deck), Prophecies (sunrise/twilight), Debt reuse | planned |
| 15 | Promos (11) | mostly rides earlier systems (Stash needs shuffle-placement) | planned |

Sequencing rationale: Seaside's duration machinery is the single most-reused mechanic
(Adventures, Nocturne, Menagerie, Allies, Plunder, Rising Sun all lean on it); Prosperity
and Hinterlands generalize the gain/buy trigger surface that half the later sets assume.
The landscape-card UI (Phase 7+) is the next big FRONTEND lift: a new board row + a
"buy an Event" flow beside the supply.

Kernel v2 (Phase 1) API additions — see `engine.py` "DURATION kernel" section and the
frozen-API notes in `CLAUDE.md`: `add_duration_fx`, `add_watcher`, `watcher_data`,
`remove_watcher`, `mark_duration_rider`, `set_aside_duration`, `take_dur_aside`,
`to_island`, `to_village_mat`, `take_village_mat`, `request_extra_turn`, `duration_in_play`.

## Structural-debt ledger (what the bus does NOT yet cover — pay these ON TIME)

| Debt | First bitten by | Pay when |
|---|---|---|
| ~~Replacement effects~~ **PAID (Phase 2):** the would-gain protocol (park/window/cancel_pending_gain) is live with contract tests | Trader (ph. 3) lands on proven machinery | done |
| **cost() -> int becomes a vector** (Potion, Debt) — *helpers PAID (Phase 2): all comparisons go through cost_le/cost_eq* | Alchemy (ph. 5) / Empires (ph. 8) | the vector change itself lands in those phases, now confined to two functions |
| **Non-supply gain sources** (Rewards/Spoils/Horses/Loot) — gain() only knows the supply | Cornucopia & Guilds (ph. 4) | Phase 4 kernel work |
| **Vault's opponent offer is feasibility-filtered** (0-1-card hands never asked) — harmless until a when-discard trigger exists | Tunnel (ph. 3!) | Phase 3, WITH the when-discard emit point |
| **Landscape cards** (Events/Landmarks/Projects/Ways…) + the bus's "global" trigger source + a frontend row | Adventures (ph. 7) | Phase 7 kernel+UI work |
| **Pile abstraction** — `supply={name:count}` can't do split/rotating piles | Dark Ages Knights (ph. 6) | Phase 6 kernel work |
| **Turn structure** — Night phase breaks the action/buy enum + auto-advance + frontend phase logic | Nocturne (ph. 11) | Phase 11 |

Rule: when a phase's spec hits one of these, the KERNEL work comes first (stop-the-line, like
Phase 1's durations), the ledger row gets deleted, and the audit agent re-runs on the phase.

**THE TRIGGER BUS (post-Phase-1 hardening):** all off-turn/triggered abilities now flow
through ONE event system — kernel `emit()` (events: gain / buy / play_treasure / trash /
buy_phase_end) consumed by dynamic watchers + the static `TRIGGERS` registry (sources:
hand-reaction window, in-play prompt, self-trigger), plus the `COST_MODS` while-in-play
cost seam. This is the load-bearing design for phases 2+: Prosperity's on-buy (`"buy"` +
in_play), Hinterlands' when-gain (`"gain"` + self — the emit point already exists),
Dark Ages' on-trash (`"trash"` + self), Quarry (`COST_MODS`). A future set should need at
most a NEW EVENT NAME and registry entries — if a set seems to need a new bespoke kernel
mechanism, stop and extend the bus instead.
