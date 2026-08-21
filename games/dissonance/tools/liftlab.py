"""IS THE LEVEL-ONLY ABSTRACTION LEAVING MONEY ON THE TABLE? (2026-08-21)

THE QUESTION `DENOMS` WAS BUILT TO ANSWER, and it cannot be answered by
comparing two exploitability numbers. Exploitability is only defined against a
best responder, and the two abstractions hand the responder different action
sets -- so the level-only figure and the wide figure are numbers from different
games and ranking them is meaningless. The campaign has made that mistake in
other clothes twice.

THE EMBEDDING IS EXACT, WHICH IS WHAT MAKES THIS WORK. The level-only game is a
strict SUB-GAME of the wide one, not an approximation of it:

    pass            -> pass
    HOLD            -> the SAME level at rank `holds + 1`
    raise to `L`    -> level `L` at rank 0

`leaf` already prices a contract as "rank = holds" under the all-denomination
cache, and level-only's `_step` resets `holds` to 0 on a raise and increments it
on a HOLD -- so a level-only state `(level, prev, holds)` and a wide state
`(level, prev, rank)` with `rank == holds` are THE SAME CONTRACT with THE SAME
payoff. The lift is a relabelling, and every lifted action is legal where it
lands (a HOLD's `holds + 1` is exactly the "strictly higher rank" a same-level
bid must name).

So: solve level-only, LIFT the policy into the wide action space, and let a
best responder with the full denomination set loose on it. That prices what the
abstraction costs in a single number, against the same responder that prices
the wide equilibrium. Two policies, one game, one instrument.

    PYTHONPATH=. CFR_DCKPT=<all-denom cache> python3 \\
        games/dissonance/tools/liftlab.py <iters-level-only> <iters-wide>
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time

_ARGV = list(sys.argv)
sys.argv = ["cfrlab.py"]
from games.dissonance.tools import cfrlab as C   # noqa: E402
sys.argv = _ARGV


def solve(recs, iters, seed=1234):
    """Average strategy after `iters` iterations, both seats trained."""
    cfr = C.CFR(recs)
    rng = random.Random(seed)
    t0 = time.time()
    for i in range(iters):
        rec = recs[rng.randrange(len(recs))]
        cfr.t = i + 1
        for me in (0, 1):
            cfr.iterate(rec, me, rng)
    eq = {}
    for key, s in cfr.S.items():
        tot = sum(max(x, 0.0) for x in s.values())
        if tot > 0:
            eq[key] = {a: max(x, 0.0) / tot for a, x in s.items()}
    return eq, time.time() - t0


def lift(eq):
    """Relabel a level-only policy into the packed action space.

    THE STATE KEY IS UNCHANGED -- `(bucket, level, prev, holds)` reads as
    `(bucket, level, prev, RANK)` on the other side and means the same
    contract. Only the ACTIONS move.
    """
    out = {}
    for (bucket, level, prev, holds), row in eq.items():
        moved = {}
        for a, p in row.items():
            if a == -1:
                moved[-1] = moved.get(-1, 0.0) + p
                continue
            if a == C.HOLD:                     # same level, next rank up
                b = level * C._APACK + (holds + 1)
            else:                               # raise: the bidder's best suit
                b = a * C._APACK
            moved[b] = moved.get(b, 0.0) + p
        out[(bucket, level, prev, holds)] = moved
    return out


def price(recs, table, backoff):
    """Exploitability of `table` in the WIDE game, both seats.

    REPORTED BOTH WAYS ON PURPOSE. `Policy`'s own docstring records why: an
    infoset the table never reached CONCEDES under `backoff=False`, and a best
    responder then bids high purely to steer into the holes, so the number
    comes back as mostly a sample size. That failure mode is not hypothetical
    here -- the lifted policy is solved in a SMALLER game, so it is structurally
    the one with holes, and reading the gap off the no-backoff column alone
    would manufacture exactly the answer this probe is looking for. `hits[9]`
    is the reach-weighted share that fell all the way through, which is what
    says whether the two columns should differ at all.
    """
    p = C.Policy(table, backoff=backoff)
    b0 = C.best_response(recs, p, 0)
    miss = p.hits[9] / max(sum(p.hits.values()), 1e-9)
    p.hits.clear()
    b1 = C.best_response(recs, p, 1)
    miss = max(miss, p.hits[9] / max(sum(p.hits.values()), 1e-9))
    return b0, b1, (b0 + b1) / 2, miss


def _child(argv, env):
    e = dict(os.environ)
    e.update(env)
    r = subprocess.run([sys.executable, __file__] + argv, env=e,
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"child failed:\n{r.stdout}\n{r.stderr}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def main(argv):
    ck = os.environ.get("CFR_DCKPT")
    if not ck:
        raise SystemExit("liftlab needs CFR_DCKPT pointing at an "
                         "all-denomination cache (`cfrlab dcache N`)")
    recs = [json.loads(x) for x in open(ck) if x.strip()]
    if not any(isinstance(r["pts"][0], list) for r in recs):
        raise SystemExit(
            f"{ck} is a plain cache -- its `pts` are scalars, so every "
            "denomination would price identically and the whole comparison "
            "would read zero by construction. Build one with `cfrlab dcache`.")
    C.bucketise(recs)

    # A CHILD PROCESS PER ABSTRACTION, NOT A MODULE RELOAD. `CFR_DENOMS` is read
    # once at import; deleting `sys.modules` and re-importing does NOT re-read
    # it, and this package has already measured one arm twice while believing it
    # had measured two (visible only as an infoset count that did not move).
    if len(argv) > 3 and argv[1] == "--solve":
        eq, secs = solve(recs, int(argv[2]))
        print(json.dumps({"secs": secs, "eq": [
            [list(k), {str(a): v for a, v in row.items()}]
            for k, row in eq.items()]}))
        return

    narrow_it = int(argv[1]) if len(argv) > 1 else 200_000
    wide_it = int(argv[2]) if len(argv) > 2 else 19_000

    # SOLVES ARE CACHED TO DISK, because pricing is the part that gets
    # re-asked (with backoff, against a different responder, at a different
    # coverage threshold) and re-solving to change a display option is how a
    # measurement session turns into an afternoon.
    def cached(tag, want, build):
        f = os.path.join(cdir, f"{tag}_{want}.json") if cdir else None
        if f and os.path.exists(f):
            got = json.load(open(f))
            return ({tuple(k): {int(a): v for a, v in row.items()}
                     for k, row in got["eq"]}, got["secs"])
        got = build()
        if f:
            json.dump({"secs": got[1], "eq": [[list(k), {str(a): v for a, v
                                                         in row.items()}]
                                              for k, row in got[0].items()]},
                      open(f, "w"))
        return got

    cdir = os.environ.get("CFR_LIFT_DIR")
    if cdir:
        os.makedirs(cdir, exist_ok=True)

    def _narrow():
        got = _child(["--solve", str(narrow_it), "x"], {"CFR_DENOMS": "0"})
        return ({tuple(k): {int(a): v for a, v in row.items()}
                 for k, row in got["eq"]}, got["secs"])

    narrow, nsecs = cached("narrow", narrow_it, _narrow)
    if not C.DENOMS:
        raise SystemExit("run the parent with CFR_DENOMS=1 -- the pricing side "
                         "IS the wide game")
    wide, wsecs = cached("wide", wide_it, lambda: solve(recs, wide_it))

    print(f"  {len(recs)} all-denomination deals, MAXL={C.MAXL}")
    print(f"  level-only solve: {narrow_it:,} iters, {nsecs:.0f}s, "
          f"{len(narrow)} infosets")
    print(f"  wide solve:       {wide_it:,} iters, {wsecs:.0f}s, "
          f"{len(wide)} infosets\n")
    print(f"  {'policy':>22} {'backoff':>8} {'BR seat 0':>10} "
          f"{'BR seat 1':>10} {'exploitability':>15} {'unseen':>8}")
    for name, tbl in (("level-only, LIFTED", lift(narrow)),
                      ("wide (native)", wide)):
        for backoff in (False, True):
            b0, b1, ex, miss = price(recs, tbl, backoff)
            print(f"  {name:>22} {str(backoff):>8} {b0:>10.2f} {b1:>10.2f} "
                  f"{ex:>15.2f} {100 * miss:>7.1f}%")
    print("\n  Both priced by the SAME responder in the SAME (wide) game, so "
          "the\n  difference is what the level-only abstraction costs. Read "
          "the BACKOFF\n  rows: the no-backoff pair prices coverage, not the "
          "abstraction.")


if __name__ == "__main__":
    main(_ARGV)
