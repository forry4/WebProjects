"""Replay a BGA Tag Team log through our own engine (games/rag_tag).

TWO JOBS, and the first one is the point:
  1. ENGINE PARITY. Every log that replays to the recorded winner is a real game BGA and our
     engine agree about. Every divergence names a rule we have wrong, with a reproduction.
     This is a stronger check than the unit suite because it is adversarial in the right way:
     top humans reach positions nobody writes a test for.
  2. TRAINING ROWS. The same drive loop, with `on_move`, is the harvest hook.

THE HARD PART IS NOT THE MOVES, IT IS THE RANDOMNESS. rag_tag's engine shuffles in exactly
two places (engine.py: `r.shuffle(draft)` and `r.shuffle(build)`), and a replay cannot seed
its way to the same order. Both must be OVERRIDDEN from what the log reveals -- the same
trick cob_replay.py used for CoB's dice:

  * DRAFT HANDS  -- forced once, from whatever the log shows each player was offered.
  * BUILD DECK   -- forced LAZILY. We never learn the full shuffled order, only the three
    cards offered each BUILD step, so instead of reconstructing the deck we reorder it just
    before each draw so its top three ARE the observed offer. Cards not kept go to the
    BOTTOM (engine.py:1197), so the tail order matters and is preserved.

DECISIONS ARE FEW, which is what makes this tractable: the FIGHT step resolves automatically
(both players flip simultaneously), so the only player choices are draft / order / build /
character -- exactly engine.legal_moves' four kinds.

STATUS: the engine-driving half is written and correct against rag_tag's API. The BGA-parsing
half (`parse_actions`) is DELIBERATELY UNIMPLEMENTED -- run tt_inspect.py against real logs
first and fill it in from what is actually there. Guessing event names is how you get a
parser that silently matches nothing.

  python tt_replay.py <table_id> [-v]
"""
import json
import sys

sys.path.insert(0, "C:/Users/Forrest/forrestm_projects")
from games.rag_tag import engine                                    # noqa: E402

import scrape_target as tgt                                         # noqa: E402
import tt_inspect                                                   # noqa: E402

LOGS = tgt.CORP + "/logs"
SEATS = ["p0", "p1"]


# ── the BGA half — fill in from tt_inspect.py output ──────────────────────────────────
def parse_actions(events):
    """BGA events -> an ordered list of replay instructions.

    Return a list of dicts, each one of:
        {"op": "draft_hands", "hands": [[fid, ...], [fid, ...]]}
        {"op": "build_offer", "seat": int, "insts": [a, b, c]}
        {"op": "move", "seat": int, "move": {...}}    # an engine.legal_moves shape
    plus, at the end:
        {"op": "result", "winner_seat": int}

    NOT IMPLEMENTED — needs real logs. See the module docstring.
    """
    raise NotImplementedError(
        "parse_actions: run `python tt_inspect.py` on a downloaded log and write this "
        "against the event types it reports. Do not guess the names."
    )


# ── the engine half — correct today, no logs required ─────────────────────────────────
def force_draft_hands(game, hands):
    """Override the dealt draft (engine.py:182 shuffles it)."""
    game["draft_hands"] = [list(hands[0]), list(hands[1])]


def force_build_offer(game, seat, insts):
    """Reorder build_deck so the next draw yields exactly `insts`.

    engine._begin_build takes build_deck[seat][:BUILD_DRAW] off the top, so we lift the
    observed three to the front and keep everything else in its existing relative order --
    unkept cards are appended to the BOTTOM later, so that tail is not arbitrary.
    """
    deck = game["build_deck"][seat]
    missing = [i for i in insts if i not in deck]
    if missing:
        raise ValueError(f"seat {seat}: offered cards not in build deck: {missing}")
    rest = [i for i in deck if i not in insts]
    game["build_deck"][seat] = list(insts) + rest


def replay(path, verbose=False, on_move=None):
    """Drive our engine from a log. Returns a dict describing how far it got."""
    events, _raw = list(tt_inspect.events(path)), None
    plan = parse_actions(events)

    game = engine.new_game(SEATS, seed=0)
    applied = stopped = 0
    for step in plan:
        op = step["op"]
        try:
            if op == "draft_hands":
                force_draft_hands(game, step["hands"])
            elif op == "build_offer":
                force_build_offer(game, step["seat"], step["insts"])
            elif op == "move":
                seat, move = step["seat"], step["move"]
                legal = engine.legal_moves(game, seat)
                if move not in legal:
                    return _stop(game, applied, f"illegal {move!r}; legal={legal[:6]}")
                if on_move is not None:
                    on_move(game, SEATS[seat], move, seat)
                engine.apply_move(game, SEATS[seat], move)
                applied += 1
                if verbose:
                    print(f"  [{applied:>3}] seat {seat} {move}")
            elif op == "result":
                stopped = step["winner_seat"]
        except Exception as e:                       # noqa: BLE001 — report, don't crash the batch
            return _stop(game, applied, f"{type(e).__name__}: {e}")

    over = engine.is_over(game)
    summary = engine.result_summary(game) if over else {}
    return {"over": over, "applied": applied, "stopped": None,
            "winner": summary.get("winner"), "recorded_winner": stopped,
            "winner_match": over and summary.get("winner") == stopped,
            "summary": summary}


def _stop(game, applied, why):
    return {"over": False, "applied": applied, "stopped": why,
            "winner": None, "recorded_winner": None, "winner_match": False, "summary": {}}


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[-1])
        return 2
    r = replay(f"{LOGS}/{sys.argv[1]}.json", verbose="-v" in sys.argv)
    print(json.dumps({k: v for k, v in r.items() if k != "summary"}, indent=1, default=str))
    return 0 if r["winner_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
