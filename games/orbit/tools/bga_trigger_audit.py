"""Audit the cards the other audits CANNOT judge: the ones whose effect is a trigger.

`bga_effect_audit` discards any segment containing a tech advance, a bonus token or a
planet capture, because `TECH_EFFECTS` and `BONUS_EFFECTS` reach every kind in the
vocabulary and a card cannot be accused once one fires. That is right, and it leaves a
hole shaped exactly like eight cards whose WHOLE effect is to fire one:

    develop           208 AS1M0V, 210 Doc Wissen, 211 BR4DBURY,
                      212 Archimedes, 214 BUJ0LD
    draw_bonus        107 ORW3LL, 108 Guy Gambler
    take_board_bonus  417 Handy Luke

For these the useful question is the opposite one. The other audits ask "did this card
produce something it CANNOT?" -- unanswerable here, since the trigger legitimately
produces anything. This asks "did it produce the specific thing it DECLARES?", which for
a develop card is a sharp question with an arithmetic answer.

THE PAYMENT IS THE MEASUREMENT, AND IT WAS CALIBRATED FIRST
-----------------------------------------------------------
`engine.py` charges `max(0, old_level + 1 - discount)` zenithium, i.e. `max(0, new_level
- discount)`. BGA logs that as the `deltaSolium` immediately preceding the `setTech` for
the same player.

Before trusting that reading it was checked where the answer is already known -- the 545
ORDINARY advances taken as the `technology` action, whose discount is zero. All 545 match.
Only then were the discounted card advances measured against it.

    plain (action)  545 payments, discount 0
    card 208         14 payments, discount 2
    card 210         23           discount 1
    card 211         26           discount 1
    card 212         22           discount 1
    card 214         18           free
                    ---
                    648 payments, 0 mismatches

The first attempt at this scoped the lookup to a single `move_id` and reported 102
mismatches, all of them `paid = step - 1` or `step - 2`. They were card advances: a card
play and the `setTech` it causes sit in DIFFERENT moves of the same segment, so the card
was invisible and its discount was read as a divergence. The same segment/move confusion
the effect audit's boundary bug came from.

WHAT EACH CHECK CAN AND CANNOT SAY
----------------------------------
* payment    -- arithmetic, and the sharpest thing in any of these audits.
* faction    -- only where the card names one (210 human, 211 robot, 212 animod).
* lowest     -- 214 says "one of your LOWEST technologies", checked by rebuilding each
                player's three tech levels from the `setTech` stream.
* bonus      -- weak on purpose: a token was gained. `draw_bonus` and `take_board_bonus`
                differ in WHERE the token comes from, and the log does not say, so this
                cannot separate 107/108 from 417 and does not pretend to.
* 107's rider -- "7 additional Credits if you give the Leader badge" is conditional, so it
                is scored BOTH ways: with a leader hand-over there must be +7, without one
                there must not be.

A card that declares a trigger and produced nothing is reported separately, never as a
defect: a player can be unable to afford an advance, or have nothing left to raise.

Usage::

    python -m games.orbit.tools.bga_trigger_audit [--corpus <dir>] [--verbose]
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

#: Ends the segment a card play opened -- the same three the effect audit uses.
BOUNDARY = {"setHandSize", "undo", "playCardDiploTech"}

#: BGA's `race_name` -> our faction key.
RACE = {"robot": "robot", "human": "human", "animod": "animod"}

#: Card 107's rider.
LEADER_RIDER_CARD = 107
LEADER_RIDER_CREDITS = 7

TRIGGERS = ("develop", "draw_bonus", "take_board_bonus")


#: A trigger nested under one of these fires only when a condition holds, so its ABSENCE
#: proves nothing. Card 108 is the case that forced this: "gain 1 BONUS token IF YOU HAVE
#: the Leader badge" was read as an unconditional draw, and seven perfectly correct plays
#: without the badge were reported as a card failing to do what it declares.
CONDITIONAL = ("if_leader", "if_credits", "optional", "choose_branch")


def trigger_of(card_id):
    """-> (trigger task, conditional?) for a card, or (None, False)."""
    found = []

    def walk(tasks, guarded):
        for task in tasks or ():
            if not isinstance(task, dict):
                continue
            inner = guarded or task.get("type") in CONDITIONAL
            if task.get("type") in TRIGGERS:
                found.append((task, guarded))
            for key in ("then", "tasks", "effects"):
                walk(task.get(key), inner)
            for branch in task.get("branches") or ():
                if isinstance(branch, dict):
                    walk(branch.get("tasks"), True)
            for opt in task.get("options") or ():
                if isinstance(opt, (list, tuple)) and len(opt) == 2:
                    walk(opt[1], True)
                elif isinstance(opt, dict):
                    walk(opt.get("then"), True)

    walk(E.CARD_EFFECTS.get(card_id), False)
    return found[0] if found else (None, False)


def walk_log(path):
    """Yield (card_being_resolved_or_None, event) in move order.

    Mirrors `bga_effect_audit.segments`: a play opens a segment, `setHandSize` / `undo` /
    `playCardDiploTech` close it. Packets with no `move_id` are a live table's
    `wakeupPlayers` nudges and carry no state.
    """
    grouped = collections.defaultdict(list)
    for packet in json.load(open(path, encoding="utf-8")):
        if packet.get("move_id") is None:
            continue
        grouped[int(packet["move_id"])].extend(packet.get("data") or [])

    card = None
    for move_id in sorted(grouped):
        for event in grouped[move_id]:
            kind = event.get("type")
            args = event.get("args") or {}
            if kind == "moveCard" and args.get("location") == "play":
                try:
                    card = int(args.get("card_num"))
                except (TypeError, ValueError):
                    card = None
            elif kind in BOUNDARY:
                card = None
                yield None, event      # the caller needs to see undo / setHandSize
            else:
                yield card, event


def audit_log(path, stats, findings):
    """One log: every trigger a card claimed, against what the game did."""
    pending_payment = {}                       # player -> last deltaSolium seen
    levels = collections.defaultdict(lambda: collections.defaultdict(int))
    # AN UNDONE ADVANCE DID NOT HAPPEN, and the reconstructed levels have to know it.
    # This is the third time `undo` has produced a false finding in these audits, each
    # time wearing a different hat: it stitched a retracted play onto a later action in
    # the effect audit, and here it left a retracted TECH ADVANCE in the level model --
    # so card 214 was accused of raising a track that was not its lowest, when the track
    # it "already had" had been taken back 60 moves earlier. Journal every advance made
    # since the last end-of-turn draw and roll the journal back on `undo`; BGA re-emits
    # the real advance afterwards, which re-applies cleanly.
    journal = []
    seen_bonus = set()                         # cards that produced a token this segment
    leader_moved = set()
    credits_7 = set()
    open_card = None
    abandoned = False

    for card, event in walk_log(path):
        kind = event.get("type")
        args = event.get("args") or {}
        # THE FLAG MUST BE SET BEFORE THE CLOSE, not after. `undo` arrives as an event
        # with no card, which itself triggers the close below -- so setting `abandoned`
        # in the handler further down marked the NEXT segment, and the retracted one was
        # still scored. Four correct plays of card 107 were reported as failures twice
        # over because of this.
        if kind in ("undo", "playCardDiploTech"):
            abandoned = True

        if card != open_card:
            _close(open_card, seen_bonus, leader_moved, credits_7, stats, findings,
                   abandoned)
            open_card, seen_bonus, leader_moved, credits_7 = card, set(), set(), set()
            abandoned = False

        if kind == "undo":
            for pid, faction, was in reversed(journal):
                levels[pid][faction] = was
            journal = []
            continue

        if kind == "setHandSize":
            journal = []                       # the turn stands
            continue

        if kind == "deltaSolium":
            pending_payment[str(args.get("player_no"))] = args.get("nb")
            continue

        if kind == "setTech":
            pid = str(args.get("player_no"))
            faction = RACE.get(str(args.get("race_name", "")).lower())
            try:
                step = int(args.get("step"))
            except (TypeError, ValueError):
                continue
            paid = pending_payment.pop(pid, None)
            before = dict(levels[pid])
            if faction:
                journal.append((pid, faction, levels[pid][faction]))
                levels[pid][faction] = step
            task, _cond = trigger_of(card) if card else (None, False)
            if task is None or task.get("type") != "develop":
                stats["plain advances"] += 1
                if paid is not None and int(paid) != step:
                    findings.append((None, f"a plain advance to {step} cost {paid}"))
                continue

            stats[f"card {card} develops"] += 1
            discount = task.get("discount", 0)
            expected = max(0, step - discount)
            if paid is None:
                stats[f"card {card} no payment logged"] += 1
            elif int(paid) != expected:
                findings.append((card, f"advance to {step} cost {paid}, "
                                       f"discount {discount} implies {expected}"))
            else:
                stats[f"card {card} payment matches"] += 1

            named = task.get("faction")
            if named:
                if faction == named:
                    stats[f"card {card} faction matches"] += 1
                else:
                    findings.append((card, f"names {named} but advanced {faction}"))

            if task.get("lowest"):
                # "one of your LOWEST technologies": the track raised must have been at
                # the minimum before it moved. Levels are rebuilt from the setTech stream,
                # every faction starting at 0.
                floor = min(before.get(f, 0) for f in C.FACTIONS)
                if before.get(faction, 0) == floor:
                    stats[f"card {card} raised a lowest track"] += 1
                else:
                    findings.append((card, f"raised {faction} at {before.get(faction, 0)} "
                                           f"when its lowest was {floor}"))
            continue

        if kind == "gainBonus" and card:
            seen_bonus.add(card)
        elif kind == "updateLeader" and card:
            leader_moved.add(card)
        elif kind == "deltaCredits" and card:
            try:
                if int(args.get("nb")) == LEADER_RIDER_CREDITS:
                    credits_7.add(card)
            except (TypeError, ValueError):
                pass

    _close(open_card, seen_bonus, leader_moved, credits_7, stats, findings,
           abandoned)


def _close(card, seen_bonus, leader_moved, credits_7, stats, findings, abandoned=False):
    """Score the bonus-drawing cards when their segment ends.

    An ABANDONED segment is not scored. A play taken back by `undo`, or a card spent as a
    diplo/tech resource instead of played, produced nothing and must not be read as a card
    failing to do what it declares -- which is exactly how four correct plays of card 107
    were first reported.
    """
    if card is None or abandoned:
        return
    task, conditional = trigger_of(card)
    if task and task.get("type") in ("draw_bonus", "take_board_bonus"):
        if card in seen_bonus:
            stats[f"card {card} took a token"] += 1
        elif conditional:
            stats[f"card {card} condition not met, no token"] += 1
        else:
            stats[f"card {card} declared a token, none seen"] += 1

    if card == LEADER_RIDER_CARD:
        # Scored BOTH ways: the rider fires only when the badge changes hands.
        gave = card in leader_moved
        paid = card in credits_7
        if gave and paid:
            stats["card 107 rider taken, +7 paid"] += 1
        elif not gave and not paid:
            stats["card 107 rider declined, no +7"] += 1
        elif gave and not paid:
            findings.append((107, "gave the Leader badge but no +7 Credits"))
        else:
            findings.append((107, "+7 Credits without giving the Leader badge"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--verbose", action="store_true", help="list every counter")
    args = ap.parse_args(argv)

    paths = sorted(glob.glob(args.corpus + "/logs/*.json"))
    if not paths:
        print(f"no logs in {args.corpus}/logs")
        return 1

    stats, findings = collections.Counter(), []
    for path in paths:
        audit_log(path, stats, findings)

    cards = sorted({int(k.split()[1]) for k in stats if k.startswith("card ")})
    print(f"{len(paths)} logs\n")
    print("TRIGGER CARDS -- did each produce what it declares?")
    print(f"  {'card':<6} {'name':<15} {'declares':<34} evidence")
    for card in cards:
        task, conditional = trigger_of(card)
        task = task or {}
        what = task.get("type", "?") + (" (conditional)" if conditional else "")
        if what == "develop":
            what += (f" {task.get('faction') or 'any'}"
                     f", discount {'free' if task.get('discount', 0) > 5 else task.get('discount', 0)}"
                     f"{', lowest' if task.get('lowest') else ''}")
        bits = [f"{v} {k.split(' ', 2)[2]}" for k, v in sorted(stats.items())
                if k.startswith(f"card {card} ")]
        print(f"  {card:<6} {C.CARDS[card]['name'][:14]:<15} {what:<34} {'; '.join(bits)}")

    print(f"\n  plain advances (the calibration, discount 0) : {stats['plain advances']}")
    for key in ("card 107 rider taken, +7 paid", "card 107 rider declined, no +7"):
        if stats[key]:
            print(f"  {key:<44} : {stats[key]}")
    print(f"\n  DISAGREEMENTS : {len(findings)}   <- review, not verdict")
    for card, note in findings[:15]:
        label = f"card {card} {C.CARDS[card]['name']!r}" if card else "plain advance"
        print(f"    {label}: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
