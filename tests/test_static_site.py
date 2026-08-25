import json
from pathlib import Path
import struct


ROOT = Path(__file__).parents[1]


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as image:
        assert image.read(8) == b"\x89PNG\r\n\x1a\n"
        image.seek(16)
        return struct.unpack(">II", image.read(8))


def test_web_app_manifest_has_installable_icons():
    manifest = json.loads((ROOT / "manifest.webmanifest").read_text())

    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "./"
    icons = {icon["sizes"]: ROOT / icon["src"] for icon in manifest["icons"]}
    assert png_size(icons["192x192"]) == (192, 192)
    assert png_size(icons["512x512"]) == (512, 512)
    assert png_size(ROOT / "assets/icons/apple-touch-icon.png") == (180, 180)


def test_frontend_registers_pwa_and_native_location_support():
    html = (ROOT / "index.html").read_text()
    javascript = (ROOT / "assets/app.js").read_text()

    assert 'rel="manifest" href="manifest.webmanifest"' in html
    assert 'rel="apple-touch-icon"' in html
    assert "navigator.serviceWorker.register('service-worker.js')" in javascript
    assert "navigator.serviceWorker.getRegistrations()" in javascript
    assert "['localhost', '127.0.0.1']" in javascript
    assert "navigator.geolocation.getCurrentPosition" in javascript


def test_frontend_uses_social_domains_as_reference_labels():
    javascript = (ROOT / "assets/app.js").read_text()

    assert "'instagram.com': 'Instagram'" in javascript
    assert "'tiktok.com': 'TikTok'" in javascript
    assert "`${referenceLabel(value)} ${value}`" in javascript


def test_frontend_uses_google_maps_and_live_place_details():
    html = (ROOT / "index.html").read_text()
    javascript = (ROOT / "assets/app.js").read_text()

    assert "leaflet" not in html.lower()
    assert "maps.googleapis.com/maps/api/js" in javascript
    assert "AdvancedMarkerElement" in javascript
    assert "PlaceAutocompleteElement" in javascript
    assert "ColorScheme.LIGHT" in javascript
    assert "ColorScheme.DARK" in javascript
    assert "gmp-place-opening-hours" in javascript
    assert "gmp-place-price" in javascript
    assert "gmp-place-open-now-status" in javascript
    assert "assets/maki/" in javascript
    assert ">Open in Maps</a>" in javascript
    assert "RestFinder details" not in javascript
    assert "restaurant.google_place_id ? mentionMetadata" in javascript
    assert "const showLabels = visible.length < 50" in javascript
    assert "showLabels !== markerLabelMode" in javascript


def test_frontend_theme_switches_app_and_map_and_remembers_choice():
    html = (ROOT / "index.html").read_text()
    javascript = (ROOT / "assets/app.js").read_text()

    assert 'id="theme-toggle"' in html
    assert 'id="version"' in html
    assert 'id="status" class="status">${restaurants.length} places</span>' in javascript
    assert html.index('<h1>') < html.index('id="address-search"') < html.index('id="theme-toggle"') < html.index('id="version"')
    assert "prefers-color-scheme: light" in html
    assert "localStorage.setItem('restfinder-theme', theme)" in javascript
    assert "createGoogleMap(center, zoom)" in javascript


def test_build_copies_pwa_files():
    makefile = (ROOT / "Makefile").read_text()

    assert "manifest.webmanifest service-worker.js privacy.html terms.html NOTICE .site/" in makefile
