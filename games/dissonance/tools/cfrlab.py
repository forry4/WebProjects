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
DCKPT = os.environ.get("CFR_DCKPT")
#: The ladder the abstract game bids on. Nothing in 800 deals of Expert
#: self-play ever settled above 8, so rungs above it are tree with no data.
MAXL = int(os.environ.get("CFR_MAXL", "8"))
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


def sample_deal_alldenoms(seed):
    """One deal, solved in EVERY denomination for both seats.

    The cache the suit-priced ladder needs. `pts`/`duck` become lists of five,
    ORDERED BY THE SEAT'S OWN `hand_strength` rather than by the solved result --
    which matters and is not fussiness. A seat picks its suit from what it can
    see; ordering by the true points would let the abstraction's declarer always
    find the genuinely best suit, which is a cheater's ladder and would flatter
    the mechanism being tested.
    """
    g = E.new_game(["a", "b"], random.Random(seed), opener=0, mode="classic")
    rec = {"str": [0.0, 0.0], "pts": [[], []], "duck": [[], []]}
    for seat in (0, 1):
        order = sorted(range(E.NOTRUMP + 1),
                       key=lambda d: -B.hand_strength(g, seat, d))
        rec["str"][seat] = B.hand_strength(g, seat, order[0])
        for d in order:
            r = rpc({"resolve": {
                "hands": [sorted(h) for h in g["hands"]],
                "piles": [[list(x) for x in q] for q in g["piles"]],
                "trump": d, "leader": seat,
                "terms": {"declarer": seat, "target": 1, "make": 1,
                          "set_base": 1, "short": 1, "over": 1, "null": 20},
            }})
            rec["pts"][seat].append(r.get("pts", 0))
            rec["duck"][seat].append(bool(r.get("duck")))
    return rec


def dcache_main(n):
    """`cfrlab dcache N` -- build the all-denomination deal cache."""
    recs = []
    if DCKPT and os.path.exists(DCKPT):
        for line in open(DCKPT):
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        print(f"  resumed {len(recs)} deals", flush=True)
    ck = open(DCKPT, "a")
    while len(recs) < n:
        recs.append(sample_deal_alldenoms(900_000 + len(recs)))
        ck.write(json.dumps(recs[-1]) + "\n")
        ck.flush()
        if len(recs) % 20 == 0:
            print(f"  {len(recs)}/{n} deals", flush=True)
    print(f"  {len(recs)} deals cached")


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


#: A scoring OVERRIDE for the design sweeps, empty in every other mode. `p`/`A`
#: reshape the made base (the engine hardcodes `level * level`, so it is the one
#: term a constant cannot reach); everything else is a module constant patched
#: in place. `_terms_for` returns a plain dict, so overriding after the fact
#: keeps the sweep out of the engine entirely.
CURVE = {}

#: Whether the solved auction includes the DOUBLE. Off for `br`, whose question
#: is Expert's bidding and which must not have its tree changed underneath it.
WITH_DOUBLE = False

#: THE TARGET PROFILE, stated as numbers so the sweep can be SEARCHED rather
#: than eyeballed. Both are over levels 1..MAXL.
#:
#: The opening decays linearly (`MAXL + 1 - L`) -- "as even as possible, less
#: probable at the upper end". The settled distribution is a hump over 3-6 with
#: thin tails everywhere else. Together they encode the design intent the jump
#: term exists to serve: opening high is for exceptional hands only, but the
#: ladder must still be CLIMBABLE to the same heights a rung at a time.
#: REVISED 2026-08-15: a common level-1 opening is FINE. The linear decay that
#: preceded this wanted 22% at the floor and was penalising the ~38% every arm
#: produces -- effort spent fighting a shape nobody objected to, and it competed
#: directly with the settled distribution, which is what actually matters.
TARGET_OPEN = [.32, .20, .15, .12, .09, .06, .04, .02]
if MAXL != 8:
    TARGET_OPEN = [TARGET_OPEN[round(i * 7 / (MAXL - 1))] for i in range(MAXL)]
TARGET_OPEN = [x / sum(TARGET_OPEN) for x in TARGET_OPEN]
#: REVISED 2026-08-15: level 6 is acceptable, but no rung may carry 40%+. The
#: hump therefore sits at 5 and runs 3-7 with a maximum of 24%, rather than the
#: original brief's tighter 3-6.
_SETTLE8 = [.03, .06, .13, .20, .24, .20, .10, .04]
#: Resampled onto whatever ladder is in play, so a FINER ladder is judged
#: against the same SHAPE rather than a shape it cannot express. Without this
#: the granularity experiment would be scored against an 8-rung target while
#: bidding on 16 rungs, and would lose for the wrong reason.
TARGET_SETTLE = ([_SETTLE8[round(i * 7 / (MAXL - 1))] for i in range(MAXL)]
                 if MAXL != 8 else _SETTLE8)
TARGET_SETTLE = [x / sum(TARGET_SETTLE) for x in TARGET_SETTLE]


#: No rung may carry more than this share. A total-variation distance alone is
#: too forgiving of a single tall spike -- it trades a 50% pile on one level
#: against small errors spread over the rest and can score them equal -- so the
#: cap is priced separately and steeply.
CAP = 0.40
CAP_WEIGHT = 2.0


def double_violations(cfg):
    """Levels where the Double stops being a bet and becomes free money.

    THE CONSTRAINT THE SCORING SEARCH WAS MISSING, and it cost a shipping
    attempt. On the COMMON failure -- one point short -- doubling wins
    `set_base + ramp` and risks `make`. If the reward exceeds the risk the
    defender should simply always double, which is not a decision. The shipped
    scoring holds this from level 2 up; the first re-priced candidate broke it
    at 2 and 3, where the made base is small and the set base is not.

    Pure arithmetic on the constants, so a violating scoring can be rejected
    before any CFR time is spent on it. `games/dissonance/tests/test_double.py::
    test_doubling_still_risks_more_than_it_wins_on_a_near_miss` is the shipped
    assertion of the same property -- this is that test, moved upstream of the
    search so it stops proposing scorings the suite will reject.
    """
    bad = []
    for L in range(2, MAXL + 1):
        make = cfg["A"] * L ** cfg["p"] + cfg.get("C", 0) * L + cfg["Fm"]
        setb = cfg["B"] * L ** cfg["q"] + cfg["Fs"]
        if make <= setb + E.DOUBLE_RAMP:
            bad.append(L)
    return bad


def _tv(got, target):
    """Total-variation distance, plus an explicit penalty for a tall spike."""
    tv = sum(abs(got.get(L, 0.0) - t)
             for L, t in zip(range(1, MAXL + 1), target)) / 2
    over = max((v - CAP for v in got.values()), default=0.0)
    return tv + CAP_WEIGHT * max(0.0, over)


def leaf(rec, level, prev, declarer, holds=0, dbl=False):
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
    terms = E._terms_for("classic", 0, level, jump=level - prev,
                         doubling=2 if dbl else 1)
    if CURVE:
        # THE LADDER'S GRANULARITY. `target` is what the contract must actually
        # TAKE, and it is the only knob that changes how much HARDER one rung is
        # than the last. Achievable points measure mean 4.03 sd 1.92, so at the
        # shipped `target = level` a single rung is 0.52 sd -- which is why no
        # payoff curve can spread the settled distribution past two or three
        # rungs. `tscale` shrinks the step.
        if "tscale" in CURVE:
            terms["target"] = max(1, round(1 + (level - 1) * CURVE["tscale"]))
            # AND THE PAYOFF MUST TRACK THE TARGET, NOT THE RUNG. A finer ladder
            # scored off the raw level pays level 11 more than twice what level 5
            # pays for a contract barely one point harder, and the auction simply
            # races to the top -- measured, settling at 10.2 of 12 with 15%
            # making. What a contract is worth has to follow how hard it is.
            level = terms["target"]
        # `C` is a LINEAR level term on the made base, mirroring the one the set
        # base already carries. Both sides then read the same shape --
        # quadratic + linear + flat on the make, linear + flat on the set -- and
        # in EV terms it is a mild HIGH-contract subsidy, which is the opposite
        # tilt to the flat bonus and the overtrick rate. That is why it can buy
        # back what turning overtricks on costs.
        terms["make"] = round(CURVE.get("A", 1.0) * level ** CURVE.get("p", 2.0)
                              + CURVE.get("C", 0.0) * level
                              + E.FLAT_MAKE_BONUS["classic"])
        # THE SET BASE'S OWN CURVE. `short x (target - pts)` already makes a
        # deep failure quadratic-ish in the level -- bid 7, make 3, and you are
        # four short on a base that also grew -- which is what makes the top of
        # the ladder unreachable however good the make side gets. `q` is the
        # exponent on the level part of that base, so the top can be made
        # SURVIVABLE without inflating the reward for getting there.
        if "q" in CURVE or "B" in CURVE or "jexp" in CURVE:
            base = CURVE.get("B", 1.0) * level ** CURVE.get("q", 1.0) \
                + E.FLAT_SET_PENALTY["classic"]
            # THE JUMP'S OWN EXPONENT. Linear in `j` means opening at 6 costs
            # six times a one-rung raise, which is why no hand opens high at any
            # rate that also punishes jumping -- the design intent ("punish
            # opening too high with anything but extremely good hands") wants a
            # CONCAVE penalty: steep for the first rungs, then levelling, so a
            # big opening is expensive without being unaffordable.
            j = level - prev
            base += E.JUMP_SET_BONUS["classic"] * j ** CURVE.get("jexp", 1.0)
            terms["set_base"] = round(base)
        # THE DENOMINATION AS A PRICE RUNG -- the one mechanism that escapes the
        # invariance above. Every payoff rule multiplies the per-rung fall in
        # P(make) and the per-hand spread in it by the SAME (make + set), so the
        # ratio that sets the settled distribution's width cannot be moved by
        # paying more or less. What CAN move it is putting more rungs inside one
        # step of difficulty -- and Dissonance already has them. A same-level
        # overtake in a higher-ranked denomination is legal and is 28.6% of
        # Expert's bids, but it carries no money: it is a free re-bid at an
        # identical price. `dmult` gives it one, so the five denominations
        # become five price steps per level and P(make) falls five times more
        # slowly per RUNG. This is skat's trick (base value x multipliers), done
        # with rules classic already has.
        if "dmult" in CURVE:
            m = 1.0 + CURVE["dmult"] * holds
            terms["make"] = round(terms["make"] * m)
            terms["set_base"] = round(terms["set_base"] * m)
        # `_terms_for` already applied the Double, but everything above REPLACED
        # both bases with undoubled values -- so it has to be re-applied, or a
        # doubled contract would quietly score as an undoubled one under every
        # experimental scoring and the Double would measure as worthless.
        if dbl:
            terms["make"] *= 2
            terms["set_base"] *= 2
            terms["ramp"] = E.DOUBLE_RAMP
    # WHICH SUIT IS ACTUALLY BEING PLAYED. With the all-denomination cache,
    # `holds` is not just a price step -- it selects the contract. The seat that
    # opens a level names its best suit; each same-level overtake must outrank
    # the standing bid, so it lands the bidder in a progressively worse one.
    # Modelling that as "rank = holds" is the abstraction, and it is the whole
    # difference between this test and the earlier `dmult` one, which raised the
    # PRICE of an overtake while leaving its difficulty identical.
    pts, duck = rec["pts"][declarer], rec["duck"][declarer]
    if isinstance(pts, list):
        i = min(holds, len(pts) - 1)
        pts, duck = pts[i], duck[i]
    # REAL-PLAY LEAF. `pts` is the double-dummy guarantee, which assumes a
    # PERFECT DEFENDER; 794 measured rounds put real outcomes 0.95 points above
    # it with sd 1.94. Two parts, and they are separated on purpose:
    #
    #   `eps`   -- a per-deal, per-seat draw from the CENTRED deviation, fixed
    #              in the cache so the leaf stays deterministic.
    #   shift   -- the deviation's MEAN, which falls with the level (+1.14 at 3
    #              down to +0.77 at 6): a defender leaks less to a declarer who
    #              is straining. Small against the sd, but it is the term that
    #              makes high contracts relatively harder, so folding it into a
    #              pooled constant would flatter exactly the rungs in question.
    if rec.get("eps") is not None:
        pts = round(pts + rec["eps"][declarer] + 1.45 - 0.11 * level)
    return E.payoff(terms, pts, not duck)


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
        #: CFR+ / LINEAR AVERAGING. Vanilla CFR averages every iteration equally,
        #: so the average strategy carries all the early ones when it was still
        #: uniform -- and the OPENING infoset is where that showed: the level-1
        #: opening rate climbed 27 -> 35 -> 42 -> 49% over 30k -> 200k iterations
        #: and was still moving, while the settled distribution had long since
        #: stopped. Rankings read off a solve that had not settled were comparing
        #: iteration counts as much as scorings. Two standard changes fix it:
        #: cumulative regrets floored at 0 (regret matching+), and iteration `t`
        #: contributing to the average with weight `t`.
        self.t = 1

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
                if WITH_DOUBLE:
                    return self.dbl_node(rec, level, prev, holds, to_act, me, rng)
                return leaf(rec, level, prev, holder, holds) * (1 if holder == me else -1)
            if a == HOLD:
                return self.walk(rec, level, prev, holds + 1, 1 - to_act, me, rng)
            return self.walk(rec, a, level, 0, 1 - to_act, me, rng)

        if to_act != me:
            # SAMPLE the opponent, and accumulate their average strategy.
            for a in acts:
                self.S[key][a] += self.t * sig[a]
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
            self.R[key][a] = max(self.R[key][a] + vals[a] - node, 0.0)
        return node

    def dbl_node(self, rec, level, prev, holds, defender, me, rng):
        """The DEFENDER's Double, priced as its own decision.

        Reached the moment somebody concedes: the passer is the defender, and
        the contract they just handed over is the one they may now double. Both
        bases double, so the defender is betting the contract fails -- and the
        bet's break-even moves with the scoring, which is the whole reason a
        scoring change forces a Double re-tune rather than merely permitting one.
        """
        decl = 1 - defender
        key = ("D", rec["b"][defender], level, prev, holds)
        acts = [0, 1]                       # 0 = decline, 1 = double
        sig = self.strategy(key, acts)
        sign = 1 if decl == me else -1

        def val(a):
            return leaf(rec, level, prev, decl, holds, dbl=bool(a)) * sign

        if defender != me:
            for a in acts:
                self.S[key][a] += self.t * sig[a]
            return val(1 if rng.random() <= sig[1] else 0)
        vals = {a: val(a) for a in acts}
        node = sum(sig[a] * vals[a] for a in acts)
        for a in acts:
            self.R[key][a] = max(self.R[key][a] + vals[a] - node, 0.0)
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
        conc = [sign * leaf(rc, level, prev, holder, holds) for rc in recs]
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
    for _i in range(iters):
        rec = recs[rng.randrange(len(recs))]
        cfr.t = _i + 1
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
    nbids = defaultdict(int)
    for _ in range(n):
        rec = recs[rng.randrange(len(recs))]
        level, prev, holds, to_act, holder = 0, 0, 0, 0, None
        bids = 0
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
            bids += 1
            if pick == HOLD:
                holds, to_act = holds + 1, 1 - to_act
            else:
                level, prev, holds, to_act = pick, level, 0, 1 - to_act
        settle[level] += 1
        nbids[bids] += 1
        if leaf(rec, level, prev, holder, holds) > 0:
            made += 1
    smean = sum(k * v for k, v in settle.items()) / n
    print(f"{rate:>4}{'' if seed == 1234 else chr(96+seed)} {ent:>8.3f} {sd:>7.2f} {mean:>7.2f} "
          f"{per[0]:>7.2f} {per[NBUCKET-1]:>7.2f} "
          f"{per[NBUCKET-1]-per[0]:>+8.2f} {smean:>8.2f} {100*made/n:>7.1f}% "
          f"| " + " ".join(f"{a}:{100*opn[a]:.0f}" for a in acts if opn[a] > .015),
          flush=True)


#: What the CLIMBED declarer-EV curve has to look like, levels 1..8.
#:
#: This is the target profile restated as a MECHANISM, and it is the whole
#: reason a scoring search is tractable. An auction rests at level L when the
#: contract there is worth about nothing to the marginal contested hand -- so a
#: settled distribution spread over 3-6 needs the EV curve to cross zero near 5
#: with a GENTLE slope, and an opening distribution that decays needs the low
#: rungs to still be worth taking (positive at 1-2) so nobody can just sit
#: there. The shipped curve is +13 +12 +10 +4 -9 -26 -43 -59: it crosses once,
#: at a slope of ~15 a rung, and one steep crossing is one mode.
TARGET_EV = [10.0, 7.0, 4.0, 2.0, 0.0, -3.0, -8.0, -16.0]


def ev_profile(recs):
    """Collapse the deal cache to what an EV curve needs, ONCE.

    `pts` and `duck` do not depend on the scoring, so the 4000 (deal, seat)
    pairs reduce to a duck fraction plus a histogram over `pts` -- about thirty
    numbers. That turns one config's whole EV curve from 32k payoff evaluations
    into a few hundred, which is what makes an exhaustive grid affordable and
    means CFR only ever runs on survivors.
    """
    duck, hist = 0, defaultdict(int)
    for r in recs:
        for s in (0, 1):
            if r["duck"][s]:
                duck += 1
            else:
                hist[r["pts"][s]] += 1
    n = 2 * len(recs)
    return duck / n, [(p, c / n) for p, c in sorted(hist.items())]


def ev_curve(prof, cfg, jump=1):
    """The declarer-EV curve under `cfg`, climbed a rung at a time by default."""
    duck, hist = prof
    out = []
    for L in range(1, MAXL + 1):
        make = cfg["A"] * L ** cfg["p"] + cfg["Fm"]
        setb = cfg["B"] * L ** cfg["q"] + cfg["Fs"] + cfg["jump"] * jump
        acc = duck * 20.0
        for pts, w in hist:
            acc += w * (make + (pts - L) if pts >= L
                        else -(setb + cfg["short"] * (L - pts)))
        out.append(acc)
    return out


def evscan_main(top):
    """`cfrlab evscan N` -- grid the scoring, rank by EV-curve shape.

    STAGE ONE of the search, and deliberately not the answer: a curve that
    matches `TARGET_EV` is a NECESSARY condition for the target profile, not a
    sufficient one, because the curve is unconditional and the auction is
    played by two hands that each know their own. Survivors go to CFR.
    """
    recs = [json.loads(x) for x in open(CKPT) if x.strip()]
    prof = ev_profile(recs)
    grid, seen = [], set()
    ps = [1.6 + .1 * i for i in range(16)]
    qs = [0.6 + .2 * i for i in range(8)]
    for p in ps:
        for A in (0.5, 1.0, 2.0, 3.0):
            for Fm in (0, 5, 10):
                for q in qs:
                    # B = 0 DROPS THE LEVEL TERM FROM THE SET BASE ENTIRELY, so
                    # going down at 7 costs the same base as at 3 and only the
                    # SHORTFALL separates them. It is the most direct way to
                    # make the top of the ladder survivable.
                    for B in (0.0, 0.5, 1.0, 2.0, 3.0):
                        for Fs in (0, 5, 10):
                            for short in (1, 2, 3, 5):
                                for jump in (3, 4, 5):
                                    grid.append(dict(
                                        p=p, A=A, Fm=Fm, q=q, B=B, Fs=Fs,
                                        short=short, jump=jump))
    scored, dropped = [], 0
    for cfg in grid:
        # THE SCALE IS AN ANCHORED CONSTRAINT, not a free parameter. `null` is a
        # flat 20 and does not scale with anything here, so a scoring that
        # shrinks the made base to single digits would quietly make the Null
        # consolation worth more than most contracts -- a perfect EV curve
        # around a broken game. Level 4 pays 26 today; hold it in that region.
        if not 18 <= cfg["A"] * 4 ** cfg["p"] + cfg["Fm"] <= 34:
            dropped += 1
            continue
        # `q` multiplies B, so every q ties when the level term is dropped. Fold
        # them, or the top of the table is eight copies of one scoring.
        key = (cfg["p"], cfg["A"], cfg["Fm"], cfg["B"], cfg["Fs"],
               cfg["short"], cfg["jump"],
               cfg["q"] if cfg["B"] else 0)
        if key in seen:
            continue
        seen.add(key)
        ev = ev_curve(prof, cfg)
        loss = sum((a - b) ** 2 for a, b in zip(ev, TARGET_EV)) ** 0.5
        scored.append((loss, cfg, ev))
    scored.sort(key=lambda x: x[0])
    print(f"  gridded {len(grid)} scorings, {dropped} dropped off-scale, "
          f"{len(scored)} distinct; target EV "
          + " ".join(f"{v:+.0f}" for v in TARGET_EV))
    for loss, cfg, ev in scored[:top]:
        spec = (f"p={cfg['p']:.1f},A={cfg['A']},Fm={cfg['Fm']},"
                f"q={cfg['q']:.1f},B={cfg['B']},Fs={cfg['Fs']},"
                f"short={cfg['short']},jump={cfg['jump']}")
        mk = [cfg["A"] * L ** cfg["p"] + cfg["Fm"] for L in (1, 4, 8)]
        st = [cfg["B"] * L ** cfg["q"] + cfg["Fs"] + cfg["jump"]
              for L in (1, 4, 8)]
        print(f"  {loss:>5.1f}  {spec:<50} make {mk[0]:>4.0f}/{mk[1]:>3.0f}/"
              f"{mk[2]:>3.0f}  set {st[0]:>3.0f}/{st[1]:>3.0f}/{st[2]:>3.0f}"
              f"  EV " + " ".join(f"{v:+.0f}" for v in ev))


def search_main(n, shard, nshard, iters):
    """`cfrlab search N SHARD NSHARD ITERS` -- random search over the scoring.

    STAGE THREE, after the EV grid and the hand-picked probes, and the reason it
    exists is that hand-picking stopped working: the concave-jump probes all
    came in WORSE than the linear arm they were meant to beat, which is the
    signal that intuition about a seven-parameter interaction has run out.

    Iterations are deliberately low here. The ranking only has to be good enough
    to pick survivors, and the survivors get re-solved at full length -- spending
    200k on a config that loses by 0.3 buys nothing.
    """
    rng = random.Random(20250815 + shard)
    recs = [json.loads(x) for x in open(CKPT) if x.strip()]
    bucketise(recs)
    for i in range(n):
        if i % nshard != shard:
            continue
        # CLEAN NUMBERS ONLY -- integers, or halves at worst. A scoring rule is
        # read by a player at the table, and `0.5 x L^2.4` is not a rule anyone
        # can hold in their head. Exponents are whole; coefficients are integers
        # or 0.5; everything else is an integer. This shrinks the space a long
        # way and rules out the previous best-found arm, which is fine: that arm
        # was fitted to the double-dummy leaf and does not survive this one.
        cfg = {
            "p": rng.choice([1, 2, 2, 3]),
            "A": rng.choice([0.5, 1, 1, 2, 3]),
            # `C` -- the linear make term, the only lever measured to lengthen
            # the auction and cut the one-bid rate.
            "C": rng.choice([0, 0, 1, 2, 3]),
            "Fm": rng.choice([0, 2, 5, 8, 10, 12, 15]),
            "q": rng.choice([1, 1, 2]),
            "B": rng.choice([0, 0, 0.5, 1, 2]),
            "Fs": 0,      # chosen below, inside the Double constraint

            "short": rng.choice([1, 2, 2, 3, 4, 5]),
            # Constrained to 5-6: 7 was measured to produce too many level-1
            # openings, and below 5 the ladder stops punishing a big leap.
            "jump": rng.choice([5, 6]),
            # Never 0 -- overtricks must count for something.
            "over": rng.choice([1, 1, 2]),
        }
        if not 18 <= cfg["A"] * 4 ** cfg["p"] + cfg["C"] * 4 + cfg["Fm"] <= 34:
            continue                       # same scale anchor as the EV grid
        # SAMPLE Fs INSIDE THE DOUBLE CONSTRAINT rather than rejecting after the
        # fact. Rejection cost 98% of the draws (8 of 400 survived), which is
        # not a search -- it is a lottery. The constraint is linear in `Fs`, so
        # its ceiling is closed-form: `Fs < make(L) - B x L^q - ramp` at every
        # level, and the binding level is whichever is tightest.
        ceil = min(cfg["A"] * L ** cfg["p"] + cfg["C"] * L + cfg["Fm"]
                   - cfg["B"] * L ** cfg["q"] - E.DOUBLE_RAMP
                   for L in range(2, MAXL + 1))
        if ceil <= 0:
            continue                       # no flat set stake can rescue it
        cfg["Fs"] = rng.choice([x for x in (0, 2, 5, 8, 10, 12, 15)
                                if x < ceil] or [0])
        assert not double_violations(cfg), cfg
        spec = ",".join(f"{k}={v}" for k, v in cfg.items())
        # Each config gets a FRESH process-level scoring state; the knobs are
        # module constants, so a loop that mutated them in place would leak the
        # previous config into the next one.
        # `curvedbl`, not `curve`: the Double is a branch both sides use, and
        # solving without it measurably moves the settled distribution -- the
        # candidate's 38% maximum became 55% once it was there. A search on the
        # cheaper tree ranks scorings for a game nobody plays.
        subprocess.run([sys.executable, "-m", "games.dissonance.tools.cfrlab",
                        "curvedbl", spec, str(iters)],
                       env=dict(os.environ), check=False)


def play_round(seed, level, k=8):
    """Impose a contract at `level`, then play it out with the SHIPPED search.

    Returns (made, declarer_points). Both seats search -- this is real play, so
    the defender must be real too.
    """
    g = E.new_game(["a", "b"], random.Random(seed), opener=0, mode="classic")
    seat = E.turn_seat(g)
    best = max(range(E.NOTRUMP + 1), key=lambda d: B.hand_strength(g, seat, d))
    E.apply_move(g, g["seats"][seat], {"kind": "bid", "level": level,
                                       "denom": best})
    # Drive the rest of the auction to THIS contract: the opponent concedes, and
    # any pending double is declined, so the only thing varying between arms is
    # the card play.
    guard = 0
    while g["phase"] != "play" and guard < 12:
        guard += 1
        s = E.turn_seat(g)
        if s is None:
            return None
        if g["phase"] == "auction":
            E.apply_move(g, g["seats"][s], {"kind": "pass"})
        elif g["phase"] == "double":
            E.apply_move(g, g["seats"][s], {"kind": "double", "on": False})
        elif g["phase"] == "swap":
            p = B.choose_swap(g, s)
            E.apply_move(g, g["seats"][s], {"kind": "swap", "take": p.get("take"),
                                            "give": p.get("give")})
        else:
            return None
    if g["phase"] != "play":
        return None
    decl = g["auction"]["declarer"]
    terms = E.payoff_terms(g)
    guard = 0
    while g["phase"] == "play" and guard < 40:
        guard += 1
        s = E.turn_seat(g)
        if s is None:
            break
        r = rpc({"pick": {"view": E.view_for(g, s), "payoff": terms, "k": k}})
        moves, sums = r.get("moves"), r.get("sum")
        if not moves:
            break
        card = moves[max(range(len(moves)), key=lambda j: sums[j])]
        E.apply_move(g, g["seats"][s], {"kind": "play", "card": card})
    # `pts`, and read it WITHOUT a default. `g.get("points", [0, 0])` was the
    # first cut: the engine's key is `pts`, so every round silently scored zero
    # and the harness reported a perfectly plausible "real play never makes
    # anything". A defaulted read of a misspelled key is indistinguishable from
    # a real result.
    pts = g["pts"][decl]
    return (pts >= level, pts)


def playnoise_main(n, shard=0, nshard=1, levels=(3, 4, 5, 6)):
    """`cfrlab playnoise N [SHARD NSHARD]` -- how much looser is the REAL ladder?

    EVERYTHING ELSE IN THIS FILE IS DOUBLE-DUMMY: `pts` is what a declarer can
    guarantee seeing all forty cards. Real play is noisier, and noise WIDENS the
    achieved-points distribution, which flattens P(make) per rung -- so every
    "the ladder is too coarse" conclusion here is an upper bound on the
    coarseness until this is measured.

    So: impose a contract at each level on the same deals the cache holds, play
    it out with the shipped search on BOTH seats, and compare the realised make
    rate against the double-dummy one. The gap between the two curves is the
    answer, and its SLOPE is what matters -- a curve that is uniformly lower is
    just "real play is worse than perfect play", while a curve that is FLATTER
    is a genuinely finer ladder than the double-dummy numbers imply.
    """
    ck = os.environ.get("CFR_PLAY_CKPT")
    if ck and nshard > 1:
        ck = f"{ck}.{shard}"
    done = set()
    if ck and os.path.exists(ck):
        for line in open(ck):
            try:
                r = json.loads(line)
                done.add((r["seed"], r["level"]))
            except (json.JSONDecodeError, KeyError):
                pass
    out = open(ck, "a") if ck else None
    jobs = [(800_000 + i, L) for i in range(n) for L in levels]
    for idx, (seed, L) in enumerate(jobs):
        if idx % nshard != shard or (seed, L) in done:
            continue
        r = play_round(seed, L)
        if r is None:
            continue
        rec = {"seed": seed, "level": L, "made": bool(r[0]), "pts": r[1]}
        if out:
            out.write(json.dumps(rec) + "\n")
            out.flush()


def playnoise_report():
    base = os.environ.get("CFR_PLAY_CKPT")
    rows, seen = [], set()
    for p in [base] + [f"{base}.{i}" for i in range(8)]:
        if not p or not os.path.exists(p):
            continue
        for line in open(p):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (r["seed"], r["level"]) not in seen:
                seen.add((r["seed"], r["level"]))
                rows.append(r)
    if not rows:
        print("no played rounds yet")
        return
    dd = {}
    for i, line in enumerate(open(CKPT)):
        if line.strip():
            dd[800_000 + i] = json.loads(line)["pts"][0]
    by = defaultdict(list)
    for r in rows:
        if r["seed"] in dd:
            by[r["level"]].append(r)
    print(f"\n=== REAL PLAY vs DOUBLE-DUMMY ({len(rows)} played rounds) ===")
    print(f"  {'level':>6} {'n':>5} {'DD makes':>9} {'REAL makes':>11} "
          f"{'gap':>7} {'DD pts':>8} {'real pts':>9}")
    prev = None
    slopes = [[], []]
    for L in sorted(by):
        v = by[L]
        ddm = 100 * sum(1 for r in v if dd[r["seed"]] >= L) / len(v)
        rlm = 100 * sum(1 for r in v if r["made"]) / len(v)
        ddp = statistics.mean(dd[r["seed"]] for r in v)
        rlp = statistics.mean(r["pts"] for r in v)
        print(f"  {L:>6} {len(v):>5} {ddm:>8.1f}% {rlm:>10.1f}% "
              f"{rlm-ddm:>+6.1f} {ddp:>8.2f} {rlp:>9.2f}")
        if prev:
            slopes[0].append(prev[0] - ddm)
            slopes[1].append(prev[1] - rlm)
        prev = (ddm, rlm)
    if slopes[0]:
        d, r = statistics.mean(slopes[0]), statistics.mean(slopes[1])
        print(f"\n  COST OF ONE RUNG:  double-dummy {d:.1f} points of make-chance"
              f"   real play {r:.1f}")
        print(f"  The real ladder is {100*(1-r/d):.0f}% "
              f"{'LOOSER' if r < d else 'TIGHTER'} than the double-dummy numbers "
              f"say.")


def denom_main(n):
    """`cfrlab denom N` -- is a same-level overtake an INTERMEDIATE contract?

    THE QUESTION THE `dmult` TEST COULD NOT ANSWER, and the reason that test
    only nudged the settled distribution. Scaling the payoff by the denomination
    rank prices a same-level overtake higher at IDENTICAL difficulty, which is
    leverage, not granularity. In the real game an overtake means playing a
    DIFFERENT suit -- usually a worse one -- so it is genuinely harder than the
    standing contract and genuinely easier than the next level up.

    If that is true, the five ranked denominations already interleave four extra
    difficulty rungs between every pair of levels, and the ladder is five times
    finer than `target = level` makes it look. That is the one mechanism that
    escapes the invariance: every payoff rule scales the per-rung fall in
    P(make) and the per-hand spread by the same (make + set) and cannot move
    their ratio, but putting more rungs inside one step of difficulty moves the
    denominator directly.

    Measured, not assumed: this solves EVERY denomination for both seats.
    """
    tot = defaultdict(list)
    for i in range(n):
        g = E.new_game(["a", "b"], random.Random(900_000 + i), opener=0,
                       mode="classic")
        for seat in (0, 1):
            byd = []
            for d in range(E.NOTRUMP + 1):
                r = rpc({"resolve": {
                    "hands": [sorted(h) for h in g["hands"]],
                    "piles": [[list(x) for x in q] for q in g["piles"]],
                    "trump": d, "leader": seat,
                    "terms": {"declarer": seat, "target": 1, "make": 1,
                              "set_base": 1, "short": 1, "over": 1, "null": 20},
                }})
                byd.append(r.get("pts", 0))
            byd.sort(reverse=True)
            for rank, v in enumerate(byd):
                tot[rank].append(v)
        if (i + 1) % 25 == 0:
            print(f"  {i+1}/{n} deals", flush=True)
    print(f"\n=== ACHIEVABLE POINTS BY DENOMINATION RANK ({n} deals) ===")
    print(f"  {'rank':>16} {'mean pts':>9} | P(make) at level 3 / 4 / 5 / 6")
    best = tot[0]
    for rank in sorted(tot):
        v = tot[rank]
        ps = [100 * sum(1 for x in v if x >= L) / len(v) for L in (3, 4, 5, 6)]
        lbl = "best" if rank == 0 else f"{rank+1}th best"
        print(f"  {lbl:>16} {statistics.mean(v):>9.2f} | "
              + "  ".join(f"{p:>4.0f}%" for p in ps))
    # THE NUMBER THAT DECIDES IT: how far down the level ladder does dropping
    # one denomination rank move you? If it is a fraction of a rung, the
    # denominations interleave and the effective ladder is already finer.
    print(f"\n  In LEVELS, how far one denomination rank costs you:")
    for rank in sorted(tot):
        if rank == 0:
            continue
        gap = statistics.mean(best) - statistics.mean(tot[rank])
        print(f"    best -> {rank+1}th best: {gap:>5.2f} points "
              f"= {gap:>4.2f} of a level")


def curve_main(spec, iters, seed=1234):
    """`cfrlab curve p=2,Fm=10,Fs=10,short=5,jump=3 ITERS [SEED]`.

    THE JUMP RATE COULD NOT SPREAD THE OPENING and the ladder table says why:
    levels 1-3 make 95.7/90.4/80.0% and pay the declarer +12.71/+12.32/+10.39,
    so they are near-free money and the auction can never rest there. That is
    the MAKE/SET CURVE, not the jump term, which is what this sweeps.

    The mechanism to watch is the declarer-EV-by-level curve, printed beside
    every row. Under the shipped scoring it falls monotonically -- every hand
    wants the lowest rung, competition bids that up to the one point where
    taking the contract stops paying, and a single crossing point is a single
    mode. An interior peak, or a flat stretch, is what a spread opening would
    have to look like, and it is the only reading here that is a MECHANISM
    rather than a summary statistic.

    Arithmetic worth having before reading the rows: the make base runs 11 -> 74
    over levels 1..8, a factor of 6.7, while the make PROBABILITY falls 95.7% ->
    2.3%, a factor of 42. Nothing about a 6.7x reward against a 42x risk can be
    flat, which is the whole reason the curve falls. `Fm = 0` alone takes the
    reward ratio to 64x (1 -> 64) and `p` tunes it -- 8^p = 42 lands near 1.8.

    NOTE ON PRIOR ART, because this is re-asking a settled question. The
    symmetric +-10 flat stake shipped 2026-08-11 on 400 paired Expert-vs-Expert
    deals per arm, and `FLAT_MAKE_MIN_LEVEL` gating measured indistinguishable
    there. Those arms were judged by Expert against Expert -- the mirror this
    campaign has since measured at 9.06 points of exploitability -- so the
    equilibrium is entitled to a different answer, and a disagreement between
    the two is information rather than a contradiction to explain away.
    """
    for kv in spec.split(","):
        k, _, v = kv.partition("=")
        if k in ("p", "A", "C", "q", "B", "jexp", "tscale", "dmult"):
            CURVE[k] = float(v)
        elif k == "Fm":
            E.FLAT_MAKE_BONUS["classic"] = int(v)
        elif k == "Fs":
            E.FLAT_SET_PENALTY["classic"] = int(v)
        elif k == "short":
            # `CLASSIC_SHORT_PENALTY`, not `SHORT_PENALTY`. The engine split the
            # two on 2026-08-16 so classic and skat could move independently,
            # and this knob kept patching skat's -- so every sweep after the
            # split silently ran at the shipped 5 whatever it was told. Caught
            # because two specs differing only in `short` printed byte-identical
            # rows. Patch BOTH: skat does not reach this branch, and a knob that
            # half-works is worse than one that does not.
            E.CLASSIC_SHORT_PENALTY = int(v)
            E.SHORT_PENALTY = int(v)
        elif k == "jump":
            E.JUMP_SET_BONUS["classic"] = int(v)
        elif k == "dshort":
            # The DOUBLED per-point rate (`DOUBLED_SHORT_PENALTY`). Its own dial
            # since 2026-08-16 -- patching `short` alone would move the undoubled
            # game too and make a Double sweep un-attributable.
            E.DOUBLED_SHORT_PENALTY["classic"] = int(v)
        elif k == "dmake":
            E.DOUBLE_MAKE_MULT["classic"] = int(v)
        elif k == "djump":
            E.DOUBLE_JUMP_MULT["classic"] = int(v)
        elif k == "dbase":
            # THE DIAL THAT SETS HOW OFTEN DOUBLING IS CORRECT. At 1 the
            # defender's winnings come only from the shortfall, so the Double
            # becomes a bet on HOW BADLY the contract misses rather than that it
            # does -- which raises the break-even and thins the rate.
            E.DOUBLE_BASE_MULT["classic"] = int(v)
        elif k == "over":
            # The ONE term that scales with HOW MUCH you make rather than
            # whether -- so it is the only knob that can discriminate by hand
            # strength without steepening the top of the ladder, which is what
            # `short` does and why `short` cannot buy both at once.
            E.OVER_BONUS["classic"] = int(v)
        else:
            raise SystemExit(f"unknown scoring knob {k!r} in {spec!r}")
    CURVE.setdefault("p", 2.0)

    recs = [json.loads(x) for x in open(CKPT) if x.strip()]
    bucketise(recs)
    cfr = CFR(recs)
    rng = random.Random(seed)
    for _i in range(iters):
        rec = recs[rng.randrange(len(recs))]
        cfr.t = _i + 1
        for me in (0, 1):
            cfr.walk(rec, 0, 0, 0, 0, me, rng)
    eqp = Policy({k: {a: max(x, 0.0) / sum(max(y, 0.0) for y in s.values())
                      for a, x in s.items()}
                  for k, s in cfr.S.items()
                  if sum(max(y, 0.0) for y in s.values()) > 0}, backoff=False)

    acts = actions(0, 0)
    opn = {a: 0.0 for a in acts}
    per = {}
    for b in range(NBUCKET):
        s = eqp.at(b, 0, 0, 0, acts) or {a: 1 / len(acts) for a in acts}
        per[b] = sum(a * s[a] for a in acts)
        for a in acts:
            opn[a] += s[a] / NBUCKET
    ent = -sum(p * math.log(p) for p in opn.values() if p > 0) / math.log(len(acts))

    settle, made, n = defaultdict(int), 0, 6000
    nbids = defaultdict(int)
    ndbl = [0, 0, 0]
    for _ in range(n):
        rec = recs[rng.randrange(len(recs))]
        level, prev, holds, to_act, holder = 0, 0, 0, 0, None
        bids = 0
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
            bids += 1
            if pick == HOLD:
                holds, to_act = holds + 1, 1 - to_act
            else:
                level, prev, holds, to_act = pick, level, 0, 1 - to_act
        # The Double, played out with the same average strategy.
        dbl = False
        if WITH_DOUBLE and holder is not None:
            dk = ("D", rec["b"][1 - holder], level, prev, holds)
            dbl = rng.random() <= cfr.average(dk, [0, 1])[1]
            ndbl[0] += 1
            if dbl:
                ndbl[1] += 1
                if leaf(rec, level, prev, holder, holds, dbl=True) < 0:
                    ndbl[2] += 1       # doubled AND set: the bet came in
        settle[level] += 1
        nbids[bids] += 1
        if leaf(rec, level, prev, holder, holds) > 0:
            made += 1
    smean = sum(k * v for k, v in settle.items()) / n
    # The mechanism column: unconditional declarer EV per rung, opened straight.
    ev = [statistics.mean(leaf(r, lv, 0, s) for r in recs for s in (0, 1))
          for lv in range(1, MAXL + 1)]
    sd = {k: v / n for k, v in settle.items()}
    lo, ls = _tv(opn, TARGET_OPEN), _tv(sd, TARGET_SETTLE)
    # A scoring that breaks the Double is not a candidate however well it
    # distributes, so it is priced into the headline number rather than noted
    # beside it -- a footnote is what let the first candidate reach a ship.
    bad = double_violations(dict(
        A=CURVE.get("A", 1.0), p=CURVE.get("p", 2.0), C=CURVE.get("C", 0.0),
        Fm=E.FLAT_MAKE_BONUS["classic"], B=CURVE.get("B", 1.0),
        q=CURVE.get("q", 1.0), Fs=E.FLAT_SET_PENALTY["classic"]))
    lo += 0.5 * len(bad)
    print(f"{lo+ls:>5.2f} {lo:>5.2f} {ls:>5.2f} "
          f"{spec:>40}{'' if seed == 1234 else chr(96+seed)} "
          f"{per[NBUCKET-1]-per[0]:>+6.2f} {smean:>5.2f} {100*made/n:>5.1f}% | o "
          + " ".join(f"{a}:{100*opn[a]:.0f}" for a in acts if opn[a] > .015)
          + " | s "
          + " ".join(f"{k}:{100*v:.0f}" for k, v in sorted(sd.items())
                     if v > .015)
          + " | bids " + f"{sum(k*v for k,v in nbids.items())/n:.2f} "
          + " ".join(f"{k}:{100*v/n:.0f}" for k, v in sorted(nbids.items())
                     if v / n > .015)
          + (f" | DBL {100*ndbl[1]/max(1,ndbl[0]):.0f}% taken, "
             f"{100*ndbl[2]/max(1,ndbl[1]):.0f}% of those set" if WITH_DOUBLE else "")
          + (f" | DBL-BROKEN at {bad}" if bad else "")
          + " | EV " + " ".join(f"{v:+.0f}" for v in ev), flush=True)


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
    for _i in range(iters):
        rec = recs[rng.randrange(len(recs))]
        cfr.t = _i + 1
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
    if len(sys.argv) > 1 and sys.argv[1] == "playnoise":
        if len(sys.argv) > 2 and sys.argv[2] == "report":
            return playnoise_report()
        return playnoise_main(int(sys.argv[2]),
                              int(sys.argv[3]) if len(sys.argv) > 3 else 0,
                              int(sys.argv[4]) if len(sys.argv) > 4 else 1)
    if len(sys.argv) > 1 and sys.argv[1] == "dcache":
        return dcache_main(int(sys.argv[2]) if len(sys.argv) > 2 else 600)
    if len(sys.argv) > 1 and sys.argv[1] == "denom":
        return denom_main(int(sys.argv[2]) if len(sys.argv) > 2 else 200)
    if len(sys.argv) > 1 and sys.argv[1] == "search":
        return search_main(int(sys.argv[2]), int(sys.argv[3]),
                           int(sys.argv[4]), int(sys.argv[5]))
    if len(sys.argv) > 1 and sys.argv[1] == "evscan":
        return evscan_main(int(sys.argv[2]) if len(sys.argv) > 2 else 25)
    if len(sys.argv) > 1 and sys.argv[1] == "curvedbl":
        globals()["WITH_DOUBLE"] = True
        return curve_main(sys.argv[2],
                          int(sys.argv[3]) if len(sys.argv) > 3 else 200_000,
                          int(sys.argv[4]) if len(sys.argv) > 4 else 1234)
    if len(sys.argv) > 1 and sys.argv[1] == "curve":
        return curve_main(sys.argv[2],
                          int(sys.argv[3]) if len(sys.argv) > 3 else 200_000,
                          int(sys.argv[4]) if len(sys.argv) > 4 else 1234)
    if len(sys.argv) > 1 and sys.argv[1] == "chdr":
        return print(f"{'loss':>5} {'open':>5} {'setl':>5} {'scoring':>40} "
                     f"{'discr':>6} {'mean':>5} {'made':>6} | distributions % "
                     f"| unconditional declarer EV by level 1..8\n"
                     f"{'':>5} {'':>5} {'':>5} {'TARGET':>40} "
                     f"{'':>6} {'':>5} {'':>6} | o "
                     + " ".join(f"{L}:{100*t:.0f}" for L, t in
                                zip(range(1, MAXL + 1), TARGET_OPEN))
                     + " | s "
                     + " ".join(f"{L}:{100*t:.0f}" for L, t in
                                zip(range(1, MAXL + 1), TARGET_SETTLE)
                                if t > .015))
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
    for _i in range(iters):
        rec = recs[rng.randrange(len(recs))]
        cfr.t = _i + 1
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
        v = leaf(rec, level, prev, holder, holds)
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
