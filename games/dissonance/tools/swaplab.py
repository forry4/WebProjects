"""The talon swap, held against an ORACLE.

`bot.choose_swap` is the swap every tier plays (the talon stays server-side),
and it measures **-0.477 +- 0.226 score per round against standing pat** over
3000 paired deals. Before designing a replacement, this asks the sharper
question: on each real swap decision, what was the BEST exchange, and what does
the current policy's choice cost against it?

THE ORACLE CHEATS, ON PURPOSE. For every candidate exchange (3 shown x 7 held,
plus standing pat) it applies the swap and resolves the settled contract by an
exact double-dummy solve of the REAL deal -- hidden cards included -- via
`bidserve`'s `resolve` request. That is an upper bound no honest policy can
reach, because the real decision sees only the hand, the shown talon and the
public piles. It is a DIAGNOSTIC, not a ship gate: it says what kinds of
exchange are worth making, and how much of the current policy's loss is
recoverable at all. The ship gate stays what it was -- a paired arena over the
real information set.

Per decision it records every candidate's exact value plus the features a
replacement heuristic would have to work from (ranks, trumpness, resulting
suit shape), so the report can say not just "the policy is wrong" but what the
oracle DOES instead.

    cargo build --release --features bridge --bin bidserve
    PYTHONPATH=. python3 games/dissonance/tools/swaplab.py <mode> <n> \\
        [<lo> <hi> [dd|play]]

Shards by deal window like the arena; prints one `SWAP {...}` line per decision.
The `dd` build needs `cargo build --release --features bridge --bin bidserve`;
`play` needs no Rust at all and runs ~600 rounds a second, so a corpus that
assumes the SHIPPED card play is essentially free to build.
"""
import json
import sys

from games.dissonance import bot as B
from games.dissonance.tools import talon as T

MODE = sys.argv[1] if len(sys.argv) > 1 else "classic"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 100
LO = int(sys.argv[3]) if len(sys.argv) > 3 else 0
HI = int(sys.argv[4]) if len(sys.argv) > 4 else N
#: WHICH CARD PLAY THE LABEL ASSUMES -- `dd` (the exact solve, the oracle this
#: file was built around) or `play` (the shipped bot). Both are real objectives
#: and they DISAGREE: a policy fitted to `dd` labels measured +0.817 a round
#: against the shipped rule under `dd` and -2.132 under `play` (`swaparena`).
#: So the resolution is not a detail of the harness, it is a choice about which
#: card player the talon is being optimised for.
RES = sys.argv[5] if len(sys.argv) > 5 else "dd"
SOLVER = T.Solver() if RES in ("dd", "hard") else None
SKAT = MODE == "skat"


def one(m):
    """Drive one round to the swap; enumerate and resolve every candidate."""
    at = T.drive_to_talon(m, MODE)
    if at is None:
        return None
    g, decl = at
    denom = g["auction"]["denom"]
    hand = sorted(g["hands"][decl])
    shown = list(g["shown"])
    snap = json.dumps(g)

    def value_of(take, give):
        return T.value(snap, decl, take, give, m, RES, SOLVER)

    pat_v = value_of(None, None)
    if pat_v is None:
        return None
    cands = [{"take": None, "give": None, "v": pat_v}]
    for t in shown:
        for h in hand:
            v = value_of(t, h)
            if v is None:
                return None
            cands.append({"take": t, "give": h, "v": v})
    cur = B.choose_swap(g, decl)
    best = max(cands, key=lambda c: c["v"])
    pat = cands[0]["v"]
    cur_v = next(c["v"] for c in cands
                 if c["take"] == cur["take"] and c["give"] == cur["give"])
    return {"deal": m, "denom": denom, "res": RES,
            # Skat's level is not settled yet; its bid VALUE is what the
            # declarer has to satisfy, and is the analogous number.
            "level": g["auction"]["value"] if SKAT else g["auction"]["level"],
            "guess": B.swap_denom(g, decl) if SKAT else denom,
            "declarer": decl,
            "hand": hand, "shown": shown,
            "pat": pat, "best": best["v"], "cur": cur_v,
            "best_take": best["take"], "best_give": best["give"],
            "cur_take": cur["take"], "cur_give": cur["give"],
            "n_gaining": sum(1 for c in cands[1:] if c["v"] > pat),
            "cands": [[c["take"], c["give"], c["v"]] for c in cands]}


for m in range(LO, HI):
    rec = one(m)
    if rec:
        print("SWAP " + json.dumps(rec), flush=True)
