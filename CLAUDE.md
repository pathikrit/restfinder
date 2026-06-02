# CLAUDE.md

## What is this

RestFinder — a static restaurant finder app. Shows restaurants on a map with data from OpenStreetMap, augmented with mentions from foodie review sites via Google Custom Search. Deployed to GitHub Pages at pathikrit.github.io/restfinder.

## File layout

```
cities.json       — city definitions: center, zoom, bbox (for Overpass), foodie_sites (for Google CSE)
fetch.py          — two modes:
                      `uv run fetch.py`        → fetch restaurants from Overpass API
                      `uv run fetch.py foodie`  → augment with foodie URLs from Google Custom Search
index.html        — the entire frontend (inline CSS + JS), no build step
Makefile          — make db-copy / make db-smoketest / make db / make site / make dev / make clean
pyproject.toml    — uv project, all deps pinned ==x.y.z, Python pinned ===x.y.z
.env              — GOOGLE_API_KEY + GOOGLE_CSE_ID (gitignored)
.site/            — build output dir (gitignored), served by make dev / GitHub Pages
.site/data/*.json — pre-fetched restaurant data per city
.github/workflows/deploy.yml — manual fetch + deploy to GitHub Pages
```

## How to run

```bash
make db-copy                           # download pre-built data from GitHub Pages
make dev                               # serve on :8080 with file watching
```

To rebuild data from scratch (requires Google API credentials):
```bash
printf "GOOGLE_API_KEY=your-key\nGOOGLE_CSE_ID=your-cx" > .env  # one-time setup
make db-smoketest                      # quick: 2 cities, 100 restaurants each
make db                                # full: all cities, all restaurants (~15min)
```

## Makefile targets

- `make db-copy` — downloads pre-built restaurant data from GitHub Pages. No API keys needed — fastest way to get started.
- `make db-smoketest` — fetches first 2 cities, 100 restaurants each, with foodie lookup. Quick local dev sanity check.
- `make db` — full Overpass fetch + Google Custom Search foodie lookup for all cities. Fails if `.env` missing `GOOGLE_API_KEY`/`GOOGLE_CSE_ID`.
- `make site` — copies `cities.json` + `index.html` into `.site/`. Used by GitHub Actions.
- `make dev` — depends on `site`. Watches `index.html`/`cities.json` for changes (via `fswatch`) and auto-copies. Serves `.site/` on port 8080.
- `make clean` — removes `.site/`.

## Data flow

1. `fetch.py` queries Overpass API with each city's `bbox` → raw restaurant data with full OSM `tags`
2. `fetch.py foodie` reads the saved JSON, queries Google Custom Search for each named restaurant against the city's `foodie_sites`, adds `foodie_urls` to each restaurant object
3. `make site` copies static assets into `.site/`
4. `index.html` loads `cities.json` (for tabs) and `data/{key}.json` (for restaurants) — zero API calls at runtime

## Data format in .site/data/{city}.json

```json
[
  {
    "id": 123456,
    "lat": 40.76,
    "lon": -73.98,
    "tags": { "name": "...", "cuisine": "...", "addr:street": "...", ... },
    "foodie_urls": ["https://ny.eater.com/..."]
  }
]
```

- `tags` is raw from Overpass (OSM tags, unmodified)
- `foodie_urls` is at the top level (not inside `tags`), added by the foodie step
- `foodie_urls` key absent = not yet checked. `[]` = checked, no results. `null` = error, retry next run.

## Key conventions

- **Pinned versions**: **zero tolerance for unpinned versions.** All Python deps use `==x.y.z`, Python itself uses `===x.y.z` in `requires-python`, and JS CDN libs are pinned to exact versions in the URL. No `>=`, `^`, `~`, `latest`, or unversioned references anywhere.
- **Raw data**: `fetch.py` stores data as close to the API response as possible. All formatting (address assembly, cuisine semicolons→commas, etc.) happens in `index.html` JavaScript.
- **Incremental foodie**: `fetch.py foodie` skips restaurants that already have a `foodie_urls` key, so re-runs only process new restaurants.
- **SSL**: `truststore` is used to handle corporate proxy SSL interception.
- **Google CSE**: Create a Programmable Search Engine at https://programmablesearchengine.google.com/ configured to search the whole web. Site restriction is done per-query via `site:` operators using each city's `foodie_sites`. Free tier: 100 queries/day; paid: $5 per 1000 queries.
- **No framework**: single HTML file with inline CSS/JS, Leaflet via CDN. No build tools, no npm.

## Frontend architecture (index.html)

- City tabs dynamically built from `cities.json`
- On city select: loads `data/{key}.json`, caches in memory
- On pan/zoom (`moveend`): filters cached data to visible map bounds, re-renders markers + table
- `t(r, key)` helper reads from `r.tags[key]` (raw format) or `r[key]` (legacy flat format)
- "Foodie" pill toggle: when active, filters to `r.foodie_urls.length > 0`
- `<meta name="last-updated">` populated by GitHub Actions at build time via `sed`

## GitHub Actions

- Runs on manual dispatch only
- `GOOGLE_API_KEY` and `GOOGLE_CSE_ID` passed via env (from repo secrets)
- Runs `make db` → `make site`
- Injects last-updated date into `index.html`
- Deploys `.site/` to GitHub Pages

## Adding a new city

1. Add entry to `cities.json` with `key`, `name`, `lat`, `lng`, `zoom`, `bbox`, `foodie_sites`
2. Run `make db` — it fetches restaurants and foodie URLs for all cities
3. The frontend picks it up automatically (tabs built from `cities.json`)
