"""Record whole CLASSIC rounds so `classic.rs` can be held to this engine.

`rust-cores/dissonance-core/src/classic.rs` is a second implementation of the
shipped phase machine — the one a browser referees an offline game with — and
two implementations of the same rules drift silently. `test_rust_parity.py`
already holds the CARD PLAY to the Rust reference this way; this is the same
method one phase earlier, over the auction, the talon swap, the Double and the
per-seat redaction, which had no Rust side at all until the offline build.

Each line is one round:

    {"g": <the dealt game dict>,
     "steps": [{"pid", "move", "h": [fnv0, fnv1], "views": [v0, v1] | absent}]}

**The per-step check is a DIGEST, and the full views ride only on the first and
last steps.** Recording both seats' whole view after all ~30 moves came to
72KB a round — 8.6MB for 120 rounds, twenty-odd times the largest fixture this
repo commits. The digest is FNV-1a over the view's canonical JSON (sorted
keys, no spaces), which both languages produce identically; the two full views
are what makes a failure diagnosable, and they are also the CONTROL — a
canonicalisation difference between Python and Rust would break every digest
at once, so it is caught by the same run rather than hidden by it.

The dealt dict is PYTHON's, deliberately: what has to agree is the RULES, never
the shuffle, so the Rust side is handed this deal rather than asked to
reproduce it. Every move is a real `engine.apply_move` payload, so the fixture
also pins the move SHAPES the offline driver has to send.

WHAT THE VIEWS OMIT, and why each is not a hole:

* **`result`** — `classic.rs` deliberately does not score (see its module
  note); the offline driver prices the round with `pricing.js`, which
  `tests/test_bid_worth.py` already gates against `engine.payoff`. Comparing it
  here would demand a price list the Rust does not have.
* **`match`** — banked by the driver for the same reason. It is carried through
  the Rust untouched, and the round in a fixture never advances one.

Everything else is compared byte for byte, both seats, after every single move.

Run: PYTHONPATH=. python -m games.dissonance.tools.gen_classic_fixtures 120 \
       > games/dissonance/tests/fixtures/classic.jsonl
"""
import copy
import json
import random
import sys

from games.dissonance import engine as E

# The keys the Rust does not produce -- see the module docstring.
SKIP = ("result", "match")


def canon(v):
    """The view as one canonical string — sorted keys, no spaces.

    `serde_json`'s `Value` is a BTreeMap, so Rust emits its keys sorted and
    separator-free too; that is what makes the digest comparable at all, and
    the full-view rows are what prove it.
    """
    return json.dumps(v, sort_keys=True, separators=(",", ":"))


def fnv1a(s: str) -> int:
    """FNV-1a/64 over the canonical JSON. Not a security hash and does not need
    to be — it is comparing two implementations of one rule set, so any stable
    function both languages can write in five lines will do, and this one needs
    no dependency in a crate that deliberately has none."""
    h = 0xCBF29CE484222325
    for b in s.encode():
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def _views(g):
    out = []
    for seat in (0, 1):
        v = E.view_for(g, seat)
        for k in SKIP:
            v.pop(k, None)
        out.append(v)
    return out


def _a_move(g, rng):
    """One legal move for whoever is to act, chosen at random.

    Random rather than bot-driven ON PURPOSE: a policy visits the lines it
    likes, and the states most likely to be ported wrong are the ones nobody
    plays -- a same-level overtake, a declined swap, a Double on a floor
    contract. `test_classic_parity.py` asserts the corpus really reaches them.
    """
    ph = g["phase"]
    if ph == "auction":
        opts = E.auction_options(g)
        seat = g["auction"]["to_act"]
        # NO LEGAL BID IS A REAL STATE, not a broken generator: denominations
        # are a per-player forever-ban, so a seat that has named all five can
        # only pass. Random play finds it, which is exactly the kind of corner
        # the corpus is for.
        if not opts["bids"] or (opts["may_pass"] and rng.random() < 0.35):
            return seat, {"kind": "pass"}
        lvl, den = rng.choice(opts["bids"])
        return seat, {"kind": "bid", "level": lvl, "denom": den}
    if ph == "swap":
        decl = g["auction"]["declarer"]
        if rng.random() < 0.25:
            return decl, {"kind": "swap", "take": None, "give": None}
        take = rng.choice(g["shown"])
        give = rng.choice(g["hands"][decl])
        return decl, {"kind": "swap", "take": take, "give": give}
    if ph == "double":
        seat = 1 - g["auction"]["declarer"]
        return seat, {"kind": "double", "on": rng.random() < 0.4}
    if ph == "play":
        seat = E.playing_seat(g)
        return seat, {"kind": "play", "card": rng.choice(E.legal_moves(g, seat))}
    raise AssertionError(f"nothing to do in phase {ph}")


def one_round(seed):
    rng = random.Random(seed)
    g = E.new_game(["p0", "p1"], rng, opener=seed % 2, mode="classic")
    line = {"g": copy.deepcopy(g), "steps": []}
    while g["phase"] != "over":
        seat, move = _a_move(g, rng)
        pid = line["g"]["seats"][seat]
        E.apply_move(g, pid, move)
        vs = _views(g)
        line["steps"].append({
            "pid": pid,
            "move": move,
            "h": [fnv1a(canon(v)) for v in vs],
        })
    # The first and last steps carry their views in full: the first because a
    # canonicalisation mismatch has to fail LOUDLY rather than as 30 identical
    # digest misses, the last because the terminal state is the richest one and
    # the hardest to reconstruct by hand when something diverges.
    for i in (0, len(line["steps"]) - 1):
        line["steps"][i]["views"] = _views_at(line, i)
    return line


def _views_at(line, i):
    """Replay the round to step `i` and take the views there.

    Replaying rather than stashing every view as we go is the whole point of
    the digest: holding 30 of them per round is what made the file 8.6MB.
    """
    g = copy.deepcopy(line["g"])
    for step in line["steps"][: i + 1]:
        E.apply_move(g, step["pid"], step["move"])
    return _views(g)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    for i in range(n):
        print(json.dumps(one_round(i), separators=(",", ":")))


if __name__ == "__main__":
    main()
