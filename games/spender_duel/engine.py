"""Pure rules engine for Spender Duel (a faithful Splendor Duel port).

No FastAPI / web dependency: the engine operates on a plain ``game`` dict so it
is deterministic (given a seed), JSON-safe, and unit-testable in isolation. It
is the single contract used by the server, the bot, tests, and future AI.

Public API:
    new_game(player_ids, names=None, seed=None) -> game
    legal_moves(game, pid) -> list[move]
    apply_move(game, pid, move) -> (ok, error)
    is_over(game) -> bool
    winner(game) -> pid | None
    player_view(game, pid) -> redacted game dict (hidden info stripped)

Turn structure (rulebook): optional actions in strict order (use privileges,
then replenish), then exactly ONE mandatory action (take tokens / gold+reserve
/ purchase), then ability + royal + discard resolution, then the victory check.
Pending sub-decisions are real state keys (``pending_pid``/``pending_kind``/
``pending``) so they survive save/reconnect and are server-enforced.

Randomness that must survive save/load (bag reshuffles at replenish) persists
in ``game["rng_state"]``; decks are shuffled once at new_game and drawn
sequentially.
"""
from __future__ import annotations

import copy
import random

from . import cards as C

ABIL_AGAIN = "again"
ABIL_TAKE_SAME = "take_same"
ABIL_PRIVILEGE = "privilege"
ABIL_STEAL = "steal"

MAX_TOKENS = 10
MAX_RESERVED = 3
WIN_POINTS = 20
WIN_CROWNS = 10
WIN_COLOR_POINTS = 10
CROWN_THRESHOLDS = (3, 6)


# ── RNG persistence ──────────────────────────────────────────────────────────
def _make_rng(game: dict) -> random.Random:
    rng = random.Random()
    st = game.get("rng_state")
    if st is not None:
        rng.setstate((st[0], tuple(st[1]), st[2]))
    return rng


def _save_rng(game: dict, rng: random.Random) -> None:
    st = rng.getstate()
    game["rng_state"] = [st[0], list(st[1]), st[2]]


# ── Small helpers ────────────────────────────────────────────────────────────
def empty_tokens() -> dict:
    return {t: 0 for t in C.TOKENS}


def _opponent(game: dict, pid: str) -> str:
    a, b = game["order"]
    return b if pid == a else a


def _card(cid: str) -> dict:
    return C.CARDS[cid]


def _is_gem_or_pearl(tok) -> bool:
    return tok is not None and tok != "gold"


def bonuses_of(p: dict) -> dict:
    """Effective bonus count per color; wild cards count as their attached color."""
    b = {c: 0 for c in C.COLORS}
    for pc in p["purchased"]:
        card = _card(pc["id"])
        col = pc["as_color"] if card["bonus"] == "wild" else card["bonus"]
        if col in b:
            b[col] += card["bonus_count"]
    return b


def crowns_of(p: dict) -> int:
    return sum(_card(pc["id"])["crowns"] for pc in p["purchased"])


def points_of(p: dict) -> int:
    pts = sum(_card(pc["id"])["points"] for pc in p["purchased"])
    pts += sum(C.ROYALS[rid]["points"] for rid in p["royals"])
    return pts


def color_points_of(p: dict) -> dict:
    """Card points per bonus-color group (victory condition 3). Wilds count in
    their attached group; bonus-less cards and royals count in no group."""
    cp = {c: 0 for c in C.COLORS}
    for pc in p["purchased"]:
        card = _card(pc["id"])
        col = pc["as_color"] if card["bonus"] == "wild" else card["bonus"]
        if col in cp:
            cp[col] += card["points"]
    return cp


def _royal_entitlement(p: dict) -> int:
    crowns = crowns_of(p)
    return sum(1 for t in CROWN_THRESHOLDS if crowns >= t)


# ── Turn undo ────────────────────────────────────────────────────────────────
def _snapshot_turn(game: dict) -> None:
    """Snapshot the whole game at the START of a turn, so it can be taken back.

    Everything a turn does is undoable this way — including moves already sent to the
    server, like spending a Privilege, which no amount of client-side "deselect" can
    reverse.

    PERF (the CoC lesson — do not remove): this is a full deepcopy on every turn, which
    is the dominant cost inside an MCTS simulation. Search clones set ``_skip_undo`` and
    pay nothing (they never undo).
    """
    if game.get("_skip_undo"):
        return
    game.pop("turn_undo", None)          # never nest a snapshot inside a snapshot
    game["turn_undo"] = copy.deepcopy(game)


def _log(game: dict, pid, mtype: str, **fields) -> None:
    entry = {"t": game["turn_number"], "pid": pid, "type": mtype}
    entry.update({k: v for k, v in fields.items() if v is not None})
    game["log"].append(entry)


# ── Payment (Spender's helpers extended with pearls) ─────────────────────────
def effective_cost(cost: dict, bonuses: dict) -> dict:
    """Post-bonus cost. Pearls have no bonuses; floor 0 per color."""
    out = {}
    for col, n in cost.items():
        need = max(0, n - bonuses.get(col, 0)) if col in bonuses else n
        if need > 0:
            out[col] = need
    return out


def can_afford(cost: dict, tokens: dict, bonuses: dict) -> bool:
    """Same answer as `effective_cost` + a shortfall sum, without building the dict.

    Inlined deliberately: the MCTS asks this for every pyramid card + reserve at every
    rollout step (~12 calls per step, 240k per search), and the intermediate dict made
    it ~22% of total search time. Kept byte-identical — `max(0, n-b) > 0` is exactly
    `n-b > 0`, so the filter and the shortfall sum are unchanged.
    """
    gold = 0
    for col, n in cost.items():
        need = n - bonuses[col] if col in bonuses else n
        if need > 0:
            short = need - tokens.get(col, 0)
            if short > 0:
                gold += short
    return gold <= tokens.get("gold", 0)


def calc_spend(cost: dict, tokens: dict, bonuses: dict) -> dict:
    """Auto-payment: colored/pearl tokens first, gold covers any shortfall."""
    spend = {}
    gold = 0
    for col, need in effective_cost(cost, bonuses).items():
        have = min(tokens.get(col, 0), need)
        if have:
            spend[col] = have
        gold += need - have
    if gold:
        spend["gold"] = gold
    return spend


# ── Privileges (closed loop of 3: board pool <-> players) ────────────────────
def _grant_privilege(game: dict, to_pid: str) -> bool:
    """Scarcity rule: board pool first, else transfer from the opponent, else no-op."""
    p = game["players"][to_pid]
    if game["privileges_board"] > 0:
        game["privileges_board"] -= 1
        p["privileges"] += 1
        return True
    opp = game["players"][_opponent(game, to_pid)]
    if opp["privileges"] > 0:
        opp["privileges"] -= 1
        p["privileges"] += 1
        return True
    return False  # to_pid already holds all 3


# ── Board geometry ───────────────────────────────────────────────────────────
_UNIT_DIRS = [(0, 1), (1, 0), (1, 1), (1, -1)]  # E, S, SE, SW (positive scan)


def _valid_line(board: list, cells: list) -> bool:
    """1-3 distinct cells, all holding gems/pearls, forming a contiguous
    straight line (any of 8 directions; gaps/gold break the line by occupancy)."""
    if not isinstance(cells, list) or not 1 <= len(cells) <= 3:
        return False
    if len(set(cells)) != len(cells):
        return False
    for i in cells:
        if not isinstance(i, int) or not 0 <= i < 25 or not _is_gem_or_pearl(board[i]):
            return False
    if len(cells) == 1:
        return True
    pts = sorted(divmod(i, 5) for i in cells)
    d = (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1])
    if max(abs(d[0]), abs(d[1])) != 1:
        return False
    if len(cells) == 3:
        d2 = (pts[2][0] - pts[1][0], pts[2][1] - pts[1][1])
        if d2 != d:
            return False
    return True


def _fill_board(game: dict, rng: random.Random) -> int:
    """Shuffle the bag and fill empty cells in spiral order until the bag (or
    the empties) run out. Returns the number of tokens placed."""
    rng.shuffle(game["bag"])
    placed = 0
    for idx in C.SPIRAL_ORDER:
        if not game["bag"]:
            break
        if game["board"][idx] is None:
            game["board"][idx] = game["bag"].pop()
            placed += 1
    return placed


# ── Game creation ────────────────────────────────────────────────────────────
def new_game(player_ids: list, names: dict | None = None, seed=None) -> dict:
    assert len(player_ids) == 2, "Spender Duel is strictly 2-player"
    names = names or {}
    rng = random.Random(seed)
    decks = {}
    for lvl in (1, 2, 3):
        ids = C.deck_ids(lvl)
        rng.shuffle(ids)
        decks[str(lvl)] = ids
    pyramid = {str(lvl): [decks[str(lvl)].pop() for _ in range(n)]
               for lvl, n in C.PYRAMID_SIZES.items()}
    game = {
        "game": "spender_duel",
        "phase": "playing",
        "winner": None,
        "win_condition": None,
        "win_color": None,
        "order": list(player_ids),
        "turn": player_ids[0],
        "turn_number": 1,
        "turn_flags": {"replenished": False},
        "again": False,
        "board": [None] * 25,
        "bag": list(C.TOKEN_BAG),
        "privileges_board": 3,
        "decks": decks,
        "pyramid": pyramid,
        "royals_available": sorted(C.ROYALS.keys()),
        "players": {
            pid: {
                "name": names.get(pid, pid),
                "tokens": empty_tokens(),
                "privileges": 0,
                "reserved": [],
                # Which of `reserved` were BLIND deck draws (vs taken face-up off the
                # pyramid, which the opponent watched). The log can't answer this — it
                # deliberately omits card_id for blind reserves — so the AI needs the
                # flag here to determinize the opponent's hand instead of reading it.
                # A list of card ids; REDACTED in player_view (it would leak identities).
                "reserved_from_deck": [],
                "purchased": [],
                "royals": [],
                "royals_claimed": 0,
            }
            for pid in player_ids
        },
        "pending_pid": None,
        "pending_kind": None,
        "pending": None,
        "log": [],
        "rng_state": None,
        "seed": seed if isinstance(seed, (int, str, type(None))) else None,
    }
    _fill_board(game, rng)  # initial fill uses all 25 tokens
    _save_rng(game, rng)
    # Setup rule: the opponent of the first player starts with 1 privilege.
    _grant_privilege(game, player_ids[1])
    _snapshot_turn(game)                 # arm undo for the first turn
    return game


# ── Pending machinery ────────────────────────────────────────────────────────
def _set_pending(game: dict, pid: str, kind: str, ctx: dict) -> None:
    game["pending_pid"] = pid
    game["pending_kind"] = kind
    game["pending"] = {"ctx": ctx}


def _clear_pending(game: dict) -> None:
    game["pending_pid"] = None
    game["pending_kind"] = None
    game["pending"] = None


# ── Ability resolution ───────────────────────────────────────────────────────
def _resolve_ability(game: dict, pid: str, ability: str | None, color: str | None,
                     via: str) -> None:
    """Resolve a jewel-card or royal ability. May set a pending choice; the
    caller continues via _after_action. ``color`` = the card's effective bonus
    color (for take_same)."""
    if ability is None:
        return
    p = game["players"][pid]
    if ability == ABIL_AGAIN:
        game["again"] = True
        _log(game, pid, "again", via=via)
    elif ability == ABIL_PRIVILEGE:
        if _grant_privilege(game, pid):
            _log(game, pid, "privilege_gain", via=via)
    elif ability == ABIL_TAKE_SAME:
        cells = [i for i, t in enumerate(game["board"]) if t == color]
        if not cells:
            return  # no matching token on the board: ignore
        if len(cells) == 1:
            game["board"][cells[0]] = None
            p["tokens"][color] += 1
            _log(game, pid, "take_same", color=color, cell=cells[0], via=via)
        else:
            # The emptied CELL changes future line geometry — a real choice.
            _set_pending(game, pid, "take_same", {"color": color, "cells": cells, "via": via})
    elif ability == ABIL_STEAL:
        opp = game["players"][_opponent(game, pid)]
        colors = [t for t in C.TOKENS if t != "gold" and opp["tokens"][t] > 0]
        if not colors:
            return  # opponent has no stealable token: ignore
        if len(colors) == 1:
            opp["tokens"][colors[0]] -= 1
            p["tokens"][colors[0]] += 1
            _log(game, pid, "steal", color=colors[0], via=via)
        else:
            _set_pending(game, pid, "steal", {"colors": colors, "via": via})


# ── Turn pipeline ────────────────────────────────────────────────────────────
def _after_action(game: dict, pid: str) -> None:
    """Drive the post-mandatory-action chain: ability pendings -> royal choices
    -> discard-to-10 -> finish turn. Called after the mandatory move and after
    every pending resolver."""
    if game["pending_pid"] is not None:
        return
    p = game["players"][pid]
    if p["royals_claimed"] < _royal_entitlement(p) and game["royals_available"]:
        _set_pending(game, pid, "choose_royal", {"royals": list(game["royals_available"])})
        return
    total = sum(p["tokens"].values())
    if total > MAX_TOKENS:
        _set_pending(game, pid, "discard", {"excess": total - MAX_TOKENS})
        return
    _finish_turn(game, pid)


def _check_victory(game: dict, pid: str) -> bool:
    p = game["players"][pid]
    if points_of(p) >= WIN_POINTS:
        game["win_condition"] = "points"
    elif crowns_of(p) >= WIN_CROWNS:
        game["win_condition"] = "crowns"
    else:
        cp = color_points_of(p)
        best = max(cp, key=lambda c: cp[c])
        if cp[best] >= WIN_COLOR_POINTS:
            game["win_condition"] = "color"
            game["win_color"] = best
        else:
            return False
    game["phase"] = "over"
    game["winner"] = pid
    game["again"] = False
    _log(game, pid, "game_over", condition=game["win_condition"], color=game["win_color"])
    return True


def _finish_turn(game: dict, pid: str) -> None:
    if _check_victory(game, pid):  # victory pre-empts AGAIN
        return
    game["turn_flags"] = {"replenished": False}
    game["turn_number"] += 1
    if game["again"]:
        game["again"] = False
        _log(game, pid, "extra_turn")
    else:
        game["turn"] = _opponent(game, pid)
    # Re-arm undo for whoever now has the turn (an AGAIN turn is its own undoable turn).
    _snapshot_turn(game)


# ── Optional-action handlers (turn continues afterwards) ─────────────────────
def _h_use_privilege(game: dict, pid: str, move: dict):
    p = game["players"][pid]
    if p["privileges"] < 1:
        return False, "no privilege to use"
    if game["turn_flags"]["replenished"]:
        return False, "privileges must be used before replenishing"
    cell = move.get("cell")
    if not isinstance(cell, int) or not 0 <= cell < 25 or not _is_gem_or_pearl(game["board"][cell]):
        return False, "pick a gem or pearl token on the board"
    color = game["board"][cell]
    game["board"][cell] = None
    p["tokens"][color] += 1
    p["privileges"] -= 1
    game["privileges_board"] += 1
    _log(game, pid, "use_privilege", cell=cell, color=color)
    return True, None


def _h_replenish(game: dict, pid: str, move: dict):
    if not game["bag"]:
        return False, "the bag is empty"
    if all(t is not None for t in game["board"]):
        return False, "the board is full"
    if game["turn_flags"]["replenished"]:
        return False, "already replenished this turn"
    rng = _make_rng(game)
    placed = _fill_board(game, rng)
    _save_rng(game, rng)
    game["turn_flags"]["replenished"] = True
    granted = _grant_privilege(game, _opponent(game, pid))
    _log(game, pid, "replenish", count=placed, opp_privilege=granted or None)
    return True, None


# ── Mandatory-action handlers (each ends by driving _after_action) ───────────
def _h_take(game: dict, pid: str, move: dict):
    cells = move.get("cells")
    if not _valid_line(game["board"], cells):
        return False, "tokens must form an unbroken straight line of 1-3 gems/pearls"
    p = game["players"][pid]
    taken = []
    for i in cells:
        taken.append(game["board"][i])
        game["board"][i] = None
    for t in taken:
        p["tokens"][t] += 1
    granted = False
    if (len(taken) == 3 and len(set(taken)) == 1) or taken.count("pearl") >= 2:
        granted = _grant_privilege(game, _opponent(game, pid))
    _log(game, pid, "take", cells=list(cells), colors=taken, opp_privilege=granted or None)
    _after_action(game, pid)
    return True, None


def _h_reserve(game: dict, pid: str, move: dict):
    p = game["players"][pid]
    if len(p["reserved"]) >= MAX_RESERVED:
        return False, "you already have 3 reserved cards"
    gold_cell = move.get("gold_cell")
    if not isinstance(gold_cell, int) or not 0 <= gold_cell < 25 or game["board"][gold_cell] != "gold":
        return False, "pick a gold token on the board"
    src = move.get("source") or {}
    kind, lvl = src.get("kind"), str(src.get("level"))
    if lvl not in ("1", "2", "3"):
        return False, "bad reserve source"
    if kind == "pyramid":
        slot = src.get("slot")
        row = game["pyramid"][lvl]
        if not isinstance(slot, int) or not 0 <= slot < len(row) or row[slot] is None:
            return False, "no card in that pyramid slot"
        cid = row[slot]
        row[slot] = game["decks"][lvl].pop() if game["decks"][lvl] else None
        p["reserved"].append(cid)
        # Face-up reserve was public when performed -> card id in the log is fine.
        _log(game, pid, "reserve", level=int(lvl), slot=slot, card_id=cid, gold_cell=gold_cell)
    elif kind == "deck":
        if not game["decks"][lvl]:
            return False, "that deck is empty"
        cid = game["decks"][lvl].pop()
        p["reserved"].append(cid)
        p["reserved_from_deck"].append(cid)
        # Blind draw: the log must NOT carry the card id.
        _log(game, pid, "reserve", level=int(lvl), from_deck=True, gold_cell=gold_cell)
    else:
        return False, "bad reserve source"
    game["board"][gold_cell] = None
    p["tokens"]["gold"] += 1
    _after_action(game, pid)
    return True, None


def _find_pyramid(game: dict, cid: str):
    for lvl, row in game["pyramid"].items():
        for slot, c in enumerate(row):
            if c == cid:
                return lvl, slot
    return None, None


def _h_buy(game: dict, pid: str, move: dict):
    p = game["players"][pid]
    cid = move.get("card_id")
    if cid not in C.CARDS:
        return False, "unknown card"
    frm = move.get("from")
    if frm == "pyramid":
        lvl, slot = _find_pyramid(game, cid)
        if lvl is None:
            return False, "that card is not in the pyramid"
    elif frm == "reserve":
        if cid not in p["reserved"]:
            return False, "that card is not in your reserve"
    else:
        return False, "bad buy source"
    card = _card(cid)
    as_color = move.get("as_color")
    if card["bonus"] == "wild":
        eligible = [c for c, n in bonuses_of(p).items() if n > 0]
        if not eligible:
            return False, "you need a bonus card to purchase a wild card"
        if as_color not in eligible:
            return False, "pick one of your bonus colors for the wild card"
    elif as_color is not None:
        return False, "as_color only applies to wild cards"
    bonuses = bonuses_of(p)
    if not can_afford(card["cost"], p["tokens"], bonuses):
        return False, "you can't afford that card"
    spend = calc_spend(card["cost"], p["tokens"], bonuses)
    for col, n in spend.items():
        p["tokens"][col] -= n
        game["bag"].extend([col] * n)  # spent tokens return to the bag
    if frm == "pyramid":
        game["pyramid"][lvl][slot] = game["decks"][lvl].pop() if game["decks"][lvl] else None
    else:
        p["reserved"].remove(cid)
        if cid in p["reserved_from_deck"]:
            p["reserved_from_deck"].remove(cid)
    p["purchased"].append({"id": cid, "as_color": as_color})
    _log(game, pid, "buy", card_id=cid, frm=frm, as_color=as_color,
         points=card["points"] or None, crowns=card["crowns"] or None)
    eff_color = as_color if card["bonus"] == "wild" else card["bonus"]
    _resolve_ability(game, pid, card["ability"], eff_color, via=cid)
    _after_action(game, pid)
    return True, None


def _h_pass(game: dict, pid: str, move: dict):
    # Defensive liveness fallback only — unreachable per the no-deadlock argument
    # (see legal_moves), but the engine must never strand a player.
    if legal_moves(game, pid) != [{"type": "pass"}]:
        return False, "you have a legal action"
    _log(game, pid, "pass")
    _after_action(game, pid)
    return True, None


# ── Pending resolvers ────────────────────────────────────────────────────────
def _r_take_same(game: dict, pid: str, move: dict):
    ctx = game["pending"]["ctx"]
    cell = move.get("cell")
    if cell not in ctx["cells"] or game["board"][cell] != ctx["color"]:
        return False, "pick one of the matching tokens"
    game["board"][cell] = None
    game["players"][pid]["tokens"][ctx["color"]] += 1
    _log(game, pid, "take_same", color=ctx["color"], cell=cell, via=ctx.get("via"))
    _clear_pending(game)
    _after_action(game, pid)
    return True, None


def _r_steal(game: dict, pid: str, move: dict):
    ctx = game["pending"]["ctx"]
    color = move.get("color")
    opp = game["players"][_opponent(game, pid)]
    if color not in ctx["colors"] or color == "gold" or opp["tokens"].get(color, 0) < 1:
        return False, "pick a gem or pearl your opponent holds"
    opp["tokens"][color] -= 1
    game["players"][pid]["tokens"][color] += 1
    _log(game, pid, "steal", color=color, via=ctx.get("via"))
    _clear_pending(game)
    _after_action(game, pid)
    return True, None


def _r_choose_royal(game: dict, pid: str, move: dict):
    rid = move.get("royal_id")
    if rid not in game["royals_available"]:
        return False, "that royal card is not available"
    game["royals_available"].remove(rid)
    p = game["players"][pid]
    p["royals"].append(rid)
    p["royals_claimed"] += 1
    _log(game, pid, "royal", royal_id=rid, points=C.ROYALS[rid]["points"])
    _clear_pending(game)
    _resolve_ability(game, pid, C.ROYALS[rid]["ability"], None, via=rid)
    _after_action(game, pid)
    return True, None


def _r_discard(game: dict, pid: str, move: dict):
    p = game["players"][pid]
    color = move.get("color")
    if color not in C.TOKENS or p["tokens"][color] < 1:
        return False, "pick a token you hold"
    p["tokens"][color] -= 1
    game["bag"].append(color)
    _log(game, pid, "discard", color=color)
    _clear_pending(game)
    _after_action(game, pid)  # re-arms the discard pending while still over 10
    return True, None


def _r_skip_pending(game: dict, pid: str, move: dict):
    kind = game["pending_kind"]
    if kind == "choose_royal":
        # Forfeit: count the entitlement as consumed so the check can't loop.
        game["players"][pid]["royals_claimed"] += 1
    _log(game, pid, "skip_pending", kind=kind)
    _clear_pending(game)
    _after_action(game, pid)
    return True, None


_RESOLVERS = {
    "take_same": _r_take_same,
    "steal": _r_steal,
    "choose_royal": _r_choose_royal,
    "discard": _r_discard,
    "skip_pending": _r_skip_pending,
}
# Which resolver move types are allowed per pending kind. Discard is mandatory
# (no skip) — it strictly reduces the hand, so it always terminates.
RESOLVERS_FOR = {
    "take_same": {"take_same", "skip_pending"},
    "steal": {"steal", "skip_pending"},
    "choose_royal": {"choose_royal", "skip_pending"},
    "discard": {"discard"},
}

_HANDLERS = {
    "use_privilege": _h_use_privilege,
    "replenish": _h_replenish,
    "take": _h_take,
    "reserve": _h_reserve,
    "buy": _h_buy,
    "pass": _h_pass,
}


# ── Move enumeration ─────────────────────────────────────────────────────────
def _pending_legal_moves(game: dict, pid: str) -> list:
    kind = game["pending_kind"]
    ctx = game["pending"]["ctx"] if game.get("pending") else {}
    moves: list = []
    if kind == "take_same":
        for i in ctx.get("cells", []):
            if game["board"][i] == ctx.get("color"):
                moves.append({"type": "take_same", "cell": i})
    elif kind == "steal":
        opp = game["players"][_opponent(game, pid)]
        for c in ctx.get("colors", []):
            if opp["tokens"].get(c, 0) > 0:
                moves.append({"type": "steal", "color": c})
    elif kind == "choose_royal":
        for rid in game["royals_available"]:
            moves.append({"type": "choose_royal", "royal_id": rid})
    elif kind == "discard":
        p = game["players"][pid]
        for t in C.TOKENS:
            if p["tokens"][t] > 0:
                moves.append({"type": "discard", "color": t})
        return moves  # no skip: discarding to 10 is mandatory
    moves.append({"type": "skip_pending"})
    return moves


def _line_moves(board: list) -> list:
    moves = []
    for i in range(25):
        if not _is_gem_or_pearl(board[i]):
            continue
        moves.append({"type": "take", "cells": [i]})
        r, c = divmod(i, 5)
        for dr, dc in _UNIT_DIRS:
            r2, c2 = r + dr, c + dc
            if not (0 <= r2 < 5 and 0 <= c2 < 5) or not _is_gem_or_pearl(board[r2 * 5 + c2]):
                continue
            j = r2 * 5 + c2
            moves.append({"type": "take", "cells": [i, j]})
            r3, c3 = r2 + dr, c2 + dc
            if 0 <= r3 < 5 and 0 <= c3 < 5 and _is_gem_or_pearl(board[r3 * 5 + c3]):
                moves.append({"type": "take", "cells": [i, j, r3 * 5 + c3]})
    return moves


def _reserve_moves(game: dict, pid: str) -> list:
    p = game["players"][pid]
    moves = []
    if len(p["reserved"]) < MAX_RESERVED:
        gold_cells = [i for i, t in enumerate(game["board"]) if t == "gold"]
        for g in gold_cells:
            for lvl in ("1", "2", "3"):
                for slot, cid in enumerate(game["pyramid"][lvl]):
                    if cid is not None:
                        moves.append({"type": "reserve", "gold_cell": g,
                                      "source": {"kind": "pyramid", "level": int(lvl), "slot": slot}})
                if game["decks"][lvl]:
                    moves.append({"type": "reserve", "gold_cell": g,
                                  "source": {"kind": "deck", "level": int(lvl)}})
    return moves


def _buy_moves(game: dict, pid: str) -> list:
    p = game["players"][pid]
    moves = []
    bonuses = bonuses_of(p)
    eligible_wild = [c for c, n in bonuses.items() if n > 0]
    sources = [("pyramid", cid) for row in game["pyramid"].values()
               for cid in row if cid is not None]
    sources += [("reserve", cid) for cid in p["reserved"]]
    for frm, cid in sources:
        card = _card(cid)
        if not can_afford(card["cost"], p["tokens"], bonuses):
            continue
        if card["bonus"] == "wild":
            for col in eligible_wild:
                moves.append({"type": "buy", "card_id": cid, "from": frm, "as_color": col})
        else:
            moves.append({"type": "buy", "card_id": cid, "from": frm})
    return moves


def _mandatory_moves(game: dict, pid: str) -> list:
    """Takes, then reserves, then buys — the ORDER is load-bearing.

    `ai._rollout_move` reproduces one priority tier of this list without building the
    rest, and relies on generating it in exactly this order so its `rng.choice` lands
    on the same move. Split into per-tier helpers so it can call them directly; the
    concatenation here must stay takes -> reserves -> buys.
    """
    return _line_moves(game["board"]) + _reserve_moves(game, pid) + _buy_moves(game, pid)


def legal_moves(game: dict, pid: str) -> list:
    if is_over(game):
        return []
    if game["pending_pid"] is not None:
        if pid != game["pending_pid"]:
            return []
        return _pending_legal_moves(game, pid)
    if pid != game["turn"]:
        return []
    p = game["players"][pid]
    moves: list = []
    if p["privileges"] > 0 and not game["turn_flags"]["replenished"]:
        for i, t in enumerate(game["board"]):
            if _is_gem_or_pearl(t):
                moves.append({"type": "use_privilege", "cell": i})
    if game["bag"] and not game["turn_flags"]["replenished"] and any(t is None for t in game["board"]):
        moves.append({"type": "replenish"})
    moves.extend(_mandatory_moves(game, pid))
    if not moves:
        # Unreachable per the no-deadlock argument (<=20 tokens held, <=3 gold of
        # 25 => an empty bag implies a takeable gem/pearl) — defensive only.
        return [{"type": "pass"}]
    return moves


# ── Public API ────────────────────────────────────────────────────────────────
def _undo_turn(game: dict, pid: str) -> tuple:
    """Take back everything done so far this turn, back to the turn's start.

    Restores the snapshot WHOLESALE — including the move log, so the undone actions
    leave no trace. That is deliberate and load-bearing for the review: `replay.py`
    reconstructs a game by re-applying its log, so the log must only ever contain moves
    that actually stood. (Logging the undo instead would put an unreplayable record in
    the log and break turn-by-turn review.) The rng_state is restored too, so a redone
    draw plays out identically and the game stays reproducible from seed + log.

    KNOWN TRADE-OFF (same one CoC's undo accepts): a player can blind-reserve, see the
    card, and undo — learning that deck's top card. Re-shuffling on undo would close
    that, but the reshuffle is a random event that ISN'T in the log, so replay would
    diverge from what was played. A friendly-game undo is worth more than the exploit.
    """
    if game.get("turn") != pid:
        return False, "you can only undo on your turn"
    snap = game.get("turn_undo")
    if not snap:
        return False, "nothing to undo"
    restored = copy.deepcopy(snap)
    game.clear()
    game.update(restored)
    _snapshot_turn(game)                 # the restored turn is itself undoable again
    return True, None


def apply_move(game: dict, pid: str, move: dict) -> tuple:
    if is_over(game):
        return False, "game is over"
    mt = move.get("type")
    # Undo is checked BEFORE the pending gate: a turn must be takeable back from any
    # point, including part-way through an ability's sub-decision.
    if mt == "undo_turn":
        return _undo_turn(game, pid)
    if game["pending_pid"] is not None:
        if pid != game["pending_pid"]:
            return False, "not your decision"
        if mt not in RESOLVERS_FOR.get(game["pending_kind"], set()):
            return False, f"must resolve {game['pending_kind']} first"
        return _RESOLVERS[mt](game, pid, move)
    if pid != game["turn"]:
        return False, "not your turn"
    handler = _HANDLERS.get(mt)
    if handler is None:
        return False, f"unknown move: {mt}"
    return handler(game, pid, move)


def is_over(game: dict) -> bool:
    return game.get("phase") == "over"


def winner(game: dict):
    return game.get("winner")


# ── Hidden-information boundary ──────────────────────────────────────────────
def player_view(game: dict, pid: str | None) -> dict:
    """Per-recipient redaction: the bag's contents, the decks' order, and the
    OPPONENT's BLIND (deck-drawn) reserved cards are hidden. Reveal everything at game
    over. ``pid=None`` = spectator (both hands' blind reserves redacted).

    ONLY DECK-TOP RESERVES ARE SECRET — the Spender model, and the only one that was ever
    coherent here. Reserving a face-up pyramid card is a PUBLIC act: your opponent watched
    that exact card leave the pyramid, and `_h_reserve` accordingly puts its `card_id`
    straight into the move log ("public when performed"), which is broadcast to everyone.
    So hiding it here was pure theatre — the opponent could already read the id out of the
    log. A blind deck draw is different: nobody saw it, and its id is deliberately kept out
    of the log, so it stays redacted until game over.

    This also removes the one thing that made client-side AI leak: the browser must be
    handed the bot's own view to search with, and now that view contains no secret the
    log hasn't already published — except its blind draws, which stay hidden.
    """
    g = copy.deepcopy(game)
    g["bag_count"] = len(g.pop("bag"))
    g["deck_counts"] = {lvl: len(d) for lvl, d in g["decks"].items()}
    g.pop("decks")
    g.pop("rng_state", None)
    g.pop("seed", None)
    # The undo snapshot is a FULL copy of the game — bag, decks, both hands. Shipping it
    # would hand the client every hidden card while the visible state stays redacted.
    g.pop("turn_undo", None)
    g.pop("_skip_undo", None)
    # `reserved_from_deck` is a list of card IDS — it must never reach an opponent (it
    # would reveal the very identities `reserved` redacts). No client needs it, so it
    # comes off every seat's view.
    for p in g["players"].values():
        p.pop("reserved_from_deck", None)
    if not is_over(game):
        for opid, p in g["players"].items():
            if opid == pid:
                continue
            blind = set(game["players"][opid]["reserved_from_deck"])
            p["reserved"] = [{"level": _card(cid)["level"], "facedown": True}
                             if cid in blind else cid
                             for cid in p["reserved"]]
    return g
