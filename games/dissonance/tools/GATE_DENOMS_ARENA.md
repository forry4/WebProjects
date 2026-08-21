# PRE-REGISTRATION — the denomination-aware blueprint at the table (2026-08-21)

Written BEFORE any arena number exists. This campaign has recorded five
sign-flips between a first read and a declared one, and the most recent caught a
result already written down as "promising" (+1.1938 ± 0.7555 at n=800 → −0.4786
± 0.3951 at n=2900). The pre-registration is the only reason that was a
correction rather than a shipped regression.

## The question

Does giving the blueprint the real action space — a bid names a level AND a
denomination — make it play better against the shipped Expert?

## Why this is NOT a re-reading of the 14.0

`liftlab` measured the level-only abstraction as **14.0 points a deal more
exploitable** than the wide one. Three things already measured say that number
will not appear here, and they are recorded now so the arena cannot be spun
afterwards:

1. **The wide policy barely uses its freedom.** It names rank 0 on 89.9% of its
   bids (`bpexpress`, 200 deals / 477 decisions).
2. **The level-only bot is not restricted in play the way the abstraction models
   it.** `leaf` prices its raise as "rank = holds", but in serving the exact
   double-dummy pricer picks the denomination per deal — landing on rank 0 only
   38.2% of the time. The abstraction is pessimistic about its own restriction.
3. **Exploitability and head-to-head strength measure close to INDEPENDENT in
   this game** (Diverse: less exploitable, not stronger; Expert: more
   exploitable than Hard while winning +0.957).

**So the prediction on record is that the DENOMS blueprint is NO BETTER at the
table than the level-only one, and plausibly worse** — it replaces an exact
per-deal suit choice with a learned average preference over `hand_strength`, a
cheap estimate.

## The arms

| arm | auction | everything else |
|---|---|---|
| `bpdt` | blueprint, `CFR_DENOMS=1`, 200k iterations | the tree |
| `bplt` | blueprint, level-only, 200k iterations | the tree |
| `expertst` | shipped Expert | the tree |

Both blueprints are solved on the **same 600-deal all-denomination cache**, at
the **same iteration count**, and priced against the **same** Expert on the
**same** deals. That is what isolates the action space; the historical −12.84 ±
1.47 was measured on a different cache and is a reference point, not a control.

## Declared before reading

* **n = 800 paired deals per arm**, CRN-paired, dd-resolved, k=8.
* At the paired σ implied by the −12.84 ± 1.47 read (σ ≈ 27.7 a deal), n=800
  buys **± ~0.98**. That is deliberately sized to answer the question that
  matters — "does the wide action space close any material part of the
  blueprint's gap to Expert?" — and NOT sized to resolve a ±0.3 effect. If the
  answer lands inside ±1 of the level-only arm, the honest report is "no
  measurable difference at this n", not a sign.
* **The mirror control must read exactly 0.0000.** Any other value voids the run.
* **Primary comparison: `bpdt` − `bplt`** on the same deals. `expertst` is the
  common opponent, not the thing being ranked.
* **Ship criterion: none.** No arm here is a shipping candidate — the blueprint
  loses to Expert by a wide margin in both abstractions. This measures whether
  the ACTION SPACE is worth further work, and the answer is a direction for the
  research line, not a release.

## What would count as the 14.0 showing up

`bpdt` beating `bplt` by several points a deal. Given (1)–(3) above I do not
expect it, and if it happens the first thing to check is whether the two arms
really differ only in the auction.
