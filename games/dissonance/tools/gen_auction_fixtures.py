"""The auction's LEGALITY, as a table, for the Expert tier's tree to be held to.

The Expert tier minimaxes the auction (`rust-cores/dissonance-core/src/
auc_search.rs`), and a tree has to know which edges exist. Everything else it
needs is shipped as data -- the leaf prices come from `_terms_for` rows on the
wire, exactly as `payoff_terms` ships the card search's scoring -- but legality
cannot be, because it is a function of the node the search is standing on rather
than of the node the server is. So `legal_bids` MIRRORS `auction_options`, and
this is the gate that stops the two drifting.

It is the quietest kind of drift there is. A tree that thinks one extra bid is
legal simply prefers a line the room would refuse, gets its move rejected by
`_validated_bot_move`, and hands the decision to the server bot -- which is the
exact silent-degradation shape this game has already shipped twice.

    PYTHONPATH=<repo root> python -m games.dissonance.tools.gen_auction_fixtures \\
        > games/dissonance/tests/fixtures/auction.jsonl

Committed, like the other fixtures -- CI runs cargo with no Python available.
"""

from __future__ import annotations

import json
import random
import sys

from games.dissonance import engine as E


def _edges(g: dict) -> list[dict]:
    """`auction_options` as the tree's own edge vocabulary."""
    opt = E.auction_options(g)
    out: list[dict] = []
    if E.mode_of(g) == "skat":
        out.extend({"value": v} for v in opt["values"])
    else:
        out.extend({"level": lvl, "denom": d} for lvl, d in opt["bids"])
    if opt["may_pass"]:
        out.append({"pass": True})
    return out


def _row(g: dict) -> dict:
    payload = E.auction_search_payload(g)
    return {"mode": E.mode_of(g), "state": payload["state"], "rules": payload["rules"],
            "legal": _edges(g)}


def _walk(g: dict, rng: random.Random, out: list[dict]) -> None:
    """Record every auction node on one random line of bidding."""
    guard = 0
    while g["phase"] == "auction" and guard < 24:
        guard += 1
        out.append(_row(g))
        seat = g["auction"]["to_act"]
        edges = _edges(g)
        # Weighted towards BIDDING, or almost every walk stops at the first
        # pass and the deep nodes -- the exhausted-denomination and capped-raise
        # states this exists for -- never get recorded.
        bids = [e for e in edges if "pass" not in e]
        e = rng.choice(bids) if bids and rng.random() < 0.8 else rng.choice(edges)
        if e.get("pass"):
            E.apply_pass(g, seat)
        elif "value" in e:
            E.apply_skat_bid(g, seat, e["value"])
        else:
            E.apply_bid(g, seat, e["level"], e["denom"])


def _forced_classic_lines(out: list[dict]) -> None:
    """The states a random walk reaches rarely and the tree gets wrong loudly.

    Both of these are cases where the legal set SHRINKS for a reason the search
    has to know about: the raise cap running into the ceiling, and a seat that
    has spent every denomination it is allowed to name.
    """
    # A seat with every denomination used, at the top of the ladder.
    g = E.new_game(["a", "b"], random.Random(7), opener=0)
    for lvl, (d0, d1) in zip((1, 2, 3, 4, 5), ((0, 1), (2, 3), (4, 0), (1, 2), (3, 4))):
        if g["phase"] != "auction":
            break
        E.apply_bid(g, g["auction"]["to_act"], lvl, d0)
        out.append(_row(g))
        E.apply_bid(g, g["auction"]["to_act"], lvl + 1, d1)
        out.append(_row(g))
    # The raise cap at the ceiling: MAX_LEVEL - 1 leaves exactly one rung.
    g = E.new_game(["a", "b"], random.Random(9), opener=0)
    E.apply_bid(g, 0, E.MAX_LEVEL - 1, 0)
    out.append(_row(g))
    g = E.new_game(["a", "b"], random.Random(11), opener=0)
    E.apply_bid(g, 0, E.MAX_LEVEL, E.NOTRUMP)
    out.append(_row(g))


def _forced_minor_lines(out: list[dict]) -> None:
    """Minor is the classic SHAPE with `max_level` 6, and the cap is the whole
    of what its legality adds -- so the forced lines are the ceiling states: an
    opener seeing exactly 1..6, and the raise cap running into a ceiling half
    of classic's. A tree that hardcoded 12 anywhere prefers an overtake the
    room refuses, which is the silent degradation this file exists to stop."""
    g = E.new_game(["a", "b"], random.Random(19), opener=0, mode="minor")
    out.append(_row(g))                          # the opener's 1..6
    E.apply_bid(g, 0, E.MINOR_MAX_LEVEL - 1, 0)
    out.append(_row(g))                          # one rung left under the cap
    g = E.new_game(["a", "b"], random.Random(23), opener=0, mode="minor")
    E.apply_bid(g, 0, E.MINOR_MAX_LEVEL, E.NOTRUMP)
    out.append(_row(g))                          # nothing outranks it


def _forced_skat_lines(out: list[dict]) -> None:
    """A skat pass-out is a NODE, not a leaf -- the first open pass hands the
    deal over and the auction goes on, and only the second throws it in. A
    random walk hits that state about as often as it hits any other, but it is
    the one shape classic has no analogue for."""
    g = E.new_game(["a", "b"], random.Random(13), opener=0, mode="skat")
    out.append(_row(g))
    E.apply_pass(g, 0)
    out.append(_row(g))          # one pass in, nothing standing
    # ...and the top of the ladder, where nothing outbids.
    g = E.new_game(["a", "b"], random.Random(17), opener=0, mode="skat")
    E.apply_skat_bid(g, 0, max(E.SKAT_VALUES))
    out.append(_row(g))


def main() -> None:
    out: list[dict] = []
    rng = random.Random(4242)
    for i in range(24):
        for mode in ("classic", "skat", "minor"):
            g = E.new_game(["a", "b"], random.Random(90000 + i), opener=i % 2, mode=mode)
            _walk(g, rng, out)
    _forced_classic_lines(out)
    _forced_minor_lines(out)
    _forced_skat_lines(out)
    sys.stdout.write("\n".join(json.dumps(r, separators=(",", ":")) for r in out) + "\n")


if __name__ == "__main__":
    main()
