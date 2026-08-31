#!/usr/bin/env python3
"""Render a consolidated, pre-import Markdown review from social-post drafts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse


def parse_lines(value: str) -> set[int]:
    return {int(item) for item in value.split(",") if item.strip()}


def escape(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def post_id(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if not parts:
        raise ValueError(f"URL has no post ID: {url}")
    return parts[-1]


def render(
    inventory: Path,
    draft_directory: Path,
    *,
    existing_lines: set[int],
    excluded_lines: set[int],
) -> str:
    urls = [line.strip() for line in inventory.read_text().splitlines() if line.strip()]
    rows: list[str] = []
    missing: list[tuple[int, str]] = []
    existing: list[tuple[int, str]] = []
    excluded: list[tuple[int, str]] = []
    excluded_venue_rows: list[str] = []
    fallback_ids: set[str] = set()
    draft_count = selected_count = fallback_count = 0

    for line_number, url in enumerate(urls, 1):
        if line_number in existing_lines:
            existing.append((line_number, url))
            continue
        draft_path = draft_directory / f"instagram-{post_id(url)}.json"
        if not draft_path.exists():
            missing.append((line_number, url))
            continue
        payload = json.loads(draft_path.read_text())
        selected = [venue for venue in payload["venues"] if venue.get("selected", True)]
        for venue in payload["venues"]:
            if venue.get("selected", True):
                continue
            resolution = venue.get("resolution") or {}
            excluded_venue_rows.append(
                "| "
                + " | ".join(
                    escape(value)
                    for value in (
                        f"{line_number}. {url}",
                        venue.get("name"),
                        resolution.get("status"),
                        resolution.get("address") or venue.get("address") or "",
                    )
                )
                + " |"
            )
        if line_number in excluded_lines or not selected:
            excluded.append((line_number, url))
            continue
        draft_count += 1
        selected_count += len(selected)
        for venue_index, venue in enumerate(selected, 1):
            resolution = venue["resolution"]
            if resolution["status"] == "fallback":
                fallback_count += 1
                fallback_ids.add(resolution["fallback_id"])
                action = f"fallback `{resolution['fallback_id']}`"
            else:
                action = f"match `{resolution['restaurant_id']}`"
            proposed_type = venue["type"]
            current_type = resolution.get("current_type")
            type_text = (
                f"{current_type} → {proposed_type}"
                if current_type and current_type != proposed_type
                else proposed_type
            )
            address = resolution.get("address") or venue.get("address") or ""
            source_label = f"{line_number}. {url}" if venue_index == 1 else ""
            rows.append(
                "| "
                + " | ".join(
                    escape(value)
                    for value in (
                        source_label,
                        venue.get("rank") or venue_index,
                        venue.get("name"),
                        type_text,
                        action,
                        address,
                    )
                )
                + " |"
            )

    lines = [
        "# RestFinder social-post batch review",
        "",
        f"- Supplied URLs: {len(urls)}",
        f"- Importable drafts: {draft_count}",
        f"- Selected venue rows: {selected_count}",
        f"- Proposed fallback rows: {fallback_count}",
        f"- Unique fallback venues: {len(fallback_ids)}",
        f"- Existing sources skipped: {len(existing)}",
        f"- Excluded reviewed sources: {len(excluded)}",
        f"- Excluded venue rows: {len(excluded_venue_rows)}",
        f"- Sources without a draft: {len(missing)}",
        "",
        "No database writes have been authorized by this review artifact.",
        "",
        "## Importable sources",
        "",
        "| Source | # | Venue | Type | Proposed action | Address |",
        "|---|---:|---|---|---|---|",
        *rows,
        "",
        "## Existing sources skipped",
        "",
        *[f"- {line}. {url}" for line, url in existing],
        "",
        "## Reviewed sources excluded",
        "",
        *[f"- {line}. {url}" for line, url in excluded],
        "",
        "## Excluded venue rows",
        "",
        "| Source | Venue | Prior resolution | Address |",
        "|---|---|---|---|",
        *excluded_venue_rows,
        "",
        "## Sources without a draft",
        "",
        *[
            f"- {line}. {url} — analysis failed, timed out, or public media was unavailable"
            for line, url in missing
        ],
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--draft-directory", type=Path, required=True)
    parser.add_argument("--existing-lines", default="")
    parser.add_argument("--excluded-lines", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = render(
        args.inventory,
        args.draft_directory,
        existing_lines=parse_lines(args.existing_lines),
        excluded_lines=parse_lines(args.excluded_lines),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output)


if __name__ == "__main__":
    main()
