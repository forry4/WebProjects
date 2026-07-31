"""Dontminion static card data (Dominion Base 2E + Intrigue 2E) — the full 59-card dataset.

Verified against the Knutsen compendium (Dominion_CompleteRules_v11.1.pdf: ch. V editions/
errata p37-38 + ch. VII Card Reference) and the dominionstrategy.com card-list pages for
Base 2E and Intrigue 2E (see .claude-plans/i-want-to-add-luminous-pebble.md par.2/par.5/par.9).
Texts are the CURRENT card versions: ch. V lists Masquerade, Mine, Moneylender and Throne Room
as functionally changed post-2016; their entries' "Current (2016) version" notes are reflected
here.

NAMES ARE THE CURRENT ONES (user directive: "the most updated names and rules"). Intrigue's
"Harem" ships as **Farm** — compendium: "Harem ❖ In 2023 this card was renamed 'Farm'". An
earlier phase logged the rename as trivia and kept the old name; that was wrong. A rename is
NOT cosmetic here: the string lives inside live prod decks/supplies/trash, so every rename
owes a `_RENAMES` entry + SCHEMA bump in engine.py, which rewrites persisted saves on load.

Schema (frozen contract — see plan par.9):
  CARDS[name] = {
    "cost": int,
    "types": [str, ...],          # lowercase: action/treasure/victory/curse/attack/reaction
    "coins": int,                 # treasure coin value (0 for non-treasures)
    "vp": int | str,              # static VP; "gardens"/"duke" for the computed rules
    "text": str,                  # current (2E) official wording, "\n"-separated lines
    "expansion": str,             # "basic" | "base" | "intrigue"
    "kingdom": bool,
  }
  KINGDOM = {"base": [...26 names...], "intrigue": [...26 names...]}
  pile_size(name, n_players) -> int
  DATA_COMPLETE: bool — True only when all 59 cards are present and verified.
"""

DATA_COMPLETE = True

# Bandit ruling (VERIFIED): when an attacked player's two revealed cards are both
# non-Copper Treasures, the ATTACKED player chooses which one is trashed — the card
# instructs "each other player ... trashes a revealed Treasure other than Copper",
# so the trash (and its choice) is that player's own instruction. Compendium v11.1:
# Bandit entry (Card Reference p61-62) defers to EACH OTHER PLAYER / "TRIGGERED
# ABILITY (each opponent first trashes, then discards)"; Common effects "Each
# player/Each other player" (p48) lists Bandit among the each-other-player effects
# "that involve choices"; and ch. III Advanced timing rules: Grouping of effects
# (p24) — "Some abilities (e.g. Bandit) say 'each (other) player...'. Resolve all
# the effects for the first player (including any choices by you or the player),
# then all the effects for the next player, etc., in turn order." Bandit's only
# choice point is the affected player's trash pick (contrast Swindler, whose text
# explicitly assigns its gain choice to the attacker: "that you choose").
BANDIT_VICTIM_CHOOSES = True

CARDS = {
    # --- basic supply -------------------------------------------------------
    "Copper":   {"cost": 0, "types": ["treasure"], "coins": 1, "vp": 0,
                 "text": "$1", "expansion": "basic", "kingdom": False},
    "Silver":   {"cost": 3, "types": ["treasure"], "coins": 2, "vp": 0,
                 "text": "$2", "expansion": "basic", "kingdom": False},
    "Gold":     {"cost": 6, "types": ["treasure"], "coins": 3, "vp": 0,
                 "text": "$3", "expansion": "basic", "kingdom": False},
    "Estate":   {"cost": 2, "types": ["victory"], "coins": 0, "vp": 1,
                 "text": "1 VP", "expansion": "basic", "kingdom": False},
    "Duchy":    {"cost": 5, "types": ["victory"], "coins": 0, "vp": 3,
                 "text": "3 VP", "expansion": "basic", "kingdom": False},
    "Province": {"cost": 8, "types": ["victory"], "coins": 0, "vp": 6,
                 "text": "6 VP", "expansion": "basic", "kingdom": False},
    "Curse":    {"cost": 0, "types": ["curse"], "coins": 0, "vp": -1,
                 "text": "-1 VP", "expansion": "basic", "kingdom": False},

    # --- Base Set kingdom (2E, 26) -----------------------------------------
    "Cellar":   {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Action\nDiscard any number of cards.\n"
                         "+1 Card per card discarded.",
                 "expansion": "base", "kingdom": True},
    "Chapel":   {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "Trash up to 4 cards from your hand.",
                 "expansion": "base", "kingdom": True},
    "Moat":     {"cost": 2, "types": ["action", "reaction"], "coins": 0, "vp": 0,
                 "text": "+2 Cards\nWhen another player plays an Attack card, you may first "
                         "reveal this from your hand, to be unaffected by it.",
                 "expansion": "base", "kingdom": True},
    "Harbinger": {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Card\n+1 Action\nLook through your discard pile. You may put a "
                         "card from it onto your deck.",
                 "expansion": "base", "kingdom": True},
    "Merchant": {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Card\n+1 Action\nThe first time you play a Silver this turn, +$1.",
                 "expansion": "base", "kingdom": True},
    "Vassal":   {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+$2\nDiscard the top card of your deck. If it's an Action card, "
                         "you may play it.",
                 "expansion": "base", "kingdom": True},
    "Village":  {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Card\n+2 Actions", "expansion": "base", "kingdom": True},
    "Workshop": {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "Gain a card costing up to $4.",
                 "expansion": "base", "kingdom": True},
    "Bureaucrat": {"cost": 4, "types": ["action", "attack"], "coins": 0, "vp": 0,
                 "text": "Gain a Silver onto your deck. Each other player reveals a Victory "
                         "card from their hand and puts it onto their deck (or reveals a hand "
                         "with no Victory cards).",
                 "expansion": "base", "kingdom": True},
    "Gardens":  {"cost": 4, "types": ["victory"], "coins": 0, "vp": "gardens",
                 "text": "Worth 1 VP per 10 cards you have (round down).",
                 "expansion": "base", "kingdom": True},
    "Militia":  {"cost": 4, "types": ["action", "attack"], "coins": 0, "vp": 0,
                 "text": "+$2\nEach other player discards down to 3 cards in hand.",
                 "expansion": "base", "kingdom": True},
    "Moneylender": {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "You may trash a Copper from your hand for +$3.",
                 "expansion": "base", "kingdom": True},
    "Poacher":  {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Card\n+1 Action\n+$1\nDiscard a card per empty Supply pile.",
                 "expansion": "base", "kingdom": True},
    "Remodel":  {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "Trash a card from your hand. Gain a card costing up to $2 more "
                         "than it.",
                 "expansion": "base", "kingdom": True},
    "Smithy":   {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+3 Cards", "expansion": "base", "kingdom": True},
    "Throne Room": {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "You may play an Action card from your hand twice.",
                 "expansion": "base", "kingdom": True},
    "Bandit":   {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                 "text": "Gain a Gold. Each other player reveals the top 2 cards of their "
                         "deck, trashes a revealed Treasure other than Copper, and discards "
                         "the rest.",
                 "expansion": "base", "kingdom": True},
    "Council Room": {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+4 Cards\n+1 Buy\nEach other player draws a card.",
                 "expansion": "base", "kingdom": True},
    "Festival": {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+2 Actions\n+1 Buy\n+$2", "expansion": "base", "kingdom": True},
    "Laboratory": {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+2 Cards\n+1 Action", "expansion": "base", "kingdom": True},
    "Library":  {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "Draw until you have 7 cards in hand, skipping any Action cards "
                         "you choose to; set those aside, discarding them afterwards.",
                 "expansion": "base", "kingdom": True},
    "Market":   {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Card\n+1 Action\n+1 Buy\n+$1",
                 "expansion": "base", "kingdom": True},
    "Mine":     {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "You may trash a Treasure from your hand. Gain a Treasure to your "
                         "hand costing up to $3 more than it.",
                 "expansion": "base", "kingdom": True},
    "Sentry":   {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Card\n+1 Action\nLook at the top 2 cards of your deck. Trash "
                         "and/or discard any number of them. Put the rest back on top in "
                         "any order.",
                 "expansion": "base", "kingdom": True},
    "Witch":    {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                 "text": "+2 Cards\nEach other player gains a Curse.",
                 "expansion": "base", "kingdom": True},
    "Artisan":  {"cost": 6, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "Gain a card to your hand costing up to $5.\nPut a card from your "
                         "hand onto your deck.",
                 "expansion": "base", "kingdom": True},

    # --- Intrigue kingdom (2E, 26) -----------------------------------------
    "Courtyard": {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+3 Cards\nPut a card from your hand onto your deck.",
                 "expansion": "intrigue", "kingdom": True},
    "Lurker":   {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Action\nChoose one: Trash an Action card from the Supply; or "
                         "gain an Action card from the trash.",
                 "expansion": "intrigue", "kingdom": True},
    "Pawn":     {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "Choose two: +1 Card; +1 Action; +1 Buy; +$1. The choices must "
                         "be different.",
                 "expansion": "intrigue", "kingdom": True},
    "Masquerade": {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+2 Cards\nEach player with any cards in hand passes one to the "
                         "next such player to their left, at once. Then you may trash a "
                         "card from your hand.",
                 "expansion": "intrigue", "kingdom": True},
    "Shanty Town": {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+2 Actions\nReveal your hand.\nIf you have no Action cards in "
                         "hand, +2 Cards.",
                 "expansion": "intrigue", "kingdom": True},
    "Steward":  {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "Choose one: +2 Cards; or +$2; or trash 2 cards from your hand.",
                 "expansion": "intrigue", "kingdom": True},
    "Swindler": {"cost": 3, "types": ["action", "attack"], "coins": 0, "vp": 0,
                 "text": "+$2\nEach other player trashes the top card of their deck and "
                         "gains a card with the same cost that you choose.",
                 "expansion": "intrigue", "kingdom": True},
    "Wishing Well": {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Card\n+1 Action\nName a card, then reveal the top card of "
                         "your deck. If you named it, put it into your hand.",
                 "expansion": "intrigue", "kingdom": True},
    "Baron":    {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Buy\nYou may discard an Estate, for +$4. If you don't, gain "
                         "an Estate.",
                 "expansion": "intrigue", "kingdom": True},
    "Bridge":   {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Buy\n+$1\nThis turn, cards (everywhere) cost $1 less, but not "
                         "less than $0.",
                 "expansion": "intrigue", "kingdom": True},
    "Conspirator": {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+$2\nIf you've played 3 or more Actions this turn (counting "
                         "this), +1 Card and +1 Action.",
                 "expansion": "intrigue", "kingdom": True},
    "Diplomat": {"cost": 4, "types": ["action", "reaction"], "coins": 0, "vp": 0,
                 "text": "+2 Cards\nIf you have 5 or fewer cards in hand (after drawing), "
                         "+2 Actions.\nWhen another player plays an Attack card, you may "
                         "first reveal this from a hand of 5 or more cards, to draw 2 "
                         "cards then discard 3.",
                 "expansion": "intrigue", "kingdom": True},
    "Ironworks": {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "Gain a card costing up to $4.\nIf the gained card is an...\n"
                         "Action card, +1 Action\nTreasure card, +$1\nVictory card, +1 Card",
                 "expansion": "intrigue", "kingdom": True},
    "Mill":     {"cost": 4, "types": ["action", "victory"], "coins": 0, "vp": 1,
                 "text": "+1 Card\n+1 Action\nYou may discard 2 cards, for +$2.\n1 VP",
                 "expansion": "intrigue", "kingdom": True},
    "Mining Village": {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Card\n+2 Actions\nYou may trash this, for +$2.",
                 "expansion": "intrigue", "kingdom": True},
    "Secret Passage": {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+2 Cards\n+1 Action\nTake a card from your hand and put it "
                         "anywhere in your deck.",
                 "expansion": "intrigue", "kingdom": True},
    "Courtier": {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "Reveal a card from your hand. For each type it has (Action, "
                         "Attack, etc.), choose one: +1 Action; or +1 Buy; or +$3; or gain "
                         "a Gold. The choices must be different.",
                 "expansion": "intrigue", "kingdom": True},
    "Duke":     {"cost": 5, "types": ["victory"], "coins": 0, "vp": "duke",
                 "text": "Worth 1 VP per Duchy you have.",
                 "expansion": "intrigue", "kingdom": True},
    "Minion":   {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                 "text": "+1 Action\nChoose one: +$2; or discard your hand, +4 Cards, and "
                         "each other player with at least 5 cards in hand discards their "
                         "hand and draws 4 cards.",
                 "expansion": "intrigue", "kingdom": True},
    "Patrol":   {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+3 Cards\nReveal the top 4 cards of your deck. Put the Victory "
                         "cards and Curses into your hand. Put the rest back in any order.",
                 "expansion": "intrigue", "kingdom": True},
    "Replace":  {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                 "text": "Trash a card from your hand. Gain a card costing up to $2 more "
                         "than it. If the gained card is an Action or Treasure, put it "
                         "onto your deck; if it's a Victory card, each other player gains "
                         "a Curse.",
                 "expansion": "intrigue", "kingdom": True},
    "Torturer": {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                 "text": "+3 Cards\nEach other player either discards 2 cards or gains a "
                         "Curse to their hand, their choice. (They may pick an option they "
                         "can't do.)",
                 "expansion": "intrigue", "kingdom": True},
    "Trading Post": {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "Trash 2 cards from your hand. If you did, gain a Silver to your "
                         "hand.",
                 "expansion": "intrigue", "kingdom": True},
    "Upgrade":  {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Card\n+1 Action\nTrash a card from your hand. Gain a card "
                         "costing exactly $1 more than it.",
                 "expansion": "intrigue", "kingdom": True},
    # renamed from "Harem" in 2023 — see the module docstring and engine._RENAMES
    "Farm":     {"cost": 6, "types": ["treasure", "victory"], "coins": 2, "vp": 2,
                 "text": "$2\n2 VP", "expansion": "intrigue", "kingdom": True},
    "Nobles":   {"cost": 6, "types": ["action", "victory"], "coins": 0, "vp": 2,
                 "text": "Choose one: +3 Cards; or +2 Actions.\n2 VP",
                 "expansion": "intrigue", "kingdom": True},
}

CARDS.update({
    # --- Prosperity kingdom (2E, 25) + Platinum/Colony — spec: scratchpad
    # prosperity-spec.md, verified against compendium ch. VII (current texts) ---
    "Platinum": {"cost": 9, "types": ["treasure"], "coins": 5, "vp": 0,
                 "text": "$5", "expansion": "prosperity", "kingdom": False},
    "Colony": {"cost": 11, "types": ["victory"], "coins": 0, "vp": 10,
               "text": "10 VP", "expansion": "prosperity", "kingdom": False},
    "Anvil": {"cost": 3, "types": ["treasure"], "coins": 1, "vp": 0,
              "text": "$1\nYou may discard a Treasure to gain a card costing up to $4.",
              "expansion": "prosperity", "kingdom": True},
    "Bank": {"cost": 7, "types": ["treasure"], "coins": 0, "vp": 0,
             "text": "+$1 per Treasure card you have in play (counting this).",
             "expansion": "prosperity", "kingdom": True},
    "Bishop": {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
               "text": "+$1\n+1 VP\nTrash a card from your hand. +1 VP per $2 it costs (round down).\nEach other player may trash a card from their hand.",
               "expansion": "prosperity", "kingdom": True},
    "Charlatan": {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                  "text": "+$3\nEach other player gains a Curse.\nIn games using this, Curse is also a Treasure worth $1.",
                  "expansion": "prosperity", "kingdom": True},
    "City": {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
             "text": "+1 Card\n+2 Actions\nIf there are one or more empty Supply piles, +1 Card. If there are two or more, +1 Buy and +$1.",
             "expansion": "prosperity", "kingdom": True},
    "Clerk": {"cost": 4, "types": ["action", "reaction", "attack"], "coins": 0, "vp": 0,
              "text": "+$2\nEach other player with 5 or more cards in hand puts one onto their deck.\nAt the start of your turn, you may play this from your hand.",
              "expansion": "prosperity", "kingdom": True},
    "Collection": {"cost": 5, "types": ["treasure"], "coins": 2, "vp": 0,
                   "text": "$2\n+1 Buy\nThis turn, when you gain an Action card, +1 VP.",
                   "expansion": "prosperity", "kingdom": True},
    "Crystal Ball": {"cost": 5, "types": ["treasure"], "coins": 1, "vp": 0,
                     "text": "$1\nLook at the top card of your deck. You may trash it, discard it, or, if it's an Action or Treasure, play it.",
                     "expansion": "prosperity", "kingdom": True},
    "Expand": {"cost": 7, "types": ["action"], "coins": 0, "vp": 0,
               "text": "Trash a card from your hand. Gain a card costing up to $3 more than it.",
               "expansion": "prosperity", "kingdom": True},
    "Forge": {"cost": 7, "types": ["action"], "coins": 0, "vp": 0,
              "text": "Trash any number of cards from your hand. Gain a card with cost exactly equal to the total cost in $ of the trashed cards.",
              "expansion": "prosperity", "kingdom": True},
    "Grand Market": {"cost": 6, "types": ["action"], "coins": 0, "vp": 0,
                     "text": "+1 Card\n+1 Action\n+1 Buy\n+$2\nYou can't buy this if you have any Coppers in play.",
                     "expansion": "prosperity", "kingdom": True},
    "Hoard": {"cost": 6, "types": ["treasure"], "coins": 2, "vp": 0,
              "text": "$2\nThis turn, when you gain a Victory card, if you bought it, gain a Gold.",
              "expansion": "prosperity", "kingdom": True},
    "Investment": {"cost": 4, "types": ["treasure"], "coins": 0, "vp": 0,
                   "text": "Trash a card from your hand.\nChoose one: +$1; or trash this to reveal your hand for +1 VP per differently named Treasure there.",
                   "expansion": "prosperity", "kingdom": True},
    "King's Court": {"cost": 7, "types": ["action"], "coins": 0, "vp": 0,
                     "text": "You may play an Action card from your hand three times.",
                     "expansion": "prosperity", "kingdom": True},
    "Magnate": {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                "text": "Reveal your hand. +1 Card per Treasure in it.",
                "expansion": "prosperity", "kingdom": True},
    "Mint": {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
             "text": "You may reveal a Treasure card from your hand. Gain a copy of it.\nWhen you gain this, trash all non-Duration Treasures you have in play.",
             "expansion": "prosperity", "kingdom": True},
    "Monument": {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+$2\n+1 VP", "expansion": "prosperity", "kingdom": True},
    "Peddler": {"cost": 8, "types": ["action"], "coins": 0, "vp": 0,
                "text": "+1 Card\n+1 Action\n+$1\nDuring a player's Buy phase, this costs $2 less per Action card they have in play.",
                "expansion": "prosperity", "kingdom": True},
    "Quarry": {"cost": 4, "types": ["treasure"], "coins": 1, "vp": 0,
               "text": "$1\nThis turn, Actions cost $2 less.",
               "expansion": "prosperity", "kingdom": True},
    "Rabble": {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
               "text": "+3 Cards\nEach other player reveals the top 3 cards of their deck, discards the Actions and Treasures, and puts the rest back in any order they choose.",
               "expansion": "prosperity", "kingdom": True},
    "Tiara": {"cost": 4, "types": ["treasure"], "coins": 0, "vp": 0,
              "text": "+1 Buy\nThis turn, when you gain a card, you may put it onto your deck.\nYou may play a Treasure from your hand twice.",
              "expansion": "prosperity", "kingdom": True},
    "Vault": {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
              "text": "+2 Cards\nDiscard any number of cards for +$1 each.\nEach other player may discard 2 cards, to draw a card.",
              "expansion": "prosperity", "kingdom": True},
    "War Chest": {"cost": 5, "types": ["treasure"], "coins": 0, "vp": 0,
                  "text": "The player to your left names a card. Gain a card costing up to $5 that hasn't been named for War Chests this turn.",
                  "expansion": "prosperity", "kingdom": True},
    "Watchtower": {"cost": 3, "types": ["action", "reaction"], "coins": 0, "vp": 0,
                   "text": "Draw until you have 6 cards in hand.\nWhen you gain a card, you may reveal this from your hand, to either trash that card or put it onto your deck.",
                   "expansion": "prosperity", "kingdom": True},
    "Worker's Village": {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "+1 Card\n+2 Actions\n+1 Buy",
                         "expansion": "prosperity", "kingdom": True},
})

CARDS.update({
    # --- Seaside kingdom (2E, 27) — spec: scratchpad seaside-spec.md, verified
    # against compendium ch. VII (current texts) + dominionstrategy card list ---
    "Astrolabe": {"cost": 3, "types": ["treasure", "duration"], "coins": 1, "vp": 0,
                  "text": "Now and at the start of your next turn:\n$1 and +1 Buy.",
                  "expansion": "seaside", "kingdom": True},
    "Bazaar": {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
               "text": "+1 Card\n+2 Actions\n+$1", "expansion": "seaside", "kingdom": True},
    "Blockade": {"cost": 4, "types": ["action", "duration", "attack"], "coins": 0, "vp": 0,
                 "text": "Gain a card costing up to $4, setting it aside.\nAt the start of your next turn, put it into your hand. While it's set aside, when another player gains a copy of it on their turn, they gain a Curse.",
                 "expansion": "seaside", "kingdom": True},
    "Caravan": {"cost": 4, "types": ["action", "duration"], "coins": 0, "vp": 0,
                "text": "+1 Card\n+1 Action\nAt the start of your next turn, +1 Card.",
                "expansion": "seaside", "kingdom": True},
    "Corsair": {"cost": 5, "types": ["action", "duration", "attack"], "coins": 0, "vp": 0,
                "text": "+$2\nAt the start of your next turn, +1 Card. Until then, each other player trashes the first Silver or Gold they play each turn.",
                "expansion": "seaside", "kingdom": True},
    "Cutpurse": {"cost": 4, "types": ["action", "attack"], "coins": 0, "vp": 0,
                 "text": "+$2\nEach other player discards a Copper (or reveals a hand with no Copper).",
                 "expansion": "seaside", "kingdom": True},
    "Fishing Village": {"cost": 3, "types": ["action", "duration"], "coins": 0, "vp": 0,
                        "text": "+2 Actions\n+$1\nAt the start of your next turn:\n+1 Action and +$1.",
                        "expansion": "seaside", "kingdom": True},
    "Haven": {"cost": 2, "types": ["action", "duration"], "coins": 0, "vp": 0,
              "text": "+1 Card\n+1 Action\nSet aside a card from your hand face down (under this). At the start of your next turn, put it into your hand.",
              "expansion": "seaside", "kingdom": True},
    "Island": {"cost": 4, "types": ["action", "victory"], "coins": 0, "vp": 2,
               "text": "Put this and a card from your hand onto your Island mat.\n2 VP",
               "expansion": "seaside", "kingdom": True},
    "Lighthouse": {"cost": 2, "types": ["action", "duration"], "coins": 0, "vp": 0,
                   "text": "+1 Action\n+$1\nAt the start of your next turn: +$1. Until then, when another player plays an Attack card, it doesn't affect you.",
                   "expansion": "seaside", "kingdom": True},
    "Lookout": {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                "text": "+1 Action\nLook at the top 3 cards of your deck. Trash one of them. Discard one of them. Put the other one back on top of your deck.",
                "expansion": "seaside", "kingdom": True},
    "Merchant Ship": {"cost": 5, "types": ["action", "duration"], "coins": 0, "vp": 0,
                      "text": "Now and at the start of your next turn: +$2.",
                      "expansion": "seaside", "kingdom": True},
    "Monkey": {"cost": 3, "types": ["action", "duration"], "coins": 0, "vp": 0,
               "text": "Until your next turn, when the player to your right gains a card, +1 Card.\nAt the start of your next turn, +1 Card.",
               "expansion": "seaside", "kingdom": True},
    "Native Village": {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                       "text": "+2 Actions\nChoose one: Put the top card of your deck face down on your Native Village mat (you may look at those cards at any time); or put all the cards from your mat into your hand.",
                       "expansion": "seaside", "kingdom": True},
    "Outpost": {"cost": 5, "types": ["action", "duration"], "coins": 0, "vp": 0,
                "text": "You only draw 3 cards for your next hand.\nTake an extra turn after this one (but not a 3rd turn in a row).",
                "expansion": "seaside", "kingdom": True},
    "Pirate": {"cost": 5, "types": ["action", "duration", "reaction"], "coins": 0, "vp": 0,
               "text": "At the start of your next turn, gain a Treasure costing up to $6 to your hand.\nWhen any player gains a Treasure, you may play this from your hand.",
               "expansion": "seaside", "kingdom": True},
    "Sailor": {"cost": 4, "types": ["action", "duration"], "coins": 0, "vp": 0,
               "text": "+1 Action\nOnce this turn, when you gain a Duration card, you may play it.\nAt the start of your next turn, +$2 and you may trash a card from your hand.",
               "expansion": "seaside", "kingdom": True},
    "Salvager": {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Buy\nTrash a card from your hand.\n+$1 per $1 it costs.",
                 "expansion": "seaside", "kingdom": True},
    "Sea Chart": {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                  "text": "+1 Card\n+1 Action\nReveal the top card of your deck. If you have a copy of it in play, put it into your hand.",
                  "expansion": "seaside", "kingdom": True},
    "Sea Witch": {"cost": 5, "types": ["action", "duration", "attack"], "coins": 0, "vp": 0,
                  "text": "+2 Cards\nEach other player gains a Curse.\nAt the start of your next turn, +2 Cards, then discard 2 cards.",
                  "expansion": "seaside", "kingdom": True},
    "Smugglers": {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                  "text": "Gain a copy of a card costing up to $6 that the player to your right gained on their last turn.",
                  "expansion": "seaside", "kingdom": True},
    "Tactician": {"cost": 5, "types": ["action", "duration"], "coins": 0, "vp": 0,
                  "text": "If you have at least one card in hand:\nDiscard your hand, and at the start of your next turn: +5 Cards, +1 Action, and +1 Buy.",
                  "expansion": "seaside", "kingdom": True},
    "Tide Pools": {"cost": 4, "types": ["action", "duration"], "coins": 0, "vp": 0,
                   "text": "+3 Cards\n+1 Action\nAt the start of your next turn, discard 2 cards.",
                   "expansion": "seaside", "kingdom": True},
    "Treasure Map": {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                     "text": "Trash this and a Treasure Map from your hand. If you trashed two Treasure Maps, gain 4 Golds onto your deck.",
                     "expansion": "seaside", "kingdom": True},
    "Treasury": {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                 "text": "+1 Card\n+1 Action\n+$1\nAt the end of your Buy phase this turn, if you didn't gain a Victory card in it, you may put this onto your deck.",
                 "expansion": "seaside", "kingdom": True},
    "Warehouse": {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                  "text": "+3 Cards\n+1 Action\nDiscard 3 cards.",
                  "expansion": "seaside", "kingdom": True},
    "Wharf": {"cost": 5, "types": ["action", "duration"], "coins": 0, "vp": 0,
              "text": "Now and at the start of your next turn:\n+2 Cards and +1 Buy.",
              "expansion": "seaside", "kingdom": True},
})

# --- Hinterlands 2E (26) -------------------------------------------------
# 17 kept from 1E + 9 new in the 2022 Second Edition; the 9 removed cards
# (Cache, Duchess, Embassy, Ill-Gotten Gains, Mandarin, Noble Brigand,
# Nomad Camp, Oracle, Silk Road) are deliberately absent.
CARDS.update({
    "Berserker":           {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                         "text": "Gain a card costing less than this. Each other player discards down to 3 cards in hand.\nWhen you gain this, if you have an Action in play, play this.",
                         "expansion": "hinterlands", "kingdom": True},
    "Border Village":      {"cost": 6, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "+1 Card\n+2 Actions\nWhen you gain this, gain a cheaper card.",
                         "expansion": "hinterlands", "kingdom": True},
    "Cartographer":        {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "+1 Card\n+1 Action\nLook at the top 4 cards of your deck. Discard any number of them, then put the rest back in any order.",
                         "expansion": "hinterlands", "kingdom": True},
    "Cauldron":            {"cost": 5, "types": ["treasure", "attack"], "coins": 2, "vp": 0,
                         "text": "$2\n+1 Buy\nThe third time you gain an Action this turn, each other player gains a Curse.",
                         "expansion": "hinterlands", "kingdom": True},
    "Crossroads":          {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "Reveal your hand. +1 Card per Victory card revealed. If this is the first time you played a Crossroads this turn, +3 Actions.",
                         "expansion": "hinterlands", "kingdom": True},
    "Develop":             {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "Trash a card from your hand. Gain two cards onto your deck, with one costing exactly $1 more than it, and one costing exactly $1 less than it, in either order.",
                         "expansion": "hinterlands", "kingdom": True},
    "Farmland":            {"cost": 6, "types": ["victory"], "coins": 0, "vp": 2,
                         "text": "When you gain this, trash a card from your hand and gain a non-Farmland card costing exactly $2 more than it.\n2 VP",
                         "expansion": "hinterlands", "kingdom": True},
    "Fool's Gold":         {"cost": 2, "types": ["treasure", "reaction"], "coins": 0, "vp": 0,
                         "text": "If this is the first time you played a Fool's Gold this turn, +$1, otherwise +$4.\nWhen another player gains a Province, you may trash this from your hand, to gain a Gold onto your deck.",
                         "expansion": "hinterlands", "kingdom": True},
    "Guard Dog":           {"cost": 3, "types": ["action", "reaction"], "coins": 0, "vp": 0,
                         "text": "+2 Cards\nIf you have 5 or fewer cards in hand, +2 Cards.\nWhen another player plays an Attack, you may first play this from your hand.",
                         "expansion": "hinterlands", "kingdom": True},
    "Haggler":             {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "+$2\nThis turn, when you gain a card, if you bought it, gain a cheaper non-Victory card.",
                         "expansion": "hinterlands", "kingdom": True},
    "Highway":             {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "+1 Card\n+1 Action\nThis turn, cards cost $1 less.",
                         "expansion": "hinterlands", "kingdom": True},
    "Inn":                 {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "+2 Cards\n+2 Actions\nDiscard 2 cards.\nWhen you gain this, reveal any number of Action cards from your discard pile and shuffle them into your deck.",
                         "expansion": "hinterlands", "kingdom": True},
    "Jack of All Trades":  {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "Gain a Silver. Look at the top card of your deck; you may discard it. Draw until you have 5 cards in hand. You may trash a non-Treasure card from your hand.",
                         "expansion": "hinterlands", "kingdom": True},
    "Margrave":            {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                         "text": "+3 Cards\n+1 Buy\nEach other player draws a card, then discards down to 3 cards in hand.",
                         "expansion": "hinterlands", "kingdom": True},
    "Nomads":              {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "+1 Buy\n+$2\nWhen you gain or trash this, +$2.",
                         "expansion": "hinterlands", "kingdom": True},
    "Oasis":               {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "+1 Card\n+1 Action\n+$1\nDiscard a card.",
                         "expansion": "hinterlands", "kingdom": True},
    "Scheme":              {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "+1 Card\n+1 Action\nThis turn, you may put one of your Action cards onto your deck when you discard it from play.",
                         "expansion": "hinterlands", "kingdom": True},
    "Souk":                {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "+1 Buy\n+$7\n–$1 per card in your hand (you can't go below $0).\nWhen you gain this, trash up to 2 cards from your hand.",
                         "expansion": "hinterlands", "kingdom": True},
    "Spice Merchant":      {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "You may trash a Treasure from your hand to choose one: +2 Cards and +1 Action; or +1 Buy and +$2.",
                         "expansion": "hinterlands", "kingdom": True},
    "Stables":             {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "You may discard a Treasure, for +3 Cards and +1 Action.",
                         "expansion": "hinterlands", "kingdom": True},
    "Trader":              {"cost": 4, "types": ["action", "reaction"], "coins": 0, "vp": 0,
                         "text": "Trash a card from your hand. Gain a Silver per $1 it costs.\nWhen you gain a card, you may reveal this from your hand, to exchange the card for a Silver.",
                         "expansion": "hinterlands", "kingdom": True},
    "Trail":               {"cost": 4, "types": ["action", "reaction"], "coins": 0, "vp": 0,
                         "text": "+1 Card\n+1 Action\nWhen you gain, trash, or discard this, other than in Clean-up, you may play it.",
                         "expansion": "hinterlands", "kingdom": True},
    "Tunnel":              {"cost": 3, "types": ["victory", "reaction"], "coins": 0, "vp": 2,
                         "text": "When you discard this other than during Clean-up, you may reveal it to gain a Gold.\n2 VP",
                         "expansion": "hinterlands", "kingdom": True},
    "Weaver":              {"cost": 4, "types": ["action", "reaction"], "coins": 0, "vp": 0,
                         "text": "Gain two Silvers or a card costing up to $4.\nWhen you discard this other than in Clean-up, you may play it.",
                         "expansion": "hinterlands", "kingdom": True},
    "Wheelwright":         {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                         "text": "+1 Card\n+1 Action\nYou may discard a card to gain an Action card costing as much as it or less.",
                         "expansion": "hinterlands", "kingdom": True},
    "Witch's Hut":         {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                         "text": "+4 Cards\nDiscard 2 cards, revealed. If they're both Actions, each other player gains a Curse.",
                         "expansion": "hinterlands", "kingdom": True},
})

KINGDOM = {
    "base": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "base"],
    "intrigue": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "intrigue"],
    "seaside": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "seaside"],
    "prosperity": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "prosperity"],
    "hinterlands": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "hinterlands"],
}


def pile_size(name, n_players):
    """Supply pile size for a card, by player count (2-4)."""
    card = CARDS[name]
    if name == "Copper":
        return 60 - 7 * n_players
    if name == "Silver":
        return 40
    if name == "Gold":
        return 30
    if name == "Curse":
        return 10 * (n_players - 1)
    if name == "Platinum":
        return 12                     # fixed at every player count
    if "victory" in card["types"]:
        return 8 if n_players == 2 else 12   # includes Colony (8 at 2p)
    return 10
