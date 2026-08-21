"""THE DECK LAYER -- three widths, one id space, and the block discipline.

Dissonance has been widened twice. The base deck is 32 cards (7..A); dummy mode
deals 40 (+ the 5 and 6); the four-hand mode deals 52 (+ the 2, 3 and 4). All
three share ONE id space, and the rule that makes that safe is that each
widening APPENDS a block rather than renumbering:

    ids  0..31  the base deck      ranks 5..12   (7 8 9 10 J Q K A)
    ids 32..39  block A, 2026-08-10  ranks 3..4  (5 6)
    ids 40..51  block B, 2026-08-21  ranks 0..2  (2 3 4)

The obvious generalisation -- laying all five extra low ranks out contiguously
as `NCARD + suit * 5 + k` -- would have renumbered the 5 and the 6 into the 2
and the 3. `deal_is_current` could NOT have caught that: a renumbered dummy
save still holds forty distinct ids and still counts right against
`deck_size`, so every card would silently have changed rank in a live game.
These tests are the guard that a third widening does not do it either.
"""

from games.dissonance import engine as E


#: EVERY ID THAT HAS EVER SHIPPED, written down as the card it names. A literal
#: table on purpose: deriving it from `suit`/`rank` would just restate whatever
#: those functions currently do, and a renumbering is exactly the change that
#: keeps every formula self-consistent while moving what a saved game means.
CARD_NAMES = [
    "7c", "8c", "9c", "10c", "Jc", "Qc", "Kc", "Ac",
    "7d", "8d", "9d", "10d", "Jd", "Qd", "Kd", "Ad",
    "7h", "8h", "9h", "10h", "Jh", "Qh", "Kh", "Ah",
    "7s", "8s", "9s", "10s", "Js", "Qs", "Ks", "As",
    "5c", "6c", "5d", "6d", "5h", "6h", "5s", "6s",
    "2c", "3c", "4c", "2d", "3d", "4d", "2h", "3h",
    "4h", "2s", "3s", "4s",
]


def test_no_card_id_has_ever_changed_what_it_names():
    """The whole point of appending blocks. Ids 0..39 shipped before the full
    deck existed, and every saved dummy game and every classic/skat/minor row
    reads them; ids 40..51 are the new block and must sit ABOVE them."""
    assert len(CARD_NAMES) == E.NCARD_FULL == 52
    for c, name in enumerate(CARD_NAMES):
        assert E.card_name(c) == name, (c, E.card_name(c), name)


def test_the_id_space_is_a_bijection_and_card_of_inverts_it():
    seen = {}
    for c in range(E.NCARD_FULL):
        s, r = E.suit(c), E.rank(c)
        assert 0 <= s < E.NSUIT and 0 <= r < E.NRANKS, (c, s, r)
        assert (s, r) not in seen, ("two ids name one card", c, seen[(s, r)])
        seen[(s, r)] = c
        assert E.card_of(s, r) == c, ("card_of is not the inverse", c, s, r)
    assert len(seen) == E.NSUIT * E.NRANKS == 52


def test_a_deck_is_a_prefix_of_the_ids_and_a_top_slice_of_the_ranks():
    """THE INVARIANT EVERY DECK FUNCTION LEANS ON. `deck_size` alone says what
    the deck is -- callers write `range(deck_size(mode))` rather than carrying a
    set -- and that is only true while the two orderings agree: the first N ids
    must be exactly the top N/4 ranks. Block B is what could break it, since it
    appends HIGH ids holding LOW ranks."""
    for mode in E.MODES:
        n = E.deck_size(mode)
        assert n == E.NSUIT * E.nranks_for(mode)
        ranks = {E.rank(c) for c in range(n)}
        assert ranks == set(range(E.rank_offset(mode), E.NRANKS)), (mode,
                                                                   sorted(ranks))
        assert len({E.suit(c) for c in range(n)}) == E.NSUIT
        # every suit contributes the same ranks -- a deck is suits x ranks
        for s in range(E.NSUIT):
            assert {E.rank(c) for c in range(n) if E.suit(c) == s} == ranks


def test_the_shipped_deck_widths_are_the_ones_the_modes_expect():
    assert E.deck_size("classic") == E.deck_size("skat") == 32
    assert E.deck_size("minor") == 32
    assert E.deck_size("dummy") == E.NCARD_WIDE == 40
    assert E.rank_offset("classic") == E.BASE_OFFSET == 5
    assert E.rank_offset("dummy") == E.WIDE_OFFSET == 3
    assert E.rank_bounds("classic") == (5, 12)
    assert E.rank_bounds("dummy") == (3, 12)


def test_every_rank_table_spans_the_full_width():
    """A table indexed by `E.rank` must be `NRANKS` long or it raises on the
    ace -- the bug the skat swap policy already paid for once. Widening the
    deck is exactly when these fall out of step, so they are checked together
    rather than one per module."""
    from games.dissonance import bot
    assert len(E.RANK_NAMES) == E.NRANKS == 13
    assert len(E.CARD_VALUES) == E.NRANKS
    for name in ("_RANK_VALUE", "_SKAT_RANK_VALUE", "_SWAP_TAKE_W",
                 "_SWAP_GIVE_W", "_SK_TAKE_W", "_SK_GIVE_W"):
        assert len(getattr(bot, name)) == E.NRANKS, name
    # and every card in the widest deck can actually index them
    for c in range(E.NCARD_FULL):
        assert E.RANK_NAMES[E.rank(c)]
        assert E.card_points(c) in (-1, 0, 2)


def test_widening_the_deck_never_moved_the_card_point_total():
    """+16 AT EVERY WIDTH. A ladder or a level map keyed on what a deck adds up
    to must not be silently re-scaled by a mode that deals more cards, which is
    why each new rank is worth nothing."""
    assert E.card_pool_for("classic") == 16
    assert E.card_pool_for("dummy") == 16
    assert sum(E.card_points(c) for c in range(E.NCARD_FULL)) == 16
    assert all(E.card_points(c) == 0 for c in range(E.NCARD, E.NCARD_FULL))


def test_the_low_blocks_are_beaten_by_every_higher_card_in_suit():
    """Ordering is a plain `>` on strength, so the blocks being out of id order
    must not leak into play. Block B's ids are the HIGHEST in the deck and its
    cards are the WEAKEST."""
    for c in range(E.NCARD, E.NCARD_FULL):
        for b in range(E.NCARD_FULL):
            if E.suit(b) != E.suit(c) or b == c:
                continue
            hi, lo = (b, c) if E.rank(b) > E.rank(c) else (c, b)
            # `beats(led, follow)` asks whether FOLLOW takes the trick from LED
            assert E.beats(lo, hi, E.NOTRUMP)
            assert not E.beats(hi, lo, E.NOTRUMP)


def test_the_full_deck_deals_four_hands_of_thirteen_with_six_out():
    """The arithmetic the four-hand mode is built on, asserted before the mode
    exists so the deck is known to support it: 13 + 10 + 13 + 10 dealt is 46,
    leaving 6 out -- the same out-count classic's talon is cut from."""
    assert E.NCARD_FULL == 52
    assert 13 + 10 + 13 + 10 == 46
    assert E.NCARD_FULL - 46 == 6
    # ten tricks of four cards is forty played, six of the dealt cards kept
    assert 10 * 4 == 40
    assert 46 - 40 == 6      # three kept in each player's own hand
