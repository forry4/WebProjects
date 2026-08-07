
### Null at 0% is NOT a finding, and the Sharp knob barely moved

Two entries retired, one of them by arithmetic that should have been done
before it was ever written down.

**Null.** Every skat run reports 0% Null contracts, and that is exactly what a
working mechanic looks like at this sample size. Null's measured per-deal
availability is **~7%** (the no-even-trick version; see the section above), so
over 32 deals the expected count is about two and P(zero) is roughly 11%.
Observing none is unremarkable. Distinguishing 0% from 5% needs hundreds of
deals, which no run here has had — so "Null is dead in skat mode" was never
supported and is withdrawn.

Worth stating the corollary, because it is the actually useful part: **the
binding constraint on Null is availability, not price and not the trump rule.**
Playing it at no-trump is not a restriction to relax either — NT weakly
DOMINATES every suit for a Null declarer. Trump adds one danger no-trump has
not got, the forced ruff: late in a hand, if all you hold is trumps and a side
suit is led, you must play a trump and it wins, where at no-trump the same
position is a safe discard. Trump cannot help in return, because the only thing
it offers the declarer is the defender being ABLE to ruff — and a defender
defending Null will never take a trick voluntarily. Letting the declarer pick
the denomination would therefore add a decision whose answer is "no-trump" on
essentially every hand.

Levers that would move Null are the ones that raise AVAILABILITY — a bigger
talon swap so more than one stopper can be buried, or softening the condition
to "at most one +2 trick". Not the value, and not the denomination.

**Sharp.** The bonus sweep (24 deals each, k=10/tk=6, q=0.0, Kontra polarity
fixed):

| sharp_bonus | Sharp rate | Hand rate | declarer net |
|---|---|---|---|
| 3 | 0.0% (0/24) | 95.8% | +30.67 |
| 2 | 4.2% (1/24) | 91.7% | +32.75 |

Shipped at 2, and it moved the rate off zero — but one contract in 24 is a
single observation, not a rate, and it is nowhere near a live mechanic. The
structural reason is unchanged by the number: **Hand and Sharp each add exactly
+1, while Hand costs one declined card swap and Sharp costs points off a
12-point scale.** That is a property of ADDITIVE stacking, so tuning the bonus
further is unlikely to be what fixes it; the multiplier structure is.
