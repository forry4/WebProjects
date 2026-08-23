"""Nothing hidden may reach a wire that should not see it.

These assert against the WHOLE SERIALIZED PAYLOAD of a REAL in-progress game, not
a synthetic dict. That is not fussiness: CoC's redaction was correct at the top
level for months while a nested undo snapshot shipped the same four hidden keys
to every client, and a test built on a hand-made game dict cannot catch that
shape of bug. Play a real game, serialize what a real socket would receive, and
search the bytes.

WHAT IS SECRET IN RAG TAG, and why it matters more than it looks:

* Your Fight Deck's ORDER is very nearly the whole game. Both players know which
  cards exist -- the fighters are face up and the decks are public knowledge --
  so the only thing you are guessing at is the SEQUENCE, and where they slid this
  round's card into it. Leak that and there is nothing left to play.
* Both Build Decks are hidden from BOTH players, because their order decides the
  next three cards drawn.
* An unsubmitted build choice, since the whole step is a simultaneous secret.
* `rng_state`, which predicts every Scheme reveal to come.
"""

from __future__ import annotations

import json
import random

from games.rag_tag import engine as E
from games.rag_tag import main as m


def _game_in_progress(seed=4, rounds=3):
    """A real game played a few rounds in, with random legal moves."""
    rng = random.Random(seed)
    game = E.new_game(["alice", "bob"], seed=seed)
    for _ in range(4000):
        if game["winner"] is not None or game["round"] > rounds:
            break
        acted = False
        for pid in ("alice", "bob"):
            seat = E.seat_of(game, pid)
            moves = E.legal_moves(game, seat)
            if moves:
                E.apply_move(game, pid, rng.choice(moves))
                acted = True
        if not acted:
            E.advance(game)
    return game


def _payload(game, viewer):
    """Exactly the bytes a socket for `viewer` would be sent."""
    m.ROOMS["red1"] = {
        "players": {"alice": "Alice", "bob": "Bob"},
        "host": "alice", "status": "playing", "game": game,
        "meta": {"alice": {"token": "TOKEN-ALICE"}, "bob": {"token": "TOKEN-BOB"}},
        "sockets": {}, "vs_ai": False, "ai_player": None,
    }
    try:
        return json.dumps(m.mk_room_state("red1", viewer_pid=viewer))
    finally:
        m.ROOMS.pop("red1", None)


def test_the_opponents_fight_deck_order_never_ships():
    game = _game_in_progress()
    blob = _payload(game, "alice")
    view = json.loads(blob)["game"]

    assert view["fight_deck"] == game["fight_deck"][0], "your own order is yours"
    assert view["fight_deck_counts"][1] == len(game["fight_deck"][1])

    # The opponent's ORDER is the secret, so look for the sequence rather than
    # membership: every instance id appears somewhere legitimately (the
    # `instances` table is public -- it says which card each id IS, which both
    # players already know from the face-up fighters).
    theirs = game["fight_deck"][1]
    if len(theirs) >= 2:
        assert json.dumps(theirs)[1:-1] not in blob, (
            "the opponent's Fight Deck sequence appears verbatim in the payload")


def test_neither_build_deck_ships_to_anyone():
    game = _game_in_progress()
    for viewer in ("alice", "bob", None):
        blob = _payload(game, viewer)
        for seat in (0, 1):
            deck = game["build_deck"][seat]
            assert len(deck) > 3
            assert json.dumps(deck[:4])[1:-1] not in blob, (
                f"build deck {seat} order leaked to {viewer}")
        assert '"build_deck"' not in blob


def test_rng_state_never_ships():
    game = _game_in_progress()
    for viewer in ("alice", "bob", None):
        blob = _payload(game, viewer)
        assert "rng_state" not in blob
        assert str(game["rng_state"][1][:4])[1:-1] not in blob


def _at_a_build_step(seed=6):
    """A real game paused at a BUILD! step with neither player submitted yet."""
    rng = random.Random(seed)
    game = E.new_game(["alice", "bob"], seed=seed)
    for _ in range(4000):
        if game["winner"] is not None:
            break
        if game["phase"] == "build" and game["build_choice"] == [None, None]:
            return game
        acted = False
        for pid in ("alice", "bob"):
            moves = E.legal_moves(game, E.seat_of(game, pid))
            if moves:
                E.apply_move(game, pid, rng.choice(moves))
                acted = True
        if not acted:
            E.advance(game)
    raise AssertionError("could not reach a BUILD! step")


def test_an_unsubmitted_build_choice_stays_secret():
    game = _at_a_build_step()

    E.build_submit(game, "alice", game["build_offer"][0][0], 0)
    blob = _payload(game, "bob")
    assert '"build_choice"' not in blob
    view = json.loads(blob)["game"]
    assert view["build_submitted"] == [True, False], (
        "THAT they have submitted is public; WHAT they chose is not")
    assert view["build_offer"] == game["build_offer"][1], "your own three are yours"
    assert json.dumps(game["build_offer"][0])[1:-1] not in blob, (
        "the opponent's three drawn cards leaked")


def test_the_draft_hand_is_secret_until_it_is_played():
    game = E.new_game(["alice", "bob"], seed=9)
    blob = _payload(game, "alice")
    view = json.loads(blob)["game"]
    assert view["draft_hand"] == game["draft_hands"][0]
    for fid in game["draft_hands"][1]:
        assert f'"{fid}"' not in blob, f"the opponent's draft hand leaked {fid}"


def test_a_pending_sub_decision_only_reaches_the_player_it_belongs_to():
    """The Fey Folk's Character choice is theirs alone to see."""
    game = E.new_game(["alice", "bob"], seed=1)
    game["draft_picks"] = [["the_fey_folk", "golem"], ["mordred", "joan"]]
    game["draft_hands"] = [[], []]
    E._begin_order(game)
    assert game["pending_kind"] == "choose_character"

    mine = json.loads(_payload(game, game["pending_pid"]))["game"]
    theirs = json.loads(_payload(game, "bob" if game["pending_pid"] == "alice"
                                 else "alice"))["game"]
    assert mine["pending"] is not None and mine["pending_is_yours"]
    assert theirs["pending"] is None and not theirs["pending_is_yours"]
    assert theirs["pending_kind"] == "choose_character", (
        "the other player still needs to know something is being waited on")
