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


def optional_environment(variable: str) -> str | None:
    load_environment()
    value = os.environ.get(variable, "").strip()
    return value or None


def required_environment(variable: str) -> str:
    value = optional_environment(variable)
    if not value:
        raise RuntimeError(f"{variable} is required")
    return value


def google_places_monthly_limit() -> int:
    value = optional_environment("GOOGLE_PLACES_MONTHLY_LIMIT") or "4500"
    limit = int(value)
    if limit < 1:
        raise RuntimeError("GOOGLE_PLACES_MONTHLY_LIMIT must be positive")
    return limit
