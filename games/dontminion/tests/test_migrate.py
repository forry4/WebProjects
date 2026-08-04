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
V6_KEYS_GAME = ("piles", "nonsupply")
V7_KEYS_GAME = ("coffers", "bane", "ferryman_pile", "footpad_draw")
V7_KEYS_SEAT = ("set_aside", "start_fx", "cleanup_aside")
V8_KEYS_GAME = ("potions",)
V9_KEYS_GAME = ("shelters",)


def _fresh(expansions=("base",), kingdom=None):
    return engine.new_game([A, B], list(expansions), seed=3,
                           kingdom=kingdom or ["Smithy", "Village", "Moat", "Militia",
                                               "Witch", "Throne Room", "Gardens",
                                               "Market", "Cellar", "Festival"])


def _downgrade(g, to_version):
    """Strip a current blob back to what the vN engine would have persisted."""
    g = json.loads(json.dumps(g))
    if to_version < 9:
        for k in V9_KEYS_GAME:
            g.pop(k, None)
    if to_version < 8:
        for k in V8_KEYS_GAME:
            g.pop(k, None)
    if to_version < 7:
        for k in V7_KEYS_GAME:
            g.pop(k, None)
        for seat in g["seats"].values():
            for k in V7_KEYS_SEAT:
                seat.pop(k, None)
    if to_version < 6:
        for k in V6_KEYS_GAME:
            g.pop(k, None)
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
    assert _fresh()["schema"] == engine.SCHEMA == 9


@pytest.mark.parametrize("version", [1, 2])
def test_migrate_fills_every_key_the_kernel_reads(version):
    old = _downgrade(_fresh(), version)
    if version < 2:
        assert "watchers" not in old and "duration" not in old["seats"][A]
    g = engine.migrate(old)
    assert g["schema"] == engine.SCHEMA
    for k in (V2_KEYS_GAME + V3_KEYS_GAME + V6_KEYS_GAME + V7_KEYS_GAME
              + V8_KEYS_GAME + V9_KEYS_GAME):
        assert k in g, k
    for seat in g["seats"].values():
        for k in V2_KEYS_SEAT + V7_KEYS_SEAT:
            assert k in seat, k
    assert g["vp_tokens"] == {A: 0, B: 0}
    assert g["colony"] is False and g["curse_is_treasure"] is False
    # ph. 3H: the pile model rebuilds from the count index — every pile a
    # pre-3H save can hold is an ordinary Supply pile of its own card
    assert set(g["piles"]) == set(g["supply"]) and g["nonsupply"] == {}
    for name in g["supply"]:
        assert engine.pile_count(g, name) == g["supply"][name]


@pytest.mark.parametrize("version", [1, 2, 3, 5, 6, 7, 8])
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


@pytest.mark.parametrize("missing", V2_KEYS_GAME + V3_KEYS_GAME + V6_KEYS_GAME
                         + V7_KEYS_GAME + V8_KEYS_GAME + V9_KEYS_GAME)
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


@pytest.mark.parametrize("missing", ["duration", "island", "aside",
                                     "set_aside", "start_fx", "cleanup_aside"])
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


def _harem_game():
    """A live, mid-turn v3 game with the OLD name in every place it can hide."""
    g = _fresh(expansions=("base", "intrigue"),
               kingdom=["Farm", "Courtyard", "Pawn", "Steward", "Baron", "Bridge",
                        "Ironworks", "Mill", "Nobles", "Upgrade"])
    _drive(g, moves=30)
    A_ = A
    g["seats"][A_]["hand"].append("Farm")
    g["seats"][A_]["deck"].append("Farm")
    g["seats"][A_]["discard"].append("Farm")
    g["seats"][A_]["in_play"].append("Farm")
    g["trash"].append("Farm")
    g["last_turn_gains"].setdefault(A_, []).append("Farm")
    blob = json.loads(json.dumps(g))
    # downgrade: every "Farm" becomes the pre-2023 "Harem", schema back to 3
    blob = json.loads(json.dumps(blob).replace('"Farm"', '"Harem"')
                      .replace("Farm", "Harem"))
    blob["schema"] = 3
    return blob


def test_the_harem_to_farm_rename_rewrites_a_whole_live_save():
    """A rename is NOT cosmetic: the string sits in real decks, supplies, trash,
    pending frames and undo snapshots, so a load that missed one would leave a
    live game holding a card the kernel no longer knows."""
    blob = _harem_game()
    assert "Harem" in json.dumps(blob) and "Farm" not in json.dumps(blob)

    engine.migrate(blob)
    dumped = json.dumps(blob)
    assert "Harem" not in dumped, "an old name survived the migration"
    assert blob["schema"] == engine.SCHEMA

    # it is the SAME card in every zone, under the new name
    assert "Farm" in blob["supply"] and "Farm" in blob["kingdom"]
    seat = blob["seats"][A]
    for zone in ("hand", "deck", "discard", "in_play"):
        assert "Farm" in seat[zone], zone
    assert "Farm" in blob["trash"]
    assert "Farm" in blob["last_turn_gains"][A]

    # ...and the migrated game still plays and scores (Farm is 2 VP)
    _drive(blob, moves=60)
    for viewer in (A, B, None):
        json.dumps(engine.player_view(blob, viewer))


def test_the_rename_never_touches_a_players_display_name():
    """Someone can call themselves after a card. Identity is protected by
    POSITION (which key holds it), not by matching the value — a value-blind
    guard would refuse to rename the real card whenever a player shared its
    name, leaving the game holding a card the kernel no longer knows."""
    blob = _harem_game()
    blob["names"] = {A: "Harem", B: "bob"}         # a player called Harem
    blob["turn"] = A

    engine.migrate(blob)
    assert blob["names"][A] == "Harem"             # display name untouched
    assert blob["players"] == [A, B] and set(blob["seats"]) == {A, B}
    assert blob["turn"] == A
    assert "Farm" in blob["supply"]                # ...and the CARD still renamed
    assert "Harem" not in blob["supply"]
    assert "Farm" in blob["seats"][A]["hand"]
    _drive(blob, moves=40)


def test_rename_is_idempotent_on_an_already_current_save():
    g = _fresh(expansions=("base", "intrigue"),
               kingdom=["Farm", "Courtyard", "Pawn", "Steward", "Baron", "Bridge",
                        "Ironworks", "Mill", "Nobles", "Upgrade"])
    _drive(g, moves=20)
    before = json.dumps(g, sort_keys=True)
    engine.migrate(g)
    engine.migrate(g)
    assert json.dumps(g, sort_keys=True) == before


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


def test_a_pre_cornucopia_save_gains_the_coffers_shape():
    """ph. 4 adds a per-player counter and three seat zones the kernel indexes
    directly. A live prod game predates all of them, so the fill is what stops
    the first end of turn KeyErroring."""
    g = _fresh()
    old = _downgrade(g, 6)
    for k in V7_KEYS_GAME:
        assert k not in old
    engine.migrate(old)
    assert old["coffers"] == {A: 0, B: 0}
    assert old["bane"] is None and old["ferryman_pile"] is None
    assert old["footpad_draw"] is False
    for seat in old["seats"].values():
        assert seat["set_aside"] == [] and seat["start_fx"] == []
        assert seat["cleanup_aside"] == []
    _drive(old, moves=120)


def test_a_pre_alchemy_save_gains_the_second_money_pool():
    """ph. 5 adds game["potions"], which _end_turn and _h_buy index directly.
    A live prod game predates it."""
    old = _downgrade(_fresh(), 7)
    assert "potions" not in old
    engine.migrate(old)
    assert old["potions"] == 0
    _drive(old, moves=120)


def test_a_pre_dark_ages_save_gains_the_shelter_flag():
    """ph. 6 adds game["shelters"] — the record of whether this game dealt
    Shelter starting decks. A live prod game predates it and played without
    them, which is exactly what the fill says."""
    old = _downgrade(_fresh(), 8)
    assert "shelters" not in old
    engine.migrate(old)
    assert old["shelters"] is False
    _drive(old, moves=120)


def test_a_dark_ages_position_with_shuffled_piles_round_trips():
    """The two ORDERED Supply piles (Ruins, Knights) and the three non-Supply
    ones are pile-model state, so a save carrying them has to survive JSON and
    migrate untouched — including the hidden `contents` order."""
    g = engine.new_game([A, B], ["darkages"], seed=11,
                        kingdom=["Knights", "Cultist", "Hermit", "Urchin",
                                 "Marauder", "Fortress", "Rats", "Squire",
                                 "Altar", "Ironmonger"])
    assert engine.pile_count(g, "Knights") == 10
    assert engine.pile_count(g, "Ruins") == 10          # 2 players => 10 Curses
    assert set(g["nonsupply"]) == {"Madman", "Mercenary", "Spoils"}
    _drive(g, moves=80)
    blob = json.loads(json.dumps(g))
    engine.migrate(blob)
    assert blob == json.loads(json.dumps(g)), "migrate mutated a current save"
    _drive(blob, moves=60)
    for viewer in (A, B, None):
        view = engine.player_view(blob, viewer)
        json.dumps(view)
        # the shuffled order is hidden information and never ships
        assert "contents" not in view["piles"]["Knights"]
