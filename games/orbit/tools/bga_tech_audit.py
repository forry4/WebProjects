"""Audit the TECHNOLOGY ladder and the BONUS TOKENS against real BGA games.

The fourth alignment-free audit, and it covers the two systems the other three had to
throw away. `bga_effect_audit` discards any segment containing a tech advance or a bonus
token, on the grounds that `TECH_EFFECTS` and `BONUS_EFFECTS` between them reach every
kind in the vocabulary -- so a card cannot be accused once one fires. That is the right
call there, and it leaves both systems unexamined. This is where they get examined.

THE BONUS TOKENS CHECK THEMSELVES
---------------------------------
`gainBonus` carries `bonus_num` AND `bonus_desc` -- BGA's own words for what the token
does. So the eight tokens need no inference at all: compare the text.

THE TECH LADDER IS AN A/B, NOT A COMPARISON
-------------------------------------------
Two things stand between the log and a verdict, and the second turns out to be a feature.

1. The board is DOUBLE-SIDED. `TECH_EFFECTS` is keyed `(faction, side, level)` and the
   side is chosen at setup; `setTech` reports `race` and `step` but no side. The default
   `SUN_CONFIGURATION` is all-1s and real tables clearly are not (measured below), so the
   side has to be inferred.

2. Our engine resolves a tech advance CUMULATIVELY and downward: reaching level 4 fires
   4, then 3, then 2, then 1 (`_develop_tasks`, `range(level, 0, -1)`). That is a strong
   reading of the rule, and the obvious rival -- only the new level fires -- would look
   identical on a first advance and diverge sharply later.

Inferring a side and then declaring agreement would be circular, so the audit is built as
a CONTEST between those two readings instead. For each game and faction it asks which
sides remain possible under each reading, where a side is possible only if it explains
EVERY advance of that faction in that game -- both players', since the board is shared.
One bit of freedom against up to five levels of consequence is a real constraint, and the
two readings are scored on the same evidence. A reading that survives where the other dies
has earned something; a reading that survives only because it can explain anything has not.

WHAT COUNTS AS EXPLAINABLE
--------------------------
A tech resolution legitimately draws bonus tokens (`draw_bonus` at several levels, plus
the fixed token every faction pays at level 2). That is not the fan-out the card audit
guards against, because the log says WHICH token: `bonus_num` names it, so its declared
effects come from `BONUS_EFFECTS` and stay accountable.

`influence` IS ambient here, and finding that out cost a wrong answer. Treating it as
evidence made robot and animod impossible on every single log -- while a hand check of
those same logs matched the ladder step for step. The reason is the rule the magnitude
audit measured at 85 of 85: a card entering a column advances that column's planet. A
`mobilize` puts cards into columns, so any ladder step that mobilizes drags influence
along behind it regardless of its own `influence_each`. Planet captures are ambient for
the same downstream reason.

What is left still discriminates: mobilize, transfer, discard, zenithium, credits and
leader are what actually separate the two readings below.

Usage::

    python -m games.orbit.tools.bga_tech_audit [--corpus <dir>] [--verbose]
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
from games.orbit.tools.bga_effect_audit import EVENT_KIND, GOODIES, declared_kinds

DEFAULT_CORPUS = os.environ.get("ZENITH_CORPUS", "C:/Users/Forrest/Zenith_corpus")

#: BGA's `race_name` -> our faction key.
RACE = {"robot": "robot", "human": "human", "animod": "animod"}

#: The sides a physical board can be set up on.
SIDES = (1, 2)

#: Ends a tech resolution. `undo` and `playCardDiploTech` are here for the reason
#: `bga_effect_audit.segments` documents at length: they are boundaries, not noise.
BOUNDARY = {"moveCard", "setHandSize", "undo", "playCardDiploTech", "setTech"}

#: Says nothing about what resolved.
NOISE = frozenset({
    "gameStateChange", "updateReflexionTime", "lastMove", "showCurTech", "info", "logs",
    "gameStateMultipleActiveUpdate", "simpleNode", "updateBonusDeck", "setPlayerCounter",
    "gameover",
})

#: Kinds a tech resolution can produce without the ladder being the reason.
#:
#: `influence` is here for the same reason the card audit has it, and it is the same
#: rule: a card entering a column advances that column's planet. The magnitude audit
#: measured exactly that for card PLAYS (85 of 85 segments open with the card's own
#: planet, +1), and a `mobilize` puts cards into columns too -- so any ladder step that
#: mobilizes drags influence along behind it, whatever its own `influence_each` says.
#: Treating it as evidence made robot and animod look impossible on every log while a
#: hand check of the same logs matched the ladder exactly.
#:
#: `gain_planet` / `reset_planet` are a filled track capturing a planet, downstream again.
AMBIENT = frozenset({"influence", "gain_planet", "reset_planet"})


def advances(path):
    """-> [(faction, level, player, [events])] for every tech advance in a log."""
    grouped = collections.defaultdict(list)
    for packet in json.load(open(path, encoding="utf-8")):
        for event in packet.get("data") or []:
            grouped[int(packet["move_id"])].append(event)

    out, current, head = [], [], None
    for move_id in sorted(grouped):
        for event in grouped[move_id]:
            kind = event.get("type")
            args = event.get("args") or {}
            if kind == "setTech":
                if head:
                    out.append(head + (current,))
                faction = RACE.get(str(args.get("race_name", "")).lower())
                try:
                    level = int(args.get("step"))
                except (TypeError, ValueError):
                    level = None
                head = (faction, level, str(args.get("player_no")))
                current = []
            elif kind in BOUNDARY:
                if head:
                    out.append(head + (current,))
                head, current = None, []
            elif head and kind not in NOISE:
                current.append(event)
    if head:
        out.append(head + (current,))
    return [row for row in out if row[0] and row[1]]


def observed_kinds(events):
    """-> (kinds seen, bonus token numbers drawn)."""
    kinds, tokens = set(), []
    for event in events:
        kind = EVENT_KIND.get(event.get("type"))
        if kind:
            kinds.add(kind)
        if event.get("type") == "gainBonus":
            raw = (event.get("args") or {}).get("bonus_num")
            if raw not in (None, ""):
                tokens.append(int(raw))
    return kinds, tokens


def explainable(faction, side, level, tokens, cumulative):
    """Every kind the ladder could produce for this advance, under one reading."""
    levels = list(range(level, 0, -1)) if cumulative else [level]
    kinds = set(AMBIENT)
    for resolved in levels:
        kinds |= declared_kinds(E.TECH_EFFECTS.get((faction, side, resolved)))
        # Level 2 pays the faction's fixed token, and that is `_develop_tasks` doing it,
        # not TECH_EFFECTS -- so it has to be added here or the ladder gets blamed for a
        # bonus it never declared. Note this is a REAL asymmetry between the two
        # readings: reaching level 5 pays it under ours and not under the rival.
        if resolved == 2:
            kinds.add("bonus")
    # A drawn token is NAMED in the log, so its effects stay accountable rather than
    # becoming the fan-out the card audit has to discard.
    for token in tokens:
        kinds |= declared_kinds(E.BONUS_EFFECTS.get(token))
    return kinds


def audit_bonus_text(paths):
    """-> (matches, mismatches, seen) comparing BGA's own token wording with ours."""
    matches, mismatches, seen = 0, [], set()
    for path in paths:
        for packet in json.load(open(path, encoding="utf-8")):
            for event in packet.get("data") or []:
                if event.get("type") != "gainBonus":
                    continue
                args = event.get("args") or {}
                raw = args.get("bonus_num")
                if raw in (None, ""):
                    continue
                num = int(raw)
                seen.add(num)
                theirs = str(args.get("bonus_desc") or "").strip()
                ours = str(C.BONUS_TYPES.get(num, {}).get("description") or "").strip()
                if theirs and theirs == ours:
                    matches += 1
                else:
                    mismatches.append((num, theirs, ours))
    return matches, mismatches, seen


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--verbose", action="store_true", help="show every advance")
    args = ap.parse_args(argv)

    paths = sorted(glob.glob(args.corpus + "/logs/*.json"))
    if not paths:
        print(f"no logs in {args.corpus}/logs")
        return 1

    base = []
    for path in paths:
        rows = advances(path)
        if not rows:
            continue
        with open(path, encoding="utf-8") as fh:
            cards = {int((d.get("args") or {}).get("card_num") or 0)
                     for p in json.load(fh) for d in p.get("data") or []
                     if d.get("type") == "moveCard"}
        if cards & GOODIES:
            continue
        base.append((os.path.basename(path), rows))

    print(f"{len(base)} base-game logs, "
          f"{sum(len(rows) for _, rows in base)} tech advances\n")

    matches, mismatches, seen = audit_bonus_text(paths)
    print("BONUS TOKENS (BGA states its own wording, so this needs no inference)")
    print(f"  token gains seen         : {matches + len(mismatches)}")
    print(f"  distinct tokens          : {len(seen)} of {len(C.BONUS_TYPES)}")
    print(f"  description matches ours : {matches}")
    print(f"  disagrees                : {len(mismatches)}")
    for num, theirs, ours in mismatches[:8]:
        print(f"    token {num}: BGA {theirs!r} / ours {ours!r}")

    # THE CONTEST. Each reading gets the same evidence and the same one bit of freedom.
    totals = collections.Counter()
    detail = []
    for name, rows in base:
        by_faction = collections.defaultdict(list)
        for faction, level, player, events in rows:
            by_faction[faction].append((level, player, events))
        for faction, entries in sorted(by_faction.items()):
            fits = {}
            for cumulative in (True, False):
                ok = []
                for side in SIDES:
                    if all(
                        (observed_kinds(events)[0] - AMBIENT)
                        <= explainable(faction, side, level,
                                       observed_kinds(events)[1], cumulative)
                        for level, _player, events in entries
                    ):
                        ok.append(side)
                fits[cumulative] = ok
            detail.append((name, faction, len(entries), fits[True], fits[False]))
            totals["cumulative_unique"] += len(fits[True]) == 1
            totals["cumulative_none"] += not fits[True]
            totals["single_unique"] += len(fits[False]) == 1
            totals["single_none"] += not fits[False]

    print("\nTECH LADDER: which reading survives the evidence?")
    print("  our engine resolves level L then L-1 ... down to 1 (cumulative);")
    print("  the rival reading fires only level L.\n")
    print(f"  {'log':<20} {'faction':<9} {'advances':>8}  {'cumulative':>12}"
          f"  {'level-L only':>13}")
    for name, faction, n, cum, single in detail:
        fmt = lambda s: ("side " + "/".join(map(str, s))) if s else "IMPOSSIBLE"
        print(f"  {name:<20} {faction:<9} {n:>8}  {fmt(cum):>12}  {fmt(single):>13}")

    groups = len(detail)
    print(f"\n  cumulative : {totals['cumulative_none']}/{groups} impossible, "
          f"{totals['cumulative_unique']}/{groups} pinned to one side")
    print(f"  level-L    : {totals['single_none']}/{groups} impossible, "
          f"{totals['single_unique']}/{groups} pinned to one side")
    if totals["cumulative_none"] == 0 and totals["single_none"] > 0:
        print("\n  => the logs CONTRADICT the level-L-only reading and are consistent")
        print("     with ours, on every faction of every game.")
    elif totals["cumulative_none"]:
        print("\n  => our reading is contradicted somewhere <- review, not verdict")
    else:
        print("\n  => both readings survive; this evidence does not separate them")

    if args.verbose:
        print("\nadvances:")
        for name, rows in base:
            for faction, level, player, events in rows:
                kinds, tokens = observed_kinds(events)
                print(f"  {name} p{player} {faction} -> {level}: "
                      f"{','.join(sorted(kinds)) or '-'}"
                      f"{'  tokens ' + str(tokens) if tokens else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
