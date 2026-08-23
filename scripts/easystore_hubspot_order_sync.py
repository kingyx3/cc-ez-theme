#!/usr/bin/env python3
"""Production Order sync entrypoint with primary-Phone Contact identity."""

from __future__ import annotations

import easystore_hubspot_orders as orders
from easystore_hubspot_contact_identity import hubspot_contact_index


def main(argv: list[str] | None = None) -> int:
    # Keep the mapping implementation in easystore_hubspot_orders, but inject the
    # same authoritative Contact identity used by preflight/customer sync.
    orders.hubspot_contact_index = hubspot_contact_index
    return orders.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
