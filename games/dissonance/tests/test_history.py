"""The lobby's History row describes a MATCH, not the deal that ended it.

A game is rounds played onto a running total until one side reaches 100, so the
final round's score says nothing about who won: a match taken 100-84 whose last
deal was a 9-point make listed as "Won 9-0", and one lost on the opponent
crossing the line listed as a loss on a round the reader could not tell apart
from the whole game.

`list_user_history` reads a STORED result and never the live game (the room is
gone by then), which is why the standing is written onto the result row. These
drive the real function against a temp sqlite file with real played-out matches
in it -- a hand-built row would only pin the shape this test happened to write.
"""

from __future__ import annotations

import random
import sqlite3
import time

import pytest

from core import db as core_db
from games.dissonance import bot
from games.dissonance import engine as E
from games.dissonance import main as m


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point `core.db` at an empty temp file and build the table in it."""
    monkeypatch.setattr(core_db, "DB_PATH", str(tmp_path / "site.db"))
    monkeypatch.setattr(core_db, "TURSO_URL", None)
    m.dissonance_init_db()
    return tmp_path / "site.db"


def _play_round(g, rng):
    guard = 0
    while g["phase"] != "over":
        guard += 1
        assert guard < 300, f"stuck in {g['phase']}"
        seat = E.turn_seat(g)
        if g["phase"] == "auction":
            _, mv = bot.act(g, seat, rng)
            if mv.get("pass"):
                E.apply_pass(g, seat)
            else:
                E.apply_bid(g, seat, mv["level"], mv["denom"])
        elif g["phase"] == "swap":
            _, mv = bot.act(g, seat, rng)
            E.apply_swap(g, seat, mv.get("take"), mv.get("give"))
        elif g["phase"] == "double":
            E.apply_double(g, seat, bot.choose_double(g, seat))
        else:
            E.apply_play(g, seat, bot.choose_card(g, seat))
    return g


def _play_match(seed):
    """A whole match, the way a room plays one: rounds until the target."""
    g = E.new_game(["alice", "bob"], random.Random(seed), opener=0)
    rounds = 0
    while not E.is_over(g):
        g = _play_round(g, random.Random(seed * 10 + rounds))
        rounds += 1
        assert rounds < 60, "the match never reached its target"
        if not E.is_over(g):
            E.next_round(g, 0, g["result"]["round"])
    return g, rounds


def _store(db_path, g, room_id="R1"):
    """Write a finished match as the room server would have saved it."""
    blob = m._encode_state({
        "players": {"alice": "Alice", "bob": "Bob"},
        "host": "alice", "status": "over", "game": g, "meta": {},
        "vs_ai": False, "ai_player": None, "ai_difficulty": "normal",
        "mode": E.mode_of(g),
    })
    now = int(time.time())
    con = sqlite3.connect(db_path)
    try:
        con.execute(
            f"""INSERT INTO {m.TABLE}
                (id,status,player1_id,player1_name,player2_id,player2_name,
                 host_id,state_json,created_at,updated_at)
                VALUES (?,'over','alice','Alice','bob','Bob','alice',?,?,?)""",
            (room_id, blob, now, now))
        con.commit()
    finally:
        con.close()


def test_history_reports_the_match_standing_not_the_last_rounds_score(db):
    g, rounds = _play_match(21)
    _store(db, g)

    row = m.list_user_history("alice")[0]
    seat = E.seat_of(g, "alice")
    match = g["match"]

    assert rounds > 1, "a match to 100 takes more than one deal, or this proves nothing"
    assert [row["your_score"], row["opp_score"]] == [match["scores"][seat],
                                                     match["scores"][1 - seat]]
    assert max(row["your_score"], row["opp_score"]) >= match["target"]
    assert row["you_won"] is (match["scores"][seat] > match["scores"][1 - seat])
    # ...and the round's own score, which is what used to be reported, is a
    # different and much smaller number.
    assert row["your_score"] != g["result"]["scores"][seat] \
        or row["opp_score"] != g["result"]["scores"][1 - seat], \
        "the row is still reporting the final DEAL"


def test_history_says_how_many_rounds_it_took_and_what_it_was_played_to(db):
    g, rounds = _play_match(22)
    _store(db, g)

    row = m.list_user_history("alice")[0]
    assert row["rounds"] == rounds == g["match"]["round"]
    assert row["target"] == g["match"]["target"]
    assert row["abandoned"] is False


def test_both_seats_read_the_same_match_from_their_own_side(db):
    g, _ = _play_match(23)
    _store(db, g)

    a = m.list_user_history("alice")[0]
    b = m.list_user_history("bob")[0]
    assert (a["your_score"], a["opp_score"]) == (b["opp_score"], b["your_score"])
    assert a["you_won"] is not b["you_won"], "exactly one of them won it"
    assert (a["opp_name"], b["opp_name"]) == ("Bob", "Alice")


def test_a_forfeited_match_is_marked_and_still_carries_the_standing(db):
    """Walking out ends the MATCH, so the row is a match row like any other --
    it just says how it ended."""
    g, _ = _play_match(24)
    # Rewind to a live second round and walk out of it, so the standing on the
    # row is a real one rather than a single forfeit.
    g["match"]["over"] = False
    E.next_round(g, 0, g["result"]["round"])
    # PIN the standing rather than inherit whatever the seed happened to produce.
    # `abandon_result` pays the seat left standing `forfeit_value` and banks it;
    # it does NOT hand them the match, so who the ROW calls the winner is decided
    # by the running total. This test is about what the row says, so the total it
    # says it from has to be fixed: seed 24 used to finish with alice ahead and,
    # after the bot stopped valuing two cards it could not see (0cbd0c5), finishes
    # 66-110 the other way -- at which point one forfeit payment does not close a
    # 44-point gap and the assertion below was testing the seed, not the rule.
    alice, bob = E.seat_of(g, "alice"), E.seat_of(g, "bob")
    g["match"]["scores"][alice] = 70
    g["match"]["scores"][bob] = 66
    before = list(g["match"]["scores"])
    g["result"] = E.abandon_result(g, E.seat_of(g, "bob"))
    g["phase"] = "over"
    _store(db, g)

    row = m.list_user_history("alice")[0]
    assert row["abandoned"] is True
    assert row["you_won"] is True, \
        "the seat left standing is paid the forfeit and leads the standing"
    assert row["your_score"] > before[alice], \
        "the forfeit is banked onto the running total, not reported on its own"


def test_a_row_from_before_matches_existed_is_still_read_as_one_round(db):
    """A save with no match dict really is a single round, and really is the
    whole game -- the round's own score is the honest standing for it."""
    g = E.new_game(["alice", "bob"], random.Random(25), opener=0)
    del g["match"]
    g = _play_round(g, random.Random(25))
    assert E.is_over(g) and "match_scores" not in g["result"]
    _store(db, g)

    row = m.list_user_history("alice")[0]
    seat = E.seat_of(g, "alice")
    assert row["your_score"] == g["result"]["scores"][seat]
    assert row["rounds"] == 1
    assert row["target"] is None
    # The contract IS the story for a one-round game, so it is still reported.
    assert row["contract"]["level"] == g["result"]["level"]
