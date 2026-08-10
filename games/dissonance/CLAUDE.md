# Dissonance — Claude context

Sixth game. Two-player trick-taking where **taking tricks is not simply good**:
even-numbered tricks score **+2** to whoever wins them, odd-numbered ones
**−1**. Six positive against seven negative, so both players' totals always sum
to exactly **+5** — sweeping all thirteen tricks scores 5, while taking exactly
the six even ones scores 12. The game is about *which* tricks you win.
(FOUR modes: classic, skat — a second auction, and since 2026-08-09 a second
CURRENCY, since skat scores the CARDS captured rather than the trick parity —
**minor**, where even tricks pay **+1** and the pool is **−1**, and since
2026-08-10 **dummy**, a three-seat game between two players off a 40-card deck.
Each has its own section below.)

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

## Minor mode — the third mode, and the first to touch the trick VALUES (2026-08-09; skat's card scoring, below, was the second and went further)

`mode: "minor"` — even tricks pay **+1** instead of +2 (odd tricks stay −1),
over the CLASSIC auction shape. Same room-flag machinery as skat: one table,
one route, chosen in the create modal, badged on lobby cards. Unlike skat it
changes no phase — a minor round is classic's phase machine (swap, Double and
all) in a different currency.

**Everything follows from the one number, and the map of what it drags along
is `EVEN_TRICK_VALUE`'s docstring.** The pool goes NEGATIVE (6×1 − 7 = −1):
winning every trick scores −1, par is −0.5, and a perfect declarer tops out at
6 — so the ladder compresses to **1..6** (`MINOR_MAX_LEVEL`, asserted derived
from the parity, never typed beside it).

**The re-anchored prices, and why (all measured in
`tools/minor_calibration.py`, bot self-play, 400-600 rounds/config):**
* **make N² + 1/overtrick, set base N** — classic's shapes, unchanged.
* **set rate 2, not classic's 5 (`MINOR_SHORT_PENALTY`)** — payoffs run about
  a quarter of classic's (ceiling 36 vs 144) while shortfalls keep the same
  magnitude (median ~2 in both sweeps), so the classic rate made the set the
  biggest number on the table: two-thirds of rounds ended in a set paying ~11
  against makes of 1–6, i.e. "whoever had to open loses". 2 tracks the
  ceiling ratio. The Double and its shortfall ramp apply unchanged.
* **Null 6 (`MINOR_NULL_MAKE`)** — the same relationship classic's 12 has:
  exactly a made level-1's CEILING under the overtrick bonus (1 + 5). The
  cliff this buys is proportionally bigger than classic's (minor makes rarely
  reach their ceiling) — a declarer who bought cheap has an even stronger
  licence to duck. Deliberate, same as classic's documented stance; the rate
  it produces under searching tiers is unmeasured (`skatlab`-class question).
* **match to 25 (`MATCH_TARGET`)** — buys ~7 self-play rounds against
  classic's ~6 under the identical harness. NOT 100 rescaled by feel.

**The mode is structurally DECLARER-HOSTILE, and that is the design, priced:**
even level 1 asks the declarer to beat par by 1.5 points and makes only ~45%
under greedy play (searching tiers do better); level 2 ≈ classic level 5 in
margin terms, because each even trick swung moves the differential by 2 rather
than classic's 4. The server bot's map (`bot._MINOR_LEVEL_NEEDS`) is therefore
COMPRESSED — level 2 fires around p96 of hand strength, 4+ effectively never —
and its settled distribution is ~87% level 1. Rungs 3–6 are sacrifice space,
the role classic's unused 7–12 play. An open question a `skatlab`-class sweep
should answer: with sub-50% make rates, does Hard-vs-Hard converge on "Double
every contract"? (Break-even is around a 45-50% set rate.)

**How the value reaches every consumer — one runtime number, three surfaces:**
* **Python**: `trick_value(t, even)` + `trick_value_in(g, t)`;
  `payoff_terms`/`_terms_for` take the real mode; `pool_for`,
  `max_level_for`. `view_for` ships **`even_val`**; `_deal_snapshot` carries
  **`even`** (the DD review must replay the round's own parity);
  `persist._pack_deal` passes it through generically.
* **Rust**: `State.even` (runtime, default 2). `State::play` scores with it,
  `State::pool()` replaces POOL on every serving-path diff→points conversion
  (`bid.rs`), `dd::key_of` mixes it into the TT key (two parities of one card
  layout are different positions), and — the subtle one — **the MTD(f)
  bounds/parity tables are per-`Dd` state (`ensure_even`), because the
  ladder's stride-2 parity trick is DIFFERENT under minor** (every trick
  swings odd) and classic tables step the ladder right past reachable values.
  `wire.rs` reads `even_val` (view) / `even` (deal), optional, default 2.
  Gates: `solver_matches_brute_force` sweeps the parity like it sweeps Grand;
  fixtures — `play.jsonl` (1 in 4 minor), `views.jsonl` (a minor game),
  `payoff.jsonl` (minor contracts, doubled and not), `auction.jsonl` (minor
  nodes; its `rules.mode` is **"classic"** — the SHAPE — with `max_level` 6,
  so the legality mirror needed no third arm).
* **Expert/Hard auction**: free ride. `auction_payoff_options` and
  `auction_search_payload` are already data; the classic swap-policy weights
  now ride on minor auctions too (`!= "skat"` in main.py — fitted on +2,
  an approximation; minor's own swaplab run is queued with skat's).

**THE STALE-WASM GATE IS A THREE-PART HANDSHAKE, and it exists because an old
artifact reading a minor view would silently search the WRONG GAME** (it
ignores `even_val`, scores +2, returns legal-but-misvalued moves — the exact
shape of the `shown` outage, with nothing red anywhere). Fail-closed:
1. the wasm exports **`odd_wire()` = 2**; the worker probes for the export
   and refuses minor payloads on an artifact without it (per-decision error →
   server bot, the ordinary degradation);
2. the page reports the pool's weakest `wire` in **`client_ai_ready`**;
3. the server refuses to arm a MINOR room for `wire < 2`
   (`_handle_client_ai_ready`) — so an old cached bundle that never sends the
   field plays the server bot, honestly labelled by nothing happening.
Classic and skat rooms accept any vintage, as before. `test_minor.py` pins
the server half; the worker half is the export-table probe.

**Frontend**: trick labels print the VALUE off the wire (`evenVal(game)` /
`view.trick_value`), never a hardcoded "+2" — three sites carried the literal.
`shortRate`/`nullMake` are mode-picked off `/catalog` (which now serves
`even_value`, `pools`, `max_levels`, `minor_null_make`, `minor_short_penalty`,
`match_targets`). The "Doubled · set pays" row had said "+ 4 each" since
before the 4→5 move and the ramp — it now renders rate+ramp from the catalog.
`screens.mjs` drives the create-modal segment to a dealt minor room inside
the `dissonanceSkat` block (same lane, no new roster entry): the marker is
the 1..6 ladder or the "+1 trick" Null price, per who opened.

## Skat scores the CARDS, not the trick number (2026-08-09)

Skat mode's rounds are scored in a different currency from classic/minor: a
completed trick pays its winner the SUM OF ITS TWO CARDS — **9/10/J/Q are +2
each, 7/8/K/A are −1 each** (`CARD_VALUES`) — so a trick is worth **−2, +1 or
+4**, and the trick-number parity means nothing in this mode. 16 cards at +2
against 16 at −1 put the deck at **+16**; six cards sit out, so a round's pool
is `played_pool(g)` = 16 − the out-cards' worth — **deal-dependent (4..22,
measured mean ~14.5)**, never a constant. The design tension the values buy:
the ranks that WIN tricks (K, A) are −1 liabilities — the second player ducks
a 7 under your ace and hands you a −2 trick — while the +2 cards sit in the
middle where they rarely win a trick on their own. The auction, the ladder,
the announcements, Null and all the payoff arithmetic are unchanged; only what
"trick points" MEANS moved.

**How the flag reaches every consumer — the `even_val` pattern, one wire rung
further:**
* **Python**: `card_points` / `uses_card_points` / `played_pool`;
  `apply_play` dispatches on the mode; **`etricks` generalises for free** — a
  "scoring trick" is one with positive value in either currency, which is
  exactly what the Null consolation means (a declarer may freely win −2
  tricks). `view_for` ships **`card_pts`** (+ `card_values` for the board's
  corner chips); `_deal_snapshot` carries **`cards`** — explicit and
  DEFAULT-FALSE on the wire, so a skat round banked before the change reviews
  under the parity it was played at, for free. `pool_for("skat")` returns
  **None** on purpose — a caller assuming a constant must fail loudly.
* **Rust**: `State.cards` (runtime, like `even`). `State::play` sums the two
  cards; `State::pool()` computes pts-banked + in-play worth (correct from any
  position); `completed_trick_value` is the one place both currencies meet and
  is what `nsearch`/`tsearch` read for "scoring trick". **Three solver
  invariants had to move, all in `dd.rs`, all gated by
  `solver_matches_brute_force`'s new card arm:** (1) the MTD(f) ladder's
  stride-2 parity trick DOES NOT EXIST here (−2/+1/+4 mix both parities → step
  by 1); (2) the static bounds are ±4 a trick (`build_bounds_cards`, loose but
  sound); (3) the equivalence collapse may only merge rank-adjacent cards of
  EQUAL WORTH — the 8/9 and Q/K boundaries change every trick they land in,
  and an unguarded merge is a silently wrong VALUE, not a crash. `dd::key_of`
  mixes the flag (bit 42) and `bid::hand_key` mixes it too — same argument as
  the contract-table bug, one cache further out. `tests/engine.rs` also gates
  the per-trick recount and `null_no_even_makeable` against naive recursions
  under cards.
* **The wire is rung 3.** `odd_wire()` = 3; the worker now reads the export's
  VALUE (after init — a wasm-bindgen export throws before the module loads)
  and refuses any payload whose `card_pts`/`cards` it cannot honour; the
  server refuses to arm a SKAT room for `wire < 3`
  (`_handle_client_ai_ready`), exactly minor's three-part handshake at the
  next rung. Classic rooms still accept any vintage. **The artifact was
  rebuilt and committed with this change** (glue + wasm from one `wasm-pack`
  run, export table unchanged); a stale cached wasm degrades skat Hard/Expert
  rooms to the server bot honestly, per decision.
* **Fixtures**: `play.jsonl` — 1 in 4 fixtures card-scored (`"cards":true`),
  with coverage tests on the Python side so a regenerate that dropped them
  fails; `views.jsonl` / `payoff.jsonl` (rows −12..24 for skat — card totals
  range far past the parity pool) / `auction.jsonl` all regenerated.
* **Frontend**: the board gets `.dis-cardpts` and every card renders a
  corner worth-chip that CSS shows only there (colour + glyph, never colour
  alone); the trick line shows the held trick's real value and, mid-trick,
  the led card's "so far"; Null copy reads `nullCond(game)` ("no positive
  trick"); the skat result maths line now prints `short_rate` off the row —
  it had a literal 4 that survived the 4→5 move unnoticed.

**The bots were re-anchored, measured in `tools/skat_calibration.py`** (bot
self-play, 400 rounds, same harness as `minor_calibration`): the play policy's
card branch scores the exact one-trick delta when following (bank the sum /
shed the sum) and leads low keeping +2s back — mirrored in `policy.rs` and
`bot.policy_score` as ever. Bidding runs a card-currency rank curve
(`_SKAT_RANK_VALUE`; best-denomination strength p50 ~14.8, p90 ~16.4) into its
own level map (`_SKAT_LEVEL_NEEDS`), calibrated to: settled levels 2–6
(30/31/22/12/4%), **made 85%** (classic's same-harness figure: 82%), median
overtricks 6, mean winning payoff ~20 → implied match length ~5.0 rounds
against classic's 6.2 on the identical harness. `_KONTRA_TARGET`/`_KONTRA_
STRENGTH` were re-anchored to the new scale but remain GUESSES, as before.
**The old skat match-length medians ("median 11 to 100") describe the parity
game and are stale**; the skatlab-class sweeps queued against skat (talon
policy, announcement rates, Kontra) now also predate the currency and must be
run on it. `skatlab` itself deals `cards = true` and converts through
`State::pool()` since this change, but `skat.rs`'s lab `Decl::payoff` still
pays a flat stake (no overtrick term) — the lab lags the engine there, as it
already did.

## DUMMY mode — a third hand, played by the declarer (2026-08-10)

The fourth mode, and the answer to card scoring measuring as "random, no
control". The diagnosis, which the shelved must-head experiment sharpened: in
a two-hand trick the player NOT taking the trick chooses its payload — you win
with an ace, they slide a 7 under it, and the trick pays −2. Commanding a
SECOND HAND is the direct fix, because it makes you the author of two of a
trick's three cards.

**The shape.** THREE seats of THIRTEEN (7 in hand + three 2-card piles, the
same holding every other mode deals), ONE card out, THIRTEEN tricks of three
cards, card scoring, CLASSIC's auction. Seats 0 and 1 are the players; **seat 2
is the dummy**.
* **Its hand is face up from the deal, to both players.** Shared information
  advantages neither bidder and turns the auction into a judgement about "my
  hand plus that one" against "theirs plus that one".
* **Its outer pile bottoms are hidden from everyone, the declarer included** —
  a fully open dummy makes the endgame a double-dummy problem for both seats.
  The dummy is OPEN, not SOLVED.
* **WHOEVER LEADS THE TRICK PLAYS IT** (`DUMMY_COMMAND = "leader"`, since
  2026-08-10). The first rule gave it to the declarer for the whole round and
  that OVERSHOT, measured: two of three hands plus the lead banked them **69%
  of the pool** before they decided anything. Command now follows the lead, so
  the third hand is a prize fought over rather than a gift — and it carries
  this game's own tension, since winning a trick can cost points and still be
  worth it for the command it buys. Measured: the declarer's share falls
  **0.69 → 0.57** and contracts made fall 73% → 61%. The whole rule lives in
  `side_of`, which `playing_seat`, the trick winner and the next leader all
  derive from.
* **It plays SECOND, always, and never leads** — a trick it takes passes the
  lead to the declarer. Three reasons in order: its card is information in the
  middle of the trick both players react to; the third seat is therefore
  always the real player who did not lead, so the duck-or-take decision stays
  a human one every trick; and it gives the declarer a new move — lead low,
  drop the dummy's +2 on it, and dare the defender to take a fat trick.
* **NO FOLLOW-SUIT** (2026-08-10), the only mode without it, and MEASURED
  against the classic prior rather than in spite of it. The FOLLOWERS were the
  seats with nothing to decide — 2.27 legal cards against a leader's 4.11 —
  and free discard levels that to 4.11 / 4.11 / 4.10, with forced plies
  falling **33% → 13%** and hand-predicts-points doubling **+0.11 → +0.21**
  (classic's own choices-per-decision is 4.07, so this lands exactly there).
  The collapse the classic prior warns of does NOT happen here: the leader
  keeps the lead on 55% of tricks under follow-suit and 50% without it, so
  unwanted tricks do not simply fall to whoever led — because under CARD
  scoring a trick's worth is chosen by the other two seats rather than fixed
  by its number, which is exactly the premise the prior rests on and does not
  hold in this mode. Ducking out does not become free either (Null 3% → 1%).
  Ruffs rise 0.37 → 0.57 a trick, so the denomination you name matters more.
* **No talon.** Two out-cards cannot support showing three, and the declarer's
  prize is the dummy. That also removes skat's Hand/Sharp/Open, which are all
  announcements ABOUT the talon.

**THE WIDE DECK — 40 cards, and the eight new ones are ids 32..39 (2026-08-10).**
Three seats of thirteen is 39 cards and the deck holds 32, so dummy deals the
base 32 plus a **5 and a 6 in each suit**. It went to thirteen because ten was
the mode's biggest remaining problem: at 4 in hand + 6 in piles a seat was 60%
ON RAILS with 2.89 legal cards at a decision and a third of all plies forced
outright, against classic's 46% and 4.07 (`tools/agency_probe.py`). It now
reads **5.59 choices and 9% forced, above classic**, and all three positions
read the same (5.60 / 5.61 / 5.57) — the third seat is not carrying the mean.

* **The layout is the id space, not `suit * 10 + rank`, and that is the whole
  decision.** Renumbering is the obvious way to widen a deck and it would have
  voided every saved classic/skat/minor game, every committed Rust parity
  fixture and the committed wasm artifact, since a card id means a card. Bolting
  the new ranks onto the END keeps every existing id and — the bigger win —
  keeps `suit(c)` and `rank(c)` TOTAL functions of the id. A per-mode
  `suit * nrank + rank` would make a card id mean different cards in different
  modes, and all ~30 call sites across `engine.py`, `bot.py` and the JSX would
  need a mode threaded through them to stay correct.
* **The cost, and it is real: `rank()` no longer returns the id's low bits.** It
  returns a STRENGTH index 0..9 (0 = the 5, 9 = the ace) in every mode, so
  `RANK_NAMES`, `CARD_VALUES` and every rank curve are indexed by strength,
  `beats` is still a plain `>`, and the base deck simply never produces a 0 or
  1. **`E.card_of(suit, rank)` is the inverse and the only correct way to write
  a card down** — `s * NRANK + r` is wrong for the wide deck and wrong for the
  base deck too if `r` came out of `rank()` or `TEN_RANK`. That is not
  hypothetical: it silently turned `TEN_RANK` into a queen and broke five Grand
  tests on the first run.
* **The two new ranks are worth ZERO, and each of the three reasons was
  measured before it was chosen** (`tools/dummy_matrix.py`):
  - the deck total stays **+16** — 4 × (0+0−1−1+2+2+2+2−1−1) — so a wider deck
    does not silently re-scale the ladder the level map keys on;
  - **it breaks the mod-3 granularity.** Every value used to be 2 mod 3, so
    three of them always summed to a multiple of 3: every dummy total was a
    multiple of 3, contracts of 7, 8 and 9 were literally the same contract and
    two thirds of the ladder was duplicate rungs. Reachable totals now run
    every integer from −7 to 18 and the gcd is 1. `dummy_auction_design.py`
    COMPUTES that gcd rather than printing a hardcoded 3, which is how the old
    claim would have survived the fix;
  - it gives the mode a genuinely **safe discard**, which is what free discard
    wants to feed on — a card that neither wins a trick you want to lose nor
    costs the taker anything.
* **`card_values` on the wire is SLICED to the deck the room deals** — eight
  entries in a 32-card room, ten in a dummy room — so a bundle cached from
  before the wide deck goes on indexing skat's table with `c % 8` and labelling
  every corner chip correctly. The client takes its offset from the LENGTH
  (`RANKS.length - t.length`), which needed no new field and no version bump.
  `bot.swap_policy_terms` slices the same way for the opposite reason: Rust's
  `SwapPolicy` indexes by its own 0..7 rank, so ten entries would price a 7 as
  a 5 client-side. (Dummy has no talon, so the rows are unreachable there.)
* **A dummy round dealt BEFORE this is DELETED on load, not migrated and not
  voided.** A round in progress plays from its own hands, so a ten-card round
  resumed under the thirteen-card layout runs fine to trick 10 and then jams
  with no legal move — a hung room with nothing red anywhere, not an error.
  `engine.deal_is_current` counts the union of hands / piles / out / played
  against `deck_size` and `load_game_to_memory` drops any row that fails it.
  Unlike the pre-v2 guard beside it, this had a live population: dummy shipped
  the same day.
  - **VOIDING IT IN PLACE WAS THE FIRST ATTEMPT AND WAS WORSE THAN IT SOUNDS.**
    It closed the round in memory (`phase="over"`, no result) and left the row
    saying `playing`, so the game sat in the player's Active list forever,
    re-voiding on every open — and the lobby's cancel is scoped to
    `status='open'` rows, so there was no way to be rid of it. It also blanked
    the BOARD: the result panel reads `res.made` as the first property it
    touches, so a closed round with no result threw
    `TypeError: null is not an object`. Nothing about such a round is
    recoverable — it cannot be played, continued or scored — so the row served
    nobody.
  - **The delete is safe because the predicate is EXACT, and that is the whole
    argument for making it a delete.** Every card sits in exactly one of hands
    / piles / out / played at every moment (`expand_state` rebuilds `played`
    from `history`, so it is never merely absent), so the union IS the deck and
    `deal_is_current` is arithmetic rather than a heuristic. A predicate that
    could be WRONG must never drive an irreversible delete —
    `test_a_playable_save_is_never_deleted_by_the_unplayable_guard` walks whole
    rounds in all four modes asserting it at every ply, because one that is
    right at the deal and wrong at trick 9 would destroy live games.
  - **THE LOBBY IS WHERE IT ACTUALLY GETS DROPPED, and the first delete missed
    that.** `load_game_to_memory` only runs when someone OPENS a room, so a
    game nobody clicks sat in Active exactly as before — the delete was there
    and the symptom was unchanged. `list_user_games` drops it too, and free:
    that function already decodes every row's `state_json` to work out whose
    turn it is.
  - **`_unplayable` is ONE predicate read by both paths**, because two copies
    of "can this be played" drift and the first symptom is a game that vanishes
    from one and not the other. It **fails safe on absence of evidence**:
    `list_user_games` hands over `{}` for a row whose blob will not decode, and
    treating "I cannot tell" as unplayable would turn one transient decode
    error into destroyed games — so a dict with no deal in it is left alone,
    and a test pins that an undecodable row SURVIVES.
  - The tests drive the SEAM, not the predicate: a predicate that passes says
    nothing about whether anything calls it. The result panel keeps its
    no-result branch as a NET, since the cost is a dozen lines and the failure
    it prevents is the entire screen.
* **Rust is untouched and stays that way.** `client_searchable("dummy")` is
  False, so the core never sees a wide-deck game; the parity fixtures, the
  `views.jsonl` wire fixtures and the committed wasm all describe the 32-card
  game and are still exactly right about it. `persist._pack_hist`'s card field
  is six bits, so ids up to 63 fit — the wide deck needed no format version.

**THE AUCTION IS A DECISION NOW, and the fix was the deal, not the ladder.**
Everything the old measurements said about it has moved:

| | ten cards a seat | thirteen |
|---|---|---|
| declarer's share of the pool | 0.69 → 0.57 (leader command) | **0.48** |
| corr(visible hand → points taken) | +0.06 → +0.15 | **+0.145** |
| forced-level EV at level 1 → the top | +10.4 → **+58.2 at 9** (bid the top) | **+7.2 → peak +21.4 at 6 → −8.0 at 12** |
| granularity of a trick | 3 | **1** |
| choices at a decision / plies forced | 2.89 / 33% (2.27 following) | **5.59 / 9%** |

The shipped 1..12 ladder therefore needs no re-pricing at all: it has a real
interior peak and a real punishment at the top, which is what
`dummy_auction_design.py` was written to look for and never found before.

**`_DUMMY_LEVEL_NEEDS` and `MATCH_TARGET["dummy"]` were BOTH re-anchored, and
the first attempt at each is the lesson.** A level map is a set of quantiles on
a distribution and does not survive the distribution moving: against thirteen-
card hands every one of the old 18.4–23.9 thresholds was cleared, so **100% of
contracts settled at level 12 and 13% were made**. Re-placed at 23.0–30.6
against the measured spread (p50 27.2, p90 29.0), self-play now settles
**2–10, mode 6 (2/5/15/21/28/19/6/3/2%), 74% made** — against classic's 82% and
skat's 85%, and with the mode sitting exactly on the EV peak. `MATCH_TARGET`
fell **400 → 200**: the declarer's collapse from ~12 of a 15-point pool to 7.7
of 15.6 took the mean winning round from ~61 to ~34, and 400 would now buy
nearly twelve rounds where classic's 100 buys ~6.2. 200 buys ~5.9.

**A NEW MODE rather than a change to skat, deliberately.** Skat keeps its
solver, its parity fixtures and its DD review column, and the two can be
judged side by side. The cost is that the modes now differ in SEAT COUNT,
which is why `layout_for` exists rather than the numbers being spread around.

**POSITION IS NOT SEAT, and conflating them is the mode's central trap.**
`to_play` returns a POSITION (0, 1, or the dummy's 2); `playing_seat` /
`turn_seat` return the PLAYER who acts for it, which for the dummy is the
declarer. `side_of` maps a position to the player it scores for. Everything
downstream reads the right one: `legal_moves` takes a SEAT (so every existing
caller is unchanged and a bare position returns [] rather than a wrong
answer), `history` records a POSITION (which hand a card came from is what a
replay and the board need), and the frontend compares against `turn_seat` —
comparing `to_play` told the declarer it was not their move on a third of the
plies they actually have to make.

**THE AUCTION WAS A LOTTERY AT TEN CARDS A SEAT, and the record is kept
because it is what the wide deck was bought to fix** (measured in
`tools/dummy_auction_design.py` and `tools/dummy_matrix.py`; the current
figures are in the wide-deck section above):
* the points a declarer took correlated **+0.07** with the hand they could see
  — and **+0.06** with a CHEATING count of the cards really in their two hands,
  so no honest estimator could do better and no pricing of the rungs helped;
* every card was −1 or +2 and both are 2 mod 3, so **three** of them always
  summed to a multiple of 3 (two do not: −2/+1/+4). Every total was a multiple
  of 3, so contracts of 7, 8 and 9 were **literally the same contract** and two
  thirds of the ladder was duplicate rungs;
* make pays N² against a set's N + 5×short, so at levels 9–12 the reward was
  quadratic against linear risk — forced-level EV ran +10.4 at level 1 to
  **+58.2 at level 9**, i.e. there was no such thing as bidding too high.

`DUMMY_COMMAND = "leader"` fixed the SHARE and was orthogonal to all of that
(it moved the correlation only +0.07 → +0.15). **The measured lever on
predictability was whether card VALUE is aligned with trick-winning POWER**,
over five tables: the shipped anti-aligned one read +0.07, a monotonic aligned
one (−1,−1,0,1,2,3,4,5) read **+0.39**, and a table spread WIDE but still
anti-aligned read **−0.18** — so it is alignment, not spread.

**That lever was NOT the one pulled, and the reason is worth keeping.** The
anti-alignment is the mode's whole premise — the cards that win tricks are the
ones that cost points — so an aligned table buys predictability by deleting the
game. What the wide deck did instead was give the players more CARDS (13, so
46% on rails instead of 60%) and one genuinely inert rank, and the correlation
came up to **+0.145** on its own with the premise intact. A design lever
measured strong is not thereby the right lever.

**THE BOT'S FIRST TRAP IS OVERTAKING ITS OWN DUMMY**, and the policy is
written against sides rather than positions to avoid it: if the declarer's
card is already winning, a dummy card that beats it wins nothing and only
spends a better card. `policy_score`'s card branch folds the trick so far,
asks whether the current winner is on ITS OWN side, and weights a
not-yet-final card lower (0.3 against 0.5) because the defender can still take
it off you — which is exactly the dummy's dilemma at position two.

**HARD AND EXPERT DO NOT RUN HERE, and that is enforced twice.** The Rust core
is two-seat to its bones (`State.hand` is `[Mask; 2]`, the solver alternates
between two players, the wire reader partitions a two-hand pool), so a
three-seat search is its own project. `engine.client_searchable` says so;
`_handle_client_ai_ready` refuses to arm a dummy room at all, and `/catalog`
ships `searchable_modes` so the create modal need not offer a tier that cannot
run. Without both, an armed client would answer with a card for the wrong hand,
the engine would refuse it, and the room would play the server bot at full
speed while the label said Hard — the failure this repo has paid for twice.

**Two consequences worth knowing:** a dummy round banks **no review snapshot**
(the DD column is an exact solve, and nothing can price three hands), and its
**history stays verbose at rest** — the packer has one bit of seat and a
position needs two, so `persist._packable_hist` asks the DATA and leaves
3-seat histories alone, which `expand_state` already discriminates by shape.
Versioning the format instead would have risked every stored row to save bytes
on a mode that has none.

**Coverage is Python-only and that is the whole risk.** The parity fixtures
are two-seat, so `tests/test_dummy.py` (20 tests) is the only thing standing
behind this card play AND behind the wide deck: the deal partition (asserted
against `deck_size`, never a literal), every base id proving it did not move,
the eight new cards being a 5 and a 6 per suit that every 7 beats, their zero
worth and the deck total not moving, the trick gcd being 1, the sliced wire
table, dummy-second/never-leads over whole rounds, the declarer acting for it
and the defender never being able to, a dummy trick scoring for the declarer
and handing it the lead, the pool conserved, free discard, the redaction (its
hand open, its outer bottoms shut, the opponent's hand still hidden), and the
persistence round trip. `screens.mjs` drives the create modal to a dealt dummy
room and asserts the third seat renders face-up with its own piles, that a
trick really reaches three cards, and that **a 5 or a 6 renders as itself** —
a client still decoding ids as `suit*8 + rank` would draw the eight new cards
with a blank glyph and an undefined rank rather than throwing.

## Must head the trick — MEASURED, THEN SHELVED THE SAME DAY (2026-08-10)

**`MUST_HEAD` is off in every mode.** The implementation is kept whole and the
gates still drive it through the flag (the `_score_is_settled` idiom), because
the rule works and the measurement below is the only reason it is not on. The
dummy above is what was tried instead. When it was on: when you CAN follow
suit and hold a card that BEATS the lead, you must play one. Ducking under a winner is legal only when you cannot beat it at all.
Ruffing is untouched: void in the suit you may still play anything and are
never forced to trump — must-head filters the FOLLOW set alone.

**Its own per-mode dict (`MUST_HEAD`), deliberately NOT folded into
`uses_card_points`.** A legality rule and a scoring rule are different things,
this one is an experiment, and one line turns it off — including the wire
requirement below, which is derived rather than pinned.

**WHAT IT IS WORTH IS ONE TRICK SHAPE, and that is measured, not asserted.**
Enumerating every shape, the rule changes the outcome of exactly one:

| lead | they hold | without | with |
|---|---|---|---|
| **K** | 9, A | 9 → **+1 to the leader** | A → **−2 to them** |
| K | 7, A | 7 → −2 to leader | A → −2 to them |
| 9 | 8, K | K → +1 to them | K → +1 to them (unchanged) |
| 7 | 8, K | K → −2 to them | unchanged |
| A | 7, Q | 7 → −2 to leader | unchanged |

So the whole mechanic is **lead a king, force the ace** — a three-point swing
that turns the deck's two dead cards (K and A, both −1) into a duel, and makes
a bare ace a real exposure. It does NOT fix the complaint that prompted it
("you win with an ace and they slide a 7 under it"): nothing beats an ace, so
must-head never fires there. Know that before spending more on this direction.

**HOW OFTEN IT BINDS — and the gap that matters:**
* random play: 7.4% of plies · **the shipped greedy policy: 6.2% of follows**
* **a leader who CHOSE to could bind on 34.4% of tricks** (counterfactual over
  real rounds: at each lead, does any legal lead narrow the follower?).

The 5.5x gap is the whole story: it is a lever the bot was not pulling, not an
inert rule. Leading LOW — the card policy's default — is precisely the lead
that can never bind, since every follow beats it. The searching tiers get the
lever for free (an exact solver over the real legality); the greedy tier had
to be taught, so `policy_score`'s card-lead branch now scores the EXTRACTION
LEAD: a liability card whose every unplayed beater is also a liability, read
off `played` plus this seat's own holding (honest counting, decays to nothing
once the ace is gone, weight 1.6). That took binding 6.2% → **9.7%**, and both
seats wield it, so the declarer's make rate lands back on **85%** — the same
figure card scoring measured without the rule, so `_SKAT_LEVEL_NEEDS` needed
no re-anchoring. Mean winning payoff 20.1 → 20.6.

**Caveat worth keeping:** of the follows it binds, ~85% leave the follower no
choice at all, so what the rule mostly does is move a decision from the
FOLLOW to the LEAD. That is the intended direction (the lead is where control
was missing) but it is a transfer, not an addition.

**The inference it buys, and why it is not optional.** Following without
beating proves the seat could reach no higher card of that suit — so none is
in hand, and hands only shrink, so the ceiling is permanent.
`Knowledge::hand_cap` records it (hand-written `Default`: `NRANK - 1` is "no
constraint", and a derived zero would assert both players hold nothing above
the deck's lowest rank), `determinize` keeps capped cards out of the hand and
lets them fall into the covered pile slots — the same "piles launder voids"
property the module note already describes — and `wire.rs` mirrors it from
history. Without it the searcher spends its worlds on deals the opponent has
already disproved, silently.

**Rung 4 on the wire, and it is a HARDER rung than 2 and 3.** Those carried
scoring fields, so an artifact missing them returned legal-but-misvalued
moves. This one carries LEGALITY: an artifact without it answers with cards
the room refuses, `_validated_bot_move` drops them, and the room plays the
server bot at full speed while still saying Hard. `odd_wire()` is 4, the
worker refuses any payload whose `must_head`/`head` it cannot honour, and
`_handle_client_ai_ready` computes what a room NEEDS from its own rules
(`must_head_mode` → 4, else card scoring → 3) rather than pinning a literal.
The artifact was rebuilt and committed with the change.

Gates: `must_head_forces_a_winner_when_one_can_follow` and
`a_must_head_ceiling_is_inferred_and_respected_by_the_determinizer` (Rust),
`beats_mask_agrees_with_beats_over_the_whole_card_space` (the mask form drives
the filter and sits on the hot path, so it is swept exhaustively), the
brute-force solver's card arm now runs the shipped cards+head combination, and
`play.jsonl` carries `head` on its card fixtures with a NON-VACUITY test —
must-head bound on 192 of 2600 fixture plies, so a legality break really would
surface as an illegal move rather than passing unnoticed.

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

(**Dummy mode deals 40** — the same 32 plus a 5 and a 6 in each suit, at ids
32..39 — because three seats of thirteen do not come out of 32. Same 7 + three
piles per seat, one card out. `deck_size(mode)` is the only place that varies;
see the wide-deck section under DUMMY mode above for why the ids were appended
rather than the deck renumbered.)

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

**Scoring** (contract only; trick points are the yardstick *and* the margin —
and in skat mode "trick points" means CARD points, per the section above):
make → **N² + 1 per trick point past N**; set → defender scores
**N + 4 × shortfall**. **NULL OVERRIDES A SET**: a declarer who won **no +2
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
* **set base N, not N−1 (2026-08-07)** — a product decision, not a measurement,
  and it is one number in one place (`_terms_for`'s classic `set_base`). At the
  floor the old base contributed *nothing*: breaking a level-1 contract paid the
  defender by the margin alone, and ~42% of openings sit at level 1. It adds
  exactly 1 to every set in the mode, so it can never reorder two set results —
  what it moves is set-vs-make and set-vs-Null, both by one. **Everything
  downstream follows for free**: `payoff_terms` ships to the Hard tier, so the
  bot re-priced itself with no bot code at all, and the only files that had to
  change with it are the ones holding a SECOND copy — `payoff.jsonl`
  (regenerate: `PYTHONPATH=. python -m games.dissonance.tools.gen_payoff_fixtures`),
  the Rust harnesses that hand-build classic terms (`bid.rs`'s test `opt`,
  `cmatch.rs`, `abench.rs`), and the two places that print the arithmetic to a
  human (the result panel's maths line, `rules.jsx`). Skat is untouched: its set
  base is the STAKE, so there was no N−1 in it to add to.
* **short 4** — the sacrifice dial. Doubling it roughly halves sacrifice bids.
* **per-player denominations** — a shared budget was measured to be a no-op:
  94% of auctions name ≤2 denominations, so a budget of five never binds.

## The round-end panel says POINTS or SCORE, never both as "scored" (2026-08-09)

The round has two quantities that are both "how much", and the panel used one
verb for both. They are now fixed vocabulary, in the classic/minor result
panel and in `rules.jsx`:

* **points** = TRICK points, the currency the contract is measured in;
* **score** = what the round pays onto the scoreboard.

So a made round reads *"Alice bid 4♠ and took 3 extra points"* over
`(4 × 4) + 3 = 19 to Alice`, and a set one *"…finished 2 points short"* over
`4 + (5 × 2) = 14 to Bob`.

* **The formula is COLOUR-KEYED to the sentence and deliberately NOT
  simplified.** The contract level is plain full-strength text, trick points
  are blue, the score is the panel's green (`.dis-n-lvl` / `.dis-n-pts` /
  `.dis-n-score`), so the `3` in "took 3 extra points" and the `+ 3` it turns
  into are visibly one number. The old line reduced through an intermediate
  (`4 × 4 = 16 + 3 = 19`); the shape is now constant — `+ 0` on a contract
  brought home exactly included, because a formula whose SHAPE moves with its
  values has to be re-parsed every round.
* **A DOUBLE IS REPORTED AS THE DIFFERENCE IT MADE (2026-08-09)** — "Doubling
  earned Alice 55 — 110 instead of 55", not "the set base went 9 → 20". The old
  line narrated an internal term rather than the bet the player had just
  watched, and quoted `level - 1` for the undoubled base: the **pre-2026-08
  N−1 rule**, a number the game had not charged in months. `_finish` now puts
  `undoubled` on the row — this same round re-scored through `payoff` with the
  bet taken off — so the comparison is the engine's arithmetic, not a second
  copy in JS. Two properties make the panel's magnitude comparison sound and
  both are asserted: a Double can never flip WHO won (it scales both ends and
  the ramp only adds), and it can only raise the stake it was placed on.
* **A DOUBLE MULTIPLIES THE OVERTRICK RATE TOO, and the old line dropped it**:
  it printed `4 × 4 × 2 = 32 + 3 = 38`, which does not add up, because the tail
  only ever showed the raw points while the payoff charged `over_bonus × over`.
  Doubling now rides inside the term it multiplies.
* **Twice a hardcoded rate has outlived the number it copied.** `+ 4 × short`
  survived the 4 → 5 move in BOTH the skat maths line and the side panel, each
  printing a sum that did not reach the score displayed beside it — the score
  was right, only the story about it was wrong, so nothing failed.
  `_finish_skat` now puts `short_rate` on its row (classic already did) and
  both lines read it. **`test_the_result_row_carries_every_term_its_own_score_
  needs` is the gate**: it plays real rounds in all three modes, forces the
  Double so the ramped branch is reached, and re-adds the row's own terms to
  demand they reproduce its score. Verified non-vacuous by putting the stale 4
  back — it fails.

## Double — classic's defender bet, priced for the SACRIFICE (2026-08-07)

A `double` phase between the classic swap and trick 1, the DEFENDER to act.
Skat keeps Kontra; classic gets this, and the two are deliberately different
shapes. `g["doubled"]`, `classic_doubling`, `apply_double`.

    made   N^2  ->  2 N^2      (the overtrick rate doubles with it)
    set      N  ->  2N, and the shortfall RAMPS: 5, 6, 7, 8 a point
                    (`DOUBLE_RAMP`) instead of a flat 4
    Null    12  ->  12         (untouched, as skat's Kontra leaves its own)

**Kontra is symmetric and this is not**, which is the one thing to keep hold
of: because a made contract doubles while a set one steps by N+1, DECLINING IS
NOT WORTH ZERO — it is worth the undoubled contract. So `auction_payoff_options`
prices BOTH branches as their own options, each carrying its own move, and the
Hard tier picks the better. Skat's Kontra can ship one option and decide on its
sign precisely because its doubling cancels out of the comparison.

**MEASURED, and the first measurement was of the WRONG SCENARIO.** Doubling
risks N² and, flat, wins only N — so break-even climbed 50/67/75/80/83/86%
across levels 1-6 while contracts bid NORMALLY fail only 4/9/18/24/37/56%
(2500 self-play rounds). Against ordinary bidding no level was a profitable
Double, and that is what an initial measurement said, full stop.

**It is not for ordinary bidding.** The mechanic is for the SACRIFICE: a player
about to concede a big made contract overtakes at a level they cannot reach,
purely to deny it — 6♣ over 5♠, because 25 points is worse than being set. And
sacrificing PAYS at every level (gain over conceding +3.3 / +5.7 / +9.1 / +13.0
at levels 3-6), so it is a default response, not a desperation move.

**THE RAMP IS WHAT MADE THE MECHANIC WORK, and the reason is one line of data:**

| when a contract is set | median shortfall | short by exactly 1 |
|---|---|---|
| ordinary bidding | 2 | **48%** |
| sacrifice | 4 | 13% |

Scaling the doubled base by N taxes the LEVEL, which both cases share. Ramping
taxes the SHORTFALL, which only a sacrifice has. Measured EV of doubling:

| scheme | ordinary lvl 6 | sac @5 | sac @6 | worst round | sacrifice RATE |
|---|---|---|---|---|---|
| 2N flat (first ship) | −13.82 | −1.63 | −0.24 | 48 | 36% → 36% |
| 3N flat | −10.62 | +1.86 | +4.41 | 54 | 36% → 36% |
| **2N +1 ramp (SHIPPED)** | **−11.70** | **+4.56** | **+9.20** | **93** | **36% → 23%** |
| 2N +2 ramp | −9.58 | +10.75 | +18.64 | 138 | 36% → 7% |

`2N +1` was chosen because it turns Double on exactly at level 4 and above,
which is where sacrificing becomes clearly profitable, and TAXES the play rather
than removing it: a level-6 sacrifice still nets the sacrificer ≈+2.6 over
conceding. `2N +2` drives the rate to 7%, i.e. it deletes a strategic option.
The tail matters too — a match runs to 100, and `+2` allows a single round of
138.

**Opening aggression does not move at all** (1.82 under every scheme): Double
answers a SETTLED contract, and the opener acts before any of that is known.
What moves is the END of the auction — settled level 6.20 → 6.08 → 5.89 as the
sacrifice-overbidding it was made of gets taxed away.

**Do not re-measure this against self-play alone**: the shipped bots did not
sacrifice at all until the pass was priced, so a sweep can only ever produce the
first row.

* **The server tier declines every Double**, because it cannot TELL the two
  apart. The obvious signal is the defender's own holding and it does not
  work: the set rate is 38-43% within normal play at EVERY strength gate and
  78% within sacrifices at every gate. A gate at strength 11 fires on 58% of
  sacrifices and 6% of genuine high contracts, which only pays if sacrifices
  are half as common as real contracts. They are not.
* **The Hard tier decides by search, and this is the point.** What separates a
  sacrifice from a real contract is whether the target is REACHABLE, which is a
  solve rather than a rank sum. It gets both branches priced and takes the one
  worst for the declarer, so it doubles precisely when the contract is dead.
  Needed NO Rust change and no wasm rebuild — `contract_from_json` and
  `options_from_json` already read every term generically, which is the return
  on shipping the scoring as numbers instead of as a second copy of the rules.
* **The Null escape is real**: 9-10% of sacrificing declarers duck to the flat
  12, which Double does not touch. Already counted in the EV above.

**Inserting a phase is not free**, and this is the shape of the cost: 160 tests
went red at once, essentially all of them drivers that walked swap -> play in
one step. The one REAL bug among them was `view_for`'s `sees_shown`, which read
`phase in ("swap", "play")` — so the classic declarer lost sight of the talon
for exactly one phase, and the Hard tier would have been handed a different
out-of-play set for the Double than for the opening lead immediately after it.

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
* **…and the lobby History row must READ it (fixed 2026-08-07).** It shipped
  reporting `result["scores"]` — the score of the DEAL that happened to end the
  match — so a match taken 100–84 listed as "Won 9–0" and one lost by the
  opponent crossing the line listed a loss on a round the reader could not tell
  apart from the whole game. The keys were on the row from the day matches
  shipped; nothing read them. Now: `match_scores` (falling back to `scores`, so
  a genuinely one-round save is still right), plus `rounds`/`target` so the meta
  line says "12 rounds to 100" instead of narrating the last deal's contract —
  which is one deal in ten and read as the headline. The contract line is kept
  for the one-round case, where it *is* the whole game. `tests/test_history.py`
  drives real played-out matches through a temp sqlite file, because a
  hand-built result row only pins the shape the test itself wrote.
  A match can also end LEVEL (a forfeit closes it regardless of the target), so
  the row has a third state — the shared kit's `tie` class, which CoC and
  Dontminion already use.
* **The match keeps a SCORECARD, `match["rounds"]`** — one line per round
  banked: the contract, the declarer's trick points against what they promised,
  and the round's scores. The side panel's "Match to 100" box renders it under
  the running total (`MatchCard`), because a total says who is ahead and nothing
  about how: which rounds were bought cheaply, who has been declaring, whether
  the gap is one big set or six small ones.
  - **Every line is DERIVED from the result row, in `_bank_round`.** The three
    finishers (`_finish`, `_finish_skat`, `abandon_result`) now build their
    result dict FIRST and hand it over, so the scorecard cannot disagree with
    the panel that narrates the same round — re-reading made/null/target off the
    board would have been a second copy of the scoring, which is what
    `payoff_terms` exists to prevent.
  - **A DOUBLED ROUND SAYS SO ON ITS LINE (2026-08-09)** — `doubling` on the
    row, rendered as a gold `×2` / `×4` chip after the contract. Without it a
    doubled round sat in the box as an ordinary line with a surprising number
    beside it, which is precisely the row a reader wants explained. It carries
    the MULTIPLIER rather than either mode's word for the bet, so classic's
    Double and skat's Kontra-then-Re land in one field and the box needs no
    idea which auction the room ran; it is read off `res` (skat already had
    `doubling`, classic has `doubled`), so no rule is re-derived here. Absent
    on a round banked before it shipped, which reads as undoubled — correctly.
    Gated by `test_the_scorecard_line_says_a_round_was_doubled` and the skat
    Kontra/Re case beside it, both verified non-vacuous.
  - **`rounds` is `setdefault`ed, never created in `new_game`** — same reason
    `match_of` exists. A match already in progress when this shipped has no
    scorecard and must go on banking rounds rather than KeyError; its earlier
    rounds are simply gone, and there is nowhere to recover them from.
  - A pass-out redeal adds no line, because it is not a round.
  - It rides in `view_for`'s `match` (wholly public, like the totals) and
    through `persist.py` untouched. ~8 small keys x a median of ten rounds.
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
`N + 4 × shortfall`, so every remaining trick still moves the shortfall);
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
* **The side panel's order is TALON → match → contract → last trick → points**
  (2026-08-07). The talon is the only panel there you play *from* rather than
  read after the fact — three cards you know are out of play is a holding to
  count from — so it sits at the top of the column, above the standing. It was
  fourth, under Last trick, which put the thing you paid the auction to see
  below two panels that only report. The phone rules drop Contract and Points
  (both duplicated elsewhere) and stack the rest, so the order carries there
  too.
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

## The board screen — pinned to the viewport, three columns wide (2026-08-10)

Nothing on a game screen may be below the fold: at any normal resolution the
whole board is visible and **there is no page scrollbar to have**. `.dis-game`
is `100dvh`, a flex column, `overflow: hidden`; the table takes what the header
leaves and is a `container-type: size` box, so the card budget reads the table's
**real height** (`100cqh`) rather than guessing from the window. Seats keep their
card-derived height; the variable-height panels (`.dis-auction`, `.dis-result`)
take the slack and scroll **inside themselves**, so a miscalculation shows up as
a scrollbar on one panel and never as a hand clipped off the bottom. Below 761px
wide or 600px tall the page scrolls instead — that is the honest answer for a
phone and for a window too short to fit a board plus an auction panel at any card
size.

`.dis-main` is a grid, and **every tier places all three items by hand**. The DOM
order is board → `.dis-side-info` → `.dis-side-match`, which is what a phone
stacks and a screen reader hears; the desktop grid overrides it:

| width | shape |
|---|---|
| ≤760 | one column, everything stacked, the page scrolls |
| 761–1199 | felt left, info panel over match panel in one right-hand column |
| ≥1200 | **match left, felt centre, info right** |

Four things there are load-bearing and were each paid for:

* **`align-items: stretch`, not the base `start`.** A size container with no
  definite height reports `100cqh: 0`, which drove the card budget negative and
  collapsed the board to a 31px sliver.
* **The felt FILLS its column (`width: 100%`).** It briefly sized itself to its
  seven cards instead — but the cards are height-capped on any normal desktop, so
  hugging them left the surplus width as bare *page*, not table: black where the
  user wanted green. The flanking panel columns take most of that width for
  content now; the rest belongs to the felt.
* **…and that width must stay DEFINITE.** The same 31px sliver has now appeared
  twice: once from `margin-inline: auto` beating `justify-self: stretch`, once
  from a malformed comment above the declaration silently dropping it. A size
  container has no contents to fall back on. `screens.mjs` asserts the felt is
  ≥45% of the grid, which catches both.
* **`:has(> .dis-side-match)` gates the three-column tier.** The match panel is
  conditional (a game saved before matches existed has none), and reserving a
  column for an absent element re-creates the empty flank.
* **Each flank has one panel that takes the slack** — the scorecard on the left,
  the trick history on the right — so the columns are full rather than a stack
  of panels with bare page under them. That is also why the wide tier shows all
  thirteen tricks instead of a five-row window.

**The auction and the round-end report sit BESIDE the cards** (≥1200px), in a
17–24rem rail inside `.dis-table` — the seats auto-place down column 1, the panel
is pinned to column 2 spanning the explicit grid, and `.dis-3seat` is the only
thing that has to know the row count. They used to be a row *between* the seats,
which cost twice: the card budget paid for them (`--dis-rows: 4` against a `30rem`
reserve, versus play's 5 against 17.5rem), so **the board visibly redrew smaller
for the auction and again for the report** — at the one moment you want to
compare it with what you just played — and the report, the tallest thing this
screen ever shows, scrolled inside itself while a third of the felt sat empty.
In the rail both go away: the seats keep the PLAY budget at every phase, and the
report has a full-height column to be tall in. `min-height: 0` on the panel is
what keeps it out of the row sizing — an auto track otherwise sizes to a spanning
item's min-content, and the report would be setting the seats' heights.
`screens.mjs` asserts the card width is **identical at the auction, in play and
at the report**, which is the claim that matters and the one nothing else sees.

**The parity modes' bid ladder tops out at 10** (`PARITY_MAX_LEVEL`), and that is
a product cap, not an arithmetic one: 11 and 12 are reachable (six even tricks
plus one odd, and a clean sweep) but never bid, and twelve buttons is not a shape
— ten is two rows of five. **Skat is deliberately untouched**: its levels
multiply a base rather than promise points, so `SKAT_VALUES`, `skat_declarable`
and `apply_declare` all keep reading `MAX_LEVEL` (12) and its 32-rung ladder is
unmoved. Three things had to move with it, and each is the kind that fails
confusingly: `test_rust_parity`'s synthetic contract took `max_level_for` and now
takes the **parity ceiling** (it exists to stop `_score_is_settled` firing, and
the two stopped being the same number); `gen_auction_fixtures` named `MAX_LEVEL`
for its ceiling states, so the states it generates stopped being ceiling states;
and `wire.rs` asserted classic nodes at `level >= 11`, which is now unreachable
and would have failed as "the fixtures are thin". All three are ceiling-relative
now. The Expert auction search needed nothing — it already reads `max_level` off
the wire, which is why minor worked the same way.

**The trick line is STACKED under the cards, in flow** (`.dis-trickcards` +
`.dis-trickinfo`). It used to be one row with the line absolutely positioned at
`bottom: -4px` — a 4px offset against a ~14px name label — so "Trick 5 of 13 ·
−1" drew straight through the "who played this" name under a card. Reserving a
padding band for it did **not** fix it: on a short screen the cards sit at their
`3.4rem` floor, so the board is deliberately over budget and this row is what
shrinks — and flex content overflows a shrunken box right back through the band.
Stacked in flow, a squeeze cannot make two rows overlap. `screens.mjs` measures
the two rects, because nothing else can see it.

The Contract panel carries the **bidding** and the Points panel the **round's
trick history** (`BidLog` / `TrickHistory`, both off one `trickList(game)`
derivation shared with the Last-trick panel). The bid log used to live inside the
auction panel, so it vanished the moment the auction ended — which is when
"what did they bid to get here" is asked most. Those two panels used to be
`display: none` on a phone as duplicates of the contract chip and the seat rows;
they are not duplicates any more, so the phone shows them.

`poolNote(game)` replaced a hardcoded "Always adds up to +5." — classic's parity
and nobody else's. It is derived from the wire (`tricks`, `even_val`), so minor
reads −1 and the next parity mode is correct without an edit; card scoring has no
constant to state (its pool is a property of the deal) and gets its own sentence.

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

## Tests (490)

`test_minor.py` (24) minor mode end to end — the ±1 parity and the −1 pool,
the derived 1..6 ladder, the re-anchored prices (Null 6, set rate 2, the
Double's arithmetic), Null-replaces-set, the result row naming its mode and
prices, `even_val` on the view / `even` on the deal snapshot surviving
persist, minor-priced auction options and the Expert payload's
classic-shape-with-minor-ceiling, the bot inside the ladder, and the
three-part stale-wasm gate's server half (a minor room arms only a `wire: 2`
client; classic/skat accept any vintage) ·
`test_engine.py` rules (including the match SCORECARD: one line per banked
round, derived from the result row, none for a pass-out, and a match that
predates it gaining one without crashing) · `test_history.py` (5) the lobby
History row — the MATCH standing rather than the last deal's, the rounds/target
line, both seats reading the same match from their own side, a forfeit, and a
pre-match save still read as one round · `test_rust_parity.py` the drift gate ·
`test_bot_fairness.py` (14) the bots see only their own seat, by INVARIANCE
over re-dealt hidden cards, plus EXACTLY what an auction decision may consult ·
`test_double.py` (52) classic's Double: the doubled arithmetic, the phase, and
the measured reason the server tier declines while the search does not ·
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
tier agreement · `test_expert.py` (16) what the server ships so the browser can
SEARCH the auction: the payload is the auction verbatim, every settlement it
prices is `_terms_for`'s own answer, every option the server offers has a row to
settle on, unreachable rows are pruned, and only an EXPERT room carries the
block at all.

Rust side, `cargo test --features bridge` runs `wire::fixture_replay` (the
wire-reader gate above) plus `tests/engine.rs`, the 16-test mirror of
`test_engine.py`. Three of those are Grand's: the fifth-suit rules, the
whole-card-space no-regression sweep, and a trump void surviving the
determinizer. `solver_matches_brute_force` also sweeps `DENOMS` now and asserts
it reached Grand — the equivalence collapse is the one place a Grand bug would
show up only as a slightly wrong VALUE, which nothing else would notice.

**RUN IT — and since 2026-08-07 so does CI: `.github/workflows/
rust-dissonance.yml` runs this exact gate on every push touching the crate or
the committed fixtures** (it deploys nothing — the wasm artifact stays a
by-hand `wasm-pack` step). The workflow exists because a broken Rust test
target is invisible here in a way a Python one never is — nothing goes red,
the suite simply stops existing — and this crate had already been bitten
twice. `tests/engine.rs` had not COMPILED since the deck-width
campaign (`2a8957b`) took masks from 32 to 64 bits: it kept a `let mut covered
= 0u32`, which stopped type-checking against `Mask`, and the whole target — all
13 tests — silently dropped out of every run for the entire v2 release. Behind
it sat a second stale assertion (`v.len() == 28`, "26 dealt + 2 out of play")
that had been wrong since the deck went to 32 and had never once been executed.

Both are now DERIVED from `NCARD` / `NDEALT` / `NOUT` rather than written as
literals, so they hold under the `rank7` / `rank9` / `rank10` builds too — which
is not a hypothetical, since a literal 28 is wrong under three of the four and
`rank7` is exactly the 28-card game the pre-sweep numbers were measured on.

The second bite was the GATE itself: `[profile.release] panic = "abort"`
(there for the wasm artifact) made `cargo test --release` fail its FIRST run
from every clean checkout — the cdylib's abort flavour and the test targets'
forced unwind collide in one build graph — and pass on the re-run once cached
unwind artifacts exist, which is exactly the friction that stops a by-hand
gate being run at all. Removed 2026-08-07; the Cargo.toml note carries the
measurement (the shipped wasm does not change).

Browser side, `webapp/test/screens.mjs` drives the skat **create-modal segment**
through to a dealt room and a first bid — a mounted screen says nothing about
whether a new room flag can actually be created (the Renaissance lesson) — plays
a **whole Hard game** and counts `client_ai_ready` / `ai_move` on the socket
(every failure in the Worker→wasm→fetch chain degrades to the server bot, so a
game that plays out perfectly is exactly what the fallback looks like), and
measures the **completed-trick beat** described above. It also reads the match
**scorecard** off the rendered panel — cells, not a substring — and asserts
round 1's line survives the next deal: the panel is fed by `match.rounds` off
the wire, so a field that never shipped and a panel that renders nothing look
identical from the outside.

## The Hard tier — an exact solver, in the player's browser (2026-08-07)

`easy` / `normal` / **`hard`** / **`expert`**. Hard's CARD PLAY is
`dissonance-core`'s `PimcBot` compiled to WASM and run client-side; Expert is
that plus a search over the AUCTION (its own section below).

**WHAT THE BROWSER ACTUALLY BUYS — measured 2026-08-07 on the v2 rules, since
the old "69.8% behind `pimc:8`" figure predates the 32-card deck, Grand and the
payoff-aware search.** CRN-paired `bin/arena`, 120 paired deals, mirror reading
exactly 0.0000; edge in trick points per round to the stronger side, on a pool
where both players' totals always sum to 5:

| | vs `greedy` | doubling buys |
|---|---|---|
| `pimc:1` | **+0.04 ± 0.11** | — |
| `pimc:2` | +0.46 ± 0.11 | +0.42 |
| `pimc:4` | +0.90 ± 0.12 | +0.44 |
| `pimc:8` *(shipped cap)* | **+1.10 ± 0.10** | +0.20 |
| `pimc:16` | +1.20 ± 0.10 | +0.10 |

and search against search: `pimc:8` over `pimc:2` is +0.58 ± 0.10, `pimc:32`
over `pimc:8` only **+0.21 ± 0.08** for four times the compute.

Three things follow, and they are the answer to "is client-side worth it":

* **`greedy` IS what the server plays.** When the browser does not answer,
  `_bot_move_sync` falls through to `bot.act` — the same one-trick-deep policy
  Normal uses (`GreedyBot` is `policy_best`, which `bot.choose_card` ports).
  There is no server-side search at any tier, so **Hard without a browser is
  Normal**, and the whole +1.10 is what the client buys.
* **One world of exact solving is worth NOTHING** (+0.04 ± 0.11 — inside the
  error bar of the heuristic). The strength is in AVERAGING OVER UNCERTAINTY,
  not in the double-dummy solve, so a server that could afford one world per
  decision would gain nothing at all for the trouble.
* **Past the shipped cap a faster machine buys very little.** 8 → 32 worlds is
  four times the compute for +0.21, so a fast desktop is not meaningfully
  stronger than a slow laptop here — the CAP binds, not the CPU (except at ≤4
  cores, where the worker pool itself shrinks).

**This is CARD PLAY only.** The auction's compute→strength curve is still
unmeasured; its cap is a separate `CLIENT_AI_AUCTION_WORLDS` (3) and nothing
says whether that sits at the knee the way 8 does here.

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
  seconds for a bid. Hard is a card-play tier until that is measured. (It has
  been, twice over: the Hard AUCTION and then Expert's tree, both below.)
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
* **PASSING IS PRICED (2026-08-08), and it was the tier's biggest blind spot.**
  It used to be valued at zero, so the bot passed rather than buy a contract
  that priced negative. That makes a SACRIFICE unreachable by construction — a
  sacrifice is a contract that prices negative, bought because passing prices
  worse — and it also bought contracts it should have declined whenever the
  opponent's standing contract was worse for them than a bad one is for us.
  `engine.pass_options` now ships the pass as a priced option like any other:
  the STANDING contract, priced from the opponent's side, flagged `opp: True`.
  - **`opp` means SOLVE THE OTHER SIDE, not flip the sign.** The declarer LEADS
    to trick 1 (worth ~0.93 points), so swapping who declares changes the
    POSITION, not the perspective. `World` carries `opp_pts`/`opp_duck` from
    their own `solve_world` pass, `Solved` tracks a second `covered_opp` mask,
    and `price` negates the result because every option in the list is signed
    for the seat being asked.
  - **Cost is one extra solve per world**, for the standing denomination only —
    not double, because our own side already solves up to five.
  - **A skat pass-out is `redeal: True`, priced flat at 0** — a fresh deal
    neither seat has seen — and needs no solve. Priced rather than omitted so
    `pass` is always in the list when it is legal.
  - **A skat pass prices EVERY game the standing number buys them**, because the
    winner has not named one yet; the search takes the worst for us, which is
    the same as assuming they declare well.
  - **MEASURED: +0.7175 points per round** over 400 paired rounds, `bin/bidlab
    solve nosac` — `NoSac` is exactly the old restriction ("refuse to overtake
    unless expecting to make it"). The sacrifice-capable bidder sacrificed 4.2%
    of rounds. Caveat: that harness runs the design campaign's `auction.rs` on
    the pre-2026-08-07 scoring (set base N-1, doubling off), so read the sign
    and the magnitude, not the third decimal.
  - The classic opener must bid, so there is no pass option at all there.
  - **Back-compat is by omission**: `opp`/`redeal` are optional and default
    false, so a cached wasm older than the server prices every option as one it
    could buy itself and falls back to the old "value <= 0 means pass" rule the
    client still carries for exactly that window.

* **A REJECTED OPTION EMPTIES THE WHOLE LIST, and that silenced the skat tier
  entirely (found + fixed 2026-08-08).** `options_from_json` returns
  `Vec::new()` on any malformed entry — deliberately, since a partial list would
  be scored positionally against the wrong moves — and its denomination guard
  was `(0..=4)`. **Grand is denomination 6**, and `skat_declarable` offers Grand
  at every rung, so EVERY skat auction and declare decision came back empty, the
  client answered nothing, and the room played out on the server bot while still
  saying Hard. Silent, deal-independent, and live from the Grand release until
  this fix. The guard is now `DENOMS.contains`, and
  `every_denomination_the_server_can_offer_survives_the_option_reader` walks the
  whole roster so the next denomination cannot repeat it.

## EXPERT — the auction as a game tree (2026-08-08)

A fourth tier: `easy` / `normal` / `hard` / **`expert`**. Expert is Hard in
every respect except one — its AUCTION decisions are a minimax over the bidding
tree (`rust-cores/dissonance-core/src/auc_search.rs`) instead of a price list.

**WHY, precisely.** Hard prices each option as "if I end up declaring THIS
contract, what does it pay". Pricing the pass told it what CONCEDING costs; it
still has no model of the opponent's REPLY, so two things are unreachable:

* **underbidding to CAP an auction.** `MAX_RAISE` is 2, so opening at 1 holds
  the responder to level 3 on their turn. Opening at 1 on a hand worth 4 prices
  as ~1 point, so the myopic search never picks it — even when capping them at 3
  is the whole play. (This is exactly the line the design brief described: *"if
  you have a terrible hand, you can open at the 1 level and pass when they bid
  3, limiting how much they can score."*)
* **judging a RE-ENTRY.** Measured on shipped Hard: of 43 classic rounds that
  opened at level 1, only 30% passed when overtaken.

**IT COSTS NO EXTRA SOLVES OF ITS OWN.** The expensive half is `bid::Solved`,
already cached per hand; every leaf here is arithmetic. What it *does* ask for
is more DENOMINATIONS — whatever either seat could still bid, on both sides,
rather than Hard's own five plus the opponent's one — so the first decision of a
hand roughly doubles and every one after it is free. Measured natively at k=3,
one process, classic: **0.81s → 1.56s for the first decision, ~0 for the rest**;
skat 1.11s → 2.66s. In a browser that is spread over the worker pool (one world
each rather than three), so it lands around 0.5s / 0.9s against a 12s watchdog.

**WHAT CROSSES THE WIRE IS DATA, NOT RULES — with exactly ONE exception, and it
is gated.** `engine.auction_search_payload` ships three things on the armed
request as `auction.search`: where the bidding stands, the legality knobs, and a
priced row per settlement still reachable, each built by `_terms_for`. So the
SCORING is not duplicated at all, the same discipline `payoff_terms` established
for card play — change a payoff and Expert follows with no bot code.
- **The auction's LEGALITY is mirrored**, because it is a function of the node
  the SEARCH is standing on and the server is not standing there. `legal_bids`
  therefore reimplements `auction_options`, and
  `wire::auction_legality::the_tree_offers_exactly_the_bids_the_engine_calls_legal`
  replays `tests/fixtures/auction.jsonl` (299 real auction nodes across both
  modes, from `tools/gen_auction_fixtures.py`) and demands the same set at every
  one. Drift here is silent in the usual way: a tree that believes one extra bid
  is legal prefers a line the room refuses, `_validated_bot_move` throws the
  answer away, and the room plays the server bot while still saying Expert.
- A second test asserts the FIXTURE still reaches the states worth covering —
  the classic opener (the only node where passing is illegal), the ceiling where
  the raise cap stops binding, spent denominations, and a skat node mid-pass-out.
  A regenerate that quietly stopped reaching them would pass the first test
  while covering nothing.

**THE PROTOCOL DOES NOT MOVE.** Expert rides in on `odd_pick_bid`, returns the
same per-option vector indexed by the server's own option list, pools across
workers by addition and hands back a move the server handed it. So the frontend
needed one line (the tier id) and a cached wasm older than the server just
prices the Hard way — the cached-bundle window degrades to Hard, not to nothing.
`wire::answer_auction` is the one body both the browser entry and `bin/bidserve`
call; the harness used to reproduce `odd_pick_bid` and with two search modes
that is one copy too many.

**TIES ARE THE COMMON CASE, AND THE INDEX IS A TERRIBLE WAY TO BREAK THEM.**
This was the first version's real bug and it is worth keeping hold of, because
the search looked like it was working. Whenever the opponent has a reply that
equalises whatever we open with, every one of our openings has the SAME minimax
value — on 25 classic deals the top four openings were exactly tied on 4 of the
first 6, and taking the earliest index opened at level 1 in **13 of 25** against
Hard's 1 of 25. That is not the search capping an auction, it is the search
having no opinion and the enumeration order answering for it. So Hard's price is
the tie-break (`tree + 1e-5 * myopic`): among lines the opponent equalises,
prefer the one that pays best if they do not. Agreement with Hard on the opening
went 4/25 → 11/25, and Expert still opens at level 1 in 9 of 25 — which is the
capping play, arrived at deliberately.
- The weight is safe rather than tuned: both halves are sums of integer payoffs,
  so a genuine tree difference is ≥1 per worker while the price is bounded by a
  few thousand, leaving the tie-break two orders of magnitude below the smallest
  real difference, pool included. It can order ties and nothing else.

**THE WORLD COUNT WAS THE LEVER (2026-08-08, the Phase-3 campaign).** Every
opponent-model idea lost or washed; more worlds won. All CRN-paired, dd-resolved,
classic, ~600 deals per row unless said:

| experiment | result |
|---|---|
| expert minimax k=3 vs hard k=3 | −0.28 ± 0.33 (n=2250) |
| expert MYOPIC-OPPONENT k=3 vs hard k=3 | **−0.62 ± 0.50** — best-responding to a model is brittle to the same leaf noise the tree already has; code kept behind the optional `opp_model` wire field, default `minimax`, for future sweeps |
| expert k=8 (one tree) vs hard k=3 | **+1.36 ± 0.48, CI [+0.43, +2.29]** |
| hard k=8 vs hard k=3 | +0.86 ± 0.49 — most of the k=8 gain is the worlds |
| expert POOLED 4×2 vs deployed hard | **+0.14 ± 0.45 — the pooling trap.** Four 2-world trees summed are NOT one 8-world tree; the tree is nonlinear in its worlds and quarter-sample trees are noise-dominated. Caught at the serving-shape gate, before shipping |
| expert ONE tree k=8 vs hard 4×1 | +0.40 ± 0.45 — hard's deployed shape was really k=4 all along (`perWorker = ceil(3/4) = 1` across four workers), which absorbed most of the +1.36 |
| **the shipped pairing**: expert one-tree k=8 vs hard pooled 4×2 (=k8) | +0.26 ± 0.42 at n=600, pre-talon — unresolved then, superseded by the row below |
| **the shipped pairing, RE-MEASURED with the talon model in the leaf (n=1600)** | **+1.19 ± 0.32, CI [+0.57, +1.81]** — the tree's marginal over worlds-matched Hard, finally clear of zero. A better leaf helped the TREE more than the pricer, which is the campaign's story closing: the tree composes leaf values through max/min chains, so leaf error hurt it most and leaf accuracy pays it most |

**What shipped from it:** `CLIENT_AI_AUCTION_WORLDS` 3 → **8** for every auction
tier (Hard's pricing is linear in the worlds, so the pooled 4×2 computes exactly
the measured single k=8: +0.86 for ~850ms a bid), and Expert's auction runs the
same k=8 as **ONE TREE IN ONE WORKER** (`solo` dispatch in `Dissonance.jsx`,
~3.4s for the first decision of a hand, ~0 after — and note the OLD deployed
Expert was four ONE-world trees summed, the deepest point of the pooling trap).
The tree's marginal over worlds-matched Hard is **+1.19 ± 0.32 (CI [+0.57,
+1.81], 1600 paired deals, both tiers with the talon model)** — the queued
resolution run, completed 2026-08-09. The same run's bidding profile (collected
in-arena, exact-play outcome labels): Expert opens BIMODALLY — 30% at level 1,
the cap line, plus a 5–6 mass, against Hard's unimodal 3–5 — declares fewer
contracts at higher levels (1409 at mean 5.67 vs Hard's 1791 at 4.79),
sacrifices slightly less (13% vs 16% of decisions), Doubles the opponent more
(25% vs 16.5% of opportunities), and its DEFENCE carries much of the edge: it
holds Hard's level-5/6 contracts to 33%/24% made while making its own at
48%/38%.

`tools/auction_arena.py`
(the harness lives with the code and drives `bin/bidserve`, i.e. the same
`wire::answer_auction` the browser calls). **Since 2026-08-08 the arena resolves
by exact double-dummy of the real deal (`resolve=dd`, the default)** — per-deal
σ 15.8 → 11.5, no greedy-play bias, mirror still exactly +0.0000. Two additions
measured USELESS for expert-vs-hard and kept for cheaper comparisons: the
conditional-on-differing mean (the tiers bid differently on **93%** of deals,
so there is nothing to condition away) and the opener-quality control variate
(β ≈ +0.05, no σ reduction). ±0.15 still needs ~5900 paired deals; the loop got
~2× faster, not 5×. CRN-paired: every deal played twice
with the tiers swapped, greedy card play and the server's talon on BOTH sides so
the auction is the only difference; the mirror `hard`-vs-`hard` reads exactly
**+0.0000**.

| classic, expert − hard | payoff/round | n (paired deals) |
|---|---|---|
| deals 0–299 | +1.71 ± 0.94 | 300 |
| deals 300–749 | −0.68 ± 0.74 | 450 |
| deals 750–2249 | −0.56 ± 0.41 | 1500 |
| **pooled** | **−0.28 ± 0.33**, 95% CI **[−0.93, +0.38]** | **2250** |

Per-deal σ is 15.8 even after pairing, so the first 300 deals on their own said
**+1.71 and I reported that** — it was a partial run. At 2250 the interval
excludes anything better than +0.38: Expert is not stronger than Hard, and there
is no longer room for it to be meaningfully so. Skat is separately unmeasured
(−3.50 ± 3.70 at n=90 resolves nothing).

**AND YET IT BIDS COMPLETELY DIFFERENTLY, which is why the wash is a ceiling and
not a bug.** `tools/auction_style.py`, self-play, 320 classic deals, identical
cards for both tiers:

| | Hard | Expert |
|---|---|---|
| opens at level 1 | 11% | **32%** |
| mean opening level | 3.63 | 3.33 |
| **passes when overtaken** | 41% | **77%** |
| **the cap line** (open ≤2, then pass) | 8% | **26%** |
| …settling at | mean 3.35 | **mean 2.95** |
| settled level | mean 4.71 | 4.22 |
| settled at 3 | 11% | **25%** |
| contract made | 50% | **63%** |

It plays the open-low-and-pass line 3.3x as often as Hard and the cap HOLDS —
67 of its 83 such auctions settle at exactly 3. And it opens lighter for real,
not because it was dealt worse: paired on the same hand it opens lower 43% of
the time (same 32%, higher 25%, mean −0.30 levels), and the gap survives
bucketing by what the hand is worth on Hard's own yardstick, widening on the
best hands (−0.21 / −0.25 / −0.33 / −0.23 / −0.47 across quintiles).

**WHERE IT GIVES THE GAIN BACK, measured.** In 10% of rounds Expert opens ≤2 and
the opponent simply PASSES — leaving it declaring at level 1 or 2 on hands Hard
priced at a mean of +8.4, which it then makes 93% of the time. A made level-1
pays `1 + (pts − 1)`, i.e. exactly the trick points, where a level-4 taking the
same tricks pays `16 + over`. **Hard does this zero times in 320 deals.**

**WHY LOOKAHEAD LOSES HERE — four mechanisms, and none of them is the search.**
1. **The modelled opponent knows our hand.** The tree runs from OUR information
   set: our cards are fixed across every sampled world, only theirs vary, so at
   every MIN node they choose knowing our exact holding. They never overbid into
   our strength and always find the punishing reply — against which aggression
   genuinely is worthless, so the search shades everything down. The 10% giveaway
   above is that assumption meeting an opponent that does not punish.
2. **Minimax best-responds to a minimaxer, and it faces Hard**, which bids
   myopically. The mismatch costs more the more plies you commit to it.
3. **The optimiser's curse compounds with depth.** The leaf is a noisy estimate
   over 3 sampled worlds; Hard takes ONE max over ~50 of them, Expert takes
   max/min repeatedly down the tree, so our branches are shaded down and theirs
   up at every level.
4. **Ties** — the acute form of (1), already found and patched; see below.

**THE TALON IS IN THE LEAF NOW (2026-08-09), and it measured exactly what the
theory said it should.** `bid::solve_world` used to build its `State` from the
deal AS DEALT — the lead modelled explicitly (~0.93), the swap not at all — so
once the swap fix made a classic swap worth **+1.500 ± 0.208**, every
declarable contract was under-priced by about that much, a one-directional
lean toward conceding. Now each determinized world samples 3 of its 6
out-cards as that world's talon (stored with the deal in `Solved.shown`, never
re-drawn — the cache fills denominations incrementally and a moving talon
would put between-denomination noise right back), and whoever declares gets
the fitted chooser's exchange applied as one hand edit before the solve, per
denomination, both sides of the pass.
- **Measured: talon model on-vs-off is +1.54 ± 0.51, CI [+0.54, +2.54]** (600
  paired deals, dd-resolved, deployed shapes) — the campaign's second result
  to exclude zero, and the size matches the swap's own value almost exactly.
- **The weights cross the wire** (`bot.swap_policy_terms` → `auction.swap` on
  every classic auction request, both tiers → `bid::SwapPolicy`), so a re-fit
  server-side moves the leaf with no Rust change. Only the FEATURE arithmetic
  lives twice, and `tests/fixtures/swap_policy.jsonl` (476 decisions, both
  branches engineered to appear) holds the two copies to one answer.
  Optional on the wire: an older wasm ignores it and prices the deal as dealt.
- **A harness lesson found on the way:** bidserve's one-slot `Solved` cache is
  evicted by cross-phase asks (a double ask keys differently), which is
  harmless in serving but broke the arena's mirror when a deal is replayed —
  the second flip re-solved fresh worlds. The arena now routes non-auction
  asks to their own process; mirrors read exactly 0.0000 again.

## The classic swap policy is FITTED, and the old one was backwards (2026-08-08)

`bot.choose_swap`'s classic branch. The old rule looked like a 3×7 search but
`gain = worth(t) − worth(h)` is separable, so it was exactly "take the highest
card shown, throw the lowest card held" — and `_RANK_VALUE` is strictly
increasing, so it could not represent any other preference. Backwards by
construction in a game where 7 of 13 tricks are penalties and low cards are how
you force them onto the opponent (the play policy's own "lead low" branch
depends on the cards it discarded). Measured: **−0.477 ± 0.226 score/round
against standing pat**, firing in 64% of rounds.

**The method, reusable for any talon question** (`tools/swaplab.py`):
1. **An oracle labels real decisions.** Drive real rounds to the swap, resolve
   every candidate exchange (3 shown × 7 held, plus pat) by an exact
   double-dummy solve of the real deal — `bidserve`'s `resolve` request. The
   oracle cheats (full information) on purpose: it is a diagnostic bound, not a
   ship gate.
2. **The dataset evaluates any policy for free** — every candidate's exact
   value is recorded, so a proposed policy's regret is a lookup, not a run.
3. **Fit interpretable, information-legal features** (rank one-hots, trumpness,
   resulting suit shape) by ridge on `value − pat`; hold out a second sweep.
4. **Ship-gate on the paired arena over the real information set**, under BOTH
   resolutions — the swap's value depends on who plays the cards afterwards
   (the old policy was +1.6 vs pat under exact play and −0.48 under greedy).

**What the oracle knows that the old rule did not:** its take-histogram is
**U-shaped** — it takes 7s (36) almost as often as Aces (52) and dips through
the middle ranks; it discards Kings when shape wants it (20 of 300); it stands
pat in 35% of decisions (old policy: 4%); and its edge concentrates at high
levels (L5 −4.9, L6 −22 policy loss), where a wrong swap flips make→set at
quadratic stakes.

**Shipped numbers** (constants and derivation documented at `_SWAP_TAKE_W` in
`bot.py`): held-out regret vs the oracle **1.92** against the old policy's
2.50; greedy-playout paired arena over 3000 deals **+1.500 ± 0.208 vs pat,
+1.976 ± 0.194 vs the old policy** — the shipped function itself, not a copy.
A fitted level-scaled stand-pat bar was tried and dropped: it cancels out of
the argmax and measured no better held-out (2.03 vs 1.92). The remaining ~1.9
regret against the oracle is deal-specific combinatorics (make/set boundary,
the Null threat) that no information-legal linear feature set sees — closing
it means solving, which the server cannot afford and the user declined to
client-serve.

**Skat's talon deliberately keeps the old rule** — no denomination, no level,
no measurement. Its own swaplab run is queued.

**THREE APPROXIMATIONS, stated because they are the difference between this and
an exact answer.**
1. **The leaf is `bid.rs`'s** — what a declarer can guarantee with both sides
   playing for POINTS. Same proxy Hard uses, same reason. **Its exact error is
   now measured (2026-08-08, after the contract-table fix): the ONLY gap is the
   adaptive Null threat.** Over 900 (deal, contract) pairs: `payoff(solve,
   duck)` equals `solve_contract` in 93.3%; every nonzero gap is POSITIVE
   (exact ≥ served, +6.5 conditional, worst +27), sits in the same ~7% of
   (deal, denom, declarer) combos at every level, and the guaranteed-duck
   subset gaps exactly 0. The mechanism: a declarer who cannot GUARANTEE
   ducking can still leverage the threat of it — the defender cannot always
   prevent the Null and hold the points down at once — and
   `max(contract, null·duck)` only credits the guarantee. One-sided toward
   UNDER-valuing declaring, i.e. the same direction as Expert's other leaks.
2. **The opponent is modelled against OUR sample**, so their branch is chosen
   knowing our hand exactly. Inherent to searching from one seat's information
   set. It is however LESS strategy-fusion than per-world minimax would be: the
   leaf sums over worlds *before* the min/max, so the opponent has to commit to
   one bid across the whole sample.
3. **Classic's Double is not modelled.** The tree stops when the auction
   settles; the defender's bet is priced on its own turn, by Hard's pricing,
   which is exactly right for a decision with no reply after it.

**Expert is deliberately identical to Hard everywhere else.** `declare`,
`kontra`, `re` and `double` have no reply after them, so a tree over them would
be one node deep — `SEARCH_AUCTION_TIERS` is a separate, smaller list than
`CLIENT_AI_TIERS` for exactly that reason.

**The browser gate drives EXPERT, not Hard, and that is strictly more coverage
for the same minutes** — Expert is Hard plus the auction on the same request and
the same wasm export. It also asserts an AUCTION answer specifically (they log
an option count; card answers log a card), because a tier whose auction search
failed and whose card search worked answers most of the game and otherwise reads
green. That is the exact shape of the Grand outage.
## The DD column — an exact double-dummy replay of every round (2026-08-08)
The match scorecard (`MatchCard`, in the side panel's "Match to N" box) carries
a fifth column, **DD**: what double dummy would have scored — the same deal,
the same contract, the card play redone from trick 1 by two players who see
all 32 cards. Hover the header for the full sentence. Beating it means the
hidden cards broke your way; trailing it is the cost of playing honestly in
the dark. (It began life as a right-click modal and was deliberately folded
into the box itself — always visible, no gesture to discover, less code.)

* **`odd_review` is the fifth wasm export**, and it is NOT `odd_pick_card` with
  a fully-specified view — that obvious implementation cannot work twice over.
  A `View` is an information set: it carries a pool the searcher SAMPLES from,
  so even a payload naming every card gets reshuffled; and `view_from_json`
  rejects it first anyway (`hidden_slots` counts covered outer piles by
  `n == 2`, not by whether the bottom is known, so a filled-in bottom breaks
  the partition check — which is *right*, for its own job). A finished round
  has no uncertainty left, so `wire.rs::deal_from_json` is a different reader:
  one exact `solve_contract`, no determinization, no seed. Same answer every
  time — which is what lets the column be labelled a FACT about the round
  rather than a bot's opinion, and the tests pin exactly that (including
  against a TT warmed on another deal, the state the export actually runs in).
* **The value is the round's PAYOFF, signed for the declarer** — rendered in
  the Score column's own vocabulary (`+` what you'd have taken, `−` what it
  would have cost). It is deliberately NOT a "DD pts" (`p/target`) figure:
  the payoff-optimal line's trick points are not unique (payoff-equal lines
  differ in points), and deriving points back out of a payoff in JS would be
  a second copy of the scoring — the drift `payoff_terms` exists to prevent.
* **The data is `engine._deal_snapshot`, taken at `_start_play`** — it must be
  snapshotted, not reconstructed: by round end `history` says which card each
  seat played but never WHERE from (hand and pile-top plays are the same
  entry), so the hand/pile split that defines the position is gone. After the
  talon swap on purpose: the review prices the hand that was PLAYED.
* **Redaction**: `g["deal"]` holds BOTH hands and never leaves the server. The
  reviewable copy is written only in `_round_summary` at bank time, when the
  round is finished and wholly public — the same reason `match` rides the wire
  at all. An abandoned round banks NO deal (nothing to review, and it is the
  one path that banks mid-play with cards still live). The test asserts on the
  SERIALISED payload, per the nested-snapshot lesson.
* **The solves run client-side in ONE on-demand worker** (`kind: "review"` in
  dissonance-worker.js, driven by `useDdReviews`), created lazily when a
  banked round has no cached answer and torn down when the batch is done —
  the column renders at every tier and in human-vs-human rooms, so it cannot
  lean on Hard's pool being armed. Results are cached for the life of the tab
  (`REVIEW_CACHE`): the deal is immutable and the solve exact, so a result
  can never go stale. The hook's dependency is the rounds COUNT, not the
  array — a fresh array arrives on every broadcast, but a banked round never
  changes.
* **At rest the snapshot is packed** (`persist._pack_deal`): the partition is
  fixed (7+7 hands, 3×2 piles each, 6 out), so the 32 card ids flatten into a
  32-char string (`_CARD_ALPHA`), and `terms` packs STRUCTURALLY — sorted keys
  joined into one string plus a values list, so persist.py still knows nothing
  about what `payoff_terms` produces. Measured after zlib: +135% verbose →
  +55-86% packed, ~46-52 bytes/round against the permutation's ~20-byte
  entropy floor. Rows written before the string encoding still load (the
  unpacker discriminates on shape); an unrecognisable deal fails OPEN to
  verbose, since an unreadable save is worse than an unshrunk one.
## Not built yet

* **Announcements beyond Sharp.** `auction_payoff_options` enumerates Sharp but
  never Open, and the multiplier is priced without modelling the extra risk.
* **The Expert tier's leaf is still a points solve, and that is where the next
  effort belongs** — not on the tree, which demonstrably reaches the lines it
  was built for. Pricing a candidate exactly needs a `solve_contract` per
  (denomination, level) per world; the tree makes the option list smaller than
  Hard's ~50, so this is closer to affordable than it was.
* **Skat's talon swap still runs the OLD take-high/give-low rule.** Classic's
  was replaced 2026-08-08 by a fitted policy (see the swap section below); the
  fit was trained and gated on classic decisions, where the contract is
  settled, and skat's talon resolves before the game is named. It needs its
  own `swaplab` run, not the classic weights on faith —
  `test_the_skat_talon_still_runs_the_old_policy` is the marker.
* **Modelling the opponent's UNCERTAINTY in the auction tree.** The single
  clearest reason Expert's lookahead does not pay is that its modelled opponent
  is handed our exact hand. Anything that makes their branch choose without it
  (a sampled-opponent-view search, or simply capping how sharply their reply is
  modelled) attacks the mechanism the measurements point at.
* A `/review`.