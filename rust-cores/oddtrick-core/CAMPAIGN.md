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
