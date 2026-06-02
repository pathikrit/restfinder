#!/usr/bin/env python3
"""Augment restaurant data with foodie URLs from Exa.ai."""

import json
import os
import sys
import time

import truststore
truststore.inject_into_ssl()

for _var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
    if os.environ.get(_var) in (None, "", "None"):
        os.environ.pop(_var, None)

SITE_DIR = ".site"
DATA_DIR = os.path.join(SITE_DIR, "data")


def fetch_urls(restaurant: str, city: str, foodie_sites: list[str], exa, max_retries: int = 3) -> list[str] | None:
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    def _search():
        return exa.search(
            query=f'"{restaurant}" {city} restaurant',
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


def main(quick: bool = False):
    from dotenv import load_dotenv
    from exa_py import Exa

    load_dotenv()
    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        print("Error: set EXA_API_KEY in .env", file=sys.stderr)
        sys.exit(1)

    exa = Exa(api_key=api_key)

    with open("cities.json") as f:
        cities = [c for c in json.load(f) if c.get("enabled", True)]

    if quick:
        cities = cities[:2]

    for city in cities:
        foodie_sites = city.get("foodie_sites", [])
        if not foodie_sites:
            print(f"Skipping {city['name']}: no foodie_sites configured")
            continue

        data_path = os.path.join(DATA_DIR, f"{city['key']}.json")
        if not os.path.exists(data_path):
            print(f"Skipping {city['name']}: {data_path} not found (run fetcher.py first)")
            continue

        with open(data_path) as f:
            restaurants = json.load(f)

        updated = 0
        skipped = sum(1 for r in restaurants if "foodie_urls" in r)
        to_search = sum(1 for r in restaurants if "foodie_urls" not in r and (r.get("name") or "").strip())
        total = len(restaurants)

        print(f"\n{city['name']} ({total} restaurants, {to_search} to search, {skipped} already done)...", flush=True)

        for i, r in enumerate(restaurants):
            if "foodie_urls" in r:
                continue

            name = (r.get("name") or "").strip()
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
    main(quick="--quick" in sys.argv)
