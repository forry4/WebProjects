"""The lobby History query returns at most `core.rooms.HISTORY_LIMIT` rows.

The four games each own their own copy of `list_user_history` and had drifted to
20/30/30/30 independently; they now all bind the shared constant. Worth a real
sqlite round-trip rather than a source check, because the change that introduced
it also changed the PARAMETER TUPLE — `(user_id,) * 4 + (limit,)` — and getting
the arity wrong is a runtime binding error the query planner alone can't catch.
"""
import json
import time

import core.db as coredb
from core import rooms as _rooms
from games.castles_of_crimson import main, engine


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(coredb, "DB_PATH", str(tmp_path / "coc_hist.db"))
    conn = coredb.get_db_conn()
    coredb.init_core_schema(conn)
    conn.close()
    main._save_conn = None
    main.coc_init_db()


def _finished_rows(n, pids=("a", "b")):
    """n finished games, oldest first — `updated_at` increases with the index,
    so the newest is the LAST one written."""
    g = engine.new_game(list(pids), names={p: p.upper() for p in pids}, seed=1)
    g["phase"] = "over"
    g["winner"] = pids[0]
    state = json.dumps({"players": {p: p.upper() for p in pids}, "host": pids[0],
                        "status": "over", "game": g})
    now = int(time.time())
    conn = coredb.get_db_conn()
    cur = conn.cursor()
    for i in range(n):
        cur.execute("""INSERT INTO coc_games
                       (id, status, player1_id, player1_name, player2_id, player2_name,
                        host_id, state_json, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (f"H{i:03d}", "over", pids[0], "A", pids[1], "B", pids[0],
                     state, now, now + i))
    conn.commit()
    conn.close()


def test_history_is_capped_at_the_shared_limit_and_newest_first(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    try:
        extra = 12
        _finished_rows(_rooms.HISTORY_LIMIT + extra)
        rows = main.list_user_history("a")
        assert len(rows) == _rooms.HISTORY_LIMIT
        # the cap must drop the OLDEST games, not an arbitrary window
        assert rows[0]["id"] == f"H{_rooms.HISTORY_LIMIT + extra - 1:03d}"
        assert rows[-1]["id"] == f"H{extra:03d}"
    finally:
        main._save_conn = None


def test_a_short_history_is_returned_whole(tmp_path, monkeypatch):
    """Non-vacuity: the cap must be a ceiling, not a fixed page size."""
    _seed(tmp_path, monkeypatch)
    try:
        _finished_rows(3)
        assert len(main.list_user_history("a")) == 3
    finally:
        main._save_conn = None
