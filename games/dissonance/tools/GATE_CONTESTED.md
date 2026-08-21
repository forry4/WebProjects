# The contested-node softening gate — PRE-REGISTERED 2026-08-20

**Written BEFORE any number exists.** This package's ledger records four
separate occasions where a running total said the opposite of the completed
sample (+1.71 at n=300 → −0.28 at n=2250; −2.57 at n=196 → −0.68 at n=1550;
a `DOUBLE_MARGIN` peak at n=320 that vanished on the next 320). So the sample
size, the arms and the read-out are fixed here in advance and the result is
read once, at the end.

## The arm

`expertsgt` (soft, gated, talon) vs `expertst` (soft, talon) — the shipped
Expert. The only difference is `main.opp_temp_for(g)`: at nodes where a PASS is
legal the modelled opponent is softened at `DIS_OPP_TEMP_CONTESTED` instead of
`EXPERT_OPP_TEMP`. The opening — the one node that cannot pass — keeps its
fitted 5.

```
PYTHONPATH=. DIS_OPP_TEMP=5 DIS_OPP_TEMP_CONTESTED=12 \
ARENA_CKPT=<ckpt> python3 games/dissonance/tools/auction_arena.py \
    classic 8 800 expertsgt expertst <lo> <hi> dd
```

**`DIS_OPP_TEMP=5` is not optional** — the arena defaults it to 4 while
`main.EXPERT_OPP_TEMP` is 5, so without it the CONTROL is not the shipped tier
and the race is against a bot nobody plays. (`opp_temp_for` reads
`EXPERT_OPP_TEMP` directly, so the treated arm is unaffected; the mismatch would
land entirely on the control.)

## Verified before running

| check | result |
|---|---|
| unarmed `expertsgt` vs `expertst` | **exactly +0.0000** — one change wide |
| armed mirror `expertsgt` vs `expertsgt` | **exactly +0.0000** |
| armed, non-vacuity | 13/14 auctions differ |

## Pre-declared

* **n = 800 paired deals.** Per-deal σ ≈ 18 even CRN-paired and dd-resolved, so
  this buys **±0.64**. For scale, the shipped `opp_temp` gain is +0.957 ± 0.454
  and the tree's whole edge over Hard is +1.19 ± 0.32.
* **Read ONCE, at n = 800.** No interim totals. If it lands inside ±0.64 of
  zero the honest answer is "not established at this n", and the note says what
  n would settle it rather than the run being extended until it looks decisive.
* **THE PAYOFF IS NOT THE ONLY READ-OUT.** The settled-level distribution and
  the make rate come out of the same shards and must be reported beside it.
  This package records Experts already bidding each other past the making point
  (level 6 settling 28%, 64% of those set), so a correction that wins on points
  while pushing contracts up the ladder is buying strength the game's shape says
  it should not keep. A win on payoff with the settled distribution climbing is
  a **hold**, not a ship.

## Why 12

`tools/shadeprobe.py` (400 deals, 973 decisions, both pricers on the same
worlds): the shade on the option actually being chosen crosses zero at temp
≈ 13.5, and 12 lands the tree's concession rate on 29.0% — the price list's own
rate to the decimal. 12 is also inside the range the original 2/5/12 sweep
covered, so it is not an extrapolation.

**It is a candidate, not an optimum.** Zeroing the shade is not self-evidently
right: the price list concedes 29.0% and the CFR equilibrium concedes 0–5%, so
both pricers may be conceding far too much and matching the price list would
only match a bidder the tree already beats. If 12 measures positive, 15 and 20
are the next arms — and each needs its own pre-registration, not a sweep read
off this run.
