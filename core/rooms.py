"""Shared room-server primitives.

Every game's ``main.py`` reimplements the same scaffolding around an in-memory
``ROOMS`` dict. Most of that is genuinely game-specific (persistence columns,
broadcast redaction, bot scheduling), but a handful of pieces were BYTE-IDENTICAL
across all four games, and one of them encodes a footgun that has already cost a
production outage. Those live here.

WHY THIS MATTERS more than tidiness: a cross-cutting fix currently has to be
applied four times by hand, with no compiler help, and history shows that is not
what happens. The hidden-info broadcast leak had to be found and fixed three
separate times because three copies of ``mk_room_state`` each leaked differently,
and the WebSocket identity binding shipped in Where Wolf? months before the other
three games got it. One definition, four callers, is the point.

This module sits in ``core/`` and therefore imports NO game (the layering rule:
core -> features -> app). It knows about sockets and rooms in the abstract; it
does not know what a game is.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from core.auth import gen_token
from core.db import get_db_conn

# The room dict shape every game shares:
#   {"players": {pid: name}, "sockets": {pid: ws}, "status": "open"|"playing"|"over",
#    "host": pid, "game": {...}|None, "meta": {pid: {"token": str, ...}}}
Room = dict[str, Any]
Rooms = dict[str, Room]


def normalize_room(rid: str) -> str:
    """Room codes are case-insensitive; the upper form is canonical (it is the dict
    key, the DB id, and the URL segment)."""
    return (rid or "").upper()


def gen_room_token(n: int = 12) -> str:
    """Per-seat reconnect token. Delegates to core.auth.gen_token, which is CSPRNG
    backed (`secrets`, never `random`) — these are credentials."""
    return gen_token(n)


def db_conn():
    """The shared dual sqlite/Turso connection. Not pooled: callers close it."""
    return get_db_conn()


def ensure_room_loaded(rooms: Rooms, room_id: str,
                       loader: Callable[[str], Any]) -> Room | None:
    """Return the live room, hydrating it from the DB on first touch.

    `loader` is the game's `load_game_to_memory`, which inserts into `rooms` as a
    side effect — hence the re-read rather than using its return value.
    """
    if room_id not in rooms:
        loader(room_id)
    return rooms.get(room_id)


async def send_json(ws, payload: dict) -> None:
    await ws.send_text(json.dumps(payload))


def delete_open_game(table: str, host_col: str, game_id: str, user_id: str) -> bool:
    """Delete an OPEN game the user hosts (the lobby 'cancel'). True if a row went.

    SELECT-then-DELETE, never ``cursor.rowcount``. The driver-agnostic core.db
    wrapper does not expose rowcount, and on the prod Turso/libsql backend reading
    it RAISED — which 500'd the cancel endpoint in production. Every affected-row
    count in this codebase must be an existence SELECT for the same reason.

    `table` and `host_col` are interpolated into SQL, so they must be trusted
    literals from the calling module — never user input. Asserted below.
    """
    assert table.isidentifier() and host_col.isidentifier(), \
        "table/host_col are SQL identifiers, not user input"
    conn = db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"SELECT 1 FROM {table} WHERE id=? AND {host_col}=? AND status='open'",
            (game_id, user_id))
        existed = cur.fetchone() is not None
        if existed:
            conn.execute(
                f"DELETE FROM {table} WHERE id=? AND {host_col}=? AND status='open'",
                (game_id, user_id))
            conn.commit()
        return existed
    finally:
        conn.close()


def release_socket(rooms: Rooms, room_id: str, pid: str, websocket,
                   *, disarm_client_ai: bool = False,
                   drop_empty_open_only: bool = True) -> bool:
    """The WebSocket `finally` cleanup. Returns True if the room was dropped.

    THE STALE-SOCKET GUARD IS LOAD-BEARING: only act if `websocket` is the exact
    object still registered for `pid`. During a reconnect race (WS1 dropping while
    WS2 is already live) the departing handler would otherwise remove the NEW
    socket and delete a room that is actively being played.

    Flags capture the deliberate per-game differences:
      - `disarm_client_ai`: clear the room's client-AI opt-in when the tab goes, so
        the bot's next decision takes the server path instead of waiting out the
        per-decision watchdog. A reconnecting client re-arms itself.
      - `drop_empty_open_only`: keep playing/over games resident when the last
        socket leaves (they are resumable); drop only never-started open lobbies.
        Spender passes False — it drops any empty room.
    """
    room = rooms.get(room_id)
    if not room or room.get("sockets", {}).get(pid) is not websocket:
        return False
    room["sockets"].pop(pid, None)
    if disarm_client_ai:
        room["client_ai"] = False
    if room["sockets"]:
        return False
    if drop_empty_open_only and not (room.get("status") == "open" and room.get("game") is None):
        return False
    rooms.pop(room_id, None)
    return True
