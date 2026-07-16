"""Strong opponent for Spender Duel: determinized MCTS over the pure engine.

Pure Python, no new prod deps; reuses the engine's legal_moves/apply_move
contract (the same one the trivial ``bot`` and the tests use).

Design (mirrors games/castles_of_crimson/ai.py, which mirrors Spender's search):
  * **Determinized UCT.** The ONLY hidden information is the bag's contents, each
    deck's order, and the OPPONENT's blind (deck-drawn) reserved cards. Per
    simulation, ``_determinize`` CANONICALIZES those pools (sorts them) and then
    reshuffles + re-deals from a fresh rng, so the search provably cannot depend
    on the true hidden order — even though it runs server-side holding the real
    game dict. Everything else (board, pyramid, privileges, tokens, purchased,
    face-up reserves) is public and left TRUE.
  * Bounded in-tree horizon -> truncated rollout -> heuristic leaf ``_value``.
    ``_value`` scores BOTH seats with the same function and subtracts, so denial
    falls out of the search for free (no contested-card knob).
  * **Tiles/cards are never mutated** — the engine stores card IDS and reads the
    frozen ``cards.CARDS`` catalog — which is what makes ``_clone_game``'s shallow
    sharing safe. Don't break that invariant.
"""
from __future__ import annotations

import math
import random
import time

from . import cards as C
from . import engine

# ── Heuristic leaf weights ───────────────────────────────────────────────────
# Tuned by ai_selfplay.arena (hard-vs-normal / hard-vs-random). The three win
# conditions make "progress toward the NEAREST win" the dominant term; it is
# convex so that closing out a win outweighs broad, unfocused accumulation.
WEIGHTS = {
    "progress": 26.0,      # max(pts/20, crowns/10, best_color/10), convex
    "progress_exp": 2.0,
    "points": 1.00,        # realized prestige (also the 20-pt condition's currency)
    "crowns": 1.35,        # crowns are scarce (28 in the whole deck) and gate royals
    "color": 0.55,         # points concentrated in one color (the 10-in-a-color win)
    "bonus": 0.85,         # permanent discounts — the engine
    "bonus_spread": 0.20,  # having SOME of many colors (keeps future cards reachable)
    "token": 0.16,         # raw tokens in hand
    "gold": 0.30,          # gold is wild — worth more than a plain gem
    # A privilege converts 1:1 into a gem/pearl of your choice, so it is worth ABOUT a
    # token — and must be worth slightly LESS, or hoarding always out-scores using and
    # the bot never spends one (measured: at 0.55 vs token 0.16 it sat on two all game).
    # Just under `token` makes cashing in mildly positive and lets the SEARCH judge the
    # timing, rather than baking a preference either way.
    "privilege": 0.13,
    "reserved": 0.25,      # optionality (+ denial of a card the opponent wanted)
    "scale": 9.0,          # tanh squash of the standing DIFFERENCE
}

# Search budgets. "hard" = big budget, greedy. "normal" = small budget + visit-count
# TEMPERATURE sampling, so it makes human-scale blunders.
#
# `turn_budget` caps the WHOLE turn, `time_limit` any ONE decision. Both matter: a
# turn can be several decisions (optional privilege -> mandatory -> ability pendings),
# so a per-decision cap alone would let one turn think 3x its budget while the human
# stares at a frozen board.
#
# Budgets are sized for PRODUCTION, not this box. Render's free tier is ~10x slower
# (documented: Spender measures ~85 sims/s there vs ~950 local), and branching here is
# ~76, so a 0.35s decision would buy ~0.8 sims per root move in prod — indistinguishable
# from random, and pointless next to the trivial "easy" tier. Sims, not seconds, are the
# strength currency; keep an eye on that ratio if these are ever re-tuned.
# `temperature` is a softmax over mean Q (see choose_move) — NOT the usual sample-by-
# visits, which measures nothing here. Q spreads are ~0.1-0.3, so T=0.08 keeps a clear
# preference for good moves while erring often enough to be beatable.
DIFFICULTY = {
    "normal": {"turn_budget": 1.6, "time_limit": 0.8, "max_iters": 1200,
               "temperature": 0.08, "rollout_steps": 12},
    "hard": {"turn_budget": 5.0, "time_limit": 2.5, "max_iters": 5000,
             "temperature": 0.0, "rollout_steps": 12},
}
DEFAULT_DIFFICULTY = "hard"

C_PUCT = 1.5
_MAX_TREE_DEPTH = 14      # in-tree plies before truncating to a rollout
_ROLLOUT_STEPS = 12       # engine moves played out before the heuristic leaf

# Set per-decision by choose_move (never poke it directly — see that docstring).
_TAKE_DOMINANCE = True


# ── Fast cloning ─────────────────────────────────────────────────────────────
def _clone_game(g: dict) -> dict:
    """Explicit shallow clone (~100x faster than deepcopy on this state).

    Safe because every value we SHARE is treated as immutable by the engine:
    card ids are strings, `purchased` entries are new dicts appended on buy and
    never mutated in place, and `rng_state`/`pending` are replaced wholesale.
    The move log is dropped — the search never reads it.
    """
    players = {}
    for pid, p in g["players"].items():
        players[pid] = {
            "name": p["name"],
            "tokens": dict(p["tokens"]),
            "privileges": p["privileges"],
            "reserved": list(p["reserved"]),
            "reserved_from_deck": list(p.get("reserved_from_deck", ())),
            "purchased": list(p["purchased"]),      # entries are never mutated
            "royals": list(p["royals"]),
            "royals_claimed": p["royals_claimed"],
        }
    pend = g.get("pending")
    return {
        # Search clones never undo, so switch the per-turn snapshot OFF: it is a full
        # deepcopy of the game on EVERY turn and would dominate simulation cost (the
        # documented CoC lesson). Note this also means a clone carries no `turn_undo`.
        "_skip_undo": True,
        "game": g["game"],
        "phase": g["phase"],
        "winner": g["winner"],
        "win_condition": g.get("win_condition"),
        "win_color": g.get("win_color"),
        "order": g["order"],                        # never mutated
        "turn": g["turn"],
        "turn_number": g["turn_number"],
        "turn_flags": dict(g["turn_flags"]),
        "again": g["again"],
        "board": list(g["board"]),
        "bag": list(g["bag"]),
        "privileges_board": g["privileges_board"],
        "decks": {k: list(v) for k, v in g["decks"].items()},
        "pyramid": {k: list(v) for k, v in g["pyramid"].items()},
        "royals_available": list(g["royals_available"]),
        "players": players,
        "pending_pid": g["pending_pid"],
        "pending_kind": g["pending_kind"],
        "pending": {"ctx": dict(pend["ctx"])} if pend else None,
        "log": [],                                  # search never reads the log
        "rng_state": g.get("rng_state"),            # replaced wholesale by _save_rng
        "seed": None,
    }


# ── Determinization (the hidden-info boundary for the search) ────────────────
def _determinize(game: dict, pid: str, rng: random.Random) -> dict:
    """Resample everything `pid` cannot legitimately see.

    Hidden: the bag's CONTENTS (its count is public), each deck's ORDER, and the
    opponent's BLIND reserved cards. We pool the decks with the opponent's blind
    reserves, canonicalize (sort) the pool, shuffle it, then re-deal — so two
    positions differing only in hidden order give the SAME search distribution.
    Public and therefore untouched: the board, pyramid, privileges, tokens,
    purchased cards, royals, and face-up (pyramid-sourced) reserves.
    """
    g = _clone_game(game)
    opp = engine._opponent(g, pid)
    op = g["players"][opp]
    blind = list(op.get("reserved_from_deck", ()))
    blind_set = set(blind)

    # Resample PER LEVEL: a blind reserve's level is PUBLIC (the opponent saw which
    # deck it came off), so only its identity within that level is unknown. Pool each
    # level's unseen cards = that deck + the opponent's blind reserves of that level.
    unseen: dict[str, list] = {"1": [], "2": [], "3": []}
    for lvl, deck in g["decks"].items():
        unseen[lvl].extend(deck)
    for cid in blind:
        unseen[str(C.CARDS[cid]["level"])].append(cid)
    for pool in unseen.values():
        pool.sort()                                 # canonicalize: kill the true order
        rng.shuffle(pool)

    # Re-deal the opponent's blind reserves (same level, new identity), keeping their
    # face-up reserves — those are public — then refill each deck from the remainder.
    if blind:
        redealt = [unseen[str(C.CARDS[cid]["level"])].pop() for cid in blind]
        op["reserved"] = [c for c in op["reserved"] if c not in blind_set] + redealt
        op["reserved_from_deck"] = redealt
    for lvl in g["decks"]:
        g["decks"][lvl] = unseen[lvl][:len(g["decks"][lvl])]   # sizes are public

    g["bag"] = sorted(g["bag"])                     # canonicalize; _fill_board shuffles
    rng.shuffle(g["bag"])
    engine._save_rng(g, rng)                        # future draws follow THIS sim's rng
    return g


# ── Heuristic evaluation ─────────────────────────────────────────────────────
def _standing(game: dict, pid: str, w: dict) -> float:
    """One seat's positional worth. Scored identically for both players and
    subtracted in _value, so blocking/denial emerges from the search itself."""
    p = game["players"][pid]
    pts = engine.points_of(p)
    crowns = engine.crowns_of(p)
    cp = engine.color_points_of(p)
    best_color = max(cp.values())

    # Progress toward whichever win condition is closest, convex: 90% of the way
    # to a win is worth far more than twice 45%.
    prog = max(pts / engine.WIN_POINTS, crowns / engine.WIN_CROWNS,
               best_color / engine.WIN_COLOR_POINTS)
    s = w["progress"] * (prog ** w["progress_exp"])
    s += w["points"] * pts + w["crowns"] * crowns + w["color"] * best_color

    bon = engine.bonuses_of(p)
    s += w["bonus"] * sum(bon.values())
    s += w["bonus_spread"] * sum(1 for n in bon.values() if n > 0)

    toks = p["tokens"]
    gold = toks["gold"]
    s += w["token"] * (sum(toks.values()) - gold) + w["gold"] * gold
    s += w["privilege"] * p["privileges"] + w["reserved"] * len(p["reserved"])
    return s


def _value(game: dict, pid: str, w: dict = WEIGHTS) -> float:
    """Leaf value in [-1, 1] from pid's perspective."""
    if engine.is_over(game):
        return 1.0 if game["winner"] == pid else -1.0
    opp = engine._opponent(game, pid)
    diff = _standing(game, pid, w) - _standing(game, opp, w)
    return math.tanh(diff / w["scale"])


# ── Search-legality pruning ──────────────────────────────────────────────────
def _take_gifts_privilege(board: list, cells: list) -> bool:
    """Does this take hand the OPPONENT a Privilege? (3 of a colour, or 2+ pearls)

    Fast-pathed and called per-take inside `_legal`, which runs at every node: a
    1-cell take can be neither, and that's most of the enumeration.
    """
    if len(cells) < 2:
        return False
    colors = [board[i] for i in cells]
    if len(colors) == 3 and colors[0] == colors[1] == colors[2]:
        return True
    return colors.count("pearl") >= 2


def _legal(game: dict, pid: str) -> list:
    """legal_moves minus redundant/dominated branches, to spend sims where they
    matter. Never returns empty when legal_moves is non-empty (the CoC lesson: a
    prune that can strand the search makes it play worse, not better).

    Three prunes:
      * `skip_pending` — skipping an ability is never better than using it
        (take_same/steal are free gains; a royal is free points). Discard has no skip.
      * duplicate reserve `gold_cell`s — WHICH gold you take is very nearly
        irrelevant: gold tokens are fungible, and vacating a cell can never open a
        line (the empty cell still breaks contiguity exactly as the gold did). So
        the 3 gold cells x 15 sources = 45 branches collapse to 15. The one residual
        effect is spiral REFILL order on a later replenish — a deliberate, tiny
        approximation bought for a ~3x branching cut on this move class.
      * takes that are a strict SUBSET of another legal take — taking {white} when
        {white, pearl} is on offer is free value left on the board (reported from a
        real game). This one is a real BLUNDER FIX, not just a speed prune: one extra
        token is worth ~0.018 to `_value`, which is at or BELOW rollout noise, so the
        search genuinely could not tell the two apart and the tie-break picked
        near-arbitrarily — measured, it left the free token behind in 32/60 positions,
        a coin flip. With the prune: 0/60, because the blunder is never enumerated.
        It also cuts branching ~2.8x on a full board (159 -> 56 moves), so every
        surviving move gets ~2.8x the sims. That dominates the scan's cost — A/B vs
        `hard+nodom`, CRN-paired, mirror verified at exactly 0.5000:
            equal-SIMS (400 iters)   -> 0.675 [0.520,0.799] n=40
            equal-TIME (0.5s/decide) -> 0.700 [0.546,0.819] n=40
        i.e. the edge GROWS once the prune has to pay for itself in wall-clock.
        Dominance is exact, not heuristic. A superset take is never worse:
          - it grants strictly more tokens, and a token carries no per-token cost;
          - the 10-cap can't punish it either: discard the extra straight back and you
            hold exactly the subset's hand. (Not literally identical — the discard
            sends that token to the BAG rather than leaving it on the board — but that
            direction only ever denies the opponent, so the >= still holds.)
          - the one real cost is handing the opponent a Privilege (3-of-a-colour or
            2+ pearls), so a superset that newly triggers that does NOT dominate.
            That exception is why "just always take the most" would be a rules bug.
    """
    moves = engine.legal_moves(game, pid)
    if len(moves) <= 1:
        return moves
    board = game["board"]

    # Takes are only ever 1-3 cells, so dominance resolves with two lookup sets
    # instead of an O(takes^2) subset scan — worth the care, since _legal runs at
    # every node AND every rollout step (the scan cost 7x legal_moves itself).
    #   * a 1-take never gifts, so it is dominated iff its cell sits in ANY
    #     non-gifting take of size >= 2  -> `covered`.
    #   * a 2-take is dominated iff some 3-take contains it that doesn't newly gift.
    #   * a 3-take is maximal: nothing can dominate it.
    covered, dom_pairs, dom_pairs_gift = set(), set(), set()
    for m in moves if _TAKE_DOMINANCE else ():
        if m["type"] != "take":
            continue
        cells = m["cells"]
        gift = _take_gifts_privilege(board, cells)
        if len(cells) >= 2 and not gift:
            covered.update(cells)
        if len(cells) == 3:
            a, b, c = cells
            tgt = dom_pairs_gift if gift else dom_pairs
            tgt.add(frozenset((a, b))); tgt.add(frozenset((b, c))); tgt.add(frozenset((a, c)))

    pruned, seen_reserve = [], set()
    for m in moves:
        if m["type"] == "skip_pending":
            continue
        if m["type"] == "reserve":
            src = m["source"]
            key = (src["kind"], src["level"], src.get("slot"))
            if key in seen_reserve:
                continue
            seen_reserve.add(key)
        if m["type"] == "take":
            cells = m["cells"]
            if len(cells) == 1:
                if cells[0] in covered:
                    continue
            elif len(cells) == 2:
                pair = frozenset(cells)
                if pair in dom_pairs or (pair in dom_pairs_gift
                                         and _take_gifts_privilege(board, cells)):
                    continue
        pruned.append(m)
    return pruned or moves


# ── Rollout ──────────────────────────────────────────────────────────────────
_ROLLOUT_PRIORITY = {"buy": 0, "take": 1, "reserve": 2, "replenish": 3, "use_privilege": 4}


def _rollout_move(game: dict, pid: str, rng: random.Random):
    moves = _legal(game, pid)
    if not moves:
        return None
    if game.get("pending_pid") == pid:
        return rng.choice(moves)
    best = min(_ROLLOUT_PRIORITY.get(m["type"], 9) for m in moves)
    top = [m for m in moves if _ROLLOUT_PRIORITY.get(m["type"], 9) == best]
    return rng.choice(top)


def _rollout(game: dict, pid: str, rng: random.Random, steps: int = _ROLLOUT_STEPS) -> float:
    """Play a short, cheap continuation then evaluate (steps=0 -> a static leaf).

    Whether the rollout earns its ~40x cost per sim is game-specific and MEASURED,
    not assumed: Spender's static value-leaf beats its rollout, while Castles of
    Crimson needs the rollout (its payoffs are delayed, so a 0-step leaf undervalues
    in-flight turns). See ai_selfplay.probe / the module note in DIFFICULTY.
    """
    for _ in range(steps):
        if engine.is_over(game):
            break
        actor = game.get("pending_pid") or game["turn"]
        mv = _rollout_move(game, actor, rng)
        if mv is None:
            break
        ok, _err = engine.apply_move(game, actor, mv)
        if not ok:
            break
    return _value(game, pid)


# ── MCTS ─────────────────────────────────────────────────────────────────────
class _Node:
    __slots__ = ("actor", "moves", "children", "n", "w", "expanded")

    def __init__(self, actor: str, moves: list):
        self.actor = actor
        self.moves = moves
        self.children: list[_Node | None] = [None] * len(moves)
        self.n = [0] * len(moves)
        self.w = [0.0] * len(moves)
        self.expanded = False


def _select(node: _Node, total: int) -> int:
    """UCT selection: `U = C_PUCT*sqrt(N)/(1+n)`, with NO 1/branches prior scaling.

    The missing prior looks like a bug. It isn't, and the reason is MEASURED, not
    argued (CRN-paired, equal sims, mirror verified at exactly 0.5000):

        prior@c100   vs no-prior@c1.5  ->  0.5000   (100/76 ~= 1.3 ~= 1.5: identical)
        no-prior@c0.4 vs no-prior@c1.5 ->  0.5000   (broad plateau)
        prior@c1.5   vs no-prior@c1.5  ->  0.2500   (effective c ~= 0.02: far too low)

    So a FLAT prior is mathematically just a constant rescale of C_PUCT — it carries no
    information and is not the issue. What matters is the exploration LEVEL, and there
    is a wide plateau (~0.4-1.5) with a cliff below it: at c~=0.02 the search commits to
    whatever the first couple of rollouts liked, and this leaf is NOISY (rollout ~+-0.3),
    so it commits to noise. Broad sampling + picking the best MEAN (the value tie-break
    in choose_move) is the better estimator here.

    Selection and the final pick are a PAIR: near-uniform visits are only sound because
    the pick breaks visit ties by value. Don't change one without re-measuring the other.
    A LEARNED prior would be different — it carries real information — so revisit this
    if a policy net ever lands.
    """
    best, best_i = -1e18, 0
    sqrt_t = math.sqrt(max(1, total))
    for i in range(len(node.moves)):
        n = node.n[i]
        q = node.w[i] / n if n else 0.0      # FPU: an unvisited move looks neutral
        u = C_PUCT * sqrt_t / (1 + n)
        s = q + u
        if s > best:
            best, best_i = s, i
    return best_i


def _simulate(game: dict, node: _Node, root_pid: str, rng: random.Random, depth: int,
              steps: int) -> float:
    """One simulation. Returns the value from ROOT_PID's perspective.

    Turns don't strictly alternate (AGAIN chains, pendings), so each edge is
    credited by the ACTING player's identity, not by parity.
    """
    if engine.is_over(game) or depth >= _MAX_TREE_DEPTH:
        return _rollout(game, root_pid, rng, steps)
    i = _select(node, sum(node.n))
    mv = node.moves[i]
    ok, _err = engine.apply_move(game, node.actor, mv)
    if not ok:
        return _value(game, root_pid)
    child = node.children[i]
    if child is None:
        if engine.is_over(game):
            v = _value(game, root_pid)
        else:
            actor = game.get("pending_pid") or game["turn"]
            node.children[i] = _Node(actor, _legal(game, actor))
            v = _rollout(game, root_pid, rng, steps)
        node.n[i] += 1
        node.w[i] += v
        return v
    v = _simulate(game, child, root_pid, rng, depth + 1, steps)
    node.n[i] += 1
    node.w[i] += v
    return v


def choose_move(game: dict, pid: str, *, difficulty: str = DEFAULT_DIFFICULTY,
                rng: random.Random | None = None,
                time_limit: float | None = None, max_iters: int | None = None,
                temperature: float | None = None, rollout_steps: int | None = None,
                take_dominance: bool | None = None):
    """Pick a move for `pid`'s current decision via determinized MCTS.

    `take_dominance=False` disables the dominated-take prune for THIS decision — the
    A/B hook for `ai_selfplay`'s "hard+nodom" spec. Set per-call rather than by
    flipping the module global directly, so an arena can vary ONE side (the same
    reason `rollout_steps` is a parameter).
    """
    global _TAKE_DOMINANCE
    _TAKE_DOMINANCE = True if take_dominance is None else take_dominance
    cfg = DIFFICULTY.get(difficulty, DIFFICULTY[DEFAULT_DIFFICULTY])
    time_limit = cfg["time_limit"] if time_limit is None else time_limit
    max_iters = cfg["max_iters"] if max_iters is None else max_iters
    temperature = cfg["temperature"] if temperature is None else temperature
    steps = cfg.get("rollout_steps", _ROLLOUT_STEPS) if rollout_steps is None else rollout_steps
    rng = rng or random.Random()

    root_moves = _legal(game, pid)
    if not root_moves:
        return None
    if len(root_moves) == 1:
        return root_moves[0]

    root = _Node(pid, root_moves)
    deadline = time.monotonic() + time_limit
    iters = 0
    while iters < max_iters and time.monotonic() < deadline:
        iters += 1
        sim = _determinize(game, pid, rng)
        _simulate(sim, root, pid, rng, 0, steps)

    if temperature and temperature > 0:
        # Sample by VALUE (softmax over mean Q), NOT by visit count.
        #
        # The usual AlphaZero trick — sample proportional to visits — is WRONG for this
        # search and was measured so: our selection is deliberately exploration-heavy, so
        # visits come out near-uniform across all ~76 branches (quality lives in Q, not in
        # the visit distribution). Temperature-on-visits therefore collapses to a uniform
        # random move, and the "normal" tier LOST to the trivial random-legal bot 0.20.
        # Softmax over Q gives a real "understands but errs" opponent instead.
        scored = [(i, root.w[i] / root.n[i]) for i in range(len(root.moves)) if root.n[i]]
        if scored:
            top = max(q for _, q in scored)
            weights = [math.exp((q - top) / temperature) for _, q in scored]
            return root.moves[rng.choices([i for i, _ in scored], weights=weights, k=1)[0]]
    # Visit count first, mean value as the TIE-BREAK. The tie-break is load-bearing
    # when sims are thin relative to the branching factor: without it `max` returns
    # the FIRST index, which is whatever legal_moves enumerates first (a token take)
    # — a badly under-sampled search then "always takes tokens", never buys, and the
    # game literally never ends (Duel has no turn limit).
    best_i = max(range(len(root.moves)),
                 key=lambda i: (root.n[i], root.w[i] / root.n[i] if root.n[i] else -2.0))
    return root.moves[best_i]


def play_turn_plan(game: dict, pid: str, *, difficulty: str = DEFAULT_DIFFICULTY,
                   rng: random.Random | None = None, turn_budget: float | None = None,
                   max_moves: int = 24) -> list:
    """Plan `pid`'s whole turn on a CLONE and return the move sequence.

    The server applies these back one at a time (re-validating each), so the heavy
    search runs off the event loop. Stops when the turn passes to the opponent — an
    AGAIN chain keeps the same `turn`, so the guard is the ACTOR, not the turn field.

    The turn's total think time is capped by `turn_budget`: each decision gets at most
    the tier's per-decision `time_limit` AND whatever budget remains, so a multi-decision
    turn can't multiply the wait. Once the budget is spent the rest of the turn still
    resolves (a small floor per decision) rather than bailing to a half-planned turn.
    """
    cfg = DIFFICULTY.get(difficulty, DIFFICULTY[DEFAULT_DIFFICULTY])
    turn_budget = cfg.get("turn_budget", 5.0) if turn_budget is None else turn_budget
    rng = rng or random.Random()
    sim = _clone_game(game)
    seq = []
    deadline = time.monotonic() + turn_budget
    for _ in range(max_moves):
        if engine.is_over(sim):
            break
        actor = sim.get("pending_pid") or sim["turn"]
        if actor != pid:
            break
        left = deadline - time.monotonic()
        budget = max(0.05, min(cfg["time_limit"], left))   # floor: always decide, never stall
        mv = choose_move(sim, pid, difficulty=difficulty, rng=rng, time_limit=budget)
        if mv is None:
            break
        ok, _err = engine.apply_move(sim, pid, mv)
        if not ok:
            break
        seq.append(mv)
    return seq
