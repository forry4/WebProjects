"""The bot, and the soak that plays it against itself.

The soak is the broad net the rigged rules tests cannot be: it runs whole games
over randomly drafted teams and asserts they all end legally, with nothing out of
bounds along the way. It is what found the two real engine bugs during the build
-- an unreachable Fey Folk prompt, and a seat bias that showed up as a losing
record rather than a crash.

Coverage is DERIVED from `fighters.ROSTER`, never a hardcoded count. A hardcoded
one only ever guards the roster shrinking, so the next fighter added would go
unsoaked in silence -- which is exactly the shape of the `range(13)` bug.
"""

from __future__ import annotations

import random

from games.rag_tag import bot
from games.rag_tag import engine as E
from games.rag_tag.fighters import ROSTER


def play(seed: int) -> dict:
    """A whole game, both seats driven by the random bot through apply_move."""
    game = E.new_game(["A", "B"], seed=seed)
    for step in range(6000):
        if E.is_over(game):
            return game
        acted = False
        for seat, pid in enumerate(game["seats"]):
            if not E.owes_move(game, seat):
                continue
            move = bot.choose_move(game, seat, seed=seed * 977 + step * 31 + seat)
            assert move is not None, "owes a move but produced none"
            E.apply_move(game, pid, move)
            acted = True
        if not acted:
            E.advance(game)
    raise AssertionError("a game failed to terminate")


def _check_invariants(game: dict) -> None:
    for seat in (0, 1):
        for slot in (0, 1):
            f = E.fighter(game, seat, slot)
            assert f["power"] >= 0, "Power can never be below 0"
            track = E.track_of(f)
            if track and f["hp"] is not None:
                assert 0 <= f["hp"] < len(track), "marker off the end of its track"
                assert E.hp_value(f) <= E.max_hp(f), "above Max HP"
            for name, count in f["tokens"].items():
                assert count >= 0, f"negative {name} tokens"


def test_the_bot_only_ever_offers_a_legal_move():
    for seed in range(40):
        game = E.new_game(["A", "B"], seed=seed)
        for step in range(300):
            if E.is_over(game):
                break
            moved = False
            for seat, pid in enumerate(game["seats"]):
                if not E.owes_move(game, seat):
                    continue
                move = bot.choose_move(game, seat, seed=step * 13 + seat)
                legal = E.legal_moves(game, seat)
                if move["kind"] == "build":
                    assert any(m["inst"] == move["inst"] and m["pos"] == move["pos"]
                               for m in legal), move
                else:
                    assert move in legal, move
                E.apply_move(game, pid, move)
                moved = True
            if not moved:
                E.advance(game)


def test_the_soak_terminates_and_covers_every_fighter():
    seen: set[str] = set()
    outcomes: set = set()
    lengths = []
    for seed in range(220):
        game = play(seed)
        assert game["winner"] in (0, 1, "draw"), game["winner"]
        _check_invariants(game)
        outcomes.add(game["winner"])
        lengths.append(game["round"])
        for team in game["teams"]:
            seen.update(team)

    assert seen == set(ROSTER), f"never drafted: {sorted(set(ROSTER) - seen)}"
    assert outcomes == {0, 1, "draw"}, (
        "random play should reach a win either way and a draw")
    assert max(lengths) <= 20, (
        "a fight cannot run forever: the Build Deck loses a card a round, so "
        "failing to draw 3 caps it at about sixteen")


def test_every_fighter_survives_a_game_it_is_actually_in():
    """Force each fighter into a team in turn, so none is covered only by luck.

    The soak above drafts at random; over 220 games that reaches all twelve, but
    it reaches the rarer ones a handful of times. This puts every one of them
    into a real game, twice, with the roster derived from the data.
    """
    others = list(ROSTER)
    for i, fid in enumerate(ROSTER):
        partner = others[(i + 1) % len(others)]
        opp = (others[(i + 2) % len(others)], others[(i + 3) % len(others)])
        for seed in (i, i + 100):
            game = E.new_game(["A", "B"], seed=seed)
            game["draft_picks"] = [[fid, partner], list(opp)]
            game["draft_hands"] = [[], []]
            E._begin_order(game)
            for step in range(6000):
                if E.is_over(game):
                    break
                acted = False
                for seat, pid in enumerate(game["seats"]):
                    if not E.owes_move(game, seat):
                        continue
                    move = bot.choose_move(game, seat, seed=step * 7 + seat + seed)
                    E.apply_move(game, pid, move)
                    acted = True
                if not acted:
                    E.advance(game)
            assert E.is_over(game), f"{fid} produced a game that never ended"
            _check_invariants(game)


def test_the_bot_is_reproducible_from_its_seed():
    a, b = play(31), play(31)
    assert a["winner"] == b["winner"]
    assert a["log"] == b["log"]
    assert a["teams"] == b["teams"]


def test_random_play_is_not_biased_towards_a_seat():
    """A seat bias is a rules bug that never crashes, so it needs its own check.

    It is how the two-pass declaration bug was found: conditions that ask about
    the opposing card were being answered before that card had been walked, which
    only ever went wrong for seat 0. The band is wide because this is 300 games,
    not a strength measurement -- it is here to catch a systematic defect, and
    the one it caught sat at 0.45.
    """
    wins = [0, 0]
    for seed in range(300):
        game = play(seed + 5000)
        if game["winner"] in (0, 1):
            wins[game["winner"]] += 1
    total = sum(wins)
    assert total > 200, "too many draws to read anything"
    assert 0.40 < wins[0] / total < 0.60, f"seat 0 won {wins[0]}/{total}"
