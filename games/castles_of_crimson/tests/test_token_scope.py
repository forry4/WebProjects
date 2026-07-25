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
