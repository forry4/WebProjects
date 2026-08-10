"""Skat mode — the second auction over the same card play.

Everything from `_start_play` onwards is shared with the classic auction and is
covered by `test_engine.py` / `test_rust_parity.py`; nothing here re-tests the
card play. What IS here is the phase machine between the deal and trick 1, the
value ladder, the announcement arithmetic, and the two places where skat mode
introduces new secrets (the talon it may never look at, the hand it may choose
to show).
"""

import json

import pytest

from games.dissonance import engine as E


# --- helpers ---------------------------------------------------------------



def _pool_of(g: dict) -> int:
    """The completed round's pool in this game's own currency: the worth of
    the 26 dealt-in cards under card scoring, the parity constant otherwise."""
    if E.uses_card_points(E.mode_of(g)):
        return E.played_pool(g)
    return E.pool_for(E.mode_of(g))

def _skat(opener: int = 0) -> dict:
    return E.new_game(["alice", "bob"], None, opener=opener, mode="skat")


def _settled(value: int = 12, opener: int = 0) -> dict:
    """A skat game with the auction won by the opener at `value`."""
    g = _skat(opener)
    E.apply_skat_bid(g, opener, value)
    E.apply_pass(g, 1 - opener)
    assert g["phase"] == "talon"
    return g


def _declared(value=12, denom=3, level=4, hand=False, sharp=False, open_=False,
              kontra=False, re=False) -> dict:
    """Drive a skat game all the way to the opening lead."""
    g = _settled(value)
    decl = g["auction"]["declarer"]
    if hand:
        E.apply_hand(g, decl)
    else:
        E.apply_look(g, decl)
        E.apply_swap(g, decl, None, None)
    E.apply_declare(g, decl, denom, level, sharp, open_)
    E.apply_kontra(g, 1 - decl, kontra)
    if kontra:
        E.apply_re(g, decl, re)
    return g


# --- the value ladder ------------------------------------------------------


def test_every_rung_is_a_base_times_a_level_or_null():
    """The ladder is DERIVED from the bases, never typed out.

    SKAT_MODE.md's prose enumerates the rungs by hand and gets it wrong twice
    (it counts 43 and lists a 7). The generator is the rule, so the test asserts
    against the generator.
    """
    products = {E.SKAT_BASE[d] * lvl
                for d in E.SKAT_DENOMS
                for lvl in range(E.MIN_LEVEL, E.MAX_LEVEL + 1)}
    for v in E.SKAT_VALUES:
        assert v in products or v == E.SKAT_NULL_VALUE, v
    assert E.SKAT_VALUES == sorted(set(E.SKAT_VALUES)), "no duplicate rungs"
    # DERIVED from the bases, not written as literals: the colour re-pricing
    # moved the ceiling from 6x12 to 5x12, and a literal would have had to be
    # hand-edited to notice. Over SKAT_DENOMS, never over the raw table -- that
    # carries a 0 in Null's slot for "not on the ladder".
    buyable = [E.SKAT_BASE[d] for d in E.SKAT_DENOMS]
    assert E.SKAT_VALUES[0] == min(buyable)
    assert E.SKAT_VALUES[-1] == max(buyable) * E.MAX_LEVEL


def test_seven_is_the_ladders_only_hole_below_ten():
    """Documenting a real gap rather than pretending the prose was right: 7 is
    not a multiple of any base, so the otherwise dense 2..10 stretch skips it."""
    assert [v for v in range(2, 11) if v not in E.SKAT_VALUES] == [7]


def test_a_number_does_not_say_which_game_is_coming():
    """The mode's entire premise, asserted: several declarations clear 12."""
    reach = [d for d in E.skat_declarable(12)
             if E.SKAT_BASE[d["denom"]] * d["min_level"] == 12]
    assert len(reach) >= 3


def _declare_phase_at(value: int) -> dict:
    g = _settled(value)
    decl = g["auction"]["declarer"]
    E.apply_hand(g, decl)
    return g


def test_every_legal_bid_is_declarable():
    """Skat's "overbid loses at once" rule has nothing to fire on here.

    The level is the declarer's free choice from 1..12 and no-trump at 12 is the
    ladder's top rung, so no bid can strand its winner. Stretching is punished
    structurally instead — a big number forces a level you cannot make.
    """
    for v in E.SKAT_VALUES:
        opts = E.skat_declarable(v)
        assert opts, f"bid of {v} had no declarable game"
        assert any(E.SKAT_BASE[o["denom"]] * o["min_level"] >= v for o in opts)


def test_the_price_table_is_two_tiers_by_COLOUR_plus_no_trump():
    """Red 2, black 3, no-trump dearest -- and the two suits in a colour cost
    exactly the same, which is the point.

    It replaced a four-tier table (D2 H3 S4 C5 NT6). The suits are measured
    symmetric, so pricing hearts a rung under spades made the cheap suits
    swallow the auction for a reason no player could name. With the colours
    level, choosing within one is a question about your cards again -- so the
    EQUALITIES below are the assertion, not an incidental consequence of it.
    """
    clubs, diamonds, hearts, spades, notrump = (
        E.SKAT_BASE[d] for d in (0, 1, 2, 3, E.NOTRUMP))
    assert diamonds == hearts, "the two reds are priced identically"
    assert clubs == spades, "the two blacks are priced identically"
    assert diamonds < clubs < E.SKAT_BASE[E.GRAND] < notrump, (
        "red cheap, black dearer, Grand above them, no-trump dearest")
    assert notrump == max(E.SKAT_BASE), "no-trump at MAX_LEVEL is the top rung"
    assert E.SKAT_BASE[E.NULL_DENOM] == 0, (
        "Null is not on the ladder, and a base of 0 is how the table says so")


# --- Grand: the four tens are trump, and belong to no suit -----------------
#
# Only the skat auction can buy it, but the CARD PLAY is shared with classic
# mode, so these drive `beats` / `legal_moves` directly rather than through an
# auction. The one thing every case below turns on: `esuit` is `suit` under
# every contract but Grand.


def _card(s: int, r: int) -> int:
    return s * E.NRANK + r


_TENS = [_card(s, E.TEN_RANK) for s in range(4)]


def test_the_ten_is_derived_from_the_deck_not_written_as_an_index():
    """A literal 3 is wrong on any deck but this one, and the rank list is what
    actually says which index is the ten."""
    assert E.RANK_NAMES[E.TEN_RANK] == "10"
    assert all(E.card_name(c).startswith("10") for c in _TENS)


def test_grand_is_priced_between_the_black_suits_and_no_trump():
    """Four trumps, of which ~0.75 sit out of play on an average deal, is
    no-trump with a handful of wild cards -- not a suit game with a long
    trump. The price says so."""
    assert E.SKAT_BASE[E.GRAND] == 4
    assert E.SKAT_BASE[3] < E.SKAT_BASE[E.GRAND] < E.SKAT_BASE[E.NOTRUMP]
    assert E.GRAND in E.SKAT_DENOMS
    assert 12 in E.SKAT_VALUES and E.skat_min_level(E.GRAND, 12) == 3


def test_grand_does_not_collide_with_the_legacy_null_marker():
    """5 is NULL_DENOM, left on saves from before Null stopped being a bid.
    Reusing it for Grand would silently re-read one of those as a Grand
    contract -- a different trump AND a different follow-suit rule."""
    assert E.GRAND != E.NULL_DENOM
    assert E.NULL_DENOM not in E.SKAT_DENOMS
    g = _declare_phase_at(12)
    with pytest.raises(ValueError):
        E.apply_declare(g, g["auction"]["declarer"], E.NULL_DENOM, 3)


def test_the_second_ten_played_wins_whichever_two_they_are():
    """Grand's trumps are unrankable -- they are all tens -- so the order they
    are PLAYED in is the only thing that can decide, and the follower takes it.

    Which makes leading a ten a way to LOSE a trick on purpose. Seven of the
    thirteen tricks are worth -1, so that is a tool, not a penalty.
    """
    for led in _TENS:
        for follow in _TENS:
            if led == follow:
                continue
            assert E.beats(led, follow, E.GRAND), (
                f"{E.card_name(follow)} answering {E.card_name(led)}")


def test_a_ten_ruffs_but_a_ten_lead_is_never_ruffed():
    ace_of_spades, king_of_spades = _card(3, 7), _card(3, 6)
    assert E.beats(ace_of_spades, _TENS[0], E.GRAND), "a ten ruffs from any suit"
    assert not E.beats(_TENS[0], ace_of_spades, E.GRAND), "nothing over-ruffs a ten"
    assert E.beats(ace_of_spades, king_of_spades, E.GRAND) is False
    assert E.beats(king_of_spades, ace_of_spades, E.GRAND) is True


def test_a_ten_is_not_a_card_of_its_own_suit_under_grand():
    """The rule with all the consequences. The ten of diamonds does not answer
    a diamond lead, does not beat a lower diamond as a diamond, and its absence
    from the suit is what makes a hand VOID."""
    ten_d, nine_d, seven_d = _TENS[1], _card(1, 2), _card(1, 0)
    assert E.beats(nine_d, ten_d, E.GRAND), "it takes the trick as a TRUMP"
    assert not E.beats(ten_d, nine_d, E.GRAND), "a diamond cannot beat a trump"
    assert E.esuit(ten_d, E.GRAND) == E.TRUMP_CLASS
    assert E.esuit(seven_d, E.GRAND) == E.suit(seven_d) == 1


def _grand_at(hand: list[int], led: int) -> dict:
    """A play position with `hand` at seat 1 and `led` on the table."""
    g = E.new_game(["alice", "bob"], None, opener=0, mode="skat")
    g["phase"], g["trump"] = "play", E.GRAND
    g["hands"][1], g["piles"][1] = sorted(hand), [[], [], []]
    g["led"], g["leader"] = led, 0
    return g


def test_follow_suit_reads_the_grand_trump_as_a_fifth_suit():
    ten_d, seven_d, queen_h = _TENS[1], _card(1, 0), _card(2, 5)
    ace_d = _card(1, 7)

    # Holding the ten of diamonds does NOT discharge a diamond lead.
    g = _grand_at([ten_d, seven_d, queen_h], ace_d)
    assert E.legal_moves(g, 1) == [seven_d]

    # Drop the seven and the same hand is void: the ten may ruff, or not.
    g = _grand_at([ten_d, queen_h], ace_d)
    assert E.legal_moves(g, 1) == sorted([ten_d, queen_h]), "may ruff, never forced"

    # A ten LED is a trump lead, and a trump must be followed.
    g = _grand_at([ten_d, queen_h], _TENS[0])
    assert E.legal_moves(g, 1) == [ten_d]

    # ...and with no ten at all, anything goes.
    g = _grand_at([seven_d, queen_h], _TENS[0])
    assert E.legal_moves(g, 1) == sorted([seven_d, queen_h])


def test_every_other_contract_plays_exactly_as_it_did_before_grand_existed():
    """The regression that matters most: `esuit` collapses to `suit` under all
    five old denominations, so this asserts the OLD rule over the whole 32x32
    card space rather than sampling it."""
    for trump in list(range(E.NOTRUMP)) + [E.NOTRUMP]:
        for led in range(E.NCARD):
            for follow in range(E.NCARD):
                ls, fs = E.suit(led), E.suit(follow)
                if fs == ls:
                    want = E.rank(follow) > E.rank(led)
                elif trump < E.NOTRUMP:
                    want = fs == trump and ls != trump
                else:
                    want = False
                assert E.beats(led, follow, trump) is want, (led, follow, trump)


def test_a_grand_round_plays_from_the_declaration_to_a_scored_result():
    """End to end through the real phase machine, not a hand-built dict: the
    auction has to OFFER Grand, `_start_play` has to put GRAND in `trump`, and
    thirteen tricks have to score to the pool under the fifth-suit rule."""
    from games.dissonance import bot

    g = _skat(opener=0)
    E.apply_skat_bid(g, 0, 12)
    E.apply_pass(g, 1)
    E.apply_hand(g, 0)
    assert any(d["denom"] == E.GRAND for d in E.declare_options(g)["denoms"])
    E.apply_declare(g, 0, E.GRAND, 3)          # 4 x 3 = 12
    E.apply_kontra(g, 1, False)
    assert g["phase"] == "play" and g["trump"] == E.GRAND

    guard = 0
    while g["phase"] == "play":
        seat = E.to_play(g)
        E.apply_play(g, seat, bot.choose_card(g, seat))
        guard += 1
        assert guard <= E.NTRICKS * 2
    assert g["phase"] == "over"
    if not g["result"]["ended_early"]:
        assert g["trick"] == E.NTRICKS and sum(g["pts"]) == _pool_of(g)
    assert g["result"]["denom"] == E.GRAND
    assert g["result"]["base"] == E.SKAT_BASE[E.GRAND]


def test_a_grand_game_survives_the_state_json_codec():
    """`trump` is 6 here, outside the 0..4 every other contract uses, and it
    rides the compaction boundary like any other int."""
    from games.dissonance import persist

    g = _skat(opener=0)
    E.apply_skat_bid(g, 0, 12)
    E.apply_pass(g, 1)
    E.apply_hand(g, 0)
    E.apply_declare(g, 0, E.GRAND, 3)
    E.apply_kontra(g, 1, False)
    E.apply_play(g, 0, E.legal_moves(g, 0)[0])

    back = persist.expand_state(json.loads(json.dumps(persist.compact_state(g))))
    assert back["trump"] == E.GRAND
    assert E.legal_moves(back, E.to_play(back)) == E.legal_moves(g, E.to_play(g))


# --- the auction -----------------------------------------------------------


def test_the_opener_may_pass_and_both_passing_throws_the_hand_in():
    g = _skat(opener=0)
    assert E.auction_options(g)["may_pass"] is True, "unlike classic, no forced open"
    hands_before = [list(h) for h in g["hands"]]
    E.apply_pass(g, 0)
    assert g["phase"] == "auction" and g["auction"]["to_act"] == 1
    E.apply_pass(g, 1)
    assert g["phase"] == "auction", "a thrown-in hand redeals rather than ending"
    assert g["redeals"] == 1
    # The SAME seat opens the replacement deal. This used to flip, on the
    # reasoning that passing out of a bad seat should not be free -- but the
    # replacement is fresh cards, so there was no bad seat left to escape, and
    # the flip's real effect was to knock the match's round-by-round
    # alternation out of phase (a thrown-in hand is not a round).
    assert g["opener"] == 0, "a redeal moved the opener without a round passing"
    assert g["auction"]["passes"] == 0 and g["auction"]["log"] == []
    assert [list(h) for h in g["hands"]] != hands_before or g["out"], "a fresh deal"


def test_passing_after_a_bid_settles_the_auction_on_the_last_bidder():
    g = _skat(opener=0)
    E.apply_pass(g, 0)
    E.apply_skat_bid(g, 1, 10)
    E.apply_skat_bid(g, 0, 12)     # an opener who passed may still come back in
    E.apply_pass(g, 1)
    assert g["phase"] == "talon"
    assert g["auction"]["declarer"] == 0
    assert g["auction"]["value"] == 12
    assert g["auction"]["level"] == 0 and g["auction"]["denom"] == -1, \
        "the declaration is not made yet, and the wire must not imply one"


def test_a_bid_must_be_a_rung_and_must_outrank_the_standing_number():
    g = _skat()
    E.apply_skat_bid(g, 0, 12)
    with pytest.raises(ValueError):
        E.apply_skat_bid(g, 1, 12)      # equal is not higher
    with pytest.raises(ValueError):
        E.apply_skat_bid(g, 1, 11)      # lower
    with pytest.raises(ValueError):
        E.apply_skat_bid(g, 1, 13)      # not on the ladder
    with pytest.raises(ValueError):
        E.apply_skat_bid(g, 0, 14)      # not your turn
    assert E.auction_options(g)["values"][0] == 14


def test_the_classic_bid_shape_is_refused_in_skat_mode_and_the_reverse():
    g = _skat()
    with pytest.raises(ValueError):
        E.apply_bid(g, 0, 3, 1)
    classic = E.new_game(["alice", "bob"], None, opener=0)
    with pytest.raises(ValueError):
        E.apply_skat_bid(classic, 0, 12)
    assert "contract" not in classic, "classic games carry no skat state"
    assert E.mode_of(classic) == "classic"


def test_the_options_the_client_renders_are_the_options_the_engine_enforces():
    g = _skat()
    E.apply_skat_bid(g, 0, 20)
    for v in E.auction_options(g)["values"]:
        probe = _skat()
        E.apply_skat_bid(probe, 0, 20)
        E.apply_skat_bid(probe, 1, v)   # must not raise
    for v in (2, 10, 20):
        with pytest.raises(ValueError):
            E.apply_skat_bid(g, 1, v)


# --- the talon -------------------------------------------------------------


def test_hand_never_sees_the_talon_even_at_the_declarers_own_seat():
    """Hand has to cost the information, or it is a free multiplier."""
    g = _settled()
    decl = g["auction"]["declarer"]
    assert E.talon_options(g)["shown"] == [], "not shown before the choice is made"
    E.apply_hand(g, decl)
    assert g["contract"]["hand"] is True
    assert g["phase"] == "declare"
    assert E.view_for(g, decl)["shown"] is None
    with pytest.raises(ValueError):
        E.apply_look(g, decl)


def test_looking_gives_up_hand_and_standing_pat_does_not_win_it_back():
    g = _settled()
    decl = g["auction"]["declarer"]
    E.apply_look(g, decl)
    assert E.talon_options(g)["shown"] == g["shown"]
    assert E.view_for(g, decl)["shown"] == g["shown"]
    assert E.view_for(g, 1 - decl)["shown"] is None
    with pytest.raises(ValueError):
        E.apply_hand(g, decl)          # too late, you have seen them
    E.apply_swap(g, decl, None, None)
    assert g["phase"] == "declare"
    assert g["contract"]["hand"] is False and g["swapped"] is False


def test_the_swap_needs_a_look_first_and_moves_to_the_declaration_not_to_play():
    g = _settled()
    decl = g["auction"]["declarer"]
    with pytest.raises(ValueError):
        E.apply_swap(g, decl, g["shown"][0], sorted(g["hands"][decl])[0])
    E.apply_look(g, decl)
    take, give = g["shown"][0], sorted(g["hands"][decl])[0]
    E.apply_swap(g, decl, take, give)
    assert g["phase"] == "declare", "in skat mode the talon resolves BEFORE the game is named"
    assert take in g["hands"][decl] and give not in g["hands"][decl]
    assert give in g["out"] and g["swapped"] is True


def test_only_the_declarer_touches_the_talon():
    g = _settled()
    other = 1 - g["auction"]["declarer"]
    for call in (E.apply_look, E.apply_hand):
        with pytest.raises(ValueError):
            call(g, other)


# --- the declaration -------------------------------------------------------


def test_the_declaration_must_reach_the_bid():
    g = _declare_phase_at(20)
    decl = g["auction"]["declarer"]
    with pytest.raises(ValueError):
        E.apply_declare(g, decl, 1, 9)      # diamonds x 9 = 18 < 20
    E.apply_declare(g, decl, 1, 10)         # diamonds x 10 = 20
    assert g["contract"]["value"] == 20 and g["auction"]["level"] == 10


def test_declaring_higher_than_you_must_is_legal_and_costs_you_the_level():
    g = _declare_phase_at(12)
    decl = g["auction"]["declarer"]
    E.apply_declare(g, decl, 4, 6)          # no-trump x 6 = 30, far past the bid
    assert g["contract"]["value"] == E.SKAT_BASE[4] * 6
    assert E.skat_target(g) == 6, "the level you declared is the level you owe"


def test_null_is_not_a_declaration_either():
    """It stopped being a game you buy, in BOTH modes at once. The ladder still
    contains 20 -- as diamonds at 10, hearts at 10 and no-trump at 4 -- but
    nothing on it names Null any more."""
    g = _declare_phase_at(20)
    assert all(d["denom"] != E.NULL_DENOM for d in E.declare_options(g)["denoms"])
    assert "null_ok" not in E.declare_options(g)
    with pytest.raises(ValueError):
        E.apply_declare(g, g["auction"]["declarer"], E.NULL_DENOM, 0)
    assert 20 in E.SKAT_VALUES, "20 is still an ordinary rung, reached three ways"


def test_open_rides_on_sharp():
    g = _declare_phase_at(12)
    decl = g["auction"]["declarer"]
    with pytest.raises(ValueError):
        E.apply_declare(g, decl, 3, 4, sharp=False, open_=True)
    E.apply_declare(g, decl, 3, 4, sharp=True, open_=True)
    assert g["contract"]["open"] is True


def test_only_the_declarer_declares():
    g = _declare_phase_at(12)
    with pytest.raises(ValueError):
        E.apply_declare(g, 1 - g["auction"]["declarer"], 3, 4)


# --- announcements and Kontra ----------------------------------------------


@pytest.mark.parametrize("hand,sharp,open_,want", [
    (False, False, False, 1),
    (True, False, False, 2),
    (False, True, False, 2),
    (False, True, True, 3),
    (True, True, False, 3),
    (True, True, True, 4),
    (True, False, True, 3),
    (False, False, True, 2),
])
def test_announcements_stack_by_addition(hand, sharp, open_, want):
    """Skat-style: each announcement adds one. A multiplier rather than a flat
    bonus because the classic campaign measured flat bonuses RAISING the floor
    cluster -- they are proportionally biggest on the smallest contracts."""
    assert E.skat_multiplier(hand, sharp, open_) == want


def test_kontra_doubles_and_re_doubles_again():
    plain = _declared()
    assert E.skat_doubling(plain["contract"]) == 1
    assert plain["phase"] == "play"

    doubled = _declared(kontra=True, re=False)
    assert doubled["contract"]["kontra"] is True and doubled["contract"]["re"] is False
    assert E.skat_doubling(doubled["contract"]) == 2

    quadrupled = _declared(kontra=True, re=True)
    assert E.skat_doubling(quadrupled["contract"]) == 4


def test_kontra_belongs_to_the_defender_and_re_to_the_declarer():
    g = _declare_phase_at(12)
    decl = g["auction"]["declarer"]
    E.apply_declare(g, decl, 3, 4)
    assert g["phase"] == "kontra"
    assert E.turn_seat(g) == 1 - decl
    with pytest.raises(ValueError):
        E.apply_kontra(g, decl, True)
    E.apply_kontra(g, 1 - decl, True)
    assert g["phase"] == "re" and E.turn_seat(g) == decl
    with pytest.raises(ValueError):
        E.apply_re(g, 1 - decl, True)
    E.apply_re(g, decl, False)
    assert g["phase"] == "play"


def test_declining_kontra_goes_straight_to_the_lead():
    g = _declared(kontra=False)
    assert g["phase"] == "play"
    assert g["leader"] == g["auction"]["declarer"], "the declarer still leads trick 1"


@pytest.mark.parametrize("phase_at,seat_is_declarer", [
    ("talon", True), ("declare", True), ("kontra", False), ("re", True),
])
def test_every_skat_phase_names_exactly_one_seat_to_act(phase_at, seat_is_declarer):
    g = _settled()
    decl = g["auction"]["declarer"]
    if phase_at != "talon":
        E.apply_hand(g, decl)
    if phase_at in ("kontra", "re"):
        E.apply_declare(g, decl, 3, 4)
    if phase_at == "re":
        E.apply_kontra(g, 1 - decl, True)
    assert g["phase"] == phase_at
    assert E.turn_seat(g) == (decl if seat_is_declarer else 1 - decl)
    assert E.turn_pid(g) == g["seats"][E.turn_seat(g)]


# --- scoring ---------------------------------------------------------------


def _score(g: dict, declarer_pts: int, etricks: int = 1) -> dict:
    """Run the scorer over a declared game held at a chosen point total.

    `etricks` defaults to 1 because Null is checked FIRST and wins: a declarer
    left on zero scoring tricks takes the consolation whatever their point total
    says, so a staged result that forgot it would score every contract as Null.
    Pass 0 deliberately to exercise that branch.
    """
    decl = g["auction"]["declarer"]
    g["pts"][decl] = declarer_pts
    g["pts"][1 - decl] = E.POOL - declarer_pts
    g["etricks"][decl] = etricks
    g["etricks"][1 - decl] = 6 - etricks
    E._finish(g)
    return g["result"]


def test_making_it_pays_value_times_multiplier():
    g = _declared(value=12, denom=3, level=4)      # spades x 4 = 12
    res = _score(g, 4)                             # exactly on target: no bonus
    assert res["mode"] == "skat"
    assert (res["value"], res["mult"], res["doubling"]) == (12, 1, 1)
    assert res["made"] is True
    assert res["over"] == 0
    assert res["scores"][res["declarer"]] == 12
    assert res["scores"][1 - res["declarer"]] == 0


def test_every_point_past_the_target_adds_one():
    """The overtrick bonus. Flat, and NOT run through the multipliers -- one
    trick point is worth one whatever the contract cost, on the same argument
    that keeps the Null consolation unscaled."""
    plain = _score(_declared(value=12, denom=3, level=4), 7)
    assert plain["made"] is True and plain["over"] == 3
    assert plain["over_bonus"] == E.OVER_BONUS["skat"] == 1
    assert plain["scores"][plain["declarer"]] == 12 + 3

    # x16 on the stake, x1 on the bonus.
    stacked = _declared(value=12, denom=3, level=4, hand=True, sharp=True,
                        open_=True, kontra=True, re=True)
    res = _score(stacked, 9)
    assert res["target"] == 4 + E.SHARP_BONUS
    assert res["over"] == 9 - res["target"]
    assert res["scores"][res["declarer"]] == 12 * 4 * 4 + res["over"]

    # Being SET is untouched by it: there is no margin above a target you
    # missed, and the shortfall rule already prices the distance below.
    lost = _score(_declared(value=12, denom=3, level=4), 1)
    assert lost["over"] == 0 and lost["made"] is False
    assert lost["scores"][1 - lost["declarer"]] == 12 + E.SHORT_PENALTY * 3


def test_missing_it_pays_the_defender_the_same_number_plus_the_shortfall():
    g = _declared(value=12, denom=3, level=4)
    res = _score(g, 1)
    assert res["made"] is False and res["short"] == 3
    assert res["scores"][1 - res["declarer"]] == 12 + E.SHORT_PENALTY * 3
    assert res["scores"][res["declarer"]] == 0


def test_sharp_raises_the_bar_and_a_bare_make_now_loses():
    """The margin is SHARP_BONUS, read symbolically — it is a tuned knob (3 was
    measured at 0% of contracts and dropped to 2), so a test that hardcodes it
    fails on the next tuning pass for no reason."""
    bonus = E.SHARP_BONUS
    g = _declared(value=12, denom=3, level=4, sharp=True)
    assert E.skat_target(g) == 4 + bonus
    res = _score(g, 4)      # would have made the plain contract exactly
    assert res["made"] is False, "Sharp promises level + the bonus, not level"
    assert res["short"] == bonus
    assert res["scores"][1 - res["declarer"]] == 12 * 2 + E.SHORT_PENALTY * bonus

    made = _score(_declared(value=12, denom=3, level=4, sharp=True), 4 + bonus)
    assert made["made"] is True and made["over"] == 0
    assert made["scores"][made["declarer"]] == 24
    # Exactly on the bar makes it; one under does not.
    just_under = _score(_declared(value=12, denom=3, level=4, sharp=True), 3 + bonus)
    assert just_under["made"] is False and just_under["short"] == 1


def test_the_full_stack_multiplies_rather_than_adds_to_the_payout():
    g = _declared(value=12, denom=3, level=4, hand=True, sharp=True, open_=True,
                  kontra=True, re=True)
    # Sharp moves the target to 4 + 2, so scoring 6 makes it with nothing over
    # and the payout is the stack alone.
    res = _score(g, 4 + E.SHARP_BONUS)
    assert (res["mult"], res["doubling"]) == (4, 4)
    assert res["stake"] == 12 * 4 * 4
    assert res["over"] == 0
    assert res["scores"][res["declarer"]] == 192


def test_kontra_cuts_both_ways():
    """Doubling is not a defender-only weapon -- it doubles the make too."""
    made = _score(_declared(value=12, denom=3, level=4, kontra=True), 4)
    assert made["scores"][made["declarer"]] == 24
    lost = _score(_declared(value=12, denom=3, level=4, kontra=True), 1)
    assert lost["scores"][1 - lost["declarer"]] == 24 + E.SHORT_PENALTY * 3


def test_null_is_a_flat_consolation_that_ignores_the_contract_entirely():
    """It replaces being set, and NOTHING about the contract scales it -- not
    the value, not Hand, not Kontra. Doubling a consolation would have a
    defender's Kontra rewarding the very outcome it was betting against."""
    for kontra in (False, True):
        g = _declared(value=20, denom=4, level=4, hand=True, sharp=True,
                      kontra=kontra, re=False)
        decl = g["auction"]["declarer"]
        res = _score(g, -3, etricks=0)   # a dreadful total is beside the point
        assert res["null"] is True and res["made"] is False
        assert res["short"] == 0, "Null is flat; there is no shortfall to scale"
        assert res["scores"][decl] == E.SKAT_NULL_VALUE
        assert res["scores"][1 - decl] == 0
        assert res["mult"] > 1 and (res["doubling"] > 1) == kontra, \
            "the multipliers are still on the row; they simply do not apply"


def test_one_scoring_trick_is_the_difference_between_null_and_a_heavy_set():
    """The cliff the consolation puts in the middle of a losing hand."""
    ducked = _score(_declared(value=24, denom=4, level=6), -3, etricks=0)
    slipped = _score(_declared(value=24, denom=4, level=6), -1, etricks=1)
    decl = ducked["declarer"]
    assert ducked["scores"][decl] == E.SKAT_NULL_VALUE
    assert slipped["scores"][decl] == 0 and slipped["scores"][1 - decl] > 0


def test_walking_out_costs_the_declared_game_not_a_classic_square():
    g = _declared(value=12, denom=3, level=4, hand=True, kontra=True)
    assert E.forfeit_value(g) == 12 * 2 * 2
    # Before the declaration the standing bid is the closest honest number.
    mid = _settled(15)
    assert E.forfeit_value(mid) == 15
    # And a classic game still scores in its own currency.
    classic = E.new_game(["a", "b"], None, opener=0)
    classic["auction"]["level"] = 3
    assert E.forfeit_value(classic) == 9


# --- redaction -------------------------------------------------------------


def test_a_skat_view_never_leaks_the_talon_or_the_opponents_hand():
    """Asserted against the whole SERIALIZED view of a real in-progress game --
    a nested copy is exactly how CoC's redaction was correct at the top level
    and still leaking."""
    g = _declared(value=12, denom=3, level=4)
    for _ in range(6):
        s = E.to_play(g)
        E.apply_play(g, s, E.legal_moves(g, s)[0])
    decl = g["auction"]["declarer"]

    for seat in (0, 1):
        blob = json.dumps(E.view_for(g, seat))
        view = json.loads(blob)
        assert "hands" not in view
        assert view["out"] is None, "the out-of-play cards stay secret until the end"
        assert view["shown"] == (g["shown"] if seat == decl else None)
        assert view["opp_hand"] is None, "no Open was announced"
        assert sorted(view["hand"]) == sorted(g["hands"][seat])
        # The declaration and the ladder are public; the private prompts are not.
        assert view["contract"] == g["contract"]
        assert view["auction"]["value"] == 12
        assert view["talon"] is None and view["declare"] is None
        for owner in range(2):
            for j, pv in enumerate(view["piles"][owner]):
                real = g["piles"][owner][j]
                assert pv["under"] == (real[0] if (len(real) == 2 and j == 1) else None)
        # A hidden holding leaks as a COLLECTION, not as a stray index -- a
        # nested whole-game copy is how CoC shipped the ordered supply while its
        # top-level redaction was correct. So: no list anywhere in this payload,
        # however deep, may carry the other seat's hand or the out-of-play cards.
        for secret in (set(g["hands"][1 - seat]), set(g["out"])):
            for got in _all_lists(view):
                assert not secret.issubset(got), sorted(got)


def _all_lists(node):
    """Every list of ints in a view, however deeply nested, as sets."""
    if isinstance(node, dict):
        for v in node.values():
            yield from _all_lists(v)
    elif isinstance(node, (list, tuple)):
        yield {x for x in node if isinstance(x, int) and not isinstance(x, bool)}
        for v in node:
            yield from _all_lists(v)


def test_the_defender_never_sees_the_talon_a_hand_game_declined_to_look_at():
    g = _declared(value=12, denom=3, level=4, hand=True)
    for seat in (0, 1):
        assert E.view_for(g, seat)["shown"] is None, \
            "nobody has seen these cards, the declarer included"


def test_open_shows_the_declarers_hand_and_only_from_trick_one():
    g = _settled(12)
    decl = g["auction"]["declarer"]
    E.apply_hand(g, decl)
    E.apply_declare(g, decl, 3, 4, sharp=True, open_=True)
    # Announced, but the cards are not down until the Kontra decision resolves.
    assert E.view_for(g, 1 - decl)["opp_hand"] is None
    assert g["phase"] == "kontra"
    E.apply_kontra(g, 1 - decl, False)
    assert g["phase"] == "play"

    defender_view = E.view_for(g, 1 - decl)
    assert defender_view["opp_hand"] == sorted(g["hands"][decl])
    # ...and it is one-way: the declarer bought a multiplier, not a mirror.
    assert E.view_for(g, decl)["opp_hand"] is None


def test_a_spectator_sees_the_public_game_and_no_more():
    g = _declared(value=12, denom=3, level=4)
    v = E.player_view(g, "nobody")
    assert v["hand"] == [] and v["you"] is None
    assert v["shown"] is None and v["opp_hand"] is None
    assert v["talon"] is None and v["declare"] is None
    assert v["contract"] == g["contract"], "the declaration is public"


# --- the whole round -------------------------------------------------------


def test_a_skat_round_plays_from_the_deal_to_a_scored_result():
    g = _declared(value=12, denom=3, level=4, sharp=True, kontra=True, re=True)
    guard = 0
    while g["phase"] == "play":
        guard += 1
        assert guard <= E.NTRICKS * 2 + 1
        s = E.to_play(g)
        E.apply_play(g, s, E.legal_moves(g, s)[0])
    assert g["phase"] == "over"
    # `_skat` deals from an UNSEEDED rng, so this round is a different one every
    # run -- and a round stops the moment the score can no longer change. The
    # pool invariant is therefore only available on the complete branch. Read
    # the helper, not six green local runs: this assertion passed here and went
    # red in CI on the first deal that settled at trick 10.
    if g["trick"] == E.NTRICKS:
        assert sum(g["pts"]) == _pool_of(g)
    else:
        assert g["result"]["ended_early"]
    res = g["result"]
    assert res["mode"] == "skat"
    assert res["stake"] == 12 * 2 * 4, "Sharp alone is x2; Kontra + Re is x4"
    winner = res["declarer"] if (res["made"] or res["null"]) else 1 - res["declarer"]
    assert res["scores"][winner] > 0 and res["scores"][1 - winner] == 0


def test_the_game_dict_stays_json_safe_in_every_skat_phase():
    """The state_json codec, saves and reconnects all depend on it -- and skat
    mode added four phases' worth of new keys."""
    g = _skat()
    seen = []
    E.apply_skat_bid(g, 0, 12)
    seen.append(json.dumps(g))
    E.apply_pass(g, 1)
    seen.append(json.dumps(g))
    E.apply_look(g, 0)
    E.apply_swap(g, 0, g["shown"][0], sorted(g["hands"][0])[0])
    seen.append(json.dumps(g))
    E.apply_declare(g, 0, 3, 4, sharp=True)
    E.apply_kontra(g, 1, True)
    E.apply_re(g, 0, True)
    seen.append(json.dumps(g))
    for blob in seen:
        assert json.loads(blob)["mode"] == "skat"
    assert "rng_state" not in g, "all randomness is spent in the deal"


def test_apply_move_routes_every_skat_move_kind():
    """main.py's single entry point. A kind that never reaches the engine is a
    phase the client cannot get out of."""
    g = _skat()
    pid0, pid1 = g["seats"]
    E.apply_move(g, pid0, {"kind": "bid", "value": 12})
    E.apply_move(g, pid1, {"kind": "pass"})
    E.apply_move(g, pid0, {"kind": "look"})
    E.apply_move(g, pid0, {"kind": "swap", "take": None, "give": None})
    E.apply_move(g, pid0, {"kind": "declare", "denom": 3, "level": 4,
                           "sharp": True, "open": True})
    E.apply_move(g, pid1, {"kind": "kontra", "on": True})
    E.apply_move(g, pid0, {"kind": "re", "on": True})
    assert g["phase"] == "play"
    assert g["contract"] == {"value": 12, "hand": False, "sharp": True,
                             "open": True, "kontra": True, "re": True, "mult": 3}
    E.apply_move(g, g["seats"][E.to_play(g)],
                 {"kind": "play", "card": E.legal_moves(g, E.to_play(g))[0]})
    assert len(g["history"]) == 1


def test_a_skat_game_survives_the_state_json_codec():
    """Every new key is a real game-state key, so it has to come back off disk
    intact — a declaration or a Kontra that a reconnect forgets is a contract
    the server would then score wrong."""
    from games.dissonance import main as m

    g = _declared(value=12, denom=3, level=4, sharp=True, kontra=True, re=True)
    for _ in range(4):
        s = E.to_play(g)
        E.apply_play(g, s, E.legal_moves(g, s)[0])

    blob = m._encode_state({"players": {}, "host": None, "status": "playing",
                            "game": g, "meta": {}, "mode": "skat"})
    back = m._decode_state(blob)["game"]
    assert back == g, "the compaction boundary must be lossless for skat state"
    E._finish(back)
    E._finish(g)
    assert back["result"] == g["result"]


def test_the_rust_lab_prices_the_same_ladder_this_engine_does():
    """`rust-cores/dissonance-core/src/skat.rs` is the measurement instrument for
    this mode, and it carries its own copy of the price table. A drift there
    does not break anything visibly — it silently measures a DIFFERENT game and
    reports the numbers as if they were this one's.

    Read as TEXT, the way `core/tests/test_history_limit.py` checks the history
    cap across the Python/JSX boundary: CI has no Rust toolchain (the crates are
    committed artefacts and are in neither deploy path filter), so a test that
    needed `cargo` would not run.
    """
    import pathlib
    import re

    src = (pathlib.Path(__file__).resolve().parents[3]
           / "rust-cores" / "dissonance-core" / "src" / "skat.rs")
    assert src.exists(), f"the skat lab moved: {src}"
    text = src.read_text(encoding="utf-8")

    def const(name, pattern=r"(-?\d+)"):
        m = re.search(rf"pub const {name}[^=]*=\s*{pattern}", text)
        assert m, f"could not find {name} in {src.name}"
        return m.group(1)

    bases = [int(x) for x in const("SKAT_BASE", r"\[([^\]]*)\]").split(",") if x.strip()]
    assert bases == E.SKAT_BASE, (bases, E.SKAT_BASE)
    assert int(const("SKAT_NULL_VALUE")) == E.SKAT_NULL_VALUE
    assert int(const("SHARP_BONUS")) == E.SHARP_BONUS


def test_walking_out_leaves_a_result_row_every_reader_can_render():
    """A forfeit row is read by the same result panel and history card as a
    played-out one. In skat mode the panel branches on `mode` and reads six keys
    only `_finish_skat` would otherwise set -- so a hand-rolled row rendered as
    "bought it at undefined"."""
    quit_mid = _declared(value=12, denom=3, level=4, hand=True, kontra=True)
    res = E.abandon_result(quit_mid, seat=0)
    assert res["mode"] == "skat" and res["abandoned_by"] == 0
    for key in ("bid", "value", "mult", "doubling", "stake", "target",
                "hand", "sharp", "open", "kontra", "re",
                "declarer", "level", "denom", "declarer_pts", "made",
                "short", "scores"):
        assert key in res, key
    assert res["scores"][1] == E.forfeit_value(quit_mid) == 12 * 2 * 2
    assert res["scores"][0] == 0


def test_a_skat_room_can_be_abandoned_before_anyone_has_bid():
    """Only skat mode can reach this: classic's opener is forced to bid, but
    here both players may pass, so `declarer` is still -1 -- and a result row
    indexed off -1 would name the wrong seat as the winner."""
    g = _skat()
    res = E.abandon_result(g, seat=1)
    assert res["declarer"] == -1 and res["level"] == 0
    assert res["abandoned_by"] == 1
    # The seat that stayed is named by `abandoned_by`, never by `declarer`,
    # so it is always a real index.
    assert res["scores"][0] > 0 and res["scores"][1] == 0
    assert res["declarer_pts"] == 0 and res["declarer_etricks"] == 0
    assert res["value"] == 0 and res["target"] == 0
    assert json.dumps(res)


def test_the_bots_talon_swap_is_valued_in_a_real_denomination():
    """Skat resolves the talon BEFORE the game is named, so `auction["denom"]`
    is still -1 there. Reading it silently disables both contract-aware terms in
    the bot's `worth()` -- the swap degenerates to "take the highest card"."""
    from games.dissonance import bot

    g = _settled(12)
    decl = g["auction"]["declarer"]
    E.apply_look(g, decl)
    assert g["auction"]["denom"] == -1, "the premise: nothing is declared yet"

    d = bot.swap_denom(g, decl)
    assert d in E.SKAT_DENOMS, d
    kind, move = bot.act(g, decl, None)
    assert kind == "move" and move["kind"] == "swap"
    # The action the bot actually takes is the one that denomination implies.
    assert move["take"] == bot.choose_swap(g, decl, d)["take"]

    # ...and classic mode, which swaps AFTER the auction, still uses the
    # denomination it actually declared.
    classic = E.new_game(["a", "b"], None, opener=0)
    E.apply_bid(classic, 0, 3, 1)
    E.apply_pass(classic, 1)
    assert bot.swap_denom(classic, 0) == 1


def test_a_hand_game_reaches_the_lead_without_ever_entering_a_swap():
    g = _settled(24)
    decl = g["auction"]["declarer"]
    E.apply_move(g, g["seats"][decl], {"kind": "hand"})
    # no-trump at 5 a level: 5 is the lowest that clears a bid of 24.
    E.apply_move(g, g["seats"][decl], {"kind": "declare", "denom": 4, "level": 5})
    E.apply_move(g, g["seats"][1 - decl], {"kind": "kontra", "on": False})
    assert g["phase"] == "play"
    assert g["trump"] == E.NOTRUMP and g["contract"]["mult"] == 2
    assert len(g["hands"][decl]) == 7, "no card ever moved in or out"


# --- Null ends the moment it is broken -------------------------------------


def _drive(mode: str, seed: int, level: int = 4, denom: int = 2, pick=-1):
    """Play a declared game out with a fixed policy until the engine stops."""
    import random as _r
    g = E.new_game(["alice", "bob"], _r.Random(seed), 0, mode=mode)
    if mode == "skat":
        E.apply_skat_bid(g, 0, E.SKAT_BASE[denom] * level)
        E.apply_pass(g, 1)
        E.apply_hand(g, 0)
        E.apply_declare(g, 0, denom, level)
        E.apply_kontra(g, 1, False)
    else:
        E.apply_bid(g, 0, level, denom)
        E.apply_pass(g, 1)
        E.apply_swap(g, 0, None, None)
        E.apply_double(g, 1, False)     # classic's defender declines
    while g["phase"] == "play":
        s = E.to_play(g)
        E.apply_play(g, s, E.legal_moves(g, s)[pick])
    return g


@pytest.mark.parametrize("mode", ["classic", "skat"])
def test_a_contract_that_cannot_fail_plays_on_for_the_overtricks(mode):
    """The early end is SHELVED in both modes, and this is the position it used
    to fire on: a level-1 contract long since safe, with tricks still to play.

    It used to stop there because a made contract paid a flat amount and the
    rest of the round could not move the score. Every point past the target is
    now worth 1, so those tricks are the declarer's to win and the round runs
    to thirteen. Driven over 400 deals so the safe-early position is certainly
    reached rather than hoped for.
    """
    safe = 0
    for seed in range(400):
        g = _drive(mode, seed, level=1)
        res = g["result"]
        assert g["trick"] == E.NTRICKS, f"seed {seed} ended at trick {g['trick']}"
        assert res["ended_early"] is False
        assert sum(g["pts"]) == _pool_of(g), "a completed round conserves the pool"
        if res["made"]:
            stake, target = _contract_of(res, mode)
            assert res["over"] == res["declarer_pts"] - target
            assert res["scores"][res["declarer"]] == stake + res["over"]
            if res["over"]:
                safe += 1
    assert safe, f"no {mode} deal in 400 finished above a level-1 target"


def _contract_of(res: dict, mode: str) -> tuple[int, int]:
    """(what the contract itself paid, the target it promised) from a result row.

    Classic rows carry neither key by that name -- the level IS the target and
    N^2 is the payout -- which is the one place the two modes' rows differ in
    shape rather than only in value.
    """
    if mode == "skat":
        return res["stake"], res["target"]
    return res["level"] ** 2, res["level"]


@pytest.mark.parametrize("mode", ["classic", "skat"])
def test_no_trick_is_ever_skipped_while_overtricks_pay(mode):
    """Replayed trick by trick: the predicate must be False at EVERY ply, not
    merely at the ones a finished game happens to expose. Stopping anywhere
    would silently drop tricks the declarer could still have scored on."""
    import random as _r
    plies = 0
    for seed in range(60):
        g = E.new_game(["alice", "bob"], _r.Random(seed), 0, mode=mode)
        if mode == "skat":
            E.apply_skat_bid(g, 0, E.SKAT_BASE[2] * 1)
            E.apply_pass(g, 1)
            E.apply_hand(g, 0)
            E.apply_declare(g, 0, 2, 1)
            E.apply_kontra(g, 1, False)
        else:
            E.apply_bid(g, 0, 1, 2)
            E.apply_pass(g, 1)
            E.apply_swap(g, 0, None, None)
            E.apply_double(g, 1, False)
        while g["phase"] == "play":
            assert not E._score_is_settled(g), (
                f"seed {seed}: the round settled at trick {g['trick']} while "
                "every remaining trick still moves the score")
            plies += 1
            s = E.to_play(g)
            E.apply_play(g, s, E.legal_moves(g, s)[-1])
        assert g["trick"] == E.NTRICKS
    assert plies >= 60 * E.NTRICKS, f"only {plies} plies — the sweep went short"


@pytest.mark.parametrize("mode", ["classic", "skat"])
def test_a_contract_that_cannot_be_MADE_still_plays_on(mode):
    """The asymmetry, and it is deliberate. Being mathematically set does not
    settle the SCORE: the defender is paid (N-1) + 4 x shortfall and every
    remaining trick still moves the shortfall, so holding a busted declarer
    down is a real contest rather than dead time."""
    hopeless = None
    for seed in range(400):
        g = _drive(mode, seed, level=E.MAX_LEVEL, denom=4, pick=0)
        if not g["result"]["made"] and not g["result"]["null"]:
            hopeless = g
            break
    assert hopeless is not None, f"no seed in 400 busted a {mode} contract"
    assert hopeless["trick"] == E.NTRICKS, "a set contract runs to thirteen"
    assert hopeless["result"]["ended_early"] is False
    assert sum(hopeless["pts"]) == _pool_of(hopeless)


@pytest.mark.parametrize("mode", ["classic", "skat"])
def test_null_gets_no_early_exit_of_its_own(mode):
    """It used to end the round the moment the declarer took a scoring trick --
    correct while Null was a flat CONTRACT, meaningless now that the contract
    underneath it is still being scored on points."""
    ducked = None
    for seed in range(400):
        g = _drive(mode, seed, level=6, denom=2, pick=0)
        if g["result"]["null"]:
            ducked = g
            break
    assert ducked is not None, f"no seed in 400 reached Null in {mode}"
    assert ducked["trick"] == E.NTRICKS
    assert ducked["result"]["ended_early"] is False
    assert sum(ducked["pts"]) == _pool_of(ducked)
    decl = ducked["result"]["declarer"]
    assert ducked["result"]["scores"][decl] == (
        E.SKAT_NULL_VALUE if mode == "skat" else E.NULL_MAKE)


# --- card scoring (2026-08-09): the cards captured are the points ------------


def test_card_values_price_the_middle_ranks_up_and_the_ends_down():
    """9/10/J/Q are +2, 7/8/K/A are -1 -- and the whole deck sums to +16, so
    the dealt-in pool is 16 minus whatever the six out-cards are worth."""
    assert E.CARD_VALUES == [-1, -1, 2, 2, 2, 2, -1, -1]
    assert E.CARD_POOL == 16
    for c in range(E.NCARD):
        want = 2 if E.RANK_NAMES[E.rank(c)] in ("9", "10", "J", "Q") else -1
        assert E.card_points(c) == want, E.card_name(c)
    assert E.uses_card_points("skat")
    assert not E.uses_card_points("classic") and not E.uses_card_points("minor")
    # The parity pool is meaningless for a card-scored mode and must fail loud
    # rather than read 5.
    assert E.pool_for("skat") is None
    assert E.pool_for("classic") == 5 and E.pool_for("minor") == -1


def test_a_skat_round_scores_by_the_cards_captured():
    """Recount every trick off the public record: the winner banks the SUM of
    the trick's two cards (-2, +1 or +4), and `etricks` marks exactly the
    positive ones -- which is what the Null consolation means by a scoring
    trick in this currency."""
    for seed in range(8):
        g = _drive("skat", seed, level=2, denom=seed % 4, pick=0)
        assert g["trick"] == E.NTRICKS
        h = g["history"]
        pts, et = [0, 0], [0, 0]
        for t in range(E.NTRICKS):
            a, b = h[2 * t], h[2 * t + 1]
            winner = b[0] if E.beats(a[1], b[1], g["trump"]) else a[0]
            v = E.card_points(a[1]) + E.card_points(b[1])
            assert v in (-2, 1, 4), "a trick is two cards from {-1, +2}"
            pts[winner] += v
            if v > 0:
                et[winner] += 1
        assert pts == g["pts"], f"seed {seed}: recount diverged"
        assert et == g["etricks"], f"seed {seed}: scoring-trick count diverged"
        assert sum(pts) == E.played_pool(g)


def test_the_parity_modes_are_untouched_by_card_scoring():
    """Classic still pays the trick NUMBER's value; a recount by cards must
    generally disagree with it, or the two currencies collapsed silently."""
    diverged = False
    for seed in range(6):
        g = _drive("classic", seed, level=1, denom=seed % 4, pick=0)
        assert sum(g["pts"]) == E.POOL
        h = g["history"]
        card_pts = [0, 0]
        for t in range(E.NTRICKS):
            a, b = h[2 * t], h[2 * t + 1]
            winner = b[0] if E.beats(a[1], b[1], g["trump"]) else a[0]
            card_pts[winner] += E.card_points(a[1]) + E.card_points(b[1])
        diverged |= card_pts != g["pts"]
    assert diverged, "classic scored exactly like cards on every seed -- vacuous"


def test_the_view_flags_card_scoring_and_ships_the_values():
    skat = _declared()
    v = E.view_for(skat, 0)
    assert v["card_pts"] is True
    assert v["card_values"] == E.CARD_VALUES
    # A card-scored trick has no value until both cards are down, so the
    # per-trick label is 0 and the client renders off the cards instead.
    assert v["trick_value"] == 0
    import random as _r
    classic = E.new_game(["a", "b"], _r.Random(5))
    cv = E.view_for(classic, 0)
    assert cv["card_pts"] is False and cv["card_values"] is None


def test_the_deal_snapshot_says_it_was_card_scored():
    """The DD review replays the round under the scoring it was PLAYED at, and
    a snapshot from before the change has no `cards` key -- absent means the
    parity, which is exactly what those rounds were."""
    skat = _declared()
    assert skat["deal"]["cards"] is True
    import random as _r
    classic = E.new_game(["a", "b"], _r.Random(6))
    E.apply_bid(classic, 0, 1, 0)
    E.apply_pass(classic, 1)
    E.apply_swap(classic, 0, None, None)
    E.apply_double(classic, 1, False)
    assert classic["deal"]["cards"] is False


# --- must head the trick (2026-08-10) ----------------------------------------


def test_must_head_forces_a_beating_card_when_one_can_follow(monkeypatch):
    """The rule, and the two halves it must NOT touch: a lead is never
    constrained, and a void seat may still play anything (ruffing stays
    optional). Driven over real deals rather than a hand-built position, so it
    covers the pile tops counting as followable cards."""
    import random as _r
    # SHELVED but kept live: drive it through the flag, the same way the
    # overtrick shelf drives `_score_is_settled`.
    monkeypatch.setitem(E.MUST_HEAD, "skat", True)
    bound = voids = 0
    for seed in range(40):
        g = _drive_to_play(seed)
        while g["phase"] == "play":
            seat = E.to_play(g)
            legal = E.legal_moves(g, seat)
            if g["led"] is None:
                assert set(legal) == set(E.playable(g, seat)), "a lead is free"
            else:
                ls = E.esuit(g["led"], g["trump"])
                follow = [c for c in E.playable(g, seat)
                          if E.esuit(c, g["trump"]) == ls]
                if not follow:
                    assert set(legal) == set(E.playable(g, seat)), \
                        "a void seat is never forced to ruff"
                    voids += 1
                elif any(E.beats(g["led"], c, g["trump"]) for c in follow):
                    assert all(E.beats(g["led"], c, g["trump"]) for c in legal), \
                        f"seed {seed}: a duck survived must-head"
                    if len(legal) < len(follow):
                        bound += 1
                else:
                    assert set(legal) == set(follow), "nothing beats: follow stands"
            E.apply_play(g, seat, legal[_r.Random(seed * 97 + g["trick"]).randrange(len(legal))])
    assert bound > 0, "must-head never bound -- the test proves nothing"
    assert voids > 0, "no void seat arose -- the ruff half is untested"


def test_must_head_is_shelved_off_in_every_shipped_mode():
    """SHELVED the day it shipped -- see `MUST_HEAD` for the measurement. The
    rule is off everywhere; the tests around it drive it through the flag so
    the branch stays live rather than rotting into something that no longer
    compiles against the state around it."""
    for mode in E.MODES:
        assert E.must_head_mode(mode) is False, mode
    assert E.must_head_mode("nonsense") is False


def test_a_classic_room_may_still_duck_under_a_winner():
    """The parity modes are UNTOUCHED, and this is the case that proves it:
    a follower holding a winner and a loser keeps both options."""
    import random as _r
    ducked = False
    for seed in range(60):
        g = E.new_game(["a", "b"], _r.Random(seed), 0, mode="classic")
        E.apply_bid(g, 0, 1, 2)
        E.apply_pass(g, 1)
        E.apply_swap(g, 0, None, None)
        E.apply_double(g, 1, False)
        while g["phase"] == "play" and not ducked:
            seat = E.to_play(g)
            legal = E.legal_moves(g, seat)
            if g["led"] is not None:
                w = [c for c in legal if E.beats(g["led"], c, g["trump"])]
                if w and len(w) < len(legal):
                    ducked = True     # a winner AND a loser both offered
            E.apply_play(g, seat, legal[0])
        if ducked:
            break
    assert ducked, "classic never offered a duck under a winner"


def test_the_view_says_when_must_head_is_binding(monkeypatch):
    """The board's hint is the ENGINE's answer, not a client mirror -- the
    client's `beats` is label-only and does not know Grand."""
    assert E.view_for(_declared(), 0)["must_head"] is False, "shelved by default"
    monkeypatch.setitem(E.MUST_HEAD, "skat", True)
    g = _declared()
    v = E.view_for(g, E.to_play(g))
    assert v["must_head"] is True, "the room's rule is public from the start"
    assert v["must_head_now"] is False, "nothing is led yet"
    classic = E.new_game(["a", "b"], None)
    assert E.view_for(classic, 0)["must_head"] is False


def _drive_to_play(seed: int) -> dict:
    """A skat game driven to the opening lead on a fixed contract."""
    import random as _r
    g = E.new_game(["alice", "bob"], _r.Random(seed), 0, mode="skat")
    E.apply_skat_bid(g, 0, E.SKAT_BASE[2] * 3)
    E.apply_pass(g, 1)
    E.apply_hand(g, 0)
    E.apply_declare(g, 0, 2, 3)
    E.apply_kontra(g, 1, False)
    return g
