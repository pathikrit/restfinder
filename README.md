# Rick's Restaurant Finder

[![Test and deploy](https://github.com/pathikrit/restfinder/actions/workflows/deploy.yml/badge.svg)](https://github.com/pathikrit/restfinder/actions/workflows/deploy.yml)

A curated map of NYC restaurants recommended by Rick's List, Michelin, James
Beard, Atlas Obscura, Itsfound, and The Infatuation. NYC DOHMH is the canonical
restaurant source, Neon stores restaurants and their references, and GitHub
Pages serves a static export. The Python data pipeline lives in
`src/restfinder/`, migrations in `migrations/`, source snapshots in `data/`, and
the frontend in `index.html`.

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
| `make build` | Generate the static site |

## Importing social recommendations

Use the repository skill to review an Instagram or TikTok restaurant post:

```text
$import-ig https://www.instagram.com/p/example/
```

It checks whether the URL is already in Neon, extracts and matches the mentioned
venues, and asks for approval before importing anything.
