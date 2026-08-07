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
from games.dissonance import engine as E
from games.dissonance import main as m


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

    assert g["result"] is not None
    if g["trick"] == E.NTRICKS:
        assert sum(g["pts"]) == E.POOL
    else:
        # A round stops the moment the score can no longer change, so a room
        # can legitimately reach a result before the thirteenth trick.
        assert g["result"]["ended_early"] and g["result"]["made"]
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
    # This room is dealt from an UNSEEDED rng, so the pool invariant has to be
    # stated the way the engine means it: over a round that ran to thirteen.
    if room["game"]["trick"] == E.NTRICKS:
        assert sum(room["game"]["pts"]) == E.POOL
    else:
        assert room["game"]["result"]["ended_early"]


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


def _drive(g, pick_auction):
    """One move for whichever phase a room is in, in either mode."""
    pid = E.turn_pid(g)
    seat = E.seat_of(g, pid)
    phase = g["phase"]
    if phase == "auction":
        return pid, pick_auction(g)
    if phase == "swap":
        return pid, {"kind": "swap", "take": None}
    if phase == "talon":
        return pid, {"kind": "hand"}
    if phase == "declare":
        d = E.declare_options(g)["denoms"][0]
        return pid, {"kind": "declare", "denom": d["denom"],
                     "level": d["min_level"], "sharp": True}
    if phase == "kontra":
        return pid, {"kind": "kontra", "on": True}
    if phase == "re":
        return pid, {"kind": "re", "on": True}
    return pid, {"kind": "play", "card": E.legal_moves(g, seat)[0]}


def _skat_auction_move(g):
    vals = E.auction_options(g)["values"]
    # Bid low enough that the auction settles instead of climbing to the top of
    # the ladder, but never pass out of a hand nobody has bid on.
    return ({"kind": "bid", "value": vals[0]} if vals and vals[0] <= 12
            else {"kind": "pass"})


def test_a_skat_room_plays_from_create_to_a_scored_result():
    """The mode is a room FLAG, not a second game: same table, same route, same
    handlers. If any of that were wrong the room would stall in a phase no
    handler advances."""
    wa, wb = _FakeWS(), _FakeWS()
    assert run(m._handle_create(wa, "K", "alice",
                                {"name": "Alice", "mode": "skat"})) is True
    assert run(m._handle_join(wb, "K", "bob", {"name": "Bob"})) is True
    run(m._handle_start(wa, "K", "alice"))

    room = m.ROOMS["K"]
    g = room["game"]
    assert room["mode"] == "skat" and g["mode"] == "skat"

    guard = 0
    while g["phase"] != "over":
        guard += 1
        assert guard < 300, f"the room stalled in {g['phase']}"
        pid, move = _drive(g, _skat_auction_move)
        run(m._handle_move(wa if pid == "alice" else wb, "K", pid, {"move": move}))

    # A round stops the moment the score can no longer change, so the pool
    # invariant holds only over a COMPLETED round.
    if g["trick"] == E.NTRICKS:
        assert sum(g["pts"]) == E.POOL
    else:
        assert g["result"]["ended_early"]
    res = g["result"]
    assert res["mode"] == "skat" and res["value"] > 0
    winner = res["declarer"] if (res["made"] or res["null"]) else 1 - res["declarer"]
    assert res["scores"][winner] > 0
    assert room["status"] == "over"
    assert "error" not in wa.types() and "error" not in wb.types()


def test_a_vs_bot_skat_room_is_creatable_and_the_bot_takes_every_phase(monkeypatch):
    """The bot has to answer four NEW prompts (talon, declaration, Kontra, Re),
    and a bot that stalls on any of them leaves the human with no way forward."""
    monkeypatch.setattr(m, "BOT_FLOOR_SECONDS", 0.0)
    ws = _FakeWS()
    assert run(m._handle_create(ws, "KB", "alice",
                                {"name": "Alice", "vs_ai": True,
                                 "ai_difficulty": "normal", "mode": "skat"})) is True
    room = m.ROOMS["KB"]
    assert room["game"]["mode"] == "skat"

    guard = 0
    while room["game"]["phase"] != "over":
        guard += 1
        assert guard < 400, f"stalled in {room['game']['phase']}"
        g = room["game"]
        if E.turn_pid(g) == m.AI_PID:
            run(m._schedule_bot_turn("KB"))
            continue
        pid, move = _drive(g, _skat_auction_move)
        run(m._handle_move(ws, "KB", pid, {"move": move}))

    assert room["game"]["result"] is not None
    # Unseeded deal, so the pool invariant is stated the way the engine means
    # it: over a round that ran to thirteen tricks.
    if room["game"]["trick"] == E.NTRICKS:
        assert sum(room["game"]["pts"]) == E.POOL
    else:
        assert room["game"]["result"]["ended_early"]
    assert "error" not in ws.types(), "the bot never produced an illegal move"


def test_abandoning_a_skat_room_scores_it_in_skat_currency():
    """Reachable in skat mode with NOTHING agreed — both players may pass, so
    the room can be walked out of with no declarer at all."""
    wa, wb = _FakeWS(), _FakeWS()
    run(m._handle_create(wa, "A1", "alice", {"name": "Alice", "mode": "skat"}))
    run(m._handle_join(wb, "A1", "bob", {"name": "Bob"}))
    run(m._handle_start(wa, "A1", "alice"))
    g = m.ROOMS["A1"]["game"]
    assert g["auction"]["declarer"] == -1

    run(m._handle_abandon(wa, "A1", "alice"))
    res = m.ROOMS["A1"]["game"]["result"]
    assert res["mode"] == "skat" and res["abandoned_by"] == E.seat_of(g, "alice")
    # Whoever stayed is paid, and named by a seat index that really exists.
    assert res["scores"][1 - res["abandoned_by"]] > 0
    assert res["scores"][res["abandoned_by"]] == 0
    assert m.ROOMS["A1"]["status"] == "over"
    assert "error" not in wa.types() and "error" not in wb.types()


def test_a_room_created_without_a_mode_is_still_the_classic_auction():
    ws = _FakeWS()
    run(m._handle_create(ws, "C", "alice", {"name": "Alice", "vs_ai": True}))
    room = m.ROOMS["C"]
    assert room["mode"] == "classic"
    assert room["game"]["mode"] == "classic"
    assert "contract" not in room["game"]
    # ...and a nonsense mode falls back rather than dealing something undefined.
    run(m._handle_create(_FakeWS(), "C2", "alice", {"name": "A", "mode": "chess"}))
    assert m.ROOMS["C2"]["mode"] == "classic"


def test_the_catalog_matches_the_engine():
    """The client renders trick values from /catalog; if the two ever disagree
    the board would lie about what a trick is worth."""
    cat = run(m.catalog())
    assert cat["trick_values"] == [E.trick_value(t) for t in range(E.NTRICKS)]
    assert cat["pool"] == E.POOL
    assert sum(cat["trick_values"]) == cat["pool"]
    assert cat["max_raise"] == E.MAX_RAISE
    assert cat["short_penalty"] == E.SHORT_PENALTY
    # Skat mode's price table is served, never copied into the client — the
    # bases and the ladder they generate must agree.
    assert cat["modes"] == list(E.MODES)
    assert cat["skat_bases"] == list(E.SKAT_BASE)
    assert cat["skat_values"] == list(E.SKAT_VALUES)
    assert set(cat["skat_values"]) == (
        {b * lvl for b in cat["skat_bases"]
         for lvl in range(cat["min_level"], cat["max_level"] + 1)}
        | {cat["skat_null_value"]})
