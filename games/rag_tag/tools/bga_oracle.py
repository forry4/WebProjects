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


def _hp_marker(st):
    """The fighter's health-track index, or None when it is not unambiguous.

    BGA's marker `locationArg` IS our hp-track index -- verified for every fighter, whose
    start slot matches ours exactly (wild_bunch 5, mordred 19, golem 25, wong 17...), which
    follows from every health track matching slot-for-slot. So no mapping is needed.

    Returns None when a fighter has more than one health marker on the board, which is how
    Bodvar (human + Bear) and the Fey Folk (three Characters) present. Comparing those needs
    to know which track is live, and a wrong guess manufactures divergences -- so they are
    skipped rather than guessed at.
    """
    marks = [m for track in (st.get("trackMarkers") or {}).values() for m in (track or [])
             if isinstance(m, dict) and m.get("type") == "health"]
    return marks[0].get("locationArg") if len(marks) == 1 else None


def snapshot_of(d):
    """One updateCardAndFighterData event -> {fid: (power, is_ko, hp)}."""
    snap = {}
    for f in (d["args"].get("allFighters") or []):
        fid = BGA_TO_FID.get(f.get("typeArg"))
        st = f.get("fighterState") or {}
        if fid is not None and isinstance(st, dict):
            snap[fid] = (f.get("power"), bool(st.get("isKnockedOut")), _hp_marker(st))
    return snap


def snapshots(events):
    """Ordered [{fid: (power, is_ko)}], one per updateCardAndFighterData that carries state."""
    out = []
    for _mid, d in events:
        if d["type"] != "updateCardAndFighterData":
            continue
        snap = snapshot_of(d)          # ONE codec -- a second copy is how they drift
        if snap:
            # BGA re-sends identical snapshots; only keep transitions.
            if not out or out[-1] != snap:
                out.append(snap)
    return out


def our_slot(f):
    """Our fighter's health position expressed as a BGA SLOT id.

    Our track is indexed from the bottom; BGA numbers its slots by the HP printed on them,
    and the two coincide only for a track whose bottom space is 0. Maman Brijit's runs
    16 down to -2 (her two knock-out spaces and the revive below them), so our index 18 is
    her BGA slot 16 -- a constant +2. Reading our raw index as a slot reported her two
    spaces too healthy in EVERY game she appeared in, which looked like eight independent
    engine bugs and was one missing conversion.

    The offset is derived from the track itself (index - printed hp), never hardcoded, so a
    fighter whose track gains a space below zero needs no change here.
    """
    idx = f.get("hp")
    track = engine.track_of(f)
    if idx is None or not track:
        return None
    for i, space in enumerate(track):
        if space.get("kind") == "hp" and space.get("hp") is not None:
            return idx - (i - space["hp"])
    return idx


def our_state(game):
    """{fid: (power, is_ko, hp_slot)} for all four fighters in our engine.

    `hp_slot` is a BGA slot id, which is what BGA's health marker reports.
    """
    return {f["id"]: (f["power"], engine.is_ko(f), our_slot(f))
            for side in game["fighters"] for f in side}


#: What each slot of the state tuple means, for readable failures.
FIELDS = ("power", "ko", "hp")


def disagrees(ours, theirs):
    """Field-wise, skipping anything BGA did not report.

    A missing field is NOT a mismatch. `hp` is None whenever a fighter has more than one
    health marker (Bodvar's Bear, the Fey Folk's Characters); comparing None against a real
    index would invent a divergence for every one of them, which is exactly the kind of
    self-inflicted noise that made the first oracle useless.
    """
    if ours is None:
        return True
    return any(t is not None and o != t for o, t in zip(ours, theirs))


def diff(game, snap):
    """[(fid, ours, theirs)] for every fighter whose reported state disagrees."""
    ours = our_state(game)
    return [(fid, ours.get(fid), theirs)
            for fid, theirs in snap.items() if disagrees(ours.get(fid), theirs)]
