"""Renaissance, half A — the SIMPLE half (batch agent A owns this file).

Concatenated into `effects_renaissance.py` when the phase lands (registry
UNION, not last-assignment-wins). See games/dontminion/CLAUDE.md for the
frozen engine API and "Kernel v9" for this phase's delta.
"""

from . import engine as E

EFFECTS = {}
STAGES = {}
TRIGGERS = {}
WATCHER_WHENS = {}
MANUAL_TREASURES = set()
LANDSCAPE_FX = {}
