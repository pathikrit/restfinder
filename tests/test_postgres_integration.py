import os
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from restfinder.duplicates import merge_restaurant
from restfinder.enrichment import ProviderMatch, ProviderPlace, upsert_enrichment
from restfinder.export import export_rows
from restfinder.kmz import KMZPlace, import_places
from restfinder.legacy import LegacyRestaurant, import_legacy_restaurants
from restfinder.nyc import Restaurant, upsert_snapshot
from restfinder.references import ReferenceManifest, import_manifests
from restfinder.social_video import (
    fallback_id as social_fallback_id,
    import_manifest,
    source_import_status,
)


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")


def row(identifier: int, *, name: str = "Independent Place", chain: bool = False) -> Restaurant:
    return Restaurant(
        id=f"nyc_dohmh:{identifier}",
        source="nyc_dohmh",
        name=name,
        cuisine="Korean",
        address="1 TEST STREET, Manhattan, 10001",
        phone="2125550100",
        latitude=40.75,
        longitude=-73.99,
        is_chain=chain,
    )


@pytest.fixture(autouse=True)
def clean_database():
    if TEST_DATABASE_URL and "test" not in TEST_DATABASE_URL:
        pytest.fail("TEST_DATABASE_URL must point to a visibly named test database")
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(
            "TRUNCATE enrichment_runs, restaurant_enrichments, restaurant_aliases, "
            "restaurant_references, restaurants RESTART IDENTITY"
        )
    yield
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute(
            "TRUNCATE enrichment_runs, restaurant_enrichments, restaurant_aliases, "
            "restaurant_references, restaurants RESTART IDENTITY"
        )


def test_overture_fills_missing_export_fields_without_overwriting_canonical():
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    restaurant = row(77)
    restaurant = Restaurant(
        id=restaurant.id,
        source=restaurant.source,
        name=restaurant.name,
        cuisine=None,
        address=None,
        phone=None,
        latitude=restaurant.latitude,
        longitude=restaurant.longitude,
        is_chain=False,
    )
    upsert_snapshot([restaurant], connection_url=TEST_DATABASE_URL, observed_at=now)
    import_manifests(
        [ReferenceManifest("A list", now, (restaurant.id,))],
        connection_url=TEST_DATABASE_URL,
    )
    place = ProviderPlace(
        id="overture-id",
        name=restaurant.name,
        address="77 Test Street, New York, NY",
        latitude=restaurant.latitude,
        longitude=restaurant.longitude,
        primary_category="korean_restaurant",
        category_hierarchy=("food_and_drink", "restaurant", "korean_restaurant"),
        operating_status="open",
        phones=("+12125550177",),
        websites=("https://example.test",),
    )
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        upsert_enrichment(
            connection,
            restaurant_id=restaurant.id,
            provider="overture",
            match=ProviderMatch("matched", place, "exact_name_nearby", 1.0),
            checked_at=now,
            provider_release="2026-08-19.0",
        )

    exported = export_rows(connection_url=TEST_DATABASE_URL)[0]
    assert exported["cuisine"] == "Korean"
    assert exported["address"] == "77 Test Street, New York, NY"
    assert exported["phone"] == "+12125550177"
    assert exported["website"] == "https://example.test"
    assert exported["operating_status"] == "open"
    assert exported["detail_sources"]["cuisine"] == "overture"


def test_reviewed_merge_moves_references_and_hides_alias():
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    upsert_snapshot([row(1), row(2)], connection_url=TEST_DATABASE_URL, observed_at=now)
    import_manifests(
        [ReferenceManifest("First", now, ("nyc_dohmh:1",)), ReferenceManifest("Second", now, ("nyc_dohmh:2",))],
        connection_url=TEST_DATABASE_URL,
    )
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        merge_restaurant(
            connection,
            alias_id="nyc_dohmh:2",
            canonical_id="nyc_dohmh:1",
            reviewed_at=now,
            reason="Reviewed duplicate",
        )

    exported = export_rows(connection_url=TEST_DATABASE_URL)
    assert [item["id"] for item in exported] == ["nyc_dohmh:1"]
    assert {item["reference"] for item in exported[0]["references"]} == {"First", "Second"}


def test_google_enrichment_persists_only_place_id_and_match_metadata():
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    restaurant = row(88)
    upsert_snapshot([restaurant], connection_url=TEST_DATABASE_URL, observed_at=now)
    import_manifests(
        [ReferenceManifest("A list", now, (restaurant.id,))],
        connection_url=TEST_DATABASE_URL,
    )
    transient_google_place = ProviderPlace(
        id="google-place-id",
        name="Google-provided name",
        address="Google-provided address",
        latitude=restaurant.latitude,
        longitude=restaurant.longitude,
        primary_category="restaurant",
        phones=("+12125550188",),
        websites=("https://google-content.invalid",),
    )
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        upsert_enrichment(
            connection,
            restaurant_id=restaurant.id,
            provider="google_places",
            match=ProviderMatch("matched", transient_google_place, "exact_name_nearby", 1.0),
            checked_at=now,
        )
        stored = connection.execute(
            """
            SELECT provider_place_id, primary_category, address, phones, websites
            FROM restaurant_enrichments
            WHERE restaurant_id = %s AND provider = 'google_places'
            """,
            (restaurant.id,),
        ).fetchone()

    assert stored == ("google-place-id", None, None, None, None)
    exported = export_rows(connection_url=TEST_DATABASE_URL)[0]
    assert exported["google_place_id"] == "google-place-id"
    assert "Google-provided" not in str(exported)


def test_upsert_import_and_curated_export():
    first = datetime(2026, 8, 1, tzinfo=timezone.utc)
    second = first + timedelta(days=1)
    inserted, updated = upsert_snapshot([row(1), row(2, chain=True)], connection_url=TEST_DATABASE_URL, observed_at=first)
    assert (inserted, updated) == (2, 0)

    manifest = ReferenceManifest("Rick's Favorites", first, ("nyc_dohmh:1", "nyc_dohmh:2"))
    assert import_manifests([manifest], connection_url=TEST_DATABASE_URL) == 2

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        connection.execute("UPDATE restaurants SET type = 'Restaurant' WHERE id = 'nyc_dohmh:1'")

    changed = row(1, name="Updated Independent Place")
    inserted, updated = upsert_snapshot([changed, row(2, chain=True)], connection_url=TEST_DATABASE_URL, observed_at=second)
    assert (inserted, updated) == (0, 2)

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        record = connection.execute(
            "SELECT first_seen, last_seen, name, type FROM restaurants WHERE id = 'nyc_dohmh:1'"
        ).fetchone()
        assert record == (first, second, "Updated Independent Place", "Restaurant")
        assert connection.execute("SELECT count(*) FROM restaurant_references").fetchone()[0] == 2

    exported = export_rows(connection_url=TEST_DATABASE_URL)
    assert [item["id"] for item in exported] == ["nyc_dohmh:1"]
    assert exported[0]["type"] == "Restaurant"
    assert exported[0]["references"][0]["reference"] == "Rick's Favorites"


def test_missing_rows_remain_historical_and_are_not_exported():
    first = datetime(2026, 8, 1, tzinfo=timezone.utc)
    second = first + timedelta(days=1)
    upsert_snapshot([row(1), row(2)], connection_url=TEST_DATABASE_URL, observed_at=first)
    import_manifests(
        [ReferenceManifest("A list", first, ("nyc_dohmh:1", "nyc_dohmh:2"))],
        connection_url=TEST_DATABASE_URL,
    )
    upsert_snapshot([row(1)], connection_url=TEST_DATABASE_URL, observed_at=second)

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        assert connection.execute("SELECT count(*) FROM restaurants").fetchone()[0] == 2
    assert [item["id"] for item in export_rows(connection_url=TEST_DATABASE_URL)] == ["nyc_dohmh:1"]


def test_unknown_reference_id_rolls_back_entire_import():
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    upsert_snapshot([row(1)], connection_url=TEST_DATABASE_URL, observed_at=now)
    manifest = ReferenceManifest("A list", now, ("nyc_dohmh:1", "nyc_dohmh:999"))
    with pytest.raises(ValueError, match="Unknown restaurant IDs"):
        import_manifests([manifest], connection_url=TEST_DATABASE_URL)
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        assert connection.execute("SELECT count(*) FROM restaurant_references").fetchone()[0] == 0


def test_kmz_import_sets_source_type_and_reference():
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    place = KMZPlace(
        source_id="kmz:ricks-list:test",
        name="Test Cafe",
        category="Cafes, Ice Cream and Bakeries",
        description=None,
        latitude=40.75,
        longitude=-73.98,
        type_hint="Coffee Shops",
        restaurant_candidate=True,
    )
    result = import_places(
        [place],
        connection_url=TEST_DATABASE_URL,
        observed_at=now,
        reference_added_at=now,
    )
    assert (result.inserted, result.updated, result.matched_existing) == (1, 0, 0)

    with psycopg.connect(TEST_DATABASE_URL) as connection:
        assert connection.execute(
            "SELECT source, type FROM restaurants WHERE id = %s", (place.source_id,)
        ).fetchone() == ("Rick's List", "Coffee Shops")
        assert connection.execute(
            "SELECT reference FROM restaurant_references WHERE restaurant_id = %s",
            (place.source_id,),
        ).fetchone() == ("Rick's List",)


def test_kmz_import_references_matching_master_without_duplicate():
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    master = Restaurant(
        id="nyc_dohmh:123",
        source="nyc_dohmh",
        name="Café China",
        cuisine="Chinese",
        address="59 W 37TH ST, Manhattan, NY 10018",
        phone="2122132810",
        latitude=40.7501,
        longitude=-73.9821,
        is_chain=False,
    )
    upsert_snapshot([master], connection_url=TEST_DATABASE_URL, observed_at=now)
    place = KMZPlace(
        source_id="kmz:ricks-list:cafe-china",
        name="CAFE CHINA",
        category="Restaurants",
        description=None,
        latitude=40.7500,
        longitude=-73.9821,
        type_hint="Restaurant",
        restaurant_candidate=True,
    )

    result = import_places(
        [place],
        connection_url=TEST_DATABASE_URL,
        observed_at=now,
        reference_added_at=now,
    )

    assert (result.inserted, result.matched_existing, result.ambiguous) == (0, 1, 0)
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        assert connection.execute("SELECT count(*) FROM restaurants").fetchone()[0] == 1
        assert connection.execute(
            "SELECT restaurant_id, reference FROM restaurant_references"
        ).fetchone() == (master.id, "Rick's List")


def test_kmz_import_reuses_existing_external_fallback():
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    duplicate_permits = [
        Restaurant(
            id=f"nyc_dohmh:{identifier}",
            source="nyc_dohmh",
            name="Test Place",
            cuisine="American",
            address="1 TEST STREET, Manhattan, 10001",
            phone="2125550100",
            latitude=latitude,
            longitude=-73.98,
            is_chain=False,
        )
        for identifier, latitude in ((1, 40.75001), (2, 40.75002))
    ]
    upsert_snapshot(
        duplicate_permits,
        connection_url=TEST_DATABASE_URL,
        observed_at=now,
    )
    rick_place = KMZPlace(
        source_id="kmz:ricks-list:test-place",
        name="Test Place",
        category="Restaurants",
        description=None,
        latitude=40.75,
        longitude=-73.98,
        type_hint="Restaurant",
        restaurant_candidate=True,
    )
    import_places(
        [rick_place],
        connection_url=TEST_DATABASE_URL,
        observed_at=now,
        reference_added_at=now,
    )
    megan_place = KMZPlace(
        source_id="kmz:megans-list:test-place",
        name="TEST PLACE",
        category="Drinks",
        description=None,
        latitude=40.7501,
        longitude=-73.98,
        type_hint="Bars",
        restaurant_candidate=True,
    )
    result = import_places(
        [megan_place],
        connection_url=TEST_DATABASE_URL,
        observed_at=now,
        reference_added_at=now,
        source="Megan's List",
    )

    assert (result.inserted, result.matched_existing) == (0, 1)
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        assert connection.execute("SELECT count(*) FROM restaurants").fetchone()[0] == 3
        assert connection.execute(
            """
            SELECT restaurant_id
            FROM restaurant_references
            WHERE reference = 'Megan''s List'
            """
        ).fetchone() == (rick_place.source_id,)
        assert connection.execute(
            "SELECT type FROM restaurants WHERE id = %s", (rick_place.source_id,)
        ).fetchone() == ("Bars",)
        assert connection.execute(
            "SELECT reference FROM restaurant_references ORDER BY reference"
        ).fetchall() == [("Megan's List",), ("Rick's List",)]


def test_new_fallback_import_does_not_expire_older_fallback():
    first = datetime(2026, 8, 24, tzinfo=timezone.utc)
    second = first + timedelta(days=1)
    places = [
        KMZPlace(
            source_id="kmz:ricks-list:first",
            name="First Place",
            category="Restaurants",
            description=None,
            latitude=40.70,
            longitude=-73.90,
            type_hint="Restaurant",
            restaurant_candidate=True,
        ),
        KMZPlace(
            source_id="kmz:ricks-list:second",
            name="Second Place",
            category="Cocktail Bars",
            description=None,
            latitude=40.71,
            longitude=-73.91,
            type_hint="Bars",
            restaurant_candidate=True,
        ),
    ]
    import_places(
        places[:1],
        connection_url=TEST_DATABASE_URL,
        observed_at=first,
        reference_added_at=first,
    )
    import_places(
        places[1:],
        connection_url=TEST_DATABASE_URL,
        observed_at=second,
        reference_added_at=second,
    )

    assert [row["id"] for row in export_rows(connection_url=TEST_DATABASE_URL)] == [
        "kmz:ricks-list:first",
        "kmz:ricks-list:second",
    ]


def test_social_video_import_is_reviewed_synchronized_and_idempotent():
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    master = row(123, name="Existing Bar")
    upsert_snapshot([master], connection_url=TEST_DATABASE_URL, observed_at=now)
    reference = "https://www.instagram.com/p/DcU1FfROXHZ/"
    fallback_id = social_fallback_id("Secret Bar", 40.75, -73.99)
    manifest = {
        "schema_version": 1,
        "reference": reference,
        "added_at": "2026-08-24T00:00:00Z",
        "restaurants": [
            {"restaurant_id": master.id, "type": "Bars"},
            {
                "restaurant_id": fallback_id,
                "type": "Hidden / Speakeasy",
                "fallback": {
                    "name": "Secret Bar",
                    "address": "1 Secret Street, New York, NY 10001",
                    "latitude": 40.75,
                    "longitude": -73.99,
                },
            },
        ],
    }

    first = import_manifest(manifest, connection_url=TEST_DATABASE_URL)
    second = import_manifest(manifest, connection_url=TEST_DATABASE_URL)

    assert (first.matched_existing, first.inserted_fallbacks) == (1, 1)
    assert (first.types_updated, first.references_inserted) == (1, 2)
    assert (second.inserted_fallbacks, second.updated_fallbacks) == (0, 1)
    assert (second.types_updated, second.references_inserted) == (0, 0)
    equivalent_references = [
        reference,
        "https://www.instagram.com/reel/DcU1FfROXHZ/",
        "https://www.instagram.com/tv/DcU1FfROXHZ/",
        "https://www.instagram.com/angelhuangny/reel/DcU1FfROXHZ/",
    ]
    for equivalent_reference in equivalent_references:
        status = source_import_status(
            equivalent_reference, connection_url=TEST_DATABASE_URL
        )
        assert status["imported"] is True
        assert len(status["restaurants"]) == 2
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        assert connection.execute(
            "SELECT type FROM restaurants WHERE id = %s", (master.id,)
        ).fetchone() == ("Bars",)
        assert connection.execute(
            "SELECT source, type FROM restaurants WHERE id = %s", (fallback_id,)
        ).fetchone() == ("social_video", "Hidden / Speakeasy")
        assert connection.execute(
            "SELECT count(*) FROM restaurant_references WHERE reference = %s", (reference,)
        ).fetchone()[0] == 2

    reduced = {
        **manifest,
        "restaurants": [{"restaurant_id": master.id, "type": "Restaurant"}],
    }
    synchronized = import_manifest(reduced, connection_url=TEST_DATABASE_URL)

    assert synchronized.references_removed == 1
    assert synchronized.orphan_fallbacks_removed == 1
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        assert connection.execute(
            "SELECT type FROM restaurants WHERE id = %s", (master.id,)
        ).fetchone() == ("Bars",)
        assert connection.execute(
            "SELECT count(*) FROM restaurants WHERE id = %s", (fallback_id,)
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT restaurant_id FROM restaurant_references WHERE reference = %s",
            (reference,),
        ).fetchall() == [(master.id,)]


def test_legacy_import_uses_master_id_and_tags_atlas_obscura():
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    master = row(123, name="Secret Place")
    upsert_snapshot([master], connection_url=TEST_DATABASE_URL, observed_at=now)
    legacy = LegacyRestaurant(
        source_id="123",
        name="Secret Place",
        cuisine="American",
        address="1 TEST STREET, Manhattan, 10001",
        phone="2125550100",
        latitude=40.75,
        longitude=-73.99,
        references=(
            "https://www.atlasobscura.com/places/secret-place",
            "https://guide.michelin.com/us/en/secret-place",
        ),
    )

    result = import_legacy_restaurants(
        [legacy],
        connection_url=TEST_DATABASE_URL,
        observed_at=now,
    )

    assert result.direct_id_matches == 1
    assert result.inserted_fallbacks == 0
    assert result.references_imported == 2
    with psycopg.connect(TEST_DATABASE_URL) as connection:
        assert connection.execute("SELECT count(*) FROM restaurants").fetchone()[0] == 1
        assert connection.execute(
            "SELECT type FROM restaurants WHERE id = %s", (master.id,)
        ).fetchone() == ("Hidden / Speakeasy",)
        assert connection.execute(
            "SELECT count(*) FROM restaurant_references WHERE restaurant_id = %s",
            (master.id,),
        ).fetchone()[0] == 2
