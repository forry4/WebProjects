"""EXPERT vs HARD, in the AUCTION only.

The instrument behind the numbers in `games/dissonance/CLAUDE.md`. It drives the
SHIPPED path -- the server builds the option list and the armed request exactly
as `main._ask_the_client` does, `bin/bidserve` answers it through the same
`wire::answer_auction` the browser entry calls, and the pick is the client's own
argmax rule -- so what it measures is the tier, not a second implementation of
it.

CRN-paired: every deal is played twice with the tiers swapped, so the deal
cancels and what is left is the bidding. Card play is the greedy server policy
on BOTH sides and the talon/swap are the server bot's, so the auction is the
only thing that differs -- an arena that also swapped the card play would be
measuring the wrong thing. The mirror (`hard hard`) must read exactly +0.0000,
and it is the first thing to run after touching this.

READ THE `per DEAL` NUMBER, not the per-round one: averaging a deal's two flips
cancels the seat effect as well as the cards. And read the ERROR BAR -- per-round
scores run sigma~26, so 750 paired deals only resolves about +-0.6, and the
first 300 of a run reported on their own said +1.71 where the full 750 said
+0.28.

    cargo build --release --features bridge --bin bidserve
    PYTHONPATH=. python3 games/dissonance/tools/auction_arena.py <mode> <k> <n> \
        [<tierA> <tierB> [<lo> <hi>]]

`lo`/`hi` window the deal indices so shards can run in parallel; each prints a
`SHARD {...}` line to pool afterwards. Each (tier, seat) gets its OWN `bidserve`
process: the `Solved` cache is keyed on the cards, and one process playing both
seats thrashes it.
"""
import collections, json, random, statistics, subprocess, sys
from games.dissonance import engine as E, bot as B

BIN = "rust-cores/dissonance-core/target/release/bidserve"
MODE = sys.argv[1] if len(sys.argv) > 1 else "classic"
K = sys.argv[2] if len(sys.argv) > 2 else "3"
N = int(sys.argv[3]) if len(sys.argv) > 3 else 60
TIER_A = sys.argv[4] if len(sys.argv) > 4 else "expert"
TIER_B = sys.argv[5] if len(sys.argv) > 5 else "hard"
LO = int(sys.argv[6]) if len(sys.argv) > 6 else 0
HI = int(sys.argv[7]) if len(sys.argv) > 7 else N

PROC = {}


def proc_for(tier, seat):
    if (tier, seat) not in PROC:
        PROC[(tier, seat)] = subprocess.Popen([BIN, K], stdin=subprocess.PIPE,
                                              stdout=subprocess.PIPE, text=True)
    return PROC[(tier, seat)]


def ask(g, seat, tier):
    opts = E.auction_payoff_options(g)
    if not opts:
        return None
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
    res = json.loads(p.stdout.readline())
    sums = res.get("sums")
    if not sums or len(sums) != len(opts):
        return None
    i = max(range(len(opts)), key=lambda j: sums[j])
    o = opts[i]
    mv = o.get("move")
    if o.get("decline") and not sums[i] > 0:
        mv = o["decline"]
    return mv


def play(m, tier_of):
    """One round. `tier_of[seat]` is the auction tier that seat bids with."""
    g = E.new_game(["a", "b"], random.Random(600000 + m), opener=m % 2, mode=MODE)
    guard = 0
    while g["phase"] not in ("play", "over") and guard < 40:
        guard += 1
        seat = E.turn_seat(g)
        mv = None
        if g["phase"] in ("auction", "declare", "kontra", "re", "double"):
            mv = ask(g, seat, tier_of[seat])
        if mv is None:
            kind, p = B.act(g, seat, random.Random(m))
            mv = ({"kind": "pass"} if p.get("pass")
                  else {"kind": "bid", **{a: b for a, b in p.items() if a != "pass"}}) \
                if kind == "bid" else (p if kind == "move"
                                       else ({"kind": "swap", **p} if kind == "swap" else p))
        E.apply_move(g, g["seats"][seat], mv)
    if g["phase"] != "play":
        return None, None
    while g["phase"] == "play":
        s = E.to_play(g)
        E.apply_play(g, s, B.choose_card(g, s))
    return g["result"], g["auction"]


rows = []
pairs = []            # one per DEAL: the two flips averaged, so the deal cancels
levels = collections.Counter()
opens = collections.Counter()
for m in range(LO, HI):
    both = []
    for flip in (0, 1):
        tier_of = {flip: TIER_A, 1 - flip: TIER_B}
        res, a = play(m, tier_of)
        if res is None:
            continue
        sc = res["scores"]
        a_seat = flip
        rows.append(sc[a_seat] - sc[1 - a_seat])
        both.append(sc[a_seat] - sc[1 - a_seat])
        if TIER_A != TIER_B:
            # the level A settled on when A was DECLARING
            if a["declarer"] == a_seat:
                levels[a.get("level") or a.get("value")] += 1
    if len(both) == 2:
        pairs.append(sum(both) / 2)
    if (m + 1) % 20 == 0:
        mu = statistics.mean(rows)
        print(f"  {m+1:4} deals  {TIER_A} - {TIER_B} = {mu:+.4f}", flush=True)

def _stat(x):
    return statistics.mean(x), statistics.pstdev(x) / (len(x) ** 0.5)


mu, sd = _stat(rows)
print(f"\n{MODE} k={K}: {TIER_A} - {TIER_B} = {mu:+.4f} +- {sd:.4f} "
      f"payoff/round over {len(rows)} paired rounds")
if pairs:
    # THE HEADLINE. Averaging a deal's two flips cancels the seat effect as
    # well as the cards, so this is the tighter of the two and the one to quote.
    pmu, psd = _stat(pairs)
    print(f"  per DEAL (flips averaged): {pmu:+.4f} +- {psd:.4f} over {len(pairs)} deals")
if TIER_A != TIER_B:
    tot = sum(levels.values())
    print(f"  {TIER_A} declared {tot} of them at "
          + " ".join(f"{k}:{v}" for k, v in sorted(levels.items())))
print("SHARD " + json.dumps({"rows": rows, "pairs": pairs, "levels": {str(k): v for k, v in levels.items()}}))
for p in PROC.values():
    p.stdin.close()
