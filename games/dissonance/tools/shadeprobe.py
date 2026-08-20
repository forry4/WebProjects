"""IS THE AUCTION TREE PESSIMISTIC ONLY ABOUT THE BRANCH THAT CONTINUES? (2026-08-20)

THE LAST STANDING DIAGNOSIS, AND THE FIRST INSTRUMENT POINTED AT IT. Every arm
this campaign has run attacked either the SAMPLER (the belief prior and its
channels -- four nulls) or the ABSTRACTION (diverse, the blueprint, widened
features -- three refusals). None touched the defect the attribution keeps
naming: **both tiers concede level 4 at 31-67% where the equilibrium concedes
0-5%**, at every strength, on infosets with 11+ observations.

THE HYPOTHESIS, in the crate's own words: in the tree, PASSING is a LEAF --
priced once, myopically, as the standing contract from the opponent's side --
while RAISING continues into a subtree whose modelled opponent is handed our
exact hand and always finds the punishing reply. The subtree is shaded down
twice over (clairvoyance, plus the optimiser's curse compounding with depth).
**The pessimism is applied only to the branch that continues**, so raising looks
worse than passing BY CONSTRUCTION, which predicts exactly the observed sign.

THE MEASUREMENT NEEDS NO GROUND TRUTH AND NO CONTINUATION ASSUMPTION, which is
what makes it cheap and what makes it clean:

    shade(option) = tree_value(option) - myopic_value(option)

Both pricers are asked about the SAME option list at the SAME node, on their own
`bidserve` channels. Passing is a leaf in BOTH of them, so its shade is the
control and must read ~0. If the diagnosis is right, bids -- and only bids --
come back shaded negative. Any difference is the asymmetry, in per-world payoff
points, and it cannot be a leaf-accuracy artefact because both pricers share the
leaf.

GROUND TRUTH IS ASKED FOR ONLY WHERE IT DECIDES SOMETHING -- the pass, and each
pricer's favourite bid -- because a `resolve` is three exact solves and a node
carries ~50 options. Its job is the second question: when the shading FLIPS the
argmax from a bid to the pass, was the flip right? An exact resolve of "this
option settles the auction here" is the option's own price list applied to the
real deal, i.e. exactly what `_terms_for` promised, so no scoring is duplicated.

THE NODES ARE EXPERT'S OWN. The auction is driven by the tree's own argmax, so
the standing levels and hand strengths are the ones the shipped tier actually
faces -- this package's rule that WHICH BOT DID THE BIDDING IS THE DISTRIBUTION
applies to a diagnostic as much as to a rate.

    PYTHONPATH=. python3 games/dissonance/tools/shadeprobe.py [deals] [lo] [hi]

`SHADE_CKPT` makes it resumable per deal, like the arena.
"""
from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys

from games.dissonance import engine as E

TIER = os.environ.get("SHADE_TIER", "expertst")

# IMPORTING THE ARENA RUNS THE ARENA. `auction_arena.py` is a SCRIPT -- it reads
# `sys.argv` at module level AND its race body is module level with no
# `if __name__ == "__main__"` guard -- so a bare import executes a whole
# comparison against whatever argv happens to be there. The first version of
# this file did exactly that: my argv parsed as mode "6", **k = 0**, and every
# number below was produced by a search over ZERO worlds. It printed a clean,
# plausible table.
#
# The fix is to hand it a VALID, EMPTY window before importing, not to copy its
# `ask()` here: a second copy of the armed payload is precisely how `cfrlab`
# spent a campaign measuring Hard while its docstring said Expert. So `K` is
# read back OFF THE ARENA rather than kept here, and the two cannot diverge.
_K = os.environ.get("SHADE_K", "8")
_ARGV = list(sys.argv)          # ours, before the arena's parser eats it
sys.argv = ["auction_arena.py", "classic", _K, "0", TIER, TIER, "0", "0", "dd"]
from games.dissonance.tools import auction_arena as A   # noqa: E402

K = int(A.K)
assert A.MODE == "classic" and A.TIER_A == TIER, "arena imported misconfigured"
#: Exact resolves cost three solves apiece, so they are asked for only at the
#: options that can change a decision. Off gives the shade columns alone.
TRUTH = os.environ.get("SHADE_TRUTH", "1") not in ("", "0")


def myopic_sums(g, seat, opts):
    """The PRICE LIST's value for every option -- `bid::price`, no tree.

    IT MUST LAND ON THE SAME WORLDS AS THE TREE ASK OR IT MEASURES NOTHING BUT
    SAMPLING NOISE, and the first version of this probe did exactly that. Sent
    to its own channel (the `quality_of` discipline), it drew a fresh sample and
    the CONTROL -- the pass option, a leaf in both pricers, which must read ~0 --
    came back at **-13.2 +/- 6.5**. That is the two samples disagreeing, not the
    tree shading anything.

    So it goes to the SAME processes as `A.ask`, in the same order, after it:
    `bidserve` carries its one-slot `Solved` cache across lines, the tree's ask
    fills that entry with the UNION of denominations either seat could bid, and
    the price list wants a subset -- so this is a pure cache HIT and
    `bid::price` runs over `entry.worlds`, the identical worlds the tree just
    ranked. `answer_auction` computes both vectors off that one entry anyway;
    this reaches the second one without a Rust change.

    THE `swap` BLOCK IS LOAD-BEARING AND IS NOT DECORATION: it is XOR'd into the
    cache key (`hand_key ^ swap.key() ^ exact`), so a myopic ask that omits the
    talon model the tier carries keys DIFFERENTLY, misses, and solves fresh
    worlds -- re-creating the exact confound this function exists to remove, and
    evicting the tree's entry on the way out.
    """
    auc = {"phase": g["phase"], "declarer": seat, "options": opts}
    base = TIER[:-1] if TIER.endswith("b") else TIER
    if base.endswith("t") and E.mode_of(g) == "classic":
        auc["swap"] = A.B.swap_policy_terms()
    req = json.dumps({"view": E.view_for(g, seat), "auction": auc}) + "\n"
    per_k, nproc = A._kspec(A.K_A)
    sums = None
    for i in range(nproc):
        p = A.proc_for(("auc", TIER, seat, i), k=per_k, seed=i * 7919)
        p.stdin.write(req)
        p.stdin.flush()
        part = json.loads(p.stdout.readline()).get("sums")
        if not part or len(part) != len(opts):
            return None
        sums = part if sums is None else [a + b for a, b in zip(sums, part)]
    return sums


def exact_of(g, seat, o):
    """What this option is REALLY worth if the auction settles on it.

    Signed for the SEAT BEING ASKED, like every value in the option list. The
    pass carries `opp: True`, so the opponent declares its standing contract and
    the sign flips; a bid names its own denomination and we declare. The
    declarer LEADS trick 1, which is worth ~0.99 points double-dummy, so the
    leader moves with the declarer rather than being fixed.

    The terms are the OPTION'S OWN -- `_terms_for`'s answer, already carried on
    the option the search priced -- so this duplicates no scoring.
    """
    decl = 1 - seat if o.get("opp") else seat
    terms = {k: v for k, v in o.items() if k not in ("move", "opp", "redeal")}
    terms["declarer"] = decl
    req = json.dumps({"resolve": {
        "hands": [sorted(h) for h in g["hands"]],
        "piles": [[list(x) for x in q] for q in g["piles"]],
        "trump": o["denom"], "leader": decl, "terms": terms,
    }}) + "\n"
    p = A.proc_for(("shade_truth",), k=1, seed=7919)
    p.stdin.write(req)
    p.stdin.flush()
    pay = json.loads(p.stdout.readline()).get("payoff")
    return None if pay is None else (pay if decl == seat else -pay)


def node(g, seat):
    """One decision, priced both ways. None where the comparison cannot exist."""
    opts = E.auction_payoff_options(g)
    if not opts:
        return None, None
    ipass = [i for i, o in enumerate(opts) if o["move"]["kind"] == "pass"]
    ibid = [i for i, o in enumerate(opts) if o["move"]["kind"] == "bid"]
    # BOTH BRANCHES MUST BE LEGAL or there is no asymmetry to see. The classic
    # opener cannot pass, so its node is skipped rather than counted as a
    # concession -- exactly the node a naive count would poison.
    if not ipass or not ibid:
        mv, _, _ = A.ask(g, seat, TIER)
        return None, mv
    mv, tsum, _ = A.ask(g, seat, TIER)
    if not tsum or len(tsum) != len(opts):
        return None, mv
    msum = myopic_sums(g, seat, opts)
    if not msum:
        return None, mv

    # THE TIE-BREAK COMES OFF FIRST, and it is why the control read -0.000
    # rather than 0.000 on the first 400-deal run. `answer_auction` returns
    # `tree + 1e-5 * myopic` -- Hard's price ordering ties the tree cannot see --
    # so the raw sums carry a myopic term even on the pass. It is recoverable
    # EXACTLY, because this function is holding the same `myopic` vector the
    # Rust added, so the tree's own value is `sums - 1e-5 * myopic` and the
    # control goes back to being exactly zero rather than nearly zero.
    def tv(i):
        return (tsum[i] - 1e-5 * msum[i]) / K

    tp, mp = tv(ipass[0]), msum[ipass[0]] / K
    tb = [tv(i) for i in ibid]
    mb = [msum[i] / K for i in ibid]
    bt = max(range(len(ibid)), key=lambda j: tb[j])     # tree's favourite bid
    bm = max(range(len(ibid)), key=lambda j: mb[j])     # price list's favourite
    row = {
        "level": g["auction"]["level"],
        "shade_pass": tp - mp,
        # EVERY bid, unselected -- an argmax of either pricer would choose the
        # option whose own noise favoured it, which is the optimiser's curse
        # being measured instead of the shading.
        "shade_bid": statistics.mean(t - m for t, m in zip(tb, mb)),
        "shade_bestbid": tb[bm] - mb[bm],
        "tree_passes": bool(tp > tb[bt]),
        "myopic_passes": bool(mp > mb[bm]),
    }
    if TRUTH and row["tree_passes"] != row["myopic_passes"]:
        # ONLY WHERE THE SHADING FLIPPED THE DECISION. Three options resolved,
        # not fifty: the pass, and each pricer's own favourite bid.
        xp = exact_of(g, seat, opts[ipass[0]])
        xt = exact_of(g, seat, opts[ibid[bt]])
        xm = exact_of(g, seat, opts[ibid[bm]])
        if None not in (xp, xt, xm):
            row["flip"] = {
                "tree_took": xp if row["tree_passes"] else xt,
                "myopic_took": xp if row["myopic_passes"] else xm,
            }
    return row, mv


def deal(m):
    """Drive one auction with the tree's own argmax, pricing every node."""
    g = E.new_game(["a", "b"], random.Random(600000 + m), opener=m % 2,
                   mode="classic")
    redeal_rng = random.Random(900000 + m)
    rows = []
    guard = 0
    while g["phase"] == "auction" and guard < 40:
        guard += 1
        seat = E.turn_seat(g)
        if seat is None:
            break
        row, mv = node(g, seat)
        if row:
            rows.append(row)
        if mv is None:
            break
        E.apply_move(g, g["seats"][seat], mv, redeal_rng)
    return rows


def report(rows):
    def line(v):
        if len(v) < 2:
            return "n/a"
        return (f"{statistics.mean(v):+.3f} +/- "
                f"{statistics.stdev(v)/len(v)**0.5:.3f}")

    n = len(rows)
    print(f"\nshadeprobe: {n} auction decisions where BOTH passing and bidding "
          f"were legal\n  tier {TIER}, k={K}, values in per-world payoff points")
    print("\n  SHADE = tree value - price-list value, same option, same node")
    print(f"    {'passing (the CONTROL -- a leaf in both)':>42}: "
          f"{line([r['shade_pass'] for r in rows])}")
    print(f"    {'bidding, every option unselected':>42}: "
          f"{line([r['shade_bid'] for r in rows])}")
    print(f"    {'bidding, the price list favourite':>42}: "
          f"{line([r['shade_bestbid'] for r in rows])}")
    d = [r["shade_bid"] - r["shade_pass"] for r in rows]
    zero = all(r["shade_pass"] == 0.0 for r in rows)
    print(f"\n    {'ASYMMETRY (bid shade - pass shade)':>42}: {line(d)}")
    print("    " + ("the control is EXACTLY 0 on every node, so every point of "
                    "bid shade is asymmetry" if zero else
                    "*** CONTROL IS NOT ZERO -- the two pricers are not on the "
                    "same worlds; read nothing here ***"))

    tp = sum(1 for r in rows if r["tree_passes"])
    mp = sum(1 for r in rows if r["myopic_passes"])
    print(f"\n  CONCESSION RATE at these nodes")
    print(f"    {'tree':>42}: {tp}/{n} = {100*tp/n:.1f}%")
    print(f"    {'price list':>42}: {mp}/{n} = {100*mp/n:.1f}%")

    # BY STANDING LEVEL, because the defect the attribution names is specific:
    # both tiers concede level 4 where the equilibrium concedes ~never. A shade
    # that is flat across levels would be a general pessimism; one that grows
    # with the standing bid is the subtree getting deeper and is the mechanism.
    print(f"\n  {'standing':>8}  {'n':>4}  {'bid shade':>16}  {'tree pass':>9}  "
          f"{'list pass':>9}")
    for lv in sorted({r["level"] for r in rows}):
        v = [r for r in rows if r["level"] == lv]
        sb = [r["shade_bid"] for r in v]
        t = 100 * sum(1 for r in v if r["tree_passes"]) / len(v)
        m = 100 * sum(1 for r in v if r["myopic_passes"]) / len(v)
        print(f"  {lv:>8}  {len(v):>4}  {line(sb):>16}  {t:>8.1f}%  {m:>8.1f}%")

    fl = [r for r in rows if "flip" in r]
    if fl:
        gain = [r["flip"]["tree_took"] - r["flip"]["myopic_took"] for r in fl]
        print(f"\n  WHERE THE SHADING FLIPPED THE DECISION ({len(fl)} nodes), "
              f"against exact truth")
        print(f"    {'tree minus price list, real payoff':>42}: {line(gain)}")
        better = sum(1 for x in gain if x > 0)
        worse = sum(1 for x in gain if x < 0)
        print(f"    {'tree better / worse / same':>42}: "
              f"{better} / {worse} / {len(gain)-better-worse}")
    print("\n  The pass row is the control: it is a LEAF in both pricers, so a "
          "shade there\n  is measurement noise. A bid row that differs from it "
          "is the asymmetry.")


def main(argv):
    n = int(argv[1]) if len(argv) > 1 else 200
    lo = int(argv[2]) if len(argv) > 2 else 0
    hi = int(argv[3]) if len(argv) > 3 else n
    ck = os.environ.get("SHADE_CKPT")
    done, rows = set(), []
    if ck and os.path.exists(ck):
        for ln in open(ck):
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            done.add(r["m"])
            rows.extend(r["rows"])
    fh = open(ck, "a") if ck else None
    for m in range(lo, hi):
        if m in done:
            continue
        rs = deal(m)
        rows.extend(rs)
        if fh:
            fh.write(json.dumps({"m": m, "rows": rs}) + "\n")
            fh.flush()
        if (m - lo + 1) % 10 == 0:
            print(f"  deal {m-lo+1}/{hi-lo}, {len(rows)} nodes", flush=True)
    if rows:
        report(rows)


if __name__ == "__main__":
    main(_ARGV)
