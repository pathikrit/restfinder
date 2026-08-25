"""Shared restaurant-name, location, and type matching helpers."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from math import atan2, cos, floor, radians, sin, sqrt
from typing import Iterable, Protocol
import unicodedata


RESTAURANT_TYPES = frozenset(
    {
        "Restaurant",
        "Bars",
        "Coffee Shops",
        "Dessert",
        "Fast Food",
        "Hidden / Speakeasy",
    }
)
TYPE_PRIORITY = {
    "Restaurant": 1,
    "Fast Food": 2,
    "Coffee Shops": 2,
    "Dessert": 3,
    "Bars": 4,
    "Hidden / Speakeasy": 5,
}
MATCH_DISTANCE_METERS = 100


class MatchablePlace(Protocol):
    source_id: str
    name: str
    latitude: float
    longitude: float


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
    fuzzy: int = 0
    ambiguous_source_ids: frozenset[str] = frozenset()


def normalize_name(name: str) -> str:
    return " ".join(name.casefold().split())


def normalize_match_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name.casefold())
    return " ".join(
        "".join(
            character if character.isalnum() else " " for character in decomposed
        ).split()
    )


def compact_match_name(name: str) -> str:
    return normalize_match_name(name).replace(" ", "")


def fuzzy_name_score(first: str, second: str) -> float:
    first_normalized = normalize_match_name(first)
    second_normalized = normalize_match_name(second)
    if compact_match_name(first) == compact_match_name(second):
        return 1.0
    direct = SequenceMatcher(None, first_normalized, second_normalized).ratio()
    token_sorted = SequenceMatcher(
        None,
        " ".join(sorted(first_normalized.split())),
        " ".join(sorted(second_normalized.split())),
    ).ratio()
    return max(direct, token_sorted)


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
    places: Iterable[MatchablePlace],
    existing_restaurants: Iterable[ExistingRestaurant],
    *,
    max_distance_meters: float = MATCH_DISTANCE_METERS,
) -> MatchResult:
    existing_restaurants = list(existing_restaurants)
    by_name: dict[str, list[ExistingRestaurant]] = {}
    for restaurant in existing_restaurants:
        by_name.setdefault(normalize_match_name(restaurant.name), []).append(restaurant)

    cell_size = 0.002
    by_cell: dict[tuple[int, int], list[ExistingRestaurant]] = {}
    for restaurant in existing_restaurants:
        key = (
            floor(restaurant.latitude / cell_size),
            floor(restaurant.longitude / cell_size),
        )
        by_cell.setdefault(key, []).append(restaurant)

    matches: dict[str, str] = {}
    ambiguous_source_ids: set[str] = set()
    fuzzy = 0
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
        nearby = [
            candidate for candidate in nearby if candidate[0] <= max_distance_meters
        ]
        if len(nearby) == 1:
            matches[place.source_id] = nearby[0][1].id
        elif len(nearby) > 1:
            nearest_distance = nearby[0][0]
            next_distance = nearby[1][0]
            if next_distance - nearest_distance >= 25:
                matches[place.source_id] = nearby[0][1].id
            else:
                ambiguous_source_ids.add(place.source_id)
        else:
            cell = (
                floor(place.latitude / cell_size),
                floor(place.longitude / cell_size),
            )
            fuzzy_candidates = []
            for latitude_offset in (-1, 0, 1):
                for longitude_offset in (-1, 0, 1):
                    for restaurant in by_cell.get(
                        (cell[0] + latitude_offset, cell[1] + longitude_offset),
                        [],
                    ):
                        distance = distance_meters(
                            place.latitude,
                            place.longitude,
                            restaurant.latitude,
                            restaurant.longitude,
                        )
                        if distance > max_distance_meters:
                            continue
                        score = fuzzy_name_score(place.name, restaurant.name)
                        if score >= 0.88:
                            fuzzy_candidates.append((score, distance, restaurant))
            fuzzy_candidates.sort(
                key=lambda candidate: (-candidate[0], candidate[1], candidate[2].id)
            )
            if len(fuzzy_candidates) == 1:
                matches[place.source_id] = fuzzy_candidates[0][2].id
                fuzzy += 1
            elif len(fuzzy_candidates) > 1:
                best = fuzzy_candidates[0]
                second = fuzzy_candidates[1]
                if best[0] - second[0] >= 0.08 or (
                    best[0] == second[0] and second[1] - best[1] >= 25
                ):
                    matches[place.source_id] = best[2].id
                    fuzzy += 1
                else:
                    ambiguous_source_ids.add(place.source_id)
    return MatchResult(
        matches=matches,
        ambiguous=len(ambiguous_source_ids),
        fuzzy=fuzzy,
        ambiguous_source_ids=frozenset(ambiguous_source_ids),
    )
