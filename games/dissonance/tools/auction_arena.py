"""EXPERT vs HARD, in the AUCTION only.

The instrument behind the numbers in `games/dissonance/CLAUDE.md`. It drives the
SHIPPED path -- the server builds the option list and the armed request exactly
as `main._ask_the_client` does, `bin/bidserve` answers it through the same
`wire::answer_auction` the browser entry calls, and the pick is the client's own
argmax rule -- so what it measures is the tier, not a second implementation of
it.

CRN-paired: every deal is played twice with the tiers swapped, so the deal
cancels and what is left is the bidding. The talon/swap are the server bot's on
both sides, so the auction is the only thing that differs. The mirror
(`hard hard`) must read exactly +0.0000, and it is the first thing to run after
touching this file.

HOW A ROUND IS RESOLVED -- the variance lives here, so this is a flag:

* ``dd`` (default): the settled contract is scored by an EXACT double-dummy
  solve of the real deal (`bidserve`'s ``resolve`` request). No card-play noise
  and no card-play BIAS -- the old way scored both arms' auctions against a
  greedy policy neither tier would use. This is `bin/bidlab`'s method.
* ``play``: the old greedy playout, kept as the cross-check. A conclusion that
  holds under ``dd`` and reverses under ``play`` is a statement about the greedy
  policy, not about the bidding.

WHAT TO READ, in order:

* the ``per DEAL`` line -- a deal's two flips averaged, so seat and cards both
  cancel. Two identical auctions average to EXACTLY zero, which leads to:
* the ``differing auctions`` line -- the mean CONDITIONAL on the two arms having
  actually bid differently. Identical deals contribute a hard 0 to the mean and
  nothing to the question; this is the effect size where the tiers disagree,
  and `n_differ` says how often they do.
* the ``quality-adjusted`` line -- the same mean after a control-variate on the
  opener's hand quality (Hard's own myopic best price at the opening node,
  captured for free from whichever flip has Hard opening). The adjustment
  cannot move the mean's expectation, only shrink its error bar.

AND THE ERROR BAR IS THE POINT. Per-deal sigma was 15.8 under greedy playout --
2250 paired deals resolved only +-0.33, and the first 300 of a run once read
+1.71 where the full run said -0.28. Every progress line here prints a CI, not
a bare running mean, because that bare mean is exactly what got quoted.

    cargo build --release --features bridge --bin bidserve
    PYTHONPATH=. python3 games/dissonance/tools/auction_arena.py <mode> <k> <n> \\
        [<tierA> <tierB> [<lo> <hi> [dd|play]]]

`lo`/`hi` window the deal indices so shards can run in parallel; each prints a
`SHARD {...}` line to pool afterwards. Each (tier, seat) gets its OWN `bidserve`
process: the `Solved` cache is keyed on the cards, and one process playing both
seats thrashes it.
"""
import collections
import json
import random
import statistics
import subprocess
import sys

from games.dissonance import engine as E, bot as B

BIN = "rust-cores/dissonance-core/target/release/bidserve"
MODE = sys.argv[1] if len(sys.argv) > 1 else "classic"
K = sys.argv[2] if len(sys.argv) > 2 else "3"
N = int(sys.argv[3]) if len(sys.argv) > 3 else 60
TIER_A = sys.argv[4] if len(sys.argv) > 4 else "expert"
TIER_B = sys.argv[5] if len(sys.argv) > 5 else "hard"
LO = int(sys.argv[6]) if len(sys.argv) > 6 else 0
HI = int(sys.argv[7]) if len(sys.argv) > 7 else N
RESOLVE = sys.argv[8] if len(sys.argv) > 8 else "dd"
assert RESOLVE in ("dd", "play"), RESOLVE

PROC = {}


def proc_for(key):
    if key not in PROC:
        PROC[key] = subprocess.Popen([BIN, K], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True)
    return PROC[key]


def ask(g, seat, tier):
    """The armed request, answered by the shipped path; the client's own pick.

    Returns `(move, sums, opts)` -- the sums so the caller can read the opener's
    hand quality off a Hard ask without a second request.
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
    p = proc_for((tier, seat))
    p.stdin.write(json.dumps({"view": E.view_for(g, seat), "auction": auc}) + "\n")
    p.stdin.flush()
    res = json.loads(p.stdout.readline())
    sums = res.get("sums")
    if not sums or len(sums) != len(opts):
        return None, None, None
    i = max(range(len(opts)), key=lambda j: sums[j])
    o = opts[i]
    mv = o.get("move")
    if o.get("decline") and not sums[i] > 0:
        mv = o["decline"]
    return mv, sums, opts


def play(m, tier_of, qual):
    """One round: the auction by the tiers, the talon by the server bot, the
    resolution per `RESOLVE`.

    Returns `(margin_for_declarer_sign, declarer, fingerprint)` or None. The
    fingerprint is the full auction log plus the doubled flag -- everything
    downstream of those is deterministic (the server bot's swap included), so
    two flips with equal fingerprints had IDENTICAL rounds and their pair is
    exactly zero by construction.
    """
    g = E.new_game(["a", "b"], random.Random(600000 + m), opener=m % 2, mode=MODE)
    guard = 0
    while g["phase"] not in ("play", "over") and guard < 40:
        guard += 1
        seat = E.turn_seat(g)
        mv = None
        if g["phase"] in ("auction", "declare", "kontra", "re", "double"):
            mv, sums, opts = ask(g, seat, tier_of[seat])
            # THE CONTROL VARIATE, captured for free. The opening node is asked
            # of Hard in exactly one of a deal's two flips (the tiers swap
            # seats), and its myopic best bid price IS the hand-quality
            # yardstick `auction_style.py` uses. Noise in a covariate only
            # weakens the adjustment; it cannot bias the mean.
            if (mv is not None and g["phase"] == "auction"
                    and g["auction"]["declarer"] < 0 and not g["auction"]["log"]
                    and tier_of[seat] == "hard" and m not in qual):
                bids = [s for s, o in zip(sums, opts) if o["move"]["kind"] == "bid"]
                if bids:
                    qual[m] = max(bids) / max(1, int(K))
        if mv is None:
            kind, p = B.act(g, seat, random.Random(m))
            mv = ({"kind": "pass"} if p.get("pass")
                  else {"kind": "bid", **{a: b for a, b in p.items() if a != "pass"}}) \
                if kind == "bid" else (p if kind == "move"
                                       else ({"kind": "swap", **p} if kind == "swap" else p))
        E.apply_move(g, g["seats"][seat], mv)
    if g["phase"] != "play":
        return None
    fp = json.dumps([g["auction"]["log"], bool(g.get("doubled"))])
    terms = E.payoff_terms(g)
    decl = terms["declarer"]
    if RESOLVE == "dd":
        req = {"resolve": {"hands": [list(h) for h in g["hands"]],
                           "piles": [[list(x) for x in row] for row in g["piles"]],
                           "trump": g["auction"]["denom"], "leader": decl,
                           "terms": terms}}
        p = proc_for("resolver")
        p.stdin.write(json.dumps(req) + "\n")
        p.stdin.flush()
        r = json.loads(p.stdout.readline())
        if "payoff" not in r:
            raise SystemExit(f"deal {m}: unresolvable ({r})")   # harness bug, be loud
        return r["payoff"], decl, fp
    while g["phase"] == "play":
        s = E.to_play(g)
        E.apply_play(g, s, B.choose_card(g, s))
    sc = g["result"]["scores"]
    return sc[decl] - sc[1 - decl], decl, fp


def _stat(x):
    if not x:
        return 0.0, 0.0
    return statistics.mean(x), statistics.pstdev(x) / (len(x) ** 0.5)


pairs = []            # one per DEAL with BOTH flips resolved: flips averaged
diff_pairs = []       # ...the subset where the two arms' auctions differed
qof = []              # quality covariate, aligned with `pairs`
qual = {}
dropped = 0
for m in range(LO, HI):
    got = []
    for flip in (0, 1):
        tier_of = {flip: TIER_A, 1 - flip: TIER_B}
        out = play(m, tier_of, qual)
        if out is None:
            continue
        margin, decl, fp = out
        # Signed for tier A's seat this flip.
        row = margin if decl == flip else -margin
        got.append((row, fp))
    if len(got) != 2:
        # BOTH flips or neither: a one-sided drop would leave `pairs` and any
        # per-round view describing different deal sets, which is the exact
        # asymmetry this rewrite removes.
        dropped += len(got)
        continue
    pair = (got[0][0] + got[1][0]) / 2
    pairs.append(pair)
    qof.append(qual.get(m, 0.0))
    if got[0][1] != got[1][1]:
        diff_pairs.append(pair)
    if (m + 1) % 20 == 0 and pairs:
        mu, se = _stat(pairs)
        print(f"  {m + 1:4} deals  {TIER_A} - {TIER_B} = {mu:+.4f} "
              f"[{mu - 1.96 * se:+.2f}, {mu + 1.96 * se:+.2f}]  "
              f"({len(diff_pairs)}/{len(pairs)} differ)", flush=True)

mu, se = _stat(pairs)
print(f"\n{MODE} k={K} resolve={RESOLVE}: {TIER_A} - {TIER_B} = {mu:+.4f} +- {se:.4f} "
      f"payoff/round over {len(pairs)} paired deals"
      + (f" ({dropped} one-sided drops discarded)" if dropped else ""))
if diff_pairs:
    dmu, dse = _stat(diff_pairs)
    print(f"  differing auctions: {len(diff_pairs)}/{len(pairs)} deals, "
          f"conditional {dmu:+.4f} +- {dse:.4f}")
# The control variate. adjusted_i = pair_i - beta (q_i - qbar): expectation
# unchanged, variance down by the square of the correlation.
if len(pairs) > 3 and statistics.pstdev(qof) > 0:
    qbar = statistics.mean(qof)
    beta = (sum((p - mu) * (q - qbar) for p, q in zip(pairs, qof))
            / sum((q - qbar) ** 2 for q in qof))
    adj = [p - beta * (q - qbar) for p, q in zip(pairs, qof)]
    amu, ase = _stat(adj)
    print(f"  quality-adjusted:   {amu:+.4f} +- {ase:.4f}  "
          f"(beta {beta:+.3f}, se {'-' if ase < se else '+'}{abs(1 - ase / max(se, 1e-9)):.0%})")
print("SHARD " + json.dumps({"pairs": pairs, "diff_pairs": diff_pairs, "qof": qof,
                             "dropped": dropped}))
for p in PROC.values():
    p.stdin.close()
