"""Prepare and apply explicit restaurant duplicate decisions."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from math import floor
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from restfinder.config import database_url
from restfinder.matching import distance_meters, fuzzy_name_score, normalize_match_name

DEFAULT_DRAFT = Path(".restfinder/duplicate-review.json")
DEFAULT_MANIFEST_DIRECTORY = Path("imports/merges")


@dataclass(frozen=True, slots=True)
class DuplicateRestaurant:
    id: str
    source: str
    name: str
    address: str | None
    latitude: float
    longitude: float


def utc_iso(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).isoformat().replace("+00:00", "Z")


def pair_key(first_id: str, second_id: str) -> tuple[str, str]:
    if first_id == second_id:
        raise ValueError("A duplicate pair must contain two different restaurant IDs")
    return tuple(sorted((first_id, second_id)))


def reviewed_pairs(directory: Path = DEFAULT_MANIFEST_DIRECTORY) -> set[tuple[str, str]]:
    reviewed: set[tuple[str, str]] = set()
    if not directory.exists():
        return reviewed
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for decision in payload.get("decisions", []):
            reviewed.add(pair_key(decision["first_id"], decision["second_id"]))
    return reviewed


def suggested_canonical(first: DuplicateRestaurant, second: DuplicateRestaurant) -> str:
    def rank(restaurant: DuplicateRestaurant) -> tuple[int, str]:
        return (0 if restaurant.source == "nyc_dohmh" else 1, restaurant.id)

    return min((first, second), key=rank).id


def _cell(restaurant: DuplicateRestaurant) -> tuple[int, int]:
    size = 0.002
    return floor(restaurant.latitude / size), floor(restaurant.longitude / size)


def nearby_duplicate_pairs(
    restaurants: Iterable[DuplicateRestaurant],
) -> dict[tuple[str, str], dict[str, object]]:
    restaurants = list(restaurants)
    by_cell: dict[tuple[int, int], list[DuplicateRestaurant]] = {}
    for restaurant in restaurants:
        by_cell.setdefault(_cell(restaurant), []).append(restaurant)

    pairs: dict[tuple[str, str], dict[str, object]] = {}
    for restaurant in restaurants:
        latitude_cell, longitude_cell = _cell(restaurant)
        for latitude_offset in (-1, 0, 1):
            for longitude_offset in (-1, 0, 1):
                for candidate in by_cell.get(
                    (latitude_cell + latitude_offset, longitude_cell + longitude_offset),
                    (),
                ):
                    if candidate.id <= restaurant.id:
                        continue
                    distance = distance_meters(
                        restaurant.latitude,
                        restaurant.longitude,
                        candidate.latitude,
                        candidate.longitude,
                    )
                    if distance > 100:
                        continue
                    score = fuzzy_name_score(restaurant.name, candidate.name)
                    if score < 0.88:
                        continue
                    key = pair_key(restaurant.id, candidate.id)
                    pairs[key] = {
                        "distance_meters": round(distance, 1),
                        "name_score": round(score, 4),
                        "match_method": (
                            "exact_nearby"
                            if normalize_match_name(restaurant.name)
                            == normalize_match_name(candidate.name)
                            else "fuzzy_nearby"
                        ),
                        "provider_ids": [],
                    }
    return pairs


def load_duplicate_restaurants(connection: psycopg.Connection) -> list[DuplicateRestaurant]:
    rows = connection.execute(
        """
        SELECT restaurant.id, restaurant.source, restaurant.name,
               restaurant.address, restaurant.latitude, restaurant.longitude
        FROM restaurants restaurant
        LEFT JOIN restaurant_aliases alias
          ON alias.alias_restaurant_id = restaurant.id
        WHERE alias.alias_restaurant_id IS NULL
          AND restaurant.latitude IS NOT NULL
          AND restaurant.longitude IS NOT NULL
          AND (restaurant.source <> 'nyc_dohmh' OR restaurant.last_seen = (
              SELECT max(current.last_seen) FROM restaurants current
              WHERE current.source = restaurant.source
          ))
        ORDER BY restaurant.id
        """
    ).fetchall()
    return [DuplicateRestaurant(*row) for row in rows]


def duplicate_candidates(
    connection: psycopg.Connection,
    *,
    ignored_pairs: set[tuple[str, str]] | None = None,
) -> list[dict[str, object]]:
    restaurants = load_duplicate_restaurants(connection)
    by_id = {restaurant.id: restaurant for restaurant in restaurants}
    evidence = nearby_duplicate_pairs(restaurants)
    shared_rows = connection.execute(
        """
        SELECT first.restaurant_id, second.restaurant_id,
               first.provider, first.provider_place_id
        FROM restaurant_enrichments first
        JOIN restaurant_enrichments second
          ON second.provider = first.provider
         AND second.provider_place_id = first.provider_place_id
         AND second.restaurant_id > first.restaurant_id
        LEFT JOIN restaurant_aliases first_alias
          ON first_alias.alias_restaurant_id = first.restaurant_id
        LEFT JOIN restaurant_aliases second_alias
          ON second_alias.alias_restaurant_id = second.restaurant_id
        WHERE first.provider_place_id IS NOT NULL
          AND first_alias.alias_restaurant_id IS NULL
          AND second_alias.alias_restaurant_id IS NULL
        """
    ).fetchall()
    for first_id, second_id, provider, provider_place_id in shared_rows:
        if first_id not in by_id or second_id not in by_id:
            continue
        key = pair_key(first_id, second_id)
        item = evidence.setdefault(
            key,
            {
                "distance_meters": round(
                    distance_meters(
                        by_id[first_id].latitude,
                        by_id[first_id].longitude,
                        by_id[second_id].latitude,
                        by_id[second_id].longitude,
                    ),
                    1,
                ),
                "name_score": round(fuzzy_name_score(by_id[first_id].name, by_id[second_id].name), 4),
                "match_method": "shared_provider_id",
                "provider_ids": [],
            },
        )
        item["provider_ids"].append(
            {"provider": provider, "provider_place_id": provider_place_id}
        )

    ignored_pairs = ignored_pairs or set()
    candidates = []
    for key in sorted(evidence):
        if key in ignored_pairs:
            continue
        first, second = by_id[key[0]], by_id[key[1]]
        candidates.append(
            {
                "first_id": first.id,
                "first_name": first.name,
                "first_source": first.source,
                "first_address": first.address,
                "second_id": second.id,
                "second_name": second.name,
                "second_source": second.source,
                "second_address": second.address,
                **evidence[key],
                "suggested_canonical_id": suggested_canonical(first, second),
                "decision": "defer",
                "canonical_restaurant_id": None,
                "reason": "",
            }
        )
    return candidates


def prepare_review(
    *,
    connection_url: str,
    output_path: Path = DEFAULT_DRAFT,
    manifest_directory: Path = DEFAULT_MANIFEST_DIRECTORY,
) -> int:
    with psycopg.connect(connection_url) as connection:
        candidates = duplicate_candidates(
            connection,
            ignored_pairs=reviewed_pairs(manifest_directory),
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps({"generated_at": utc_iso(), "decisions": candidates}, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(candidates)


def _enrichment_rank(row: dict[str, object]) -> tuple[bool, bool, float, datetime]:
    return (
        row["reviewed_at"] is not None,
        row["match_status"] == "matched",
        float(row["match_score"] or 0),
        row["last_checked_at"],
    )


def merge_restaurant(
    connection: psycopg.Connection,
    *,
    alias_id: str,
    canonical_id: str,
    reviewed_at: datetime,
    reason: str,
) -> None:
    if alias_id == canonical_id:
        raise ValueError("Alias and canonical restaurant must differ")
    existing = connection.execute(
        "SELECT canonical_restaurant_id FROM restaurant_aliases WHERE alias_restaurant_id = %s",
        (alias_id,),
    ).fetchone()
    if existing:
        if existing[0] == canonical_id:
            return
        raise ValueError(f"{alias_id} is already aliased to {existing[0]}")
    if connection.execute(
        "SELECT 1 FROM restaurant_aliases WHERE alias_restaurant_id = %s",
        (canonical_id,),
    ).fetchone():
        raise ValueError(f"Canonical restaurant {canonical_id} is itself an alias")
    found = {
        row[0]
        for row in connection.execute(
            "SELECT id FROM restaurants WHERE id = ANY(%s)",
            ([alias_id, canonical_id],),
        ).fetchall()
    }
    missing = {alias_id, canonical_id} - found
    if missing:
        raise ValueError(f"Unknown restaurant IDs: {', '.join(sorted(missing))}")

    connection.execute(
        """
        INSERT INTO restaurant_references (restaurant_id, reference, added_at)
        SELECT %s, reference, added_at
        FROM restaurant_references
        WHERE restaurant_id = %s
        ON CONFLICT (restaurant_id, reference) DO UPDATE
        SET added_at = least(restaurant_references.added_at, excluded.added_at)
        """,
        (canonical_id, alias_id),
    )
    connection.execute("DELETE FROM restaurant_references WHERE restaurant_id = %s", (alias_id,))

    with connection.cursor(row_factory=dict_row) as cursor:
        alias_rows = cursor.execute(
            "SELECT * FROM restaurant_enrichments WHERE restaurant_id = %s",
            (alias_id,),
        ).fetchall()
    for alias_row in alias_rows:
        with connection.cursor(row_factory=dict_row) as cursor:
            canonical_row = cursor.execute(
                """
                SELECT * FROM restaurant_enrichments
                WHERE restaurant_id = %s AND provider = %s
                """,
                (canonical_id, alias_row["provider"]),
            ).fetchone()
        if canonical_row is None:
            connection.execute(
                """
                UPDATE restaurant_enrichments SET restaurant_id = %s
                WHERE restaurant_id = %s AND provider = %s
                """,
                (canonical_id, alias_id, alias_row["provider"]),
            )
        elif _enrichment_rank(alias_row) > _enrichment_rank(canonical_row):
            connection.execute(
                "DELETE FROM restaurant_enrichments WHERE restaurant_id = %s AND provider = %s",
                (canonical_id, alias_row["provider"]),
            )
            connection.execute(
                """
                UPDATE restaurant_enrichments SET restaurant_id = %s
                WHERE restaurant_id = %s AND provider = %s
                """,
                (canonical_id, alias_id, alias_row["provider"]),
            )
        else:
            connection.execute(
                "DELETE FROM restaurant_enrichments WHERE restaurant_id = %s AND provider = %s",
                (alias_id, alias_row["provider"]),
            )

    connection.execute(
        """
        UPDATE restaurant_aliases SET canonical_restaurant_id = %s
        WHERE canonical_restaurant_id = %s
        """,
        (canonical_id, alias_id),
    )
    connection.execute(
        """
        INSERT INTO restaurant_aliases (
            alias_restaurant_id, canonical_restaurant_id, reviewed_at, reason
        ) VALUES (%s, %s, %s, %s)
        """,
        (alias_id, canonical_id, reviewed_at, reason),
    )


def apply_manifest(*, connection_url: str, manifest_path: Path) -> tuple[int, int]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    reviewed_at = datetime.fromisoformat(
        payload.get("reviewed_at", payload.get("generated_at", ""))
    )
    merged = kept_separate = 0
    with psycopg.connect(connection_url) as connection:
        for decision in payload.get("decisions", []):
            action = decision.get("decision")
            if action == "defer":
                continue
            if action == "keep_separate":
                kept_separate += 1
                continue
            if action != "merge":
                raise ValueError(f"Unsupported duplicate decision: {action!r}")
            canonical_id = decision.get("canonical_restaurant_id")
            if canonical_id not in {decision["first_id"], decision["second_id"]}:
                raise ValueError("A merge canonical_restaurant_id must be one of the reviewed pair")
            alias_id = (
                decision["second_id"]
                if canonical_id == decision["first_id"]
                else decision["first_id"]
            )
            reason = str(decision.get("reason") or "Reviewed duplicate")
            merge_restaurant(
                connection,
                alias_id=alias_id,
                canonical_id=canonical_id,
                reviewed_at=reviewed_at,
                reason=reason,
            )
            merged += 1
        connection.commit()
    return merged, kept_separate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--output", type=Path, default=DEFAULT_DRAFT)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        count = prepare_review(connection_url=database_url(), output_path=args.output)
        print(f"Wrote {count} duplicate candidates to {args.output}.")
    else:
        merged, kept = apply_manifest(connection_url=database_url(), manifest_path=args.manifest)
        print(f"Applied {merged} merges; recorded {kept} keep-separate decisions.")


if __name__ == "__main__":
    main()
