"""Replay real BGA Zenith games through Orbit's engine.

`AGENTS.md`: "BGA replays are the parity oracle." This is the harness that makes that
true. It is deliberately built in the order the Rag Tag harness was, because that order
is what got that game from 13/30 to full 40/40 parity:

  1. the ENGINE-DRIVING half first, proven against games the engine itself produced;
  2. the BGA-PARSING half second, written against real logs and never guessed.

STATUS
------
Half 1 is written and PROVEN: `selftest()` plays random games, records the intents, and
replays them through the same `drive()` a BGA log will use, asserting the replay lands on
an identical final state. So when a real log fails, the failure is in the parse or in the
rules -- not in the driver.

Half 2 (`parse_actions`) is DELIBERATELY UNIMPLEMENTED. There are no Zenith logs on disk
yet; the `cob-mining` cron fills `C:/Users/Forrest/Zenith_corpus/logs`. Guessing BGA's
event names is how you get a parser that silently matches nothing -- the replay stalls and
it presents as a rules bug. Dump what is actually there first:

    python log_inspect.py                      # in the cob-mining worktree
    python log_inspect.py <table_id>

THE HARD PART, WHEN YOU GET THERE
---------------------------------
Not the moves -- the SETUP. `new_game` shuffles the card deck, the bonus pool, the agent
deck, the seating order and (on "random") the board sides. A real table had a specific
one of each, so a replay must FORCE the setup to the log's rather than seed its way there.
On Rag Tag this was most of the harness bugs, and every one of them looked like an engine
bug: reversed insert positions, a de-dup key that needed two fields, forced choices BGA
never logged. Expect the same here and suspect the harness first.

Usage::

    python -m games.orbit.tools.bga_replay --selftest [--games 50]
    python -m games.orbit.tools.bga_replay <table_id>        # once half 2 exists
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys

from games.orbit import engine

#: Where the cob-mining cron drops Zenith logs. Same env-var-with-a-default shape the Rag
#: Tag tools use, so the corpus can move without editing code.
CORP = os.environ.get("ZENITH_CORPUS", "C:/Users/Forrest/Zenith_corpus")
LOGS = CORP + "/logs"

#: The five actions the engine accepts. `choose` is POLYMORPHIC and that is the single
#: most useful thing to know before writing the parser: it answers whatever sub-decision
#: is pending, and its payload is one of at least nine shapes -- `card_id`, `planet`,
#: `planets` (a pair), `faction`, `tier`, `branch`, `accept`, `cost`+`amount`, or
#: `bonus_area`+`slot`. A first cut of this file keyed `choose` on `planet` alone and the
#: selftest caught it inside one game: two pending choices both matched `planet: null`.
#: So a move's identity is the WHOLE dict, not a chosen subset of it.
ACTIONS = ("mulligan", "leader", "recruit", "technology", "choose")


def whose_move(game: dict) -> str:
    """Who the engine is waiting on. Mirrors tools/soak.py, which is the proven driver."""
    if game["phase"] == "mulligan":
        return next(pid for pid in game["players"] if pid not in game["mulligan_done"])
    return game["pending_pid"] if game.get("pending") else game["turn_pid"]


def as_intent(move: dict) -> dict:
    """The identity of a move: all of it.

    Subsetting the fields is what a log-shaped intent WANTS to be, and it is wrong here --
    see ACTIONS. The parser's job is therefore to reconstruct a full move from a log
    event; `match` then holds that reconstruction to what the engine actually offers,
    which is the check that makes a wrong reconstruction loud instead of silent.
    """
    action = move.get("action")
    if action not in ACTIONS:
        raise KeyError(f"unknown move action {action!r} -- ACTIONS is out of date")
    return dict(move)


def match(moves: list[dict], intent: dict) -> dict:
    """The legal move this intent names.

    SELECTED from `legal_moves`, never constructed. A hand-built move that the engine
    happens to accept proves nothing about whether it was the move the human made, and a
    hand-built move the engine rejects looks like a rules bug.
    """
    hits = [m for m in moves if as_intent(m) == intent]
    if hits:
        # MEASURED: across 10,985 decision points in 60 random games, `legal_moves` never
        # offered two byte-identical entries, so this never has to choose. If one ever
        # appears the entries are equal, and applying either is the same move.
        return hits[0]
    raise LookupError(
        f"no legal move matches {json.dumps(intent, sort_keys=True)}; "
        f"legal now: {json.dumps([as_intent(m) for m in moves], sort_keys=True)[:400]}")


def drive(game: dict, intents: list[dict], *, validate: bool = True) -> int:
    """Apply intents in order. Returns how many were consumed.

    Stops early and cleanly when the game ends, because a real log can carry trailing
    packets after the win: that is normal, not a mismatch.
    """
    used = 0
    for intent in intents:
        if engine.is_over(game):
            break
        pid = whose_move(game)
        moves = engine.legal_moves(game, pid)
        if not moves:
            raise AssertionError(f"engine stalled with {len(intents) - used} intents left")
        ok, error = engine.apply_move(game, pid, match(moves, intent))
        if not ok:
            raise AssertionError(f"engine rejected a move it had just offered: {error}")
        if validate:
            engine.validate_state(game)
        used += 1
    return used


def record(seed: int, configuration: str = "sun", move_cap: int = 1500) -> tuple[dict, list[dict]]:
    """Play a reproducible random game and keep the intents it produced.

    This is the STAND-IN for a BGA log until real ones land: same driver, same matcher,
    same comparison -- only the source of the intents differs.
    """
    chooser = random.Random(seed * 104_729 + 17)
    game = engine.new_game(["A", "B"], seed=seed, configuration=configuration)
    intents: list[dict] = []
    for _ in range(move_cap):
        if engine.is_over(game):
            return game, intents
        pid = whose_move(game)
        moves = engine.legal_moves(game, pid)
        if not moves:
            raise AssertionError(f"seed {seed} stalled")
        move = chooser.choice(moves)
        intents.append(as_intent(move))
        ok, error = engine.apply_move(game, pid, move)
        if not ok:
            raise AssertionError(f"seed {seed} rejected a legal move: {error}")
    raise AssertionError(f"seed {seed} exceeded {move_cap} moves")


def fingerprint(game: dict) -> str:
    """What two runs of the same game must agree on, to the byte.

    The move LOG is excluded on purpose: it carries prose, and comparing prose turns a
    wording change into a parity failure. Everything mechanical is in.
    """
    return json.dumps({k: v for k, v in sorted(game.items()) if k != "log"},
                      sort_keys=True, default=str)


def selftest(games: int, configuration: str = "sun") -> int:
    """Prove the DRIVER before trusting it to judge the engine.

    An instrument that has not been calibrated on cases known to pass will blame the
    thing it is measuring. This is that calibration: the intents are known-good by
    construction, so any failure here is the harness.
    """
    for seed in range(games):
        played, intents = record(seed, configuration)
        fresh = engine.new_game(["A", "B"], seed=seed, configuration=configuration)
        used = drive(fresh, intents)
        if used != len(intents):
            raise AssertionError(f"seed {seed}: consumed {used} of {len(intents)} intents")
        if engine.winner(fresh) != engine.winner(played):
            raise AssertionError(
                f"seed {seed}: replay won by {engine.winner(fresh)}, "
                f"original by {engine.winner(played)}")
        if fingerprint(fresh) != fingerprint(played):
            raise AssertionError(f"seed {seed}: replay diverged from the original game")
    print(f"driver OK: {games} games recorded and replayed to an identical final state "
          f"(configuration={configuration})")
    return 0


def parse_actions(log: list) -> list[dict]:
    """BGA log -> intents. NOT YET WRITTEN, and not to be guessed.

    See the module docstring: dump the real event stream with `log_inspect.py` and write
    this against what is actually in it. Every field it needs -- card ids, planet names --
    has a public mechanical name in `data/bga_reference.json`, which is the mapping table
    to translate through, not to reinvent.
    """
    raise NotImplementedError(
        "no Zenith logs have been parsed yet. Run `python log_inspect.py` in the "
        "cob-mining worktree against " + LOGS + " and write this against the real "
        "event names -- guessing them yields a parser that silently matches nothing.")


def replay_table(table_id: str) -> int:
    path = f"{LOGS}/{table_id}.json"
    if not os.path.isfile(path):
        print(f"no log for table {table_id} at {path}")
        return 1
    with open(path, encoding="utf-8") as fh:
        log = json.load(fh)
    parse_actions(log)          # raises until half 2 exists
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("table_id", nargs="?", help="a downloaded BGA table id")
    parser.add_argument("--selftest", action="store_true",
                        help="prove the driver against engine-generated games")
    parser.add_argument("--games", type=int, default=25)
    parser.add_argument("--configuration", default="sun", choices=("sun", "random"))
    args = parser.parse_args(argv)

    if args.selftest or not args.table_id:
        if not args.table_id:
            have = len(os.listdir(LOGS)) if os.path.isdir(LOGS) else 0
            print(f"{have} Zenith logs in {LOGS}; running the driver selftest.")
        return selftest(args.games, args.configuration)
    return replay_table(args.table_id)


if __name__ == "__main__":
    sys.exit(main())
