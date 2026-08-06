"""MENAGERIE, half B (phase 10) — the mechanically complex half: all 20 WAYS
(a landscape kind the game has never dealt), the Reactions that play
themselves, the Attacks, the Durations and the two Treasures.

Written against **Kernel v10**, frozen in `games/dontminion/CLAUDE.md`. The
registries below are the module contract; `effects_menagerie.py` unions this
half with half A and `effects.py` merges that into the game.

Owned by this half (11 cards + 20 Ways):
  Black Cat · Sleigh · Sheepdog · Falconer · Village Green · Barge · Coven ·
  Cardinal · Gatekeeper · Mastermind · Stockpile
  Ways: Butterfly · Camel · Chameleon · Frog · Goat · Horse · Mole · Monkey ·
  Mouse · Mule · Otter · Ox · Owl · Pig · Rat · Seal · Sheep · Squirrel ·
  Turtle · Worm
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
