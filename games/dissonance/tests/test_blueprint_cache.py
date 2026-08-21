"""A CACHED BLUEPRINT MUST BE THE BLUEPRINT IT WAS CACHED FROM.

`load_blueprint` writes its solved average strategy to disk when
`CFR_BP_CACHE` names a file, because the arena shards by PROCESS and every
shard would otherwise re-solve the same equilibrium -- under `CFR_DENOMS` that
is over an hour each, so a 4-shard run would spend more time re-deriving one
policy than measuring it.

That makes the cache load-bearing for every number an arena reports, and a
cache is exactly the kind of component that fails SILENTLY: a wrong one still
produces a policy, still bids, and still yields a plausible arena result. So
two things are asserted here, and the second matters more than the first.
"""
import json
import os
import random

import pytest

from games.dissonance import engine as E
from games.dissonance.tools import cfrlab as C


@pytest.fixture
def solved(tmp_path, monkeypatch):
    """A tiny real cache and a short real solve -- not a stubbed policy.

    500 iterations is far from converged and deliberately so: what is under
    test is the CACHE, and a converged solve would only make the suite slower
    (this file was 38s at 2000 against a package that runs in ~26s). The
    non-vacuity assert at the foot of the second test is what keeps the short
    solve honest -- if 500 iterations ever stopped separating the two
    abstractions, it fails rather than passing quietly.
    """
    recs = [{"str": [s0, s1],
             "pts": [[p0, p0 - 1, p0 - 2, p0 - 2, p0 - 3],
                     [p1, p1 - 1, p1 - 1, p1 - 2, p1 - 3]],
             "duck": [[False] * 5, [False] * 5]}
            for s0, s1, p0, p1 in [(6.0, 13.0, 4, 7), (15.0, 6.0, 8, 3),
                                   (10.0, 11.0, 5, 5), (12.0, 8.0, 6, 4)]]
    ckpt = tmp_path / "deals.jsonl"
    ckpt.write_text("".join(json.dumps(r) + "\n" for r in recs))
    monkeypatch.setattr(C, "CKPT", str(ckpt))
    # A SHORT LADDER, because `DENOMS` costs the BRANCHING FACTOR at our own
    # nodes: at the shipped MAXL=8 an opening offers 40 actions and 500
    # iterations is 18 seconds, against a package that runs in ~26. MAXL=4 is
    # 20 and the two abstractions still separate, which the non-vacuity assert
    # below is what actually checks.
    monkeypatch.setattr(C, "MAXL", 4)
    monkeypatch.setenv("CFR_BP_ITERS", "500")
    monkeypatch.setenv("CFR_BP_CACHE", str(tmp_path / "bp.json"))
    return tmp_path


def _bids():
    """Replay a few real auctions through the blueprint. Its actual behaviour,
    rather than a table comparison -- a cache that round-trips the numbers but
    is read back under a different abstraction would pass a table check."""
    C._BP["cfr"] = None
    C.load_blueprint()
    out = []
    for s in range(8):
        g = E.new_game(["a", "b"], random.Random(500_000 + s), opener=0,
                       mode="classic")
        for _ in range(40):
            if g["phase"] != "auction":
                break
            seat = g["auction"]["to_act"]
            mv = C.blueprint_bid(g, seat)
            if mv is None:
                mv = max(E.auction_payoff_options(g),
                         key=lambda o: o.get("value", 0))["move"]
            out.append((seat, mv.get("level"), mv.get("denom"), mv["kind"]))
            if mv["kind"] == "bid":
                E.apply_bid(g, seat, mv["level"], mv["denom"])
            else:
                E.apply_pass(g, seat)
    return out


def test_a_cached_blueprint_plays_the_same_auctions(solved):
    """The round trip. Solve, cache, reload, and play the identical bids."""
    fresh = _bids()
    assert os.path.exists(os.environ["CFR_BP_CACHE"]), "no cache was written"
    assert fresh, "the blueprint made no bids at all"
    assert _bids() == fresh


def test_a_cache_from_a_DIFFERENT_ABSTRACTION_IS_REFUSED(solved, monkeypatch,
                                                         capsys):
    """...and the failure this really guards against.

    The two abstractions pack actions differently -- level-only stores a bare
    level, `DENOMS` stores `level * 8 + rank`. Reading one back as the other
    would not crash: every key parses, every action is an int, and the
    blueprint would bid confidently off a table that means something else. That
    is the shape of bug this package has paid for repeatedly, so the key
    carries the action space and a mismatch RE-SOLVES rather than loading.
    """
    monkeypatch.setattr(C, "DENOMS", False)
    level_only = _bids()
    blob = json.load(open(os.environ["CFR_BP_CACHE"]))
    assert blob["key"].endswith("|0|1"), f"key does not record DENOMS: {blob['key']}"

    monkeypatch.setattr(C, "DENOMS", True)
    wide = _bids()
    capsys.readouterr()
    assert json.load(open(os.environ["CFR_BP_CACHE"]))["key"].endswith("|1|1"), \
        "the wide solve did not overwrite the stale level-only cache"
    assert wide != level_only, \
        "the two abstractions played identically -- the check cannot see a mix-up"
