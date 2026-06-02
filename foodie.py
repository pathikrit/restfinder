#!/usr/bin/env python3
"""Augment restaurant data with foodie URLs from Serper.dev (Google Search API)."""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

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
PARALLEL_BATCHES = 4


def matches_foodie_site(url: str, foodie_sites: list[str]) -> bool:
    """Check if a URL belongs to one of the allowed foodie sites."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        path = parsed.path or ""
        for site in foodie_sites:
            # site can be "ny.eater.com" or "www.theinfatuation.com/new-york"
            if "/" in site:
                domain, prefix = site.split("/", 1)
                if host.endswith(domain) and path.startswith("/" + prefix):
                    return True
            elif host.endswith(site):
                return True
    except Exception:
        pass
    return False


def search_batch(queries: list[dict], api_key: str) -> list[dict]:
    """Send a batch of up to 100 queries to Serper, return list of results."""
    resp = requests.post(SERPER_URL, json=queries, timeout=60,
                         headers={"X-API-KEY": api_key, "Content-Type": "application/json"})
    resp.raise_for_status()
    results = resp.json()
    return results if isinstance(results, list) else [results]


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
        sites_query = " OR ".join(foodie_sites)
        to_search = []
        for i, r in enumerate(restaurants):
            if "foodie_urls" in r:
                continue
            name = (r.get("name") or "").strip()
            if not name:
                r["foodie_urls"] = []
                continue
            to_search.append((i, {"q": f'"{name}" restaurant {city["name"]} site:({sites_query})', "num": 5}))

        skipped = len(restaurants) - len(to_search) - sum(1 for r in restaurants if "foodie_urls" not in r and not (r.get("name") or "").strip())
        print(f"\n{city['name']}: {len(restaurants)} total, {len(to_search)} to search, {skipped} already done", flush=True)

        # Submit batches in parallel
        batches = []
        for start in range(0, len(to_search), BATCH_SIZE):
            chunk = to_search[start:start + BATCH_SIZE]
            batches.append(([idx for idx, _ in chunk], [q for _, q in chunk]))

        searched = 0
        with ThreadPoolExecutor(max_workers=PARALLEL_BATCHES) as pool:
            futures = {pool.submit(search_batch, queries, api_key): idxs for idxs, queries in batches}
            for future in as_completed(futures):
                idxs = futures[future]
                try:
                    results = future.result()
                    for idx, result in zip(idxs, results):
                        urls = [r["link"] for r in result.get("organic", []) if r.get("link")]
                        restaurants[idx]["foodie_urls"] = [u for u in urls if matches_foodie_site(u, foodie_sites)]
                except Exception as e:
                    print(f"  FAILED batch: {e}")
                    for idx in idxs:
                        restaurants[idx]["foodie_urls"] = None

                searched += len(idxs)
                with open(data_path, "w") as f:
                    json.dump(restaurants, f)
                found = sum(1 for r in restaurants if r.get("foodie_urls"))
                print(f"  {searched}/{len(to_search)} searched, {found} with URLs", flush=True)

        # Filter to restaurants with >=2 distinct foodie domains
        def distinct_domains(urls):
            domains = set()
            for u in (urls or []):
                try:
                    host = urlparse(u).hostname.replace("archive.", "www.")
                    if host:
                        domains.add(host)
                except Exception:
                    pass
            return domains

        restaurants = [r for r in restaurants if len(distinct_domains(r.get("foodie_urls"))) >= 2]
        with open(data_path, "w") as f:
            json.dump(restaurants, f)
        print(f"  Done: {len(restaurants)} restaurants with foodie URLs written")

    print("\nDone.")


if __name__ == "__main__":
    main(quick="--quick" in sys.argv)
