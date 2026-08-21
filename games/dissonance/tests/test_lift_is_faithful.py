"""THE LEVEL-ONLY ABSTRACTION EMBEDS EXACTLY IN THE WIDE ONE. Proved, not asserted.

`liftlab` prices what the level-only abstraction costs by relabelling its
policy into the packed action space and turning a best responder with the FULL
denomination set loose on it. That number is only about the ABSTRACTION if the
relabelling is faithful -- if the lift mangles anything, the same measurement
comes back as a large, confident, entirely manufactured cost. This package has
recorded that shape of error more than once.

THE IDENTITY THAT SETTLES IT. Take the wide game and restrict the responder to
exactly the lifted images of the level-only actions. It is then playing the
level-only game through a different labelling, so the exact best response must
come back at exactly the same value -- to floating point, not to a tolerance.
Any discrepancy is the lift, since `leaf` already prices a contract as
"rank = holds" on both sides and `best_response` reads no abstraction flag at
all.
"""
import random

import pytest

from games.dissonance.tools import cfrlab as C
from games.dissonance.tools import liftlab as L


MAXL = 3


@pytest.fixture
def solved(monkeypatch):
    """A real level-only solve over four hand-written deals, priced per suit.

    `pts`/`duck` are LISTS here, as the all-denomination cache builds them --
    with scalars every denomination pays identically and the whole comparison
    would read zero by construction, which is a test that cannot fail.
    """
    monkeypatch.setattr(C, "MAXL", MAXL)
    monkeypatch.setattr(C, "DENOMS", False)
    recs = [{"str": [s0, s1],
             "pts": [[p0, p0 - 1, p0 - 1, p0 - 2, p0 - 3],
                     [p1, p1 - 1, p1 - 2, p1 - 2, p1 - 3]],
             "duck": [[False] * 5, [False] * 5]}
            for s0, s1, p0, p1 in [(6.0, 13.0, 4, 7), (15.0, 6.0, 8, 3),
                                   (10.0, 11.0, 5, 5), (12.0, 8.0, 6, 4)]]
    C.bucketise(recs)
    eq, _ = L.solve(recs, 4000, seed=7)
    assert eq, "the solve reached no infoset at all"
    return recs, eq


@pytest.fixture
def restrict(monkeypatch):
    """Put `best_response` on the WIDE transitions but the LIFT's action set.

    `_step`, `act_level` and `act_rank` all read `DENOMS` live, so flipping the
    flag is enough to move `best_response` onto the packed transitions -- it
    reads no abstraction flag of its own. Restricting `actions` to the lift's
    image then makes the wide game a relabelling of the narrow one.
    """
    plain = C.actions

    def imaged(level, holds):
        monkeypatch.setattr(C, "DENOMS", False)
        try:
            acts = plain(level, holds)
        finally:
            monkeypatch.setattr(C, "DENOMS", True)
        return [a if a == -1
                else (level * C._APACK + holds + 1 if a == C.HOLD
                      else a * C._APACK)
                for a in acts]

    def go(on):
        monkeypatch.setattr(C, "DENOMS", True)
        monkeypatch.setattr(C, "actions", imaged if on else plain)
    return go


def _ex(recs, table):
    return [C.best_response(recs, C.Policy(table, backoff=False), s)
            for s in (0, 1)]


def test_the_lift_reproduces_the_level_only_best_response_exactly(solved,
                                                                  restrict):
    """The identity. Same game, different labels, same number."""
    recs, eq = solved
    narrow = _ex(recs, eq)
    restrict(True)
    assert _ex(recs, L.lift(eq)) == pytest.approx(narrow, abs=1e-9)


def test_the_restriction_is_what_makes_the_identity_hold(solved, restrict):
    """...and it is the RESTRICTION doing the work, not a coincidence.

    Hand the same responder the full denomination set and the number must move
    -- that is `liftlab`'s entire headline, asserted here in miniature. If it
    did not move, the identity above would be holding because the wide game
    offers nothing extra, and the cost `liftlab` reports would be noise.
    """
    recs, eq = solved
    narrow = _ex(recs, eq)
    restrict(False)
    wide = _ex(recs, L.lift(eq))
    assert wide != pytest.approx(narrow, abs=1e-6)
    # The wide responder is strictly stronger: it can play every lifted action
    # and more, so it can never do WORSE against the same policy.
    assert all(w >= n - 1e-9 for w, n in zip(wide, narrow)), \
        f"a strictly larger action set priced LOWER: {wide} vs {narrow}"


def test_a_broken_lift_is_caught(solved, restrict):
    """...and the identity is sharp enough to fail on one character.

    Send a HOLD to the bidder's best suit (rank 0) instead of the next rank up.
    That is the whole difference between "an overtake lands you in a
    progressively worse denomination" and "an overtake is free", which is the
    mechanism the wide abstraction exists to model -- so a check that could not
    see it would be measuring nothing.
    """
    recs, eq = solved
    narrow = _ex(recs, eq)
    assert max(abs(x) for x in narrow) > 0.5, \
        "the responder wins nothing, so the identity would hold trivially"
    bad = {}
    for (bucket, level, prev, holds), row in eq.items():
        moved = {}
        for a, p in row.items():
            b = -1 if a == -1 else (level * C._APACK if a == C.HOLD
                                    else a * C._APACK)
            moved[b] = moved.get(b, 0.0) + p
        bad[(bucket, level, prev, holds)] = moved
    restrict(True)
    assert _ex(recs, bad) != pytest.approx(narrow, abs=1e-9), \
        "a deliberately broken lift priced identically -- the check is blind"
