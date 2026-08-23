# Rag Tag — raw source data

Drop the BGA extraction dumps here. `tools/import_bga.py` reads this directory and
generates `games/rag_tag/fighters.py`; the dumps stay committed so that generation is
reproducible and a correction is a re-run rather than a re-transcription.

`../PLAN.md` §"Stage 0" has the extraction recipes. Expected files:

| File | Source | What it gives us |
|---|---|---|
| `tagteam_bundle.js` | the public BGA client bundle on `x.boardgamearena.net` | the static fighter/card tables and the effect-name vocabulary — **try this first, it needs no login** |
| `tagteam_gamedatas.json` | `gameui.gamedatas` in a logged-in table or replay | the full server-sent state, incl. each fighter's definition |
| `tagteam_replay_*.json` | a replay's notification stream | **parity fixtures** — every turn's revealed cards and resulting HP / power / track deltas, produced by the real implementation |

The replay dumps are the valuable ones: `tools/replay_bga.py` feeds them through our engine
and asserts we produce identical state transitions turn by turn. Grab two or three covering
different fighters — that is what turns "faithful" from an aspiration into a test, and it is
what will catch a wrong guess in the within-turn resolution order (`../PLAN.md` §"Resolution
order").

Nothing here is imported at runtime. Keep the generated `fighters.py` to mechanics —
numbers, op lists, track layouts — rather than verbatim card text or art.
