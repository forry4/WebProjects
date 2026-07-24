"""Parity fixtures for the COMPACT PROJECTION — the state the browser's WASM bot is
handed instead of the real game dict.

WHAT THIS GATE HAS TO PROVE, and why it is not covered by the existing two. `parity`
proves the Rust engine reproduces the Python engine from the SAME state; `ai_parity`
proves the leaf and the move lists match on the SAME state. Both start from a state Rust
was handed in full. Serving does not: the server projects the game through
`compact.project`, deliberately DROPPING the deck order and the opponent's blind-reserve
identities, and the browser searches whatever comes out. So the open question is exactly:

    is the projection lossless for everything the search reads?

which this answers by projecting a real position, ingesting it in Rust, and requiring the
ingested state to give the IDENTICAL `legal_moves` (exact, order included — the rollout
samples that list by index) and the IDENTICAL `ai._value` (1e-12) for the projected seat.
Anything the projection lost that the search actually needs shows up here as a diverging
move list or a diverging leaf.

Both seats are projected at every position, not just the mover's: a projection is a
per-seat redaction, and a seat/perspective slip is a classic port bug that only shows
from the side you didn't check. (The non-mover's `legal_moves` is `[]` — which is itself
worth asserting, since it is what the turn/pending fields decide.)

The complementary half of the contract — that the projection carries no SECRET — cannot
be checked from here (Rust can only see what was shipped). It is gated on the Python side
by `games/spender_duel/tests/test_compact.py`, which requires the projection to be
invariant under any permutation of the hidden state.

    python duel-core/tools/gen_compact_fixtures.py --games 120
"""
import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)

import gen_engine_fixtures as G  # noqa: E402
from games.spender_duel import ai, bot, compact, engine  # noqa: E402

# compact.py is production code and owns its own copy of the wire encoding; the fixture
# tools own theirs. They describe the same format, so a drift between them would make
# this gate quietly compare the wrong things — fail loudly instead.
assert compact.CARD_IX == G.CARD_IX, "compact.py and gen_engine_fixtures disagree on card indices"
assert compact.TOK_IX == G.TOK_IX, "compact.py and gen_engine_fixtures disagree on token indices"
assert compact.COLOR_IX == G.COLOR_IX, "compact.py and gen_engine_fixtures disagree on color indices"
assert compact.ROYAL_IX == G.ROYAL_IX, "compact.py and gen_engine_fixtures disagree on royal indices"
assert compact.KIND_IX == G.KIND_IX, "compact.py and gen_engine_fixtures disagree on pending kinds"


def _rec(g: dict) -> list:
    out = []
    for seat, pid in enumerate(g["order"]):
        proj = compact.project(g, pid)
        assert proj["seat"] == seat
        # The order within a level's unseen pool is the secret; it must never ship.
        for pool in proj["unseen"]:
            assert pool == sorted(pool), "unseen pool shipped unsorted — leaks the deck order"
        out.append({
            "proj": proj,
            "seat": seat,
            "legal": [G.enc_move(m) for m in engine.legal_moves(g, pid)],
            "val": repr(ai._value(g, pid)),
        })
    return out


def play(seed: int, loaded: bool = False, max_moves: int = 4000) -> list:
    fills: list = []
    orig_fill = engine._fill_board
    engine._fill_board = lambda game, rng: orig_fill(game, G._SpyRng(rng, fills))
    try:
        g = engine.new_game([G.A, G.B], seed=seed)
        rng = random.Random(seed + 1301)
        pick = G._pick_loaded if loaded else bot.choose
        recs = list(_rec(g))
        for _ in range(max_moves):
            if engine.is_over(g):
                break
            actor = g.get("pending_pid") or g["turn"]
            mv = pick(g, actor, rng)
            if mv is None:
                break
            ok, err = engine.apply_move(g, actor, mv)
            assert ok, (mv, err)
            recs.extend(_rec(g))
    finally:
        engine._fill_board = orig_fill
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=120, help="tiered-bot games (realistic play)")
    ap.add_argument("--loaded", type=int, default=40,
                    help="uniform-random games — reach the states the tiered bot never does "
                         "(it never blind-reserves off a deck, which is the whole redaction)")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "fixtures"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    dst = os.path.join(args.out, "compact_fixtures.jsonl")
    n = legal_n = 0
    blind = pend = 0
    with open(dst, "w", encoding="utf-8") as f:
        for seed in range(args.games + args.loaded):
            for r in play(seed if seed < args.games else 3_000_000 + seed,
                          loaded=seed >= args.games):
                n += 1
                legal_n += len(r["legal"])
                # The redaction only bites when the OPPONENT holds a blind reserve; a
                # corpus without those would pass while proving nothing about it.
                if any(sum(p["reserved_blind"]) for p in r["proj"]["players"]):
                    blind += 1
                if r["proj"]["pending_kind"]:
                    pend += 1
                f.write(json.dumps(r) + "\n")
    print(f"wrote {os.path.normpath(dst)}: {n} projections, {legal_n} legal moves")
    print(f"  with an opponent blind reserve : {blind}")
    print(f"  with a pending sub-decision    : {pend}")
    if not blind:
        raise SystemExit("FATAL: no fixture has an opponent blind reserve — the gate would be "
                         "blind to the redaction it exists to check. Raise --loaded.")
    if not pend:
        raise SystemExit("FATAL: no fixture has a pending sub-decision. Raise --loaded.")


if __name__ == "__main__":
    main()
