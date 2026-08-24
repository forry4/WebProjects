"""The finished-game review endpoint must be restricted to a PARTICIPANT and to
FINISHED games — an anonymous id-guess can't read another table's revealed board,
and an in-progress game's hidden state is never exposed here. Drives games_review
directly (no server), mirroring CoC's test_review_auth. player_view / is_over are
stubbed so only the GATE is under test (the real view is covered by test_view_wire)."""
import asyncio

import pytest

from games.dontminion import main as m


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    m.ROOMS.clear()
    monkeypatch.setattr(m, "load_game_state", lambda gid: None)
    monkeypatch.setattr(m, "get_user_by_session", lambda tok: None)
    # Only the gate is under test here; keep the view + over-check off the engine.
    monkeypatch.setattr(m.engine, "player_view", lambda g, viewer: {"viewer": viewer})
    monkeypatch.setattr(m.engine, "is_over", lambda g: bool(g.get("over")))


def _over_game_in_memory(rid="DMREV", over=True):
    m.ROOMS[rid] = {
        "players": {"alice": "Alice", "bob": "Bob"},
        "game": {"players": ["alice", "bob"], "over": over, "winners": ["alice"]},
        "status": "over",
    }
    return rid


def _call(rid, token=None, player_id=None):
    return asyncio.new_event_loop().run_until_complete(
        m.games_review(rid, token=token, player_id=player_id))


def test_member_by_player_id_can_review():
    rid = _over_game_in_memory()
    out = _call(rid, player_id="alice")
    assert out["ok"] is True
    assert out["winners"] == ["alice"]
    assert out["players"] == {"alice": "Alice", "bob": "Bob"}
    assert out["game"] == {"viewer": "alice"}   # went through player_view as the requester


def test_non_member_is_rejected():
    rid = _over_game_in_memory()
    out = _call(rid, player_id="mallory")
    assert out["ok"] is False and out["message"] == "not your game"


def test_anonymous_no_identity_is_rejected():
    rid = _over_game_in_memory()
    out = _call(rid)
    assert out["ok"] is False and out["message"] == "not your game"


def test_unfinished_game_is_not_exposed():
    rid = _over_game_in_memory(over=False)
    out = _call(rid, player_id="alice")
    assert out["ok"] is False and out["message"] == "game not finished"


def test_missing_game_is_not_found():
    out = _call("NOPE", player_id="alice")
    assert out["ok"] is False and out["message"] == "not found"


def test_logged_in_member_via_session(monkeypatch):
    monkeypatch.setattr(m, "get_user_by_session",
                        lambda tok: {"id": "bob"} if tok == "s" else None)
    rid = _over_game_in_memory()
    out = _call(rid, token="s")
    assert out["ok"] is True
    assert out["game"] == {"viewer": "bob"}   # the session identity is the viewer


def test_review_reads_a_finished_game_from_the_db(monkeypatch):
    # No room in memory → the endpoint loads + migrates the saved blob. migrate is
    # stubbed to a pass-through so the gate (participant + over) is still what's tested.
    monkeypatch.setattr(m, "load_game_state", lambda gid: {
        "players": {"alice": "Alice", "bob": "Bob"},
        "game": {"players": ["alice", "bob"], "over": True, "winners": ["bob"]},
    })
    monkeypatch.setattr(m.engine, "migrate", lambda g: g)
    out = _call("DBGAME", player_id="bob")
    assert out["ok"] is True and out["winners"] == ["bob"]
