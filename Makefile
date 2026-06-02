.PHONY: check-keys db db-copy db-smoketest site dev clean

check-keys:
	@test -n "$$SERPER_API_KEY" || (test -f .env && grep -q SERPER_API_KEY .env) || { echo "Error: set SERPER_API_KEY in env or .env"; exit 1; }

PAGES_URL := https://pathikrit.github.io/restfinder

db-copy:
	@mkdir -p .site/data
	@unset SSL_CERT_FILE REQUESTS_CA_BUNDLE; \
	python3 -c "import json; [print(c['key']) for c in json.load(open('cities.json')) if c.get('enabled', True)]" | \
		while read key; do \
			echo "Downloading $$key..."; \
			curl -sSf "$(PAGES_URL)/data/$$key.json" -o ".site/data/$$key.json"; \
		done
	@echo "Done."

db-smoketest:
	uv run fetcher.py --quick
	uv run foodie.py --quick

db: check-keys
	uv run fetcher.py
	uv run foodie.py

site:
	mkdir -p .site
	cp -f cities.json index.html .site/

dev: site
	fswatch -o index.html cities.json | xargs -n1 -I{} cp -f index.html cities.json .site/ &
	python3 -m http.server 8080 -d .site

clean:
	rm -rf .site
