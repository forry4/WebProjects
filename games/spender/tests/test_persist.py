"""The at-rest compaction must be EXACTLY lossless.

`persist.compact_state` sits on the DB boundary, so a bug here is a saved game that
loads back subtly different. These tests round-trip real game dicts and check the two
things a happy-path round-trip alone can't: that the card-location list still covers
every card, and that a card which does NOT match its catalog entry (a blind deck
reserve carries `from_deck`) survives verbatim rather than being flattened to an id.
"""
import copy
import json

from core import rooms as _rooms
from games.spender import cards as C, engine, persist


def _game(bought=20, reserved=3, logged=60):
    """A late-game-shaped dict: the same keys main.py builds and saves."""
    decks = C.build_deck()
    board = engine.deal_board(decks)
    g = {
        "bank": C.empty_gems(), "decks": decks, "board": board,
        "nobles": [dict(n) for n in C.ALL_NOBLES[:3]],
        "players": {p: {"tokens": C.empty_gems(), "purchased": [], "reserved": [],
                        "nobles": []} for p in ("p0", "p1")},
        "turn": "p0", "order": ["p0", "p1"], "phase": "playing", "winner": None,
        "moves": [], "win_points": 15,
    }
    for i in range(bought):
        lk = "L1" if i < 12 else ("L2" if i < 18 else "L3")
        if decks[lk]:
            g["players"]["p0" if i % 2 else "p1"]["purchased"].append(decks[lk].pop())
    for _ in range(reserved):
        if decks["L1"]:
            g["players"]["p0"]["reserved"].append(decks["L1"].pop())
    g["players"]["p0"]["nobles"].append(dict(C.ALL_NOBLES[0]))
    for _ in range(logged):
        g["moves"].insert(0, {"pid": "p0", "type": "buy", "card_id": "L1-12"})
    engine.capture_setup(g)
    return g


def _state(game):
    return {"players": {"p0": "A", "p1": "B"}, "host": "p0", "status": "playing",
            "game": game, "meta": {}, "ai_variant": None, "max_players": 2}


def _count_cards(o):
    """Every card/noble OBJECT anywhere in the structure, found structurally."""
    if isinstance(o, dict):
        if "id" in o and ("cost" in o or "req" in o):
            return 1
        return sum(_count_cards(v) for v in o.values())
    if isinstance(o, list):
        return sum(_count_cards(v) for v in o)
    return 0


# ── losslessness ─────────────────────────────────────────────────────────────
def test_round_trip_is_exact():
    for bought, res in ((0, 0), (5, 1), (20, 3), (40, 3)):
        state = _state(_game(bought, res))
        before = json.loads(json.dumps(state))
        assert persist.expand_state(persist.compact_state(state)) == before, (bought, res)


def test_round_trip_through_the_real_db_codec():
    state = _state(_game())
    before = json.loads(json.dumps(state))
    blob = _rooms.encode_state(persist.compact_state(state))
    assert blob.startswith("z:")
    assert persist.expand_state(_rooms.decode_state(blob)) == before


def test_compaction_does_not_mutate_the_live_game():
    """`state["game"]` is the LIVE dict of a running room — save must not touch it."""
    state = _state(_game())
    untouched = copy.deepcopy(state)
    persist.compact_state(state)
    assert state == untouched


# ── the fallback, which is load-bearing ──────────────────────────────────────
def test_a_card_that_differs_from_the_catalog_survives_verbatim():
    """`_apply_reserve` stamps `from_deck` on a blind deck reserve, so not every card
    equals its catalog entry. Flattening one to an id would silently drop the flag."""
    g = _game()
    marked = dict(g["players"]["p0"]["reserved"][0])
    marked["from_deck"] = True
    g["players"]["p0"]["reserved"][0] = marked
    packed = persist.compact_state(_state(g))["game"]
    assert packed["players"]["p0"]["reserved"][0] == marked      # kept as an object
    assert persist.expand_state(persist.compact_state(_state(g)))["game"] == \
        json.loads(json.dumps(g))


def test_the_pending_discard_snapshot_is_compacted_too():
    """It is a whole second copy of the game and carries every card location again."""
    g = _game()
    g["pre_discard_snapshot"] = copy.deepcopy(g)
    packed = persist.compact_state(_state(g))["game"]
    assert _count_cards(packed["pre_discard_snapshot"]) == 0
    assert persist.expand_state(persist.compact_state(_state(g)))["game"] == \
        json.loads(json.dumps(g))


# ── coverage + the id-string keys a generic walk would corrupt ───────────────
def test_every_card_object_is_reached():
    for bought in (0, 20, 40):
        g = _game(bought)
        packed = persist.compact_state(_state(g))["game"]
        assert _count_cards(g) > 0
        assert _count_cards(packed) == 0, "a card location was missed"


def test_the_id_only_structures_are_left_alone():
    """`moves` and `setup` already hold BARE ID STRINGS. A generic walk would try to
    'decode' them into card objects; this codec must not touch them."""
    g = _game()
    state = _state(g)
    packed = persist.compact_state(state)["game"]
    assert packed["moves"] == g["moves"]
    assert packed["setup"] == g["setup"]
    out = persist.expand_state(persist.compact_state(state))["game"]
    assert out["setup"]["decks"]["L1"] == g["setup"]["decks"]["L1"]   # still strings
    assert all(isinstance(x, str) for x in out["setup"]["decks"]["L1"])


# ── backward compatibility + effect ──────────────────────────────────────────
def test_legacy_uncompacted_blob_passes_through():
    legacy = json.loads(json.dumps(_state(_game())))
    assert persist.expand_state(legacy) == legacy


def test_compaction_actually_shrinks_the_blob():
    state = _state(_game())
    plain = len(_rooms.encode_state(state))
    packed = len(_rooms.encode_state(persist.compact_state(state)))
    assert packed < plain * 0.6, f"{packed} vs {plain} — compaction lost its effect"
