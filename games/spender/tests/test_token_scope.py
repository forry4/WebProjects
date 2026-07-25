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


def test_decks_shipped_as_lengths_not_card_order():
    """mk_room_state must NOT ship the ordered draw piles — a client could otherwise read the
    exact future draws. Only per-level lengths (same-length null lists) reach the wire, and the
    live game dict is left untouched."""
    real_decks = {"L1": [{"id": "c1"}, {"id": "c2"}, {"id": "c3"}],
                  "L2": [{"id": "d1"}], "L3": []}
    m.ROOMS["TDECK"] = {
        "players": {"a": "A"}, "host": "a", "status": "playing",
        "game": {"decks": real_decks, "players": {}, "moves": [], "phase": "playing"},
        "meta": {"a": {"token": "t"}},
    }
    try:
        gv = m.mk_room_state("TDECK", viewer_pid="a")["game"]
        assert [len(gv["decks"][lk]) for lk in ("L1", "L2", "L3")] == [3, 1, 0]  # counts kept
        assert all(x is None for lk in gv["decks"] for x in gv["decks"][lk])     # no identities
        # live dict untouched — still the real card dicts
        assert m.ROOMS["TDECK"]["game"]["decks"] is real_decks
        assert real_decks["L1"][0] == {"id": "c1"}
    finally:
        m.ROOMS.pop("TDECK", None)
