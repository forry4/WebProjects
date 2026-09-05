"""Audit each card's effect MAGNITUDES against what BGA produced in real games.

The third of the alignment-free audits, and the sharpest of them:

    bga_card_audit.py       what a card COST
    bga_effect_audit.py     what KINDS of effect it produced
    bga_magnitude_audit.py  how MUCH, and onto which planet   <- this file

It reuses `bga_effect_audit.segments` -- the same turn segment, the same fan-out
exclusion, the same Secret Agents skip -- so only the comparison is new.

THE OPENING INFLUENCE, WHICH THE KINDS AUDIT ASSUMED
----------------------------------------------------
That audit treats `influence` as ambient, on the stated grounds that "every card advances
its OWN planet when played". That was an assumption carrying a lot of weight, so this file
MEASURES it: the first `movePlanet` of a segment should be the played card's own planet,
+1. It is reported as a rate, and any exception is named rather than averaged away.

WHAT A CARD CAN GRANT IS A SET, NOT A NUMBER
--------------------------------------------
Half the deck's payouts are computed rather than printed, and each computes over a
knowable set:

    exile_tier          exile 2/4/7 cards -> 2/4/7 zenithium (or 1/2/3 influence)
    card_cost           "gain its cost in Credits" -> the cost of SOME card in the deck
    per_nonempty        "2 Credits per track" -> BGA pays 2 per track, at most five times
    influence_each      one grant of 1 per mobilized card
    matching_influence  one grant of 1 per exiled / transferred card

So the check is MEMBERSHIP, not equality: a magnitude BGA produced that our card cannot
produce at all is a finding. The reverse -- a declared amount never seen -- says nothing,
the same one-directional rule the cost audit settled.

WHAT IS DELIBERATELY NOT CHECKED
--------------------------------
`restriction` -- and this one is worth writing down, because the obvious reading is wrong.
`middle` looks like it means the three middle planets, and card 409's observed grants
(Terra, Mars, Venus) would have "confirmed" that beautifully. It does not: `engine.py`
reads it as *tracks whose disc sits at zero*, which is a position in the game state and
cannot be recovered from a log with no setup dump. Hardcoding the plausible reading would
have produced a confident agreement between two things that were never compared.

Usage::

    python -m games.orbit.tools.bga_magnitude_audit [--corpus <dir>] [--verbose]
"""

from __future__ import annotations

import argparse
import collections
import glob
import os
import sys

from games.orbit import cards as C
from games.orbit import effects as E
from games.orbit.tools.bga_effect_audit import GOODIES, segments

DEFAULT_CORPUS = os.environ.get("ZENITH_CORPUS", "C:/Users/Forrest/Zenith_corpus")

#: Segments containing these cannot be attributed -- see `bga_effect_audit`.
FANOUT = {"setTech", "gainBonus", "gainPlanet"}

#: Mirrors the `exile_tier` branch of `engine.py`: exiling 2/4/7 cards pays 2/4/7
#: zenithium, or 1/2/3 influence.
TIER_REWARD = {"zenithium": (2, 4, 7), "influence": (1, 2, 3)}

#: A card play advances its own planet by this much, before anything the card says.
OPENING = 1

#: `per_nonempty` pays per track, and there are only ever five tracks.
MAX_TRACKS = len(C.PLANETS)


def _walk(tasks, fn):
    """Every task a card can reach, through optional / choice / branch nesting."""
    for task in tasks or ():
        if not isinstance(task, dict):
            continue
        fn(task)
        for key in ("then", "tasks", "effects"):
            _walk(task.get(key), fn)
        for branch in task.get("branches") or ():
            if isinstance(branch, dict):
                _walk(branch.get("tasks"), fn)
        for opt in task.get("options") or ():
            if isinstance(opt, (list, tuple)) and len(opt) == 2:
                _walk(opt[1], fn)
            elif isinstance(opt, dict):
                _walk(opt.get("then"), fn)


def grantable(card_id):
    """-> {influence, planets, zenithium, credits}, everything the card COULD produce.

    `planets` is None when the card lets the player choose, which constrains nothing.
    """
    influence, zenithium, credits = set(), set(), set()
    planets = set()
    free_choice = False
    costs = {card["cost"] for card in C.CARDS.values()}

    def visit(task):
        nonlocal free_choice
        kind = task.get("type")
        amount = task.get("amount")
        reward = task.get("reward")

        if kind in ("influence", "influence_other", "all_planets"):
            if isinstance(amount, int):
                influence.add(amount)
            if task.get("planet"):
                planets.add(task["planet"])
            else:
                free_choice = True
        for value in task.get("amounts") or ():          # split_influence
            influence.add(value)
            free_choice = True
        if kind == "split_influence":
            free_choice = True
        if task.get("center") is not None:               # adjacent_three
            influence.add(task["center"])
            influence.add(task.get("neighbor"))
            free_choice = True
        if kind == "zenithium" and isinstance(amount, int):
            zenithium.add(amount)
        if kind == "credits" and isinstance(amount, int):
            credits.add(amount)
        if kind == "per_nonempty" and isinstance(amount, int):
            credits.add(amount)                          # BGA pays it one track at a time
        if kind == "per_tech_first" and isinstance(amount, int):
            credits.update(amount * n for n in range(1, len(C.FACTIONS) + 1))
        if kind == "exile_tier":
            bucket = zenithium if reward == "zenithium" else influence
            for value in TIER_REWARD.get(str(reward), ()):
                bucket.add(value)
            if reward != "zenithium":
                free_choice = True
        if task.get("influence_each") or reward == "matching_influence":
            influence.add(1 if kind == "mobilize" else task.get("amount", 1))
            free_choice = True                           # the mobilized card names it
        if reward == "card_cost":
            credits.update(costs)
        if isinstance(reward, dict) and isinstance(reward.get("amount"), int):
            target = {"credits": credits, "zenithium": zenithium,
                      "influence": influence}.get(reward.get("resource"))
            if target is not None:
                target.add(reward["amount"])

    _walk(E.CARD_EFFECTS.get(card_id), visit)
    influence.discard(None)
    return {
        "influence": influence,
        "planets": None if free_choice or not planets else planets,
        "zenithium": zenithium,
        "credits": credits,
    }


def constrains(can, widest):
    """Is this set narrow enough that an observation could have contradicted it?

    Empty means the card declares no payout of that kind, so there is nothing to compare
    against. Equal to `widest` means the payout is "the cost of some card", which every
    real cost satisfies. Neither is a check.
    """
    return bool(can) and can != widest


def observed(events):
    """-> (movePlanet [(planet, nb)], zenithium gains, credit gains).

    Only POSITIVE deltas are gains. A negative one is the card being paid for, which
    lands inside the segment because the segment opens at the play.
    """
    moves, zenithium, credits = [], [], []
    for event in events:
        args = event.get("args")
        if not isinstance(args, dict):
            continue
        try:
            nb = int(args.get("nb", 0))
        except (TypeError, ValueError):
            continue
        kind = event.get("type")
        if kind == "movePlanet":
            moves.append((str(args.get("planet_name") or "").lower(), nb))
        elif kind == "deltaSolium" and nb > 0:
            zenithium.append(nb)
        elif kind == "deltaCredits" and nb > 0:
            credits.append(nb)
    return moves, zenithium, credits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--verbose", action="store_true", help="describe each card flagged")
    args = ap.parse_args(argv)

    paths = sorted(glob.glob(args.corpus + "/logs/*.json"))
    if not paths:
        print(f"no logs in {args.corpus}/logs")
        return 1

    opening_ok = opening_bad = opening_none = 0
    bad_openings = []
    findings = collections.defaultdict(set)
    checked, unconstrained = collections.Counter(), collections.Counter()
    used = skipped = clean = 0
    # The widest set any card can produce. A set this wide rules nothing out.
    all_amounts = {card["cost"] for card in C.CARDS.values()}

    for path in paths:
        used += 1
        for card, events in segments(path):
            if card in GOODIES:
                skipped += 1          # see GOODIES in bga_effect_audit: per segment
                continue
            if card is None or card not in C.CARDS:
                continue
            if any(e.get("type") in FANOUT for e in events):
                continue
            clean += 1
            moves, zenithium, credits = observed(events)
            can = grantable(card)
            own = C.CARDS[card]["planet"]

            if not moves:
                opening_none += 1
            elif moves[0] == (own, OPENING):
                opening_ok += 1
            else:
                opening_bad += 1
                bad_openings.append((card, own, moves[0]))

            # A COMPARISON THAT CANNOT FAIL IS NOT A COMPARISON, and there are two ways
            # to fail to constrain. A card that declares no payout of a kind has an
            # EMPTY set, and a `card_cost` reward ("gain its cost in Credits") admits
            # EVERY cost in the deck. Counting either would pad the total with
            # observations that were never at risk -- the same inflation the cost
            # audit's separate "only ever seen discounted" line exists to avoid.
            for planet, nb in moves[1:]:
                if constrains(can["influence"], all_amounts):
                    checked["influence"] += 1
                    if nb not in can["influence"]:
                        findings[card].add(
                            f"influence {nb} (can grant {sorted(can['influence'])})")
                else:
                    unconstrained["influence"] += 1
                if can["planets"] is not None:
                    checked["planet"] += 1
                    if planet not in can["planets"]:
                        findings[card].add(
                            f"influence onto {planet} (names {sorted(can['planets'])})")
                else:
                    unconstrained["planet"] += 1
            for nb in zenithium:
                if constrains(can["zenithium"], all_amounts):
                    checked["zenithium"] += 1
                    if nb not in can["zenithium"]:
                        findings[card].add(
                            f"zenithium {nb} (can grant {sorted(can['zenithium'])})")
                else:
                    unconstrained["zenithium"] += 1
            if len(credits) > MAX_TRACKS:
                findings[card].add(f"{len(credits)} separate credit gains "
                                   f"(nothing pays more than {MAX_TRACKS} times)")
            for nb in credits:
                if constrains(can["credits"], all_amounts):
                    checked["credits"] += 1
                    if nb not in can["credits"]:
                        findings[card].add(
                            f"credits {nb} (can grant {sorted(can['credits'])[:8]})")
                else:
                    unconstrained["credits"] += 1

    print(f"{used} logs ({skipped} Secret Agents segments skipped), "
          f"{clean} cleanly attributable segments\n")

    total = opening_ok + opening_bad
    print("OPENING INFLUENCE (the kinds audit assumes this; here it is measured)")
    print(f"  first movePlanet is the card's own planet, +1 : "
          f"{opening_ok}/{total or 'no data'}")
    print(f"  segments with no movePlanet at all            : {opening_none}")
    for card, own, saw in bad_openings[:10]:
        print(f"    card {card} {C.CARDS[card]['name']!r} is {own}, opened {saw}")

    print("\nMAGNITUDES (membership, not equality -- a card's payout is often computed)")
    print(f"  grants that COULD have failed : {checked['influence']} influence, "
          f"{checked['zenithium']} zenithium, {checked['credits']} credits, "
          f"{checked['planet']} named-planet")
    loose = ", ".join(f"{n} {k}" for k, n in sorted(unconstrained.items()) if n)
    print(f"  not counted, nothing to rule out : {loose or 'none'}")
    print(f"  cards producing a magnitude they cannot : {len(findings)}"
          f"   <- review, not verdict")
    for card in sorted(findings):
        print(f"    card {card} {C.CARDS[card]['name']!r}  [{C.CARDS[card]['rule']}]")
        for note in sorted(findings[card]):
            print(f"      {note}")
        if args.verbose:
            print(f"      desc: {C.CARDS[card]['description']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
