# Oddtrick — Claude context

Sixth game. Two-player trick-taking where **taking tricks is not simply good**:
even-numbered tricks score **+2** to whoever wins them, odd-numbered ones
**−1**. Six positive against seven negative, so both players' totals always sum
to exactly **+5** — sweeping all thirteen tricks scores 5, while taking exactly
the six even ones scores 12. The game is about *which* tricks you win.

Working name. Renaming costs: the `/oddtrick` route string, the `MODES` entry,
the home card, and the `oddtrick_games` table.

## The reference implementation is Rust, not this Python

`rust-cores/oddtrick-core` is the solver-validated source of truth for the
rules. `engine.py` is a hand port of `state.rs`, and **`tests/test_rust_parity.py`
replays 400 fixtures generated there and demands identical results** — two
implementations of the same rules drift silently otherwise.

The fixtures are **committed** (they feed pytest, which CI runs). Regenerate
after any rules change — the default Rust build is now the 32-card v2 game;
the original 28-card game is behind the `rank7` feature:

```
cd rust-cores/oddtrick-core
cargo run --release --bin gen_fixtures 400 > ../../games/oddtrick/tests/fixtures/play.jsonl
```

That crate also holds the design campaign (`CAMPAIGN.md`) — every scoring rule
below was chosen from measurement, and the negative results are recorded so
nobody re-spends on them.

## Rules as shipped (v2, 2026-08-07)

**32-card deck** (7–A ×4). 13 cards each: **7 in hand + three 2-card piles**.
Only a pile's top is playable; the card under it becomes playable *and public*
when uncovered. The **middle** pile's bottom is dealt face-up to both; the
outer two are hidden from everyone **including the owner**. **Six** cards sit
out, revealed at the end.

**Auction.** Denominations are **ranked C < D < H < S < NT < Null**. Opener
names level 1–12 and a denomination, committing to score at least that many
points. Responses overtake at the **same level in a higher-ranked
denomination**, or **raise by +1/+2** in any denomination that player has not
named. Per-player no-repeat. The opener may not pass. **Null** is a single
rung: it bids as a 6, above NT, and commits the declarer to winning **no +2
trick** — flat **12** made, flat **10** to the defender broken.

**The talon.** The auction winner is shown **3 of the 6** out-cards (fixed at
the deal) and may swap ONE into hand, discarding a hand card face-down — never
a pile card. The defender learns *that* a swap happened, never which cards.

**Play.** Declarer leads trick 1. Null plays at no trump. Follow-suit is
mandatory **and a pile top counts as a card you hold**. May ruff when void,
never forced to. Winner leads next.

**Scoring** (contract only; trick points are the yardstick): make → **N²**;
set → defender scores **(N−1) + 4 × shortfall**. Null: flat 12 / flat 10.

### Why these numbers, in one line each

* **32 cards / 6 out** — the hidden-information sweep's efficient point: 74%
  of the secrecy available at ANY width, and the curve saturates hard past it
  (marginal value per dead card 0.065 → 0.029 → 0.007).
* **ranked denominations** — the first change that ever SPREAD the settled
  distribution instead of translating its spike (level-4 hole 6.7% → 14.2%,
  replicated on both decks). Openers name where it is CHEAP, not where they
  are strong (best-denom openings 45% → 31%), which is the hidden-info point.
* **Null at rung 6, 12/10** — rung is measured: at 3 it was overtaken away in
  100% of auctions; at 8 nobody makes it; raising the price SUPPRESSES it
  (33%-make gamble, only worth taking while losing is cheap). In play it is a
  **sacrifice valve** — all 18 observed contracts arrived by overtake, none by
  opening.
* **the swap** — makes winning the auction worth something beyond the
  contract, adds real overbid risk, and the discard is a bluffable signal.
* **maxraise 2** — a cap of exactly 2 relocates the punishment-landing pile
  from level 2 to level 3, which is where the distribution had a hole. A cap of
  3 empties level 3 again; the spike *translates*, it never spreads.
* **declarer leads** — the opening lead was measured at **+0.93 pts**, the
  strongest single lever on contract height — and the reason Null exists at
  all (its make rate defending is ~0%).
* **N² make / linear set** — the make/set RATIO is what lifts bidding. Matched
  curves cancel: N² on both left the floor cluster identically at 42.7%.
* **short 4** — the sacrifice dial. Doubling it roughly halves sacrifice bids.
* **per-player denominations** — a shared budget was measured to be a no-op:
  94% of auctions name ≤2 denominations, so a budget of five never binds.

## Do not relitigate

* **Optional follow-suit is rejected.** With negative odd tricks it makes every
  odd trick fall deterministically to whoever leads it — 7 of 13 tricks lose
  all decision content.
* **The bot never bids Null.** It is a 33%-make gamble under EXACT play; a
  one-trick-deep policy has no business finding the other 67%. Revisit only
  with the WASM Hard tier.
* **v1 saves are voided on load, not migrated.** A 28-card save's card indices
  mean different cards under `suit = c // 8`; the prod table was verified
  EMPTY when v2 shipped, so the guard in `load_game_to_memory` is for
  completeness.
* **No `rng_state` is persisted.** All randomness is spent in the deal and
  nothing draws later, so storing one would be ~600 words nothing reads (the
  Where Wolf? lesson). This also sidesteps the "pack every copy or none" trap.
* **Card play strength is understood.** Determinizations saturate at k=8; the
  cheating oracle beats PIMC by 0.79 pts/round and most of that is irreducible
  hidden information. Opponent-consistency resampling, Vote/Quantile
  aggregators and an IIMC blend were all measured and all washed — see
  `CAMPAIGN.md` before spending on any of them.
* **The floor cluster was structural, not a scoring problem.** ~42% of openings
  sat at level 1 under *every* scoring configuration tried. It is caused by the
  opener being forced to bid with nowhere to put a weak hand; only unlimited
  jump overtakes (42.7% → 2.7%) or letting the opener pass (→ 0%) moved it, and
  both cost the maneuvering game. Shipped config keeps forced opening.

## Layout

| file | what |
|---|---|
| `engine.py` | the rules + per-seat redaction (`view_for`). JSON-safe dict. |
| `bot.py` | Easy/Normal server bot; `policy_score` is a port of `policy.rs`. |
| `persist.py` | at-rest compaction boundary — drops `played` (derivable), packs `history` triples into ints. |
| `main.py` | `oddtrick_app` @ `/oddtrick`, on `core.rooms` primitives. |
| `Oddtrick.jsx` / `.css` | frontend; CSS via `?inline`, never a JS literal. |

Cards render as **rank + suit glyph in CSS** — there are no image assets and
none are needed. Suits differ by glyph as well as colour, so red/black is never
the only signal.

## Wiring points (there are five, and one is easy to miss)

1. `shared/router.js` → `MODES`
2. `games/spender/Spender.jsx` → `lazyChunk` + `<Suspense>` branch
3. **`games/spender/Spender.jsx` → `SCREEN_FOR_MODE` *and* `MODE_FOR_SCREEN`** —
   missing these is why the chunk was never fetched; the route resolved to no
   screen at all and the `screens` gate caught it.
4. `shared/HomeScreen.jsx` → card + icon
5. `webapp/test/screens.mjs` → `SCREENS` entry, marker `.odd`

`LobbyHeader`'s `user` prop takes a **node**, not the auth object — passing
`authUser` raw throws React error #31 and blanks the screen.

## Tests (189)

`test_engine.py` rules · `test_rust_parity.py` the drift gate ·
`test_ws_auth.py` seat-identity binding + whole-payload redaction ·
`test_integration.py` create → auction → 13 tricks → scored result, vs human
and vs bot.

## Not built yet

* **Hard tier.** The plan is `oddtrick-core` compiled to WASM and run
  client-side (Duel pattern; server validates every move). Pool must be capped
  at `min(hc-1, 4)` — the never-take-every-core rule.
* Match play across rounds (currently one round per room), and a `/review`.
