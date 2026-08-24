.PHONY: migrate fetch import import-all export site build dev test clean

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

export: migrate
	$(PYTHON) -m restfinder.export

site:
	@mkdir -p .site
	cp -f cities.json index.html .site/

build: export site

dev: build
	python3 -m http.server 8080 -d .site

test:
	PYTHONPATH=src uv run pytest

clean:
	rm -rf .site
