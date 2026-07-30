"""Merged card-effect registries.

Each effects_* module owns a disjoint set of cards and exports EFFECTS/STAGES
(see effects_core.py for the contract). This module is the single lookup point
the engine uses; a duplicate registration is a packaging bug and raises.
"""

from . import (effects_core, effects_base_a, effects_base_b,
               effects_intrigue_a, effects_intrigue_b,
               effects_seaside_a, effects_seaside_b,
               effects_prosperity_a, effects_prosperity_b)

_MODULES = (effects_core, effects_base_a, effects_base_b,
            effects_intrigue_a, effects_intrigue_b,
            effects_seaside_a, effects_seaside_b,
            effects_prosperity_a, effects_prosperity_b)

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
