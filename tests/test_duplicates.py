import json

from restfinder.duplicates import (
    DuplicateRestaurant,
    nearby_duplicate_pairs,
    pair_key,
    reviewed_pairs,
    suggested_canonical,
)


def duplicate(identifier, *, source="nyc_dohmh", name="Cafe China", latitude=40.75):
    return DuplicateRestaurant(identifier, source, name, "10 Main Street", latitude, -73.98)


def test_nearby_duplicate_detection_is_non_destructive():
    pairs = nearby_duplicate_pairs(
        [duplicate("nyc_dohmh:1"), duplicate("external:1", source="Rick", latitude=40.7501)]
    )
    assert list(pairs) == [("external:1", "nyc_dohmh:1")]
    assert pairs[("external:1", "nyc_dohmh:1")]["match_method"] == "exact_nearby"


def test_suggested_canonical_prefers_dohmh():
    canonical = suggested_canonical(
        duplicate("external:1", source="Rick"),
        duplicate("nyc_dohmh:1"),
    )
    assert canonical == "nyc_dohmh:1"


def test_reviewed_pairs_loads_merge_and_keep_separate(tmp_path):
    (tmp_path / "review.json").write_text(
        json.dumps(
            {
                "reviewed_at": "2026-08-25T00:00:00Z",
                "decisions": [
                    {"first_id": "a", "second_id": "b", "decision": "merge"},
                    {"first_id": "d", "second_id": "c", "decision": "keep_separate"},
                ],
            }
        )
    )
    assert reviewed_pairs(tmp_path) == {("a", "b"), ("c", "d")}
    assert pair_key("z", "a") == ("a", "z")
