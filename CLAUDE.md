# CLAUDE.md

## What is this

RestFinder — a static restaurant finder app. Shows restaurants on a map with data from city open-data APIs (NYC DOHMH via Socrata), augmented with mentions from foodie review sites via Serper.dev (Google Search). Deployed to GitHub Pages at pathikrit.github.io/restfinder.

## File layout

```
cities.json       — city definitions: center, zoom, bbox, foodie_sites, enabled flag
fetcher.py        — fetch restaurant data from city APIs (NYC uses Socrata DOHMH)
foodie.py         — augment with foodie URLs from Serper.dev (batched Google Search)
index.html        — the entire frontend (inline CSS + JS), no build step
Makefile          — make db-copy / make db-smoketest / make db / make site / make dev / make clean
pyproject.toml    — uv project, all deps pinned ==x.y.z, Python pinned ===x.y.z
.env.sample       — template for .env (checked in)
.env              — SERPER_API_KEY (gitignored)
.site/            — build output dir (gitignored), served by make dev / GitHub Pages
.site/data/*.json — pre-fetched restaurant data per city
.github/workflows/deploy.yml — manual fetch + deploy to GitHub Pages
```

## How to run

```bash
make db-copy                           # download pre-built data from GitHub Pages
make dev                               # serve on :8080 with file watching
```

To rebuild data from scratch (requires Serper API key for foodie step):
```bash
cp .env.sample .env                    # one-time setup, then fill in key
make db-smoketest                      # quick: 100 restaurants, with foodie lookup
make db                                # full: all enabled cities, all restaurants
```

## Makefile targets

- `make db-copy` — downloads pre-built restaurant data from GitHub Pages. No API keys needed — fastest way to get started.
- `make db-smoketest` — fetches 100 restaurants with foodie lookup. Quick local dev sanity check.
- `make db` — full fetch + Serper foodie lookup for all enabled cities. Fails if `.env` missing `SERPER_API_KEY`.
- `make site` — copies `cities.json` + `index.html` into `.site/`. Used by GitHub Actions.
- `make dev` — depends on `site`. Watches `index.html`/`cities.json` for changes (via `fswatch`) and auto-copies. Serves `.site/` on port 8080.
- `make clean` — removes `.site/`.

## Data flow

1. `fetcher.py` queries city open-data APIs (NYC: Socrata DOHMH, GROUP BY camis) → deduplicated restaurant data
2. `foodie.py` reads the saved JSON, queries Serper.dev in batches of 100 for each named restaurant against the city's `foodie_sites`, adds `foodie_urls`
3. `make site` copies static assets into `.site/`
4. `index.html` loads `cities.json` (for tabs) and `data/{key}.json` (for restaurants) — zero API calls at runtime

## Data format in .site/data/{city}.json

```json
[
  {
    "id": "50076500",
    "name": "Atomix",
    "cuisine": "Korean",
    "address": "104 East 30 Street, Manhattan, 10016",
    "lat": 40.7444,
    "lon": -73.9827,
    "phone": "6466968901",
    "foodie_urls": ["https://ny.eater.com/..."]
  }
]
```

- `foodie_urls` key absent = not yet checked. `[]` = checked, no results. `null` = error, retry next run.

## Key conventions

- **Pinned versions**: **zero tolerance for unpinned versions.** All Python deps use `==x.y.z`, Python itself uses `===x.y.z` in `requires-python`, and JS CDN libs are pinned to exact versions in the URL. No `>=`, `^`, `~`, `latest`, or unversioned references anywhere.
- **Incremental foodie**: `foodie.py` skips restaurants that already have a `foodie_urls` key, so re-runs only process new restaurants.
- **SSL**: `truststore` is used to handle corporate proxy SSL interception.
- **Serper.dev**: Batched Google Search API — up to 100 queries per request. Uses `site:` operator to restrict to foodie sites.
- **No framework**: single HTML file with inline CSS/JS, Leaflet via CDN. No build tools, no npm.

## Frontend architecture (index.html)

- City tabs dynamically built from `cities.json`; disabled cities show as greyed-out "Coming soon"
- On city select: loads `data/{key}.json`, caches in memory
- On pan/zoom (`moveend`): filters cached data to visible map bounds, re-renders markers + table
- Foodie site checkboxes: when active, filters to restaurants with matching `foodie_urls`
- `<meta name="last-updated">` populated by GitHub Actions at build time via `sed`

## GitHub Actions

- Runs on push (UI-only deploy via `db-copy`) and manual dispatch (full data rebuild)
- `SERPER_API_KEY` passed via env (from repo secret) for manual dispatch
- Runs `make db` → `make site`
- Injects last-updated date into `index.html`
- Deploys `.site/` to GitHub Pages

## Adding a new city

1. Add entry to `cities.json` with `key`, `name`, `enabled`, `lat`, `lng`, `zoom`, `bbox`, `foodie_sites`
2. Implement a fetcher function in `fetcher.py` for the city's data source
3. Run `make db` — it fetches restaurants and foodie URLs for all enabled cities
4. The frontend picks it up automatically (tabs built from `cities.json`)
