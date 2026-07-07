import importlib


def test_reconnect_token_scoped_to_viewer():
    m = importlib.import_module('games.spender.main')
    room = 'TEST'
    pid = 'P1'
    other = 'P2'
    m.ROOMS[room] = {
        "players": {pid: 'Player', other: 'Other'},
        "sockets": {}, "status": "waiting", "game": None,
        "meta": {pid: {"token": "abc123"}, other: {"token": "xyz789"}},
    }
    try:
        # A viewer gets ONLY its own token — never other seats'.
        state = m.mk_room_state(room, viewer_pid=pid)
        assert state['reconnect_tokens'] == {pid: 'abc123'}
        # A no-viewer build (transient, rebuilt per-recipient by broadcast_room) leaks nothing.
        assert m.mk_room_state(room)['reconnect_tokens'] == {}
    finally:
        m.ROOMS.pop(room, None)
