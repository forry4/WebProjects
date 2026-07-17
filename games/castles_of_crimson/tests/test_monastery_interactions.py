"""Monastery ↔ monastery interaction tests.

Several monasteries fire on the SAME trigger and must combine correctly: some
REPLACE the base amount ("gain 4 workers instead of 2", "2 silver instead of 1")
and some ADD on top ("+1 silver when taking workers", "+1 worker when selling").
These verify the combinations don't double-count the replacement or drop the
add-on — e.g. owning 13 AND 14 gives 4 workers *and* 1 silver from one action."""
from games.castles_of_crimson import engine, board, tiles
from .conftest import complete_setup


def _fresh(effects=()):
    g = engine.new_game(["p1", "p2"], seed=1)
    complete_setup(g)
    g["turn"] = "p1"
    g["dice"]["p1"] = {"values": [1, 6], "used": [False, False]}
    for d in range(1, 7):
        g["depots"][str(d)]["hexes"] = []
        g["depots"][str(d)]["goods"] = []
    p = g["players"]["p1"]
    p["goods"], p["vp"], p["workers"], p["silver"] = {}, 0, 0, 0
    p["monastery_effects"] = list(effects)
    return g


def _hext(ttype, color, tid, **extra):
    t = {"id": tid, "kind": "hex", "type": ttype, "color": color}
    t.update(extra)
    return t


def _ensure_neighbor(g, sid):
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


# ── Same-trigger stacking (the two real pairs) ────────────────────────────────
def test_m13_and_m14_stack_on_take_workers():
    """13 (+1 silver) and 14 (4 workers instead of 2) fire together on one action."""
    g = _fresh(effects=[13, 14])
    engine.apply_move(g, "p1", {"type": "take_workers", "die_index": 0})
    p = g["players"]["p1"]
    assert p["workers"] == 4 and p["silver"] == 1


def test_m3_and_m4_stack_on_sell():
    """3 (2 silver instead of 1) and 4 (+1 worker) fire together on one sale."""
    g = _fresh(effects=[3, 4])
    g["players"]["p1"]["goods"] = {"amber": 2}       # amber == die value 1
    engine.apply_move(g, "p1", {"type": "sell_goods", "die_index": 0})
    p = g["players"]["p1"]
    assert p["silver"] == 2                           # m3: 2 (not 1)
    assert p["workers"] == 1                          # m4: +1 (per sale, not per tile)
    assert p["vp"] == tiles.sell_vp_per_tile(2) * 2   # 2 tiles sold


# ── "instead of" effects REPLACE, they don't add to the base ──────────────────
def test_m14_replaces_base_workers_not_additive():
    g = _fresh(effects=[14])
    engine.apply_move(g, "p1", {"type": "take_workers", "die_index": 0})
    assert g["players"]["p1"]["workers"] == 4          # exactly 4, not 2 + 4


def test_m3_replaces_base_silver_not_additive():
    g = _fresh(effects=[3])
    g["players"]["p1"]["goods"] = {"amber": 1}
    engine.apply_move(g, "p1", {"type": "sell_goods", "die_index": 0})
    assert g["players"]["p1"]["silver"] == 2           # exactly 2, not 1 + 2


def test_m13_alone_still_gives_base_two_workers_plus_silver():
    g = _fresh(effects=[13])
    engine.apply_move(g, "p1", {"type": "take_workers", "die_index": 0})
    p = g["players"]["p1"]
    assert p["workers"] == 2 and p["silver"] == 1      # base 2 workers + m13's silver


def test_m4_alone_gives_base_silver_plus_worker():
    g = _fresh(effects=[4])
    g["players"]["p1"]["goods"] = {"amber": 1}
    engine.apply_move(g, "p1", {"type": "sell_goods", "die_index": 0})
    p = g["players"]["p1"]
    assert p["silver"] == tiles.SELL_SILVER and p["workers"] == 1   # base 1 silver + m4's worker


# ── Effect 8 (adjust by 2) vs the base 1-per-worker cost ──────────────────────
def test_m8_halves_die_adjust_cost():
    g = _fresh(effects=[8])
    # 1 -> 4 is 3 steps: base costs 3 workers, but effect 8 does 2 steps per worker
    assert engine._adjust_cost(g, "p1", 1, 4) == 2
    assert engine._adjust_cost(_fresh(), "p1", 1, 4) == 3   # no effect -> 3 workers


# ── Free-shift monasteries 9/10/11 coexist, each firing for ITS tile type ─────
def test_free_shift_monasteries_coexist_by_tile_type():
    for ttype, color, extra in [("building", "beige", {"building": "bank"}),
                                ("ship", "blue", {}),
                                ("mine", "gray", {})]:
        g = _fresh(effects=[9, 10, 11])              # own all three at once
        sid, num = next((s, i["number"]) for s, i in board.SPACES.items()
                        if i["color"] == color and g["players"]["p1"]["duchy"][s] is None)
        _ensure_neighbor(g, sid)
        off = num % 6 + 1                            # a die one step off the required number
        ok, err = _place(g, _hext(ttype, color, "x", **extra), sid, off)
        assert ok, f"{ttype} should free-shift when 9/10/11 are all owned: {err}"


# ── Endgame monasteries all sum together ──────────────────────────────────────
def test_all_endgame_monasteries_sum_together():
    g = _fresh(effects=[15, 16, 17, 24, 25, 26])
    p = g["players"]["p1"]
    p["sold_goods"] = ["amber", "rose"]              # 15: 2 types -> 4 ; 25: 2 tiles -> 2
    p["buildings_placed"]["warehouse"] = 1           # 16: 4 (per warehouse)
    p["buildings_placed"]["watchtower"] = 2          # 17: 8
    p["livestock_types"] = ["cow", "pig"]            # 24: 2 types -> 8
    p["claimed_bonus"] = [{"color": "gray", "vp": 5}]  # 26: 1 tile -> 3
    assert engine._endgame_monastery_vp(g, "p1") == 4 + 4 + 8 + 8 + 2 + 3


# ── Robustness: owning every continuous monastery breaks nothing ──────────────
def test_owning_all_continuous_monasteries_is_stable():
    g = _fresh(effects=list(range(1, 15)))           # every continuous effect (1..14)
    p = g["players"]["p1"]
    p["goods"], p["mines_count"] = {"amber": 1}, 2
    # take workers: 14 -> 4 workers, 13 -> +1 silver
    engine.apply_move(g, "p1", {"type": "take_workers", "die_index": 0})
    assert p["workers"] == 4 and p["silver"] == 1
    # sell: 3 -> +2 silver, 4 -> +1 worker
    g["dice"]["p1"] = {"values": [1, 6], "used": [False, False]}
    s0, w0 = p["silver"], p["workers"]
    engine.apply_move(g, "p1", {"type": "sell_goods", "die_index": 0})
    assert p["silver"] == s0 + 2 and p["workers"] == w0 + 1
    # phase end with 2 mines: base +2 silver AND (effect 2) +2 workers
    s1, w1 = p["silver"], p["workers"]
    for _ in range(10):
        engine.apply_move(g, g["turn"], {"type": "end_turn"})
    assert p["silver"] == s1 + 2 and p["workers"] == w1 + 2
