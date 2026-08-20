"""Pool `auction_arena` checkpoints into one reading, at any point in a run.

WHY THIS EXISTS. The arena only prints its poolable `SHARD {...}` line when a
shard FINISHES, and the gate this was written for is a ~17-hour run on a 4-core
box that will not finish inside one session. The checkpoints hold the same
per-deal records, so a partial run is readable without waiting for -- or
corrupting -- the run producing them.

    PYTHONPATH=. python3 games/dissonance/tools/gate_pool.py <ckpt> [<ckpt> ...]

Reads the same fields `auction_arena` writes and resumes from: `pair` is the
deal's two flips averaged (so seat and cards both cancel), `q` is the opener's
hand quality for the control variate, `differ` says whether the two arms
actually bid differently.

A half-written last line is the normal shape of a kill, not corruption -- the
arena drops it and replays that deal, and so does this.
"""
from __future__ import annotations

import json
import sys


def load(paths):
    pairs, qs, differ, seen = [], [], [], set()
    for p in paths:
        try:
            fh = open(p, encoding="utf-8")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Shards partition the deal index, so a duplicate `m` means two
                # shards were pointed at one checkpoint -- which would double
                # count. Guard rather than trust the caller.
                key = (p, r["m"])
                if key in seen:
                    continue
                seen.add(key)
                pairs.append(r["pair"])
                qs.append(r.get("q", 0.0))
                differ.append(bool(r.get("differ")))
    return pairs, qs, differ


def stats(v):
    n = len(v)
    if n < 2:
        return (v[0] if v else 0.0), 0.0, n
    m = sum(v) / n
    var = sum((x - m) ** 2 for x in v) / (n - 1)
    return m, (var / n) ** 0.5, n


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    pairs, qs, differ = load(argv[1:])
    if not pairs:
        raise SystemExit("no deals in those checkpoints yet")
    m, se, n = stats(pairs)
    print(f"pooled over {n} paired deals from {len(argv) - 1} checkpoint(s)")
    print(f"  expertdt - expertst = {m:+.4f} +/- {se:.4f} payoff/round")
    print(f"  95% CI              [{m - 1.96 * se:+.3f}, {m + 1.96 * se:+.3f}]")
    nd = sum(differ)
    print(f"  auctions that differ: {nd}/{n} ({100.0 * nd / n:.1f}%)")
    if nd:
        dm, dse, _ = stats([p for p, d in zip(pairs, differ) if d])
        print(f"  conditional on differing: {dm:+.4f} +/- {dse:.4f}")

    # CONTROL VARIATE on the opener's hand quality. It cannot move the mean's
    # expectation, only shrink its error bar -- so a large shift here is a
    # symptom (an unbalanced sample), not a better estimate.
    qm = sum(qs) / n
    sq = sum((q - qm) ** 2 for q in qs)
    if sq > 0:
        beta = sum((p - m) * (q - qm) for p, q in zip(pairs, qs)) / sq
        adj = [p - beta * (q - qm) for p, q in zip(pairs, qs)]
        am, ase, _ = stats(adj)
        shrink = (1.0 - ase / se) * 100.0 if se > 0 else 0.0
        print(f"  quality-adjusted:   {am:+.4f} +/- {ase:.4f}  "
              f"(beta {beta:+.3f}, se {shrink:+.0f}%)")
    # The precision this run is aiming at, so a partial read is never mistaken
    # for the gate itself.
    print(f"  [target for the gate: n=1550, +/- ~0.46 -- "
          f"{'REACHED' if n >= 1550 else f'{100.0 * n / 1550:.0f}% of the way'}]")


if __name__ == "__main__":
    main(sys.argv)
