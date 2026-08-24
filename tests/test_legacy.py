import json

import pytest

from restfinder.legacy import LegacyRestaurant, load_legacy_json, match_legacy_restaurants


def legacy(source_id: str, name: str = "Test Place") -> LegacyRestaurant:
    return LegacyRestaurant(
        source_id=source_id,
        name=name,
        cuisine="Cafe",
        address="1 Test Street",
        phone="2125550100",
        latitude=40.75,
        longitude=-73.98,
        references=("https://example.com/place",),
    )


def test_loads_legacy_rows_and_deduplicates_urls(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "123",
                    "name": "Secret Place",
                    "cuisine": "Cafe",
                    "address": "1 Test Street",
                    "lat": 40.75,
                    "lon": -73.98,
                    "phone": "2125550100",
                    "foodie_urls": [
                        "https://www.atlasobscura.com/places/secret-place",
                        "https://www.atlasobscura.com/places/secret-place",
                    ],
                }
            ]
        )
    )

    rows = load_legacy_json(path)

    assert len(rows) == 1
    assert rows[0].fallback_id == "legacy_nyc:123"
    assert rows[0].dohmh_id == "nyc_dohmh:123"
    assert rows[0].is_atlas_obscura
    assert rows[0].references == ("https://www.atlasobscura.com/places/secret-place",)


def test_rejects_non_web_reference(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "123",
                    "name": "Test Place",
                    "lat": 40.75,
                    "lon": -73.98,
                    "foodie_urls": ["Rick's List"],
                }
            ]
        )
    )

    with pytest.raises(ValueError, match="invalid foodie URL"):
        load_legacy_json(path)


def test_matching_prefers_original_dohmh_id():
    targets, direct, ambiguous = match_legacy_restaurants(
        [legacy("123")],
        [
            ("nyc_dohmh:123", "Different Current Name", 40.8, -74.0, "nyc_dohmh"),
            ("kmz:nearby", "Test Place", 40.75, -73.98, "Rick's List"),
        ],
    )

    assert targets == {"123": "nyc_dohmh:123"}
    assert direct == 1
    assert ambiguous == 0


def test_missing_id_matches_master_then_rick_fallback():
    restaurants = [legacy("old-master", "Master Place"), legacy("old-rick", "Rick Place")]
    targets, direct, ambiguous = match_legacy_restaurants(
        restaurants,
        [
            ("nyc_dohmh:new", "MASTER PLACE", 40.7501, -73.98, "nyc_dohmh"),
            ("kmz:rick", "RICK PLACE", 40.7501, -73.98, "Rick's List"),
        ],
    )

    assert targets == {
        "old-master": "nyc_dohmh:new",
        "old-rick": "kmz:rick",
    }
    assert direct == 0
    assert ambiguous == 0
