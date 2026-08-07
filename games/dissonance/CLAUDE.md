# Dissonance — Claude context

Sixth game. Two-player trick-taking where **taking tricks is not simply good**:
even-numbered tricks score **+2** to whoever wins them, odd-numbered ones
**−1**. Six positive against seven negative, so both players' totals always sum
to exactly **+5** — sweeping all thirteen tricks scores 5, while taking exactly
the six even ones scores 12. The game is about *which* tricks you win.

**Renamed from Oddtrick (2026-08-07)** — the working name is gone from the route
(`/dissonance`), the `MODES` entry, the home card, the package, the Rust crate,
the `.dis-*` CSS prefix and the table. Three things still carry the old name ON
PURPOSE, all of them inside the committed wasm and none of them reachable from
a rename:

* **`odd_pick_card` / `odd_best_card` / `odd_pool`** are the wasm EXPORT names,
  baked into the artifact's export table. The Rust source keeps them for the
  same reason: source and artifact have to agree, and renaming one without
  rebuilding the other breaks the Hard tier at runtime with an import error.
  Rename them in `src/wasm.rs`, the glue and the worker in ONE commit that also
  ships a fresh `wasm-pack` build, or not at all.
* **`"./oddtrick_bg.js"`** in `webapp/public/wasm/dissonance.js` is the wasm's
  declared import-module key, matched against the glue's own object key — never
  against a filename. It is length-prefixed inside the binary, so it only moves
  at a rebuild. The FILES were renamed (`dissonance.js` / `dissonance_bg.wasm` /
  `dissonance-worker.js`) because those are plain strings in the glue and the
  worker; the lib name in `Cargo.toml` is now `dissonance`, so the next
  `wasm-pack` build emits exactly those filenames and this key resolves itself.
* **`main.LEGACY_TABLE`** — prod rows live in `oddtrick_games`, so
  `dissonance_init_db` ADOPTS that table via `ALTER TABLE ... RENAME TO` before
  its own `CREATE TABLE IF NOT EXISTS` can mint an empty one beside it. Guarded
  on old-present-and-new-absent, so it fires once, no-ops on a fresh checkout,
  and never overwrites a live table with a stale one. `tests/test_table_rename.py`
  pins all four cases; the libsql path is untestable locally as always.

There is no `/oddtrick` redirect and no localStorage fallback (deliberate, per
the rename brief): old invite links no longer resolve, and anyone mid-game gets
a fresh reconnect token — they rejoin by room code.

## The reference implementation is Rust, not this Python

`rust-cores/dissonance-core` is the solver-validated source of truth for the
rules. `engine.py` is a hand port of `state.rs`, and **`tests/test_rust_parity.py`
replays 400 fixtures generated there and demands identical results** — two
implementations of the same rules drift silently otherwise.

The fixtures are **committed** (they feed pytest, which CI runs). Regenerate
after any rules change — the default Rust build is now the 32-card v2 game;
the original 28-card game is behind the `rank7` feature:

```
cd rust-cores/dissonance-core
cargo run --release --bin gen_fixtures 400 > ../../games/dissonance/tests/fixtures/play.jsonl
```

That crate also holds the design campaign (`CAMPAIGN.md`) — every scoring rule
below was chosen from measurement, and the negative results are recorded so
nobody re-spends on them.

## Two auctions, one game (skat mode, 2026-08-07)

**`mode` is a ROOM FLAG, not a second game** — one `dissonance_games` table, one
route, one lobby, chosen in the create modal (`CmSeg`) and shown as a badge on
lobby cards. The deal, the piles, the talon, follow-suit, the parity, the
redaction machinery and every `_start_play`-onwards path are **shared verbatim**;
`apply_move` dispatches on `g["mode"]` and both paths converge on `_start_play`.
The design argument is `rust-cores/dissonance-core/SKAT_MODE.md`.

Classic is described below; this section is only what skat mode adds.

* **Bid a number, name the game later.** `value = base × level`, bases
  **♦2 ♥3 ♠4 ♣5 NT6** (deliberately *inverting* classic's C<D<H<S rank — so the
  two tables can't be confused). The ladder is
  `SKAT_VALUES`, **derived from the bases**, and served via `/catalog`
  (`skat_bases`, `skat_values`) so the client holds no copy.
* **Collisions are the point.** 12 = ♦6 = ♥4 = ♠3 = NT2, so a bid names a price,
  never a shape. The frontend *shows* this (`.dis-clears`) rather than
  explaining it.
* **Phases:** `auction` (numeric) → `talon` → `declare` → `kontra` → [`re`] →
  `play`. `talon` splits into `look` / `hand` / `swap` because **declining to
  look is what Hand means** — the declarer who plays Hand never sees `shown`
  either, in the engine *and* in `view_for`, or Hand would be a free multiplier.
* **Announcements add, they don't multiply**: `mult = 1 + hand + sharp + open`.
  Sharp promises `level + SHARP_BONUS` (2); Open rides on Sharp. Kontra ×2 /
  Re ×4 on top. A multiplier rather
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
  make. Writing the rule anyway would be an untestable branch, which
  the repo's zero-skips policy is the same argument against.
* **The bot's skat thresholds are guesses, not measurements.** `skat_ceiling` is
  the real arithmetic (max over denominations of `base × the level that
  denomination is worth`), but `_KONTRA_TARGET` / `_KONTRA_STRENGTH` are placed
  by hand, and the bot never announces Hand/Sharp/Open and never Res.
  SKAT_MODE.md's open questions — announcement rates, overbid frequency, the
  Kontra threshold, and whether the mode beats classic on the
  settled-contract distribution — are a **`skatlab` self-play sweep that has not
  been run**. None of them are answered by shipping this.

## Rules as shipped (v2, 2026-08-07)

**32-card deck** (7–A ×4). 13 cards each: **7 in hand + three 2-card piles**.
Only a pile's top is playable; the card under it becomes playable *and public*
when uncovered. The **middle** pile's bottom is dealt face-up to both; the
outer two are hidden from everyone **including the owner**. **Six** cards sit
out, revealed at the end.

**Auction.** Denominations are **ranked C < D < H < S < NT**. Opener
names level 1–12 and a denomination, committing to score at least that many
points. Responses overtake at the **same level in a higher-ranked
denomination**, or **raise by +1/+2** in any denomination that player has not
named. Per-player no-repeat. The opener may not pass.

**The talon.** The auction winner is shown **3 of the 6** out-cards (fixed at
the deal) and may swap ONE into hand, discarding a hand card face-down — never
a pile card. The defender learns *that* a swap happened, never which cards.

**Play.** Declarer leads trick 1. Follow-suit is
mandatory **and a pile top counts as a card you hold**. May ruff when void,
never forced to. Winner leads next.

**Scoring** (contract only; trick points are the yardstick): make → **N²**;
set → defender scores **(N−1) + 4 × shortfall**. **NULL OVERRIDES A SET**: a
declarer who won **no +2 trick all round** scores a flat **12** (skat: **20**)
instead, whatever they declared. **A round stops the moment the score can no
longer change** — see below.

### Why these numbers, in one line each

* **32 cards / 6 out** — the hidden-information sweep's efficient point: 74%
  of the secrecy available at ANY width, and the curve saturates hard past it
  (marginal value per dead card 0.065 → 0.029 → 0.007).
* **ranked denominations** — the first change that ever SPREAD the settled
  distribution instead of translating its spike (level-4 hole 6.7% → 14.2%,
  replicated on both decks). Openers name where it is CHEAP, not where they
  are strong (best-denom openings 45% → 31%), which is the hidden-info point.
* **Null is not a bid (2026-08-07)** — and every measurement of it as one said
  the same thing. At rung 3 it was overtaken away in 100% of auctions; at 8
  nobody makes it; raising the price SUPPRESSES it (a 33%-make gamble is only
  worth taking while losing is cheap); all 18 observed contracts arrived by
  OVERTAKE, none by opening. As a purchase it was either free or dead. It is a
  **consolation** now, live under every contract at once — which is what the
  "sacrifice valve" reading always wanted, at no auction cost.
* **the swap** — makes winning the auction worth something beyond the
  contract, adds real overbid risk, and the discard is a bluffable signal.
* **maxraise 2** — a cap of exactly 2 relocates the punishment-landing pile
  from level 2 to level 3, which is where the distribution had a hole. A cap of
  3 empties level 3 again; the spike *translates*, it never spreads.
* **declarer leads** — the opening lead was measured at **+0.93 pts**, the
  strongest single lever on contract height — and the reason Null is a
  DECLARER'S consolation (its make rate defending is ~0%).
* **N² make / linear set** — the make/set RATIO is what lifts bidding. Matched
  curves cancel: N² on both left the floor cluster identically at 42.7%.
* **short 4** — the sacrifice dial. Doubling it roughly halves sacrifice bids.
* **per-player denominations** — a shared budget was measured to be a no-op:
  94% of auctions name ≤2 denominations, so a budget of five never binds.

## A round stops when the SCORE stops moving (2026-08-07)

`_score_is_settled` is checked after every completed trick, and the bar is the
SCORE, not the outcome — which is why only one direction of "decided" ends a
round early:

* **Cannot fail** → stop. If the declarer clears the target even after losing
  every remaining +2 trick and being handed every remaining −1, the contract is
  made, and a made contract pays a flat N² (or the skat stake) that does not move
  with the final total.
* **Cannot make** → play on. Being mathematically set does NOT settle the score:
  the defender is paid `(N−1) + 4 × shortfall`, and every remaining trick still
  moves the shortfall. Holding a busted declarer down is a real contest, and the
  Null consolation makes it a live one from the other side too.
* **Null** gets no early exit of its own. It used to (as a bid it was decided the
  moment the declarer took a scoring trick), but as a consolation it is settled
  early only when no +2 trick remains — which by the parity of the trick values
  can only ever save the thirteenth, and the floor below now forbids that anyway.
* **Never with ONE trick left** (2026-08-07). Stopping a trick from home saves
  nothing and costs the hand its last beat — the trick where the shortfall and
  the Null consolation are both still live, i.e. the one most worth watching.
  `_score_is_settled` returns False below two remaining, so the earliest stop
  leaves at least two. Pinned at the predicate by
  `test_the_last_trick_is_always_played_out` rather than by a seed sweep: the
  position is common enough to matter and rare enough that random play passing
  is no evidence it was checked.

**A round that stopped early reports "scored AT LEAST N".** The score is exact —
that is the whole precondition for stopping — but the trick TOTAL is not, because
the unplayed tricks would still have moved it. Printing the running total as if
it were final reads as a miscount, so the result panel says "at least" whenever
`result.ended_early` (which only ever coincides with a MADE contract, since a set
one plays on).

**`pts` sums to POOL only over a COMPLETED round.** Every conservation assertion
has to say "a round that ran to thirteen tricks"; four tests and one fixture
generator learned that the hard way.

**The Rust parity harness names a `MAX_LEVEL` contract on purpose.** The
reference always plays all thirteen tricks, so `_game_from` has to describe a
contract that can never settle early — at its old level of 1 the early end fired
most of the way through most deals and every fixture's final points diverged.
MAX_LEVEL works because one player's ceiling is sweeping the six +2 tricks;
`test_rust_parity` asserts that relationship rather than assuming it.

## The talon reveal describes WHAT HAPPENED, not the final position

`shown` is the record of the three cards the declarer was shown, fixed at the
deal. **`apply_swap` must never rewrite it.** It used to — the taken card was
replaced in place by the discard, keeping `shown` in step with `out` — and the
round-end reveal then named the discarded card as one the declarer "was shown",
when that card had come out of their own hand and may never have been near the
talon. `out` DOES change (the discard really is out of play now, and the reveal
has to show the six cards that actually sat out); `swap_take` / `swap_give`
record which cards moved, and are **redacted until the round is over** — the
defender learns THAT a swap happened and nothing more, which is the entire point
of the discard going face-down.

The same mistake had a second form: the reveal said "was shown" even for a skat
**Hand** game, where declining to look IS the announcement and the declarer never
saw the talon at all. The frontend gates that line on `sawTalon`
(`!isSkat || game.looked`).

Both are one error — describing the talon from the final position instead of from
what happened. `test_engine.py` pins the record, the redaction and the decline;
one pre-existing test asserted the old behaviour outright and was corrected.

## Do not relitigate

* **No card is ever dimmed** (2026-08-07). Every face-up card renders
  identically, playable or not; legality lives in the `play` affordance and is
  enforced server-side. Two earlier versions of this failed differently and both
  are recorded in the stylesheet: `opacity` let a pile's buried card show
  straight through its top so the two read as one smeared card, and the
  `filter: brightness()` that replaced it fixed the transparency while keeping
  the real problem — a hand that read as two different kinds of card.
  `screens.mjs` now guards the absence (no `dim` class, no reduced opacity, no
  filter), sampled MID-round: the check it replaced ran after the game was over,
  when every pile is exhausted, so it read all-zeroes on every run and could
  never pass.
* **Optional follow-suit is rejected.** With negative odd tricks it makes every
  odd trick fall deterministically to whoever leads it — 7 of 13 tricks lose
  all decision content.
* **Neither tier CHASES the Null consolation, and both should.** A declarer
  whose contract has gone wrong ought to switch to ducking every +2 trick — but
  "has gone wrong" is a lookahead judgement, and the server bot is one trick
  deep (reading it off the current total instead would throw away contracts it
  was still winning). The Hard tier misses it for a different reason: its solver
  maximises trick POINTS, and Null is a discontinuous jump a double-dummy value
  function cannot see. Both want the contract-aware solve `dd::solve_contract`
  already provides for the auction.
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

## The completed-trick beat (frontend, and it is timing — nothing else can see it)

A finished trick stays face up for `TRICK_HOLD_MS` (700) before it moves to the
Last trick panel, because the server clears `led` the instant the second card
lands. Three things about it are load-bearing, all three MEASURED in a browser
against a live backend (`screens.mjs`, "Dissonance's completed-trick beat"):

* **The hold covers `over`, not just `play`.** The thirteenth trick, and any
  trick that settles the score, ends the game in the SAME message that completes
  the trick, so a hold gated on `phase === "play"` skipped the one trick a player
  most wants to see: measured 700ms on every other trick and **0ms on the last**,
  swapped straight for the result panel. `wasPlaying` keeps that to a game that
  ended under you — opening a finished room from the lobby must not replay its
  last trick at you first.
* **The hold BLOCKS play** (`canPlay = myTurn && !heldTrick`). A trick takes
  ~600ms at full tilt against the 450ms bot floor, so a player who answered
  inside the hold was leading the next trick behind a screen still showing the
  last one: their card sat invisible, the opponent's reply landed in the same
  window, and two finished tricks ran together with a **single 18ms frame**
  between them. Nothing is swallowed — a card with no click handler also loses
  its `.play` affordance, so the hand visibly stops offering itself.
* **The trick line is about the trick you are LOOKING at.** `game.trick` has
  already moved on during a hold, so reading it there labelled the two cards
  with the next trick's number and the next trick's ±value.

The gate plays a whole game at full tilt and asserts every dwell; it reads
695–700ms on all thirteen tricks. A polling loop from Node cannot see a state
that lasts one frame, so it samples per `requestAnimationFrame` in the page.

## Layout

| file | what |
|---|---|
| `engine.py` | the rules + per-seat redaction (`view_for`). JSON-safe dict. |
| `bot.py` | Easy/Normal server bot; `policy_score` is a port of `policy.rs`. |
| `persist.py` | at-rest compaction boundary — drops `played` (derivable), packs `history` triples into ints. |
| `main.py` | `dissonance_app` @ `/dissonance`, on `core.rooms` primitives. |
| `Dissonance.jsx` / `.css` | frontend; CSS via `?inline`, never a JS literal. |

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
5. `webapp/test/screens.mjs` → `SCREENS` entry, marker `.dis`

`LobbyHeader`'s `user` prop takes a **node**, not the auth object — passing
`authUser` raw throws React error #31 and blanks the screen.

## Tests (259)

`test_engine.py` rules · `test_rust_parity.py` the drift gate ·
`test_ws_auth.py` seat-identity binding + whole-payload redaction ·
`test_integration.py` create → auction → 13 tricks → scored result, vs human
and vs bot, in **both modes** · `test_skat.py` (50) the skat phase machine: the
derived ladder, the redeal, talon/Hand secrecy, declaration validity,
the announcement table, Kontra/Re, the Open reveal, and a `state_json`
round-trip · `test_client_ai.py` (12) the Hard tier's protocol: the armed
request, the re-validation, the stale drop, the watchdog, and the picker/server
tier agreement.

Rust side, `cargo test --features bridge` runs `wire::fixture_replay` — the
wire-reader gate above.

Browser side, `webapp/test/screens.mjs` drives the skat **create-modal segment**
through to a dealt room and a first bid — a mounted screen says nothing about
whether a new room flag can actually be created (the Renaissance lesson) — plays
a **whole Hard game** and counts `client_ai_ready` / `ai_move` on the socket
(every failure in the Worker→wasm→fetch chain degrades to the server bot, so a
game that plays out perfectly is exactly what the fallback looks like), and
measures the **completed-trick beat** described above.

## The Hard tier — an exact solver, in the player's browser (2026-08-07)

`easy` / `normal` / **`hard`**. Hard's CARD PLAY is `dissonance-core`'s `PimcBot`
compiled to WASM and run client-side; its auction is still the server's
heuristic. The reference measured the one-trick-deep policy **69.8% behind
`pimc:8`**, so this is the ladder's real rung.

* **Why client-side, and why it could never be otherwise.** The search is an
  EXACT double-dummy solve per sampled deal: `bin/bench` times one full solve at
  ~74ms natively and the wasm measures **~70ms per world at trick 1**, collapsing
  to ~0 by trick 7. Render's free tier is ~0.1 CPU with five games on one uvicorn
  process. The player's own cores are the only place this fits.
* **The strength knob is the WORLD COUNT and nothing else.** Sampling saturates
  at k≈8 (CAMPAIGN.md), so the server caps the pooled total at 8 and the worker's
  millisecond budget only exists so a slow phone still answers.
* **Pooling sums per-move VALUES, indexed by `State::legal`** — a pure function
  of the position, so index *i* is the same card in every worker and in the pick.
  Sums over disjoint world samples add, so the pooled answer is exactly what one
  worker with the combined `k` would compute. The pick rule (highest total, ties
  to the earliest legal move) lives in `odd_best_card`, NOT in the worker's JS —
  a copy that drifted would be a different bot with the same name.
* **Pool size is `max(1, min(hc-1, 4))`** — the never-take-every-core rule. Two
  other games shipped without it for months.
* **Only card play goes to the browser.** An auction decision is `eval_hand`:
  ten exact solves per sampled world against card play's one, i.e. multiple
  seconds for a bid. Hard is a card-play tier until that is measured.
* **Nothing is trusted.** The card arrives over the human's own socket and is
  re-validated against `legal_moves` for the BOT's seat; a refusal is treated
  exactly like silence. A tampered client can only weaken its own opponent.
* **Degradation is per-DECISION, so a browser can never stall a room**: an
  unarmed client, a timeout (`CLIENT_AI_TIMEOUT`), a stale reply and an illegal
  card all fall through to the server bot for that one decision. The armed
  request lives in ROOM STATE (`_ai_search`), so every re-broadcast and every
  reconnect re-ships it; `release_socket(disarm_client_ai=True)` clears the
  opt-in when the tab goes, and a reconnecting client re-arms itself.
* **The staleness key is a monotonic counter, not the ply.** Every play happens
  to append exactly one history entry today, but nothing ENFORCES that, and two
  decisions sharing a key make a late reply indistinguishable from a fresh one.
* **The wire reader is a SECOND parity surface** (`src/wire.rs`), and it fails
  silently: a reader that mis-sizes the hidden pool, drops a suit void or
  mistakes which pile bottom is public still returns a legal card, just a worse
  one — a room that says Hard while playing below it, with nothing red anywhere.
  Hence `views.jsonl` (committed, both seats, both modes, every ply of four
  games, from `tools/gen_view_fixtures.py`) and the `wire::fixture_replay` tests.
  It reads `view_for` itself rather than a second projection, so the redaction
  boundary the server already rests on is the one the bot searches.
* **Rebuilding the artifact**: `wasm-pack build --target web --release
  --no-typescript` in `rust-cores/dissonance-core`, then copy `pkg/dissonance.js` +
  `pkg/dissonance_bg.wasm` into `webapp/public/wasm/` and COMMIT them. CI does not
  build Rust and the crate is in neither deploy path filter, so committing one
  never deploys anything on its own. Same filename ⇒ browsers may serve the
  cached old wasm (~10 min Pages TTL).

## Not built yet

* **A Hard auction.** `auction.rs` / `skat.rs` already hold solvers over
  `eval_hand`; what is missing is a measurement that the cost is worth paying at
  a bid, and a `SkatCfg` tied to the engine's own price table rather than the
  crate's default.
* Match play across rounds (currently one round per room), and a `/review`.
