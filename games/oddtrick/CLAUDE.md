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

## Two auctions, one game (skat mode, 2026-08-07)

**`mode` is a ROOM FLAG, not a second game** — one `oddtrick_games` table, one
route, one lobby, chosen in the create modal (`CmSeg`) and shown as a badge on
lobby cards. The deal, the piles, the talon, follow-suit, the parity, the
redaction machinery and every `_start_play`-onwards path are **shared verbatim**;
`apply_move` dispatches on `g["mode"]` and both paths converge on `_start_play`.
The design argument is `rust-cores/oddtrick-core/SKAT_MODE.md`.

Classic is described below; this section is only what skat mode adds.

* **Bid a number, name the game later.** `value = base × level`, bases
  **♦2 ♥3 ♠4 ♣5 NT6** (deliberately *inverting* classic's C<D<H<S rank — so the
  two tables can't be confused), Null a flat **20**. The ladder is
  `SKAT_VALUES`, **derived from the bases**, and served via `/catalog`
  (`skat_bases`, `skat_values`) so the client holds no copy.
* **Collisions are the point.** 12 = ♦6 = ♥4 = ♠3 = NT2, so a bid names a price,
  never a shape. The frontend *shows* this (`.odd-clears`) rather than
  explaining it.
* **Phases:** `auction` (numeric) → `talon` → `declare` → `kontra` → [`re`] →
  `play`. `talon` splits into `look` / `hand` / `swap` because **declining to
  look is what Hand means** — the declarer who plays Hand never sees `shown`
  either, in the engine *and* in `view_for`, or Hand would be a free multiplier.
* **Announcements add, they don't multiply**: `mult = 1 + hand + sharp + open`.
  Sharp promises `level + SHARP_BONUS` (3); Open rides on Sharp (except Null,
  which has no margin to sharpen). Kontra ×2 / Re ×4 on top. A multiplier rather
  than a flat bonus because classic's campaign measured a flat +1 *raising* the
  floor cluster — it is proportionally biggest on the smallest contracts.
* **Open is the only path by which one seat legitimately sees the other's hand.**
  `view_for` ships `opp_hand` only when the contract is Open and the phase is
  `play`/`over`, and only to the defender.
* **Both players may pass; both passing redeals.** Safe here and not in classic:
  classic's opener is *forced* to name a contract, so passing would be strictly
  better than a bad one. Here a pass hands the opponent the talon and the lead at
  *their* price. `_redeal` mutates `g` **in place** — the room server, the bot
  scheduler and every open socket hold that exact object.

### Skat mode: things that are not what the spec says
* **SKAT_MODE.md's ladder enumeration is wrong** — it counts 43 rungs and lists a
  7. `base × level` is the rule and 7 is a multiple of no base, so the real
  ladder is **36 rungs with one hole at 7**. `test_skat.py` asserts against the
  *generator*, and pins the hole so nobody "fixes" it back.
* **"Overbid loses automatically" cannot fire, and is deliberately not
  implemented.** The level is the declarer's free 1..12 choice and NT×12 = 72 is
  the top rung, so every legal bid is declarable (`test_every_legal_bid_is_
  declarable`). Stretching is punished *structurally* instead — a big number
  forces you up the level ladder into a contract you can't make, and past 20 it
  locks Null away. Writing the rule anyway would be an untestable branch, which
  the repo's zero-skips policy is the same argument against.
* **The bot's skat thresholds are guesses, not measurements.** `skat_ceiling` is
  the real arithmetic (max over denominations of `base × the level that
  denomination is worth`), but `_KONTRA_TARGET` / `_KONTRA_STRENGTH` are placed
  by hand, and the bot never announces Hand/Sharp/Open and never Res.
  SKAT_MODE.md's five open questions — announcement rates, overbid frequency,
  Null at 20, the Kontra threshold, and whether the mode beats classic on the
  settled-contract distribution — are a **`skatlab` self-play sweep that has not
  been run**. None of them are answered by shipping this.

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
* **The bot scheduler's staleness guard is `_position_key`, and EVERY
  state-advancing action must appear in it.** Two schedulers can be in flight at
  once (`_handle_move` starts one, so does every reconnect), and the guard used
  to be `(phase, trick, len(history), len(auction.log))` — which skat mode broke
  twice over: `look` changes none of those (the duplicate re-sent it and was
  rejected as illegal), and a redeal resets all of them to their opening values
  (so a thrown-in hand reads as "nothing moved"). `redeals`, `looked` and
  `swapped` are in the key for exactly those two reasons.
* **Easy tier used to `KeyError` on its first bid.** Its blunder branch fired in
  *every* non-play phase and read `opt["levels"]`, a key the v2 auction stopped
  returning; the scheduler logged and abandoned the room. It is now scoped to
  the two phases where a careless choice is still a *legal* one.
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

## Tests (247)

`test_engine.py` rules · `test_rust_parity.py` the drift gate ·
`test_ws_auth.py` seat-identity binding + whole-payload redaction ·
`test_integration.py` create → auction → 13 tricks → scored result, vs human
and vs bot, in **both modes** · `test_skat.py` (50) the skat phase machine: the
derived ladder, the redeal, talon/Hand secrecy, declaration validity,
the announcement table, Kontra/Re, the Open reveal, and a `state_json`
round-trip.

Browser side, `webapp/test/screens.mjs` drives the skat **create-modal segment**
through to a dealt room and a first bid — a mounted screen says nothing about
whether a new room flag can actually be created (the Renaissance lesson).

## Not built yet

* **Hard tier.** The plan is `oddtrick-core` compiled to WASM and run
  client-side (Duel pattern; server validates every move). Pool must be capped
  at `min(hc-1, 4)` — the never-take-every-core rule.
* Match play across rounds (currently one round per room), and a `/review`.
