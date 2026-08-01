"""Merged card-effect registries.

ONE effects_* module per expansion, each owning a disjoint set of cards and
exporting EFFECTS/STAGES (contract: games/dontminion/CLAUDE.md). This module is
the single lookup point the engine uses; a duplicate registration across
modules is a packaging bug and raises at import.
"""

from . import (effects_base, effects_intrigue, effects_seaside, effects_prosperity,
               effects_hinterlands, effects_cornucopia)

_MODULES = (effects_base, effects_intrigue, effects_seaside, effects_prosperity,
            effects_hinterlands, effects_cornucopia)

EFFECTS = {}
STAGES = {}
# The trigger-bus registries (see engine.py "THE TRIGGER BUS" for the spec
# shapes): TRIGGERS = {card: [{"on": event, "from": source, ...}, ...]};
# COST_MODS = {card: fn(game, priced_name) -> reduction per in-play copy}.
TRIGGERS = {}
COST_MODS = {}
DYN_COSTS = {}          # card -> fn(game) -> reduction on the card's OWN cost (Peddler)
BUY_GATES = {}          # card -> fn(game, pid) -> error string | None (Grand Market)
MANUAL_TREASURES = set()  # treasures play_all must skip (interactive: Anvil-class)
# Treasures whose VALUE depends on what else is already in play, so play_all
# must play them AFTER the rest (Bank). Membership means "later is never
# worse" — a card where the player might genuinely want it early belongs in
# MANUAL_TREASURES instead, since the button must not choose for them.
AUTOPLAY_LAST = set()
# card -> reaction spec for the attack window (see engine.attack_reactions)
ATTACK_REACTIONS = {}
# (card, stage) -> fn(game, watcher, ctx) -> bool: does this WATCHER actually
# fire for this occurrence? Evaluated by emit() at JOIN time (p25 §3 — triggers
# are based on the actual occurrence), so a watcher whose ability would no-op
# (Monkey on anyone but the right-hand neighbour, a spent Sailor) never enters
# the ability pool and never pollutes the what-resolves-first prompt. The stage
# keeps its own guard as the resolve-time re-check.
WATCHER_WHENS = {}

for _m in _MODULES:
    for _name, _fn in _m.EFFECTS.items():
        if _name in EFFECTS:
            raise RuntimeError(f"dontminion: duplicate EFFECTS entry {_name!r}")
        EFFECTS[_name] = _fn
    for _key, _fn in _m.STAGES.items():
        if _key in STAGES:
            raise RuntimeError(f"dontminion: duplicate STAGES entry {_key!r}")
        STAGES[_key] = _fn
    for _name, _specs in getattr(_m, "TRIGGERS", {}).items():
        if _name in TRIGGERS:
            raise RuntimeError(f"dontminion: duplicate TRIGGERS entry {_name!r}")
        TRIGGERS[_name] = _specs
    for _name, _fn in getattr(_m, "COST_MODS", {}).items():
        if _name in COST_MODS:
            raise RuntimeError(f"dontminion: duplicate COST_MODS entry {_name!r}")
        COST_MODS[_name] = _fn
    for _name, _fn in getattr(_m, "DYN_COSTS", {}).items():
        if _name in DYN_COSTS:
            raise RuntimeError(f"dontminion: duplicate DYN_COSTS entry {_name!r}")
        DYN_COSTS[_name] = _fn
    for _name, _fn in getattr(_m, "BUY_GATES", {}).items():
        if _name in BUY_GATES:
            raise RuntimeError(f"dontminion: duplicate BUY_GATES entry {_name!r}")
        BUY_GATES[_name] = _fn
    for _name in getattr(_m, "MANUAL_TREASURES", ()):
        MANUAL_TREASURES.add(_name)
    for _name in getattr(_m, "AUTOPLAY_LAST", ()):
        AUTOPLAY_LAST.add(_name)
    for _name, _spec in getattr(_m, "ATTACK_REACTIONS", {}).items():
        if _name in ATTACK_REACTIONS:
            raise RuntimeError(f"dontminion: duplicate ATTACK_REACTIONS entry {_name!r}")
        ATTACK_REACTIONS[_name] = _spec
    for _key, _fn in getattr(_m, "WATCHER_WHENS", {}).items():
        if _key in WATCHER_WHENS:
            raise RuntimeError(f"dontminion: duplicate WATCHER_WHENS entry {_key!r}")
        WATCHER_WHENS[_key] = _fn
