#!/usr/bin/env python3
"""Fetch restaurant data from Overpass API and foodie URLs from Exa.ai."""

import json
import os
import sys
import time

import truststore
truststore.inject_into_ssl()

# Clear invalid SSL env vars (e.g. set to "None" by corporate proxies) so requests
# falls back to certifi / OS trust store via truststore
for _var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
    if os.environ.get(_var) in (None, "", "None"):
        os.environ.pop(_var, None)

import requests  # noqa: E402

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SITE_DIR = ".site"
DATA_DIR = os.path.join(SITE_DIR, "data")


def fetch_city(city: dict) -> list[dict]:
    """Fetch restaurants for a city from the Overpass API."""
    bbox = city["bbox"]
    query = (
        f'[out:json][timeout:60];'
        f'(node["amenity"="restaurant"]({bbox["south"]},{bbox["west"]},{bbox["north"]},{bbox["east"]});'
        f'way["amenity"="restaurant"]({bbox["south"]},{bbox["west"]},{bbox["north"]},{bbox["east"]}););'
        f'out center;'
    )
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=120,
                         headers={"User-Agent": "RestFinder/0.1"})
    resp.raise_for_status()
    raw = resp.json()

    restaurants = []
    for el in raw.get("elements", []):
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if not lat or not lon:
            continue
        restaurants.append({
            "id": el["id"],
            "lat": lat,
            "lon": lon,
            "tags": el.get("tags", {}),
        })
    return restaurants


def main():
    with open("cities.json") as f:
        cities = json.load(f)

    os.makedirs(DATA_DIR, exist_ok=True)

    for i, city in enumerate(cities):
        print(f"Fetching {city['name']}...", flush=True)
        restaurants = fetch_city(city)
        out_path = os.path.join(DATA_DIR, f"{city['key']}.json")
        with open(out_path, "w") as f:
            json.dump(restaurants, f)
        print(f"  {len(restaurants)} restaurants -> {out_path}")
        if i < len(cities) - 1:
            time.sleep(5)  # be nice to Overpass API

    print("Done.")


def get_restaurant_name(r: dict) -> str:
    if "tags" in r:
        return r["tags"].get("name", "")
    return r.get("name", "")


def fetch_urls(restaurant: str, city: str, foodie_sites: list[str], exa, max_retries: int = 3) -> list[str] | None:
    for attempt in range(max_retries):
        try:
            result = exa.search(
                query=f"{restaurant} {city} restaurant",
                type="keyword",
                num_results=5,
                include_domains=foodie_sites,
            )
            return [r.url for r in result.results]
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"    retry {attempt + 1}/{max_retries} in {wait}s: {e}")
                time.sleep(wait)
                continue
            print(f"    FAILED after {max_retries} attempts: {e}")
            return None


def foodie_main():
    """Augment saved restaurant data with foodie URLs from Exa.ai."""
    from dotenv import load_dotenv
    from exa_py import Exa

    load_dotenv()
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        print("Error: set EXA_API_KEY in .env", file=sys.stderr)
        sys.exit(1)

    exa = Exa(api_key=api_key)

    with open("cities.json") as f:
        cities = json.load(f)

    for city in cities:
        foodie_sites = city.get("foodie_sites", [])
        if not foodie_sites:
            print(f"Skipping {city['name']}: no foodie_sites configured")
            continue

        data_path = os.path.join(DATA_DIR, f"{city['key']}.json")
        if not os.path.exists(data_path):
            print(f"Skipping {city['name']}: {data_path} not found (run make fetch first)")
            continue

        with open(data_path) as f:
            restaurants = json.load(f)

        updated = 0
        skipped = 0
        total = len(restaurants)

        print(f"\n{city['name']} ({total} restaurants)...", flush=True)

        for i, r in enumerate(restaurants):
            if "foodie_urls" in r:
                skipped += 1
                continue

            name = get_restaurant_name(r).strip()
            if not name:
                r["foodie_urls"] = []
                continue

            urls = fetch_urls(name, city["name"], foodie_sites, exa)
            r["foodie_urls"] = urls if urls is not None else None
            updated += 1

            if urls:
                print(f"  [{updated}] {name}: {len(urls)} URLs")

            time.sleep(0.2)

            if updated > 0 and updated % 50 == 0:
                with open(data_path, "w") as f:
                    json.dump(restaurants, f)
                print(f"  ... checkpoint ({updated}/{total - skipped} searched)")

        with open(data_path, "w") as f:
            json.dump(restaurants, f)

        found = sum(1 for r in restaurants if r.get("foodie_urls"))
        print(f"  {updated} searched, {skipped} skipped, {found} with foodie URLs")

    print("\nDone.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "foodie":
        foodie_main()
    else:
        main()
