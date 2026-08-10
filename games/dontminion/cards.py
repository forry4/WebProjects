"""Dontminion static card data — the full 276-card dataset plus the first 20 LANDSCAPE
cards (Base, Intrigue, Seaside, Prosperity, Hinterlands and Cornucopia & Guilds in 2E,
plus Alchemy, Dark Ages and Adventures).

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
  KINGDOM = {"base": [...26 names...], "intrigue": [...26 names...], ...}
      — a list entry is a kingdom CARD, or (Dark Ages' "Knights") the name of a
        dealt PILE that is not a card at all; see PILES.
  PILES = {pile_name: {cost, expansion, kingdom, members, size}}
  LANDSCAPES = {name: {kind, cost, text, expansion}}
      — NOT cards and NOT piles (no copies, never gained, never in a zone); see
        the LANDSCAPES block near the bottom of this file.
  Optional cost dimensions, on BOTH tables: "potion" (Alchemy) and "debt"
  (Empires) — a cost is the vector {coins, potions, debt}, and both extra
  components are read through accessors (potion_of/debt_of, landscape_debt)
  rather than by indexing, so an entry without one costs zero of it.
  pile_size(name, n_players) -> int
  DATA_COMPLETE: bool — True only when every set's cards are present and verified.
"""

import re

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
                 # Base 2E. The 1E card read "+1 Card per card discarded"; we
                 # shipped that wording until ph. 10, where Way of the
                 # Chameleon made the difference observable for the first time
                 # (the compendium names Cellar in exactly that list).
                 "text": "+1 Action\nDiscard any number of cards, then draw "
                         "that many.",
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

# --- Cornucopia & Guilds 2E (26 + 6 Rewards) ------------------------------
# The 2024 Second Edition is a COMBINED set: 18 kept (Cornucopia 8 + Guilds 10)
# plus 8 new. The 13 removed cards (Doctor, Farming Village, Fortune Teller,
# Harvest, Horse Traders, Masterpiece, Taxman, Tournament and the 5 Prizes) are
# deliberately absent — verified twice over, by the compendium's 13
# "Not included in the 2024 Second Edition" markers and the wiki chart's
# "Cornucopia & Guilds, 1E" label, which name the same 13.
#
# "overpay": True is the `$N+` cost — you may pay MORE when buying, and the
# extra is handed to the card's own when-gain ability. Any ability that reads
# the card's cost ignores the + (compendium, OVERPAYING § IV), so `cost` stays
# the plain number and nothing else has to know.
CARDS.update({
    "Advisor":           {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nReveal the top 3 cards of your deck. The player to your left chooses one of them. Discard that card and put the rest into your hand.",
                        "expansion": "cornucopia", "kingdom": True},
    "Baker":             {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\n+1 Coffers\nSetup: Each player gets +1 Coffers.",
                        "expansion": "cornucopia", "kingdom": True},
    "Butcher":           {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Coffers\nYou may trash a card from your hand, to gain a card costing up to $1 more than it per Coffers you spend.",
                        "expansion": "cornucopia", "kingdom": True},
    "Candlestick Maker": {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Action\n+1 Buy\n+1 Coffers",
                        "expansion": "cornucopia", "kingdom": True},
    "Carnival":          {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Reveal the top 4 cards of your deck. Put one of each differently named card into your hand and discard the rest.",
                        "expansion": "cornucopia", "kingdom": True},
    "Fairgrounds":       {"cost": 6, "types": ["victory"], "coins": 0, "vp": "fairgrounds",
                        "text": "Worth 2 VP per 5 differently named cards you have (round down).",
                        "expansion": "cornucopia", "kingdom": True},
    "Farmhands":         {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+2 Actions\nWhen you gain this, you may set aside an Action or Treasure from your hand, and play it at the start of your next turn.",
                        "expansion": "cornucopia", "kingdom": True},
    "Farrier":           {"cost": 2, "types": ["action"], "coins": 0, "vp": 0, "overpay": True,
                        "text": "+1 Card\n+1 Action\n+1 Buy\nOverpay: +1 Card at the end of this turn per $1 overpaid.",
                        "expansion": "cornucopia", "kingdom": True},
    "Ferryman":          {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\n+1 Action\nDiscard a card.\nSetup: Choose an unused Kingdom card pile costing $3 or $4. Gain one when you gain a Ferryman.",
                        "expansion": "cornucopia", "kingdom": True},
    "Footpad":           {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "+2 Coffers\nEach other player discards down to 3 cards in hand.\nIn games using this, when you gain a card in an Action phase, +1 Card.",
                        "expansion": "cornucopia", "kingdom": True},
    "Hamlet":            {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nYou may discard a card for +1 Action.\nYou may discard a card for +1 Buy.",
                        "expansion": "cornucopia", "kingdom": True},
    "Herald":            {"cost": 4, "types": ["action"], "coins": 0, "vp": 0, "overpay": True,
                        "text": "+1 Card\n+1 Action\nReveal the top card of your deck. If it's an Action, play it.\nOverpay: Per $1 overpaid, put any card from your discard pile onto your deck.",
                        "expansion": "cornucopia", "kingdom": True},
    "Horn of Plenty":    {"cost": 5, "types": ["treasure"], "coins": 0, "vp": 0,
                        "text": "Gain a card costing up to $1 per differently named card you have in play (counting this). If it's a Victory card, trash this.",
                        "expansion": "cornucopia", "kingdom": True},
    "Hunting Party":     {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nReveal your hand. Reveal cards from your deck until you reveal a card that isn't a copy of one in your hand. Put it into your hand and discard the rest.",
                        "expansion": "cornucopia", "kingdom": True},
    "Infirmary":         {"cost": 3, "types": ["action"], "coins": 0, "vp": 0, "overpay": True,
                        "text": "+1 Card\nYou may trash a card from your hand.\nOverpay: Play this once per $1 overpaid.",
                        "expansion": "cornucopia", "kingdom": True},
    "Jester":            {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "+$2\nEach other player discards the top card of their deck. If it's a Victory card they gain a Curse; otherwise they gain a copy of the discarded card or you do, your choice.",
                        "expansion": "cornucopia", "kingdom": True},
    "Journeyman":        {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Name a card. Reveal cards from your deck until you reveal 3 cards without that name. Put those cards into your hand and discard the rest.",
                        "expansion": "cornucopia", "kingdom": True},
    "Joust":             {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\n+$1\nYou may set aside a Province from your hand to gain any Reward to your hand. Discard the Province in Clean-up.",
                        "expansion": "cornucopia", "kingdom": True},
    "Menagerie":         {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nReveal your hand. If the revealed cards all have different names, +3 Cards. Otherwise, +1 Card.",
                        "expansion": "cornucopia", "kingdom": True},
    "Merchant Guild":    {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Buy\n+$1\nAt the end of your Buy phase this turn, +1 Coffers per card you gained in it.",
                        "expansion": "cornucopia", "kingdom": True},
    "Plaza":             {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+2 Actions\nYou may discard a Treasure for +1 Coffers.",
                        "expansion": "cornucopia", "kingdom": True},
    "Remake":            {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Do this twice: Trash a card from your hand, then gain a card costing exactly $1 more than it.",
                        "expansion": "cornucopia", "kingdom": True},
    "Shop":              {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+$1\nYou may play an Action card from your hand that you don't have a copy of in play.",
                        "expansion": "cornucopia", "kingdom": True},
    "Soothsayer":        {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "Gain a Gold. Each other player gains a Curse, and if they did, draws a card.",
                        "expansion": "cornucopia", "kingdom": True},
    "Stonemason":        {"cost": 2, "types": ["action"], "coins": 0, "vp": 0, "overpay": True,
                        "text": "Trash a card from your hand. Gain 2 cards each costing less than it.\nOverpay: Gain 2 Action cards each costing the amount overpaid.",
                        "expansion": "cornucopia", "kingdom": True},
    "Young Witch":       {"cost": 4, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\nDiscard 2 cards. Each other player gains a Curse unless they reveal a Bane from their hand.\nSetup: Add an extra Kingdom card pile costing $2 or $3 to the Supply. Its cards are Banes.",
                        "expansion": "cornucopia", "kingdom": True},
})

# The 6 REWARDS — a pile outside the Supply, gained only by Joust and only to
# your hand. `kingdom: False` keeps them out of the randomiser; the `reward`
# type is what Coronet reads ("a non-Reward Action"). Their cost is $0 for any
# ability that refers to it (compendium, Reward (type)).
REWARDS = ["Coronet", "Courser", "Demesne", "Housecarl", "Huge Turnip", "Renown"]
CARDS.update({
    "Coronet":     {"cost": 0, "types": ["action", "treasure", "reward"], "coins": 0, "vp": 0,
                    "text": "You may play a non-Reward Action from your hand twice.\nYou may play a non-Reward Treasure from your hand twice.\n(This is not in the Supply.)",
                    "expansion": "cornucopia", "kingdom": False},
    "Courser":     {"cost": 0, "types": ["action", "reward"], "coins": 0, "vp": 0,
                    "text": "Choose two different options: +2 Cards; +2 Actions; +$2; gain 4 Silvers.\n(This is not in the Supply.)",
                    "expansion": "cornucopia", "kingdom": False},
    "Demesne":     {"cost": 0, "types": ["action", "victory", "reward"], "coins": 0, "vp": "demesne",
                    "text": "+2 Actions\n+2 Buys\nGain a Gold.\nWorth 1 VP per Gold you have.\n(This is not in the Supply.)",
                    "expansion": "cornucopia", "kingdom": False},
    "Housecarl":   {"cost": 0, "types": ["action", "reward"], "coins": 0, "vp": 0,
                    "text": "+1 Card per differently named Action card you have in play.\n(This is not in the Supply.)",
                    "expansion": "cornucopia", "kingdom": False},
    "Huge Turnip": {"cost": 0, "types": ["treasure", "reward"], "coins": 0, "vp": 0,
                    "text": "+2 Coffers\n+$1 per Coffers you have.\n(This is not in the Supply.)",
                    "expansion": "cornucopia", "kingdom": False},
    "Renown":      {"cost": 0, "types": ["action", "reward"], "coins": 0, "vp": 0,
                    "text": "+1 Buy\nThis turn, cards cost $2 less.\n(This is not in the Supply.)",
                    "expansion": "cornucopia", "kingdom": False},
})


# --- Alchemy (12 kingdom cards + Potion; no second edition) ----------------
# Alchemy was reprinted in 2018 with no card removed, so the roster is the
# original 12 — except that POSSESSION IS DELIBERATELY DEFERRED (see DEFERRED
# below). `potion` is the second component of a card's COST: a cost of just
# {Potion} is {$0, 1 Potion}, and a plain $3 is {$3, 0 Potions}.
CARDS.update({
    "Alchemist":          {"cost": 3, "potion": 1, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\n+1 Action\nAt the start of Clean-up this turn, if you have a Potion in play, you may put this onto your deck.",
                        "expansion": "alchemy", "kingdom": True},
    "Apothecary":         {"cost": 2, "potion": 1, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nReveal the top 4 cards of your deck. Put the Coppers and Potions into your hand. Put the rest back in any order.",
                        "expansion": "alchemy", "kingdom": True},
    "Apprentice":         {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nTrash a card from your hand.\n+1 Card per $1 it costs.\n+2 Cards if it has Potion in its cost.",
                        "expansion": "alchemy", "kingdom": True},
    "Familiar":           {"cost": 3, "potion": 1, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nEach other player gains a Curse.",
                        "expansion": "alchemy", "kingdom": True},
    "Golem":              {"cost": 4, "potion": 1, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Reveal cards from your deck until you reveal 2 Action cards other than Golems. Discard the other cards, then play the Action cards in either order.",
                        "expansion": "alchemy", "kingdom": True},
    "Herbalist":          {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Buy\n+$1\nOnce this turn, when you discard a Treasure from play, you may put it onto your deck.",
                        "expansion": "alchemy", "kingdom": True},
    "Philosopher's Stone": {"cost": 3, "potion": 1, "types": ["treasure"], "coins": 0, "vp": 0,
                        "text": "Count your deck and discard pile. +$1 per 5 cards total between them (round down).",
                        "expansion": "alchemy", "kingdom": True},
    "Scrying Pool":       {"cost": 2, "potion": 1, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nEach player (including you) reveals the top card of their deck and either discards it or puts it back, your choice.\nThen reveal cards from your deck until revealing one that isn't an Action. Put all of those revealed cards into your hand.",
                        "expansion": "alchemy", "kingdom": True},
    "Transmute":          {"cost": 0, "potion": 1, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Trash a card from your hand. If it is an...\nAction card, gain a Duchy\nTreasure card, gain a Transmute\nVictory card, gain a Gold",
                        "expansion": "alchemy", "kingdom": True},
    "University":         {"cost": 2, "potion": 1, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Actions\nYou may gain an Action card costing up to $5.",
                        "expansion": "alchemy", "kingdom": True},
    "Vineyard":           {"cost": 0, "potion": 1, "types": ["victory"], "coins": 0, "vp": "vineyard",
                        "text": "Worth 1 VP per 3 Action cards you have (round down).",
                        "expansion": "alchemy", "kingdom": True},
    # Potion is a basic-style pile, not a kingdom card: it joins the Supply
    # whenever any kingdom card has a Potion in its cost.
    "Potion":             {"cost": 4, "types": ["treasure"], "coins": 0, "vp": 0,
                        "text": "1 Potion",
                        "expansion": "alchemy", "kingdom": False},
})

# --- Dark Ages (35 Supply piles + Ruins/Shelters/Spoils/Madman/Mercenary) ----
# No second edition exists, so nothing is trimmed: 34 ordinary kingdom piles
# plus the KNIGHTS pile (10 differently named cards in one shuffled pile), the
# Ruins pile (5 different cards, included when a Looter is in the kingdom), the
# 3 Shelters (which replace the starting Estates, and belong to no pile) and
# the three non-Supply piles Spoils / Madman / Mercenary.
#
# FOUR NEW TYPES, all inert flags the cards themselves read: `looter` (its
# presence in the kingdom is what includes the Ruins pile), `ruins`, `knight`
# and `shelter` (Vagrant reads all three by name).
_KNIGHT_ATTACK = ("Each other player reveals the top 2 cards of their deck, "
                  "trashes one of them costing from $3 to $6, and discards the "
                  "rest. If a Knight is trashed by this, trash this.")

CARDS.update({
    "Altar":             {"cost": 6, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Trash a card from your hand. Gain a card costing up to $5.",
                        "expansion": "darkages", "kingdom": True},
    "Armory":            {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Gain a card onto your deck costing up to $4.",
                        "expansion": "darkages", "kingdom": True},
    "Band of Misfits":   {"cost": 5, "types": ["action", "command"], "coins": 0, "vp": 0,
                        "text": "Play a non-Command non-Duration Action card from the Supply that costs less than this, leaving it there.",
                        "expansion": "darkages", "kingdom": True},
    "Bandit Camp":       {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+2 Actions\nGain a Spoils.",
                        "expansion": "darkages", "kingdom": True},
    "Beggar":            {"cost": 2, "types": ["action", "reaction"], "coins": 0, "vp": 0,
                        "text": "Gain 3 Coppers to your hand.\nWhen another player plays an Attack card, you may first discard this to gain 2 Silvers, putting one onto your deck.",
                        "expansion": "darkages", "kingdom": True},
    "Catacombs":         {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Look at the top 3 cards of your deck. Choose one: Put them into your hand; or discard them and +3 Cards.\nWhen you trash this, gain a cheaper card.",
                        "expansion": "darkages", "kingdom": True},
    "Count":             {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Choose one: Discard 2 cards; or put a card from your hand onto your deck; or gain a Copper.\nChoose one: +$3; or trash your hand; or gain a Duchy.",
                        "expansion": "darkages", "kingdom": True},
    "Counterfeit":       {"cost": 5, "types": ["treasure"], "coins": 1, "vp": 0,
                        "text": "$1\n+1 Buy\nYou may play a non-Duration Treasure from your hand twice. Trash it.",
                        "expansion": "darkages", "kingdom": True},
    "Cultist":           {"cost": 5, "types": ["action", "attack", "looter"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\nEach other player gains a Ruins. You may play a Cultist from your hand.\nWhen you trash this, +3 Cards.",
                        "expansion": "darkages", "kingdom": True},
    "Death Cart":        {"cost": 4, "types": ["action", "looter"], "coins": 0, "vp": 0,
                        "text": "You may trash this or an Action card from your hand, for +$5.\nWhen you gain this, gain 2 Ruins.",
                        "expansion": "darkages", "kingdom": True},
    "Feodum":            {"cost": 4, "types": ["victory"], "coins": 0, "vp": "feodum",
                        "text": "Worth 1 VP per 3 Silvers you have (round down).\nWhen you trash this, gain 3 Silvers.",
                        "expansion": "darkages", "kingdom": True},
    "Forager":           {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Action\n+1 Buy\nTrash a card from your hand, then +$1 per differently named Treasure in the trash.",
                        "expansion": "darkages", "kingdom": True},
    "Fortress":          {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+2 Actions\nWhen you trash this, put it into your hand.",
                        "expansion": "darkages", "kingdom": True},
    "Graverobber":       {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Choose one: Gain a card from the trash costing from $3 to $6, onto your deck; or trash an Action card from your hand and gain a card costing up to $3 more than it.",
                        "expansion": "darkages", "kingdom": True},
    "Hermit":            {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Look through your discard pile. You may trash a non-Treasure from it or from your hand. Gain a card costing up to $3.\nAt the end of your Buy phase this turn, if you didn't gain any cards in it, exchange this for a Madman.",
                        "expansion": "darkages", "kingdom": True},
    "Hunting Grounds":   {"cost": 6, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+4 Cards\nWhen you trash this, gain a Duchy or 3 Estates.",
                        "expansion": "darkages", "kingdom": True},
    "Ironmonger":        {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nReveal the top card of your deck; you may discard it. Either way, if it is an...\nAction card, +1 Action\nTreasure card, +$1\nVictory card, +1 Card",
                        "expansion": "darkages", "kingdom": True},
    "Junk Dealer":       {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\n+$1\nTrash a card from your hand.",
                        "expansion": "darkages", "kingdom": True},
    "Marauder":          {"cost": 4, "types": ["action", "attack", "looter"], "coins": 0, "vp": 0,
                        "text": "Gain a Spoils. Each other player gains a Ruins.",
                        "expansion": "darkages", "kingdom": True},
    "Market Square":     {"cost": 3, "types": ["action", "reaction"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\n+1 Buy\nWhen one of your cards is trashed, you may discard this from your hand to gain a Gold.",
                        "expansion": "darkages", "kingdom": True},
    "Mystic":            {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Action\n+$2\nName a card, then reveal the top card of your deck. If you named it, put it into your hand.",
                        "expansion": "darkages", "kingdom": True},
    "Pillage":           {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "Trash this. If you did, gain 2 Spoils, and each other player with 5 or more cards in hand reveals their hand and discards a card that you choose.",
                        "expansion": "darkages", "kingdom": True},
    "Poor House":        {"cost": 1, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+$4\nReveal your hand. -$1 per Treasure card in your hand. (You can't go below $0.)",
                        "expansion": "darkages", "kingdom": True},
    "Procession":        {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "You may play a non-Duration Action card from your hand twice. Trash it. Gain an Action card costing exactly $1 more than it.",
                        "expansion": "darkages", "kingdom": True},
    "Rats":              {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nGain a Rats. Trash a card from your hand other than a Rats (or reveal a hand of all Rats).\nWhen you trash this, +1 Card.",
                        "expansion": "darkages", "kingdom": True},
    "Rebuild":           {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nName a card. Reveal cards from your deck until you reveal a Victory card you did not name. Discard the rest, trash the Victory card, and gain a Victory card costing up to $3 more than it.",
                        "expansion": "darkages", "kingdom": True},
    "Rogue":             {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "+$2\nIf there are any cards in the trash costing from $3 to $6, gain one of them. Otherwise, each other player reveals the top 2 cards of their deck, trashes one of them costing from $3 to $6, and discards the rest.",
                        "expansion": "darkages", "kingdom": True},
    "Sage":              {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nReveal cards from the top of your deck until you reveal one costing $3 or more. Put that card into your hand and discard the rest.",
                        "expansion": "darkages", "kingdom": True},
    "Scavenger":         {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+$2\nYou may put your deck into your discard pile. Put a card from your discard pile onto your deck.",
                        "expansion": "darkages", "kingdom": True},
    "Squire":            {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+$1\nChoose one: +2 Actions; or +2 Buys; or gain a Silver.\nWhen you trash this, gain an Attack card.",
                        "expansion": "darkages", "kingdom": True},
    "Storeroom":         {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Buy\nDiscard any number of cards, then draw that many. Then discard any number of cards for +$1 each.",
                        "expansion": "darkages", "kingdom": True},
    "Urchin":            {"cost": 3, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nEach other player discards down to 4 cards in hand.\nWhen you play another Attack card with this in play, you may first trash this, to gain a Mercenary.",
                        "expansion": "darkages", "kingdom": True},
    "Vagrant":           {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nReveal the top card of your deck. If it's a Curse, Ruins, Shelter, or Victory card, put it into your hand.",
                        "expansion": "darkages", "kingdom": True},
    "Wandering Minstrel": {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+2 Actions\nReveal the top 3 cards of your deck. Put the Action cards back in any order and discard the rest.",
                        "expansion": "darkages", "kingdom": True},

    # --- the KNIGHTS: ten differently named cards in ONE shuffled pile -------
    # `kingdom: False` keeps them out of the randomiser — the PILE is what gets
    # dealt (cards.PILES below), and only its top card is ever visible.
    "Dame Anna":         {"cost": 5, "types": ["action", "attack", "knight"], "coins": 0, "vp": 0,
                        "text": "You may trash up to 2 cards from your hand.\n" + _KNIGHT_ATTACK,
                        "expansion": "darkages", "kingdom": False},
    "Dame Josephine":    {"cost": 5, "types": ["action", "attack", "knight", "victory"], "coins": 0, "vp": 2,
                        "text": _KNIGHT_ATTACK + "\n2 VP",
                        "expansion": "darkages", "kingdom": False},
    "Dame Molly":        {"cost": 5, "types": ["action", "attack", "knight"], "coins": 0, "vp": 0,
                        "text": "+2 Actions\n" + _KNIGHT_ATTACK,
                        "expansion": "darkages", "kingdom": False},
    "Dame Natalie":      {"cost": 5, "types": ["action", "attack", "knight"], "coins": 0, "vp": 0,
                        "text": "You may gain a card costing up to $3.\n" + _KNIGHT_ATTACK,
                        "expansion": "darkages", "kingdom": False},
    "Dame Sylvia":       {"cost": 5, "types": ["action", "attack", "knight"], "coins": 0, "vp": 0,
                        "text": "+$2\n" + _KNIGHT_ATTACK,
                        "expansion": "darkages", "kingdom": False},
    "Sir Bailey":        {"cost": 5, "types": ["action", "attack", "knight"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\n" + _KNIGHT_ATTACK,
                        "expansion": "darkages", "kingdom": False},
    "Sir Destry":        {"cost": 5, "types": ["action", "attack", "knight"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\n" + _KNIGHT_ATTACK,
                        "expansion": "darkages", "kingdom": False},
    # "This Knight has a lower cost than the others."
    "Sir Martin":        {"cost": 4, "types": ["action", "attack", "knight"], "coins": 0, "vp": 0,
                        "text": "+2 Buys\n" + _KNIGHT_ATTACK,
                        "expansion": "darkages", "kingdom": False},
    "Sir Michael":       {"cost": 5, "types": ["action", "attack", "knight"], "coins": 0, "vp": 0,
                        "text": "Each other player discards down to 3 cards in hand.\n" + _KNIGHT_ATTACK,
                        "expansion": "darkages", "kingdom": False},
    "Sir Vander":        {"cost": 5, "types": ["action", "attack", "knight"], "coins": 0, "vp": 0,
                        "text": _KNIGHT_ATTACK + "\nWhen you trash this, gain a Gold.",
                        "expansion": "darkages", "kingdom": False},

    # --- the RUINS: one shuffled Supply pile, included iff a Looter is in the
    # kingdom, holding as many cards as there are Curses ---------------------
    "Abandoned Mine":    {"cost": 0, "types": ["action", "ruins"], "coins": 0, "vp": 0,
                        "text": "+$1", "expansion": "darkages", "kingdom": False},
    "Ruined Library":    {"cost": 0, "types": ["action", "ruins"], "coins": 0, "vp": 0,
                        "text": "+1 Card", "expansion": "darkages", "kingdom": False},
    "Ruined Market":     {"cost": 0, "types": ["action", "ruins"], "coins": 0, "vp": 0,
                        "text": "+1 Buy", "expansion": "darkages", "kingdom": False},
    "Ruined Village":    {"cost": 0, "types": ["action", "ruins"], "coins": 0, "vp": 0,
                        "text": "+1 Action", "expansion": "darkages", "kingdom": False},
    "Survivors":         {"cost": 0, "types": ["action", "ruins"], "coins": 0, "vp": 0,
                        "text": "Look at the top 2 cards of your deck. Discard them or put them back in any order.",
                        "expansion": "darkages", "kingdom": False},

    # --- the SHELTERS: they replace the 3 starting Estates and belong to NO
    # pile ("Shelter cards don't belong to any pile") ------------------------
    "Hovel":             {"cost": 1, "types": ["reaction", "shelter"], "coins": 0, "vp": 0,
                        "text": "When you gain a Victory card, you may trash this from your hand.",
                        "expansion": "darkages", "kingdom": False},
    "Necropolis":        {"cost": 1, "types": ["action", "shelter"], "coins": 0, "vp": 0,
                        "text": "+2 Actions", "expansion": "darkages", "kingdom": False},
    "Overgrown Estate":  {"cost": 1, "types": ["victory", "shelter"], "coins": 0, "vp": 0,
                        "text": "0 VP\nWhen you trash this, +1 Card.",
                        "expansion": "darkages", "kingdom": False},

    # --- the three NON-SUPPLY piles ----------------------------------------
    # "The cost of Spoils/Madman/Mercenary is $0 for any ability that refers to
    # its cost" — the printed `$0*` only marks it as not being in the Supply.
    "Spoils":            {"cost": 0, "types": ["treasure"], "coins": 3, "vp": 0,
                        "text": "$3\nWhen you play this, return it to the Spoils pile.\n(This is not in the Supply.)",
                        "expansion": "darkages", "kingdom": False},
    "Madman":            {"cost": 0, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Actions\nReturn this to the Madman pile. If you do, +1 Card per card in your hand.\n(This is not in the Supply.)",
                        "expansion": "darkages", "kingdom": False},
    "Mercenary":         {"cost": 0, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "You may trash 2 cards from your hand. If you did, +2 Cards, +$2, and each other player discards down to 3 cards in hand.\n(This is not in the Supply.)",
                        "expansion": "darkages", "kingdom": False},
})

# --- ADVENTURES (phase 7) ----------------------------------------------------
#
# TEXTS ARE THE CURRENT ONES, AND FOR NINE CARDS THAT MEANS THEY DIFFER FROM
# EVERY CARD-LIST SITE. The compendium's ch. V lists Bonfire, Bridge Troll,
# Haunted Woods, Inheritance, Messenger, Plan, Port, Storyteller and Swamp Hag
# among the cards printed in 2022, and Mission among the 2023 no-third-turn
# changes. The 2022 pass did two things across the whole catalogue — "when-buy
# triggers were changed to when-gain, and while-in-play timers were removed" —
# and both bite here:
#   * Haunted Woods / Swamp Hag / Messenger / Port / Plan's token now trigger on
#     a GAIN (Haunted Woods and Swamp Hag on a BOUGHT gain), not on the buy;
#   * Bridge Troll's cost reduction is turn-scoped like Highway's (this turn AND
#     your next turn, cumulative with a throne-room), not while-in-play;
#   * Bonfire only trashes COPPERS;
#   * Storyteller gives +1 Card instead of the +$1 it used to pay itself with.
# dominionstrategy.com/card-lists/ and the 2015 rulebook both still show the old
# wording; the compendium is the source of truth per this package's CLAUDE.md.
CARDS.update({
    # --- $2 ---
    "Coin of the Realm": {"cost": 2, "types": ["treasure", "reserve"], "coins": 1, "vp": 0,
                        "text": "$1\nWhen you play this, put it on your Tavern mat.\nDirectly after you finish playing an Action card, you may call this, for +2 Actions.",
                        "expansion": "adventures", "kingdom": True},
    "Page":              {"cost": 2, "types": ["action", "traveller"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nWhen you discard this from play, you may exchange it for a Treasure Hunter.",
                        "expansion": "adventures", "kingdom": True},
    "Peasant":           {"cost": 2, "types": ["action", "traveller"], "coins": 0, "vp": 0,
                        "text": "+1 Buy\n+$1\nWhen you discard this from play, you may exchange it for a Soldier.",
                        "expansion": "adventures", "kingdom": True},
    "Ratcatcher":        {"cost": 2, "types": ["action", "reserve"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nPut this on your Tavern mat.\nAt the start of your turn, you may call this, to trash a card from your hand.",
                        "expansion": "adventures", "kingdom": True},
    "Raze":              {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nTrash this or a card from your hand. Look at a number of cards from the top of your deck equal to the cost in $ of the trashed card. Put one of them into your hand and discard the rest.",
                        "expansion": "adventures", "kingdom": True},
    # --- $3 ---
    "Amulet":            {"cost": 3, "types": ["action", "duration"], "coins": 0, "vp": 0,
                        "text": "Now and at the start of your next turn, choose one: +$1; or trash a card from your hand; or gain a Silver.",
                        "expansion": "adventures", "kingdom": True},
    "Caravan Guard":     {"cost": 3, "types": ["action", "duration", "reaction"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nAt the start of your next turn, +$1.\nWhen another player plays an Attack card, you may first play this from your hand.",
                        "expansion": "adventures", "kingdom": True},
    "Dungeon":           {"cost": 3, "types": ["action", "duration"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nNow and at the start of your next turn: +2 Cards, then discard 2 cards.",
                        "expansion": "adventures", "kingdom": True},
    "Gear":              {"cost": 3, "types": ["action", "duration"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\nSet aside up to 2 cards from your hand face down (under this). At the start of your next turn, put them into your hand.",
                        "expansion": "adventures", "kingdom": True},
    "Guide":             {"cost": 3, "types": ["action", "reserve"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nPut this on your Tavern mat.\nAt the start of your turn, you may call this, to discard your hand and draw 5 cards.",
                        "expansion": "adventures", "kingdom": True},
    # --- $4 ---
    "Duplicate":         {"cost": 4, "types": ["action", "reserve"], "coins": 0, "vp": 0,
                        "text": "Put this on your Tavern mat.\nWhen you gain a card costing up to $6, you may call this, to gain a copy of that card.",
                        "expansion": "adventures", "kingdom": True},
    "Magpie":            {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nReveal the top card of your deck. If it's a Treasure, put it into your hand. If it's an Action or Victory card, gain a Magpie.",
                        "expansion": "adventures", "kingdom": True},
    "Messenger":         {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Buy\n+$2\nYou may put your deck into your discard pile.\nWhen you gain this, if it's your first gain this Buy phase, gain a card costing up to $4, and each other player gains a copy of it.",
                        "expansion": "adventures", "kingdom": True},
    "Miser":             {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Choose one: Put a Copper from your hand onto your Tavern mat; or +$1 per Copper on your Tavern mat.",
                        "expansion": "adventures", "kingdom": True},
    "Port":              {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+2 Actions\nWhen you gain this, gain another Port.",
                        "expansion": "adventures", "kingdom": True},
    "Ranger":            {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Buy\nTurn your Journey token over (it starts face up). Then if it's face up, +5 Cards.",
                        "expansion": "adventures", "kingdom": True},
    "Transmogrify":      {"cost": 4, "types": ["action", "reserve"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nPut this on your Tavern mat.\nAt the start of your turn, you may call this, to trash a card from your hand, and gain a card costing up to $1 more than it, into your hand.",
                        "expansion": "adventures", "kingdom": True},
    # --- $5 ---
    "Artificer":         {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\n+$1\nDiscard any number of cards. You may gain a card costing exactly $1 per card discarded, onto your deck.",
                        "expansion": "adventures", "kingdom": True},
    "Bridge Troll":      {"cost": 5, "types": ["action", "attack", "duration"], "coins": 0, "vp": 0,
                        "text": "Each other player takes their -$1 token.\nNow and at the start of your next turn: +1 Buy.\nThis turn and your next turn, cards cost $1 less.",
                        "expansion": "adventures", "kingdom": True},
    "Distant Lands":     {"cost": 5, "types": ["action", "reserve", "victory"], "coins": 0, "vp": "distant_lands",
                        "text": "Put this on your Tavern mat.\nWorth 4 VP if on your Tavern mat at the end of the game (otherwise worth 0 VP).",
                        "expansion": "adventures", "kingdom": True},
    "Giant":             {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "Turn your Journey token over (it starts face up). Then if it's face down, +$1. If it's face up, +$5, and each other player reveals the top card of their deck, trashes it if it costs from $3 to $6, and otherwise discards it and gains a Curse.",
                        "expansion": "adventures", "kingdom": True},
    "Haunted Woods":     {"cost": 5, "types": ["action", "attack", "duration"], "coins": 0, "vp": 0,
                        "text": "Until your next turn, when another player gains a bought card, they put their hand onto their deck in any order.\nAt the start of your next turn, +3 Cards.",
                        "expansion": "adventures", "kingdom": True},
    "Lost City":         {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\n+2 Actions\nWhen you gain this, each other player draws a card.",
                        "expansion": "adventures", "kingdom": True},
    "Relic":             {"cost": 5, "types": ["treasure", "attack"], "coins": 2, "vp": 0,
                        "text": "$2\nWhen you play this, each other player puts their -1 Card token on their deck.",
                        "expansion": "adventures", "kingdom": True},
    "Royal Carriage":    {"cost": 5, "types": ["action", "reserve"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nPut this on your Tavern mat.\nDirectly after you finish playing an Action card, if it's still in play, you may call this, to replay that Action.",
                        "expansion": "adventures", "kingdom": True},
    "Storyteller":       {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nPlay up to 3 Treasures from your hand. Then pay all of your $, and draw a card per $1 you paid.",
                        "expansion": "adventures", "kingdom": True},
    "Swamp Hag":         {"cost": 5, "types": ["action", "attack", "duration"], "coins": 0, "vp": 0,
                        "text": "Until your next turn, when another player gains a bought card, they gain a Curse.\nAt the start of your next turn, +$3.",
                        "expansion": "adventures", "kingdom": True},
    "Treasure Trove":    {"cost": 5, "types": ["treasure"], "coins": 2, "vp": 0,
                        "text": "$2\nWhen you play this, gain a Gold and a Copper.",
                        "expansion": "adventures", "kingdom": True},
    "Wine Merchant":     {"cost": 5, "types": ["action", "reserve"], "coins": 0, "vp": 0,
                        "text": "+1 Buy\n+$4\nPut this on your Tavern mat.\nAt the end of your Buy phase, if you have at least $2 unspent, you may discard this from your Tavern mat.",
                        "expansion": "adventures", "kingdom": True},
    # --- $6 ---
    "Hireling":          {"cost": 6, "types": ["action", "duration"], "coins": 0, "vp": 0,
                        "text": "At the start of each of your turns for the rest of the game: +1 Card.\n(This stays in play.)",
                        "expansion": "adventures", "kingdom": True},

    # --- the TRAVELLER upgrades: eight NON-SUPPLY piles of 5 (never bought,
    # only exchanged into). Their printed `$N*` cost is a real cost for every
    # ability that reads one — unlike Spoils' $0*, which is a placeholder.
    "Treasure Hunter":   {"cost": 3, "types": ["action", "traveller"], "coins": 0, "vp": 0,
                        "text": "+1 Action\n+$1\nGain a Silver per card the player to your right gained on their last turn.\nWhen you discard this from play, you may exchange it for a Warrior.\n(This is not in the Supply.)",
                        "expansion": "adventures", "kingdom": False},
    "Warrior":           {"cost": 4, "types": ["action", "attack", "traveller"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\nFor each Traveller you have in play (including this), each other player discards the top card of their deck and trashes it if it costs from $3 to $4.\nWhen you discard this from play, you may exchange it for a Hero.\n(This is not in the Supply.)",
                        "expansion": "adventures", "kingdom": False},
    "Hero":              {"cost": 5, "types": ["action", "traveller"], "coins": 0, "vp": 0,
                        "text": "+$2\nGain a Treasure.\nWhen you discard this from play, you may exchange it for a Champion.\n(This is not in the Supply.)",
                        "expansion": "adventures", "kingdom": False},
    "Champion":          {"cost": 6, "types": ["action", "duration"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nFor the rest of the game, when another player plays an Attack card, it doesn't affect you, and when you play an Action card, +1 Action.\n(This stays in play. This is not in the Supply.)",
                        "expansion": "adventures", "kingdom": False},
    "Soldier":           {"cost": 3, "types": ["action", "attack", "traveller"], "coins": 0, "vp": 0,
                        "text": "+$2\n+$1 per other Attack card you have in play.\nEach other player with 4 or more cards in hand discards a card.\nWhen you discard this from play, you may exchange it for a Fugitive.\n(This is not in the Supply.)",
                        "expansion": "adventures", "kingdom": False},
    "Fugitive":          {"cost": 4, "types": ["action", "traveller"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\n+1 Action\nDiscard a card.\nWhen you discard this from play, you may exchange it for a Disciple.\n(This is not in the Supply.)",
                        "expansion": "adventures", "kingdom": False},
    "Disciple":          {"cost": 5, "types": ["action", "traveller"], "coins": 0, "vp": 0,
                        "text": "You may play an Action card from your hand twice. Gain a copy of it.\nWhen you discard this from play, you may exchange it for a Teacher.\n(This is not in the Supply.)",
                        "expansion": "adventures", "kingdom": False},
    "Teacher":           {"cost": 6, "types": ["action", "reserve"], "coins": 0, "vp": 0,
                        "text": "Put this on your Tavern mat.\nAt the start of your turn, you may call this, to move your +1 Card, +1 Action, +1 Buy, or +$1 token to an Action Supply pile you have no tokens on.\n(This is not in the Supply.)",
                        "expansion": "adventures", "kingdom": False},
})

# --- EMPIRES (phase 8) --------------------------------------------------------
#
# 24 Supply piles = 18 ordinary ones + the five SPLIT piles + Castles, which is
# 36 card definitions. See EMPIRES_SPLITS / CASTLES below for the piles; the
# split halves and the Castles are `kingdom: False` because the thing that gets
# DEALT is the pile, not the card (the same shape as Knights in ph. 6).
#
# SIXTEEN OF THESE DIFFER FROM EVERY CARD-LIST SITE AND FROM BOTH EMPIRES
# RULEBOOKS, because the set straddles three errata passes (compendium ch. V):
#
#   2021 — Farmers' Market, Mountain Pass, Opulent Castle, Temple.
#          Opulent Castle reveals the Victory cards AS it discards them.
#          Farmers' Market and Temple gained the word "SUPPLY" ("the Temple
#          Supply pile"), which is not cosmetic for us: both cards cost $3/$4,
#          so either can be drawn as FERRYMAN's extra pile — a pile that is in
#          the game and NOT in the Supply — and then there is no Supply pile to
#          gather onto. Same for Gladiator's trash (2025, same erratum).
#   2022 — Charm, Forum, Groundskeeper, Tax (+ the Landmarks Basilica,
#          Colonnade, Defiled Shrine). THE WHEN-BUY → WHEN-GAIN PASS: every one
#          of these used to trigger on a BUY. Charm's rider now fires on your
#          next GAIN, Forum's +1 Buy is a when-gain, and Groundskeeper SETS UP
#          an ability for the rest of the turn (cumulative with a throne-room,
#          and only Victory cards gained AFTER it was played count) rather than
#          being a while-in-play timer.
#   2025 — Capital, Chariot Race, Gladiator, Overlord (+ Ritual).
#          Chariot Race now DRAWS the card instead of revealing it and putting
#          it in hand — so the -1 Card token can deny the bonuses. Capital LOST
#          its "then pay off Debt" clause (the 2024 rule made it redundant:
#          you may pay off Debt at any time during your turn). Overlord follows
#          Band of Misfits and can no longer play a Duration.
CARDS.update({
    # --- the four DEBT-COSTED Actions ({0D} costs — no coins at all) ---------
    "Engineer":          {"cost": 0, "debt": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Gain a card costing up to $4.\nYou may trash this. If you do, gain a card costing up to $4.",
                        "expansion": "empires", "kingdom": True},
    "City Quarter":      {"cost": 0, "debt": 8, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Actions\nReveal your hand. +1 Card per Action card revealed.",
                        "expansion": "empires", "kingdom": True},
    "Overlord":          {"cost": 0, "debt": 8, "types": ["action", "command"], "coins": 0, "vp": 0,
                        "text": "Play a non-Command, non-Duration Action card from the Supply costing up to $5, leaving it there.",
                        "expansion": "empires", "kingdom": True},
    "Royal Blacksmith":  {"cost": 0, "debt": 8, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+5 Cards\nReveal your hand; discard the Coppers.",
                        "expansion": "empires", "kingdom": True},
    # --- $3 ------------------------------------------------------------------
    "Chariot Race":      {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nDraw a card, revealing it. The player to your left reveals the top card of their deck. If your card costs more, +$1 and +1 VP.",
                        "expansion": "empires", "kingdom": True},
    "Enchantress":       {"cost": 3, "types": ["action", "attack", "duration"], "coins": 0, "vp": 0,
                        "text": "Until your next turn, the first time each other player plays an Action card on their turn, they get +1 Card and +1 Action instead of following its instructions.\nAt the start of your next turn, +2 Cards.",
                        "expansion": "empires", "kingdom": True},
    "Farmers' Market":   {"cost": 3, "types": ["action", "gathering"], "coins": 0, "vp": 0,
                        "text": "+1 Buy\nIf there is 4 VP or more on the Farmers' Market Supply pile, take it and trash this. Otherwise, add 1 VP to the pile and then +$1 per 1 VP on it.",
                        "expansion": "empires", "kingdom": True},
    # --- $4 ------------------------------------------------------------------
    "Sacrifice":         {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Trash a card from your hand. If it's an\nAction card, +2 Cards and +2 Actions;\nTreasure card, +$2;\nVictory card, +2 VP.",
                        "expansion": "empires", "kingdom": True},
    "Temple":            {"cost": 4, "types": ["action", "gathering"], "coins": 0, "vp": 0,
                        "text": "+1 VP\nTrash from 1 to 3 differently named cards from your hand.\nAdd 1 VP to the Temple Supply pile.\nWhen you gain this, take the VP from the Temple Supply pile.",
                        "expansion": "empires", "kingdom": True},
    "Villa":             {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Actions\n+1 Buy\n+$1\nWhen you gain this, put it into your hand, +1 Action, and if it's your Buy phase return to your Action phase.",
                        "expansion": "empires", "kingdom": True},
    # --- $5 ------------------------------------------------------------------
    "Archive":           {"cost": 5, "types": ["action", "duration"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nSet aside the top 3 cards of your deck face down (you may look at them). Now and at the start of your next two turns, put one into your hand.",
                        "expansion": "empires", "kingdom": True},
    "Capital":           {"cost": 5, "types": ["treasure"], "coins": 6, "vp": 0,
                        "text": "$6\n+1 Buy\nWhen you discard this from play, take 6 Debt.",
                        "expansion": "empires", "kingdom": True},
    "Charm":             {"cost": 5, "types": ["treasure"], "coins": 0, "vp": 0,
                        "text": "When you play this, choose one: +1 Buy and +$2; or the next time you gain a card this turn, you may also gain a differently named card with the same cost.",
                        "expansion": "empires", "kingdom": True},
    "Crown":             {"cost": 5, "types": ["action", "treasure"], "coins": 0, "vp": 0,
                        "text": "If it's your Action phase, you may play an Action from your hand twice.\nIf it's your Buy phase, you may play a Treasure from your hand twice.",
                        "expansion": "empires", "kingdom": True},
    "Forum":             {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+3 Cards\n+1 Action\nDiscard 2 cards.\nWhen you gain this, +1 Buy.",
                        "expansion": "empires", "kingdom": True},
    "Groundskeeper":     {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nThis turn, when you gain a Victory card, +1 VP.",
                        "expansion": "empires", "kingdom": True},
    "Legionary":         {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "+$3\nYou may reveal a Gold from your hand. If you do, each other player discards down to 2 cards in hand, then draws a card.",
                        "expansion": "empires", "kingdom": True},
    "Wild Hunt":         {"cost": 5, "types": ["action", "gathering"], "coins": 0, "vp": 0,
                        "text": "Choose one: +3 Cards and add 1 VP to the Wild Hunt Supply pile; or gain an Estate, taking the VP from the pile.",
                        "expansion": "empires", "kingdom": True},

    # --- the five SPLIT piles: five of the cheap half on top of five of the
    # dear half. Both halves are `kingdom: False` — EMPIRES_SPLITS deals the
    # PILE, whose name is not a card (see PILES).
    "Encampment":        {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\n+2 Actions\nReveal a Gold or Plunder from your hand. If you don't, set this aside, and return it to the Supply at the start of Clean-up.",
                        "expansion": "empires", "kingdom": False},
    "Plunder":           {"cost": 5, "types": ["treasure"], "coins": 2, "vp": 0,
                        "text": "$2\n+1 VP",
                        "expansion": "empires", "kingdom": False},
    "Patrician":         {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nReveal the top card of your deck. If it costs $5 or more, put it into your hand.",
                        "expansion": "empires", "kingdom": False},
    "Emporium":          {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\n+$1\nWhen you gain this, if you have at least 5 Action cards in play, +2 VP.",
                        "expansion": "empires", "kingdom": False},
    "Settlers":          {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nLook through your discard pile. You may reveal a Copper from it and put it into your hand.",
                        "expansion": "empires", "kingdom": False},
    "Bustling Village":  {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+3 Actions\nLook through your discard pile. You may reveal a Settlers from it and put it into your hand.",
                        "expansion": "empires", "kingdom": False},
    "Catapult":          {"cost": 3, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "+$1\nTrash a card from your hand. If it costs $3 or more, each other player gains a Curse. If it's a Treasure, each other player discards down to 3 cards in hand.",
                        "expansion": "empires", "kingdom": False},
    "Rocks":             {"cost": 4, "types": ["treasure"], "coins": 1, "vp": 0,
                        "text": "$1\nWhen you gain or trash this, gain a Silver; put it onto your deck if it's your Buy phase, otherwise into your hand.",
                        "expansion": "empires", "kingdom": False},
    "Gladiator":         {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+$2\nReveal a card from your hand. The player to your left reveals a copy of it from their hand. If they don't, +$1 and trash a Gladiator from the Supply.",
                        "expansion": "empires", "kingdom": False},
    "Fortune":           {"cost": 8, "debt": 8, "types": ["treasure"], "coins": 0, "vp": 0,
                        "text": "+1 Buy\nWhen you play this, double your $ (once per turn).\nWhen you gain this, gain a Gold per Gladiator you have in play.",
                        "expansion": "empires", "kingdom": False},

    # --- the CASTLES pile: eight different Victory cards, sorted by cost with
    # the cheapest on top. Humble and King's Castle count Castles, which is a
    # TYPE, so both are computed VP kinds rather than numbers.
    "Humble Castle":     {"cost": 3, "types": ["treasure", "victory", "castle"], "coins": 1, "vp": "humble_castle",
                        "text": "$1\nWorth 1 VP per Castle you have.",
                        "expansion": "empires", "kingdom": False},
    "Crumbling Castle":  {"cost": 4, "types": ["victory", "castle"], "coins": 0, "vp": 1,
                        "text": "1 VP\nWhen you gain or trash this, +1 VP and gain a Silver.",
                        "expansion": "empires", "kingdom": False},
    "Small Castle":      {"cost": 5, "types": ["action", "victory", "castle"], "coins": 0, "vp": 2,
                        "text": "2 VP\nTrash this or a Castle from your hand. If you do, gain a Castle.",
                        "expansion": "empires", "kingdom": False},
    "Haunted Castle":    {"cost": 6, "types": ["victory", "castle"], "coins": 0, "vp": 2,
                        "text": "2 VP\nWhen you gain this on your turn, gain a Gold, and each other player with 5 or more cards in hand puts 2 cards from their hand onto their deck.",
                        "expansion": "empires", "kingdom": False},
    "Opulent Castle":    {"cost": 7, "types": ["action", "victory", "castle"], "coins": 0, "vp": 3,
                        "text": "3 VP\nDiscard any number of Victory cards, revealing them. +$2 per card discarded.",
                        "expansion": "empires", "kingdom": False},
    "Sprawling Castle":  {"cost": 8, "types": ["victory", "castle"], "coins": 0, "vp": 4,
                        "text": "4 VP\nWhen you gain this, gain a Duchy or 3 Estates.",
                        "expansion": "empires", "kingdom": False},
    "Grand Castle":      {"cost": 9, "types": ["victory", "castle"], "coins": 0, "vp": 5,
                        "text": "5 VP\nWhen you gain this, reveal your hand. +1 VP per Victory card in your hand and in play.",
                        "expansion": "empires", "kingdom": False},
    "King's Castle":     {"cost": 10, "types": ["victory", "castle"], "coins": 0, "vp": "kings_castle",
                        "text": "Worth 2 VP per Castle you have.",
                        "expansion": "empires", "kingdom": False},
})

# --- RENAISSANCE (phase 9) ----------------------------------------------------
#
# 25 kingdom piles, all of size 10 (the compendium states every pile-size
# exception as a special-setup line — "if Rats is in the Supply, use all 20
# cards" — and Renaissance's SPECIAL SETUP section has none, Experiment
# included). No second edition, so nothing is trimmed; no Victory kingdom
# cards, no Events, no Landmarks, no Heirlooms. The 20 Projects are LANDSCAPES
# and the 5 Artifacts are neither cards nor landscapes — see ARTIFACTS.
#
# SEVEN OBJECTS DIFFER FROM THEIR ORIGINAL 2018 PRINTING (compendium ch. V);
# the texts below are the CURRENT ones:
#
#   2019 — Lantern. It now "triggers when you play ANY Border Guard instead of
#          changing just your Border Guards", so a Border Guard played out of
#          the trash or from the Supply is modified if the PLAYER holds it.
#   2021 — Citadel, Innovation. Citadel was changed to play the card twice and
#          then, "because of an unintended effect, CHANGED BACK IN 2022" — the
#          current card replays it after it resolves (the ph.-6H
#          `action_resolved` seam). Innovation dropped its "set aside" clause.
#   2022 — Experiment, Exploration, Patron (+ Citadel's revert). Experiment
#          returns "to its PILE" rather than to the Supply, which is what lets
#          it work with Ferryman's extra pile; Exploration counts every card
#          GAINED in the Buy phase, not just bought ones; and Patron pays
#          Coffers only "during an Action phase", which is what kills the old
#          Pursue infinite and means a Buy-phase reveal (Loan, Venture) pays
#          nothing.
#   2024 — Scepter, with Rising Sun. It is now itself a COMMAND card and may
#          only replay non-Command cards, "to prevent you from using Scepter
#          to replay itself infinitely when Enlightenment is active". Ch. V
#          notes this was NOT PRINTED YET; we ship current texts by directive.
#
# Villagers are the second spendable mat and are ACTION-PHASE ONLY — they never
# received Coffers' 2022 "any time during your turn" change. See Kernel v9.
CARDS.update({
    "Border Guard":      {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nReveal the top 2 cards of your deck. Put one into your hand and discard the other. If both were Actions, take the Lantern or Horn.",
                        "expansion": "renaissance", "kingdom": True},
    "Ducat":             {"cost": 2, "types": ["treasure"], "coins": 0, "vp": 0,
                        "text": "+1 Coffers\n+1 Buy\nWhen you gain this, you may trash a Copper from your hand.",
                        "expansion": "renaissance", "kingdom": True},
    "Lackeys":           {"cost": 2, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\nWhen you gain this, +2 Villagers.",
                        "expansion": "renaissance", "kingdom": True},
    "Acting Troupe":     {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+4 Villagers\nTrash this.",
                        "expansion": "renaissance", "kingdom": True},
    "Cargo Ship":        {"cost": 3, "types": ["action", "duration"], "coins": 0, "vp": 0,
                        "text": "+$2\nOnce this turn, when you gain a card, you may set it aside face up (on this). At the start of your next turn, put it into your hand.",
                        "expansion": "renaissance", "kingdom": True},
    "Experiment":        {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\n+1 Action\nReturn this to its pile.\nWhen you gain this, gain another Experiment (that doesn't come with another).",
                        "expansion": "renaissance", "kingdom": True},
    "Improve":           {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+$2\nAt the start of Clean-up, you may trash an Action card you would discard from play this turn, to gain a card costing exactly $1 more than it.",
                        "expansion": "renaissance", "kingdom": True},
    "Flag Bearer":       {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+$2\nWhen you gain or trash this, take the Flag.",
                        "expansion": "renaissance", "kingdom": True},
    "Hideout":           {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+2 Actions\nTrash a card from your hand. If it's a Victory card, gain a Curse.",
                        "expansion": "renaissance", "kingdom": True},
    "Inventor":          {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Gain a card costing up to $4, then cards cost $1 less this turn.",
                        "expansion": "renaissance", "kingdom": True},
    "Mountain Village":  {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Actions\nLook through your discard pile and put a card from it into your hand; if you can't, +1 Card.",
                        "expansion": "renaissance", "kingdom": True},
    "Patron":            {"cost": 4, "types": ["action", "reaction"], "coins": 0, "vp": 0,
                        "text": "+1 Villager\n+$2\nWhen something causes you to reveal this (using the word \"reveal\") in an Action phase, +1 Coffers.",
                        "expansion": "renaissance", "kingdom": True},
    "Priest":            {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+$2\nTrash a card from your hand.\nFor the rest of this turn, when you trash a card, +$2.",
                        "expansion": "renaissance", "kingdom": True},
    "Research":          {"cost": 4, "types": ["action", "duration"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nTrash a card from your hand. Per $1 it costs, set aside a card from your deck face down (on this). At the start of your next turn, put those cards into your hand.",
                        "expansion": "renaissance", "kingdom": True},
    "Silk Merchant":     {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\n+1 Buy\nWhen you gain or trash this, +1 Coffers and +1 Villager.",
                        "expansion": "renaissance", "kingdom": True},
    "Old Witch":         {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "+3 Cards\nEach other player gains a Curse and may trash a Curse from their hand.",
                        "expansion": "renaissance", "kingdom": True},
    "Recruiter":         {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\nTrash a card from your hand. +1 Villager per $1 it costs.",
                        "expansion": "renaissance", "kingdom": True},
    "Scepter":           {"cost": 5, "types": ["treasure", "command"], "coins": 0, "vp": 0,
                        "text": "Choose one: +$2; or replay a non-Command Action card you played this turn that's still in play.",
                        "expansion": "renaissance", "kingdom": True},
    "Scholar":           {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Discard your hand. +7 Cards.",
                        "expansion": "renaissance", "kingdom": True},
    "Sculptor":          {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Gain a card to your hand costing up to $4. If it's a Treasure, +1 Villager.",
                        "expansion": "renaissance", "kingdom": True},
    "Seer":              {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\nReveal the top 3 cards of your deck. Put the ones costing from $2 to $4 into your hand. Put the rest back in any order.",
                        "expansion": "renaissance", "kingdom": True},
    "Spices":            {"cost": 5, "types": ["treasure"], "coins": 2, "vp": 0,
                        "text": "$2\n+1 Buy\nWhen you gain this, +2 Coffers.",
                        "expansion": "renaissance", "kingdom": True},
    "Swashbuckler":      {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+3 Cards\nIf your discard pile has any cards in it: +1 Coffers, then if you have at least 4 Coffers tokens, take the Treasure Chest.",
                        "expansion": "renaissance", "kingdom": True},
    "Treasurer":         {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+$3\nChoose one: Trash a Treasure from your hand; or gain a Treasure from the trash to your hand; or take the Key.",
                        "expansion": "renaissance", "kingdom": True},
    "Villain":           {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "+2 Coffers\nEach other player with 5 or more cards in hand discards one costing $2 or more (or reveals they can't).",
                        "expansion": "renaissance", "kingdom": True},
})

# --- MENAGERIE (phase 10): 30 kingdom cards + the Horse pile ------------------
#
# All 30 piles are 10 cards: the compendium expresses every pile-size exception
# as a special-setup line ("If Rats is in the Supply, use all 20 cards") and the
# Menagerie SPECIAL SETUP section contains none, and the set has NO Victory-typed
# kingdom card, so the 8/12 rule is moot.
#
# THE ERRATA — four objects differ from the 2020 printing, three of them from the
# 2025 pass that no card-list site necessarily carries yet:
#   2020 — Village Green gained a REVEAL on its Reaction. The compendium then
#          contradicts itself: ch. VII 10 says it "was reverted back to the
#          original version when printed in 2025", while ch. VIII's own timing
#          model is headed "Village Green (current version, 2020)" and reads
#          "you may reveal This. If you do: Play This". Two sources say reveal,
#          one says reverted; we SHIP THE REVEAL (chart + ch. VIII) and pin it.
#          Recorded as ambiguity A9.
#   2025 — Gamble now ALWAYS discards the top card first, then plays it from the
#          discard pile if you choose to. Pre-2025 it revealed and only
#          discarded on a decline, so a Village Green / Trail / Weaver /
#          Faithful Hound now reacts to Gamble's discard.
#   2025 — Reap gains the Gold DIRECTLY to the set-aside area rather than to the
#          discard pile and then setting it aside ("with the first version, the
#          Gold visits your discard pile, so a when-gain ability like Sheepdog
#          could cause it to be shuffled in and therefore lost track of").
#   2025 — Way of the Mouse's set-aside card may no longer be a DURATION. Ch. I's
#          setup paragraph was not updated to match; the card and ch. VII win.
#
# Horse's cost is $3 "for any ability that refers to its cost", and it is
# REMOVED FROM PLAY when played — both card-code concerns, but the $3 lives here.
CARDS.update({
    "Horse":             {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\n+1 Action\nReturn this to its pile. (This is not in the Supply.)",
                        "expansion": "menagerie", "kingdom": False},
    "Black Cat":         {"cost": 2, "types": ["action", "attack", "reaction"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\nIf it isn't your turn, each other player gains a Curse.\nWhen another player gains a Victory card, you may play this from your hand.",
                        "expansion": "menagerie", "kingdom": True},
    "Sleigh":            {"cost": 2, "types": ["action", "reaction"], "coins": 0, "vp": 0,
                        "text": "Gain 2 Horses.\nWhen you gain a card, you may discard this, to put that card into your hand or onto your deck.",
                        "expansion": "menagerie", "kingdom": True},
    "Supplies":          {"cost": 2, "types": ["treasure"], "coins": 1, "vp": 0,
                        "text": "$1\nGain a Horse onto your deck.",
                        "expansion": "menagerie", "kingdom": True},
    "Camel Train":       {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Exile a non-Victory card from the Supply.\nWhen you gain this, Exile a Gold from the Supply.",
                        "expansion": "menagerie", "kingdom": True},
    "Goatherd":          {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nYou may trash a card from your hand.\n+1 Card per card the player to your right trashed on their last turn.",
                        "expansion": "menagerie", "kingdom": True},
    "Scrap":             {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Trash a card from your hand. Choose a different thing per $1 it costs: +1 Card; +1 Action; +1 Buy; +$1; gain a Silver; gain a Horse.",
                        "expansion": "menagerie", "kingdom": True},
    "Sheepdog":          {"cost": 3, "types": ["action", "reaction"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\nWhen you gain a card, you may play this from your hand.",
                        "expansion": "menagerie", "kingdom": True},
    "Snowy Village":     {"cost": 3, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+4 Actions\n+1 Buy\nIgnore any further +Actions you get this turn.",
                        "expansion": "menagerie", "kingdom": True},
    "Stockpile":         {"cost": 3, "types": ["treasure"], "coins": 3, "vp": 0,
                        "text": "$3\n+1 Buy\nExile this.",
                        "expansion": "menagerie", "kingdom": True},
    "Bounty Hunter":     {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Action\nExile a card from your hand. If you didn't have a copy of it in Exile, +$3.",
                        "expansion": "menagerie", "kingdom": True},
    "Cardinal":          {"cost": 4, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "+$2\nEach other player reveals the top 2 cards of their deck, Exiles one costing from $3 to $6, and discards the rest.",
                        "expansion": "menagerie", "kingdom": True},
    "Cavalry":           {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Gain 2 Horses.\nWhen you gain this, +2 Cards, +1 Buy, and if it's your Buy phase return to your Action phase.",
                        "expansion": "menagerie", "kingdom": True},
    "Groom":             {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Gain a card costing up to $4. If it's an...\nAction card, gain a Horse;\nTreasure card, gain a Silver;\nVictory card, +1 Card and +1 Action.",
                        "expansion": "menagerie", "kingdom": True},
    "Hostelry":          {"cost": 4, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+2 Actions\nWhen you gain this, you may discard any number of Treasures, revealed, to gain that many Horses.",
                        "expansion": "menagerie", "kingdom": True},
    "Village Green":     {"cost": 4, "types": ["action", "duration", "reaction"], "coins": 0, "vp": 0,
                        "text": "Either now or at the start of your next turn, +1 Card and +2 Actions.\nWhen you discard this other than during Clean-up, you may reveal it to play it.",
                        "expansion": "menagerie", "kingdom": True},
    "Barge":             {"cost": 5, "types": ["action", "duration"], "coins": 0, "vp": 0,
                        "text": "Either now or at the start of your next turn, +3 Cards and +1 Buy.",
                        "expansion": "menagerie", "kingdom": True},
    "Coven":             {"cost": 5, "types": ["action", "attack"], "coins": 0, "vp": 0,
                        "text": "+1 Action\n+$2\nEach other player Exiles a Curse from the Supply. If they can't, they discard their Exiled Curses.",
                        "expansion": "menagerie", "kingdom": True},
    "Displace":          {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "Exile a card from your hand. Gain a differently named card costing up to $2 more than it.",
                        "expansion": "menagerie", "kingdom": True},
    "Falconer":          {"cost": 5, "types": ["action", "reaction"], "coins": 0, "vp": 0,
                        "text": "Gain a card to your hand costing less than this.\nWhen any player gains a card with 2 or more types (Action, Attack, etc.), you may play this from your hand.",
                        "expansion": "menagerie", "kingdom": True},
    "Fisherman":         {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\n+$1\nDuring your turns, if your discard pile is empty, this costs $3 less.",
                        "expansion": "menagerie", "kingdom": True},
    "Gatekeeper":        {"cost": 5, "types": ["action", "duration", "attack"], "coins": 0, "vp": 0,
                        "text": "At the start of your next turn, +$3.\nUntil then, when another player gains an Action or Treasure card they don't have an Exiled copy of, they Exile it.",
                        "expansion": "menagerie", "kingdom": True},
    "Hunting Lodge":     {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+2 Actions\nYou may discard your hand for +5 Cards.",
                        "expansion": "menagerie", "kingdom": True},
    "Kiln":              {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+$2\nThe next time you play a card this turn, you may first gain a copy of it.",
                        "expansion": "menagerie", "kingdom": True},
    "Livery":            {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+$3\nThis turn, when you gain a card costing $4 or more, gain a Horse.",
                        "expansion": "menagerie", "kingdom": True},
    "Mastermind":        {"cost": 5, "types": ["action", "duration"], "coins": 0, "vp": 0,
                        "text": "At the start of your next turn, you may play an Action card from your hand three times.",
                        "expansion": "menagerie", "kingdom": True},
    "Paddock":           {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+$2\nGain 2 Horses.\n+1 Action per empty Supply pile.",
                        "expansion": "menagerie", "kingdom": True},
    "Sanctuary":         {"cost": 5, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+1 Card\n+1 Action\n+1 Buy\nYou may Exile a card from your hand.",
                        "expansion": "menagerie", "kingdom": True},
    "Destrier":          {"cost": 6, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+2 Cards\n+1 Action\nDuring your turns, this costs $1 less per card you've gained this turn.",
                        "expansion": "menagerie", "kingdom": True},
    "Wayfarer":          {"cost": 6, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+3 Cards\nYou may gain a Silver.\nThis has the same cost as the last other card gained this turn, if any.",
                        "expansion": "menagerie", "kingdom": True},
    "Animal Fair":       {"cost": 7, "types": ["action"], "coins": 0, "vp": 0,
                        "text": "+$4\n+1 Buy per empty Supply pile.\nInstead of paying this card's cost, you may trash an Action card from your hand.",
                        "expansion": "menagerie", "kingdom": True},
})

# THE TRAVELLER CHAINS — "when you discard this from play, you may EXCHANGE it
# for the next one". `from -> into`; each upgrade is its own non-Supply pile of
# TRAVELLER_PILE cards, included whenever the chain's head is in the kingdom.
# A chain is data rather than a per-card constant because the setup rule ("if
# Page is in the Supply, add the Treasure Hunter, Warrior, Hero and Champion
# piles") has to walk it, and because a Traveller can only be exchanged for the
# card that follows it.
TRAVELLERS = {
    "Page": "Treasure Hunter", "Treasure Hunter": "Warrior",
    "Warrior": "Hero", "Hero": "Champion",
    "Peasant": "Soldier", "Soldier": "Fugitive",
    "Fugitive": "Disciple", "Disciple": "Teacher",
}
TRAVELLER_PILE = 5          # "5 copies each of the Traveller upgrades"


def traveller_chain(head):
    """Every upgrade above `head`, in order — the piles its presence adds."""
    out, cur = [], TRAVELLERS.get(head)
    while cur is not None:
        out.append(cur)
        cur = TRAVELLERS.get(cur)
    return out

# The cards each shuffled Dark Ages pile is built from. Named constants rather
# than a types scan so a set that reuses a type can't quietly join a pile.
KNIGHTS = ["Dame Anna", "Dame Josephine", "Dame Molly", "Dame Natalie",
           "Dame Sylvia", "Sir Bailey", "Sir Destry", "Sir Martin",
           "Sir Michael", "Sir Vander"]
RUINS = ["Abandoned Mine", "Ruined Library", "Ruined Market", "Ruined Village",
         "Survivors"]
RUINS_EACH = 10          # "shuffle the 50 Ruins cards" — 10 of each of the 5
SHELTERS = ["Hovel", "Necropolis", "Overgrown Estate"]

# PILES — dealt like a kingdom card, but the pile's NAME IS NOT A CARD.
#
# "Knight" and "Ruins" are TYPES, not names (compendium): there is no card
# called "Knights", so the pile cannot have a CARDS entry — engine._priced
# resolves a name that IS a card to itself, which would make the pile show its
# own printed cost instead of its top card's (a Sir Martin on top costs $4).
# Everything that walks a kingdom list therefore has to tolerate a name that is
# a pile: `grants` returns False for one, `expansion_of` answers for it, and
# the bots go through bot_traits.pile_traits.
# EMPIRES' split piles: five of the cheap half on top of five of the dear half
# ("if one of these piles is in the Supply, put the five cheaper cards on top").
# The pile's NAME is the randomizer's, which is why it is a PILES entry and not
# a CARDS one — `_priced` resolves a name that IS a card to itself, so a pile
# called "Encampment" would keep showing $2 with a Plunder on top.
EMPIRES_SPLITS = {
    "Encampment/Plunder":        ("Encampment", "Plunder"),
    "Patrician/Emporium":        ("Patrician", "Emporium"),
    "Settlers/Bustling Village": ("Settlers", "Bustling Village"),
    "Catapult/Rocks":            ("Catapult", "Rocks"),
    "Gladiator/Fortune":         ("Gladiator", "Fortune"),
}
SPLIT_EACH = 5           # "put the FIVE cheaper cards on top" (5 + 5)

# The Castles pile, cheapest on top. "In a 2-player game, use one of each of the
# 8 unique cards" — otherwise two of each.
CASTLES = ["Humble Castle", "Crumbling Castle", "Small Castle", "Haunted Castle",
           "Opulent Castle", "Sprawling Castle", "Grand Castle", "King's Castle"]

# PILES — dealt like a kingdom card, but the pile's NAME IS NOT A CARD.
#
# "Knight" and "Ruins" are TYPES, not names (compendium): there is no card
# called "Knights", so the pile cannot have a CARDS entry — engine._priced
# resolves a name that IS a card to itself, which would make the pile show its
# own printed cost instead of its top card's (a Sir Martin on top costs $4).
# Everything that walks a kingdom list therefore has to tolerate a name that is
# a pile: `grants` returns False for one, `expansion_of` answers for it, and
# the bots go through bot_traits.pile_traits.
#
# `cost` and `types` are THE RANDOMIZER'S, not the top card's, and ph. 8 is
# where that distinction started to matter (compendium ch. IV, SPLIT PILES:
# PILE TYPE AND COST — "split piles instead follow the Randomizer card"). Three
# of the five Empires splits show a TREASURE once the bottom half surfaces, but
# the pile stays an ACTION pile: "you can put your +$1 token on the
# Catapult/Rocks pile, and then get +$1 when you play a Catapult OR A ROCKS".
# It decides Defiled Shrine's and Obelisk's setup, every Adventures token, the
# Young Witch Bane and the Ferryman pile. Read it through `pile_types` /
# `pile_printed_cost`, never off the face.
PILES = {
    "Knights": {"cost": 5, "types": ["action", "attack", "knight"],
                "expansion": "darkages", "kingdom": True,
                "members": KNIGHTS, "size": len(KNIGHTS)},
    "Castles": {"cost": 3, "types": ["victory", "castle"],
                "expansion": "empires", "kingdom": True,
                "members": CASTLES, "size": len(CASTLES)},
}
for _pile, (_cheap, _dear) in EMPIRES_SPLITS.items():
    PILES[_pile] = {"cost": CARDS[_cheap]["cost"],
                    "types": list(CARDS[_cheap]["types"]),
                    "expansion": "empires", "kingdom": True,
                    "members": [_cheap, _dear], "size": 2 * SPLIT_EACH}


# --- LANDSCAPES (phase 6H) ----------------------------------------------------
#
# A LANDSCAPE IS NOT A CARD AND NOT A PILE, and that is why it gets its own home
# rather than a corner of one of theirs. It has no copies, is never gained,
# never sits in a zone, and "buying an Event is not buying a card" (compendium
# p32) — so a CARDS entry would give it a cost that cost() would then reduce, a
# type list nothing reads, and a `kingdom` flag that would deal it as one of the
# ten. This is the Knights lesson (a pile name that is not a card) in reverse:
# there, an existing structure had to LEARN to tolerate a foreign name; here the
# foreign thing arrives before its first consumer, so it gets its own table.
#
#   LANDSCAPES[name] = {"kind": ..., "cost": int, "text": str, "expansion": str,
#                       "debt": int (optional — Empires' Debt-costed Events)}
#
# `kind` is the whole taxonomy up front, so the schema does not have to change
# per set even though the machinery arrives per set:
#   event     — bought from the buy phase for a one-shot ability   (Adventures, ph. 7)
#   project   — bought once, permanent, a cube marks it            (Renaissance, ph. 9)
#   way       — an alternative way to play an Action                (Menagerie, ph. 10)
#   landmark  — an alternative scoring rule                         (Empires, ph. 8)
#   trait     — attaches to one Kingdom pile                        (Plunder, ph. 13)
#   prophecy  — a global rule that switches on partway through      (Rising Sun, ph. 14)
# 6H builds the EVENT path end to end and only frames the rest.
LANDSCAPE_KINDS = ("event", "project", "way", "landmark", "trait", "prophecy")
# The kinds you BUY (spending a Buy and money). Everything else is consulted,
# never purchased — which is the difference `buy_landscape` gates on.
BUYABLE_LANDSCAPE_KINDS = ("event", "project")
# `once` (optional): "once per turn" / "once per game" restrictions on BUYING it
# — p32, "once per turn/once per game means you can only buy it once per
# turn/game". Both are per player.
LANDSCAPE_ONCE = ("turn", "game")

LANDSCAPES = {
    # --- ADVENTURES: the first 20 Events (phase 7) ---------------------------
    # `once` is the BUY restriction (compendium p32: "once per turn / once per
    # game means you can only buy it once per turn / once per game"), per player.
    "Alms":            {"kind": "event", "cost": 0, "expansion": "adventures", "once": "turn",
                        "text": "Once per turn: If you have no Treasures in play, gain a card costing up to $4."},
    "Borrow":          {"kind": "event", "cost": 0, "expansion": "adventures", "once": "turn",
                        "text": "Once per turn: +1 Buy. If your -1 Card token isn't on your deck, put it there and +$1."},
    "Quest":           {"kind": "event", "cost": 0, "expansion": "adventures",
                        "text": "You may discard an Attack, two Curses, or six cards. If you do, gain a Gold."},
    "Save":            {"kind": "event", "cost": 1, "expansion": "adventures", "once": "turn",
                        "text": "Once per turn: +1 Buy. Set aside a card from your hand, and put it into your hand at end of turn (after drawing)."},
    "Scouting Party":  {"kind": "event", "cost": 2, "expansion": "adventures",
                        "text": "+1 Buy. Look at the top 5 cards of your deck. Discard 3 and put the rest back in any order."},
    "Travelling Fair": {"kind": "event", "cost": 2, "expansion": "adventures",
                        "text": "+2 Buys. When you gain a card this turn, you may put it onto your deck."},
    "Bonfire":         {"kind": "event", "cost": 3, "expansion": "adventures",
                        "text": "Trash up to 2 Coppers you have in play."},
    "Expedition":      {"kind": "event", "cost": 3, "expansion": "adventures",
                        "text": "Draw 2 extra cards for your next hand."},
    "Ferry":           {"kind": "event", "cost": 3, "expansion": "adventures",
                        "text": "Move your -$2 cost token to an Action Supply pile.\n(Cards from that pile cost $2 less on your turns.)"},
    "Plan":            {"kind": "event", "cost": 3, "expansion": "adventures",
                        "text": "Move your Trashing token to an Action Supply pile.\n(When you gain a card from that pile, you may trash a card from your hand.)"},
    "Mission":         {"kind": "event", "cost": 4, "expansion": "adventures", "once": "turn",
                        "text": "Once per turn: If the previous turn wasn't yours, take another turn after this one, during which you can't buy cards."},
    "Pilgrimage":      {"kind": "event", "cost": 4, "expansion": "adventures", "once": "turn",
                        "text": "Once per turn: Turn your Journey token over (it starts face up); then if it's face up, choose up to 3 differently named cards you have in play and gain a copy of each."},
    "Ball":            {"kind": "event", "cost": 5, "expansion": "adventures",
                        "text": "Take your -$1 token. Gain 2 cards each costing up to $4."},
    "Raid":            {"kind": "event", "cost": 5, "expansion": "adventures",
                        "text": "Gain a Silver per Silver you have in play. Each other player puts their -1 Card token on their deck."},
    "Seaway":          {"kind": "event", "cost": 5, "expansion": "adventures",
                        "text": "Gain an Action card costing up to $4. Move your +1 Buy token to its pile.\n(When you play a card from that pile, you first get +1 Buy.)"},
    "Trade":           {"kind": "event", "cost": 5, "expansion": "adventures",
                        "text": "Trash up to 2 cards from your hand. Gain a Silver per card you trashed."},
    "Lost Arts":       {"kind": "event", "cost": 6, "expansion": "adventures",
                        "text": "Move your +1 Action token to an Action Supply pile.\n(When you play a card from that pile, you first get +1 Action.)"},
    "Training":        {"kind": "event", "cost": 6, "expansion": "adventures",
                        "text": "Move your +$1 token to an Action Supply pile.\n(When you play a card from that pile, you first get +$1.)"},
    "Inheritance":     {"kind": "event", "cost": 7, "expansion": "adventures", "once": "game",
                        "text": "Once per game: Set aside a non-Command Action card from the Supply costing up to $4. Move your Estate token to it.\n(During your turns, Estates are also Actions that play the set-aside card, leaving it there.)"},
    "Pathfinding":     {"kind": "event", "cost": 8, "expansion": "adventures",
                        "text": "Move your +1 Card token to an Action Supply pile.\n(When you play a card from that pile, you first get +1 Card.)"},

    # --- EMPIRES: 13 Events + 21 LANDMARKS (phase 8) -------------------------
    # The first Debt-costed landscapes ({8D} Annex/Donate, {5D} Triumph,
    # {$4,3D} Wedding) and the first landmarks the game has ever dealt.
    "Advance":         {"kind": "event", "cost": 0, "expansion": "empires",
                        "text": "You may trash an Action card from your hand. If you do, gain an Action card costing up to $6."},
    "Delve":           {"kind": "event", "cost": 2, "expansion": "empires",
                        "text": "+1 Buy\nGain a Silver."},
    "Tax":             {"kind": "event", "cost": 2, "expansion": "empires",
                        "text": "Setup: Add 1 Debt to each Supply pile.\nAdd 2 Debt to a Supply pile.\nWhen a player gains a card in their Buy phase, they take the Debt from its pile."},
    "Banquet":         {"kind": "event", "cost": 3, "expansion": "empires",
                        "text": "Gain 2 Coppers and a non-Victory card costing up to $5."},
    "Ritual":          {"kind": "event", "cost": 4, "expansion": "empires",
                        "text": "Gain a Curse. If you do, trash a card from your hand. +1 VP per $1 it costs."},
    "Salt the Earth":  {"kind": "event", "cost": 4, "expansion": "empires",
                        "text": "+1 VP\nTrash a Victory card from the Supply."},
    "Windfall":        {"kind": "event", "cost": 5, "expansion": "empires",
                        "text": "If your deck and discard pile are empty, gain 3 Golds."},
    "Conquest":        {"kind": "event", "cost": 6, "expansion": "empires",
                        "text": "Gain 2 Silvers. +1 VP per Silver you've gained this turn."},
    "Dominate":        {"kind": "event", "cost": 14, "expansion": "empires",
                        "text": "Gain a Province. If you do, +9 VP."},
    "Wedding":         {"kind": "event", "cost": 4, "debt": 3, "expansion": "empires",
                        "text": "+1 VP\nGain a Gold."},
    "Triumph":         {"kind": "event", "cost": 0, "debt": 5, "expansion": "empires",
                        "text": "Gain an Estate. If you did, +1 VP per card you've gained this turn."},
    "Annex":           {"kind": "event", "cost": 0, "debt": 8, "expansion": "empires",
                        "text": "Look through your discard pile. Shuffle all but up to 5 cards from it into your deck. Gain a Duchy."},
    "Donate":          {"kind": "event", "cost": 0, "debt": 8, "expansion": "empires",
                        "text": "At the start of your next turn, before anything else, put all cards from your deck and discard pile into your hand, trash any number of them, then shuffle your hand into your deck and draw 5 cards."},

    # LANDMARKS. A Landmark is never bought — "a Landmark's ability is always
    # active for all players" — so `landmark` is not in BUYABLE_LANDSCAPE_KINDS
    # and there is no cost. Eleven of them are pure `LANDSCAPE_SCORING`
    # functions; the other ten trigger during the game, and six of those store
    # their own VP ("put 6 tokens multiplied by the number of players").
    "Aqueduct":        {"kind": "landmark", "expansion": "empires",
                        "text": "Setup: Put 8 VP on the Silver pile and 8 VP on the Gold pile.\nWhen you gain a Treasure, move 1 VP from its pile to this.\nWhen you gain a Victory card, take the VP from this."},
    "Arena":           {"kind": "landmark", "expansion": "empires",
                        "text": "Setup: Put 6 VP per player on this.\nAt the start of your Buy phase, you may discard an Action card. If you do, take 2 VP from this."},
    "Bandit Fort":     {"kind": "landmark", "expansion": "empires",
                        "text": "When scoring, -2 VP for each Silver and each Gold you have."},
    "Basilica":        {"kind": "landmark", "expansion": "empires",
                        "text": "Setup: Put 6 VP per player on this.\nWhen you gain a card in your Buy phase, if you have $2 or more, take 2 VP from this."},
    "Baths":           {"kind": "landmark", "expansion": "empires",
                        "text": "Setup: Put 6 VP per player on this.\nWhen you end your turn without having gained a card, take 2 VP from this."},
    "Battlefield":     {"kind": "landmark", "expansion": "empires",
                        "text": "Setup: Put 6 VP per player on this.\nWhen you gain a Victory card, take 2 VP from this."},
    "Colonnade":       {"kind": "landmark", "expansion": "empires",
                        "text": "Setup: Put 6 VP per player on this.\nWhen you gain an Action card in your Buy phase, if you have a copy of it in play, take 2 VP from this."},
    "Defiled Shrine":  {"kind": "landmark", "expansion": "empires",
                        "text": "Setup: Move 2 VP from here to each Action Supply pile.\nWhen you gain an Action card, move 1 VP from its pile to this.\nWhen you gain a Curse in your Buy phase, take the VP from this."},
    "Fountain":        {"kind": "landmark", "expansion": "empires",
                        "text": "When scoring, 15 VP if you have at least 10 Coppers."},
    "Keep":            {"kind": "landmark", "expansion": "empires",
                        "text": "When scoring, 5 VP per differently named Treasure you have, that you have more copies of than each other player (ties count)."},
    "Labyrinth":       {"kind": "landmark", "expansion": "empires",
                        "text": "Setup: Put 6 VP per player on this.\nWhen you gain a 2nd card in one of your turns, take 2 VP from this."},
    "Mountain Pass":   {"kind": "landmark", "expansion": "empires",
                        "text": "When you are the first player to gain a Province, each player, starting with the player to your left, bids once, up to 40 Debt, ending with you. The highest bidder gets +8 VP and takes the Debt."},
    "Museum":          {"kind": "landmark", "expansion": "empires",
                        "text": "When scoring, 2 VP per differently named card you have."},
    "Obelisk":         {"kind": "landmark", "expansion": "empires",
                        "text": "Setup: Choose a random Action Supply pile.\nWhen scoring, 2 VP per card you have from that pile."},
    "Orchard":         {"kind": "landmark", "expansion": "empires",
                        "text": "When scoring, 4 VP per differently named Action card you have 3 or more copies of."},
    "Palace":          {"kind": "landmark", "expansion": "empires",
                        "text": "When scoring, 3 VP per set of Copper-Silver-Gold you have."},
    "Tomb":            {"kind": "landmark", "expansion": "empires",
                        "text": "When you trash a card, +1 VP."},
    "Tower":           {"kind": "landmark", "expansion": "empires",
                        "text": "When scoring, 1 VP per non-Victory card you have from empty Supply piles."},
    "Triumphal Arch":  {"kind": "landmark", "expansion": "empires",
                        "text": "When scoring, 3 VP per copy you have of the 2nd most common Action card among your differently named Action cards (ties are broken favourably)."},
    "Wall":            {"kind": "landmark", "expansion": "empires",
                        "text": "When scoring, -1 VP per card you have after the first 15."},
    "Wolf Den":        {"kind": "landmark", "expansion": "empires",
                        "text": "When scoring, -3 VP per card you have exactly 1 copy of."},

    # --- RENAISSANCE: the game's first 20 PROJECTS (phase 9) -----------------
    # A Project is bought ONCE and then always on: "you activate the Project by
    # placing an unused Project cube of your player color on it. This Project's
    # ongoing ability now applies to you for the rest of the game." You get two
    # cubes and may not buy the same one twice — both are properties of the
    # KIND, enforced in `landscape_gate`, not `once` rows here.
    "Cathedral":       {"kind": "project", "cost": 3, "expansion": "renaissance",
                        "text": "At the start of your turn, trash a card from your hand."},
    "City Gate":       {"kind": "project", "cost": 3, "expansion": "renaissance",
                        "text": "At the start of your turn, +1 Card, then put a card from your hand onto your deck."},
    "Pageant":         {"kind": "project", "cost": 3, "expansion": "renaissance",
                        "text": "At the end of your Buy phase, you may pay $1 for +1 Coffers."},
    "Sewers":          {"kind": "project", "cost": 3, "expansion": "renaissance",
                        "text": "When you trash a card other than with this, you may trash a card from your hand."},
    "Star Chart":      {"kind": "project", "cost": 3, "expansion": "renaissance",
                        "text": "When shuffling, you may pick one of the cards to go on top."},
    "Exploration":     {"kind": "project", "cost": 4, "expansion": "renaissance",
                        "text": "At the end of your Buy phase, if you didn't gain any cards during it, +1 Coffers and +1 Villager."},
    "Fair":            {"kind": "project", "cost": 4, "expansion": "renaissance",
                        "text": "At the start of your turn, +1 Buy."},
    "Silos":           {"kind": "project", "cost": 4, "expansion": "renaissance",
                        "text": "At the start of your turn, discard any number of Coppers, revealed, and draw that many cards."},
    "Sinister Plot":   {"kind": "project", "cost": 4, "expansion": "renaissance",
                        "text": "At the start of your turn, add a token here, or remove your tokens here for +1 Card each."},
    "Academy":         {"kind": "project", "cost": 5, "expansion": "renaissance",
                        "text": "When you gain an Action card, +1 Villager."},
    "Capitalism":      {"kind": "project", "cost": 5, "expansion": "renaissance",
                        "text": "During your turns, Actions with +$ amounts in their text are also Treasures."},
    "Fleet":           {"kind": "project", "cost": 5, "expansion": "renaissance",
                        "text": "After the game ends, there's an extra round of turns just for players with this."},
    "Guildhall":       {"kind": "project", "cost": 5, "expansion": "renaissance",
                        "text": "When you gain a Treasure, +1 Coffers."},
    "Piazza":          {"kind": "project", "cost": 5, "expansion": "renaissance",
                        "text": "At the start of your turn, reveal the top card of your deck. If it's an Action, play it."},
    "Road Network":    {"kind": "project", "cost": 5, "expansion": "renaissance",
                        "text": "When another player gains a Victory card, +1 Card."},
    "Barracks":        {"kind": "project", "cost": 6, "expansion": "renaissance",
                        "text": "At the start of your turn, +1 Action."},
    "Crop Rotation":   {"kind": "project", "cost": 6, "expansion": "renaissance",
                        "text": "At the start of your turn, you may discard a Victory card for +2 Cards."},
    "Innovation":      {"kind": "project", "cost": 6, "expansion": "renaissance",
                        "text": "Once during each of your turns, when you gain an Action card, you may play it."},
    "Canal":           {"kind": "project", "cost": 7, "expansion": "renaissance",
                        "text": "During your turns, cards cost $1 less."},
    "Citadel":         {"kind": "project", "cost": 8, "expansion": "renaissance",
                        "text": "The first time you play an Action card during each of your turns, replay it afterwards."},

    # --- MENAGERIE: 20 Events + 20 WAYS (phase 10) ---------------------------
    # The first `way` landscapes the game has ever dealt. A WAY HAS NO COST AND
    # IS NEVER BOUGHT — `way` is not in BUYABLE_LANDSCAPE_KINDS, so the `cost`
    # below is inert and exists only because the table's shape is uniform; every
    # reader that could spend it (`landscape_gate`, `_h_buy_landscape`) refuses
    # the kind first. The dealer's `_WAY_CAP` of 1 has been in place since 6H.
    #
    # ⚠ Adding 40 landscapes to the pool RE-DEALS every existing seed's
    # landscapes: `deal_landscapes` simulates the randomizer mix literally, so
    # pool SIZE is an input. That is the ph.-9 side effect again, and it is why
    # the forced-board soaks churn on this commit.
    #
    # "Ways that refer to 'this' (Butterfly / Chameleon / Frog / Horse / Rat /
    # Turtle) refer to THE PLAYED ACTION CARD, not the Way card itself"
    # (ch. IV WAYS) — six of the twenty need the emit's subject.
    "Delay":           {"kind": "event", "cost": 0, "expansion": "menagerie",
                        "text": "You may set aside an Action card from your hand. At the start of your next turn, play it."},
    "Desperation":     {"kind": "event", "cost": 0, "expansion": "menagerie", "once": "turn",
                        "text": "Once per turn: You may gain a Curse. If you do, +1 Buy and +$2."},
    "Gamble":          {"kind": "event", "cost": 2, "expansion": "menagerie",
                        "text": "+1 Buy\nDiscard the top card of your deck. If it's an Action or Treasure, you may play it."},
    "Pursue":          {"kind": "event", "cost": 2, "expansion": "menagerie",
                        "text": "+1 Buy\nName a card. Reveal the top 4 cards from your deck. Put the matches back and discard the rest."},
    "Ride":            {"kind": "event", "cost": 2, "expansion": "menagerie",
                        "text": "Gain a Horse."},
    "Toil":            {"kind": "event", "cost": 2, "expansion": "menagerie",
                        "text": "+1 Buy\nYou may play an Action card from your hand."},
    "Enhance":         {"kind": "event", "cost": 3, "expansion": "menagerie",
                        "text": "You may trash a non-Victory card from your hand, to gain a card costing up to $2 more than it."},
    "March":           {"kind": "event", "cost": 3, "expansion": "menagerie",
                        "text": "Look through your discard pile. You may play an Action card from it."},
    "Transport":       {"kind": "event", "cost": 3, "expansion": "menagerie",
                        "text": "Choose one: Exile an Action card from the Supply; or put an Action card you have in Exile onto your deck."},
    "Banish":          {"kind": "event", "cost": 4, "expansion": "menagerie",
                        "text": "Exile any number of cards with the same name from your hand."},
    "Bargain":         {"kind": "event", "cost": 4, "expansion": "menagerie",
                        "text": "Gain a non-Victory card costing up to $5. Each other player gains a Horse."},
    "Invest":          {"kind": "event", "cost": 4, "expansion": "menagerie",
                        "text": "Exile an Action card from the Supply. While it's in Exile, when another player gains or Invests in a copy of it, +2 Cards."},
    "Seize the Day":   {"kind": "event", "cost": 4, "expansion": "menagerie", "once": "game",
                        "text": "Once per game: Take an extra turn after this one."},
    "Commerce":        {"kind": "event", "cost": 5, "expansion": "menagerie",
                        "text": "Gain a Gold per differently named card you've gained this turn."},
    "Demand":          {"kind": "event", "cost": 5, "expansion": "menagerie",
                        "text": "Gain a Horse and a card costing up to $4, both onto your deck."},
    "Stampede":        {"kind": "event", "cost": 5, "expansion": "menagerie",
                        "text": "If you have 5 or fewer cards in play, gain 5 Horses onto your deck."},
    "Reap":            {"kind": "event", "cost": 7, "expansion": "menagerie",
                        "text": "Gain a Gold, setting it aside. At the start of your next turn, play it."},
    "Enclave":         {"kind": "event", "cost": 8, "expansion": "menagerie",
                        "text": "Gain a Gold. Exile a Duchy from the Supply."},
    "Alliance":        {"kind": "event", "cost": 10, "expansion": "menagerie",
                        "text": "Gain a Province, a Duchy, an Estate, a Gold, a Silver, and a Copper."},
    "Populate":        {"kind": "event", "cost": 10, "expansion": "menagerie",
                        "text": "Gain one card from each Action Supply pile."},

    "Way of the Butterfly":  {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "You may return this to its pile to gain a card costing exactly $1 more than it."},
    "Way of the Camel":      {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "Exile a Gold from the Supply."},
    "Way of the Chameleon":  {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "Follow this card's instructions; each time that would give you +Cards this turn, you get +$ instead, and vice versa."},
    "Way of the Frog":       {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "+1 Action\nWhen you discard this from play this turn, put it onto your deck."},
    "Way of the Goat":       {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "Trash a card from your hand."},
    "Way of the Horse":      {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "+2 Cards\n+1 Action\nReturn this to its pile."},
    "Way of the Mole":       {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "+1 Action\nDiscard your hand. +3 Cards."},
    "Way of the Monkey":     {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "+1 Buy\n+$1"},
    "Way of the Mouse":      {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "Play the set-aside card, leaving it there.\nSetup: Set aside an unused non-Duration Action costing $2 or $3."},
    "Way of the Mule":       {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "+1 Action\n+$1"},
    "Way of the Otter":      {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "+2 Cards"},
    "Way of the Ox":         {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "+2 Actions"},
    "Way of the Owl":        {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "Draw until you have 6 cards in hand."},
    "Way of the Pig":        {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "+1 Card\n+1 Action"},
    "Way of the Rat":        {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "You may discard a Treasure to gain a copy of this."},
    "Way of the Seal":       {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "+$1\nThis turn, when you gain a card, you may put it onto your deck."},
    "Way of the Sheep":      {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "+$2"},
    "Way of the Squirrel":   {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "+2 Cards at the end of this turn."},
    "Way of the Turtle":     {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "Set this aside. If you did, play it at the start of your next turn."},
    "Way of the Worm":       {"kind": "way", "cost": 0, "expansion": "menagerie",
                        "text": "Exile an Estate from the Supply."},
}


def landscape_pool(expansions):
    """Sorted landscape names belonging to the enabled expansions — the deck the
    setup dealer shuffles in with the Kingdom randomizers."""
    exps = set(expansions or ())
    return sorted(n for n, d in LANDSCAPES.items() if d["expansion"] in exps)


def landscape_kind(name):
    return LANDSCAPES[name]["kind"] if name in LANDSCAPES else None


# --- ARTIFACTS (phase 9) ------------------------------------------------------
#
# AN ARTIFACT IS NOT A CARD AND NOT A LANDSCAPE, so it gets its own table — the
# 6H lesson a third time. It has one copy, is never gained, bought or dealt,
# never sits in a zone, and "State and Artifact cards never belong to any player
# and are never considered to be in play" (compendium p35). A CARDS entry would
# hand it a cost and a kingdom flag that lie; a LANDSCAPES entry would put it in
# the randomizer deal. `by` is the kingdom card whose SETUP brings it: "If the
# following cards are in the game, keep these Artifact cards available"
# (SPECIAL SETUP: RENAISSANCE) — and a Bane or Ferryman pile is in the game.
ARTIFACTS = {
    "Flag":           {"by": "Flag Bearer", "expansion": "renaissance",
                       "text": "When drawing your hand, +1 Card."},
    "Horn":           {"by": "Border Guard", "expansion": "renaissance",
                       "text": "Once per turn, when you discard a Border Guard from play, you may put it onto your deck."},
    "Key":            {"by": "Treasurer", "expansion": "renaissance",
                       "text": "At the start of your turn, +$1."},
    "Lantern":        {"by": "Border Guard", "expansion": "renaissance",
                       "text": "Border Guards you play reveal 3 cards and discard 2. (It takes all 3 being Actions to take the Horn.)"},
    "Treasure Chest": {"by": "Swashbuckler", "expansion": "renaissance",
                       "text": "At the start of your Buy phase, gain a Gold."},
}


# MENAGERIE (ph. 10): the Horse pile is 30 cards and sits OUTSIDE the Supply
# ("include the Horse pile (30 cards) outside the Supply"), so it is never
# buyable and never counts toward the three-empty-piles game end.
HORSE_PILE = 30


def uses_horses(name):
    """Does this card's setup bring the Horse pile? Read off the printed text
    rather than a hand-kept list — every Horse producer says "Horse" in it, and
    a list would be one more place to forget a card.

    `name` may be a CARD or a LANDSCAPE: the setup line says "if any cards
    referring to Horses are used", and four Events gain Horses. Reading the
    TEXT and not the name is what correctly excludes **Way of the Horse**,
    which needs no Horse pile: its "Return this to its pile" returns the played
    Action card to ITS own pile, and "this" on a Way means the played card
    (ch. IV WAYS), never the Way."""
    d = CARDS.get(name) or LANDSCAPES.get(name)
    return bool(d) and "Horse" in d["text"] and name != "Horse"


def artifacts_for(in_play_cards):
    """The artifacts a game must keep available, given the cards in the game
    (the dealt kingdom plus any setup-chosen extra pile)."""
    have = set(in_play_cards)
    return sorted(a for a, d in ARTIFACTS.items() if d["by"] in have)


# Cards we have deliberately NOT implemented, and why. This is a real roster
# hole, so it is DATA rather than a comment: `test_cards.py` asserts the set's
# published size equals what we ship plus what is listed here, so the omission
# cannot be quietly forgotten — and the day one is built, the test tells you to
# delete its row.
DEFERRED = {
    "Possession": (
        "Alchemy. One player takes a turn that another player CONTROLS: the "
        "possessor makes every decision, gains every card the possessed player "
        "would gain, takes their VP tokens, and their trashed cards are set "
        "aside and returned. That is ~10 kernel seams, two of them "
        "security-adjacent (the move gate and per-recipient redaction), which "
        "is why the roadmap sizes it as a kernel system rather than a card. "
        "Scoped in .claude-plans/dontminion-phase5-alchemy-possession-scope.md "
        "— including a design that adds a `controller_of` indirection instead "
        "of relaxing the WS seat binding."),
}


KINGDOM = {
    "base": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "base"],
    "intrigue": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "intrigue"],
    "seaside": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "seaside"],
    "prosperity": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "prosperity"],
    "hinterlands": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "hinterlands"],
    "cornucopia": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "cornucopia"],
    "alchemy": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "alchemy"],
    # Dark Ages deals 35 piles: the 34 ordinary kingdom cards plus KNIGHTS,
    # which is a pile name rather than a card (see PILES).
    "darkages": ([n for n, c in CARDS.items()
                  if c["kingdom"] and c["expansion"] == "darkages"]
                 + [p for p, d in PILES.items()
                    if d["kingdom"] and d["expansion"] == "darkages"]),
    "adventures": [n for n, c in CARDS.items()
                   if c["kingdom"] and c["expansion"] == "adventures"],
    # Empires deals 24 piles: 18 ordinary kingdom cards plus the six piles
    # whose name is not a card — the five splits and Castles (see PILES).
    "empires": ([n for n, c in CARDS.items()
                 if c["kingdom"] and c["expansion"] == "empires"]
                + [p for p, d in PILES.items()
                   if d["kingdom"] and d["expansion"] == "empires"]),
    "renaissance": [n for n, c in CARDS.items()
                    if c["kingdom"] and c["expansion"] == "renaissance"],
    # Menagerie deals 30 kingdom piles; Horse is a card of the set but sits
    # outside the Supply (kingdom=False), so it is excluded by construction.
    "menagerie": [n for n, c in CARDS.items()
                  if c["kingdom"] and c["expansion"] == "menagerie"],
}


# CAPITALISM (ph. 9): "During your turns, Actions with +$ amounts in their text
# are also Treasures." The membership test is LITERAL — the card's text carrying
# "+$" with the plus ("It doesn't change a card that has just $ amounts without
# the + … It also changes Teacher", whose text names the +$1 token) — so the set
# is DERIVED from the text field over the whole catalogue: the rule reaches
# every set in the game, not just Renaissance. Derived once at import; the
# derivation is pinned by an explicit-list test (the ph.-7 REVIEWED lesson: a
# guard rebuilt from the thing it checks can never fail), so a future card's
# membership is a visible decision, not a regex accident.
CAPITALISM_CARDS = frozenset(
    n for n, c in CARDS.items() if "action" in c["types"] and "+$" in c["text"])


def expansion_of(name):
    """Which set a kingdom-list entry belongs to — a CARD or a PILE name."""
    if name in CARDS:
        return CARDS[name]["expansion"]
    return PILES[name]["expansion"] if name in PILES else None


def printed_cost(name):
    """The printed COIN cost of a kingdom-list entry — a CARD or a PILE name.

    A split/shuffled pile's cost "follows the Randomizer card" (compendium,
    SPLIT PILES: PILE TYPE AND COST), which is what the setup rules that pick a
    pile by cost (Young Witch's Bane, Ferryman's extra pile) have to read. This
    is SETUP data: in play, a pile costs what its top card costs, which is
    engine.cost's job."""
    if name in CARDS:
        return CARDS[name]["cost"]
    return PILES[name]["cost"] if name in PILES else None


def overpays(name):
    """Does buying this card let you pay MORE than its cost? (The `$N+` cost.)"""
    return bool(CARDS[name].get("overpay"))


def potion_of(name):
    """The POTION component of a card's printed cost (Alchemy). Cards without
    one cost {$N, 0 Potions}, which is what makes "up to $N" exclude every
    Potion card — see engine.cost_le."""
    return CARDS[name].get("potion", 0)


def debt_of(name):
    """The DEBT component of a card's printed cost (Empires). "Debt functions
    like another kind of cost, just like Potion" (DEBT § IV), so a printed cost
    of {4D} is {$0, 0 Potions, 4 Debt} and an ordinary card is {$N, 0, 0}."""
    return CARDS[name].get("debt", 0)


def landscape_debt(name):
    """The DEBT component of a LANDSCAPE's printed cost — Empires' Debt-costed
    Events (Triumph, Annex, Ritual). A sibling of `landscape_cost` rather than a
    vector return, because a landscape's price is the PRINTED one and never
    passes through engine.cost() (p32: "its cost cannot be changed by cards like
    Bridge"), so the two components never travel together."""
    return LANDSCAPES[name].get("debt", 0)


# --- kingdom REQUIREMENTS (create-time "at least one card that gives ...") ----
#
# DERIVED FROM CARD TEXT, on purpose: a new expansion's villages and smithies
# join these pools the day the set ships, the way KINGDOM above derives its
# lists. `REQUIREMENT_ORDER` fixes the order the dealer honours them in so the
# deal stays reproducible from (seed, options).
#
# The bar is the PRINTED bonus — "+2 Actions" and up, "+1 Buy" and up, "+2
# Cards" and up. That deliberately EXCLUDES variable and draw-to-X cards:
# Cellar ("discard any number, draw that many") and Library ("draw until you
# have 7") are real draw, but a player who asks to be guaranteed a drawer wants
# a Smithy, and counting a sifter would let the requirement be satisfied by a
# card that doesn't satisfy it. Being narrow only ever adds a card the player
# asked for; being broad breaks the guarantee. Multipliers (Throne Room) are
# out of the Actions pool for the same reason — they play an Action twice, they
# do not give you an extra Action.
REQUIREMENTS = {
    "actions": {"label": "+2 Actions", "word": "Action", "min": 2},
    "buys": {"label": "+1 Buy", "word": "Buy", "min": 1},
    "draw": {"label": "+2 Cards", "word": "Card", "min": 2},
}
REQUIREMENT_ORDER = ("actions", "buys", "draw")


# A CALL ability is not a play ability, so its bonuses don't count toward a
# requirement. Adventures' Coin of the Realm is the case: it prints "+2
# Actions", but only when you CALL it off the Tavern mat, having played it as a
# Treasure — a player who asked to be guaranteed a village would be handed one
# that is not a village at all. Same principle as excluding Throne Room from
# the Actions pool: being narrow only ever adds a card the player asked for.
_CALL_CLAUSE = re.compile(r"[^.\n]*\bcall this\b[^.\n]*[.\n]?", re.I)


def _printed_bonus(text, word):
    """The largest printed "+N <word>s" a card gives when PLAYED (0 if none).

    A **"per" clause does not count** — "+1 Buy per empty Supply pile" (Animal
    Fair) is $0 on a fresh board, and a guarantee that can be zero is not a
    guarantee. Same principle as excluding draw-to-X: being narrow only ever
    adds a card the player asked for; being broad lets the promise be satisfied
    by a card that does not keep it. Menagerie is where this first bites — the
    eight earlier "+N X per" cards all print the clause BELOW their bar
    (Cellar, Crossroads, Paddock…), so the lookahead changes exactly one
    classification and no shipped board's deal."""
    return max([int(n) for n in
                re.findall(rf"\+(\d+) {word}s?\b(?! per\b)",
                           _CALL_CLAUSE.sub("", text))]
               or [0])


def grants(name, requirement):
    """Does `name` satisfy the named kingdom requirement?

    A PILE name never does: only its top card is available, so a Knights pile
    cannot promise the +2 Actions that one Dame Molly deep inside it prints.
    (It is also not a card, so there is no text to read.)"""
    if name not in CARDS:
        return False
    spec = REQUIREMENTS[requirement]
    return _printed_bonus(CARDS[name]["text"], spec["word"]) >= spec["min"]


def cards_granting(requirement, pool=None):
    """Sorted kingdom cards satisfying `requirement` (within `pool` if given)."""
    names = sorted(pool) if pool is not None else sorted(
        n for n, c in CARDS.items() if c["kingdom"])
    return [n for n in names if grants(n, requirement)]


def pile_size(name, n_players):
    """Supply pile size for a card, by player count (2-4)."""
    if name == "Castles":
        # "In a 2-player game, use one of each of the 8 unique cards" —
        # otherwise two of each. The only pile whose SIZE varies with the
        # player count without its contents being a straight multiple.
        return len(CASTLES) * (1 if n_players == 2 else 2)
    if name in PILES:
        return PILES[name]["size"]        # Knights: one shuffled pile of 10
    card = CARDS[name]
    if name == "Rats":
        return 20                         # "If Rats is in the Supply, use all 20"
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
    if name == "Potion":
        return 16                     # "include the 16 Potion cards" 
    if "victory" in card["types"]:
        return 8 if n_players == 2 else 12   # includes Colony (8 at 2p)
    return 10
