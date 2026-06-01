# CLAUDE.md

## Project

RestFinder — minimal restaurant finder for NYC. Single-page static app.

## Architecture

- `index.html` — the entire app (HTML + CSS + JS, all inline)
- No build tools, no package.json, no framework
- Map: Leaflet.js via CDN + OpenStreetMap tiles
- Data: Overpass API (OpenStreetMap) — free, no API key, CORS-enabled
- Must be served over HTTP (not file://) for CORS to work

## Dev

```
python3 -m http.server 8080
```

Then open http://localhost:8080/index.html

## Key decisions

- Overpass API chosen over Google/Foursquare/Yelp because it's free, needs no API key, and supports browser-side CORS
- Queries both OSM nodes and ways for restaurants (`amenity=restaurant`)
- Zoom guard at level 14 prevents overly large Overpass queries
