#!/usr/bin/env python3
"""Fetch restaurant data from Overpass API for all cities defined in cities.json."""

import json
import os
import time

import truststore
truststore.inject_into_ssl()

import requests  # noqa: E402

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SITE_DIR = ".site"
DATA_DIR = os.path.join(SITE_DIR, "data")


def fetch_city(city: dict) -> list[dict]:
    bbox = city["bbox"]
    query = (
        f'[out:json][timeout:30];'
        f'(node["amenity"="restaurant"]({bbox["south"]},{bbox["west"]},{bbox["north"]},{bbox["east"]});'
        f'way["amenity"="restaurant"]({bbox["south"]},{bbox["west"]},{bbox["north"]},{bbox["east"]}););'
        f'out center;'
    )
    resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=60,
                         headers={"User-Agent": "RestFinder/0.1"})
    resp.raise_for_status()
    raw = resp.json()

    restaurants = []
    for el in raw.get("elements", []):
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if not lat or not lon:
            continue
        tags = el.get("tags", {})
        housenumber = tags.get("addr:housenumber", "")
        street = tags.get("addr:street", "")
        address = f"{housenumber} {street}".strip()
        restaurants.append({
            "id": el["id"],
            "lat": lat,
            "lon": lon,
            "name": tags.get("name", "Unnamed"),
            "cuisine": tags.get("cuisine", "").replace(";", ", "),
            "address": address,
            "phone": tags.get("phone", ""),
            "website": tags.get("website", ""),
            "hours": tags.get("opening_hours", ""),
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


if __name__ == "__main__":
    main()
