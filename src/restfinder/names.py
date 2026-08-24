"""Restaurant name display formatting."""

from __future__ import annotations

import re

from titlecase import titlecase

ACRONYMS = (
    "ABC",
    "BBQ",
    "BLT",
    "BYOB",
    "DJ",
    "JG",
    "KFC",
    "LES",
    "LGBTQ",
    "LLC",
    "NY",
    "NYC",
    "S&P",
    "UK",
    "US",
    "USA",
    "VIP",
)
ACRONYM_PATTERN = re.compile(
    rf"(?<!\w)({'|'.join(re.escape(value) for value in ACRONYMS)})(?!\w)",
    re.IGNORECASE,
)
APOSTROPHE_PREFIX_PATTERN = re.compile(r"\b([dlo])(['’])([A-Z][A-Z]+)\b")


def display_name(value: str) -> str:
    """Return readable casing while preserving already-styled source names."""
    cleaned = " ".join(value.split())
    letters = [character for character in cleaned if character.isalpha()]
    if not letters:
        return cleaned
    uppercase_ratio = sum(character.isupper() for character in letters) / len(letters)
    if uppercase_ratio < 0.8:
        return cleaned

    formatted = titlecase(cleaned.upper())
    formatted = APOSTROPHE_PREFIX_PATTERN.sub(
        lambda match: f"{match[1].upper()}{match[2]}{match[3].capitalize()}",
        formatted,
    )
    return ACRONYM_PATTERN.sub(lambda match: match[0].upper(), formatted)
