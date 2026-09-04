from games.orbit import engine
from games.orbit.persist import compact_state, expand_state


def test_persistence_round_trip_packs_rng_without_mutating_live_state():
    room = {"status": "playing", "game": engine.new_game(["A", "B"], seed=3)}
    original_rng = room["game"]["rng_state"]
    compact = compact_state(room)
    assert compact is not room
    assert isinstance(compact["game"]["rng_state"][1], dict)
    assert room["game"]["rng_state"] is original_rng
    assert expand_state(compact) == room
