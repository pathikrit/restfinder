from pathlib import Path
from zipfile import ZipFile

import pytest

from restfinder.kmz import (
    KMZPlace,
    KMZDocument,
    ExistingRestaurant,
    driving_durations,
    dry_run_payload,
    fuzzy_name_score,
    parse_coordinates,
    parse_category_types,
    parse_kmz,
    match_existing_restaurants,
    type_for,
    unique_restaurant_candidates,
    within_driving_limit,
)

KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Test List</name>
    <Folder>
      <name>Restaurants</name>
      <Placemark>
        <name>Noodle Place</name>
        <description>Worth a visit</description>
        <Point><coordinates>-73.99,40.75,0</coordinates></Point>
      </Placemark>
    </Folder>
    <Folder>
      <name>Museums, Galleries &amp; Landmarks</name>
      <Placemark>
        <name>A Museum</name>
        <Point><coordinates>-73.98,40.76,0</coordinates></Point>
      </Placemark>
    </Folder>
  </Document>
</kml>
"""


def write_kmz(path: Path) -> None:
    with ZipFile(path, "w") as archive:
        archive.writestr("doc.kml", KML)


def test_parse_kmz_preserves_category_description_and_coordinates(tmp_path):
    path = tmp_path / "list.kmz"
    write_kmz(path)
    document = parse_kmz(path)

    assert document.name == "Test List"
    assert len(document.places) == 2
    restaurant = document.places[0]
    assert restaurant.name == "Noodle Place"
    assert restaurant.category == "Restaurants"
    assert restaurant.description == "Worth a visit"
    assert restaurant.latitude == 40.75
    assert restaurant.longitude == -73.99
    assert restaurant.type_hint == "Restaurant"
    assert restaurant.restaurant_candidate is True
    assert restaurant.source_id.startswith("kmz:ricks-list:")


def test_dry_run_defaults_to_restaurant_candidates(tmp_path):
    path = tmp_path / "list.kmz"
    write_kmz(path)
    payload = dry_run_payload(parse_kmz(path), source_file=path)

    assert payload["total_placemarks"] == 2
    assert payload["restaurant_candidates"] == 1
    assert payload["skipped_non_restaurant"] == 1
    assert payload["unique_placemarks"] == 2
    assert payload["duplicate_placemarks"] == 0
    assert payload["unique_restaurant_candidates"] == 1
    assert payload["candidate_type_hint_counts"] == {"Restaurant": 1}
    assert payload["selected_count"] == 1
    assert [place["name"] for place in payload["places"]] == ["Noodle Place"]


def test_source_id_is_stable(tmp_path):
    path = tmp_path / "list.kmz"
    write_kmz(path)
    first = parse_kmz(path).places[0].source_id
    second = parse_kmz(path).places[0].source_id
    assert first == second


def test_source_id_namespace_changes_with_list_name(tmp_path):
    path = tmp_path / "list.kmz"
    write_kmz(path)
    document = parse_kmz(
        path,
        source="Megan's List",
        category_types={"Restaurants": "Restaurant"},
    )
    assert document.source == "Megan's List"
    assert document.places[0].source_id.startswith("kmz:megans-list:")


def test_category_type_mapping():
    assert type_for("Restaurants", "Any Place") == "Restaurant"
    assert type_for("Cocktail Bars", "Any Place") == "Bars"
    assert type_for("Cafes, Ice Cream and Bakeries", "Devoción") == "Coffee Shops"
    assert type_for("Cafes, Ice Cream and Bakeries", "Van Leeuwen Ice Cream") == "Dessert"
    assert type_for("Museums, Galleries & Landmarks", "Any Place") is None


def test_custom_category_mapping_and_dessert_classification():
    mapping = parse_category_types(
        [
            "Drinks=Bars",
            "Snacks & Desserts=Coffee Shops",
            "Good Eats=Restaurant",
            "Fancy Eats=Restaurant",
        ]
    )
    assert type_for("Drinks", "Any Place", mapping) == "Bars"
    assert type_for("Snacks & Desserts", "Devoción", mapping) == "Coffee Shops"
    assert type_for("Snacks & Desserts", "Morgenstern's Ice Cream", mapping) == "Dessert"
    assert type_for("Cheap Eats + Quick Bites", "Any Place", mapping) is None


class RouteResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"code": "Ok", "durations": [[3600.0, 8000.0]]}


class RouteSession:
    def __init__(self):
        self.headers = {}

    def get(self, *_args, **_kwargs):
        return RouteResponse()


def test_driving_time_filter():
    places = [
        KMZPlace("one", "One", "Restaurants", None, 40.7, -73.9, "Restaurant", True),
        KMZPlace("two", "Two", "Restaurants", None, 41.0, -74.0, "Restaurant", True),
    ]
    durations = driving_durations(places, session=RouteSession(), pause_seconds=0)
    assert durations == {"one": 3600.0, "two": 8000.0}
    assert within_driving_limit(places, durations) == [places[0]]


def test_matching_uses_normalized_name_and_nearby_location():
    place = KMZPlace(
        "kmz:one",
        "Café China",
        "Restaurants",
        None,
        40.7500,
        -73.9821,
        "Restaurant",
        True,
    )
    existing = ExistingRestaurant(
        "nyc_dohmh:1",
        "CAFE CHINA",
        40.7501,
        -73.9821,
    )
    result = match_existing_restaurants([place], [existing])
    assert result.matches == {"kmz:one": "nyc_dohmh:1"}
    assert result.ambiguous == 0


def test_matching_leaves_close_duplicate_permits_ambiguous():
    place = KMZPlace(
        "kmz:one", "Same Name", "Restaurants", None, 40.75, -73.98, "Restaurant", True
    )
    existing = [
        ExistingRestaurant("nyc_dohmh:1", "Same Name", 40.75001, -73.98),
        ExistingRestaurant("nyc_dohmh:2", "Same Name", 40.75002, -73.98),
    ]
    result = match_existing_restaurants([place], existing)
    assert result.matches == {}
    assert result.ambiguous == 1
    assert result.ambiguous_source_ids == frozenset({"kmz:one"})


def test_matching_accepts_high_confidence_name_variant_nearby():
    place = KMZPlace(
        "kmz:one",
        "Peter Luger Steak House",
        "Good Eats",
        None,
        40.7099,
        -73.9625,
        "Restaurant",
        True,
    )
    existing = ExistingRestaurant(
        "nyc_dohmh:1",
        "PETER LUGER STEAKHOUSE",
        40.7100,
        -73.9625,
    )
    result = match_existing_restaurants([place], [existing])
    assert result.matches == {"kmz:one": "nyc_dohmh:1"}
    assert result.fuzzy == 1


def test_matching_rejects_nearby_unrelated_name():
    place = KMZPlace(
        "kmz:one", "Emily", "Good Eats", None, 40.73, -74.0, "Restaurant", True
    )
    existing = ExistingRestaurant("nyc_dohmh:1", "Aria", 40.7301, -74.0)
    result = match_existing_restaurants([place], [existing])
    assert result.matches == {}
    assert fuzzy_name_score(place.name, existing.name) < 0.88


def test_candidates_coalesce_same_name_and_nearby_location_across_folders():
    restaurant = KMZPlace(
        "kmz:restaurant",
        "Angel's Share",
        "Restaurants",
        None,
        40.72975,
        -73.98916,
        "Restaurant",
        True,
    )
    bar = KMZPlace(
        "kmz:bar",
        "ANGEL'S SHARE",
        "Cocktail Bars",
        None,
        40.72976,
        -73.98916,
        "Bars",
        True,
    )

    unique = unique_restaurant_candidates(KMZDocument("Test", (restaurant, bar)))

    assert len(unique) == 1
    assert unique[0].source_id == "kmz:bar"
    assert unique[0].type_hint == "Bars"
    assert unique[0].duplicate_source_ids == ("kmz:restaurant",)


@pytest.mark.parametrize("coordinates", [None, "bad", "181,40", "-73,91"])
def test_invalid_coordinates_are_rejected(coordinates):
    with pytest.raises(ValueError, match="coordinates"):
        parse_coordinates(coordinates, place_name="Broken Place")
