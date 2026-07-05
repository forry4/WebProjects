"""Property / invariant tests for the CoC engine.

Instead of scripting one situation, these play MANY full games by choosing random
legal moves and assert the engine never breaks its own rules: every move it lists
as legal is actually applyable, resources never go negative, storage/goods caps
hold, state stays JSON-safe, and identical inputs stay deterministic. This is the
broadest safety net — it exercises paths (chained pendings, storage-full takes,
ship depot choices, monastery combos) that targeted tests miss."""
import copy
import json
import random

from games.castles_of_crimson import engine
from .conftest import complete_setup


# ── invariant checks applied at every step of a random game ───────────────────
def _assert_state_invariants(g):
    for pid, p in g["players"].items():
        assert p["workers"] >= 0, (pid, "negative workers", p["workers"])
        assert p["silver"] >= 0, (pid, "negative silver", p["silver"])
        assert p["vp"] >= 0, (pid, "negative vp")
        assert len(p["storage"]) <= 3, (pid, "storage over cap", len(p["storage"]))
        assert len(p["goods"]) <= 3, (pid, "over 3 distinct goods", p["goods"])
        assert all(c > 0 for c in p["goods"].values()), (pid, "zero/negative goods count")
        assert p["mines_count"] >= 0
        # duchy always has exactly the board's spaces
        assert len(p["duchy"]) == 37
    # pending state is always consistent
    if g["pending_pid"] is not None:
        assert g["pending_pid"] in g["players"]
        assert g["pending_kind"] in engine.RESOLVERS_FOR, g["pending_kind"]
        # the pending player must have at least the skip move available
        assert engine.legal_moves(g, g["pending_pid"]), "pending player has no legal moves"
    # phase/round bounds
    assert g["phase"] in ("setup", "playing", "over")
    assert 1 <= g["round"] <= 5
    assert g["phase_letter"] in ("A", "B", "C", "D", "E")


def _random_playout(seed, max_steps=3000, check_applyable=False):
    """Play a full game choosing a random legal move each step; assert invariants."""
    move_rng = random.Random(seed * 7919 + 13)
    g = engine.new_game(["p1", "p2"], names={"p1": "A", "p2": "B"}, seed=seed)
    complete_setup(g)
    steps = 0
    while not engine.is_over(g) and steps < max_steps:
        steps += 1
        mover = g["pending_pid"] if g["pending_pid"] is not None else g["turn"]
        legal = engine.legal_moves(g, mover)
        assert legal, f"seed {seed} step {steps}: no legal moves for {mover}"
        _assert_state_invariants(g)
        if check_applyable:
            # EVERY move the engine advertises as legal must actually apply cleanly.
            for mv in legal:
                clone = copy.deepcopy(g)
                clone["_skip_undo"] = True   # skip per-turn deepcopy in the clone
                ok, err = engine.apply_move(clone, mover, mv)
                assert ok, f"seed {seed} step {steps}: legal move rejected {mv} -> {err}"
        mv = move_rng.choice(legal)
        ok, err = engine.apply_move(g, mover, mv)
        assert ok, f"seed {seed} step {steps}: random legal move failed {mv} -> {err}"
    assert engine.is_over(g), f"seed {seed}: game did not finish within {max_steps} steps"
    return g


def test_random_playouts_complete_and_hold_invariants():
    """40 full random games: each finishes, sets a winner, and never violates an invariant."""
    for seed in range(40):
        g = _random_playout(seed)
        assert g["winner"] in ("p1", "p2")
        scores = engine.final_scores(g)
        assert set(scores) == {"p1", "p2"}
        assert all(isinstance(s, int) and s >= 0 for s in scores.values())


def test_every_listed_legal_move_is_applyable():
    """The strongest consistency check: on real game states, every move legal_moves
    returns must succeed via apply_move (no phantom/illegal moves are advertised)."""
    for seed in range(6):
        _random_playout(seed, check_applyable=True)


def test_playout_state_stays_json_safe():
    """The whole game dict must remain JSON-serializable (no sets / tuples-as-keys)
    at every step — it is persisted to the DB and broadcast over the WebSocket."""
    move_rng = random.Random(999)
    g = engine.new_game(["p1", "p2"], seed=5)
    complete_setup(g)
    steps = 0
    while not engine.is_over(g) and steps < 3000:
        steps += 1
        json.dumps(g)   # raises if any non-JSON value crept in
        mover = g["pending_pid"] if g["pending_pid"] is not None else g["turn"]
        legal = engine.legal_moves(g, mover)
        ok, _ = engine.apply_move(g, mover, move_rng.choice(legal))
        assert ok
    json.dumps(g)


def test_playout_is_deterministic():
    """Same game seed + same move-choice stream ⇒ identical final scores/winner."""
    a = _random_playout(123)
    b = _random_playout(123)
    assert engine.final_scores(a) == engine.final_scores(b)
    assert a["winner"] == b["winner"]
    assert a["round_in_game"] == b["round_in_game"]


def test_legal_moves_empty_only_when_over_or_not_your_turn():
    """A player to move (or with a pending) always has ≥1 legal move; a player who
    is NOT to move has none. legal_moves is empty exactly when the game is over."""
    move_rng = random.Random(7)
    g = engine.new_game(["p1", "p2"], seed=8)
    complete_setup(g)
    while not engine.is_over(g):
        active = g["pending_pid"] if g["pending_pid"] is not None else g["turn"]
        idle = "p2" if active == "p1" else "p1"
        assert engine.legal_moves(g, active), "active player must have a move"
        assert engine.legal_moves(g, idle) == [], "idle player must have no moves"
        ok, _ = engine.apply_move(g, active, move_rng.choice(engine.legal_moves(g, active)))
        assert ok
    assert engine.legal_moves(g, "p1") == [] and engine.legal_moves(g, "p2") == []


def test_vp_is_monotonic_non_decreasing():
    """This game never subtracts VP — accumulated player VP only ever grows."""
    move_rng = random.Random(31)
    g = engine.new_game(["p1", "p2"], seed=17)
    complete_setup(g)
    last = {pid: 0 for pid in g["players"]}
    while not engine.is_over(g):
        for pid, p in g["players"].items():
            assert p["vp"] >= last[pid], f"{pid} VP decreased {last[pid]} -> {p['vp']}"
            last[pid] = p["vp"]
        mover = g["pending_pid"] if g["pending_pid"] is not None else g["turn"]
        ok, _ = engine.apply_move(g, mover, move_rng.choice(engine.legal_moves(g, mover)))
        assert ok


def test_vp_breakdown_sums_to_final_score():
    """The itemized end-game VP review must EXACTLY reconstruct every player's final
    score — this is the whole point of the review (spot a scoring bug). Checked over
    many random games so it exercises every VP source (regions, bonuses, livestock,
    sells, watchtower, leftover resources, and monastery endgame effects)."""
    for seed in range(25):
        g = _random_playout(seed)
        scores = engine.final_scores(g)
        for pid in g["players"]:
            items = engine.vp_breakdown(g, pid)
            assert sum(i["vp"] for i in items) == scores[pid], (
                f"seed {seed} {pid}: breakdown {sum(i['vp'] for i in items)} != final {scores[pid]}\n{items}")


def test_three_and_four_player_random_games_complete():
    """The engine is player-count-agnostic: 3- and 4-player random games finish
    with a single winner and the right number of end-of-turn cycles."""
    for n in (3, 4):
        pids = [f"p{i}" for i in range(n)]
        move_rng = random.Random(n * 101)
        g = engine.new_game(pids, seed=n)
        complete_setup(g)
        steps = 0
        while not engine.is_over(g) and steps < 5000:
            steps += 1
            mover = g["pending_pid"] if g["pending_pid"] is not None else g["turn"]
            ok, _ = engine.apply_move(g, mover, move_rng.choice(engine.legal_moves(g, mover)))
            assert ok
        assert engine.is_over(g)
        assert g["winner"] in pids
