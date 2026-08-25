"""Write immutable build metadata for links in the static site."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Mapping

from restfinder.config import load_environment


OUTPUT_PATH = Path(".site/build.json")
CONFIG_PATH = Path(".site/config.json")
DEFAULT_REPOSITORY = "pathikrit/restfinder"
DEFAULT_SERVER_URL = "https://github.com"


def current_sha() -> str:
    """Return the exact local commit used for a non-CI build."""
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
    ).strip()


def build_url(environment: Mapping[str, str], *, sha: str | None = None) -> str:
    """Return the immutable GitHub run URL, falling back to the exact commit."""
    server_url = environment.get("GITHUB_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")
    repository = environment.get("GITHUB_REPOSITORY", DEFAULT_REPOSITORY)
    run_id = environment.get("GITHUB_RUN_ID")
    if run_id:
        return f"{server_url}/{repository}/actions/runs/{run_id}"

    commit = environment.get("GITHUB_SHA") or sha or current_sha()
    return f"{server_url}/{repository}/commit/{commit}"


def write_metadata(path: Path = OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"url": build_url(os.environ)}, indent=2) + "\n",
        encoding="utf-8",
    )


def write_runtime_config(
    path: Path = CONFIG_PATH,
    environment: Mapping[str, str] | None = None,
) -> None:
    if environment is None:
        load_environment()
        environment = os.environ
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "google_maps_browser_key": environment.get("GOOGLE_MAPS_BROWSER_KEY", ""),
                "google_map_id": environment.get("GOOGLE_MAP_ID", ""),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    write_metadata()
    write_runtime_config()
    print(f"Wrote build metadata to {OUTPUT_PATH}.")


if __name__ == "__main__":
    main()
