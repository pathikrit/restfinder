import pytest

from restfinder.nyc import Restaurant, build_address, fetch_snapshot, mark_chains, transform_row


def restaurant(identifier: int, name: str) -> Restaurant:
    return Restaurant(
        id=f"nyc_dohmh:{identifier}",
        source="nyc_dohmh",
        name=name,
        cuisine=None,
        address=None,
        phone=None,
        latitude=None,
        longitude=None,
    )


def test_transform_row_uses_namespaced_camis_and_preserves_source_text():
    result = transform_row(
        {
            "camis": "50000001",
            "name": "McDONALD'S",
            "building": "12",
            "street": "WEST 34 STREET",
            "boro": "Manhattan",
            "zipcode": "10001",
            "phone": "2125550100",
            "cuisine": "Hamburgers",
            "latitude": "40.75",
            "longitude": "-73.99",
        }
    )

    assert result.id == "nyc_dohmh:50000001"
    assert result.name == "McDONALD'S"
    assert result.address == "12 WEST 34 STREET, Manhattan, 10001"
    assert result.latitude == 40.75
    assert result.longitude == -73.99


def test_transform_row_handles_missing_optional_values():
    result = transform_row({"camis": "50000002", "name": None})
    assert result.name == "Unnamed establishment"
    assert result.address is None
    assert result.phone is None
    assert result.latitude is None


def test_build_address_uses_available_components():
    assert build_address({"street": "BROADWAY", "boro": "Manhattan"}) == "BROADWAY, Manhattan"
    assert build_address({}) is None


def test_chain_threshold_is_more_than_five_and_normalized():
    rows = [restaurant(index, "  Same   Name ") for index in range(5)]
    assert not any(item.is_chain for item in mark_chains(rows))

    rows.append(restaurant(6, "same name"))
    marked = mark_chains(rows)
    assert all(item.is_chain for item in marked)


def test_missing_camis_is_rejected():
    with pytest.raises(ValueError, match="CAMIS"):
        transform_row({"name": "No ID"})


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, pages):
        self.pages = iter(pages)

    def get(self, *_args, **_kwargs):
        return FakeResponse(next(self.pages))


def test_snapshot_accepts_batched_record_dates_from_one_publication_window():
    session = FakeSession(
        [
            [{"count": "2"}],
            [
                {"camis": "1", "name": "One", "source_snapshot_at": "2026-08-21T06:00:12.000"},
                {"camis": "2", "name": "Two", "source_snapshot_at": "2026-08-21T06:00:17.000"},
            ],
            [{"count": "2"}],
        ]
    )
    rows, snapshot = fetch_snapshot(session)
    assert len(rows) == 2
    assert snapshot == "2026-08-21T06:00:17"


def test_snapshot_rejects_record_dates_spanning_multiple_publication_windows():
    session = FakeSession(
        [
            [{"count": "2"}],
            [
                {"camis": "1", "name": "One", "source_snapshot_at": "2026-08-21T06:00:00.000"},
                {"camis": "2", "name": "Two", "source_snapshot_at": "2026-08-21T08:00:00.000"},
            ],
            [{"count": "2"}],
        ]
    )
    with pytest.raises(ValueError, match="inconsistent record dates"):
        fetch_snapshot(session)
