"""Environment-backed configuration."""

from __future__ import annotations

import os

from dotenv import load_dotenv


def load_environment() -> None:
    """Load local values while preserving variables supplied by CI."""
    load_dotenv(override=False)


def database_url(variable: str = "DATABASE_URL") -> str:
    load_environment()
    value = os.environ.get(variable, "").strip()
    if not value:
        raise RuntimeError(f"{variable} is required")
    return value


def nyc_open_data_app_token() -> str | None:
    load_environment()
    return os.environ.get("NYC_OPEN_DATA_APP_TOKEN") or None
