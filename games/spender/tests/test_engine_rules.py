"""The AUTHORITATIVE Spender rules — `engine.apply_move`.

This is the path that adjudicates a real human's move: main.py's WebSocket handler
calls straight into it. Before the engine was extracted, those rules lived inline in
the handler and NOTHING tested them — test_game_logic.py covers helpers and the MCTS
simulator (`main._sim_apply_move`), and the differential/parity chain only ties the
simulator to the AZ compact engine to the Rust port. The live path had no test and
could drift from all three.

Covered here:
  - the documented error hierarchy (order is load-bearing),
  - every move type's legality rules,
  - the pending sub-decisions (discard / noble choice) as GAME STATE, incl. undo,
  - a differential check against `main._sim_apply_move`, pinning where the simulator
    is intended to DIFFER (it auto-resolves sub-decisions) rather than assuming parity.
"""
import copy
import random

import pytest

from games.spender import engine, main


def make_game(p1="p1", p2="p2", win_points=15):
    decks = main.build_deck()
    board = engine.deal_board(decks)
    nobles_pool = list(main.ALL_NOBLES)
    random.shuffle(nobles_pool)

    def player_state():
        return {"tokens": main.empty_gems(), "purchased": [], "reserved": [], "nobles": []}

    bank = {c: 4 for c in main.GEM_COLORS}
    bank["gold"] = 5
    return {
        "bank": bank, "decks": decks, "board": board, "nobles": nobles_pool[:3],
        "players": {p1: player_state(), p2: player_state()},
        "order": [p1, p2], "turn": p1, "phase": "playing", "winner": None,
        "moves": [], "win_points": win_points,
    }


def apply(g, pid, mv):
    return engine.apply_move(g, pid, mv)


# ─── Error hierarchy (ORDER matters — it is the documented contract) ──────────

def test_game_over_beats_everything():
    g = make_game()
    g["phase"] = "over"
    ok, err, _ = apply(g, "p1", {"type": "take_gems", "colors": ["red"]})
    assert (ok, err) == (False, "game is over")


def test_not_your_turn_beats_move_validation():
    g = make_game()
    # An outright invalid move from the wrong player must still report the TURN error.
    ok, err, _ = apply(g, "p2", {"type": "nonsense"})
    assert (ok, err) == (False, "not your turn")


def test_pending_noble_blocks_other_moves():
    g = make_game()
    g["pending_noble_pid"] = "p1"
    g["pending_noble_choice"] = ["n1", "n2"]
    ok, err, _ = apply(g, "p1", {"type": "take_gems", "colors": ["red"]})
    assert (ok, err) == (False, "must choose a noble first")


def test_pending_discard_blocks_all_but_discard_and_undo():
    g = make_game()
    g["pending_discard_pid"] = "p1"
    ok, err, _ = apply(g, "p1", {"type": "take_gems", "colors": ["red"]})
    assert (ok, err) == (False, "must discard down to 10 gems first")
    # ...but `discard` itself is let through to its own validation.
    ok, err, _ = apply(g, "p1", {"type": "discard", "color": "red"})
    assert (ok, err) == (False, "can't discard that")   # holds no red


def test_unknown_move_type_rejected():
    g = make_game()
    ok, err, _ = apply(g, "p1", {"type": "teleport"})
    assert (ok, err) == (False, "unknown move type")


def test_illegal_move_does_not_mutate_state():
    g = make_game()
    before = copy.deepcopy(g)
    apply(g, "p1", {"type": "take_gems", "colors": ["red", "red", "red", "red"]})
    assert g == before


# ─── take_gems ───────────────────────────────────────────────────────────────

def test_take_three_distinct_gems():
    g = make_game()
    ok, err, fx = apply(g, "p1", {"type": "take_gems", "colors": ["red", "blue", "green"]})
    assert (ok, err) == (True, None)
    assert g["players"]["p1"]["tokens"]["red"] == 1
    assert g["bank"]["red"] == 3
    assert g["turn"] == "p2"          # turn completed
    assert fx["discard_pid"] is None


def test_take_zero_or_four_rejected():
    g = make_game()
    assert apply(g, "p1", {"type": "take_gems", "colors": []})[1] == "take 1-3 gems"
    assert apply(g, "p1", {"type": "take_gems",
                           "colors": ["red", "blue", "green", "black"]})[1] == "take 1-3 gems"


def test_take_two_same_requires_four_in_bank():
    g = make_game()
    g["bank"]["red"] = 3
    assert apply(g, "p1", {"type": "take_gems", "colors": ["red", "red"]})[1] \
        == "need >= 4 in bank for double take"
    g["bank"]["red"] = 4
    ok, _, _ = apply(g, "p1", {"type": "take_gems", "colors": ["red", "red"]})
    assert ok and g["players"]["p1"]["tokens"]["red"] == 2


def test_double_take_must_be_alone():
    g = make_game()
    ok, err, _ = apply(g, "p1", {"type": "take_gems", "colors": ["red", "red", "blue"]})
    assert (ok, err) == (False, "double take must be exactly 2 of one color")


def test_take_three_of_one_colour_rejected():
    g = make_game()
    ok, err, _ = apply(g, "p1", {"type": "take_gems", "colors": ["red", "red", "red"]})
    assert (ok, err) == (False, "invalid gem selection")


def test_take_from_empty_bank_rejected():
    g = make_game()
    g["bank"]["green"] = 0
    ok, err, _ = apply(g, "p1", {"type": "take_gems", "colors": ["red", "green"]})
    assert (ok, err) == (False, "no green in bank")


# ─── buy ─────────────────────────────────────────────────────────────────────

def test_buy_board_card_refills_from_deck():
    g = make_game()
    card = {"id": "tc1", "level": 1, "points": 1, "bonus": "blue", "cost": {"white": 2}}
    g["board"]["L1"][0] = card
    g["players"]["p1"]["tokens"]["white"] = 2
    deck_before = len(g["decks"]["L1"])
    ok, err, _ = apply(g, "p1", {"type": "buy", "card_id": "tc1"})
    assert (ok, err) == (True, None)
    assert card in g["players"]["p1"]["purchased"]
    assert len(g["decks"]["L1"]) == deck_before - 1
    assert g["bank"]["white"] == 6          # 4 + the 2 spent


def test_buy_unaffordable_rejected():
    g = make_game()
    g["board"]["L1"][0] = {"id": "tc1", "level": 1, "points": 1, "bonus": "blue",
                           "cost": {"white": 3}}
    g["players"]["p1"]["tokens"]["white"] = 2
    ok, err, _ = apply(g, "p1", {"type": "buy", "card_id": "tc1"})
    assert (ok, err) == (False, "can't afford")


def test_buy_missing_card_rejected():
    g = make_game()
    ok, err, _ = apply(g, "p1", {"type": "buy", "card_id": "no-such-card"})
    assert (ok, err) == (False, "card not found")


def test_buy_reserved_card_leaves_the_hand():
    g = make_game()
    res = {"id": "r1", "level": 1, "points": 1, "bonus": "blue", "cost": {"blue": 2}}
    g["players"]["p1"]["reserved"] = [res]
    g["players"]["p1"]["tokens"]["blue"] = 2
    ok, _, _ = apply(g, "p1", {"type": "buy", "card_id": "r1"})
    assert ok and g["players"]["p1"]["reserved"] == []
    assert res in g["players"]["p1"]["purchased"]


def test_buy_uses_gold_for_the_shortfall():
    g = make_game()
    g["board"]["L1"][0] = {"id": "tc1", "level": 1, "points": 0, "bonus": "blue",
                           "cost": {"white": 3}}
    g["players"]["p1"]["tokens"]["white"] = 1
    g["players"]["p1"]["tokens"]["gold"] = 2
    ok, _, _ = apply(g, "p1", {"type": "buy", "card_id": "tc1"})
    assert ok
    assert g["players"]["p1"]["tokens"]["gold"] == 0
    assert g["bank"]["gold"] == 7            # 5 + the 2 spent


def test_buy_deck_exhaustion_leaves_empty_slot():
    g = make_game()
    g["decks"]["L1"] = []
    g["board"]["L1"][0] = {"id": "tc1", "level": 1, "points": 0, "bonus": "blue", "cost": {}}
    ok, _, _ = apply(g, "p1", {"type": "buy", "card_id": "tc1"})
    assert ok and g["board"]["L1"][0] is None


# ─── nobles ──────────────────────────────────────────────────────────────────

def _bonus_cards(colour, n, start=0):
    return [{"id": f"{colour}{i+start}", "level": 1, "points": 0, "bonus": colour, "cost": {}}
            for i in range(n)]


def test_single_claimable_noble_auto_claims():
    g = make_game()
    g["nobles"] = [{"id": "n1", "points": 3, "req": {"red": 4, "green": 4}}]
    p = g["players"]["p1"]
    p["purchased"] = _bonus_cards("red", 4) + _bonus_cards("green", 3)
    g["board"]["L1"][0] = {"id": "tc1", "level": 1, "points": 0, "bonus": "green", "cost": {}}
    ok, _, fx = apply(g, "p1", {"type": "buy", "card_id": "tc1"})
    assert ok
    assert [n["id"] for n in p["nobles"]] == ["n1"]
    assert g["nobles"] == []
    assert fx["noble_choice_pid"] is None
    assert g["turn"] == "p2"                    # turn completed, no pending step


def test_two_claimable_nobles_enter_a_pending_choice():
    g = make_game()
    g["nobles"] = [{"id": "n1", "points": 3, "req": {"red": 4, "green": 4}},
                   {"id": "n2", "points": 3, "req": {"green": 4, "blue": 4}}]
    p = g["players"]["p1"]
    p["purchased"] = _bonus_cards("red", 4) + _bonus_cards("blue", 4) + _bonus_cards("green", 3)
    g["board"]["L1"][0] = {"id": "tc1", "level": 1, "points": 0, "bonus": "green", "cost": {}}
    ok, _, fx = apply(g, "p1", {"type": "buy", "card_id": "tc1"})
    assert ok
    assert fx["noble_choice_pid"] == "p1"
    assert g["pending_noble_pid"] == "p1"
    assert sorted(g["pending_noble_choice"]) == ["n1", "n2"]
    assert g["turn"] == "p1"                    # turn does NOT advance until resolved


def test_pick_noble_resolves_and_finishes_the_turn():
    g = make_game()
    g["nobles"] = [{"id": "n1", "points": 3, "req": {"red": 1}},
                   {"id": "n2", "points": 3, "req": {"blue": 1}}]
    g["pending_noble_pid"] = "p1"
    g["pending_noble_choice"] = ["n1", "n2"]
    ok, err, _ = apply(g, "p1", {"type": "pick_noble", "noble_id": "n2"})
    assert (ok, err) == (True, None)
    assert [n["id"] for n in g["players"]["p1"]["nobles"]] == ["n2"]
    assert [n["id"] for n in g["nobles"]] == ["n1"]
    assert "pending_noble_pid" not in g and "pending_noble_choice" not in g
    assert g["turn"] == "p2"


def test_pick_noble_outside_the_pending_set_rejected():
    g = make_game()
    g["nobles"] = [{"id": "n1", "points": 3, "req": {"red": 1}},
                   {"id": "n3", "points": 3, "req": {"black": 1}}]
    g["pending_noble_pid"] = "p1"
    g["pending_noble_choice"] = ["n1"]
    ok, err, _ = apply(g, "p1", {"type": "pick_noble", "noble_id": "n3"})
    assert (ok, err) == (False, "no noble choice pending")


def test_pick_noble_with_nothing_pending_rejected():
    g = make_game()
    ok, err, _ = apply(g, "p1", {"type": "pick_noble", "noble_id": "n1"})
    assert (ok, err) == (False, "no noble choice pending")


# ─── reserve ─────────────────────────────────────────────────────────────────

def test_reserve_board_card_grants_gold_and_refills():
    g = make_game()
    card = g["board"]["L2"][0]
    ok, err, _ = apply(g, "p1", {"type": "reserve", "card_id": card["id"]})
    assert (ok, err) == (True, None)
    assert card in g["players"]["p1"]["reserved"]
    assert g["players"]["p1"]["tokens"]["gold"] == 1
    assert g["bank"]["gold"] == 4
    assert g["board"]["L2"][0] is not None            # refilled


def test_reserve_from_deck_is_flagged_blind():
    g = make_game()
    ok, _, _ = apply(g, "p1", {"type": "reserve", "deck_level": 3})
    assert ok
    assert g["players"]["p1"]["reserved"][0]["from_deck"] is True
    # The log records that it was blind but not which card it was.
    entry = g["moves"][0]
    assert entry["type"] == "reserve" and entry["from_deck"] is True


def test_reserve_with_no_gold_left_grants_none():
    g = make_game()
    g["bank"]["gold"] = 0
    ok, _, _ = apply(g, "p1", {"type": "reserve", "card_id": g["board"]["L1"][0]["id"]})
    assert ok and g["players"]["p1"]["tokens"]["gold"] == 0


def test_reserve_cap_is_three():
    g = make_game()
    g["players"]["p1"]["reserved"] = [{"id": f"x{i}"} for i in range(3)]
    ok, err, _ = apply(g, "p1", {"type": "reserve", "card_id": g["board"]["L1"][0]["id"]})
    assert (ok, err) == (False, "already have 3 reserved")


def test_reserve_from_an_empty_deck_rejected():
    g = make_game()
    g["decks"]["L3"] = []
    ok, err, _ = apply(g, "p1", {"type": "reserve", "deck_level": 3})
    assert (ok, err) == (False, "card not found")


# ─── the discard sub-decision + undo ─────────────────────────────────────────

def _at_ten_tokens(g, pid="p1"):
    g["players"][pid]["tokens"] = {"white": 2, "blue": 2, "green": 2, "red": 2, "black": 2, "gold": 0}


def test_overfilling_take_parks_a_discard_and_holds_the_turn():
    g = make_game()
    _at_ten_tokens(g)
    ok, _, fx = apply(g, "p1", {"type": "take_gems", "colors": ["red"]})
    assert ok
    assert fx["discard_pid"] == "p1"
    assert g["pending_discard_pid"] == "p1"
    assert "pre_discard_snapshot" in g
    assert g["turn"] == "p1"                       # turn withheld until resolved


def test_discard_back_to_the_cap_completes_the_turn():
    g = make_game()
    _at_ten_tokens(g)
    apply(g, "p1", {"type": "take_gems", "colors": ["red"]})
    ok, _, fx = apply(g, "p1", {"type": "discard", "color": "red"})
    assert ok and fx["discard_pid"] is None
    assert "pending_discard_pid" not in g
    assert "pre_discard_snapshot" not in g
    assert sum(g["players"]["p1"]["tokens"].values()) == 10
    assert g["turn"] == "p2"


def test_discard_still_over_cap_keeps_the_pending_state():
    g = make_game()
    g["players"]["p1"]["tokens"] = {"white": 3, "blue": 3, "green": 3, "red": 1, "black": 0, "gold": 0}
    apply(g, "p1", {"type": "take_gems", "colors": ["red", "black", "white"]})   # -> 13
    ok, _, fx = apply(g, "p1", {"type": "discard", "color": "white"})            # -> 12
    assert ok and fx["discard_pid"] == "p1"
    assert g["pending_discard_pid"] == "p1"
    assert g["turn"] == "p1"


def test_discard_a_colour_you_do_not_hold_rejected():
    g = make_game()
    _at_ten_tokens(g)
    apply(g, "p1", {"type": "take_gems", "colors": ["red"]})
    ok, err, _ = apply(g, "p1", {"type": "discard", "color": "gold"})
    assert (ok, err) == (False, "can't discard that")


def test_undo_discard_reverts_the_whole_action():
    g = make_game()
    _at_ten_tokens(g)
    before = copy.deepcopy(g)
    apply(g, "p1", {"type": "take_gems", "colors": ["red", "blue"]})
    apply(g, "p1", {"type": "discard", "color": "green"})
    ok, err, _ = apply(g, "p1", {"type": "undo_discard"})
    assert (ok, err) == (True, None)
    assert g["players"]["p1"]["tokens"] == before["players"]["p1"]["tokens"]
    assert g["bank"] == before["bank"]
    assert g["moves"] == before["moves"]           # the log is rewound too
    assert "pending_discard_pid" not in g
    assert g["turn"] == "p1"


def test_undo_restores_in_place_so_the_caller_ref_stays_valid():
    """main.py holds `g = room["game"]` across the call; the engine must not swap the
    object out from under it (the handler used to rebind its own local)."""
    g = make_game()
    _at_ten_tokens(g)
    apply(g, "p1", {"type": "take_gems", "colors": ["red"]})
    same = g
    apply(g, "p1", {"type": "undo_discard"})
    assert same is g and same["turn"] == "p1"


def test_undo_with_nothing_pending_rejected():
    g = make_game()
    ok, err, _ = apply(g, "p1", {"type": "undo_discard"})
    assert (ok, err) == (False, "nothing to undo")


def test_undo_by_the_wrong_player_rejected():
    g = make_game()
    _at_ten_tokens(g)
    apply(g, "p1", {"type": "take_gems", "colors": ["red"]})
    # p2 isn't on turn, so the turn gate fires first — the point is it is NOT accepted.
    ok, err, _ = apply(g, "p2", {"type": "undo_discard"})
    assert ok is False


def test_overfilling_reserve_also_parks_a_discard():
    g = make_game()
    _at_ten_tokens(g)
    ok, _, fx = apply(g, "p1", {"type": "reserve", "card_id": g["board"]["L1"][0]["id"]})
    assert ok and fx["discard_pid"] == "p1"        # the granted gold pushed it to 11


# ─── final round / winner ────────────────────────────────────────────────────

def test_reaching_the_threshold_starts_the_final_round_not_the_end():
    g = make_game()
    g["players"]["p1"]["purchased"] = [
        {"id": "big", "level": 3, "points": 15, "bonus": "red", "cost": {}}]
    apply(g, "p1", {"type": "take_gems", "colors": ["red"]})
    assert g["final_round_trigger"] == "p1"
    assert g["phase"] == "playing"                 # p2 still gets a turn
    assert g["turn"] == "p2"


def test_game_resolves_once_the_round_returns_to_the_trigger():
    g = make_game()
    g["players"]["p1"]["purchased"] = [
        {"id": "big", "level": 3, "points": 15, "bonus": "red", "cost": {}}]
    apply(g, "p1", {"type": "take_gems", "colors": ["red"]})
    apply(g, "p2", {"type": "take_gems", "colors": ["blue"]})
    assert g["phase"] == "over"
    assert g["winner"] == "p1"


def test_long_mode_uses_the_per_game_win_points():
    g = make_game(win_points=21)
    g["players"]["p1"]["purchased"] = [
        {"id": "big", "level": 3, "points": 15, "bonus": "red", "cost": {}}]
    apply(g, "p1", {"type": "take_gems", "colors": ["red"]})
    assert "final_round_trigger" not in g          # 15 < 21
    assert g["phase"] == "playing"


def test_tiebreak_prefers_fewest_purchased():
    g = make_game()
    five = {"id": "a", "level": 3, "points": 15, "bonus": "red", "cost": {}}
    g["players"]["p1"]["purchased"] = [five]
    g["players"]["p2"]["purchased"] = [
        {"id": f"b{i}", "level": 1, "points": 5, "bonus": "blue", "cost": {}} for i in range(3)]
    apply(g, "p1", {"type": "take_gems", "colors": ["red"]})
    apply(g, "p2", {"type": "take_gems", "colors": ["blue"]})
    assert g["phase"] == "over" and g["winner"] == "p1"


def test_equal_points_and_cards_is_a_shared_win():
    g = make_game()
    for pid in ("p1", "p2"):
        g["players"][pid]["purchased"] = [
            {"id": f"{pid}c", "level": 3, "points": 15, "bonus": "red", "cost": {}}]
    apply(g, "p1", {"type": "take_gems", "colors": ["red"]})
    apply(g, "p2", {"type": "take_gems", "colors": ["blue"]})
    assert g["phase"] == "over" and sorted(g["winner"]) == ["p1", "p2"]


# ─── the move log ────────────────────────────────────────────────────────────

def test_log_is_newest_first_and_id_only():
    g = make_game()
    card = g["board"]["L1"][0]
    g["players"]["p1"]["tokens"] = {c: 7 for c in main.GEM_COLORS}
    g["players"]["p1"]["tokens"]["gold"] = 0
    apply(g, "p1", {"type": "buy", "card_id": card["id"]})
    apply(g, "p2", {"type": "take_gems", "colors": ["red"]})
    assert g["moves"][0]["type"] == "take_gems"        # newest first
    buy = next(m for m in g["moves"] if m["type"] == "buy")
    assert buy["card_id"] == card["id"] and "cost" not in buy   # id-only


# ─── differential vs the MCTS simulator ──────────────────────────────────────

def test_matches_sim_on_a_plain_take():
    """Where no sub-decision arises, the authoritative path and the simulator must
    agree exactly — that is the shared-semantics contract between them."""
    g1 = make_game()
    g2 = copy.deepcopy(g1)
    apply(g1, "p1", {"type": "take_gems", "colors": ["red", "blue", "green"]})
    main._sim_apply_move(g2, "p1", {"type": "take_gems", "colors": ["red", "blue", "green"]})
    assert g1["bank"] == g2["bank"]
    assert g1["players"]["p1"]["tokens"] == g2["players"]["p1"]["tokens"]
    assert g1["turn"] == g2["turn"]


def test_matches_sim_on_a_plain_buy():
    g1 = make_game()
    g1["board"]["L1"][0] = {"id": "tc1", "level": 1, "points": 1, "bonus": "blue",
                            "cost": {"white": 2}}
    g1["players"]["p1"]["tokens"]["white"] = 2
    g2 = copy.deepcopy(g1)
    apply(g1, "p1", {"type": "buy", "card_id": "tc1"})
    main._sim_apply_move(g2, "p1", {"type": "buy", "card_id": "tc1"})
    assert g1["bank"] == g2["bank"]
    assert [c["id"] for c in g1["players"]["p1"]["purchased"]] == \
           [c["id"] for c in g2["players"]["p1"]["purchased"]]
    assert g1["turn"] == g2["turn"]


def test_sim_deliberately_collapses_the_discard_subdecision():
    """DOCUMENTED DIVERGENCE, not a bug: the search treats an over-cap take as forced,
    auto-discarding with a heuristic, while the live path stops and asks the player.
    Pinned so a future 'unification' has to face the choice explicitly."""
    g1 = make_game()
    _at_ten_tokens(g1)
    g2 = copy.deepcopy(g1)
    apply(g1, "p1", {"type": "take_gems", "colors": ["red"]})
    main._sim_apply_move(g2, "p1", {"type": "take_gems", "colors": ["red"]})

    assert g1["pending_discard_pid"] == "p1" and g1["turn"] == "p1"      # asks
    assert "pending_discard_pid" not in g2 and g2["turn"] == "p2"        # auto-resolves
    assert sum(g2["players"]["p1"]["tokens"].values()) == 10


def test_sim_deliberately_collapses_the_noble_choice():
    g1 = make_game()
    g1["nobles"] = [{"id": "n1", "points": 3, "req": {"red": 4, "green": 4}},
                    {"id": "n2", "points": 3, "req": {"green": 4, "blue": 4}}]
    p = g1["players"]["p1"]
    p["purchased"] = _bonus_cards("red", 4) + _bonus_cards("blue", 4) + _bonus_cards("green", 3)
    g1["board"]["L1"][0] = {"id": "tc1", "level": 1, "points": 0, "bonus": "green", "cost": {}}
    g2 = copy.deepcopy(g1)
    apply(g1, "p1", {"type": "buy", "card_id": "tc1"})
    main._sim_apply_move(g2, "p1", {"type": "buy", "card_id": "tc1"})

    assert g1["pending_noble_pid"] == "p1"                       # asks
    assert "pending_noble_pid" not in g2                         # auto-picks
    assert len(g2["players"]["p1"]["nobles"]) == 1


@pytest.mark.parametrize("seed", range(8))
def test_random_legal_play_preserves_token_conservation(seed):
    """Soak: gems only move between the bank and hands, so the per-colour totals are
    invariant for the whole game (5x the per-colour bank + 5 gold in a 2p setup)."""
    rng = random.Random(seed)
    g = make_game()
    totals = {c: g["bank"][c] for c in list(main.GEM_COLORS) + ["gold"]}

    for _ in range(400):
        if g["phase"] == "over":
            break
        pid = g["turn"]
        moves = main._get_all_moves(g, pid)
        if not moves:
            break
        ok, err, fx = apply(g, pid, rng.choice(moves))
        if not ok:
            continue
        # Resolve any sub-decision the same way a player would, so play continues.
        while g.get("pending_discard_pid") == pid:
            colour = next(c for c, n in g["players"][pid]["tokens"].items() if n > 0)
            apply(g, pid, {"type": "discard", "color": colour})
        if g.get("pending_noble_pid") == pid:
            apply(g, pid, {"type": "pick_noble", "noble_id": g["pending_noble_choice"][0]})

        for c in totals:
            held = sum(p["tokens"].get(c, 0) for p in g["players"].values())
            assert g["bank"].get(c, 0) + held == totals[c], f"{c} leaked/duplicated"
