from datetime import datetime, timezone
import json
import wave

import av
from PIL import Image
import pytest
import requests

from restfinder.social_video import (
    DatabaseRestaurant,
    NominatimGeocoder,
    build_manifest,
    choose_existing_match,
    extract_audio,
    extract_frames,
    fallback_id,
    inspect_draft,
    inspect_source_status,
    normalize_extraction,
    social_identity,
    validate_draft,
    validate_manifest,
    validate_social_download_url,
)


def test_social_identity_canonicalizes_supported_urls():
    instagram = social_identity(
        "https://instagram.com/p/DcU1FfROXHZ/?utm_source=ig_web_copy_link"
    )
    assert instagram.platform == "instagram"
    assert instagram.post_id == "DcU1FfROXHZ"
    assert instagram.canonical_url == "https://www.instagram.com/p/DcU1FfROXHZ/"

    tiktok = social_identity("https://m.tiktok.com/@food/video/123456?is_from_webapp=1")
    assert tiktok.platform == "tiktok"
    assert tiktok.post_id == "123456"
    assert tiktok.canonical_url == "https://www.tiktok.com/@food/video/123456"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video/1",
        "https://www.instagram.com/accounts/login/",
        "https://www.tiktok.com/@food",
    ],
)
def test_social_identity_rejects_unsupported_urls(url):
    with pytest.raises(ValueError):
        social_identity(url)


def test_social_download_url_requires_https_platform_host():
    validate_social_download_url("https://vm.tiktok.com/abc123/")

    with pytest.raises(ValueError):
        validate_social_download_url("http://www.instagram.com/p/DcU1FfROXHZ/")


def test_inspect_source_status_reports_new_and_existing_sources():
    new_source = {
        "reference": "https://www.instagram.com/p/new/",
        "imported": False,
        "restaurants": [],
    }
    existing_source = {
        "reference": "https://www.instagram.com/p/existing/",
        "imported": True,
        "restaurants": [
            {
                "restaurant_id": "nyc_dohmh:1",
                "name": "Cafe China",
                "type": "Restaurant",
                "source": "nyc_dohmh",
                "added_at": "2026-08-24T00:00:00Z",
            }
        ],
    }

    assert "Imported: no" in inspect_source_status(new_source)
    rendered = inspect_source_status(existing_source)
    assert "Imported: yes" in rendered
    assert "nyc_dohmh:1" in rendered


def test_normalize_extraction_deduplicates_and_requires_evidence():
    payload = {
        "venues": [
            {
                "rank": 1,
                "name": "CAFE CHINA",
                "type": "Restaurant",
                "neighborhood": "Midtown",
                "address": None,
                "confidence": 0.8,
                "evidence": [
                    {"kind": "speech", "text": "Cafe China", "timestamp_seconds": 2.0}
                ],
            },
            {
                "rank": None,
                "name": "Cafe China",
                "type": "Restaurant",
                "neighborhood": None,
                "address": None,
                "confidence": 0.95,
                "evidence": [
                    {
                        "kind": "overlay",
                        "text": "59 W 37th St",
                        "timestamp_seconds": 3.0,
                    }
                ],
            },
            {
                "rank": 2,
                "name": "Ungrounded",
                "type": "Bars",
                "neighborhood": None,
                "address": None,
                "confidence": 0.4,
                "evidence": [],
            },
        ]
    }

    venues = normalize_extraction(payload)

    assert len(venues) == 1
    assert venues[0]["name"] == "Cafe China"
    assert venues[0]["confidence"] == 0.95
    assert len(venues[0]["evidence"]) == 2
    assert venues[0]["candidate_id"].startswith("candidate:")


def restaurant(
    identifier: str,
    *,
    name: str = "Cafe China",
    source: str = "nyc_dohmh",
    current: bool = True,
    latitude: float = 40.7501,
) -> DatabaseRestaurant:
    return DatabaseRestaurant(
        id=identifier,
        source=source,
        name=name,
        type="Restaurant",
        address="59 W 37TH ST, Manhattan, 10018",
        latitude=latitude,
        longitude=-73.9821,
        current_dohmh=current,
    )


def test_choose_existing_match_prefers_current_exact_name():
    candidate = {"candidate_id": "candidate:1", "name": "CAFÉ CHINA"}
    rows = [
        restaurant("nyc_dohmh:old", current=False),
        restaurant("nyc_dohmh:new", current=True),
        restaurant("legacy:1", source="legacy_site", current=False),
    ]

    match = choose_existing_match(candidate, rows)

    assert match["restaurant_id"] == "nyc_dohmh:new"
    assert match["method"] == "unique_exact_current_dohmh"


def test_choose_existing_match_leaves_duplicate_permits_ambiguous_without_coordinates():
    candidate = {"candidate_id": "candidate:1", "name": "Cafe China"}
    rows = [restaurant("nyc_dohmh:1"), restaurant("nyc_dohmh:2", latitude=40.7502)]

    match = choose_existing_match(candidate, rows)

    assert match["status"] == "ambiguous"
    assert len(match["alternatives"]) == 2


class GeocodeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return [
            {
                "lat": "40.7501",
                "lon": "-73.9821",
                "display_name": "Cafe China, 59 West 37th Street, New York, NY",
            }
        ]


class GeocodeSession:
    def __init__(self):
        self.headers = {}
        self.calls = 0

    def get(self, *_args, **_kwargs):
        self.calls += 1
        return GeocodeResponse()


def test_geocoder_caches_nyc_results(tmp_path):
    session = GeocodeSession()
    cache = tmp_path / "geocode.json"
    geocoder = NominatimGeocoder(
        cache_path=cache,
        session=session,
        minimum_interval_seconds=0,
    )

    first = geocoder.geocode("Cafe China", "59 W 37th St")
    second = geocoder.geocode("Cafe China", "59 W 37th St")

    assert first == second
    assert first["latitude"] == 40.7501
    assert session.calls == 1
    assert json.loads(cache.read_text())


class FailedGeocodeResponse:
    def raise_for_status(self):
        raise requests.HTTPError("provider unavailable")


class NycGeocodeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "features": [
                {
                    "geometry": {"coordinates": [-74.0059, 40.7396]},
                    "properties": {
                        "label": "55 GANSEVOORT STREET, New York, NY, USA",
                    },
                }
            ]
        }


class FallbackGeocodeSession:
    def __init__(self):
        self.headers = {}
        self.urls = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        if "nominatim" in url:
            return FailedGeocodeResponse()
        return NycGeocodeResponse()


def test_geocoder_falls_back_to_nyc_geosearch_on_provider_error(tmp_path):
    session = FallbackGeocodeSession()
    geocoder = NominatimGeocoder(
        cache_path=tmp_path / "geocode.json",
        session=session,
        minimum_interval_seconds=0,
    )

    result = geocoder.geocode("RH Guesthouse", "55 Gansevoort Street")

    assert result["provider"] == "NYC Planning GeoSearch"
    assert result["latitude"] == 40.7396
    assert session.urls == [
        "https://nominatim.openstreetmap.org/search",
        "https://geosearch.planninglabs.nyc/v2/search",
    ]


def test_extract_frames_supports_still_images(tmp_path):
    source = tmp_path / "overlay.png"
    Image.new("RGB", (1600, 900), "white").save(source)

    frames = extract_frames(source, tmp_path)

    assert frames[0][0] == 0
    with Image.open(frames[0][1]) as image:
        assert max(image.size) == 1280


def test_extract_audio_transcodes_audio_media(tmp_path):
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\0\0" * 1_600)

    result = extract_audio(source, tmp_path / "copy.wav")

    assert result is not None
    with wave.open(str(result), "rb") as output:
        assert output.getnchannels() == 1
        assert output.getframerate() == 16_000


def test_extract_audio_returns_none_for_invalid_media(tmp_path):
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"not video")

    assert extract_audio(source, tmp_path / "audio.wav") is None


def test_extract_frames_keeps_scene_changes_between_regular_samples(tmp_path):
    source = tmp_path / "scenes.mp4"
    container = av.open(str(source), "w")
    stream = container.add_stream("mpeg4", rate=4)
    stream.width = 160
    stream.height = 90
    stream.pix_fmt = "yuv420p"
    for index in range(8):
        color = "white" if index < 4 else "black"
        frame = av.VideoFrame.from_image(Image.new("RGB", (160, 90), color))
        for packet in stream.encode(frame):
            container.mux(packet)
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()

    frames = extract_frames(source, tmp_path, interval_seconds=10, max_frames=10)

    assert len(frames) == 2
    assert frames[0][0] == 0
    assert frames[1][0] == 1


def approved_draft() -> dict:
    return {
        "schema_version": 1,
        "reference": "https://www.instagram.com/p/DcU1FfROXHZ/",
        "platform": "instagram",
        "post_id": "DcU1FfROXHZ",
        "theme": "Two places",
        "venues": [
            {
                "candidate_id": "candidate:1",
                "rank": 1,
                "name": "Cafe China",
                "type": "Restaurant",
                "evidence": [
                    {"kind": "speech", "text": "Cafe China", "timestamp_seconds": 2.0}
                ],
                "selected": True,
                "resolution": {
                    "status": "matched",
                    "restaurant_id": "nyc_dohmh:1",
                    "name": "Cafe China",
                },
            },
            {
                "candidate_id": "candidate:2",
                "rank": 2,
                "name": "Secret Bar",
                "type": "Hidden / Speakeasy",
                "evidence": [
                    {"kind": "overlay", "text": "1 Secret St", "timestamp_seconds": 6.0}
                ],
                "selected": True,
                "resolution": {
                    "status": "fallback",
                    "fallback_id": fallback_id("Secret Bar", 40.72, -73.99),
                    "name": "Secret Bar",
                    "address": "1 Secret St, New York, NY",
                    "latitude": 40.72,
                    "longitude": -73.99,
                },
            },
        ],
    }


def test_build_and_validate_manifest_from_reviewed_draft():
    draft = approved_draft()
    added_at = datetime(2026, 8, 24, tzinfo=timezone.utc)

    manifest = build_manifest(draft, added_at=added_at)

    validate_manifest(manifest)
    assert manifest["reference"] == draft["reference"]
    assert manifest["restaurants"][0] == {
        "restaurant_id": "nyc_dohmh:1",
        "type": "Restaurant",
    }
    assert manifest["restaurants"][1]["fallback"]["name"] == "Secret Bar"


def test_validate_draft_refuses_selected_unresolved_venue():
    draft = approved_draft()
    draft["venues"][0]["resolution"] = {"status": "unresolved"}

    with pytest.raises(ValueError, match="unresolved"):
        validate_draft(draft)


def test_validate_draft_refuses_unstable_fallback_id():
    draft = approved_draft()
    draft["venues"][1]["resolution"]["fallback_id"] = "social_video:wrong"

    with pytest.raises(ValueError, match="stable identity"):
        validate_draft(draft)


def test_inspect_draft_displays_matches_and_fallbacks():
    review = inspect_draft(approved_draft())

    assert "nyc_dohmh:1" in review
    assert "social_video:" in review
    assert "Hidden / Speakeasy" in review
