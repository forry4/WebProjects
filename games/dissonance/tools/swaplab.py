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


def _skat_decl(g):
    return g["auction"]["declarer"]

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


SKAT = MODE == "skat"
#: THE PHASE THE SWAP LIVES IN. Classic's is `swap` and skat's is `talon` --
#: and skat's has to be LOOKED at first, since declining to look IS the Hand
#: announcement and a declarer who plays Hand never sees the talon at all.
SWAP_PHASE = "talon" if SKAT else "swap"


def _step(g, rng):
    seat = E.turn_seat(g)
    kind, p = B.act(g, seat, rng)
    mv = ({"kind": "pass"} if p.get("pass")
          else {"kind": "bid", **{a: b for a, b in p.items() if a != "pass"}}) \
        if kind == "bid" else (p if kind == "move"
                               else ({"kind": "swap", **p} if kind == "swap" else p))
    E.apply_move(g, g["seats"][seat], mv)


def one(m):
    """Drive one round to the swap; enumerate and resolve every candidate."""
    g = E.new_game(["a", "b"], random.Random(600000 + m), opener=m % 2, mode=MODE)
    rng = random.Random(m)
    guard = 0
    while g["phase"] not in (SWAP_PHASE, "play", "over") and guard < 40:
        guard += 1
        _step(g, rng)
    if g["phase"] != SWAP_PHASE:
        return None
    if SKAT:
        # Look before swapping. `talon` is one phase covering look / hand /
        # swap, so a round that has not looked is not yet AT the decision.
        if not g.get("looked"):
            E.apply_move(g, g["seats"][_skat_decl(g)], {"kind": "look"})
        decl = _skat_decl(g)
    else:
        decl = g["auction"]["declarer"]
    denom = g["auction"]["denom"]
    hand = sorted(g["hands"][decl])
    shown = list(g["shown"])
    snap = json.dumps(g)

    def value_of(take, give):
        gg = json.loads(snap)
        E.apply_swap(gg, decl, take, give)
        if SKAT:
            # SKAT'S TALON RESOLVES BEFORE THE GAME IS NAMED, which is the whole
            # reason classic's fitted policy could not simply be pointed at it.
            # So a candidate exchange has no contract to be priced against until
            # the declaration is made -- and the declaration is made FROM THE
            # POST-SWAP HAND, by the shipped `choose_declare`, which is exactly
            # how it happens at the table. Letting it respond is not a
            # contaminant: naming a better game IS part of what a good swap buys,
            # and a fit that held the declaration fixed would be measuring a
            # decision nobody makes.
            #
            # Kontra and Re are forced OFF for every candidate, the same reason
            # classic forces the Double off: the comparison is between SWAPS,
            # not between the tier's answers to the contracts they lead to.
            gd = 0
            while gg["phase"] in ("declare", "kontra", "re") and gd < 6:
                gd += 1
                if gg["phase"] == "declare":
                    E.apply_move(gg, gg["seats"][decl],
                                 {"kind": "declare", **B.choose_declare(gg, decl)})
                else:
                    E.apply_move(gg, gg["seats"][1 - decl],
                                 {"kind": gg["phase"], "on": False})
            if gg["phase"] != "play":
                return None
        else:
            # The defender's Double intervenes before play; hold it OFF for every
            # candidate so the comparison is between swaps, not between the server
            # tier's Double answers to them (it declines every Double anyway).
            E.apply_double(gg, 1 - decl, False)
        return resolve(gg)

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
    return {"deal": m, "denom": denom,
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
PROC.stdin.close()
