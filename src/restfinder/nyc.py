"""NYC DOHMH restaurant snapshot ingestion."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Iterable

import psycopg
import requests
from requests.adapters import HTTPAdapter
import truststore
from urllib3.util.retry import Retry

from restfinder.config import database_url, nyc_open_data_app_token

truststore.inject_into_ssl()

NYC_SOCRATA_URL = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"
SOURCE = "nyc_dohmh"
PAGE_SIZE = 50_000
SELECT = ", ".join(
    (
        "camis",
        "max(dba) as name",
        "max(building) as building",
        "max(street) as street",
        "max(boro) as boro",
        "max(zipcode) as zipcode",
        "max(phone) as phone",
        "max(cuisine_description) as cuisine",
        "max(latitude) as latitude",
        "max(longitude) as longitude",
        "max(record_date) as source_snapshot_at",
    )
)


@dataclass(frozen=True, slots=True)
class Restaurant:
    id: str
    source: str
    name: str
    cuisine: str | None
    address: str | None
    phone: str | None
    latitude: float | None
    longitude: float | None
    is_chain: bool = False


def clean(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def build_address(row: dict[str, Any]) -> str | None:
    building = clean(row.get("building"))
    street = clean(row.get("street"))
    boro = clean(row.get("boro"))
    zipcode = clean(row.get("zipcode"))

    street_address = " ".join(part for part in (building, street) if part)
    parts = [part for part in (street_address or None, boro, zipcode) if part]
    return ", ".join(parts) or None


def optional_float(value: Any) -> float | None:
    text = clean(value)
    return float(text) if text is not None else None


def transform_row(row: dict[str, Any]) -> Restaurant:
    camis = clean(row.get("camis"))
    if not camis:
        raise ValueError("NYC row is missing CAMIS")
    return Restaurant(
        id=f"{SOURCE}:{camis}",
        source=SOURCE,
        name=clean(row.get("name")) or "Unnamed establishment",
        cuisine=clean(row.get("cuisine")),
        address=build_address(row),
        phone=clean(row.get("phone")),
        latitude=optional_float(row.get("latitude")),
        longitude=optional_float(row.get("longitude")),
    )


def normalize_chain_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).casefold()


def mark_chains(restaurants: Iterable[Restaurant]) -> list[Restaurant]:
    restaurants = list(restaurants)
    counts = Counter(normalize_chain_name(item.name) for item in restaurants)
    return [
        replace(item, is_chain=counts[normalize_chain_name(item.name)] > 5)
        for item in restaurants
    ]


def api_session() -> requests.Session:
    retry = Retry(
        total=4,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "RestFinder/0.0.1"
    token = nyc_open_data_app_token()
    if token:
        session.headers["X-App-Token"] = token
    return session


def source_count(session: requests.Session) -> int:
    response = session.get(
        NYC_SOCRATA_URL,
        params={"$select": "count(distinct camis) as count"},
        timeout=120,
    )
    response.raise_for_status()
    return int(response.json()[0]["count"])


def fetch_snapshot(session: requests.Session | None = None) -> tuple[list[Restaurant], str]:
    session = session or api_session()
    count_before = source_count(session)
    raw_rows: list[dict[str, Any]] = []
    last_camis: str | None = None

    while True:
        params = {
            "$select": SELECT,
            "$group": "camis",
            "$order": "camis",
            "$limit": PAGE_SIZE,
        }
        if last_camis is not None:
            params["$where"] = f"camis > '{last_camis}'"
        response = session.get(NYC_SOCRATA_URL, params=params, timeout=120)
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, list):
            raise ValueError("NYC API returned a non-list response")
        if not page:
            break
        raw_rows.extend(page)
        next_camis = clean(page[-1].get("camis"))
        if not next_camis or next_camis == last_camis:
            raise ValueError("NYC pagination did not advance")
        last_camis = next_camis
        if len(page) < PAGE_SIZE:
            break

    count_after = source_count(session)
    if count_before != count_after or len(raw_rows) != count_after:
        raise ValueError(
            "NYC snapshot changed or was incomplete during fetch "
            f"(before={count_before}, fetched={len(raw_rows)}, after={count_after})"
        )

    ids = [clean(row.get("camis")) for row in raw_rows]
    if len(ids) != len(set(ids)):
        raise ValueError("NYC snapshot contains duplicate CAMIS values")
    snapshot_values = {clean(row.get("source_snapshot_at")) for row in raw_rows}
    if None in snapshot_values:
        raise ValueError("NYC snapshot contains a missing record date")
    snapshot_times = sorted(datetime.fromisoformat(value) for value in snapshot_values if value)
    if not snapshot_times or snapshot_times[-1] - snapshot_times[0] > timedelta(hours=1):
        raise ValueError(f"NYC snapshot spans inconsistent record dates: {sorted(snapshot_values)}")

    return mark_chains(transform_row(row) for row in raw_rows), snapshot_times[-1].isoformat()


def upsert_snapshot(
    restaurants: Iterable[Restaurant],
    *,
    connection_url: str,
    observed_at: datetime | None = None,
) -> tuple[int, int]:
    restaurants = list(restaurants)
    if not restaurants:
        raise ValueError("Refusing to upsert an empty restaurant snapshot")
    observed_at = observed_at or datetime.now(timezone.utc)

    with psycopg.connect(connection_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TEMP TABLE incoming_restaurants (
                    id text PRIMARY KEY,
                    source text NOT NULL,
                    name text NOT NULL,
                    cuisine text,
                    address text,
                    phone text,
                    latitude double precision,
                    longitude double precision,
                    is_chain boolean NOT NULL
                ) ON COMMIT DROP
                """
            )
            with cursor.copy(
                """
                COPY incoming_restaurants
                    (id, source, name, cuisine, address, phone, latitude, longitude, is_chain)
                FROM STDIN
                """
            ) as copy:
                for item in restaurants:
                    copy.write_row(
                        (
                            item.id,
                            item.source,
                            item.name,
                            item.cuisine,
                            item.address,
                            item.phone,
                            item.latitude,
                            item.longitude,
                            item.is_chain,
                        )
                    )

            cursor.execute(
                """
                SELECT count(*)
                FROM incoming_restaurants incoming
                JOIN restaurants existing USING (id)
                """
            )
            existing = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO restaurants (
                    id, source, name, cuisine, address, phone, latitude, longitude,
                    first_seen, last_seen, is_chain
                )
                SELECT
                    id, source, name, cuisine, address, phone, latitude, longitude,
                    %(observed_at)s, %(observed_at)s, is_chain
                FROM incoming_restaurants
                ON CONFLICT (id) DO UPDATE SET
                    source = excluded.source,
                    name = excluded.name,
                    cuisine = excluded.cuisine,
                    address = excluded.address,
                    phone = excluded.phone,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude,
                    last_seen = excluded.last_seen,
                    is_chain = excluded.is_chain
                """,
                {"observed_at": observed_at},
            )
    return len(restaurants) - existing, existing


def main() -> None:
    restaurants, source_snapshot = fetch_snapshot()
    inserted, updated = upsert_snapshot(restaurants, connection_url=database_url())
    chains = sum(item.is_chain for item in restaurants)
    print(
        f"NYC snapshot {source_snapshot}: {len(restaurants)} restaurants "
        f"({inserted} inserted, {updated} updated, {chains} chain locations)"
    )


if __name__ == "__main__":
    main()
