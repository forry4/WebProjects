"""THE SWAP'S SHIP GATE: two talon policies, paired on the same deals.

`swaplab` measures REGRET AGAINST AN ORACLE that resolves every candidate
against the real deal. That is a diagnostic and it cannot be a ship gate: the
oracle cheats, so beating another policy's regret says the fit RANKS candidates
better, not that the rounds come out better once real cards get played over the
real information set. Classic's fitted swap shipped on this instrument, not on
its held-out regret (+1.500 +- 0.208 vs pat, +1.976 +- 0.194 vs the old rule,
3000 deals); skat's fit has to clear the same bar.

PAIRED BY CONSTRUCTION, and it needs no CRN trick to be. A deal is driven ONCE
to the talon -- same cards, same auction, same declarer -- and the snapshot is
then branched per arm. Everything downstream of the swap is deterministic given
the state and a seeded RNG, and each arm gets the SAME seed, so a deal where the
two arms pick the same exchange contributes an exact 0 rather than noise. There
is no mirror to run: the arms are two policies for ONE seat, not two tiers
sitting in two seats, so there is nothing for a seat swap to cancel.

    old   the shipped `choose_swap`             (skat: the separable rank rule)
    fit   the same function under DIS_SKAT_SWAP_OLD
    pat   stand pat -- decline the exchange entirely

`fit` and `old` are THE SAME SHIPPED FUNCTION under two settings of its own
flag, deliberately: a copy of the policy in the harness is a second
implementation, and the number it produces is then about the copy.

RESOLUTION -- and the swap's value depends on who plays the cards afterwards,
so this is a flag and both answers matter. The old classic rule measured +1.6
vs pat under exact play and -0.48 under greedy; a policy that only wins under a
resolution nobody plays has not won.

* ``play`` (default): the round is PLAYED OUT by the shipped bot, declaration,
  Kontra and all. This is the real information set -- it is what the server
  actually does with a talon -- and it needs no solver, which is what makes a
  3000-deal run cheap.
* ``dd``: the settled contract is scored by an exact double-dummy solve of the
  real deal (`bidserve`'s ``resolve``), so card play contributes no noise and no
  bias. Needs `cargo build --release --features bridge --bin bidserve`.

WHAT THE DECLARATION IS ALLOWED TO DO. In skat the talon resolves BEFORE the
game is named, so each arm makes its OWN declaration from its OWN post-swap hand
via the shipped `choose_declare`. That is not a contaminant: naming a better
game is part of what a good swap buys, and holding the declaration fixed would
measure a decision nobody makes. Under ``play`` the defender's Kontra is left
live for the same reason -- it is answering the contract this arm arrived at.
Under ``dd`` Kontra/Re are forced off, matching `swaplab`, because there the
comparison has to be between swaps and not between two tiers' Kontra answers.

    PYTHONPATH=. python3 games/dissonance/tools/swaparena.py \\
        <mode> <n> <armA> <armB> [<lo> <hi> [play|dd]]

Shards by deal window; each shard prints a `SHARD {...}` line to pool.
"""
import json
import math
import os
import sys

from games.dissonance import bot as B
from games.dissonance.tools import talon as T

MODE = sys.argv[1] if len(sys.argv) > 1 else "skat"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 200
ARM_A = sys.argv[3] if len(sys.argv) > 3 else "fit"
ARM_B = sys.argv[4] if len(sys.argv) > 4 else "old"
LO = int(sys.argv[5]) if len(sys.argv) > 5 else 0
HI = int(sys.argv[6]) if len(sys.argv) > 6 else N
RES = sys.argv[7] if len(sys.argv) > 7 else "play"
SOLVER = T.Solver() if RES in ("dd", "hard") else None

#: THE MIRROR'S TEETH. `arm arm` reads +0.0000 for free, because identical picks
#: short-circuit to an exact 0 without playing a card -- which makes the usual
#: mirror check assert nothing about the PLAYOUT. `SWAPARENA_NO_SHORTCUT=1`
#: removes the short-circuit so both arms are actually driven through the whole
#: round, and a mirror under it is a real statement: the round is deterministic
#: given the state and the seed, so anything but +0.0000 is a leak between the
#: two branches (a shared mutable snapshot, an RNG drawn once and reused, a
#: policy reading a global the previous arm moved).
NO_SHORTCUT = bool(os.environ.get("SWAPARENA_NO_SHORTCUT"))


def pick(g, decl, arm):
    """One arm's exchange, from the SHIPPED function under its own flag."""
    if arm == "pat":
        return (None, None)
    was = os.environ.get("DIS_SKAT_SWAP_OLD")
    try:
        if arm == "old":
            os.environ["DIS_SKAT_SWAP_OLD"] = "1"
        else:
            os.environ.pop("DIS_SKAT_SWAP_OLD", None)
        sw = B.choose_swap(g, decl)
    finally:
        os.environ.pop("DIS_SKAT_SWAP_OLD", None)
        if was is not None:
            os.environ["DIS_SKAT_SWAP_OLD"] = was
    return (sw["take"], sw["give"])


def one(m):
    at = T.drive_to_talon(m, MODE)
    if at is None:
        return None
    g, decl = at
    snap = json.dumps(g)
    ta, ga = pick(g, decl, ARM_A)
    tb, gb = pick(g, decl, ARM_B)
    if (ta, ga) == (tb, gb) and not NO_SHORTCUT:
        # IDENTICAL PICKS CONTRIBUTE AN EXACT 0 and are counted, not dropped.
        # Dropping them would report the conditional mean as if it were the
        # per-deal one -- the effect on a round of play is what ships, and a
        # policy that agrees with the incumbent most of the time moves it less.
        return {"deal": m, "d": 0.0, "same": True}
    va = T.value(snap, decl, ta, ga, m, RES, SOLVER)
    vb = T.value(snap, decl, tb, gb, m, RES, SOLVER)
    if va is None or vb is None:
        return None
    return {"deal": m, "d": va - vb, "same": False, "a": va, "b": vb}


def ci(xs):
    n = len(xs)
    if n < 2:
        return (0.0, 0.0)
    mu = sum(xs) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))
    return (mu, 1.96 * sd / math.sqrt(n))


def main():
    ds, diff = [], []
    print(f"  {ARM_A} vs {ARM_B}   mode={MODE} resolution={RES} deals [{LO},{HI})")
    for m in range(LO, HI):
        r = one(m)
        if r is None:
            continue
        ds.append(r["d"])
        if not r["same"]:
            diff.append(r["d"])
        if len(ds) % 100 == 0:
            mu, h = ci(ds)
            # A CI ON EVERY PROGRESS LINE, never a bare running mean: the first
            # 300 deals of an auction-arena run once read +1.71 where the full
            # run said -0.28, and the bare mean is what got quoted.
            print(f"    {len(ds):>5} deals   {mu:+.3f} +- {h:.3f}"
                  f"   (differing {len(diff)})", flush=True)
    mu, h = ci(ds)
    dmu, dh = ci(diff)
    print(f"\n  PER DEAL       {mu:+.3f} +- {h:.3f}   n={len(ds)}")
    print(f"  differing only {dmu:+.3f} +- {dh:.3f}   n={len(diff)} "
          f"({100 * len(diff) / max(1, len(ds)):.0f}% of deals)")
    print("SHARD " + json.dumps({"mode": MODE, "res": RES, "a": ARM_A, "b": ARM_B,
                                 "lo": LO, "hi": HI, "d": ds, "n_diff": len(diff)}))


if __name__ == "__main__":
    main()
