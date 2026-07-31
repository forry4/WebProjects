"""The bots, one strategy per rung of the ladder, selected by `ai_difficulty`:

* ``random``   — uniform over legal moves (v1; the easy/normal/hard tiers).
* ``bigmoney`` — the classic Big Money buy ladder. Buys ONLY Treasure and
  Victory, never an Action, and greens on a Province-count clock. It is a real
  opponent: the random bot mostly buys Coppers and Curses and rarely finishes a
  Province.
* ``bmplus``   — Big Money that READS THE BOARD: it picks the kingdom's best
  terminal (the published Terminal-Draw-BM ranking), plays its Actions, buys
  Colonies/Platinum in a colony game, and hands every buy to `bot_endgame` for
  the Penultimate Province Rule and pile control.

Each rung is the one below it plus a NAMED skill, so the ladder reads like
playing better humans rather than different species.

`choose` is the server scheduler's guaranteed turn-finisher: for EVERY strategy
it must return a valid move for ANY state where (pending_pid or turn) == pid,
and it must never consume the game's own rng_state (pass an explicit rng).
"""

import random

from . import bot_decisions, bot_endgame, engine
from .bot_traits import best_bm_terminal, traits

# ai_difficulty values that route to a real strategy. Everything else
# (easy/normal/hard) is still the random-legal bot.
BIG_MONEY = "bigmoney"
BM_PLUS = "bmplus"


def choose(game, pid, rng=None, difficulty=None):
    """ONE move for pid. `difficulty` is the room's persisted tier."""
    if difficulty == BIG_MONEY:
        return choose_big_money(game, pid, rng)
    if difficulty == BM_PLUS:
        return choose_bm_plus(game, pid, rng)
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

_MAX_TERMINALS = 2          # the published cap for a BM deck
_SECOND_TERMINAL_DECK = 16  # "add the 2nd Smithy at ~16-18 cards"
# Cards good enough to buy a second copy of; the article singles out the
# 5-card drawers as the ones that collide too hard to double up.
_SINGLE_COPY = {"Council Room", "Magnate", "Witch's Hut"}


def _bm_terminal(game, pid):
    """The kingdom's best Big Money terminal, or None on a board with none."""
    return best_bm_terminal(game["kingdom"], game["supply"])


def _terminals_owned(game, pid, card):
    return engine.owned_cards(game, pid).count(card)


def _wants_terminal(game, pid):
    """Should we buy (another copy of) our terminal at these coins?"""
    card = _bm_terminal(game, pid)
    if card is None or engine.cost(game, card) > game["coins"]:
        return None
    if game["supply"].get(card, 0) <= 0:
        return None
    if engine.buy_gate(game, pid, card) is not None:
        return None
    have = _terminals_owned(game, pid, card)
    if have == 0:
        return card
    cap = 1 if card in _SINGLE_COPY else _MAX_TERMINALS
    if have >= cap:
        return None
    # the second copy waits for the deck to be big enough to absorb it
    if len(engine.owned_cards(game, pid)) >= _SECOND_TERMINAL_DECK:
        return card
    return None


def _colony_rungs(game, pid):
    """Platinum/Colony, which plain Big Money deliberately ignores."""
    if not game.get("colony"):
        return None
    coins = game["coins"]
    if coins >= 11 and game["supply"].get("Colony", 0) > 0:
        return "Colony"
    if 9 <= coins <= 10 and game["supply"].get("Platinum", 0) > 0:
        # a Platinum is worth more than the Gold this would otherwise buy, and
        # 2.2 density is what a Colony game actually needs
        return "Platinum"
    return None


def _bm_plus_buy(game, pid):
    """What to buy this turn, before the endgame module gets a say.

    Order matters and is the published one: the Colony rungs outrank
    everything (a Colony game is a different economy), then the terminal that
    makes the money work, then the plain ladder.
    """
    colony = _colony_rungs(game, pid)
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


def choose_bm_plus(game, pid, rng=None):
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

    for m in moves:
        if m["type"] == "play_all_treasures":
            return m
    treasures = [m for m in moves if m["type"] == "play_treasure"]
    if treasures:
        return r.choice(treasures)

    want = bot_endgame.override(game, pid, _bm_plus_buy(game, pid))
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
