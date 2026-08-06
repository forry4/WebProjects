"""End-to-end: a room is actually creatable and playable to a result.

Mounting a screen is not the same as being able to start a game — Dontminion's
Renaissance set rendered fine and could not be created, because a list in
main.py had not been updated. This drives the real WS handlers from create
through the auction and all thirteen tricks to a scored result, so that class
of failure cannot pass silently here.
"""

import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms
from games.oddtrick import engine as E
from games.oddtrick import main as m


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, t):
        self.sent.append(t)

    async def receive_text(self):
        raise WebSocketDisconnect()

    def last(self, mtype=None):
        for t in reversed(self.sent):
            d = json.loads(t)
            if mtype is None or d.get("type") == mtype:
                return d
        return None

    def types(self):
        return [json.loads(t).get("type") for t in self.sent]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    _rooms._ws_connect_limiter = _rooms.SlidingWindowLimiter(
        _rooms.WS_CONNECTS_PER_MIN, 60)
    monkeypatch.setattr(m, "save_game", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "_ensure_room_loaded", lambda rid: m.ROOMS.get(rid))
    monkeypatch.setattr(m, "get_user_by_session", lambda _t: None)
    yield
    loop.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_a_two_player_room_plays_from_create_to_a_scored_result():
    wa, wb = _FakeWS(), _FakeWS()
    assert run(m._handle_create(wa, "R", "alice", {"name": "Alice"})) is True
    assert run(m._handle_join(wb, "R", "bob", {"name": "Bob"})) is True
    run(m._handle_start(wa, "R", "alice"))

    room = m.ROOMS["R"]
    g = room["game"]
    assert g is not None, "starting must deal a game"
    assert g["phase"] == "auction"

    guard = 0
    while g["phase"] != "over":
        guard += 1
        assert guard < 200, "the room failed to reach a result"
        pid = E.turn_pid(g)
        ws = wa if pid == "alice" else wb
        if g["phase"] == "auction":
            opt = E.auction_options(g)
            if opt["may_pass"]:
                move = {"kind": "pass"}
            else:
                lvl, den = opt["bids"][0]
                move = {"kind": "bid", "level": lvl, "denom": den}
        elif g["phase"] == "swap":
            move = {"kind": "swap", "take": None}
        else:
            seat = E.seat_of(g, pid)
            move = {"kind": "play", "card": E.legal_moves(g, seat)[0]}
        run(m._handle_move(ws, "R", pid, {"move": move}))

    assert g["trick"] == E.NTRICKS
    assert g["result"] is not None
    assert sum(g["pts"]) == E.POOL
    assert room["status"] == "over", "the room status must follow the game"
    # And no handler ever reported an error along the way.
    assert "error" not in wa.types() and "error" not in wb.types()


def test_a_vs_bot_room_is_creatable_and_the_bot_takes_its_turn():
    ws = _FakeWS()
    assert run(m._handle_create(ws, "B", "alice",
                                {"name": "Alice", "vs_ai": True,
                                 "ai_difficulty": "normal"})) is True
    room = m.ROOMS["B"]
    assert room["game"] is not None, "a vs-bot room deals immediately"
    assert room["ai_player"] == m.AI_PID

    # Drive it to the end, letting the scheduler play every bot turn.
    guard = 0
    while room["game"]["phase"] != "over":
        guard += 1
        assert guard < 300
        g = room["game"]
        pid = E.turn_pid(g)
        if pid == m.AI_PID:
            run(m._schedule_bot_turn("B"))
            continue
        if g["phase"] == "auction":
            opt = E.auction_options(g)
            move = ({"kind": "pass"} if opt["may_pass"]
                    else {"kind": "bid", "level": opt["bids"][0][0],
                          "denom": opt["bids"][0][1]})
        elif g["phase"] == "swap":
            move = {"kind": "swap", "take": None}
        else:
            move = {"kind": "play", "card": E.legal_moves(g, E.seat_of(g, pid))[0]}
        run(m._handle_move(ws, "B", pid, {"move": move}))

    assert room["game"]["result"] is not None
    assert sum(room["game"]["pts"]) == E.POOL


def test_an_illegal_move_is_refused_without_corrupting_the_game():
    wa, wb = _FakeWS(), _FakeWS()
    run(m._handle_create(wa, "R", "alice", {"name": "Alice"}))
    run(m._handle_join(wb, "R", "bob", {"name": "Bob"}))
    run(m._handle_start(wa, "R", "alice"))
    g = m.ROOMS["R"]["game"]
    before = json.dumps(g, sort_keys=True)

    mover = E.turn_pid(g)
    other = "bob" if mover == "alice" else "alice"
    # Wrong player.
    run(m._handle_move(wa if other == "alice" else wb, "R", other,
                       {"move": {"kind": "bid", "level": 3, "denom": 0}}))
    # Right player, illegal level (the opener may not raise past the cap).
    run(m._handle_move(wa if mover == "alice" else wb, "R", mover,
                       {"move": {"kind": "bid", "level": 99, "denom": 0}}))
    # Right player, wrong phase.
    run(m._handle_move(wa if mover == "alice" else wb, "R", mover,
                       {"move": {"kind": "play", "card": 0}}))

    assert json.dumps(g, sort_keys=True) == before, "a refused move must not mutate state"


def test_the_catalog_matches_the_engine():
    """The client renders trick values from /catalog; if the two ever disagree
    the board would lie about what a trick is worth."""
    cat = run(m.catalog())
    assert cat["trick_values"] == [E.trick_value(t) for t in range(E.NTRICKS)]
    assert cat["pool"] == E.POOL
    assert sum(cat["trick_values"]) == cat["pool"]
    assert cat["max_raise"] == E.MAX_RAISE
    assert cat["short_penalty"] == E.SHORT_PENALTY
