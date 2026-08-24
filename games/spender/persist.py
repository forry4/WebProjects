"""At-rest compaction for the Spender `state_json` blob.

A PURE PERSISTENCE BOUNDARY, exactly like `games/castles_of_crimson/persist.py`:
`compact_state` runs on the way into the DB, `expand_state` on the way back out, and
nothing else in the codebase knows the stored shape. The live game dict, the wire, the
engine, the AI and the frontend all keep seeing full card objects.

Spender's deck is STATIC and deterministic — a card id like "L2-7" is a level plus an
index into a frozen list, which is why `cards.card_catalog()` can rebuild any card from
its id alone. The move log and the `setup` snapshot have always exploited that and store
ids only; the live `board`/`decks`/`nobles`/`purchased`/`reserved` never did, and carried
the full `{id, level, points, bonus, cost}` object everywhere instead. Measured on a
late-game shape: **1,598 -> 562 stored bytes (-65%)**, 10,519 -> 3,648 raw.

THE FALLBACK IS NOT DEFENSIVE PADDING — it is load-bearing. `_apply_reserve` stamps
`card["from_deck"] = True` on a blind deck reserve, so not every card in a game equals
its catalog entry. A card is replaced by its id ONLY when it round-trips exactly;
anything else is stored verbatim. That makes the codec lossless by construction rather
than by having thought of every mutation.
"""
from __future__ import annotations

from . import cards as C

_VERSION = 1
_MARK = "_c"            # compaction marker; absent => a legacy row, expand is a no-op

_CATALOG: dict | None = None
_NOBLES: dict | None = None


def _catalog() -> dict:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = C.card_catalog()
    return _CATALOG


def _nobles() -> dict:
    global _NOBLES
    if _NOBLES is None:
        _NOBLES = {n["id"]: n for n in C.ALL_NOBLES}
    return _NOBLES


# ── one card / one noble ─────────────────────────────────────────────────────
def _enc_card(c):
    if not isinstance(c, dict):
        return c
    cid = c.get("id")
    entry = _catalog().get(cid) if isinstance(cid, str) else None
    if entry is None:
        return c
    return cid if c == {"id": cid, **entry} else c      # exact round-trip, or verbatim


def _dec_card(v):
    if not isinstance(v, str):
        return v
    entry = _catalog().get(v)
    return {"id": v, **entry} if entry else v


def _enc_noble(n):
    if not isinstance(n, dict):
        return n
    nid = n.get("id")
    ref = _nobles().get(nid) if isinstance(nid, str) else None
    return nid if ref is not None and n == ref else n


def _dec_noble(v):
    if not isinstance(v, str):
        return v
    ref = _nobles().get(v)
    return dict(ref) if ref else v


# ── the card locations, spelled out ──────────────────────────────────────────
# Enumerated by hand rather than walked generically: `moves` and `setup` already hold
# BARE ID STRINGS, so a generic walk would try to "decode" them into card objects and
# silently corrupt the log. tests/test_persist.py asserts this covers every card.
def _map(game: dict, card_fn, noble_fn) -> dict:
    g = dict(game)
    if isinstance(g.get("decks"), dict):
        g["decks"] = {lk: [card_fn(c) for c in v] if isinstance(v, list) else v
                      for lk, v in g["decks"].items()}
    if isinstance(g.get("board"), dict):
        g["board"] = {lk: [card_fn(c) if c is not None else None for c in v]
                      if isinstance(v, list) else v
                      for lk, v in g["board"].items()}
    if isinstance(g.get("nobles"), list):
        g["nobles"] = [noble_fn(n) for n in g["nobles"]]
    if isinstance(g.get("players"), dict):
        players = {}
        for pid, p in g["players"].items():
            if isinstance(p, dict):
                p = dict(p)
                for k in ("purchased", "reserved"):
                    if isinstance(p.get(k), list):
                        p[k] = [card_fn(c) for c in p[k]]
                if isinstance(p.get("nobles"), list):
                    p["nobles"] = [noble_fn(n) for n in p["nobles"]]
            players[pid] = p
        g["players"] = players
    # The pending-discard snapshot is a whole second copy of the game (only present
    # while a discard is open) and carries every card location again.
    snap = g.get("pre_discard_snapshot")
    if isinstance(snap, dict):
        g["pre_discard_snapshot"] = _map(snap, card_fn, noble_fn)
    return g


# ── public API ───────────────────────────────────────────────────────────────
def compact_state(state: dict) -> dict:
    """Shrink a save blob. Returns a new dict; `state` and its game are untouched —
    `state["game"]` is the LIVE game dict of a running room."""
    game = state.get("game")
    if not isinstance(game, dict):
        return state
    return {**state, "game": _map(game, _enc_card, _enc_noble), _MARK: _VERSION}


def expand_state(state: dict) -> dict:
    """Inverse of `compact_state`. A blob written before this existed carries no marker
    and is returned unchanged, so old prod rows load with no migration."""
    if not isinstance(state, dict) or not state.get(_MARK):
        return state
    out = {k: v for k, v in state.items() if k != _MARK}
    game = out.get("game")
    if isinstance(game, dict):
        out["game"] = _map(game, _dec_card, _dec_noble)
    return out
