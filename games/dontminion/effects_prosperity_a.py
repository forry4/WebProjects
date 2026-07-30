"""Prosperity-2E card effects, batch A (WP-prosperity-a).

Owns: Anvil, Bank, Bishop, City, Expand, Forge, Grand Market, Monument,
Quarry, Rabble, Vault, War Chest, Worker's Village.

See effects_core.py for the EFFECTS/STAGES contract. Prosperity notes:
  * VP tokens go through E.add_vp_tokens (public, monotone, scored at over).
  * ALL cost comparisons go through E.cost / E.cost_le / E.cost_eq; all type
    and coin queries through E.has_type / E.coins_of (Charlatan's
    Curse-is-a-Treasure rule lives behind those, never in card code).
  * Quarry's discount is TURN-scoped (2022): the effect only bumps
    turn_ctx["quarries"]; engine.cost applies -$2/Action per count, so the
    discount survives the Quarry leaving play.
  * Interactive treasures (Anvil, War Chest) are exported in MANUAL_TREASURES
    so play_all_treasures skips them; Grand Market's no-Coppers rule is a
    BUY_GATES entry (buying only — gaining bypasses it, kernel-enforced).
"""

from . import engine as E


# --- Anvil (Treasure $1, manual) ---------------------------------------------
# Kernel banks the printed $1 first; the optional discard-for-gain runs here.
# No discard -> no gain ("do X to Y").

def _anvil(game, pid):
    hand = game["seats"][pid]["hand"]
    treasures = [c for c in hand if E.has_type(game, c, "treasure")]
    if treasures:
        E.push_choose_cards(game, pid, "Anvil", "discard",
                            cards=treasures, mn=0, mx=1, purpose="discard")


def _anvil_discard(game, pid, frame, choice):
    if not choice["cards"]:
        return                          # declined the discard -> no gain
    E.discard(game, pid, choice["cards"])
    piles = sorted(p for p in game["supply"]
                   if game["supply"][p] > 0 and E.cost_le(game, p, 4))
    if piles:
        E.push_choose_pile(game, pid, "Anvil", "gain", piles)


def _anvil_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Bank (Treasure, $0 printed) ---------------------------------------------
# +$1 per Treasure IN PLAY counting itself: in_play (Bank is already there
# when the effect runs) plus persisting duration-zone cards and their riders.

def _bank(game, pid):
    seat = game["seats"][pid]
    on_table = list(seat["in_play"])
    for e in seat.get("duration", []):
        on_table.append(e["card"])
        on_table.extend(e.get("riders", []))
    E.add_coins(game, sum(1 for c in on_table if E.has_type(game, c, "treasure")))


# --- Bishop ------------------------------------------------------------------
# +$1 +1VP; own trash MANDATORY when hand non-empty, +1 VP per $2 of the
# trashed card's CURRENT cost (Quarry/Bridge reduce the payout); THEN each
# other player MAY trash one (not an attack — no Moat window), in turn order.

def _bishop(game, pid):
    E.add_coins(game, 1)
    E.add_vp_tokens(game, pid, 1)
    # LIFO: push the last opponent first, own trash last (on top), so the
    # resolution order is own trash, then opponents in turn order.
    for o in reversed(E.opponents(game, pid)):
        opp_hand = game["seats"][o]["hand"]
        if opp_hand:
            E.push_choose_cards(game, o, "Bishop", "opp_trash",
                                cards=list(opp_hand), mn=0, mx=1, purpose="trash")
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Bishop", "trash",
                            cards=list(hand), mn=1, mx=1, purpose="trash")


def _bishop_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    E.trash(game, pid, [card])
    # cost read AT TRASH TIME — cost reduction lowers the payout (compendium)
    E.add_vp_tokens(game, pid, E.cost(game, card) // 2)


def _bishop_opp_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, choice["cards"])   # no VP for opponents


# --- City --------------------------------------------------------------------
# Empty-pile count evaluated ONCE at play time (effects are immediate).

def _city(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 2)
    empty = E.count_empty_piles(game)
    if empty >= 1:
        E.draw(game, pid, 1)
    if empty >= 2:
        E.add_buys(game, 1)
        E.add_coins(game, 1)


# --- Expand ------------------------------------------------------------------

def _expand(game, pid):
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Expand", "trash",
                            cards=list(hand), mn=1, mx=1, purpose="trash")


def _expand_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    E.trash(game, pid, [card])
    cap = E.cost(game, card) + 3
    piles = sorted(p for p in game["supply"]
                   if game["supply"][p] > 0 and E.cost_le(game, p, cap))
    if piles:
        E.push_choose_pile(game, pid, "Expand", "gain", piles)


def _expand_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Forge -------------------------------------------------------------------
# Trash ANY number (one trash event); gain EXACTLY the total (empty set = $0,
# so a Copper/Curse). No matching non-empty pile -> gain nothing, but the
# trashing still happened (compendium ruling).

def _forge_offer_gain(game, pid, total):
    piles = sorted(p for p in game["supply"]
                   if game["supply"][p] > 0 and E.cost_eq(game, p, total))
    if piles:
        E.push_choose_pile(game, pid, "Forge", "gain", piles)


def _forge(game, pid):
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Forge", "trash",
                            cards=list(hand), mn=0, mx=len(hand), purpose="trash")
    else:
        _forge_offer_gain(game, pid, 0)   # sum of the empty set is $0


def _forge_trash(game, pid, frame, choice):
    E.trash(game, pid, choice["cards"])
    # costs read AT TRASH TIME — cost reduction shrinks the total
    _forge_offer_gain(game, pid, sum(E.cost(game, c) for c in choice["cards"]))


def _forge_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Grand Market ------------------------------------------------------------
# Vanilla super-Peddler; the no-Coppers rule binds BUYING only (BUY_GATES —
# the kernel consults it in the buy handler and legal_moves; gains bypass it).

def _grand_market(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_buys(game, 1)
    E.add_coins(game, 2)


def _grand_market_gate(game, pid):
    if "Copper" in game["seats"][pid]["in_play"]:
        return "can't buy Grand Market with Coppers in play"
    return None


# --- Monument ----------------------------------------------------------------

def _monument(game, pid):
    E.add_coins(game, 2)
    E.add_vp_tokens(game, pid, 1)


# --- Quarry (Treasure $1) ----------------------------------------------------
# 2022 semantics: playing Quarry sets up a TURN-scoped -$2 on Actions.
# engine.cost applies the counter, so the discount survives the Quarry being
# trashed from play and stacks per play.

def _quarry(game, pid):
    game["turn_ctx"]["quarries"] = game["turn_ctx"].get("quarries", 0) + 1


# --- Rabble ------------------------------------------------------------------
# +3 Cards; per opponent (standard attack window applies): reveal top 3,
# discard every Action/Treasure, the rest go back in the OWNER's order.

def _rabble(game, pid):
    E.draw(game, pid, 3)
    E.attack_opponents(game, pid, "Rabble", "hit")


def _rabble_hit(game, pid, frame, choice):
    looked = E.look_top(game, pid, 3)
    if not looked:
        return
    E.reveal(game, pid, looked, "deck")
    hits = [c for c in looked
            if E.has_type(game, c, "action") or E.has_type(game, c, "treasure")]
    rest = list(looked)
    for c in hits:
        rest.remove(c)
    if hits:
        E.discard(game, pid, hits, zone="aside", public=True)
    if len(rest) >= 2:
        E.push_order_cards(game, pid, "Rabble", "order", cards=rest)
    else:
        E.deck_from_aside(game, pid, rest)


def _rabble_order(game, pid, frame, choice):
    E.deck_from_aside(game, pid, choice["order"])   # order[0] ends up on top


# --- Vault -------------------------------------------------------------------
# +2 Cards; discard any number for +$1 each; THEN each other player may
# discard EXACTLY 2 to draw 1 (both discards required — a 0/1-card hand
# can't do it at all; not an attack).

def _vault(game, pid):
    E.draw(game, pid, 2)
    for o in reversed(E.opponents(game, pid)):
        if len(game["seats"][o]["hand"]) >= 2:
            E.push_choose_option(game, o, "Vault", "opp_opt",
                                 options=[{"id": "discard", "label": "Discard 2 cards to draw 1"},
                                          {"id": "decline", "label": "Don't discard"}])
    hand = game["seats"][pid]["hand"]
    if hand:
        E.push_choose_cards(game, pid, "Vault", "discard",
                            cards=list(hand), mn=0, mx=len(hand), purpose="discard")


def _vault_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])
    E.add_coins(game, len(choice["cards"]))


def _vault_opp_opt(game, pid, frame, choice):
    if choice["ids"][0] != "discard":
        return
    hand = game["seats"][pid]["hand"]
    E.push_choose_cards(game, pid, "Vault", "opp_discard",
                        cards=list(hand), mn=2, mx=2, purpose="discard")


def _vault_opp_discard(game, pid, frame, choice):
    E.discard(game, pid, choice["cards"])
    E.draw(game, pid, 1)


# --- War Chest (Treasure $0, manual) -----------------------------------------
# The player to your LEFT names a card; you gain a non-empty pile costing up
# to $5 that hasn't been named for War Chests THIS TURN (the list accumulates
# per play — turn_ctx["war_chest_names"]).

def _war_chest(game, pid):
    left = E.opponents(game, pid)[0]     # next player in turn order
    E.push_name_card(game, left, "War Chest", "named", data={"owner": pid})


def _war_chest_named(game, pid, frame, choice):
    owner = frame["data"]["owner"]
    named = game["turn_ctx"].setdefault("war_chest_names", [])
    named.append(choice["card"])         # the name lands BEFORE the gain
    piles = sorted(p for p in game["supply"]
                   if game["supply"][p] > 0 and E.cost_le(game, p, 5)
                   and p not in named)
    if piles:
        E.push_choose_pile(game, owner, "War Chest", "gain", piles)


def _war_chest_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Worker's Village --------------------------------------------------------

def _workers_village(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 2)
    E.add_buys(game, 1)


EFFECTS = {
    "Anvil": _anvil,
    "Bank": _bank,
    "Bishop": _bishop,
    "City": _city,
    "Expand": _expand,
    "Forge": _forge,
    "Grand Market": _grand_market,
    "Monument": _monument,
    "Quarry": _quarry,
    "Rabble": _rabble,
    "Vault": _vault,
    "War Chest": _war_chest,
    "Worker's Village": _workers_village,
}

STAGES = {
    ("Anvil", "discard"): _anvil_discard,
    ("Anvil", "gain"): _anvil_gain,
    ("Bishop", "trash"): _bishop_trash,
    ("Bishop", "opp_trash"): _bishop_opp_trash,
    ("Expand", "trash"): _expand_trash,
    ("Expand", "gain"): _expand_gain,
    ("Forge", "trash"): _forge_trash,
    ("Forge", "gain"): _forge_gain,
    ("Rabble", "hit"): _rabble_hit,
    ("Rabble", "order"): _rabble_order,
    ("Vault", "discard"): _vault_discard,
    ("Vault", "opp_opt"): _vault_opp_opt,
    ("Vault", "opp_discard"): _vault_opp_discard,
    ("War Chest", "named"): _war_chest_named,
    ("War Chest", "gain"): _war_chest_gain,
}

BUY_GATES = {
    "Grand Market": _grand_market_gate,
}

MANUAL_TREASURES = {"Anvil", "War Chest"}
