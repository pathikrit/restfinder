"""Import the legacy published restaurant JSON into the canonical database."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

import psycopg

from restfinder.config import database_url
from restfinder.kmz import ExistingRestaurant, KMZPlace, match_existing_restaurants, normalize_name

SOURCE = "legacy_site"
DEFAULT_SNAPSHOT_AT = datetime(2026, 6, 4, tzinfo=timezone.utc)
ATLAS_TYPE = "Hidden / Speakeasy"


@dataclass(frozen=True, slots=True)
class LegacyRestaurant:
    source_id: str
    name: str
    cuisine: str | None
    address: str | None
    phone: str | None
    latitude: float
    longitude: float
    references: tuple[str, ...]

    @property
    def fallback_id(self) -> str:
        return f"legacy_nyc:{self.source_id}"

    @property
    def dohmh_id(self) -> str:
        return f"nyc_dohmh:{self.source_id}"

    @property
    def is_atlas_obscura(self) -> bool:
        return any(is_atlas_obscura(reference) for reference in self.references)


@dataclass(frozen=True, slots=True)
class LegacyImportResult:
    direct_id_matches: int
    matched_existing: int
    inserted_fallbacks: int
    updated_fallbacks: int
    references_imported: int
    atlas_obscura_restaurants: int
    ambiguous_matches: int


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int)):
        raise ValueError("optional restaurant fields must be strings, integers, or null")
    cleaned = str(value).strip()
    return cleaned or None


def is_web_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_atlas_obscura(value: str) -> bool:
    hostname = (urlsplit(value).hostname or "").casefold()
    return hostname == "atlasobscura.com" or hostname.endswith(".atlasobscura.com")


def load_legacy_json(path: Path) -> list[LegacyRestaurant]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read {path}: {error}") from error
    if not isinstance(payload, list) or not payload:
        raise ValueError(f"{path}: expected a non-empty JSON array")

    restaurants = []
    for index, row in enumerate(payload):
        if not isinstance(row, dict):
            raise ValueError(f"{path}: row {index} must be an object")
        source_id = optional_text(row.get("id"))
        name = optional_text(row.get("name"))
        references = row.get("foodie_urls")
        if not source_id or not name:
            raise ValueError(f"{path}: row {index} requires id and name")
        if not isinstance(references, list) or not references:
            raise ValueError(f"{path}: row {index} requires foodie_urls")
        if not all(isinstance(value, str) and is_web_url(value) for value in references):
            raise ValueError(f"{path}: row {index} contains an invalid foodie URL")
        try:
            latitude = float(row["lat"])
            longitude = float(row["lon"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"{path}: row {index} requires numeric coordinates") from error
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError(f"{path}: row {index} has out-of-range coordinates")
        restaurants.append(
            LegacyRestaurant(
                source_id=source_id,
                name=name,
                cuisine=optional_text(row.get("cuisine")),
                address=optional_text(row.get("address")),
                phone=optional_text(row.get("phone")),
                latitude=latitude,
                longitude=longitude,
                references=tuple(dict.fromkeys(references)),
            )
        )

    ids = [restaurant.source_id for restaurant in restaurants]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: restaurant IDs must be unique")
    return restaurants


def match_legacy_restaurants(
    restaurants: Iterable[LegacyRestaurant],
    existing_restaurants: Iterable[tuple[str, str, float | None, float | None, str]],
) -> tuple[dict[str, str], int, int]:
    restaurants = list(restaurants)
    existing_restaurants = list(existing_restaurants)
    existing_ids = {restaurant[0] for restaurant in existing_restaurants}
    targets = {
        restaurant.source_id: restaurant.dohmh_id
        for restaurant in restaurants
        if restaurant.dohmh_id in existing_ids
    }
    direct = len(targets)
    unmatched = [restaurant for restaurant in restaurants if restaurant.source_id not in targets]

    ambiguous = 0
    for source in ("nyc_dohmh", "Rick's List"):
        if not unmatched:
            break
        candidates = [
            ExistingRestaurant(row[0], row[1], row[2], row[3])
            for row in existing_restaurants
            if row[4] == source and row[2] is not None and row[3] is not None
        ]
        places = [
            KMZPlace(
                source_id=restaurant.source_id,
                name=restaurant.name,
                category="",
                description=None,
                latitude=restaurant.latitude,
                longitude=restaurant.longitude,
                type_hint=None,
                restaurant_candidate=True,
            )
            for restaurant in unmatched
        ]
        result = match_existing_restaurants(places, candidates)
        targets.update(result.matches)
        ambiguous += result.ambiguous
        unmatched = [restaurant for restaurant in unmatched if restaurant.source_id not in targets]

    return targets, direct, ambiguous


def import_legacy_restaurants(
    restaurants: Iterable[LegacyRestaurant],
    *,
    connection_url: str,
    observed_at: datetime = DEFAULT_SNAPSHOT_AT,
) -> LegacyImportResult:
    restaurants = list(restaurants)
    if not restaurants:
        raise ValueError("Refusing to import an empty legacy snapshot")
    name_counts = Counter(normalize_name(restaurant.name) for restaurant in restaurants)

    with psycopg.connect(connection_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, name, latitude, longitude, source FROM restaurants")
            matches, direct, ambiguous = match_legacy_restaurants(
                restaurants,
                cursor.fetchall(),
            )
            cursor.execute(
                """
                CREATE TEMP TABLE incoming_legacy_restaurants (
                    source_id text PRIMARY KEY,
                    fallback_id text NOT NULL,
                    restaurant_id text NOT NULL,
                    name text NOT NULL,
                    cuisine text,
                    address text,
                    phone text,
                    latitude double precision NOT NULL,
                    longitude double precision NOT NULL,
                    is_chain boolean NOT NULL,
                    is_atlas_obscura boolean NOT NULL
                ) ON COMMIT DROP
                """
            )
            with cursor.copy(
                """
                COPY incoming_legacy_restaurants
                    (source_id, fallback_id, restaurant_id, name, cuisine, address, phone,
                     latitude, longitude, is_chain, is_atlas_obscura)
                FROM STDIN
                """
            ) as copy:
                for restaurant in restaurants:
                    copy.write_row(
                        (
                            restaurant.source_id,
                            restaurant.fallback_id,
                            matches.get(restaurant.source_id, restaurant.fallback_id),
                            restaurant.name,
                            restaurant.cuisine,
                            restaurant.address,
                            restaurant.phone,
                            restaurant.latitude,
                            restaurant.longitude,
                            name_counts[normalize_name(restaurant.name)] > 5,
                            restaurant.is_atlas_obscura,
                        )
                    )
            cursor.execute(
                """
                SELECT count(*)
                FROM incoming_legacy_restaurants incoming
                JOIN restaurants existing ON existing.id = incoming.fallback_id
                WHERE incoming.restaurant_id = incoming.fallback_id
                """
            )
            existing_fallbacks = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO restaurants (
                    id, source, name, type, cuisine, address, phone, latitude, longitude,
                    first_seen, last_seen, is_chain
                )
                SELECT
                    fallback_id, %(source)s, name,
                    CASE WHEN is_atlas_obscura THEN %(atlas_type)s END,
                    cuisine, address, phone, latitude, longitude,
                    %(observed_at)s, %(observed_at)s, is_chain
                FROM incoming_legacy_restaurants
                WHERE restaurant_id = fallback_id
                ON CONFLICT (id) DO UPDATE SET
                    source = excluded.source,
                    name = excluded.name,
                    type = COALESCE(excluded.type, restaurants.type),
                    cuisine = excluded.cuisine,
                    address = excluded.address,
                    phone = excluded.phone,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    last_seen = excluded.last_seen,
                    is_chain = excluded.is_chain
                """,
                {"source": SOURCE, "atlas_type": ATLAS_TYPE, "observed_at": observed_at},
            )
            cursor.execute(
                """
                UPDATE restaurants restaurant
                SET type = %(atlas_type)s
                FROM incoming_legacy_restaurants incoming
                WHERE restaurant.id = incoming.restaurant_id
                  AND incoming.is_atlas_obscura
                """,
                {"atlas_type": ATLAS_TYPE},
            )
            atlas_count = cursor.rowcount

            reference_rows = [
                (matches.get(restaurant.source_id, restaurant.fallback_id), reference, observed_at)
                for restaurant in restaurants
                for reference in restaurant.references
            ]
            cursor.executemany(
                """
                INSERT INTO restaurant_references (restaurant_id, reference, added_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (restaurant_id, reference)
                DO UPDATE SET added_at = excluded.added_at
                """,
                reference_rows,
            )
            cursor.execute(
                """
                DELETE FROM restaurants restaurant
                USING incoming_legacy_restaurants incoming
                WHERE restaurant.id = incoming.fallback_id
                  AND incoming.restaurant_id <> incoming.fallback_id
                  AND restaurant.source = %s
                """,
                (SOURCE,),
            )

    unmatched = len(restaurants) - len(matches)
    return LegacyImportResult(
        direct_id_matches=direct,
        matched_existing=len(matches) - direct,
        inserted_fallbacks=unmatched - existing_fallbacks,
        updated_fallbacks=existing_fallbacks,
        references_imported=len(reference_rows),
        atlas_obscura_restaurants=atlas_count,
        ambiguous_matches=ambiguous,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="legacy data/nyc.json snapshot")
    args = parser.parse_args()
    restaurants = load_legacy_json(args.path)
    result = import_legacy_restaurants(restaurants, connection_url=database_url())
    print(json.dumps(asdict(result), indent=2))


if __name__ == "__main__":
    main()
