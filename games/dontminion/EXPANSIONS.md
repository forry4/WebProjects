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
`to_island`, `to_village_mat`, `take_village_mat`, `request_extra_turn`,
`duration_in_play`, plus the effects registries `GAIN_REACTIONS` and `CLEANUP_PROMPTS`.
