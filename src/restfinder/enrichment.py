"""Persist open Overture enrichment and durable Google Place identifiers."""

from __future__ import annotations

import argparse
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import floor
from typing import Literal

import duckdb
import psycopg
import requests
from psycopg.types.json import Jsonb

from restfinder.config import (
    database_url,
    google_places_monthly_limit,
    optional_environment,
    required_environment,
)
from restfinder.matching import distance_meters, fuzzy_name_score, normalize_match_name

OVERTURE_CATALOG_URL = "https://stac.overturemaps.org/catalog.json"
OVERTURE_S3_ROOT = "s3://overturemaps-us-west-2/release"
GOOGLE_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
NYC_BOUNDS = (-74.50, 40.40, -73.20, 41.20)
MATCH_DISTANCE_METERS = 100.0
FUZZY_MATCH_SCORE = 0.92
FUZZY_WIN_MARGIN = 0.03
GOOGLE_PROVIDER = "google_places"
OVERTURE_PROVIDER = "overture"
MatchStatus = Literal["matched", "unmatched", "ambiguous"]
GENERIC_FOOD_CATEGORIES = frozenset(
    {
        "food_and_drink",
        "restaurant",
        "casual_eatery",
        "fast_food_restaurant",
        "food_court",
        "bar",
        "cafe",
        "bakery",
        "coffee_shop",
    }
)
OVERTURE_DESSERT_CATEGORIES = frozenset(
    {
        "candy_store",
        "chocolate_shop",
        "dessert_restaurant",
        "dessert_shop",
        "donut_shop",
        "frozen_yogurt_shop",
        "ice_cream_shop",
    }
)
OVERTURE_FAST_FOOD_CATEGORIES = frozenset(
    {"fast_food_restaurant", "food_court"}
)
OVERTURE_BAR_CATEGORIES = frozenset(
    {
        "bar",
        "beer_garden",
        "brewery",
        "cocktail_bar",
        "night_club",
        "pub",
        "wine_bar",
    }
)
OVERTURE_COFFEE_CATEGORIES = frozenset(
    {"bakery", "cafe", "coffee_shop", "tea_house"}
)


@dataclass(frozen=True, slots=True)
class RestaurantForEnrichment:
    id: str
    name: str
    address: str | None
    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class ProviderPlace:
    id: str
    name: str
    address: str | None
    latitude: float
    longitude: float
    primary_category: str | None = None
    category_hierarchy: tuple[str, ...] = ()
    alternate_categories: tuple[str, ...] = ()
    operating_status: str | None = None
    confidence: float | None = None
    phones: tuple[str, ...] = ()
    websites: tuple[str, ...] = ()
    attribution: object | None = None


@dataclass(frozen=True, slots=True)
class ProviderMatch:
    status: MatchStatus
    place: ProviderPlace | None = None
    method: str | None = None
    score: float | None = None


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    checked: int
    matched: int
    unmatched: int
    ambiguous: int
    requests: int = 0


def utcnow() -> datetime:
    return datetime.now(UTC)


def house_number(address: str | None) -> str | None:
    if not address:
        return None
    match = re.search(r"\b\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?\b", address)
    return match.group(0).casefold() if match else None


def category_label(category: str | None) -> str | None:
    if not category:
        return None
    value = category.removesuffix("_restaurant").removesuffix("_cuisine")
    return value.replace("_", " ").title()


def overture_cuisine(category_hierarchy: Iterable[str] | None) -> str | None:
    for category in reversed(tuple(category_hierarchy or ())):
        if category not in GENERIC_FOOD_CATEGORIES:
            return category_label(category)
    return None


def overture_restaurant_type(
    primary_category: str | None,
    category_hierarchy: Iterable[str] | None,
) -> str | None:
    categories = set(category_hierarchy or ())
    if primary_category:
        categories.add(primary_category)
    for restaurant_type, provider_categories in (
        ("Dessert", OVERTURE_DESSERT_CATEGORIES),
        ("Fast Food", OVERTURE_FAST_FOOD_CATEGORIES),
        ("Bars", OVERTURE_BAR_CATEGORIES),
        ("Coffee Shops", OVERTURE_COFFEE_CATEGORIES),
    ):
        if categories & provider_categories:
            return restaurant_type
    if "food_and_drink" in categories or any(
        category.endswith("_restaurant") for category in categories
    ):
        return "Restaurant"
    return None


def choose_provider_match(
    restaurant: RestaurantForEnrichment,
    candidates: Iterable[ProviderPlace],
) -> ProviderMatch:
    nearby: list[tuple[ProviderPlace, float, float]] = []
    for candidate in candidates:
        distance = distance_meters(
            restaurant.latitude,
            restaurant.longitude,
            candidate.latitude,
            candidate.longitude,
        )
        if distance <= MATCH_DISTANCE_METERS:
            nearby.append((candidate, fuzzy_name_score(restaurant.name, candidate.name), distance))

    exact = [
        item
        for item in nearby
        if normalize_match_name(item[0].name) == normalize_match_name(restaurant.name)
    ]
    if len(exact) == 1:
        return ProviderMatch("matched", exact[0][0], "exact_name_nearby", 1.0)
    if len(exact) > 1:
        return ProviderMatch("ambiguous")

    expected_number = house_number(restaurant.address)
    fuzzy = [
        item
        for item in nearby
        if expected_number
        and house_number(item[0].address) == expected_number
        and item[1] >= FUZZY_MATCH_SCORE
    ]
    fuzzy.sort(key=lambda item: (-item[1], item[2], item[0].id))
    if not fuzzy:
        return ProviderMatch("unmatched")
    if len(fuzzy) > 1 and fuzzy[0][1] - fuzzy[1][1] < FUZZY_WIN_MARGIN:
        return ProviderMatch("ambiguous")
    return ProviderMatch("matched", fuzzy[0][0], "fuzzy_name_address", fuzzy[0][1])


def _cell(latitude: float, longitude: float) -> tuple[int, int]:
    cell_size = 0.002
    return floor(latitude / cell_size), floor(longitude / cell_size)


def candidate_index(places: Iterable[ProviderPlace]) -> dict[tuple[int, int], list[ProviderPlace]]:
    index: dict[tuple[int, int], list[ProviderPlace]] = {}
    for place in places:
        index.setdefault(_cell(place.latitude, place.longitude), []).append(place)
    return index


def nearby_candidates(
    restaurant: RestaurantForEnrichment,
    index: dict[tuple[int, int], list[ProviderPlace]],
) -> list[ProviderPlace]:
    latitude_cell, longitude_cell = _cell(restaurant.latitude, restaurant.longitude)
    return [
        place
        for latitude_offset in (-1, 0, 1)
        for longitude_offset in (-1, 0, 1)
        for place in index.get(
            (latitude_cell + latitude_offset, longitude_cell + longitude_offset),
            (),
        )
    ]


def latest_overture_release(session: requests.Session | None = None) -> str:
    response = (session or requests.Session()).get(OVERTURE_CATALOG_URL, timeout=30)
    response.raise_for_status()
    for link in response.json().get("links", []):
        if link.get("rel") == "child" and link.get("latest") is True:
            return str(link["href"]).rstrip("/").split("/")[-2]
    raise RuntimeError("Overture catalog did not identify a latest release")


def fetch_overture_places(release: str) -> list[ProviderPlace]:
    minimum_longitude, minimum_latitude, maximum_longitude, maximum_latitude = NYC_BOUNDS
    parquet_path = f"{OVERTURE_S3_ROOT}/{release}/theme=places/type=place/*"
    connection = duckdb.connect()
    try:
        connection.execute("INSTALL httpfs")
        connection.execute("LOAD httpfs")
        connection.execute("INSTALL spatial")
        connection.execute("LOAD spatial")
        connection.execute("SET s3_region = 'us-west-2'")
        rows = connection.execute(
            """
            SELECT
                id,
                names.primary AS name,
                ST_X(geometry) AS longitude,
                ST_Y(geometry) AS latitude,
                basic_category,
                taxonomy.primary AS primary_category,
                taxonomy.hierarchy AS category_hierarchy,
                taxonomy.alternates AS alternate_categories,
                operating_status,
                confidence,
                addresses[1].freeform AS address,
                phones,
                websites,
                sources
            FROM read_parquet(?)
            WHERE bbox.xmin >= ? AND bbox.xmax <= ?
              AND bbox.ymin >= ? AND bbox.ymax <= ?
              AND names.primary IS NOT NULL
              AND taxonomy.hierarchy IS NOT NULL
              AND list_contains(taxonomy.hierarchy, 'food_and_drink')
            """,
            [
                parquet_path,
                minimum_longitude,
                maximum_longitude,
                minimum_latitude,
                maximum_latitude,
            ],
        ).fetchall()
    finally:
        connection.close()

    return [
        ProviderPlace(
            id=str(row[0]),
            name=str(row[1]),
            longitude=float(row[2]),
            latitude=float(row[3]),
            primary_category=row[5] or row[4],
            category_hierarchy=tuple(row[6] or ()),
            alternate_categories=tuple(row[7] or ()),
            operating_status=row[8],
            confidence=float(row[9]) if row[9] is not None else None,
            address=row[10],
            phones=tuple(row[11] or ()),
            websites=tuple(row[12] or ()),
            attribution=row[13],
        )
        for row in rows
    ]


def current_restaurants(
    connection: psycopg.Connection,
    *,
    provider: str | None = None,
    scope: Literal["all", "exportable", "backlog"] = "all",
    exclude_checked_since: datetime | None = None,
    limit: int | None = None,
) -> list[RestaurantForEnrichment]:
    conditions = [
        "restaurant.latitude IS NOT NULL",
        "restaurant.longitude IS NOT NULL",
        "alias.alias_restaurant_id IS NULL",
        (
            "(restaurant.source <> 'nyc_dohmh' OR restaurant.last_seen = "
            "(SELECT max(current.last_seen) FROM restaurants current "
            "WHERE current.source = restaurant.source))"
        ),
    ]
    parameters: list[object] = []
    if scope == "exportable":
        conditions.extend(
            [
                "NOT restaurant.is_chain",
                "restaurant.is_permanently_closed IS DISTINCT FROM true",
                "EXISTS (SELECT 1 FROM restaurant_references reference "
                "WHERE reference.restaurant_id = restaurant.id)",
            ]
        )
    if provider is not None and exclude_checked_since is not None:
        conditions.append(
            "(enrichment.restaurant_id IS NULL OR enrichment.last_checked_at < %s)"
        )
        parameters.append(exclude_checked_since)

    provider_priority = (
        "CASE WHEN enrichment.restaurant_id IS NULL THEN 0 ELSE 1 END, "
        "enrichment.last_checked_at ASC NULLS FIRST, "
        if provider is not None
        else ""
    )

    query = f"""
        SELECT restaurant.id, restaurant.name, restaurant.address,
               restaurant.latitude, restaurant.longitude,
               CASE WHEN EXISTS (
                   SELECT 1 FROM restaurant_references reference
                   WHERE reference.restaurant_id = restaurant.id
               ) THEN 0 ELSE 1 END AS reference_priority
        FROM restaurants restaurant
        LEFT JOIN restaurant_aliases alias
          ON alias.alias_restaurant_id = restaurant.id
        {"LEFT JOIN restaurant_enrichments enrichment ON enrichment.restaurant_id = restaurant.id AND enrichment.provider = %s" if provider is not None else ""}
        WHERE {" AND ".join(conditions)}
        ORDER BY {provider_priority}reference_priority,
                 restaurant.last_seen DESC, restaurant.id
        {"LIMIT %s" if limit is not None else ""}
    """
    if provider is not None:
        parameters.insert(0, provider)
    if limit is not None:
        parameters.append(limit)
    rows = connection.execute(query, parameters).fetchall()
    return [
        RestaurantForEnrichment(
            id=row[0],
            name=row[1],
            address=row[2],
            latitude=float(row[3]),
            longitude=float(row[4]),
        )
        for row in rows
    ]


def start_run(connection: psycopg.Connection, provider: str, scope: str) -> int:
    run_id = connection.execute(
        """
        INSERT INTO enrichment_runs (provider, scope, started_at, status)
        VALUES (%s, %s, %s, 'running')
        RETURNING id
        """,
        (provider, scope, utcnow()),
    ).fetchone()[0]
    connection.commit()
    return run_id


def finish_run(
    connection: psycopg.Connection,
    run_id: int,
    result: EnrichmentResult,
    *,
    status: Literal["completed", "failed"] = "completed",
    error: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE enrichment_runs
        SET completed_at = %s, request_count = %s, matched_count = %s,
            unmatched_count = %s, ambiguous_count = %s, status = %s, error = %s
        WHERE id = %s
        """,
        (
            utcnow(),
            result.requests,
            result.matched,
            result.unmatched,
            result.ambiguous,
            status,
            error,
            run_id,
        ),
    )
    connection.commit()


def upsert_enrichment(
    connection: psycopg.Connection,
    *,
    restaurant_id: str,
    provider: str,
    match: ProviderMatch,
    checked_at: datetime,
    provider_release: str | None = None,
) -> None:
    place = match.place
    connection.execute(
        """
        INSERT INTO restaurant_enrichments (
            restaurant_id, provider, provider_place_id, match_status,
            match_method, match_score, last_checked_at, provider_release,
            primary_category, category_hierarchy, alternate_categories,
            operating_status, provider_confidence, address, phones, websites,
            attribution
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s
        )
        ON CONFLICT (restaurant_id, provider) DO UPDATE SET
            provider_place_id = excluded.provider_place_id,
            match_status = excluded.match_status,
            match_method = excluded.match_method,
            match_score = excluded.match_score,
            last_checked_at = excluded.last_checked_at,
            provider_release = excluded.provider_release,
            primary_category = excluded.primary_category,
            category_hierarchy = excluded.category_hierarchy,
            alternate_categories = excluded.alternate_categories,
            operating_status = excluded.operating_status,
            provider_confidence = excluded.provider_confidence,
            address = excluded.address,
            phones = excluded.phones,
            websites = excluded.websites,
            attribution = excluded.attribution
        """,
        (
            restaurant_id,
            provider,
            place.id if place else None,
            match.status,
            match.method,
            match.score,
            checked_at,
            provider_release,
            place.primary_category if provider == OVERTURE_PROVIDER and place else None,
            list(place.category_hierarchy) if provider == OVERTURE_PROVIDER and place else None,
            list(place.alternate_categories) if provider == OVERTURE_PROVIDER and place else None,
            place.operating_status if provider == OVERTURE_PROVIDER and place else None,
            place.confidence if provider == OVERTURE_PROVIDER and place else None,
            place.address if provider == OVERTURE_PROVIDER and place else None,
            list(place.phones) if provider == OVERTURE_PROVIDER and place else None,
            list(place.websites) if provider == OVERTURE_PROVIDER and place else None,
            Jsonb(place.attribution) if provider == OVERTURE_PROVIDER and place and place.attribution is not None else None,
        ),
    )


def summarize(matches: Sequence[ProviderMatch], *, requests_count: int = 0) -> EnrichmentResult:
    return EnrichmentResult(
        checked=len(matches),
        matched=sum(match.status == "matched" for match in matches),
        unmatched=sum(match.status == "unmatched" for match in matches),
        ambiguous=sum(match.status == "ambiguous" for match in matches),
        requests=requests_count,
    )


def enrich_overture(
    *,
    connection_url: str,
    release: str | None = None,
    places: Sequence[ProviderPlace] | None = None,
    checked_at: datetime | None = None,
) -> EnrichmentResult:
    release = release or latest_overture_release()
    places = list(places) if places is not None else fetch_overture_places(release)
    index = candidate_index(places)
    checked_at = checked_at or utcnow()
    with psycopg.connect(connection_url) as connection:
        run_id = start_run(connection, OVERTURE_PROVIDER, "all_current")
        try:
            restaurants = current_restaurants(connection)
            matches = []
            with connection.pipeline():
                for restaurant in restaurants:
                    match = choose_provider_match(
                        restaurant,
                        nearby_candidates(restaurant, index),
                    )
                    upsert_enrichment(
                        connection,
                        restaurant_id=restaurant.id,
                        provider=OVERTURE_PROVIDER,
                        match=match,
                        checked_at=checked_at,
                        provider_release=release,
                    )
                    matches.append(match)
            connection.commit()
            result = summarize(matches)
            finish_run(connection, run_id, result)
            return result
        except Exception as error:
            connection.rollback()
            result = EnrichmentResult(0, 0, 0, 0)
            finish_run(connection, run_id, result, status="failed", error=str(error)[:2000])
            raise


def google_places_from_payload(payload: dict[str, object]) -> list[ProviderPlace]:
    places = []
    for item in payload.get("places", []):
        if not isinstance(item, dict):
            continue
        location = item.get("location") or {}
        display_name = item.get("displayName") or {}
        if not isinstance(location, dict) or not isinstance(display_name, dict):
            continue
        if (
            not item.get("id")
            or not display_name.get("text")
            or location.get("latitude") is None
            or location.get("longitude") is None
        ):
            continue
        places.append(
            ProviderPlace(
                id=str(item["id"]),
                name=str(display_name["text"]),
                address=str(item.get("formattedAddress") or "") or None,
                latitude=float(location["latitude"]),
                longitude=float(location["longitude"]),
                primary_category=str(item.get("primaryType") or "") or None,
            )
        )
    return places


def search_google_place(
    restaurant: RestaurantForEnrichment,
    *,
    api_key: str,
    session: requests.Session,
    consume_request: Callable[[], None],
) -> list[ProviderPlace]:
    body = {
        "textQuery": f"{restaurant.name}, {restaurant.address or 'New York, NY'}",
        "pageSize": 5,
        "languageCode": "en",
        "locationBias": {
            "circle": {
                "center": {
                    "latitude": restaurant.latitude,
                    "longitude": restaurant.longitude,
                },
                "radius": 200.0,
            }
        },
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": (
            "places.id,places.displayName,places.formattedAddress,"
            "places.location,places.primaryType"
        ),
    }
    for attempt in range(3):
        consume_request()
        response = session.post(GOOGLE_TEXT_SEARCH_URL, json=body, headers=headers, timeout=30)
        if response.status_code not in {429, 500, 502, 503, 504}:
            response.raise_for_status()
            return google_places_from_payload(response.json())
        if attempt < 2:
            time.sleep(min(2**attempt, 5))
    response.raise_for_status()
    return []


def month_start(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def google_requests_this_month(connection: psycopg.Connection, now: datetime) -> int:
    return connection.execute(
        """
        SELECT coalesce(sum(request_count), 0)
        FROM enrichment_runs
        WHERE provider = 'google_places' AND started_at >= %s
        """,
        (month_start(now),),
    ).fetchone()[0]


def enrich_google(
    *,
    connection_url: str,
    api_key: str,
    scope: Literal["exportable", "backlog"] = "backlog",
    monthly_limit: int = 4500,
    checked_at: datetime | None = None,
    session: requests.Session | None = None,
) -> EnrichmentResult:
    checked_at = checked_at or utcnow()
    session = session or requests.Session()
    with psycopg.connect(connection_url) as connection:
        used = google_requests_this_month(connection, checked_at)
        remaining = max(0, monthly_limit - used)
        run_id = start_run(connection, GOOGLE_PROVIDER, scope)
        matches: list[ProviderMatch] = []
        request_count = 0

        def consume_request() -> None:
            nonlocal request_count
            if request_count >= remaining:
                raise RuntimeError("Google Places monthly request limit reached")
            request_count += 1
            connection.execute(
                "UPDATE enrichment_runs SET request_count = %s WHERE id = %s",
                (request_count, run_id),
            )
            connection.commit()

        try:
            if remaining:
                restaurants = current_restaurants(
                    connection,
                    provider=GOOGLE_PROVIDER,
                    scope=scope,
                    exclude_checked_since=month_start(checked_at),
                    limit=remaining,
                )
                for restaurant in restaurants:
                    if request_count >= remaining:
                        break
                    candidates = search_google_place(
                        restaurant,
                        api_key=api_key,
                        session=session,
                        consume_request=consume_request,
                    )
                    match = choose_provider_match(restaurant, candidates)
                    upsert_enrichment(
                        connection,
                        restaurant_id=restaurant.id,
                        provider=GOOGLE_PROVIDER,
                        match=match,
                        checked_at=checked_at,
                    )
                    connection.commit()
                    matches.append(match)
            result = summarize(matches, requests_count=request_count)
            finish_run(connection, run_id, result)
            return result
        except Exception as error:
            connection.rollback()
            result = summarize(matches, requests_count=request_count)
            finish_run(connection, run_id, result, status="failed", error=str(error)[:2000])
            raise


def print_result(provider: str, result: EnrichmentResult) -> None:
    print(
        f"{provider}: checked {result.checked}; matched {result.matched}; "
        f"unmatched {result.unmatched}; ambiguous {result.ambiguous}; "
        f"requests {result.requests}."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="provider", required=True)
    overture_parser = subparsers.add_parser("overture")
    overture_parser.add_argument("--release", default=optional_environment("OVERTURE_RELEASE"))
    google_parser = subparsers.add_parser("google")
    google_parser.add_argument("--scope", choices=("exportable", "backlog"), default="backlog")
    google_parser.add_argument("--monthly-limit", type=int, default=google_places_monthly_limit())
    args = parser.parse_args()

    if args.provider == OVERTURE_PROVIDER:
        result = enrich_overture(connection_url=database_url(), release=args.release)
    else:
        result = enrich_google(
            connection_url=database_url(),
            api_key=required_environment("GOOGLE_PLACES_SERVER_KEY"),
            scope=args.scope,
            monthly_limit=args.monthly_limit,
        )
    print_result(args.provider, result)


if __name__ == "__main__":
    main()
