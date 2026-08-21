"""Does the DENOMS blueprint get the bid it asks for -- and does it use its freedom?

    PYTHONPATH=. CFR_DENOMS=1 CFR_BP_TRACE=1 CFR_CKPT=<all-denom cache> \
        CFR_BP_ITERS=19000 N=200 python3 games/dissonance/tools/bpexpress.py

TWO QUESTIONS, AND THE SECOND IS THE ONE THAT BIT.

The 14-point measurement priced a policy inside the abstraction. Serving it
means resolving each abstract action to a REAL bid, and the abstraction's rank
ordering is not the engine's denomination ordering. If the blueprint is forced
off its first choice on most decisions, the thing that plays is not the thing
that was measured -- so this runs BEFORE any arena.

Measured (200 deals, 477 decisions, 19k-iteration solve on the 600-deal
all-denomination cache):

    first choice served    99.2%
    fell back down list     0.8%   (mean depth 0.01)
    UNEXPRESSIBLE           0.0%

The ordering disagreement is real but almost never BINDS, and the breakdown
says exactly why: it can only bite on a same-level overtake, which is 0.8% of
what the blueprint plays (4 of 477). A raise permits any rank, so `order[r]` is
always legal there.

AND THEN THE SECOND QUESTION ANSWERS ITSELF UNHELPFULLY. The rank the blueprint
NAMES is 0 -- its own best suit, exactly what the level-only abstraction forces
-- on **89.9%** of its bids. So the wide action space changes about one bid in
ten. That does not refute the 14-point exploitability gap; it locates it. The
gap is what a BEST RESPONDER extracts from a policy that cannot answer, not
what the wide policy does differently in ordinary play -- which is the caveat
`docs/ai-research-log.md` attaches to that number, here with a measurement
behind it. Expect an arena against Expert to read far below 14.
"""
import os, random, sys, time
sys.argv = ["cfrlab.py"]
sys.path.insert(0, "/home/user/forry4.github.io")
from games.dissonance import engine as E
from games.dissonance.tools import cfrlab as C

n = int(os.environ.get("N", "200"))
t0 = time.time()
C.load_blueprint()
print(f"  blueprint solved in {time.time()-t0:.0f}s  (DENOMS={C.DENOMS})", flush=True)

auctions = settled = fellback = 0
kinds = {"open": 0, "raise": 0, "same-level overtake": 0, "pass": 0}
ranks = {}   # the RANK the blueprint named -- 0 is "my best suit", i.e. what
             # the level-only abstraction would have been forced to play
for s in range(n):
    g = E.new_game(["a", "b"], random.Random(700_000 + s), opener=0, mode="classic")
    auctions += 1
    for _ in range(40):
        if g["phase"] != "auction":
            break
        seat = g["auction"]["to_act"]
        mv = C.blueprint_bid(g, seat)
        if mv is None:                      # abstraction cannot express it
            fellback += 1
            opts = E.auction_payoff_options(g)
            mv = max(opts, key=lambda o: o.get("value", 0))["move"]
        lvl0 = g["auction"]["level"]
        if mv["kind"] == "bid":
            kinds["open" if lvl0 == 0 else
                  ("same-level overtake" if mv["level"] == lvl0 else "raise")] += 1
            r = C.denom_order(g, seat).index(mv["denom"])
            ranks[r] = ranks.get(r, 0) + 1
        else:
            kinds["pass"] += 1
        if mv["kind"] == "bid":
            E.apply_bid(g, seat, mv["level"], mv["denom"])
        else:
            E.apply_pass(g, seat)
    if g["phase"] != "auction":
        settled += 1

h = C.BP_HITS
d = max(h["decisions"], 1)
print(f"  {auctions} auctions, {settled} settled, {h['decisions']} decisions")
print(f"    first choice served : {100*h['first_choice']/d:5.1f}%")
print(f"    fell back down list : {100*h['fell_back']/d:5.1f}%  "
      f"(mean depth {h['depth_sum']/max(h['served'],1):.2f})")
print(f"    UNEXPRESSIBLE       : {100*h['unexpressible']/d:5.1f}%  "
      f"(caller used the pricer: {fellback})")
print("  what the blueprint actually played:")
for k, v in kinds.items():
    print(f"    {k:<22} {100*v/max(sum(kinds.values()),1):5.1f}%  ({v})")
tot = max(sum(ranks.values()), 1)
print("  the RANK it named (0 = its own best suit = what level-only forces):")
for r in sorted(ranks):
    print(f"    rank {r}  {100*ranks[r]/tot:5.1f}%  ({ranks[r]})")
