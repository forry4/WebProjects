"""Card-trait tests.

The load-bearing one is `test_every_kingdom_card_is_reviewed`: traits are half
derived and half hand-tagged, and an unreviewed card would be silently
classified as "a plain terminal" — a wrong answer that looks like the bot
playing badly rather than like missing data. Every expansion phase owes its
cards to `REVIEWED`.
"""

from games.dontminion import bot_traits as T
from games.dontminion.cards import CARDS, KINGDOM


def test_every_kingdom_card_is_reviewed():
    """A new set's cards MUST be added to the trait tables. Derived from the
    data, so the next expansion fails here on the day it ships."""
    every = {c for names in KINGDOM.values() for c in names}
    missing = sorted(every - set(T.REVIEWED))
    assert not missing, (
        f"{len(missing)} kingdom cards have no reviewed traits: {missing}. "
        "Add them to bot_traits.py's tables (trasher/attack/gainer/... as "
        "applicable) and to REVIEWED.")


def test_reviewed_names_all_exist():
    """The reverse guard — a rename must not leave a dangling trait row."""
    unknown = sorted(n for n in T.REVIEWED if n not in CARDS)
    assert not unknown, f"trait rows for cards that do not exist: {unknown}"


def test_hand_tagged_tables_only_name_real_cards():
    for label, names in (("TRASHERS", T.TRASHERS), ("ATTACKS", T.ATTACKS),
                         ("DEFENSE", T.DEFENSE), ("GAINERS", T.GAINERS),
                         ("SIFTERS", T.SIFTERS), ("ALT_VP", T.ALT_VP),
                         ("VP_TOKENS", T.VP_TOKENS),
                         ("BM_TREASURES", T.BM_TREASURES),
                         ("BM_TERMINALS", T.BM_TERMINALS)):
        bad = sorted(n for n in names if n not in CARDS)
        assert not bad, f"{label} names cards that do not exist: {bad}"


def test_every_tagged_attack_is_actually_an_attack():
    """ATTACKS classifies attack cards; a non-Attack in there means the
    defensive read (do I need a Moat?) is answering about the wrong card."""
    for name in T.ATTACKS:
        assert "attack" in CARDS[name]["types"], f"{name} is not an Attack"


def test_derived_classifications():
    assert T.t("Smithy", "terminal_draw") and T.t("Smithy", "terminal")
    assert T.t("Village", "village") and not T.t("Village", "terminal")
    assert T.t("Laboratory", "cantrip") and not T.t("Laboratory", "terminal")
    assert T.t("Market", "cantrip") and T.t("Market", "plus_buy")
    assert T.t("Festival", "village") and T.t("Festival", "plus_buy")
    assert T.t("Gold", "coins") == 3 and not T.t("Gold", "action")
    # a payload Action's coins come from its printed +$N, not the data column
    assert T.t("Militia", "coins") == 2
    # Moat draws 2 but is not a BM-grade drawer bar; it is still terminal draw
    assert T.t("Moat", "terminal_draw") and T.t("Moat", "defense")


def test_reviewed_semantics():
    assert T.t("Chapel", "trasher") == "mass"
    assert T.t("Steward", "trasher") == "multi"
    assert T.t("Remodel", "trasher") == "tfb"
    assert T.t("Witch", "curser") and T.t("Witch", "attack_kind") == "curse"
    assert T.t("Militia", "attack_kind") == "discard"
    assert not T.t("Village", "curser")
    assert T.t("Gardens", "alt_vp") == "per_10_cards"
    assert T.t("Duke", "alt_vp") == "per_duchy"
    assert T.t("Monument", "vp_tokens")


def test_money_density_matches_the_articles_numbers():
    """The published anchors: a fresh deck is 0.7, and 1.6 is the Province
    threshold the strategy corpus measures decks against."""
    assert round(T.density(["Copper"] * 7 + ["Estate"] * 3), 4) == 0.7
    # cantrips are "virtual cards" — they leave the denominator alone
    with_lab = ["Copper"] * 7 + ["Estate"] * 3 + ["Laboratory"]
    assert round(T.density(with_lab), 4) == 0.7
    rich = ["Gold"] * 4 + ["Silver"] * 4 + ["Copper"] * 2
    assert T.density(rich) >= 1.6


def test_best_bm_terminal_prefers_the_articles_ranking():
    assert T.best_bm_terminal(["Smithy", "Wharf", "Village"]) == "Wharf"
    assert T.best_bm_terminal(["Smithy", "Moat"]) == "Smithy"
    assert T.best_bm_terminal(["Village", "Festival"]) is None      # no drawer
    # an empty pile is not a terminal you can buy
    assert T.best_bm_terminal(["Smithy", "Wharf"],
                              supply={"Smithy": 10, "Wharf": 0}) == "Smithy"


def test_card_quality_rankings_are_real_cards_and_normalized():
    """The ThunderDominion 2022 rankings are transcribed by hand — guard against
    a typo (a name that is not a real card) and against a broken normalization.
    Not a COMPLETENESS check: a future expansion the 2022 list never ranked is
    fine (card_power falls back to cost), so we don't force every kingdom card
    to appear."""
    from games.dontminion.cards import CARDS, KINGDOM
    bad = sorted(n for n in T.CARD_QUALITY if n not in CARDS)
    assert not bad, f"CARD_QUALITY has names that are not cards: {bad}"
    # every current kingdom card IS ranked today (all five sets were captured)
    kingdom = set(sum((KINGDOM[s] for s in KINGDOM), []))
    assert all(T.quality(c) is not None for c in kingdom)
    # normalized to (0, 1], best in each set ~1.0
    assert all(0 < q <= 1 for q in T.CARD_QUALITY.values())
    assert T.quality("Chapel") == 1.0 and T.quality("Wharf") == 1.0
    assert T.quality("Bureaucrat") < 0.1        # last in Base
