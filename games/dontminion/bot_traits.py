"""Card traits — the shared vocabulary every bot tier reasons in.

Two layers, on purpose:

* **DERIVED** (`plus_cards`/`plus_actions`/`plus_buys`/`plus_coins` and the
  village/cantrip/terminal-draw classifications built on them) come from the
  printed text, the way `cards.KINGDOM` and `cards.grants` derive from the data.
  A new expansion's villages and smithies classify themselves the day they ship.
* **REVIEWED** (trasher class, curser, attack kind, gainer, sifter, defense,
  alt-VP, the Big-Money terminal ranking) cannot be derived — "trash up to 4"
  and "trash the top card of their deck" read identically to a regex but mean
  opposite things. These are hand-tagged, and `REVIEWED` lists every kingdom
  card that has been looked at.

**A new set's cards MUST be added to `REVIEWED`** — `test_bot_traits.py` fails
otherwise. That is the whole point: an unreviewed card silently classified as
"a plain terminal" would quietly mis-steer every tier above Big Money, and the
failure would look like the bot playing badly rather than like missing data.

Nothing here reads game state; traits are a pure function of the card name, so
callers can cache freely.
"""

import functools
import re

from .cards import CARDS, KINGDOM

# ── derived: printed bonuses ─────────────────────────────────────────────────


def _printed(text, word):
    """Largest printed "+N <word>s" (0 if none). Same bar as cards.grants."""
    return max([int(n) for n in re.findall(rf"\+(\d+) {word}s?\b", text)] or [0])


def _printed_coins(text):
    """Largest printed "+$N" (0 if none) — the coin analog of _printed."""
    return max([int(n) for n in re.findall(r"\+\$(\d+)", text)] or [0])


# ── reviewed: what text cannot tell you ──────────────────────────────────────
#
# Trasher strength, ordered by the Level-10 article's ranking (Forge > Chapel >
# Steward) and the "trash-for-benefit beats weak trashers" rule:
#   "mass"    — trashes 3+ at once; the deck-thinning engines are built on these
#   "multi"   — trashes exactly 2
#   "tfb"     — trash-for-benefit: converts a card into something better
#   "weak"    — trashes one card, or only one narrow type
TRASHERS = {
    "Chapel": "mass", "Forge": "mass",
    "Steward": "multi", "Trading Post": "multi", "Souk": "multi",
    "Remodel": "tfb", "Mine": "tfb", "Upgrade": "tfb", "Replace": "tfb",
    "Expand": "tfb", "Develop": "tfb", "Salvager": "tfb", "Bishop": "tfb",
    "Moneylender": "tfb", "Spice Merchant": "tfb", "Trader": "tfb",
    "Investment": "tfb", "Farmland": "tfb",
    "Masquerade": "weak", "Lookout": "weak", "Sentry": "weak",
    "Jack of All Trades": "weak", "Sailor": "weak", "Treasure Map": "weak",
    "Lurker": "weak",           # trashes from the SUPPLY, not your deck
    # Cornucopia & Guilds
    "Butcher": "tfb", "Remake": "tfb", "Stonemason": "tfb",
    "Infirmary": "weak",
}

# Attack kind — what the attack DOES to its victims. Drives both the defensive
# read (do I need a Moat?) and the offensive one (is this attack still worth
# playing against a greening opponent — the R10 rule).
ATTACKS = {
    "Witch": "curse", "Sea Witch": "curse", "Charlatan": "curse",
    "Cauldron": "curse", "Witch's Hut": "curse", "Torturer": "curse",
    "Replace": "curse", "Blockade": "curse",
    "Militia": "discard", "Margrave": "discard", "Berserker": "discard",
    "Minion": "discard", "Cutpurse": "discard",
    "Bandit": "trash", "Swindler": "trash", "Corsair": "trash",
    "Bureaucrat": "topdeck", "Rabble": "topdeck", "Clerk": "topdeck",
    # Cornucopia & Guilds. Jester is filed under "curse" for the DEFENSIVE
    # read that matters — on a Victory card it hands out a Curse, and the
    # alternative (a copy of what they discarded) is not reliably junk.
    "Young Witch": "curse", "Soothsayer": "curse", "Jester": "curse",
    "Footpad": "discard",
}

# Cards that answer an Attack from hand (the reaction window / immunity).
DEFENSE = {"Moat", "Lighthouse", "Guard Dog", "Diplomat"}

# Gains a card from the supply without buying it.
GAINERS = {
    "Workshop", "Ironworks", "Artisan", "Smugglers", "Weaver", "Wheelwright",
    "Haggler", "Border Village", "Mint", "War Chest", "Anvil", "Tiara",
    "Berserker", "Develop", "Trader", "Remodel", "Upgrade", "Replace",
    "Expand", "Forge", "Farmland", "Bureaucrat", "Bandit", "Blockade",
    "Pirate", "Jack of All Trades", "Treasure Map", "Lurker", "Mine",
    # Cornucopia & Guilds
    "Butcher", "Remake", "Stonemason", "Horn of Plenty", "Soothsayer",
    "Demesne", "Courser",
}

# The subset that can gain ANY pile of its own choosing, repeatably, without
# spending a card to do it — i.e. the cards that can actually drain a pile.
# This is the distinction a rush plan lives or dies on: Bureaucrat and Bandit
# are in GAINERS (they gain a Silver, a Gold) but can no more empty the Gardens
# pile than a Copper can, and a rush selector that counts them fires on boards
# with no rush (measured: it bought 8 Gardens into a 25-card deck and lost at
# 0.165). The remodel family is excluded for the same reason — each gain costs
# a card from your hand, so the deck never grows.
PILE_GAINERS = {"Workshop", "Ironworks", "Artisan", "Wheelwright", "Weaver",
                "Haggler", "War Chest", "Anvil", "Tiara", "Smugglers"}

# Looks at / discards / reorders cards to improve what you draw. The
# reshuffle-control rules (R4: "don't overcartograph") key on these.
SIFTERS = {
    "Cellar", "Warehouse", "Cartographer", "Oasis", "Lookout", "Sentry",
    "Harbinger", "Vault", "Stables", "Inn", "Tide Pools", "Sea Chart",
    "Crystal Ball", "Jack of All Trades", "Patrol", "Library", "Scheme",
    "Native Village", "Haven", "Secret Passage", "Courtyard", "Wishing Well",
}

# Victory cards whose value is NOT a fixed number — the alt-VP article's
# subject. The value is the RULE, so a bot can price them per board.
ALT_VP = {
    "Gardens": "per_10_cards", "Duke": "per_duchy", "Farm": "treasure_vp",
    "Mill": "action_vp", "Nobles": "action_vp", "Island": "action_vp",
    "Tunnel": "reaction_vp", "Farmland": "on_gain_vp",
    "Fairgrounds": "per_5_distinct", "Demesne": "per_gold",
}

# Accumulates VP tokens — never lost, never clogs the deck (a slog's engine).
VP_TOKENS = {"Monument", "Bishop", "Collection", "Investment"}

# Draws a variable number of cards, so it prints no "+N Cards" and the derived
# `draw` flag misses it entirely. Library is a top-tier drawer that a
# text-derived classifier cannot see — it was absent from the engine plan's
# draw pool for exactly this reason.
DRAW_TO_X = {"Library", "Watchtower", "Jack of All Trades", "Magnate",
             "Cellar", "Crossroads", "Shanty Town", "Minion", "Tactician",
             # C&G: Advisor nets 2, Carnival up to 4, Journeyman exactly 3,
             # Housecarl scales with the table — none of them print "+N Cards"
             "Advisor", "Carnival", "Journeyman", "Housecarl"}

# Kingdom Treasures a money deck genuinely wants (the Terminal-Draw-BM
# article's list) vs the ones that are engine parts wearing a Treasure's
# clothes (Quarry discounts Actions BM never buys; Investment/War Chest/Crystal
# Ball push decisions a money deck gains nothing from).
BM_TREASURES = {"Fool's Gold", "Bank", "Hoard", "Farm", "Collection",
                "Astrolabe", "Cauldron", "Anvil", "Tiara"}

# How good a card is as Big Money's ONE terminal, higher = better. Ordered from
# the Terminal-Draw-BM article (Wharf best; cursers score for the Curses, not
# the pace; Smithy is the benchmark at 50). Cards absent from this table are
# not BM terminals at all — `bm_terminal_rank` returns 0 for them.
BM_TERMINALS = {
    "Wharf": 100,               # "best non-attack card": split draw + a Buy
    "Sea Witch": 95, "Witch": 92,           # cursing-BM wins on the split
    "Margrave": 88, "Torturer": 86,
    "Witch's Hut": 82, "Rabble": 78,
    "Jack of All Trades": 76,   # the double-Jack deck
    "Council Room": 70, "Library": 68,
    "Magnate": 60, "Vault": 58,
    "Smithy": 50,               # the benchmark
    "Courtyard": 46, "Militia": 44,
    "Patrol": 40, "Nobles": 36,
    "Steward": 30, "Moat": 20,
    # Cornucopia & Guilds. Ranked against the same article's logic: the cursers
    # score for the Curses (Young Witch is a Witch that can be blocked;
    # Soothsayer trades a card to them for the Gold), then the terminal draw.
    "Young Witch": 90, "Soothsayer": 84, "Footpad": 62, "Jester": 58,
    "Journeyman": 54, "Carnival": 45,
}

# Every kingdom card that has been reviewed against the tables above. A set
# lands => its 25-30 names land here => the test goes green again.
REVIEWED = frozenset(
    KINGDOM["base"] + KINGDOM["intrigue"] + KINGDOM["seaside"]
    + KINGDOM["prosperity"] + KINGDOM["hinterlands"] + KINGDOM["cornucopia"]
)


# ── the trait record ─────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=None)
def traits(name):
    """Every trait of `name`, as a plain dict. Pure function of the card."""
    c = CARDS[name]
    text = c["text"]
    types = c["types"]
    is_action = "action" in types
    plus_cards = _printed(text, "Card")
    plus_actions = _printed(text, "Action")
    plus_buys = _printed(text, "Buy")
    plus_coins = _printed_coins(text)
    return {
        "cost": c["cost"],
        "types": tuple(types),
        "action": is_action,
        "treasure": "treasure" in types,
        "victory": "victory" in types,
        "curse": "curse" in types,
        "attack": "attack" in types,
        "reaction": "reaction" in types,
        "duration": "duration" in types,
        "plus_cards": plus_cards,
        "plus_actions": plus_actions,
        "plus_buys": plus_buys,
        "plus_coins": plus_coins,
        # An Action that does NOT replace the action it costs. The single most
        # load-bearing classification in the whole file: the terminal budget
        # (≤1 per 5-6 cards) and every collision estimate read it.
        "terminal": is_action and plus_actions == 0,
        # Replaces itself: free to add to any deck.
        "cantrip": is_action and plus_actions >= 1 and plus_cards >= 1,
        # Pays for another terminal (+2 Actions or better).
        "village": plus_actions >= 2,
        # The engine's / BM's draw. "+2 Cards or better" is the article's bar.
        "draw": plus_cards >= 2,
        "draw_to_x": name in DRAW_TO_X,
        "terminal_draw": is_action and plus_actions == 0 and plus_cards >= 2,
        "plus_buy": plus_buys >= 1,
        # Coins this card puts in the pool: a Treasure's face value, or an
        # Action's printed +$N (the "virtual coin" a payload card gives).
        "coins": c["coins"] if "treasure" in types else plus_coins,
        "trasher": TRASHERS.get(name),
        "attack_kind": ATTACKS.get(name),
        "curser": ATTACKS.get(name) == "curse",
        "defense": name in DEFENSE,
        "gainer": name in GAINERS,
        "pile_gainer": name in PILE_GAINERS,
        "sifter": name in SIFTERS,
        "alt_vp": ALT_VP.get(name),
        "vp_tokens": name in VP_TOKENS,
        "bm_treasure": name in BM_TREASURES,
        "bm_terminal_rank": BM_TERMINALS.get(name, 0),
        "reviewed": name in REVIEWED or not c["kingdom"],
    }


def t(name, key):
    """One trait, terse — `t("Smithy", "terminal_draw")`."""
    return traits(name)[key]


def money_value(name):
    """Coins this card contributes to money DENSITY.

    Cantrips count as ZERO CARDS in the density math (they replace themselves —
    the "virtual card" rule), which the caller handles by excluding them from
    the denominator; here they still contribute their coins.
    """
    return traits(name)["coins"]


def density(owned):
    """Money density = coins per NON-CANTRIP card (the article's measure).

    Thresholds it is measured against: 1.6 buys Provinces reliably, 2.2 buys
    Colonies, 1.0 sustains a Duchy/Duke slog. A fresh deck is 7/10 = 0.7.
    """
    total = sum(money_value(c) for c in owned)
    n = sum(1 for c in owned if not traits(c)["cantrip"])
    return total / n if n else 0.0


def kingdom_traits(kingdom):
    """{name: traits} for a dealt kingdom — the board-read entry point."""
    return {n: traits(n) for n in kingdom}


def pile_traits(game, pile):
    """Traits of what a PILE is currently offering.

    `traits` is a pure function of a CARD, and a pile is not always the card it
    is named after — an ordered pile (Ruins, Knights, a split pile) shows its
    top card. So any read that STARTS from a Supply key has to come through
    here; calling traits() on the key is a KeyError the day ph. 6 ships Ruins,
    raised inside the scheduler's turn-finisher on a live game."""
    from . import engine                  # kept lazy: this module is card data
    return traits(engine.pile_face(game, pile))


def best_bm_terminal(kingdom, supply=None):
    """The kingdom's best Big-Money terminal, or None if it has none.

    `supply` (optional) skips piles that are already empty.
    """
    best, score = None, 0
    for n in kingdom:
        if n not in CARDS:
            # an ORDERED pile: what it offers changes as it empties, so it is
            # nobody's reliable terminal — and the deck-count rules below
            # ("the second Smithy at ~16 cards") can't count copies of a pile
            continue
        r = traits(n)["bm_terminal_rank"]
        if r > score and (supply is None or supply.get(n, 0) > 0):
            best, score = n, r
    return best
