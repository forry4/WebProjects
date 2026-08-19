# Strength campaign log

Baseline: `pimc:8` — 8 uniform determinizations, each solved exactly, mean
value wins. Ceiling: `oracle` (cheats, solves the real deal) beats it by
**+0.79 pts/round**.

## Why not a net

Duel needed a learned value leaf because it could not search to the end. This
game can: `dd.rs` solves a full 13-trick deal exactly. A value net would be
approximating a function we already compute perfectly, so there is nothing for
it to learn on the evaluation axis.

The two fixes that actually broke Duel's plateau are already banked here and
were checked, not assumed:

* **Coherent determinization.** Duel's per-sim determinization injected the
  flat targets that killed every AZ attempt. Our PIMC samples one world and
  solves it to the end — coherent by construction, never per-sim.
* **Minimax, not max-max.** Duel's `select()` modelled the opponent as
  cooperating. `dd.rs` is explicit max/min, and `solver_matches_brute_force`
  asserts it against a reference search.

So the Duel playbook points away from more search and towards the hidden
information — which is where the measurements pointed too.

## The measurement that set the direction

| result | reading |
|---|---|
| `pimc:24 vs pimc:8` = **50.0%** | sampling is saturated; more worlds buy nothing |
| `oracle vs pimc:8` = **+0.79** | all remaining headroom is hidden-information handling |

`diag` then decomposed the gap per decision (60 deals, 1242 real choices):

* **89.5%** of decisions are already exactly optimal.
* Sampled worlds **disagree** on the best move **53.6%** of the time — so
  world *selection* is not dead by unanimity.
* The world-majority move is truly optimal **82.9%** of the time, i.e. WORSE
  than the mean aggregator's 89.5%.
* Regret is roughly flat across tricks 1-7 and collapses after trick 8.

That combination is the signature of **strategy fusion**, not of bad sampling:
a double-dummy value prices a move for a player who will KNOW the deal from
here on. No re-weighting and no re-aggregation of those values can fix it.

## Tried and washed (140 deals / 280 rounds each, all vs `pimc:8`)

| lever | edge | verdict |
|---|---|---|
| opponent-consistency resampling, 600 particles, temp=inf | -0.003 | wash |
| ditto, temp=1.0 (policy-shaped inference) | -0.052 | wash |
| `Vote` aggregator instead of `Mean` | -0.073 | wash |

Standard error at this sample size is ~0.14, so all three are indistinguishable
from zero. The inference machinery is kept — it is correct, tested, and cheap —
but on this game it does not pay. Consistent with `diag`: PIMC's errors are not
errors about WHICH world.

### A real finding buried in the inference work

`temp -> infinity` does **not** reduce to uniform sampling. The likelihood
keeps `-sum(ln n_legal)` over the opponent's past decisions, so a world in
which they were FORCED explains their play better than one in which they chose
from five. That is the **principle of restricted choice**, and it falls out of
the replay for free. It is asserted exactly in
`infinite_temperature_is_exactly_restricted_choice`.

## The lever that moved: IIMC

Evaluate a root move by PLAYING THE REST OUT with policies that never see the
hidden cards, instead of by solving. That prices what a double-dummy value
structurally cannot. Playouts cost microseconds against a ~20 ms solve, so the
term is nearly free and blends with the existing one:

```
score = (1 - lambda) * mean double-dummy value + lambda * mean playout value
```

Both terms are in differential units, so they blend without normalisation, and
`lambda = 0` reproduces `pimc:8` exactly — the A/B cannot be confounded.

First sweep (140 deals each):

| lambda | edge |
|---|---|
| 0.15 | +0.108 |
| 0.35 | +0.091 |
| 0.60 | -0.014 |

Run out properly at 803 deals / 1606 rounds, with a null control:

| run | rounds | edge |
|---|---|---|
| NULL: `pimc:8` vs `pimc:8`, different RNG seeds | 1606 | -0.014 |
| IIMC lambda=0.15 vs `pimc:8` | 1606 | +0.059 |
| (earlier, independent seeds) | 286 | +0.108 |
| **pooled** | **1892** | **+0.067 +/- 0.053** |

**Verdict: not established.** ~1.3 SE. It is directionally positive in two
independent runs and the null control is clean, so it is not nothing — but it
is ~8% of the 0.79 oracle gap and does not clear a ship bar. `lambda` is left
at 0 by default.

## Where that leaves card-play strength

Four levers tried, none shippable. The honest reading is that most of the
0.79 oracle gap is IRREDUCIBLE: it is the value of actually knowing 13 hidden
cards, which no amount of inference recovers. The reducible part is strategy
fusion, IIMC is the right tool for it, and it is worth about +0.07.

If this is picked up again, the untried lever with the best prior is a
one-sided search: evaluate a move with OUR side searching and the OPPONENT
restricted to public-information play. Standard PIMC is pessimistic in a
specific way (its opponent sees our hand); that variant is optimistic in the
opposite way, and bracketing the two should beat either.

## ALPHA-MU: BUILT, CORRECT, AND IT MEASURES WORSE THAN PIMC (2026-08-19)

**Verdict first: `AlphaMuBot` is committed and gated OFF. At depth 2 it is about
0.22 pts/round WORSE than `pimc:8` for roughly ten times the compute.** This is
the fifth entry in this campaign where a mechanism that is real and correctly
implemented did not convert; it is recorded in full because the reasoning that
motivated it still looks right and someone will want to try it again.

**WHAT WAS BUILT.** Cazenave & Ventos's answer to strategy fusion is not a better
aggregator but a different SEARCH: commit to ONE card across every world you
cannot tell apart, iterated `m` of your own decisions deep, and only then let the
double-dummy solver take over. `m = 1` is plain PIMC. Faithful here in that
mechanism; NOT faithful in keeping Pareto fronts over boolean outcomes, since our
shipped objective is a real-valued payoff where Pareto dominance is too weak to
prune on — so this is alpha-mu's commitment structure with PIMC's aggregator.

**THE NULL CONTROL IS AN IDENTITY, NOT A RESEMBLANCE.** `alpha_mu_at_depth_one_is_exactly_pimc`
plays a whole game card-for-card against `PimcBot` across 6 deals x k in {1,4,8}
x both seats. Beside it `alpha_mu_at_depth_two_actually_diverges_from_pimc` is
the positive control, so the identity is a clean arm rather than an inert knob.

**THE GROUPING IS THE ALGORITHM.** After our card the opponent replies, and who
leads next — and what they lead — depends on hidden cards, so it differs across
worlds; and our OWN two outer pile bottoms are hidden from us too, so the card
exposed under a pile we play differs per world and is something we would
actually see. Committing one card across worlds we can TELL APART is not a
stronger search, it is an illegal one: the first cut keyed only on the
opponent's cards and hit `panic!("illegal card ...")` on the second decision.
Worlds are partitioned by everything observable before each of our decisions.

**THE MEASUREMENT, and the control is the interesting half:**

| arm (bot A vs bot B, same 102 deals, 204 paired rounds) | edge to A |
|---|---|
| `amu:1:8` vs `pimc:8` — same algorithm, different seed | **+0.147 ± 0.077** |
| `amu:2:8` vs `pimc:8` — identical opponent, identical deals | **−0.074 ± 0.078** |
| **difference (the only valid reading)** | **≈ −0.22** |

The two runs share their deals AND their opponent, differing only in bot A, so
the difference is paired and its true error bar is below the 0.11 an independent
combination would give.

**THE ARENA'S NULL IS NOT ZERO AT THIS SAMPLE SIZE, AND ITS DOCSTRING SAYS IT
MUST BE.** `arena.rs` states "two identical deterministic bots must therefore
score exactly 2.500 — that mirror reading is the harness's own correctness
check". That holds only for bots seeded IDENTICALLY, and the arena deliberately
seeds A with `0x5EED` and B with `0xB0B`. Same algorithm, different stream, and
at 204 rounds the pedestal is **+0.147 ± 0.077** — the seat swap cancels deal
luck but nothing cancels a seed that happens to sample better worlds on this
particular deal set. It averages out (this campaign's own 1606-round null read
−0.014) but it does NOT vanish at the sample sizes small arms get run at. **Read
no arena number near ±0.15 at n≈200 without running its own identity control on
the same deals.** That is why the row above exists and it is the reason the
alpha-mu verdict flipped from "no effect" to "a loss".

**WHY IT PLAUSIBLY LOSES, which is the part worth carrying.** PIMC is already
pessimistic in a specific way this file documents: its modelled opponent sees
our hand. Alpha-mu constrains US to one card across the group while leaving THEM
free to answer world by world, so it tightens our side of an asymmetry that was
already against us. Removing our own fusion has to pay for that, and at depth 2
it does not. The published algorithm keeps a Pareto front and takes the root
choice off it rather than collapsing to a mean, which may be exactly what pays
for the constraint; a mean aggregator throws that away. **If this is reopened,
implement the Pareto front over a BINARISED objective (made / set, which this
game has) before touching the depth knob again.**

**And the shape of the game predicted this**, which is worth noting for
calibration: leaf correlation measures 0.713 near the leaves (below), and high
leaf correlation is the regime the PIMC-properties paper says PIMC already
handles well. The recoverable slice was always small.

## THE THREE PIMC PROPERTIES, MEASURED (2026-08-19)

`bin/pimcprops`, 400 deals, PimcBot k=8, classic parity, 32 cards. Long,
Sturtevant, Buro & Bowling (AAAI 2010) parameterise a synthetic tree by three
numbers and show which combinations leave PIMC near-optimal. This game had never
been placed on those axes, and two of the three put it in the region where PIMC
is NOT near-optimal — which is the first evidence independent of `diag` that the
residual above is structural rather than a sampling artefact.

| property | measured | reading |
|---|---|---|
| **leaf correlation** | **0.713** at trick 12 (deepest trick with choices, n=631), rising 0.257 -> 0.713 from trick 1; 0.365 pooled over 8346 choice nodes | HIGH near the leaves, which FAVOURS PIMC |
| **bias** | seat 0 ahead on **60.5%** of deals under exact double-dummy play, no ties (n=400); distance from even **0.210** | near-even, i.e. mid-range — does not help |
| **disambiguation** | **0.505** mean per ply over the round, **0.568** over the first 13 plies | MID-RANGE, which the paper names as the WORST CASE for PIMC |

**What each is here, because none of the three has a canonical estimator on a
real game** — the paper's own note is that a real game is "a cloud of parameters"
rather than a point, and its three knobs are knobs on a synthetic binary tree:

* **leaf correlation** — at a reachable node where the mover has >= 2 legal
  cards, solve the TRUE world for every one of them and ask whether they all come
  back equal. The per-trick curve is the useful object; "near a leaf" is the part
  of their model that carries the weight. Mean sibling SPREAD falls with it, 2.58
  points at trick 1 to 0.87 at trick 12.
* **bias** — off the exact root solve, so it is a property of the GAME rather
  than of whoever is playing it. The 60.5% is the opening lead, already measured
  at +0.93 pts and here in a second currency.
* **disambiguation** — `View::infoset_log10` COUNTS the information set exactly
  (see below), and df = 1 - |I_t+1| / |I_t| per ply. Same construction as their
  model, where a set shrinks by a factor of (1 - df) per level; the mapping onto
  their synthetic tree is qualitative and should not be read as a calibrated
  number.

**THE COUNT IS EXACT, AND THAT IS THE PART TO TRUST.** `determinize` is uniform
over consistent deals and its constraint structure is simple enough to count in
closed form rather than sample: the opponent's hand is any `nh`-subset of the
cards no void and no must-head ceiling excludes, and every remaining pool card
falls into a labelled covered-pile slot or the unordered out-pile, so
`|I| = C(n_allowed, nh) * (nslots + n_out)! / n_out!`. A fresh deal is exactly
**98,017,920** worlds. Both are tested — `a_fresh_deal_has_exactly_98_017_920_consistent_worlds`
pins the arithmetic against a hand computation, and
`counts_exactly_what_determinize_can_draw` runs the SAMPLER 20,000 times at
positions where the set is small enough to enumerate and demands it reach exactly
that many distinct deals and no more. Verified non-vacuous: a one-off in the
falling factorial fails both.

**AND THE COUNT DECOMPOSES, which is the number this campaign never had.** The
same count with the void and must-head constraints DROPPED is what a searcher
faces if it never reads the play record, so the gap between the two curves is
what follow-suit inference is worth, in bits:

| ply | log10 \|I\| | inference gap | share of remaining uncertainty |
|---|---|---|---|
| 0 | 7.99 (26.5 bits) | 0.00 bits | 0% — nothing played yet |
| 4 | 6.35 (21.1 bits) | 0.19 bits | 0.9% |
| 12 | 3.48 (11.5 bits) | 0.50 bits | 4.3% |
| 18 | 1.75 (5.8 bits) | 0.58 bits | 9.9% |
| 25 | 0.14 (0.5 bits) | 0.19 bits | — |

**Hard-constraint inference never removes more than about six tenths of a bit**,
against sets 6 to 27 bits wide, and its SHARE only becomes non-trivial late,
by which point the set is collapsing on its own at ~50% a ply. Scope this
precisely before citing it: it measures the channel `determinize` actually
enforces (voids + must-head ceilings). The opponent-consistency resampling in
`infer.rs` is a softer, separate channel and so is `bid::BidPrior`'s auction
evidence — neither is in this number.

**WHAT IT PREDICTS, and it is genuinely two-sided.** High leaf correlation is
the strongest PIMC-favourable signal there is and we have it, which is consistent
with `diag`'s 89.5%-already-optimal. But a mid-range disambiguation factor is the
paper's stated worst case, and 0.505 is as mid-range as the axis gets. So the
shape of the game says strategy fusion is STRUCTURALLY PRESENT rather than
absent — it supports spending one bounded experiment on a fusion-aware search
(alpha-mu), and it does not move the ceiling, which is still the 0.79 oracle gap
of which most is the value of simply knowing 13 cards.

# Bidding

`bidlab` runs full auctions and resolves the contract by an exact double-dummy
solve rather than by playing the cards — so a difference between two bidding
strategies is a difference in BIDDING, with zero card-play noise. Reported
"made" rates are therefore ceilings.

The auction is solved, not hand-coded. Once a player has an estimate of both
sides' results in every denomination (`eval_hand`: sample worlds, solve all ten
denomination x declarer cells in each), the rest of the auction is pure
arithmetic over that matrix, so `AuctionSolver` minimaxes it exactly. Bidding
strategies are read OFF the solution instead of being guessed.

## What emerged on its own

* **Sandbagging is real.** The solver opens in its best denomination only
  41-55% of the time, keeping the best one in reserve for the overtake —
  exactly the line predicted before any of this was built.
* **Openings are BIMODAL**, ~40% at level 1 and a second cluster at 5, with
  levels 2 and 4 rare. That is "open low to trap, or open high to claim",
  emerging with no such rule in the code. The level-1 cluster is the weak
  hands: it is not trying to score 1, it is trying to make the OPPONENT
  declare, because the defender gets the +0.93 opening lead plus the set bonus.
* Mean settled contract level is ~3.1, against a double-dummy best-contract
  mean of 3.49. The auction lands just under what is makeable.

## The knobs behave exactly as designed

| change | sacrifices | opened in best denom | made |
|---|---|---|---|
| baseline (short=1) | 5.0% | 41% | 81.2% |
| short=2 | 3.1% | 51% | 83.8% |
| short=2, slope=1 | 4.5% | 46% | 81.8% |
| short=2, slope=2 | 5.7% | 43% | 72.7% |

The shortfall penalty is the sacrifice knob, as intended: doubling it nearly
halves sacrifice bidding. The reward slope is the stretch knob: tripling the
top-end reward drops the made rate from 84% to 73%.

## The one thing no knob moved

**Level-1 openings sit at 38-43% under every configuration tested**, including
slope=2 which triples the reward for high contracts. That is because the
level-1 opening is not a scoring decision at all — it is a decision to be the
DEFENDER. Nothing on the make-reward curve can change it, because it is not
paid on the make side. The levers that would are: a floor on the opening bid,
trimming the defender's edge, or reducing what setting a low contract pays.

Whether that is a fault is a design call, not a measurement. The bimodality is
evidence FOR the auction being informative — weak hands open 1, strong hands
open 5 — so 40% at the floor may simply be the true fraction of hands that
prefer to defend.

## The 2x2: doubling x who leads trick 1

All `solve` vs `solve`, make N^2 / set linear / short 4, 90 deals = 180
contracts per cell. Cells are +/-3-5%.

| | dbl off, def leads | dbl off, DECL leads | DBL on, def leads | **DBL on, DECL leads** |
|---|---|---|---|---|
| mean contract level | 3.33 | 3.73 | 3.06 | **3.57** |
| settled at 6+ | 8.9% | 25.5% | 3.3% | **15.5%** |
| highest settled | 6 | 8 | 6 | **7** |
| overtook | 23.3% | 33.9% | 13.9% | **25.0%** |
| sacrificed | 6.7% | 11.1% | 4.4% | **4.4%** |
| declarer made | 68.9% | 63.3% | 75.6% | **75.6%** |
| opened in best denom | 61.1% | 36.7% | 65.6% | **46.7%** |
| contracts doubled | - | - | 36.7% | **33.3%** |

They do partly cancel, but NOT symmetrically, and the combination is the best
cell on every axis except raw height:

* **Doubling does not merely shorten the auction, it disciplines it.** On its
  own it cuts overtakes 40% and drops the auction a full half-level. Combined
  with declarer-leads it keeps sacrifices at 4.4% (against 11.1% for
  declarer-leads alone) while the contracts stay high.
* **Declarer-leads is the strongest single lever on contract height** - bigger
  than the N^2 make curve. It is the only thing that ever put levels 7 and 8 on
  the board.
* Together: 15.5% of contracts at level 6+, a contested auction (25%
  overtakes), the best make rate of any cell (75.6%), and sandbagging alive at
  46.7%.

### The hole nothing fixed

**Settled level 3 is nearly extinct in every cell** (2.2-11.1%), and level 4 is
thin whenever the declarer leads. Auctions resolve either fast and low (1-2,
40-49% of contracts) or high after a fight (5-6). The mechanism is structural:
openings are bimodal at 1 and 5, an opening at 1 gets overtaken to 2 and stops
there, and an opening at 5 stays at 5 or goes to 6. Levels 3-4 can only arise
from openings at 3-4, which the solver rarely makes. The +1 ladder plus bimodal
openings leaves a dead band in the middle of the range.

## Synthesis: what actually moves the contract distribution

Every configuration tried in this session - both parities, linear and N^2 on
each of the make and set curves, flat bonuses, min bid 0, doubling on/off,
either lead rule, four jump settings - lands on **about five well-used contract
levels**. maxraise=1 gives 1,2,6,7,8; maxraise=2 gives 1,3,6,7,8; maxraise=3
gives 1,4,6,7,8. Always five.

That is not a scoring failure. It is the spread of hand strength. Widening the
pool (the parity flip, +5 -> +8) RELABELS the levels rather than adding any;
changing the curves moves where they sit; capping jumps translates one spike.
None of it creates more distinguishable contracts, because there are not more
distinguishable hands.

The distribution is three-modal in every capped setting:

1. a **floor pile** (11-17% at level 1),
2. a **punishment-landing pile** of exactly 22.0%, sitting at level
   `1 + max_raise` - it TRANSLATES with the cap, it never spreads,
3. an **honest-value cluster** at 6-9 (~53%, well spread).

### The one lever that ever moved the floor pile

Unlimited jump overtakes: 42.7% -> 2.7%. Nothing else came close, because the
floor bid was never about the value of a level-1 contract - it is about CAPPING
what the opponent can reach. Levers that change how valuable contracts are
(N^2, declarer-leads, doubling, flat bonus, parity flip, min bid 0) cannot
touch it.

The price of unlimited jumps is the maneuvering game: sandbagging collapses
(opened in best denomination 49% -> 70-81%), overtakes fall to ~15%, sacrifices
to ~2%. The auction becomes a sealed-bid value declaration.

**Capped jumps do not escape the trade-off.** They preserve the maneuvering
(overtaking PEAKS at max_raise=2, 29.0%, above both the plain ladder's 22.0%
and unlimited's 15.5%) but leave the floor at 36-41%.

### Untried ideas that could change the SHAPE rather than move it

* **Over-penalty for exceeding the contract.** Attacks the trap from the
  scoring side: opening 1 with a hand worth 7 becomes expensive. Caveat - a
  declarer can usually throttle by throwing tricks, so it only bites when the
  DEFENDER can force overtricks, which is an empirical question. Expensive to
  build: the payoff stops being linear in the point differential, so
  accumulated points must enter the transposition key and the "future
  differential" trick in `dd.rs` dies (expect 3-5x slower solves).
* **Divide-and-choose**: the opener names a contract, the responder chooses
  which side plays it. Eliminates the floor pile by construction and forces
  centred, honest bids - at the cost of eliminating sandbagging too.

### Dead ends, measured

* **Round limits.** 54-68% of auctions are a single bid and ~97% are two or
  fewer, so any cap above 2 never binds.
* **Flat +1 for making.** Raised the floor cluster (43.3% -> 46.4%) rather than
  lowering it: a flat bonus is proportionally far larger on a made 1 (1 -> 2)
  than on a made 5 (5 -> 6).
* **Allowing a bid of 0.** Shifted the floor down one rung and slightly
  deepened it (43.3% at 1 -> 48% across 0 and 1). Levels 3-7 were byte
  identical.

---

# Hidden information: how much is there, and can it be bought

The complaint this answers: in a two-player trick-taker you end up knowing the
opponent's whole hand. Skat's uncertainty is DISTRIBUTIONAL - the card exists in
a known place-set, you just don't know which of two opponents holds it. Two
players can only have EXISTENTIAL uncertainty: is that card dead, or is it
theirs. So the entire permanent hidden-information budget of this game is the
number of cards out of play, and everything else (the opponent's hand, the
covered pile bottoms) resolves as the round runs.

`arena oracle pimc:8` measures it directly. Both players always hold 13, so
widening the deck changes ONLY the out-of-play count: features `rank8`/`rank9`/
`rank10` give 6/10/14 out against the default's 2, and 13 tricks, the +5 pool
and every scoring number survive untouched.

**The control is the load-bearing part.** A wider deck also thins each suit,
which makes voids rarer and ruffing scarcer - a different effect on the game
entirely. `--out-public all` deals the out-cards FACE UP: same deck, same suit
lengths, hidden information removed. So `gap(hidden) - gap(public)` is what the
out-pile's secrecy is worth, and `gap(public)` is what the hand and covered
pile bottoms are worth - which must stay FLAT across widths, because those
holdings never change size. It did (mean 0.703, spread 0.096 against SEs of
~0.043), so the sweep measures information and not density.

| deck | out | hidden | public (control) | secrecy | marginal/card |
|---|---|---|---|---|---|
| 28 | 2 | 0.8493 | 0.7153 | 0.134 | - |
| 32 | 6 | 1.1411 | 0.7464 | 0.395 | +0.065 |
| 36 | 10 | 1.1603 | 0.6507 | 0.510 | +0.029 |
| 40 | 14 | 1.2344 | 0.6986 | 0.536 | +0.007 |

209 deals x 2 seatings per cell. Baseline reproduces the logged 0.79 oracle gap.

**It saturates.** Marginal value per added dead card falls tenfold across the
range. Do not read the first two points as a line - they are consistent with a
line AND with the early part of a curve that bends at 8, and the bend is real
and sits between 6 and 10.

**Conclusion: 32 cards / 6 out.** Banks 0.395 of the 0.536 available at any
width (74%) for the smallest change to the deck, and lifts total hidden
information 34%. Going wider buys a third more secrecy for a 25% bigger deck
and materially thinner suits.

The honest limit: the out-pile can never dominate. Even at 14 out it is worth
0.536 against the hand-and-piles component's ~0.70. More dead cards is a real
lever but a bounded one, and it does not on its own stop the back half of a
round from being solvable. That needs INFERENTIAL hidden information - a
private symmetric discard, where the uncertainty is about what the opponent
CHOSE to throw rather than about the shuffle - which is untried.

## NULL is dead here, and the reachable version is not at zero

Skat's escape hatch for a hand with no power. It cannot be built on the point
scale: the pool is constant-sum, so "I score >= N" and "my opponent scores
<= 5-N" are the same bid and there is no inverse contract to be had. Like
Skat's, it has to be a trick-COUNT condition, which needs its own search
(`Dd::null_makeable`) because `Contract` pays off on `pts` - and taking no
tricks scores zero, but so does taking one even trick and two odd ones.

**Measured base rate: 0.7% of hands** (`nullprobe`, 300 deals, declarer
leading; 0.3% defending). It is not a contract, it is a lottery ticket. The
cause is structural and will not move: 13 cards, mandatory follow-suit, and no
discard. Skat's Null works because you play ten cards and can bury two stoppers
in the Skat first. There is no equivalent here.

Do not re-run this. The general form is what is live:

| hold declarer to | declarer leads | defender leads |
|---|---|---|
| 0 tricks | 0.7% | 0.3% |
| 2 tricks | 7.7% | 3.8% |
| 3 tricks | 17.2% | 9.5% |
| 4 tricks | 28.8% | 18.8% |
| 5 tricks | 43.3% | 28.5% |

`Dd::min_tricks`. The two lead conventions come out exact mirrors
(`declarer_leads[k] == defender_leads[13-k]`), which is the search's own
coherence check. "At most 3" (~17%) or "at most 4" (~29%) is the frequency band
a non-dominant escape bid would sit in. Unbuilt - it is a design decision, not
a measurement.

## Ranked denominations: the claim failed, the effect did not

C<D<H<S<NT, so an overtake need only OUTRANK the standing bid rather than
out-level it (`--rank`). Skat's price-is-not-the-task idea without Skat's
arithmetic.

**Harness bug found first, and it would have handed this arm a free win.**
`best_open` scanned denominations in index order and kept the first maximum, so
every tie landed on clubs - 96% of floor openings, a property of the loop
rather than of the game. `AuctionSolver::tie_salt` rotates the scan order per
deal. Note the deeper trap: a denomination histogram can be flattened for free
by breaking ties differently, which changes how the floor LOOKS without giving
the opener one new decision. `floor_spread` (best-worst solver value across the
floor bids) is the metric that cannot be gamed that way, and both are reported.

Claim was "give level 1 five rungs". **Refuted**: clubs still takes 85.1% of
floor openings (from 88.0%), and the floor cluster grew 37.5% -> 43.5%. There is
a good reason - opening at the floor means you are weak and WANT to be
overtaken, so you name the cheapest denomination to invite it. `1C` is not one
of five rungs, it is a single bid meaning "I have nothing".

But the contract distribution moved, and in the way nothing else had:

| settled level | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| shipped | 9.5 | 7.5 | 22.5 | **2.5** | 26.0 | 21.5 | 10.0 |
| ranked | 14.0 | 5.5 | 27.5 | **13.5** | 21.5 | 13.5 | 4.0 |

The level-4 hole fills 2.5% -> 13.5% (~6 SE). Every earlier fix made the spike
TRANSLATE rather than spread; this is the first that spread it. Supporting:
opened-in-BEST-denomination 45% -> 31% (openers name where it is CHEAP, not
where they are strong - the price/task decoupling working), overtakes 30% ->
36%, auctions of 3+ bids 7% -> 13%, NT usage 6.5% -> 11.5%, floor_spread 0.453
-> 0.770.

200 deals. The level-4 result is solid; the floor-cluster worsening is ~1.7 SE
and may be noise. All of it on the 28-card deck - re-confirm on 32 before
locking, since deck width changes hand strength and hand strength is what the
auction prices.

## The v2 config, measured then shipped (2026-08-07)

Shipped to prod as engine v2: 32 cards / 6 out, ranked denominations, Null at
rung 6 (12 make / 10 set), declarer shown 3 out-cards and may swap one with a
HAND card. The default Rust build is now this deck; `rank7` rebuilds the
original 28-card game.

Four arms at 120 deals, k=3, on 32/6/shown-3 (settled-level evenness in
brackets): baseline [0.864], +rungs [0.897], +null [0.866], both [0.905].

* **The deck + swap did real work alone**: vs the 28-card baseline, settled
  level 2 went 7.5% -> 11.7% and level 4 went 2.5% -> 6.7% before any auction
  change.
* **Rungs replicated** on the wider deck: level-4 hole 6.7% -> 14.2%, level-5
  spike 25.0% -> 20.8%, overtakes 30% -> 43%, best-denom openings 36% -> 27%,
  floor_spread 0.478 -> 0.633.
* **Null at its designed rung 3 was a NO-OP** — zero settled contracts in 240
  rounds, because maxraise 2 lets the opponent take it away with a 4 or 5.
  Even paying 500 it was opened and never survived. The rung, not the price,
  was the problem.

Null rung sweep (120 deals, rungs on):

| config | contracts | made | share |
|---|---|---|---|
| rung 6, pays 12 | 18 | 33% | 7.5% |
| rung 8, pays 12 | 4 | 0% | 1.7% |
| rung 6, pays 25 | 6 | 33% | 2.5% |

Rung 6 / 12 / 10 shipped. Note the 7.5% share lands on the measured 7.0%
per-deal availability, and note what the per-row dump showed Null actually IS:
**all 18 arrived by OVERTAKE, none by opening, at net -2.67/contract for the
declarer** — a defensive SACRIFICE against a strong standing contract, not the
weak-hand opening it was designed as. The weak-hand problem stays solved by
rungs. Raising the price suppresses the bid (a 33% gamble is only worth taking
while losing is cheap), so 12/10 is likely near the ceiling of what Null can
pay without vanishing.

**Standing caveat on every auction number in this section**: the lab auction
is swap-UNAWARE while resolution is swap-exact (all 21 candidate swaps played
out, best kept — 22x cheaper than a swap-aware auction). Declarers therefore
systematically under-bid: levels read LOW, make rates read HIGH, in that one
direction only.

Per-deal JSONL dumps for every arm are in the session scratchpad
(`rows_*.jsonl`: seed, opening bid, settled contract, declarer, made, scores,
swap cards) — new questions can be answered from the rows without re-running.

## Skat mode: a second auction, and the instrument for it (2026-08-07)

`src/skat.rs` + `src/bin/skatlab.rs`. The shipped auction makes level N both
the price and the task, so naming your bid announces your plan. Skat mode
splits them: you bid a bare NUMBER (`value = base x level`, bases D2 H3 S4 C5
NT6 — inverting the classic ranking on purpose — Null flat 20), and only after
winning do you declare the game that clears it. Many games clear the same
number, so the ladder cannot be read backwards into a denomination.

`HandEval` is reused verbatim. The structural fact that made `AuctionSolver`
exact holds unchanged — once you have both sides' results in every
denomination, the whole auction is arithmetic over that matrix — so `SkatSolver`
is a sibling, not a second evaluator. It maximises over `{value, declaration,
announcements}` instead of `{level, denomination}`.

### What this instrument can and cannot see

* **Open is not modelled, and cannot be.** It buys +1 to the multiplier for
  playing face up, and a double-dummy defence already has perfect information —
  so the reveal costs exactly nothing here and a solver would take it on every
  contract. That would be a property of the instrument, not of the game. The
  multiplier therefore runs 1..3 in the lab against 1..4 as shipped. Pricing
  Open needs a defence that plays from an information set, which this is not.
* **Hand and Sharp ARE measurable.** Hand costs the talon (double-dummy resolves
  it exactly); Sharp raises the point target, which is arithmetic over the same
  matrix.
* **Overbid cannot fire at all.** The level is the declarer's free 1..12 choice
  and NT x 12 is the ladder's top rung, so every legal bid is declarable.
  Skat's sharpest rule has nothing to bite on here; the live decision in its
  place is declaring ABOVE what the number forced, which the lab reports.

### Two methodology facts that cost real runs to learn

* **`eval_hand` was evaluating a contract nobody is paid on.** Its Null column
  called `Dd::null_makeable` — take no trick AT ALL, measured 0.7% of hands —
  while both `bidlab` and the shipped engine resolve `null_no_even_makeable`,
  win no +2 trick (~7%). So the bidder believed Null was makeable in ~0.7% of
  worlds and then made it 33% of the time. **Every Null conclusion in the rung
  sweep above was drawn under that mismatch**, and "all 18 arrived by OVERTAKE,
  none by opening" is exactly the signature of a bidder that thinks the contract
  never makes. Fixed; the rung sweep wants re-running before its conclusions are
  trusted.
* **Resolving the DECLARATION exactly is clairvoyance, not optimal play.**
  `bidlab` resolves the swap exactly, which is a small cheat over 22 options.
  Extending that to the declaration is not: a declarer who already knows the
  double-dummy outcome simply picks the highest-paying game it happens to make.
  Measured, that pinned the make rate at 95.7% and Kontra accuracy at 6.2% —
  numbers that look like findings and are artefacts. `skatlab` therefore chooses
  under BELIEFS (a talon-aware world sample: after looking, the three shown
  cards are known out of play) and resolves exactly only afterwards.
* **Maximising a sample mean over ~120 declarations is a winner's curse.**
  5 denominations x 12 levels x Sharp is a lot of candidates for a small world
  sample, and the max of many noisy means is badly optimistic. At the mean with
  k=3 the solver over-declared by +1.8 levels on 83% of contracts and the
  declarer netted -26 per contract. `SkatCfg::q` scores a declaration by its
  q-quantile world instead — the confidence dial the design note anticipated,
  here doing real work rather than acting as a strength knob.

### The instrument is NOT converged, and the mean belief gap does not show it

First numbers, 16 deals, q=0.0, the conservative end of the confidence dial:

| worlds | made | declarer net | mean belief gap |
|---|---|---|---|
| k=4, tk=3 | 46.2% | **-20.46** | +0.23 |
| k=10, tk=6 | 75.0% | **+24.00** | -0.25 |

Doubling the world sample flips the sign of the headline metric. **Nothing that
moves with k is a measurement**, and every skat number below k=10 should be
read as direction-finding only.

**The mean belief gap is the wrong diagnostic, and it was built specifically to
answer this question.** It is near zero in BOTH arms (+0.23 / -0.25 points on a
12-point scale) while the outcome swings 44 points, so it flatly failed to
discriminate. The reason is selection: the declaration is chosen by a max over
~120 candidates (5 denominations x 12 levels x Sharp), so it is picked ON the
sampling noise. The mean residual can sit at zero while the choice is badly
wrong — what matters is the SPREAD of the gap, not its centre. A mean-residual
check cannot see a winner's-curse failure by construction, which is worth
remembering before building the next one.

It also produced a wrong conclusion on the way through, recorded so it is not
re-derived: from the k=4 arm alone the make/miss arithmetic looks damning.
Break-even is `p = (S + 4d) / (2S + 4d)`, above 50% for EVERY stake, because
the stake is symmetric while the shortfall is a one-sided tax with no
convexity paying for it — where classic mode has N^2 on the make. At S~40,
d~3 that is p = 56.5% against a measured 46.2%, which reproduces the -20
almost exactly and reads as a scoring bug in the mode. It is not one: at k=10
the declarer makes 75% against the same 56.5% bar and nets +24. The arithmetic
is right and the conclusion drawn from it was wrong.

**What survives both sampling regimes** (and so is worth carrying forward):

* **Hand is announced 92-94% of the time**, unmoved by k. The x2 is worth more
  than the talon on nearly every hand, so the talon — a mechanic the classic
  campaign measured as doing real work — gets skipped almost always. This is
  the strongest measured signal against the mode as specified.
* **Kontra fires 75-85%** against the design note's 10-20% target, and its
  accuracy FELL to 33% at k=10. Too frequent, and at better sampling also
  wrong.

**Structural, needing no measurement at all:**

* **Overbid-loses cannot fire.** The level is a free 1..12 choice and NT x 12
  is the top rung, so every legal bid is declarable. The design note calls this
  "Skat's sharpest rule" and rests its fourth two-player compensation on it;
  there is no mechanism behind it here.
* **The cheap rungs constrain nothing.** Diamonds at base 2 clears rungs 2..10
  at levels 1..5, so a bid of 2 commits the winner to scoring one point. Price
  density is not task density.

Withdrawn pending re-measurement at converged k: the rung-2 floor cluster
(25% of contracts), Null at 0%, Sharp at 0-7.7%. All were single-arm at k=4.

### The Kontra rate was a polarity bug, not a property of the mode

Flagged by an obvious inconsistency that the numbers had been carrying in plain
sight: at k=10 the defender doubled **75%** of contracts while **75% of them
made**, and Kontra "accuracy" came out at 33% — worse than never doubling, and
worse than chance. A defender cannot be that wrong by accident.

Cause: `SkatSolver::kontra` called `decl_value`, which reads `cfg.q`, and every
run so far was at `--q 0.0`. So the defender judged the contract at the
DECLARER'S WORST sampled world, where the declarer usually fails.

`q` is a SELF-confidence dial. Low means "assume my contract goes badly", which
makes the declarer cautious — and pointed at the defender, who is valuing the
OPPONENT's contract, the identical number means "assume their contract goes
badly", i.e. maximal aggression. One number, opposite meanings per seat. The
earlier q sweep was monotone in exactly the direction the bug predicts and was
read as noise:

| q (shared) | doubled | correct |
|---|---|---|
| 0.0 | 84.6% | 54.5% |
| 0.5 | 53.8% | 85.7% |
| 1.0 | 64.3% | 88.9% |

Split into `SkatCfg::kontra_q`, defaulting to the median. A Kontra doubles a
SYMMETRIC bet, so the risk-neutral rule is just "double iff the contract is
worth less than nothing to the declarer" — the middle quantile — and anything
away from it is a risk preference that should be set on purpose.

**"Kontra fires 75-85%" is therefore withdrawn**, which leaves exactly ONE
measured finding standing across sampling regimes (Hand at 92-94%) and two
structural ones (overbid-loses has no mechanism; the cheap rungs constrain
nothing). Three of the four measured problems reported from this lab have now
turned out to be instrument defects. The pattern is consistent enough to be
worth stating as a rule: **on this instrument, assume a striking number is a
bug until a second, differently-shaped run agrees with it.**

One real bias remains in the defender's read, and it is faithful rather than a
defect: their `HandEval` predates the talon, so they are valuing a hand the
declarer may since have improved. They know THAT a swap happened and nothing
else, which is exactly the shipped game — but it does bias Kontra upward, and
the residual rate should be read with that in mind.
