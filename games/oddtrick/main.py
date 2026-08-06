"""Oddtrick room server — mounted at /oddtrick.

Same scaffolding as the other five games: an in-memory ``ROOMS`` dict under a
single lock, WebSocket per room+player, and every rule delegated to
``engine.py``. The generic half of that scaffolding lives in ``core/rooms.py``
and is aliased below under the historical private names.

Two things here are load-bearing and were expensive to learn elsewhere:

* **Seat identity is bound.** The ``player`` path segment is client-supplied
  and every pid is broadcast in the public players map, so a socket must PROVE
  it owns its pid before it can act as that seat or receive that seat's view.
  ``authed`` flips true only via create / join-as-a-new-seat / join-with-a-
  matching-session-token / reconnect-with-the-room-token / auth_reconnect.
* **Broadcasts are redacted per recipient.** ``mk_room_state`` rebuilds the
  game through ``engine.player_view`` for each socket's own pid, so the
  opponent's hand, the covered side-pile bottoms and the out-of-play pair
  never reach a wire that should not see them.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import random
import time
from typing import Any

from fastapi import Depends, FastAPI, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from core import rooms as _rooms
from core.auth import get_user_by_session
from core.build_info import build_info
from core.config import cors_allowed_origins
from core.db import cleanup_stale_games, get_db_conn, maybe_cleanup_games

from . import bot
from . import engine
from . import persist

LOG = logging.getLogger("oddtrick")

TABLE = "oddtrick_games"
AI_PID = "bot"
DIFFICULTIES = ("easy", "normal")
DEFAULT_DIFFICULTY = "normal"

#: Minimum wall-clock a bot move takes, so the board does not jump.
BOT_FLOOR_SECONDS = 0.45


def _valid_difficulty(value) -> str:
    return value if value in DIFFICULTIES else DEFAULT_DIFFICULTY


oddtrick_app = FastAPI(title="Oddtrick API")
oddtrick_app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

ROOMS: dict[str, dict] = {}
ROOM_LOCK = asyncio.Lock()

# ── Shared room-server primitives (core/rooms.py) ────────────────────────────
normalize_room = _rooms.normalize_room
_gen_token = _rooms.gen_room_token
_db = _rooms.db_conn
_send = _rooms.send_json


def _ensure_room_loaded(room_id: str) -> dict | None:
    return _rooms.ensure_room_loaded(ROOMS, room_id, load_game_to_memory)


def oddtrick_init_db() -> None:
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        id TEXT PRIMARY KEY,
        status TEXT,
        player1_id TEXT, player1_name TEXT,
        player2_id TEXT, player2_name TEXT,
        host_id TEXT,
        state_json TEXT,
        created_at INTEGER, updated_at INTEGER)""")
    conn.commit()
    conn.close()


oddtrick_init_db()
try:
    # Retention: guest 24h / registered 30d, by last activity. Guarded because
    # this runs at IMPORT time and joins `users` — in a fresh checkout that
    # table may not exist yet, and a retention sweep must never stop the module
    # (or every test that imports it) from loading.
    cleanup_stale_games(TABLE)
except Exception as _cleanup_err:  # pragma: no cover - environment-dependent
    LOG.warning("oddtrick retention sweep skipped at import: %s", _cleanup_err)


# ── Persistence ──────────────────────────────────────────────────────────────
_DB_WRITE_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="oddtrick-db-write")
_save_conn = None  # only ever touched by the write-executor thread


def _persist_row(room_id, status, p1id, p1name, p2id, p2name, host,
                 state_json, now, created_at) -> None:
    global _save_conn
    try:
        if _save_conn is None:
            _save_conn = _db()
        cur = _save_conn.cursor()
        cur.execute(f"SELECT id FROM {TABLE} WHERE id=?", (room_id,))
        if cur.fetchone() is not None:
            cur.execute(f"""UPDATE {TABLE} SET status=?, player2_id=?, player2_name=?,
                            state_json=?, updated_at=? WHERE id=?""",
                        (status, p2id, p2name, state_json, now, room_id))
        else:
            cur.execute(f"""INSERT INTO {TABLE}
                (id,status,player1_id,player1_name,player2_id,player2_name,
                 host_id,state_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (room_id, status, p1id, p1name, p2id, p2name, host,
                         state_json, created_at, now))
        _save_conn.commit()
    except Exception:  # noqa: BLE001 — a save must never crash the room
        LOG.warning("oddtrick save failed for %s; dropping connection",
                    room_id, exc_info=True)
        try:
            if _save_conn is not None:
                _save_conn.close()
        except Exception:
            pass
        _save_conn = None


def _encode_state(state: dict) -> str:
    """The ONLY write path into state_json — compact, then the shared codec."""
    return _rooms.encode_state(persist.compact_state(state))


def _decode_state(blob) -> dict:
    """The ONLY read path out of state_json. Every reader must funnel through
    here, offline tools included, or a compacted blob reaches code expecting
    the verbose shape."""
    return persist.expand_state(_rooms.decode_state(blob))


def save_game(room_id: str) -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    pids = list(room.get("players", {}).keys())
    names = list(room.get("players", {}).values())
    state = {
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
        "game": room.get("game"),
        "meta": room.get("meta", {}),
        "vs_ai": room.get("vs_ai", False),
        "ai_player": room.get("ai_player"),
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
    }
    now = int(time.time())
    _DB_WRITE_EXEC.submit(
        _persist_row, room_id, room.get("status", "open"),
        pids[0] if pids else None, names[0] if names else None,
        pids[1] if len(pids) > 1 else None, names[1] if len(names) > 1 else None,
        room.get("host"), _encode_state(state), now, now,
    )


def load_game_state(room_id: str) -> dict | None:
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"SELECT state_json FROM {TABLE} WHERE id=?", (room_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row["state_json"]:
        return None
    try:
        return _decode_state(row["state_json"])
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
        "ai_player": state.get("ai_player"),
        # Persisted so a vs-bot game reconnected after a redeploy keeps the
        # tier it was created with instead of silently reverting to default.
        "ai_difficulty": _valid_difficulty(state.get("ai_difficulty")),
        "sockets": {},
    }
    return True


def list_open_games() -> list[dict]:
    maybe_cleanup_games(TABLE, background=True)
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"""SELECT id, player1_id, player1_name, created_at FROM {TABLE}
                    WHERE status='open' ORDER BY created_at DESC LIMIT 20""")
    rows = cur.fetchall()
    conn.close()
    return [{"id": r["id"], "host_id": r["player1_id"],
             "host_name": r["player1_name"], "created_at": r["created_at"]}
            for r in rows]


def list_user_games(user_id: str) -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"""SELECT id, status, player1_id, player1_name, player2_id,
                           player2_name, state_json, created_at, updated_at
                    FROM {TABLE}
                    WHERE (player1_id=? OR player2_id=?) AND status != 'over'
                    ORDER BY updated_at DESC""", (user_id, user_id))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            g = (_decode_state(r["state_json"]).get("game") or {})
        except Exception:
            g = {}
        your_turn = bool(g) and engine.turn_pid(g) == user_id
        out.append({
            "id": r["id"], "status": r["status"],
            "player1_name": r["player1_name"], "player2_name": r["player2_name"],
            "you_are_p1": r["player1_id"] == user_id, "your_turn": your_turn,
            "created_at": r["created_at"], "updated_at": r["updated_at"],
        })
    return out


def list_user_history(user_id: str) -> list[dict]:
    conn = _db()
    cur = conn.cursor()
    cur.execute(f"""SELECT id, player1_id, player1_name, player2_id, player2_name,
                           state_json, updated_at
                    FROM {TABLE}
                    WHERE (player1_id=? OR player2_id=?) AND status='over'
                    ORDER BY updated_at DESC LIMIT ?""",
                (user_id, user_id, _rooms.HISTORY_LIMIT))
    rows = cur.fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            g = (_decode_state(r["state_json"]).get("game") or {})
        except Exception:
            g = {}
        res = (g or {}).get("result")
        if not res:
            continue
        seat = engine.seat_of(g, user_id)
        if seat is None:
            continue
        is_p1 = r["player1_id"] == user_id
        opp_name = (r["player2_name"] if is_p1 else r["player1_name"]) or "Opponent"
        scores = res.get("scores") or [0, 0]
        out.append({
            "id": r["id"], "opp_name": opp_name,
            "your_score": scores[seat], "opp_score": scores[1 - seat],
            "you_won": scores[seat] > scores[1 - seat],
            "contract": {"level": res.get("level"), "denom": res.get("denom"),
                         "made": res.get("made"),
                         "you_declared": res.get("declarer") == seat},
            "updated_at": r["updated_at"],
        })
    return out


def delete_open_game(game_id: str, user_id: str) -> bool:
    """SELECT-then-DELETE lives in core.rooms — never cursor.rowcount, which
    the libsql wrapper does not expose (it 500'd the cancel endpoint in prod)."""
    return _rooms.delete_open_game(TABLE, "player1_id", game_id, user_id)


# ── Room state / broadcast (PER-RECIPIENT redaction) ─────────────────────────
def mk_room_state(room_id: str, viewer_pid: str | None = None) -> dict[str, Any]:
    room = ROOMS.get(room_id, {})
    g = room.get("game")
    return {
        "room_id": room_id,
        "players": room.get("players", {}),
        "host": room.get("host"),
        "status": room.get("status", "open"),
        # Rebuilt for THIS recipient. Never ship `room["game"]` raw.
        "game": engine.player_view(g, viewer_pid) if g else None,
        "vs_ai": room.get("vs_ai", False),
        "ai_player": room.get("ai_player"),
        "ai_difficulty": room.get("ai_difficulty", DEFAULT_DIFFICULTY),
        # Scoped to the recipient: a room-wide token map would hand every
        # socket the other seat's reconnect credential.
        "reconnect_tokens": (
            {viewer_pid: room.get("meta", {}).get(viewer_pid, {}).get("token")}
            if viewer_pid and room.get("meta", {}).get(viewer_pid) else {}
        ),
    }


async def broadcast_state(room_id: str, mtype: str = "room_update") -> None:
    room = ROOMS.get(room_id)
    if not room:
        return
    for pid, ws in list(room.get("sockets", {}).items()):
        try:
            await ws.send_text(json.dumps(
                {"type": mtype, "room": mk_room_state(room_id, viewer_pid=pid)}))
        except Exception:
            pass


def _sync_status_from_game(room: dict) -> None:
    if engine.is_over(room.get("game")):
        room["status"] = "over"


def _bot_should_act(room: dict) -> bool:
    g = room.get("game")
    ai = room.get("ai_player")
    return bool(g and ai and not engine.is_over(g) and engine.turn_pid(g) == ai)


# ── Bot scheduler ────────────────────────────────────────────────────────────
# Heavy work never runs under ROOM_LOCK on the event-loop thread: snapshot under
# the lock, compute off it, re-lock, RE-VALIDATE that the turn is still the
# bot's, then apply. A rewrite that looped synchronous engine work under the
# lock took prod down once.
_BOT_EXEC = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="oddtrick-bot")


def _bot_move_sync(g: dict, seat: int, difficulty: str, seed: int):
    rng = random.Random(seed)
    if difficulty == "easy" and rng.random() < 0.35:
        # Easy blunders on purpose rather than searching worse.
        if g["phase"] == "play":
            return {"kind": "play", "card": rng.choice(engine.legal_moves(g, seat))}
        opt = engine.auction_options(g)
        if opt["may_pass"] and rng.random() < 0.5:
            return {"kind": "pass"}
        if opt["levels"] and opt["denoms"]:
            return {"kind": "bid", "level": opt["levels"][0],
                    "denom": rng.choice(opt["denoms"])}
        return {"kind": "pass"}
    kind, mv = bot.act(g, seat, rng)
    if kind == "play":
        return {"kind": "play", "card": mv}
    if mv.get("pass"):
        return {"kind": "pass"}
    return {"kind": "bid", "level": mv["level"], "denom": mv["denom"]}


async def _schedule_bot_turn(room_id: str) -> None:
    """Safe to call at any time; no-ops when it is not the bot's turn."""
    loop = asyncio.get_running_loop()
    while True:
        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if not room or not _bot_should_act(room):
                return
            g = room["game"]
            ai = room["ai_player"]
            seat = engine.seat_of(g, ai)
            difficulty = _valid_difficulty(room.get("ai_difficulty"))
            snapshot = json.loads(json.dumps(g))
            trick_before = (g["phase"], g["trick"], len(g["history"]),
                            len(g["auction"]["log"]))

        t0 = time.monotonic()
        try:
            move = await loop.run_in_executor(
                _BOT_EXEC, _bot_move_sync, snapshot, seat, difficulty,
                random.randrange(2 ** 31))
        except Exception:
            LOG.warning("oddtrick bot failed in %s", room_id, exc_info=True)
            return
        delay = BOT_FLOOR_SECONDS - (time.monotonic() - t0)
        if delay > 0:
            await asyncio.sleep(delay)

        async with ROOM_LOCK:
            room = ROOMS.get(room_id)
            if not room or not _bot_should_act(room):
                return
            g = room["game"]
            # Re-validate: the position must not have moved while we computed.
            if (g["phase"], g["trick"], len(g["history"]),
                    len(g["auction"]["log"])) != trick_before:
                continue
            try:
                engine.apply_move(g, ai, move)
            except ValueError:
                LOG.warning("oddtrick bot produced an illegal move in %s", room_id)
                return
            _sync_status_from_game(room)
            save_game(room_id)
        await broadcast_state(room_id)


def _new_rng() -> random.Random:
    return random.Random()


def _start_new_game(room: dict, room_id: str) -> None:
    seats = [p for p in room["players"].keys()]
    rng = _new_rng()
    rng.shuffle(seats)   # who opens the auction is a real edge; randomise it
    room["game"] = engine.new_game(seats, rng, opener=0)
    room["status"] = "playing"


# ── WebSocket ────────────────────────────────────────────────────────────────
@oddtrick_app.websocket("/ws/{room}/{player}")
async def ws_room_player(websocket: WebSocket, room: str, player: str):
    await websocket.accept()
    room_id = normalize_room(room)
    pid = player
    if await _rooms.reject_if_connecting_too_fast(websocket):
        return
    _msg_throttle = _rooms.MessageThrottle()
    # See the module docstring: the pid in the path is not trusted until a
    # handshake proves ownership. NOTHING registers this socket in
    # room["sockets"] before that.
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
                await _send(websocket, {"type": "error", "message": "bad message"})
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
                    await _send(websocket, {
                        "type": "error",
                        "message": "not authenticated for this seat"})
                    continue
                if action == "start":
                    await _handle_start(websocket, room_id, pid)
                elif action == "move":
                    await _handle_move(websocket, room_id, pid, msg)
                else:
                    await _handle_abandon(websocket, room_id, pid)
            else:
                await _send(websocket, {"type": "error", "message": "unknown action"})
    except WebSocketDisconnect:
        pass
    finally:
        _rooms.release_socket(ROOMS, room_id, pid, websocket)


async def _handle_create(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    vs_ai = bool(msg.get("vs_ai"))
    difficulty = _valid_difficulty(msg.get("ai_difficulty"))
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
            "ai_player": None,
            "ai_difficulty": difficulty,
        }
        ROOMS[room_id] = room
        if vs_ai:
            room["players"][AI_PID] = "Bot"
            room["ai_player"] = AI_PID
            _start_new_game(room, room_id)
        save_game(room_id)
        bot_turn = vs_ai and _bot_should_act(room)
    await _send(ws, {"type": "created", "room_id": room_id,
                     "room": mk_room_state(room_id, viewer_pid=pid)})
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))
    return True   # the creator minted this seat, so they own it


async def _handle_join(ws, room_id, pid, msg):
    name = (msg.get("name") or "Player").strip()[:24] or "Player"
    sess = msg.get("session_token")
    session_uid = (get_user_by_session(sess) or {}).get("id") if sess else None
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return False
        if pid in room["players"]:
            # Re-entering an EXISTING seat: prove it, or the reply below hands
            # a stranger that seat's hand.
            if session_uid != pid:
                await _send(ws, {"type": "error",
                                 "message": "seat already taken — reconnect to rejoin"})
                return False
        else:
            if room.get("status") != "open" or len(room["players"]) >= 2:
                await _send(ws, {"type": "error", "message": "room is full"})
                return False
            room["players"][pid] = name
            room.setdefault("meta", {})[pid] = {"token": _gen_token()}
        room["sockets"][pid] = ws
        save_game(room_id)
    await _send(ws, {"type": "joined", "room_id": room_id,
                     "room": mk_room_state(room_id, viewer_pid=pid)})
    await broadcast_state(room_id)
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
        if len(room["players"]) < 2:
            await _send(ws, {"type": "error", "message": "need two players"})
            return
        if room.get("game"):
            await _send(ws, {"type": "error", "message": "already started"})
            return
        _start_new_game(room, room_id)
        save_game(room_id)
        bot_turn = _bot_should_act(room)
    await broadcast_state(room_id, "started")
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_move(ws, room_id, pid, msg):
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or not room.get("game"):
            await _send(ws, {"type": "error", "message": "no game"})
            return
        g = room["game"]
        if engine.is_over(g):
            await _send(ws, {"type": "error", "message": "game is over"})
            return
        if engine.turn_pid(g) != pid:
            await _send(ws, {"type": "error", "message": "not your turn"})
            return
        try:
            engine.apply_move(g, pid, msg.get("move") or {})
        except (ValueError, KeyError, TypeError) as exc:
            await _send(ws, {"type": "error", "message": str(exc) or "illegal move"})
            return
        _sync_status_from_game(room)
        save_game(room_id)
        bot_turn = _bot_should_act(room)
    await broadcast_state(room_id)
    if bot_turn:
        asyncio.create_task(_schedule_bot_turn(room_id))


async def _handle_reconnect(ws, room_id, pid, msg):
    token = msg.get("token")
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room:
            await _send(ws, {"type": "error", "message": "no such room"})
            return False
        want = room.get("meta", {}).get(pid, {}).get("token")
        if not token or not want or token != want:
            await _send(ws, {"type": "error", "message": "bad reconnect token"})
            return False
        room["sockets"][pid] = ws
    await _send(ws, {"type": "joined", "room_id": room_id,
                     "room": mk_room_state(room_id, viewer_pid=pid)})
    await broadcast_state(room_id)
    # Deliberate: unsticks a vs-bot game whose scheduler died with the socket.
    asyncio.create_task(_schedule_bot_turn(room_id))
    return True


async def _handle_auth_reconnect(ws, room_id, pid, msg):
    sess = msg.get("session_token")
    user = get_user_by_session(sess) if sess else None
    if not user or user.get("id") != pid:
        await _send(ws, {"type": "error", "message": "bad session"})
        return False
    async with ROOM_LOCK:
        room = _ensure_room_loaded(room_id)
        if not room or pid not in room.get("players", {}):
            await _send(ws, {"type": "error", "message": "no such seat"})
            return False
        room["sockets"][pid] = ws
    await _send(ws, {"type": "joined", "room_id": room_id,
                     "room": mk_room_state(room_id, viewer_pid=pid)})
    await broadcast_state(room_id)
    asyncio.create_task(_schedule_bot_turn(room_id))
    return True


async def _handle_abandon(ws, room_id, pid):
    async with ROOM_LOCK:
        room = ROOMS.get(room_id)
        if not room:
            return
        g = room.get("game")
        if g and not engine.is_over(g):
            seat = engine.seat_of(g, pid)
            if seat is not None:
                # Forfeit: the opponent takes the contract's value.
                g["phase"] = "over"
                scores = [0, 0]
                scores[1 - seat] = max(1, g["auction"]["level"] ** 2)
                g["result"] = {"declarer": g["auction"]["declarer"],
                               "level": g["auction"]["level"],
                               "denom": g["auction"]["denom"],
                               "declarer_pts": g["pts"][g["auction"]["declarer"]]
                               if g["auction"]["declarer"] >= 0 else 0,
                               "made": False, "short": 0,
                               "abandoned_by": seat, "scores": scores}
        room["status"] = "over"
        save_game(room_id)
    await broadcast_state(room_id)


# ── REST ─────────────────────────────────────────────────────────────────────
@oddtrick_app.get("/health")
async def health():
    return {"ok": True, "game": "oddtrick", **build_info()}


@oddtrick_app.get("/catalog")
async def catalog():
    """Static rules data the client renders — kept server-side so the two can
    never disagree about what a trick is worth."""
    return {
        "ranks": engine.RANK_NAMES,
        "suits": engine.SUIT_NAMES,
        "denoms": engine.DENOM_NAMES,
        "tricks": engine.NTRICKS,
        "pool": engine.POOL,
        "trick_values": [engine.trick_value(t) for t in range(engine.NTRICKS)],
        "min_level": engine.MIN_LEVEL,
        "max_level": engine.MAX_LEVEL,
        "max_raise": engine.MAX_RAISE,
        "short_penalty": engine.SHORT_PENALTY,
        "difficulties": list(DIFFICULTIES),
    }


@oddtrick_app.get("/games")
async def games_open():
    return {"games": list_open_games()}


def _bearer_token(authorization: str | None = Header(default=None),
                  token: str | None = Query(default=None)) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return token


@oddtrick_app.get("/games/mine")
async def games_mine(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    if not user:
        return {"games": []}
    return {"games": list_user_games(user["id"])}


@oddtrick_app.get("/games/history")
async def games_history(token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    if not user:
        return {"games": []}
    return {"games": list_user_history(user["id"])}


@oddtrick_app.delete("/games/{game_id}")
async def games_cancel(game_id: str, token: str | None = Depends(_bearer_token)):
    user = get_user_by_session(token) if token else None
    if not user:
        return {"ok": False, "message": "not signed in"}
    ok = delete_open_game(game_id, user["id"])
    if ok:
        ROOMS.pop(normalize_room(game_id), None)
    return {"ok": ok}
