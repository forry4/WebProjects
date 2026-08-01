"""Bot tests. Random-legal: full games terminate, foreign pendings are answered,
and the anti-stall bias holds. Big Money: the buy ladder rung by rung, plus the
same finisher guarantees.

Kingdom is pinned to the six kernel exemplars — the only cards guaranteed
implemented independent of the batch WPs. (Full-roster coverage lives in the
forced-kingdom soak sweeps once all batches land.)
"""

import random

from games.dontminion import bot, engine

A, B, C, D = "alice", "bob", "carol", "dave"
K7 = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room", "Gardens"]
BM = bot.BIG_MONEY


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


# --- Big Money -----------------------------------------------------------------

def in_buy(coins, provinces=8, owned=("Gold",), buys=1, seed=5):
    """A's buy phase, staged: empty hand (nothing left to play), `coins` in the
    pool, `provinces` left in the supply, and `owned` sitting in the discard on
    top of the opening deck (the $8 exception reads the whole deck)."""
    g = fresh(seed=seed)
    give_hand(g, A, [])
    assert engine.apply_move(g, A, {"type": "end_phase"})[0]
    assert g["phase"] == "buy"
    g["coins"] = coins
    g["buys"] = buys
    g["supply"]["Province"] = provinces
    g["seats"][A]["discard"] += list(owned)
    return g


def test_big_money_buy_ladder():
    # (coins, provinces left) -> the pile it buys, None = buys nothing
    table = [
        # $8 and up is always the Province — there is never a second buy to
        # spend the change on (the bot buys no Action, so nothing grants one).
        (13, 8, "Province"), (12, 8, "Province"), (10, 8, "Province"),
        (9, 8, "Province"), (8, 8, "Province"),          # not early: owns a Gold
        (7, 8, "Gold"), (6, 8, "Gold"),
        (7, 5, "Gold"), (6, 5, "Gold"),                  # 5 provinces isn't near enough
        (7, 4, "Duchy"), (6, 4, "Duchy"),                # 4 or fewer: green instead
        (5, 8, "Silver"), (5, 6, "Silver"), (5, 5, "Duchy"), (5, 1, "Duchy"),
        (4, 8, "Silver"), (3, 8, "Silver"), (4, 3, "Silver"),
        (4, 2, "Estate"), (3, 2, "Estate"),
        (2, 8, None), (2, 4, None), (2, 3, "Estate"), (2, 1, "Estate"),
        (1, 1, None), (0, 8, None),
    ]
    for coins, provinces, want in table:
        g = in_buy(coins, provinces)
        mv = bot.choose(g, A, random.Random(1), BM)
        expect = {"type": "buy", "card": want} if want else {"type": "end_phase"}
        assert mv == expect, f"${coins}, {provinces} Provinces -> {mv}"


def test_big_money_takes_gold_over_province_at_eight_only_when_early():
    # opening deck: no Gold, no Silver
    assert bot.choose(in_buy(8, owned=()), A, random.Random(1), BM) \
        == {"type": "buy", "card": "Gold"}
    # 4 Silvers is still "fewer than 5"
    assert bot.choose(in_buy(8, owned=("Silver",) * 4), A, random.Random(1), BM) \
        == {"type": "buy", "card": "Gold"}
    # 5 Silvers, or any Gold at all, and it's no longer early
    assert bot.choose(in_buy(8, owned=("Silver",) * 5), A, random.Random(1), BM) \
        == {"type": "buy", "card": "Province"}
    assert bot.choose(in_buy(8, owned=("Gold",)), A, random.Random(1), BM) \
        == {"type": "buy", "card": "Province"}
    # the exception is written against $8 — $9 always buys the Province
    assert bot.choose(in_buy(9, owned=()), A, random.Random(1), BM) \
        == {"type": "buy", "card": "Province"}
    # a Silver anywhere but the deck still counts as owned
    g = in_buy(8, owned=("Silver",) * 4)
    g["seats"][A]["in_play"].append("Silver")
    assert bot.choose(g, A, random.Random(1), BM) == {"type": "buy", "card": "Province"}


def test_big_money_spends_its_one_buy_on_the_province():
    """A big hand is one Province, full stop. The bot never gets a second buy
    (it buys no Action, so nothing in its deck grants one), so no rung plans a
    follow-up — and if a buy somehow existed, the leftover just re-reads the
    ladder rather than following a stale plan."""
    for coins in (10, 11, 12):
        g = in_buy(coins, provinces=8, buys=2)
        assert engine.apply_move(g, A, bot.choose(g, A, random.Random(1), BM))[0]
        assert g["seats"][A]["discard"][-1] == "Province"
        assert g["buys"] == 1 and g["coins"] == coins - 8
        assert bot.choose(g, A, random.Random(1), BM) \
            == ({"type": "buy", "card": "Silver"} if coins > 10 else {"type": "end_phase"})
    # and with the ONE buy it really has, the turn ends there
    g = in_buy(12, provinces=8)
    assert engine.apply_move(g, A, bot.choose(g, A, random.Random(1), BM))[0]
    assert bot.choose(g, A, random.Random(1), BM) == {"type": "end_phase"}


def test_big_money_plays_every_treasure_before_it_buys():
    g = fresh()
    give_hand(g, A, ["Gold", "Copper", "Estate"])
    assert engine.apply_move(g, A, {"type": "end_phase"})[0]
    mv = bot.choose(g, A, random.Random(1), BM)
    assert mv == {"type": "play_all_treasures"}
    assert engine.apply_move(g, A, mv)[0]
    assert g["coins"] == 4
    assert bot.choose(g, A, random.Random(1), BM) == {"type": "buy", "card": "Silver"}


def test_big_money_plays_no_actions():
    g = fresh()
    give_hand(g, A, ["Smithy", "Village", "Copper"])
    assert bot.choose(g, A, random.Random(1), BM) == {"type": "end_phase"}


def test_big_money_answers_a_foreign_pending():
    g = fresh()
    give_hand(g, A, ["Militia"])
    give_hand(g, B, ["Copper"] * 5)
    assert engine.apply_move(g, A, {"type": "play_action", "card": "Militia"})[0]
    mv = bot.choose(g, B, random.Random(1), BM)
    assert mv["type"] == "decision"
    assert engine.apply_move(g, B, mv)[0]
    assert g["pending_pid"] is None and len(g["seats"][B]["hand"]) == 3


def _run_game(g, difficulties, seed):
    """Play g out with each seat on its own tier. Returns the final vp map."""
    rng = random.Random(seed)
    for _ in range(6000):
        if g["over"]:
            break
        pid = g["pending_pid"] or g["turn"]
        ok, err = engine.apply_move(g, pid, bot.choose(g, pid, rng, difficulties[pid]))
        assert ok, err
    assert g["over"] and g["winners"]
    return dict(g["vp"])


def test_big_money_full_games_terminate_and_actually_green():
    for players, seed in (([A, B], 31), ([A, B, C], 32), ([A, B, C, D], 33)):
        g = engine.new_game(players, ["base"], seed=seed, kingdom=K7)
        vp = _run_game(g, {p: BM for p in players}, seed)
        assert max(vp.values()) >= 12          # not a Copper-shuffling stalemate
        assert g["supply"]["Province"] == 0    # ended ON the Provinces


def test_big_money_beats_the_random_bot():
    """Deterministic (fixed seeds, fixed rng), so this pins a real strength gap
    rather than sampling one — the whole point of the tier."""
    wins = 0
    for seed in (41, 42, 43, 44, 45):
        g = engine.new_game([A, B], ["base"], seed=seed, kingdom=K7)
        vp = _run_game(g, {A: BM, B: "normal"}, seed)
        wins += vp[A] > vp[B]
    assert wins == 5, f"Big Money won {wins}/5 against random-legal"


def test_war_chest_naming_denies_a_gainable_card_not_a_platinum():
    """The bot naming for someone else's War Chest must name a card they could
    ACTUALLY gain (cost <= $5) — naming a Platinum ($9) they can't take wastes
    the deny. Regression: the policy used to pick the highest gain_value pile."""
    import random
    from games.dontminion import bot_decisions
    kingdom = ["War Chest", "Village", "Smithy", "Market", "Festival",
               "Laboratory", "Grand Market", "Witch", "Chapel", "Cellar"]
    g = engine.new_game([A, B], ["base", "prosperity"], seed=2, kingdom=kingdom)
    g["colony"] = True
    g["supply"].setdefault("Platinum", 12)
    g["supply"].setdefault("Colony", 8)
    seat = g["seats"][g["turn"]]
    seat["hand"].append("War Chest")
    g["phase"] = "buy"
    assert engine.apply_move(g, g["turn"], {"type": "play_treasure", "card": "War Chest"})[0]
    namer = g["pending_pid"]
    assert "Platinum" in g["pending"][-1]["constraint"]["cards"]     # it's on offer
    ans = bot_decisions.decide(g, namer, random.Random(0))
    assert engine.cost_le(g, ans["card"], 5)                         # names something gainable
    assert ans["card"] != "Platinum"
