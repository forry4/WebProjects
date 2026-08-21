"""What the talon tools agree on: how a round is driven, and how it is scored.

TWO TOOLS HAVE TO MEAN THE SAME THING BY "play" AND BY "dd". `swaplab` labels
candidate exchanges, `skat_swapfit` fits a policy to those labels, and
`swaparena` gates the fitted policy. If their resolutions drift, the policy is
trained against one number and gated on another and the gate's verdict is about
the drift rather than about the policy -- which is not a hypothetical: the whole
reason skat's fit failed its gate is that `dd` and `play` disagree by ~3 points
a round on the same exchanges, so a half-point of accidental difference between
two copies of "play" would have been invisible inside that.

    dd    the settled contract scored by an EXACT double-dummy solve of the real
          deal (`bidserve`'s `resolve`). No card-play noise and no card-play
          bias -- and no card play anybody actually gets, which is the point of
          having the other one.
    play  the round PLAYED OUT by the shipped bot, declaration and Kontra and
          all. The real information set, and free: no solver, ~600 rounds a
          second, so a 30000-deal arena costs under a minute.

Neither is the right answer on its own. The swap's value depends on who plays
the cards afterwards, and this game serves at least two card players -- the
server bot on the lower tiers and the browser's PIMC search on Hard.
"""
import json
import random
import subprocess

from games.dissonance import engine as E, bot as B

#: THE DEAL SEEDS. One constant, so a decision the arena disagrees with can be
#: looked up in the oracle corpus by its deal index instead of being re-solved.
DEAL_SEED = 600_000
#: A SEPARATE STREAM FOR THE PLAYOUT, and the same one for every arm. Sharing
#: the auction's `rng` would work too, but only by accident: the auction has
#: already drawn from it a deal-dependent number of times, so the playout would
#: start at a different offset per deal for no reason anyone could reconstruct.
PLAY_SEED = 1_000_000
BIN = "rust-cores/dissonance-core/target/release/bidserve"


def mv(kind, p):
    """`bot.act`'s return, as a move dict."""
    if kind == "play":
        # The one branch that hands back a bare card id rather than a dict.
        return {"kind": "play", "card": p}
    if kind == "bid":
        return ({"kind": "pass"} if p.get("pass")
                else {"kind": "bid", **{a: b for a, b in p.items() if a != "pass"}})
    if kind == "swap":
        return {"kind": "swap", **p}
    return p


def step(g, rng):
    seat = E.turn_seat(g)
    kind, p = B.act(g, seat, rng)
    E.apply_move(g, g["seats"][seat], mv(kind, p), rng)


def swap_phase(mode):
    """Classic's swap is its own phase; skat's lives inside `talon`."""
    return "talon" if mode == "skat" else "swap"


def drive_to_talon(m, mode):
    """Deal `m`, bid it out, and stop at the swap. `(game, declarer)` or None.

    A skat declarer is LOOKED first: `talon` is one phase covering look / hand /
    swap, so a round that has not looked is not yet at the decision -- and
    declining to look IS the Hand announcement, a different round entirely.
    """
    g = E.new_game(["a", "b"], random.Random(DEAL_SEED + m), opener=m % 2, mode=mode)
    rng = random.Random(m)
    guard = 0
    want = swap_phase(mode)
    while g["phase"] not in (want, "play", "over") and guard < 40:
        guard += 1
        step(g, rng)
    if g["phase"] != want:
        return None
    decl = g["auction"]["declarer"]
    if mode == "skat" and not g.get("looked"):
        E.apply_move(g, g["seats"][decl], {"kind": "look"})
    return g, decl


def settle(g, decl):
    """Drive an exchanged game to trick 1, for `dd`. True if it got there.

    SKAT'S TALON RESOLVES BEFORE THE GAME IS NAMED, so a candidate exchange has
    no contract to be priced against until the declaration is made -- and it is
    made FROM THE POST-SWAP HAND by the shipped `choose_declare`, which is how
    it happens at the table. Letting it respond is not a contaminant: naming a
    better game IS part of what a good swap buys, and holding the declaration
    fixed would price a decision nobody makes.

    Kontra/Re (and classic's Double) are forced OFF, because under `dd` the
    comparison has to be between SWAPS and not between a tier's answers to the
    contracts they lead to. Under `play` they are left live -- there the round
    is the thing being measured, and the defender is answering the contract this
    exchange actually arrived at.
    """
    guard = 0
    while g["phase"] in ("declare", "kontra", "re", "double") and guard < 6:
        guard += 1
        if g["phase"] == "declare":
            E.apply_move(g, g["seats"][decl],
                         {"kind": "declare", **B.choose_declare(g, decl)})
        else:
            E.apply_move(g, g["seats"][1 - decl], {"kind": g["phase"], "on": False})
    return g["phase"] == "play"


def playout(g, m):
    """Play the round out with the shipped bot. Declarer net, or None."""
    rng = random.Random(PLAY_SEED + m)
    guard = 0
    while g["phase"] != "over" and guard < 200:
        guard += 1
        step(g, rng)
    if g["phase"] != "over":
        return None
    s = g["result"]["scores"]
    return float(s[decl_of(g)] - s[1 - decl_of(g)])


def decl_of(g):
    return g["auction"]["declarer"]


#: WHAT THE HARD TIER IS ASKED TO SPEND on one card decision. `main.py`'s
#: `CLIENT_AI_MAX_WORLDS`, and it has to be that number: the browser splits the
#: cap across its worker pool and SUMS, which computes exactly the single k=8
#: answer, so a harness at any other k is measuring a tier nobody plays.
HARD_K = 8


class Solver:
    """One `bidserve`, for `dd` and `hard`. Spawned only when one is asked for,
    so the `play` resolution needs no Rust build at all."""

    def __init__(self, depth="3"):
        self.proc = subprocess.Popen([BIN, depth], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True)

    def ask(self, req):
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def resolve(self, g):
        """Exact declarer payoff of `g`'s settled contract on the real deal."""
        terms = E.payoff_terms(g)
        req = {"resolve": {"hands": [list(h) for h in g["hands"]],
                           "piles": [[list(x) for x in row] for row in g["piles"]],
                           "trump": g["auction"]["denom"],
                           "leader": terms["declarer"], "terms": terms}}
        r = self.ask(req)
        if "payoff" not in r:
            raise SystemExit(f"unresolvable: {r}")
        return r["payoff"]


def hard_playout(g, m, solver):
    """Play the round out with the HARD TIER'S OWN CARD SEARCH, both seats.

    `bidserve`'s `pick` calls `wire::answer_card` -- the same body the browser
    worker runs -- fed the seat's OWN redacted `view_for`, so what plays here is
    what the tier plays. The pick is the client's argmax over the summed
    per-option values, ties to the first index, exactly as `Dissonance.jsx` does.

    THE DECLARATION AND KONTRA STAY ON THE SERVER BOT, as they do under `dd` and
    `play`. In the room they would be client-served too, but they are auction
    decisions (a solve in every denomination, ~6x the cost of a card one) and
    both arms get the identical treatment, so what is left in the difference is
    still the swap. Say it out loud rather than let it be inferred: this
    resolution reproduces the tier's CARD PLAY, not the whole tier.
    """
    rng = random.Random(PLAY_SEED + m)
    guard = 0
    while g["phase"] != "over" and guard < 200:
        guard += 1
        if g["phase"] != "play":
            step(g, rng)
            continue
        seat = E.turn_seat(g)
        legal = E.legal_moves(g, seat)
        if len(legal) < 2:
            E.apply_move(g, g["seats"][seat], {"kind": "play", "card": legal[0]})
            continue
        r = solver.ask({"pick": {"view": E.view_for(g, seat),
                                 "payoff": E.payoff_terms(g), "k": HARD_K}})
        if "moves" in r and r["moves"]:
            sums = r["sum"]
            best = max(range(len(sums)), key=lambda i: (sums[i], -i))
            card = r["moves"][best]
        else:
            # THE SERVER BOT FINISHES THE DECISION, which is not a harness
            # shortcut -- it is what the room does when the browser cannot
            # answer. An unsearchable view degrades per DECISION here too.
            card = B.choose_card(g, seat)
        E.apply_move(g, g["seats"][seat], {"kind": "play", "card": card})
    if g["phase"] != "over":
        return None
    s = g["result"]["scores"]
    return float(s[decl_of(g)] - s[1 - decl_of(g)])


def value(snap, decl, take, give, m, res, solver=None):
    """Apply one exchange to a talon snapshot and score the round.

    `snap` is a `json.dumps` of the game at the talon -- a STRING, deliberately.
    Every candidate has to start from a byte-identical position, and a dict
    handed round and deep-copied by hand is how one arm ends up seeing what the
    previous arm did to a nested list.
    """
    g = json.loads(snap)
    E.apply_swap(g, decl, take, give)
    if res == "dd":
        return solver.resolve(g) if settle(g, decl) else None
    if res == "hard":
        return hard_playout(g, m, solver)
    return playout(g, m)
