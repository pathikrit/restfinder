# Rick's Restaurant Finder

A curated NYC restaurant map. NYC DOHMH is the restaurant source of truth, Neon
Postgres stores current and historical observations, and checked-in manifests
attach recommendations such as “Rick's Favorites” or an Instagram post. The
public app remains a static GitHub Pages site backed by generated JSON.

## Setup

Requires Python 3.13.2 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked
cp .env.sample .env
# Set DATABASE_URL in .env to the Neon connection string.
make fetch
make dev
```

`python-dotenv` loads `.env` locally without overriding environment variables.
The `.env` file and generated `.site/` directory are gitignored.

## Commands

```bash
make migrate                          # apply schema migrations
make fetch                            # fetch and upsert the current NYC snapshot
make import FILE=imports/example.json # apply one reference manifest
make import-all                       # apply every imports/*.json manifest
make kmz-dry-run FILE="data/Rick's List.kmz" LIMIT=25 # parse without database writes
make export                           # write .site/data/nyc.json from Neon
make build                            # export data and assemble the static site
make dev                              # build and serve http://localhost:8080
make test                             # run unit and PostgreSQL integration tests
```

`make fetch` is safe to repeat. New CAMIS records are inserted; existing records
are refreshed while retaining `first_seen`, closure checks, and references.
Restaurants that disappear from DOHMH remain in the database with an older
`last_seen` value.

Restaurant `type` is nullable until classification is implemented and accepts
only: `Restaurant`, `Bars`, `Coffee Shops`, `Dessert`, `Fast Food`, or
`Hidden / Speakeasy`. The UI displays these as 🍝, 🍸, ☕, 🍰, 🍔, and 🤐;
unclassified restaurants use 🍴.

## Reference manifests

Imports are deliberately reviewed and explicit. Create a JSON file under
`imports/` that points at existing namespaced restaurant IDs:

```json
{
  "reference": "https://www.instagram.com/reel/example/",
  "added_at": "2026-08-24T00:00:00Z",
  "restaurant_ids": [
    "nyc_dohmh:50123456",
    "nyc_dohmh:50123457"
  ]
}
```

The importer rejects unknown IDs and applies an entire invocation in one
transaction. Re-running it updates the declared timestamp without duplicating
references.

## KMZ dry-run importer

The checked-in `data/Rick's List.kmz` can be inspected without opening a
database connection:

```bash
make kmz-dry-run FILE="data/Rick's List.kmz" LIMIT=25
```

The parser reads every KML placemark without extracting the archive. Its default
output contains restaurant candidates from the `Restaurants`, `Cocktail Bars`,
and `Cafes, Ice Cream and Bakeries` folders, along with counts for the skipped
non-food folders. `Restaurants` and `Cocktail Bars` receive type hints;
cafe/bakery entries remain unclassified because the source folder does not
distinguish coffee shops from desserts. The dry-run command never reads `.env`
or connects to Postgres.

## Static export

The frontend export contains restaurants that were seen in the latest complete
DOHMH snapshot, have at least one reference, are not chains or confirmed closed,
and have map coordinates. It is deterministically ordered by restaurant ID.

## GitHub Actions

Add the rotated Neon connection string as the repository secret `DATABASE_URL`.
Optionally add `NYC_OPEN_DATA_APP_TOKEN`. The workflow:

- tests every push and pull request against PostgreSQL;
- exports and deploys the current database on pushes to `main`;
- fetches DOHMH, replays manifests, exports, and deploys on the first day of each
  month or via manual dispatch.

Never commit a live database URL or password.
