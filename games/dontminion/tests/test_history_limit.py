"""The lobby History query returns at most `core.rooms.HISTORY_LIMIT` rows.
See the twin in games/castles_of_crimson/tests for why this is a real sqlite
round-trip rather than a source check.
"""
import json
import time

import core.db as coredb
from core import rooms as _rooms
from games.dontminion import main


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(coredb, "DB_PATH", str(tmp_path / "dm_hist.db"))
    conn = coredb.get_db_conn()
    coredb.init_core_schema(conn)
    conn.close()
    main._save_conn = None
    main.dontminion_init_db()


def _finished_rows(n):
    """n finished games, oldest first — `updated_at` increases with the index."""
    state = json.dumps({
        "players": {"a": "A", "b": "B"},
        "game": {"players": ["a", "b"], "winners": ["a"],
                 "scores": {"a": {"vp": 30}, "b": {"vp": 10}}},
    })
    now = int(time.time())
    conn = coredb.get_db_conn()
    cur = conn.cursor()
    for i in range(n):
        cur.execute("""INSERT INTO dontminion_games
                       (id, status, player1_id, player1_name, player2_id, player2_name,
                        host_id, state_json, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (f"H{i:03d}", "over", "a", "A", "b", "B", "a", state, now, now + i))
    conn.commit()
    conn.close()


def test_history_is_capped_at_the_shared_limit_and_newest_first(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    try:
        extra = 12
        _finished_rows(_rooms.HISTORY_LIMIT + extra)
        rows = main.list_user_history("a")
        assert len(rows) == _rooms.HISTORY_LIMIT
        assert rows[0]["id"] == f"H{_rooms.HISTORY_LIMIT + extra - 1:03d}"
        assert rows[-1]["id"] == f"H{extra:03d}"
    finally:
        main._save_conn = None


def test_a_short_history_is_returned_whole(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    try:
        _finished_rows(3)
        assert len(main.list_user_history("a")) == 3
    finally:
        main._save_conn = None
