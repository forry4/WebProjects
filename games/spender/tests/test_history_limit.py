"""The lobby History query returns at most `core.rooms.HISTORY_LIMIT` rows.

Spender's `list_user_history` already took a `limit` argument, but its DEFAULT
was 20 and the route never passed one — so 20 was the real cap, and it was the
odd one out among four games that had independently drifted to 20/30/30/30. The
default now binds the shared constant. See the twin in
games/castles_of_crimson/tests for why this is a real sqlite round-trip.
"""
import json
import time

import core.db as coredb
from core import rooms as _rooms
from games.spender import main


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(coredb, "DB_PATH", str(tmp_path / "spender_hist.db"))
    main.init_db()


def _finished_rows(n):
    """n finished games, oldest first — `updated_at` increases with the index."""
    state = json.dumps({
        "players": {"a": "A", "b": "B"},
        "game": {"order": ["a", "b"], "winner": "a",
                 "players": {"a": {"purchased": [], "nobles": []},
                             "b": {"purchased": [], "nobles": []}}},
    })
    now = int(time.time())
    conn = coredb.get_db_conn()
    cur = conn.cursor()
    for i in range(n):
        cur.execute("""INSERT INTO games
                       (id, status, player1_id, player1_name, player2_id, player2_name,
                        host_id, state_json, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (f"H{i:03d}", "over", "a", "A", "b", "B", "a", state, now, now + i))
    conn.commit()
    conn.close()


def test_history_is_capped_at_the_shared_limit_and_newest_first(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    extra = 12
    _finished_rows(_rooms.HISTORY_LIMIT + extra)
    rows = main.list_user_history("a")
    assert len(rows) == _rooms.HISTORY_LIMIT
    assert rows[0]["id"] == f"H{_rooms.HISTORY_LIMIT + extra - 1:03d}"
    assert rows[-1]["id"] == f"H{extra:03d}"


def test_the_route_does_not_pass_its_own_limit(tmp_path, monkeypatch):
    """The argument exists, so the cap is only real if the caller leaves it
    alone — that is exactly how Spender sat at 20 while the constant said
    otherwise. Calling it the way the route does must give the shared cap."""
    _seed(tmp_path, monkeypatch)
    _finished_rows(_rooms.HISTORY_LIMIT + 5)
    assert len(main.list_user_history("a")) == _rooms.HISTORY_LIMIT


def test_a_short_history_is_returned_whole(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    _finished_rows(3)
    assert len(main.list_user_history("a")) == 3
