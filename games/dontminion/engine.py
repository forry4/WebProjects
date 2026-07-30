"""Dontminion engine — pure rules for Dominion (Base 2E + Intrigue 2E).

No I/O, no FastAPI. The game dict is JSON-safe (no sets, RNG persisted as lists)
so it survives save/reconnect. Public API (the frozen contract — see
.claude-plans/i-want-to-add-luminous-pebble.md §9 and games/dontminion/CLAUDE.md):

    new_game(player_ids, expansions, seed=None, names=None, kingdom=None) -> game
    apply_move(game, pid, move) -> (ok, err)
    legal_moves(game, pid) -> list[move]
    sample_decision(game, pid, rng) -> decision payload
    is_over(game) / winners(game) / score_game(game)
    player_view(game, pid) -> per-recipient redacted dict
    cost(game, card) -> int

Moves are dicts keyed on "type": play_action / play_treasure / play_all_treasures /
buy / end_phase / decision. Pauses for input are FRAMES on the game["pending"] stack;
pending_pid / pending_kind mirror the top frame. Auto frames (parked continuations)
are executed by _drive() so at rest the top frame is always a decision frame or the
stack is empty. Card effects live in effects_*.py and register EFFECTS/STAGES; they
may only touch the game through the kernel helpers exported here.
"""

import copy
import itertools
import random

from .cards import CARDS, KINGDOM, pile_size

BASIC_CARDS = ("Copper", "Silver", "Gold", "Estate", "Duchy", "Province", "Curse")
_DRIVE_CAP = 500
_ENUM_CAP = 200


# --- RNG (persisted as lists so the game dict stays JSON-safe) ---------------

def _make_rng(game):
    rng = random.Random()
    st = game.get("rng_state")
    if st is not None:
        rng.setstate((st[0], tuple(st[1]), st[2]))
    return rng


def _save_rng(game, rng):
    st = rng.getstate()
    game["rng_state"] = [st[0], list(st[1]), st[2]]


# --- logging -----------------------------------------------------------------

def _log(game, pid, event, private_to=None, **kw):
    entry = dict(kw)
    d = game.get("log_depth", 0)
    if d:
        entry["d"] = min(d, 3)
    if private_to is not None:
        entry["private_to"] = list(private_to)
    # Core fields are set LAST so an event kwarg can never clobber them. A
    # draw kwarg named n= used to overwrite the SEQUENCE n with the card count
    # — every draw entry shared n, the client keyed lines on it, and React's
    # reconciler visibly scrambled the log. Counts are the `count` kwarg now.
    entry["n"] = len(game["log"])
    entry["pid"] = pid
    entry["event"] = event
    game["log"].append(entry)


# log_depth tracks how deep inside a card's resolution we are, so the client can
# indent sub-effects under the play that caused them (the Dominion-online look).
# Incremented around every effect/stage dispatch; always 0 at rest (try/finally),
# so snapshots/saves never carry a stale depth.

def _push_depth(game):
    game["log_depth"] = game.get("log_depth", 0) + 1


def _pop_depth(game):
    game["log_depth"] = max(0, game.get("log_depth", 1) - 1)


# --- frame machinery ---------------------------------------------------------

def _sync_pending(game):
    top = game["pending"][-1] if game["pending"] else None
    game["pending_pid"] = top["pid"] if top else None
    game["pending_kind"] = top["kind"] if top else None


def _push_frame(game, frame):
    game["pending"].append(frame)
    _sync_pending(game)


def _pop_frame(game):
    frame = game["pending"].pop()
    _sync_pending(game)
    return frame


def push_choose_cards(game, pid, card, stage, cards, mn, mx, purpose, data=None):
    cards = list(cards)
    mn = max(0, min(mn, len(cards)))
    mx = max(mn, min(mx, len(cards)))
    _push_frame(game, {"kind": "choose_cards", "pid": pid, "card": card, "stage": stage,
                       "constraint": {"cards": cards, "min": mn, "max": mx, "purpose": purpose},
                       "data": data or {}})


def push_choose_pile(game, pid, card, stage, piles, data=None):
    piles = list(piles)
    if not piles:
        raise ValueError("push_choose_pile with no piles — pusher must guard")
    _push_frame(game, {"kind": "choose_pile", "pid": pid, "card": card, "stage": stage,
                       "constraint": {"piles": piles}, "data": data or {}})


def push_choose_option(game, pid, card, stage, options, pick=1, distinct=True, data=None):
    _push_frame(game, {"kind": "choose_option", "pid": pid, "card": card, "stage": stage,
                       "constraint": {"options": list(options), "pick": pick, "distinct": distinct},
                       "data": data or {}})


def push_order_cards(game, pid, card, stage, cards, data=None):
    _push_frame(game, {"kind": "order_cards", "pid": pid, "card": card, "stage": stage,
                       "constraint": {"cards": list(cards)}, "data": data or {}})


def push_place_in_deck(game, pid, card, stage, deck_card, data=None):
    deck_len = len(game["seats"][pid]["deck"])
    _push_frame(game, {"kind": "place_in_deck", "pid": pid, "card": card, "stage": stage,
                       "constraint": {"card": deck_card, "deck_len": deck_len}, "data": data or {}})


def push_name_card(game, pid, card, stage, data=None):
    _push_frame(game, {"kind": "name_card", "pid": pid, "card": card, "stage": stage,
                       "constraint": {"cards": sorted(game["supply"])}, "data": data or {}})


def push_auto(game, pid, card, stage, data=None):
    _push_frame(game, {"kind": "auto", "pid": pid, "card": card, "stage": stage,
                       "constraint": None, "data": data or {}})


def _stage_fn(card, stage):
    fn = KERNEL_STAGES.get((card, stage))
    if fn is None:
        from . import effects
        fn = effects.STAGES.get((card, stage))
    if fn is None:
        raise KeyError(f"dontminion: no stage handler for {card!r}/{stage!r}")
    return fn


def _effect_fn(card):
    from . import effects
    fn = effects.EFFECTS.get(card)
    if fn is None:
        raise KeyError(f"dontminion: no effect registered for {card!r}")
    return fn


def _drive(game):
    """Run auto frames until the top of the stack is a decision frame (or empty)."""
    for _ in range(_DRIVE_CAP):
        if not game["pending"] or game["pending"][-1]["kind"] != "auto":
            return
        frame = _pop_frame(game)
        _push_depth(game)
        try:
            _stage_fn(frame["card"], frame["stage"])(game, frame["pid"], frame, None)
        finally:
            _pop_depth(game)
    raise RuntimeError("dontminion: _drive exceeded iteration cap (runaway auto frames)")


# --- undo (one MOVE at a time; gated on HIDDEN INFORMATION, the Duel model) ---
# A snapshot is pushed before each of the turn player's own moves, so undo can
# be pressed repeatedly — walking back move by move until the start of the turn
# ("nothing to undo") or until something revealed information that can't be
# un-seen, which locks AND clears the whole stack.

_UNDO_CAP = 30  # snapshots per turn — a runaway backstop, far above real turns


def _mark_revealed(game):
    """This turn exposed information that can't be un-seen (a draw, a look, a
    reveal, a pass, an opponent's choice) — undo is dead from here on."""
    game["turn_revealed"] = True
    game["undo_stack"] = []


def _arm_undo(game):
    game["turn_revealed"] = False
    game["undo_stack"] = []


def _push_undo(game):
    """Snapshot the game before a (turn player's) move. Snapshots exclude the
    stack itself (else they'd nest); JSON-safe so they survive save/reconnect;
    stripped from player_view (they hold every hidden zone)."""
    snap = copy.deepcopy({k: v for k, v in game.items() if k != "undo_stack"})
    game["undo_stack"].append(snap)
    if len(game["undo_stack"]) > _UNDO_CAP:
        game["undo_stack"].pop(0)


def _undo_move(game, pid):
    if pid != game["turn"]:
        return False, "not your turn"
    if game.get("turn_revealed"):
        return False, "can't undo — new information was revealed this turn"
    stack = game.get("undo_stack") or []
    if not stack:
        return False, "nothing to undo"
    snap = stack.pop()
    game.clear()
    game.update(snap)
    game["undo_stack"] = stack   # the remaining, earlier snapshots
    _log(game, pid, "undo")
    return True, None


# --- kernel zone helpers (importable by card modules) ------------------------

def draw(game, pid, n):
    """Draw up to n cards (shuffle-on-empty per the rules). Returns the drawn list."""
    seat = game["seats"][pid]
    drawn = []
    for _ in range(n):
        if not seat["deck"]:
            if not seat["discard"]:
                break
            rng = _make_rng(game)
            pile = seat["discard"][:]
            rng.shuffle(pile)
            seat["deck"] = pile
            seat["discard"] = []
            _save_rng(game, rng)
            _log(game, pid, "shuffle")
        drawn.append(seat["deck"].pop(0))
    seat["hand"].extend(drawn)
    if drawn:
        _mark_revealed(game)
        # card names are per-field redacted in player_view (owner-only pre-over)
        _log(game, pid, "draw", count=len(drawn), cards=list(drawn))
    return drawn


def look_top(game, pid, n):
    """Move up to n cards from the top of the deck to the seat's aside zone.

    Aside cards are excluded from any mid-look shuffle (they are not in the
    deck or discard), matching the reveal/look rules. Returns the moved list.
    """
    seat = game["seats"][pid]
    moved = []
    for _ in range(n):
        if not seat["deck"]:
            if not seat["discard"]:
                break
            rng = _make_rng(game)
            pile = seat["discard"][:]
            rng.shuffle(pile)
            seat["deck"] = pile
            seat["discard"] = []
            _save_rng(game, rng)
            _log(game, pid, "shuffle")
        moved.append(seat["deck"].pop(0))
    seat["aside"].extend(moved)
    if moved:
        _mark_revealed(game)
    return moved


def gain(game, pid, card, dest="discard"):
    """Gain from the supply; returns False (nothing happens) if the pile is empty."""
    if game["supply"].get(card, 0) <= 0:
        return False
    game["supply"][card] -= 1
    seat = game["seats"][pid]
    if dest == "discard":
        seat["discard"].append(card)
    elif dest == "hand":
        seat["hand"].append(card)
    elif dest == "deck":
        seat["deck"].insert(0, card)
    else:
        raise ValueError(f"bad gain dest {dest!r}")
    _log(game, pid, "gain", card=card, dest=dest)
    return True


def gain_from_trash(game, pid, card):
    if card not in game["trash"]:
        return False
    game["trash"].remove(card)
    game["seats"][pid]["discard"].append(card)
    _log(game, pid, "gain_from_trash", card=card)
    return True


def trash(game, pid, cards, zone="hand"):
    seat = game["seats"][pid]
    for c in cards:
        seat[zone].remove(c)
        game["trash"].append(c)
    if cards:
        _log(game, pid, "trash", cards=list(cards))


def trash_from_supply(game, card):
    if game["supply"].get(card, 0) <= 0:
        return False
    game["supply"][card] -= 1
    game["trash"].append(card)
    return True


def discard(game, pid, cards, zone="hand", public=False):
    """Discard named cards from a zone. Names are logged for every discard —
    faithful to the table, where cards land face-up on the pile one at a time
    (the pile can't be browsed later, but the event itself is public)."""
    seat = game["seats"][pid]
    for c in cards:
        seat[zone].remove(c)
        seat["discard"].append(c)
    if cards:
        _log(game, pid, "discard", cards=list(cards), count=len(cards))


def topdeck(game, pid, card, zone="hand", public=False):
    seat = game["seats"][pid]
    seat[zone].remove(card)
    seat["deck"].insert(0, card)
    if public:
        _log(game, pid, "topdeck", card=card)
    else:
        _log(game, pid, "topdeck")


def reveal(game, pid, cards, source):
    """Reveals are information events only — cards stay where they are."""
    _mark_revealed(game)
    _log(game, pid, "reveal", cards=list(cards), source=source)


def take_aside(game, pid, cards, dest="hand"):
    """Move looked-at/set-aside cards out of the aside zone (Library keeps,
    Patrol pockets victory cards, ...)."""
    seat = game["seats"][pid]
    for c in cards:
        seat["aside"].remove(c)
        if dest == "hand":
            seat["hand"].append(c)
        elif dest == "discard":
            seat["discard"].append(c)
        else:
            raise ValueError(f"bad take_aside dest {dest!r}")


def deck_from_aside(game, pid, order):
    """Return aside cards to the top of the deck in the given order
    (order[0] ends up on top) — Sentry/Patrol put-backs."""
    seat = game["seats"][pid]
    for c in order:
        seat["aside"].remove(c)
    seat["deck"] = list(order) + seat["deck"]


def deck_insert(game, pid, card, position, zone="hand"):
    """Put a card from a zone anywhere in the deck (0 = top) — Secret Passage."""
    seat = game["seats"][pid]
    seat[zone].remove(card)
    seat["deck"].insert(position, card)
    _log(game, pid, "deck_insert")


def pass_card(game, giver, receiver, card):
    """Masquerade hand-to-hand pass: identity visible only to giver+receiver."""
    _mark_revealed(game)
    game["seats"][giver]["hand"].remove(card)
    game["seats"][receiver]["hand"].append(card)
    _log(game, giver, "pass", private_to=[giver, receiver], card=card, to=receiver)
    _log(game, giver, "pass_public", to=receiver)


# The +X counters always belong to the turn player (they're turn-scoped), so the
# "plus" log lines carry game["turn"] no matter which card path granted them.

def add_actions(game, n):
    game["actions"] += n
    if n > 0:
        _log(game, game["turn"], "plus", actions=n)


def add_buys(game, n):
    game["buys"] += n
    if n > 0:
        _log(game, game["turn"], "plus", buys=n)


def add_coins(game, n):
    game["coins"] += n
    if n > 0:
        _log(game, game["turn"], "plus", coins=n)


def opponents(game, pid):
    """All other players, in turn order starting after pid."""
    order = game["players"]
    i = order.index(pid)
    return order[i + 1:] + order[:i]


def count_empty_piles(game):
    return sum(1 for v in game["supply"].values() if v == 0)


def cost(game, card):
    """THE single cost function — Bridge reduction applies everywhere, min 0."""
    return max(0, CARDS[card]["cost"] - game["turn_ctx"]["bridges"])


# --- playing action cards + the attack/reaction kernel -----------------------

def play_action_card(game, pid, card, from_zone="hand"):
    """Move the card to in_play (from_zone=None for throne-room replays), count the
    play, and run its effect. Attack-typed plays are wrapped: reaction windows for
    every opponent holding an eligible Reaction resolve BEFORE the play ability
    (official timing), with per-play immunity collected in the play_ability frame."""
    seat = game["seats"][pid]
    if from_zone is not None:
        seat[from_zone].remove(card)
        seat["in_play"].append(card)
    game["turn_ctx"]["actions_played"] += 1
    _log(game, pid, "play", card=card)
    if "attack" in CARDS[card]["types"]:
        push_auto(game, pid, "__attack", "play_ability", data={"card": card, "immune": []})
        for o in reversed(opponents(game, pid)):
            opts = _reaction_options(game, o, immune=[], moat_ok=True)
            if opts:
                _push_window(game, o, opts)
    else:
        _push_depth(game)
        try:
            _effect_fn(card)(game, pid)
        finally:
            _pop_depth(game)


def _reaction_options(game, o, immune, moat_ok=True):
    hand = game["seats"][o]["hand"]
    opts = []
    if moat_ok and "Moat" in hand and o not in immune:
        opts.append({"id": "reveal_moat", "label": "Reveal Moat (unaffected by this attack)"})
    if "Diplomat" in hand and len(hand) >= 5:
        opts.append({"id": "reveal_diplomat", "label": "Reveal Diplomat (+2 cards, then discard 3)"})
    if opts:
        opts.append({"id": "decline", "label": "Don't react"})
    return opts


def _push_window(game, o, opts):
    push_choose_option(game, o, "__attack", "window", options=opts, pick=1)


def _current_attack_frame(game):
    for f in reversed(game["pending"]):
        if f["card"] == "__attack" and f["stage"] == "play_ability":
            return f
    return None


def _k_window(game, pid, frame, choice):
    atk = _current_attack_frame(game)
    immune = atk["data"]["immune"] if atk else []
    cid = choice["ids"][0]
    if cid == "decline":
        return
    if cid == "reveal_moat":
        reveal(game, pid, ["Moat"], "hand")
        if pid not in immune:
            immune.append(pid)
        opts = _reaction_options(game, pid, immune, moat_ok=False)
        if opts:
            _push_window(game, pid, opts)
    elif cid == "reveal_diplomat":
        reveal(game, pid, ["Diplomat"], "hand")
        draw(game, pid, 2)
        hand = game["seats"][pid]["hand"]
        push_choose_cards(game, pid, "__attack", "diplomat_discard",
                          cards=list(hand), mn=3, mx=3, purpose="discard")


def _k_diplomat_discard(game, pid, frame, choice):
    discard(game, pid, choice["cards"])
    atk = _current_attack_frame(game)
    immune = atk["data"]["immune"] if atk else []
    opts = _reaction_options(game, pid, immune, moat_ok=True)
    if opts:
        _push_window(game, pid, opts)


def _k_play_ability(game, pid, frame, choice):
    game["_atk_immune"] = list(frame["data"]["immune"])
    try:
        _effect_fn(frame["data"]["card"])(game, pid)
    finally:
        game.pop("_atk_immune", None)


def attack_opponents(game, pid, card, per_opp_stage, data=None, immune=None):
    """Queue the card's per-opponent stage for every non-immune opponent, in turn
    order; each opponent's whole chain resolves before the next starts.

    Called from on_play (inside the play_ability frame) the per-play immune set
    is picked up automatically. A card that calls this from a LATER stage (its
    attack part follows another choice — Minion's mode, Replace's gain) must
    capture `list(game["_atk_immune"])` into its frame data during on_play and
    pass it back via `immune=` — the transient is gone by then."""
    if immune is None:
        immune = game.get("_atk_immune", [])
    targets = [o for o in opponents(game, pid) if o not in immune]
    if targets:
        push_auto(game, pid, "__attack", "next",
                  data={"queue": targets, "card": card, "stage": per_opp_stage,
                        "extra": data or {}})


def _k_next(game, pid, frame, choice):
    queue = frame["data"]["queue"]
    if not queue:
        return
    o, rest = queue[0], queue[1:]
    if rest:
        push_auto(game, pid, "__attack", "next", data={**frame["data"], "queue": rest})
    push_auto(game, o, frame["data"]["card"], frame["data"]["stage"],
              data={"opp": o, **frame["data"]["extra"]})


KERNEL_STAGES = {
    ("__attack", "window"): _k_window,
    ("__attack", "diplomat_discard"): _k_diplomat_discard,
    ("__attack", "play_ability"): _k_play_ability,
    ("__attack", "next"): _k_next,
}


# --- turn-move handlers ------------------------------------------------------

def _fresh_turn_ctx():
    return {"bridges": 0, "actions_played": 0, "merchants": 0,
            "silver_played": False, "bought": False}


def _h_play_action(game, pid, move):
    if game["phase"] != "action":
        return False, "not in your action phase"
    card = move.get("card")
    if card not in game["seats"][pid]["hand"]:
        return False, "card not in hand"
    if "action" not in CARDS[card]["types"]:
        return False, "not an action card"
    if game["actions"] <= 0:
        return False, "no actions left"
    game["actions"] -= 1
    play_action_card(game, pid, card, from_zone="hand")
    return True, None


def _play_one_treasure(game, pid, card):
    seat = game["seats"][pid]
    seat["hand"].remove(card)
    seat["in_play"].append(card)
    game["coins"] += CARDS[card]["coins"]
    _log(game, pid, "play", card=card, coins=CARDS[card]["coins"])
    if card == "Silver" and not game["turn_ctx"]["silver_played"]:
        game["turn_ctx"]["silver_played"] = True
        m = game["turn_ctx"]["merchants"]
        if m:
            game["coins"] += m
            _log(game, pid, "plus", coins=m, why="Merchant")


def _h_play_treasure(game, pid, move):
    if game["phase"] != "buy":
        return False, "treasures are played in your buy phase"
    if game["turn_ctx"]["bought"]:
        return False, "can't play treasures after buying"
    card = move.get("card")
    if card not in game["seats"][pid]["hand"]:
        return False, "card not in hand"
    if "treasure" not in CARDS[card]["types"]:
        return False, "not a treasure"
    _play_one_treasure(game, pid, card)
    return True, None


def _h_play_all_treasures(game, pid, move):
    if game["phase"] != "buy":
        return False, "treasures are played in your buy phase"
    if game["turn_ctx"]["bought"]:
        return False, "can't play treasures after buying"
    hand = game["seats"][pid]["hand"]
    for card in [c for c in list(hand) if "treasure" in CARDS[c]["types"]]:
        _play_one_treasure(game, pid, card)
    return True, None


def _h_buy(game, pid, move):
    if game["phase"] != "buy":
        return False, "not in your buy phase"
    card = move.get("card")
    if card not in game["supply"]:
        return False, "no such pile"
    if game["supply"][card] <= 0:
        return False, "pile is empty"
    if game["buys"] <= 0:
        return False, "no buys left"
    c = cost(game, card)
    if c > game["coins"]:
        return False, "can't afford it"
    game["coins"] -= c
    game["buys"] -= 1
    game["turn_ctx"]["bought"] = True
    _log(game, pid, "buy", card=card)
    gain(game, pid, card)
    return True, None


def _h_end_phase(game, pid, move):
    if game["phase"] == "action":
        game["phase"] = "buy"
        _log(game, pid, "phase", phase="buy")
    else:
        _end_turn(game, pid)
    return True, None


_HANDLERS = {
    "play_action": _h_play_action,
    "play_treasure": _h_play_treasure,
    "play_all_treasures": _h_play_all_treasures,
    "buy": _h_buy,
    "end_phase": _h_end_phase,
}


def _end_turn(game, pid):
    seat = game["seats"][pid]
    seat["discard"].extend(seat["in_play"])
    seat["in_play"] = []
    seat["discard"].extend(seat["hand"])
    seat["hand"] = []
    draw(game, pid, 5)
    seat["turns_taken"] += 1
    if game["supply"].get("Province", 0) <= 0 or count_empty_piles(game) >= 3:
        _finish_game(game)
        return
    order = game["players"]
    nxt = order[(order.index(pid) + 1) % len(order)]
    game["turn"] = nxt
    game["turn_number"] += 1
    game["phase"] = "action"
    game["actions"] = 1
    game["buys"] = 1
    game["coins"] = 0
    game["turn_ctx"] = _fresh_turn_ctx()
    _log(game, nxt, "turn_start", turn=game["turn_number"])
    _arm_undo(game)


def _finish_game(game):
    game["over"] = True
    scores = score_game(game)
    game["scores"] = scores
    best = max(s["vp"] for s in scores.values())
    tied = [p for p in game["players"] if scores[p]["vp"] == best]
    if len(tied) > 1:
        fewest = min(scores[p]["turns"] for p in tied)
        tied = [p for p in tied if scores[p]["turns"] == fewest]
    game["winners"] = tied
    _log(game, None, "game_over", winners=list(tied))


# --- the move gate -----------------------------------------------------------

def apply_move(game, pid, move):
    if game["over"]:
        return False, "game is over"
    if not isinstance(move, dict):
        return False, "bad move"
    mt = move.get("type")
    if mt == "undo_turn":
        # BEFORE the pending gate — an unrevealed move is undoable even with a
        # frame open (yours: a Workshop pile pick; an opponent's: a Militia they
        # haven't answered yet). legal_moves deliberately never offers this, so
        # the random bot can't take it back.
        ok, err = _undo_move(game, pid)
        if ok:
            _post_move(game)
        return ok, err
    pushed = False
    if game["pending_pid"] is not None:
        if pid != game["pending_pid"]:
            return False, "not your decision"
        if mt != "decision":
            return False, f"must resolve {game['pending_kind']} first"
        if pid == game["turn"] and not game.get("turn_revealed"):
            _push_undo(game)
            pushed = True
        ok, err = _resolve_decision(game, pid, move)
    elif mt == "decision":
        return False, "nothing to decide"
    elif pid != game["turn"]:
        return False, "not your turn"
    else:
        handler = _HANDLERS.get(mt)
        if handler is None:
            return False, f"unknown move: {mt}"
        if not game.get("turn_revealed"):
            _push_undo(game)
            pushed = True
        ok, err = handler(game, pid, move)
    if ok:
        _drive(game)
        _post_move(game)
    elif pushed and game.get("undo_stack"):
        game["undo_stack"].pop()   # a rejected move mutated nothing
    return ok, err


def _resolve_decision(game, pid, move):
    top = game["pending"][-1]
    ok, err = _validate_choice(top, move)
    if not ok:
        return False, err
    if pid != game["turn"]:
        # An opponent's choice (attack response, Masquerade pick, window
        # decline) is information the turn player didn't have — no undo after.
        _mark_revealed(game)
    frame = _pop_frame(game)
    _push_depth(game)
    try:
        _stage_fn(frame["card"], frame["stage"])(game, pid, frame, move)
    finally:
        _pop_depth(game)
    return True, None


def _validate_choice(frame, move):
    kind = frame["kind"]
    c = frame["constraint"]
    if kind == "choose_cards":
        cards = move.get("cards")
        if not isinstance(cards, list) or not all(isinstance(x, str) for x in cards):
            return False, "bad cards"
        if not (c["min"] <= len(cards) <= c["max"]):
            return False, f"pick between {c['min']} and {c['max']} cards"
        if not _is_submultiset(cards, c["cards"]):
            return False, "cards not available"
        return True, None
    if kind == "choose_option":
        ids = move.get("ids")
        if not isinstance(ids, list) or len(ids) != c["pick"]:
            return False, f"pick exactly {c['pick']} option(s)"
        valid = {o["id"] for o in c["options"]}
        if not all(i in valid for i in ids):
            return False, "unknown option"
        if c.get("distinct", True) and len(set(ids)) != len(ids):
            return False, "options must be different"
        return True, None
    if kind == "order_cards":
        order = move.get("order")
        if not isinstance(order, list) or sorted(order) != sorted(c["cards"]):
            return False, "order must use exactly the shown cards"
        return True, None
    if kind == "place_in_deck":
        pos = move.get("position")
        if not isinstance(pos, int) or not (0 <= pos <= c["deck_len"]):
            return False, f"position must be 0..{c['deck_len']}"
        return True, None
    if kind == "name_card":
        if move.get("card") not in c["cards"]:
            return False, "name a card in the supply"
        return True, None
    if kind == "choose_pile":
        if move.get("pile") not in c["piles"]:
            return False, "not an eligible pile"
        return True, None
    return False, f"unknown decision kind {kind}"


def _is_submultiset(sub, full):
    counts = {}
    for x in full:
        counts[x] = counts.get(x, 0) + 1
    for x in sub:
        counts[x] = counts.get(x, 0) - 1
        if counts[x] < 0:
            return False
    return True


# --- legal moves + uniform sampling ------------------------------------------

def legal_moves(game, pid):
    """Every ≥1-valid-move guarantee applies to the ACTOR; others get [].
    Decision spaces are enumerated completely when small (≤ _ENUM_CAP), else a
    single valid sampled fallback is returned (apply_move validates, so the UI
    never depends on this being complete)."""
    if game["over"]:
        return []
    if game["pending_pid"] is not None:
        if pid != game["pending_pid"]:
            return []
        return _legal_decisions(game, pid)
    if pid != game["turn"]:
        return []
    mv = []
    hand = game["seats"][pid]["hand"]
    if game["phase"] == "action":
        if game["actions"] > 0:
            for c in sorted(set(hand)):
                if "action" in CARDS[c]["types"]:
                    mv.append({"type": "play_action", "card": c})
    else:
        if not game["turn_ctx"]["bought"]:
            treasures = sorted({c for c in hand if "treasure" in CARDS[c]["types"]})
            for c in treasures:
                mv.append({"type": "play_treasure", "card": c})
            if treasures:
                mv.append({"type": "play_all_treasures"})
        if game["buys"] > 0:
            for pile in sorted(game["supply"]):
                if game["supply"][pile] > 0 and cost(game, pile) <= game["coins"]:
                    mv.append({"type": "buy", "card": pile})
    mv.append({"type": "end_phase"})
    return mv


def _legal_decisions(game, pid):
    frame = game["pending"][-1]
    kind = frame["kind"]
    c = frame["constraint"]
    out = []
    if kind == "choose_cards":
        seen = set()
        for k in range(c["min"], c["max"] + 1):
            for combo in itertools.combinations(sorted(c["cards"]), k):
                if combo in seen:
                    continue
                seen.add(combo)
                out.append({"type": "decision", "cards": list(combo)})
                if len(out) > _ENUM_CAP:
                    return [_sampled_fallback(game, pid)]
    elif kind == "choose_option":
        ids = [o["id"] for o in c["options"]]
        for combo in itertools.combinations(ids, c["pick"]):
            out.append({"type": "decision", "ids": list(combo)})
    elif kind == "order_cards":
        seen = set()
        for perm in itertools.permutations(c["cards"]):
            if perm in seen:
                continue
            seen.add(perm)
            out.append({"type": "decision", "order": list(perm)})
            if len(out) > _ENUM_CAP:
                return [_sampled_fallback(game, pid)]
    elif kind == "place_in_deck":
        out = [{"type": "decision", "position": p} for p in range(c["deck_len"] + 1)]
    elif kind == "name_card":
        out = [{"type": "decision", "card": n} for n in c["cards"]]
    elif kind == "choose_pile":
        out = [{"type": "decision", "pile": n} for n in c["piles"]]
    return out or [_sampled_fallback(game, pid)]


def _sampled_fallback(game, pid):
    return {"type": "decision", **sample_decision(game, pid, random.Random(0))}


def sample_decision(game, pid, rng):
    """Uniform valid payload for the top frame. Uses the caller's rng, never the
    game's rng_state (the AI must not consume game entropy)."""
    frame = game["pending"][-1]
    assert frame["pid"] == pid, "sample_decision for the wrong seat"
    kind = frame["kind"]
    c = frame["constraint"]
    if kind == "choose_cards":
        k = rng.randint(c["min"], c["max"])
        return {"cards": rng.sample(c["cards"], k)}
    if kind == "choose_option":
        ids = [o["id"] for o in c["options"]]
        return {"ids": rng.sample(ids, c["pick"])}
    if kind == "order_cards":
        order = list(c["cards"])
        rng.shuffle(order)
        return {"order": order}
    if kind == "place_in_deck":
        return {"position": rng.randint(0, c["deck_len"])}
    if kind == "name_card":
        return {"card": rng.choice(c["cards"])}
    if kind == "choose_pile":
        return {"pile": rng.choice(c["piles"])}
    raise ValueError(f"unknown decision kind {kind}")


# --- scoring -----------------------------------------------------------------

def _all_cards(game, pid):
    s = game["seats"][pid]
    return s["deck"] + s["hand"] + s["discard"] + s["in_play"] + s["aside"]


def _vp_of(game, pid):
    owned = _all_cards(game, pid)
    n = len(owned)
    duchies = owned.count("Duchy")
    total = 0
    for c in owned:
        v = CARDS[c]["vp"]
        if v == "gardens":
            total += n // 10
        elif v == "duke":
            total += duchies
        else:
            total += v
    return total


def _post_move(game):
    game["vp"] = {p: _vp_of(game, p) for p in game["players"]}


def score_game(game):
    return {p: {"vp": _vp_of(game, p), "turns": game["seats"][p]["turns_taken"]}
            for p in game["players"]}


def is_over(game):
    return bool(game["over"])


def winners(game):
    return list(game["winners"]) if game["over"] else []


# --- per-recipient redaction -------------------------------------------------

def player_view(game, viewer):
    """Build (not filter) the wire view. Deck order NEVER ships; hands only to
    their owner; discard = top + count; the raw pending stack (frame data!) is
    replaced by pending_view; rng_state/seed popped; the undo snapshots (every
    hidden zone!) never leave the server — only their COUNT ships (undo_depth),
    which with turn_revealed drives the client's Undo button. Everything
    reveals at over."""
    g = copy.deepcopy({k: v for k, v in game.items() if k != "undo_stack"})
    g["undo_depth"] = len(game.get("undo_stack") or [])
    g.pop("rng_state", None)
    g.pop("seed", None)
    pend = g.pop("pending")
    if pend:
        top = pend[-1]
        if viewer == top["pid"]:
            g["pending_view"] = {"kind": top["kind"], "card": top["card"],
                                 "constraint": top["constraint"]}
        else:
            g["pending_view"] = {"card": top["card"], "waiting_on": top["pid"]}
    else:
        g["pending_view"] = None
    over = g["over"]
    for p, seat in g["seats"].items():
        seat["deck_count"] = len(seat["deck"])
        seat["hand_count"] = len(seat["hand"])
        seat["aside_count"] = len(seat["aside"])
        seat["discard_view"] = {"top": seat["discard"][-1] if seat["discard"] else None,
                                "count": len(seat["discard"])}
        if not over:
            seat.pop("deck")
            seat.pop("discard")
            seat.pop("aside")
            if p != viewer:
                seat.pop("hand")
    log = []
    for e in g["log"]:
        if "private_to" in e and viewer not in e["private_to"]:
            continue
        # draw entries carry the drawn card names — owner-only until game over
        # (per-field redaction; the count n stays public)
        if not over and e.get("event") == "draw" and e.get("pid") != viewer and "cards" in e:
            e = {k: v for k, v in e.items() if k != "cards"}
        log.append(e)
    g["log"] = log
    return g


# --- setup -------------------------------------------------------------------

def new_game(player_ids, expansions, seed=None, names=None, kingdom=None):
    """players in seat/turn order (the caller shuffles seats); expansions a
    non-empty subset of KINGDOM's keys; kingdom overrides the random 10 (tests,
    forced-kingdom soaks)."""
    players = list(player_ids)
    if not 2 <= len(players) <= 4:
        raise ValueError("dontminion needs 2-4 players")
    exps = sorted(set(expansions or []))
    if not exps or any(e not in KINGDOM for e in exps):
        raise ValueError(f"expansions must be a non-empty subset of {sorted(KINGDOM)}")
    rng = random.Random(seed)
    if kingdom is not None:
        kingdom = list(kingdom)
        bad = [c for c in kingdom if c not in CARDS or not CARDS[c]["kingdom"]]
        if bad:
            raise ValueError(f"unknown kingdom cards: {bad}")
    else:
        pool = sorted({c for e in exps for c in KINGDOM[e]})
        if len(pool) < 10:
            raise ValueError("not enough kingdom cards in the enabled expansions")
        kingdom = sorted(rng.sample(pool, 10))
    n = len(players)
    supply = {c: pile_size(c, n) for c in BASIC_CARDS}
    for c in kingdom:
        supply[c] = pile_size(c, n)
    game = {
        "game": "dontminion",
        "players": players,
        "names": dict(names or {p: p for p in players}),
        "expansions": exps,
        "kingdom": kingdom,
        "supply": supply,
        "trash": [],
        "seats": {},
        "turn": players[0],
        "turn_number": 1,
        "phase": "action",
        "actions": 1,
        "buys": 1,
        "coins": 0,
        "turn_ctx": _fresh_turn_ctx(),
        "pending": [],
        "pending_pid": None,
        "pending_kind": None,
        "vp": {},
        "log": [],
        "log_depth": 0,
        "over": False,
        "winners": [],
        "scores": {},
        "seed": seed,
        "rng_state": None,
    }
    _save_rng(game, rng)
    for pid in players:
        game["seats"][pid] = {"deck": [], "hand": [], "discard": [],
                              "in_play": [], "aside": [], "turns_taken": 0}
        start = ["Copper"] * 7 + ["Estate"] * 3
        r = _make_rng(game)
        r.shuffle(start)
        _save_rng(game, r)
        game["seats"][pid]["deck"] = start
        draw(game, pid, 5)
    _log(game, players[0], "turn_start", turn=1)
    _post_move(game)
    # The setup draws marked "revealed" — arm the FIRST turn's undo cleanly.
    _arm_undo(game)
    return game
