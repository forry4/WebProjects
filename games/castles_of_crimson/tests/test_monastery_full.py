"""End-to-end monastery acquisition tests.

test_monasteries.py verifies each of the 26 effects by INJECTING it into
`monastery_effects`. This file closes the remaining gap: that actually PLACING a
monastery tile grants its effect (for all 26), that the granted effect then works,
that multiple monasteries stack, and that a duplicate effect isn't double-counted.
It also exercises the free-die-shift monasteries (10/11) for the tile sub-types
the parametrized placement test didn't cover (livestock, castle, monastery)."""
from games.castles_of_crimson import engine, board, tiles
from .conftest import complete_setup


def _fresh():
    """A 2-player game past setup with p1 to move, empty depots, and a known die pair."""
    g = engine.new_game(["p1", "p2"], seed=1)
    complete_setup(g)
    g["turn"] = "p1"
    g["dice"]["p1"] = {"values": [1, 1], "used": [False, False]}
    for d in range(1, 7):
        g["depots"][str(d)]["hexes"] = []
        g["depots"][str(d)]["goods"] = []
    p = g["players"]["p1"]
    p["goods"], p["vp"], p["monastery_effects"] = {}, 0, []
    return g


def _hext(ttype, color, tid, **extra):
    t = {"id": tid, "kind": "hex", "type": ttype, "color": color}
    t.update(extra)
    return t


def _ensure_neighbor(g, sid):
    """Make sure `sid` has a placed neighbour so a tile can legally go there."""
    if engine._has_placed_neighbor(g, "p1", sid):
        return
    for nb in board.neighbors(sid):
        if g["players"]["p1"]["duchy"][nb] is None:
            g["players"]["p1"]["duchy"][nb] = _hext("mine", "gray", "dummy_" + nb)
            return


def _place(g, tile, sid, die):
    g["dice"]["p1"]["values"] = [die, 6]
    g["dice"]["p1"]["used"] = [False, False]
    g["players"]["p1"]["storage"] = [tile]
    return engine.apply_move(g, "p1", {"type": "place_tile", "die_index": 0, "tile_id": tile["id"], "space_id": sid})


def _place_monastery(g, eid):
    """Actually place a monastery tile carrying effect `eid` on an empty yellow space."""
    p = g["players"]["p1"]
    sid = next(s for s, i in board.SPACES.items() if i["color"] == "yellow" and p["duchy"][s] is None)
    _ensure_neighbor(g, sid)
    tile = _hext("monastery", "yellow", f"mon{eid}_{sid}", effect_id=eid)
    ok, err = _place(g, tile, sid, board.SPACES[sid]["number"])
    return ok, err, sid


# ── Acquisition: placing a monastery grants its effect (all 26) ───────────────
def test_placing_each_monastery_tile_grants_its_effect():
    for eid in range(1, 27):
        g = _fresh()
        ok, err, sid = _place_monastery(g, eid)
        assert ok, f"could not place monastery {eid}: {err}"
        assert g["players"]["p1"]["duchy"][sid]["type"] == "monastery"
        assert eid in g["players"]["p1"]["monastery_effects"], f"effect {eid} not granted on placement"


def test_duplicate_monastery_effect_not_counted_twice():
    g = _fresh()
    _place_monastery(g, 7)
    _place_monastery(g, 7)                       # a second monastery with the same effect_id
    assert g["players"]["p1"]["monastery_effects"].count(7) == 1


# ── Acquired effects actually fire (a sample across the effect kinds) ──────────
def test_acquired_monastery3_gives_two_silver_on_sell():
    g = _fresh()
    ok, err, _ = _place_monastery(g, 3)
    assert ok, err
    p = g["players"]["p1"]
    p["goods"], p["silver"] = {"amber": 1}, 0
    g["dice"]["p1"] = {"values": [1, 6], "used": [False, False]}
    engine.apply_move(g, "p1", {"type": "sell_goods", "die_index": 0})
    assert p["silver"] == 2                       # effect 3 active via placement


def test_acquired_monastery14_gives_four_workers():
    g = _fresh()
    ok, err, _ = _place_monastery(g, 14)
    assert ok, err
    p = g["players"]["p1"]
    p["workers"] = 0
    g["dice"]["p1"] = {"values": [1, 6], "used": [False, False]}
    engine.apply_move(g, "p1", {"type": "take_workers", "die_index": 0})
    assert p["workers"] == 4


def test_acquired_monastery15_scores_at_endgame():
    g = _fresh()
    ok, err, _ = _place_monastery(g, 15)          # 2 VP per different sold goods type
    assert ok, err
    g["players"]["p1"]["sold_goods"] = ["amber", "amber", "rose", "jade"]   # 3 distinct types
    assert engine._endgame_monastery_vp(g, "p1") == 6


def test_two_monasteries_stack_their_effects():
    g = _fresh()
    ok1, e1, _ = _place_monastery(g, 13)          # +1 silver on take-workers
    ok2, e2, _ = _place_monastery(g, 14)          # 4 workers instead of 2
    assert ok1 and ok2, (e1, e2)
    eff = g["players"]["p1"]["monastery_effects"]
    assert 13 in eff and 14 in eff
    p = g["players"]["p1"]
    p["workers"], p["silver"] = 0, 0
    g["dice"]["p1"] = {"values": [1, 6], "used": [False, False]}
    engine.apply_move(g, "p1", {"type": "take_workers", "die_index": 0})
    assert p["workers"] == 4 and p["silver"] == 1   # both effects fired together


# ── Free-die-shift monasteries 10/11: the tile sub-types the other test skipped ─
def test_monastery10_free_shift_on_livestock_placement():
    g = _fresh()
    g["players"]["p1"]["monastery_effects"] = [10]
    sid, num = next((s, i["number"]) for s, i in board.SPACES.items()
                    if i["color"] == "green" and g["players"]["p1"]["duchy"][s] is None)
    _ensure_neighbor(g, sid)
    off = num % 6 + 1                              # a die one step off the required number
    ok, err = _place(g, _hext("livestock", "green", "cow", animal="cow", count=2), sid, off)
    assert ok, err
    # without the effect the same off-by-one placement must fail
    g2 = _fresh()
    _ensure_neighbor(g2, sid)
    ok2, _ = _place(g2, _hext("livestock", "green", "cow", animal="cow", count=2), sid, off)
    assert not ok2


def test_monastery11_free_shift_on_castle_and_monastery_placement():
    for ttype, color, extra in [("castle", "burgundy", {}), ("monastery", "yellow", {"effect_id": 20})]:
        g = _fresh()
        g["players"]["p1"]["monastery_effects"] = [11]
        sid, num = next((s, i["number"]) for s, i in board.SPACES.items()
                        if i["color"] == color and g["players"]["p1"]["duchy"][s] is None)
        _ensure_neighbor(g, sid)
        off = num % 6 + 1
        ok, err = _place(g, _hext(ttype, color, "x", **extra), sid, off)
        assert ok, f"{ttype} free-shift placement failed: {err}"
        g2 = _fresh()
        _ensure_neighbor(g2, sid)
        ok2, _ = _place(g2, _hext(ttype, color, "x", **extra), sid, off)
        assert not ok2, f"{ttype} off-by-one placement should fail without monastery 11"
