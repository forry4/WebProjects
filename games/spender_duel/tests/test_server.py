"""Server-layer tests for Spender Duel main.py: room lifecycle, per-recipient
redaction on the wire, the bot scheduler finishing games, and reconnects.

Drives the WS handlers directly (no real websocket), DB stubbed out — never
touches users.db (the CoC test_client_ai.py pattern).
"""
import asyncio
import json
import random

from games.spender_duel import engine
from games.spender_duel import main as m


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, t):
        self.sent.append(t)

    def last(self, mtype=None):
        for raw in reversed(self.sent):
            msg = json.loads(raw)
            if mtype is None or msg.get("type") == mtype:
                return msg
        return None


def _isolate(monkeypatch, rid):
    m.ROOMS.pop(rid, None)
    monkeypatch.setattr(m, "save_game", lambda room_id: None)
    monkeypatch.setattr(m, "load_game_state", lambda room_id: None)
    monkeypatch.setattr(m, "load_game_to_memory", lambda room_id: False)
    monkeypatch.setattr(m, "_BOT_MOVE_DELAY", 0.001)


def test_vs_ai_full_game_and_wire_redaction(monkeypatch):
    rid, pid = "DUEL01", "human1"
    _isolate(monkeypatch, rid)

    async def run():
        ws = _FakeWS()
        await m._handle_create(ws, rid, pid, {"name": "H", "vs_ai": True})
        created = ws.last("created")
        assert created and created["room"]["status"] == "playing"
        g_wire = created["room"]["game"]
        # the wire never carries hidden info
        assert "bag" not in g_wire and "decks" not in g_wire and "rng_state" not in g_wire
        assert isinstance(g_wire["bag_count"], int) and set(g_wire["deck_counts"]) == {"1", "2", "3"}

        room = m.ROOMS[rid]
        rng = random.Random(3)
        for _ in range(6000):
            await asyncio.sleep(0.002)
            g = room.get("game")
            if g is None or engine.is_over(g):
                break
            actor = g.get("pending_pid") or g.get("turn")
            if actor == pid and not room.get("_bot_running"):
                mv = rng.choice(engine.legal_moves(g, pid))
                await m._handle_move(ws, rid, pid, {"move": mv})
        g = room["game"]
        assert engine.is_over(g), "game did not finish"
        assert g["winner"] in (pid, m.AI_PID)
        # every room_update sent to the human redacted the bot's reserves pre-over
        for raw in ws.sent:
            msg = json.loads(raw)
            gm = (msg.get("room") or {}).get("game")
            if not gm or gm.get("phase") == "over":
                continue
            for opid, p in gm["players"].items():
                if opid != pid:
                    assert all(isinstance(x, dict) and "id" not in x for x in p["reserved"])
            assert "bag" not in gm and "decks" not in gm

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


def test_join_capped_at_two_and_reconnect(monkeypatch):
    rid = "DUEL02"
    _isolate(monkeypatch, rid)

    async def run():
        ws1, ws2, ws3 = _FakeWS(), _FakeWS(), _FakeWS()
        await m._handle_create(ws1, rid, "p1", {"name": "One", "vs_ai": False})
        await m._handle_join(ws2, rid, "p2", {"name": "Two"})
        assert ws2.last("joined")
        await m._handle_join(ws3, rid, "p3", {"name": "Three"})
        assert ws3.last("error")["message"] == "room is full"

        await m._handle_start(ws1, rid, "p1")
        room = m.ROOMS[rid]
        assert room["status"] == "playing"
        g = room["game"]
        assert set(g["order"]) == {"p1", "p2"}
        # each socket got ITS OWN redacted view + only its own reconnect token
        for pid, ws in (("p1", ws1), ("p2", ws2)):
            upd = ws.last("room_update")
            toks = upd["room"]["reconnect_tokens"]
            assert set(toks) <= {pid}
        # reconnect with the room token
        tok = room["meta"]["p2"]["token"]
        ws2b = _FakeWS()
        await m._handle_reconnect(ws2b, rid, "p2", {"token": tok})
        assert ws2b.last("reconnected")
        ws2c = _FakeWS()
        await m._handle_reconnect(ws2c, rid, "p2", {"token": "WRONG"})
        assert ws2c.last("error")["message"] == "invalid token"

    asyncio.run(run())
    m.ROOMS.pop(rid, None)


def test_abandon_ends_game(monkeypatch):
    rid = "DUEL03"
    _isolate(monkeypatch, rid)

    async def run():
        ws = _FakeWS()
        await m._handle_create(ws, rid, "p1", {"name": "One", "vs_ai": True})
        await m._handle_abandon(ws, rid, "p1")
        room = m.ROOMS[rid]
        assert room["status"] == "over"
        assert room["game"]["winner"] == m.AI_PID

    asyncio.run(run())
    m.ROOMS.pop(rid, None)
