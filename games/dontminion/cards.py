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
PILES = {
    "Knights": {"cost": 5, "expansion": "darkages", "kingdom": True,
                "members": KNIGHTS, "size": len(KNIGHTS)},
}


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
#   LANDSCAPES[name] = {"kind": ..., "cost": int, "text": str, "expansion": str}
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
}


def landscape_pool(expansions):
    """Sorted landscape names belonging to the enabled expansions — the deck the
    setup dealer shuffles in with the Kingdom randomizers."""
    exps = set(expansions or ())
    return sorted(n for n, d in LANDSCAPES.items() if d["expansion"] in exps)


def landscape_kind(name):
    return LANDSCAPES[name]["kind"] if name in LANDSCAPES else None


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
}


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
    """The largest printed "+N <word>s" a card gives when PLAYED (0 if none)."""
    return max([int(n) for n in
                re.findall(rf"\+(\d+) {word}s?\b", _CALL_CLAUSE.sub("", text))]
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
