# The contested-node softening gate — PRE-REGISTERED, then RUN 2026-08-20

**RESULT (read once, at the declared n): +1.1938 ± 0.7555 payoff/round, CI
[−0.287, +2.674], n = 800. Spans zero — NOT ESTABLISHED, does not ship.**
Every secondary read-out is favourable and the pre-declared hold condition did
not fire: the opening is unmoved (mean 2.42 vs 2.44), concessions fall 31.3% →
21.5%, the settled mean falls 4.68 → 4.43, level-6 settlements fall 29% → 22%,
and the make rate rises 58.9% → 60.1%. **The mechanism is confirmed; the payoff
is not.** Settling it needs **n ≈ 2900** — σ measured 21.4, not the 18 budgeted
below, so the declared n bought ±0.76 rather than ±0.64. Full write-up in
`games/dissonance/CLAUDE.md`.

**EXTENSION PRE-REGISTERED (2026-08-20), before any further number exists.**
Running deals **800–2900** in four NEW windows (525 each) with their own
checkpoint files beside the first four. Fresh windows rather than widened ones
on purpose: widening the existing shards would make shard 0's new range overlap
deals shards 1–3 already recorded, and the pooled read would double-count them.
The pooler also dedupes on the deal id as a net.

* **Read ONCE at n = 2900**, target ±0.40 at the measured σ = 21.4. No interim
  totals — the n=800 read is the last number quoted until then.
* **The n=800 read stands as recorded** (+1.1938 ± 0.7555) and is NOT revised
  by the extension; the pooled 2900 is a different, larger sample that
  CONTAINS it, and only the pooled figure gets quoted afterwards.
* **The secondary read-outs are re-declared unchanged**: settled distribution,
  make rate and mean opening are reported beside the payoff, and a payoff win
  with contracts climbing the ladder is still a hold.
* **The ship bar is unchanged and is not "positive"**: the CI must exclude zero.

Per-shard reads at n=800 were +2.59 / +2.02 / +1.56 / −1.40.

---

## The pre-registration, as written before any number existed

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
