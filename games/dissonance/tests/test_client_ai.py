"""The Hard tier's client-AI protocol (main.py).

Hard searches its CARD PLAY in the player's browser — an exact double-dummy
solve per sampled deal, which cannot run on Render's free tier. That makes the
BOT'S move arrive over the same WebSocket a human plays on, so every one of
these is really the same question: what stops that channel from being a way to
play the bot's seat badly, or to hang the room?

The answers this pins:

* nothing is trusted — the card is re-validated against ``engine.legal_moves``
  for the BOT's seat, and a refusal is treated exactly like silence;
* a stale answer (one to a decision that has been superseded) is dropped, which
  is why the armed decision carries a monotonic counter rather than a ply;
* degradation is per-DECISION — an unarmed client, a timeout, a bad card and a
  disarmed socket all fall through to the server's own bot, so a room can never
  stall waiting on a browser;
* the request is only ever armed on a vs-AI room, because it carries the bot's
  own view (its hand) and a human opponent must never receive it.

Drives the handlers directly with a fake websocket, like ``test_ws_auth.py``.
"""

import asyncio
import json
import random

import pytest

from core import rooms as _rooms
from games.dissonance import engine as E
from games.dissonance import main as m


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, t):
        self.sent.append(t)

    def msgs(self):
        return [json.loads(t) for t in self.sent]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    # Process-global WS throttle keyed on client IP; every fake socket reports
    # "unknown", so without this reset the suite eventually throttles itself.
    _rooms._ws_connect_limiter = _rooms.SlidingWindowLimiter(
        _rooms.WS_CONNECTS_PER_MIN, 60)
    monkeypatch.setattr(m, "save_game", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "_ensure_room_loaded", lambda rid: m.ROOMS.get(rid))
    yield
    loop.close()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _playing_room(difficulty="hard", mode="classic", seed=5):
    """A vs-AI room driven to trick play, with the bot on the lead."""
    g = E.new_game(["alice", m.AI_PID], random.Random(seed), opener=0, mode=mode)
    from games.dissonance import bot as B
    rng = random.Random(seed)
    for _ in range(80):
        if g["phase"] in ("play", "over"):
            break
        seat = E.turn_seat(g)
        kind, mv = B.act(g, seat, rng)
        pid = g["seats"][seat]
        if kind == "bid":
            E.apply_move(g, pid, {"kind": "pass"} if mv.get("pass") else {"kind": "bid", **mv})
        elif kind == "swap":
            E.apply_move(g, pid, {"kind": "swap", **mv})
        elif kind == "play":
            E.apply_move(g, pid, {"kind": "play", "card": mv})
        else:
            E.apply_move(g, pid, mv)
    assert g["phase"] == "play"
    # Make it the bot's move, whichever seat it drew.
    if E.turn_pid(g) != m.AI_PID:
        seat = E.to_play(g)
        E.apply_move(g, g["seats"][seat], {"kind": "play", "card": B.choose_card(g, seat)})
    assert E.turn_pid(g) == m.AI_PID
    room = {
        "players": {"alice": "Alice"},
        "sockets": {},
        "status": "playing",
        "host": "alice",
        "game": g,
        "meta": {"alice": {"token": "tok"}},
        "vs_ai": True,
        "ai_player": m.AI_PID,
        "ai_difficulty": difficulty,
        "mode": mode,
    }
    m.ROOMS["r1"] = room
    return room


def _arm(room):
    """Run the request half of one decision, without waiting for an answer."""
    seat = E.seat_of(room["game"], m.AI_PID)
    task = asyncio.ensure_future(m._ask_the_client("r1", seat))
    # Let `_ask_the_client` reach its wait; the arm happens before it blocks.
    run(asyncio.sleep(0))
    run(asyncio.sleep(0))
    return task


# --- the request -----------------------------------------------------------


def test_arming_ships_the_bots_own_view_and_only_on_a_vs_ai_room():
    room = _playing_room()
    room["client_ai"] = True
    ws = _FakeWS()
    room["sockets"]["alice"] = ws
    task = _arm(room)

    armed = room["_ai_search"]
    seat = E.seat_of(room["game"], m.AI_PID)
    assert armed["seat"] == seat and armed["decision"] == 1
    # The BOT's view, not the human's: its own hand, and the opponent's as a
    # count. This is the whole reason the flag is refused off a vs-AI room.
    assert sorted(armed["view"]["hand"]) == sorted(room["game"]["hands"][seat])
    assert armed["view"]["you"] == seat
    # And it rides ROOM STATE, so every re-broadcast and every reconnect
    # re-ships it rather than the request being a one-shot message.
    state = m.mk_room_state("r1", viewer_pid="alice")
    assert state["ai_search"]["decision"] == 1

    run(m._handle_ai_move(ws, "r1", "alice", {
        "decision": 1, "card": E.legal_moves(room["game"], seat)[0]}))
    assert run(task) is not None


def test_an_unarmed_room_is_never_asked():
    room = _playing_room()
    room["client_ai"] = False
    assert run(m._ask_the_client("r1", E.seat_of(room["game"], m.AI_PID))) is None
    assert room.get("_ai_search") is None
    assert "ai_search" not in m.mk_room_state("r1", viewer_pid="alice")


def test_ready_is_refused_unless_the_room_is_vs_ai_on_a_client_tier():
    for difficulty, vs_ai, want in (("hard", True, True),
                                    ("normal", True, False),
                                    ("easy", True, False),
                                    ("hard", False, False)):
        room = _playing_room(difficulty=difficulty)
        room["vs_ai"] = vs_ai
        run(m._handle_client_ai_ready(_FakeWS(), "r1", "alice", {}))
        assert bool(room.get("client_ai")) is want, (difficulty, vs_ai)


def test_a_stranger_cannot_arm_the_room():
    room = _playing_room()
    run(m._handle_client_ai_ready(_FakeWS(), "r1", "mallory", {}))
    assert not room.get("client_ai")


def test_a_dropped_socket_disarms_the_room():
    """With the tab gone there is nobody to answer, and every later decision
    would burn the whole watchdog before the server took over."""
    room = _playing_room()
    room["client_ai"] = True
    ws = _FakeWS()
    room["sockets"]["alice"] = ws
    _rooms.release_socket(m.ROOMS, "r1", "alice", ws, disarm_client_ai=True)
    assert room["client_ai"] is False


# --- the answer ------------------------------------------------------------


def test_a_legal_card_is_taken():
    room = _playing_room()
    room["client_ai"] = True
    seat = E.seat_of(room["game"], m.AI_PID)
    legal = E.legal_moves(room["game"], seat)
    assert len(legal) > 1, "a forced move would make this test vacuous"
    task = _arm(room)
    run(m._handle_ai_move(_FakeWS(), "r1", "alice", {"decision": 1, "card": legal[-1]}))
    assert run(task) == {"kind": "play", "card": legal[-1]}


def test_a_card_the_engine_refuses_is_treated_exactly_like_silence():
    """The move arrives over the human's socket. Every card is re-validated
    against `legal_moves` for the BOT's seat, so the worst a tampered client can
    do is make its own opponent play the server's heuristic move instead."""
    room = _playing_room()
    room["client_ai"] = True
    seat = E.seat_of(room["game"], m.AI_PID)
    legal = set(E.legal_moves(room["game"], seat))
    illegal = next(c for c in range(E.NCARD) if c not in legal)
    for bad in (illegal, "7♠", None, -1, 999):
        task = _arm(room)
        run(m._handle_ai_move(_FakeWS(), "r1", "alice",
                              {"decision": room["_ai_search"]["decision"], "card": bad}))
        assert run(task) is None, bad


def test_an_answer_to_a_superseded_decision_is_dropped():
    """The staleness key is a monotonic counter, not the ply: every play happens
    to append exactly one history entry today, but nothing ENFORCES that, and
    two decisions sharing a key make a late reply indistinguishable."""
    room = _playing_room()
    room["client_ai"] = True
    seat = E.seat_of(room["game"], m.AI_PID)
    legal = E.legal_moves(room["game"], seat)
    first = _arm(room)
    assert room["_ai_search"]["decision"] == 1
    # Answering decision 1 correctly, then re-arming, gives decision 2.
    run(m._handle_ai_move(_FakeWS(), "r1", "alice", {"decision": 1, "card": legal[0]}))
    assert run(first) is not None
    second = _arm(room)
    assert room["_ai_search"]["decision"] == 2
    run(m._handle_ai_move(_FakeWS(), "r1", "alice", {"decision": 1, "card": legal[0]}))
    # The stale reply did not release the waiter; a fresh one still does.
    run(m._handle_ai_move(_FakeWS(), "r1", "alice", {"decision": 2, "card": legal[0]}))
    assert run(second) is not None


def test_an_answer_that_arrives_after_the_decision_closed_is_harmless():
    room = _playing_room()
    room["client_ai"] = True
    seat = E.seat_of(room["game"], m.AI_PID)
    legal = E.legal_moves(room["game"], seat)
    task = _arm(room)
    run(m._handle_ai_move(_FakeWS(), "r1", "alice", {"decision": 1, "card": legal[0]}))
    run(task)
    assert room["_ai_search"] is None
    run(m._handle_ai_move(_FakeWS(), "r1", "alice", {"decision": 1, "card": legal[0]}))
    assert room.get("_ai_pending_move") is None


def test_the_client_never_answers_and_the_server_finishes_the_turn(monkeypatch):
    """The watchdog is the reason a browser cannot stall a room. Nobody replies,
    the wait times out, and the scheduler plays the decision itself."""
    monkeypatch.setattr(m, "CLIENT_AI_TIMEOUT", 0.05)
    monkeypatch.setattr(m, "BOT_FLOOR_SECONDS", 0.0)
    room = _playing_room()
    room["client_ai"] = True
    before = len(room["game"]["history"])
    run(m._schedule_bot_turn("r1"))
    assert len(room["game"]["history"]) > before, "the turn must still advance"
    assert room["_ai_search"] is None


# --- the tier --------------------------------------------------------------


def test_hard_is_offered_and_the_other_tiers_stay_server_side():
    assert "hard" in m.DIFFICULTIES
    assert m.CLIENT_AI_TIERS == ("hard",)
    # Easy and Normal are the shipped ladder; handing a one-trick-deep policy a
    # solver would be a strength change dressed up as a serving one.
    assert set(m.CLIENT_AI_TIERS).isdisjoint({"easy", "normal"})
    assert m._valid_difficulty("hard") == "hard"
    assert m._valid_difficulty("wasm") == m.DEFAULT_DIFFICULTY


def test_every_tier_the_picker_offers_is_one_the_server_accepts():
    """This seam fails SILENTLY: an id that drifts out of `DIFFICULTIES` does not
    error, `_valid_difficulty` quietly coerces it, and the room seats a different
    bot than the player picked. Read as text — the JSX is not importable here."""
    import pathlib
    import re
    jsx = (pathlib.Path(__file__).resolve().parents[1] / "Dissonance.jsx").read_text(encoding="utf-8")
    block = re.search(r"const BOT_TIERS = \[(.*?)\];", jsx, re.S)
    assert block, "BOT_TIERS moved; this test is reading the wrong thing"
    offered = set(re.findall(r'id:\s*"([a-z]+)"', block.group(1)))
    assert offered, "no tiers parsed"
    assert offered <= set(m.DIFFICULTIES), offered - set(m.DIFFICULTIES)
    # And the client-side tier list agrees with the server's, or a Hard room
    # would never load a worker and would silently play at Normal.
    client = set(re.findall(r'const CLIENT_AI_TIERS = \[([^\]]*)\]', jsx))
    assert client, "CLIENT_AI_TIERS moved"
    assert set(re.findall(r'"([a-z]+)"', client.pop())) == set(m.CLIENT_AI_TIERS)
