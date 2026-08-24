# Rag Tag — source data

`tools/import_bga.py` reads this directory and generates `games/rag_tag/fighters.py`.
Nothing here is imported at runtime.

## Where it came from

`PLAN.md` assumed this data could only be got out of a logged-in BoardGameArena table,
via a devtools console dump. **It can't only be got that way, and that route is no longer
the gating dependency.** Everything the engine needs is served publicly, without a login:

| Source | Gives us |
|---|---|
| [the rulebook PDF](https://gamers-hq.de/media/pdf/81/2d/2c/TT_Rules_01_EN_06may2025.pdf) | the full 16-page fight rules — round structure, action glossary, health-track and STOP semantics, KO / draw / depleted-Build-Deck |
| [BGA's Gamehelp page](https://en.doc.boardgamearena.com/Gamehelptagteam) | the same rules again *plus* the per-fighter section for all 12, with the FAQ that settles most of the awkward interactions |
| `x.boardgamearena.net/.../tagteam/current/tagteam.css` | the asset manifest — which is how the card and board art was found |
| `.../img/fighters/*.jpg`, `.../img/cards/*/*.jpg` | 12 fighter boards (+2 backs) and 78 card faces, each legible enough to transcribe |
| `.../tagteam/current/tagteam.js` | the client bundle. UI only — it carries **no** card tables — but its i18n strings name the special tracks and list Milady's 11 Intrigue effects verbatim |

`sources.json` lists every asset URL. `tools/fetch_bga_assets.py` re-downloads them, so a
correction can be checked against the same pixels the transcription was made from.

**The art itself is not committed** — it is the publisher's, and a mechanical table is the
better engineering anyway. Rules aren't copyrightable; card text and art are. What is
committed is the transcription: numbers, op lists, track layouts.

## Files

| File | Contents |
|---|---|
| `sources.json` | every source URL, per fighter |
| `boards.json` | the 12 fighter boards: base Power, health track (ordered, with icons and stops), special tracks, token supplies |
| `cards.json` | the 78 card faces: name, fighter, frequency, starting-card flag, op list |

## Still missing: the parity fixtures

`PLAN.md` §Verification wants `tools/replay_bga.py` to feed a captured BGA game through our
engine and assert identical state transitions turn by turn. That capture is the **one** part
that still needs a logged-in browser, because a replay's notification stream only exists
inside an authenticated session:

```js
(() => {
  const log = [];
  (dojo || gameui.dojo).subscribe('*', null, (n) => log.push(n));
  console.log('capturing — play the replay to the end, then run __rtdump()');
  window.__rtdump = () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(log, null, 1)], {type: 'application/json'}));
    a.download = 'tagteam_replay.json'; a.click();
  };
})()
```

Drop the results in here as `tagteam_replay_*.json` and they become fixtures. Two or three
covering different fighters is enough. Without them the resolution order is pinned by the
rulebook and the Gamehelp FAQ rather than by a test against the real implementation — good,
but not the same thing.

The other console dump worth grabbing while logged in is `gameui.gamedatas`, which carries
each fighter's server-side definition and would let `import_bga.py` cross-check the
transcription mechanically instead of by eye.
