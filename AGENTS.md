# Repository Notes for Coding Agents

Keep `README.md` concise and human-facing. Put implementation details and
operational notes in this file instead.

## Architecture

- NYC DOHMH (`43nn-pn8j`) is the canonical restaurant source.
- Neon Postgres is the source of truth. Alembic migrations live in
  `migrations/versions/`.
- `restaurants` stores canonical DOHMH rows and fallback rows for external
  places that cannot be matched.
- `restaurant_references.restaurant_id` foreign-keys into `restaurants.id`.
  Each recommendation URL or list name is a separate reference.
- The frontend is the static `index.html`; `src/restfinder/export.py` writes
  `.site/data/nyc.json`.
- Map category glyphs are official CC0 Maki SVGs under `assets/maki/`; do not
  replace them with emoji or hand-authored pictograms.
- The UI includes restaurants referenced by Rick's List or by one or more
  legacy mention URLs, excluding chains, confirmed closures, historical DOHMH
  rows, and records without coordinates.

## Environment

The project uses Python 3.13.2 and uv. Local configuration is loaded with
`python-dotenv` from the ignored `.env` file:

```dotenv
DATABASE_USER=<username>
DATABASE_PASSWORD=<password>
DATABASE_URL=postgresql://${DATABASE_USER}:${DATABASE_PASSWORD}@<host>/<database>?sslmode=require
NYC_OPEN_DATA_APP_TOKEN=
```

`DATABASE_URL` is required. `NYC_OPEN_DATA_APP_TOKEN` is optional and is sent as
the Socrata `X-App-Token` header when present. CI can provide a complete
`DATABASE_URL` directly. Never commit `.env`, live credentials, or generated
`.site/` output.

## Commands

| Command | Purpose |
| --- | --- |
| `make fetch` | Fetch and upsert the current DOHMH snapshot |
| `make build` | Export data and assemble the static site |
| `make dev` | Export data and serve source frontend files on port 8080 |
| `make test` | Run unit and PostgreSQL integration tests |

The Makefile intentionally covers only recurring development and deployment.
One-time imports are run explicitly through their modules in `src/restfinder/`;
their source snapshots stay checked in under `data/` or `imports/` and are never
replayed automatically by CI.

## DOHMH ingestion

`src/restfinder/nyc.py` fetches the NYC Open Data API with keyset pagination and
groups inspection rows by CAMIS. IDs are stable and namespaced as
`nyc_dohmh:<CAMIS>`. Repeated fetches preserve `first_seen`, closure metadata,
types, and references while updating current fields and `last_seen`. Missing
restaurants remain historical; the exporter includes only the latest complete
DOHMH snapshot.

The current chain heuristic marks normalized names with more than five
locations as chains. Supported types are `Restaurant`, `Bars`, `Coffee Shops`,
`Dessert`, `Fast Food`, and `Hidden / Speakeasy`.

Shouty uppercase source names are converted to readable title casing by
`restfinder.names.display_name`; already-styled mixed/lowercase names are kept.
Chain detection and importer matching use case-insensitive normalized keys, so
display casing never determines restaurant identity.

## Reference manifests

Checked-in manifests under `imports/` use this shape:

```json
{
  "reference": "https://www.instagram.com/reel/example/",
  "added_at": "2026-08-24T00:00:00Z",
  "restaurant_ids": ["nyc_dohmh:50123456"]
}
```

The importer rejects unknown IDs, applies an invocation transactionally, and is
idempotent.

## Legacy mentions

`data/legacy-nyc.json` snapshots the previously deployed site data from June 4,
2026. `src/restfinder/legacy.py` uses original CAMIS IDs first, then exact
normalized name plus coordinates against current DOHMH and Rick fallback rows.
Only unresolved records create `legacy_site` fallbacks. Each `foodie_urls` value
is stored verbatim as a reference URL. Any Atlas Obscura mention sets the
canonical restaurant type to `Hidden / Speakeasy`. The importer is transactional
and idempotent.

## Rick's List KMZ

`data/Rick's List.kmz` is the checked-in source. The importer only accepts the
Restaurants, Cocktail Bars, and Cafes/Ice Cream/Bakeries folders, and discards
places more than a nominal two-hour OSRM drive from Times Square. Same-name pins
within 100 meters are coalesced across folders.

Every KMZ candidate must first attempt a canonical DOHMH match using normalized
name and nearby coordinates; the KMZ has no address field. Confident matches add
a `Rick's List` reference to the DOHMH row. Only unmatched or ambiguous places
create Rick fallback rows. Reruns are idempotent and remove obsolete alias rows.

Folder types map as follows:

- Restaurants → `Restaurant`
- Cocktail Bars → `Bars`
- Cafe/ice cream/bakery entries → `Coffee Shops` or `Dessert` using name keywords

## Deployment

`.github/workflows/deploy.yml` tests pushes and pull requests against PostgreSQL.
Pushes to `main` export Neon and deploy GitHub Pages. The monthly schedule and
manual dispatch also refresh DOHMH before export. Checked-in one-time imports
are not replayed. `DATABASE_URL` is the required repository secret;
`NYC_OPEN_DATA_APP_TOKEN` is optional.
