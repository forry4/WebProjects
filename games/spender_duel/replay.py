"""Reconstruct a finished Spender Duel game from its seed + move log.

A saved game stores only the FINAL state plus a log, so a review needs the board as
it stood at each moment rebuilt from scratch. That is exact here because
``engine.new_game`` is seeded and the seed is persisted: re-deal with the same seed,
re-apply the logged moves, and every draw/shuffle follows identically. (Spender had
to retrofit a `setup` snapshot for this — its deck was shuffled with no seed saved.)

    reconstruct(game) -> [Snapshot]     # one per player MOVE, plus the initial board
    review_payload(game) -> dict        # snapshots + final, hidden piles stripped

THE LOG IS NOT A MOVE LIST. It interleaves player moves with records the engine
generates itself (auto-resolved abilities, `again`, `privilege_gain`, `extra_turn`,
`game_over`) — and an AUTO-resolved `take_same`/`steal` is byte-identical to the
player-chosen one, so records cannot be classified by shape. Instead we let the
engine disambiguate: after applying a move, whatever records it appended are exactly
the ones to consume from the source log (see `_replay`). That is robust to any future
ability that logs extra records, with no per-type table to keep in sync.
"""
from __future__ import annotations

import copy

from . import engine


class ReplayError(Exception):
    """A game that cannot be reconstructed (pre-seed save, corrupt/truncated log)."""


# Log record type -> the move that produced it. Records NOT listed here are
# engine-generated and are never applied (they are consumed automatically).
def _record_to_move(rec: dict):
    t = rec.get("type")
    if t == "take":
        return {"type": "take", "cells": list(rec["cells"])}
    if t == "use_privilege":
        return {"type": "use_privilege", "cell": rec["cell"]}
    if t == "replenish":
        return {"type": "replenish"}
    if t == "reserve":
        src = ({"kind": "deck", "level": rec["level"]} if rec.get("from_deck")
               else {"kind": "pyramid", "level": rec["level"], "slot": rec["slot"]})
        return {"type": "reserve", "gold_cell": rec["gold_cell"], "source": src}
    if t == "buy":
        mv = {"type": "buy", "card_id": rec["card_id"], "from": rec["frm"]}
        if rec.get("as_color"):
            mv["as_color"] = rec["as_color"]
        return mv
    if t == "take_same":
        return {"type": "take_same", "cell": rec["cell"]}
    if t == "steal":
        return {"type": "steal", "color": rec["color"]}
    if t == "royal":                       # the resolver logs "royal", the move is choose_royal
        return {"type": "choose_royal", "royal_id": rec["royal_id"]}
    if t == "discard":
        return {"type": "discard", "color": rec["color"]}
    if t == "skip_pending":
        return {"type": "skip_pending"}
    if t == "pass":
        return {"type": "pass"}
    return None


def _strip_hidden(g: dict) -> dict:
    """Review view of a snapshot.

    The game is FINISHED, so identities are REVEALED — the point of a review is to see
    what your opponent was holding. Only the undrawable piles and the rng come off (and
    `reserved_from_deck`, which no client uses). Shape matches engine.player_view
    (bag_count / deck_counts) so the frontend renders a snapshot exactly like live state.
    """
    v = copy.deepcopy(g)
    v["bag_count"] = len(v.pop("bag", []))
    v["deck_counts"] = {k: len(d) for k, d in v.pop("decks", {}).items()}
    v.pop("rng_state", None)
    v.pop("seed", None)
    for p in v["players"].values():
        p.pop("reserved_from_deck", None)
    return v


def _replay(game: dict):
    """Yield (move, mover, sim) after each applied move, starting from the initial deal.

    The first yield is the INITIAL board (move=None). Raises ReplayError if the log
    can't be walked — callers treat that as "no turn-by-turn", never as a crash.
    """
    seed = game.get("seed")
    if seed is None:
        raise ReplayError("game has no recorded seed (saved before seeds were persisted)")
    order = list(game.get("order") or [])
    if len(order) != 2:
        raise ReplayError("game has no seat order")
    names = {pid: p.get("name", pid) for pid, p in game["players"].items()}
    sim = engine.new_game(order, names=names, seed=seed)
    yield None, None, sim

    src = game.get("log") or []
    i = 0
    guard = 0
    while i < len(src):
        guard += 1
        if guard > 5000:
            raise ReplayError("replay exceeded its step guard")
        rec = src[i]
        mv = _record_to_move(rec)
        if mv is None:
            # An engine-generated record that our own replay did NOT produce: the log
            # has drifted from the engine (e.g. a record type added without updating
            # _record_to_move). Skipping it would desync the board, so stop honestly.
            raise ReplayError(f"unreplayable log record at {i}: {rec.get('type')!r}")
        before = len(sim["log"])
        ok, err = engine.apply_move(sim, rec["pid"], mv)
        if not ok:
            raise ReplayError(f"log move {i} ({rec.get('type')}) rejected on replay: {err}")
        grown = len(sim["log"]) - before
        if grown < 1:
            raise ReplayError(f"log move {i} ({rec.get('type')}) produced no record")
        # Consume every record this ONE move generated: the move's own, plus anything
        # the engine logged for it (auto-resolved abilities, again, extra_turn,
        # game_over). This is what keeps auto- and player-resolved abilities apart
        # without a per-type table.
        i += grown
        yield mv, rec["pid"], sim


def reconstruct(game: dict) -> list[dict]:
    """Per-move snapshots of a finished game, oldest first.

    snapshots[0] is the initial deal (before any move); snapshots[k] is the board
    AFTER the k-th move. Each carries `log_len` — the log length at that point — so a
    log row at index r maps to the first snapshot with log_len > r.
    """
    out = []
    for mv, pid, sim in _replay(game):
        out.append({
            "i": len(out),
            "move": mv,
            "pid": pid,
            "log_len": len(sim["log"]),
            "game": _strip_hidden(sim),
        })
    return out


def review_payload(game: dict) -> list | None:
    """`reconstruct`, but returning None instead of raising — a review must still show
    the final board when turn-by-turn isn't available (old save, log drift)."""
    try:
        return reconstruct(game)
    except Exception:                       # noqa: BLE001 — never break the review
        return None
