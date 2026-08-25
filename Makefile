.PHONY: fetch enrich build dev test clean _migrate _export duplicates

PYTHON := PYTHONPATH=src uv run python

_migrate:
	PYTHONPATH=src uv run alembic upgrade head

fetch: _migrate
	$(PYTHON) -m restfinder.nyc

enrich: _migrate
	$(PYTHON) -m restfinder.enrichment overture
	$(PYTHON) -m restfinder.enrichment google --scope exportable

duplicates: _migrate
	$(PYTHON) -m restfinder.duplicates prepare

_export: _migrate
	$(PYTHON) -m restfinder.export
	$(PYTHON) -m restfinder.site_metadata

build: _export
	@mkdir -p .site
	cp -f cities.json index.html manifest.webmanifest service-worker.js privacy.html terms.html NOTICE .site/
	@mkdir -p .site/assets
	cp -R assets/. .site/assets/

dev: _export
	$(PYTHON) -m restfinder.dev

test: _migrate
	PYTHONPATH=src uv run pytest

clean:
	rm -rf .site
