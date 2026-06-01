# CLAUDE.md

## Project

RestFinder — minimal restaurant finder. Pre-fetches data from OpenStreetMap, serves as a static site.

## Architecture

- `cities.json` — city definitions (name, center, zoom, bbox for Overpass query)
- `fetch.py` — Python script that queries Overpass API for each city, saves processed JSON to `.site/data/`
- `index.html` — static app that loads pre-fetched JSON, no runtime API calls
- `Makefile` — `make fetch` to download data, `make dev` to serve locally
- `.github/workflows/deploy.yml` — nightly fetch + deploy to GitHub Pages

## Stack

- **Frontend**: Leaflet.js 1.9.4 (CDN) + OpenStreetMap tiles, vanilla JS
- **Data**: Overpass API (OpenStreetMap), fetched offline by `fetch.py`
- **Python deps**: `requests`, `truststore` (for corporate proxy SSL)
- **Serving**: static files from `.site/` directory

## Dev

```
make fetch   # download restaurant data for all cities
make dev     # copy files to .site/ and serve on :8080
make clean   # remove .site/
```

## Key decisions

- No runtime API calls — data is pre-fetched and served as static JSON
- `truststore` used to handle corporate proxy SSL interception
- "Search Here" filters pre-loaded data to visible map bounds (instant, no network)
- `.site/` is gitignored; built fresh by fetch + copy
