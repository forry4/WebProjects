"""Cornucopia & Guilds 2E card effects — 26 kingdom cards + the 6 Rewards.

Merged from the two batch halves; the per-card notes from each are kept
verbatim below. Registry entries are UNIONED, never re-assigned.

The 2024 Second Edition is a COMBINED set. The 13 removed cards (Doctor,
Farming Village, Fortune Teller, Harvest, Horse Traders, Masterpiece, Taxman,
Tournament, and the 5 Prizes) are deliberately absent — the roster was verified
twice, by the compendium's 13 "Not included in the 2024 Second Edition" markers
and the wiki chart's "Cornucopia & Guilds, 1E" label, which name the same 13.

=== batch A notes ===
Advisor, Baker, Candlestick Maker, Carnival, Fairgrounds, Hamlet, Hunting
Party, Joust, Menagerie, Merchant Guild, Plaza, Remake, Shop, Soothsayer, and
the Rewards Courser, Demesne, Housecarl, Huge Turnip, Renown.

  * DIFFERENTLY NAMED CARDS is this set's signature and there is exactly ONE
    helper for it (`_distinct`), not seven copies. Carnival, Fairgrounds,
    Horn of Plenty, Housecarl, Hunting Party, Menagerie and Shop all count by
    NAME; Fairgrounds' and Demesne's counts live in engine._vp_of, because
    scoring reads the whole deck rather than a zone.
  * CARDS YOU HAVE IN PLAY (Horn of Plenty, Housecarl, Shop) is in_play PLUS
    the duration zone's cards PLUS their riders — the Bank walk. Reading only
    in_play would silently under-count on any board with a Duration.
  * RENOWN IS BRIDGE, not a while-in-play modifier: "This turn, cards cost $2
    less", cumulative per play, so it increments the existing
    turn_ctx["bridges"] by 2 rather than adding a COST_MODS entry. Same
    decision, and the same reasoning, as Highway in ph. 3 — being turn-scoped
    is what makes the discount survive the card leaving play.
  * ADVISOR is decided by an OPPONENT on your turn: the reveal is yours, the
    choice belongs to "the player to your left" (opponents(pid)[0], since
    `opponents` returns turn order starting after pid), and the discard is
    still yours. Not an attack — no reaction window opens.
  * MERCHANT GUILD is the 2022 rewrite: a per-play until="turn_end" watcher on
    buy_phase_end (Hoard's exact shape), paying +1 Coffers per card GAINED in
    that Buy phase — all gains, not just buys, including ones from before it
    was played. It was changed precisely so the tokens arrive too late to
    spend that turn, which only works because they land at end of buy phase.
  * JOUST sets the Province aside into `cleanup_aside`, NOT into play and not
    into the discard: "Discard the Province in Clean-up". A Province sitting in
    play would wrongly feed Horn of Plenty and Shop.

=== batch B notes ===
Butcher, Coronet, Farmhands, Farrier, Ferryman, Footpad, Herald, Horn of
Plenty, Infirmary, Jester, Journeyman, Stonemason, Young Witch.

The half that owns OVERPAY, Coffers-spending, and the two setup-chosen piles.

  * OVERPAY IS A WHEN-GAIN ABILITY (2022 retiming). All four overpay cards
    register `on="gain", from="self"` and read `ctx["overpay"]` — the amount
    rides the gain event, because the money was already paid by the kernel
    when the card was bought. This is why Herald may pick the Herald itself
    out of the discard pile, and why Infirmary plays a card that is already
    gained. Pre-2022 it was a when-buy ability; the compendium's older
    examples describe that version and do not apply.
  * BUTCHER'S SPENT COFFERS STILL PAY. Spending a Coffers is defined globally
    as "+$1 and immediately removed"; Butcher only adds a use for the COUNT.
    So its spend goes through the same accounting as the spend move. Recorded
    as an open ambiguity in CLAUDE.md — the compendium's phrasing ("tokens you
    don't use to remodel a card, you save for later to spend for +$ as normal")
    can be read either way, and we took the branch that keeps one rule for
    spending rather than two.
  * FARMHANDS is the reason the kernel grew per-seat start-of-turn abilities.
    Its set-aside is NOT a Duration — the Farmhands itself goes to the discard
    — so there is nothing on the table to hang a duration fx off. It also
    fires when you gain a Farmhands on an OPPONENT's turn, and a Farmhands
    gained to hand may set ITSELF aside.
  * FOOTPAD's second ability binds the whole GAME, not its owner: "in games
    using this, when you gain a card in an Action phase, +1 Card" — every
    player, in anyone's Action phase, whether or not they own a copy. That is
    the trigger bus' new `from="game"` source, keyed on the KINGDOM. It is on
    the bus rather than a game-dict flag (Charlatan's shape) because it has to
    resolve in the player's chosen order against the other abilities the same
    gain triggered.
  * YOUNG WITCH's Bane and FERRYMAN's extra pile are both chosen at SETUP from
    the kingdom cards this game did not deal (engine.new_game). The Bane joins
    the Supply; Ferryman's pile does not, so it is only reachable through
    Ferryman — which is exactly what ph. 3H's non-supply piles are for.
    "Bane" is not a type: it is whichever pile `game["bane"]` names.
  * YOUNG WITCH's order is load-bearing: reactions resolve first, THEN you draw
    2 and discard 2, THEN opponents may reveal a Bane. A Bane that is itself a
    Reaction has to be in hand at that last point, so the attack half runs from
    a later stage and must capture the immune set at play time (the
    Minion/Replace rule).
  * INFIRMARY plays ITSELF from the discard pile after overpaying, once per $1.
    Each play draws and then optionally trashes, resolved in turn. The
    lose-track guard is real: Watchtower may have moved it first.

The EFFECTS/STAGES contract lives in games/dontminion/CLAUDE.md (the frozen
engine API); card code touches the game ONLY through the engine helpers.
"""

from . import engine as E


# ── shared helpers ───────────────────────────────────────────────────────────

def _distinct(cards):
    """How many DIFFERENTLY NAMED cards are in a list. The set's signature
    count — one implementation, seven consumers."""
    return len(set(cards))


def _on_table(game, pid):
    """CARDS YOU HAVE IN PLAY: in_play plus the persisting duration cards and
    their throne-room riders (the Bank walk). Horn of Plenty, Housecarl and
    Shop all read this, never `in_play` alone."""
    seat = game["seats"][pid]
    out = list(seat["in_play"])
    for e in seat["duration"]:
        out.append(e["card"])
        out.extend(e.get("riders", []))
    return out


def _piles(game, pred=None):
    """Non-empty SUPPLY piles, deterministically ordered. Non-supply piles
    (the Rewards, Ferryman's pile) are not in this dict by construction, so
    "gain a card costing up to $N" can never reach them."""
    return [p for p in sorted(game["supply"])
            if game["supply"][p] > 0 and (pred is None or pred(p))]


def _first_of_each(cards):
    """One of each differently named card, keeping the order they came in."""
    seen, out = set(), []
    for c in cards:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


# ── batch A ──────────────────────────────────────────────────────────────────

# --- Advisor -----------------------------------------------------------------
# +1 Action, reveal 3, THE PLAYER TO YOUR LEFT chooses one, you discard that and
# take the rest. GET FROM DECK, THEN DISCARD. Not an attack: no reaction window.

def _advisor(game, pid):
    E.add_actions(game, 1)
    seen = E.look_top(game, pid, 3)
    if not seen:
        return
    E.reveal(game, pid, seen, "deck")
    left = E.opponents(game, pid)[0]      # turn order starting after pid
    E.push_choose_cards(game, left, "Advisor", "pick", seen, 1, 1,
                        "choose a card for the Advisor player to discard",
                        data={"owner": pid, "seen": list(seen)})


def _advisor_pick(game, left, frame, choice):
    owner = frame["data"]["owner"]
    picked = list(choice["cards"])
    rest = list(frame["data"]["seen"])
    for c in picked:
        rest.remove(c)
    E.discard(game, owner, picked, zone="aside", public=True)
    E.take_aside(game, owner, rest, dest="hand")


# --- Baker -------------------------------------------------------------------
# +1 Card +1 Action +1 Coffers. Its SETUP ("each player gets +1 Coffers") is in
# engine.new_game — it happens before anyone plays anything.

def _baker(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_coffers(game, 1)


# --- Candlestick Maker -------------------------------------------------------

def _candlestick_maker(game, pid):
    E.add_actions(game, 1)
    E.add_buys(game, 1)
    E.add_coffers(game, 1)


# --- Carnival ----------------------------------------------------------------
# Reveal 4; put ONE OF EACH differently named card into your hand, discard the
# rest. No choice anywhere: "if several cards with the same name are revealed,
# discard all but one of these". Fewer than 4 to reveal: take what there is.

def _carnival(game, pid):
    seen = E.look_top(game, pid, 4)
    if not seen:
        return
    E.reveal(game, pid, seen, "deck")
    keep = _first_of_each(seen)
    rest = list(seen)
    for c in keep:
        rest.remove(c)
    E.take_aside(game, pid, keep, dest="hand")
    if rest:
        E.discard(game, pid, rest, zone="aside", public=True)


# --- Fairgrounds -------------------------------------------------------------
# Pure Victory: 2 VP per 5 differently named cards you have. Scored in
# engine._vp_of ("fairgrounds"), which counts the WHOLE deck — no play ability,
# so no EFFECTS entry.


# --- Hamlet ------------------------------------------------------------------
# +1 Card +1 Action, then two INDEPENDENT optional discards: one for +1 Action,
# one for +1 Buy. "DO X FOR" — each discard is separately optional and each pays
# only if you actually discarded.

def _hamlet(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    _hamlet_offer(game, pid, "action")


def _hamlet_offer(game, pid, kind):
    """The two offers are SEQUENTIAL, not both pushed up front. Pushing both
    would snapshot the hand twice before either resolved, so answering the
    first with a discard left the second offering a card that had already
    left the hand — a decision the engine would then fail to apply."""
    hand = game["seats"][pid]["hand"]
    if not hand:
        return
    E.push_choose_cards(game, pid, "Hamlet", "discard", sorted(hand), 0, 1,
                        f"discard a card for +1 {kind.capitalize()}",
                        data={"kind": kind})


def _hamlet_discard(game, pid, frame, choice):
    picked = list(choice["cards"])
    kind = frame["data"]["kind"]
    if picked:
        E.discard(game, pid, picked)
        if kind == "action":
            E.add_actions(game, 1)
        else:
            E.add_buys(game, 1)
    if kind == "action":
        _hamlet_offer(game, pid, "buy")


# --- Hunting Party -----------------------------------------------------------
# +1 Card +1 Action, reveal your hand, then DIG FOR a card differently named
# from every card in hand. Everything else revealed is discarded.

def _hunting_party(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    seat = game["seats"][pid]
    E.reveal(game, pid, sorted(seat["hand"]), "hand")
    names = set(seat["hand"])
    found = None
    while True:
        got = E.look_top(game, pid, 1)
        if not got:
            break                                  # deck and discard exhausted
        E.reveal(game, pid, got, "deck")
        if got[0] not in names:
            found = got[0]
            break
    if found is not None:
        E.take_aside(game, pid, [found], dest="hand")
    rest = list(seat["aside"])
    if rest:
        E.discard(game, pid, rest, zone="aside", public=True)


# --- Joust -------------------------------------------------------------------
# +1 Card +1 Action +$1; you MAY set aside a Province from your hand to gain any
# Reward TO YOUR HAND. The Rewards are six non-Supply piles, all face up, so
# this is a plain pile choice rather than an ordered pile's top card.

def _joust(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_coins(game, 1)
    if "Province" not in game["seats"][pid]["hand"]:
        return
    E.push_choose_cards(game, pid, "Joust", "set_aside", ["Province"], 0, 1,
                        "set aside a Province to gain a Reward")


def _joust_set_aside(game, pid, frame, choice):
    if not choice["cards"]:
        return
    E.set_aside(game, pid, ["Province"], until="cleanup")
    piles = [r for r in E.REWARDS if E.pile_count(game, r) > 0]
    if not piles:
        return                                    # every Reward already taken
    E.push_choose_pile(game, pid, "Joust", "reward", piles)


def _joust_reward(game, pid, frame, choice):
    E.gain_from(game, pid, choice["pile"], dest="hand")


# --- Menagerie ---------------------------------------------------------------
# +1 Action, reveal your hand: all different names -> +3 Cards, else +1 Card.
# An EMPTY hand counts as all different (compendium): +3 Cards.

def _menagerie(game, pid):
    E.add_actions(game, 1)
    hand = list(game["seats"][pid]["hand"])
    E.reveal(game, pid, sorted(hand), "hand")
    E.draw(game, pid, 3 if _distinct(hand) == len(hand) else 1)


# --- Merchant Guild ----------------------------------------------------------
# +1 Buy +$1, then SET UP A LATER ABILITY for this turn: at the end of your Buy
# phase, +1 Coffers per card you GAINED in it. Cumulative per play; counts every
# gain, including ones from before the Merchant Guild was played.

def _merchant_guild(game, pid):
    E.add_buys(game, 1)
    E.add_coins(game, 1)
    E.add_watcher(game, pid, "Merchant Guild", "buy_phase_end",
                  stage="payout", until="turn_end")


def _merchant_guild_payout(game, pid, frame, choice):
    n = game["turn_ctx"]["buy_gains"]
    if n:
        E.add_coffers(game, n, pid)


def _merchant_guild_fires(game, watcher, ctx):
    """Join-time pool filter: a Buy phase with no gains pays nothing, and an
    ability that will visibly do nothing must not be offered for ordering."""
    return game["turn_ctx"]["buy_gains"] > 0


# --- Plaza -------------------------------------------------------------------
# +1 Card +2 Actions; you MAY discard a Treasure for +1 Coffers ("DO X FOR").

def _plaza(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 2)
    treasures = sorted({c for c in game["seats"][pid]["hand"]
                        if E.has_type(game, c, "treasure")})
    if not treasures:
        return
    E.push_choose_cards(game, pid, "Plaza", "discard", treasures, 0, 1,
                        "discard a Treasure for +1 Coffers")


def _plaza_discard(game, pid, frame, choice):
    if not choice["cards"]:
        return
    E.discard(game, pid, list(choice["cards"]))
    E.add_coffers(game, 1)


# --- Remake ------------------------------------------------------------------
# DO THIS TWICE: trash a card, then gain one costing EXACTLY $1 more. The two
# halves are fully sequential — the first remodel's when-trash and when-gain
# abilities resolve before the second one starts, which can change what is in
# hand and what things cost.

def _remake(game, pid):
    _remake_step(game, pid, 2)


def _remake_step(game, pid, left):
    if left <= 0:
        return
    hand = sorted(game["seats"][pid]["hand"])
    if not hand:
        return
    E.push_choose_cards(game, pid, "Remake", "trash", hand, 1, 1,
                        "trash a card (Remake)", data={"left": left})


def _remake_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    ref = card                             # read BEFORE the trash resolves (B3)
    left = frame["data"]["left"] - 1
    E.push_auto(game, pid, "Remake", "again", data={"left": left})
    E.trash(game, pid, [card])
    piles = _piles(game, lambda p: E.cost_eq_card(game, p, ref, 1))
    if piles:
        E.push_choose_pile(game, pid, "Remake", "gain", piles)


def _remake_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


def _remake_again(game, pid, frame, choice):
    _remake_step(game, pid, frame["data"]["left"])


# --- Shop --------------------------------------------------------------------
# +1 Card +$1; you MAY play an Action from your hand that you don't have a copy
# of IN PLAY. The played Shop is itself in play, so a Shop can never chain into
# another Shop.

def _shop(game, pid):
    E.draw(game, pid, 1)
    E.add_coins(game, 1)
    table = set(_on_table(game, pid))
    playable = sorted({c for c in game["seats"][pid]["hand"]
                       if E.has_type(game, c, "action") and c not in table})
    if not playable:
        return
    E.push_choose_cards(game, pid, "Shop", "play", playable, 0, 1,
                        "play an Action you have no copy of in play")


def _shop_play(game, pid, frame, choice):
    if not choice["cards"]:
        return
    E.play_action_card(game, pid, choice["cards"][0])


# --- Soothsayer --------------------------------------------------------------
# Gain a Gold; each other player gains a Curse, and IF THEY DID, draws a card.
# "The other players gain a Curse even if you can't gain a Gold", and only the
# players who actually got one draw.

def _soothsayer(game, pid):
    E.gain(game, pid, "Gold")
    E.attack_opponents(game, pid, "Soothsayer", "hit")


def _soothsayer_hit(game, opp, frame, choice):
    if E.gain(game, opp, "Curse"):
        E.draw(game, opp, 1)


# --- Rewards: Courser --------------------------------------------------------
# Choose TWO DIFFERENT options, then do them IN THE ORDER GIVEN (not the order
# you picked them) — the compendium is explicit about both halves.

_COURSER = [("cards", "+2 Cards"), ("actions", "+2 Actions"),
            ("coins", "+$2"), ("silvers", "Gain 4 Silvers")]


def _courser(game, pid):
    E.push_choose_option(game, pid, "Courser", "pick",
                         options=[{"id": i, "label": l} for i, l in _COURSER],
                         pick=2, distinct=True)


def _courser_pick(game, pid, frame, choice):
    picked = set(choice["ids"])
    for key, _ in _COURSER:                       # printed order, not pick order
        if key not in picked:
            continue
        if key == "cards":
            E.draw(game, pid, 2)
        elif key == "actions":
            E.add_actions(game, 2)
        elif key == "coins":
            E.add_coins(game, 2)
        else:
            for _ in range(4):
                E.gain(game, pid, "Silver")


# --- Rewards: Demesne --------------------------------------------------------
# +2 Actions +2 Buys, gain a Gold. Its "1 VP per Gold you have" is scored in
# engine._vp_of ("demesne").

def _demesne(game, pid):
    E.add_actions(game, 2)
    E.add_buys(game, 2)
    E.gain(game, pid, "Gold")


# --- Rewards: Housecarl ------------------------------------------------------
# +1 Card per differently named ACTION card you have in play, counting itself.

def _housecarl(game, pid):
    actions = [c for c in _on_table(game, pid) if E.has_type(game, c, "action")]
    E.draw(game, pid, _distinct(actions))


# --- Rewards: Huge Turnip ----------------------------------------------------
# +2 Coffers, then +$1 per Coffers you have — counted AFTER the +2 (VARIABLE
# PRODUCTION: "count your Coffers tokens right when you play it, after getting
# +2 Coffers").

def _huge_turnip(game, pid):
    E.add_coffers(game, 2)
    E.add_coins(game, game["coffers"].get(pid, 0))


# --- Rewards: Renown ---------------------------------------------------------
# +1 Buy; this turn cards cost $2 less. Bridge's counter, cumulative per play.

def _renown(game, pid):
    E.add_buys(game, 1)
    game["turn_ctx"]["bridges"] += 2


# ── batch B ──────────────────────────────────────────────────────────────────

# --- Butcher -----------------------------------------------------------------
# +2 Coffers; you MAY trash a card from hand, to gain a card costing up to $1
# more than it per Coffers you SPEND. You may trash nothing; you may spend 0, or
# more than the 2 you just got. Spending still pays +$1 each (see the header).

def _butcher(game, pid):
    E.add_coffers(game, 2)
    hand = sorted(game["seats"][pid]["hand"])
    if not hand:
        return
    E.push_choose_cards(game, pid, "Butcher", "trash", hand, 0, 1,
                        "trash a card (Butcher)")


def _butcher_trash(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    base = E.cost(game, card)              # captured before the trash (B3)
    E.trash(game, pid, [card])
    have = game["coffers"].get(pid, 0)
    E.push_choose_option(
        game, pid, "Butcher", "spend",
        options=[{"id": str(k), "label": "Spend nothing" if k == 0
                  else f"Spend {k} Coffers"} for k in range(have + 1)],
        data={"base": base})


def _butcher_spend(game, pid, frame, choice):
    n = min(int(choice["ids"][0]), game["coffers"].get(pid, 0))
    if n:
        game["coffers"][pid] -= n
        E._log(game, pid, "spend", what="coffers", n=n)
        E.add_coins(game, n)
    cap = frame["data"]["base"] + n
    piles = _piles(game, lambda p: E.cost_le(game, p, cap))
    if piles:
        E.push_choose_pile(game, pid, "Butcher", "gain", piles)


def _butcher_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])


# --- Coronet -----------------------------------------------------------------
# A Reward that is BOTH an Action and a Treasure at all times: you may play a
# non-Reward Action from hand twice, and a non-Reward Treasure from hand twice.
# It gives no $ itself. Registered under EFFECTS so it runs from either play
# path — the kernel plays it as an Action in the Action phase and as a Treasure
# in the Buy phase, and the same ability is correct either way.

def _coronet(game, pid):
    # The Treasure half is PARKED FIRST, so it resolves second and — the part
    # that matters — it happens whether or not the Action half was offered at
    # all. Queuing it from the Action half's answer instead silently dropped
    # the whole Treasure ability for a hand with no playable Action.
    E.push_auto(game, pid, "Coronet", "offer_treasure")
    _coronet_offer(game, pid, "action")


def _coronet_offer(game, pid, kind):
    """SEQUENTIAL, like Hamlet's two offers: the Action half is resolved (and
    may draw, discard or trash) before the Treasure half looks at the hand."""
    opts = sorted({c for c in game["seats"][pid]["hand"]
                   if E.has_type(game, c, kind) and not E.has_type(game, c, "reward")})
    if not opts:
        return
    E.push_choose_cards(game, pid, "Coronet", "play", opts, 0, 1,
                        f"play a non-Reward {kind.capitalize()} twice",
                        data={"kind": kind})


def _coronet_play(game, pid, frame, choice):
    kind = frame["data"]["kind"]
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    E.push_auto(game, pid, "Coronet", "replay",
                data={"card": card, "kind": kind})
    if kind == "action":
        E.play_action_card(game, pid, card)
    else:
        E.play_treasure_card(game, pid, card)


def _coronet_offer_treasure(game, pid, frame, choice):
    _coronet_offer(game, pid, "treasure")


def _coronet_replay(game, pid, frame, choice):
    """The SECOND play. `from_zone=None` is the throne-room shape: run the
    ability again without moving the card. If it left play in between (it
    trashed itself, or a when-trash moved it), the replay is lost track of."""
    card, kind = frame["data"]["card"], frame["data"]["kind"]
    if card not in game["seats"][pid]["in_play"]:
        E.lost_track(game, pid, card, "played")
        return
    if kind == "action":
        E.play_action_card(game, pid, card, from_zone=None)
    else:
        E.play_treasure_card(game, pid, card, from_zone=None)


# --- Farmhands ---------------------------------------------------------------
# +1 Card +2 Actions. WHEN YOU GAIN THIS you may set aside an Action or Treasure
# from your hand and play it at the start of your next turn — including when you
# gain it on an opponent's turn, and including setting ITSELF aside if it was
# gained to your hand.

def _farmhands(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 2)


def _farmhands_gained(game, pid, frame, choice):
    opts = sorted({c for c in game["seats"][pid]["hand"]
                   if E.has_type(game, c, "action") or E.has_type(game, c, "treasure")})
    if not opts:
        return
    E.push_choose_cards(game, pid, "Farmhands", "set_aside", opts, 0, 1,
                        "set aside a card to play next turn")


def _farmhands_set_aside(game, pid, frame, choice):
    if not choice["cards"]:
        return
    card = choice["cards"][0]
    E.set_aside(game, pid, [card])
    E.add_start_fx(game, pid, "Farmhands", "play_it", data={"card": card})


def _farmhands_play_it(game, pid, frame, choice):
    """"If you set aside a card, you MUST play it next turn" — not optional."""
    card = frame["data"]["card"]
    if card not in game["seats"][pid]["set_aside"]:
        E.lost_track(game, pid, card, "played")
        return
    E.take_set_aside(game, pid, [card], dest="aside")
    if E.has_type(game, card, "action"):
        E.play_action_card(game, pid, card, from_zone="aside")
    else:
        E.play_treasure_card(game, pid, card, from_zone="aside")


# --- Farrier -----------------------------------------------------------------
# +1 Card +1 Action +1 Buy. OVERPAY: +1 Card at the end of this turn per $1
# overpaid — the extra cards are drawn in Clean-up AFTER the new hand, so they
# are cards for NEXT turn (engine._end_turn reads turn_ctx["end_draw"]).

def _farrier(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    E.add_buys(game, 1)


def _farrier_gained(game, pid, frame, choice):
    n = frame["data"].get("overpay", 0)
    if n and pid == game["turn"]:
        game["turn_ctx"]["end_draw"] += n
        E._log(game, pid, "end_draw", n=n)


# --- Ferryman ----------------------------------------------------------------
# +2 Cards +1 Action, discard a card. WHEN YOU GAIN A FERRYMAN, gain one from
# the extra pile chosen at setup — which is deliberately OUTSIDE the Supply, so
# nothing else in the game can reach it.

def _ferryman(game, pid):
    E.draw(game, pid, 2)
    E.add_actions(game, 1)
    hand = sorted(game["seats"][pid]["hand"])
    if not hand:
        return
    E.push_choose_cards(game, pid, "Ferryman", "discard", hand, 1, 1,
                        "discard a card (Ferryman)")


def _ferryman_discard(game, pid, frame, choice):
    E.discard(game, pid, list(choice["cards"]))


def _ferryman_gained(game, pid, frame, choice):
    pile = game["ferryman_pile"]
    if pile:
        E.gain_from(game, pid, pile)


# --- Footpad -----------------------------------------------------------------
# +2 Coffers; each other player discards down to 3. Its SECOND ability is a
# game rule, not an ability of the card: in games using Footpad, EVERY player
# who gains a card in an Action phase draws one, whether or not they own a copy
# and whichever player's Action phase it is.

def _footpad(game, pid):
    E.add_coffers(game, 2)
    E.attack_opponents(game, pid, "Footpad", "hit")


def _footpad_hit(game, opp, frame, choice):
    hand = game["seats"][opp]["hand"]
    n = len(hand) - 3
    if n <= 0:
        return
    E.push_choose_cards(game, opp, "Footpad", "down_to_3", sorted(hand), n, n,
                        "discard down to 3 cards")


def _footpad_down_to_3(game, opp, frame, choice):
    E.discard(game, opp, list(choice["cards"]))


def _footpad_game_draw(game, pid, frame, choice):
    E.draw(game, pid, 1)


def _footpad_in_action_phase(game, pid, ctx):
    return game["phase"] == "action"


# --- Herald ------------------------------------------------------------------
# +1 Card +1 Action, reveal the top card; if it's an Action, PLAY IT (not
# optional). OVERPAY: per $1 overpaid, put any card from your discard pile onto
# your deck — resolved on when-gain, so the Herald is already in the discard
# pile and may be chosen.

def _herald(game, pid):
    E.draw(game, pid, 1)
    E.add_actions(game, 1)
    seen = E.look_top(game, pid, 1)
    if not seen:
        return
    E.reveal(game, pid, seen, "deck")
    card = seen[0]
    if E.has_type(game, card, "action"):
        # played straight off the reveal — it never passes through your hand,
        # which matters for anything that reads or counts the hand mid-play
        E.play_action_card(game, pid, card, from_zone="aside")
    else:
        E.take_aside(game, pid, [card], dest="discard")


def _herald_gained(game, pid, frame, choice):
    _herald_topdeck_step(game, pid, frame["data"].get("overpay", 0))


def _herald_topdeck_step(game, pid, left):
    if left <= 0:
        return
    discard = sorted(game["seats"][pid]["discard"])
    if not discard:
        return
    E.push_choose_cards(game, pid, "Herald", "topdeck", discard, 1, 1,
                        "put a card from your discard pile onto your deck",
                        data={"left": left})


def _herald_topdeck(game, pid, frame, choice):
    E.topdeck(game, pid, choice["cards"][0], zone="discard", public=True)
    _herald_topdeck_step(game, pid, frame["data"]["left"] - 1)


# --- Horn of Plenty ----------------------------------------------------------
# A Treasure worth NO $: gain a card costing up to $1 per differently named card
# you have in play, counting itself. If the gained card is a Victory card, trash
# the Horn of Plenty — only if you actually gained one.

def _horn_of_plenty(game, pid):
    cap = _distinct(_on_table(game, pid))
    piles = _piles(game, lambda p: E.cost_le(game, p, cap))
    if not piles:
        return
    E.push_choose_pile(game, pid, "Horn of Plenty", "gain", piles)


def _horn_gain(game, pid, frame, choice):
    pile = choice["pile"]
    got = E.pile_top(game, pile)
    if not E.gain(game, pid, pile):
        return
    if got is not None and E.has_type(game, got, "victory"):
        # first gain, THEN trash (compendium). It may have left play already —
        # a second Horn play via Coronet trashes the first one's copy.
        if "Horn of Plenty" in game["seats"][pid]["in_play"]:
            E.trash(game, pid, ["Horn of Plenty"], zone="in_play")
        else:
            E.lost_track(game, pid, "Horn of Plenty", why="it is no longer in play")


# --- Infirmary ---------------------------------------------------------------
# +1 Card; you may trash a card. OVERPAY: play this once per $1 overpaid — each
# play draws and then optionally trashes, resolved in turn.

def _infirmary(game, pid):
    E.draw(game, pid, 1)
    hand = sorted(game["seats"][pid]["hand"])
    if not hand:
        return
    E.push_choose_cards(game, pid, "Infirmary", "trash", hand, 0, 1,
                        "trash a card (Infirmary)")


def _infirmary_trash(game, pid, frame, choice):
    if choice["cards"]:
        E.trash(game, pid, list(choice["cards"]))


def _infirmary_gained(game, pid, frame, choice):
    n = frame["data"].get("overpay", 0)
    if n:
        E.push_auto(game, pid, "Infirmary", "replay", data={"left": n})


def _infirmary_replay(game, pid, frame, choice):
    """Play the just-gained Infirmary once per $1 overpaid. The FIRST play moves
    it out of the discard pile into play; the rest are replays. Watchtower or
    Innovation may have moved it first — "cards that are lost track of can't be
    played" — so the zone is asked for, never assumed."""
    left = frame["data"]["left"]
    if left <= 0:
        return
    if "Infirmary" in game["seats"][pid]["in_play"]:
        E.push_auto(game, pid, "Infirmary", "replay", data={"left": left - 1})
        E.play_action_card(game, pid, "Infirmary", from_zone=None)
        return
    zone = E.find_card_zone(game, pid, "Infirmary", zones=("discard", "hand"))
    if zone is None:
        E.lost_track(game, pid, "Infirmary", "played")
        return
    E.push_auto(game, pid, "Infirmary", "replay", data={"left": left - 1})
    E.play_action_card(game, pid, "Infirmary", from_zone=zone)


# --- Jester ------------------------------------------------------------------
# +$2; each other player discards their top card. Victory -> they gain a Curse;
# otherwise a copy of it is gained by them OR BY YOU, the attacker's choice.

def _jester(game, pid):
    E.add_coins(game, 2)
    # the attacker rides the frame: on a non-Victory card the CHOICE of who
    # gains the copy is theirs, and the per-opponent stage runs as the opponent
    E.attack_opponents(game, pid, "Jester", "hit", data={"attacker": pid})


def _jester_hit(game, opp, frame, choice):
    attacker = frame["data"]["attacker"]
    top = E.look_top(game, opp, 1)
    if not top:
        return
    card = top[0]
    E.reveal(game, opp, [card], "deck")
    E.discard(game, opp, [card], zone="aside", public=True)
    if E.has_type(game, card, "victory"):
        E.gain(game, opp, "Curse")
        return
    if E.pile_count(game, card) <= 0:
        return                                    # no copy left to gain
    E.push_choose_option(
        game, attacker, "Jester", "who",
        options=[{"id": "me", "label": f"You gain the {card}"},
                 {"id": "them", "label": f"{game['names'].get(opp, opp)} gains the {card}"}],
        data={"card": card, "opp": opp})


def _jester_who(game, attacker, frame, choice):
    d = frame["data"]
    E.gain(game, attacker if choice["ids"][0] == "me" else d["opp"], d["card"])


# --- Journeyman --------------------------------------------------------------
# Name a card, then DIG FOR 3 cards WITHOUT that name; they go INTO YOUR HAND
# (the rulebook's "draws you three cards" is an erratum — it matters for tokens
# we don't have yet, but the distinction is free to get right).

def _journeyman(game, pid):
    E.push_name_card(game, pid, "Journeyman", "named")


def _journeyman_named(game, pid, frame, choice):
    named = choice["card"]
    seat = game["seats"][pid]
    keep = []
    while len(keep) < 3:
        got = E.look_top(game, pid, 1)
        if not got:
            break
        E.reveal(game, pid, got, "deck")
        if got[0] != named:
            keep.append(got[0])
    if keep:
        E.take_aside(game, pid, keep, dest="hand")
    rest = list(seat["aside"])
    if rest:
        E.discard(game, pid, rest, zone="aside", public=True)


# --- Stonemason --------------------------------------------------------------
# Trash a card, gain TWO cards each costing LESS than it (strictly). OVERPAY:
# gain 2 Action cards each costing EXACTLY the amount overpaid. Each gain is
# chosen and taken in turn, so a cost change from the first applies to the next.

def _stonemason(game, pid):
    hand = sorted(game["seats"][pid]["hand"])
    if not hand:
        return
    E.push_choose_cards(game, pid, "Stonemason", "trash", hand, 1, 1,
                        "trash a card (Stonemason)")


def _stonemason_trash(game, pid, frame, choice):
    card = choice["cards"][0]
    ref = card                             # captured before the trash (B3)
    E.trash(game, pid, [card])
    _stonemason_gain_step(game, pid, ref, 2)


def _stonemason_gain_step(game, pid, ref, left):
    """`ref` is the TRASHED CARD, not a coin cap: "each costing less than it"
    is a vector comparison, so trashing a Golem {$4,P} may gain {$3,P} and
    {$4} but not {$5}."""
    if left <= 0:
        return
    piles = _piles(game, lambda p: E.cost_lt_card(game, p, ref))
    if not piles:
        return
    E.push_choose_pile(game, pid, "Stonemason", "gain", piles,
                       data={"ref": ref, "left": left})


def _stonemason_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])
    d = frame["data"]
    _stonemason_gain_step(game, pid, d["ref"], d["left"] - 1)


def _stonemason_gained(game, pid, frame, choice):
    n = frame["data"].get("overpay", 0)
    if n:
        _stonemason_overpay_step(game, pid, n, 2)


def _stonemason_overpay_step(game, pid, amount, left):
    if left <= 0:
        return
    piles = _piles(game, lambda p: E.has_type(game, p, "action")
                   and E.cost_eq(game, p, amount))
    if not piles:
        return
    E.push_choose_pile(game, pid, "Stonemason", "overpay_gain", piles,
                       data={"amount": amount, "left": left})


def _stonemason_overpay_gain(game, pid, frame, choice):
    E.gain(game, pid, choice["pile"])
    d = frame["data"]
    _stonemason_overpay_step(game, pid, d["amount"], d["left"] - 1)


# --- Young Witch -------------------------------------------------------------
# +2 Cards, discard 2, then each other player gains a Curse unless they reveal a
# BANE from their hand. Order matters: reactions first (kernel), then YOUR draw
# and discard, then the Bane reveals — so a Bane that is itself a Reaction must
# still be in hand at that point. The attack half runs from a later stage, so it
# captures the immune set at play time (the Minion/Replace rule).

def _young_witch(game, pid):
    E.draw(game, pid, 2)
    immune = list(game.get("_atk_immune", []))
    hand = sorted(game["seats"][pid]["hand"])
    if not hand:
        _young_witch_attack(game, pid, immune)
        return
    n = min(2, len(hand))
    E.push_choose_cards(game, pid, "Young Witch", "discard", hand, n, n,
                        "discard 2 cards", data={"immune": immune})


def _young_witch_discard(game, pid, frame, choice):
    E.discard(game, pid, list(choice["cards"]))
    _young_witch_attack(game, pid, frame["data"]["immune"])


def _young_witch_attack(game, pid, immune):
    E.attack_opponents(game, pid, "Young Witch", "hit", immune=immune)


def _young_witch_hit(game, opp, frame, choice):
    bane = game["bane"]
    if bane and bane in game["seats"][opp]["hand"]:
        E.push_choose_option(
            game, opp, "Young Witch", "bane",
            options=[{"id": "reveal", "label": f"Reveal {bane} (block the Curse)"},
                     {"id": "no", "label": "Take the Curse"}],
            data={"bane": bane})
        return
    E.gain(game, opp, "Curse")


def _young_witch_bane(game, opp, frame, choice):
    bane = frame["data"]["bane"]
    if choice["ids"][0] == "reveal" and bane in game["seats"][opp]["hand"]:
        E.reveal(game, opp, [bane], "hand")
        return
    E.gain(game, opp, "Curse")


# ── registries ───────────────────────────────────────────────────────────────

EFFECTS = {
    # batch A
    "Advisor": _advisor,
    "Baker": _baker,
    "Candlestick Maker": _candlestick_maker,
    "Carnival": _carnival,
    "Hamlet": _hamlet,
    "Hunting Party": _hunting_party,
    "Joust": _joust,
    "Menagerie": _menagerie,
    "Merchant Guild": _merchant_guild,
    "Plaza": _plaza,
    "Remake": _remake,
    "Shop": _shop,
    "Soothsayer": _soothsayer,
    "Courser": _courser,
    "Demesne": _demesne,
    "Housecarl": _housecarl,
    "Huge Turnip": _huge_turnip,
    "Renown": _renown,
    # batch B
    "Butcher": _butcher,
    "Coronet": _coronet,
    "Farmhands": _farmhands,
    "Farrier": _farrier,
    "Ferryman": _ferryman,
    "Footpad": _footpad,
    "Herald": _herald,
    "Horn of Plenty": _horn_of_plenty,
    "Infirmary": _infirmary,
    "Jester": _jester,
    "Journeyman": _journeyman,
    "Stonemason": _stonemason,
    "Young Witch": _young_witch,
}

STAGES = {
    # batch A
    ("Advisor", "pick"): _advisor_pick,
    ("Hamlet", "discard"): _hamlet_discard,
    ("Joust", "set_aside"): _joust_set_aside,
    ("Joust", "reward"): _joust_reward,
    ("Merchant Guild", "payout"): _merchant_guild_payout,
    ("Plaza", "discard"): _plaza_discard,
    ("Remake", "trash"): _remake_trash,
    ("Remake", "gain"): _remake_gain,
    ("Remake", "again"): _remake_again,
    ("Shop", "play"): _shop_play,
    ("Soothsayer", "hit"): _soothsayer_hit,
    ("Courser", "pick"): _courser_pick,
    # batch B
    ("Butcher", "trash"): _butcher_trash,
    ("Butcher", "spend"): _butcher_spend,
    ("Butcher", "gain"): _butcher_gain,
    ("Coronet", "play"): _coronet_play,
    ("Coronet", "replay"): _coronet_replay,
    ("Coronet", "offer_treasure"): _coronet_offer_treasure,
    ("Farmhands", "gained"): _farmhands_gained,
    ("Farmhands", "set_aside"): _farmhands_set_aside,
    ("Farmhands", "play_it"): _farmhands_play_it,
    ("Farrier", "gained"): _farrier_gained,
    ("Ferryman", "discard"): _ferryman_discard,
    ("Ferryman", "gained"): _ferryman_gained,
    ("Footpad", "hit"): _footpad_hit,
    ("Footpad", "down_to_3"): _footpad_down_to_3,
    ("Footpad", "game_draw"): _footpad_game_draw,
    ("Herald", "gained"): _herald_gained,
    ("Herald", "topdeck"): _herald_topdeck,
    ("Horn of Plenty", "gain"): _horn_gain,
    ("Infirmary", "trash"): _infirmary_trash,
    ("Infirmary", "gained"): _infirmary_gained,
    ("Infirmary", "replay"): _infirmary_replay,
    ("Jester", "hit"): _jester_hit,
    ("Jester", "who"): _jester_who,
    ("Journeyman", "named"): _journeyman_named,
    ("Stonemason", "trash"): _stonemason_trash,
    ("Stonemason", "gain"): _stonemason_gain,
    ("Stonemason", "overpay_gain"): _stonemason_overpay_gain,
    ("Stonemason", "gained"): _stonemason_gained,
    ("Young Witch", "discard"): _young_witch_discard,
    ("Young Witch", "hit"): _young_witch_hit,
    ("Young Witch", "bane"): _young_witch_bane,
}

TRIGGERS = {
    # the four OVERPAY cards: the amount rides the gain event (2022 retiming)
    "Farrier": [{"on": "gain", "from": "self", "stage": "gained"}],
    "Herald": [{"on": "gain", "from": "self", "stage": "gained"}],
    "Infirmary": [{"on": "gain", "from": "self", "stage": "gained"}],
    "Stonemason": [{"on": "gain", "from": "self", "stage": "gained"}],
    # plain when-gain abilities
    "Farmhands": [{"on": "gain", "from": "self", "stage": "gained"}],
    "Ferryman": [{"on": "gain", "from": "self", "stage": "gained"}],
    # Footpad's GAME rule — every player, any Action phase, no copy needed
    "Footpad": [{"on": "gain", "from": "game", "stage": "game_draw",
                 "when": _footpad_in_action_phase}],
}

WATCHER_WHENS = {
    ("Merchant Guild", "payout"): _merchant_guild_fires,
}

# Horn of Plenty pushes a pile choice, so play_all_treasures must skip it —
# bucket 1. Coronet and Huge Turnip are Rewards and can only be played
# deliberately; Coronet pushes decisions too.
MANUAL_TREASURES = {"Horn of Plenty", "Coronet"}
