"""Self-play calibration for SKAT mode's server-bot thresholds under CARD
SCORING (2026-08-09: captured cards score -- 9/10/J/Q +2, 7/8/K/A -1 -- so the
bid ladder's levels price a ~13-point deal-dependent pool instead of the old
+5 parity pool, and every threshold in `bot.py` needed re-anchoring).

Drives whole bot-vs-bot rounds through the real engine (`bot.act` both seats,
`engine.apply_move` applying) and reports: the hand-strength distribution the
level map keys on, the settled bid/level distributions, contracts made by
level, Null consolations, overtricks, mean winning payoff and the implied
rounds-to-target -- the numbers `_SKAT_LEVEL_NEEDS`, `_KONTRA_TARGET` and
`_KONTRA_STRENGTH` were placed with.

    PYTHONPATH=. python -m games.dissonance.tools.skat_calibration [rounds]

Not a strength arena (both seats are the same bot; there is no edge to read)
-- it is the distribution check, the cheap Python end of a proper `skatlab`
sweep on the Rust side.
"""

from __future__ import annotations

import random
import sys
from collections import Counter

from games.dissonance import bot, engine as E


def _move_of(kind, mv):
    """`bot.act`'s answer as an `apply_move` dict -- main.py's own mapping."""
    if kind == "move":
        return mv
    if kind == "play":
        return {"kind": "play", "card": mv}
    if kind == "swap":
        return {"kind": "swap", "take": mv.get("take"), "give": mv.get("give")}
    if mv.get("pass"):
        return {"kind": "pass"}
    return {"kind": "bid", "level": mv["level"], "denom": mv["denom"]}


def play_round(rng: random.Random) -> dict:
    g = E.new_game(["a", "b"], rng, opener=rng.randrange(2), mode="skat")
    guard = 0
    while g["phase"] != "over":
        seat = E.turn_seat(g)
        if seat is None:
            break
        kind, mv = bot.act(g, seat, rng)
        E.apply_move(g, g["seats"][seat], _move_of(kind, mv))
        guard += 1
        if guard > 400:
            raise RuntimeError("round did not terminate")
    return g


def sweep(n: int, seed: int = 7) -> None:
    rng = random.Random(seed)
    levels: Counter[int] = Counter()
    made_at: Counter[int] = Counter()
    bids: Counter[int] = Counter()
    strengths = []
    dpts = []
    pools = []
    shorts = []
    overs = []
    made = null = 0
    pay = []
    for _ in range(n):
        g = play_round(rng)
        res = g["result"]
        levels[res["level"]] += 1
        bids[res["bid"]] += 1
        made += bool(res.get("made"))
        made_at[res["level"]] += bool(res.get("made"))
        if not res.get("made") and not res.get("null"):
            shorts.append(res.get("short", 0))
        if res.get("made"):
            overs.append(res.get("over", 0))
        null += bool(res.get("null"))
        pay.append(max(res["scores"]))
        dpts.append(res["declarer_pts"])
        pools.append(E.played_pool(g))
        assert sum(g["pts"]) == E.played_pool(g), (g["pts"], E.played_pool(g))
        # The strength scale the level map keys on, from a fresh deal.
        probe = E.new_game(["a", "b"], rng, mode="skat")
        strengths.append(max(bot.hand_strength(probe, 0, d)
                             for d in E.SKAT_DENOMS))
    def pct(v, q):
        s = sorted(v)
        return s[min(len(s) - 1, int(q * len(s)))]
    mean_pay = sum(pay) / n
    target = E.MATCH_TARGET["skat"]
    print(f"\n== skat / card scoring  ({n} rounds) ==")
    print(f"pool: mean {sum(pools) / n:.1f}  range {min(pools)}..{max(pools)}")
    print(f"declarer pts: mean {sum(dpts) / n:.1f}  "
          f"p10 {pct(dpts, .1)}  p50 {pct(dpts, .5)}  p90 {pct(dpts, .9)}")
    print(f"best-denom strength: p50 {pct(strengths, .5):.1f}  "
          f"p75 {pct(strengths, .75):.1f}  p90 {pct(strengths, .9):.1f}  "
          f"p99 {pct(strengths, .99):.1f}")
    print("settled bids:",
          " ".join(f"{b}:{100 * bids[b] / n:.0f}%" for b in sorted(bids)))
    print("declared levels:",
          " ".join(f"{l}:{100 * levels[l] / n:.0f}%" for l in sorted(levels)))
    print("made by level:",
          " ".join(f"{l}:{100 * made_at[l] / levels[l]:.0f}%"
                   for l in sorted(levels)))
    med_short = sorted(shorts)[len(shorts) // 2] if shorts else 0
    med_over = sorted(overs)[len(overs) // 2] if overs else 0
    print(f"made {100 * made / n:.0f}%   null {100 * null / n:.0f}%   "
          f"median shortfall {med_short}   median overtricks {med_over}")
    print(f"mean winning payoff {mean_pay:.1f}   "
          f"~rounds to {target}: {target / mean_pay:.1f}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    sweep(n)
