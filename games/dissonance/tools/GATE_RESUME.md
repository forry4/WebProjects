# The diverse-vs-Expert auction gate — how to resume it

**Status at time of writing (2026-08-20): RUNNING, INCOMPLETE.** The
exploitability result that motivates it (`Diverse` 9.14 → 7.06, −23%) is in
`games/dissonance/CLAUDE.md`; this is the head-to-head gate it needs before
anything ships, because exploitability and strength are different quantities in
this game and this repo's own ledger proves it (Expert is *more* exploitable
than Hard while beating it +0.957 ± 0.454).

## The run

```
PYTHONPATH=. DIS_OPP_TEMP=5 DIS_OPP_SPREAD=6 DIS_OPP_N=3 \
ARENA_CKPT=<ckpt path> python3 games/dissonance/tools/auction_arena.py \
    classic 8 1550 expertdt expertst <lo> <hi> dd
```

* `expertdt` = diverse + talon, `expertst` = soft + talon. **Verified one change
  wide** — the suffix parser gives `expertdt` diverse-without-soft and
  `expertst` soft-without-diverse, and both get the talon model the server
  actually ships.
* **`DIS_OPP_TEMP=5` is not optional.** The arena defaults it to 4 while
  `main.EXPERT_OPP_TEMP` is 5, so without it the soft arm is not the shipped
  Expert and the race is against a tier nobody plays.
* `ARENA_CKPT` makes it resumable: re-running with the same path skips deals
  already recorded, so a larger `N` EXTENDS the sample rather than restarting
  it. The checkpoints are a few tens of KB at n=1550.
* Shard with `<lo> <hi>`; each shard needs its OWN checkpoint file, and each
  prints a `SHARD {...}` line to pool afterwards.

## Run the mirror first

`hard hard` must read **exactly +0.0000**. It is the first thing to run after
touching `auction_arena.py`, and it did read exactly that after the `d` arm was
added.

## What it costs, measured

**~5.5 deals/min on an uncontended 4-core box at 4 shards**, so n=1550 is roughly
**4–5 hours** there. (An earlier figure of 1.5/min in this file was measured
while another job had the cores and is what produced a 17-hour estimate; the
lesson is the ordinary one — time a harness on a quiet box or not at all.)
Per-deal sigma is **≈18**, which is why:

| n | error bar |
|---|---|
| 300 | ±1.04 |
| 900 | ±0.60 |
| 1550 | ±0.46 |

That ±0.46 at 1550 is exactly the precision the shipped `opp_temp` result was
published at, which is the point of choosing it — like for like. Note even then
an `opp_temp`-sized effect (+0.957) lands at only ~2 SE. **This measurement is
expensive to make decisive; budget for it rather than expecting a quick answer.**

**AND THE HARNESS'S VARIANCE REDUCTION IS INERT HERE, which is why those error
bars cannot be shrunk (found 2026-08-20).** The quality control variate — the
one the docstring says "cannot move the mean's expectation, only shrink its
error bar" — is captured under `tier_of[seat] == "hard"`, i.e. **only when one
arm is literally Hard.** In any expert-vs-expert race `qual` stays empty, every
recorded `q` is 0.0, and the adjustment silently does nothing. That covers this
gate and it also covers the shipped `opp_temp` measurement, whose ±0.454 was
therefore raw.

It is gated that way for a reason — the covariate is Hard's own myopic price at
the opening node, free from an ask Hard is making anyway, and an expert arm's
tree value is a different quantity. Making it work for expert-vs-expert means
paying for one extra myopic ask per deal, which is cheap next to the tree. Worth
doing before anyone runs another 17-hour expert-vs-expert arm.

## What to do with the result

* Positive and clear → then check LATENCY before shipping. `Diverse` measured
  ~2.5x slower than `soft` on the exploitability control arm. Classic's first
  decision of a hand is ~1.56s → ~4s; skat is ~2.66s → ~6.6s against a 12s
  watchdog. Classic is comfortable, skat is not.
* Positive → also sweep the spread. **6 was chosen by analogy to `opp_temp`'s 5
  and has never been swept**, and `opp_temp`'s own sweep found 2 "too cold to
  change anything" and measured negative — the knob has a dead zone.
* Null or negative → the exploitability cut stands as a measurement about
  exploitability and nothing more, and the conditional defect (the opening
  barely varying with hand) is still untouched by it. That is the Edelkamp
  direction: widen the abstraction's features and bootstrap the table.
