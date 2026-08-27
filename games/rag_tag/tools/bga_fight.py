"""Compare our fight, turn by turn, against BGA's own `fightLog`.

THE WINNER IS ONE BIT AT THE END OF A GAME. This is the same log read at full resolution:
BGA's `trackPositionUpdated` entries carry `marker.locationArg`, which IS our health-track
index (verified: every track matches slot-for-slot, so no mapping is needed), stamped with
the fight and the turn it happened on. So for every turn of every game we can ask "did the
same fighter end this turn on the same space?" and get a yes or no.

That turns a game our engine cannot finish into a bisect: the FIRST turn whose HP disagrees
is where the rules diverge, and everything after it is downstream noise.

CALIBRATE IT BEFORE YOU TRUST IT. An earlier per-turn damage comparison blamed EVERY card at
0.6-0.9, which cannot be true alongside 27 games reproducing exactly -- the instrument was
wrong, not the engine. So this tool reports its score on the games that ALREADY replay to the
recorded winner separately from the ones that do not. Those must read ~100%: they are games
where our engine and BGA agree about the whole result, so any turn-level disagreement there
is a bug in this file. Read that number first, every time.

  python -m games.rag_tag.tools.bga_fight            # the corpus, split pass/fail
  python -m games.rag_tag.tools.bga_fight <table_id> # one game, turn by turn
"""
import collections
import glob
import json
import os
import sys

from games.rag_tag import engine
from games.rag_tag.fighters import FIGHTERS
from games.rag_tag.tools import bga_inspect as tt_inspect
from games.rag_tag.tools import bga_replay as tt_replay

CORP = os.environ.get("TAGTEAM_CORPUS", "C:/Users/Forrest/TagTeam_corpus")
BGA_TO_FID = {v["bga_id"]: k for k, v in FIGHTERS.items()}


def _entries(events):
    """Every fightLog entry in the log, de-duplicated by (fight, log_id), in play order.

    The entries arrive spread over many `newPrivateState` packets that re-send overlapping
    slices of the same fight, so they have to be keyed rather than concatenated. `log_id` is
    a STRING in the log and sorting it as one interleaves turn 10 with turn 1 -- the kind of
    ordering bug that reads as a rules divergence.
    """
    out = {}
    for _mid, d in events:
        if d["type"] != "newPrivateState":
            continue
        a = d.get("args") or {}
        inner = a.get("args") if isinstance(a, dict) else None
        if not isinstance(inner, dict) or "fightLog" not in inner:
            continue
        for e in inner["fightLog"]:
            try:
                out[(int(e["fight_id"]), int(e["log_id"]))] = (e["type"],
                                                               json.loads(e["value"]))
            except Exception:                    # noqa: BLE001 — a malformed entry is not fatal
                continue
    return [(k, v) for k, v in sorted(out.items())]


def bga_turns(events):
    """[(fight, turn, {(fid, marker_id): printed_hp})] — health markers at each turn's END.

    BGA's `locationArg` is a board SLOT, and for every fighter in the corpus the alive slots
    read as the PRINTED HP: slot 16 is 16 health. That is not the same as our track INDEX.
    Nine of the ten fighters have exactly one space below "1 health", so index and printed HP
    coincide and the distinction never shows; Maman Brijit has three (two KOs and a revive),
    so our index runs two ahead of her printed HP all game.

    Comparing indices therefore scored her wrong on turn 1 of every game she appeared in --
    a systematic 2 in games that otherwise reproduce perfectly, which is the signature of an
    encoding mismatch rather than a rules bug. Compare PRINTED HP on both sides.

    A marker that is not touched in a turn keeps its position, so the state is carried
    forward rather than rebuilt; only markers of `type: "health"` count. `marker.id` is part
    of the key because Bodvar's Bear and the Fey Folk's Characters put more than one health
    marker on one fighter's board.
    """
    state, out, cur = {}, [], None
    for (fight, _log), (kind, v) in _entries(events):
        if kind == "cardsRevealed":
            cur = (fight, int(v["turnNumber"]))
        elif kind == "cardsFinished" and cur is not None:
            # CLOSE THE TURN AT `cardsFinished`, not at the next reveal. Health moves
            # between rounds -- an Instant Bonus off a card just built, "The Wild Bunch
            # heals The Wild Bunch for 1" -- and bucketing those with the turn before them
            # compares our end-of-turn state against BGA's end-of-BUILD state. It read as a
            # persistent off-by-one on The Wild Bunch in eight games. They still update the
            # carried state, so the next turn's snapshot has them.
            out.append((cur[0], cur[1], dict(state)))
            cur = None
        elif kind == "trackPositionUpdated":
            m = v.get("marker") or {}
            if m.get("type") != "health":
                continue
            fid = BGA_TO_FID.get(str(m.get("location", "")).split("_track_")[0])
            if fid is not None:
                state[(fid, m.get("id"))] = m.get("locationArg")
    return out


def bga_kos(events):
    """{(fight, turn): [payload, ...]} — every fighter BGA knocked out, and when."""
    out, cur = collections.defaultdict(list), None
    for (fight, _log), (kind, v) in _entries(events):
        if kind == "cardsRevealed":
            cur = (fight, int(v["turnNumber"]))
        elif kind == "knockedOut" and cur is not None:
            out[cur].append(v)
    return dict(out)


def our_turns(path, row):
    """([(round, turn, {(fid, 0): hp_index})], replay result) — our health after each turn.

    Taken by wrapping `_resolve_turn` rather than by reading `game["beats"]` at the end:
    beats are CLEARED every round (engine.py `_finish_build`), so an end-of-replay read
    compares one round against a whole game. That exact mistake once scored a 0.935
    agreement as 0.21.
    """
    snaps, real = [], engine._resolve_turn

    def spy(game, revealed, doubles=None):
        beat = real(game, revealed, doubles)
        snaps.append((game["round"], game["turn"],
                      {(game["teams"][s][t], 0): engine.hp_value(game["fighters"][s][t])
                       for s in (0, 1) for t in (0, 1)}))
        return beat

    engine._resolve_turn = spy
    try:
        r = tt_replay.replay(path, row)
    finally:
        engine._resolve_turn = real
    return snaps, r


def compare(path, row):
    """(agreed, total, first_bad, replay result, BGA turns, our turns)."""
    events = list(tt_inspect.events(path))
    theirs = bga_turns(events)
    ours, r = our_turns(path, row)
    # ALIGN BY (fight, turn), NEVER BY POSITION. BGA's fight_id is our round and its
    # turnNumber restarts with each fight, so the two sides carry the same key. Zipping the
    # lists instead drifts the moment either side plays a different number of turns -- which
    # is exactly the case this tool exists to diagnose, so positional alignment mismeasures
    # precisely the games that matter.
    mine = {(rd, tn): st for rd, tn, st in ours}
    agreed = total = 0
    first_bad = None
    for i, (_f, _t, want) in enumerate(theirs):
        got = mine.get((_f, _t))
        if got is None:
            continue
        for (fid, _mid), hp in want.items():
            if (fid, 0) not in got:              # a fighter we never had (parse divergence)
                continue
            if sum(1 for k in want if k[0] == fid) > 1:
                continue                         # multi-marker fighter: which track is live?
            total += 1
            if got[(fid, 0)] == hp:
                agreed += 1
            elif first_bad is None:
                first_bad = (i + 1, fid, got[(fid, 0)], hp)
    return agreed, total, first_bad, r, theirs, ours


def one(tid):
    row = json.load(open(f"{CORP}/manifest.json"))[tid]
    agreed, total, first_bad, r, theirs, ours = compare(f"{CORP}/logs/{tid}.json", row)
    pct = f" ({agreed / total:.1%})" if total else ""
    print(f"{tid}: hp agreement {agreed}/{total}{pct} | turns ours {len(ours)} "
          f"bga {len(theirs)} | winner_match {r['winner_match']} | {r['stopped']}")
    if first_bad:
        print(f"  FIRST DIVERGENCE at turn {first_bad[0]}: {first_bad[1]} "
              f"ours {first_bad[2]} vs BGA {first_bad[3]}")
    mine = {(rd, tn): st for rd, tn, st in ours}
    for i, (f, t, want) in enumerate(theirs):
        got = mine.get((f, t)) or {}
        cells = []
        for (fid, _m), hp in sorted(want.items()):
            val = got.get((fid, 0), "?")
            cells.append(f"{fid}:{val}" + ("" if val == hp else f"!={hp}"))
        print(f"  f{f} t{t}  " + "  ".join(cells))
    for (f, t), kos in sorted(bga_kos(list(tt_inspect.events(f"{CORP}/logs/{tid}.json")))
                              .items()):
        print(f"  BGA KO at f{f} t{t}: "
              + ", ".join(str(k.get("iconFighter", {}).get("typeArg")) for k in kos))
    return 0


def main():
    if len(sys.argv) > 1:
        return one(sys.argv[1])
    manifest = json.load(open(f"{CORP}/manifest.json"))
    tally = {True: [0, 0, 0], False: [0, 0, 0]}   # winner_match -> [agreed, total, games]
    rows = []
    for p in sorted(glob.glob(f"{CORP}/logs/*.json")):
        tid = os.path.basename(p)[:-5]
        row = manifest.get(tid)
        if not row:
            continue
        try:
            agreed, total, first_bad, r, theirs, ours = compare(p, row)
        except Exception as e:                   # noqa: BLE001 — never break the batch
            print(f"  {tid}: {type(e).__name__}: {e}")
            continue
        t = tally[bool(r["winner_match"])]
        t[0] += agreed
        t[1] += total
        t[2] += 1
        if not r["winner_match"]:
            rows.append((tid, agreed, total, first_bad, len(ours), len(theirs)))
    for match, label in ((True, "games that ALREADY replay to the recorded winner"),
                         (False, "games that do not")):
        a, n, g = tally[match]
        print(f"{label}: {a}/{n} ({a / n:.1%} of turns) over {g} games" if n
              else f"{label}: no turns")
    print("\nCALIBRATION: the first line must read ~100%. Below that, this tool is wrong.\n")
    for tid, a, n, bad, no, nt in sorted(rows):
        where = (f"turn {bad[0]}: {bad[1]} ours {bad[2]} vs BGA {bad[3]}" if bad
                 else "no HP divergence")
        print(f"  {tid}  hp {a}/{n}  turns {no}/{nt}  {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
