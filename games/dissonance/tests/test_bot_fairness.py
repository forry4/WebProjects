"""The bots must not see what their seat may not see.

Every bot here is handed the WHOLE game dict — `bot.act(g, seat)` and
`_ask_the_client` both take `g`, because the server owns the state and there is
nowhere else for it to come from. So nothing structural stops a bot reading the
opponent's hand; only the code does, and only a test can say whether it still
holds.

These are INVARIANCE tests rather than greps. Rewrite the cards the seat cannot
see, ask the bot the same question, and demand the same answer: a bot that
peeked at any of them would have to change its mind about at least one of the
rewrites. That catches a peek through any number of helper layers, which is
what a grep for `hands[1 - seat]` does not.

What each bot is entitled to:
  * its own hand;
  * every pile TOP, both seats';
  * the MIDDLE pile's bottom, both seats' — dealt face up;
  * `shown`, the talon cards it was actually shown (classic: after winning the
    auction; skat: only if it chose to look, which is what Hand costs);
  * the whole public record — the auction log, the played cards, the score.

Everything else is hidden: the opponent's hand, BOTH seats' outer pile bottoms
(hidden from their owner too), and the out-of-play cards it was not shown.
"""

import random

import pytest

from games.dissonance import bot
from games.dissonance import engine as E


# --- helpers ---------------------------------------------------------------


def _hidden_from(g: dict, seat: int) -> list[int]:
    """Every card `seat` may not place, as a flat list.

    The opponent's hand, both seats' covered OUTER pile bottoms, and the
    out-of-play cards this seat was not shown.
    """
    opp = 1 - seat
    out = list(g["hands"][opp])
    for owner in (0, 1):
        for i, p in enumerate(g["piles"][owner]):
            if len(p) == 2 and i != 1:
                out.append(p[0])
    sees_shown = seat == g["auction"]["declarer"] and (
        bool(g.get("looked")) if E.mode_of(g) == "skat"
        else g["phase"] in ("swap", "play"))
    shown = set(g["shown"]) if sees_shown else set()
    out.extend(c for c in g["out"] if c not in shown)
    return out


def _reshuffle_hidden(g: dict, seat: int, rng: random.Random) -> None:
    """Deal the cards `seat` cannot see back into the same SLOTS, in a new order.

    The position stays legal and identical from that seat's point of view: the
    same number of cards sit in the same places, and every card it may actually
    see is untouched.
    """
    opp = 1 - seat
    pool = _hidden_from(g, seat)
    rng.shuffle(pool)
    it = iter(pool)
    g["hands"][opp] = sorted(next(it) for _ in range(len(g["hands"][opp])))
    for owner in (0, 1):
        for i, p in enumerate(g["piles"][owner]):
            if len(p) == 2 and i != 1:
                p[0] = next(it)
    sees_shown = seat == g["auction"]["declarer"] and (
        bool(g.get("looked")) if E.mode_of(g) == "skat"
        else g["phase"] in ("swap", "play"))
    shown = set(g["shown"]) if sees_shown else set()
    g["out"] = [c if c in shown else next(it) for c in g["out"]]
    if not sees_shown:
        # `shown` is a subset of `out` and must keep pointing at real cards.
        g["shown"] = g["out"][:E.N_SHOWN]


def _ask(g: dict, seat: int):
    """The bot's answer, as something comparable."""
    kind, payload = bot.act(g, seat, random.Random(0))
    return (kind, repr(payload))


def _positions(mode: str, seeds=range(6)):
    """Bot-to-act positions across every phase the bot handles."""
    for seed in seeds:
        g = E.new_game(["a", "b"], random.Random(700 + seed), opener=0, mode=mode)
        rng = random.Random(seed)
        guard = 0
        while not E.round_over(g):
            guard += 1
            assert guard < 300, f"stuck in {g['phase']}"
            seat = E.turn_seat(g)
            yield g, seat
            kind, payload = bot.act(g, seat, rng)
            if kind == "move":
                E.apply_move(g, g["seats"][seat], payload)
            elif kind == "bid":
                E.apply_move(g, g["seats"][seat],
                             {"kind": "pass"} if payload.get("pass") else
                             {"kind": "bid", "level": payload["level"],
                              "denom": payload["denom"]})
            elif kind == "swap":
                E.apply_move(g, g["seats"][seat],
                             {"kind": "swap", "take": payload["take"],
                              "give": payload["give"]})
            elif kind == "play":
                E.apply_move(g, g["seats"][seat], {"kind": "play", "card": payload})
            else:
                raise AssertionError(f"the bot went idle in {g['phase']}")


# --- the server bot (Easy / Normal), both modes -----------------------------


@pytest.mark.parametrize("mode", ["classic", "skat"])
def test_the_server_bot_plays_the_same_whatever_it_cannot_see(mode):
    """THE MAIN CLAIM. Re-deal every hidden card and the answer must not move.

    Driven over whole games in both modes, so it covers the auction, the talon,
    the declaration, Kontra and all thirteen tricks -- every phase `bot.act`
    answers, rather than a hand-picked position that might be the one place it
    happens to behave.
    """
    checked = 0
    for g, seat in _positions(mode):
        before = _ask(g, seat)
        snapshot = {"hands": [list(h) for h in g["hands"]],
                    "piles": [[list(p) for p in row] for row in g["piles"]],
                    "out": list(g["out"]), "shown": list(g["shown"])}
        for trial in range(4):
            _reshuffle_hidden(g, seat, random.Random(9000 + trial))
            assert _ask(g, seat) == before, (
                f"{mode}: the bot changed its mind in phase {g['phase']} when only "
                f"cards it cannot see moved -- it is reading hidden state")
            checked += 1
        # Put the real deal back so the game continues down one line.
        g["hands"] = [list(h) for h in snapshot["hands"]]
        g["piles"] = [[list(p) for p in row] for row in snapshot["piles"]]
        g["out"] = list(snapshot["out"])
        g["shown"] = list(snapshot["shown"])
    assert checked > 200, f"only {checked} positions exercised"


@pytest.mark.parametrize("mode", ["classic", "skat"])
def test_the_reshuffle_would_actually_catch_a_peeking_bot(mode):
    """The invariance test above is worthless if the rewrite never bites.

    A bot that DOES read the opponent's hand must fail it -- so plant one and
    watch it fail. Without this, a `_reshuffle_hidden` that quietly did nothing
    (or a phase where every answer is forced) would report a clean bill of
    health for a bot that cheats outright.
    """
    caught = False
    for g, seat in _positions(mode, seeds=range(2)):
        def peek(gg, s=seat):
            # The crudest possible cheat: rank the opponent's actual holding.
            return sum(E.rank(c) for c in gg["hands"][1 - s])
        before = peek(g)
        for trial in range(6):
            _reshuffle_hidden(g, seat, random.Random(4000 + trial))
            if peek(g) != before:
                caught = True
                break
        if caught:
            break
    assert caught, "the reshuffle never changed the opponent's hand -- it is a no-op"


def test_the_bot_never_reads_a_card_its_seat_cannot_place():
    """The same claim from the other side: what it is ALLOWED to see.

    Stated as a list rather than left implicit, because the redaction rules are
    the kind of thing that gets extended (the talon, the swap) without every
    reader being revisited.
    """
    g = E.new_game(["a", "b"], random.Random(77), opener=0)
    hidden = _hidden_from(g, 0)
    # 7 cards in the opponent's HAND (their other six are pile cards, whose tops
    # are public), + 2 of its own covered outer bottoms + 2 of the opponent's
    # + the 6 out of play. No card is in two places at once.
    assert len(hidden) == len(set(hidden))
    assert len(hidden) == 7 + 2 + 2 + E.N_OUT
    own_blind = [p[0] for i, p in enumerate(g["piles"][0]) if i != 1 and len(p) == 2]
    assert all(c in hidden for c in own_blind), \
        "a seat's own OUTER pile bottoms are hidden from it too, and must count as hidden"
    assert g["piles"][0][1][0] not in hidden, "the middle pile's bottom is face up"


# --- the client-served Hard tier -------------------------------------------


@pytest.mark.parametrize("mode", ["classic", "skat"])
def test_the_hard_tier_is_only_ever_handed_its_own_seats_view(mode):
    """The Hard tier searches in the BROWSER, so the only thing it could cheat
    with is what crosses the wire — and that is `view_for(g, seat)`, the same
    redaction a human seat gets.

    Asserted by the same invariance: re-deal every hidden card and the armed
    request must come out BYTE-IDENTICAL. Enumerating fields instead would miss
    exactly the failure that has bitten this repo before — something that nests
    a whole-game snapshot defeats per-field redaction while every field-by-field
    check still passes — and scanning the payload for card numbers cannot work
    at all, because a card id and a trick count are both small integers.
    """
    import json

    from games.dissonance import main as m

    assert m.CLIENT_AI_TIERS == ("hard",), \
        "only the Hard tier is client-served; the others never see a wire payload"

    for seed in range(4):
        g = E.new_game(["a", "b"], random.Random(780 + seed), opener=0, mode=mode)
        rng = random.Random(seed)
        # Walk the whole round, arming a request at every seat and phase — the
        # talon and the declaration hold the secrets this mode adds.
        guard = 0
        while not E.round_over(g):
            guard += 1
            assert guard < 300, f"stuck in {g['phase']}"
            seat = E.turn_seat(g)
            for who in (0, 1):
                armed = json.dumps({"view": E.view_for(g, who),
                                    "payoff": E.payoff_terms(g)}, sort_keys=True)
                snapshot = {"hands": [list(h) for h in g["hands"]],
                            "piles": [[list(p) for p in row] for row in g["piles"]],
                            "out": list(g["out"]), "shown": list(g["shown"])}
                for trial in range(3):
                    _reshuffle_hidden(g, who, random.Random(5000 + trial))
                    after = json.dumps({"view": E.view_for(g, who),
                                        "payoff": E.payoff_terms(g)}, sort_keys=True)
                    assert after == armed, (
                        f"{mode}: the request armed for seat {who} in phase "
                        f"{g['phase']} moved when only cards it cannot see moved")
                g["hands"] = [list(h) for h in snapshot["hands"]]
                g["piles"] = [[list(p) for p in row] for row in snapshot["piles"]]
                g["out"] = list(snapshot["out"])
                g["shown"] = list(snapshot["shown"])
            kind, payload = bot.act(g, seat, rng)
            if kind == "bid":
                payload = ({"kind": "pass"} if payload.get("pass")
                           else {"kind": "bid", "level": payload["level"],
                                 "denom": payload["denom"]})
            elif kind == "swap":
                payload = {"kind": "swap", "take": payload["take"],
                           "give": payload["give"]}
            elif kind == "play":
                payload = {"kind": "play", "card": payload}
            E.apply_move(g, g["seats"][seat], payload)


def test_the_view_reshuffle_would_catch_a_leak_in_the_armed_request():
    """...and the same guard on the guard: a view that DID ship a hidden card
    must fail the check above, or a `view_for` that redacted everything by
    accident would look perfect."""
    g = E.new_game(["a", "b"], random.Random(79), opener=0)
    leaky = lambda gg, s: dict(E.view_for(gg, s), opp_hand=sorted(gg["hands"][1 - s]))
    before = leaky(g, 0)
    moved = False
    for trial in range(6):
        _reshuffle_hidden(g, 0, random.Random(6000 + trial))
        if leaky(g, 0) != before:
            moved = True
            break
    assert moved, "a view leaking the opponent's hand went undetected"
