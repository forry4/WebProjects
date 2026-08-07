"""The Oddtrick -> Dissonance table rename must ADOPT the old rows, not orphan them.

`dissonance_init_db` runs at import time against whatever database the process
is pointed at, and its `CREATE TABLE IF NOT EXISTS` would happily mint an empty
`dissonance_games` beside a populated `oddtrick_games` — every saved game still
on disk, none of them reachable, and nothing anywhere would raise. That failure
is invisible to every other test in this package, because they all start from a
database that never had the old table in it.

These drive the real function against a temp sqlite file, since the guard is a
`sqlite_master` query and a hand-rolled mock of that would only be testing the
mock. The libsql path cannot be exercised locally (no wheel here) — same
standing caveat as the rest of the DB layer.
"""

from __future__ import annotations

import sqlite3

import pytest

from core import db as core_db
from games.dissonance import main as m


COLUMNS = ("id TEXT PRIMARY KEY, status TEXT, player1_id TEXT, player1_name TEXT, "
           "player2_id TEXT, player2_name TEXT, host_id TEXT, state_json TEXT, "
           "created_at INTEGER, updated_at INTEGER")


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point `core.db` at an empty temp file and hand back its path."""
    path = tmp_path / "site.db"
    monkeypatch.setattr(core_db, "DB_PATH", str(path))
    monkeypatch.setattr(core_db, "TURSO_URL", None)
    return path


def _tables(path) -> set[str]:
    con = sqlite3.connect(path)
    try:
        return {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def _seed(path, table, *ids):
    con = sqlite3.connect(path)
    try:
        con.execute(f"CREATE TABLE {table} ({COLUMNS})")
        for i in ids:
            con.execute(f"INSERT INTO {table} (id, status) VALUES (?, 'playing')", (i,))
        con.commit()
    finally:
        con.close()


def test_an_oddtrick_era_table_is_adopted_with_its_rows(db):
    _seed(db, m.LEGACY_TABLE, "ABC123", "XYZ789")

    m.dissonance_init_db()

    assert m.TABLE in _tables(db), "the renamed table is missing"
    assert m.LEGACY_TABLE not in _tables(db), \
        "the old table survived, so the rename copied rather than moved them"
    con = sqlite3.connect(db)
    try:
        rows = {r[0] for r in con.execute(f"SELECT id FROM {m.TABLE}")}
    finally:
        con.close()
    assert rows == {"ABC123", "XYZ789"}, "saved games were lost in the rename"


def test_a_fresh_install_just_creates_the_new_table(db):
    m.dissonance_init_db()

    assert m.TABLE in _tables(db)
    assert m.LEGACY_TABLE not in _tables(db), \
        "a fresh install must not conjure the legacy table"


def test_it_is_idempotent(db):
    """It runs at every import, so a second pass must be a no-op — not a second
    rename attempt against a table that is no longer there."""
    _seed(db, m.LEGACY_TABLE, "ABC123")

    m.dissonance_init_db()
    m.dissonance_init_db()

    con = sqlite3.connect(db)
    try:
        assert [r[0] for r in con.execute(f"SELECT id FROM {m.TABLE}")] == ["ABC123"]
    finally:
        con.close()


def test_a_real_new_table_is_never_clobbered_by_a_leftover_old_one(db):
    """Both present means the rename already happened and something re-made the
    old name. Renaming then would either error or destroy live rows, so the
    guard requires the new table to be ABSENT — this is what pins that."""
    _seed(db, m.LEGACY_TABLE, "OLD001")
    _seed(db, m.TABLE, "NEW001")

    m.dissonance_init_db()

    con = sqlite3.connect(db)
    try:
        assert [r[0] for r in con.execute(f"SELECT id FROM {m.TABLE}")] == ["NEW001"], \
            "the live table was overwritten by the stale one"
    finally:
        con.close()
    assert m.LEGACY_TABLE in _tables(db), "the stale table should be left alone, not dropped"
