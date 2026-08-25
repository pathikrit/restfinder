"""Export the curated current restaurant set for the static frontend."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

import psycopg
from psycopg.rows import dict_row

from restfinder.config import database_url
from restfinder.enrichment import (
    category_label,
    overture_cuisine,
    overture_restaurant_type,
)
from restfinder.names import display_name

OUTPUT_PATH = Path(".site/data/nyc.json")


def isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def export_rows(*, connection_url: str) -> list[dict[str, Any]]:
    with psycopg.connect(connection_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    restaurant.id,
                    restaurant.source,
                    restaurant.name,
                    restaurant.type,
                    restaurant.cuisine AS canonical_cuisine,
                    restaurant.address AS canonical_address,
                    restaurant.phone AS canonical_phone,
                    restaurant.latitude AS lat,
                    restaurant.longitude AS lon,
                    restaurant.first_seen,
                    restaurant.last_seen,
                    overture.primary_category,
                    overture.category_hierarchy,
                    overture.operating_status,
                    overture.address AS overture_address,
                    overture.phones[1] AS overture_phone,
                    overture.websites[1] AS website,
                    google.provider_place_id AS google_place_id
                FROM restaurants restaurant
                LEFT JOIN restaurant_aliases alias
                  ON alias.alias_restaurant_id = restaurant.id
                LEFT JOIN restaurant_enrichments overture
                  ON overture.restaurant_id = restaurant.id
                 AND overture.provider = 'overture'
                 AND overture.match_status = 'matched'
                LEFT JOIN restaurant_enrichments google
                  ON google.restaurant_id = restaurant.id
                 AND google.provider = 'google_places'
                 AND google.match_status = 'matched'
                WHERE (
                    restaurant.source <> 'nyc_dohmh'
                    OR restaurant.last_seen = (
                        SELECT max(current.last_seen)
                        FROM restaurants current
                        WHERE current.source = restaurant.source
                    )
                )
                  AND NOT restaurant.is_chain
                  AND restaurant.is_permanently_closed IS DISTINCT FROM true
                  AND alias.alias_restaurant_id IS NULL
                  AND restaurant.latitude IS NOT NULL
                  AND restaurant.longitude IS NOT NULL
                  AND EXISTS (
                      SELECT 1 FROM restaurant_references reference
                      WHERE reference.restaurant_id = restaurant.id
                  )
                ORDER BY restaurant.id
                """,
            )
            rows = cursor.fetchall()
            if not rows:
                return []

            ids = [row["id"] for row in rows]
            cursor.execute(
                """
                SELECT restaurant_id, reference, added_at
                FROM restaurant_references
                WHERE restaurant_id = ANY(%s)
                ORDER BY restaurant_id, added_at, reference
                """,
                (ids,),
            )
            references: dict[str, list[dict[str, str]]] = {restaurant_id: [] for restaurant_id in ids}
            for reference in cursor.fetchall():
                references[reference["restaurant_id"]].append(
                    {
                        "reference": reference["reference"],
                        "added_at": isoformat(reference["added_at"]),
                    }
                )

    exported = []
    for row in rows:
        overture_cuisine_value = overture_cuisine(row["category_hierarchy"])
        overture_type_value = overture_restaurant_type(
            row["primary_category"], row["category_hierarchy"]
        )
        cuisine = row["canonical_cuisine"] or overture_cuisine_value
        address = row["canonical_address"] or row["overture_address"]
        phone = row["canonical_phone"] or row["overture_phone"]
        detail_sources = {
            key: source
            for key, source in (
                ("cuisine", row["source"] if row["canonical_cuisine"] else "overture" if overture_cuisine_value else None),
                ("address", row["source"] if row["canonical_address"] else "overture" if row["overture_address"] else None),
                ("phone", row["source"] if row["canonical_phone"] else "overture" if row["overture_phone"] else None),
                ("website", "overture" if row["website"] else None),
                ("operating_status", "overture" if row["operating_status"] else None),
                ("place_category", "overture" if row["primary_category"] else None),
            )
            if source
        }
        exported.append(
            {
                "id": row["id"],
                "source": row["source"],
                "name": display_name(row["name"]),
                "type": row["type"] or overture_type_value or "Restaurant",
                "cuisine": cuisine,
                "address": address,
                "phone": phone,
                "website": row["website"],
                "operating_status": row["operating_status"],
                "place_category": category_label(row["primary_category"]),
                "google_place_id": row["google_place_id"],
                "detail_sources": detail_sources,
                "lat": row["lat"],
                "lon": row["lon"],
                "first_seen": isoformat(row["first_seen"]),
                "last_seen": isoformat(row["last_seen"]),
                "references": references[row["id"]],
            }
        )
    return exported


def write_export(rows: list[dict[str, Any]], path: Path = OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as temporary:
        json.dump(rows, temporary, indent=2, ensure_ascii=False)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def main() -> None:
    rows = export_rows(connection_url=database_url())
    write_export(rows)
    print(f"Exported {len(rows)} restaurants to {OUTPUT_PATH}.")


if __name__ == "__main__":
    main()
