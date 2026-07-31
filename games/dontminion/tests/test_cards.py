"""Card-data tests: the verified 139-card dataset (Base + Intrigue + Seaside +
Prosperity + Hinterlands, all 2E).

Pure data tests — no engine import. The EXPECTED table below is the corruption tell:
every (name, cost, types) triple was verified against the Knutsen compendium v11.1
(ch. V + ch. VII Card Reference) and the dominionstrategy.com 2E card lists.
"""

from games.dontminion import cards


ALLOWED_TYPES = {"action", "treasure", "victory", "curse", "attack", "reaction", "duration"}
ALLOWED_EXPANSIONS = {"basic", "base", "intrigue", "seaside", "prosperity", "hinterlands"}
SCHEMA_FIELDS = {"cost", "types", "coins", "vp", "text", "expansion", "kingdom"}

REMOVED_1E = [
    # Base 1E -> 2E removals
    "Adventurer", "Chancellor", "Feast", "Spy", "Thief", "Woodcutter",
    # Intrigue 1E -> 2E removals
    "Coppersmith", "Great Hall", "Saboteur", "Scout", "Secret Chamber", "Tribute",
    # Seaside 1E -> 2E removals
    "Ambassador", "Embargo", "Explorer", "Ghost Ship", "Navigator", "Pearl Diver",
    "Pirate Ship", "Sea Hag",
    # Prosperity 1E -> 2E removals
    "Contraband", "Counting House", "Goons", "Loan", "Mountebank", "Royal Seal",
    "Talisman", "Trade Route", "Venture",
]

# The full verified (cost, types) table for all 59 cards.
EXPECTED = {
    # basic (7)
    "Copper": (0, ["treasure"]),
    "Silver": (3, ["treasure"]),
    "Gold": (6, ["treasure"]),
    "Estate": (2, ["victory"]),
    "Duchy": (5, ["victory"]),
    "Province": (8, ["victory"]),
    "Curse": (0, ["curse"]),
    # Base 2E kingdom (26)
    "Cellar": (2, ["action"]),
    "Chapel": (2, ["action"]),
    "Moat": (2, ["action", "reaction"]),
    "Harbinger": (3, ["action"]),
    "Merchant": (3, ["action"]),
    "Vassal": (3, ["action"]),
    "Village": (3, ["action"]),
    "Workshop": (3, ["action"]),
    "Bureaucrat": (4, ["action", "attack"]),
    "Gardens": (4, ["victory"]),
    "Militia": (4, ["action", "attack"]),
    "Moneylender": (4, ["action"]),
    "Poacher": (4, ["action"]),
    "Remodel": (4, ["action"]),
    "Smithy": (4, ["action"]),
    "Throne Room": (4, ["action"]),
    "Bandit": (5, ["action", "attack"]),
    "Council Room": (5, ["action"]),
    "Festival": (5, ["action"]),
    "Laboratory": (5, ["action"]),
    "Library": (5, ["action"]),
    "Market": (5, ["action"]),
    "Mine": (5, ["action"]),
    "Sentry": (5, ["action"]),
    "Witch": (5, ["action", "attack"]),
    "Artisan": (6, ["action"]),
    # Intrigue 2E kingdom (26)
    "Courtyard": (2, ["action"]),
    "Lurker": (2, ["action"]),
    "Pawn": (2, ["action"]),
    "Masquerade": (3, ["action"]),
    "Shanty Town": (3, ["action"]),
    "Steward": (3, ["action"]),
    "Swindler": (3, ["action", "attack"]),
    "Wishing Well": (3, ["action"]),
    "Baron": (4, ["action"]),
    "Bridge": (4, ["action"]),
    "Conspirator": (4, ["action"]),
    "Diplomat": (4, ["action", "reaction"]),
    "Ironworks": (4, ["action"]),
    "Mill": (4, ["action", "victory"]),
    "Mining Village": (4, ["action"]),
    "Secret Passage": (4, ["action"]),
    "Courtier": (5, ["action"]),
    "Duke": (5, ["victory"]),
    "Minion": (5, ["action", "attack"]),
    "Patrol": (5, ["action"]),
    "Replace": (5, ["action", "attack"]),
    "Torturer": (5, ["action", "attack"]),
    "Trading Post": (5, ["action"]),
    "Upgrade": (5, ["action"]),
    "Farm": (6, ["treasure", "victory"]),
    "Nobles": (6, ["action", "victory"]),
    # Seaside 2E kingdom (27)
    "Haven": (2, ["action", "duration"]),
    "Lighthouse": (2, ["action", "duration"]),
    "Native Village": (2, ["action"]),
    "Astrolabe": (3, ["treasure", "duration"]),
    "Fishing Village": (3, ["action", "duration"]),
    "Lookout": (3, ["action"]),
    "Monkey": (3, ["action", "duration"]),
    "Sea Chart": (3, ["action"]),
    "Smugglers": (3, ["action"]),
    "Warehouse": (3, ["action"]),
    "Blockade": (4, ["action", "duration", "attack"]),
    "Caravan": (4, ["action", "duration"]),
    "Cutpurse": (4, ["action", "attack"]),
    "Island": (4, ["action", "victory"]),
    "Sailor": (4, ["action", "duration"]),
    "Salvager": (4, ["action"]),
    "Tide Pools": (4, ["action", "duration"]),
    "Treasure Map": (4, ["action"]),
    "Bazaar": (5, ["action"]),
    "Corsair": (5, ["action", "duration", "attack"]),
    "Merchant Ship": (5, ["action", "duration"]),
    "Outpost": (5, ["action", "duration"]),
    "Pirate": (5, ["action", "duration", "reaction"]),
    "Sea Witch": (5, ["action", "duration", "attack"]),
    "Tactician": (5, ["action", "duration"]),
    "Treasury": (5, ["action"]),
    "Wharf": (5, ["action", "duration"]),
    # Prosperity 2E kingdom (25) + Platinum/Colony
    "Platinum": (9, ["treasure"]),
    "Colony": (11, ["victory"]),
    "Anvil": (3, ["treasure"]),
    "Watchtower": (3, ["action", "reaction"]),
    "Bishop": (4, ["action"]),
    "Clerk": (4, ["action", "reaction", "attack"]),
    "Investment": (4, ["treasure"]),
    "Monument": (4, ["action"]),
    "Quarry": (4, ["treasure"]),
    "Tiara": (4, ["treasure"]),
    "Worker's Village": (4, ["action"]),
    "Charlatan": (5, ["action", "attack"]),
    "City": (5, ["action"]),
    "Collection": (5, ["treasure"]),
    "Crystal Ball": (5, ["treasure"]),
    "Magnate": (5, ["action"]),
    "Mint": (5, ["action"]),
    "Rabble": (5, ["action", "attack"]),
    "Vault": (5, ["action"]),
    "War Chest": (5, ["treasure"]),
    "Grand Market": (6, ["action"]),
    "Hoard": (6, ["treasure"]),
    "Bank": (7, ["treasure"]),
    "Expand": (7, ["action"]),
    "Forge": (7, ["action"]),
    "King's Court": (7, ["action"]),
    "Peddler": (8, ["action"]),
    # Hinterlands 2E kingdom (26) - 17 kept from 1E + 9 new in 2E
    "Crossroads": (2, ['action']),
    "Fool's Gold": (2, ['treasure', 'reaction']),
    "Develop": (3, ['action']),
    "Guard Dog": (3, ['action', 'reaction']),
    "Oasis": (3, ['action']),
    "Scheme": (3, ['action']),
    "Tunnel": (3, ['victory', 'reaction']),
    "Jack of All Trades": (4, ['action']),
    "Nomads": (4, ['action']),
    "Spice Merchant": (4, ['action']),
    "Trader": (4, ['action', 'reaction']),
    "Trail": (4, ['action', 'reaction']),
    "Weaver": (4, ['action', 'reaction']),
    "Berserker": (5, ['action', 'attack']),
    "Cartographer": (5, ['action']),
    "Cauldron": (5, ['treasure', 'attack']),
    "Haggler": (5, ['action']),
    "Highway": (5, ['action']),
    "Inn": (5, ['action']),
    "Margrave": (5, ['action', 'attack']),
    "Souk": (5, ['action']),
    "Stables": (5, ['action']),
    "Wheelwright": (5, ['action']),
    "Witch's Hut": (5, ['action', 'attack']),
    "Border Village": (6, ['action']),
    "Farmland": (6, ['victory']),
}

BASIC_7 = ["Copper", "Silver", "Gold", "Estate", "Duchy", "Province", "Curse"]


def test_data_complete():
    assert cards.DATA_COMPLETE is True


def test_bandit_ruling_constant():
    # Compendium v11.1: the attacked player performs (and chooses) the trash.
    assert cards.BANDIT_VICTIM_CHOOSES is True


def test_card_count_and_expansion_counts():
    assert len(cards.CARDS) == 139
    by_exp = {"basic": [], "base": [], "intrigue": [], "seaside": [],
              "prosperity": [], "hinterlands": []}
    for name, c in cards.CARDS.items():
        by_exp[c["expansion"]].append(name)
    assert len(by_exp["basic"]) == 7
    assert len(by_exp["base"]) == 26
    assert len(by_exp["intrigue"]) == 26
    assert len(by_exp["seaside"]) == 27
    assert len(by_exp["prosperity"]) == 27      # 25 kingdom + Platinum + Colony
    assert len(by_exp["hinterlands"]) == 26     # 17 kept from 1E + 9 new in 2E
    assert sorted(by_exp["basic"]) == sorted(BASIC_7)


def test_kingdom_lists_match_flags_no_duplicates():
    for exp, want in (("base", 26), ("intrigue", 26), ("seaside", 27),
                      ("prosperity", 25), ("hinterlands", 26)):
        names = cards.KINGDOM[exp]
        assert len(names) == want
        assert len(set(names)) == want  # no duplicates
        for n in names:
            assert cards.CARDS[n]["kingdom"] is True
            assert cards.CARDS[n]["expansion"] == exp
    # every kingdom-flagged card appears in exactly one KINGDOM list
    flagged = {n for n, c in cards.CARDS.items() if c["kingdom"]}
    listed = set().union(*(set(v) for v in cards.KINGDOM.values()))
    assert flagged == listed
    # the expansion lists are pairwise disjoint — a card belongs to exactly one
    names = list(cards.KINGDOM)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            overlap = set(cards.KINGDOM[a]) & set(cards.KINGDOM[b])
            assert not overlap, f"{a}/{b} share {sorted(overlap)}"
    # basics are never kingdom cards
    for n in BASIC_7:
        assert cards.CARDS[n]["kingdom"] is False


def test_removed_1e_cards_absent():
    for name in REMOVED_1E:
        assert name not in cards.CARDS, f"1E card {name} must not be in the 2E roster"


def test_schema_field_completeness_and_validity():
    str_vp = []
    for name, c in cards.CARDS.items():
        assert set(c.keys()) == SCHEMA_FIELDS, name
        # cost
        assert type(c["cost"]) is int and 0 <= c["cost"] <= 11, name   # Colony is $11
        # types
        assert isinstance(c["types"], list) and c["types"], name
        assert all(t in ALLOWED_TYPES for t in c["types"]), name
        assert len(set(c["types"])) == len(c["types"]), name
        # coins: treasures > 0, everything else exactly 0
        assert type(c["coins"]) is int, name
        if "treasure" in c["types"]:
            # computed/zero producers (Bank, Tiara, Investment, War Chest) print no $
            assert c["coins"] >= 0, name
        else:
            assert c["coins"] == 0, name
        # vp: int, or the two computed-rule strings
        if isinstance(c["vp"], str):
            str_vp.append((name, c["vp"]))
        else:
            assert type(c["vp"]) is int, name
        # text / expansion / kingdom
        assert isinstance(c["text"], str) and c["text"].strip(), name
        assert c["expansion"] in ALLOWED_EXPANSIONS, name
        assert isinstance(c["kingdom"], bool), name
    assert sorted(str_vp) == [("Duke", "duke"), ("Gardens", "gardens")]


def test_static_vp_values():
    expected_vp = {"Estate": 1, "Duchy": 3, "Province": 6, "Curse": -1,
                   "Farm": 2, "Mill": 1, "Nobles": 2, "Island": 2, "Colony": 10,
                   "Farmland": 2, "Tunnel": 2}          # Hinterlands
    for name, vp in expected_vp.items():
        assert cards.CARDS[name]["vp"] == vp, name
    # every other int-vp card is 0
    for name, c in cards.CARDS.items():
        if name not in expected_vp and not isinstance(c["vp"], str):
            assert c["vp"] == 0, name


def test_treasure_coin_values():
    assert cards.CARDS["Copper"]["coins"] == 1
    assert cards.CARDS["Silver"]["coins"] == 2
    assert cards.CARDS["Gold"]["coins"] == 3
    assert cards.CARDS["Farm"]["coins"] == 2
    assert cards.CARDS["Astrolabe"]["coins"] == 1
    assert cards.CARDS["Platinum"]["coins"] == 5


def test_full_name_cost_types_table():
    # The corruption tell: every one of the 113 (name, cost, types) triples, literally.
    assert set(cards.CARDS.keys()) == set(EXPECTED.keys())
    for name, (cost, types) in EXPECTED.items():
        c = cards.CARDS[name]
        assert c["cost"] == cost, f"{name}: cost {c['cost']} != {cost}"
        assert c["types"] == types, f"{name}: types {c['types']} != {types}"


def test_pile_sizes():
    for n_players, copper, curse, victory in [(2, 46, 10, 8), (3, 39, 20, 12), (4, 32, 30, 12)]:
        assert cards.pile_size("Copper", n_players) == copper
        assert cards.pile_size("Curse", n_players) == curse
        # basic + kingdom victory-typed piles all use the victory size
        for v in ("Estate", "Duchy", "Province", "Gardens", "Duke", "Farm", "Mill", "Nobles"):
            assert cards.pile_size(v, n_players) == victory, v
        assert cards.pile_size("Silver", n_players) == 40
        assert cards.pile_size("Gold", n_players) == 30
        assert cards.pile_size("Smithy", n_players) == 10


# --- kingdom requirements (create-time "guarantee me a village/+Buy/drawer") ---

def test_requirement_pools_are_the_expected_cards():
    """The pools are DERIVED from card text, so a regex slip would silently
    change what "Require: +2 Actions" means. Pin the membership; a new set adds
    names here on purpose."""
    assert cards.REQUIREMENT_ORDER == ("actions", "buys", "draw")
    assert set(cards.REQUIREMENTS) == set(cards.REQUIREMENT_ORDER)
    assert cards.cards_granting("actions") == [
        "Bazaar", "Border Village", "City", "Crossroads", "Diplomat", "Festival",
        "Fishing Village", "Inn", "Mining Village", "Native Village", "Nobles",
        "Shanty Town", "Village", "Worker's Village"]
    assert cards.cards_granting("buys") == [
        "Astrolabe", "Baron", "Bridge", "Cauldron", "City", "Collection",
        "Council Room", "Courtier", "Festival", "Grand Market", "Margrave",
        "Market", "Nomads", "Pawn", "Salvager", "Souk", "Spice Merchant",
        "Tactician", "Tiara", "Wharf", "Worker's Village"]
    assert cards.cards_granting("draw") == [
        "Council Room", "Courtyard", "Diplomat", "Guard Dog", "Inn",
        "Laboratory", "Margrave", "Masquerade", "Minion", "Moat", "Nobles",
        "Patrol", "Rabble", "Sea Witch", "Secret Passage", "Shanty Town",
        "Smithy", "Spice Merchant", "Stables", "Steward", "Tactician",
        "Tide Pools", "Torturer", "Vault", "Warehouse", "Wharf", "Witch",
        "Witch's Hut"]


def test_requirement_bar_is_the_printed_bonus():
    # the threshold really binds: a cantrip is not a village, a Moat is a drawer
    assert cards.grants("Village", "actions") and not cards.grants("Market", "actions")
    assert cards.grants("Market", "buys") and not cards.grants("Village", "buys")
    assert cards.grants("Moat", "draw") and not cards.grants("Market", "draw")
    # one card can answer two requirements (the dealer must not spend two slots)
    assert cards.grants("Worker's Village", "actions") and cards.grants("Worker's Village", "buys")
    # deliberate exclusions: variable / draw-to-X / multipliers are not counted
    for name in ("Cellar", "Library", "Throne Room", "Harbinger"):
        assert not any(cards.grants(name, r) for r in cards.REQUIREMENT_ORDER), name


def test_every_expansion_alone_can_satisfy_every_requirement():
    """A one-expansion game must never be able to ask for something the pool
    can't give — that would be an unsatisfiable create the player can reach."""
    for exp, pool in sorted(cards.KINGDOM.items()):
        for req in cards.REQUIREMENT_ORDER:
            assert cards.cards_granting(req, pool), f"{exp} has no {req} card"
