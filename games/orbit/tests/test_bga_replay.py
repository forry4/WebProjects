"""The BGA replay DRIVER, held to games the engine itself produced.

`AGENTS.md` makes BGA replays Orbit's parity oracle. An oracle you have not calibrated
will blame the thing it is measuring: on Rag Tag, a per-turn comparison once accused every
card in the game of being wrong at 0.6-0.9, which was impossible next to 27 exact
reproductions, and the tool was wrong rather than the engine.

So this pins the half of the harness that has nothing to do with BGA. The intents here are
known-good by construction -- they came out of `legal_moves` -- so a failure is the
driver, never the rules and never the parse. When a real log eventually fails, that is
what makes "the parser or the rules" a sound conclusion instead of a guess.

No corpus is involved and none is needed, so this runs everywhere and always: the repo
bans a test that opts out of the state it means to exercise.
"""
import json
import random

from games.orbit import engine
from games.orbit.tools import bga_replay as replay


def test_a_recorded_game_replays_to_an_identical_final_state():
    replay.selftest(12)


def test_it_replays_the_randomly_configured_boards_too():
    """The `sun` layout is one fixed configuration; `random` moves the board sides."""
    replay.selftest(12, configuration="random")


def test_the_driver_notices_when_a_replay_stops_short():
    """A replay that quietly consumed half its log would otherwise 'pass'."""
    played, intents = replay.record(3)
    fresh = engine.new_game(["A", "B"], seed=3, configuration="sun")
    used = replay.drive(fresh, intents[:-4])
    assert used == len(intents) - 4
    assert replay.fingerprint(fresh) != replay.fingerprint(played)


def test_an_intent_the_engine_never_offered_is_loud():
    """The whole point of matching against `legal_moves` rather than building a move."""
    game = engine.new_game(["A", "B"], seed=5, configuration="sun")
    try:
        replay.drive(game, [{"action": "recruit", "card_id": -1}])
    except LookupError as exc:
        assert "no legal move matches" in str(exc)
    else:
        raise AssertionError("a fabricated move was accepted")


def test_every_action_the_engine_can_offer_is_known_to_the_harness():
    """`as_intent` raises on an unknown action, so a new one cannot pass through silently.

    Derived from real play rather than a hand-written list -- a hardcoded roster only
    guards the vocabulary SHRINKING, which is the wrong direction.
    """
    seen = set()
    for seed in range(6):
        chooser = random.Random(seed)
        game = engine.new_game(["A", "B"], seed=seed, configuration="random")
        for _ in range(1500):
            if engine.is_over(game):
                break
            moves = engine.legal_moves(game, replay.whose_move(game))
            if not moves:
                break
            seen.update(m.get("action") for m in moves)
            engine.apply_move(game, replay.whose_move(game), chooser.choice(moves))
    assert seen, "no moves were generated at all"
    assert seen <= set(replay.ACTIONS), f"actions the harness does not know: {seen - set(replay.ACTIONS)}"


def test_the_bga_half_refuses_to_guess():
    """`parse_actions` must stay unwritten until it can be written against real logs.

    A parser guessed at BGA's event names matches nothing and stalls the replay, which
    presents as a rules bug -- the failure mode this whole build order exists to avoid.
    Delete this test when the parser lands; until then it keeps the placeholder honest.
    """
    try:
        replay.parse_actions([])
    except NotImplementedError as exc:
        assert "log_inspect" in str(exc)
    else:
        raise AssertionError("parse_actions returned something -- update these tests")


def test_a_move_is_identified_by_all_of_itself():
    """`choose` is polymorphic; keying it on one field matched the wrong pending decision.

    Caught by the selftest on its first run, and cheap to pin: two different `choose`
    payloads must not compare equal just because they share an action.
    """
    a = {"action": "choose", "planet": "mars"}
    b = {"action": "choose", "tier": 2}
    assert replay.as_intent(a) != replay.as_intent(b)
    assert replay.as_intent(a) == json.loads(json.dumps(a))
