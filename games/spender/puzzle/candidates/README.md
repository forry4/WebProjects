# Puzzle candidate ledger

`candidate_ledger.jsonl.gz` — one line per **verified** position from the offline puzzle miners
(self-play + real WWSD games). Each line is the compact engine state plus **every legal move's
K=8-averaged N eval**. That table is the expensive artifact (per position ≈ #moves × 8 searches);
persisting it makes a future accept-threshold change a pure re-filter with **zero AI recompute**.

## Re-emit puzzles at any threshold
```bash
# report what's available at each gap bar (no writes)
python -m games.spender.puzzle.candidates.rebuild_from_ledger --stats

# emit takes at the shipped rule (gap >= 0.25, no upper bound)
python -m games.spender.puzzle.candidates.rebuild_from_ledger --out /tmp/takes --types take

# try a softer take bar (e.g. 0.15)
python -m games.spender.puzzle.candidates.rebuild_from_ledger --out /tmp/t --types take --gap-take 0.15
```
Then renumber/merge the emitted `advantage_*.json` into `../puzzles/` (see the miner tooling notes in
the root CLAUDE.md "Spender Puzzle mode" section) and ship.

## Accept rule (matches the shipped bank)
- **buy / reserve**: gap (best − 2nd best N eval) in `[0.25, 0.50]` — the upper bound rejects blowouts
  (a huge-gap buy is an obvious forced win, not a puzzle).
- **take**: gap `>= 0.25`, **no upper bound** — a big-gap take is NOT obvious the way a big-gap buy is,
  because the wrong gem-combos look identical to the right one (measured: most ≥0.25 takes have another
  *take* as the runner-up). Genuine only-move takes are structurally rare, so this keeps every good one.
- Answers that would force a discard/noble sub-step are always excluded (bad puzzle UX).

## Growing the ledger
The miners (`gen_single.py` / `harvest_wwsd.py`, scratchpad tooling) take `--ledger PATH` and append
every verified candidate. New WWSD downloads or self-play runs can be swept and their ledgers merged
into this file (dedupe by the `(dump, hero)` key).
