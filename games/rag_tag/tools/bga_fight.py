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

    BGA's `locationArg` is a board SLOT, not our track INDEX: it numbers the space printed
    "1" as slot 1, so every alive slot reads as the printed HP and the spaces below run 0,
    -1, -2. Nine of the ten fighters have exactly one space under "1", so index and slot
    coincide and the distinction never shows; Maman Brijit has three (two KOs and a revive),
    so our index ran two ahead of her all game -- a systematic 2 in games that otherwise
    reproduce perfectly, which is the signature of an encoding mismatch, not a rules bug.
    `_slot` derives the offset per track rather than assuming it.

    A marker that is not touched in a turn keeps its position, so the state is carried
    forward rather than rebuilt; only markers of `type: "health"` count.

    The key carries the TRACK NUMBER off `marker.location` ("TheFeyFolk_track_2"), because
    the Fey Folk have one health track per Character and Bodvar has a second for the Bear.
    Their retired tracks sit on 0 forever, so comparing our live fighter against "whichever
    marker moved" scored the Fey Folk wrong from the turn their first Character died.
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
            where = str(m.get("location", "")).split("_track_")
            fid = BGA_TO_FID.get(where[0])
            if fid is None or len(where) != 2 or not where[1].isdigit():
                continue
            if m.get("type") == "health":
                state[(fid, int(where[1]))] = m.get("locationArg")
            elif m.get("type") == "special":
                # A fighter has at most one special track, so it needs no numbering: Joan's
                # Divine Voice dial, Bodvar's Rage, Ching Shih's Ships, the Fey Folk's
                # Spirits. Worth comparing because it is upstream of Power -- Joan's dial
                # pays her, and a dial one step out puts every Attack she makes one light.
                state[(fid, "special")] = m.get("locationArg")
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
        st = {}
        for s in (0, 1):
            for t in (0, 1):
                f = game["fighters"][s][t]
                fid = game["teams"][s][t]
                st[(fid, _track_no(f))] = _slot(f)
                spec = engine._board(f).get("special_track")
                if spec:
                    st[(fid, "special")] = f["tracks"].get(spec["id"])
        snaps.append((game["round"], game["turn"], st))
        return beat

    engine._resolve_turn = spy
    try:
        r = tt_replay.replay(path, row)
    finally:
        engine._resolve_turn = real
    return snaps, r


def _slot(f):
    """Our track index expressed as BGA's board SLOT.

    BGA numbers a health track so that the space printed "1" is slot 1, which makes every
    alive slot read as the printed HP -- and the spaces BELOW it run 0, -1, -2. Our tracks
    carry a different number of spaces under "1" (Maman Brijit has three: two KOs and a
    revive), so the offset has to be derived rather than assumed, and printed HP alone
    cannot tell her two KO spaces apart (886310308 ends with BGA reporting her on -1).
    """
    track = engine.track_of(f)
    if not track or f.get("hp") is None:
        return 0
    one = next((i for i, sp in enumerate(track)
                if sp["kind"] == "hp" and sp.get("hp") == 1), None)
    return f["hp"] - one + 1 if one is not None else engine.hp_value(f)


def _track_no(f):
    """Which of BGA's numbered health tracks this fighter's marker is on right now.

    One for almost everyone. The Fey Folk get one per Character in board order, and Bodvar's
    Bear gets a second -- matching `fighterSpecificState.activeTrack`, the same 1-based
    numbering the replayer already reads Character choices from.
    """
    board = engine._board(f)
    chars = board.get("characters") or []
    if chars:
        return next((i + 1 for i, c in enumerate(chars) if c["id"] == f.get("character")), 1)
    return 2 if f.get("face") == "berserker_bear" else 1


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
        for key, hp in want.items():
            if key not in got:                   # a track that is not the live one
                continue
            total += 1
            if got[key] == hp:
                agreed += 1
            elif first_bad is None:
                first_bad = (i + 1, key[0] + ("*" if key[1] == "special" else ""),
                             got[key], hp)
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
        for key, hp in sorted(want.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
            if key not in got:
                continue
            val = got[key]
            tag = key[0] if key[1] != "special" else key[0] + "*"
            cells.append(f"{tag}:{val}" + ("" if val == hp else f"!={hp}"))
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
