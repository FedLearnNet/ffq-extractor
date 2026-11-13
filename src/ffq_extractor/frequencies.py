"""Map FFQ Excel frequency headers to microbiome schema codes."""

from __future__ import annotations

from typing import FrozenSet, Optional

# Schema pattern: ^(?:<1\/M|[0-9]+\/[MW]|[1-5]\/D|6\+\/D)$
FREQUENCY_HEADER_TO_CODE = {
    "less than once a month": "<1/M",
    "once a month": "1/M",
    "once a week": "1/W",
    "twice a week": "2/W",
    "5 times a week": "5/W",
    "once a day": "1/D",
    "twice a day": "2/D",
    "4 times a day": "4/D",
    "6 or more times a day": "6+/D",
}

NEVER_HEADER = "never"

# Marks accepted as a selected frequency cell
ACCEPTED_MARKS: FrozenSet[str] = frozenset({"x", "1", "✓", "✔", "yes", "y"})


def normalize_header(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def frequency_code_for_header(header: object) -> Optional[str]:
    """Return schema frequency code, None for Never, raise for unknown headers."""
    key = normalize_header(header)
    if not key:
        return None
    if key == NEVER_HEADER:
        return None
    code = FREQUENCY_HEADER_TO_CODE.get(key)
    if code is None:
        raise ValueError(f"Unknown frequency header: {header!r}")
    return code


def is_accepted_mark(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    return text.lower() in ACCEPTED_MARKS or text in {"✓", "✔"}


def is_blank_cell(value: object) -> bool:
    if value is None:
        return True
    return str(value).strip() == ""
