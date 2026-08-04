"""Which cards are worth buying as Big Money's terminal? MEASURE, don't guess.

`bot_traits.BM_TERMINALS` decides what `bmplus` buys, and it was hand-written
from the Terminal-Draw-BM article — which predates half the roster. A card
missing from it scores 0 and is INVISIBLE to the tier, so a new expansion's
best drawer is silently never bought; a card wrongly in it is bought over a
Silver every game.

The test here is the one that matters and the one the article itself frames:
**is buying this card better than buying nothing but money?** For each
candidate the sweep plays `bmplus` forced to use that card as its terminal
against `bmplus` forced to use NO terminal, CRN-paired, on boards built so the
candidate is the only Action worth having.

    python -m games.dontminion.tools.bm_terminal_sweep            # unranked only
    python -m games.dontminion.tools.bm_terminal_sweep --all -n 30

Reading the output: >0.5 means the card earns its place. The magnitude is what
the rank should reflect — it is a measured ordering, not an opinion.
"""

import argparse
import random
import sys

from .. import bot, engine
from ..bot_traits import BM_TERMINALS, traits
from ..cards import CARDS, KINGDOM

# Filler that gives the deck nothing to do: no draw, no payload, no +Buy. It
# keeps the candidate the ONLY thing the tier could want, so the comparison is
# "this card vs money", not "this card vs that other card".
FILLER = ["Moneylender", "Chapel", "Gardens", "Workshop", "Harbinger",
          "Vassal", "Cellar", "Bureaucrat", "Mine"]


def candidates(include_ranked=False):
    """Cards shaped like a Big Money terminal: a terminal that draws, or a
    terminal attack. Potion costs are excluded — this tier buys no Potion, so
    it could never pay for one (and naming one used to waste the whole turn)."""
    out = []
    for names in KINGDOM.values():
        for n in sorted(names):
            if not include_ranked and n in BM_TERMINALS:
                continue
            t = traits(n)
            if CARDS[n].get("potion") or engine.cards_potion(n):
                continue
            if not t["terminal"]:
                continue
            if t["plus_cards"] >= 2 or t["draw_to_x"] or t["attack_kind"]:
                out.append(n)
    return out


def board_for(card):
    """A kingdom where `card` is the only Action worth buying."""
    filler = [f for f in FILLER if f != card][:9]
    return sorted([card] + filler)


def duel(card, pairs, seed0=9000):
    """`card` as the terminal vs no terminal at all. Returns (win_rate, n)."""
    won, n = 0.0, 0
    board = board_for(card)
    exps = sorted({CARDS[c]["expansion"] for c in board})
    for k in range(pairs):
        for swap in (False, True):
            forced = ["", card] if swap else [card, ""]
            g = engine.new_game(["p1", "p2"], exps, seed=seed0 + k,
                                kingdom=board)
            rngs = {p: random.Random((seed0 + k) * 977 + i)
                    for i, p in enumerate(g["players"])}
            by_seat = {p: forced[i] for i, p in enumerate(g["players"])}
            for _ in range(20000):
                if g["over"]:
                    break
                pid = g["pending_pid"] or g["turn"]
                bot.FORCE_TERMINAL = by_seat[pid]
                mv = bot.choose(g, pid, rngs[pid], bot.BM_PLUS)
                ok, err = engine.apply_move(g, pid, mv)
                if not ok:
                    raise AssertionError(f"{card}: {mv} -> {err}")
            bot.FORCE_TERMINAL = None
            if not g["over"]:
                raise AssertionError(f"{card}: game {seed0 + k} never ended")
            seat = g["players"][1] if swap else g["players"][0]
            win = set(engine.winners(g))
            won += (1.0 / len(win)) if seat in win and win else 0.0
            n += 1
    return won / n, n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-n", "--pairs", type=int, default=20)
    ap.add_argument("--all", action="store_true",
                    help="also re-measure the cards already ranked")
    ap.add_argument("cards", nargs="*", help="specific cards to measure")
    a = ap.parse_args(argv)
    names = a.cards or candidates(include_ranked=a.all)
    print(f"{len(names)} candidates, {a.pairs} CRN pairs each "
          f"({a.pairs * 2} games)\n")
    print(f"{'card':22s} {'$':>3} {'rank':>5}  {'vs no terminal':>14}   verdict")
    rows = []
    for name in names:
        try:
            wr, n = duel(name, a.pairs)
        except AssertionError as e:
            print(f"{name:22s} SKIPPED ({e})")
            continue
        se = (0.25 / n) ** 0.5
        sig = abs(wr - 0.5) > 1.96 * se
        verdict = ("KEEP/ADD" if wr > 0.5 and sig else
                   "DROP" if wr < 0.5 and sig else "wash")
        rank = BM_TERMINALS.get(name, 0)
        print(f"{name:22s} {CARDS[name]['cost']:>3} {rank:>5}  "
              f"{wr:>8.4f} +-{1.96 * se:.3f}   {verdict}", flush=True)
        rows.append((wr, name, rank, verdict))
    print("\nBy measured value (this is the ordering BM_TERMINALS should have):")
    for wr, name, rank, verdict in sorted(rows, reverse=True):
        print(f"  {wr:.4f}  {name:22s} (table rank {rank}, {verdict})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
