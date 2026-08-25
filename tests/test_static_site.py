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

    assert 'rel="manifest" href="manifest.webmanifest"' in html
    assert 'rel="apple-touch-icon"' in html
    assert "navigator.serviceWorker.register('service-worker.js')" in html
    assert "navigator.geolocation.getCurrentPosition" in html


def test_frontend_uses_social_domains_as_reference_labels():
    html = (ROOT / "index.html").read_text()

    assert "'instagram.com': 'Instagram'" in html
    assert "'tiktok.com': 'TikTok'" in html
    assert "`${referenceLabel(value)} ${value}`" in html


def test_map_popup_is_wide_and_survives_map_autopan():
    html = (ROOT / "index.html").read_text()

    assert "const minWidth = Math.min(300, availableWidth);" in html
    assert "autoPanPadding: [20, 20]" in html
    assert "keepInView: true" in html
    assert "markerLayer.clearLayers();" not in html
    assert "id !== activePopupRestaurantId" in html
    assert "marker.on('popupopen'" in html
    assert "pendingPopupRestaurantId !== id" in html
    assert "map.getCenter().distanceTo(target) < 1" in html


def test_build_copies_pwa_files():
    makefile = (ROOT / "Makefile").read_text()

    assert "manifest.webmanifest service-worker.js .site/" in makefile
