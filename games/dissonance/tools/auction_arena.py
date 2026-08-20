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
import os
import random
import statistics
import subprocess
import sys

from games.dissonance import engine as E, bot as B, main as M

# Absolute, because a relative forward-slash path never reaches CreateProcess
# intact on Windows; harmless elsewhere.
BIN = os.path.abspath("rust-cores/dissonance-core/target/release/bidserve"
                      + (".exe" if os.name == "nt" else ""))
MODE = sys.argv[1] if len(sys.argv) > 1 else "classic"

# EXPERIMENT ARM: override the flat stake for THIS MODE, threaded through
# `engine.FLAT_MAKE_BONUS`/`FLAT_SET_PENALTY` (terms are data end to end, so
# the Expert search, the Double pricing and the DD resolver all see it with no
# further plumbing). Env rather than argv because the shard windows already
# use the positional slots, and a shard must inherit the arm it belongs to.
# ONLY when the env var is present: the +-10 classic stake SHIPPED 2026-08-11,
# so the engine default is no longer 0, and a knob that wrote unconditionally
# would silently measure a rule the room stopped using. `DIS_FLAT_MAKE=0
# DIS_FLAT_SET=0` is how the lab asks for the pre-ship baseline now.
# ...and the denomination rule, so an arm can be measured under a rule the
# engine no longer ships (e.g. re-running the v2-alone profile -- jump bonus
# with the original per-player forever-ban -- after "own" became the default).
if "DIS_DENOM_RULE" in os.environ:
    assert os.environ["DIS_DENOM_RULE"] in ("used", "standing", "own")
    E.DENOM_RULE[MODE] = os.environ["DIS_DENOM_RULE"]
# ...and the jump bonus rate, for the dose sweep (2/3/4 per level).
if "DIS_JUMP_SET" in os.environ:
    E.JUMP_SET_BONUS[MODE] = int(os.environ["DIS_JUMP_SET"])
# ...and whether the DOUBLE multiplies that bonus. `DIS_JUMP_DOUBLED=0` adds it
# after the doubling instead, which leaves the undoubled game byte-identical and
# only trims what a doubled set pays -- see `engine.JUMP_DOUBLED`.
if "DIS_JUMP_DOUBLED" in os.environ:
    E.JUMP_DOUBLED[MODE] = os.environ["DIS_JUMP_DOUBLED"] not in ("", "0")
# ...and whether the classic opener may pass (both passing throws the hand in).
if "DIS_OPENER_PASS" in os.environ:
    E.OPENER_MAY_PASS[MODE] = os.environ["DIS_OPENER_PASS"] not in ("", "0")
if "DIS_FLAT_MAKE" in os.environ:
    E.FLAT_MAKE_BONUS[MODE] = int(os.environ["DIS_FLAT_MAKE"])
if "DIS_FLAT_MIN" in os.environ:
    E.FLAT_MAKE_MIN_LEVEL = int(os.environ["DIS_FLAT_MIN"])
if "DIS_FLAT_SET" in os.environ:
    E.FLAT_SET_PENALTY[MODE] = int(os.environ["DIS_FLAT_SET"])
#: `<k>` or `<kA>:<kB>` -- per-tier world counts, so a tier can be measured at
#: the budget it would actually deploy with (Expert's 3s allowance buys k=8
#: where Hard's latency target picked 3). The resolver ignores k entirely.
#:
#: A trailing `p` (e.g. `8p`) runs that tier THE WAY THE BROWSER DOES: four
#: worker processes, each with its own quarter of the worlds and its own seed
#: stream, per-option sums added, argmax over the total. For Hard's linear
#: pricing that is identical to one process with the combined k; for Expert's
#: tree it is NOT -- four independent 2-world trees summed are a different
#: computation from one 8-world tree, and a measurement of the second says
#: nothing certain about shipping the first. The Duel campaign paid for this
#: lesson already ("a measurement harness must reproduce the SERVING shape").
K = sys.argv[2] if len(sys.argv) > 2 else "3"
K_A, _, K_B = K.partition(":")
K_B = K_B or K_A
POOL_N = 4


def _kspec(spec):
    return (int(spec[:-1]) // POOL_N, POOL_N) if spec.endswith("p") else (int(spec), 1)
N = int(sys.argv[3]) if len(sys.argv) > 3 else 60
TIER_A = sys.argv[4] if len(sys.argv) > 4 else "expert"
TIER_B = sys.argv[5] if len(sys.argv) > 5 else "hard"
LO = int(sys.argv[6]) if len(sys.argv) > 6 else 0
HI = int(sys.argv[7]) if len(sys.argv) > 7 else N
RESOLVE = sys.argv[8] if len(sys.argv) > 8 else "dd"
assert RESOLVE in ("dd", "play"), RESOLVE

PROC = {}


def proc_for(key, k=None, seed=0):
    if key not in PROC:
        PROC[key] = subprocess.Popen([BIN, str(k), "18", str(seed)],
                                     stdin=subprocess.PIPE,
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
    # `double` joins kontra/re here, per main.py: all three are the DEFENDER
    # betting on the DECLARER's settled contract, so the solve is from the
    # declarer's side and only the sign belongs to the asker. `DIS_OLD_DBL=1`
    # ships the pre-2026-08-14 field (the acting seat) so the bug can be
    # arena'd against its own fix rather than argued about.
    settled = ("kontra", "re") if os.environ.get("DIS_OLD_DBL") else ("double", "kontra", "re")
    auc = {"phase": g["phase"],
           "declarer": (g["auction"]["declarer"] if g["phase"] in settled else seat),
           "options": opts}
    # ATTRIBUTION ARM. The 2026-08-14 Double work was two changes at once -- the
    # declarer field above, and pricing the settled contract by an exact solve
    # instead of the points proxy. `DIS_PROXY_DBL=1` keeps the first and drops
    # the second by OMITTING `phase`, which is exactly what a server older than
    # the routing sends, so the searcher takes its own back-compat path rather
    # than a special one built for the harness.
    if os.environ.get("DIS_PROXY_DBL") and g["phase"] == "double":
        auc.pop("phase")
    # THE DOUBLE'S TWO KNOBS, MIRRORING main.py's shipped config so the arena
    # measures the room rather than something adjacent to it. Both are ON, and
    # both have an off switch because the control arm has to stay reachable:
    # `DIS_BID_PRIOR=0` drops the belief prior (uniform world sampling, i.e.
    # every run before 2026-08-14) and `DIS_DBL_MARGIN=<x>` re-doses or, at 0,
    # removes the doubling threshold.
    #
    # An `o` anywhere in a tier's SUFFIX ("expertot") is the OLD DOUBLE: neither
    # knob, i.e. the tier exactly as it stood before 2026-08-14. That is what
    # makes a STRENGTH measurement of this work possible at all -- self-play
    # mirrors read exactly +0.0000 by construction, so the two arms have to
    # differ, and a global env var cannot make them. It deliberately keeps the
    # declarer-side FIX, which is a bug fix rather than a knob.
    old_double = "o" in tier[len("expert"):] if tier.startswith("expert") else False
    if g["phase"] == "double" and not old_double:
        if os.environ.get("DIS_BID_PRIOR", "1") not in ("", "0"):
            prior = B.bid_prior_terms(g)
            if prior:
                auc["bid_prior"] = prior
        margin = float(os.environ.get("DIS_DBL_MARGIN",
                                      M.DOUBLE_MARGIN.get(MODE, 0.0)))
        if margin:
            auc["double_margin"] = margin
    if tier.startswith("expert") and g["phase"] == "auction":
        s = E.auction_search_payload(g)
        if s:
            # `expertm` is Expert with the MYOPIC opponent model -- the harness
            # injects the optional wire field the server does not send yet, so
            # the two models can be arena'd against each other before either
            # becomes the shipped default.
            if "m" in tier[len("expert"):]:
                s["rules"]["opp_model"] = "myopic"
            # `experts` -- the SOFT opponent model (2026-08-14). The tree runs
            # from our information set, so its modelled opponent sees our hand
            # and always finds the punishing reply; `soft` prices them as good
            # rather than clairvoyant. DIS_OPP_TEMP is per-world payoff points,
            # and 0 IS today's Expert exactly, so the A/B cannot be confounded.
            if "s" in tier[len("expert"):]:
                s["rules"]["opp_model"] = "soft"
                s["rules"]["opp_temp"] = float(os.environ.get("DIS_OPP_TEMP", "4"))
            # `expertd` -- DIVERSE CONTINUATIONS (2026-08-19), Brown/Sandholm/
            # Amos multi-valued states. The opponent commits to one of
            # `DIS_OPP_N` hand-blind strategies spanning a bias toward conceding
            # through a bias toward contesting, and the node takes the worst of
            # them for us. `soft` blurs the clairvoyant min; this changes WHICH
            # replies are on the menu instead.
            #
            # A spread of 0 collapses to `myopic` in the Rust (every bias is 0
            # and the dedupe folds them), which is a tier this crate has already
            # measured -- so the knob has a known null rather than an undefined
            # one. It is checked AFTER `s` so a tier naming both takes diverse,
            # and no shipped tier names both.
            if "d" in tier[len("expert"):]:
                s["rules"]["opp_model"] = "diverse"
                s["rules"]["opp_spread"] = float(os.environ.get("DIS_OPP_SPREAD", "6"))
                s["rules"]["opp_n"] = int(os.environ.get("DIS_OPP_N", "3"))
            auc["search"] = s
    # A trailing `t` on either tier name adds the TALON MODEL -- the fitted
    # swap weights the server ships on classic auction requests -- so the
    # model can be measured against its own absence before it is the default.
    # STRIP THE `o` BEFORE ASKING ABOUT `t`. `"expertto".endswith("t")` is
    # False, so an unstripped check silently drops the talon model from the
    # bias arm -- which would make the comparison two changes wide and read as
    # the bias doing something it did not.
    base = tier[:-1] if tier.endswith("b") else tier
    if base.endswith("t") and g["phase"] == "auction" and E.mode_of(g) == "classic":
        auc["swap"] = B.swap_policy_terms()
    # A trailing `b` adds the OPENING BIAS, the same way: an arm the tier name
    # turns on, so it can be measured against its own absence. `DIS_OPEN_BIAS`
    # sets the weight; the bias itself returns None when the weight is 0, so a
    # tier without the suffix is byte-identical to one before this existed.
    #
    # `b`, NOT `o`, AND THAT IS A BUG FIX. The bias shipped on `o`, which
    # `old_double` above already claimed -- `"o" in "to"` is True, so `expertto`
    # silently ran the OLD Double as well, making the arm two changes wide and
    # crediting the bias with whatever the Double lost. Exactly the failure the
    # `t`-stripping note above warns about, committed one suffix later. Any
    # `expertto` number recorded before 2026-08-16 is bias + old-Double pooled.
    if tier.endswith("b") and g["phase"] == "auction":
        bias = B.open_bias_terms(g, seat, opts)
        if bias:
            auc["open_bias"] = bias
    per_k, nproc = _kspec(K_A if tier == TIER_A else K_B)
    req = json.dumps({"view": E.view_for(g, seat), "auction": auc}) + "\n"
    sums = None
    # NON-AUCTION asks (double / kontra / declare) go to a SEPARATE process.
    # bidserve's Solved cache is one slot; a double ask keys differently (other
    # declarer, no swap field) and EVICTS the auction entry -- harmless in
    # serving, where the auction is over before the double arrives, but this
    # harness replays the same deal twice, and the second flip's auction then
    # re-solved fresh worlds off an advanced seed. With the talon model's extra
    # per-world variance that flipped the odd argmax and broke the mirror
    # (hardt-hardt read -1.67 where hard-hard read exactly 0). Splitting the
    # channels restores flip determinism and changes no measured answer.
    chan = "auc" if g["phase"] == "auction" else "aux"
    for i in range(nproc):
        p = proc_for((chan, tier, seat, i), k=per_k, seed=i * 7919)
        p.stdin.write(req)
        p.stdin.flush()
        res = json.loads(p.stdout.readline())
        part = res.get("sums")
        if not part or len(part) != len(opts):
            return None, None, None
        sums = part if sums is None else [a + b for a, b in zip(sums, part)]
    i = max(range(len(opts)), key=lambda j: sums[j])
    o = opts[i]
    mv = o.get("move")
    if o.get("decline") and not sums[i] > 0:
        mv = o["decline"]
    return mv, sums, opts


def play(m, tier_of, qual, events):
    """One round: the auction by the tiers, the talon by the server bot, the
    resolution per `RESOLVE`.

    Returns `(margin_for_declarer_sign, declarer, fingerprint)` or None. The
    fingerprint is the full auction log plus the doubled flag -- everything
    downstream of those is deterministic (the server bot's swap included), so
    two flips with equal fingerprints had IDENTICAL rounds and their pair is
    exactly zero by construction.

    `events` collects HOW each tier bid, attributed to the tier that made the
    decision -- the strength number says who won, these say what they did:

    * per auction decision, the corrected sacrifice taxonomy (a chosen bid is a
      SACRIFICE only when a pass was on offer and the search still priced the
      bid negative -- a forced classic opening is not a choice, and on a bad
      hand every option prices negative, where taking the least-bad is simply
      correct play);
    * the OPENING level, per tier;
    * the Double answer, per tier;
    * per settled round, the level, the declaring tier, the doubled flag, and
      the OUTCOME under exact play -- classified by resolving the contract
      twice, with and without the Null consolation: made iff the null-less
      value is positive, Null iff the consolation strictly improved on it.
    """
    g = E.new_game(["a", "b"], random.Random(600000 + m), opener=m % 2, mode=MODE)
    # THE REDEAL'S OWN RNG, seeded per DEAL and not per flip. A pass-out throws
    # the hand in and deals again; with production's fresh entropy the two
    # flips of one deal would draw DIFFERENT replacements and the pairing --
    # the whole point of the harness -- would silently break. Seeded here, both
    # flips replay the same replacement, and the mirror still reads +0.0000.
    redeal_rng = random.Random(900000 + m)
    # HOW EACH SEAT'S LAST BID WAS PRICED BY ITS OWN SEARCH. The seat still
    # holding a bid at the end is the declarer, so this is what lets a settled
    # round be attributed to the decision that produced it -- "was the contract
    # this seat is about to play one it priced NEGATIVE" is the join the tier
    # counters cannot make, and it is the only way to tell a deliberate
    # sacrifice apart from a raise the search genuinely liked. Keyed by SEAT
    # rather than tier on purpose: in a mirror both tiers are the same string.
    last_bid_kind = {}
    # Did the seat that acted FIRST in the current auction pass? Under
    # OPENER_MAY_PASS the opening is a real choice, so this is the rate the
    # experiment exists to measure. Reset by a redeal, since the replacement
    # deal has its own opening decision.
    opener_passed = False
    guard = 0
    while g["phase"] not in ("play", "over") and guard < 40:
        guard += 1
        seat = E.turn_seat(g)
        mv = None
        if g["phase"] in ("auction", "declare", "kontra", "re", "double"):
            phase_now = g["phase"]
            opening = phase_now == "auction" and not g["auction"]["log"]
            mv, sums, opts = ask(g, seat, tier_of[seat])
            if mv is not None and sums is not None:
                tier = tier_of[seat]
                if phase_now == "auction":
                    best = max(range(len(sums)), key=lambda j: sums[j])
                    has_pass = any(o["move"]["kind"] == "pass" for o in opts)
                    if mv.get("kind") == "bid":
                        kind = ("forced_open" if not has_pass
                                else "sacrifice" if sums[best] < 0 else "bid_positive")
                    else:
                        kind = "passed"
                    events.append(("decision", tier, kind))
                    if mv.get("kind") == "bid":
                        last_bid_kind[seat] = kind
                    if opening and mv.get("kind") == "bid":
                        events.append(("open", tier,
                                       mv.get("level") or mv.get("value"),
                                       mv.get("denom", -1)))
                    # THE OPENER'S PASS, and the pass-out it can lead to --
                    # the two rates the OPENER_MAY_PASS experiment is for.
                    if opening and mv.get("kind") == "pass":
                        opener_passed = True
                        events.append(("openpass", tier))
                elif phase_now == "double" and os.environ.get("ARENA_DEALS"):
                    # THE POSITION AT THE DOUBLE, for re-fitting the belief
                    # prior against EXPERT-driven auctions. The tilt map was
                    # fitted on auctions the SERVER bot bid, and that bot scores
                    # hands on the same rank curve the probe measures with -- so
                    # the two share a yardstick and the magnitude is inflated
                    # even though the direction is not. Recording the position
                    # here re-fits it against the bidder that actually plays.
                    #
                    # Off unless asked for: it is the biggest thing in a
                    # checkpoint line by far, and no other report reads it.
                    events.append(("deal", tier_of[g["auction"]["declarer"]],
                                   g["auction"]["declarer"],
                                   g["auction"]["level"], g["auction"]["denom"],
                                   [sorted(h) for h in g["hands"]],
                                   [[list(x) for x in q] for q in g["piles"]]))
                if phase_now == "double" and mv.get("kind") == "double":
                    # ...WITH THE SEARCH'S OWN TWO NUMBERS, so the doubling
                    # THRESHOLD can be swept offline instead of costing a run
                    # per value. The decision is `on - off > margin x k`, and
                    # neither sum depends on the margin, so a recorded pair
                    # prices every threshold exactly -- the same "label the
                    # decisions once, evaluate any policy for free" method
                    # `swaplab` uses for the talon.
                    on = next((i for i, o in enumerate(opts)
                               if o["move"].get("on")), None)
                    off = next((i for i, o in enumerate(opts)
                                if not o["move"].get("on")), None)
                    events.append(("double", tier, bool(mv.get("on")),
                                   None if on is None else sums[on],
                                   None if off is None else sums[off],
                                   len(g["auction"]["log"])))
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
                    # Per-world normalised; a pooled spec's TOTAL k is what the
                    # summed sums are proportional to. (The first version did
                    # int("4p") here and killed all four shards -- and the
                    # mirror never covers this line, because it only runs on
                    # the HARD flip of a mixed pairing.)
                    per, np_ = _kspec(K_B if TIER_B == "hard" else K_A)
                    qual[m] = max(bids) / max(1, per * np_)
        if mv is None:
            kind, p = B.act(g, seat, random.Random(m))
            mv = ({"kind": "pass"} if p.get("pass")
                  else {"kind": "bid", **{a: b for a, b in p.items() if a != "pass"}}) \
                if kind == "bid" else (p if kind == "move"
                                       else ({"kind": "swap", **p} if kind == "swap" else p))
        redeals_before = g.get("redeals", 0)
        E.apply_move(g, g["seats"][seat], mv, redeal_rng)
        if g.get("redeals", 0) > redeals_before:
            # Both seats passed it out: the hand is thrown in and re-dealt in
            # place, so every per-auction counter starts again.
            events.append(("passout", tier_of[seat]))
            opener_passed = False
            last_bid_kind = {}
    if g["phase"] != "play":
        return None
    fp = json.dumps([g["auction"]["log"], bool(g.get("doubled"))])
    terms = E.payoff_terms(g)
    decl = terms["declarer"]
    if RESOLVE == "dd":
        deal = {"hands": [list(h) for h in g["hands"]],
                "piles": [[list(x) for x in row] for row in g["piles"]],
                "trump": g["auction"]["denom"], "leader": decl}
        p = proc_for("resolver", k=1)

        def solve(t):
            p.stdin.write(json.dumps({"resolve": {**deal, "terms": t}}) + "\n")
            p.stdin.flush()
            r = json.loads(p.stdout.readline())
            if "payoff" not in r:
                raise SystemExit(f"deal {m}: unresolvable ({r})")   # harness bug, be loud
            return r["payoff"]

        payoff = solve(terms)
        # The OUTCOME, from a second solve with the consolation off the table.
        # `contract_from_json` reads a missing `null` as None, so this is the
        # pure contract value: positive means MADE under exact play (every make
        # pays at least its base), and the full solve beating it means the
        # optimum went through Null.
        nonull = solve({k: v for k, v in terms.items() if k != "null"})
        outcome = "null" if payoff > nonull else ("made" if nonull > 0 else "set")
        # The whole trajectory: what was opened, by whom, where it settled, who
        # took it there. `log[0]` is the opening bid; the opener may not pass in
        # classic, so it is always a bid entry.
        first = g["auction"]["log"][0] if g["auction"].get("log") else {}
        # ...and how LONG the auction ran: bids only, so a lone opening that
        # was passed out reads 1, however many passes surround it.
        n_bids = sum(1 for e in g["auction"]["log"] if not e.get("pass"))
        events.append(("settled", tier_of[decl],
                       g["auction"]["level"] or g["auction"]["value"],
                       outcome, bool(g.get("doubled")),
                       first.get("level") or first.get("value") or 0,
                       tier_of.get(first.get("seat"), "?"),
                       # ...and the DENOMINATION it settled in. `open_denom`
                       # covered the opening only, so "the spread of final
                       # bids" could be read by level and not by suit.
                       g["auction"]["denom"],
                       # ...and HOW THE DECLARER'S OWN SEARCH PRICED the bid it
                       # is about to play. `sacrifice` means it chose a bid it
                       # had priced negative over an available pass.
                       last_bid_kind.get(decl, "?"),
                       n_bids,
                       # ...and the round's exact-play PAYOFF, signed for the
                       # declarer, so a report can average what each side was
                       # actually paid per (level, outcome, doubled) rather
                       # than only counting outcomes.
                       payoff,
                       # ...and the auction's LEVEL SEQUENCE (bids only, in
                       # order), which is what the jump-size distribution and
                       # the raise-by-how-much question read. Classic levels;
                       # skat values ride the same slot.
                       [e.get("level") or e.get("value") or 0
                        for e in g["auction"]["log"] if not e.get("pass")],
                       # ...and whether the seat on turn first PASSED the
                       # opening (OPENER_MAY_PASS only), so the profile can be
                       # split by it rather than only counted.
                       opener_passed))
        return payoff, decl, fp
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
stats = {t: {"opens": collections.Counter(), "decisions": collections.Counter(),
             "doubles": collections.Counter(), "declared": collections.Counter(),
             "outcome": collections.Counter(), "open_denom": collections.Counter(),
             "settled_denom": collections.Counter(),
             "by_price": collections.Counter(),
             "auction_len": collections.Counter(),
             "traject": collections.Counter()} for t in {TIER_A, TIER_B}}
#: deal -> {tier: opening level}. The CRN pairing puts BOTH tiers on the same
#: opener hand (same seat, same deal, flips swap only which tier sits there),
#: so this is a same-hand joint distribution of the two policies' openings.
joint = {}

#: CHECKPOINT FILE, and it is why a killed run is no longer a lost run. A shard
#: printed its `SHARD {...}` only at the very end, so being killed at minute 19
#: of 21 cost EVERYTHING -- which is exactly what happened when the container
#: was reclaimed mid-run. One JSON line per completed DEAL, appended and
#: flushed, so a kill costs at most the deal in flight; on restart the finished
#: deals are replayed from the file and skipped.
#:
#: Off unless `ARENA_CKPT` names a path: the default behaviour is byte-for-byte
#: what it was, and a checkpoint that silently appeared next to the code would
#: be its own surprise. The file is keyed by the caller, so a shard must be
#: given its OWN path -- two shards sharing one would resume each other's deals.
#:
#: A RESUMED RUN IS NOT BIT-IDENTICAL to an uninterrupted one, and that is a
#: property of `bidserve`, not of this file: it advances a seed stream per
#: REQUEST (`bin/bidserve.rs`), so skipping already-finished deals shifts the
#: seed of every later one and the searcher samples different worlds. The
#: resumed deals are an equally valid sample -- the seed is independent of the
#: cards -- so means and distributions are unbiased, but do not expect the same
#: numbers twice. VERIFIED that this is all it is: a kill-and-resume over the
#: same window reproduces the same TOTALS (same deal count, same number of
#: openings) with a different split, which is what a reseed looks like and not
#: what double-counting looks like. Making it exact means sending a per-deal
#: seed in the request, which is a Rust change and has not been done.
CKPT = os.environ.get("ARENA_CKPT")


def _absorb(deal_events):
    """Fold one deal's events into the running counters.

    Called from BOTH the live loop and the checkpoint replay, so a resumed run
    and an uninterrupted one aggregate through the same code. A second copy
    here is how a resumed run quietly reports different numbers.
    """
    for events in deal_events:
        opened_this_flip = None
        for e in events:
            if e[0] == "decision":
                stats[e[1]]["decisions"][e[2]] += 1
            elif e[0] == "open":
                stats[e[1]]["opens"][e[2]] += 1
                stats[e[1]]["open_denom"][f"{e[2]}:{e[3]}"] += 1
                opened_this_flip = (e[1], e[2])
            elif e[0] == "double":
                stats[e[1]]["doubles"]["on" if e[2] else "off"] += 1
            elif e[0] == "settled":
                stats[e[1]]["declared"][e[2]] += 1
                stats[e[1]]["outcome"][f"{e[2]}:{e[3]}"] += 1
                if len(e) > 7:
                    stats[e[1]]["settled_denom"][f"{e[2]}:{e[7]}"] += 1
                if len(e) > 8:
                    stats[e[1]]["by_price"][f"{e[8]}:{e[2]}:{e[3]}"] += 1
                if len(e) > 9:
                    stats[e[1]]["auction_len"][e[9]] += 1
                if e[4]:
                    stats[e[1]]["doubles"]["suffered"] += 1
                # The TRAJECTORY, attributed to the OPENER's tier: opened at
                # e[5], settled at e[2], and whether the opener kept it. This is
                # the open->settled matrix -- the only way to tell "a level is
                # rare because nobody opens there" from "it never survives".
                if len(e) > 6 and e[6] in stats:
                    stats[e[6]]["traject"][f"{e[5]}>{e[2]}:{'kept' if e[6] == e[1] else 'lost'}:{e[3]}"] += 1
        if opened_this_flip is not None:
            yield opened_this_flip


done = set()
if CKPT and os.path.exists(CKPT):
    with open(CKPT, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                # A half-written last line is the normal shape of a kill, not a
                # corrupt file. Drop it and re-play that one deal.
                continue
            done.add(r["m"])
            pairs.append(r["pair"])
            qof.append(r["q"])
            if r["differ"]:
                diff_pairs.append(r["pair"])
            for tier, lvl in _absorb(r["events"]):
                joint.setdefault(r["m"], {})[tier] = lvl
    print(f"  resumed {len(done)} deals from {CKPT}", flush=True)

ck = open(CKPT, "a", encoding="utf-8") if CKPT else None
for m in range(LO, HI):
    if m in done:
        continue
    got = []
    deal_events = []
    for flip in (0, 1):
        tier_of = {flip: TIER_A, 1 - flip: TIER_B}
        events = []
        out = play(m, tier_of, qual, events)
        if out is None:
            continue
        deal_events.append(events)
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
    for tier, lvl in _absorb(deal_events):
        joint.setdefault(m, {})[tier] = lvl
    pair = (got[0][0] + got[1][0]) / 2
    pairs.append(pair)
    qof.append(qual.get(m, 0.0))
    differ = got[0][1] != got[1][1]
    if differ:
        diff_pairs.append(pair)
    if ck:
        # FLUSHED per deal. An OS buffer holding the last 20 deals when the
        # process is killed is the same lost work this exists to prevent.
        ck.write(json.dumps({"m": m, "pair": pair, "q": qual.get(m, 0.0),
                             "differ": differ, "events": deal_events}) + "\n")
        ck.flush()
    if (m + 1) % 20 == 0 and pairs:
        mu, se = _stat(pairs)
        print(f"  {m + 1:4} deals  {TIER_A} - {TIER_B} = {mu:+.4f} "
              f"[{mu - 1.96 * se:+.2f}, {mu + 1.96 * se:+.2f}]  "
              f"({len(diff_pairs)}/{len(pairs)} differ)", flush=True)
if ck:
    ck.close()

mu, se = _stat(pairs)
print(f"\n{MODE} k={K} resolve={RESOLVE}: {TIER_A} - {TIER_B} = {mu:+.4f} +- {se:.4f} "
      f"payoff/round over {len(pairs)} paired deals"
      + (f" ({dropped} one-sided drops discarded)" if dropped else ""))
print(f"[ARM] FLAT_MAKE_BONUS = {E.FLAT_MAKE_BONUS.get(MODE, 0)}, "
      f"FLAT_SET_PENALTY = {E.FLAT_SET_PENALTY.get(MODE, 0)}"
      + (f" from level {E.FLAT_MAKE_MIN_LEVEL}" if E.FLAT_MAKE_MIN_LEVEL > 1 else ""))
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
                             "dropped": dropped,
                             "stats": {t: {k: dict(v) for k, v in d.items()}
                                       for t, d in stats.items()},
                             "joint": [[v.get(TIER_A), v.get(TIER_B)]
                                       for v in joint.values()
                                       if TIER_A in v and TIER_B in v]}))
for p in PROC.values():
    p.stdin.close()
