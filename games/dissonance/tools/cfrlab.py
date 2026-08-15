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
2. **The auction becomes a LEVEL LADDER PLUS A HOLD.** Denomination is
   abstracted out of the PAYOFF -- each bid is "in my best denomination" -- but
   NOT out of the auction's shape, because a plain ladder is not a defensible
   model of this auction. **28.6% of Expert's decisions are same-level overtakes
   in a higher-ranked denomination**, and a first cut of this harness mapped
   them to "+1 rung", which silently rewrote more than a quarter of the very
   behaviour it was fitting. They are now their own action, `HOLD`, and the
   count of consecutive holds is part of the state. The bound is EXACT rather
   than a guess: overtaking requires a strictly higher rank out of 5
   denominations, so at most 4 holds can follow a bid at a given level.
   What remains abstracted is `DENOM_RULE = "used"`, classic's per-player
   forever-ban -- each seat really burns a denomination per bid, so a real climb
   runs out of suits where this one does not, which makes the abstract game
   MORE permissive. The suits are measured symmetric (evenness 0.943), which is
   what makes pricing every seat at its best denomination defensible.
3. **The leaf is the POINTS solve plus payoff arithmetic**, i.e. exactly the
   approximation the shipped tier makes, measured at 93.3% agreement with
   `solve_contract` with the only gap being the adaptive Null threat.

    cargo build --release --features bridge --bin bidserve
    # solve the abstraction and report its shape (deals ~0.5s each)
    PYTHONPATH=. python -m games.dissonance.tools.cfrlab 2000 200000
    # the CONTROL arm: shipped Expert on the same seeds, ~25s a deal, shard it
    for i in 0 1 2 3; do python -m ...cfrlab expert 440 $i 4 & done; wait
    # PRICE the difference: exact best response against Expert's fitted policy
    PYTHONPATH=. python -m games.dissonance.tools.cfrlab br 200000

Env: `CFR_CKPT` for the deal cache, `CFR_EXPERT_CKPT` for the control arm's
(sharded, one file per shard). Both resume.
"""
import json
import math
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
#: Consecutive same-level overtakes. EXACT, not a truncation: an overtake must
#: name a strictly higher-ranked denomination and there are `NOTRUMP + 1` = 5 of
#: them, so at most 4 can follow the bid that set the level.
HOLDCAP = E.NOTRUMP
HOLD = 0          # the abstract action; -1 is pass, >=1 is "raise to that level"

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


def actions(level, holds):
    """Legal abstract actions from a state. `level == 0` is the forced opening.

    Pass concedes the standing bid; HOLD overtakes it at the same level in a
    higher-ranked denomination; anything else raises to that level. The opener
    can do neither of the first two (`OPENER_MAY_PASS` is off in classic, and
    there is nothing standing to overtake).
    """
    if level == 0:
        return list(range(1, MAXL + 1))
    acts = [-1]
    if holds < HOLDCAP:
        acts.append(HOLD)
    return acts + list(range(level + 1, MAXL + 1))


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
    # EVERY AUCTION DECISION, in the abstraction's own vocabulary, so the policy
    # a best response is computed against is Expert's OWN behaviour rather than
    # a guess at it. `flat` counts the same-level overtakes; the first cut of
    # this harness had no HOLD action and mapped them to "+1 rung", which turned
    # out to rewrite 28.6% of the decisions it was fitting -- so the counter
    # stays, as the check that the abstraction still covers what Expert does.
    dec, flat = [], 0
    prev, holds = 0, 0
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
            standing = g["auction"]["level"]
            mv = bid(g, seat)
            if mv is None:
                return None
            if g["phase"] == "auction":
                if mv["kind"] != "bid":
                    dec.append([seat, standing, prev, holds, -1])
                elif mv["level"] == standing:
                    dec.append([seat, standing, prev, holds, HOLD])
                    flat, holds = flat + 1, holds + 1
                else:
                    dec.append([seat, standing, prev, holds, mv["level"]])
                    prev, holds = standing, 0
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
    return {"level": level, "decl": decl, "v": v, "dec": dec, "flat": flat}


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

    def walk(self, rec, level, prev, holds, to_act, me, rng):
        """External-sampling MCCFR. Returns the value to `me`.

        THE STATE IS THE WHOLE HISTORY, and that is what makes the exact best
        response in `best_response` possible: `(level, prev, holds, to_act)`
        determines every legal action, every child and every leaf, so two
        different auctions that reach it are interchangeable from here on.
        There is also no separate `holder` -- every non-passing action hands the
        turn over, so the standing bid always belongs to the seat NOT to act.
        """
        holder = 1 - to_act if level else None
        acts = actions(level, holds)
        # `prev` is in the infoset because it prices the standing contract's
        # jump: conceding is worth different amounts at the same level depending
        # on how the ladder got there, and the whole auction is public.
        key = (rec["b"][to_act], level, prev, holds)
        sig = self.strategy(key, acts)

        def child(a):
            if a == -1:
                return leaf(rec, level, prev, holder) * (1 if holder == me else -1)
            if a == HOLD:
                return self.walk(rec, level, prev, holds + 1, 1 - to_act, me, rng)
            return self.walk(rec, a, level, 0, 1 - to_act, me, rng)

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
            return child(pick)
        # OUR node: evaluate every action, regret-match on the difference.
        vals, node = {}, 0.0
        for a in acts:
            vals[a] = child(a)
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


def states():
    """Every reachable auction state, children BEFORE parents.

    `(level, prev, holds, actor)`. A raise strictly increases `level`, a HOLD
    strictly increases `holds` at the same level, and nothing else moves -- so
    ordering by `(-level, -holds)` puts every child ahead of its parent and one
    linear pass suffices. Roughly 400 states, which is why the best response
    below is EXACT rather than another sampled estimate: the earlier draft
    enumerated HISTORIES and drowned (65k of them once HOLD existed), but the
    history beyond this tuple changes nothing that follows it.
    """
    out = []
    for level in range(MAXL, 0, -1):
        for holds in range(HOLDCAP, -1, -1):
            for prev in range(level):
                for actor in (0, 1):
                    out.append((level, prev, holds, actor))
    return out


def best_response(recs, pol, br_seat):
    """EXACT best response for `br_seat` against `pol`, in payoff points a deal.

    The poker-standard measure, and the reason it is worth the machinery: two
    self-play profiles of a symmetric zero-sum game cannot be ranked against
    each other -- every seat has EV 0 by construction -- so "the shapes differ"
    stays an observation until somebody prices what the difference is WORTH.

    Two passes. Backward for the values, and a forward reach pass folded into
    it: the best-responder's OWN probabilities are excluded from the reach,
    which is the standard trick that makes the maximisation separable. The
    choice is made ONCE PER INFOSET across every deal that shares it -- choosing
    per deal would be a cheater's response that reads the cards it cannot see.
    """
    N = len(recs)
    st = states()

    # FORWARD: how likely is the opponent to let us reach each state, per deal.
    # Ordered parents-first, which is `st` reversed.
    reach = {(0, 0, 0, 0): [1.0] * N}
    for s in reversed(st):
        reach.setdefault(s, [0.0] * N)
    for level, prev, holds, actor in [(0, 0, 0, 0)] + list(reversed(st)):
        s = (level, prev, holds, actor)
        base = reach[s]
        if not any(base):
            continue
        acts = actions(level, holds)
        kids = {a: reach.setdefault(
            (level, prev, holds + 1, 1 - actor) if a == HOLD
            else (a, level, 0, 1 - actor), [0.0] * N)
            for a in acts if a != -1}
        if actor == br_seat:
            for tgt in kids.values():            # BR's own choice not weighted
                for i in range(N):
                    tgt[i] += base[i]
            continue
        for i, rc in enumerate(recs):
            if not base[i]:
                continue
            # ONE lookup per (state, deal): the backoff tally is reach-weighted,
            # so asking once per ACTION would count the same miss up to nine
            # times and make coverage look far worse than it is.
            sig = pol.at(rc["b"][actor], level, prev, holds, acts, base[i] / N)
            if not sig:
                continue
            for a, tgt in kids.items():
                if sig.get(a):
                    tgt[i] += base[i] * sig[a]

    # BACKWARD: the value to `br_seat` of standing at each state, per deal.
    val = {}
    for s in st:
        level, prev, holds, actor = s
        holder = 1 - actor
        sign = 1 if holder == br_seat else -1
        conc = [sign * leaf(rc, level, prev, holder) for rc in recs]
        acts = actions(level, holds)

        def kid(a):
            return val[(level, prev, holds + 1, 1 - actor)] if a == HOLD \
                else val[(a, level, 0, 1 - actor)]

        if actor == br_seat:
            grp = defaultdict(list)
            for i, rc in enumerate(recs):
                grp[rc["b"][actor]].append(i)
            v = [0.0] * N
            for _, idx in grp.items():
                opts = {a: (sum(reach[s][i] * conc[i] for i in idx) if a == -1
                            else sum(reach[s][i] * kid(a)[i] for i in idx))
                        for a in acts}
                pick = max(opts, key=lambda a: opts[a])
                src = conc if pick == -1 else kid(pick)
                for i in idx:
                    v[i] = src[i]
            val[s] = v
        else:
            v = list(conc)
            for i, rc in enumerate(recs):
                sig = pol.at(rc["b"][actor], level, prev, holds, acts)
                if not sig:
                    continue                     # wholly unseen: concede
                acc = sig.get(-1, 0.0) * conc[i]
                for a in acts:
                    if a != -1 and sig.get(a):
                        acc += sig[a] * kid(a)[i]
                v[i] = acc
            val[s] = v

    # The root: seat 0 opens and cannot pass.
    if br_seat == 0:
        grp = defaultdict(list)
        for i, rc in enumerate(recs):
            grp[rc["b"][0]].append(i)
        tot = 0.0
        for _, idx in grp.items():
            pick = max(range(1, MAXL + 1),
                       key=lambda a: sum(val[(a, 0, 0, 1)][i] for i in idx))
            tot += sum(val[(pick, 0, 0, 1)][i] for i in idx)
        return tot / N
    acts = actions(0, 0)
    tot = 0.0
    for i, rc in enumerate(recs):
        sig = pol.at(rc["b"][0], 0, 0, 0, acts)
        if sig:
            tot += sum(sig[a] * val[(a, 0, 0, 1)][i] for a in acts)
    return tot / N


class Policy:
    """A behaviour strategy, normalised over whatever is legal AT the state.

    Both callers go through this for the same reason. A raw count table has
    holes -- infosets the sampled bidder never reached -- and the first cut of
    this harness treated a hole as CONCEDING, which is the single most
    exploitable thing a policy can do: a best responder then bids high purely to
    steer into the holes, and the number it reports is mostly the sample size.
    So misses BACK OFF along the axes in order of how much they should matter
    (`prev`, then `holds`, then the hand bucket itself) and only the totally
    unseen concedes. Every lookup is renormalised over the legal set, because a
    pooled distribution can otherwise put mass on a HOLD that is illegal at the
    cap -- mass that would silently vanish and read as extra exploitability.
    """

    def __init__(self, table, backoff=True):
        self.t = table
        self.backoff = backoff
        self.hits = defaultdict(float)   # reach-weighted, by backoff tier
        self.pool = {}
        if not backoff:
            return
        for depth, drop in enumerate(((2,), (2, 3), (0, 2, 3)), start=1):
            acc = defaultdict(lambda: defaultdict(float))
            for k, v in table.items():
                kk = tuple(0 if i in drop else x for i, x in enumerate(k))
                for a, p in v.items():
                    acc[(depth,) + kk][a] += p
            self.pool.update(acc)

    def at(self, bucket, level, prev, holds, acts, w=1.0):
        k = (bucket, level, prev, holds)
        src = self.t.get(k)
        tier = 0
        if src is None and self.backoff:
            for depth, drop in enumerate(((2,), (2, 3), (0, 2, 3)), start=1):
                kk = tuple(0 if i in drop else x for i, x in enumerate(k))
                src = self.pool.get((depth,) + kk)
                if src:
                    tier = depth
                    break
        if src is None:
            self.hits[9] += w
            return None
        self.hits[tier] += w
        out = {a: src.get(a, 0.0) for a in acts}
        tot = sum(out.values())
        return {a: p / tot for a, p in out.items()} if tot > 0 else None


def fit_policy(rows):
    """Expert's auction as a table over the abstraction's own infosets."""
    cnt = defaultdict(lambda: defaultdict(float))
    for r in rows:
        for seat, level, prev, holds, a in r.get("dec", []):
            cnt[(r["bk"][seat], level, prev, holds)][a] += 1.0
    return Policy({k: {a: c / sum(v.values()) for a, c in v.items()}
                   for k, v in cnt.items()})


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


def jump_main(rate, iters, seed=1234):
    """`cfrlab jump RATE ITERS` -- re-solve under a different JUMP_SET_BONUS.

    A DESIGN knob, not a bot knob. The solve above says the equilibrium opens
    near 4 almost regardless of the hand, which is a flat and uninformative
    auction however well a bot plays it -- so the question is whether the
    SCORING can be moved to make the opening spread out and mean something.

    The jump bonus is the candidate because it rides inside the SET base:
    `-(N + 10 + rate x j + 5s)`. Its expected cost is `P(set) x rate x j`, so it
    is already strength-conditioned -- a weak hand goes down more often and pays
    it more often -- and the rate is the gain on that discrimination.

    NO NEW DEALS ARE NEEDED. `pts` and `duck` are properties of the deal, not of
    the scoring, so the whole cache re-prices under any terms. That is what
    makes sweeping a scoring rule affordable at all; the expensive arm is the
    Expert control, which this does not need.

    TWO DIFFERENT THINGS get reported and they are not the same knob:
    * **spread** -- how evenly the rungs get used at all, as the normalised
      entropy of the opening distribution (0 = every hand opens on one rung,
      1 = uniform over the ladder). This is "more evenly distributed".
    * **discrimination** -- how far the opening moves between the weakest and
      strongest bucket. An auction can be perfectly spread and still carry no
      information, if the spread is randomisation rather than strength.
    A scoring change is only worth making if it buys the second; the first
    without it is noise dressed as variety.
    """
    E.JUMP_SET_BONUS["classic"] = rate
    recs = [json.loads(x) for x in open(CKPT) if x.strip()]
    bucketise(recs)
    cfr = CFR(recs)
    rng = random.Random(seed)
    for _ in range(iters):
        rec = recs[rng.randrange(len(recs))]
        for me in (0, 1):
            cfr.walk(rec, 0, 0, 0, 0, me, rng)
    eqp = Policy({k: {a: max(x, 0.0) / sum(max(y, 0.0) for y in s.values())
                      for a, x in s.items()}
                  for k, s in cfr.S.items()
                  if sum(max(y, 0.0) for y in s.values()) > 0}, backoff=False)

    # The opening distribution, marginalised over the bucket distribution --
    # which is uniform by construction, the buckets being quantiles.
    acts = actions(0, 0)
    opn = {a: 0.0 for a in acts}
    per = {}
    for b in range(NBUCKET):
        s = eqp.at(b, 0, 0, 0, acts) or {a: 1 / len(acts) for a in acts}
        per[b] = sum(a * s[a] for a in acts)
        for a in acts:
            opn[a] += s[a] / NBUCKET
    ent = -sum(p * math.log(p) for p in opn.values() if p > 0) / math.log(len(acts))
    mean = sum(a * p for a, p in opn.items())
    sd = (sum(p * (a - mean) ** 2 for a, p in opn.items())) ** 0.5

    # And what the change COSTS elsewhere: a scoring knob moves the whole game,
    # so a spread bought by making every contract fail is not a win.
    settle, made, n = defaultdict(int), 0, 6000
    for _ in range(n):
        rec = recs[rng.randrange(len(recs))]
        level, prev, holds, to_act, holder = 0, 0, 0, 0, None
        while True:
            a = actions(level, holds)
            s = eqp.at(rec["b"][to_act], level, prev, holds, a) or \
                {x: 1 / len(a) for x in a}
            r, acc, pick = rng.random(), 0.0, a[-1]
            for x in a:
                acc += s[x]
                if r <= acc:
                    pick = x
                    break
            if pick == -1:
                break
            holder = to_act
            if pick == HOLD:
                holds, to_act = holds + 1, 1 - to_act
            else:
                level, prev, holds, to_act = pick, level, 0, 1 - to_act
        settle[level] += 1
        if leaf(rec, level, prev, holder) > 0:
            made += 1
    smean = sum(k * v for k, v in settle.items()) / n
    print(f"{rate:>4}{'' if seed == 1234 else chr(96+seed)} {ent:>8.3f} {sd:>7.2f} {mean:>7.2f} "
          f"{per[0]:>7.2f} {per[NBUCKET-1]:>7.2f} "
          f"{per[NBUCKET-1]-per[0]:>+8.2f} {smean:>8.2f} {100*made/n:>7.1f}% "
          f"| " + " ".join(f"{a}:{100*opn[a]:.0f}" for a in acts if opn[a] > .015),
          flush=True)


def load_expert():
    base = os.environ.get("CFR_EXPERT_CKPT")
    rows, seen = [], set()
    for p in [base] + [f"{base}.{i}" for i in range(16)]:
        if not p or not os.path.exists(p):
            continue
        for line in open(p):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("seed") not in seen:
                seen.add(r["seed"])
                rows.append(r)
    return rows


def br_main(iters):
    """`cfrlab br` -- price the difference, instead of describing it."""
    recs = [json.loads(x) for x in open(CKPT) if x.strip()]
    bucketise(recs)
    rows = [r for r in load_expert() if r.get("dec")]
    if not rows:
        raise SystemExit("no Expert rounds carry a decision log -- re-run "
                         "`cfrlab expert` with the instrumented build")
    for r in rows:
        i = r["seed"] - 800_000
        if not (0 <= i < len(recs)):
            raise SystemExit(f"seed {r['seed']} has no deal in {CKPT}")
        r["bk"] = recs[i]["b"]
    nd = sum(len(r["dec"]) for r in rows)
    flat = sum(r.get("flat", 0) for r in rows)
    pol = fit_policy(rows)
    print(f"  fitted Expert over {len(rows)} rounds / {nd} decisions, "
          f"{len(pol.t)} infosets")
    print(f"  same-level overtakes (the HOLD action): {flat} = "
          f"{100*flat/nd:.1f}% of decisions")

    cfr = CFR(recs)
    rng = random.Random(1234)
    for _ in range(iters):
        rec = recs[rng.randrange(len(recs))]
        for me in (0, 1):
            cfr.walk(rec, 0, 0, 0, 0, me, rng)
    eq = {}
    for key, s in cfr.S.items():
        tot = sum(max(x, 0.0) for x in s.values())
        if tot > 0:
            eq[key] = {a: max(x, 0.0) / tot for a, x in s.items()}

    print(f"\n=== EXPLOITABILITY (payoff points a deal, {len(recs)} deals) ===")
    print(f"  {'policy':>12} {'BR as seat 0':>13} {'BR as seat 1':>13} "
          f"{'exploitability':>15}")
    tally = {}
    for name, p in (("CFR equilib", Policy(eq, backoff=False)),
                    ("EXPERT", pol)):
        b0 = best_response(recs, p, 0)
        p.hits.clear()
        b1 = best_response(recs, p, 1)
        tally[name] = dict(p.hits)
        print(f"  {name:>12} {b0:>13.2f} {b1:>13.2f} {(b0 + b1) / 2:>15.2f}")

    # HOW MUCH OF THIS IS THE SAMPLE RATHER THAN THE BIDDER. A best responder
    # steers TOWARDS whatever the fit does not cover, so the honest question is
    # not "what fraction of infosets did Expert visit" but "what fraction of the
    # BR's own reach lands on a backed-off one" -- the second is the number that
    # can inflate the row above, and it is the first thing to check before
    # believing it.
    lbl = {0: "exact", 1: "pooled prev", 2: "+ pooled holds",
           3: "+ pooled bucket", 9: "UNSEEN (concedes)"}
    for name, h in tally.items():
        tot = sum(h.values()) or 1.0
        print(f"\n  {name} lookups along the best responder's reach: "
              + ", ".join(f"{lbl[k]} {100*h[k]/tot:.1f}%" for k in sorted(h)))

    # WHERE THE 9 POINTS ARE, which is the only part of this that turns into a
    # code change. Two cells per bucket, both at `holds = 0`: what the seat
    # OPENS at, and how readily it concedes a standing bid. Everything else in
    # the auction hangs off those.
    eqp = Policy(eq, backoff=False)
    print(f"\n  OPENING LEVEL and CONCESSION RATE, by hand bucket "
          f"(0 = weakest):")
    print(f"    {'bucket':>7} | {'opens EQ':>9} {'opens EXP':>10} | "
          f"{'pass@4 EQ':>10} {'pass@4 EXP':>11} | "
          f"{'pass@6 EQ':>10} {'pass@6 EXP':>11}")
    for b in range(NBUCKET):
        row = [f"    {b:>7} |"]
        for p in (eqp, pol):
            s = p.at(b, 0, 0, 0, actions(0, 0))
            row.append(f"{sum(a * q for a, q in s.items()):>9.2f}" if s
                       else f"{'--':>9}")
        row.append(" |")
        for lv in (4, 6):
            for p in (eqp, pol):
                acts = actions(lv, 0)
                s = p.at(b, lv, lv - 1, 0, acts)
                row.append(f"{100*s.get(-1, 0.0):>9.0f}%" if s
                           else f"{'--':>10}")
            row.append(" |")
        print(" ".join(row).rstrip(" |"))

    # SPLIT-HALF, which is the check that decides whether the Expert row is a
    # measurement or a sample size. Fitting on half the rounds roughly doubles
    # every hole the backoff has to cover, so if the two halves land near the
    # full fit the number is about the bidder; if they run well above it, the
    # best responder is eating the sample and more rounds are the only fix.
    rng2 = random.Random(99)
    sh = list(rows)
    rng2.shuffle(sh)
    print(f"\n  SPLIT-HALF (fit on half the rounds, same {len(recs)} deals):")
    for tag, half in (("first half", sh[:len(sh) // 2]),
                      ("second half", sh[len(sh) // 2:])):
        q = fit_policy(half)
        e = (best_response(recs, q, 0) + best_response(recs, q, 1)) / 2
        print(f"    {tag:>12} ({len(half)} rounds): exploitability {e:.2f}")
    print("\n  Exploitability is (BR0 + BR1)/2 -- for a zero-sum game whose "
          "value need\n  not be 0 by seat (the opener is FORCED to bid), that "
          "sum cancels the\n  positional term and leaves what a best responder "
          "gains. The CFR row is\n  the FLOOR this abstraction can reach, not "
          "zero: it is an average strategy\n  over finite iterations against a "
          "bucketed hand, so read the two rows as a\n  difference and never the "
          "Expert row on its own.")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "jump":
        return jump_main(int(sys.argv[2]),
                         int(sys.argv[3]) if len(sys.argv) > 3 else 200_000,
                         int(sys.argv[4]) if len(sys.argv) > 4 else 1234)
    if len(sys.argv) > 1 and sys.argv[1] == "hdr":
        return print(f"{'rate':>4} {'spread':>8} {'sd':>7} {'mean':>7} "
                     f"{'weakest':>7} {'strong':>7} {'discrim':>8} "
                     f"{'settled':>8} {'made':>8} | opening distribution %")
    if len(sys.argv) > 1 and sys.argv[1] == "br":
        return br_main(int(sys.argv[2]) if len(sys.argv) > 2 else 200_000)
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
            cfr.walk(rec, 0, 0, 0, 0, me, rng)
        if (i + 1) % max(1, iters // 5) == 0:
            print(f"  {i+1}/{iters} iterations", flush=True)

    # --- play the average strategy out and report the SHAPE ----------------
    settled, made, opening = defaultdict(list), 0, defaultdict(int)
    bybk = defaultdict(list)
    ev = []
    rounds = 20000
    for _ in range(rounds):
        rec = recs[rng.randrange(len(recs))]
        level, prev, holds, to_act, first = 0, 0, 0, 0, None
        holder = None
        while True:
            acts = actions(level, holds)
            key = (rec["b"][to_act], level, prev, holds)
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
            holder = to_act
            if pick == HOLD:
                holds, to_act = holds + 1, 1 - to_act
            else:
                level, prev, holds, to_act = pick, level, 0, 1 - to_act
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
