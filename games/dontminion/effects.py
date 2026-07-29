"""Merged card-effect registries.

Each effects_* module owns a disjoint set of cards and exports EFFECTS/STAGES
(see effects_core.py for the contract). This module is the single lookup point
the engine uses; a duplicate registration is a packaging bug and raises.
"""

from . import (effects_core, effects_base_a, effects_base_b,
               effects_intrigue_a, effects_intrigue_b)

_MODULES = (effects_core, effects_base_a, effects_base_b,
            effects_intrigue_a, effects_intrigue_b)

EFFECTS = {}
STAGES = {}

for _m in _MODULES:
    for _name, _fn in _m.EFFECTS.items():
        if _name in EFFECTS:
            raise RuntimeError(f"dontminion: duplicate EFFECTS entry {_name!r}")
        EFFECTS[_name] = _fn
    for _key, _fn in _m.STAGES.items():
        if _key in STAGES:
            raise RuntimeError(f"dontminion: duplicate STAGES entry {_key!r}")
        STAGES[_key] = _fn
