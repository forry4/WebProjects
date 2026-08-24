"""Self-play calibration for MINOR mode's server-bot thresholds and payoffs.

Drives whole bot-vs-bot rounds through the real engine (`bot.act` both seats,
`engine.apply_move` applying) and reports, per mode: the settled-level
distribution, contracts made, Null consolations, mean winning payoff, and the
implied rounds-to-target -- the numbers `_MINOR_LEVEL_NEEDS` and
`MATCH_TARGET["minor"]` were placed against classic's baseline with.

    PYTHONPATH=. python -m games.dissonance.tools.minor_calibration [rounds]

Not a strength arena (both seats are the same bot; there is no edge to read)
-- it is the distribution check SKAT_MODE.md's open questions describe, the
cheap Python end of a proper `skatlab` sweep.
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


def play_round(mode: str, rng: random.Random) -> dict:
    g = E.new_game(["a", "b"], rng, opener=rng.randrange(2), mode=mode)
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


def sweep(mode: str, n: int, seed: int = 7) -> None:
    rng = random.Random(seed)
    levels: Counter[int] = Counter()
    made_at: Counter[int] = Counter()
    shorts = []
    made = null = 0
    pay = []
    for _ in range(n):
        g = play_round(mode, rng)
        res = g["result"]
        levels[res["level"]] += 1
        made += bool(res.get("made"))
        made_at[res["level"]] += bool(res.get("made"))
        if not res.get("made") and not res.get("null"):
            shorts.append(res.get("short", 0))
        null += bool(res.get("null"))
        pay.append(max(res["scores"]))
        pool = E.pool_for(mode)
        assert sum(g["pts"]) == pool, (mode, g["pts"], pool)
    mean_pay = sum(pay) / n
    target = E.MATCH_TARGET[mode]
    print(f"\n== {mode}  ({n} rounds) ==")
    print("settled levels:",
          " ".join(f"{l}:{100 * levels[l] / n:.0f}%" for l in sorted(levels)))
    print("made by level:",
          " ".join(f"{l}:{100 * made_at[l] / levels[l]:.0f}%"
                   for l in sorted(levels)))
    med_short = sorted(shorts)[len(shorts) // 2] if shorts else 0
    print(f"made {100 * made / n:.0f}%   null {100 * null / n:.0f}%   "
          f"median shortfall {med_short}   mean winning payoff {mean_pay:.1f}   "
          f"~rounds to {target}: {target / mean_pay:.1f}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    for mode in ("classic", "minor"):
        sweep(mode, n)
