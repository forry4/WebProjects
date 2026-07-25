"""WebSocket identity binding (main.py).

The `player` path segment is client-supplied, and every pid in a room is broadcast in
the public players map — so anyone who can see a game could open a socket claiming
another seat's pid, receive that seat's `viewer_pid`-redacted view (which reveals its
own blind reserves), and move on its turn: the move handler only checks whose turn it
is, never who the socket is.

These tests pin the rule that a socket must PROVE ownership of its pid before it can
act as that seat. Mirrors games/wherewolf/tests/test_ws_auth.py, where this binding
pattern was first shipped, and its Duel/CoC counterparts.

Drives the WS loop directly with a fake websocket; DB access is stubbed so these never
touch a real users.db.
"""
import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms
from games.spender import main as m


class _FakeWS:
    """Records sent frames and replays a scripted inbox for the WS loop."""

    def __init__(self, inbox=None, on_drain=None):
        self.sent = []
        self._inbox = list(inbox or [])
        # Called once the scripted inbox is exhausted, just BEFORE this socket
        # disconnects — see _create for why that moment matters.
        self._on_drain = on_drain

    async def accept(self):
        pass

    async def close(self, code=1000):
        pass

    async def send_text(self, t):
        self.sent.append(t)

    async def receive_text(self):
        if self._inbox:
            return self._inbox.pop(0)
        if self._on_drain:
            self._on_drain()
            self._on_drain = None
        raise WebSocketDisconnect()

    def msgs(self):
        return [json.loads(t) for t in self.sent]

    def types(self):
        return [d.get("type") for d in self.msgs()]

    def errors(self):
        return [d.get("message") for d in self.msgs() if d.get("type") == "error"]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """No DB, no AI scheduling, a clean ROOMS slate, and nobody logged in unless a
    test says so. A fresh per-test event loop + ROOM_LOCK so the module-level lock
    never straddles two loops."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    # The WS connect throttle (core.rooms) is a per-process sliding window keyed on
    # client IP — and every fake socket here reports "unknown", so the whole suite
    # shares ONE 60/min budget with no natural reset. Left alone, adding tests (or a
    # re-run inside the same minute) starts closing sockets with 1008 and the failures
    # look like anything but a rate limit. Reset it per test.
    _rooms._ws_connect_limiter.reset()
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "load_game_to_memory", lambda room_id: False)
    monkeypatch.setattr(m, "get_user_by_session", lambda tok: None)

    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(m, "_schedule_ai_turn", _noop)
    yield
    loop.close()


def _run(ws, room, pid):
    asyncio.get_event_loop().run_until_complete(m.ws_room_player(ws, room, pid))


AUTH_ERR = "not authenticated for this seat"


def _create(room="ROOMA", pid="host", extra=None):
    """Run a full create handshake on its own socket, leaving the room in ROOMS.

    `ws_room_player` returns only on disconnect, and its `finally` drops the room once
    the LAST socket goes — so a scripted socket that runs to completion would delete
    the room it just made. Park an inert keeper socket at the moment the inbox drains
    (i.e. while the room still exists) to hold it open for the rest of the test.
    It is never a seat: it lives in `sockets` only, never in `players`, and
    broadcast_room tolerates any send failure anyway.
    """
    msg = {"action": "create", "name": "Host"}
    msg.update(extra or {})

    def _keep():
        m.ROOMS[room]["sockets"]["_keeper"] = _FakeWS()

    ws = _FakeWS(inbox=[json.dumps(msg)], on_drain=_keep)
    _run(ws, room, pid)
    return ws


# ── privileged actions require a handshake ───────────────────────────────────

@pytest.mark.parametrize("action", [
    "start", "move", "abandon", "ping", "ai_move", "client_ai_ready", "client_ai_hidden",
])
def test_privileged_actions_gated_before_handshake(action):
    """A spoofed-pid socket that never handshakes can't act. The gate fires BEFORE the
    handler, so the error is the auth one, not the handler's own complaint."""
    _create(room="ROOMB", pid="host")
    ws = _FakeWS(inbox=[json.dumps({"action": action, "move": {"type": "take_gems",
                                                              "colors": ["red"]},
                                    "target": "host"})])
    _run(ws, "ROOMB", "host")
    assert AUTH_ERR in ws.errors()


def test_create_authenticates_the_creator():
    ws = _create(room="ROOMC", pid="host")
    assert "created" in ws.types()
    assert AUTH_ERR not in ws.errors()


def test_creator_can_move_on_the_same_socket():
    """Sanity control: the gate is about identity, not a blanket block."""
    ws = _FakeWS(inbox=[
        json.dumps({"action": "create", "name": "Host", "vs_ai": True, "ai_variant": "H3"}),
        json.dumps({"action": "move", "move": {"type": "take_gems", "colors": ["red"]}}),
    ])
    _run(ws, "ROOMD", "host")
    assert AUTH_ERR not in ws.errors()


# ── join to an occupied seat needs proof ─────────────────────────────────────

def test_join_new_seat_authenticates():
    _create(room="ROOME", pid="host")
    ws = _FakeWS(inbox=[json.dumps({"action": "join", "name": "Guest"})])
    _run(ws, "ROOME", "guest")
    assert "joined" in ws.types()
    assert "guest" in m.ROOMS["ROOME"]["players"]


def test_join_an_occupied_seat_without_proof_is_rejected():
    """The core exploit: a stranger claiming a seated pid must NOT get the seat."""
    _create(room="ROOMF", pid="host")
    victim = _FakeWS(inbox=[json.dumps({"action": "join", "name": "Victim"})])
    _run(victim, "ROOMF", "victim")

    attacker = _FakeWS(inbox=[json.dumps({"action": "join", "name": "hijack"})])
    _run(attacker, "ROOMF", "victim")

    assert "joined" not in attacker.types()       # never got the private view
    assert any("seat already taken" in e for e in attacker.errors())
    assert m.ROOMS["ROOMF"]["players"]["victim"] == "Victim"   # name not overwritten


def test_hijack_attempt_cannot_then_move():
    """End to end: the rejected join leaves the socket unauthenticated, so the move
    it follows up with is refused rather than played as the victim."""
    _create(room="ROOMG", pid="host")
    _run(_FakeWS(inbox=[json.dumps({"action": "join", "name": "Victim"})]), "ROOMG", "victim")

    attacker = _FakeWS(inbox=[
        json.dumps({"action": "join", "name": "hijack"}),
        json.dumps({"action": "move", "move": {"type": "take_gems", "colors": ["red"]}}),
    ])
    _run(attacker, "ROOMG", "victim")
    assert AUTH_ERR in attacker.errors()


def test_join_an_occupied_seat_with_matching_session_is_allowed(monkeypatch):
    """A logged-in user re-entering their OWN seat (pid == account id) is allowed."""
    _create(room="ROOMH", pid="host")
    _run(_FakeWS(inbox=[json.dumps({"action": "join", "name": "Real"})]), "ROOMH", "acct-1")

    monkeypatch.setattr(m, "get_user_by_session",
                        lambda tok: {"id": "acct-1"} if tok == "good" else None)
    ws = _FakeWS(inbox=[json.dumps({"action": "join", "name": "Real",
                                    "session_token": "good"})])
    _run(ws, "ROOMH", "acct-1")
    assert "joined" in ws.types()                 # accepted back into its own seat
    assert not ws.errors()


def test_join_an_occupied_seat_with_another_account_is_rejected(monkeypatch):
    """A valid session for a DIFFERENT account can't claim someone else's seat."""
    _create(room="ROOMI", pid="host")
    _run(_FakeWS(inbox=[json.dumps({"action": "join", "name": "Victim"})]), "ROOMI", "acct-victim")

    monkeypatch.setattr(m, "get_user_by_session", lambda tok: {"id": "acct-attacker"})
    ws = _FakeWS(inbox=[json.dumps({"action": "join", "name": "x",
                                    "session_token": "attacker-sess"})])
    _run(ws, "ROOMI", "acct-victim")
    assert "joined" not in ws.types()


# ── the room reconnect token still works ─────────────────────────────────────

def test_reconnect_with_the_seat_token_authenticates():
    _create(room="ROOMJ", pid="host")
    _run(_FakeWS(inbox=[json.dumps({"action": "join", "name": "Guest"})]), "ROOMJ", "guest")
    tok = m.ROOMS["ROOMJ"]["meta"]["guest"]["token"]

    ws = _FakeWS(inbox=[
        json.dumps({"action": "reconnect", "token": tok}),
        json.dumps({"action": "ping", "target": "host"}),
    ])
    _run(ws, "ROOMJ", "guest")
    assert "reconnected" in ws.types()
    assert AUTH_ERR not in ws.errors()


def test_reconnect_with_a_wrong_token_does_not_authenticate():
    _create(room="ROOMK", pid="host")
    _run(_FakeWS(inbox=[json.dumps({"action": "join", "name": "Guest"})]), "ROOMK", "guest")

    ws = _FakeWS(inbox=[
        json.dumps({"action": "reconnect", "token": "nope"}),
        json.dumps({"action": "move", "move": {"type": "take_gems", "colors": ["red"]}}),
    ])
    _run(ws, "ROOMK", "guest")
    assert "reconnected" not in ws.types()
    assert AUTH_ERR in ws.errors()


# ── disconnect cleanup (shared guard, Spender's own policy) ──────────────────

def test_stale_socket_disconnect_stays_silent():
    """A socket already superseded by a reconnect must not be treated as a leaver:
    it removes nothing and broadcasts nothing. (The shared core/rooms guard covers
    the removal; this pins Spender's extra 'tell the survivors' broadcast, which
    must fire ONLY when our socket was really the live one.)"""
    _create(room="ROOML", pid="host")
    live = _FakeWS()
    m.ROOMS["ROOML"]["sockets"]["guest"] = live
    m.ROOMS["ROOML"]["players"]["guest"] = "Guest"

    stale = _FakeWS()                      # never registered — superseded
    _run(stale, "ROOML", "guest")

    assert m.ROOMS["ROOML"]["sockets"]["guest"] is live   # live socket untouched
    assert live.types() == []                             # survivors not notified


def test_departing_socket_notifies_the_survivors():
    """The control for the above: when OUR socket really is the live one and the
    room outlives it, the remaining sockets do get a room_update."""
    _create(room="ROOMM", pid="host")
    other = _FakeWS()
    m.ROOMS["ROOMM"]["sockets"]["other"] = other
    m.ROOMS["ROOMM"]["players"]["other"] = "Other"

    leaver = _FakeWS(inbox=[json.dumps({"action": "join", "name": "Guest"})])
    _run(leaver, "ROOMM", "guest")

    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))  # let the task run
    assert "guest" not in m.ROOMS["ROOMM"]["sockets"]
    assert "room_update" in other.types()


def test_connecting_alone_leaks_nothing():
    """REGRESSION (found in the pre-ship health check). The socket used to be
    registered in `room["sockets"]` at CONNECT time, before any proof of identity.
    Because broadcast_room rebuilds room state PER RECIPIENT keyed on that pid,
    merely opening a socket claiming a victim's pid — sending nothing at all —
    returned that seat's own view: its blind reserves AND its `reconnect_tokens`
    entry, which could then be replayed as `{"action":"reconnect"}` to become fully
    authenticated. It also displaced the victim's live socket, dropping them.
    """
    _create(room="ROOMN", pid="victim")
    m.ROOMS["ROOMN"]["game"]["players"]["victim"]["reserved"] = [
        {"id": "L3-7", "level": 3, "from_deck": True, "points": 5, "bonus": "red", "cost": {}}]
    live = _FakeWS()
    m.ROOMS["ROOMN"]["sockets"]["victim"] = live

    attacker = _FakeWS()                       # connects, sends nothing
    _run(attacker, "ROOMN", "victim")

    assert attacker.sent == []                                  # no frame at all
    assert m.ROOMS["ROOMN"]["sockets"]["victim"] is live        # victim not dropped


def test_connect_does_not_register_the_socket():
    """The mechanism behind the above, pinned directly: connecting is not a
    handshake, so it must not put the socket in the room."""
    _create(room="ROOMO", pid="host")
    before = dict(m.ROOMS["ROOMO"]["sockets"])
    _run(_FakeWS(), "ROOMO", "stranger")
    assert dict(m.ROOMS["ROOMO"]["sockets"]) == before
