"""The bots, one strategy per rung of the ladder, selected by `ai_difficulty`:

* ``random``   — uniform over legal moves (v1; the easy/normal/hard tiers).
* ``bmplus``   — Big Money that READS THE BOARD: it picks the kingdom's best
  terminal (the published Terminal-Draw-BM ranking), plays its Actions, buys
  Colonies/Platinum in a colony game, and hands every buy to `bot_endgame` for
  the Penultimate Province Rule and pile control. **The strongest tier we
  have**, and the default.

THREE further strategies exist in code and are deliberately NOT in
`main.AI_DIFFICULTIES`. Reaching one needs an explicit difficulty string, which
the server will not accept from a client (`_valid_difficulty` coerces anything
unknown), so they are usable from the arena and tests only. They are the
research harness, not opponents (every number: docs/ai-research-log.md):

* ``bigmoney``    — the classic Big Money buy ladder: ONLY Treasure and
  Victory, never an Action, greening on a Province-count clock. Retired as an
  opponent because it is a strict SUBSET of bmplus — same ladder minus the
  terminal, the Colony rungs and the endgame — which bmplus beats 0.77 (base) /
  0.73 (all sets). It stays here as THE REFERENCE RUNG: "is bmplus still better
  than just buying money?" is the most informative gate the ladder has, and the
  pace anchors (pure BM reaches 4 Provinces ~turn 17) are how we know the buy
  ladder is faithful to the published one. It is also the only clean harness
  for the shared `_want` ladder below, which bmplus reuses — bmplus's own buy
  path wraps it in terminal, Colony and endgame logic.
* ``strategist``  — archetype board-read + action sequencing + reshuffle rules.
  Measured 0.35 vs bmplus overall; per archetype engine 0.231, minion 0.237,
  cursing-money 0.381, rush 0.000, and even its money plan reads 0.4667 over
  120 games. This is the corpus's own headline result — "a simple engine loses
  to Big Money" — reproduced.
* ``champion``    — per-kingdom plan tournament + determinized rollout buy
  search. Roughly a wash with bmplus at ~160x the cost.

`choose` is the server scheduler's guaranteed turn-finisher: for EVERY strategy
it must return a valid move for ANY state where (pending_pid or turn) == pid,
and it must never consume the game's own rng_state (pass an explicit rng).
"""

import random

from . import bot_champion, bot_decisions, bot_endgame, bot_plan, engine
from .bot_traits import best_bm_terminal, traits

# ai_difficulty values that route to a real strategy. Everything else
# (easy/normal/hard) is still the random-legal bot.
BIG_MONEY = "bigmoney"
BM_PLUS = "bmplus"
STRATEGIST = "strategist"
CHAMPION = "champion"


def choose(game, pid, rng=None, difficulty=None):
    """ONE move for pid. `difficulty` is the room's persisted tier."""
    if difficulty == BIG_MONEY:
        return choose_big_money(game, pid, rng)
    if difficulty == BM_PLUS:
        return choose_bm_plus(game, pid, rng)
    if difficulty == STRATEGIST:
        return choose_strategist(game, pid, rng)
    if difficulty == CHAMPION:
        return choose_champion(game, pid, rng)
    # "strategist:<archetype>" forces one plan — the arena measures archetypes
    # one at a time this way, and the champion applies its tournament result
    # through the same seam.
    if isinstance(difficulty, str) and difficulty.startswith(STRATEGIST + ":"):
        return choose_strategist(game, pid, rng,
                                 force=difficulty.split(":", 1)[1])
    # "bmplus:<policy>" forces a Colony-game buy policy — the same seam, used
    # to measure the colony variants against each other.
    if isinstance(difficulty, str) and difficulty.startswith(BM_PLUS + ":"):
        return choose_bm_plus(game, pid, rng,
                              policy=difficulty.split(":", 1)[1])
    return choose_random(game, pid, rng)


def _decision(game, pid, rng, policy):
    """Answer the top frame. `policy` False = uniform sampling (the `random`
    tier's defining weakness — it keeps its Gold to a Militia only by luck)."""
    if policy:
        return {"type": "decision", **bot_decisions.decide(game, pid, rng)}
    return {"type": "decision", **engine.sample_decision(game, pid, rng)}


def choose_random(game, pid, rng=None):
    """Uniform over legal moves with the sibling bots' anti-stall bias: never
    end a phase while something else is possible (an unbiased bot ends its turn
    instantly ~1/N of the time and the game crawls). Decisions are answered with
    `engine.sample_decision` — uniform over the frame's valid payloads."""
    r = rng or random.Random()
    if game["pending_pid"] == pid:
        return _decision(game, pid, r, policy=False)
    moves = engine.legal_moves(game, pid)
    for m in moves:
        if m["type"] == "play_all_treasures":
            return m
    # We only get here with no play_all_treasures on offer, so any remaining
    # play_treasure is an INTERACTIVE one (War Chest/Anvil) that play_all
    # skips — it has to be played individually or the turn ends holding
    # unspent coins. Each play removes a card from hand, so this can't loop.
    active = [m for m in moves if m["type"] != "end_phase"]
    if active:
        return r.choice(active)
    return {"type": "end_phase"}


# ── Big Money ────────────────────────────────────────────────────────────────
# The buy ladder, verbatim from the strategy it implements: $8+ Province, $6-7
# Gold (Duchy once Provinces are short), $5 Silver (Duchy), $3-4 Silver
# (Estate), $2 Estate only at the very end, and never more than one buy.
#
# `_want` IS SHARED — bmplus falls back to it for every rung it doesn't
# override, so this ladder is live production code. Only `choose_big_money`,
# the wrapper that plays NOTHING but this ladder, is research-only (see the
# module docstring: it is the arena's reference rung and this ladder's test
# harness, and no room can select it).
#
# DELIBERATE GAPS, both faithful to the ladder as specified:
#   * Colony/Platinum are not in it. In a Prosperity game with the colony setup
#     the bot still buys Province at $10-12 and Gold at $6-7.
#   * It plays no Action cards at all. It never BUYS one, so it only ever holds
#     one an opponent handed it (Masquerade, Jester, Swindler) — and a random
#     play of an unknown Action is as likely to hurt as help.

_EARLY_SILVERS = 5      # "fewer than 5 Silvers in your deck"


def _early_for_gold(game, pid):
    """The $8 exception — "really early": no Gold and fewer than 5 Silvers in
    the whole deck. Counts every zone, so a Silver sitting in play or on a mat
    still counts as owned."""
    owned = engine.owned_cards(game, pid)
    return owned.count("Gold") == 0 and owned.count("Silver") < _EARLY_SILVERS


def _want(game, pid):
    """Which pile the ladder wants at the current coin total, or None.

    Read fresh every call — the bot is stateless. That is sound because there
    is exactly ONE buy per turn: Big Money buys no Action, so nothing in its
    deck ever grants a second buy, and no rung has to plan a follow-up."""
    coins = game["coins"]
    provinces = game["supply"].get("Province", 0)

    if coins >= 8:
        # The exception is written against $8 specifically, not $9 or more.
        return "Gold" if coins == 8 and _early_for_gold(game, pid) else "Province"
    if coins >= 6:
        return "Duchy" if provinces <= 4 else "Gold"
    if coins == 5:
        return "Duchy" if provinces <= 5 else "Silver"
    if coins >= 3:
        return "Estate" if provinces <= 2 else "Silver"
    if coins == 2:
        return "Estate" if provinces <= 3 else None
    return None


def choose_big_money(game, pid, rng=None):
    r = rng or random.Random()
    if game["pending_pid"] == pid:
        # Big Money buys no Action, but it is still ATTACKED: the Militia
        # discard and the Torturer choice are most of what a human sees this
        # bot decide, and answering them by policy costs nothing.
        return _decision(game, pid, r, policy=True)

    if game["phase"] == "action":
        return {"type": "end_phase"}        # Big Money plays no Actions

    moves = engine.legal_moves(game, pid)
    # Every coin first — the ladder reads the FULL turn total, so a buy before
    # the treasures are down would read the wrong rung.
    # DEBT (Empires) FIRST — see _pay_off_debt.
    debt = _pay_off_debt(game, pid, moves)
    if debt is not None:
        return debt
    for m in moves:
        if m["type"] == "play_all_treasures":
            return m
    treasures = [m for m in moves if m["type"] == "play_treasure"]
    if treasures:
        # Only the interactive ones (War Chest/Anvil) reach here — play_all
        # skips them. Each play removes a card from hand, so this can't loop.
        return r.choice(treasures)

    want = _want(game, pid)
    if want is not None and {"type": "buy", "card": want} in moves:
        return {"type": "buy", "card": want}
    return {"type": "end_phase"}


# ── Big Money+ ───────────────────────────────────────────────────────────────
# Big Money with the three skills the corpus adds first: a terminal off the
# board, the Colony rungs, and endgame technique.
#
# It stays a MONEY deck on purpose. It buys one kind of Action (the kingdom's
# best drawer/curser) and never a village, because the terminal budget is the
# whole reason plain Big Money works: "<= 1 terminal per 5-6 cards, ~2 drawers
# max, Envoy exactly 1".

# HOW MANY copies of its terminal the tier buys, and WHEN the extra one is
# allowed. Both knobs were the article's rules of thumb; both are now measured
# (tools/bm_quantity_sweep.py), and most of the defaults survived:
#
#   cap 2 is right ON AVERAGE — capping at 1, 3 or 4 all measured BELOW it on
#   random boards (0.458 / 0.446 / 0.446), so the global default stands.
#
#   the deck>=16 gate for the extra copy also stands. 12 looked better at
#   n=120 (0.550 random, 0.545 colony) and COLLAPSED to 0.5050 at n=400 — a
#   textbook regression to the mean, and the reason the promising arm gets a
#   confirmation run before it gets shipped.
#
#   longer games want slightly more, as expected, but not enough to act on:
#   cap 3 goes from 0.446 on random boards to 0.508 on COLONY boards, still
#   n.s. If that is ever revisited, the knob wants to key on the Colony pile.
_MAX_TERMINALS = 2
_SECOND_TERMINAL_DECK = 16

# Per-card exceptions to the cap, each one MEASURED against the default of 2
# on a board where that card is the only terminal (n=120 CRN games):
#
#   Sea Witch    cap 3 = 0.5917 sig  (and cap 1 = 0.2958 sig — it wants many)
#   Council Room 2nd copy = 0.4042 sig -> stays at 1
#   Magnate      2nd copy = 0.4208 n.s. -> stays at 1, point estimate agrees
#   Witch's Hut  2nd copy = 0.6000 sig -> was WRONGLY capped at 1 by hand
#   Margrave     cap 3 = 0.3833 sig  -> the default 2 already blocks it
#
# Sea Witch being the one card that wants a THIRD is not obviously a fluke: it
# is a Duration, so it sits in play across the shuffle and de-collides with
# itself (the reshuffle article's R8), and each copy races the 10-card Curse
# pile faster. Wharf is also a Duration and did NOT want a third (0.4708), so
# treat that as a plausible mechanism rather than a rule.
TERMINAL_CAPS = {"Sea Witch": 3, "Council Room": 1, "Magnate": 1,
                 # Dark Ages: Catacombs wants exactly ONE (cap1 0.593 at
                 # n=400, cap3 0.391 — both significant, and the promising arm
                 # got its confirmation run). It draws no cards on net when it
                 # collides: the second copy just re-reads the same three.
                 # Cultist / Marauder / Rogue / Hunting Grounds all measured
                 # inside the noise band at the default 2 (a third Marauder is
                 # significantly WORSE at 0.333), so they keep it.
                 "Catacombs": 1}


# Set by the terminal-sweep harness to force ONE card (or "" for none) as the
# tier's terminal, so a candidate can be measured against buying no terminal at
# all. Read at call time; never set outside tools/tests.
FORCE_TERMINAL = None


# Swapped by the sweep/gate harness to score an alternative ranking table
# against the shipped one. None = the real table.
TERMINAL_TABLE = None


def _bm_terminal(game, pid):
    """The kingdom's best Big Money terminal, or None on a board with none."""
    if FORCE_TERMINAL is not None:
        return FORCE_TERMINAL or None
    return best_bm_terminal(game["kingdom"], game["supply"],
                            table=TERMINAL_TABLE)


def _terminals_owned(game, pid, card):
    return engine.owned_cards(game, pid).count(card)


def _wants_terminal(game, pid):
    """Should we buy (another copy of) our terminal at these coins?"""
    card = _bm_terminal(game, pid)
    if card is None or engine.cost(game, card) > game["coins"]:
        return None
    # The cost VECTOR's second dimension (Alchemy). `cost()` returns only the
    # COIN component, so a Golem reads as $4 and looks affordable at $4 — the
    # bot then names a card it cannot pay for. This tier buys no Potion, so any
    # Potion cost is simply out of reach.
    if engine.potion_cost(game, card) > game.get("potions", 0):
        return None
    if game["supply"].get(card, 0) <= 0:
        return None
    if engine.buy_gate(game, pid, card) is not None:
        return None
    have = _terminals_owned(game, pid, card)
    if have == 0:
        return card
    cap = TERMINAL_CAPS.get(card, _MAX_TERMINALS)
    if have >= cap:
        return None
    # the second copy waits for the deck to be big enough to absorb it
    if len(engine.owned_cards(game, pid)) >= _SECOND_TERMINAL_DECK:
        return card
    return None


# ── Colony games ─────────────────────────────────────────────────────────────
# A Colony game is a DIFFERENT ECONOMY, not the same one with a bigger card on
# top: the density a deck needs rises from 1.6 to 2.2, and the pile the game
# actually ends on is the Colony pile.
#
# `COLONY_POLICY` selects the buy policy; the alternatives are kept because
# they are the measured decomposition, and the arena can still play them
# head-to-head through the "bmplus:<policy>" tier string.
#
# MEASURED, 120 Colony-only boards, 240 CRN-paired games each, mirror 0.5000:
#   v2 ($8 -> Gold only)            vs v1  0.5312  (n.s.)
#   v4 (Colony greening clock only) vs v1  0.5896  significant
#   v3 (both)                       vs v1  0.6562  significant   <- SHIPPED
#   v3 vs v4                               0.5188  (n.s.)
# The clock is the real lever; the $8 rung adds a little and never hurts.
COLONY_POLICY = "v3"

# How few Colonies must remain before the deck stops building and converts.
_COLONY_GREEN_AT = 4


def _colony_rungs(game, pid, policy=None):
    """Platinum/Colony, which plain Big Money deliberately ignores."""
    if not game.get("colony"):
        return None
    policy = policy or COLONY_POLICY
    coins = game["coins"]
    sup = game["supply"]
    if coins >= 11 and sup.get("Colony", 0) > 0:
        return "Colony"
    if 9 <= coins <= 10 and sup.get("Platinum", 0) > 0:
        # a Platinum is worth more than the Gold this would otherwise buy, and
        # 2.2 density is what a Colony game actually needs
        return "Platinum"
    if policy in ("v1", "v4"):
        return None
    # v2/v3: at $8 the plain ladder takes a Province. In a Colony game that
    # spends the climb to $11 on a 6-point card — take the Gold instead while
    # the Colony pile is still deep.
    if coins == 8 and sup.get("Colony", 0) > _COLONY_GREEN_AT \
            and sup.get("Gold", 0) > 0:
        return "Gold"
    return None


def _colony_green(game, pid, policy=None):
    """The COLONY clock: the race is the Colony pile, so the green rungs must
    read THAT pile, not the Provinces.

    The plain ladder keys every green threshold to the Province count, so a
    Colony game with 2 Colonies left and 8 Provinces untouched reads as "no
    urgency" and the bot keeps buying economy while the game ends under it.

    **This is consulted BEFORE the Platinum rung, and the ordering is the
    point:** checked after it, a $9 hand with one Colony left still bought a
    Platinum — economy the game will end before the deck ever draws. Above $11
    there is nothing to decide (a Colony is both the best green and the best
    buy), so this stays quiet there.
    """
    policy = policy or COLONY_POLICY
    if policy not in ("v3", "v4") or not game.get("colony"):
        return None
    sup = game["supply"]
    if sup.get("Colony", 0) > _COLONY_GREEN_AT:
        return None
    coins = game["coins"]
    if coins >= 11:
        return None                     # the Colony rung owns this band
    if coins >= 8 and sup.get("Province", 0) > 0:
        return "Province"
    if 5 <= coins <= 7 and sup.get("Duchy", 0) > 0:
        return "Duchy"
    return None


def _bm_plus_buy(game, pid, policy=None):
    """What to buy this turn, before the endgame module gets a say.

    Order matters and is the published one: the Colony rungs outrank
    everything (a Colony game is a different economy), then the terminal that
    makes the money work, then the plain ladder.
    """
    green = _colony_green(game, pid, policy)
    if green is not None:
        return green
    colony = _colony_rungs(game, pid, policy)
    if colony is not None:
        return colony
    terminal = _wants_terminal(game, pid)
    if terminal is not None:
        # the terminal competes with the money rung at the same price; the
        # published order buys the drawer first (it is what makes the money
        # work), except when a Province is on the table
        if game["coins"] < 8 or game["supply"].get("Province", 0) <= 0:
            return terminal
    want = _want(game, pid)
    # Big Money's "really early: take Gold at $8" exception must NOT fire once
    # the game is ending — economy you will never get to spend is worth less
    # than the points on the table. Plain Big Money keeps the quirk (it is
    # faithful to the ladder as published); this rung is the one that reads a
    # clock, so it is the one that fixes it.
    if want == "Gold" and game["coins"] >= 8 \
            and bot_endgame.should_green(game, pid) \
            and game["supply"].get("Province", 0) > 0:
        return "Province"
    return want


def _pay_off_debt(game, pid, moves):
    """Debt (Empires) FIRST, or the bot never buys again.

    "When you have Debt tokens you can't buy anything. This is the only effect
    of having Debt" — so a tier that ignores it and buys an Engineer is locked
    out of the whole Supply for the rest of the game, quietly: no error, no
    stall, it just ends every turn with its coins unspent. Paying off as much
    as it can, as soon as it can, is also very close to optimal — the tokens do
    nothing but block, and money cannot be carried between turns.

    `spendable` is THE reader (it caps the payment at what this player can
    actually afford), so its value IS the largest legal payment. Returns None
    when there is no Debt or no money for it."""
    if not game["debt"].get(pid):
        return None
    n = engine.spendable(game, pid).get("debt", 0)
    if n <= 0:
        return None
    move = {"type": "spend", "what": "debt", "n": n}
    return move if move in moves else None


def _buy_or_fall_back(game, pid, want, moves):
    """Turn a wanted pile into a move, falling back to the money ladder.

    A plan can name a card that is not actually buyable — a Potion cost the
    tier cannot pay, a buy_gate (Grand Market with Coppers in play), a pile
    that emptied. Ending the turn on that is the worst outcome available: the
    coins are simply thrown away, silently, every turn the condition holds.
    Fall through to the ladder, and only then end the phase.
    """
    for candidate in (want, _want(game, pid)):
        if candidate is not None and {"type": "buy", "card": candidate} in moves:
            return {"type": "buy", "card": candidate}
    return {"type": "end_phase"}


def choose_bm_plus(game, pid, rng=None, policy=None):
    """`policy` overrides the Colony-game buy policy — the arena seam that lets
    colony variants play each other under CRN."""
    r = rng or random.Random()
    if game["pending_pid"] == pid:
        return _decision(game, pid, r, policy=True)

    moves = engine.legal_moves(game, pid)
    if game["phase"] == "action":
        # Unlike Big Money this tier OWNS Actions, so it plays them: villages
        # and cantrips first (they cost nothing and may find more), terminals
        # last. It only ever holds one kind of terminal, so no ordering
        # question arises beyond that.
        plays = [m for m in moves if m["type"] == "play_action"]
        if plays:
            plays.sort(key=lambda m: (traits(m["card"])["terminal"],
                                      -traits(m["card"])["plus_cards"]))
            return plays[0]
        return {"type": "end_phase"}

    # DEBT (Empires) FIRST — see _pay_off_debt.
    debt = _pay_off_debt(game, pid, moves)
    if debt is not None:
        return debt
    for m in moves:
        if m["type"] == "play_all_treasures":
            return m
    treasures = [m for m in moves if m["type"] == "play_treasure"]
    if treasures:
        return r.choice(treasures)

    want = bot_endgame.override(game, pid, _bm_plus_buy(game, pid, policy))
    return _buy_or_fall_back(game, pid, want, moves)


# ── the Strategist ───────────────────────────────────────────────────────────
# Tier 3. Three skills over Big Money+:
#   * a board READ (bot_plan) — an archetype and a buy menu, not one terminal;
#   * real action SEQUENCING, including the reshuffle rules;
#   * deck knowledge. That one needs no module: a server-side bot legitimately
#     holds the real game dict, so `seat["deck"]` IS the draw pile and its
#     length is the exact distance to the next reshuffle. The "tracking" a
#     human works years to approximate is free here, which is precisely what
#     the level-45 thread predicts about a bot.

def _plan(game, force=None):
    return bot_plan.plan_for(tuple(game["kingdom"]), bool(game.get("colony")),
                             len(game["players"]), force)


# How much money we will leave on the table to take a plan card instead of the
# money ladder's rung. Spending $6 on a $3 Village is how an engine bot ends up
# with no economy — "every non-money buy costs a Silver", and overpaying costs
# more than that.
_MENU_SLACK = 1


def _menu_buy(game, pid, force=None):
    """The first menu entry we can afford whose cap is not yet reached.

    Entries priced far below our coins are SKIPPED rather than bought: the
    money ladder gets those turns instead. Without this the engine plan spends
    every $6 and $7 hand on cheap pieces and never builds an economy — the
    "Village Idiot" / durdle failure the corpus names.
    """
    plan = _plan(game, force)
    owned = engine.owned_cards(game, pid)
    coins = game["coins"]
    for e in plan.menu:
        card = e["card"]
        if owned.count(card) >= e["count"]:
            continue
        if any(owned.count(pre) < n for pre, n in e["after"].items()):
            continue
        if game["supply"].get(card, 0) <= 0:
            continue
        cost = engine.cost(game, card)
        if cost > coins or cost < coins - _MENU_SLACK:
            continue
        if engine.buy_gate(game, pid, card) is not None:
            continue
        return card
    return None


def _strategist_buy(game, pid, force=None):
    plan = _plan(game, force)
    owned = engine.owned_cards(game, pid)
    coins = game["coins"]

    # Points first once the plan's clock says the deck is ready. An engine
    # greens late (it wants to draw itself first); money greens on the ladder.
    ready = len(owned) >= plan.green_at.get("deck", 0)
    if ready and bot_endgame.should_green(game, pid):
        colony = _colony_rungs(game, pid)
        if colony is not None:
            return colony
        if coins >= 8 and game["supply"].get("Province", 0) > 0:
            return "Province"

    # A rush plan buys its own green early and often — that IS the plan.
    if plan.archetype.startswith("rush:"):
        target = plan.archetype.split(":", 1)[1]
        if game["supply"].get(target, 0) > 0 \
                and engine.cost(game, target) <= coins \
                and engine.buy_gate(game, pid, target) is None:
            # keep building while the deck is still tiny, then flood
            if len(owned) >= plan.green_at.get("deck", 0):
                return target

    want = _menu_buy(game, pid, force)
    if want is not None:
        return want
    return _want(game, pid)                 # the money ladder underneath


def _action_sort_key(game, pid, card):
    """Play order. Non-terminals before terminals (they cost nothing and may
    find more to do), draw before payload (drawing can find payload, payload
    can never find draw), and cursers early so the split is contested."""
    t = traits(card)
    return (
        t["terminal"],                      # False sorts first
        not t["curser"],                    # cursers ahead of other terminals
        -t["plus_actions"],
        -t["plus_cards"],
        -t["plus_coins"],
    )


def _would_reshuffle(game, pid, card):
    """Would playing `card` draw past the end of the draw pile?

    Rule R3 from the reshuffle-control article: before playing a drawer, check
    `cards_needed > cards_left`. Free for us — `seat["deck"]` is the real draw
    pile.
    """
    need = traits(card)["plus_cards"]
    return need > 0 and need > len(game["seats"][pid]["deck"])


def _skip_for_reshuffle(game, pid, card):
    """Should we DECLINE to play this drawer to avoid a bad reshuffle?

    Only in the narrow case the article actually endorses: we are already at a
    buy threshold, the draw would trigger a reshuffle, and there is nothing the
    extra cards could buy that we cannot buy now. Greening decks also want to
    delay the shuffle so their green misses a pass.
    """
    if not _would_reshuffle(game, pid, card):
        return False
    if game["actions"] <= 1 and any(traits(c)["action"] and traits(c)["terminal"]
                                    for c in game["seats"][pid]["hand"]
                                    if c != card):
        return False                        # nothing else to do with the turn
    # already able to buy the best thing on our menu? then the draw is upside
    # only, and the reshuffle cost is real
    return bot_endgame.should_green(game, pid) and game["coins"] >= 8


def choose_strategist(game, pid, rng=None, force=None):
    """`force` names an archetype to play instead of the selector's pick — the
    seam the champion's tournament result comes back through."""
    r = rng or random.Random()
    if game["pending_pid"] == pid:
        return _decision(game, pid, r, policy=True)

    moves = engine.legal_moves(game, pid)
    if game["phase"] == "action":
        plays = [m for m in moves if m["type"] == "play_action"]
        if plays:
            plays.sort(key=lambda m: _action_sort_key(game, pid, m["card"]))
            for m in plays:
                if not _skip_for_reshuffle(game, pid, m["card"]):
                    return m
        return {"type": "end_phase"}

    # DEBT (Empires) FIRST — see _pay_off_debt.
    debt = _pay_off_debt(game, pid, moves)
    if debt is not None:
        return debt
    for m in moves:
        if m["type"] == "play_all_treasures":
            return m
    treasures = [m for m in moves if m["type"] == "play_treasure"]
    if treasures:
        return r.choice(treasures)

    want = bot_endgame.override(game, pid, _strategist_buy(game, pid, force))
    return _buy_or_fall_back(game, pid, want, moves)


# ── the Champion ─────────────────────────────────────────────────────────────
# Tier 4: the strategist's play, a plan chosen by TOURNAMENT rather than by
# rule, and buys decided by rollout search. See bot_champion for why the
# tournament is the smaller of the two levers.

def choose_champion(game, pid, rng=None):
    r = rng or random.Random()
    if game["pending_pid"] == pid:
        return _decision(game, pid, r, policy=True)

    force = bot_champion.pick_plan(tuple(game["kingdom"]),
                                   bool(game.get("colony")),
                                   len(game["players"]))
    tier = f"{STRATEGIST}:{force}" if force else bot_champion.BENCHMARK

    moves = engine.legal_moves(game, pid)
    if game["phase"] != "buy":
        return choose_strategist(game, pid, r, force=force)
    # DEBT (Empires) FIRST — see _pay_off_debt.
    debt = _pay_off_debt(game, pid, moves)
    if debt is not None:
        return debt
    for m in moves:
        if m["type"] == "play_all_treasures":
            return m
    treasures = [m for m in moves if m["type"] == "play_treasure"]
    if treasures:
        return r.choice(treasures)

    planned = _strategist_buy(game, pid, force)
    # The endgame module is not a suggestion the search may overrule: its
    # rules are exact (this buy wins now / this buy hands over the win), and a
    # noisy rollout estimate has no business second-guessing arithmetic.
    forced = bot_endgame.override(game, pid, planned)
    if forced != planned or game["coins"] < bot_champion.SEARCH_FROM_COINS:
        want = forced
    else:
        options = bot_champion.buy_candidates(game, pid, planned)
        want, _score = bot_champion.best_buy(game, pid, options, tier, r) \
            if len(options) > 1 else (planned, 0.0)
    if want is not None and {"type": "buy", "card": want} in moves:
        return {"type": "buy", "card": want}
    return {"type": "end_phase"}


def play_turn(game, pid, rng=None, max_steps=200, difficulty=None):
    """Drive pid until the actor is someone else / the game ends. Returns the
    moves played. Mirrors the sibling bots' shape (the scheduler's fallback)."""
    r = rng or random.Random()
    played = []
    for _ in range(max_steps):
        if engine.is_over(game):
            break
        if (game["pending_pid"] or game["turn"]) != pid:
            break
        mv = choose(game, pid, r, difficulty)
        ok, _err = engine.apply_move(game, pid, mv)
        if not ok:
            break
        played.append(mv)
    return played
