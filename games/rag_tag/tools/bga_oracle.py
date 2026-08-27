"""A per-turn STATE oracle for the Tag Team replayer.

Winner-only parity tells you a game diverged; it cannot tell you WHERE, and with fighters
whose abilities interact you need where. BGA's `updateCardAndFighterData` carries
`allFighters[].power` and `isKnockedOut`, refreshed as the game runs (observed: Golem
1 -> 4 -> 5 -> 6 across consecutive snapshots), and our engine holds exactly the same two
facts as `f["power"]` and `engine.is_ko(f)`. So they can be compared directly.

This is the CoB lesson applied: cob_replay.py only became score-exact because BGA logged a
running `score` on `tileAddedToEstate`, which acted as a bisect oracle -- all five bugs were
found by tracing it, and none by reading the rules. `power` is that field here.

ALIGNMENT: this module reports raw state; the LAG lives in bga_replay.do_check, which
compares our state at check i against BGA snapshot i+1. That offset is measured, not
assumed -- see its docstring for the numbers.

ALREADY PAID OFF: two real Power bugs, both invisible to the unit suite.
  * The Wild Bunch's `setup_icons` ("gives partner 1 power") was generated into the data,
    validated by test_fighters, and executed by NOBODY -- so its partner started every
    game one Power short.
  * Joan's divine-voice dial was a four-space ring the marker left for good, with the
    self-Power icon on the first step out. BGA's is FIVE positions including the Halo,
    with the icon on the second -- so our Joan paid out a step early and once every four
    steps instead of five, compounding to ~2 Power by mid-game.
Neither is the kind of bug a hand-written test finds, because both look exactly like the
rules as written; only a real game disagrees.

DELIBERATELY NOT COMPARED YET: the health marker. BGA reports it as a board SLOT id
(locationArg 25/22/19/15/3), not an HP value, so it needs each fighter's track layout to
become comparable. `power` needs no such mapping, so it is the cheap 80% -- add health once
the replayer reaches the end of games routinely.
"""
from games.rag_tag.tools import bga_inspect as tt_inspect
from games.rag_tag import engine, fighters as F

BGA_TO_FID = {v["bga_id"]: k for k, v in F.FIGHTERS.items()}


def snapshot_of(d):
    """One updateCardAndFighterData event -> {fid: (power, is_ko)}."""
    snap = {}
    for f in (d["args"].get("allFighters") or []):
        fid = BGA_TO_FID.get(f.get("typeArg"))
        st = f.get("fighterState") or {}
        if fid is not None and isinstance(st, dict):
            snap[fid] = (f.get("power"), bool(st.get("isKnockedOut")))
    return snap


def snapshots(events):
    """Ordered [{fid: (power, is_ko)}], one per updateCardAndFighterData that carries state."""
    out = []
    for _mid, d in events:
        if d["type"] != "updateCardAndFighterData":
            continue
        snap = {}
        for f in (d["args"].get("allFighters") or []):
            fid = BGA_TO_FID.get(f.get("typeArg"))
            st = f.get("fighterState") or {}
            if fid is None or not isinstance(st, dict):
                continue
            snap[fid] = (f.get("power"), bool(st.get("isKnockedOut")))
        if snap:
            # BGA re-sends identical snapshots; only keep transitions.
            if not out or out[-1] != snap:
                out.append(snap)
    return out


def our_state(game):
    """{fid: (power, is_ko)} for all four fighters in our engine."""
    return {f["id"]: (f["power"], engine.is_ko(f))
            for side in game["fighters"] for f in side}


def diff(game, snap):
    """[(fid, ours, theirs)] for every fighter whose (power, ko) disagrees."""
    ours = our_state(game)
    return [(fid, ours.get(fid), theirs)
            for fid, theirs in snap.items() if ours.get(fid) != theirs]
