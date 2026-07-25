"""Spender's rules — the single source of truth for how a move changes the game.

WHY THIS EXISTS. Spender was the only one of the four games without an engine
module. Its rules lived INLINE inside the WebSocket handler in main.py (a ~200-line
`elif move_type == ...` ladder), and a second, independent implementation
(`main._sim_apply_move`) served the server MCTS. Counting the AZ compact engine
(`ai/serving/engine.py`) and the Rust/WASM port (`rust-cores/spender-core`), the
rules existed in FOUR places — and the differential tests chained the other three
to each other, leaving the one path that actually adjudicates a human's move
untested and free to drift. `apply_move` below IS that path, extracted verbatim,
so `main.py` now validates through the same code the tests drive.

CONTRACT (mirrors CoC / Where Wolf? / Duel):

    apply_move(game, pid, mv) -> (ok, err, effects)

- Validates and mutates `game` IN PLACE; returns ``(False, "reason", {})``
  without touching state when the move is illegal.
- `effects` reports the sub-decisions the caller must surface:
  ``{"discard_pid": pid|None, "noble_choice_pid": pid|None}``.
- Room-level concerns (status, sockets, saves, AI scheduling, broadcasting)
  stay in main.py. This module knows nothing about rooms, FastAPI, or the DB —
  it imports only the leaf `cards` module.

PENDING SUB-DECISIONS ARE GAME-STATE KEYS (`pending_noble_pid`,
`pending_discard_pid`, `pending_noble_choice`, `pre_discard_snapshot`), not
transient message fields, so they survive saves/reconnects and are enforced
here rather than trusted from the client. The game dict stays JSON-safe.

NOTE ON THE MCTS SIMULATOR. `main._sim_apply_move` deliberately DIFFERS: it
auto-resolves nobles and discards with heuristics instead of entering a pending
phase, because the search treats those as forced. That difference is intended
and is pinned by tests/test_engine_rules.py rather than papered over.
"""
from __future__ import annotations

import copy

from games.spender.cards import (
    GEM_COLORS, bonuses_from, can_afford, calc_spend,
)

LEVEL_KEYS = ["L1", "L2", "L3"]
TOKEN_CAP = 10
RESERVE_CAP = 3


# ─── Setup ──────────────────────────────────────────────────────────────────

def deal_board(decks: dict) -> dict:
    return {lk: [decks[lk].pop() if decks[lk] else None for _ in range(4)] for lk in LEVEL_KEYS}


def capture_setup(g: dict) -> None:
    """Snapshot the dealt initial board / deck-order / nobles (ids only) so a finished game can
    be replayed move-by-move offline (games/spender/ai/serving/replay.py). The deck is shuffled in
    place and popped during play with no seed stored, so without this the per-turn 12-card board
    (the biggest input to the S evaluator) is unrecoverable. Captured ONCE right after the board
    and nobles are dealt, before any move. ids only -> compact; resolve via card_catalog()."""
    g["setup"] = {
        "board": {lk: [c["id"] if c else None for c in g["board"][lk]] for lk in g["board"]},
        "decks": {lk: [c["id"] for c in g["decks"][lk]] for lk in g["decks"]},
        "nobles": [n["id"] for n in g["nobles"]],
    }


# ─── Scoring / turn lifecycle ───────────────────────────────────────────────

def check_nobles(game: dict, pid: str) -> list:
    bonuses = bonuses_from(game["players"][pid]["purchased"])
    return [n for n in game["nobles"] if all(bonuses.get(c, 0) >= v for c, v in n["req"].items())]


def advance_turn(game: dict) -> str:
    order = game["order"]
    return order[(order.index(game["turn"]) + 1) % len(order)]


def calc_points(ps: dict) -> int:
    return sum(c["points"] for c in ps["purchased"]) + sum(n["points"] for n in ps["nobles"])


def resolve_winner(game: dict) -> None:
    """End the game: pick winner(s) via tiebreakers — most pts → fewest purchased → shared."""
    def score_key(pid):
        ps = game["players"][pid]
        return (calc_points(ps), -len(ps["purchased"]))

    scores = {pid: score_key(pid) for pid in game["order"]}
    best = max(scores.values())
    winners = [pid for pid, s in scores.items() if s == best]
    game["phase"] = "over"
    game["winner"] = winners[0] if len(winners) == 1 else winners


def win_points(game: dict) -> int:
    """Points needed to trigger the final round. Defaults to 15 (Classic); 21 for the Long mode.
    Read per-game so the value lives in the game dict (persisted by save/load; old saves -> 15)."""
    return int(game.get("win_points", 15))


def finish_turn(game: dict, pid: str) -> None:
    """Advance turn after pid's action; start final-round countdown if pid hit the win threshold; end game when round completes."""
    if calc_points(game["players"][pid]) >= win_points(game) and "final_round_trigger" not in game:
        game["final_round_trigger"] = pid

    new_turn = advance_turn(game)
    game["turn"] = new_turn

    if "final_round_trigger" in game:
        trigger_idx = game["order"].index(game["final_round_trigger"])
        if game["order"].index(new_turn) <= trigger_idx:
            resolve_winner(game)


def check_winner(game: dict) -> str | None:
    wp = win_points(game)
    for pid in game["order"]:
        if calc_points(game["players"][pid]) >= wp:
            return pid
    return None


def log_move(game: dict, pid: str, mv_type: str, **details) -> None:
    """Prepend a move record to game['moves'] (newest first). Entries are COMPACT — a
    buy/reserve stores only `card_id` (resolve via card_catalog()/build_deck()), not the
    full card dict — so the whole game is cheap to keep and ship over the wire. The 500
    cap is a safety bound (a real game is well under it). Read by the end-game Review
    screen and the admin GET /games/{id}/full analysis endpoint."""
    entry: dict = {"pid": pid, "type": mv_type}
    entry.update({k: v for k, v in details.items() if v is not None})
    game.setdefault("moves", []).insert(0, entry)
    game["moves"] = game["moves"][:500]


# ─── Move application (the authoritative path) ──────────────────────────────

def _find_board_card(game: dict, card_id) -> tuple[dict | None, tuple | None]:
    for lk in LEVEL_KEYS:
        for i, c in enumerate(game["board"][lk]):
            if c and c["id"] == card_id:
                return c, ("board", lk, i)
    return None, None


def _no_effects() -> dict:
    return {"discard_pid": None, "noble_choice_pid": None}


def apply_move(game: dict, pid: str, mv: dict) -> tuple[bool, str | None, dict]:
    """Validate + apply `mv` for `pid`. See the module docstring for the contract.

    The guard ORDER is load-bearing (it is the documented error hierarchy): game-over
    beats not-your-turn, which beats the pending sub-decision gates, which beat the
    per-move-type rules. A stray client message can never clear an unmet requirement,
    because the gates read the game dict, not the message.
    """
    effects = _no_effects()

    if game.get("phase") == "over":
        return False, "game is over", effects
    if game.get("turn") != pid:
        return False, "not your turn", effects

    ps = game["players"][pid]
    move_type = mv.get("type")

    if game.get("pending_noble_pid") == pid and move_type != "pick_noble":
        return False, "must choose a noble first", effects
    if game.get("pending_discard_pid") == pid and move_type not in ("discard", "undo_discard"):
        return False, "must discard down to 10 gems first", effects

    if move_type == "take_gems":
        return _apply_take_gems(game, pid, ps, mv, effects)
    if move_type == "discard":
        return _apply_discard(game, pid, ps, mv, effects)
    if move_type == "undo_discard":
        return _apply_undo_discard(game, pid, effects)
    if move_type == "buy":
        return _apply_buy(game, pid, ps, mv, effects)
    if move_type == "reserve":
        return _apply_reserve(game, pid, ps, mv, effects)
    if move_type == "pick_noble":
        return _apply_pick_noble(game, pid, ps, mv, effects)
    return False, "unknown move type", effects


def _apply_take_gems(game, pid, ps, mv, effects):
    colors = mv.get("colors", [])
    if not colors or len(colors) > 3:
        return False, "take 1-3 gems", effects

    freq: dict[str, int] = {}
    for c in colors:
        freq[c] = freq.get(c, 0) + 1
    doubles = [c for c, n in freq.items() if n == 2]
    if any(n > 2 for n in freq.values()) or len(doubles) > 1:
        return False, "invalid gem selection", effects
    if doubles and (len(colors) != 2 or len(freq) != 1):
        return False, "double take must be exactly 2 of one color", effects
    if doubles and game["bank"].get(doubles[0], 0) < 4:
        return False, "need >= 4 in bank for double take", effects
    for c in colors:
        if game["bank"].get(c, 0) <= 0:
            return False, f"no {c} in bank", effects

    pre = copy.deepcopy(game)   # for undo if this overfills
    for c in colors:
        game["bank"][c] -= 1
        ps["tokens"][c] = ps["tokens"].get(c, 0) + 1
    log_move(game, pid, "take_gems", colors=colors)
    _settle_or_discard(game, pid, ps, effects, pre)
    return True, None, effects


def _apply_discard(game, pid, ps, mv, effects):
    color = mv.get("color")
    if not color or ps["tokens"].get(color, 0) <= 0:
        return False, "can't discard that", effects
    ps["tokens"][color] -= 1
    game["bank"][color] = game["bank"].get(color, 0) + 1
    # Log on commit; an undo_discard restores the pre-action snapshot (taken before
    # the take/reserve was logged), which drops these discard entries too — so the
    # log stays faithful.
    log_move(game, pid, "discard", color=color)
    if sum(ps["tokens"].values()) > TOKEN_CAP:
        effects["discard_pid"] = pid
        game["pending_discard_pid"] = pid
    else:
        game.pop("pending_discard_pid", None)
        game.pop("pre_discard_snapshot", None)
        finish_turn(game, pid)
    return True, None, effects


def _apply_undo_discard(game, pid, effects):
    """Revert the whole over-filling action (take/reserve) and any discards made
    since, restoring the pre-action snapshot."""
    snap = game.get("pre_discard_snapshot")
    if game.get("pending_discard_pid") != pid or not snap:
        return False, "nothing to undo", effects
    restored = copy.deepcopy(snap)   # snapshot has no pending/snapshot keys
    # Restore IN PLACE so the caller's `game` reference (and room["game"]) stays the
    # same object — the handler used to swap in a new dict and rebind its local.
    game.clear()
    game.update(restored)
    return True, None, effects


def _apply_buy(game, pid, ps, mv, effects):
    card_id = mv.get("card_id")
    card, source = _find_board_card(game, card_id)
    if not card:
        for i, c in enumerate(ps["reserved"]):
            if c["id"] == card_id:
                card, source = c, ("reserved", i)
                break
    if not card:
        return False, "card not found", effects

    bonuses = bonuses_from(ps["purchased"])
    if not can_afford(card["cost"], ps["tokens"], bonuses):
        return False, "can't afford", effects

    spend = calc_spend(card["cost"], ps["tokens"], bonuses)
    for c, n in spend.items():
        ps["tokens"][c] = ps["tokens"].get(c, 0) - n
        game["bank"][c] = game["bank"].get(c, 0) + n
    ps["purchased"].append(card)
    if source[0] == "board":
        lk, idx = source[1], source[2]
        game["board"][lk][idx] = game["decks"][lk].pop() if game["decks"][lk] else None
    else:
        ps["reserved"].pop(source[1])
    log_move(game, pid, "buy", card_id=card["id"])

    claimable = check_nobles(game, pid)
    if len(claimable) > 1:
        # A real decision — park it as game state and let the player choose.
        game["pending_noble_choice"] = [n["id"] for n in claimable]
        game["pending_noble_pid"] = pid
        effects["noble_choice_pid"] = pid
    elif claimable:
        n = claimable[0]
        ps["nobles"].append(n)
        game["nobles"] = [x for x in game["nobles"] if x["id"] != n["id"]]
        log_move(game, pid, "noble", pts=n["points"], noble_id=n["id"])
        finish_turn(game, pid)
    else:
        finish_turn(game, pid)
    return True, None, effects


def _apply_reserve(game, pid, ps, mv, effects):
    if len(ps["reserved"]) >= RESERVE_CAP:
        return False, "already have 3 reserved", effects

    pre = copy.deepcopy(game)   # for undo if this overfills
    card_id = mv.get("card_id")
    deck_level = mv.get("deck_level")
    card = None
    if card_id:
        for lk in LEVEL_KEYS:
            for i, c in enumerate(game["board"][lk]):
                if c and c["id"] == card_id:
                    card = c
                    game["board"][lk][i] = game["decks"][lk].pop() if game["decks"][lk] else None
                    break
            if card:
                break
    elif deck_level:
        lk = f"L{deck_level}"
        if game["decks"][lk]:
            card = game["decks"][lk].pop()
            # blind deck-top reserve — hidden from the opponent (Splendor rule)
            card["from_deck"] = True
    if not card:
        return False, "card not found", effects

    ps["reserved"].append(card)
    if game["bank"].get("gold", 0) > 0:
        game["bank"]["gold"] -= 1
        ps["tokens"]["gold"] = ps["tokens"].get("gold", 0) + 1
    log_move(game, pid, "reserve", card_id=card["id"], from_deck=card.get("from_deck"))
    _settle_or_discard(game, pid, ps, effects, pre)
    return True, None, effects


def _apply_pick_noble(game, pid, ps, mv, effects):
    noble_id = mv.get("noble_id")
    pending = game.get("pending_noble_choice") or []
    if game.get("pending_noble_pid") != pid or noble_id not in pending:
        return False, "no noble choice pending", effects
    noble = next((n for n in game["nobles"] if n["id"] == noble_id), None)
    if not noble:
        return False, "noble not found", effects
    ps["nobles"].append(noble)
    game["nobles"] = [x for x in game["nobles"] if x["id"] != noble_id]
    log_move(game, pid, "noble", pts=noble["points"], noble_id=noble_id)
    game.pop("pending_noble_choice", None)
    game.pop("pending_noble_pid", None)
    finish_turn(game, pid)
    return True, None, effects


def _settle_or_discard(game, pid, ps, effects, pre) -> None:
    """Shared tail of take_gems/reserve: either the action overfilled past the token
    cap — park a discard sub-decision plus the undo snapshot — or the turn completes."""
    if sum(ps["tokens"].values()) > TOKEN_CAP:
        effects["discard_pid"] = pid
        game["pending_discard_pid"] = pid
        game["pre_discard_snapshot"] = pre
    else:
        game.pop("pending_discard_pid", None)
        finish_turn(game, pid)
