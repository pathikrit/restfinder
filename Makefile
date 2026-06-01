.PHONY: db site dev clean

db:
	@test -f .env && grep -q EXA_API_KEY .env || { echo "Error: set EXA_API_KEY in .env"; exit 1; }
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
