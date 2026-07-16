"""Generate differential-parity fixtures: games played by the PYTHON engine, recorded
move-by-move, for the Rust port to replay and match state-exactly.

THIS IS THE CONTRACT THAT MAKES THE PORT TRUSTWORTHY. The Rust engine is only allowed
to ship if it reproduces `games/spender_duel/engine.py` exactly, and "exactly" means:
starting from the same deal, applying the same moves, its state matches the projection
below after EVERY move — not just at the end, where two bugs could cancel.

RANDOMNESS IS SCRIPTED, NOT REPRODUCED. The engine's only rng is (1) the deck shuffles
in `new_game` and (2) the bag shuffle inside `_fill_board` (new_game's initial fill and
each `replenish`). So a fixture ships the exact post-deal state plus, per fill, the bag
order Python got after shuffling — and Rust consumes that script. This is the coc-core
`dice_script` trick, and it means we never have to reimplement Mersenne Twister in Rust
just to compare rules. (Deck pops and pyramid refills are already deterministic.)

The capture wraps the RNG rather than reimplementing `_fill_board`, so the fixture
generator cannot drift from the code it is recording.

    python duel-core/tools/gen_engine_fixtures.py --games 400 --out duel-core/fixtures
"""
import argparse
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)

from games.spender_duel import bot, cards as C, engine  # noqa: E402

IDS = C.deck_ids(1) + C.deck_ids(2) + C.deck_ids(3)
CARD_IX = {cid: i for i, cid in enumerate(IDS)}
TOK_IX = {t: i for i, t in enumerate(C.TOKENS)}          # ...pearl=5, gold=6
ROYAL_IX = {r: i for i, r in enumerate(sorted(C.ROYALS))}
COLOR_IX = {c: i for i, c in enumerate(C.COLORS)}
KIND_IX = {None: 0, "take_same": 1, "steal": 2, "choose_royal": 3, "discard": 4}
A, B = "p0", "p1"


class _SpyRng:
    """Delegates to the real rng but records what `shuffle` produced.

    Wrapping the rng (instead of reimplementing `_fill_board`) is deliberate: the
    recorder stays honest even if the fill logic changes.
    """

    def __init__(self, real, sink):
        self._real, self._sink = real, sink

    def shuffle(self, x):
        self._real.shuffle(x)
        self._sink.append([TOK_IX[t] for t in x])

    def __getattr__(self, name):
        return getattr(self._real, name)


def _tok(t):
    return -1 if t is None else TOK_IX[t]


def _card(cid):
    return -1 if cid is None else CARD_IX[cid]


def proj(g: dict) -> str:
    """Canonical, TOTAL projection of the game state.

    Everything the rules can touch goes in — including the hidden piles (bag/deck
    order) and the pending context, because a port that gets the visible board right
    while drifting on deck order is still wrong and will diverge later.
    """
    parts = [
        f"ph={0 if g['phase'] == 'playing' else 1}",
        f"wn={-1 if g['winner'] is None else g['order'].index(g['winner'])}",
        f"wc={g['win_condition'] or '-'}",
        f"wcol={COLOR_IX[g['win_color']] if g.get('win_color') else -1}",
        f"turn={g['order'].index(g['turn'])}",
        f"tn={g['turn_number']}",
        f"rep={int(g['turn_flags']['replenished'])}",
        f"agn={int(g['again'])}",
        f"pb={g['privileges_board']}",
        "board=" + ",".join(str(_tok(t)) for t in g["board"]),
        "bag=" + ",".join(str(TOK_IX[t]) for t in g["bag"]),
        "roy=" + ",".join(str(ROYAL_IX[r]) for r in g["royals_available"]),
    ]
    for lvl in ("1", "2", "3"):
        parts.append(f"d{lvl}=" + ",".join(str(CARD_IX[c]) for c in g["decks"][lvl]))
        parts.append(f"p{lvl}=" + ",".join(str(_card(c)) for c in g["pyramid"][lvl]))
    for seat, pid in enumerate(g["order"]):
        p = g["players"][pid]
        parts.append(f"t{seat}=" + ",".join(str(p["tokens"][t]) for t in C.TOKENS))
        parts.append(f"v{seat}={p['privileges']}")
        parts.append(f"r{seat}=" + ",".join(str(CARD_IX[c]) for c in p["reserved"]))
        parts.append(f"rd{seat}=" + ",".join(str(CARD_IX[c]) for c in p["reserved_from_deck"]))
        parts.append(f"b{seat}=" + ",".join(
            f"{CARD_IX[e['id']]}:{COLOR_IX[e['as_color']] if e.get('as_color') else -1}"
            for e in p["purchased"]))
        parts.append(f"y{seat}=" + ",".join(str(ROYAL_IX[r]) for r in p["royals"]))
        parts.append(f"yc{seat}={p['royals_claimed']}")
    parts.append(f"pp={-1 if g['pending_pid'] is None else g['order'].index(g['pending_pid'])}")
    parts.append(f"pk={KIND_IX[g['pending_kind']]}")
    ctx = (g.get("pending") or {}).get("ctx") or {}
    # TOKEN index, not colour: a `steal` may target a PEARL, not just a gem.
    parts.append("pcol=" + ",".join(str(TOK_IX[c]) for c in ctx.get("colors", [])))
    parts.append("proy=" + ",".join(str(ROYAL_IX[r]) for r in ctx.get("royals", [])))
    parts.append(f"pbon={TOK_IX[ctx['bonus']] if ctx.get('bonus') else -1}")
    parts.append(f"pvia={ctx.get('via') or '-'}")
    return "|".join(parts)


def enc_move(mv: dict) -> dict:
    """Python move dict -> index-encoded form the Rust side parses."""
    t = mv["type"]
    o = {"t": t}
    if t == "take":
        o["cells"] = list(mv["cells"])
    elif t == "use_privilege" or t == "take_same":
        o["cell"] = mv["cell"]
    elif t == "reserve":
        src = mv["source"]
        o["cell"] = mv["gold_cell"]
        o["kind"] = 0 if src["kind"] == "pyramid" else 1
        o["level"] = src["level"]
        o["slot"] = src.get("slot", -1)
    elif t == "buy":
        o["card"] = CARD_IX[mv["card_id"]]
        o["from"] = 0 if mv["from"] == "pyramid" else 1
        o["as_color"] = COLOR_IX[mv["as_color"]] if mv.get("as_color") else -1
    elif t in ("steal", "discard"):
        o["color"] = TOK_IX[mv["color"]]
    elif t == "choose_royal":
        o["royal"] = ROYAL_IX[mv["royal_id"]]
    return o


def setup_of(g: dict) -> dict:
    """The exact post-new_game state, fully explicit — Rust starts from this."""
    return {
        "board": [_tok(t) for t in g["board"]],
        "bag": [TOK_IX[t] for t in g["bag"]],
        "decks": {l: [CARD_IX[c] for c in g["decks"][l]] for l in ("1", "2", "3")},
        "pyramid": {l: [_card(c) for c in g["pyramid"][l]] for l in ("1", "2", "3")},
        "privileges_board": g["privileges_board"],
        "royals": [ROYAL_IX[r] for r in g["royals_available"]],
        "privs": [g["players"][p]["privileges"] for p in g["order"]],
    }


def _pick_loaded(g, actor, rng):
    """Uniform over ALL legal moves — deliberately BAD play, to reach rules the tiered
    bot never does.

    Needed because `bot.choose` ranks `use_privilege` last and never skips a pending, so
    a corpus made only of its games exercises NEITHER — and a parity suite that never
    runs a rule cannot validate it. These games backfill the rare paths (the coc-core
    "loaded scenario" trick).
    """
    moves = engine.legal_moves(g, actor)
    return rng.choice(moves) if moves else None


def play(seed: int, max_moves: int = 4000, loaded: bool = False) -> dict:
    fills: list = []
    orig_fill = engine._fill_board
    engine._fill_board = lambda game, rng: orig_fill(game, _SpyRng(rng, fills))
    try:
        g = engine.new_game([A, B], seed=seed)
        setup = setup_of(g)
        setup_fills = list(fills)          # the initial deal's fill
        proj0 = proj(g)                    # checks Rust's setup BEFORE any move runs
        fills.clear()
        rng = random.Random(seed + 7919)
        pick = _pick_loaded if loaded else bot.choose
        moves = []
        for _ in range(max_moves):
            if engine.is_over(g):
                break
            actor = g.get("pending_pid") or g["turn"]
            mv = pick(g, actor, rng)
            if mv is None:
                break
            fills.clear()
            ok, err = engine.apply_move(g, actor, mv)
            assert ok, (mv, err)
            moves.append({
                "actor": g["order"].index(actor),
                "mv": enc_move(mv),
                "fills": list(fills),      # bag order(s) post-shuffle, if this move filled
                "proj": proj(g),
            })
    finally:
        engine._fill_board = orig_fill
    return {"seed": seed, "setup": setup, "setup_fills": setup_fills,
            "proj0": proj0, "moves": moves, "over": engine.is_over(g)}


# Every move type the engine can be asked to apply. The corpus MUST contain all of
# them or the parity gate is silently blind to one — this is a hard failure, not a note.
REQUIRED = {"take", "reserve", "buy", "replenish", "use_privilege",
            "take_same", "steal", "choose_royal", "discard", "skip_pending"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=400, help="tiered-bot games (realistic play)")
    ap.add_argument("--loaded", type=int, default=120,
                    help="uniform-random games — backfill rules the tiered bot never plays")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "fixtures"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    dst = os.path.join(args.out, "engine_fixtures.jsonl")
    n_moves, kinds = 0, {}
    with open(dst, "w") as f:
        for seed in range(args.games):
            fx = play(seed)
            n_moves += len(fx["moves"])
            for m in fx["moves"]:
                kinds[m["mv"]["t"]] = kinds.get(m["mv"]["t"], 0) + 1
            f.write(json.dumps(fx) + "\n")
        for seed in range(args.loaded):
            fx = play(1_000_000 + seed, loaded=True)
            n_moves += len(fx["moves"])
            for m in fx["moves"]:
                kinds[m["mv"]["t"]] = kinds.get(m["mv"]["t"], 0) + 1
            f.write(json.dumps(fx) + "\n")
    print(f"wrote {os.path.normpath(dst)}: {args.games + args.loaded} games, {n_moves} moves")
    print("coverage: " + "  ".join(f"{k}={kinds.get(k, 0)}" for k in sorted(REQUIRED)))
    missing = sorted(REQUIRED - set(kinds))
    if missing:
        raise SystemExit(f"FATAL: no fixture exercises {missing} — the parity gate would "
                         f"be blind to it. Raise --loaded or add a scenario.")


if __name__ == "__main__":
    main()
