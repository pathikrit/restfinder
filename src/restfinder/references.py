"""Import checked-in restaurant reference manifests."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Iterable

import psycopg

from restfinder.config import database_url


@dataclass(frozen=True, slots=True)
class ReferenceManifest:
    reference: str
    added_at: datetime
    restaurant_ids: tuple[str, ...]


def parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("added_at must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("added_at must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError("added_at must include a timezone")
    return parsed


def load_manifest(path: Path) -> ReferenceManifest:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read {path}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{path}: manifest must be a JSON object")

    reference = data.get("reference")
    restaurant_ids = data.get("restaurant_ids")
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError(f"{path}: reference must be a non-empty string")
    if not isinstance(restaurant_ids, list) or not restaurant_ids:
        raise ValueError(f"{path}: restaurant_ids must be a non-empty array")
    if not all(isinstance(value, str) and value.strip() for value in restaurant_ids):
        raise ValueError(f"{path}: every restaurant ID must be a non-empty string")
    if len(restaurant_ids) != len(set(restaurant_ids)):
        raise ValueError(f"{path}: restaurant_ids contains duplicates")

    return ReferenceManifest(
        reference=reference.strip(),
        added_at=parse_timestamp(data.get("added_at")),
        restaurant_ids=tuple(restaurant_ids),
    )


def import_manifests(manifests: Iterable[ReferenceManifest], *, connection_url: str) -> int:
    manifests = list(manifests)
    rows = [
        (restaurant_id, manifest.reference, manifest.added_at)
        for manifest in manifests
        for restaurant_id in manifest.restaurant_ids
    ]
    if not rows:
        return 0

    requested_ids = sorted({row[0] for row in rows})
    with psycopg.connect(connection_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM restaurants WHERE id = ANY(%s)",
                (requested_ids,),
            )
            existing_ids = {row[0] for row in cursor.fetchall()}
            missing = sorted(set(requested_ids) - existing_ids)
            if missing:
                raise ValueError(f"Unknown restaurant IDs: {', '.join(missing)}")
            cursor.executemany(
                """
                INSERT INTO restaurant_references (restaurant_id, reference, added_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (restaurant_id, reference)
                DO UPDATE SET added_at = excluded.added_at
                """,
                rows,
            )
    return len(rows)


def manifest_paths(selected: str | None) -> list[Path]:
    if selected:
        return [Path(selected)]
    return sorted(Path("imports").glob("*.json"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="one manifest; omit to import imports/*.json")
    args = parser.parse_args()

    paths = manifest_paths(args.path)
    if not paths:
        print("No reference manifests found.")
        return
    manifests = [load_manifest(path) for path in paths]
    count = import_manifests(manifests, connection_url=database_url())
    print(f"Imported {count} restaurant references from {len(paths)} manifest(s).")


if __name__ == "__main__":
    main()
