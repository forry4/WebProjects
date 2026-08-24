"""HOW a tier bids, not how much it wins -- the companion to `auction_arena.py`.

The arena answers "is Expert stronger". This answers "what does Expert actually
DO differently", which is the question a strength number cannot: two tiers can
score the same and bid nothing alike, and if the tree is not reaching the lines
it was built for then the wash is a bug rather than a ceiling.

SELF-PLAY, one tier on BOTH seats, over the same deals for each tier. That is
deliberate and it is not the arena's shape: head-to-head tells you how a tier
does against a specific opponent, while a style profile wants the auction that
tier would have with itself. The deals are keyed by index, so `hard` and
`expert` see the identical cards and every distribution below is paired.

What it profiles, in the order the questions get asked:

* the OPENING level, and whether the opener opens LIGHT -- bucketed by what the
  hand is actually worth, which is Hard's own myopic best price at the opening
  node (a number this harness gets for free, since it asks Hard the same
  question on the same deal);
* THE CAP LINE -- open low, let them overtake, pass, and hold the auction at
  the raise cap. `MAX_RAISE` is 2, so an opening at 1 holds the responder to 3
  on their turn; this counts how often each tier plays it and where those
  auctions settle;
* what the opener does WHEN OVERTAKEN -- pass or re-enter, the measurement that
  motivated the tier (shipped Hard passed in 30% of 43 level-1 openings);
* where the auction SETTLES, who declares, and whether the contract is made --
  because opening lighter is only good if it does not simply hand the deal over.

    cargo build --release --features bridge --bin bidserve
    PYTHONPATH=. python3 games/dissonance/tools/auction_style.py <mode> <k> <n> \\
        [<lo> <hi>]

Shards by deal-index window like the arena, and prints one `STYLE {...}` line
per tier to pool afterwards.
"""

import collections
import json
import random
import subprocess
import sys

from games.dissonance import engine as E, bot as B

BIN = "rust-cores/dissonance-core/target/release/bidserve"
MODE = sys.argv[1] if len(sys.argv) > 1 else "classic"
K = sys.argv[2] if len(sys.argv) > 2 else "3"
N = int(sys.argv[3]) if len(sys.argv) > 3 else 60
LO = int(sys.argv[4]) if len(sys.argv) > 4 else 0
HI = int(sys.argv[5]) if len(sys.argv) > 5 else N
TIERS = ("hard", "expert")

PROC = {}


def proc_for(tier, seat):
    """One process per (tier, seat): the `Solved` cache is keyed on the cards,
    and a single process playing both seats thrashes it."""
    if (tier, seat) not in PROC:
        PROC[(tier, seat)] = subprocess.Popen([BIN, K], stdin=subprocess.PIPE,
                                              stdout=subprocess.PIPE, text=True)
    return PROC[(tier, seat)]


def ask(g, seat, tier):
    """The armed request, the shipped answer, and the client's own pick rule.

    Returns `(move, sums, options)` so the caller can read the VALUES as well as
    the choice -- what a tier thought the alternatives were worth is most of the
    style story.
    """
    opts = E.auction_payoff_options(g)
    if not opts:
        return None, None, None
    auc = {"phase": g["phase"],
           "declarer": (g["auction"]["declarer"] if g["phase"] in ("kontra", "re") else seat),
           "options": opts}
    if tier == "expert" and g["phase"] == "auction":
        s = E.auction_search_payload(g)
        if s:
            auc["search"] = s
    p = proc_for(tier, seat)
    p.stdin.write(json.dumps({"view": E.view_for(g, seat), "auction": auc}) + "\n")
    p.stdin.flush()
    sums = json.loads(p.stdout.readline()).get("sums")
    if not sums or len(sums) != len(opts):
        return None, None, None
    i = max(range(len(opts)), key=lambda j: sums[j])
    mv = opts[i].get("move")
    if opts[i].get("decline") and not sums[i] > 0:
        mv = opts[i]["decline"]
    return mv, sums, opts


def _server_move(g, seat, rng):
    kind, p = B.act(g, seat, rng)
    if kind == "bid":
        return ({"kind": "pass"} if p.get("pass")
                else {"kind": "bid", **{a: b for a, b in p.items() if a != "pass"}})
    if kind == "move":
        return p
    if kind == "swap":
        return {"kind": "swap", **p}
    return p


def one(m, tier):
    """One self-played round, with the whole auction recorded."""
    g = E.new_game(["a", "b"], random.Random(600000 + m), opener=m % 2, mode=MODE)
    opener = E.turn_seat(g)
    rec = {"opener": opener, "acts": [], "quality": None, "greedy_open": None}
    guard = 0
    while g["phase"] not in ("play", "over") and guard < 40:
        guard += 1
        seat = E.turn_seat(g)
        phase = g["phase"]
        mv = None
        if phase in ("auction", "declare", "kontra", "re", "double"):
            mv, sums, opts = ask(g, seat, tier)
            if mv is not None and phase == "auction":
                # HAND QUALITY, and it must be the SAME yardstick in both runs
                # or "opens lighter" is unreadable -- Expert's own sums are TREE
                # values on a different scale, so reading quality off whichever
                # tier is playing would compare two rulers. So HARD is asked at
                # the opening node in both runs: its myopic best price is what
                # the cards are worth taken at face value, before any model of
                # the opponent, and Expert's opening is then measured as a
                # departure from it. The extra request is nearly free -- it is
                # the same hand, so it hits that process's cache all round.
                if rec["quality"] is None:
                    _, hsums, hopts = ask(g, seat, "hard")
                    if hsums:
                        bids = [(s, o["move"]) for s, o in zip(hsums, hopts)
                                if o["move"]["kind"] == "bid"]
                        if bids:
                            best = max(bids, key=lambda x: x[0])
                            rec["quality"] = round(best[0] / max(1, int(K)), 2)
                            rec["greedy_open"] = best[1].get("level") or best[1].get("value")
                rec["acts"].append({"seat": seat, "mv": mv})
        if mv is None:
            mv = _server_move(g, seat, random.Random(m))
        E.apply_move(g, g["seats"][seat], mv)
    if g["phase"] != "play":
        return None                       # a skat pass-out: no round to profile
    while g["phase"] == "play":
        s = E.to_play(g)
        E.apply_play(g, s, B.choose_card(g, s))
    a, r = g["auction"], g["result"]
    # The SCORES matter as much as the shape: capping the opponent at 3 instead
    # of 5 and being left in a level-1 contract are the same play seen from two
    # ends, and only the payoff says which one happened.
    rec.update(level=a["level"] or a["value"], denom=a["denom"], declarer=a["declarer"],
               made=bool(r["made"]), null=bool(r["null"]),
               pts=r["declarer_pts"], target=r["target"], scores=list(r["scores"]))
    return rec


out = {t: [] for t in TIERS}
for m in range(LO, HI):
    for t in TIERS:
        rec = one(m, t)
        if rec:
            rec["deal"] = m
            out[t].append(rec)
    if (m + 1) % 10 == 0:
        print(f"  {m + 1} deals", flush=True)

for t in TIERS:
    print(f"STYLE {t} " + json.dumps(out[t]))
for p in PROC.values():
    p.stdin.close()
