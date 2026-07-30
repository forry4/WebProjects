"""FastAPI sub-application for Dontminion.

Exposes ``dontminion_app`` which the composition-root ``app.py`` mounts under
``/dontminion``. WebSocket lives at ``/dontminion/ws/{room}/{player}`` and REST
under ``/dontminion/...``.

Thin layer over the pure ``engine``: rooms, sockets, persistence, WS protocol,
and the bot scheduler. Structural mirror of Spender Duel's main.py (per-recipient
redacted broadcasts via ``engine.player_view``; the single-thread DB write
executor; the stale-socket disconnect guard) with three differences:

* 2-4 players (CoC-shaped table: player1..player4 columns) with create-time
  options — max_players, enabled expansions, bot count, difficulty — validated
  by coercers and kept in sync across create / save blob / load / wire state.
* MULTIPLE bot seats (``room["ai_players"]`` is a list). The scheduler is a
  finisher loop only — every tier is the random-legal bot in v1, so there is no
  executor and never heavy work under ROOM_LOCK. ``_bot_to_act`` recomputes the
  actor each iteration, which is what lets bot B answer during bot A's turn and
  lets bots answer a HUMAN's attack (Militia) mid-human-turn.
* No client-side AI machinery at all.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import random
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware

from . import engine
from . import bot
from . import cards

from core.db import cleanup_stale_games, maybe_cleanup_games
from core.auth import (
    get_user_by_session, validate_reconnect_token, mark_reconnect_token_used,
)
from core.config import cors_allowed_origins
from core import rooms as _rooms
from core.build_info import build_info

LOG = logging.getLogger("games.dontminion")

# The bot pauses this long BEFORE every move (its "think"), so the client reads
# each move as it lands — an instant reply feels robotic, a burst is unreadable.
_BOT_THINK = 0.7


# Every tier is the random-legal bot in v1 (stronger tiers are a later campaign).
# The tier is still validated + persisted so a future strength ladder slots in
# without a migration — and so a redeploy can't silently retier a live game
# (the Spender ai_variant lesson).
AI_DIFFICULTIES = ("easy", "normal", "hard")
DEFAULT_DIFFICULTY = "normal"

AI_PIDS = ("bot1", "bot2", "bot3")


def _valid_difficulty(value) -> str:
    return value if value in AI_DIFFICULTIES else DEFAULT_DIFFICULTY


KNOWN_EXPANSIONS = ("base", "intrigue", "seaside")


def _valid_expansions(value) -> list[str]:
    """Non-empty ordered subset of the known expansions; default = the classic
    pair (Seaside is opt-in at create)."""
    if isinstance(value, (list, tuple)):
        got = [e for e in KNOWN_EXPANSIONS if e in value]
        if got:
            return got
    return ["base", "intrigue"]


def _valid_max_players(value) -> int:
    try:
        return max(2, min(4, int(value)))
    except (TypeError, ValueError):
        return 4


def _valid_num_bots(value) -> int:
    try:
        return max(1, min(3, int(value)))
    except (TypeError, ValueError):
        return 1


def _new_rng() -> random.Random:
    """Test seam: every source of game entropy (seat shuffle, game seed, bot
    move choices) goes through here so tests can pin it."""
    return random.Random()


dontminion_app = FastAPI(title="Dontminion API")
dontminion_app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── In-memory room state ──────────────────────────────────────────────────────
ROOMS: dict[str, dict] = {}
ROOM_LOCK = asyncio.Lock()


# ── Shared room-server primitives (core/rooms.py) ─────────────────────────────
normalize_room = _rooms.normalize_room
_gen_token = _rooms.gen_room_token
_db = _rooms.db_conn
_send = _rooms.send_json


def _ensure_room_loaded(room_id: str) -> dict | None:
    return _rooms.ensure_room_loaded(ROOMS, room_id, load_game_to_memory)


def dontminion_init_db() -> None:
    conn = _db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS dontminion_games (
        id TEXT PRIMARY KEY,
        status TEXT,
        player1_id TEXT, player1_name TEXT,
        player2_id TEXT, player2_name TEXT,
        player3_id TEXT, player3_name TEXT,
        player4_id TEXT, player4_name TEXT,
        host_id TEXT,
        state_json TEXT,
        created_at INTEGER, updated_at INTEGER)""")
    conn.commit()
    conn.close()


dontminion_init_db()
# Retention: same policy as the other games (guest 24h / registered 30d).
cleanup_stale_games("dontminion_games")


# ── Persistence (single-thread write executor with a reused connection) ──────
_DB_WRITE_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="dontminion-db-write")
_save_conn = None  # only ever touched by the _DB_WRITE_EXEC thread


def _persist_row(room_id, status, seats, host, state_json, now, created_at) -> None:
    """seats = [(pid, name)] padded to 4. SELECT-then-INSERT/UPDATE — never
    cursor.rowcount (absent on libsql; it 500'd prod once)."""
    global _save_conn
    try:
        if _save_conn is None:
            _save_conn = _db()
        cur = _save_conn.cursor()
        cur.execute("SELECT id FROM dontminion_games WHERE id=?", (room_id,))
        flat = [x for pair in seats for x in pair]
        if cur.fetchone() is not None:
            cur.execute("""UPDATE dontminion_games SET status=?,
                           player1_id=?, player1_name=?, player2_id=?, player2_name=?,
                           player3_id=?, player3_name=?, player4_id=?, player4_name=?,
                           state_json=?, updated_at=? WHERE id=?""",
                        (status, *flat, state_json, now, room_id))
        else:
            cur.execute("""INSERT INTO dontminion_games
                           (id,status,player1_id,player1_name,player2_id,player2_name,
                            player3_id,player3_name,player4_id,player4_name,
                            host_id,state_json,created_at,updated_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (room_id, status, *flat, host, state_json, created_at, now))
        _save_conn.commit()
    except Exception:  # noqa: BLE001 — a save must never crash; reconnect next time
        LOG.warning("dontminion save_game write failed for %s; dropping connection",
                    room_id, exc_info=True)
        try:
            if _save_conn is not None:
                _save_conn.close()
        except Exception:
            pass
        _save_conn = None


def save_game(room_id: str) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    players = room.get("players", {})
    seats = [(pid, players[pid]) for pid in players]
    seats += [(None, None)] * (4 - len(seats))
    state = {
        "players": players,
        "host": room.get("host"),
        "status": room.get("status", "open"),
        "game": room.get("game"),
        "meta": room.get("meta", {}),
        "vs_ai": room.get("vs_ai", False),
        "ai_players": room.get("ai_players", []),
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
        "expansions": room.get("expansions", ["base", "intrigue"]),
        "max_players": room.get("max_players", 4),
    }
    now = int(time.time())
    _DB_WRITE_EXEC.submit(
        _persist_row, room_id, room.get("status", "open"), seats[:4],
        room.get("host"), json.dumps(state), now, now,
    )


def load_game_state(room_id: str) -> dict | None:
    conn = _db()
    cur = conn.cursor()
    cur.execute("SELECT state_json FROM dontminion_games WHERE id=?", (room_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row["state_json"]:
        return None
    try:
        return json.loads(row["state_json"])
    except Exception:
        return None


def load_game_to_memory(room_id: str) -> bool:
    state = load_game_state(room_id)
    if not state:
        return False
    ROOMS[room_id] = {
        "players": state.get("players", {}),
        "host": state.get("host"),
        "status": state.get("status", "open"),
        "game": state.get("game"),
        "meta": state.get("meta", {}),
        "vs_ai": state.get("vs_ai", False),
        "ai_players": list(state.get("ai_players", [])),
        "ai_difficulty": _valid_difficulty(state.get("ai_difficulty")),
        "expansions": _valid_expansions(state.get("expansions")),
        "max_players": _valid_max_players(state.get("max_players")),
        "sockets": {},
    }
    return True


def list_open_games() -> list[dict]:
    maybe_cleanup_games("dontminion_games", background=True)  # throttled, non-blocking
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, player1_id, player1_name, state_json, created_at
                   FROM dontminion_games
                   WHERE status='open' ORDER BY created_at DESC LIMIT 20""")
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            state = json.loads(r["state_json"] or "{}")
        except Exception:
            state = {}
        out.append({
            "id": r["id"], "host_id": r["player1_id"], "host_name": r["player1_name"],
            "player_count": len(state.get("players", {})) or 1,
            "max_players": _valid_max_players(state.get("max_players")),
            "expansions": _valid_expansions(state.get("expansions")),
            "created_at": r["created_at"],
        })
    return out


def list_user_games(user_id: str) -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, status, player1_id, player1_name, player2_id, player2_name,
                          player3_id, player3_name, player4_id, player4_name,
                          state_json, created_at, updated_at
                   FROM dontminion_games
                   WHERE (player1_id=? OR player2_id=? OR player3_id=? OR player4_id=?)
                         AND status != 'over'
                   ORDER BY updated_at DESC""", (user_id,) * 4)
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            state = json.loads(r["state_json"] or "{}")
        except Exception:
            state = {}
        g = state.get("game") or {}
        players = state.get("players", {})
        others = [n for p, n in players.items() if p != user_id]
        your_turn = isinstance(g, dict) and (g.get("pending_pid") or g.get("turn")) == user_id
        out.append({
            "id": r["id"], "status": r["status"],
            "players": list(players.values()),
            "opponents": others,
            "your_turn": your_turn,
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        })
    return out


def list_user_history(user_id: str) -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute("""SELECT id, state_json, updated_at
                   FROM dontminion_games
                   WHERE (player1_id=? OR player2_id=? OR player3_id=? OR player4_id=?)
                         AND status='over'
                   ORDER BY updated_at DESC LIMIT 30""", (user_id,) * 4)
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            state = json.loads(r["state_json"] or "{}")
        except Exception:
            state = {}
        g = state.get("game") or {}
        players = state.get("players", {})
        if not isinstance(g, dict) or not g.get("players"):
            continue
        scores = g.get("scores") or {}
        out.append({
            "id": r["id"],
            "players": list(players.values()),
            "opponents": [n for p, n in players.items() if p != user_id],
            "your_vp": (scores.get(user_id) or {}).get("vp"),
            "scores": {players.get(p, p): (s or {}).get("vp")
                       for p, s in scores.items()},
            "you_won": user_id in (g.get("winners") or []),
            "winners": [players.get(p, p) for p in (g.get("winners") or [])],
            "updated_at": r["updated_at"],
        })
    return out


def delete_open_game(game_id: str, user_id: str) -> bool:
    """Cancel an open game this user hosts. SELECT-then-DELETE lives in core.rooms."""
    return _rooms.delete_open_game("dontminion_games", "player1_id", game_id, user_id)


# ── Room state / broadcast (PER-RECIPIENT redaction) ─────────────────────────
def mk_room_state(room_id: str, viewer_pid: str | None = None) -> dict[str, Any]:
    """Room snapshot AS SEEN BY viewer_pid: the game passes through
    engine.player_view so hands, deck order, and pending-frame internals never
    reach the wire. reconnect_tokens only ever carry the viewer's own token."""
    room = ROOMS.get(room_id, {})
    g = room.get("game")
    return {
        "room_id": room_id,
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
        "game": engine.player_view(g, viewer_pid) if g else None,
        "vs_ai": room.get("vs_ai", False),
        "ai_players": room.get("ai_players", []),
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
        "expansions": room.get("expansions", ["base", "intrigue"]),
        "max_players": room.get("max_players", 4),
        "reconnect_tokens": (
            {viewer_pid: room.get("meta", {}).get(viewer_pid, {}).get("token")}
            if viewer_pid and room.get("meta", {}).get(viewer_pid) else {}
        ),
    }


async def broadcast_state(room_id: str, mtype: str = "room_update") -> None:
    """Send each connected socket ITS OWN redacted view of the room."""
    room = ROOMS.get(room_id)
    if not room:
        return
    for pid, ws in list(room.get("sockets", {}).items()):
        try:
            await ws.send_text(json.dumps({"type": mtype,
                                           "room": mk_room_state(room_id, viewer_pid=pid)}))
        except Exception:
            pass


def _sync_status_from_game(room: dict) -> None:
    g = room.get("game")
    if g and engine.is_over(g):
        room["status"] = "over"


def _bot_to_act(room: dict) -> str | None:
    """WHICH bot owns the live decision (pending frame or turn), else None."""
    game = room.get("game")
    if not game or engine.is_over(game):
        return None
    actor = game.get("pending_pid") or game.get("turn")
    return actor if actor in (room.get("ai_players") or ()) else None


async def _schedule_bots(room_id: str) -> None:
    """Drain every pending bot decision. Safe to call any time (guards no-op);
    single-flighted per room; recomputes the acting bot EVERY iteration so
    chained decisions across different bots — and bot responses during a
    human's turn — all drain in one pass. Never heavy work under ROOM_LOCK
    (the random bot is O(legal moves))."""
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room or room.get("_bot_running") or _bot_to_act(room) is None:
            return
        room["_bot_running"] = True
    try:
        for _ in range(300):
            await asyncio.sleep(_BOT_THINK)      # think BEFORE each move
            async with ROOM_LOCK:
                room = ROOMS.get(room_id)
                if not room:
                    return
                pid = _bot_to_act(room)
                if pid is None:
                    return
                mv = bot.choose(room["game"], pid, _new_rng())
                ok, err = engine.apply_move(room["game"], pid, mv)
                if not ok:
                    LOG.warning("dontminion: bot move rejected in %s (%s): %s",
                                room_id, pid, err)
                    return
                _sync_status_from_game(room)
                more = _bot_to_act(room) is not None
            await broadcast_state(room_id)
            save_game(room_id)
            if not more:
                return
        LOG.warning("dontminion: bot iteration cap hit in %s", room_id)
    finally:
        async with ROOM_LOCK:
            r = ROOMS.get(room_id)
            if r:
                r["_bot_running"] = False


def _kick_bots(room_id: str) -> None:
    asyncio.create_task(_schedule_bots(room_id))


# ── WebSocket ─────────────────────────────────────────────────────────────────
@dontminion_app.websocket("/ws/{room}/{player}")
async def ws_room_player(websocket: WebSocket, room: str, player: str):
    await websocket.accept()
    room_id = normalize_room(room)
    pid = player
    if await _rooms.reject_if_connecting_too_fast(websocket):
        return
    _msg_throttle = _rooms.MessageThrottle()
    # The `player` path segment is CLIENT-SUPPLIED and NOT trusted. State is
    # per-recipient redacted by viewer_pid, so an unproven socket would be handed
    # that seat's HAND. `authed` flips true only via a handshake that proves seat
    # ownership: create / join-new-seat / join-own-seat with a matching session
    # token / reconnect with the per-seat room token / auth_reconnect.
    authed = False
    try:
        while True:
            raw = await websocket.receive_text()
            if not _msg_throttle.allow():
                await websocket.close(code=1008)
                return
            try:
                msg = json.loads(raw)
            except Exception:
                await websocket.send_text(json.dumps({"type": "error", "message": "bad message"}))
                continue
            action = msg.get("action")

            if action == "create":
                authed = await _handle_create(websocket, room_id, pid, msg) or authed
            elif action == "join":
                authed = await _handle_join(websocket, room_id, pid, msg) or authed
            elif action == "reconnect":
                authed = await _handle_reconnect(websocket, room_id, pid, msg) or authed
            elif action == "auth_reconnect":
                authed = await _handle_auth_reconnect(websocket, room_id, pid, msg) or authed
            elif action in ("start", "move", "abandon"):
                if not authed:
                    await websocket.send_text(json.dumps(
                        {"type": "error", "message": "not authenticated for this seat"}))
                    continue
                if action == "start":
                    await _handle_start(websocket, room_id, pid)
                elif action == "move":
                    await _handle_move(websocket, room_id, pid, msg)
                else:
                    await _handle_abandon(websocket, room_id, pid)
            else:
                await websocket.send_text(json.dumps({"type": "error", "message": "unknown action"}))
    except WebSocketDisconnect:
        pass
    finally:
        _rooms.release_socket(ROOMS, room_id, pid, websocket)


async def _handle_create(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    vs_ai = bool(msg.get("vs_ai"))
    difficulty = _valid_difficulty(msg.get("ai_difficulty"))
    expansions = _valid_expansions(msg.get("expansions"))
    num_bots = _valid_num_bots(msg.get("num_bots"))
    max_players = _valid_max_players(msg.get("max_players"))
    async with ROOM_LOCK:
        if room_id in ROOMS or _ensure_room_loaded(room_id):
            await _send(ws, {"type": "error", "message": "room already exists"})
            return False
        room = {
            "players": {pid: name},
            "sockets": {pid: ws},
            "status": "open",
            "host": pid,
            "game": None,
            "meta": {pid: {"token": _gen_token()}},
            "vs_ai": vs_ai,
            "ai_players": [],
            "ai_difficulty": difficulty,
            "expansions": expansions,
            "max_players": (1 + num_bots) if vs_ai else max_players,
        }
        ROOMS[room_id] = room
        if vs_ai:
            bots = list(AI_PIDS[:num_bots])
            for i, b in enumerate(bots):
                room["players"][b] = f"Bot {i + 1}"   # no meta entry: not joinable
            room["ai_players"] = bots
            room["status"] = "playing"
            seats = [pid] + bots
            _r = _new_rng()
            _r.shuffle(seats)                          # random seat/turn order
            room["game"] = engine.new_game(seats, expansions,
                                           seed=_r.randrange(2**31),
                                           names=dict(room["players"]))
        save_game(room_id)
        bots_pending = vs_ai and _bot_to_act(room) is not None
    await _send(ws, {"type": "created", "room_id": room_id,
                     "room": mk_room_state(room_id, viewer_pid=pid)})
    if bots_pending:
        _kick_bots(room_id)
    return True   # the creator minted this seat -> owns it


async def _handle_join(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    # A logged-in user re-entering a seat they ALREADY hold proves ownership with
    # their session token (pid == account id). Resolved before the lock (DB read).
    sess = msg.get("session_token")
    session_uid = (get_user_by_session(sess) or {}).get("id") if sess else None
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return False
        if pid in room["players"]:
            if pid in (room.get("ai_players") or ()) or session_uid != pid:
                await _send(ws, {"type": "error",
                                 "message": "seat already taken — reconnect to rejoin"})
                return False
        else:
            if room.get("status") != "open" or len(room["players"]) >= room.get("max_players", 4):
                await _send(ws, {"type": "error", "message": "room is full"})
                return False
            room["players"][pid] = name
            room.setdefault("meta", {})[pid] = {"token": _gen_token()}
        room["sockets"][pid] = ws
        save_game(room_id)
        bots_pending = _bot_to_act(room) is not None
    await _send(ws, {"type": "joined", "room_id": room_id,
                     "room": mk_room_state(room_id, viewer_pid=pid)})
    await broadcast_state(room_id)
    if bots_pending:
        _kick_bots(room_id)
    return True


async def _handle_start(ws, room_id, pid):
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return
        if room.get("host") != pid:
            await _send(ws, {"type": "error", "message": "only the host can start"})
            return
        if room.get("status") != "open":
            await _send(ws, {"type": "error", "message": "already started"})
            return
        humans = list(room["players"])
        if not 2 <= len(humans) <= room.get("max_players", 4):
            await _send(ws, {"type": "error", "message": "need at least 2 players"})
            return
        room["status"] = "playing"
        _r = _new_rng()
        _r.shuffle(humans)                             # random seat/turn order
        room["game"] = engine.new_game(humans, room.get("expansions", ["base", "intrigue"]),
                                       seed=_r.randrange(2**31),
                                       names=dict(room["players"]))
        save_game(room_id)
    await broadcast_state(room_id)


async def _handle_move(ws, room_id, pid, msg):
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or not room.get("game"):
            await _send(ws, {"type": "error", "message": "game not started"})
            return
        ok, err = engine.apply_move(room["game"], pid, msg.get("move") or {})
        if not ok:
            await _send(ws, {"type": "error", "message": err or "illegal move"})
            return
        _sync_status_from_game(room)
        bots_pending = _bot_to_act(room) is not None
    await broadcast_state(room_id)
    save_game(room_id)
    if bots_pending:
        _kick_bots(room_id)


async def _handle_reconnect(ws, room_id, pid, msg):
    token = msg.get("token")
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or pid not in room.get("players", {}):
            await _send(ws, {"type": "error", "message": "invalid token"})
            return False
        if room.get("meta", {}).get(pid, {}).get("token") != token:
            await _send(ws, {"type": "error", "message": "invalid token"})
            return False
        room["sockets"][pid] = ws
        bots_pending = _bot_to_act(room) is not None
    await _send(ws, {"type": "reconnected", "room": mk_room_state(room_id, viewer_pid=pid)})
    if bots_pending:
        _kick_bots(room_id)                            # unstick socket-dropped games
    return True


async def _handle_auth_reconnect(ws, room_id, pid, msg):
    token = msg.get("token")
    info = validate_reconnect_token(token)
    if not info or info.get("room_id") != room_id or info.get("player_id") != pid:
        await _send(ws, {"type": "error", "message": "invalid token"})
        return False
    mark_reconnect_token_used(token)
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or pid not in room.get("players", {}):
            await _send(ws, {"type": "error", "message": "no such room"})
            return False
        room["sockets"][pid] = ws
        room.setdefault("meta", {}).setdefault(pid, {})["token"] = _gen_token()
        save_game(room_id)
        bots_pending = _bot_to_act(room) is not None
    await _send(ws, {"type": "reconnected", "room": mk_room_state(room_id, viewer_pid=pid)})
    if bots_pending:
        _kick_bots(room_id)
    return True


async def _handle_abandon(ws, room_id, pid):
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            return
        game = room.get("game")
        room["status"] = "over"
        if game and not game.get("over"):
            game["over"] = True
            game["scores"] = engine.score_game(game)
            game["winners"] = [p for p in game.get("players", []) if p != pid]
            game["log"].append({"n": len(game["log"]), "pid": pid, "event": "abandon"})
        save_game(room_id)
    await broadcast_state(room_id)


# ── REST ──────────────────────────────────────────────────────────────────────
@dontminion_app.get("/health")
async def health():
    return {"status": "ok", "service": "dontminion", "version": "1.0", **build_info()}


@dontminion_app.get("/catalog")
async def catalog():
    """Static card catalog (single source for the frontend's card faces)."""
    return {
        "ok": True,
        "cards": cards.CARDS,
        "kingdom": cards.KINGDOM,
        "expansions": list(KNOWN_EXPANSIONS),
    }


@dontminion_app.get("/games")
async def games_open():
    return {"ok": True, "games": list_open_games()}


def _bearer_token(authorization: str | None = Header(default=None),
                  token: str | None = Query(default=None)) -> str | None:
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            return value.strip()
    return token


@dontminion_app.get("/games/mine")
async def games_mine(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    if not user:
        return {"ok": False, "games": [], "message": "unauthenticated"}
    return {"ok": True, "games": list_user_games(user["id"])}


@dontminion_app.get("/games/history")
async def games_history(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    if not user:
        return {"ok": False, "games": [], "message": "unauthenticated"}
    return {"ok": True, "games": list_user_history(user["id"])}


@dontminion_app.post("/games/{game_id}/cancel")
async def games_cancel(game_id: str, token: str | None = Depends(_bearer_token),
                       player_id: str | None = None):
    game_id = normalize_room(game_id)
    owner = None
    user = get_user_by_session(token) if token else None
    if user:
        owner = user["id"]
    elif player_id:
        owner = player_id
    if not owner:
        return {"ok": False, "message": "unauthenticated"}
    deleted = delete_open_game(game_id, owner)
    if deleted:
        async with ROOM_LOCK:
            ROOMS.pop(game_id, None)
    return {"ok": deleted, "message": None if deleted else "not your open game"}
