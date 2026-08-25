# Rick's Restaurant Finder

[![Test and deploy](https://github.com/pathikrit/restfinder/actions/workflows/deploy.yml/badge.svg)](https://github.com/pathikrit/restfinder/actions/workflows/deploy.yml)

A curated Google map of NYC restaurants recommended by Rick's List, Michelin,
James Beard, Atlas Obscura, Itsfound, and The Infatuation. NYC DOHMH is the
canonical restaurant source, Overture fills persistable missing details, Neon
stores the data, and Google supplies live place details when selected.

## Development

Requires Python 3.13.2 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked
cp .env.sample .env  # add Neon credentials and an OpenAI key for video imports
make dev             # serve http://localhost:8080; refresh after frontend edits
```

| Command | What it does |
| --- | --- |
| `make test` | Run the test suite |
| `make fetch` | Refresh the NYC DOHMH data |
| `make enrich` | Refresh Overture details and the Google ID backlog |
| `make duplicates` | Prepare the reviewed duplicate report |
| `make build` | Generate the static site |

## Importing social recommendations

Use the repository skill to review an Instagram or TikTok restaurant post:

```text
$import-ig https://www.instagram.com/p/example/
```

It checks whether the URL is already in Neon, extracts and matches the mentioned
venues, and asks for approval before importing anything.
