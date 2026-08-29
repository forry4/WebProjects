# BGG Filter — Claude Context

A **frontend-only** feature: a filterable table of BoardGameGeek's ranked games, reached from
the home menu next to Spender Puzzles and Books. No backend, no room server, no auth — it
fetches one static JSON and does everything client-side.

| File | What it is |
|---|---|
| `BggFilter.jsx` | the whole feature; props are just `{ onExit }` |
| `BggFilter.css` | `?inline`-imported stylesheet, `.bgf`-prefixed |
| `tools/scan_bgg.py` | **the harvester** — hits BGG, writes `results_all.json` |
| `tools/make_data.py` | `results_all.json` → `webapp/public/data/bgg-filter.json` (the shipped payload) |

## The data is GENERATED — do not hand-edit the JSON

`webapp/public/data/bgg-filter.json` (6,920 games, ~1MB / ~300KB gzipped) is a build artifact.
Regenerate with `python bggfilter/tools/scan_bgg.py && python bggfilter/tools/make_data.py`.
The intermediate `results_all.json` is **not** committed; only the trimmed payload is.

**It is fetched, not imported.** At ~1MB, bundling it would put the whole dataset in the lazy
chunk for everyone who opens the page. The chunk is ~18KB and the data arrives separately,
CDN-cached like any other asset in `webapp/public/`.

## Harvesting lessons (paid for once — do not relearn)

- **BGG's XML API is closed.** It returns 401 and needs a registered application (a week+ of
  approval). Everything here uses the endpoints the BGG *website* calls: the advanced search
  page, `geekitempoll.php?action=view` (to find a game's poll id), `geekpoll.php?action=results`
  (the vote matrix), and `api.geekdo.com/api/dynamicinfo` (exact weight + rating stats).
- **BGG 403s Python's TLS fingerprint**, so every request shells out to `curl`.
- **The advanced search hard-caps at 50 pages (5,000 rows)** whatever the filter, so the
  universe is enumerated in **weight bands** and de-duplicated by id.
- **Cloudflare answers a burst with a 200-OK "Just a moment..." challenge page.** The first run
  cached those as if they were data and three whole weight bands came back "empty" — every game
  over 3.5 weight vanished with nothing to indicate it. `reject()` in `scan_bgg.py` validates
  every response *before* it is cached (challenge signatures, HTML where JSON was expected,
  implausibly short pages) and retries with escalating backoff. **Never cache an unvalidated
  response.**
- **Unranked entries are dropped.** BGG excludes alternate editions and big boxes from its
  ranking, so their Geek ratings are not comparable and they duplicate games already listed.

## Reading the percentages

The poll lets each voter mark every player count Best / Recommended / Not Recommended
**independently**, so the shares across counts do not sum to 100%. Per count the UI shows
`best% / (best+recommended)%`, both over the voters who expressed an opinion about *that*
count — the same denominator BGG displays. A count with no votes reads `-1` internally so it
fails every threshold above zero while still rendering as "no votes".

**A 60% bar means different things at different counts**: votes at three and four spread across
neighbouring counts, so Best-at-4 ≥60% is a far harsher filter than Best-at-2 ≥60% (17 games vs
792). Poll size matters too — 100% off 40 voters is not 97% off 1,500 — so polls under 100 votes
are flagged amber.

## Wiring (the five places a new screen must be registered)

`shared/router.js` `MODES` · `shared/HomeScreen.jsx` (the `onBggFilter` button) ·
`games/spender/Spender.jsx` (**three** spots: the `lazyChunk`, the `screen === "bggfilter"`
branch, **and both `SCREEN_FOR_MODE` / `MODE_FOR_SCREEN`** — missing the maps compiles, renders
a working home button, and then the route simply never mounts) · `webapp/test/screens.mjs`
`SCREENS` · and **both deploy path filters** (`.github/workflows/deploy-pages.yml` and
`.githooks/pre-push`) — a top-level directory absent from those never triggers a deploy.
