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
- The UI includes restaurants carrying at least one named-list or URL reference,
  excluding chains, confirmed closures, historical DOHMH rows, and records
  without coordinates.

## Environment

The project uses Python 3.13.2 and uv. Local configuration is loaded with
`python-dotenv` from the ignored `.env` file:

```dotenv
DATABASE_USER=<username>
DATABASE_PASSWORD=<password>
DATABASE_URL=postgresql://${DATABASE_USER}:${DATABASE_PASSWORD}@<host>/<database>?sslmode=require
NYC_OPEN_DATA_APP_TOKEN=
OPENAI_API_KEY=
GOOGLE_PLACES_SERVER_KEY=
GOOGLE_MAPS_BROWSER_KEY=
GOOGLE_MAP_ID=
GOOGLE_MAP_STYLE_ID=
GOOGLE_PLACES_MONTHLY_LIMIT=4500
OVERTURE_RELEASE=
RESTFINDER_VIDEO_MODEL=gpt-5.6-terra
RESTFINDER_TRANSCRIPTION_MODEL=gpt-transcribe
RESTFINDER_GEOCODER_URL=https://nominatim.openstreetmap.org/search
```

`DATABASE_URL` is required. `NYC_OPEN_DATA_APP_TOKEN` is optional and is sent as
the Socrata `X-App-Token` header when present. CI can provide a complete
`DATABASE_URL` directly. `OPENAI_API_KEY` is required only for social-video
analysis; the model and geocoder variables are optional overrides. Never commit
`.env`, live credentials, generated `.site/` output, or `.restfinder/` drafts
and geocoding cache.

`GOOGLE_PLACES_SERVER_KEY` is the secret batch-matching key. The browser key is
published in `.site/config.json` by design and must be restricted by HTTPS
referrer and API. `GOOGLE_MAP_ID` is required for production advanced markers.
The monthly Google request ceiling defaults to 4,500 across reruns. An optional
Overture release pins enrichment; otherwise the latest STAC release is used.
The dark and light label-filtering styles checked into `data/google-map-style.json`
and `data/google-map-style-light.json` must be published in Google Cloud and
associated with the matching modes of that map ID.
Each monthly Google pass considers only exportable restaurants, skips rows
already checked that month, processes never-checked rows first, and then uses
the remaining allowance for the least recently checked rows.

## Commands

| Command | Purpose |
| --- | --- |
| `make fetch` | Fetch and upsert the current DOHMH snapshot |
| `make enrich` | Refresh Overture data and fill the Google Place ID backlog |
| `make duplicates` | Write an ignored duplicate review draft |
| `make build` | Export data and assemble the static site |
| `make dev` | Export data and serve source frontend files on port 8080 |
| `make test` | Run unit and PostgreSQL integration tests |

The Makefile intentionally covers only recurring development and deployment.
One-time imports are run explicitly through their modules in `src/restfinder/`;
their source snapshots stay checked in under `data/` or `imports/` and are never
replayed automatically by CI.

## Place enrichment

`restaurant_enrichments` stores one provider result per restaurant. Overture
fields may be persisted and are used only when canonical fields are missing.
Google rows contain Place IDs and match metadata only; hours, price, and
open-now are rendered live with Places UI Kit and must never enter exports,
caches, logs, or drafts. `last_checked_at` is provider-specific.

Matching automatically accepts only a unique exact nearby name or a strong
address-confirmed fuzzy match. Ambiguous matches remain unresolved. Overture's
general `operating_status` never directly marks a restaurant closed.

Duplicate preparation writes `.restfinder/duplicate-review.json`. Each reviewed
pair is recorded as merge, keep-separate, or defer in a manifest under
`imports/merges/`; only explicit merge decisions create `restaurant_aliases`.
Aliases remain auditable, references are moved to their canonical restaurant,
and the exporter excludes alias rows.

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

## Social post imports

The repository-local `/import-ig` skill under `.agents/skills/import-ig/`
handles Instagram and TikTok restaurant recommendation posts, including videos
and image carousels. `src/restfinder/social_video.py` first attempts an
unauthenticated public download; if a platform blocks it, analyze user-supplied
media with its original `--source-url`. An ordered directory of image/video
files represents a carousel. Never extract browser cookies for this workflow.

Analysis transcribes audio, samples timestamped frames, extracts grounded venue
mentions with structured OpenAI output, and resolves them against Neon. Matching
prefers current DOHMH rows, then historical DOHMH rows, then existing external
fallbacks. Ambiguous canonical matches remain unresolved. Clearly identified
unmatched NYC venues may become `social_video` fallbacks only after their address
and coordinates have been reviewed. Public Nominatim use is cached, serialized,
and limited to one request per second. NYC Planning GeoSearch is the
authoritative address fallback, followed by bounded Photon search when both are
unavailable.

Drafts and the geocoding cache live under ignored `.restfinder/`. A selected
unresolved row blocks import. After explicit approval, the importer writes a
versioned manifest under `imports/videos/` and applies one database transaction:
fallback upserts, type upgrades using the existing specificity priority, and an
exact synchronization of references for that post URL. Repeated imports are
idempotent. The skill must never run the `import` command or pass `--import-db`
before the user approves the displayed one-post review. It must not commit or
push Git changes unless requested.

Before analysis, the skill checks the canonical post URL against
`restaurant_references.reference` in Neon. If the URL is already present, it
shows the existing rows and waits for explicit reimport confirmation before
downloading or using a model. Reimport confirmation does not replace the later
approval of the newly extracted review table.

## Legacy mentions

`data/legacy-nyc.json` snapshots the previously deployed site data from June 4,
2026. `src/restfinder/legacy.py` uses original CAMIS IDs first, then exact
normalized name plus coordinates against current DOHMH and Rick fallback rows.
Only unresolved records create `legacy_site` fallbacks. Each `foodie_urls` value
is stored verbatim as a reference URL. Any Atlas Obscura mention sets the
canonical restaurant type to `Hidden / Speakeasy`. The importer is transactional
and idempotent.

## KMZ list imports

`src/restfinder/kmz.py` accepts a list name and repeated folder-to-type mappings.
It discards places more than a nominal two-hour OSRM drive from Times Square and
coalesces same-name pins within 100 meters across folders. Source snapshots are
checked in under `data/`; invocations remain explicit one-time operations.

Every KMZ candidate must first attempt a canonical DOHMH match using normalized
or high-confidence similar name plus nearby coordinates; KMZ files generally
have no address field. Matching prefers DOHMH, then existing external fallback
rows. Only unresolved places create a source-namespaced fallback. Reruns are
idempotent and remove obsolete alias rows.

Checked-in mappings:

- `data/Rick's List.kmz`: Restaurants → `Restaurant`; Cocktail Bars → `Bars`;
  Cafes/Ice Cream/Bakeries → `Coffee Shops` or keyword-derived `Dessert`.
- `data/Megan's List.kmz`: Drinks → `Bars`; Snacks & Desserts → `Coffee Shops`
  or keyword-derived `Dessert`; Good Eats and Fancy Eats → `Restaurant`. All
  other Megan folders are skipped.
- `data/Zoo Booze Hidden.kmz`: Hidden, Sort of Hidden, and Not Sure →
  `Hidden / Speakeasy`; reference → `@zoo.booze's Hidden`.

The repository-local `/import-kmz` skill under `.agents/skills/import-kmz/`
documents the review and import workflow for future maps.

## Deployment

`.github/workflows/deploy.yml` tests pushes and pull requests against PostgreSQL.
Pushes to `main` export Neon and deploy GitHub Pages. The monthly schedule and
manual dispatch also refresh DOHMH before export. Checked-in one-time imports
are not replayed. Deploys require the `DATABASE_URL`,
`GOOGLE_PLACES_SERVER_KEY`, `GOOGLE_MAPS_BROWSER_KEY`, and `GOOGLE_MAP_ID`
GitHub Actions secrets. The workflow fails at preflight when any required value
is absent. `NYC_OPEN_DATA_APP_TOKEN` is optional.
