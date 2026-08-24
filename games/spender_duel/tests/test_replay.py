"""Replay fidelity: a finished game reconstructed from seed + log must match the
game that was actually played, state-for-state.

This is a DIFFERENTIAL test (the Spender pattern): play real bot-vs-bot games, then
rebuild from the persisted seed + move log and compare every intermediate board to a
live engine stepped in parallel. It is what guarantees the review shows the truth
rather than a plausible-looking fiction.
"""
import copy
import random

import pytest

from games.spender_duel import bot, engine, replay

A, B = "alice", "bob"


def _play(seed):
    """A full bot-vs-bot game, plus the per-move live states for comparison."""
    g = engine.new_game([A, B], names={A: "Alice", B: "Bob"}, seed=seed)
    rng = random.Random(seed + 77)
    live = []                       # live board after each applied move
    for _ in range(4000):
        if engine.is_over(g):
            break
        actor = g.get("pending_pid") or g["turn"]
        mv = bot.choose(g, actor, rng)
        if mv is None:
            break
        ok, err = engine.apply_move(g, actor, mv)
        assert ok, (mv, err)
        live.append(copy.deepcopy(g))
    return g, live


def _key(g):
    """The state that a review actually renders (ignores the rng cursor)."""
    return {
        "board": g["board"], "pyramid": g["pyramid"], "privileges_board": g["privileges_board"],
        "royals_available": g["royals_available"], "turn": g["turn"], "phase": g["phase"],
        "winner": g.get("winner"), "turn_number": g["turn_number"],
        "players": {pid: {"tokens": p["tokens"], "privileges": p["privileges"],
                          "reserved": p["reserved"], "purchased": p["purchased"],
                          "royals": p["royals"]}
                    for pid, p in g["players"].items()},
    }


@pytest.mark.parametrize("seed", [1, 2, 3, 5, 8, 13, 21, 34])
def test_reconstruct_matches_the_game_that_was_played(seed):
    g, live = _play(seed)
    assert engine.is_over(g)
    snaps = replay.reconstruct(g)

    # one snapshot per MOVE, plus the initial deal
    assert len(snaps) == len(live) + 1
    assert snaps[0]["move"] is None and snaps[0]["pid"] is None

    # the initial deal reproduces exactly (same seed => same shuffle + spiral fill)
    first = snaps[0]["game"]
    assert first["bag_count"] == 0 and all(t is not None for t in first["board"])

    # every intermediate board matches the live game, move for move
    for k, want in enumerate(live, start=1):
        got = snaps[k]["game"]
        assert _key(got) == _key(want), f"seed {seed}: divergence after move {k}"

    # the final snapshot is the finished game
    assert snaps[-1]["game"]["phase"] == "over"
    assert snaps[-1]["game"]["winner"] == g["winner"]


def test_snapshots_never_leak_hidden_piles():
    g, _ = _play(4)
    for s in replay.reconstruct(g):
        v = s["game"]
        assert "bag" not in v and "decks" not in v and "rng_state" not in v and "seed" not in v
        assert isinstance(v["bag_count"], int) and set(v["deck_counts"]) == {"1", "2", "3"}
        for p in v["players"].values():
            assert "reserved_from_deck" not in p
    # ...but a FINISHED game's review DOES reveal both hands (that's the point)
    snaps = replay.reconstruct(g)
    for pid, p in snaps[-1]["game"]["players"].items():
        assert all(isinstance(c, str) for c in p["reserved"]), "review should reveal reserves"


def test_log_len_maps_rows_to_boards():
    """Each snapshot records the log length at that point, so the UI can jump from a
    clicked log row to the board right after it."""
    g, _ = _play(6)
    snaps = replay.reconstruct(g)
    assert snaps[0]["log_len"] == 0
    assert snaps[-1]["log_len"] == len(g["log"])
    lens = [s["log_len"] for s in snaps]
    assert lens == sorted(lens), "log_len must be non-decreasing"
    # every log row resolves to exactly one board
    for r in range(len(g["log"])):
        idx = next(i for i, s in enumerate(snaps) if s["log_len"] > r)
        assert 1 <= idx < len(snaps)


def test_auto_resolved_abilities_are_not_replayed_as_moves():
    """An AUTO-resolved take_same/steal is logged identically to a player-chosen one.
    Replay must not re-apply it — the `buy` regenerates it. Exercised by finding a
    game whose log actually contains an auto-resolved ability."""
    found = False
    for seed in range(30):
        g, live = _play(seed)
        autos = [i for i, e in enumerate(g["log"])
                 if e["type"] in ("take_same", "steal") and e.get("via")]
        if not autos:
            continue
        found = True
        snaps = replay.reconstruct(g)          # would desync/raise if re-applied
        assert len(snaps) == len(live) + 1
        assert _key(snaps[-1]["game"]) == _key(g)
        break
    assert found, "no game exercised an ability-generated log record"


def test_a_game_containing_undos_still_replays():
    """Undo restores the turn's snapshot WHOLESALE, log included, so undone actions leave
    no trace — which is exactly what keeps this replay valid. If undo ever started
    logging (or half-restoring), the reconstruction would desync here."""
    g = engine.new_game([A, B], names={A: "Alice", B: "Bob"}, seed=11)
    rng = random.Random(11)
    undos = 0
    for step in range(4000):
        if engine.is_over(g):
            break
        actor = g.get("pending_pid") or g["turn"]
        mv = bot.choose(g, actor, rng)
        if mv is None:
            break
        ok, _ = engine.apply_move(g, actor, mv)
        assert ok
        # every so often, take the whole turn back and play it again
        if step % 7 == 3 and not engine.is_over(g):
            turn_owner = g["turn"]
            if engine.apply_move(g, turn_owner, {"type": "undo_turn"})[0]:
                undos += 1
    assert engine.is_over(g)
    assert undos > 3, f"the undo path was barely exercised ({undos})"
    assert not any(e["type"] == "undo_turn" for e in g["log"]), "undo must not be logged"

    snaps = replay.reconstruct(g)          # would raise/desync if the log kept undone moves
    assert _key(snaps[-1]["game"]) == _key(g)
    assert snaps[-1]["game"]["winner"] == g["winner"]


def test_unreplayable_games_degrade_instead_of_crashing():
    g, _ = _play(9)
    noseed = copy.deepcopy(g)
    noseed["seed"] = None                       # a pre-seed save
    with pytest.raises(replay.ReplayError):
        replay.reconstruct(noseed)
    assert replay.review_payload(noseed) is None    # the review still renders its final board

    corrupt = copy.deepcopy(g)
    corrupt["log"].insert(1, {"t": 1, "pid": A, "type": "not_a_real_record"})
    assert replay.review_payload(corrupt) is None
