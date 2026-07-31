"""Decision-policy tests.

Two kinds. The named ones pin the specific plays the strategy corpus is
explicit about (keep the money against a Militia, take the discard over the
Curse, trash junk not payload, stop trashing once green is points). The soak
pins the CONTRACT: `decide` must answer every frame the engine can push with a
payload `apply_move` accepts, because it sits behind the scheduler's guaranteed
turn-finisher.
"""

import random

import pytest

from games.dontminion import bot, bot_decisions as D, engine

A, B = "alice", "bob"
K = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room",
     "Gardens", "Chapel", "Cellar", "Masquerade"]


def fresh(seed=5, kingdom=K, exps=("base", "intrigue")):
    return engine.new_game([A, B], list(exps), seed=seed, kingdom=kingdom)


def hand(g, pid, cards):
    g["seats"][pid]["hand"] = list(cards)


def play(g, pid, card):
    ok, err = engine.apply_move(g, pid, {"type": "play_action", "card": card})
    assert ok, err


# ── discard attacks: keep the buying power ───────────────────────────────────

def test_militia_victim_keeps_the_money_and_discards_the_dead_cards():
    g = fresh()
    hand(g, A, ["Militia"])
    hand(g, B, ["Gold", "Silver", "Estate", "Curse", "Copper"])
    play(g, A, "Militia")
    got = set(D.decide(g, B, random.Random(1))["cards"])
    assert got == {"Estate", "Curse"}, f"discarded {got}, not the dead cards"


def test_militia_victim_does_not_keep_two_terminals_over_the_money():
    """The collision discount. Ranking cards independently keeps both Smithies
    (25 each) over a Gold (31) once the hand is cut to three."""
    g = fresh(6)
    hand(g, A, ["Militia"])
    hand(g, B, ["Smithy", "Smithy", "Gold", "Estate", "Copper"])
    play(g, A, "Militia")
    kept = list(g["seats"][B]["hand"])
    for c in D.decide(g, B, random.Random(1))["cards"]:
        kept.remove(c)
    assert "Gold" in kept
    assert kept.count("Smithy") <= 1, f"kept two dead terminals: {kept}"


def test_torturer_victim_takes_the_discard_not_the_curse():
    """The Level-10 rule: an early Curse costs ~4-5 future draws; two discards
    cost two. Pinned because the uniform sampler took the Curse half the time."""
    g = fresh(7, kingdom=["Torturer"] + K[:9])
    hand(g, A, ["Torturer"])
    hand(g, B, ["Copper", "Copper", "Estate", "Estate", "Silver"])
    play(g, A, "Torturer")
    assert g["pending_pid"] == B
    assert D.decide(g, B, random.Random(1))["ids"] == ["discard"]


# ── trashing: junk only, and it knows when to stop ───────────────────────────

def test_chapel_trashes_the_junk_and_never_the_payload():
    g = fresh(8)
    hand(g, A, ["Chapel", "Curse", "Estate", "Gold", "Copper"])
    play(g, A, "Chapel")
    got = D.decide(g, A, random.Random(1))["cards"]
    assert "Gold" not in got
    assert "Curse" in got and "Estate" in got


def test_chapel_protects_the_coppers_until_real_money_exists():
    """"The Trasher" is a named losing archetype: a deck thinned below its
    money can no longer reach $8."""
    g = fresh(9)
    hand(g, A, ["Chapel", "Curse", "Copper", "Copper", "Copper"])
    play(g, A, "Chapel")
    assert D.decide(g, A, random.Random(1))["cards"] == ["Curse"]

    g = fresh(10)
    g["seats"][A]["discard"] += ["Gold", "Silver", "Silver"]
    hand(g, A, ["Chapel", "Curse", "Copper", "Copper", "Copper"])
    play(g, A, "Chapel")
    got = D.decide(g, A, random.Random(1))["cards"]
    assert got.count("Copper") == 3, f"real money in the deck, still kept {got}"


def test_trashing_stops_treating_green_as_junk_once_the_game_is_ending():
    g = fresh(11)
    g["supply"]["Province"] = 3
    hand(g, A, ["Chapel", "Curse", "Estate", "Estate", "Gold"])
    play(g, A, "Chapel")
    got = D.decide(g, A, random.Random(1))["cards"]
    assert got == ["Curse"], f"trashed points in the endgame: {got}"


def test_the_ending_check_is_not_fooled_by_a_missing_colony_pile():
    """`supply.get("Colony", 0) <= 3` reads True in every non-Prosperity game.
    That flipped Estates from junk to treasure on turn one — the bot refused to
    trash them and gain_value wanted more."""
    g = fresh(12)
    assert "Colony" not in g["supply"]
    assert not D._ending(g)
    assert D.gain_value(g, A, "Estate") < 0


# ── the rest of the policy surface ───────────────────────────────────────────

def test_cellar_discards_exactly_the_dead_cards():
    g = fresh(13)
    hand(g, A, ["Cellar", "Estate", "Curse", "Gold", "Copper"])
    play(g, A, "Cellar")
    got = set(D.decide(g, A, random.Random(1))["cards"])
    assert got == {"Estate", "Curse"}


def test_masquerade_passes_the_worst_card():
    g = fresh(14)
    hand(g, A, ["Masquerade", "Curse", "Gold", "Silver", "Estate"])
    hand(g, B, ["Copper"] * 5)
    play(g, A, "Masquerade")
    frame = g["pending"][-1]
    assert frame["constraint"]["purpose"] == "pass"
    assert D.decide(g, frame["pid"], random.Random(1))["cards"] == ["Curse"]


def test_the_attack_window_always_reacts():
    """Every reaction we ship is immunity or free value; declining is never
    right, and the sampler declined half the time."""
    g = fresh(15)
    hand(g, A, ["Militia"])
    hand(g, B, ["Moat", "Gold", "Gold", "Gold", "Gold"])
    play(g, A, "Militia")
    assert g["pending_pid"] == B
    assert D.decide(g, B, random.Random(1))["ids"] == ["react:Moat"]


def test_vassal_plays_the_free_action():
    g = fresh(16, kingdom=["Vassal"] + K[:9])
    g["seats"][A]["deck"] = ["Village"] + g["seats"][A]["deck"]
    hand(g, A, ["Vassal"])
    play(g, A, "Vassal")
    if g["pending_pid"] == A and g["pending"][-1]["card"] == "Vassal":
        assert D.decide(g, A, random.Random(1))["ids"] == ["play"]


def test_courtier_reveals_the_card_with_the_most_types():
    """Courtier pays per TYPE, so revealing a dual-type card is the play."""
    g = fresh(17, kingdom=["Courtier", "Mill"] + K[:8])
    hand(g, A, ["Courtier", "Copper", "Mill"])
    play(g, A, "Courtier")
    assert D.decide(g, A, random.Random(1))["cards"] == ["Mill"]


def test_baron_takes_the_four_coins_over_gaining_a_junk_estate():
    g = fresh(18, kingdom=["Baron"] + K[:9])
    hand(g, A, ["Baron", "Estate"])
    play(g, A, "Baron")
    assert D.decide(g, A, random.Random(1))["ids"] == ["discard"]
    # with no Estate to discard the engine never opens the choice at all —
    # it gains one directly, so there is no policy branch to test here.
    g = fresh(19, kingdom=["Baron"] + K[:9])
    hand(g, A, ["Baron", "Copper"])
    play(g, A, "Baron")
    assert g["pending_pid"] is None


# ── the contract ─────────────────────────────────────────────────────────────

def _soak(seed, kingdom=None):
    """Play a full game answering every frame by policy. Returns the count."""
    exps = ["base", "intrigue", "seaside", "prosperity", "hinterlands"]
    g = engine.new_game([A, B], exps, seed=seed, kingdom=kingdom)
    rng = random.Random(seed)
    answered = 0
    for _ in range(20000):
        if g["over"]:
            break
        pid = g["pending_pid"] or g["turn"]
        if g["pending_pid"] == pid:
            mv = {"type": "decision", **D.decide(g, pid, rng)}
            answered += 1
        else:
            mv = bot.choose_random(g, pid, rng)
        ok, err = engine.apply_move(g, pid, mv)
        assert ok, f"policy produced an illegal move {mv}: {err}"
    assert g["over"], f"game {seed} did not finish"
    return answered


# A board built to push frames of every kind: mass trash, sifters, ordering,
# naming, gain choices, an attack of each family, and a would-gain reaction.
DENSE = ["Chapel", "Militia", "Witch", "Torturer", "Masquerade", "Sentry",
         "Wishing Well", "Remodel", "Watchtower", "Vault"]


@pytest.mark.parametrize("seed", range(6))
def test_every_policy_answer_is_a_legal_move_on_a_decision_dense_board(seed):
    """The bar is high here BECAUSE the kingdom guarantees the frames exist —
    on a random board the count is board-dependent (one seed produced 18), and
    a threshold tuned to survive that would stop proving anything."""
    assert _soak(2000 + seed, kingdom=DENSE) > 40


@pytest.mark.parametrize("seed", range(6))
def test_every_policy_answer_is_a_legal_move(seed):
    """The turn-finisher contract, soaked over full games on the whole roster.

    A policy that returns an impossible payload would be REJECTED by
    apply_move, and the room scheduler would spin on it — the failure mode the
    manual-treasure livelock already cost two live prod games.

    BOTH seats run the random-legal bot's move selection: it buys and plays
    every card on the board, which is what actually pushes the long tail of
    frames. Driving this with two Big Money seats proves nothing — Big Money
    plays no Actions, so the pair never plays an Attack and `answered` is 0
    (this soak caught exactly that in its first version).
    """
    assert _soak(1000 + seed) > 0
