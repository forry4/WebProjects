# Dissonance — Claude context

Sixth game. Two-player trick-taking where **taking tricks is not simply good**:
even-numbered tricks score **+2** to whoever wins them, odd-numbered ones
**−1**. Six positive against seven negative, so both players' totals always sum
to exactly **+5** — sweeping all thirteen tricks scores 5, while taking exactly
the six even ones scores 12. The game is about *which* tricks you win.

**Renamed from Oddtrick (2026-08-07)** — the working name is gone from the route
(`/dissonance`), the `MODES` entry, the home card, the package, the Rust crate,
the `.dis-*` CSS prefix and the table. Two things still carry the old name ON
PURPOSE, and a third resolved itself exactly as this section predicted:

* **`odd_pick_card` / `odd_pick_bid` / `odd_best_card` / `odd_pool`** are the
  wasm EXPORT names,
  baked into the artifact's export table. The Rust source keeps them for the
  same reason: source and artifact have to agree, and renaming one without
  rebuilding the other breaks the Hard tier at runtime with an import error.
  Rename them in `src/wasm.rs`, the glue and the worker in ONE commit that also
  ships a fresh `wasm-pack` build, or not at all.
* ~~**`"./oddtrick_bg.js"`**, the wasm's declared import-module key~~ — RESOLVED
  as predicted. It is length-prefixed inside the binary and matched against the
  glue's own object key, never against a filename, so it could only move at a
  rebuild; the Hard auction shipped one and it now reads `"./dissonance_bg.js"`.
  Anything rebuilding this artifact must ship the glue and the `.wasm` from the
  SAME `wasm-pack` run — they are a matched ABI pair, and a mixed pair fails at
  `init()`, which the client-AI path degrades silently from.
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
  **♦2 ♥2 ♠3 ♣3 Grand4 NT5** — priced by COLOUR. The ladder is
  `SKAT_VALUES`, **derived from the bases**, and served via `/catalog`
  (`skat_bases`, `skat_values`) so the client holds no copy.
  **`SKAT_BASE` is indexed by DENOMINATION and is SPARSE**: index 5 is
  `NULL_DENOM` and carries a base of 0, the marker for "not on the ladder".
  Iterate `SKAT_DENOMS`, never `range(len(SKAT_BASE))` — and the client filters
  `base > 0` for the same reason (`levelsFor`), because a 0 divides to Infinity
  and only failed to render by accident.
* **Collisions are the point.** 12 = ♦6 = ♥6 = ♠4 = ♣4 = Grand3, so a bid names
  a price, never a shape. The frontend *shows* this (`.dis-clears`) rather than
  explaining it.
* **The colour pricing replaced a four-tier table (D2 H3 S4 C5 NT6), 2026-08-07,
  and it is a deliberate partial reversal.** The original argument still holds
  where it is load-bearing: the suits are *measured* symmetric (settled-
  denomination evenness 0.943), and the prices exist to manufacture an asymmetry
  the game does not otherwise have. Four tiers was too much of it — a hand
  equally playable in hearts and spades was priced a whole rung apart for a
  reason no player could name, and the cheap suits swallowed the auction. Two
  tiers keep the convention where it earns its keep and hand the within-colour
  choice back to the cards.
  - **The ladder loses nothing anyone bids.** Every multiple of 6 at or below 36
    is already a multiple of 2 or 3, so dropping base 6 removes only 42, 54, 66
    and 72: the rungs are IDENTICAL through 40, the ceiling falls 72 → 60, and
    the count goes 36 → 28 (32 once Grand's base 4 is added). 7 is still the
    only hole below ten. `test_skat.py`
    asserts the ends off `min`/`max(SKAT_BASE)` rather than as literals, which
    is exactly what let the ceiling move without a hand-edit.
  - **Null's flat 20 got relatively dearer to duck under**: still 13 rungs below
    it, but 13-of-32 rather than 13-of-36, against a ceiling that fell by a
    sixth. "A cheap contract is a licence to duck" is already the intended
    shape; this nudges it. Retuning is engine-side alone (the Hard tier reads
    `payoff_terms`), so it can wait for a measurement rather than a guess.
* **GRAND (2026-08-07) — the four 10s are trump and belong to NO suit**, Skat's
  jack rule on the ten. Skat mode only: classic *ranks* denominations rather
  than pricing them, and Grand has no natural rank slot in `C<D<H<S<NT` because
  it is defined by what it costs. Base 4, between the blacks and no-trump —
  with four trumps (~0.75 of them out of play on an average deal) it is
  no-trump with a handful of wild cards, not a suit game with a long trump.
  - **The SECOND ten played wins.** They are all tens, so there is nothing to
    rank them by, and any imposed order (Skat's ♣>♠>♥>♦ or otherwise) is one
    more rule a player cannot read off the cards. So leading a ten is a way to
    LOSE a trick on purpose — which, with seven of thirteen tricks at −1, is a
    tool and not a penalty. It also makes all four tens fully interchangeable,
    which the solver's equivalence collapse depends on.
  - **`GRAND = 6`, NOT 5.** 5 is `NULL_DENOM`, the marker on games saved before
    Null stopped being a bid; reusing it would silently re-read one of those as
    a Grand contract — different trump, different follow-suit. The value is
    never arithmetic, so the gap costs nothing but the sparse `SKAT_BASE`.
  - **`esuit(card, trump)` IS THE WHOLE FEATURE, and it is expressed once.**
    Suit membership stops being `card // NRANK` while Grand is trump, which is
    the deepest shared invariant in both implementations. Everything derives
    from that one function: `beats`, `legal_moves`, `Knowledge::hand_void`
    (**five classes, not four** — a trump void is a real fact, and a `[bool; 4]`
    would have dropped it silently while the determinizer kept dealing tens into
    a hand that had proved it held none), the determinizer's partition,
    `dd.rs`'s equivalence collapse (`follow_mask`, because under Grand a suit
    LOSES its ten so its 9 and J become adjacent — reading the raw suit mask
    would refuse a collapse that is legal, and would collapse two tens against a
    suit that is not theirs), `policy.rs`, and `wire.rs`'s void inference.
  - **It is the identity under every other contract, and both suites assert that
    over the WHOLE card space** rather than sampling it (`test_every_other_
    contract_plays_exactly_as_it_did_before_grand_existed`,
    `no_other_contract_moved_when_grand_arrived`). `esuit` sits on the solver's
    hottest path; a regression there is a different game, not a worse bot.
  - **The fixtures cover it or it is not covered.** `gen_fixtures` samples trump
    over `DENOMS` (so ~1 play fixture in 6 is Grand and the Python port replays
    it), `solver_matches_brute_force` sweeps `DENOMS` and asserts it reached
    Grand, and `gen_view_fixtures.py` appends a FORCED Grand game — the bot
    picks a denomination on hand strength and can go whole runs without choosing
    Grand, which would leave the wire reader's Grand path covered by nothing
    while the file still looked comprehensive.
* **Phases:** `auction` (numeric) → `talon` → `declare` → `kontra` → [`re`] →
  `play`. `talon` splits into `look` / `hand` / `swap` because **declining to
  look is what Hand means** — the declarer who plays Hand never sees `shown`
  either, in the engine *and* in `view_for`, or Hand would be a free multiplier.
* **Overtricks pay 1 each, flat.** `stake + 1 × (pts − target)` on a make — the
  same `OVER_BONUS` classic uses, and deliberately NOT run through `mult` or the
  doubling. See the overtrick section above.
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
* **The ladder is DERIVED, and SKAT_MODE.md's hand enumeration of it was wrong
  twice** — it counted 43 rungs and listed a 7. `base × level` is the rule and 7
  is a multiple of no base, so the real ladder is **32 rungs from 2 to 60 with
  one hole at 7**. `test_skat.py` asserts against the *generator* and pins the
  hole so nobody "fixes" it back; it also reads the ends off `min`/`max(
  SKAT_BASE)` rather than as literals, which is what let the colour re-pricing
  move the ceiling without anyone hand-editing a number.
* **"Overbid loses automatically" cannot fire, and is deliberately not
  implemented.** The level is the declarer's free 1..12 choice and NT×12 is the
  top rung, so every legal bid is declarable (`test_every_legal_bid_is_
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

**Scoring** (contract only; trick points are the yardstick *and* the margin):
make → **N² + 1 per trick point past N**; set → defender scores
**(N−1) + 4 × shortfall**. **NULL OVERRIDES A SET**: a declarer who won **no +2
trick all round** scores a flat **12** (skat: **20**) instead, whatever they
declared. **Every round runs all thirteen tricks** — see the overtrick section.

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

## The bots do not cheat — and this is TESTED, not asserted (2026-08-07)

Every bot is handed the WHOLE game dict. `bot.act(g, seat)` and `_ask_the_client`
both take `g`, because the server owns the state and there is nowhere else for it
to come from — so **nothing structural stops a bot reading the opponent's hand;
only the code does.** `tests/test_bot_fairness.py` is what says it still holds.

**The method is INVARIANCE, not grep.** Re-deal every card the seat cannot see,
back into the same slots, and demand the identical answer — a bot that peeked at
any of them would have to change its mind about at least one rewrite. It catches
a peek through any number of helper layers, which `grep hands[1 - seat]` does
not. Driven over whole games in BOTH modes, so it covers the auction, the talon,
the declaration, Kontra and all thirteen tricks. Two of the eight tests guard the
guard — a planted cheat must FAIL them, or a reshuffle that quietly did nothing
would report a clean bill of health.

What a seat is entitled to: its own hand; every pile TOP; the MIDDLE pile's
bottom (dealt face up); `shown` if it earned it; the public record. Hidden: the
opponent's hand, **both** seats' OUTER pile bottoms, and the unshown talon.

* **IT FOUND A REAL ONE.** `bot.hand_strength` valued a hand as
  `playable() + every pile bottom it owned` — but only the middle bottom is face
  up, so the server bot (Easy/Normal) bid knowing **two cards the rules never
  gave it**, in both auctions and in the talon swap. Not opponent knowledge, so
  it never played a card it could not have played; it simply rated its own hand
  more accurately than the human across the table could rate theirs. Fixed by
  counting the two unknowns at `_UNKNOWN_RANK_VALUE`, the deck mean — dropping
  them outright would under-rate every hand by two cards and silently re-tune
  every threshold in `_level_for`. Measured effect on 150 rounds/mode: classic's
  settled level fell 4.13 → 3.77 and contracts made rose 75% → 79%; skat barely
  moved (4.02 → 3.99, 64% → 63%).
* **The Hard tier was already clean, by construction.** The armed request ships
  `engine.view_for(g, seat)` — the same builder that feeds a human seat, so there
  is no second projection to keep in step — and `wire.rs` reads a seat's own
  outer bottoms as `UNKNOWN` and **fails closed**: if `pool` does not partition
  into exactly `opp_hand_n + hidden_slots + n_out_hidden` it returns None and the
  decision goes back to the server bot rather than searching a lie. The wire test
  `a_seats_own_covered_outer_bottoms_are_hidden_from_it_too` pins the asymmetry
  on that side too, and checks the resampling is real rather than a constant.
* **The wire test asserts on the SERIALISED payload**, not field by field — the
  failure this repo has already paid for is something that nests a whole-game
  snapshot, which defeats per-field redaction while every field check passes.
  Scanning the blob for card numbers cannot work at all: a card id and a trick
  count are both small integers.
* **THE MIRROR IMAGE IS REAL AND IS THE COST OF A CLIENT-SERVED TIER.** In a
  vs-AI room on Hard, the armed request carries the BOT's view to the human's
  browser, because the human's browser is what runs the search. So the human
  *can* read the bot's hand out of devtools. `_handle_client_ai_ready` refuses to
  arm unless the room really is vs-AI on a client tier, which is what keeps it
  away from a human OPPONENT — but the bot's own opponent necessarily holds it.
  The repo-wide framing ("tampering only weakens the tamperer's own opponent") is
  about MOVE quality and does not cover information leakage in a hidden-info
  game. Moving Hard server-side is the only fix, and Render's free tier
  (~0.1 CPU) is why it is client-served in the first place.

## A game is a MATCH of rounds (2026-08-07)

`MATCH_TARGET` — **100 in both modes**. A round is one deal; a game is rounds
played onto a running total until one side reaches the target. Measured against
the normal-tier bot: classic **median 10 rounds** (6–16), skat **median 11**
(6–18). **Re-measure if the bases or the payoff arithmetic move** — the target
is a product decision, but the round count it buys is not a guess, and skat was
a median of 8 to the same 100 before its bases were re-priced by colour.

**THOSE MEDIANS ARE NOW STALE and have not been re-run.** The overtrick bonus
raises every made contract, so 100 buys FEWER rounds than the numbers above —
by how much is unmeasured. It is a `skatlab` run, not a guess, and it is the
same run the Null-cliff question below wants.

Still a per-mode DICT though both read 100, because the modes score on different
scales and nothing requires them to agree: a classic round pays level² (up to
144, flat 12 for Null), a skat one base × level × the announcements (up to 60,
flat 20). They land on the same match length regardless.

**WHY:** one deal can simply be bad, and the auction is the only lever either
player has against it. Over a match the deals average out and what is left is
the bidding judgement, which is the part worth playing.

* **`phase == "over"` still means the ROUND is over — `is_over()` now means the
  MATCH is.** That split is the whole feature and it is load-bearing in
  `main.py`: `_sync_status_from_game` and `_bot_should_act` both read `is_over`,
  so between rounds the room stays `playing`, keeps its sockets, and stays out
  of the finished-games list. `round_over()` is the other half.
* **`may_act(g, pid)`, not `turn_pid(g) == pid`.** Between rounds the round is
  scored and NO seat is on turn, yet either player may deal the next one — a
  question the single-seat turn model cannot express. It lives in the engine
  rather than as a special case in the move handler.
* **`next_round` carries the round it was pressed on.** Both players clicking at
  the same moment is the normal case, not an error either should see; without
  the token the second click either reads as "the round is still being played"
  or — far worse — deals a third round over the top of the second. A mismatched
  token is a silent no-op, the same idempotency discipline as the client-AI
  decision counter.
* **The opener alternates every round, and is DERIVED from the round number**
  (`opener_for_round`), never flipped from whatever the last deal used. Not
  every deal is a round: a skat hand both players pass out is thrown in and
  dealt again, and a redeal that flipped the opener knocked the alternation out
  of phase, so which seat opened round 4 depended on how many hands got passed
  out along the way. `_redeal` therefore keeps the SAME opener — it used to
  flip, on the reasoning that passing out of a bad seat should not be free, but
  the replacement deal is fresh cards so there was no bad seat left to escape.
  A match saved before `first_opener` existed recovers its phase from where the
  alternation actually is rather than restarting at seat 0.
* **What the opener alternation is FOR is the BIDDING, not the lead** — the
  DECLARER leads to trick 1 (`_start_play`), whoever opened. The opener names a
  contract into no information at all, and in classic mode may not pass.
* **A skat pass-out redeals WITHOUT counting as a round.** `_redeal` carries the
  match through untouched, `round` included — a deal nobody played is not a
  round.
* **Walking out ends the MATCH.** `abandon_result` banks the forfeit and then
  closes the match regardless of the target: there is nobody left to play the
  rest of it.
* **The final standing is written onto the RESULT ROW** (`match_scores`,
  `match_target`, `match_over`, `round`), not left only in `g["match"]`. The
  lobby history reads a stored result and never the live game.
* **A save with no `match` key is a single round and still ends at its own
  end.** `match_of()` is the only reader of `g["match"]` for exactly that
  reason — a game already in progress when this shipped must not crash and must
  not silently acquire a target it was never being played to.
* **`next_round` clears `room["_ai_search"]`.** A new deal makes any armed
  search a question about a game that no longer exists; the answer would be
  re-validated and thrown out, but the ARMING must not survive the deal.
* **The bot never deals for you.** `turn_pid` is None between rounds, so the
  scheduler finds nothing to do and the result panel stays up until a human
  presses Next round. `test_the_bot_never_deals_the_next_round_by_itself`.

## Every trick point past your contract is worth 1 (2026-08-07)

`OVER_BONUS = {"classic": 1, "skat": 1}` — a per-mode dict like `MATCH_TARGET`,
and like that one it currently reads the same in both while the modes score on
different scales. A made contract pays **N² + 1 × (pts − N)** in classic and
**stake + 1 × (pts − target)** in skat. Set is untouched; Null is untouched.

* **It ships through `payoff_terms` as an `over` term**, so `_finish` and the
  Hard tier's solver get it from one place — **change it and the bot follows with
  no bot code at all.** `dd::Contract.over` was already there as a *penalty* from
  the auction lab's burst experiments; it is now SIGNED (a bonus, negative for a
  penalty) so the sign convention matches the server's, and `forced_floor` passes
  −1. On the wire it is OPTIONAL, defaulting to flat, because a browser can hold
  a cached wasm older than the server.
* **FLAT, not scaled by skat's announcements or Kontra** — the `SKAT_NULL_VALUE`
  argument. Hand/Sharp/Open are promises about the CONTRACT, and running a
  per-point bonus through a ×4 would make one overtrick worth more than the rungs
  the ladder is built from.
* **It narrows the Null cliff, which was measured and deliberate.** "A cheap
  contract is a licence to duck" was priced against FLAT payouts: a made classic
  level-1 now runs 1 → up to 12 against Null's 12, and a skat stake of 6 runs
  6 → 15 against 20. Narrowed, not removed — and it is the number most worth
  re-running in `skatlab`, since the measurement behind it no longer describes
  the game.
* **`contract_score` now DELEGATES to `payoff`.** It held its own copy of the
  classic make/set rule, was reachable from the tests only, and would have gone
  on paying flat — a test agreeing with itself.

### The early end is SHELVED, not deleted

`_score_is_settled` stopped a round the moment the score could no longer change.
Its "cannot fail → stop" branch rested *entirely* on a made contract paying a
flat amount; with overtricks every remaining trick moves the score, so **every
round now runs all thirteen tricks.**

The predicate is kept whole and **gated on the TERMS, not on the mode** — put a
0 back in `OVER_BONUS` for a mode and the early end returns for that mode alone,
with no other edit. `test_no_round_ends_before_the_thirteenth_trick` drives both
halves (bonus on: never settles; bonus off via `monkeypatch.setitem`: the old
rule exactly, last-trick guard included), so the branch stays live and tested
rather than rotting into something that no longer compiles against the state
around it. `test_a_round_that_would_have_stopped_early_now_plays_on_for_the_bonus`
finds the seeds that used to stop and asserts they now run to thirteen — the same
deal both ways, so the difference is the rule and not the cards.

What the shelved rule said, kept because it was measured rather than assumed:
cannot-fail stopped, cannot-**make** played on (the defender is paid
`(N−1) + 4 × shortfall`, so every remaining trick still moves the shortfall);
Null got no early exit of its own; and it never stopped with ONE trick left,
because that beat is where the shortfall and the Null consolation are both still
live.

**`result.ended_early` is now always false, and the key stays.** The result panel
still reads it (`scored()` prints "at least N", because a stopped round's trick
TOTAL was not final even though its score was) — a stored result from before the
bonus can still carry it, and the shelf could put it back.

**`pts` sums to POOL only over a COMPLETED round** — still the correct way to
state it, and now unconditionally true. The four tests and one fixture generator
that learned it the hard way assert it flat rather than behind an `if`: a round
that ended early would be a real regression and must not read as the other half
of a legitimate pair.

**The Rust parity harness names a `MAX_LEVEL` contract on purpose, and it stays
that way.** The reference always plays all thirteen tricks, so `_game_from` has
to describe a contract that can never settle early — at its old level of 1 the
early end fired most of the way through most deals and every fixture's final
points diverged. MAX_LEVEL works because one player's ceiling is sweeping the six
+2 tricks; `test_rust_parity` asserts that relationship rather than assuming it.
The overtrick bonus makes this redundant *today* (nothing settles early any more)
— keep it, because it is the shelf's insurance: flipping `OVER_BONUS` back to 0
would otherwise silently truncate every fixture replay again.

## `shown` is the OUT-OF-PLAY SET, not a record of what was shown

Two questions, two fields, and collapsing them breaks the Hard tier silently.

* **`shown`** — the out-of-play cards this seat can place. A swap REWRITES it,
  so it keeps matching `out`: the taken card leaves, the discard takes its slot.
  This is what goes on the wire, what the in-round talon panel shows (a holding
  to count from), and what the client-side searcher reads.
* **`shown_at_deal`** — the three cards the declarer was actually shown, fixed
  at the deal and never rewritten. Only the round-end reveal reads it.
* **`swap_take` / `swap_give`** — which cards moved, **redacted until the round
  is over**: the defender learns THAT a swap happened and nothing more, which is
  the entire point of the discard going face-down.

**THE WIRE'S `shown` IS NOT OURS TO REDEFINE.**
`rust-cores/dissonance-core/src/wire.rs` treats every card in `view["shown"]` as
out of play and does exact card-count arithmetic on it — the unseen pool must
partition into the opponent's hand, the covered pile bottoms and the unplaced
out-cards, or `view_from_json` returns None. That contract is frozen by the
COMMITTED wasm, which cannot be rebuilt without `wasm-pack`, so changing what
the field means requires a rebuild in the same commit or it is simply a break.

Making `shown` the historical record put the taken card — by then in the
declarer's HAND — into the searcher's out-of-play set. The arithmetic stopped
balancing on every decision after a swap, all four workers returned "not a
searchable position", and the main thread's `good` filter dropped them without a
word. **The room played on at full speed, still labelled Hard, on the server
bot.** No exception, no console error, nothing red — and because it only bites
after a swap, it passed locally and went red in CI.

`test_every_card_the_wire_calls_shown_is_really_out_of_play` is the guard: it
walks a whole played round, both seats, and asserts `view["shown"] ⊆ out`. It
fails on 25 of 25 seeds against the broken version, because the bot swaps in
nearly every game — which is also why whether the HARNESS or the BOT won the
auction decided whether the browser gate passed.

The reveal's other half: it said "was shown" even for a skat **Hand** game,
where declining to look IS the announcement and the declarer never saw the talon
at all. The frontend gates that line on `sawTalon` (`!isSkat || game.looked`).

## Do not relitigate

* **EVERY BUTTON ON THIS BOARD IS THE GREEN, and `.btn` alone is not a button**
  (2026-08-07). `.btn` in the shared kit is GEOMETRY ONLY — padding, radius,
  font, `border:none`, and deliberately no background or colour, because the
  paint comes from a variant. This file carried **nine** bare `className="btn"`
  buttons and was the only file in the repo that did, so Bid / Start / Swap /
  Look / Next round / Back to lobby rendered as the browser's DEFAULT button
  face — measured `rgba(239,239,239,.3)` on `rgba(16,16,16,.3)`, a white chip
  with grey text on a dark green board. They are `.dis-gobtn` now (solid
  accent), and `.dis-annbtn` — a `#6fa8d8` blue borrowed from nothing, on a
  board with no other blue — is an accent OUTLINE, one step down from the solid.
  - **Gold was the wrong fix even though it is the kit's primary.** The lobby,
    the board, the selected bid and the turn badge are all `--accent`; gold is
    Spender's colour arriving through the same fallback that already dressed
    this game's lobby in the wrong accent once.
  - **`--accent-hi` and `--ink` are tokens now**, not hex literals repeated in
    eight places, so the go button, the bid toggles and the announcement outline
    agree by construction.
  - **Kontra stays red** (`#b8434f`, white text) and that is deliberate: it is
    the defender's one moment of leverage and reads as a threat, the same role
    the kit gives `btn-danger`. It is not an oversight to "fix".
  - Guarded by `shared/tests/test_btn_has_a_variant.py`, repo-wide, because this
    failed SILENTLY — nothing throws, the button works, and `smoke`, `screens`
    and the whole Python suite all ask whether a thing renders, never what
    colour it came out. Verified against the old file: it names all nine.
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
* **The SERVER bot does not chase the Null consolation; the Hard tier does.**
  A declarer whose contract has gone wrong ought to switch to ducking every +2
  trick — but "has gone wrong" is a lookahead judgement, and Easy/Normal are one
  trick deep (reading it off the current total instead would throw away
  contracts they were still winning). Hard got it by searching the payoff
  instead of the points; that is the fix, and it is not portable to a policy
  with no search.
* **NULL AT A FLAT 12 (skat 20) DOMINATES A LOW CONTRACT, and this is measured,
  not speculative.** Classic levels 1–3 pay 1/4/9, all below 12; in skat, 13 of
  the 28 ladder rungs pay under 20 at ×1. So a declarer who bought cheaply has
  no reason to play for their contract at all — and the floor cluster puts ~42%
  of openings at level 1. The contract-aware Hard tier exploits it on sight
  (6–7 Nulls per 40 rounds against the points searcher's 0). **Flat is a
  DECISION, taken 2026-08-07 with this measurement in hand** — a cheap contract
  is now a licence to duck, and that is the intended shape of the escape hatch.
  Revisiting it costs no bot work: the search reads `payoff_terms`, so scaling
  Null or capping it below what it replaces is an engine-side change alone.
  - **THE OVERTRICK BONUS (same day) NARROWED THIS, and the measurement above
    was taken on FLAT payouts.** A made contract is now worth its stake plus
    every point past the target, and the declarer's ceiling is 12: classic
    level 1 runs 1 → up to 12 against Null's 12, and a skat stake of 6 runs
    6 → 15 against 20. The cliff is smaller and the Null rate should have
    fallen with it. **Nobody has re-run it.** The rate is a `skatlab` sweep and
    the same one the match-length medians want; until it exists, treat "6–7
    Nulls per 40 rounds" as describing a game that no longer ships.
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

## Tests (353)

`test_engine.py` rules · `test_rust_parity.py` the drift gate ·
`test_bot_fairness.py` (8) the bots see only their own seat, by INVARIANCE over
re-dealt hidden cards ·
`test_ws_auth.py` seat-identity binding + whole-payload redaction ·
`test_integration.py` create → auction → 13 tricks → scored result → the NEXT
round → the match, vs human and vs bot, in **both modes** (its vs-bot pair covers
the case most likely to strand: only the human can deal the next round, and the
bot has to pick its own turn back up once they do) · `test_skat.py` (74) the skat
phase machine: the derived ladder, the redeal, talon/Hand secrecy, declaration
validity, the announcement table, Kontra/Re, the Open reveal, a `state_json`
round-trip, and **Grand** (the tens as a fifth suit, second-ten-wins, the
NULL_DENOM collision, a whole round through the real phase machine, and the
whole-card-space assertion that no other contract moved), and the **overtrick
bonus** (the make boundary, the flat-through-the-multipliers rule, and that no
trick is ever skipped) · `test_client_ai.py` (12) the Hard tier's protocol: the armed
request, the re-validation, the stale drop, the watchdog, and the picker/server
tier agreement.

Rust side, `cargo test --features bridge` runs `wire::fixture_replay` (the
wire-reader gate above) plus `tests/engine.rs`, the 16-test mirror of
`test_engine.py`. Three of those are Grand's: the fifth-suit rules, the
whole-card-space no-regression sweep, and a trump void surviving the
determinizer. `solver_matches_brute_force` also sweeps `DENOMS` now and asserts
it reached Grand — the equivalence collapse is the one place a Grand bug would
show up only as a slightly wrong VALUE, which nothing else would notice.

**RUN IT. CI DOES NOT BUILD RUST, so a broken Rust test target is invisible
here in a way a Python one never is** — nothing goes red, the suite simply
stops existing. `tests/engine.rs` had not COMPILED since the deck-width
campaign (`2a8957b`) took masks from 32 to 64 bits: it kept a `let mut covered
= 0u32`, which stopped type-checking against `Mask`, and the whole target — all
13 tests — silently dropped out of every run for the entire v2 release. Behind
it sat a second stale assertion (`v.len() == 28`, "26 dealt + 2 out of play")
that had been wrong since the deck went to 32 and had never once been executed.

Both are now DERIVED from `NCARD` / `NDEALT` / `NOUT` rather than written as
literals, so they hold under the `rank7` / `rank9` / `rank10` builds too — which
is not a hypothetical, since a literal 28 is wrong under three of the four and
`rank7` is exactly the 28-card game the pre-sweep numbers were measured on.

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
* **It searches the CONTRACT PAYOFF, not the trick points (2026-08-07).** Points
  are the game's yardstick, not its score: a points solver cannot see what a
  declarer past their target actually gains (1 a point since the overtrick
  bonus, and nothing at all before it — the payoff says which, the solver does
  not assume), that every point of a defender's shortfall is worth four, or —
  since Null became a consolation —
  that a declarer who has taken no +2 trick is one ducked trick from scoring
  instead of being set. That last one is a CLIFF in the payoff at a single bit
  of state, which is why `State` carries `escored` (not derivable from `pts`: a
  total of −1 is one +2 trick and three −1s just as easily as one −1 alone).
  Ducking for Null and defending against it both fall straight out of the
  minimax; neither is a special case.
  - **The terms are SHIPPED, not reimplemented.** `_ai_search` carries
    `engine.payoff_terms` — the same function `_finish` scores with — so the
    only thing written twice is the arithmetic turning terms into a number, and
    `wire::payoff_parity` holds that to a fixture of the engine's own answers.
    A consequence worth knowing: **change the Null value or the curves and the
    bot follows with no code change at all.**
  - **Measured** (`bin/cmatch`, paired, mirror reads exactly 0.000): **+0.55**
    payoff/round at level 4 and **+1.25** at level 1, positive in BOTH roles,
    and it finds Nulls the points search never does (6–7 vs 0 in 40 rounds).
    n=80, so treat the magnitudes as indicative. **The first run of this read
    +4.05 and was wrong** — the harness seeded bots by identity rather than by
    seat, so swapping tiers swapped their RNG streams too. The mirror caught it;
    that is what the mirror is for.
  - **The browser gate counts ARMED decisions, not an absolute number of
    answers.** The server arms a decision only where the bot has a CHOICE —
    under mandatory follow-suit most plays are forced and it applies those
    itself — so how many arrive is a property of the DEAL. An absolute threshold
    failed on deals with more forced moves while the tier worked perfectly, and
    read exactly like the tier being broken. `screens.mjs` reads the count off
    the WebSocket frames and asserts every armed decision came back.
  - Costs **1.79x** a points solve (`csearch` has no MTD(f) and must play to
    trick 13), so ~125ms per world at trick 1 against ~70ms.
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

## The Hard AUCTION (2026-08-07)

`bid.rs`, served over the same protocol as the card play. The old bot scored a
hand by summing a rank curve and mapping it onto a level through hand-placed
thresholds — guesses, driving four decisions at once. This samples deals and
SOLVES each one in every denomination (most the declarer can guarantee, plus
"could they duck to Null in this trump"), then prices every option the server
says is legal. No thresholds.

* **The server owns the options AND their moves.** `engine.auction_payoff_options`
  returns each legal action priced by `payoff_terms`' own arithmetic, each
  carrying the move it stands for, so the browser ranks an index and sends back
  a move it was handed. Four move shapes across two auction modes, and no rule
  about any of them crosses the wire. `_validated_bot_move` re-runs whatever
  comes back through the ENGINE on a throwaway copy — a client-side allowlist
  would have been the second copy of the rules all over again.
* **The talon and the swap stay server-side ON PURPOSE.** They are decisions
  about INFORMATION: what declining to look is worth depends on a game that has
  not been named yet, so there is no contract for the solver to price them
  against.
* **PERFORMANCE — a world costs a different amount here**, and getting that
  wrong is what the first wired version did. A card decision solves the deal
  once (74ms native); an auction decision solves it in every denomination
  (417ms). Inheriting the card tier's 8-world cap put **7.5–9.2s** on a bid,
  past the point where the watchdog took decisions back (6 of 8 answered). It
  now runs **~1.0s for the first decision of a hand and ~0 for every one after
  it, 14 of 14 answered** — but note that the "~0 for the rest" only became true
  with the `covered` mask below; before it, the cache hit inside a round and
  missed across them, so a whole auction paid its opening price on every turn:
  - **A separate `CLIENT_AI_AUCTION_WORLDS` (3).** The estimate is a whole-hand
    question and much less noisy than a mid-play one; the design lab's own
    sweeps ran at k=4.
  - **The solve is CACHED on what the seat HOLDS** (`hand_key`). An auction asks
    the same question of the same cards every round — five or six in classic,
    more up a skat ladder — and only the option list changes, which is
    arithmetic. The talon swap changes the hand and so invalidates it by
    construction. This is the big one.
  - **…and the denominations asked about are a QUERY against that entry, never
    part of its identity.** The option list does not merely change, it SHRINKS:
    a classic seat cannot re-bid a denomination it has named, so the set its
    options span runs 5, 4, 3, 2 down its own four turns, and skat's runs
    5, 4, 3, 2, 1 as the rungs price denominations out. With that set in the
    key every one of those steps MISSED and re-solved denominations already in
    hand — the cache only ever hit inside a round. `Solved` now carries the
    sampled deals plus a `covered` mask: a subset is a hit, a superset solves
    only the difference **on the same deals** (a fresh sample would make the
    choice between denominations noise). Measured over a whole classic auction,
    **18,435k nodes → 7,220k, −61%**, and every turn after the first is free.
  - **MTD(f) seeds each denomination from the last** (−6%, exact). The same hand
    is worth a similar amount in hearts and spades, so the first solve pays for
    the other four. `solve_root` had done this between sibling moves since the
    campaign.
  - **Seeding ACROSS WORLDS is worth nothing — do not relitigate.** The obvious
    next step (carry each denomination's value into the same denomination of the
    next world, since a different lie of the unseen cards should move the value
    less than a different trump does) measures 8,634k → 8,685k nodes: no change.
    It first read −14% on a bench that solved the SAME deal three times, where
    the carried seed was already exactly right; the fix is that the worlds must
    be really determinized. `bin/abench`.
  - **A BIGGER TT IS SLOWER — do not relitigate.** 2^19 and 2^20 each cut nodes
    (2.55M → 2.43M → 2.38M) and each ran SLOWER in wall clock (423 → 472 → 491
    ms/world): cache locality dominates at this size. 2^18 stays.
  - **THE FAN-OUT IS ALREADY OPTIMAL — splitting it finer cannot help.** The
    pool gives each worker its own world, so four workers buy four worlds for
    one world's wall clock with no idle time. Splitting by denomination instead
    (each worker owning some trumps across shared worlds) was measured and is
    WORSE at equal quality: total work is unchanged and worlds are near-equal
    cost, so the balance being optimised was never the problem. What is left is
    total work — which is what the cache above attacks.
  - **MEASURE THIS IN NODES, NOT MILLISECONDS.** `Dd::nodes` is exact and
    proportional to time; wall clock on a dev box swings ~2.5x on byte-identical
    work, which is more than any of the effects above.
* **The approximation, stated:** `solve` gives what a declarer can guarantee
  with both sides playing for POINTS, which is not either side playing for the
  contract. Pricing every candidate exactly needs a `solve_contract` per
  (denomination, level) per world against ~50 options; the points solve is the
  proxy and the payoff arithmetic is exact on top. `auction.rs` has made the
  same trade since the design campaign.
* **Passing is valued at zero**, so the bot passes rather than buy a contract
  that prices negative. It does NOT price what passing hands the opponent —
  that needs their eval too, at double the cost. The classic opener must bid, so
  there it takes the best option regardless.

## Not built yet

* **Pricing the pass.** See above: the bot knows what a contract is worth to it,
  not what letting the opponent have it costs.
* **Announcements beyond Sharp.** `auction_payoff_options` enumerates Sharp but
  never Open, and the multiplier is priced without modelling the extra risk.
* Match play across rounds (currently one round per room), and a `/review`.
