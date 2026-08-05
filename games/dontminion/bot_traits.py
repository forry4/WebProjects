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

from .cards import CARDS, KINGDOM, KNIGHTS, RUINS, SHELTERS

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
    # Empires
    "Sacrifice": "tfb", "Catapult": "tfb", "Small Castle": "tfb",
    "Temple": "multi",
    # Cornucopia & Guilds
    "Butcher": "tfb", "Remake": "tfb", "Stonemason": "tfb",
    "Infirmary": "weak",
    # Alchemy
    "Apprentice": "tfb", "Transmute": "tfb",
    # Dark Ages — the trashing set. Rats is "weak" on purpose: it trashes one
    # card and hands you a Rats for it, so it thins nothing on net. Count's
    # "trash your hand" is deliberately ABSENT: it takes the good cards with
    # the bad, so a plan that reads it as a thinner would build on sand.
    "Altar": "tfb", "Counterfeit": "tfb", "Forager": "tfb",
    "Graverobber": "tfb", "Hermit": "tfb", "Junk Dealer": "tfb",
    "Procession": "tfb", "Rebuild": "tfb",
    "Death Cart": "weak", "Rats": "weak",
    "Mercenary": "multi",
    # Adventures. Transmogrify is the "tfb" one (trash a card, gain one costing
    # up to $1 more, into your hand); Amulet, Ratcatcher and Raze each trash a
    # single card. Bonfire and Trade are EVENTS, so they are not cards a bot
    # classifies here at all.
    "Transmogrify": "tfb",
    "Amulet": "weak", "Ratcatcher": "weak", "Raze": "weak",
    # Renaissance. Recruiter and Priest are the "tfb" ones — each converts a
    # trashed card into a scaling payoff (Villagers per $1; +$2 on every trash
    # for the rest of the turn). Hideout and Improve trash exactly one, and
    # Hideout's is a real cost on a Victory card (it hands you a Curse back).
    # Ducat is DELIBERATELY absent: its trash is a when-GAIN ability that fires
    # once, on one Copper, and a plan that read it as a thinner would be
    # counting a card it can only use the turn it buys it.
    "Recruiter": "tfb", "Priest": "tfb",
    "Hideout": "weak", "Improve": "weak",
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
    # Empires. Enchantress is its own kind: it neither junks nor empties a
    # hand, it REPLACES the victim's first Action each turn with a cantrip,
    # which is a tempo attack nothing else in the pool does. Only truthiness
    # and the `curse` test are read off this, so a new kind is safe.
    "Enchantress": "replace", "Legionary": "discard", "Catapult": "curse",
    # Cornucopia & Guilds. Jester is filed under "curse" for the DEFENSIVE
    # read that matters — on a Victory card it hands out a Curse, and the
    # alternative (a copy of what they discarded) is not reliably junk.
    "Young Witch": "curse", "Soothsayer": "curse", "Jester": "curse",
    "Footpad": "discard",
    # Alchemy. Scrying Pool is filed as "topdeck": it does not junk anyone,
    # it reorders what they draw (the attacker chooses discard-or-keep).
    "Familiar": "curse", "Scrying Pool": "topdeck",
    # Dark Ages. The RUINS-givers are filed under "curse": the kind drives the
    # defensive read ("am I about to be junked?"), and a Ruin is junk that
    # costs a card slot exactly like a Curse does — it just scores 0 instead
    # of -1. The Knights are "trash" (they eat a $3-$6 card off your deck);
    # Sir Michael also discards, and its harsher half is the trashing one.
    "Cultist": "curse", "Marauder": "curse",
    "Pillage": "discard", "Urchin": "discard", "Mercenary": "discard",
    "Rogue": "trash",
    "Dame Anna": "trash", "Dame Josephine": "trash", "Dame Molly": "trash",
    "Dame Natalie": "trash", "Dame Sylvia": "trash", "Sir Bailey": "trash",
    "Sir Destry": "trash", "Sir Martin": "trash", "Sir Michael": "trash",
    "Sir Vander": "trash",
    # Adventures. Bridge Troll and Relic hand out TOKENS rather than cards —
    # filed under "discard" and "topdeck" respectively for the defensive read
    # they actually produce (you get less this turn / you draw one fewer).
    # Giant is "trash" for its harsher half, though it also Curses.
    "Bridge Troll": "discard", "Relic": "topdeck",
    "Giant": "trash", "Warrior": "trash",
    "Swamp Hag": "curse", "Haunted Woods": "topdeck", "Soldier": "discard",
    # Renaissance. Only two Attacks in the set: Old Witch is a Witch that also
    # lets its victims un-junk (still a curser for the defensive read), and
    # Villain forces a $2+ discard, which is the Militia read.
    "Old Witch": "curse", "Villain": "discard",
}

# Cards that answer an Attack from hand (the reaction window / immunity).
# Adventures: Caravan Guard is the Guard Dog shape (it plays itself and grants
# no immunity), and Champion is unconditional immunity for the rest of the game.
DEFENSE = {"Moat", "Lighthouse", "Guard Dog", "Diplomat",
           "Caravan Guard", "Champion"}

# Gains a card from the supply without buying it.
GAINERS = {
    "Workshop", "Ironworks", "Artisan", "Smugglers", "Weaver", "Wheelwright",
    "Haggler", "Border Village", "Mint", "War Chest", "Anvil", "Tiara",
    "Berserker", "Develop", "Trader", "Remodel", "Upgrade", "Replace",
    # Adventures
    "Artificer", "Disciple", "Duplicate", "Hero", "Magpie", "Messenger",
    "Port", "Transmogrify", "Treasure Hunter", "Treasure Trove",
    # Empires
    "Engineer", "Charm", "Small Castle",
    "Expand", "Forge", "Farmland", "Bureaucrat", "Bandit", "Blockade",
    "Pirate", "Jack of All Trades", "Treasure Map", "Lurker", "Mine",
    # Cornucopia & Guilds
    "Butcher", "Remake", "Stonemason", "Horn of Plenty", "Soothsayer",
    "Demesne", "Courser",
    # Alchemy
    "University", "Transmute", "Apprentice",
    # Dark Ages
    "Altar", "Armory", "Bandit Camp", "Beggar", "Count", "Dame Natalie",
    "Graverobber", "Hermit", "Marauder", "Procession", "Rats", "Rebuild",
    "Rogue",
    # Renaissance. Inventor and Sculptor gain any pile up to $4 (Sculptor
    # straight to hand); Experiment gains a second copy of itself; Improve
    # remodels a card leaving play; Treasurer takes a Treasure out of the
    # TRASH, which is a gain by rule ("when-gain abilities will trigger").
    "Inventor", "Sculptor", "Experiment", "Improve", "Treasurer",
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
                "Haggler", "War Chest", "Anvil", "Tiara", "Smugglers",
                # Dark Ages: Armory and Hermit both gain a pile of your choice
                # every play without spending a card to do it (Hermit's trash
                # is optional) — the two Dark Ages cards a rush can be built
                # on. Altar is NOT one: its gain costs a card from your hand,
                # so the deck never grows, exactly like the remodel family.
                "Armory", "Hermit",
                # Empires: Engineer gains any pile up to $4 and can then trash
                # ITSELF for a second one, so the deck grows without spending a
                # card from hand — the Workshop shape, twice.
                "Engineer",
                # Renaissance: Inventor and Sculptor are both the Workshop
                # shape — any pile up to $4, every play, costing no card from
                # hand. Sculptor gains to HAND, which if anything makes it the
                # better rush engine. Improve is excluded (its gain costs the
                # Action leaving play), and so is Experiment (it only ever
                # drains its OWN pile — the Port/Magpie rule).
                "Inventor", "Sculptor"}
# Adventures adds NONE, deliberately. Every gainer it ships pays for the gain:
# Artificer discards a card per $1, Hero and Treasure Hunter give you Treasures
# rather than a pile of your choice, Duplicate needs a gain to copy, and Port
# and Magpie only ever drain their OWN pile. Counting one of those is how the
# Bureaucrat entry once fired a Gardens rush on a board with no rush.

# Looks at / discards / reorders cards to improve what you draw. The
# reshuffle-control rules (R4: "don't overcartograph") key on these.
SIFTERS = {
    # Empires: two cards that fish a known card out of the discard pile, one
    # that peeks at the top, and Archive, which parcels out a known three.
    "Settlers", "Bustling Village", "Patrician", "Archive",
    "Apothecary", "Golem",
    "Cellar", "Warehouse", "Cartographer", "Oasis", "Lookout", "Sentry",
    "Harbinger", "Vault", "Stables", "Inn", "Tide Pools", "Sea Chart",
    "Crystal Ball", "Jack of All Trades", "Patrol", "Library", "Scheme",
    "Native Village", "Haven", "Secret Passage", "Courtyard", "Wishing Well",
    # Dark Ages
    "Catacombs", "Ironmonger", "Mystic", "Sage", "Scavenger", "Storeroom",
    "Survivors", "Vagrant", "Wandering Minstrel",
    # Adventures: Dungeon and Fugitive both draw-then-discard, and a called
    # Guide replaces your whole hand. Gear is NOT one — it sets cards aside for
    # next turn rather than improving what you draw now.
    "Dungeon", "Fugitive", "Guide",
    # Renaissance. Border Guard and Seer both look at the top of the deck and
    # keep the useful ones; Mountain Village fishes a KNOWN card out of the
    # discard pile (the Hermit/Scavenger shape); Cargo Ship parks a gained
    # card in next turn's hand rather than in the discard pile.
    "Border Guard", "Seer", "Mountain Village", "Cargo Ship",
}

# Victory cards whose value is NOT a fixed number — the alt-VP article's
# subject. The value is the RULE, so a bot can price them per board.
ALT_VP = {
    "Gardens": "per_10_cards", "Duke": "per_duchy", "Farm": "treasure_vp",
    "Mill": "action_vp", "Nobles": "action_vp", "Island": "action_vp",
    "Tunnel": "reaction_vp", "Farmland": "on_gain_vp",
    "Fairgrounds": "per_5_distinct", "Demesne": "per_gold",
    "Vineyard": "per_3_actions",
    # Empires: the two Castles that count CASTLES (a type), including
    # themselves. The other six print a flat number and are ordinary Victory
    # cards that happen to share a pile.
    "Humble Castle": "per_castle", "King's Castle": "per_castle_x2",
    # Dark Ages. Dame Josephine is a flat 2 VP, so it is not an alt-VP card —
    # it is a Victory card that happens to live in the Knights pile.
    "Feodum": "per_3_silvers",
    # Adventures: the first VP that depends on WHERE the card is
    "Distant Lands": "on_tavern_mat_vp",
}

# Accumulates VP tokens — never lost, never clogs the deck (a slog's engine).
VP_TOKENS = {"Monument", "Bishop", "Collection", "Investment",
             # Empires is the VP-token set: three cards GATHER tokens on their
             # own pile and cash them out, three hand them straight to you.
             "Temple", "Wild Hunt", "Farmers' Market",
             "Chariot Race", "Plunder", "Groundskeeper", "Emporium"}

# Draws a variable number of cards, so it prints no "+N Cards" and the derived
# `draw` flag misses it entirely. Library is a top-tier drawer that a
# text-derived classifier cannot see — it was absent from the engine plan's
# draw pool for exactly this reason.
DRAW_TO_X = {"Library", "Watchtower", "Jack of All Trades", "Magnate",
             "Cellar", "Crossroads", "Shanty Town", "Minion", "Tactician",
             # Dark Ages: Catacombs takes 3 either way, Madman empties your
             # hand into a draw, Storeroom cycles as many as you discard, and
             # Sage/Mystic/Vagrant each fish exactly one card into hand
             "Catacombs", "Madman", "Storeroom", "Sage",
             # C&G: Advisor nets 2, Carnival up to 4, Journeyman exactly 3,
             # Housecarl scales with the table — none of them print "+N Cards"
             "Advisor", "Carnival", "Journeyman", "Housecarl",
             # Alchemy: Apprentice scales with what it trashed, Scrying Pool
             # with how many Actions sit on top of the deck
             "Apprentice", "Scrying Pool",
             # Adventures: a called Guide draws 5 whatever your hand was, and
             # Storyteller draws one card per $1 it takes off you — neither
             # prints a "+N Cards" a text scan could find
             "Guide", "Storyteller",
             # Empires: City Quarter draws one per Action in your hand, and
             # Archive parcels three cards out over three turns
             "City Quarter", "Archive",
             # Renaissance: Scholar discards its hand for a flat 7 (a real
             # drawer no "+N Cards" scan can see), Seer takes however many of
             # the top 3 are priced $2-$4, Research parcels out cards equal to
             # what it trashed, and Mountain Village nets exactly one either
             # way — from the discard pile if it can, off the deck if not
             "Scholar", "Seer", "Research", "Mountain Village"}

# Kingdom Treasures a money deck genuinely wants (the Terminal-Draw-BM
# article's list) vs the ones that are engine parts wearing a Treasure's
# clothes (Quarry discounts Actions BM never buys; Investment/War Chest/Crystal
# Ball push decisions a money deck gains nothing from).
BM_TREASURES = {"Fool's Gold", "Bank", "Hoard", "Farm", "Collection",
                "Astrolabe", "Cauldron", "Anvil", "Tiara",
                # Empires: Plunder is a Silver that also scores. Capital is
                # DELIBERATELY absent — $6 for $5 is the best rate in the game
                # and the 6 Debt it hands back locks your next buy entirely,
                # which this bot does not model; a money deck that cannot buy
                # is worse than one that bought a Gold.
                "Plunder",
                # Renaissance: Spices is a $2 Treasure with a +Buy and two
                # Coffers on the way in — strictly better than a Silver for a
                # money deck. Ducat and Scepter are NOT: Ducat prints $0
                # (its Coffers is one deferred coin) and Scepter's whole value
                # is replaying an Action a money deck never has.
                "Spices"}

# How good a card is as Big Money's ONE terminal, higher = better. Cards absent
# from this table are not BM terminals at all and `bm_terminal_rank` returns 0
# for them — which makes them INVISIBLE to the tier, so an omission is silent.
#
# MEASURED, not judged (tools/bm_terminal_sweep.py). Each card was played as
# bmplus's forced terminal against bmplus forced to buy NO terminal, on a board
# of inert filler so the candidate is the only Action worth having — i.e. the
# article's own question, "is this better than just buying money?". 25 CRN
# pairs each; the no-terminal control reads exactly 0.5000 on every board, so
# the values share a baseline. The rank IS the measured win rate x100, and a
# card measuring at or below 0.5 is simply absent.
#
# The hand-written table this replaced had real errors, in both directions:
#   Steward   rank 30 -> measured 0.36  (bought over a Silver, and LOSING)
#   Footpad   rank 62 -> measured 0.28  (the worst card in the sweep)
#   Moat      rank 20 -> measured 0.41
#   Vault     rank 58 -> measured 0.82  (badly underrated)
#   Patrol    rank 40 -> measured 0.77
#   Rabble    rank 78 -> measured 0.58  (overrated)
# and seven cards were missing entirely, including Masquerade — which the
# source article names as a Big Money opener.
#
# CAVEAT ON THE METHOD: this scores each card in ISOLATION against a common
# baseline, while the rank is used to choose BETWEEN cards on a board holding
# several. A shared baseline is a good proxy for that ordering, not a proof of
# it; re-run head-to-head if a specific pairing ever looks wrong.
BM_TERMINALS = {
    "Sea Witch": 94,
    "Witch": 90,
    # Dark Ages, measured at 300 games each (the sweep's default 50 left all
    # four of the non-Cultist ones inside the noise band). Every non-drawing
    # Dark Ages terminal was measured too and every one of them LOST badly —
    # Death Cart 0.008, Graverobber 0.025, Procession 0.058, Altar 0.171,
    # Poor House 0.179, Squire 0.192, Count/Armory 0.242, Hermit 0.350 — which
    # is the tier being honest about itself: they are engine parts, and this
    # bot buys no engine. Pillage (0.10) and Storeroom (0.05) are absent for
    # the same reason.
    "Cultist": 76,
    # Adventures, measured at 300 games each. Only six of the set's cards are
    # even shaped like a BM terminal (a terminal that draws, or a terminal
    # attack) and three of them earn their place. The other three are absent
    # and each is instructive: Ranger is a WASH (0.5333) because its +5 Cards
    # only arrives every other turn; Gear (0.4558) hands next turn's hand to
    # this turn's; and Bridge Troll (0.1983) is the set's clearest "engine part
    # wearing an attack's clothes" — a money deck buys nothing with the +1 Buy
    # and cannot use the cost reduction it isn't spending on Actions.
    "Swamp Hag": 91,
    "Giant": 78,
    "Haunted Woods": 76,
    # Empires, measured at 300 games each. Three earn their place, and the two
    # REJECTIONS are the set's real lesson: **a Debt cost is close to fatal for
    # a money deck.** Royal Blacksmith (0.0433) and City Quarter (0.0067) are
    # both {8D} and both score at the very bottom of every sweep this repo has
    # run — worse than Death Cart — because taking 8 Debt blocks the tier from
    # buying ANYTHING until it has paid $8 it would otherwise have spent on
    # Gold. The card is fine; the price is a whole turn of buying. Sacrifice
    # (0.5467) is a wash and is absent for the usual reason.
    # The five split piles and Castles are not candidates at all — an ordered
    # pile's face changes, so it is nobody's reliable terminal (ph. 3H).
    "Forum": 70,
    "Legionary": 65,
    "Wild Hunt": 64,
    # Renaissance, measured at 300 games each. **Old Witch (0.9125) is the
    # strongest card this sweep has ever measured** — a Witch that also lets
    # its victims un-junk still beats every other terminal in the roster,
    # because against a money deck the Curses are what matter and the
    # may-trash rarely fires. The four REJECTIONS are the set's lesson, and
    # they all fail the same way: **Coffers and Villagers are DEFERRED value
    # a money deck never collects.** Villain (0.1033) is the worst card in
    # any sweep here, below even Footpad — its +2 Coffers is money next turn
    # and its discard attack barely dents a deck of Treasures. Priest
    # (0.3733) needs a trashing deck it hasn't got, Recruiter (0.4200) pays
    # in Villagers this tier cannot spend (it holds one terminal), and Patron
    # (0.4475) is a Reaction on an event a money deck never causes. Scholar
    # (0.5342) and Seer (0.5150) are washes and absent for the usual reason.
    "Old Witch": 91,
    "Swashbuckler": 63,
    "Lackeys": 57,
    "Silk Merchant": 56,
    "Wharf": 87,
    "Vault": 82,
    "Charlatan": 81,
    "Young Witch": 80,
    "Corsair": 80,
    "Soothsayer": 79,
    "Torturer": 78,
    "Patrol": 77,
    "Witch's Hut": 76,
    "Blockade": 72,
    "Margrave": 71,
    "Clerk": 71,
    "Cutpurse": 70,
    "Jester": 68,
    "Rogue": 62,
    "Marauder": 62,
    "Hunting Grounds": 61,
    "Smithy": 65,
    "Militia": 65,
    "Masquerade": 65,
    "Jack of All Trades": 65,
    "Bandit": 64,
    "Council Room": 63,
    "Carnival": 63,
    "Catacombs": 58,
    "Rabble": 58,
    "Magnate": 58,
    "Berserker": 57,
    "Library": 55,
    "Journeyman": 55,
    "Courtyard": 55,
}
# Every kingdom card that has been reviewed against the tables above. A set
# lands => its 25-30 names land here => the test goes green again.
#
# A kingdom list may hold a PILE NAME that is not a card (Dark Ages' Knights),
# and the cards a bot actually meets are that pile's MEMBERS — plus the Ruins,
# the Shelters it starts with, and the non-Supply cards it can be handed. All
# of those are classified above, so all of them belong here; the pile name
# itself does not (traits() is a function of a card, and the bots reach a pile
# through pile_traits).
# IT IS AN EXPLICIT LIST, AND IT HAS TO BE. Phase 6 rebuilt this as a
# comprehension over KINGDOM — which is exactly what the test compares it
# against, so `every - REVIEWED` was empty by construction and the guard could
# never fail. Dark Ages passed it while 55 unreviewed cards shipped. Reviewing a
# card is a HUMAN act; the record of it therefore has to be data, not a
# derivation of the thing it is meant to check.
REVIEWED = frozenset([
    "Abandoned Mine", "Advisor", "Alchemist", "Altar", "Anvil", "Apothecary",
    "Apprentice", "Armory", "Artisan", "Astrolabe", "Baker",
    "Band of Misfits", "Bandit", "Bandit Camp", "Bank", "Baron", "Bazaar",
    "Beggar", "Berserker", "Bishop", "Blockade", "Border Village", "Bridge",
    "Bureaucrat", "Butcher", "Candlestick Maker", "Caravan", "Carnival",
    "Cartographer", "Catacombs", "Cauldron", "Cellar", "Chapel", "Charlatan",
    "City", "Clerk", "Collection", "Conspirator", "Corsair", "Council Room",
    "Count", "Counterfeit", "Courtier", "Courtyard", "Crossroads",
    "Crystal Ball", "Cultist", "Cutpurse", "Dame Anna", "Dame Josephine",
    "Dame Molly", "Dame Natalie", "Dame Sylvia", "Death Cart", "Develop",
    "Diplomat", "Duke", "Expand", "Fairgrounds", "Familiar", "Farm",
    "Farmhands", "Farmland", "Farrier", "Feodum", "Ferryman", "Festival",
    "Fishing Village", "Fool's Gold", "Footpad", "Forager", "Forge",
    "Fortress", "Gardens", "Golem", "Grand Market", "Graverobber",
    "Guard Dog", "Haggler", "Hamlet", "Harbinger", "Haven", "Herald",
    "Herbalist", "Hermit", "Highway", "Hoard", "Horn of Plenty", "Hovel",
    "Hunting Grounds", "Hunting Party", "Infirmary", "Inn", "Investment",
    "Ironmonger", "Ironworks", "Island", "Jack of All Trades", "Jester",
    "Journeyman", "Joust", "Junk Dealer", "King's Court", "Laboratory",
    "Library", "Lighthouse", "Lookout", "Lurker", "Madman", "Magnate",
    "Marauder", "Margrave", "Market", "Market Square", "Masquerade",
    "Menagerie", "Mercenary", "Merchant", "Merchant Guild", "Merchant Ship",
    "Militia", "Mill", "Mine", "Mining Village", "Minion", "Mint", "Moat",
    "Moneylender", "Monkey", "Monument", "Mystic", "Native Village",
    "Necropolis", "Nobles", "Nomads", "Oasis", "Outpost", "Overgrown Estate",
    "Patrol", "Pawn", "Peddler", "Philosopher's Stone", "Pillage", "Pirate",
    "Plaza", "Poacher", "Poor House", "Procession", "Quarry", "Rabble",
    "Rats", "Rebuild", "Remake", "Remodel", "Replace", "Rogue",
    "Ruined Library", "Ruined Market", "Ruined Village", "Sage", "Sailor",
    "Salvager", "Scavenger", "Scheme", "Scrying Pool", "Sea Chart",
    "Sea Witch", "Secret Passage", "Sentry", "Shanty Town", "Shop",
    "Sir Bailey", "Sir Destry", "Sir Martin", "Sir Michael", "Sir Vander",
    "Smithy", "Smugglers", "Soothsayer", "Souk", "Spice Merchant", "Spoils",
    "Squire", "Stables", "Steward", "Stonemason", "Storeroom", "Survivors",
    "Swindler", "Tactician", "Throne Room", "Tiara", "Tide Pools",
    "Torturer", "Trader", "Trading Post", "Trail", "Transmute",
    "Treasure Map", "Treasury", "Tunnel", "University", "Upgrade", "Urchin",
    "Vagrant", "Vassal", "Vault", "Village", "Vineyard",
    "Wandering Minstrel", "War Chest", "Warehouse", "Watchtower", "Weaver",
    "Wharf", "Wheelwright", "Wishing Well", "Witch", "Witch's Hut",
    "Worker's Village", "Workshop", "Young Witch",
    # --- Adventures (ph. 7) ---
    "Amulet", "Artificer", "Bridge Troll", "Caravan Guard", "Champion",
    "Coin of the Realm", "Disciple", "Distant Lands", "Dungeon", "Duplicate",
    "Fugitive", "Gear", "Giant", "Guide", "Haunted Woods", "Hero",
    "Hireling", "Lost City", "Magpie", "Messenger", "Miser", "Page",
    "Peasant", "Port", "Ranger", "Ratcatcher", "Raze", "Relic",
    "Royal Carriage", "Soldier", "Storyteller", "Swamp Hag", "Teacher",
    "Transmogrify", "Treasure Hunter", "Treasure Trove", "Warrior",
    "Wine Merchant",
    # --- Empires (ph. 8) — the 18 ordinary kingdom cards... ---
    "Archive", "Capital", "Charm", "Chariot Race", "City Quarter", "Crown",
    "Enchantress", "Engineer", "Farmers' Market", "Forum", "Groundskeeper",
    "Legionary", "Overlord", "Royal Blacksmith", "Sacrifice", "Temple",
    "Villa", "Wild Hunt",
    # ...the ten split-pile halves (a bot meets BOTH halves of a pile, so both
    # owe a review even though only the pile is dealt)...
    "Bustling Village", "Catapult", "Emporium", "Encampment", "Fortune",
    "Gladiator", "Patrician", "Plunder", "Rocks", "Settlers",
    # ...and the eight Castles.
    "Crumbling Castle", "Grand Castle", "Haunted Castle", "Humble Castle",
    "King's Castle", "Opulent Castle", "Small Castle", "Sprawling Castle",
    # --- Renaissance (ph. 9) — all 25 are ordinary kingdom piles; the 20
    # Projects are landscapes and the 5 Artifacts are neither, so neither
    # kind reaches traits() at all.
    "Acting Troupe", "Border Guard", "Cargo Ship", "Ducat", "Experiment",
    "Flag Bearer", "Hideout", "Improve", "Inventor", "Lackeys",
    "Mountain Village", "Old Witch", "Patron", "Priest", "Recruiter",
    "Research", "Scepter", "Scholar", "Sculptor", "Seer", "Silk Merchant",
    "Spices", "Swashbuckler", "Treasurer", "Villain",
])


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


def best_bm_terminal(kingdom, supply=None, table=None):
    """The kingdom's best Big-Money terminal, or None if it has none.

    `supply` (optional) skips piles that are already empty. `table` overrides
    the ranking — the harness seam for scoring one ranking against another.
    """
    ranks = BM_TERMINALS if table is None else table
    best, score = None, 0
    for n in kingdom:
        if n not in CARDS:
            # an ORDERED pile: what it offers changes as it empties, so it is
            # nobody's reliable terminal — and the deck-count rules below
            # ("the second Smithy at ~16 cards") can't count copies of a pile
            continue
        r = ranks.get(n, 0)
        if r > score and (supply is None or supply.get(n, 0) > 0):
            best, score = n, r
    return best
