"""Canonical compact projection of a Spender Duel game dict — the searchable state the
browser's WASM bot is handed.

WHY IT EXISTS. Moving the bot's search into the player's browser means handing the
player the bot's own searchable view. Duel has hidden information, so that view must
contain nothing the player could not already deduce — otherwise "client-side AI is
harmless, tampering only weakens your own opponent" stops being true and becomes "open
the console and read the deck".

The rule is exactly ``ai._determinize``'s: what the search may not depend on, we do not
ship.

  * BAG — the multiset is fully deducible (25 tokens minus the board minus both hands,
    all public), so shipping it is not a leak. Its ORDER is the secret, so it ships
    SORTED — and ``_fill_board`` reshuffles it before drawing anyway.
  * DECKS — the ORDER is the secret. Per level we ship the UNSEEN POOL (that level's
    deck plus the OPPONENT's blind reserves of that level), SORTED, plus the true deck
    length; the client re-deals from it, which is precisely what ``_determinize`` does
    server-side. That pool is also fully deducible: every card is in exactly one of
    deck / pyramid / a hand / purchased, and all but the deck and the blind reserves are
    public, so ``unseen = all_of_level - pyramid - purchased - known_reserved`` is
    arithmetic the client can already do.
  * OPPONENT BLIND RESERVES — WHICH card is secret; the LEVEL is not (they were watched
    drawing off that deck). So we ship a per-level COUNT, never an id.
  * Everything else — board, pyramid, privileges, tokens, purchased, royals, and the
    opponent's FACE-UP reserves — is public (see ``engine.player_view``) and ships true.

The invariant this buys, and the one ``tests/test_compact.py`` gates: **the projection
is a pure function of public information** — permuting the hidden state (shuffling a
deck, swapping which blind card is whose within a level) cannot change the output.

THE ONE DELIBERATE EXCEPTION, inherited from Spender's ``_compact_state_dict``: this is
the BOT's view, so it carries the BOT's OWN blind reserves in full. It has to — the
search can buy them, so redacting them would change how the bot plays. In a vs-AI game
the recipient is the human opponent, who could therefore read the bot's face-down cards
out of the console. That is cheating at solitaire: it costs the reader their own fun and
nobody else's. It is NOT acceptable between two humans, which is why ``main.py`` arms the
client path for vs-AI rooms only.

NOT PROJECTED, deliberately: the pending's ``via`` (log-only — no rule reads it; see
``engine._log``) and the move log itself (the server's, for replay/review).

``duel-core/src/compact.rs`` ingests this shape and
``duel-core/src/bin/compact_parity.rs`` gates that the ingested state yields identical
``legal_moves`` and ``ai._value`` for the projected seat. This file and that one must
never drift independently.
"""
from __future__ import annotations

from . import cards as C
from . import engine

# Index encodings — the wire format shared with the Rust. Identical to the ones
# `duel-core/tools/gen_engine_fixtures.py` already gates the engine port with;
# `gen_compact_fixtures.py` asserts they still agree, so a drift fails loudly.
IDS = C.deck_ids(1) + C.deck_ids(2) + C.deck_ids(3)
CARD_IX = {cid: i for i, cid in enumerate(IDS)}     # deck order: L1 0..29, L2 30..53, L3 54..66
TOK_IX = {t: i for i, t in enumerate(C.TOKENS)}     # white=0..black=4, pearl=5, gold=6
COLOR_IX = {c: i for i, c in enumerate(C.COLORS)}
ROYAL_IX = {r: i for i, r in enumerate(sorted(C.ROYALS))}
KIND_IX = {None: 0, "take_same": 1, "steal": 2, "choose_royal": 3, "discard": 4}
WIN_IX = {None: 0, "points": 1, "crowns": 2, "color": 3}


ROYAL_IDS = sorted(C.ROYALS)


def _tok(t) -> int:
    return -1 if t is None else TOK_IX[t]


def _card(cid) -> int:
    return -1 if cid is None else CARD_IX[cid]


def _level_ix(cid: str) -> int:
    return C.CARDS[cid]["level"] - 1


def project(game: dict, pid: str) -> dict:
    """The game as `pid` may legitimately see it, in the Rust `State`'s int encoding.

    Seats are INDICES into `game["order"]` throughout (the Rust has no player ids); the
    projected `seat` field is `pid`'s own index — whose view this is, and whose decision
    the client is being asked to search.
    """
    order = game["order"]
    seat = order.index(pid)
    opp_pid = order[1 - seat]

    # The opponent's blind reserves, bucketed by LEVEL: the level is public, the
    # identity is not, so only the per-level COUNT is ever shipped.
    blind_by_level: list[list[str]] = [[], [], []]
    for cid in game["players"][opp_pid]["reserved_from_deck"]:
        blind_by_level[_level_ix(cid)].append(cid)

    unseen, deck_lens = [], []
    for lvl in range(3):
        deck = game["decks"][str(lvl + 1)]
        pool = [CARD_IX[c] for c in deck] + [CARD_IX[c] for c in blind_by_level[lvl]]
        pool.sort()                      # canonicalize: the order is the secret, the multiset isn't
        unseen.append(pool)
        deck_lens.append(len(deck))

    players = []
    for s, p_pid in enumerate(order):
        p = game["players"][p_pid]
        mine = s == seat
        blind = set(p["reserved_from_deck"])
        players.append({
            "tokens": [p["tokens"][t] for t in C.TOKENS],
            "privileges": p["privileges"],
            # Own: every reserve, in TRUE order — `_buy_moves` enumerates this list in
            # order and the rollout samples it by index, so the order is play-affecting.
            # Opponent: face-up only, in their true relative order (public — the log
            # published each as it was reserved). `_determinize` appends the re-dealt
            # blind cards after the face-ups, so the ingested shape matches it exactly.
            "reserved": [CARD_IX[c] for c in p["reserved"] if mine or c not in blind],
            "reserved_from_deck": [CARD_IX[c] for c in p["reserved_from_deck"]] if mine else [],
            "reserved_blind": [0, 0, 0] if mine else [len(b) for b in blind_by_level],
            "purchased": [[CARD_IX[e["id"]],
                           COLOR_IX[e["as_color"]] if e.get("as_color") else -1]
                          for e in p["purchased"]],
            "royals": [ROYAL_IX[r] for r in p["royals"]],
            "royals_claimed": p["royals_claimed"],
        })

    ctx = (game.get("pending") or {}).get("ctx") or {}
    return {
        "seat": seat,
        "phase": 1 if engine.is_over(game) else 0,
        "winner": -1 if game["winner"] is None else order.index(game["winner"]),
        "win_condition": WIN_IX[game["win_condition"]],
        "win_color": COLOR_IX[game["win_color"]] if game.get("win_color") else -1,
        "turn": order.index(game["turn"]),
        "turn_number": game["turn_number"],
        "replenished": int(game["turn_flags"]["replenished"]),
        "again": int(game["again"]),
        "board": [_tok(t) for t in game["board"]],
        "bag": sorted(TOK_IX[t] for t in game["bag"]),
        "privileges_board": game["privileges_board"],
        "pyramid": [[_card(c) for c in game["pyramid"][str(l)]] for l in (1, 2, 3)],
        "deck_lens": deck_lens,
        "unseen": unseen,
        "royals": [ROYAL_IX[r] for r in game["royals_available"]],
        "players": players,
        "pending_pid": -1 if game["pending_pid"] is None else order.index(game["pending_pid"]),
        "pending_kind": KIND_IX[game["pending_kind"]],
        "pending": {
            "color": _tok(ctx.get("color")),
            "cells": list(ctx.get("cells", [])),
            "colors": [TOK_IX[c] for c in ctx.get("colors", [])],
            "royals": [ROYAL_IX[r] for r in ctx.get("royals", [])],
            "excess": ctx.get("excess", 0),
        },
    }


# ── The move coming back ──────────────────────────────────────────────────────
def _at(seq, i):
    """Bounds-checked lookup. `seq[i]` would happily accept a NEGATIVE index and return
    a real-but-wrong card/colour — a silently legal move, not an error. This decodes
    data from the browser, so every index is hostile until proven otherwise."""
    if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(seq):
        raise ValueError(f"index {i!r} out of range")
    return seq[i]


def decode_move(enc) -> dict | None:
    """`duel-core`'s `encmove::enc_move` output -> an engine move dict, or None.

    The inverse of `duel-core/tools/gen_engine_fixtures.enc_move`, i.e. the shape the
    fixtures already prove both engines agree on.

    TOTAL AND NON-RAISING BY CONTRACT: the input crossed the network from a browser, so
    anything malformed is None and the caller drops it. This is NOT the authorization
    boundary — the server still re-validates the decoded move by MEMBERSHIP in
    `engine.legal_moves`, so the worst a hostile client achieves is a move it was
    entitled to play anyway (against itself).

    Key SETS matter for that membership check: `legal_moves` omits `as_color` entirely
    for a non-wild card and `slot` for a deck reserve, so this must too, or `==` fails
    against a move that is in fact legal.
    """
    if not isinstance(enc, dict):
        return None
    t = enc.get("t")
    try:
        if t == "take":
            cells = enc["cells"]
            if not isinstance(cells, list) or not all(
                    isinstance(c, int) and not isinstance(c, bool) and 0 <= c < 25 for c in cells):
                return None
            return {"type": "take", "cells": list(cells)}
        if t == "use_privilege":
            return {"type": "use_privilege", "cell": _at(range(25), enc["cell"])}
        if t == "replenish":
            return {"type": "replenish"}
        if t == "pass":
            return {"type": "pass"}
        if t == "reserve":
            level = _at((None, 1, 2, 3), enc["level"])
            source = ({"kind": "pyramid", "level": level, "slot": _at(range(5), enc["slot"])}
                      if enc["kind"] == 0 else {"kind": "deck", "level": level})
            return {"type": "reserve", "gold_cell": _at(range(25), enc["cell"]), "source": source}
        if t == "buy":
            mv = {"type": "buy", "card_id": _at(IDS, enc["card"]),
                  "from": "pyramid" if enc["from"] == 0 else "reserve"}
            as_color = enc.get("as_color", -1)
            if as_color is not None and as_color != -1:
                mv["as_color"] = _at(C.COLORS, as_color)   # wild cards only
            return mv
        if t == "take_same":
            return {"type": "take_same", "cell": _at(range(25), enc["cell"])}
        if t in ("steal", "discard"):
            return {"type": t, "color": _at(C.TOKENS, enc["color"])}
        if t == "choose_royal":
            return {"type": "choose_royal", "royal_id": _at(ROYAL_IDS, enc["royal"])}
        if t == "skip_pending":
            return {"type": "skip_pending"}
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    return None
