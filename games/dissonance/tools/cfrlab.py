"""EQUILIBRIUM bidding for classic, by CFR over an abstracted auction.

THE QUESTION THIS EXISTS TO ANSWER, which self-play structurally cannot.
`CLAUDE.md` records it as open: two Experts bid each other to a settled mean of
~4.95 and 41% of contracts FAIL, and "whether that is correct (the payoff
asymmetry may reward it) or a shared blind spot is UNRESOLVED and this run
cannot tell them apart". A mirror cannot diagnose itself -- both seats share
every bias. An equilibrium solve can, because it is not a self-play fixed point
of one bot's habits but of the GAME.

WHY THE AUCTION AND NOT THE CARD PLAY. Poker's toolkit is abstraction + CFR, and
Dissonance is the same class as heads-up poker (two-player zero-sum imperfect
information). The card play is far too big to abstract usefully; THE AUCTION IS
TINY -- a handful of bids over a ten-rung ladder -- and its leaves can be priced
by the exact solver we already have. That asymmetry is what makes this tractable
at all.

THE THREE ABSTRACTIONS, stated because they are the difference between this and
the real game:

1. **The hand becomes a BUCKET**, and it must be information-legal or the answer
   is a cheater's. So the bucket is a quantile of `bot.hand_strength` over the
   seat's best denomination -- computed from the eleven cards a seat may name,
   never from the solve (which depends on the opponent's cards and is therefore
   not private information).
2. **The auction becomes a LEVEL LADDER.** Denomination is abstracted away: each
   bid is "raise to L in my best denomination", and TWO real rules go with it.
   Classic's `DENOM_RULE` is `"used"` -- a per-player forever-ban, so each seat
   burns a denomination per bid and a real climb runs out of suits where this
   one does not. And a real overtake may stand at the SAME level in a
   higher-ranked denomination, which this ladder cannot express (every action
   strictly raises). Both make the abstract game MORE permissive than the real
   one, so read a high settled level as an upper bound. The suits are measured
   symmetric (evenness 0.943), which is what makes the abstraction defensible.
3. **The leaf is the POINTS solve plus payoff arithmetic**, i.e. exactly the
   approximation the shipped tier makes, measured at 93.3% agreement with
   `solve_contract` with the only gap being the adaptive Null threat.

    cargo build --release --features bridge --bin bidserve
    PYTHONPATH=. python -m games.dissonance.tools.cfrlab 400 200000

Env: `CFR_CKPT` to checkpoint the (expensive) deal sampling and resume.
"""
import json
import os
import random
import statistics
import subprocess
import sys
from collections import defaultdict

from games.dissonance import bot as B
from games.dissonance import engine as E

BIN = os.path.abspath("rust-cores/dissonance-core/target/release/bidserve")
CKPT = os.environ.get("CFR_CKPT")
#: The ladder the abstract game bids on. Nothing in 800 deals of Expert
#: self-play ever settled above 8, so rungs above it are tree with no data.
MAXL = 8
NBUCKET = 8

_P = None


def rpc(payload):
    global _P
    if _P is None:
        _P = subprocess.Popen([BIN, "8", "18", "0"], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True, bufsize=1)
    _P.stdin.write(json.dumps(payload) + "\n")
    _P.stdin.flush()
    return json.loads(_P.stdout.readline())


def sample_deal(seed):
    """One deal, reduced to what the abstract game needs.

    Per seat: the information-legal strength of its best denomination (the
    bucketing feature), and -- for the leaf -- the points it could guarantee
    declaring in that denomination plus whether it could duck to the
    consolation there.
    """
    g = E.new_game(["a", "b"], random.Random(seed), opener=0, mode="classic")
    rec = {"str": [0.0, 0.0], "pts": [0, 0], "duck": [False, False]}
    for seat in (0, 1):
        best_d, best_s = 0, -1e9
        for d in range(E.NOTRUMP + 1):
            s = B.hand_strength(g, seat, d)
            if s > best_s:
                best_d, best_s = d, s
        rec["str"][seat] = best_s
        r = rpc({"resolve": {
            "hands": [sorted(h) for h in g["hands"]],
            "piles": [[list(x) for x in q] for q in g["piles"]],
            "trump": best_d, "leader": seat,
            # A throwaway contract: only `pts` and `duck` are read, and both are
            # properties of the DEAL rather than of the terms.
            "terms": {"declarer": seat, "target": 1, "make": 1, "set_base": 1,
                      "short": 1, "over": 1, "null": 20},
        }})
        rec["pts"][seat] = r.get("pts", 0)
        rec["duck"][seat] = bool(r.get("duck"))
    return rec


def collect(n):
    recs = []
    if CKPT and os.path.exists(CKPT):
        for line in open(CKPT):
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        print(f"  resumed {len(recs)} deals from {CKPT}", flush=True)
    ck = open(CKPT, "a") if CKPT else None
    while len(recs) < n:
        rec = sample_deal(800_000 + len(recs))
        recs.append(rec)
        if ck:
            ck.write(json.dumps(rec) + "\n")
            ck.flush()
        if len(recs) % 25 == 0:
            print(f"  {len(recs)}/{n} deals", flush=True)
    return recs[:n]


def bucketise(recs):
    """Quantile buckets over the strength of each seat's best denomination."""
    allv = sorted(s for r in recs for s in r["str"])
    cuts = [allv[int((i + 1) * len(allv) / NBUCKET)] for i in range(NBUCKET - 1)]

    def b(x):
        i = 0
        while i < len(cuts) and x >= cuts[i]:
            i += 1
        return i
    for r in recs:
        r["b"] = [b(r["str"][0]), b(r["str"][1])]
    return cuts


def leaf(rec, level, prev, declarer):
    """What the settled contract pays, DECLARER-SIGNED.

    `payoff_terms`' own arithmetic on the shipped scoring. THE JUMP IS THE FINAL
    BID'S RISE, `level - prev`, and getting that wrong is not a rounding error:
    the classic set base is `(N + 10 + 3j) x D`, so pricing every contract as if
    it were reached in one leap from zero charges the maximum jump penalty on a
    climb that earned none. It taxes exactly the deep auctions this harness
    exists to judge, and it does so in the direction that would manufacture the
    answer "the equilibrium bids lower than Expert". Under the v2 rule an
    OPENING's rise is its whole level, which `prev = 0` gives for free.
    """
    terms = E._terms_for("classic", 0, level, jump=level - prev)
    scored = not rec["duck"][declarer]
    return E.payoff(terms, rec["pts"][declarer], scored)


def actions(level, holder, to_act):
    """Legal abstract actions: pass (never as the opener), or raise."""
    acts = []
    if holder is not None:
        acts.append(-1)                      # pass = concede the standing bid
    acts += list(range(level + 1, MAXL + 1))
    return acts


def bid(g, seat):
    """One SHIPPED Expert auction decision, through the served path."""
    opts = E.auction_payoff_options(g)
    if not opts:
        return None
    auc = {"phase": g["phase"], "declarer": seat, "options": opts}
    if g["phase"] == "auction":
        s = E.auction_search_payload(g)
        if s:
            auc["search"] = s
        auc["swap"] = B.swap_policy_terms()
    r = rpc({"view": E.view_for(g, seat), "auction": auc})
    sums = r.get("sums")
    if not sums or len(sums) != len(opts):
        return None
    return opts[max(range(len(opts)), key=lambda j: sums[j])]["move"]


def expert_round(seed):
    """What Expert's auction settles at on one deal, scored by the SAME leaf.

    THIS IS THE CONTROL THE HEADLINE NUMBER NEEDS. The equilibrium's make rate
    is computed under the points proxy at exact play; Expert's recorded 58.9% is
    real PIMC card play. Those are two resolvers, and comparing across them
    would credit the bidder for the resolver's difference. Here the deal, the
    solver and the scoring are identical and the ONLY thing that varies is who
    bids -- so the gap that survives is the bidding's.

    The contract is resolved in the denomination Expert actually named, not in
    the seat's best one: reusing the bucketing feature's denomination here would
    score Expert's contract on somebody else's trump suit.
    """
    g = E.new_game(["a", "b"], random.Random(seed), opener=0, mode="classic")
    for _ in range(40):
        if g["phase"] not in ("auction", "double", "swap"):
            break
        seat = E.turn_seat(g)
        if seat is None:
            return None
        if g["phase"] == "swap":
            p = B.choose_swap(g, seat)
            mv = {"kind": "swap", "take": p.get("take"), "give": p.get("give")}
        else:
            mv = bid(g, seat)
            if mv is None:
                return None
        E.apply_move(g, g["seats"][seat], mv)
    a = g.get("auction") or {}
    decl, level = a.get("declarer"), a.get("level", 0)
    if decl is None or not level:
        return None
    r = rpc({"resolve": {
        "hands": [sorted(h) for h in g["hands"]],
        "piles": [[list(x) for x in q] for q in g["piles"]],
        "trump": a["denom"], "leader": decl,
        "terms": {"declarer": decl, "target": 1, "make": 1, "set_base": 1,
                  "short": 1, "over": 1, "null": 20},
    }})
    terms = E._terms_for("classic", 0, level, jump=a.get("jump", level))
    v = E.payoff(terms, r.get("pts", 0), not bool(r.get("duck")))
    return {"level": level, "decl": decl, "v": v}


class CFR:
    def __init__(self, recs):
        self.recs = recs
        self.R = defaultdict(lambda: defaultdict(float))   # cumulative regret
        self.S = defaultdict(lambda: defaultdict(float))   # cumulative strategy

    def strategy(self, key, acts):
        r = self.R[key]
        pos = {a: max(r[a], 0.0) for a in acts}
        tot = sum(pos.values())
        if tot > 0:
            return {a: pos[a] / tot for a in acts}
        return {a: 1.0 / len(acts) for a in acts}

    def walk(self, rec, level, prev, holder, to_act, me, rng, depth=0):
        """External-sampling MCCFR. Returns the value to `me`.

        The depth guard is a BACKSTOP, not an abstraction: every action strictly
        raises off a ladder of MAXL rungs, so the longest possible auction is
        MAXL raises and the guard cannot bind. It is here so a future edit that
        adds a non-raising action fails loudly at the recursion limit's edge
        rather than silently recursing.
        """
        if depth > MAXL:
            return leaf(rec, level, prev, holder) * (1 if holder == me else -1) \
                if holder is not None else 0.0
        acts = actions(level, holder, to_act)
        if not acts:
            return leaf(rec, level, prev, holder) * (1 if holder == me else -1)
        # The infoset: MY bucket, and the PUBLIC auction state. `prev` is in the
        # key because it prices the standing contract's jump, so conceding is
        # worth different amounts at the same level depending on how the ladder
        # got there -- and the whole auction is public, so a player legally
        # knows it. Bidding alternates, so "do I hold the standing bid" is
        # always False and is deliberately NOT in the key: a component that
        # never varies splits nothing and only makes the table look more
        # informed than it is.
        key = (rec["b"][to_act], level, prev)
        sig = self.strategy(key, acts)
        if to_act != me:
            # SAMPLE the opponent, and accumulate their average strategy.
            for a in acts:
                self.S[key][a] += sig[a]
            r, acc = rng.random(), 0.0
            pick = acts[-1]
            for a in acts:
                acc += sig[a]
                if r <= acc:
                    pick = a
                    break
            if pick == -1:
                return leaf(rec, level, prev, holder) * (1 if holder == me else -1)
            return self.walk(rec, pick, level, to_act, 1 - to_act, me, rng,
                             depth + 1)
        # OUR node: evaluate every action, regret-match on the difference.
        vals, node = {}, 0.0
        for a in acts:
            if a == -1:
                vals[a] = leaf(rec, level, prev, holder) * (1 if holder == me else -1)
            else:
                vals[a] = self.walk(rec, a, level, to_act, 1 - to_act, me, rng,
                                    depth + 1)
            node += sig[a] * vals[a]
        for a in acts:
            self.R[key][a] += vals[a] - node
        return node

    def average(self, key, acts):
        s = self.S[key]
        tot = sum(max(s[a], 0.0) for a in acts)
        if tot > 0:
            return {a: max(s[a], 0.0) / tot for a in acts}
        return {a: 1.0 / len(acts) for a in acts}


def expert_main(n, shard=0, nshard=1):
    """`cfrlab expert N [SHARD NSHARD]` -- the control arm, on the same seeds.

    SHARDED because this arm is ~25s a deal against the equilibrium's 0.5s: it
    runs the real k=8 search at every auction node, which is the point (a
    control that ran a cheaper search would be measuring the search, not the
    bidder). Four processes on four cores bring it to ~6s a deal. Each shard
    keeps its OWN checkpoint and the reporter reads them all, so a shard dying
    costs that shard's tail and nothing else.
    """
    ck_path = os.environ.get("CFR_EXPERT_CKPT")
    if ck_path and nshard > 1:
        ck_path = f"{ck_path}.{shard}"
    rows, done = [], set()
    if ck_path and os.path.exists(ck_path):
        for line in open(ck_path):
            try:
                r = json.loads(line)
                rows.append(r)
                done.add(r["seed"])
            except (json.JSONDecodeError, KeyError):
                pass
        print(f"  resumed {len(rows)} rounds", flush=True)
    ck = open(ck_path, "a") if ck_path else None
    for i in range(n):
        if i % nshard != shard:
            continue
        seed = 800_000 + i
        if seed in done:
            continue
        r = expert_round(seed)
        if r is None:
            continue
        r["seed"] = seed
        rows.append(r)
        if ck:
            ck.write(json.dumps(r) + "\n")
            ck.flush()
        if len(rows) % 25 == 0:
            print(f"  {len(rows)} rounds", flush=True)
    # REPORT OFF EVERY SHARD, not just this process's slice -- a per-shard
    # summary is a quarter of the sample and reads like the whole thing.
    if os.environ.get("CFR_EXPERT_CKPT"):
        rows, seen = [], set()
        base = os.environ["CFR_EXPERT_CKPT"]
        for p in [base] + [f"{base}.{i}" for i in range(16)]:
            if not os.path.exists(p):
                continue
            for line in open(p):
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("seed") not in seen:
                    seen.add(r["seed"])
                    rows.append(r)
    if not rows:
        print("no Expert rounds")
        return
    lv = defaultdict(list)
    for r in rows:
        lv[r["level"]].append(r["v"])
    tot = len(rows)
    made = sum(1 for r in rows if r["v"] > 0)
    p = made / tot
    ci = 196 * (p * (1 - p) / tot) ** 0.5
    print(f"\n=== EXPERT on the SAME {tot} deals, SAME leaf, undoubled ===")
    print(f"  settled mean {sum(k*len(v) for k, v in lv.items())/tot:.2f}   "
          f"made {100*p:.1f}% +-{ci:.1f}   "
          f"declarer EV {statistics.mean(r['v'] for r in rows):+.2f}")
    print("  settled: " + "  ".join(f"{k}:{100*len(v)/tot:.0f}%"
                                    for k, v in sorted(lv.items())))
    # THE SELECTION COLUMN, and the reason this table is worth more than the
    # headline. A bidder's job at level L is to pick the deals that make it, so
    # the yardstick is the level's UNCONDITIONAL make rate: land on it and the
    # bidding added nothing at all.
    print(f"\n  {'level':>6} {'n':>5} {'made':>7} {'declarer EV':>12}")
    for k in sorted(lv):
        v = lv[k]
        print(f"  {k:>6} {len(v):>5} "
              f"{100*sum(1 for x in v if x > 0)/len(v):>6.1f}% "
              f"{statistics.mean(v):>+12.2f}")

    # DOES THE LEVEL TRACK THE HAND? Joined against the equilibrium's own deal
    # cache by seed, so it is the SAME bucketing feature on the SAME deals --
    # which is the only way the two ladders are readable side by side. If the
    # declarer's bucket barely moves the settled level, the bidder is choosing
    # a rung on something other than its hand, and no amount of search at the
    # leaves fixes that.
    if CKPT and os.path.exists(CKPT):
        recs = [json.loads(x) for x in open(CKPT) if x.strip()]
        bucketise(recs)
        by = defaultdict(list)
        for r in rows:
            i = r["seed"] - 800_000
            if 0 <= i < len(recs):
                by[recs[i]["b"][r["decl"]]].append(r)
        if by:
            print(f"\n  SETTLED LEVEL BY THE DECLARER'S STRENGTH BUCKET "
                  f"(0 = weakest of {NBUCKET}):")
            print(f"    {'bucket':>7} {'n':>5} {'mean level':>11} {'made':>7}")
            for b in sorted(by):
                v = by[b]
                print(f"    {b:>7} {len(v):>5} "
                      f"{statistics.mean(x['level'] for x in v):>11.2f} "
                      f"{100*sum(1 for x in v if x['v'] > 0)/len(v):>6.1f}%")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "expert":
        return expert_main(int(sys.argv[2]) if len(sys.argv) > 2 else 300,
                           int(sys.argv[3]) if len(sys.argv) > 3 else 0,
                           int(sys.argv[4]) if len(sys.argv) > 4 else 1)
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    iters = int(sys.argv[2]) if len(sys.argv) > 2 else 100_000
    recs = collect(n)
    bucketise(recs)
    cfr = CFR(recs)
    rng = random.Random(1234)
    for i in range(iters):
        rec = recs[rng.randrange(len(recs))]
        for me in (0, 1):
            cfr.walk(rec, 0, 0, None, 0, me, rng)
        if (i + 1) % max(1, iters // 5) == 0:
            print(f"  {i+1}/{iters} iterations", flush=True)

    # --- play the average strategy out and report the SHAPE ----------------
    settled, made, opening = defaultdict(list), 0, defaultdict(int)
    bybk = defaultdict(list)
    ev = []
    rounds = 20000
    for _ in range(rounds):
        rec = recs[rng.randrange(len(recs))]
        level, prev, holder, to_act, first = 0, 0, None, 0, None
        for _ in range(MAXL + 1):
            acts = actions(level, holder, to_act)
            key = (rec["b"][to_act], level, prev)
            sig = cfr.average(key, acts)
            r, acc, pick = rng.random(), 0.0, acts[-1]
            for a in acts:
                acc += sig[a]
                if r <= acc:
                    pick = a
                    break
            if pick == -1:
                break
            if first is None:
                first = pick
            level, prev, holder, to_act = pick, level, to_act, 1 - to_act
        # The opener cannot pass, so every auction settles -- there is no
        # passed-out branch to report.
        v = leaf(rec, level, prev, holder)
        settled[level].append(v)
        opening[first] += 1
        ev.append(v)
        bybk[rec["b"][holder]].append((level, v))
        if v > 0:
            made += 1
    tot = sum(len(v) for v in settled.values())
    print(f"\n=== EQUILIBRIUM over {n} deals, {iters} iterations, "
          f"{NBUCKET} buckets ===")
    mean = sum(k * len(v) for k, v in settled.items()) / max(1, tot)
    omean = sum(k * v for k, v in opening.items()) / max(1, tot)
    print(f"  settled mean {mean:.2f}   made {100*made/tot:.1f}%   "
          f"declarer EV {statistics.mean(ev):+.2f}   contracts {tot}")
    print("  settled: " + "  ".join(f"{k}:{100*len(v)/tot:.0f}%"
                                    for k, v in sorted(settled.items())))
    print(f"  opening (mean {omean:.2f}): "
          + "  ".join(f"{k}:{100*v/tot:.0f}%"
                      for k, v in sorted(opening.items())))
    print(f"\n  {'level':>6} {'n':>6} {'made':>7} {'declarer EV':>12}")
    for k in sorted(settled):
        v = settled[k]
        print(f"  {k:>6} {len(v):>6} "
              f"{100*sum(1 for x in v if x > 0)/len(v):>6.1f}% "
              f"{statistics.mean(v):>+12.2f}")
    print(f"\n  SETTLED LEVEL BY THE DECLARER'S STRENGTH BUCKET "
          f"(0 = weakest of {NBUCKET}):")
    print(f"    {'bucket':>7} {'n':>6} {'mean level':>11} {'made':>7}")
    for b in sorted(bybk):
        v = bybk[b]
        print(f"    {b:>7} {len(v):>6} "
              f"{statistics.mean(x[0] for x in v):>11.2f} "
              f"{100*sum(1 for x in v if x[1] > 0)/len(v):>6.1f}%")

    print(f"\n  EXPERT SELF-PLAY, for comparison:")
    print(f"    settled mean 4.95   made 58.9%")
    print("    NB Expert's 58.9% is measured on REAL card play; this column is "
          "the\n    points proxy under exact play, so read the two as the same "
          "question\n    asked of different resolvers, not as one number.")

    # WHAT THE DEALS THEMSELVES SAY, independent of any strategy. If the
    # equilibrium and Expert both settle near 5, the interesting question is
    # what a contract at each rung is actually worth -- and that is a property
    # of the deal distribution, not of either bidder.
    # The two EV columns are the SAME contract reached two ways, because the
    # jump term makes that a real difference: a level opened in one leap is
    # taxed 3 x level on a set, one climbed a rung at a time is taxed 3.
    print(f"\n  THE LADDER ITSELF (best-denomination declarer, over {n} deals):")
    print(f"    {'level':>6} {'makes':>8} {'EV opened':>10} {'EV climbed':>11}")
    for lv in range(1, MAXL + 1):
        op = [leaf(r, lv, 0, s) for r in recs for s in (0, 1)]
        cl = [leaf(r, lv, lv - 1, s) for r in recs for s in (0, 1)]
        mk = 100 * sum(1 for v in op if v > 0) / len(op)
        print(f"    {lv:>6} {mk:>7.1f}% {statistics.mean(op):>+10.2f} "
              f"{statistics.mean(cl):>+11.2f}")


if __name__ == "__main__":
    main()
