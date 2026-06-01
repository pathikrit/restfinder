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


def fetch_city(city: dict, max_retries: int = 5) -> list[dict]:
    """Fetch restaurants for a city from the Overpass API."""
    bbox = city["bbox"]
    query = (
        f'[out:json][timeout:60];'
        f'(node["amenity"="restaurant"]({bbox["south"]},{bbox["west"]},{bbox["north"]},{bbox["east"]});'
        f'way["amenity"="restaurant"]({bbox["south"]},{bbox["west"]},{bbox["north"]},{bbox["east"]}););'
        f'out center;'
    )
    for attempt in range(max_retries):
        try:
            resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=120,
                                 headers={"User-Agent": "RestFinder/0.1"})
            resp.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait = 15 * 2 ** attempt
                print(f"  retry {attempt + 1}/{max_retries} in {wait}s: {e}")
                time.sleep(wait)
                continue
            raise
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


def main(quick: bool = False):
    with open("cities.json") as f:
        cities = json.load(f)

    if quick:
        cities = cities[:2]

    os.makedirs(DATA_DIR, exist_ok=True)

    failed = []
    for i, city in enumerate(cities):
        print(f"Fetching {city['name']}...", flush=True)
        try:
            restaurants = fetch_city(city)
        except Exception as e:
            print(f"  FAILED: {e}")
            failed.append(city["name"])
            continue
        if quick:
            restaurants = restaurants[:100]
        out_path = os.path.join(DATA_DIR, f"{city['key']}.json")
        with open(out_path, "w") as f:
            json.dump(restaurants, f)
        print(f"  {len(restaurants)} restaurants -> {out_path}")
        if i < len(cities) - 1:
            time.sleep(5)  # be nice to Overpass API

    if failed:
        print(f"\nWARNING: failed to fetch: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)

    print("Done.")


def get_restaurant_name(r: dict) -> str:
    if "tags" in r:
        return r["tags"].get("name", "")
    return r.get("name", "")


def fetch_urls(restaurant: str, city: str, foodie_sites: list[str], exa, max_retries: int = 3) -> list[str] | None:
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    def _search():
        return exa.search(
            query=f"{restaurant} {city} restaurant",
            type="instant",
            num_results=5,
            include_domains=foodie_sites,
            system_prompt="Restaurant highlights & recommendations in foodie sites; prefer atmost 1 result per site in includeDomains",
        )

    for attempt in range(max_retries):
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(_search).result(timeout=30)
            return [r.url for r in result.results]
        except FuturesTimeout:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"    timeout, retry {attempt + 1}/{max_retries} in {wait}s")
                time.sleep(wait)
                continue
            print(f"    FAILED after {max_retries} attempts: timeout")
            return None
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"    retry {attempt + 1}/{max_retries} in {wait}s: {e}")
                time.sleep(wait)
                continue
            print(f"    FAILED after {max_retries} attempts: {e}")
            return None


def foodie_main(quick: bool = False):
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

    if quick:
        cities = cities[:2]

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
        skipped = sum(1 for r in restaurants if "foodie_urls" in r)
        to_search = sum(1 for r in restaurants if "foodie_urls" not in r and get_restaurant_name(r).strip())
        total = len(restaurants)

        print(f"\n{city['name']} ({total} restaurants, {to_search} to search, {skipped} already done)...", flush=True)

        for i, r in enumerate(restaurants):
            if "foodie_urls" in r:
                continue

            name = get_restaurant_name(r).strip()
            if not name:
                r["foodie_urls"] = []
                continue

            urls = fetch_urls(name, city["name"], foodie_sites, exa)
            r["foodie_urls"] = urls if urls is not None else None
            updated += 1

            time.sleep(0.2)

            if updated % 100 == 0:
                with open(data_path, "w") as f:
                    json.dump(restaurants, f)
                found_so_far = sum(1 for r in restaurants if r.get("foodie_urls"))
                print(f"  ... checkpoint {updated}/{to_search} searched, {found_so_far} with URLs so far", flush=True)

        with open(data_path, "w") as f:
            json.dump(restaurants, f)

        found = sum(1 for r in restaurants if r.get("foodie_urls"))
        print(f"  {updated} searched, {skipped} skipped, {found} with foodie URLs")

    print("\nDone.")


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    if "foodie" in sys.argv:
        foodie_main(quick=quick)
    else:
        main(quick=quick)
