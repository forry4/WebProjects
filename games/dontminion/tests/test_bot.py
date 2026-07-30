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


def test_a_hand_of_only_manual_treasures_does_not_livelock():
    """Found by replaying real prod saves. play_all_treasures SKIPS the
    interactive treasures (War Chest/Anvil), but legal_moves offered it for a
    hand holding nothing else and the handler then no-op'd with ok=True — and
    the bot prefers that move unconditionally. Two live prod games spun the
    scheduler's entire iteration cap on it, ~4000 no-op moves in the replay."""
    manual = sorted(engine.manual_treasures())
    assert manual, "registry empty — this test would prove nothing"
    card = manual[0]
    g = engine.new_game([A, B], ["base", "prosperity"], seed=7,
                        kingdom=[card] + ["Smithy", "Village", "Moat", "Militia",
                                          "Witch", "Throne Room", "Gardens",
                                          "Market", "Cellar"])
    assert engine.apply_move(g, A, {"type": "end_phase"})[0]
    give_hand(g, A, [card])

    moves = engine.legal_moves(g, A)
    assert {"type": "play_all_treasures"} not in moves      # it would do nothing
    ok, err = engine.apply_move(g, A, {"type": "play_all_treasures"})
    assert not ok and "autoplay" in err                     # and it's rejected

    # the bot plays it individually instead of looping / ending on unspent coins
    mv = bot.choose(g, A, random.Random(1))
    assert mv == {"type": "play_treasure", "card": card}

    # a mixed hand still autoplays, leaving only the manual one behind
    give_hand(g, A, [card, "Copper", "Silver"])
    assert {"type": "play_all_treasures"} in engine.legal_moves(g, A)
    assert engine.apply_move(g, A, {"type": "play_all_treasures"})[0]
    assert g["seats"][A]["hand"] == [card]


def test_play_turn_stops_at_foreign_pending():
    g = fresh()
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Copper"] * 5)
    bot.play_turn(g, A, random.Random(9))
    assert g["pending_pid"] == B          # stopped the moment B must act
