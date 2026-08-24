"""Parse and import Google My Maps KMZ exports."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path
import time
from typing import Iterable
import unicodedata
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

import psycopg
import requests

KML_NAMESPACE = "http://www.opengis.net/kml/2.2"
NAMESPACES = {"kml": KML_NAMESPACE}
RESTAURANT_CATEGORIES = {
    "Restaurants": "Restaurant",
    "Cocktail Bars": "Bars",
    "Cafes, Ice Cream and Bakeries": "Coffee Shops",
}
SOURCE = "Rick's List"
REFERENCE = "Rick's List"
TIMES_SQUARE = (40.7580, -73.9855)
MAX_DRIVING_SECONDS = 2 * 60 * 60
OSRM_TABLE_URL = "https://router.project-osrm.org/table/v1/driving"
ROUTE_BATCH_SIZE = 75
MATCH_DISTANCE_METERS = 100
TYPE_PRIORITY = {"Restaurant": 1, "Coffee Shops": 2, "Dessert": 3, "Bars": 4}
DESSERT_KEYWORDS = (
    "bakery",
    "bake shop",
    "bakeshop",
    "cake",
    "candy",
    "chocolate",
    "confection",
    "cookie",
    "creamery",
    "cupcake",
    "dessert",
    "donut",
    "doughnut",
    "gelato",
    "ice cream",
    "macaron",
    "patisserie",
    "pastry",
    "pie shop",
    "pudding",
    "sweet",
)


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
    duplicate_source_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KMZDocument:
    name: str
    places: tuple[KMZPlace, ...]


@dataclass(frozen=True, slots=True)
class ExistingRestaurant:
    id: str
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class MatchResult:
    matches: dict[str, str]
    ambiguous: int


@dataclass(frozen=True, slots=True)
class ImportResult:
    inserted: int
    updated: int
    matched_existing: int
    ambiguous: int
    duplicates_removed: int


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


def type_for(category: str, name: str) -> str | None:
    if category == "Cafes, Ice Cream and Bakeries":
        normalized_name = name.casefold()
        if any(keyword in normalized_name for keyword in DESSERT_KEYWORDS):
            return "Dessert"
        return "Coffee Shops"
    return RESTAURANT_CATEGORIES.get(category)


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
                    type_hint=type_for(category, name),
                    restaurant_candidate=category in RESTAURANT_CATEGORIES,
                )
            )

    return KMZDocument(name=document_name, places=tuple(places))


def unique_restaurant_candidates(document: KMZDocument) -> list[KMZPlace]:
    candidates = {
        place.source_id: place for place in document.places if place.restaurant_candidate
    }
    unique: list[KMZPlace] = []
    for place in sorted(candidates.values(), key=lambda candidate: candidate.source_id):
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(unique)
                if normalize_match_name(existing.name) == normalize_match_name(place.name)
                and distance_meters(
                    existing.latitude,
                    existing.longitude,
                    place.latitude,
                    place.longitude,
                )
                <= MATCH_DISTANCE_METERS
            ),
            None,
        )
        if duplicate_index is None:
            unique.append(place)
            continue

        existing = unique[duplicate_index]
        type_hint = existing.type_hint
        if TYPE_PRIORITY[place.type_hint] > TYPE_PRIORITY[existing.type_hint]:
            type_hint = place.type_hint
        unique[duplicate_index] = replace(
            existing,
            type_hint=type_hint,
            duplicate_source_ids=(*existing.duplicate_source_ids, place.source_id),
        )
    return unique


def driving_durations(
    places: Iterable[KMZPlace],
    *,
    session: requests.Session | None = None,
    pause_seconds: float = 1.0,
) -> dict[str, float | None]:
    """Return traffic-free fastest driving durations from Times Square."""
    places = list(places)
    session = session or requests.Session()
    session.headers.setdefault(
        "User-Agent",
        "RestFinder/0.0.1 (github.com/pathikrit/restfinder)",
    )
    durations: dict[str, float | None] = {}

    for start in range(0, len(places), ROUTE_BATCH_SIZE):
        batch = places[start : start + ROUTE_BATCH_SIZE]
        points = [TIMES_SQUARE, *((place.latitude, place.longitude) for place in batch)]
        coordinates = ";".join(f"{longitude:.7f},{latitude:.7f}" for latitude, longitude in points)
        destinations = ";".join(str(index) for index in range(1, len(points)))
        response = session.get(
            f"{OSRM_TABLE_URL}/{coordinates}",
            params={
                "sources": "0",
                "destinations": destinations,
                "annotations": "duration",
            },
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != "Ok" or len(payload.get("durations", [])) != 1:
            raise ValueError(f"OSRM returned an invalid table response: {payload.get('code')}")
        batch_durations = payload["durations"][0]
        if len(batch_durations) != len(batch):
            raise ValueError("OSRM returned the wrong number of route durations")
        durations.update(
            (place.source_id, duration)
            for place, duration in zip(batch, batch_durations, strict=True)
        )
        if start + ROUTE_BATCH_SIZE < len(places):
            time.sleep(pause_seconds)

    return durations


def within_driving_limit(
    places: Iterable[KMZPlace],
    durations: dict[str, float | None],
    *,
    max_seconds: float = MAX_DRIVING_SECONDS,
) -> list[KMZPlace]:
    accepted = []
    for place in places:
        duration = durations.get(place.source_id)
        if duration is not None and duration <= max_seconds:
            accepted.append(place)
    return accepted


def normalize_name(name: str) -> str:
    return " ".join(name.casefold().split())


def normalize_match_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    return " ".join(
        "".join(character if character.isalnum() else " " for character in decomposed).split()
    )


def distance_meters(
    first_latitude: float,
    first_longitude: float,
    second_latitude: float,
    second_longitude: float,
) -> float:
    first_latitude_radians = radians(first_latitude)
    second_latitude_radians = radians(second_latitude)
    latitude_delta = second_latitude_radians - first_latitude_radians
    longitude_delta = radians(second_longitude - first_longitude)
    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(first_latitude_radians)
        * cos(second_latitude_radians)
        * sin(longitude_delta / 2) ** 2
    )
    return 6_371_000 * 2 * atan2(sqrt(haversine), sqrt(1 - haversine))


def match_existing_restaurants(
    places: Iterable[KMZPlace],
    existing_restaurants: Iterable[ExistingRestaurant],
) -> MatchResult:
    by_name: dict[str, list[ExistingRestaurant]] = {}
    for restaurant in existing_restaurants:
        by_name.setdefault(normalize_match_name(restaurant.name), []).append(restaurant)

    matches: dict[str, str] = {}
    ambiguous = 0
    for place in places:
        nearby = sorted(
            [
                (
                    distance_meters(
                        place.latitude,
                        place.longitude,
                        restaurant.latitude,
                        restaurant.longitude,
                    ),
                    restaurant,
                )
                for restaurant in by_name.get(normalize_match_name(place.name), [])
            ],
            key=lambda candidate: (candidate[0], candidate[1].id),
        )
        nearby = [candidate for candidate in nearby if candidate[0] <= MATCH_DISTANCE_METERS]
        if len(nearby) == 1:
            matches[place.source_id] = nearby[0][1].id
        elif len(nearby) > 1:
            nearest_distance = nearby[0][0]
            next_distance = nearby[1][0]
            if next_distance - nearest_distance >= 25:
                matches[place.source_id] = nearby[0][1].id
            else:
                ambiguous += 1
    return MatchResult(matches=matches, ambiguous=ambiguous)


def import_places(
    places: Iterable[KMZPlace],
    *,
    connection_url: str,
    observed_at: datetime,
    reference_added_at: datetime,
) -> ImportResult:
    places = list(places)
    if not places:
        raise ValueError("Refusing to import an empty KMZ selection")
    name_counts = Counter(normalize_name(place.name) for place in places)

    with psycopg.connect(connection_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, latitude, longitude
                FROM restaurants
                WHERE source = 'nyc_dohmh'
                  AND latitude IS NOT NULL
                  AND longitude IS NOT NULL
                """
            )
            match_result = match_existing_restaurants(
                places,
                (
                    ExistingRestaurant(
                        id=row[0],
                        name=row[1],
                        latitude=row[2],
                        longitude=row[3],
                    )
                    for row in cursor.fetchall()
                ),
            )
            cursor.execute(
                """
                CREATE TEMP TABLE incoming_kmz_restaurants (
                    source_id text PRIMARY KEY,
                    restaurant_id text NOT NULL,
                    name text NOT NULL,
                    type text NOT NULL,
                    type_priority integer NOT NULL,
                    latitude double precision NOT NULL,
                    longitude double precision NOT NULL,
                    is_chain boolean NOT NULL
                ) ON COMMIT DROP
                """
            )
            with cursor.copy(
                """
                COPY incoming_kmz_restaurants
                    (source_id, restaurant_id, name, type, type_priority,
                     latitude, longitude, is_chain)
                FROM STDIN
                """
            ) as copy:
                for place in places:
                    copy.write_row(
                        (
                            place.source_id,
                            match_result.matches.get(place.source_id, place.source_id),
                            place.name,
                            place.type_hint,
                            TYPE_PRIORITY[place.type_hint],
                            place.latitude,
                            place.longitude,
                            name_counts[normalize_name(place.name)] > 5,
                        )
                    )
            cursor.execute(
                """
                SELECT count(*)
                FROM incoming_kmz_restaurants incoming
                JOIN restaurants existing ON existing.id = incoming.source_id
                WHERE incoming.restaurant_id = incoming.source_id
                """
            )
            existing = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO restaurants (
                    id, source, name, type, latitude, longitude,
                    first_seen, last_seen, is_chain
                )
                SELECT
                    source_id, %(source)s, name, type, latitude, longitude,
                    %(observed_at)s, %(observed_at)s, is_chain
                FROM incoming_kmz_restaurants
                WHERE restaurant_id = source_id
                ON CONFLICT (id) DO UPDATE SET
                    source = excluded.source,
                    name = excluded.name,
                    type = excluded.type,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    last_seen = excluded.last_seen,
                    is_chain = excluded.is_chain
                """,
                {"source": SOURCE, "observed_at": observed_at},
            )
            cursor.execute(
                """
                UPDATE restaurants restaurant
                SET type = matched.type
                FROM (
                    SELECT DISTINCT ON (restaurant_id) restaurant_id, type
                    FROM incoming_kmz_restaurants
                    WHERE restaurant_id <> source_id
                    ORDER BY restaurant_id, type_priority DESC
                ) matched
                WHERE restaurant.id = matched.restaurant_id
                  AND restaurant.type IS NULL
                """
            )
            cursor.execute(
                """
                INSERT INTO restaurant_references (restaurant_id, reference, added_at)
                SELECT DISTINCT restaurant_id, %(reference)s, %(added_at)s
                FROM incoming_kmz_restaurants
                ON CONFLICT (restaurant_id, reference)
                DO NOTHING
                """,
                {"reference": REFERENCE, "added_at": reference_added_at},
            )
            cursor.execute(
                """
                DELETE FROM restaurants restaurant
                USING incoming_kmz_restaurants incoming
                WHERE restaurant.id = incoming.source_id
                  AND incoming.restaurant_id <> incoming.source_id
                  AND restaurant.source = %s
                """,
                (SOURCE,),
            )
            duplicate_source_ids = [
                duplicate_source_id
                for place in places
                for duplicate_source_id in place.duplicate_source_ids
            ]
            if duplicate_source_ids:
                cursor.execute(
                    """
                    DELETE FROM restaurants
                    WHERE source = %s
                      AND id = ANY(%s)
                    """,
                    (SOURCE, duplicate_source_ids),
                )
                duplicates_removed = cursor.rowcount
            else:
                duplicates_removed = 0
    unmatched = len(places) - len(match_result.matches)
    return ImportResult(
        inserted=unmatched - existing,
        updated=existing,
        matched_existing=len(match_result.matches),
        ambiguous=match_result.ambiguous,
        duplicates_removed=duplicates_removed,
    )


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
    parser.add_argument(
        "--import-db",
        action="store_true",
        help="route-filter and idempotently import candidates into Postgres",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be zero or greater")

    document = parse_kmz(args.path)
    if args.import_db:
        if args.all or args.limit is not None:
            parser.error("--import-db cannot be combined with --all or --limit")
        from restfinder.config import database_url

        candidates = unique_restaurant_candidates(document)
        durations = driving_durations(candidates)
        accepted = within_driving_limit(candidates, durations)
        observed_at = datetime.now(timezone.utc)
        reference_added_at = datetime.fromtimestamp(args.path.stat().st_mtime, timezone.utc)
        import_result = import_places(
            accepted,
            connection_url=database_url(),
            observed_at=observed_at,
            reference_added_at=reference_added_at,
        )
        accepted_types = Counter(place.type_hint for place in accepted)
        routed = [duration for duration in durations.values() if duration is not None]
        print(
            json.dumps(
                {
                    "source": SOURCE,
                    "unique_candidates": len(candidates),
                    "within_two_hours": len(accepted),
                    "over_two_hours": sum(
                        duration is not None and duration > MAX_DRIVING_SECONDS
                        for duration in durations.values()
                    ),
                    "unroutable": sum(duration is None for duration in durations.values()),
                    "maximum_accepted_minutes": round(
                        max(durations[place.source_id] for place in accepted) / 60, 1
                    ),
                    "maximum_routed_minutes": round(max(routed) / 60, 1),
                    "types": dict(sorted(accepted_types.items())),
                    "matched_existing": import_result.matched_existing,
                    "ambiguous_matches": import_result.ambiguous,
                    "duplicates_removed": import_result.duplicates_removed,
                    "inserted": import_result.inserted,
                    "updated": import_result.updated,
                    "reference": REFERENCE,
                },
                indent=2,
            )
        )
        return

    payload = dry_run_payload(
        document,
        source_file=args.path,
        include_all=args.all,
        limit=args.limit,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
