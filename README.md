# RestFinder

Find restaurants on a map. Zoom in, click "Search Here", see restaurants.

## How it works

- Single HTML file — no build tools, no framework, no backend
- [Leaflet.js](https://leafletjs.com/) + OpenStreetMap tiles for the map
- [Overpass API](https://overpass-api.de/) for restaurant data (free, no API key)
- Scoped to NYC for now

## Run locally

```
python3 -m http.server 8080
open http://localhost:8080/index.html
```

Must be served via HTTP (not `file://`) due to CORS.
