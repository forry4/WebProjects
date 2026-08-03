"""Generate game-dict serializer parity fixtures for the Rust port.

Plays random legal games through the PYTHON engine and, at sampled positions, dumps the
compact State alongside the reference render dict two ways:
  - `full`: `serving.engine.to_game_dict(s)` — the unredacted view (Rust viewer=-1), and
  - `red0`: that dict passed through the REAL server redaction
    (`main._redact_blind_reserves(game, "p0")`) — seat 0's view, seat 1's blind reserves
    hidden (Rust viewer=0).
The Rust test (`tests/gamedict_parity.rs`) re-renders each sampled State and must match both
as JSON values (key order canonicalized by value comparison).

Positions are SAMPLED (every kth ply + every DISCARD/NOBLE-phase ply + the final position):
a full game dict repeats all 90 card dicts, so recording every ply would balloon the fixture
file for no extra coverage. The sub-decision plies are always kept because pending_* keys are
exactly where a serializer drifts.

Run:  python spender-core/tools/gen_gamedict_fixtures.py [n_games]
Writes: spender-core/tests/gamedict_fixtures.json
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# tools/ → spender-core/ → rust-cores/ → repo root (where the `games` package lives).
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, REPO)
os.environ.setdefault("SPENDER_AZ_MODEL", "none")

from games.spender.ai.serving import engine as E  # noqa: E402
from games.spender.main import _redact_blind_reserves  # noqa: E402  (the real server redaction)

N = int(sys.argv[1]) if len(sys.argv) > 1 else 30


def dump(s):
    return {
        "bank": list(s.bank),
        "tokens": [list(s.tokens[0]), list(s.tokens[1])],
        "bonuses": [list(s.bonuses[0]), list(s.bonuses[1])],
        "points": list(s.points),
        "purchased_n": list(s.purchased_n),
        "purchased": [list(s.purchased[0]), list(s.purchased[1])],
        "reserved": [list(s.reserved[0]), list(s.reserved[1])],
        "reserved_blind": [[bool(x) for x in s.reserved_blind[0]],
                           [bool(x) for x in s.reserved_blind[1]]],
        "nobles_won": [list(s.nobles_won[0]), list(s.nobles_won[1])],
        "board": list(s.board),
        "decks": [list(s.decks[0]), list(s.decks[1]), list(s.decks[2])],
        "nobles": list(s.nobles),
        "turn": s.turn,
        "phase": s.phase,
        "pending_nobles": list(s.pending_nobles),
        "final_trigger": s.final_trigger,
        "winner": s.winner,
        "ply": s.ply,
        "win_points": s.win_points,
    }


def record(s):
    full = E.to_game_dict(s)
    red0 = _redact_blind_reserves(json.loads(json.dumps(full)), "p0")
    return {"dump": dump(s), "full": full, "red0": red0}


positions = []
n_pending = 0
for g in range(N):
    wp = 21 if g % 4 == 0 else 15
    s = E.new_game(random.Random(g), win_points=wp)
    mv = random.Random(2_000_000 + g)
    positions.append(record(s))
    for step in range(400):
        if s.phase == E.OVER:
            break
        a = mv.choice(sorted(E.legal_actions(s)))
        E.apply(s, a)
        pending = s.phase in (E.DISCARD, E.NOBLE)
        if pending:
            n_pending += 1
        if pending or step % 7 == 0 or s.phase == E.OVER:
            positions.append(record(s))

# The whole point of sampling sub-decision plies is exercising pending_*; random play makes
# them plentiful, so an empty count means the sampler broke — fail, don't ship a hollow fixture.
assert n_pending > 0, "no DISCARD/NOBLE-phase positions sampled — fixture would prove nothing"

dst = os.path.abspath(os.path.join(HERE, "..", "tests", "gamedict_fixtures.json"))
with open(dst, "w", encoding="utf-8") as f:
    json.dump(positions, f)
print(f"wrote {dst}: {len(positions)} positions ({n_pending} in a pending sub-decision phase)")
