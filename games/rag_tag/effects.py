"""The op vocabulary, and the registries the engine resolves it through.

`fighters.py` is generated data; this module is the closed set of things that data
is allowed to say. Nothing here knows how a turn resolves — that is `engine.py`.
What it knows is the SHAPE of every op, condition and computed value, so that a
mis-transcribed card or a newly imported expansion fails at test time with the
offending path named, instead of resolving to nothing at runtime.

Three registries:

* ``OPS`` — every declarative op, with the fields it takes. The engine dispatches
  on the op name; this is the schema those handlers can rely on.
* ``FIGHTER_FX`` — the escape hatch. A card whose behaviour is not expressible as
  ops carries ``{"op": "fx", "name": ...}``, and the named function does the work.
  Register with the ``@fx`` decorator.
* ``FIGHTER_HOOKS`` — per-fighter lifecycle callbacks the engine calls at fixed
  points, rather than a card calling them.

``UNIMPLEMENTED_FX`` is the honest half of that: the fx names the data already
uses and this module has not implemented yet. ``tests/test_fighters.py`` asserts
the data's fx names are exactly ``FIGHTER_FX | UNIMPLEMENTED_FX``, that the two
never overlap, and that nothing in ``UNIMPLEMENTED_FX`` has gone stale — so the
remaining work is machine-checked in both directions and an fx that is in neither
fails loudly rather than silently doing nothing.
"""

from __future__ import annotations

from typing import Any, Callable

# --------------------------------------------------------------------------
# The vocabulary
# --------------------------------------------------------------------------

#: Who an op acts on. ``both_opps`` is the opposing Active Fighter and their
#: Partner; ``all_others`` adds your own Partner; ``all`` adds you as well.
TARGETS = frozenset({"self", "partner", "opp", "opp_partner", "both_opps",
                     "all_others", "all"})

#: A numeric field may be an int, or one of these computed values as
#: ``{"kind": ..., ...}``. Resolved by the engine at resolution time.
VALUE_KINDS = {
    # As many as the Active Fighter's Power at the start of the turn.
    "power": (),
    # The combined Power of every Opponent whose Attack this Block negated.
    "attacking_opponents_power": (),
    # The Fey Folk's Spirit count, read at the START of the turn.
    "spirits": ("times",),
}

#: Condition kinds usable in an ``if`` op, and the extra fields each requires.
COND_KINDS = {
    "power_at_least": ("n",),
    "hp_equals": ("n",),
    "no_opponent_attacked": (),
    "self_attacked": (),
    "own_attack_blocked": (),
    "opponent_played_starting_card": (),
    "serpent": ("face",),
    "face": ("face",),
    "ships": ("min", "max"),
    "has_token": ("token",),
    "token_on": ("token", "who"),
}

def _op(*fields: str, **optional: Any) -> dict:
    return {"required": frozenset(fields), "optional": frozenset(optional)}


#: name -> the fields it takes. Every op additionally accepts ``after`` (the
#: printed THEN keyword: resolve me only once the ops before me have).
OPS = {
    "attack":         _op(target=None, success=None, flamepower=None, power_bonus=None, by=None),
    "block":          _op(success=None),
    "damage":         _op("n", target=None),
    "heal":           _op("n", target=None),
    "power":          _op("n", target=None),
    "transfer_power": _op("n", "from", "to"),
    "cancel":         _op(target=None),
    "track":          _op("track", "n"),
    "if":             _op("cond", "then", **{"else": None}),
    "fx":             _op("name"),
    # Fighter-specific verbs that are still declarative enough to stay ops:
    # they take no arguments and always mean the same thing.
    "ignite":         _op(),           # Shango: 1 Aflame! token on the Opponent
    "plant_scheme":   _op(),           # Milady: top token from the pile, face down
    "unleash_scheme": _op(),           # Milady: flip a random planted token
    "give_token":     _op("token", "to"),
    "take_token":     _op("token"),
    "flip_card":      _op(),           # The Fey Folk's Summoning cards
    "spirit":         _op("n"),        # advance the Spirits track
}

#: Ops every one of them also accepts.
UNIVERSAL_OP_FIELDS = frozenset({"op", "after"})

#: Non-op icons a health-track space may carry.
TRACK_ICONS = frozenset({"stop"})


# --------------------------------------------------------------------------
# The registries
# --------------------------------------------------------------------------

FIGHTER_FX: dict[str, Callable] = {}
FIGHTER_HOOKS: dict[str, dict[str, Callable]] = {}


def fx(name: str) -> Callable[[Callable], Callable]:
    """Register the handler for ``{"op": "fx", "name": name}``."""

    def deco(fn: Callable) -> Callable:
        if name in FIGHTER_FX:
            raise ValueError(f"duplicate FIGHTER_FX registration: {name!r}")
        if name in UNIMPLEMENTED_FX:
            raise ValueError(
                f"{name!r} is implemented — drop it from UNIMPLEMENTED_FX")
        FIGHTER_FX[name] = fn
        return fn

    return deco


#: Named by the data, not yet implemented. Shrinks to empty as engine.py lands;
#: test_fighters.py fails if it disagrees with what the data actually uses.
UNIMPLEMENTED_FX = frozenset({
    # Health-track and board mechanics
    "bodvar_transform",           # Rage tops out: +3 Power, then flip to the Bear
    "brijit_revive",              # pushed past both KOs: back at 4 HP, end of turn
    "mephisto_flip_serpent",      # flip the token WITHOUT applying the new face
    "milady_unleash_scheme",      # from the HEALTH TRACK: resolves after card actions
    # Cards
    "golem_reanimation",          # next card resolves twice, second as a fresh turn
    "mordred_execution",          # finisher, after the Opponent's card resolves
    "mephisto_drag_you_to_hell",  # lose this turn for any reason => you win instead
    "feyfolk_all_legends_must_pass",
    "brijit_redirect_attacks",
    "brijit_eternal_youth",       # steal the Opponents' Healing
    "ching_terror_of_the_seas",   # 0-7 / 8-15 / exactly 20, and the 20 resets to 0
    "wong_harder_they_fall",      # Attack using the OPPONENT'S Power
    "wong_crippling_touch",       # removes both cards from the game permanently
    "wong_match_partner_power",
    "wb_corrupted_lawman",
    "wb_keys_to_the_armory",
    "milady_poison",              # half current HP rounded down; resolves last
})


# --------------------------------------------------------------------------
# Validation — used by tests and by tools/import_bga.py
# --------------------------------------------------------------------------

class OpError(ValueError):
    """A malformed op, with the path through the data that reached it."""


def _fail(path: str, msg: str) -> None:
    raise OpError(f"{path}: {msg}")


def validate_value(value: Any, path: str) -> None:
    """An int, or a computed ``{"kind": ...}``."""
    if isinstance(value, bool):
        _fail(path, "a bool is not a number")
    if isinstance(value, int):
        return
    if not isinstance(value, dict):
        _fail(path, f"expected a number or a computed value, got {value!r}")
    kind = value.get("kind")
    if kind not in VALUE_KINDS:
        _fail(path, f"unknown computed value kind {kind!r}")
    extra = set(value) - {"kind"} - set(VALUE_KINDS[kind])
    if extra:
        _fail(path, f"computed value {kind!r} has unexpected fields {sorted(extra)}")


def validate_cond(cond: Any, path: str) -> None:
    if not isinstance(cond, dict):
        _fail(path, f"expected a condition object, got {cond!r}")
    kind = cond.get("kind")
    if kind not in COND_KINDS:
        _fail(path, f"unknown condition kind {kind!r}")
    missing = set(COND_KINDS[kind]) - set(cond)
    if missing:
        _fail(path, f"condition {kind!r} is missing {sorted(missing)}")
    extra = set(cond) - {"kind"} - set(COND_KINDS[kind])
    if extra:
        _fail(path, f"condition {kind!r} has unexpected fields {sorted(extra)}")


def validate_op(op: Any, path: str) -> None:
    if not isinstance(op, dict):
        _fail(path, f"expected an op object, got {op!r}")
    name = op.get("op")
    if name not in OPS:
        _fail(path, f"unknown op {name!r}")
    spec = OPS[name]

    missing = spec["required"] - set(op)
    if missing:
        _fail(path, f"op {name!r} is missing {sorted(missing)}")
    allowed = spec["required"] | spec["optional"] | UNIVERSAL_OP_FIELDS
    extra = set(op) - allowed
    if extra:
        _fail(path, f"op {name!r} has unexpected fields {sorted(extra)}")

    if "target" in op and op["target"] not in TARGETS:
        _fail(path, f"unknown target {op['target']!r}")
    if "to" in op and op["to"] not in TARGETS:
        _fail(path, f"unknown target {op['to']!r}")
    if "from" in op and op["from"] not in TARGETS:
        _fail(path, f"unknown target {op['from']!r}")
    if "by" in op and op["by"] not in TARGETS:
        _fail(path, f"unknown actor {op['by']!r}")
    if "n" in op:
        validate_value(op["n"], f"{path}.n")
    if "cond" in op:
        validate_cond(op["cond"], f"{path}.cond")
    if "power_bonus" in op:
        validate_value(op["power_bonus"], f"{path}.power_bonus")

    for branch in ("then", "else", "success"):
        if branch in op:
            validate_ops(op[branch], f"{path}.{branch}")


def validate_ops(ops: Any, path: str) -> None:
    if not isinstance(ops, list):
        _fail(path, f"expected a list of ops, got {ops!r}")
    for i, op in enumerate(ops):
        validate_op(op, f"{path}[{i}]")


def validate_icons(icons: Any, path: str) -> None:
    """A health-track space's icons: ops, plus the bare string ``stop``."""
    if not isinstance(icons, list):
        _fail(path, f"expected a list of icons, got {icons!r}")
    for i, icon in enumerate(icons):
        if isinstance(icon, str):
            if icon not in TRACK_ICONS:
                _fail(f"{path}[{i}]", f"unknown track icon {icon!r}")
            continue
        validate_op(icon, f"{path}[{i}]")


def collect_fx_names(ops: Any, found: set[str]) -> set[str]:
    """Every fx name reachable from an op list, branches included."""
    if isinstance(ops, dict):
        ops = [ops]
    for op in ops or ():
        if isinstance(op, str):
            continue
        if op.get("op") == "fx":
            found.add(op["name"])
        for branch in ("then", "else", "success"):
            if branch in op:
                collect_fx_names(op[branch], found)
    return found
