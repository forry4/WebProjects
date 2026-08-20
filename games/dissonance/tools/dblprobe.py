"""Is the Double decision priced from the RIGHT SIDE, and is it any good?

Drives real classic rounds to the `double` phase, asks the SHIPPED search
(`bin/bidserve` -> `wire::answer_auction`, the same body the browser calls), and
compares its answer against the GROUND TRUTH for that deal -- an exact
double-dummy resolve of the real cards under both the doubled and the undoubled
terms, which is the best any defender could possibly do.

Run:  PYTHONPATH=. python -m games.dissonance.tools.dblprobe 200
"""
import json
import os
import random
import subprocess
import sys

from games.dissonance import bot as B
from games.dissonance import engine as E
from games.dissonance import main as M

BIN = os.path.abspath("rust-cores/dissonance-core/target/release/bidserve")
K = int(os.environ.get("DIS_K", "8"))
#: The seat that acts at the double phase is the DEFENDER; `declarer` on the
#: request is what the server ships. `DIS_DECL_FIX=1` ships the real declarer
#: instead, which is the candidate fix.
FIX = os.environ.get("DIS_DECL_FIX") == "1"

_procs = {}


def proc(tag, seed=0):
    if tag not in _procs:
        _procs[tag] = subprocess.Popen(
            [BIN, str(K), "18", str(seed)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, text=True, bufsize=1)
    return _procs[tag]


#: THE TWO KNOBS main.py SHIPS ON A DOUBLE, and this probe was sending NEITHER
#: (found 2026-08-20) while its docstring said "exactly as main.py builds it".
#: So every number it has ever produced described a Double the server does not
#: play. Same shape as the three offline harnesses found scoring on a dead price
#: list, and the same fix: send what ships, and keep the control arm reachable.
#:
#:   DIS_BID_PRIOR=0    drop the belief prior (uniform world sampling)
#:   DIS_DBL_MARGIN=<x> re-dose or, at 0, remove the doubling threshold
#:
#: Both default to the shipped values, so the DEFAULT run is now the served
#: decision rather than an adjacent one.
PRIOR_ON = os.environ.get("DIS_BID_PRIOR", "1") not in ("", "0")
MARGIN = float(os.environ.get("DIS_DBL_MARGIN", str(M.DOUBLE_MARGIN.get("classic", 0.0))))


def ask(g, seat, opts):
    """The armed double request, exactly as main.py builds it."""
    auc = {"phase": g["phase"],
           "declarer": (g["auction"]["declarer"] if FIX else seat),
           "options": opts}
    if PRIOR_ON:
        prior = B.bid_prior_terms(g)
        if prior:
            auc["bid_prior"] = prior
    if MARGIN:
        auc["double_margin"] = MARGIN
    p = proc("dbl")
    p.stdin.write(json.dumps({"view": E.view_for(g, seat), "auction": auc}) + "\n")
    p.stdin.flush()
    res = json.loads(p.stdout.readline())
    return res.get("sums")


def truth(g, terms):
    """Exact double-dummy payoff of the REAL deal under `terms`, declarer-signed."""
    # `g["deal"]` is only written at `_start_play`, and the Double is decided
    # one phase BEFORE that -- so the position is read live off the game. The
    # swap has already happened, so these are the cards that will be played.
    p = proc("res")
    p.stdin.write(json.dumps({"resolve": {
        "hands": [sorted(h) for h in g["hands"]],
        "piles": [[list(x) for x in q] for q in g["piles"]],
        "trump": g["auction"]["denom"],
        "leader": g["auction"]["declarer"], "terms": terms}}) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline()).get("payoff")


def to_double(seed):
    """A real round driven with the server bot to the moment the Double is live."""
    g = E.new_game(["a", "b"], random.Random(seed), opener=seed % 2, mode="classic")
    for _ in range(60):
        if g["phase"] == "double":
            return g
        if g["phase"] == "over":
            return None
        seat = E.turn_seat(g)
        if seat is None:
            return None
        kind, p = B.act(g, seat, random.Random(seed))
        # `bot.act` returns (kind, payload); flatten exactly as main.py does.
        if kind == "move":
            mv = p
        elif kind == "swap":
            mv = {"kind": "swap", "take": p.get("take"), "give": p.get("give")}
        elif kind == "play":
            mv = {"kind": "play", "card": p}
        elif p.get("pass"):
            mv = {"kind": "pass"}
        else:
            mv = {"kind": "bid", "level": p["level"], "denom": p["denom"]}
        E.apply_move(g, g["seats"][seat], mv)
    return None


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    rows = []
    for s in range(n):
        g = to_double(600_000 + s)
        if g is None:
            continue
        defender = 1 - g["auction"]["declarer"]
        opts = E.auction_payoff_options(g)
        if len(opts) != 2:
            continue
        sums = ask(g, defender, opts)
        if not sums:
            continue
        # The client's own pick: highest sum wins (`ask` in auction_arena.py).
        pick = max(range(2), key=lambda i: sums[i])
        chose_double = bool(opts[pick]["move"]["on"])
        # GROUND TRUTH: what each branch really pays, declarer-signed.
        vals = [truth(g, {k: v for k, v in o.items()
                          if k not in ("move", "opp", "redeal")}
                      | {"declarer": g["auction"]["declarer"]}) for o in opts]
        on = next(i for i, o in enumerate(opts) if o["move"]["on"])
        off = 1 - on
        # The defender wants the DECLARER's payoff as low as possible.
        should_double = vals[on] < vals[off]
        rows.append({"level": g["auction"]["level"],
                     "jump": g["auction"].get("jump", 0),
                     "chose": chose_double, "should": should_double,
                     "gain": vals[off] - vals[on],
                     "made": vals[off] > 0, "sums": sums})
    m = len(rows)
    if not m:
        print("no rounds reached the double phase")
        return
    agree = sum(1 for r in rows if r["chose"] == r["should"])
    tp = sum(1 for r in rows if r["chose"] and r["should"])
    fp = sum(1 for r in rows if r["chose"] and not r["should"])
    fn = sum(1 for r in rows if not r["chose"] and r["should"])
    got = sum(r["gain"] for r in rows if r["chose"]) / m
    best = sum(max(0, r["gain"]) for r in rows if r["should"]) / m
    print(f"  arm: bid_prior {'ON' if PRIOR_ON else 'OFF'}, "
          f"double_margin {MARGIN:g}")
    print(f"\n=== {m} rounds at the double phase "
          f"(k={K}, declarer field = {'REAL DECLARER (fix)' if FIX else 'ACTING SEAT (shipped)'}) ===")
    print(f"  doubles taken            {sum(r['chose'] for r in rows):4d} "
          f"({100*sum(r['chose'] for r in rows)/m:.1f}%)")
    print(f"  doubles that SHOULD be   {sum(r['should'] for r in rows):4d} "
          f"({100*sum(r['should'] for r in rows)/m:.1f}%)")
    print(f"  agreement with truth     {agree:4d} ({100*agree/m:.1f}%)")
    print(f"  hit / false alarm / miss {tp} / {fp} / {fn}")
    print(f"  value captured           {got:+.2f} per round "
          f"of an available {best:+.2f}")
    made = [r for r in rows if r["made"]]
    fail = [r for r in rows if not r["made"]]
    print(f"  doubles MADE contracts   {sum(r['chose'] for r in made)}/{len(made)}"
          f" = {100*sum(r['chose'] for r in made)/max(1,len(made)):.1f}%")
    print(f"  doubles FAILED contracts {sum(r['chose'] for r in fail)}/{len(fail)}"
          f" = {100*sum(r['chose'] for r in fail)/max(1,len(fail)):.1f}%")


if __name__ == "__main__":
    main()
