"""mk_room_state / broadcast_room must reveal only the RECIPIENT's own reconnect token,
never other seats' — a per-recipient secret. Was: every seat's token to everyone."""
import asyncio
import json

from games.castles_of_crimson import main as m


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, t):
        self.sent.append(json.loads(t))


def _room(sockets=None):
    m.ROOMS["TSCOPE"] = {
        "players": {"a": "A", "b": "B"},
        "sockets": sockets or {},
        "host": "a",
        "status": "playing",
        "game": None,
        "meta": {"a": {"token": "tok-a"}, "b": {"token": "tok-b"}},
    }


def test_viewer_sees_only_own_token():
    _room()
    try:
        assert m.mk_room_state("TSCOPE", viewer_pid="a")["reconnect_tokens"] == {"a": "tok-a"}
        assert m.mk_room_state("TSCOPE", viewer_pid="b")["reconnect_tokens"] == {"b": "tok-b"}
        assert m.mk_room_state("TSCOPE")["reconnect_tokens"] == {}
    finally:
        m.ROOMS.pop("TSCOPE", None)


def test_broadcast_injects_only_recipient_token():
    ws_a, ws_b = _FakeWS(), _FakeWS()
    _room(sockets={"a": ws_a, "b": ws_b})
    try:
        base = m.mk_room_state("TSCOPE")  # no tokens in the shared snapshot
        asyncio.new_event_loop().run_until_complete(
            m.broadcast_room("TSCOPE", {"type": "room_update", "room": base}))
        assert ws_a.sent[0]["room"]["reconnect_tokens"] == {"a": "tok-a"}
        assert ws_b.sent[0]["room"]["reconnect_tokens"] == {"b": "tok-b"}
    finally:
        m.ROOMS.pop("TSCOPE", None)


def test_supply_and_rng_not_shipped_to_wire():
    """mk_room_state must strip the ordered draw piles (future depot tiles) and rng_state (from
    which a client could reconstruct every future die for BOTH players) — both hidden in real
    Castles of Burgundy. Non-hidden fields survive and the live game dict is untouched."""
    live = {"supply": [1, 2, 3], "black_supply": [9], "goods_supply": [7, 8],
            "rng_state": [1, [2, 3], None], "depots": {"marker": True}, "phase": "playing"}
    m.ROOMS["TLEAK"] = {
        "players": {"a": "A"}, "sockets": {}, "host": "a", "status": "playing",
        "game": live, "meta": {"a": {"token": "t"}},
    }
    try:
        gv = m.mk_room_state("TLEAK", viewer_pid="a")["game"]
        for hidden in ("supply", "black_supply", "goods_supply", "rng_state"):
            assert hidden not in gv, f"{hidden} leaked to the wire"
        assert gv["depots"] == {"marker": True}   # non-hidden fields preserved
        assert live["supply"] == [1, 2, 3]        # live dict untouched
        assert "rng_state" in live
    finally:
        m.ROOMS.pop("TLEAK", None)


def test_no_hidden_state_anywhere_in_a_real_broadcast():
    """The test above builds a synthetic game dict, so it can only prove the TOP-LEVEL
    keys are stripped — and that is exactly how the leak got in: `turn_undo` is a
    whole-game snapshot carrying its own copy of all four hidden keys, and shipping it
    defeated the redaction entirely (100 ordered supply tiles + rng_state on the wire).

    So this runs a REAL in-progress game and searches the whole serialized payload,
    which is the only form that catches a hidden field nested inside a new one."""
    import json
    import random

    from games.castles_of_crimson import engine

    g = engine.new_game(["a", "b"], seed=4)
    rng = random.Random(99)
    for _ in range(60):                       # play in far enough to arm a snapshot
        if engine.is_over(g):
            break
        pid = g.get("pending_pid") or g.get("turn")
        moves = engine.legal_moves(g, pid)
        if not moves:
            break
        engine.apply_move(g, pid, rng.choice(moves))
    assert "turn_undo" in g, "test needs a game with an armed undo snapshot"

    m.ROOMS["TDEEP"] = {
        "players": {"a": "A", "b": "B"}, "sockets": {}, "host": "a",
        "status": "playing", "game": g, "meta": {"a": {"token": "t"}},
    }
    try:
        for viewer in ("a", "b", None):
            blob = json.dumps(m.mk_room_state("TDEEP", viewer_pid=viewer))
            for hidden in ("supply", "black_supply", "goods_supply", "rng_state"):
                assert f'"{hidden}"' not in blob, f"{hidden} leaked to {viewer}'s wire"
        assert len(g["supply"]) > 0 and g["rng_state"] is not None   # live dict intact
    finally:
        m.ROOMS.pop("TDEEP", None)
