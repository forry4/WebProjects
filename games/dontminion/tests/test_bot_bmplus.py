"""Big Money+ tests — the three skills this rung adds over plain Big Money:
a terminal read off the board, the Colony rungs, and endgame technique.
"""

import random

from games.dontminion import bot, engine

A, B = "alice", "bob"
BMP = bot.BM_PLUS
K = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room",
     "Gardens", "Chapel", "Cellar", "Market"]


def fresh(seed=5, kingdom=K, exps=("base", "intrigue")):
    return engine.new_game([A, B], list(exps), seed=seed, kingdom=kingdom)


def in_buy(g, coins, buys=1):
    seat = g["seats"][A]
    seat["discard"] += seat["hand"]
    seat["hand"] = []
    ok, err = engine.apply_move(g, A, {"type": "end_phase"})
    assert ok, err
    g["coins"], g["buys"] = coins, buys
    return g


def buys(g, seed=1):
    return bot.choose(g, A, random.Random(seed), BMP)


# ── it reads a terminal off the board ────────────────────────────────────────

def test_it_buys_the_kingdoms_best_terminal():
    """The published Terminal-Draw-BM ranking, not the first Action it sees."""
    g = in_buy(fresh(kingdom=["Wharf", "Smithy"] + K[:8],
                     exps=("base", "intrigue", "seaside")), 5)
    assert buys(g) == {"type": "buy", "card": "Wharf"}


def test_a_board_with_no_terminal_still_plays_plain_big_money():
    g = in_buy(fresh(kingdom=["Village", "Festival", "Laboratory", "Market",
                             "Cellar", "Chapel", "Gardens", "Workshop",
                             "Harbinger", "Merchant"]), 5)
    assert buys(g) == {"type": "buy", "card": "Silver"}


# Smithy is the best terminal here on purpose: the default board has Witch,
# which outranks it and costs $5, so at $4 the bot correctly saves for the
# Witch instead and this rule would never be reached.
SMITHY_BOARD = ["Smithy", "Village", "Moat", "Throne Room", "Gardens",
                "Chapel", "Cellar", "Market", "Harbinger", "Merchant"]


def test_it_respects_the_terminal_budget():
    """<= 2 terminals, and the second only once the deck can absorb it."""
    g = in_buy(fresh(kingdom=SMITHY_BOARD), 4)
    assert buys(g) == {"type": "buy", "card": "Smithy"}       # the first one

    g = in_buy(fresh(seed=6, kingdom=SMITHY_BOARD), 4)
    g["seats"][A]["discard"] += ["Smithy"]
    assert buys(g) == {"type": "buy", "card": "Silver"}       # deck too small

    g = in_buy(fresh(seed=7, kingdom=SMITHY_BOARD), 4)
    g["seats"][A]["discard"] += ["Smithy"] + ["Silver"] * 6   # 17 cards owned
    assert buys(g) == {"type": "buy", "card": "Smithy"}       # now it fits

    g = in_buy(fresh(seed=8, kingdom=SMITHY_BOARD), 4)
    g["seats"][A]["discard"] += ["Smithy", "Smithy"] + ["Silver"] * 8
    assert buys(g) == {"type": "buy", "card": "Silver"}       # capped at two


def test_it_saves_for_a_better_terminal_rather_than_taking_a_worse_one():
    """With Witch ($5, rank 92) on the board, $4 buys a Silver to reach it —
    not the affordable Smithy. Diluting a money deck with a second KIND of
    terminal is the "too many terminals" mistake the corpus names."""
    g = in_buy(fresh(), 4)                  # default board has both
    assert buys(g) == {"type": "buy", "card": "Silver"}
    g = in_buy(fresh(seed=9), 5)
    assert buys(g) == {"type": "buy", "card": "Witch"}


def test_it_plays_its_actions_villages_first():
    g = fresh()
    g["seats"][A]["hand"] = ["Smithy", "Village", "Copper"]
    mv = buys(g)
    assert mv == {"type": "play_action", "card": "Village"}, mv


def test_it_plays_the_terminal_when_that_is_all_there_is():
    g = fresh()
    g["seats"][A]["hand"] = ["Smithy", "Copper", "Copper"]
    assert buys(g) == {"type": "play_action", "card": "Smithy"}


# ── Colony games: the gap plain Big Money leaves open ────────────────────────

def _colony_game(seed=5, coins=11):
    for s in range(seed, seed + 60):
        g = engine.new_game([A, B], ["base", "prosperity"], seed=s,
                            kingdom=["Peddler", "Monument", "Bishop", "City",
                                     "Rabble", "Vault", "Smithy", "Village",
                                     "Market", "Cellar"])
        if g.get("colony"):
            return in_buy(g, coins)
    raise AssertionError("no colony game in 60 seeds — setup rule changed?")


def test_it_buys_colonies_and_platinum_where_big_money_does_not():
    g = _colony_game(coins=11)
    assert buys(g) == {"type": "buy", "card": "Colony"}
    assert bot.choose(g, A, random.Random(1), bot.BIG_MONEY) \
        == {"type": "buy", "card": "Province"}          # the documented gap

    g = _colony_game(coins=9)
    assert buys(g) == {"type": "buy", "card": "Platinum"}


# ── endgame technique ────────────────────────────────────────────────────────

def test_it_takes_a_winning_game_ending_buy():
    g = in_buy(fresh(), 8)
    g["supply"]["Province"] = 1
    g["vp_tokens"][A] = 20
    engine._post_move(g)
    assert buys(g) == {"type": "buy", "card": "Province"}


def test_it_will_not_end_the_game_while_losing():
    g = in_buy(fresh(), 8)
    g["supply"]["Province"] = 1
    g["vp_tokens"][B] = 20
    engine._post_move(g)
    mv = buys(g)
    assert mv != {"type": "buy", "card": "Province"}


def test_it_honours_the_penultimate_province_rule():
    g = in_buy(fresh(), 8)
    g["supply"]["Province"] = 2
    g["vp_tokens"][B] = 2                   # trailing by 2: a Duchy leads
    engine._post_move(g)
    assert buys(g) == {"type": "buy", "card": "Duchy"}


# ── the finisher contract ────────────────────────────────────────────────────

def test_full_games_terminate_on_every_expansion():
    for seed, exps in ((41, ["base"]), (42, ["intrigue"]), (43, ["seaside"]),
                       (44, ["prosperity"]), (45, ["hinterlands"]),
                       (46, ["base", "intrigue", "seaside", "prosperity",
                             "hinterlands"])):
        g = engine.new_game([A, B], exps, seed=seed)
        rng = random.Random(seed)
        for _ in range(20000):
            if g["over"]:
                break
            pid = g["pending_pid"] or g["turn"]
            ok, err = engine.apply_move(g, pid, bot.choose(g, pid, rng, BMP))
            assert ok, f"{exps} seed {seed}: {err}"
        assert g["over"] and g["winners"], f"{exps} seed {seed} did not finish"


def test_multi_bot_rooms_still_finish():
    for players in ([A, B, "carol"], [A, B, "carol", "dave"]):
        g = engine.new_game(players, ["base", "intrigue"], seed=51)
        rng = random.Random(51)
        for _ in range(20000):
            if g["over"]:
                break
            pid = g["pending_pid"] or g["turn"]
            ok, err = engine.apply_move(g, pid, bot.choose(g, pid, rng, BMP))
            assert ok, err
        assert g["over"]


def test_bmplus_beats_big_money():
    """The ship gate: a rung must beat the one below it. Measured at 0.77 over
    60 CRN pairs; this is the cheap deterministic version of that."""
    from games.dontminion.tools import bot_arena
    res = bot_arena.duel(BMP, bot.BIG_MONEY, 12, ["base", "intrigue"],
                         quiet=True)
    assert res["win_rate"] >= 0.60, f"only {res['win_rate']:.3f} vs Big Money"


def test_the_arena_mirror_is_exactly_even():
    """If this drifts off 0.5 the harness is leaking state between games and
    every number it has ever printed is suspect."""
    from games.dontminion.tools import bot_arena
    res = bot_arena.duel(BMP, BMP, 6, ["base"], quiet=True)
    assert res["win_rate"] == 0.5, f"mirror read {res['win_rate']!r}"
