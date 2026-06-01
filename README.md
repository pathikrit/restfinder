# RestFinder

Find restaurants on a map. Pick a city, zoom in, click "Search Here".

## How it works

Data is pre-fetched from [OpenStreetMap](https://www.openstreetmap.org/) via the Overpass API. The frontend is a static page that loads the pre-fetched JSON — no runtime API calls.

## Setup

```
make fetch   # download restaurant data (~30s)
make dev     # serve on http://localhost:8080
```

## Deploy

Deployed nightly to GitHub Pages via Actions. See `.github/workflows/deploy.yml`.

## Cities

NYC, Miami, SF, LA, Chicago. Add more in `cities.json`.
