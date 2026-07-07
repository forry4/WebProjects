"""The finished-game review endpoint must be restricted to a PARTICIPANT — an anonymous
id-guess can't read another table's board. Drives games_review directly (no server)."""
import asyncio

import pytest

from games.castles_of_crimson import main as m


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    m.ROOMS.clear()
    monkeypatch.setattr(m, "load_game_state", lambda gid: None)
    monkeypatch.setattr(m, "get_user_by_session", lambda tok: None)


def _over_game_in_memory(rid="COCREV"):
    m.ROOMS[rid] = {
        "players": {"alice": "Alice", "bob": "Bob"},
        "game": {"players": {"alice": {}, "bob": {}}, "phase": "over", "winner": "alice"},
        "status": "over",
    }
    return rid


def _call(rid, token=None, player_id=None):
    return asyncio.new_event_loop().run_until_complete(
        m.games_review(rid, token=token, player_id=player_id))


def test_member_by_player_id_can_review(monkeypatch):
    # final_scores/vp_breakdown touch the engine; stub them so we only test the gate.
    monkeypatch.setattr(m.engine, "final_scores", lambda g: {})
    monkeypatch.setattr(m.engine, "vp_breakdown", lambda g, pid: [])
    rid = _over_game_in_memory()
    out = _call(rid, player_id="alice")
    assert out["ok"] is True


def test_non_member_is_rejected():
    rid = _over_game_in_memory()
    out = _call(rid, player_id="mallory")
    assert out["ok"] is False and out["message"] == "not your game"


def test_anonymous_no_identity_is_rejected():
    rid = _over_game_in_memory()
    out = _call(rid)
    assert out["ok"] is False


def test_logged_in_member_via_session(monkeypatch):
    monkeypatch.setattr(m, "get_user_by_session", lambda tok: {"id": "bob"} if tok == "s" else None)
    monkeypatch.setattr(m.engine, "final_scores", lambda g: {})
    monkeypatch.setattr(m.engine, "vp_breakdown", lambda g, pid: [])
    rid = _over_game_in_memory()
    out = _call(rid, token="s")
    assert out["ok"] is True
