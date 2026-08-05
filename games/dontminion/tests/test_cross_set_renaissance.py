"""Cross-set tests for phase 9 (RENAISSANCE) — the combos where the new
mechanics meet the nine already-shipped sets.

Step 6 of the per-phase playbook, and it is not optional: a card batch can only
ever be as correct as the precedent it copies, so per-set tests structurally
cannot find the class of bug where a NEW rule meets an OLD card. Everything
here therefore builds a board that mixes Renaissance with at least one shipped
expansion and drives real moves.

Every test names the rule it encodes and the compendium ruling it comes from
(Knutsen v11.1; page numbers are the PDF's printed page, one higher than the
0-based index).

HEADLINE FINDINGS (see the docstrings, each marked FOUND BUG):

  * **Improve x Peddler** — "cost reductions for this turn, or from cards in
    play, still apply in Clean-up (EXCEPT Peddler's cost reduction)" (Improve,
    p. 108). `game["phase"]` never leaves `"buy"` during Clean-up, so
    Peddler's `DYN_COSTS` discount is still live when Improve reads costs and
    Improve can "remodel" a $3 into a Peddler.
"""

import copy
import json
import random

from games.dontminion import cards, effects, engine

A, B, C = "alice", "bob", "carol"


# --- fixtures ----------------------------------------------------------------

def fresh(kingdom, expansions, landscapes=(), players=(A, B), seed=7):
    return engine.new_game(list(players), list(expansions), seed=seed,
                           kingdom=list(kingdom), landscapes=list(landscapes))


def mv(g, pid, m):
    return engine.apply_move(g, pid, m)


def decide(g, pid, **payload):
    return engine.apply_move(g, pid, {"type": "decision", **payload})


def frame(g):
    return g["pending"][-1] if g["pending"] else None


def opt_ids(g):
    return [o["id"] for o in frame(g)["constraint"]["options"]]


def give_hand(g, pid, cards_):
    g["seats"][pid]["hand"] = list(cards_)


def give_deck(g, pid, cards_):
    g["seats"][pid]["deck"] = list(cards_)


def give_cube(g, name, pid):
    """Buy a Project without paying for it — the cube IS `bought_by`."""
    g["landscapes"][name]["bought_by"].append(pid)


def events(g, name):
    return [e for e in g["log"] if e.get("event") == name]


def play(g, pid, card):
    ok, err = mv(g, pid, {"type": "play_action", "card": card})
    assert ok, err


def to_buy(g, pid):
    if g["phase"] == "action" and not g["pending"]:
        ok, err = mv(g, pid, {"type": "end_phase"})
        assert ok, err


def end_turn(g, pid):
    to_buy(g, pid)
    if g["over"] or g["pending"]:
        return
    ok, err = mv(g, pid, {"type": "end_phase"})
    assert ok, err


def drain(g, rng=None, cap=200):
    """Answer every open decision with a uniform valid payload."""
    rng = rng or random.Random(3)
    for _ in range(cap):
        pid = g["pending_pid"]
        if pid is None:
            return
        ok, err = decide(g, pid, **engine.sample_decision(g, pid, rng))
        assert ok, err
    raise AssertionError("decisions never drained")


def gain(g, pid, pile, **kw):
    out = engine.gain(g, pid, pile, **kw)
    engine._drive(g)
    return out


def pass_turn_to(g, pid):
    """End turns (answering nothing but auto frames) until it is pid's turn."""
    for _ in range(12):
        if g["turn"] == pid and g["phase"] == "action":
            return
        cur = g["turn"]
        end_turn(g, cur)
        drain(g)
    raise AssertionError("never reached %s" % pid)
