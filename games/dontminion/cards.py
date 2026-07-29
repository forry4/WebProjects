"""Dontminion static card data (Dominion Base 2E + Intrigue 2E) — the full 59-card dataset.

Verified against the Knutsen compendium (Dominion_CompleteRules_v11.1.pdf: ch. V editions/
errata p37-38 + ch. VII Card Reference) and the dominionstrategy.com card-list pages for
Base 2E and Intrigue 2E (see .claude-plans/i-want-to-add-luminous-pebble.md par.2/par.5/par.9).
Texts are the CURRENT card versions: ch. V lists Masquerade, Mine, Moneylender and Throne Room
as functionally changed post-2016; their entries' "Current (2016) version" notes are reflected
here. (Compendium trivia, no effect on us: Harem was renamed "Farm" in 2023 printings; the 2E
roster name Harem is kept.)

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
                 "text": "+1 Action\nDiscard any number of cards, then draw that many.",
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
    "Harem":    {"cost": 6, "types": ["treasure", "victory"], "coins": 2, "vp": 2,
                 "text": "$2\n2 VP", "expansion": "intrigue", "kingdom": True},
    "Nobles":   {"cost": 6, "types": ["action", "victory"], "coins": 0, "vp": 2,
                 "text": "Choose one: +3 Cards; or +2 Actions.\n2 VP",
                 "expansion": "intrigue", "kingdom": True},
}

KINGDOM = {
    "base": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "base"],
    "intrigue": [n for n, c in CARDS.items() if c["kingdom"] and c["expansion"] == "intrigue"],
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
    if "victory" in card["types"]:
        return 8 if n_players == 2 else 12
    return 10
