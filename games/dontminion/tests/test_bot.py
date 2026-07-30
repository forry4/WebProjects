"""Random-legal bot tests: full games terminate, foreign pendings are answered,
and the anti-stall bias holds.

Kingdom is pinned to the six kernel exemplars — the only cards guaranteed
implemented independent of the batch WPs. (Full-roster coverage lives in the
forced-kingdom soak sweeps once all batches land.)
"""

import random

from games.dontminion import bot, engine

A, B, C, D = "alice", "bob", "carol", "dave"
K7 = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room", "Gardens"]


def fresh(players=(A, B), seed=5):
    return engine.new_game(list(players), ["base"], seed=seed, kingdom=K7)


def give_hand(g, pid, cards):
    g["seats"][pid]["hand"] = list(cards)


def test_bot_full_games_terminate():
    for players, seed in (([A, B], 21), ([A, B, C], 22), ([A, B, C, D], 23)):
        g = engine.new_game(players, ["base"], seed=seed, kingdom=K7)
        rng = random.Random(seed)
        for _ in range(6000):
            if g["over"]:
                break
            pid = g["pending_pid"] or g["turn"]
            ok, err = engine.apply_move(g, pid, bot.choose(g, pid, rng))
            assert ok, err
        assert g["over"] and g["winners"]


def test_bot_answers_foreign_pending():
    g = fresh()
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Copper"] * 5)
    assert engine.apply_move(g, A, {"type": "play_action", "card": "Militia"})[0]
    assert g["pending_pid"] == B
    mv = bot.choose(g, B, random.Random(1))
    assert mv["type"] == "decision"
    assert engine.apply_move(g, B, mv)[0]
    assert g["pending_pid"] is None and len(g["seats"][B]["hand"]) == 3


def test_bot_plays_treasures_then_buys_then_ends():
    g = fresh()
    give_hand(g, A, ["Gold", "Copper"])
    assert engine.apply_move(g, A, {"type": "end_phase"})[0]
    mv = bot.choose(g, A, random.Random(2))
    assert mv == {"type": "play_all_treasures"}
    assert engine.apply_move(g, A, mv)[0]
    mv = bot.choose(g, A, random.Random(3))
    assert mv["type"] == "buy"
    g["buys"] = 0
    assert bot.choose(g, A, random.Random(4)) == {"type": "end_phase"}


def test_play_turn_stops_at_foreign_pending():
    g = fresh()
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Copper"] * 5)
    bot.play_turn(g, A, random.Random(9))
    assert g["pending_pid"] == B          # stopped the moment B must act
