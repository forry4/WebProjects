"""HOW MANY copies of its terminal should Big Money+ buy, and when?

The quantities in `bot._wants_terminal` came from the Terminal-Draw-BM article
and have never been measured: a cap of 2, the second copy withheld until the
deck reaches 16 cards, and three named cards capped at 1. Each is a plausible
rule of thumb standing in for a number nobody has checked.

Two reasons to expect the defaults to be wrong somewhere:

* **Cards differ.** A cheap cantrip-ish drawer and a $5 terminal attack do not
  want the same count, and the article's own advice is card-by-card ("2
  Smithies, exactly 1 Envoy").
* **Games differ in LENGTH.** A Colony game runs many more turns, so a second
  copy has far more turns to pay for itself. A single global cap cannot express
  that.

Both knobs are module constants read at CALL time, so the harness sets them per
move and plays two settings against each other inside one CRN-paired game.

    python -m games.dontminion.tools.bm_quantity_sweep caps
    python -m games.dontminion.tools.bm_quantity_sweep caps --colony
    python -m games.dontminion.tools.bm_quantity_sweep timing
    python -m games.dontminion.tools.bm_quantity_sweep percard -n 20
"""

import argparse
import random
import sys

from .. import bot, engine
from ..bot_traits import BM_TERMINALS
from ..cards import CARDS

EXPS = ["base", "intrigue", "seaside", "prosperity", "hinterlands",
        "cornucopia", "alchemy", "darkages"]

# The defaults every arm is measured against.
BASE = {"cap": 2, "deck": 16}


def _apply(knobs):
    bot._MAX_TERMINALS = knobs["cap"]
    bot._SECOND_TERMINAL_DECK = knobs["deck"]


def play(seed, knobs_a, knobs_b, kingdom=None, exps=EXPS):
    """One CRN pair: knobs_a in each seat against knobs_b. Returns a's share."""
    won = 0.0
    for swap in (False, True):
        settings = [knobs_b, knobs_a] if swap else [knobs_a, knobs_b]
        g = engine.new_game(["p1", "p2"], exps, seed=seed, kingdom=kingdom)
        rngs = {p: random.Random(seed * 977 + i)
                for i, p in enumerate(g["players"])}
        by_seat = {p: settings[i] for i, p in enumerate(g["players"])}
        for _ in range(40000):
            if g["over"]:
                break
            pid = g["pending_pid"] or g["turn"]
            _apply(by_seat[pid])
            ok, err = engine.apply_move(g, pid,
                                        bot.choose(g, pid, rngs[pid],
                                                   bot.BM_PLUS))
            if not ok:
                raise AssertionError(err)
        _apply(BASE)
        if not g["over"]:
            raise AssertionError(f"seed {seed} never ended")
        seat = g["players"][1] if swap else g["players"][0]
        win = set(engine.winners(g))
        won += (1.0 / len(win)) if seat in win and win else 0.0
    return won / 2.0


def duel(knobs_a, knobs_b, seeds, kingdom=None):
    tot = sum(play(s, knobs_a, knobs_b, kingdom) for s in seeds)
    n = len(seeds) * 2
    return tot / len(seeds), n


def report(label, wr, n):
    se = (0.25 / n) ** 0.5
    sig = "*** SIGNIFICANT" if abs(wr - 0.5) > 1.96 * se else "(n.s.)"
    print(f"  {label:34s} {wr:.4f} +-{1.96 * se:.3f}  n={n}  {sig}", flush=True)


def colony_seeds(want, start=0):
    out, s = [], start
    while len(out) < want:
        g = engine.new_game(["p1", "p2"], EXPS, seed=s)
        if g.get("colony"):
            out.append(s)
        s += 1
    return out


def board_for(card):
    """A board where `card` is the only terminal worth buying."""
    filler = [f for f in ["Moneylender", "Chapel", "Gardens", "Workshop",
                          "Harbinger", "Vassal", "Cellar", "Mine", "Village"]
              if f != card][:9]
    return sorted([card] + filler)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=["caps", "timing", "percard"])
    ap.add_argument("-n", "--boards", type=int, default=40)
    ap.add_argument("--colony", action="store_true",
                    help="colony boards only — the long-game question")
    ap.add_argument("cards", nargs="*",
                    help="percard: measure these cards instead of the top 12")
    a = ap.parse_args(argv)

    if a.colony:
        seeds = colony_seeds(a.boards)
        where = "COLONY boards"
    else:
        seeds = list(range(6000, 6000 + a.boards))
        where = "random boards"

    if a.mode == "caps":
        print(f"Terminal COUNT cap, {where} (baseline = cap 2, deck 16)\n")
        for cap in (1, 3, 4):
            wr, n = duel({"cap": cap, "deck": 16}, BASE, seeds)
            report(f"cap {cap} vs cap 2", wr, n)

    elif a.mode == "timing":
        print(f"When the SECOND copy is allowed, {where} "
              f"(baseline = deck 16)\n")
        for deck in (0, 8, 12, 20, 26):
            wr, n = duel({"cap": 2, "deck": deck}, BASE, seeds)
            report(f"second copy at deck>={deck:2d} vs >=16", wr, n)

    else:  # percard
        cards = a.cards or [c for c in sorted(BM_TERMINALS,
                                              key=BM_TERMINALS.get,
                                              reverse=True)
                            if CARDS[c]["expansion"] in EXPS][:12]
        print(f"Per-card cap on a board where that card is the ONLY terminal "
              f"({len(seeds)} boards each)\n")
        print(f"  {'card':20s} {'cap1':>16s} {'cap3':>16s}")
        for card in cards:
            kd = board_for(card)
            exps = sorted({CARDS[c]["expansion"] for c in kd})
            try:
                w1, n = duel({"cap": 1, "deck": 16}, BASE, seeds, kd)
                w3, _ = duel({"cap": 3, "deck": 16}, BASE, seeds, kd)
            except AssertionError as e:
                print(f"  {card:20s} SKIPPED ({e})")
                continue
            se = (0.25 / n) ** 0.5
            m = lambda w: f"{w:.3f}{'*' if abs(w-0.5) > 1.96*se else ' '}"
            print(f"  {card:20s} {m(w1):>16s} {m(w3):>16s}", flush=True)
        print(f"\n  (* = differs from the cap-2 default beyond noise, "
              f"+-{1.96 * (0.25 / (len(seeds)*2))**0.5:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
