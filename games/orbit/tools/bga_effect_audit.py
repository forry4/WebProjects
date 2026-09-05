"""Audit each card's EFFECT KINDS against what BGA produced in real games.

The companion to `bga_card_audit.py`, which checks costs. This checks what a card DOES.

HOW A CARD'S EFFECTS ARE ISOLATED
---------------------------------
BGA does not bracket a card with its consequences in one packet -- a card with a choice
resolves over several `move_id`s. The unit is a TURN SEGMENT: from `moveCard` (location
`play`) up to the next `setHandSize`, which is the end-of-turn draw.

Getting that boundary wrong is not a small error. A first cut ran each segment to the next
CARD PLAY, which swallowed the rest of the turn and the opponent's entire turn after it;
every card then appeared to produce credits and influence, and the audit "found" that most
of the deck was mistranscribed. Calibrated against cards whose answer is known first:

    502  influence(2), zenithium(2), leader(2)  -> movePlanet, deltaSolium, updateLeader
    507  influence(1, terra), leader()          -> movePlanet x2, updateLeader
    104  influence(1, mars), leader()           -> movePlanet, updateLeader

WHAT IS AMBIENT AND CANNOT BE ATTRIBUTED
----------------------------------------
Some effects appear in a segment without the card causing them, so they are excluded from
the verdict rather than counted as evidence either way:

  influence     every card advances its OWN planet when played, so this is always present
  gain_planet   filling a track captures the planet -- downstream of influence
  reset_planet  the same capture, resetting the discs
  bonus         a captured planet pays a bonus token
  credits       turn income and refunds land inside the segment

The remaining kinds -- zenithium, leader, mobilize, transfer, develop, discard, and the
opponent-directed ones -- are things a card does deliberately, and those are compared.

THE VERDICT IS ONE-DIRECTIONAL, like the cost audit. A kind our card cannot produce but
BGA produced is worth looking at. The reverse says nothing: an `optional` or `if_leader`
branch that never fired in three games is not a missing effect.

Usage::

    python -m games.orbit.tools.bga_effect_audit [--corpus <dir>] [--verbose]
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys

from games.orbit import cards as C
from games.orbit import effects as E

DEFAULT_CORPUS = os.environ.get("ZENITH_CORPUS", "C:/Users/Forrest/Zenith_corpus")
GOODIES = frozenset({119, 120, 219, 220, 319, 320, 419, 420, 519, 520})

#: Events that say nothing about what a card did.
NOISE = frozenset({
    "gameStateChange", "updateReflexionTime", "lastMove", "showCurTech", "info", "logs",
    "gameStateMultipleActiveUpdate", "simpleNode", "updateBonusDeck", "setPlayerCounter",
    "undo", "gameover", "moveCard", "playCardDiploTech",
})

#: BGA event -> the effect kind it is evidence of.
EVENT_KIND = {
    "deltaSolium": "zenithium", "stealSolium": "zenithium", "giveSolium": "zenithium",
    "deltaCredits": "credits", "stealCredits": "credits", "giveCredits": "credits",
    "movePlanet": "influence", "updateLeader": "leader", "mobilize": "mobilize",
    "transfer": "transfer", "setTech": "develop", "gainBonus": "bonus",
    "resetPlanet": "reset_planet", "gainPlanet": "gain_planet", "discardCard": "discard",
}

#: Our task type -> the same vocabulary.
TASK_KIND = {
    "credits": "credits", "zenithium": "zenithium", "influence": "influence",
    "influence_other": "influence", "split_influence": "influence",
    "adjacent_three": "influence", "leader": "leader", "mobilize": "mobilize",
    "transfer": "transfer", "transfer_each": "transfer", "develop": "develop",
    "draw_bonus": "bonus", "take_board_bonus": "bonus", "reset_planet": "reset_planet",
    "discard_hand": "discard", "exile": "discard", "exile_tier": "discard",
    "optional_exile_each": "discard",
}

#: Kinds that turn up in a segment without the card causing them -- see the docstring.
#:
#: `leader` was a candidate and is deliberately NOT here, because it discriminates:
#: measured over the clean segments, cards that DECLARE a leader effect show
#: `updateLeader` in 13 of 15, and cards that do not show it in 1 of 74. Dropping it into
#: AMBIENT would have silenced the only finding this audit has.
AMBIENT = frozenset({"influence", "gain_planet", "reset_planet", "bonus", "credits"})

#: Wrappers whose CHILDREN are the real effects.
WRAPPERS = ("then", "tasks", "effects")


def declared_kinds(tasks, out=None):
    """Every kind a card can produce, through every optional / choice branch."""
    out = set() if out is None else out
    for task in tasks or ():
        if not isinstance(task, dict):
            continue
        kind = TASK_KIND.get(task.get("type"))
        if kind:
            out.add(kind)
        # A generic task can name its payout in a `resource` or `reward` field.
        for field in ("resource", "reward"):
            value = task.get(field)
            if isinstance(value, str) and TASK_KIND.get(value):
                out.add(TASK_KIND[value])
            elif isinstance(value, dict) and TASK_KIND.get(value.get("resource")):
                out.add(TASK_KIND[value["resource"]])
        for key in WRAPPERS:
            declared_kinds(task.get(key), out)
        # `choose_branch` keeps its alternatives under `branches`, each a {label, tasks}.
        # Missing this made three `choose` cards declare NOTHING, which the audit then
        # reported as unaccounted effects -- the parser accusing the data of its own gap.
        for branch in task.get("branches") or ():
            if isinstance(branch, dict):
                declared_kinds(branch.get("tasks"), out)
        cost = task.get("cost")
        if isinstance(cost, dict):
            res = str(cost.get("resource", ""))
            if res.startswith("zenithium"):
                out.add("zenithium")
            elif res.startswith("credits"):
                out.add("credits")
            elif res.startswith("leader"):
                out.add("leader")
        for opt in task.get("options") or ():
            if isinstance(opt, (list, tuple)) and len(opt) == 2:
                declared_kinds(opt[1], out)
            elif isinstance(opt, dict):
                declared_kinds(opt.get("then"), out)
    return out


def segments(path):
    """(card_id, [events]) per turn segment: a play up to the end-of-turn draw."""
    by = collections.defaultdict(list)
    for packet in json.load(open(path, encoding="utf-8")):
        for event in packet.get("data") or []:
            by[int(packet["move_id"])].append(event)

    out, current, card = [], [], None
    for move_id in sorted(by):
        for event in by[move_id]:
            kind = event.get("type")
            if kind == "moveCard" and (event.get("args") or {}).get("location") == "play":
                if card is not None:
                    out.append((card, current))
                raw = (event.get("args") or {}).get("card_num")
                card = int(raw) if raw not in (None, "") else None
                current = []
            elif kind == "setHandSize":
                if card is not None:
                    out.append((card, current))
                card, current = None, []
            elif card is not None and kind not in NOISE:
                current.append(event)
    if card is not None:
        out.append((card, current))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--verbose", action="store_true", help="list every card")
    args = ap.parse_args(argv)

    paths = sorted(glob.glob(args.corpus + "/logs/*.json"))
    if not paths:
        print(f"no logs in {args.corpus}/logs")
        return 1

    # ONLY CLEAN SEGMENTS COUNT, and this is what makes the number mean anything.
    #
    # TECH_EFFECTS and BONUS_EFFECTS between them reach EVERY kind in the vocabulary. So
    # the moment a segment contains a tech advance or a bonus token, "the card could have
    # caused this downstream" is true of almost any effect, and the comparison stops
    # discriminating -- it would score cards as clean by being unable to accuse them.
    #
    # A segment is scored only if nothing in it can fan out like that: no `setTech`, no
    # `gainBonus`, and no `gainPlanet` (a capture pays a bonus). What is left is a card
    # play and the effects that are genuinely its own.
    FANOUT = {"setTech", "gainBonus", "gainPlanet"}
    observed = collections.defaultdict(set)
    plays, clean_plays = collections.Counter(), collections.Counter()
    used = skipped = 0
    for path in paths:
        segs = segments(path)
        if any(card in GOODIES for card, _ in segs):
            skipped += 1
            continue
        used += 1
        for card, events in segs:
            if card is None or card not in C.CARDS:
                continue
            plays[card] += 1
            if any(e.get("type") in FANOUT for e in events):
                continue
            clean_plays[card] += 1
            for event in events:
                kind = EVENT_KIND.get(event.get("type"))
                if kind:
                    observed[card].add(kind)

    agree, review = [], []
    for card in sorted(observed):
        seen = observed[card] - AMBIENT
        ours = declared_kinds(E.CARD_EFFECTS.get(card))
        extra = seen - ours
        (review if extra else agree).append((card, seen, ours, extra))

    print(f"{used} base-game logs ({skipped} skipped: Secret Agents)")
    print(f"cards played: {len(plays)} of {len(C.CARDS)}, {sum(plays.values())} plays")
    print(f"  of which CLEANLY attributable: {len(clean_plays)} cards, "
          f"{sum(clean_plays.values())} plays")
    print(f"  (a segment with a tech advance, a bonus or a planet capture is discarded:"
          f" those chains reach every kind and would score a card clean by being unable"
          f" to accuse it)\n")
    print(f"EFFECT KINDS (ambient excluded: {', '.join(sorted(AMBIENT))})")
    print(f"  produced nothing our card cannot : {len(agree)}")
    print(f"  produced something unaccounted   : {len(review)}   <- review, not verdict")

    for card, seen, ours, extra in review:
        print(f"    card {card} {C.CARDS[card]['name']!r}")
        print(f"      unaccounted : {', '.join(sorted(extra))}")
        print(f"      we declare  : {', '.join(sorted(ours)) or '(nothing)'}")
        print(f"      rule        : {C.CARDS[card]['rule']}")
    if args.verbose:
        print("\nall cards:")
        for card, seen, ours, _ in sorted(agree + review):
            print(f"  {card:>4} {C.CARDS[card]['name'][:18]:<19} "
                  f"seen={','.join(sorted(seen)) or '-':<34} ours={','.join(sorted(ours)) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
