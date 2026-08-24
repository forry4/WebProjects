"""Card-data tests: the verified 171-card dataset (Base + Intrigue + Seaside +
Prosperity + Hinterlands + Cornucopia & Guilds + Alchemy).

Pure data tests — no engine import. The EXPECTED table below is the corruption tell:
every (name, cost, types) triple was verified against the Knutsen compendium v11.1
(ch. V + ch. VII Card Reference) and the dominionstrategy.com 2E card lists.
"""

from games.dontminion import cards


ALLOWED_TYPES = {"action", "treasure", "victory", "curse", "attack", "reaction",
                 "duration", "reward", "command",
                 # Dark Ages: four inert flags the cards themselves read
                 "looter", "ruins", "knight", "shelter",
                 # Adventures: Reserve (waits on the Tavern mat to be CALLED)
                 # and Traveller (exchanges upward when discarded from play)
                 "reserve", "traveller",
                 # Empires: Castle (the eight cards of the Castles pile) and
                 # Gathering (a card that accumulates VP tokens on its own pile)
                 "castle", "gathering"}
ALLOWED_EXPANSIONS = {"basic", "base", "intrigue", "seaside", "prosperity",
                      "hinterlands", "cornucopia", "alchemy", "darkages",
                      "adventures", "empires", "renaissance", "menagerie"}
SCHEMA_FIELDS = {"cost", "types", "coins", "vp", "text", "expansion", "kingdom"}
# keys a card may carry IN ADDITION to the required schema
OPTIONAL_FIELDS = {"overpay",      # the `$N+` cost (Guilds/C&G)
                   "potion",       # the Potion component of a cost (Alchemy)
                   "debt"}         # the Debt component of a cost (Empires)

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
    # Cornucopia & Guilds 1E -> 2E removals (5 Cornucopia + 3 Guilds + 5 Prizes)
    "Doctor", "Farming Village", "Fortune Teller", "Harvest", "Horse Traders",
    "Masterpiece", "Taxman", "Tournament",
    "Bag of Gold", "Diadem", "Followers", "Princess", "Trusty Steed",
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
    # Cornucopia & Guilds 2E (26 kingdom + 6 Rewards)
    "Advisor": (4, ['action']),
    "Baker": (5, ['action']),
    "Butcher": (5, ['action']),
    "Candlestick Maker": (2, ['action']),
    "Carnival": (5, ['action']),
    "Coronet": (0, ['action', 'treasure', 'reward']),
    "Courser": (0, ['action', 'reward']),
    "Demesne": (0, ['action', 'victory', 'reward']),
    "Fairgrounds": (6, ['victory']),
    "Farmhands": (4, ['action']),
    "Farrier": (2, ['action']),
    "Ferryman": (5, ['action']),
    "Footpad": (5, ['action', 'attack']),
    "Hamlet": (2, ['action']),
    "Herald": (4, ['action']),
    "Horn of Plenty": (5, ['treasure']),
    "Housecarl": (0, ['action', 'reward']),
    "Huge Turnip": (0, ['treasure', 'reward']),
    "Hunting Party": (5, ['action']),
    "Infirmary": (3, ['action']),
    "Jester": (5, ['action', 'attack']),
    "Journeyman": (5, ['action']),
    "Joust": (5, ['action']),
    "Menagerie": (3, ['action']),
    "Merchant Guild": (5, ['action']),
    "Plaza": (4, ['action']),
    "Remake": (4, ['action']),
    "Renown": (0, ['action', 'reward']),
    "Shop": (3, ['action']),
    "Soothsayer": (5, ['action', 'attack']),
    "Stonemason": (2, ['action']),
    "Young Witch": (4, ['action', 'attack']),
    # Alchemy (11 shipped kingdom cards + Potion; Possession deferred)
    "Alchemist": (3, ['action']),
    "Apothecary": (2, ['action']),
    "Apprentice": (5, ['action']),
    "Familiar": (3, ['action', 'attack']),
    "Golem": (4, ['action']),
    "Herbalist": (2, ['action']),
    "Philosopher's Stone": (3, ['treasure']),
    "Potion": (4, ['treasure']),
    "Scrying Pool": (2, ['action', 'attack']),
    "Transmute": (0, ['action']),
    "University": (2, ['action']),
    "Vineyard": (0, ['victory']),
    # Dark Ages (34 kingdom cards; no second edition, so nothing is trimmed)
    "Poor House": (1, ['action']),
    "Beggar": (2, ['action', 'reaction']),
    "Squire": (2, ['action']),
    "Vagrant": (2, ['action']),
    "Forager": (3, ['action']),
    "Hermit": (3, ['action']),
    "Market Square": (3, ['action', 'reaction']),
    "Sage": (3, ['action']),
    "Storeroom": (3, ['action']),
    "Urchin": (3, ['action', 'attack']),
    "Armory": (4, ['action']),
    "Death Cart": (4, ['action', 'looter']),
    "Feodum": (4, ['victory']),
    "Fortress": (4, ['action']),
    "Ironmonger": (4, ['action']),
    "Marauder": (4, ['action', 'attack', 'looter']),
    "Procession": (4, ['action']),
    "Rats": (4, ['action']),
    "Scavenger": (4, ['action']),
    "Wandering Minstrel": (4, ['action']),
    "Band of Misfits": (5, ['action', 'command']),
    "Bandit Camp": (5, ['action']),
    "Catacombs": (5, ['action']),
    "Count": (5, ['action']),
    "Counterfeit": (5, ['treasure']),
    "Cultist": (5, ['action', 'attack', 'looter']),
    "Graverobber": (5, ['action']),
    "Junk Dealer": (5, ['action']),
    "Mystic": (5, ['action']),
    "Pillage": (5, ['action', 'attack']),
    "Rebuild": (5, ['action']),
    "Rogue": (5, ['action', 'attack']),
    "Altar": (6, ['action']),
    "Hunting Grounds": (6, ['action']),
    # the Knights — one shuffled pile of 10 ($5 each; Sir Martin is the
    # cheaper one, and Dame Josephine is also a Victory card)
    "Dame Anna": (5, ['action', 'attack', 'knight']),
    "Dame Josephine": (5, ['action', 'attack', 'knight', 'victory']),
    "Dame Molly": (5, ['action', 'attack', 'knight']),
    "Dame Natalie": (5, ['action', 'attack', 'knight']),
    "Dame Sylvia": (5, ['action', 'attack', 'knight']),
    "Sir Bailey": (5, ['action', 'attack', 'knight']),
    "Sir Destry": (5, ['action', 'attack', 'knight']),
    "Sir Martin": (4, ['action', 'attack', 'knight']),
    "Sir Michael": (5, ['action', 'attack', 'knight']),
    "Sir Vander": (5, ['action', 'attack', 'knight']),
    # the Ruins — one shuffled pile, all $0
    "Abandoned Mine": (0, ['action', 'ruins']),
    "Ruined Library": (0, ['action', 'ruins']),
    "Ruined Market": (0, ['action', 'ruins']),
    "Ruined Village": (0, ['action', 'ruins']),
    "Survivors": (0, ['action', 'ruins']),
    # the Shelters — they replace the 3 starting Estates
    "Hovel": (1, ['reaction', 'shelter']),
    "Necropolis": (1, ['action', 'shelter']),
    "Overgrown Estate": (1, ['victory', 'shelter']),
    # outside the Supply
    "Madman": (0, ['action']),
    "Mercenary": (0, ['action', 'attack']),
    # --- Adventures (30 kingdom) ---
    'Coin of the Realm': (2, ['treasure', 'reserve']),
    'Page': (2, ['action', 'traveller']),
    'Peasant': (2, ['action', 'traveller']),
    'Ratcatcher': (2, ['action', 'reserve']),
    'Raze': (2, ['action']),
    'Amulet': (3, ['action', 'duration']),
    'Caravan Guard': (3, ['action', 'duration', 'reaction']),
    'Dungeon': (3, ['action', 'duration']),
    'Gear': (3, ['action', 'duration']),
    'Guide': (3, ['action', 'reserve']),
    'Duplicate': (4, ['action', 'reserve']),
    'Magpie': (4, ['action']),
    'Messenger': (4, ['action']),
    'Miser': (4, ['action']),
    'Port': (4, ['action']),
    'Ranger': (4, ['action']),
    'Transmogrify': (4, ['action', 'reserve']),
    'Artificer': (5, ['action']),
    'Bridge Troll': (5, ['action', 'attack', 'duration']),
    'Distant Lands': (5, ['action', 'reserve', 'victory']),
    'Giant': (5, ['action', 'attack']),
    'Haunted Woods': (5, ['action', 'attack', 'duration']),
    'Lost City': (5, ['action']),
    'Relic': (5, ['treasure', 'attack']),
    'Royal Carriage': (5, ['action', 'reserve']),
    'Storyteller': (5, ['action']),
    'Swamp Hag': (5, ['action', 'attack', 'duration']),
    'Treasure Trove': (5, ['treasure']),
    'Wine Merchant': (5, ['action', 'reserve']),
    'Hireling': (6, ['action', 'duration']),
    # the 8 Traveller upgrades — non-Supply piles of 5, never bought
    'Treasure Hunter': (3, ['action', 'traveller']),
    'Warrior': (4, ['action', 'attack', 'traveller']),
    'Hero': (5, ['action', 'traveller']),
    'Champion': (6, ['action', 'duration']),
    'Soldier': (3, ['action', 'attack', 'traveller']),
    'Fugitive': (4, ['action', 'traveller']),
    'Disciple': (5, ['action', 'traveller']),
    'Teacher': (6, ['action', 'reserve']),
    "Spoils": (0, ['treasure']),

    # --- Empires (18 ordinary kingdom cards) ---
    # The four Debt-costed Actions print NO coin cost at all: {4D} and {8D}.
    'Engineer': (0, ['action']),
    'City Quarter': (0, ['action']),
    'Overlord': (0, ['action', 'command']),
    'Royal Blacksmith': (0, ['action']),
    'Chariot Race': (3, ['action']),
    'Enchantress': (3, ['action', 'attack', 'duration']),
    "Farmers' Market": (3, ['action', 'gathering']),
    'Sacrifice': (4, ['action']),
    'Temple': (4, ['action', 'gathering']),
    'Villa': (4, ['action']),
    'Archive': (5, ['action', 'duration']),
    'Capital': (5, ['treasure']),
    'Charm': (5, ['treasure']),
    'Crown': (5, ['action', 'treasure']),
    'Forum': (5, ['action']),
    'Groundskeeper': (5, ['action']),
    'Legionary': (5, ['action', 'attack']),
    'Wild Hunt': (5, ['action', 'gathering']),
    # --- Empires: the five split piles (cheap half on top) ---
    'Encampment': (2, ['action']),
    'Plunder': (5, ['treasure']),
    'Patrician': (2, ['action']),
    'Emporium': (5, ['action']),
    'Settlers': (2, ['action']),
    'Bustling Village': (5, ['action']),
    'Catapult': (3, ['action', 'attack']),
    'Rocks': (4, ['treasure']),
    'Gladiator': (3, ['action']),
    'Fortune': (8, ['treasure']),          # {$8, 8D}
    # --- Empires: the Castles pile, cheapest on top ---
    'Humble Castle': (3, ['treasure', 'victory', 'castle']),
    'Crumbling Castle': (4, ['victory', 'castle']),
    'Small Castle': (5, ['action', 'victory', 'castle']),
    'Haunted Castle': (6, ['victory', 'castle']),
    'Opulent Castle': (7, ['action', 'victory', 'castle']),
    'Sprawling Castle': (8, ['victory', 'castle']),
    'Grand Castle': (9, ['victory', 'castle']),
    "King's Castle": (10, ['victory', 'castle']),
    # --- Renaissance (25) — no second edition, all piles of 10 ---
    'Border Guard': (2, ['action']),
    'Ducat': (2, ['treasure']),
    'Lackeys': (2, ['action']),
    'Acting Troupe': (3, ['action']),
    'Cargo Ship': (3, ['action', 'duration']),
    'Experiment': (3, ['action']),
    'Improve': (3, ['action']),
    'Flag Bearer': (4, ['action']),
    'Hideout': (4, ['action']),
    'Inventor': (4, ['action']),
    'Mountain Village': (4, ['action']),
    'Patron': (4, ['action', 'reaction']),
    'Priest': (4, ['action']),
    'Research': (4, ['action', 'duration']),
    'Silk Merchant': (4, ['action']),
    'Old Witch': (5, ['action', 'attack']),
    'Recruiter': (5, ['action']),
    'Scepter': (5, ['treasure', 'command']),   # the 2024 errata added Command
    'Scholar': (5, ['action']),
    'Sculptor': (5, ['action']),
    'Seer': (5, ['action']),
    'Spices': (5, ['treasure']),
    'Swashbuckler': (5, ['action']),
    'Treasurer': (5, ['action']),
    'Villain': (5, ['action', 'attack']),
    # Menagerie (31): 30 kingdom piles + Horse (non-Supply)
    'Horse': (3, ['action']),
    'Black Cat': (2, ['action', 'attack', 'reaction']),
    'Sleigh': (2, ['action', 'reaction']),
    'Supplies': (2, ['treasure']),
    'Camel Train': (3, ['action']),
    'Goatherd': (3, ['action']),
    'Scrap': (3, ['action']),
    'Sheepdog': (3, ['action', 'reaction']),
    'Snowy Village': (3, ['action']),
    'Stockpile': (3, ['treasure']),
    'Bounty Hunter': (4, ['action']),
    'Cardinal': (4, ['action', 'attack']),
    'Cavalry': (4, ['action']),
    'Groom': (4, ['action']),
    'Hostelry': (4, ['action']),
    'Village Green': (4, ['action', 'duration', 'reaction']),
    'Barge': (5, ['action', 'duration']),
    'Coven': (5, ['action', 'attack']),
    'Displace': (5, ['action']),
    'Falconer': (5, ['action', 'reaction']),
    'Fisherman': (5, ['action']),
    'Gatekeeper': (5, ['action', 'duration', 'attack']),
    'Hunting Lodge': (5, ['action']),
    'Kiln': (5, ['action']),
    'Livery': (5, ['action']),
    'Mastermind': (5, ['action', 'duration']),
    'Paddock': (5, ['action']),
    'Sanctuary': (5, ['action']),
    'Destrier': (6, ['action']),
    'Wayfarer': (6, ['action']),
    'Animal Fair': (7, ['action']),
}

BASIC_7 = ["Copper", "Silver", "Gold", "Estate", "Duchy", "Province", "Curse"]


def test_data_complete():
    assert cards.DATA_COMPLETE is True


def test_bandit_ruling_constant():
    # Compendium v11.1: the attacked player performs (and chooses) the trash.
    assert cards.BANDIT_VICTIM_CHOOSES is True


def test_card_count_and_expansion_counts():
    assert len(cards.CARDS) == 368
    by_exp = {"basic": [], "base": [], "intrigue": [], "seaside": [],
              "prosperity": [], "hinterlands": [], "cornucopia": [],
              "alchemy": [], "darkages": [], "adventures": [],
              "empires": [], "renaissance": [], "menagerie": []}
    for name, c in cards.CARDS.items():
        by_exp[c["expansion"]].append(name)
    # 34 kingdom + 10 Knights + 5 Ruins + 3 Shelters + Spoils/Madman/Mercenary
    assert len(by_exp["darkages"]) == 55
    assert len(by_exp["basic"]) == 7
    assert len(by_exp["base"]) == 26
    assert len(by_exp["intrigue"]) == 26
    assert len(by_exp["seaside"]) == 27
    assert len(by_exp["prosperity"]) == 27      # 25 kingdom + Platinum + Colony
    assert len(by_exp["hinterlands"]) == 26     # 17 kept from 1E + 9 new in 2E
    assert len(by_exp["cornucopia"]) == 32      # 18 kept + 8 new + 6 Rewards
    assert len(by_exp["alchemy"]) == 12         # 11 shipped + Potion; see DEFERRED
    # 30 kingdom + the 8 Traveller upgrades (non-Supply piles of 5)
    assert len(by_exp["adventures"]) == 38
    # 18 ordinary kingdom cards + the 10 split-pile halves + the 8 Castles
    assert len(by_exp["empires"]) == 36
    # Renaissance has no second edition and no extra cards — the 25 kingdom
    # piles are the whole set (the 20 Projects are LANDSCAPES and the 5
    # Artifacts are neither cards nor landscapes; see cards.ARTIFACTS)
    assert len(by_exp["renaissance"]) == 25
    # Menagerie: 30 kingdom piles + Horse, which is a card of the set but sits
    # OUTSIDE the Supply (the 20 Events and 20 Ways are LANDSCAPES, and Way of
    # the Mouse's set-aside card is borrowed from another set's undealt ten)
    assert len(by_exp["menagerie"]) == 31
    assert sorted(by_exp["basic"]) == sorted(BASIC_7)


def test_kingdom_lists_match_flags_no_duplicates():
    for exp, want in (("base", 26), ("intrigue", 26), ("seaside", 27),
                      ("prosperity", 25), ("hinterlands", 26),
                      ("cornucopia", 26), ("alchemy", 11), ("darkages", 35),
                      # 18 ordinary piles + 5 split piles + Castles
                      ("empires", 24), ("renaissance", 25),
                      ("menagerie", 30)):
        names = cards.KINGDOM[exp]
        assert len(names) == want
        assert len(set(names)) == want  # no duplicates
        for n in names:
            # an entry is a kingdom CARD, or a dealt PILE whose name is not a
            # card at all ("Knight" and "Ruins" are types, not names)
            spec = cards.CARDS.get(n) or cards.PILES[n]
            assert spec["kingdom"] is True
            assert spec["expansion"] == exp
    # every kingdom-flagged card appears in exactly one KINGDOM list
    flagged = {n for n, c in cards.CARDS.items() if c["kingdom"]}
    listed = set().union(*(set(v) for v in cards.KINGDOM.values()))
    assert flagged == listed - set(cards.PILES)
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
        assert SCHEMA_FIELDS <= set(c.keys()), name
        assert set(c.keys()) - SCHEMA_FIELDS <= OPTIONAL_FIELDS, name
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
    assert sorted(str_vp) == [("Demesne", "demesne"),
                              # the first VP kind that depends on WHERE the
                              # card is, not on what else you own (ph. 7)
                              ("Distant Lands", "distant_lands"),
                              ("Duke", "duke"), ("Fairgrounds", "fairgrounds"),
                              ("Feodum", "feodum"), ("Gardens", "gardens"),
                              # Empires: both count CASTLES, which is a type
                              ("Humble Castle", "humble_castle"),
                              ("King's Castle", "kings_castle"),
                              ("Vineyard", "vineyard")]


def test_static_vp_values():
    expected_vp = {"Estate": 1, "Duchy": 3, "Province": 6, "Curse": -1,
                   "Farm": 2, "Mill": 1, "Nobles": 2, "Island": 2, "Colony": 10,
                   "Farmland": 2, "Tunnel": 2,          # Hinterlands
                   # Dark Ages: a Knight that is also a Victory card, and a
                   # Shelter printed as a literal 0 VP
                   "Dame Josephine": 2, "Overgrown Estate": 0,
                   # Empires: the six Castles with a printed number (Humble and
                   # King's count Castles instead, so they are computed)
                   "Crumbling Castle": 1, "Small Castle": 2,
                   "Haunted Castle": 2, "Opulent Castle": 3,
                   "Sprawling Castle": 4, "Grand Castle": 5}
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
        'Bandit Camp', 'Bazaar', 'Border Village', 'City', 'City Quarter',
        'Crossroads', 'Diplomat', 'Farmhands', 'Festival', 'Fishing Village',
        'Fortress', 'Hideout', 'Hostelry', 'Hunting Lodge', 'Inn',
        'Lost City', 'Mining Village', 'Mountain Village', 'Native Village',
        'Nobles', 'Plaza', 'Port', 'Sacrifice', 'Shanty Town',
        'Snowy Village', 'Squire', 'University', 'Villa', 'Village',
        'Village Green', 'Wandering Minstrel', "Worker's Village"]
    assert cards.cards_granting("buys") == [
        'Astrolabe', 'Barge', 'Baron', 'Bridge', 'Bridge Troll',
        'Candlestick Maker', 'Capital', 'Cauldron', 'Cavalry', 'Charm',
        'City', 'Collection', 'Council Room', 'Counterfeit', 'Courtier',
        'Ducat', "Farmers' Market", 'Farrier', 'Festival', 'Forager', 'Forum',
        'Grand Market', 'Hamlet', 'Herbalist', 'Margrave', 'Market',
        'Market Square', 'Merchant Guild', 'Messenger', 'Nomads', 'Pawn',
        'Peasant', 'Ranger', 'Salvager', 'Sanctuary', 'Scrap',
        'Silk Merchant', 'Snowy Village', 'Souk', 'Spice Merchant', 'Spices',
        'Squire', 'Stockpile', 'Storeroom', 'Tactician', 'Tiara', 'Villa',
        'Wharf', 'Wine Merchant', "Worker's Village"]
    assert cards.cards_granting("draw") == [
        'Alchemist', 'Apprentice', 'Barge', 'Black Cat', 'Catacombs',
        'Cavalry', 'Council Room', 'Courtyard', 'Cultist', 'Destrier',
        'Diplomat', 'Dungeon', 'Enchantress', 'Experiment', 'Ferryman',
        'Forum', 'Gear', 'Guard Dog', 'Haunted Woods', 'Hunting Grounds',
        'Hunting Lodge', 'Inn', 'Laboratory', 'Lackeys', 'Lost City',
        'Margrave', 'Masquerade', 'Menagerie', 'Minion', 'Moat', 'Nobles',
        'Old Witch', 'Patrol', 'Rabble', 'Ranger', 'Recruiter',
        'Royal Blacksmith', 'Sacrifice', 'Scholar', 'Sea Witch',
        'Secret Passage', 'Shanty Town', 'Sheepdog', 'Silk Merchant',
        'Smithy', 'Spice Merchant', 'Stables', 'Steward', 'Swashbuckler',
        'Tactician', 'Tide Pools', 'Torturer', 'Vault', 'Warehouse',
        'Wayfarer', 'Wharf', 'Wild Hunt', 'Witch', "Witch's Hut",
        'Young Witch']

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


def test_the_deferred_cards_are_recorded_and_still_absent():
    """A roster hole is DATA, not a comment. Alchemy published 12 kingdom
    cards; we ship 11 and record the twelfth here with its reason, so the set's
    published size still reconciles and the omission cannot be quietly
    forgotten. Build Possession -> delete its DEFERRED row -> this test tells
    you where the counts now disagree."""
    assert set(cards.DEFERRED) == {"Possession"}
    for name, why in cards.DEFERRED.items():
        assert name not in cards.CARDS, f"{name} is implemented — drop its DEFERRED row"
        assert len(why) > 80, f"{name} needs a real reason, not a shrug"
        assert ".claude-plans/" in why, f"{name} should point at where it is scoped"
    # Alchemy's published roster is 12 kingdom cards: what we ship + what we defer
    assert len(cards.KINGDOM["alchemy"]) + len(cards.DEFERRED) == 12
