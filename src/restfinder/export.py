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
                    restaurant.cuisine,
                    restaurant.address,
                    restaurant.phone,
                    restaurant.latitude AS lat,
                    restaurant.longitude AS lon,
                    restaurant.first_seen,
                    restaurant.last_seen
                FROM restaurants restaurant
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
        exported.append(
            {
                "id": row["id"],
                "source": row["source"],
                "name": row["name"],
                "type": row["type"],
                "cuisine": row["cuisine"],
                "address": row["address"],
                "phone": row["phone"],
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
