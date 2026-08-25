import json

from restfinder.site_metadata import build_url, write_metadata, write_runtime_config


def test_build_url_prefers_the_exact_actions_run():
    assert build_url(
        {
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "pathikrit/restfinder",
            "GITHUB_RUN_ID": "123456",
            "GITHUB_SHA": "abc123",
        }
    ) == "https://github.com/pathikrit/restfinder/actions/runs/123456"


def test_build_url_falls_back_to_the_exact_commit():
    assert build_url({}, sha="abc123") == "https://github.com/pathikrit/restfinder/commit/abc123"


def test_write_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    output = tmp_path / "build.json"

    write_metadata(output)

    assert json.loads(output.read_text()) == {
        "url": "https://github.com/pathikrit/restfinder/actions/runs/123456"
    }


def test_write_runtime_config(tmp_path):
    output = tmp_path / "config.json"
    write_runtime_config(
        output,
        {"GOOGLE_MAPS_BROWSER_KEY": "browser-key", "GOOGLE_MAP_ID": "map-id"},
    )

    assert json.loads(output.read_text()) == {
        "google_maps_browser_key": "browser-key",
        "google_map_id": "map-id",
    }
