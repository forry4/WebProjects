"""The Champion — the tier that MEASURES instead of knowing.

Two levers, in the order the evidence supports them:

1. **A per-kingdom plan tournament.** At game start, play every candidate plan
   this board supports off against the benchmark by self-play and keep the
   winner. `bmplus` is itself a candidate, which is what makes this safe: the
   champion can only adopt a plan that beat the tier below it ON THIS BOARD,
   so a plan that is wrong here costs nothing.

2. **Rollout buy evaluation.** On buys that matter, simulate each candidate
   purchase to the end of the game and take the one that wins most often.
   This is the lever the hand-written tiers structurally cannot have: "a
   simulator does not understand risk" is true of a buy TABLE, not of a search
   that plays the position out.

Why the tournament is not the main lever, measured rather than assumed: an
oracle that picks the best hand-written plan per board beats Big Money+ by only
~0.60 (and that number is optimistic — it selects on the same trials it scores
on), because "money" is simply the right answer on ~75% of boards. Hand-written
archetypes are not where the strength is. Search is.

**Rollouts determinize.** The bot holds the real game dict, so it can see deck
ORDER — the one thing a player genuinely cannot know. Every rollout reshuffles
every seat's draw pile first, which keeps the search honest rather than letting
it read the future (the cross-game rule: determinization is a correctness
requirement, not a strength knob).

**Nothing here may run under ROOM_LOCK.** The server drives this through an
executor; see `main._schedule_bots`.
"""

import copy
import functools
import random

from . import bot_plan, engine

# The tournament's opponent and the rollout policy. Deliberately the tier
# BELOW: rollouts must be fast and must never recurse into the champion.
BENCHMARK = "bmplus"

TOURNAMENT_TRIALS = 8       # CRN pairs per candidate
# How far a candidate must beat the benchmark before we abandon a tier that is
# already measured to win. With 8 trials a coin-flip plan clears 0.5 about a
# third of the time, and the hand-written archetypes are measurably WORSE than
# the benchmark (engine 0.231, rush 0.000), so "better than 0.5" adopts a
# losing plan far more often than it finds a winning one.
TOURNAMENT_MARGIN = 0.65
ROLLOUTS = 12               # paired simulations per candidate buy
ROLLOUT_MOVE_CAP = 4000
# Buys worth searching. Below this the ladder's answer is not in doubt and the
# rollouts are noise; a full search on every $3 Silver would spend the whole
# budget proving what the ladder already knows.
SEARCH_FROM_COINS = 5


def _bot():
    """Imported lazily — bot imports this module for the tier dispatch."""
    from . import bot
    return bot


# ── 1. the plan tournament ───────────────────────────────────────────────────

def _play_out(game, tiers, rng, cap=ROLLOUT_MOVE_CAP):
    """Drive `game` to the end with each seat on its tier. Mutates `game`."""
    bot = _bot()
    players = game["players"]
    by_seat = {p: tiers[i % len(tiers)] for i, p in enumerate(players)}
    for _ in range(cap):
        if game["over"]:
            break
        pid = game["pending_pid"] or game["turn"]
        mv = bot.choose(game, pid, rng, by_seat[pid])
        ok, _err = engine.apply_move(game, pid, mv)
        if not ok:
            break
    return game


def _trial(kingdom, colony, players, tier, seed):
    """One CRN pair: `tier` in each seat against the benchmark. 0..1."""
    won = 0.0
    for swap in (False, True):
        tiers = [BENCHMARK, tier] if swap else [tier, BENCHMARK]
        g = engine.new_game(list(players), ["base"], seed=seed,
                            kingdom=list(kingdom))
        _play_out(g, tiers, random.Random(seed))
        seat = players[1] if swap else players[0]
        win = set(engine.winners(g))
        won += (1.0 / len(win)) if seat in win and win else 0.0
    return won / 2.0


@functools.lru_cache(maxsize=256)
def pick_plan(kingdom, colony=False, n_players=2, trials=TOURNAMENT_TRIALS):
    """The archetype to play on this board, or None to play the benchmark.

    Cached on the kingdom, so a reconnect or a reload recomputes nothing and
    the answer cannot drift mid-game.
    """
    players = tuple(f"t{i}" for i in range(n_players))
    best, best_score = None, TOURNAMENT_MARGIN
    for plan in bot_plan.candidates(kingdom, colony, n_players):
        tier = f"{_bot().STRATEGIST}:{plan.archetype}"
        score = sum(_trial(kingdom, colony, players, tier, 7000 + i)
                    for i in range(trials)) / trials
        if score > best_score:
            best, best_score = plan.archetype, score
    return best


# ── 2. rollout buy evaluation ────────────────────────────────────────────────

def _determinize(game, rng):
    """Reshuffle every seat's draw pile. Deck ORDER is the hidden information
    in Dominion — contents are public knowledge to anyone counting — so this
    is exactly the resampling the search is entitled to do."""
    for seat in game["seats"].values():
        rng.shuffle(seat["deck"])
    return game


def _one_rollout(game, pid, card, tier, seed):
    """Play the position out once after committing to `card`. 1.0 = pid won.

    `card is None` means BUY NOTHING, and it has to be committed to like any
    other choice — by ending the phase. Letting the rollout continue in the
    buy phase instead does not evaluate passing, it hands the position to a
    fresh policy that buys something anyway, so "nothing" scored 0.75 against
    every real buy's 0.2 and the search passed on turn after turn.
    """
    g = copy.deepcopy(game)
    g["log"] = []                       # the log is pure overhead in a rollout
    g["undo_stack"] = []
    move = ({"type": "buy", "card": card} if card is not None
            else {"type": "end_phase"})
    ok, _err = engine.apply_move(g, pid, move)
    if not ok:
        return None
    rng = random.Random(seed)
    _determinize(g, rng)
    _play_out(g, [tier], rng)
    win = set(engine.winners(g))
    if not win:
        return None                     # hit the cap — no evidence either way
    return (1.0 / len(win)) if pid in win else 0.0


def best_buy(game, pid, options, tier, rng, rollouts=None):
    """The option with the best simulated win rate, evaluated with COMMON
    RANDOM NUMBERS: rollout i uses the same seed for every candidate, so the
    shuffle and the opponent's luck are identical across the comparison and
    only the decision differs.

    This is the same trick the arena uses between tiers, and it matters far
    more here: independent rollouts put a ~0.14 standard error on each estimate,
    which is wider than the gap between buying a Gold and buying a Province.
    Measured unpaired, three identical batches of 12 scored the same buy at
    0.417 / 0.167 / 0.250 — the search was reading noise and overruling a
    well-tuned ladder with it.
    """
    if not options:
        return None, 0.0
    # read at CALL time, not as a default argument: a default binds once at
    # def time, so a sweep that patches the module constant silently measures
    # the same depth three times (it did — 6, 24 and 96 rollouts all returned
    # 0.375 to three decimals, which is what gave the bug away).
    rollouts = rollouts or ROLLOUTS
    base = rng.randrange(1 << 30)
    totals = {i: 0.0 for i in range(len(options))}
    counts = {i: 0 for i in range(len(options))}
    for r in range(rollouts):
        seed = base + r
        for i, card in enumerate(options):
            got = _one_rollout(game, pid, card, tier, seed)
            if got is not None:
                totals[i] += got
                counts[i] += 1
    best_i, best_score = 0, float("-inf")
    for i in range(len(options)):
        score = totals[i] / counts[i] if counts[i] else -1.0
        if score > best_score:
            best_i, best_score = i, score
    return options[best_i], best_score


def buy_candidates(game, pid, planned, limit=3):
    """The shortlist worth simulating: what the plan wants, the money rungs
    around it, and passing. Kept short — each entry costs `ROLLOUTS` games."""
    out = []
    coins = game["coins"]
    for card in (planned, "Province", "Colony", "Gold", "Duchy"):
        if card is None or card in out:
            continue
        if game["supply"].get(card, 0) <= 0:
            continue
        if engine.cost(game, card) > coins:
            continue
        if engine.buy_gate(game, pid, card) is not None:
            continue
        out.append(card)
        if len(out) >= limit:
            break
    if planned is None and not out:
        return []
    out.append(None)                    # "buy nothing" is on the table
    return out
