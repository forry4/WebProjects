"""Where Wolf spends ALL its randomness at setup, so it persists no `rng_state`.

That saved 89.6% of the stored row (5,306 -> 554 bytes) — the Mersenne state is
incompressible, so it dominated the blob even after zlib, and nothing ever read it
(`_load_rng` was defined and never called).

The saving is only safe while the premise holds. If a night step or the vote ever starts
drawing, that draw silently stops being reproducible across a save/reconnect — the exact
class of bug that is invisible to tests which never reload. So rather than only asserting
the key is absent, `test_no_randomness_is_consumed_after_setup` plays a whole game with
the stdlib RNG booby-trapped and fails the moment anything draws.
"""
import json
import random

from games.wherewolf import engine, roles


PIDS = [f"p{i}" for i in range(6)]
NAMES = {p: p.upper() for p in PIDS}


def _new(seed=7):
    return engine.new_game(PIDS, names=NAMES, seed=seed)


def _first(g, role):
    return next((p for p in g["order"] if g["players"][p]["dealt_role"] == role), None)


def _play_out(g):
    """A full game on the server conductor's path (mirrors tests/test_smoke.py),
    with every choice made deterministically so the driver itself never draws."""
    for p in g["order"]:
        engine.apply_move(g, p, {"type": "ready"})

    engine.start_night(g)
    for step in roles.NIGHT_ORDER:
        role = roles.STEP_ROLE[step]
        if role not in g["deck"]:
            continue
        engine.set_step(g, step)
        actor = _first(g, role)
        if actor is None:
            continue                               # role sits in the center; nobody acts
        others = [p for p in g["order"] if p != actor]
        if step == "seer":
            engine.apply_move(g, actor, {"type": "seer_peek_center", "indices": [0, 1]})
        elif step == "robber":
            engine.apply_move(g, actor, {"type": "robber_swap", "target": others[0]})
        elif step == "troublemaker" and len(others) >= 2:
            engine.apply_move(g, actor, {"type": "troublemaker_swap",
                                         "a": others[0], "b": others[1]})
        elif step == "drunk":
            engine.apply_move(g, actor, {"type": "drunk_swap", "center_index": 0})
        elif step == "werewolves" and len(g["wolf_pids"]) == 1:
            engine.apply_move(g, actor, {"type": "wolf_peek_center", "index": 0})

    engine.begin_day(g, deadline=None)
    for p in g["order"]:
        engine.apply_move(g, p, {"type": "vote", "target": g["order"][0]})
        engine.apply_move(g, p, {"type": "lock_vote"})
    engine.resolve_votes(g)
    return g


# ── the saving itself ────────────────────────────────────────────────────────
def test_new_game_persists_no_rng_state():
    g = _new()
    assert "rng_state" not in g, "the row must not carry 625 words nothing reads"


def test_a_played_out_game_never_grows_one():
    g = _play_out(_new())
    assert engine.is_over(g)
    assert "rng_state" not in g


def test_the_deal_still_works_and_stays_json_safe():
    """Dropping the key must not have broken setup."""
    g = _new()
    json.dumps(g)                                   # no sets/tuples crept in
    assert len(g["order"]) == len(PIDS)
    assert all(p["dealt_role"] for p in g["players"].values())
    assert len(g["center"]) == 3


def test_the_deal_is_still_seeded():
    """Reproducibility of the DEAL is what the seed is for, and it must survive."""
    assert _new(7)["deck"] == _new(7)["deck"]
    a = [_new(7)["players"][p]["dealt_role"] for p in PIDS]
    b = [_new(7)["players"][p]["dealt_role"] for p in PIDS]
    assert a == b


# ── the guard that keeps it safe ─────────────────────────────────────────────
class _Boom(random.Random):
    """A Random that refuses to be used."""

    def random(self, *a, **k):      raise AssertionError("engine drew from the RNG")
    def getrandbits(self, *a, **k): raise AssertionError("engine drew from the RNG")
    def shuffle(self, *a, **k):     raise AssertionError("engine shuffled")
    def choice(self, *a, **k):      raise AssertionError("engine chose randomly")
    def randint(self, *a, **k):     raise AssertionError("engine drew from the RNG")
    def sample(self, *a, **k):      raise AssertionError("engine sampled")


def test_no_randomness_is_consumed_after_setup(monkeypatch):
    """THE guard. `new_game` may draw; nothing after it may.

    If this fails, the engine gained a post-setup draw and `_save_rng`/`_load_rng` must
    be re-armed around it (see engine._save_rng) — do NOT just delete this test."""
    g = _new()                                      # setup draws, and that is allowed

    for name in ("random", "getrandbits", "shuffle", "choice", "randint", "sample"):
        monkeypatch.setattr(random, name, getattr(_Boom(), name))
    monkeypatch.setattr(random, "Random", _Boom)

    _play_out(g)                                    # raises if anything here draws
    assert engine.is_over(g)


def test_a_legacy_row_still_plays(monkeypatch):
    """Rows saved before the change carry rng_state; the extra key must be harmless."""
    g = _new()
    g["rng_state"] = [3, [0] * 625, None]           # what a pre-change save looked like
    _play_out(g)
    assert engine.is_over(g)
