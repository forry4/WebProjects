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
    PYTHONPATH=. python3 games/dissonance/tools/swaplab.py <mode> <n> [<lo> <hi>]

Shards by deal window like the arena; prints one `SWAP {...}` line per decision.
"""
import json
import random
import subprocess
import sys

from games.dissonance import engine as E, bot as B

BIN = "rust-cores/dissonance-core/target/release/bidserve"
MODE = sys.argv[1] if len(sys.argv) > 1 else "classic"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 100
LO = int(sys.argv[3]) if len(sys.argv) > 3 else 0
HI = int(sys.argv[4]) if len(sys.argv) > 4 else N

PROC = subprocess.Popen([BIN, "3"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        text=True)


def resolve(g):
    """Exact declarer payoff of `g`'s settled contract on the real deal."""
    terms = E.payoff_terms(g)
    req = {"resolve": {"hands": [list(h) for h in g["hands"]],
                       "piles": [[list(x) for x in row] for row in g["piles"]],
                       "trump": g["auction"]["denom"],
                       "leader": terms["declarer"], "terms": terms}}
    PROC.stdin.write(json.dumps(req) + "\n")
    PROC.stdin.flush()
    r = json.loads(PROC.stdout.readline())
    if "payoff" not in r:
        raise SystemExit(f"unresolvable: {r}")
    return r["payoff"]


def one(m):
    """Drive one round to the swap phase; enumerate and resolve every candidate."""
    g = E.new_game(["a", "b"], random.Random(600000 + m), opener=m % 2, mode=MODE)
    rng = random.Random(m)
    guard = 0
    while g["phase"] not in ("swap", "play", "over") and guard < 40:
        guard += 1
        seat = E.turn_seat(g)
        kind, p = B.act(g, seat, rng)
        mv = ({"kind": "pass"} if p.get("pass")
              else {"kind": "bid", **{a: b for a, b in p.items() if a != "pass"}}) \
            if kind == "bid" else (p if kind == "move"
                                   else ({"kind": "swap", **p} if kind == "swap" else p))
        E.apply_move(g, g["seats"][seat], mv)
    if g["phase"] != "swap":
        return None
    decl = g["auction"]["declarer"]
    denom = g["auction"]["denom"]
    hand = sorted(g["hands"][decl])
    shown = list(g["shown"])
    snap = json.dumps(g)

    def value_of(take, give):
        gg = json.loads(snap)
        E.apply_swap(gg, decl, take, give)
        # The defender's Double intervenes before play; hold it OFF for every
        # candidate so the comparison is between swaps, not between the server
        # tier's Double answers to them (it declines every Double anyway).
        E.apply_double(gg, 1 - decl, False)
        return resolve(gg)

    cands = [{"take": None, "give": None, "v": value_of(None, None)}]
    for t in shown:
        for h in hand:
            cands.append({"take": t, "give": h, "v": value_of(t, h)})
    cur = B.choose_swap(g, decl)
    best = max(cands, key=lambda c: c["v"])
    pat = cands[0]["v"]
    cur_v = next(c["v"] for c in cands
                 if c["take"] == cur["take"] and c["give"] == cur["give"])
    return {"deal": m, "denom": denom, "level": g["auction"]["level"],
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
PROC.stdin.close()
