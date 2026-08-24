.PHONY: migrate fetch import import-all legacy-import kmz-dry-run kmz-import export site build dev test clean

PYTHON := PYTHONPATH=src uv run python

migrate:
	PYTHONPATH=src uv run alembic upgrade head

fetch: migrate
	$(PYTHON) -m restfinder.nyc

import: migrate
	@test -n "$(FILE)" || { echo "Usage: make import FILE=imports/example.json"; exit 1; }
	$(PYTHON) -m restfinder.references "$(FILE)"

import-all: migrate
	$(PYTHON) -m restfinder.references
	$(PYTHON) -m restfinder.legacy data/legacy-nyc.json

legacy-import: migrate
	$(PYTHON) -m restfinder.legacy data/legacy-nyc.json

kmz-dry-run:
	@test -n "$(FILE)" || { echo "Usage: make kmz-dry-run FILE=\"data/Rick's List.kmz\" [LIMIT=25]"; exit 1; }
	$(PYTHON) -m restfinder.kmz "$(FILE)" $(if $(LIMIT),--limit $(LIMIT),)

kmz-import: migrate
	@test -n "$(FILE)" || { echo "Usage: make kmz-import FILE=\"data/Rick's List.kmz\""; exit 1; }
	$(PYTHON) -m restfinder.kmz "$(FILE)" --import-db

export: migrate
	$(PYTHON) -m restfinder.export

site:
	@mkdir -p .site
	cp -f cities.json index.html .site/

build: export site

dev: export
	$(PYTHON) -m restfinder.dev

test:
	PYTHONPATH=src uv run pytest

clean:
	rm -rf .site
