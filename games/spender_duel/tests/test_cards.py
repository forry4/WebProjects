"""Static-data invariants for Spender Duel cards/tokens/board."""
from collections import Counter

from games.spender_duel import cards


def test_token_bag_multiset():
    c = Counter(cards.TOKEN_BAG)
    assert sum(c.values()) == 25
    for col in cards.COLORS:
        assert c[col] == 4
    assert c["pearl"] == 2
    assert c["gold"] == 3


def test_spiral_is_center_out_adjacent_permutation():
    so = cards.SPIRAL_ORDER
    assert sorted(so) == list(range(25))
    assert so[0] == 12  # center of the 5x5
    for a, b in zip(so, so[1:]):
        ra, ca = divmod(a, 5)
        rb, cb = divmod(b, 5)
        assert max(abs(ra - rb), abs(ca - cb)) == 1, f"non-adjacent spiral step {a}->{b}"


def test_deck_counts():
    per_level = Counter(c["level"] for c in cards.CARDS.values())
    assert per_level[1] == cards.DECK_SIZES[1] == 30
    assert per_level[2] == cards.DECK_SIZES[2] == 24
    assert per_level[3] == cards.DECK_SIZES[3] == 13
    assert len(cards.CARDS) == 67


def test_card_schema():
    for cid, c in cards.CARDS.items():
        assert cid == c["id"]
        assert c["level"] in (1, 2, 3)
        assert c["points"] >= 0 and c["crowns"] >= 0
        assert c["bonus"] in cards.COLORS or c["bonus"] in ("wild", None)
        assert c["bonus_count"] in (1, 2)
        if c["bonus"] in ("wild", None):
            assert c["bonus_count"] == 1
        assert c["ability"] in (None, "again", "take_same", "privilege", "steal")
        # take_same needs a concrete color to match
        if c["ability"] == "take_same":
            assert c["bonus"] in cards.COLORS
        for col, n in c["cost"].items():
            assert col in cards.COLORS + ["pearl"], f"{cid} bad cost color {col}"
            assert n > 0
        assert sum(c["cost"].values()) > 0


def test_no_pearl_bonus_and_royals():
    assert all(c["bonus"] != "pearl" for c in cards.CARDS.values())
    assert len(cards.ROYALS) == 4
    for rid, r in cards.ROYALS.items():
        assert rid == r["id"]
        assert r["points"] > 0
        assert r["ability"] in (None, "again", "take_same", "privilege", "steal")


def test_real_deck_aggregates():
    """Totals of the transcribed real deck (cross-checked across 5 sources)."""
    assert cards.DATA_COMPLETE
    cs = list(cards.CARDS.values())
    assert sum(c["crowns"] for c in cs) == 28
    assert sum(c["points"] for c in cs) == 92
    abil = Counter(c["ability"] for c in cs if c["ability"])
    assert abil == {"again": 6, "take_same": 5, "steal": 5, "privilege": 5}
    assert sum(1 for c in cs if c["bonus"] == "wild") == 9
    assert Counter(c["level"] for c in cs if c["bonus"] == "wild") == {1: 4, 2: 3, 3: 2}
    assert sum(1 for c in cs if c["bonus"] is None) == 3
    dbl = [c for c in cs if c["bonus_count"] == 2]
    assert len(dbl) == 5 and all(c["level"] == 2 for c in dbl)
    assert max(max(c["cost"].values()) for c in cs) == 8
    assert max(c["cost"].get("pearl", 0) for c in cs) == 1
    assert sum(1 for c in cs if c["cost"].get("pearl")) == 29


def test_deck_ids_cover_catalog():
    all_ids = set()
    for lvl in (1, 2, 3):
        ids = cards.deck_ids(lvl)
        assert len(ids) == cards.DECK_SIZES[lvl]
        all_ids.update(ids)
    assert all_ids == set(cards.CARDS)
