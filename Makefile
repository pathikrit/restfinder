.PHONY: fetch dev clean

fetch:
	uv run fetch.py

dev:
	mkdir -p .site
	cp -f cities.json index.html .site/
	python3 -m http.server 8080 -d .site

clean:
	rm -rf .site
