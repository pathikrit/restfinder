import json

import pytest

from restfinder.references import load_manifest


def test_load_manifest(tmp_path):
    path = tmp_path / "favorites.json"
    path.write_text(
        json.dumps(
            {
                "reference": "Rick's Favorites",
                "added_at": "2026-08-24T10:30:00Z",
                "restaurant_ids": ["nyc_dohmh:50000001"],
            }
        )
    )
    manifest = load_manifest(path)
    assert manifest.reference == "Rick's Favorites"
    assert manifest.added_at.utcoffset().total_seconds() == 0
    assert manifest.restaurant_ids == ("nyc_dohmh:50000001",)


@pytest.mark.parametrize(
    "manifest,message",
    [
        ({}, "reference"),
        ({"reference": "x", "added_at": "not-a-date", "restaurant_ids": ["a"]}, "RFC 3339"),
        ({"reference": "x", "added_at": "2026-08-24T00:00:00Z", "restaurant_ids": []}, "non-empty"),
        (
            {
                "reference": "x",
                "added_at": "2026-08-24T00:00:00Z",
                "restaurant_ids": ["a", "a"],
            },
            "duplicates",
        ),
    ],
)
def test_invalid_manifest_is_rejected(tmp_path, manifest, message):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=message):
        load_manifest(path)
