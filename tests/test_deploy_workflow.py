from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_deploy_preflight_requires_database_and_google_configuration():
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
    deploy_job = workflow.split("\n  deploy:", maxsplit=1)[1]

    assert "Validate deployment configuration" in deploy_job
    for name in (
        "DATABASE_URL",
        "GOOGLE_PLACES_SERVER_KEY",
        "GOOGLE_MAPS_BROWSER_KEY",
        "GOOGLE_MAP_ID",
    ):
        assert f"{name}: ${{{{ secrets.{name} }}}}" in deploy_job
        assert name in deploy_job
    assert "Missing required deployment configuration" in deploy_job
