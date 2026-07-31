"""The bots. Two strategies today, selected by the room's `ai_difficulty`:

* ``random``   — uniform over legal moves (v1; the easy/normal/hard tiers).
* ``bigmoney`` — the classic Big Money buy ladder. Buys ONLY Treasure and
  Victory, never an Action, and greens on a Province-count clock. It is a real
  opponent: the random bot mostly buys Coppers and Curses and rarely finishes a
  Province.

`choose` is the server scheduler's guaranteed turn-finisher: for EVERY strategy
it must return a valid move for ANY state where (pending_pid or turn) == pid,
and it must never consume the game's own rng_state (pass an explicit rng).
"""

import random

from . import engine

# ai_difficulty values that route to the Big Money buy ladder. Everything else
# (easy/normal/hard) is still the random-legal bot.
BIG_MONEY = "bigmoney"


def choose(game, pid, rng=None, difficulty=None):
    """ONE move for pid. `difficulty` is the room's persisted tier."""
    if difficulty == BIG_MONEY:
        return choose_big_money(game, pid, rng)
    return choose_random(game, pid, rng)


def choose_random(game, pid, rng=None):
    """Uniform over legal moves with the sibling bots' anti-stall bias: never
    end a phase while something else is possible (an unbiased bot ends its turn
    instantly ~1/N of the time and the game crawls). Decisions are answered with
    `engine.sample_decision` — uniform over the frame's valid payloads."""
    r = rng or random.Random()
    if game["pending_pid"] == pid:
        return {"type": "decision", **engine.sample_decision(game, pid, r)}
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
        # No card-specific play, so a forced choice (an opponent's Militia, a
        # Curse handed over) is answered uniformly, same as the random bot.
        return {"type": "decision", **engine.sample_decision(game, pid, r)}

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
