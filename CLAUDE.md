# CLAUDE.md

## Project

RestFinder — restaurant finder with foodie site mentions. Pre-fetches data, serves as a static site.

## Architecture

- `cities.json` — city definitions (center, zoom, bbox, foodie_sites)
- `fetch.py` — two modes:
  - Default: queries Overpass API, saves raw restaurant data to `.site/data/`
  - `foodie`: queries Exa.ai for each restaurant against foodie sites, augments data with `foodie_urls`
- `index.html` — static app, loads pre-fetched JSON, no runtime API calls
- `Makefile` — `make db` (fetch + foodie), `make site` (copy), `make dev` (watch + serve)
- `.github/workflows/deploy.yml` — monthly fetch + deploy to GitHub Pages

## Stack

- **Frontend**: Leaflet.js 1.9.4 (CDN), vanilla JS
- **Data**: Overpass API (OSM) for restaurants, Exa.ai for foodie URLs
- **Python deps**: requests, truststore, exa-py, python-dotenv (all pinned ==)
- **Serving**: static files from `.site/`

## Dev

```
# Set up API key
echo "EXA_API_KEY=your-key" > .env

make db    # fetch restaurants + foodie URLs
make dev   # copy to .site/ + serve on :8080 with watch mode
make clean # remove .site/
```

## Key decisions

- All deps pinned to exact versions (==x.y.z)
- Fetched data kept raw (tags as-is from Overpass); all formatting in browser JS
- `foodie_urls` at top level of restaurant object (not inside `tags`)
- Incremental foodie: skips restaurants already processed
- Exa.ai keyword search for cost ($~8/full run) and native domain filtering
- `truststore` for corporate proxy SSL
