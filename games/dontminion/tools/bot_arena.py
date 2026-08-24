"""The bot arena — CRN-paired offline measurement. Never in a serving path.

Usage:
    python -m games.dontminion.tools.bot_arena bigmoney easy -n 100
    python -m games.dontminion.tools.bot_arena bmplus bigmoney -n 200 -e base,intrigue
    python -m games.dontminion.tools.bot_arena --mirror bigmoney -n 50

**Common Random Numbers, and the mirror must read exactly 0.5000.** Each
"pair" is the same seed played twice with the tiers swapped between the two
seats, so the kingdom, both opening decks and every seat's bot rng are shared
across the pair — the only difference is which tier sits where. Two
consequences, both load-bearing:

* Seat advantage cancels inside the pair, so a small real edge is visible at
  sample sizes where raw win counts are still noise (Dominion's first-player
  advantage is ~51/42 in a Big Money mirror — bigger than most gains we are
  trying to measure).
* The rng is keyed on the SEAT, not the tier. A tier played against itself
  therefore produces two byte-identical games per pair, one win each, so
  `--mirror` reads exactly 0.5000. Anything else means the harness leaked
  state between games and every number it prints is suspect.

The ship criterion for a new tier is beating the tier below it at >= 0.60
(theory's 60/40 calibration for a one-level skill gap), never losing the pace
anchors (pure Big Money reaches 4 Provinces around turn 17; +Smithy around 14).
"""

import argparse
import random
import statistics
import sys
import time

from .. import bot, engine

MOVE_CAP = 20000            # a game that needs more is a livelock, not a game
PLAYERS = ("p1", "p2", "p3", "p4")


def play_one(seed, tiers, expansions, kingdom=None, n_players=2):
    """One game. `tiers[i]` is the difficulty for seat i.

    Every seat gets its own rng, seeded from (seed, seat INDEX) — never from
    the tier — so swapping tiers between seats leaves the entropy untouched.
    """
    players = list(PLAYERS[:n_players])
    g = engine.new_game(players, expansions, seed=seed, kingdom=kingdom)
    rngs = {p: random.Random((seed << 8) + i) for i, p in enumerate(players)}
    by_seat = {p: tiers[i] for i, p in enumerate(players)}
    fourth_province = None
    moves = 0
    for _ in range(MOVE_CAP):
        if g["over"]:
            break
        pid = g["pending_pid"] or g["turn"]
        mv = bot.choose(g, pid, rngs[pid], by_seat[pid])
        ok, err = engine.apply_move(g, pid, mv)
        if not ok:
            raise AssertionError(f"seat {pid} ({by_seat[pid]}) played {mv}: {err}")
        moves += 1
        if fourth_province is None:
            for p in players:
                if engine.owned_cards(g, p).count("Province") >= 4:
                    fourth_province = g["seats"][p]["turns_taken"]
                    break
    if not g["over"]:
        raise AssertionError(f"game {seed} hit the move cap ({MOVE_CAP})")
    score = engine.score_game(g)
    win = set(engine.winners(g))
    return {
        "vp": {p: score[p]["vp"] for p in players},
        "turns": max(score[p]["turns"] for p in players),
        "share": {p: (1.0 / len(win) if p in win else 0.0) for p in players},
        "fourth_province": fourth_province,
        "empty_piles": engine.count_empty_piles(g),
        "moves": moves,
    }


def duel(tier_a, tier_b, n_pairs, expansions, start=0, n_players=2, quiet=False):
    """`n_pairs` CRN pairs of tier_a vs tier_b. Returns tier_a's stats."""
    wins_a = 0.0
    games = 0
    turns, vps_a, vps_b, paces, empties = [], [], [], [], []
    filler = [tier_b] * (n_players - 2)
    t0 = time.perf_counter()
    for k in range(n_pairs):
        seed = start + k
        for swap in (False, True):
            tiers = ([tier_b, tier_a] if swap else [tier_a, tier_b]) + filler
            r = play_one(seed, tiers, expansions, n_players=n_players)
            seat_a = PLAYERS[1] if swap else PLAYERS[0]
            seat_b = PLAYERS[0] if swap else PLAYERS[1]
            wins_a += r["share"][seat_a]
            vps_a.append(r["vp"][seat_a])
            vps_b.append(r["vp"][seat_b])
            turns.append(r["turns"])
            empties.append(r["empty_piles"])
            if r["fourth_province"] is not None:
                paces.append(r["fourth_province"])
            games += 1
        if not quiet and (k + 1) % 25 == 0:
            print(f"  ...{k + 1}/{n_pairs} pairs, {tier_a} at "
                  f"{wins_a / games:.4f}", file=sys.stderr)
    return {
        "tier_a": tier_a, "tier_b": tier_b, "games": games,
        "win_rate": wins_a / games,
        "vp_a": statistics.mean(vps_a), "vp_b": statistics.mean(vps_b),
        "turns": statistics.mean(turns),
        "pace_4p": statistics.mean(paces) if paces else None,
        "empty_piles": statistics.mean(empties),
        "seconds": time.perf_counter() - t0,
    }


def report(res):
    n = res["games"]
    # binomial standard error on the paired result
    se = (0.25 / n) ** 0.5
    lo, hi = res["win_rate"] - 1.96 * se, res["win_rate"] + 1.96 * se
    print(f"\n{res['tier_a']} vs {res['tier_b']}   {n} games "
          f"({n // 2} CRN pairs, {res['seconds']:.1f}s, "
          f"{n / res['seconds']:.1f} games/s)")
    print(f"  win rate   {res['win_rate']:.4f}   95% CI [{lo:.4f}, {hi:.4f}]"
          f"{'   *** significant' if lo > 0.5 or hi < 0.5 else '   (n.s.)'}")
    print(f"  mean VP    {res['vp_a']:.1f} vs {res['vp_b']:.1f}")
    print(f"  game len   {res['turns']:.1f} turns, "
          f"{res['empty_piles']:.2f} empty piles")
    if res["pace_4p"] is not None:
        print(f"  pace       4th Province on turn {res['pace_4p']:.1f} "
              f"(anchors: pure BM ~17, BM+Smithy ~14)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tiers", nargs="+", help="tier_a tier_b (or one with --mirror)")
    ap.add_argument("-n", "--pairs", type=int, default=50)
    ap.add_argument("-e", "--expansions", default="base",
                    help="comma-separated; 'all' for every set")
    ap.add_argument("-p", "--players", type=int, default=2)
    ap.add_argument("-s", "--start", type=int, default=0, help="first seed")
    ap.add_argument("--mirror", action="store_true",
                    help="play the tier against itself; MUST read 0.5000")
    a = ap.parse_args(argv)
    exps = (["base", "intrigue", "seaside", "prosperity", "hinterlands"]
            if a.expansions == "all" else a.expansions.split(","))
    if a.mirror:
        res = duel(a.tiers[0], a.tiers[0], a.pairs, exps,
                   start=a.start, n_players=a.players)
        report(res)
        ok = abs(res["win_rate"] - 0.5) < 1e-9
        print(f"\n  mirror sanity: {'PASS' if ok else 'FAIL'} "
              f"({res['win_rate']:.6f}, must be exactly 0.500000)")
        return 0 if ok else 1
    if len(a.tiers) != 2:
        ap.error("give two tiers, or one tier with --mirror")
    report(duel(a.tiers[0], a.tiers[1], a.pairs, exps,
                start=a.start, n_players=a.players))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
