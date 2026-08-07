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

from games.oddtrick import engine as E


# --- helpers ---------------------------------------------------------------


def _skat(opener: int = 0) -> dict:
    return E.new_game(["alice", "bob"], None, opener=opener, mode="skat")


def _settled(value: int = 12, opener: int = 0) -> dict:
    """A skat game with the auction won by the opener at `value`."""
    g = _skat(opener)
    E.apply_skat_bid(g, opener, value)
    E.apply_pass(g, 1 - opener)
    assert g["phase"] == "talon"
    return g


def _declared(value=12, denom=2, level=4, hand=False, sharp=False, open_=False,
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
                for d in range(E.NOTRUMP + 1)
                for lvl in range(E.MIN_LEVEL, E.MAX_LEVEL + 1)}
    for v in E.SKAT_VALUES:
        assert v in products or v == E.SKAT_NULL_VALUE, v
    assert E.SKAT_VALUES == sorted(set(E.SKAT_VALUES)), "no duplicate rungs"
    assert E.SKAT_VALUES[0] == 2 and E.SKAT_VALUES[-1] == 6 * E.MAX_LEVEL


def test_seven_is_the_ladders_only_hole_below_ten():
    """Documenting a real gap rather than pretending the prose was right: 7 is
    not a multiple of any base, so the otherwise dense 2..10 stretch skips it."""
    assert [v for v in range(2, 11) if v not in E.SKAT_VALUES] == [7]


def test_a_number_does_not_say_which_game_is_coming():
    """The mode's entire premise, asserted: several declarations clear 12."""
    reach = [d for d in E.skat_declarable(12)
             if E.SKAT_BASE[d["denom"]] * d["min_level"] == 12]
    assert len(reach) >= 3
    # ...and Null is a fourth reading of a number below its flat value.
    assert E.declare_options(_declare_phase_at(12))["null_ok"] is True


def _declare_phase_at(value: int) -> dict:
    g = _settled(value)
    decl = g["auction"]["declarer"]
    E.apply_hand(g, decl)
    return g


def test_every_legal_bid_is_declarable():
    """Skat's "overbid loses at once" rule has nothing to fire on here.

    The level is the declarer's free choice from 1..12 and no-trump at 12 is the
    ladder's top rung, so no bid can strand its winner. Stretching is punished
    structurally instead — a big number forces a level you cannot make, and past
    20 it locks Null away.
    """
    for v in E.SKAT_VALUES:
        opts = E.skat_declarable(v)
        assert opts, f"bid of {v} had no declarable game"
        assert any(E.SKAT_BASE[o["denom"]] * o["min_level"] >= v for o in opts)


def test_the_price_table_inverts_the_classic_ranking():
    """Deliberate, so the two modes' tables can't be confused: classic ranks
    C < D < H < S < NT; here diamonds are cheap and clubs dear."""
    assert E.SKAT_BASE[1] < E.SKAT_BASE[2] < E.SKAT_BASE[3] < E.SKAT_BASE[0]
    assert E.SKAT_BASE[4] == max(E.SKAT_BASE)


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
    assert g["opener"] == 1, "the opener alternates so passing out is not free"
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
    E.apply_declare(g, decl, 4, 6)          # no-trump x 6 = 36, far past the bid
    assert g["contract"]["value"] == 36
    assert E.skat_target(g) == 6, "the level you declared is the level you owe"


def test_a_bid_past_twenty_locks_null_away():
    """The one place where stretching the auction really removes a game."""
    assert E.declare_options(_declare_phase_at(20))["null_ok"] is True
    g = _declare_phase_at(21)
    assert E.declare_options(g)["null_ok"] is False
    with pytest.raises(ValueError):
        E.apply_declare(g, g["auction"]["declarer"], E.NULL_DENOM, 0)


def test_null_cannot_be_sharpened_and_open_rides_on_sharp():
    g = _declare_phase_at(12)
    decl = g["auction"]["declarer"]
    with pytest.raises(ValueError):
        E.apply_declare(g, decl, E.NULL_DENOM, 0, sharp=True)
    with pytest.raises(ValueError):
        E.apply_declare(g, decl, 2, 4, sharp=False, open_=True)
    # Null Open needs no Sharp -- there is no margin to sharpen.
    E.apply_declare(g, decl, E.NULL_DENOM, 0, sharp=False, open_=True)
    assert g["contract"]["value"] == E.SKAT_NULL_VALUE
    # Null keeps its classic-mode rung so `auction.level`/`denom` mean the same
    # thing downstream in both modes.
    assert g["auction"]["level"] == E.NULL_LEVEL
    assert g["auction"]["denom"] == E.NULL_DENOM


def test_only_the_declarer_declares():
    g = _declare_phase_at(12)
    with pytest.raises(ValueError):
        E.apply_declare(g, 1 - g["auction"]["declarer"], 2, 4)


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
    E.apply_declare(g, decl, 2, 4)
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
        E.apply_declare(g, decl, 2, 4)
    if phase_at == "re":
        E.apply_kontra(g, 1 - decl, True)
    assert g["phase"] == phase_at
    assert E.turn_seat(g) == (decl if seat_is_declarer else 1 - decl)
    assert E.turn_pid(g) == g["seats"][E.turn_seat(g)]


# --- scoring ---------------------------------------------------------------


def _score(g: dict, declarer_pts: int) -> dict:
    """Run the scorer over a declared game held at a chosen point total."""
    decl = g["auction"]["declarer"]
    g["pts"][decl] = declarer_pts
    g["pts"][1 - decl] = E.POOL - declarer_pts
    E._finish(g)
    return g["result"]


def test_making_it_pays_value_times_multiplier():
    g = _declared(value=12, denom=2, level=4)      # hearts x 4 = 12
    res = _score(g, 5)
    assert res["mode"] == "skat"
    assert (res["value"], res["mult"], res["doubling"]) == (12, 1, 1)
    assert res["made"] is True
    assert res["scores"][res["declarer"]] == 12
    assert res["scores"][1 - res["declarer"]] == 0


def test_missing_it_pays_the_defender_the_same_number_plus_the_shortfall():
    g = _declared(value=12, denom=2, level=4)
    res = _score(g, 1)
    assert res["made"] is False and res["short"] == 3
    assert res["scores"][1 - res["declarer"]] == 12 + E.SHORT_PENALTY * 3
    assert res["scores"][res["declarer"]] == 0


def test_sharp_raises_the_bar_and_a_bare_make_now_loses():
    """The margin is SHARP_BONUS, read symbolically — it is a tuned knob (3 was
    measured at 0% of contracts and dropped to 2), so a test that hardcodes it
    fails on the next tuning pass for no reason."""
    bonus = E.SHARP_BONUS
    g = _declared(value=12, denom=2, level=4, sharp=True)
    assert E.skat_target(g) == 4 + bonus
    res = _score(g, 4)      # would have made the plain contract exactly
    assert res["made"] is False, "Sharp promises level + the bonus, not level"
    assert res["short"] == bonus
    assert res["scores"][1 - res["declarer"]] == 12 * 2 + E.SHORT_PENALTY * bonus

    made = _score(_declared(value=12, denom=2, level=4, sharp=True), 4 + bonus)
    assert made["made"] is True and made["scores"][made["declarer"]] == 24
    # Exactly on the bar makes it; one under does not.
    just_under = _score(_declared(value=12, denom=2, level=4, sharp=True), 3 + bonus)
    assert just_under["made"] is False and just_under["short"] == 1


def test_the_full_stack_multiplies_rather_than_adds_to_the_payout():
    g = _declared(value=12, denom=2, level=4, hand=True, sharp=True, open_=True,
                  kontra=True, re=True)
    res = _score(g, 7)
    assert (res["mult"], res["doubling"]) == (4, 4)
    assert res["stake"] == 12 * 4 * 4
    assert res["scores"][res["declarer"]] == 192


def test_kontra_cuts_both_ways():
    """Doubling is not a defender-only weapon -- it doubles the make too."""
    made = _score(_declared(value=12, denom=2, level=4, kontra=True), 5)
    assert made["scores"][made["declarer"]] == 24
    lost = _score(_declared(value=12, denom=2, level=4, kontra=True), 1)
    assert lost["scores"][1 - lost["declarer"]] == 24 + E.SHORT_PENALTY * 3


def test_null_is_flat_and_scores_off_the_scoring_tricks_not_the_points():
    g = _declared(value=12, denom=E.NULL_DENOM, level=0, hand=True)
    decl = g["auction"]["declarer"]
    assert g["contract"]["value"] == E.SKAT_NULL_VALUE
    g["etricks"][decl] = 0
    res = _score(g, -1)     # a dreadful point total is irrelevant to Null
    assert res["made"] is True
    assert res["short"] == 0, "Null is flat; there is no shortfall to scale"
    assert res["scores"][decl] == E.SKAT_NULL_VALUE * 2

    broken = _declared(value=12, denom=E.NULL_DENOM, level=0, hand=True)
    broken["etricks"][broken["auction"]["declarer"]] = 1
    bres = _score(broken, 4)
    assert bres["made"] is False
    assert bres["scores"][1 - bres["declarer"]] == E.SKAT_NULL_VALUE * 2


def test_walking_out_costs_the_declared_game_not_a_classic_square():
    g = _declared(value=12, denom=2, level=4, hand=True, kontra=True)
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
    g = _declared(value=12, denom=2, level=4)
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
    g = _declared(value=12, denom=2, level=4, hand=True)
    for seat in (0, 1):
        assert E.view_for(g, seat)["shown"] is None, \
            "nobody has seen these cards, the declarer included"


def test_open_shows_the_declarers_hand_and_only_from_trick_one():
    g = _settled(12)
    decl = g["auction"]["declarer"]
    E.apply_hand(g, decl)
    E.apply_declare(g, decl, 2, 4, sharp=True, open_=True)
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
    g = _declared(value=12, denom=2, level=4)
    v = E.player_view(g, "nobody")
    assert v["hand"] == [] and v["you"] is None
    assert v["shown"] is None and v["opp_hand"] is None
    assert v["talon"] is None and v["declare"] is None
    assert v["contract"] == g["contract"], "the declaration is public"


# --- the whole round -------------------------------------------------------


def test_a_skat_round_plays_from_the_deal_to_a_scored_result():
    g = _declared(value=12, denom=2, level=4, sharp=True, kontra=True, re=True)
    guard = 0
    while g["phase"] == "play":
        guard += 1
        assert guard <= E.NTRICKS * 2 + 1
        s = E.to_play(g)
        E.apply_play(g, s, E.legal_moves(g, s)[0])
    assert g["phase"] == "over"
    assert g["trick"] == E.NTRICKS
    assert sum(g["pts"]) == E.POOL
    res = g["result"]
    assert res["mode"] == "skat"
    assert res["stake"] == 12 * 2 * 4, "Sharp alone is x2; Kontra + Re is x4"
    winner = res["declarer"] if res["made"] else 1 - res["declarer"]
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
    E.apply_declare(g, 0, 2, 4, sharp=True)
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
    E.apply_move(g, pid0, {"kind": "declare", "denom": 2, "level": 4,
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
    from games.oddtrick import main as m

    g = _declared(value=12, denom=2, level=4, sharp=True, kontra=True, re=True)
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
    """`rust-cores/oddtrick-core/src/skat.rs` is the measurement instrument for
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
           / "rust-cores" / "oddtrick-core" / "src" / "skat.rs")
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
    quit_mid = _declared(value=12, denom=2, level=4, hand=True, kontra=True)
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
    from games.oddtrick import bot

    g = _settled(12)
    decl = g["auction"]["declarer"]
    E.apply_look(g, decl)
    assert g["auction"]["denom"] == -1, "the premise: nothing is declared yet"

    d = bot.swap_denom(g, decl)
    assert 0 <= d <= E.NOTRUMP, d
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
    E.apply_move(g, g["seats"][decl], {"kind": "declare", "denom": 4, "level": 4})
    E.apply_move(g, g["seats"][1 - decl], {"kind": "kontra", "on": False})
    assert g["phase"] == "play"
    assert g["trump"] == E.NOTRUMP and g["contract"]["mult"] == 2
    assert len(g["hands"][decl]) == 7, "no card ever moved in or out"


# --- Null ends the moment it is broken -------------------------------------


def _drive_null(mode: str, seed: int):
    """Play a Null contract out with a fixed policy until the engine stops."""
    import random as _r
    g = E.new_game(["alice", "bob"], _r.Random(seed), 0, mode=mode)
    if mode == "skat":
        E.apply_skat_bid(g, 0, 12)
        E.apply_pass(g, 1)
        E.apply_hand(g, 0)
        E.apply_declare(g, 0, E.NULL_DENOM, 0)
        E.apply_kontra(g, 1, False)
    else:
        E.apply_bid(g, 0, E.NULL_LEVEL, E.NULL_DENOM)
        E.apply_pass(g, 1)
        E.apply_swap(g, 0, None, None)
    while g["phase"] == "play":
        s = E.to_play(g)
        E.apply_play(g, s, E.legal_moves(g, s)[-1])
    return g


@pytest.mark.parametrize("mode", ["classic", "skat"])
def test_a_broken_null_stops_the_moment_the_declarer_takes_a_scoring_trick(mode):
    """Null pays a FLAT amount either way, so once the declarer has won one +2
    trick no remaining card can move the score by a point — playing them out is
    dead time at a table where the result is already settled."""
    broken = None
    for seed in range(400):
        g = _drive_null(mode, seed)
        if not g["result"]["made"]:
            broken = g
            break
    assert broken is not None, f"no seed in 400 broke a {mode} Null"
    res = broken["result"]
    decl = res["declarer"]
    assert broken["phase"] == "over"
    assert broken["trick"] < E.NTRICKS, "a broken Null should not run to thirteen"
    assert res["ended_early"] is True
    assert broken["etricks"][decl] == 1, "it stops at the FIRST scoring trick, not later"
    # ...and the score is exactly what playing it out would have paid.
    assert res["scores"][decl] == 0
    assert res["scores"][1 - decl] > 0


@pytest.mark.parametrize("mode", ["classic", "skat"])
def test_a_made_null_still_runs_all_thirteen_tricks(mode):
    """The early exit must be keyed on the contract being BROKEN, not on Null.
    A Null the declarer is winning has to be played to the end — the thirteenth
    trick can still be the one that breaks it."""
    made = None
    for seed in range(400):
        g = _drive_null(mode, seed)
        if g["result"]["made"]:
            made = g
            break
    assert made is not None, f"no seed in 400 made a {mode} Null"
    assert made["trick"] == E.NTRICKS
    assert made["result"]["ended_early"] is False
    assert sum(made["pts"]) == E.POOL, "a completed round still sums to the pool"


def test_only_null_ends_early():
    """A point contract is never decided before the last trick — the shortfall
    term means every remaining trick can still change the score."""
    g = _declared(value=12, denom=2, level=4)
    while g["phase"] == "play":
        s = E.to_play(g)
        E.apply_play(g, s, E.legal_moves(g, s)[0])
    assert g["trick"] == E.NTRICKS
    assert g["result"]["ended_early"] is False
