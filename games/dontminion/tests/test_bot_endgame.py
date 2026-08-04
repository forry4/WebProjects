"""Endgame-module tests — the Penultimate Province Rule and pile control.

Each case is one of the rules the strategy corpus states explicitly, including
the exceptions: PPR is only interesting BECAUSE of when it doesn't apply.
"""

from games.dontminion import bot_endgame as E, engine

A, B = "alice", "bob"
K = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room",
     "Gardens", "Chapel", "Cellar", "Market"]


def fresh(seed=5, kingdom=K, exps=("base", "intrigue")):
    return engine.new_game([A, B], list(exps), seed=seed, kingdom=kingdom)


def board(provinces=8, coins=8, lead=0, turns=(5, 5), seed=5):
    """A's buy phase with an EXACT score difference.

    `lead` is A's margin, applied through VP tokens rather than by stuffing
    green into a discard pile: both seats start with 3 Estates, so a fixture
    that edits zones has to keep the baseline straight, and the first version
    of this helper emptied A's hand (deleting whatever Estates were in it) and
    silently shifted every score it was trying to control.
    """
    g = fresh(seed)
    ok, err = engine.apply_move(g, A, {"type": "end_phase"})
    assert ok, err
    # park the hand in the discard so there is nothing left to play, WITHOUT
    # destroying cards (which would move the score)
    seat = g["seats"][A]
    seat["discard"] += seat["hand"]
    seat["hand"] = []
    g["coins"] = coins
    g["supply"]["Province"] = provinces
    if lead >= 0:
        g["vp_tokens"][A] = lead
    else:
        g["vp_tokens"][B] = -lead
    g["seats"][A]["turns_taken"], g["seats"][B]["turns_taken"] = turns
    engine._post_move(g)
    assert g["vp"][A] - g["vp"][B] == lead, "fixture failed to set the score"
    return g


# ── take the win ─────────────────────────────────────────────────────────────

def test_a_buy_that_ends_the_game_while_ahead_is_taken_immediately():
    """The most emphatic rule in the level-30-to-40 threads: no style points,
    no comeback window."""
    g = board(provinces=1, coins=8, lead=15)
    assert E.override(g, A, "Gold") == "Province"


def test_the_last_province_is_refused_when_it_would_lose():
    """Ending the game while behind hands over the win — buy anything else."""
    g = board(provinces=1, coins=8, lead=-18)
    got = E.override(g, A, "Province")
    assert got != "Province"
    assert got is None or not E.ends_the_game(g, got)


def test_a_tied_score_counts_as_winning_when_we_took_fewer_turns():
    """Dominion breaks a VP tie for the player with FEWER turns, so a tie is a
    win for whoever is behind on turns — the PPR page is explicit that this
    changes the endgame decision by seat.

    Tested through a PILE-OUT rather than a Province: buying the last Province
    adds 6 points, so it wins on score whatever the turn counts say, and the
    tiebreak would never be consulted. Emptying a third pile with a cheap
    Action ends the game leaving the scores exactly level, which is the only
    shape where the tiebreak decides anything.
    """
    def piled_out(turns):
        g = board(provinces=6, coins=2, lead=0, turns=turns)
        g["supply"]["Village"] = 0
        g["supply"]["Smithy"] = 0
        g["supply"]["Moat"] = 1             # cost $2 — the third pile
        return g

    g = piled_out((4, 5))                   # fewer turns: the tie is ours
    assert E.ends_the_game(g, "Moat")
    assert E.override(g, A, "Silver") == "Moat"

    g = piled_out((5, 4))                   # more turns: the tie is theirs
    assert E.override(g, A, "Moat") != "Moat"


# ── the Penultimate Province Rule ────────────────────────────────────────────

def test_ppr_blocks_the_penultimate_province_while_trailing():
    g = board(provinces=2, coins=8, lead=-2)
    assert E.ppr_blocks(g, A, "Province")
    assert E.override(g, A, "Province") == "Duchy"


def test_ppr_does_not_block_when_ahead_or_level():
    g = board(provinces=2, coins=8, lead=6)
    assert not E.ppr_blocks(g, A, "Province")
    # tied AND fewer turns taken: the tiebreak makes it a win
    g = board(provinces=2, coins=8, turns=(4, 5))
    assert not E.ppr_blocks(g, A, "Province")


def test_ppr_does_not_block_when_a_duchy_cannot_take_the_lead():
    """Wiki exception: if the lesser green card only ties (or still trails),
    take the Province — you need both remaining ones anyway."""
    g = board(provinces=2, coins=8, lead=-12)
    assert not E.ppr_blocks(g, A, "Province")


def test_ppr_does_not_block_when_nothing_lesser_is_affordable():
    g = board(provinces=2, coins=8, lead=-2)
    for pile in ("Duchy", "Estate", "Gardens"):
        g["supply"][pile] = 0
    assert not E.ppr_blocks(g, A, "Province")


def test_ppr_only_looks_at_the_penultimate_copy():
    g = board(provinces=5, coins=8, lead=-2)
    assert not E.ppr_blocks(g, A, "Province")
    g = board(provinces=1, coins=8, lead=-2)
    assert not E.ppr_blocks(g, A, "Province")      # the LAST one is rule 1/2


# ── pile control ─────────────────────────────────────────────────────────────

def test_two_low_piles_turn_a_money_buy_into_a_duchy():
    """The level-40 rule: when two piles run low, mass-buying Duchies is
    strong, because the game can end under you at any moment."""
    g = board(provinces=6, coins=6)
    g["supply"]["Village"] = 1
    g["supply"]["Smithy"] = 0
    assert E.override(g, A, "Gold") == "Duchy"


def test_a_healthy_board_leaves_the_plan_alone():
    g = board(provinces=8, coins=6)
    assert E.override(g, A, "Gold") == "Gold"


def test_ends_the_game_reads_all_three_conditions():
    g = board(provinces=1)
    assert E.ends_the_game(g, "Province")
    g = board(provinces=4)
    assert not E.ends_the_game(g, "Province")
    g["supply"]["Village"] = 0
    g["supply"]["Smithy"] = 0
    g["supply"]["Moat"] = 1
    assert E.ends_the_game(g, "Moat")          # the third empty pile
    g["supply"]["Moat"] = 2
    assert not E.ends_the_game(g, "Moat")


def test_opponent_swing_grows_with_their_buy_sources():
    """The +Buy exception: a bare one-Province lead is not a buffer against a
    deck that can take a Province AND a Duchy in one turn."""
    plain = board(provinces=2)
    assert E.opponent_max_vp_swing(plain, A) == 6
    rich = board(provinces=2)
    rich["seats"][B]["discard"] += ["Market", "Market"]
    assert E.opponent_max_vp_swing(rich, A) > 6


# ── the greening clock ───────────────────────────────────────────────────────

def test_the_greening_clock_waits_for_the_economy():
    g = board(provinces=8)
    assert not E.should_green(g, A)                 # opening deck, no Golds
    g["seats"][A]["discard"] += ["Gold", "Gold"]
    assert E.should_green(g, A)


def test_the_greening_clock_opens_once_the_provinces_run_short():
    """Past the clock it does not matter how thin the deck is — points are the
    only thing left to buy."""
    g = board(provinces=4)
    assert E.should_green(g, A)


# ── the stall breaker ────────────────────────────────────────────────────────

def test_a_deadlocked_game_stops_refusing_to_end():
    """Two bots both refusing to end a game they would lose is a deadlock with
    no exit. Found for real: on a Corsair board each side trashes the other's
    first Silver or Gold every turn, so neither ever reaches $8 again — the
    pair ran 4,448 turns and never finished. Past the horizon the refusal
    stops applying and somebody takes the ending."""
    g = board(provinces=1, coins=8, lead=-20)
    assert E.override(g, A, "Province") != "Province"    # normal play: refuse
    g["turn_number"] = E.STALL_TURNS
    assert E._stalled(g)
    assert E.override(g, A, "Province") == "Province"    # stalled: end it


def test_a_stalled_game_piledrives_when_no_single_buy_ends_it():
    """The position that motivated the breaker had NO game-ending buy on
    offer: Estates and Duchies gone, and the only affordable piles were Curse
    (10 left) and Copper (46). Ending it means buying the shallowest pile down
    until a third one empties."""
    g = board(provinces=6, coins=2, lead=0)
    g["supply"]["Village"] = 0
    g["supply"]["Smithy"] = 0
    g["supply"]["Estate"] = 0
    g["supply"]["Moat"] = 5          # affordable at $2, and the shallowest
    g["turn_number"] = E.STALL_TURNS
    got = E.override(g, A, None)
    assert got == "Moat", f"expected the shallowest affordable pile, got {got}"


def test_the_stall_breaker_never_drains_copper():
    """Copper is always affordable and 46 deep, so on cost alone it would win
    the "shallowest" comparison forever and drain nothing."""
    g = board(provinces=6, coins=2, lead=0)
    g["turn_number"] = E.STALL_TURNS
    for pile in list(g["supply"]):
        if pile not in ("Copper", "Curse"):
            g["supply"][pile] = 0
    assert E._shallowest(g, ["Copper", "Curse"]) == "Curse"


def test_the_horizon_cannot_fire_in_a_normal_length_game():
    """A Big Money game finishes around turn 17-20, so the breaker must sit far
    outside normal play — it changes losing behaviour, and a false positive
    would make the bot throw games away."""
    assert E.STALL_TURNS >= 50
    g = board(provinces=6, coins=8, lead=-5)
    g["turn_number"] = 25
    assert not E._stalled(g)
