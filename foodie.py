#!/usr/bin/env python3
"""Augment restaurant data with foodie URLs from Serper.dev (Google Search API)."""

import json
import os
import sys
import time

import truststore
truststore.inject_into_ssl()

for _var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
    if os.environ.get(_var) in (None, "", "None"):
        os.environ.pop(_var, None)

import requests  # noqa: E402

SITE_DIR = ".site"
DATA_DIR = os.path.join(SITE_DIR, "data")
SERPER_URL = "https://google.serper.dev/search"
BATCH_SIZE = 100


def build_query(name: str, city: str, foodie_sites: list[str]) -> str:
    sites = " OR ".join(foodie_sites)
    return f'"{name}" restaurant {city} site:({sites})'


def search_batch(queries: list[dict], api_key: str, max_retries: int = 3) -> list[dict]:
    """Send a batch of queries to Serper and return results."""
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }
    for attempt in range(max_retries):
        try:
            resp = requests.post(SERPER_URL, json=queries, headers=headers, timeout=60)
            resp.raise_for_status()
            results = resp.json()
            # Single query returns a dict, batch returns a list
            return results if isinstance(results, list) else [results]
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  retry {attempt + 1}/{max_retries} in {wait}s: {e}")
                time.sleep(wait)
                continue
            raise


def extract_urls(result: dict) -> list[str]:
    """Extract URLs from a Serper search result."""
    return [item["link"] for item in result.get("organic", []) if item.get("link")]


def main(quick: bool = False):
    from dotenv import load_dotenv

    load_dotenv()
    api_key = os.environ.get("SERPER_API_KEY")
    if not api_key:
        print("Error: set SERPER_API_KEY in .env", file=sys.stderr)
        sys.exit(1)

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

        # Collect restaurants needing search
        to_search = []
        for i, r in enumerate(restaurants):
            if "foodie_urls" in r:
                continue
            name = (r.get("name") or "").strip()
            if not name:
                r["foodie_urls"] = []
                continue
            to_search.append((i, name))

        skipped = sum(1 for r in restaurants if "foodie_urls" in r)
        total = len(restaurants)
        print(f"\n{city['name']} ({total} restaurants, {len(to_search)} to search, {skipped} already done)...", flush=True)

        searched = 0
        for batch_start in range(0, len(to_search), BATCH_SIZE):
            batch = to_search[batch_start:batch_start + BATCH_SIZE]
            queries = [{"q": build_query(name, city["name"], foodie_sites), "num": 5} for _, name in batch]

            try:
                results = search_batch(queries, api_key)
                for (idx, _), result in zip(batch, results):
                    restaurants[idx]["foodie_urls"] = extract_urls(result)
            except Exception as e:
                print(f"  FAILED batch at {batch_start}: {e}")
                for idx, _ in batch:
                    restaurants[idx]["foodie_urls"] = None

            searched += len(batch)
            with open(data_path, "w") as f:
                json.dump(restaurants, f)
            found_so_far = sum(1 for r in restaurants if r.get("foodie_urls"))
            print(f"  ... {searched}/{len(to_search)} searched, {found_so_far} with URLs", flush=True)

        found = sum(1 for r in restaurants if r.get("foodie_urls"))
        print(f"  {searched} searched, {skipped} skipped, {found} with foodie URLs")

    print("\nDone.")


if __name__ == "__main__":
    main(quick="--quick" in sys.argv)
