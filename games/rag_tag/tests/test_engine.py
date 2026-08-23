"""Rules tests.

Most of these rig an exact position rather than playing to it: pick the two
teams, stack both Fight Decks with named cards, resolve one turn, and assert what
moved. That is the only way to test a simultaneous game -- there is no "make a
move and see", both cards land at once.

The soak at the bottom is the other half, and it derives its roster from
`fighters.ROSTER` so the next fighter added is covered without anyone remembering.
"""

from __future__ import annotations

import random

import pytest

from games.rag_tag import engine as E
from games.rag_tag.fighters import CARDS, ROSTER, STARTING_CARD


# ---------------------------------------------------------------- rigging

def rig(team0, team1, deck0=None, deck1=None, seed=1):
    """A game in the FIGHT! phase with both teams and both decks chosen.

    `deck0`/`deck1` are lists of card ids, top first. Omit to use the two
    Starting Cards, which is what a real first round holds.
    """
    game = E.new_game(["A", "B"], seed=seed)
    game["draft_picks"] = [list(team0), list(team1)]
    game["draft_hands"] = [[], []]
    E._begin_order(game)

    for seat, cids in ((0, deck0), (1, deck1)):
        if cids is None:
            continue
        used: list[int] = []
        for cid in cids:
            used.append(_take(game, seat, cid))
        game["fight_deck"][seat] = used

    game["order_choice"] = [0, 0]
    game["phase"] = "fight"
    return game


def _take(game, seat, cid):
    """Pull one unplayed instance of `cid` out of that seat's decks."""
    for pile in (game["build_deck"][seat], game["fight_deck"][seat]):
        for inst in pile:
            if game["instances"][inst]["cid"] == cid:
                pile.remove(inst)
                return inst
    raise AssertionError(f"seat {seat} has no card {cid}")


def one_turn(game):
    """Resolve exactly one turn, without running on into the next."""
    E._fight_turn(game)


def f(game, seat, slot):
    return E.fighter(game, seat, slot)


def hp(game, seat, slot):
    return E.hp_value(f(game, seat, slot))


def set_hp(game, seat, slot, value):
    fighter = f(game, seat, slot)
    for i, space in enumerate(E.track_of(fighter)):
        if space["kind"] == "hp" and space["hp"] == value:
            fighter["hp"] = i
            return
    raise AssertionError(f"no HP {value} on that track")


# ------------------------------------------------------------------ setup

def test_the_draft_deals_half_picks_one_swaps_and_picks_again():
    game = E.new_game(["A", "B"], seed=3)
    assert game["phase"] == "draft"
    assert len(game["draft_hands"][0]) == len(game["draft_hands"][1]) == 6
    assert not set(game["draft_hands"][0]) & set(game["draft_hands"][1])

    left_over = list(game["draft_hands"][0])
    first = left_over[0]
    E.draft_pick(game, "A", first)
    assert game["draft_round"] == 1, "the round only turns over once BOTH have picked"
    E.draft_pick(game, "B", game["draft_hands"][1][0])
    assert game["draft_round"] == 2

    # The five you did not take are now the five they choose from.
    assert set(game["draft_hands"][1]) == set(left_over[1:])


def test_setup_builds_a_two_card_fight_deck_and_an_eighteen_card_build_deck():
    game = rig(["joan", "ching_shih"], ["bodvar", "wong_fei_hung"])
    for seat in (0, 1):
        assert len(game["fight_deck"][seat]) == 2
        assert len(game["build_deck"][seat]) == 18
        starts = {CARDS[game["instances"][i]["cid"]]["id"]
                  for i in game["fight_deck"][seat]}
        team = game["teams"][seat]
        assert starts == {STARTING_CARD[fid] for fid in team}


def test_power_and_health_start_where_the_boards_say():
    game = rig(["joan", "ching_shih"], ["bodvar", "wong_fei_hung"])
    assert f(game, 0, 0)["power"] == 1        # Joan
    assert f(game, 0, 1)["power"] == 2        # Ching Shih
    assert f(game, 1, 0)["power"] == 3        # Bödvar
    assert hp(game, 0, 0) == 18
    assert hp(game, 1, 0) == 11


def test_order_pick_puts_the_chosen_starting_card_on_top():
    game = E.new_game(["A", "B"], seed=5)
    game["draft_picks"] = [["joan", "ching_shih"], ["bodvar", "mordred"]]
    game["draft_hands"] = [[], []]
    E._begin_order(game)
    E.order_pick(game, "A", 1)
    top = game["instances"][game["fight_deck"][0][0]]
    assert top["slot"] == 1, "the fighter you chose leads"


# ------------------------------------------------------------------ combat

def test_attack_reads_power_from_the_START_of_the_turn():
    """Mordred's Dark Power gains 1 Power; that Power does not fuel its own turn."""
    game = rig(["mordred", "joan"], ["golem", "mordred"],
               deck0=[20], deck1=[11])          # Dark Power vs Fist of Clay
    f(game, 0, 0)["power"] = 9                  # over the 8+ gate
    before = hp(game, 1, 0)
    one_turn(game)
    assert hp(game, 1, 0) == before - 9, "used 10, i.e. the Power it gained this turn"
    assert f(game, 0, 0)["power"] == 10


def test_a_block_negates_both_opposing_fighters_attacks():
    game = rig(["mordred", "joan"], ["shango", "golem"],
               deck0=[23], deck1=[112])         # Cloak of Shadow vs Lightning Strike
    f(game, 1, 0)["power"] = 4
    set_hp(game, 0, 0, 10)
    set_hp(game, 0, 1, 10)
    set_hp(game, 1, 1, 10)
    one_turn(game)
    assert hp(game, 0, 0) == 13, "Blocked, and Cloak of Shadow's Bonus healed 3"
    assert hp(game, 0, 1) == 10, "the one aimed at the Partner died too"
    assert hp(game, 1, 1) == 10, (
        "one Block kills the whole Lightning Strike -- including the arm of it "
        "that was aimed at Shango's OWN Partner")


def test_a_block_does_not_stop_direct_damage():
    game = rig(["mordred", "joan"], ["maman_brijit", "golem"],
               deck0=[23], deck1=[60])          # Cloak of Shadow vs Chili Pepper Rum
    set_hp(game, 1, 0, 10)
    one_turn(game)
    assert hp(game, 1, 0) == 9, "she takes her own 1 Direct Damage even when Blocked"


def test_a_successful_block_fires_its_bonus_and_a_lonely_one_does_not():
    caught = rig(["mordred", "joan"], ["golem", "mordred"], deck0=[23], deck1=[11])
    set_hp(caught, 0, 0, 10)
    one_turn(caught)
    assert hp(caught, 0, 0) == 13, "Block caught an Attack, so Heal 3 fired"

    lonely = rig(["mordred", "joan"], ["golem", "mordred"], deck0=[23], deck1=[12])
    set_hp(lonely, 0, 0, 10)
    one_turn(lonely)                            # Self Sacrifice is not an Attack
    assert hp(lonely, 0, 0) == 10, "nothing to Block, so no Bonus Action"


def test_a_zero_power_attack_still_counts_as_an_attack():
    game = rig(["mordred", "joan"], ["shango", "golem"], deck0=[23], deck1=[111])
    f(game, 1, 0)["power"] = 0                  # Shango's Base Power really is 0
    set_hp(game, 0, 0, 10)
    one_turn(game)
    assert hp(game, 0, 0) == 13, "a 0-Power Attack is an Attack, so the Bonus fired"


def test_heal_and_damage_net_into_one_movement():
    """The rulebook's own worked example: a +3 Heal into a 2-Power Attack is +1."""
    game = rig(["ching_shih", "golem"], ["joan", "mordred"],
               deck0=[75], deck1=[31])          # Gunpowder Wine vs Hand of the Righteous
    f(game, 1, 0)["power"] = 2
    set_hp(game, 0, 0, 10)
    one_turn(game)
    assert hp(game, 0, 0) == 11


def test_cancel_makes_the_other_card_contribute_nothing():
    game = rig(["the_fey_folk", "golem"], ["golem", "mordred"],
               deck0=[53], deck1=[11])          # Entanglement vs Fist of Clay
    game["fighters"][0][0]["character"] = "elf"
    game["fighters"][0][0]["chars"]["elf"] = "active"
    game["fighters"][0][0]["hp"] = E._start_index(E.track_of(f(game, 0, 0)))
    before = hp(game, 0, 0)
    one_turn(game)
    assert hp(game, 0, 0) == before


# ------------------------------------------------------- tracks and icons

def test_a_stop_halts_the_marker_the_moment_it_lands():
    """The Wild Bunch move one space a turn however big the hit."""
    game = rig(["the_wild_bunch", "golem"], ["bodvar", "mordred"],
               deck0=[104], deck1=[122])        # Back to the Hideout vs Berserk!
    f(game, 1, 0)["power"] = 9
    set_hp(game, 0, 0, 5)
    one_turn(game)
    assert hp(game, 0, 0) == 4, "nine damage, one space"


def test_a_stop_halts_healing_too():
    game = rig(["the_wild_bunch", "golem"], ["golem", "mordred"],
               deck0=[105], deck1=[13])         # Outlaw Doc; Golem heals partner 1
    set_hp(game, 0, 0, 2)
    one_turn(game)
    assert hp(game, 0, 0) == 2, "the Wild Bunch was not the one being healed"


def test_a_health_track_icon_fires_when_passed_and_not_when_left():
    """The Golem's +1 Power sits at 20. Passing it pays; stepping off it does not."""
    game = rig(["golem", "mordred"], ["bodvar", "joan"],
               deck0=[12], deck1=[122])         # Self Sacrifice vs Berserk!
    f(game, 1, 0)["power"] = 2
    set_hp(game, 0, 0, 21)
    start_power = f(game, 0, 0)["power"]
    one_turn(game)
    assert hp(game, 0, 0) == 19
    assert f(game, 0, 0)["power"] == start_power - 1 + 1, "passed the +1 Power space"

    game2 = rig(["golem", "mordred"], ["joan", "bodvar"],
                deck0=[13], deck1=[33])          # both heal, nobody attacks
    set_hp(game2, 0, 0, 20)
    was = f(game2, 0, 0)["power"]
    one_turn(game2)
    assert f(game2, 0, 0)["power"] == was, "sitting on an icon and leaving pays nothing"


def test_joans_divine_voice_dial_steps_clockwise_off_the_halo():
    game = rig(["joan", "golem"], ["mordred", "bodvar"], deck0=[30], deck1=[24])
    assert f(game, 0, 0)["tracks"]["divine_voice"] == -1, "starts on the central Halo"
    was = f(game, 0, 0)["power"]
    one_turn(game)
    assert f(game, 0, 0)["tracks"]["divine_voice"] == 0
    assert f(game, 0, 0)["power"] == was + 1, "the top-right space grants 1 Power"


def test_ching_shihs_fleet_is_capped_at_twenty():
    game = rig(["ching_shih", "golem"], ["mordred", "joan"], deck0=[71], deck1=[24])
    f(game, 0, 0)["tracks"]["navigation"] = 19
    one_turn(game)
    assert f(game, 0, 0)["tracks"]["navigation"] == 20, "gains past 20 are ignored"


def test_bodvar_transforms_at_the_top_of_the_rage_track():
    game = rig(["bodvar", "golem"], ["mordred", "joan"], deck0=[120], deck1=[24])
    board = E.FIGHTERS["bodvar"]["special_track"]
    f(game, 0, 0)["tracks"]["rage"] = len(board["spaces"]) - 2
    f(game, 0, 0)["power"] = 5
    one_turn(game)
    hero = f(game, 0, 0)
    assert hero["face"] == "berserker_bear"
    assert hero["power"] == 8, "+3 Power applies, and then he flips"
    assert E.hp_value(hero) == 8, "the Bear opens on his Power cubes"


def test_maman_brijit_comes_back_from_past_the_ko_spaces():
    game = rig(["maman_brijit", "golem"], ["bodvar", "joan"],
               deck0=[63], deck1=[122])         # Sacrifice of Love vs Berserk!
    f(game, 1, 0)["power"] = 12
    set_hp(game, 0, 0, 2)
    one_turn(game)
    hero = f(game, 0, 0)
    assert not E.is_ko(hero), "she is pushed PAST both KO spaces, not onto one"
    assert E.hp_value(hero) == 4, "and returns to 4 at the end of the turn"
    assert game["winner"] is None


# ------------------------------------------------------------- the Fey Folk

def test_a_fey_folk_character_becomes_a_spirit_and_the_next_is_chosen():
    game = rig(["the_fey_folk", "golem"], ["bodvar", "joan"],
               deck0=[52], deck1=[122])
    game["fighters"][0][0]["character"] = "fairy"
    game["fighters"][0][0]["chars"]["fairy"] = "active"
    set_hp(game, 0, 0, 1)
    f(game, 1, 0)["power"] = 6
    one_turn(game)
    hero = f(game, 0, 0)
    assert hero["chars"]["fairy"] == "spirit"
    assert hero["tracks"]["spirits"] == 2, "they begin on 1 and this is the first death"
    assert game["pending_kind"] == "choose_character"
    assert game["winner"] is None, "a Spirit is not a KO"

    E.choose_character(game, "A", game["pending"]["options"][0])
    assert f(game, 0, 0)["character"] is not None


def test_the_fey_folk_lose_only_to_their_own_card_with_all_three_gone():
    game = rig(["the_fey_folk", "golem"], ["mordred", "joan"],
               deck0=[50], deck1=[24])          # All Legends Must Pass
    hero = f(game, 0, 0)
    hero["tracks"]["spirits"] = 4
    hero["chars"] = {k: "spirit" for k in hero["chars"]}
    hero["character"] = None
    hero["hp"] = None
    one_turn(game)
    assert game["winner"] == 1


# ------------------------------------------------------------------ ending

def test_a_ko_ends_the_fight():
    game = rig(["mordred", "joan"], ["bodvar", "golem"],
               deck0=[24], deck1=[122])
    f(game, 1, 0)["power"] = 30
    set_hp(game, 0, 0, 3)
    one_turn(game)
    assert game["winner"] == 1


def test_both_teams_down_in_one_turn_is_a_draw():
    game = rig(["golem", "joan"], ["bodvar", "mordred"],
               deck0=[11], deck1=[122])         # Fist of Clay vs Berserk!
    f(game, 0, 0)["power"] = 30
    f(game, 1, 0)["power"] = 30
    set_hp(game, 0, 0, 2)
    set_hp(game, 1, 0, 2)
    one_turn(game)
    assert game["winner"] == "draw"


def test_incineration_beats_a_double_ko():
    game = rig(["shango", "joan"], ["bodvar", "golem"],
               deck0=[110], deck1=[122])        # Aflame! vs Berserk!
    f(game, 1, 0)["tokens"]["aflame"] = 4       # the fifth finishes them
    f(game, 1, 0)["power"] = 30
    set_hp(game, 0, 0, 2)
    set_hp(game, 1, 0, 2)
    one_turn(game)
    assert game["winner"] == 0, "burning is a LOSS for that side, not a draw"


def test_drag_you_to_hell_turns_a_loss_into_a_win():
    game = rig(["mephisto", "joan"], ["bodvar", "golem"],
               deck0=[43], deck1=[122])
    f(game, 1, 0)["power"] = 30
    set_hp(game, 0, 0, 2)
    one_turn(game)
    assert game["winner"] == 0


def test_a_depleted_build_deck_is_a_draw():
    game = rig(["joan", "ching_shih"], ["bodvar", "wong_fei_hung"])
    for seat in (0, 1):
        game["build_deck"][seat] = game["build_deck"][seat][:2]
    E.advance(game)
    assert game["winner"] == "draw"
    assert "depleted" in game["log"][-1]


# -------------------------------------------------------------- the BUILD!

def test_the_fight_deck_is_never_shuffled():
    game = rig(["joan", "ching_shih"], ["mordred", "golem"])
    order = list(game["fight_deck"][0])
    E.advance(game)
    assert game["phase"] == "build"
    assert game["fight_deck"][0] == order, "played cards keep their order"


def test_build_inserts_where_you_ask_and_discards_to_the_bottom():
    game = rig(["joan", "ching_shih"], ["mordred", "golem"])
    E.advance(game)
    offer = list(game["build_offer"][0])
    kept, tail = offer[1], list(game["build_deck"][0])
    E.build_submit(game, "A", kept, 1, bottom_last=offer[2])
    # Drive the second submission by hand: a real one advances straight into the
    # next FIGHT!, and the thing under test is the state at THIS instant.
    game["build_choice"][1] = {"inst": game["build_offer"][1][0], "pos": 0,
                               "discard": game["build_offer"][1][1:]}
    E._finish_build(game)
    assert game["fight_deck"][0][1] == kept, "inserted exactly where asked"
    assert game["build_deck"][0][len(tail):] == [offer[0], offer[2]], (
        "the two you did not keep go to the bottom, in the order you chose")


def test_you_cannot_build_twice_or_out_of_phase():
    game = rig(["joan", "ching_shih"], ["mordred", "golem"])
    with pytest.raises(E.IllegalMove):
        E.build_submit(game, "A", 0, 0)
    E.advance(game)
    kept = game["build_offer"][0][0]
    E.build_submit(game, "A", kept, 0)
    with pytest.raises(E.IllegalMove):
        E.build_submit(game, "A", kept, 0)


def test_an_instant_bonus_fires_after_both_players_have_inserted():
    game = rig(["the_wild_bunch", "golem"], ["mordred", "joan"])
    E.advance(game)
    doc = next(i for i in game["build_deck"][0]
               if CARDS[game["instances"][i]["cid"]]["id"] == 105)
    game["build_offer"][0] = [doc] + game["build_offer"][0][:2]
    set_hp(game, 0, 0, 3)
    E.build_submit(game, "A", doc, 0)
    assert hp(game, 0, 0) == 3, "not until BOTH have inserted"
    game["build_choice"][1] = {"inst": game["build_offer"][1][0], "pos": 0,
                               "discard": game["build_offer"][1][1:]}
    E._finish_build(game)
    assert hp(game, 0, 0) == 4, "Outlaw Doc heals the Wild Bunch 1 on the way in"


# ------------------------------------------------ the two-pass declaration

@pytest.mark.parametrize("dagger_seat", [0, 1])
def test_hidden_dagger_sees_the_opponent_from_either_seat(dagger_seat):
    """A condition about the other card must not depend on which seat holds it.

    Seat 0's card is walked first, so a naive single pass answers "did the
    Opponent Attack?" against a half-declared turn -- and gets it wrong for seat 0
    every time. That is a silent seat bias, invisible except as a losing record.
    """
    teams = (["mordred", "joan"], ["golem", "bodvar"])
    decks = ([22], [11])                        # Hidden Dagger vs Fist of Clay
    if dagger_seat == 1:
        teams, decks = (teams[1], teams[0]), (decks[1], decks[0])
    game = rig(teams[0], teams[1], deck0=decks[0], deck1=decks[1])
    victim = 1 - dagger_seat
    f(game, dagger_seat, 0)["power"] = 5
    set_hp(game, victim, 0, 15)
    before = hp(game, victim, 0)
    one_turn(game)
    assert hp(game, victim, 0) == before, (
        "the Opponent DID Attack, so the Hidden Dagger must not fire")


@pytest.mark.parametrize("blocker_seat", [0, 1])
def test_what_doesnt_kill_you_sees_its_own_attack_blocked_from_either_seat(blocker_seat):
    teams = (["milady", "joan"], ["mordred", "golem"])
    decks = ([92], [23])                        # ...Makes Me Stronger vs Cloak of Shadow
    milady_seat = 1 - blocker_seat
    if blocker_seat == 0:
        teams, decks = (teams[1], teams[0]), (decks[1], decks[0])
    game = rig(teams[0], teams[1], deck0=decks[0], deck1=decks[1])
    was = f(game, milady_seat, 0)["power"]
    one_turn(game)
    assert f(game, milady_seat, 0)["power"] == was + 1, "her Attack was Blocked"


# --------------------------------------------------------------- redaction

def test_the_public_view_keeps_the_hidden_things_hidden():
    game = rig(["joan", "ching_shih"], ["mordred", "golem"])
    E.advance(game)
    view = E.public_view(game, 0)
    assert view["fight_deck"] == game["fight_deck"][0], "your own order is yours"
    assert "build_deck" not in view, "nobody sees a Build Deck's order"
    assert view["build_offer"] == game["build_offer"][0]
    assert "rng_state" not in view

    assert view["fight_deck_counts"] == [len(d) for d in game["fight_deck"]], (
        "the opponent's Fight Deck is a COUNT -- its order is the whole game")


def test_a_spectator_sees_no_hand_at_all():
    game = rig(["joan", "ching_shih"], ["mordred", "golem"])
    view = E.public_view(game, None)
    assert view["fight_deck"] is None
    assert view["draft_hand"] == []
    assert view["build_offer"] == []


# -------------------------------------------------------------------- soak

def _random_game(seed):
    r = random.Random(seed)
    game = E.new_game(["A", "B"], seed=seed)
    for _ in range(4000):
        if game["winner"] is not None:
            return game
        acted = False
        for pid in ("A", "B"):
            seat = E.seat_of(game, pid)
            if game["pending_pid"] == pid:
                E.choose_character(game, pid, r.choice(game["pending"]["options"]))
                acted = True
            elif game["phase"] == "draft" and len(game["draft_picks"][seat]) < game["draft_round"]:
                E.draft_pick(game, pid, r.choice(game["draft_hands"][seat]))
                acted = True
            elif game["phase"] == "order" and game["order_choice"][seat] is None:
                E.order_pick(game, pid, r.randint(0, 1))
                acted = True
            elif game["phase"] == "build" and game["build_choice"][seat] is None:
                E.build_submit(game, pid, r.choice(game["build_offer"][seat]),
                               r.randint(0, len(game["fight_deck"][seat])))
                acted = True
        if not acted:
            E.advance(game)
    raise AssertionError("a game failed to terminate")


def test_random_play_terminates_and_covers_every_fighter():
    seen: set[str] = set()
    outcomes: set = set()
    for seed in range(160):
        game = _random_game(seed)
        assert game["winner"] in (0, 1, "draw")
        outcomes.add(game["winner"])
        for team in game["teams"]:
            seen.update(team)
        for seat in (0, 1):
            for slot in (0, 1):
                fighter = E.fighter(game, seat, slot)
                assert fighter["power"] >= 0
                track = E.track_of(fighter)
                if track and fighter["hp"] is not None:
                    assert 0 <= fighter["hp"] < len(track)
    assert seen == set(ROSTER), f"never drafted: {sorted(set(ROSTER) - seen)}"
    assert outcomes == {0, 1, "draw"}, "random play should reach every outcome"


def test_the_game_state_stays_json_safe():
    import json

    game = _random_game(11)
    round_trip = json.loads(json.dumps(game))
    assert round_trip["winner"] == game["winner"]
    assert round_trip["fighters"] == game["fighters"]
