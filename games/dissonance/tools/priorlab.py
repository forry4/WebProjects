"""Does the belief prior pick BETTER CARDS? Per-decision regret against an oracle.

WHY THIS HARNESS EXISTS. The obvious way to judge a card-play change is a paired
arena, and for this change there is no affordable one: `bin/arena` plays rounds
with a fixed trump and NO auction, so the declarer's hand is not selected by
anything and the prior's whole premise is absent; `bin/cmatch` imposes a
contract on a random hand, which makes a tilt wrong rather than merely
unmeasurable. The only valid vehicle is the full auction-then-searching-play
pipeline, and that runs ~30-60s a deal against the ~6s the auction arena costs.

So this measures DECISIONS instead of rounds, which is the same trade
`CAMPAIGN.md`'s "89.5% of decisions are already exactly optimal" makes:

* **~13 samples a round instead of one payoff.** Per-deal payoff sigma is 15.8
  even CRN-paired, which is why 500-deal runs resolve nothing here.
* **Paired on the identical position** -- both variants answer the same
  question, so there is no deal luck left to cancel.
* **Checkpointed per DECISION**, so a container restart costs seconds.
* **The oracle is only paid for when the two variants DISAGREE.** When they pick
  the same card the regret difference is exactly zero whatever the position is
  worth, so the expensive solve is skipped -- which is most decisions.

WHAT IT IS AND IS NOT. Regret against a double-dummy oracle is a PROXY: the
oracle's card is what a cheater plays, and `CAMPAIGN.md` finds PIMC's residual
error is strategy fusion, where matching it is not even the goal. But it is
well aligned with THIS change's mechanism -- the claim is that the world sample
is mis-centred on the declarer, and a better-centred sample should choose the
truly-better card more often. It tests the mechanism, not the win.

    cargo build --release --features bridge --bin bidserve
    PYTHONPATH=. python -m games.dissonance.tools.priorlab 60

Env: `PRIORLAB_CKPT` to checkpoint, `DIS_K` worlds per search (default 8).
"""
import json
import os
import random
import statistics
import subprocess
import sys

from games.dissonance import bot as B
from games.dissonance import engine as E

BIN = os.path.abspath("rust-cores/dissonance-core/target/release/bidserve")
K = int(os.environ.get("DIS_K", "8"))
CKPT = os.environ.get("PRIORLAB_CKPT")

_PROC = {}


def proc(tag, seed=0):
    if tag not in _PROC:
        _PROC[tag] = subprocess.Popen([BIN, str(K), "18", str(seed)],
                                      stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, text=True, bufsize=1)
    return _PROC[tag]


def rpc(tag, payload, seed=0):
    p = proc(tag, seed)
    p.stdin.write(json.dumps(payload) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())


def bid(g, seat):
    """One Expert auction decision, through the shipped path.

    The AUCTION MUST BE REAL and it must be EXPERT'S. The prior's premise is
    that winning an auction selects a strong hand, and the tilt was re-fitted
    against Expert's bidding specifically -- the server bot maps strength onto a
    level monotonically and Expert does not, which is the mistake the per-level
    map already made once.
    """
    opts = E.auction_payoff_options(g)
    if not opts:
        return None
    auc = {"phase": g["phase"], "declarer": seat, "options": opts}
    if g["phase"] == "auction":
        s = E.auction_search_payload(g)
        if s:
            auc["search"] = s
        auc["swap"] = B.swap_policy_terms()
    r = rpc("auc", {"view": E.view_for(g, seat), "auction": auc})
    sums = r.get("sums")
    if not sums or len(sums) != len(opts):
        return None
    return opts[max(range(len(opts)), key=lambda j: sums[j])]["move"]


def to_play_phase(seed):
    """A round driven through a REAL Expert auction to the opening lead."""
    g = E.new_game(["a", "b"], random.Random(seed), opener=seed % 2, mode="classic")
    for _ in range(40):
        if g["phase"] == "play":
            return g
        if g["phase"] == "over":
            return None
        seat = E.turn_seat(g)
        if seat is None:
            return None
        if g["phase"] in ("auction", "double"):
            mv = bid(g, seat)
            if mv is None:
                return None
        elif g["phase"] == "swap":
            p = B.choose_swap(g, seat)
            mv = {"kind": "swap", "take": p.get("take"), "give": p.get("give")}
        else:
            return None
        E.apply_move(g, g["seats"][seat], mv)
    return None


def pick(g, seat, with_prior):
    """The card the shipped search chooses, with the prior on or off."""
    req = {"view": E.view_for(g, seat), "payoff": E.payoff_terms(g), "k": K}
    if with_prior:
        p = B.bid_prior_terms(g)
        if not p:
            return None
        req["bid_prior"] = p
    r = rpc("pick" if with_prior else "pick0", {"pick": req},
            seed=7 if with_prior else 7)
    moves, sums = r.get("moves"), r.get("sum")
    if not moves:
        return None
    return moves[max(range(len(moves)), key=lambda j: sums[j])]


def oracle(g):
    """Every legal card's EXACT value on the real deal, signed for the declarer."""
    d = g.get("deal")
    if not d:
        return None
    r = rpc("orc", {"rootvals": {
        "hands": d["hands"], "piles": d["piles"], "out": d["out"],
        "trump": d["trump"], "leader": d["leader"],
        "played": [c for _, c, _ in (g.get("history") or [])],
        "terms": E.payoff_terms(g),
    }})
    if r.get("error") or not r.get("moves"):
        return None
    # THE ORACLE MUST BE ANSWERING THE POSITION THE BOT WAS ASKED ABOUT. It
    # rebuilds the deal and replays every card, so an off-by-one in that replay
    # would return a different seat's legal moves and quietly score every row
    # against the wrong question -- and still look like a perfectly ordinary
    # number. Checked rather than assumed.
    seat = E.turn_seat(g)
    if r.get("to_play") != seat:
        raise SystemExit(f"oracle replayed to seat {r.get('to_play')}, "
                         f"engine says {seat} -- the replay has drifted")
    if sorted(r["moves"]) != sorted(E.legal_moves(g, seat)):
        raise SystemExit(f"oracle legal set {sorted(r['moves'])} != engine "
                         f"{sorted(E.legal_moves(g, seat))} -- positions differ")
    return dict(zip(r["moves"], r["vals"]))


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    ck = open(CKPT, "a", encoding="utf-8") if CKPT else None
    done = set()
    if CKPT and os.path.exists(CKPT):
        for line in open(CKPT, encoding="utf-8"):
            try:
                done.add(json.loads(line)["round"])
            except (json.JSONDecodeError, KeyError):
                pass
        print(f"  resumed {len(done)} rounds from {CKPT}", flush=True)

    rows = []
    for s in range(n):
        if s in done:
            continue
        g = to_play_phase(700_000 + s)
        if g is None:
            continue
        decl = g["auction"]["declarer"]
        out = []
        guard = 0
        while g["phase"] == "play" and guard < 40:
            guard += 1
            seat = E.turn_seat(g)
            if seat is None:
                break
            legal = E.legal_moves(g, seat)
            # Only the DEFENDER's decisions: the prior is evidence about the
            # DECLARER's hand, and the declarer already knows their own.
            if seat != decl and len(legal) > 1:
                a = pick(g, seat, False)
                b = pick(g, seat, True)
                if a is not None and b is not None and a != b:
                    # They disagree, so and only so is the oracle worth paying
                    # for -- an agreement contributes exactly 0 either way.
                    vals = oracle(g)
                    if vals and a in vals and b in vals:
                        sign = 1 if seat == decl else -1
                        best = max(sign * v for v in vals.values())
                        out.append({"trick": g["trick"],
                                    "off": best - sign * vals[a],
                                    "on": best - sign * vals[b]})
                E.apply_move(g, g["seats"][seat], {"kind": "play", "card": a or legal[0]})
                continue
            kind, card = B.act(g, seat, random.Random(s))
            if kind != "play":
                break
            E.apply_move(g, g["seats"][seat], {"kind": "play", "card": card})
        rows += out
        if ck:
            ck.write(json.dumps({"round": s, "rows": out}) + "\n")
            ck.flush()
        if out:
            print(f"  round {s}: {len(out)} disagreements", flush=True)

    if CKPT and os.path.exists(CKPT):
        rows = []
        for line in open(CKPT, encoding="utf-8"):
            try:
                rows += json.loads(line)["rows"]
            except (json.JSONDecodeError, KeyError):
                pass
    if not rows:
        print("\nno decisions where the two variants disagreed")
        return
    off = [r["off"] for r in rows]
    on = [r["on"] for r in rows]
    d = [a - b for a, b in zip(off, on)]
    se = 1.96 * statistics.stdev(d) / (len(d) ** 0.5) if len(d) > 1 else 0
    print(f"\n=== {len(rows)} DISAGREEING decisions (k={K}) ===")
    print(f"  mean regret, prior OFF: {statistics.mean(off):+.3f}")
    print(f"  mean regret, prior ON : {statistics.mean(on):+.3f}")
    print(f"  improvement           : {statistics.mean(d):+.3f} +- {se:.3f}"
          f"  ({'PRIOR BETTER' if statistics.mean(d) > 0 else 'prior worse'})")
    better = sum(1 for a, b in zip(off, on) if b < a)
    worse = sum(1 for a, b in zip(off, on) if b > a)
    print(f"  of the disagreements: prior BETTER {100*better/len(rows):.1f}%, "
          f"WORSE {100*worse/len(rows):.1f}%, tied {100*(len(rows)-better-worse)/len(rows):.1f}%")
    # BY TRICK, because the tilt is a CONSTANT and the bias it corrects is not:
    # `decayprobe` measures the declarer's holding at the 0.769 percentile at
    # trick 1 and 0.554 by trick 12, so one dose must over-correct late even if
    # it is right early. If the damage concentrates in the late tricks, that is
    # the shape to look for -- and it is the same mistake the per-level map made.
    print(f"\n  {'trick':>6} {'n':>4} {'off':>7} {'on':>7} {'improvement':>12}")
    for lo, hi, lbl in ((0, 3, "1-4"), (4, 7, "5-8"), (8, 12, "9-13")):
        sel = [r for r in rows if lo <= r["trick"] <= hi]
        if not sel:
            continue
        o = statistics.mean(r["off"] for r in sel)
        n_ = statistics.mean(r["on"] for r in sel)
        print(f"  {lbl:>6} {len(sel):>4} {o:>7.2f} {n_:>7.2f} {o - n_:>+12.2f}")


if __name__ == "__main__":
    main()
