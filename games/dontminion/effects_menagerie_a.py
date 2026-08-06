"""MENAGERIE, half A (phase 10) — the cards whose interest is their own play
ability, plus all 20 Events.

Written against **Kernel v10**, frozen in `games/dontminion/CLAUDE.md`. The
registries below are the module contract; `effects_menagerie.py` unions this
half with half B and `effects.py` merges that into the game.

Owned by this half (20 cards + 20 Events):
  Horse · Supplies · Camel Train · Goatherd · Scrap · Snowy Village ·
  Bounty Hunter · Cavalry · Groom · Hostelry · Displace · Hunting Lodge ·
  Kiln · Livery · Paddock · Sanctuary · Destrier · Fisherman · Wayfarer ·
  Animal Fair
  Events: Delay · Desperation · Gamble · Pursue · Ride · Toil · Enhance ·
  March · Transport · Banish · Bargain · Invest · Seize the Day · Commerce ·
  Demand · Stampede · Reap · Enclave · Alliance · Populate
"""

from . import engine as E

EFFECTS = {}
STAGES = {}
TRIGGERS = {}
COST_MODS = {}
DYN_COSTS = {}
COST_OVERRIDE = {}
BUY_PAY_ALT = {}
BUY_GATES = {}
MANUAL_TREASURES = set()
AUTOPLAY_LAST = set()
ATTACK_REACTIONS = {}
WATCHER_WHENS = {}
LANDSCAPE_FX = {}
LANDSCAPE_SCORING = {}
LANDSCAPE_SETUP = {}
