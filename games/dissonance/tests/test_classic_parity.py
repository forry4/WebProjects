"""The offline referee's corpus reaches the states worth porting wrong.

`rust-cores/dissonance-core/tests/classic.rs` replays `fixtures/classic.jsonl`
and demands the same per-seat view after every move. That gate is only as good
as the corpus it replays, and a corpus is exactly the kind of thing that
quietly stops covering something — the `range(13)` lesson: a roster nobody
checks only guards the tree SHRINKING.

So this file asks the fixture what it contains, and every count below is a
state where the two implementations could plausibly disagree:

* a SAME-LEVEL overtake (the one rung a client rebuilding the bid set from two
  axes gets wrong),
* a seat with no legal bid left at all (the denomination forever-ban biting),
* a DECLINED swap and a taken one (`shown` follows `out`, and the redaction of
  which cards moved),
* the Double taken AND let stand (both branches reach `_start_play`),
* a round that reaches the thirteenth trick.

It also pins the shape of what is recorded, since the Rust side reads it
positionally and a generator change that dropped the full-view control would
otherwise leave the digest comparison with nothing checking its canonicalisation.
"""
import json
import pathlib

import pytest

from games.dissonance import engine as E

FIX = pathlib.Path(__file__).parent / "fixtures" / "classic.jsonl"


@pytest.fixture(scope="module")
def rounds():
    if not FIX.exists():
        pytest.fail(
            f"{FIX} is missing. Regenerate:\n"
            "  PYTHONPATH=. python -m games.dissonance.tools.gen_classic_fixtures 120"
            f" > {FIX}"
        )
    return [json.loads(l) for l in FIX.read_text().splitlines() if l.strip()]


def _moves(rounds, kind):
    return [s["move"] for r in rounds for s in r["steps"] if s["move"]["kind"] == kind]


def test_the_corpus_is_not_thin(rounds):
    assert len(rounds) >= 20
    steps = sum(len(r["steps"]) for r in rounds)
    # 26 plays plus an auction and two prompts; anything near this says every
    # round really ran to the end.
    assert steps > 30 * len(rounds) * 0.8, steps


def test_every_round_is_classic_and_finishes(rounds):
    for r in rounds:
        assert r["g"]["mode"] == "classic"
        assert r["steps"][-1]["move"]["kind"] == "play"
        # 13 tricks of two cards, however the auction went.
        plays = [s for s in r["steps"] if s["move"]["kind"] == "play"]
        assert len(plays) == 26, len(plays)


def test_the_auction_reaches_its_awkward_rungs(rounds):
    same_level, jumps = 0, 0
    for r in rounds:
        level = 0
        for s in r["steps"]:
            if s["move"]["kind"] != "bid":
                continue
            if s["move"]["level"] == level and level > 0:
                same_level += 1
            elif s["move"]["level"] > level:
                jumps += 1
            level = s["move"]["level"]
    assert same_level > 0, "no same-level overtake in the whole corpus"
    assert jumps > 0


def test_a_seat_runs_out_of_denominations(rounds):
    """The forever-ban biting is what makes `may_pass` the only option, and it
    is the state a bid-set port is most likely to get wrong."""
    found = False
    for r in rounds:
        g = json.loads(json.dumps(r["g"]))   # a fresh copy per round
        for s in r["steps"]:
            if g["phase"] == "auction" and not E.auction_options(g)["bids"]:
                found = True
            E.apply_move(g, s["pid"], s["move"])
    assert found, "no auction ever exhausted a seat's denominations"


def test_both_halves_of_the_swap_and_the_Double_are_covered(rounds):
    swaps = _moves(rounds, "swap")
    assert any(m["take"] is None for m in swaps), "no declined swap"
    assert any(m["take"] is not None for m in swaps), "no taken swap"
    doubles = _moves(rounds, "double")
    assert any(m["on"] for m in doubles), "the Double is never taken"
    assert any(not m["on"] for m in doubles), "the Double is never let stand"


def test_the_full_view_control_is_present_on_both_ends(rounds):
    """The Rust replay compares full views only where they were recorded, and
    they are what would catch a canonicalisation difference between the two
    languages — a digest-only corpus would hide one as 30 identical misses."""
    for r in rounds:
        assert "views" in r["steps"][0], "no full view on the first step"
        assert "views" in r["steps"][-1], "no full view on the last step"
        for s in r["steps"]:
            assert len(s["h"]) == 2, "a step is missing a seat's digest"
        # ...and the recorded view is the REDACTED one: the seat's own hand and
        # never the opponent's, which is what the board renders from.
        v0 = r["steps"][0]["views"][0]
        assert v0["you"] == 0 and "hand" in v0
        assert v0["opp_hand"] is None


def test_the_recorded_views_are_the_engines_own(rounds):
    """Replay one round in Python and demand the fixture's digests match what
    this engine produces TODAY. Without it the corpus could drift away from the
    engine and the Rust would be held to a rule set nobody ships any more."""
    from games.dissonance.tools.gen_classic_fixtures import canon, fnv1a, SKIP

    r = rounds[0]
    g = json.loads(json.dumps(r["g"]))
    for i, s in enumerate(r["steps"]):
        E.apply_move(g, s["pid"], s["move"])
        for seat in (0, 1):
            v = E.view_for(g, seat)
            for k in SKIP:
                v.pop(k, None)
            assert fnv1a(canon(v)) == s["h"][seat], (
                f"step {i} seat {seat}: the fixture no longer matches this engine "
                "-- regenerate games/dissonance/tests/fixtures/classic.jsonl"
            )
