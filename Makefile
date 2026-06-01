.PHONY: fetch site serve clean

fetch:
	uv run fetch.py

site:
	mkdir -p .site
	cp -f cities.json index.html .site/

serve: site
	python3 -m http.server 8080 -d .site

clean:
	rm -rf .site
