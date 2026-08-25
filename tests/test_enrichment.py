from datetime import UTC, datetime

from restfinder.enrichment import (
    ProviderPlace,
    RestaurantForEnrichment,
    category_label,
    choose_provider_match,
    google_places_from_payload,
    month_start,
    overture_cuisine,
    overture_restaurant_type,
    search_google_place,
)


def restaurant(*, address="10 Main Street"):
    return RestaurantForEnrichment("restaurant:1", "Café China", address, 40.75, -73.98)


def place(identifier, *, name="Cafe China", address="10 Main Street", latitude=40.7501):
    return ProviderPlace(identifier, name, address, latitude, -73.98)


def test_unique_exact_nearby_match_is_accepted():
    result = choose_provider_match(restaurant(), [place("place:1")])
    assert result.status == "matched"
    assert result.place.id == "place:1"
    assert result.method == "exact_name_nearby"


def test_multiple_exact_matches_are_ambiguous():
    result = choose_provider_match(
        restaurant(),
        [place("place:1"), place("place:2", latitude=40.7502)],
    )
    assert result.status == "ambiguous"


def test_fuzzy_match_requires_matching_house_number():
    accepted = choose_provider_match(
        restaurant(),
        [place("place:1", name="Cafe Chinaa", address="10 Main St")],
    )
    rejected = choose_provider_match(
        restaurant(),
        [place("place:2", name="Cafe Chinaa", address="11 Main St")],
    )
    assert accepted.status == "matched"
    assert accepted.method == "fuzzy_name_address"
    assert rejected.status == "unmatched"


def test_overture_cuisine_uses_specific_taxonomy_only():
    assert overture_cuisine(["food_and_drink", "restaurant", "italian_restaurant"]) == "Italian"
    assert overture_cuisine(["food_and_drink", "restaurant", "fast_food_restaurant"]) is None
    assert category_label("coffee_shop") == "Coffee Shop"


def test_overture_categories_map_to_supported_restaurant_types():
    assert overture_restaurant_type(None, ["food_and_drink", "ice_cream_shop"]) == "Dessert"
    assert overture_restaurant_type("fast_food_restaurant", ["food_and_drink"]) == "Fast Food"
    assert overture_restaurant_type(None, ["food_and_drink", "cocktail_bar"]) == "Bars"
    assert overture_restaurant_type(None, ["food_and_drink", "coffee_shop"]) == "Coffee Shops"
    assert overture_restaurant_type(None, ["food_and_drink", "italian_restaurant"]) == "Restaurant"
    assert overture_restaurant_type(None, ["retail"]) is None


def test_google_payload_parsing_drops_incomplete_places():
    places = google_places_from_payload(
        {
            "places": [
                {
                    "id": "google-id",
                    "displayName": {"text": "Cafe China"},
                    "formattedAddress": "10 Main Street",
                    "location": {"latitude": 40.75, "longitude": -73.98},
                    "primaryType": "chinese_restaurant",
                },
                {"id": "missing-location", "displayName": {"text": "No Location"}},
            ]
        }
    )
    assert [place.id for place in places] == ["google-id"]


def test_month_start_is_utc():
    assert month_start(datetime(2026, 8, 25, 12, tzinfo=UTC)) == datetime(
        2026, 8, 1, tzinfo=UTC
    )


def test_google_search_uses_matching_fields_without_persisting_response():
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "places": [
                    {
                        "id": "google-id",
                        "displayName": {"text": "Cafe China"},
                        "formattedAddress": "10 Main Street",
                        "location": {"latitude": 40.75, "longitude": -73.98},
                    }
                ]
            }

    class Session:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response()

    requests_used = []
    session = Session()
    places = search_google_place(
        restaurant(),
        api_key="secret",
        session=session,
        consume_request=lambda: requests_used.append(True),
    )

    assert [item.id for item in places] == ["google-id"]
    assert len(requests_used) == 1
    assert session.calls[0][1]["headers"]["X-Goog-FieldMask"] == (
        "places.id,places.displayName,places.formattedAddress,"
        "places.location,places.primaryType"
    )
