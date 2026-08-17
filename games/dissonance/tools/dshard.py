"""Build a SLICE of the all-denomination deal cache, so the build can shard.

`cfrlab dcache` derives each deal's seed from the current row count
(`900_000 + len(recs)`), which is correct and resumable but inherently
SEQUENTIAL -- two processes pointed at one checkpoint would draw the same seeds
and interleave their writes. This takes the seed range EXPLICITLY instead, so N
shards can build disjoint slices in parallel and be concatenated afterwards.

At ~2.9s a deal that is the difference between ~70 minutes and ~17 on four
cores, which is what made the 2000-deal suit-priced ladder measurement
affordable (see this game's CLAUDE.md, "THE SUIT-PRICED LADDER -- RESOLVED").

Run, one shard per core, then concatenate:

    for i in 0 1 2 3; do
      lo=$((900600 + i*350)); hi=$((900600 + (i+1)*350))
      PYTHONPATH=. python -m games.dissonance.tools.dshard $lo $hi dc/s$i.jsonl &
    done; wait
    cat dcache.jsonl dc/s*.jsonl > dc2000.jsonl

RESUMES BY SEED, not by row count -- re-running the same range tops up whatever
is missing, so a shard killed by a timeout is picked up by the next invocation.
Each row carries its `seed` for exactly that reason; `cfrlab`'s readers ignore
the extra key, but strip it if you want a byte-identical cache.

MIND THE SEED RANGE. The original 600-deal `dcache.jsonl` is seeds
900_000..900_599 and carries no `seed` field, so it cannot be de-duplicated
against -- start new work at 900_600 or you will silently pool duplicates.
"""
import json
import os
import sys

from games.dissonance.tools import cfrlab as C


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    lo, hi, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    done = set()
    if os.path.exists(out):
        for line in open(out):
            try:
                done.add(json.loads(line)["seed"])
            except (json.JSONDecodeError, KeyError):
                pass
        print(f"  resumed {len(done)} deals from {out}", flush=True)
    f = open(out, "a")
    for seed in range(lo, hi):
        if seed in done:
            continue
        rec = C.sample_deal_alldenoms(seed)
        rec["seed"] = seed
        f.write(json.dumps(rec) + "\n")
        f.flush()
    print(f"shard {lo}-{hi} -> {out}: {sum(1 for _ in open(out))} rows")


if __name__ == "__main__":
    main()
