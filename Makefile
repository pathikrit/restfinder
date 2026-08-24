.PHONY: fetch build dev test clean _migrate _export

PYTHON := PYTHONPATH=src uv run python

_migrate:
	PYTHONPATH=src uv run alembic upgrade head

fetch: _migrate
	$(PYTHON) -m restfinder.nyc

_export: _migrate
	$(PYTHON) -m restfinder.export

build: _export
	@mkdir -p .site
	cp -f cities.json index.html .site/
	@mkdir -p .site/assets
	cp -R assets/. .site/assets/

dev: _export
	$(PYTHON) -m restfinder.dev

test: _migrate
	PYTHONPATH=src uv run pytest

clean:
	rm -rf .site
