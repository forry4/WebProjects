# Dissonance vs the outside world — who has beaten a game like this, and what transfers

**Purpose.** Dissonance's own strength campaign is at a point where both halves have a
*measured* verdict and neither verdict is "keep turning the knob":

* **Card play** — `oracle` beats `pimc:8` by **+0.79 pts/round**, `pimc:24 vs pimc:8`
  reads **50.0%**, and `diag` says the residual is **strategy fusion**, not bad sampling
  (89.5% of decisions already optimal; the world-*majority* move is optimal 82.9% of the
  time, i.e. WORSE than the mean aggregator). Four levers tried, none shippable; IIMC is
  worth ~+0.067 ± 0.053 and sits at `lambda = 0`.
* **The auction** — exploitability **5.45 (Hard) / 5.70 (Expert)** against an abstraction
  floor of **1.47**, on the fixed instrument with 100% coverage. The diagnosis is
  *conditional*: Expert's opening barely varies with its hand (1.38 → 4.48 across buckets
  whose make rate runs 36% → 80%), and both tiers concede level 4 at 31–67% where the
  equilibrium concedes 0–5%.

Two of this file's own entries — the opening bias and the exact auction leaf — are nulls
recorded with the same explanation: **a marginal-shaped treatment cannot fix a conditional
defect.** So the question "what has the world built for games shaped like this, and what
did they do that we have not" is worth asking properly rather than from memory.

This is a survey, not a plan, and nothing here is measured on Dissonance. Every
recommendation ends with what it would have to beat, in the units this repo already
measures in.

---

## Part 1 — the honest landscape

**No game with Dissonance's exact shape has a superhuman AI.** Two-player, zero-sum,
imperfect-information trick-taking *with a competitive auction* is not a solved problem
anywhere. What exists is a set of adjacent games, each sharing one half of the structure,
and the useful framing is which half.

| Game | Best AI | Status | Shares with Dissonance | Does NOT share |
|---|---|---|---|---|
| **Skat** | Kermit (Buro/Long/Furtak/Sturtevant), later Edelkamp's KBPS + hope cards | **Expert / above-human on replay** | Trick-taking, an auction, contract scoring, PIMC card play, inference from bidding | 3 players (2 defenders cooperate) |
| **Bridge (declarer play)** | NooK (NukkAI, 2022); GIB, WBridge5, Jack | **Beat 8 world champions over 800 deals (83% of sets)** | 13-trick play, follow-suit, hidden hands, double-dummy solvers | Partnerships; declarer sees dummy |
| **Bridge (bidding)** | — | **NOT solved, not superhuman** | An auction where bids carry information | Bidding is *cooperative* signalling to a partner |
| **Heads-up no-limit poker** | Libratus, DeepStack (2017); Modicum (2018); ReBeL (2020) | **Superhuman** | Two-player zero-sum, a betting/bidding ladder, ranges, exploitability as the metric | No trick-taking; leaf is not solvable |
| **6-player poker** | Pluribus (2019) | **Superhuman** | Blueprint + real-time search | Multiplayer |
| **DouDizhu** | DouZero (2021), PerfectDou (2022) | **Dominates prior bots; above strong humans on ladder** | Card game, a bidding phase, hidden hands, huge action space | Card-shedding, not trick parity |
| **Mahjong** | Suphx (2019) | **10-dan on Tenhou, ~top 0.01%** | Hidden tiles, oracle available offline | Stochastic draws; 4 players |
| **Stratego** | DeepNash (2022) | **Top-3 on Gravon** | Two-player zero-sum imperfect info, huge | Deterministic-but-private board, no chance deal |
| **Scotland Yard** | Student of Games (2023) | **Strong** | Imperfect info, search + learning unified | Asymmetric roles |

**The two that matter most, and they matter for different halves:**

1. **Skat is the closest structural cousin of Dissonance's *card play*** — and it is the
   game where the exact PIMC-plus-inference stack Dissonance runs was invented, measured,
   and then improved past. Anything Kermit's lineage found is directly on-topic.
2. **Heads-up poker is the closest cousin of Dissonance's *auction*** — a two-player
   zero-sum ladder of escalating commitments, measured by exploitability, where the whole
   toolkit (abstraction, CFR, blueprint, re-solving, ranges) was built. `cfrlab` already
   imports half of it as an *instrument*. Nobody has yet made it a *player*.

**And one asymmetry in Dissonance's favour, worth stating loudly:** poker's hard problem is
that the leaf is not computable — everything from DeepStack's value net to ReBeL's PBS
machinery exists to approximate a value that cannot be solved. **Dissonance's auction leaf
IS solvable**, exactly, by `dd.rs`, and `bid::Solved` caches it per hand so a probe that
moves the standing bid rather than the cards is nearly free (measured: 16.4 s/deal at 0
probes, 13.1 at 96). Dissonance's auction is a smaller, better-conditioned problem than the
one poker solved. That is the single most encouraging fact in this document.

---

## Part 2 — what to borrow, ranked against this repo's own measurements

### 1. Make the equilibrium a PLAYER, not a measuring stick — poker's blueprint + re-solving

**Attacks:** the 5.45/5.70 vs 1.47 exploitability gap, and specifically the conditional
defect (opening does not vary with hand; level 4 conceded 31–67% vs 0–5%).

**The observation.** `cfrlab` computes a CFR+ equilibrium over the ladder abstraction and
uses it only to *score* Expert. The file's own conclusion is that the equilibrium's policy
table is "a DIRECTION, not a table to ship", because the abstraction buckets the hand and
drops denominations entirely. **That is exactly the objection poker faced and answered.**
Libratus/Pluribus do not ship the blueprint's abstract table either: they use the blueprint
as a *prior over the subgame*, then **re-solve the current subgame in the real, unabstracted
action space** at decision time. The abstraction's coarseness stops being a shipping blocker
the moment it is only a seed.

**Why it is unusually cheap here.** A poker re-solve needs an estimated leaf. A Dissonance
auction re-solve does not — every settlement is priced by `payoff_terms` over `bid::Solved`,
already cached on the hand, and `threat_value` (built, gated, correct, off behind
`DIS_EXACT_LEAF`) makes that pricing *exact* at 2.1x. The auction subtree from any node is a
few hundred states (`cfrlab`'s BR is already a DP over ~400 states running in 0.8s). **A CFR
solve of the real auction from the current node, with denominations in the tree, is plausibly
affordable inside the existing 12s watchdog** in a way the equivalent poker computation never
was.

**The specific thing it fixes that nothing else has.** An equilibrium policy is *randomized
and conditioned* — it is allowed to open 4 on a weak hand *and* on a strong one, at different
frequencies. Expert's minimax tree can only ever produce a deterministic best reply to a
modelled opponent, which is why its opening is a monotone strength signal and why the
exploitability sits where it does. **This is a class-of-algorithm difference, not a tuning
difference**, and it is the reason the two marginal-shaped treatments already tried could not
have worked.

**What it must beat:** exploitability 5.45 (Hard) / 5.70 (Expert) on the fixed
`CFR_PROBES=96` instrument, against the 1.47 floor — and then a CRN-paired auction arena at
equal time with the mirror reading exactly 0.5000, because exploitability is not a
head-to-head margin (the file is explicit that Expert is *more* exploitable than Hard while
beating it +0.957 ± 0.454).

**Reading:** [Depth-Limited Solving for Imperfect-Information Games](https://arxiv.org/pdf/1805.08195) ·
[Combining Deep RL and Search (ReBeL)](https://arxiv.org/pdf/2007.13544) ·
[DecisionHoldem: safe depth-limited solving](https://arxiv.org/pdf/2201.11580)

---

### 2. Replace `opp_temp` with multi-valued states — the principled version of the same idea

**Attacks:** the mechanism `main.py` names as Expert's whole edge and the crate names as its
whole defect — "the tree's modelled opponent is handed our exact hand."

**The observation.** `OppModel::Soft(5.0)` softens the min so the opponent is "good, not
clairvoyant", and it measured +0.957 ± 0.454. That is a real gain from a *hack*: it does not
model the opponent's uncertainty, it blurs the min. Brown/Sandholm/Amos solved the same
problem properly with **multi-valued states**: at the depth limit, the opponent may choose
among **K different continuation strategies** (generated by biasing the blueprint, or
self-generatively by best responses). The searching player then cannot assume a single
punishing reply, because the opponent has a *choice* the searcher must be robust to — and
crucially the K strategies are ones the opponent could actually be playing, rather than a
temperature.

**Why this is the natural next step and not a lateral move.** `EXPERT_OPP_TEMP`'s own note
says 5 came from a 3-point sweep and should be read as "somewhere around 5–12 rather than a
tuned optimum" — i.e. the knob is at the limit of what a knob can tell you. And the
measurement that killed the alternative (`OppModel::Myopic`, −0.62 ± 0.50) is exactly the
paper's point: best-responding to *one* opponent model is brittle; the fix is a *set* of
them. **The repo has already measured both endpoints of this axis (one model: bad; blurred
min: good) and never tried the middle, which is the published answer.**

**Cost note in this repo's terms:** the soft min costs nothing because a MIN node already
evaluates every child. K continuation strategies costs roughly K× the *aggregation*, still
over the same cached `bid::Solved` — so it is closer to free than to 2.1x.

**Reading:** [Depth-Limited Solving](https://arxiv.org/pdf/1805.08195) (Brown, Sandholm, Amos, NeurIPS 2018) — Modicum reached master-level HUNL on 700 core-hours and a 4-core CPU, which is the relevant existence proof for a browser tier.

---

### 3. αµ search for card play — the named algorithm for the exact residual `diag` found

**Attacks:** the +0.79 oracle gap, specifically the part CAMPAIGN.md calls irreducible.

**The observation.** CAMPAIGN.md's diagnosis — *"a double-dummy value prices a move for a
player who will KNOW the deal from here on. No re-weighting and no re-aggregation of those
values can fix it"* — is textbook **strategy fusion**, and it is correct that no aggregator
fixes it. But the literature's response was not "give up on search", it was **a different
search**: αµ (Cazenave & Ventos) keeps, per move, a **vector of outcomes across the possible
worlds** and compares moves by **Pareto front** rather than collapsing to a mean. Because the
vector is never collapsed until the root, the search cannot silently play a different
strategy in each world — which is the definition of the defect. It handles **non-locality**
in the same pass.

**Why it fits this codebase unusually well.**
* It is built on exactly the primitives already here: sampled worlds + an exact
  double-dummy solve. `dd.rs` is 1031 lines of solver with MTD(f) and `threat_value`; αµ
  needs no value net and no training.
* `lambda = 0` reproduces `pimc:8` byte-for-byte in the existing IIMC blend; **αµ(1) is
  likewise exactly PIMC**, so the A/B is unconfoundable by construction — the same property
  this repo insists on for every arm it trusts.
* The reported bridge result is that αµ(3) beats αµ(1) decisively (**62% ± 3.4% at 32
  cards**). Dissonance is a 32-card game.
* CAMPAIGN.md's own "untried lever with the best prior" — *a one-sided search where the
  opponent is restricted to public-information play* — is a weaker, hand-rolled cousin of
  this. **αµ is the published, optimized version of the idea already at the top of the
  untried list.**

**The one caveat worth pricing first.** αµ's cost grows with M (the number of moves it looks
ahead before collapsing), and the shipped tier is a browser at ~70ms/world at trick 1 with a
watchdog. Optimizing αµ (Pareto-front cuts, redundant-world tracking) is a second paper for a
reason. **Measure αµ(2) natively before assuming αµ(3) fits the wasm budget** — and note the
existing finding that the *cap* binds rather than the CPU, which means headroom here is a
product decision about the watchdog, not a hardware one.

**What it must beat:** +0.79 is the oracle ceiling and most of it is genuinely
unrecoverable. IIMC got +0.067 ± 0.053 and did not ship. **A ship bar of ~+0.15 with a clean
null control is the honest target**, and the null control must be αµ(1) vs `pimc:8` reading
zero.

**Reading:** [The αµ Search Algorithm for the Game of Bridge](https://arxiv.org/abs/1911.07960) ·
[Optimizing αµ](https://arxiv.org/pdf/2101.12639) ·
Frank & Basin's best-defence model / vector minimaxing is the theory both of these sit in.

---

### 4. Learn the IMPERFECT-information value — the one place "why not a net" does not hold

**Attacks:** the same strategy-fusion residual, from the evaluation side rather than the
search side.

**The observation, and it is a direct challenge to a standing conclusion.** CAMPAIGN.md
opens with *"a value net would be approximating a function we already compute perfectly, so
there is nothing for it to learn on the evaluation axis."* **That is true of the double-dummy
value and false of the value that actually governs play.** The solver computes
`V_perfect(deal, position)`. What a PIMC search needs at its leaf is
`V_imperfect(infoset)` — the value achievable by a player who will *not* learn the deal — and
that function is **not computable by any solver**. The gap between them *is* strategy fusion.
So there is a well-defined, non-trivial, learnable target sitting exactly where the file says
nothing is learnable.

**Three programmes converged on this and all three are directly usable:**
* **Bias-corrected PIMC** (Solinas, Rebstock, Buro — *Improving Search with Supervised
  Learning in Trick-Based Card Games*): train a model to correct the double-dummy leaf toward
  what real play achieves, in Skat, the closest cousin.
* **PerfectDou's perfect-information distillation**: perfect-training / imperfect-execution —
  the **critic** sees everything, the **actor** never does, so the global information shapes
  training without leaking at inference.
* **Suphx's oracle guiding**: the actor starts with oracle features and they are annealed
  away. PerfectDou's paper notes the distinction — Suphx must *drop* the oracle before
  inference, PerfectDou feeds it only to the critic and distils. The critic route is cleaner
  and is what Dissonance would want.

**The labels are already affordable here, which is what makes this concrete rather than
aspirational.** Every ingredient exists: `dd.rs` produces the oracle value for free, the
paired arenas produce real-play outcomes, and `priorlab` already measures per-decision regret
against a double-dummy oracle *paid for only when two variants disagree*. **And the repo has
already written down the measurement this needs and never run it** — the noise-sigma entry:
*"Sigma is measurable — compare double-dummy `pts` against what the shipped PIMC search
actually achieves on the same deal and contract — and it has not been measured."* That
comparison, done per position instead of in aggregate, **is the training set for this net.**
Running it settles the sigma question and produces the labels in one pass, which makes it the
cheapest item on this list to start.

**Reading:** [Improving Search with Supervised Learning in Trick-Based Card Games](https://arxiv.org/pdf/1903.09604) ·
[PerfectDou](https://arxiv.org/pdf/2203.16406) · Suphx (oracle guiding).

---

### 5. Hope cards and paranoia search — the Null cliff is exactly their use case

**Attacks:** a specific, local, cheap piece of the card-play gap.

**The observation.** Dissonance's payoff has a **cliff at one bit of state**: a declarer who
has won no +2 trick scores a flat 20 (`escored`, which the file notes is deliberately carried
in `State` because it is not derivable from `pts`). The Hard tier handles this by searching
the payoff rather than the points, and it works — 6–7 Nulls per 40 rounds against the points
searcher's 0.

**But mean-over-worlds aggregation is at its worst near a cliff.** Averaging payoff across
worlds is the right thing for maximizing EV *of a fixed strategy*; it is precisely wrong when
the searcher plays for the contract in world A and ducks for Null in world B, because the
mean credits a plan no single strategy executes. **The cliff amplifies strategy fusion
rather than being independent of it** — which connects two facts this repo has recorded
separately.

Edelkamp's Skat work is the literature's answer to exactly this shape:
* **Knowledge-based paranoia search (KBPS)** — a worst-case forced-win analysis run after a
  few tricks, producing a *prioritized* card choice rather than a mean.
* **Hope cards** — cards that excel *not in all worlds, but in the set of still-winnable
  ones*. For Dissonance, "still-winnable" has two disjoint meanings (make the contract, or
  reach the Null escape), and a hope-card analysis over each set is a far better-posed
  question than one mean over both.

**Why it is attractive as a first build:** it is bounded, needs no training, no new wire
field, and `threat_value` already computes the "can I force *pts ≥ x* OR no scoring trick"
question — **the machinery for the two-sets analysis is committed and gated.** The reported
Skat result is above-human replay scores in the extended Seeger system.

**Reading:** [Knowledge-Based Paranoia Search in Trick-Taking](https://arxiv.org/abs/2104.05423) ·
[Improving Computer Play in Skat with Hope Cards](https://link.springer.com/chapter/10.1007/978-3-031-34017-8_12)

---

### 6. Inference from bidding — Kermit found it pays; this repo measured a wash. Reconcile before re-spending.

**Status: do NOT re-open on enthusiasm. Read this first.**

Kermit's headline contribution was *"improving state evaluations using game data produced by
human players and using these state evaluations to perform inference on the unobserved hands
of opposing players"* — a table-based procedure taking opponent **bids** into account to infer
state likelihood. That is, to a first approximation, `bid::BidPrior`.

**Dissonance built it, and closed the thread deliberately.** The bias is real and large (real
holding at the 0.765 percentile of the uniform resample, 0.704 against Expert, still 0.617 at
trick 11); correcting it genuinely centres the sample (0.704 → 0.521); and it converts to
**+0.161 ± 0.623 at the Double** and **+0.617 ± 2.522 in card play** — *"A MEASURED BIAS DID
NOT IMPLY A MEASURED GAIN, by two independent instruments."* Opponent-consistency resampling
at two temperatures and a Vote aggregator all washed (−0.003, −0.052, −0.073, SE ~0.14).

**The literature explains why the same idea pays differently in two similar games, and this
is the genuinely useful import.** Long, Sturtevant, Buro & Bowling's *Understanding the
Success of PIMC* gives three properties that predict whether PIMC is near-optimal and
therefore how much inference can buy:

* **leaf correlation** — P(all sibling terminal nodes share a payoff). Low correlation means
  a player can still affect the payoff late.
* **bias** — how far the game favours one player.
* **disambiguation factor** — how fast an information set shrinks with depth. **Low is good
  for PIMC; a mid-range value is the worst case.**

**Dissonance has never measured its own three numbers, and it should before spending another
hour on inference in either direction.** The repo already holds the raw material: `diag`'s
per-decision decomposition, `decayprobe`'s belief-gap-over-tricks curve (the 0.617-at-trick-11
figure is a disambiguation measurement in all but name), and the 89.5%-optimal figure. **This
is the cheapest high-value item in this document**: three numbers that turn "inference washed
here but worked in Skat" from a puzzle into a prediction, and that would also say in advance
whether αµ (item 3) is likely to pay — because the same properties govern how much strategy
fusion is on the table.

**A finding this repo already owns and should keep credit for:** CAMPAIGN.md's
`infinite_temperature_is_exactly_restricted_choice` — that `temp → ∞` does not reduce to
uniform sampling, because the likelihood keeps `-sum(ln n_legal)`, so a world where the
opponent was *forced* explains their play better than one where they chose from five. That is
**the principle of restricted choice**, derived independently and asserted exactly in a test.
It is the same reasoning Kermit's inference tables encode.

**Reading:** [Understanding the Success of PIMC](https://webdocs.cs.ualberta.ca/~nathanst/papers/pimc.pdf) ·
[Improving State Evaluation, Inference, and Search in Trick-Based Card Games](https://webdocs.cs.ualberta.ca/~nathanst/papers/skat.pdf) ·
[Learning Policies from Human Data for Skat](https://www.researchgate.net/publication/336088752_Learning_Policies_from_Human_Data_for_Skat)

---

## Part 3 — what NOT to borrow, and why

* **A value net for card play, in the ordinary sense.** CAMPAIGN.md is right: `dd.rs` solves
  the deal exactly, so there is nothing to learn about the *perfect-information* value. Item
  4 above is a different function and the distinction is the whole point — do not let it
  become a licence for a conventional AlphaZero-shaped net.
* **DeepNash / R-NaD (Stratego).** Model-free equilibrium learning without any search, built
  because Stratego admits no useful solver and no tractable abstraction. Dissonance has an
  exact solver and a tiny auction. This is the right tool for the opposite situation.
* **Bridge *bidding* systems.** Bridge bidding is cooperative signalling to a partner, and
  is not superhuman anyway. Dissonance's auction is purely adversarial — the poker framing
  (item 1) is correct and the bridge framing is actively misleading.
* **Big self-play RL over the whole game (DouZero-style Deep Monte Carlo).** DouZero works
  because DouDizhu has no usable solver and enormous action spaces. Here it would spend
  months rediscovering a function `dd.rs` already computes exactly.
* **Anything already measured and washed** — opponent-consistency resampling, Vote/Quantile
  aggregators, the IIMC blend at higher lambda, `OppModel::Myopic`, the opening bias, the
  exact auction leaf as an exploitability treatment. All are in CAMPAIGN.md or the Dissonance
  `CLAUDE.md` with numbers.

---

## Part 4 — RESULTS (all five items built and measured, 2026-08-19)

Everything below was implemented and run. Two of the five paid, three did not, and
one of the nulls is un-measurable rather than negative — the distinction matters.

| # | Item | Outcome |
|---|---|---|
| 1 | **Three PIMC properties** | **Measured.** Leaf correlation **0.713** near the leaves (favours PIMC), bias **0.605**, disambiguation **0.505** — mid-range, the paper's stated worst case. Two of three axes put this game where PIMC is *not* near-optimal, so fusion is structurally present. Also: the information set is now COUNTED exactly, and hard-constraint inference is worth **≤0.6 bits** against sets 6–27 bits wide. |
| 2 | **Sigma** | **Measured, and it replicates** — 1.586 / 1.590. But the convolution model **overstates** the ladder loosening by ~2.4× (predicted ~19%, measured 7.7%). Bonus: the opening lead is **+0.992 double-dummy but +0.673 in real play**, a third smaller than the number that justified `declarer leads`. |
| 3 | **Multi-valued states** | **PAID. Exploitability 9.14 → 7.06, a 23% cut**, split-half bands not overlapping. The first thing this campaign has measured that moves exploitability at all. Costs ~2.5× the soft min. |
| 4 | **αµ** | **Built, correct, and it LOSES** — about −0.22 pts/round against `pimc:8` at ~10× the compute. αµ(1) is a byte-identical null control, so the arm is clean. |
| 5 | **Auction re-solving** | **Blueprint half built and measured at 1.46 — but that number is largely CIRCULAR** (the blueprint plays the abstraction's own equilibrium and the best responder lives in that same abstraction). Needs a head-to-head arena to mean anything. |
| 6 | **Prior's exploitability cost** (from the 2019 PI paper) | **Built; un-measurable at this n.** −0.033 ± 1.785 — an error bar fifty times the effect. Not a null, a non-measurement. |

**The one that matters:** item 3. Both endpoints of the opponent-model axis had
already been measured here (one hand-blind model: −0.62; a blurred clairvoyant
min: +0.957) and nobody had tried the middle, which is the published answer.

**Two methodological findings worth more than some of the results:**

* **The arena's null is not zero at n≈200.** Two provably identical algorithms
  read **+0.147 ± 0.077**, because the harness seeds A and B differently and the
  seat swap cancels deal luck but not seed luck. Running that control is what
  flipped the αµ verdict from "no effect" to "a loss". Any arena number near
  ±0.15 at that sample size needs its own identity control on the same deals.
* **Two offline harnesses were scoring on a price list that died on 2026-08-16**
  (`cmatch.rs`, `abench.rs`: `N²+10 / N+10 / over:0` against the shipped
  `N²+4 / 2N+2 / over:1`). The existing parity gate covers terms→payoff, never
  *which terms the game charges*, so a bin inventing its own was unguarded by
  construction.

**Still not done:** a CRN-paired auction arena for items 3 and 5 — exploitability
is not a head-to-head margin, and this repo's own ledger has Expert measuring
*more* exploitable than Hard while beating it. Neither arm should ship on the
table above alone.

## Sources

* [The αµ Search Algorithm for the Game of Bridge](https://arxiv.org/abs/1911.07960) — Cazenave & Ventos
* [Optimizing αµ](https://arxiv.org/pdf/2101.12639) — Cazenave, Legras, Ventos
* [Depth-Limited Solving for Imperfect-Information Games](https://arxiv.org/pdf/1805.08195) — Brown, Sandholm, Amos (Modicum)
* [Combining Deep Reinforcement Learning and Search for Imperfect-Information Games](https://arxiv.org/pdf/2007.13544) — Brown et al. (ReBeL)
* [DecisionHoldem: Safe Depth-Limited Solving With Diverse Opponents](https://arxiv.org/pdf/2201.11580)
* [Understanding the Success of Perfect Information Monte Carlo Sampling in Game Tree Search](https://webdocs.cs.ualberta.ca/~nathanst/papers/pimc.pdf) — Long, Sturtevant, Buro, Bowling
* [Improving State Evaluation, Inference, and Search in Trick-Based Card Games](https://webdocs.cs.ualberta.ca/~nathanst/papers/skat.pdf) — Buro, Long, Furtak, Sturtevant (Kermit)
* [Improving Search with Supervised Learning in Trick-Based Card Games](https://arxiv.org/pdf/1903.09604) — Solinas, Rebstock, Buro
* [Learning Policies from Human Data for Skat](https://www.researchgate.net/publication/336088752_Learning_Policies_from_Human_Data_for_Skat) — Rebstock, Solinas, Buro
* [Knowledge-Based Paranoia Search in Trick-Taking](https://arxiv.org/abs/2104.05423) — Edelkamp
* [Improving Computer Play in Skat with Hope Cards](https://link.springer.com/chapter/10.1007/978-3-031-34017-8_12) — Edelkamp
* [PerfectDou: Dominating DouDizhu with Perfect Information Distillation](https://arxiv.org/pdf/2203.16406) — Guan et al.
* [AI beats eight world champions at bridge (NooK / NukkAI, 2022)](https://www.cbc.ca/radio/asithappens/as-it-happens-the-wednesday-edition-1.6402751/an-artificial-intelligence-just-beat-8-world-champions-at-bridge-1.6402861)
