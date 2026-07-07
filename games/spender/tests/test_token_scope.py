"""mk_room_state must reveal only the RECIPIENT's own reconnect token, never other
seats' — a per-recipient secret. Was: every seat's token broadcast to everyone."""
from games.spender import main as m


def _room():
    m.ROOMS["TSCOPE"] = {
        "players": {"a": "A", "b": "B"},
        "host": "a",
        "status": "playing",
        "game": None,
        "meta": {"a": {"token": "tok-a"}, "b": {"token": "tok-b"}},
    }


def test_viewer_sees_only_own_token():
    _room()
    try:
        av = m.mk_room_state("TSCOPE", viewer_pid="a")["reconnect_tokens"]
        bv = m.mk_room_state("TSCOPE", viewer_pid="b")["reconnect_tokens"]
        assert av == {"a": "tok-a"}
        assert bv == {"b": "tok-b"}
    finally:
        m.ROOMS.pop("TSCOPE", None)


def test_no_viewer_leaks_nothing():
    _room()
    try:
        assert m.mk_room_state("TSCOPE")["reconnect_tokens"] == {}
    finally:
        m.ROOMS.pop("TSCOPE", None)
