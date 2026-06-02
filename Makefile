.PHONY: check-keys db db-copy db-smoketest site dev clean

check-keys:
	@test -n "$$EXA_API_KEY" || (test -f .env && grep -q EXA_API_KEY .env) || { echo "Error: set EXA_API_KEY in env or .env"; exit 1; }

PAGES_URL := https://pathikrit.github.io/restfinder

db-copy:
	@mkdir -p .site/data
	@unset SSL_CERT_FILE REQUESTS_CA_BUNDLE; \
	python3 -c "import json; [print(c['key']) for c in json.load(open('cities.json'))]" | \
		while read key; do \
			echo "Downloading $$key..."; \
			curl -sSf "$(PAGES_URL)/data/$$key.json" -o ".site/data/$$key.json"; \
		done
	@echo "Done."

db-smoketest: check-keys
	uv run fetch.py --quick
	uv run fetch.py foodie --quick

db: check-keys
	uv run fetch.py
	uv run fetch.py foodie

site:
	mkdir -p .site
	cp -f cities.json index.html .site/

dev: site
	fswatch -o index.html cities.json | xargs -n1 -I{} cp -f index.html cities.json .site/ &
	python3 -m http.server 8080 -d .site

clean:
	rm -rf .site
