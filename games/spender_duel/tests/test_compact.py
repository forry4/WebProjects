"""The compact projection carries no secret.

This is the half of the projection's contract that `duel-core/src/bin/compact_parity.rs`
structurally CANNOT check: it only ever sees what was shipped, so it can prove the
projection is lossless for the search and still not notice it smuggling the deck order.
The check has to run here, against the real game dict, and it is the reason client-side
AI is safe to enable at all.

THE INVARIANT: `project(game, pid)` is a pure function of what `pid` may legitimately
know. Rather than grep the output for ids that shouldn't be there (which only catches the
leaks you thought of), the tests below PERMUTE the hidden state — shuffle a deck, swap
which blind card is whose within a level — and require the projection not to move. A
projection that depended on any secret would have to change.
"""
import copy
import random

import pytest

from games.spender_duel import cards as C
from games.spender_duel import compact, engine


def _game(seed=7):
    return engine.new_game(["p0", "p1"], seed=seed)


def _blind_reserve(g, pid, level):
    """Give `pid` a blind (deck-top) reserve off `level` — the one genuinely secret
    holding in the game, and the whole reason the projection needs a redaction."""
    cid = g["decks"][str(level)].pop()
    g["players"][pid]["reserved"].append(cid)
    g["players"][pid]["reserved_from_deck"].append(cid)
    return cid


def test_projection_ignores_deck_order():
    """The deck's ORDER is secret; its multiset is deducible. Reshuffling must not move
    the projection (and the pools must ship canonicalized)."""
    g = _game()
    before = compact.project(g, "p0")
    rng = random.Random(99)
    for lvl in ("1", "2", "3"):
        rng.shuffle(g["decks"][lvl])
    assert compact.project(g, "p0") == before
    for pool in before["unseen"]:
        assert pool == sorted(pool)


def test_projection_hides_which_blind_card_the_opponent_holds():
    """The LEVEL of an opponent's blind reserve is public (they were watched drawing off
    that deck); WHICH card it is must not be recoverable. Swapping their card for any
    other unseen card of the same level must be invisible to us."""
    g = _game()
    held = _blind_reserve(g, "p1", 2)
    before = compact.project(g, "p0")

    other = g["decks"]["2"][0]
    g["players"]["p1"]["reserved"] = [other]
    g["players"]["p1"]["reserved_from_deck"] = [other]
    g["decks"]["2"][0] = held

    assert compact.project(g, "p0") == before, "the projection reveals WHICH card is reserved"
    # What DOES ship: the count, bucketed by level — and never the id.
    opp = before["players"][1]
    assert opp["reserved_blind"] == [0, 1, 0]
    assert opp["reserved"] == []
    assert opp["reserved_from_deck"] == []
    assert compact.CARD_IX[held] in before["unseen"][1], "the pool must still contain it"


def _card_ids_in(node) -> list:
    """Every int in a subtree — cards ship as ints, so this is where an id could hide."""
    if isinstance(node, dict):
        return [x for v in node.values() for x in _card_ids_in(v)]
    if isinstance(node, list):
        return [x for v in node for x in _card_ids_in(v)]
    return [node] if isinstance(node, int) and not isinstance(node, bool) else []


def test_opponent_blind_id_never_appears_outside_the_unseen_pool():
    """Belt-and-braces on the invariance tests: the id may only ever appear inside its
    level's pool, where it is indistinguishable from every other unseen card of that
    level — exactly what `ai._determinize` re-deals from."""
    g = _game()
    held = compact.CARD_IX[_blind_reserve(g, "p1", 3)]
    proj = compact.project(g, "p0")
    assert held in proj["unseen"][2], "the pool must contain it (that is the redaction)"

    # `players` and `pyramid` are the only fields outside `unseen` that carry card ids at
    # all, so between them they cover every route the id could escape by. (A raw scan of
    # the whole projection would false-positive on any int that merely equals the id — a
    # token count, a cell index.)
    outside = copy.deepcopy(proj)
    for field in ("players", "pyramid"):
        assert held not in _card_ids_in(outside[field]), \
            f"opponent's blind reserve id leaked into {field}"


def test_own_blind_reserve_is_projected_in_full():
    """The deliberate exception (see compact.py's docstring): this is the BOT's view, and
    the bot can BUY its own reserves — redacting them would change how it plays. The cost
    is that a vs-AI human could read the bot's face-down cards out of the console, which
    is why main.py arms the client path for vs-AI rooms only."""
    g = _game()
    held = _blind_reserve(g, "p0", 1)
    proj = compact.project(g, "p0")
    me = proj["players"][0]
    assert me["reserved"] == [compact.CARD_IX[held]]
    assert me["reserved_from_deck"] == [compact.CARD_IX[held]]
    assert me["reserved_blind"] == [0, 0, 0]
    # ...and it must NOT be in the pool: it is no longer unseen, and double-counting it
    # would let determinize deal the same card twice.
    assert compact.CARD_IX[held] not in proj["unseen"][0]


def test_bag_ships_sorted_and_ignores_bag_order():
    """The bag's multiset is deducible (25 tokens minus the board minus both hands), so
    shipping it is not a leak — but its draw order is secret."""
    g = _game()
    before = compact.project(g, "p0")
    assert before["bag"] == sorted(before["bag"])
    random.Random(5).shuffle(g["bag"])
    assert compact.project(g, "p0") == before


def test_unseen_pool_is_deducible_from_public_information():
    """The strongest statement available: the pool is not a concession, it is arithmetic
    the client can already do. Every card is in exactly one of deck / pyramid / a hand /
    purchased, and all but the deck and the opponent's blind reserves are public — so a
    client with only the public view can reconstruct `unseen` exactly."""
    g = _game()
    _blind_reserve(g, "p1", 2)
    _blind_reserve(g, "p0", 2)
    proj = compact.project(g, "p0")
    view = engine.player_view(g, "p0")     # what the client is shipped in the normal game view

    for lvl in (1, 2, 3):
        seen = set()
        for cid in view["pyramid"][str(lvl)]:
            if cid is not None:
                seen.add(cid)
        for p in view["players"].values():
            seen |= {e["id"] for e in p["purchased"]}
            # A redacted opponent reserve is a {level, facedown} dict, not an id — so it
            # correctly contributes nothing to `seen`, which is the point.
            seen |= {c for c in p["reserved"] if isinstance(c, str)}
        deduced = sorted(compact.CARD_IX[c] for c in C.deck_ids(lvl) if c not in seen)
        assert proj["unseen"][lvl - 1] == deduced


def test_projection_covers_both_seats_symmetrically():
    g = _game()
    _blind_reserve(g, "p1", 1)
    assert compact.project(g, "p0")["seat"] == 0
    assert compact.project(g, "p1")["seat"] == 1
    # p1's own blind reserve is full from p1's side, counted from p0's.
    assert compact.project(g, "p1")["players"][1]["reserved_from_deck"]
    assert compact.project(g, "p0")["players"][1]["reserved_from_deck"] == []


@pytest.mark.parametrize("seed", range(6))
def test_projection_survives_a_real_game(seed):
    """Every position of a played-out game projects without raising, and the invariance
    holds throughout — including after abilities, royals and discards have fired."""
    from games.spender_duel import bot

    g = _game(seed)
    rng = random.Random(seed)
    for _ in range(2000):
        if engine.is_over(g):
            break
        actor = g.get("pending_pid") or g["turn"]
        mv = bot.choose(g, actor, rng)
        if mv is None:
            break
        ok, _ = engine.apply_move(g, actor, mv)
        assert ok
        for pid in g["order"]:
            proj = compact.project(g, pid)
            for pool in proj["unseen"]:
                assert pool == sorted(pool)
            assert len(proj["board"]) == 25
