# Transient gate checkpoints — DELETE once the gate is recorded

Per-deal results for the diverse-vs-Expert auction gate, banked here **only
because this repo is the one durable store** reachable from an ephemeral remote
container. See `../GATE_RESUME.md` for the invocation and the two settings that
would silently invalidate a re-run.

Re-running `auction_arena.py` with `ARENA_CKPT` pointed at one of these files
skips the deals it already holds, so the sample EXTENDS rather than restarts.
One file per shard; a shard must never share a checkpoint with another.

**These are measurement state, not fixtures.** Nothing reads them at build or
test time. Once the gate has a result and that result is written into
`games/dissonance/CLAUDE.md`, delete this directory.
