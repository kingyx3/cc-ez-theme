"""Reads the customer purchase limit configuration the way the theme does.

One configured limit is one `customer-order-limit-row` include carrying the
handle, the maximum, and the date the allowance is counted from. Tests parse the
rows rather than counting numbered slots, so adding a product to the storefront
stays a one-line change here too.
"""
from __future__ import annotations

import re
from pathlib import Path


CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "theme" / "snippets" / "customer-order-limit-config.liquid"
)

ROW = re.compile(
    r"\{% include 'customer-order-limit-row',"
    r" limit_handle: '(?P<handle>[^']*)',"
    r" limit_maximum: (?P<maximum>\d+)"
    r"(?:, limit_refresh: '(?P<refresh>[^']*)')? %\}"
)


def configured_rows(config: str | None = None) -> list[tuple[str, int, str]]:
    """Returns (handle, maximum, refresh) for every configured limit, in order."""
    if config is None:
        config = CONFIG_PATH.read_text(encoding="utf-8")
    return [
        (match.group("handle"), int(match.group("maximum")), match.group("refresh") or "")
        for match in ROW.finditer(config)
    ]


def row_liquid(handle: str, maximum: int, refresh: str = "") -> str:
    """The single row that adds or updates one limit."""
    return (
        "{% include 'customer-order-limit-row',"
        f" limit_handle: '{handle}', limit_maximum: {maximum},"
        f" limit_refresh: '{refresh}' %}}"
    )
