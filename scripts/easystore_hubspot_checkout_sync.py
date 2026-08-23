#!/usr/bin/env python3
"""Production Checkout/Cart sync entrypoint with primary-Phone Contact identity."""

from __future__ import annotations

import easystore_hubspot_checkouts as checkouts
import easystore_hubspot_commerce as commerce
import easystore_hubspot_orders as orders
from easystore_hubspot_contact_identity import hubspot_contact_index


def main(argv: list[str] | None = None) -> int:
    # commerce imported the low-level Contact index by name, so patch both module
    # globals before the checkout entrypoint starts resolving Cart associations.
    orders.hubspot_contact_index = hubspot_contact_index
    commerce.hubspot_contact_index = hubspot_contact_index
    return checkouts.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
