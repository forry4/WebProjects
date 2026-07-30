"""Save-blob migration: a live prod game may predate any number of phases, so
engine.migrate() must bring every historical shape up to engine.SCHEMA. The
kernel is allowed to assume the current shape ONLY because of this — every
phase that adds a key the kernel reads owes a step here plus a test below.

The blobs are built by DOWNGRADING a current game (stripping exactly what the
older engine didn't write), which keeps these tests honest as the shape grows.
"""

import json
import random

import pytest

from games.dontminion import engine

A, B = "alice", "bob"

V2_KEYS_GAME = ("watchers", "last_turn_pid", "extra_turn", "last_turn_gains")
V2_KEYS_SEAT = ("duration", "dur_aside", "island", "village_mat")
V3_KEYS_GAME = ("vp_tokens", "colony", "curse_is_treasure")


def _fresh(expansions=("base",), kingdom=None):
    return engine.new_game([A, B], list(expansions), seed=3,
                           kingdom=kingdom or ["Smithy", "Village", "Moat", "Militia",
                                               "Witch", "Throne Room", "Gardens",
                                               "Market", "Cellar", "Festival"])


def _downgrade(g, to_version):
    """Strip a current blob back to what the vN engine would have persisted."""
    g = json.loads(json.dumps(g))
    if to_version < 3:
        for k in V3_KEYS_GAME:
            g.pop(k, None)
    if to_version < 2:
        for k in V2_KEYS_GAME:
            g.pop(k, None)
        for seat in g["seats"].values():
            for k in V2_KEYS_SEAT:
                seat.pop(k, None)
    g.pop("schema", None) if to_version < 2 else g.update(schema=to_version)
    return g


def _drive(g, moves=120, seed=5):
    """Play the migrated game to prove the kernel accepts it."""
    rng = random.Random(seed)
    for _ in range(moves):
        if g["over"]:
            break
        pid = g["pending_pid"] or g["turn"]
        if g["pending_pid"]:
            mv = {"type": "decision", **engine.sample_decision(g, pid, rng)}
        else:
            mv = rng.choice(engine.legal_moves(g, pid))
        ok, err = engine.apply_move(g, pid, mv)
        assert ok, err
        json.dumps(g)
    return g


def test_new_games_carry_the_current_schema():
    assert _fresh()["schema"] == engine.SCHEMA == 3


@pytest.mark.parametrize("version", [1, 2])
def test_migrate_fills_every_key_the_kernel_reads(version):
    old = _downgrade(_fresh(), version)
    if version < 2:
        assert "watchers" not in old and "duration" not in old["seats"][A]
    g = engine.migrate(old)
    assert g["schema"] == engine.SCHEMA
    for k in V2_KEYS_GAME + V3_KEYS_GAME:
        assert k in g, k
    for seat in g["seats"].values():
        for k in V2_KEYS_SEAT:
            assert k in seat, k
    assert g["vp_tokens"] == {A: 0, B: 0}
    assert g["colony"] is False and g["curse_is_treasure"] is False


@pytest.mark.parametrize("version", [1, 2, 3])
def test_migrated_blobs_play_through_the_current_kernel(version):
    g = engine.migrate(_downgrade(_fresh(), version))
    _drive(g)
    assert g["seats"][A]["turns_taken"] + g["seats"][B]["turns_taken"] > 2
    for viewer in (A, B, None):
        json.dumps(engine.player_view(g, viewer))


def test_migrate_is_idempotent_and_preserves_live_state():
    g = _fresh()
    _drive(g, moves=40)
    before = json.dumps(g, sort_keys=True)
    engine.migrate(g)
    engine.migrate(g)
    assert json.dumps(g, sort_keys=True) == before


def test_migrate_tolerates_junk():
    for junk in ({}, {"no": "seats"}, None, []):
        engine.migrate(junk)          # must not raise


@pytest.mark.parametrize("missing", V2_KEYS_GAME + V3_KEYS_GAME)
def test_a_stamped_blob_missing_a_key_is_still_filled(missing):
    """THE prod shape that broke this. `schema = 2` was stamped across the whole
    Seaside AND Prosperity eras, so prod carries v2 blobs that predate keys
    added later under that same stamp (two live games had schema 2 and no
    last_turn_gains). A version-GATED fill skips them and the kernel then
    KeyErrors at end of turn — so fills must go by presence, not by version."""
    g = _fresh()
    g["schema"] = 2
    g.pop(missing)
    engine.migrate(g)
    assert missing in g
    _drive(g, moves=60)          # the KeyError landed at the next end of turn


@pytest.mark.parametrize("missing", ["duration", "island", "aside"])
def test_a_stamped_blob_missing_a_seat_zone_is_still_filled(missing):
    g = _fresh()
    g["schema"] = 2
    for seat in g["seats"].values():
        seat.pop(missing)
    engine.migrate(g)
    assert all(missing in s for s in g["seats"].values())
    _drive(g, moves=60)


def test_migrate_fills_a_partial_turn_ctx():
    """A save caught MID-TURN carries whatever turn_ctx the older engine wrote;
    the kernel indexes its keys directly."""
    g = _fresh()
    g["turn_ctx"].pop("bought")
    engine.migrate(g)
    assert g["turn_ctx"]["bought"] is False
    _drive(g, moves=60)

    g2 = _fresh()
    g2.pop("turn_ctx")
    engine.migrate(g2)
    assert g2["turn_ctx"] == engine._fresh_turn_ctx()


def test_v3_keys_survive_a_v3_blob_untouched():
    g = _fresh(expansions=("base", "prosperity"),
               kingdom=["Charlatan", "Peddler", "Quarry", "Monument", "Bishop",
                        "City", "Vault", "Rabble", "Expand", "Forge"])
    assert g["curse_is_treasure"] is True          # Charlatan in the kingdom
    engine.add_vp_tokens(g, A, 4)
    blob = json.loads(json.dumps(g))
    engine.migrate(blob)
    assert blob["curse_is_treasure"] is True       # NOT reset by the migration
    assert blob["vp_tokens"][A] == 4
