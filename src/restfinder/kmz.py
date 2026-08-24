"""Parse Google My Maps KMZ exports without changing the database."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

KML_NAMESPACE = "http://www.opengis.net/kml/2.2"
NAMESPACES = {"kml": KML_NAMESPACE}
RESTAURANT_CATEGORIES = {
    "Restaurants": "Restaurant",
    "Cocktail Bars": "Bars",
    "Cafes, Ice Cream and Bakeries": None,
}


@dataclass(frozen=True, slots=True)
class KMZPlace:
    source_id: str
    name: str
    category: str
    description: str | None
    latitude: float
    longitude: float
    type_hint: str | None
    restaurant_candidate: bool


@dataclass(frozen=True, slots=True)
class KMZDocument:
    name: str
    places: tuple[KMZPlace, ...]


def text(element: ET.Element, path: str) -> str | None:
    value = element.findtext(path, default=None, namespaces=NAMESPACES)
    if value is None:
        return None
    value = value.strip()
    return value or None


def parse_coordinates(raw: str | None, *, place_name: str) -> tuple[float, float]:
    if not raw:
        raise ValueError(f"{place_name!r} is missing point coordinates")
    first_coordinate = raw.strip().split()[0]
    parts = first_coordinate.split(",")
    if len(parts) < 2:
        raise ValueError(f"{place_name!r} has invalid coordinates: {raw!r}")
    try:
        longitude, latitude = float(parts[0]), float(parts[1])
    except ValueError as error:
        raise ValueError(f"{place_name!r} has invalid coordinates: {raw!r}") from error
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError(f"{place_name!r} has out-of-range coordinates: {raw!r}")
    return latitude, longitude


def stable_source_id(category: str, name: str, latitude: float, longitude: float) -> str:
    identity = f"{category}\0{name}\0{latitude:.7f}\0{longitude:.7f}".encode()
    digest = hashlib.sha256(identity).hexdigest()[:20]
    return f"kmz:ricks-list:{digest}"


def kml_member(archive: ZipFile) -> str:
    names = archive.namelist()
    if "doc.kml" in names:
        return "doc.kml"
    candidates = sorted(name for name in names if name.casefold().endswith(".kml"))
    if len(candidates) != 1:
        raise ValueError("KMZ must contain doc.kml or exactly one KML file")
    return candidates[0]


def parse_kmz(path: Path) -> KMZDocument:
    try:
        with ZipFile(path) as archive:
            root = ET.fromstring(archive.read(kml_member(archive)))
    except (OSError, BadZipFile, KeyError, ET.ParseError) as error:
        raise ValueError(f"Could not parse {path}: {error}") from error

    document = root.find("kml:Document", NAMESPACES)
    if document is None:
        raise ValueError(f"{path} does not contain a KML Document")
    document_name = text(document, "kml:name") or path.stem
    places: list[KMZPlace] = []

    for folder in document.findall("kml:Folder", NAMESPACES):
        category = text(folder, "kml:name") or "Uncategorized"
        for index, placemark in enumerate(folder.findall("kml:Placemark", NAMESPACES), start=1):
            name = text(placemark, "kml:name")
            if not name:
                raise ValueError(f"{category!r} placemark {index} is missing a name")
            latitude, longitude = parse_coordinates(
                text(placemark, ".//kml:Point/kml:coordinates"),
                place_name=name,
            )
            places.append(
                KMZPlace(
                    source_id=stable_source_id(category, name, latitude, longitude),
                    name=name,
                    category=category,
                    description=text(placemark, "kml:description"),
                    latitude=latitude,
                    longitude=longitude,
                    type_hint=RESTAURANT_CATEGORIES.get(category),
                    restaurant_candidate=category in RESTAURANT_CATEGORIES,
                )
            )

    return KMZDocument(name=document_name, places=tuple(places))


def dry_run_payload(
    document: KMZDocument,
    *,
    source_file: Path,
    include_all: bool = False,
    limit: int | None = None,
) -> dict:
    selected: Iterable[KMZPlace] = document.places
    if not include_all:
        selected = (place for place in selected if place.restaurant_candidate)
    selected = list(selected)
    displayed = selected if limit is None else selected[:limit]
    category_counts = Counter(place.category for place in document.places)
    candidate_count = sum(place.restaurant_candidate for place in document.places)
    all_source_ids = Counter(place.source_id for place in document.places)
    candidate_source_ids = Counter(
        place.source_id for place in document.places if place.restaurant_candidate
    )
    candidate_names = Counter(
        place.name.casefold() for place in document.places if place.restaurant_candidate
    )
    type_hint_counts = Counter(
        place.type_hint or "Unclassified"
        for place in document.places
        if place.restaurant_candidate
    )
    return {
        "source_file": str(source_file),
        "list_name": document.name,
        "total_placemarks": len(document.places),
        "restaurant_candidates": candidate_count,
        "skipped_non_restaurant": len(document.places) - candidate_count,
        "unique_placemarks": len(all_source_ids),
        "duplicate_placemarks": sum(count - 1 for count in all_source_ids.values()),
        "unique_restaurant_candidates": len(candidate_source_ids),
        "duplicate_restaurant_candidates": sum(
            count - 1 for count in candidate_source_ids.values()
        ),
        "duplicate_candidate_name_groups": sum(count > 1 for count in candidate_names.values()),
        "candidate_type_hint_counts": dict(sorted(type_hint_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "selection": "all" if include_all else "restaurant_candidates",
        "selected_count": len(selected),
        "displayed_count": len(displayed),
        "truncated": len(displayed) < len(selected),
        "places": [asdict(place) for place in displayed],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="KMZ file to parse")
    parser.add_argument("--all", action="store_true", help="include non-restaurant folders")
    parser.add_argument("--limit", type=int, help="print at most this many selected placemarks")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be zero or greater")

    document = parse_kmz(args.path)
    payload = dry_run_payload(
        document,
        source_file=args.path,
        include_all=args.all,
        limit=args.limit,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
