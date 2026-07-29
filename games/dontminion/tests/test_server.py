"""Room-server tests: option coercers + 4-layer sync, lifecycle, join caps,
the multi-bot scheduler (a full 1-human+3-bot game through the REAL scheduler),
bots answering a human's attack, and the persistence blob round-trip."""

import asyncio
import json
import random

import pytest
from fastapi import WebSocketDisconnect

from core import rooms as _rooms
from games.dontminion import bot, engine
from games.dontminion import main as m

# The real function objects, grabbed at import time — the autouse fixture stubs
# the module attributes, and the persistence tests need the real ones back.
_REAL_LOAD_TO_MEMORY = m.load_game_to_memory


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, t):
        self.sent.append(t)

    async def receive_text(self):
        raise WebSocketDisconnect()

    def msgs(self):
        return [json.loads(t) for t in self.sent]


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
    # Bots run through _schedule_bots called EXPLICITLY in tests; the fire-and-
    # forget kick would leave dangling tasks on the per-test loop.
    monkeypatch.setattr(m, "_kick_bots", lambda room_id: None)
    # Zero the pacing so scheduler tests run in milliseconds. Any NEW pacing
    # constant must be zeroed here too (the Duel test_server rule).
    monkeypatch.setattr(m, "_BOT_MOVE_DELAY", 0.0)
    monkeypatch.setattr(m, "_MIN_BOT_THINK", 0.0)
    monkeypatch.setattr(m, "_new_rng", lambda: random.Random(1234))
    yield
    loop.close()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- option coercers + create ---------------------------------------------------

def test_create_coerces_bad_options():
    ws = _FakeWS()
    assert _run(m._handle_create(ws, "R1", "host", {
        "name": "Host", "expansions": ["romance", 7], "max_players": 99,
        "num_bots": -3, "ai_difficulty": "insane",
    })) is True
    room = m.ROOMS["R1"]
    assert room["expansions"] == ["base", "intrigue"]
    assert room["max_players"] == 4
    assert room["ai_difficulty"] == "normal"
    assert room["status"] == "open" and room["game"] is None


def test_create_vs_ai_starts_immediately_with_bots():
    ws = _FakeWS()
    assert _run(m._handle_create(ws, "R2", "host", {
        "name": "Host", "vs_ai": True, "num_bots": 3,
        "expansions": ["base"], "ai_difficulty": "easy",
    })) is True
    room = m.ROOMS["R2"]
    assert room["status"] == "playing" and room["game"] is not None
    assert room["ai_players"] == ["bot1", "bot2", "bot3"]
    assert room["max_players"] == 4
    assert set(room["game"]["players"]) == {"host", "bot1", "bot2", "bot3"}
    assert all(b not in room.get("meta", {}) for b in room["ai_players"])
    assert room["game"]["expansions"] == ["base"]
    created = [d for d in ws.msgs() if d["type"] == "created"]
    assert created and created[0]["room"]["ai_players"] == ["bot1", "bot2", "bot3"]


def test_friend_lifecycle_and_join_cap():
    _run(m._handle_create(_FakeWS(), "R3", "host", {"name": "Host", "max_players": 2}))
    assert _run(m._handle_join(_FakeWS(), "R3", "p2", {"name": "P2"})) is True
    late = _FakeWS()
    assert _run(m._handle_join(late, "R3", "p3", {"name": "P3"})) is False
    assert late.msgs()[-1]["message"] == "room is full"
    # non-host can't start
    nh = _FakeWS()
    _run(m._handle_start(nh, "R3", "p2"))
    assert nh.msgs()[-1]["message"] == "only the host can start"
    ws = _FakeWS()
    _run(m._handle_start(ws, "R3", "host"))
    room = m.ROOMS["R3"]
    assert room["status"] == "playing"
    assert set(room["game"]["players"]) == {"host", "p2"}
    # already started
    again = _FakeWS()
    _run(m._handle_start(again, "R3", "host"))
    assert again.msgs()[-1]["message"] == "already started"


def test_start_needs_two_players():
    _run(m._handle_create(_FakeWS(), "R4", "host", {"name": "Host"}))
    ws = _FakeWS()
    _run(m._handle_start(ws, "R4", "host"))
    assert "need at least 2" in ws.msgs()[-1]["message"]


# --- the multi-bot scheduler -----------------------------------------------------

def test_full_game_one_human_three_bots_through_the_real_scheduler():
    _run(m._handle_create(_FakeWS(), "R5", "human", {
        "name": "H", "vs_ai": True, "num_bots": 3, "expansions": ["base"]}))
    room = m.ROOMS["R5"]
    ws = _FakeWS()
    room["sockets"]["human"] = ws
    rng = random.Random(7)
    for _ in range(1500):
        game = room["game"]
        if engine.is_over(game):
            break
        actor = game["pending_pid"] or game["turn"]
        if actor == "human":
            mv = bot.choose(game, "human", rng)
            _run(m._handle_move(ws, "R5", "human", {"move": mv}))
        else:
            _run(m._schedule_bots("R5"))
    assert engine.is_over(room["game"])
    assert room["status"] == "over"
    assert room["game"]["winners"]
    assert room.get("_bot_running") is False


def test_bots_answer_a_humans_attack_mid_turn():
    _run(m._handle_create(_FakeWS(), "R6", "human", {
        "name": "H", "vs_ai": True, "num_bots": 2, "expansions": ["base"]}))
    room = m.ROOMS["R6"]
    game = room["game"]
    # force the human on turn with a Militia; fatten the bots' hands
    game["pending"].clear()
    engine._sync_pending(game)
    game["turn"] = "human"
    game["phase"] = "action"
    game["actions"] = 1
    game["seats"]["human"]["hand"] = ["Militia"]
    for b in room["ai_players"]:
        game["seats"][b]["hand"] = ["Copper"] * 5
    ws = _FakeWS()
    room["sockets"]["human"] = ws
    _run(m._handle_move(ws, "R6", "human",
                        {"move": {"type": "play_action", "card": "Militia"}}))
    assert room["game"]["pending_pid"] in room["ai_players"]
    _run(m._schedule_bots("R6"))                       # drains BOTH bots' discards
    assert room["game"]["pending_pid"] is None
    assert room["game"]["turn"] == "human"             # still the human's turn
    for b in room["ai_players"]:
        assert len(room["game"]["seats"][b]["hand"]) == 3


def test_scheduler_noops_when_no_bot_owes_a_move():
    _run(m._handle_create(_FakeWS(), "R7", "host", {"name": "Host"}))
    _run(m._schedule_bots("R7"))                       # open room, no game
    assert m.ROOMS["R7"].get("_bot_running") in (None, False)


# --- persistence blob round-trip ---------------------------------------------------

def test_save_blob_round_trip_restores_options(monkeypatch):
    _run(m._handle_create(_FakeWS(), "R8", "human", {
        "name": "H", "vs_ai": True, "num_bots": 2,
        "expansions": ["intrigue"], "ai_difficulty": "hard"}))
    captured = {}

    def fake_persist(room_id, status, seats, host, state_json, now, created_at):
        captured["state"] = json.loads(state_json)
        captured["seats"] = seats
        captured["status"] = status

    monkeypatch.setattr(m, "_persist_row", fake_persist)

    # save_game submits to the executor — build + persist the blob synchronously
    room = m.ROOMS["R8"]
    players = room["players"]
    seats = [(pid, players[pid]) for pid in players]
    seats += [(None, None)] * (4 - len(seats))
    state = {
        "players": players, "host": room["host"], "status": room["status"],
        "game": room["game"], "meta": room["meta"], "vs_ai": room["vs_ai"],
        "ai_players": room["ai_players"], "ai_difficulty": room["ai_difficulty"],
        "expansions": room["expansions"], "max_players": room["max_players"],
    }
    fake_persist("R8", room["status"], seats[:4], room["host"],
                 json.dumps(state), 0, 0)
    assert captured["seats"][0][0] == "human"          # creator is player1 (host col)
    assert len(captured["seats"]) == 4                 # padded to 4 columns
    assert captured["seats"][3] == (None, None) or captured["seats"][3] == [None, None]

    # wipe + reload through the REAL load_game_to_memory (state read stubbed)
    monkeypatch.setattr(m, "load_game_state", lambda rid: captured["state"])
    monkeypatch.setattr(m, "load_game_to_memory", _REAL_LOAD_TO_MEMORY)
    m.ROOMS.clear()
    assert m.load_game_to_memory("R8") is True
    r2 = m.ROOMS["R8"]
    assert r2["expansions"] == ["intrigue"]
    assert r2["ai_difficulty"] == "hard"
    assert r2["ai_players"] == ["bot1", "bot2"]
    assert r2["max_players"] == 3
    assert r2["sockets"] == {}                         # always reset on load
    assert r2["game"]["expansions"] == ["intrigue"]


def test_load_revalidates_difficulty(monkeypatch):
    blob = {"players": {"h": "H"}, "host": "h", "status": "open", "game": None,
            "meta": {}, "vs_ai": False, "ai_players": [],
            "ai_difficulty": "cheater", "expansions": ["nope"], "max_players": 99}
    monkeypatch.setattr(m, "load_game_state", lambda rid: blob)
    monkeypatch.setattr(m, "load_game_to_memory", _REAL_LOAD_TO_MEMORY)
    assert m.load_game_to_memory("R9") is True
    r = m.ROOMS["R9"]
    assert r["ai_difficulty"] == "normal"
    assert r["expansions"] == ["base", "intrigue"]
    assert r["max_players"] == 4
