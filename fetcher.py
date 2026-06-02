#!/usr/bin/env python3
"""Fetch restaurant data from city open-data APIs."""

import json
import os
import sys

import truststore
truststore.inject_into_ssl()

for _var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
    if os.environ.get(_var) in (None, "", "None"):
        os.environ.pop(_var, None)

import requests  # noqa: E402

SITE_DIR = ".site"
DATA_DIR = os.path.join(SITE_DIR, "data")

NYC_SOCRATA_URL = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"


def title_case(s: str) -> str:
    """Title-case a string, handling all-caps input from DOHMH."""
    return " ".join(w.capitalize() for w in s.lower().split())


def build_address(row: dict) -> str:
    building = (row.get("building") or "").strip()
    street = title_case(" ".join((row.get("street") or "").split()))
    boro = row.get("boro") or ""
    zipcode = row.get("zipcode") or ""
    parts = []
    if building and street:
        parts.append(f"{building} {street}")
    elif street:
        parts.append(street)
    if boro:
        parts.append(boro)
    if zipcode:
        parts.append(zipcode)
    return ", ".join(parts)


def fetch_nyc(limit: int = 50000) -> list[dict]:
    """Fetch all restaurants from NYC DOHMH via Socrata API."""
    params = {
        "$select": (
            "camis, "
            "max(dba) as dba, "
            "max(building) as building, "
            "max(street) as street, "
            "max(boro) as boro, "
            "max(zipcode) as zipcode, "
            "max(phone) as phone, "
            "max(cuisine_description) as cuisine, "
            "max(latitude) as lat, "
            "max(longitude) as lon"
        ),
        "$where": "latitude IS NOT NULL",
        "$group": "camis",
        "$limit": limit,
    }
    resp = requests.get(NYC_SOCRATA_URL, params=params, timeout=120,
                        headers={"User-Agent": "RestFinder/0.1"})
    resp.raise_for_status()
    raw = resp.json()

    restaurants = []
    for row in raw:
        name = (row.get("dba") or "").strip()
        if not name:
            continue
        restaurants.append({
            "id": row["camis"],
            "name": title_case(name),
            "cuisine": (row.get("cuisine") or "").strip(),
            "address": build_address(row),
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "phone": (row.get("phone") or "").strip(),
        })
    return restaurants


def fetch_city(city: dict, quick: bool = False) -> list[dict]:
    key = city["key"]
    if key == "nyc":
        return fetch_nyc(limit=100 if quick else 50000)
    raise NotImplementedError(f"No fetcher implemented for {city['name']}")


def main(quick: bool = False):
    with open("cities.json") as f:
        cities = [c for c in json.load(f) if c.get("enabled", True)]

    os.makedirs(DATA_DIR, exist_ok=True)

    failed = []
    for city in cities:
        print(f"Fetching {city['name']}...", flush=True)
        try:
            restaurants = fetch_city(city, quick=quick)
        except NotImplementedError as e:
            print(f"  SKIPPED: {e}")
            continue
        except Exception as e:
            print(f"  FAILED: {e}")
            failed.append(city["name"])
            continue

        out_path = os.path.join(DATA_DIR, f"{city['key']}.json")
        with open(out_path, "w") as f:
            json.dump(restaurants, f)
        print(f"  {len(restaurants)} restaurants -> {out_path}")

    if failed:
        print(f"\nWARNING: failed to fetch: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main(quick="--quick" in sys.argv)
