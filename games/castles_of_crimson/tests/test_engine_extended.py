"""Targeted edge-case, guard, and end-of-game scoring tests for the CoC engine.

These complement the random-playout invariants with specific hard-to-hit
situations: storage/goods caps, die-adjust cost wrapping, once-per-turn flags,
chained/failed pending sub-decisions, move guards, and the exact composition of
the final score. Each sets up a controlled state and asserts one rule."""
from games.castles_of_crimson import engine, board, tiles
from .conftest import complete_setup


def _playing(seed=1):
    """A fresh 2-player game past setup (phase 'playing', round 1 rolled)."""
    g = engine.new_game(["p1", "p2"], names={"p1": "A", "p2": "B"}, seed=seed)
    complete_setup(g)
    return g


def _controlled_turn(g, pid="p1", values=(1, 6)):
    """Force pid to be the active player with a known pair of dice, then snapshot."""
    g["turn"] = pid
    g["dice"][pid] = {"values": list(values), "used": [False, False]}
    engine._snapshot_turn(g)


# ── Storage cap ───────────────────────────────────────────────────────────────
def test_buy_black_rejected_when_storage_full():
    g = _playing(1)
    p = g["players"]["p1"]
    p["silver"] = 5
    p["storage"] = [tiles._hex_tile("mine", "gray") for _ in range(3)]
    g["black_depot"] = [tiles._hex_tile("mine", "gray")]
    _controlled_turn(g)
    ok, err = engine.apply_move(g, "p1", {"type": "buy_black", "tile_id": g["black_depot"][0]["id"]})
    assert not ok and "storage" in err


def test_buy_black_once_per_turn_then_resets_next_turn():
    g = _playing(2)
    p = g["players"]["p1"]
    p["silver"] = 10
    p["storage"] = []
    g["black_depot"] = [tiles._hex_tile("mine", "gray"), tiles._hex_tile("mine", "gray")]
    _controlled_turn(g)
    ok, err = engine.apply_move(g, "p1", {"type": "buy_black", "tile_id": g["black_depot"][0]["id"]})
    assert ok, err
    # a second black-depot buy on the same turn is rejected
    ok, err = engine.apply_move(g, "p1", {"type": "buy_black", "tile_id": g["black_depot"][0]["id"]})
    assert not ok and "black depot" in err
    # cycle back to p1's next turn -> the once-per-turn flag has reset
    engine.apply_move(g, "p1", {"type": "end_turn"})
    engine.apply_move(g, "p2", {"type": "end_turn"})
    assert g["turn"] == "p1" and g["black_depot_used_this_turn"] is False
    ok, err = engine.apply_move(g, "p1", {"type": "buy_black", "tile_id": g["black_depot"][0]["id"]})
    assert ok, err


def test_monastery6_requires_effect_workers_room_and_once_per_turn():
    g = _playing(3)
    p = g["players"]["p1"]
    tile = tiles._hex_tile("building", "beige", building="market")
    g["depots"]["1"]["hexes"] = [tile]
    _controlled_turn(g)
    # without the monastery effect the action is illegal
    ok, err = engine.apply_move(g, "p1", {"type": "monastery6_take", "tile_id": tile["id"]})
    assert not ok and "monastery" in err
    # with the effect but too few workers
    p["monastery_effects"] = [6]
    p["workers"] = 1
    ok, err = engine.apply_move(g, "p1", {"type": "monastery6_take", "tile_id": tile["id"]})
    assert not ok and "workers" in err
    # enough workers -> succeeds, spends exactly 2, takes the tile
    p["workers"] = 2
    ok, err = engine.apply_move(g, "p1", {"type": "monastery6_take", "tile_id": tile["id"]})
    assert ok, err
    assert p["workers"] == 0 and any(t["id"] == tile["id"] for t in p["storage"])
    assert g["m6_used_this_turn"] is True
    # once per turn: even with plenty of workers, a second use is rejected
    tile2 = tiles._hex_tile("building", "beige", building="bank")
    g["depots"]["1"]["hexes"] = [tile2]
    p["workers"] = 5
    ok, err = engine.apply_move(g, "p1", {"type": "monastery6_take", "tile_id": tile2["id"]})
    assert not ok and "this turn" in err


# ── Goods cap + ship goods intake ─────────────────────────────────────────────
def test_take_all_goods_respects_three_distinct_limit():
    """With 3 distinct colors already held, a ship take-all tops up an existing
    color but leaves a would-be 4th color sitting in the depot (rulebook cap of 3)."""
    g = _playing(4)
    p = g["players"]["p1"]
    p["goods"] = {"amber": 1, "rose": 1, "jade": 1}   # 3 distinct
    g["depots"]["1"]["goods"] = [{"id": "g1", "color": "amber", "kind": "goods"},
                                 {"id": "g2", "color": "cobalt", "kind": "goods"}]
    needs_pick, _ = engine._take_goods_from_depot(g, "p1", 1)
    assert not needs_pick                              # only one new colour, no free slot -> no prompt
    assert p["goods"]["amber"] == 2                    # existing color topped up
    assert "cobalt" not in p["goods"]                  # 4th distinct color not stored
    assert [x["color"] for x in g["depots"]["1"]["goods"]] == ["cobalt"]  # remains in depot


def test_take_all_goods_adds_new_colors_up_to_three():
    g = _playing(5)
    p = g["players"]["p1"]
    p["goods"] = {"amber": 1}
    g["depots"]["2"]["goods"] = [{"id": "g1", "color": "rose", "kind": "goods"},
                                 {"id": "g2", "color": "rose", "kind": "goods"},
                                 {"id": "g3", "color": "jade", "kind": "goods"}]
    needs_pick, _ = engine._take_goods_from_depot(g, "p1", 2)
    assert not needs_pick                              # 2 new colours, 2 free slots -> unambiguous
    assert p["goods"] == {"amber": 1, "rose": 2, "jade": 1}
    assert g["depots"]["2"]["goods"] == []             # all taken (room was available)


def test_take_goods_prompts_a_pick_when_more_new_colors_than_slots():
    """One free slot but two NEW colours in the depot -> the player must choose which
    to take (a goods_pick pending); the chosen colour's tiles transfer, the rest stay."""
    g = _playing(9)
    p = g["players"]["p1"]
    p["goods"] = {"amber": 1, "rose": 1}               # 1 free slot
    g["turn"] = "p1"
    g["depots"]["3"]["goods"] = [{"id": "g1", "color": "jade", "kind": "goods"},
                                 {"id": "g2", "color": "cobalt", "kind": "goods"}]
    engine._set_pending(g, "p1", "ship_choose_depot", {})
    ok, err = engine.apply_move(g, "p1", {"type": "ship_take_goods", "depot": 3})
    assert ok, err
    assert g["pending_kind"] == "goods_pick"
    assert set(g["pending"]["ctx"]["colors"]) == {"jade", "cobalt"}
    # only jade + cobalt + skip are legal while the pick is open
    assert {m["type"] for m in engine.legal_moves(g, "p1")} == {"goods_pick", "skip_pending"}
    ok, err = engine.apply_move(g, "p1", {"type": "goods_pick", "color": "cobalt"})
    assert ok, err
    assert p["goods"] == {"amber": 1, "rose": 1, "cobalt": 1}   # took the chosen colour
    assert [x["color"] for x in g["depots"]["3"]["goods"]] == ["jade"]  # the other stays
    assert g["pending_pid"] is None                    # slots full -> pick phase ends


def test_take_goods_pick_can_be_skipped():
    g = _playing(10)
    p = g["players"]["p1"]
    p["goods"] = {"amber": 1, "rose": 1}
    g["turn"] = "p1"
    g["depots"]["3"]["goods"] = [{"id": "g1", "color": "jade", "kind": "goods"},
                                 {"id": "g2", "color": "cobalt", "kind": "goods"}]
    engine._set_pending(g, "p1", "ship_choose_depot", {})
    engine.apply_move(g, "p1", {"type": "ship_take_goods", "depot": 3})
    assert g["pending_kind"] == "goods_pick"
    ok, err = engine.apply_move(g, "p1", {"type": "skip_pending"})
    assert ok, err
    assert p["goods"] == {"amber": 1, "rose": 1}        # forwent both new colours
    assert len(g["depots"]["3"]["goods"]) == 2          # both remain in the depot
    assert g["pending_pid"] is None


def test_sell_goods_clears_entire_color_and_records_each_tile():
    g = _playing(6)
    p = g["players"]["p1"]
    p["goods"] = {"amber": 3}                          # amber == die value 1
    _controlled_turn(g, values=(1, 6))
    vp0, silver0 = p["vp"], p["silver"]
    ok, err = engine.apply_move(g, "p1", {"type": "sell_goods", "die_index": 0})
    assert ok, err
    assert "amber" not in p["goods"]                   # the whole stack is sold at once
    assert p["sold_goods"].count("amber") == 3         # each sold tile recorded for endgame
    assert p["vp"] == vp0 + tiles.sell_vp_per_tile(2) * 3
    assert p["silver"] == silver0 + tiles.SELL_SILVER


# ── Free die-shift monasteries (which tile type each frees) ───────────────────
def test_free_shift_monastery_matrix():
    g = _playing(22)
    p = g["players"]["p1"]

    def fs(eff, ttype):
        p["monastery_effects"] = eff
        return engine._free_shift_for_tile(p, ttype)

    assert not fs([], "building") and not fs([], "ship")            # none: no free shift
    assert fs([9], "building") and not fs([9], "ship") and not fs([9], "mine")      # 9: buildings
    assert fs([10], "ship") and fs([10], "livestock") and not fs([10], "building")  # 10: ship/livestock
    assert fs([11], "castle") and fs([11], "mine") and fs([11], "monastery") and not fs([11], "ship")  # 11


def test_allowed_values_wrap_around():
    assert engine._allowed_values(3, False) == {3}                 # no shift -> exact value only
    assert engine._allowed_values(3, True) == {2, 3, 4}
    assert engine._allowed_values(1, True) == {6, 1, 2}            # wraps below 1 to 6
    assert engine._allowed_values(6, True) == {5, 6, 1}            # wraps above 6 to 1


# ── Die adjust ────────────────────────────────────────────────────────────────
def test_adjust_die_to_same_value_rejected():
    g = _playing(7)
    g["players"]["p1"]["workers"] = 5
    _controlled_turn(g, values=(3, 3))
    ok, err = engine.apply_move(g, "p1", {"type": "adjust_die", "die_index": 0, "to": 3})
    assert not ok and "already shows" in err


def test_adjust_die_on_used_die_rejected():
    g = _playing(7)
    g["players"]["p1"]["workers"] = 5
    g["turn"] = "p1"
    g["dice"]["p1"] = {"values": [3, 4], "used": [True, False]}
    engine._snapshot_turn(g)
    ok, err = engine.apply_move(g, "p1", {"type": "adjust_die", "die_index": 0, "to": 5})
    assert not ok and "used" in err


def test_adjust_cost_wraps_and_monastery8_halves():
    g = _playing(8)
    assert engine._adjust_cost(g, "p1", 6, 1) == 1     # 6->1 wraps: 1 step
    assert engine._adjust_cost(g, "p1", 1, 6) == 1     # 1->6 wraps: 1 step
    assert engine._adjust_cost(g, "p1", 1, 4) == 3     # 1->4: min(3,3)=3 steps
    g["players"]["p1"]["monastery_effects"] = [8]      # 2 steps per worker
    assert engine._adjust_cost(g, "p1", 1, 4) == 2     # ceil(3/2)
    assert engine._adjust_cost(g, "p1", 1, 3) == 1     # ceil(2/2)


# ── take_hex ──────────────────────────────────────────────────────────────────
def test_take_hex_from_empty_matching_depot_rejected():
    g = _playing(9)
    g["players"]["p1"]["storage"] = []
    _controlled_turn(g, values=(1, 6))
    g["depots"]["1"]["hexes"] = []                     # depot 1 matches die value 1 but is empty
    ok, err = engine.apply_move(g, "p1", {"type": "take_hex", "die_index": 0, "depot": 1, "tile_id": "nope"})
    assert not ok


def test_take_hex_bad_die_index_rejected():
    g = _playing(9)
    _controlled_turn(g)
    ok, err = engine.apply_move(g, "p1", {"type": "take_hex", "die_index": 5, "depot": 1, "tile_id": "x"})
    assert not ok and "die_index" in err


# ── Ships / track ─────────────────────────────────────────────────────────────
def test_end_turn_applies_all_queued_ship_advances():
    """Every ship placed this turn queues +1 track space; they apply together at end."""
    g = _playing(10)
    _controlled_turn(g)
    sp0 = engine._player_space(g, "p1")
    g["ship_advance_pending"] = 2                      # e.g. a ship + a ship via a castle extra action
    ok, err = engine.apply_move(g, "p1", {"type": "end_turn"})
    assert ok, err
    assert engine._player_space(g, "p1") == min(sp0 + 2, engine.NUM_TRACK_SPACES - 1)


def test_ship_with_no_goods_anywhere_sets_no_depot_pending():
    g = _playing(11)
    for d in range(1, 7):
        g["depots"][str(d)]["goods"] = []
    sp0 = engine._player_space(g, "p1")
    engine._place_ship_effect(g, "p1", g["players"]["p1"]["castle_sid"], tiles._hex_tile("ship", "blue"))
    assert engine._player_space(g, "p1") == min(sp0 + 1, engine.NUM_TRACK_SPACES - 1)  # advanced immediately
    assert g["pending_pid"] is None                    # but no depot-choice pending (nothing to take)


def test_per_turn_flags_reset_on_turn_change():
    g = _playing(12)
    _controlled_turn(g)
    g["black_depot_used_this_turn"] = True
    g["m6_used_this_turn"] = True
    g["ship_advance_pending"] = 3
    engine.apply_move(g, "p1", {"type": "end_turn"})
    assert g["black_depot_used_this_turn"] is False
    assert g["m6_used_this_turn"] is False
    assert g["ship_advance_pending"] == 0


# ── Pending sub-decisions: chaining and failure recovery ──────────────────────
def test_extra_action_failed_sub_keeps_the_pending():
    g = _playing(13)
    g["turn"] = "p1"
    engine._set_pending(g, "p1", "extra_action", {"source": "castle"})
    # a sub-action that can't apply (tile not in that depot) must leave the pending in place
    ok, err = engine.apply_move(g, "p1", {"type": "extra_action", "value": 1,
                                          "sub": {"type": "take_hex", "depot": 2, "tile_id": "missing"}})
    assert not ok
    assert g["pending_kind"] == "extra_action" and g["pending_pid"] == "p1"


def test_townhall_place_failed_keeps_the_pending():
    g = _playing(13)
    p = g["players"]["p1"]
    g["turn"] = "p1"
    p["storage"] = [tiles._hex_tile("mine", "gray")]
    engine._set_pending(g, "p1", "townhall_place", {"building": "townhall"})
    ok, err = engine.apply_move(g, "p1", {"type": "townhall_place",
                                          "tile_id": p["storage"][0]["id"], "space_id": "no-such-space"})
    assert not ok
    assert g["pending_kind"] == "townhall_place"


def test_warehouse_with_no_goods_sets_no_pending():
    g = _playing(14)
    p = g["players"]["p1"]
    p["goods"] = {}
    engine._place_building_effect(g, "p1", p["castle_sid"], tiles._hex_tile("building", "beige", building="warehouse"))
    assert g["pending_pid"] is None                    # nothing to sell -> no interaction


def test_skip_pending_always_available_and_clears():
    g = _playing(14)
    g["turn"] = "p1"
    engine._set_pending(g, "p1", "ship_choose_depot", {})
    assert {"type": "skip_pending"} in engine.legal_moves(g, "p1")
    ok, err = engine.apply_move(g, "p1", {"type": "skip_pending"})
    assert ok, err
    assert g["pending_pid"] is None


# ── Move guards ───────────────────────────────────────────────────────────────
def test_move_rejected_once_game_is_over():
    g = _playing(15)
    while not engine.is_over(g):
        engine.apply_move(g, g["turn"], {"type": "end_turn"})
    ok, err = engine.apply_move(g, "p1", {"type": "end_turn"})
    assert not ok and "over" in err


def test_setup_phase_rejects_non_castle_moves():
    g = engine.new_game(["p1", "p2"], seed=16)         # still in setup
    ok, err = engine.apply_move(g, g["turn"], {"type": "take_workers", "die_index": 0})
    assert not ok


def test_unknown_move_type_rejected():
    g = _playing(16)
    _controlled_turn(g)
    ok, err = engine.apply_move(g, "p1", {"type": "frobnicate"})
    assert not ok and "unknown" in err


def test_opponent_cannot_resolve_your_pending():
    g = _playing(17)
    g["turn"] = "p1"
    engine._set_pending(g, "p1", "extra_action", {"source": "castle"})
    ok, err = engine.apply_move(g, "p2", {"type": "skip_pending"})
    assert not ok


def test_non_pending_player_cannot_act_during_a_pending():
    g = _playing(17)
    g["turn"] = "p1"
    engine._set_pending(g, "p1", "extra_action", {"source": "castle"})
    ok, err = engine.apply_move(g, "p2", {"type": "end_turn"})
    assert not ok
    assert engine.legal_moves(g, "p2") == []           # and it lists no moves for them


def test_place_starting_castle_on_non_burgundy_rejected():
    g = engine.new_game(["p1", "p2"], seed=18)
    sid = next(s for s, i in board.SPACES.items() if i["color"] != "burgundy")
    ok, err = engine.apply_move(g, g["turn"], {"type": "place_starting_castle", "space_id": sid})
    assert not ok and "burgundy" in err


def test_place_starting_castle_on_occupied_rejected():
    g = engine.new_game(["p1", "p2"], seed=18)
    burg = sorted(s for s, i in board.SPACES.items() if i["color"] == "burgundy")[0]
    g["players"]["p1"]["duchy"][burg] = tiles.starting_castle_tile()   # pre-occupy the space
    ok, err = engine.apply_move(g, "p1", {"type": "place_starting_castle", "space_id": burg})
    assert not ok and "occupied" in err


# ── End-of-game scoring ───────────────────────────────────────────────────────
def test_final_score_composition():
    g = _playing(19)
    p = g["players"]["p1"]
    p["vp"], p["silver"], p["workers"] = 10, 3, 5
    p["goods"] = {"amber": 2, "rose": 1}
    p["monastery_effects"], p["sold_goods"], p["claimed_bonus"] = [], [], []
    # 10 VP + 3 leftover goods + 3 silver + 5//2 workers(2) = 18
    assert engine.final_scores(g)["p1"] == 10 + 3 + 3 + 2


def test_leftover_workers_round_down():
    g = _playing(19)
    p = g["players"]["p1"]
    p["vp"], p["silver"], p["goods"], p["monastery_effects"] = 0, 0, {}, []
    p["workers"] = 5
    assert engine.final_scores(g)["p1"] == 2           # 5 // 2


def test_endgame_monastery_effects_stack():
    g = _playing(20)
    p = g["players"]["p1"]
    p["monastery_effects"] = [15, 25, 26]
    p["sold_goods"] = ["amber", "amber", "rose"]       # 2 distinct types, 3 tiles
    p["claimed_bonus"] = [{"color": "amber", "vp": 5}]
    # 15: 2*2=4 ; 25: 1*3=3 ; 26: 3*1=3
    assert engine._endgame_monastery_vp(g, "p1") == 4 + 3 + 3


def test_endgame_monastery_building_scoring():
    g = _playing(20)
    p = g["players"]["p1"]
    p["monastery_effects"] = [16, 22]                  # 16: 4/market, 22: 4/bank
    p["buildings_placed"]["market"] = 2
    p["buildings_placed"]["bank"] = 1
    assert engine._endgame_monastery_vp(g, "p1") == 4 * 2 + 4 * 1


# ── Goods queue (the "goods left this phase" mechanic) ────────────────────────
def test_goods_queue_deals_one_per_round_and_refills_each_phase():
    g = _playing(21)
    # complete_setup began round 1, which dealt one goods tile.
    assert len(g["goods_queue"]) == tiles.GOODS_PER_PHASE - 1
    seen = [len(g["goods_queue"])]
    # play out phase A (rounds 1..5 -> phase B round 1): 10 end_turns for a 2-player game.
    for _ in range(10):
        engine.apply_move(g, g["turn"], {"type": "end_turn"})
        seen.append(len(g["goods_queue"]))
    assert g["phase_letter"] == "B" and g["round"] == 1
    # the queue emptied to 0 by the end of phase A, then refilled to 5 and dealt 1 for phase B round 1.
    assert 0 in seen
    assert len(g["goods_queue"]) == tiles.GOODS_PER_PHASE - 1
