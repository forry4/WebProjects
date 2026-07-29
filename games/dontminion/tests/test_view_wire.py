"""Wire-redaction tests: capture EVERY payload each socket ever receives and
assert the hidden-information matrix over all of them — no deck arrays, hands
only to their owner, discard as top+count, the pending frame's constraint only
to the actor (and its data to nobody), reconnect_tokens only the viewer's own,
rng_state/seed absent, and the game-over reveal."""

import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms
from games.dontminion import engine
from games.dontminion import main as m

A, B, C = "alice", "bob", "carol"


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, t):
        self.sent.append(t)

    async def receive_text(self):
        raise WebSocketDisconnect()

    def rooms_seen(self):
        return [json.loads(t)["room"] for t in self.sent
                if json.loads(t).get("room")]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    _rooms._ws_connect_limiter.reset()
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "load_game_to_memory", lambda room_id: False)
    monkeypatch.setattr(m, "get_user_by_session", lambda tok: None)
    monkeypatch.setattr(m, "_kick_bots", lambda room_id: None)
    yield
    loop.close()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _three_player_room(rid="WIRE"):
    sockets = {A: _FakeWS(), B: _FakeWS(), C: _FakeWS()}
    _run(m._handle_create(sockets[A], rid, A, {"name": "Alice"}))
    _run(m._handle_join(sockets[B], rid, B, {"name": "Bob"}))
    _run(m._handle_join(sockets[C], rid, C, {"name": "Carol"}))
    _run(m._handle_start(sockets[A], rid, A))
    return sockets


def _assert_room_redacted(room_payload, viewer):
    game = room_payload.get("game")
    toks = room_payload.get("reconnect_tokens", {})
    assert set(toks) <= {viewer}, "reconnect token leaked to another seat"
    if not game:
        return
    assert "rng_state" not in game and "seed" not in game
    assert "undo_stack" not in game, "the undo snapshots (every hidden zone!) on the wire"
    assert "pending" not in game, "raw pending stack (frame data!) on the wire"
    pv = game.get("pending_view")
    if pv is not None:
        assert "data" not in pv
        if game.get("pending_pid") == viewer:
            assert "constraint" in pv
        else:
            assert "constraint" not in pv and pv.get("waiting_on") == game["pending_pid"]
    over = game.get("over")
    for pid, seat in game.get("seats", {}).items():
        if over:
            continue
        assert "deck" not in seat, "deck order on the wire"
        assert "discard" not in seat and "aside" not in seat
        assert isinstance(seat.get("discard_view"), dict)
        assert set(seat["discard_view"]) == {"top", "count"}
        if pid != viewer:
            assert "hand" not in seat, f"{pid}'s hand leaked to {viewer}"
        else:
            assert isinstance(seat.get("hand"), list)


def test_wire_redaction_through_a_militia_pending():
    sockets = _three_player_room()
    room = m.ROOMS["WIRE"]
    game = room["game"]
    turn = game["turn"]
    others = [p for p in game["players"] if p != turn]
    game["phase"] = "action"
    game["actions"] = 1
    game["seats"][turn]["hand"] = ["Militia", "Copper"]
    for o in others:
        game["seats"][o]["hand"] = ["Copper", "Silver", "Gold", "Estate", "Duchy"]
    _run(m._handle_move(sockets[turn], "WIRE", turn,
                        {"move": {"type": "play_action", "card": "Militia"}}))
    assert game["pending_pid"] == others[0]
    # the pending opponent answers over the wire path too
    hand2 = game["seats"][others[0]]["hand"][:2]
    _run(m._handle_move(sockets[others[0]], "WIRE", others[0],
                        {"move": {"type": "decision", "cards": hand2}}))
    # every payload every socket ever received is redacted for ITS viewer
    for viewer, ws in sockets.items():
        seen = ws.rooms_seen()
        assert seen, f"{viewer} never received a state frame"
        for payload in seen:
            _assert_room_redacted(payload, viewer)
    # the actor saw a constraint at least once; a non-actor saw waiting_on
    actor_frames = [p["game"]["pending_view"] for p in sockets[others[0]].rooms_seen()
                    if p.get("game") and p["game"].get("pending_view")
                    and "constraint" in p["game"]["pending_view"]]
    assert actor_frames and actor_frames[-1]["kind"] == "choose_cards"
    waiting = [p["game"]["pending_view"] for p in sockets[turn].rooms_seen()
               if p.get("game") and p["game"].get("pending_view")
               and "waiting_on" in p["game"]["pending_view"]]
    assert waiting


def test_game_over_reveals_everything():
    sockets = _three_player_room("WIRE2")
    room = m.ROOMS["WIRE2"]
    room["game"]["over"] = True
    room["game"]["scores"] = engine.score_game(room["game"])
    room["game"]["winners"] = [A]
    _run(m.broadcast_state("WIRE2"))
    for viewer, ws in sockets.items():
        last = ws.rooms_seen()[-1]
        for pid, seat in last["game"]["seats"].items():
            assert "hand" in seat and "deck" in seat and "discard" in seat


def test_spectator_view_is_fully_redacted():
    _three_player_room("WIRE3")
    payload = m.mk_room_state("WIRE3", viewer_pid=None)
    _assert_room_redacted(payload, viewer=None)
    for seat in payload["game"]["seats"].values():
        assert "hand" not in seat
