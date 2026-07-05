"""Multi-step scenario tests: chained pending sub-decisions, the pending guard,
building-take choices, the track ↔ start-player interaction, and player-count
scaling of VP rewards. These stitch several rules together the way a real turn
does, catching regressions that single-rule tests can't."""
from games.castles_of_crimson import engine, board, tiles
from .conftest import complete_setup


def _playing(seed=1):
    g = engine.new_game(["p1", "p2"], names={"p1": "A", "p2": "B"}, seed=seed)
    complete_setup(g)
    return g


# ── Chained pendings: resolving one sub-decision can create the next ──────────
def test_castle_extra_action_placing_a_ship_chains_to_ship_depot_pending():
    """A castle grants an extra action; spending it to place a SHIP must then hand
    the player the ship's own depot-choice pending (a pending that spawns a pending)."""
    g = _playing(30)
    p = g["players"]["p1"]
    g["turn"] = "p1"
    blue = next(s for s, i in board.SPACES.items() if i["color"] == "blue")
    nb = board.neighbors(blue)[0]
    p["duchy"][nb] = {"id": "n", "kind": "hex", "type": "mine", "color": board.SPACES[nb]["color"]}
    p["storage"] = [{"id": "ship1", "kind": "hex", "type": "ship", "color": "blue"}]
    g["depots"]["1"]["goods"] = [{"id": "gg", "color": "amber", "kind": "goods"}]  # goods exist -> depot choice
    engine._set_pending(g, "p1", "extra_action", {"source": "castle"})
    num = board.SPACES[blue]["number"]
    ok, err = engine.apply_move(g, "p1", {"type": "extra_action", "value": num,
                                          "sub": {"type": "place_tile", "tile_id": "ship1", "space_id": blue}})
    assert ok, err
    assert p["duchy"][blue] is not None and p["duchy"][blue]["type"] == "ship"
    assert g["pending_kind"] == "ship_choose_depot"          # the new pending from the ship effect
    assert engine._player_space(g, "p1") >= 1                # and the ship advanced the track immediately


def test_region_completion_logged_before_tile_ability():
    """Completing a region is logged the moment the tile lands — BEFORE the tile's own
    ability (here: livestock scoring), so the log reads placed -> region -> ability."""
    g = _playing(50)
    p = g["players"]["p1"]
    b = board.get_board(p["board_id"])
    sid = next(list(r["spaces"])[0] for r in b.REGIONS.values() if r["size"] == 1 and r["color"] == "green")
    tile = tiles._hex_tile("livestock", "green", animal="pig", count=2)
    p["duchy"][sid] = tile                        # place it, then run the on-placed effects
    g["moves"] = []
    engine._on_tile_placed(g, "p1", sid, tile)
    types = [m["type"] for m in g["moves"]]       # newest-first
    assert "area_complete" in types and "livestock_score" in types
    # chronological order is the reverse of the log; region must come first
    assert types.index("area_complete") > types.index("livestock_score")


def test_ship_track_advance_is_undone_by_undo_turn():
    """A ship advances the track immediately; undoing the whole turn restores it."""
    g = _playing(51)
    g["turn"] = "p1"
    for d in range(1, 7):
        g["depots"][str(d)]["goods"] = []         # no goods -> ship sets no depot pending
    engine._snapshot_turn(g)                       # mark the turn-start state
    sp0 = engine._player_space(g, "p1")
    engine._place_ship_effect(g, "p1", g["players"]["p1"]["castle_sid"], tiles._hex_tile("ship", "blue"))
    assert engine._player_space(g, "p1") == min(sp0 + 1, engine.NUM_TRACK_SPACES - 1)
    ok, err = engine.apply_move(g, "p1", {"type": "undo_turn"})
    assert ok, err
    assert engine._player_space(g, "p1") == sp0    # track restored to before the ship


def test_ship_pending_must_be_resolved_before_other_moves():
    g = _playing(31)
    g["turn"] = "p1"
    engine._set_pending(g, "p1", "ship_choose_depot", {})
    ok, err = engine.apply_move(g, "p1", {"type": "end_turn"})
    assert not ok and "resolve" in err
    # only the depot picks + skip are legal while the pending is open
    kinds = {m["type"] for m in engine.legal_moves(g, "p1")}
    assert kinds == {"ship_take_goods", "skip_pending"}


# ── Building take-a-tile choices ──────────────────────────────────────────────
def test_carpenter_take_pending_lists_only_buildings_and_resolves():
    g = _playing(32)
    p = g["players"]["p1"]
    g["turn"] = "p1"
    p["storage"] = []
    bt = tiles._hex_tile("building", "beige", building="market")
    ship = tiles._hex_tile("ship", "blue")
    g["depots"]["1"]["hexes"] = [bt]
    g["depots"]["2"]["hexes"] = [ship]
    engine._building_take_pending(g, "p1", "carpenter", ("building",))
    assert g["pending_kind"] == "building_take_choice"
    cands = g["pending"]["ctx"]["candidates"]
    assert bt["id"] in cands and ship["id"] not in cands     # only building-type tiles offered
    ok, err = engine.apply_move(g, "p1", {"type": "building_take_choice", "tile_id": bt["id"]})
    assert ok, err
    assert any(t["id"] == bt["id"] for t in p["storage"])     # moved to storage
    assert bt not in g["depots"]["1"]["hexes"]                # removed from the depot
    assert g["pending_pid"] is None


def test_building_take_choice_rejects_non_candidate_tile():
    g = _playing(32)
    p = g["players"]["p1"]
    g["turn"] = "p1"
    p["storage"] = []
    bt = tiles._hex_tile("building", "beige", building="bank")
    g["depots"]["1"]["hexes"] = [bt]
    engine._building_take_pending(g, "p1", "carpenter", ("building",))
    ok, err = engine.apply_move(g, "p1", {"type": "building_take_choice", "tile_id": "not-a-candidate"})
    assert not ok
    assert g["pending_kind"] == "building_take_choice"        # pending remains open


def test_building_take_pending_not_set_when_no_candidates():
    g = _playing(32)
    for d in range(1, 7):
        g["depots"][str(d)]["hexes"] = []                    # no building tiles anywhere
    engine._building_take_pending(g, "p1", "carpenter", ("building",))
    assert g["pending_pid"] is None


# ── Track ↔ start-player ──────────────────────────────────────────────────────
def test_track_advance_changes_next_round_start_player_and_white_die_holder():
    g = _playing(33)
    assert g["start_player"] == "p1"
    engine._advance_track(g, "p2", 2)                        # p2 jumps ahead on the turn track
    engine.apply_move(g, g["turn"], {"type": "end_turn"})    # p1 ends
    engine.apply_move(g, g["turn"], {"type": "end_turn"})    # p2 ends -> round 2 begins
    assert g["round"] == 2
    assert g["start_player"] == "p2"                         # furthest-forward acts first next round
    assert g["turn"] == "p2"


def test_track_order_is_top_of_stack_first():
    g = engine.new_game(["p1", "p2"], seed=1)
    # both start on space 0, first player on top -> p1 acts first
    assert engine._track_order(g)[0] == "p1"
    engine._advance_track(g, "p2", 2)
    engine._advance_track(g, "p1", 2)                        # lands ON TOP of p2 on space 2
    assert engine._track_order(g)[0] == "p1"                 # top of the shared stack acts first


# ── Player-count scaling of rewards ───────────────────────────────────────────
def test_sell_vp_scales_with_player_count():
    assert (tiles.sell_vp_per_tile(2), tiles.sell_vp_per_tile(3), tiles.sell_vp_per_tile(4)) == (2, 3, 4)


def test_bonus_tile_values_scale_with_player_count():
    assert (tiles.bonus_first(2), tiles.bonus_second(2)) == (5, 2)
    assert (tiles.bonus_first(3), tiles.bonus_second(3)) == (6, 3)
    assert (tiles.bonus_first(4), tiles.bonus_second(4)) == (7, 4)


def test_bonus_tiles_initialized_per_color_for_player_count():
    for n in (2, 3, 4):
        pids = [f"p{i}" for i in range(n)]
        g = engine.new_game(pids, seed=1)
        for c in board.COLORS:
            assert g["bonus_tiles"][c] == [tiles.bonus_first(n), tiles.bonus_second(n)]


def test_starting_workers_are_seat_dependent_for_all_counts():
    for n in (2, 3, 4):
        pids = [f"p{i}" for i in range(n)]
        g = engine.new_game(pids, seed=2)
        for seat, pid in enumerate(pids):
            assert g["players"][pid]["workers"] == seat + 1   # start player 1, next 2, ...


def test_three_player_bank_scales_by_area_score_only_not_bonus():
    # sanity: a 3-player game deals the depots + goods the same way (fixed plan / counts).
    g = engine.new_game(["p1", "p2", "p3"], seed=3)
    for i in range(1, 7):
        assert len(g["depots"][str(i)]["hexes"]) == tiles.DEPOT_FILL_2P
    assert len(g["black_depot"]) == tiles.BLACK_FILL_2P
    assert g["num_players"] == 3


# ── Ship + monastery 5 adjacent-depot chain (the double-take) ────────────────
def test_monastery5_chains_to_adjacent_depot_then_clears():
    g = _playing(34)
    p = g["players"]["p1"]
    g["turn"] = "p1"
    p["monastery_effects"] = [5]
    p["goods"] = {}                                          # start from empty for a clean count
    # goods sit in depot 3 (the chosen depot) and its adjacent depot 4
    g["depots"]["3"]["goods"] = [{"id": "a", "color": "amber", "kind": "goods"}]
    g["depots"]["4"]["goods"] = [{"id": "b", "color": "rose", "kind": "goods"}]
    engine._set_pending(g, "p1", "ship_choose_depot", {})
    ok, err = engine.apply_move(g, "p1", {"type": "ship_take_goods", "depot": 3})
    assert ok, err
    assert p["goods"].get("amber") == 1                      # took depot 3
    assert g["pending_kind"] == "ship_adjacent_depot"        # monastery 5 offers an adjacent depot
    assert 4 in g["pending"]["ctx"]["candidates"]
    ok, err = engine.apply_move(g, "p1", {"type": "ship_adjacent_take", "depot": 4})
    assert ok, err
    assert p["goods"].get("rose") == 1                       # took the adjacent depot too
    assert g["pending_pid"] is None


def test_monastery5_adjacent_can_be_skipped():
    g = _playing(34)
    p = g["players"]["p1"]
    g["turn"] = "p1"
    p["monastery_effects"] = [5]
    p["goods"] = {}                                          # start from empty for a clean count
    g["depots"]["3"]["goods"] = [{"id": "a", "color": "amber", "kind": "goods"}]
    g["depots"]["4"]["goods"] = [{"id": "b", "color": "rose", "kind": "goods"}]
    engine._set_pending(g, "p1", "ship_choose_depot", {})
    engine.apply_move(g, "p1", {"type": "ship_take_goods", "depot": 3})
    assert g["pending_kind"] == "ship_adjacent_depot"
    ok, err = engine.apply_move(g, "p1", {"type": "skip_pending"})
    assert ok, err
    assert g["pending_pid"] is None
    assert p["goods"].get("rose") is None                    # adjacent depot forgone
