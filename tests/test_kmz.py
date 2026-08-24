from pathlib import Path
from zipfile import ZipFile

import pytest

from restfinder.kmz import dry_run_payload, parse_coordinates, parse_kmz

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


@pytest.mark.parametrize("coordinates", [None, "bad", "181,40", "-73,91"])
def test_invalid_coordinates_are_rejected(coordinates):
    with pytest.raises(ValueError, match="coordinates"):
        parse_coordinates(coordinates, place_name="Broken Place")
