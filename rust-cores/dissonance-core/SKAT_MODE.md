# Skat mode — a second auction over the same card play

A separate game mode alongside the shipped auction. Same 32-card deck, same
piles, same parity scoring, same talon — a different way to arrive at a
contract. The shipped v2 auction stays exactly as it is.

## The one idea worth stealing

In the shipped auction, **level N is both the price and the task**: naming
your bid tells the opponent what you intend to play. Skat separates them. You
bid a **number**; only after winning do you declare the game that satisfies
it. The number is a price, and it cannot be read backwards into a
denomination, because many games clear the same number.

Everything below follows from that one move.

## Game values

    value = base × level        (level 1–12, exactly the shipped scale)

| denomination | base |
|---|---|
| diamonds | 2 |
| hearts | 2 |
| spades | 3 |
| clubs | 3 |
| no-trump | 5 |

**Priced by COLOUR since 2026-08-07.** This section originally specified four
tiers (D2 H3 S4 C5 NT6), mirroring real Skat's 9/10/11/12 and deliberately
inverting the shipped mode's C < D < H < S. That shipped and was too much
manufactured asymmetry: a hand equally playable in hearts and spades was priced
a whole rung apart for a reason no player could name, and the cheap suits
swallowed the auction.

**Null is a fixed 20**, sitting mid-ladder the way Skat's 23 does (between
spades-at-6 = 18 and diamonds-at-11 = 22 it has plenty of neighbours).

The base values are pure convention — the suits are measured symmetric
(settled-denomination evenness 0.943; the clubs spike in early data was a
solver tie-break artifact). That is exactly why assigning them works: it
manufactures an asymmetry the game does not otherwise have. Your *ability* in
a denomination is real and varies by hand; only its *price* is convention. Two
tiers keep that argument where it is load-bearing and hand the within-colour
choice back to the cards.

**The re-pricing costs no rung anyone bids.** Every multiple of 6 at or below 36
is already a multiple of 2 or 3, so dropping base 6 removes exactly 42, 54, 66
and 72. The ladder is identical through 40, the ceiling falls 72 → 60, and the
rung count goes 36 → 28. The playable range does not move at all.

**Collisions are the point, and colour pricing makes them ambiguous rather than
merely numerous.** 12 = ♦6 = ♥6 = ♠4 = ♣4. That is four declarations, the same
count the old table gave — but the old four (♦6 ♥4 ♠3 NT2) sat at four
*distinct* levels, so a bid plus any tell about the level pinned the
denomination exactly. These pair up, and the pairs are the two suits of a
colour: the same information still leaves a two-way choice. A bid of 12 does not
say which game is coming. A hand playable in two denominations can bid higher
*safely* than an equally strong hand playable in one — flexibility becomes a
resource with a price, a decision the shipped auction cannot express.

## The auction

Ascending numeric, alternating, opener speaks first and **may pass** (both
pass = hand thrown in, redeal). Each bid names any legal value higher than
the standing one. Whoever holds the last bid declares.

Legal values are the products {base × level}, and the ladder is DERIVED from
the bases rather than typed out — this paragraph originally enumerated it by
hand, claimed "every integer 2–10", and counted 43 rungs, and all of that was
wrong. The real ladder under the colour-priced table is **28 rungs from 2 to
60**:

    2 3 4 5 6 8 9 10 12 14 15 16 18 20 21 22 24 25 27 30 33 35 36 40 45 50 55 60

Density is good through the playable range — 7 is the only gap below ten,
because it is a multiple of no base — and thins exactly where hands get rare,
which is the right shape for an auction ladder.

Why opener-may-pass is safe HERE and was not in the shipped mode: the shipped
floor cluster exists because the opener is *forced* to name a contract. In
this mode passing is not an escape into a degenerate bid — it is a genuine
"you take it" that hands the opponent declarer's advantages (talon + lead) at
their price. The measured open-pass pathology (floor → 0% but auctions
hollow) came from pass being strictly better than a forced bad contract;
here the pass has a real cost attached.

## After the auction: the declarer escalates against themselves

This is where the mode's interest lives — see "two players" below.

1. **Talon or Hand.** Take the 3 shown cards and swap one (the shipped
   mechanic, unchanged), or **decline to look** and play Hand.
2. **Declare** denomination and level such that `base × level ≥ your bid`
   (Null: only if you bid ≤ 20). Declaring the *minimum* satisfying level is
   normal; declaring higher is voluntary, for the multipliers below.
3. **Optional announcements**, before trick 1, each compounding:

| announcement | condition | multiplier |
|---|---|---|
| (base game) | score ≥ level | ×1 |
| **Hand** | played without the talon | ×2 |
| **Sharp** | score ≥ level + 3 | +1 to the multiplier |
| **Open** | Sharp, with your hand face up from trick 1 | +1 again |

Multipliers stack Skat-style by addition: Hand+Sharp = ×3, Hand+Sharp+Open =
×4. Sharp/Open without Hand = ×2/×3.

**Scoring.** Make everything you announced → **declared value × multiplier**.
Miss anything → defender scores **declared value × multiplier**, plus the
shipped shortfall term (4 × points short) so deep failures still hurt more
than near misses. Null: flat 20, ×2 Hand, ×3 Hand+Open (no Sharp — there is
no margin to sharpen).

Why multipliers rather than flat bonuses: the shipped campaign measured flat
bonuses distorting the bottom of the ladder (a flat +1 RAISED the floor
cluster — proportionally biggest on the smallest contracts). A multiplier
scales with what is at stake, so it prices confidence identically at every
level. That negative result is the reason this table has no flat term.

Why announcements at all: they let a strong hand keep bidding *after* the
auction ends. Sandbagging (winning cheap at 6, declaring ♦3) is legal but
pays 6 — the same hand announcing Hand+Sharp pays 18 from the same auction.
The declarer's real bid is therefore made against themselves, after the
opponent is out of the loop — which is exactly the pressure a 2-player
auction otherwise lacks.

**Overbid loses automatically.** If no declarable game reaches your bid — you
took the talon expecting it to fix a denomination and it didn't — you lose
your bid at once, unplayed (defender scores it). Skat's sharpest rule,
transplanted intact; it is what makes a numeric auction dangerous rather than
a formality. The talon peek is 3 known cards against 3 unknown, so "will the
talon save me" is a computable but genuinely uncertain gamble.

**Kontra.** After the declaration (and announcements) but before trick 1, the
defender may say **Kontra**: double everything, whichever way it falls. The
declarer may **Re** it back to ×4 of the announced total. This gives the
defender a real decision at exactly the moment they finally learn what game
they are defending — the reply move a two-player auction otherwise denies
them.

## Making it interesting for TWO players — the design problem, stated

Skat's auction is a three-way contest with an outside option: two bidders
escalate, and the third player profits from whichever of them stretched too
far. Overbidding is punished by a party outside the fight. With two players
that police force does not exist — a plain ascending ladder is "who wants it
more," and the real 2-player Skat variants (Offiziersskat, Bauernskat) drop
the auction entirely rather than play that thin game.

This mode compensates in four places, all after the auction:

1. **The declaration is hidden information.** The number can't be read
   backwards; the defender learns the game only at declaration. The shipped
   mode leaks the denomination with every bid — here the whole auction
   happens behind it. (This also costs the shipped mode's denomination-denial
   game — measured nearly inert: 94% of auctions name ≤ 2 denominations —
   and its public hand-reads, which is the real trade.)
2. **The declarer bids against themselves** via Hand/Sharp/Open, so the
   escalation contest survives the auction's end — relocated from
   bidder-vs-bidder to declarer-vs-their-own-hand.
3. **The defender gets the last word** via Kontra, priced at the moment of
   maximum information asymmetry.
4. **Overbid-loses makes every bid falsifiable.** The opponent can push you
   one rung past your hand *knowing* you might not be able to declare there —
   the two-player analogue of Skat's third-party punishment.

## Implementation alongside the current game

The card play, talon, redaction and room machinery are untouched; only the
auction phase machine changes. Concretely:

* **Room flag**, not a new game: `mode: "classic" | "skat"` chosen in the
  create modal (a `CmSeg` row), carried in the game dict, rendered as a badge
  in the lobby card. One `dissonance_games` table, one route, one lobby.
* **engine.py** gains a parallel phase machine for the skat mode:
  `auction2` state (standing value, log) → `declare` phase (talon/Hand,
  denomination+level, announcements) → the existing `swap`-equivalent folds
  into `declare` → play → `_finish_skat` scoring. The shipped
  `auction`/`swap` path is untouched; `apply_move` dispatches on the mode.
  Shared: `legal_moves`, `apply_play`, piles, redaction (plus one new secret:
  the declaration is public, the *bid ladder* needs no redaction at all).
* **Values table** lives in `engine.py` and is served via `/catalog`
  (`skat_values`, `skat_bases`) so the client never hardcodes it.
* **Frontend**: one new middle-panel branch per phase (value ladder buttons →
  declare card → announcement toggles → Kontra prompt), reusing the bid-grid
  CSS wholesale. The result panel learns `value × multiplier` arithmetic.
* **Rust `skatlab`**: the existing `HandEval` matrix (per-world, per-denom,
  per-declarer exact solves) is already everything a value-ladder solver
  needs — `AuctionSolver` gets a sibling that maximises over
  {value, declaration, announcements} instead of {level, denom}. The
  measurement instrument stays bidlab's: settled-value distribution, overbid
  frequency, announcement rates, Kontra accuracy.
* **Persistence**: same compaction; the skat auction log is a short int list.
  No schema change (the game dict is a JSON blob).

Ship order: measure in `skatlab` first (below), then engine.py + tests
(parity gate unaffected — card play identical), then frontend.

## Training the AI for it

The good news: **card play transfers whole.** Same deck, same tricks, same
solver — the PIMC bot and the future WASM Hard tier need zero retraining for
this mode. What is new is decision-making around the contract, and none of it
needs a net:

* **Bidding**: `eval_hand` already yields the exact per-denomination result
  matrix under k sampled worlds. A hand's *bid ceiling* is
  `max over (denom, level) of {base × level : makeable in ≥ q of worlds}` —
  the auction reduces to marching up the ladder while the standing bid is
  below your ceiling, exactly the arithmetic `AuctionSolver` does today.
  q (the confidence quantile) is the strength dial: Easy bids at q=0.9
  (timid), Hard at the solver's exact indifference point.
* **Announcements**: Sharp/Open/Hand are the same computation with a stricter
  make condition (`score ≥ level+3`, no talon) — three more columns in
  `HandEval`, each an exact solve. No search innovation required.
* **Kontra**: defender's posterior that the declaration is makeable, from
  *their* world sample — again the existing machinery pointed backwards.
* **Where self-play matters**: tuning q, the announcement thresholds, and the
  Kontra trigger against each other. That is a ~4-parameter sweep in
  `skatlab` self-play, the same CRN-paired arena discipline as everything
  else in this crate — not a training run. The known trap to watch:
  bot-vs-bot gates hide absolute weakness when both sides share a blind spot
  (the Duel lesson), so gate the tuned bidder against the *shipped-mode*
  bidder on identical deals too, not only against itself.
* **The one caveat**: the lab auction is swap-unaware (22× cheaper); its
  levels read low and make rates high in one known direction. For skat mode
  the talon decision is bigger (Hand ×2 hangs on it), so `skatlab` should
  spend the 22× and be talon-aware from day one — the auction tree here is
  tiny (one ladder, not a level×denom grid), which pays for it.

## Open questions, to be measured not guessed

1. **Announcement rates.** Hand should be a real temptation (~15–30% of
   contracts?), not a default and not decoration. The ×2 is a guess until
   `skatlab` runs.
2. **Overbid frequency.** Too high → the mode is a trap; ~0 → the rule is
   decoration. The talon-gamble overbid (bid on 2-of-3 talon outs) is the
   interesting case; measure how often optimal play attempts it.
3. **Is 20 right for Null?** Its shipped-mode analysis says availability
   ~7%/deal and always one-sided; at value 20 it must clear diamonds-through-
   spades hands without becoming the default weak-hand bid.
4. **Kontra threshold.** If optimal Kontra is near-never or near-always the
   multiplier is wrong; target somewhere near "doubles ~10–20% of contracts,
   correctly more often than not."
5. **Does the mode beat the shipped auction on the distribution?** Same
   instrument as everything else: settled-contract spread, and specifically
   whether the auction produces *information games* (trap bids, denomination
   bluffs) the shipped mode cannot. If it only reproduces the same
   distribution with more machinery, it does not ship.
