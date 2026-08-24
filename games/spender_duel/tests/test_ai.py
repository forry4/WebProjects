"""The MCTS bot's SEARCH-side pruning (`ai._legal`).

These prunes are not rules — the engine still permits every move here. They exist so
the search spends its sims on branches that can matter. That makes them dangerous in
one specific way: a prune that drops a move which is genuinely best makes the bot
play WORSE while looking like an optimization. So each one is pinned to an exact
argument, and the exceptions to that argument are tested as hard as the rule.
"""
from games.spender_duel import ai, engine

A, B = "alice", "bob"


def board(**cells):
    """A game whose board holds exactly the given tokens, `A` to move."""
    g = engine.new_game([A, B], names={A: "Alice", B: "Bob"}, seed=42)
    g["board"] = [None] * 25
    for cell, tok in cells.items():
        g["board"][int(cell[1:])] = tok
    g["turn"] = A
    return g


def takes(g, pid=A):
    return sorted(tuple(m["cells"]) for m in ai._legal(g, pid) if m["type"] == "take")


# ── dominated takes ──────────────────────────────────────────────────────────
def test_a_take_is_never_a_strict_subset_of_another():
    """The reported blunder: the bot took a lone white while a white+pearl line sat
    on the board. One extra token is worth ~0.018 to `_value` — at or below rollout
    noise — so the search could not tell the two apart and picked near-arbitrarily.
    Taking the subset is strictly dominated, so it never reaches the search at all.
    """
    g = board(c12="white", c13="pearl")
    assert takes(g) == [(12, 13)]


def test_maximal_line_is_the_only_survivor():
    g = board(c10="white", c11="blue", c12="red")
    assert takes(g) == [(10, 11, 12)]


def test_a_take_that_would_gift_a_privilege_does_not_dominate():
    """Three of a colour hands the OPPONENT a Privilege, so the 3-take is NOT strictly
    better than the 2-takes inside it — the search must still get to choose. This is
    the exception that makes "always take the most tokens" wrong as a rule.
    """
    g = board(c10="white", c11="white", c12="white")
    assert takes(g) == [(10, 11), (10, 11, 12), (11, 12)]
    # the singletons ARE still dominated: {10,11} takes more and gifts nothing
    assert (10,) not in takes(g)


def test_two_pearls_gift_so_the_singles_survive():
    g = board(c12="pearl", c13="pearl")
    assert takes(g) == [(12,), (12, 13), (13,)]


def test_gifting_only_shields_the_takes_that_avoid_the_gift():
    """pearl,pearl,gem — the subtle case. Surviving options are exactly:
      {10}        one pearl, no gift
      {11,12}     pearl+gem, no gift
      {10,11,12}  gifts, but maximal
    {11}/{12} lose to {11,12}; {10,11} already gifts, so the full line dominates it.
    """
    g = board(c10="pearl", c11="pearl", c12="red")
    assert takes(g) == [(10,), (10, 11, 12), (11, 12)]


def test_prune_leaves_the_engine_rules_untouched():
    """`_legal` is a SEARCH filter. Every move it drops is still legal to play — the
    human is never denied a take the bot declines to consider.
    """
    g = board(c12="white", c13="pearl")
    legal = {tuple(m["cells"]) for m in engine.legal_moves(g, A) if m["type"] == "take"}
    assert legal == {(12,), (13,), (12, 13)}
    for cells in legal:
        probe = board(c12="white", c13="pearl")
        assert engine.apply_move(probe, A, {"type": "take", "cells": list(cells)})[0]


def test_take_dominance_is_switchable_for_ab_measurement():
    """The A/B hook: `hard+nodom` must actually restore the unpruned branch set, or an
    arena comparing them measures nothing.
    """
    g = board(c12="white", c13="pearl")
    ai._local.take_dominance = False
    try:
        assert takes(g) == [(12,), (12, 13), (13,)]
    finally:
        del ai._local.take_dominance
    assert takes(g) == [(12, 13)], "must default back to pruned"


def test_choose_move_sets_the_flag_per_decision():
    """choose_move owns the flag. If a `take_dominance=False` decision leaked, every
    later search in that thread would silently run unpruned.
    """
    g = board(c12="white", c13="pearl")
    ai.choose_move(g, A, difficulty="normal", max_iters=8, time_limit=0.05,
                   take_dominance=False)
    assert ai._take_dominance() is False
    ai.choose_move(g, A, difficulty="normal", max_iters=8, time_limit=0.05)
    assert ai._take_dominance() is True


def test_the_prune_flag_does_not_leak_across_threads():
    """The server searches in a thread pool (run_in_executor), so one game's setting must
    never reach another's. A plain module global made this a live corruption risk the
    moment two values coexist; thread-local scoping is what rules it out.
    """
    import threading
    g = board(c12="white", c13="pearl")
    seen = {}

    def worker(name, dominance, barrier):
        ai.choose_move(g, A, difficulty="normal", max_iters=8, time_limit=0.05,
                       take_dominance=dominance)
        barrier.wait()                       # both threads have now set their value
        seen[name] = ai._take_dominance()    # ...each must still read its OWN

    barrier = threading.Barrier(2)
    ts = [threading.Thread(target=worker, args=(n, d, barrier))
          for n, d in (("on", True), ("off", False))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert seen == {"on": True, "off": False}
    assert ai._take_dominance() is True      # the main thread was never touched


def test_the_bot_actually_takes_the_free_token():
    """End to end, through the real search: given only white+pearl, every legal take is
    a take, so the pruned root has exactly one move and the bot cannot blunder it.
    """
    g = board(c12="white", c13="pearl")
    mv = ai.choose_move(g, A, difficulty="normal", max_iters=64, time_limit=0.3)
    assert mv["type"] == "take" and sorted(mv["cells"]) == [12, 13]


# ── the pre-existing prunes (regression cover) ───────────────────────────────
def test_skip_pending_is_pruned_but_never_to_empty():
    """Skipping an ability is never better than using it — but a prune that can strand
    the search with nothing to play makes the bot worse, not better (the CoC lesson).
    """
    g = board(c12="red")
    g["pending_pid"] = A
    g["pending_kind"] = "steal"
    g["pending"] = {"ctx": {"colors": ["red", "blue"], "via": None}}
    g["players"][B]["tokens"]["red"] = 2
    g["players"][B]["tokens"]["blue"] = 1
    assert any(m["type"] == "skip_pending" for m in engine.legal_moves(g, A))
    moves = ai._legal(g, A)
    assert moves, "never empty"
    assert all(m["type"] != "skip_pending" for m in moves)
    assert {m["color"] for m in moves} == {"red", "blue"}


def test_a_skip_that_is_the_only_option_is_kept():
    """`pruned or moves`: when skipping is all there is, the search must still get it
    rather than an empty move list.
    """
    g = board(c12="red")
    g["pending_pid"] = A
    g["pending_kind"] = "steal"
    g["pending"] = {"ctx": {"colors": [], "via": None}}
    assert ai._legal(g, A) == [{"type": "skip_pending"}]
