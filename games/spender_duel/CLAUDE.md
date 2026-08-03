# Spender Duel (Splendor Duel) — package notes

Strictly 2-player. Mounted at `/duel`. LIVE on prod. See the root `CLAUDE.md` for the room-server
invariants and deploy; full AI campaign detail in `docs/ai-research-log.md`.

---

## Engine + hidden information

- **Hidden info is first-class:** `player_view(game, pid)` strips `bag` (→ `bag_count`), `decks` (→
  `deck_counts`), rng, and the OPPONENT's reserve identities (→ `{level, facedown}`); reveals all at game
  over. `main.py` broadcasts **per-recipient views** (`broadcast_state`) — the one structural difference
  from CoC/WW's shared snapshot. Blind deck reserves log level only.
- **Cell choices are strategic, not cosmetic** — take-same resolution, privilege takes, the reserve's gold
  token all carry a board CELL index (removing a specific token changes line-take geometry). Don't
  "simplify" them to color choices.
- **Turn pipeline:** one mandatory action → `_after_action` recheck loop (royal entitlement
  `(crowns>=3)+(crowns>=6)` vs `royals_claimed`; then discard-to-10) → `_finish_turn` (victory check
  pre-empts the AGAIN extra turn). Payments return to the BAG (not a bank); token conservation (exact
  25-multiset across board+bag+hands) is soak-tested after every move.
- Pending sub-decisions are game-state keys (`pending_pid`/`pending_kind`/`pending`), server-enforced
  and reconnect-safe.
- **Review** (`replay.py`): reconstruction is EXACT from the persisted seed + move log (no `setup`
  snapshot needed — `new_game` is seeded). The log interleaves player moves with engine-written records
  (auto-abilities, `again`, `extra_turn`), and an auto-resolved take is byte-identical to a chosen one —
  so records can't be classified by shape; `_replay` lets the engine disambiguate by counting how many
  records the sim's log grew by. A finished game reveals reserves.
- **Turn undo is gated on HIDDEN INFORMATION, not on which actions you took.** `undo_turn` restores the
  whole turn from `turn_undo` (a full snapshot, taken at turn start and stripped from `player_view` —
  it contains the bag and decks). It is refused once `turn_flags["revealed"]` is set, which
  `_mark_revealed` does whenever a card is flipped face up off a deck or tokens are drawn out of the
  bag. That closes the documented blind-reserve exploit (reserve off a deck, read the top card, undo)
  WITHOUT reshuffling — a reshuffle is a random event that never reaches the log, so `replay.py` would
  diverge from what was played. In practice the guard only bites while the turn is still yours:
  reserve/buy are the MANDATORY action and pass the turn on anyway, so the case it really protects is
  **a pyramid buy that opens an ability sub-decision** (new card flipped up, turn not yet over), plus
  replenish. `legal_moves` deliberately omits `undo_turn`, which keeps the bot from taking it and stops
  a tampered client smuggling one through `ai_move`.
- **The snapshot stores `_log_len`, not the log.** The log is the only unbounded-growth structure in
  the dict (everything else is bounded by 66 cards and 25 tokens) and `save_game` persists `turn_undo`
  with the game, so copying it in wrote the log twice per save. `_log` only appends, so the turn-start
  log is exactly `log[:_log_len]` and undo truncates back. Worth **-28% on the raw dict** but only
  **-2.7% stored** — zlib was already deduping the near-identical copy, so the real win is the per-turn
  deepcopy and the per-save serialize/compress, not disk. (CoC's equivalent needs a monotonic counter
  rather than a length, because its log PREPENDS and evicts; Duel's appends, so a length is exact.)
  Post-fix `turn_undo` is 3.3% of the stored blob and the log itself is 28% — shrinking that further
  would mean changing a format both `replay.py` and the frontend read, for a measured ~0.1%.
- **AI determinization needs `players[pid]["reserved_from_deck"]`** (a list of card ids stripped by
  `player_view`) — the log can't answer "was this reserve blind?" because it omits `card_id` for blind
  draws. Blind reserves resample PER LEVEL (which deck is public; identity is secret).

---

## AI tiers — Easy / Normal / Hard / Expert

| Tier | What it is | Lever |
|---|---|---|
| **Easy** | `bot.py` random-legal | — |
| **Normal** | determinized MCTS, **softmax(Q/T) sampling** (T≈0.08) | temperature (beatable — throws ~90% of games by design) |
| **Hard** | coherent MCTS + card-set **attention value net** leaf (`ATTN_NET`, the v2 champion) | the net |
| **Expert** | the same search + **`EXPERT_NET`** (policy+value "netB") + **minimax selection** + an **AZ policy prior at T\*=2.0** | the net; the search knobs below |

Ported to Rust→WASM and served **client-side** (`rust-cores/duel-core`). Entry points are
`duel_search` (Hard) and `duel_search_expert` (Expert) in `src/wasm.rs` — a separate entry rather than a
tier param, so the Hard worker call stays byte-unchanged. `duel_pick_move` is net-independent (pooled
greedy pick) and shared. Nets are **embedded in the wasm** (`include_str!`), not fetched — unlike CoC, a
net swap here DOES need a wasm rebuild.

### The serving shape — and the rule that comes with it

The live bot fans one decision across **4 independent workers** (`min(hardwareConcurrency-1, 4)` — never
take every core), each searching **its own tree** with its own determinized world, then **sums only the
ROOT stats** by move index and makes one greedy pick. Because each worker holds one coherent world, the
pool is an N-world coherent ensemble that hedges strategy fusion.

> **Tune at K=1, CONFIRM at pool=N.** Every headline number in this campaign (coherent 0.585, minimax
> 0.62/0.67, prior 0.589, visits-vs-qsoftmax 0.655) is a **single-tree K=1** measurement, and the flag
> that looked like it covered the ensemble did not: `Opts::root_dets` runs K worlds into ONE SHARED
> tree, so world 2 descends statistics world 1 wrote — a different algorithm. Use
> `root_search_pooled_with_leaf` / `gate_netleaf --pool N`, which reproduce serving exactly. Self-gate
> at pool=4 reads 0.5000.

Budget (`main.py`): **3.5s wall-clock OR 20k aggregate sims**, whichever comes first, split evenly across
the pool. `CLIENT_AI_TIMEOUT = 8.0` → the server plays the move itself with the Python bot (per-decision,
so a flaky client costs sims, never a stuck game). Coherent+minimax makes each sim a
real deepening of one sound world, pushing saturation outward; at ~1420 sims/s/core the TIME bound now
governs on desktop too. **The saturation ladder under the new search is still pending.**

### The 2026-07-26/27 search findings (the current basis — do not relitigate)

- **COHERENT search** (determinize once, hold chance fixed for the whole tree) beats the old per-sim PIMC
  **0.585** (n=400, mirror 0.5000). Shipped to both Hard and Expert. `prior_c: 1.0` is the winning
  plateau (0.3–1.0).
- **`select()` was MAX-MAX** — it maximized the ROOT's value even at OPPONENT nodes, i.e. modeled an
  opponent who cooperates. Invisible under per-sim noise; worth **0.62 @c_puct 1.0 / 0.67 @c_puct 0.3**
  once coherent search let visits concentrate. Control 0.5000 exact. **Expert only** — Hard is
  byte-unchanged.
- **AZ policy prior GO at T\*=2.0**, a clean interior optimum (0.5 sharp → 0.446 HURTS; 1.0 → 0.524;
  2.0 soft → **0.5887** [.554,.622]). Guide, don't dominate. Requires a policy head, so Expert only.
  The edge decays with per-world depth (0.535 @4000 sims) — **re-verify if the sims/worker budget moves.**
- **VISITS beat qsoftmax as the training target, 0.655 vs 0.589.** The canonical AZ choice was only ever
  abandoned here because per-sim determinization flattened visits.
- **Lazy PUCT priors = 1.55× more sims, bit-identical** (`f4c2864`). This mattered for more than speed:
  the prior was net-NEGATIVE at its original cost by equal-TIME arithmetic, and only the speedup made it
  positive.
- **`Opts::opp_c`** sets `c_puct` at nodes whose actor isn't the root player — low = hard minimax, high =
  closer to expectimax. Unset = same c as ours = shipped behaviour, byte-identical. Both ends are wrong
  in principle (hard minimax in a determinized search models an opponent who can see the sampled hidden
  world — classic PIMC over-pessimism; pure averaging was the per-sim era's accident), so the optimum
  should be interior. `tools/opp_model_sweep.py` screens at K=1 then confirms at `--pool 4`.
- **Rollout costs nothing with an attention leaf** — the repo's heuristic-leaf "rollout is expensive"
  fact does NOT transfer here.

### Standing constraints

- **NO human game data.** There isn't enough of it; never propose a human corpus for Duel training. All
  strengthening is no-data: leaf augmentation, targeted self-play, architecture, search.
- Judge with CRN paired arenas; the mirror sanity must read exactly 0.5000; ship criterion is EQUAL-TIME.

### Campaign tooling (`rust-cores/duel-core/tools/`)

`phase1_overnight` (runoff → pivotal harvest → GO/NO-GO; `P1_MINIMAX`/`P1_RESUME_FROM_RUNOFF`),
`az_pv_loop` (the flywheel; `AZ_MINIMAX`, `AZ_PTARGET`), `runoff` (disjoint-seed winner's-curse de-bias),
`hp_sweep` (`HP_GATE` to use a side build), `k_sweep`, `az_loop`, `opp_model_sweep`. Build to a side dir
(`target-*/`, gitignored) — cargo can't relink an `.exe` another process is running, which is how a
rebuild coexists with a multi-hour gate.

---

## Tests

`tests/` — card invariants, `player_view` redaction, `test_ws_auth.py`, and a bot-vs-bot soak with the
25-token conservation invariant. Rust: `cargo test --lib` in `rust-cores/duel-core` (37 lib tests,
including one pinning minimax `select()` semantics — at an opponent node it must take the root's WORST
reply where max-max takes its best).
